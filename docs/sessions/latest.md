# Session summary (2026-11-17 01:42)

## Goal
Finish MVP roadmap step 14 (SeaweedFS hardening, e2e, Linux `extra_hosts`, promotion to `main`), audit the unticked requirement boxes, then switch e2e to Playwright.

## Done
- SeaweedFS internals bound to 127.0.0.1, Iceberg/Lance off, only S3 8333 (+ gRPC 18333) reachable; `extra_hosts: host.docker.internal:host-gateway` on the `x-api` anchor (221d3fa, PR #33).
- First e2e test (pytest + httpx through nginx, stdlib Ollama stub on host :11435), `make e2e`, push-only CI `e2e` job gating `build`, `deploy-production`, `autofix`; `nc -z` probe in the `api` job (4d00220, PR #33).
- ADR 0002 amendment 2026-11-16, ADR 0003/0004 wording, docs and lessons (27dfef6, PR #33).
- Requirements audit: all 8 unticked boxes were implemented; gap tests added, boxes ticked, line 172 test names fixed (PR #34).
- `dnspython` 2.9.1 -> 2.9.2 for CVE-2026-128089, which failed `security` on develop run 43911250376 (a7fe2e8, PR #35); autofix-skip lesson (a3029f1).
- Promoted develop -> staging (PR #36, run 43913686995 green incl. build + deploy-staging) -> main (PR #37).

## In progress
- Main Pipeline run 43914518917: `api`, `web`, `e2e`, `security` green; `deploy-production` is `waiting` on the `production` environment's required-reviewer approval.
- Playwright e2e: plan ready (planner), not approved, no branch yet.

## Next steps
1. Approve `deploy-production` for run 43914518917 (GitHub: Actions -> run -> Review deployments), then confirm it is green.
2. Get answers to the Playwright open questions, then branch `test/playwright-e2e` from develop and run tasks 1 and 2 in parallel.
3. Mark promotion done in `docs/development/roadmap.md` step 14.

## Decisions
- Loopback bind over `-filer.disableHttp` or a separate network: the flag leaves master 9333 and volume 8080 open; api/worker must share a network with S3 anyway (ADR 0002 amendment 2026-11-16).
- LLM/embeddings mocked at the HTTP edge with an Ollama stub via `OLLAMA_BASE_URL`, not a `fake` provider in app code.
- Step 14 closes with images promoted; no deploy host picked (needs a new ADR).
- Playwright plan: `pytest-playwright` 0.10.0 (no `[base-url]` extra) in a non-default uv group `e2e` in `apps/api`; the browser test replaces the httpx test (API contract already in `apps/api/tests/test_chats.py`); Chromium only via `playwright install --with-deps --only-shell chromium`; trace/screenshot artifact on CI failure; no ADR, no frontend change (UI already has accessible names). Delete dialogs need `page.on("dialog", lambda d: d.accept())`; match the answer with `exact=True` (stub answer equals the document text).

## Open questions
- Playwright: replace the httpx e2e test (planned) or keep both? Approve the plan?
- Approve the production deploy yourself, or let the orchestrator do it with `gh api`?
- Restore the removed `typescript` devDependency lesson (still covered by ADR 0010)?
- Set the `ANTHROPIC_API_KEY` repo secret so `autofix` runs instead of skipping green?

## Files touched
- `infrastructure/docker/docker-compose.yml`: seaweedfs flags, `extra_hosts`.
- `.github/workflows/pipeline.yml`: probe step, `e2e` job, `needs`.
- `Makefile`: `e2e` target.
- `tests/e2e/*`: conftest, Ollama stub, happy path, compose override.
- `apps/api/tests/*`: audit tests; `apps/api/uv.lock`: dnspython.
- `docs/decisions/0002,0003,0004`, `docs/architecture/requirements.md`, `docs/development/{roadmap,workflow,lessons}.md`, README, CONTRIBUTING, AGENTS.

Cleanup pending: worktree `.claude/worktrees/agent-a67aed127c65b995f` (merged), S3 bucket `devops-bucket` in `seaweedfs_data`, volumes `ragidy-e2e_pgdata` and `ragidy-e2e_seaweedfs_data`.

Branch: docs/session-summary | Uncommitted: 0 | PR: #33-#37 merged | CI: develop and staging green; main waiting on deploy-production approval
