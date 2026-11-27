const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.css"), "utf8");
const context = { React: { createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }) } };
vm.runInNewContext(source.slice(source.indexOf("  // How much of the wait until the next rolling-search round"), source.indexOf("  function whisparrRotationStatus(")), context);

const rotation = { interval_ms: 900000, next_sweep_at_ms: 1_000_000 + 450000 };
assert.equal(context.whisparrRoundLeft(rotation, 1_000_000), 0.5);
assert.equal(context.whisparrRoundLeft(rotation, 1_000_000 + 900000), 0, "an overdue round has nothing left");
assert.equal(context.whisparrRoundLeft({ ...rotation, next_sweep_at_ms: 1_000_000 + 2_000_000 }, 1_000_000), 1, "capped at a full ring");
assert.equal(context.whisparrRoundLeft({ interval_ms: 0, next_sweep_at_ms: 5 }, 0), 0);
const ring = context.WhisparrCountdown({ rotation, now: 1_000_000 });
assert.equal(ring.children[1].props.strokeDashoffset, 50);

// The send button and the badge show what just happened.
const actions = source.slice(source.indexOf("  function ExternalActions("), source.indexOf("  function WhisparrBadge("));
assert.match(actions, /whisparr\?\.status === "adding" \? " is-sending"/);
assert.match(actions, /whisparr\?\.status === "sent" \|\| whisparr\?\.status === "already_exists" \? " is-sent"/);
assert.match(source, /React\.createElement\(WhisparrBadge, \{ fresh: whisparr\?\.status === "sent" \}\)/);
// Counts re-key on change so the bump plays; the panel's clock ticks.
assert.match(source, /key: data \? counts\[entry\.value\] : "loading", className: "curator-whisparr-count"/);
assert.match(source, /setInterval\(\(\) => setNow\(Date\.now\(\)\), WHISPARR_TICK_MS\)/);
const section = css.slice(css.indexOf("Motion: Whisparr sends and the rolling search"));
const reduced = section.slice(section.indexOf("@media (prefers-reduced-motion: reduce)"));
for (const selector of [".curator-whisparr-action.is-sending::after", ".curator-whisparr-badge.is-fresh", ".curator-whisparr-count", ".curator-whisparr-progress span"]) {
  assert.ok(reduced.includes(selector), `${selector} respects reduced motion`);
}
