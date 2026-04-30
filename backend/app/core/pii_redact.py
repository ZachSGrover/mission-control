"""PII redaction for outbound LLM prompts.

Distinct from :mod:`app.core.redact` — that module is for audit
*metadata*. **This** module is for prompt *content* about to leave the
process for a third-party LLM API.

Goals (Sprint 3):
- Strip obvious credential / token / API-key shaped substrings.
- Strip email addresses and phone numbers (the most reliable PII shape
  for the kind of data Mission Control actually handles).
- Strip ``Bearer …`` / ``Basic …`` headers if a caller pasted one.
- Do **not** destroy normal business utility — short identifiers like
  "creator-A" or "FY24Q1" stay intact.

Non-goals:
- Full PII redaction. Names, addresses, free-text identifiers, and
  message bodies are out of scope. The goal is to reduce the worst
  surface (credentials + structured PII), not pretend we have
  enterprise-grade DLP.

Usage::

    safe_prompt, was_redacted, marker_count = redact_for_llm(prompt)
    # Caller can audit ``was_redacted`` without ever logging the
    # original ``prompt``.
"""

from __future__ import annotations

import re
from typing import Final

REDACTED_MARKER: Final[str] = "[REDACTED]"

# Order matters: token / key patterns first so they don't get partially
# redacted by a less-specific pattern further down. Each pattern is
# *intentionally* conservative — false negatives are preferred over
# false positives, because over-redacting destroys utility.
_PATTERNS: Final[list[tuple[str, re.Pattern[str]]]] = [
    # Bearer / Basic auth headers (with at least 16 chars of token).
    ("auth_header", re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9_\-\./+=]{16,}", re.I)),
    # OpenAI sk-..., GitHub ghp_/gho_/ghr_/ghs_, AWS AKIA, Slack xoxb-/xoxp-/xoxa-,
    # Stripe sk_live_/pk_live_/sk_test_/pk_test_, Anthropic sk-ant-..., Google AIza,
    # Twilio AC..., SendGrid SG..., Mailchimp md-XXXXXXXX (server-prefix tokens),
    # generic 'X-API-Key:' and 'token=' patterns.
    (
        "vendor_key",
        re.compile(
            r"\b(?:"
            r"sk-ant-[A-Za-z0-9_\-]{20,}|"  # Anthropic
            r"sk-[A-Za-z0-9]{20,}|"  # OpenAI
            r"sk_live_[A-Za-z0-9]{20,}|sk_test_[A-Za-z0-9]{20,}|"  # Stripe secret
            r"pk_live_[A-Za-z0-9]{20,}|pk_test_[A-Za-z0-9]{20,}|"  # Stripe public
            r"gh[psour]_[A-Za-z0-9]{30,}|"  # GitHub PATs / install / oauth / refresh / server
            r"AKIA[0-9A-Z]{16}|"  # AWS access key id
            r"xox[bpaors]-[A-Za-z0-9-]{10,}|"  # Slack
            r"AIza[0-9A-Za-z_\-]{35}|"  # Google
            r"AC[a-f0-9]{32}|"  # Twilio Account SID
            r"SG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"  # SendGrid
            r")\b"
        ),
    ),
    # X-API-Key / Authorization-style header pairs (catches "X-API-Key: abc...").
    (
        "header_pair",
        re.compile(
            r"(?i)\b(?:x[-_]api[-_]?key|api[-_]?key|authorization)\s*[:=]\s*[A-Za-z0-9_\-\./+=]{12,}"
        ),
    ),
    # JWT-shaped triple-segment tokens.
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    ),
    # Sprint 5: structured ``name:`` / ``Name:`` labels followed by a
    # plausible person-name. Conservative — requires the explicit label
    # so business strings like "creator:Aria" survive untouched.
    # Same-line only: name parts are joined by ``[ \t]+`` (not ``\s+``)
    # so a newline ends the match and a label on a separate line from
    # its value is treated as two distinct concerns.
    (
        "labelled_name",
        re.compile(
            r"(?im)\b(?:full[ \t_-]?name|first[ \t_-]?name|last[ \t_-]?name|name)"
            r"[ \t]*[:=][ \t]*[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3}"
        ),
    ),
    # Sprint 5: street addresses — number + street + suffix. Keeps the
    # match conservative: must start with a 1-5 digit number, then a
    # capitalised street name, then a known suffix (St / Street / Rd /
    # Road / Ave / Avenue / Blvd / Boulevard / Ln / Lane / Dr / Drive /
    # Ct / Court / Way / Pl / Place).
    (
        "street_address",
        re.compile(
            r"\b\d{1,5}\s+[A-Z][A-Za-z0-9.'\- ]{1,40}?\s+"
            r"(?:St(?:reet)?|Rd|Road|Ave(?:nue)?|Blvd|Boulevard|Ln|Lane|Dr(?:ive)?|"
            r"Ct|Court|Way|Pl|Place)\b\.?",
        ),
    ),
    # Email addresses.
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # Phone numbers — conservative: at least 10 digits, optional +/spaces/-/parens.
    (
        "phone",
        re.compile(r"(?:\+?\d[\d\s\-\(\)]{8,}\d)"),
    ),
    # Long opaque hex / base64 strings >= 32 chars (catches loose API
    # keys not matched above). Letters+digits only; pure-digit runs are
    # excluded so order numbers don't trigger this.
    (
        "long_token",
        re.compile(r"\b(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}\b"),
    ),
]


def redact_for_llm(text: str) -> tuple[str, bool, dict[str, int]]:
    """Return a redacted copy of ``text`` plus metadata about what changed.

    The third element is a per-category count of how many substrings
    were redacted, e.g. ``{"email": 2, "phone": 1}``. Useful for
    auditing "was redaction applied?" without ever logging the
    original text.

    The original ``text`` is not mutated; a new string is returned.
    """
    if not text:
        return text, False, {}

    counts: dict[str, int] = {}
    redacted = text
    for label, pattern in _PATTERNS:
        if not pattern.search(redacted):
            continue
        new_text, n = pattern.subn(REDACTED_MARKER, redacted)
        if n:
            counts[label] = counts.get(label, 0) + n
            redacted = new_text

    return redacted, bool(counts), counts
