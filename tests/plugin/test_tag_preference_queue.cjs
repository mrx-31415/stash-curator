const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const slice = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));

function harness({ health, full = false, hold = true }) {
  const store = new Map();
  const calls = { submitted: [], tasks: [] };
  let release = null;
  const context = {
    JSON, Date, Set, Promise, setTimeout: (callback) => setImmediate(callback),
    TAG_PREFERENCE_QUEUE_KEY: "queue",
    localStorage: {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, value) => {
        if (full) throw new Error("QuotaExceededError");
        store.set(key, value);
      },
    },
    uuid: (() => { let n = 0; return () => `p${++n}`; })(),
    clearSlateCache: () => {},
    scheduleModelUpdate: () => {},
    runTask: async (name) => { calls.tasks.push(name); },
    operation: async (args) => {
      if (args.operation === "health") return health.shift();
      calls.submitted.push(args.entries.map((entry) => entry.tag_id));
      // Hold the first request open so later answers queue behind it.
      if (hold && calls.submitted.length === 1) await new Promise((resolve) => { release = resolve; });
    },
  };
  vm.createContext(context);
  vm.runInContext(
    slice("  const MODEL_REFRESH_POLL_MS", "  // Stash records plays")
      + slice("  // Stash and every plugin share one localStorage", "  // RatingRows renders"),
    context
  );
  return { context, calls, store, release: () => release() };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

(async () => {
  // Answers given while a flush is in flight are sent once it returns,
  // not left in the browser until the next page load.
  const app = harness({ health: [] });
  app.context.submitTagPreference("a", { value: 1, blocked: false });
  await settle();
  app.context.submitTagPreference("b", { value: 0.5, blocked: false });
  app.context.submitTagPreference("c", { value: -1, blocked: false });
  app.release();
  await app.context.flushTagPreferenceQueue();
  await settle();
  assert.equal(JSON.stringify(app.calls.submitted), JSON.stringify([["a"], ["b", "c"]]));
  assert.equal(app.store.get("queue"), "[]");

  // With storage full, an answer is sent directly instead of throwing from
  // the click handler.
  const full = harness({ health: [], full: true, hold: false });
  full.context.submitTagPreference("a", { value: 1, blocked: false });
  await settle();
  assert.equal(JSON.stringify(full.calls.submitted), JSON.stringify([["a"]]));
  assert.equal(full.store.has("queue"), false);

  // A large backlog drains in bounded batches, and the stored queue keeps
  // only the newest entries.
  const backlog = harness({ health: [], hold: false });
  backlog.store.set("queue", JSON.stringify(Array.from({ length: 450 }, (_, i) => ({ preference_id: `b${i}`, tag_id: `t${i}` }))));
  await backlog.context.flushTagPreferenceQueue();
  assert.equal(JSON.stringify(backlog.calls.submitted.map((batch) => batch.length)), JSON.stringify([200, 200, 50]));
  assert.equal(backlog.store.get("queue"), "[]");
  assert.equal(backlog.context.writeQueue("queue", Array.from({ length: 1005 }, (_, i) => i)), true);
  const kept = JSON.parse(backlog.store.get("queue"));
  assert.equal(kept.length, 1000);
  assert.equal(kept[0], 5);

  // Apply now sends queued answers first, and builds when feedback is
  // pending even below the automatic update threshold.
  const apply = harness({ health: [
    { model_id: "m1", model_pending: true, model_update_ready: false, model_rebuilding: false },
    { model_id: "m2", model_pending: false, model_update_ready: false, model_rebuilding: false },
  ] });
  apply.store.set("queue", JSON.stringify([{ preference_id: "x", tag_id: "x" }]));
  const pending = apply.context.applyFeedbackAndAwaitBuild();
  await settle();
  apply.release();
  assert.equal(await pending, true);
  assert.equal(JSON.stringify(apply.calls.submitted), JSON.stringify([["x"]]));
  assert.equal(JSON.stringify(apply.calls.tasks), JSON.stringify(["Apply recent Curator feedback"]));

  // With nothing pending it returns at once without starting a build.
  const idle = harness({ health: [{ model_id: "m1", model_pending: false, model_update_ready: false, model_rebuilding: false }] });
  assert.equal(await idle.context.applyFeedbackAndAwaitBuild(), false);
  assert.equal(idle.calls.tasks.length, 0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
