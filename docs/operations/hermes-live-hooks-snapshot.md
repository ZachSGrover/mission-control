# Hermes live hooks — operational snapshot

**Snapshot taken:** 2026-04-28
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
| `system_event.sh`      | 3367  | `81c60f82f9ebc7eb994cd968c4d048c1b59253aa8a5515572542e281c39c1c9c` | `notify.sh` (legacy plain-string) |
| `health_claw_remote.sh`| 9032  | `71a02ee0d80c68e12b78ab535fb23cb85a2574bc8db497229533eb5bec85c9c5` | none — diagnostic only, prints to stdout |
| `notify.sh`            | 1154  | `0703d20f774cee57ca49dd0e1de843e165be2d684c62d6da18da446a2badd8c2` | (legacy sender — backs `system_event.sh`) |

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
| `system_event.sh.bak.spam.20260423_090057`   | 1546 | older — predates this initiative (Apr 23 spam fix) |

To roll back any rewired hook:
```
mv ~/.hermes/hooks/<hook>.sh.bak.20260428 ~/.hermes/hooks/<hook>.sh
```
The launchd jobs run the file directly, so the next tick uses the restored
script. No daemon restart needed.

## Recommended next hook to wire

`system_event.sh` (size 3367, SHA `81c60f82…`).

Why:
- Smallest remaining hook still on the legacy sender — minimal blast radius.
- A direct match for the existing `tpl_machine_restarted` template
  (boot/wake events).
- One-line transition logic — the rewire pattern from `claw_watchdog.sh`
  applies almost verbatim.
- Low-frequency: fires only on real boot or wake events, so dedupe state
  matters less.

After that:
- `health_claw_remote.sh` is a diagnostic script the user invokes manually
  via `/health claw`. It does not currently send alerts; rewiring would
  involve adding a structured-alert summary on failure. Lower priority —
  it's only relevant if you want the on-demand check to also post a
  Discord/Telegram digest of the failures it found.
- `notify.sh` itself stays in place as the legacy fallback. It is no
  longer the primary path for the two rewired hooks, but `system_event.sh`
  still depends on it. Once `system_event.sh` is rewired, `notify.sh` can
  be considered for retirement.

## What this snapshot is NOT

- Not a backup of secrets. `~/.hermes/.env` is deliberately excluded.
- Not a backup of channel or chat IDs. None appear in this file. (The
  hashed contents above will reveal them to anyone who reads the live
  scripts, since the production channel ID is hard-coded in `notify.sh` —
  but this snapshot itself does not surface them.)
- Not a substitute for version control. If you want hook history beyond
  the timestamped `.bak` files, place `~/.hermes/hooks/` under git in a
  separate repo or a dotfiles repo.
