CREATE TABLE expand_candidate_revision (
    entity_type TEXT PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0
) STRICT, WITHOUT ROWID;

INSERT INTO expand_candidate_revision(entity_type) VALUES ('scene'), ('performer');

DELETE FROM application_meta WHERE key IN ('expand_order:v1:scene', 'expand_order:v1:performer');

CREATE TRIGGER expand_candidate_insert AFTER INSERT ON external_entity
WHEN NEW.pool = 'candidate'
BEGIN
    UPDATE expand_candidate_revision SET revision = revision + 1
    WHERE entity_type = NEW.entity_type;
END;

CREATE TRIGGER expand_candidate_delete AFTER DELETE ON external_entity
WHEN OLD.pool = 'candidate'
BEGIN
    UPDATE expand_candidate_revision SET revision = revision + 1
    WHERE entity_type = OLD.entity_type;
END;

CREATE TRIGGER expand_candidate_update
AFTER UPDATE OF entity_type, external_id, pool, score, payload_json, sources_json ON external_entity
WHEN (OLD.pool = 'candidate' OR NEW.pool = 'candidate')
AND (OLD.entity_type IS NOT NEW.entity_type OR OLD.external_id IS NOT NEW.external_id
     OR OLD.pool IS NOT NEW.pool OR OLD.score IS NOT NEW.score
     OR OLD.payload_json IS NOT NEW.payload_json OR OLD.sources_json IS NOT NEW.sources_json)
BEGIN
    UPDATE expand_candidate_revision SET revision = revision + 1
    WHERE (entity_type = OLD.entity_type AND OLD.pool = 'candidate')
       OR (entity_type = NEW.entity_type AND NEW.pool = 'candidate');
END;
