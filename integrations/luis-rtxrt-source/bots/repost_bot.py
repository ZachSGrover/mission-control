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
import os
import re
import sys
import time
import random
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
    """Öffnet ein AdsPower-Profil. Wirft RuntimeError mit klarer Disk-Full-Erkennung."""
    try:
        r = requests.get(f"{ADS_HOST}/api/v1/browser/start",
                         params={"user_id": user_id}, timeout=45)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"AdsPower nicht erreichbar: {e}") from e
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"AdsPower antwortet ungültig: {e}") from e
    if data.get("code") != 0:
        msg = (data.get("msg") or "") + " " + str(data)
        msg_low = msg.lower()
        # Klartext-Mapping häufiger Fehler
        if "disk space" in msg_low or "running out of disk" in msg_low or "out of disk" in msg_low:
            raise RuntimeError("AdsPower: running out of disk space")
        if "concurrent" in msg_low or "too many" in msg_low:
            raise RuntimeError("AdsPower: concurrent-browser-limit reached")
        raise RuntimeError(f"AdsPower Fehler: {data.get('msg') or data}")
    try:
        ws = data["data"]["ws"]["puppeteer"]
    except (KeyError, TypeError) as e:
        raise RuntimeError(f"AdsPower-Response ohne ws-URL: {data}") from e
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
    """Atomarer Schreibe + Retry bei OneDrive-Locks (Errno 22 / Permission denied).
    Schreibt erst in eine .tmp-Datei und rennt anschließend einen atomic-replace —
    so kann OneDrive die Originaldatei nicht mid-write sperren.
    """
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    last_err = None
    for attempt in range(6):
        try:
            tmp.write_text(payload, encoding="utf-8")
            try:
                tmp.replace(path)  # atomic rename
            except OSError:
                # Fallback: direkter overwrite + tmp cleanup
                path.write_text(payload, encoding="utf-8")
                try: tmp.unlink()
                except Exception: pass
            return
        except OSError as e:
            last_err = e
            time.sleep(0.6 * (attempt + 1))   # 0.6s, 1.2s, 1.8s, 2.4s, 3.0s, 3.6s
    # Letzter Versuch: direkter write ohne tmp
    try:
        path.write_text(payload, encoding="utf-8")
        return
    except OSError:
        # Wir loggen den Fehler in stderr aber crashen NICHT —
        # ein verlorener Log-Eintrag ist besser als ein abgebrochener Run.
        import sys as _sys
        print(f"  ⚠ save_json fehlgeschlagen für {path.name}: {last_err}",
              file=_sys.stderr)

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

def wait_for_x_ready(page, timeout: float = 12.0) -> str:
    """
    Aktives Warten bis die X-SPA gerendert ist. Returns:
      'home'    → eingeloggt (Sidebar/PrimaryColumn sichtbar)
      'login'   → Login-Form sichtbar
      'error'   → 'Something went wrong' o.ä.
      'timeout' → Nichts erkennbar nach <timeout> Sekunden
    """
    deadline = time.time() + timeout
    LOGGED_IN_SELECTORS = (
        '[data-testid="primaryColumn"], '
        '[data-testid="SideNav_AccountSwitcher_Button"], '
        '[data-testid="AppTabBar_Home_Link"], '
        '[data-testid="SideNav_NewTweet_Button"], '
        'a[href="/home"][role="link"]'
    )
    LOGIN_SELECTORS = (
        'input[name="text"], '
        'input[name="session[username_or_email]"], '
        'a[href="/i/flow/login"], '
        'a[data-testid="loginButton"], '
        'a[data-testid="login"]'
    )
    while time.time() < deadline:
        try:
            # Login-Form sichtbar?
            try:
                if page.locator(LOGIN_SELECTORS).first.is_visible(timeout=300):
                    return "login"
            except Exception:
                pass
            # Eingeloggter Home-Feed sichtbar?
            try:
                if page.locator(LOGGED_IN_SELECTORS).first.is_visible(timeout=300):
                    return "home"
            except Exception:
                pass
            # Error-State?
            try:
                body_txt = (page.evaluate("() => document.body ? document.body.innerText : ''") or "").lower()
            except Exception:
                body_txt = ""
            if body_txt and ("something went wrong" in body_txt or "try refreshing" in body_txt):
                return "error"
            # Fallback: substantieller Body-Inhalt = wahrscheinlich gerendert
            if len(body_txt) > 250:
                return "home"
        except Exception:
            pass
        time.sleep(0.4)
    return "timeout"

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

    # NEU: aktives Warten bis SPA gerendert ist (fixt "empty-body" False-Positives
    # nach mehreren Browser-Starts wenn AdsPower langsamer wird)
    ready = wait_for_x_ready(page, timeout=10.0)
    if ready == "login":
        return "login", "not-logged-in"
    if ready == "error":
        return "unknown", "page-error"

    try:
        body = (page.evaluate("() => document.body ? document.body.innerText : ''") or "")
    except Exception:
        return "unknown", "dom-error"
    txt = body.lower()
    if not txt or len(txt) < 30:
        # 2. Versuch: nochmal kurz warten und neu prüfen
        time.sleep(2.5)
        try:
            body = (page.evaluate("() => document.body ? document.body.innerText : ''") or "")
            txt = body.lower()
        except Exception:
            return "unknown", "dom-error"
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
      'renewed'            → war schon reposted, un-reposted + neu reposted
      'login'              → nicht eingeloggt
      <other>              → Fehler-Reason
    """
    # 3-stufige Click-Strategie (oben definiert weil sowohl für undo als auch repost verwendet)
    def robust_click(locator, label: str) -> tuple:
        """Returns (ok: bool, method: str, error: str)"""
        # 1) Normaler click mit großzügigem Timeout
        try:
            locator.click(timeout=7000)
            return True, "normal", ""
        except Exception as e1:
            err1 = str(e1)[:120]
        # 2) Force-Click (bypass actionability)
        try:
            locator.click(timeout=4000, force=True)
            return True, "force", ""
        except Exception as e2:
            err2 = str(e2)[:120]
        # 3) JavaScript-Click (final fallback)
        try:
            locator.evaluate("el => el.click()")
            return True, "js", ""
        except Exception as e3:
            err3 = str(e3)[:120]
        return False, "all-failed", f"{label}: normal={err1} | force={err2} | js={err3}"

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

    # Warte auf Tweet-Hauptelement — mit Sensitive-Gate-Recovery und genauer Diagnose
    def diagnose_tweet_missing() -> str:
        """Untersucht die Page wenn Tweet-Selektoren nicht gefunden wurden.
           Returns ein konkreter Reason-String. Bei unbekannten Fällen wird
           ein Snippet des Body-Texts angehängt, damit man die echte X-Meldung sieht."""
        try:
            body = (page.evaluate("() => document.body ? document.body.innerText : ''") or "")
        except Exception:
            return "tweet-load-timeout"
        low = body.lower()
        if not low or len(low) < 30:
            return "tweet-load-timeout"

        # 1) Sensitive-Content-Gate — höchste Priorität, weil wir das auto-clicken können
        if ("contains sensitive content" in low or "sensitive content" in low
            or "this content might contain" in low or "may contain sensitive" in low
            or ("the following media includes" in low and ("sensitive" in low or "potentially" in low))):
            return "tweet-sensitive-gate"

        # 2) Vom Author geblockt
        if ("you’re blocked" in low or "you're blocked" in low
            or "has blocked you" in low or "blocked you from following" in low):
            return "tweet-blocked-by-author"

        # 3) Geschützter Account
        if ("these posts are protected" in low or "these tweets are protected" in low
            or "this account's tweets are protected" in low or "this account’s posts are protected" in low
            or "protected account" in low):
            return "tweet-protected"

        # 4) Rate-Limit auf der Tweet-Seite
        if "rate limit exceeded" in low or "try again later" in low:
            return "tweet-rate-limited"

        # 5) Tweet wirklich gelöscht — wir verlangen STARKE Signale, nicht nur "doesn't exist"
        strong_deleted = (
            ("hmm…this page doesn" in low and ("try searching" in low or "back to home" in low))
            or "this post was deleted" in low
            or "this post is from an account" in low and "no longer exist" in low
            or "this tweet was deleted" in low
            or "post unavailable" in low
        )
        if strong_deleted:
            return "tweet-deleted"

        # 6) Schwaches "doesn't exist"-Signal ohne weitere Bestätigung →
        #    könnte False Positive sein (z.B. teil eines Link-Beschreibungstexts).
        #    Snippet zur Diagnose anhängen.
        if "doesn't exist" in low or "doesn’t exist" in low or "deleted" in low:
            snippet = body.strip().split("\n")[0][:120].replace('"', "'")
            return f"tweet-unclear-state: {snippet}"

        # 7) Generischer X-Error trotz recover_if_errored
        if "something went wrong" in low or "try refreshing" in low:
            return "tweet-page-error"

        # 8) Nichts erkennbar — gib einen Snippet aus dem Body zurück
        first_line = body.strip().split("\n")[0][:120].replace('"', "'")
        if first_line and first_line.lower() != "x":
            return f"tweet-load-timeout: {first_line}"
        return "tweet-load-timeout"

    def try_click_sensitive_view() -> bool:
        """Versucht den 'View'/'Show'-Button auf einem Sensitive-Gate zu klicken.
           Returns True wenn erfolgreich geklickt."""
        candidates = [
            '[role="button"]:has-text("View")',
            'button:has-text("View")',
            '[role="button"]:has-text("Show")',
            'button:has-text("Show")',
            '[data-testid="sensitiveMediaWarning"] button',
            'span:has-text("View") >> xpath=ancestor::*[@role="button"][1]',
        ]
        for sel in candidates:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=800):
                    try:
                        btn.click(timeout=3000)
                    except Exception:
                        try:
                            btn.click(timeout=2500, force=True)
                        except Exception:
                            try:
                                btn.evaluate("el => el.click()")
                            except Exception:
                                continue
                    return True
            except Exception:
                continue
        return False

    try:
        page.wait_for_selector('article[data-testid="tweet"], [data-testid="retweet"], [data-testid="unretweet"]', timeout=10000)
    except PWTimeout:
        reason = diagnose_tweet_missing()
        # Bei Sensitive-Gate: klicken + erneut versuchen
        if reason == "tweet-sensitive-gate":
            print(f"    ⚠ Sensitive-Gate — klicke 'View' und versuche erneut")
            if try_click_sensitive_view():
                time.sleep(1.2)
                try:
                    page.wait_for_selector('article[data-testid="tweet"], [data-testid="retweet"], [data-testid="unretweet"]', timeout=8000)
                except PWTimeout:
                    return "error", "tweet-sensitive-gate-stuck"
            else:
                return "error", "tweet-sensitive-gate-no-button"
        else:
            return "error", reason
    time.sleep(0.8)

    # Schon reposted? → Renewal-Flow: un-reposten + neu reposten
    was_already_reposted = False
    try:
        unret = page.locator('[data-testid="unretweet"]').first
        if unret.is_visible(timeout=800):
            was_already_reposted = True
            print(f"    ↻ schon reposted → renewal (undo + repost)")
            try:
                unret.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            time.sleep(0.3)
            ok, method, err = robust_click(unret, "unretweet-btn")
            if not ok:
                return "error", f"undo-click-fail: {err}"
            # Confirm-Popup für Undo (X nennt es 'unretweetConfirm' oder Menüitem 'Undo')
            time.sleep(1.0)
            try:
                undo_confirm = page.locator('[data-testid="unretweetConfirm"]').first
                undo_confirm_visible = False
                try:
                    undo_confirm_visible = undo_confirm.is_visible(timeout=4000)
                except Exception:
                    undo_confirm_visible = False
                if undo_confirm_visible:
                    ok, method, err = robust_click(undo_confirm, "unretweetConfirm")
                    if not ok:
                        return "error", f"undo-confirm-fail: {err}"
                else:
                    # Fallback: Menüitem mit Text "Undo repost" / "Undo Repost"
                    mi_undo = page.locator(
                        'div[role="menuitem"]:has-text("Undo repost"), '
                        'div[role="menuitem"]:has-text("Undo Repost"), '
                        'div[role="menuitem"]:has-text("Undo")'
                    ).first
                    try:
                        mi_undo.scroll_into_view_if_needed(timeout=1500)
                    except Exception:
                        pass
                    ok, method, err = robust_click(mi_undo, "menuitem-Undo")
                    if not ok:
                        return "error", f"undo-confirm-fail: {err}"
            except Exception as e:
                return "error", f"undo-confirm-fail: {str(e)[:200]}"
            time.sleep(1.8)
            # Warte bis retweet-button wieder sichtbar ist (un-repost erfolgreich)
            try:
                page.wait_for_selector('[data-testid="retweet"]', timeout=6000)
            except PWTimeout:
                return "error", "retweet-btn-not-back-after-undo"
            time.sleep(0.5)
    except (PWTimeout, Exception):
        pass

    try:
        btn = page.locator('[data-testid="retweet"]').first
        if not btn.is_visible(timeout=4000):
            return "error", "no-retweet-button"
        # Scroll button into view first (fixt 'scrolling into view if needed' Hangs)
        try:
            btn.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        time.sleep(0.3)
        ok, method, err = robust_click(btn, "retweet-btn")
        if not ok:
            return "error", f"retweet-click-fail: {err}"
    except Exception as e:
        return "error", f"retweet-click-fail: {str(e)[:200]}"

    # Bestätigungs-Popup mit "Repost"-Option
    time.sleep(1.0)
    try:
        confirm = page.locator('[data-testid="retweetConfirm"]').first
        confirm_visible = False
        try:
            confirm_visible = confirm.is_visible(timeout=4000)
        except Exception:
            confirm_visible = False
        if confirm_visible:
            ok, method, err = robust_click(confirm, "retweetConfirm")
            if not ok:
                return "error", f"confirm-fail: {err}"
        else:
            # Fallback: Menüitem mit Text "Repost"
            mi = page.locator('div[role="menuitem"]:has-text("Repost")').first
            try:
                mi.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            ok, method, err = robust_click(mi, "menuitem-Repost")
            if not ok:
                return "error", f"confirm-fail: {err}"
    except Exception as e:
        return "error", f"confirm-fail: {str(e)[:200]}"

    time.sleep(1.5)
    # Final-Status hängt davon ab, ob renewal-Flow oder fresh repost
    final_status = "renewed" if was_already_reposted else "ok"
    # Verify success — unretweet button should now be present
    try:
        unret = page.locator('[data-testid="unretweet"]').first
        if unret.is_visible(timeout=2500):
            return final_status, "ok"
    except (PWTimeout, Exception):
        pass
    # Fallback: trotzdem als erfolgreich werten wenn keine Fehler-Meldung
    return final_status, "ok-unverified"

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
                page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=25000)
                # NEU: aktives Warten bis X gerendert ist (statt nur 2 Sek)
                ready = wait_for_x_ready(page, timeout=12.0)
                if ready == "timeout":
                    # Letzte Chance: reload + nochmal warten
                    print(f"    ⟳ X nicht gerendert — Reload …")
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=20000)
                    except Exception:
                        pass
                    wait_for_x_ready(page, timeout=8.0)
            except Exception as e:
                out["state"] = "nav-error"
                out["reason"] = f"goto-fail: {e}"
                log.append(f"{name}: ⚠ {out['reason'][:120]}")
                # Browser sauber schließen vorm Return
                try:
                    if browser: browser.close()
                except Exception: pass
                ads_close(user_id)
                time.sleep(2)
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
    renewed  = 0
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
                elif status == "renewed":
                    renewed += 1
                    log.append(f"{name}: …/{short_link} ⟳ renewed (un-reposted + neu reposted)")
                    print(f"    ⟳ [{idx}/{len(links)}] renewed")
                elif status == "already-reposted":
                    # Sollte nach Umbau nicht mehr vorkommen, aber falls doch: nicht crashen
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
    return reposted, renewed, already, errors

# ─── Main ────────────────────────────────────────────
def main():
    # ── Run-mode flags (added: real --dry-run; live-one cap below already exists) ──
    # Parsed permissively so unknown flags from the runner don't break the bot.
    import argparse as _ap
    _p = _ap.ArgumentParser(add_help=False)
    _p.add_argument("--dry-run", action="store_true")
    _p.add_argument("--live-one", action="store_true")
    _p.add_argument("--max-actions", type=int, default=None)
    _args, _ = _p.parse_known_args()
    dry_run = bool(_args.dry_run)

    start = time.time()
    print(f"\n{'═'*55}")
    print(f"  repost_bot.py  —  Start{' (DRY RUN)' if dry_run else ''}")
    print(f"{'═'*55}")

    auftrag = load_json(AUFTRAG_PATH, {})
    log_archive = load_json(LOG_PATH, {})

    accounts_raw = auftrag.get("accounts") or []
    links     = auftrag.get("links") or []
    preflight = bool(auftrag.get("preflight"))

    # ── DRY RUN: validate + plan + exit. No AdsPower, no browser, no repost. ──
    if dry_run:
        n_accounts = len(accounts_raw)
        n_links    = len(links)
        planned    = n_accounts * n_links
        print(f"DRY RUN — repost_bot.py would:")
        print(f"  - auftrag accounts: {n_accounts}")
        print(f"  - tweet links:      {n_links}")
        print(f"  - planned reposts:  up to {planned}  (accounts x links)")
        print(f"  - preflight-only mode in auftrag: {preflight}")
        print(f"  - would call: ads_open -> playwright -> retweet")
        print(f"DRY RUN OK -- no AdsPower call, no browser, no repost.")
        set_status("done", f"DRY RUN OK -- up to {planned} reposts planned", [])
        return

    # AVAILABLE-Platzhalter (ungenutzte AdsPower-Profile) immer rausfiltern
    accounts = []
    available_skipped = []
    for a in accounts_raw:
        if (a.get("name") or "").strip().upper() == "AVAILABLE":
            available_skipped.append(a.get("user_id") or "?")
        else:
            accounts.append(a)
    if available_skipped:
        print(f"  ⏭  AVAILABLE-Platzhalter übersprungen: {len(available_skipped)} ({', '.join(available_skipped)})")

    if not accounts:
        set_status("skipped", "Kein Account ausgewählt", [])
        return

    # ───────────────────────────────────────────────────────────────
    #  LIVE-MODE HARD CAP (defense in depth, gespiegelt von safety_guard.py)
    # ───────────────────────────────────────────────────────────────
    # Wenn ALLOW_LIVE_EXTERNAL_ACTIONS=true gesetzt ist, MUSS auch
    # MAX_TEST_ACTIONS exakt 1 sein. Sonst bricht der Bot mit error ab.
    # Zusätzlich werden accounts + links HART auf 1 gecapped — selbst wenn
    # versehentlich mehrere im auftrag stehen, kann maximal 1 Aktion passieren.
    live_mode = (os.environ.get("ALLOW_LIVE_EXTERNAL_ACTIONS", "").strip() == "true")
    if live_mode:
        confirm = (os.environ.get("CONFIRM_LIVE_TEST", "").strip())
        mta_raw = (os.environ.get("MAX_TEST_ACTIONS", "").strip())
        try:
            mta = int(mta_raw)
        except (ValueError, TypeError):
            mta = -1
        if confirm != "YES" or mta != 1:
            log = [
                f"⛔ LIVE-MODE-ABORT: ALLOW_LIVE_EXTERNAL_ACTIONS=true ohne korrekte Flags.",
                f"   CONFIRM_LIVE_TEST={confirm!r} (muss 'YES' sein)",
                f"   MAX_TEST_ACTIONS={mta_raw!r} (muss '1' sein)",
                f"   Repost-Run wurde sicherheitshalber abgebrochen.",
            ]
            for ln in log: print(ln)
            set_status("error", "live-mode flag-mismatch — abort", log)
            return
        # Mass-Live-Flags müssen alle aus sein
        forbidden = ["ALLOW_MASS_LIVE","ALLOW_BULK_DM","ALLOW_BULK_REPOST",
                     "ALLOW_FULL_BLAST","DISABLE_RATE_LIMITS","DISABLE_DAILY_CAP"]
        bad = [f for f in forbidden if (os.environ.get(f,"").strip().lower() in ("1","true","yes","on"))]
        if bad:
            log = [f"⛔ LIVE-MODE-ABORT: mass-live flag(s) set: {bad}"]
            for ln in log: print(ln)
            set_status("error", f"mass-live flags set: {bad}", log)
            return
        # HART-CAP: nur 1 Account, nur 1 Link
        log = []
        if len(accounts) > 1:
            log.append(f"⚠ LIVE-CAP: {len(accounts)} accounts im auftrag → cap to 1 (nur erster wird verwendet)")
            accounts = accounts[:1]
        if len(links) > 1:
            log.append(f"⚠ LIVE-CAP: {len(links)} links im auftrag → cap to 1 (nur erster wird verwendet)")
            links = links[:1]
        log.append(f"━━ LIVE MODE ACTIVE — single-shot: 1 account × 1 link = max 1 action ━━")
        for ln in log: print(ln)
        # Diese Vorwarnung wird in den späteren log[] gemergt unten
        _live_cap_warnings = log
    else:
        _live_cap_warnings = []

    # ─── Pre-Flight-Modus: nur Status checken, keine Reposts ──
    if preflight:
        log = []
        results = {}
        set_status("running", f"Preflight — {len(accounts)} Accounts werden geprüft", log)
        disk_full = False
        try:
            for idx, acc in enumerate(accounts, start=1):
                if disk_full:
                    results[acc["user_id"]] = {"user_id": acc["user_id"], "name": acc.get("name") or acc["user_id"],
                                                "state": "skipped", "reason": "adspower-disk-full",
                                                "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")}
                    save_json(PREFLIGHT_PATH, results)
                    continue
                # Fortschritt sichtbar machen (verhindert "stuck"-Optik im Dashboard)
                set_status("running",
                           f"Preflight {idx}/{len(accounts)}: {acc.get('name') or acc['user_id']}",
                           log)
                try:
                    r = preflight_account(acc, log)
                    results[r["user_id"]] = r
                    reason_low = (r.get("reason","") or "").lower()
                    if "disk space" in reason_low or "running out of disk" in reason_low:
                        disk_full = True
                        log.append(f"⛔ AdsPower-Disk voll — Preflight abgebrochen ab Account {idx+1}.")
                except Exception as e:
                    emsg = str(e)
                    if "disk space" in emsg.lower() or "running out of disk" in emsg.lower():
                        disk_full = True
                        log.append(f"⛔ AdsPower-Disk voll bei {acc.get('name')} — Preflight abgebrochen.")
                    results[acc["user_id"]] = {"user_id": acc["user_id"], "name": acc.get("name") or acc["user_id"],
                                                "state": "error", "reason": emsg[:200],
                                                "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")}
                    log.append(f"{acc.get('name')}: ⚠ {emsg[:140]}")
                # Live-Persist nach jedem Account
                save_json(PREFLIGHT_PATH, results)
        except Exception as fatal:
            # Bot soll NIE silent sterben — immer einen Endstatus schreiben.
            log.append(f"💥 Fatal: {fatal}")
            print(f"\n  💥 Fatal: {fatal}")

        # Zusammenfassung
        by_state = {}
        for r in results.values():
            by_state[r.get("state","unknown")] = by_state.get(r.get("state","unknown"), 0) + 1
        elapsed = int(time.time() - start)
        mins, secs = divmod(elapsed, 60)
        if by_state:
            summary = "Preflight fertig — " + ", ".join(f"{n}× {s}" for s, n in sorted(by_state.items(), key=lambda x: -x[1])) + f" in {mins}m {secs}s"
        else:
            summary = f"Preflight beendet ohne Ergebnisse in {mins}m {secs}s"
        set_status("done", summary, log)
        print(f"\n  ✅ {summary}\n")
        return

    if not links:
        set_status("skipped", "Keine Links ausgewählt", [])
        return

    log = list(_live_cap_warnings)  # Live-Cap-Warnungen ins User-sichtbare log uebernehmen

    # ─── Preflight: parallel pro Account testen ob Retweets möglich sind ──
    if preflight_and_filter is not None and not auftrag.get("skip_preflight"):
        preflight_workers = int(auftrag.get("preflight_workers") or 3)
        healthy, failed = preflight_and_filter(
            accounts, mode="retweet", log=log,
            set_status_fn=lambda step: set_status("running", step, log),
            max_workers=preflight_workers,
        )
        if not healthy:
            set_status("error",
                       f"Preflight: ALLE {len(accounts)} Accounts haben Probleme — siehe Log",
                       log)
            return
        accounts = healthy

    total_ok = total_renewed = total_already = total_err = 0
    set_status("running", f"Start — {len(links)} Links × {len(accounts)} Accounts", log)

    disk_full = False
    for acc in accounts:
        if disk_full:
            log.append(f"⏭  {acc.get('name')}: übersprungen — AdsPower Disk-Space-Problem.")
            continue
        try:
            ok, ren, alr, err = process_account(acc, links, log_archive, log)
            total_ok += ok
            total_renewed += ren
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
               f"{total_renewed} renewed, "
               f"{total_already} schon vorher, {total_err} Fehler in {mins}m {secs}s")
    set_status("done", summary, log)
    print(f"\n  ✅ {summary}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Letzte Verteidigungslinie: schreibe IMMER einen Endstatus,
        # damit das Dashboard nicht ewig "running" zeigt.
        try:
            existing = load_json(STATUS_PATH, {"log":[]})
            log = existing.get("log") or []
            log.append(f"💥 Bot abgestürzt: {e}")
            save_json(STATUS_PATH, {"state":"error","step":f"crashed: {e}","current_account":"","log":log})
        except Exception:
            pass
        raise
