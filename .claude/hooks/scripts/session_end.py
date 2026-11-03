"""SessionEnd: write a git-based fallback summary when /summarize did not run this session."""

import json
import sys
import time
from datetime import datetime

from _common import ARCHIVE, LATEST, STATE_DIR, git, read_input


def archive_latest() -> None:
    if LATEST.exists():
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(LATEST.stat().st_mtime).strftime("%Y-%m-%d-%H%M%S")
        LATEST.replace(ARCHIVE / f"{stamp}.md")


def main() -> int:
    data = read_input()
    try:
        current = json.loads((STATE_DIR / "current_session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {"started": time.time(), "head": ""}

    if LATEST.exists() and LATEST.stat().st_mtime >= current["started"]:
        return 0  # /summarize already wrote the summary for this session

    commits = git("log", "--oneline", f"{current['head']}..HEAD") if current["head"] else ""
    status = git("status", "-s")
    if not commits and not status:
        return 0  # nothing happened; keep the previous summary

    archive_latest()
    LATEST.write_text(
        "\n".join(
            [
                f"# Session summary (auto, {datetime.now():%Y-%m-%d %H:%M})",
                "",
                "Auto-generated: /summarize was not run. Goal and next steps unknown; ask the user.",
                "",
                f"- Session: {data.get('session_id', '?')} (end reason: {data.get('reason', '?')})",
                f"- Branch: {git('branch', '--show-current') or '(none)'}",
                "",
                "## Commits this session",
                commits or "(none)",
                "",
                "## Uncommitted changes",
                status or "(none)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
