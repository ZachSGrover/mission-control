"""Local Claw-computer runner for the MSA RT/X Automation Bot.

Architecture (Mission Control split):
  - Mission Control web UI is the *control panel*. It enqueues jobs.
  - This runner lives on Zach's Claw computer. It polls the queue,
    runs the matching local Python command inside Luis's imported
    MSA RT/X folder, captures output, and reports status back.
  - The runner is started manually on the Claw computer. Mission
    Control never starts it remotely.

Safety contract (hard-coded in this file — must not be bypassed):
  - Default mode is dry-run. ``ALLOW_LIVE_EXTERNAL_ACTIONS`` must be
    set to ``true`` *in the runner's local environment* to even
    consider a live-one job.
  - Live-one jobs require ALL of:
      * ``ALLOW_LIVE_EXTERNAL_ACTIONS=true``
      * ``CONFIRM_LIVE_TEST=YES``
      * ``MAX_TEST_ACTIONS=1``
  - Mass live runs are blocked outright. There is no "live many" job
    kind in this runner and the dispatch table refuses to construct
    one even if the queue asks for it.
  - The runner never reads secrets from Mission Control. All env
    vars (AdsPower keys, X session cookies, OnlyFans tokens, etc.)
    live in the Claw computer's local environment and never reach
    the frontend.

The poll loop talks to Mission Control over HTTP:
  - ``GET  {base}/api/v1/msa-rtxrt/runner/poll``  to claim work
  - ``PATCH {base}/api/v1/msa-rtxrt/jobs/{id}``    to report status

Auth: the runner sends ``X-MSA-RTXRT-Runner-Token`` matching the value
the operator stored on the Claw computer in ``MSA_RTXRT_RUNNER_TOKEN``.
The same token must be configured on the backend. The token is
NEVER stored in the DB and never appears in any response.

This module is import-safe (no side effects at import time) so the
tests next door can call into helpers directly. We use ``urllib`` from
the stdlib so the runner has zero pip deps beyond Python itself.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess  # noqa: S404 - intentional; called via list args, no shell.
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# ── Job-kind contract ───────────────────────────────────────────────────────

DRY_RUN_KINDS: Final[tuple[str, ...]] = (
    "smoke",
    "dry_run_blast",
    "dry_run_dm",
    "dry_run_repost",
    "dry_run_builder",
    "dry_run_scan",
)
LIVE_ONE_KINDS: Final[tuple[str, ...]] = (
    "live_one_blast",
    "live_one_dm",
    "live_one_repost",
    "live_one_builder",
    "live_one_scan",
)
ALL_KINDS: Final[tuple[str, ...]] = DRY_RUN_KINDS + LIVE_ONE_KINDS

# Map job kind -> (script filename, default flag args). Live-one jobs add
# the live-mode flags only after passing the safety gate.
_DRY_RUN_COMMANDS: Final[dict[str, tuple[str, list[str]]]] = {
    "smoke": ("safety_guard.py", ["--smoke"]),
    "dry_run_blast": ("blast_bot.py", ["--dry-run"]),
    "dry_run_dm": ("dm_bot.py", ["--dry-run"]),
    "dry_run_repost": ("repost_bot.py", ["--dry-run"]),
    "dry_run_builder": ("builder_bot.py", ["--dry-run"]),
    "dry_run_scan": ("scan_test.py", ["--dry-run"]),
}

_LIVE_ONE_COMMANDS: Final[dict[str, tuple[str, list[str]]]] = {
    "live_one_blast": ("blast_bot.py", ["--live-one", "--max-actions=1"]),
    "live_one_dm": ("dm_bot.py", ["--live-one", "--max-actions=1"]),
    "live_one_repost": ("repost_bot.py", ["--live-one", "--max-actions=1"]),
    "live_one_builder": ("builder_bot.py", ["--live-one", "--max-actions=1"]),
    "live_one_scan": ("scan_test.py", ["--live-one", "--max-actions=1"]),
}


# ── Safety gate ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateResult:
    """Outcome of the live-one safety gate."""

    allowed: bool
    reason: str


def evaluate_live_one_gate(env: dict[str, str]) -> GateResult:
    """Decide whether a live-one job may proceed given the runner's env.

    The gate enforces the hard contract from the module docstring:
    ALLOW_LIVE_EXTERNAL_ACTIONS=true, CONFIRM_LIVE_TEST=YES,
    MAX_TEST_ACTIONS=1. Anything else => denied.

    Returning a plain dataclass (instead of raising) makes the gate
    trivially unit-testable and keeps the caller in control of how
    to report a denial back to Mission Control.
    """
    allow = env.get("ALLOW_LIVE_EXTERNAL_ACTIONS", "").strip().lower()
    if allow != "true":
        return GateResult(False, "ALLOW_LIVE_EXTERNAL_ACTIONS != true")

    confirm = env.get("CONFIRM_LIVE_TEST", "").strip()
    if confirm != "YES":
        return GateResult(False, "CONFIRM_LIVE_TEST != YES")

    max_actions_raw = env.get("MAX_TEST_ACTIONS", "").strip()
    try:
        max_actions = int(max_actions_raw)
    except ValueError:
        return GateResult(False, "MAX_TEST_ACTIONS is not an integer")
    if max_actions != 1:
        return GateResult(False, "MAX_TEST_ACTIONS != 1")

    return GateResult(True, "ok")


def is_mass_live_kind(kind: str) -> bool:
    """Mass live runs are not supported. Used by the dispatch table.

    No job-kind string in this runner refers to a mass live action. Any
    string that smells like one (contains ``live_all``, ``live_mass``,
    ``live_batch``, etc.) is rejected to defend against future drift.
    """
    suspicious = ("live_all", "live_mass", "live_batch", "live_many")
    lowered = kind.lower()
    return any(token in lowered for token in suspicious)


# ── Command construction ───────────────────────────────────────────────────


def build_command(
    kind: str,
    bot_dir: Path,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Construct the local shell command for ``kind`` against ``bot_dir``.

    Returns the argv list ready for ``subprocess.run`` (no ``shell=True``).
    Raises ``ValueError`` on unknown kinds, blocked mass-live kinds, or
    when a live-one kind fails the safety gate.
    """
    # Mass-live check goes first so a string like ``live_all_blast``
    # gets the specific "mass live runs are not supported" error even
    # if it isn't in ALL_KINDS — clearer signal at the safety boundary.
    if is_mass_live_kind(kind):
        raise ValueError(f"mass live runs are not supported: {kind!r}")
    if kind not in ALL_KINDS:
        raise ValueError(f"unknown job kind: {kind!r}")

    if kind in _DRY_RUN_COMMANDS:
        script, args = _DRY_RUN_COMMANDS[kind]
    else:
        # Live-one path — re-check the safety gate.
        gate = evaluate_live_one_gate(env or {})
        if not gate.allowed:
            raise ValueError(
                f"live-one denied by safety gate: {gate.reason}",
            )
        script, args = _LIVE_ONE_COMMANDS[kind]

    script_path = bot_dir / script
    return [sys.executable, str(script_path), *args]


# ── Runner status helpers ──────────────────────────────────────────────────


def resolve_bot_dir(env: dict[str, str] | None = None) -> Path:
    """Where Luis's MSA RT/X Python folder lives on this machine.

    Prefers ``MSA_RTXRT_BOT_DIR`` if set. Falls back to the expected
    path inside ``incoming/luis-msa-import``. Never reads from the
    frontend.
    """
    env = env if env is not None else dict(os.environ)
    override = env.get("MSA_RTXRT_BOT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    return (
        repo_root
        / "incoming"
        / "luis-msa-import"
        / "MSA"
        / "Monthly revenue"
        / "Automation [RTxRT]"
    ).resolve()


# ── HTTP helpers (stdlib only — runner has zero pip deps) ──────────────────


@dataclass(frozen=True)
class RunnerConfig:
    """Resolved runner config. Each field reads from ``env`` at construction."""

    base_url: str
    runner_token: str
    runner_id: str
    bot_dir: Path
    poll_interval_seconds: float

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "RunnerConfig":
        env = env if env is not None else dict(os.environ)
        base = env.get("MSA_RTXRT_BACKEND_URL", "").strip().rstrip("/")
        token = env.get("MSA_RTXRT_RUNNER_TOKEN", "").strip()
        runner_id = env.get("MSA_RTXRT_RUNNER_ID", "claw-1").strip() or "claw-1"
        bot_dir = resolve_bot_dir(env)
        try:
            interval = float(env.get("MSA_RTXRT_POLL_INTERVAL_SECONDS", "5") or "5")
        except ValueError:
            interval = 5.0
        return cls(
            base_url=base,
            runner_token=token,
            runner_id=runner_id,
            bot_dir=bot_dir,
            poll_interval_seconds=max(1.0, interval),
        )


def _http_request(
    *,
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any] | None]:
    """Minimal stdlib HTTP wrapper.

    Returns ``(status_code, parsed_body)``. ``parsed_body`` is ``None``
    when the body is empty or not JSON. The runner-auth token is sent in
    the header. We never log the URL with a token in it.
    """
    data: bytes | None = None
    headers = {
        "X-MSA-RTXRT-Runner-Token": token,
        "Accept": "application/json",
        "User-Agent": "msa-rtxrt-runner/1",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - controlled URL.
            raw = resp.read()
            try:
                parsed = json.loads(raw.decode("utf-8")) if raw else None
            except (json.JSONDecodeError, UnicodeDecodeError):
                parsed = None
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            parsed = None
        return exc.code, parsed


def poll_for_job(
    cfg: RunnerConfig,
    *,
    http: Any = None,
) -> dict[str, Any] | None:
    """Call ``GET /runner/poll`` and return the claimed job dict, or None.

    ``http`` defaults to :func:`_http_request` and is parameterized so
    tests can inject a stub without touching the network.
    """
    if not cfg.base_url or not cfg.runner_token:
        return None
    http = http if http is not None else _http_request
    query = urllib.parse.urlencode({"runner_id": cfg.runner_id})
    url = f"{cfg.base_url}/api/v1/msa-rtxrt/runner/poll?{query}"
    status, body = http(method="GET", url=url, token=cfg.runner_token)
    if status != 200 or not isinstance(body, dict):
        return None
    job = body.get("job")
    return job if isinstance(job, dict) else None


# Retry config for the final-state PATCH. A transient HTTP blip (e.g. one
# slow Render edge or a brief connection reset) must NOT leave a completed
# job stuck as "running" in Mission Control. Retries are intentionally
# short — we'd rather give up loudly than block the poll loop indefinitely.
PATCH_MAX_ATTEMPTS: Final[int] = 4
PATCH_BACKOFF_SECONDS: Final[tuple[float, ...]] = (0.5, 1.5, 4.0)


def patch_job_status(
    cfg: RunnerConfig,
    *,
    job_id: str,
    status_value: str,
    summary: str | None = None,
    stdout_excerpt: str | None = None,
    error_excerpt: str | None = None,
    http: Any = None,
    max_attempts: int = PATCH_MAX_ATTEMPTS,
    sleep: Any = None,
) -> bool:
    """PATCH a job with a new status.

    Retries on transient network errors (raised exceptions, server 5xx,
    408 Request Timeout, 429 Too Many Requests) so a completed bot
    subprocess does not leave its job stuck as "running" in Mission Control
    after a brief HTTP blip. Returns True if the backend eventually
    accepted the PATCH (HTTP 200), False otherwise.

    Never raises. The bot subprocess has already exited by the time this
    is called from the success / failure paths; turning a transient PATCH
    failure into an apparent runner crash would mis-report a real outcome
    and leave the poll loop's outer except to log a confusing trace.

    ``max_attempts`` and ``sleep`` are parameterised so tests can drive
    the retry path without inserting real seconds of backoff.
    """
    http = http if http is not None else _http_request
    sleep = sleep if sleep is not None else time.sleep
    payload: dict[str, Any] = {"status": status_value, "runner_id": cfg.runner_id}
    if summary is not None:
        payload["summary"] = summary
    if stdout_excerpt is not None:
        payload["stdout_excerpt"] = stdout_excerpt
    if error_excerpt is not None:
        payload["error_excerpt"] = error_excerpt
    url = f"{cfg.base_url}/api/v1/msa-rtxrt/jobs/{job_id}"

    attempts = max(1, max_attempts)
    last_status: int | None = None
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            status, _body = http(
                method="PATCH",
                url=url,
                token=cfg.runner_token,
                body=payload,
            )
            last_status = status
            last_exc = None
            if status == 200:
                return True
            # Only retry transient server errors (5xx, 408 Request Timeout,
            # 429 Too Many Requests). Other 4xx mean the request itself is
            # invalid; retrying won't change the outcome.
            if status < 500 and status not in (408, 429):
                print(
                    f"  PATCH job={job_id} status={status_value} -> HTTP {status} "
                    f"(non-retryable, giving up after attempt {attempt}/{attempts})",
                    file=sys.stderr,
                )
                return False
        except Exception as exc:  # noqa: BLE001 - never crash the poll loop here
            last_exc = exc

        if attempt < attempts:
            delay = PATCH_BACKOFF_SECONDS[
                min(attempt - 1, len(PATCH_BACKOFF_SECONDS) - 1)
            ]
            sleep(delay)

    detail = (
        f"HTTP {last_status}" if last_exc is None
        else f"{type(last_exc).__name__}: {last_exc!r}"
    )
    print(
        f"  PATCH job={job_id} status={status_value} FAILED after "
        f"{attempts} attempts ({detail}). Job may remain visible as "
        f"'running' in Mission Control until manually reconciled.",
        file=sys.stderr,
    )
    return False


# Privacy caps on excerpts we send back. The backend re-caps too.
MAX_SUMMARY_LEN: Final[int] = 240
MAX_EXCERPT_LEN: Final[int] = 1900


def _excerpt(text: str | None, *, cap: int) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) <= cap:
        return text
    return text[:cap] + "…"


def execute_job(
    cfg: RunnerConfig,
    job: dict[str, Any],
    *,
    http: Any = None,
    runner: Any = None,
) -> str:
    """Run one queued job to completion and PATCH the result back.

    ``runner`` defaults to :func:`run_job` and is parameterized so tests
    can inject a stub that doesn't actually spawn a subprocess.
    Returns the final status string (``succeeded``/``failed``/``blocked``).
    """
    runner = runner if runner is not None else run_job
    job_id = str(job.get("id", "")).strip()
    kind = str(job.get("kind", "")).strip()
    if not job_id or not kind:
        return "blocked"

    # If the runner can't even build the command (gate / unknown / mass
    # live), report `blocked` immediately with a privacy-safe reason.
    try:
        _ = build_command(kind, cfg.bot_dir, env=dict(os.environ))
    except ValueError as exc:
        patch_job_status(
            cfg,
            job_id=job_id,
            status_value="blocked",
            summary=_excerpt(str(exc), cap=MAX_SUMMARY_LEN),
            http=http,
        )
        return "blocked"

    try:
        result = runner(kind, bot_dir=cfg.bot_dir)
    except Exception as exc:  # noqa: BLE001 — surface any failure as `failed`.
        patch_job_status(
            cfg,
            job_id=job_id,
            status_value="failed",
            summary=_excerpt(f"runner crashed: {exc!r}", cap=MAX_SUMMARY_LEN),
            error_excerpt=_excerpt(str(exc), cap=MAX_EXCERPT_LEN),
            http=http,
        )
        return "failed"

    if result.returncode == 0:
        patch_job_status(
            cfg,
            job_id=job_id,
            status_value="succeeded",
            summary=_excerpt(f"{kind} ok", cap=MAX_SUMMARY_LEN),
            stdout_excerpt=_excerpt(result.stdout, cap=MAX_EXCERPT_LEN),
            http=http,
        )
        return "succeeded"

    patch_job_status(
        cfg,
        job_id=job_id,
        status_value="failed",
        summary=_excerpt(
            f"{kind} exited {result.returncode}", cap=MAX_SUMMARY_LEN
        ),
        stdout_excerpt=_excerpt(result.stdout, cap=MAX_EXCERPT_LEN),
        error_excerpt=_excerpt(result.stderr, cap=MAX_EXCERPT_LEN),
        http=http,
    )
    return "failed"


def poll_once(cfg: RunnerConfig, *, http: Any = None, runner: Any = None) -> str | None:
    """One poll → run → patch round trip.

    Returns the final status string, or ``None`` if no job was available
    (or if backend connection failed).
    """
    job = poll_for_job(cfg, http=http)
    if job is None:
        return None
    return execute_job(cfg, job, http=http, runner=runner)


# ── Preflight + AdsPower connectivity check ────────────────────────────────
#
# `--preflight` (recommended for Luis) prints a structured JSON report of
# every safety/runtime precondition, without sending anything anywhere
# except (1) a /healthz GET to the configured backend and (2) a single
# GET to the AdsPower local API. Neither call opens a browser profile,
# logs in to X, or touches OnlyFans / OnlyMonster.
#
# `--check-adspower` is a narrower variant that only probes AdsPower.

ADSPOWER_LOCAL_BASE: Final[str] = "http://local.adspower.net:50325"
ADSPOWER_LIST_PATH: Final[str] = "/api/v1/user/list?page=1&page_size=1"


def _bool_env(name: str) -> bool:
    val = os.environ.get(name)
    return bool(val and val.strip().lower() in ("1", "true", "yes", "on"))


def check_python_imports() -> dict[str, bool]:
    """Soft-import the deps Luis's bot folder declares. Never raises."""
    out: dict[str, bool] = {}
    for mod in ("requests", "playwright", "playwright.sync_api"):
        try:
            __import__(mod)
            out[mod] = True
        except Exception:  # noqa: BLE001 - missing deps must not crash preflight
            out[mod] = False
    return out


def check_backend_reachable(cfg: RunnerConfig, *, http: Any = None) -> dict[str, Any]:
    """GET {base}/healthz with no auth. Reports HTTP status + reachable bool."""
    if not cfg.base_url:
        return {"configured": False, "reachable": False, "http_status": None}
    http = http if http is not None else _http_request
    try:
        status, _body = http(
            method="GET",
            url=f"{cfg.base_url}/healthz",
            token="",  # /healthz takes no auth header
            timeout=10.0,
        )
    except Exception as exc:  # noqa: BLE001 - any error counts as unreachable
        return {
            "configured": True,
            "reachable": False,
            "http_status": None,
            "error": type(exc).__name__,
        }
    return {
        "configured": True,
        "reachable": status == 200,
        "http_status": status,
    }


def check_backend_token(cfg: RunnerConfig, *, http: Any = None) -> dict[str, Any]:
    """Probe the runner-auth endpoint with the configured token.

    Returns ``accepted: True`` if HTTP 200 (token valid), ``accepted: False``
    if 401 (token configured but wrong) or 503 (token not configured on
    backend). Does NOT consume a job (the poll endpoint is idempotent and
    returns ``{"job": null}`` if no work is queued).
    """
    if not cfg.base_url or not cfg.runner_token:
        return {"configured": False, "accepted": False, "http_status": None}
    http = http if http is not None else _http_request
    try:
        status, _body = http(
            method="GET",
            url=f"{cfg.base_url}/api/v1/msa-rtxrt/runner/poll?runner_id={urllib.parse.quote(cfg.runner_id)}",
            token=cfg.runner_token,
            timeout=10.0,
        )
    except Exception as exc:  # noqa: BLE001 - report cleanly
        return {
            "configured": True,
            "accepted": False,
            "http_status": None,
            "error": type(exc).__name__,
        }
    return {
        "configured": True,
        "accepted": status == 200,
        "http_status": status,
    }


def check_adspower(*, http: Any = None) -> dict[str, Any]:
    """Probe the local AdsPower API. Does NOT open any profile.

    Calls the documented profile-list endpoint with a tiny page size.
    If the AdsPower app isn't running locally, the request raises a
    connection error which we report cleanly. We never log API responses.
    """
    api_key_present = bool((os.environ.get("ADSPOWER_API_KEY") or "").strip())
    http = http if http is not None else _http_request
    try:
        status, _body = http(
            method="GET",
            url=f"{ADSPOWER_LOCAL_BASE}{ADSPOWER_LIST_PATH}",
            token="",  # AdsPower local API uses no auth by default
            timeout=5.0,
        )
        reachable = status == 200
        return {
            "api_reachable": reachable,
            "http_status": status,
            "api_key_present": api_key_present,
        }
    except Exception as exc:  # noqa: BLE001 - "not running" is a normal outcome
        return {
            "api_reachable": False,
            "http_status": None,
            "api_key_present": api_key_present,
            "error": type(exc).__name__,
        }


def check_local_config_files(bot_dir: Path) -> dict[str, bool]:
    """Report which canonical config files are present (booleans only).

    Never prints file contents. The bot's docs list these names as the
    runtime configs Luis needs to fill in from the ``.example.json``
    templates.
    """
    names = (
        "auftrag.json",
        "contacts.json",
        "blast_auftrag.json",
        "repost_auftrag.json",
        "schedule.json",
    )
    return {name: (bot_dir / name).is_file() for name in names}


def build_preflight_report(cfg: RunnerConfig, *, http: Any = None) -> dict[str, Any]:
    """Aggregate every preflight check into one privacy-safe dict.

    Used by ``--preflight`` and exposed so the Mission Control UI can
    (in a future PR) request this same report from the Claw machine
    via a small local HTTP endpoint.
    """
    return {
        "env": {
            "backend_url_set": bool(cfg.base_url),
            "runner_token_set": bool(cfg.runner_token),
            "runner_id": cfg.runner_id,
            "bot_dir": str(cfg.bot_dir),
            "bot_dir_exists": cfg.bot_dir.is_dir(),
            "poll_interval_seconds": cfg.poll_interval_seconds,
            "live_flags": {
                "ALLOW_LIVE_EXTERNAL_ACTIONS": _bool_env("ALLOW_LIVE_EXTERNAL_ACTIONS"),
                "CONFIRM_LIVE_TEST": os.environ.get("CONFIRM_LIVE_TEST") == "YES",
                "MAX_TEST_ACTIONS_is_1": os.environ.get("MAX_TEST_ACTIONS") == "1",
                "DRY_RUN_explicitly_false": os.environ.get("DRY_RUN", "").strip().lower() == "false",
            },
        },
        "python_imports": check_python_imports(),
        "backend": {
            "health": check_backend_reachable(cfg, http=http),
            "runner_token_check": check_backend_token(cfg, http=http),
        },
        "adspower": check_adspower(http=http),
        "config_files": check_local_config_files(cfg.bot_dir),
        "safety": {
            "mass_live_kinds_blocked": True,  # always — by code
            "live_one_requires_three_flags": True,  # always — by code
            "bot_dir_safety_guard_module_present": (cfg.bot_dir / "safety_guard.py").is_file(),
        },
    }


# ── Entrypoint ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint.

    Subcommands (only one allowed at a time):
      (no args)         print config snapshot and exit 0 (no network)
      --poll            start the live poll loop (blocks)
      --preflight       print structured JSON report of every precondition
      --check-adspower  probe AdsPower local API only (no profile open)
    """
    argv = argv if argv is not None else sys.argv[1:]
    cfg = RunnerConfig.from_env()

    if argv and argv[0] == "--poll":
        return _run_poll_loop(cfg)

    if argv and argv[0] == "--preflight":
        report = build_preflight_report(cfg)
        print(json.dumps(report, indent=2, default=str))  # noqa: T201
        # Exit code reflects whether the runner is ready to do anything safe.
        # Backend reachable + runner token accepted + python imports OK =>
        # exit 0 (ready). Anything else => exit 1. The full report is on
        # stdout so the operator (or a future UI panel) can read details.
        ready = (
            report["env"]["backend_url_set"]
            and report["env"]["runner_token_set"]
            and report["env"]["bot_dir_exists"]
            and report["backend"]["health"]["reachable"]
            and report["backend"]["runner_token_check"]["accepted"]
            and all(report["python_imports"].values())
        )
        return 0 if ready else 1

    if argv and argv[0] == "--check-adspower":
        result = check_adspower()
        print(json.dumps(result, indent=2, default=str))  # noqa: T201
        return 0 if result.get("api_reachable") else 1

    print("MSA RT/X Local Runner — configuration check")  # noqa: T201
    print("--------------------------------------------")  # noqa: T201
    print(f"  MSA_RTXRT_BOT_DIR:                  {cfg.bot_dir}")  # noqa: T201
    print(f"  MSA_RTXRT_BACKEND_URL:              {cfg.base_url or '<unset>'}")  # noqa: T201
    print(f"  MSA_RTXRT_RUNNER_TOKEN:             {'<set>' if cfg.runner_token else '<unset>'}")  # noqa: T201
    print(f"  MSA_RTXRT_RUNNER_ID:                {cfg.runner_id}")  # noqa: T201
    print(f"  MSA_RTXRT_POLL_INTERVAL_SECONDS:    {cfg.poll_interval_seconds}")  # noqa: T201
    for key in ("ALLOW_LIVE_EXTERNAL_ACTIONS", "CONFIRM_LIVE_TEST", "MAX_TEST_ACTIONS", "DRY_RUN"):
        print(f"  {key}: {os.environ.get(key, '<unset>')}")  # noqa: T201
    print()  # noqa: T201
    print("Supported job kinds (dry-run):")  # noqa: T201
    for kind in DRY_RUN_KINDS:
        script, args = _DRY_RUN_COMMANDS[kind]
        print(f"  {kind}: {script} {shlex.join(args)}")  # noqa: T201
    print()  # noqa: T201
    print("Supported job kinds (live-one — owner-gated, safety-gated):")  # noqa: T201
    for kind in LIVE_ONE_KINDS:
        script, args = _LIVE_ONE_COMMANDS[kind]
        print(f"  {kind}: {script} {shlex.join(args)}")  # noqa: T201
    print()  # noqa: T201
    print("Run with --poll to start the live poll loop.")  # noqa: T201
    print("Mass live runs: BLOCKED by design.")  # noqa: T201
    return 0


def _run_poll_loop(cfg: RunnerConfig) -> int:  # pragma: no cover - exercised manually
    if not cfg.base_url:
        print("MSA_RTXRT_BACKEND_URL is required to --poll", file=sys.stderr)  # noqa: T201
        return 2
    if not cfg.runner_token:
        print("MSA_RTXRT_RUNNER_TOKEN is required to --poll", file=sys.stderr)  # noqa: T201
        return 2
    print(  # noqa: T201
        f"Polling {cfg.base_url}/api/v1/msa-rtxrt/runner/poll every "
        f"{cfg.poll_interval_seconds}s as {cfg.runner_id}…"
    )
    while True:
        try:
            result = poll_once(cfg)
            if result is not None:
                print(f"  job → {result}")  # noqa: T201
        except Exception as exc:  # noqa: BLE001 - never let one bad iteration kill the loop
            print(f"  poll error: {exc!r}", file=sys.stderr)  # noqa: T201
        time.sleep(cfg.poll_interval_seconds)


# Provide a wired-up ``run_job`` for tests + future backend wiring. Lives
# at module scope (no side effects) so callers can import it without
# starting the poll loop.
def run_job(
    kind: str,
    *,
    bot_dir: Path | None = None,
    env: dict[str, str] | None = None,
    timeout_seconds: int = 600,
) -> subprocess.CompletedProcess[str]:
    """Run the local command for ``kind`` synchronously and return the result.

    Honors the safety gate via :func:`build_command`. Never invokes
    ``shell=True``. Captures stdout + stderr for the caller to report
    back to Mission Control.
    """
    env = env if env is not None else dict(os.environ)
    resolved_dir = bot_dir if bot_dir is not None else resolve_bot_dir(env)
    cmd = build_command(kind, resolved_dir, env=env)
    return subprocess.run(  # noqa: S603 - argv list, no shell.
        cmd,
        cwd=resolved_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
