const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.css"), "utf8");
const context = { React: { createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }) } };
vm.runInNewContext(source.slice(source.indexOf("  function TagQuestionRing("), source.indexOf("  // Answer review: your own tag answers")), context);

const segments = (node) => node.children[0].children;
const two = context.TagQuestionRing({ pending: 2, every: 5, updating: false });
assert.equal(segments(two).length, 5);
assert.equal(segments(two).filter((segment) => /is-on/.test(segment.props.className)).length, 2);
assert.equal(two.children[0].props["aria-label"], "3 more answers to the next update");
assert.equal(context.TagQuestionRing({ pending: 4, every: 5 }).children[0].props["aria-label"], "1 more answer to the next update");
const updating = context.TagQuestionRing({ pending: 0, every: 5, updating: true });
assert.match(updating.props.className, /is-updating/);
assert.equal(segments(updating).filter((segment) => /is-on/.test(segment.props.className)).length, 5);
assert.equal(updating.children[0].props["aria-label"], "Updating recommendations now");
// Each segment starts where the previous one ended, with a small gap.
assert.deepEqual(segments(two).map((segment) => segment.props.strokeDashoffset), [-0, -20, -40, -60, -80]);

// The answered card waits for its exit animation only when motion is allowed.
const questions = source.slice(source.indexOf("  function TagQuestions("), source.indexOf("  function TagQuestionRing("));
assert.match(questions, /if \(reducedMotion\(\)\) return show\(\);/);
assert.match(questions, /leaveTimer\.current = setTimeout\(show, TAG_QUESTION_LEAVE_MS\)/);
const section = css.slice(css.indexOf("Motion: tag questions and what an update moved"));
const reduced = section.slice(section.indexOf("@media (prefers-reduced-motion: reduce)"));
for (const selector of [".curator-tag-question.is-leaving", ".curator-what-moved", ".curator-moved-chip", ".curator-sweep::after"]) {
  assert.ok(reduced.includes(selector), `${selector} respects reduced motion`);
}
