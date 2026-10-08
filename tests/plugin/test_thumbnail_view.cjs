const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const storage = new Map();
let hovered = false;
let canHover = true;
const context = {
  window: {
    localStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    matchMedia: () => ({ matches: canHover }),
  },
  React: {
    createElement: (type, props, ...children) => ({ type, props, children }),
    useState: () => [hovered, (value) => { hovered = value; }],
  },
  ButtonGroup: "group", Button: "button",
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  const WALL_STORAGE_KEY"), source.indexOf("  const CARD_SIZE_MIN")), context);
vm.runInContext(source.slice(source.indexOf("  function RecommendationViewSelector"), source.indexOf("  function PreviewTile")), context);
assert.equal(context.readRecommendationView(), "cards");
storage.set("stash-curator:preview-wall:v1", "1");
assert.equal(context.readRecommendationView(), "wall");
context.writeRecommendationView("thumbnails");
assert.equal(context.readRecommendationView(), "thumbnails");
storage.set("stash-curator:recommendation-view:v1", "invalid");
assert.equal(context.readRecommendationView(), "wall");
const entry = { scene_id: "42", scene: { title: "Scene title" } };
const render = () => context.ThumbnailTile({ entry });
const media = (tile) => tile.children[0].children[0].children[0];
let tile = render();
assert.equal(media(tile).type, "img");
assert.equal(tile.children[0].props["aria-label"], "Scene title");
assert.equal(tile.children[0].props.href, "/scenes/42");
assert.equal(tile.children.length, 1); // No title, score, or lane overlays.
tile.props.onMouseEnter();
tile = render();
assert.equal(media(tile).type, "video");
assert.equal(media(tile).props.autoPlay, true);
assert.equal(media(tile).props.muted, true);
const node = {};
media(tile).props.ref(node);
assert.equal(node.muted, true);
assert.equal(node.defaultMuted, true);
tile.props.onMouseLeave();
assert.equal(media(render()).type, "img");
canHover = false;
render().props.onMouseEnter();
assert.equal(media(render()).type, "img");
let selected;
const selector = context.RecommendationViewSelector({ view: "thumbnails", onChange: (value) => { selected = value; } });
const buttons = selector.children[0];
assert.equal(buttons.length, 3);
assert.equal(buttons[1].props["aria-pressed"], true);
buttons[2].props.onClick();
assert.equal(selected, "wall");
context.window.localStorage.getItem = () => { throw new Error("Unavailable"); };
context.window.localStorage.setItem = () => { throw new Error("Unavailable"); };
assert.equal(context.readRecommendationView(), "cards");
context.writeRecommendationView("thumbnails");
