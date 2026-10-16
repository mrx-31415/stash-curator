const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require("node:path").join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const patches = new Map(), calls = [], operations = [];
let adapter, failPage = false, failScores = false;
const client = {
  link: {}, setLink(link) { adapter = link; },
  async query(request) {
    calls.push(request);
    assert.notEqual(request.variables.filter.sort, "curator_appeal");
    assert.equal(request.variables.scene_filter, null);
    assert.equal(request.context.token, "preserved");
    if (failPage) throw new Error("Page failed");
    return { data: { findScenes: { __typename: "FindScenesResultType", count: 2, duration: 2, filesize: 2,
      scenes: request.variables.scene_ids.slice().reverse().map((id) => ({ id: String(id), title: `Scene ${id}` })) } } };
  },
};
class ApolloLink {
  constructor(callback) { this.callback = callback; }
  concat(link) { this.next = link; return this; }
}
class Observable { constructor(subscribe) { this.subscribe = subscribe; } }
class StringCriterionOption {
  constructor(options) {
    Object.assign(this, options);
    this.makeCriterionFn = () => ({ criterionOption: this, modifier: this.defaultModifier, value: "",
      fromDecodedParams(saved) { this.value = saved.value; this.modifier = saved.modifier; },
    });
  }
  makeCriterion() { return this.makeCriterionFn(this); }
}
let effect, state, contextScores;
const element = (type, props, ...children) => ({ type, props: { ...props, children } });
const context = {
  URLSearchParams, NavLink: "NavLink", faClone: "clone",
  Api: { utils: { StashService: { getClient: () => client } }, patch: {
    before: (name, callback) => patches.set(`before:${name}`, callback),
    after: (name, callback) => patches.set(`after:${name}`, callback),
  } },
  libraries: { Apollo: { ApolloLink, Observable } },
  React: {
    isValidElement: (item) => Boolean(item?.props), createElement: element,
    cloneElement: (item, props) => ({ ...item, props: { ...item.props, ...props } }), Fragment: "fragment",
    createContext: () => ({ Provider: "provider" }), useState: () => [null, (value) => { state = value; }],
    useEffect: (callback) => { effect = callback; }, useContext: () => contextScores,
    Children: { forEach: (children, callback) => { for (const child of children || []) callback(child); } },
  },
  operation: async (args, timeout) => {
    operations.push(args);
    if (failScores) throw new Error("Scores failed");
    if (args.operation === "get_scene_affinities") return { affinities: { "3": { appeal: 0.2, confidence: 0.8 }, "2": { appeal: 0, confidence: 0.4 } } };
    assert.equal(timeout, 120000, "Allow full-library native metadata aggregation to finish");
    const empty = args.per_page === 0 || args.page > 2;
    return { scene_ids: empty ? [] : ["3", "2"], affinities: {}, count: 5, duration: 500, filesize: 10000 };
  },
  CuratorAffinityGauge() {}, FontAwesomeIcon() {}, faCompass: "compass", clamp01: (value) => Math.max(0, Math.min(1, value)),
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function configureAffinityFilter("), source.indexOf("  function matchesPerformerAffinity(")), context);
vm.runInContext(source.slice(source.indexOf("  const SCENE_AFFINITY_SORT ="), source.indexOf("  function CuratorPerformerCardBadge(")), context);
vm.runInContext(source.slice(source.indexOf("  function CuratorContextControls("), source.indexOf("  function CuratorContextLink(")), context);
const request = (sort = "curator_appeal", criterion) => ({
  query: "native-page", operationName: "FindScenes", getContext: () => ({ token: "preserved" }),
  variables: { scene_ids: [1, 2, 3, 4, 5], filter: { sort, direction: "DESC", page: 1, per_page: 2, q: "query" },
    scene_filter: { rating100: { modifier: "GREATER_THAN", value: 20 }, ...(criterion ? { curator_appeal: criterion } : {}) } },
});
const plain = (value) => JSON.parse(JSON.stringify(value));
(async () => {
  const before = patches.get("before:FilteredSceneList");
  const options = { sortByOptions: [{ value: "title" }], criterionOptions: [new StringCriterionOption({ type: "title" })] };
  const filter = { options, criteria: [] };
  const patched = before({ filterHook: (item) => ({ ...item, preserved: true }) })[0];
  assert.ok(patched.filterHook(filter).preserved);
  context.addSceneAffinitySortOption(element("list", null, element("toolbar", { filter })));
  context.addSceneAffinitySortOption(element("toolbar", { filter }));
  assert.equal(filter.options.sortByOptions.length, 2);
  assert.equal(options.sortByOptions.length, 1);
  const option = options.criterionOptions.find((item) => item.type === "curator_appeal");
  const criterion = option.makeCriterion(); criterion.value = "0.15";
  assert.ok(criterion.isValid()); assert.equal(criterion.toCriterionInput().value, 0.15);
  criterion.value = ""; assert.equal(criterion.isValid(), false);
  criterion.value = "Infinity"; assert.equal(criterion.isValid(), false);
  criterion.modifier = "IS_NULL"; assert.ok(criterion.isValid());
  const restored = context.configureAffinityFilter({ options, criteria: [{
    criterionOption: { type: "curator_appeal", messageID: "unsupported_criterion" },
    toQueryParams: () => ({ modifier: "LESS_THAN", value: "-0.15" }),
  }] }, "curator_appeal");
  assert.equal(restored.criteria[0].toCriterionInput().value, -0.15);
  const first = await context.affinitySortedScenes(client, request());
  assert.deepEqual(Array.from(first.data.findScenes.scenes, (item) => item.id), ["3", "2"]);
  assert.equal(first.data.findScenes.count, 5);
  assert.equal(first.data.findScenes.duration, 500);
  assert.equal(first.data.findScenes.filesize, 10000);
  assert.deepEqual(plain(operations.at(-1).scene_filter), { rating100: { modifier: "GREATER_THAN", value: 20 } });
  assert.equal(operations.at(-1).filter.sort, "title");
  assert.equal(operations.at(-1).filter.q, "query");
  assert.deepEqual(plain(operations.at(-1).scene_ids), [1, 2, 3, 4, 5]);
  assert.equal(calls.at(-1).variables.filter.per_page, 2);
  await context.affinitySortedScenes(client, request("date", { modifier: "NOT_NULL" }));
  assert.equal(operations.at(-1).sort, false);
  assert.equal(operations.at(-1).filter.sort, "date");
  assert.equal(operations.at(-1).filter.direction, "DESC");
  assert.deepEqual(plain(operations.at(-1).criterion), { modifier: "NOT_NULL" });
  await context.affinitySortedScenes(client, request("date", { modifier: "GREATER_THAN", value: "0.15" }));
  assert.deepEqual(plain(operations.at(-1).criterion), { modifier: "GREATER_THAN", value: 0.15 });
  await assert.rejects(context.affinitySortedScenes(client, request("date", { modifier: "GREATER_THAN", value: "" })), /valid Curator Appeal/);
  const metadata = request(); metadata.variables.filter.per_page = 0;
  const callCount = calls.length;
  assert.equal((await context.affinitySortedScenes(client, metadata)).data.findScenes.count, 5);
  assert.equal(calls.length, callCount);
  failPage = true; await assert.rejects(context.affinitySortedScenes(client, request()), /Page failed/); failPage = false;
  failScores = true; await assert.rejects(context.affinitySortedScenes(client, request()), /Scores failed/); failScores = false;
  assert.equal(adapter.callback(request("date"), () => "native"), "native");
  assert.equal(adapter.callback({ ...request(), operationName: "FindPerformers" }, () => "native"), "native");
  let emitted = false;
  const unsubscribe = adapter.callback(request(), () => assert.fail("Unexpected native query")).subscribe({
    next() { emitted = true; }, complete() {}, error(error) { throw error; },
  });
  unsubscribe(); await new Promise((resolve) => setImmediate(resolve)); assert.equal(emitted, false);
  const wrapped = patches.get("after:SceneList")({ scenes: [{ id: "3" }, { id: "2" }] }, null, element("grid"));
  assert.equal(wrapped.props.ids, '["3","2"]');
  context.CuratorSceneAffinityCards(wrapped.props);
  const cleanup = effect(); await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(plain(operations.at(-1)), { operation: "get_scene_affinities", scene_ids: ["3", "2"] });
  assert.equal(state["2"].appeal, 0); cleanup();
  contextScores = state;
  const badge = context.CuratorSceneAffinityPill({ id: "2" });
  assert.equal(badge.props.children[1].props.value, 0);
  assert.equal(badge.props.children[1].props.confidenceLabel, "Confidence 40%");
  const similar = badge.props.children[2];
  const query = new URL(similar.props.to, "http://example.test").searchParams;
  assert.equal(query.get("view"), "similar");
  assert.equal(query.get("type"), "scene");
  assert.equal(query.get("id"), "2");
  assert.equal(similar.props.title, similar.props["aria-label"]);
  assert.match(badge.props.className, /curator-context-group-scene/);
  assert.equal(context.CuratorSceneAffinityPill({ id: "4" }).props.children[1].props.confidenceLabel, "No estimate");
  contextScores = null; assert.equal(context.CuratorSceneAffinityPill({ id: "3" }), null);
  const page = context.CuratorContextControls({ type: "scene", id: "2", label: "Scene", details: { score: { appeal: -0.4, confidence: 0.8 } } });
  assert.equal(page.type, context.CuratorSceneAffinityPill);
  const pagePill = context.CuratorSceneAffinityPill(page.props);
  assert.match(pagePill.props.className, /curator-scene-page-pill/);
  assert.equal(pagePill.props.children[1].props.value, -0.4);
  assert.equal(pagePill.props.children[1].props.confidenceLabel, "Confidence 80%");
  assert.equal(pagePill.props.children[2].props.title, "Find similar scenes with Curator");
  const overlays = patches.get("after:SceneCard.Overlays");
  assert.equal(patches.has("after:SceneCard"), false, "avoid writing overlay props onto theme wrappers");
  for (const original of [element("native-overlay", { selecting: true }), null, element("studio-logo", {}), []]) {
    const patched = overlays({ scene: { id: "3", title: "Example" } }, null, original);
    assert.equal(patched.props.children[0], original, "preserve native and themed overlays");
    const badge = patched.props.children[1];
    assert.equal(badge.type, context.CuratorSceneAffinityPill);
    assert.equal(badge.props.id, "3");
    assert.equal(badge.props.label, "Example");
    assert.equal(overlays({ scene: { id: "3" }, curatorAppeal: 0.2 }, null, original), original);
    assert.equal(overlays({}, null, original), original);
  }
  const emptyReplacement = overlays({ scene: { id: "3" } }, {});
  assert.equal(emptyReplacement.props.children[0].length, 0, "Stash spreads an empty replacement array into no result arguments");
  const themedOverlays = [element("studio-logo", {}), element("theme-marker", {})];
  const multiple = overlays({ scene: { id: "3" } }, {}, ...themedOverlays);
  assert.deepEqual(Array.from(multiple.props.children[0]), themedOverlays, "preserve every replacement overlay");
  console.log("scene affinity checks passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
