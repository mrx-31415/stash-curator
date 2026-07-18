# ADR 001: Stash plugin backend runtime

Status: accepted, 2026-07-18.

## Decision

Ship Curator as a self-contained Stash plugin using the external `raw` interface.
The UI calls Stash's synchronous `runPluginOperation` mutation once per batched
interaction. Stash starts the packaged Python entry point, passes authenticated
connection context over stdin, and returns its JSON result to the UI. Long-running
sync/build/backup work uses normal plugin tasks through the same entry point.

The package contains the dependency-free `curator` Python package. SQLite lives in
`{pluginDir}/data` by default and may be moved with configuration. Each operation
migrates before use, so state survives process and Stash restarts without a daemon.

## Consequences

- no separate HTTP service, port, RPC process, or container is required;
- interactive operations must stay short and batched;
- model updates are drained on later operations or explicit jobs rather than by a
  permanently resident timer;
- the initial supported deployment requires Python 3.12+ in Stash's plugin runtime;
- plugin updates must preserve the configured data directory or database path.

This matches Stash v0.31's documented UI route API, external raw-plugin contract,
and `runPluginOperation` GraphQL operation. The UI API remains experimental, so the
supported Stash version range is declared per release.
