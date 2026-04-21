// Mission Control — Discord gateway bridge.
//
// A minimal Render background worker that holds a discord.js gateway
// connection and forwards each inbound user message to the Mission Control
// backend (cloud) at /api/v1/discord/message.
//
// Design:
//   • Single process, single gateway.  No state.  No DB.
//   • Auto-reconnect is built into discord.js — we simply log the events.
//   • Replay protection is enforced on the backend via message_id dedup
//     (Redis ZSET, 24 h TTL).  Every forward carries `message_id`, so a
//     gateway RESUME that re-delivers a message is a no-op downstream.
//   • We deliberately DO NOT echo the bot's reply back through Discord here.
//     The backend already calls OpenAI; if/when we wire a reply path we'll
//     add an authenticated webhook that hits channel.send().
//
// Env:
//   DISCORD_BOT_TOKEN       — Clawdia 2 bot token (required)
//   MC_BACKEND_URL          — e.g. https://mission-control-jbx8.onrender.com (required)
//   MC_BACKEND_AUTH_TOKEN   — shared bearer token; matches backend LOCAL_AUTH_TOKEN
//   MC_BRIDGE_DEBUG         — "1" for verbose stdout

import { Client, Events, GatewayIntentBits, Partials } from "discord.js";

const DISCORD_BOT_TOKEN     = (process.env.DISCORD_BOT_TOKEN     || "").trim();
const MC_BACKEND_URL        = (process.env.MC_BACKEND_URL        || "").replace(/\/+$/, "");
const MC_BACKEND_AUTH_TOKEN = (process.env.MC_BACKEND_AUTH_TOKEN || "").trim();
const DEBUG                 = process.env.MC_BRIDGE_DEBUG === "1";

if (!DISCORD_BOT_TOKEN) {
  console.error("[bridge] FATAL: DISCORD_BOT_TOKEN is not set");
  process.exit(1);
}
if (!MC_BACKEND_URL) {
  console.error("[bridge] FATAL: MC_BACKEND_URL is not set");
  process.exit(1);
}

const log = (...args) => console.log(new Date().toISOString(), "[bridge]", ...args);
const dbg = (...args) => DEBUG && log("[debug]", ...args);

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.DirectMessages,
  ],
  partials: [Partials.Channel],
});

// ── Lifecycle logs (ops visibility) ──────────────────────────────────────────
client.once(Events.ClientReady, (c) => {
  log(`ready  username=${c.user?.tag}  id=${c.user?.id}`);
});
client.on(Events.ShardReady,       (id) => log(`shard.ready   id=${id}`));
client.on(Events.ShardReconnecting,(id) => log(`shard.reconnect id=${id}`));
client.on(Events.ShardResume,      (id, replayed) => log(`shard.resume  id=${id} replayed=${replayed}`));
client.on(Events.ShardDisconnect,  (ev, id) => log(`shard.disconnect id=${id} code=${ev?.code}`));
client.on(Events.ShardError,       (err, id) => log(`shard.error id=${id} error=${err?.message}`));
client.on(Events.Error,            (err) => log(`client.error ${err?.message}`));
client.on(Events.Warn,             (msg) => log(`client.warn  ${msg}`));

// ── Message forwarding ───────────────────────────────────────────────────────
async function forward(message) {
  const body = {
    text:        message.content || "",
    channel_id:  message.channelId || null,
    user:        message.author?.username || null,
    message_id:  message.id || null,
  };
  const headers = { "Content-Type": "application/json" };
  if (MC_BACKEND_AUTH_TOKEN) headers["Authorization"] = `Bearer ${MC_BACKEND_AUTH_TOKEN}`;

  const started = Date.now();
  try {
    const res = await fetch(`${MC_BACKEND_URL}/api/v1/discord/message`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    const elapsed = Date.now() - started;
    if (!res.ok) {
      log(`forward.http_${res.status} ms=${elapsed} channel=${body.channel_id} msg=${body.message_id}`);
      return null;
    }
    const data = await res.json();
    if (data.reason === "duplicate") {
      dbg(`forward.dup ms=${elapsed} msg=${body.message_id}`);
      return null;                       // backend de-duped — never reply twice
    }
    log(
      `forward.ok ms=${elapsed} used_ai=${data.used_ai} reason=${data.reason} ` +
      `provider=${data.provider} reply_chars=${(data.reply || "").length}`
    );
    return data;
  } catch (err) {
    log(`forward.error channel=${body.channel_id} msg=${body.message_id} err=${err?.message}`);
    return null;
  }
}

client.on(Events.MessageCreate, async (message) => {
  try {
    if (message.author?.bot) return;                // ignore other bots + self
    if (!message.content)    return;                // skip empty / attachments-only for now

    const reply = await forward(message);
    if (reply && reply.reply && !reply.used_ai === false) {
      // Only echo replies when the backend explicitly returns non-empty text.
      if (reply.reply.trim().length > 0) {
        try {
          await message.reply({ content: reply.reply.slice(0, 1900), allowedMentions: { repliedUser: false } });
        } catch (err) {
          log(`reply.error msg=${message.id} err=${err?.message}`);
        }
      }
    }
  } catch (err) {
    log(`handler.error msg=${message?.id} err=${err?.message}`);
  }
});

// ── Graceful shutdown — Render sends SIGTERM on redeploy ────────────────────
let shuttingDown = false;
async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  log(`shutdown signal=${signal}`);
  try { await client.destroy(); } catch {}
  process.exit(0);
}
process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT",  () => void shutdown("SIGINT"));
process.on("unhandledRejection", (err) => log(`unhandledRejection ${err?.message || err}`));

// ── Connect ──────────────────────────────────────────────────────────────────
log("logging in to Discord…");
client.login(DISCORD_BOT_TOKEN).catch((err) => {
  log(`login.failed ${err?.message}`);
  process.exit(1);
});
