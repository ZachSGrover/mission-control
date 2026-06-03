"""Manual / sanitized Daily-QC import — offline dry run.

Loads a sanitized CSV or JSON fixture into a throwaway in-memory SQLite DB,
runs the existing Daily-QC detectors over it, and prints the resulting
privacy-safe report.  NO network.  NO real database.  NO live connectors.

Usage:
  cd backend
  uv run python scripts/qc_manual_import_dry_run.py            # bundled JSON sample
  uv run python scripts/qc_manual_import_dry_run.py --csv      # bundled CSV sample
  uv run python scripts/qc_manual_import_dry_run.py path/to/your_sanitized.json
  uv run python scripts/qc_manual_import_dry_run.py path/to/your_sanitized.csv

The report is printed as JSON.  It contains aliases, counts, generic signal
phrases, and short capped excerpts only — never a raw message body or a real
identifier.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from app.services.of_intelligence.qc.manual_import import (  # noqa: E402
    ManualImportBatch,
    parse_csv,
    parse_json,
    run_manual_import,
)

FIXTURES = Path(__file__).resolve().parents[1] / "app/services/of_intelligence/qc/fixtures"


def _load_batch(arg: str | None) -> ManualImportBatch:
    if arg in (None, "--csv"):
        if arg == "--csv":
            return parse_csv((FIXTURES / "manual_sample.csv").read_text())
        return parse_json((FIXTURES / "manual_sample.json").read_text())
    path = Path(arg)
    text = path.read_text()
    if path.suffix.lower() == ".csv":
        return parse_csv(text)
    return parse_json(text)


async def _run(batch: ManualImportBatch) -> dict:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with maker() as session:
            return await run_manual_import(session, batch)
    finally:
        await engine.dispose()


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    batch = _load_batch(arg)
    report = asyncio.run(_run(batch))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
