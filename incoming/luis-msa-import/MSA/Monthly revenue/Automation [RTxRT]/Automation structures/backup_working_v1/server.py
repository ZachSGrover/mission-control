#!/usr/bin/env python3
"""
Revenue Dashboard – Server
Liest Daten aus data.json und serviert sie an Chrome.

Starten:  python server.py
Browser:  http://localhost:8765
Stoppen:  Ctrl+C
"""
import http.server, json, os, sys, subprocess, urllib.request, urllib.parse
from socketserver import ThreadingMixIn
class ThreadedHTTPServer(ThreadingMixIn, http.server.HTTPServer): pass

PORT = 8765
BASE = os.path.dirname(os.path.abspath(__file__))

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

        elif self.path == "/xdashboard" or self.path == "/xdashboard.html":
            path = os.path.join(BASE, "xdashboard.html")
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
            auftrag_path = os.path.join(BASE, "auftrag.json")
            if os.path.exists(auftrag_path):
                with open(auftrag_path, "r", encoding="utf-8") as f:
                    self.send_json(json.load(f))
            else:
                self.send_json({"status": "leer"})

        elif self.path == "/ads-profiles":
            ADS_KEY = os.environ.get("ADSPOWER_API_KEY", "")
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
            p = os.path.join(BASE, "status.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"state":"idle","step":"","log":[]})

        elif self.path == "/chats":
            p = os.path.join(BASE, "chats.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"chats":[]})

        elif self.path == "/confirm":
            p = os.path.join(BASE, "confirm.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"confirmed":False})

        elif self.path == "/contacts":
            p = os.path.join(BASE, "contacts.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})

        elif self.path == "/logo.jpg":
            path = os.path.join(BASE, "logo.jpg")
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
            p = os.path.join(BASE, "schedule.json")
            self.send_json(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"enabled": False, "time": "01:00"})

        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/auftrag":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            auftrag_path = os.path.join(BASE, "auftrag.json")
            with open(auftrag_path, "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ auftrag.json gespeichert")
            self.send_json({"status": "ok"})
        elif self.path == "/chats":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(BASE, "chats.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ chats.json gespeichert")
            self.send_json({"status": "ok"})
        elif self.path == "/confirm":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(BASE, "confirm.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ confirm.json gespeichert")
            self.send_json({"status": "ok"})
        elif self.path == "/contacts":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(BASE, "contacts.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            print(f"  ✓ contacts.json gespeichert")
            self.send_json({"status": "ok"})

        elif self.path == "/status":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(os.path.join(BASE, "status.json"), "w", encoding="utf-8") as f:
                f.write(body.decode("utf-8"))
            self.send_json({"status": "ok"})

        elif self.path == "/start-bot":
            try:
                script = os.path.join(BASE, "dm_bot.py")
                subprocess.Popen(
                    [sys.executable, script],
                    cwd=BASE,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
                )
                print(f"  ✓ dm_bot.py gestartet")
                self.send_json({"status": "started"})
            except Exception as e:
                self.send_json({"status": "error", "msg": str(e)})

        elif self.path == "/schedule":
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length).decode("utf-8"))
            sched_path = os.path.join(BASE, "schedule.json")
            with open(sched_path, "w", encoding="utf-8") as f:
                json.dump(body, f)
            # Windows Task Scheduler
            script = os.path.join(BASE, "dm_bot.py")
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
