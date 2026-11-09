"""A2A client side: discover the reviewer agents and send them review tasks in parallel."""

import asyncio
import logging
import uuid
from typing import Any, Dict, List

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers import get_data_parts, get_message_text, new_data_part
from a2a.types.a2a_pb2 import Message, Role, SendMessageRequest, TaskState

from common.config import settings

log = logging.getLogger(__name__)

REVIEWERS: Dict[str, str] = {
    "code": settings.code_reviewer_url,
    "best_practice": settings.best_practice_reviewer_url,
    "security": settings.security_reviewer_url,
}


async def fetch_cards() -> List[Dict[str, Any]]:
    """Read each reviewer's Agent Card (A2A discovery)."""
    async with httpx.AsyncClient(timeout=5) as http:
        async def one(key: str, url: str) -> Dict[str, Any]:
            try:
                r = await http.get(f"{url}/.well-known/agent-card.json")
                r.raise_for_status()
                card = r.json()
                return {"key": key, "url": url, "online": True, "name": card.get("name"),
                        "description": card.get("description"),
                        "skills": [s.get("name") for s in card.get("skills", [])]}
            except Exception as e:
                return {"key": key, "url": url, "online": False, "error": str(e)}

        return list(await asyncio.gather(*(one(k, u) for k, u in REVIEWERS.items())))


async def send_review(key: str, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send one ReviewRequest to one reviewer and return its ReviewerResult (or an error)."""
    async with httpx.AsyncClient(timeout=settings.reviewer_timeout_s) as http:
        client = await create_client(url, client_config=ClientConfig(streaming=False, httpx_client=http))
        try:
            message = Message(
                message_id=str(uuid.uuid4()),
                role=Role.ROLE_USER,
                parts=[new_data_part(payload)],
            )
            task = None
            async for event in client.send_message(SendMessageRequest(message=message)):
                if event.HasField("task"):
                    task = event.task
                elif event.HasField("message"):
                    return {"ok": False, "error": get_message_text(event.message)}
            if task is None:
                return {"ok": False, "error": "no task returned"}

            state = TaskState.Name(task.status.state)
            if task.status.state != TaskState.TASK_STATE_COMPLETED:
                reason = get_message_text(task.status.message) if task.status.HasField("message") else ""
                return {"ok": False, "error": f"{state}: {reason}".strip(": ")}
            for artifact in task.artifacts:
                data = get_data_parts(artifact.parts)
                if data:
                    return {"ok": True, "result": data[0], "task_id": task.id}
            return {"ok": False, "error": "completed without a result artifact"}
        finally:
            await client.close()


async def review_with_all(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Fan out: all three reviewers work on the same push at the same time."""
    keys = list(REVIEWERS)
    results = await asyncio.gather(
        *(send_review(k, REVIEWERS[k], payload) for k in keys), return_exceptions=True
    )
    out = {}
    for key, res in zip(keys, results, strict=True):
        if isinstance(res, Exception):
            log.warning("reviewer %s failed: %s", key, res)
            out[key] = {"ok": False, "error": f"{type(res).__name__}: {res}"}
        else:
            out[key] = res
    return out
