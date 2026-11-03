---
name: lesson
description: Record a durable lesson in .claude/LESSONS.md so a mistake is not repeated. Use for /lesson, after fixing a non-obvious bug, after a hook or CI failure that took more than one try, or when the user corrects you.
---

# /lesson [what happened]

`.claude/LESSONS.md` is loaded into every session through `CLAUDE.md`. Keep it small and useful.

1. Write the lesson as one rule, one line. Use the form: `- <Do or never do X> because <cause>. (<area>, <YYYY-MM-DD>)`
   - Good: `- Always mock embeddings at app/providers because tests hit OpenAI otherwise. (tests, 2026-11-03)`
   - Bad: `- Fixed the bug in ingestion.` (not a rule, cannot be reused)
2. Read `.claude/LESSONS.md`. If an existing rule covers the same cause, sharpen that line instead of adding a new one.
3. Add the rule under the matching section heading.
4. Keep the file at 50 lines or fewer. When it is full, merge related rules. Move rules that became code (a lint rule, a test, a helper) out of the file, because the code now enforces them.
5. Skip the lesson if it only applied to this one task, or if the code, a test, or `CLAUDE.md` already enforces it.
6. Report the line you added or changed.
