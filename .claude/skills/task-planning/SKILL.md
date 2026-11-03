---
name: task-planning
description: Turn a feature request into a small, ordered task plan with owners, contracts, and acceptance checks. Use for /plan, "plan X", "break this down", or before any non-trivial change.
---

# Task planning

1. **Understand.** Restate the goal in 1-2 lines. Read the code the change touches, `AGENTS.md`, and the relevant `docs/architecture/` and `docs/decisions/` files.
2. **Clarify.** Ask the user (AskUserQuestion) only about choices that change the design. For anything else, pick the convention and state it.
3. **Scope.** List every place the change must reach: routes, services, rag, agents, models, migrations, UI, tests, docs, CI. Name what you are deliberately leaving out (YAGNI).
4. **Contracts first.** Define each new API endpoint (method, path, request, response, errors) and each new DB table or column. When the design has real trade-offs, ask the `architect` agent for an ADR.
5. **Slice.** Split the work into tasks of under about 300 lines each. Each task gets:
   - an owner agent (see the table in the `feature-development` skill)
   - the files it touches
   - an acceptance check: a test name or command that proves it works
   - its dependencies on other tasks
6. **Order.** Put contracts and migrations first, then rag and agents, then routes, then UI. Mark the tasks that can run in parallel.
7. **Risks.** Note security risks (uploads, SSRF, secrets), data migrations, re-index needs (an embedding model change), and new env vars.

Output this plan to the user and track it with the task list tool:

```markdown
## Plan: <goal>
Out of scope: <items>
Contracts: <endpoints and tables>
| # | Task | Owner | Files | Acceptance | Depends on |
Risks: <list>
```
