const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const hooks = [], observers = [];
let cursor, dirty, effects, tree;
const context = {
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
    createElement: (type, props, ...children) => { if (props?.ref) props.ref.current = {}; return { type, props, children }; },
  },
  Button: "button", window: { innerHeight: 800, IntersectionObserver: true },
  IntersectionObserver: class { constructor(fn, options) { this.fn = fn; this.options = options; observers.push(this); } observe() {} disconnect() { this.disconnected = true; } },
};
vm.runInNewContext(source.slice(source.indexOf("  function EndlessFindResults("), source.indexOf("  function relationshipChips(")), context);
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
const more = () => tree.children[2]?.children?.[0];
const flush = () => new Promise(setImmediate);
(async () => {
  let calls = [], settle;
  props = { first: { items: [{ id: "1" }], has_more: true }, page: 1, pageSize: 1, metadata: true,
    loadPage: page => { calls.push(page); return new Promise((resolve, reject) => { settle = { resolve, reject }; }); },
    renderPage: (batch, ready) => { batches.push({ batch, ready }); return batch; },
  };
  render();
  assert.equal(more().props.disabled, true); // Wait for Stash metadata before advancing.
  batches[0].ready(1); render();
  assert.equal(observers.at(-1).options.rootMargin, "0px 0px 1600px 0px");
  observers.at(-1).fn([{ isIntersecting: true }]);
  observers.at(-1).fn([{ isIntersecting: true }]);
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

  hooks.length = 0; observers.length = 0;
  props = { ...props, metadata: false, first: { items: [] }, clientItems: Array.from({ length: 5 }, (_, index) => ({ id: String(index + 1) })), pageSize: 2,
    loadPage: () => { throw Error("Client paging must not refetch the catalog"); },
  };
  render(); more().props.onClick(); await flush(); render(); more().props.onClick(); await flush(); render();
  assert.equal(batches.map(value => value.batch.items.map(item => item.id).join(",")).join("|"), "1,2|3,4|5");
  assert.equal(more(), undefined);
  props.clientItems = props.clientItems.map(item => ({ ...item, shortlisted: true }));
  render();
  assert.equal(batches[2].batch.items[0].shortlisted, true);
  console.log("Find endless loading, metadata guard, retry and client paging checks passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
