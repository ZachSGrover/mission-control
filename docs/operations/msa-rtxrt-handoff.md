# MSA RT/X — Luis handoff + live-one readiness

Operating manual for the MSA RT/X Automation Bot bridge. Read this once;
reference whenever.

## Architecture in one paragraph

Mission Control web (`hq.digidle.com/bots/msa-rtxrt`) is the control
panel. The Render-hosted backend stores job intent + safe audit logs.
The actual automation runs on Zach's Claw computer via a local Python
runner that polls the backend, executes the matching script inside
Luis's bot folder, and reports status back. **No live automation
runs from Mission Control.** Every Mission Control button either
enqueues a smoke / dry-run job (no external side effects), or — for
owner-only live-one — enqueues a single capped action that the Claw
runner refuses unless three local env flags are set.

## What Luis can do

| Capability | Notes |
|---|---|
| Open `hq.digidle.com/bots/msa-rtxrt` from phone or laptop | Sign in via Clerk; operator role required |
| See live runner status (online / idle / busy / offline) | Backed by the heartbeat endpoint; flips in real time as runner polls |
| Click **Run smoke test** | Enqueues a `smoke` job — no external action |
| Click any dry-run button | Enqueues `dry_run_*` — Luis's bot refuses to actually send via its own `safety_guard.require_live_or_exit()` unless DRY_RUN=false AND ALLOW_LIVE_EXTERNAL_ACTIONS=true |
| See run history (queued / running / succeeded / failed / blocked) | Privacy-safe summary + stdout/stderr excerpts, capped server-side |
| Edit local configs on the Claw computer (auftrag.json, contacts.json) | NEVER commit; the worktree's exclude rules already block these |
| Tell Zach when AdsPower / X is ready | Required before any live test |

## What only Zach (owner) can do

| Capability | Notes |
|---|---|
| Arm + confirm live-one | UI surface is owner-gated; backend also rechecks role |
| Set the three live-mode env vars on the Claw shell | `ALLOW_LIVE_EXTERNAL_ACTIONS=true` + `CONFIRM_LIVE_TEST=YES` + `MAX_TEST_ACTIONS=1` |
| Restart the runner with live-mode env in scope | Without restart, the runner's env doesn't pick up live flags |
| Change Render / Vercel / Clerk / DNS / billing | Production surfaces |
| Rotate the runner token | `openssl rand -hex 32 | pbcopy` → paste into Render → restart runner with new value in `.msa-rtxrt-runner.env` |
| Approve merging changes to `main` | Default branch protection |

**Mass-live actions do not exist anywhere in the system** and are
blocked at four independent layers:

1. UI: no mass-live button exists, no kind option, no way to compose
2. Backend `validate_kind`: rejects any `kind` containing `live_all` / `live_mass` / `live_batch` / `live_many`
3. Local runner `is_mass_live_kind`: same rejection before any subprocess fires
4. Bot's own `safety_guard.require_live_or_exit()`: refuses without explicit live opt-in regardless of caller

## Day-to-day Claw operations

```sh
# Start / restart the runner
cd /Users/zachary/mission-control-postmerge-main && ./.start-msa-rtxrt-runner.sh

# Tail the runner log
tail -F /Users/zachary/mission-control-postmerge-main/.msa-rtxrt-runner.log

# Stop the runner
kill "$(cat /Users/zachary/mission-control-postmerge-main/.msa-rtxrt-runner.pid)"

# Verify everything is wired without polling
cd /Users/zachary/mission-control-postmerge-main && \
  set -a && . ./.msa-rtxrt-runner.env && set +a && \
  python3 tools/local-runners/msa_rtxrt_runner.py --preflight
```

The `--preflight` command returns JSON. Exit 0 means *ready to take
work*. Exit 1 means at least one precondition isn't met (and the JSON
explains which). It only hits two HTTP endpoints: `/healthz` (no
auth, no side effect) and `/runner/poll` (idempotent, returns
`{"job": null}` if no work is queued). It never opens a browser, never
calls X, never sends a DM.

## Local config workflow (never commit these)

The Luis bot folder uses example templates that get copied to working
configs on the Claw computer only. **Never commit the working
versions.** The repo's worktree-exclude rules already block them.

| Example | Working name | Holds |
|---|---|---|
| `auftrag.example.json` | `auftrag.json` | DM order — target handles + message text |
| `contacts.example.json` | `contacts.json` | Recipient lookup |
| (none) | `blast_auftrag.json` | Blast bot order (if used) |
| (none) | `repost_auftrag.json` | Repost bot order (if used) |
| `schedule.json` | `schedule.json` | Optional auto-run schedule |

Recommended Claw-only workflow:

```sh
cd "/Users/zachary/mission-control-coo-access/incoming/luis-msa-import/MSA/Monthly revenue/Automation [RTxRT]"

# Start from the example, fill in real values locally only:
cp auftrag.example.json auftrag.json
cp contacts.example.json contacts.json
# Edit auftrag.json + contacts.json in your editor.

# Verify the files exist (preflight only reports yes/no, never contents):
python3 ../../../../../tools/local-runners/msa_rtxrt_runner.py --preflight | grep -A 8 '"config_files"'
```

The runner never reads these files itself — it only spawns the bot
scripts as subprocesses. The bot scripts read them from disk inside
their own process and never leak them across the bridge. Operator-facing
job summaries are capped at 256 chars and never include the file
contents.

## The chicken-and-egg fix (heartbeat)

Older versions of this UI derived runner status only from the most
recent jobs. That meant the **Run smoke test** button stayed disabled
forever on a fresh deploy: no job → status = offline → button disabled.

The current bridge has a real heartbeat:

1. On every valid `/runner/poll` request (even an idle one), the
   backend upserts a row in `msa_rtxrt_runner_heartbeats` with
   `runner_id`, `last_seen_at`, and `last_status` (`idle` / `busy`).
2. The operator-facing `GET /runner/status` endpoint returns the
   aggregate snapshot. `any_online === true` when any runner has
   been seen within `freshness_seconds` (default 90 s).
3. The frontend fetches both `/jobs` and `/runner/status` on each
   refresh and derives:
   - **busy** ← any job currently `running`
   - **idle** ← heartbeat says `any_online`
   - **offline** ← otherwise
4. If `/runner/status` is unavailable (e.g. during a deploy), the
   UI falls back to the legacy jobs-only derivation. Graceful
   degradation — never locks.

Run buttons (smoke + dry-run) enable when status is `idle`. Live-one
stays owner-gated regardless.

## Live-one readiness checklist (do NOT execute yet)

Use this when Zach is genuinely ready to do one controlled live action.
Do not execute any step here as part of routine operations.

1. **AdsPower running** on the Claw computer. Verify via:
   ```sh
   python3 tools/local-runners/msa_rtxrt_runner.py --check-adspower
   ```
   Output should be `{"api_reachable": true, ...}`. Exit 0.
2. **Correct X profile logged in** inside the AdsPower profile that
   `auftrag.json` references.
3. **Test/burner recipient only** in `auftrag.json` and `contacts.json`.
   The bot's `--max-actions=1` means exactly one DM goes out; pick
   the recipient with that in mind.
4. **`auftrag.json` and `contacts.json` copied from examples and
   filled in** on the Claw computer. The repo never sees these.
5. **Set the three live-mode env vars in the runner's shell only**
   (NOT in `.msa-rtxrt-runner.env` — leave the persistent file
   dry-run by default):
   ```sh
   export ALLOW_LIVE_EXTERNAL_ACTIONS=true
   export CONFIRM_LIVE_TEST=YES
   export MAX_TEST_ACTIONS=1
   ```
6. **Restart the runner** so the new env is in scope:
   ```sh
   kill "$(cat .msa-rtxrt-runner.pid)"
   ./.start-msa-rtxrt-runner.sh
   ```
   (The helper sources `.msa-rtxrt-runner.env` and inherits the
   surrounding shell env, so the three flags travel into the
   runner process.)
7. **As owner in the UI**: open `/bots/msa-rtxrt`, scroll to the
   red **Live-one test** section, **Arm live-one**, **pick exactly
   one `live_one_*` kind**, **Confirm**.
8. **Verify one action only**. Run History should show the job
   succeed; the bot's stdout excerpt should mention exactly one
   DM/repost/etc.
9. **Remove the live env vars immediately afterward**:
   ```sh
   unset ALLOW_LIVE_EXTERNAL_ACTIONS CONFIRM_LIVE_TEST MAX_TEST_ACTIONS
   ```
10. **Restart the runner in dry-run mode** so the next click can't
    fire another live action by accident:
    ```sh
    kill "$(cat .msa-rtxrt-runner.pid)"
    ./.start-msa-rtxrt-runner.sh
    ```

Until every step above is satisfied, the four safety layers will
refuse to do anything live — that's defense in depth and is the
intended posture.

## Privacy + security guarantees

- The runner token is shared-secret material between Render's backend
  env and the Claw computer's `.msa-rtxrt-runner.env`. It never lands
  in any database row, any audit log, any API response, or any
  Mission Control UI. Rotating it on either side requires updating
  both.
- Job summaries / stdout / stderr excerpts are capped at 256 / 2048 /
  2048 chars respectively, both at the runner (before PATCH) and at
  the backend (before write). Long output cannot leak through the
  bridge.
- `runner_id` is operator-chosen (`claw-1` by default) and contains
  no machine fingerprint, IP, hostname, or path.
- Local files (`.msa-rtxrt-runner.env`, `.msa-rtxrt-runner.log`,
  `.msa-rtxrt-runner.pid`, `.start-msa-rtxrt-runner.sh`, and the
  Luis bot's `auftrag.json` / `contacts.json` / cookies / sessions)
  are excluded via the per-worktree `info/exclude` and cannot be
  staged with `git add`.

## Endpoint reference

| Method + path | Auth | Used by |
|---|---|---|
| `GET /api/v1/msa-rtxrt/jobs?limit=N&status=...` | Clerk operator+ | Frontend run-history + page refresh |
| `POST /api/v1/msa-rtxrt/jobs` | Clerk operator+ (owner for live-one) | Frontend run buttons |
| `GET /api/v1/msa-rtxrt/runner/poll?runner_id=...` | Runner token header | Claw runner poll loop |
| `PATCH /api/v1/msa-rtxrt/jobs/{id}` | Runner token header | Claw runner status PATCH |
| `GET /api/v1/msa-rtxrt/runner/status` | Clerk operator+ | Frontend status pill |

Audit events written by the bridge:

- `msa_rtxrt.job.create` / `.create.live_one`
- `msa_rtxrt.job.create.blocked_mass_live`
- `msa_rtxrt.job.create.blocked_safety_gate`
- `msa_rtxrt.job.create.denied_non_owner`
- `msa_rtxrt.job.claimed`
- `msa_rtxrt.job.succeeded` / `.failed` / `.blocked`

## See also

- `docs/operations/msa-rtxrt-multi-runner.md` — adding Luis's Mac, Zach's laptop, or a future Mac mini as additional runners
- `docs/operations/product-map.md` — Bots vs Agents vs Workflows
- `docs/operations/local-web-parity.md` — keeping the Claw machine on main
- `tools/local-runners/README.md` — runner internals + safety contract
