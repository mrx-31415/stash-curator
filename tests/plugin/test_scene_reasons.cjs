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
    useRef(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = { current: initial };
      return hooks[index];
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

const scene = (id, extra = {}) => ({
  id, title: `Scene ${id}`, play_count: 2, paths: { preview: `/p/${id}`, screenshot: `/s/${id}` },
  studio: { id: `st${id}`, name: `Studio ${id}` },
  performers: [{ id: `p${id}`, name: `Performer ${id}`, image_path: `/i/${id}` }],
  // "utility" is not a content tag (absent from the taste profile).
  tags: [{ id: "liked", name: "Liked" }, { id: "disliked", name: "Disliked" }, { id: "plain", name: "Plain" },
    { id: "utility", name: "[Utility]" }],
  ...extra,
});

function harness({ candidates, storage }) {
  const runtime = createRuntime();
  const calls = { operations: [], answers: [], graphql: [] };
  const store = storage || new Map();
  const context = {
    React: runtime.React,
    Button: "button",
    Date, JSON, Set, Map, Error, Object, Math, Number, String, Promise, setTimeout, clearTimeout,
    keepPreviewMuted: () => {},
    uuid: () => "uuid-1",
    scheduleModelUpdate: () => { calls.scheduled = (calls.scheduled || 0) + 1; },
    useCuratorActivity: () => {},
    submitSceneReason: (entry) => calls.answers.push(entry),
    localStorage: {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, value) => store.set(key, value),
    },
    // Like the backend: excluded scenes never come back.
    operation: async (args) => {
      calls.operations.push(args);
      if (args.operation === "get_taste_profile") {
        return { items: [{ tag_id: "liked", inferred_value: 0.6 }, { tag_id: "disliked", inferred_value: -0.7, direct_value: null },
          { tag_id: "plain", inferred_value: 0 }] };
      }
      const excluded = new Set(args.exclude_scene_ids);
      return { items: (candidates[args.mode] || []).filter((id) => !excluded.has(id)).map((id) => ({ scene_id: id })) };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      calls.graphql.push(body.variables);
      return { ok: true, json: async () => ({ data: { findScenes: { scenes: body.variables.ids.map((id) => scene(String(id))) } } }) };
    },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("  // Why these?: scenes Curator rates"), source.indexOf("  function CurateProgress(")), context);
  return {
    context, calls, store,
    render: () => runtime.render(() => context.SceneReasons()),
    renderFollowUp: (followUp) => runtime.render(() => context.SceneReasonFollowUp({ followUp, onDismiss: () => { calls.dismissed = (calls.dismissed || 0) + 1; } })),
  };
}

const button = (tree, label) => nodes(tree).find((node) => node.type === "button" && text(node).trim() === label);

(async () => {
  const app = harness({ candidates: { hits: ["1", "2", "3", "4"], misses: ["9"] } });
  app.render();
  await settle();
  await settle();
  let tree = app.render();
  const fetches = app.calls.operations.filter((call) => call.operation === "get_scene_reason_candidates");
  assert.equal(JSON.stringify(fetches[0]), JSON.stringify({ operation: "get_scene_reason_candidates", mode: "hits", limit: 20, exclude_scene_ids: [] }));
  assert.match(text(tree), /Curator rates this highly\. What makes it work for you\?/);
  assert.match(text(tree), /Scene 1/);

  // Hits rank the scene's liked tags first; Next stays off until something is picked.
  const chips = nodes(tree).filter((node) => node.type === app.context.ReasonChip);
  assert.deepEqual(chips.map((node) => text(node).trim()),
    ["Performer 1", "Liked", "Plain", "Disliked", "Studio 1", "Just this scene"]);
  assert.equal(button(tree, "Next").props.disabled, true);
  const pick = (label) => nodes(app.render()).find((node) => node.type === app.context.ReasonChip && text(node).trim() === label).props.onClick();
  pick("Performer 1");
  pick("Liked");
  pick("Studio 1");
  pick("Studio 1");
  tree = app.render();
  nodes(tree).find((node) => node.type === app.context.MissingTagPicker).props.onPick({ id: "absent", name: "Absent" });
  tree = app.render();
  assert.equal(button(tree, "Next").props.disabled, false);
  button(tree, "Next").props.onClick();
  tree = app.render();
  assert.equal(JSON.stringify(app.calls.answers[0]), JSON.stringify({
    scene_id: "1", polarity: 1, flipped: false,
    reasons: [{ subject_type: "performer", subject_id: "p1" }, { subject_type: "tag", subject_id: "liked" },
      { subject_type: "missing_tag", subject_id: "absent" }],
  }));
  assert.match(text(tree), /Scene 2 · 1 answered/);

  // The flip turns a hit into a miss: the question, the tag order, and the polarity follow.
  button(tree, "I don't actually like it").props.onClick();
  tree = app.render();
  assert.match(text(tree), /What puts you off\?/);
  assert.deepEqual(nodes(tree).filter((node) => node.type === app.context.ReasonChip).map((node) => text(node).trim()).slice(1, 4),
    ["Disliked", "Plain", "Liked"]);
  button(tree, "Next").props.onClick();
  assert.equal(JSON.stringify(app.calls.answers[1]), JSON.stringify({ scene_id: "2", polarity: -1, flipped: true, reasons: [] }));

  // Skip remembers the scene in this browser; nearing the end tops up with
  // every seen scene excluded, and an empty top-up ends the queue.
  tree = app.render();
  button(tree, "Skip").props.onClick();
  app.render();
  await settle();
  await settle();
  tree = app.render();
  assert.ok(JSON.parse(app.store.get("stash-curator:scene-reason-skips:v1"))["3"]);
  const last = app.calls.operations.filter((call) => call.operation === "get_scene_reason_candidates").at(-1);
  assert.deepEqual([...last.exclude_scene_ids].sort(), ["1", "2", "3", "4"]);
  button(tree, "Skip").props.onClick();
  tree = app.render();
  assert.match(text(tree), /That's every scene to ask about for now\. Your answers are saved/);

  // Misses ask the other way round and rank disliked tags first.
  button(tree, "Misses").props.onClick();
  app.render();
  await settle();
  await settle();
  tree = app.render();
  assert.match(text(tree), /Curator expects this isn't for you\. What puts you off\?/);
  assert.deepEqual(nodes(tree).filter((node) => node.type === app.context.ReasonChip).map((node) => text(node).trim()).slice(1, 4),
    ["Disliked", "Plain", "Liked"]);
  pick("Disliked");
  button(app.render(), "Next").props.onClick();
  assert.equal(app.calls.answers.at(-1).polarity, -1);

  // A fresh browser with skips sends them as exclusions.
  const skipped = harness({
    candidates: { hits: ["5"] },
    storage: new Map([["stash-curator:scene-reason-skips:v1", JSON.stringify({ 7: Date.now() })]]),
  });
  skipped.render();
  await settle();
  await settle();
  assert.equal(JSON.stringify(skipped.calls.operations.find((call) => call.mode).exclude_scene_ids), JSON.stringify(["7"]));
  // After a thumbs down: the same chips, dislikes first; Done needs a pick,
  // saves a scene reason at the thumb's polarity, and closes the panel.
  {
    const app = harness({ candidates: {} });
    const followUp = { scene_id: "8", polarity: -1 };
    app.renderFollowUp(followUp);
    await settle();
    await settle();
    let view = app.renderFollowUp(followUp);
    assert.match(text(view), /What put you off\?/);
    assert.match(text(view), /Scene 8 · optional/);
    const labels = nodes(view).filter((node) => node.type === app.context.ReasonChip).map((node) => text(node).trim());
    assert.deepEqual(labels, ["Performer 8", "Disliked", "Plain", "Liked", "Studio 8", "Just this scene"]);
    assert.equal(button(view, "Done").props.disabled, true);
    assert.ok(button(view, "Metadata is wrong"));
    nodes(view).find((node) => node.type === app.context.ReasonChip && text(node).trim() === "Disliked").props.onClick();
    view = app.renderFollowUp(followUp);
    button(view, "Done").props.onClick();
    assert.equal(JSON.stringify(app.calls.answers.at(-1)), JSON.stringify({
      scene_id: "8", polarity: -1, flipped: false, reasons: [{ subject_type: "tag", subject_id: "disliked" }],
    }));
    assert.equal(app.calls.dismissed, 1);
    // Metadata is wrong records that feedback instead of a reason.
    await button(app.renderFollowUp(followUp), "Metadata is wrong").props.onClick();
    const metadata = app.calls.operations.find((call) => call.operation === "submit_feedback");
    assert.equal(metadata.entries[0].feedback_type, "metadata_wrong");
    assert.equal(metadata.entries[0].scene_id, "8");
    assert.equal(app.calls.dismissed, 2);
  }

  // After a thumbs up the panel asks what made it work, likes first, and has
  // no metadata action.
  {
    const app = harness({ candidates: {} });
    const followUp = { scene_id: "6", polarity: 1 };
    app.renderFollowUp(followUp);
    await settle();
    await settle();
    const view = app.renderFollowUp(followUp);
    assert.match(text(view), /What made it work\?/);
    assert.deepEqual(nodes(view).filter((node) => node.type === app.context.ReasonChip).map((node) => text(node).trim()).slice(1, 4),
      ["Liked", "Plain", "Disliked"]);
    assert.equal(button(view, "Metadata is wrong"), undefined);
  }
  console.log("PASS: why-these queue, reasons, flip, skips, modes, and the thumb follow-up");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
