# Maintainer release checklist

- Run all Python and frontend tests using temporary databases and synthetic data.
- Check the browser flows with an isolated instance and a fake key; never screenshot or publish a user's task list.
- Run `python3 scripts/check_release.py` and `git diff --check`.
- Run `gitleaks dir . --redact` and `gitleaks git --redact --log-opts='--all' .` (GitLeaks 8.30.1 is pinned in CI).
- Audit optional dependencies with `pip-audit -r requirements-mcp.txt` in an isolated environment.
- Inspect `git ls-files`, the commit graph, and author identities. No databases, exports, personal home paths, copied workspace history, or credentials may be published.
- Verify LICENSE, NOTICE, commercial-contact route, contribution agreement, and private vulnerability reporting settings.
- Keep GitHub Actions permissions at contents:read, actions pinned, and checkout credentials disabled. Do not run untrusted pull-request code with maintainer secrets.
- Verify CI after pushing; tag the tested commit only. Document limitations rather than claiming a security certification or live-provider verification based on mocks.

Initial public release checks: 58 Python tests passed (including the real MCP stdio handshake), frontend checks passed, key save/disconnect checked in an isolated browser, source and history scanners run before publishing, and optional dependency audit completed without known vulnerability findings. Gemini response handling was verified with mocked responses; live Gemini billing/model access requires the operator's own valid key and is not certified by these checks.
