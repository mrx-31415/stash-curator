"""Normalize Stash response objects into source-cache records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any


class AdapterError(RuntimeError):
    """Raised when a required response shape is absent or invalid."""


@dataclass(frozen=True)
class StashID:
    endpoint: str
    stash_id: str


@dataclass(frozen=True)
class Tag:
    id: str
    name: str | None
    updated_at: str | None
    parents: tuple[Tag, ...] = ()
    stash_ids: tuple[StashID, ...] = ()


@dataclass(frozen=True)
class Studio:
    id: str
    name: str | None
    updated_at: str | None
    favorite: bool = False
    rating100: int | None = None
    parent: Studio | None = None


@dataclass(frozen=True)
class Performer:
    id: str
    name: str | None
    updated_at: str | None
    favorite: bool
    gender: str | None
    rating100: int | None
    birthdate: str | None
    ethnicity: str | None
    country: str | None
    eye_color: str | None
    hair_color: str | None
    height_cm: int | None
    weight_kg: int | None
    measurements: str | None
    augmentation: str | None
    tattoos: str | None
    piercings: str | None
    tags: tuple[Tag, ...]


@dataclass(frozen=True)
class SourceFile:
    id: str
    duration_seconds: float | None


@dataclass(frozen=True)
class Marker:
    id: str
    seconds: float
    end_seconds: float | None
    primary_tag: Tag
    tags: tuple[Tag, ...]


@dataclass(frozen=True)
class Scene:
    id: str
    title: str | None
    details: str | None
    scene_date: str | None
    rating100: int | None
    updated_at: str | None
    play_count: int
    play_duration_seconds: float
    play_history_ms: tuple[int, ...]
    o_history_ms: tuple[int, ...]
    studio: Studio | None
    tags: tuple[Tag, ...]
    performers: tuple[Performer, ...]
    files: tuple[SourceFile, ...]
    markers: tuple[Marker, ...]


SourceEntity = Tag | Studio | Performer | Scene


@dataclass(frozen=True)
class EntityPage:
    total: int
    items: tuple[SourceEntity, ...]


def _object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdapterError(f"{label} must be an object")
    return value


def _objects(value: object, label: str) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise AdapterError(f"{label} must be a list")
    return tuple(_object(item, label) for item in value)


def _id(value: Mapping[str, Any], label: str) -> str:
    identifier = value.get("id")
    if not isinstance(identifier, (str, int)):
        raise AdapterError(f"{label}.id is required")
    return str(identifier)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object, *, positive: bool = False) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if not positive or value > 0 else None


def _epoch_ms(value: object) -> int:
    if not isinstance(value, str):
        raise AdapterError("history timestamps must be strings")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AdapterError(f"invalid history timestamp: {value}") from error
    return int(parsed.timestamp() * 1000)


def adapt_tag(value: object, *, include_parents: bool = True) -> Tag:
    raw = _object(value, "tag")
    parents: tuple[Tag, ...] = ()
    if include_parents:
        parents = tuple(adapt_tag(item, include_parents=False) for item in raw.get("parents", []))
    return Tag(
        _id(raw, "tag"),
        _optional_str(raw.get("name")),
        _optional_str(raw.get("updated_at")),
        parents,
        tuple(
            StashID(str(item["endpoint"]), str(item["stash_id"]))
            for item in _objects(raw.get("stash_ids", []), "stash_ids")
            if item.get("endpoint") and item.get("stash_id")
        ),
    )


def adapt_studio(value: object, *, include_parent: bool = True) -> Studio:
    raw = _object(value, "studio")
    parent_raw = raw.get("parent_studio")
    parent = (
        adapt_studio(parent_raw, include_parent=False) if include_parent and parent_raw else None
    )
    return Studio(
        _id(raw, "studio"),
        _optional_str(raw.get("name")),
        _optional_str(raw.get("updated_at")),
        bool(raw.get("favorite", False)),
        _optional_int(raw.get("rating100")),
        parent,
    )


def adapt_performer(value: object, *, include_details: bool = True) -> Performer:
    raw = _object(value, "performer")
    tags = tuple(adapt_tag(item, include_parents=False) for item in raw.get("tags", []))
    return Performer(
        id=_id(raw, "performer"),
        name=_optional_str(raw.get("name")),
        updated_at=_optional_str(raw.get("updated_at")),
        favorite=bool(raw.get("favorite", False)),
        gender=_optional_str(raw.get("gender")) if include_details else None,
        rating100=_optional_int(raw.get("rating100")) if include_details else None,
        birthdate=_optional_str(raw.get("birthdate")) if include_details else None,
        ethnicity=_optional_str(raw.get("ethnicity")) if include_details else None,
        country=_optional_str(raw.get("country")) if include_details else None,
        eye_color=_optional_str(raw.get("eye_color")) if include_details else None,
        hair_color=_optional_str(raw.get("hair_color")) if include_details else None,
        height_cm=_optional_int(raw.get("height_cm"), positive=True) if include_details else None,
        weight_kg=_optional_int(raw.get("weight"), positive=True) if include_details else None,
        measurements=_optional_str(raw.get("measurements")) if include_details else None,
        augmentation=_optional_str(raw.get("fake_tits")) if include_details else None,
        tattoos=_optional_str(raw.get("tattoos")) if include_details else None,
        piercings=_optional_str(raw.get("piercings")) if include_details else None,
        tags=tags,
    )


def adapt_scene(value: object) -> Scene:
    raw = _object(value, "scene")
    studio_raw = raw.get("studio")
    files = tuple(
        SourceFile(
            _id(item, "file"),
            float(item["duration"]) if isinstance(item.get("duration"), (int, float)) else None,
        )
        for item in _objects(raw.get("files", []), "files")
    )
    markers: list[Marker] = []
    for item in _objects(raw.get("scene_markers", []), "scene_markers"):
        primary = adapt_tag(item.get("primary_tag"), include_parents=False)
        end = item.get("end_seconds")
        markers.append(
            Marker(
                _id(item, "marker"),
                float(item["seconds"]),
                float(end) if isinstance(end, (int, float)) else None,
                primary,
                tuple(adapt_tag(tag, include_parents=False) for tag in item.get("tags", [])),
            )
        )
    return Scene(
        id=_id(raw, "scene"),
        title=_optional_str(raw.get("title")),
        details=_optional_str(raw.get("details")),
        scene_date=_optional_str(raw.get("date")),
        rating100=_optional_int(raw.get("rating100")),
        updated_at=_optional_str(raw.get("updated_at")),
        play_count=max(0, _optional_int(raw.get("play_count")) or 0),
        play_duration_seconds=max(0.0, float(raw.get("play_duration") or 0.0)),
        play_history_ms=tuple(_epoch_ms(item) for item in raw.get("play_history", [])),
        o_history_ms=tuple(_epoch_ms(item) for item in raw.get("o_history", [])),
        studio=adapt_studio(studio_raw) if studio_raw else None,
        tags=tuple(adapt_tag(item, include_parents=False) for item in raw.get("tags", [])),
        performers=tuple(
            adapt_performer(item, include_details=False) for item in raw.get("performers", [])
        ),
        files=files,
        markers=tuple(markers),
    )


def adapt_page(data: Mapping[str, Any], *, root_key: str, items_key: str) -> EntityPage:
    """Adapt one standard Stash find* response page."""
    root = _object(data.get(root_key), root_key)
    count = root.get("count")
    if not isinstance(count, int):
        raise AdapterError(f"{root_key}.count must be an integer")
    raw_items = _objects(root.get(items_key), items_key)
    if items_key == "tags":
        items: tuple[SourceEntity, ...] = tuple(adapt_tag(item) for item in raw_items)
    elif items_key == "studios":
        items = tuple(adapt_studio(item) for item in raw_items)
    elif items_key == "performers":
        items = tuple(adapt_performer(item) for item in raw_items)
    elif items_key == "scenes":
        items = tuple(adapt_scene(item) for item in raw_items)
    else:
        raise AdapterError(f"unsupported entity collection: {items_key}")
    return EntityPage(count, items)
