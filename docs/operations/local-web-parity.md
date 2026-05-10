# Local ↔ Web parity runbook

When `hq.digidle.com` and the local Mission Control / Digidle OS app look
different, the cause is almost always one of:

1. The local folder is on a feature branch, not `main`.
2. The local Next.js production server is serving a stale `.next` build.
3. The local app has a separate launchd service that wasn't restarted after
   a branch switch.
4. The chat surface is in a different gateway state on each side (see
   `docs/operations/openclaw-gateway-status.md` — that's a chat issue, not a
   parity issue).

This runbook covers cases 1–3. It is **read-only by default** — none of the
inspection steps modify anything. Modification steps are clearly marked.

## Worktree layout (snapshot)

This repo has multiple long-lived worktrees on disk. The ones that matter
for parity:

| Folder                                          | Branch (intended)                          | Role                                   |
| ----------------------------------------------- | ------------------------------------------ | -------------------------------------- |
| `/Users/zachary/mission-control`                | `main` (currently detached)                | Primary clone — origin of all worktrees |
| `/Users/zachary/mission-control-main`           | `main`                                     | Intended canonical local checkout      |
| `/Users/zachary/mission-control-rt-bot`         | `feat/x-dm-bot-rtxrt-mvp-isolated`        | RT bot work — do NOT run the local app from here |
| `/Users/zachary/mission-control-of-intelligence`| Major Security source branch              | Security work — read-only, do not run  |
| `/Users/zachary/mission-control-recovery`       | `fix/mission-control-parity-recovery`     | This sprint                            |

The other `mission-control-*` folders are short-lived hotfix worktrees and
should not be running the local app.

## Inspection — what should I check first?

These four `git` commands answer "is local on main?" without touching anything.

```sh
# 1. Which branch is the canonical local checkout on?
git -C /Users/zachary/mission-control-main branch --show-current

# 2. Is it in sync with origin/main?
git -C /Users/zachary/mission-control-main fetch origin
git -C /Users/zachary/mission-control-main log --oneline main..origin/main
git -C /Users/zachary/mission-control-main log --oneline origin/main..main

# 3. Are there uncommitted edits hiding the truth?
git -C /Users/zachary/mission-control-main status --short

# 4. Where do all worktrees point?
git -C /Users/zachary/mission-control worktree list
```

Expected healthy output:

- `branch --show-current` → `main`
- both `log` commands → empty (zero ahead, zero behind)
- `status --short` → empty
- `worktree list` → shows `mission-control-main` on `[main]`, RT bot on its
  isolated branch, recovery on `fix/mission-control-parity-recovery`

If any of these are wrong, see the next section.

## Inspection — which local process is serving the app?

```sh
# Production Next.js server (PID + cwd)
launchctl print gui/$(id -u)/com.digidle.next-server | grep -E 'pid|state'
lsof -p "$(launchctl print gui/$(id -u)/com.digidle.next-server \
  | awk '/^[ \t]+pid =/{print $3}')" 2>/dev/null | grep cwd

# Local FastAPI backend
launchctl print gui/$(id -u)/com.digidle.backend | grep -E 'pid|state'

# OpenClaw runtime (the chat gateway)
launchctl print gui/$(id -u)/com.digidle.openclaw | grep -E 'pid|state'

# Cloudflare tunnel (terminates wss://claw.digidle.com)
launchctl print gui/$(id -u)/com.cloudflare.cloudflared | grep -E 'pid|state'
```

`cwd` on the next-server PID tells you which folder is actually being
served. If it points at a feature-branch folder, that's the parity break.

## Restoring parity (operator-friendly)

These steps fix the **most common** case: the local checkout drifted onto
a feature branch.

### Step 1 — pick the canonical local folder

By convention, `/Users/zachary/mission-control-main` is the folder the
local app should serve from. Do **not** make `mission-control-recovery`
the canonical local — it's a temporary worktree for this audit sprint.

### Step 2 — back off RT bot work without losing it

If the canonical local folder is currently on the RT bot branch, the work
must not be discarded. Two safe options:

- **Option A — already preserved elsewhere.** The `mission-control-rt-bot`
  worktree on disk is on `feat/x-dm-bot-rtxrt-mvp-isolated`. If that's
  current, you can safely switch the canonical folder back to `main`
  without losing RT bot work.
- **Option B — commit + push the in-flight RT branch first.** From the
  canonical folder:

  ```sh
  cd /Users/zachary/mission-control-main
  git status
  # If anything is uncommitted on the RT branch and not already in the
  # rt-bot worktree, stage and commit it on the RT branch first.
  git add -p
  git commit -m "WIP: rt-bot pre-parity-restore"
  git push origin feat/x-dm-bot-rtxrt-mvp
  ```

Do **not** stash or reset without a record. The audit doc explicitly
warned that the untracked `BotPermissionsEditor.*` files in the RT
worktree are real files on main (PR #26 landed them later) and will
collide on checkout. Use a worktree, not a stash.

### Step 3 — switch the canonical folder back to main

```sh
cd /Users/zachary/mission-control-main
git fetch origin
git checkout main
git pull --ff-only origin main
git status --short      # should be empty
```

If `git checkout main` complains about untracked files that would be
overwritten (BotPermissionsEditor or others), they are files that exist
on main but the RT branch wasn't carrying them yet. Move them out of the
way rather than deleting:

```sh
mkdir -p ~/.mission-control/parity-restore-$(date +%F)
git ls-files --others --exclude-standard | xargs -I {} mv {} ~/.mission-control/parity-restore-$(date +%F)/
```

Then re-attempt `git checkout main`.

### Step 4 — rebuild the local Next.js bundle

The launchd service serves the static `.next` build. After switching
branches you must rebuild, then restart the service:

```sh
cd /Users/zachary/mission-control-main
npm install
npm run build
launchctl kickstart -k gui/$(id -u)/com.digidle.next-server
```

`kickstart -k` is a hard restart — safer than `stop` then `start` because
launchd will not re-spawn into the old `.next` between the two commands.

### Step 5 — verify parity end-to-end

1. Visit `http://localhost:3000` in a browser. Hard reload (Shift+Reload).
2. Sidebar should match `https://hq.digidle.com`: Chat, Memory, Projects,
   Memory, Calendar, Hermes, Boards, Agents, Control, Workflows, Skills,
   (Bots, Bot Builder — owner/operator only), Logs, Guide, Settings,
   Usage Tracker, (Users, Integrations, Security — owner only).
3. Chat header should not say "Offline" if the gateway token is configured
   in this browser. See `docs/operations/openclaw-gateway-status.md`.

## Sanity check — what should NEVER happen

- Local app being served from `mission-control-rt-bot` or any
  `mission-control-of-intelligence`-style branch. Those are scratch
  worktrees, not deploy sources.
- The canonical local folder having uncommitted edits to files that exist
  on origin/main but are tracked as `?? untracked` locally — that means
  the branch is behind and the files are conflicting.
- Two separate `next-server` processes serving the same port. Check
  `lsof -i :3000` if you suspect this.

## When the chat pill says "Offline" but the rest of the app looks fine

That's not a parity issue. It's a gateway issue. See the chat header
itself — the pill now distinguishes:

- "Gateway not configured" — no WS URL for the current host
- "Gateway token missing" — paste the token in Settings → Gateway
- "Gateway unreachable" — Cloudflare Access expired, or the token doesn't
  match the gateway's expected value, or the local runtime is down
- "Connecting…" — handshake in flight, give it a beat
- "Online" — fully connected

The pill includes a **Reconnect** button when it can usefully retry, and
a link to **Settings** when the token is missing.

## See also

- `docs/operations/product-map.md` — what each module (Bots / Agents /
  Workflows / Boards / Gateway) actually is
- `docs/operations/qc-status.md` — current state of the QC bot
- `docs/operations/major-security-status.md` — read-only snapshot of the
  Major Security branch
- `docs/operations/ofi-status.md` — OnlyFans Intelligence audit
