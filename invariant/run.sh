#!/usr/bin/env bash
set -a; [ -f .env ] && . ./.env; set +a
export INVARIANT_DATA="${INVARIANT_DATA:-./data}"
exec python3 -m uvicorn invariant.app:app --reload --port 8000
