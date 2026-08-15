-- Curation batches: user-rated scene batches that test tag hypotheses
-- (stratified 2x2 sample around a base/context tag pair) or explore the
-- interactive tag space (rarity-weighted max-coverage sampler). Batch items
-- are immutable once issued; the ratings themselves live in `feedback` as
-- feedback_type='curation_rating' with value "0".."10" and the batch/cell in
-- payload_json, so reversals, staleness handling, and the model label
-- fingerprint work unchanged. status 'rated' means every item was answered;
-- 'superseded' is reserved for a later package's cleanup.

CREATE TABLE curation_batch (
    batch_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('hypothesis', 'explore')),
    base_tag_id TEXT,
    context_tag_id TEXT,
    budget INTEGER NOT NULL CHECK (budget BETWEEN 1 AND 40),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'rated', 'superseded')),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    payload_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE TABLE curation_batch_item (
    batch_id TEXT NOT NULL REFERENCES curation_batch(batch_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL,
    cell TEXT NOT NULL,
    anchor INTEGER NOT NULL DEFAULT 0 CHECK (anchor IN (0, 1)),
    rated INTEGER NOT NULL DEFAULT 0 CHECK (rated IN (0, 1)),
    PRIMARY KEY (batch_id, scene_id)
) STRICT, WITHOUT ROWID;
