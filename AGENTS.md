# Agent development loop

This is repository guidance for agents implementing Stash Curator changes.

## Before changing code

1. Read `docs/handover.md`, then the relevant part of `docs/design.md` or
   `docs/implementation.md`.
2. Run `git status --short` and preserve all existing user changes.
3. Trace the complete path with `rg` before editing shared code. Fix the common root
   rather than each caller.
4. Keep private Stash URLs, entity IDs, reports, databases, credentials, and
   evaluation notes out of tracked files and command output where practical.

Use `apply_patch` for edits. Prefer the existing implementation and standard library;
do not introduce a dependency or abstraction without a measured need. SQLite schema
changes always get a new ordered migration. Never edit an applied migration or reset
the sidecar to work around one.

Custom scene and performer cards must preserve Stash's native SFW Switch class
contract: `scene-card`/`performer-card`, the matching `*-card-image`, `card-section`,
and `card-section-title`. Keep usable controls outside `card-section`; the SFW Switch
blurs that section and the media while active.

## Implementation loop

1. Make the smallest complete change.
2. Add one focused regression test for non-trivial behavior.
3. Run `scripts/verify changed path/to/test_file.py` while iterating. Omit the test
   path for trivial or documentation-only changes. This formats and lints changed
   Python, checks changed plugin JavaScript, runs requested tests, and checks the diff.
4. Run `scripts/verify full` once near completion.
5. Inspect `git diff` and `git status --short` before handoff.

After a fresh checkout, or when `pyproject.toml` or `uv.lock` changes, synchronize the
environment once:

```bash
uv sync --locked
```

The verifier creates unique pytest temporary space under the workspace. Override its
location with `TMPDIR` only when needed.

Enable the repository's native pre-push verification hook once per clone:

```bash
git config core.hooksPath .githooks
```

## Required pre-push verification

Run the same checks as CI:

```bash
scripts/verify full
```

The build produces `dist/stash-curator.zip` and `dist/index.yml`; the archive test
checks that every runtime file and migration is included. `dist/` is generated and
ignored; do not add it.

For documentation-only changes, `scripts/verify changed` plus checking local links
and commands is sufficient. Do not run the full suite merely for Markdown edits.

## Installed verification

After the user updates the plugin:

1. Let migrations and any first-use backfill finish.
2. Reproduce the exact operation once for cold-start behavior and again for steady
   state.
3. Use returned `timings_ms` or stage logs rather than judging only by the spinner.
4. Check Stash logs, task progress, browser console, desktop layout, and mobile layout
   when the change touches those paths.
5. For model or ranking changes, inspect both recommendation quality and truthful
   explanations. Turn general defects into synthetic tests.

Live Stash and StashDB access is read-only unless the user explicitly asks to test
the reversible Prune-tag mutation. Curator must never delete media.

## Commit, push, and publish

Do not commit or push merely because implementation is complete.

1. Summarize changed files and verification results to the user.
2. Commit only when requested or clearly authorized for the current work package.
3. Push only after the user explicitly asks to push. Never infer push authorization
   from an earlier turn.
4. Before committing, verify the staged diff with `git diff --cached --check` and
   `git diff --cached`.
5. Use a short imperative commit subject describing the outcome.
6. Run `git push` without force. Never rewrite shared history.

A push to `main` triggers both CI and GitHub Pages. Pages rebuilds the plugin archive
and source index from `main`; once deployment finishes, the user updates Curator from
Stash's plugin manager. Do not claim an installed fix is verified until the user has
updated and the live behavior has been retested.

## Handoff format

Report briefly:

- outcome and root cause;
- files changed;
- checks run and exact result;
- commit hash only if committed;
- whether anything was pushed;
- the one next live verification step, if needed.

Leave the worktree clean only with respect to your own tracked changes. Never discard
unrelated edits or generated private data.
