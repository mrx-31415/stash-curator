const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");

// Find → Whisparr: filters and order, chunked actions that only send
// StashDB ids for removals, the page-chat shelf, and rows that keep Stash's
// SFW card contract with controls outside card-section.
const DAY = 86400000;
const NOW = 400 * DAY;
const items = [
  { id: 1, stashdb_id: "a", title: "Alpha Scene", studio: "North", status: "missing", added: "1970-01-10T00:00:00Z", score: 0.4, sent_at_ms: NOW - 20 * DAY, monitored: false },
  { id: 2, stashdb_id: "b", title: "Beta Scene", studio: "South", status: "missing", added: "1970-01-20T00:00:00Z", score: 0.9, sent_at_ms: NOW - 3 * DAY, monitored: true },
  { id: 3, stashdb_id: "c", title: "Gamma Scene", studio: "North", status: "missing", added: "1970-01-30T00:00:00Z", score: null, sent_at_ms: null, monitored: false },
  { id: 4, stashdb_id: "d", title: "Delta Scene", studio: "East", status: "downloading", added: "1970-01-05T00:00:00Z", score: null, sent_at_ms: null, queue: { progress: 0.5, state: "downloading", time_left: "00:05:00", problem: "slow" } },
  { id: 5, stashdb_id: "e", title: "Echo Scene", studio: "West", status: "not_in_stash", added: "1970-01-06T00:00:00Z", score: null, sent_at_ms: null },
  { id: 6, stashdb_id: "f", title: "Foxtrot Scene", studio: "West", status: "in_library", local_scene_id: "42", added: "1970-01-07T00:00:00Z", score: 0.7, sent_at_ms: NOW - 2 * DAY },
];
const data = { items, counts: {}, library_ready: true, whisparr_url: "http://whisparr" };

const calls = [];
let states = [];
const context = {
  React: {
    createElement: (type, props, ...kids) => ({ type, props: { ...props, children: kids.flat() } }),
    Fragment: "fragment",
    useState: (initial) => [states.length ? states.shift() : typeof initial === "function" ? initial() : initial, () => {}],
    useEffect: () => {},
    useMemo: (make) => make(),
  },
  usePageChatFeed: () => {},
  pageChatShortTitle: (title) => title || null,
  pageChatDay: (ms, now) => `${Math.round((now - ms) / DAY)}d`,
  pageChatTo: (kind, id) => `/${kind}/${id}`,
  PAGE_CHAT_DAY: DAY,
  formatTimeAgo: () => "recently",
  Button: "button",
  FontAwesomeIcon: "icon",
  faSearch: "search", faBell: "bell", faBellSlash: "bell-slash", faPlay: "play", faExternalLinkAlt: "external", faInbox: "inbox", faTrash: "trash", faSync: "sync", faCog: "cog",
  operation: async (args) => { calls.push(args); return { count: args.whisparr_ids.length }; },
  window: { confirm: () => true },
  Math, Number, String, Date, Map, Set, Array, Object, Promise,
};
vm.createContext(context);
const start = source.indexOf("  // Find → Whisparr:");
vm.runInContext(source.slice(start, source.indexOf("  function ExpandPanel(", start)), context);

const ids = (list) => list.map((item) => item.id).join(",");
assert.equal(ids(context.whisparrVisible(items)), "2,1,3", "missing by best match, unscored last");
assert.equal(ids(context.whisparrVisible(items, { sort: "added_old" })), "1,2,3");
assert.equal(ids(context.whisparrVisible(items, { sentOnly: true })), "2,1");
assert.equal(ids(context.whisparrVisible(items, { status: "all", query: "north" })), "1,3");
assert.equal(JSON.stringify(context.whisparrCounts(items)), JSON.stringify({ missing: 3, downloading: 1, not_in_stash: 1, in_library: 1, all: 6 }));

(async () => {
  const many = Array.from({ length: 1201 }, (_, index) => ({ id: index + 1, stashdb_id: `s${index}` }));
  assert.equal(await context.runWhisparrAction("search", many), 1201);
  assert.deepEqual(calls.map((call) => call.whisparr_ids.length), [500, 500, 201], "chunks of 500");
  assert.ok(calls.every((call) => call.action === "search" && !("stashdb_ids" in call)));
  calls.length = 0;
  await context.runWhisparrAction("remove", items.slice(0, 2));
  assert.deepEqual(calls[0].stashdb_ids, ["a", "b"], "removals clear Curator's sent record");

  const shelf = context.pageChatWhisparrShelf(data, NOW).map(([, line]) => line);
  const byKey = Object.fromEntries(shelf.map((line) => [line.key, line]));
  assert.equal(byKey.whisparrArrived.values.r, "Foxtrot Scene");
  assert.equal(byKey.whisparrArrived.links.r, "/scenes/42");
  assert.equal(byKey.whisparrWaiting.values.n, "2");
  assert.equal(byKey.whisparrWaiting.values.when, "20d", "the oldest send still missing");
  assert.equal(byKey.whisparrBest.values.r, "Beta Scene");
  assert.equal(byKey.whisparrGrabbed.values.n, "1");
  for (const key of Object.keys(byKey)) assert.match(source, new RegExp(`\\b${key}: \\[`), `${key} has lines`);

  function expand(node) {
    if (Array.isArray(node)) return node.map(expand);
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") return expand(node.type(node.props));
    return { ...node, props: { ...node.props, children: (node.props.children || []).map(expand) } };
  }
  const all = (node) => (node && typeof node === "object" ? [node, ...(node.props?.children || []).flatMap(all)] : []);
  states = [data, "", false];
  const nodes = all(expand(context.WhisparrPanel({ onOpenSettings: () => {} })));
  const rows = nodes.filter((node) => /curator-whisparr-row/.test(node.props.className || ""));
  assert.equal(rows.length, 3, "the Missing tab lists the missing scenes");
  for (const row of rows) {
    assert.match(row.props.className, /\bscene-card\b/);
    const inner = all(row);
    assert.ok(inner.some((node) => /\bscene-card-image\b/.test(node.props.className || "")));
    const section = inner.find((node) => /\bcard-section\b/.test(node.props.className || ""));
    assert.ok(all(section).some((node) => node.props.className === "card-section-title"));
    assert.ok(!all(section).some((node) => node.type === "button" || node.type === "input"), "controls stay outside card-section");
  }
  const searchAll = nodes.find((node) => node.props.className === "curator-whisparr-search-all");
  assert.ok(searchAll.props.children.join("").includes("Search all 3"));
  const chips = nodes.filter((node) => /curator-whisparr-chip/.test(node.props.className || ""));
  assert.deepEqual(chips.map((chip) => all(chip).find((node) => node.props.className === "curator-whisparr-count").props.children[0]), ["3", "1", "1", "1", "6"]);

  states = [null, "Whisparr URL and API key are required", false];
  const setup = all(expand(context.WhisparrPanel({ onOpenSettings: () => {} })));
  assert.ok(setup.some((node) => node.props.children.includes("Whisparr isn't set up. Add its URL and API key in Settings, with StashDB as the selected endpoint.")));
  console.log("PASS: Whisparr overview");
})().catch((error) => { console.error(error); process.exit(1); });
