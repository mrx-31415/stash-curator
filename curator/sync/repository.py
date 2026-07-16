"""Transactional persistence for normalized sync pages."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from typing import cast

from curator.graphql.adapters import Marker, Performer, Scene, SourceEntity, SourceFile, Studio, Tag
from curator.storage import transaction


def _hash(entity: SourceEntity | SourceFile | Marker) -> str:
    payload = json.dumps(asdict(entity), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _later(left: str | None, right: str | None) -> str | None:
    values = [value for value in (left, right) if value]
    return max(values, default=None)


class SyncRepository:
    """Persist pages and their resume cursors in the same transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def resumable_run(self, mode: str) -> sqlite3.Row | None:
        row = self.connection.execute(
            """
            SELECT run_id, mode, state, server_version, started_at_ms
            FROM sync_run
            WHERE mode = ? AND state IN ('running', 'failed')
            ORDER BY started_at_ms DESC LIMIT 1
            """,
            (mode,),
        ).fetchone()
        return cast(sqlite3.Row | None, row)

    def start_run(self, run_id: str, mode: str, server_version: str, now_ms: int) -> None:
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO sync_run(run_id, mode, state, server_version, started_at_ms)
                VALUES (?, ?, 'running', ?, ?)
                """,
                (run_id, mode, server_version, now_ms),
            )

    def resume_run(self, run_id: str) -> None:
        with transaction(self.connection):
            self.connection.execute(
                "UPDATE sync_run SET state = 'running', error = NULL WHERE run_id = ?",
                (run_id,),
            )

    def prepare_entity(self, run_id: str, entity_type: str, now_ms: int) -> int | None:
        """Return the next page, or None when this entity completed in this run."""
        row = self.connection.execute(
            "SELECT run_id, page_cursor, state FROM sync_cursor WHERE entity_type = ?",
            (entity_type,),
        ).fetchone()
        if row is not None and row["run_id"] == run_id and row["state"] == "complete":
            return None
        if row is not None and row["run_id"] == run_id:
            with transaction(self.connection):
                self.connection.execute(
                    """
                    UPDATE sync_cursor SET state = 'running', updated_at_ms = ?
                    WHERE entity_type = ?
                    """,
                    (now_ms, entity_type),
                )
            return int(row["page_cursor"] or "1")

        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO sync_cursor(
                    entity_type, watermark, page_cursor, state, updated_at_ms,
                    run_id, baseline_watermark, pending_watermark
                ) VALUES (?, NULL, '1', 'running', ?, ?, NULL, NULL)
                ON CONFLICT(entity_type) DO UPDATE SET
                    page_cursor = '1', state = 'running', updated_at_ms = excluded.updated_at_ms,
                    run_id = excluded.run_id,
                    baseline_watermark = sync_cursor.watermark, pending_watermark = NULL
                """,
                (entity_type, now_ms, run_id),
            )
            self.connection.execute(
                """
                UPDATE sync_cursor
                SET baseline_watermark = watermark
                WHERE entity_type = ? AND baseline_watermark IS NULL
                """,
                (entity_type,),
            )
        return 1

    def cursor_watermarks(self, entity_type: str) -> tuple[str | None, str | None]:
        row = self.connection.execute(
            "SELECT baseline_watermark, pending_watermark FROM sync_cursor WHERE entity_type = ?",
            (entity_type,),
        ).fetchone()
        if row is None:
            return None, None
        return row["baseline_watermark"], row["pending_watermark"]

    def save_page(
        self,
        run_id: str,
        entity_type: str,
        items: tuple[SourceEntity, ...],
        *,
        next_page: int,
        page_high_watermark: str | None,
        now_ms: int,
        record_seen: bool,
    ) -> None:
        with transaction(self.connection):
            for item in items:
                self._upsert(item)
                if record_seen:
                    self.connection.execute(
                        """
                        INSERT OR IGNORE INTO sync_seen(run_id, entity_type, entity_id)
                        VALUES (?, ?, ?)
                        """,
                        (run_id, entity_type, item.id),
                    )
            row = self.connection.execute(
                "SELECT pending_watermark FROM sync_cursor WHERE entity_type = ?",
                (entity_type,),
            ).fetchone()
            pending = _later(row["pending_watermark"], page_high_watermark)
            self.connection.execute(
                """
                UPDATE sync_cursor
                SET page_cursor = ?, pending_watermark = ?, updated_at_ms = ?
                WHERE entity_type = ? AND run_id = ?
                """,
                (str(next_page), pending, now_ms, entity_type, run_id),
            )

    def complete_entity(self, run_id: str, entity_type: str, now_ms: int) -> None:
        with transaction(self.connection):
            self.connection.execute(
                """
                UPDATE sync_cursor
                SET watermark = COALESCE(pending_watermark, watermark), page_cursor = NULL,
                    state = 'complete', updated_at_ms = ?
                WHERE entity_type = ? AND run_id = ?
                """,
                (now_ms, entity_type, run_id),
            )

    def reconcile(self, run_id: str) -> None:
        """Delete only entities absent from a successfully traversed full snapshot."""
        with transaction(self.connection):
            self.connection.execute(
                """
                DELETE FROM source_scene WHERE NOT EXISTS (
                    SELECT 1 FROM sync_seen
                    WHERE run_id = ? AND entity_type = 'scene' AND entity_id = scene_id
                )
                """,
                (run_id,),
            )
            self.connection.execute(
                """
                DELETE FROM source_performer WHERE NOT EXISTS (
                    SELECT 1 FROM sync_seen
                    WHERE run_id = ? AND entity_type = 'performer' AND entity_id = performer_id
                )
                """,
                (run_id,),
            )
            self.connection.execute(
                """
                DELETE FROM source_tag WHERE NOT EXISTS (
                    SELECT 1 FROM sync_seen
                    WHERE run_id = ? AND entity_type = 'tag' AND entity_id = tag_id
                )
                """,
                (run_id,),
            )
            self.connection.execute(
                """
                UPDATE source_studio SET parent_studio_id = NULL
                WHERE NOT EXISTS (
                    SELECT 1 FROM sync_seen
                    WHERE run_id = ? AND entity_type = 'studio' AND entity_id = studio_id
                )
                """,
                (run_id,),
            )
            self.connection.execute(
                """
                DELETE FROM source_studio WHERE NOT EXISTS (
                    SELECT 1 FROM sync_seen
                    WHERE run_id = ? AND entity_type = 'studio' AND entity_id = studio_id
                )
                """,
                (run_id,),
            )

    def finish_run(self, run_id: str, now_ms: int) -> None:
        with transaction(self.connection):
            self.connection.execute(
                """
                UPDATE sync_run SET state = 'complete', completed_at_ms = ?, error = NULL
                WHERE run_id = ?
                """,
                (now_ms, run_id),
            )
            self.connection.execute("DELETE FROM sync_seen WHERE run_id = ?", (run_id,))

    def fail_run(self, run_id: str, entity_type: str | None, error: str, now_ms: int) -> None:
        with transaction(self.connection):
            self.connection.execute(
                "UPDATE sync_run SET state = 'failed', error = ? WHERE run_id = ?",
                (error[:2000], run_id),
            )
            if entity_type is not None:
                self.connection.execute(
                    """
                    UPDATE sync_cursor SET state = 'failed', updated_at_ms = ?
                    WHERE entity_type = ? AND run_id = ?
                    """,
                    (now_ms, entity_type, run_id),
                )

    def _upsert(self, entity: SourceEntity) -> None:
        if isinstance(entity, Tag):
            self._upsert_tag(entity)
        elif isinstance(entity, Studio):
            self._upsert_studio(entity)
        elif isinstance(entity, Performer):
            self._upsert_performer(entity)
        else:
            self._upsert_scene(entity)

    def _upsert_tag(self, tag: Tag, *, replace_parents: bool = True) -> None:
        for parent in tag.parents:
            self._upsert_tag(parent, replace_parents=False)
        self.connection.execute(
            """
            INSERT INTO source_tag(tag_id, name, updated_at, source_hash) VALUES (?, ?, ?, ?)
            ON CONFLICT(tag_id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at,
                source_hash=excluded.source_hash
            """,
            (tag.id, tag.name, tag.updated_at, _hash(tag)),
        )
        if replace_parents:
            self.connection.execute("DELETE FROM tag_parent WHERE tag_id = ?", (tag.id,))
            self.connection.executemany(
                "INSERT INTO tag_parent(tag_id, parent_tag_id) VALUES (?, ?)",
                ((tag.id, parent.id) for parent in tag.parents),
            )
            self.connection.execute("DELETE FROM source_tag_stash_id WHERE tag_id = ?", (tag.id,))
            stash_ids: dict[str, str] = {}
            for item in tag.stash_ids:
                stash_ids.setdefault(item.endpoint, item.stash_id)
            self.connection.executemany(
                """
                INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id)
                VALUES (?, ?, ?)
                """,
                ((tag.id, endpoint, stash_id) for endpoint, stash_id in stash_ids.items()),
            )

    def _upsert_studio(self, studio: Studio, *, replace_details: bool = True) -> None:
        if studio.parent:
            self._upsert_studio(studio.parent, replace_details=False)
        if not replace_details:
            self.connection.execute(
                """
                INSERT INTO source_studio(studio_id, name, updated_at, source_hash)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(studio_id) DO UPDATE SET
                    name=COALESCE(excluded.name, source_studio.name),
                    updated_at=COALESCE(excluded.updated_at, source_studio.updated_at)
                """,
                (studio.id, studio.name, studio.updated_at, _hash(studio)),
            )
            return
        self.connection.execute(
            """
            INSERT INTO source_studio(
                studio_id, name, parent_studio_id, updated_at, source_hash, favorite, rating100
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(studio_id) DO UPDATE SET name=excluded.name,
                parent_studio_id=excluded.parent_studio_id, updated_at=excluded.updated_at,
                source_hash=excluded.source_hash, favorite=excluded.favorite,
                rating100=excluded.rating100
            """,
            (
                studio.id,
                studio.name,
                studio.parent.id if studio.parent else None,
                studio.updated_at,
                _hash(studio),
                int(studio.favorite),
                studio.rating100,
            ),
        )

    def _upsert_performer(self, performer: Performer, *, replace_tags: bool = True) -> None:
        for tag in performer.tags:
            self._upsert_tag(tag, replace_parents=False)
        self.connection.execute(
            """
            INSERT INTO source_performer(
                performer_id, name, favorite, birthdate, ethnicity, country, eye_color,
                hair_color, height_cm, weight_kg, measurements, augmentation, tattoos,
                piercings, updated_at, source_hash, gender, rating100
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(performer_id) DO UPDATE SET name=excluded.name, favorite=excluded.favorite,
                birthdate=COALESCE(excluded.birthdate, source_performer.birthdate),
                ethnicity=COALESCE(excluded.ethnicity, source_performer.ethnicity),
                country=COALESCE(excluded.country, source_performer.country),
                eye_color=COALESCE(excluded.eye_color, source_performer.eye_color),
                hair_color=COALESCE(excluded.hair_color, source_performer.hair_color),
                height_cm=COALESCE(excluded.height_cm, source_performer.height_cm),
                weight_kg=COALESCE(excluded.weight_kg, source_performer.weight_kg),
                measurements=COALESCE(excluded.measurements, source_performer.measurements),
                augmentation=COALESCE(excluded.augmentation, source_performer.augmentation),
                tattoos=COALESCE(excluded.tattoos, source_performer.tattoos),
                piercings=COALESCE(excluded.piercings, source_performer.piercings),
                updated_at=excluded.updated_at, source_hash=excluded.source_hash,
                gender=COALESCE(excluded.gender, source_performer.gender),
                rating100=COALESCE(excluded.rating100, source_performer.rating100)
            """,
            (
                performer.id,
                performer.name,
                int(performer.favorite),
                performer.birthdate,
                performer.ethnicity,
                performer.country,
                performer.eye_color,
                performer.hair_color,
                performer.height_cm,
                performer.weight_kg,
                performer.measurements,
                performer.augmentation,
                performer.tattoos,
                performer.piercings,
                performer.updated_at,
                _hash(performer),
                performer.gender,
                performer.rating100,
            ),
        )
        if replace_tags:
            self.connection.execute(
                "DELETE FROM performer_tag WHERE performer_id = ?", (performer.id,)
            )
            self.connection.executemany(
                "INSERT INTO performer_tag(performer_id, tag_id) VALUES (?, ?)",
                ((performer.id, tag.id) for tag in performer.tags),
            )

    def _upsert_scene(self, scene: Scene) -> None:
        if scene.studio:
            self._upsert_studio(scene.studio)
        for tag in scene.tags:
            self._upsert_tag(tag, replace_parents=False)
        for performer in scene.performers:
            self.connection.execute(
                """
                INSERT INTO source_performer(
                    performer_id, name, favorite, updated_at, source_hash
                ) VALUES (?, ?, 0, ?, ?)
                ON CONFLICT(performer_id) DO UPDATE SET
                    name=COALESCE(excluded.name, source_performer.name),
                    updated_at=COALESCE(excluded.updated_at, source_performer.updated_at)
                """,
                (performer.id, performer.name, performer.updated_at, _hash(performer)),
            )
        for marker in scene.markers:
            self._upsert_tag(marker.primary_tag, replace_parents=False)
            for tag in marker.tags:
                self._upsert_tag(tag, replace_parents=False)
        self.connection.execute(
            """
            INSERT INTO source_scene(
                scene_id, title, details, scene_date, studio_id, play_count,
                play_duration_seconds, rating100, updated_at, source_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scene_id) DO UPDATE SET title=excluded.title, details=excluded.details,
                scene_date=excluded.scene_date, studio_id=excluded.studio_id,
                play_count=excluded.play_count,
                play_duration_seconds=excluded.play_duration_seconds,
                rating100=excluded.rating100, updated_at=excluded.updated_at,
                source_hash=excluded.source_hash
            """,
            (
                scene.id,
                scene.title,
                scene.details,
                scene.scene_date,
                scene.studio.id if scene.studio else None,
                scene.play_count,
                scene.play_duration_seconds,
                scene.rating100,
                scene.updated_at,
                _hash(scene),
            ),
        )
        self.connection.execute("DELETE FROM source_file WHERE scene_id = ?", (scene.id,))
        self.connection.executemany(
            """
            INSERT INTO source_file(file_id, scene_id, duration_seconds, available, source_hash)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(file_id) DO UPDATE SET scene_id=excluded.scene_id,
                duration_seconds=excluded.duration_seconds, available=excluded.available,
                source_hash=excluded.source_hash
            """,
            ((item.id, scene.id, item.duration_seconds, _hash(item)) for item in scene.files),
        )
        self.connection.execute("DELETE FROM scene_performer WHERE scene_id = ?", (scene.id,))
        self.connection.executemany(
            "INSERT INTO scene_performer(scene_id, performer_id, position) VALUES (?, ?, ?)",
            ((scene.id, item.id, position) for position, item in enumerate(scene.performers)),
        )
        self.connection.execute("DELETE FROM scene_tag WHERE scene_id = ?", (scene.id,))
        self.connection.executemany(
            "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, ?, 'scene')",
            ((scene.id, item.id) for item in scene.tags),
        )
        self.connection.execute("DELETE FROM scene_marker WHERE scene_id = ?", (scene.id,))
        for marker in scene.markers:
            self.connection.execute(
                """
                INSERT INTO scene_marker(
                    marker_id, scene_id, seconds, end_seconds, primary_tag_id, source_hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(marker_id) DO UPDATE SET scene_id=excluded.scene_id,
                    seconds=excluded.seconds, end_seconds=excluded.end_seconds,
                    primary_tag_id=excluded.primary_tag_id, source_hash=excluded.source_hash
                """,
                (
                    marker.id,
                    scene.id,
                    marker.seconds,
                    marker.end_seconds,
                    marker.primary_tag.id,
                    _hash(marker),
                ),
            )
            self.connection.execute("DELETE FROM marker_tag WHERE marker_id = ?", (marker.id,))
            self.connection.executemany(
                "INSERT INTO marker_tag(marker_id, tag_id) VALUES (?, ?)",
                ((marker.id, tag.id) for tag in marker.tags),
            )
        self.connection.execute("DELETE FROM source_play WHERE scene_id = ?", (scene.id,))
        self.connection.executemany(
            "INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES (?, ?, ?)",
            (
                (scene.id, timestamp, ordinal)
                for ordinal, timestamp in enumerate(scene.play_history_ms)
            ),
        )
        self.connection.execute("DELETE FROM source_o WHERE scene_id = ?", (scene.id,))
        self.connection.executemany(
            "INSERT INTO source_o(scene_id, occurred_at_ms, ordinal) VALUES (?, ?, ?)",
            (
                (scene.id, timestamp, ordinal)
                for ordinal, timestamp in enumerate(scene.o_history_ms)
            ),
        )
