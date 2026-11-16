const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Two updateUrl calls in one event (a filter chip moving from include to
// exclude) must build on each other instead of the second overwriting the
// first, and leave a single history entry.
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const pushes = [];
const replaces = [];
let rendered;
let slots = [];
let index = 0;
const location = { pathname: "/plugins/stash-curator", search: "" };
const context = {
  URLSearchParams,
  React: {
    useState: (initial) => {
      const position = index++;
      if (!(position in slots)) slots[position] = typeof initial === "function" ? initial() : initial;
      return [slots[position], (value) => { slots[position] = value; }];
    },
    useRef: (value) => { const position = index++; if (!(position in slots)) slots[position] = { current: value }; return slots[position]; },
    useEffect: () => {},
  },
  useHistory: () => ({ push: (value) => pushes.push(value), replace: (value) => replaces.push(value) }),
  useLocation: () => location,
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function parseUrlState("), source.indexOf("  function pagerPages(")), context);
vm.runInContext(`spec = { defaults: { include: [], exclude: [], page: 1 }, fields: { include: urlListField("inc", []), exclude: urlListField("exc", []) }, page: urlPageSpec("page") };`, context);
function render() { index = 0; rendered = context.useUrlState(context.spec); return rendered; }

render();
let [, update] = rendered;
update((s) => ({ ...s, include: [{ id: "1", name: "Tag" }] }));
[, update] = render();
assert.equal(pushes.length, 1);

// Same event: drop it from include, then add it to exclude.
update((s) => ({ ...s, include: s.include.filter((item) => item.id !== "1") }));
update((s) => ({ ...s, exclude: [...s.exclude, { id: "1", name: "Tag" }] }));
const [state] = render();
assert.equal(JSON.stringify([state.include, state.exclude]), JSON.stringify([[], [{ id: "1", name: "Tag" }]]));
const search = new URLSearchParams([...pushes, ...replaces].at(-1).search);
assert.equal(search.get("inc"), null);
assert.equal(search.get("exc"), JSON.stringify([{ id: "1", name: "Tag" }]));
assert.equal(pushes.length, 2); // One entry for the move, not one per half.
assert.equal(replaces.length, 1);
