const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
let state = ["studio", [], ""];
let index = 0;
let effect;
let timer;
let applied;
const response = { items: [{ id: "a", name: "STUDIO LOCAL", parent_name: null }, { id: "7", name: "Remote Site", parent_name: "Example Network" }] };
const requests = [];
const context = {
  React: {
    useState: () => { const position = index++; return [state[position], (value) => { state[position] = value; }]; },
    useEffect: (callback) => { effect = callback; },
    createElement: (type, props, ...children) => ({ type, props, children: children.flat().filter(Boolean) }),
  },
  GQL: {
    useFindTagsQuery: () => ({}), useFindPerformersQuery: () => ({}),
    useFindStudiosQuery: () => ({ data: { findStudios: { studios: [{ id: "7", name: "Studio Local" }] } } }),
  },
  setTimeout: (callback) => { timer = callback; return 1; },
  clearTimeout: () => { timer = null; },
  operation: async (request) => { requests.push(request); return response; },
  Button: "button", FontAwesomeIcon: "icon", faHeart: "heart", faVenus: "gender",
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function FilterTokens("), source.indexOf("  function SavedFilters(")), context);
vm.runInContext(source.slice(source.indexOf("  function FilterBar("), source.indexOf("  function SimilarityPanel(")), context);
const same = (actual, expected) => assert.equal(JSON.stringify(actual), JSON.stringify(expected));
function nodes(node) { return node && typeof node === "object" ? [node, ...node.children.flatMap(nodes)] : []; }
function picker(searchBoth = true) {
  index = 0;
  return context.FilterTokens({ kind: "studio", label: "Studios", values: [], searchBoth, onChange: (value) => { applied = value; } });
}

async function check() {
  picker();
  const cleanup = effect();
  await timer();
  await Promise.resolve();
  assert.equal(JSON.stringify(requests[0]), JSON.stringify({ operation: "get_stashdb_studio_search", query: "studio", limit: 8 }));
  const options = nodes(picker()).find((node) => node.props?.className === "curator-token-options");
  assert.equal(options.children.length, 2); // Same-name library studio wins.
  assert.equal(options.children[0].children[1].children[0], "Library");
  assert.equal(options.children[1].children[0].children[0], "Remote Site (Example Network)");
  assert.equal(options.children[1].children[1].children[0], "Stash-box");
  options.children[1].props.onClick();
  assert.equal(applied[0].name, "Remote Site"); // Filters match scenes by name.
  assert.equal(applied[0].id, "stashdb-studio:7"); // Cannot collide with local id 7.
  cleanup();

  state[0] = "studio";
  context.operation = async () => { throw new Error("Stash-box down"); };
  picker(); effect(); await timer(); await Promise.resolve();
  assert.equal(state[2], "Stash-box down");

  requests.length = 0;
  context.operation = async (request) => { requests.push(request); return response; };
  picker(false); effect();
  assert.equal(requests.length, 0);
  assert.equal(nodes(picker(false)).find((node) => node.props?.className === "curator-token-options").children.length, 1);

  // One box, two lists: new picks include; the chip's mode switch moves an
  // item between the lists; removing works from either list.
  let include = [{ id: "1", name: "Kept" }];
  let exclude = [{ id: "2", name: "Hidden" }];
  const both = () => { index = 0; state[0] = ""; return context.FilterTokens({ kind: "studio", label: "Studios", values: include, onChange: (value) => { include = value; }, excluded: exclude, onExcludedChange: (value) => { exclude = value; } }); };
  let chips = nodes(both()).filter((node) => node.props?.className?.startsWith?.("curator-token-chip"));
  same(chips.map((node) => node.props.className), ["curator-token-chip curator-token-include", "curator-token-chip curator-token-exclude"]);
  chips[0].children[0].props.onClick();
  same([include.map((item) => item.name), exclude.map((item) => item.name)], [[], ["Hidden", "Kept"]]);
  chips = nodes(both()).filter((node) => node.props?.className?.startsWith?.("curator-token-chip"));
  chips[0].children[0].props.onClick();
  same([include.map((item) => item.name), exclude.map((item) => item.name)], [["Hidden"], ["Kept"]]);
  chips = nodes(both()).filter((node) => node.props?.className?.startsWith?.("curator-token-chip"));
  chips[1].children[1].props.onClick();
  same(exclude, []);
  // An item already in either list is not added again.
  index = 0; state[0] = "studio";
  exclude = [{ id: "7", name: "Studio Local" }];
  nodes(context.FilterTokens({ kind: "studio", label: "Studios", values: include, onChange: (value) => { include = value; }, excluded: exclude, onExcludedChange: (value) => { exclude = value; } }))
    .find((node) => node.props?.className === "curator-token-options").children[0].props.onClick();
  same(include.map((item) => item.name), ["Hidden"]);

  for (const [variant, source, expected] of [
    ["expand", undefined, true], ["hunt", undefined, true],
    ["similar", "stashdb", true], ["similar", "library", false],
    ["recommendations", undefined, false],
  ]) {
    const studios = nodes(context.FilterBar({ variant, source, entityType: "scene", minimum: 0, studios: [], excludeStudios: [], onExcludeStudiosChange: () => {} }))
      .filter((node) => node.type === context.FilterTokens && node.props.kind === "studio");
    assert.equal(studios.length, 1, variant);
    assert.equal(studios[0].props.searchBoth, expected, variant);
    assert.equal(Array.isArray(studios[0].props.excluded), true, variant);
  }
}
check().catch((error) => { console.error(error); process.exitCode = 1; });
