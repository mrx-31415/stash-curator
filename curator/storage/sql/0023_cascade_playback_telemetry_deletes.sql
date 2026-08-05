-- play_session and behavior_event keyed on scene_id with no foreign key, so a scene deleted
-- from Stash left orphaned rows behind that a later model build would crash on (see the
-- previous migration). SQLite cannot ALTER a constraint onto an existing column, so both
-- tables are rebuilt here with ON DELETE CASCADE to source_scene, and behavior_event's
-- existing (unenforced-by-default) link to play_session is upgraded to CASCADE too: without
-- that, deleting a scene would cascade into play_session, then hit behavior_event's
-- session_id constraint and abort the whole delete instead of cleaning up.
--
-- This never uses ALTER TABLE RENAME. A connection with a published model or feature
-- generation attached creates temp views over table names like entity_feature so the rest of
-- the code can read them uniformly; renaming *any* table while such a view exists makes
-- SQLite rescan the whole schema (every attached database, to patch other objects' text) and
-- that rescan hits a real SQLite bug ("views may not be indexed") on the shadowed name,
-- unrelated to what's actually being renamed. Plain CREATE TABLE/DROP TABLE do not trigger
-- that rescan, so both tables are staged under throwaway names, the old ones dropped, and the
-- replacements created directly under their real names instead.
--
-- Foreign keys stay enforced throughout (PRAGMA foreign_keys is a no-op inside a transaction,
-- and every migration runs in one), so behavior_event is staged before play_session is
-- dropped: DROP TABLE on a table other rows still reference performs an implicit delete that
-- re-triggers those references, and the staging copy carries no constraint on session_id to
-- trip over that.

CREATE TABLE play_session_staging (
    session_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL,
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    ended_at_ms INTEGER CHECK (ended_at_ms IS NULL OR ended_at_ms >= started_at_ms),
    active_seconds REAL NOT NULL DEFAULT 0 CHECK (active_seconds >= 0),
    provenance TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    impression_id TEXT REFERENCES impression(impression_id),
    summary_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

INSERT INTO play_session_staging SELECT * FROM play_session;

CREATE TABLE behavior_event_staging (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    scene_id TEXT,
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
    outcome REAL CHECK (outcome BETWEEN -1 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    provenance TEXT NOT NULL,
    session_id TEXT,
    impression_id TEXT REFERENCES impression(impression_id),
    payload_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

INSERT INTO behavior_event_staging SELECT * FROM behavior_event;

DROP TABLE behavior_event;
DROP TABLE play_session;

CREATE TABLE play_session (
    session_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    ended_at_ms INTEGER CHECK (ended_at_ms IS NULL OR ended_at_ms >= started_at_ms),
    active_seconds REAL NOT NULL DEFAULT 0 CHECK (active_seconds >= 0),
    provenance TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    impression_id TEXT REFERENCES impression(impression_id),
    summary_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

INSERT INTO play_session SELECT * FROM play_session_staging;
DROP TABLE play_session_staging;

CREATE TABLE behavior_event (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    scene_id TEXT REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
    outcome REAL CHECK (outcome BETWEEN -1 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    provenance TEXT NOT NULL,
    session_id TEXT REFERENCES play_session(session_id) ON DELETE CASCADE,
    impression_id TEXT REFERENCES impression(impression_id),
    payload_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

INSERT INTO behavior_event SELECT * FROM behavior_event_staging;
DROP TABLE behavior_event_staging;

CREATE INDEX play_session_scene_idx ON play_session(scene_id, started_at_ms);
CREATE INDEX behavior_event_scene_idx ON behavior_event(scene_id, occurred_at_ms);
