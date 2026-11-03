---
description: "Write missing tests for a target, then run the full quality gate"
argument-hint: "[target path or behavior] [--fast]"
---

Target: $ARGUMENTS

1. If a target path or behavior is given, follow the `test-generation` skill, or delegate to the `test-engineer` agent, to cover it.
2. Then follow the `test-validation` skill. Run `python infrastructure/scripts/check.py` and fix failures until it passes. Pass `--fast` through if it was given.
