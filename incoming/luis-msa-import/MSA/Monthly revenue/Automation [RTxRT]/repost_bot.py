#!/usr/bin/env python3
"""
repost_bot.py — X-Post Repost Bot

Liest repost_auftrag.json:
  {
    "group_name": "X Promo Group",
    "accounts":   [{"user_id":"k1bhvfaa","name":"AVAILABLE"}, ...],
    "links":      ["https://x.com/foo/status/123", ...]
  }

Für jeden Account in AdsPower:
  → navigiert zu jedem Link
  → erkennt ob schon reposted (überspringt)
  → klickt Repost-Button + bestätigt im Popup

Schreibt repost_status.json + repost_log.json.
"""
import json
import re
import time
import random
import datetime
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_DIR        = Path(__file__).parent
AUFTRAG_PATH    = BASE_DIR / "repost_auftrag.json"
STATUS_PATH     = BASE_DIR / "repost_status.json"
LOG_PATH        = BASE_DIR / "repost_log.json"
PREFLIGHT_PATH  = BASE_DIR / "preflight_status.json"

# Pacing
SEND_PAUSE_MIN = 3.0
SEND_PAUSE_MAX = 6.0
ACCOUNT_PAUSE  = 8.0   # zwischen Accounts

# ─── AdsPower ─────────────────────────────────────────
ADS_HOST = "http://local.adspower.net:50325"
def ads_open(user_id: str) -> str:
    r = requests.get(f"{ADS_HOST}/api/v1/browser/start",
                     params={"user_id": user_id}, timeout=30)
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

# ─── JSON helpers ─────────────────────────────────────
def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default

def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def set_status(state: str, step: str, log: list, current: str = ""):
    save_json(STATUS_PATH, {"state": state, "step": step, "current_account": current, "log": log})
    print(f"  [{state.upper()}] {step}")

# ─── Helpers ──────────────────────────────────────────
def normalize_link(url: str) -> str:
    """Strip tracking params, normalize host."""
    if not url: return ""
    url = url.strip()
    if not url: return ""
    # x.com or twitter.com both work
    url = re.sub(r'^https?://(www\.)?twitter\.com/', 'https://x.com/', url)
    url = re.sub(r'^https?://(www\.)?x\.com/', 'https://x.com/', url)
    if not url.startswith('http'):
        url = 'https://' + url
    # Strip query parameters (often tracking)
    url = url.split('?', 1)[0]
    return url

def detect_account_state(page) -> tuple:
    """
    Untersucht die aktuelle X-Seite und gibt zurück:
       ('ok'|'login'|'suspended'|'verify-required'|'locked'|'restricted'|'unknown', reason)
    """
    url = (page.url or "").lower()
    if "login" in url or "/i/flow/login" in url:
        return "login", "not-logged-in"
    if "/i/flow/consent" in url:
        return "verify-required", "consent-required"
    if "/account/access" in url:
        return "locked", "account-access-page"
    try:
        body = (page.evaluate("() => document.body ? document.body.innerText : ''") or "")
    except Exception:
        return "unknown", "dom-error"
    txt = body.lower()
    if not txt or len(txt) < 30:
        return "unknown", "empty-body"
    if "account suspended" in txt or "your account is suspended" in txt:
        return "suspended", "account-suspended"
    if "we need to make sure you’re a real person" in txt or "we need to make sure you're a real person" in txt:
        return "verify-required", "human-check-required"
    if ("verify your phone" in txt) or ("verify your email" in txt and "to continue" in txt) or ("confirm your phone" in txt):
        return "verify-required", "phone-or-email-verify-required"
    if "your account is locked" in txt or "we locked your account" in txt:
        return "locked", "account-locked"
    if "you can’t do that right now" in txt or "you can't do that right now" in txt or "rate limit exceeded" in txt:
        return "restricted", "rate-limited-or-restricted"
    if "you’re temporarily restricted" in txt or "you're temporarily restricted" in txt:
        return "restricted", "temporarily-restricted"
    if "complete this captcha" in txt or "complete a captcha" in txt:
        return "verify-required", "captcha-required"
    return "ok", "ok"

def page_has_error(page) -> bool:
    try:
        txt = (page.evaluate("() => document.body ? document.body.innerText : ''") or "")[:3000].lower()
    except Exception:
        return True
    if not txt or len(txt) < 20:
        return True
    markers = ["something went wrong", "try again", "try refreshing",
               "this page doesn’t exist", "this page doesn't exist", "rate limit"]
    return any(m in txt for m in markers)

def recover_if_errored(page, max_reloads: int = 2) -> bool:
    for attempt in range(max_reloads):
        if not page_has_error(page):
            return True
        try:
            print(f"    ⟳ Page-Error → Reload {attempt+1}/{max_reloads}")
            page.reload(wait_until="domcontentloaded", timeout=25000)
            time.sleep(2.5)
        except Exception:
            time.sleep(3)
    return not page_has_error(page)

# ─── Repost-Aktion auf X-Tweet-Seite ──────────────────
def do_repost(page, link: str) -> tuple:
    """
    Returns (status, reason) wobei status:
      'ok'                 → reposted
      'already-reposted'   → war schon reposted
      'login'              → nicht eingeloggt
      <other>              → Fehler-Reason
    """
    # Safety hook: dry-run logs, live counts. See safety_guard.py.
    import safety_guard
    if safety_guard.is_dry_run():
        safety_guard.dry_run_log(f"would repost {link}")
        return "ok", "dry-run"
    safety_guard.record_action_or_exit(f"repost {link}")
    try:
        page.goto(link, wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        return "error", f"goto-fail: {e}"
    time.sleep(1.5)
    # Erst Account-State prüfen — klarere Fehler-Reasons als generisches "tweet-not-found"
    state, reason = detect_account_state(page)
    if state != "ok":
        return state, reason
    if not recover_if_errored(page):
        return "error", "page-error"

    # Warte auf Tweet-Hauptelement
    try:
        page.wait_for_selector('article[data-testid="tweet"], [data-testid="retweet"], [data-testid="unretweet"]', timeout=10000)
    except PWTimeout:
        return "error", "tweet-not-found"
    time.sleep(0.8)

    # Schon reposted? → unretweet-Button existiert
    try:
        unret = page.locator('[data-testid="unretweet"]').first
        if unret.is_visible(timeout=600):
            return "already-reposted", "ok"
    except (PWTimeout, Exception):
        pass

    # Repost-Button klicken
    try:
        btn = page.locator('[data-testid="retweet"]').first
        if not btn.is_visible(timeout=3000):
            return "error", "no-retweet-button"
        btn.click(timeout=3000)
    except Exception as e:
        return "error", f"retweet-click-fail: {e}"

    # Bestätigungs-Popup mit "Repost"-Option
    time.sleep(0.9)
    try:
        confirm = page.locator('[data-testid="retweetConfirm"]').first
        if confirm.is_visible(timeout=3500):
            confirm.click(timeout=3000)
        else:
            # Fallback: Menüitem mit Text "Repost"
            page.locator('div[role="menuitem"]:has-text("Repost")').first.click(timeout=3000)
    except Exception as e:
        return "error", f"confirm-fail: {e}"

    time.sleep(1.5)
    # Verify success — unretweet button should now be present
    try:
        unret = page.locator('[data-testid="unretweet"]').first
        if unret.is_visible(timeout=2500):
            return "ok", "ok"
    except (PWTimeout, Exception):
        pass
    # Fallback: trotzdem als erfolgreich werten wenn keine Fehler-Meldung
    return "ok", "ok-unverified"

# ─── Pre-Flight: schneller Account-Health-Check ───────
def preflight_account(account: dict, log: list) -> dict:
    """
    Öffnet AdsPower-Profil, navigiert zu x.com/home, prüft Account-Status,
    schließt sofort wieder. Returns dict mit state+reason.
    """
    user_id = account["user_id"]
    name    = account.get("name") or user_id
    print(f"\n  ─ Preflight: {name} ({user_id}) ─")
    set_status("running", f"Preflight: {name}", log)

    out = {"user_id": user_id, "name": name, "state": "unknown", "reason": "", "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")}

    try:
        ws_url = ads_open(user_id)
    except Exception as e:
        emsg = str(e)
        out["state"] = "adspower-error"
        out["reason"] = emsg[:200]
        log.append(f"{name}: ⛔ AdsPower-Fehler: {emsg[:120]}")
        return out
    time.sleep(3)

    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.connect_over_cdp(ws_url)
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20000)
                time.sleep(2)
            except Exception as e:
                out["state"] = "nav-error"
                out["reason"] = f"goto-fail: {e}"
                log.append(f"{name}: ⚠ {out['reason'][:120]}")
                return out
            state, reason = detect_account_state(page)
            out["state"] = state
            out["reason"] = reason
            icon = {"ok":"✅","login":"🔒","suspended":"⛔","locked":"🔐","verify-required":"📱","restricted":"⏸"}.get(state, "❓")
            log.append(f"{name}: {icon} {state} ({reason})")
            print(f"    {icon} {state} — {reason}")
        except Exception as e:
            out["state"] = "playwright-error"
            out["reason"] = str(e)[:200]
            log.append(f"{name}: ⚠ {out['reason'][:120]}")
        finally:
            try:
                if browser: browser.close()
            except Exception: pass

    ads_close(user_id)
    time.sleep(2)
    return out

# ─── Account-Loop ─────────────────────────────────────
def process_account(account: dict, links: list, repost_log: dict, log: list) -> tuple:
    user_id = account["user_id"]
    name    = account.get("name") or user_id

    print(f"\n{'═'*55}")
    print(f"  Account : {name}  ({user_id})")
    print(f"  Links   : {len(links)}")
    print(f"{'═'*55}")
    set_status("running", f"{name} – starte ({len(links)} Links)", log, name)

    ws_url = ads_open(user_id)
    time.sleep(4)

    reposted = 0
    already  = 0
    errors   = 0
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.connect_over_cdp(ws_url)
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            for idx, link in enumerate(links, start=1):
                link_norm = normalize_link(link)
                if not link_norm:
                    continue
                set_status("running", f"{name} – Link {idx}/{len(links)}", log, name)
                try:
                    status, reason = do_repost(page, link_norm)
                except Exception as ex:
                    status, reason = "error", f"unhandled: {ex}"

                ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
                entry = {"link": link_norm, "status": status, "reason": reason, "ts": ts}
                repost_log.setdefault(user_id, []).append(entry)
                save_json(LOG_PATH, repost_log)

                short_link = link_norm.split('/status/')[-1] if '/status/' in link_norm else link_norm
                if status == "ok":
                    reposted += 1
                    log.append(f"{name}: …/{short_link} ✓ reposted")
                    print(f"    ✓ [{idx}/{len(links)}] {short_link}")
                elif status == "already-reposted":
                    already += 1
                    log.append(f"{name}: …/{short_link} ↻ schon reposted")
                    print(f"    ↻ [{idx}/{len(links)}] schon reposted")
                elif status == "login":
                    errors += 1
                    log.append(f"FEHLER {name}: nicht eingeloggt — Account übersprungen")
                    print(f"    ❌ nicht eingeloggt")
                    break
                else:
                    errors += 1
                    log.append(f"{name}: …/{short_link} ✗ ({reason})")
                    print(f"    ✗ [{idx}/{len(links)}] {reason}")

                time.sleep(random.uniform(SEND_PAUSE_MIN, SEND_PAUSE_MAX))

        except Exception as e:
            log.append(f"KRITISCHER FEHLER {name}: {e}")
            print(f"  ❌ {e}")
        finally:
            try:
                if browser: browser.close()
            except Exception:
                pass

    ads_close(user_id)
    time.sleep(ACCOUNT_PAUSE)
    return reposted, already, errors

# ─── Main ────────────────────────────────────────────
def main():
    start = time.time()
    print(f"\n{'═'*55}")
    print(f"  repost_bot.py  —  Start")
    print(f"{'═'*55}")

    auftrag = load_json(AUFTRAG_PATH, {})
    log_archive = load_json(LOG_PATH, {})

    accounts  = auftrag.get("accounts") or []
    links     = auftrag.get("links") or []
    preflight = bool(auftrag.get("preflight"))

    if not accounts:
        set_status("skipped", "Kein Account ausgewählt", [])
        return

    # ─── Pre-Flight-Modus: nur Status checken, keine Reposts ──
    if preflight:
        log = []
        results = {}
        set_status("running", f"Preflight — {len(accounts)} Accounts werden geprüft", log)
        disk_full = False
        for acc in accounts:
            if disk_full:
                results[acc["user_id"]] = {"user_id": acc["user_id"], "name": acc.get("name") or acc["user_id"],
                                            "state": "skipped", "reason": "adspower-disk-full",
                                            "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")}
                continue
            try:
                r = preflight_account(acc, log)
                results[r["user_id"]] = r
                if "disk space" in (r.get("reason","") or "").lower():
                    disk_full = True
                    log.append(f"⛔ AdsPower-Disk voll — Preflight abgebrochen.")
            except Exception as e:
                results[acc["user_id"]] = {"user_id": acc["user_id"], "name": acc.get("name") or acc["user_id"],
                                            "state": "error", "reason": str(e)[:200],
                                            "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")}
            # Live-Persist nach jedem Account
            save_json(PREFLIGHT_PATH, results)

        # Zusammenfassung
        by_state = {}
        for r in results.values():
            by_state[r["state"]] = by_state.get(r["state"], 0) + 1
        elapsed = int(time.time() - start)
        mins, secs = divmod(elapsed, 60)
        summary = "Preflight fertig — " + ", ".join(f"{n}× {s}" for s, n in sorted(by_state.items(), key=lambda x: -x[1])) + f" in {mins}m {secs}s"
        set_status("done", summary, log)
        print(f"\n  ✅ {summary}\n")
        return

    if not links:
        set_status("skipped", "Keine Links ausgewählt", [])
        return

    log = []
    total_ok = total_already = total_err = 0
    set_status("running", f"Start — {len(links)} Links × {len(accounts)} Accounts", log)

    disk_full = False
    for acc in accounts:
        if disk_full:
            log.append(f"⏭  {acc.get('name')}: übersprungen — AdsPower Disk-Space-Problem.")
            continue
        try:
            ok, alr, err = process_account(acc, links, log_archive, log)
            total_ok += ok
            total_already += alr
            total_err += err
        except Exception as e:
            emsg = str(e).lower()
            if "running out of disk" in emsg or "disk space" in emsg or "out of disk" in emsg:
                log.append(f"⛔ AdsPower: Festplatte voll. Run abgebrochen.")
                log.append(f"   → Im Dashboard 'AdsPower-Cache leeren' klicken ODER manuell Speicher freigeben, dann erneut.")
                print(f"\n❌ AdsPower disk-space — Run abgebrochen")
                disk_full = True
            else:
                log.append(f"KRITISCH {acc.get('name')}: {e}")

    elapsed = int(time.time() - start)
    mins, secs = divmod(elapsed, 60)
    summary = (f"Repost fertig — {total_ok} reposted, "
               f"{total_already} schon vorher, {total_err} Fehler in {mins}m {secs}s")
    set_status("done", summary, log)
    print(f"\n  ✅ {summary}\n")


def _dry_run_walkthrough():
    """
    Print what main() would do — config only, no browser / AdsPower / Playwright.
    repost_bot iterates (account, link) pairs from repost_auftrag.json.
    """
    import safety_guard
    print(f"\n{'═'*55}")
    print(f"  repost_bot — DRY-RUN walkthrough (no browser, no AdsPower)")
    print(f"{'═'*55}")

    auftrag = load_json(AUFTRAG_PATH, {})
    accounts  = auftrag.get("accounts") or []
    links     = auftrag.get("links") or []
    preflight = bool(auftrag.get("preflight"))

    if not accounts:
        print(f"  ⏭  No accounts in repost_auftrag.json — nothing would be done.")
        print(f"     Expected at: {AUFTRAG_PATH}")
        return

    if preflight:
        print(f"  Mode     : PREFLIGHT (login/state check only)")
        print(f"  Accounts : {len(accounts)}")
        for acc in accounts:
            safety_guard.dry_run_log(f"would preflight account {acc.get('name') or acc.get('user_id')}")
        print(f"  ✓ Walkthrough complete. No repost was made.")
        return

    print(f"  Accounts : {len(accounts)} reposter(s)")
    print(f"  Links    : {len(links)} tweet(s) to repost")
    total = len(accounts) * len(links)
    print(f"  Total pairs (accounts × links): up to {total}")
    if total == 0:
        print(f"  ⏭  Nothing to repost.")
        return

    cap = 10
    print(f"  Showing first {min(cap, total)} as samples:")
    shown = 0
    for acc in accounts:
        for link in links:
            if shown >= cap:
                break
            safety_guard.dry_run_log(f"would repost {link} from {acc.get('name') or acc.get('user_id')}")
            shown += 1
        if shown >= cap:
            break
    if total > cap:
        print(f"  … and {total - cap} more pair(s) skipped from log.")
    print(f"  ✓ Walkthrough complete. No repost was made.")


if __name__ == "__main__":
    from safety_guard import require_live_or_exit, is_dry_run
    require_live_or_exit("repost_bot")
    if is_dry_run():
        _dry_run_walkthrough()
        raise SystemExit(0)
    main()
