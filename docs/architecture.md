---
title: Architecture
permalink: /architecture/
---

# Architecture

Curator is a self-contained external raw plugin with no runtime dependencies beyond
Python 3.12+. Optional numpy acceleration is provisioned on demand into a
plugin-local venv (see Runtime components); without it, the same code paths run in
pure Python. Stash loads `plugin/backend.py`; the browser UI is one JavaScript file
and one CSS file, and model code lives in the packaged `curator` module.

```text
Stash GraphQL
    │ read-only sync                      optional read-only metadata
    ▼                                                ▲
source cache ──► normalized events                  StashDB
                     │
                     ▼
             versioned features
                     │
                     ▼
        Appeal + Current Fit + confidence
                     │
                     ▼
       lane policy + published lane orders
                     │
                     ▼
       cards, Similar, and explanations
```

## Runtime components

- `plugin/stash-curator.js` registers the route, renders Stash-native cards, captures
  feedback/playback, and retries unacknowledged browser events.
- `plugin/backend.py` resolves Stash connection details, applies plugin settings,
  opens SQLite, and dispatches interactive operations and one-shot tasks.
- `curator/graphql/` and `curator/sync/` incrementally copy the required Stash facts.
- `curator/events/` conservatively reconstructs history and stores direct outcomes.
- `curator/features/`, `curator/model/`, and `curator/ranking/` publish immutable
  feature/model versions with indexed score-first queries and stable varied lane
  orders.
- `curator/similarity.py`, `curator/expand.py`, and `curator/explanations/` serve
  Similar, StashDB discovery, and factual reasons.
- `curator/optional_deps.py` and the **Install optional dependencies** task provide
  the optional numpy acceleration: the task creates a versioned venv beside the
  plugin and pip-installs `plugin/packages/curator-tools.txt`; `backend.py` adds the
  venv's site-packages to `sys.path` when present. The content-neighbor and
  performer-similarity stages use numpy (BLAS matmuls) when importable and fall back
  to their pure-Python implementations otherwise, so builds are deterministic and
  correct in either mode. The same venv carries networkx (and, when installed,
  scipy) for the multi-hop affinity stage: `curator/model/multi_hop.py` walks the
  persisted performer-collaboration graph with personalized PageRank and falls back
  to an equivalent pure-Python power iteration.
- `curator/storage/sql/` contains ordered, checksummed, transactional migrations.

## Data flow and failure boundaries

Sync writes normalized source tables, then event and feature builders create a new
version. Lane classifications, varied page orders, and the scheduled score-first
orders are built before model publication; simple score-first lanes use the published
classification index directly. Readers see the old complete model or the new complete
model, never a partial build. Interactive lane and Similar requests use compact SQLite
indexes and return stable IDs; the browser fetches current display metadata from
Stash.

Feedback and playback increment a durable generation counter and trigger a smaller
preference rebuild after a short debounce. They do not rerun library sync; after playback a
lightweight play-only sync keeps cooldown and recovery context current between full syncs.
Stash entity hooks (scene, performer, studio, and tag create/update/destroy) record each
changed entity in a pending queue, and the preference-rebuild task drains that queue
(fetching the entity by id or removing it on destroy) before rebuilding, so the model
always sees fresh source data while bulk edits pay no inline fetch cost. Full
sync/build and Expand refresh remain one-shot tasks because Stash provides no plugin
background scheduler/startup hook.

Direct tag sentiments keep append-only replacement history plus one current value per
tag. Model publication blends that value into the shared content affinity, so local
recommendations, Similar, Expand, and factual explanations consume the same result.
Expand refresh is incremental where the StashDB instance supports the updated_at
watermark (fetching only changed entries), falling back to a full fetch otherwise; it
keeps the existing candidate pool and explore rows from hunts and StashDB Similar,
re-scores the pool when the model has changed, and drops candidates older than the
recent-release horizon.

The only mutation path into Stash is isolated Prune tag application/removal.
StashDB failures affect external discovery only; cached Expand results and local
recommendations remain available.
