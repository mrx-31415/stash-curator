const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const helpers = source.slice(source.indexOf("  let filterPresets ="), source.indexOf("  async function copyText("));

test("presets persist across private sessions and browser imports preserve server names", async () => {
  let database = {};
  let failSave = false;
  function session(legacy = null) {
    const storage = new Map(legacy ? [["presets", JSON.stringify(legacy)]] : []);
    const context = {
      FILTER_PRESETS_KEY: "presets",
      localStorage: { getItem: (key) => storage.get(key), removeItem: (key) => storage.delete(key) },
      operation: async (args) => {
        if (args.operation === "update_config") {
          if (failSave) throw new Error("Database unavailable");
          database = JSON.parse(JSON.stringify(args.values.saved_filters));
        }
        return { config: { saved_filters: JSON.parse(JSON.stringify(database)) } };
      },
    };
    vm.createContext(context);
    vm.runInContext(helpers, context);
    return { context, storage };
  }
  const first = session();
  await first.context.loadFilterPresets(database);
  await first.context.saveFilterPreset("expand", "Favorites", { favoriteOnly: true }, true);
  const privateSession = session();
  await privateSession.context.loadFilterPresets(database);
  assert.equal(privateSession.context.defaultFilters("expand").favoriteOnly, true);
  assert.equal(privateSession.storage.size, 0);

  const browser = session({ expand: { presets: { Favorites: { favoriteOnly: false }, New: { gender: "MALE" } }, default: "New" } });
  await browser.context.loadFilterPresets(database);
  assert.equal(database.expand.presets.Favorites.favoriteOnly, true);
  assert.equal(database.expand.presets.New.gender, "MALE");
  assert.equal(database.expand.default, "Favorites");
  assert.equal(browser.storage.size, 0);

  // Fetch current server state before saving, preserving another browser's filters.
  await privateSession.context.saveFilterPreset("hunt", "Tags", { includeTags: [] }, false);
  assert.equal(database.expand.presets.New.gender, "MALE");
  failSave = true;
  const failed = session({ similar: { presets: { Import: {} } } });
  await assert.rejects(failed.context.loadFilterPresets(database), /Database unavailable/);
  assert.equal(failed.storage.size, 1);
  await assert.rejects(browser.context.saveFilterPreset("expand", "Failed", {}, false), /Database unavailable/);
  assert.equal(database.expand.presets.Failed, undefined);
});

test("the selector shows the matching saved filter and marks changed settings unsaved", async () => {
  const context = {
    filterPresets: {},
    readFilterPresets: () => ({ expand: { presets: { Tags: { includeTags: [{ name: "Example", id: "1" }], favoriteOnly: true } } } }),
    uuid: () => "switch",
    Button: "button",
    React: {
      useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
      createElement: (type, props, ...children) => ({ type, props, children }),
    },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("  function SavedFilters("), source.indexOf("  // Shared filter panel")), context);
  let applied;
  const current = { favoriteOnly: true, includeTags: [{ id: "1", name: "Example" }] };
  const render = () => context.SavedFilters({ scope: "expand", current, onApply: (value) => { applied = value; } });
  assert.equal(render().children[0].props.value, "Tags");
  current.favoriteOnly = false;
  assert.equal(render().children[0].props.value, "");
  render().children[0].props.onChange({ target: { value: "Tags" } });
  assert.equal(applied.favoriteOnly, true);
  assert.equal(render().children[1].type, "details");
});
