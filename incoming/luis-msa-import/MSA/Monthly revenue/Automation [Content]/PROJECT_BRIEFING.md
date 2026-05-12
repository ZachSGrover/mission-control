# Content (Models Dashboard) — Projekt-Briefing

> Lies diese Datei beim Start einer neuen Session, dann bist du sofort im Bild.
> Letzte Aktualisierung: 2026-05-07 (Recovery nach Cowork-Reset)

---

## Wer ist der User?

Zach betreibt eine MSA (Model-Management-Agentur). In diesem Projekt geht es um das **Content-Strategy-Tooling** für die einzelnen Models — also pro Model:

1. Stammdaten halten (Niche, Accounts auf X/IG/OF/TT, Status)
2. Detail-Profile pflegen (Follower-Zahl, Caption-Style, Top-Posts, Caption-Patterns)
3. Per Klick eine **wöchentliche Content-Strategie** generieren lassen — mittels Claude API (Haiku 4.5)

Aktuelle Models in `models.json`:
- **Zachary Grover** (`zach-grover`) — Fitness-Model, Findom, Teaser, No-Nude
- **Miachel Mains** (`movlmixkze6gb4liqq`) — Fitness Model

Detail-Profil bisher nur für Zach Grover (`profiles/zach-grover.json`).

---

## Architektur

```
[models-dashboard.html]  ←→  [server.py :8765]  ←→  [Anthropic API]
   Liste aller Models       /models, /analyze       Claude Haiku 4.5
                                                      generiert Strategie
   pro Model:
     ↳ Profil aus profiles/{id}.json
     ↳ "Analyze" Button → POST /analyze → KI-Output rendert
```

| Komponente | Zweck |
|---|---|
| `models-dashboard.html` | Frontend. Lädt Modelle von `/models`, zeigt Detail-Karten. |
| `models.json` | Stammdaten aller Models (Liste). |
| `profiles/{id}.json` | Detail-Profil pro Model (Captions, Patterns, Top-Posts, etc). |
| `../server.py` | Servt `/models-dashboard`, `/models`, `/analyze` (POST). |

Das Endpoint `/analyze` in `server.py` ruft Claude Haiku 4.5 auf mit dem Prompt aus `claude-cowork-automation-bot-spec.md` Abschnitt 5 (Inputs: name, alias, niche, platforms, notes → Output: strukturierter Markdown mit Niche/Audience, Content Pillars, 7 Feed Ideas, 3 Hooks, 3 Engagement-Bait, 3 Reels, 2 Promo, Weekly Schedule, Optimization Advice).

---

## models.json — Schema

```json
{
  "id": "...",                  // unique
  "name": "Vollständiger Name",
  "alias": "Künstlername",
  "niche": "Fitness Model, Findom, ...",
  "status": "active" | "paused" | ...,
  "notes": "",
  "accounts": {
    "x":  ["handle1", "handle2"],
    "ig": [...],
    "of": [...],
    "tt": [...]
  },
  "profileFile": "datei.json",  // optional, zeigt auf profiles/
  "createdAt": <unix-ms>,
  "updatedAt": <unix-ms>
}
```

## profiles/{id}.json — Schema (am Beispiel Zach Grover)

```json
{
  "id": "zach-grover",
  "name": "...", "alias": "...", "niche": "...", "status": "...",
  "lastUpdated": "2026-05-07",
  "accounts": { ... wie in models.json ... },
  "instagram": {
    "handle", "followers", "followerDisplay", "contentThemes",
    "captionStyle", "postingFrequency", "notes"
  },
  "onlyfans": {
    "handle", "totalPosts", "totalMedia", "subscriptionPrice",
    "activeSpenders", "topSpender",
    "contentType", "captionVoice",
    "captionExamples": [{ "date", "caption", "likes" }],
    "captionPatterns": [],
    "topPerformingPosts": [{ "caption", "likes" }],
    "scrapedAt", "scrapedBy"
  }
}
```

Das Profil ist die Faktenbasis, mit der die Content-Strategie generiert wird. Je reicher das Profil, desto schärfer der Output.

---

## Wie startet man das Projekt

Server läuft im Hauptordner — der hostet auch dieses Dashboard:

```
cd "Monthly revenue"
python server.py
```

Browser: `http://localhost:8765/models-dashboard`

Anthropic-API-Key muss als ENV-Variable `ANTHROPIC_API_KEY` gesetzt sein, sonst schlägt `/analyze` fehl.

---

## Aktueller Stand

- 2 Models in `models.json` angelegt (Zach Grover, Mike Mains)
- 1 vollständiges Detail-Profil (Zach Grover) — gescraped am 2026-05-07 von Claude (OnlyMonster Desktop)
- `/analyze` Endpoint funktioniert, nutzt Claude Haiku 4.5 (Modell-String `claude-haiku-4-5-20251001`), max_tokens 1800

---

## Offene Punkte / TODOs

- Profil für Mike Mains scrapen + `profiles/mike-mains.json` anlegen
- Mehr Models einpflegen
- Eventuell: History der generierten Strategien speichern (aktuell flüchtig, jeder /analyze-Call regeneriert)
- UI für Profile-Edit (aktuell JSON manuell editieren)

---

## Was NICHT in diesen Chat gehört

- DM-Bot, AdsPower, Playwright → **Automation [RTxRT]** Chat
- Notion-Sync, Revenue-Dashboard → **Model Revenue** Chat

Der Server hostet zwar alle drei Dashboards, aber an Server-Code arbeite hier nur, wenn es um `/models`, `/analyze`, `/models-dashboard` Routes geht — alles andere läuft im Revenue-Chat.
