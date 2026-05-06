# ruff: noqa: INP001
"""Unit tests for the QC Discord publisher.

Network is fully mocked.  Tests cover the publish contract — kill switch,
webhook resolution, retry/backoff, 429 honor, 4xx/5xx handling, privacy
guard short-circuit, and the no-webhook-url-in-logs invariant.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

import httpx
import pytest

from app.services.of_intelligence.qc import publisher
from app.services.of_intelligence.qc.publisher import PublishResult, publish

WEBHOOK_URL = "https://discord.com/api/webhooks/123456789/abcDEF_ghi-jkl"
SAFE_MESSAGE = "🟥 [QC] luna_main may have lost access\nAccount: luna_main\nAction: re-auth"


# ── Fakes ────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._json_body = json_body

    def json(self) -> Any:
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient.

    Holds a queue of responses.  Records every call (URL + body).  Optionally
    raises a queued exception instead of returning a response.
    """

    def __init__(
        self,
        responses: Iterable[_FakeResponse | BaseException],
        *,
        timeout: float | None = None,
    ) -> None:
        self._queue = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.timeout = timeout

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any] | None = None) -> _FakeResponse:
        self.calls.append((url, json or {}))
        if not self._queue:
            raise AssertionError("FakeAsyncClient ran out of queued responses")
        nxt = self._queue.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    responses: Iterable[_FakeResponse | BaseException],
) -> _FakeAsyncClient:
    """Install a single _FakeAsyncClient that the publisher will use.

    Returns the fake so the test can inspect ``calls`` afterward.
    """
    fake = _FakeAsyncClient(responses)

    def _factory(*_args: object, **_kwargs: object) -> _FakeAsyncClient:
        return fake

    monkeypatch.setattr(publisher.httpx, "AsyncClient", _factory)
    return fake


def _enable(monkeypatch: pytest.MonkeyPatch, *, webhook: str | None = WEBHOOK_URL) -> None:
    monkeypatch.setenv("MC_OF_QC_DISCORD_ENABLED", "1")
    if webhook is None:
        monkeypatch.delenv("MC_OF_QC_DISCORD_WEBHOOK_URL", raising=False)
    else:
        monkeypatch.setenv("MC_OF_QC_DISCORD_WEBHOOK_URL", webhook)


# Eliminate real backoff sleep so tests run instantly.
@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fast(_seconds: float) -> None:
        return None

    monkeypatch.setattr(publisher.asyncio, "sleep", _fast)


# Stub the DB resolvers for env-only tests.  Resolver-specific behavior is
# tested separately below — the rest of the suite needs deterministic
# env-driven resolution without spinning up SQLAlchemy.
@pytest.fixture(autouse=True)
def _stub_db_state(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty_webhook() -> str:
        return ""

    async def _no_db_toggle() -> bool | None:
        return None  # falls through to env

    monkeypatch.setattr(publisher, "_read_db_webhook", _empty_webhook)
    monkeypatch.setattr(publisher, "_read_db_enabled", _no_db_toggle)


# ── Kill switch + config ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_returns_disabled_when_kill_switch_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MC_OF_QC_DISCORD_ENABLED", raising=False)
    monkeypatch.setenv("MC_OF_QC_DISCORD_WEBHOOK_URL", WEBHOOK_URL)

    fake = _patch_client(monkeypatch, [_FakeResponse(204)])
    result = await publish(SAFE_MESSAGE, code="x", severity="critical")

    assert result == PublishResult(
        ok=False, status=None, attempts=0, reason="disabled", elapsed_ms=result.elapsed_ms
    )
    assert fake.calls == []  # never hit the network


@pytest.mark.asyncio
async def test_publish_returns_no_webhook_when_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, webhook=None)
    fake = _patch_client(monkeypatch, [_FakeResponse(204)])

    result = await publish(SAFE_MESSAGE, code="x", severity="critical")

    assert result.ok is False
    assert result.reason == "no_webhook"
    assert fake.calls == []


# ── Happy path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_204_returns_ok_in_one_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    fake = _patch_client(monkeypatch, [_FakeResponse(204)])

    result = await publish(SAFE_MESSAGE, code="account_blocked", severity="critical")

    assert result.ok is True
    assert result.status == 204
    assert result.attempts == 1
    assert result.reason == "ok"
    assert len(fake.calls) == 1
    url, body = fake.calls[0]
    assert url == WEBHOOK_URL
    assert body == {"content": SAFE_MESSAGE}


# ── 429 rate limiting ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_429_then_204_succeeds_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    fake = _patch_client(
        monkeypatch,
        [
            _FakeResponse(429, headers={"Retry-After": "0.01"}),
            _FakeResponse(204),
        ],
    )
    result = await publish(SAFE_MESSAGE, code="x", severity="high")

    assert result.ok is True
    assert result.attempts == 2
    assert result.reason == "ok"
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_publish_persistent_429_returns_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    _patch_client(
        monkeypatch,
        [_FakeResponse(429, json_body={"retry_after": 0.01}) for _ in range(5)],
    )
    result = await publish(SAFE_MESSAGE, code="x", severity="high")

    assert result.ok is False
    assert result.reason == "rate_limited"
    assert result.attempts == publisher._MAX_ATTEMPTS


# ── 5xx retried, then gives up ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_5xx_retries_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    fake = _patch_client(
        monkeypatch,
        [_FakeResponse(500), _FakeResponse(502), _FakeResponse(503)],
    )
    result = await publish(SAFE_MESSAGE, code="x", severity="critical")

    assert result.ok is False
    assert result.reason == "http_5xx"
    assert result.status == 503
    assert len(fake.calls) == publisher._MAX_ATTEMPTS


# ── 4xx (other than 429) is terminal ────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_404_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    fake = _patch_client(monkeypatch, [_FakeResponse(404)])

    result = await publish(SAFE_MESSAGE, code="x", severity="medium")

    assert result.ok is False
    assert result.reason == "http_4xx"
    assert result.status == 404
    assert len(fake.calls) == 1  # no retry


# ── Network errors ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_timeout_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    fake = _patch_client(
        monkeypatch,
        [httpx.TimeoutException("slow"), _FakeResponse(204)],
    )
    result = await publish(SAFE_MESSAGE, code="x", severity="high")

    assert result.ok is True
    assert result.attempts == 2
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_publish_persistent_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    _patch_client(
        monkeypatch,
        [httpx.ConnectError("nope") for _ in range(5)],
    )
    result = await publish(SAFE_MESSAGE, code="x", severity="critical")

    assert result.ok is False
    assert result.reason == "network_error"


# ── Privacy short-circuit ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_aborts_when_message_contains_webhook_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    fake = _patch_client(monkeypatch, [_FakeResponse(204)])

    leaky = f"oops we leaked {WEBHOOK_URL}"
    result = await publish(leaky, code="x", severity="medium")

    assert result.ok is False
    assert result.reason == "privacy_violation"
    assert fake.calls == []


@pytest.mark.asyncio
async def test_publish_aborts_when_message_contains_forbidden_substring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    fake = _patch_client(monkeypatch, [_FakeResponse(204)])

    msg = "🟧 [QC] Refund risk on luna_main — fan_handle_xyz mentioned chargeback"
    result = await publish(
        msg,
        code="refund_risk",
        severity="critical",
        forbidden_substrings=("fan_handle_xyz",),
    )
    assert result.ok is False
    assert result.reason == "privacy_violation"
    assert fake.calls == []


# ── No-leak invariant for logs ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publisher_never_logs_webhook_url_on_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable(monkeypatch)
    _patch_client(monkeypatch, [_FakeResponse(204)])

    with caplog.at_level(logging.DEBUG, logger=publisher.logger.name):
        await publish(SAFE_MESSAGE, code="account_blocked", severity="critical")

    for record in caplog.records:
        assert WEBHOOK_URL not in record.getMessage()
        for value in record.__dict__.values():
            if isinstance(value, str):
                assert WEBHOOK_URL not in value


@pytest.mark.asyncio
async def test_publisher_never_logs_webhook_url_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable(monkeypatch)
    _patch_client(monkeypatch, [_FakeResponse(500), _FakeResponse(500), _FakeResponse(500)])

    with caplog.at_level(logging.DEBUG, logger=publisher.logger.name):
        await publish(SAFE_MESSAGE, code="x", severity="critical")

    for record in caplog.records:
        assert WEBHOOK_URL not in record.getMessage()
        for value in record.__dict__.values():
            if isinstance(value, str):
                assert WEBHOOK_URL not in value


# ── Public helpers ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_enabled_reads_env_each_call_when_db_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_row() -> bool | None:
        return None

    monkeypatch.setattr(publisher, "_read_db_enabled", _no_row)

    monkeypatch.delenv("MC_OF_QC_DISCORD_ENABLED", raising=False)
    assert await publisher.is_enabled() is False

    monkeypatch.setenv("MC_OF_QC_DISCORD_ENABLED", "1")
    assert await publisher.is_enabled() is True

    monkeypatch.setenv("MC_OF_QC_DISCORD_ENABLED", "no")
    assert await publisher.is_enabled() is False


@pytest.mark.asyncio
async def test_is_enabled_db_value_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once the operator has set the toggle in the UI, env must not flip it."""

    async def _db_off() -> bool | None:
        return False

    monkeypatch.setattr(publisher, "_read_db_enabled", _db_off)
    monkeypatch.setenv("MC_OF_QC_DISCORD_ENABLED", "1")
    assert await publisher.is_enabled() is False

    async def _db_on() -> bool | None:
        return True

    monkeypatch.setattr(publisher, "_read_db_enabled", _db_on)
    monkeypatch.delenv("MC_OF_QC_DISCORD_ENABLED", raising=False)
    assert await publisher.is_enabled() is True


# ── bypass_kill_switch (Send test alert) ────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_bypass_sends_when_db_toggle_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test alert path must fire even when the operator toggle is off."""

    async def _db_off() -> bool | None:
        return False

    monkeypatch.setattr(publisher, "_read_db_enabled", _db_off)
    monkeypatch.setenv("MC_OF_QC_DISCORD_WEBHOOK_URL", WEBHOOK_URL)
    monkeypatch.delenv("MC_OF_QC_DISCORD_ENABLED", raising=False)

    fake = _patch_client(monkeypatch, [_FakeResponse(204)])
    result = await publish(
        SAFE_MESSAGE,
        code="qc_discord_settings_test",
        severity="info",
        bypass_kill_switch=True,
    )
    assert result.ok is True
    assert result.reason == "ok"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_publish_bypass_still_requires_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass does not invent a URL — no webhook still means no_webhook."""
    monkeypatch.delenv("MC_OF_QC_DISCORD_WEBHOOK_URL", raising=False)

    fake = _patch_client(monkeypatch, [_FakeResponse(204)])
    result = await publish(
        SAFE_MESSAGE,
        code="qc_discord_settings_test",
        severity="info",
        bypass_kill_switch=True,
    )
    assert result.ok is False
    assert result.reason == "no_webhook"
    assert fake.calls == []


@pytest.mark.asyncio
async def test_publish_bypass_still_runs_privacy_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MC_OF_QC_DISCORD_WEBHOOK_URL", WEBHOOK_URL)

    fake = _patch_client(monkeypatch, [_FakeResponse(204)])
    leaky = f"oops we leaked {WEBHOOK_URL}"
    result = await publish(
        leaky,
        code="qc_discord_settings_test",
        severity="info",
        bypass_kill_switch=True,
    )
    assert result.ok is False
    assert result.reason == "privacy_violation"
    assert fake.calls == []


# ── Resolver: DB-first with env fallback ────────────────────────────────────


@pytest.mark.asyncio
async def test_resolver_prefers_db_value_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    db_url = "https://discord.com/api/webhooks/9999/dbtoken"
    env_url = "https://discord.com/api/webhooks/1111/envtoken"

    async def _from_db() -> str:
        return db_url

    monkeypatch.setattr(publisher, "_read_db_webhook", _from_db)
    monkeypatch.setenv("MC_OF_QC_DISCORD_ENABLED", "1")
    monkeypatch.setenv("MC_OF_QC_DISCORD_WEBHOOK_URL", env_url)

    fake = _patch_client(monkeypatch, [_FakeResponse(204)])
    result = await publish(SAFE_MESSAGE, code="x", severity="critical")

    assert result.ok is True
    assert len(fake.calls) == 1
    sent_url, _ = fake.calls[0]
    assert sent_url == db_url
    assert sent_url != env_url


@pytest.mark.asyncio
async def test_resolver_falls_back_to_env_when_db_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    env_url = "https://discord.com/api/webhooks/2222/envonly"

    async def _empty() -> str:
        return ""

    monkeypatch.setattr(publisher, "_read_db_webhook", _empty)
    monkeypatch.setenv("MC_OF_QC_DISCORD_ENABLED", "1")
    monkeypatch.setenv("MC_OF_QC_DISCORD_WEBHOOK_URL", env_url)

    fake = _patch_client(monkeypatch, [_FakeResponse(204)])
    result = await publish(SAFE_MESSAGE, code="x", severity="medium")

    assert result.ok is True
    sent_url, _ = fake.calls[0]
    assert sent_url == env_url


@pytest.mark.asyncio
async def test_resolver_returns_no_webhook_when_both_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _empty() -> str:
        return ""

    monkeypatch.setattr(publisher, "_read_db_webhook", _empty)
    monkeypatch.setenv("MC_OF_QC_DISCORD_ENABLED", "1")
    monkeypatch.delenv("MC_OF_QC_DISCORD_WEBHOOK_URL", raising=False)

    fake = _patch_client(monkeypatch, [_FakeResponse(204)])
    result = await publish(SAFE_MESSAGE, code="x", severity="medium")

    assert result.ok is False
    assert result.reason == "no_webhook"
    assert fake.calls == []


@pytest.mark.asyncio
async def test_read_db_webhook_swallows_secrets_store_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the DB / secrets_store raises for any reason, return ''.

    The publisher must keep its never-raise contract, so DB outages must
    fall through silently to the env fallback.
    """
    # Disable the autouse stub for this test so we exercise the real function.
    monkeypatch.undo()

    import app.core.secrets_store as secrets_store

    async def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(secrets_store, "get_secret", _boom)

    value = await publisher._read_db_webhook()
    assert value == ""


# Silence pyright on unused imports — kept for symmetry with existing test files.
_ = (Callable, logging)
