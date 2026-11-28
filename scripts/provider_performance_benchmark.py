"""Repeatable offline benchmark for acquisition, normalization and enrichment stages."""

from __future__ import annotations

import json
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources.jobspy_source import normalize_jobspy_row
from sources.provider_runtime import GeocodeRuntime


def synthetic_rows(count: int) -> list[dict[str, str]]:
    return [
        {
            "id": f"bench-{index}",
            "title": "Software Developer",
            "company": f"Employer {index % 25}",
            "location": "Toronto, ON",
            "job_url": f"https://example.test/jobs/{index}",
            "description": "Requirements: 2 years of professional software experience. Python, SQL. Benefits include PTO.",
        }
        for index in range(count)
    ]


def benchmark(count: int) -> dict[str, float | int]:
    rows = synthetic_rows(count)
    acquisition_start = time.perf_counter()
    acquired = list(rows)
    acquisition_ms = (time.perf_counter() - acquisition_start) * 1000

    normalization_start = time.perf_counter()
    normalized = [normalize_jobspy_row(row, fallback_source="linkedin") for row in acquired]
    normalization_ms = (time.perf_counter() - normalization_start) * 1000

    runtime = GeocodeRuntime(provider_name="benchmark")
    enrichment_start = time.perf_counter()
    runtime.resolve_many(
        [{"query": row["location"], "lookup_type": "job"} for row in normalized],
        provider=lambda query, **_kwargs: {"ok": True, "status": "synthetic", "normalized_query": query},
        context_key="profile-a",
    )
    enrichment_ms = (time.perf_counter() - enrichment_start) * 1000
    return {
        "postings": count,
        "acquisition_ms": round(acquisition_ms, 3),
        "normalization_ms": round(normalization_ms, 3),
        "geocoding_enrichment_ms": round(enrichment_ms, 3),
        "total_ms": round(acquisition_ms + normalization_ms + enrichment_ms, 3),
        "unique_geocode_calls": runtime.calls,
    }


def main() -> None:
    print(json.dumps({str(size): benchmark(size) for size in (50, 200, 1000)}, indent=2))


if __name__ == "__main__":
    main()
