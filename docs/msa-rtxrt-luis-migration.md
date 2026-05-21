# MSA RT/X — Luis ↔ Digital OS migration

This doc explains how the RT/X bot is operated today, where its surface
moves over the coming PRs, and exactly how Luis should make changes going
forward without us drifting back into two incompatible dashboards.

## TL;DR

| Layer | Today | Where it's going | Who edits |
|---|---|---|---|
| **Operator UI** | Luis's localhost dashboard at `http://localhost:8765/xdashboard` | Digital OS at `https://hq.digidle.com/bots/msa-rtxrt` | Luis, via branches + PRs in `mission-control` |
| **Runner** | `tools/local-runners/msa_rtxrt_runner.py` on Luis's PC (`luis-pc-1`) | Same — still on Luis's PC. Other future runners can join (`claw-1`, `zach-laptop-1`, `mac-mini-1`, `mac-mini-2`). | Luis, via PRs in `mission-control` |
| **Bot logic** | The five `*_bot.py` files in Luis's OneDrive folder | Same. Long-term, candidate to move into the shared runner layer or its own package — TBD. | Luis, **directly edits the active folder on his runner PC**; the runner picks up changes on the next job |
| **Localhost dashboard** | Source of truth | **Working backup / reference only** once Digital OS is verified | Frozen as a reference snapshot in `integrations/luis-rtxrt-source/`. Live copy on Luis's PC still works and can still be used. |

Nothing on Luis's PC is "frozen" in the sense of being read-only. The
localhost dashboard stays alive and usable. Drift between Luis's live
local files and Digital OS is the migration's central problem — the rules
below exist to keep that drift small and visible.

## Why we're moving the surface

1. Mission Control / Digital OS is the company-owned operating surface for
   every bot. RT/X being the last lane that lives on a single laptop
   makes it the bottleneck for onboarding, audit, RBAC, and runbooks.
2. The runner architecture is already in place — `luis-pc-1` polls Mission
   Control, executes safe jobs, and reports back. The remaining work is
   moving the *operator UI* onto Digital OS without breaking the
   workflow.
3. Bot logic and the runner stay on Luis's PC because that's where
   AdsPower lives. Network-level changes are explicitly out of scope.

## Source-of-truth snapshot

`integrations/luis-rtxrt-source/` is a point-in-time reference snapshot of
Luis's localhost source. It lets reviewers and Digital OS developers read
the exact local interface without ssh'ing into Luis's PC.

- Code (`server.py`, `dashboards/*.html`, `bots/*.py`) is committed
  verbatim — none of it contains private data.
- JSON queue / list files (`*_auftrag.json`, `contacts.json`,
  `follower_lists.json`, etc.) are **not** committed verbatim because
  they contain real recipient handles, message bodies, or AdsPower
  profile IDs. They are represented as
  `integrations/luis-rtxrt-source/examples/*.example.json` (placeholders)
  or `*.schema.json` (JSON Schema) files.
- Live status / log files (`*_status.json`, `*_log.json`,
  `preflight_status.json`) are **skipped entirely** — see
  `integrations/luis-rtxrt-source/REDACTION_LOG.md`.

The snapshot is refreshed manually by PR when Luis lands a meaningful
change locally and we want Digital OS to mirror it.

## How Digital OS edits flow (operator UI)

Until Digital OS reaches verified parity, the local dashboard remains the
day-to-day operator surface. New features go through Mission Control:

```
Luis (or claude) on luis-pc-1
   │
   ├── git switch -c feat/msa-rtxrt-<short-name>   # branch off main
   ├── edit frontend/src/components/bots/MsaRtxrtDashboard.tsx (or sibling files)
   ├── npm/vitest equivalent CI passes (Mission Control has its own pipeline)
   ├── gh pr create --title "..."                  # open the PR
   ├── PR review + checks → squash merge to main
   └── Vercel auto-deploys hq.digidle.com
```

**Do not edit `xdashboard.html` or `blast_dashboard.html` on Luis's PC
for new operator features going forward.** If a change is needed in the
local dashboard for a one-off fix, file a follow-up PR to mirror the
change in `MsaRtxrtDashboard.tsx` (Digital OS) within the same week.

## How runner / bot edits flow

Bot-logic changes still happen directly in Luis's active RT/X bot folder
(no PR required, runner picks up on next job).

When a bot change needs a corresponding Mission Control bridge (e.g. a
new job kind, a new safety gate, a new payload field), the matching
Mission Control PR must land in the **same week** and be linked from the
bot change so we don't accumulate runner-side capability that Digital OS
can't reach.

```
Luis on luis-pc-1
   │
   ├── edit C:\…\Automation [RTxRT]\<bot>.py
   ├── (locally) python <bot>.py --dry-run             # smoke locally
   ├── /apply runner change (e.g. new job kind) in tools/local-runners/msa_rtxrt_runner.py
   ├── /apply matching Digital OS UI change in frontend/src/components/bots/MsaRtxrtDashboard.tsx
   └── single PR titled "feat(rtxrt): <bot-feature> + runner kind + UI"
```

Long-term, the active bot folder is a candidate to migrate into the
`mission-control` repo (under `bots/msa-rtxrt/` or a sibling repo) so
the entire stack is reviewable as one diff. That migration is **not** in
scope for the exact-interface-port-v1 sprint.

## What lives in the runner repo vs Luis's PC

| File | Owner | Edited by |
|---|---|---|
| `tools/local-runners/msa_rtxrt_runner.py` | Mission Control (in git) | PRs only |
| `tools/local-runners/test_msa_rtxrt_runner.py` | Mission Control | PRs only |
| `frontend/src/components/bots/MsaRtxrtDashboard.tsx` | Mission Control | PRs only |
| `frontend/src/components/bots/MsaRtxrtControlPanel.tsx` | Mission Control | PRs only |
| `integrations/luis-rtxrt-source/` (this snapshot) | Mission Control | PRs only (manual refresh) |
| `C:\…\Monthly revenue\server.py` | Luis's PC | Luis edits directly; reflected in next snapshot refresh |
| `C:\…\Automation [RTxRT]\xdashboard.html` | Luis's PC | Same (but new features should not go here — see above) |
| `C:\…\Automation [RTxRT]\dm_bot.py` etc. | Luis's PC | Luis edits directly; runner picks up next job |
| `C:\…\Automation [RTxRT]\auftrag.json` / `contacts.json` / `follower_lists.json` | Luis's PC | Luis edits via the local dashboard (until Digital OS has the matching form) |
| `.msa-rtxrt-runner.env`, `.msa-rtxrt-runner.live.env` | Luis's PC, **never committed** | Luis manually; runner token + bot dir |

## What "verified" means before flipping the switch

Digital OS replaces the localhost dashboard **only after** all of:

- [ ] Native Promo Repost form (AdsPower group + tweet URLs) wired through Local Bridge.
- [ ] Native All Chats form (account selector + message composer + max-chats) wired.
- [ ] Native New Database form (mode + account picker + start) wired.
- [ ] Native Recipient Database form (source + senders + rate limits + start) wired.
- [ ] Native Campaign orchestrator wired (or interim deep-link to the localhost Campaign tab with clear UX).
- [ ] AdsPower profile picker shared component wired (so all five forms can pick profiles).
- [ ] Daily Auto-Run schedule editor wired.
- [ ] Operator end-to-end runs at least one of each `live_one_*` from Digital OS without surprise.
- [ ] Run History `stdout_excerpt` displays cleanly on Windows (cosmetic cp1252 fix in runner — known follow-up).
- [ ] Localhost dashboard explicitly marked "reference only — do not edit for new features" in the local UI.

Until that checklist is done, **Luis's localhost dashboard remains the
working backup**.

## Anti-drift rules (the short list)

1. **No new UI feature in `xdashboard.html` without a matching `MsaRtxrtDashboard.tsx` PR within the same week.**
2. **No new runner job kind without a matching Digital OS surface in the
   same PR (a disabled control with `Local bridge not connected yet` is
   acceptable as the interim).**
3. **No new bot script in the active folder without a snapshot refresh PR
   within the week.**
4. **No edits to `integrations/luis-rtxrt-source/` outside snapshot
   refresh PRs.** Treat it as read-only between refreshes.
5. **No backend/runner code that surfaces real recipient handles, message
   bodies, or AdsPower profile IDs to Digital OS without a redaction
   wrapper.** Privacy stays on the runner side.

## Things this migration explicitly does not do

- Move bot files into the `mission-control` repo (TBD; out of scope for v1).
- Build a public tunnel / ngrok / cloudflared for the localhost dashboard.
- Touch AdsPower credentials, cookies, sessions, or browser profile data.
- Touch Clerk / auth / RBAC / billing / DNS / Render production /
  Vercel production settings.
- Add mass-live anywhere.
- Weaken `safety_guard.py` or the live-one gate.

## Where to look when something looks wrong

| Problem | First place to look |
|---|---|
| Digital OS RT/X page is empty / blank | `frontend/src/components/bots/MsaRtxrtDashboard.tsx` + browser devtools |
| Job stuck "running" in Run History | runner stderr log + `tools/local-runners/msa_rtxrt_runner.py` (`patch_job_status` retry was added in PR #42) |
| Live-one denied with three-flag error | `safety_guard.py --gate-check` on the runner + the `.msa-rtxrt-runner.live.env` source |
| Smoke fails but dry-run succeeds | Runner log + `safety_guard.py --smoke` (imports each bot module) |
| Local dashboard not loading | `server.py` running on the runner PC; `http://localhost:8765/healthz` if exposed |
| Discrepancy between Digital OS and local dashboard | `integrations/luis-rtxrt-source/` may be stale — open a snapshot refresh PR |

## Maintainers

- **Owner of system:** Zach / Digidle OS / Modern Sales Agency
- **Builder/operator for RT/X:** Luis
- **Runner machines:** `luis-pc-1` (active), planned `claw-1`, `zach-laptop-1`, `mac-mini-1`, `mac-mini-2`
- **Source of truth:** Mission Control on GitHub (this repo)
