# Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Development Setup

1. Clone the repository
2. Install dependencies: `pip install -e ".[dev]"`
3. Run tests: `pytest tests/`
4. Run linting: `black dbt_ci/ tests/`

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
