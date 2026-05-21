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
import os
import re
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

# Shared preflight (parallel state checks + action hints)
try:
    from _preflight import preflight_and_filter
except ImportError:
    preflight_and_filter = None

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
    # ── Run-mode flags (added: real --dry-run + defense-in-depth live cap) ──
    import argparse as _ap
    _p = _ap.ArgumentParser(add_help=False)
    _p.add_argument("--dry-run", action="store_true")
    _p.add_argument("--live-one", action="store_true")
    _p.add_argument("--max-actions", type=int, default=None)
    _args, _ = _p.parse_known_args()
    dry_run = bool(_args.dry_run)
    live_one_flag = bool(_args.live_one)

    start = time.time()
    print(f"\n{'═'*55}")
    print(f"  builder_bot.py  —  Start{' (DRY RUN)' if dry_run else ''}")
    print(f"{'═'*55}")

    auftrag = load_json(AUFTRAG_PATH, {})

    # ── DRY RUN: validate + plan + exit. No AdsPower, no browser, no scrape. ──
    if dry_run:
        mode_planned    = (auftrag or {}).get("mode", "<unset>")
        user_id_planned = (auftrag or {}).get("user_id", "<unset>")
        name_planned    = (auftrag or {}).get("name", "<unset>")
        print(f"DRY RUN — builder_bot.py would:")
        print(f"  - mode: {mode_planned}")
        print(f"  - account user_id present: {bool(user_id_planned and user_id_planned != '<unset>')}")
        print(f"  - account name: {name_planned}")
        if mode_planned == "followers":
            print(f"  - would scrape: x.com/<handle>/verified_followers")
            print(f"  - would write:  follower_lists.json[{user_id_planned}]")
        elif mode_planned == "chats":
            print(f"  - would scrape: x.com/messages chat list")
            print(f"  - would write:  contacts.json[{user_id_planned}]")
        else:
            print(f"  - mode '{mode_planned}' not recognized — real run would error here")
        print(f"  - would call: ads_open -> playwright -> scroll -> save_json")
        print(f"DRY RUN OK -- no AdsPower call, no browser, no list mutation.")
        set_status("done", f"DRY RUN OK -- builder({mode_planned}) plan only", [])
        return

    if not auftrag or not auftrag.get("mode") or not auftrag.get("user_id"):
        print("⏭  Kein Builder-Auftrag.")
        set_status("skipped", "Kein Builder-Auftrag", [])
        return

    mode    = auftrag["mode"]
    user_id = auftrag["user_id"]
    name    = auftrag.get("name") or user_id
    log = []

    # AVAILABLE-Guard: Platzhalter haben keinen X-Login → sofort skip
    if (name or "").strip().upper() == "AVAILABLE":
        log.append(f"⏭  Account '{name}' ist ein AVAILABLE-Platzhalter — kein X-Login, nichts zu builden.")
        set_status("skipped", "AVAILABLE-Platzhalter — übersprungen", log)
        return

    # ───────────────────────────────────────────────────────────────
    #  LIVE-MODE HARD CAP (defense in depth, gespiegelt von repost_bot.py)
    # ───────────────────────────────────────────────────────────────
    # Builder läuft immer mit genau 1 Account (per Design), aber die Mass-
    # Flag-Validierung und die Required-Flag-Validierung gelten trotzdem.
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
                "   Builder-Run wurde sicherheitshalber abgebrochen.",
            ]
            for ln in log_msg: print(ln)
            set_status("error", "live-mode flag-mismatch — abort", log_msg)
            return
        forbidden = ["ALLOW_MASS_LIVE","ALLOW_BULK_DM","ALLOW_BULK_REPOST",
                     "ALLOW_FULL_BLAST","DISABLE_RATE_LIMITS","DISABLE_DAILY_CAP"]
        bad = [f for f in forbidden if (os.environ.get(f,"").strip().lower() in ("1","true","yes","on"))]
        if bad:
            log_msg = [f"⛔ LIVE-MODE-ABORT: mass-live flag(s) set: {bad}"]
            for ln in log_msg: print(ln)
            set_status("error", f"mass-live flags set: {bad}", log_msg)
            return
        log.append("━━ LIVE MODE ACTIVE — Builder runs on a single account by design ━━")

    # ─── Preflight (Account-Health-Check) ───────────────
    if preflight_and_filter is not None and not auftrag.get("skip_preflight"):
        accounts = [{"user_id": user_id, "name": name}]
        healthy, failed = preflight_and_filter(
            accounts, mode="basic", log=log,
            set_status_fn=lambda step: set_status("running", step, log),
            max_workers=1,
        )
        if not healthy:
            f = failed[0] if failed else {"state": "unknown", "reason": "no-result"}
            set_status("error",
                       f"Preflight FEHLGESCHLAGEN: {f.get('state')} ({f.get('reason')}) — siehe Log",
                       log)
            return

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


if __name__ == "__main__":
    main()
