# Local deployment

## Foreground server

Run `python3 server.py --open`. It binds only to loopback, defaults to port 8765, and creates a local SQLite database. Use `--port` and `--db` for separate instances. Default timezone is Asia/Kolkata; change it in Settings.

## macOS login service

From this checkout:

```sh
python3 service.py install
python3 service.py status
```

The installer copies runtime files to `~/Library/Application Support/Flowdesk`, preserves/backs up any existing installed database, installs `~/Library/LaunchAgents/local.flowdesk.plist`, and creates `~/Applications/Flowdesk.app`. It uses the Python executable found at installation time. The service starts when that user logs in, not before login. Re-run install to deploy source updates.

Commands: `start`, `restart`, `stop`, `disable-startup`. `stop` unloads the job; `disable-startup` also disables future automatic starts. Data is retained. Logs are in `~/Library/Logs/Flowdesk`.

On an already-installed Mac, the installed server has its own database. Point any MCP client at that exact database; do not accidentally create a second database in your checkout. See MCP.md.

## Credentials

The simplest option is Settings → Your Gemini API key. Session keys intentionally disappear when the server restarts. For persistent configuration, provide `GEMINI_API_KEY` through a protected process-manager environment. A login service does not automatically inherit your terminal environment. This project does not write API keys into its launch plist or repository. Disconnect disables AI for the current process even if an environment key exists; restarting restores environment configuration.

## Backup and restore

`python3 backup.py /absolute/path/to/new-backup.sqlite3 --db /absolute/path/to/live.sqlite3` uses SQLite's backup API and refuses to overwrite an existing backup. Keep backups private.

To restore: stop the service, back up the current database, replace the database with the chosen backup, ensure no stale `-wal`/`-shm` files from the stopped database are left alongside it, and restart. Verify tasks, timers, and reports. Never copy or replace an active SQLite database file manually.

## Team / Internet hosting

Not supported in phase one. Do not change the loopback boundary to deploy a shared instance. See ROADMAP.md for required accounts, permissions, per-user state, and operational work.
