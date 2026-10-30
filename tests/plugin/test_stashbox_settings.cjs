const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const defaultEndpoint = "https://stashdb.org/graphql";
const otherEndpoint = "https://example.test/graphql";
const boxes = [{ name: "StashDB", endpoint: defaultEndpoint }, { name: "Other server", endpoint: otherEndpoint }];

test("external links use their saved source and preserve legacy StashDB links", () => {
  const context = vm.createContext({ URL });
  vm.runInContext(source.slice(source.indexOf("  function stashboxEntityURL("), source.indexOf("  const ExternalCard =")), context);
  assert.equal(context.stashboxEntityURL({}, "scenes", "one"), "https://stashdb.org/scenes/one");
  assert.equal(context.stashboxEntityURL({ curator_endpoint: "https://fansdb.cc/graphql/" }, "tags", "two"), "https://fansdb.cc/tags/two");
  assert.equal(context.stashboxEntityURL({ curator_endpoint: "https://javstash.org/graphql" }, "performers", "three"), "https://javstash.org/performers/three");
  assert.equal(context.stashboxEntityURL({ curator_endpoint: "https://example.test/box/graphql" }, "scenes", "a/b"), "https://example.test/box/scenes/a%2Fb");
  assert.equal(context.stashboxEntityURL({ curator_endpoint: "javascript:alert(1)" }, "scenes", "one"), undefined);
  const tpdb = { curator_endpoint: "https://theporndb.net/graphql" };
  assert.equal(context.stashboxEntityURL(tpdb, "performers", "parent"), "https://theporndb.net/performers/parent");
  assert.equal(context.stashboxEntityURL(tpdb, "performers", "site", { curator_site_performer: true }), "https://theporndb.net/performer-sites/site");
});
function nodes(node) {
  return node && typeof node === "object" ? [node, ...(node.children || []).flat(Infinity).flatMap(nodes)] : [];
}

test("endpoint dropdown uses configured servers and saves without losing other settings", async () => {
  let hook = 0;
  let saved;
  const raw = { whisparrApiKey: "keep-existing-setting" };
  const state = [{ moods: [] }, raw, false, "", new Set(), {}, "", "", false, boxes];
  const context = vm.createContext({
    React: {
      createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
      useState: (initial) => {
        const index = hook++;
        if (state[index] === undefined) state[index] = initial;
        return [state[index], (value) => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
      },
      useEffect() {}, useRef: () => ({ current: false }),
    },
    useCuratorActivity() {}, clearEndlessCache() {}, Button: "button",
    configurePlugin: async (values) => { saved = values; },
    getPluginSettings: async () => saved,
    LANES: [], HOME_DEFAULT_LANES: new Set(),
  });
  vm.runInContext(source.slice(source.indexOf("  const SETTINGS_GENDER_OPTIONS"), source.indexOf("  // Manage shell")), context);
  function render() {
    hook = 0;
    return nodes(context.SettingsPanel({ diversityEnabled: null })).find((node) => node.type === context.SettingsField && node.props.field.key === "stashBoxEndpoint");
  }
  let field = render();
  assert.equal(field.props.field.type, "SELECT");
  assert.equal(field.props.value, defaultEndpoint);
  assert.deepEqual(Array.from(field.props.field.options, (option) => option.value), boxes.map((box) => box.endpoint));
  assert.match(field.props.field.options[1].label, /Other server/);
  const select = nodes(context.SettingsField(field.props)).find((node) => node.type === "select");
  select.props.onChange({ target: { value: otherEndpoint } });
  // onChange delegates to the existing asynchronous save path.
  await new Promise(setImmediate);
  assert.equal(saved.stashBoxEndpoint, otherEndpoint);
  assert.equal(saved.whisparrApiKey, raw.whisparrApiKey);
  assert.equal(render().props.value, otherEndpoint);

  state[9] = [boxes[0]];
  field = render();
  assert.equal(field.props.field.options[0].value, otherEndpoint);
  assert.equal(field.props.field.options[0].disabled, true);
  assert.match(field.props.field.options[0].label, /not configured/);
  assert.equal(nodes(context.SettingsField(field.props)).find((node) => node.type === "option").props.disabled, true);
  state[9] = [];
  assert.equal(render().props.field.options[0].label, "No endpoints configured in Stash");
});

test("endpoint lookup requests names and URLs and surfaces Stash query failures", async () => {
  let query;
  let failure = false;
  const context = vm.createContext({ fetch: async (_url, request) => {
    query = JSON.parse(request.body).query;
    return { ok: true, json: async () => failure ? { errors: [{ message: "Stash unavailable" }] } : { data: { configuration: { general: { stashBoxes: boxes } } } } };
  } });
  vm.runInContext(source.slice(source.indexOf("  async function getStashBoxEndpoints("), source.indexOf("  function formatTimeAgo(")), context);
  assert.equal(await context.getStashBoxEndpoints(), boxes);
  assert.match(query, /stashBoxes \{ name endpoint \}/);
  assert.doesNotMatch(query, /api_key/);
  failure = true;
  await assert.rejects(context.getStashBoxEndpoints(), /Stash unavailable/);
});
