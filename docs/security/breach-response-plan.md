# Breach Response Plan — Mission Control / OnlyFans Intelligence

**Version:** 1.0 (draft)
**Last updated:** 2026-04-28
**Owner of this plan:** Zachary
**Audience:** Anyone with operator or developer access to Mission Control. This plan is short on purpose. Print it. Re-read it once a quarter.

---

## 0. Principles

1. **Contain first, investigate second, communicate third, learn fourth.** In that order.
2. **Default to revocation.** It is cheaper to rotate every credential than to wonder which one was leaked.
3. **Assume more is compromised than you know.** Pivot the blast radius outward, not inward.
4. **Write everything down in real time.** Times in UTC, actor names, command outputs, screenshots.
5. **Owner makes the call** on external notifications. Operators do not contact creators or clients on their own.
6. **Drill it.** A plan that has never been exercised is a wish.

---

## 1. Severity ladder

| Sev | Trigger | Response posture |
|---|---|---|
| **Sev 1 — Critical** | Confirmed data breach, confirmed creator account hijack, confirmed leak of credentials, public exposure of any creator data | Full incident: kill switch on, all hands, owner notifies creators within 24 hours, regulators if required |
| **Sev 2 — High** | Strong evidence (e.g. anomaly + missing audit + log gap) but not yet confirmed; staff laptop theft of an account that **had** prod access; suspected developer misuse | Treat as Sev 1 until disproven |
| **Sev 3 — Medium** | Single user role abuse with no creator data exposure; minor misconfiguration found before exploitation; secret committed to git but caught & rotated within an hour | Internal incident; no creator notification unless investigation widens |
| **Sev 4 — Low** | Near-miss, audit anomaly with benign explanation, dependency CVE without exploitation | Track as security ticket, no incident |

When in doubt: classify **one level higher**. Downgrading after investigation is fine; upgrading late is the failure mode that hurts.

---

## 2. The first hour (every incident, every severity)

Do these in order. Don't skip ahead.

1. **Open an incident log.** A new file in a private location: `~/.mission-control-incidents/<UTC-timestamp>-<short-name>.md`. Append-only mental model: never delete, only add.
2. **Write down what you know.** What you saw, when, where (URL, log line, alert name), and your current confidence.
3. **Tentatively classify** (Sev 1–4) per §1.
4. **Hit the kill switch** if Sev ≤ 2:
   - Set `mc.connectors.frozen = true`.
   - Set `mc.ai.frozen = true`.
   - Disable any specific connectors known or suspected to be involved.
5. **Page the owner.** If you are the owner, page the second owner / agency principal. Phone, not email.
6. **Stop touching prod.** No "let me just check one more thing." Subsequent investigation goes through the read-only forensic path in §3.
7. **Take a snapshot** of the production database before any rotation/cleanup. Encrypted backup, separate location.

After step 7 you can breathe. Now follow the playbook for the specific scenario in §4.

---

## 3. Forensic posture (read-only)

Until contained, any active investigation must be **read-only** so that evidence is preserved.

- Use a read-only DB replica or snapshot, never the live DB.
- Do not run migrations, do not re-deploy, do not delete logs.
- Pull `audit_events`, application logs, gateway logs, and reverse-proxy logs into a single working folder.
- For credential exposure: query `audit_events` for `target_type='credential'` and `target_type='connector'` for the suspected window; preserve the rows.
- Capture which secrets were live in which environment at the time. The current values are not the question; the values **at incident time** are.

---

## 4. Scenario playbooks

### 4.1 Token / API key leak (LLM key, OnlyMonster key, Clerk key, GitHub PAT, OnlyFans creator credential)

**Indicators:** secret committed to git, posted in Slack/Discord, in a screenshot, in a public log; provider notifies us; anomalous billing.

1. **Revoke at the source first.** Provider dashboard. Rotate the value. Do not skip — even if you are about to rotate ours too.
2. **Rotate in Mission Control.** Update `app_settings` (or `creator_credentials`) with the new value. Verify decryption succeeds.
3. **Audit usage.** Pull provider-side logs for the leaked key for the full window from "first-could-have-leaked" to "now." Record any unfamiliar IPs / models / endpoints.
4. **For OnlyFans creator credentials:** also rotate the creator's password and re-pair any 2FA. Inform the creator the same hour.
5. **For LLM keys:** scan provider account for any data exfil (downloaded fine-tunes, batches we didn't run, retained prompt logs).
6. **Search the leak surface.** Was it in git? `git log -G '<secret-fragment>' --all` to find every commit. Force-push removal is not enough — assume the value is permanently compromised even after history rewrite.
7. **Update the gap audit:** add the source of the leak (commit hook missed, screenshot in Discord, etc.) and a control to prevent recurrence.
8. **Sev classification:** Sev 1 if the key gave access to creator data; Sev 2 if it gave access to LLM/billing only; Sev 3 if rotation completed within an hour and no usage in the window.

### 4.2 Creator account compromise (OnlyFans account hijacked)

**Indicators:** OF login from new geo, password reset email the creator did not initiate, missing posts/messages, support ticket from creator, anomaly alert from connector.

1. **Disable the connector instance** for that creator (per-instance enable=false). Audit row written.
2. **Revoke and delete** the stored creator credential (`creator_credentials` row) for OF.
3. **Call the creator** (don't email — phishing risk). Walk them through:
   - Reset OF password via the OF web UI (not via any link we send).
   - Enable / re-pair 2FA.
   - Review active sessions on OF and revoke any unfamiliar.
   - Review payout / payment account on OF for changes.
4. **Pull our audit log** for that creator's connector for the previous 30 days. Look for: unusual sync times, unfamiliar IPs (compare against our deploy regions), surprise mode flips.
5. **Determine root cause posture:**
   - If our connector was the leak path → Sev 1, follow §4.5 (database breach) too.
   - If creator was phished outside our system → Sev 2 (creator at risk, but our system is intact); still rotate everything we held.
6. **Document timeline** with the creator: when did they first notice, when did we first see the alert, when did we revoke.
7. **Notify** the agency principal regardless of source.

### 4.3 Staff laptop theft

**Indicators:** stolen / lost device with active sessions, browser-cached credentials, or a synced `.env`.

1. **Assume worst case:** any session, any cached credential, any sync'd file is compromised.
2. **Revoke device sessions** at every identity provider: Clerk (sign out all sessions for that user), GitHub (revoke device), 1Password (sign out & rotate vault key if prod values were in it), Cloudflare, AWS/GCP, OnlyMonster, any LLM provider.
3. **Rotate prod secrets** the user could have had access to. At minimum: `SETTINGS_ENCRYPTION_KEY` (re-encrypt all rows, bump `key_version`), `LOCAL_AUTH_TOKEN`, `CLERK_SECRET_KEY`, all integration keys, all `creator_credentials` for any creator the user had grants on.
4. **Revoke the user's grants** in Mission Control: `creator_grants` removed, `mc_user_roles` set to disabled until investigation completes.
5. **Remote-wipe** the device if managed (Find My Mac, MDM). Disk encryption at rest is assumed but not relied on.
6. **Audit-search** for the user's `actor_user_id` in `audit_events` for the 24 hours before the loss. Anything anomalous?
7. **Sev classification:** Sev 2 by default. Sev 1 if disk was unencrypted or there's evidence of post-theft access (impossible-travel logins, etc.).
8. **File a police report** if law enforcement engagement might recover the device or be useful for cyber-insurance.

### 4.4 Database breach (cloud DB credentials leaked, replica reachable from the internet, dump found in the wild)

**Indicators:** a dump appears externally; cloud provider alert; DB shows connections from unfamiliar IPs; missing/altered audit rows.

1. **Containment first:** rotate DB credentials at the cloud provider; rotate `DATABASE_URL`; lock the DB to known IPs / VPC only.
2. **Preserve evidence:** snapshot the DB and the audit log into encrypted offline storage **before** any cleanup.
3. **Assume `app_settings` ciphertexts and `creator_credentials` ciphertexts are exposed.** Even though they are encrypted, treat the encryption key as also compromised (in cloud-DB scenarios the env is often co-resident).
4. **Rotate `SETTINGS_ENCRYPTION_KEY`.** Re-encrypt everything; bump `key_version`. Old ciphertexts are useless to the attacker only if the key never leaked — assume it did.
5. **Rotate every value protected by the old key.** Provider keys, integration keys, creator credentials. This is the worst day; budget hours, not minutes.
6. **For OnlyFans creator credentials specifically:** the creator must reset OF password and 2FA per §4.2.5. We cannot do this for them — call them.
7. **Notify creators and the agency principal** within 24 hours of confirmation, sooner if regulator-required.
8. **Forensic review:** what did the attacker access vs. exfiltrate? Pull cloud egress logs for the breach window.
9. **Public posture:** owner decides on disclosure. Do not unilaterally post.
10. **Classify Sev 1.** Always.

### 4.5 Developer misuse (insider exfil, misuse of grants, prod access from unauthorized device)

**Indicators:** audit log shows `actor_user_id` accessing creators they should not, unusual export bursts, grants granted outside change control, creator data appearing in personal projects / blogs / repos.

1. **Quietly preserve evidence.** Do not tip the user off — disabling them mid-investigation may destroy evidence. Decision to disable is the owner's, not the investigator's.
2. **Pull the user's full `audit_events` history.** Their last 90 days; widen if needed.
3. **Identify exposed creators** from the audit trail.
4. **When ready to act:** disable the user (`mc_user_roles.disabled=true`), revoke all sessions (Clerk sign-out all), revoke device tokens, remove `creator_grants`, rotate any secret they had write access to.
5. **Rotate `SETTINGS_ENCRYPTION_KEY`** if the user could have read it (treat developer-tier as yes by default).
6. **Notify each affected creator individually.** This is the hardest call — the owner makes it. Include what was accessed, when, and what we are doing.
7. **Legal:** consult counsel before any public statement, employment action, or law-enforcement involvement.
8. **Engineering follow-up:** every grant the user had that they should not have had is a control failure. Document and fix.
9. **Sev 1.** Always.

---

## 5. Communication discipline

- **Operators do not contact creators about a breach.** Owner only.
- **No public statement** before investigation reaches a stable narrative. "We're investigating" is not a public statement.
- **Internal updates** every 30 minutes during Sev 1, hourly during Sev 2, end-of-day for Sev 3.
- **Post-incident review** within 7 days of resolution. Written. Stored in `docs/security/incidents/`.
- **Templates:**
  - Creator notification: state what data, what window, what we did, what they should do, contact for questions.
  - Internal heads-up: severity, status, kill-switch state, expected next update time.

---

## 6. Recovery & verification

Before lifting the kill switch:

1. Root cause identified and documented.
2. Compensating controls in place (new audit rule, new alert, blocked endpoint, removed grant, rotated key — whatever applies).
3. All affected secrets rotated; old secrets confirmed dead at the provider.
4. Audit log shows the kill-switch toggle, the rotation actions, and the all-clear, in order, with timestamps.
5. Drill the affected scenario in staging to confirm controls bite.
6. Owner approves lift; audit row records the approval.
7. Re-enable connectors one at a time, watching for anomaly.

---

## 7. Drill schedule

| Drill | Frequency | Owner |
|---|---|---|
| Token leak (rotate everything in 60 min) | Quarterly | Zachary |
| Staff laptop theft (revoke sessions in 15 min) | Quarterly | Zachary |
| Database breach restore-from-backup | Annually | Zachary |
| Creator account compromise call-script | Before first live OF connector creator, then quarterly | Owner of agency relationship |
| Developer misuse tabletop | Annually | Zachary |
| Full Sev-1 walk-through (no production change) | Bi-annually | Owner + agency principal |

A drill that does not produce a written timeline did not happen.

---

## 8. Contact card (fill in before the first creator)

Keep one printed copy. Update on staff change.

| Role | Name | Phone | Backup contact |
|---|---|---|---|
| Mission Control owner | Zachary | _fill_ | _fill_ |
| Agency principal |  |  |  |
| Legal counsel |  |  |  |
| Cloud provider security |  |  |  |
| Identity provider (Clerk) support |  |  |  |
| Cyber insurance broker |  |  |  |
| OnlyFans creator support liaison (if any) |  |  |  |

---

## 9. What this plan deliberately does NOT do

- It does not replace a written legal incident-response policy from counsel. When real incidents touch personal data of EU/UK individuals, get counsel involved.
- It does not list every CVE or runtime mitigation. That belongs in the gap audit and in dependency hygiene.
- It does not authorize any developer to take destructive action without owner sign-off, except `mc.connectors.frozen=true` (always allowed).
- It does not promise a recovery time. Each scenario has a worst case in hours-to-days. Set creator expectations honestly.
