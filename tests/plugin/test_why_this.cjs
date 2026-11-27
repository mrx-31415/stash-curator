const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const slots = [];
let cursor = 0;
const React = {
  createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }),
  useState: (initial) => {
    const index = cursor++;
    if (!(index in slots)) slots[index] = initial;
    return [slots[index], (value) => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
  },
};
const submitted = [];
const context = { React, Button: "Button", submitTagPreference: (tagId, answer) => submitted.push([tagId, answer]) };
vm.runInNewContext(source.slice(source.indexOf("  function clamp01("), source.indexOf("  function scoreBar(")), context);
vm.runInNewContext(source.slice(source.indexOf("  function evidenceStrongest("), source.indexOf("  function reasonLabel(")), context);
Object.assign(context, vm.runInNewContext(`${source.slice(source.indexOf("  function reasonLabel("), source.indexOf("  const BELIEF_PHRASES = {"))}\n;({ SENTIMENTS })`, context));

function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (predicate(node)) return node;
  for (const child of node.children || []) {
    const hit = find(child, predicate);
    if (hit) return hit;
  }
  return null;
}

// One step along the sentiment scale, clamped at both ends.
assert.equal(context.nudgedSentiment(0, 1), 0.5);
assert.equal(context.nudgedSentiment(0, -1), -0.5);
assert.equal(context.nudgedSentiment(0.5, 1), 0.75);
assert.equal(context.nudgedSentiment(1, 1), 1);
assert.equal(context.nudgedSentiment(-1, -1), -1);
assert.equal(context.nudgedSentiment(null, 1), 0.5);
assert.equal(context.nudgedSentiment(0.6, -1), 0, "an inferred value snaps to the nearest level first");

// Bars are sized against the strongest row and grow from the centre line.
const rows = [
  { code: "appeal.tag_positive", label: "Familiar content pattern", direction: "positive", magnitude: 0.6, confidence: 0.8, subject_type: "tag", subject_id: "12", detail: { name: "Outdoor" } },
  { code: "appeal.studio", label: "Studio appeal", direction: "positive", magnitude: 0.3, confidence: 0.5, subject_type: "studio", subject_id: "4", detail: { name: "Studio" } },
  { code: "appeal.tag_negative", label: "Less familiar content pattern", direction: "negative", magnitude: 0.15, confidence: 0.4, subject_type: "tag", subject_id: "9", detail: { name: "Long take", declared_preference: -0.5 } },
];
const strongest = context.evidenceStrongest(rows);
assert.equal(strongest, 0.6);
const render = (row, index) => { cursor = 0; return context.EvidenceRow({ row, index, strongest }); };
const first = render(rows[0], 0);
const fill = find(first, (node) => /curator-evidence-fill/.test(node.props.className || ""));
assert.equal(fill.props.style.width, "50%");
assert.equal(fill.props.style.left, "50%");
assert.match(find(first, (node) => node.type === "strong").children[0], /Outdoor/);
assert.equal(first.props.style["--curator-row-i"], 0);

slots.length = 0;
const studio = render(rows[1], 1);
assert.equal(find(studio, (node) => /curator-evidence-fill/.test(node.props.className || "")).props.style.width, "25%");
assert.equal(find(studio, (node) => node.props.className === "curator-evidence-teach"), null, "only tag rows can be taught here");

slots.length = 0;
const negative = render(rows[2], 2);
const negativeFill = find(negative, (node) => /curator-evidence-fill/.test(node.props.className || ""));
assert.match(negativeFill.props.className, /is-negative/);
assert.equal(negativeFill.props.style.right, "50%");
// Teaching starts from the declared answer and steps along the scale.
find(negative, (node) => node.props["aria-label"] === "More of Long take").props.onClick();
assert.equal(JSON.stringify(submitted.at(-1)), JSON.stringify(["9", { value: 0, blocked: false }]));
const taught = render(rows[2], 2);
assert.match(find(taught, (node) => node.props.role === "status").children[0], /^Neutral\. Picks update soon\./);
find(taught, (node) => node.props["aria-label"] === "Less of Long take").props.onClick();
assert.equal(JSON.stringify(submitted.at(-1)), JSON.stringify(["9", { value: -0.5, blocked: false }]));
