---
title: Architecture
permalink: /architecture/
---

# Architecture

Curator is a self-contained external raw plugin with no runtime dependencies
beyond the compiled Go core (`curator-core`) that ships in the plugin zip;
there is no runtime install task, virtual environment, or Python backend.
Stash loads `plugin/launcher.py`, which execs the per-arch `curator-core`
binary; the browser UI is one JavaScript file and one CSS file. `backend.py`
and the `curator` Python package remain in the repository only as the
differential-test oracle (`tests/core/`, `tests/plugin/`).

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
- `curator-core` (Go, shipped as per-arch `curator-core-<goos>-<goarch>`
  binaries in the plugin zip, exec'd by `plugin/launcher.py`) resolves Stash
  connection details, applies plugin settings, opens SQLite, and dispatches
  interactive operations, one-shot tasks, and the entity-sync hook mode; it
  also implements the model-build kernels.
- `core/` is the production Go implementation: ingestion, events, model versions,
  recommendation lanes, Similar, external discovery, explanations, and SQLite access.
- `curator/` and `backend.py` remain development/test oracles; they are not shipped as
  a production backend. The explanation realization catalog is the sole runtime resource
  retained from `curator/`.
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
always sees fresh source data while bulk edits pay no inline fetch cost. The persistent
worker applies automatic model updates and recent-play syncs without an open browser tab.
It also maintains scheduled-task records for optional Expand refresh, sync/build, and backups.

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
