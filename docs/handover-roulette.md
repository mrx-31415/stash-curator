# Roulette implementation handoff

Branch: `prototype/roulette`. Targets current `main`; the standalone
[prototype](prototypes/roulette/README.md) remains an interaction reference.
The [public guide](using-curator.md#roulette) describes the final behavior.

## Delivered behavior

- Launch from a recommendation lane with its filters, mood, and provenance.
  Rank-weighted picks continue across fetched batches and automatically start
  another round once all eligible scenes have been selected. Avoid immediate
  repeats when an alternative exists; a single eligible scene can repeat.
- Visible lane cards gather into a large rectangular-card wheel. The winner
  pulses and expands into Stash's native ScenePlayer. The wheel and felt fade
  completely to the player's black background; simple mode keeps letterboxing
  consistent throughout its short fade.
- Next and natural completion continue the session. Back restores a previous
  pick and its saved playback position. The same native media element stays
  mounted during reveal and return.
- Native ratings, O counter, Useful/Not for me, and Open scene are available.
  Native activity tracking retains play duration, resume position, and play count;
  Curator observations retain lane provenance and natural completion.
- Animate roulette is available in Manage → Settings → Playback and a small
  in-player gear menu. Both controls share a browser-local preference, default on,
  with cross-tab synchronization and an in-memory fallback if storage fails.
  Changes apply to the next pick. Off skips wheel effects and sounds and uses
  a 220 ms fade. Reduced motion also suppresses the fade.
- Mute persists locally. Fullscreen includes the controls; overlays hide and wake
  with activity. An open settings dropdown stays visible. Exit, errors, hidden
  tabs, and moving between picks stop sound tails and cancel pending work.
- Sound uses CC0 recordings for the card shuffle, textured rise, and a heavy
  slam with chip accent and four-second room decay. The rise follows actual
  wheel progress through landing. Audio remains embedded PCM with no runtime
  requests or codec initialization. Source licenses, checksums, and reproducible
  edits are in [the asset notes](assets/roulette-card-shuffle.md),
  [rise note](assets/roulette-cinematic-sound.md), and
  [landing note](assets/roulette-casino-slam.md).

## Implementation and scope

Frontend session/ranking, player integration, preferences, and effects are in
`plugin/stash-curator.js`; presentation is in `plugin/stash-curator.css`.
Tests are in `tests/plugin/test_roulette.cjs`, its pytest wrapper, and
`tests/integration/test_roulette.py` with synthetic media fixtures.
Shared Feedback supports a compact form without removing its existing card flow.
No backend, database schema, plugin manifest, or runtime dependency is added.

SVG card bounds come from getBBox plus the composed screen transform, avoiding
Firefox's inflated intermediate rotation bounds. Native thumbnail padding is
removed from the wheel SVG so the highlight and player expansion align.
Native player initialization cannot restore a stale mute preference during a
reveal; once playing, native mute controls synchronize back into Roulette.

## Verification before PR preparation

- The full repository gate passed during implementation: lint, format, typing,
  Go checks, packaging, 751 unit tests, and the performance budget. An earlier
  performance failure was resolved by rerunning without competing browser work;
  no baseline was changed.
- Subsequent frontend changes passed 52 plugin checks and all 13 then-existing
  native browser scenarios. The final fade correction passed its three focused
  cases, including the new simple-mode regression (14 total browser scenarios).
- Coverage includes selection, pagination, scope/provenance, continuous rounds,
  history, native statistics/actions, sound rendering and decay, mute/visibility,
  settings synchronization and persistence, geometry, and cancellation.
- Native Stash tests intercept every GraphQL mutation and keep Curator events
  in-browser. Synthetic fixture IDs and media isolate library data.
- The installed archive's 11 runtime files matched tested JavaScript and CSS.

PR preparation will record fresh post-rebase verification below. Physical Firefox
mobile touch, rotation, and platform fullscreen acceptance remains a manual check;
desktop/mobile emulation and the user's installed listening/visual passes do not
cover every device behavior.

## PR preparation

Rebased cleanly onto main at `33c8ddf` (0.40.5). A recovery branch preserves the
pre-rebase commits. Roulette runtime and native-browser tests are byte-identical
across the rebase. Fresh Go, lint, formatting, type, archive, and syntax checks
passed. The full unit run passed 764 tests and exposed one isolated SettingsPanel
fixture missing the new RouletteAnimationSetting component; adding its component
stub fixed that fixture, and all 53 focused plugin checks then passed. The PR's
validation notes record the final performance result. No performance baseline
was changed, and live Stash writes remain outside verification scope.
