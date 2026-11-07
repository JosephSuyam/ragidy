# Lessons

Rules learned from real mistakes. Record them with the `documentation` skill. Keep this file at 50 lines or fewer, one rule per line.

## API
- Set `hide_input_in_errors=True` on pydantic `Settings` and never log `exc.errors()`, because a failing model validator's ValidationError otherwise prints the whole raw settings dict, secrets included (an OAuth check echoed a client secret). (api, 2026-11-04)
- Pass `TRUSTED_PROXIES` to uvicorn `ProxyHeadersMiddleware(trusted_hosts=...)` as strings, never `ip_network` objects, because uvicorn 0.54 runs `"/" in host` on each entry and crashes at startup on network objects (`AttributeError 'str' object has no attribute 'version'`). (api, 2026-11-04)
- On Windows, run async DB entrypoints with `loop_factory=asyncio.SelectorEventLoop` (`TestClient(backend_options=...)`, `asyncio.run(..., loop_factory=...)`, `uvicorn --loop asyncio:SelectorEventLoop`), because psycopg async refuses the default ProactorEventLoop and `fastapi run` returns 500 on every DB route. (api, 2026-11-05)
- Set LlamaIndex `OpenAIEmbedding(max_retries=1)` for at most 2 requests, never assume one retry layer, because it applies `max_retries` twice (OpenAI client retry plus its own tenacity wrapper). (api, 2026-11-05)
- Never log, `repr` or serialize (`to_dict`, `to_json`) a LlamaIndex `OpenAIEmbedding`, because it stores `api_key` as a plain str, not `SecretStr`. (api, 2026-11-05)
- Hash or verify passwords (argon2) before the request's first DB query, or commit the read transaction first, because the pooled connection otherwise idles in a transaction during the hash and about 15 concurrent logins exhaust the pool. (api, 2026-11-06)
- Reject a DOCX DOCTYPE only after requiring strict UTF-8 with no NUL bytes, because expat auto-detects UTF-16 even with `XMLParser(encoding="utf-8")`, so a UTF-16 `<!DOCTYPE` slips past a byte check and its entities expand. (api, 2026-11-08)
- Strip `\x00` from parsed text before storing it, because pypdf `extract_text()` emits NUL for some fonts and Postgres `text` rejects it after the embeddings were already paid. (api, 2026-11-08)
- Set `num_workers` on LlamaIndex embed models, because without it `aget_text_embedding_batch` sends every batch at once with `asyncio.gather` (about 25 OpenAI or 250 Ollama parallel requests for a 5 MB file). (api, 2026-11-08)

## Web
- In Vite `server.proxy`, scrub `req.url` in an `error` listener added in `configure`, because `configure` runs before Vite attaches its own error logger, which prints `req.url` with the query (OAuth codes). (web, 2026-11-06)

## Tests
- Test S3 endpoints with boto3, never `curl --aws-sigv4` from curl older than 7.86, because old curl omits `x-amz-content-sha256`, so valid credentials get `SignatureDoesNotMatch`. (tests, 2026-11-04)
- Before debugging an integration test that fails with `password authentication failed for user "ragidy"`, run `netstat -ano | rg :5432`, because a native Windows Postgres service on :5432 shadows the Docker `ragidy-db-1` port. (tests, 2026-11-05)
- Build signed or time-limited test values (cookies, tokens) inside the test body, never in `pytest.mark.parametrize` arguments, because parametrize runs at collection and the values can expire before the case runs (an `exp=now+600` OAuth cookie). (tests, 2026-11-06)
- Run `docker ps` before integration tests and start `make db` if `ragidy-db-1` is not up, because with Postgres down they hang for more than 180 s with no output instead of failing. (tests, 2026-11-06)

## Docs
- Write diagram labels as the step name first, then its folder in parentheses (`Services (app/services)`), and name folders only, never files that do not exist yet, because mixed label formats and phantom paths mislead readers. (docs, 2026-11-04)

## Tooling and CI
- Use `python infrastructure/scripts/check.py`, never ad-hoc lint/test commands, because hooks and CI run exactly that gate. (workflow, 2026-11-03)
- Do bulk path renames in one regex pass, never as chained `str.replace` calls, because later pairs re-match earlier output (`scripts/check.py` → `infrastructure/infrastructure/...`). (tooling, 2026-11-03)
- Quote YAML frontmatter values that contain `: `, because unquoted ones silently fail to parse (command descriptions fell back to body text). (workflow, 2026-11-03)
- oxlint only warns by default, so `npm run lint` uses `--deny-warnings`; keep it, or lint never blocks. (web, 2026-11-03)
- When a subagent reports that plan mode blocked its edits, ask the user whether auto mode needs to be turned on instead of re-launching the agent, because re-launches stay blocked and waste runs. (workflow, 2026-11-04)
- Before an ADR picks a third-party service, check that its upstream is maintained and its image pulls anonymously (Docker Hub manifest check), because MinIO was archived and its images went private after ADR 0002 picked it. (workflow, 2026-11-04)
- PRs trigger no CI; after each merge, watch the Pipeline run (`gh run list --workflow pipeline.yml --branch <branch>`), because a merged PR is not proof the branch is green. (workflow, 2026-11-04)
- In nginx, `proxy_pass` to a Docker service through `resolver 127.0.0.11` and a variable (`set $api http://api:8000`), never a literal host, because nginx resolves literal upstreams at startup and fails `nginx -t` (`host not found in upstream "api"`) when the service is not up. (infra, 2026-11-06)
- On nginx routes whose query holds a secret (the OAuth callback), turn off both `access_log` and `error_log`, because nginx error lines of every level quote the full request line, query included. (infra, 2026-11-06)
- Tell parallel agents to prefix their scratchpad files, because agents share the session scratchpad and one agent's `smoke.py` overwrote another's. (workflow, 2026-11-08)
