"""Read-only public employer careers-board discovery.

This module intentionally uses published ATS listing APIs, rather than
scraping private candidate pages or bypassing authentication.
Board slugs below are grounded in employer careers URLs. They are not a
claim that the employers have current openings.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from html.parser import HTMLParser
from typing import Any


# Public employer board identifiers used by the direct-discovery pilot.  A
# board is counted as working only when its feed responds and yields usable
# Canadian/remote postings; failed or empty boards remain visible in the
# diagnostics instead of being presented as coverage.
DEFAULT_BOARDS: tuple[dict[str, str], ...] = (
    {"kind": "lever", "slug": "policyme", "company": "PolicyMe"},
    {"kind": "lever", "slug": "achievers", "company": "Achievers"},
    {"kind": "lever", "slug": "shyftlabs", "company": "ShyftLabs"},
    {"kind": "lever", "slug": "caseware", "company": "Caseware"},
    {"kind": "lever", "slug": "getmaple", "company": "Maple"},
    {"kind": "lever", "slug": "applydigital", "company": "Apply Digital"},
    {"kind": "lever", "slug": "ttecdigital", "company": "TTEC Digital"},
    {"kind": "lever", "slug": "koho", "company": "KOHO Financial"},
    {"kind": "lever", "slug": "humi", "company": "Humi"},
    {"kind": "ashby", "slug": "wealthsimple", "company": "Wealthsimple"},
    {"kind": "ashby", "slug": "clearco", "company": "Clearco"},
    {"kind": "greenhouse", "slug": "shopify", "company": "Shopify"},
    {"kind": "greenhouse", "slug": "hopper", "company": "Hopper"},
    {"kind": "greenhouse", "slug": "ritual", "company": "Ritual"},
    {"kind": "greenhouse", "slug": "ecobee", "company": "ecobee"},
    {"kind": "greenhouse", "slug": "pointclickcare", "company": "PointClickCare"},
    {"kind": "smartrecruiters", "slug": "d2l", "company": "D2L"},
    {"kind": "smartrecruiters", "slug": "thinkific", "company": "Thinkific"},
    {"kind": "smartrecruiters", "slug": "pointclickcare", "company": "PointClickCare"},
    {"kind": "smartrecruiters", "slug": "loblaw", "company": "Loblaw Digital"},
)

MAX_RESPONSE_BYTES = 2_000_000
USER_AGENT = "Job Tracker/0.0.0 (public employer job board reader)"
SMARTRECRUITERS_PAGE_LIMIT = 100
SMARTRECRUITERS_MAX_PAGES = 5
SMARTRECRUITERS_MAX_DETAIL_REQUESTS = 10
SMARTRECRUITERS_DETAIL_TIMEOUT = 3


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def plain(value: Any) -> str:
    value = value if isinstance(value, str) else ""
    parser = _PlainText()
    parser.feed(value)
    return re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()


def _url(board: dict[str, str]) -> str:
    kind, slug = board["kind"], board["slug"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", slug):
        raise ValueError("Invalid employer-board identifier")
    if kind == "lever":
        return f"https://api.lever.co/v0/postings/{slug}?mode=json"
    if kind == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    if kind == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    if kind == "smartrecruiters":
        return f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
    raise ValueError(f"Unsupported public careers-board API: {kind}")


def _get_json(url: str, *, timeout: int = 7) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if int(getattr(response, "status", 200)) != 200:
            raise ValueError("ATS feed returned an unsuccessful status")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("ATS feed exceeds bounded response size")
    return json.loads(raw.decode("utf-8"))


def _failure_class(exc: Exception) -> str:
    """Classify transport failures without confusing proxy and board errors."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"employer_http_{exc.code}"
    message = str(exc).lower()
    if "tunnel connection failed" in message or "proxy" in message:
        return "proxy_establishment_failure"
    if isinstance(exc, urllib.error.URLError):
        reason = str(getattr(exc, "reason", "")).lower()
        if "tls" in reason or "ssl" in reason:
            return "tls_failure"
        if "name or service not known" in reason or "nodename" in reason or "dns" in reason:
            return "dns_failure"
        return "connection_failure"
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return "malformed_response"
    if isinstance(exc, TimeoutError) or "timed out" in message:
        return "timeout"
    return "request_failure"


def _location(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(str(value.get(k) or "") for k in ("city", "region", "country") if value.get(k)).strip()
    return str(value or "").strip()


def _row(board: dict[str, str], entry: dict[str, Any]) -> dict[str, Any] | None:
    kind, slug = board["kind"], board["slug"]
    if kind == "lever":
        categories = entry.get("categories") or {}
        title = entry.get("text")
        loc = categories.get("location") or entry.get("workplaceType") or ""
        description = plain(entry.get("descriptionPlain") or "") or plain(entry.get("description") or "")
        for part in entry.get("lists") or []:
            if isinstance(part, dict):
                description += " " + plain(part.get("text") or "") + " " + plain(part.get("content") or "")
        id_value = entry.get("id")
        link = entry.get("applyUrl") or entry.get("hostedUrl")
        posted = entry.get("createdAt")
        work_arrangement = entry.get("workplaceType") or ""
    elif kind == "ashby":
        title = entry.get("title")
        loc = entry.get("location") or ""
        description = plain(entry.get("descriptionPlain") or "") or plain(entry.get("descriptionHtml") or "")
        id_value = entry.get("id") or entry.get("jobUrl")
        link = entry.get("applyUrl") or entry.get("jobUrl")
        posted = entry.get("publishedAt") or ""
        work_arrangement = "remote" if entry.get("isRemote") else entry.get("workplaceType") or ""
    elif kind == "greenhouse":
        title = entry.get("title")
        loc = (entry.get("location") or {}).get("name") if isinstance(entry.get("location"), dict) else entry.get("location")
        description = plain(entry.get("content") or "")
        id_value = entry.get("id")
        link = entry.get("absolute_url")
        posted = entry.get("updated_at") or ""
        work_arrangement = ""
    elif kind == "smartrecruiters":
        title = entry.get("name") or entry.get("title")
        location = entry.get("location") or {}
        if isinstance(location, dict):
            loc = ", ".join(str(location.get(key) or "") for key in ("city", "region", "country") if location.get(key))
        else:
            loc = location
        job_ad = entry.get("jobAd") if isinstance(entry.get("jobAd"), dict) else {}
        sections = job_ad.get("sections") if isinstance(job_ad.get("sections"), dict) else {}
        description = " ".join(
            plain(section.get("title") or "") + " " + plain(section.get("text") or "")
            for section in sections.values() if isinstance(section, dict)
        ).strip()
        id_value = entry.get("id") or entry.get("refNumber")
        link = entry.get("ref")
        if not link and isinstance(entry.get("jobAd"), dict):
            link = entry["jobAd"].get("applyUrl")
        posted = entry.get("releasedDate") or entry.get("createdOn") or ""
        work_arrangement = ""
    else:
        return None
    if not title or not id_value or not isinstance(link, str) or not link.startswith("https://"):
        return None
    return {
        "source": "employer_direct",
        "source_job_id": f"{kind}:{slug}:{id_value}",
        "ats_kind": kind,
        "ats_board": slug,
        "company": board["company"],
        "title": str(title),
        "location": _location(loc),
        "description": description.strip(),
        "job_url": link,
        "application_url": link,
        "posted_date": str(posted or ""),
        "remote_type": str(work_arrangement or ""),
    }


def _smartrecruiters_entries(
    board: dict[str, str], fetcher: Any, timeout: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch SmartRecruiters' content envelope with bounded pagination."""
    entries: list[dict[str, Any]] = []
    offset = 0
    pages = 0
    total_found: int | None = None
    complete = False
    while pages < SMARTRECRUITERS_MAX_PAGES:
        url = f"{_url(board)}&offset={offset}"
        payload = fetcher(url, timeout=timeout)
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
            raise ValueError("SmartRecruiters response missing content list")
        page = [item for item in payload["content"] if isinstance(item, dict)]
        entries.extend(page)
        pages += 1
        raw_total = payload.get("totalFound")
        if raw_total not in (None, ""):
            try:
                total_found = max(0, int(raw_total))
            except (TypeError, ValueError):
                raise ValueError("SmartRecruiters totalFound is not numeric")
        if not page or (total_found is not None and offset + len(page) >= total_found) or len(page) < SMARTRECRUITERS_PAGE_LIMIT:
            complete = True
            break
        offset += len(page)
    return entries, {"pages": pages, "offset": offset, "total_found": total_found, "complete": complete}


def _smartrecruiters_detail_url(board: dict[str, str], entry: dict[str, Any]) -> str:
    identifier = entry.get("id") or entry.get("refNumber")
    if not identifier:
        return ""
    return f"https://api.smartrecruiters.com/v1/companies/{board['slug']}/postings/{identifier}"


def _local_relevance(job: dict[str, Any]) -> bool:
    """Restrict the pilot to Ontario/Canada or appropriately marked remote ads.

    Do not infer Canadian work eligibility from a blank location.
    """
    location = str(job.get("location") or "").lower()
    if not location:
        return False
    positive = ("toronto", "ontario", "canada", "north york", "markham",
                "mississauga", "oakville", "vaughan", "scarborough",
                "brampton", "richmond hill", "etobicoke", "remote - ca",
                "remote, ca", "remote (ca)")
    return any(token in location for token in positive)


def fetch_employer_direct_jobs(
    *, boards: tuple[dict[str, str], ...] | None = None,
    max_workers: int = 4, timeout: int = 7, max_jobs: int = 250,
    fetch_json: Any = None,
) -> dict[str, Any]:
    boards = DEFAULT_BOARDS if boards is None else boards
    fetcher = fetch_json or _get_json
    started = time.monotonic()
    all_rows: list[dict[str, Any]] = []
    board_outcomes: list[dict[str, Any]] = []
    seen: set[str] = set()

    def fetch_board(board: dict[str, str]) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, Any]]:
        if board["kind"] == "smartrecruiters":
            entries, pagination = _smartrecruiters_entries(board, fetcher, timeout)
            return board, entries, pagination
        payload = fetcher(_url(board), timeout=timeout)
        if board["kind"] == "lever":
            entries = payload if isinstance(payload, list) else []
        else:
            entries = payload.get("jobs", []) if isinstance(payload, dict) else []
        if not isinstance(entries, list):
            raise ValueError("ATS response did not contain a job list")
        return board, [item for item in entries if isinstance(item, dict)], {"pages": 1, "offset": 0, "total_found": len(entries), "complete": True}

    with ThreadPoolExecutor(max_workers=min(max(1, max_workers), max(1, len(boards)))) as executor:
        futures = {executor.submit(fetch_board, board): board for board in boards}
        for future in as_completed(futures):
            board = futures[future]
            try:
                _, entries, pagination = future.result()
                accepted = 0
                excluded = 0
                duplicates = 0
                detail_attempted = 0
                detail_succeeded = 0
                detail_failures = 0
                detail_budget_exhausted = False
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    # The listing contains enough location data to reject
                    # irrelevant postings before making any detail request.
                    job = _row(board, entry)
                    if job is None or not _local_relevance(job):
                        excluded += 1
                        continue
                    sections = (entry.get("jobAd") or {}).get("sections", {}) if isinstance(entry.get("jobAd"), dict) else {}
                    has_description = isinstance(sections, dict) and any(
                        plain(section.get("text") or section.get("content") or "")
                        for section in sections.values() if isinstance(section, dict)
                    )
                    if board["kind"] == "smartrecruiters" and not has_description:
                        detail_url = _smartrecruiters_detail_url(board, entry)
                        if detail_url and detail_attempted < SMARTRECRUITERS_MAX_DETAIL_REQUESTS:
                            detail_attempted += 1
                            try:
                                detail = fetcher(detail_url, timeout=min(timeout, SMARTRECRUITERS_DETAIL_TIMEOUT))
                                if isinstance(detail, dict):
                                    merged_entry = dict(entry)
                                    merged_entry.update(detail)
                                    entry = merged_entry
                                    detail_succeeded += 1
                            except Exception:
                                detail_failures += 1
                            job = _row(board, entry)
                        elif detail_url:
                            detail_budget_exhausted = True
                    if job["source_job_id"] in seen:
                        duplicates += 1
                        continue
                    seen.add(job["source_job_id"])
                    all_rows.append(job)
                    accepted += 1
                board_outcomes.append({"board": f"{board['kind']}:{board['slug']}", "state": "working" if accepted else "no_results", "scan_state": "complete" if pagination.get("complete", True) else "partial", "raw": len(entries), "jobs": accepted, "excluded": excluded, "duplicates": duplicates, "pages": pagination.get("pages", 1), "total_found": pagination.get("total_found"), "detail_attempted": detail_attempted, "detail_succeeded": detail_succeeded, "detail_failures": detail_failures, "detail_budget_exhausted": detail_budget_exhausted})
            except Exception as exc:
                board_outcomes.append({"board": f"{board['kind']}:{board['slug']}", "state": "failed", "failure_class": _failure_class(exc), "error": f"{type(exc).__name__}: {exc}"[:180]})
    all_rows.sort(key=lambda item: (item["company"].lower(), item["title"].lower(), item["source_job_id"]))
    all_rows = all_rows[:max_jobs]
    responded = sum(item["state"] in {"working", "no_results"} for item in board_outcomes)
    failures = sum(item["state"] == "failed" for item in board_outcomes)
    state = "working" if all_rows else "no_results" if responded else "unavailable"
    diagnostic = {
        "source": "employer_direct", "attempted": bool(boards), "state": state,
        "provider_status": state, "result_count": len(all_rows), "raw_records_row_count": sum(int(item.get("raw") or 0) for item in board_outcomes),
        "fetched_count": sum(int(item.get("raw") or 0) for item in board_outcomes),
        "usable_count": len(all_rows),
        "excluded_count": sum(int(item.get("excluded") or 0) for item in board_outcomes),
        "duplicate_count": sum(int(item.get("duplicates") or 0) for item in board_outcomes),
        "description_available_count": sum(bool(row["description"]) for row in all_rows),
        "detail_attempted_count": sum(int(item.get("detail_attempted") or 0) for item in board_outcomes),
        "detail_succeeded_count": sum(int(item.get("detail_succeeded") or 0) for item in board_outcomes),
        "detail_failure_count": sum(int(item.get("detail_failures") or 0) for item in board_outcomes),
        "partial_scan_count": sum(item.get("scan_state") == "partial" for item in board_outcomes),
        "detail_budget_exhausted_count": sum(bool(item.get("detail_budget_exhausted")) for item in board_outcomes),
        "boards_attempted": len(board_outcomes), "boards_succeeded": responded, "boards_failed": failures,
        "board_outcomes": sorted(board_outcomes, key=lambda item: item["board"]),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "success": responded > 0,
    }
    return {
        "jobs": all_rows,
        "errors": {"employer_direct": "Every configured public employer board failed."} if failures and not responded else {},
        "source_counts": {"employer_direct": len(all_rows)},
        "source_diagnostics": {"employer_direct": diagnostic},
        "source_snapshots": {"employer_direct": []},
    }
