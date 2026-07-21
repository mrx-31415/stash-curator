---
title: Architecture
permalink: /architecture/
---

# Architecture

Curator is a self-contained external raw plugin with no runtime dependencies beyond
Python 3.12+. Stash loads `plugin/backend.py`; the browser UI is one JavaScript file
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
        lane policy + diversity slate
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
  feature/model versions and construct slates.
- `curator/similarity.py`, `curator/expand.py`, and `curator/explanations/` serve
  Similar, StashDB discovery, and factual reasons.
- `curator/storage/sql/` contains ordered, checksummed, transactional migrations.

## Data flow and failure boundaries

Sync writes normalized source tables, then event and feature builders create a new
version. Model publication is atomic: readers see the old complete model or the new
complete model, never a partial build. Interactive lane and Similar requests use
compact SQLite indexes and return stable IDs; the browser fetches current display
metadata from Stash.

Feedback and playback increment a durable generation counter and trigger a smaller
preference rebuild after a short debounce. They do not rerun library sync. Full
sync/build and Expand refresh remain one-shot tasks because Stash provides no plugin
background scheduler/startup hook.

The only mutation path into Stash is isolated Prune tag application/removal.
StashDB failures affect external discovery only; cached Expand results and local
recommendations remain available.
