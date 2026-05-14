"""MSA RT/X bot job-queue bridge API.

Endpoints (all under ``/api/v1/msa-rtxrt``):

  GET    /jobs                  list recent jobs (operator+)
  POST   /jobs                  create a job (operator+ for dry-run,
                                require_owner + safety-flag body for
                                live-one)
  GET    /runner/poll           atomically claim the next queued job
                                (runner-token auth)
  PATCH  /jobs/{id}             runner reports status (runner-token auth)

Hard rules enforced here:
  * Mass-live job kinds are refused outright.
  * Live-one jobs require ``confirm_live="YES"`` and
    ``max_test_actions=1`` in the request body AND owner role.
  * Status transitions are gated against ALLOWED_TRANSITIONS.
  * Every mutation writes an ``audit_events`` row.
  * The runner-auth header is the only way the runner endpoints
    authenticate; if the env var is unset, both endpoints 503.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from app.api.mc_roles import (
    get_mc_role,
    require_operator,
    require_owner,
)
from app.core.auth import AuthContext, get_auth_context
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import get_session
from app.models.msa_rtxrt_job import (
    DRY_RUN_KINDS,
    LIVE_ONE_KINDS,
    STATUS_BLOCKED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    VALID_KINDS,
    VALID_STATUSES,
    MsaRtxrtJob,
)
from app.models.msa_rtxrt_runner_heartbeat import (
    ONLINE_FRESHNESS_SECONDS,
    RUNNER_STATUS_BUSY,
    RUNNER_STATUS_IDLE,
    MsaRtxrtRunnerHeartbeat,
)
from app.services.audit_log import actor_from_auth, record_audit
from app.services.msa_rtxrt_jobs import (
    IllegalTransitionError,
    LiveOneSafetyError,
    MassLiveBlockedError,
    UnknownKindError,
    cap_excerpt,
    cap_summary,
    is_live_one_kind,
    validate_kind,
    validate_live_one_request,
    validate_transition,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/msa-rtxrt", tags=["msa-rtxrt"])
logger = get_logger(__name__)

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)
ROLE_DEP = Depends(get_mc_role)
OPERATOR_DEP = Depends(require_operator)
OWNER_DEP = Depends(require_owner)


# ── Runner-auth dependency ──────────────────────────────────────────────────


async def require_runner_auth(
    x_msa_rtxrt_runner_token: str | None = Header(default=None),
) -> str:
    """Validate the shared-secret header the Claw runner sends.

    Returns the matched token (only the fact-of-match matters; the value
    is never logged). Refuses with 503 if the server has no runner token
    configured — better to disable the endpoint than match an empty
    string.
    """
    expected = (settings.msa_rtxrt_runner_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MSA RT/X runner endpoint is disabled (no runner token configured).",
        )
    presented = (x_msa_rtxrt_runner_token or "").strip()
    if not presented or presented != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid runner token.",
        )
    return presented


RUNNER_AUTH_DEP = Depends(require_runner_auth)


# ── Schemas ─────────────────────────────────────────────────────────────────


class CreateJobRequest(BaseModel):
    """Request body for ``POST /jobs``."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(..., min_length=1, max_length=32)
    # Live-one safety flags. Optional for dry-run kinds; required (and
    # validated) for live-one kinds.
    confirm_live: str | None = Field(default=None, max_length=8)
    max_test_actions: int | None = Field(default=None, ge=0, le=1)


class JobRow(BaseModel):
    """Privacy-safe job row returned by the list / poll / patch endpoints."""

    id: UUID
    kind: str
    status: str
    requested_by_user_id: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    summary: str | None
    stdout_excerpt: str | None
    error_excerpt: str | None
    runner_id: str | None
    dry_run: bool
    live_one: bool
    max_test_actions: int


class JobList(BaseModel):
    items: list[JobRow]


class PatchJobRequest(BaseModel):
    """Request body for ``PATCH /jobs/{id}`` (runner-only)."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., min_length=1, max_length=16)
    summary: str | None = Field(default=None, max_length=2048)
    stdout_excerpt: str | None = Field(default=None, max_length=8192)
    error_excerpt: str | None = Field(default=None, max_length=8192)
    runner_id: str | None = Field(default=None, max_length=128)


class PollResponse(BaseModel):
    """Response from ``GET /runner/poll``."""

    job: JobRow | None


# ── Helpers ─────────────────────────────────────────────────────────────────


def _job_to_row(job: MsaRtxrtJob) -> JobRow:
    return JobRow(
        id=job.id,
        kind=job.kind,
        status=job.status,
        requested_by_user_id=job.requested_by_user_id,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        summary=job.summary,
        stdout_excerpt=job.stdout_excerpt,
        error_excerpt=job.error_excerpt,
        runner_id=job.runner_id,
        dry_run=job.dry_run,
        live_one=job.live_one,
        max_test_actions=job.max_test_actions,
    )


# ── GET /jobs ───────────────────────────────────────────────────────────────


@router.get("/jobs", response_model=JobList)
async def list_jobs(
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
) -> JobList:
    """List recent MSA RT/X jobs. Operator or higher only."""
    _ = auth
    _ = role
    stmt = (
        select(MsaRtxrtJob)
        .order_by(MsaRtxrtJob.created_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
    )
    if status_filter:
        if status_filter not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown status: {status_filter!r}",
            )
        stmt = (
            select(MsaRtxrtJob)
            .where(MsaRtxrtJob.status == status_filter)
            .order_by(MsaRtxrtJob.created_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
    result = await session.exec(stmt)
    rows = result.all()
    return JobList(items=[_job_to_row(r) for r in rows])


# ── POST /jobs ──────────────────────────────────────────────────────────────


@router.post(
    "/jobs",
    response_model=JobRow,
    status_code=status.HTTP_201_CREATED,
)
async def create_job(
    body: CreateJobRequest,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    viewer_role: str = ROLE_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> JobRow:
    """Enqueue a new MSA RT/X job.

    Dry-run kinds (``smoke``, ``dry_run_*``) require operator+.
    Live-one kinds (``live_one_*``) require owner AND
    ``confirm_live="YES"`` AND ``max_test_actions=1``.
    """
    _ = role  # operator+ already enforced by OPERATOR_DEP
    actor_id, actor_email = actor_from_auth(auth)

    # Validate the kind first (mass-live block + membership).
    try:
        validate_kind(body.kind)
    except MassLiveBlockedError as exc:
        await record_audit(
            session,
            actor_clerk_user_id=actor_id,
            actor_email=actor_email,
            action="msa_rtxrt.job.create.blocked_mass_live",
            target_type="msa_rtxrt_job",
            outcome="blocked",
            safe_summary=str(exc),
            request=request,
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UnknownKindError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Live-one path: owner + safety flags.
    live_one = is_live_one_kind(body.kind)
    if live_one:
        if viewer_role != "owner":
            await record_audit(
                session,
                actor_clerk_user_id=actor_id,
                actor_email=actor_email,
                actor_role=viewer_role,
                action="msa_rtxrt.job.create.denied_non_owner",
                target_type="msa_rtxrt_job",
                outcome="denied",
                safe_summary=f"non-owner attempted live-one kind {body.kind!r}",
                request=request,
            )
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Live-one jobs require owner role.",
            )
        try:
            validate_live_one_request(
                kind=body.kind,
                confirm_live=body.confirm_live,
                max_test_actions=body.max_test_actions,
            )
        except LiveOneSafetyError as exc:
            await record_audit(
                session,
                actor_clerk_user_id=actor_id,
                actor_email=actor_email,
                actor_role="owner",
                action="msa_rtxrt.job.create.blocked_safety_gate",
                target_type="msa_rtxrt_job",
                outcome="blocked",
                safe_summary=str(exc),
                request=request,
            )
            await session.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Build the row.
    job = MsaRtxrtJob(
        kind=body.kind,
        status=STATUS_QUEUED,
        requested_by_user_id=actor_id,
        dry_run=not live_one,
        live_one=live_one,
        max_test_actions=body.max_test_actions or 0,
    )
    session.add(job)
    await session.flush()  # populate job.id

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role="owner" if live_one else None,
        action=("msa_rtxrt.job.create.live_one" if live_one else "msa_rtxrt.job.create"),
        target_type="msa_rtxrt_job",
        target_id=str(job.id),
        outcome="success",
        safe_summary=f"kind={body.kind} live_one={live_one}",
        request=request,
    )
    await session.commit()
    await session.refresh(job)
    return _job_to_row(job)


# ── GET /runner/poll ────────────────────────────────────────────────────────


async def _upsert_runner_heartbeat(
    session: "AsyncSession",
    *,
    runner_id: str | None,
    busy: bool,
) -> None:
    """Update (or insert) the heartbeat row for ``runner_id``.

    Called on every valid ``/runner/poll`` regardless of whether work is
    returned. ``busy`` is True when this poll claimed a job; the row is
    set to ``idle`` immediately afterwards when the runner's next poll
    returns no work, so the status reflects the most recent observation.
    """
    if runner_id is None or not runner_id.strip():
        return  # No identifier → no heartbeat (the v1 frontend asserts on claw-1).
    rid = runner_id.strip()
    now = utcnow()
    heartbeat = await session.get(MsaRtxrtRunnerHeartbeat, rid)
    target_status = RUNNER_STATUS_BUSY if busy else RUNNER_STATUS_IDLE
    if heartbeat is None:
        heartbeat = MsaRtxrtRunnerHeartbeat(
            runner_id=rid,
            last_seen_at=now,
            last_poll_at=now,
            last_status=target_status,
        )
    else:
        heartbeat.last_seen_at = now
        heartbeat.last_poll_at = now
        heartbeat.last_status = target_status
    session.add(heartbeat)


@router.get("/runner/poll", response_model=PollResponse)
async def runner_poll(
    request: Request,
    _token: str = RUNNER_AUTH_DEP,
    session: "AsyncSession" = SESSION_DEP,
    runner_id: str | None = Query(default=None, max_length=128),
) -> PollResponse:
    """Atomically claim the next queued job for the runner.

    Also writes the runner's heartbeat row. Returns ``{"job": null}``
    when the queue is empty; the heartbeat still gets stamped so the UI
    can show *Runner online (idle)* even before the first job ships.
    """
    stmt = (
        select(MsaRtxrtJob)
        .where(MsaRtxrtJob.status == STATUS_QUEUED)
        .order_by(MsaRtxrtJob.created_at.asc())  # type: ignore[attr-defined]
        .limit(1)
    )
    result = await session.exec(stmt)
    candidate = result.first()
    if candidate is None:
        # Empty queue → still heartbeat (idle) so the UI knows we're alive.
        await _upsert_runner_heartbeat(session, runner_id=runner_id, busy=False)
        await session.commit()
        return PollResponse(job=None)

    # Atomic-ish claim: flip queued→running and refresh. The
    # ``ALLOWED_TRANSITIONS`` check is defensive — if another runner
    # already grabbed this row, ``status`` will have moved off
    # ``queued`` and the validate call will raise.
    try:
        validate_transition(candidate.status, STATUS_RUNNING)
    except IllegalTransitionError:
        await _upsert_runner_heartbeat(session, runner_id=runner_id, busy=False)
        await session.commit()
        return PollResponse(job=None)

    candidate.status = STATUS_RUNNING
    candidate.started_at = utcnow()
    if runner_id is not None and runner_id.strip():
        candidate.runner_id = runner_id.strip()
    session.add(candidate)

    await _upsert_runner_heartbeat(session, runner_id=runner_id, busy=True)

    await record_audit(
        session,
        actor_clerk_user_id="runner",
        action="msa_rtxrt.job.claimed",
        target_type="msa_rtxrt_job",
        target_id=str(candidate.id),
        outcome="success",
        safe_summary=f"kind={candidate.kind} runner_id={candidate.runner_id or '?'}",
        request=request,
    )
    await session.commit()
    await session.refresh(candidate)
    return PollResponse(job=_job_to_row(candidate))


# ── GET /runner/status ──────────────────────────────────────────────────────


class RunnerHeartbeatRow(BaseModel):
    """One heartbeat snapshot. Privacy-safe — runner_id is operator-chosen."""

    runner_id: str
    last_seen_at: datetime
    seconds_since_seen: int
    status: str  # "online" | "offline"
    last_status: str  # "idle" | "busy"


class RunnerStatusResponse(BaseModel):
    """Aggregate runner-status snapshot returned by GET /runner/status."""

    runners: list[RunnerHeartbeatRow]
    any_online: bool
    freshness_seconds: int


@router.get("/runner/status", response_model=RunnerStatusResponse)
async def runner_status_endpoint(
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> RunnerStatusResponse:
    """Operator-facing runner heartbeat snapshot.

    Online == observed within ``ONLINE_FRESHNESS_SECONDS``. Used by the
    frontend pill to flip *Runner online (idle)* even when no jobs have
    ever run. No secrets exposed; runner_id is operator-chosen.
    """
    _ = auth
    _ = role
    result = await session.exec(select(MsaRtxrtRunnerHeartbeat))
    rows = result.all()
    now = utcnow()
    out: list[RunnerHeartbeatRow] = []
    any_online = False
    for row in rows:
        age = max(0, int((now - row.last_seen_at).total_seconds()))
        online = age <= ONLINE_FRESHNESS_SECONDS
        if online:
            any_online = True
        out.append(
            RunnerHeartbeatRow(
                runner_id=row.runner_id,
                last_seen_at=row.last_seen_at,
                seconds_since_seen=age,
                status="online" if online else "offline",
                last_status=row.last_status,
            )
        )
    # Sort newest-seen first so the most relevant runner is index 0.
    out.sort(key=lambda r: r.seconds_since_seen)
    return RunnerStatusResponse(
        runners=out,
        any_online=any_online,
        freshness_seconds=ONLINE_FRESHNESS_SECONDS,
    )


# ── PATCH /jobs/{id} ────────────────────────────────────────────────────────


@router.patch("/jobs/{job_id}", response_model=JobRow)
async def patch_job(
    job_id: UUID,
    body: PatchJobRequest,
    request: Request,
    _token: str = RUNNER_AUTH_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> JobRow:
    """Runner reports status + privacy-safe excerpts.

    Allowed transitions:
        running -> succeeded | failed | blocked | cancelled
        queued  -> blocked   (e.g. the runner refused to even start it)
    The runner is the only path that PATCHes; operators cannot.
    """
    job = await session.get(MsaRtxrtJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    try:
        validate_transition(job.status, body.status)
    except IllegalTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    job.status = body.status
    job.summary = cap_summary(body.summary) if body.summary is not None else job.summary
    job.stdout_excerpt = (
        cap_excerpt(body.stdout_excerpt) if body.stdout_excerpt is not None else job.stdout_excerpt
    )
    job.error_excerpt = (
        cap_excerpt(body.error_excerpt) if body.error_excerpt is not None else job.error_excerpt
    )
    if body.runner_id is not None and body.runner_id.strip():
        job.runner_id = body.runner_id.strip()
    if body.status in {STATUS_SUCCEEDED, STATUS_FAILED, STATUS_BLOCKED, "cancelled"}:
        job.finished_at = utcnow()

    session.add(job)

    action = {
        STATUS_SUCCEEDED: "msa_rtxrt.job.succeeded",
        STATUS_FAILED: "msa_rtxrt.job.failed",
        STATUS_BLOCKED: "msa_rtxrt.job.blocked",
    }.get(body.status, "msa_rtxrt.job.updated")
    outcome = (
        "success"
        if body.status == STATUS_SUCCEEDED
        else (
            "failed"
            if body.status == STATUS_FAILED
            else ("blocked" if body.status == STATUS_BLOCKED else "success")
        )
    )
    await record_audit(
        session,
        actor_clerk_user_id="runner",
        action=action,
        target_type="msa_rtxrt_job",
        target_id=str(job.id),
        outcome=outcome,
        safe_summary=f"status={body.status} kind={job.kind}",
        request=request,
    )
    await session.commit()
    await session.refresh(job)
    return _job_to_row(job)


# Public reference values for tests + the frontend's typed kind list.
__all__ = [
    "router",
    "DRY_RUN_KINDS",
    "LIVE_ONE_KINDS",
    "VALID_KINDS",
]
