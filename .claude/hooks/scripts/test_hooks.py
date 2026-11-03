"""Self-checks for the quality gate and Claude Code hooks. Run by infrastructure/scripts/check.py."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "infrastructure" / "scripts"))

import check  # noqa: E402
import post_edit_check  # noqa: E402
import validate_change  # noqa: E402


class CheckTest(unittest.TestCase):
    def test_tail_keeps_last_lines(self) -> None:
        self.assertEqual(check.tail("a\nb\nc\n", 2), "b\nc")

    def test_run_reports_missing_tool(self) -> None:
        code, output = check.run(["definitely-not-a-tool-xyz"], ROOT)
        self.assertEqual(code, 127)
        self.assertIn("not found", output)


class PostEditTest(unittest.TestCase):
    def test_ignores_non_code_files(self) -> None:
        self.assertIsNone(post_edit_check.commands(ROOT / "README.md"))

    def test_lints_backend_python(self) -> None:
        plan = post_edit_check.commands(ROOT / "apps" / "api" / "app" / "main.py")
        assert plan is not None
        self.assertEqual(plan[0], ROOT / "apps" / "api")


class ValidateChangeTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patches = [
            mock.patch.object(validate_change, "STATE", Path(tmp.name) / "state.json"),
            mock.patch.object(validate_change, "git", lambda *args: ".git"),
            mock.patch.object(validate_change, "run", lambda cmd, cwd: (1, "boom")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def stop(self, active: bool) -> int:
        with (
            mock.patch.object(validate_change, "read_input", lambda: {"stop_hook_active": active}),
            redirect_stderr(io.StringIO()),
            redirect_stdout(io.StringIO()),
        ):
            return validate_change.main()

    def test_blocks_then_gives_up_after_max_attempts(self) -> None:
        codes = [self.stop(active=i > 0) for i in range(validate_change.MAX_ATTEMPTS + 1)]
        self.assertEqual(codes, [2] * validate_change.MAX_ATTEMPTS + [0])

    def test_new_user_turn_resets_attempts(self) -> None:
        for i in range(validate_change.MAX_ATTEMPTS + 1):
            self.stop(active=i > 0)
        self.assertEqual(self.stop(active=False), 2)

    def test_skips_when_tree_unchanged_since_green(self) -> None:
        with mock.patch.object(validate_change, "run", lambda cmd, cwd: (0, "")):
            self.assertEqual(self.stop(active=False), 0)
        self.assertEqual(self.stop(active=False), 0)  # failing run is never reached


if __name__ == "__main__":
    unittest.main()
