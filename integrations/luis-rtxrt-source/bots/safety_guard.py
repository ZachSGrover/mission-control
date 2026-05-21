#!/usr/bin/env python3
"""
safety_guard.py — Mission Control safety guard / smoke / live-gate.

Modi:
    py safety_guard.py --smoke        # Lokale Health-Checks. Exit 0 wenn alles ok, sonst 2.
    py safety_guard.py --gate-check   # Live-Authorization-Gate. Exit 0 NUR wenn alle 3
                                      # Live-Flags exakt + alle Mass-Live-Blocks erfüllt sind.

Dieser Script darf NIE eine Live-Aktion ausführen (keine DM, kein Repost,
kein Scrape, keine X-Navigation). Er verifiziert nur lokale Zustände.

--smoke wird genutzt von Digidle OS:
    _DRY_RUN_COMMANDS["smoke"] = ("safety_guard.py", ["--smoke"])

--gate-check wird vor jedem Live-One-Job aufgerufen. Wenn der Gate Exit 2 zurückgibt,
darf KEINE Live-Aktion ausgeführt werden. Der Gate prüft die exakten Werte:
    ALLOW_LIVE_EXTERNAL_ACTIONS=true
    CONFIRM_LIVE_TEST=YES
    MAX_TEST_ACTIONS=1
Und blockt zusätzlich, wenn Mass-Live-Flags gesetzt sind.

Jeder Gate-Versuch wird in .safety_guard_audit.log angehängt (lokal, NIE committed).
"""
import argparse
import datetime
import os
import sys
from pathlib import Path

# UTF-8 stdout — gleiches Defense-in-Depth-Pattern wie die anderen Bots
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent

# Erwartete Bot-Scripts in diesem Ordner
EXPECTED_BOTS = (
    "dm_bot.py",
    "blast_bot.py",
    "repost_bot.py",
    "builder_bot.py",
)

# Diese Env-Vars MÜSSEN für den Smoke-Test unset/false sein.
# Sind sie auf "live" gesetzt, brechen wir ab — Mass-Live-Schutz.
LIVE_PERMISSION_FLAGS = (
    "ALLOW_LIVE_EXTERNAL_ACTIONS",
    "CONFIRM_LIVE_TEST",
)


def _is_truthy(val: str) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def run_smoke() -> int:
    """Lokaler Smoke-Check. Returns 0 (ok) oder 2 (problem)."""
    print(f"safety_guard.smoke  bot_dir={BASE_DIR}")
    problems = []

    # 1) Python-Version >= 3.10
    if sys.version_info < (3, 10):
        problems.append(f"Python zu alt: {sys.version_info[:2]} (>= 3.10 noetig)")
    else:
        print(f"  ok Python {sys.version.split()[0]}")

    # 2) Bot-Scripts vorhanden?
    missing_bots = []
    for name in EXPECTED_BOTS:
        if (BASE_DIR / name).exists():
            print(f"  ok {name}")
        else:
            missing_bots.append(name)
            problems.append(f"Bot-Datei fehlt: {name}")

    # 3) Live-Flags MUESSEN aus sein
    live_set = []
    for flag in LIVE_PERMISSION_FLAGS:
        if _is_truthy(os.environ.get(flag, "")):
            live_set.append(flag)
            problems.append(
                f"Live-Flag aktiv: {flag} (muss fuer Smoke aus sein)"
            )
    if not live_set:
        print(f"  ok Live-Flags alle aus")

    # 4) Bot-Dependencies importierbar?
    for mod in ("requests", "playwright"):
        try:
            __import__(mod)
            print(f"  ok import {mod}")
        except ImportError as e:
            problems.append(f"Python-Modul fehlt: {mod} ({e})")

    # 5) Bot-Folder ist beschreibbar?
    try:
        probe = BASE_DIR / ".smoke_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        print(f"  ok bot_dir schreibbar")
    except Exception as e:
        problems.append(f"bot_dir nicht beschreibbar: {e}")

    # Ergebnis
    if problems:
        print("")
        print("SMOKE FAILED:")
        for p in problems:
            print(f"  fail {p}")
        return 2

    print("")
    print("SMOKE OK")
    return 0


# ────────────────────────────────────────────────────────────────────
#  LIVE-GATE: exakte 3-Flag-Verifikation + Mass-Live-Block
# ────────────────────────────────────────────────────────────────────
# Erwartete EXAKTE Werte (case-sensitive). Nicht "1", nicht "Yes", nicht "True" — exakt.
REQUIRED_LIVE_FLAGS = {
    "ALLOW_LIVE_EXTERNAL_ACTIONS": "true",
    "CONFIRM_LIVE_TEST":           "YES",
    "MAX_TEST_ACTIONS":            "1",
}

# Diese Flags duerfen unter KEINEN Umstaenden gesetzt sein wenn ein live-one
# laufen soll. Auch nicht "kombiniert mit den richtigen 3 oben".
# Mass-Live-Schutz: ein einzelner Live-Test darf max EINE Aktion sein.
FORBIDDEN_MASS_FLAGS = (
    "ALLOW_MASS_LIVE",
    "ALLOW_BULK_DM",
    "ALLOW_BULK_REPOST",
    "ALLOW_FULL_BLAST",
    "DISABLE_RATE_LIMITS",
    "DISABLE_DAILY_CAP",
)

AUDIT_LOG_PATH = BASE_DIR / ".safety_guard_audit.log"


def _audit(event: str, decision: str, reason: str = "") -> None:
    """Schreibt eine Zeile in den lokalen Audit-Log. Best-effort, never crashes."""
    try:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        flags = " | ".join(
            f"{k}={os.environ.get(k, '<unset>')}" for k in REQUIRED_LIVE_FLAGS
        )
        line = f"{ts}  {event}  decision={decision}  {flags}"
        if reason:
            line += f"  reason={reason}"
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # Audit darf den Gate-Check NIE zum Crash bringen


def run_gate_check() -> int:
    """Strenge Live-Authorization. Returns 0 NUR wenn alles passt.

    Prüft:
      1. Alle 3 REQUIRED_LIVE_FLAGS gesetzt + exakt richtige Werte
      2. MAX_TEST_ACTIONS parsebar als int <= 1
      3. Kein FORBIDDEN_MASS_FLAGS truthy gesetzt
      4. DRY_RUN explizit nicht 'true' (Konflikt zwischen Live und Dry-Run vermeiden)

    Jeder Gate-Versuch wird im Audit-Log notiert.
    """
    print(f"safety_guard.gate-check  bot_dir={BASE_DIR}")

    # ── DIAGNOSTIC: dump every non-secret live var as the subprocess sees it ──
    # Prints to BOTH stdout and stderr so Mission Control captures either.
    _diag = [
        f"[DIAG safety_guard pid={os.getpid()}]",
        f"  ALLOW_LIVE_EXTERNAL_ACTIONS={os.environ.get('ALLOW_LIVE_EXTERNAL_ACTIONS','<UNSET>')!r}",
        f"  CONFIRM_LIVE_TEST={os.environ.get('CONFIRM_LIVE_TEST','<UNSET>')!r}",
        f"  MAX_TEST_ACTIONS={os.environ.get('MAX_TEST_ACTIONS','<UNSET>')!r}",
        f"  DRY_RUN={os.environ.get('DRY_RUN','<UNSET>')!r}",
        f"  MSA_RTXRT_RUNNER_ID={os.environ.get('MSA_RTXRT_RUNNER_ID','<UNSET>')!r}",
        f"  PYTHONIOENCODING={os.environ.get('PYTHONIOENCODING','<UNSET>')!r}",
        f"  env_var_count={len(os.environ)}",
    ]
    for line in _diag:
        print(line)
        print(line, file=sys.stderr)

    problems: list[str] = []

    # 1) Exakte Wertprüfung der 3 Required-Flags
    for var, expected in REQUIRED_LIVE_FLAGS.items():
        actual = (os.environ.get(var, "") or "").strip()
        if actual == expected:
            print(f"  ok {var}={actual!r}")
        else:
            problems.append(
                f"{var} muss EXAKT {expected!r} sein, ist {actual!r}"
            )

    # 2) Doppelter Schutz: MAX_TEST_ACTIONS muss numerisch <= 1
    try:
        mta_val = (os.environ.get("MAX_TEST_ACTIONS", "") or "").strip()
        mta_int = int(mta_val)
        if mta_int > 1:
            problems.append(f"MAX_TEST_ACTIONS={mta_int} > 1 verboten")
        elif mta_int < 1:
            problems.append(f"MAX_TEST_ACTIONS={mta_int} < 1 ungueltig")
        else:
            print(f"  ok MAX_TEST_ACTIONS parse: {mta_int} (single-shot)")
    except ValueError:
        problems.append(
            f"MAX_TEST_ACTIONS nicht als integer parsebar: {os.environ.get('MAX_TEST_ACTIONS', '')!r}"
        )

    # 3) Mass-Live-Block: keine bulk/mass-Flags
    for forbidden in FORBIDDEN_MASS_FLAGS:
        if _is_truthy(os.environ.get(forbidden, "")):
            problems.append(
                f"{forbidden} ist truthy gesetzt — Mass-Live verboten fuer Single-Live-Test"
            )

    # 4) DRY_RUN-Konflikt: wenn DRY_RUN explizit true, ist das ein Konflikt mit Live
    if _is_truthy(os.environ.get("DRY_RUN", "")):
        problems.append(
            "DRY_RUN ist truthy — Konflikt mit live-one. Erst DRY_RUN unsetten."
        )

    # Defense in depth: Bot-Folder noch da? (sollte trivial sein, aber prüfen)
    if not BASE_DIR.exists():
        problems.append(f"bot_dir nicht erreichbar: {BASE_DIR}")

    if problems:
        print("")
        print("LIVE-GATE BLOCKED:")
        for p in problems:
            print(f"  fail {p}")
        print("")
        print("Zum Oeffnen des Gates ALLE drei Flags exakt setzen:")
        print("  ALLOW_LIVE_EXTERNAL_ACTIONS=true")
        print("  CONFIRM_LIVE_TEST=YES")
        print("  MAX_TEST_ACTIONS=1")
        print("Und KEINE Mass-Live-Flags (siehe FORBIDDEN_MASS_FLAGS).")
        _audit("gate-check", "BLOCK", "; ".join(problems)[:300])
        return 2

    print("")
    print("LIVE-GATE OPEN  (single-shot, MAX_TEST_ACTIONS=1)")
    print("  WARNUNG: Dieser Lauf darf MAXIMAL EINE Live-Aktion ausfuehren.")
    _audit("gate-check", "OPEN")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safety guard / smoke / live-gate für Mission Control."
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Lokale Health-Checks. Exit 0 wenn ok, sonst 2.",
    )
    parser.add_argument(
        "--gate-check",
        action="store_true",
        help="Live-Authorization-Gate. Exit 0 NUR wenn alle 3 Live-Flags exakt + keine Mass-Live-Flags + kein DRY_RUN.",
    )
    args = parser.parse_args()

    if args.smoke and args.gate_check:
        print("Konflikt: --smoke und --gate-check zusammen nicht erlaubt.")
        return 2
    if args.smoke:
        return run_smoke()
    if args.gate_check:
        return run_gate_check()

    # Ohne Flag: nichts tun, aber kein Crash. Print eine kurze Hilfe.
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
