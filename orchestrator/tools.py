"""Tools the orchestrator LLM can call. The LLM only fills in typed parameters;
the queries themselves are fixed code in common/repository.py."""

import json
from typing import Literal, Optional

from langchain_core.tools import tool

from common import repository
from common.timeutils import fmt_local, parse_dt, resolve_period
from orchestrator.review_service import compact_review, run_review

Period = Literal["today", "yesterday", "last_24_hours", "last_7_days", "this_week", "this_month"]


def _json(data) -> str:
    return json.dumps(data, default=str, ensure_ascii=False)


def _time_range(period, since, until):
    if period:
        return resolve_period(period)
    return (parse_dt(since) if since else None, parse_dt(until) if until else None)


def _push_line(p: dict) -> dict:
    return {
        "push_id": p["push_id"],
        "project": p["project"],
        "branch": p["branch"],
        "pusher": p.get("pusher"),
        "pushed_at": fmt_local(p.get("pushed_at")),
        "commits": p.get("commit_count", 0),
        "files_changed": p.get("stats", {}).get("files_changed", 0),
        "first_commit_message": (p.get("commits") or [{}])[0].get("message", "")[:100],
        "review_status": p.get("review_status"),
        "scores": p.get("latest_scores"),
    }


@tool
async def list_projects() -> str:
    """List all tracked projects (repos) with their push counts and last push time."""
    projects = await repository.list_projects()
    return _json([
        {"project": p["name"], "repo": p.get("repo"), "pushes": p.get("push_count", 0),
         "last_push_at": fmt_local(p.get("last_push_at")), "last_push_id": p.get("last_push_id")}
        for p in projects
    ] or "No projects yet. No pushes have been stored.")


@tool
async def search_pushes(
    project: Optional[str] = None,
    branch: Optional[str] = None,
    author: Optional[str] = None,
    period: Optional[Period] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    reviewed: Optional[bool] = None,
    limit: int = 10,
) -> str:
    """Find stored git pushes, newest first. Use this for "any updates?", "recent pushes",
    "what did X push today", etc.

    Args:
        project: project/repo name (partial, case-insensitive)
        branch: exact branch name
        author: pusher or commit author name (partial)
        period: named time range; prefer this for today/yesterday/this week
        since: ISO date or datetime (local time) - start of range, used if period is not set
        until: ISO date or datetime (local time) - end of range (exclusive)
        reviewed: True = only reviewed pushes, False = only not-yet-reviewed pushes
        limit: max results (1-50)
    """
    start, end = _time_range(period, since, until)
    query = repository.build_filter(project, branch, author, start, end, reviewed)
    pushes = await repository.find_pushes(query, min(max(limit, 1), 50))
    total = await repository.count_pushes(query)
    return _json({"total_matching": total, "showing": len(pushes),
                  "pushes": [_push_line(p) for p in pushes]})


@tool
async def count_pushes(
    project: Optional[str] = None,
    branch: Optional[str] = None,
    author: Optional[str] = None,
    period: Optional[Period] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    reviewed: Optional[bool] = None,
) -> str:
    """Count stored pushes matching the filters (same filters as search_pushes)."""
    start, end = _time_range(period, since, until)
    query = repository.build_filter(project, branch, author, start, end, reviewed)
    return _json({"count": await repository.count_pushes(query),
                  "range": {"since": fmt_local(start), "until": fmt_local(end)}})


@tool
async def get_push_details(push_id: int) -> str:
    """Show one push in detail: commits and changed files with line counts."""
    push = await repository.get_push(push_id)
    if not push:
        return _json({"error": f"Push {push_id} not found"})
    return _json({
        **_push_line(push),
        "repo": push.get("repo"),
        "commit_range": f"{push['before_sha'][:7]}..{push['after_sha'][:7]}",
        "forced": push.get("forced"),
        "commit_list": [f"{c['sha'][:7]} {c.get('author', '')}: {c.get('message', '')[:120]}"
                        for c in push.get("commits", [])[:20]],
        "files": [f"{f['status']} {f['path']} (+{f.get('additions', 0)}/-{f.get('deletions', 0)})"
                  for f in push.get("files", [])[:50]],
    })


@tool
async def review_push(push_id: int, force: bool = False) -> str:
    """Score a push with the three reviewer agents (code quality, best practices, security).
    Each returns a separate score out of 10 with a short report. If the push was already
    reviewed, the saved review is returned unless force=True (re-run)."""
    return _json(compact_review(await run_review(push_id, force=force)))


@tool
async def get_review(push_id: int) -> str:
    """Get the saved review (scores and reports) of a push without re-running the agents."""
    review = await repository.get_latest_review(push_id)
    if not review:
        return _json({"push_id": push_id, "message": "This push has not been reviewed yet."})
    review["created_at"] = fmt_local(review.get("created_at"))
    review["cached"] = True
    return _json(compact_review(review))


TOOLS = [list_projects, search_pushes, count_pushes, get_push_details, review_push, get_review]
