const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.css"), "utf8");

// A tiny hook runtime: state survives re-renders of one component instance.
function instance(component) {
  const slots = [];
  let cursor = 0;
  const React = {
    createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }),
    useState: (initial) => {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === "function" ? initial() : initial;
      return [slots[index], (value) => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
    },
    useEffect: () => {},
    useRef: (value) => ({ current: value }),
    Fragment: "fragment",
  };
  return { React, render: (props) => { cursor = 0; return component(props); } };
}
function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (predicate(node)) return node;
  for (const child of node.children || []) {
    const hit = find(child, predicate);
    if (hit) return hit;
  }
  return null;
}

const region = source.slice(source.indexOf("  function Feedback("), source.indexOf("  const FEEDBACK_LABELS = {"));
const calls = [];
const context = {
  Button: "Button", FontAwesomeIcon: "Icon", faThumbsUp: "up", faThumbsDown: "down", faRotateLeft: "undo",
  uuid: (() => { let n = 0; return () => `id-${++n}`; })(),
  operation: async (request) => { calls.push(request); return {}; },
  scheduleModelUpdate: () => {}, announcePageChat: () => {}, setTimeout, clearTimeout,
};
const { React, render } = instance((props) => context.Feedback(props));
context.React = React;
Object.assign(context, vm.runInNewContext(`${region}
;({ FEEDBACK_UNDO_TEXT })`, context));

(async () => {
  const removed = [];
  const item = { scene_id: 7, impression_id: "imp" };
  let tree = render({ item, onRemove: (id, info) => removed.push([id, info]) });
  const useful = find(tree, (node) => node.props["aria-label"] === "Useful");
  assert.equal(useful.props["aria-pressed"], false);
  await useful.props.onClick();
  tree = render({ item, onRemove: () => {} });
  const liked = find(tree, (node) => node.props["aria-label"] === "Useful");
  assert.equal(liked.props["aria-pressed"], true);
  assert.match(liked.props.className, /is-on/);
  assert.ok(find(liked, (node) => node.type === context.FeedbackBurst), "a thumbs-up bursts");
  assert.ok(find(tree, (node) => node.props.className === "curator-feedback-float"), "the saved note floats up");
  assert.equal(removed.length, 0, "a thumbs-up keeps the card");

  const down = find(tree, (node) => node.props["aria-label"] === "Not for me");
  await down.props.onClick();
  const sent = calls.at(-1).entries[0];
  assert.equal(sent.feedback_type, "thumb_down");
  // The lane needs the saved id to undo exactly this reaction.
  assert.deepEqual(removed, []);
  const removing = [];
  const second = instance((props) => context.Feedback(props));
  context.React = second.React;
  let tree2 = second.render({ item, onRemove: (id, info) => removing.push([id, info]) });
  await find(tree2, (node) => node.props["aria-label"] === "Not for me").props.onClick();
  assert.equal(removing.length, 1);
  assert.equal(removing[0][0], 7);
  assert.equal(removing[0][1].feedbackType, "thumb_down");
  assert.equal(removing[0][1].feedbackId, calls.at(-1).entries[0].feedback_id);

  for (const type of ["thumb_down", "not_now", "never_show", "metadata_wrong", "prune"]) {
    assert.ok(context.FEEDBACK_UNDO_TEXT[type], `undo text for ${type}`);
  }

  // The toast offers Undo with the entry it was given, and no Undo after a failure.
  const toast = instance((props) => context.UndoToast(props));
  context.React = toast.React;
  const undone = [];
  const entry = { key: "k", text: "Hidden.", feedbackId: "f" };
  const shown = toast.render({ entry, onUndo: (value) => undone.push(value), onClose: () => {} });
  find(shown, (node) => node.type === "Button" && node.children.includes(" Undo")).props.onClick();
  assert.deepEqual(undone, [entry]);
  const failed = toast.render({ entry: { ...entry, failed: true }, onUndo: () => {}, onClose: () => {} });
  assert.equal(find(failed, (node) => node.type === "Button" && node.children.includes(" Undo")), null);

  // Every new animation is switched off for reduced motion.
  const motion = css.slice(css.indexOf("Motion: cards that arrive"));
  const reduced = motion.slice(motion.indexOf("@media (prefers-reduced-motion: reduce)"));
  for (const selector of [".curator-card-enter", ".curator-card.curator-card-leaving", ".curator-feedback-button.btn-link.is-on", ".curator-undo-toast", ".curator-feedback-burst"]) {
    assert.ok(reduced.includes(selector), `${selector} respects reduced motion`);
  }

  // The lane page passes each card its place so the grid arrives in a stagger.
  assert.match(source, /onReaction: showFollowUp, enterIndex: index \}/);
  assert.match(source, /enterIndex: index % \(entry\.slate\.page_size \|\| 20\)/);
})().catch((error) => { console.error(error); process.exit(1); });
