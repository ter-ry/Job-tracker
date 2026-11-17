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


# Verified employer-facing career board URL patterns, 17 Nov 2026.
# Board names are kept editable in code until a separate owner registry UI ships.
DEFAULT_BOARDS: tuple[dict[str, str], ...] = (
    {"kind": "lever", "slug": "policyme", "company": "PolicyMe"},
    {"kind": "lever", "slug": "achievers", "company": "Achievers"},
    {"kind": "lever", "slug": "shyftlabs", "company": "ShyftLabs"},
    {"kind": "lever", "slug": "caseware", "company": "Caseware"},
    {"kind": "lever", "slug": "getmaple", "company": "Maple"},
    {"kind": "lever", "slug": "applydigital", "company": "Apply Digital"},
    {"kind": "lever", "slug": "ttecdigital", "company": "TTEC Digital"},
    {"kind": "ashby", "slug": "wealthsimple", "company": "Wealthsimple"},
    {"kind": "greenhouse", "slug": "greenhouse", "company": "Greenhouse"},
)

MAX_RESPONSE_BYTES = 2_000_000
USER_AGENT = "Job Tracker/0.0.0 (public employer job board reader)"


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

    def fetch_board(board: dict[str, str]) -> tuple[dict[str, str], Any]:
        return board, fetcher(_url(board), timeout=timeout)

    with ThreadPoolExecutor(max_workers=min(max(1, max_workers), max(1, len(boards)))) as executor:
        futures = {executor.submit(fetch_board, board): board for board in boards}
        for future in as_completed(futures):
            board = futures[future]
            try:
                _, payload = future.result()
                if board["kind"] == "lever":
                    entries = payload if isinstance(payload, list) else []
                else:
                    entries = payload.get("jobs", []) if isinstance(payload, dict) else []
                if not isinstance(entries, list):
                    raise ValueError("ATS response did not contain a job list")
                accepted = 0
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    job = _row(board, entry)
                    if job is None or not _local_relevance(job):
                        continue
                    if job["source_job_id"] in seen:
                        continue
                    seen.add(job["source_job_id"])
                    all_rows.append(job)
                    accepted += 1
                board_outcomes.append({"board": f"{board['kind']}:{board['slug']}", "state": "working", "jobs": accepted})
            except Exception as exc:
                board_outcomes.append({"board": f"{board['kind']}:{board['slug']}", "state": "failed", "error": f"{type(exc).__name__}: {exc}"[:180]})
    all_rows.sort(key=lambda item: (item["company"].lower(), item["title"].lower(), item["source_job_id"]))
    all_rows = all_rows[:max_jobs]
    successful = sum(item["state"] == "working" for item in board_outcomes)
    failures = len(board_outcomes) - successful
    state = "working" if all_rows else "no_results" if successful else "unavailable"
    diagnostic = {
        "source": "employer_direct", "attempted": bool(boards), "state": state,
        "provider_status": state, "result_count": len(all_rows), "raw_records_row_count": len(all_rows),
        "description_available_count": sum(bool(row["description"]) for row in all_rows),
        "boards_attempted": len(board_outcomes), "boards_succeeded": successful, "boards_failed": failures,
        "board_outcomes": sorted(board_outcomes, key=lambda item: item["board"]),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "success": successful > 0,
    }
    return {
        "jobs": all_rows,
        "errors": {"employer_direct": "Every configured public employer board failed."} if failures and not successful else {},
        "source_counts": {"employer_direct": len(all_rows)},
        "source_diagnostics": {"employer_direct": diagnostic},
        "source_snapshots": {"employer_direct": []},
    }
