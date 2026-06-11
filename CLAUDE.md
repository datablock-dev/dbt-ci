# Workspace Guidelines

## Slack Messages
When asked to write a Slack message, write it as humanly as possible. Structure it professionally using headers and emojis.

## Pull Requests
Use the same naming convention as for 'Commit Messages'.

Ticket IDs are always uppercase, regardless of how they are passed in.

Never include references to AI generation in PR bodies — no "Generated with Claude Code", no `Co-authored-by:` trailers, no similar attribution lines.

## README.md
Always update the README.md file prior to creating a new PR to ensure that it is up to date.

## Commit Messages
Use conventional commit prefixes: `feat:`, `fix:`, `enhance:`, `refactor:`, `chore:`, `docs:`, `test:`. No ticket ID required. Never add `Co-authored-by:` trailers.

## Code Style
- Prefer Python for all new code.
- Refactor code into modules rather than keeping everything in a single file.
- GCP-related code (Pub/Sub, Secret Manager, etc.) belongs in a `gcp/` directory for reusability across services.
- Always add a docstring to every Python function, method, and class. One concise sentence is enough for simple cases; use multi-line docstrings only when the behaviour is non-obvious.
