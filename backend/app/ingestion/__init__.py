"""Ingestion: adapters, mapping profiles, and the canonical staging shape.

Every adapter's only job is to emit `RawRow`. Validation, calculation,
aggregation and audit are written once against `RawRow` and never learn where
the data came from -- which is what lets the Parquet and API feeds drop in
later without touching the pipeline.
"""
