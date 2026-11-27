const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");

// Manage → Viewing history: rows say whether a play counts and why, the row
// button sends that watch's own span back, pauses mark where they began, and
// the pause switch writes the whole settings map.
const HOUR = 3600000;
const NOW = new Date(2026, 10, 27, 15, 0).getTime();
const watch = (scene, start, counted, reason, extra = {}) => ({
  scene_id: scene, started_at_ms: start, ended_at_ms: start + HOUR / 2, watched_seconds: 600,
  source: "lane", lane: "best_bets", stash_plays: 1, counted, reason, ...extra,
});
const items = [
  watch("1", NOW - HOUR, false, "paused"),
  watch("2", NOW - 2 * HOUR, true, null, { source: "history", lane: null, watched_seconds: null }),
  watch("3", NOW - 30 * HOUR, false, "chosen", { source: "stash", lane: null }),
  watch("4", NOW - 60 * HOUR, true, null),
];
const data = {
  paused: true, paused_since_ms: NOW - 1.5 * HOUR, paused_not_counted: 1, has_more: false,
  pause_periods: [{ rule_id: 7, started_at_ms: NOW - 1.5 * HOUR, ended_at_ms: null }],
  summary: { days: 30, watches: 4, watched_seconds: 1800, counted: 2, not_counted: 2 },
  items,
};

const calls = [];
const plain = (value) => JSON.parse(JSON.stringify(value));
const configured = [];
let states = [];
const context = {
  React: {
    createElement: (type, props, ...kids) => ({ type, props: { ...props, children: kids.flat() } }),
    Fragment: "fragment",
    useState: (initial) => [states.length ? states.shift() : typeof initial === "function" ? initial() : initial, () => {}],
    useEffect: () => {},
  },
  GQL: { useFindScenesQuery: () => ({ data: { findScenes: { scenes: [
    { id: "1", title: "Alpha", studio: { name: "North" }, files: [{ duration: 1800 }], paths: { screenshot: "/s1.jpg" } },
    { id: "2", title: "Beta", files: [{ duration: 900 }], paths: {} },
  ] } } }) },
  laneByValue: new Map([["best_bets", { label: "Best bets" }]]),
  useCuratorActivity: () => {},
  operation: async (args) => { calls.push(args); return { undo: { added_rule_ids: [9], removed_rules: [] } }; },
  getPluginSettings: async () => ({ homeForYou: true, pauseLearning: true }),
  configurePlugin: async (values) => { configured.push(values); },
  scheduleModelUpdate: () => {},
  clearSlateCache: () => {},
  Button: "button", ButtonGroup: "group", NavLink: "link", FontAwesomeIcon: "icon",
  faPause: "pause", faPlayCircle: "play", faFilm: "film",
  Math, Number, String, Date, Map, Set, Array, Object, Promise, JSON,
};
vm.createContext(context);
const start = source.indexOf("  // Manage → Viewing history:");
vm.runInContext(source.slice(start, source.indexOf("  // Manage shell (GH #150", start)), context);
context.Date = class extends Date {
  constructor(...args) { super(...(args.length ? args : [NOW])); }
  static now() { return NOW; }
};

function render(node) {
  if (Array.isArray(node)) return node.map(render);
  if (!node || typeof node !== "object") return node;
  if (typeof node.type === "function") return render(node.type(node.props));
  return { ...node, props: { ...node.props, children: (node.props.children || []).map(render) } };
}
function all(node, match, found = []) {
  if (Array.isArray(node)) node.forEach((child) => all(child, match, found));
  else if (node && typeof node === "object") {
    if (match(node)) found.push(node);
    all(node.props?.children, match, found);
  }
  return found;
}
const text = (node) => (Array.isArray(node) ? node.map(text).join("") : node && typeof node === "object" ? text(node.props.children) : node == null || node === false ? "" : String(node));
// data, items, loading, busy, error, filter, period, selected, toast, pages, version
const panel = (filter = "all", selected = new Set()) => {
  states = [data, items, false, false, "", filter, "today", selected, null, 1, 0];
  return render(context.ViewingHistoryPanel());
};

(async () => {
  const page = panel();
  const rows = all(page, (node) => typeof node.props?.className === "string" && node.props.className.startsWith("curator-viewing-row"));
  assert.deepEqual(plain(rows.map((row) => row.props.className)), [
    "curator-viewing-row is-paused", "curator-viewing-row is-counted", "curator-viewing-row is-excluded", "curator-viewing-row is-counted",
  ]);
  assert.match(text(rows[0]), /Alpha.*North.*10 min of 30 min.*From Best bets.*Not counted · paused.*Count/);
  assert.match(text(rows[1]), /Beta.*Played.*Stash history.*Counted.*Don’t count/);
  assert.match(text(rows[2]), /Scene removed from Stash.*Stash player.*Not counted · your choice/, "Stash answered without it");
  const listText = all(page, (node) => node.props?.className === "curator-viewing-list").map(text).join("");
  assert.ok(listText.indexOf("Alpha") < listText.indexOf("Learning paused") && listText.indexOf("Learning paused") < listText.indexOf("Beta"),
    "the pause marker sits where the pause began");
  assert.match(listText, /^Today/);
  assert.match(text(page), /1 play from the pause isn’t counted/);
  assert.match(text(page), /Learning paused since/);

  // The row button sends the watch's own span back.
  const button = all(rows[1], (node) => node.type === "button")[0];
  await button.props.onClick();
  assert.deepEqual(plain(calls.pop()), { operation: "set_viewing_choice", choice: "exclude",
    watches: [{ scene_id: "2", started_at_ms: NOW - 2 * HOUR, ended_at_ms: NOW - 1.5 * HOUR }] });
  await all(rows[0], (node) => node.type === "button")[0].props.onClick();
  assert.equal(calls.pop().choice, "include");

  // Count them counts every pause period, an open one up to now.
  const countThem = all(page, (node) => node.type === "button" && text(node) === "Count them")[0];
  await countThem.props.onClick();
  assert.deepEqual(plain(calls.pop()), { operation: "set_viewing_choice", choice: "include", periods: [{ since_ms: NOW - 1.5 * HOUR, until_ms: NOW }] });

  // Resume writes the whole settings map with the pause off.
  await all(page, (node) => node.type === "button" && text(node) === "Resume learning")[0].props.onClick();
  assert.deepEqual(plain(configured.pop()), { homeForYou: true, pauseLearning: false });

  // Selection acts on every selected watch.
  const selectedPage = panel("all", new Set(["1:" + (NOW - HOUR), "4:" + (NOW - 60 * HOUR)]));
  const bar = all(selectedPage, (node) => node.props?.className === "curator-viewing-selection")[0];
  assert.match(text(bar), /2 selected/);
  await all(bar, (node) => node.type === "button" && text(node) === "Don’t count")[0].props.onClick();
  assert.deepEqual(plain(calls.pop().watches.map((w) => w.scene_id)), ["1", "4"]);

  // Counted only: no uncounted rows and no pause marker.
  const counted = panel("counted");
  const countedText = all(counted, (node) => node.props?.className === "curator-viewing-list").map(text).join("");
  assert.ok(!countedText.includes("Learning paused") && !countedText.includes("Alpha") && countedText.includes("Beta"));
})().catch((error) => { console.error(error); process.exit(1); });
