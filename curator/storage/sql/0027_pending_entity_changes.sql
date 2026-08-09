-- Entity hooks enqueue the changed entity instead of fetching it inline: Stash fires
-- hooks inside the mutation path, and a per-edit GraphQL fetch plus upsert added latency
-- to every edit (and minutes to bulk edits). The hook records the change here, and the
-- preference-rebuild task drains the queue before rebuilding, so the model always sees
-- fresh source data. The row keeps the latest operation (an update followed by a destroy
-- becomes a delete), and the queue is superseded by any full sync.

CREATE TABLE pending_entity_change (
    entity_type TEXT NOT NULL CHECK (entity_type IN ('tag', 'studio', 'performer', 'scene')),
    entity_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('upsert', 'delete')),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY (entity_type, entity_id)
) STRICT, WITHOUT ROWID;
