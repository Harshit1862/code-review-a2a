"""The bridge between A2A and LangGraph, shared by all three reviewers.

A2A request (data part = ReviewRequest JSON)
  -> run the reviewer's LangGraph graph
  -> A2A artifact (data part = ReviewerResult JSON) + task state COMPLETED
"""

import logging

from a2a.helpers import get_data_parts, new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from pydantic import ValidationError

from common.schemas import ReviewRequest

log = logging.getLogger(__name__)


class ReviewerExecutor(AgentExecutor):
    def __init__(self, graph, reviewer_name: str):
        self.graph = graph  # compiled LangGraph graph
        self.reviewer_name = reviewer_name

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # 1. Read the ReviewRequest from the message's data part
        data = get_data_parts(context.message.parts)
        if not data:
            await updater.reject(updater.new_agent_message(
                [new_text_part("Expected a data part containing a ReviewRequest JSON object.")]))
            return
        try:
            request = ReviewRequest.model_validate(data[0])
        except ValidationError as e:
            await updater.reject(updater.new_agent_message(
                [new_text_part(f"Invalid ReviewRequest: {e.errors()[:3]}")]))
            return

        reviewable = [f for f in request.files if f.content]
        await updater.start_work(updater.new_agent_message(
            [new_text_part(f"{self.reviewer_name}: reviewing {len(reviewable)} file(s) "
                           f"of push {request.push_id}")]))

        # 2. Run the LangGraph graph
        try:
            state = await self.graph.ainvoke({"request": request.model_dump()})
            result = state["result"]
        except Exception as e:  # report the failure to the caller instead of crashing
            log.exception("review failed")
            await updater.failed(updater.new_agent_message(
                [new_text_part(f"{self.reviewer_name} failed: {type(e).__name__}: {e}")]))
            return

        # 3. Return the result as an artifact and finish the task
        await updater.add_artifact([new_data_part(result)], name="review_result")
        await updater.complete(updater.new_agent_message(
            [new_text_part(f"{self.reviewer_name} score: {result['score']}/10")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()
