# Mission Control local runners

Scripts in this folder run on Zach's Claw computer (or any operator's
local machine) and act as the bridge between the Mission Control web UI
and code that must not run inside the production backend — automations
that touch external platforms, browser sessions, AdsPower profiles, etc.

## Why a local runner

The Mission Control split is:

- **Web UI (`hq.digidle.com`)** is the *control panel*. It enqueues
  jobs and reads status. It NEVER drives AdsPower, Playwright, X,
  OnlyFans, or anything that needs a real browser session.
- **Backend (Render)** stores job intent + safe audit logs. No
  external automation runs here either.
- **Local runner (this folder)** runs on the operator's computer.
  It pulls jobs, executes the corresponding local Python command,
  captures output, and writes status back.

This separation keeps real API keys, cookies, session tokens, and
client data off the production stack.

## msa_rtxrt_runner.py — MSA RT/X Automation Bot

Wraps Luis's imported MSA RT/X automation (`incoming/luis-msa-import/
MSA/Monthly revenue/Automation [RTxRT]`) so it can be driven from
Mission Control's "Bots → MSA RT/X Automation Bot" page.

### What this PR ships

- The runner wrapper itself (this file's safety gate + command
  builder + entrypoint).
- The local-command contract: ten job kinds, six dry-run, four
  live-one — see `DRY_RUN_KINDS` and `LIVE_ONE_KINDS` in the script.
- Unit tests proving the safety gate and the mass-live block.
- The Mission Control UI page at `/bots/msa-rtxrt` rendered in
  "Claw runner offline" mode.

### What this PR deliberately does NOT ship

- **Backend job table + poll endpoint.** The runner stub today
  prints its config and exits; it does not poll Mission Control.
  Adding the queue is a follow-up because it requires a migration,
  a job model, role-gated POST + GET routes, and the wiring on
  both sides. See "Next steps" below for the exact contract.
- **Live mode by default.** `ALLOW_LIVE_EXTERNAL_ACTIONS` defaults
  to unset → all live-one jobs are refused at the gate.
- **A copy of Luis's bot code.** Nothing in `coo/import-luis-msa`
  is brought into this branch. The runner expects the operator
  to have that branch checked out locally and pointed at via
  `MSA_RTXRT_BOT_DIR`, or via the default path under
  `incoming/luis-msa-import/`.

### Operator setup (Claw computer)

1. Check out `coo/import-luis-msa` so the bot folder exists on disk.
2. `cd` into the repo root.
3. Install the bot's local Python deps inside that folder (per
   Luis's bot README — not Mission Control's concern).
4. Run a configuration check:

   ```sh
   python tools/local-runners/msa_rtxrt_runner.py
   ```

   The script prints which `MSA_RTXRT_BOT_DIR` it resolved, the
   live-mode env it sees, and the full list of dry-run + live-one
   commands it knows how to issue. It exits 0 without touching
   anything.

5. *(Once the backend bridge ships:)* set the operator token in the
   runner's env, then run with the `--poll` flag (to be added in
   the follow-up PR).

### Safety contract (hard-coded in the script)

- Default mode is dry-run. `DRY_RUN=true` is the implicit posture.
- Live-one jobs require ALL of these env vars on the Claw computer:
  - `ALLOW_LIVE_EXTERNAL_ACTIONS=true`
  - `CONFIRM_LIVE_TEST=YES`
  - `MAX_TEST_ACTIONS=1`
- Mass live runs are blocked. The runner has no `live_all_*` /
  `live_mass_*` / `live_batch_*` job kinds and the dispatch table
  refuses to construct one even if the queue asks for it.
- Secrets stay on the Claw computer. The runner never reads from
  Mission Control's `secrets_store` and never writes secrets back.
- The runner is started **manually** on the Claw computer. Mission
  Control cannot start it remotely.

### Job-kind catalog

| Kind | Maps to | Lives behind |
|---|---|---|
| `smoke` | `safety_guard.py --smoke` | Operator+, no external action |
| `dry_run_blast` | `blast_bot.py --dry-run` | Operator+ |
| `dry_run_dm` | `dm_bot.py --dry-run` | Operator+ |
| `dry_run_repost` | `repost_bot.py --dry-run` | Operator+ |
| `dry_run_builder` | `builder_bot.py --dry-run` | Operator+ |
| `dry_run_scan` | `scan_test.py --dry-run` | Operator+ |
| `live_one_blast` | `blast_bot.py --live-one --max-actions=1` | Owner + UI two-step confirm + runner safety gate |
| `live_one_dm` | `dm_bot.py --live-one --max-actions=1` | Owner + UI two-step confirm + runner safety gate |
| `live_one_repost` | `repost_bot.py --live-one --max-actions=1` | Owner + UI two-step confirm + runner safety gate |
| `live_one_builder` | `builder_bot.py --live-one --max-actions=1` | Owner + UI two-step confirm + runner safety gate |
| `live_one_scan` | `scan_test.py --live-one --max-actions=1` | Owner + UI two-step confirm + runner safety gate |

### Next steps (follow-up PR)

To make the bot actually controllable from `hq.digidle.com`, the
follow-up PR needs to add:

1. **Backend job model.** A new SQLModel table — call it
   `msa_rtxrt_jobs` — with columns: `id`, `kind`, `status`
   (`queued | running | succeeded | failed | blocked`),
   `requested_by`, `created_at`, `started_at`, `finished_at`,
   `summary` (short, privacy-safe), `stdout_excerpt` (truncated).
   Requires an Alembic migration.

2. **Backend job endpoints.** Under a new router
   (`backend/app/api/msa_rtxrt.py`) with prefix `/msa-rtxrt`:

   - `GET /msa-rtxrt/jobs?status=…` — paginated job feed. Operator+
     can read. Returns privacy-safe summaries only.
   - `POST /msa-rtxrt/jobs` — enqueue. Body: `{kind}`. Operator+
     for dry-run; `require_owner` + body
     `{kind, confirm_live: "YES", max_test_actions: 1}` for
     live-one. Writes an `audit_events` row.
   - `GET /msa-rtxrt/runner/poll` — long-poll for the runner.
     Returns the next queued job and atomically marks it `running`.
     Auth: the existing gateway-token mechanism (no new secret).
   - `PATCH /msa-rtxrt/jobs/{id}` — runner updates status + summary
     + stdout excerpt. Auth: same gateway-token gate.

3. **Frontend wiring.** Replace the stubbed `handleSubmitJob` and
   `handleRefresh` in `frontend/src/app/bots/msa-rtxrt/page.tsx`
   with calls to the four endpoints above. Render real
   `runnerStatus` + recent jobs returned by the API.

4. **Runner poll loop.** Replace `main()` in `msa_rtxrt_runner.py`
   with a real polling loop that calls `GET /msa-rtxrt/runner/poll`
   on a 5s interval, runs `run_job`, and `PATCH`es the job back.

5. **Per-creator credentials path.** Live-one jobs that need
   AdsPower / X / OnlyFans credentials must read from a creator
   credentials store on the Claw computer (NOT Mission Control's
   `secrets_store`). That's a follow-up beyond the basic bridge.

### Tests

```sh
pytest tools/local-runners/test_msa_rtxrt_runner.py
```

Covers:

- Safety gate denials for each missing / wrong flag.
- Safety gate allow path when all three live-mode flags are set.
- Command builder argv shape and `shell=False` posture.
- Command builder denies live-one without gate pass, allows with.
- Mass-live block catches `live_all_*` / `live_mass_*` /
  `live_batch_*` strings.
- Bot-dir resolution honors `MSA_RTXRT_BOT_DIR` override and falls
  back to the expected `incoming/luis-msa-import` path.
