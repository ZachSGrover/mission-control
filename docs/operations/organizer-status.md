# Organizer / channel mover — status

## Summary

**Not built.** A repo-wide search for `organizer`, `channel.mover`,
`drag.*drop.*channel`, `move.*channel`, `reorder.*sidebar`, and
`nav_order` returns zero hits in source code. The only match across
the entire tree is a comment in `TaskBoard.tsx` about FLIP reordering
of task cards — unrelated.

The runtime parity audit
(`/Users/zachary/Desktop/mission-control-runtime-parity-audit.md`,
section 11) confirmed the same gap: "The Organizer / channel mover
does not exist in this repo."

If anyone remembers an Organizer feature, it was either on a feature
branch that never landed, or part of an earlier upstream commit that
was removed in the `digital-os-total-audit` rebrand. It would need to
be **rebuilt**, not restored.

## Current sidebar order (hardcoded)

The order shown to operators today lives in
`frontend/src/components/organisms/DashboardSidebar.tsx` and is fixed
at compile time:

```
Chat            → Chat
Memory          → Projects, Memory, Calendar
Automation      → Hermes, Boards, Agents, Control, Workflows, Skills,
                  (Bots, Bot Builder — owner+operator), Logs
Business / Intelligence → OnlyFans Intelligence
System          → (Save — owner only), Guide, Settings,
                  Usage Tracker, (Users, Integrations, Security — owner)
```

There is no UI to reorder sections, no UI to hide a module, and no
persisted preference table for nav state.

## Why it was deferred from this sprint

Organizer v1 has the right components on paper:

1. New table — `ui_navigation_preferences` (owner-scope, single row
   for the organization).
2. New backend module — `app/api/ui_nav.py` with GET/PUT (require_owner).
3. New service — `app/services/ui_nav.py` with default order + merge.
4. New migration.
5. New frontend page — `/settings/organizer`.
6. Refactor of `DashboardSidebar.tsx` to consume the preference rather
   than the hardcoded order.
7. Role-visibility tests so Organizer cannot expose owner-only routes
   to non-owners.

That is a real new feature, not a recovery. The hard rule for this
sprint is "not a new feature sprint unless a missing built feature
needs to be restored or safely rebuilt." Organizer would also intersect
the active Build Request Approvals session's surface area, since both
touch the System nav block.

## What this sprint DID do

- Added owner-only gating on the **Save** button so operators don't
  see (and accidentally click into) a 403 from `/api/v1/git/save`.
- Documented the gap here and in `docs/operations/product-map.md`.
- Confirmed Usage Tracker is already in the right place (under System,
  between Settings and the owner-only group).

## Next Organizer branch (when this sprint closes)

`feat/organizer-v1`

Off `origin/main` after this sprint's PR lands. Scope:

1. Owner-only `/settings/organizer` page.
2. Drag-and-drop reorder of nav sections (sortable list, not full
   modular grid — keep v1 small).
3. Per-section hide/show toggles.
4. Server-side persist via `ui_navigation_preferences`.
5. Backend role gates: `require_owner` for write; everyone reads.
6. Audit events: `organizer.update`, `nav_order.update`,
   `role_visibility.update`.
7. Tests: owner can save, operator cannot, role-preview still works,
   default order renders when no preference exists, Organizer cannot
   expose owner-only routes to non-owner roles.

Hard safety: backend role gates remain the source of truth.
Frontend visibility is display logic only. Role Preview must
continue to not grant real privileges.
