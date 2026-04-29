"""Chat-message QC engine — text-based rules over imported messages.

Operates on `of_intelligence_messages` rows scoped to a single import
batch (`import_id`).  Every rule is a deterministic, dependency-free
Python heuristic — **no LLM calls, no external network**.

This engine is distinct from `chatter_qc.py` (which works off
`of_intelligence_user_metrics` aggregates).  The two complement each
other:
  • `chatter_qc.py`   — quantitative, per-chatter, OnlyMonster-driven.
  • `chat_message_qc.py` — qualitative, per-message, requires text.

Each finding carries:
  rule_id, severity, title, issue, why_it_matters, suggested_better,
  recommended_action, message_excerpt (≤ 280 chars), context (json).

Limitations (intentional, documented for the UI):
  • All "suggested better response" templates are canned per rule.  An
    LLM upgrade can replace these without changing call sites.
  • Heuristics are conservative — false negatives are preferred over
    false positives so operators don't get spam-flagged.
  • Sentiment / tone / "robotic feel" detection uses surface signals
    (length, casing, punctuation, repetition).  Real semantic checks
    arrive when an LLM is wired.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceChatQcFinding,
    OfIntelligenceMessage,
)

logger = logging.getLogger(__name__)

# ── Tunables (constants — easy to override in tests) ─────────────────────────

LOW_EFFORT_MAX_CHARS = 8  # ≤ 8 chars on an OUT message → "low effort"
LOW_EFFORT_PHRASES = {
    "ok",
    "k",
    "kk",
    "lol",
    "lmao",
    "yeah",
    "yep",
    "yes",
    "no",
    "haha",
    "hahaha",
    "nice",
    "cool",
    "sure",
    "yup",
    "nah",
    "mhm",
    "thx",
    "ty",
}
TOO_AGGRESSIVE_CAPS_RATIO = 0.6  # ≥ 60 % uppercase letters
TOO_AGGRESSIVE_EXCLAIM_COUNT = 3  # ≥ 3 "!" in one message
ROBOTIC_GREETINGS = (
    "hey babe how are you",
    "hi babe how are you",
    "hey honey how are you",
    "hello how are you doing",
    "what's up babe",
    "whats up babe",
)
COPY_PASTE_MIN_LEN = 25  # ignore short utterances when matching
TOO_PASSIVE_NO_QUESTION_THRESHOLD = 3  # ≥ 3 OUTs in a row with no "?" / CTA
MOMENTUM_KILLER_AFTER_SECONDS = 6 * 3600  # silent for 6h after a chatter msg
MISSED_UPSELL_KEYWORDS = (
    "show me",
    "send",
    "see more",
    "more pics",
    "more videos",
    "vault",
    "ppv",
    "what do you have",
    "any pics",
    "any vids",
    "naughty",
    "spicy",
)
OBJECTION_KEYWORDS = (
    "too expensive",
    "expensive",
    "broke",
    "no money",
    "can't afford",
    "cant afford",
    "not now",
    "later",
    "maybe later",
    "next week",
)
NEEDS_REVIEW_RULES = {"too_aggressive", "needs_manager_review"}

# Keep excerpts compact — never echo a full long message.
EXCERPT_MAX_CHARS = 280

# Crude grammar / English-quality patterns.  These are deliberately
# conservative — only fire on obvious patterns.
DOUBLE_SPACE_RE = re.compile(r"  +")
REPEATED_PUNCT_RE = re.compile(r"([!?.])\1{2,}")  # "!!!", "???", "..."  (we
# ignore "..." since that's
# idiomatic in DMs)
NO_TERMINATING_PUNCT_RE = re.compile(r"[a-zA-Z0-9]\s*$")


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class MessageView:
    """Lightweight, immutable view used for rule evaluation.

    Avoids passing SQLModel rows directly so each rule is testable with
    dataclasses and we don't accidentally mutate ORM state.
    """

    id: UUID
    source: str
    source_id: str
    chat_source_id: str | None
    account_source_id: str | None
    fan_source_id: str | None
    chatter_source_id: str | None
    direction: str | None
    sent_at: datetime | None
    body: str


@dataclass
class Finding:
    rule_id: str
    severity: str
    title: str
    issue: str
    why_it_matters: str
    suggested_better: str | None
    recommended_action: str | None
    message: MessageView
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class QcRunSummary:
    import_id: UUID | None
    evaluated_at: datetime
    messages_evaluated: int
    findings_created: int
    findings_by_severity: dict[str, int]
    findings_by_rule: dict[str, int]


# ── Public entrypoint ────────────────────────────────────────────────────────


async def run_qc_for_import(
    session: AsyncSession,
    import_id: UUID,
    *,
    persist: bool = True,
) -> QcRunSummary:
    """Run all rules against every message attached to `import_id`."""
    rows = (
        await session.exec(
            select(OfIntelligenceMessage)
            .where(OfIntelligenceMessage.import_id == import_id)
            .order_by(col(OfIntelligenceMessage.sent_at).asc())
        )
    ).all()
    return await _run_qc(session, list(rows), import_id=import_id, persist=persist)


async def run_qc_all_imported(
    session: AsyncSession,
    *,
    persist: bool = True,
) -> QcRunSummary:
    """Convenience: run QC over every imported (non-null import_id) row."""
    rows = (
        await session.exec(
            select(OfIntelligenceMessage)
            .where(OfIntelligenceMessage.import_id.is_not(None))  # type: ignore[union-attr]
            .order_by(col(OfIntelligenceMessage.sent_at).asc())
        )
    ).all()
    return await _run_qc(session, list(rows), import_id=None, persist=persist)


async def list_findings(
    session: AsyncSession,
    *,
    import_id: UUID | None = None,
    limit: int = 200,
) -> list[OfIntelligenceChatQcFinding]:
    stmt = (
        select(OfIntelligenceChatQcFinding)
        .order_by(col(OfIntelligenceChatQcFinding.created_at).desc())
        .limit(limit)
    )
    if import_id is not None:
        stmt = stmt.where(OfIntelligenceChatQcFinding.import_id == import_id)
    rows = (await session.exec(stmt)).all()
    return list(rows)


# ── Engine internals ─────────────────────────────────────────────────────────


async def _run_qc(
    session: AsyncSession,
    messages: list[OfIntelligenceMessage],
    *,
    import_id: UUID | None,
    persist: bool,
) -> QcRunSummary:
    if persist and import_id is not None:
        # Wipe prior findings for this import so a re-run gives a clean slate.
        await _delete_findings_for_import(session, import_id)

    views: list[MessageView] = [
        MessageView(
            id=m.id,
            source=m.source,
            source_id=m.source_id,
            chat_source_id=m.chat_source_id,
            account_source_id=m.account_source_id,
            fan_source_id=m.fan_source_id,
            chatter_source_id=m.chatter_source_id,
            direction=m.direction,
            sent_at=m.sent_at,
            body=m.body or "",
        )
        for m in messages
        if (m.body or "").strip()
    ]

    findings: list[Finding] = []
    findings.extend(_rule_low_effort_replies(views))
    findings.extend(_rule_robotic_replies(views))
    findings.extend(_rule_too_aggressive(views))
    findings.extend(_rule_too_passive(views))
    findings.extend(_rule_bad_english(views))
    findings.extend(_rule_bad_grammar(views))
    findings.extend(_rule_wrong_tone(views))
    findings.extend(_rule_copy_paste_feel(views))
    findings.extend(_rule_missed_upsell(views))
    findings.extend(_rule_bad_objection_handling(views))
    findings.extend(_rule_ignored_fan_context(views))
    findings.extend(_rule_momentum_killed(views))
    findings.extend(_rule_needs_manager_review(findings))

    by_sev: Counter[str] = Counter()
    by_rule: Counter[str] = Counter()
    if persist:
        for f in findings:
            session.add(
                OfIntelligenceChatQcFinding(
                    import_id=import_id,
                    message_source_id=f.message.source_id,
                    source=f.message.source,
                    chat_source_id=f.message.chat_source_id,
                    account_source_id=f.message.account_source_id,
                    fan_source_id=f.message.fan_source_id,
                    chatter_source_id=f.message.chatter_source_id,
                    rule_id=f.rule_id,
                    severity=f.severity,
                    title=f.title,
                    issue=f.issue,
                    why_it_matters=f.why_it_matters,
                    suggested_better=f.suggested_better,
                    recommended_action=f.recommended_action,
                    message_excerpt=_excerpt(f.message.body),
                    context=f.context or None,
                )
            )
            by_sev[f.severity] += 1
            by_rule[f.rule_id] += 1
        if findings:
            await session.commit()

        # Sync the import row's findings_count if applicable.
        if import_id is not None:
            from app.models.of_intelligence import OfIntelligenceChatImport

            row = (
                await session.exec(
                    select(OfIntelligenceChatImport).where(OfIntelligenceChatImport.id == import_id)
                )
            ).first()
            if row is not None:
                row.findings_count = len(findings)
                session.add(row)
                await session.commit()
    else:
        for f in findings:
            by_sev[f.severity] += 1
            by_rule[f.rule_id] += 1

    summary = QcRunSummary(
        import_id=import_id,
        evaluated_at=utcnow(),
        messages_evaluated=len(views),
        findings_created=len(findings),
        findings_by_severity=dict(by_sev),
        findings_by_rule=dict(by_rule),
    )
    logger.info(
        "of_intelligence.chat_message_qc.evaluated import_id=%s msgs=%s findings=%s",
        import_id,
        summary.messages_evaluated,
        summary.findings_created,
    )
    return summary


async def _delete_findings_for_import(session: AsyncSession, import_id: UUID) -> None:
    rows = (
        await session.exec(
            select(OfIntelligenceChatQcFinding).where(
                OfIntelligenceChatQcFinding.import_id == import_id
            )
        )
    ).all()
    for r in rows:
        await session.delete(r)
    if rows:
        await session.commit()


# ── Rule helpers ─────────────────────────────────────────────────────────────


def _excerpt(text: str) -> str:
    text = text.strip()
    if len(text) <= EXCERPT_MAX_CHARS:
        return text
    return text[: EXCERPT_MAX_CHARS - 1] + "…"


def _is_out(m: MessageView) -> bool:
    return m.direction == "out"


def _is_in(m: MessageView) -> bool:
    return m.direction == "in"


def _by_chat(views: list[MessageView]) -> dict[str, list[MessageView]]:
    out: dict[str, list[MessageView]] = {}
    for v in views:
        if not v.chat_source_id:
            continue
        out.setdefault(v.chat_source_id, []).append(v)
    for chat in out.values():
        chat.sort(key=lambda m: m.sent_at or datetime.min)
    return out


# ── Rules ────────────────────────────────────────────────────────────────────


def _rule_low_effort_replies(views: list[MessageView]) -> list[Finding]:
    findings: list[Finding] = []
    for v in views:
        if not _is_out(v):
            continue
        body = v.body.strip()
        normalised = re.sub(r"[^a-z0-9 ]", "", body.lower())
        is_short = len(body) <= LOW_EFFORT_MAX_CHARS
        is_filler = normalised in LOW_EFFORT_PHRASES
        if is_short or is_filler:
            findings.append(
                Finding(
                    rule_id="low_effort_reply",
                    severity="warn",
                    title="Low-effort reply",
                    issue="Reply is too short or filler-only.",
                    why_it_matters=(
                        "Short / filler replies kill conversational momentum. "
                        "The fan reads them as disengagement and stops "
                        "spending."
                    ),
                    suggested_better=(
                        "Reply with a personalised line that references the "
                        "fan's last message and ends with a hook (a question, "
                        "a tease, or a soft CTA)."
                    ),
                    recommended_action=(
                        "Coach this chatter on minimum reply standards; flag "
                        "the chat for manager review if it's a paying fan."
                    ),
                    message=v,
                    context={"length": len(body)},
                )
            )
    return findings


def _rule_robotic_replies(views: list[MessageView]) -> list[Finding]:
    findings: list[Finding] = []
    for v in views:
        if not _is_out(v):
            continue
        normalised = re.sub(r"[^a-z ]", "", v.body.lower()).strip()
        if any(g in normalised for g in ROBOTIC_GREETINGS):
            findings.append(
                Finding(
                    rule_id="robotic_reply",
                    severity="warn",
                    title="Robotic / template-feel opener",
                    issue=(
                        "Reply uses a recognisably template opener ('hey babe "
                        "how are you' / 'what's up babe')."
                    ),
                    why_it_matters=(
                        "Repeat fans clock template openers immediately. They "
                        "signal bot-feel and tank perceived intimacy — the "
                        "exact thing they're paying for."
                    ),
                    suggested_better=(
                        "Open with something specific to this chat: reference "
                        "their last message, tease something they bought, or "
                        "open with an observation about their last activity."
                    ),
                    recommended_action="Audit chatter's opener library; rotate / personalise.",
                    message=v,
                )
            )
    return findings


def _rule_too_aggressive(views: list[MessageView]) -> list[Finding]:
    findings: list[Finding] = []
    for v in views:
        if not _is_out(v):
            continue
        letters = [c for c in v.body if c.isalpha()]
        if not letters:
            continue
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        exclaim_count = v.body.count("!")
        too_caps = upper_ratio >= TOO_AGGRESSIVE_CAPS_RATIO and len(letters) >= 8
        too_punctuated = exclaim_count >= TOO_AGGRESSIVE_EXCLAIM_COUNT
        if too_caps or too_punctuated:
            findings.append(
                Finding(
                    rule_id="too_aggressive",
                    severity="critical",
                    title="Too aggressive tone",
                    issue=(
                        "Heavy uppercase or excessive '!' — message reads as " "shouting / pushy."
                    ),
                    why_it_matters=(
                        "Aggressive tone causes fans to disengage and refund. "
                        "It is the single most common cause of complaint "
                        "tickets and chargebacks."
                    ),
                    suggested_better=(
                        "Drop to mixed-case, soften the punctuation, and end "
                        "with a question to give the fan room to respond."
                    ),
                    recommended_action=(
                        "Manager review immediately; pause this chatter from "
                        "high-value chats until coached."
                    ),
                    message=v,
                    context={
                        "uppercase_ratio": round(upper_ratio, 2),
                        "exclaim_count": exclaim_count,
                    },
                )
            )
    return findings


def _rule_too_passive(views: list[MessageView]) -> list[Finding]:
    """Three OUT messages in a row in the same chat with no '?' and no CTA."""
    findings: list[Finding] = []
    for chat_id, chat in _by_chat(views).items():
        run: list[MessageView] = []
        for v in chat:
            if not _is_out(v):
                run = []
                continue
            has_question = "?" in v.body
            has_cta = bool(re.search(r"\b(send|tip|unlock|check|see|buy)\b", v.body.lower()))
            if has_question or has_cta:
                run = []
                continue
            run.append(v)
            if len(run) >= TOO_PASSIVE_NO_QUESTION_THRESHOLD:
                findings.append(
                    Finding(
                        rule_id="too_passive",
                        severity="warn",
                        title="Too passive — no questions, no CTA",
                        issue=(
                            "Three or more outbound messages in a row with no "
                            "question, hook, or call-to-action."
                        ),
                        why_it_matters=(
                            "Without questions or CTAs the fan has nothing to "
                            "respond to and conversations decay. Passive runs "
                            "correlate with revenue drop-off."
                        ),
                        suggested_better=(
                            "End at least one of the next three messages with "
                            "a direct question or a soft pitch (vault tease, "
                            "tip nudge, unlock CTA)."
                        ),
                        recommended_action=(
                            "Coach the chatter on conversation hooks; ensure "
                            "every 2–3 messages include a question or CTA."
                        ),
                        message=v,
                        context={"chat_id": chat_id, "passive_run": len(run)},
                    )
                )
                run = []  # reset so we don't fire repeatedly
    return findings


def _rule_bad_english(views: list[MessageView]) -> list[Finding]:
    """Surface obvious surface errors only.

    We deliberately do NOT call a grammar library here — false positives
    on flirty / playful tone would drown the operator. We only flag:
      • double spaces inside a word run
      • multiple repeated terminal punctuation (e.g. '!!!', '???')
        but excluding ellipsis '…' and '...'
    """
    findings: list[Finding] = []
    for v in views:
        if not _is_out(v):
            continue
        body = v.body
        problems: list[str] = []
        if DOUBLE_SPACE_RE.search(body):
            problems.append("double spaces")
        # repeated !? (but NOT ...)
        for m in REPEATED_PUNCT_RE.finditer(body):
            if m.group(1) == ".":
                continue
            problems.append(f"repeated '{m.group(0)}'")
        if not problems:
            continue
        findings.append(
            Finding(
                rule_id="bad_english",
                severity="info",
                title="Surface-level English errors",
                issue=f"Found: {', '.join(problems[:3])}.",
                why_it_matters=(
                    "Surface errors break immersion. They flag the chatter "
                    "as careless and reduce the fan's willingness to spend."
                ),
                suggested_better=(
                    "Re-read before sending; collapse double spaces; cap "
                    "exclamation/question marks at one per sentence."
                ),
                recommended_action="Ask chatter to enable a basic spellcheck on their workstation.",
                message=v,
                context={"problems": problems[:5]},
            )
        )
    return findings


def _rule_bad_grammar(views: list[MessageView]) -> list[Finding]:
    """Lowercase 'i' and missing terminal punctuation as cheap signals."""
    findings: list[Finding] = []
    for v in views:
        if not _is_out(v):
            continue
        body = v.body
        problems: list[str] = []
        # Lowercase standalone 'i'
        if re.search(r"(?:^|\s)i(?=\s|[.,!?]|$)", body):
            problems.append("lowercase 'i'")
        # No terminal punctuation on a long-ish message (≥ 25 chars)
        if len(body.strip()) >= 25 and NO_TERMINATING_PUNCT_RE.search(body):
            problems.append("no terminal punctuation")
        if not problems:
            continue
        findings.append(
            Finding(
                rule_id="bad_grammar",
                severity="info",
                title="Grammar slips",
                issue=f"Found: {', '.join(problems)}.",
                why_it_matters=(
                    "Grammar slips are individually harmless but compound. "
                    "Fans paying premium prices expect premium polish."
                ),
                suggested_better=(
                    "Capitalise standalone 'I'; close longer messages with a "
                    "period, question mark, or playful punctuation."
                ),
                recommended_action="Style guide refresher with this chatter.",
                message=v,
                context={"problems": problems},
            )
        )
    return findings


def _rule_wrong_tone(views: list[MessageView]) -> list[Finding]:
    """Profanity / clinical language flagged as tone risk.

    Note: NSFW content is *expected* on this platform; we are looking
    for *insulting* / hostile language, not adult content.  Conservative
    list — operator can extend.
    """
    findings: list[Finding] = []
    hostile_words = (
        "stupid",
        "idiot",
        "moron",
        "loser",
        "creep",
        "freak",
        "weirdo",
        "annoying",
        "shut up",
    )
    for v in views:
        if not _is_out(v):
            continue
        body_lower = v.body.lower()
        hits = [w for w in hostile_words if re.search(rf"\b{re.escape(w)}\b", body_lower)]
        if not hits:
            continue
        findings.append(
            Finding(
                rule_id="wrong_tone",
                severity="critical",
                title="Hostile / insulting language",
                issue=f"Hostile word(s) detected: {', '.join(hits)}.",
                why_it_matters=(
                    "Hostile language toward a paying fan triggers refunds, "
                    "complaint tickets, and platform escalations."
                ),
                suggested_better=(
                    "Replace with playful / teasing language that maintains "
                    "the persona without insulting the fan."
                ),
                recommended_action=(
                    "Manager review immediately. Pause chatter from this " "account until coached."
                ),
                message=v,
                context={"hostile_words": hits},
            )
        )
    return findings


def _rule_copy_paste_feel(views: list[MessageView]) -> list[Finding]:
    """Same chatter sending the same body across multiple chats."""
    findings: list[Finding] = []
    bodies_by_chatter: dict[str | None, dict[str, list[MessageView]]] = {}
    for v in views:
        if not _is_out(v):
            continue
        body = v.body.strip()
        if len(body) < COPY_PASTE_MIN_LEN:
            continue
        norm = re.sub(r"\s+", " ", body.lower())
        bodies_by_chatter.setdefault(v.chatter_source_id, {}).setdefault(norm, []).append(v)

    for chatter_id, bodies in bodies_by_chatter.items():
        for norm, occurrences in bodies.items():
            distinct_chats = {o.chat_source_id for o in occurrences if o.chat_source_id}
            if len(distinct_chats) >= 2:
                # Flag the *last* occurrence so the operator sees the most
                # recent example.
                v = occurrences[-1]
                findings.append(
                    Finding(
                        rule_id="copy_paste_feel",
                        severity="warn",
                        title="Same message reused across chats",
                        issue=(
                            f"Chatter sent the same message in "
                            f"{len(distinct_chats)} different chats."
                        ),
                        why_it_matters=(
                            "Identical copy-paste across chats is the single "
                            "biggest tell of a low-effort chatter. Repeat fans "
                            "compare notes — once is enough to lose a whale."
                        ),
                        suggested_better=(
                            "Personalise per-chat. Reference the fan's name, "
                            "their last purchase, or something specific to the "
                            "thread."
                        ),
                        recommended_action=(
                            "Pull the chatter's recent outbound messages; if "
                            "duplication is widespread, retraining required."
                        ),
                        message=v,
                        context={
                            "chatter_id": chatter_id,
                            "distinct_chats": len(distinct_chats),
                        },
                    )
                )
    return findings


def _rule_missed_upsell(views: list[MessageView]) -> list[Finding]:
    """Fan asked for content; next OUT message didn't pivot to vault / PPV / tip."""
    findings: list[Finding] = []
    for chat_id, chat in _by_chat(views).items():
        for i, v in enumerate(chat):
            if not _is_in(v):
                continue
            body_lower = v.body.lower()
            if not any(k in body_lower for k in MISSED_UPSELL_KEYWORDS):
                continue
            # Look for next OUT message
            next_out = next((m for m in chat[i + 1 :] if _is_out(m)), None)
            if next_out is None:
                continue
            out_lower = next_out.body.lower()
            mentions_offer = any(
                w in out_lower for w in ("vault", "tip", "unlock", "ppv", "$", "send you", "for ")
            )
            if not mentions_offer:
                findings.append(
                    Finding(
                        rule_id="missed_upsell",
                        severity="warn",
                        title="Missed upsell — fan teed it up",
                        issue=(
                            "Fan asked about content (e.g. 'show me' / 'more "
                            "pics' / 'vault') but the next outbound message "
                            "did not propose an offer."
                        ),
                        why_it_matters=(
                            "Fan-initiated content asks are the highest-"
                            "converting moments in a chat. Missing them is "
                            "direct revenue lost."
                        ),
                        suggested_better=(
                            "Pivot directly to a paid offer: 'I have something "
                            "spicy in the vault for $X — want me to send it?'"
                        ),
                        recommended_action=(
                            "Drill on upsell pivots; review chatter's "
                            "objection-handling library."
                        ),
                        message=next_out,
                        context={
                            "fan_message_excerpt": _excerpt(v.body),
                            "chat_id": chat_id,
                        },
                    )
                )
    return findings


def _rule_bad_objection_handling(views: list[MessageView]) -> list[Finding]:
    """Fan raised a price/timing objection; next OUT didn't address it."""
    findings: list[Finding] = []
    for chat_id, chat in _by_chat(views).items():
        for i, v in enumerate(chat):
            if not _is_in(v):
                continue
            body_lower = v.body.lower()
            if not any(k in body_lower for k in OBJECTION_KEYWORDS):
                continue
            next_out = next((m for m in chat[i + 1 :] if _is_out(m)), None)
            if next_out is None:
                continue
            out_lower = next_out.body.lower()
            handled = any(
                w in out_lower
                for w in (
                    "discount",
                    "deal",
                    "for you",
                    "special",
                    "later",
                    "save",
                    "tip",
                    "earlier",
                    "smaller",
                    "lower",
                    "i hear you",
                    "no worries",
                    "no pressure",
                )
            )
            if not handled:
                findings.append(
                    Finding(
                        rule_id="bad_objection_handling",
                        severity="warn",
                        title="Objection not handled",
                        issue=(
                            "Fan raised a price/timing objection but the next "
                            "outbound message did not acknowledge or recover."
                        ),
                        why_it_matters=(
                            "Objections that go unhandled compound. Fans "
                            "remember the last unaddressed friction next time "
                            "they consider opening their wallet."
                        ),
                        suggested_better=(
                            "Acknowledge first ('totally hear you'), then "
                            "offer a softer alternative (smaller bundle, "
                            "discounted tip-unlock, defer-to-later-this-week)."
                        ),
                        recommended_action=(
                            "Pair coaching session on objection handling; "
                            "build a shared response library."
                        ),
                        message=next_out,
                        context={
                            "fan_objection_excerpt": _excerpt(v.body),
                            "chat_id": chat_id,
                        },
                    )
                )
    return findings


def _rule_ignored_fan_context(views: list[MessageView]) -> list[Finding]:
    """Fan asked a direct question; next OUT didn't answer it."""
    findings: list[Finding] = []
    for chat_id, chat in _by_chat(views).items():
        for i, v in enumerate(chat):
            if not _is_in(v):
                continue
            if "?" not in v.body:
                continue
            next_out = next((m for m in chat[i + 1 :] if _is_out(m)), None)
            if next_out is None:
                continue
            # Heuristic: outbound message is "ignoring" if it shares no
            # content-word stem with the inbound question.  Strip stop words
            # and look for any overlap of words ≥ 4 chars.
            stop = {
                "what",
                "where",
                "when",
                "your",
                "you",
                "are",
                "can",
                "the",
                "for",
                "and",
                "but",
                "this",
                "that",
                "with",
                "have",
                "they",
                "will",
                "from",
                "into",
                "about",
                "their",
                "would",
                "could",
                "doing",
                "today",
                "going",
            }
            in_words = {w for w in re.findall(r"[a-zA-Z]{4,}", v.body.lower()) if w not in stop}
            out_words = {
                w for w in re.findall(r"[a-zA-Z]{4,}", next_out.body.lower()) if w not in stop
            }
            if not in_words:
                continue
            if in_words & out_words:
                continue
            findings.append(
                Finding(
                    rule_id="ignored_fan_context",
                    severity="warn",
                    title="Fan question went unanswered",
                    issue=(
                        "Fan asked a question but the next outbound message "
                        "shared no content words with it."
                    ),
                    why_it_matters=(
                        "Ignored questions read as the chatter not paying "
                        "attention. Fans churn fast when they feel unseen."
                    ),
                    suggested_better=(
                        "Re-read the fan's last message before replying; "
                        "echo at least one specific noun or detail back to "
                        "them."
                    ),
                    recommended_action=(
                        "Coach the chatter on context-mirroring; require "
                        "every reply to reference at least one specific from "
                        "the fan's last message."
                    ),
                    message=next_out,
                    context={
                        "fan_question_excerpt": _excerpt(v.body),
                        "chat_id": chat_id,
                    },
                )
            )
    return findings


def _rule_momentum_killed(views: list[MessageView]) -> list[Finding]:
    """Outbound was the last message and ≥ 6h have passed since."""
    findings: list[Finding] = []
    now = utcnow()
    for chat_id, chat in _by_chat(views).items():
        if not chat:
            continue
        last = chat[-1]
        if not _is_out(last) or last.sent_at is None:
            continue
        gap = (now - last.sent_at).total_seconds()
        if gap < MOMENTUM_KILLER_AFTER_SECONDS:
            continue
        findings.append(
            Finding(
                rule_id="momentum_killed",
                severity="info",
                title="Conversation momentum killed",
                issue=(
                    f"Last message in this chat was outbound and "
                    f"{int(gap // 3600)}h+ have passed with no response."
                ),
                why_it_matters=(
                    "Long silences after an outbound message often indicate "
                    "the message landed flat (wrong tone, wrong ask, or "
                    "ignored fan context)."
                ),
                suggested_better=(
                    "Send a low-pressure follow-up: a tease, an observation, "
                    "or a question that gives the fan an easy on-ramp back."
                ),
                recommended_action=(
                    "Audit the chatter's last outbound; if the close was off, "
                    "coach. If the fan's a whale, manager intervenes directly."
                ),
                message=last,
                context={"hours_since_last_out": round(gap / 3600, 1)},
            )
        )
    return findings


def _rule_needs_manager_review(findings: list[Finding]) -> list[Finding]:
    """Roll-up rule: if any critical finding fired on a chat, emit a
    "needs manager review" finding on that chat's last outbound message
    so the operator has one place to triage."""
    out: list[Finding] = []
    by_chat_critical: dict[str, list[Finding]] = {}
    for f in findings:
        if f.severity != "critical":
            continue
        chat = f.message.chat_source_id
        if chat is None:
            continue
        by_chat_critical.setdefault(chat, []).append(f)

    for chat_id, criticals in by_chat_critical.items():
        # Re-flag the most recent critical's message as needs-review.
        latest = max(criticals, key=lambda f: f.message.sent_at or datetime.min)
        out.append(
            Finding(
                rule_id="needs_manager_review",
                severity="critical",
                title="Needs manager review",
                issue=(
                    f"{len(criticals)} critical finding(s) on this chat "
                    f"({', '.join(sorted({f.rule_id for f in criticals}))})."
                ),
                why_it_matters=(
                    "Critical findings on the same chat cluster around the "
                    "same fan; the manager needs to step in before the "
                    "chatter loses the relationship entirely."
                ),
                suggested_better=(
                    "Manager takes the next 1–2 messages in this chat "
                    "personally; coaches the chatter offline."
                ),
                recommended_action=(
                    "Open this chat in the OF account, take over for the "
                    "next two messages, then debrief the chatter."
                ),
                message=latest.message,
                context={
                    "chat_id": chat_id,
                    "rules_fired": sorted({f.rule_id for f in criticals}),
                },
            )
        )
    return out


# ── Limitations note (rendered by the UI) ────────────────────────────────────


CHAT_QC_LAB_LIMITATIONS_NOTE = (
    "Chat QC Lab v1: heuristic, no LLM. Suggested-better-response strings "
    "are canned per rule. Rules are deliberately conservative — false "
    "negatives over false positives. Live chat scraping is not connected; "
    "direct OnlyFans connector is not connected; OnlyMonster does not "
    "expose chat content. This page only sees data the operator has "
    "explicitly imported."
)
