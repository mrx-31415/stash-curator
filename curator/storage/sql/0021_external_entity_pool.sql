-- A performer hunt or a "similar to this" probe merges scenes it finds into
-- external_entity so they can be shortlisted, but that table also backs the
-- general Expand browse. Without a pool marker, one performer's whole StashDB
-- catalog bleeds into another performer's Expand results until the next
-- refresh() wipes the table. Only rows refresh() writes belong in Expand.
-- Default existing rows to 'candidate' rather than 'explore': whatever is
-- already in the table came from the last refresh() plus whatever hunts and
-- similarity probes wrote since, and refresh() clears it wholesale on its
-- next run regardless, so there is nothing to gain by blanking Expand now.
ALTER TABLE external_entity ADD COLUMN pool TEXT NOT NULL DEFAULT 'candidate'
    CHECK (pool IN ('candidate', 'explore'));

CREATE INDEX external_entity_pool_idx ON external_entity(entity_type, pool, score DESC);
