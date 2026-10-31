const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const hooks = [];
const element = (type, props = {}, ...children) => ({ type, key: props?.key, props: { ...props, children } });
const homeRemovals = [];
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
  useHistory: () => ({}),
  installPerformerAffinitySort() {}, installSceneAffinitySort() {}, configureAffinityFilter() {}, configureLaneFilter() {},
  addPerformerAffinitySortOption() {}, addSceneAffinitySortOption() {},
  CuratorNavItem: "curator-nav", EvidenceScore: "score", CuratorSceneAffinityPill: "scene-pill", CuratorLaneListView: "lane-view",
  CuratorPerformerCardBadge: "performer-badge", CuratorContextLink: "context-link",
  CuratorPerformerSortLocale: "performer-locale",
  CuratorSceneSortLocale: "scene-locale", CuratorSceneAffinityCards: "affinity-cards",
  PerformerHuntLink: "hunt", CuratorHomeSlates: "home-slates", CuratorHomeSync: "home-sync", CuratorHomeLane: "home-lane",
  CuratorHomeEditor: "home-editor", HOME_ENTRY_TYPE: "CuratorLane", laneByValue: new Map([["for_you", { value: "for_you" }]]),
  saveHomeRemovals: async (content) => { homeRemovals.push(content); }, formatAppealValue: () => "0.8", SCENE_AFFINITY_SORT: "curator_appeal",
});

// The FrontPage patch's own helpers run for real.
for (const name of ["isHomeEntry", "placeHomeRows"]) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, name);
  vm.runInContext(source.slice(start, source.indexOf("\n  }\n", start) + "\n  }\n".length), context);
}

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
  HoverPopover: { className: "unrelated-popover", content: nativeChild },
  "SceneCard.Details": {},
  "MainNavBar.MenuItems": { children: [nativeChild] },
  FilteredPerformerList: { filterHook: (filter) => filter },
  FilteredSceneList: { filterHook: (filter) => filter },
  SceneList: { scenes: [{ id: "1" }] },
  "SceneCard.Overlays": { scene: { id: "1", title: "Scene" } },
  "PerformerCard.Overlays": { performer: { id: "1", name: "Performer" } },
  ScenePage: { scene: { id: "1", title: "Scene" } },
  PerformerPage: { performer: { id: "1", name: "Performer" } },
  FrontPage: {},
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

// Stash's runInstead, verbatim: next() wraps each later instead patch in a new
// Proxy per render. A prior plugin rendering its continuation as <Original />
// (Stash TV) remounts the page, resetting its tabs, unless that continuation is
// Stash's stable component.
for (const name of ["ScenePage", "PerformerPage"]) {
  const target = () => element("native");
  const fns = [(props, ...args) => element(args[args.length - 1], props),
    ...hooks.filter((hook) => hook.name === name && hook.kind === "instead").map((hook) => hook.callback)];
  function runInstead(argArray) {
    let i = 1;
    function next() {
      if (i >= fns.length) return target;
      const thisTarget = fns[i++];
      return new Proxy(thisTarget, { apply: (fn, ctx, args) => fn.apply(ctx, args.concat(next())) });
    }
    return fns[0].apply(undefined, argArray.concat(next()));
  }
  const [first, second] = [0, 1].map(() => runInstead([cases[name]]).type);
  assert.equal(first, second, `${name}: a JSX continuation keeps its component type across renders`);
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

// FrontPage: each Curator entry in Stash's rows view becomes that lane's row
// in place, unknown lanes and Stash's rows (with any other plugin's
// additions) survive, the Customise editor keeps its onClose contract, and
// the saving spinner is left alone.
const frontPage = hooks.find((hook) => hook.name === "FrontPage").callback;
const control = (key, content) => element("control", { key, content });
const otherRows = element("other-plugin-rows");
const footer = element("div", { className: "recommendations-footer" });
const rowsView = (...rows) => element("div", { className: "recommendations-container" }, element("div", {}, rows), footer);
(async () => {
  for (const extra of [[], [{ pluginContext: true }, "another-argument"]]) {
    const native = control(0, { __typename: "CustomFilter" });
    const retired = control(2, { __typename: "CuratorLane", lane: "retired_lane" });
    const front = frontPage({}, ...extra, rowsView(native, control(1, { __typename: "CuratorLane", lane: "for_you" }), retired, otherRows));
    assert.equal(front.type, "home-slates");
    assert.deepEqual([...front.props.lanes], ["for_you"]);
    const [sync, view] = front.props.children;
    assert.equal(sync.type, "home-sync");
    assert.equal(view.props.className, "recommendations-container");
    const rows = children(view.props.children[0].props.children);
    assert.deepEqual(rows.map((row) => row.type), ["control", "home-lane", "control", "other-plugin-rows"]);
    assert.equal(rows[1].key, 1);
    assert.equal(rows[1].props.lane.value, "for_you");
    assert.ok(rows.includes(native) && rows.includes(retired) && contains(view, footer));
    // No list yet (a fresh install before Stash writes its default).
    const empty = frontPage({}, ...extra, element("div", { className: "recommendations-container" }, element("div", {}, undefined), footer));
    assert.deepEqual([...empty.props.lanes], []);
    // Another plugin's FrontPage patch ran first: it wrapped the view, or put
    // its own rows before Stash's list. Curator still finds the list.
    const lane = () => control(1, { __typename: "CuratorLane", lane: "for_you" });
    const wrapped = frontPage({}, ...extra, element("other-plugin-wrapper", {}, otherRows, rowsView(native, lane())));
    assert.deepEqual([...wrapped.props.lanes], ["for_you"]);
    const wrapper = wrapped.props.children[1];
    assert.equal(wrapper.type, "other-plugin-wrapper");
    assert.equal(children(wrapper.props.children)[0], otherRows);
    const wrappedRows = children(children(wrapper.props.children)[1].props.children[0].props.children);
    assert.deepEqual(wrappedRows.map((row) => row.type), ["control", "home-lane"]);
    const ahead = element("div", { className: "recommendations-container" }, element("other-plugin-list", {}, otherRows), element("div", {}, [native, lane()]), footer);
    const aheadView = frontPage({}, ...extra, ahead).props.children[1];
    const [theirs, list, foot] = children(aheadView.props.children);
    assert.equal(theirs.type, "other-plugin-list");
    assert.deepEqual(children(list.props.children).map((row) => row.type), ["control", "home-lane"]);
    assert.equal(foot, footer);
    // A view nested deeper than Curator looks is left alone.
    const deep = element("a", {}, element("b", {}, element("c", {}, element("d", {}, rowsView(lane())))));
    assert.equal(frontPage({}, ...extra, deep), deep);
  }
  const closed = [];
  const editor = element("front-page-config", { onClose: (content) => closed.push(content) });
  const wrapped = frontPage({}, editor);
  assert.equal(wrapped.type, "home-editor");
  const config = children(wrapped.props.children)[0];
  assert.equal(config.type, "front-page-config");
  const saved = [{ __typename: "CustomFilter" }];
  config.props.onClose(saved);
  config.props.onClose(undefined);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(closed, [saved, undefined]);
  assert.deepEqual(homeRemovals, [saved, undefined]);
  assert.equal(frontPage({}, null), null);
  const plain = element("front-page-config");
  assert.equal(frontPage({}, plain), plain);
  const spinner = element("div", { className: "recommendations-container-edit" });
  assert.equal(frontPage({}, spinner), spinner);
  const unknown = element("div", { className: "recommendations-container" }, "text");
  assert.equal(frontPage({}, unknown), unknown);
})().catch((error) => { console.error(error); process.exitCode = 1; });
