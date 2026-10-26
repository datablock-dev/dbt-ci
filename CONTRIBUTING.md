# Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Development Setup

1. Clone the repository
2. Install dependencies: `pip install -e ".[dev]"`
3. Run tests: `pytest tests/` (the end-to-end tests also need `dbt-duckdb`; see [tests/README.md](tests/README.md))
4. Run the checks CI runs on every pull request:

   ```bash
   black dbt_ci action tests        # format
   flake8 dbt_ci action tests       # lint, configured in .flake8
   mypy                             # type check, configured in pyproject.toml
   ```

The black reformat of the whole codebase is listed in `.git-blame-ignore-revs`. Run
`git config blame.ignoreRevsFile .git-blame-ignore-revs` once so `git blame` skips it;
GitHub does this automatically.

## Errors

Library code raises instead of exiting: a `DbtCiError` from `dbt_ci/errors.py` for
failures dbt-ci explains itself (`ConfigurationError`, `ManifestError`,
`DbtCommandError`), and ordinary exceptions for bugs. Only a command's entry point turns
an error into an exit code. Every runner raises `DbtCommandError` when dbt fails, so
callers never check return codes.

## Commit Message Format

This project uses [Conventional Commits](https://www.conventionalcommits.org/) for automated releases:

- `feat:` New feature (minor version bump)
- `fix:` Bug fix (patch version bump)
- `docs:` Documentation changes
- `refactor:` Code refactoring
- `test:` Adding tests
- `chore:` Maintenance tasks

Example:
```bash
git commit -m "feat: add Docker runner support"
git commit -m "fix: resolve path resolution on Windows"
```

See [RELEASING.md](RELEASING.md) for details on the automated release process.
