"""Small Whisparr v3 scene boundary."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, cast

Transport = Callable[[str, str, Mapping[str, str], bytes | None], bytes]


def _transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> bytes:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return cast(bytes, response.read())
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Whisparr request failed: {error}") from error


class WhisparrClient:
    def __init__(self, url: str, api_key: str, *, transport: Transport = _transport) -> None:
        if not url.strip() or not api_key.strip():
            raise ValueError("Whisparr URL and API key are required")
        self.url = f"{url.rstrip('/')}/api/v3"
        self.headers = {"Content-Type": "application/json", "X-Api-Key": api_key}
        self.transport = transport

    def send_scene(
        self,
        stashdb_id: str,
        title: str,
        root_folder: str = "",
        quality_profile_id: int = 0,
        *,
        search: bool = True,
    ) -> dict[str, object]:
        movies = self._request("GET", f"/movie?{urllib.parse.urlencode({'stashId': stashdb_id})}")
        if not isinstance(movies, list):
            raise RuntimeError("Whisparr returned an invalid movie list")
        existing = next(
            (
                item
                for item in movies
                if str(item.get("stashId") or item.get("foreignId") or "") == stashdb_id
            ),
            None,
        )
        if existing:
            return {"status": "already_exists", "id": existing.get("id")}
        if not root_folder.strip():
            folders = self._request("GET", "/rootfolder")
            root_folder = (
                next(
                    (
                        str(item.get("path") or "").strip()
                        for item in folders
                        if isinstance(item, dict) and item.get("path")
                    ),
                    "",
                )
                if isinstance(folders, list)
                else ""
            )
            if not root_folder:
                raise RuntimeError("Whisparr has no configured root folder")
        if quality_profile_id < 1:
            profiles = self._request("GET", "/qualityprofile")
            available = (
                [item for item in profiles if isinstance(item, dict)]
                if isinstance(profiles, list)
                else []
            )
            profile = next((item for item in available if item.get("fallback")), None)
            profile = profile or next(iter(available), None)
            quality_profile_id = int(profile.get("id") or 0) if profile else 0
            if quality_profile_id < 1:
                raise RuntimeError("Whisparr has no configured quality profile")
        created = self._request(
            "POST",
            "/movie",
            {
                "foreignId": stashdb_id,
                "stashId": stashdb_id,
                "title": title or "Added by Stash Curator",
                "rootFolderPath": root_folder,
                "qualityProfileId": quality_profile_id,
                "monitored": False,
                "addOptions": {"monitor": "none", "searchForMovie": search},
            },
        )
        if not isinstance(created, dict):
            raise RuntimeError("Whisparr returned an invalid add response")
        return {"status": "sent", "id": created.get("id")}

    def _request(self, method: str, path: str, payload: object | None = None) -> Any:
        body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
        raw = self.transport(method, f"{self.url}{path}", self.headers, body)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RuntimeError("Whisparr returned invalid JSON") from error
