import json

import pytest

from curator.whisparr import WhisparrClient


def test_whisparr_send_checks_duplicates_and_honors_search_toggle() -> None:
    requests: list[tuple[str, str, object | None]] = []

    def transport(method: str, url: str, headers, body: bytes | None) -> bytes:
        requests.append((method, url, json.loads(body) if body else None))
        assert headers["X-Api-Key"] == "secret"
        return b"[]" if method == "GET" else b'{"id":42}'

    result = WhisparrClient("http://whisparr.local", "secret", transport=transport).send_scene(
        "stashdb-scene", "Scene", "/media", 3, search=False
    )

    assert result == {"status": "sent", "id": 42}
    assert requests[1][0:2] == (
        "POST",
        "http://whisparr.local/api/v3/movie",
    )
    assert requests[1][2]["addOptions"] == {"monitor": "none", "searchForMovie": False}


def test_whisparr_duplicate_is_not_posted() -> None:
    calls = 0

    def transport(_method: str, _url: str, _headers, _body: bytes | None) -> bytes:
        nonlocal calls
        calls += 1
        return b'[{"id":7,"stashId":"known"}]'

    result = WhisparrClient("http://whisparr.local", "secret", transport=transport).send_scene(
        "known", "Scene", "/media", 3
    )

    assert result == {"status": "already_exists", "id": 7}
    assert calls == 1


def test_whisparr_authentication_error_is_exposed() -> None:
    def transport(_method: str, _url: str, _headers, _body: bytes | None) -> bytes:
        raise RuntimeError("Whisparr request failed: HTTP Error 401")

    client = WhisparrClient("http://whisparr.local", "bad", transport=transport)
    with pytest.raises(RuntimeError, match="401"):
        client.send_scene("scene", "Scene", "/media", 3)
