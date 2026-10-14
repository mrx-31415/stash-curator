const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const patches = new Map();
let adapter, idsQueries = 0, failIds = false, failPage = false;
const calls = [];
const client = {
  link: {}, setLink(link) { adapter = link; },
  async query(request) {
    calls.push(request);
    assert.notEqual(request.variables.filter.sort, "curator_affinity");
    assert.ok(!request.variables.performer_filter?.curator_affinity, "Do not send affinity filters to Stash");
    assert.equal(request.context.token, "test-context");
    if (request.query === "ids") {
      idsQueries++;
      if (failIds) throw new Error("ID query failed");
      assert.equal(request.variables.filter.per_page, -1);
      const ids = ["1", "2", "3", "4", "5", "6"];
      if (request.variables.filter.direction === "DESC") ids.reverse();
      return { data: { findPerformers: { performers: ids.map((id) => ({ id })) } } };
    }
    if (failPage) throw new Error("Page query failed");
    assert.equal(request.variables.performer_filter, null);
    return { data: { findPerformers: { count: request.variables.performer_ids.length,
      performers: [...request.variables.performer_ids].reverse().map((id) => ({ id: String(id), name: `Performer ${id}` })) } } };
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
const context = {
  libraries: { Apollo: { gql: () => "ids", ApolloLink, Observable } },
  Api: { utils: { StashService: { getClient: () => client } }, patch: {
    before: (name, callback) => patches.set(`before:${name}`, callback),
    after: (name, callback) => patches.set(`after:${name}`, callback),
  } },
  window: { location: { pathname: "/performers" } },
  React: { isValidElement: (element) => Boolean(element?.props), Children: {
    forEach: (children, callback) => { for (const child of children || []) callback(child); },
  } },
  loadPerformerAffinities: async () => ({ affinities: {
    "1": { affinity: 0.1 }, "2": { affinity: 0.8 }, "3": { affinity: null },
    "4": { affinity: -0.2 }, "5": { affinity: 0.8 }, "6": { affinity: 0 },
  } }),
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  const PERFORMER_AFFINITY_SORT ='), source.indexOf('  const SCENE_AFFINITY_SORT =')), context);
const request = (direction = "DESC", page = 1, performerFilter = { filter_favorites: true }) => ({
  query: "page", operationName: "FindPerformers", getContext: () => ({ token: "test-context" }),
  variables: { filter: { sort: "curator_affinity", direction, page, per_page: 2, q: "query" }, performer_filter: performerFilter },
});
const resultIds = (result) => Array.from(result.data.findPerformers.performers, (item) => item.id);
(async () => {
  const before = patches.get("before:FilteredPerformerList");
  const props = { filterHook: (filter) => ({ ...filter, extra: "preserved" }) };
  const patched = before(props)[0];
  const options = { sortByOptions: [{ value: "name" }], criterionOptions: [new StringCriterionOption({ type: "name" })] };
  const filter = { options, criteria: [] };
  assert.equal(patched.filterHook(filter).extra, "preserved");
  const element = { props: { children: [{ props: { filter, children: [] } }] } };
  context.addPerformerAffinitySortOption(element);
  context.addPerformerAffinitySortOption(element);
  assert.equal(filter.options.sortByOptions.length, 2);
  assert.equal(options.sortByOptions.length, 1, "Do not change shared Stash filter options");
  assert.equal(options.criterionOptions.length, 2, "Register the criterion for Stash's dialog and saved filters");
  const affinityOption = options.criterionOptions.find((option) => option.type === "curator_affinity");
  const criterion = affinityOption.makeCriterion();
  criterion.value = "0.25";
  assert.ok(criterion.isValid());
  assert.equal(criterion.toCriterionInput().value, 0.25);
  criterion.value = "";
  assert.equal(criterion.isValid(), false);
  criterion.value = "wrong";
  assert.equal(criterion.isValid(), false);
  criterion.modifier = "IS_NULL";
  assert.ok(criterion.isValid());
  const restored = context.configureAffinityFilter({ options, criteria: [{
    criterionOption: { type: "curator_affinity", messageID: "unsupported_criterion" },
    toQueryParams: () => ({ modifier: "LESS_THAN", value: "-0.15" }),
  }] });
  assert.equal(restored.criteria[0].toCriterionInput().value, -0.15);
  before(props);
  assert.ok(adapter.next === client.link);
  const first = await context.affinitySortedPerformers(client, request());
  assert.deepEqual(resultIds(first), ["2", "5"]);
  assert.equal(first.data.findPerformers.count, 6);
  assert.deepEqual(resultIds(await context.affinitySortedPerformers(client, request("DESC", 2))), ["1", "6"]);
  assert.deepEqual(resultIds(await context.affinitySortedPerformers(client, request("DESC", 3))), ["4", "3"]);
  assert.deepEqual(resultIds(await context.affinitySortedPerformers(client, request("ASC"))), ["4", "6"]);
  assert.equal(idsQueries, 1);
  const affinityFilter = (modifier, value, sort = "curator_affinity", page = 1, direction = "DESC") => {
    const result = request(direction, page, { filter_favorites: true, curator_affinity: { modifier, value } });
    result.variables.filter.sort = sort;
    return result;
  };
  assert.deepEqual(resultIds(await context.affinitySortedPerformers(client, affinityFilter("GREATER_THAN", 0.1))), ["2", "5"]);
  const none = await context.affinitySortedPerformers(client, affinityFilter("GREATER_THAN", 1));
  assert.equal(none.data.findPerformers.count, 0);
  assert.deepEqual(resultIds(none), []);
  const second = await context.affinitySortedPerformers(client, affinityFilter("NOT_NULL", 0, "curator_affinity", 2));
  assert.equal(second.data.findPerformers.count, 5);
  assert.deepEqual(resultIds(second), ["1", "6"]);
  assert.deepEqual(resultIds(await context.affinitySortedPerformers(client, affinityFilter("IS_NULL"))), ["3"]);
  assert.deepEqual(resultIds(await context.affinitySortedPerformers(client, affinityFilter("EQUALS", 0))), ["6"]);
  assert.deepEqual(resultIds(await context.affinitySortedPerformers(client, affinityFilter("LESS_THAN", 0))), ["4"]);
  assert.equal(context.matchesPerformerAffinity(null, { modifier: "NOT_EQUALS", value: 0 }), false);
  assert.equal(context.matchesPerformerAffinity(-0.2, { modifier: "NOT_EQUALS", value: 0 }), true);
  assert.throws(() => context.matchesPerformerAffinity(0, { modifier: "GREATER_THAN", value: NaN }), /valid Curator affinity/);
  assert.throws(() => context.matchesPerformerAffinity(0, { modifier: "BAD", value: 0 }), /Unsupported/);
  assert.equal(idsQueries, 1, "Threshold changes reuse Stash's matching ID list");
  const metadata = affinityFilter("NOT_NULL"); metadata.variables.filter.per_page = 0;
  assert.equal((await context.affinitySortedPerformers(client, metadata)).data.findPerformers.count, 5);
  const native = await context.affinitySortedPerformers(client, affinityFilter("NOT_NULL", 0, "name"));
  assert.deepEqual(resultIds(native), ["6", "5"], "Keep native descending name order when only filtering affinity");
  assert.equal(idsQueries, 2);
  // Return to the affinity-sorting key for the remaining cache checks.
  await context.affinitySortedPerformers(client, request());
  const empty = await context.affinitySortedPerformers(client, request("DESC", 5));
  assert.equal(empty.data.findPerformers.count, 6);
  assert.deepEqual(resultIds(empty), []);
  const all = request(); all.variables.filter.per_page = -1;
  assert.deepEqual(resultIds(await context.affinitySortedPerformers(client, all)), ["2", "5", "1", "6", "4", "3"]);
  const filtered = request("DESC", 1, { gender: "FEMALE" });
  await context.affinitySortedPerformers(client, filtered);
  assert.equal(idsQueries, 4);
  assert.equal(calls.findLast((call) => call.query === "ids").variables.performer_filter.gender, "FEMALE");
  assert.equal(calls.findLast((call) => call.query === "ids").variables.filter.q, "query");
  failIds = true;
  await assert.rejects(context.affinitySortedPerformers(client, request("DESC", 1, {})), /ID query failed/);
  failIds = false;
  await context.affinitySortedPerformers(client, request("DESC", 1, {}));
  failPage = true;
  await assert.rejects(context.affinitySortedPerformers(client, request("DESC", 1, {})), /Page query failed/);
  failPage = false;
  assert.equal(adapter.callback({ variables: { filter: { sort: "name" } } }, () => "native"), "native");
  assert.equal(adapter.callback({ ...request(), operationName: "FindScenes" }, () => "native scenes"), "native scenes");
  let emitted = false;
  const subscription = adapter.callback(request(), () => { throw new Error("Unexpected native query"); });
  const unsubscribe = subscription.subscribe({ next() { emitted = true; }, complete() {}, error(error) { throw error; } });
  unsubscribe();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(emitted, false);
  context.window.location.pathname = "/tags/1";
  assert.ok(before(props)[0].filterHook);
  console.log("performer affinity sort checks passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
