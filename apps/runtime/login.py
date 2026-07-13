from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from browser.managed_chromium_host import ManagedChromiumHost
from browser.profile_repository import ProfileRepository
from browser.profile_storage import ProfileStorageManager
from storage.db import init_db


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
    storage = ProfileStorageManager()
    profile_dir = storage.paths_for("default").user_data_dir
    return LoginTarget(url=login_url, site=parsed.netloc, profile_dir=profile_dir)


def run_login_window(target: LoginTarget, input_func=input, output_func=print) -> dict:
    init_db()
    profile = ProfileRepository().ensure_default_profile()
    storage = ProfileStorageManager()
    runtime_instance_id = f"login_{uuid4().hex}"
    runtime_generation = f"login_generation_{uuid4().hex}"
    session_id = f"login_session_{uuid4().hex}"
    process_lock = storage.acquire_process_lock(
        profile,
        runtime_instance_id=runtime_instance_id,
        runtime_generation=runtime_generation,
        session_id=session_id,
    )
    output_func("WebFA Login")
    output_func(f"Site: {target.site}")
    output_func("Profile: default")
    output_func(f"Profile path: {target.profile_dir}")
    output_func("Sign in manually. WebFA will not ask an agent to type your password.")
    output_func("Status: launching login window")

    host = ManagedChromiumHost(
        launch_spec=storage.launch_spec(
            profile,
            headless=False,
            runtime_instance_id=runtime_instance_id,
            runtime_generation=runtime_generation,
        )
    )
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
        try:
            host.close()
        finally:
            process_lock.release()
