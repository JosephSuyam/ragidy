---
name: ship
description: End-to-end feature workflow for Ragidy. Clarify, delegate to agents, build, test, review, document, commit, open a PR, and watch CI. Use for "build X", "add feature X", "ship X", or /ship.
---

# /ship <task>

Run these steps in order. Do not skip a step; if one does not apply, say why in one line.

1. **Clarify.** Restate the task in 1-2 lines. Ask the user (AskUserQuestion) about anything that changes the design. Write a short task list.
2. **Branch.** `git switch -c <type>/<short-name>` from an up-to-date `main` (type: feature, fix, refactor, docs, chore).
3. **Delegate.** Send each slice to its agent with the task, the files it owns, and the acceptance check:
   - `backend-dev` for `backend/`, and `frontend-dev` for `frontend/`. Run them in parallel when the slices are independent. Agree the API contract (path, request, response) first and include it in both prompts.
   - `test-writer` for the tests for each behavior.
4. **Gate.** Run `/check` until it passes. The Stop hook also enforces this.
5. **Review.** Run `/ponytail-review` on the diff. Also run `/security-review` when the change touches uploads, URL fetching, the DB, or secrets. Fix every finding, or tell the user why you are not fixing it.
6. **Docs.** Send the diff to `docs-writer`.
7. **Commit.** Run `/commit`.
8. **PR.** Run `/pr`.
9. **CI.** Run `gh pr checks --watch`. If CI fails, run `/fix-ci`.
10. **Close.** Run `/lesson` for anything non-obvious you learned, then `/handoff`.

Report at the end: the PR URL, the CI status, and anything skipped or left open.
