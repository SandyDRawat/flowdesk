# Contributing to Flowdesk

Thank you for helping improve a source-available project. Read LICENSE and COMMERCIAL_LICENSE.md before using or contributing.

## Before starting

- Search existing issues and discuss significant features before implementing them.
- Keep pull requests focused; include the problem, final behavior, and verification.
- Use synthetic examples. Never submit production databases, customer tasks, screenshots containing private information, credentials, local agent config, or private repository context.
- Report vulnerabilities privately using SECURITY.md, not in a public issue.

## Setup and checks

Python 3.11+, Node 20+ for frontend checks, and an isolated virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-mcp.txt
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
node tests/frontend.cjs
python3 scripts/check_release.py
```

For manual testing use an explicitly temporary database (`python3 server.py --port 8766 --db /tmp/flowdesk-dev.sqlite3`). Do not point tests at a real user's data. Model tests must mock the provider; CI must not require live Gemini credentials.

## Implementation expectations

Preserve original estimates, timer sessions, historical reports, and task edits. Use transactions for multi-step state changes and test migrations on a synthetic existing database. Escape user/provider content before rendering. No AI call should happen without an explicit user action; no provider credentials may enter task records, logs, exports, or browser storage. Keep phase-two features clearly separate from shipped capabilities.

## Pull requests and licensing

To allow the maintainer to offer both the public noncommercial license and separate commercial agreements, code/documentation contributions require the [Contributor Agreement](CONTRIBUTOR_AGREEMENT.md). Confirm acceptance in the pull-request template. You retain copyright; the agreement grants additional nonexclusive licensing rights to the maintainer. If you cannot grant those rights (for example, employer-owned code), do not submit the contribution without authorization.

Do not copy third-party code unless its license and provenance are documented and compatible. Maintainers must verify agreement acceptance before merging. Bug reports and ordinary feature suggestions do not require signing an agreement unless they include a proposed code/documentation contribution.
