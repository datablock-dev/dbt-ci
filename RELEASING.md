# Release Process

Every push to `main` is released automatically. The version is derived from the commit
messages by [`ietf-tools/semver-action`](https://github.com/ietf-tools/semver-action), and
the package is published to PyPI.

## How It Works

A push to `main` runs the CI/CD pipeline (`.github/workflows/ci.yml`):

1. Runs the test suite across the supported Python and dbt-core versions (`tests.yml`)
2. Runs the release job (`publish-pypi.yml`), which:
   1. Checks out the latest `main` and runs the tests again
   2. Works out the next version from the commits since the latest `v*` tag
   3. Writes it to `pyproject.toml` and pushes a `chore(release): vX.Y.Z [skip ci]` commit
   4. Builds the wheel and sdist from that commit
   5. Creates the `vX.Y.Z` tag and a GitHub Release with generated release notes, both on that commit
   6. Publishes the package to PyPI (https://pypi.org/project/dbt-ci/)
   7. Moves the major version tag (`v1`) to that commit, so workflows using the GitHub Action as `datablock-dev/dbt-ci@v1` pick up the release

The release job waits for the GitHub Action smoke test (`action-smoke.yml`) as well as the
tests, so `v1` never moves to a commit whose `action.yml` is broken.

Release notes live in [GitHub Releases](https://github.com/datablock-dev/dbt-ci/releases);
there is no hand-maintained changelog.

**Note:** Pushes that change only Markdown files (`*.md`) skip the pipeline, and pull requests that change only Markdown files skip the tests. Any release they would have produced goes out with the next push that touches other files.

**Note:** Releases run one at a time, and each run releases the latest `main` rather than the commit that triggered it. Merging several PRs in quick succession therefore produces one release that includes all of them; the runs queued behind it find nothing new and skip without failing. The release tag points at the version-bump commit the package was built from.

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

PRs are squash-merged, so the PR title becomes the commit message that decides the version.

### Version Bumping

| Commit | Bump | Example |
|--------|------|---------|
| `feat:` / `feature:` | Minor (1.9.5 → 1.10.0) | `feat: add S3 state storage support` |
| `type!:` or a `BREAKING CHANGE:` footer | Major (1.9.5 → 2.0.0) | `feat!: rename --prod-manifest-dir to --state` |
| Anything else (`fix:`, `refactor:`, `chore:`, `docs:`, …) | Patch (1.9.5 → 1.9.6) | `fix: resolve path resolution on Windows` |

Every release-triggering push bumps at least the patch version, whatever its type.

```bash
# Breaking change
git commit -m "feat!: change --prod-manifest-dir to --state

BREAKING CHANGE: --prod-manifest-dir flag renamed to --state
for consistency with dbt conventions"

# No release at all
git commit -m "chore: tidy CI config [skip ci]"
```

## Manual Release

There is no manual release path: the release job only runs on a push to `main`
(running `ci.yml` by hand with `workflow_dispatch` runs the tests but not the release).
To release, merge a change to `main`.

## Checking Release Status

- GitHub Releases: https://github.com/datablock-dev/dbt-ci/releases
- PyPI: https://pypi.org/project/dbt-ci/
- Pipeline runs: `gh run list --workflow=ci.yml`

## Troubleshooting

### No release created

1. Check that the push wasn't marked `[skip ci]` and changed more than Markdown files.
2. Check the release job's log in the CI/CD Pipeline run.
3. If an earlier run already released the same commits, the job logs "Couldn't find any commits between branch HEAD and latest tag. Exiting silently..." and skips. That is expected.

### Release job failed

- **Secrets:** the job needs `ORG_TOKEN` (to push the version bump to `main` and read tags) and `PYPI_TOKEN`.
- **Push rejected:** if another commit landed on `main` between checkout and the bump push, the push fails. The next push to `main` releases both.

## GitHub Marketplace

The GitHub Action (`action.yml` at the repository root) is listed on the Marketplace by
publishing a GitHub Release with "Publish this Action to the GitHub Marketplace" ticked.
That has to be done once by hand from the release page; later releases stay listed.

## Docker Images

`.github/workflows/docker.yml` can build images to `ghcr.io/datablock-dev/dbt-ci`, but no
workflow currently calls it, so releases do not publish Docker images.
