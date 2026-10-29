"""Optional Windows Word layout measurements for format-preserving resumes."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

_POWERSHELL = r'''
$ErrorActionPreference = "Stop"
$path = $env:JOB_TRACKER_LAYOUT_PATH
$word = $null
$document = $null
try {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $false
  $document = $word.Documents.Open($path)
  $paragraphs = @()
  for ($index = 1; $index -le $document.Paragraphs.Count; $index++) {
    $paragraph = $document.Paragraphs.Item($index)
    $paragraphs += [pscustomobject]@{ index = $index - 1; text = ([string]$paragraph.Range.Text).TrimEnd([char]13, [char]7); lines = [int]$paragraph.Range.ComputeStatistics(1) }
  }
  [pscustomobject]@{ available = $true; pages = [int]$document.ComputeStatistics(2); paragraphs = $paragraphs } | ConvertTo-Json -Compress -Depth 6
}
finally {
  if ($document -ne $null) { $document.Close($false) }
  if ($word -ne $null) { $word.Quit() }
}
'''

_EXPORT_POWERSHELL = r'''
$ErrorActionPreference = "Stop"
$word = $null
$document = $null
try {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $false
  $document = $word.Documents.Open($env:JOB_TRACKER_LAYOUT_PATH)
  $document.ExportAsFixedFormat($env:JOB_TRACKER_PDF_PATH, 17)
  [pscustomobject]@{ available = $true; path = $env:JOB_TRACKER_PDF_PATH } | ConvertTo-Json -Compress
}
finally {
  if ($document -ne $null) { $document.Close($false) }
  if ($word -ne $null) { $word.Quit() }
}
'''

_COMBINED_POWERSHELL = r'''
$ErrorActionPreference = "Stop"
$word = $null
function Measure-Document($path) {
  $document = $word.Documents.Open($path, $false, $true)
  $paragraphs = @()
  for ($index = 1; $index -le $document.Paragraphs.Count; $index++) {
    $paragraph = $document.Paragraphs.Item($index)
    $paragraphs += [pscustomobject]@{ index = $index - 1; text = ([string]$paragraph.Range.Text).TrimEnd([char]13, [char]7); lines = [int]$paragraph.Range.ComputeStatistics(1) }
  }
  $pages = [int]$document.ComputeStatistics(2)
  $document.Close($false)
  return [pscustomobject]@{ available = $true; pages = $pages; paragraphs = $paragraphs }
}
try {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $false
  $original = Measure-Document $env:JOB_TRACKER_ORIGINAL_PATH
  $candidate = Measure-Document $env:JOB_TRACKER_CANDIDATE_PATH
  $document = $word.Documents.Open($env:JOB_TRACKER_CANDIDATE_PATH)
  $document.ExportAsFixedFormat($env:JOB_TRACKER_PDF_PATH, 17)
  $document.Close($false)
  [pscustomobject]@{ available = $true; original = $original; candidate = $candidate; pdf_path = $env:JOB_TRACKER_PDF_PATH } | ConvertTo-Json -Compress -Depth 8
}
finally {
  if ($word -ne $null) { $word.Quit() }
}
'''

_LAYOUT_CACHE: dict[str, dict[str, Any]] = {}
_LAYOUT_CACHE_LOCK = threading.Lock()


def _layout_cache_dir() -> Path:
    return Path(os.environ.get("JOB_TRACKER_DATA_DIR", Path.cwd() / "data")) / "layout_cache"


def _content_fingerprint(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cached_measurement(path: str | Path) -> dict[str, Any] | None:
    try:
        fingerprint = _content_fingerprint(path)
    except OSError:
        return None
    with _LAYOUT_CACHE_LOCK:
        value = _LAYOUT_CACHE.get(fingerprint)
    if value is None:
        cache_file = _layout_cache_dir() / f"{fingerprint}.json"
        try:
            value = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            value = None
    return json.loads(json.dumps(value)) if value is not None else None


def _store_measurement(path: str | Path, value: dict[str, Any]) -> None:
    try:
        fingerprint = _content_fingerprint(path)
    except OSError:
        return
    with _LAYOUT_CACHE_LOCK:
        _LAYOUT_CACHE[fingerprint] = json.loads(json.dumps(value))
    cache_dir = _layout_cache_dir()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = cache_dir / f".{fingerprint}.tmp"
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(cache_dir / f"{fingerprint}.json")
    except OSError:
        pass


def _compare_measurements(original: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    original_paragraphs = original.get("paragraphs", [])
    candidate_paragraphs = candidate.get("paragraphs", [])
    line_mismatches = []
    if len(original_paragraphs) != len(candidate_paragraphs):
        line_mismatches.append({"reason": "paragraph count changed", "original": len(original_paragraphs), "candidate": len(candidate_paragraphs)})
    for left, right in zip(original_paragraphs, candidate_paragraphs):
        if left.get("lines") != right.get("lines"):
            line_mismatches.append({"index": left.get("index"), "original_lines": left.get("lines"), "candidate_lines": right.get("lines")})
    page_mismatch = original.get("pages") != candidate.get("pages")
    return {"verified": bool(original.get("available") and candidate.get("available")) and not line_mismatches and not page_mismatch, "page_mismatch": page_mismatch, "line_mismatches": line_mismatches, "original_pages": original.get("pages"), "candidate_pages": candidate.get("pages")}


def _run_word(command: str, environment: dict[str, str]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, check=False, env=environment)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if completed.returncode != 0:
        return None, completed.stderr.strip() or "Word COM operation failed."
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None, "Word COM returned invalid measurement data."
    return result if isinstance(result, dict) else None, None


def measure_docx_layout(path: str | Path) -> dict[str, Any]:
    """Measure rendered paragraphs/pages through Word COM when available."""
    if os.name != "nt":
        return {"available": False, "reason": "Microsoft Word COM is only available on Windows."}
    cached = _cached_measurement(path)
    if cached is not None:
        cached["cached"] = True
        return cached
    environment = os.environ.copy()
    environment["JOB_TRACKER_LAYOUT_PATH"] = str(Path(path).resolve())
    result, error = _run_word(_POWERSHELL, environment)
    if error:
        return {"available": False, "reason": error}
    if result and result.get("available"):
        _store_measurement(path, result)
        return result
    return {"available": False, "reason": "Invalid Word COM measurement data."}


def compare_docx_layout(original: str | Path, candidate: str | Path) -> dict[str, Any]:
    """Require identical rendered paragraph line counts and page count."""
    original_measurement = measure_docx_layout(original)
    candidate_measurement = measure_docx_layout(candidate)
    if not original_measurement.get("available") or not candidate_measurement.get("available"):
        return {"verified": False, "available": False, "reason": original_measurement.get("reason") or candidate_measurement.get("reason") or "Word rendering unavailable.", "original": original_measurement, "candidate": candidate_measurement}
    return {"available": True, **_compare_measurements(original_measurement, candidate_measurement), "original": original_measurement, "candidate": candidate_measurement}


def compare_docx_layout_and_export(original: str | Path, candidate: str | Path, output: str | Path) -> dict[str, Any]:
    """Validate and export in one Word session, reusing fingerprinted measurements."""
    if os.name != "nt":
        return {"available": False, "verified": False, "reason": "Microsoft Word COM is only available on Windows."}
    original_measurement = _cached_measurement(original)
    candidate_measurement = _cached_measurement(candidate)
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if original_measurement and candidate_measurement and target.is_file() and target.stat().st_size:
        return {"available": True, "cached": True, **_compare_measurements(original_measurement, candidate_measurement), "original": original_measurement, "candidate": candidate_measurement, "pdf_path": str(target)}
    environment = os.environ.copy()
    environment["JOB_TRACKER_ORIGINAL_PATH"] = str(Path(original).resolve())
    environment["JOB_TRACKER_CANDIDATE_PATH"] = str(Path(candidate).resolve())
    environment["JOB_TRACKER_PDF_PATH"] = str(target)
    result, error = _run_word(_COMBINED_POWERSHELL, environment)
    if error or not result:
        return {"available": False, "verified": False, "reason": error or "Word COM operation failed."}
    original_measurement = result.get("original") or {"available": False}
    candidate_measurement = result.get("candidate") or {"available": False}
    if original_measurement.get("available"):
        _store_measurement(original, original_measurement)
    if candidate_measurement.get("available"):
        _store_measurement(candidate, candidate_measurement)
    return {"available": True, **_compare_measurements(original_measurement, candidate_measurement), "original": original_measurement, "candidate": candidate_measurement, "pdf_path": str(target)}


def export_docx_to_pdf(path: str | Path, output: str | Path) -> dict[str, Any]:
    """Export the exact DOCX through Word for an authoritative browser preview."""
    if os.name != "nt":
        return {"available": False, "reason": "Microsoft Word PDF export is only available on Windows."}
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["JOB_TRACKER_LAYOUT_PATH"] = str(Path(path).resolve())
    environment["JOB_TRACKER_PDF_PATH"] = str(target)
    result, error = _run_word(_EXPORT_POWERSHELL, environment)
    if error or not target.is_file() or target.stat().st_size == 0:
        return {"available": False, "reason": error or "Word PDF export failed."}
    return result or {"available": True, "path": str(target)}
