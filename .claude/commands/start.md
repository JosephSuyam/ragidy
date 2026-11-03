---
description: Resume work: review last session summary, git state, and propose the next step
---

The SessionStart hook already loaded `docs/sessions/latest.md`, the git state, and the lesson count into context.

1. Summarize where the project stands in 3-5 lines: the last goal, what is done, and what is in progress.
2. Run `git status -s` and `git log --oneline -5`. Note any drift since the summary, such as new commits or uncommitted files.
3. Propose the first item from "Next steps" as the next action. If it is still valid, ask the user to confirm it. Otherwise ask what to work on.
4. Answer any "Open questions" from the summary that the user resolves.

Focus: $ARGUMENTS
