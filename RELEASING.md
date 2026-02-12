# Release Process

This project uses automated semantic versioning and releases.

## How It Works

When you push to `main`, the CI automatically:
1. Analyzes commit messages to determine version bump
2. Updates version in `pyproject.toml`
3. Creates a git tag
4. Generates a changelog
5. Creates a GitHub release
6. Publishes to PyPI

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

If you need to manually trigger a release:

```bash
# Ensure you're on main with latest changes
git checkout main
git pull

# Create a tag manually
git tag v0.2.0
git push origin v0.2.0

# Or use gh CLI
gh release create v0.2.0 --generate-notes
```

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
