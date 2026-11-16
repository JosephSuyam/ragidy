---
name: documentation
description: Keep Ragidy's docs true to the code, and record durable lessons in docs/development/lessons.md. Use after a feature lands, before a commit, after a non-obvious bug, after a hook or CI failure that took more than one try, or when the user corrects you.
---

# Documentation

## Update docs for a change
1. Run `git diff develop...HEAD` and `git status` to see what changed.
2. Update only docs that the diff makes stale or incomplete:

| Changed | Update |
|---|---|
| Setup, commands, Make targets | `README.md`, `CONTRIBUTING.md`, `AGENTS.md` |
| Env vars | `.env.example` |
| Endpoints | `docs/api/` |
| Module layout or pipeline | `AGENTS.md` layout section, `docs/architecture/` |
| A design choice with trade-offs | New ADR in `docs/decisions/NNNN-<slug>.md` |
| Agents, skills, commands, hooks | `CLAUDE.md`, `docs/development/workflow.md` |

3. Never document a planned feature as if it exists.
4. Keep docs short: commands in code blocks, one fact per bullet. Keep `CLAUDE.md` and `AGENTS.md` under about 150 lines each; move detail into `docs/` and link to it.
5. Report which files you changed and why. If no docs needed changes, say so.

## Record a lesson
`docs/development/lessons.md` is loaded into every Claude session through `CLAUDE.md`. Keep it small and useful.

1. Write the lesson as one rule, one line. Use the form: `- <Do or never do X> because <cause>. (<area>, <YYYY-MM-DD>)`
   - Good: `- Always mock embeddings at app/core/providers.py because tests hit OpenAI otherwise. (tests, 2026-11-03)`
   - Bad: `- Fixed the bug in ingestion.` (not a rule, cannot be reused)
2. Read `docs/development/lessons.md`. If an existing rule covers the same cause, sharpen that line instead of adding a new one.
3. Add the rule under the matching section heading.
4. Keep the file at 50 lines or fewer. When it is full, merge related rules. Move rules that became code (a lint rule, a test, a helper) out of the file, because the code now enforces them.
5. Skip the lesson if it only applied to this one task, or if the code, a test, `AGENTS.md`, or `CLAUDE.md` already enforces it.
6. Report the line you added or changed.
