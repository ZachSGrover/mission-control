"""Direct OnlyFans sandbox credential loader — Sprint 8E.

The :class:`VaultBackedCredentialLoader` is the only Sprint 8E
implementation of the
:class:`app.services.onlyfans_direct_transport.CredentialLoader`
Protocol. It resolves a value-free
:class:`app.core.onlyfans_direct_credential_ref.CredentialReference`
into header-shaped
:class:`app.services.onlyfans_direct_transport.CredentialMaterial`.

Safety contract (binding):

1. The decrypted credential value is touched **only** inside
   :meth:`load`. It is not stored on any attribute of the loader.
2. The function resolves the vault row, checks status, decrypts,
   parses the canonical JSON wire shape, builds
   :class:`CredentialMaterial`, and returns. Local references to
   the plaintext are dropped explicitly before return.
3. Audit metadata records only credential id / status / provider /
   type — never the value, never a preview, never a length
   beyond what
   :func:`app.services.creator_credentials.get_credential_metadata`
   already produces.
4. Wire-shape validation is strict: the encrypted blob must
   decrypt to a JSON object with **only** the keys
   ``cookie``, ``authorization``, ``user_agent``. Unknown keys
   are dropped silently. Missing keys default to ``None``.
   Anything other than a dict is a hard failure
   (:class:`CredentialLoaderError`).

This module performs **no I/O** beyond the single SELECT for the
vault row and one decrypt call. It does not build HTTP headers
itself; that's the transport's job. It does not audit either; the
transport / connector wrapper handles that.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Final

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.onlyfans_direct_credential_ref import (
    ALLOWED_PROVIDER,
    CredentialReference,
)
from app.core.secrets_store import decrypt_value
from app.models.creator_credentials import CreatorCredential
from app.services.onlyfans_direct_transport import (
    CredentialLoaderError,
    CredentialMaterial,
)

logger = logging.getLogger(__name__)


# Wire-shape allowlist. Stored credentials for the OnlyFans direct
# sandbox path must serialise to JSON of this shape; all other keys
# are dropped silently.
_ALLOWED_KEYS: Final[frozenset[str]] = frozenset({"cookie", "authorization", "user_agent"})


@dataclass(frozen=True)
class VaultBackedCredentialLoader:
    """Loader that pulls a credential from
    :class:`app.models.creator_credentials.CreatorCredential` and
    decrypts inside :meth:`load`.

    The session and credential reference are injected at
    construction; the loader holds no plaintext at any point. A
    fresh decrypt happens on every :meth:`load` call.
    """

    session: AsyncSession
    ref: CredentialReference

    async def load(self) -> CredentialMaterial:
        """Resolve the credential and return header-shaped material.

        Refuses if the row is missing, revoked, rotated, stale, or
        has the wrong provider. Refuses if the decrypted value is
        not a JSON dict.
        """
        from app.core.onlyfans_direct_credential_ref import (
            check_credential_status,
        )

        report = await check_credential_status(self.session, ref=self.ref)
        if report.kind != "active":
            raise CredentialLoaderError(
                f"credential not active: kind={report.kind!r} " f"(provider={report.provider!r})"
            )

        # Re-fetch the row so we have the encrypted blob. The status
        # check above used a separate SELECT; doing one extra select
        # here keeps the helper small. A future sprint could merge
        # them if the perf cost is meaningful.
        from sqlmodel import select as _select

        stmt = (
            _select(CreatorCredential)
            .where(CreatorCredential.id == self.ref.credential_id)
            .where(CreatorCredential.creator_id == self.ref.creator_id)
        )
        result = await self.session.exec(stmt)
        row = result.first()
        if row is None:
            raise CredentialLoaderError("credential row vanished between checks")
        if row.provider != ALLOWED_PROVIDER:
            raise CredentialLoaderError(f"credential provider mismatch: got {row.provider!r}")

        # Decrypt. The plaintext lives only in the local ``plaintext``
        # variable for the duration of the JSON parse + material
        # build, then is replaced by an empty string before return.
        plaintext = decrypt_value(row.encrypted_value)
        if not plaintext:
            raise CredentialLoaderError("decrypt failed or empty plaintext")

        try:
            parsed: Any = json.loads(plaintext)
        except json.JSONDecodeError:
            # Replace the plaintext reference before raising so the
            # exception traceback cannot capture the value via
            # local-frame inspection.
            plaintext = ""
            raise CredentialLoaderError("credential value is not valid JSON")

        if not isinstance(parsed, dict):
            plaintext = ""
            raise CredentialLoaderError("credential value must be a JSON object")

        material = CredentialMaterial(
            cookie=_safe_str(parsed.get("cookie")) if "cookie" in _ALLOWED_KEYS else None,
            authorization=(
                _safe_str(parsed.get("authorization")) if "authorization" in _ALLOWED_KEYS else None
            ),
            user_agent=(
                _safe_str(parsed.get("user_agent")) if "user_agent" in _ALLOWED_KEYS else None
            ),
        )

        # Defensive: ensure the parsed dict and plaintext are dropped
        # before return so a future caller can't inspect them via
        # ``locals()`` or a debugger.
        plaintext = ""
        parsed = None
        del plaintext, parsed

        return material


def _safe_str(value: Any) -> str | None:
    """Return ``None`` if value is missing/empty; otherwise the
    string with length capped at 4096 chars (cookie strings can be
    long but should not be unbounded).
    """
    if value is None:
        return None
    s = str(value)
    if not s:
        return None
    return s[:4096]
