---
title: Privacy and data safety
permalink: /privacy/
---

# Privacy and data safety

Curator is local-first. A separate plugin-owned SQLite database stores the Stash
metadata needed for recommendations, viewing and feedback events, tag preferences,
recommendation history, shortlists, model versions, and explanation evidence. The
browser temporarily keeps an idempotent feedback/playback queue so navigation or a
short failure does not lose an action.

## Stash and StashDB boundaries

Stash GraphQL remains authoritative for your library. Normal sync and recommendation
work is read-only. Curator's sole intentional Stash mutation is an explicit Prune
action that adds or removes the configured tag; it never deletes media.

StashDB discovery is opt-in. Curator sends bounded, read-only metadata searches for
public tags, performers, and scenes. Scoring happens locally. Viewing history,
feedback, learned weights, local URLs, and the preference model are not uploaded to
StashDB. Whisparr is a separate optional integration and receives only an item you
explicitly send with **Send to Whisparr**; it is never sent automatically.

## Retention and diagnostics

Curator keeps the current and previous published model snapshots and incrementally
cleans older derived versions. Source cache, durable feedback, and event history are
retained because they rebuild the model. Profiling retains the latest 200 operation
and task traces; trace details omit SQL parameters and GraphQL variables. Disable
profiling when finished and clear saved traces explicitly when no longer needed.

Evaluation reports contain local titles and model details unless generated in
redacted mode. Keep databases, reports, exports, GraphQL payloads, credentials, real
entity IDs, and personal evaluation notes out of shared repositories.

## Backups, reset, and uninstall

The default sidecar is `{pluginDir}/data/curator.sqlite3`. Configure another path
before first use if plugin lifecycle operations may replace that directory. SQLite
needs POSIX locking that network filesystems do not provide, so the working sidecar
must stay on **local** storage; point the **Sidecar database path** at a local
directory when the plugin data directory is on a share. The **Backup Curator data**
task creates a timestamped SQLite backup via SQLite's backup API (a consistent
snapshot even in WAL mode) — that copy is the right thing to keep on a network share,
configured with the **Backup directory** setting. Copy it somewhere safe before
updates or uninstalling.

The Curator **Backups** view can restore a recognized backup. It first creates a
safety copy of the current sidecar, then invalidates the current recommendation
model; run **Rebuild recommendation model** after restoring.

Removing Curator leaves Stash-owned entities and history intact. Applied Prune tags
remain in Stash until you remove them. Deleting the sidecar discards Curator's learned
state and cannot be undone without a backup; it is never a migration repair step.
