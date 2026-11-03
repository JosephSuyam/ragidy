"""Single quality gate. Used by the Stop hook, the /check skill, and CI.

Usage: python scripts/check.py [--backend] [--frontend] [--fast]
No side flag = both sides. --fast skips tests marked `integration`.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
TAIL_LINES = 40


def tail(text: str, lines: int = TAIL_LINES) -> str:
    kept = text.strip().splitlines()[-lines:]
    return "\n".join(kept)


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    # shutil.which resolves npm.cmd / npx.cmd on Windows without shell=True
    exe = shutil.which(cmd[0])
    if exe is None:
        return 127, f"{cmd[0]} not found on PATH"
    proc = subprocess.run(
        [exe, *cmd[1:]],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout + proc.stderr


def steps(backend: bool, frontend: bool, fast: bool) -> list[tuple[Path, list[str]]]:
    plan: list[tuple[Path, list[str]]] = [
        (ROOT, [sys.executable, "-m", "unittest", "discover", "-q", "-s", "scripts"])
    ]
    if backend:
        pytest = ["uv", "run", "pytest", "-q", *(["-m", "not integration"] if fast else [])]
        plan += [
            (BACKEND, ["uv", "run", "ruff", "check", "."]),
            (BACKEND, ["uv", "run", "ruff", "format", "--check", "."]),
            (BACKEND, ["uv", "run", "mypy"]),
            (BACKEND, pytest),
        ]
    if frontend and (FRONTEND / "package.json").exists():
        plan += [
            (FRONTEND, ["npm", "run", "lint"]),
            (FRONTEND, ["npm", "run", "typecheck"]),
            (FRONTEND, ["npm", "test"]),
        ]
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", action="store_true")
    parser.add_argument("--frontend", action="store_true")
    parser.add_argument("--fast", action="store_true")
    args = parser.parse_args()
    both = not (args.backend or args.frontend)

    failures = 0
    for cwd, cmd in steps(args.backend or both, args.frontend or both, args.fast):
        name = "python" if cmd[0] == sys.executable else cmd[0]
        label = f"[{cwd.name}] {name} {' '.join(cmd[1:])}"
        code, output = run(cmd, cwd)
        if code == 0:
            print(f"PASS {label}")
        else:
            failures += 1
            print(f"FAIL {label}\n{tail(output)}\n")
    print(f"{failures} failing step(s)" if failures else "All checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.exit(main())
