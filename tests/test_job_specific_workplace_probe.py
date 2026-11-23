from scripts.probe_job_specific_workplace import probe_url


class _Response:
    status = 200

    def __init__(self, body, url):
        self._body = body.encode("utf-8")
        self._url = url
        self.headers = {"content-type": "text/html; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self._body[:limit]

    def geturl(self):
        return self._url


def test_probe_reads_job_specific_json_ld_and_visible_header(monkeypatch):
    html = """
    <script type="application/ld+json">
      {"@type":"JobPosting","jobLocation":{"address":{
        "streetAddress":"100 Galloway Road","addressLocality":"Scarborough",
        "addressRegion":"ON","postalCode":"M1E 1W7"}}}
    </script>
    <h1>RECE - BGC East Scarborough</h1>
    <div>100 Galloway Road, Scarborough, ON M1E 1W7</div>
    <h2>Full job description</h2>
    <div>Benefits mention 999 Fake Street only as unrelated text.</div>
    """
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _Response(html, request.full_url),
    )

    result = probe_url("https://example.test/job/1", timeout=5, max_bytes=100_000)

    assert result["retrieval_succeeded"] is True
    assert result["job_specific_tie"] is True
    assert result["jsonld_job_locations"][0]["address"].startswith("100 Galloway Road")
    assert any(item["value"] == "100 Galloway Road" for item in result["visible_header_location_evidence"])
    assert result["manual_confirmation_required"] is True


def test_probe_does_not_scan_scripts_or_job_description_chrome(monkeypatch):
    html = """
    <script>var challenge = "350 Queens Quay West, Toronto, ON M5V 1A1";</script>
    <h1>Registered Early Childhood Educator - Toronto, ON M5P 1J4</h1>
    <h2>Full job description</h2>
    <div>Contact office: 500 King Street, Toronto, ON M5V 1L9.</div>
    """
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _Response(html, request.full_url),
    )

    result = probe_url("https://example.test/job/2", timeout=5, max_bytes=100_000)

    assert all("350 Queens" not in item["excerpt"] for item in result["visible_header_location_evidence"])
    assert all(item["value"] != "500 King Street" for item in result["visible_header_location_evidence"])
    assert any(item["value"] == "M5P 1J4" for item in result["visible_header_location_evidence"])


def test_probe_reports_bounded_failures_without_retry(monkeypatch):
    calls = []

    def fail(request, timeout):
        calls.append((request.full_url, timeout))
        raise TimeoutError("bounded test timeout")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    result = probe_url("https://example.test/job/3", timeout=7, max_bytes=100_000)

    assert result["retrieval_succeeded"] is False
    assert "TimeoutError" in result["failure_reason"]
    assert calls == [("https://example.test/job/3", 7)]
