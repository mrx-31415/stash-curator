const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");

// A minimal hook runtime: state persists by call order across renders, and
// effects run after each render when their dependencies change.
function createRuntime() {
  let hooks = [], cursor = 0, pendingEffects = [];
  const React = {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat() } }),
    useState(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = typeof initial === "function" ? initial() : initial;
      return [hooks[index], (value) => { hooks[index] = typeof value === "function" ? value(hooks[index]) : value; }];
    },
    useCallback(callback, deps) {
      const index = cursor++;
      const previous = hooks[index];
      if (!previous || deps.some((dep, i) => dep !== previous.deps[i])) hooks[index] = { callback, deps };
      return hooks[index].callback;
    },
    useEffect(effect, deps) {
      const index = cursor++;
      const previous = hooks[index];
      if (!previous || deps.some((dep, i) => dep !== previous.deps[i])) {
        hooks[index] = { deps };
        pendingEffects.push(effect);
      }
    },
  };
  return {
    React,
    render(component) {
      cursor = 0;
      const tree = component();
      const effects = pendingEffects;
      pendingEffects = [];
      effects.forEach((effect) => effect());
      return tree;
    },
  };
}

const children = (node) => (node && typeof node === "object" ? node.props?.children || [] : []);
const nodes = (node) => (node && typeof node === "object" ? [node, ...children(node).flatMap(nodes)] : []);
const text = (node) => (node == null || node === false ? "" : typeof node === "object" ? children(node).map(text).join(" ") : String(node));
const settle = () => new Promise((resolve) => setImmediate(resolve));

function harness({ result, storage, built = true }) {
  const runtime = createRuntime();
  const calls = { operations: [], preferences: [], applied: 0 };
  const store = storage || new Map();
  const context = {
    React: runtime.React,
    Button: "button",
    TagSentimentControl: "sentiment-control",
    Date, JSON, Object, Math, Number, Set, Error,
    fetch: async () => ({ ok: true, json: async () => ({ data: {} }) }),
    localStorage: {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, value) => store.set(key, value),
    },
    operation: async (args) => { calls.operations.push(args); return result; },
    submitTagPreference: (tagId, choice) => calls.preferences.push([tagId, choice]),
    applyFeedbackAndAwaitBuild: async () => { calls.applied += 1; return built; },
    useCuratorActivity: () => {},
    nearestSentimentLabel: (value) => ({ "-1": "Strong dislike", "-0.5": "Slight dislike", "0": "Neutral", "0.5": "Slight like", "1": "Strong like" })[String(Math.round(value * 2) / 2)],
    formatTimeAgo: () => "3d ago",
  };
  vm.createContext(context);
  vm.runInContext(
    source.slice(source.indexOf("  // Tag questions: unanswered tags"), source.indexOf("  function CurateProgress(")),
    context
  );
  return { context, calls, store, render: () => runtime.render(() => context.AnswerReview({ onShowAllTags: () => {} })) };
}

const review = (tagId, name, answer, extra = {}) => ({
  tag_id: tagId, name, answer, answered_at_ms: 1000, learned_value: 0.4, learned_confidence: 0.9,
  scene_count: 40, disagreement: 1.0, examples: ["s1"], ...extra,
});
const button = (tree, label) => nodes(tree).find((node) => node.type === "button" && text(node) === label);
const control = (tree) => nodes(tree).find((node) => node.type === "sentiment-control");

(async () => {
  // A kept answer stays hidden until it changes; the slider starts on the
  // current answer, and Keep is the only action until something changes.
  const storage = new Map([["stash-curator:answer-review-kept:v1", JSON.stringify({ kept: Date.now(), changed: 500 })]]);
  const app = harness({
    result: { candidate_count: 12, items: [review("kept", "Kept", 0.5), review("a", "Alpha", -0.5), review("changed", "Changed", 0), review("b", "Beta", 1)] },
    storage,
  });
  app.render();
  await settle();
  let tree = app.render();
  assert.equal(JSON.stringify(app.calls.operations), JSON.stringify([{ operation: "get_answer_review", limit: 10 }]));
  assert.match(text(tree), /Answer 1 of 3 · 12 answers can be compared with your viewing/);
  assert.match(text(tree), /You said “Slight dislike” for “Alpha”\. Still right\?/);
  assert.match(text(tree), /Your viewing on its own points to Slight like \(fairly sure\)\. You answered 3d ago\./);
  assert.equal(control(tree).props.value, -0.5);
  assert.equal(button(tree, "Save change").props.disabled, true);
  assert.equal(button(tree, "Keep").props.disabled, false);

  // Keep writes nothing, remembers the tag, and moves on to the next answer.
  button(tree, "Keep").props.onClick();
  tree = app.render();
  assert.equal(app.calls.preferences.length, 0);
  assert.ok(JSON.parse(app.store.get("stash-curator:answer-review-kept:v1")).a > 0);
  assert.match(text(tree), /for “Changed”/);
  assert.equal(control(tree).props.value, 0);

  // Changing the answer enables Save, which sends an ordinary answer.
  control(tree).props.onChange({ value: 1, blocked: false });
  tree = app.render();
  assert.equal(button(tree, "Keep").props.disabled, true);
  button(tree, "Save change").props.onClick();
  tree = app.render();
  assert.equal(JSON.stringify(app.calls.preferences), JSON.stringify([["changed", { value: 1, blocked: false }]]));

  // Clear means "let viewing decide": Save sends a clear.
  assert.match(text(tree), /for “Beta”/);
  control(tree).props.onChange({ value: null, blocked: false });
  tree = app.render();
  assert.match(text(tree), /Saving clears your answer, so viewing decides this tag again\./);
  button(tree, "Save change").props.onClick();
  tree = app.render();
  assert.equal(JSON.stringify(app.calls.preferences[1]), JSON.stringify(["b", { value: null, blocked: false }]));
  assert.match(text(tree), /2 changes queued/);

  // Apply runs the shared path and reports the outcome.
  await button(tree, "Apply my changes now").props.onClick();
  await settle();
  assert.equal(app.calls.applied, 1);
  assert.match(text(app.render()), /Recommendations updated with your changes/);

  // Nothing to review explains itself.
  const empty = harness({ result: { candidate_count: 0, items: [] } });
  empty.render();
  await settle();
  assert.match(text(empty.render()), /Nothing to review right now/);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
