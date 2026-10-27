"""Optional Windows Word layout measurements for format-preserving resumes."""

from __future__ import annotations

import json
import os
import subprocess
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
    $paragraphs += [pscustomobject]@{
      index = $index - 1
      text = ([string]$paragraph.Range.Text).TrimEnd([char]13, [char]7)
      lines = [int]$paragraph.Range.ComputeStatistics(1)
    }
  }
  [pscustomobject]@{
    available = $true
    pages = [int]$document.ComputeStatistics(2)
    paragraphs = $paragraphs
  } | ConvertTo-Json -Compress -Depth 6
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


def measure_docx_layout(path: str | Path) -> dict[str, Any]:
    """Measure rendered paragraphs/pages through Word COM when available."""
    if os.name != "nt":
        return {"available": False, "reason": "Microsoft Word COM is only available on Windows."}
    source = str(Path(path).resolve())
    try:
        environment = os.environ.copy()
        environment["JOB_TRACKER_LAYOUT_PATH"] = source
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "reason": str(exc)}
    if completed.returncode != 0:
        return {"available": False, "reason": completed.stderr.strip() or "Word COM measurement failed."}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"available": False, "reason": "Word COM returned invalid measurement data."}
    return result if isinstance(result, dict) else {"available": False, "reason": "Invalid Word COM measurement data."}


def compare_docx_layout(original: str | Path, candidate: str | Path) -> dict[str, Any]:
    """Require identical rendered paragraph line counts and page count."""
    original_measurement = measure_docx_layout(original)
    candidate_measurement = measure_docx_layout(candidate)
    if not original_measurement.get("available") or not candidate_measurement.get("available"):
        return {
            "verified": False,
            "available": False,
            "reason": original_measurement.get("reason") or candidate_measurement.get("reason") or "Word rendering unavailable.",
            "original": original_measurement,
            "candidate": candidate_measurement,
        }
    original_paragraphs = original_measurement.get("paragraphs", [])
    candidate_paragraphs = candidate_measurement.get("paragraphs", [])
    line_mismatches = []
    if len(original_paragraphs) != len(candidate_paragraphs):
        line_mismatches.append({"reason": "paragraph count changed", "original": len(original_paragraphs), "candidate": len(candidate_paragraphs)})
    for left, right in zip(original_paragraphs, candidate_paragraphs):
        if left.get("lines") != right.get("lines"):
            line_mismatches.append({"index": left.get("index"), "original_lines": left.get("lines"), "candidate_lines": right.get("lines")})
    page_mismatch = original_measurement.get("pages") != candidate_measurement.get("pages")
    return {
        "verified": not line_mismatches and not page_mismatch,
        "available": True,
        "page_mismatch": page_mismatch,
        "line_mismatches": line_mismatches,
        "original_pages": original_measurement.get("pages"),
        "candidate_pages": candidate_measurement.get("pages"),
        "original": original_measurement,
        "candidate": candidate_measurement,
    }


def export_docx_to_pdf(path: str | Path, output: str | Path) -> dict[str, Any]:
    """Export the exact DOCX through Word for an authoritative browser preview."""
    if os.name != "nt":
        return {"available": False, "reason": "Microsoft Word PDF export is only available on Windows."}
    source = str(Path(path).resolve())
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        environment = os.environ.copy()
        environment["JOB_TRACKER_LAYOUT_PATH"] = source
        environment["JOB_TRACKER_PDF_PATH"] = str(target)
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _EXPORT_POWERSHELL],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "reason": str(exc)}
    if completed.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        return {"available": False, "reason": completed.stderr.strip() or "Word PDF export failed."}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result = {"available": True, "path": str(target)}
    return result if isinstance(result, dict) else {"available": True, "path": str(target)}
