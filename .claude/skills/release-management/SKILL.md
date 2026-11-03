---
name: release-management
description: Cut a Ragidy release - verify main, tag a semantic version, publish release notes, and promote the tested staging images to production. Use for /release, "cut a release", "tag vX.Y.Z", or "deploy to production".
---

# Release management

Flow: merge to `main` → `deploy-staging.yml` builds and pushes images tagged `sha-<sha>` and `staging` → tag `vX.Y.Z` → `deploy-production.yml` promotes that same `sha-<sha>` image to `vX.Y.Z` and `production`. Production never rebuilds; it ships the image that staging tested.

1. **Verify main.** Run `git switch main && git pull`. Check that `gh run list --branch main --limit 5` shows CI, Tests, and Deploy staging green for `HEAD`. If anything is red, stop and follow the `debugging` skill.
2. **Pick the version.** Use semantic versioning from the commits since the last tag (`git log $(git describe --tags --abbrev=0)..HEAD --oneline`):
   - any breaking API or schema change bumps major
   - any `feature` commit bumps minor
   - otherwise, bump patch
   - The first release is `v0.1.0`.
3. **Confirm with the user.** Show the version, the commit list, and any migrations. Tagging deploys to production, so wait for an explicit yes.
4. **Tag and publish.** Run `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`, then `gh release create vX.Y.Z --generate-notes`.
5. **Watch.** Run `gh run watch` on the `Deploy production` run. The `production` environment may need a manual approval in GitHub.
6. **Roll back if needed.** Re-run `deploy-production.yml` with `workflow_dispatch` and the previous tag as input. Never delete a published tag.
7. Report the version, the release URL, and the deploy status.
