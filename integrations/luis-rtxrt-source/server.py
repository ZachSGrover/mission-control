#!/usr/bin/env python3
"""
Revenue Dashboard – Server
Liest Daten aus data.json und serviert sie an Chrome.

Starten:  python server.py
Browser:  http://localhost:8765
Stoppen:  Ctrl+C
"""
import http.server, json, os, sys, subprocess, urllib.request, urllib.parse, threading, traceback
from socketserver import ThreadingMixIn
class ThreadedHTTPServer(ThreadingMixIn, http.server.HTTPServer): pass

# Notion-Sync (lazy import damit server auch ohne Token startet)
try:
    import notion_sync
except Exception as _e:
    notion_sync = None
    print(f"  ⚠ notion_sync.py nicht ladbar: {_e}")

PORT = 8765
BASE      = os.path.dirname(os.path.abspath(__file__))         # Monthly revenue/
AUTO_DIR  = os.path.join(BASE, "Automation [RTxRT]")           # Automation files
CONT_DIR  = os.path.join(BASE, "Automation [Content]")         # Content / Models

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {fmt % args}")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors(); self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/dashboard.html"):
            path = os.path.join(BASE, "dashboard.html")
            try:
                with open(path, "rb") as f: body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors(); self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_json({"error": "dashboard.html nicht gefunden"}, 404)

        elif self.path == "/data":
            data_path = os.path.join(BASE, "data.json")
            if os.path.exists(data_path):
                with open(data_path, "r", encoding="utf-8") as f:
                    self.send_json(json.load(f))
            else:
                self.send_json({"status": "waiting"})

        elif self.path in ("/models-dashboard", "/models-dashboard.html"):
            path = os.path.join(CONT_DIR, "models-dashboard.html")
            try:
                with open(path, "rb") as f: body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors(); self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_json({"error": "models-dashboard.html nicht gefunden"}, 404)

        elif self.path == "/models":
            p = os.path.join(CONT_DIR, "models.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else [])

        elif self.path == "/xdashboard" or self.path == "/xdashboard.html":
            path = os.path.join(AUTO_DIR, "xdashboard.html")
            try:
                with open(path, "rb") as f: body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors(); self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_json({"error": "xdashboard.html nicht gefunden"}, 404)

        elif self.path.startswith("/ads-start/"):
            user_id = self.path.split("/ads-start/")[1].split("?")[0]
            ads_url = f"http://local.adspower.net:50325/api/v1/browser/start?user_id={user_id}"
            try:
                req = urllib.request.Request(ads_url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = resp.read()
                print(f"  ← Browser start: {body[:300]}")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self._cors(); self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_json({"code": -1, "msg": str(e)})

        elif self.path == "/auftrag":
            auftrag_path = os.path.join(AUTO_DIR, "auftrag.json")
            if os.path.exists(auftrag_path):
                with open(auftrag_path, "r", encoding="utf-8") as f:
                    self.send_json(json.load(f))
            else:
                self.send_json({"status": "leer"})

        elif self.path == "/ads-profiles":
            ADS_KEY = "659e8c59f3a6464e250cf0d22d921d5700757728b198f647"
            ads_url = "http://local.adspower.net:50325/api/v1/user/list?page=1&page_size=100"
            try:
                req = urllib.request.Request(ads_url)
                req.add_header("api-key", ADS_KEY)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    body = resp.read()
                print(f"  ← AdsPower: {body[:200]}")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self._cors(); self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                print(f"  ✗ AdsPower Fehler: {e}")
                self.send_json({"code": -1, "msg": str(e)})

        elif self.path == "/status":
            p = os.path.join(AUTO_DIR, "status.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"state":"idle","step":"","log":[]})

        elif self.path == "/chats":
            p = os.path.join(AUTO_DIR, "chats.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"chats":[]})

        elif self.path == "/confirm":
            p = os.path.join(AUTO_DIR, "confirm.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"confirmed":False})

        elif self.path == "/contacts":
            p = os.path.join(AUTO_DIR, "contacts.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        elif self.path == "/logo.jpg":
            path = os.path.join(AUTO_DIR, "logo.jpg")
            try:
                with open(path, "rb") as f: body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self._cors(); self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_json({"error": "logo.jpg nicht gefunden"}, 404)

        elif self.path == "/schedule":
            p = os.path.join(AUTO_DIR, "schedule.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"enabled": False, "time": "01:00"})

        # ─── BLAST (Cross-Account DM Bot) ───────────────────
        elif self.path in ("/blast-dashboard", "/blast-dashboard.html"):
            path = os.path.join(AUTO_DIR, "blast_dashboard.html")
            try:
                with open(path, "rb") as f: body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors(); self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_json({"error": "blast_dashboard.html nicht gefunden"}, 404)

        elif self.path == "/blast-auftrag":
            p = os.path.join(AUTO_DIR, "blast_auftrag.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        elif self.path == "/blast-status":
            p = os.path.join(AUTO_DIR, "blast_status.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"state":"idle","step":"","current_account":"","log":[]})

        elif self.path == "/blast-log":
            p = os.path.join(AUTO_DIR, "blast_log.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        # ─── BUILDER (New-Database mode) ────────────────────
        elif self.path == "/builder-auftrag":
            p = os.path.join(AUTO_DIR, "builder_auftrag.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        elif self.path == "/builder-status":
            p = os.path.join(AUTO_DIR, "builder_status.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"state":"idle","step":"","log":[]})

        elif self.path == "/follower-lists":
            p = os.path.join(AUTO_DIR, "follower_lists.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        # ─── REPOST (Promo Group Repost) ────────────────────
        elif self.path == "/repost-auftrag":
            p = os.path.join(AUTO_DIR, "repost_auftrag.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        elif self.path == "/repost-status":
            p = os.path.join(AUTO_DIR, "repost_status.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"state":"idle","step":"","current_account":"","log":[]})

        elif self.path == "/repost-log":
            p = os.path.join(AUTO_DIR, "repost_log.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        elif self.path == "/promo-groups":
            p = os.path.join(AUTO_DIR, "promo_groups.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        elif self.path == "/preflight-status":
            p = os.path.join(AUTO_DIR, "preflight_status.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        # ─── CAMPAIGN (Repost + DM kombiniert) ─────────────
        elif self.path == "/campaign-auftrag":
            p = os.path.join(AUTO_DIR, "campaign_auftrag.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        elif self.path == "/campaign-status":
            p = os.path.join(AUTO_DIR, "campaign_status.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"state":"idle","step":"","log":[]})

        # ─── Blast-Dashboard URL → unified Dashboard ────────
        elif self.path in ("/blast-dashboard", "/blast-dashboard.html"):
            self.send_response(302)
            self.send_header("Location", "/xdashboard")
            self._cors(); self.end_headers()

        elif self.path == "/sync":
            # On-demand Notion-Sync — schreibt data.json komplett neu
            if notion_sync is None:
                self.send_json({"ok": False, "error": "notion_sync.py nicht geladen"}, 500)
                return
            try:
                result = notion_sync.run()
                print(f"  ✓ Notion-Sync: {result['ofRows']} Revenue + {result['pmtRows']} Payments")
                self.send_json(result)
            except Exception as e:
                print(f"  ✗ Notion-Sync fehlgeschlagen: {e}")
                traceback.print_exc()
                self.send_json({"ok": False, "error": str(e)}, 500)

        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/auftrag":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            auftrag_path = os.path.join(AUTO_DIR, "auftrag.json")
            with open(auftrag_path, "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ auftrag.json gespeichert")
            self.send_json({"status": "ok"})
        elif self.path == "/chats":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "chats.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ chats.json gespeichert")
            self.send_json({"status": "ok"})
        elif self.path == "/confirm":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "confirm.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ confirm.json gespeichert")
            self.send_json({"status": "ok"})
        elif self.path == "/contacts":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "contacts.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ contacts.json gespeichert")
            self.send_json({"status": "ok"})

        elif self.path == "/status":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "status.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            self.send_json({"status": "ok"})

        elif self.path == "/models":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            models_path = os.path.join(CONT_DIR, "models.json")
            os.makedirs(CONT_DIR, exist_ok=True)
            with open(models_path, "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ models.json gespeichert")
            self.send_json({"status": "ok"})

        elif self.path == "/analyze":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            try:
                import anthropic
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if not api_key:
                    self.send_json({"error": "ANTHROPIC_API_KEY environment variable not set. Set it and restart server.py."})
                    return
                client = anthropic.Anthropic(api_key=api_key)
                name    = data.get("name", "Unknown")
                alias   = data.get("alias", "")
                niche   = data.get("niche", "Not specified")
                notes   = data.get("notes", "")
                accts   = data.get("accounts", {})
                def fmt_accts(key, prefix):
                    vals = accts.get(key, [])
                    if isinstance(vals, str): vals = [vals] if vals else []
                    out = []
                    for v in vals:
                        if isinstance(v, str):
                            if v: out.append(f"{prefix}{v} (SFW)")
                        elif isinstance(v, dict):
                            h = v.get("handle", "")
                            if not h: continue
                            tag = "NSFW" if v.get("nude") else "SFW"
                            out.append(f"{prefix}{h} ({tag})")
                    return ", ".join(out) or "—"
                platforms_str = (
                    f"X/Twitter: {fmt_accts('x','@')} | "
                    f"Instagram: {fmt_accts('ig','@')} | "
                    f"OnlyFans: {fmt_accts('of','/')} | "
                    f"TikTok: {fmt_accts('tt','@')}"
                )
                prompt = f"""You are an elite social media content strategist specialized in creator growth and monetization.

Analyze this creator profile and provide a complete weekly content strategy:

**Creator:** {name}{f' (alias: {alias})' if alias else ''}
**Niche / Category:** {niche}
**Platforms:** {platforms_str}
**Notes:** {notes if notes else 'None'}

**IMPORTANT — content level per account:** Each account is tagged (SFW) or (NSFW). SFW accounts (e.g. mainstream IG, public X) MUST stay safe-for-work — clean fitness, lifestyle, no nudity, no explicit teasing. NSFW accounts (e.g. some OnlyFans, alt X accounts) can use nude/explicit content. Tailor every post idea, hook and caption to the level of the platform it's intended for. Never recommend nude content for an SFW-tagged account.

Provide a structured analysis with these exact sections using markdown:

## 🎯 Niche & Audience Analysis
2-3 sentences on the exact niche, sub-niche, target audience, and what emotional triggers/fantasies perform best for this type of creator.

## 📊 Content Pillars
List 4 core content pillars with a one-line description each. Be specific to this niche.

## 💡 7 Feed Post Ideas
Numbered list. Each idea = format + caption hook + CTA. Be specific and actionable.

## 🔥 3 Viral Hook Ideas
Opening lines designed to stop the scroll. Include platform context.

## 💬 3 Engagement Bait Ideas
Posts designed to drive comments, saves, shares.

## 🎬 3 Short-Form Video / Reel Ideas
Specific concepts with structure (hook → body → CTA).

## 💰 2 High-Converting Promotional Ideas
Posts designed to drive OnlyFans subscriptions or paid content sales.

## 📅 Weekly Posting Schedule
Table: Platform | Posts/Week | Best Times | Content Mix

## ⚠️ Optimization Advice
- What to STOP doing
- What to DOUBLE DOWN on
- Top missed opportunity

Keep advice specific to this creator's niche. No generic filler."""

                msg = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1800,
                    messages=[{"role": "user", "content": prompt}]
                )
                self.send_json({"analysis": msg.content[0].text})
            except ImportError:
                self.send_json({"error": "anthropic package not installed. Run: pip install anthropic"})
            except Exception as e:
                self.send_json({"error": str(e)})

        elif self.path == "/start-bot":
            try:
                script = os.path.join(AUTO_DIR, "dm_bot.py")
                subprocess.Popen(
                    [sys.executable, script],
                    cwd=AUTO_DIR,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
                )
                print(f"  ✓ dm_bot.py gestartet")
                self.send_json({"status": "started"})
            except Exception as e:
                self.send_json({"status": "error", "msg": str(e)})

        # ─── BLAST POST endpoints ───────────────────────────
        elif self.path == "/blast-auftrag":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "blast_auftrag.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ blast_auftrag.json gespeichert")
            self.send_json({"status": "ok"})

        elif self.path == "/blast-status":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "blast_status.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            self.send_json({"status": "ok"})

        elif self.path == "/blast-start":
            try:
                script = os.path.join(AUTO_DIR, "blast_bot.py")
                subprocess.Popen(
                    [sys.executable, script],
                    cwd=AUTO_DIR,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
                )
                print(f"  ✓ blast_bot.py gestartet")
                self.send_json({"status": "started"})
            except Exception as e:
                self.send_json({"status": "error", "msg": str(e)})

        # ─── BUILDER POST endpoints ─────────────────────────
        elif self.path == "/builder-auftrag":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "builder_auftrag.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ builder_auftrag.json gespeichert")
            self.send_json({"status": "ok"})

        elif self.path == "/builder-status":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "builder_status.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            self.send_json({"status": "ok"})

        elif self.path == "/builder-start":
            try:
                script = os.path.join(AUTO_DIR, "builder_bot.py")
                subprocess.Popen(
                    [sys.executable, script],
                    cwd=AUTO_DIR,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
                )
                print(f"  ✓ builder_bot.py gestartet")
                self.send_json({"status": "started"})
            except Exception as e:
                self.send_json({"status": "error", "msg": str(e)})

        # ─── REPOST POST endpoints ──────────────────────────
        elif self.path == "/repost-auftrag":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "repost_auftrag.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            self.send_json({"status": "ok"})

        elif self.path == "/repost-status":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "repost_status.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            self.send_json({"status": "ok"})

        elif self.path == "/repost-start":
            try:
                script = os.path.join(AUTO_DIR, "repost_bot.py")
                subprocess.Popen(
                    [sys.executable, script], cwd=AUTO_DIR,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
                )
                print(f"  ✓ repost_bot.py gestartet")
                self.send_json({"status": "started"})
            except Exception as e:
                self.send_json({"status": "error", "msg": str(e)})

        # ─── CAMPAIGN (Orchestrator: Repost → DM) ───────────
        elif self.path == "/campaign-auftrag":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "campaign_auftrag.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ campaign_auftrag.json gespeichert")
            self.send_json({"status": "ok"})

        elif self.path == "/campaign-status":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "campaign_status.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            self.send_json({"status": "ok"})

        elif self.path == "/campaign-start":
            try:
                script = os.path.join(AUTO_DIR, "campaign.py")
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUTF8"] = "1"
                subprocess.Popen(
                    [sys.executable, script], cwd=AUTO_DIR,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                    env=env,
                )
                print(f"  ✓ campaign.py gestartet")
                self.send_json({"status": "started"})
            except Exception as e:
                self.send_json({"status": "error", "msg": str(e)})

        elif self.path == "/promo-groups":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(AUTO_DIR, "promo_groups.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ promo_groups.json gespeichert")
            self.send_json({"status": "ok"})

        elif self.path == "/ads-clean-cache":
            # Versucht mehrere AdsPower-Endpoints — deren Naming hat sich über Versionen verändert
            ADS_KEY = "659e8c59f3a6464e250cf0d22d921d5700757728b198f647"
            ADS_BASE = "http://local.adspower.net:50325"
            candidates = [
                ("GET",  "/api/v1/user/delete-cache"),
                ("POST", "/api/v1/user/delete-cache"),
                ("GET",  "/api/v1/browser/delete-cache"),
            ]
            results = []
            any_ok = False
            for method, ep in candidates:
                try:
                    req = urllib.request.Request(f"{ADS_BASE}{ep}", method=method)
                    req.add_header("api-key", ADS_KEY)
                    if method == "POST":
                        req.add_header("Content-Type", "application/json")
                        req.data = b"{}"
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        body_bytes = resp.read()
                        body_str = body_bytes[:500].decode("utf-8", errors="replace")
                        try: parsed = json.loads(body_str)
                        except Exception: parsed = {"raw": body_str}
                        ok = (resp.status == 200 and isinstance(parsed, dict) and parsed.get("code") == 0)
                        if ok: any_ok = True
                        results.append({"endpoint": ep, "method": method, "status": resp.status, "body": parsed})
                except Exception as e:
                    results.append({"endpoint": ep, "method": method, "error": str(e)[:200]})
            self.send_json({"any_ok": any_ok, "results": results})
            print(f"  ✓ ads-clean-cache versucht: any_ok={any_ok}")

        # ─── LIST-MANAGEMENT (delete / merge) ───────────────
        elif self.path == "/list-delete":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self.send_json({"status":"error","msg":"bad json"}, 400); return
            kind = body.get("kind"); uid = body.get("uid")
            if kind not in ("contacts", "followers") or not uid:
                self.send_json({"status":"error","msg":"missing/invalid kind or uid"}, 400); return
            fname = "contacts.json" if kind == "contacts" else "follower_lists.json"
            path = os.path.join(AUTO_DIR, fname)
            if not os.path.exists(path):
                self.send_json({"status":"error","msg":f"{fname} not found"}, 404); return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if uid not in data:
                self.send_json({"status":"error","msg":f"{uid} not in {fname}"}, 404); return
            removed = len(data[uid])
            del data[uid]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  ✓ Liste gelöscht: {fname}[{uid}] ({removed} Einträge)")
            self.send_json({"status":"ok","kind":kind,"uid":uid,"removed":removed})

        elif self.path == "/list-merge":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self.send_json({"status":"error","msg":"bad json"}, 400); return
            kind = body.get("kind")
            src = body.get("from_uid"); dst = body.get("into_uid")
            if kind not in ("contacts","followers") or not src or not dst or src == dst:
                self.send_json({"status":"error","msg":"missing/invalid params"}, 400); return
            fname = "contacts.json" if kind == "contacts" else "follower_lists.json"
            path = os.path.join(AUTO_DIR, fname)
            if not os.path.exists(path):
                self.send_json({"status":"error","msg":f"{fname} not found"}, 404); return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if src not in data:
                self.send_json({"status":"error","msg":f"source {src} not found"}, 404); return
            src_arr = data.get(src, [])
            dst_arr = data.get(dst, [])
            added = 0
            if kind == "contacts":
                # Dedup: prefer existing dst entries (preserve last_sent), then append new src entries.
                by_url = {}
                no_url = []
                for entry in dst_arr:
                    u = entry.get("url")
                    if u: by_url[u] = entry
                    else: no_url.append(entry)
                for entry in src_arr:
                    u = entry.get("url")
                    if u:
                        if u not in by_url:
                            by_url[u] = entry
                            added += 1
                    else:
                        no_url.append(entry); added += 1
                data[dst] = list(by_url.values()) + no_url
            else:  # followers
                by_h = {(e.get("handle") or "").lower(): e for e in dst_arr if e.get("handle")}
                for entry in src_arr:
                    h = (entry.get("handle") or "").lower()
                    if h and h not in by_h:
                        by_h[h] = entry
                        added += 1
                data[dst] = list(by_h.values())
            del data[src]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  ✓ Merge {fname}: {src} → {dst} (+{added} neu)")
            self.send_json({"status":"ok","kind":kind,"added":added,"into":dst,"removed_source":src})

        elif self.path == "/schedule":
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length).decode("utf-8"))
            sched_path = os.path.join(AUTO_DIR, "schedule.json")
            with open(sched_path, "w", encoding="utf-8") as f:
                json.dump(body, f)
            # Windows Task Scheduler
            script = os.path.join(AUTO_DIR, "dm_bot.py")
            task   = "XDMBot"
            if body.get("enabled"):
                t = body.get("time", "01:00")
                cmd = ["schtasks", "/create", "/tn", task,
                       "/tr", f'"{sys.executable}" "{script}"',
                       "/sc", "daily", "/st", t, "/f"]
                r = subprocess.run(cmd, capture_output=True, text=True)
                ok = r.returncode == 0
                print(f"  ✓ Zeitplan gesetzt: {t} ({'OK' if ok else r.stderr.strip()})")
                self.send_json({"status": "ok" if ok else "error", "msg": r.stderr.strip()})
            else:
                subprocess.run(["schtasks", "/delete", "/tn", task, "/f"],
                               capture_output=True, text=True)
                print(f"  ✓ Zeitplan deaktiviert")
                self.send_json({"status": "ok"})

        else:
            self.send_json({"error": "not found"}, 404)

if __name__ == "__main__":
    print(f"\n{'─'*50}")
    print(f"  Revenue Dashboard")
    print(f"{'─'*50}")
    print(f"  http://localhost:{PORT}")
    print(f"  Stoppen: Ctrl+C")
    print(f"{'─'*50}\n")
    ThreadedHTTPServer(("localhost", PORT), Handler).serve_forever()
