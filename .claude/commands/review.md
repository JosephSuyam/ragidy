---
description: Review the current branch or a PR for correctness, security, RAG rules, and tests
argument-hint: "[PR number]"
---

Review $ARGUMENTS. If no PR number is given, review the current branch against `main`.

Delegate to the `code-reviewer` agent, which follows the `code-review` skill. When the diff touches uploads, URL fetching, the DB, auth, or secrets, also run `/security-review`.

Show the findings and the verdict. Ask before fixing anything.
