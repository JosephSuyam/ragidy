---
name: code-review
description: Review a Ragidy diff for correctness, security, RAG-specific pitfalls, tests, and unneeded code. Use for /review, "review this", "review my PR", or as the review step of feature-development.
---

# Code review

The `code-reviewer` agent follows this checklist. Base the review on `git diff main...HEAD`, or on the PR (`gh pr diff <n>`). Read the code around the diff, not only the changed lines.

## Checklist
1. **Correctness.** Does the logic do what the task says? Check edge cases: empty input, huge input, unicode, concurrent requests, a provider timeout.
2. **Security.**
   - Uploads: a size limit, a MIME allowlist, and safe file names.
   - URL ingestion: http(s) only, no private, loopback, or link-local IPs (SSRF), with a timeout and a size cap.
   - No secrets in code or logs.
   - SQL only through the ORM or bound parameters.
   - Prompt injection: retrieved text is data and never becomes instructions or tool arguments without validation.
3. **RAG and agents.**
   - The library split holds: LlamaIndex code stays in `app/rag/`, LangChain/LangGraph code stays in `app/agents/`, and only plain data crosses between them.
   - Answers cite their chunks. Empty retrieval says "not found" and never answers from model memory.
   - Every provider call follows the self-healing rules in `docs/architecture/overview.md`.
   - Embedding model changes come with a re-index plan.
4. **Data.** Migrations are reversible, and there is no data loss.
5. **Tests.** Each new behavior has a test that fails without it. No paid API calls happen in tests.
6. **Necessity.** Flag code nobody asked for, abstractions with one caller, duplicated logic, and dead code. Apply the ponytail rules (`/ponytail-review`).
7. **Docs.** `.env.example`, `docs/api/`, and `AGENTS.md` match the change.

## Output
One line per finding, most severe first:

`path:line: <blocker|major|minor>: <problem>. <fix>.`

End with a verdict: `approve`, `approve with minors`, or `changes required`. Do not praise, and do not raise style nits that the linters already enforce.
