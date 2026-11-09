"""Build a push document from a local git repository (dev/testing without GitHub)."""

import asyncio
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from common.config import settings
from common.diffutils import added_lines
from common.timeutils import utcnow

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
STATUS = {"A": "added", "M": "modified", "D": "removed", "T": "modified"}


class GitError(RuntimeError):
    pass


def _git(repo: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, timeout=60
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _repo_slug(repo_path: str, name: str) -> str:
    url = _git(repo_path, "config", "--get", "remote.origin.url", check=False).strip()
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return match.group(1) if match else f"local/{name}"


def _build(repo_path: str, before: Optional[str], after: str, branch: Optional[str],
           project: Optional[str]) -> Dict[str, Any]:
    repo_path = os.path.abspath(os.path.expanduser(repo_path))
    if not os.path.isdir(repo_path):
        raise GitError(f"Folder not found: {repo_path}")
    top = _git(repo_path, "rev-parse", "--show-toplevel").strip()
    name = project or os.path.basename(top)
    after_sha = _git(top, "rev-parse", after).strip()

    if not before:
        has_parent = _git(top, "rev-parse", "--verify", "--quiet", f"{after_sha}~1", check=False).strip()
        before_sha = has_parent or EMPTY_TREE
    else:
        before_sha = _git(top, "rev-parse", before).strip()

    # Commits in the range
    log_range = [after_sha, "--max-count=50"] if before_sha == EMPTY_TREE else [f"{before_sha}..{after_sha}"]
    log = _git(top, "log", "--format=%H%x1f%an%x1f%aI%x1f%s%x1e", *log_range)
    commits = []
    for rec in log.strip("\x1e\n").split("\x1e"):
        rec = rec.strip()
        if not rec:
            continue
        sha, author, ts, msg = rec.split("\x1f")
        commits.append({"sha": sha, "author": author, "timestamp": ts, "message": msg})

    # Changed files (renames are shown as delete + add to keep this simple)
    statuses = {}
    for line in _git(top, "diff", "--name-status", "--no-renames", before_sha, after_sha).splitlines():
        code, path = line.split("\t", 1)
        statuses[path] = STATUS.get(code[0], "modified")
    counts = {}
    for line in _git(top, "diff", "--numstat", "--no-renames", before_sha, after_sha).splitlines():
        add, delete, path = line.split("\t", 2)
        counts[path] = (int(add) if add.isdigit() else 0, int(delete) if delete.isdigit() else 0)

    files: List[Dict[str, Any]] = []
    for path, status in list(statuses.items())[: settings.max_files_per_push]:
        additions, deletions = counts.get(path, (0, 0))
        reviewable = status != "removed" and os.path.splitext(path)[1] in settings.review_extensions
        patch = _git(top, "diff", "-U3", "--no-renames", before_sha, after_sha, "--", path) if reviewable else None
        content = None
        if reviewable:
            content = _git(top, "show", f"{after_sha}:{path}", check=False)
            if len(content.encode()) > settings.max_file_bytes:
                content = None
        files.append({
            "path": path,
            "status": status,
            "additions": additions,
            "deletions": deletions,
            "patch": patch,
            "changed_lines": added_lines(patch or ""),
            "content": content,
        })

    current_branch = _git(top, "rev-parse", "--abbrev-ref", "HEAD").strip()
    # Project-wide reviewer guidance, if the repo has one -- not a "changed file", so it's
    # fetched at HEAD regardless of whether this push touched it.
    review_prompt = _git(top, "show", f"{after_sha}:prompt.md", check=False).strip() or None
    return {
        "source": "local",
        "delivery_id": None,
        "project": name,
        "repo": _repo_slug(top, name),
        "default_branch": None,
        "branch": branch or current_branch,
        "pusher": _git(top, "config", "user.name", check=False).strip() or "local",
        "pushed_at": utcnow(),
        "before_sha": before_sha,
        "after_sha": after_sha,
        "forced": False,
        "new_branch": before_sha == EMPTY_TREE,
        "compare_url": None,
        "commits": commits,
        "files": files,
        "review_prompt": review_prompt,
    }


async def build_push_from_local(repo_path: str, before: Optional[str] = None, after: str = "HEAD",
                                branch: Optional[str] = None, project: Optional[str] = None) -> Dict[str, Any]:
    return await asyncio.to_thread(_build, repo_path, before, after, branch, project)
