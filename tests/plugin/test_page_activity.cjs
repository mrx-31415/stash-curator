const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
let tick, visibilityChange, cleanup, request;
let heartbeats = 0;
const document = {
  visibilityState: "visible",
  addEventListener(event, callback) { assert.equal(event, "visibilitychange"); visibilityChange = callback; },
  removeEventListener(event, callback) { assert.equal(event, "visibilitychange"); assert.equal(callback, visibilityChange); },
};
const context = {
  document,
  React: { useEffect(effect) { cleanup = effect(); } },
  operation: async (args) => { assert.equal(args.operation, "page_activity"); heartbeats++; },
  setInterval(callback, ms) { assert.equal(ms, 20000); tick = callback; return 1; },
  clearInterval(id) { assert.equal(id, 1); },
  fetch: async (_url, options) => {
    request = JSON.parse(options.body);
    return { ok: true, json: async () => ({ data: { runPluginTask: "queued" } }) };
  },
};
vm.createContext(context);
const start = source.indexOf("  function CuratorPage()");
vm.runInContext(source.slice(start, source.indexOf("    const history =", start)) + "  }", context);
context.CuratorPage();
assert.equal(heartbeats, 1);
tick();
assert.equal(heartbeats, 2);
document.visibilityState = "hidden";
tick();
assert.equal(heartbeats, 2);
document.visibilityState = "visible";
visibilityChange();
assert.equal(heartbeats, 3);
cleanup();

vm.runInContext(source.slice(source.indexOf("  async function runTask("), source.indexOf("  function scheduleModelUpdate(")), context);
(async () => {
  await context.runTask("Refresh Expand cache");
  assert.equal(request.variables.args.automatic, false);
  await context.runTask("Apply recent Curator feedback", true);
  assert.equal(request.variables.args.automatic, true);
  assert.match(request.query, /args_map: \$args/);
  assert.equal((source.match(/runTask\("Apply recent Curator feedback", true\)/g) || []).length, 1);
  assert.doesNotMatch(source, /scheduleModelMaintenance/);
  assert.match(source, /runTask\("Sync recent plays", true\)/);
  assert.match(source, /await runTask\("Apply recent Curator feedback"\)\.catch/);
})().catch((error) => { console.error(error); process.exitCode = 1; });
