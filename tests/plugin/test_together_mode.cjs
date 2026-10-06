const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
let cookie = "other=1";
let writtenCookie;
const document = {};
Object.defineProperty(document, "cookie", {
  get: () => cookie,
  set: (value) => { writtenCookie = value; cookie = `other=1; ${value.split(";")[0]}`; },
});
const calls = [];
const cached = { items: [{ scene_id: "excluded" }] };
const context = {
  document, location: { protocol: "https:", pathname: "/plugin/stash-curator" },
  rotateDay() {}, slateKey: (lane, page) => `${lane}:${page}`,
  slateCache: new Map([["for_you:1", cached]]), slateRequests: new Map(),
  cacheGeneration: 0, laneExclusions: new Map(),
  rotationLane: () => ({ seed: "fixed", atMs: 1 }),
  rotation: {}, cachedModelId: null, cachedConfigUpdatedAtMs: null,
  saveRotation() {}, persistSlateCache() {},
  operation: async (args) => { calls.push(args); return { items: [], model_id: "model", config_updated_at_ms: 1 }; },
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function readMoodID("), source.indexOf("  function readFilterPresets(")), context);
vm.runInContext(source.slice(source.indexOf("  function loadSlate("), source.indexOf("  function prefetchLane(")), context);

let search = "";
let tagRequest;
let tagResult = { data: { findTags: { tags: [{ id: "1", name: "Alpha" }, { id: "2", name: "Beta" }] } } };
let changed;
context.React = {
  useState: (initial) => [typeof initial === "string" ? search : initial, (value) => { search = value; }],
  useEffect() {},
  createElement: (type, props, ...children) => ({ type, props, children: children.flat().filter(Boolean) }),
};
context.GQL = {
  useFindTagsQuery: (request) => { tagRequest = request; return tagResult; },
  useFindStudiosQuery: () => ({}), useFindPerformersQuery: () => ({}),
};
vm.runInContext(source.slice(source.indexOf("  function FilterTokens("), source.indexOf("  function SavedFilters(")), context);
function nodes(node) { return node && typeof node === "object" ? [node, ...node.children.flatMap(nodes)] : []; }
function picker(disabled = false) {
  return context.FilterTokens({ kind: "tag", label: "Excluded tags", values: [{ id: "2", name: "Beta" }], disabled, onChange: (value) => { changed = value; } });
}
let tree = nodes(picker());
assert.equal(tagRequest.skip, true);
assert.equal(tagRequest.variables.filter.per_page, 8);
tree.find((node) => node.type === "input").props.onChange({ target: { value: "Al" } });
tree = nodes(picker());
assert.equal(tagRequest.variables.filter.q, "Al");
assert.equal(tagRequest.skip, false);
const options = tree.find((node) => node.props?.className === "curator-token-options");
assert.equal(options.children[0].children[0].children[0], "Alpha");
options.children[0].props.onClick();
assert.equal(changed.map((item) => item.id).join(","), "2,1");
assert.equal(search, "");
nodes(picker()).find((node) => node.type === "button").props.onClick();
assert.equal(changed.length, 0);
const settingsSource = source.slice(source.indexOf("  function SettingsPanel("), source.indexOf("  const MANAGE_BODIES"));
assert.ok(settingsSource.indexOf('"Recommendations"') < settingsSource.indexOf('"Moods"'));
assert.ok(settingsSource.indexOf('"Recommendation variety"') < settingsSource.indexOf('"Moods"'));
assert.match(settingsSource, /className: "curator-record-meta".*Each mood hides/);
assert.match(settingsSource, /onChange: \(tags\) => saveMoods/);
assert.doesNotMatch(settingsSource, /Save exclusions|dropdown: true/);
assert.match(settingsSource, /"fieldset".*disabled: togetherSaving/);
vm.runInContext(settingsSource.slice(settingsSource.indexOf("    async function saveMoods("), settingsSource.indexOf("    async function saveField(")), context);

vm.runInContext(source.slice(source.indexOf("  function MoodMenu("), source.indexOf("  function PreviewWallToggle(")), context);
const choices = [];
let focusCount = 0;
const menuRef = { current: { open: true, querySelector: () => ({ focus: () => { focusCount += 1; } }) } };
context.React.useRef = () => menuRef;
Object.assign(context, { FontAwesomeIcon() {}, faHeart: "heart", faCog: "cog" });
const menuMoods = [{ id: "together", name: "Together" }, { id: "light", name: "Lighthearted" }];
for (const id of ["", "together", "light"]) {
  menuRef.current.open = true;
  const menu = context.MoodMenu({ moods: menuMoods, moodID: id, disabled: false, onSelect: (value) => choices.push(value), onManage: () => choices.push("settings") });
  const menuNodes = nodes(menu);
  assert.equal(menu.type, "details");
  const summary = menuNodes.find((node) => node.type === "summary");
  assert.equal(summary.children[1].children[0], id ? menuMoods.find((mood) => mood.id === id).name : "Moods");
  assert.equal(summary.props.className.includes("btn-primary"), Boolean(id));
  const items = menuNodes.filter((node) => node.props?.className === "curator-mood-option");
  assert.equal(items.length, 3);
  const selected = items.find((node) => node.props["aria-pressed"]);
  assert.equal(selected.children[0].children[0], "✓");
  selected.props.onClick();
  assert.equal(menuRef.current.open, false);
  menuNodes.find((node) => node.props?.className === "curator-mood-manage").props.onClick();
  menuRef.current.open = true;
  menu.props.onKeyDown({ key: "Escape", preventDefault() {} });
  assert.equal(menuRef.current.open, false);
}
assert.deepEqual(choices, ["", "settings", "together", "settings", "light", "settings"]);
assert.equal(focusCount, 9);

(async () => {
  const originalOperation = context.operation;
  let finishSave;
  let storedMoods = [{ id: "together", name: "Together", excluded_tags: [] }];
  let saving;
  let error;
  let invalidations = 0;
  const saves = [];
  Object.assign(context, {
    togetherSaveInFlight: { current: false },
    setTogetherSaving: (value) => { saving = value; },
    setError: (value) => { error = value; },
    setConfig: (value) => { storedMoods = value.moods; },
    onMoodsSaved() {},
    clearSlateCache: () => { invalidations += 1; },
    operation: (args) => { saves.push(args); return new Promise((resolve) => { finishSave = resolve; }); },
  });
  const nextMoods = [{ id: "light", name: "Lighthearted", excluded_tags: [{ id: "1", name: "Alpha" }] }];
  const pending = context.saveMoods(nextMoods);
  assert.equal(saving, true);
  assert.equal(storedMoods[0].id, "together");
  assert.equal(saves[0].values.moods[0].excluded_tags[0].id, "1");
  await context.saveMoods([]); // A second click cannot race the active save.
  assert.equal(saves.length, 1);
  finishSave({ config: { moods: nextMoods } });
  await pending;
  assert.equal(storedMoods[0].id, "light");
  assert.equal(saving, false);
  assert.equal(invalidations, 1);
  context.operation = async () => { throw new Error("Save failed"); };
  await context.saveMoods([]);
  assert.equal(error, "Save failed");
  assert.equal(storedMoods[0].id, "light");
  assert.equal(saving, false);
  context.operation = async () => ({ config: { moods: [] } });
  await context.saveMoods([]);
  assert.equal(storedMoods.length, 0);
  assert.equal(error, "");

  // Exercise creation, tag edits, rename, and deletion through Settings controls.
  const originalUseState = context.React.useState;
  const state = [{ moods: [{ id: "together", name: "Together", excluded_tags: [] }] }, {}, false, "", new Set(), {}, "", "", false];
  let hook = 0;
  context.React.useState = () => { const index = hook++; return [state[index], (value) => { state[index] = typeof value === "function" ? value(state[index]) : value; }]; };
  context.React.useRef = () => context.togetherSaveInFlight;
  context.React.Fragment = "fragment";
  Object.assign(context, { SETTINGS_FIELD_GROUPS: [], Button: "button", uuid: () => "created", useCuratorActivity() {} });
  context.operation = async (args) => ({ config: { moods: args.values.moods } });
  vm.runInContext(settingsSource.slice(0, settingsSource.indexOf("  // Manage shell")), context);
  function settings() { hook = 0; return nodes(context.SettingsPanel({ diversityEnabled: null })); }
  settings().find((node) => node.props?.["aria-label"] === "New mood name").props.onChange({ target: { value: "Relaxed" } });
  await settings().find((node) => node.type === "button" && node.children[0] === "Add mood").props.onClick();
  assert.equal(state[0].moods.length, 2);
  assert.equal(state[0].moods[1].name, "Relaxed");
  assert.equal(state[6], "created");
  await settings().find((node) => node.type === context.FilterTokens).props.onChange([{ id: 42, name: "Theme", extra: "discard" }]);
  assert.equal(state[0].moods[1].excluded_tags[0].id, "42");
  assert.equal(state[0].moods[1].excluded_tags[0].extra, undefined);
  await settings().find((node) => node.props?.["aria-label"] === "Mood name").props.onBlur({ target: { value: "Lighthearted" } });
  assert.equal(state[0].moods[1].id, "created");
  assert.equal(state[0].moods[1].name, "Lighthearted");
  await settings().find((node) => node.type === "button" && node.children[0] === "Delete mood").props.onClick();
  assert.equal(state[0].moods.length, 1);
  await settings().find((node) => node.type === "button" && node.children[0] === "Delete mood").props.onClick();
  assert.equal(state[0].moods.length, 0);
  assert.equal(settings().some((node) => node.type === context.FilterTokens), false);
  context.React.useState = originalUseState;

  context.operation = originalOperation;
  assert.equal(context.readTogetherMode(), false);
  assert.equal(await context.loadSlate("for_you"), cached);
  cookie = "other=1; curator_together=1";
  assert.equal(context.readMoodID(), "together");
  context.writeMoodID("light");
  assert.match(writtenCookie, /Max-Age=31536000; SameSite=Lax; Secure/);
  assert.equal(context.readTogetherMode(), true);
  const filtered = await context.loadSlate("for_you");
  assert.equal(filtered.items.length, 0);
  assert.equal(calls[0].together_mode, true);
  assert.equal(calls[0].mood_id, "light");
  assert.equal(context.slateCache.get("for_you:1"), cached);
  for (const lane of ["best_bets", "revisit", "stretch", "blind_spots", "dormant"]) {
    await context.loadSlate(lane, 1, true);
    assert.equal(calls.at(-1).together_mode, true);
  }
  context.writeMoodID("");
  assert.equal(context.readTogetherMode(), false);
  assert.match(writtenCookie, /^curator_mood=;/);
  cookie += "; curator_together=1";
  assert.equal(context.readMoodID(), ""); // Explicit Off overrides the legacy On cookie.
})().catch((error) => { console.error(error); process.exitCode = 1; });
