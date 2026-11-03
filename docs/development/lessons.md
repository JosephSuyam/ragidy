# Lessons

Rules learned from real mistakes. Record them with the `documentation` skill. Keep this file at 50 lines or fewer, one rule per line.

## API

## Web

## Tests

## Tooling and CI
- Use `python infrastructure/scripts/check.py`, never ad-hoc lint/test commands, because hooks and CI run exactly that gate. (workflow, 2026-11-03)
- Do bulk path renames in one regex pass, never as chained `str.replace` calls, because later pairs re-match earlier output (`scripts/check.py` → `infrastructure/infrastructure/...`). (tooling, 2026-11-03)
- Quote YAML frontmatter values that contain `: `, because unquoted ones silently fail to parse (command descriptions fell back to body text). (workflow, 2026-11-03)
- oxlint only warns by default, so `npm run lint` uses `--deny-warnings`; keep it, or lint never blocks. (web, 2026-11-03)
