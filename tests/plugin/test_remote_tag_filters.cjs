const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
let state = ["remote", [], ""];
let index = 0;
let effect;
let timer;
let applied;
let response = { ready: true, items: [{ id: "1", name: "REMOTE LOCAL" }, { id: "2", name: "Remote Only" }] };
const requests = [];
const context = {
  React: {
    useState: () => { const position = index++; return [state[position], (value) => { state[position] = value; }]; },
    useEffect: (callback) => { effect = callback; },
    createElement: (type, props, ...children) => ({ type, props, children: children.flat().filter(Boolean) }),
  },
  GQL: {
    useFindTagsQuery: () => ({ data: { findTags: { tags: [{ id: "2", name: "Remote Local" }] } } }),
    useFindStudiosQuery: () => ({}), useFindPerformersQuery: () => ({}),
  },
  setTimeout: (callback) => { timer = callback; return 1; },
  clearTimeout: () => { timer = null; },
  operation: async (request) => { requests.push(request); return response; },
  Button: "button", FontAwesomeIcon: "icon", faHeart: "heart", faVenus: "gender",
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function FilterTokens("), source.indexOf("  function SavedFilters(")), context);
vm.runInContext(source.slice(source.indexOf("  function FilterBar("), source.indexOf("  function SimilarityPanel(")), context);
function nodes(node) { return node && typeof node === "object" ? [node, ...node.children.flatMap(nodes)] : []; }
function picker(searchBoth = true) {
  index = 0;
  return context.FilterTokens({ kind: "tag", label: "Exclude tags", values: [], searchBoth, onChange: (value) => { applied = value; } });
}

async function check() {
  picker();
  const cleanup = effect();
  assert.equal(requests.length, 0); // Debounced, no request during render.
  await timer();
  await Promise.resolve();
  assert.equal(requests[0].operation, "get_external_tag_search");
  let tree = nodes(picker());
  const options = tree.find((node) => node.props?.className === "curator-token-options");
  assert.equal(options.children.length, 2); // Same-name local tag wins.
  assert.equal(options.children[0].children[1].children[0], "Library");
  assert.equal(options.children[1].children[1].children[0], "StashDB");
  options.children[1].props.onClick();
  assert.equal(applied[0].name, "Remote Only");
  assert.equal(applied[0].id, "stashdb:2"); // Cannot collide with local id 2.
  assert.equal(state[0], "");
  cleanup();

  state[0] = "missing";
  response = { ready: false, items: [] };
  picker(); effect(); await timer(); await Promise.resolve();
  assert.match(nodes(picker()).find((node) => node.props?.role === "status").children[0], /Refresh Expand cache/);
  context.operation = async () => { throw new Error("Search unavailable"); };
  picker(); effect(); await timer(); await Promise.resolve();
  assert.equal(state[2], "Search unavailable");
  let finish;
  context.operation = () => new Promise((resolve) => { finish = resolve; });
  picker(); const cancel = effect(); timer(); cancel();
  finish({ ready: true, items: [{ id: "late", name: "Stale result" }] });
  await Promise.resolve();
  assert.equal(state[1].length, 0);
  picker(false); effect();
  assert.equal(state[1].length, 0);
  assert.equal(state[2], "");

  for (const [variant, source, expected] of [
    ["expand", undefined, true], ["hunt", undefined, true],
    ["similar", "stashdb", true], ["similar", "library", false],
    ["recommendations", undefined, false],
  ]) {
    const tags = nodes(context.FilterBar({ variant, source, entityType: "scene", minimum: 0 }))
      .filter((node) => node.type === context.FilterTokens && node.props.kind === "tag");
    assert.equal(tags.length, 2);
    assert.equal(tags.every((node) => node.props.searchBoth === expected), true);
  }
}
check().catch((error) => { console.error(error); process.exitCode = 1; });
