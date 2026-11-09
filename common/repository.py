"""All database reads/writes live here. Ingest and orchestrator both use these functions,
so neither of them (nor the LLM) ever writes raw MongoDB queries."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from common.db import get_db, next_push_id
from common.timeutils import utcnow


def _clean(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if doc is not None:
        doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------- pushes (write)


async def delivery_seen(delivery_id: str) -> bool:
    if not delivery_id:
        return False
    return await get_db().pushes.find_one({"delivery_id": delivery_id}, {"_id": 1}) is not None


async def save_push(doc: Dict[str, Any]) -> Tuple[int, bool]:
    """Store a push. Returns (push_id, created). The same repo+branch+commit is stored once."""
    db = get_db()
    doc["dedupe_key"] = f"{doc['repo']}:{doc['branch']}:{doc['after_sha']}"

    existing = await db.pushes.find_one({"dedupe_key": doc["dedupe_key"]}, {"push_id": 1})
    if existing:
        return int(existing["push_id"]), False

    files = doc.get("files", [])
    doc["stats"] = {
        "files_changed": len(files),
        "additions": sum(f.get("additions", 0) for f in files),
        "deletions": sum(f.get("deletions", 0) for f in files),
        "reviewable_files": sum(1 for f in files if f.get("content")),
    }
    doc["commit_count"] = len(doc.get("commits", []))
    doc["review_status"] = "not_reviewed"
    doc["created_at"] = utcnow()
    doc["push_id"] = await next_push_id()
    try:
        await db.pushes.insert_one(doc)
    except DuplicateKeyError:
        # Two deliveries of the same push raced each other: return the stored one.
        existing = await db.pushes.find_one({"dedupe_key": doc["dedupe_key"]}, {"push_id": 1})
        return int(existing["push_id"]), False

    await db.projects.update_one(
        {"name": doc["project"]},
        {
            "$set": {
                "repo": doc["repo"],
                "default_branch": doc.get("default_branch"),
                "last_push_at": doc["pushed_at"],
                "last_push_id": doc["push_id"],
            },
            "$inc": {"push_count": 1},
            "$setOnInsert": {"created_at": utcnow()},
        },
        upsert=True,
    )
    return doc["push_id"], True


# ---------------------------------------------------------------- pushes (read)


def build_filter(
    project: Optional[str] = None,
    branch: Optional[str] = None,
    author: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    reviewed: Optional[bool] = None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if project:
        query["project"] = {"$regex": re.escape(project.strip()), "$options": "i"}
    if branch:
        query["branch"] = {"$regex": f"^{re.escape(branch.strip())}$", "$options": "i"}
    if author:
        pattern = {"$regex": re.escape(author.strip()), "$options": "i"}
        query["$or"] = [{"pusher": pattern}, {"commits.author": pattern}]
    if since or until:
        query["pushed_at"] = {}
        if since:
            query["pushed_at"]["$gte"] = since
        if until:
            query["pushed_at"]["$lt"] = until
    if reviewed is not None:
        query["review_status"] = "reviewed" if reviewed else "not_reviewed"
    return query


async def find_pushes(query: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
    cursor = (
        get_db()
        .pushes.find(query, {"files": 0, "_id": 0})
        .sort("pushed_at", DESCENDING)
        .limit(max(1, min(limit, 100)))
    )
    return [doc async for doc in cursor]


async def count_pushes(query: Dict[str, Any]) -> int:
    return await get_db().pushes.count_documents(query)


async def get_push(push_id: int, include_content: bool = False) -> Optional[Dict[str, Any]]:
    doc = _clean(await get_db().pushes.find_one({"push_id": int(push_id)}))
    if doc and not include_content:
        for f in doc.get("files", []):
            f.pop("content", None)
            f.pop("patch", None)
    return doc


async def latest_push_id() -> Optional[int]:
    doc = await get_db().pushes.find_one({}, {"push_id": 1}, sort=[("pushed_at", DESCENDING)])
    return int(doc["push_id"]) if doc else None


# ---------------------------------------------------------------- projects


async def list_projects() -> List[Dict[str, Any]]:
    cursor = get_db().projects.find({}, {"_id": 0}).sort("last_push_at", DESCENDING)
    return [doc async for doc in cursor]


# ---------------------------------------------------------------- reviews


async def save_review(review: Dict[str, Any]) -> None:
    db = get_db()
    await db.reviews.insert_one(dict(review))
    await db.pushes.update_one(
        {"push_id": review["push_id"]},
        {
            "$set": {
                "review_status": "reviewed",
                "latest_scores": review.get("scores", {}),
                "reviewed_at": review["created_at"],
            }
        },
    )


async def get_latest_review(push_id: int) -> Optional[Dict[str, Any]]:
    return _clean(
        await get_db().reviews.find_one(
            {"push_id": int(push_id)}, sort=[("created_at", DESCENDING)]
        )
    )
