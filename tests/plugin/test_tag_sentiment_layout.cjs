const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const context = {
  React: { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }) },
  Button: "button",
  libraries: { Bootstrap: { Overlay: "overlay", Popover: "popover" } },
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  const SENTIMENTS ="),
  source.indexOf("  function readTagPreferenceQueue(")), context);
const changes = [];
const render = (props = {}) => context.TagSentimentControl({
  tag: { name: "Example tag" }, value: null, blocked: false, compact: true,
  onChange: (answer) => changes.push(JSON.parse(JSON.stringify(answer))), ...props,
});
function nodes(root) {
  return root && typeof root === "object"
    ? [root, ...(root.props?.children || []).flat(Infinity).flatMap(nodes)] : [];
}
const find = (root, type) => nodes(root).find((node) => node.type === type);
const unrated = render();
const input = find(unrated, "input");
assert.equal(input.props["aria-valuetext"], "Not rated", "unrated must not appear neutral");
assert.equal(input.props["aria-label"], "Sentiment for Example tag");
assert.equal(find(unrated, "select"), undefined, "keep one slider format everywhere");
const scale = context.SentimentScale();
assert.deepEqual(nodes(scale).filter(node => node.type === "span").map(node => node.props.children[0]), [
  "Never (block)", "Strong dislike", "Slight dislike", "Neutral",
  "Slight like", "Strong like",
]);
for (let index = 0; index <= 5; index++) {
  input.props.onChange({ target: { value: String(index) } });
  const answer = index === 0 ? { value: null, blocked: true }
    : { value: [-1, -0.5, 0, 0.5, 1][index - 1], blocked: false };
  assert.deepEqual(changes.at(-1), answer);
  const rated = render(answer);
  assert.equal(find(rated, "input").props.value, index);
  find(rated, "button").props.onClick();
  assert.deepEqual(changes.at(-1), { value: null, blocked: false });
}
const full = render({ compact: false, value: -0.5, inferredValue: 0.6 });
assert.equal(find(full, "select"), undefined, "keep the model-comparison slider on the full page");
assert.equal(find(full, "input").props.type, "range");
assert.equal(find(full, "input").props["aria-valuetext"], "Slight dislike");
assert.ok(nodes(full).some((node) => node.props?.className === "curator-sentiment-model-dot"));
const followUp = source.slice(source.indexOf("  function TagSentimentFollowUp("),
  source.indexOf("  function ExternalActions("));
assert.match(followUp, /TagSentimentControl, \{[^}]*compact: true/);
vm.runInContext(source.slice(source.indexOf("  function RatingRows("),
  source.indexOf("  // LocalRatingPanel is")), context);
const rows = [{ key: "a", name: "Example tag" }, { key: "b", name: "Second tag" }];
const renderedRows = context.RatingRows({ rows, onAnswer() {} });
for (const row of renderedRows) {
  const control = nodes(row).find(node => node.type === context.TagSentimentControl);
  assert.equal(control.props.showScale, false, "do not repeat the label header on every row");
}
const section = context.RatingSection({ title: "Tags", rows, onAnswer() {} });
assert.equal(nodes(section).filter(node => node.type === context.SentimentScale).length, 1);
const close = () => {};
const anchor = {};
const popover = context.RatingPopover({ anchor, onClose: close, children: section });
assert.equal(popover.type, "overlay");
assert.equal(popover.props.target, anchor);
assert.equal(popover.props.placement, "bottom");
assert.equal(popover.props.flip, false, "scrolling must not flip the panel above its trigger");
assert.deepEqual(JSON.parse(JSON.stringify(popover.props.popperConfig.modifiers)), [
  { name: "preventOverflow", options: { padding: 8, altAxis: false } },
]);
assert.equal(popover.props.rootClose, true);
assert.equal(popover.props.onHide, close);
const panel = popover.props.children[0];
assert.equal(panel.props.children[0], section);
const footer = panel.props.children.at(-1);
assert.equal(footer.props.className, "curator-rating-footer");
assert.equal(find(footer, "button").props.onClick, close);
assert.doesNotMatch(source, /curator-external-tag-rating-close/);
console.log("PASS: shared slider semantics, one label header per section, and anchored dismissible panel");

// Every slider snaps a tap or drag anywhere on the track to the nearest
// drawn stop, including the end stops, and ignores moves without a press.
for (const props of [{}, { large: true, compact: false, showScale: true }]) {
  const track = nodes(render(props)).find((node) => node.props?.className === "curator-sentiment-track");
  let captured = false;
  const at = (x) => ({
    clientX: x, pointerId: 1,
    currentTarget: {
      getBoundingClientRect: () => ({ left: 100, width: 300 }),
      setPointerCapture: () => { captured = true; },
      hasPointerCapture: () => captured,
    },
  });
  changes.length = 0;
  track.props.onPointerMove(at(400));
  assert.equal(changes.length, 0, "a hover is not an answer");
  track.props.onPointerDown(at(95));
  track.props.onPointerMove(at(160));
  track.props.onPointerMove(at(405));
  assert.deepEqual(changes, [
    { value: null, blocked: true }, { value: -1, blocked: false }, { value: 1, blocked: false },
  ]);
  // A tap on the stop an unrated item rests on still answers.
  changes.length = 0;
  captured = false;
  track.props.onPointerDown(at(280));
  assert.deepEqual(changes, [{ value: 0, blocked: false }]);
}
