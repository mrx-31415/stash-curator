const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const helpers = source.slice(source.indexOf("  function localDay()"), source.indexOf("  function readSlateCache()"));

// Each call loads the plugin script afresh, as a document load does; storage persists.
function loadDocument(stored, state) {
  const context = {
    rotation: state.rotation,
    ROTATION_KEY: "rotation",
    RELOAD_ROTATION_KEY: "reloads",
    localStorage: { setItem: (key, value) => stored.set(key, value) },
    uuid: () => `seed-${++state.nextSeed}`,
    sessionStorage: {
      getItem: (key) => stored.get(key) || null,
      setItem: (key, value) => stored.set(key, value),
    },
    URL,
    window: {
      location: state.location,
      performance: { getEntriesByType: () => [{ type: state.navigation, name: state.loadedUrl }] },
    },
    clearSlateCache: () => { state.clears += 1; },
    Date: class extends Date {
      constructor() { super(2026, 8, state.day, 12); }
      static now() { return new Date(2026, 8, state.day, 12).getTime(); }
    },
  };
  vm.runInNewContext(`${helpers}\nthis.rotationHelpers = { rotationLane, rotateDay, advanceRotation, rotateOnRepeatedReload };`, context);
  return context.rotationHelpers;
}

const PAGE = "http://stash/plugins/stash-curator";

function freshState() {
  return {
    rotation: { day: "2026-9-23", modelId: "model-a", lanes: {} },
    day: 23,
    navigation: "navigate",
    loadedUrl: PAGE,
    location: { pathname: "/plugins/stash-curator" },
    clears: 0,
    nextSeed: 0,
  };
}

test("draw seed changes on a new day, button press, and second reload", () => {
  const stored = new Map();
  const state = freshState();
  let helpers = loadDocument(stored, state);
  const { rotationLane, rotateDay, advanceRotation } = helpers;

  const first = rotationLane("for_you").seed;
  assert.equal(first, "seed-1");
  assert.equal(rotateDay(), false);
  state.day = 24;
  assert.equal(rotateDay(), true);
  const saved = JSON.parse(stored.get("rotation"));
  assert.equal(saved.lanes.for_you.seed, "seed-2");
  assert.equal(saved.lanes.for_you.atMs, new Date(2026, 8, state.day, 12).getTime());
  assert.equal(state.clears, 1);

  assert.equal(helpers.rotateOnRepeatedReload("for_you", 1), false);
  state.navigation = "reload";
  assert.equal(loadDocument(stored, state).rotateOnRepeatedReload("for_you", 1), false);
  helpers = loadDocument(stored, state);
  assert.equal(helpers.rotateOnRepeatedReload("for_you", 1), true);
  helpers.advanceRotation("for_you");
  assert.equal(JSON.parse(stored.get("rotation")).lanes.for_you.seed, "seed-3");
  assert.equal(loadDocument(stored, state).rotateOnRepeatedReload("best_bets", 1), false);
});

test("returning to the page after a reload is not another reload", () => {
  const stored = new Map();
  const state = freshState();
  state.navigation = "reload";
  // The tab was reloaded on Recommendations; the user opens a scene and goes Back, twice.
  const helpers = loadDocument(stored, state);
  assert.equal(helpers.rotateOnRepeatedReload("for_you", 1), false);
  for (let visit = 0; visit < 3; visit += 1) {
    assert.equal(helpers.rotateOnRepeatedReload("for_you", 1), false);
  }
  // A reload of another page, then navigating to Recommendations, is not a reload of it.
  state.loadedUrl = "http://stash/scenes/12";
  stored.set("reloads", JSON.stringify({ identity: "unused", count: 1 }));
  assert.equal(loadDocument(stored, state).rotateOnRepeatedReload("for_you", 1), false);
});
