---
name: handoff
description: Write a session summary to .claude/sessions/LATEST.md so the next session starts with full context. Use for /handoff, "wrap up", "end session", "I'm done", or "save progress".
---

# /handoff

The SessionStart hook loads `.claude/sessions/LATEST.md` into the next session automatically.

1. Archive the old summary if it exists: move `.claude/sessions/LATEST.md` to `.claude/sessions/archive/<YYYY-MM-DD-HHMM>.md`.
2. Collect facts with `git status -s`, `git log --oneline -10`, and the current branch.
3. Write a new `.claude/sessions/LATEST.md`, 60 lines or fewer:

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
- <decision>: <why>

## Open questions
- <question for the user>

## Files touched
- <path>: <change>

Branch: <branch> | Uncommitted: <n files> | PR: <url or none> | CI: <status>
```

4. Write facts only. Use exact paths, commands, and error messages. Omit any section that has nothing in it.
5. Report the path and the "Next steps" list.
