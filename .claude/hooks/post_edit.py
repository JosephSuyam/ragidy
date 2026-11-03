"""PostToolUse(Edit|Write): format + lint the edited file. Exit 2 feeds errors back to Claude."""

import sys
from pathlib import Path

from _common import ROOT, read_input, run, tail

BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def commands(path: Path) -> tuple[Path, list[list[str]]] | None:
    if path.suffix == ".py" and BACKEND in path.parents:
        return BACKEND, [
            ["uv", "run", "ruff", "format", str(path)],
            ["uv", "run", "ruff", "check", "--fix", str(path)],
        ]
    if (
        path.suffix in {".ts", ".tsx"}
        and FRONTEND in path.parents
        and (FRONTEND / "node_modules").exists()
    ):
        return FRONTEND, [["npx", "eslint", "--fix", str(path)]]
    return None


def main() -> int:
    file_path = read_input().get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0
    path = Path(file_path).resolve()
    plan = commands(path)
    if plan is None or not path.exists():
        return 0
    cwd, cmds = plan
    for cmd in cmds:
        code, output = run(cmd, cwd)
        if code != 0:
            rel = path.relative_to(ROOT).as_posix()
            print(f"Lint errors remain in {rel}. Fix them now:\n{tail(output)}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
