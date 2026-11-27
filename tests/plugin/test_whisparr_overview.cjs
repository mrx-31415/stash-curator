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
  { id: 1, stashdb_id: "a", title: "Alpha Scene", studio: "North", status: "missing", added: "1970-01-10T00:00:00Z", score: 0.4, sent_at_ms: NOW - 20 * DAY, monitored: false,
    rotation: { state: "active", attempts: 2, added_at_ms: NOW - 20 * DAY, last_searched_at_ms: NOW - 2 * 3600000, next_due_at_ms: NOW + 4 * 3600000 } },
  { id: 2, stashdb_id: "b", title: "Beta Scene", studio: "South", status: "missing", added: "1970-01-20T00:00:00Z", score: 0.9, sent_at_ms: NOW - 3 * DAY, monitored: true },
  { id: 3, stashdb_id: "c", title: "Gamma Scene", studio: "North", status: "missing", added: "1970-01-30T00:00:00Z", score: null, sent_at_ms: null, monitored: false,
    rotation: { state: "gave_up", attempts: 9, added_at_ms: 0, last_searched_at_ms: 0, next_due_at_ms: 0 } },
  { id: 4, stashdb_id: "d", title: "Delta Scene", studio: "East", status: "downloading", added: "1970-01-05T00:00:00Z", score: null, sent_at_ms: null, queue: { progress: 0.5, state: "downloading", time_left: "00:05:00", problem: "slow" } },
  { id: 5, stashdb_id: "e", title: "Echo Scene", studio: "West", status: "not_in_stash", added: "1970-01-06T00:00:00Z", score: null, sent_at_ms: null },
  { id: 6, stashdb_id: "f", title: "Foxtrot Scene", studio: "West", status: "in_library", local_scene_id: "42", added: "1970-01-07T00:00:00Z", score: 0.7, sent_at_ms: NOW - 2 * DAY },
];
const rotation = { enabled: true, interval_ms: 15 * 60000, batch_size: 3, active: 1, last_run_at_ms: NOW - 5 * 60000, next_sweep_at_ms: NOW + 10 * 60000, paused_until_ms: null, last_error: null };
const data = { items, counts: {}, library_ready: true, whisparr_url: "http://whisparr", rotation };

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
  faSearch: "search", faBell: "bell", faBellSlash: "bell-slash", faPlay: "play", faExternalLinkAlt: "external", faInbox: "inbox", faTrash: "trash", faSync: "sync", faCog: "cog", faHistory: "history",
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
assert.equal(JSON.stringify(context.whisparrCounts(items)), JSON.stringify({ missing: 3, downloading: 1, not_in_stash: 1, in_library: 1, rotation: 1, all: 6 }));
assert.equal(ids(context.whisparrVisible(items, { status: "rotation" })), "1", "only scenes still being searched");
assert.equal(ids(context.whisparrVisible(items, { sort: "next_search" })), "1,3,2", "rotating scenes first, soonest search first");

// Each scene's place in the rolling search, never sooner than the next round.
context.formatTimeAgo = (ms) => `${Math.round((NOW - ms) / 3600000)}h ago`;
const line = (item, summary = rotation) => context.whisparrRotationLine(item, summary, NOW);
assert.equal(line(items[0]), "Searched 2× · last 2h ago · next in 4h");
assert.equal(line(items[2]), "Rolling search gave up after 9 searches");
assert.equal(line(items[1]), null, "not in the rotation");
const fresh = { ...items[1], rotation: { state: "active", attempts: 0, last_searched_at_ms: null, next_due_at_ms: NOW - 1 } };
assert.equal(line(fresh), "In the rolling search · first search in 10m", "waits for the next round");
const unreleased = { ...fresh, release_date: "1971-03-01" };
assert.match(line(unreleased), /waits for its release in \d+d$/);
assert.match(line(fresh, { ...rotation, enabled: false }), /rolling search is off$/);
assert.equal(line({ ...fresh, rotation: { ...fresh.rotation, state: "done", attempts: 1 } }), "Found by the rolling search after 1 search");

// The rolling search as a whole.
const status = (summary, waiting = 1) => context.whisparrRotationStatus(summary, waiting, NOW);
assert.equal(status(rotation).text, "Rolling search: 1 scene waiting, 3 every 15 min · next round in 10m · last round 0h ago.");
assert.equal(status(rotation, 0), null, "nothing to say with nothing waiting");
assert.equal(status({ ...rotation, paused_until_ms: NOW + 2 * 3600000 }).tone, "warning");
assert.match(status({ ...rotation, paused_until_ms: NOW + 2 * 3600000 }).text, /indexer in backoff\. It resumes in 2h\.$/);
assert.match(status({ ...rotation, last_error: "HTTP 500" }).text, /couldn't reach Whisparr on its last round \(HTTP 500\)/);
assert.ok(status({ ...rotation, last_error: "HTTP 500" }).retry && status({ ...rotation, paused_until_ms: NOW + 1 }).retry, "a paused rotation offers Try now");
assert.ok(!status(rotation).retry);
assert.match(status({ ...rotation, enabled: false }).text, /^Rolling search is off\./);
context.formatTimeAgo = () => "recently";

(async () => {
  const many = Array.from({ length: 1201 }, (_, index) => ({ id: index + 1, stashdb_id: `s${index}` }));
  assert.equal(await context.runWhisparrAction("search", many), 1201);
  assert.deepEqual(calls.map((call) => call.whisparr_ids.length), [500, 500, 201], "chunks of 500");
  assert.ok(calls.every((call) => call.action === "search" && !("stashdb_ids" in call)));
  calls.length = 0;
  await context.runWhisparrAction("remove", items.slice(0, 2));
  assert.deepEqual(calls[0].stashdb_ids, ["a", "b"], "removals clear Curator's sent record");
  calls.length = 0;
  await context.runWhisparrAction("rotate", [items[0], { id: 9 }, items[1]]);
  assert.deepEqual(calls[0].stashdb_ids, ["a", "", "b"], "rotation ids stay paired with Whisparr ids");

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
  assert.deepEqual(chips.map((chip) => all(chip).find((node) => node.props.className === "curator-whisparr-count").props.children[0]), ["3", "1", "1", "1", "1", "6"]);
  const banner = nodes.find((node) => /curator-whisparr-rotation\b/.test(node.props.className || ""));
  assert.ok(banner && banner.props.children.join("").includes("1 scene waiting"), "the rolling search status shows above the list");
  const rowLines = nodes.filter((node) => /curator-whisparr-rotation-line/.test(node.props.className || ""));
  assert.equal(rowLines.length, 2, "rows in or once in the rotation say so");
  const stop = nodes.find((node) => node.props["aria-label"] === "Stop retrying");
  const add = nodes.filter((node) => node.props["aria-label"] === "Add to rolling search");
  assert.ok(stop, "a scene being searched can leave the rotation");
  assert.equal(add.length, 2, "missing scenes outside the rotation can join it");

  states = [null, "Whisparr URL and API key are required", false];
  const setup = all(expand(context.WhisparrPanel({ onOpenSettings: () => {} })));
  assert.ok(setup.some((node) => node.props.children.includes("Whisparr isn't set up. Add its URL and API key in Settings, with StashDB as the selected endpoint.")));
  console.log("PASS: Whisparr overview");
})().catch((error) => { console.error(error); process.exit(1); });
