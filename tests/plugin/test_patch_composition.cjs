const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const hooks = [];
const element = (type, props = {}, ...children) => ({ type, key: props?.key, props: { ...props, children } });
const children = (value) => [value].flat(Infinity).filter((item) => item != null);
const context = vm.createContext({
  Api: { patch: Object.fromEntries(["before", "instead", "after"].map((kind) => [kind,
    (name, callback) => hooks.push({ kind, name, callback }),
  ])) },
  React: {
    createElement: element, Fragment: "fragment", isValidElement: (value) => Boolean(value?.props),
    cloneElement: (value, props, ...nextChildren) => ({ ...value, props: { ...value.props, ...props, children: nextChildren } }),
    Children: {
      // React.Children.toArray rewrites keys while preserving component types.
      toArray: (value) => children(value).map((child) => child?.key == null ? child : { ...child, key: `.$${child.key}` }),
      map: (value, callback) => children(value).map(callback),
    },
  },
  window: { location: { pathname: "/performers" } },
  useHistory: () => ({}), activeLanePlaylist: () => null,
  installPerformerAffinitySort() {}, installSceneAffinitySort() {}, configureAffinityFilter() {},
  addPerformerAffinitySortOption() {}, addSceneAffinitySortOption() {},
  CuratorNavItem: "curator-nav", EvidenceScore: "score", CuratorSceneAffinityPill: "scene-pill",
  CuratorPerformerCardBadge: "performer-badge", CuratorContextLink: "context-link",
  LanePlaylistControls: "playlist", CuratorPerformerSortLocale: "performer-locale",
  CuratorSceneSortLocale: "scene-locale", CuratorSceneAffinityCards: "affinity-cards",
  PerformerHuntLink: "hunt", formatAppealValue: () => "0.8", SCENE_AFFINITY_SORT: "curator_appeal",
});

// Load every registered callback, so adding a patch also requires a coverage case.
for (const match of source.matchAll(/^  Api\.patch\.(before|instead|after)\("([^\"]+)", function/gm)) {
  const end = source.indexOf("\n  });", match.index);
  assert.ok(end > match.index);
  vm.runInContext(source.slice(match.index, end + "\n  });".length), context);
}
assert.equal(hooks.length, [...source.matchAll(/Api\.patch\.(before|instead|after)\(/g)].length,
  "every patch registration must be loaded by the composition test");

// Stash ui/v2.5/src/patch.tsx: before replaces args; instead chains next;
// after receives args.concat(result), which flattens array results.
function invoke(name, target, args, receiver, otherFirst, extra) {
  const registered = hooks.filter((hook) => hook.name === name);
  const otherBefore = { kind: "before", callback: (props) => [props, ...extra] };
  const otherInstead = { kind: "instead", callback: function (...args) {
    const next = args.pop();
    return next.apply(this, args);
  } };
  const chain = otherFirst ? [otherBefore, otherInstead, ...registered] : [...registered, otherBefore, otherInstead];
  for (const hook of chain.filter((hook) => hook.kind === "before")) args = hook.callback.apply(receiver, args);
  const instead = chain.filter((hook) => hook.kind === "instead");
  function run(index, current) {
    if (index === instead.length) return target.apply(receiver, current);
    const next = function (...forwarded) { return run(index + 1, forwarded); };
    return instead[index].callback.apply(receiver, current.concat(next));
  }
  let result = run(0, args);
  for (const hook of chain.filter((hook) => hook.kind === "after")) result = hook.callback.apply(receiver, args.concat(result));
  return result;
}

const nativeChild = element("native-child");
const cases = {
  ScenePlayer: { scene: { id: "1" } },
  HoverPopover: { className: "unrelated-popover", content: nativeChild },
  "SceneCard.Details": {}, "SceneCard.Popovers": {},
  "MainNavBar.MenuItems": { children: [nativeChild] },
  FilteredPerformerList: { filterHook: (filter) => filter },
  FilteredSceneList: { filterHook: (filter) => filter },
  SceneList: { scenes: [{ id: "1" }] },
  "SceneCard.Overlays": { scene: { id: "1", title: "Scene" } },
  "PerformerCard.Overlays": { performer: { id: "1", name: "Performer" } },
  ScenePage: { scene: { id: "1", title: "Scene" } },
  PerformerPage: { performer: { id: "1", name: "Performer" } },
};
assert.deepEqual([...new Set(hooks.map((hook) => hook.name))].sort(), Object.keys(cases).sort());
function contains(tree, value) {
  if (tree === value) return true;
  if (Array.isArray(tree)) return tree.some((child) => contains(child, value));
  if (tree?.props) return Object.values(tree.props).some((child) => contains(child, value));
  return false;
}
let checks = 0;
for (const [name, props] of Object.entries(cases)) {
  const arrayResults = hooks.some((hook) => hook.name === name && hook.kind === "instead");
  const results = [element("native", { existingAttribute: true }, nativeChild), null];
  if (arrayResults) results.push([], [element("theme-one"), element("theme-two")]);
  for (const original of results) for (const extra of [[], [undefined], [{ pluginContext: true }, "another-argument"]]) {
    for (const otherFirst of [true, false]) {
      const receiver = { pluginReceiver: true };
      let calls = 0;
      const output = invoke(name, function (forwarded, ...rest) {
        calls++;
        assert.equal(this, receiver, `${name}: renderer context`);
        assert.deepEqual(rest, extra, `${name}: trailing arguments`);
        if (props.filterHook) assert.equal(forwarded.filterHook("native-filter"), "native-filter");
        return original;
      }, [props, { nativeContext: true }], receiver, otherFirst, extra);
      assert.equal(calls, 1, `${name}: render exactly once`);
      if (name === "MainNavBar.MenuItems" && original) {
        assert.equal(output.props.existingAttribute, true);
        assert.ok(contains(output, nativeChild));
      } else assert.ok(contains(output, original), `${name}: preserve complete original result`);
      checks++;
    }
  }
}

// A prior after-hook can add menu children not present in the original props.
const themeItem = element("theme-menu");
const menu = element("nav", {}, nativeChild, themeItem);
const navbar = hooks.find((hook) => hook.name === "MainNavBar.MenuItems").callback;
const patched = navbar({ children: [nativeChild] }, menu);
assert.ok(contains(patched, themeItem));
assert.equal(children(patched.props.children).filter((child) => child.type === "curator-nav").length, 1);
const repeated = navbar({ children: [nativeChild] }, patched);
assert.equal(children(repeated.props.children).filter((child) => child.type === "curator-nav").length, 1);
console.log(`${checks} hook composition cases passed across ${Object.keys(cases).length} Stash surfaces`);
