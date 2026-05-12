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
import time
import datetime
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

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
    # Safety hook: dry-run logs, live counts. See safety_guard.py.
    import safety_guard
    snippet = (message or "")[:60].replace("\n", " ")
    if safety_guard.is_dry_run():
        safety_guard.dry_run_log(f"would send DM (msg: {snippet!r}…)")
        return True
    safety_guard.record_action_or_exit(f"DM (msg: {snippet!r}…)")
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
    start_time = time.time()
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    print(f"\n{'═'*55}")
    print(f"  dm_bot.py  —  Start: {now_str}")
    print(f"{'═'*55}")

    # Dateien laden
    auftrag  = load_json(AUFTRAG_PATH)
    contacts = load_json(CONTACTS_PATH)

    if not auftrag or not auftrag.get("accounts"):
        print("⏭  Kein Auftrag heute — übersprungen.")
        set_status("skipped", "Kein Auftrag heute — übersprungen", [])
        return

    accounts  = auftrag["accounts"]
    max_chats = auftrag.get("max_chats", 50)
    log       = []
    total     = 0

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


def _dry_run_walkthrough():
    """
    Print what main() would do — config only, no browser / AdsPower / Playwright.
    dm_bot discovers actual DM targets live (by scrolling x.com chat list), so
    per-DM walkthrough isn't possible from config alone. We log per-account.
    """
    import safety_guard
    print(f"\n{'═'*55}")
    print(f"  dm_bot — DRY-RUN walkthrough (no browser, no AdsPower)")
    print(f"{'═'*55}")

    auftrag = load_json(AUFTRAG_PATH)
    if not auftrag or not auftrag.get("accounts"):
        print(f"  ⏭  auftrag.json missing/empty — no DMs would be sent.")
        print(f"     Expected at: {AUFTRAG_PATH}")
        return

    accounts  = auftrag.get("accounts", [])
    max_chats = auftrag.get("max_chats", 50)
    message   = auftrag.get("message", "")

    print(f"  Accounts : {len(accounts)} sender(s)")
    print(f"  max_chats: {max_chats} DM(s) per account")
    print(f"  Message  : {message[:60]}{'…' if len(message) > 60 else ''}")
    print(f"  Note     : targets are discovered live by scrolling x.com — not listable here.")
    if not accounts:
        print(f"  ⏭  No accounts — nothing would be sent.")
        return

    for acc in accounts:
        name = acc.get("name") or acc.get("user_id") or "?"
        safety_guard.dry_run_log(f"would process account {name} (up to {max_chats} DMs)")
    print(f"  ✓ Walkthrough complete. No DM was sent.")


if __name__ == "__main__":
    from safety_guard import require_live_or_exit, is_dry_run
    require_live_or_exit("dm_bot")
    if is_dry_run():
        _dry_run_walkthrough()
        raise SystemExit(0)
    main()
