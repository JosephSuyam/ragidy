# Session summary (2026-11-06 00:25)

## Goal
Review what is left of the MVP, keep the MVP roadmap in the repo, and build MVP steps 5 and 6.

## Done
- Step 5 providers + logging merged, PR #8 (8b02113), Pipeline 41977025492 green. ADR 0004: `app/core/providers.py` is the single exception to the LlamaIndex/LangChain split; chat SDK `max_retries=2`, `EMBED_MAX_RETRIES=1` for OpenAIEmbedding (LlamaIndex applies it twice), no `.with_retry`; Ollama library defaults.
- Step 6 guest session + `GET /me` merged, PR #9 (a968f2d), Pipeline 42061774228 green. ADR 0005: async SQLAlchemy on psycopg 3, `loop_factory=asyncio.SelectorEventLoop` on Windows, one AsyncSession per request, services commit, guest creation flushes only.
- Step 6 infra: api image ships Alembic; one-shot compose `migrate` service; `--no-proxy-headers`. 108 api tests (36 integration). Tests never read `apps/api/.env` (`pytest_configure`).
- MVP roadmap saved to `docs/development/roadmap.md`.

## Next steps
1. Plan step 7 (accounts R2-R6) with the planner: register/login/logout, OAuth Google/GitHub, `ragidy_session` resolution, origin check `403 origin_mismatch`, owner-row `FOR UPDATE` + `401 session_expired`, guest-to-user migration (R6). Reuse `app/services/tokens.py`, `rate_limit.py` (`ip_key`, `SlidingWindow`), `AppError`.
2. Promote `develop` → `staging` (staging is behind; one PR per step, `gh pr merge --merge`, no `--delete-branch`).
3. Push and PR this `docs/session-2026-11-06` branch into `develop`.

## Decisions
- Async SQLAlchemy: chosen by the user over the planner's sync recommendation (`docs/decisions/0005-request-db-access.md`).
- In-memory per-IP limiter: documented shortcut, valid while there is a single API process.
- `/me` user tier and `ragidy_session`: wait for step 7.
- `packages/shared-types`: wait for the first web consumer.

## Known gaps
- `/api` proxy (Vite + web container) (step 14).
- SeaweedFS internal-port hardening before the public guest tier.
- Linux Docker: api service needs `extra_hosts: ["host.docker.internal:host-gateway"]` for Ollama on the host (step 14).
- `llama-index-vector-stores-postgres` 0.9.0 (`PGVectorStore`) requires `sqlalchemy<2.1`, repo is on 2.1.8; decide at step 9: pin 2.0.x, wait for upstream, or a small pgvector store in `app/rag`.
- Cookie names have no `__Host-` prefix, so a sibling subdomain could plant a guest cookie; settle before production on a shared parent domain.
- Upload step: web client must send the first write alone and wait for the guest cookie (concurrent cookieless writes create orphan guests).
- `WriteOwner` routes must not return a `Response` object, or the guest cookie is dropped.
- Concurrent cookieless writes and the rate-limit slot counted on failed first writes are documented in `docs/api/README.md`.

## Housekeeping
- Local branch `docs/session-2026-11-05` holds an unmerged stale commit c49cdcd; it can be deleted.
- Windows service `postgresql-x64-15` was stopped to free :5432 for Docker `ragidy-db-1`; it restarts on reboot unless set to Manual.
- Local `ragidy-db-1` is migrated to `0002 (head)`.
- First `git push` of PR #9 failed once with "failed to push some refs" and succeeded on retry (cause not captured).

## Files touched
- `apps/api/app/core/{providers,logging,db,errors,config}.py`: providers, logging, async DB session, errors, settings.
- `apps/api/app/{services,repositories,schemas,api}/...`: guest session, owner lookup, `GET /me`.
- `apps/api/tests/...`: providers, guest session, rate limit, `/me` tests.
- `infrastructure/docker/{api.Dockerfile,docker-compose.yml}`, `Makefile`: Alembic in image, `migrate` service.
- `docs/decisions/0004-provider-factory.md`, `docs/decisions/0005-request-db-access.md`: ADRs.
- `docs/development/{lessons,roadmap}.md`, `docs/api/README.md`: lessons, roadmap, API docs.

Branch: docs/session-2026-11-06 | Uncommitted: 0 | PR: #8, #9 merged | CI: develop green (42061774228)
