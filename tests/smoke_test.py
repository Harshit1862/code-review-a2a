"""End-to-end smoke test against the running services.

    python -m tests.smoke_test                 # creates a demo git repo with buggy code
    python -m tests.smoke_test --repo ~/myrepo # or uses your own repo (last commit)

Needs: ingest on :8000, orchestrator on :8001, the three reviewers on :10001-10003,
and DEV_ENDPOINTS=true.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import textwrap

import httpx

CLEAN = '''\
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
'''

BUGGY = '''\
import hashlib
import pickle
import subprocess

API_KEY = "sk-live-1234567890abcdef"


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def load_user(data):
    return pickle.loads(data)


def run(cmd):
    return subprocess.call(cmd, shell=True)


def average(nums):
    try:
        return sum(nums) / len(nums)
    except:
        print("error")


def hash_password(pw):
    return hashlib.md5(pw.encode()).hexdigest()


def find(items, x):
    for i in range(len(items)):
        if items[i] == x:
            return i
'''


def make_demo_repo() -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="demo_"), "demo-shop")
    os.makedirs(path)

    def git(*args):
        return subprocess.run(["git", "-C", path, *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "Demo Dev")
    git("config", "user.email", "demo@example.com")
    with open(os.path.join(path, "utils.py"), "w") as f:
        f.write(CLEAN)
    git("add", ".")
    git("commit", "-m", "Add math utils")
    with open(os.path.join(path, "utils.py"), "w") as f:
        f.write(BUGGY)
    git("add", ".")
    git("commit", "-m", "Add user loading, command runner and password hashing")
    return path


def show(title: str, text: str) -> None:
    print(f"\n=== {title} ===\n{textwrap.indent(str(text), '  ')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", default="http://localhost:8000")
    ap.add_argument("--orch", default="http://localhost:8001")
    ap.add_argument("--repo", help="local git repo to ingest (default: create a demo repo)")
    args = ap.parse_args()

    with httpx.Client(timeout=300) as http:
        http.get(f"{args.ingest}/health").raise_for_status()
        http.get(f"{args.orch}/health").raise_for_status()

        agents = http.get(f"{args.orch}/agents").json()
        show("Reviewer agents (A2A cards)", "\n".join(
            f"{a['key']}: {'online' if a['online'] else 'OFFLINE'} {a.get('name') or a.get('error')}"
            for a in agents))
        if not all(a["online"] for a in agents):
            print("Start all three reviewers first.")
            return 1

        repo = args.repo or make_demo_repo()
        r = http.post(f"{args.ingest}/dev/ingest-local", json={"repo_path": repo})
        r.raise_for_status()
        push = r.json()
        show("Stored push", push)
        push_id = push["push_id"]

        thread = None
        for question in [
            "Is there any update today?",
            f"How many pushes for {push['project']} today?",
            "Score the latest one",
            f"What was the score for push #{push_id}?",
        ]:
            r = http.post(f"{args.orch}/chat", json={"message": question, "thread_id": thread})
            r.raise_for_status()
            data = r.json()
            thread = data["thread_id"]
            show(f"You: {question}   (tools: {', '.join(data['tools_used']) or 'none'})", data["reply"])

        review = http.get(f"{args.orch}/reviews/{push_id}").json()
        show("Saved scores", {k: f"{v:g}/10" for k, v in review["scores"].items()})
        for key, result in review["results"].items():
            show(f"{key} report", result["report"])
    print("\nSmoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
