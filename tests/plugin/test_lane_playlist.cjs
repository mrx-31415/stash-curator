const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const storage = new Map();
const requests = [];
const sceneQueries = [];
const routes = [];
const patches = new Map();
let nextSlate;
let available = new Set(["1", "2", "4"]);
let storageError = false;
const context = {
  lanePlaylist: null, lanePlaylistPending: false, lanePlaylistError: "", lanePlaylistListeners: new Set(),
  LANE_PLAYLIST_KEY: "playlist", ORIGIN_KEY: "origin", URLSearchParams,
  sessionStorage: {
    getItem: (key) => storage.get(key) || null,
    setItem: (key, value) => { if (storageError) throw new Error("Storage full"); storage.set(key, value); },
    removeItem: (key) => storage.delete(key),
  },
  laneByValue: new Map([["for_you", { label: "For You" }]]),
  laneExclusions: new Map([["for_you", new Set([99])]]),
  location: { pathname: "/plugins/stash-curator", search: "" },
  uuid: () => "playlist-one", rotationLane: () => ({ seed: "draw-one", atMs: 123 }),
  readMoodID: () => "mood-one", readTogetherMode: () => true,
  operation: async (request) => { requests.push(request); if (nextSlate instanceof Error) throw nextSlate; return nextSlate; },
  fetch: async (url, options) => {
    const request = JSON.parse(options.body);
    sceneQueries.push(Object.values(request.variables));
    return { ok: true, json: async () => ({ data: Object.fromEntries(Object.entries(request.variables).map(([key, id]) => [key, available.has(id) ? { id } : null])) }) };
  },
  Api: { patch: { before: (name, callback) => patches.set(name, callback) } },
};
const history = {
  push(route) { routes.push(route); const url = new URL(route, "http://stash"); context.location.pathname = url.pathname; context.location.search = url.search; },
  replace(route) { this.push(route); },
};
context.useHistory = () => history;
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function readLanePlaylist("), source.indexOf("  function localDay(")), context);
const item = (id, position = 0) => ({ scene_id: id, position, impression_id: "impression-first" });
const slate = { lane: "for_you", model_id: "model-one", impression_id: "first", page_size: 2, items: [item("1"), item("2", 1)] };
const filters = { includeTags: [{ name: "Include" }], excludeTags: [{ name: "Exclude" }], performers: [{ id: 10 }], studios: [{ id: 20 }], gender: "FEMALE" };
function start() { context.startLanePlaylist(slate, slate.items, filters, history); }
const plain = (value) => JSON.parse(JSON.stringify(value));
(async () => {
  assert.equal(context.readLanePlaylist(), null);
  storage.set("playlist", '{"id":"bad","lane":"for_you","items":[],"index":-1}');
  assert.equal(context.readLanePlaylist(), null);
  const ordinary = { scene: { id: "1" }, onNext: () => "ordinary", onPrevious: () => "ordinary" };
  assert.equal(patches.get("ScenePlayer")(ordinary)[0], ordinary);
  start();
  assert.equal(context.location.pathname, "/scenes/1");
  assert.equal(new URLSearchParams(context.location.search).get("autoplay"), "true");
  assert.equal(new URLSearchParams(context.location.search).get("continue"), "false");
  assert.deepEqual(plain(context.readLanePlaylist()), plain(context.lanePlaylist));
  assert.equal(JSON.parse(storage.get("origin")).impression_position, 0);
  const player = patches.get("ScenePlayer")(ordinary)[0];
  assert.notEqual(player, ordinary);
  assert.equal(player.onPrevious, undefined);
  await player.onNext();
  assert.equal(context.location.pathname, "/scenes/2");
  assert.equal(requests.length, 0); // Queued picks don't need another recommendation request.
  assert.equal(JSON.parse(storage.get("origin")).impression_position, 1);
  context.readMoodID = () => "changed-mood";
  context.readTogetherMode = () => false;
  let resolve;
  nextSlate = new Promise((done) => { resolve = done; });
  const pending = context.nextLanePlaylist("2", history);
  await context.nextLanePlaylist("2", history);
  assert.equal(requests.length, 1); // Rapid clicks cannot skip or duplicate a scene.
  resolve({ ...slate, model_id: "model-two", items: [item("2"), item("3"), item("4", 2)] });
  await pending;
  assert.equal(context.location.pathname, "/scenes/4");
  assert.deepEqual(plain(context.lanePlaylist.items.map((entry) => entry.scene_id)), ["1", "2", "4"]);
  assert.equal(JSON.parse(storage.get("origin")).model_id, "model-two");
  assert.deepEqual(plain(requests[0].exclude_scene_ids), ["99", "1", "2"]);
  assert.equal(requests[0].page, 1);
  assert.equal(requests[0].mood_id, "mood-one");
  assert.equal(requests[0].together_mode, true);
  assert.equal(requests[0].draw_seed, "draw-one");
  assert.deepEqual(plain(requests[0].include_tags), ["Include"]);
  assert.deepEqual(plain(requests[0].exclude_tags), ["Exclude"]);
  assert.deepEqual(plain(requests[0].performer_ids), ["10"]);
  assert.deepEqual(plain(requests[0].studio_ids), ["20"]);
  assert.equal(requests[0].gender, "FEMALE");
  nextSlate = new Error("Network unavailable");
  await context.nextLanePlaylist("4", history);
  assert.equal(context.location.pathname, "/scenes/4");
  assert.equal(context.lanePlaylistError, "Network unavailable");
  assert.equal(context.lanePlaylistPending, false);
  nextSlate = { ...slate, items: [] };
  await context.nextLanePlaylist("4", history);
  assert.equal(context.lanePlaylist.finished, true);
  assert.equal(context.location.pathname, "/scenes/4");
  const count = requests.length;
  await context.nextLanePlaylist("4", history);
  assert.equal(requests.length, count);
  // Deleted queued scenes are skipped, and an entirely deleted batch fetches again.
  start();
  available = new Set(["1", "4"]);
  const responses = [{ ...slate, items: [item("3")] }, { ...slate, items: [item("4")] }];
  context.operation = async (request) => { requests.push(request); return responses.shift(); };
  await context.nextLanePlaylist("1", history);
  assert.equal(context.location.pathname, "/scenes/4");
  assert(requests.at(-1).exclude_scene_ids.includes("2"));
  assert(requests.at(-1).exclude_scene_ids.includes("3"));
  // Stopping or navigating elsewhere while a fetch runs must not hijack playback.
  context.operation = async () => new Promise((done) => { resolve = done; });
  const cancelled = context.nextLanePlaylist("4", history);
  context.saveLanePlaylist(null);
  history.push("/scenes/77");
  resolve({ ...slate, items: [item("1")] });
  await cancelled;
  assert.equal(context.location.pathname, "/scenes/77");
  assert.equal(context.lanePlaylist, null);
  assert.equal(context.lanePlaylistPending, false);
  assert.equal(patches.get("ScenePlayer")(ordinary)[0], ordinary);
  // Scene lookup failures retain the queue and allow retry without navigation.
  start();
  available = new Set(["1", "2"]);
  const fetchScenes = context.fetch;
  for (const response of [
    { ok: false, json: async () => ({}) },
    { ok: true, json: async () => ({ errors: [{ message: "Lookup failed" }] }) },
    { ok: true, json: async () => ({ data: {} }) },
  ]) {
    context.fetch = async () => response;
    await context.nextLanePlaylist("1", history);
    assert.equal(context.location.pathname, "/scenes/1");
    assert.equal(context.lanePlaylist.index, 0);
    assert(context.lanePlaylistError);
    assert.equal(context.lanePlaylistPending, false);
  }
  context.fetch = fetchScenes;
  await context.nextLanePlaylist("1", history);
  assert.equal(context.location.pathname, "/scenes/2");
  assert.equal(context.lanePlaylistError, "");
  // Leaving a queue without stopping it also cancels in-flight navigation.
  const abandoned = context.nextLanePlaylist("2", history);
  history.push("/scenes/77");
  resolve({ ...slate, items: [item("4")] });
  await abandoned;
  assert.equal(context.location.pathname, "/scenes/77");
  context.saveLanePlaylist(null);
  storageError = true;
  assert.throws(start, /Storage full/);
  assert.equal(context.lanePlaylist, null);
  assert.equal(context.location.pathname, "/scenes/77");
  console.log("PASS: continuous lane playback, frozen filters and mood, origin metadata, reload, duplicate clicks, deleted scenes, retry, end, cancellation, and native Next isolation");
})().catch((error) => { console.error(error); process.exitCode = 1; });
