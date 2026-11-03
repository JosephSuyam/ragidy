# Development workflow

How work flows through Ragidy's Claude Code setup. `CLAUDE.md` has the quick reference.

## Lifecycle
```
/start ─▶ /plan ─▶ /implement ───────────────────────────────────────────▶ /summarize
           │        delegate → gate → /review → docs → commit → PR → CI
           │                    ▲                                   │ red
           │                    └──────── /debug ci (or autofix) ◀──┘
           └─ planner + architect (ADR in docs/decisions/)
merge to main ─▶ deploy-staging ─▶ /release (tag vX.Y.Z) ─▶ deploy-production
```

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
3. **CI-time:** a red PR triggers the `autofix` job, which follows the `debugging` skill's CI section.
4. **Memory:** each non-obvious fix becomes a one-line rule in `lessons.md`, so the same mistake does not repeat.
5. **Runtime:** the app itself retries, falls back across providers, and re-retrieves. See `docs/architecture/overview.md`.

## Local state
`.claude/.state/` (gitignored) holds the hook state: the current session start and the last gate result. Delete it to reset.
