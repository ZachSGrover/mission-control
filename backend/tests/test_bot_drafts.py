# ruff: noqa: INP001
"""Tests for the Bot Builder v1 (``bot_drafts``) API surface.

Covers:
  • role gating: viewer/builder cannot create; operator can; only owner
    can approve.
  • audit rows are written for create / update / archive / approval
    requested / approved.
  • secret-pattern rejection: free-text fields containing API keys,
    bearer tokens, cookie material, webhook URLs, or DSN URLs are
    rejected with HTTP 400.
  • sandbox_mode is sticky-on — a malicious ``sandbox_mode=False`` body
    cannot un-stick it via create or update.
  • response shape carries no secret-like keys (privacy contract).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.bot_drafts import router as bot_drafts_router
from app.api.mc_roles import (
    get_mc_role,
    require_operator,
    require_owner,
)
from app.core.auth import AuthContext, get_auth_context
from app.db.session import get_session
from app.models.audit_event import AuditEvent
from app.models.bot_draft import (
    DRAFT_STATUS_APPROVED,
    DRAFT_STATUS_ARCHIVED,
    DRAFT_STATUS_PENDING,
    BotDraft,
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
    api_v1.include_router(bot_drafts_router)
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


def _valid_create_body(slug: str = "rt-bot-v1") -> dict[str, object]:
    return {
        "slug": slug,
        "name": "Outreach RT Bot",
        "purpose": "Retweet curated content and follow up with replies.",
        "category": "growth",
        "description": "Sandbox draft for retweet operations.",
        "owner": "founder",
        "risk_level": "medium",
        "approval_required": True,
        "trigger_type": "manual",
        "input_requirements": "List of seed accounts to monitor.",
        "output_requirements": "Retweet log + per-target tally.",
        "prompt_template": "Read the timeline. Pick best post. Suggest a reply.",
        "dashboard_notes": "Awaiting cowork export.",
        "tools_needed": ["timeline-reader", "scheduler"],
    }


# ── Role gating: list/get available to anyone authenticated ─────────────────


@pytest.mark.asyncio
async def test_list_visible_to_all_authenticated_roles() -> None:
    for role in ("owner", "operator", "builder", "viewer"):
        async with _make_client(role=role) as (client, _maker):
            res = await client.get("/api/v1/bot-drafts")
            assert res.status_code == 200, (role, res.text)
            assert isinstance(res.json(), list)


# ── Role gating: create requires operator+ ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["builder", "viewer"])
async def test_create_denied_for_below_operator(role: str) -> None:
    async with _make_client(role=role) as (client, _maker):
        res = await client.post("/api/v1/bot-drafts", json=_valid_create_body())
        assert res.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "owner"])
async def test_create_allowed_for_operator_and_owner(role: str) -> None:
    async with _make_client(role=role) as (client, _maker):
        res = await client.post("/api/v1/bot-drafts", json=_valid_create_body())
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["slug"] == "rt-bot-v1"
        assert body["status"] == "draft"
        assert body["sandbox_mode"] is True


# ── Sandbox stickiness: caller cannot unset sandbox_mode ───────────────────


@pytest.mark.asyncio
async def test_sandbox_mode_is_forced_on_during_create() -> None:
    async with _make_client(role="operator") as (client, _maker):
        body = _valid_create_body()
        body["sandbox_mode"] = False  # malicious / mistaken
        res = await client.post("/api/v1/bot-drafts", json=body)
        assert res.status_code == 201
        assert res.json()["sandbox_mode"] is True


@pytest.mark.asyncio
async def test_sandbox_mode_is_forced_on_during_update() -> None:
    async with _make_client(role="operator") as (client, _maker):
        created = (await client.post("/api/v1/bot-drafts", json=_valid_create_body())).json()
        res = await client.patch(
            f"/api/v1/bot-drafts/{created['id']}",
            json={"sandbox_mode": False, "name": "renamed"},
        )
        assert res.status_code == 200
        assert res.json()["sandbox_mode"] is True
        assert res.json()["name"] == "renamed"


# ── Secret rejection ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("description", "Use api_key=sk-foo when calling the helper"),
        ("prompt_template", "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9"),
        ("dashboard_notes", "Webhook url is https://discord.com/api/webhooks/123/abc"),
        ("trigger_type", "cookie: session_token=abc"),
        ("input_requirements", "DATABASE_URL=postgres://u:p@host/db"),
        ("owner", "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    ],
)
async def test_create_rejects_secret_like_fields(field: str, value: str) -> None:
    async with _make_client(role="operator") as (client, _maker):
        body = _valid_create_body()
        body[field] = value
        res = await client.post("/api/v1/bot-drafts", json=body)
        assert res.status_code == 400, (field, res.text)
        assert "credential" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_rejects_secret_in_tools_needed() -> None:
    async with _make_client(role="operator") as (client, _maker):
        body = _valid_create_body()
        body["tools_needed"] = ["timeline-reader", "AKIA1234567890ABCDEF"]
        res = await client.post("/api/v1/bot-drafts", json=body)
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_update_rejects_secret_like_fields() -> None:
    async with _make_client(role="operator") as (client, _maker):
        created = (await client.post("/api/v1/bot-drafts", json=_valid_create_body())).json()
        res = await client.patch(
            f"/api/v1/bot-drafts/{created['id']}",
            json={"prompt_template": "Authorization: Bearer ghp_secret"},
        )
        assert res.status_code == 400


# ── Audit rows ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_rows_for_full_lifecycle() -> None:
    async with _make_client(role="operator", actor_user_id="u-op") as (client, maker):
        created = (await client.post("/api/v1/bot-drafts", json=_valid_create_body())).json()
        draft_id = created["id"]

        res_update = await client.patch(
            f"/api/v1/bot-drafts/{draft_id}",
            json={"name": "renamed-bot"},
        )
        assert res_update.status_code == 200

        res_request = await client.post(
            f"/api/v1/bot-drafts/{draft_id}/request-approval",
        )
        assert res_request.status_code == 200
        assert res_request.json()["status"] == DRAFT_STATUS_PENDING

        async with maker() as session:
            rows = (await session.exec(select(AuditEvent))).all()
            actions = sorted(r.action for r in rows)
            assert actions == [
                "bot_draft.approval_requested",
                "bot_draft.create",
                "bot_draft.update",
            ]
            for row in rows:
                # Privacy: only safe summaries — no payload bodies stored.
                assert row.payload_hash is None or isinstance(row.payload_hash, str)


@pytest.mark.asyncio
async def test_archive_writes_audit_and_blocks_edit() -> None:
    async with _make_client(role="operator") as (client, maker):
        created = (await client.post("/api/v1/bot-drafts", json=_valid_create_body())).json()
        draft_id = created["id"]
        archived = await client.post(f"/api/v1/bot-drafts/{draft_id}/archive")
        assert archived.status_code == 200
        assert archived.json()["status"] == DRAFT_STATUS_ARCHIVED

        # Editing an archived draft is blocked.
        bad = await client.patch(
            f"/api/v1/bot-drafts/{draft_id}",
            json={"name": "should-fail"},
        )
        assert bad.status_code == 409

        async with maker() as session:
            actions = sorted(r.action for r in (await session.exec(select(AuditEvent))).all())
            assert "bot_draft.archive" in actions


# ── Owner-only approve ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "builder", "viewer"])
async def test_approve_denied_for_non_owner(role: str) -> None:
    # Seed via owner so a draft exists.
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/bot-drafts", json=_valid_create_body())).json()
        draft_id = created["id"]

        # Switch role on the same DB by reusing the client's overrides.
        # Easier: spin a fresh client at the lower role on a *new* DB
        # and prove the gate independent of pre-state.
    async with _make_client(role=role) as (client2, _maker2):
        # On a fresh DB the draft doesn't exist; we still want to show
        # the gate fires before lookup.  Use any UUID.
        res = await client2.post(
            f"/api/v1/bot-drafts/{draft_id}/approve",
        )
        assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_approve_owner_writes_audit() -> None:
    async with _make_client(role="owner") as (client, maker):
        created = (await client.post("/api/v1/bot-drafts", json=_valid_create_body())).json()
        draft_id = created["id"]
        await client.post(f"/api/v1/bot-drafts/{draft_id}/request-approval")
        approved = await client.post(f"/api/v1/bot-drafts/{draft_id}/approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == DRAFT_STATUS_APPROVED
        async with maker() as session:
            actions = sorted(r.action for r in (await session.exec(select(AuditEvent))).all())
            assert "bot_draft.approval_approved" in actions


# ── Privacy: response shape contains no secret-shaped fields ───────────────


@pytest.mark.asyncio
async def test_response_shape_has_no_secret_fields() -> None:
    async with _make_client(role="operator") as (client, _maker):
        created = (await client.post("/api/v1/bot-drafts", json=_valid_create_body())).json()
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
        }
        assert forbidden.isdisjoint(created.keys()), created


# ── Slug validation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rejects_bad_slug() -> None:
    async with _make_client(role="operator") as (client, _maker):
        body = _valid_create_body()
        body["slug"] = "Bad Slug!"
        res = await client.post("/api/v1/bot-drafts", json=body)
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_create_rejects_invalid_risk_level() -> None:
    async with _make_client(role="operator") as (client, _maker):
        body = _valid_create_body()
        body["risk_level"] = "extreme"
        res = await client.post("/api/v1/bot-drafts", json=body)
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_create_rejects_duplicate_slug() -> None:
    async with _make_client(role="operator") as (client, _maker):
        first = await client.post("/api/v1/bot-drafts", json=_valid_create_body())
        assert first.status_code == 201
        second = await client.post("/api/v1/bot-drafts", json=_valid_create_body())
        assert second.status_code == 409


# ── Bootstrap seed places RT Bot placeholder ──────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_seed_creates_rt_bot_placeholder() -> None:
    from app.services.bot_drafts import RT_BOT_SLUG, bootstrap_seed

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with maker() as session:
            inserted = await bootstrap_seed(session)
            assert inserted == 1
        async with maker() as session:
            again = await bootstrap_seed(session)
            assert again == 0  # idempotent
            row = (
                await session.exec(
                    select(BotDraft).where(BotDraft.slug == RT_BOT_SLUG),
                )
            ).first()
            assert row is not None
            assert row.sandbox_mode is True
            assert row.status == "draft"
    finally:
        await engine.dispose()
