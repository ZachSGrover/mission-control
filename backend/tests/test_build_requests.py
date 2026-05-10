# ruff: noqa: INP001
"""Tests for the Build Request Approvals API.

Covers the 20 backend test cases from the sprint spec:

  1. owner can create build request
  2. operator can create build request
  3. viewer cannot create build request
  4. operator can submit own request
  5. operator cannot approve
  6. operator cannot reject
  7. owner can approve
  8. owner can reject
  9. owner can request changes
 10. operator can edit own draft
 11. operator cannot edit approved request
 12. build request rejects obvious secrets
 13. no git command is run
 14. no gh command is run
 15. audit row is written for create
 16. audit row is written for submit
 17. audit row is written for approve
 18. audit row is written for reject
 19. list endpoint respects role visibility
 20. no raw secret values in API responses

Plus a sweep of safety / transition guards.
"""

from __future__ import annotations

import contextlib
import subprocess
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.build_requests import router as build_requests_router
from app.api.mc_roles import (
    get_mc_role,
    require_operator,
    require_owner,
)
from app.core.auth import AuthContext, get_auth_context
from app.db.session import get_session
from app.models.audit_event import AuditEvent
from app.models.build_request import (
    STATUS_APPROVED,
    STATUS_BUILDING,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_NEEDS_CHANGES,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    BuildRequest,
)
from app.models.mc_role import ROLE_RANK


@contextlib.asynccontextmanager
async def _make_client(
    *,
    role: str = "owner",
    actor_user_id: str = "u-test",
    actor_email: str | None = "actor@test.local",
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(build_requests_router)
    app.include_router(api_v1)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    async def _override_auth() -> AuthContext:
        from app.models.users import User

        return AuthContext(
            actor_type="user",
            user=User(
                clerk_user_id=actor_user_id,
                email=actor_email,
                name="Test Actor",
            ),
        )

    async def _override_role() -> str:
        return role

    async def _override_owner_dep() -> str:
        if role != "owner":
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner only")
        return "owner"

    async def _override_operator_dep() -> str:
        if ROLE_RANK.get(role, 0) < ROLE_RANK["operator"]:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator only")
        return role

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_auth_context] = _override_auth
    app.dependency_overrides[get_mc_role] = _override_role
    app.dependency_overrides[require_owner] = _override_owner_dep
    app.dependency_overrides[require_operator] = _override_operator_dep

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, maker
    finally:
        await engine.dispose()


def _valid_create_body(slug: str = "build-rt-bot-v1") -> dict[str, Any]:
    return {
        "title": "Build RT Bot v1",
        "slug": slug,
        "request_type": "bot_build",
        "summary": "Stand up a sandbox-only RT Bot draft for review.",
        "description": "Detailed spec lives in the related bot draft.",
        "business_reason": "Unblocks growth retweet workflow.",
        "priority": "normal",
        "risk_level": "medium",
        "target_area": "growth/rt-bot",
        "external_actions_requested": False,
        "secrets_required": False,
        "platforms_requested": ["X"],
        "acceptance_criteria": [
            "Draft visible in bot builder",
            "No live X connection",
        ],
    }


# ── 1, 2, 3 — create permissions ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_can_create_build_request() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.post("/api/v1/build-requests", json=_valid_create_body())
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["status"] == "draft"
        assert body["safe_mode_required"] is True
        assert body["requested_by_role"] == "owner"


@pytest.mark.asyncio
async def test_operator_can_create_build_request() -> None:
    async with _make_client(role="operator") as (client, _maker):
        res = await client.post("/api/v1/build-requests", json=_valid_create_body())
        assert res.status_code == 201, res.text
        assert res.json()["requested_by_role"] == "operator"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["builder", "viewer"])
async def test_viewer_or_builder_cannot_create_build_request(role: str) -> None:
    async with _make_client(role=role) as (client, _maker):
        res = await client.post("/api/v1/build-requests", json=_valid_create_body())
        assert res.status_code == 403


# ── 4 — operator can submit their own ───────────────────────────────────────


@pytest.mark.asyncio
async def test_operator_can_submit_own_request() -> None:
    async with _make_client(role="operator", actor_user_id="u-op") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        res = await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        assert res.status_code == 200, res.text
        assert res.json()["status"] == STATUS_SUBMITTED


# ── 5, 6 — operator cannot approve / reject ─────────────────────────────────


@pytest.mark.asyncio
async def test_operator_cannot_approve() -> None:
    async with _make_client(role="operator") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        res = await client.post(f"/api/v1/build-requests/{created['id']}/approve", json={})
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_operator_cannot_reject() -> None:
    async with _make_client(role="operator") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        res = await client.post(
            f"/api/v1/build-requests/{created['id']}/reject",
            json={"reason": "out of scope"},
        )
        assert res.status_code == 403


# ── 7, 8, 9 — owner can approve / reject / request_changes ──────────────────


@pytest.mark.asyncio
async def test_owner_can_approve() -> None:
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        res = await client.post(
            f"/api/v1/build-requests/{created['id']}/approve",
            json={"notes": "looks good"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == STATUS_APPROVED
        assert body["approved_by_user_id"]
        assert body["approved_at"]


@pytest.mark.asyncio
async def test_owner_can_reject() -> None:
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        res = await client.post(
            f"/api/v1/build-requests/{created['id']}/reject",
            json={"reason": "duplicates existing work"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == STATUS_REJECTED
        assert body["rejection_reason"] == "duplicates existing work"


@pytest.mark.asyncio
async def test_owner_can_request_changes() -> None:
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        res = await client.post(
            f"/api/v1/build-requests/{created['id']}/request-changes",
            json={"notes": "Please clarify acceptance criteria."},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == STATUS_NEEDS_CHANGES
        assert body["owner_notes"] == "Please clarify acceptance criteria."


# ── 10, 11 — operator edit gating ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_operator_can_edit_own_draft() -> None:
    async with _make_client(role="operator", actor_user_id="u-op") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        res = await client.patch(
            f"/api/v1/build-requests/{created['id']}",
            json={"summary": "updated summary"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["summary"] == "updated summary"


@pytest.mark.asyncio
async def test_operator_cannot_edit_approved_request() -> None:
    # Owner creates + approves so the row exists in approved status.
    async with _make_client(role="owner", actor_user_id="u-owner") as (client, maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        await client.post(
            f"/api/v1/build-requests/{created['id']}/approve",
            json={},
        )
        # Confirm row state via DB before the operator attempt.
        async with maker() as session:
            row = (await session.exec(select(BuildRequest))).first()
            assert row is not None and row.status == STATUS_APPROVED

        # Same engine/session, switched role: rebuild app overrides as operator.
        from fastapi import HTTPException, status as st

        async def _operator_role() -> str:
            return "operator"

        async def _owner_dep_block() -> str:
            raise HTTPException(status_code=st.HTTP_403_FORBIDDEN, detail="Owner only")

        async def _operator_dep() -> str:
            return "operator"

        client._transport.app.dependency_overrides[get_mc_role] = _operator_role  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[require_owner] = _owner_dep_block  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[require_operator] = _operator_dep  # type: ignore[attr-defined]

        # Operator is NOT the author and the row is in approved (terminal-edit)
        # state. PATCH must be rejected — either 403 (not author) or 409
        # (status not editable). Both are acceptable; we check for either.
        res = await client.patch(
            f"/api/v1/build-requests/{created['id']}",
            json={"summary": "should not change"},
        )
        assert res.status_code in (403, 409), res.text


@pytest.mark.asyncio
async def test_operator_cannot_edit_someone_elses_draft() -> None:
    # Owner creates the row.
    async with _make_client(role="owner", actor_user_id="u-owner") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()

        async def _operator_role() -> str:
            return "operator"

        async def _operator_auth() -> AuthContext:
            from app.models.users import User

            return AuthContext(
                actor_type="user",
                user=User(
                    clerk_user_id="u-other-op",
                    email="other@test.local",
                    name="Other",
                ),
            )

        async def _operator_dep() -> str:
            return "operator"

        client._transport.app.dependency_overrides[get_mc_role] = _operator_role  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[get_auth_context] = _operator_auth  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[require_operator] = _operator_dep  # type: ignore[attr-defined]

        # The operator is NOT the author. Visibility filter should hide
        # the row entirely (404), or PATCH should be 403/404.
        res = await client.patch(
            f"/api/v1/build-requests/{created['id']}",
            json={"summary": "no"},
        )
        assert res.status_code in (403, 404), res.text


# ── 12 — secret rejection ──────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("description", "Use api_key=sk-foo when calling the helper"),
        ("business_reason", "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9"),
        (
            "target_area",
            "Webhook url is https://discord.com/api/webhooks/123/abc",
        ),
        ("requested_branch_name", "sk_live_secret_branch"),
    ],
)
async def test_create_rejects_secret_like_fields(field: str, value: str) -> None:
    async with _make_client(role="operator") as (client, _maker):
        body = _valid_create_body()
        body[field] = value
        res = await client.post("/api/v1/build-requests", json=body)
        assert res.status_code == 400, (field, res.text)
        assert "credential" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_rejects_secret_in_platforms_or_acs() -> None:
    async with _make_client(role="operator") as (client, _maker):
        body = _valid_create_body()
        body["platforms_requested"] = ["X", "AKIA1234567890ABCDEF"]
        res = await client.post("/api/v1/build-requests", json=body)
        assert res.status_code == 400


# ── 13, 14 — no git or gh command is run ────────────────────────────────────


@pytest.mark.asyncio
async def test_no_git_or_gh_command_is_run_through_lifecycle() -> None:
    """Patch subprocess.* so any git/gh invocation throws.

    Exercising every mutating endpoint must NOT shell out.  v1 is intake
    + approval only; branches and PRs are out of scope.
    """
    forbidden_executables = {"git", "gh"}

    def _guard(args: Any, *posargs: Any, **kwargs: Any) -> None:
        # args is either a list or a string; first token is the binary.
        cmd = args[0] if isinstance(args, (list, tuple)) and args else args
        if isinstance(cmd, str):
            tail = cmd.split("/")[-1].split()[0]
            assert tail not in forbidden_executables, f"forbidden subprocess: {cmd}"
        raise AssertionError(f"unexpected subprocess call: {args!r}")

    with (
        patch.object(subprocess, "run", side_effect=_guard),
        patch.object(subprocess, "Popen", side_effect=_guard),
        patch.object(subprocess, "call", side_effect=_guard),
        patch.object(subprocess, "check_call", side_effect=_guard),
        patch.object(subprocess, "check_output", side_effect=_guard),
    ):
        async with _make_client(role="owner") as (client, _maker):
            created = (
                await client.post("/api/v1/build-requests", json=_valid_create_body())
            ).json()
            req_id = created["id"]

            assert (
                await client.patch(
                    f"/api/v1/build-requests/{req_id}",
                    json={"summary": "edit"},
                )
            ).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/build-requests/{req_id}/submit",
                )
            ).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/build-requests/{req_id}/request-changes",
                    json={"notes": "tweak this"},
                )
            ).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/build-requests/{req_id}/submit",
                )
            ).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/build-requests/{req_id}/approve",
                    json={},
                )
            ).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/build-requests/{req_id}/mark-building",
                    json={},
                )
            ).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/build-requests/{req_id}/mark-completed",
                    json={},
                )
            ).status_code == 200
            list_res = await client.get("/api/v1/build-requests")
            assert list_res.status_code == 200


# ── 15-18 — audit rows ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_row_for_create() -> None:
    async with _make_client(role="operator", actor_user_id="u-op") as (client, maker):
        await client.post("/api/v1/build-requests", json=_valid_create_body())
        async with maker() as session:
            actions = sorted(r.action for r in (await session.exec(select(AuditEvent))).all())
            assert "build_request.create" in actions


@pytest.mark.asyncio
async def test_audit_row_for_submit() -> None:
    async with _make_client(role="operator", actor_user_id="u-op") as (client, maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        async with maker() as session:
            actions = sorted(r.action for r in (await session.exec(select(AuditEvent))).all())
            assert "build_request.submit" in actions


@pytest.mark.asyncio
async def test_audit_row_for_approve() -> None:
    async with _make_client(role="owner") as (client, maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        await client.post(
            f"/api/v1/build-requests/{created['id']}/approve",
            json={},
        )
        async with maker() as session:
            actions = sorted(r.action for r in (await session.exec(select(AuditEvent))).all())
            assert "build_request.approve" in actions


@pytest.mark.asyncio
async def test_audit_row_for_reject() -> None:
    async with _make_client(role="owner") as (client, maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        await client.post(
            f"/api/v1/build-requests/{created['id']}/reject",
            json={"reason": "no"},
        )
        async with maker() as session:
            actions = sorted(r.action for r in (await session.exec(select(AuditEvent))).all())
            assert "build_request.reject" in actions


# ── 19 — list endpoint role visibility ─────────────────────────────────────


@pytest.mark.asyncio
async def test_list_endpoint_respects_role_visibility() -> None:
    """Owner sees all rows; an operator sees only rows they authored."""
    async with _make_client(role="owner", actor_user_id="u-owner") as (client, _maker):
        # Owner creates row A.
        owner_body = _valid_create_body("br-owner")
        owner_body["title"] = "Owner row"
        res_a = await client.post("/api/v1/build-requests", json=owner_body)
        assert res_a.status_code == 201

        # Switch to operator u-op-b and create row B.
        async def _op_role() -> str:
            return "operator"

        async def _op_auth() -> AuthContext:
            from app.models.users import User

            return AuthContext(
                actor_type="user",
                user=User(
                    clerk_user_id="u-op-b",
                    email="opb@test.local",
                    name="Op B",
                ),
            )

        async def _op_dep() -> str:
            return "operator"

        async def _owner_dep_block() -> str:
            from fastapi import HTTPException, status as st

            raise HTTPException(status_code=st.HTTP_403_FORBIDDEN, detail="Owner only")

        client._transport.app.dependency_overrides[get_mc_role] = _op_role  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[get_auth_context] = _op_auth  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[require_operator] = _op_dep  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[require_owner] = _owner_dep_block  # type: ignore[attr-defined]

        op_body = _valid_create_body("br-op")
        op_body["title"] = "Op row"
        res_b = await client.post("/api/v1/build-requests", json=op_body)
        assert res_b.status_code == 201

        # Operator list — should only see their own row.
        list_op = await client.get("/api/v1/build-requests")
        assert list_op.status_code == 200
        op_titles = {r["title"] for r in list_op.json()}
        assert op_titles == {"Op row"}, op_titles


@pytest.mark.asyncio
async def test_owner_list_sees_all_rows() -> None:
    async with _make_client(role="owner", actor_user_id="u-owner") as (client, _maker):
        # Owner creates row.
        await client.post("/api/v1/build-requests", json=_valid_create_body("br-1"))

        # Swap to operator, create another.
        async def _op_role() -> str:
            return "operator"

        async def _op_auth() -> AuthContext:
            from app.models.users import User

            return AuthContext(
                actor_type="user",
                user=User(
                    clerk_user_id="u-op-c",
                    email="opc@test.local",
                    name="Op C",
                ),
            )

        async def _op_dep() -> str:
            return "operator"

        client._transport.app.dependency_overrides[get_mc_role] = _op_role  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[get_auth_context] = _op_auth  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[require_operator] = _op_dep  # type: ignore[attr-defined]
        body2 = _valid_create_body("br-2")
        body2["title"] = "Op-authored"
        await client.post("/api/v1/build-requests", json=body2)

        # Swap back to owner.
        async def _owner_role() -> str:
            return "owner"

        async def _owner_auth() -> AuthContext:
            from app.models.users import User

            return AuthContext(
                actor_type="user",
                user=User(
                    clerk_user_id="u-owner",
                    email="owner@test.local",
                    name="Owner",
                ),
            )

        async def _owner_ok() -> str:
            return "owner"

        client._transport.app.dependency_overrides[get_mc_role] = _owner_role  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[get_auth_context] = _owner_auth  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[require_owner] = _owner_ok  # type: ignore[attr-defined]
        client._transport.app.dependency_overrides[require_operator] = _owner_ok  # type: ignore[attr-defined]

        list_owner = await client.get("/api/v1/build-requests")
        assert list_owner.status_code == 200
        slugs = {r["slug"] for r in list_owner.json()}
        assert {"br-1", "br-2"}.issubset(slugs)


# ── 20 — response shape carries no secret-shaped fields ────────────────────


@pytest.mark.asyncio
async def test_response_shape_has_no_secret_fields() -> None:
    async with _make_client(role="operator") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        forbidden = {
            "token",
            "secret",
            "webhook_url",
            "api_key",
            "credential",
            "password",
            "preview",
            "message_body",
            "cookie",
            "session_token",
        }
        assert forbidden.isdisjoint(created.keys()), created


# ── Extra safety / transition guards ───────────────────────────────────────


@pytest.mark.asyncio
async def test_safe_mode_required_is_sticky_on_create_and_update() -> None:
    async with _make_client(role="operator") as (client, _maker):
        body = _valid_create_body()
        body["safe_mode_required"] = False  # malicious / mistaken
        # Request body model doesn't accept the field — ignored. But
        # we want to assert the row comes back True regardless.
        res = await client.post("/api/v1/build-requests", json=body)
        assert res.status_code == 201
        created = res.json()
        assert created["safe_mode_required"] is True

        upd = await client.patch(
            f"/api/v1/build-requests/{created['id']}",
            json={"safe_mode_required": False, "summary": "tweak"},
        )
        assert upd.status_code == 200
        assert upd.json()["safe_mode_required"] is True


@pytest.mark.asyncio
async def test_owner_cancel_then_no_further_mutation() -> None:
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        cancelled = await client.post(f"/api/v1/build-requests/{created['id']}/cancel", json={})
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == STATUS_CANCELLED

        # Submit on cancelled row must conflict.
        res = await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        assert res.status_code == 409


@pytest.mark.asyncio
async def test_owner_full_lifecycle_to_completed() -> None:
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        assert (
            await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        ).status_code == 200
        assert (
            await client.post(f"/api/v1/build-requests/{created['id']}/approve", json={})
        ).status_code == 200
        building = await client.post(
            f"/api/v1/build-requests/{created['id']}/mark-building", json={}
        )
        assert building.status_code == 200
        assert building.json()["status"] == STATUS_BUILDING
        completed = await client.post(
            f"/api/v1/build-requests/{created['id']}/mark-completed", json={}
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == STATUS_COMPLETED


@pytest.mark.asyncio
async def test_status_filter_works() -> None:
    async with _make_client(role="owner") as (client, _maker):
        a = (await client.post("/api/v1/build-requests", json=_valid_create_body("br-a"))).json()
        await client.post("/api/v1/build-requests", json=_valid_create_body("br-b"))
        await client.post(f"/api/v1/build-requests/{a['id']}/submit")

        submitted = await client.get("/api/v1/build-requests", params={"status": "submitted"})
        assert submitted.status_code == 200
        slugs = {r["slug"] for r in submitted.json()}
        assert slugs == {"br-a"}

        drafts = await client.get("/api/v1/build-requests", params={"status": "draft"})
        assert {r["slug"] for r in drafts.json()} == {"br-b"}


@pytest.mark.asyncio
async def test_invalid_request_type_rejected() -> None:
    async with _make_client(role="operator") as (client, _maker):
        body = _valid_create_body()
        body["request_type"] = "rocket-launch"
        res = await client.post("/api/v1/build-requests", json=body)
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_duplicate_slug_conflict() -> None:
    async with _make_client(role="operator") as (client, _maker):
        first = await client.post("/api/v1/build-requests", json=_valid_create_body())
        assert first.status_code == 201
        second = await client.post("/api/v1/build-requests", json=_valid_create_body())
        assert second.status_code == 409


@pytest.mark.asyncio
async def test_reject_requires_reason() -> None:
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/build-requests", json=_valid_create_body())).json()
        await client.post(f"/api/v1/build-requests/{created['id']}/submit")
        # Empty reason rejected.
        res = await client.post(
            f"/api/v1/build-requests/{created['id']}/reject",
            json={"reason": "   "},
        )
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_external_actions_and_secrets_flags_persist() -> None:
    """Operators may flag risky requests; the row must record both flags."""
    async with _make_client(role="operator") as (client, _maker):
        body = _valid_create_body()
        body["external_actions_requested"] = True
        body["secrets_required"] = True
        body["risk_level"] = "high"
        res = await client.post("/api/v1/build-requests", json=body)
        assert res.status_code == 201, res.text
        out = res.json()
        assert out["external_actions_requested"] is True
        assert out["secrets_required"] is True
        assert out["risk_level"] == "high"
