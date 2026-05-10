# Mission Control product map

Quick reference for the surfaces that show up in the sidebar. The
concepts are not interchangeable — each one solves a specific problem
and has a different permission gate.

## Bots

**What:** Long-lived operational workers that run agency tasks.

**Examples:** OF Daily QC, RT Bot (sandbox), Hermes, Radar, Discord
publisher, Telegram publisher.

**Source of truth:** `bot_registry` table; `backend/app/api/bots.py`.

**Who can see them:** `owner`, `operator` (sidebar gated in
`DashboardSidebar.tsx`; page gated by `RoleGuard` in `bots/page.tsx`).

**Who can act on them:**

- `owner` — can do everything, including edit `permitted_roles`.
- `operator` — can start/stop bots whose `permitted_roles` includes
  `operator`, **and** the bot is not `read_only_external`.
- Other roles — no controls visible, no API access.

**Special class:** `read_only_external` bots (Hermes, Radar) are managed
by launchd outside Mission Control. The API rejects start/stop on these
with `managed_externally` — no path here can touch the OS-level
services.

**When to add a bot:** A persistent worker that should be visible to
operators in a single dashboard. Status / start / stop must be
auditable.

## Agents

**What:** AI workers that reason, build, research, or execute scoped
tasks inside Mission Control. Backed by the `agents` table and the
`/api/v1/agents` endpoints. May be attached to a Gateway to take
real-world action through OpenClaw.

**Source of truth:** `backend/app/api/agents.py`,
`frontend/src/app/agents`.

**Who can see them:** all signed-in roles (no role gate on the link),
but mutations require auth and the per-board permissions still apply.

**When to add an agent:** A specific AI worker tied to a Board that
operates on tasks. Distinct from a Bot because an Agent is scoped to
work — it doesn't run forever the way a Bot does.

## Workflows

**What:** Repeatable multi-step processes. The orchestration layer that
sits above Agents — chains tasks together.

**Source of truth:** `backend/app/api/workflows.py`,
`frontend/src/app/workflows`.

**Who can see them:** all signed-in roles.

**When to use:** Anything you'd otherwise document as a runbook and
trigger manually. If you do it more than twice, it's a workflow.

## Boards

**What:** Planning and task containers. Kanban-style. Each board has an
optional `gateway_id`. Agents and Tasks scope to a Board.

**Source of truth:** `backend/app/api/boards.py`,
`frontend/src/app/boards`.

**Who can see them:** all signed-in roles.

**When to use:** Any unit of work big enough to need multiple tasks.
One board per initiative or per client engagement is typical.

## Gateway

**What:** The OpenClaw connection that lets an Agent take real-world
action — call APIs, run local tools, drive a browser, etc. Per-board
WebSocket endpoint.

**Source of truth:** `backend/app/api/gateways.py`. Browser-side
singleton in `frontend/src/lib/openclaw-singleton.ts`.

**Who can see it:** today the sidebar exposes a `Control` link
(distributed device + agent control plane) and a `boards/[boardId]`
detail surface; the gateway management UI is owner-adjacent and not
shown as a top-level nav entry. The chat header surface shows derived
gateway *status* to everyone who can see chat.

**When to touch it:** never, day-to-day. The gateway URL,
token, and Cloudflare Access policy are owner / founder concerns.

## Hermes

**What:** System guardian — alerts, health checks, on-call wiring.
Lives in the sidebar as `Hermes` and reports under "All systems
operational" / "System degraded" at the bottom-left.

**Source of truth:** `backend/app/api/hermes.py`,
`frontend/src/app/hermes`. The on-machine guardian is a launchd
service (`ai.hermes.status-server`) — Mission Control reads it but
does not control it.

## Boards groups, Skills, Tags, Custom fields

Supporting taxonomy. Not in scope for the parity sprint.

## Decision table — "where should this live?"

| If you need to…                              | Build a…    |
| -------------------------------------------- | ----------- |
| Run a daemon that QCs OF chat daily          | Bot         |
| Send Discord alerts on a schedule            | Bot         |
| Have an AI worker pick up tasks on a board   | Agent       |
| Chain a sequence of human + AI steps         | Workflow    |
| Organize work for a single initiative        | Board       |
| Let an Agent click a Chrome window           | Gateway     |
| Watch for system failures + page the owner   | Hermes hook |

## "Why are Bots and Agents both in the sidebar?"

Because they answer different questions.

- **Bots** answer "what background workers are running for the agency
  right now, and can I stop one?" The audience is the operator (COO),
  who needs a single page to triage running processes without touching
  the underlying OS.
- **Agents** answer "what AI worker is attached to *this board*?" The
  audience is whoever owns the board — they need agents to be
  per-board, scopeable, and easy to spin up without touching launchd.

A Bot is heavy and long-lived; an Agent is lightweight and
board-scoped. They share the OpenClaw runtime but are operated and
gated separately.

## See also

- `docs/operations/local-web-parity.md`
- `docs/operations/coo-bot-access.md`
- `docs/operations/qc-status.md`
- `docs/operations/major-security-status.md`
- `docs/operations/ofi-status.md`
