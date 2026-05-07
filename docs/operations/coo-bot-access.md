# COO Bot Access — Operator Role + Bots Dashboard

This page is the runbook for inviting Zach's COO (or any non-owner
operator) into Mission Control without sharing personal Claude / GitHub
/ bank-level / owner credentials. It pairs with PR `feat/coo-bot-access-v1`
(adds the `operator` role, the unified Bots dashboard, and the audit
log foundation).

## 1. How Zach adds the COO to the allowlist

1. Sign in to `hq.digidle.com` as the existing owner.
2. Open **Settings → Users**.
3. In **Invite by email**, type the COO's work email and pick **Operator**.
4. Click **Invite**. A pending allowlist row is created — and an
   `allowlist.add` row lands in `audit_events` immediately.
5. Send the COO her sign-up URL out-of-band (email / Slack / SMS):
   `https://hq.digidle.com/sign-up?email=<her-email>`.
   *(There is intentionally no automated invite-email send in this
   sprint — that's a follow-up.)*
6. On her first sign-in, the backend `_check_allowlist` code path
   binds her Clerk user id to the row and writes her `MCUserRole`
   with the pending role automatically.

## 2. Recommended role

`operator`.

`builder` would let her use AI / projects / memory but doesn't grant
any bot operations surface, and `viewer` is read-only. `owner` is
reserved for Zach.

## 3. What an operator can do

- Sign in to `hq.digidle.com`.
- See the **Bots** sidebar entry and open `/bots`.
- See every registered bot's status, kind, last-run, and permitted-roles list.
- Start / stop **only** the bots Zach has explicitly added `operator`
  to (per-bot `permitted_roles_json` is the gate). Default seed lists
  only owner — Zach grants operator access per-bot.
- Read everything a `builder` can read (boards, projects, memory,
  workflows, skills, logs, calendar, chat).

## 4. What an operator cannot do

- Cannot view **Settings → Users** or change anyone's role.
- Cannot view **Settings → Integrations** (`GET /api/v1/integrations`
  is now owner-only).
- Cannot save / delete API keys, GitHub PATs, Discord webhooks, or
  Telegram tokens.
- Cannot start / stop **read-only external** bots (Hermes, AI Radar,
  Social Radar) — those are managed by launchd and cloudflared
  outside Mission Control. Even owners cannot actuate them through
  this API.
- Cannot edit any bot's `permitted_roles` (owner-only).
- Cannot bypass kill switches; the existing Daily QC scheduler and
  Discord/Telegram publisher kill switches are still owner-only.

## 5. How to use the Bots page

1. Open `/bots`.
2. Each row shows: name, kind, status pill, safe-mode badge,
   `last_run_at`, `permitted_roles`, and (when applicable) an error
   summary.
3. If the operator has permission to operate the bot, **Start** /
   **Stop** buttons appear.
4. If the bot is `read_only_external` or the operator's role is not
   in `permitted_roles`, the row shows a **blocked** badge with a
   tooltip explaining why.
5. Every Start / Stop / permission-change writes one `audit_events`
   row. Owner can later inspect that audit feed (UI is a follow-up;
   today the data is queryable directly from `audit_events`).

## 6. Bots safe to operate today

These start/stop the bot's *intent flag* in the registry. They do
**not** flip live-send toggles, do **not** start real OS processes,
do **not** trigger live Discord or Telegram sends. Downstream
supervisor loops poll the registry's `enabled` flag.

- `master_control_loop` — Mission Control's master orchestration loop
  (today owner-only by default; grant operator if Zach wants the
  COO to bounce it).

The Daily QC bots below are also in the registry but their authoritative
on/off controls remain on the existing owner-only QC endpoints
(`/api/v1/of-qc-scheduler/enabled`, `/api/v1/of-qc-discord/enabled`).
The Bots-page Start/Stop here records intent only and audits the action;
it does not duplicate or override those endpoints. Treat the Bots-page
controls for these bots as a status surface, not a replacement.

- `of_daily_qc_scheduler`
- `of_qc_discord_publisher`
- `of_qc_telegram_publisher`

## 7. Bots read-only today

- `hermes` — guardian process, owned by launchd.
- `ai_radar` — Discord posting bot, owned by launchd.
- `social_radar` — Discord posting bot, owned by launchd.

For these, Mission Control reflects status only. Start/Stop attempts
return HTTP 403 with `managed_externally`.

## 8. What must NOT be connected yet

These items are on the gap-audit prereq list (see
`docs/security/security-gap-audit.md` §4) and remain blockers for
real OF / OnlyMonster operation by anyone, including operators:

- Per-creator credential vault (M11) — no per-creator credentials
  may be entered yet.
- Direct OnlyFans connector — read-only-or-not, not yet built.
- Client consent record (M3) — required before any sync touches a
  real creator account.
- Per-org settings scoping (M8) — prevents cross-tenant credential
  leakage.
- Live LLM-redaction layer (M6).
- Data-retention job (M5).

If any of those is missing, the COO must not be connecting real
creator accounts through Mission Control.

## 9. Why owner credentials should not be shared

The owner role can:

- Read the masked-preview list of every integration credential.
- Set / delete every integration credential.
- Write any user's role, including elevating someone to owner.
- Edit every bot's `permitted_roles_json`.
- Flip kill switches.

Sharing owner credentials means the COO inherits all of Zach's
personal Claude / GitHub / Discord / Telegram / AdsPower / PhantomBuster
keys *and* the ability to silently re-grant them to someone else.
The operator role lets her run the agency without ever holding any of
that.

## 10. Emergency rollback steps

If something looks wrong (operator account behaving oddly, audit
shows unexpected actions, a bot started by mistake):

1. **Owner only — disable the operator account:**
   `Settings → Users → operator row → toggle disabled`.
   Equivalent API call: `PUT /api/v1/roles/users/<clerk_id>` with
   `{"role":"operator","disabled":true}`. Writes a `role.set` audit
   row.
2. **Owner only — remove from allowlist:**
   `Settings → Users → operator row → trash icon`.
   Equivalent: `DELETE /api/v1/allowed-users/<email-or-clerk-id>`.
   Writes an `allowlist.remove` audit row and revokes the role.
3. **Stop a bot started in error:** `/bots → Stop` if the role still
   has access; otherwise owner can hit `POST
   /api/v1/bots/<slug>/stop`.
4. **Emergency: lock down all integrations:** owner deletes
   credentials in `Settings → Integrations` (each delete writes an
   `integration.delete` audit row). Bots that depend on those
   credentials degrade gracefully.
5. **Investigate:** query `audit_events` filtered by
   `actor_clerk_user_id` to reconstruct the timeline. The audit log
   is append-only — no UPDATE / DELETE callers exist.

## Out-of-scope for v1

Documented for clarity so the next sprint knows what to pick up:

- Automated invite-email send (today: pre-authorize then notify
  out-of-band).
- Audit log UI (today: query the table directly).
- Global kill switch row (`mc.bots.frozen`).
- Per-creator credential vault.
- Client consent flow.

These belong in subsequent sprints; the foundation in this PR is
designed to make them additive.
