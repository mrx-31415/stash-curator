# Roulette interaction prototype

Serve this directory, then open the printed URL:

```bash
python3 -m http.server 8765 --directory docs/prototypes/roulette
```

Standalone HTML, CSS, and JavaScript; no build, external runtime requests, or Stash
connection. Sample photographs are from Lorem Picsum / Unsplash. Each photograph
has a matching generated ten-second silent zoom clip; these are interaction
fixtures, not recommendations from your library.

Try Roulette, Next, Back, fullscreen, mute, and letting a clip end. Best Bets and
Revisit have smaller sample pools to exercise lane scoping. Play lane demonstrates
sequential playback without spinning. Exit and Escape cancel an in-progress spin.
Mute is remembered locally. Reduced motion replaces spinning and zooming with a
direct reveal. Selected scenes do not repeat until you explicitly restart.

The larger, open-centre wheel shows up to twenty-four remaining contenders
(sixteen on narrow screens), with a gentle camera push toward the pointer.
Selection has a mild rank weighting to favour surprise. First entry spins for
3.8 seconds; subsequent spins take 2.6 seconds, with fewer rotations and gentle
acceleration and deceleration. The winning segment becomes the playing video:
its crop, position, and outline reshape into the player over 1.3 seconds
while playback runs. The rest of the wheel retreats behind it; no image overlay,
crossfade, or player swap is used.
Thumbnails have a fixed orientation within each slot, chosen so any slot is
upright at the pointer. They never rotate independently, including at the stop.
Next folds the current video back into its original slot before
starting the next spin; Back still returns directly to the saved playback position.
The wheel keeps its slots across spins. The returned pick holds its final video
frame, and candidates are not reshuffled while the wheel is stationary. If more
unplayed candidates are waiting off-wheel, they replace spent slots after rotation
begins; the current pick's slot is protected. Already selected tiles remain visible
as context but cannot win again in the session.

Run the browser self-check with Python and Playwright installed:

```bash
python3 docs/prototypes/roulette/smoke.py
```

Screenshots go to `/tmp/curator-roulette-preview/`. Native Stash player integration,
real recommendation pagination, and platform-specific fullscreen behaviour remain
implementation work. Nothing in this directory is included in the plugin runtime.
