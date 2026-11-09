# Code Review A2A

Every `git push` is stored in MongoDB with a short ID. You then chat with an **orchestrator agent**
in plain English ("any updates on athena today?", "score the latest one"), and it asks **three
reviewer agents over A2A** for **separate scores out of 10**, each with its own report.

Backend only: FastAPI + LangGraph + A2A (`a2a-sdk` 1.3.0) + MongoDB + Groq.

```
 GitHub push ──webhook──▶ Ingest service :8000 ──▶ MongoDB (projects, pushes, reviews)
                                                        ▲
 You ──POST /chat──▶ Orchestrator agent :8001 ──────────┘  (tools query the DB)
                          │  A2A (JSON-RPC), in parallel
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
   Code reviewer  Best practice  Security reviewer
   :10001 (LLM)   :10002 (LLM)   :10003 (LLM)
```

## Project structure

```
common/            shared code
  config.py        settings from .env
  schemas.py       ReviewRequest / Finding / ReviewerResult (the contracts between services)
  db.py            MongoDB connection, indexes, push-ID counter
  repository.py    every DB query (the LLM never writes queries)
  scoring.py       severity counting/ordering helpers (the score itself comes from the LLM)
  diffutils.py     changed-line numbers from a unified diff
  timeutils.py     "today", "this week" -> UTC ranges
  llm.py           Groq chat model (or the offline fake)
ingest/
  main.py          FastAPI: GitHub webhook, dev local-repo ingest, read APIs
  github.py        signature check + diff/content fetch from the GitHub API
  local_git.py     build a push from a local repo (testing without GitHub)
agents/
  base/            shared A2A server, A2A<->LangGraph executor, prompt/scoring helpers
  code_reviewer/            graph.py + __main__.py   (llm_review -> finalize, fully LLM-powered)
  best_practice_reviewer/   graph.py + __main__.py   (llm_review -> finalize, fully LLM-powered)
  security_reviewer/        graph.py + __main__.py   (llm_review -> finalize, fully LLM-powered)
orchestrator/
  main.py          FastAPI: /chat, direct review, agents status
  graph.py         LangGraph tool-calling agent with per-thread memory
  tools.py         the 6 tools the agent can call
  a2a_client.py    Agent Card discovery + parallel A2A calls
  review_service.py  load push -> 3 agents -> save scores
tests/
  smoke_test.py    end-to-end test against the running services
  fake_llm.py      offline LLM for LLM_PROVIDER=fake
run_all.sh         starts all 5 services
```

## Setup

Needs Python 3.10+, git, and MongoDB.

```bash
cd code-review-a2a
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in GROQ_API_KEY, GROQ_MODEL, etc.

# MongoDB, if not already running:
docker run -d --name mongo -p 27017:27017 -v mongo_data:/data/db mongo
```

## Run

```bash
./run_all.sh
```

This starts the three reviewers (10001-10003), the ingest service (8000) and the orchestrator (8001).
Logs go to `logs/`. Swagger UIs: http://localhost:8000/docs and http://localhost:8001/docs

Or run each in its own terminal:

```bash
python -m agents.code_reviewer
python -m agents.best_practice_reviewer
python -m agents.security_reviewer
uvicorn ingest.main:app --port 8000
uvicorn orchestrator.main:app --port 8001
```

## Test it (no GitHub needed)

**One command:** creates a demo repo with buggy code, stores the push, chats, and prints the three reports:

```bash
python -m tests.smoke_test
python -m tests.smoke_test --repo ~/Projects_/some-repo   # or use your own repo's last commit
```

**By hand with curl:**

```bash
# 1. Store a push from a local repo (last commit by default; needs DEV_ENDPOINTS=true)
curl -X POST localhost:8000/dev/ingest-local -H 'Content-Type: application/json' \
  -d '{"repo_path": "/home/you/Projects_/athena"}'
# optional fields: "before": "<sha>", "after": "HEAD", "branch": "main", "project": "athena"

# 2. Chat. Keep the returned thread_id to continue the same conversation.
curl -X POST localhost:8001/chat -H 'Content-Type: application/json' \
  -d '{"message": "Is there any update on athena today?"}'

curl -X POST localhost:8001/chat -H 'Content-Type: application/json' \
  -d '{"message": "Score the latest one", "thread_id": "<thread_id from above>"}'

# 3. Or skip the chat and review directly (full reports in the response)
curl -X POST localhost:8001/pushes/1/review
curl -X POST 'localhost:8001/pushes/1/review?force=true'   # re-run instead of returning the saved one
curl localhost:8001/reviews/1
```

Things you can ask the orchestrator:

- "any updates today?" / "recent pushes on athena" / "what did Harshit push this week?"
- "how many pushes yesterday?" / "how many unreviewed pushes on main?"
- "what changed in push #12?"
- "score it" / "review push #12" / "review it again"
- "what was the score for #12?" / "which projects do you track?"

## Connect GitHub

1. Create a channel at https://smee.io and put the URL in `.env` as `SMEE_URL`.
2. Forward it to the ingest service (leave this running):
   ```bash
   npm install -g smee-client
   smee -u https://smee.io/<your-channel> -t http://localhost:8000/webhooks/github
   ```
3. In your GitHub repo: **Settings → Webhooks → Add webhook**
   - Payload URL: your smee URL
   - Content type: `application/json`
   - Secret: the same value as `GITHUB_WEBHOOK_SECRET`
   - Events: **Just the push event**
4. GitHub sends a `ping` first (the ingest service answers `pong`). Push a commit, then:
   `curl localhost:8000/pushes`

The webhook returns `202` immediately and fetches the diff in the background, because GitHub expects a
reply within 10 seconds. A redelivered webhook or a re-push of the same commit is stored only once.

## API reference

| Service | Method & path | What it does |
|---|---|---|
| Ingest :8000 | `POST /webhooks/github` | GitHub push webhook (HMAC-verified) |
| | `POST /dev/ingest-local` | Store a push from a local repo (dev only) |
| | `GET /pushes?project=&branch=&limit=` | List stored pushes |
| | `GET /pushes/{id}?include_content=false` | One push with commits and files |
| | `GET /projects` | Tracked projects |
| Orchestrator :8001 | `POST /chat` `{message, thread_id?}` | Talk to the agent |
| | `POST /pushes/{id}/review?force=false` | Run the 3 reviewers directly |
| | `GET /reviews/{id}` | Latest saved review with full reports |
| | `GET /agents` | Reviewer Agent Cards and online status |
| Reviewers :10001-3 | `GET /.well-known/agent-card.json` | A2A Agent Card |
| | `POST /` (JSON-RPC `SendMessage`) | A2A endpoint |

Call a reviewer directly over A2A:

```bash
curl -X POST localhost:10003/ -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' -d '{
  "jsonrpc": "2.0", "id": "1", "method": "SendMessage",
  "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"data": {
    "push_id": 7, "project": "demo",
    "files": [{"path": "a.py", "status": "added", "changed_lines": [1,2,3],
               "content": "import pickle\ndef f(d):\n    return pickle.loads(d)\n"}]}}]}}}'
```

## How the scores work

Each reviewer is **fully LLM-powered**: no `ast`/`ruff`/`bandit` static-analysis step, no code-computed
formula. The LLM reads the changed lines, decides the findings, and also returns its own `score` (0-10)
for that one dimension (code quality / best practices / security) directly, as part of its structured
output (`common/schemas.py:LLMReview`). The score is only clamped to 0-10 in code -- the judgment is the
model's. This trades the old reproducibility guarantee (same push -> same score, always) for a review
that reasons about the change as a whole rather than being anchored to what a linter/scanner can see.

Each report still shows a one-line breakdown, e.g. `6.5/10, LLM's own judgment (1 high, 1 medium, 1 low)`.

## Offline mode

Set `LLM_PROVIDER=fake` in `.env` to run everything without a Groq key. The database, A2A and scoring
all run for real; only the LLM is replaced by keyword rules, so chat replies and reviews are basic.

## Notes

- Chat memory is in-process (`InMemorySaver`): it resets when the orchestrator restarts. Pushes and
  reviews are in MongoDB and persist.
- Only `.py` files are reviewed (`REVIEW_EXTENSIONS` in `.env`). Other files are stored as metadata.
- First push to a brand-new repo: only the head commit's diff is available from GitHub.
- If you hit Groq rate limits, lower `LLM_MAX_CHARS` in `.env`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `GET /agents` shows a reviewer offline | Check `logs/<reviewer>.log`; ports 10001-10003 must be free |
| Webhook returns 401 | The GitHub webhook secret must match `GITHUB_WEBHOOK_SECRET` exactly |
| Push accepted but not stored | Check `logs/ingest.log`; usually `GITHUB_TOKEN` lacks access to the repo |
| `GROQ_API_KEY is not set` | Fill in `.env`, or use `LLM_PROVIDER=fake` |
| `/dev/ingest-local` returns 404 | Set `DEV_ENDPOINTS=true` |
