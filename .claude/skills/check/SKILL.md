---
name: check
description: Run Ragidy's quality gate (lint, format, typecheck, tests for backend and frontend) and fix failures. Use for /check, "run the tests", "is it green", or before commit.
---

# /check [--backend|--frontend] [--fast]

1. Run `python scripts/check.py $ARGUMENTS`. It prints `PASS` or `FAIL` for each step and the tail of each failing step's output.
2. For each `FAIL`, fix the root cause in the code. Never weaken, skip, or delete a test to make it pass, and never add a blanket `# type: ignore` or `eslint-disable`.
3. Run the gate again. Repeat until it passes, up to 3 rounds. If it still fails, stop and report the remaining errors. Use the `debugger` agent if the cause is unclear.
4. Report in one line: the steps that passed, and the steps you fixed.
