"""Public-secret guardrail.

Sprint 5: a test that scans the frontend source tree for env-var names
that would leak into the client bundle if set. Catches the
``NEXT_PUBLIC_*`` family of footguns flagged in Sprint 3:

- ``NEXT_PUBLIC_LOCAL_AUTH_TOKEN`` is allowlisted because the build-
  time fallback is a known dev convenience with a runtime guard
  in ``frontend/src/auth/localAuth.ts``.
- ``NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`` is allowlisted because Clerk's
  publishable key is, by design, public.
- Anything else matching ``NEXT_PUBLIC_*(SECRET|TOKEN|PASSWORD|KEY)``
  beyond the allowlist fails the test.

The test runs as part of the regular ``pytest`` invocation so CI
catches new footguns at the earliest gate.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# Names of NEXT_PUBLIC_* vars that we have explicitly accepted as
# safe-to-be-public OR documented as dev-only with a runtime guard.
ALLOWLIST: frozenset[str] = frozenset(
    {
        "NEXT_PUBLIC_LOCAL_AUTH_TOKEN",  # dev fallback; runtime-guarded in localAuth.ts
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",  # Clerk publishable key — public by design
        "NEXT_PUBLIC_AUTH_MODE",
        "NEXT_PUBLIC_API_URL",
        "NEXT_PUBLIC_APP_URL",
        "NEXT_PUBLIC_WS_URL",
        "NEXT_PUBLIC_FRONTEND_URL",
        "NEXT_PUBLIC_ENV",
        "NEXT_PUBLIC_GIT_SHA",
        "NEXT_PUBLIC_GATEWAY_TOKEN_PROMPT",  # UI hint string; not an actual token
        "NEXT_PUBLIC_OPENCLAW_TOKEN",  # OpenClaw browser-side ws token (separate scope)
        "NEXT_PUBLIC_OPENCLAW_SESSION",
        "NEXT_PUBLIC_OPENCLAW_WS_URL",
        "NEXT_PUBLIC_SKIP_ONBOARDING",
        "NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL",
        "NEXT_PUBLIC_CLERK_AFTER_SIGN_OUT_URL",
        "NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL",
        "NEXT_PUBLIC_CLERK_SIGN_IN_URL",
        "NEXT_PUBLIC_CLERK_SIGN_UP_URL",
    }
)

# The pattern that identifies a "public secret-shaped" var name.
SUSPICIOUS_NAME = re.compile(r"NEXT_PUBLIC_[A-Z0-9_]*?(?:SECRET|TOKEN|PASSWORD|KEY)[A-Z0-9_]*")


def _scan_for_public_var_references() -> set[str]:
    """Return the set of ``NEXT_PUBLIC_*`` names referenced in frontend source."""
    if not FRONTEND_SRC.exists():
        return set()
    found: set[str] = set()
    for path in FRONTEND_SRC.rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover — defensive
            continue
        for match in re.finditer(r"\bNEXT_PUBLIC_[A-Z0-9_]+", text):
            found.add(match.group(0))
    return found


def test_no_unallowlisted_public_secret_shaped_env_vars() -> None:
    """Fail if a frontend file references a ``NEXT_PUBLIC_*`` env var
    whose name looks secret-shaped and is not in the explicit allowlist.

    A failure here means: someone added a `NEXT_PUBLIC_*_SECRET` or
    `NEXT_PUBLIC_*_TOKEN` reference that hasn't been reviewed for
    "this is OK to ship to every visitor in the bundle." Add it to the
    allowlist with a one-line justification *or* refactor the code to
    fetch the value from the server.
    """
    referenced = _scan_for_public_var_references()
    suspicious = {name for name in referenced if SUSPICIOUS_NAME.match(name)}
    unreviewed = suspicious - ALLOWLIST
    assert not unreviewed, (
        "Frontend references suspicious NEXT_PUBLIC_* variables that are not "
        "on the public-secret allowlist. Either (a) add them to the allowlist "
        f"in {Path(__file__).name} with a justification, or (b) refactor to "
        f"fetch the value from the server. Offenders: {sorted(unreviewed)}"
    )


def test_allowlist_does_not_drift_to_unknown_names() -> None:
    """Sanity: every name in the allowlist must look like a NEXT_PUBLIC var."""
    for name in ALLOWLIST:
        assert name.startswith("NEXT_PUBLIC_"), name
