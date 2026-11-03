"""SessionStart: load the last session summary, git state, and lessons into context."""

import json
import sys
import time

from _common import LATEST, ROOT, STATE_DIR, git, read_input

LESSONS = ROOT / "docs" / "development" / "lessons.md"
MAX_SUMMARY_LINES = 80


def main() -> int:
    data = read_input()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "current_session.json").write_text(
        json.dumps(
            {
                "session_id": data.get("session_id", ""),
                "started": time.time(),
                "head": git("rev-parse", "HEAD"),
            }
        ),
        encoding="utf-8",
    )

    sections = ["# Ragidy session context"]
    if LATEST.exists():
        summary = LATEST.read_text(encoding="utf-8").splitlines()[:MAX_SUMMARY_LINES]
        sections.append("## Last session summary (docs/sessions/latest.md)\n" + "\n".join(summary))
    else:
        sections.append("## Last session summary\nNone yet. Run /summarize before ending a session.")

    branch = git("branch", "--show-current") or "(no branch)"
    status = git("status", "-s").splitlines()
    log = git("log", "--oneline", "-5")
    sections.append(
        f"## Git\nBranch: {branch}\nUncommitted files: {len(status)}\n"
        + "\n".join(status[:20])
        + (f"\nRecent commits:\n{log}" if log else "")
    )

    if LESSONS.exists():
        lines = LESSONS.read_text(encoding="utf-8").splitlines()
        count = sum(1 for line in lines if line.startswith("- "))
        sections.append(f"## Lessons\n{count} lesson(s) in docs/development/lessons.md (loaded via CLAUDE.md).")

    print("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
