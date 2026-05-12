#!/usr/bin/env python3
"""
notion_sync.py — Holt Live-Daten aus Notion und schreibt data.json.

Wird vom server.py aufgerufen wenn /sync getriggert wird.
Liest Token aus .env (NOTION_TOKEN), DB-IDs ebenfalls.

Nutzt nur Standardbibliothek — keine pip-Installs nötig.
"""
import os, json, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE, "data.json")
ENV_PATH = os.path.join(BASE, ".env")

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def load_env():
    """Liest .env-Datei (Schlüssel=Wert pro Zeile)."""
    cfg = {}
    if not os.path.exists(ENV_PATH):
        raise RuntimeError(
            ".env-Datei nicht gefunden. "
            "Kopiere .env.example zu .env und trage NOTION_TOKEN ein."
        )
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    if not cfg.get("NOTION_TOKEN") or "xxxx" in cfg.get("NOTION_TOKEN", ""):
        raise RuntimeError("NOTION_TOKEN in .env fehlt oder ist Platzhalter.")
    return cfg


def notion_query(database_id: str, token: str):
    """POST gegen /databases/{id}/query — sammelt alle Pages über Pagination."""
    url = f"{NOTION_API}/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    all_results = []
    next_cursor = None
    while True:
        body = {"page_size": 100}
        if next_cursor:
            body["start_cursor"] = next_cursor
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Notion API Fehler {e.code}: {err_body[:300]}")
        all_results.extend(payload.get("results", []))
        if not payload.get("has_more"):
            break
        next_cursor = payload.get("next_cursor")
    return all_results


def prop_value(prop: dict):
    """Extrahiert den 'lesbaren' Wert einer Notion-Property aus der API-Antwort."""
    if not prop:
        return None
    t = prop.get("type")
    v = prop.get(t) if t else None
    if t == "title" or t == "rich_text":
        return "".join(span.get("plain_text", "") for span in (v or []))
    if t == "number":
        return v
    if t == "select":
        return (v or {}).get("name", "") if v else ""
    if t == "status":
        return (v or {}).get("name", "") if v else ""
    if t == "multi_select":
        return ", ".join(o.get("name", "") for o in (v or []))
    if t == "date":
        return v or {}
    if t == "checkbox":
        return bool(v)
    if t == "url":
        return v or ""
    if t == "email":
        return v or ""
    if t == "phone_number":
        return v or ""
    if t == "files":
        names = [f.get("name", "") for f in (v or [])]
        return ", ".join(names)
    if t == "people":
        return ", ".join(p.get("name", "") for p in (v or []) if p.get("name"))
    if t == "relation":
        return ", ".join(r.get("id", "") for r in (v or []))
    if t == "formula":
        ft = v.get("type") if v else None
        return v.get(ft) if ft else None
    if t == "rollup":
        rt = v.get("type") if v else None
        if rt == "array":
            return ", ".join(str(prop_value({"type": x.get("type"), x.get("type"): x.get(x.get("type"))})) for x in v.get("array", []))
        return v.get(rt) if rt else None
    return v


def transform_revenue(pages: list):
    """MODEL REVENUE-Pages → ofRows-Format für data.json."""
    rows = []
    for p in pages:
        props = p.get("properties", {})
        date_prop = props.get("Payout Date", {}).get("date") or {}
        row = {
            "date:Payout Date:start": date_prop.get("start"),
            "date:Payout Date:is_datetime": 1 if (date_prop.get("start") and "T" in (date_prop.get("start") or "")) else 0,
            "Gross Revenue": prop_value(props.get("Gross Revenue")) or 0,
            "Revenue Payout": prop_value(props.get("Revenue Payout")) or "",
            "Invoice": prop_value(props.get("Invoice")) or "",
            "Notes": prop_value(props.get("Notes")) or "",
            "Total Payout ": prop_value(props.get("Total Payout")) or prop_value(props.get("Total Payout ")) or "",
            "Paid": ("__YES__" if prop_value(props.get("Paid")) in ("Paid", "Yes", "yes", True, "✓") else (prop_value(props.get("Paid")) or "")),
            "Model %": prop_value(props.get("Model %")) or 0,
            "Name": prop_value(props.get("Name")) or "",
            "url": p.get("url", ""),
        }
        rows.append(row)
    return rows


def transform_payments(pages: list):
    """PAYMENTS-Pages → pmtRows-Format für data.json."""
    rows = []
    for p in pages:
        props = p.get("properties", {})
        date_prop = props.get("Date", {}).get("date") or {}
        row = {
            "Attachments": prop_value(props.get("Attachments")) or "",
            "Creator": prop_value(props.get("Creator")) or "",
            "Amount": prop_value(props.get("Amount")) or 0,
            "date:Date:start": date_prop.get("start"),
            "date:Date:is_datetime": 1 if (date_prop.get("start") and "T" in (date_prop.get("start") or "")) else 0,
            "Payment Source": prop_value(props.get("Payment Source")) or "",
            "Chatter": prop_value(props.get("Chatter")) or "",
            "Name": prop_value(props.get("Name")) or "",
            "url": p.get("url", ""),
        }
        rows.append(row)
    return rows


def run():
    """Führt den vollständigen Sync aus, schreibt data.json. Returns dict mit Counts."""
    cfg = load_env()
    token = cfg["NOTION_TOKEN"]
    db_rev = cfg.get("NOTION_DB_REVENUE", "2ecc4ce4962e8071b5e6f463df259ad1")
    db_pmt = cfg.get("NOTION_DB_PAYMENTS", "2edc4ce4962e80a6b09ad0ed9ab3ba40")

    rev_pages = notion_query(db_rev, token)
    pmt_pages = notion_query(db_pmt, token)

    of_rows = transform_revenue(rev_pages)
    pmt_rows = transform_payments(pmt_pages)

    data = {
        "ofRows": of_rows,
        "pmtRows": pmt_rows,
        "custRows": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "ofRows": len(of_rows),
        "pmtRows": len(pmt_rows),
        "timestamp": data["timestamp"],
    }


if __name__ == "__main__":
    try:
        result = run()
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
