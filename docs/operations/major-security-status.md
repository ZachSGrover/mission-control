# Major Security — status (read-only)

Read-only snapshot taken during the parity-recovery sprint. **No source
files in any Major Security branch were modified.** This is a status
report only.

## Known canonical commits on origin/main

- `b43a562d` — "Add Major Security gates and sandbox transport
  foundation (#22)". This is the highest Major Security commit on main.
- `c8b764e7` — "fix(security): lock /api/v1/git/save to owner only
  (#27)". Owner-only gate on git_save closes the privilege-escalation
  the runtime parity audit flagged.

Both are merged into main.

## Implementation docs on main

Present under `docs/security/`:

- `audit-events-implementation.md`
- `breach-response-plan.md`
- `direct-connector-safety-checklist.md`
- `direct-onlyfans-readiness-checklist.md`
- `incident-drill-token-leak.md`
- `onlyfans-intelligence-security-plan.md`
- `security-gap-audit.md`
- `security-sprint-2-implementation.md`
- `security-sprint-3-implementation.md`
- `security-sprint-4-implementation.md`
- `security-sprint-5-implementation.md`
- `security-sprint-6-implementation.md`
- `security-sprint-7-direct-of-prep.md`
- `security-sprint-8a-onlymonster-gate.md`
- `security-sprint-8b-of-dryrun.md`
- `security-sprint-8c-of-sandbox.md`
- `security-sprint-8d-of-sandbox-reads.md`
- `security-sprint-8e-of-sandbox-transport.md`

So **Sprints 1–6** docs are on main and the corresponding code surfaces
were merged through PR #22 (transport sandbox foundation).

## What's still out of main (per local worktree presence)

The disk has a worktree at
`/Users/zachary/mission-control-of-intelligence` on
`feat/security-pra-audit-reconcile-with-coo-bot-access`. This is the
in-flight Major Security reconciliation branch. Without inspecting that
worktree's commits in this sprint (explicit hard rule: no modification,
read-only only), the safe summary is:

- **Sprints 7 + 8 (a/b/c/d/e)** — docs are on main but full code is
  carried on the reconciliation branch and has not been merged.
- The reconciliation branch needs to be turned into a clean PR off the
  current `origin/main` so PR #21's audit_events drift is squared with
  the COO bot access work that landed after.

## What's blocked on what

- COO connecting to a real OF account → blocked on Sprints 7+8 merging.
- OnlyMonster live ingestion → blocked on Sprint 8a's OM gate landing
  on main.
- OF dry-run from inside Mission Control → blocked on Sprint 8b.
- OF sandbox read flow → blocked on Sprint 8c+8d.
- Transport sandbox (the safe layer between any future OF connector and
  the rest of the stack) → foundation on main via PR #22; full impl in
  Sprint 8e doc.

## What was verified during this sprint

- `/api/v1/git/save` is owner-only (`require_owner` at
  `backend/app/api/git_save.py:73`). PR #27 closed the gap the runtime
  parity audit flagged. Confirmed read-only.
- No new security code was added by the parity-recovery sprint.

## Recommended next steps (not in scope for this PR)

1. Rebase
   `feat/security-pra-audit-reconcile-with-coo-bot-access` onto
   `origin/main` (which now contains PR #27).
2. Resolve the audit_events / PR #21 reconciliation conflicts.
3. Open a clean PR for Sprint 7 (direct OF prep).
4. Sequentially open PRs for Sprints 8a → 8e.

## Next Major Security branch (recommendation)

`feat/major-security-sprint-7-direct-of-prep-clean-rebase`

Off `origin/main` (post PR #27).
