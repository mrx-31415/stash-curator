---
title: Getting started
permalink: /getting-started/
---

# Getting started

Stash Curator is preview software for **Stash v0.31**. Start with a library already
scanned into Stash. Curator reads its metadata; it does not scan your media files.

Curator can build local recommendations from your library metadata. StashDB is not
required; viewing history and feedback make the model more personal over time.

## Before installing

- **Python** must be available as `python` where Stash runs to start the launcher. For Docker,
  that means inside the Stash container, not just on the host. Check with
  `python --version` in that environment.
- Supported platforms are **Linux x86-64/ARM64**, **macOS Intel/Apple silicon**, and
  **Windows x86-64**. The plugin includes the matching compiled backend; you do not
  need Go or Python packages.
- Curator needs writable, persistent **local storage** for its database and model
  files. If Stash's plugin directory is on an NFS/SMB share, configure a local
  database path before opening Curator or starting a task (see below).

## Install

In Stash, open **Settings → Plugins → Available Plugins**, add this source, and refresh:

```text
https://mrx-31415.github.io/stash-curator/index.yml
```

Install **Stash Curator**, reload plugins, then refresh the browser page. Curator
appears as a compass in Stash's main navigation.
See [Stash's plugin guide](https://docs.stashapp.cc/in-app-manual/plugins/)
if you are adding a plugin source for the first time.

### Smaller downloads

For a smaller download, use a platform-specific plugin source below instead of
the regular source. Each source offers the same Curator plugin and version, with
just the matching backend binary.
Choose the platform where **Stash runs**; for Docker, use the container's Linux
architecture, even when the host is Windows or macOS.

| Stash platform | Plugin source | Release archive |
| --- | --- | --- |
| Linux x86-64 | [index-linux-amd64.yml](https://mrx-31415.github.io/stash-curator/index-linux-amd64.yml) | `stash-curator-linux-amd64.zip` |
| Linux ARM64 | [index-linux-arm64.yml](https://mrx-31415.github.io/stash-curator/index-linux-arm64.yml) | `stash-curator-linux-arm64.zip` |
| Windows x86-64 | [index-windows-amd64.yml](https://mrx-31415.github.io/stash-curator/index-windows-amd64.yml) | `stash-curator-windows-amd64.zip` |
| macOS Intel | [index-darwin-amd64.yml](https://mrx-31415.github.io/stash-curator/index-darwin-amd64.yml) | `stash-curator-darwin-amd64.zip` |
| macOS Apple silicon | [index-darwin-arm64.yml](https://mrx-31415.github.io/stash-curator/index-darwin-arm64.yml) | `stash-curator-darwin-arm64.zip` |
| All supported platforms | [index.yml](https://mrx-31415.github.io/stash-curator/index.yml) | `stash-curator.zip` |

Use one Curator source at a time. When switching an existing installation, keep
the source's **Local Path** unchanged so Stash updates the existing plugin folder
and retains its data. Back up the folder before switching.

For manual installation, download the matching ZIP from the
[latest release](https://github.com/mrx-31415/stash-curator/releases/latest).
Extract it into a `stash-curator` folder inside Stash's configured plugins directory,
then reload plugins and refresh your browser. On Linux and macOS, ensure the
`curator-core-*` binary has execute permission. When updating an existing manual
installation, stop Stash first, back up the plugin folder, and preserve its `data/`
directory. The regular plugin source continues to provide the multi-platform ZIP.

The default database is `{pluginDir}/data/curator.sqlite3`. To use another location,
open Stash's plugin settings for Curator and set **Sidecar database path** to an
absolute **file path**, for example `/curator-data/curator.sqlite3`. The directory
must be writable by Stash. In Docker, use a path inside the container backed by a
persistent local volume or bind mount. Changing this setting later opens a different
database; it does not move your existing Curator data.

To hide Curator's ratings/confidence badges on Stash scene and performer cards,
enable **Manage → Settings → Page settings → Hide card ratings and confidence**.
This updates the card display immediately. The same option is available in Stash's
Curator plugin settings; refresh the browser after changing it there.

## Build the first model

Open Curator and select **Sync and build recommendations** in the setup checklist.
You can also run it from Curator's **Manage → Tasks** page (the wrench opens Manage)
or Stash's plugin tasks. It reads your library metadata and history and builds the
first recommendation model. Progress and errors appear under **Manage → Tasks**.

A full reconciliation is available as **Full sync and build recommendations** on the
Tasks page. Use it when source records were deleted or an incremental sync appears
out of date; it is not required for routine refreshes.

The first sync and model build may take several minutes on a large library and can
use significant CPU, memory, and disk space. Leave the Stash task running until
Curator reports **Ready**. Then open **Recommendations → For You** to browse. If setup
fails, open **Manage → Tasks**, read the failed task's error, correct the problem,
and retry. Do not delete the database to fix a failed sync or migration.

When the model is ready, [choose a recommendation lane]({{ '/using-curator/' | relative_url }}#choose-a-lane).

## Choose the right refresh

| Action | Use it when | Contacts Stash? |
| --- | --- | --- |
| **Sync and build recommendations** | Stash metadata or viewing history changed | Yes, then rebuilds if needed |
| **Full sync and build recommendations** | Records were deleted or incremental sync is stale | Yes, reads the complete library |
| **Rebuild recommendation model** | You changed Curator settings or want to rebuild synced data | Only to import queued entity changes |
| **Apply recent Curator feedback** | You want to publish queued playback or feedback sooner | Only to import queued entity changes |
| **Refresh Expand cache** | You want new StashDB candidates | Stash and StashDB |

## Configure

Curator's settings live with Stash's plugin settings; common options are also in
Curator's **Manage → Settings**. Useful early choices are:

- **Backup directory:** where **Backup Curator data** writes timestamped snapshots.
  Leave empty to write beside the sidecar. A network share is a fine place for
  backups — it is the *working* database that must stay local.
- **Results per page:** defaults to 20 for recommendations, Similar, and Expand.
- **Disable recommendation variety:** leave unchecked to avoid repeating performers,
  studios, and similar content; check it for score-first ordering.
- **Prune tag:** defaults to `[Prune]`.
- **Expand settings:** optional StashDB and Whisparr behavior.
- **External performer gender:** defaults to Female. Choose All genders in
  **Manage → Settings** to remove this discovery filter.
- **Enable profiling:** keep off unless diagnosing performance.

For optional external discovery, configure a stash-box in Stash with its endpoint and
API key. Curator uses StashDB (`https://stashdb.org/graphql`) by default. A different
endpoint must provide a GraphQL API compatible with StashDB's queries. To use a
different configured stash-box, select it from the dropdown under **Manage → Settings →
Discovery → Stash-box endpoint**. Run **Refresh Expand cache** under **Manage → Tasks** to
populate discovery results. Expand uses a recent-release window (90 days by default),
so it does not search the entire external catalog. Use **Find → Performer Hunt** for
one performer's catalog. Local recommendations do not require an external account.

After changing the endpoint, opening Expand automatically prepares candidates from
the selected server. Previous-server candidates stay hidden during preparation;
saved shortlist entries are preserved and shown when their source is selected.
Existing shortlist entries belong to StashDB. Progress appears under **Manage → Tasks**.

Some providers expose only partial Stash-box compatibility. ThePornDB's GraphQL
interface is not supported for Expand yet; its discovery queries and taxonomy differ
from Stash-box. ThePornDB REST support is planned separately. FansDB's discovery
queries have been checked live; JAVStash's schema is compatible, but authenticated
discovery results have not yet been verified.

Whisparr v3 is also optional. Configure its URL and API key only if you want the
explicit **Send to Whisparr** action on external scene cards. Curator sends an item
only when the StashDB endpoint is selected; other endpoints disable this action.
You must select the action explicitly. **Search Whisparr immediately** is enabled by
default, so sending a scene also requests a release search. The URL must be
reachable from the Stash server or container.

## Refresh and update

Run **Sync and build recommendations** from **Manage → Tasks** after Stash metadata
or history changes. It fetches changed records and refreshes recommendations when
needed. **Rebuild recommendation model** uses Curator's already-synced data and
imports any entity changes queued by Stash hooks, without running a library sync.
Playback and Curator feedback request a smaller preference rebuild automatically. Those updates
are batched, so a recommendation may not change immediately after one action. Use
**Apply recent Curator feedback** when you want to publish pending changes now.

Enable **Automatic background tasks** to let Curator's persistent worker apply pending
model updates and sync recent plays without an open browser tab. **Scheduled Expand
refresh**, **Scheduled sync and build**, and **Scheduled backup** are optional and off
by default; configure their timing in plugin settings. Check worker status and job
progress under **Manage → Tasks**.

Plugin updates come from the same source URL. Back up first, update in Stash, allow
database migrations to finish, then load Curator and confirm the model is ready.

## Back up and uninstall safely

Run **Backup Curator data** from Stash's Tasks page. The timestamped SQLite backup is
written beside the sidecar, or into the configured **Backup directory**. The backup
uses SQLite's backup API, so it is a consistent snapshot even while the sidecar is
in WAL mode — safe to keep on a network share. Keep a copy outside the plugin
directory before an update or uninstall if that directory may be replaced.

If your plugin data directory lives on a network share, the recommended layout is
two paths: **Sidecar database path** on local storage and **Backup directory** on
the share. A live WAL database must never be file-copied while Stash is running; restore only
through the Curator **Backups** view, which uses the backup API and validates the
snapshot first.

The Curator **Backups** view can also create, restore, and delete recognized backups.
Restoring first creates a safety copy of the current sidecar, then invalidates the
current recommendation model. Run **Rebuild recommendation model** after restoring.

Removing Curator does not alter Stash-owned scenes, performers, studios, tags, or
history. A Prune tag already applied to scenes remains ordinary Stash metadata and
can be removed in Stash. See the [privacy and data lifecycle guide]({{ '/privacy/' | relative_url }}).

## If Curator does not start

- If Stash cannot find `python`, make Python available in Stash's runtime environment.
- If the error says **no curator-core binary for this platform**, check the supported
  platforms above and reinstall from the plugin source. The plugin directory must
  allow executable files.
- For database permission or locking errors, check that the configured path names a
  file on writable local storage, visible inside the container if you use Docker.
- If the compass is missing after installation, reload plugins and refresh the
  browser. Check Stash's logs if it still does not appear.
