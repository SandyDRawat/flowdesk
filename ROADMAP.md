# Roadmap

## Phase one — available

Local inbox and planning; statuses, timers and assignments; communication tracking; subissues and comments; daily/weekly history; Gemini task-only rewriting with bring-your-own-key; assistant-to-Flowdesk MCP.

## Phase two — project MCP context (not implemented)

Goal: generate tasks grounded in the user's project rather than only rewriting their input.

Proposed flow:
1. User explicitly connects a project MCP server and selects a project.
2. Show the server's tools and approve a bounded read-only tool allowlist.
3. Preview the task and context scope before sending anything to an AI provider.
4. Run a limited research session with time, tool-call, context-size, and cost budgets.
5. Treat tool output as untrusted data; do not follow embedded instructions.
6. Propose a title, scope, subissues, acceptance criteria, and questions with source references.
7. Let the user review the diff and accept changes. Never execute code or mutate project resources as part of task research.

Requirements: scoped credentials, explicit server trust, reconnect/remove controls, secret filtering, isolated per-project execution, audit records, cancellation, prompt-injection tests, and protection against arbitrary URL/process execution. No automatic discovery of local projects or credentials.

The existing Flowdesk MCP server goes in the other direction: an external assistant updates the task tracker. It is not a project-context server.

## Later — shared team hosting

Accounts/invitations and workspace roles; authenticated API and remote MCP; per-user My Day, timers and running limits; real member assignments and notifications; database migrations and PostgreSQL; isolated repository access; background jobs with budgets; HTTPS, deployment checks, monitoring, backup/restore exercises, and abuse controls.

The current local release is not ready for multi-user/public hosting. No dates or compatibility guarantees are promised for these phases.
