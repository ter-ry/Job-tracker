"""Offline Ontario licensed child-care facility matching.

This module deliberately produces candidates, never confirmed job workplaces.
It accepts the Ontario workbook and a small cohort export supplied by the
owner; neither is persisted by the application.
"""

from __future__ import annotations

import io
import json
import re
import urllib.error
import urllib.request
from urllib.parse import quote_plus
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd


FACILITY_COLUMNS = {
    "Report Snapshot Date": "snapshot_date",
    "Licensee Name": "licensee_name",
    "Child Care Site Name": "site_name",
    "Licence Number": "licence_number",
    "Licence Status": "licence_status",
    "Street Number": "street_number",
    "Street Name": "street_name",
    "Street Type": "street_type",
    "City": "municipality",
    "Province": "province",
    "Postal Code": "postal_code",
}

COHORT_COLUMNS = {"job_id", "employer", "job_title", "advertised_location"}
GENERIC_NAME_WORDS = {
    "child", "children", "care", "centre", "center", "daycare", "day", "school",
    "preschool", "preschool", "program", "services", "service", "the", "inc", "ltd",
    "limited", "ontario", "community", "licensed", "facility", "facilities", "midtown",
    "east", "scarborough", "city", "place", "music", "corp", "corporation",
    "infant", "toddler", "development", "learning", "family", "and", "childcare",
}
ONTARIO_REGISTRY_URL = "https://data.ontario.ca/dataset/licensed-child-care-facilities-in-ontario/resource/876d6b6a-784f-4d79-85f1-f0433e7e5e58"
_GOOGLE_PLACES_CACHE: dict[str, list[dict[str, Any]]] = {}


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def normalize_facility_name(value: Any) -> str:
    value = unicodedata.normalize("NFKD", _text(value)).encode("ascii", "ignore").decode().lower()
    value = value.replace("&", " and ")
    value = re.sub(r"\bbgc\b", "boys girls club", value)
    value = re.sub(r"['’]s\b", "", value)
    value = re.sub(r"\b(?:incorporated|corporation|corporate|inc|ltd|limited)\b", " ", value)
    tokens = re.findall(r"[a-z0-9]+", value)
    return " ".join(tokens)


def _meaningful_tokens(value: Any) -> set[str]:
    return {token for token in normalize_facility_name(value).split() if len(token) > 2 and token not in GENERIC_NAME_WORDS}


def _municipality(value: Any) -> str:
    value = normalize_facility_name(value)
    # The cohort uses strings such as Toronto, ON, Canada. Keep the first
    # geographic component; facility rows contain a dedicated City column.
    known = ("east york", "north york", "scarborough", "thornhill", "mississauga", "vaughan", "toronto", "brampton", "markham")
    for candidate in known:
        if re.search(rf"\b{re.escape(candidate)}\b", value):
            value = candidate
            break
    else:
        value = re.split(r",|\s+(?:canada|ontario|on)\b", value, maxsplit=1)[0].strip()
    return {"east york": "toronto", "scarborough": "toronto", "north york": "toronto", "york": "toronto"}.get(value, value)


def _address(row: dict[str, Any]) -> str:
    parts = [row.get("street_number", ""), row.get("street_name", ""), row.get("street_type", "")]
    line = " ".join(part for part in (_text(item) for item in parts) if part)
    city = _text(row.get("municipality"))
    province = _text(row.get("province"))
    postal = _text(row.get("postal_code"))
    suffix = ", ".join(part for part in (city, province, postal) if part)
    return ", ".join(part for part in (line, suffix) if part)


def load_facilities(source: str | Path | bytes | BinaryIO) -> list[dict[str, Any]]:
    if isinstance(source, (str, Path)):
        frame = pd.read_excel(source, sheet_name=0, dtype=str)
    else:
        raw = source if isinstance(source, bytes) else source.read()
        frame = pd.read_excel(io.BytesIO(raw), sheet_name=0, dtype=str)
    missing = sorted(set(FACILITY_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"Ontario facility workbook is missing columns: {', '.join(missing)}")
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        row = {target: _text(record.get(source_name)) for source_name, target in FACILITY_COLUMNS.items()}
        row["address"] = _address(row)
        row["name_normalized"] = normalize_facility_name(row["site_name"])
        row["licensee_normalized"] = normalize_facility_name(row["licensee_name"])
        if row["licence_status"].lower() == "active":
            rows.append(row)
    return rows


def load_cohort(source: str | Path | bytes | BinaryIO) -> list[dict[str, Any]]:
    if isinstance(source, (str, Path)):
        frame = pd.read_csv(source, dtype=str)
    else:
        raw = source if isinstance(source, bytes) else source.read()
        frame = pd.read_csv(io.BytesIO(raw), dtype=str)
    missing = sorted(COHORT_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"ECE cohort is missing columns: {', '.join(missing)}")
    return [{key: _text(record.get(key)) for key in frame.columns} for record in frame.to_dict(orient="records")]


def _candidate_score(job: dict[str, Any], facility: dict[str, Any]) -> tuple[float, list[str]]:
    employer_normalized = normalize_facility_name(job.get("employer"))
    site_normalized = facility.get("name_normalized", "")
    licensee_normalized = facility.get("licensee_normalized", "")
    employer_tokens = _meaningful_tokens(job.get("employer"))
    site_tokens = _meaningful_tokens(facility.get("site_name"))
    licensee_tokens = _meaningful_tokens(facility.get("licensee_name"))
    if not employer_tokens:
        operator_match = SequenceMatcher(None, employer_normalized, licensee_normalized).ratio() >= 0.9
        if not operator_match:
            return 0.0, ["Employer name contains no distinctive matching terms."]
    municipality = _municipality(job.get("advertised_location"))
    facility_city = _municipality(facility.get("municipality"))
    reasons: list[str] = []
    city_match = bool(municipality and facility_city and (municipality == facility_city or municipality in facility_city or facility_city in municipality))
    if city_match:
        reasons.append(f"municipality matches {facility.get('municipality')}")
    else:
        return 0.0, [f"municipality does not match advertised {municipality or 'location'}"]
    site_overlap = len(employer_tokens & site_tokens) / max(1, len(employer_tokens))
    licensee_overlap = len(employer_tokens & licensee_tokens) / max(1, len(employer_tokens))
    site_ratio = SequenceMatcher(None, employer_normalized, site_normalized).ratio()
    licensee_ratio = SequenceMatcher(None, employer_normalized, licensee_normalized).ratio()
    best_ratio = max(site_ratio, licensee_ratio)
    # A high employer/licensee similarity is sufficient for an operator with
    # multiple branches, even when punctuation or a minor spelling error means
    # token overlap is zero (for example, Scarborugh vs Scarborough).
    overlap = max(site_overlap, licensee_overlap)
    required_overlap = 0.75 if len(employer_tokens) > 1 else 0.5
    if overlap < required_overlap:
        # An operator such as Family Day Care Services can be recognized by a
        # nearly exact licensee string even though generic-word filtering leaves
        # no meaningful tokens. A named centre such as Roden must still share a
        # distinctive token; phrase similarity alone is not enough.
        if not employer_tokens and best_ratio >= 0.9:
            score = 0.9
        else:
            return 0.0, ["Employer and registered name share insufficient distinctive terms."]
    else:
        score = overlap * 0.65 + best_ratio * 0.35
    if site_overlap:
        reasons.append(f"employer/site name overlap: {sorted(employer_tokens & site_tokens)}")
    if licensee_overlap:
        reasons.append(f"employer/licensee name overlap: {sorted(employer_tokens & licensee_tokens)}")
    return score, reasons


def match_facilities(job: dict[str, Any], facilities: list[dict[str, Any]]) -> dict[str, Any]:
    scored: list[tuple[float, list[str], dict[str, Any]]] = []
    for facility in facilities:
        score, reasons = _candidate_score(job, facility)
        if score >= 0.42:
            scored.append((score, reasons, facility))
    scored.sort(key=lambda item: (-item[0], item[2].get("site_name", "")))
    distinct = []
    seen = set()
    for score, reasons, facility in scored:
        key = (facility.get("licence_number"), facility.get("address"))
        if key in seen:
            continue
        seen.add(key)
        distinct.append({
            "registered_facility_name": facility.get("site_name", ""),
            "licensee_name": facility.get("licensee_name", ""),
            "licence_number": facility.get("licence_number", ""),
            "licence_status": facility.get("licence_status", ""),
            "address": facility.get("address", ""),
            "municipality": facility.get("municipality", ""),
            "postal_code": facility.get("postal_code", ""),
            "registry_snapshot_date": facility.get("snapshot_date", ""),
            "source": "Ontario licensed child care facilities registry",
            "source_url": ONTARIO_REGISTRY_URL,
            "maps_name_search_url": "https://www.google.com/maps/search/" + quote_plus(f"{facility.get('site_name', '')}, {facility.get('municipality', '')}, Ontario"),
            "score": round(score, 3),
            "matching_evidence": reasons,
            "status": "Possible licensed facility — verify job workplace.",
        })
    existing_address = normalize_facility_name(job.get("workplace_address"))
    existing_postal = normalize_facility_name(job.get("workplace_postal_code"))
    if existing_address or existing_postal:
        precise = [
            item for item in distinct
            if (existing_postal and existing_postal in normalize_facility_name(item.get("postal_code")))
            or (existing_address and existing_address in normalize_facility_name(item.get("address")))
        ]
        if precise:
            distinct = precise
    existing = _text(job.get("workplace_address")) or _text(job.get("workplace_postal_code"))
    if existing and distinct:
        category = "existing_precise_registry_supported"
    elif not distinct:
        category = "no_defensible_registry_match"
    elif len(distinct) > 1:
        category = "multiple_licensed_facilities"
    elif distinct[0]["score"] >= 0.78 and SequenceMatcher(
        None,
        normalize_facility_name(job.get("employer")),
        normalize_facility_name(distinct[0].get("registered_facility_name")),
    ).ratio() >= 0.8:
        category = "strong_single_centre_match"
    else:
        category = "similar_name_requires_verification"
    return {
        "job_id": _text(job.get("job_id")),
        "employer": _text(job.get("employer")),
        "job_title": _text(job.get("job_title")),
        "advertised_location": _text(job.get("advertised_location")),
        "category": category,
        "candidates": distinct,
        "candidate_count": len(distinct),
        "confidence": "strong" if category in {"strong_single_centre_match", "existing_precise_registry_supported"} else "review" if distinct else "none",
        "assigned_workplace_confirmed": False,
    }


def match_cohort(cohort: list[dict[str, Any]], facilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [match_facilities(job, facilities) for job in cohort]


def google_places_text_search(employer: str, municipality: str, api_key: str, *, timeout: float = 5.0) -> list[dict[str, Any]]:
    """Optional, bounded Google Places Text Search; never confirms a worksite."""
    key = f"{normalize_facility_name(employer)}|{normalize_facility_name(municipality)}"
    if key in _GOOGLE_PLACES_CACHE:
        return _GOOGLE_PLACES_CACHE[key]
    if not api_key:
        return []
    payload = json.dumps({"textQuery": f"{employer}, {municipality}, Ontario", "pageSize": 5}).encode()
    request = urllib.request.Request(
        "https://places.googleapis.com/v1/places:searchText",
        data=payload,
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": api_key, "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.id"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(100_000).decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        data = {}
    results = []
    for place in data.get("places", [])[:5]:
        display_name = place.get("displayName") or {}
        results.append({
            "business_name": _text(display_name.get("text")),
            "address": _text(place.get("formattedAddress")),
            "place_id": _text(place.get("id")),
            "source": "Google Places Text Search",
            "status": "Possible business location — verify job workplace.",
            "matching_evidence": [f"Name search for {employer} in {municipality}"],
        })
    _GOOGLE_PLACES_CACHE[key] = results
    return results
