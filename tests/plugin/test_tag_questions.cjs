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

function harness({ result, failure, storage }) {
  const runtime = createRuntime();
  const calls = { operations: [], preferences: [], applied: 0 };
  const store = storage || new Map();
  const context = {
    React: runtime.React,
    Button: "button",
    TagSentimentControl: "sentiment-control",
    Date,
    JSON,
    Object,
    Math,
    Number,
    localStorage: {
      getItem: (key) => (store.throws ? (() => { throw new Error("blocked"); })() : store.get(key) ?? null),
      setItem: (key, value) => { if (store.throws) throw new Error("blocked"); store.set(key, value); },
    },
    operation: async (args) => {
      calls.operations.push(args);
      if (failure) throw new Error(failure);
      return result;
    },
    submitTagPreference: (tagId, choice) => calls.preferences.push([tagId, choice]),
    applyFeedbackAndAwaitBuild: async () => { calls.applied += 1; },
    useCuratorActivity: () => {},
  };
  vm.createContext(context);
  vm.runInContext(
    source.slice(source.indexOf("  // Tag questions: unanswered tags"), source.indexOf("  function CurateProgress(")),
    context
  );
  return { context, calls, store, render: () => runtime.render(context.TagQuestions) };
}

const item = (tagId, name, extra = {}) => ({
  tag_id: tagId, name, reach: 0.42, confidence: 0.1, inferred_value: 0.2,
  examples: ["s1", "s2"], ...extra,
});

(async () => {
  // Loading asks for ten, drops tags skipped in the last 30 days (not older
  // skips), and caps the batch at five.
  const now = Date.now();
  const storage = new Map([[
    "stash-curator:tag-question-skips:v1",
    JSON.stringify({ skipped: now - 1000, expired: now - 31 * 86_400_000 }),
  ]]);
  const items = [item("skipped", "Skipped"), item("wide", "Wide"), item("expired", "Expired"),
    ...["a", "b", "c", "d", "e"].map((id) => item(id, id.toUpperCase()))];
  const app = harness({ result: { items }, storage });
  assert.equal(app.render(), null, "renders nothing until the first fetch resolves");
  await settle();
  let tree = app.render();
  assert.equal(JSON.stringify(app.calls.operations), JSON.stringify([{ operation: "get_tag_questions", limit: 10 }]));
  assert.match(text(tree), /Question 1 of 5/);
  assert.match(text(tree), /More or less of “Wide”\?/);
  assert.match(text(tree), /On about 42% of what For You would show you\. Curator has little evidence about it yet\./);
  assert.doesNotMatch(text(tree), /Skipped/);

  // Example thumbnails keep Stash's SFW Switch contract; the answer control
  // stays outside card-section.
  const examples = nodes(tree).filter((node) => String(node.props?.className || "").split(" ").includes("curator-tag-question-example"));
  assert.equal(examples.length, 2);
  for (const example of examples) {
    assert.match(example.props.className, /\bscene-card\b/);
    assert.equal(example.props.children[0].props.className, "scene-card-image card-section");
  }
  const control = nodes(tree).find((node) => node.type === "sentiment-control");
  assert.equal(control.props.tag.tag_id, "wide");
  assert.ok(!examples.some((example) => nodes(example).includes(control)));

  // Answering submits through the Tag sentiment path and advances.
  control.props.onChange({ value: 1, blocked: false });
  tree = app.render();
  assert.equal(JSON.stringify(app.calls.preferences), JSON.stringify([["wide", { value: 1, blocked: false }]]));
  assert.match(text(tree), /Question 2 of 5/);
  // A skip older than 30 days no longer hides its tag.
  assert.match(text(tree), /More or less of “Expired”\?/);
  assert.match(text(tree), /Apply my answers now/);

  // Skipping remembers the tag and advances without writing an answer.
  const skip = nodes(tree).find((node) => node.type === "button" && text(node) === "Skip");
  skip.props.onClick();
  tree = app.render();
  assert.match(text(tree), /Question 3 of 5/);
  assert.equal(app.calls.preferences.length, 1);
  // The new skip is stored with a fresh timestamp next to the live one.
  const stored = JSON.parse(app.store.get("stash-curator:tag-question-skips:v1"));
  assert.equal(Object.keys(stored).sort().join(","), "expired,skipped");
  assert.ok(stored.expired > now - 31 * 86_400_000 + 86_400_000);

  // Apply now runs the shared apply path and refetches.
  const apply = nodes(tree).find((node) => node.type === "button" && text(node) === "Apply my answers now");
  await apply.props.onClick();
  await settle();
  assert.equal(app.calls.applied, 1);
  assert.equal(app.calls.operations.length, 2);

  // Without storage, questions still load and skipping still advances.
  const blocked = harness({ result: { items: [item("x", "X"), item("y", "Y")] }, storage: Object.assign(new Map(), { throws: true }) });
  blocked.render();
  await settle();
  tree = blocked.render();
  nodes(tree).find((node) => node.type === "button" && text(node) === "Skip").props.onClick();
  tree = blocked.render();
  assert.match(text(tree), /Question 2 of 2/);

  // Finishing a batch without answers says so.
  nodes(tree).find((node) => node.type === "button" && text(node) === "Skip").props.onClick();
  assert.match(text(blocked.render()), /You skipped this batch/);

  // Empty and failed fetches explain themselves.
  const empty = harness({ result: { items: [] } });
  empty.render();
  await settle();
  assert.match(text(empty.render()), /No questions right now/);
  const failed = harness({ failure: "no published model" });
  failed.render();
  await settle();
  assert.match(text(failed.render()), /no published model/);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
