-- Avoid ALTER TABLE RENAME: attached artifact views can shadow indexed tables.
CREATE TABLE external_shortlist_endpoint_backup AS
SELECT entity_type, external_id, payload_json, score, sources_json, added_at_ms,
       lower(rtrim(COALESCE(json_extract(payload_json, '$.curator_endpoint'),
                            'https://stashdb.org/graphql'), '/')) AS endpoint
FROM external_shortlist;

DROP TABLE external_shortlist;

CREATE TABLE external_shortlist (
    entity_type TEXT NOT NULL CHECK (entity_type IN ('scene', 'performer')),
    external_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    score REAL NOT NULL,
    sources_json TEXT NOT NULL DEFAULT '[]',
    added_at_ms INTEGER NOT NULL CHECK (added_at_ms >= 0),
    endpoint TEXT NOT NULL DEFAULT 'https://stashdb.org/graphql',
    PRIMARY KEY (endpoint, entity_type, external_id)
) STRICT, WITHOUT ROWID;

INSERT INTO external_shortlist SELECT * FROM external_shortlist_endpoint_backup;
DROP TABLE external_shortlist_endpoint_backup;
