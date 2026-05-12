#!/usr/bin/env python3
"""
blast_bot.py — Cross-Account DM Blast

Liest blast_auftrag.json:
  {
    "source_user_id": "k1bhvfaa",      # AdsPower-key in contacts.json (Empfänger-Quelle)
    "message":        "Hey ...",
    "accounts": [                       # Sender-Accounts (sequenziell)
      {"user_id": "k1b6096i", "name": "MIKE"},
      {"user_id": "k1b60cn6", "name": "..."}
    ]
  }

Empfänger werden aus contacts.json[source_user_id] extrahiert.
Pro Empfänger: navigiert zu  https://x.com/messages/compose?recipient_id=<id>
und sendet die Nachricht aus dem Sender-Account.

Bestehender dm_bot.py wird NICHT angefasst — eigenständiges Skript.

Starten:
    python blast_bot.py
"""

import json
import re
import time
import random
import datetime
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ═══════════════════════════════════════════════════════
#  PFADE
# ═══════════════════════════════════════════════════════
BASE_DIR        = Path(__file__).parent
AUFTRAG_PATH    = BASE_DIR / "blast_auftrag.json"
CONTACTS_PATH   = BASE_DIR / "contacts.json"
FOLLOWERS_PATH  = BASE_DIR / "follower_lists.json"
STATUS_PATH     = BASE_DIR / "blast_status.json"
LOG_PATH        = BASE_DIR / "blast_log.json"

# ═══════════════════════════════════════════════════════
#  PACING — 0.8–1.6 Sek random (sichere Untergrenze für X)
# ═══════════════════════════════════════════════════════
PACING_MIN = 0.8
PACING_MAX = 1.6

# ═══════════════════════════════════════════════════════
#  RATE-LIMIT DEFAULTS (vom Dashboard überschreibbar)
#  Werte basieren auf öffentlich berichteten X-DM-Limits.
# ═══════════════════════════════════════════════════════
DEFAULT_BATCH_SIZE      = 40    # DMs pro Batch
DEFAULT_BATCH_PAUSE_MIN = 30    # Pause zwischen Batches in Minuten
DEFAULT_DAILY_CAP       = 800   # max. DMs pro Sender pro UTC-Tag

# Default-PIN für DM-Encryption-Locks (kann via auftrag.json "dm_pin" überschrieben werden)
_DM_PIN = "0000"

# ═══════════════════════════════════════════════════════
#  ADSPOWER API
# ═══════════════════════════════════════════════════════
ADS_HOST = "http://local.adspower.net:50325"

def ads_open(user_id: str) -> str:
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
def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default

def save_json(path: Path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def set_status(state: str, step: str, log: list, current: str = ""):
    save_json(STATUS_PATH, {
        "state": state,
        "step": step,
        "current_account": current,
        "log": log
    })
    print(f"  [{state.upper()}] {step}")

# ═══════════════════════════════════════════════════════
#  EMPFÄNGER-EXTRAKTION AUS contacts.json[source]
# ═══════════════════════════════════════════════════════
CHAT_RE = re.compile(r'/i/chat/(\d+)-(\d+)')

def detect_source_numeric_id(entries: list) -> str:
    """
    Aus contacts.json[source]-Einträgen wird der Sender (= Source-Account)
    automatisch erkannt: das ist die numerische ID die in JEDEM Chat-URL-Paar vorkommt.
    """
    pairs = []
    for e in entries:
        url = e.get("url") or ""
        m = CHAT_RE.search(url)
        if m:
            pairs.append((m.group(1), m.group(2)))
    if not pairs:
        return ""
    common = set(pairs[0])
    for p in pairs[1:]:
        common &= set(p)
    if len(common) == 1:
        return common.pop()
    # Fallback: häufigste ID
    if common:
        return sorted(common)[0]
    return ""

def build_recipient_list_from_contacts(contacts: dict, source_user_id: str) -> list:
    """
    Baut Empfängerliste aus contacts.json[source_user_id].
    Returns: [{name, recipient_id, key}, ...]  — nur Einträge mit valider Chat-URL.
    """
    entries = contacts.get(source_user_id, [])
    if not entries:
        return []

    source_num = detect_source_numeric_id(entries)
    print(f"  Auto-detected source numeric ID: {source_num or '(none)'}")

    recipients = []
    for e in entries:
        url = e.get("url") or ""
        m = CHAT_RE.search(url)
        if not m:
            continue
        ids = [m.group(1), m.group(2)]
        rec_id = next((i for i in ids if i != source_num), None)
        if not rec_id:
            continue
        recipients.append({
            "name": e.get("name") or rec_id,
            "recipient_id": rec_id,
            "key": f"id:{rec_id}"
        })

    seen = set()
    unique = []
    for r in recipients:
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        unique.append(r)
    return unique

def build_recipient_list_from_followers(follower_lists: dict, source_user_id: str) -> list:
    """
    Baut Empfängerliste aus follower_lists.json[source_user_id].
    Returns: [{name, handle, key}, ...]
    """
    entries = follower_lists.get(source_user_id, [])
    if not entries:
        return []

    out = []
    seen = set()
    for e in entries:
        h = (e.get("handle") or "").strip().lstrip("@")
        if not h:
            continue
        if h.lower() in seen:
            continue
        seen.add(h.lower())
        out.append({
            "name": e.get("name") or h,
            "handle": h,
            "key": f"h:{h.lower()}"
        })
    return out

# ═══════════════════════════════════════════════════════
#  COMPOSE-NAVIGATION + DM SENDEN
# ═══════════════════════════════════════════════════════
def find_composer(page):
    # WICHTIG: das eigentliche Eingabefeld treffen, NICHT den Wrapper-Container
    # 'dm-composer-container' ist nur ein Layout-div und nicht klickbar.
    priority = [
        '[data-testid="dmComposerTextInput"]',
        'div[data-testid="dm-composer-container"] div[contenteditable="true"]',
        'div[data-testid="dm-composer-container"] [role="textbox"]',
        'div[contenteditable="true"][data-testid*="dmComposer"]',
        '[role="textbox"][contenteditable="true"]',
        'div[contenteditable="true"]',
        'textarea',
    ]
    for sel in priority:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=500):
                return el
        except PWTimeout:
            continue
    return None

def find_send_button(page):
    selectors = [
        '[data-testid="dmComposerSendButton"]',
        '[data-testid="dm-composer-send-button"]',
        '[data-testid="dm-send-button"]',
        'button[data-testid*="send"]',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=250):   # was 1000
                return btn
        except PWTimeout:
            continue
    return None

def page_has_error(page) -> bool:
    """
    Erkennt typische X-Fehlerseiten ('Something went wrong', 'Try again',
    'Hmm…page doesn't exist', leerer Body, etc.).
    """
    try:
        txt = (page.evaluate("() => document.body ? document.body.innerText : ''") or "")[:3000].lower()
    except Exception:
        return True   # DOM nicht zugreifbar → behandeln wie Fehler
    if not txt or len(txt) < 20:
        return True   # Body zu leer → Seite hat nicht richtig geladen
    markers = [
        "something went wrong",
        "try again",
        "try refreshing",
        "hmm…this page",
        "hmm...this page",
        "this page doesn’t exist",
        "this page doesn't exist",
        "rate limit exceeded",
        "give us a few seconds",
        "retry",
    ]
    return any(m in txt for m in markers)

def recover_if_errored(page, max_reloads: int = 2) -> bool:
    """
    Reloadet die Seite wenn ein X-Fehler erkannt wird.
    Returns True wenn nach Reload kein Fehler mehr da ist.
    """
    for attempt in range(max_reloads):
        if not page_has_error(page):
            return True
        try:
            print(f"      ⟳ Page-Error → Reload {attempt+1}/{max_reloads}")
            page.reload(wait_until="domcontentloaded", timeout=25000)
            time.sleep(2.5)
        except Exception as e:
            print(f"      Reload-Fehler: {e}")
            time.sleep(3)
    return not page_has_error(page)

# ─── X-spezifischer "Something wrong with Chat"-Bug ───
# Tritt auf wenn X's IndexedDB für DMs korrupt wird. Plain reload reicht NICHT,
# der Browser-Storage muss gelöscht werden ODER X's eigener Button geklickt.
def is_chat_broken(page) -> bool:
    try:
        txt = (page.evaluate("() => document.body ? document.body.innerText : ''") or "").lower()
    except Exception:
        return False
    return ("something wrong with chat" in txt) or \
           ("clear cache and refresh" in txt and ("/messages" in (page.url or "")))

def is_dms_closed(page) -> bool:
    """Empfänger hat DMs nur für Follower/Verified — Bot kann nichts machen."""
    try:
        txt = (page.evaluate("() => document.body ? document.body.innerText : ''") or "").lower()
    except Exception:
        return False
    markers = [
        "you can’t send messages to this person",
        "you can't send messages to this person",
        "you can't message this person",
        "you can’t message this person",
        "doesn’t allow messages",
        "doesn't allow messages",
        "this account does not receive messages",
        "this account doesn't accept",
        "this account doesn’t accept",
    ]
    return any(m in txt for m in markers)

def recover_chat_broken(page) -> bool:
    """
    Behebt X's 'Something wrong with Chat'-Fehler automatisch:
      1. Versuch: X's eigenen 'Clear cache and refresh'-Button klicken
      2. Fallback: IndexedDB für x.com programmatisch löschen + Reload
    Returns True wenn nach Recovery kein Chat-Fehler mehr da ist.
    """
    print(f"      ⚠ Chat-Broken-Fehler erkannt — starte Auto-Recovery")
    # Variante A: X's eigenen Button klicken (sauberste Lösung)
    try:
        btn = page.locator('button:has-text("Clear cache and refresh"), div[role="button"]:has-text("Clear cache and refresh")').first
        if btn.is_visible(timeout=1500):
            btn.click(timeout=3000)
            time.sleep(4)
            if not is_chat_broken(page):
                print(f"      ✓ Recovery via X's Clear-Cache-Button")
                return True
    except Exception:
        pass
    # Variante B: IndexedDB programmatisch löschen
    try:
        page.evaluate("""
            async () => {
                try {
                    if(indexedDB.databases){
                        const dbs = await indexedDB.databases();
                        for (const db of dbs) { if(db.name) indexedDB.deleteDatabase(db.name); }
                    }
                } catch(e) {}
                try {
                    const keys = Object.keys(localStorage);
                    for(const k of keys){
                        const lk = k.toLowerCase();
                        if (lk.includes('chat') || lk.includes('dm') || lk.includes('message') || lk.includes('conversation')) {
                            localStorage.removeItem(k);
                        }
                    }
                } catch(e) {}
                try { sessionStorage.clear(); } catch(e) {}
            }
        """)
        time.sleep(1.5)
        page.reload(wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)
        if not is_chat_broken(page):
            print(f"      ✓ Recovery via IndexedDB-Clear")
            return True
    except Exception as e:
        print(f"      Storage-Clear fehlgeschlagen: {e}")
    return False

def is_pin_locked(page) -> bool:
    """Heuristik: PIN-Screen erkennt man an Eingabefeldern für 4 Stellen / 'passcode' / 'PIN'."""
    try:
        txt = page.evaluate("() => document.body.innerText.toLowerCase()") or ""
    except Exception:
        return False
    if "passcode" in txt or "pin code" in txt or "encrypted message" in txt:
        try:
            n = page.evaluate("""() => document.querySelectorAll('input[inputmode="numeric"], input[type="tel"]').length""")
            if n and n >= 4:
                return True
        except Exception:
            pass
    return False

def unlock_dm_pin(page, pin: str = "0000") -> bool:
    """
    Tippt den DM-PIN automatisch in den X-Passcode-Screen.
    Returns True wenn nach dem Eintippen der PIN-Screen weg ist.
    """
    if not pin or len(pin) < 4:
        return False
    print(f"      🔓 DM-PIN automatisch eintippen ({len(pin)}-stellig)")
    try:
        # Erst Single-Field-Variante (manche X-Versionen haben EIN Feld, nicht 4)
        try:
            single = page.locator('input[inputmode="numeric"], input[type="tel"], input[type="password"]').first
            if single.is_visible(timeout=600):
                try:
                    single.click(timeout=1500)
                    time.sleep(0.1)
                    single.fill("")  # leeren falls schon was drinsteht
                    page.keyboard.type(pin, delay=80)
                    time.sleep(0.6)
                    # falls Single-Field: prüfen ob PIN-Screen weg
                    if not is_pin_locked(page):
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        # Multi-Field-Variante (4 separate Boxen) — Ziffer für Ziffer
        inputs = page.locator('input[inputmode="numeric"], input[type="tel"]')
        cnt = inputs.count()
        if cnt >= len(pin):
            for i, digit in enumerate(pin):
                try:
                    inp = inputs.nth(i)
                    inp.click(timeout=1200)
                    time.sleep(0.08)
                    inp.fill(digit)
                except Exception:
                    try:
                        page.keyboard.type(digit, delay=80)
                    except Exception:
                        pass
            time.sleep(0.8)
        else:
            # Fallback: einfach tippen, X fängt's selbst auf
            try:
                page.keyboard.type(pin, delay=80)
                time.sleep(0.6)
            except Exception:
                pass

        # Unlock-Button (falls nicht auto-submit)
        for sel in [
            '[data-testid="OcfEnterPinFormUnlockButton"]',
            'button:has-text("Unlock")',
            'div[role="button"]:has-text("Unlock")',
            'button:has-text("Confirm")',
            'button:has-text("Submit")',
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=400):
                    btn.click(timeout=2000)
                    break
            except Exception:
                continue
        time.sleep(1.5)
        return not is_pin_locked(page)
    except Exception as e:
        print(f"      PIN-Unlock-Fehler: {e}")
        return False

def is_browser_dead(page) -> bool:
    """Prüft ob der Playwright-Browser-Context noch lebt."""
    try:
        _ = page.url
        return False
    except Exception:
        return True

def _type_and_send(page, message: str) -> tuple:
    """Composer suchen, tippen, senden. Returns (success, reason)."""
    # kein pre-find Sleep — wait_for_selector hat schon gewartet
    composer = find_composer(page)
    if composer is None:
        return False, "composer-not-visible"
    try:
        composer.click(timeout=2000)
        time.sleep(0.1)
        parts = message.split("\n")
        for i, part in enumerate(parts):
            page.keyboard.type(part, delay=10)
            if i < len(parts) - 1:
                page.keyboard.press("Shift+Enter")
        time.sleep(0.15)
    except Exception as e:
        return False, f"type-fail: {e}"

    btn = find_send_button(page)
    if btn:
        try:
            btn.click(timeout=1500)
        except Exception:
            try:
                page.keyboard.press("Enter")
            except Exception as e:
                return False, f"send-fail: {e}"
    else:
        try:
            page.keyboard.press("Enter")
        except Exception as e:
            return False, f"send-fail: {e}"
    time.sleep(0.3)
    return True, "ok"

def send_via_compose_url(page, recipient_id: str, message: str) -> tuple:
    """ID-basierter Send (für contacts.json-Quelle)."""
    url = f"https://x.com/messages/compose?recipient_id={recipient_id}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        return False, f"goto-fail: {e}"
    if "login" in page.url.lower() or "/i/flow/login" in page.url:
        return False, "not-logged-in"
    # kein post-goto sleep — Body-Check ist schnell, wait_for_selector wartet sowieso
    # X-spezifischer Chat-Broken-Fehler → Cache leeren + neu navigieren
    if is_chat_broken(page):
        if recover_chat_broken(page):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                return False, f"recovery-goto-fail: {e}"
        else:
            return False, "chat-broken-unrecoverable"
    if is_pin_locked(page):
        # Auto-Unlock mit konfiguriertem PIN (Default 0000)
        if not unlock_dm_pin(page, _DM_PIN):
            return False, "pin-locked"
        # Nach Unlock zur compose-URL navigieren
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            return False, f"post-unlock-goto-fail: {e}"
        if is_pin_locked(page):
            return False, "pin-still-locked"
    try:
        page.wait_for_selector(
            '[data-testid="dmComposerTextInput"], div[contenteditable="true"], textarea',
            timeout=5000
        )
    except PWTimeout:
        # Erst prüfen: ist das ein „closed DMs"-Empfänger? Dann macht reload nichts.
        if is_dms_closed(page):
            return False, "dms-closed"
        # Sonst Lade-Hänger — einmal reloaden + nochmal versuchen
        try:
            page.reload(wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector(
                '[data-testid="dmComposerTextInput"], div[contenteditable="true"], textarea',
                timeout=5000
            )
        except Exception:
            if is_dms_closed(page):
                return False, "dms-closed"
            return False, "no-composer"
    return _type_and_send(page, message)

def send_via_profile(page, handle: str, message: str) -> tuple:
    """Handle-basierter Send (für follower_lists.json-Quelle)."""
    url = f"https://x.com/{handle}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        return False, f"goto-fail: {e}"
    if "login" in page.url.lower() or "/i/flow/login" in page.url:
        return False, "not-logged-in"
    time.sleep(0.5)                       # was 0.8
    # X-Fehler abfangen → reloaden
    if not recover_if_errored(page):
        return False, "page-error"
    if is_pin_locked(page):
        return False, "pin-locked"

    # Profil-Existenz: 404/suspended-Hinweise abfangen (NACH Recover-Check, sonst gibt page-error den Kampf auf)
    try:
        body_txt = page.evaluate("() => document.body.innerText.toLowerCase()") or ""
    except Exception:
        body_txt = ""
    if "this account doesn’t exist" in body_txt or "this account doesn't exist" in body_txt:
        return False, "profile-missing"
    if "account suspended" in body_txt:
        return False, "account-suspended"

    # Message-Button auf Profilseite suchen
    btn_selectors = [
        '[data-testid="sendDMFromProfile"]',
        'a[href$="/messages"][role="link"]',
        '[aria-label="Message"]',
    ]
    clicked = False
    for sel in btn_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=3000)
                clicked = True
                break
        except (PWTimeout, Exception):
            continue
    if not clicked:
        return False, "no-dm-button"

    # Composer kann als Modal oder neue Seite erscheinen
    time.sleep(1.0)
    try:
        page.wait_for_selector(
            '[data-testid="dmComposerTextInput"], div[contenteditable="true"], textarea',
            timeout=6000
        )
    except PWTimeout:
        return False, "no-composer-after-click"
    return _type_and_send(page, message)

def send_dm_to_recipient(page, recipient: dict, message: str) -> tuple:
    """Dispatcher: nutzt compose-URL bei recipient_id, Profil-Klick bei handle."""
    if recipient.get("recipient_id"):
        return send_via_compose_url(page, recipient["recipient_id"], message)
    if recipient.get("handle"):
        return send_via_profile(page, recipient["handle"], message)
    return False, "no-id-or-handle"

# ═══════════════════════════════════════════════════════
#  ACCOUNT VERARBEITEN
# ═══════════════════════════════════════════════════════
def count_today_sends(blast_log: dict, sender_user_id: str) -> int:
    """Erfolgreiche DMs (status='ok') von DIESEM Sender heute (UTC)."""
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    n = 0
    for e in blast_log.get(sender_user_id, []):
        if e.get("status") != "ok":
            continue
        ts = e.get("ts") or ""
        if ts.startswith(today):
            n += 1
    return n

def already_blasted_keys(blast_log: dict, sender_user_id: str) -> set:
    """Dedup-Keys (id:<num> oder h:<handle>) für bereits abgearbeitete Empfänger."""
    keys = set()
    for e in blast_log.get(sender_user_id, []):
        if e.get("recipient_id"):
            keys.add(f"id:{e['recipient_id']}")
        if e.get("handle"):
            keys.add(f"h:{(e['handle'] or '').lower()}")
    return keys

def add_blast_log(blast_log: dict, sender_user_id: str, recipient: dict, status: str):
    if sender_user_id not in blast_log:
        blast_log[sender_user_id] = []
    entry = {
        "name": recipient.get("name", ""),
        "status": status,
        "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    }
    if recipient.get("recipient_id"):
        entry["recipient_id"] = recipient["recipient_id"]
    if recipient.get("handle"):
        entry["handle"] = recipient["handle"]
    blast_log[sender_user_id].append(entry)

def process_one_batch(state: dict, message: str, blast_log: dict, log: list,
                      batch_size: int, daily_cap: int):
    """
    Verarbeitet GENAU EINEN Batch (bis batch_size erfolgreiche Sends ODER Daily-Cap
    ODER todo leer). Mutiert state in-place. Browser wird AM ENDE geschlossen,
    damit der Scheduler andere Accounts während der Batch-Pause verarbeiten kann.
    Raises Exception (z.B. AdsPower-Fehler) — wird im Scheduler abgefangen.
    """
    user_id = state["user_id"]
    name    = state["name"]
    todo    = state["todo"]

    if not todo:
        return

    day_count = state["day_count_start"] + state["sent"]
    if day_count >= daily_cap:
        state["done_today"] = True
        log.append(f"{name}: Tageslimit {daily_cap} erreicht.")
        return

    remaining_today = daily_cap - day_count
    batch_target = min(batch_size, remaining_today, len(todo))
    print(f"\n  ▶ {name}: Batch — Ziel {batch_target} (von {len(todo)} todo, heute {day_count}/{daily_cap})")
    set_status("running", f"{name} – Batch startet ({state['sent']} bisher gesendet)", log, name)

    ws_url = ads_open(user_id)   # raises on disk-full
    time.sleep(4)

    sent_this_batch = 0
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.connect_over_cdp(ws_url)
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            print("  Lade x.com/messages …")
            page.goto("https://x.com/messages", wait_until="domcontentloaded", timeout=25000)
            if "login" in page.url.lower() or "/i/flow/login" in page.url:
                print(f"  🔒 {name}: nicht eingeloggt — wird übersprungen")
                log.append(f"🔒 {name}: nicht eingeloggt → übersprungen, nächster Account.")
                state["disabled"] = True
                state["skip_reason"] = "not-logged-in"
                return
            time.sleep(1.5)
            if is_pin_locked(page):
                print(f"  🔓 {name}: DM-PIN aktiv — versuche Auto-Unlock mit {_DM_PIN}")
                log.append(f"{name}: DM-PIN aktiv — Auto-Unlock-Versuch mit {_DM_PIN}.")
                if unlock_dm_pin(page, _DM_PIN):
                    log.append(f"{name}: ✓ PIN-Unlock erfolgreich.")
                    print(f"      ✓ PIN entsperrt")
                    time.sleep(1)
                else:
                    print(f"  🔓 {name}: PIN-Unlock fehlgeschlagen — wird übersprungen")
                    log.append(f"🔓 {name}: PIN-Unlock mit {_DM_PIN} fehlgeschlagen → übersprungen.")
                    state["disabled"] = True
                    state["skip_reason"] = "pin-locked"
                    return

            consecutive_errors = 0
            while todo and sent_this_batch < batch_target:
                r = todo[0]
                rname = r["name"]

                if consecutive_errors >= 3:
                    print(f"  ⟳ {name}: {consecutive_errors} Fehler in Folge — Auto-Recovery")
                    log.append(f"{name}: {consecutive_errors} Fehler in Folge — Auto-Recovery (Reload + 15s).")
                    try:
                        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20000)
                        time.sleep(15)
                    except Exception:
                        time.sleep(15)
                    consecutive_errors = 0

                # Browser-Tod prüfen — wenn Page/Context/Browser geschlossen ist,
                # brauchen wir nicht weiter zu versuchen — Batch abbrechen
                if is_browser_dead(page):
                    log.append(f"⛔ {name}: Browser/Context verloren — Batch abgebrochen ({sent_this_batch} done).")
                    print(f"  ⛔ {name}: Browser dead → break batch")
                    break

                try:
                    ok, reason = send_dm_to_recipient(page, r, message)
                except Exception as ex:
                    ok, reason = False, f"unhandled: {ex}"

                # Wenn der Fehler 'browser has been closed' enthält → Batch abbrechen
                if not ok and ("has been closed" in (reason or "") or "target page" in (reason or "").lower()):
                    state["errors"] += 1
                    consecutive_errors += 1
                    add_blast_log(blast_log, user_id, r, f"err:{reason}")
                    save_json(LOG_PATH, blast_log)
                    log.append(f"⛔ {name}: {r['name']} ✗ (browser-closed) — Batch abgebrochen.")
                    print(f"    ⛔ {name}: browser closed → break batch")
                    todo.pop(0)
                    break

                if ok:
                    state["sent"] += 1
                    sent_this_batch += 1
                    consecutive_errors = 0
                    add_blast_log(blast_log, user_id, r, "ok")
                    save_json(LOG_PATH, blast_log)
                    log.append(f"{name}: {rname} ✓")
                    day = state["day_count_start"] + state["sent"]
                    set_status("running",
                        f"{name} – Batch {sent_this_batch}/{batch_target} (heute {day}/{daily_cap}, Total {state['sent']})",
                        log, name)
                    print(f"    ✓ {name}: [{sent_this_batch}/{batch_target}] {rname}  (heute {day}/{daily_cap})")
                else:
                    state["errors"] += 1
                    consecutive_errors += 1
                    add_blast_log(blast_log, user_id, r, f"err:{reason}")
                    save_json(LOG_PATH, blast_log)
                    log.append(f"{name}: {rname} ✗ ({reason})")
                    print(f"    ✗ {name}: {rname} — {reason}")

                todo.pop(0)
                time.sleep(random.uniform(PACING_MIN, PACING_MAX))

        except Exception as e:
            log.append(f"KRITISCHER FEHLER {name}: {e}")
            print(f"  ❌ {name}: {e}")
            raise
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:
                pass

    ads_close(user_id)
    time.sleep(2)
    if todo:
        log.append(f"{name}: Batch fertig ({sent_this_batch} Sends) — pausiert, {len(todo)} todo")
        print(f"  ⏸  {name}: Batch fertig, geht in Pause ({len(todo)} verbleibend)")
    else:
        log.append(f"{name}: ALLE Empfänger fertig ({state['sent']} total gesendet).")
        print(f"  ✓ {name}: ALLE fertig — {state['sent']} Sends insgesamt")

# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════
def main():
    start = time.time()
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    print(f"\n{'═'*55}")
    print(f"  blast_bot.py  —  Start: {now_str}")
    print(f"{'═'*55}")

    auftrag   = load_json(AUFTRAG_PATH, {})
    blast_log = load_json(LOG_PATH, {})

    if not auftrag or not auftrag.get("accounts") or not auftrag.get("source_user_id"):
        print("⏭  Kein Blast-Auftrag — übersprungen.")
        set_status("skipped", "Kein Blast-Auftrag — übersprungen", [])
        return

    source       = auftrag["source_user_id"]
    source_type  = (auftrag.get("source_type") or "contacts").lower()
    accounts_raw = auftrag["accounts"]
    # AVAILABLE-Platzhalter (ungenutzte AdsPower-Profile ohne X-Login) rausfiltern
    accounts = []
    available_skipped = []
    for a in accounts_raw:
        if (a.get("name") or "").strip().upper() == "AVAILABLE":
            available_skipped.append(a.get("user_id") or "?")
        else:
            accounts.append(a)
    if available_skipped:
        print(f"  ⏭  AVAILABLE-Platzhalter übersprungen: {len(available_skipped)} ({', '.join(available_skipped)})")
    message      = auftrag.get("message", "")
    # Rate-Limit-Konfiguration (mit Defaults)
    batch_size       = int(auftrag.get("batch_size") or DEFAULT_BATCH_SIZE)
    batch_pause_min  = int(auftrag.get("batch_pause_min") or DEFAULT_BATCH_PAUSE_MIN)
    daily_cap        = int(auftrag.get("daily_cap") or DEFAULT_DAILY_CAP)
    batch_pause_sec  = max(0, batch_pause_min) * 60
    if batch_size < 1: batch_size = 1
    if daily_cap < 1: daily_cap = 1
    # DM-PIN für Auto-Unlock (alle Accounts → derselbe PIN; aus auftrag.json override-bar)
    global _DM_PIN
    _DM_PIN = (auftrag.get("dm_pin") or _DM_PIN).strip() or "0000"

    if not message.strip():
        print("⏭  Leere Nachricht — übersprungen.")
        set_status("skipped", "Leere Nachricht", [])
        return

    if source_type == "followers":
        follower_lists = load_json(FOLLOWERS_PATH, {})
        recipients = build_recipient_list_from_followers(follower_lists, source)
        if not recipients:
            print(f"⏭  Keine Followers in follower_lists.json[{source}].")
            set_status("skipped", f"Keine Followers in [{source}]", [])
            return
        print(f"  Empfänger-Pool: {len(recipients)} Followers (handle-basiert)")
    else:
        contacts = load_json(CONTACTS_PATH, {})
        recipients = build_recipient_list_from_contacts(contacts, source)
        if not recipients:
            print(f"⏭  Keine Empfänger in contacts.json[{source}] mit Chat-URL.")
            set_status("skipped", f"Keine Empfänger in [{source}]", [])
            return
        print(f"  Empfänger-Pool: {len(recipients)} Chats (id-basiert)")

    print(f"  Sender-Accounts: {len(accounts)}")
    print(f"  Nachricht: {message[:60]}{'…' if len(message)>60 else ''}")
    print(f"  Rate-Limits: Batch={batch_size}, Pause={batch_pause_min}min, Tageslimit={daily_cap}")

    log = []
    if available_skipped:
        log.append(f"⏭  AVAILABLE-Platzhalter ignoriert ({len(available_skipped)}): {', '.join(available_skipped)}")
    set_status("running", f"Start — {len(recipients)} Ziele × {len(accounts)} Accounts (interleaved)", log)

    # ─── Per-Account State initialisieren ───────────────
    states = []
    for acc in accounts:
        uid = acc["user_id"]
        nm  = acc.get("name") or uid
        done = already_blasted_keys(blast_log, uid)
        todo = [r for r in recipients if r.get("key") not in done]
        skipped = len(recipients) - len(todo)
        day_start = count_today_sends(blast_log, uid)
        if skipped:
            log.append(f"{nm}: {skipped} bereits geblastet, übersprungen.")
        if day_start:
            log.append(f"{nm}: heute schon {day_start} DMs gesendet (Cap {daily_cap}).")
        states.append({
            "user_id": uid,
            "name": nm,
            "todo": todo,
            "skipped": skipped,
            "sent": 0,
            "errors": 0,
            "day_count_start": day_start,
            "next_eligible": 0.0,
            "disabled": False,
            "skip_reason": "",
            "done_today": False,
            "disk_full": False,
        })

    # ─── Round-Robin Scheduler: interleaved Batches ────
    # Während Account A 30min pausiert, wird B (und C, …) bearbeitet.
    while True:
        now = time.time()
        ready = []
        active = []
        for st in states:
            if st["disabled"] or st["disk_full"] or st["done_today"] or not st["todo"]:
                continue
            day = st["day_count_start"] + st["sent"]
            if day >= daily_cap:
                st["done_today"] = True
                continue
            active.append(st)
            if st["next_eligible"] <= now:
                ready.append(st)

        if not active:
            break  # Alles fertig

        if not ready:
            # Alle pausieren — warte bis erster wieder darf
            wait_until = min(st["next_eligible"] for st in active)
            wait_sec = max(0, wait_until - now)
            mins = int(wait_sec // 60); secs = int(wait_sec % 60)
            resume_at = datetime.datetime.fromtimestamp(wait_until).strftime("%H:%M")
            msg = f"Alle {len(active)} Accounts pausieren — Wake-up um {resume_at} (~{mins}m{secs:02d}s)"
            print(f"\n  ⏸  {msg}")
            set_status("running", msg, log)
            remaining = wait_sec
            while remaining > 0:
                time.sleep(min(60, remaining))
                remaining -= 60
            continue

        # Pick FIFO — fairer wäre rotating, aber FIFO ist okay
        st = ready[0]
        try:
            process_one_batch(st, message, blast_log, log, batch_size, daily_cap)
            st["next_eligible"] = time.time() + batch_pause_sec
        except Exception as e:
            emsg = str(e).lower()
            if "running out of disk" in emsg or "disk space" in emsg or "out of disk" in emsg:
                log.append(f"⛔ AdsPower-Disk voll bei {st['name']} — Account aus Run entfernt.")
                print(f"\n❌ Disk-Space bei {st['name']}")
                st["disk_full"] = True
                st["skip_reason"] = "disk-full"
            else:
                log.append(f"KRITISCH {st['name']}: {e}")
                st["disabled"] = True
                st["skip_reason"] = "critical-error"

    total_sent = sum(st["sent"] for st in states)
    total_skip = sum(st["skipped"] for st in states)
    total_err  = sum(st["errors"] for st in states)

    # ─── Final-Summary im Log: welche Accounts wurden warum übersprungen ───
    not_logged_in = [st["name"] for st in states if st.get("skip_reason") == "not-logged-in"]
    pin_locked    = [st["name"] for st in states if st.get("skip_reason") == "pin-locked"]
    disk_full_l   = [st["name"] for st in states if st.get("skip_reason") == "disk-full"]
    critical      = [st["name"] for st in states if st.get("skip_reason") == "critical-error"]
    completed     = [st["name"] for st in states if not st.get("skip_reason") and not st["todo"] and st["sent"] > 0]

    log.append("─── Abschluss-Übersicht ───")
    if not_logged_in:
        log.append(f"🔒 NICHT EINGELOGGT (übersprungen, {len(not_logged_in)}): {', '.join(not_logged_in)}")
    if pin_locked:
        log.append(f"🔓 PIN-LOCK (PIN {_DM_PIN} hat nicht funktioniert, {len(pin_locked)}): {', '.join(pin_locked)}")
    if disk_full_l:
        log.append(f"💾 ADSPOWER DISK VOLL ({len(disk_full_l)}): {', '.join(disk_full_l)}")
    if critical:
        log.append(f"❌ KRITISCHE FEHLER ({len(critical)}): {', '.join(critical)}")
    if completed:
        log.append(f"✅ VOLLSTÄNDIG ABGESCHLOSSEN ({len(completed)}): {', '.join(completed)}")
    if not (not_logged_in or pin_locked or disk_full_l or critical) and not completed:
        log.append("Keine Accounts mit speziellem Status — siehe Per-Account-Breakdown unten.")

    elapsed = int(time.time() - start)
    mins, secs = divmod(elapsed, 60)
    summary = (
        f"Blast fertig — {total_sent} DMs gesendet "
        f"({total_skip} skip, {total_err} Fehler) in {mins}m {secs}s"
    )
    set_status("done", summary, log)
    print(f"\n{'═'*55}")
    print(f"  ✅ {summary}")
    # Per-Account-Breakdown
    for st in states:
        flag = ""
        if st["disabled"]: flag = " [disabled]"
        elif st["disk_full"]: flag = " [disk-full]"
        elif not st["todo"]: flag = " [done]"
        elif st["done_today"]: flag = " [cap-reached]"
        print(f"     {st['name']}: {st['sent']} sent, {st['errors']} err, {len(st['todo'])} todo{flag}")
    print(f"{'═'*55}\n")


if __name__ == "__main__":
    from safety_guard import require_live_or_exit
    require_live_or_exit("blast_bot")
    main()
