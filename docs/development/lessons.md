# Lessons

Rules learned from real mistakes. Record them with the `documentation` skill. Keep this file at 50 lines or fewer, one rule per line.

## API

## Web

## Tests

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
