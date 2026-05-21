#!/usr/bin/env python3
"""
dm_bot.py — X DM Automation
Liest auftrag.json, sendet DMs über AdsPower + Playwright (kein eigener Browser-Download)

Einmalige Installation:
    pip install playwright requests --break-system-packages

Starten:
    python dm_bot.py
"""

import json
import os
import sys
import time
import datetime
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# UTF-8 Stdout erzwingen — sonst crasht print('═') etc. unter Windows-cp1252
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Shared parallel preflight (state checks + action hints)
try:
    from _preflight import preflight_and_filter
except ImportError:
    preflight_and_filter = None

# ═══════════════════════════════════════════════════════
#  PFADE
# ═══════════════════════════════════════════════════════
BASE_DIR      = Path(__file__).parent
AUFTRAG_PATH  = BASE_DIR / "auftrag.json"
CONTACTS_PATH = BASE_DIR / "contacts.json"
STATUS_PATH   = BASE_DIR / "status.json"

# ═══════════════════════════════════════════════════════
#  ADSPOWER API
# ═══════════════════════════════════════════════════════
ADS_HOST = "http://local.adspower.net:50325"

def ads_open(user_id: str) -> str:
    """Öffnet AdsPower-Profil → gibt CDP-WebSocket-URL zurück."""
    r = requests.get(
        f"{ADS_HOST}/api/v1/browser/start",
        params={"user_id": user_id},
        timeout=30
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"AdsPower Fehler beim Öffnen: {data}")
    ws = data["data"]["ws"]["puppeteer"]
    print(f"    Browser offen ✓  ({ws[:50]}...)")
    return ws

def ads_close(user_id: str):
    """Schließt AdsPower-Profil."""
    try:
        requests.get(
            f"{ADS_HOST}/api/v1/browser/stop",
            params={"user_id": user_id},
            timeout=10
        )
        print(f"    Browser geschlossen ✓")
    except Exception as e:
        print(f"    Browser schließen fehlgeschlagen: {e}")

# ═══════════════════════════════════════════════════════
#  JSON HELFER
# ═══════════════════════════════════════════════════════
def load_json(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}

def save_json(path: Path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def set_status(state: str, step: str, log: list):
    save_json(STATUS_PATH, {"state": state, "step": step, "log": log})
    print(f"  [{state.upper()}] {step}")

# ═══════════════════════════════════════════════════════
#  24h FILTER
# ═══════════════════════════════════════════════════════
def is_filtered(contacts: dict, user_id: str, chat_url: str) -> bool:
    """True wenn dieser Chat in den letzten 24h bereits angeschrieben wurde."""
    now = datetime.datetime.now(datetime.timezone.utc)
    for c in contacts.get(user_id, []):
        if c.get("url") == chat_url:
            try:
                last = datetime.datetime.fromisoformat(
                    c["last_sent"].replace("Z", "+00:00")
                )
                if (now - last).total_seconds() < 86400:
                    return True
            except Exception:
                pass
    return False

def add_contact(contacts: dict, user_id: str, name: str, url: str):
    """Fügt gesendeten Kontakt zu contacts.json hinzu (oder updated last_sent)."""
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    entry = {"name": name, "url": url, "last_sent": now_str}
    if user_id not in contacts:
        contacts[user_id] = []
    for i, c in enumerate(contacts[user_id]):
        if c.get("url") == url:
            contacts[user_id][i] = entry
            return
    contacts[user_id].append(entry)

# ═══════════════════════════════════════════════════════
#  NACHRICHT SENDEN (in offenem Chat)
# ═══════════════════════════════════════════════════════
def find_composer(page):
    """Findet den Nachrichtenkomposer."""
    # Bestätigter Selektor zuerst — spart Zeit
    priority = [
        '[data-testid*="composer"]',
        'textarea',
        '[role="textbox"]',
        '[aria-label*="essage"]',
        'div[contenteditable="true"]',
    ]
    for sel in priority:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=800):
                return el
        except PWTimeout:
            continue
    return None

def find_send_button(page):
    """Findet den Senden-Button."""
    selectors = [
        '[data-testid="dmComposerSendButton"]',
        '[data-testid="dm-composer-send-button"]',
        '[data-testid="dm-send-button"]',
        'button[data-testid*="send"]',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                return btn
        except PWTimeout:
            continue
    return None

def send_message_in_chat(page, message: str) -> bool:
    """
    Versucht die Nachricht in den aktuell offenen Chat zu senden.
    Gibt True zurück wenn erfolgreich.
    """
    composer = find_composer(page)
    if composer is None:
        return False

    try:
        composer.click()
        time.sleep(0.3)
        parts = message.split("\n")
        for i, part in enumerate(parts):
            composer.type(part, delay=10)
            if i < len(parts) - 1:
                page.keyboard.press("Shift+Enter")
        time.sleep(0.3)
    except Exception as e:
        print(f"      Tipp-Fehler: {e}")
        return False

    # Senden: erst Button versuchen, dann Enter
    send_btn = find_send_button(page)
    if send_btn:
        send_btn.click()
    else:
        page.keyboard.press("Return")

    time.sleep(1.5)
    return True

# ═══════════════════════════════════════════════════════
#  PASS 1: Gesamte Chatliste scannen → URLs sammeln
# ═══════════════════════════════════════════════════════
def extract_chats_js(page) -> list:
    """Extrahiert alle sichtbaren Chat-Links + Namen per JS in einem Aufruf."""
    try:
        return page.evaluate("""
            () => {
                const links = [...document.querySelectorAll('a[href*="/messages/"], a[href*="/i/chat/"]')];
                return links.map(a => {
                    const href = a.getAttribute('href') || '';
                    if (!href || href.split('/').length < 3) return null;
                    let name = '';
                    // Priorität 1: span[dir="ltr"] — enthält meist den Anzeigenamen
                    const ltr = a.querySelector('span[dir="ltr"]');
                    if (ltr) {
                        const t = ltr.textContent.trim();
                        if (t.length > 0) name = t;
                    }
                    // Priorität 2: erster span der kein Timestamp/Preview ist
                    if (!name) {
                        for (const s of a.querySelectorAll('span')) {
                            const t = s.textContent.trim();
                            if (t.length > 1 && t.length < 60
                                && !/^[\\d:]+$/.test(t)
                                && !/^\\d+[smhd]$/.test(t)
                                && !t.startsWith('You:')
                                && !t.startsWith('Du:')) {
                                name = t; break;
                            }
                        }
                    }
                    if (!name) name = href.split('/').pop();
                    return { href, name };
                }).filter(x => x !== null);
            }
        """) or []
    except Exception:
        return []

def scroll_dm_list(page):
    """Scrollt den DM-Listen-Container nach unten."""
    try:
        page.evaluate("""
            () => {
                const link = document.querySelector('a[href*="/messages/"], a[href*="/i/chat/"]');
                if (link) {
                    let el = link.parentElement;
                    while (el && el !== document.body) {
                        const s = window.getComputedStyle(el);
                        if (s.overflowY === 'scroll' || s.overflowY === 'auto') {
                            el.scrollBy(0, 800); return;
                        }
                        el = el.parentElement;
                    }
                }
                const fb = document.querySelector('[data-testid="DMDrawer"]')
                        || document.querySelector('[data-testid="dm-inbox"]')
                        || document.querySelector('section[role="region"]')
                        || document.querySelector('[aria-label*="Messages"]');
                if (fb) fb.scrollBy(0, 800); else window.scrollBy(0, 800);
            }
        """)
    except Exception:
        pass

def collect_chat_urls(page, user_id: str, contacts: dict, max_collect: int, log: list) -> list:
    """
    Scrollt die komplette Chatliste durch und sammelt (name, url) Paare
    die NICHT im 24h-Filter sind. Navigiert dabei NIE weg.
    """
    seen_urls  = set()
    targets    = []          # [(name, url), ...]
    empty_scrolls = 0
    MAX_EMPTY  = 15

    print(f"\n  [SCAN] Scanne Chatliste …")
    set_status("scanning", f"🔍 Scanne Chatliste… 0 Ziele gefunden", log)

    while len(targets) < max_collect:
        items = extract_chats_js(page)
        found_new = False

        for item in items:
            try:
                href     = item["href"]
                full_url = f"https://x.com{href}" if href.startswith("/") else href
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                found_new = True

                if is_filtered(contacts, user_id, full_url):
                    continue  # bekannt & noch gesperrt → trotzdem weiter scrollen

                name = item.get("name") or full_url.split("/")[-1]
                targets.append((name, full_url))
                print(f"    + {name}")
                set_status("scanning", f"🔍 Scanne Chatliste… {len(targets)} Ziele gefunden", log)

                if len(targets) >= max_collect:
                    break
            except Exception:
                continue

        if not found_new:
            empty_scrolls += 1
            if empty_scrolls >= MAX_EMPTY:
                print(f"  [SCAN] Ende der Liste — {len(seen_urls)} Chats gesehen, {len(targets)} Ziele gefunden.")
                break
        else:
            empty_scrolls = 0

        scroll_dm_list(page)
        time.sleep(1.2)

    set_status("scan_done", f"✅ Scan abgeschlossen — {len(targets)} Chats gefunden, starte Versand…", log)
    return targets


# ═══════════════════════════════════════════════════════
#  PASS 2: Gesammelte URLs abarbeiten & senden
# ═══════════════════════════════════════════════════════
def scroll_and_send(page, user_id: str, account_name: str,
                    message: str, max_sends: int,
                    contacts: dict, log: list) -> int:
    """
    Two-Pass:
      1) Komplette Chatliste scannen → Ziele sammeln
      2) Jede Ziel-URL direkt ansteuern & DM senden
    """
    print(f"\n  Suche Kontakte für {account_name} (Ziel: {max_sends} DMs)")

    # ── Pass 1: Scan ──────────────────────────────────
    targets = collect_chat_urls(page, user_id, contacts, max_sends, log)

    if not targets:
        print("  Keine neuen Kontakte gefunden.")
        return 0

    print(f"\n  [SEND] Sende an {len(targets)} Kontakte …")

    # ── Pass 2: Senden ────────────────────────────────
    sent = 0
    for contact_name, full_url in targets:
        if sent >= max_sends:
            break
        try:
            page.goto(full_url, wait_until="domcontentloaded", timeout=25000)

            if "/messages/" not in page.url and "/i/chat/" not in page.url:
                print(f"    ✗ Navigation fehlgeschlagen: {full_url}")
                continue

            # Warten bis Composer geladen ist
            try:
                page.wait_for_selector(
                    'textarea, [role="textbox"], [contenteditable="true"], [data-testid*="composer"]',
                    timeout=6000
                )
            except PWTimeout:
                pass
            time.sleep(0.5)

            success = send_message_in_chat(page, message)

            if success:
                sent += 1
                add_contact(contacts, user_id, contact_name, full_url)
                save_json(CONTACTS_PATH, contacts)
                log.append(f"{account_name}: {contact_name} ✓")
                set_status(
                    "running",
                    f"{account_name} – {sent}/{max_sends} DMs gesendet",
                    log
                )
                print(f"    ✓ {contact_name}  [{sent}/{max_sends}]")
            else:
                print(f"    ✗ Read-only — {contact_name}")

        except Exception as e:
            print(f"    ⚠ Fehler bei {contact_name}: {e}")
            continue

    return sent

# ═══════════════════════════════════════════════════════
#  ACCOUNT VERARBEITEN
# ═══════════════════════════════════════════════════════
def process_account(account: dict, max_sends: int,
                    contacts: dict, log: list) -> int:
    user_id = account["user_id"]
    name    = account["name"]
    message = account["message"]

    print(f"\n{'═'*55}")
    print(f"  Account : {name}  ({user_id})")
    print(f"  Ziel    : {max_sends} DMs")
    print(f"{'═'*55}")

    ws_url = ads_open(user_id)
    time.sleep(4)  # Browser starten lassen

    sent = 0
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(ws_url)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()

            # Zur Chat-Liste
            print("  Lade x.com/messages ...")
            page.goto("https://x.com/messages", wait_until="domcontentloaded", timeout=30000)

            if "login" in page.url.lower():
                raise RuntimeError("Nicht eingeloggt — bitte manuell in AdsPower anmelden!")

            # Warten bis DM-Inbox UI geladen ist (dm-search-bar existiert sicher)
            print("  Warte auf DM-Inbox …")
            try:
                page.wait_for_selector('[data-testid="dm-search-bar"]', timeout=15000)
                print("  DM-Inbox bereit ✓")
            except PWTimeout:
                print("  Timeout bei dm-search-bar — warte trotzdem")

            # Netzwerk abwarten + Konversationsliste rendern lassen
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            time.sleep(3)

            sent = scroll_and_send(page, user_id, name, message, max_sends, contacts, log)

        except Exception as e:
            print(f"\n  ❌ Fehler: {e}")
            log.append(f"FEHLER {name}: {str(e)}")
        finally:
            try:
                browser.close()
            except Exception:
                pass

    ads_close(user_id)
    time.sleep(3)
    return sent

# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════
def main():
    # ── Run-mode flags (added: real --dry-run + defense-in-depth live cap) ──
    import argparse as _ap
    _p = _ap.ArgumentParser(add_help=False)
    _p.add_argument("--dry-run", action="store_true")
    _p.add_argument("--live-one", action="store_true")
    _p.add_argument("--max-actions", type=int, default=None)
    _args, _ = _p.parse_known_args()
    dry_run = bool(_args.dry_run)
    live_one_flag = bool(_args.live_one)

    start_time = time.time()
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    print(f"\n{'═'*55}")
    print(f"  dm_bot.py  —  Start: {now_str}{' (DRY RUN)' if dry_run else ''}")
    print(f"{'═'*55}")

    # Dateien laden
    auftrag  = load_json(AUFTRAG_PATH)
    contacts = load_json(CONTACTS_PATH)

    # ── DRY RUN: validate + plan + exit. No AdsPower, no browser, no DM. ──
    if dry_run:
        accs = (auftrag or {}).get("accounts") or []
        max_chats_planned = (auftrag or {}).get("max_chats", 50)
        n_accounts = len(accs)
        n_contacts = sum(len(v) for v in (contacts or {}).values()) if isinstance(contacts, dict) else 0
        planned = n_accounts * max_chats_planned
        print(f"DRY RUN — dm_bot.py would:")
        print(f"  - auftrag accounts: {n_accounts}")
        print(f"  - max_chats per account: {max_chats_planned}")
        print(f"  - planned DMs: up to {planned}")
        print(f"  - contacts.json known recipients: {n_contacts}")
        print(f"  - would call: ads_open -> playwright -> send DM")
        print(f"DRY RUN OK -- no AdsPower call, no browser, no DM sent.")
        set_status("done", f"DRY RUN OK -- up to {planned} DMs planned", [])
        return

    if not auftrag or not auftrag.get("accounts"):
        print("⏭  Kein Auftrag heute — übersprungen.")
        set_status("skipped", "Kein Auftrag heute — übersprungen", [])
        return

    accounts_raw = auftrag["accounts"]
    max_chats    = auftrag.get("max_chats", 50)
    log          = []
    total        = 0

    # AVAILABLE-Platzhalter immer rausfiltern (ungenutzte AdsPower-Profile)
    accounts = []
    available_skipped = []
    for a in accounts_raw:
        if (a.get("name") or "").strip().upper() == "AVAILABLE":
            available_skipped.append(a.get("user_id") or "?")
        else:
            accounts.append(a)
    if available_skipped:
        log.append(f"⏭  AVAILABLE-Platzhalter ignoriert ({len(available_skipped)}): {', '.join(available_skipped)}")

    if not accounts:
        set_status("skipped", "Nur AVAILABLE-Platzhalter ausgewählt — nichts zu tun", log)
        return

    # ───────────────────────────────────────────────────────────────
    #  LIVE-MODE HARD CAP (defense in depth, gespiegelt von repost_bot.py)
    # ───────────────────────────────────────────────────────────────
    # Wenn ALLOW_LIVE_EXTERNAL_ACTIONS=true gesetzt ist, MUSS auch
    # MAX_TEST_ACTIONS exakt 1 sein. Sonst bricht der Bot mit error ab.
    # Zusätzlich werden accounts + max_chats HART auf 1 gecapped.
    live_mode = live_one_flag or (os.environ.get("ALLOW_LIVE_EXTERNAL_ACTIONS", "").strip() == "true")
    if live_mode:
        confirm = (os.environ.get("CONFIRM_LIVE_TEST", "").strip())
        mta_raw = (os.environ.get("MAX_TEST_ACTIONS", "").strip())
        try:
            mta = int(mta_raw)
        except (ValueError, TypeError):
            mta = -1
        if confirm != "YES" or mta != 1:
            log_msg = [
                "⛔ LIVE-MODE-ABORT: ALLOW_LIVE_EXTERNAL_ACTIONS=true ohne korrekte Flags.",
                f"   CONFIRM_LIVE_TEST={confirm!r} (muss 'YES' sein)",
                f"   MAX_TEST_ACTIONS={mta_raw!r} (muss '1' sein)",
                "   DM-Run wurde sicherheitshalber abgebrochen.",
            ]
            for ln in log_msg: print(ln)
            set_status("error", "live-mode flag-mismatch — abort", log_msg)
            return
        # Mass-Live-Flags müssen alle aus sein
        forbidden = ["ALLOW_MASS_LIVE","ALLOW_BULK_DM","ALLOW_BULK_REPOST",
                     "ALLOW_FULL_BLAST","DISABLE_RATE_LIMITS","DISABLE_DAILY_CAP"]
        bad = [f for f in forbidden if (os.environ.get(f,"").strip().lower() in ("1","true","yes","on"))]
        if bad:
            log_msg = [f"⛔ LIVE-MODE-ABORT: mass-live flag(s) set: {bad}"]
            for ln in log_msg: print(ln)
            set_status("error", f"mass-live flags set: {bad}", log_msg)
            return
        # HART-CAP: nur 1 Account, nur 1 DM
        cap_log = []
        if len(accounts) > 1:
            cap_log.append(f"⚠ LIVE-CAP: {len(accounts)} accounts → cap to 1 (nur erster wird verwendet)")
            accounts = accounts[:1]
        if max_chats > 1:
            cap_log.append(f"⚠ LIVE-CAP: max_chats={max_chats} → cap to 1")
            max_chats = 1
        cap_log.append("━━ LIVE MODE ACTIVE — single-shot: 1 account × 1 DM = max 1 action ━━")
        for ln in cap_log: print(ln)
        log = cap_log + log

    # ─── Preflight: parallel pro Account testen ob DMs möglich sind ──
    if preflight_and_filter is not None and not auftrag.get("skip_preflight"):
        preflight_workers = int(auftrag.get("preflight_workers") or 3)
        healthy, failed = preflight_and_filter(
            accounts, mode="dm", log=log,
            set_status_fn=lambda step: set_status("running", step, log),
            max_workers=preflight_workers,
        )
        if not healthy:
            set_status("error",
                       f"Preflight: ALLE {len(accounts)} Accounts haben Probleme — siehe Log",
                       log)
            return
        accounts = healthy

    set_status("running", f"Start — 0/{max_chats} DMs, {len(accounts)} Account(s)", log)

    for acc in accounts:
        try:
            sent = process_account(acc, max_chats, contacts, log)
            total += sent
        except Exception as e:
            print(f"\n❌ Kritischer Fehler bei {acc.get('name')}: {e}")
            log.append(f"KRITISCHER FEHLER {acc.get('name')}: {e}")

    # Abschluss
    elapsed = int(time.time() - start_time)
    mins, secs = divmod(elapsed, 60)
    summary = f"Run abgeschlossen — {total} DMs gesendet in {mins}m {secs}s"
    set_status("done", summary, log)

    print(f"\n{'═'*55}")
    print(f"  ✅ {summary}")
    print(f"{'═'*55}\n")


if __name__ == "__main__":
    main()
