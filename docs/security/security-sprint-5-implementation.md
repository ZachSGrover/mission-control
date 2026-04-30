# Security Sprint 5 — Enforcement

**Status:** Sprint 5 of N. Moves Sprint 1–4's foundation from "passive
controls plus admin UI" into enforced default paths: gateway tokens
default-masked, retention supervisor wired into the lifespan, Svix
verification path for the Clerk webhook, settings-scope feature flag,
public-secret CI guardrail, approval/consent creation endpoints, and a
documented gated-OnlyMonster scaffold ready to receive a real client.
**Branch:** `feat/security-enforcement-sprint-5`
**Last updated:** 2026-04-30

Companion to:
- [Sprint 1 audit foundation](./audit-events-implementation.md)
- [Sprint 2 prevention](./security-sprint-2-implementation.md)
- [Sprint 3 hardening](./security-sprint-3-implementation.md)
- [Sprint 4 operations](./security-sprint-4-implementation.md)

---

## 1. What was added

| Concern | Where |
|---|---|
| Gated OnlyMonster sync scaffold (env-disabled by default) | [`backend/app/services/gated_onlymonster_sync.py`](../../backend/app/services/gated_onlymonster_sync.py) |
| Settings-scope feature-flag wrapper | [`backend/app/services/settings_scope.py`](../../backend/app/services/settings_scope.py) |
| Clerk webhook Svix-or-fallback verifier | [`backend/app/core/clerk_webhook_verify.py`](../../backend/app/core/clerk_webhook_verify.py) |
| Webhook handler now uses verifier | [`backend/app/api/clerk_webhooks.py`](../../backend/app/api/clerk_webhooks.py) |
| Gateway token default-mask + opt-in `?include_token=1` | [`backend/app/api/gateways.py`](../../backend/app/api/gateways.py) |
| Frontend gateway pages updated to use `token_configured` | [`frontend/src/app/gateways/[gatewayId]/page.tsx`](../../frontend/src/app/gateways/[gatewayId]/page.tsx), [`frontend/src/app/gateways/[gatewayId]/edit/page.tsx`](../../frontend/src/app/gateways/[gatewayId]/edit/page.tsx) |
| Retention supervisor registered in lifespan | [`backend/app/main.py`](../../backend/app/main.py) |
| Approval + consent creation endpoints | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py) |
| PII redactor: labelled names + street addresses | [`backend/app/core/pii_redact.py`](../../backend/app/core/pii_redact.py) |
| Public-secret CI guardrail test | [`backend/tests/test_public_secret_guardrail.py`](../../backend/tests/test_public_secret_guardrail.py) |
| Tests | [`backend/tests/test_security_enforcement.py`](../../backend/tests/test_security_enforcement.py) |

---

## 2. OnlyMonster / safe sync gate wiring — status

**Wired as a documented scaffold; not active until the OFI branch
merges.** The new `gated_onlymonster_creator_sync` is the seam every
real OnlyMonster `creator_sync` call must pass through. It refuses to
invoke any callable until both:

1. `MC_ONLYMONSTER_GATED_SYNC_ENABLED=1` is set in the env, AND
2. `is_connector_action_allowed(connector_type="onlymonster",
   requested_action="creator_sync", ...)` returns `allowed=True`.

When the OFI branch merges, the OnlyMonster integration code should
import `gated_onlymonster_creator_sync` and pass a closure that performs
the real read. The `requested_action` is hard-coded to `"creator_sync"`
so a write callable can't be smuggled through this seam.

**Not done — explicit deferral:** wiring into a real production hot
path. There is no OnlyMonster client on this branch (it lives on
`feat/of-intelligence`). The brief explicitly authorised this
deferral. Sprint 6 will wire after the merge.

Tests cover both the env-disabled refusal path and the gate-enabled
"first failure short-circuits to no_approval" path.

---

## 3. Gateway token cutover — status

**Done — default-masked with audited opt-in.** Every gateway read path
now masks the legacy plaintext `token` field by default:

- `GET /api/v1/gateways` — every row in the page is masked.
- `GET /api/v1/gateways/{id}` — masked unless `?include_token=1` is
  passed. The opt-in path records a `gateway.token.exposed` audit row
  at severity `warning`.
- `POST /api/v1/gateways` — created row is masked in the response.
- `PATCH /api/v1/gateways/{id}` — updated row is masked in the response.

`GatewayRead.token_configured` (Sprint 4) is populated truthfully on
every response.

**Frontend cutover:**
- `gateways/[gatewayId]/page.tsx` — display field switched from
  `maskToken(gateway.token)` to `gateway.token_configured ? "configured"
  : "not set"`.
- `gateways/[gatewayId]/edit/page.tsx` — the edit form's PATCH body now
  only includes `token` when the user typed a non-empty value.
  Changing the URL or workspace_root no longer clobbers a configured
  token, and rotating still works (user types the new value).

**Known small regression:** the gateway-status query in the detail
page still passes `gateway.token` (which is now `null`) to the
remote-gateway status check. This means the live-status indicator may
report "no token" even when a token is configured. Rotate via the
edit form to repopulate. Sprint 6 will add an explicit
`/gateways/{id}/runtime-status` endpoint that reads the encrypted
token server-side, so the frontend never needs raw access.

---

## 4. Org-scoped settings — status

**Foundation extended; cutover behind feature flag.** Sprint 3 added
the `app_settings_scoped` primitives. Sprint 5 adds
[`app/services/settings_scope.py`](../../backend/app/services/settings_scope.py),
a thin wrapper that routes `get/set/delete` to the org-scoped store
when `MC_APP_SETTINGS_ORG_SCOPED=1` AND an `organization_id` is
supplied. Default off — legacy global storage stays intact.

**Not done — explicit deferral:** migrating the existing call sites in
`backend/app/api/{app_settings,integrations}.py` to use this wrapper.
The wrapper is in place, tested, and documented; flipping the call
sites is a low-risk follow-up that should land alongside a UX change
to scope provider keys per org. Sprint 6.

Tests verify:
- Flag off → writes go to the global row even with `organization_id`
  passed.
- Flag on → writes are isolated per org; org A's key is invisible to
  org B.

---

## 5. Clerk webhook verification — status

**Done.** The endpoint now uses
[`app/core/clerk_webhook_verify.verify_webhook`](../../backend/app/core/clerk_webhook_verify.py)
which:

1. Checks if `svix` is importable. If yes, runs
   `svix.Webhook(secret).verify(payload, headers)` — the proper
   Clerk signing scheme.
2. If Svix is missing, falls back to the Sprint 4 shared-secret HMAC
   check **only** when allowed:
   - In dev/local/test: always allowed.
   - In production: requires explicit
     `CLERK_WEBHOOK_ALLOW_SHARED_SECRET=1`. Without that, missing Svix
     in prod is a hard 401 with a message telling the operator to
     install `svix` or set the flag.

`pip install svix` (or adding it to `pyproject.toml`) upgrades to
proper verification with no other code change. The shared-secret path
remains for emergency rollback / dev convenience.

Login-success audit on `session.created` is unchanged from Sprint 4 —
user id, email, IP, capped UA. **No tokens, cookies, or session ids
logged.**

Tests cover all four paths: no-secret error, dev-shared-secret
success, prod-no-svix-no-flag refusal, prod-with-flag success.

---

## 6. Audit retention scheduling — status

**Done — registered in lifespan, opt-in by env flag.** The supervisor
is now spawned as a background task in `app.main.lifespan`. The
supervisor itself (Sprint 4) refuses to do anything unless
`MC_AUDIT_RETENTION_ENABLED=1`, so the default deploy carries no
retention activity.

To enable in production:
- Set `MC_AUDIT_RETENTION_ENABLED=1` to start the loop.
- Set `MC_AUDIT_RETENTION_DRY_RUN=0` to actually delete (real purges
  audit at severity `critical`). Default is dry-run.

The supervisor inherits the existing background-task lifecycle:
cancels on `_bg_stop`, joins cleanly on app shutdown.

---

## 7. Public-secret guardrail — status

**Done — pytest-based, runs in CI by default.** New
[`tests/test_public_secret_guardrail.py`](../../backend/tests/test_public_secret_guardrail.py)
scans `frontend/src/**/*.{ts,tsx,js,jsx,mjs}` for any
`NEXT_PUBLIC_*` reference whose name contains `SECRET`, `TOKEN`,
`PASSWORD`, or `KEY`, and fails if it isn't on the explicit allowlist.

The allowlist is a small set of names that have been reviewed as
"OK to ship in the bundle" (e.g. `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`)
or "dev-only with runtime guard" (e.g. `NEXT_PUBLIC_LOCAL_AUTH_TOKEN`,
already constrained by [`localAuth.ts`](../../frontend/src/auth/localAuth.ts)).

A failure prints the offending names and tells the operator to either
add a justification to the allowlist or refactor to fetch the value
server-side.

---

## 8. Approval and consent creation — status

**Done.** Two new owner-only endpoints round out the lifecycle:

- `POST /api/v1/security/approvals` — creates a `pending` connector
  approval. Audits `connector.approval.request`. Validates
  `connector_type` + `risk_level` against the enum.
- `POST /api/v1/security/consents` — creates a `granted` consent.
  Audits `consent.grant`. Validates `consent_type`.

Both endpoints accept ISO timestamps for `expires_at` and route the
actor's id+email into the audit metadata. Front-end UI for these
forms is **deferred to Sprint 6** — the brief authorised that.

---

## 9. PII redaction improvements — status

**Done — additive, conservative.** Two new patterns:

- `labelled_name` — catches `Full Name: Alice Smith` /
  `First Name: Bob` / `Last Name: …`. Requires the explicit label so
  business strings like `Creator-A` or `Aria Veil` (without a
  preceding label) are not redacted.
- `street_address` — catches `1234 Elm Street` /
  `5678 Maple Ave.`. Requires a leading 1–5 digit number, a
  capitalised street name, and a known suffix
  (`St`/`Street`/`Rd`/`Road`/`Ave`/`Avenue`/`Blvd`/`Boulevard`/`Ln`/
  `Lane`/`Dr`/`Drive`/`Ct`/`Court`/`Way`/`Pl`/`Place`).

Existing tests verifying business-string preservation still pass.

---

## 10. Direct OnlyFans readiness

**Still blocked.** No direct OF connector exists; no OF write actions
exist; no real OF account is connected; the gated-sync scaffold is
explicitly OnlyMonster (read-only `creator_sync` action) and is
disabled by env flag in any case. The four prerequisites from the
security plan §4–§5 remain:

1. Approval flow — **done** (Sprint 2 + Sprint 4 + Sprint 5 creation
   endpoint).
2. Consent records — **done**.
3. Encrypted vault — **done** (Sprint 2).
4. Connector gate as a *required* pre-check on real I/O — **wrapper
   ready, hot-path wiring is Sprint 6 (OnlyMonster first, OF only
   after that proves out)**.

Plus the operational prerequisites from Sprint 4's
[`direct-connector-safety-checklist.md`](./direct-connector-safety-checklist.md):
production refuses fallback encryption (Sprint 3 ✅), gateway tokens
encrypted-at-rest with default-masked API (Sprint 3 + Sprint 5 ✅),
audit retention scheduled (Sprint 5 ✅), denial audit enriched
(Sprint 4 ✅), Svix verification path (Sprint 5 ✅).

Outstanding for direct-OF go-live (must be green before *any* real OF
account is connected):
- Connector gate wired as a required pre-check on a real
  non-OF integration first (Sprint 6).
- Frontend security admin page extended with create-approval +
  grant-consent forms (Sprint 6).
- Org-scoped settings cutover finished (Sprint 6).
- Per-creator key partitioning in `creator_credentials` (future).
- A documented incident drill against the breach response plan
  (Sprint 6).

---

## 11. Remaining gaps

| # | Gap | Severity | Sprint |
|---|---|---|---|
| G1 | Existing `app_settings`/`integrations` callers still write to global rows (the wrapper is ready) | medium | Sprint 6 |
| G2 | Gateway runtime-status check still requires raw token in frontend; should move server-side | low | Sprint 6 |
| G3 | Connector gate not yet wired into a real production hot path (OnlyMonster sync once OFI merges) | medium | Sprint 6 |
| G4 | No `svix` package in `pyproject.toml` — verifier falls back to shared-secret in current deploys | medium | Sprint 6 (`uv add svix`) |
| G5 | No frontend forms for creating approvals / granting consents (backend endpoints landed) | low | Sprint 6 |
| G6 | Per-dep denial audit detail (specific role/permission strings at the dep) | low | Sprint 6 |
| G7 | Per-creator key partitioning still missing in `creator_credentials` | medium | future |
| G8 | LLM PII redactor doesn't scrub usernames or unlabelled person-names | low | post-MVP |
| G9 | No documented incident drill against `breach-response-plan.md` | low | Sprint 6 |

---

## 12. Recommended Security Sprint 6

In priority order:

1. **Add `svix` to `pyproject.toml`** so production gets proper Clerk
   webhook verification by default (the verifier already does the
   right thing — just need the package).
2. **Wire `gated_onlymonster_creator_sync` into the real OnlyMonster
   client** when the OFI branch merges. First production proof of the
   gate on a real, non-OF integration.
3. **Migrate `app_settings` / `integrations` callers** to
   `settings_scope.set_secret_scoped` with the feature flag enabled
   for one tenant first, then everyone.
4. **Add `/api/v1/gateways/{id}/runtime-status`** that reads the
   decrypted token server-side and returns only the status — frontend
   never needs raw access.
5. **Frontend forms** for creating approvals and granting consents,
   wired to the new Sprint 5 endpoints.
6. **Document an incident drill** — pick the breach response plan's
   token-leak scenario, run it on a staging dataset, write up the
   timeline.
