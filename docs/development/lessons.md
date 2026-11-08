# Lessons

Rules learned from real mistakes. Record them with the `documentation` skill. Keep this file at 50 lines or fewer, one rule per line.

## API
- Set `hide_input_in_errors=True` on pydantic `Settings` and never log `exc.errors()`, because a failing model validator's ValidationError otherwise prints the whole raw settings dict, secrets included (an OAuth check echoed a client secret). (api, 2026-11-04)
- Pass `TRUSTED_PROXIES` to uvicorn `ProxyHeadersMiddleware(trusted_hosts=...)` as strings, never `ip_network` objects, because uvicorn 0.54 runs `"/" in host` on each entry and crashes at startup on network objects (`AttributeError 'str' object has no attribute 'version'`). (api, 2026-11-04)
- On Windows, run async DB entrypoints with `loop_factory=asyncio.SelectorEventLoop` (`TestClient(backend_options=...)`, `asyncio.run(..., loop_factory=...)`, `uvicorn --loop asyncio:SelectorEventLoop`), because psycopg async refuses the default ProactorEventLoop and `fastapi run` returns 500 on every DB route. (api, 2026-11-05)
- Set LlamaIndex `OpenAIEmbedding(max_retries=1)` for at most 2 requests, never assume one retry layer, because it applies `max_retries` twice (OpenAI client retry plus its own tenacity wrapper). (api, 2026-11-05)
- Never log, `repr` or serialize (`to_dict`, `to_json`) a LlamaIndex `OpenAIEmbedding`, because it stores `api_key` as a plain str, not `SecretStr`. (api, 2026-11-05)
- Commit the read transaction before slow non-DB work in a request (argon2 hashing, LLM calls), or do that work before the first DB query, because the pooled connection otherwise idles in a transaction meanwhile and about 15 concurrent logins exhausted the pool. (api, 2026-11-08)
- Reject a DOCX DOCTYPE only after requiring strict UTF-8 with no NUL bytes, because expat auto-detects UTF-16 even with `XMLParser(encoding="utf-8")`, so a UTF-16 `<!DOCTYPE` slips past a byte check and its entities expand. (api, 2026-11-08)
- Strip `\x00` from parsed text before storing it, and reject it with `422` in every free-text request schema, because Postgres `text` refuses NUL: pypdf `extract_text()` emits it for some fonts (rejected after the embeddings were paid), and a request that reaches the INSERT fails with a 500. (api, 2026-11-08)
- Set `hide_parameters=True` on the SQLAlchemy engine, because an escaping DB error otherwise logs its bound values (user questions, answers) through uvicorn's traceback. (api, 2026-11-08)
- Register a `RequestValidationError` handler that returns only `type`, `loc` and `msg`, because FastAPI's default 422 body echoes each error's `input`, so a login with an invalid password sends the password back. (api, 2026-11-08)
- Set `num_workers` on LlamaIndex embed models, because without it `aget_text_embedding_batch` sends every batch at once with `asyncio.gather` (about 25 OpenAI or 250 Ollama parallel requests for a 5 MB file). (api, 2026-11-08)

## Web
- In Vite `server.proxy`, scrub `req.url` in an `error` listener added in `configure`, because `configure` runs before Vite attaches its own error logger, which prints `req.url` with the query (OAuth codes). (web, 2026-11-06)
- In a Web loader used by an effect, write a promise `.then(onOk, onErr)` chain shared by the effect and its callers, never an async function that sets state synchronously in `try/catch`, because oxlint `react/set-state-in-effect` (with `--deny-warnings`) fails the gate; do not disable the rule or duplicate the fetch. (web, 2026-11-08)
- Update session state without remounting the app (`sessionVersion`) when the first-write gate refetches `/me` after the first guest write, because a remount unmounts the view mid-flow and aborts its next request (a chat's SSE stream right after `POST /chats`). (web, 2026-11-08)

## Tests
- Test S3 endpoints with boto3, never `curl --aws-sigv4` from curl older than 7.86, because old curl omits `x-amz-content-sha256`, so valid credentials get `SignatureDoesNotMatch`. (tests, 2026-11-04)
- Before debugging an integration test that fails with `password authentication failed for user "ragidy"`, run `netstat -ano | rg :5432`, because a native Windows Postgres service on :5432 shadows the Docker `ragidy-db-1` port. (tests, 2026-11-05)
- Build signed or time-limited test values (cookies, tokens) inside the test body, never in `pytest.mark.parametrize` arguments, because parametrize runs at collection and the values can expire before the case runs (an `exp=now+600` OAuth cookie). (tests, 2026-11-06)
- Run `docker ps` before integration tests and start `make db` if `ragidy-db-1` is not up, because with Postgres down they hang for more than 180 s with no output instead of failing. (tests, 2026-11-06)
- Guard tests against the app database with a `pytest.fail` (a `BaseException`) when the engine is built, never rely on an unreachable `DATABASE_URL` alone, because a psycopg connect to a refused port on Windows hung for over 120 s instead of failing, and the worker loop's `except Exception` would swallow an ordinary error. (tests, 2026-11-08)

## Docs
- Write diagram labels as the step name first, then its folder in parentheses (`Services (app/services)`), and name folders only, never files that do not exist yet, because mixed label formats and phantom paths mislead readers. (docs, 2026-11-04)

## Tooling and CI
- Add an import in the same edit as its first use, because the post-edit hook strips imports it sees as unused, so a split edit leaves an undefined name (F821) that fails the stop hook. (workflow, 2026-11-08)
- Use `python infrastructure/scripts/check.py`, never ad-hoc lint/test commands, because hooks and CI run exactly that gate. (workflow, 2026-11-03)
- Do bulk path renames in one regex pass, never as chained `str.replace` calls, because later pairs re-match earlier output (`scripts/check.py` → `infrastructure/infrastructure/...`). (tooling, 2026-11-03)
- Quote YAML frontmatter values that contain `: `, because unquoted ones silently fail to parse (command descriptions fell back to body text). (workflow, 2026-11-03)
- oxlint only warns by default, so `npm run lint` uses `--deny-warnings`; keep it, or lint never blocks. (web, 2026-11-03)
- When a subagent reports that plan mode blocked its edits, ask the user whether auto mode needs to be turned on instead of re-launching the agent, because re-launches stay blocked and waste runs. (workflow, 2026-11-04)
- Before an ADR picks a third-party service, check that its upstream is maintained and its image pulls anonymously (Docker Hub manifest check), because MinIO was archived and its images went private after ADR 0002 picked it. (workflow, 2026-11-04)
- PRs trigger no CI; after each merge, watch the Pipeline run (`gh run list --workflow pipeline.yml --branch <branch>`), because a merged PR is not proof the branch is green. (workflow, 2026-11-04)
- In nginx, `proxy_pass` to a Docker service through `resolver 127.0.0.11` and a variable (`set $api http://api:8000`), never a literal host, because nginx resolves literal upstreams at startup and fails `nginx -t` (`host not found in upstream "api"`) when the service is not up. (infra, 2026-11-06)
- On nginx routes whose query holds a secret (the OAuth callback), turn off both `access_log` and `error_log`, because nginx error lines of every level quote the full request line, query included. (infra, 2026-11-06)
- Never make a tool that imports the `typescript` JS API (`openapi-typescript`, peer `typescript ^5.x`) a devDependency of `apps/web`, because TypeScript 7 (the Go port) ships no JS compiler API (`lib/` holds only `tsc.js`); use a nested package with its own pinned `typescript@5` and lockfile (`packages/shared-types`). (tooling, 2026-11-08)
- Tell parallel agents to prefix their scratchpad files, because agents share the session scratchpad and one agent's `smoke.py` overwrote another's. (workflow, 2026-11-08)
