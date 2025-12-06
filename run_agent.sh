#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${PROJECT_ROOT}"

cd "${PROJECT_ROOT}"

if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

uvicorn api.main:app --host "${AGENT_HOST:-0.0.0.0}" --port "${AGENT_PORT:-8001}" --reload

