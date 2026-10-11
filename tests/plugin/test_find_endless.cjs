const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const hooks = [], observers = [];
let cursor, dirty, effects, tree;
const stored = new Map(), listeners = new Map();
let frames = [], scroll = 0;
const root = {
  addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name),
  querySelectorAll: () => (batches || []).map(({ batch }, index) => ({ dataset: { endlessPage: String(batch.page) }, querySelectorAll: () => [], getBoundingClientRect: () => ({ top: index * 100 - scroll, bottom: (index + 1) * 100 - scroll }) })),
  querySelector(selector) { return selector === "[data-endless-page]" ? this.querySelectorAll()[0] : this.querySelectorAll().find(node => selector.includes(`"${node.dataset.endlessPage}"`)); },
};
const context = {
  cachedConfigUpdatedAtMs: 1,
  sessionStorage: { getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value), removeItem: key => stored.delete(key) },
  requestAnimationFrame: fn => { frames.push(fn); return frames.length; }, cancelAnimationFrame() {},
  React: {
    Fragment: "fragment",
    useState(initial) {
      const i = cursor++;
      if (!(i in hooks)) hooks[i] = typeof initial === "function" ? initial() : initial;
      return [hooks[i], change => { const value = typeof change === "function" ? change(hooks[i]) : change; dirty ||= value !== hooks[i]; hooks[i] = value; }];
    },
    useRef(initial) { const i = cursor++; return hooks[i] ||= { current: initial }; },
    useCallback(fn) { const i = cursor++; return hooks[i] ||= fn; },
    useEffect(fn, deps) {
      const i = cursor++, previous = hooks[i];
      if (!previous || deps.some((value, index) => value !== previous.deps[index])) effects.push(() => { previous?.cleanup?.(); hooks[i] = { deps, cleanup: fn() }; });
    },
    createElement: (type, props, ...children) => { if (props?.ref) props.ref.current = props.className?.includes("curator-endless-results") ? root : { type }; return { type, props, children }; },
  },
  Button: "button", window: { innerHeight: 800, IntersectionObserver: true,
    addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name),
    scrollBy: ({ top }) => { scroll += top; },
  },
  IntersectionObserver: class { constructor(fn, options) { this.fn = fn; this.options = options; observers.push(this); } observe() {} disconnect() { this.disconnected = true; } },
};
vm.runInNewContext(source.slice(source.indexOf('  const ENDLESS_CACHE_KEY'), source.indexOf("  function virtualWallRange(")), context);
let props, batches;
function render() {
  let count = 0;
  do {
    cursor = 0; dirty = false; effects = []; batches = [];
    tree = context.EndlessFindResults(props);
    for (const effect of effects) effect();
    assert.ok(++count < 10, "render loop");
  } while (dirty);
  return tree;
}
const more = () => tree.children[3]?.children?.[0];
const flush = () => new Promise(setImmediate);
(async () => {
  let calls = [], settle;
  props = { cacheKey: "library", first: { items: [{ id: "1" }], has_more: true }, page: 1, pageSize: 1, metadata: true,
    loadPage: page => { calls.push(page); return new Promise((resolve, reject) => { settle = { resolve, reject }; }); },
    renderPage: (batch, ready) => { batches.push({ batch, ready }); return batch; },
  };
  render();
  assert.equal(more().props.disabled, true); // Wait for Stash metadata before advancing.
  batches[0].ready(1); render();
  assert.equal(observers.at(-1).options.rootMargin, "0px 0px 3200px 0px");
  const target = observers.at(-1);
  target.fn([{ isIntersecting: true, target: more() }]);
  target.fn([{ isIntersecting: true, target: more() }]);
  await flush();
  assert.deepEqual(calls, [2]);
  settle.reject(Error("Temporary failure")); await flush(); render();
  assert.equal(more().children[0], "Retry");
  more().props.onClick(); await flush();
  assert.deepEqual(calls, [2, 2]);
  settle.resolve({ items: [{ id: "2" }], has_more: true }); await flush(); render();
  assert.equal(batches.length, 2);
  assert.equal(batches[0].batch.items[0].id, "1");
  assert.equal(more().props.disabled, true);
  batches[1].ready(2); render(); more().props.onClick(); await flush();
  settle.resolve({ items: [{ id: "3" }], has_more: false }); await flush(); render();
  assert.equal(batches.length, 3);
  assert.equal(more(), undefined);

  for (const hook of hooks) hook?.cleanup?.();
  hooks.length = 0; observers.length = 0;
  props = { ...props, cacheKey: "client", metadata: false, first: { items: [] }, clientItems: Array.from({ length: 5 }, (_, index) => ({ id: String(index + 1) })), pageSize: 2,
    loadPage: () => { throw Error("Client paging must not refetch the catalog"); },
  };
  render(); more().props.onClick(); await flush(); render(); more().props.onClick(); await flush(); render();
  assert.equal(batches.map(value => value.batch.items.map(item => item.id).join(",")).join("|"), "1,2|3,4|5");
  assert.equal(more(), undefined);
  props.clientItems = props.clientItems.map(item => ({ ...item, shortlisted: true }));
  render();
  assert.equal(batches[2].batch.items[0].shortlisted, true);
  // A deep return retains nearby batches, never replays all preceding requests.
  for (const hook of hooks) hook?.cleanup?.();
  hooks.length = 0; observers.length = 0;
  const pages = Array.from({ length: 100 }, (_, index) => ({ page: index + 1, items: [{ id: String(index + 1) }], has_more: true }));
  context.saveEndlessCache("deep", pages, { page: 90, offset: -25 });
  const saved = context.readEndlessCache("deep");
  assert.equal(saved.pages.length, 12);
  assert.equal(saved.pages[0].page, 85);
  calls = [];
  let failEarlier = true;
  props = { ...props, cacheKey: "deep", first: pages[0], clientItems: null, pageSize: 1,
    loadPage: async number => { calls.push(number); if (number === 84 && failEarlier) { failEarlier = false; throw Error("Earlier failed"); } return pages[number - 1]; },
  };
  scroll = 0; frames = [];
  render();
  assert.equal(batches.length, 12);
  assert.equal(more().props.disabled, true);
  frames.splice(0).forEach(fn => fn()); render();
  assert.equal(scroll, 525);
  assert.deepEqual(calls, []);
  more().props.onClick(); await flush(); render();
  assert.deepEqual(calls, [97]);
  tree.children[0].children[0].props.onClick(); await flush(); render();
  assert.equal(more().children[0], "Retry");
  more().props.onClick(); await flush(); render();
  frames.splice(0).forEach(fn => fn()); render();
  assert.deepEqual(calls, [97, 84, 84]);
  assert.equal(scroll, 625); // Prepending retains the visible content.
  listeners.get("scroll")(); listeners.get("click")();
  for (const hook of hooks) hook?.cleanup?.();
  assert.equal(context.readEndlessCache("deep").anchor.page, 90);
  // Simulate a full document load, where only sessionStorage survives.
  const fresh = { ...context };
  vm.runInNewContext(source.slice(source.indexOf('  const ENDLESS_CACHE_KEY'), source.indexOf("  function virtualWallRange(")), fresh);
  assert.equal(fresh.readEndlessCache("deep").anchor.page, 90);
  context.clearEndlessCache();
  assert.equal(context.readEndlessCache("deep"), null);
  for (let index = 0; index < 8; index++) context.saveEndlessCache(`view-${index}`, pages, { page: 90, offset: 0 });
  assert.equal(context.readEndlessCache("view-0"), null);
  assert.ok(stored.values().next().value.length <= 1000000);
  context.saveEndlessCache("large", pages.map(batch => ({ ...batch, payload: "x".repeat(200000) })), { page: 90, offset: 0 });
  assert.ok(context.readEndlessCache("large").pages.some(batch => batch.page === 90));
  assert.ok(stored.values().next().value.length <= 1000000);
  // A changed generation cannot be mixed into the restored list.
  hooks.length = 0;
  props = { ...props, cacheKey: "changed", first: pages[0], loadPage: async () => ({ ...pages[1], model_id: "other" }) };
  render(); more().props.onClick(); await flush(); render();
  assert.equal(batches.length, 1);
  assert.match(tree.children[2].children[0], /Results changed/);
  for (const hook of hooks) hook?.cleanup?.();
  hooks.length = 0; frames = []; scroll = 0;
  context.saveEndlessCache("metadata-return", pages, { page: 90, offset: -25 });
  props = { ...props, cacheKey: "metadata-return", metadata: true };
  render();
  assert.equal(frames.length, 0); // Restore only after library details set the layout.
  batches.forEach(({ batch, ready }) => ready(batch.page)); render();
  frames.splice(0).forEach(fn => fn()); render();
  assert.equal(scroll, 525);
  for (const hook of hooks) hook?.cleanup?.();
  hooks.length = 0; frames = []; scroll = 0;
  const nested = {
    scrollHeight: 5000, clientHeight: 600, getBoundingClientRect: () => ({ top: 100 }),
    addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name),
    scrollBy: ({ top }) => { scroll += top; },
  };
  root.parentElement = nested;
  context.window.getComputedStyle = () => ({ overflowY: "auto" });
  context.saveEndlessCache("nested", pages, { page: 90, offset: -25 });
  props = { ...props, cacheKey: "nested", metadata: false };
  render(); frames.splice(0).forEach(fn => fn()); render();
  assert.equal(scroll, 425);
  assert.equal(observers.at(-1).options.root, nested);
  const timeouts = [], cancelled = [];
  const operationContext = {
    AbortController, actionError: message => message,
    setTimeout: (_, duration) => { timeouts.push(duration); return duration; },
    clearTimeout: id => cancelled.push(id),
    fetch: async () => ({ ok: true, json: async () => ({ data: { runPluginOperation: {} } }) }),
  };
  vm.runInNewContext(source.slice(source.indexOf("  async function operation("), source.indexOf("  function slateKey(")), operationContext);
  await operationContext.operation({ operation: "get_expand" });
  await operationContext.operation({ operation: "get_similar" });
  await operationContext.operation({ operation: "get_expand" }, 60000);
  assert.deepEqual(timeouts, [120000, 30000, 60000]);
  assert.deepEqual(cancelled, timeouts);
  for (const hook of hooks) hook?.cleanup?.();
  const filters = { includeTags: [{ id: "tag", name: "Tag" }], excludeTags: [], performers: [], studios: [], gender: "FEMALE" };
  context.saveEndlessCache("filtered", pages, { page: 90, offset: 0 }, filters);
  const filterReturn = { ...context };
  vm.runInNewContext(source.slice(source.indexOf('  const ENDLESS_CACHE_KEY'), source.indexOf("  function virtualWallRange(")), filterReturn);
  assert.equal(JSON.stringify(filterReturn.readEndlessRecommendationFilters().filters), JSON.stringify(filters));
  let resets = 0;
  Object.assign(context, { moodID: "", setMoods() {}, readMoodID: () => "", selectMood: () => { resets++; context.clearEndlessCache(); } });
  vm.runInNewContext(source.slice(source.indexOf("    function applyMoods("), source.indexOf("    const restoredSlateFilters")), context);
  context.applyMoods([], false);
  assert.ok(context.readEndlessCache("filtered")); // Initial config must preserve a valid return snapshot.
  assert.equal(resets, 0);
  context.applyMoods([]);
  assert.equal(resets, 1); // Explicit mood changes still reset results.
  context.moodID = "deleted"; context.readMoodID = () => "deleted";
  context.applyMoods([{ id: "together" }], false);
  assert.equal(resets, 2); // A removed mood cannot restore an incompatible list.
  // Playback refreshes recommendations without losing the list we left behind.
  Object.assign(context, { slateCache: new Map([["lane", {}]]), slateRequests: new Map(), similarityCache: new Map(),
    cachedModelId: "model", cachedConfigUpdatedAtMs: 1, cacheGeneration: 0, SLATE_CACHE_KEY: "slate", laneExclusions: new Map() });
  vm.runInNewContext(source.slice(source.indexOf("  function persistSlateCache("), source.indexOf("  function writePage(")), context);
  context.saveEndlessCache("playback", pages, { page: 90, offset: -25 }, filters);
  context.clearSlateCache(true);
  assert.ok(context.readEndlessCache("playback"));
  assert.equal(context.slateCache.size, 0);
  assert.equal(JSON.parse(stored.get("slate")).configUpdatedAtMs, 1);
  const returning = { ...context };
  vm.runInNewContext(source.slice(source.indexOf('  const ENDLESS_CACHE_KEY'), source.indexOf("  function virtualWallRange(")), returning);
  assert.equal(returning.readEndlessCache("playback").anchor.page, 90);
  const first = { model_id: "model", config_updated_at_ms: 1, items: [{ scene_id: "1" }], total: 100 };
  const identity = ["recommendations", "for_you", filters, { seed: 1 }];
  assert.equal(context.endlessBatchKey(first, identity), context.endlessBatchKey({ ...first, items: [{ scene_id: "2" }], total: 99 }, identity));
  assert.notEqual(context.endlessBatchKey(first, identity), context.endlessBatchKey({ ...first, model_id: "new" }, identity));
  context.clearSlateCache();
  assert.equal(context.readEndlessCache("playback"), null);
  console.log("Find endless loading, metadata guard, retry and client paging checks passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
