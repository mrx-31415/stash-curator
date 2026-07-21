CREATE TABLE profile_trace (
  trace_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('operation', 'task')),
  operation TEXT NOT NULL,
  started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
  duration_us INTEGER NOT NULL CHECK (duration_us >= 0),
  status TEXT NOT NULL CHECK (status IN ('ok', 'error')),
  span_count INTEGER NOT NULL CHECK (span_count >= 0),
  truncated INTEGER NOT NULL CHECK (truncated IN (0, 1)),
  trace_json TEXT NOT NULL CHECK (json_valid(trace_json))
) STRICT;

CREATE INDEX profile_trace_started_idx
ON profile_trace(started_at_ms DESC);
