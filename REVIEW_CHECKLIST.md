# Curator plugin — review checklist (living doc)

Consolidated from two independent review passes against the live instance
(`http://192.168.1.100:9999/plugins/stash-curator`), cross-checked against the
design mockup (`https://claude.ai/code/artifact/0e341da5-9b63-4ffc-ac60-05ee0df6174a`)
and, for pass 2, against this worktree at commit `78da835` (round 13,
`feat/plugin-visual-overhaul`). Tracks GH issue #152 (follow-up to #150);
Settings-in-Manage is deliberately out of scope here, tracked as #151.

Tick items off as they land. Add new findings at the bottom of the relevant
section rather than renumbering, so this stays a stable reference.

Artifacts:
- Pass 1 (mockup-fidelity): `/tmp/curator-review/` — `HANDOVER.md`, cached
  `mockup.html`, live bundle snapshot as of that pass, ~45 screenshots.
- Pass 2 (critical UX audit): `/tmp/curator-review2/` — screenshots + probe
  scripts, including `lane_bug_clean.py` / `lane_bug_directurl.py` /
  `lane_bug_fromrevisit.py` which reproduce the lane-switch bug below.

---

## Critical / high severity

- [x] **Recommendations lane switching broken for Revisit/Discover/Adventure
      when clicked in-app.** Investigated end-to-end (element-level and
      document-capture-phase event listeners, `history.pushState`
      instrumentation, temporary logging inside the real `openView` source,
      direct GraphQL calls, and a real-click DOM diff of rendered scene IDs).
      **Not a real bug — two independent test artifacts in the two repro
      scripts:**
      1. Revisit/Discover/Best Bets: `lane_bug_clean.py` (and this doc's own
         repro list) locate the lane card with
         `.curator-lane-card:has-text('Revisit')` etc. — Playwright's
         `:has-text()` is a case-insensitive **substring** match against the
         full element text, and "For You"'s own description ("...timely
         **revisits**, and a little **discovery**.") contains "revisits" and
         "discovery" as substrings. `.first` silently resolved to the wrong
         card (For You) instead of the intended lane. Re-run with precise
         `page.get_by_text(lane, exact=True)` locators: all three switch
         correctly (Best Bets 23908→5442, Revisit 23908→130, Discover
         23908→14054).
      2. Adventure: the repro's correctness oracle was the "N in rotation"
         count text, which is the lane's *eligible candidate pool size*, not
         its result set. In this dataset Adventure's pool happens to be
         identical to For You's (23908, both draw from nearly the whole
         library) purely by data coincidence, so the count didn't move even
         though the click worked. Verified directly: `get_slate` for
         `adventure` returns a completely different, correctly-ranked item
         set (1/20 scene-ID overlap with `for_you`, distinct `appeal`
         scores), and a real Playwright click swaps the rendered scene cards
         (1/20 overlap) and updates the URL to `?view=adventure` — all
         correctly.
      No application code changed. Removed the temporary `console.log`
      debug lines added to `openView` during this investigation and
      redeployed the clean build to both the live instance and the local
      test instance.
- [x] **Primary-button text contrast fails WCAG AA in dark theme (the
      default).** Root cause: `--curator-gradient-brand` (dark theme:
      `linear-gradient(145deg, #4f8ce0, #6cc4dc)`, driven by
      `--curator-accent`/`--curator-hue-similar`) paired with `color: #fff`
      measured **3.41:1** at the dark end, **1.99:1** at the light end — both
      fail 4.5:1. This affects every `.btn-primary` in dark theme, whether
      `variant="primary"` is explicit (Curate Left/Right, Submit picks,
      Generate) or an omitted-prop Bootstrap default (pagination, Copy
      StashDB ID, Profiling buttons, etc.) — same root cause either way, so
      fixed once at the token instead of auditing ~26+ call sites and
      guessing which were meant to read as the "one true primary action" per
      screen (many, like the Curate pick buttons, legitimately are).
      **Fix**: `--curator-gradient-brand` now uses literal `#1d5fb8`/
      `#1f7f96` — the same darker blue/teal already used as light theme's
      accent/hue-similar (measured 6.21:1/4.63:1, both pass AA) — reused as
      dark-theme-only literals so the vivid `--curator-accent`/
      `--curator-hue-similar` tokens (lane-hue dots, focus rings, etc.) are
      untouched. Verified via computed-style dump against the live instance
      (`getComputedStyle` on every `.curator-page .btn-primary`, confirmed
      `rgb(29, 95, 184)`/`rgb(31, 127, 150)` site-wide) and visually via
      screenshot on Recommendations and Curate. The JS-side button-variant
      *consistency* items below (icon-button reconciliation, Save
      unification, dropping mismatched icons) are separate, still open —
      this item was specifically the AA contrast failure.

## Sliders

- [x] **All 4 sliders render as plain unstyled native browser range inputs**
      (Taste Profile sentiment, Similar/Expand "Minimum match", Prune
      "aggressiveness", Sentiment-review "Appeal ≤" threshold). Root cause
      was broader than the sentiment slider's own specificity fight: Stash's
      global `input[type="range"]` base rule *and* its
      `::-webkit-slider-thumb`/`::-webkit-slider-runnable-track` pseudo-
      element rules all beat a bare `.curator-sentiment-range` class — and
      critically, curator's CSS never had `::-webkit-slider-runnable-track`/
      `::-moz-range-track` rules at all (only a base `background` that
      WebKit ignores for track rendering), so the intended thin bordered
      track never rendered in Chrome/Safari even before the specificity
      question. The other 3 sliders (Minimum match, Prune aggressiveness,
      Appeal ≤ threshold) had zero color/track/thumb styling of their own —
      only `width`.
      **Fix**: introduced a shared `.curator-page .curator-range` class
      (opt-in via `className="curator-range"`) covering base/track/thumb for
      both WebKit and Gecko, applied to all 4 sliders. Thumb color reads
      `var(--sc, var(--curator-accent))` so the sentiment slider's existing
      tier-color wrapper (`--sc`) recolors it for free with no separate
      override rule. Verified via computed-style dump (confirms Stash's
      rules no longer win) and screenshots of all 4 sliders in both themes.
- [x] **Taste Profile slider shows unrated items as already-filled** (~60%
      blue) — resolved as a side effect of the fix above: the "filled" look
      was Stash's own saturated `rgb(0,123,255)` track color rendering
      identically regardless of value/rated-state (native range tracks don't
      show a filled/unfilled split), combined with the unrated default
      thumb position (stop 3 of 5, i.e. ~60%). Now that curator's own neutral
      `--curator-border-strong` track and dimmed (`opacity: 0.45`,
      previously inert) unrated thumb actually render, an unrated slider
      reads as neutral/unanswered rather than pre-filled — confirmed via
      screenshot.

## Buttons / icons

- [x] Add explicit `variant` to the ~26 buttons currently defaulting to
      Bootstrap `primary`. Audited every `React.createElement(Button, ...)`
      call site without an explicit `variant`. Kept `primary` only where a
      screen genuinely has one true CTA (Curate's pick buttons and Submit,
      the first-run "Sync and build recommendations", Search, Create
      backup, Apply, Generate) — assigned `secondary` to utility/navigation
      buttons (pagination Previous/Next, Profiling/Diagnostics Refresh/View/
      Download/Copy/Export/Back-to-root, the filter-bar Save, the "minimal"
      ExternalCard tag/performer/studio count popover trigger, which turned
      out to have the same bug: no explicit variant meant `.btn-primary`'s
      gradient — at higher specificity than Stash's own `.minimal` reset —
      painted over what should read as a plain ghost trigger) and `link` to
      Curate's "More" dropdown-menu items (Not now/Never show/Metadata is
      wrong/Mark for pruning, previously solid primary blocks stacked in a
      small popover).
- [x] Reconcile the two parallel icon-button patterns:
      `.curator-icon-button` (header sync/rebuild/theme/settings) vs.
      `.curator-icon-action` (ExternalCard's row). "Copy StashDB ID" and
      "Show this performer's scenes" had no explicit variant (defaulting to
      bright-blue primary) while their siblings were explicitly secondary/
      state-toggled — now `variant: "secondary"` on both, consistent with
      "Open on StashDB" and the unselected state of "Add to shortlist"/
      "Rate tags & terms". Verified via screenshot on Expand results.
- [x] Unify the two "Save" button treatments: feedback-history's inline
      replace-row Save stays `variant="link"` (correct for a compact table-
      row micro-action alongside its "Undo" sibling); the filter-bar Save
      changed from an implicit solid-primary default to explicit
      `variant="secondary"` — neither now competes with each screen's real
      primary action (Apply/Submit), even though the two treatments still
      differ in weight (link vs. bordered button) since they sit in
      genuinely different-density contexts.
- [x] Drop the icon on **"Hide exact PHash matches"** toggle (Similar).
- [x] Drop the icon on **"Local"** (include-owned) toggle. Removed the
      now-unused `faUserCheck` import.
- [ ] Redesign the **ExternalCard action row** (5 icon-only buttons —
      external-link, copy-ID, shortlist, rate-tags, refresh-Whisparr — on
      every Similar/Expand/Hunt result card, 20+ per page): no labels, same
      size/weight, requires hovering each to learn what it does. Recommend
      collapsing to 2 visible actions + an overflow ("⋯") menu, or labeling
      the most-used 1–2.

## Other bugs / quirks

- [ ] **Manage page height still unbounded** — round 11's sticky section list
      stops the scroll-to-top pain on desktop, but the document itself is
      still ~76,700px tall (Taste Profile renders all 949 tags unpaginated/
      unvirtualized) and **worse on mobile at ~142,000px**, where
      `@media (max-width:860px) { .curator-manage-list { position: static } }`
      explicitly disables the sticky list — mobile users lose the section
      rail entirely while scrolling. Fixes the symptom, not the cause;
      consider pagination/virtualization on Taste Profile instead (see UX
      suggestions).
- [x] **Raw enum leak regression**: Manage → Recently Recommended's "Lane"
      column showed `score_review` verbatim for Sentiment-review-sourced
      rows. `RecommendationHistoryRow` had its own separate lane→label
      lookup (`laneByValue.get(item.lane)?.label || item.lane`) that never
      got the `score_review` → "Sentiment review" special case already
      applied elsewhere (e.g. the Sentiment-review card badge) — added it
      here too. Verified via screenshot.
- [x] **"Reason shown" column is dead** — not actually dead: every row
      showing the literal string "Lane" was `reasonLabel()`'s naive fallback
      (last dot-segment, title-cased) mangling `"eligibility.lane"`, the
      baseline reason code every impression gets seeded with regardless of
      lane (`core/slate.go`, `slate_greedy.go`, `score_review.go` all start
      `reasonIDs` with it; richer reasons like `appeal.performer_identity`
      are appended when they apply, but plenty of items have nothing beyond
      the baseline). Added `"eligibility.lane": "Eligible for this lane"` to
      the existing label map, same pattern as the other two entries.
      Verified via screenshot — column now reads sensibly on every row.
- [ ] **No loading affordance for slow async actions** (systemic gap, not
      just Curate): Generate has 4–8s of dead air (confirmed ~8s GraphQL
      round-trip via network trace) with only a subtly-dimmed button; Expand's
      candidate list is blank for up to 10s with zero spinner/skeleton. Reads
      as frozen, not slow.
- [x] **MATCH bar clips/misrepresents scores >1.0** — `utilityBar()` clamped
      fill to `[0, 1]`, so any overflow above 1.0 (final_utility can exceed
      1.0 via bonuses like uncovered-content) rendered at the same ~100%
      width as a plain 0.95. Rescaled against a wider ceiling (1.2) so that
      range is visible, with a distinct striped treatment for the rare case
      that still exceeds it. Verified on live data: 1.171/1.160/1.154/1.140
      now render at 98%/97%/96%/95% vs. 0.95's 79% — clearly distinguishable
      (previously all ≈100%).
- [x] **Sentiment badges carry no color signal** — reused the existing
      sentiment-tier classes (`.curator-sentiment-love`/`-danger`/`-neutral`,
      which already set `--sc`) on the badge instead of Bootstrap's
      `badge-info`, plus one small CSS rule giving `.badge` context a tinted
      background/border/text from `--sc` (those classes previously only had
      a button treatment: transparent fill, border-only). Like now reads
      green, dislike red, unsure gray — no new design work, per the UX
      suggestion below. Verified via screenshot.
- [ ] **Mobile primary nav hides 5 of 6 tabs off-screen with no affordance** —
      `.curator-tabs` is horizontally scrollable with the scrollbar hidden and
      no fade/chevron hint; only "Recommendations" is visible on load at a
      420px viewport.
- [ ] **Prune still shows plain text** ("Appeal −0.94 · confidence 0.99")
      where Recommendations/Sentiment review show a MATCH bar for the same
      underlying data — cross-surface inconsistency.
- [ ] **No inline sentiment slider on the Curate pair-comparison screen** —
      mockup has a rate-strip directly under the pair; live only exposes tag
      sentiment via the separate Taste Profile panel. (Old handover #6,
      confirmed still open — deliberately deferred pending discussion per
      prior triage.)
- [ ] **Curate's "Pick-test a hypothesis" list renders empty on first paint**
      with no loading/empty-state messaging, looks broken before it
      populates.
- [ ] Similar's free-text scene search results render as a bare, unstyled
      inline list of link-colored text — no card/border/container, visually
      inconsistent with the app's card-heavy aesthetic elsewhere.
- [ ] Minor: Backups' directory path uses an alarm-colored magenta/pink
      `curator-mono` style for what's just informational text.

## UX suggestions (independent judgment, not defects — discuss before building)

- [ ] Move **Profiling** out of the primary Manage nav rail behind a debug
      flag / `?debug=1` — it exposes raw `.pprof` CPU-trace downloads, which
      reads as developer tooling leaking into end-user navigation.
- [x] Color-code sentiment badges using the sentiment-tier color system the
      slider thumb already has (`--sc` custom property) — done, see the
      "Other bugs / quirks" entry above.
- [ ] Add pagination or virtualization to Taste Profile (fixes the Manage
      height problem at the root).
- [ ] Add loading skeletons for lane switches and Curate generation.
- [ ] Add empty-state copy to Curate's hypothesis list explaining the blank
      state instead of leaving it silent.

## Deliberately out of scope (tracked elsewhere — listed for completeness)

- [ ] Settings panel in Manage — tracked as issue #151, not #152. Gear icon
      intentionally routes to Stash's native `/settings?tab=plugins`.

## Already fixed — verified in pass 2, no action needed

- [x] Recommendations was missing a filter bar entirely — now has full
      Score-first/Filters/Saved filters/Save/tag-performer-studio filters.
- [x] Backups/Feedback history used plain HTML tables — now proper icon+
      title+meta record-row styling.
- [x] Theme toggle didn't re-theme scene/performer cards — now confirmed
      light theme properly re-themes them (round 13 commit).
- [x] `Api.components.HoverPopover` cold-load fragility — health pill popover
      confirmed working on true cold direct navigation, zero console errors.
