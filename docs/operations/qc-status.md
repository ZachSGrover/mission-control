# OF Daily QC bot — status

Read-only audit of what's actually built on `origin/main` as of the
parity-recovery sprint (`c8b764e7`, PR #27).

## What's built

| Layer                                                              | PR  | Module                                                                |
| ------------------------------------------------------------------ | --- | --------------------------------------------------------------------- |
| Dashboard + alerting foundation                                    | #18 | `frontend/src/app/of-intelligence/daily-qc`, `backend/app/api/of_intelligence.py`, `backend/app/services/of_intelligence/qc/*`, `alerts.py` |
| Safe scheduler + manual runner                                     | #19 | `backend/app/api/of_qc_scheduler.py`, scheduler job model + migration |
| Read-only ingestion layer (`of_intelligence_*` source-agnostic)    | #20 | `backend/app/services/of_intelligence/__init__.py`, ingestion columns migration |
| Discord QC publisher (configurable webhook, dry-run by default)    | —   | `backend/app/api/of_qc_discord.py`, `of_qc_discord_status` model + migration |

The frontend nav exposes **OnlyFans Intelligence** (single sidebar entry,
all signed-in roles). Under it, `daily-qc` is the QC dashboard surface.

## What is *not* built

- **No real OF account connection.** All ingestion runs on synthetic or
  locally-imported data through the `of_intelligence_*` source-agnostic
  tables. There is no upstream OF scraper wired up.
- **No real OnlyMonster connection.** `backend/app/services/onlymonster/`
  has scaffolding only; no live credentials path is enabled on main.
- **No Telegram QC publisher** wired up. Discord publisher exists but is
  default-disabled (webhook unset → no send).
- **No COO-facing QC summary view.** The dashboard is technical-first;
  operators get a raw findings table rather than a triage queue.

## Endpoints (current state)

```
GET    /api/v1/of-qc-scheduler/status          — read scheduler status
GET    /api/v1/of-qc-scheduler/recent-jobs     — list recent QC runs
PUT    /api/v1/of-qc-scheduler/enabled         — toggle the scheduler
POST   /api/v1/of-qc-scheduler/run-now         — sandbox run (synthetic data)
POST   /api/v1/of-qc-scheduler/run-now-real    — real-data run (still safe;
                                                  reads only, never writes back)
GET    /api/v1/of-qc-discord/status            — read webhook + flags
PUT    /api/v1/of-qc-discord/webhook           — set/update webhook URL
DELETE /api/v1/of-qc-discord/webhook           — clear webhook URL
PUT    /api/v1/of-qc-discord/enabled           — toggle publishing
POST   /api/v1/of-qc-discord/test              — send one synthetic test
                                                  message; no real fan data
```

All mutating endpoints write an `audit_events` row. None of them touch
any real OF or OM account.

## Safety status

| Behavior                                               | State                                       |
| ------------------------------------------------------ | ------------------------------------------- |
| Sends real Discord messages                            | Only if owner has explicitly set a webhook AND enabled. Default: no. |
| Sends real Telegram messages                           | No publisher exists.                        |
| Touches real OnlyFans                                  | No. Source columns are blank without OF connector. |
| Touches real OnlyMonster                               | No. OM service exists only as scaffolding.  |
| Logs message bodies                                    | No — explicit policy in `audit_log.py`.     |
| Exposes raw fan PII via the API                        | No — schemas redact / aggregate.            |

## What this sprint did NOT change

Nothing in the QC stack was modified by the parity-recovery sprint.
QC is foundation-complete and intentionally idle until a real
upstream data source is connected, which is gated behind the Major
Security work below.

## Next QC branch

`feat/of-qc-coo-triage-v1` — a COO-facing summary screen that takes
the existing QC findings and presents them as a triage queue. Still no
real account connection.

Prerequisites: none new. Can ship before Major Security finishes
because it operates on whatever the ingestion layer already has.
