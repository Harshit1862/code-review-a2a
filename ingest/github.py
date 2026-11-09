"""GitHub side of ingestion: verify webhook signatures and fetch each push's diff."""

import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from common.config import settings
from common.diffutils import added_lines
from common.timeutils import utcnow

ZERO_SHA = "0" * 40


def verify_signature(secret: str, body: bytes, signature_header: Optional[str]) -> bool:
    """GitHub sends X-Hub-Signature-256: sha256=<HMAC of the raw body with your secret>."""
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


class GitHubClient:
    def __init__(self, token: str, transport: Optional[httpx.AsyncBaseTransport] = None):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.AsyncClient(
            base_url=settings.github_api_url, headers=headers, timeout=30, transport=transport
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def compare(self, repo: str, base: str, head: str) -> Dict[str, Any]:
        r = await self._http.get(f"/repos/{repo}/compare/{base}...{head}")
        r.raise_for_status()
        return r.json()

    async def commit(self, repo: str, sha: str) -> Dict[str, Any]:
        r = await self._http.get(f"/repos/{repo}/commits/{sha}")
        r.raise_for_status()
        return r.json()

    async def file_content(self, repo: str, path: str, ref: str) -> Optional[str]:
        r = await self._http.get(
            f"/repos/{repo}/contents/{quote(path, safe='/')}",
            params={"ref": ref},
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        if r.status_code != 200:
            return None
        if len(r.content) > settings.max_file_bytes:
            return None
        return r.text


def _status(github_status: str) -> str:
    return {"added": "added", "removed": "removed", "renamed": "renamed"}.get(
        github_status, "modified"
    )


def _is_reviewable(path: str) -> bool:
    return os.path.splitext(path)[1] in settings.review_extensions


async def build_push_from_github(
    payload: Dict[str, Any], delivery_id: Optional[str], client: GitHubClient
) -> Dict[str, Any]:
    """Turn a GitHub push webhook payload into a push document (with diffs and file contents)."""
    repo_info = payload["repository"]
    repo = repo_info["full_name"]
    branch = payload["ref"].removeprefix("refs/heads/")
    default_branch = repo_info.get("default_branch")
    before, after = payload["before"], payload["after"]

    # Which diff to fetch?
    if before != ZERO_SHA:
        diff = await client.compare(repo, before, after)
        changed = diff.get("files", [])
    elif default_branch and branch != default_branch:
        # New branch: compare against the default branch
        diff = await client.compare(repo, default_branch, after)
        changed = diff.get("files", [])
    else:
        # First push to a new repo: only the head commit's diff is available
        changed = (await client.commit(repo, after)).get("files", [])

    files: List[Dict[str, Any]] = []
    for f in changed[: settings.max_files_per_push]:
        path = f["filename"]
        status = _status(f.get("status", "modified"))
        patch = f.get("patch")
        entry: Dict[str, Any] = {
            "path": path,
            "status": status,
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
            "patch": patch,
            "changed_lines": added_lines(patch or ""),
            "content": None,
        }
        if f.get("previous_filename"):
            entry["previous_path"] = f["previous_filename"]
        if status != "removed" and _is_reviewable(path):
            entry["content"] = await client.file_content(repo, path, after)
        files.append(entry)

    commits = [
        {
            "sha": c["id"],
            "message": c.get("message", ""),
            "author": (c.get("author") or {}).get("username")
            or (c.get("author") or {}).get("name", ""),
            "timestamp": c.get("timestamp"),
        }
        for c in payload.get("commits", [])
    ]

    pushed_at_raw = repo_info.get("pushed_at")
    pushed_at = (
        datetime.fromtimestamp(pushed_at_raw, tz=timezone.utc)
        if isinstance(pushed_at_raw, (int, float))
        else utcnow()
    )

    # Project-wide reviewer guidance, if the repo has one -- not a "changed file", so it's
    # fetched at HEAD regardless of whether this push touched it.
    review_prompt = await client.file_content(repo, "prompt.md", after)
    review_prompt = review_prompt.strip() if review_prompt else None

    return {
        "source": "github",
        "delivery_id": delivery_id,
        "project": repo_info["name"],
        "repo": repo,
        "default_branch": default_branch,
        "branch": branch,
        "pusher": (payload.get("pusher") or {}).get("name", ""),
        "pushed_at": pushed_at,
        "before_sha": before,
        "after_sha": after,
        "forced": bool(payload.get("forced")),
        "new_branch": bool(payload.get("created")),
        "compare_url": payload.get("compare"),
        "commits": commits,
        "files": files,
        "review_prompt": review_prompt,
    }
