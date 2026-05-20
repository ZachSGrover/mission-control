# MSA RT/X — multi-runner setup

How to add Luis's Mac, Zach's laptop, a future Mac mini, or any other
computer as an MSA RT/X runner. Pair this with
`docs/operations/msa-rtxrt-handoff.md` (the day-to-day operating manual).

## Concept in one paragraph

Mission Control web (`hq.digidle.com/bots/msa-rtxrt`) is the control
panel. The Render-hosted backend stores jobs and a heartbeat per
runner. Each *runner computer* runs a local Python poll loop with its
own unique `MSA_RTXRT_RUNNER_ID` (e.g. `claw-1`, `luis-mac-1`,
`zach-laptop-1`, `mac-mini-1`). The selector in the top bar of the
dashboard targets a specific runner — only that runner can claim the
job. Every machine has its own AdsPower, its own bot folder, its own
configs, its own logs. Nothing about the local environment leaks back
into the repo or the backend beyond job status + privacy-safe excerpts.

## Examples of runner_ids

| ID | Where it lives | Owner |
|---|---|---|
| `claw-1` | The original Mac Studio / claw computer | Zach |
| `luis-mac-1` | Luis's day-to-day Mac | Luis |
| `zach-laptop-1` | Zach's MacBook on the road | Zach |
| `mac-mini-1` | Future dedicated runner box | Zach |

Pick a short, dash-separated, lower-case ID. The backend stores it
verbatim and renders it in the UI selector. It is **not** secret — but
it should also not contain machine fingerprints, hostnames, IPs, or
operator personal data. The ID is also what shows up in the run-history
"who handled this job" column.

## Setup steps for a new runner computer

Repeat on each machine. Substitute the actual `MSA_RTXRT_RUNNER_ID`
your operator owns (e.g. `luis-mac-1`).

### 1. Get the code on the machine

You can either clone the full Mission Control repo or copy just the
runner package + the Luis bot folder. The full repo is the simplest:

```sh
git clone https://github.com/ZachSGrover/mission-control.git ~/mission-control
cd ~/mission-control
git checkout main
```

The runner only reads from `tools/local-runners/` and from whatever
path `MSA_RTXRT_BOT_DIR` points at, so a sparse checkout is fine if
you'd rather not pull the whole tree.

### 2. Install Python deps

The runner itself uses only the Python stdlib. The bot scripts under
Luis's folder use `requests` + `playwright`. Install into the user
site so no sudo is needed:

```sh
python3 -m pip install --user requests playwright
```

(Playwright's Chromium binary download is NOT required — the bots
connect to AdsPower's browser via CDP.)

### 3. Place the bot folder locally

The bot scripts live outside of `main` (in the Luis import worktree).
On a non-Claw machine, copy the folder over once:

```sh
mkdir -p ~/msa-rtxrt-bot
# Sync the folder from the source machine (e.g. claw-1) or from
# Luis's archive. Never commit it to main — the worktree exclude
# rules block auftrag.json / contacts.json / cookies / sessions.
```

The runner does NOT read the bot's per-account configs. Those stay on
each machine separately.

### 4. Create the local `.msa-rtxrt-runner.env`

Place it at the repo root (or wherever you'll run the runner from).
Set permissions tight:

```sh
cd ~/mission-control
touch .msa-rtxrt-runner.env
chmod 600 .msa-rtxrt-runner.env
```

Edit `.msa-rtxrt-runner.env`:

```sh
MSA_RTXRT_BACKEND_URL=https://mission-control-jbx8.onrender.com
MSA_RTXRT_RUNNER_TOKEN=<the_token_value_from_render_env>
MSA_RTXRT_RUNNER_ID=luis-mac-1
MSA_RTXRT_BOT_DIR=/Users/luis/msa-rtxrt-bot/Automation [RTxRT]

# Optional. Required only when this machine will run live actions
# (AdsPower-driven). Smoke + dry-run never need it.
# ADSPOWER_API_KEY=<value>
```

| Var | Purpose |
|---|---|
| `MSA_RTXRT_BACKEND_URL` | Render-hosted Mission Control backend. Same value on every runner. |
| `MSA_RTXRT_RUNNER_TOKEN` | Shared secret. Same value on every runner. Must match Render env. **Never** commit. |
| `MSA_RTXRT_RUNNER_ID` | Unique per machine. The Mission Control selector lists this string. |
| `MSA_RTXRT_BOT_DIR` | Local path to Luis's `Automation [RTxRT]` folder on this machine. |
| `ADSPOWER_API_KEY` | Only used by the bot scripts at live runtime; the runner itself never sends it anywhere. |

> All `.env` files are blocked from `git add` by the worktree's
> `info/exclude` rules. The token specifically must never appear in the
> repo, in any database row, in any API response, or in any log line.

### 5. Verify wiring without polling

Run preflight:

```sh
cd ~/mission-control
set -a && . ./.msa-rtxrt-runner.env && set +a
python3 tools/local-runners/msa_rtxrt_runner.py --preflight
```

Exit 0 = ready to take work. Exit 1 = at least one precondition is not
met; the JSON report tells you which. The report includes:

- `env.runner_id` (must equal your `MSA_RTXRT_RUNNER_ID`)
- `env.backend_url_set`, `env.runner_token_set` (booleans only — token
  value is never printed)
- `env.bot_dir_exists`
- `backend.health.reachable` (200 on `/healthz`)
- `backend.runner_token_check.accepted` (200 on `/runner/poll` with the
  configured token; idempotent, never consumes a job)
- `python_imports` (`requests`, `playwright`, `playwright.sync_api`)
- `adspower.api_reachable` (true only if AdsPower is running locally)
- `config_files` (presence of `auftrag.json` / `contacts.json` /
  `blast_auftrag.json` / `repost_auftrag.json` / `schedule.json`)
- `safety.mass_live_kinds_blocked` (always true — by code)
- `safety.live_one_requires_three_flags` (always true — by code)
- `safety.bot_dir_safety_guard_module_present`

For smoke + dry-run, only the env + backend + python_imports rows must
be green. AdsPower + config files only matter for live actions.

### 6. Start the runner

```sh
cd ~/mission-control
nohup python3 -u tools/local-runners/msa_rtxrt_runner.py --poll \
  > .msa-rtxrt-runner.log 2>&1 &
echo $! > .msa-rtxrt-runner.pid
```

(Or use the `./.start-msa-rtxrt-runner.sh` helper that ships on the
Claw computer — copy it over and adjust if useful.)

You should see in the log within seconds:

```
Polling https://mission-control-jbx8.onrender.com/api/v1/msa-rtxrt/runner/poll every 5.0s as luis-mac-1…
```

### 7. Confirm in Mission Control

Open `https://hq.digidle.com/bots/msa-rtxrt`, refresh. The runner
selector in the top bar now includes `luis-mac-1` (or whatever ID you
chose), with `online · idle` next to it. Pick it, then any **Run smoke
test** / **Dry-run *** button targets that runner.

## Targeting rules

- Each job carries a `target_runner_id`. The poll endpoint claims a row
  only if it's queued AND (`target_runner_id` is NULL OR matches the
  calling runner's id).
- Rows with NULL `target_runner_id` are claimable by any runner — this
  is the back-compat path for jobs created before multi-runner targeting
  landed. The Mission Control UI v2 always populates the field.
- Mass-live job kinds remain blocked at four independent layers (UI →
  backend validate_kind → runner is_mass_live_kind → bot's
  `safety_guard.require_live_or_exit()`). Multi-runner does NOT
  expand the surface — every runner still refuses anything that smells
  like `live_all` / `live_mass` / `live_batch` / `live_many`.
- Live-one remains owner-only + safety-flag-gated. Per-runner, the
  three local env vars (`ALLOW_LIVE_EXTERNAL_ACTIONS`, `CONFIRM_LIVE_TEST`,
  `MAX_TEST_ACTIONS`) still must be set in *that machine's* runner
  shell only — never in the persistent `.msa-rtxrt-runner.env`.

## Per-machine local files

Every runner machine owns its own copies. None of these are committed:

| File | Owns | Notes |
|---|---|---|
| `.msa-rtxrt-runner.env` | Each runner machine | Token + runner ID + bot dir. `chmod 600`. |
| `.msa-rtxrt-runner.log` | Each runner machine | The local poll loop's output. |
| `.msa-rtxrt-runner.pid` | Each runner machine | Tracking only — the helper script reads it. |
| Luis's `auftrag.json` / `contacts.json` / `blast_auftrag.json` / `repost_auftrag.json` | Each runner machine | Authored locally from the `.example.json` templates. |
| AdsPower profile cookies / X session cookies | Each runner machine | Lives under AdsPower's data dir on that machine. |

## Privacy guarantees that still hold under multi-runner

- The runner token is shared-secret material between Render's backend
  and each runner's `.msa-rtxrt-runner.env`. It is never stored in any
  database row, any audit log, any API response, or any Mission
  Control UI rendering. Adding a new runner does not change this.
- `runner_id` is operator-chosen and contains no machine fingerprint,
  IP, hostname, or path.
- Job summaries / stdout / stderr excerpts are capped server-side and
  by the runner before PATCH. Adding runners does not change the caps.
- `GET /runner/status` is operator+ Clerk-gated. The endpoint surfaces
  per-runner `last_seen_at`, `seconds_since_seen`, online/offline,
  idle/busy, `can_accept_jobs`, and `jobs_recently_handled` — never the
  token, never any local path, never any job content.
- The local `--preflight` report prints booleans for token presence,
  never the value.

## Adding the second / third / fourth runner

Step 1-7 above, with a different `MSA_RTXRT_RUNNER_ID`. Nothing else
changes — same backend URL, same token, same bot scripts. The selector
in Mission Control auto-populates from the heartbeat list.

## Removing a runner

Just stop its poll loop and let the heartbeat row age out. The row
will show `offline · <seconds_since_seen>` in the selector until you
explicitly delete it from the database (or it can stay — it's
harmless). No queued job can be assigned to an offline runner from the
UI: the runner-selector dropdown disables buttons when an offline
runner is selected, and the operator can pick a different runner to
make progress.

## See also

- `docs/operations/msa-rtxrt-handoff.md` — operating manual + live-one checklist
- `docs/operations/product-map.md` — Bots vs Agents vs Workflows
- `tools/local-runners/README.md` — runner internals + safety contract
