---
title: Getting started
permalink: /getting-started/
---

# Getting started

Stash Curator is preview software for **Stash v0.31**. Stash must be able to run
**Python 3.12 or newer** for external raw plugins.

## Install

In Stash, open **Settings → Plugins → Available Plugins**, add this source, and refresh:

```text
https://mrx-31415.github.io/stash-curator/index.yml
```

Install **Stash Curator**, reload plugins, and use the compass in the main navigation
to open it.

## Build the first model

Select **Sync library** in Curator's toolbar. The corresponding Stash task is named
**Sync and build recommendations**. It incrementally reads metadata and history,
normalizes evidence, and publishes the first model with indexed recommendation
orders. Progress and errors appear in Curator and on Stash's Tasks page.

A full reconciliation is available as **Full sync and build recommendations** on the
Tasks page. Use it when source records were deleted or an incremental sync appears
out of date; it is not required for routine refreshes.

## Optional acceleration

Curator runs entirely on the Python standard library, and everything works without
any extra packages. Model builds get measurably faster when **numpy** is available,
so a one-shot task installs it for you:

1. In Stash, open **Tasks** and run **Install optional dependencies** once.
2. The task creates a plugin-local virtual environment and pip-installs the pinned
   requirements from `packages/curator-tools.txt` into it.
3. Then run **Sync and build recommendations** as usual.

The numpy paths accelerate the two similarity stages (content neighbors and
performer similarity), which are the largest part of a first build. Without it, the
model builder falls back to its pure-Python implementations, so skipping the task is
always safe. The venv lives in the plugin directory and survives plugin updates;
re-run the task only if the Python interpreter Stash uses for plugins changes
version.

## Configure

Curator's settings live with Stash's plugin settings. Useful early choices are:

- **Sidecar database path:** set this before first use if plugin updates or removal
  may replace the plugin data directory.
- **Results per page:** defaults to 20 for recommendations, Similar, and Expand.
- **Disable recommendation variety:** leave unchecked to avoid repeating performers,
  studios, and similar content; check it for score-first ordering.
- **Prune tag:** defaults to `[Prune]`.
- **Expand settings:** optional StashDB and Whisparr behavior.
- **Enable profiling:** keep off unless diagnosing performance.

StashDB discovery requires a configured StashDB stash-box in Stash. It is optional;
local recommendations do not depend on it.

## Refresh and update

Use **Sync library** after Stash metadata or history changes. It fetches only changed
records and refreshes recommendations when needed. Use **Rebuild model** to force a
refresh from Curator's already-synced data; it does not contact Stash. Playback and
Curator feedback already request a smaller preference rebuild, so neither command is
normally needed for them.

Stash does not give plugins a reliable background scheduler or startup hook, so
unattended syncs must call **Sync and build recommendations** through Stash's task API
from a host scheduler.

Plugin updates come from the same source URL. Back up first, update in Stash, allow
database migrations to finish, then load Curator and confirm the model is ready.

## Back up and uninstall safely

Run **Backup Curator data** from Stash's Tasks page. The timestamped SQLite backup is
written beside the sidecar. Keep a copy outside the plugin directory before an
update or uninstall if that directory may be replaced.

Removing Curator does not alter Stash-owned scenes, performers, studios, tags, or
history. A Prune tag already applied to scenes remains ordinary Stash metadata and
can be removed in Stash. See the [privacy and data lifecycle guide]({{ '/privacy/' | relative_url }}).
