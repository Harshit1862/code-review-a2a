#!/usr/bin/env bash
# Starts all 5 services. Logs go to logs/<service>.log. Ctrl+C stops everything.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi

pids=()
start() {
  local name=$1; shift
  "$@" > "logs/$name.log" 2>&1 &
  pids+=($!)
  echo "started $name (pid $!)  -> logs/$name.log"
}

start code_reviewer           python -m agents.code_reviewer
start best_practice_reviewer  python -m agents.best_practice_reviewer
start security_reviewer       python -m agents.security_reviewer
start ingest                  uvicorn ingest.main:app --host 0.0.0.0 --port 8000
start orchestrator            uvicorn orchestrator.main:app --host 0.0.0.0 --port 8001

cleanup() { echo; echo "stopping..."; kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup INT TERM

echo
echo "Ingest API:        http://localhost:8000/docs"
echo "Orchestrator API:  http://localhost:8001/docs"
echo "Press Ctrl+C to stop."
wait
