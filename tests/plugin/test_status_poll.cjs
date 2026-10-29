const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// The page's status poll is shared, slows down when idle, and stops while
// the tab is hidden: every poll costs Stash a plugin process launch.
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const block = source.slice(source.indexOf("  const STATUS_ACTIVE_MS"), source.indexOf("  function slateKey("));

let visibilityListener = null;
const document = {
  visibilityState: "visible",
  addEventListener(event, callback) { assert.equal(event, "visibilitychange"); visibilityListener = callback; },
  removeEventListener(event, callback) { assert.equal(callback, visibilityListener); visibilityListener = null; },
};
const timers = new Map();
let nextTimer = 1;
let calls = 0;
let reply = { health: { active_jobs: [] }, jobs: [] };
const effects = [];
const context = {
  document,
  setTimeout(callback, ms) { const id = nextTimer++; timers.set(id, { callback, ms }); return id; },
  clearTimeout(id) { timers.delete(id); },
  operation: async (args) => { assert.equal(args.operation, "get_status"); calls++; return reply; },
  React: {
    useState: (value) => [value, () => {}],
    useEffect: (effect) => effects.push(effect),
  },
};
vm.createContext(context);
vm.runInContext(block + "\nthis.useCuratorStatus = useCuratorStatus; this.curatorStatus = curatorStatus;", context);
const settle = () => new Promise((resolve) => setImmediate(resolve));
const pending = () => [...timers.values()].map((timer) => timer.ms);

(async () => {
  // Two views mount: one request, one idle timer.
  context.useCuratorStatus();
  context.useCuratorStatus();
  const cleanups = effects.splice(0).map((effect) => effect());
  await settle();
  assert.equal(calls, 1);
  assert.deepEqual(pending(), [15000]);
  assert.ok(visibilityListener);

  // A running job switches to the fast cadence.
  reply = { health: { active_jobs: [{ job_id: "a" }] }, jobs: [{ state: "running" }] };
  [...timers.values()][0].callback();
  await settle();
  assert.equal(calls, 2);
  assert.deepEqual(pending(), [4000]);
  assert.equal(context.curatorStatus.value, reply);

  // Hidden: no timer at all; visible again: an immediate refresh.
  document.visibilityState = "hidden";
  visibilityListener();
  assert.deepEqual(pending(), []);
  document.visibilityState = "visible";
  visibilityListener();
  await settle();
  assert.equal(calls, 3);
  assert.deepEqual(pending(), [4000]);

  // Failures are reported and polling continues.
  context.operation = async () => { calls++; throw new Error("Stash request failed"); };
  [...timers.values()][0].callback();
  await settle();
  assert.equal(context.curatorStatus.error, "Stash request failed");
  assert.equal(pending().length, 1);

  // The last view unmounting stops polling.
  cleanups.forEach((cleanup) => cleanup());
  assert.deepEqual(pending(), []);
  assert.equal(visibilityListener, null);

  assert.doesNotMatch(source, /setInterval\(refresh, 4000\)/);
  assert.equal((source.match(/operation\(\{ operation: "get_job_status" \}\)/g) || []).length, 0);
})().catch((error) => { console.error(error); process.exitCode = 1; });
