# OnlyFans Intelligence (OFI) — status

Read-only audit of what's built on `origin/main` as of the
parity-recovery sprint (`c8b764e7`, PR #27).

## Surfaces present

Sidebar: a single **OnlyFans Intelligence** entry under
"Business / Intelligence" (`frontend/src/components/organisms/DashboardSidebar.tsx`).
Under it:

```
frontend/src/app/of-intelligence/
├── page.tsx               — entry / overview
├── accounts/              — creator account list (read)
├── alerts/                — QC alert feed
├── chatters/              — chatter analytics (synthetic until OM real)
├── daily-qc/              — Daily QC dashboard (PR #18)
├── fans/                  — fan list view (redacted; aggregates only)
├── mass-messages/         — MM planning surface (no live send)
├── memory-bank/           — per-creator memory store
├── messages/              — message log surface
├── posting-insights/      — posting cadence / engagement analytics
├── qc-reports/            — historical QC reports
├── revenue/               — revenue dashboard
└── settings/              — OFI-area settings (sub-page)
```

## Backend present

- `backend/app/api/of_intelligence.py` — core OFI read APIs.
- `backend/app/api/of_qc_scheduler.py` — Daily QC scheduler (PR #19).
- `backend/app/api/of_qc_discord.py` — Discord QC publisher (default
  disabled).
- `backend/app/services/of_intelligence/qc/*` — QC engine.
- `backend/app/services/of_intelligence/alerts.py` — alert formatting.
- `backend/app/services/of_intelligence/obsidian_export.py` — export
  (used for the brain layer in
  `/Users/zachary/Documents/Zachs Brain/brain/`).
- `backend/app/services/onlymonster/` — OM ingestion scaffolding
  (no live creds path enabled).
- Models: `of_intelligence.py`, `of_qc_finding.py`,
  `of_qc_scheduler_job.py`, `of_qc_discord_status.py`.
- Migrations: `e9a4f2b8c103_add_of_qc_dashboard_tables.py`,
  `f1c8a3b6d502_add_qc_scheduler_jobs.py`,
  `g3a8e2c5b709_add_qc_readonly_ingestion_columns.py`.

## Data state

| Source                                  | Status                                                  |
| --------------------------------------- | ------------------------------------------------------- |
| OnlyFans live API                       | Not connected.                                          |
| OnlyMonster live API                    | Not connected. Scaffolding only.                        |
| Synthetic / fixture data                | Yes — drives every dashboard for now.                   |
| Locally-imported brain data             | Yes — Obsidian export path exists for read.             |

Nothing on main exfiltrates fan PII or message bodies. All API
responses are schema-redacted.

## What is intentionally *not* built yet

- Live OnlyFans scraper / connector.
- Live OnlyMonster fetcher with creator credentials.
- Per-creator credentials vault UI (creator_credentials model exists,
  no operator UI yet).
- "Send" actions from OFI surfaces — every mass-message, message log,
  and chatter response surface is read-only by design.

## Blocked on Major Security

Per `docs/operations/major-security-status.md`, OFI live data is gated
behind Major Security Sprints 7 + 8a–8e, none of which are merged.

In practical terms: the OFI dashboards are stable and useful today as
the COO's daily triage view, but they will show synthetic / locally-
imported data until the security gates land.

## What this sprint did NOT change

Nothing in the OFI stack was modified. The OFI module remains
foundation-complete and security-gated.

## Next OFI branch

Option A — `feat/ofi-coo-triage-summary-v1`: pull QC findings into a
single COO-facing triage queue. Synthetic-data-safe. Can ship before
Major Security finishes.

Option B — `feat/ofi-creator-credential-vault-ui`: an owner-only UI
to view + rotate `creator_credentials` rows. Audit-logged, no
plaintext display. Should land *after* Major Security Sprint 7 so the
credential-storage envelope is on main.

Recommended order: A first (low risk, immediate COO value), then B.
