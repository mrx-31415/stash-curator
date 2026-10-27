const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");

// Render one Impact scene row with tag/performer contributors: every name it
// uses must be defined (a missing whyTitle once crashed the whole page).
const children = (node) => (node && typeof node === "object" ? node.props?.children || [] : []);
const nodes = (node) => (node && typeof node === "object" ? [node, ...children(node).flatMap(nodes)] : []);
const context = {
  React: {
    createElement: (type, props, ...kids) => ({ type, props: { ...props, children: kids.flat() } }),
    useState: (initial) => [initial, () => {}],
  },
  Button: "button",
  operation: async () => ({}),
  Math, Number, String,
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function fmtDelta(value) {"), source.indexOf("  function ImpactList(")), context);
const row = context.ImpactSceneCard({
  entry: {
    scene_id: "s1", title: "A scene", delta: -0.12,
    breakdown: { your_feedback: 0, tag_preference: -0.05, performer_preference: 0.01, content_similarity: -0.08 },
    contributors: [
      { kind: "tag", id: "t1", name: "Gaping", delta: -0.06, via_feedback: 0 },
      { kind: "performer", id: "p1", name: "Someone", delta: 0.01, via_feedback: 2 },
    ],
  },
});
const details = nodes(row).find((node) => node.props?.className === "curator-impact-scene-why" && node.props.title);
assert.ok(details, "the details line renders");
assert.match(details.props.title, /tags and performers/);
console.log("PASS: impact scene rows render their details");
