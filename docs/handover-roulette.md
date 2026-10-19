# Roulette implementation handoff

Branch: `prototype/roulette`. This handoff accompanies the completed implementation
and local installation. The branch has not been pushed.

## Delivered behavior

- Roulette launches from the current recommendation lane and keeps its filters,
  mood, and recommendation provenance when fetching more contenders.
- Large rectangular 16:9 cards move around the wheel's visible upper arc. The
  winning card expands into Stash's native player, retaining the same media element
  through reveal and return animations.
- Next and natural completion start another spin. Back restores an earlier pick's
  saved position. Rounds continue automatically, avoiding an immediate repeat when
  another eligible scene exists. A single eligible scene can play again.
- Mute persists locally; fullscreen includes Roulette controls. Controls fade
  during playback and wake on pointer, touch, or keyboard activity. Exit cancels
  pending work and restores focus. Reduced motion skips the animations.
- Playback observations use the existing event tracker, including recommendation
  provenance and natural completion. No backend or schema changes were needed.

## Files for review

- `plugin/stash-curator.js`: session selection, pagination, native playback,
  transitions, and embedded-player event tracking.
- `plugin/stash-curator.css`: responsive wheel, native player sizing, and controls.
- `docs/using-curator.md`: current public behavior.
- `tests/plugin/test_roulette.cjs` and its pytest wrapper: selection, lane scope,
  replenishment, provenance, retries, continuous rounds, and cancellation.
- `tests/integration/test_roulette.py` and `tests/integration/fixtures/`: six native
  browser scenarios using synthetic media and blocking live mutations.

The original [interaction prototype](prototypes/roulette/README.md) remains a
reference artifact. Its session exhaustion and wedge descriptions predate the
implemented continuous rounds and rectangular cards; use the public guide for
current behavior. Preserve its existing files when preparing the commit.

## Verification

- Focused Roulette test: passed.
- Native browser suite: all six scenarios passed, including plugin composition,
  transitions, mobile layout, retries, natural completion, and cancellation.
- Full verifier: lint, formatting, type checks, Go checks, packaging, and all 751
  unit tests passed. The performance gate failed only `feature_validation`:
  522 ms against a 508 ms budget. No performance baseline was changed.
- The installed archive's 11 runtime files match the build, including current
  JavaScript and CSS.
- Installed-code smoke tests with real library videos passed on desktop and
  mobile emulation, on first launch and reopening: playback, Next, Back with saved
  position, mute, fullscreen, exit, and focus restoration. All GraphQL mutations
  were intercepted and playback observations remained in the browser. The smoke
  launcher supplied contenders locally, so this does not verify live lane writes.
- A real video reaching its end advanced to another pick and produced a natural
  completion observation. Native activity writes were intercepted in this check.

## Remaining acceptance

Check touch playback, device rotation, and fullscreen on a physical phone. Mobile
emulation cannot establish platform-specific browser behavior. The performance
gate also remains red as recorded above.

Implementation commit subject: `feat: add continuous recommendation roulette`.
Push still requires explicit instruction.
