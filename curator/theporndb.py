"""ThePornDB retrieval normalized to Curator's existing discovery query results."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from curator.features.measurements import CUP_ALIASES, parse_measurements, presence_category
from curator.graphql.client import (
    GraphQLClient,
    GraphQLError,
    JsonObject,
    _operation_name,
    _operation_type,
)
from curator.profiling import span


def is_theporndb(endpoint: str) -> bool:
    return (urllib.parse.urlparse(endpoint).hostname or "").casefold() == "theporndb.net"


RestResponse = tuple[int, bytes] | tuple[int, bytes, Mapping[str, str]]
RestTransport = Callable[[str, Mapping[str, str], float], RestResponse]


def _transport(url: str, headers: Mapping[str, str], timeout: float) -> RestResponse:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)
    except (urllib.error.URLError, TimeoutError) as error:
        raise GraphQLError(f"ThePornDB request failed: {error}") from error


class ThePornDBClient(GraphQLClient):
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        rest_transport: RestTransport = _transport,
        cache_path: Path | None = None,
    ) -> None:
        super().__init__(endpoint, profile_category="stashdb")
        self.base = (
            "https://api.theporndb.net"
            if is_theporndb(endpoint)
            else endpoint.rstrip("/").removesuffix("/graphql")
        )
        self.headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        self.rest_transport = rest_transport
        self._requests = threading.BoundedSemaphore(4)
        self._lock = threading.Lock()
        self._details: dict[str, Future[JsonObject | None]] = {}
        self._checked_at: dict[str, int] = {}
        self._tags: list[JsonObject] | None = None
        self._tags_checked_at = 0
        self._rate_lock = threading.Lock()
        self._retry_after = 0.0
        self._next_request = 0.0
        self._request_interval = (
            1.0 if rest_transport is _transport and is_theporndb(endpoint) else 0.0
        )
        self.cache_path = cache_path
        self._load_cache()

    def _load_cache(self) -> None:
        if self.cache_path is None:
            return
        try:
            cache = json.loads(self.cache_path.read_bytes())
            if not isinstance(cache, dict) or cache.get("version") != 1:
                return
            now = int(time.time() * 1000)
            for key, entry in cache.get("identities", {}).items():
                checked = entry["checked_at_ms"]
                if (
                    0 < checked <= now
                    and now - checked < 7 * 86_400_000
                    and isinstance(entry["value"], dict)
                ):
                    pending: Future[JsonObject | None] = Future()
                    pending.set_result(entry["value"])
                    self._details[key], self._checked_at[key] = pending, checked
            checked = cache.get("tags_checked_at_ms", 0)
            if (
                0 < checked <= now
                and now - checked < 30 * 86_400_000
                and isinstance(cache.get("tags"), list)
            ):
                self._tags, self._tags_checked_at = cache["tags"], checked
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return

    def _save_cache(self) -> None:
        if self.cache_path is None:
            return
        with self._lock:
            entries = sorted(
                self._details, key=lambda key: self._checked_at.get(key, 0), reverse=True
            )
            cache = {
                "version": 1,
                "identities": {
                    key: {
                        "checked_at_ms": self._checked_at[key],
                        "value": _identity(self._details[key].result()),
                    }
                    for key in entries[:1000]
                    if self._details[key].done()
                    and self._details[key].exception() is None
                    and isinstance(self._details[key].result(), dict)
                },
                "tags_checked_at_ms": self._tags_checked_at,
                "tags": self._tags or [],
            }
            temporary = None
            try:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=self.cache_path.parent, delete=False
                ) as output:
                    temporary = Path(output.name)
                    output.write(json.dumps(cache, separators=(",", ":")).encode())
                os.replace(temporary, self.cache_path)
            except OSError:
                pass
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def _remember_identity(self, resource: str, row: JsonObject | None) -> None:
        if not row:
            return
        identifier, numeric = row.get("id"), row.get("_id")
        if resource == "sites":
            identifier, numeric = row.get("uuid"), row.get("id")
        if not identifier or not numeric:
            return
        key = f"{resource}/{identifier}"
        with self._lock:
            if key not in self._details or self._details[key].done():
                pending: Future[JsonObject | None] = Future()
                pending.set_result(_identity(row))
                self._details[key] = pending
                self._checked_at[key] = int(time.time() * 1000)

    def execute(self, document: str, variables: Mapping[str, object] | None = None) -> JsonObject:
        if _operation_type(document) != "query":
            raise GraphQLError("Curator's validation client accepts query operations only")
        name = _operation_name(document)
        with span(self.profile_category, name):
            try:
                return self._query(name, dict(variables or {}))
            finally:
                self._save_cache()

    def mutate(self, document: str, variables: Mapping[str, object] | None = None) -> JsonObject:
        raise GraphQLError("ThePornDB discovery client is read-only")

    def _get(
        self, path: str, params: Mapping[str, str] | None = None, *, missing_ok: bool = False
    ) -> JsonObject:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        with self._requests:
            for attempt in range(4):
                with self._rate_lock:
                    start = max(time.monotonic(), self._retry_after, self._next_request)
                    self._next_request = start + self._request_interval
                    delay = start - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                response = self.rest_transport(url, self.headers, self.timeout)
                status, raw = response[0], response[1]
                if status != 429 or attempt == 3:
                    break
                headers = response[2] if len(response) == 3 else {}
                try:
                    seconds = int(headers.get("Retry-After", headers.get("retry-after", "60")))
                    if seconds < 0:
                        seconds = 60
                except ValueError:
                    seconds = 60
                with self._rate_lock:
                    self._retry_after = time.monotonic() + seconds
        if missing_ok and status == 404:
            return {"data": None}
        if status != 200:
            raise GraphQLError(f"ThePornDB request failed (HTTP {status})")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise GraphQLError("ThePornDB returned an invalid response") from error
        if not isinstance(value, dict) or "data" not in value:
            raise GraphQLError("ThePornDB returned an invalid response")
        return value

    def _list(
        self, path: str, params: dict[str, str], page: int, size: int
    ) -> tuple[int, list[JsonObject]]:
        if page < 1 or not 1 <= size <= 500:
            raise GraphQLError("invalid ThePornDB page")
        offset = (page - 1) * size
        rest_size = min(size, 100)
        rest_page, skip = offset // rest_size + 1, offset % rest_size
        rows: list[JsonObject] = []
        total = 0
        while len(rows) < size:
            result = self._get(path, {**params, "page": str(rest_page), "per_page": str(rest_size)})
            data = result["data"]
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise GraphQLError("ThePornDB returned an invalid list")
            if any(not row.get("id") for row in data):
                raise GraphQLError("ThePornDB returned an invalid list identity")
            if path.startswith("/performers"):
                for row in data:
                    self._remember_identity("performers", row)
            elif path == "/scenes":
                for row in data:
                    self._remember_identity("sites", row.get("site"))
                    for person in row.get("performers") or []:
                        self._remember_identity("performer-sites", person)
                        self._remember_identity("performers", person.get("parent"))
            meta = result.get("meta")
            if not isinstance(meta, dict):
                return len(data), data[offset : offset + size]
            if type(meta.get("total")) is not int or (
                "current_page" in meta and meta["current_page"] != rest_page
            ):
                raise GraphQLError("ThePornDB returned invalid pagination")
            total = meta["total"]
            rows.extend(data[skip : skip + size - len(rows)])
            if not data or rest_page * rest_size >= total:
                break
            rest_page += 1
            skip = 0
        return total, rows

    def _detail(self, resource: str, identifier: str) -> JsonObject | None:
        key = f"{resource}/{identifier}"
        with self._lock:
            pending = self._details.get(key)
            if pending is None:
                pending = Future()
                self._details[key] = pending
                owner = True
            else:
                owner = False
        if owner:
            try:
                result = self._get(
                    f"/{resource}/{urllib.parse.quote(identifier, safe='')}", missing_ok=True
                )
                if result["data"] is not None and not isinstance(result["data"], dict):
                    raise GraphQLError("ThePornDB returned an invalid identity")
                with self._lock:
                    self._checked_at[key] = int(time.time() * 1000)
                pending.set_result(result["data"])
            except Exception as error:
                pending.set_exception(error)
        return pending.result()

    def _parent_performer(self, identifier: str) -> JsonObject | None:
        with self._lock:
            known_site = self._details.get(f"performer-sites/{identifier}")
        if known_site is not None:
            site = known_site.result()
            return site.get("parent") if site else None
        parent = self._detail("performers", identifier)
        if parent is not None:
            return parent
        site = self._detail("performer-sites", identifier)
        return site.get("parent") if site else None

    def _tag_catalog(self) -> list[JsonObject]:
        with self._lock:
            if self._tags is None:
                tags = []
                page = 1
                while True:
                    total, rows = self._list("/tags", {}, page, 100)
                    tags.extend(rows)
                    if not rows or len(tags) >= total:
                        break
                    page += 1
                self._tags = tags
                self._tags_checked_at = int(time.time() * 1000)
            return self._tags

    def _scene_filter(self, params: dict[str, str], source: str, criterion: JsonObject) -> bool:
        modifier = criterion.get("modifier")
        if modifier not in {"INCLUDES", "INCLUDES_ALL"}:
            raise GraphQLError(f"unsupported ThePornDB {source} filter modifier")
        field, numeric = ("sites", "id") if source == "studios" else (source, "_id")
        if source == "tags":
            numeric = "id"

        def resolve(identifier: str) -> JsonObject | None:
            if source == "performers":
                return self._parent_performer(str(identifier))
            if source == "studios":
                return self._detail("sites", str(identifier))
            return next(
                (tag for tag in self._tag_catalog() if tag.get("uuid") == str(identifier)), None
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            stopped = threading.Event()

            def resolve_unless_failed(identifier: str) -> JsonObject | None:
                if stopped.is_set():
                    return None
                try:
                    return resolve(identifier)
                except Exception:
                    stopped.set()
                    raise

            rows = list(pool.map(resolve_unless_failed, criterion.get("value", [])))
        count = 0
        for row in rows:
            if not row or not row.get(numeric):
                if modifier == "INCLUDES_ALL":
                    return False
                continue
            params[f"{field}[{row[numeric]}]"] = str(row.get("name") or "")
            count += 1
        if source in {"performers", "tags"}:
            params["performer_and" if source == "performers" else "tag_and"] = str(
                modifier == "INCLUDES_ALL"
            ).lower()
        return count > 0

    def _query(self, operation: str, variables: JsonObject) -> JsonObject:
        query = variables.get("input", {})
        page, size = int(query.get("page", 1)), int(query.get("per_page", 25))
        if operation == "CuratorSceneFilterSchema":
            return {"__type": {"inputFields": []}}
        if operation == "CuratorTagCategories":
            return {"queryTagCategories": {"count": 0, "tag_categories": []}}
        if operation == "CuratorTaxonomyTags":
            tags = self._tag_catalog()
            page, size = int(variables.get("page", 0)), int(variables.get("perPage", 0))
            if page < 1 or size < 1:
                raise GraphQLError("invalid ThePornDB tag page")
            start = (page - 1) * size
            return {
                "queryTags": {
                    "count": len(tags),
                    "tags": [
                        {"id": row["uuid"], "name": row["name"], "aliases": [], "category": None}
                        for row in tags[start : start + size]
                    ],
                }
            }
        if operation == "CuratorExpandScenes":
            if "updated_at" in query:
                raise GraphQLError("ThePornDB requires a full discovery refresh")
            params = {
                "orderBy": "former_released"
                if query.get("direction") == "ASC"
                else "recently_released"
            }
            if query.get("sort") in {"POPULARITY", "TRENDING"}:
                params["orderBy"] = "most_relevant"
            for source in ("performers", "studios", "tags"):
                if source in query and not self._scene_filter(params, source, query[source]):
                    return {"queryScenes": {"count": 0, "scenes": []}}
            total, rows = self._list("/scenes", params, page, size)
            return {"queryScenes": {"count": total, "scenes": [_scene(row) for row in rows]}}
        if operation in {"CuratorSimilarPerformers", "CuratorPerformerSearch"}:
            params = {"orderBy": "asc_name" if query.get("sort") == "NAME" else "most_relevant"}
            if query.get("names"):
                params["q"] = query["names"]
            for name in ("gender", "ethnicity"):
                if query.get(name):
                    params[name] = query[name].replace("_", " ").title()
            if "age" in query:
                if query["age"].get("modifier") != "GREATER_THAN":
                    raise GraphQLError("unsupported ThePornDB age filter")
                params.update(age=str(query["age"]["value"]), age_operation=">")
            path = "/performers"
            if query.get("performed_with"):
                parent = self._parent_performer(query["performed_with"])
                if parent is None:
                    return {"queryPerformers": {"performers": []}}
                # REST offers profile similarity, rather than a co-star query.
                path = "/performers/" + urllib.parse.quote(parent["id"], safe="") + "/similar"
            total, rows = self._list(path, params, page, size)
            performers = [_performer(row) for row in rows]
            for name in ("gender", "ethnicity"):
                if name in params:
                    performers = [row for row in performers if row.get(name) == query[name]]
            return {"queryPerformers": {"count": total, "performers": performers}}
        raise GraphQLError(f"unsupported ThePornDB discovery operation: {operation}")


def _identity(raw: JsonObject | None) -> JsonObject:
    if raw is None:
        return {}
    value: JsonObject = {key: raw[key] for key in ("id", "_id", "uuid", "name") if key in raw}
    if isinstance(raw.get("parent"), dict):
        value["parent"] = _identity(raw["parent"])
    return value


def _images(raw: JsonObject) -> list[JsonObject]:
    return [
        {"url": raw[name], "width": None, "height": None}
        for name in ("image", "poster", "thumbnail", "face")
        if raw.get(name)
    ]


_NUMBER = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*(cm|m|in|inches|")?\s*$')
_CUP = re.compile(r"^(\d{2,3})?([A-Za-z]{1,3})$")


def _measurement(raw: Any, *, height: bool = False) -> float | None:
    match = _NUMBER.fullmatch(str(raw or ""))
    if not match:
        return None
    value, unit = float(match[1]), match[2]
    if height:
        if unit == "m":
            value *= 100
        if unit in {"in", "inches", '"'}:
            value *= 2.54
        return value if 100 <= value <= 230 else None
    if unit == "cm":
        value /= 2.54
    return value if unit != "m" and 15 <= value <= 80 else None


def _performer(raw: JsonObject) -> JsonObject:
    is_site = isinstance(raw.get("extra"), dict) and not isinstance(raw.get("parent"), dict)
    if isinstance(raw.get("parent"), dict):
        raw = raw["parent"]
    extra = raw.get("extras")
    if not isinstance(extra, dict):
        extra = raw.get("extra") or {}
    result = {
        "id": raw.get("id"),
        "curator_site_performer": is_site,
        "name": raw.get("name"),
        "aliases": raw.get("aliases") or [],
        "disambiguation": raw.get("disambiguation"),
        "scene_count": None,
        "images": _images(raw),
        "birth_date": extra.get("birthday"),
        "height": _measurement(extra.get("height"), height=True),
        "cup_size": None,
        "band_size": None,
        "waist_size": _measurement(extra.get("waist")),
        "hip_size": _measurement(extra.get("hips")),
        "breast_type": None,
    }
    for name, source in (
        ("gender", "gender"),
        ("ethnicity", "ethnicity"),
        ("eye_color", "eye_colour"),
        ("hair_color", "hair_colour"),
    ):
        value = extra.get(source)
        if name == "hair_color" and not value:
            value = extra.get("haircolor")
        text = str(value).strip().upper().replace(" ", "_") if value else None
        result[name] = "BRUNETTE" if name == "hair_color" and text == "BROWN" else text
    measurements = parse_measurements(extra.get("measurements"))
    if measurements:
        result.update(
            band_size=measurements.band_inches,
            waist_size=measurements.waist_inches,
            hip_size=measurements.hip_inches,
        )
        if measurements.normalized_cup:
            from curator.features.measurements import MEASUREMENT_PATTERN

            match = MEASUREMENT_PATTERN.fullmatch(extra["measurements"])
            assert match is not None
            result["cup_size"] = match["cup"].upper()
    cup = _CUP.fullmatch(str(extra.get("cupsize") or "").strip())
    if cup:
        if cup[2].upper() in CUP_ALIASES:
            result["cup_size"] = cup[2].upper()
        if cup[1]:
            result["band_size"] = _measurement(cup[1])
    fake = extra.get("fake_boobs")
    if fake is None:
        fake = extra.get("fakeboobs")
    if isinstance(fake, bool):
        result["breast_type"] = "FAKE" if fake else "NATURAL"
    for name in ("tattoos", "piercings"):
        value = str(extra.get(name) or "").strip()
        result[name] = (
            [{"location": value}] if value and presence_category(value) != "absent" else []
        )
    return result


def _scene(raw: JsonObject) -> JsonObject:
    performers: dict[str, JsonObject] = {}
    for person in raw.get("performers") or []:
        performer = _performer(person)
        performers.setdefault(performer["id"], {"performer": performer})
    site = raw.get("site")
    return {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "release_date": raw.get("date"),
        "production_date": None,
        "duration": raw.get("duration"),
        "details": raw.get("description"),
        "studio": {"id": site.get("uuid"), "name": site.get("name"), "images": _images(site)}
        if site
        else None,
        "tags": [{"id": tag.get("uuid"), "name": tag.get("name")} for tag in raw.get("tags") or []],
        "performers": list(performers.values()),
        "images": _images(raw),
        "fingerprints": [
            {
                "hash": row["hash"],
                "algorithm": str(row.get("type")).upper(),
                "duration": row.get("duration"),
            }
            for row in raw.get("hashes") or []
            if row.get("hash") and str(row.get("type")).upper() in {"PHASH", "OSHASH", "MD5"}
        ],
    }
