const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const hooks = [];
let cursor = 0;
let effects = [];
let dirty = false;
let top = 0;
let frame;
let next;
let restarts = 0;
let calls = [];
let queriedIDs = [];
let metadataError = null;
const listeners = new Map();
const observers = [];
const dom = { getBoundingClientRect: () => ({ top, width: 800 }), scrollIntoView: () => { top = 0; } };
const context = {
  React: {
    Fragment: "fragment",
    useState(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = typeof initial === "function" ? initial() : initial;
      return [hooks[index], (value) => { hooks[index] = typeof value === "function" ? value(hooks[index]) : value; dirty = true; }];
    },
    useRef(initial) {
      const index = cursor++;
      return hooks[index] ||= { current: initial };
    },
    useEffect(fn, deps) {
      const index = cursor++;
      const old = hooks[index];
      if (!old || deps.some((value, i) => value !== old.deps[i])) {
        effects.push(() => { old?.cleanup?.(); hooks[index] = { deps, cleanup: fn() }; });
      }
    },
    createElement(type, props, ...children) {
      if (props?.ref && typeof props.ref === "object") props.ref.current = dom;
      return { type, props, children };
    },
  },
  window: {
    innerHeight: 600, IntersectionObserver: true,
    getComputedStyle: () => ({ gridTemplateColumns: "190px 190px 190px 190px", columnGap: "10px" }),
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: (name) => listeners.delete(name),
  },
  IntersectionObserver: class {
    constructor(fn) { this.fn = fn; observers.push(this); }
    observe(node) { this.node = node; }
    disconnect() { this.disconnected = true; }
  },
  requestAnimationFrame: (fn) => { frame = fn; return 1; }, cancelAnimationFrame() {},
  GQL: { useFindScenesQuery: ({ variables, skip }) => {
    queriedIDs = skip ? [] : variables.scene_ids;
    return { loading: false, error: metadataError, data: { findScenes: { scenes: queriedIDs.filter((id) => id !== 122).map((id) => ({ id: String(id), title: `Scene ${id}` })) } } };
  } },
  loadSlate: async (...args) => { calls.push(args); if (next instanceof Error) throw next; return next; },
  Button: "button", ThumbnailTile: "thumbnail", PreviewTile: "preview", RecommendationCard: "card",
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function virtualWallRange("), source.indexOf("  function RecommendationCard(")), context);
const range = context.virtualWallRange(10000, 4, 120, 6000, 600);
assert.equal(range.first, 192);
assert.equal(range.last, 228);
assert.equal(range.height, 300000);
assert.equal(range.offset, 5760);
assert.equal(context.virtualWallRange(0, 4, 120, 0, 600).last, 0);
assert.equal(context.virtualWallRange(3, 4, 120, 0, 600).last, 3);
const items = Array.from({ length: 120 }, (_, index) => ({ scene_id: String(index + 1), impression_id: "first", position: index }));
const slate = { items, page: 1, has_more: true, model_id: "model", config_updated_at_ms: 1, mood_id: "", lane: "for_you" };
const props = { slate, visibleItems: items, scenes: new Map(items.map((item) => [item.scene_id, { id: item.scene_id }])), lane: "for_you", filters: { includeTags: ["tag"] }, thumbnails: true, onRestart: () => { restarts++; } };
function render() {
  let tree;
  let runs = 0;
  do {
    dirty = false; cursor = 0; effects = [];
    tree = context.EndlessRecommendations(props);
    for (const effect of effects) effect();
    assert.ok(++runs < 20, "render loop");
  } while (dirty);
  return tree;
}
const tiles = (tree) => tree.children[0].children[0].children[0];
const load = (tree) => tree.children[1].children.at(-1).props.onClick();
(async () => {
  let tree = render();
  assert.ok(tiles(tree).length < 40); // DOM size depends on viewport, not loaded count.
  assert.equal(queriedIDs.length, 0);
  top = -2000; listeners.get("scroll")(); frame();
  tree = render();
  assert.notEqual(tiles(tree)[0].props.entry.scene_id, "1");
  next = { ...slate, page: 2, items: [items[0], { scene_id: "121" }, { scene_id: "122" }], has_more: true };
  await load(tree);
  tree = render();
  assert.deepEqual(calls[0].slice(0, 3), ["for_you", 2, false]);
  assert.equal(calls[0][3], props.filters);
  assert.equal(hooks[0].length, 121); // Duplicate and deleted scenes are omitted.
  assert.ok(queriedIDs.length <= 3); // Metadata fetches stay bounded to one page.
  next = new Error("Offline");
  await load(tree);
  tree = render();
  assert.equal(tree.children[1].children[0].children[0], "Offline");
  assert.equal(tree.children[1].children.at(-1).children[0], "Retry");
  next = { ...slate, page: 3, items: [{ scene_id: "123" }], has_more: false };
  metadataError = { message: "Metadata failed" };
  await load(tree);
  tree = render();
  assert.equal(hooks[1].page, 2); // Metadata failure must not advance the cursor.
  metadataError = null;
  await load(tree);
  tree = render();
  assert.equal(hooks[0].length, 122);
  assert.equal(tree.children[1].children.at(-1).children[0], "End of recommendations");
  assert.equal(calls[3][1], 3); // Retry requests the same page.
  hooks[1] = { ...next, has_more: true };
  tree = render();
  next = { ...slate, page: 4, model_id: "new-model" };
  await load(tree);
  assert.equal(restarts, 1); // Never mix model/config generations.
  for (const hook of hooks) hook?.cleanup?.();
  assert.equal(listeners.size, 0);
  hooks.length = 0;
  const recorded = [];
  let timer;
  context.setTimeout = (fn, delay) => { assert.equal(delay, 1000); timer = fn; return 1; };
  context.clearTimeout = () => { timer = null; };
  context.enqueue = (event) => recorded.push(event);
  const seen = new Set();
  const tileProps = { entry: { item: items[0], scene_id: "1", slate }, thumbnails: true, index: 0, seen };
  function renderTile() {
    cursor = 0; effects = [];
    context.EndlessRecommendationTile(tileProps);
    for (const effect of effects) effect();
  }
  renderTile();
  const observer = observers.at(-1);
  observer.fn([{ intersectionRatio: 0.5 }]);
  assert.ok(timer);
  observer.fn([{ intersectionRatio: 0 }]);
  assert.equal(timer, null); // Passing through overscan must not count as viewed.
  observer.fn([{ intersectionRatio: 0.5 }]);
  timer();
  assert.equal(recorded.length, 1);
  for (const hook of hooks) hook?.cleanup?.();
  hooks.length = 0;
  renderTile();
  assert.equal(recorded.length, 1); // Remounting must not record a second impression.
  for (const hook of hooks) hook?.cleanup?.();
  hooks.length = 0;
  top = 0;
  props.cards = true;
  props.onRemove = () => {};
  props.onThumbDown = () => {};
  tree = render();
  assert.equal(tree.children[0].type, "section");
  assert.equal(tree.children[0].props.className, "curator-grid curator-endless-cards");
  const firstCard = tree.children[0].children[0][0];
  assert.equal(firstCard.props.onRemove, props.onRemove);
  assert.equal(firstCard.props.onThumbDown, props.onThumbDown);
  assert.equal(listeners.size, 0); // Variable-height cards use native offscreen rendering.
  next = { ...slate, page: 2, items: [{ scene_id: "121", impression_id: "second" }], has_more: false };
  await load(tree);
  tree = render();
  const cards = tree.children[0].children[0];
  assert.equal(cards.length, 121);
  assert.equal(cards[0].props.key, firstCard.props.key); // Appending preserves existing card state.
  assert.equal(cards.at(-1).props.slate.page, 2);
  assert.equal(cards.at(-1).props.item.impression_id, "second");
  assert.equal(tree.children[1].children.at(-1).children[0], "End of recommendations");
  for (const hook of hooks) hook?.cleanup?.();
})().catch((error) => { console.error(error); process.exitCode = 1; });
