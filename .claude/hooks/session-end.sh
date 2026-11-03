#!/usr/bin/env bash
# Thin wrapper: hook logic lives in scripts/session_end.py (stdlib Python, cross-platform).
PY=$(command -v python || command -v python3)
exec "$PY" "$(dirname "$0")/scripts/session_end.py"
