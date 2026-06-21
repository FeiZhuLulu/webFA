from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from browser.managed_chromium_host import ManagedChromiumHost
from storage.file_store import ensure_webfa_data_dir


LOGIN_TARGETS = {
    "github": "https://github.com/login",
}


@dataclass(frozen=True)
class LoginTarget:
    url: str
    site: str
    profile_dir: Path


def resolve_login_target(site: str | None = None, url: str | None = None) -> LoginTarget:
    if bool(site) == bool(url):
        raise ValueError("provide exactly one login target: a site name or --url")
    login_url = url or LOGIN_TARGETS.get(str(site).lower())
    if not login_url:
        supported = ", ".join(sorted(LOGIN_TARGETS))
        raise ValueError(f"unknown login site; supported sites: {supported}")
    parsed = urlparse(login_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("login URL must be an http(s) URL")
    paths = ensure_webfa_data_dir()
    profile_dir = Path(paths["data_dir"]) / "browser" / "managed-chromium-profile-default"
    return LoginTarget(url=login_url, site=parsed.netloc, profile_dir=profile_dir)


def run_login_window(target: LoginTarget, input_func=input, output_func=print) -> dict:
    output_func("WebFA Login")
    output_func(f"Site: {target.site}")
    output_func("Profile: default")
    output_func(f"Profile path: {target.profile_dir}")
    output_func("Sign in manually. WebFA will not ask an agent to type your password.")
    output_func("Status: launching login window")

    host = ManagedChromiumHost(headless=False)
    try:
        host.navigate(target.url)
        output_func("Status: waiting for you to sign in")
        input_func("After signing in, press Enter here to save the profile and close the login window...")
        output_func("Status: profile updated")
        return {
            "status": "ok",
            "site": target.site,
            "profile": "default",
            "profile_dir": str(target.profile_dir),
        }
    finally:
        host.close()
