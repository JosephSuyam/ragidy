#!/usr/bin/env bash
# Thin wrapper: hook logic lives in scripts/validate_change.py (stdlib Python, cross-platform).
PY=$(command -v python || command -v python3)
exec "$PY" "$(dirname "$0")/scripts/validate_change.py"
