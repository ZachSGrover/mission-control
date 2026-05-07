# Incident Drill — Token Leak

**Version:** 1.0
**Last updated:** 2026-04-28
**Owner:** Zachary
**Audience:** Anyone who could be on call when a Mission Control or creator credential leaks. This drill is a real exercise. Run it, time it, write the result down. A drill that does not produce a written timeline did not happen.

---

## Why this drill exists

Token leaks are the single most likely security event for a small operator. A `.env` line pasted into a screenshot, a key committed to a public branch, a developer laptop backup uploaded to a personal cloud — these all happen. The cost of preparation is low; the cost of fumbling the response is enormous because attacker dwell time scales with our hesitation.

The goal of this drill is to **rotate every relevant credential within 60 minutes** of suspicion, with audit evidence and creator-impact assessment. If a real incident takes longer than the drill, we have a problem in the runbook, not in the operator.

---

## Pre-drill setup (one time)

Before you can run this drill, the following must already be in place. If anything below is ❌ when you sit down to drill, stop and fix it before drilling — drilling on a broken foundation teaches the wrong lesson.

| # | Requirement | Source of truth | Status |
|---|---|---|---|
| 0.1 | `audit_events` exists, queryable from a read-only psql session | `docs/security/audit-events-implementation.md` |  |
| 0.2 | Kill switches exist for `connectors`, `ai`, and any specific high-risk connector | `kill_switches` table, `docs/security/security-sprint-2-implementation.md` |  |
| 0.3 | `SETTINGS_ENCRYPTION_KEY` is a dedicated env var, not falling back to `LOCAL_AUTH_TOKEN` | `is_dedicated_encryption_key_configured()` in `app/core/secrets_store.py` |  |
| 0.4 | `breach-response-plan.md` printed and reachable without the laptop you might be revoking | physical copy |  |
| 0.5 | Owner phone numbers reachable without app sign-in | contact card §8 of breach response plan |  |
| 0.6 | Provider dashboards (OpenAI, Anthropic, Google AI, GitHub, Clerk, OnlyMonster) accessible from a backup device or browser profile | confirm before drill |  |
| 0.7 | `creator_credentials` rotation path tested in staging at least once | rotation runbook |  |

---

## Drill scenario

> A teammate posts a message in the operator Slack: "Heads up — I just realized I screen-shared my terminal in a Loom yesterday and the OPENAI_API_KEY scrolled past for about two seconds. The Loom is set to 'anyone with the link' and was sent to one external person. I don't know if they saw the key."
>
> Treat this as suspicion → real. Start the clock.

This is a deliberately ambiguous scenario:
- The exposure window is partially known (date of recording + range of moments where key could have been on screen).
- The external recipient is identified but not assumed hostile.
- The key gives access to LLM billing and (depending on org) to fine-tunes / batch jobs / saved prompts. **Not** to creator data directly — but if our redaction layer ever leaks a fan message into a prompt log, the LLM provider account becomes the leak surface.

The drill ends when **all rotation steps are complete, all audit evidence captured, and the post-incident note is written**.

---

## The 60-minute clock

### T+0 — Triage and containment (target: under 5 minutes)

1. **Start the timer.** Note the wall clock to the minute. Open a private incident log:
   `~/.mission-control-incidents/<YYYY-MM-DDTHH-MM>-token-leak-drill.md`.
2. **Classify.** Per `breach-response-plan.md` §1, an LLM key leak with no creator data exposure is **Sev 2** (LLM/billing only). When in doubt, classify one level higher.
3. **Hit the connector kill switch.** Even though OpenAI is not a connector to a creator account, flipping `mc.connectors.frozen=true` is cheap insurance against compounding events while you are head-down on rotation.
   - In Mission Control admin: **Security → Kill Switches → mc.connectors.frozen → ON.**
   - Verify an audit row was written: `SELECT * FROM audit_events WHERE event_type='kill_switch.toggle' ORDER BY created_at DESC LIMIT 1;`
4. **Page the owner.** If you are the owner, page the second owner / agency principal. Voice call, not Slack.
5. **Write down what you know.** What was leaked, suspected exposure window, who the external recipient is, your current confidence level.

✅ **Pass criterion:** triage complete with audit evidence in under 5 minutes.

---

### T+5 — Provider-side revocation (target: T+5 → T+15)

The single most important step is **revoking at the provider before doing anything else in our system.** A revoked key in our DB but live at the provider is worse than no rotation: we feel safe and the attacker still has access.

For an OpenAI key (this drill):

1. Open https://platform.openai.com/api-keys.
2. Find the key by its prefix; revoke it. Screenshot the "Revoked" state for the incident log.
3. Generate a new key in the same project. Restrict it to the same model set if your project uses model-level scoping.
4. Capture the new key value into the password manager **first** (so it's never just on screen), then paste it into Mission Control admin → Settings → API Keys → OpenAI.
5. Confirm a `settings.api_key.save` audit row exists: this is written by `app/api/app_settings.py:upsert_api_key`.

For other LLM keys (Anthropic, Google), the steps are identical with provider-specific URLs.

For a GitHub PAT:
1. https://github.com/settings/tokens → revoke the leaked token by note/prefix.
2. Generate a fresh fine-grained PAT with the same scopes.
3. Save in Mission Control admin → Settings → GitHub → PAT.

For a Clerk key:
1. Clerk dashboard → API Keys → roll the leaked secret.
2. Update `CLERK_SECRET_KEY` env var. **A restart is required.** This is a regression in availability — do not skip the audit row, and make sure the new secret is in the secrets backend before restarting.

For an OnlyMonster credential:
1. OnlyMonster dashboard → revoke API token.
2. Generate fresh token; update via **Mission Control admin → Integrations → OnlyMonster**.
3. Confirm `integration.credential.save` audit row exists.

✅ **Pass criterion:** every leaked key is revoked at the provider with a screenshot or response logged, and a replacement is live in Mission Control with an audit row written, by T+15.

---

### T+15 — Usage forensics (target: T+15 → T+35)

Now you find out what the leaked key was used for.

1. **Pull provider usage logs** for the leaked key for the full window from "earliest possible exposure" to "now."
   - OpenAI: https://platform.openai.com/usage and the per-key activity tab if available.
   - GitHub: audit log API filtered by token actor.
   - Clerk: dashboard → audit log filtered by API session.
2. **Compare against expected use.** For each unfamiliar entry — unfamiliar IP, unfamiliar model, unusual hour, unusual volume — record the row in the incident log.
3. **Cross-check against our own audit log.** For LLM keys: pull `audit_events` for `event_type='llm.call'` (or whatever your prompt logger emits) for the same window. Are there our-side calls without provider-side rows? Are there provider-side calls without our-side rows? The latter is the alarm bell.
4. **For Mission Control admin tokens specifically** (gateway tokens, integration tokens): pull `audit_events` filtered by the token's resource_id for the suspected window. Note any state-changing actions — those need follow-up.
5. **For OnlyFans creator credentials specifically** (only relevant when we eventually wire the direct path): the rotation MUST include having the creator reset their OnlyFans password and re-pair 2FA. We cannot do this for them; the call to the creator is the bottleneck — start it in parallel with steps 1–4.

✅ **Pass criterion:** by T+35, the incident log contains either "no anomalous usage in the leaked-key window" with evidence, or a list of every anomalous row with timestamp/IP/action/follow-up.

---

### T+35 — Source eradication (target: T+35 → T+50)

Find the leak surface and close it so the next 24 hours don't produce a sequel.

1. **Was it in git?**
   - `git log --all -G '<secret-fragment>' -- . ':(exclude)*.lock'` for every repo the operator uses.
   - If found: rewriting history is **not enough**. Treat the value as permanently compromised (you already have, since you revoked at provider). Document the commit SHAs and the path of leak.
2. **Was it in chat / video / screenshot?**
   - Note who the recipients were. Decide whether to ask the recipient to delete the artifact (be explicit and polite — they may not realize what they have).
   - For Looms / video: revoke share or delete; for chat: delete the message; for screenshots: ask sender to remove from any cloud sync.
3. **Was it in a log file?**
   - Identify which log captured it (application log, reverse proxy, error tracker, terminal scrollback). Patch the redaction so the same path won't capture the next key.
   - Rotate any log that was forwarded off-system (e.g. uploaded to an error tracker like Sentry) — the log copy at the destination still contains the value.
4. **Update prevention.** The point of eradication is to prevent recurrence. Add at least one control before closing the drill:
   - Pre-commit hook that greps for known key prefixes (`sk-`, `sk-ant-`, `pb_`, `ghp_`, `clerk_secret_`).
   - CI check on the frontend bundle for `NEXT_PUBLIC_.*(SECRET|TOKEN|KEY)`.
   - Reminder for operators: do not screen-share terminals; if you must, use a fresh terminal with no env loaded.

✅ **Pass criterion:** the source is identified and closed; at least one new control is committed (or filed as a follow-up issue with an owner and date).

---

### T+50 — Verification and lift (target: T+50 → T+60)

Before lifting the kill switch and declaring done:

1. **Confirm dead key is dead.** Make a request with the old key (curl or python one-liner). Provider must reject it. Capture the 401 response.
2. **Confirm new key is live.** Make a request with the new key. Provider must accept it. Capture the 200 response.
3. **Confirm audit chain is intact.** Pull the audit log for the drill window and verify these rows in order: kill_switch on → settings.api_key.save → (any forensic queries you ran) → kill_switch off.
4. **Lift kill switches.** `mc.connectors.frozen → OFF`. Audit row written.
5. **Write the post-incident note.** Even though this was a drill, write it as if it were real. Include:
   - Wall clock for each milestone.
   - What worked.
   - What was slow or confusing.
   - One concrete improvement to the runbook or to the codebase.
6. **Update this document** with anything you learned. Drills get better only if you let them.

✅ **Pass criterion:** total elapsed time ≤ 60 minutes; post-incident note written; at least one runbook improvement filed.

---

## Audit checklist (paste into incident log)

```
Drill date: ____
Operator: ____
Scenario chosen: ____ (token type)
Wall clock start: ____

[ ] T+0   Triage classification and kill switch on        time: ____
[ ] T+5   Provider-side revocation done                   time: ____
[ ] T+15  New key live in Mission Control with audit row  time: ____
[ ] T+15  Forensics started (usage pull)                  time: ____
[ ] T+35  Forensics complete with evidence                time: ____
[ ] T+50  Source eradication and one new control          time: ____
[ ] T+60  Verification, kill switch off, post-incident    time: ____

Audit row evidence (paste row IDs):
  kill_switch.toggle ON  : ____
  settings.api_key.save  : ____
  kill_switch.toggle OFF : ____

Provider-side proof (revocation + new-key 200/401):
  ____

What I would change in the runbook:
  ____
```

---

## Failure modes this drill catches

Run this drill at least once before going live with any direct creator integration. The drill catches all of:

- **Owner cannot reach a provider dashboard from a backup device.** (Common: 2FA tied to one phone.)
- **Audit rows are not written for kill-switch toggles.** (Means the response itself is invisible to future auditors.)
- **`SETTINGS_ENCRYPTION_KEY` rotation is conflated with API-key rotation.** (Different operations; do not muddle.)
- **Operator does not know how to query `audit_events` from psql.** (If queries are gated behind app UI, the drill fails because the app may itself be the suspect.)
- **Slow path between revocation and rotation.** (Reveals missing playbook or password-manager gaps.)
- **Provider-side usage logs are not reachable for retroactive forensics.** (Some providers archive after N days; if your suspected window is older, you have a hard stop.)
- **No pre-commit hook exists, so the same leak can recur the next day.** (The new control is the most important deliverable; if you cannot ship one, the drill is incomplete.)

---

## Drill cadence

| Drill variant | Frequency | Owner |
|---|---|---|
| OpenAI key leak | Quarterly | Zachary |
| GitHub PAT leak | Quarterly | Zachary |
| Clerk secret leak (involves a restart) | Bi-annually | Zachary |
| OnlyMonster credential leak | Before first creator behind direct OnlyMonster, then quarterly | Owner of agency relationship |
| `SETTINGS_ENCRYPTION_KEY` leak (re-encrypts everything) | Annually | Zachary |
| Compound leak (laptop theft → multiple keys) | Annually, tabletop only | Zachary |

A drill that ends without a written timeline did not happen. A drill that ends without one new control did not finish. A drill that nobody else can read in six months did not produce knowledge.

---

## What this drill deliberately does NOT do

- It does not replace the broader `breach-response-plan.md`. That document covers the surrounding posture (severity ladder, communication discipline, recovery & verification). This drill is one specific scenario from §4.1 of that plan, exercised to depth.
- It does not authorize destructive cleanup. No git history rewrites, no log deletions during the drill — the goal is rotation and forensics, not evidence destruction.
- It does not certify response capability for a real Sev 1 (creator data exposure). That requires the creator-account-compromise drill in `breach-response-plan.md` §4.2.
