---
name: release-management
description: Cut a Ragidy release - verify main, tag a semantic version, and publish release notes. Production is already deployed by the merge to main. Use for /release, "cut a release", or "tag vX.Y.Z".
---

# Release management

Flow: merge `develop` → `staging` (the `Pipeline` run builds images tagged `tree-<git tree hash>` and `staging`, then deploys staging) → merge `staging` → `main` (the run promotes those same `tree-<hash>` images to production). Production never rebuilds; it ships the image that staging tested. To get there, follow the `git-workflow` skill's Promote section. This skill only tags the version and publishes release notes. It does not deploy or promote images.

1. **Verify main.** Run `git switch main && git pull`. Check that `gh run list --workflow pipeline.yml --branch main --limit 5` shows the `Pipeline` run for `HEAD` green, including `deploy-production`. If anything is red, stop and follow the `debugging` skill.
2. **Pick the version.** Use semantic versioning from the commits since the last tag (`git log $(git describe --tags --abbrev=0)..HEAD --oneline`):
   - any breaking API or schema change bumps major
   - any `feature` commit bumps minor
   - otherwise, bump patch
   - The first release is `v0.1.0`.
3. **Confirm with the user.** Show the version, the commit list, and any migrations. Wait for an explicit yes before you push the tag.
4. **Tag and publish.** Run `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`, then `gh release create vX.Y.Z --generate-notes`.
5. **Never delete a published tag.** To roll back production fast, retag the last good image. Old `tree-<hash>` images stay in GHCR. After `docker login ghcr.io` with package write access, run:
   ```bash
   tree=$(git rev-parse <last good main commit>^{tree})
   for app in api web; do
     docker buildx imagetools create -t ghcr.io/josephsuyam/ragidy-$app:production ghcr.io/josephsuyam/ragidy-$app:tree-$tree
   done
   ```
   Then revert the change on a branch from `develop` and promote it to `main` through the flow.
6. Report the version and the release URL.
