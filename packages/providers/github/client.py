"""GitHub HTTP client with unified headers, error mapping, and redaction."""

from __future__ import annotations

import os
from typing import Any

import httpx

from schemas.github import GitHubRateLimit


class GitHubClientError(Exception):
    def __init__(self, status_code: int, message: str, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.message = message
        self.headers = headers or {}
        self.request_id = self.headers.get("x-github-request-id", "")
        self.rate_limit = self._parse_rate_limit()
        super().__init__(message)

    def _parse_rate_limit(self) -> GitHubRateLimit | None:
        limit = self.headers.get("x-ratelimit-limit")
        remaining = self.headers.get("x-ratelimit-remaining")
        reset = self.headers.get("x-ratelimit-reset")
        if limit and remaining and reset:
            return GitHubRateLimit(
                limit=int(limit),
                remaining=int(remaining),
                reset=int(reset),
            )
        return None


class GitHubClient:
    """HTTP client for GitHub REST API."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self._token = token
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=15.0,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"WebFA-Desktop/{os.getenv('WEBFA_VERSION', '0.3.0')}",
            },
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.ConnectError:
            raise GitHubClientError(0, "GitHub network error: connection failed")
        except httpx.TimeoutException:
            raise GitHubClientError(0, "GitHub timeout")

        if resp.status_code >= 400:
            detail = resp.json().get("message", resp.text[:200]) if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200]
            raise GitHubClientError(
                status_code=resp.status_code,
                message=detail,
                headers=dict(resp.headers),
            )
        return resp

    def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = self._request("GET", path, **kwargs)
        return resp.json()

    def get_raw(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("GET", path, **kwargs)

    def get_rate_limit(self) -> dict[str, Any]:
        return self.get("/rate_limit")

    def close(self) -> None:
        self._client.close()
