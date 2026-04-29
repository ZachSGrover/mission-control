# OnlyFans Intelligence — Data Brain Roadmap

**Date:** 2026-04-28
**Status:** Planning only.  Nothing in this document enables code, deploys, writes, posts, or messages.
**Branch context:** `feat/ofi-daily-qc-scheduler`.  All current OFI work lives behind this branch.

This document is a **direction reset**.  Everything we have shipped to date
(account list, fans table, messages table, mass-message table, posting
insights, sync logs, etc.) was built as an OnlyMonster *dashboard*.  That
was the wrong frame.  This document defines the right one and the
six-month path to get there.

---

## 1. Product definition

**OnlyFans Intelligence is the agency's data brain.  It is not a
dashboard.**

A dashboard answers "what does the data look like right now?"  A data
brain answers "what does the agency need to *do* right now, given
everything we know about every creator we manage?"

The shift in three sentences:

- **Old frame:** ingest OnlyMonster, render the same tables OnlyMonster
  already renders, with extra columns.
- **New frame:** ingest *every* permitted signal we can get our hands on
  — OnlyMonster, direct OnlyFans, social platforms, manual operator
  notes — and turn that pile into per-creator memory, decisions, and
  agent actions.
- **Value test:** if a screen in OFI shows a row that doesn't help Zach
  decide what to do next, that screen is not pulling its weight.

OFI's product surface, end state, is six things in priority order:

1. **Critical alerts** — things broken right now.
2. **Today's problems** — chatters slipping, accounts decaying, fans
   leaking, refunds spiking.
3. **Creator game plans** — per-creator current strategy, what's
   working, what's failing.
4. **Chatter QC** — who is doing the work well, who isn't, why.
5. **Account health** — access status, posting cadence, sub funnel,
   churn.
6. **Revenue opportunities** — under-monetised fans, dormant whales,
   missed upsells, vault gaps.
7. **Content & persona** — strategy summary, voice/tone, vault
   structure, off-limits.
8. **What Zach needs to do** — a concrete action queue, not a metrics
   dump.

Raw rows (fans, messages, transactions, sync logs) are *plumbing* and
should live behind an "Investigate" drawer, not on the home screen.

---

## 2. Data we must collect

Goal: capture enough signal that an agent could, in principle, run an
account end-to-end with operator oversight.

### 2.1 OnlyMonster surface (already partly ingested)

| Domain | Have today | Status |
|---|---|---|
| Accounts | ✅ | `of_intelligence_accounts` |
| Fans (IDs only) | ✅ | `of_intelligence_fans` |
| Chatters | ✅ | `of_intelligence_chatters` |
| Transactions / chargebacks | ✅ | `of_intelligence_revenue` |
| Mass message stats | ✅ | `of_intelligence_mass_messages` |
| Posts | ✅ | `of_intelligence_posts` |
| Tracking & trial links | ✅ | `of_intelligence_tracking_links` |
| Per-chatter metrics window | ✅ | `of_intelligence_user_metrics` |
| Vault folders / lists / media | ⚠️ partial | some 400s on filters, retry path defined |
| Sync logs | ✅ | `of_intelligence_sync_logs` |
| **Chats / message text** | ❌ | not exposed by API — confirmed via 17+ probes |
| **Per-fan engagement** | ❌ | not exposed |
| **Story views / story buys** | ❌ | not exposed |
| **PPV unlock detail** | ⚠️ | aggregate only, not per-fan |

### 2.2 OnlyFans direct surface (we do not collect any of this yet)

The high-value signals OnlyMonster does not give us:

- **Chat threads** — full DM history per fan, in-bound and out-bound
  text, timestamps, who sent what, what was paid, what was tipped.
- **Mass-message bodies** — the actual copy that was sent, not just
  recipient counts.
- **Posts & stories** — actual captions, media types, paywalled
  flag, like/comment threads.
- **Vault** — folders, files, prices, descriptions, tags, what's been
  sent and to whom.
- **Fan profile signals** — display name, location hint, last-online,
  is-fan-active, is-fan-online-now, lifetime spend (we have a partial
  proxy via `of_intelligence_revenue`).
- **Subscriptions** — current subscriber list, renewal status,
  trial-vs-paid, subscription source (campaign attribution).
- **PPV unlocks** — which fan unlocked which message at which price.
- **Tip events** — per-fan tip history with the message context.
- **Chatter behaviour** — which logged-in session sent which message
  (combined with OnlyMonster's chatter directory this lets us audit
  per-chatter performance against actual message text).
- **Notifications / activity feed** — fan re-engages, fan unsubs, fan
  comes back online, fan adds card.

### 2.3 Social-platform signals (not yet collected)

For each creator, the public read-only feeds on the platforms the
creator runs:

- **Instagram** — handle, follower count over time, post cadence,
  recent post types, link-in-bio destination, story sticker types.
- **X / Twitter** — handle, follower delta, post cadence, NSFW flag.
- **TikTok** — handle, follower delta, view-to-follow ratio.
- **Reddit** — handle, subreddit footprint, karma, posting cadence.
- **Threads / BlueSky / etc.** — handle existence + cadence only.

We do not need every post.  We need *signal that the funnel is alive*:
is the creator actually feeding the top of the funnel, and is it
converting downstream into OF subs?

### 2.4 Operator / human-in-the-loop signals

These are the signals that machines cannot capture and that today live
nowhere — they live in Zach's head.  This is the highest-leverage
collection target because the data does not exist anywhere else.

- **Creator persona** — archetype, brand promise, fantasy delivered.
- **Voice & tone** — the rules of speaking *as* this creator.
- **Off-limits** — hard nos, kinks, words, regions.
- **Vault notes** — what's in the vault, naming conventions, how to
  pick.
- **Strategy summary** — current 30–60 day plan.
- **Client (creator) notes** — preferences, history, any prior
  agency, billing terms.
- **Account history** — when we onboarded, what's been tried, what
  failed, what worked.
- **Chatter notes** — who's senior, who needs supervision, who covers
  which creator.

The Creator Account Intelligence Profile work (`feat/ofi-daily-qc-scheduler`,
commit `02dbf38`) is the v1 capture surface for this category.

---

## 3. Data sources

In priority order — by value, not by ease.

| # | Source | Status | What it unlocks |
|---|---|---|---|
| 1 | **OnlyMonster API** | live | Account list, fans, chatters, transactions, mass-message stats, per-chatter metrics window |
| 2 | **OnlyFans direct, read-only** | not built | Chat text, vault content, mass-message bodies, per-fan engagement, sub funnel |
| 3 | **Browser-session capture** | infra exists (OpenClaw `:18789`, `:19999` status server) | Same data as #2; how we *implement* #2 in practice |
| 4 | **Manual imports** | not built | Spreadsheets of historic operator notes, creator briefs, archived strategy docs |
| 5 | **Social-account audits** | not built | Funnel signal — IG/X/TikTok/Reddit cadence + follower delta |
| 6 | **Operator notes (Creator Profiles)** | partly live (Profile detail page) | Persona, voice, vault, strategy, off-limits, client notes |
| 7 | **Future webhook sources** | not built | Real-time push from OnlyMonster (if added), Discord, Stripe, etc. |

#3 deserves a note: the OpenClaw stack already running on this Mac
(`com.digidle.openclaw` on `127.0.0.1:18789`, status server on `:19999`)
is the closest thing we have to a production browser-automation
runtime.  When we get to the direct-OF connector (§7), OpenClaw is the
plausible delivery mechanism — not a fresh Puppeteer spike.

---

## 4. Storage strategy

Five concentric layers, each one strictly downstream of the layer
inside it.  Today we have layer 1 and the start of layer 4.  We have
*nothing* in layer 2, 3, or 5.

```
┌──────────────────────────────────────────────────────────────────┐
│ L5  Action queue & alerts (what Zach should do today)           │
│   ─ of_intelligence_alerts, daily report emit                    │
├──────────────────────────────────────────────────────────────────┤
│ L4  Memory summaries (the brain proper)                          │
│   ─ creator memory, fan memory, chatter memory, content memory  │
│   ─ business_memory_entries already exists; mostly empty        │
├──────────────────────────────────────────────────────────────────┤
│ L3  Clean normalised tables (per-domain, source-agnostic)        │
│   ─ messages, chats, vault, subscriptions, ppv_unlocks, etc.    │
│   ─ today: only the OnlyMonster-shaped subset                   │
├──────────────────────────────────────────────────────────────────┤
│ L2  Raw capture tables (one row per upstream payload, JSONB)     │
│   ─ of_intelligence_raw_*  per source                           │
│   ─ today: the `raw` JSON column on entity tables = partial L2  │
├──────────────────────────────────────────────────────────────────┤
│ L1  Sync runs / audit trail                                      │
│   ─ of_intelligence_sync_logs (live)                            │
└──────────────────────────────────────────────────────────────────┘
```

### L1 — Sync audit (live)
`of_intelligence_sync_logs`.  One row per (run_id, entity).  Untouched.

### L2 — Raw capture
What we should add: dedicated raw tables per source so we can re-derive
L3 without re-fetching the upstream.

```
of_intelligence_raw_onlymonster (source, endpoint, fetched_at, payload jsonb)
of_intelligence_raw_onlyfans   (source, kind, fetched_at, payload jsonb)
of_intelligence_raw_social     (platform, handle, fetched_at, payload jsonb)
```

Right now the `raw` JSON column on entity tables half-does this, but it
only covers the *last* sync.  A real raw-capture table is append-only,
so we keep the full history.

### L3 — Clean normalised
What we have now (`accounts`, `fans`, `chatters`, `messages`,
`mass_messages`, `posts`, `revenue`, `tracking_links`, `user_metrics`,
`creator_profiles`) is L3 for the OnlyMonster-shaped slice.  Adding
direct-OF data means *expanding* these tables (e.g. `messages.body`
becomes populated, `chats` becomes a real entity, `vault_*` arrives) —
not creating parallel tables.  Carry `source` everywhere so OnlyMonster
and direct-OF rows coexist without conflict.

### L4 — Memory summaries (the brain)
This is where OFI becomes a brain instead of a warehouse.

| Memory kind | One row per | Holds |
|---|---|---|
| Creator memory | creator | persona, voice, off-limits, current strategy, what's worked, what's failed, vault map (text), revenue pattern summary |
| Fan memory | (creator, fan) | spend pattern, kinks, what they've bought, do/don't say, last-touch summary |
| Chatter memory | chatter | strengths, weaknesses, recurring failure modes, supervision level |
| Content memory | (creator, theme) | what kinds of mass-DM / post / vault item perform; what flops |
| QC findings | (creator OR chatter, finding) | rolling window of evaluated rules + outcomes |

`business_memory_entries` already exists and is the right primitive —
generic atom: `(product, kind, title, body, tags, period, ...)`.  It is
under-used.  L4 is a series of *writers* that summarise L3 into atoms,
plus a *retriever* that pulls relevant atoms when an agent needs
context.

### L5 — Action queue & alerts
`of_intelligence_alerts` (live).  Daily report (live).  Discord
delivery (deferred).

The product surface (§5) reads from L4 and L5, not L3.  This is the
single biggest UI shift in this roadmap.

---

## 5. What the UI should show

Top-of-screen, in this order:

1. **Critical alerts** (red).  Sync is broken.  An account lost access.
   A chatter went 30+ minute reply on a critical fan window.  A refund
   spike.
2. **Today's action list.**  Concrete, dated, attributable.  "Reagan
   needs supervision shift today; AdamJaxon vault needs 3 new items;
   chargeback investigation due on `<creator>` at 4pm."
3. **Creator game plans.**  One panel per creator: status colour,
   30-day trend, current strategy summary, top 3 actions for the
   coming week.  Click → Creator profile detail page.
4. **Chatter QC summary.**  Tally of who's green / yellow / red this
   window with one-click drill-in to the per-finding why-and-action.
5. **Account health.**  Per-account access / sub funnel / posting
   cadence / churn — all coloured.  No raw rows.
6. **Revenue opportunities.**  Under-monetised fans (whales who
   haven't bought in 14d), trial conversions decaying, mass-DM lift
   trending down.
7. **Content & persona** (per-creator drawer).  Strategy summary,
   voice/tone, vault structure highlights, off-limits.
8. **What Zach needs to do.**  A *single* unified queue across all
   creators.  Each item is a card with creator + action + due-by.

Everything else is secondary navigation.

---

## 6. What should be hidden or secondary

Move out of the primary nav, keep behind an "Investigate" drawer:

- Raw fans table
- Raw messages table (when we have it)
- Raw transactions / revenue table
- Raw mass-message table
- Raw posting-insights table
- Raw tracking-links table
- Raw sync logs

Reasoning: these are debug surfaces.  They're how we *find out why* the
brain says what it says — they are not the answer.  Keeping them
top-level is the signature of a dashboard, not a brain.

The current OFI sub-nav in `SectionShell.tsx` (12 tabs) should
collapse to ~5: **Today**, **Creators**, **Chatters**, **Alerts**,
**Investigate** (with the raw tables nested under Investigate).

---

## 7. Direct OnlyFans connector strategy

**Scope:** read-only prototype, **one** account that we own or that
the creator has explicitly authorised.  Single Mac.  No multi-tenant.
No automation against any other account until we've proven the model
is safe and stable.

**Hard prohibitions** (these are not "for now" — these are "until
explicit operator approval per build"):

- ❌ No messages sent
- ❌ No posts created
- ❌ No mass-DMs sent
- ❌ No tips, no purchases, no subscriptions changed
- ❌ No vault edits
- ❌ No profile edits
- ❌ No replies, even drafts auto-saved server-side
- ❌ No actions that modify state on OnlyFans or OnlyMonster

**Mechanism, in order of preference:**

1. **OpenClaw browser session.**  We already run an OpenClaw gateway
   (`127.0.0.1:18789` + status server `:19999`).  The creator logs in
   in a controlled browser profile.  OpenClaw drives a read-only
   navigation loop and captures the *responses* the OnlyFans frontend
   itself receives over XHR.  We persist those payloads to L2.  No
   reverse-engineered headers — we ride on a real session.
2. **Session-token replay (fallback).**  If OpenClaw's full-browser
   approach is too slow, capture the session cookie + dynamic header
   set once, replay XHR calls server-side.  Higher risk of breakage on
   any OnlyFans frontend update; lower CPU.
3. **Reverse-engineered API (rejected).**  Independent of OpenClaw,
   directly forging header signatures.  Brittle, ToS-grey, breaks on
   every OF deploy.  Not worth it.

**Read inventory the prototype must demonstrate:**

- List my chats (chat_id, fan_id, last_message_at, unread, locked).
- For one chat: list messages (id, body, sender, sent_at, paywalled,
  paid_at, price_cents, media_count).
- List my mass DMs (id, body, sent_at, recipient_count, purchased_count,
  revenue_cents).
- List my vault folders + files (id, folder_id, type, price_cents,
  description, created_at).
- List my subscribers (id, username, subscribed_at, expires_at,
  source).

Once those five reads work, we know the connector is real.

**Persistence shape:**

Each read goes to its source-tagged raw table first:
`of_intelligence_raw_onlyfans (source='onlyfans_direct', kind, fetched_at, payload)`.
A normaliser then writes into the existing L3 tables (`messages`,
`chats`, `mass_messages`, `posts`, plus new `vault_*` and
`subscriptions` tables) tagged with `source='onlyfans_direct'` so the
same UI works across both OnlyMonster and direct-OF rows.

**Safety rails:**

- Read-only HTTP verbs only — the connector library rejects POST/PUT/
  PATCH/DELETE at the framework layer, not just at the call site.
- Rate-limit at 1 request/sec, never burst.
- A kill switch in the DB (`app_settings.onlyfans_direct_enabled`)
  defaults to `false`.  Even with credentials configured, the
  connector refuses to fetch unless the flag is on.
- Every fetch is logged to `of_intelligence_sync_logs` with the source
  tagged `onlyfans_direct` so we can audit volume.

---

## 8. Agent future

Each creator eventually gets a *team* of small, scoped agents.  Each
agent is a function that reads from L4 (memory) + L3 (clean tables),
produces a recommendation, and (after operator approval) emits an
action into a queue.  No agent writes directly to OnlyFans/OnlyMonster
in v1.  Approval gating is non-negotiable.

| Agent | Reads | Produces |
|---|---|---|
| **QC agent** | `user_metrics`, message text (when we have it), `chargedback_*` counts | per-chatter findings + supervision recommendations |
| **Chatter manager** | chatter memory, QC findings, schedule | which chatter on which creator at which hour |
| **Posting agent** | content memory, post performance history | proposed post calendar with caption drafts (operator approves before send) |
| **Mass-message agent** | mass-message memory, fan segments, vault | proposed campaign with body + segment + price (operator approves before send) |
| **Vault agent** | vault contents, sales history, gaps | "add 3 new items in this category", "this item is over-used", "this item is dead" |
| **Creator strategy agent** | all the above | rolling 30-day plan summary for the creator profile |
| **Fan memory agent** | per-fan revenue, message text, behaviour | per-fan brief: spend pattern, do/don't, last-touch, suggested next move |

Sequencing: QC agent first (Chat QC v1 already lands part of this).
Fan memory agent and chatter manager second.  Posting / mass-message /
vault agents are dependent on the direct-OF connector so the agent has
real content + sales data to reason from.

---

## 9. Six-month roadmap

Each month is a single focus.  Anything not on the focus list does not
land.

### Month 1 — Data warehouse and read-only collection
- **Direct-OF read-only prototype** (§7) on one account.  Scope: list
  chats, list messages for one chat, list vault, list subs, list
  mass-DMs.  No UI yet.
- L2 raw tables added (`of_intelligence_raw_onlyfans`, `…_raw_social`).
- Migration discipline: one migration per PR.
- **Discord alerts not yet wired.**  This month is collection only.

### Month 2 — Chat / message capture and QC depth
- Promote the direct-OF prototype from one account to all accounts the
  creator has authorised.
- L3 expansion: real `messages.body`, real `chats`, new `vault_*`
  tables.
- **QC v2:** add per-message rules (tone, missed upsell, ignored fan,
  unprofessional language) on top of the existing user_metrics rules.
- Daily QC report becomes per-message-aware.

### Month 3 — Creator memory and fan memory
- L4 writers: rolling summarisers that turn L3 into
  `business_memory_entries` rows tagged by `(creator, kind)` and
  `(creator, fan, kind)`.
- Creator profile page (already shipped) starts showing memory
  highlights instead of just raw fields.
- Fan memory drawer per fan in the (still-secondary) fans view.

### Month 4 — Discord alerts and daily operator reports
- Discord delivery wired *only after* the alert engine has been stable
  for 30 days locally.
- Daily report posts a summary card per creator + a global action
  queue.
- Alert dedup discipline reviewed (already good for `chatter_qc:*`).

### Month 5 — AI drafting and strategy recommendations
- Posting agent + mass-message agent ship in *draft mode* — they
  produce proposed copy and a recipient segment, but only operator can
  hit Send.
- Creator strategy agent emits a weekly strategy summary card per
  creator.
- All drafts logged so we can grade the agent later.

### Month 6 — CRM replacement interface prototype
- The OFI front page becomes the agency's primary operating screen.
- Internal CRM workflow (assign chatter, mark account at-risk, attach
  notes, escalate) starts living in OFI rather than the OnlyMonster UI.
- This is when raw-table tabs come *out* of the primary nav for good.

Anything not on this list — Telegram delivery, mobile app, AI
auto-send, multi-tenant, "training" custom models per creator — is
explicitly out of scope until M6+.

---

## 10. Immediate next build

**Recommendation: A — Direct OnlyFans read-only connector prototype on
one account.**

The honest reasoning, no hype:

- **The data brain is bottlenecked on chat content.**  Every
  high-leverage agent (fan memory, posting, mass-DM, vault) needs the
  raw conversation text.  OnlyMonster does not give it to us — that
  was confirmed via 17+ probe URLs in the chat-qc-agent-plan
  investigation.  Without this connector we can build memory tables,
  UI cleanups, and dashboards forever and the agents at the end never
  have anything real to reason from.
- **OpenClaw infra already exists** on this Mac.  The
  `com.digidle.openclaw` service runs on `127.0.0.1:18789` with a
  status server on `:19999` (per the project memory note).  We are
  not greenfielding the browser stack — we're pointing it at
  OnlyFans and capturing read-only XHR.
- **The risk is real and contained.**  Read-only single-account
  prototype, kill switch in DB, hard prohibition on mutating verbs at
  the framework layer.  ToS exposure is non-zero — the creator owns
  the account and explicitly authorises us, which is the standard
  agency relationship anyway.
- **Why not B (chat/message import bridge):** B is meaningless without
  A.  There is no source to import from yet — that's exactly what A
  produces.
- **Why not C (creator memory system):** C is *valuable* but it has no
  fuel.  Memory summarisers with no message text to summarise produce
  identity blurbs and aggregate metrics — the same thing we already
  surface in Creator Profiles.  Build C in M3 once A has a month of
  real data to compress.
- **Why not D (UI cleanup):** D is the *easiest* and most visible
  win, and it should happen — but doing D first means we re-skin a
  shallow product.  Better to do D in M2/M3 once the underlying
  signals justify the screens.
- **Why not E (something else):** the only honest "E" is "ship Chat QC
  v1 polish + Discord delivery now."  Chat QC v1 already works.  It
  surfaces what it can.  Polishing it does not move us closer to the
  brain — it moves us further into "nicer dashboard" territory, which
  is the exact mode we are trying to leave.

**Concrete shape of the next build (A):**

- New worktree off `feat/ofi-daily-qc-scheduler`:
  `feat/ofi-direct-of-prototype`.
- New service: `app/services/of_intelligence/onlyfans_direct/` — a
  single Python module with a read-only `OnlyFansDirectClient` that
  refuses non-GET verbs at construction.
- New table: `of_intelligence_raw_onlyfans` (L2).  Append-only.  No
  L3 expansion in this build.
- New launchctl service or one-shot script that calls the connector
  for **one** test account, captures the five reads in §7, and writes
  to L2.
- New status page at `/of-intelligence/investigate/raw-feeds` (behind
  Investigate drawer) showing what we've captured.
- `app_settings.onlyfans_direct_enabled` defaults `false`.
- No frontend changes to the primary nav.  No alert wiring.  No agent
  wiring.  No memory writer.  This build is collection only.

Success criterion: end-to-end demo on one account where the five reads
land in `of_intelligence_raw_onlyfans` over a 24-hour soak with no
errors, no rate-limit trips, no state mutation observable in the OF
account.

That demo is the gate to Month 2.

---

## Appendix — what we will *not* do

- ❌ No multi-tenant rollout of the direct-OF connector before M2.
- ❌ No reverse-engineered OF API (forged signatures).
- ❌ No write actions of any kind without explicit per-build operator
  approval.
- ❌ No "agent" that auto-sends anything in M1–M4.
- ❌ No additional dashboard tabs that visualise raw rows.
- ❌ No deletion of the existing tables — they continue to back the
  Investigate drawer.
- ❌ No deploy of any of this to production until M4 at the earliest,
  and not without an explicit go.
