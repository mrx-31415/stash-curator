CREATE TABLE model_performer_estimate (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    performer_id TEXT NOT NULL,
    value REAL NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (model_id, performer_id)
) STRICT, WITHOUT ROWID;
