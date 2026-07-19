"""Small, injectable, query-only GraphQL client."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, cast

JsonObject = dict[str, Any]
Transport = Callable[[str, Mapping[str, str], bytes, float], bytes]


class GraphQLError(RuntimeError):
    """Raised for transport, protocol, or GraphQL response failures."""


def _operation_type(document: str) -> str | None:
    without_comments = re.sub(r"#[^\n]*", "", document).lstrip()
    match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", without_comments)
    return match.group(1).lower() if match else None


def _urllib_transport(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return cast(bytes, response.read())
    except (urllib.error.URLError, TimeoutError) as error:
        raise GraphQLError(f"Stash request failed: {error}") from error


class GraphQLClient:
    """Send GraphQL operations to Stash; mutations require the explicit method."""

    def __init__(
        self,
        url: str,
        *,
        api_key: str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        transport: Transport = _urllib_transport,
    ) -> None:
        base = url.rstrip("/")
        self.url = base if base.endswith("/graphql") else f"{base}/graphql"
        self.timeout = timeout
        self.transport = transport
        self.headers = {"Content-Type": "application/json", "Accept": "application/json"}
        self.headers.update(headers or {})
        if api_key:
            self.headers["ApiKey"] = api_key

    def execute(self, document: str, variables: Mapping[str, object] | None = None) -> JsonObject:
        """Execute one explicitly declared query and return its data object."""
        if _operation_type(document) != "query":
            raise GraphQLError("Curator's validation client accepts query operations only")
        return self._send(document, variables)

    def mutate(self, document: str, variables: Mapping[str, object] | None = None) -> JsonObject:
        """Execute an explicitly declared mutation."""
        if _operation_type(document) != "mutation":
            raise GraphQLError("Curator's mutation client accepts mutation operations only")
        return self._send(document, variables)

    def _send(self, document: str, variables: Mapping[str, object] | None) -> JsonObject:
        body = json.dumps(
            {"query": document, "variables": dict(variables or {})},
            separators=(",", ":"),
        ).encode()
        raw = self.transport(self.url, self.headers, body, self.timeout)
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise GraphQLError("Stash returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise GraphQLError("Stash returned a non-object GraphQL response")
        errors = payload.get("errors")
        if errors:
            raise GraphQLError(f"Stash GraphQL error: {errors}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise GraphQLError("Stash GraphQL response has no data object")
        return data
