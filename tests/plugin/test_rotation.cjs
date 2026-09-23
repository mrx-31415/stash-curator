const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const helpers = source.slice(source.indexOf("  function localDay()"), source.indexOf("  function readSlateCache()"));

test("draw seed changes on a new day, button press, and second reload", () => {
  const stored = new Map();
  const rotation = { day: "2026-9-23", modelId: "model-a", lanes: {} };
  let day = 23;
  let navigation = "navigate";
  let clears = 0;
  let nextSeed = 0;
  const context = {
    rotation,
    ROTATION_KEY: "rotation",
    RELOAD_ROTATION_KEY: "reloads",
    localStorage: { setItem: (key, value) => stored.set(key, value) },
    uuid: () => `seed-${++nextSeed}`,
    sessionStorage: {
      getItem: (key) => stored.get(key) || null,
      setItem: (key, value) => stored.set(key, value),
    },
    window: { performance: { getEntriesByType: () => [{ type: navigation }] } },
    clearSlateCache: () => { clears += 1; },
    Date: class extends Date {
      constructor() { super(2026, 8, day, 12); }
      static now() { return new Date(2026, 8, day, 12).getTime(); }
    },
  };
  vm.runInNewContext(`${helpers}\nthis.rotationHelpers = { rotationLane, rotateDay, advanceRotation, rotateOnRepeatedReload };`, context);
  const { rotationLane, rotateDay, advanceRotation, rotateOnRepeatedReload } = context.rotationHelpers;

  const first = rotationLane("for_you").seed;
  assert.equal(first, "seed-1");
  assert.equal(rotateDay(), false);
  day = 24;
  assert.equal(rotateDay(), true);
  const saved = JSON.parse(stored.get("rotation"));
  assert.equal(saved.lanes.for_you.seed, "seed-2");
  assert.equal(saved.lanes.for_you.atMs, new Date(2026, 8, day, 12).getTime());
  assert.equal(clears, 1);

  assert.equal(rotateOnRepeatedReload("for_you", 1), false);
  navigation = "reload";
  assert.equal(rotateOnRepeatedReload("for_you", 1), false);
  assert.equal(rotateOnRepeatedReload("for_you", 1), true);
  advanceRotation("for_you");
  assert.equal(JSON.parse(stored.get("rotation")).lanes.for_you.seed, "seed-3");
  assert.equal(rotateOnRepeatedReload("best_bets", 1), false);
});
