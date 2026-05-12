# X Automation – Vollständiges Briefing für neue Claude-Session

> Lies diese Datei zu Beginn einer neuen Session vollständig durch, um sofort up to speed zu sein.

---

## Wer ist der User?

Luis betreibt eine MSA (Model-Management-Agentur). Er verwaltet mehrere OnlyFans/X-Accounts von Models. Die Automation sendet DMs auf X (Twitter) aus verschiedenen Accounts heraus – um Fans/Kunden anzuschreiben.

---

## Architektur-Überblick

```
[xdashboard.html]  ←→  [server.py :8765]  ←→  [Claude]  →  [AdsPower]  →  [X.com]
     Dashboard            HTTP API          Automation      Anti-Detect    DM senden
```

### Komponenten

| Komponente | Beschreibung |
|---|---|
| `xdashboard.html` | 3-Step-Dashboard im Browser (Chrome). Profil wählen → Nachricht eingeben → Kontakte bestätigen & senden |
| `server.py` | Python HTTP-Server auf Port 8765. Liest/schreibt JSON-Dateien. Muss manuell gestartet werden: `python server.py` im Ordner "Monthly revenue" |
| AdsPower | Anti-Detect Browser auf `http://127.0.0.1:50325`. Öffnet für jeden Account einen eigenen "Sunbrowser" (Chromium-Fenster) |
| `Sunbrowser` | Das Chromium-Fenster das AdsPower öffnet. Hier läuft X.com. Claude steuert NUR dieses Fenster – NIE Chrome direkt |
| contacts.json | **Archiv** aller je angeschriebenen Kontakte mit Timestamp. Wird genutzt für 24h-Filter |
| chats.json | **Temporäre Liste** der gescannten Chats für den aktuellen Run. Wird am Start jedes Runs auf `{"chats":[]}` zurückgesetzt |
| auftrag.json | Aufgabe für Claude: welcher Account, welche Nachricht, wie viele Chats max |
| status.json | Live-Status (state, step, log). Dashboard liest das alle 2s |
| confirm.json | User bestätigt Kontaktauswahl. `confirmed: true` = Claude startet Versand |

---

## Dateien im Detail

### server.py – Endpoints

| Endpoint | Methode | Funktion |
|---|---|---|
| `/status` | GET/POST | Status lesen/schreiben |
| `/auftrag` | GET/POST | Auftrag lesen/schreiben |
| `/confirm` | GET/POST | Bestätigung lesen/schreiben |
| `/chats` | GET/POST | Chats lesen/schreiben (reset am Start) |
| `/contacts` | GET/POST | Kontakt-Archiv lesen/schreiben |
| `/profiles` | GET | AdsPower-Profile abrufen (ruft `127.0.0.1:50325` ab) |

**Server starten:** `python server.py` im Ordner "Monthly revenue"  
**Server muss neu gestartet werden** wenn Code geändert wird.

### xdashboard.html – 2-Step-Flow (NEU ab 2026-05-05)

1. **Step 1 – Profil wählen:** Lädt Profile von `/profiles` (AdsPower). User wählt Account.
2. **Step 2 – Nachricht eingeben:** Texteingabe + "Anzahl Nachrichten" (Bedeutung NEU, siehe unten).  
   Beim Klick auf "Weiter": Browser/AdsPower-Instanz öffnen, chats.json zurücksetzen, auftrag.json schreiben.  
   **→ Claude startet sofort und sendet ohne weitere Bestätigung.**
3. ~~Step 3 (Kontakte & Senden) entfällt~~ — kein Confirm-Schritt mehr nötig. Dashboard zeigt nur Live-Status/Log.

### Bedeutung von `max_chats` (NEU)

`max_chats` = **Anzahl der Nachrichten, die wirklich rausgehen sollen** — NICHT die Anzahl gescannter Chats.

Claude muss also so weit scrollen + scannen, **bis `max_chats` qualifizierte (= nicht im 24h-Filter befindliche und nicht read-only) Kontakte gefunden sind**. Beispiel: User gibt 30 ein → es werden 30 DMs gesendet, auch wenn dafür 50+ Chats gescannt werden müssen.

**Stop-Bedingungen für den Scan:**
- N qualifizierte Kontakte gefunden → Scan stoppen, Send-Loop starten
- Ende der Chat-Liste erreicht (weiteres Scrollen liefert keine neuen Namen) → mit dem stoppen was da ist

**Kein User-Confirm mehr:** Sobald die Liste gefunden ist, läuft Claude direkt in den Send-Loop. Keine `confirm.json`-Wartezeit, keine Dashboard-Bestätigung. Status updates im Live-Log reichen.

### contacts.json – Struktur

```json
{
  "k1atoh5f": {
    "pulseguy83nyc": {"last_sent": "2026-05-05T...", "url": "https://x.com/messages/..."},
    "Sandro": {"last_sent": "2026-05-05T...", "url": "https://x.com/messages/..."}
  },
  "k1bhvfaa": {
    "DavidOFIII": {"last_sent": "2026-05-05T..."},
    ...
  }
}
```

Key = AdsPower user_id (z.B. `k1bhvfaa` = AVAILABLE account).  
24h-Filter: Wenn `last_sent` < 24h alt → wird in Dashboard nicht angezeigt.

---

## AdsPower – Account öffnen

```
GET http://127.0.0.1:50325/api/v1/browser/start?user_id=<user_id>&open_tabs=1
```

Antwortet mit `ws` (WebSocket-Debug-URL) – wird aktuell nicht genutzt.  
Claude öffnet AdsPower-Browser, wartet, wechselt zum Sunbrowser-Fenster.

**WICHTIG:** Chrome ist Browser Tier "read" → Claude kann NICHT klicken/tippen in Chrome.  
Sunbrowser (das AdsPower-Fenster) ist Tier "full" → volle Kontrolle.  
Falls Sunbrowser nicht in Taskleiste sichtbar: Taskleiste-Klick ca. (519, 873).

---

## Grid-Click-Strategie

X.com Nachrichten-Grid (Suchansicht, geöffnet durch Klick auf Suchleiste):

- **9 Kontakte pro Zeile**
- X-Positionen: 136, 229, 322, 415, 508, 602, 695, 788, 881
- Y-Positionen: Row1=290, Row2=435, Row3=575, Row4=715
- Für Row5+: nach unten scrollen

**Wichtigste Eigenschaft:** Nach jedem Send rückt der gesendete Kontakt an Position 1 (die Grid-Reihenfolge ist "most recent first"). Das heißt:

> Nach N erfolgreich gesendeten Nachrichten befinden sich die N gesendeten Kontakte auf den Positionen 1–N.  
> Der nächste ungesendete Kontakt ist **immer auf Position N+1**.

**Formel für Koordinaten:**
```
col = N % 9
row = floor(N / 9)
x = 136 + col * 93
y = 290 + row * 145
```

Für Row5 und weiter: scrollen nötig (3-4 Scroll-Ticks nach unten in Grid-Bereich).

---

## Sende-Sequenz pro Kontakt

1. Klick auf Kontakt bei (x, y) im Grid
2. Klick auf Message-Box (ca. 511, 789)
3. `write_clipboard` mit Nachricht
4. `Ctrl+V` (einfügen)
5. `Return` (senden)
6. Browser-Zurück (back-Button ca. 27, 58) oder Alt+Left
7. Klick auf Suchleiste (511, 164) um Grid-View wiederherzustellen

---

## Bekannte Bugs & Fixes

| Problem | Fix |
|---|---|
| chats.json nicht reset zwischen Runs | Dashboard setzt chats.json + confirm.json am Start zurück |
| Grid reordert nach jedem Send | Strategie: immer Position N+1 klicken nach N sends |
| Sunbrowser nicht zugänglich | Computer-use `request_access` für "Sunbrowser" anfordern |
| Chrome Tier "read" | Nie Chrome direkt steuern – nur Sunbrowser |
| server.py neu starten vergessen | Server läuft nur wenn user ihn manuell gestartet hat – immer prüfen |
| "File has not been read yet" | Write-Tool braucht immer vorheriges Read der Datei |

---

## Accounts

| user_id | Name | Beschreibung |
|---|---|---|
| `k1atoh5f` | jeff_Kaplan_ | Alter Account (viele Kontakte schon angeschrieben) |
| `k1bhvfaa` | AVAILABLE | Aktuell verwendeter Account |

---

## Aktueller Stand (Stand: 05.05.2026)

- 50 Kontakte für AVAILABLE-Account (k1bhvfaa) in chats.json
- Zuletzt gesendete Nachricht: `"Hey RtxRt? \nhttps://x.com/groverzachary_/status/2040470832141697481?s=46&t=UkRaiwfFQ-SU5lywqFftqQ"`
- Versand lief – ca. 23/50 gesendet beim letzten Kontextende
- contacts.json für k1bhvfaa muss nach Abschluss befüllt werden

---

## Wie eine neue Session starten

1. Server läuft? → `python server.py` in "Monthly revenue" Ordner ausführen  
2. Dashboard öffnen: `Monthly revenue/xdashboard.html` im Chrome öffnen  
3. Falls Versand schon lief und unterbrochen: status.json + contacts.json prüfen  
4. AdsPower läuft? → `http://127.0.0.1:50325` sollte erreichbar sein  
5. Sunbrowser in Taskleiste = AdsPower hat Browser-Instanz offen  

---

## Wenn Claude weitermacht (Senden läuft)

1. Screenshot machen → prüfen ob Sunbrowser mit X.com Grid offen
2. Aus status.json und contacts.json ableiten wie viele schon gesendet
3. Grid-Formel nutzen: N bereits gesendet → nächster Kontakt bei Position N+1
4. Senden, bis alle Kontakte aus confirm.json abgearbeitet
5. contacts.json updaten mit last_sent Timestamps
6. status.json auf "done" setzen

---

## Performance-Patterns (für Claude)

### Grid/Chat-Liste scannen — NIE Einzel-Scrolls

**Falsch (langsam):**
```
scroll(3 ticks) → screenshot → scroll(3 ticks) → screenshot → ...
```
Das verbraucht ~30s für 30 Kontakte (5+ Round-Trips à ~5s).

**Richtig (Batch-Pattern):**
```
computer_batch([
  {scroll, 7}, {screenshot},
  {scroll, 7}, {screenshot},
  {scroll, 7}, {screenshot}
])
```
3-4 Screenshots in 1 Tool-Call = ~10-15s. Größere Scroll-Ticks (7-8 statt 3) reduzieren die Anzahl der nötigen Snapshots, weil ein Viewport ~8 Kontakte zeigt.

### Send-Loop — alles am Stück, Screenshot nur am Ende

Pro Kontakt-Send (Suche → Klick → Paste → Senden) gehört in EINEN `computer_batch`. Verifikation per Screenshot reicht **am Ende des gesamten Loops**, nicht nach jedem einzelnen Send. Spart pro Send 1-2s Overhead × N Kontakte.

### Search-statt-Scroll für gezielte Aktionen

Wenn ein konkreter Kontakt anzusprechen ist: X.com-interne Suche (Klick auf Suchleiste, tippen, erstes Result klicken) ist deterministisch und reordering-unabhängig. Kein Scroll-Risiko.

### Read-only Konversationen

Manche X-Konversationen sind im "read-only mode" — sichtbar an dem Hinweis-Text unten statt der Message-Box. Diese Kontakte:
- NICHT in `contacts.json` archivieren (sonst werden sie 24h fälschlich blockiert)
- Idealerweise in einer separaten Liste markieren, damit sie in Zukunft direkt übersprungen werden (TODO im Dashboard)
