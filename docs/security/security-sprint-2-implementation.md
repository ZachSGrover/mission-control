# Security Sprint 2 — Prevention Foundation

**Status:** Sprint 2 of N. Builds on Sprint 1's audit foundation. Adds
the four prevention controls — approval, kill switch, consent, vault —
and a single composite gate that connectors must call before acting.
**Branch:** `feat/security-prevention-sprint-2`
**Last updated:** 2026-04-29

This document is the developer-facing companion to
[`onlyfans-intelligence-security-plan.md`](./onlyfans-intelligence-security-plan.md)
§5 (connector lifecycle) and §6 (consent). It describes what is in the
code right now, where the seams are, and how a future direct-connector
implementation must use it.

---

## 1. What was added

| Concern | Where |
|---|---|
| Connector approval row | [`backend/app/models/connector_approvals.py`](../../backend/app/models/connector_approvals.py) |
| Connector approval service | [`backend/app/services/connector_approvals.py`](../../backend/app/services/connector_approvals.py) |
| Kill-switch row | [`backend/app/models/kill_switches.py`](../../backend/app/models/kill_switches.py) |
| Kill-switch service | [`backend/app/services/kill_switch.py`](../../backend/app/services/kill_switch.py) |
| Client consent row | [`backend/app/models/client_consents.py`](../../backend/app/models/client_consents.py) |
| Client consent service | [`backend/app/services/consent.py`](../../backend/app/services/consent.py) |
| Creator credential vault row | [`backend/app/models/creator_credentials.py`](../../backend/app/models/creator_credentials.py) |
| Creator credential vault service | [`backend/app/services/creator_credentials.py`](../../backend/app/services/creator_credentials.py) |
| Composite "is this allowed?" gate | [`backend/app/core/connector_gate.py`](../../backend/app/core/connector_gate.py) |
| Vault guardrail (`is_dedicated_encryption_key_configured`) | [`backend/app/core/secrets_store.py`](../../backend/app/core/secrets_store.py) |
| Read-only security status endpoint | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py) (mounted at `GET /api/v1/security/status`, owner-only) |
| Combined Alembic migration | [`backend/migrations/versions/d4e5f6a7b8c9_add_major_security_foundation.py`](../../backend/migrations/versions/d4e5f6a7b8c9_add_major_security_foundation.py) (consolidated Sprint 1+2+3) |
| Tests | [`backend/tests/test_security_prevention.py`](../../backend/tests/test_security_prevention.py), [`backend/tests/test_security_admin.py`](../../backend/tests/test_security_admin.py) |

---

## 2. How connector approval works

State machine:

```
                 ┌────────┐
   request →──→ │pending│ ─→ approve →─→ ┌────────┐ ─→ revoke ─→ ┌──────┐
                 └────────┘               │approved│              │revoked│
                     ↓                    └────────┘              └──────┘
                  reject                       ↓
                     ↓                     expires_at < now
                 ┌────────┐                    ↓
                 │rejected│                ┌────────┐
                 └────────┘                │expired │
                                            └────────┘
```

A connector action is "approved right now" only when the row is
`status="approved"`, `revoked_at` is `NULL`, and `expires_at` is
either `NULL` or in the future. `is_approved()` enforces this. Every
state transition records an audit event under category `connector`.

The `(connector_type, requested_action, organization_id, creator_id)`
tuple is the lookup key. Wildcard scopes (e.g. an org-wide approval
that doesn't pin a creator) are expressed by passing `None` for the
unused dimension; the service uses `IS NULL` matching so a row is not
inadvertently broadened.

**Vocabularies (model file):**
- Connector types: `onlymonster, onlyfans_direct, discord, telegram, github, openai, anthropic, internal`
- Statuses: `pending, approved, rejected, revoked, expired`
- Risk levels: `low, medium, high, critical`

---

## 3. How kill switches work

Four scopes, queried in broadest-first order:

| Scope | `scope_id` |
|---|---|
| `global` | `None` |
| `connector` | connector_type string (e.g. `"onlyfans_direct"`) |
| `organization` | str(org.id) |
| `creator` | creator_id string |

`enable()` flips an existing row or creates it; `disable()` updates the
row in place (we never delete switches — disabled rows are the audit
trail). `is_active(scope, scope_id)` answers single-scope queries; the
composite check `check_action_allowed()` returns the **first** active
scope that blocks an action and short-circuits the lookup.

Every toggle records an audit event at severity `critical`. Toggles
include `reason`, who flipped it, and when.

---

## 4. How client consent works

A consent row is the durable record that a creator (or an org acting
on a creator's behalf) authorised a specific class of data action.

Lifecycle:
- `grant()` inserts a row with `status="granted"`, audit at `warning`.
- `revoke()` flips the row to `status="revoked"`, sets `revoked_at`,
  appends a `revoke_reason:` line to `notes`, audit at `high`.
- Rows are **never deleted**. A revoked consent is evidence that
  consent existed and was withdrawn.
- `is_granted()` returns the live row, or `None` if the consent type
  is unknown / no granted row exists / the live row was revoked / the
  expiry has passed. Fail-closed in every dimension.

**Consent types** (model):

| Type | Used by |
|---|---|
| `data_storage` | any storage of creator-related data |
| `ai_analysis` | LLM analysis touching creator/fan data |
| `onlymonster_sync` | OnlyMonster pulls |
| `onlyfans_direct_read` | direct OF reads |
| `onlyfans_direct_write` | direct OF writes (none in scope this sprint) |
| `chat_log_review` | reading DM threads |
| `fan_data_processing` | working with fan PII |
| `revenue_analysis` | analysing transactions |

The mapping `(connector_type, requested_action) → consent_type` is
maintained in `app.core.connector_gate.CONSENT_REQUIREMENTS`. Future
connectors only need to register their entry there to inherit the
fail-closed check.

---

## 5. How creator credential vault works

`CreatorCredential` rows hold Fernet ciphertext under the same key
machinery as `app_settings`, with two **hard** Sprint-2 guardrails:

1. **Dedicated encryption key required for writes.** The vault refuses
   to write a new credential if `SETTINGS_ENCRYPTION_KEY` is not set.
   This stops new creator credentials from being encrypted under a
   rotation-prone auth-token fallback. (Existing flows — provider API
   keys, GitHub PAT, integration credentials — still allow fallback for
   dev convenience; the line in the sand is creator-scoped credentials.)
2. **Plaintext is never stored, returned, or logged.** Audit metadata
   uses an 8-char SHA-256 hash prefix for traceability — irreversible
   but enough to correlate "the credential created earlier with prefix
   `a1b2c3d4` is the one being rotated now."

Lifecycle:
- `create_credential()` — insert encrypted row, audit at `high`.
- `rotate_credential()` — atomic "old → rotated, new active row," audit
  at `high`.
- `revoke_credential()` — old → revoked, audit at `critical`. Old row
  preserved as evidence.
- `get_credential_metadata()` — pure helper that returns API-safe row
  metadata (no `encrypted_value`, no derived plaintext).

API responses **MUST NOT** include `encrypted_value`. There is no
endpoint that reads it back to a caller; the only consumer of plaintext
is the future connector code, which will fetch + decrypt + use + drop
in a single function scope.

---

## 6. The composite gate (the seam connectors must use)

`app.core.connector_gate.is_connector_action_allowed()` is the single
chokepoint a future connector calls before acting. It returns a
typed `GateVerdict(allowed: bool, reason: VerdictReason, detail: str | None)`.

Order of checks (first failure wins):

1. **Unknown connector type** → `unknown_connector`.
2. **Kill switches** (global → connector → organization → creator) →
   `kill_switch_*`.
3. **Approval** in force for `(connector_type, requested_action, scope)`
   → `no_approval`.
4. **Consent** required for this `(connector_type, requested_action)`
   pair → `no_consent`.
5. **Credential vault** available for high-sensitivity connectors →
   `vault_unavailable`.

Anything else returns `allowed=True, reason="ok"`. The verdict's
`reason` always points at the *nearest* gating cause so the operator
knows what to fix.

The gate is framework-light by design: takes a session and plain
values, no `Depends`, no FastAPI. Reusable from API routes, RQ workers,
CLI scripts, and future connector code.

---

## 7. What was intentionally **not** built

In line with the brief's explicit prohibitions:

- **No direct OnlyFans connector.** Not even a stub function — the gate
  exists so the connector *can* be built later, not so it gets built
  now.
- **No write actions for any connector.** `onlyfans_direct_write`
  consent type exists for completeness, but no code path can use it.
- **No real account credentials stored or referenced.** The vault tests
  use deterministic placeholder strings; nothing in this sprint touches
  a real creator account.
- **No live integration runs.** Existing OnlyMonster / Discord /
  Telegram clients are unchanged; this sprint only adds the gate they
  *will* call when they're rewired.
- **No production secret modified.** `is_dedicated_encryption_key_configured`
  reads the env at runtime; it does not write the key.
- **No customer-facing consent portal.** Per the security plan, v1
  consent capture is out-of-band (signed PDF / DocuSign) and recorded
  via the `grant()` service. A self-serve portal is Sprint 3+ scope.
- **No frontend admin UI.** The `GET /api/v1/security/status` endpoint
  is owner-gated and read-only; building a richer dashboard is a
  follow-up if the JSON proves insufficient.
- **No automatic enforcement of the gate from existing routes.** The
  gate is implemented and tested; wiring it into a real connector entry
  point happens *after* the connector itself is approved for build.

---

## 8. How a future direct OnlyFans connector must use this

```python
async def run_of_direct_read(
    session: AsyncSession,
    *,
    auth: AuthContext,
    organization_id: UUID,
    creator_id: str,
) -> ReadResult:
    # 1. Single chokepoint check.
    verdict = await is_connector_action_allowed(
        session,
        connector_type="onlyfans_direct",
        requested_action="read",
        organization_id=organization_id,
        creator_id=creator_id,
    )
    if not verdict.allowed:
        # The audit row for "this connector run was blocked" lives
        # in the prevention services that detected the block; the
        # connector code only logs its own failure to act.
        await record_audit(
            session,
            event_type="connector.run.blocked",
            category="connector",
            action="run",
            result="blocked",
            severity="high",
            actor_user_id=auth.user.id if auth.user else None,
            organization_id=organization_id,
            creator_id=creator_id,
            resource_type="connector_run",
            metadata={"verdict_reason": verdict.reason, "detail": verdict.detail},
        )
        await session.commit()
        raise HTTPException(409, f"connector blocked: {verdict.reason}")

    # 2. Fetch the credential. Plaintext lives only in this scope.
    cred_row = await select_active_creator_credential(
        session, creator_id=creator_id, provider="onlyfans_direct"
    )
    if cred_row is None:
        raise HTTPException(409, "no active credential")
    plaintext = decrypt_value(cred_row.encrypted_value)

    # 3. Do the actual read. Mode = read only — never write — until
    #    a separate, second-owner approval flips us to read_write.
    try:
        result = await of_client.read_only_pull(plaintext, ...)
    finally:
        del plaintext  # be explicit about scope hygiene

    # 4. Update last_used_at, audit the success.
    cred_row.last_used_at = utcnow()
    session.add(cred_row)
    await record_audit(
        session,
        event_type="connector.run.finish",
        category="connector",
        action="finish",
        result="success",
        severity="info",
        actor_user_id=auth.user.id if auth.user else None,
        organization_id=organization_id,
        creator_id=creator_id,
        resource_type="connector_run",
        metadata={"rows_read": result.rows_read, "rows_written": 0},
    )
    await session.commit()
    return result
```

Critical: never put fan usernames, message bodies, or revenue
breakdowns into audit metadata — the redactor catches credential keys,
not PII. Aggregates only.

---

## 9. Remaining gaps

| # | Gap | Severity | Sprint |
|---|---|---|---|
| G1 | `gateways.token` is still plaintext (R4) | high | Sprint 3 |
| G2 | `app_settings` is still global, not org-scoped (R5) | high | Sprint 3 |
| G3 | `SETTINGS_ENCRYPTION_KEY` fallback is allowed for legacy flows (R2) | medium | Sprint 3 / KMS migration |
| G4 | No login / 403-denial audit (Sprint 1 gap G2/G3) | medium | Sprint 3 |
| G5 | No retention / cleanup on `audit_events` | low | Sprint 3 |
| G6 | No frontend security dashboard — only the JSON endpoint | low | Sprint 3 / 4 |
| G7 | `NEXT_PUBLIC_LOCAL_AUTH_TOKEN` build-var footgun (R1) | high | frontend hardening sprint |
| G8 | Approval workflow is API-only (no UI to approve/reject) | medium | Sprint 3 |
| G9 | Consent capture is out-of-band only (no portal) | low | post-MVP |
| G10 | No PII redaction layer in front of LLM calls | medium | Sprint 3 |
| G11 | `creator_credentials.encrypted_value` shares the global Fernet key — no per-creator key partitioning | medium | future |

---

## 10. Recommended Security Sprint 3

In priority order:

1. **Encrypt `gateways.token`** + backfill migration. The same
   `encrypt_value` / `decrypt_value` helpers added in this sprint can
   be reused.
2. **Org-scope `app_settings`.** Add nullable `organization_id`
   column; reads default to "global" rows when org is unset.
3. **Refuse to start in production without `SETTINGS_ENCRYPTION_KEY`.**
   Move the dev-mode fallback behind an explicit `ENVIRONMENT=dev`
   guard so a misconfigured prod instance fails loud.
4. **Login + 403-denial audit.** A single hook in
   `get_auth_context` and a single hook on `HTTPException(403)`
   responses, both calling `record_audit`.
5. **Admin UI for approvals + kill switches.** Read+write versions of
   `GET /api/v1/security/status` with explicit owner-only guards.
6. **Audit retention job.** RQ scheduled task; keep ≥730 days per
   security plan §7.2.
7. **Connector run wrapper that *uses* the gate.** Deliberately
   non-OF: pick the OnlyMonster sync as the first integration to gate,
   to prove the seam works before any OF code is written.
