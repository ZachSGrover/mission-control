# Hermes live hooks — operational snapshot

**Snapshot taken:** 2026-04-28 (refreshed after `system_event.sh` rewire)
**Snapshot scope:** `~/.hermes/hooks/` on Zach's MacBook (the only deployment).

This file is a fingerprint of the live hook scripts that drive Hermes
notifications and watchdog behaviour. `~/.hermes/hooks/` is **not** a git
repository, so this snapshot is the authoritative record of what was running
on the date above.

## Live hooks

| Hook | Size | SHA-256 | Wired to |
|------|------|---------|----------|
| `claw_watchdog.sh`     | 3866  | `769e16258f61c00e8d7b8d839ef29a58c66ed0f832fe7104fcf5bcb70bd26c9b` | `hermes-alert.sh` (structured) |
| `service_watchdog.sh`  | 12875 | `17d4a25c9f36d258445983f7771b4b04c3a47520b2296cc1e5fff65b1a2747f4` | `hermes-alert.sh` (structured) |
| `system_event.sh`      | 5505  | `e41047fbdace2f3e1a676a384720544df16e2789bb18e6d1061d7c0c4def9330` | `hermes-alert.sh` (structured) |
| `health_claw_remote.sh`| 9032  | `71a02ee0d80c68e12b78ab535fb23cb85a2574bc8db497229533eb5bec85c9c5` | none — diagnostic only, prints to stdout |
| `notify.sh`            | 1154  | `0703d20f774cee57ca49dd0e1de843e165be2d684c62d6da18da446a2badd8c2` | legacy sender — no active live-hook callers; kept for rollback compatibility |

To re-verify integrity later:
```
shasum -a 256 ~/.hermes/hooks/*.sh
```

## What "wired to `hermes-alert.sh`" means

The hook produces a structured alert (severity / system / evidence / likely
cause / business impact / recommended fix / repair prompt) by invoking
`/Users/zachary/mission-control-hermes-alerts/scripts/hermes-alert.sh`,
which posts a Discord embed plus a Telegram plain-text message to the home
destinations. Dedupe is applied via `--check-dedupe` to suppress flap noise.

"Wired to `notify.sh`" means the hook still posts a one-line emoji string
through the original sender. Same destinations, but no severity, evidence,
impact, fix, or repair prompt.

## Rollback backups present

| Backup file | Size | Original |
|-------------|------|----------|
| `claw_watchdog.sh.bak.20260428`              | 1570 | pre-rewire `claw_watchdog.sh` |
| `service_watchdog.sh.bak.20260428`           | 8291 | pre-rewire `service_watchdog.sh` |
| `system_event.sh.bak.20260428`               | 3367 | pre-rewire `system_event.sh` |
| `system_event.sh.bak.spam.20260423_090057`   | 1546 | older — predates this initiative (Apr 23 spam fix) |

To roll back any rewired hook:
```
mv ~/.hermes/hooks/<hook>.sh.bak.20260428 ~/.hermes/hooks/<hook>.sh
```
The launchd jobs run the file directly, so the next tick uses the restored
script. No daemon restart needed.

## Recommended next steps

All three production watchdog/event hooks (`claw_watchdog.sh`,
`service_watchdog.sh`, `system_event.sh`) are now wired to
`hermes-alert.sh`. No live hook still calls `notify.sh`.

Remaining candidates (lower priority):

- **`health_claw_remote.sh`** — diagnostic-only script invoked manually via
  `/health claw`. It does not currently send alerts; rewiring would mean
  posting a structured-alert summary when the on-demand check finds
  failures. Optional. Most useful if you want a Discord/Telegram digest
  after running the check, rather than just stdout.
- **Retire `notify.sh`?** — no live hook calls it anymore, but the file is
  still referenced by name in the rollback comments inside the rewired
  hooks. It can stay until you're confident none of the three rewired
  hooks need to be reverted; at that point it's safe to delete (and the
  rollback comments updated).
- **Daily summary aggregator** — documented in
  [hermes-alerts.md](hermes-alerts.md#daily-summary-format) but not yet
  built. Now that three hooks write dedupe state to `MC_STATE_DIR/alerts/`,
  there's enough material to render a useful daily digest.

## What this snapshot is NOT

- Not a backup of secrets. `~/.hermes/.env` is deliberately excluded.
- Not a backup of channel or chat IDs. None appear in this file. (The
  hashed contents above will reveal them to anyone who reads the live
  scripts, since the production channel ID is hard-coded in `notify.sh` —
  but this snapshot itself does not surface them.)
- Not a substitute for version control. If you want hook history beyond
  the timestamped `.bak` files, place `~/.hermes/hooks/` under git in a
  separate repo or a dotfiles repo.
