---
name: feature-development
description: End-to-end feature workflow for Ragidy. Plan, delegate to specialist agents, build, test, review, document, commit, open a PR, and watch CI. Use for /implement, "build X", "add feature X", or "ship X".
---

# Feature development

Run these steps in order. Do not skip a step; if one does not apply, say why in one line.

1. **Plan.** If there is no approved plan yet, follow the `task-planning` skill. The output is a task list with an owner agent and an acceptance check for each slice.
2. **Branch.** Follow the `git-workflow` skill (`<type>/<short-name>` from `main`).
3. **Delegate.** Send each slice to its owner agent with the task, the files it owns, the API contract, the acceptance check, and the graphify rule from `CLAUDE.md`:

| Slice | Agent |
|---|---|
| Design, contracts, ADRs | `architect` |
| Routes, schemas, services, workers, core | `backend-dev` |
| Parsing, chunking, embedding, indexing, retrieval | `rag-engineer` |
| LangGraph workflows, memory, tools | `agent-engineer` |
| Models, repositories, migrations | `database-engineer` |
| UI | `frontend-dev` |
| Tests | `test-engineer` |
| CI, Docker, infrastructure | `devops` |

   Run independent slices in parallel. Settle shared contracts first: `architect` writes them, and the TypeScript side lives in `packages/shared-types`.
4. **Gate.** Follow the `test-validation` skill until it passes. The Stop hook also enforces this.
5. **Review.** Follow the `code-review` skill, using the `code-reviewer` agent. Fix every blocker. For anything you do not fix, tell the user why.
6. **Docs.** Follow the `documentation` skill, or delegate to the `documentation` agent.
7. **Commit and PR.** Follow the `git-workflow` skill.
8. **CI.** Run `gh pr checks --watch`. If it is red, follow the `debugging` skill's CI section.
9. **Close.** Record lessons with the `documentation` skill, then follow the `session-summary` skill if the user is wrapping up.

Report at the end: the PR URL, the CI status, and anything skipped or left open.
