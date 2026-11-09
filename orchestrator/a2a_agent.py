"""Exposes the orchestrator itself as a 4th A2A agent (same brain as POST /chat).

A2A request (text part = plain English message)
  -> run the orchestrator's LangGraph tool-calling agent
  -> A2A agent message (text part = reply)
"""

import logging

from a2a.helpers import get_message_text, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from langchain_core.messages import AIMessage, HumanMessage

from common.config import settings

log = logging.getLogger(__name__)


def make_orchestrator_card(port: int) -> AgentCard:
    url = f"http://{settings.reviewer_host}:{port}"
    return AgentCard(
        name="Code Review Orchestrator",
        description="Chat about tracked git pushes in plain English, or trigger a review by the "
                    "three specialist agents (code quality, best practices, security).",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="chat",
                name="Chat about pushes and reviews",
                description="Ask about tracked pushes, review a push, or get saved scores.",
                tags=["code-review", "orchestration"],
                examples=["any updates on athena today?", "score push 3",
                         "what was the score for #12?"],
            )
        ],
    )


class OrchestratorExecutor(AgentExecutor):
    def __init__(self, graph):
        self.graph = graph  # compiled LangGraph graph (same one POST /chat uses)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        text = get_message_text(context.message)
        if not text:
            await updater.reject(updater.new_agent_message(
                [new_text_part("Expected a text message, e.g. \"score push 3\".")]))
            return

        await updater.start_work(updater.new_agent_message([new_text_part("thinking...")]))

        # Each A2A context_id gets its own chat thread, so a caller can keep
        # sending follow-ups in the same context and get continued memory.
        config = {"configurable": {"thread_id": task.context_id}, "recursion_limit": 16}
        try:
            state = await self.graph.ainvoke({"messages": [HumanMessage(content=text)]}, config)
        except Exception as e:  # report the failure to the caller instead of crashing
            log.exception("orchestrator chat failed")
            await updater.failed(updater.new_agent_message(
                [new_text_part(f"orchestrator failed: {type(e).__name__}: {e}")]))
            return

        reply = next((m.content for m in reversed(state["messages"])
                     if isinstance(m, AIMessage) and m.content), "")
        await updater.complete(updater.new_agent_message([new_text_part(str(reply))]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()
