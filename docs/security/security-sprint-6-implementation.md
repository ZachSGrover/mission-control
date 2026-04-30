# Security Sprint 6 — Readiness

**Status:** Sprint 6 of N. Turns Sprint 1–5's enforced defaults into
**operational readiness**: the integration seam future OnlyMonster code
must call, server-side gateway runtime status (so the frontend never
needs the raw token), settings-scope cutover behind the existing
feature flag, frontend forms for creating approvals and consents, an
explicit denial-audit detail helper, and two new operator runbooks
(token-leak drill, direct-OnlyFans readiness checklist).
**Branch:** `feat/security-readiness-sprint-6`
**Last updated:** 2026-04-28

Companion to:
- [Sprint 1 audit foundation](./audit-events-implementation.md)
- [Sprint 2 prevention](./security-sprint-2-implementation.md)
- [Sprint 3 hardening](./security-sprint-3-implementation.md)
- [Sprint 4 operations](./security-sprint-4-implementation.md)
- [Sprint 5 enforcement](./security-sprint-5-implementation.md)

---

## 1. What was added

| Concern | Where |
|---|---|
| Typed read-only OnlyMonster integration seam | [`backend/app/services/onlymonster_integration.py`](../../backend/app/services/onlymonster_integration.py) |
| App settings + integrations cut over to scoped wrapper | [`backend/app/api/app_settings.py`](../../backend/app/api/app_settings.py), [`backend/app/api/integrations.py`](../../backend/app/api/integrations.py) |
| Gateway runtime-status server-side endpoint | [`backend/app/api/gateways.py`](../../backend/app/api/gateways.py) |
| Approval + consent creation forms in security admin UI | [`frontend/src/app/security/page.tsx`](../../frontend/src/app/security/page.tsx), [`frontend/src/lib/security/api.ts`](../../frontend/src/lib/security/api.ts) |
| Denial-audit explicit detail helper | [`backend/app/core/denial_audit.py`](../../backend/app/core/denial_audit.py) |
| Token-leak incident drill runbook | [`docs/security/incident-drill-token-leak.md`](./incident-drill-token-leak.md) |
| Direct OnlyFans readiness checklist | [`docs/security/direct-onlyfans-readiness-checklist.md`](./direct-onlyfans-readiness-checklist.md) |
| Sprint 6 readiness tests | [`backend/tests/test_security_readiness.py`](../../backend/tests/test_security_readiness.py) |

---

## 2. OnlyMonster integration seam — status

**Done — typed read-only adapter ready for the real client.** The new
`fetch_creator_snapshot` is the function the OFI branch's real
OnlyMonster client must call. It is built on top of Sprint 5's
`gated_onlymonster_creator_sync`, so:

- The env flag (`MC_ONLYMONSTER_GATED_SYNC_ENABLED=1`) AND the
  connector gate (kill switches off, approval present, consent live)
  must both pass before the underlying client is invoked.
- On block, returns `None`; the gated wrapper writes
  `connector.run.blocked`.
- On allow, returns a `CreatorSnapshot` with `rows_written = 0`
  enforced as an invariant; the seam writes `connector.run.finish`
  with **only** the safe metadata fields:
  `connector_type`, `requested_action`, `rows_read`, `rows_written`,
  `last_event_at_iso`. No fan PII, no message bodies, no revenue
  breakdowns are present in the audit row.
- A `RuntimeError` is raised if gates pass but no client is wired —
  catches the bug where an operator flips the env flag in production
  before connecting the real client.

**Not done — explicit deferral:** wiring into the real OnlyMonster
client. The client lives on `feat/of-intelligence` (not this branch).
Replace `_FAKE_CLIENT_PATH` and the `_do_fetch` body when the OFI
branch merges. The Sprint 6 tests prove the seam end-to-end against a
fake client today, so post-merge integration is mechanical.

---

## 3. App settings + integrations org-scope cutover — status

**Done — both API surfaces now route through the scoped wrapper.**
`backend/app/api/app_settings.py` and `backend/app/api/integrations.py`
were migrated from the legacy `set_secret` / `delete_secret` /
`get_secret_with_source` calls to:

- `set_secret_scoped(session, key, value, organization_id=...)`
- `delete_secret_scoped(session, key, organization_id=...)`
- `get_secret_scoped(session, key, organization_id=...)`

For the cutover all three call sites pass `organization_id=None`,
which preserves the existing global-secret behaviour byte-for-byte
when `MC_APP_SETTINGS_ORG_SCOPED` is unset (Sprint 5 default). When
the flag is on, the wrapper transparently uses derived `org:{uuid}.{key}`
storage keys without breaking the SQLModel `app_settings.key` primary
key. Future sprints can resolve the caller's `organization_id` from
the request context and pass it here without re-touching either file.

The result: the cutover is "plumbing complete, semantics unchanged"
— a green diff that unlocks per-org secret isolation behind a flag.

---

## 4. Gateway runtime-status server-side — status

**Done — frontend no longer needs the raw token to render
"configured / not configured."** New endpoint:

`GET /api/v1/gateways/{gateway_id}/runtime-status`

Response shape (`GatewayRuntimeStatusResponse`):

| Field | Purpose |
|---|---|
| `gateway_id` | echo of the path param |
| `token_configured` | bool — true iff any token (encrypted or legacy) is on disk |
| `token_source` | `"encrypted"` / `"legacy_plaintext"` / `"none"` — operator-relevant state without leaking the value |
| `url_set` | bool |
| `allow_insecure_tls` | bool |
| `disable_device_pairing` | bool |

The endpoint is read-only, scoped by `require_org_admin`, and never
returns the token value, a preview, or a length. The Sprint 5
`?include_token=1` opt-in on the row endpoint remains the *only* path
that discloses the raw token, and it audits.

This unblocks frontend pages that previously had to fetch the token
just to compute `Boolean(gw.token)` for their UI. The new endpoint
gives them the same answer with no secret transit.

---

## 5. Approval + consent creation UI — status

**Done — owner can drive the full lifecycle from the security admin
page.** The Sprint 5 backend endpoints (`POST /security/approvals`,
`POST /security/consents`) now have matching frontend forms:

- `ApprovalForm` — typed dropdowns for connector type and risk level,
  text inputs for requested action, creator id, organization id,
  expires-at, and a reason field that lands in the audit row.
- `ConsentForm` — typed dropdown for consent type, plus creator id,
  organization id, source (e.g. signed PDF / DocuSign), document
  reference (URL or hash), expires-at, and a notes field.

Both forms are owner-gated by the existing `RoleGuard` wrapping
`SecurityAdmin`. Validation is server-side; the form surfaces 400
errors verbatim. The forms collapse to a button when not in use to
keep the page tight.

The backend endpoints already wrote audit rows (Sprint 5); no new
audit hooks were added — the UI just calls into the same handlers.

---

## 6. Denial-audit explicit detail — status

**Done — dependencies can carry typed denial information without
leaking it into the response body.** New helper:

```python
attach_denial_detail(
    exc,
    dependency="require_owner",
    reason_category="role_required_owner",
    required_role="owner",
)
raise exc
```

The detail is stashed on a private `_mc_denial_detail` attribute that
the denial-audit handler reads via `getattr`. The HTTP response body
remains whatever `exc.detail` was — no new fields, no leaked metadata.

`_reason_category` was updated to prefer the explicit dict; if the
attribute is absent, it falls through to the existing keyword-scan
inference (so existing `HTTPException(403, "Owner role required")`
sites still bucket correctly).

The next sprint that touches each dependency can call
`attach_denial_detail` to upgrade the audit detail at the call site.
For now, the helper exists and is tested; existing dependencies still
pass through the keyword inference unchanged.

---

## 7. Clerk webhook hardening — status

**Already isolated in Sprint 5.** No code change in Sprint 6 — the
verifier in `backend/app/core/clerk_webhook_verify.py` already prefers
Svix when installed and refuses the shared-secret fallback in
production unless `CLERK_WEBHOOK_ALLOW_SHARED_SECRET=1` is set.

To finish hardening (out of scope for this sprint, captured here so
the operator notices):

1. Add `svix>=1.20` to `backend/pyproject.toml` under
   `[project.dependencies]`.
2. Run `pip install -e .` (or rebuild the container).
3. The verifier auto-detects `svix` and switches to it; no further
   code change is required.
4. Once Svix is in production, set
   `CLERK_WEBHOOK_ALLOW_SHARED_SECRET=0` (or simply remove the env
   var) so the fallback is unreachable.

This is a five-minute change but it depends on a dependency-install
choice the operator should make explicitly, hence "documented but
not committed in this sprint."

---

## 8. Token-leak incident drill — status

**Done — runbook written and ready to walk.** See
[`docs/security/incident-drill-token-leak.md`](./incident-drill-token-leak.md).
Highlights:

- 60-minute clock with milestones at T+0, T+5, T+15, T+35, T+50, T+60.
- Pre-drill setup checklist of 7 items (audit table accessible,
  kill switches present, dedicated encryption key, contact card,
  provider-dashboard reachability from a backup device, and a
  `creator_credentials` rotation runbook).
- Five drill cadences (OpenAI, GitHub PAT, Clerk secret, OnlyMonster
  credential, `SETTINGS_ENCRYPTION_KEY`) with frequencies and owners.
- An explicit "what this drill catches" list — failure modes
  (provider 2FA tied to one device; missing pre-commit hook;
  unreachable usage logs) that a tabletop pulls out of the runbook.

Drill cadence: quarterly for the most likely variants (OpenAI key,
GitHub PAT, OnlyMonster credential), annually for compound scenarios.

---

## 9. Direct OnlyFans readiness checklist — status

**Done — the gate between "controls exist" and "we may handle creator
credentials."** See
[`docs/security/direct-onlyfans-readiness-checklist.md`](./direct-onlyfans-readiness-checklist.md).
Highlights:

- Section A is a status report of what currently fails closed (gate,
  gated wrapper, encryption guardrail, scoped settings, denial-audit,
  PII redactor, Clerk webhook verifier, retention scheduler, gateway
  runtime-status). If any of these is intentionally weakened, the
  checklist is invalidated.
- Section B is the foundation prerequisites map (Sprints 1–6); each
  line points at the implementation doc that proves it.
- Section C is the gate for OnlyMonster behind the gated wrapper
  against a sandbox account.
- Section D is the gate for first real creator behind OnlyMonster.
- Section E is explicit pre-state for direct OnlyFans — every line
  is `❌` because the connector module does not exist on this branch,
  and that's correct.
- Section G lists re-validation triggers (any control weakening,
  encryption key rotation, new operator with grants, consent
  revocation, modification of the seam file, OFI client merge).

The honest top-line: **direct OnlyFans is not unblocked by this
checklist**, but the checklist makes the remaining gaps named and
tracked instead of implicit and forgotten.

---

## 10. Tests

New file: [`backend/tests/test_security_readiness.py`](../../backend/tests/test_security_readiness.py).
Cases:

| Test | Asserts |
|---|---|
| `test_fetch_creator_snapshot_blocks_when_gate_disabled` | env flag off → returns `None`, fake client never invoked, `connector.run.blocked` audited, no `connector.run.finish` |
| `test_fetch_creator_snapshot_blocks_when_no_approval` | env flag on but no approval → returns `None`, fake client never invoked |
| `test_fetch_creator_snapshot_runs_and_audits_finish_when_allowed` | env flag on, approval + consent live → `CreatorSnapshot` returned, `rows_written == 0`, `connector.run.finish` row carries only safe metadata fields |
| `test_fetch_creator_snapshot_refuses_loudly_without_client` | env flag on, gates pass, but no client wired → `RuntimeError` (catches the env-flipped-but-not-wired footgun) |
| `test_attach_denial_detail_overrides_keyword_inference` | explicit detail wins over `exc.detail` keyword scan; private attribute, public detail unchanged |
| `test_reason_category_falls_through_to_inference_without_attached_detail` | existing call sites still work |
| `test_attach_denial_detail_returns_same_exception` | helper returns the same `HTTPException` for one-line `raise` |
| `test_gateway_runtime_status_classifies_token_sources` | response model has no `token` / `preview` field; classifies all three states |

Plus the existing Sprint 5 enforcement tests still pass — the org-scope
cutover and gateway-runtime endpoint do not break any prior behaviour.

---

## 11. What was NOT done (and why)

Captured here so the next sprint reviewer can tell at a glance what
the brief authorised vs. what was deferred.

| Item | Status | Reason |
|---|---|---|
| Wire OnlyMonster real client into `fetch_creator_snapshot` | deferred | Real client lives on `feat/of-intelligence`; brief explicitly authorised the seam-only path on this branch. Replace `_FAKE_CLIENT_PATH` and `_do_fetch` body post-merge. |
| Direct OnlyFans connector module | deferred | Out of scope for the entire security sequence; gated by `direct-onlyfans-readiness-checklist.md` Section E. |
| Add `svix` to `pyproject.toml` | deferred | Dependency-install choice the operator should make explicitly. Verifier auto-detects when present. |
| Apply `attach_denial_detail` to every dependency | deferred | The helper exists and is tested. Each dependency that needs a typed reason can be upgraded incrementally without re-touching the audit handler. |
| Resolve `organization_id` from request context in `app_settings.py` / `integrations.py` | deferred | Cutover plumbing complete; behind feature flag; Sprint 7+ can resolve org from the auth context without re-touching the API surfaces. |
| Frontend cutover to `runtime-status` endpoint on every gateway page | deferred | Endpoint lands; the frontend can switch incrementally. The Sprint 5 `?include_token=1` audited disclosure path remains the canonical edit-page surface. |

---

## 12. Migration impact

None. No new schema, no new env vars required for default behaviour,
no new background jobs, no breaking API changes.

The gateway runtime-status endpoint is additive. The denial-audit
detail helper is additive. The org-scope cutover is plumbing-only
and gated by `MC_APP_SETTINGS_ORG_SCOPED`. The OnlyMonster seam
is read-only and refuses to run by default.

---

## 13. Sign-off scope

This sprint:

- ✅ The integration seam exists, is tested, and is read-only by
  invariant.
- ✅ App settings and integrations route through the scoped wrapper.
- ✅ The frontend can render gateway status without the raw token.
- ✅ The owner can create approvals and consents from the UI.
- ✅ Denial-audit detail can be made explicit per dependency.
- ✅ A token-leak drill is written and ready to run.
- ✅ A direct-OnlyFans readiness checklist names what's blocked and
  why, including the items that are correctly red.

This sprint does **not** authorise:

- A real OnlyMonster sync against a non-test account.
- A direct OnlyFans connector.
- Removing the env-flag opt-in for the gated wrapper.
- Any creator data leaving sandbox.
