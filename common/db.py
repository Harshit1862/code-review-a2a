"""MongoDB connection, indexes and the push ID counter."""

from typing import Optional

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from common.config import settings

_client: Optional[AsyncMongoClient] = None


def get_db() -> AsyncDatabase:
    global _client
    if _client is None:
        # tz_aware=True: datetimes come back as timezone-aware UTC
        _client = AsyncMongoClient(settings.mongo_uri, tz_aware=True)
    return _client[settings.mongo_db]


async def ensure_indexes() -> None:
    db = get_db()
    await db.pushes.create_index([("push_id", ASCENDING)], unique=True)
    await db.pushes.create_index([("dedupe_key", ASCENDING)], unique=True)
    await db.pushes.create_index([("delivery_id", ASCENDING)])
    await db.pushes.create_index([("project", ASCENDING), ("pushed_at", DESCENDING)])
    await db.pushes.create_index([("pushed_at", DESCENDING)])
    await db.reviews.create_index([("push_id", ASCENDING), ("created_at", DESCENDING)])
    await db.projects.create_index([("name", ASCENDING)], unique=True)


async def next_push_id() -> int:
    """Atomic counter: 1, 2, 3 ... (short IDs that are easy to say in chat)."""
    db = get_db()
    doc = await db.counters.find_one_and_update(
        {"_id": "push_id"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
