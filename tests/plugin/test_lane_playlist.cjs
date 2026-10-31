const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const storage = new Map();
const requests = [];
const routes = [];
let nextSlate;
const context = {
  LANE_QUEUE_KEY: "queue", LANE_QUEUE_SIZE: 4, URLSearchParams, JSON,
  sessionStorage: {
    getItem: (key) => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
  },
  laneExclusions: new Map([["for_you", new Set([99])]]),
  location: { pathname: "/plugins/stash-curator", search: "" },
  rotationLane: () => ({ seed: "draw-one", atMs: 123 }),
  readMoodID: () => "mood-one", readTogetherMode: () => true,
  operation: async (request) => { requests.push(request); if (nextSlate instanceof Error) throw nextSlate; return nextSlate; },
};
const history = { push(route) { routes.push(route); } };
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function playlistOrigins("), source.indexOf("  function localDay(")), context);
const item = (id, position) => ({ scene_id: id, position, impression_id: `impression-${id}` });
const slate = { lane: "for_you", model_id: "model-one", impression_id: "first", page_size: 2, items: [item("1", 0), item("2", 1)] };
const filters = { includeTags: [{ name: "Include" }], excludeTags: [{ name: "Exclude" }], performers: [{ id: 10 }], studios: [{ id: 20 }], gender: "FEMALE" };
const plain = (value) => JSON.parse(JSON.stringify(value));

(async () => {
  // Visible picks lead; the rest of the batch fills up to the queue size without repeats.
  nextSlate = { lane: "for_you", model_id: "model-one", impression_id: "second", items: [item("2", 0), item("3", 0), item("4", 1), item("5", 2)] };
  await context.startLanePlaylist(slate, slate.items, filters, history);
  assert.equal(requests.length, 1);
  assert.deepEqual(plain(requests[0]), {
    lane: "for_you", page: 1, count: 2, exploration: 0, mood_id: "mood-one", together_mode: true,
    draw_seed: "draw-one", draw_at_ms: 123, exclude_scene_ids: [99, "1", "2"],
    include_tags: ["Include"], exclude_tags: ["Exclude"], performer_ids: ["10"], studio_ids: ["20"], gender: "FEMALE",
    operation: "get_slate", context: { route: "/plugins/stash-curator", playlist: true },
  });
  const url = new URL(routes[0], "http://stash");
  assert.equal(url.pathname, "/scenes/1");
  assert.deepEqual(url.searchParams.getAll("qs"), ["1", "2", "3", "4"]);
  assert.equal(url.searchParams.get("autoplay"), "true");
  assert.equal(url.searchParams.has("continue"), false); // Stash's own continue default applies.

  // Plays inside Curator's queue keep their lane impression; other queues don't.
  assert.deepEqual(plain(context.laneQueueOrigin("1", url.search)), { scene_id: "1", impression_id: "impression-1", lane: "for_you", impression_position: 0, model_id: "model-one" });
  assert.deepEqual(plain(context.laneQueueOrigin("3", url.search)), { scene_id: "3", impression_id: "impression-3", lane: "for_you", impression_position: 0, model_id: "model-one" });
  assert.equal(context.laneQueueOrigin("5", url.search), null);
  assert.equal(context.laneQueueOrigin("1", "?qs=1&qs=7"), null);
  assert.equal(context.laneQueueOrigin("1", ""), null);

  // A full visible page skips the extra request; a failed request surfaces without navigating.
  const full = { ...slate, items: [item("1", 0), item("2", 1), item("3", 2), item("4", 3)] };
  await context.startLanePlaylist(full, full.items, {}, history);
  assert.equal(requests.length, 1);
  assert.deepEqual(new URL(routes[1], "http://stash").searchParams.getAll("qs"), ["1", "2", "3", "4"]);
  nextSlate = new Error("offline");
  await assert.rejects(context.startLanePlaylist(slate, slate.items, {}, history), /offline/);
  assert.equal(routes.length, 2);
  await context.startLanePlaylist(slate, [], {}, history);
  assert.equal(routes.length, 2);
  storage.set("queue", "not json");
  assert.equal(context.laneQueueOrigin("1", url.search), null);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
