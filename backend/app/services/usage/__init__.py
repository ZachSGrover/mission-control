"""Usage / spend tracking service package.

Public surface:

* ``record_usage_event(...)`` — log one internal AI call (Phase 1 foundation;
  no agents wired yet).
* ``run_collectors(...)`` — refresh provider snapshots from external usage APIs.
* ``estimate_cost(...)`` — best-effort $ from token counts and a model name.

Per-provider collectors live in sibling modules and intentionally return a
``not_configured`` status when their admin credentials are absent — they must
never make billable inference calls.
"""

from __future__ import annotations

from app.services.usage.logger import record_usage_event
from app.services.usage.pricing import estimate_cost

__all__ = ["estimate_cost", "record_usage_event", "run_collectors"]


def run_collectors(*args, **kwargs):
    # Lazy import to avoid pulling collector deps at package import time.
    from app.services.usage.collector import run_collectors as _impl

    return _impl(*args, **kwargs)
