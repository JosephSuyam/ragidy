# Ragidy: Claude Code guide

@AGENTS.md

## Commands
| Command | Does | Runs |
|---|---|---|
| `/start` | Resume from the last session summary | SessionStart context |
| `/plan <task>` | Ordered task plan with owners and acceptance checks | `planner`, `architect`, `task-planning` |
| `/implement <task>` | Build end to end: delegate, gate, review, docs, commit, PR, CI | `feature-development` |
| `/review [pr]` | Severity-tagged review and a verdict | `code-reviewer`, `code-review` |
| `/debug <symptom>` or `/debug ci [run]` | Root-cause fix and a lesson | `debugger`, `debugging` |
| `/test [target]` | Write missing tests, then run the gate | `test-engineer`, `test-generation`, `test-validation` |
| `/summarize` | Write `docs/sessions/latest.md` | `session-summary` |
| `/release [version]` | Tag a version and publish release notes | `release-management` |

For a big multi-agent feature, run the main session as `claude --agent orchestrator`. Subagents cannot spawn other agents, so the orchestrator must be the main session.

## Agents (`.claude/agents/`)
| Agent | Owns |
|---|---|
| `orchestrator` | Coordination only: plan → delegate → gate → review → PR |
| `planner` | Task plans (read-only) |
| `architect` | `docs/architecture`, `docs/decisions`, `packages/shared-types`, contracts |
| `backend-dev` | `app/{main.py,api,core,schemas,services,workers}` |
| `rag-engineer` | `app/rag/**` (LlamaIndex) |
| `agent-engineer` | `app/agents/**` (LangChain/LangGraph) |
| `database-engineer` | `app/{models,repositories}`, `alembic/`, `infrastructure/database` |
| `frontend-dev` | `apps/web` |
| `test-engineer` | `apps/*/tests`, `tests/` |
| `code-reviewer` | Reviews (read-only) |
| `debugger` | Root-cause fixes |
| `documentation` | README, CONTRIBUTING, AGENTS, CLAUDE, `docs/`, `.env.example` |
| `devops` | `.github/`, `infrastructure/{docker,scripts}`, `Makefile` |

Skills (`.claude/skills/`) hold each procedure. Commands and agents point to them, so each procedure lives in one place. The ponytail plugin is enabled: also use `/ponytail-review`, `/ponytail-audit`, and `/ponytail-debt`. Use `/security-review` for uploads, URLs, the DB, or secrets.

## Self-annealing
1. **Hooks fix as you go** (`.claude/hooks/*.sh` → `scripts/*.py`).
   - After each edit, `post-edit-check` formats and lints the file.
   - Before you stop, `validate-change` runs `check.py --fast` and blocks the stop until it passes, up to 3 attempts.
   - Fix the root cause. Never weaken, skip, or delete a test, and never add a blanket ignore.
2. **Lessons.** After a non-obvious bug, a gate failure that took more than one try, or a user correction, record a rule with the `documentation` skill.
3. **CI.** On a red push to `develop`, `staging`, or `main`, the `autofix` job in `pipeline.yml` runs the `debugging` skill and opens a `fix/autofix-<short sha>` PR into `develop`. It needs the `ANTHROPIC_API_KEY` secret and the repo setting "Allow GitHub Actions to create and approve pull requests" (Settings → Actions → General → Workflow permissions). Locally, run `/debug ci`.
4. **Runtime.** App code follows the self-healing rules in `docs/architecture/overview.md`: retries, provider fallbacks, corrective RAG, and ingestion status.

## Sessions
- At startup, the `session-start` hook loads `docs/sessions/latest.md`, the git state, and the lesson count. Continue from "Next steps", or run `/start`.
- When the user says they are done, or asks to wrap up or save, run `/summarize`. When it was not run, the `session-end` hook writes a git-only fallback summary.

## Lessons learned
@docs/development/lessons.md

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
