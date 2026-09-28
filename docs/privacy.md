---
title: Privacy and data safety
permalink: /privacy/
---

# Privacy and data safety

Curator is local-first. A separate plugin-owned SQLite database stores the Stash
metadata needed for recommendations, viewing and feedback events, tag preferences,
recommendation history, shortlists, model versions, and explanation evidence. The
browser keeps retry queues for playback events and tag/term answers. Scene feedback
is submitted directly; check its confirmation or error before moving on.

## Stash and StashDB boundaries

Stash GraphQL remains authoritative for your library. Normal sync and recommendation
work is read-only. Curator's sole intentional Stash mutation is an explicit Prune
action that adds or removes the configured tag; it never deletes media.

StashDB discovery is optional and uses the StashDB connection and API key configured
in Stash. Using external discovery or refreshing its cache sends read-only metadata
searches for tags, performers, and scenes. Search seeds can reflect your preferences;
StashDB therefore sees which metadata is requested. Scoring happens locally. Viewing
history, feedback, learned weights, local URLs, and the preference model are not
uploaded to StashDB. Optional scheduled Expand refreshes contact StashDB without an
open browser tab.

Whisparr is a separate optional integration and receives only an item you
explicitly send with **Send to Whisparr**; it is never sent automatically.
Sending a scene also requests a release search by default, controlled by the
**Search Whisparr immediately** setting.

## Retention and diagnostics

Curator keeps the current and previous published model snapshots and incrementally
cleans older derived versions. Source cache, durable feedback, and event history are
retained because they rebuild the model. Profiling retains the latest 200 operation
and task traces; trace details omit SQL parameters and GraphQL variables. Disable
profiling when finished and clear saved traces explicitly when no longer needed.

Databases, backups, and exported reports can reveal library titles, viewing history,
and preferences. Treat them as private files. Before sharing diagnostic material,
check it for personal data, server addresses, and credentials.

## Backups, reset, and uninstall

The default sidecar is `{pluginDir}/data/curator.sqlite3`. Configure another path
before first use if plugin lifecycle operations may replace that directory. The
working SQLite database must stay on **local** storage, not NFS/SMB shares. Set
**Sidecar database path** to an absolute file path, including the filename, in a
writable local directory. For Docker, the path must exist inside the container and
use persistent storage. Changing the setting does not move existing data.

The **Backup Curator data** task creates a timestamped SQLite backup via SQLite's
backup API (a consistent
snapshot even in WAL mode) — that copy is the right thing to keep on a network share,
configured with the **Backup directory** setting. Copy it somewhere safe before
updates or uninstalling.

The Curator **Backups** view can restore a recognized backup. It first creates a
safety copy of the current sidecar, then invalidates the current recommendation
model; run **Rebuild recommendation model** after restoring.

Removing Curator leaves Stash-owned entities and history intact. Applied Prune tags
remain in Stash until you remove them. Deleting the sidecar discards Curator's learned
state and cannot be undone without a backup; it is never a migration repair step.
