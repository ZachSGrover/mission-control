# Recovery README — drei Chats in einem Cowork-Projekt

> Stand: 2026-05-07. Cowork wurde gelöscht, alle Chats sind weg, der Ordner `Monthly revenue/` ist intakt.
> Setup: **ein Cowork-Projekt** (z.B. "MSA"), **drei Chats darin** — pro Komponente einer.

---

## Was du verloren hast — und was nicht

**Verloren:** Die Konversationsverläufe der drei alten Chats.

**NICHT verloren:**
- Sämtliche Code-Dateien, HTMLs, JSONs, Skripte
- Die Spec für RTxRT (`claude-cowork-automation-bot-spec.md`)
- Das Briefing für RTxRT (`Automation [RTxRT]/BRIEFING.md`)
- `data.json` mit den Notion-Sync-Daten, alle Profile, alle Models

Die Arbeit selbst ist da. Nur die Konversationen sind weg.

---

## Wie das Setup jetzt funktioniert

In Cowork gibt's zwei Ebenen:

| Ebene | Wirkt auf | Datei |
|---|---|---|
| **Project Instructions** | Alle Chats im Projekt | `PROJECT_INSTRUCTIONS.txt` (Hauptordner) |
| **Chat-Starter** (erste Nachricht) | Nur den einen Chat | `COWORK_INSTRUCTIONS.txt` (pro Komponente) |

Die Project Instructions geben Claude den Gesamtüberblick (welche drei Komponenten existieren, wer der User ist, welche Sicherheitsregeln gelten). Der Chat-Starter sagt dann: *"In diesem Chat arbeitest du an Komponente X — fass nichts anderes an."*

---

## Setup-Schritte (einmalig)

1. **Cowork öffnen** → "+ New Project"
2. **Projekt-Name:** z.B. `MSA` oder `Monthly revenue`
3. **Ordner auswählen:** `…/MSA/Monthly revenue/` (der Hauptordner — alle drei Komponenten leben darin)
4. **Project Instructions setzen:** Inhalt von `PROJECT_INSTRUCTIONS.txt` (im Hauptordner) kopieren und ins Project-Instructions-Feld einfügen

## Pro Chat (3× wiederholen)

5. **Neuen Chat starten** im Projekt
6. **Chat-Name** (falls Cowork Chat-Namen unterstützt): `Automation [RTxRT]`, `Model Revenue`, `Content`
7. **Erste Nachricht:** Inhalt der jeweiligen `COWORK_INSTRUCTIONS.txt` kopieren und absenden:

| Chat | Datei |
|---|---|
| Automation [RTxRT] | `Automation [RTxRT]/COWORK_INSTRUCTIONS.txt` |
| Model Revenue | `COWORK_INSTRUCTIONS.txt` (Hauptordner) |
| Content | `Automation [Content]/COWORK_INSTRUCTIONS.txt` |

Dadurch lädt der jeweilige Chat das passende Briefing und weiß, an welchen Dateien er arbeiten darf.

---

## Die drei Komponenten im Überblick

| Chat | Ordner | Zweck | Briefing |
|---|---|---|---|
| **Automation [RTxRT]** | `Automation [RTxRT]/` | X (Twitter) DM-Bot — sendet RT-for-RT DMs aus AdsPower | `BRIEFING.md` |
| **Model Revenue** | Hauptordner | Notion → data.json → dashboard.html | `PROJECT_BRIEFING.md` |
| **Content** | `Automation [Content]/` | Models-Profile + KI-Content-Strategie pro Model | `PROJECT_BRIEFING.md` |

---

## Server-Setup

`server.py` im Hauptordner serviert ALLE drei Dashboards auf Port 8765:

```
http://localhost:8765/                  → Model Revenue
http://localhost:8765/xdashboard        → Automation [RTxRT]
http://localhost:8765/models-dashboard  → Content
```

Starten:
```
cd "Monthly revenue"
python server.py
```

Der Server wird typischerweise im Model-Revenue-Chat verwaltet (weil er dort liegt), aber alle drei Chats nutzen ihn.

---

## Sensible Daten

- AdsPower-API-Key in `server.py` hardcoded (~Zeile 120)
- `NOTION_TOKEN` muss in `.env` (aus `.env.example` erstellen)
- `ANTHROPIC_API_KEY` als ENV-Variable für /analyze

Nichts davon ins Git committen, nichts im Chat-Output ausgeben.
