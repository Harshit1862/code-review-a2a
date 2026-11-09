"""Runs a review for one push: load from DB -> 3 agents over A2A -> save scores."""

from typing import Any, Dict

from common import repository
from common.config import settings
from common.schemas import ReviewRequest
from common.timeutils import fmt_local, utcnow
from orchestrator.a2a_client import REVIEWERS, review_with_all, send_review

LABELS = {"code": "Code quality", "best_practice": "Best practices", "security": "Security"}


def _int(value):
    # A2A data parts store numbers as floats (protobuf Value); turn 7.0 back into 7
    return int(value) if isinstance(value, float) and value.is_integer() else value


async def _load_reviewable(push_id: int) -> Dict[str, Any]:
    """Load a push and build the ReviewRequest every reviewer expects, or an error dict."""
    push = await repository.get_push(push_id, include_content=True)
    if not push:
        return {"error": f"Push {push_id} not found"}

    reviewable = [f for f in push.get("files", []) if f.get("content")]
    if not reviewable:
        return {"push_id": push_id, "error": "This push has no reviewable files "
                f"(extensions: {', '.join(settings.review_extensions)})."}

    request = ReviewRequest(
        push_id=push_id,
        project=push["project"],
        branch=push.get("branch"),
        commit_messages=[c.get("message", "") for c in push.get("commits", [])],
        files=reviewable,
        extra_instructions=push.get("review_prompt"),
    )
    return {"push": push, "request": request}


async def run_single_review(push_id: int, agent_key: str) -> Dict[str, Any]:
    """Talk to exactly one reviewer agent (agent_key: 'code' | 'best_practice' | 'security')
    about one push. Does not touch the combined 3-agent review stored by run_review."""
    if agent_key not in REVIEWERS:
        return {"error": f"Unknown agent '{agent_key}'. Choose one of: {', '.join(REVIEWERS)}"}

    loaded = await _load_reviewable(push_id)
    if "request" not in loaded:
        return loaded

    res = await send_review(agent_key, REVIEWERS[agent_key], loaded["request"].model_dump())
    if not res.get("ok"):
        return {"push_id": push_id, "agent": agent_key, "error": res.get("error", "unknown error")}

    result = res["result"]
    for f in result.get("findings", []):
        f["line"] = _int(f.get("line"))
    for k in ("files_reviewed", "changed_lines"):
        result[k] = _int(result.get(k))
    result["severity_counts"] = {s: _int(n) for s, n in result.get("severity_counts", {}).items()}
    return {
        "push_id": push_id,
        "project": loaded["push"]["project"],
        "agent": agent_key,
        "label": LABELS[agent_key],
        "result": result,
    }


async def run_review(push_id: int, force: bool = False) -> Dict[str, Any]:
    if not force:
        existing = await repository.get_latest_review(push_id)
        if existing:
            existing["cached"] = True
            existing["created_at"] = fmt_local(existing.get("created_at"))
            return existing

    loaded = await _load_reviewable(push_id)
    if "request" not in loaded:
        return loaded
    push, request = loaded["push"], loaded["request"]

    raw = await review_with_all(request.model_dump())

    results, scores, errors = {}, {}, {}
    for key, res in raw.items():
        if res.get("ok"):
            result = res["result"]
            for f in result.get("findings", []):
                f["line"] = _int(f.get("line"))
            for k in ("files_reviewed", "changed_lines"):
                result[k] = _int(result.get(k))
            result["severity_counts"] = {s: _int(n) for s, n in result.get("severity_counts", {}).items()}
            results[key] = result
            scores[key] = result["score"]
        else:
            errors[key] = res.get("error", "unknown error")

    review = {
        "push_id": push_id,
        "project": push["project"],
        "branch": push.get("branch"),
        "created_at": utcnow(),
        "status": "complete" if not errors else ("partial" if results else "failed"),
        "scores": scores,
        "overall": round(sum(scores.values()) / len(scores), 1) if scores else None,
        "results": results,
        "errors": errors,
    }
    if results:
        await repository.save_review(review)
    review.pop("_id", None)
    review["created_at"] = fmt_local(review["created_at"])
    review["cached"] = False
    return review


def compact_review(review: Dict[str, Any], max_findings: int = 4) -> Dict[str, Any]:
    """Short version for the chat LLM (keeps tokens low)."""
    if "error" in review:
        return review
    out = {
        "push_id": review["push_id"],
        "project": review.get("project"),
        "reviewed_at": review.get("created_at"),
        "cached": review.get("cached", False),
        "status": review.get("status"),
        "scores": {},
    }
    for key, label in LABELS.items():
        result = review.get("results", {}).get(key)
        if not result:
            out["scores"][label] = {"score": None, "error": review.get("errors", {}).get(key)}
            continue
        out["scores"][label] = {
            "score": f"{result['score']:g}/10",
            "summary": result.get("summary"),
            "how_scored": result.get("score_breakdown"),
            "top_findings": [
                f"[{f['severity']}] {f['file']}:{f.get('line') or '?'} {f['title']}"
                for f in result.get("findings", [])[:max_findings]
            ],
        }
    return out
