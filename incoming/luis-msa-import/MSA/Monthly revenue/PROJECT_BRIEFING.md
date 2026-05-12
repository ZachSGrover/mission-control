# Model Revenue — Projekt-Briefing

> Lies diese Datei beim Start einer neuen Session, dann bist du sofort im Bild.
> Letzte Aktualisierung: 2026-05-07 (Recovery nach Cowork-Reset)

---

## Wer ist der User?

Zach betreibt eine MSA (Model-Management-Agentur). Er verwaltet OnlyFans/X-Accounts mehrerer Models. In diesem Projekt geht es um das **Revenue-Tracking** dieser Agentur — also wie viel die Models verdienen, was an Payouts fließt, was die Agentur bekommt.

Die Buchhaltung liegt in **Notion** in zwei Datenbanken: `MODEL REVENUE` und `PAYMENTS`. Dieses Projekt ist die lokale Visualisierungs-Schicht darüber.

---

## Architektur

```
[Notion API]
   ↓ notion_sync.py (POST /sync)
[data.json]
   ↓ server.py /data
[dashboard.html]  ← Browser
```

| Komponente | Zweck |
|---|---|
| `server.py` | HTTP-Server auf Port 8765 (Python stdlib, keine Dependencies). Serviert dashboard.html + JSON. Auch Host für die anderen zwei Dashboards (xdashboard, models-dashboard). |
| `notion_sync.py` | Holt MODEL REVENUE + PAYMENTS Pages aus Notion API, transformiert sie zu `ofRows` und `pmtRows`, schreibt `data.json`. |
| `dashboard.html` | Frontend. Zeigt Revenue, Payouts, Auswertungen. Lädt Daten von `/data`. |
| `data.json` | Cache der Notion-Daten. Wird von `notion_sync` überschrieben bei Sync. |
| `.env` | Enthält `NOTION_TOKEN` + DB-IDs. **Aus `.env.example` neu erstellen, dann Token einfügen.** |

---

## Notion-Schema (was wird ausgelesen)

### MODEL REVENUE DB (`2ecc4ce4962e8071b5e6f463df259ad1`)
Felder die `transform_revenue()` zieht:
- `Payout Date` (date)
- `Gross Revenue` (number)
- `Revenue Payout` (string)
- `Invoice` (string)
- `Notes` (string)
- `Total Payout` (string, mit oder ohne Trailing-Space — beides wird probiert)
- `Paid` (Status/Select; "Paid"/"Yes"/✓ → wird zu `__YES__`)
- `Model %` (number)
- `Name` (title)

### PAYMENTS DB (`2edc4ce4962e80a6b09ad0ed9ab3ba40`)
- `Date` (date)
- `Amount` (number)
- `Creator`
- `Payment Source`
- `Chatter`
- `Attachments`
- `Name` (title)

`prop_value()` ist generisch — wenn du Properties hinzufügst, am besten Standard-Notion-Typen (title/rich_text/number/select/status/multi_select/date/checkbox/url/formula/rollup) nutzen, dann werden sie automatisch geparst.

---

## Server-Endpoints (relevant für Model Revenue)

| Endpoint | Methode | Zweck |
|---|---|---|
| `/` oder `/dashboard.html` | GET | Liefert dashboard.html |
| `/data` | GET | Liefert `data.json` |
| `/sync` | GET/POST | Triggert `notion_sync.run()` und schreibt `data.json` neu |

(Der Server hat noch viele Endpoints für RTxRT und Content — siehe deren Briefings.)

---

## Wie startet man das Projekt

```
cd "Monthly revenue"
python server.py
```

Dann im Browser: `http://localhost:8765`

Falls Notion-Sync nötig: `.env` aus `.env.example` erstellen, NOTION_TOKEN eintragen (siehe `.env.example` für die Anleitung — Integration in Notion erstellen, an beide DBs connecten), dann im Dashboard auf den Sync-Button klicken (oder `curl http://localhost:8765/sync`).

---

## Bekannte Punkte / TODOs

- `data.json` ist ziemlich groß (~50k Tokens). Bei Sync wird die ganze Datei überschrieben — Performance ist OK aber bei sehr vielen Notion-Pages perspektivisch optimierbar (Pagination ist drin).
- `custRows` ist in `data.json` immer leer (`[]`). Falls Customer-Tracking dazukommen soll: dritte Notion-DB anbinden + neue `transform_customers()`-Funktion bauen.
- API-Key der AdsPower in `server.py` ist hardcoded — nicht ins Git.

---

## Was NICHT in diesen Chat gehört

- DM-Bot-Logik (Playwright, AdsPower-Stuff) → das ist der **Automation [RTxRT]** Chat
- Models-Profile + Content-Strategie → das ist der **Content** Chat

Der Server hostet zwar alle drei, aber arbeite nur an den Komponenten dieses Projekts: `server.py` (Revenue-relevante Endpoints), `notion_sync.py`, `dashboard.html`, `data.json`, `.env`.
