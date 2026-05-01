"""Service modules that drive OnlyMonster ingestion (the first OFI data source).

These services are OnlyMonster-specific by design: future data sources will
have their own subpackages (e.g. `app.services.infloww.sync`) but write into
the same `of_intelligence_*` tables, keeping the product-level reporting
layer source-agnostic.
"""
