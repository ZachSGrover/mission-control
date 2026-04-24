"""Git Save — stage, commit, and push to origin/main from the backend."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import AuthContext, get_auth_context
from app.core.config import settings
from app.core.secrets_store import GITHUB_KEYS, get_secret
from app.db.session import get_session

router = APIRouter(prefix="/git", tags=["git"])
AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)
logger = logging.getLogger(__name__)

# Repo root is 3 levels up from this file:
# backend/app/api/git_save.py → backend/app/api → backend/app → backend → repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


# ── Schemas ───────────────────────────────────────────────────────────────────


class SaveResponse(BaseModel):
    status: str  # "saved" | "no_changes" | "error"
    message: str
    files_changed: int = 0
    commit_hash: str = ""
    error: str = ""


class ChangedFile(BaseModel):
    path: str
    status: str  # "modified" | "added" | "deleted" | "renamed" | "untracked" | "other"


class SuspiciousFile(BaseModel):
    path: str
    reason: str


class PreviewResponse(BaseModel):
    branch: str
    remote: str  # sanitized — no tokens
    willPushBranch: str
    changedFiles: list[ChangedFile]
    statusSummary: str
    diffStat: str
    commitMessage: str
    hasChanges: bool
    suspiciousFiles: list[SuspiciousFile]
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


def _push_url(pat: str, username: str, repo: str) -> str:
    """Build the push URL from resolved credentials."""
    if pat and username and repo:
        return f"https://{username}:{pat}@github.com/{repo}.git"
    return "origin"


def _sanitize_remote(url: str) -> str:
    """Strip any embedded credentials from a remote URL for safe display."""
    if not url:
        return ""
    u = url.strip()
    if u.startswith("https://") or u.startswith("http://"):
        scheme, rest = u.split("://", 1)
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        if rest.endswith(".git"):
            rest = rest[:-4]
        return rest
    if u.startswith("git@"):
        rest = u[len("git@"):]
        # git@github.com:user/repo.git → github.com/user/repo
        rest = rest.replace(":", "/", 1)
        if rest.endswith(".git"):
            rest = rest[:-4]
        return rest
    # Unknown scheme — return as-is but trim .git
    return u[:-4] if u.endswith(".git") else u


_PORCELAIN_STATUS = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "U": "unmerged",
    "?": "untracked",
    "!": "ignored",
}


def _parse_porcelain(line: str) -> ChangedFile | None:
    """Parse one line of `git status --porcelain` output."""
    if len(line) < 3:
        return None
    # Two-char status code + space + path
    x, y = line[0], line[1]
    path = line[3:].strip()
    # Strip any quoting git adds for paths with spaces
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    # For renames, path is "old -> new"; keep the new name
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    code = x if x != " " else y
    status = _PORCELAIN_STATUS.get(code, "other")
    return ChangedFile(path=path, status=status)


def _detect_suspicious(path: str) -> str | None:
    p = path.lower()
    if p == ".env" or p.startswith(".env.") or "/.env" in p:
        return ".env file — may contain secrets"
    if "node_modules/" in p or p == "node_modules":
        return "node_modules — large build dependency"
    if p.startswith(".next/") or "/.next/" in p:
        return ".next build artifact"
    if p.endswith(".log") or "/logs/" in p or p.startswith("logs/"):
        return "log file"
    for term in ("credential", "secret", "token", "password", "apikey", "api_key", "private_key"):
        if term in p:
            return f"path contains '{term}'"
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/preview", response_model=PreviewResponse)
async def git_preview(_auth: AuthContext = AUTH_DEP) -> PreviewResponse:
    """Read-only: report what `POST /git/save` *would* commit and push.

    Performs only git queries (`status`, `diff`, `rev-parse`, `remote`). Does
    not run `add`, `commit`, or `push`. Remote URL is sanitized — any embedded
    token is stripped before returning.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_preview)


def _do_preview() -> PreviewResponse:
    # Verify git is available
    rc, _, _ = _git("--version")
    if rc != 0:
        return PreviewResponse(
            branch="",
            remote="",
            willPushBranch="main",
            changedFiles=[],
            statusSummary="",
            diffStat="",
            commitMessage="",
            hasChanges=False,
            suspiciousFiles=[],
            error="git is not available",
        )

    # Current branch
    _, branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")

    # Remote URL (sanitized)
    _, remote_raw, _ = _git("remote", "get-url", "origin")
    remote = _sanitize_remote(remote_raw)

    # Changed files via porcelain
    _, status_out, _ = _git("status", "--porcelain")
    changed: list[ChangedFile] = []
    for line in status_out.splitlines():
        parsed = _parse_porcelain(line)
        if parsed is not None:
            changed.append(parsed)

    # Ahead/behind from --branch output
    _, branch_status, _ = _git("status", "--branch", "--porcelain")
    has_unpushed = "ahead" in branch_status

    has_changes = bool(changed) or has_unpushed

    # Diff stat — show both staged and unstaged changes vs HEAD
    _, diff_stat, _ = _git("diff", "HEAD", "--stat")
    if not diff_stat:
        _, diff_stat, _ = _git("diff", "--stat")

    # Summary
    counts: dict[str, int] = {}
    for cf in changed:
        counts[cf.status] = counts.get(cf.status, 0) + 1
    if counts:
        status_summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
    elif has_unpushed:
        status_summary = "working tree clean, unpushed commits ahead"
    else:
        status_summary = "no changes"

    # Commit message — exactly what /save would use
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_message = f"mission control save - {timestamp}"

    # Suspicious file detection
    suspicious: list[SuspiciousFile] = []
    for cf in changed:
        reason = _detect_suspicious(cf.path)
        if reason is not None:
            suspicious.append(SuspiciousFile(path=cf.path, reason=reason))

    return PreviewResponse(
        branch=branch or "HEAD",
        remote=remote,
        willPushBranch="main",
        changedFiles=changed,
        statusSummary=status_summary,
        diffStat=diff_stat,
        commitMessage=commit_message,
        hasChanges=has_changes,
        suspiciousFiles=suspicious,
    )


@router.post("/save", response_model=SaveResponse)
async def git_save(
    _auth: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> SaveResponse:
    """Stage all safe changes, commit with timestamp, and push to origin/main."""
    # Resolve credentials: DB takes priority over .env
    pat = await get_secret(session, GITHUB_KEYS["github_pat"], fallback=settings.github_pat)
    username = await get_secret(
        session, GITHUB_KEYS["github_username"], fallback=settings.github_username
    )
    repo = await get_secret(session, GITHUB_KEYS["github_repo"], fallback=settings.github_repo)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_save, pat.strip(), username.strip(), repo.strip())


def _do_save(pat: str, username: str, repo: str) -> SaveResponse:
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
            "-m",
            commit_msg,
            "--author",
            "Zachary Grover <hq@digidle.com>",
        )
        if rc != 0 and "nothing to commit" not in stderr and "nothing to commit" not in commit_out:
            logger.error("[git_save] git commit failed: %s", stderr)
            return SaveResponse(status="error", message="Commit failed", error=stderr)

    # ── 5. Get commit hash ────────────────────────────────────────────────────
    _, commit_hash, _ = _git("rev-parse", "--short", "HEAD")

    # ── 6. Push ───────────────────────────────────────────────────────────────
    push_target = _push_url(pat, username, repo)
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
