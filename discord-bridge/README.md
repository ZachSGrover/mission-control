# discord-bridge

Stateless Discord gateway → Mission Control backend forwarder.

Runs as a Render background worker defined in `../render.yaml`
(service `mission-control-discord-bridge`).

## Required env vars (Render dashboard)

| Var | Purpose |
|---|---|
| `DISCORD_BOT_TOKEN` | Clawdia 2 bot token |
| `MC_BACKEND_URL` | e.g. `https://mission-control-jbx8.onrender.com` |
| `MC_BACKEND_AUTH_TOKEN` | Shared bearer matching backend `LOCAL_AUTH_TOKEN` |
| `MC_BRIDGE_DEBUG` | `1` for verbose logs (optional) |

## Behaviour

- One gateway connection, auto-reconnect via discord.js.
- On each non-bot `MessageCreate`, POSTs to `/api/v1/discord/message` with
  `{ text, channel_id, user, message_id }`.
- Backend dedupes on `message_id` → a RESUMEd replay is a no-op.
- If the backend returns non-empty `reply`, the bridge replies in-channel.
- SIGTERM is respected for clean Render redeploys.
