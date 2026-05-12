#!/usr/bin/env python3
"""
builder_bot.py — Database Builder

Baut eine neue Empfängerliste OHNE zu senden.

Liest builder_auftrag.json:
  {
    "mode": "followers" | "chats",
    "user_id": "k1bhvfaa",
    "name":    "AVAILABLE"
  }

mode "followers":
  Öffnet AdsPower für user_id, navigiert zu x.com/<handle>/verified_followers
  (Fallback /followers), scrollt + scrapt {handle, name} pro User-Cell.
  Speichert in follower_lists.json[user_id] (überschreibt mit Merge by handle).

mode "chats":
  Öffnet AdsPower, navigiert zu x.com/messages, scrollt komplette Chatliste,
  sammelt {name, url} pro Chat-Link. Schreibt in contacts.json[user_id]
  (Merge mit bestehendem Archiv — nur neue Einträge werden ergänzt; vorhandene
  last_sent-Timestamps bleiben unverändert).

Keine DM wird gesendet.

Starten:
    python builder_bot.py
"""
import json
import re
import time
import datetime
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ═══════════════════════════════════════════════════════
#  PFADE
# ═══════════════════════════════════════════════════════
BASE_DIR        = Path(__file__).parent
AUFTRAG_PATH    = BASE_DIR / "builder_auftrag.json"
STATUS_PATH     = BASE_DIR / "builder_status.json"
CONTACTS_PATH   = BASE_DIR / "contacts.json"
FOLLOWERS_PATH  = BASE_DIR / "follower_lists.json"

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
        raise RuntimeError(f"AdsPower Fehler: {data}")
    ws = data["data"]["ws"]["puppeteer"]
    print(f"  Browser offen ({ws[:50]}…)")
    return ws

def ads_close(user_id: str):
    try:
        requests.get(f"{ADS_HOST}/api/v1/browser/stop",
                     params={"user_id": user_id}, timeout=10)
    except Exception:
        pass

# ═══════════════════════════════════════════════════════
#  JSON HELPER
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

def set_status(state: str, step: str, log: list):
    save_json(STATUS_PATH, {"state": state, "step": step, "log": log})
    print(f"  [{state.upper()}] {step}")

# ═══════════════════════════════════════════════════════
#  DETECT OWN HANDLE (current logged-in @handle)
# ═══════════════════════════════════════════════════════
def detect_own_handle(page) -> str:
    """
    Versucht den eingeloggten Benutzer-Handle zu ermitteln.
    Strategie: navigiere zu x.com/home, lese den AccountSwitcher-Avatar-Link.
    """
    try:
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
        handle = page.evaluate("""() => {
            // 1) Side-Nav profile link
            const a = document.querySelector('a[data-testid="AppTabBar_Profile_Link"]');
            if(a){
                const m = (a.getAttribute('href')||'').match(/^\\/([A-Za-z0-9_]+)\\/?$/);
                if(m) return m[1];
            }
            // 2) Account switcher
            const sw = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]');
            if(sw){
                const span = sw.querySelector('span[dir="ltr"]');
                if(span && span.textContent.startsWith('@')) return span.textContent.replace('@','').trim();
            }
            return '';
        }""") or ""
        return handle.strip()
    except Exception:
        return ""

# ═══════════════════════════════════════════════════════
#  MODE 1: FOLLOWERS SCRAPER
# ═══════════════════════════════════════════════════════
def scrape_followers_js(page) -> list:
    """Scrapt sichtbare User-Cells aus dem Followers-Page-DOM."""
    # Safety hook: dry-run returns empty, live counts. See safety_guard.py.
    import safety_guard
    if safety_guard.is_dry_run():
        safety_guard.dry_run_log("would scrape visible follower cells")
        return []
    safety_guard.record_action_or_exit("scrape follower cells")
    try:
        return page.evaluate("""
            () => {
                const out = [];
                const cells = document.querySelectorAll('[data-testid="UserCell"]');
                for(const cell of cells){
                    const link = cell.querySelector('a[href^="/"]');
                    if(!link) continue;
                    const href = link.getAttribute('href') || '';
                    const m = href.match(/^\\/([A-Za-z0-9_]+)\\/?$/);
                    if(!m) continue;
                    const handle = m[1];
                    if(['home','explore','notifications','messages','i','settings','search'].includes(handle.toLowerCase())) continue;
                    let name = '';
                    const nameEl = cell.querySelector('div[data-testid="User-Name"] span span') ||
                                   cell.querySelector('span[dir="ltr"]');
                    if(nameEl) name = nameEl.textContent.trim();
                    out.push({handle, name: name || handle});
                }
                return out;
            }
        """) or []
    except Exception:
        return []

def scroll_followers(page):
    """
    Robustes Scrollen für X's virtualisierte Followers-Liste:
    scrollIntoView auf die letzte sichtbare UserCell zwingt X den nächsten
    Batch zu laden — funktioniert egal welcher Container der echte Scroller ist.
    """
    try:
        page.evaluate("""
            () => {
                const cells = document.querySelectorAll('[data-testid="UserCell"]');
                if(cells.length){
                    const last = cells[cells.length - 1];
                    last.scrollIntoView({block:'end', behavior:'instant'});
                    // Zusätzlich noch einmal harten Scroll-Schub geben für Container die nicht auf scrollIntoView reagieren
                    let el = last.parentElement;
                    while(el && el !== document.body){
                        const s = window.getComputedStyle(el);
                        if(s.overflowY === 'auto' || s.overflowY === 'scroll'){
                            el.scrollBy(0, 1500);
                            return;
                        }
                        el = el.parentElement;
                    }
                    window.scrollBy(0, 1500);
                    return;
                }
                const scroller = document.scrollingElement || document.documentElement;
                scroller.scrollBy(0, 1500);
            }
        """)
    except Exception:
        pass

def followers_end_marker(page) -> bool:
    """
    Prüft, ob X einen End-of-list-Hinweis anzeigt
    ('You've reached the end' / 'No more results' / etc.) — echtes Listen-Ende.
    """
    try:
        txt = (page.evaluate("() => document.body.innerText") or "")[-3000:]
    except Exception:
        return False
    txt = txt.lower()
    markers = [
        "you’re all caught up",
        "you're all caught up",
        "no more results",
        "no results",
        "you have reached the end",
        "you’ve reached the end",
        "you've reached the end",
    ]
    return any(m in txt for m in markers)

def run_followers_mode(page, user_id: str, account_name: str, log: list) -> int:
    handle = detect_own_handle(page)
    if not handle:
        log.append(f"FEHLER {account_name}: Eigener Handle konnte nicht ermittelt werden — eingeloggt?")
        set_status("error", log[-1], log)
        return 0
    print(f"  Eingeloggt als @{handle}")
    log.append(f"{account_name}: eingeloggt als @{handle}")

    # Try /verified_followers first; if empty, fallback to /followers
    targets_url = [
        f"https://x.com/{handle}/verified_followers",
        f"https://x.com/{handle}/followers"
    ]

    seen = {}      # handle -> {handle, name}
    for url in targets_url:
        try:
            print(f"  Lade {url} …")
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(3)
        except Exception as e:
            log.append(f"FEHLER navigation {url}: {e}")
            continue

        if "login" in page.url.lower():
            log.append("FEHLER: nicht eingeloggt")
            set_status("error", log[-1], log)
            return 0

        empty_scrolls = 0
        MAX_EMPTY = 30
        last_len = -1

        while True:
            cells = scrape_followers_js(page)
            new_count = 0
            for c in cells:
                h = c["handle"].lower()
                if h not in seen:
                    seen[h] = c
                    new_count += 1
            if new_count == 0:
                empty_scrolls += 1
            else:
                empty_scrolls = 0
            n = len(seen)
            if n != last_len:
                set_status("running", f"Followers Scrape — {n} gesammelt (URL: {url.split('/')[-1]})", log)
                last_len = n
                print(f"    +{new_count}  total={n}")
            # Echter End-of-List-Marker?
            if empty_scrolls >= 5 and followers_end_marker(page):
                print(f"  Listenende-Marker erkannt bei {n} Followers.")
                break
            if empty_scrolls >= MAX_EMPTY:
                print(f"  Stoppe nach {MAX_EMPTY} leeren Scrolls bei {n} Followers.")
                break
            scroll_followers(page)
            # Längere Wartezeit weil X's virtualisierte Liste GraphQL-Requests braucht
            time.sleep(1.6)

        if len(seen) > 100:
            break  # genug Daten — kein Fallback nötig

    if not seen:
        log.append(f"{account_name}: keine Followers gefunden")
        set_status("error", log[-1], log)
        return 0

    # Persist into follower_lists.json (overwrite per user_id, with handle merge)
    all_lists = load_json(FOLLOWERS_PATH, {})
    existing = all_lists.get(user_id, [])
    by_handle = {e.get("handle","").lower(): e for e in existing if e.get("handle")}
    for h, entry in seen.items():
        prev = by_handle.get(h, {})
        by_handle[h] = {
            "handle": entry["handle"],
            "name":   entry.get("name") or prev.get("name") or entry["handle"],
            "first_seen": prev.get("first_seen") or datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "last_seen":  datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
    all_lists[user_id] = list(by_handle.values())
    save_json(FOLLOWERS_PATH, all_lists)
    log.append(f"{account_name}: {len(seen)} Followers gespeichert (gesamt im Archiv: {len(all_lists[user_id])})")
    return len(seen)

# ═══════════════════════════════════════════════════════
#  MODE 2: INBOX CHATS SCANNER
# ═══════════════════════════════════════════════════════
def extract_chats_js(page) -> list:
    try:
        return page.evaluate("""
            () => {
                const links = [...document.querySelectorAll('a[href*="/messages/"], a[href*="/i/chat/"]')];
                return links.map(a => {
                    const href = a.getAttribute('href') || '';
                    if (!href || href.split('/').length < 3) return null;
                    let name = '';
                    const ltr = a.querySelector('span[dir="ltr"]');
                    if (ltr) {
                        const t = ltr.textContent.trim();
                        if (t.length > 0) name = t;
                    }
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
    try:
        page.evaluate("""
            () => {
                const link = document.querySelector('a[href*="/messages/"], a[href*="/i/chat/"]');
                if (link) {
                    let el = link.parentElement;
                    while (el && el !== document.body) {
                        const s = window.getComputedStyle(el);
                        if (s.overflowY === 'scroll' || s.overflowY === 'auto') {
                            el.scrollBy(0, 1000); return;
                        }
                        el = el.parentElement;
                    }
                }
                window.scrollBy(0, 1000);
            }
        """)
    except Exception:
        pass

def run_chats_mode(page, user_id: str, account_name: str, log: list) -> int:
    print("  Lade x.com/messages …")
    try:
        page.goto("https://x.com/messages", wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        log.append(f"FEHLER {account_name}: {e}")
        set_status("error", log[-1], log)
        return 0
    if "login" in page.url.lower():
        log.append(f"FEHLER {account_name}: nicht eingeloggt")
        set_status("error", log[-1], log)
        return 0

    try:
        page.wait_for_selector('[data-testid="dm-search-bar"]', timeout=15000)
    except PWTimeout:
        pass
    time.sleep(2)

    seen = {}    # url -> {name, url}
    empty_scrolls = 0
    MAX_EMPTY = 15
    last_len = -1

    while True:
        items = extract_chats_js(page)
        new_count = 0
        for it in items:
            href = it["href"]
            full = f"https://x.com{href}" if href.startswith("/") else href
            if full in seen:
                continue
            seen[full] = {"name": it.get("name") or full.split("/")[-1], "url": full}
            new_count += 1
        if new_count == 0:
            empty_scrolls += 1
        else:
            empty_scrolls = 0
        n = len(seen)
        if n != last_len:
            set_status("running", f"Inbox-Scan — {n} Chats erfasst", log)
            last_len = n
            print(f"    +{new_count}  total={n}")
        if empty_scrolls >= MAX_EMPTY:
            print(f"  Ende der Liste ({n} Chats).")
            break
        scroll_dm_list(page)
        time.sleep(1.2)

    if not seen:
        log.append(f"{account_name}: keine Chats gefunden")
        set_status("error", log[-1], log)
        return 0

    # Merge into contacts.json (preserve last_sent if entry exists by url)
    contacts = load_json(CONTACTS_PATH, {})
    existing = contacts.get(user_id, [])
    by_url = {e.get("url"): e for e in existing if e.get("url")}
    added = 0
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for url, entry in seen.items():
        if url in by_url:
            # update name only; keep last_sent
            by_url[url]["name"] = by_url[url].get("name") or entry["name"]
        else:
            by_url[url] = {"name": entry["name"], "url": url, "last_sent": now_str}
            added += 1
    contacts[user_id] = list(by_url.values())
    save_json(CONTACTS_PATH, contacts)
    log.append(f"{account_name}: {len(seen)} Chats erfasst, davon {added} neu in contacts.json")
    return added

# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════
def main():
    start = time.time()
    print(f"\n{'═'*55}")
    print(f"  builder_bot.py  —  Start")
    print(f"{'═'*55}")

    auftrag = load_json(AUFTRAG_PATH, {})
    if not auftrag or not auftrag.get("mode") or not auftrag.get("user_id"):
        print("⏭  Kein Builder-Auftrag.")
        set_status("skipped", "Kein Builder-Auftrag", [])
        return

    mode    = auftrag["mode"]
    user_id = auftrag["user_id"]
    name    = auftrag.get("name") or user_id
    log = []

    set_status("running", f"{name} — Builder ({mode}) startet …", log)

    try:
        ws_url = ads_open(user_id)
    except Exception as e:
        emsg = str(e).lower()
        if "running out of disk" in emsg or "disk space" in emsg or "out of disk" in emsg:
            log.append(f"⛔ AdsPower: Festplatte voll. Builder abgebrochen.")
            log.append(f"   → Im Dashboard 'AdsPower-Cache leeren' klicken ODER manuell Speicher freigeben.")
            set_status("error", "AdsPower: Festplatte voll — Cache leeren oder Speicher freigeben.", log)
        else:
            log.append(f"KRITISCH: AdsPower-Fehler: {e}")
            set_status("error", f"AdsPower-Fehler: {e}", log)
        return
    time.sleep(4)

    added = 0
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.connect_over_cdp(ws_url)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()

            if mode == "followers":
                added = run_followers_mode(page, user_id, name, log)
            elif mode == "chats":
                added = run_chats_mode(page, user_id, name, log)
            else:
                log.append(f"FEHLER: unbekannter mode '{mode}'")
                set_status("error", log[-1], log)

        except Exception as e:
            log.append(f"KRITISCHER FEHLER: {e}")
            print(f"  ❌ {e}")
        finally:
            try:
                if browser: browser.close()
            except Exception:
                pass

    ads_close(user_id)
    elapsed = int(time.time() - start)
    mins, secs = divmod(elapsed, 60)
    summary = f"Builder fertig — {added} {'Followers' if mode=='followers' else 'Chats'} hinzugefügt in {mins}m {secs}s"
    set_status("done", summary, log)
    print(f"\n  ✅ {summary}\n")


def _dry_run_walkthrough():
    """
    Print what main() would do — config only, no browser / AdsPower / Playwright.
    builder_bot scrapes follower/chat lists live, so per-item walkthrough isn't
    possible from config alone. We log the planned operation.
    """
    import safety_guard
    print(f"\n{'═'*55}")
    print(f"  builder_bot — DRY-RUN walkthrough (no browser, no AdsPower)")
    print(f"{'═'*55}")

    auftrag = load_json(AUFTRAG_PATH, {})
    if not auftrag or not auftrag.get("mode") or not auftrag.get("user_id"):
        print(f"  ⏭  builder_auftrag.json missing/empty — nothing would be scraped.")
        print(f"     Expected at: {AUFTRAG_PATH}")
        return

    mode    = auftrag.get("mode")
    user_id = auftrag.get("user_id")
    name    = auftrag.get("name") or user_id

    print(f"  Mode     : {mode}")
    print(f"  Account  : {name} (user_id={user_id})")
    print(f"  Note     : targets are discovered live by scrolling x.com — not listable here.")
    safety_guard.dry_run_log(f"would scrape {mode} for {name}")
    print(f"  ✓ Walkthrough complete. No scrape was performed.")


if __name__ == "__main__":
    from safety_guard import require_live_or_exit, is_dry_run
    require_live_or_exit("builder_bot")
    if is_dry_run():
        _dry_run_walkthrough()
        raise SystemExit(0)
    main()
