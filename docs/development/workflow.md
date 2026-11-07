# Development workflow

How work flows through Ragidy's Claude Code setup. `CLAUDE.md` has the quick reference.

## Lifecycle
```
/start ─▶ /plan ─▶ /implement ─────────────────────────────────────────────────▶ /summarize
           │        delegate → gate → /review → docs → commit → PR → merge → CI
           │                    ▲                                           │ red
           │                    └───────────────── /debug ci (or autofix) ◀─┘
           └─ planner + architect (ADR in docs/decisions/)
develop ─▶ staging (build, deploy staging) ─▶ main (deploy production) ─▶ /release (tag vX.Y.Z)
```

## Git flow and CI
1. Branch `<type>/<short-name>` from an up-to-date `develop`.
2. Open a PR and merge the branch into `develop`. Feature PRs may use `--delete-branch`.
3. Open a PR and merge `develop` into `staging`.
4. Open a PR and merge `staging` into `main`.

Never commit directly to `develop`, `staging`, or `main`. Promotion PRs use merge commits (`gh pr merge --merge`) and never delete `develop` or `staging`.

CI is one workflow, `.github/workflows/pipeline.yml` (`Pipeline`). PRs trigger nothing, so checks run after the merge, not on the PR. Each merge to `develop`, `staging`, or `main` produces exactly one run.

| Event | Jobs |
|---|---|
| Push to `develop` | `api`, `web`, `security`, and `autofix` if red |
| Push to `staging` | The same, plus `build` (images tagged `tree-<git tree hash>` and `staging`) and `deploy-staging` |
| Push to `main` | The same checks, plus `deploy-production` (promotes the `tree-<hash>` images built on staging, with no rebuild) |
| Weekly cron (Mon 06:00 UTC) or `workflow_dispatch` | `security` only (full-history gitleaks scan) |

`security` gates `build` and `deploy-production`, so a secret finding or an unpatched CVE blocks deploys. To fix a secret finding, rotate the secret, then add its fingerprint to `.gitleaksignore` by hand in a reviewed PR.

- `api` runs `check.py --api` with Postgres and SeaweedFS, integration tests included. `web` runs the web gate plus the build. `security` runs pip-audit, npm audit, and a full-history gitleaks scan.
- Images are tagged with the git tree hash. The `staging` → `main` merge has the same tree as `staging`, so production gets exactly the image staging tested.
- `autofix`: on a red push, it cuts `fix/autofix-<short sha>` from `origin/develop`, fixes the failure with the `debugging` skill, and opens a PR into `develop`. It needs the `ANTHROPIC_API_KEY` secret and the repo setting "Allow GitHub Actions to create and approve pull requests" (Settings → Actions → General → Workflow permissions). It skips when that branch already exists or an autofix PR is already open.
- Run a full secret scan by hand: `gh workflow run pipeline.yml --ref main`.
- Roll back production fast by retagging the last good image (old `tree-<hash>` images stay in GHCR), then revert through the flow as the follow-up. See the `release-management` skill.

## Pieces and where they live

| Piece | Location | Role |
|---|---|---|
| Commands | `.claude/commands/*.md` | User entry points; each one points to a skill |
| Skills | `.claude/skills/*/SKILL.md` | The procedures, each defined once |
| Agents | `.claude/agents/*.md` | Specialists with owned paths and tool limits |
| Hooks | `.claude/hooks/*.sh` → `.claude/hooks/scripts/*.py` | Automatic checks and session memory |
| Gate | `infrastructure/scripts/check.py` | One quality gate for hooks, skills, `make`, and CI |
| Code graph | `graphify-out/` (gitignored) | graphify knowledge graph of the repo, queried before raw search |
| Lessons | `docs/development/lessons.md` | Rules learned from mistakes; loaded every session |
| Sessions | `docs/sessions/latest.md`, `archive/` | Handoff between sessions |

## Hooks

| Event | Hook | Behavior |
|---|---|---|
| SessionStart | `session-start.sh` | Prints the last summary, the git state, and the lesson count into context. Records the session start in `.claude/.state/`. |
| PostToolUse (Edit, Write) | `post-edit-check.sh` | Runs ruff format and `ruff check --fix` on api files, and `npm run lint -- --fix` on web files. Exits 2 with any remaining errors, so Claude fixes them. |
| Stop | `validate-change.sh` | Runs `check.py --fast` when the tree changed since the last green run. Blocks the stop on failure, up to 3 times in a row. After that, it tells the user what still fails. |
| PreToolUse (Bash, Grep, Read, Glob) | `graphify hook-guard` | Added by `graphify claude install`. Reminds Claude to query the graph before a raw search or file read. |
| SessionEnd | `session-end.sh` | When `/summarize` did not run and something changed, it archives the old summary and writes a git-only fallback. |

The hook logic is stdlib-only Python. `.claude/hooks/scripts/test_hooks.py` tests it, and the gate runs those tests on every check.

## Code graph (graphify)
[graphify](https://github.com/safishamsi/graphify) turns the repo into a knowledge graph, so agents find code with a scoped query instead of broad greps.

| Task | Command |
|---|---|
| Build or refresh (AST only, no LLM, no network) | `graphify update .` |
| Rebuild on each commit, checkout, and merge | `graphify hook install` (local git hooks) |
| Find what matters for a question | `graphify query "<question>"` |
| Relation between two things | `graphify path "<A>" "<B>"` |
| One concept and its neighbors | `graphify explain "<concept>"` |
| What a change could break | `graphify affected "<symbol>"` |
| Architectural hubs | `graphify god-nodes` |

- The rules for Claude are in the graphify section of `CLAUDE.md`. Delegation prompts (`orchestrator`, `feature-development`) pass them on to subagents.
- `graphify-out/` is gitignored. Each clone builds its own graph, so PRs carry no graph diffs.
- `graphify update .` indexes code only. `/graphify` adds docs and images through an LLM, so it sends file contents to that provider; run it only when that is acceptable.

## Self-annealing loop
1. **Edit-time:** lint errors go straight back to the agent.
2. **Stop-time:** the gate must pass before the turn ends.
3. **CI-time:** a red push to `develop`, `staging`, or `main` triggers the `autofix` job, which follows the `debugging` skill's CI section and opens a PR into `develop`.
4. **Memory:** each non-obvious fix becomes a one-line rule in `lessons.md`, so the same mistake does not repeat.
5. **Runtime:** the app itself retries, falls back across providers, and re-retrieves. See `docs/architecture/overview.md`.

## Local state
`.claude/.state/` (gitignored) holds the hook state: the current session start and the last gate result. Delete it to reset.
