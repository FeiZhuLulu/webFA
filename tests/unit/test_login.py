from pathlib import Path

import pytest

from apps.runtime import login as login_module
from apps.runtime.login import resolve_login_target, run_login_window
from browser.profile_repository import ProfileRepository
from browser.profile_storage import ProfileStorageManager
from storage.db import init_db, reset_engine_for_tests


def test_resolve_login_target_github(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    target = resolve_login_target(site="github")

    assert target.url == "https://github.com/login"
    assert target.site == "github.com"
    assert target.profile_dir == tmp_path / "WebFA" / "profiles" / "default" / "chromium-user-data"


def test_resolve_login_target_url(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    target = resolve_login_target(url="https://example.com/login")

    assert target.url == "https://example.com/login"
    assert target.site == "example.com"


def test_resolve_login_target_requires_exactly_one_target():
    with pytest.raises(ValueError, match="exactly one"):
        resolve_login_target()
    with pytest.raises(ValueError, match="exactly one"):
        resolve_login_target(site="github", url="https://github.com/login")


def test_resolve_login_target_rejects_unknown_site():
    with pytest.raises(ValueError, match="unknown login site"):
        resolve_login_target(site="unknown")


def test_login_window_uses_default_profile_launch_spec_and_releases_lock(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()
    captured: dict[str, object] = {}

    class FakeHost:
        def __init__(self, *, launch_spec):
            captured["launch_spec"] = launch_spec

        def navigate(self, url: str) -> None:
            captured["url"] = url

        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(login_module, "ManagedChromiumHost", FakeHost)
    target = resolve_login_target(site="github")
    result = run_login_window(
        target,
        input_func=lambda _: "",
        output_func=lambda _: None,
    )

    launch_spec = captured["launch_spec"]
    assert launch_spec.user_data_dir == target.profile_dir
    assert captured["url"] == "https://github.com/login"
    assert captured["closed"] is True
    assert result["profile_dir"] == str(target.profile_dir)

    init_db()
    profile = ProfileRepository().ensure_default_profile()
    lock = ProfileStorageManager().acquire_process_lock(
        profile,
        runtime_instance_id="post-login-check",
        runtime_generation="generation-check",
        session_id="session-check",
    )
    lock.release()
