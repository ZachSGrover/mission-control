"""
_preflight.py — Shared parallel preflight for all 4 bots.

Vor jedem Bot-Run wird hier per Account geprüft:
  - Login-Status
  - X-Verifizierung (/account/access)
  - Cloudflare Bot-Challenge
  - Suspension / Lock / Restriction
  - (Mode 'dm'): DMs erreichbar, kein PIN-Lock, DMs nicht deaktiviert
  - (Mode 'retweet'): Home-Feed lädt → Retweets möglich

Returns pro Account: state + reason + user-friendly action hint.
"""
import sys
import time
import datetime
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# UTF-8 Stdout absichern (falls von Subprocess ohne PYTHONIOENCODING geladen)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ADS_HOST = "http://local.adspower.net:50325"

# Locks, um zu verhindern dass mehrere Threads simultan dieselbe user_id öffnen
_per_uid_locks: dict = {}
_locks_guard = threading.Lock()

def _lock_for(uid: str) -> threading.Lock:
    with _locks_guard:
        lk = _per_uid_locks.get(uid)
        if lk is None:
            lk = threading.Lock()
            _per_uid_locks[uid] = lk
        return lk

# ──────────────────────────────────────────────────────
#  AdsPower
# ──────────────────────────────────────────────────────
# Globaler Semaphor: maximal X gleichzeitig offene Browser
# (AdsPower-Limit typisch 2–5 — wir nehmen 2 als sicheren Default;
# über CAMPAIGN-Env-Var oder direkt im Code anpassbar)
import threading as _th
_browser_slot = _th.Semaphore(2)

def ads_open(user_id: str, retries: int = 3) -> str:
    """Öffnet AdsPower-Profil mit Retry bei concurrent-limit.
    Belegt einen globalen Semaphor-Slot — Aufrufer MUSS ads_close aufrufen."""
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(f"{ADS_HOST}/api/v1/browser/start",
                             params={"user_id": user_id}, timeout=45)
        except requests.exceptions.RequestException as e:
            last_err = RuntimeError(f"AdsPower nicht erreichbar: {e}")
            time.sleep(2 * (attempt + 1))
            continue
        try:
            data = r.json()
        except Exception as e:
            last_err = RuntimeError(f"AdsPower antwortet ungültig: {e}")
            time.sleep(2 * (attempt + 1))
            continue
        if data.get("code") == 0:
            try:
                return data["data"]["ws"]["puppeteer"]
            except (KeyError, TypeError) as e:
                raise RuntimeError(f"AdsPower-Response ohne ws-URL: {data}") from e
        # Fehler-Code → analyze
        msg = (data.get("msg") or "") + " " + str(data)
        msg_low = msg.lower()
        if "disk space" in msg_low or "running out of disk" in msg_low:
            raise RuntimeError("AdsPower: running out of disk space")
        if "concurrent" in msg_low or "too many" in msg_low or "limit" in msg_low:
            # Retryable — vielleicht ist ein anderer Browser kurz später zu
            last_err = RuntimeError(f"AdsPower: concurrent-limit (try {attempt+1}/{retries})")
            wait = 4 + attempt * 3   # 4s, 7s, 10s
            time.sleep(wait)
            continue
        # Sonstiger Fehler → nicht retryable
        raise RuntimeError(f"AdsPower Fehler: {data.get('msg') or data}")
    # Alle Retries erschöpft
    raise last_err or RuntimeError("AdsPower: unknown error after retries")

def ads_close(user_id: str):
    try:
        requests.get(f"{ADS_HOST}/api/v1/browser/stop",
                     params={"user_id": user_id}, timeout=10)
    except Exception:
        pass

# ──────────────────────────────────────────────────────
#  Page-Helpers
# ──────────────────────────────────────────────────────
def _eval_body(page) -> str:
    try:
        return (page.evaluate("() => document.body ? document.body.innerText : ''") or "")
    except Exception:
        return ""

def wait_for_x_ready(page, timeout: float = 12.0) -> str:
    """Aktives Warten bis X-SPA gerendert. Returns 'home'|'login'|'error'|'timeout'."""
    deadline = time.time() + timeout
    LOGGED_IN = ('[data-testid="primaryColumn"], [data-testid="SideNav_AccountSwitcher_Button"], '
                 '[data-testid="AppTabBar_Home_Link"], a[href="/home"][role="link"]')
    LOGIN_SEL = ('input[name="text"], input[name="session[username_or_email]"], '
                 'a[href="/i/flow/login"], a[data-testid="loginButton"]')
    while time.time() < deadline:
        try:
            try:
                if page.locator(LOGIN_SEL).first.is_visible(timeout=300):
                    return "login"
            except Exception:
                pass
            try:
                if page.locator(LOGGED_IN).first.is_visible(timeout=300):
                    return "home"
            except Exception:
                pass
            b = _eval_body(page).lower()
            if b and ("something went wrong" in b or "try refreshing" in b):
                return "error"
            if len(b) > 250:
                return "home"
        except Exception:
            pass
        time.sleep(0.35)
    return "timeout"

# ──────────────────────────────────────────────────────
#  State-Detection
# ──────────────────────────────────────────────────────
def detect_account_state(page) -> tuple:
    """Returns (state, reason).

    states:
      ok | login | locked-x | locked-cloudflare | suspended | verify-required
      | restricted | pin-locked | dms-off | dms-restricted | unknown
    """
    url = (page.url or "").lower()
    body = _eval_body(page)
    low  = body.lower()

    # Cloudflare-Bot-Challenge (kann auf jeder URL auftauchen)
    if ("performing security verification" in low and ("cloudflare" in low or "ray id:" in low)) \
       or ("verifying you are" in low and "not a bot" in low):
        return "locked-cloudflare", "cloudflare-bot-challenge"

    # URL-basierte Checks
    if "/i/flow/login" in url or url.endswith("/login") or "/login?" in url:
        return "login", "not-logged-in"
    if "/i/flow/consent" in url:
        return "verify-required", "consent-required"
    if "/account/access" in url:
        return "locked-x", "x-verification-required"

    # Body-basierte Checks
    if not low or len(low) < 30:
        return "unknown", "empty-body"
    if "account suspended" in low or "your account is suspended" in low:
        return "suspended", "account-suspended"
    if "we need to make sure you’re a real person" in low or "we need to make sure you're a real person" in low:
        return "verify-required", "human-check-required"
    if ("verify your phone" in low) or ("verify your email" in low and "to continue" in low) or ("confirm your phone" in low):
        return "verify-required", "phone-or-email-verify-required"
    if "your account is locked" in low or "we locked your account" in low:
        return "locked-x", "account-locked"
    if "you can’t do that right now" in low or "you can't do that right now" in low or "rate limit exceeded" in low:
        return "restricted", "rate-limited-or-restricted"
    if "you’re temporarily restricted" in low or "you're temporarily restricted" in low:
        return "restricted", "temporarily-restricted"
    if "complete this captcha" in low or "complete a captcha" in low:
        return "verify-required", "captcha-required"

    return "ok", "ok"

def detect_dm_specific_state(page) -> tuple:
    """Auf /messages: erkennt PIN-Lock, deaktivierte DMs.
    Returns (state, reason) wobei state == 'ok' wenn DMs offen sind.
    """
    body = _eval_body(page).lower()
    if not body or len(body) < 20:
        return "unknown", "dm-page-empty"
    # PIN-Lock
    if "enter your code" in body or "enter the code" in body or "passcode" in body:
        # Heuristik: 4 OTP-Inputs sichtbar?
        try:
            otp = page.locator('input[autocomplete="one-time-code"]').count()
            if otp >= 4:
                return "pin-locked", "dm-pin-required"
        except Exception:
            pass
        if "passcode" in body:
            return "pin-locked", "dm-pin-required"
    if "your messages are off" in body or "your direct messages are off" in body:
        return "dms-off", "dms-disabled-in-settings"
    if "this account no longer accepts" in body or "doesn't accept direct messages" in body \
       or "doesn’t accept direct messages" in body:
        return "dms-restricted", "dms-not-accepted-from-you"
    return "ok", "ok"

# ──────────────────────────────────────────────────────
#  Action-Hints (was soll der User tun?)
# ──────────────────────────────────────────────────────
ACTION_HINTS = {
    "login":             "→ AdsPower-Profil öffnen und auf x.com einloggen (Username + Passwort)",
    "locked-x":          "→ AdsPower-Profil öffnen, /account/access durchklicken (CAPTCHA / Phone / Email)",
    "locked-cloudflare": "→ AdsPower-Profil öffnen, warten bis Cloudflare grünes Häkchen zeigt, dann X-Verifizierung machen. Account ist auf X's Bot-Liste.",
    "suspended":         "→ Account ist von X gesperrt — nicht mehr nutzbar. In AdsPower deaktivieren.",
    "verify-required":   "→ AdsPower-Profil öffnen, X-Verifizierung machen (CAPTCHA / Phone-Code / Email-Code)",
    "restricted":        "→ Account ist temporär eingeschränkt (Rate-Limit). 12–24h warten, dann erneut testen.",
    "pin-locked":        "→ AdsPower-Profil öffnen, DMs öffnen, PIN eingeben (Default '0000'). Im auftrag.json kann der PIN per Account gesetzt werden.",
    "dms-off":           "→ AdsPower-Profil öffnen, in X Settings → Privacy → Direct Messages aktivieren.",
    "dms-restricted":    "→ Account-Empfänger akzeptiert keine DMs von Nicht-Followern. Bot kann das nicht fixen.",
    "adspower-error":    "→ AdsPower-Probleme. Prüfe ob AdsPower läuft (Taskbar) und ob Festplatte voll ist. Dashboard: 'AdsPower-Cache leeren' klicken.",
    "nav-error":         "→ Browser/Netz-Problem. AdsPower-Profil manuell testen, ggf. Browser-Cache leeren.",
    "page-error":        "→ X zeigt 'Something went wrong'. AdsPower-Profil öffnen, page reloaden.",
    "empty-body":        "→ X hat nicht geladen. AdsPower-Profil manuell öffnen und prüfen.",
    "timeout":           "→ Verbindung zu X dauert zu lang. AdsPower neustarten oder anderen Account testen.",
    "playwright-error":  "→ Browser-Verbindung fehlgeschlagen. AdsPower-Profil neu starten.",
    "unknown":           "→ Unbekannter Zustand. AdsPower-Profil manuell öffnen und prüfen.",
}

STATE_ICONS = {
    "ok":                "✅",
    "login":             "🔒",
    "locked-x":          "🔐",
    "locked-cloudflare": "☁",
    "suspended":         "⛔",
    "verify-required":   "📱",
    "restricted":        "⏸",
    "pin-locked":        "🔑",
    "dms-off":           "📵",
    "dms-restricted":    "🚫",
    "adspower-error":    "💥",
    "nav-error":         "🌐",
    "page-error":        "⚠",
    "empty-body":        "❓",
    "timeout":           "⏱",
    "playwright-error":  "💻",
    "unknown":           "❓",
}

# ──────────────────────────────────────────────────────
#  Preflight pro Account (eine Thread-Unit)
# ──────────────────────────────────────────────────────
def preflight_one(account: dict, mode: str = "dm") -> dict:
    """
    Öffnet AdsPower, prüft state, schließt wieder. Thread-safe.
    mode:
      'dm'      → testet /home + /messages
      'retweet' → testet nur /home
      'basic'   → testet nur /home (für builder)
    Returns dict: {user_id, name, state, reason, action, mode, ts}
    """
    user_id = account["user_id"]
    name    = account.get("name") or user_id
    out = {
        "user_id": user_id, "name": name, "mode": mode,
        "state": "unknown", "reason": "", "action": "",
        "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }

    # Lock per user_id — niemals zwei Threads auf demselben Profil
    lock = _lock_for(user_id)
    if not lock.acquire(timeout=1):
        out["state"] = "playwright-error"
        out["reason"] = "uid-already-in-use"
        out["action"] = "→ Dieser Account wird gerade von einem anderen Bot benutzt."
        return out
    # Globalen Browser-Slot anfordern (verhindert AdsPower concurrent-limit Fehler)
    if not _browser_slot.acquire(timeout=180):
        lock.release()
        out["state"] = "adspower-error"
        out["reason"] = "warten auf freien Browser-Slot timed out"
        out["action"] = "→ Zu viele Browser laufen. AdsPower-App prüfen und alle offenen Browser schließen."
        return out
    try:
        try:
            ws_url = ads_open(user_id)
        except Exception as e:
            emsg = str(e)
            emsg_low = emsg.lower()
            out["state"] = "adspower-error"
            out["reason"] = emsg[:200]
            if "concurrent" in emsg_low or "limit" in emsg_low:
                out["action"] = "→ AdsPower-Concurrent-Browser-Limit erreicht. Schließe offene Browser in der AdsPower-App. Limit ggf. erhöhen (Plan-Upgrade) oder preflight_workers in auftrag.json reduzieren."
            elif "disk space" in emsg_low:
                out["action"] = "→ AdsPower-Festplatte voll. Dashboard: 'AdsPower-Cache leeren' klicken."
            elif "nicht erreichbar" in emsg_low or "connection" in emsg_low:
                out["action"] = "→ AdsPower-App läuft nicht. Starte AdsPower (Taskbar) und prüfe ob Port 50325 frei ist."
            else:
                out["action"] = ACTION_HINTS["adspower-error"] + f"\n        Reason: {emsg[:160]}"
            return out
        time.sleep(2.5)

        try:
            with sync_playwright() as p:
                browser = None
                try:
                    browser = p.chromium.connect_over_cdp(ws_url)
                    ctx = browser.contexts[0]
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()

                    # Schritt 1: /home laden
                    try:
                        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=25000)
                        ready = wait_for_x_ready(page, timeout=10.0)
                        if ready == "timeout":
                            try:
                                page.reload(wait_until="domcontentloaded", timeout=18000)
                            except Exception:
                                pass
                            wait_for_x_ready(page, timeout=6.0)
                    except Exception as e:
                        out["state"] = "nav-error"
                        out["reason"] = f"home-goto-fail: {str(e)[:160]}"
                        out["action"] = ACTION_HINTS["nav-error"]
                        return out

                    state, reason = detect_account_state(page)
                    if state != "ok":
                        out["state"] = state
                        out["reason"] = reason
                        out["action"] = ACTION_HINTS.get(state) or ACTION_HINTS.get(reason) or ""
                        return out

                    # Schritt 2 (nur bei DM-Mode): /messages laden
                    if mode == "dm":
                        try:
                            page.goto("https://x.com/messages", wait_until="domcontentloaded", timeout=20000)
                            time.sleep(2)
                            wait_for_x_ready(page, timeout=6)
                        except Exception as e:
                            out["state"] = "nav-error"
                            out["reason"] = f"messages-goto-fail: {str(e)[:160]}"
                            out["action"] = ACTION_HINTS["nav-error"]
                            return out
                        # Wenn /messages auch geblockt ist (Cloudflare, lockout)
                        s2, r2 = detect_account_state(page)
                        if s2 != "ok":
                            out["state"] = s2
                            out["reason"] = r2
                            out["action"] = ACTION_HINTS.get(s2) or ""
                            return out
                        # DM-spezifisch
                        ds, dr = detect_dm_specific_state(page)
                        if ds != "ok":
                            out["state"] = ds
                            out["reason"] = dr
                            out["action"] = ACTION_HINTS.get(ds) or ""
                            return out

                    out["state"] = "ok"
                    out["reason"] = "ok"
                    out["action"] = ""
                finally:
                    try:
                        if browser: browser.close()
                    except Exception:
                        pass
        except Exception as e:
            out["state"] = "playwright-error"
            out["reason"] = str(e)[:200]
            out["action"] = ACTION_HINTS["playwright-error"]
        finally:
            ads_close(user_id)
            time.sleep(1)
        return out
    finally:
        # Browser-Slot freigeben (anderer Account kann jetzt öffnen)
        try: _browser_slot.release()
        except Exception: pass
        lock.release()

# ──────────────────────────────────────────────────────
#  Parallel runner
# ──────────────────────────────────────────────────────
def run_parallel(accounts: list, mode: str = "dm",
                 max_workers: int = 3,
                 on_each = None) -> list:
    """
    Führt preflight parallel für alle Accounts aus.
    on_each(result_dict) wird nach jedem fertigen Account aufgerufen (z.B. Log-Push).
    Returns Liste der Results in Reihenfolge der Inputs.
    """
    n = len(accounts)
    results = [None] * n
    if n == 0:
        return results
    max_workers = max(1, min(max_workers, n))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_idx = {ex.submit(preflight_one, acc, mode): i
                         for i, acc in enumerate(accounts)}
        for fut in as_completed(future_to_idx):
            i = future_to_idx[fut]
            try:
                r = fut.result()
            except Exception as e:
                acc = accounts[i]
                r = {
                    "user_id": acc["user_id"],
                    "name": acc.get("name") or acc["user_id"],
                    "mode": mode, "state": "playwright-error",
                    "reason": str(e)[:200],
                    "action": ACTION_HINTS["playwright-error"],
                    "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                }
            results[i] = r
            if on_each:
                try:
                    on_each(r)
                except Exception:
                    pass
    return results

# ──────────────────────────────────────────────────────
#  Bequemer Helper: Preflight + Log + Filter
# ──────────────────────────────────────────────────────
def preflight_and_filter(accounts: list, mode: str, log: list,
                          set_status_fn=None,
                          max_workers: int = 3) -> tuple:
    """
    Convenience-Wrapper für Bot-Hauptfunktionen.
    - Loggt jeden Account-Status mit Action-Hint
    - Filtert OK-Accounts raus
    Returns: (healthy: list, failed: list)
    """
    n = len(accounts)
    if n == 0:
        return [], []

    if set_status_fn:
        set_status_fn(f"Preflight — {n} Accounts werden geprüft ({mode}, parallel {max_workers}x)")

    log.append(f"━━ Preflight ({mode}) — {n} Accounts ━━")
    done_counter = [0]
    lock = threading.Lock()

    def on_each(r):
        with lock:
            done_counter[0] += 1
            i = done_counter[0]
            icon = STATE_ICONS.get(r["state"], "❓")
            line = f"  [{i}/{n}] {icon} {r['name']}: {r['state']}"
            if r.get("reason") and r["reason"] != "ok":
                line += f" ({r['reason']})"
            log.append(line)
            if r["state"] != "ok" and r.get("action"):
                log.append(f"        {r['action']}")
            if set_status_fn:
                set_status_fn(f"Preflight {i}/{n} fertig — letzter: {r['name']} = {r['state']}")

    results = run_parallel(accounts, mode=mode, max_workers=max_workers, on_each=on_each)
    healthy = [accounts[i] for i, r in enumerate(results) if r and r["state"] == "ok"]
    failed  = [results[i] for i in range(len(results)) if results[i] and results[i]["state"] != "ok"]

    # Zusammenfassung
    by_state = {}
    for r in results:
        if r:
            by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    summary = ", ".join(f"{n}× {s}" for s, n in sorted(by_state.items(), key=lambda x: -x[1]))
    log.append(f"━━ Preflight fertig: {len(healthy)} OK, {len(failed)} übersprungen ({summary}) ━━")
    return healthy, failed
