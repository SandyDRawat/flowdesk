# Security policy

## Reporting

Use GitHub's **Report a vulnerability** feature on this repository's Security tab:
https://github.com/SandyDRawat/flowdesk/security/advisories/new

Do not publish exploit details, keys, user data, or databases in ordinary issues. Include affected version, reproduction steps with synthetic data, impact, and a suggested fix if available. Only the latest release is currently supported; no response-time guarantee is made.

## Trust boundaries

- Flowdesk 1.x is for one trusted OS user on localhost. It has no authentication or multi-user isolation. Other local processes able to access loopback or your files are inside this trust boundary.
- HTTP binds to `127.0.0.1`; Host/Origin and JSON content-type checks protect against common cross-site local-service requests. They are not substitutes for authentication. Never expose this server through a public tunnel or reverse proxy.
- Task storage and backups are ordinary SQLite files, not encrypted vaults. Protect them with OS account permissions, encrypted disks, and protected backup locations. Exports intentionally contain task data.
- Website-entered Gemini keys stay in process memory until restart/disconnect; environment credentials are managed by the operator. Neither source is included in state/export responses. Process memory and an operator's environment remain sensitive.
- Gemini receives only the explicitly previewed task title, description, and type. No automated repository reading, tool execution, or project MCP exists in phase one. Review task text before sending it; task content itself may contain sensitive data.
- Requests go to a fixed HTTPS provider endpoint with the key in a header, not a URL. Redirects are rejected. Output is size/type checked and escaped in the UI. Provider error bodies are not returned or logged.
- AI output is a suggestion, never an instruction to execute code or an automatic state change. One request runs at a time; usage charges can still occur for failed or rejected responses.
- Optional stdio MCP grants the chosen assistant access to this local task database. Use a dedicated database and explicit workspace root where isolation is needed. Do not hand it to untrusted clients.

## Release hygiene

Public release files are selected from source/static/tests/docs only. Databases, exports, environment files, private configs, virtual environments, logs, and personal workspace history are excluded. Maintainers run the release guard, tests, and a secret scanner against both files and Git history before publishing. These checks reduce risk; they are not a guarantee that no vulnerability exists.
