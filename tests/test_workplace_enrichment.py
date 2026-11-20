import tempfile
from pathlib import Path
from unittest.mock import patch

import app as app_module


class _Response:
    headers = {"Content-Type": "text/html"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return b"<html><body><h2>Our Centre</h2><p>1200 Bayview Avenue<br>Toronto, ON M4G 1Z8</p></body></html>"


def test_workplace_enrichment_is_preview_first_and_persists_evidence():
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "test.sqlite"
        app_module._INITIALIZED_DATABASE_PATH = None
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        created = client.post("/api/jobs", json={
            "title": "RECE", "company": "Example Child Care", "location": "Toronto, ON",
            "url": "https://example.test/jobs/rece-1", "source": "indeed",
            "job_description": "Join our early learning team.", "discovery_first_seen_at": "2026-11-20T00:00:00",
        })
        assert created.status_code == 201
        with patch.object(app_module.urllib.request, "urlopen", return_value=_Response()):
            preview = client.post("/api/jobs/enrich-workplace-locations", json={"apply": False, "limit": 25})
        assert preview.status_code == 200
        assert preview.get_json()["preview"] is True
        assert preview.get_json()["gained_candidate"] == 1
        with app_module.app.app_context():
            row = app_module.query_db("SELECT workplace_address FROM jobs WHERE id = 1", one=True)
        assert row["workplace_address"] == ""
        with patch.object(app_module.urllib.request, "urlopen", return_value=_Response()):
            applied = client.post("/api/jobs/enrich-workplace-locations", json={"apply": True, "limit": 25})
        assert applied.status_code == 200
        assert applied.get_json()["preview"] is False
        with app_module.app.app_context():
            row = app_module.query_db("SELECT workplace_address, workplace_alternatives_json, workplace_precision FROM jobs WHERE id = 1", one=True)
        assert row["workplace_address"] == ""
        assert "M4G 1Z8" in row["workplace_alternatives_json"]
        assert row["workplace_precision"] == "candidate street address"
