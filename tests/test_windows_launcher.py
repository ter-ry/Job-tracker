from pathlib import Path

import release_packaging.windows.launcher as launcher


def test_browser_failure_leaves_manual_startup_fallback(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args, **kwargs: False)
    monkeypatch.setattr(launcher, "show_startup_recovery", lambda url: None)

    assert launcher.open_browser_or_report("http://127.0.0.1:5000/", tmp_path) is False
    report = (tmp_path / "startup-status.txt").read_text(encoding="utf-8")
    assert "Open this address manually" in report
    assert "127.0.0.1:5000" in report
    assert "Automatic browser launch failed" in capsys.readouterr().out


def test_browser_success_does_not_create_failure_report(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args, **kwargs: True)

    assert launcher.open_browser_or_report("http://127.0.0.1:5000/", tmp_path) is True
    assert not (tmp_path / "startup-status.txt").exists()


def test_server_readiness_has_a_bounded_failure(monkeypatch):
    monkeypatch.setattr(launcher, "server_is_healthy", lambda **kwargs: False)
    assert launcher.wait_for_server(timeout=0.02) is False


def test_existing_instance_recovery_uses_same_manual_fallback(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args, **kwargs: False)
    monkeypatch.setattr(launcher, "show_startup_recovery", lambda url: None)
    assert launcher.open_browser_or_report("http://127.0.0.1:5000/", tmp_path) is False
    assert (tmp_path / "startup-status.txt").exists()


def test_qa_and_production_use_distinct_ports_and_mutexes():
    assert launcher.QA_PORT != launcher.PORT
    assert launcher.INSTANCE_MUTEX != f"{launcher.INSTANCE_MUTEX}-QA"


def test_inherited_qa_data_root_is_rejected_for_production(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("JOB_TRACKER_DATA_DIR", str(tmp_path / "Job Tracker" / "QA Session"))
    assert launcher.validated_runtime_data_dir(False) is None
    assert launcher.validated_runtime_data_dir(True) == tmp_path / "Job Tracker" / "QA Session"


def test_explicit_packaging_test_root_is_allowed_only_with_test_marker(monkeypatch, tmp_path):
    custom = tmp_path / "frozen-smoke"
    monkeypatch.setenv("JOB_TRACKER_DATA_DIR", str(custom))
    monkeypatch.setenv("JOB_TRACKER_TEST_MODE", "1")
    assert launcher.validated_runtime_data_dir(False) == custom
