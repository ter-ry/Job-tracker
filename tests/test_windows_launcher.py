from pathlib import Path

import release_packaging.windows.launcher as launcher


def test_browser_failure_leaves_manual_startup_fallback(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args, **kwargs: False)

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
    monkeypatch.setattr(launcher, "server_is_healthy", lambda timeout=0.4: False)
    assert launcher.wait_for_server(timeout=0.02) is False


def test_existing_instance_recovery_uses_same_manual_fallback(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args, **kwargs: False)
    assert launcher.open_browser_or_report("http://127.0.0.1:5000/", tmp_path) is False
    assert (tmp_path / "startup-status.txt").exists()
