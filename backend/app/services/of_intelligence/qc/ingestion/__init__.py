"""Daily QC ingestion layer — read-only, privacy-safe input contract."""

from app.services.of_intelligence.qc.ingestion.base import (
    AccountMetrics,
    IngestionResult,
    SourceConfidence,
    SourceMode,
)
from app.services.of_intelligence.qc.ingestion.factory import ingest_for_status
from app.services.of_intelligence.qc.ingestion.local_ofi import ingest_local_ofi
from app.services.of_intelligence.qc.ingestion.synthetic import ingest_synthetic

__all__ = [
    "AccountMetrics",
    "IngestionResult",
    "SourceConfidence",
    "SourceMode",
    "ingest_for_status",
    "ingest_local_ofi",
    "ingest_synthetic",
]
