# Release Process

This project uses automated semantic versioning and releases via `python-semantic-release`.

## How It Works

When you push commits to `main` branch, the CI/CD pipeline (`publish-pypi.yml`) automatically:
1. ✅ Runs tests across multiple dbt-core versions
2. ✅ Analyzes commit messages using Conventional Commits to determine version bump
3. ✅ Updates version in `pyproject.toml`
4. ✅ Updates `CHANGELOG.md` with release notes
5. ✅ Creates a git tag (e.g., `v1.1.0`)
6. ✅ Commits version changes back to repository with `[skip ci]`
7. ✅ Creates a GitHub Release with changelog
8. ✅ Builds Python package (wheel + sdist)
9. ✅ Publishes to PyPI (https://pypi.org/project/dbt-ci/)
10. ✅ Builds Docker images for multiple dbt-core versions

**Note:** The first release after setup may require a manual commit with conventional commit format to trigger semantic-release.

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Version Bumping

**Patch Release (0.1.0 → 0.1.1):**
```bash
git commit -m "fix: resolve login bug"
git commit -m "perf: improve query performance"
```

**Minor Release (0.1.0 → 0.2.0):**
```bash
git commit -m "feat: add S3 state storage support"
git commit -m "feat(cli): add --dry-run flag"
```

**Major Release (0.1.0 → 1.0.0):**
```bash
git commit -m "feat!: redesign configuration API

BREAKING CHANGE: Configuration format has changed"
```

### Commit Types

- `feat:` New feature (triggers minor version bump)
- `fix:` Bug fix (triggers patch version bump)
- `docs:` Documentation changes
- `style:` Code style changes (formatting, etc.)
- `refactor:` Code refactoring
- `perf:` Performance improvements (triggers patch version bump)
- `test:` Adding or updating tests
- `build:` Build system changes
- `ci:` CI configuration changes
- `chore:` Other changes

### Examples

```bash
# Add new feature
git commit -m "feat: add Docker runner support

Adds ability to run dbt commands in Docker containers
with customizable volumes and environment variables"

# Fix a bug
git commit -m "fix: resolve path resolution on Windows"

# Breaking change
git commit -m "feat!: change --prod-manifest-dir to --state

BREAKING CHANGE: --prod-manifest-dir flag renamed to --state
for consistency with dbt conventions"

# Multiple changes
git commit -m "feat: add cloud storage support" -m "feat: add slack notifications"

# Skip CI (no release)
git commit -m "docs: update README [skip ci]"
```

## Manual Release (if needed)

If you need to manually trigger a release or test the release process:

```bash
# Ensure you're on main with latest changes
git checkout main
git pull

# Run semantic-release locally (requires python-semantic-release installed)
pip install python-semantic-release
semantic-release version
semantic-release publish

# Or just trigger the GitHub Actions workflow manually
gh workflow run ci.yml
```

## Troubleshooting

### No Release Created

**Problem:** Commits pushed to main but no release was created.

**Solutions:**
1. Check that commits follow Conventional Commits format
2. Verify commits are not marked with `[skip ci]`
3. Check GitHub Actions logs for errors
4. Ensure secrets `SEMANTIC_RELEASE_TOKEN` and `PYPI_TOKEN` are configured

### Version Not Updated

**Problem:** Release created but version in `pyproject.toml` still shows old version.

**Solution:** This was fixed by ensuring:
- `version_toml = ["pyproject.toml:project.version"]` in semantic_release config
- Workflow has `persist-credentials: true` and proper token access
- Semantic release has permission to commit back to repository

### PyPI Upload Failed

**Problem:** Release created but package not on PyPI.

**Solution:** Verify:
- `PYPI_TOKEN` secret is configured correctly
- `upload_to_pypi = true` in `[tool.semantic_release]` (fixed in recent update)
- PyPI project name matches `name` in `pyproject.toml`

## Docker Image Releases

Docker images are built for every push to main and tagged with:
- `dbt-{VERSION}` (e.g., `dbt-1.10.13`)
- `latest` (points to dbt-1.10.13 currently)
- Future: `v{RELEASE}-dbt{VERSION}` (e.g., `v1.2.3-dbt1.10.13`)

Images are hosted at: `ghcr.io/datablock-dev/dbt-ci`

Supported dbt-core versions: 1.10.13, 1.11.5 (and future versions)

**Note:** Only dbt-core 1.10.13 and above are supported.

## Versioning Strategy

See [VERSION_STRATEGY.md](VERSION_STRATEGY.md) for detailed information about:
- Supporting multiple dbt-core versions
- PyPI package versioning approach
- Docker multi-tag strategy
- How production companies handle multi-version support

## First Release

For the initial release from 0.1.0:

```bash
git commit -m "feat: initial release of dbt-ci

First stable release with core features:
- Smart state comparison
- Multiple runner support
- Cloud storage integration"
git push origin main
```

## Checking Release Status

View releases:
- GitHub: https://github.com/datablock-dev/dbt-ci/releases
- PyPI: https://pypi.org/project/dbt-ci/

Check CI workflow:
```bash
gh run list --workflow=publish.yml
```

## Configuration

Version and release settings are in `pyproject.toml`:

```toml
[tool.semantic_release]
version_toml = ["pyproject.toml:project.version"]
branch = "main"
```

## Troubleshooting

**No release triggered:**
- Ensure commit messages follow conventional format
- Check that commits contain `feat:` or `fix:` for version bumps
- Verify GitHub Actions workflow ran successfully

**Release failed:**
- Check GitHub Actions logs
- Verify `PYPI_TOKEN` secret is set correctly
- Ensure tests pass before release
