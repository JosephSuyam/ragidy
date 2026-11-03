---
name: test-generation
description: Write focused pytest and Vitest tests for new or changed Ragidy behavior, including regression tests for bugs. Use for /test <target>, "add tests for X", or as the test step of feature-development.
---

# Test generation

The `test-engineer` agent follows these rules.

## What to test
- One focused test per behavior: the happy path, one important edge case, and one failure path.
- A regression test must fail without the fix. Check this when you can.
- No snapshot tests. No tests of framework internals.

## Where tests go

| Kind | Location | Runner |
|---|---|---|
| API unit | `apps/api/tests/`, mirroring `app/` | pytest |
| Web unit and component | `apps/web/tests/` | Vitest + Testing Library |
| Cross-app integration (API + Postgres) | `tests/integration/` | pytest, `@pytest.mark.integration` |
| End-to-end through the browser | `tests/e2e/` | add Playwright when the first e2e test is needed |
| Sample files (PDF, HTML, a golden Q&A set) | `tests/fixtures/` | shared |

## Rules
- Never call a paid LLM or embedding API. Mock at the provider factory (`app/core/providers.py`) with fake, deterministic models.
- Mark tests that need Postgres or network with `@pytest.mark.integration`. `check.py --fast` skips them.
- Web: query by role or label, never by class name. Mock `src/services/` (the API client).
- RAG retrieval quality: keep a small golden set in `tests/fixtures/` (question, expected source chunk). Assert that the expected chunk is in the top-k results.
- Finish with `python infrastructure/scripts/check.py` green. Report the tests you added and the behaviors that are still untested.
