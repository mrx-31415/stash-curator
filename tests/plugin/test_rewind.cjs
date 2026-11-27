const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const context = {
  React: { createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }), Fragment: "fragment" },
  FontAwesomeIcon: "icon", faPlay: "play", Date, Math, Number, String,
};
vm.runInNewContext(source.slice(source.indexOf("  // Monthly Rewind: during the first days of a month"), source.indexOf("  function RewindTeaser(")), context);
vm.runInNewContext(source.slice(source.indexOf("  function RewindCard("), source.indexOf("  // One of For You's top picks, dealt like a card")), context);
const text = (node) => typeof node === "string" || typeof node === "number" ? String(node) : (node?.children || []).map(text).join("");

// The month before, its length, and the month before that for comparison.
const months = context.rewindMonths(new Date(2026, 11, 3, 12).getTime());
assert.equal(months.key, "2026-11");
assert.equal(months.month.window_days, 30);
assert.equal(months.month.end_ms, new Date(2026, 11, 1).getTime());
assert.equal(months.before.window_days, 31);
assert.equal(months.before.end_ms, new Date(2026, 10, 1).getTime());
assert.equal(months.showing, true);
assert.equal(context.rewindMonths(new Date(2026, 11, 20).getTime()).showing, false, "only in the month's first days");
assert.equal(context.rewindMonths(new Date(2027, 0, 2).getTime()).key, "2026-12", "January looks back at December");

assert.equal(context.hitRate({ picks_watched: 20, rated_well: 14 }), 70);
assert.equal(context.hitRate({ picks_watched: 0, rated_well: 0 }), null);

const month = {
  picks_watched: 23, rated_well: 16, watched_seconds: 51600,
  best_find: { scene_id: "7", title: "Find", studio: "Studio C" },
  learned: { feedback: 5, answers: 10 },
  explored: { top_studios: [{ studio_id: "b", name: "Studio B", scenes: 9, rated_well: 4 }, { studio_id: "a", name: "Studio A", scenes: 6, rated_well: 1 }], new_studios: 3, new_performers: 7, watched_seconds: 51600, new_seconds: 16512 },
};
const taste = { shift: { rising: [{ tag_id: "1", name: "Outdoor" }], fading: [{ tag_id: "2", name: "Long take" }] } };
const names = { monthName: "November", nextName: "December" };
const cards = context.rewindCards({ month, before: { picks_watched: 12, rated_well: 7 }, taste, pick: { scene_id: "9" }, names });
assert.equal(cards.map((card) => card.kind).join(), "numbers,studio,find,drift,hits,explore,next");
const hits = cards.find((card) => card.kind === "hits");
assert.equal(hits.rate, 70);
assert.equal(hits.before, 58);
assert.equal(hits.taught, 15);
assert.equal(cards.find((card) => card.kind === "explore").share, 32);
// Cards without data drop out.
const sparse = context.rewindCards({ month: { picks_watched: 2, rated_well: 0, explored: {} }, before: null, taste: null, pick: null, names });
assert.equal(sparse.map((card) => card.kind).join(), "numbers,hits");

const scenes = new Map([["9", { title: "Next pick" }]]);
const render = (kind) => text(context.RewindCard({ card: cards.find((card) => card.kind === kind), month, scenes, grow: 1 }));
assert.match(render("numbers"), /November/);
assert.match(render("numbers"), /23Curator picks watched/);
assert.match(render("numbers"), /14 h 20 min/);
assert.match(render("studio"), /Studio B/);
assert.match(render("drift"), /Warming up to Outdoor\./);
assert.match(render("hits"), /70%up from 58%/);
assert.match(render("explore"), /You tried 7 new performers and 3 new studios\./);
assert.match(render("next"), /To start December/);
assert.match(render("next"), /Next pick/);
