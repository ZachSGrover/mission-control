"""Source-agnostic services for the OnlyFans Intelligence product area.

These modules operate on the `of_intelligence_*` tables and do not care which
upstream data source produced the rows.  Source-specific ingestion lives
under `app.services.onlymonster.*`.
"""
