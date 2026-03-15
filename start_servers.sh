#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Virtual environment not found at $ROOT_DIR/.venv"
  echo "Run the setup step first."
  exit 1
fi

if [[ ! -x ".venv/bin/pip" ]]; then
  echo "Virtual environment exists but is incomplete: .venv/bin/pip is missing."
  echo "Recreate the environment after python3-venv or an equivalent tool is available."
  exit 1
fi

source ".venv/bin/activate"

if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

if [[ "${1:-}" == "--background" ]]; then
  mkdir -p logs
  : > logs/uvicorn.log
  : > logs/celery.log
  setsid "$ROOT_DIR/.venv/bin/uvicorn" main:app --host 0.0.0.0 --port 8000 >> logs/uvicorn.log 2>&1 < /dev/null &
  UVICORN_PID=$!
  setsid "$ROOT_DIR/.venv/bin/celery" -A core.celery_app:celery_app worker -l info >> logs/celery.log 2>&1 < /dev/null &
  CELERY_PID=$!
  echo "Started uvicorn (pid $UVICORN_PID) and celery (pid $CELERY_PID) in the background."
  echo "Logs: $ROOT_DIR/logs/uvicorn.log and $ROOT_DIR/logs/celery.log"
  exit 0
fi

cat <<'EOF'
Run these in separate terminals from the project root:

source .venv/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000
source .venv/bin/activate && celery -A core.celery_app:celery_app worker -l info

Or run:
./start_servers.sh --background
EOF
