from pathlib import Path

import pytest

from apps.runtime.login import resolve_login_target


def test_resolve_login_target_github(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    target = resolve_login_target(site="github")

    assert target.url == "https://github.com/login"
    assert target.site == "github.com"
    assert target.profile_dir == tmp_path / "WebFA" / "browser" / "managed-chromium-profile-default"


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
