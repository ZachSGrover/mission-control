"""Git Save — stage, commit, and push to origin/main from the backend."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import AuthContext, get_auth_context
from app.core.config import settings

router = APIRouter(prefix="/git", tags=["git"])
AUTH_DEP = Depends(get_auth_context)
logger = logging.getLogger(__name__)

# Repo root is 3 levels up from this file:
# backend/app/api/git_save.py → backend/app/api → backend/app → backend → repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


# ── Schemas ───────────────────────────────────────────────────────────────────

class SaveResponse(BaseModel):
    status: str          # "saved" | "no_changes" | "error"
    message: str
    files_changed: int = 0
    commit_hash: str = ""
    error: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(args: list[str], *, env: dict | None = None) -> tuple[int, str, str]:
    """Run a git command synchronously, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        args,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _git(*args: str, env: dict | None = None) -> tuple[int, str, str]:
    return _run(["git", *args], env=env)


def _push_url() -> str:
    """Build the push URL. Uses PAT from settings if configured."""
    pat = (settings.github_pat or "").strip()
    username = (settings.github_username or "").strip()
    repo = (settings.github_repo or "").strip()

    if pat and username and repo:
        return f"https://{username}:{pat}@github.com/{repo}.git"
    # Fall back to origin — credential helper must be configured
    return "origin"


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/save", response_model=SaveResponse)
async def git_save(_auth: AuthContext = AUTH_DEP) -> SaveResponse:
    """Stage all safe changes, commit with timestamp, and push to origin/main."""

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_save)


def _do_save() -> SaveResponse:
    # ── 1. Verify git is available ────────────────────────────────────────────
    rc, _, _ = _git("--version")
    if rc != 0:
        return SaveResponse(status="error", message="git is not available", error="git not found")

    # ── 2. Check for changes ──────────────────────────────────────────────────
    rc, status_out, _ = _git("status", "--porcelain")
    has_working_changes = bool(status_out.strip())

    # Check for unpushed commits even if working tree is clean
    rc2, ahead_out, _ = _git("status", "--branch", "--porcelain")
    has_unpushed = "ahead" in ahead_out

    if not has_working_changes and not has_unpushed:
        logger.info("[git_save] nothing to save")
        return SaveResponse(status="no_changes", message="Nothing to save — already up to date.")

    files_changed = 0

    if has_working_changes:
        # ── 3. Stage all safe files (gitignore is respected by git add) ───────
        rc, _, stderr = _git("add", "-A")
        if rc != 0:
            logger.error("[git_save] git add failed: %s", stderr)
            return SaveResponse(status="error", message="Failed to stage files", error=stderr)

        # Count staged files
        rc, diff_out, _ = _git("diff", "--cached", "--name-only")
        files_changed = len([f for f in diff_out.splitlines() if f.strip()])

        # ── 4. Commit ─────────────────────────────────────────────────────────
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_msg = f"mission control save - {timestamp}"

        rc, commit_out, stderr = _git(
            "commit",
            "-m", commit_msg,
            "--author", "Zachary Grover <hq@digidle.com>",
        )
        if rc != 0 and "nothing to commit" not in stderr and "nothing to commit" not in commit_out:
            logger.error("[git_save] git commit failed: %s", stderr)
            return SaveResponse(status="error", message="Commit failed", error=stderr)

    # ── 5. Get commit hash ────────────────────────────────────────────────────
    _, commit_hash, _ = _git("rev-parse", "--short", "HEAD")

    # ── 6. Push ───────────────────────────────────────────────────────────────
    push_target = _push_url()
    push_args = [push_target, "main"] if push_target != "origin" else ["origin", "main"]

    rc, push_out, push_err = _git("push", *push_args)

    if rc != 0:
        # Provide helpful error for auth failures
        if "could not read Username" in push_err or "Authentication failed" in push_err:
            hint = (
                "Push authentication failed. "
                "Add GITHUB_PAT, GITHUB_USERNAME, and GITHUB_REPO to backend/.env "
                "to enable automatic push."
            )
            logger.error("[git_save] push auth failed")
            return SaveResponse(
                status="error",
                message=hint,
                files_changed=files_changed,
                commit_hash=commit_hash,
                error=push_err,
            )

        logger.error("[git_save] push failed: %s", push_err)
        return SaveResponse(
            status="error",
            message=f"Committed locally but push failed: {push_err}",
            files_changed=files_changed,
            commit_hash=commit_hash,
            error=push_err,
        )

    logger.info("[git_save] saved — %d file(s) — commit %s", files_changed, commit_hash)
    return SaveResponse(
        status="saved",
        message=f"Saved to GitHub ({files_changed} file{'s' if files_changed != 1 else ''} · {commit_hash})",
        files_changed=files_changed,
        commit_hash=commit_hash,
    )
