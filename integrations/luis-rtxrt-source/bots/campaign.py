#!/usr/bin/env python3
"""
campaign.py — Orchestrator für RTxRT-Campaigns.

Liest campaign_auftrag.json:
  {
    "timestamp": "...",
    "do_repost": true,
    "do_blast":  true,
    "links": ["https://x.com/..."],
    "repost_accounts": [{"user_id":..., "name":...}, ...],
    "blast_config": {
      "source_type": "contacts"|"followers",
      "source_user_id": "k1bhvfaa",
      "message": "Hey, RT x RT ❓\n{link}",
      "accounts": [{"user_id":..., "name":...}, ...],
      "batch_size": 40, "batch_pause_min": 30, "daily_cap": 800
    }
  }

Schreibt campaign_status.json laufend (state/step/log).
Spawnt repost_bot.py (wenn do_repost) und wartet bis fertig.
Dann (wenn do_blast) wird PRO LINK ein Blast-Run gemacht:
  - schreibt blast_auftrag.json mit {link} im Message substituiert
  - spawnt blast_bot.py
  - wartet
"""
import json
import os
import re
import sys
import time
import datetime
import subprocess
from pathlib import Path

# UTF-8 Stdout erzwingen (campaign.py wird selbst von server.py mit DETACHED gespawnt)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).parent
AUFTRAG_PATH  = BASE_DIR / "campaign_auftrag.json"
STATUS_PATH   = BASE_DIR / "campaign_status.json"
REPOST_AUFTRAG = BASE_DIR / "repost_auftrag.json"
REPOST_STATUS  = BASE_DIR / "repost_status.json"
BLAST_AUFTRAG  = BASE_DIR / "blast_auftrag.json"
BLAST_STATUS   = BASE_DIR / "blast_status.json"

# ───────── JSON-Helpers (atomic, OneDrive-safe) ─────────
def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default

def save_json(path: Path, data):
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    for attempt in range(6):
        try:
            tmp.write_text(payload, encoding="utf-8")
            try: tmp.replace(path)
            except OSError:
                path.write_text(payload, encoding="utf-8")
                try: tmp.unlink()
                except Exception: pass
            return
        except OSError:
            time.sleep(0.6 * (attempt + 1))
    try: path.write_text(payload, encoding="utf-8")
    except OSError: pass

# ───────── Status helpers ─────────
_status = {"state": "idle", "step": "", "log": []}
_totals = {
    "repost_ok": 0, "repost_renewed": 0, "repost_already": 0, "repost_err": 0,
    "dm_sent":   0, "dm_skip": 0, "dm_err": 0,
}

def push_log(line: str):
    _status["log"].append(line)
    save_status()

def set_step(state: str, step: str):
    _status["state"] = state
    _status["step"]  = step
    save_status()
    print(f"  [{state.upper()}] {step}")

def save_status():
    save_json(STATUS_PATH, _status)

# ───────── Summary-Parser ─────────
def parse_repost_step(step: str) -> dict:
    """Aus 'Repost fertig — 9 reposted, 0 renewed, 0 schon vorher, 7 Fehler in 16m 43s'"""
    out = {"reposted": 0, "renewed": 0, "already": 0, "errors": 0, "duration": ""}
    for key, pat in [
        ("reposted", r"(\d+)\s+reposted"),
        ("renewed",  r"(\d+)\s+renewed"),
        ("already",  r"(\d+)\s+schon"),
        ("errors",   r"(\d+)\s+Fehler"),
    ]:
        m = re.search(pat, step or "")
        if m: out[key] = int(m.group(1))
    m = re.search(r"in\s+(\d+m\s+\d+s)", step or "")
    if m: out["duration"] = m.group(1)
    return out

def parse_blast_step(step: str) -> dict:
    """Aus 'Blast fertig — 234 DMs gesendet (12 skip, 3 Fehler) in 6m 12s'"""
    out = {"sent": 0, "skip": 0, "errors": 0, "duration": ""}
    m = re.search(r"(\d+)\s+DMs?\s+gesendet", step or "")
    if m: out["sent"] = int(m.group(1))
    m = re.search(r"\((\d+)\s+skip", step or "")
    if m: out["skip"] = int(m.group(1))
    m = re.search(r"(\d+)\s+Fehler", step or "")
    if m: out["errors"] = int(m.group(1))
    m = re.search(r"in\s+(\d+m\s+\d+s)", step or "")
    if m: out["duration"] = m.group(1)
    return out

_REPOST_MARKERS = (" ✓ reposted", " ⟳ ", " ↻ ", " ✗ ")
_BLAST_MARKERS  = (" ✓ ", " ✗ ")
_PREFLIGHT_PREFIX_RE = re.compile(r"^\s*\[\d+/\d+\]")

def per_account_repost_counts(log_lines: list) -> dict:
    """Zählt pro Account ✓/⟳/↻/✗ aus echten Repost-Log-Zeilen.
    Format: '{name}: …/{tweet} ✓ reposted' bzw. '{name}: …/{tweet} ✗ ({reason})'.
    Preflight-Zeilen (mit [n/m] Prefix) und Header werden ignoriert."""
    per = {}
    for ln in log_lines or []:
        if not isinstance(ln, str): continue
        if ":" not in ln: continue
        # Preflight-Zeilen mit "[i/n]" Prefix gehören NICHT in per-account-repost
        if _PREFLIGHT_PREFIX_RE.match(ln): continue
        # Nur Zeilen mit echtem Repost-Marker zählen
        if not any(m in ln for m in _REPOST_MARKERS): continue
        name = ln.split(":", 1)[0].strip()
        if name.startswith("━") or name.startswith("⏭") or name.startswith("Preflight") \
           or name.startswith("┌") or name.startswith("│") or name.startswith("└") \
           or name in ("FEHLER","KRITISCH"):
            continue
        d = per.setdefault(name, {"ok": 0, "renewed": 0, "err": 0, "skip": 0})
        if " ✓ reposted" in ln:    d["ok"]      += 1
        elif " ⟳ " in ln:          d["renewed"] += 1
        elif " ↻ " in ln:          d["skip"]    += 1
        elif " ✗ " in ln:          d["err"]     += 1
    return per

def per_account_blast_counts(log_lines: list) -> dict:
    """Zählt pro Account 'X DMs gesendet' aus den Log-Zeilen."""
    per = {}
    for ln in log_lines or []:
        if not isinstance(ln, str): continue
        if ":" not in ln: continue
        if _PREFLIGHT_PREFIX_RE.match(ln): continue
        if not any(m in ln for m in _BLAST_MARKERS): continue
        name = ln.split(":", 1)[0].strip()
        if name.startswith("━") or name.startswith("⏭") \
           or name.startswith("┌") or name.startswith("│") or name.startswith("└"):
            continue
        d = per.setdefault(name, {"sent": 0, "err": 0})
        if " ✓ " in ln:  d["sent"] += 1
        elif " ✗ " in ln: d["err"] += 1
    return per

# ───────── Bot spawnen + Status mirrorn ─────────
def run_bot(script_name: str, mirror_status_path: Path, label: str) -> str:
    """Spawnt einen Bot via subprocess und pollt seinen Status bis 'done'/'error'/'skipped'.
    Spiegelt Log-Zeilen in den Campaign-Status. Returns final state."""
    set_step("running", f"{label}: starte …")

    # Sicherheit: status-File zurücksetzen
    save_json(mirror_status_path, {"state":"running", "step": f"{label} startet", "log":[]})

    python = sys.executable or "python"
    creation = 0
    if os.name == "nt":
        # DETACHED_PROCESS — Bot bekommt eigenes Konsolen-Window auf Windows
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        creation = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    # UTF-8 Stdout für Subprocess erzwingen — sonst crasht print('═') unter Windows-cp1252
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        proc = subprocess.Popen(
            [python, str(BASE_DIR / script_name)],
            cwd=str(BASE_DIR),
            creationflags=creation,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,
            env=env,
        )
    except Exception as e:
        push_log(f"❌ {label}: Spawn-Fehler — {e}")
        return "error"

    # Polling
    last_log_len = 0
    last_step    = ""
    poll_count   = 0
    final_state  = "unknown"
    while True:
        time.sleep(2.0)
        poll_count += 1

        s = load_json(mirror_status_path, {})
        state = s.get("state", "running")
        step  = s.get("step", "")
        log   = s.get("log", []) or []

        # Mirror new log lines
        if len(log) > last_log_len:
            for line in log[last_log_len:]:
                push_log(f"  {label}│ {line}")
            last_log_len = len(log)

        # Mirror step changes
        if step and step != last_step:
            set_step("running", f"{label}: {step}")
            last_step = step

        # Check process alive
        proc_alive = (proc.poll() is None)

        if state in ("done", "error", "skipped"):
            # Subprocess fertig laut Status-Datei
            final_state = state
            break
        if not proc_alive and poll_count > 5:
            # Subprocess tot aber Status sagt noch "running" → Kraschverdacht
            final_state = state if state != "running" else "error"
            push_log(f"  {label}│ ⚠ Subprocess beendet ohne 'done'-Status (state={state})")
            break

    # Final-Status + Logs aus dem Subprocess-Status holen
    final_status = load_json(mirror_status_path, {})
    final_step   = final_status.get("step", "")
    final_log    = final_status.get("log", [])

    # Ergebnisbox je nach Bot-Typ
    if label.startswith("Repost"):
        r = parse_repost_step(final_step)
        push_log("┌─ REPOST RESULTS ──────────────────────────")
        push_log(f"│  ✓ Reposted:    {r['reposted']}")
        push_log(f"│  ⟳ Renewed:     {r['renewed']}")
        push_log(f"│  ↻ Schon vorher:{r['already']}")
        push_log(f"│  ✗ Fehler:      {r['errors']}")
        if r['duration']: push_log(f"│  ⏱ Dauer:       {r['duration']}")
        # Per-Account Breakdown
        per = per_account_repost_counts(final_log)
        if per:
            push_log("│")
            push_log("│  Per-Account:")
            for nm in sorted(per.keys()):
                d = per[nm]
                parts = []
                if d["ok"]:      parts.append(f"✓{d['ok']}")
                if d["renewed"]: parts.append(f"⟳{d['renewed']}")
                if d["skip"]:    parts.append(f"↻{d['skip']}")
                if d["err"]:     parts.append(f"✗{d['err']}")
                push_log(f"│    {nm}: {' '.join(parts) if parts else '— (keine Aktion)'}")
        push_log("└───────────────────────────────────────────")
        # Track totals for grand summary at end
        _totals["repost_ok"]      += r["reposted"]
        _totals["repost_renewed"] += r["renewed"]
        _totals["repost_already"] += r["already"]
        _totals["repost_err"]     += r["errors"]
    elif label.startswith("DM"):
        b = parse_blast_step(final_step)
        push_log("┌─ DM RESULTS ──────────────────────────────")
        push_log(f"│  ✓ Gesendet:    {b['sent']}")
        push_log(f"│  ⏭ Skip:        {b['skip']}")
        push_log(f"│  ✗ Fehler:      {b['errors']}")
        if b['duration']: push_log(f"│  ⏱ Dauer:       {b['duration']}")
        per = per_account_blast_counts(final_log)
        if per:
            push_log("│")
            push_log("│  Per-Account:")
            for nm in sorted(per.keys()):
                d = per[nm]
                parts = []
                if d["sent"]: parts.append(f"✓{d['sent']}")
                if d["err"]:  parts.append(f"✗{d['err']}")
                push_log(f"│    {nm}: {' '.join(parts) if parts else '— (keine Aktion)'}")
        push_log("└───────────────────────────────────────────")
        _totals["dm_sent"] += b["sent"]
        _totals["dm_skip"] += b["skip"]
        _totals["dm_err"]  += b["errors"]
    else:
        push_log(f"━━ {label} fertig: {final_state} ━━")

    return final_state

# ───────── Main ─────────
def main():
    start = time.time()
    print(f"\n{'═'*55}\n  campaign.py  —  Start\n{'═'*55}")

    auftrag = load_json(AUFTRAG_PATH, {})
    if not auftrag:
        set_step("error", "Kein campaign_auftrag.json")
        return

    do_repost = bool(auftrag.get("do_repost"))
    do_blast  = bool(auftrag.get("do_blast"))
    links     = auftrag.get("links") or []

    if not links:
        set_step("skipped", "Keine Links angegeben")
        return
    if not (do_repost or do_blast):
        set_step("skipped", "Keine Aktion ausgewählt (do_repost / do_blast beide false)")
        return

    _status["log"] = []
    push_log(f"━━ Campaign Start — {len(links)} Link(s) | repost={do_repost} blast={do_blast} ━━")

    # ─── Phase 1: Repost ─────────────────────────────────
    if do_repost:
        repost_accounts = auftrag.get("repost_accounts") or []
        if not repost_accounts:
            push_log("⚠ Repost angefordert aber keine Repost-Accounts ausgewählt — Phase übersprungen.")
        else:
            push_log(f"━━ Phase 1: Repost ({len(repost_accounts)} Accounts × {len(links)} Links) ━━")
            # repost_auftrag.json schreiben
            save_json(REPOST_AUFTRAG, {
                "group_name": "Campaign",
                "accounts":   repost_accounts,
                "links":      links,
                "preflight":  False,
                # repost_bot.py macht eigenständig Preflight am Start
            })
            run_bot("repost_bot.py", REPOST_STATUS, "Repost")
    else:
        push_log("⏭  Repost-Phase übersprungen (do_repost=false).")

    # ─── Phase 2: DM-Blast — pro Link ein Blast ──────────
    if do_blast:
        bc = auftrag.get("blast_config") or {}
        blast_accounts = bc.get("accounts") or []
        if not blast_accounts:
            push_log("⚠ DM angefordert aber keine Sender-Accounts ausgewählt — Phase übersprungen.")
        elif not bc.get("message"):
            push_log("⚠ Keine Message — DM-Phase übersprungen.")
        elif not bc.get("source_user_id"):
            push_log("⚠ Keine Empfänger-Quelle — DM-Phase übersprungen.")
        else:
            push_log(f"━━ Phase 2: DM-Blast ({len(blast_accounts)} Sender × {len(links)} Link-Variant) ━━")
            for idx, link in enumerate(links, start=1):
                # {link}-Platzhalter pro Run ersetzen
                msg = (bc.get("message") or "").replace("{link}", link)
                if "{link}" in (bc.get("message") or "") and msg == bc.get("message"):
                    # placeholder existierte, wurde aber nicht ersetzt → defensiv
                    msg = msg + "\n" + link
                if "{link}" not in (bc.get("message") or ""):
                    # Kein Placeholder → Link unten anhängen
                    msg = (bc.get("message") or "") + ("\n" + link if not msg.endswith(link) else "")

                save_json(BLAST_AUFTRAG, {
                    "timestamp":      datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "source_type":    bc.get("source_type", "contacts"),
                    "source_user_id": bc.get("source_user_id"),
                    "message":        msg,
                    "accounts":       blast_accounts,
                    "batch_size":     bc.get("batch_size", 40),
                    "batch_pause_min":bc.get("batch_pause_min", 30),
                    "daily_cap":      bc.get("daily_cap", 800),
                    "cooldown_hours": bc.get("cooldown_hours", 24),
                    "campaign_label": f"Link {idx}/{len(links)}",
                })
                push_log(f"  ▸ Blast {idx}/{len(links)} für: {link[:80]}…")
                run_bot("blast_bot.py", BLAST_STATUS, f"DM[{idx}/{len(links)}]")
    else:
        push_log("⏭  DM-Phase übersprungen (do_blast=false).")

    elapsed = int(time.time() - start)
    mins, secs = divmod(elapsed, 60)

    # ═══ Grand-Total Summary ═══
    push_log("")
    push_log("╔══════════════════════════════════════════╗")
    push_log("║         CAMPAIGN TOTAL SUMMARY           ║")
    push_log("╠══════════════════════════════════════════╣")
    if do_repost:
        push_log(f"║  REPOSTS                                  ║")
        push_log(f"║    ✓ Reposted:      {_totals['repost_ok']:>4}                 ║")
        push_log(f"║    ⟳ Renewed:       {_totals['repost_renewed']:>4}                 ║")
        push_log(f"║    ↻ Schon vorher:  {_totals['repost_already']:>4}                 ║")
        push_log(f"║    ✗ Fehler:        {_totals['repost_err']:>4}                 ║")
    if do_blast:
        if do_repost: push_log("║  ────────────────────────────────────────  ║")
        push_log(f"║  DMs                                      ║")
        push_log(f"║    ✓ Gesendet:      {_totals['dm_sent']:>4}                 ║")
        push_log(f"║    ⏭ Skip:          {_totals['dm_skip']:>4}                 ║")
        push_log(f"║    ✗ Fehler:        {_totals['dm_err']:>4}                 ║")
    push_log(f"║  Dauer: {mins:>3}m {secs:>2}s                          ║")
    push_log("╚══════════════════════════════════════════╝")

    # Final step im Dashboard so kompakt dass alles sofort sichtbar ist
    final_step_parts = []
    if do_repost:
        final_step_parts.append(f"{_totals['repost_ok']} reposted, {_totals['repost_err']} Fehler")
    if do_blast:
        final_step_parts.append(f"{_totals['dm_sent']} DMs, {_totals['dm_err']} Fehler")
    set_step("done", "Campaign fertig — " + " · ".join(final_step_parts) + f" ({mins}m {secs}s)")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        push_log(f"💥 Campaign abgestürzt: {e}")
        try: set_step("error", f"crashed: {e}")
        except Exception: pass
        raise
