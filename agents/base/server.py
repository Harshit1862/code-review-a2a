"""Builds the A2A server (Agent Card + JSON-RPC endpoint) for a reviewer."""

import logging
from typing import List

import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from starlette.applications import Starlette

from agents.base.executor import ReviewerExecutor
from common.config import settings


def make_agent_card(*, name: str, description: str, port: int, skill_id: str, skill_name: str,
                    skill_description: str, tags: List[str], examples: List[str]) -> AgentCard:
    url = f"http://{settings.reviewer_host}:{port}"
    return AgentCard(
        name=name,
        description=description,
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(id=skill_id, name=skill_name, description=skill_description,
                       tags=tags, examples=examples)
        ],
    )


def build_app(card: AgentCard, graph, reviewer_name: str) -> Starlette:
    handler = DefaultRequestHandler(
        agent_executor=ReviewerExecutor(graph, reviewer_name),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(handler, rpc_url="/")
    return Starlette(routes=routes)


def serve(card: AgentCard, graph, reviewer_name: str, port: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = build_app(card, graph, reviewer_name)
    print(f"{reviewer_name} running at http://{settings.reviewer_host}:{port} "
          f"(card: /.well-known/agent-card.json)")
    uvicorn.run(app, host=settings.reviewer_host, port=port, log_level="info")
