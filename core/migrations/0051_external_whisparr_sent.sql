-- StashDB scenes Curator has sent to Whisparr (including ones Whisparr
-- already had), so Find can mark them and a batch dismissal can skip them.
-- A row records Curator's send only; removing the scene in Whisparr does not
-- clear it.
CREATE TABLE external_whisparr_sent (
    endpoint TEXT NOT NULL,
    external_id TEXT NOT NULL,
    sent_at_ms INTEGER NOT NULL CHECK (sent_at_ms >= 0),
    PRIMARY KEY (endpoint, external_id)
) STRICT, WITHOUT ROWID;
