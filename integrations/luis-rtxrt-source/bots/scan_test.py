#!/usr/bin/env python3
"""
scan_test.py — Nur Pass 1: Chatliste scannen ohne DMs zu senden.
Zeigt wie viele Chats gefunden werden.

Starten: python scan_test.py
"""
import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import requests

BASE_DIR      = Path(__file__).parent
AUFTRAG_PATH  = BASE_DIR / "auftrag.json"
CONTACTS_PATH = BASE_DIR / "contacts.json"
ADS_HOST      = "http://local.adspower.net:50325"

def ads_open(user_id):
    r = requests.get(f"{ADS_HOST}/api/v1/browser/start", params={"user_id": user_id}, timeout=30)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"AdsPower Fehler: {data}")
    return data["data"]["ws"]["puppeteer"]

def ads_close(user_id):
    try: requests.get(f"{ADS_HOST}/api/v1/browser/stop", params={"user_id": user_id}, timeout=10)
    except: pass

def is_filtered(contacts, user_id, url):
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    for c in contacts.get(user_id, []):
        if c.get("url") == url:
            try:
                last = datetime.datetime.fromisoformat(c["last_sent"].replace("Z", "+00:00"))
                if (now - last).total_seconds() < 86400:
                    return True
            except: pass
    return False

def debug_page(page):
    """Zeigt welche data-testid Attribute auf der Seite vorhanden sind."""
    try:
        ids = page.evaluate("""
            () => {
                const els = document.querySelectorAll('[data-testid]');
                const counts = {};
                els.forEach(e => {
                    const id = e.getAttribute('data-testid');
                    counts[id] = (counts[id] || 0) + 1;
                });
                return counts;
            }
        """)
        print("\n  [DEBUG] data-testid Attribute auf der Seite:")
        for k, v in sorted(ids.items(), key=lambda x: -x[1])[:30]:
            print(f"    {v:>4}x  {k}")
    except Exception as e:
        print(f"  [DEBUG] Fehler: {e}")

    # Direkte Link-Suche
    try:
        links = page.evaluate("""
            () => [...document.querySelectorAll('a[href*="/messages/"], a[href*="/i/chat/"]')]
                    .map(a => a.href).slice(0, 5)
        """)
        print(f"\n  [DEBUG] Direkte /messages/ Links gefunden: {len(links)}")
        for l in links:
            print(f"    {l}")
    except Exception as e:
        print(f"  [DEBUG] Link-Suche Fehler: {e}")

def extract_chats_js(page):
    """Extrahiert href + Name direkt per JS in einem Aufruf."""
    return page.evaluate("""
        () => {
            const links = [...document.querySelectorAll('a[href*="/messages/"], a[href*="/i/chat/"]')];
            return links.map(a => {
                const href = a.getAttribute('href') || '';
                if (!href || href.split('/').length < 3) return null;

                // Priorität 1: span[dir="ltr"] — enthält meist den Anzeigenamen
                let name = '';
                const ltr = a.querySelector('span[dir="ltr"]');
                if (ltr) { const t = ltr.textContent.trim(); if (t.length > 0) name = t; }
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

def scroll_list(page):
    """Scrollt den DM-Listen-Container nach unten."""
    page.evaluate("""
        () => {
            // Scrollbaren Vorfahren des ersten Chat-Links finden
            const link = document.querySelector('a[href*="/messages/"], a[href*="/i/chat/"]');
            if (link) {
                let el = link.parentElement;
                while (el && el !== document.body) {
                    const s = window.getComputedStyle(el);
                    if (s.overflowY === 'scroll' || s.overflowY === 'auto') {
                        el.scrollBy(0, 800);
                        return;
                    }
                    el = el.parentElement;
                }
            }
            // Fallback: bekannte Selektoren
            const fb = document.querySelector('[data-testid="DMDrawer"]')
                    || document.querySelector('[data-testid="dm-inbox"]')
                    || document.querySelector('section[role="region"]')
                    || document.querySelector('[aria-label*="Messages"]');
            if (fb) fb.scrollBy(0, 800);
            else window.scrollBy(0, 800);
        }
    """)

def scan_only(page, user_id, contacts):
    seen_urls = set()
    all_urls  = []
    filtered  = []
    empty     = 0
    MAX_EMPTY = 15

    print("\n  Scanne Chatliste …\n")

    # Erst prüfen ob überhaupt etwas geladen ist
    time.sleep(2)
    debug_page(page)
    print()

    while True:
        items = extract_chats_js(page)
        found_new = False

        for item in items:
            try:
                href = item["href"]
                url  = f"https://x.com{href}" if href.startswith("/") else href
                if url in seen_urls: continue
                seen_urls.add(url)
                found_new = True
                all_urls.append(url)
                blocked = is_filtered(contacts, user_id, url)
                if blocked: filtered.append(url)
                name   = item.get("name") or href.split("/")[-1]
                status = "🔒 gefiltert" if blocked else "✅ frei"
                print(f"  {len(all_urls):>4}.  {status}  {name}")
            except: continue

        if not found_new:
            empty += 1
            if empty >= MAX_EMPTY:
                break
        else:
            empty = 0

        try:
            scroll_list(page)
        except: pass
        time.sleep(1.2)

    print(f"\n{'═'*50}")
    print(f"  Gesamt gefunden : {len(all_urls)}")
    print(f"  Davon gefiltert : {len(filtered)}")
    print(f"  Davon frei      : {len(all_urls) - len(filtered)}")
    print(f"{'═'*50}\n")

def main():
    # ── Run-mode flag (added: real --dry-run; scan_test is read-only by design) ──
    import argparse as _ap
    _p = _ap.ArgumentParser(add_help=False)
    _p.add_argument("--dry-run", action="store_true")
    _p.add_argument("--live-one", action="store_true")
    _p.add_argument("--max-actions", type=int, default=None)
    _args, _ = _p.parse_known_args()
    dry_run = bool(_args.dry_run)

    auftrag  = json.loads(AUFTRAG_PATH.read_text(encoding="utf-8")) if AUFTRAG_PATH.exists() else {}
    contacts = json.loads(CONTACTS_PATH.read_text(encoding="utf-8")) if CONTACTS_PATH.exists() else {}
    accounts = auftrag.get("accounts", [])
    if not accounts:
        print("Kein Auftrag gefunden. Bitte erst im Dashboard einen Auftrag erstellen.")
        return

    # ── DRY RUN: validate + plan + exit. No AdsPower, no browser, no scrape. ──
    if dry_run:
        n_accounts = len(accounts)
        n_known_contacts = sum(len(v) for v in (contacts or {}).values()) if isinstance(contacts, dict) else 0
        print(f"DRY RUN -- scan_test.py would:")
        print(f"  - auftrag accounts: {n_accounts}")
        print(f"  - known contacts in contacts.json: {n_known_contacts}")
        print(f"  - per account: ads_open -> x.com/i/chat -> scroll & read (no send)")
        print(f"  - read-only by design; no JSON mutation even in real run")
        print(f"DRY RUN OK -- no AdsPower call, no browser, no scrape.")
        return

    for acc in accounts:
        user_id = acc["user_id"]
        name    = acc["name"]
        print(f"\n  Account: {name} ({user_id})")
        ws_url = ads_open(user_id)
        time.sleep(4)
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(ws_url)
            ctx  = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://x.com/i/chat", wait_until="domcontentloaded", timeout=30000)
            time.sleep(6)  # Warten bis Chatliste vollständig geladen
            if "login" in page.url.lower():
                print("  ✗ Nicht eingeloggt!")
            else:
                scan_only(page, user_id, contacts)
            browser.close()
        ads_close(user_id)

if __name__ == "__main__":
    main()
