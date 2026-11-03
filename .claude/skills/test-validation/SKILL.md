---
name: test-validation
description: Run Ragidy's quality gate (lint, format, typecheck, and tests for api and web) and fix the failures. Use for /test, "run the tests", "is it green", or before a commit.
---

# Test validation

1. Run `python infrastructure/scripts/check.py [--api|--web] [--fast]`, or `make check` / `make fast`. It prints `PASS` or `FAIL` for each step and the tail of each failing step's output.
   - `--fast` skips tests marked `integration`. The Stop hook uses it.
   - Without `--fast`, it also runs integration tests and the root `tests/` folder. They need `make db` running.
2. For each `FAIL`, fix the root cause in the code. Never weaken, skip, or delete a test to make it pass, and never add a blanket `# type: ignore` or `oxlint-disable`.
3. Run the gate again. Repeat until it passes, up to 3 rounds. If it still fails, stop and report the remaining errors. Use the `debugging` skill if the cause is unclear.
4. Report in one line: the steps that passed, and the steps you fixed.
