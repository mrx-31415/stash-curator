const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const store = new Map();
const context = {
  React: {
    createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }),
    useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
    useEffect: () => {}, useRef: (value) => ({ current: value }),
  },
  localStorage: { getItem: (key) => store.get(key) ?? null, setItem: (key, value) => store.set(key, String(value)) },
  reducedMotion: () => true, Date, Math, Number, String, Array,
  Button: "Button", FontAwesomeIcon: "icon", faPlay: "play", faClone: "clone",
  formatTimeAgo: () => "3 days ago", cardReason: () => ({ teaser: "Matches your preference for Outdoor." }),
  operation: async () => ({}),
};
vm.runInNewContext(source.slice(source.indexOf("  // Welcome back: what is new since the last visit"), source.indexOf("  // Placeholder cards that shimmer while a lane loads")), context);
const text = (node) => typeof node === "string" || typeof node === "number" ? String(node) : (node?.children || []).map(text).join("");
const all = (node) => (node && typeof node === "object" ? [node, ...(node.children || []).flatMap(all)] : []);
const expand = (node) => {
  if (!node || typeof node !== "object") return node;
  if (typeof node.type === "function") return expand(node.type(node.props));
  return { ...node, children: node.children.map(expand) };
};

// Minutes per local day, Curator sessions only, oldest day first.
const now = new Date(2026, 10, 27, 20, 0).getTime();
const today = new Date(2026, 10, 27).getTime();
const days = context.recapDays([
  { started_at_ms: today + 3600000, seconds: 600, curator: true },
  { started_at_ms: today + 7200000, seconds: 300, curator: true },
  { started_at_ms: today - 86400000 + 1000, seconds: 1200, curator: true },
  { started_at_ms: today + 1000, seconds: 9999, curator: false },
  { started_at_ms: today - 30 * 86400000, seconds: 600, curator: true },
], now);
assert.equal(days.length, 7);
assert.equal(days[6].minutes, 15);
assert.equal(days[5].minutes, 20);
assert.equal(days.slice(0, 5).reduce((sum, day) => sum + day.minutes, 0), 0, "older sessions fall outside the week");

// Tiles only for what changed.
const tiles = context.welcomeTiles({ new_scenes: 3, whisparr_landed: 0, model_updates: 1 });
assert.deepEqual(tiles.map((tile) => tile.key).join(), "new,model");
assert.equal(context.welcomeTiles(null).length, 0);
// The week key is the local Monday.
assert.equal(new Date(Number(context.recapWeekKey(now))).getDay(), 1);

// The previous visit is read once per page load and replaced with now.
store.set("stash-curator:last-visit:v1", String(now - 3 * 86400000));
assert.equal(context.welcomePrevious(), now - 3 * 86400000);
assert.ok(Number(store.get("stash-curator:last-visit:v1")) > Date.now() - 5000);
assert.equal(context.welcomePrevious(), now - 3 * 86400000, "a remount keeps the first reading");

// The recap reads as a sentence, charts the week and lists what was learned.
const recap = { picks_watched: 6, rated_well: 4, sessions: [], best_find: { scene_id: "9", title: "New find", studio: "Studio C" }, learned: { feedback: 3, answers: 9, tags: [{ tag_id: "1", name: "Outdoor", value: 1 }, { tag_id: "2", name: "Long take", value: -0.5 }] } };
const view = expand(context.WeeklyRecap({ recap, now, onHide: () => {} }));
assert.match(text(view), /You watched 6 Curator picks and rated 4 of them well\./);
assert.match(text(view), /Best find: New find from Studio C/);
assert.match(text(view), /Curator learned 12 things/);
const chips = all(view).filter((node) => /curator-recap-chip /.test(node.props?.className || ""));
assert.deepEqual(chips.map((chip) => chip.props.className.split(" ")[1]).join(), "is-up,is-down");
assert.equal(all(view).filter((node) => node.props?.className === "curator-recap-day").length, 7);

// Tonight's pick deals through the top picks with a reason.
const items = [{ scene_id: "1" }, { scene_id: "2" }];
const scenes = new Map([["1", { title: "First", studio: { name: "Studio A" } }]]);
const pick = context.TonightsPick({ items, scenes });
assert.match(text(pick), /First/);
assert.match(text(pick), /Matches your preference for Outdoor\./);
assert.match(text(pick), /Pick 1 of 2/);
assert.ok(all(pick).some((node) => /\bscene-card\b/.test(node.props?.className || "")), "the image follows the SFW card contract");
assert.ok(all(pick).some((node) => node.type === "Button" && /Deal again/.test(text(node))));
