ALTER TABLE impression_item ADD COLUMN qualified_at_ms INTEGER
    CHECK (qualified_at_ms IS NULL OR qualified_at_ms >= 0);
