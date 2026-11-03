"""Stop: run the fast quality gate on changed code. Exit 2 makes Claude keep fixing.

Gives up after MAX_ATTEMPTS consecutive blocked stops so it can never loop forever.
"""

import hashlib
import json
import sys

from _common import ROOT, SESSIONS, git, read_input, run, tail

STATE = SESSIONS / ".stop_gate.json"
MAX_ATTEMPTS = 3


def tree_fingerprint() -> str:
    status = git("status", "--porcelain", "-uall")
    digest = hashlib.sha256(status.encode())
    for line in status.splitlines():
        path = ROOT / line[3:].split(" -> ")[-1].strip('"')
        if path.is_file():
            stat = path.stat()
            digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode())
    return digest.hexdigest()


def load_state() -> dict[str, object]:
    try:
        return dict(json.loads(STATE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def save_state(**state: object) -> None:
    SESSIONS.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state), encoding="utf-8")


def main() -> int:
    if not git("rev-parse", "--git-dir"):
        return 0
    data = read_input()
    state = load_state()
    fingerprint = tree_fingerprint()
    if state.get("green") and state.get("fingerprint") == fingerprint:
        return 0

    attempts = int(str(state.get("attempts", 0))) if data.get("stop_hook_active") else 0
    code, output = run([sys.executable, "scripts/check.py", "--fast"], ROOT)
    if code == 0:
        save_state(fingerprint=fingerprint, green=True, attempts=0)
        return 0

    attempts += 1
    save_state(fingerprint=fingerprint, green=False, attempts=attempts)
    if attempts > MAX_ATTEMPTS:
        message = (
            f"Quality gate still failing after {MAX_ATTEMPTS} auto-fix attempts. "
            "Tell the user what is failing, then run /lesson once it is fixed."
        )
        print(json.dumps({"systemMessage": message}))
        return 0
    print(
        f"Quality gate failed (attempt {attempts}/{MAX_ATTEMPTS}). Fix the root cause; "
        f"never weaken or skip tests to pass:\n{tail(output, 60)}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
