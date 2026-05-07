# Security Sprint 8A — OnlyMonster Gated Production Proof

**Status:** Sprint 8A of N. Proves the Sprint 1–6 security gate on the
**real OnlyMonster integration-style path** before any direct OnlyFans
connector is implemented. The chain (env flag → connector gate →
seam → audit) is exercised end-to-end with a typed fake client.
**Branch:** `feat/gated-onlymonster-proof-sprint-8a`
**Last updated:** 2026-04-30

Companion to:
- [Sprint 1 audit foundation](./audit-events-implementation.md)
- [Sprint 2 prevention](./security-sprint-2-implementation.md)
- [Sprint 3 hardening](./security-sprint-3-implementation.md)
- [Sprint 4 operations](./security-sprint-4-implementation.md)
- [Sprint 5 enforcement](./security-sprint-5-implementation.md)
- [Sprint 6 readiness](./security-sprint-6-implementation.md)
- [Sprint 7 direct OF read-only prep](./security-sprint-7-direct-of-prep.md)
- [Direct OnlyFans readiness checklist](./direct-onlyfans-readiness-checklist.md)
- [Token-leak incident drill](./incident-drill-token-leak.md)

---

## 1. What was added

| Concern | Where |
|---|---|
| Read-only fake OnlyMonster client (typed) | [`backend/app/services/onlymonster_fake_client.py`](../../backend/app/services/onlymonster_fake_client.py) |
| Gated production-proof entrypoint | [`backend/app/services/onlymonster_gate_proof.py`](../../backend/app/services/onlymonster_gate_proof.py) |
| Owner-only status + preview endpoints | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py) |
| Frontend gate readiness card + run-preview button | [`frontend/src/app/security/page.tsx`](../../frontend/src/app/security/page.tsx), [`frontend/src/lib/security/api.ts`](../../frontend/src/lib/security/api.ts) |
| Sprint 8A tests | [`backend/tests/test_onlymonster_gate_proof.py`](../../backend/tests/test_onlymonster_gate_proof.py) |

---

## 2. How the OnlyMonster gate works

### Layered chain (top to bottom)

```
            UI: /security  → "Run gated preview"
                     │
                     ▼
   POST /api/v1/security/onlymonster-gate/preview
                     │
                     ▼
   run_onlymonster_gated_proof()  ← Sprint 8A
                     │
                     ├── resolve_onlymonster_client()
                     │     refuses fake-in-production unless
                     │     MC_ONLYMONSTER_ALLOW_FAKE_CLIENT=1
                     │
                     ▼
   fetch_creator_snapshot()  ← Sprint 6 seam
                     │
                     ▼
   gated_onlymonster_creator_sync()  ← Sprint 5 wrapper
                     │
                     ├── env flag MC_ONLYMONSTER_GATED_SYNC_ENABLED
                     │
                     ▼
   run_with_gate(connector_type="onlymonster", action="creator_sync")
                     │
                     ├── kill switch (global → connector → org → creator)
                     ├── connector approval (live row required)
                     ├── client consent (live row required)
                     └── vault available (SETTINGS_ENCRYPTION_KEY)
                     │
                     ▼
   FakeOnlyMonsterClient.read_only_pull(creator_id)
                     │
                     ▼
   audit rows:
     connector.run.blocked  (on any block, written by gated wrapper)
     connector.run.finish   (on allow, written by Sprint 6 seam)
     connector.gated_proof.blocked  (Sprint 8A wrapper)
     connector.gated_proof.success  (Sprint 8A wrapper, on allow)
```

### Refusal layers, in order

1. **Production fake guard** — if running in production and only a
   fake client is supplied without `MC_ONLYMONSTER_ALLOW_FAKE_CLIENT=1`,
   `FakeClientRefusedInProductionError` is raised after writing a
   `connector.gated_proof.blocked` audit row with
   `error_category=fake_refused_in_production`.
2. **Env flag** (`MC_ONLYMONSTER_GATED_SYNC_ENABLED`) — Sprint 5's
   gated wrapper short-circuits to a blocked verdict if unset, with
   `verdict_reason=scaffold_disabled`.
3. **Connector gate** — kill switch / approval / consent / vault.
   First failure short-circuits with `verdict_reason` and
   `verdict_detail` populated.
4. **Allowed path** — fake client called once with the creator id.
   Output is summarised into the seam's `CreatorSnapshot` (which
   asserts `rows_written = 0`) and passed up. The wrapper records
   `connector.gated_proof.success` with the safe metadata only.

The wrapper records its own audit row in addition to the seam's so
a forensic reviewer can distinguish operator-initiated proofs from
scheduled or hot-path runs.

---

## 3. What is still fake or dry-run

| Surface | Status |
|---|---|
| OnlyMonster real client | **Fake.** `FakeOnlyMonsterClient` — deterministic, synthetic, network-free, returns `synthetic: True` payload. |
| Production guard | Real. Production refuses the fake client unless explicitly enabled. |
| Connector gate | Real. Sprint 2's `is_connector_action_allowed` is the only chokepoint. |
| Approval lifecycle | Real. `app.services.connector_approvals` table-backed. |
| Consent lifecycle | Real. `app.services.consent` table-backed. |
| Kill switches | Real. Global / connector / organization / creator scopes. |
| Audit log | Real. `app.services.audit_log.record_audit` with PII redaction. |
| OnlyMonster credentials | Not used in this sprint. The fake doesn't authenticate. |
| Live network call | **None.** No `httpx`/`requests`/`aiohttp` import in any Sprint 8A file. |

---

## 4. What is required before real OnlyMonster live sync

In order:

1. **OFI branch merge.** The real `OnlyMonsterClient` lives on
   `feat/of-intelligence`. Until it is on `main`, only the fake
   client exists.
2. **Wire the real client at the seam call site.** Replace the
   `_FAKE_CLIENT_PATH` reference in
   `app.services.onlymonster_integration` and pass the real client
   through `resolve_onlymonster_client(real_client=...)`.
3. **Real OnlyMonster credential in the encrypted vault.** Stored
   via `app.services.settings_scope.set_secret_scoped` with
   `organization_id=<org>` once `MC_APP_SETTINGS_ORG_SCOPED=1` is
   on. Never as a plaintext env var, never in `app_settings.key`
   without scope.
4. **Owner-approved `connector_approvals` row** with
   `connector_type="onlymonster"`, `requested_action="creator_sync"`,
   per sandbox creator.
5. **Live `client_consents` row** with
   `consent_type="onlymonster_sync"` per sandbox creator.
6. **One `MC_ONLYMONSTER_GATED_SYNC_ENABLED=1` proof run**
   against the **fake** client first, with the real approval and
   consent rows in place. The expected outcome is
   `connector.gated_proof.success` with `used_fake_client=true`.
   This proves the chain holds before any real call.
7. **Switch to real client** for one sandbox creator, run a single
   read, confirm `connector.gated_proof.success` with
   `used_fake_client=false`, audit metadata is safe (no fan PII),
   and `rows_written=0`.
8. **24h re-check, then 7d re-check.** Same as the OnlyMonster
   readiness checklist Section D.

Until each step is documented as ✅ (in `docs/security/runs/`),
do not graduate from sandbox to a real creator account.

---

## 5. What this proves before direct OnlyFans

Sprint 8A is the **dry run for Sprint 8B**. It demonstrates that:

- The connector gate, the seam, and the audit pipeline all hold on
  a real integration-style path with a real env flag.
- The production guard against fake clients works.
- The audit chain has clear forensic joining (seam + proof rows
  reference the same creator).
- The result type cannot leak fan PII: `GatedProofResult` has no
  `payload` / `data` / `body` / `raw` / `messages` / `fans` field
  (verified by test).
- The OnlyMonster path exposes no write methods anywhere
  (verified by test).
- The Sprint 7 direct-OnlyFans policy module is untouched
  (verified by test).

If Sprint 8A is green, Sprint 8B can mirror this structure to
introduce a real OnlyFans **read-only** client behind the same
chain — with a separate env flag, a separate fake-client refusal,
and the Sprint 7 policy module enforcing read-only at the action
vocabulary layer.

---

## 6. Remaining gaps

| Gap | Owner | Notes |
|---|---|---|
| Real OnlyMonster client wiring | Post-OFI-merge | Wire at `app.services.onlymonster_integration._do_fetch` |
| Real OnlyFans read-only client | Sprint 8B | Behind the Sprint 7 disabled shell |
| `attach_denial_detail` applied to OM dependencies | incremental | Sprint 6 added the helper; per-dep upgrade is not required for Sprint 8A |
| Per-creator key partitioning | future | gap audit G7 |
| Unlabelled person-name redaction | future | gap audit G8 |
| `connector.session.challenged` audit category | Sprint 8B | Direct OF needs this; OnlyMonster does not |
| Notify channel for challenge events | Sprint 8B | Slack/Telegram bridge |
| Rate-limit live counting | Sprint 8B | Sprint 7 defined the policy; OM does not need it |

---

## 7. Recommended Sprint 8B

**Direct OnlyFans `mode="dry_run"` graduation.** Mirrors Sprint 8A's
structure on the OnlyFans direct path:

- Implement `OnlyFansReadOnlyClient` (real, isolated, read-only by
  construction). Methods named only after `READ_ACTIONS` from
  `onlyfans_direct_policy`. No write methods at all.
- Add `OnlyFansFakeReadOnlyClient` with the same invariants as
  `FakeOnlyMonsterClient`: refused in production unless an explicit
  drill flag is set.
- Extend `OnlyFansDirectConnector` with `mode="dry_run"` that
  routes through the connector gate, calls the fake client, and
  audits `connector.dry_run.pass`. (Sprint 7 already proved the
  fixture-only path; Sprint 8B is the next graduation: real client
  but only against a sandbox account.)
- Wire the `connector.session.challenged` audit category and a
  notify path for bot-detection signals.
- Add tests mirroring Sprint 8A: blocked / allowed / kill-switch /
  consent / fake-refused-in-production / no-writes.

Sprint 8B should NOT introduce production mode for OnlyFans. That
is Sprint 8C, after at least one sandbox creator has run cleanly
for 7 days.

---

## 8. Sign-off scope

This sprint:

- ✅ Wires the security gate end-to-end on the real OnlyMonster
  path with a typed fake client.
- ✅ Audits both block and allow paths, with forensic joining.
- ✅ Refuses the fake client in production unless an explicit drill
  flag is set.
- ✅ Surfaces gate readiness (env flag, approval, consent, kill
  switch, encryption key, real-client status) in the security
  admin UI.
- ✅ Adds 15 tests proving every refusal and the allowed path.
- ✅ Keeps Sprint 7 direct-OnlyFans policy untouched.

This sprint does **not** authorise:

- A real OnlyMonster sync against a real creator account.
- Any direct OnlyFans connector code.
- Any OnlyFans read or write.
- Any OnlyMonster write.
- A live network call from any Sprint 8A surface.
- Lifting any kill switch, approval, or consent gate.
