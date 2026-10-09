const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const storage = new Map();
let state;
const context = {
  window: { localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) } },
  React: {
    useState: initial => [state = typeof initial === "function" ? initial() : initial, value => { state = value; }],
    createElement: (type, props, ...children) => ({ type, props, children }),
  },
  Button: "button", ButtonGroup: "group",
};
vm.runInNewContext(source.slice(source.indexOf("  const FIND_VIEW_KEY"), source.indexOf("  function readRecommendationView")), context);
assert.equal(context.useFindView()[0], "cards");
context.useFindView()[1]("thumbnails");
assert.equal(state, "thumbnails");
assert.equal(context.useFindView()[0], "thumbnails");
assert.equal(storage.get("stash-curator:recommendation-view:v1"), undefined);
context.window.localStorage = { getItem: () => { throw Error("blocked"); }, setItem: () => { throw Error("blocked"); } };
assert.equal(context.useFindView()[0], "cards");
context.useFindView()[1]("thumbnails");
assert.equal(state, "thumbnails");

vm.runInNewContext(source.slice(source.indexOf("  function FindThumbnail("), source.indexOf("  const ExternalCard")), context);
for (const kind of ["scene", "performer"]) {
  const tile = context.FindThumbnail({ kind, image: "fixture.jpg", title: "Fixture", href: "/fixture" });
  assert.ok(tile.props.className.includes(`${kind}-card`));
  const link = tile.children[0].children[0];
  assert.equal(link.props["aria-label"], "Fixture");
  assert.equal(link.props.rel, "noreferrer");
  assert.equal(link.children[0].props.loading, "lazy");
  assert.equal(link.children[0].props.className, `${kind}-card-image`);
  assert.equal(tile.children[1].props.hidden, true);
  assert.equal(tile.children[1].children[0].props.className, "card-section-title");
}
const local = context.FindThumbnail({ kind: "performer", title: "Missing image", href: "/performers/fixture", external: false });
assert.equal(local.children[0].children[0].props.target, undefined);
assert.equal(local.children[0].children[0].children[0].children[0], "Missing image");

vm.runInNewContext(source.slice(source.indexOf("  function RecommendationViewSelector("), source.indexOf("  function virtualWallRange(")), context);
let selected;
const selector = context.RecommendationViewSelector({ view: "thumbnails", views: ["cards", "thumbnails"], label: "Find view", onChange: value => { selected = value; } });
assert.equal(selector.props["aria-label"], "Find view");
assert.equal(selector.children[0].length, 2);
assert.equal(selector.children[0][1].props["aria-pressed"], true);
selector.children[0][0].props.onClick();
assert.equal(selected, "cards");
assert.equal(context.RecommendationViewSelector({ view: "cards" }).children[0].length, 3);

Object.assign(context, { Api: { components: {}, register: { component: (_, component) => component } }, transformComponentProps: (_, props) => props, useCuratorActivity: () => {} });
vm.runInNewContext(source.slice(source.indexOf("  const ExternalCard"), source.indexOf("  function Feedback(")) + "\nglobalThis.testExternalCard = ExternalCard;", context);
const external = context.testExternalCard({ item: { id: "fixture", payload: { title: "Fixture", images: [{ url: "fixture.jpg" }] } }, kind: "scene", thumbnails: true });
assert.equal(external.type, context.FindThumbnail);
assert.equal(external.props.image, "fixture.jpg");
assert.equal(external.props.href, "https://stashdb.org/scenes/fixture");
assert.equal(context.testExternalCard({ item: { id: "fixture" }, kind: "scene", thumbnails: true }), null);
console.log("Find view checks passed");
