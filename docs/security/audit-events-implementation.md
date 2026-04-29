# Audit Events — Implementation Notes (Security Sprint 1)

**Status:** Sprint 1 of N. Audit foundation in place; not yet wired to OFI / connector / export paths (those land on later branches).
**Branch:** `feat/security-foundation-sprint-1`
**Last updated:** 2026-04-29

This document is the developer-facing companion to the durable plan in
[`onlyfans-intelligence-security-plan.md`](./onlyfans-intelligence-security-plan.md)
§8. It explains *what is in the code right now*, where it lives, and how
new code should call it.

---

## 1. What was added

| Concern | Where | Notes |
|---|---|---|
| Audit row schema | [`backend/app/models/audit_events.py`](../../backend/app/models/audit_events.py) | `AuditEvent` SQLModel; soft refs only (no hard FKs) so audit survives user deletion |
| Vocabulary frozensets | same file | `AUDIT_CATEGORIES`, `AUDIT_RESULTS`, `AUDIT_SEVERITIES` — single source of truth, mirrored as `Literal` types in the service |
| Database migration | [`backend/migrations/versions/a01b2c3d4e5f_add_audit_events.py`](../../backend/migrations/versions/a01b2c3d4e5f_add_audit_events.py) | Idempotent create; merges three pre-existing alembic heads as a side benefit |
| Metadata redactor | [`backend/app/core/redact.py`](../../backend/app/core/redact.py) | `redact_metadata()` — recursive, pure, size-capped, no mutation of input |
| Audit service | [`backend/app/services/audit_log.py`](../../backend/app/services/audit_log.py) | `record_audit()` — fail-safe by default; `strict=True` for hard-block paths |
| Tests | [`backend/tests/test_redact.py`](../../backend/tests/test_redact.py), [`backend/tests/test_audit_log.py`](../../backend/tests/test_audit_log.py) | Cover redaction edge cases + service happy/sad path |

---

## 2. Audit row shape

`audit_events` columns (see migration for SQL types):

- `id` (UUID, PK)
- `actor_user_id`, `actor_email`, `actor_role` — **soft refs** (no FK)
- `organization_id`, `creator_id` — soft scope refs
- `event_type` (free-form, e.g. `"settings.api_key.save"`)
- `category` ∈ {auth, credential, role, permission, export, connector, llm, creator_data, fan_data, system, security, integration}
- `action` (free-form verb: `"put"`, `"delete"`, `"invoke"`, …)
- `result` ∈ {success, denied, failed, blocked, skipped}
- `severity` ∈ {info, warning, high, critical}
- `resource_type`, `resource_id` — what was acted upon
- `ip_address`, `user_agent`, `request_id` — optional request context
- `metadata_json` — **always run through `redact_metadata()`**
- `redacted` (bool) — true iff redaction touched anything
- `created_at`

Indexes are populated for every column that is likely to anchor an
investigation: actor, scope, category, severity, result, created_at,
event_type, redacted. See migration.

---

## 3. Metadata redaction

`redact_metadata(value) -> (redacted_dict, was_redacted)`:

- Returns a **new** dict (never mutates input).
- Walks dicts, lists, tuples, sets, primitives, recursively.
- A key is forbidden if its lower-cased name is in `FORBIDDEN_KEYS`
  *or* contains any substring in `FORBIDDEN_KEY_FRAGMENTS`. This catches
  `password`, `oauth_access_token`, `stripe_secret_key`, etc.
- Values that look like credentials regardless of key
  (`Bearer …`, `Basic …`) are also redacted as defence in depth.
- Strings over `MAX_STRING_BYTES` are truncated.
- The total JSON-encoded size is capped at `MAX_TOTAL_BYTES = 16 KiB`.
  Oversized payloads are replaced by a small summary that records the
  original size — never the original content.
- Top-level non-dict input is wrapped in `{"value": …}` so storage shape
  is stable.

Dangerous-key list (case-insensitive, exact + substring): `password`,
`token`, `secret`, `cookie`, `session`, `apiKey`, `api_key`,
`authorization`, `bearer`, `credential`(`s`), `privateKey`,
`private_key`, `refreshToken`, `refresh_token`, `accessToken`,
`access_token`, `clientSecret`, `client_secret`, `encryptionKey`,
`encryption_key`.

---

## 4. `record_audit` — call signature

```python
from app.services.audit_log import record_audit

await record_audit(
    session,
    event_type="settings.api_key.save",
    category="credential",
    action="put",
    result="success",
    severity="warning",
    actor_user_id=auth.user.id if auth.user else None,
    actor_email=auth.user.email if auth.user else None,
    actor_role=role,
    resource_type="api_key",
    resource_id=provider,
    metadata={"provider": provider, "preview": mask_key(value)},
)
await session.commit()
```

Rules of the road:

1. **The helper does not commit.** The caller is responsible. This is
   intentional — audit success/failure should be atomic with the
   business action it describes.
2. **Metadata is auto-redacted.** Passing a forbidden key produces a
   `[REDACTED]` value and flips the row's `redacted` flag. Producers
   never need to redact themselves, but **must not put a raw secret in
   `metadata` and assume it will be safe** — the redactor is a backstop,
   not a license to be careless.
3. **Failure is fail-safe.** If `record_audit` itself raises (e.g. the
   DB is down), it logs `audit.write_failed` and returns `None`. The
   surrounding business action is **not** torpedoed by an audit-pipeline
   glitch. Pass `strict=True` to opt into hard failure.
4. **Vocabularies are pinned.** `category`, `result`, and `severity`
   are `Literal` types — mypy enforces them at every call site, and the
   helper re-validates at runtime as belt-and-braces.

---

## 5. Events tracked **as of this sprint**

Every event is paired with `await session.commit()` so it lands
durably even if the wrapping HTTP transaction is rolled back.

| Site | event_type | category | severity | Notes |
|---|---|---|---|---|
| `PUT /api/v1/integrations/{name}` | `integration.credential.save` | credential | warning | Logs masked preview only |
| `DELETE /api/v1/integrations/{name}` | `integration.credential.delete` | credential | high | |
| `PUT /api/v1/settings/api-keys/{provider}` | `settings.api_key.save` | credential | warning | OpenAI / Gemini / Anthropic |
| `DELETE /api/v1/settings/api-keys/{provider}` | `settings.api_key.delete` | credential | high | |
| `PUT /api/v1/settings/github/{field}` | `settings.github.save` | credential | high if field=github_pat else info | |
| `DELETE /api/v1/settings/github/{field}` | `settings.github.delete` | credential | high if field=github_pat else info | |
| `PUT /api/v1/roles/users/{clerk_user_id}` | `role.set` | role | high | Logs target email + new role |
| `DELETE /api/v1/roles/users/{clerk_user_id}` | `role.remove` | role | high | Result `"skipped"` if no row existed |
| Every LLM provider attempt (`ask_ai_detailed`) | `llm.call` | llm | info on success, warning on failure | Logs provider, attempts, prompt **char count**, reply char count, error class — never prompt or reply body |

---

## 6. Events **not yet** tracked

Listed in priority order. Sprint 2 candidates.

1. **Login / login-failure** — needs hooking into `get_auth_context`'s
   Clerk-or-local resolver in a way that doesn't double-fire. Not done
   in Sprint 1 to keep blast radius small.
2. **Failed authorization** (403) — same caveat: need a single
   chokepoint to log denials without spamming on every request.
3. **Telegram `/test` connection probe** (`backend/app/api/telegram.py`)
   — exists on this branch but wasn't wired; relatively isolated and
   easy to do in Sprint 2.
4. **Org member add/remove, board permission changes** — exist in
   `OrganizationMember` flow; Sprint 2.
5. **Export endpoints** — none on this branch; the OFI memory export
   lives on `feat/of-intelligence`. Audit it when those models merge.
6. **Connector run audit** — no connector run wrapper on this branch
   yet. The wrapper itself is a Sprint-2 deliverable per the security
   plan §5.
7. **Approval lifecycle** (`Approval` table) — should audit
   create/approve/reject. Existing service is uniform enough to wire
   easily.
8. **Sensitive route reads** — list-all-users, list-all-creators,
   bulk-fan-list. Currently unaudited. Low-volume audit targets.
9. **Kill-switch toggles** — kill switch doesn't exist yet; when it
   lands (Sprint 2 per security plan §5.3) every toggle MUST audit.

---

## 7. How a future OnlyFans Intelligence connector run should call this

Sketch (do **not** implement the connector itself before the safety
checklist passes — see
[`direct-connector-safety-checklist.md`](./direct-connector-safety-checklist.md)):

```python
async def run_creator_sync(
    session: AsyncSession,
    *,
    auth: AuthContext,
    creator_id: str,
    organization_id: UUID,
    mode: Literal["read", "read_write", "dry_run"],
) -> SyncResult:
    # 1. Check kill switch + connector status + consent BEFORE any IO.
    if killed_or_unapproved_or_no_consent(...):
        await record_audit(
            session,
            event_type="connector.sync.start",
            category="connector",
            action="start",
            result="blocked",
            severity="high",
            actor_user_id=auth.user.id if auth.user else None,
            organization_id=organization_id,
            creator_id=creator_id,
            resource_type="connector_instance",
            resource_id=instance_id,
            metadata={"reason": "kill_switch|unapproved|no_consent", "mode": mode},
        )
        await session.commit()
        raise HTTPException(409, "connector blocked")

    await record_audit(
        session,
        event_type="connector.sync.start",
        category="connector",
        action="start",
        result="success",
        actor_user_id=auth.user.id if auth.user else None,
        organization_id=organization_id,
        creator_id=creator_id,
        resource_type="connector_instance",
        resource_id=instance_id,
        metadata={"mode": mode},
    )
    await session.commit()

    try:
        result = await actually_sync(...)
    except Exception as exc:
        await record_audit(
            session,
            event_type="connector.sync.finish",
            category="connector",
            action="finish",
            result="failed",
            severity="high",
            ...,
            metadata={"error_class": type(exc).__name__},
        )
        await session.commit()
        raise

    await record_audit(
        session,
        event_type="connector.sync.finish",
        category="connector",
        action="finish",
        result="success",
        ...,
        metadata={
            "rows_read": result.rows_read,
            "rows_written": 0,  # ← MUST be 0 in `read` or `dry_run` mode
            "duration_s": round(result.duration, 2),
        },
    )
    await session.commit()
    return result
```

Critical: never put fan usernames, message bodies, or revenue
breakdowns into `metadata` — the redactor catches obvious credentials,
not PII. Use aggregates only.

---

## 8. How future LLM calls should call this

`ai_backend.ask_ai_detailed` already audits each provider attempt with
zero prompt/reply text. New LLM call sites should either:

- **Route through `ask_ai_detailed`** (preferred) — they get the audit
  for free.
- **Or** call `record_audit(category="llm", …)` at the call site,
  passing `prompt_chars`, `reply_chars`, provider, model, latency,
  error_class, and **nothing** that could contain content.

The redactor strips obvious credential keys but is not a PII filter.
Treat LLM metadata as low-fidelity by design.

---

## 9. Remaining gaps (operational)

| # | Gap | Severity | Sprint |
|---|---|---|---|
| G1 | Three pre-existing alembic heads — merged by this sprint's migration as a side benefit, but worth verifying with `alembic heads` after pull | low | done in this sprint |
| G2 | No login / login-failure audit | medium | Sprint 2 |
| G3 | No 403 / denial audit | medium | Sprint 2 |
| G4 | No retention policy on `audit_events` (rows accumulate forever) | low | Sprint 3 (per security plan §7.2 → 730 days) |
| G5 | Audit reads (querying who-did-what) have no UI | low | Sprint 3 |
| G6 | Audit table is not separately encrypted at rest (relies on DB-level encryption) | medium | Sprint 3 / KMS work |
| G7 | No automated alerting on suspicious patterns (e.g. credential write burst) | medium | Sprint 3 / monitoring |

---

## 10. Recommended Security Sprint 2

Build on this foundation, in priority order:

1. **Connector approval flow + kill switch** — security plan §5.1 +
   §5.3. Database-backed `connector_instances` table with
   `status (pending|approved|active|suspended)` and `mode (read|read_write|dry_run)`.
   Wire `record_audit` on every transition.
2. **Client consent records** (`client_consents` table) — security
   plan §6. Block any sync without a live consent row.
3. **Kill-switch row** (`mc.connectors.frozen`, `mc.ai.frozen`) and
   admin UI to toggle. Every toggle audits at severity `critical`.
4. **Login + denial audit** — close gaps G2/G3.
5. **Encrypt `gateways.token`** — risk R4 from
   [`security-gap-audit.md`](./security-gap-audit.md). Migration to
   re-encrypt existing rows under the same `SETTINGS_ENCRYPTION_KEY`.
6. **Org-scope `app_settings`** — risk R5. Add nullable
   `organization_id`, scope reads.
7. **`creator_credentials` table** — security plan §4.1 / direct
   connector prerequisite. Encrypted, key-versioned, with rotation API.

Sprint 2 is the bridge from "we can investigate" to "we can prevent."
