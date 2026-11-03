"""Shared hook helpers. Hooks are stdlib-only so they run anywhere Python does."""

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = ROOT / ".claude" / "sessions"
LATEST = SESSIONS / "LATEST.md"
ARCHIVE = SESSIONS / "archive"

sys.path.insert(0, str(ROOT / "scripts"))
from check import run, tail  # noqa: E402

__all__ = ["ARCHIVE", "LATEST", "ROOT", "SESSIONS", "git", "read_input", "run", "tail"]

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def read_input() -> dict[str, Any]:
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def git(*args: str) -> str:
    code, out = run(["git", *args], ROOT)
    return out.strip() if code == 0 else ""
