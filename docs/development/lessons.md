# Lessons

Rules learned from real mistakes. Record them with the `documentation` skill. Keep this file at 50 lines or fewer, one rule per line.

## API
- Set `hide_input_in_errors=True` on pydantic `Settings` and never log `exc.errors()`, because a failing model validator's ValidationError otherwise prints the whole raw settings dict, secrets included (an OAuth check echoed a client secret). (api, 2026-11-04)
- Pass `TRUSTED_PROXIES` to uvicorn `ProxyHeadersMiddleware(trusted_hosts=...)` as strings, never `ip_network` objects, because uvicorn 0.54 runs `"/" in host` on each entry and crashes at startup on network objects (`AttributeError 'str' object has no attribute 'version'`). (api, 2026-11-04)
- Set LlamaIndex `OpenAIEmbedding(max_retries=1)` for at most 2 requests, never assume one retry layer, because it applies `max_retries` twice (OpenAI client retry plus its own tenacity wrapper). (api, 2026-11-05)
- Never log, `repr` or serialize (`to_dict`, `to_json`) a LlamaIndex `OpenAIEmbedding`, because it stores `api_key` as a plain str, not `SecretStr`. (api, 2026-11-05)

## Web

## Tests
- Test S3 endpoints with boto3, never `curl --aws-sigv4` from curl older than 7.86, because old curl omits `x-amz-content-sha256`, so valid credentials get `SignatureDoesNotMatch`. (tests, 2026-11-04)
- Before debugging an integration test that fails with `password authentication failed for user "ragidy"`, run `netstat -ano | rg :5432`, because a native Windows Postgres service on :5432 shadows the Docker `ragidy-db-1` port. (tests, 2026-11-05)

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
