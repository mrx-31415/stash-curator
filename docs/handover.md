# Stash Curator handover

Updated: 2026-07-21 on `docs/showcase`.

## Current state

Curator is a working preview for Stash v0.31 with Python 3.12+. Public product,
architecture, privacy, and contributor guidance now lives in the main `docs/` pages.
Historical design and research records are retained in `docs/archive/` but are not
current guidance or part of the published site.

## Open acceptance work

- Complete the focused UI clarity round below, then replace the synthetic showcase
  illustrations with sanitized desktop captures.
- Complete installed desktop/mobile keyboard, playback, Prune, StashDB failure, and
  restart checks before calling the project 1.0-ready.
- After publishing, smoke-test every route and fetch the public `index.yml` source.

## Next work package: tab clarity and final captures

PR [#6](https://github.com/mrx-31415/stash-curator/pull/6) contains the documentation
site. Six candidate captures are in `/mnt/Misc/screenshots`, dated 2026-07-21 from
20:14 through 20:41. Review them before changing the UI.

The tab descriptions already exist in `NAV_ITEMS` in `plugin/stash-curator.js`, but
they are only exposed through `title` and `aria-label`. A user opening a tab cannot
otherwise see what the surface does. Make one small clarity pass before taking final
screenshots:

1. Render the active tab's existing description as one quiet sentence below the tab
   navigation. Reuse `laneOption.description`; do not add a tour, modal, tooltip
   system, or new configuration.
2. Add short, persistent guidance where the description is insufficient:
   - **Similar:** choose a scene or performer, then compare local Library or external
     StashDB results.
   - **Expand:** results are external metadata candidates scored locally; explain
     that a **Wildcard** was selected outside preference-derived seeds.
   - **Prune:** Curator never deletes media, tagging is reversible, and Candidates,
     Explicit dislikes, and Model suspects are different review queues.
3. Clarify near recommendation cards that the colored corner icon identifies the
   source lane and that **Score** is ranking utility, not a probability. Keep this
   compact; the existing **Why this?** disclosure owns the detail.

Touch only `plugin/stash-curator.js`, `plugin/stash-curator.css`, and one focused
runtime/UI assertion in `tests/plugin/test_runtime.py` unless the installed behavior
proves a shared component must change. Run
`scripts/verify changed tests/plugin/test_runtime.py`, then check desktop, tablet,
and narrow mobile widths with keyboard focus and no horizontal overflow.

### Capture review

- `20.14.54` shows Curator mounted three times. Do not publish it. Later captures
  show one instance, so treat it as stale unless the duplication is reproducible; a
  reproducible duplicate mount blocks the documentation capture round.
- `20.38.21` is the best recommendation overview. Retake it with one **Why this?**
  panel open and useful Appeal, Current Fit, or confidence evidence visible.
- `20.38.38` is the Discover capture. Retake it with one explanation open that names
  the familiar anchor and the challenged boundary.
- `20.39.03` is the Expand capture, but it exposes real-looking titles, performers,
  studios, tags, and a refresh timestamp. Replace those with synthetic data rather
  than blurring all explanatory text.
- `20.41.18` is the Similar capture, but its reference image and metadata identify a
  real person and scene. It is not publishable; use a fully synthetic reference.
- `20.41.49` is the strongest Prune capture. Retake it after adding the reversible,
  no-deletion guidance.

Produce five final desktop images for the existing assets: recommendations,
Discover, Expand, Similar, and Prune. Use generic titles and abstract or blurred
media; include no real people, studios, tags, URLs, IDs, timestamps, or library facts.
Preserve the useful alt-text intent already present in `docs/index.md`. The site is
responsive, but separate mobile showcase images are not needed.

## Guardrails

Never delete or reset a sidecar to solve migration trouble. Never commit private
library data, IDs, credentials, reports, or evaluation notes. Curator's only Stash
mutation is explicit, reversible Prune tagging; StashDB access stays read-only.
