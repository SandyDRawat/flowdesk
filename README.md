# Flowdesk

A local task workspace for planning your day, tracking real work, and following up on delegated tasks.

**Source-available · free for permitted noncommercial use · commercial use requires a separate license.** See [LICENSE](LICENSE) and [commercial licensing](COMMERCIAL_LICENSE.md). This is not an OSI-approved open-source license.

## What it does

- An inbox and ordered daily plans, with unfinished commitments carried forward.
- Compact, horizontally scrolling columns: Not started, To do, In progress, Waiting, Blocked, Assigned, Done.
- Start/pause/finish timers, original estimates, daily and weekly reports.
- Configurable running limits; waiting, blocked, and assigned work uses no running slots.
- Assignments with handoff notes, separate communications, timestamped comments.
- Ordered resolution trackers containing work steps, subissues, and communication follow-ups.
- Optional Gemini rewriting with your own API key, a task preview, and review before applying.
- A local MCP server so an assistant can capture and update work in Flowdesk.

## Quick start

Requires Python 3.11+ and timezone data (included on typical macOS/Linux installations). On Windows, install `tzdata` if zone data is unavailable. The web app uses the Python standard library; MCP is optional.

```sh
git clone https://github.com/SandyDRawat/flowdesk.git
cd flowdesk
python3 server.py --open
```

Open <http://127.0.0.1:8765/>. A **new, empty** SQLite database is created in `data/flowdesk.sqlite3`. No demo tasks, credentials, or personal data ship with this repository. Configure your timezone in Settings before planning.

Use `--db /absolute/path/to/tasks.sqlite3` or `FLOWDESK_DB` to choose a different database. Back it up with:

```sh
python3 backup.py /absolute/path/to/backups/tasks-backup.sqlite3
```

See [local deployment](LOCAL_DEPLOYMENT.md) for login startup on macOS and restore instructions.

## Bring your own Gemini key

1. Create a key in [Google AI Studio](https://aistudio.google.com/apikey).
2. Open **Settings → Your Gemini API key** and save the key for this server session.
3. Enable AI on a task, choose **Preview task for AI**, and review exactly what will be sent.
4. Click **Send to Gemini**. Review the suggested title, description, steps, acceptance criteria, and assumptions before applying.

The password field is cleared after saving. The key lives only in server memory, is never returned by the API, and is not included in task storage, exports, backups, or application logs. Restarting the server clears session keys. **Remove / disconnect key** also disables an environment-provided key until a new key is entered or the server restarts. A configured key is not verified until the first AI request.

For persistent configuration, supply `GEMINI_API_KEY` through your process manager's protected environment. `.env.example` is a template; the app does not automatically load `.env` files. Never commit real credentials. Gemini requests incur the usage charges and data handling terms of your Google account.

**Phase one sends only the selected task's title, description, and type.** No repository files, project paths, other tasks, comments, contacts, or MCP context are sent. There is no autonomous agent, web search, or code execution. No external call happens just by enabling AI. Applying suggestions updates the title and appends notes; it preserves estimates, status, and timers.

The default model is `gemini-2.5-flash`; you can change the Gemini model ID in Settings. Availability depends on your account and provider. The provider endpoint is fixed and redirects are rejected.

## MCP and phase two

[Set up the optional Flowdesk MCP server](MCP.md) to let Claude or another MCP client create tasks, plan days, add comments, and inspect resolution trackers. This connects **your assistant to Flowdesk**; it does not connect Flowdesk's AI to your project.

**Planned phase two:** explicitly connect a read-only project MCP server so AI can ask about architecture and code, cite relevant evidence, and propose better-scoped tasks. It is not implemented in this release. See [ROADMAP](ROADMAP.md).

## Deployment boundaries

This release is a **single-user, localhost application**. It has no accounts, role-based access, or team isolation. Assignment names track handoffs; they do not send notifications or give another person access. The HTTP server binds to loopback and rejects non-local Host/Origin values. Do not expose it through a public tunnel, reverse proxy, or shared Internet deployment. Publishing this repository does not publish your running application or database.

A shared team deployment requires the authentication, permissions, per-user planning/timing, repository isolation, and operational work in the roadmap. The built-in Python HTTP server is not an Internet-facing production server.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-mcp.txt
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
node tests/frontend.cjs
python3 scripts/check_release.py
```

Node 20+ is only used for frontend contract checks. Tests use temporary databases and mocked Gemini responses; they never need real credentials or paid model requests. Without MCP dependencies, the stdio integration test is skipped. See [CONTRIBUTING](CONTRIBUTING.md), [SECURITY](SECURITY.md), and [CHANGELOG](CHANGELOG.md).

## License

The published code is licensed under **PolyForm Noncommercial 1.0.0**, with required attribution in [NOTICE](NOTICE). The exact license controls permitted uses, including its provisions for qualifying organizations. Commercial rights are not granted by the public license; request a separate paid agreement through [commercial licensing](COMMERCIAL_LICENSE.md). There is no automatic payment collection or commercial license issuance in the app.
