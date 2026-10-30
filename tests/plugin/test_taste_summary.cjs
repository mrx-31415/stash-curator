const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");

// Render Insights -> Your taste from a get_taste_summary payload, expanding
// every function component, so each name the page uses must be defined and
// the charts must follow the data (gaps for thin windows, a bar per category
// on the side its lift says).
const DAY = 86400000;
const windows = [0, 1, 2, 3].map((index) => ({ start_ms: index * 90 * DAY, end_ms: (index + 1) * 90 * DAY, scenes: index === 1 ? 2 : 40 }));
const summary = {
  schema_version: 2,
  model_id: "m",
  totals: { plays: 120, scenes_played: 100, library_scenes: 900, first_played_at_ms: 1, as_of_ms: 360 * DAY, answered_tags: 3, reason_answers: 2 },
  windows,
  likes: [
    { tag_id: "t1", name: "Outdoors", affinity: 0.4, confidence: 0.9, answer: 1, watched_scenes: 30, trend: [0.1, null, 0.2, 0.3] },
    { tag_id: "t2", name: "Rain", affinity: 0.2, confidence: 0.5, answer: null, watched_scenes: 12, trend: [null, null, 0.05, null] },
  ],
  dislikes: [{ tag_id: "t3", name: "Loud", affinity: -0.7, confidence: 0.8, answer: -1, watched_scenes: 0, trend: [0, null, 0, 0] }],
  shift: { rising: [{ tag_id: "t1", name: "Outdoors", recent: 0.3, before: 0.1, delta: 0.2 }], fading: [] },
  dormant: [{ entity_type: "studio", entity_id: "s1", name: "Old Studio", last_played_at_ms: 10 * DAY, play_count: 9 }],
  rediscovered: [{ scene_id: "7", plays: 3, returns: 1, longest_gap_ms: 200 * DAY, last_played_at_ms: 300 * DAY, title: "Seven" }],
  apart: {
    more: [{ tag_id: "t1", name: "Outdoors", lift: Math.log(4), watched_share: 0.2, library_share: 0.05 }],
    passed: [{ tag_id: "t4", name: "Indoors", lift: Math.log(0.5), watched_share: 0.04, library_share: 0.08 }],
  },
  reasons: { hits: [{ subject_type: "tag", subject_id: "t1", name: "Outdoors", answers: 2 }], misses: [] },
};

let states = [];
const context = {
  React: {
    createElement: (type, props, ...kids) => ({ type, props: { ...props, children: kids.flat() } }),
    Fragment: "fragment",
    useState: (initial) => [states.length ? states.shift() : initial, () => {}],
    useEffect: () => {},
  },
  Api: { components: { SceneCard: "scene-card" } },
  GQL: { useFindScenesQuery: () => ({ loading: false, data: { findScenes: { scenes: [{ id: "7" }] } } }) },
  Button: "button",
  FontAwesomeIcon: "icon",
  faArrowTrendUp: "up", faArrowTrendDown: "down", faTag: "tag", faCheckCircle: "check",
  useCuratorActivity: () => {},
  operation: async () => summary,
  Math, Number, String, Date, Map,
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  // Insights -> Your taste"), source.indexOf("  function CuratePanel(")), context);

function expand(node) {
  if (Array.isArray(node)) return node.map(expand);
  if (!node || typeof node !== "object") return node;
  if (typeof node.type === "function") return expand(node.type(node.props));
  return { ...node, props: { ...node.props, children: (node.props.children || []).map(expand) } };
}
const all = (node) => (node && typeof node === "object" ? [node, ...(node.props?.children || []).flatMap(all)] : []);

states = [summary, ""];
const page = expand(context.TasteSummary({ onOpenSentiment: () => {} }));
const nodes = all(page);
const text = nodes.flatMap((node) => node.props.children.filter((child) => typeof child === "string")).join(" ");

for (const heading of ["Your taste", "What you watch most", "What sets you apart", "Lately", "Then and never", "In your words", "Rediscovered"]) {
  assert.ok(nodes.some((node) => (node.type === "h2" || node.type === "h3") && node.props.children.includes(heading)), `${heading} renders`);
}
const sparks = nodes.filter((node) => node.props.className === "curator-insight-spark");
assert.equal(sparks.length, 2, "one sparkline per like");
const firstSpark = all(sparks[0]);
assert.equal(firstSpark.filter((node) => node.type === "polyline").length, 1, "the run after the gap is a line");
assert.equal(firstSpark.filter((node) => node.props.className === "curator-insight-spark-dot").length, 1, "the lone point before the gap is a dot");
assert.ok(firstSpark.some((node) => node.type === "title" && /too few watches \(2\)/.test(node.props.children[0])), "thin windows say so");
assert.equal(all(sparks[1]).filter((node) => node.props.className === "curator-insight-spark-end").length, 0, "no end marker when the last window is a gap");

// What sets you apart: each row names the tag, pairs its two shares on the
// list's scale, and prints both shares and the ratio.
const lists = nodes.filter((node) => node.type === "ol" && /curator-insight-apart /.test(node.props.className));
assert.deepEqual(lists.map((list) => list.props.className), ["curator-insight-apart curator-insight-more", "curator-insight-apart curator-insight-less"]);
const more = all(lists[0]);
assert.equal(more.find((node) => node.props.className === "curator-insight-apart-ratio").props.children[0], "4.0×");
assert.equal(more.find((node) => node.props.className === "curator-insight-apart-shares").props.children[0], "20% vs 5.0%");
assert.equal(more.find((node) => node.props.className === "curator-insight-apart-you").props.style.width, "100%");
assert.equal(more.find((node) => node.props.className === "curator-insight-apart-library").props.style.width, "25%");
assert.equal(all(lists[1]).find((node) => node.props.className === "curator-insight-apart-ratio").props.children[0], "0.5×");
assert.ok(firstSpark.some((node) => node.props.className === "curator-insight-spark-area"), "runs get an area fill");
assert.ok(nodes.some((node) => node.type === "scene-card"), "rediscovered scenes use Stash's scene card");
assert.match(text, /Came back after 7 months/);

// Nothing stands out: an explanation instead of empty lists.
states = [{ ...summary, apart: { more: [], passed: [] } }, ""];
const plain = all(expand(context.TasteSummary({ onOpenSentiment: () => {} })));
assert.equal(plain.filter((node) => node.type === "ol" && /curator-insight-apart /.test(node.props.className)).length, 0);
assert.ok(plain.some((node) => node.props.children.includes("Nothing stands out from your library yet.")));

// No plays yet: a single explanation, no empty charts.
states = [{ ...summary, totals: { ...summary.totals, plays: 0 } }, ""];
const empty = expand(context.TasteSummary({ onOpenSentiment: () => {} }));
assert.equal(empty.props.className, "alert alert-info");
console.log("PASS: taste summary renders its sections and charts");
