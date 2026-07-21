# Stash Curator handover

Updated: 2026-07-21 at commit `d7c528d` on `main`.

## Project state

Stash Curator is a working Stash v0.31 plugin that learns locally from library
history and feedback. It provides five recommendation lanes, inspectable reasons,
local similarity, pruning assistance, and optional StashDB discovery. The project is
feature-complete enough for a 1.0 candidate; the remaining work is installed-system
testing, performance confirmation, and fixes driven by that testing.

Use these documents as the source of truth:

- [design.md](design.md) for product semantics and scoring intent;
- [implementation.md](implementation.md) for architecture, data contracts, and work
  package status;
- [tag-evidence.md](tag-evidence.md) for tag and performer-attribute treatment;
- [natural-language-explanations.md](natural-language-explanations.md) for prose.

Do not redesign the model from this handover. It records operational context that is
too transient for the design documents.

## Product conclusions

- Appeal means general learned preference. Current Fit means whether a scene suits
  the present occasion, including cooldown and recent repetition.
- Direct outcomes override inferred preference. O is the strongest positive outcome;
  thumbs down after an earlier O suppresses the scene.
- Tags are positive-unlabeled evidence: presence is useful, absence is weak because
  tagging is incomplete. Rare, outcome-enriched content tags matter more than common
  tags.
- Performer appearance belongs in missing-aware performer profiles, not duplicated
  as scene content. Approximate importance is measurements, augmentation, ethnicity,
  height, age-at-recording, hair, tattoos, piercings, then eyes.
- Diversity is a slate concern, not part of Appeal. Avoid adjacent repeated
  performers and softly vary studios and content clusters.
- Best Bets excludes viewed scenes; Revisit owns strong watched scenes; For You mixes
  lanes. Discover challenges one learned assumption, while Adventure tolerates more
  misses and can expose pruning candidates.
- Explanations must be inspectable and conversational but factual. Structured reason
  data is authoritative; deterministic prose realizes it.
- Curator never deletes media. Prune only adds or removes a configurable tag.
- StashDB discovery is opt-in. Preference data stays local; only bounded read-only
  metadata queries are sent remotely.

## Runtime architecture

The plugin is dependency-free at runtime: Stash loads `plugin/backend.py`, which
opens the sidecar SQLite database, applies migrations, and dispatches operations into
the `curator` package. The browser integration is a self-contained JavaScript/CSS
bundle in `plugin/`.

The principal flow is:

1. GraphQL sync copies relevant Stash facts into `source_*` tables.
2. Event normalization reconstructs conservative historical outcomes and records new
   player and feedback events.
3. Feature construction publishes immutable sparse features and performer profiles.
4. The deterministic model publishes affinities, Appeal, Current Fit, and lane inputs
   atomically.
5. Lane slates and Similar results are generated on demand from compact SQLite
   indexes, then cached in the browser.
6. The reason planner produces structured evidence and deterministic natural
   language.

Continuous preference updates use a durable generation counter and a short debounce.
They do not rerun library sync. Full sync/build remains a manual or externally
scheduled Stash task because Stash has no plugin background scheduler/startup hook.

## Implemented surfaces

- Curator navigation, five lanes, score tree, feedback, and playback capture;
- incremental/full sync, model tasks, progress, logs, health, backup, and settings;
- local Similar scenes and performers with filters and contextual entry buttons;
- Prune candidates, explicit dislikes, suspects, reversible tagging, and bulk action;
- Expand scenes/performers, saved filters, shortlist, copy/open actions, and optional
  Whisparr v3 handoff;
- StashDB taxonomy resolution by explicit ID, unique canonical name, or alias;
- external Similar with separate Library/StashDB results and bounded remote probes;
- self-contained evaluation report, redaction mode, CLI, package source, CI, and
  GitHub Pages publication.

Work-package details and remaining acceptance checks are recorded in
[implementation.md section 20](implementation.md#20-work-packages).

## Latest performance work

The current priority is confirming Similar latency after the latest package update.
Timing fields were added to both local and external Similar responses so profiling
does not rely on perceived UI time.

Before the last two optimizations, one representative uncached scene search measured:

| Search | Total | Main cost |
| --- | ---: | --- |
| Local Similar | about 13 s | content scan 7.6 s; profile load 3.1 s |
| StashDB Similar | about 45 s | local scoring 39.2 s; retrieval 1.6 s |

The following changes are now on `main`:

- `4198715` narrows remote scene probes to two strong tags and exact performers,
  queried concurrently. This reduced remote retrieval to roughly 1.6 seconds.
- `69c6a1c` reads performer/studio Appeal evidence from compact
  `model_scene_lane` rows rather than scanning historical `model_scene_score` rows.
- `d7c528d` adds migration 12 and `scene_content_search`, a current-version sparse
  inverted index. Feature publication refreshes it atomically; local content overlap
  no longer scans immutable feature history.

Migration 12 backfills the current published feature version once. Therefore the
first operation after installing it may be slower; later requests are the meaningful
measurement. Confirm that local `content` and external `scoring` timings fall before
adding another cache or database.

Migration 11 added Appeal to `model_scene_lane`. Concurrent plugin operations once
raced and produced `duplicate column name: appeal`; `4198715` fixed the migration
runner by rechecking each migration after acquiring the write transaction. Do not
special-case that old error in the UI.

## Immediate next steps

1. Install/update the package containing `d7c528d` and let migration 12 finish.
2. Run the same local Similar search twice. Record `timings_ms`; the second request
   removes migration and cold-cache noise.
3. Run the corresponding StashDB search twice and record retrieval, scoring, ranking,
   and total timings.
4. If local profile loading remains material, query only performers attached to the
   viable content candidates instead of loading every profile. Do this only if the
   new measurement justifies it.
5. If remote scoring remains material, inspect its SQL with `EXPLAIN QUERY PLAN` and
   the timing breakdown before changing remote probes again.
6. Complete installed browser checks for mobile layout, keyboard/touch behavior,
   playback capture, Prune tagging, StashDB failure isolation, and server restart.
7. After those checks pass, tag the 1.0 release candidate.

External recommendation quality remains inherently weaker than local quality because
StashDB records expose less preference evidence and performer metadata can be sparse.
Favor locally known/favorited performers, distinctive resolved content tags, and the
same missing-aware performer profile weights used internally. Do not compensate by
letting multiple merely known performers overwhelm scene-content mismatch.

## Code map

- `curator/sync/`, `curator/graphql/`: Stash ingestion;
- `curator/events/`: outcome normalization and event persistence;
- `curator/features/`, `curator/taxonomy/`: sparse features and tag classification;
- `curator/model/`: affinities, Appeal, Current Fit, publication, and updates;
- `curator/ranking/`: lane policy and diversity-aware slate construction;
- `curator/similarity.py`: local Similar;
- `curator/expand.py`: StashDB discovery, external Similar, shortlist, and Whisparr;
- `curator/explanations/`: reason planning and realizations;
- `curator/storage/sql/`: ordered immutable SQLite migrations;
- `plugin/backend.py`, `plugin/stash-curator.js`, `plugin/stash-curator.css`: plugin
  bridge and Stash UI;
- `tests/`: synthetic unit and integration coverage.

## Verification and packaging

From the repository root:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy curator plugin/backend.py
uv run pytest -q
uv run python scripts/build_plugin.py
```

At handover, strict typing and lint passed, all 145 tests passed, and
`dist/stash-curator.zip` contained migration 12.

## Guardrails

- Preserve existing user changes and sidecar data. Never reset or delete the database
  to solve a migration issue.
- SQLite migrations are ordered, immutable, checksummed, and transactional. Add a new
  migration instead of editing an applied one.
- Keep Stash reads separate from the only intentional library mutation: reversible
  Prune tagging.
- Do not commit databases, reports, GraphQL payloads, credentials, real entity IDs,
  or private evaluation notes.
- Prefer measured SQL/index changes over speculative caches or a second database.
- Convert generalizable live defects into synthetic regression tests.
