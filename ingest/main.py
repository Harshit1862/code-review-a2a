"""Ingest service: stores every git push in MongoDB with a short numeric ID.

Run:  uvicorn ingest.main:app --port 8000
"""

import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common import db, repository
from common.config import settings
from common.timeutils import fmt_local
from ingest.github import GitHubClient, build_push_from_github, verify_signature
from ingest.local_git import GitError, build_push_from_local

log = logging.getLogger("ingest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def github_client_factory() -> GitHubClient:
    return GitHubClient(settings.github_token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.ensure_indexes()
    yield
    await db.close()


app = FastAPI(title="Push Ingest Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    await db.get_db().command("ping")
    return {"status": "ok", "dev_endpoints": settings.dev_endpoints}


# ------------------------------------------------------------------ GitHub webhook


async def process_github_push(payload: dict, delivery_id: Optional[str]) -> None:
    client = github_client_factory()
    try:
        doc = await build_push_from_github(payload, delivery_id, client)
        push_id, created = await repository.save_push(doc)
        log.info("push %s %s (%s %s@%s)", push_id, "stored" if created else "already stored",
                 doc["repo"], doc["branch"], doc["after_sha"][:7])
    except Exception:
        log.exception("failed to process push delivery %s", delivery_id)
    finally:
        await client.close()


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_github_event: Optional[str] = Header(default=None),
    x_github_delivery: Optional[str] = Header(default=None),
    x_hub_signature_256: Optional[str] = Header(default=None),
):
    body = await request.body()
    if not settings.github_webhook_secret:
        raise HTTPException(503, "GITHUB_WEBHOOK_SECRET is not configured")
    if not verify_signature(settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(401, "Invalid signature")

    if x_github_event == "ping":
        return {"ok": True, "message": "pong"}
    if x_github_event != "push":
        return JSONResponse({"ignored": True, "reason": f"event '{x_github_event}'"}, status_code=202)

    payload = json.loads(body)
    ref = payload.get("ref", "")
    if payload.get("deleted") or not ref.startswith("refs/heads/"):
        return JSONResponse({"ignored": True, "reason": "branch deletion or tag push"}, status_code=202)
    if await repository.delivery_seen(x_github_delivery):
        return {"duplicate": True, "delivery_id": x_github_delivery}

    # GitHub needs a reply within 10 seconds, so the slow part runs after we respond.
    background.add_task(process_github_push, payload, x_github_delivery)
    return JSONResponse({"accepted": True, "delivery_id": x_github_delivery}, status_code=202)


# ------------------------------------------------------------------ dev: local repo


class LocalIngestRequest(BaseModel):
    repo_path: str
    before: Optional[str] = None  # default: parent of `after`
    after: str = "HEAD"
    branch: Optional[str] = None  # default: current branch
    project: Optional[str] = None  # default: folder name


@app.post("/dev/ingest-local")
async def ingest_local(body: LocalIngestRequest):
    """Store a push built from a local git repo. Lets you test without GitHub."""
    if not settings.dev_endpoints:
        raise HTTPException(404, "Dev endpoints are disabled (set DEV_ENDPOINTS=true)")
    try:
        doc = await build_push_from_local(body.repo_path, body.before, body.after, body.branch, body.project)
    except GitError as e:
        raise HTTPException(400, str(e)) from e
    push_id, created = await repository.save_push(doc)
    return {
        "push_id": push_id,
        "created": created,
        "project": doc["project"],
        "branch": doc["branch"],
        "commits": len(doc["commits"]),
        "files": [f["path"] for f in doc["files"]],
    }


# ------------------------------------------------------------------ read APIs


def _summary(p: dict) -> dict:
    return {
        "push_id": p["push_id"],
        "project": p["project"],
        "branch": p["branch"],
        "pusher": p.get("pusher"),
        "pushed_at": fmt_local(p.get("pushed_at")),
        "commits": p.get("commit_count", 0),
        "files_changed": p.get("stats", {}).get("files_changed", 0),
        "review_status": p.get("review_status"),
        "latest_scores": p.get("latest_scores"),
    }


@app.get("/projects")
async def projects():
    return [
        {**p, "last_push_at": fmt_local(p.get("last_push_at")),
         "created_at": fmt_local(p.get("created_at"))}
        for p in await repository.list_projects()
    ]


@app.get("/pushes")
async def pushes(project: Optional[str] = None, branch: Optional[str] = None,
                 limit: int = Query(20, ge=1, le=100)):
    query = repository.build_filter(project=project, branch=branch)
    return [_summary(p) for p in await repository.find_pushes(query, limit)]


@app.get("/pushes/{push_id}")
async def push_detail(push_id: int, include_content: bool = False):
    push = await repository.get_push(push_id, include_content=include_content)
    if not push:
        raise HTTPException(404, f"Push {push_id} not found")
    for key in ("pushed_at", "created_at", "reviewed_at"):
        if push.get(key):
            push[key] = fmt_local(push[key])
    return push
