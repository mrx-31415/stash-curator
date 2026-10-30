const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
function extract(name) {
  const start = source.search(new RegExp(`^  (async )?function ${name}\\(`, "m"));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf("\n  }\n", start) + "\n  }\n".length);
}
const lanes = source.slice(source.indexOf("  const LANES = ["), source.indexOf("  const NAV_ITEMS = ["));
const icons = Object.fromEntries([...lanes.matchAll(/icon: (fa\w+)/g)].map(([, icon]) => [icon, icon]));
const helpers = [
  lanes,
  source.match(/^  const HOME_DEFAULT_LANES = .*$/m)[0],
  source.match(/^  const HOME_ENTRY_TYPE = .*$/m)[0],
  ...["homeLanes", "isHomeEntry", "reconcileHomeContent", "ensureHomeDefaults", "saveHomeRemovals", "resetForStaleSlate", "adoptSlateIdentity", "loadHomeSlates"].map(extract),
].join("\n");

function load(overrides = {}) {
  const context = vm.createContext({
    ...icons,
    rotation: { day: "today", modelId: "model-a", lanes: {} },
    slateCache: new Map(),
    laneExclusions: new Map([["revisit", new Set(["9"])]]),
    cachedModelId: "model-a",
    cachedConfigUpdatedAtMs: 10,
    cacheGeneration: 0,
    location: { pathname: "/" },
    rotateDay() {},
    readTogetherMode: () => false,
    readMoodID: () => "",
    saveRotation() {},
    persistSlateCache() {},
    slateKey: (lane, page = 1) => `${context.cachedConfigUpdatedAtMs || 0}:${lane}:${page}`,
    rotationLane(lane) {
      context.rotation.lanes[lane] ||= { seed: `seed-${lane}`, atMs: 5 };
      return context.rotation.lanes[lane];
    },
    clearSlateCache() {
      context.slateCache.clear();
      context.cachedModelId = null;
      context.cachedConfigUpdatedAtMs = null;
      context.cacheGeneration += 1;
    },
    ...overrides,
  });
  vm.runInContext(`${helpers}\nthis.home = { LANES, homeLanes, reconcileHomeContent, ensureHomeDefaults, saveHomeRemovals, loadHomeSlates };`, context);
  return context;
}
const slate = (lane, model = "model-a", config = 10) => ({ lane, model_id: model, config_updated_at_ms: config, items: [] });

test("home lanes default to For You and follow lane order", () => {
  const { home } = load();
  const values = (settings) => [...home.homeLanes(settings).map((lane) => lane.value)];
  assert.deepEqual(values({}), ["for_you"]);
  assert.deepEqual(values({ homeForYou: false }), []);
  assert.deepEqual(values({ homeDormant: true, homeForYou: true, homeBestBets: true }), ["for_you", "best_bets", "dormant"]);
  assert.equal(new Set(home.LANES.map((lane) => lane.homeKey)).size, home.LANES.length);
});

test("For You's default is written once, keeping every other setting", async () => {
  const writes = [];
  const { home } = load({ configurePlugin: async (values) => { writes.push(values); return values; } });
  await home.ensureHomeDefaults({ pageSize: 30 });
  assert.deepEqual(JSON.parse(JSON.stringify(writes)), [{ pageSize: 30, homeForYou: true }]);
  await home.ensureHomeDefaults({ pageSize: 30, homeForYou: false });
  assert.equal(writes.length, 1);
});

test("cached lanes are reused and the rest arrive in one get_slates call", async () => {
  const calls = [];
  const context = load({ operation: async (args) => { calls.push(args); return { slates: args.slates.map(({ lane }) => slate(lane)) }; } });
  const cached = slate("for_you");
  context.slateCache.set("10:for_you:1", cached);
  const slates = await context.home.loadHomeSlates(["for_you", "revisit", "dormant"]);
  assert.equal(slates.get("for_you"), cached);
  assert.deepEqual([...slates.keys()].sort(), ["dormant", "for_you", "revisit"]);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].operation, "get_slates");
  assert.equal(calls[0].page, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0].slates)), [
    { lane: "revisit", exclude_scene_ids: ["9"], draw_seed: "seed-revisit", draw_at_ms: 5 },
    { lane: "dormant", exclude_scene_ids: [], draw_seed: "seed-dormant", draw_at_ms: 5 },
  ]);
  assert.equal(context.slateCache.get("10:revisit:1"), slates.get("revisit"));
});

test("a new model drops the cached lanes and re-requests every home lane", async () => {
  const calls = [];
  const context = load({ operation: async (args) => { calls.push(args.slates.map(({ lane }) => lane)); return { slates: args.slates.map(({ lane }) => slate(lane, "model-b", 20)) }; } });
  context.slateCache.set("10:for_you:1", slate("for_you"));
  const slates = await context.home.loadHomeSlates(["for_you", "revisit"]);
  assert.deepEqual(calls, [["revisit"], ["for_you", "revisit"]]);
  assert.equal(slates.get("for_you").model_id, "model-b");
  assert.equal(context.cachedModelId, "model-b");
  assert.equal(context.rotation.modelId, "model-b");
  assert.equal(context.slateCache.get("20:for_you:1"), slates.get("for_you"));
});

const entry = (lane) => ({ __typename: "CuratorLane", lane });
const plain = (value) => JSON.parse(JSON.stringify(value));

test("Stash's home list gains enabled lanes at the top and keeps where they were moved", () => {
  const { home } = load();
  const recent = { __typename: "CustomFilter", mode: "SCENES" };
  const saved = { __typename: "SavedFilter", savedFilterId: 4 };
  // Fresh: For You (the default) goes first, Stash's rows stay in order.
  assert.deepEqual(plain(home.reconcileHomeContent([recent, saved], {})), [entry("for_you"), recent, saved]);
  // Already placed below Stash's rows: nothing to write.
  assert.equal(home.reconcileHomeContent([recent, entry("for_you"), saved], {}), null);
  // A newly enabled lane goes on top; the moved one stays put.
  assert.deepEqual(plain(home.reconcileHomeContent([recent, entry("for_you")], { homeDormant: true })),
    [entry("dormant"), recent, entry("for_you")]);
  // Disabled, retired and repeated entries are dropped.
  assert.deepEqual(plain(home.reconcileHomeContent([entry("for_you"), recent, entry("retired"), entry("for_you"), entry("stretch")], {})),
    [entry("for_you"), recent]);
  assert.deepEqual(plain(home.reconcileHomeContent([entry("for_you"), recent], { homeForYou: false })), [recent]);
  // No list yet (Stash writes its default first) or an odd value: leave it.
  assert.equal(home.reconcileHomeContent(undefined, {}), null);
  assert.equal(home.reconcileHomeContent({ rows: [] }, {}), null);
});

test("a Curator row deleted in Customise turns its lane off, keeping every other setting", async () => {
  const writes = [];
  const settings = { pageSize: 30, homeForYou: true, homeDormant: true };
  const { home } = load({
    getPluginSettings: async () => settings,
    configurePlugin: async (values) => { writes.push(values); return values; },
  });
  await home.saveHomeRemovals(undefined);
  await home.saveHomeRemovals([entry("for_you"), entry("dormant"), { __typename: "CustomFilter" }]);
  assert.equal(writes.length, 0);
  await home.saveHomeRemovals([{ __typename: "CustomFilter" }, entry("dormant")]);
  assert.deepEqual(plain(writes), [{ pageSize: 30, homeForYou: false, homeDormant: true }]);
});
