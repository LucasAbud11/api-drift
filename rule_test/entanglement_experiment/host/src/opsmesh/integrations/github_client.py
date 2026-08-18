"""Thin GitHub REST API client.

Note: this uses `httpx` directly for OpsMesh's *own* HTTP calls to
GitHub. That's unrelated to the `httpx` the `mcp` SDK uses internally
for its own transport - the two are just independent consumers of the
same library.
"""
from __future__ import annotations

import httpx

_BASE_URL = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str | None, *, base_url: str = _BASE_URL, timeout: float = 10.0) -> None:
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)

    async def get_latest_release(self, repo: str) -> dict:
        response = await self._client.get(f"/repos/{repo}/releases/latest")
        response.raise_for_status()
        return response.json()

    async def list_open_pull_requests(self, repo: str) -> list[dict]:
        response = await self._client.get(f"/repos/{repo}/pulls", params={"state": "open"})
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()
