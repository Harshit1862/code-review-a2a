"""Orchestrator API: chat with the agent in plain English, or call reviews directly.

Run:  uvicorn orchestrator.main:app --port 8001
"""

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Literal, Optional

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import add_a2a_routes_to_fastapi, create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI, HTTPException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from common import db, repository
from common.timeutils import fmt_local
from orchestrator.a2a_agent import OrchestratorExecutor, make_orchestrator_card
from orchestrator.a2a_client import fetch_cards
from orchestrator.graph import build_graph
from orchestrator.review_service import run_review, run_single_review

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PORT = 8001


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.ensure_indexes()
    # InMemorySaver keeps chat memory per thread_id until the server restarts
    graph = build_graph(InMemorySaver())
    app.state.graph = graph

    # Also expose the orchestrator itself as a 4th A2A agent (agent card +
    # JSON-RPC), so it can be called standalone, the same way the 3 reviewers are.
    card = make_orchestrator_card(PORT)
    handler = DefaultRequestHandler(
        agent_executor=OrchestratorExecutor(graph),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
    )
    yield
    await db.close()


app = FastAPI(title="Code Review Orchestrator", version="1.0.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None  # reuse it to continue the same conversation


class ChatResponse(BaseModel):
    thread_id: str
    reply: str
    tools_used: list


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    thread_id = body.thread_id or uuid.uuid4().hex[:12]
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 16}
    state = await app.state.graph.ainvoke({"messages": [HumanMessage(content=body.message)]}, config)

    messages = state["messages"]
    last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    tools_used = [m.name for m in messages[last_human:] if isinstance(m, ToolMessage)]
    reply = next((m.content for m in reversed(messages) if isinstance(m, AIMessage) and m.content), "")
    return ChatResponse(thread_id=thread_id, reply=str(reply), tools_used=tools_used)


@app.post("/pushes/{push_id}/review")
async def review(push_id: int, force: bool = False):
    """Run the three reviewers directly (no chat). Returns full reports."""
    result = await run_review(push_id, force=force)
    if result.get("error") and "not found" in result["error"]:
        raise HTTPException(404, result["error"])
    return result


@app.post("/pushes/{push_id}/review/{agent}")
async def review_single(push_id: int, agent: Literal["code", "best_practice", "security"]):
    """Talk to exactly one reviewer agent about one push (no orchestrator fan-out,
    no interaction with the other two agents, result is not cached)."""
    result = await run_single_review(push_id, agent)
    if result.get("error") and "not found" in result["error"]:
        raise HTTPException(404, result["error"])
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@app.get("/reviews/{push_id}")
async def get_review(push_id: int):
    review = await repository.get_latest_review(push_id)
    if not review:
        raise HTTPException(404, f"Push {push_id} has not been reviewed yet")
    review["created_at"] = fmt_local(review.get("created_at"))
    return review


@app.get("/agents")
async def agents():
    """A2A discovery: shows each reviewer's Agent Card and whether it is online."""
    return await fetch_cards()


@app.get("/health")
async def health():
    await db.get_db().command("ping")
    return {"status": "ok"}
