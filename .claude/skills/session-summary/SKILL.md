---
name: session-summary
description: Write a session summary to docs/sessions/latest.md so the next session starts with full context. Use for /summarize, "wrap up", "end session", "I'm done", or "save progress".
---

# Session summary

The SessionStart hook loads `docs/sessions/latest.md` into the next session automatically. If no summary is written, the SessionEnd hook writes a git-only fallback.

1. Archive the old summary if it exists: `git mv docs/sessions/latest.md docs/sessions/archive/<YYYY-MM-DD-HHMM>.md`. Use the date and time it was written.
2. Collect facts with `git status -s`, `git log --oneline -10`, and the current branch.
3. Write a new `docs/sessions/latest.md`, 60 lines or fewer:

```markdown
# Session summary (<YYYY-MM-DD HH:MM>)

## Goal
<what the user wanted this session, in 1-2 lines>

## Done
- <finished item> (<commit sha or file>)

## In progress
- <unfinished item>: <exact state, and where it stopped>

## Next steps
1. <the first concrete action for the next session>

## Decisions
- <decision>: <why>. Link the ADR in docs/decisions/ if there is one.

## Open questions
- <question for the user>

## Files touched
- <path>: <change>

Branch: <branch> | Uncommitted: <n files> | PR: <url or none> | CI: <status>
```

4. Write facts only. Use exact paths, commands, and error messages. Omit any section that has nothing in it.
5. Record any lessons from the session with the `documentation` skill.
6. Commit the summary as `docs(sessions): summarize <topic>`.
7. Report the path and the "Next steps" list.
