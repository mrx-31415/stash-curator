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

function harness({ result, failure, storage, built = true, media = { description: "", markers: [] } }) {
  const runtime = createRuntime();
  const calls = { operations: [], preferences: [], applied: 0 };
  const store = storage || new Map();
  const context = {
    React: runtime.React,
    Button: "button",
    TagSentimentControl: "sentiment-control",
    Date,
    JSON,
    Set,
    Error,
    fetch: async (_url, init) => {
      calls.media = [...(calls.media || []), JSON.parse(init.body).variables.id];
      if (media === "fail") throw new Error("offline");
      return { ok: true, json: async () => ({ data: { findTag: { description: media.description }, findSceneMarkers: { scene_markers: media.markers } } }) };
    },
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
    applyFeedbackAndAwaitBuild: async () => { calls.applied += 1; return built; },
    useCuratorActivity: () => {},
  };
  vm.createContext(context);
  vm.runInContext(
    source.slice(source.indexOf("  // Tag questions: unanswered tags"), source.indexOf("  function CurateProgress(")),
    context
  );
  return { context, calls, store, render: () => runtime.render(() => context.TagQuestions({ onShowAllTags: () => { calls.showAll = (calls.showAll || 0) + 1; } })) };
}

const item = (tagId, name, extra = {}) => ({
  tag_id: tagId, name, reach: 0.42, confidence: 0.1, inferred_value: 0.2,
  examples: ["s1", "s2"], ...extra,
});

// Render TagQuestionMedia on its own runtime and return the settled tree.
async function renderMedia(media, item) {
  const app = harness({ result: { items: [] }, media });
  const runtime = createRuntimeFor(app);
  runtime.render(() => app.context.TagQuestionMedia({ item }));
  await settle();
  return { tree: runtime.render(() => app.context.TagQuestionMedia({ item })), calls: app.calls };
}
const runtimes = new WeakMap();
function createRuntimeFor(app) {
  // TagQuestionMedia reads React from the harness context, so swap in a
  // dedicated hook runtime for it.
  if (!runtimes.has(app)) {
    const runtime = createRuntime();
    app.context.React = { ...runtime.React, Fragment: "fragment" };
    runtimes.set(app, runtime);
  }
  return runtimes.get(app);
}

(async () => {
  // Tiles: marker moments first, one per scene, example scenes' markers
  // before others; example scene previews fill the rest; six at most.
  {
    const app = harness({ result: { items: [] } });
    const marker = (id, scene, seconds = 12.7) => ({ id, seconds, stream: `/m/${id}.mp4`, screenshot: `/m/${id}.jpg`, scene: { id: scene } });
    const tiles = app.context.tagQuestionTiles(
      ["s1", "s2", "s3", "s4", "s5", "s6"],
      [marker("m1", "other"), marker("m2", "s2"), marker("m3", "s2"), marker("m4", "other2")]
    );
    assert.equal(JSON.stringify(tiles.map((tile) => tile.key)),
      JSON.stringify(["marker-m2", "marker-m1", "marker-m4", "scene-s1", "scene-s3", "scene-s4"]));
    assert.equal(tiles[0].href, "/scenes/s2?t=12");
    assert.equal(tiles[0].video, "/m/m2.mp4");
    assert.equal(tiles[3].video, "/scene/s1/preview");
  }

  // The description and clips come from Stash; clips keep the SFW Switch
  // contract (scene-card > card-section media), with the Marker label
  // outside card-section.
  {
    const item = { tag_id: "t1", examples: ["s1", "s2"] };
    const { tree, calls } = await renderMedia({
      description: "  What the tag means.  ",
      markers: [{ id: "m1", seconds: 3, stream: "/m1.mp4", screenshot: "/m1.jpg", scene: { id: "s9" } }],
    }, item);
    assert.equal(JSON.stringify(calls.media), JSON.stringify(["t1"]));
    assert.match(text(tree), /What the tag means\./);
    const examples = nodes(tree).filter((node) => String(node.props?.className || "").split(" ").includes("curator-tag-question-example"));
    assert.equal(examples.length, 3);
    for (const example of examples) {
      assert.match(example.props.className, /\bscene-card\b/);
      const clip = example.props.children[0];
      assert.equal(clip.type, "video");
      assert.equal(clip.props.className, "scene-card-image card-section");
      assert.equal(clip.props.muted, true);
      assert.equal(clip.props.playsInline, true);
    }
    assert.equal(examples[0].props.children[1].props.className, "curator-tag-question-marker");
    assert.equal(examples[1].props.children[0].props.src, "/scene/s1/preview");
  }

  // If Stash can't answer, the example scenes still play.
  {
    const { tree } = await renderMedia("fail", { tag_id: "t2", examples: ["s1"] });
    const examples = nodes(tree).filter((node) => String(node.props?.className || "").split(" ").includes("curator-tag-question-example"));
    assert.equal(examples.length, 1);
    assert.equal(examples[0].props.children[0].props.src, "/scene/s1/preview");
  }

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
  // Without a confident guess there is no Yes shortcut.
  assert.equal(nodes(tree).some((node) => node.type === "button" && text(node) === "Yes"), false);
  // The cards use the large slider.
  assert.equal(nodes(tree).find((node) => node.type === "sentiment-control").props.large, true);
  assert.doesNotMatch(text(tree), /Skipped/);

  // The examples render through TagQuestionMedia, beside (not around) the
  // answer control.
  const mediaNode = nodes(tree).find((node) => node.type === app.context.TagQuestionMedia);
  assert.equal(mediaNode.props.item.tag_id, "wide");
  const control = nodes(tree).find((node) => node.type === "sentiment-control");
  assert.equal(control.props.tag.tag_id, "wide");
  assert.ok(!nodes(mediaNode).includes(control));

  // Picking an answer shows it but sends nothing until Next; Next is
  // disabled until something is picked, and a re-pick replaces the choice.
  const button = (tree, label) => nodes(tree).find((node) => node.type === "button" && text(node) === label);
  assert.equal(button(tree, "Next").props.disabled, true);
  control.props.onChange({ value: 0.5, blocked: false });
  tree = app.render();
  assert.match(text(tree), /Question 1 of 5/);
  assert.equal(app.calls.preferences.length, 0);
  nodes(tree).find((node) => node.type === "sentiment-control").props.onChange({ value: 1, blocked: false });
  tree = app.render();
  assert.equal(nodes(tree).find((node) => node.type === "sentiment-control").props.value, 1);
  // Clear returns to no answer.
  nodes(tree).find((node) => node.type === "sentiment-control").props.onChange({ value: null, blocked: false });
  tree = app.render();
  assert.equal(button(tree, "Next").props.disabled, true);
  nodes(tree).find((node) => node.type === "sentiment-control").props.onChange({ value: 1, blocked: false });
  tree = app.render();
  button(tree, "Next").props.onClick();
  tree = app.render();
  assert.equal(JSON.stringify(app.calls.preferences), JSON.stringify([["wide", { value: 1, blocked: false }]]));
  assert.match(text(tree), /Question 2 of 5/);
  assert.equal(nodes(tree).find((node) => node.type === "sentiment-control").props.value, null);
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
  const applied = apply.props.onClick();
  assert.match(text(app.render()), /Rebuilding recommendations with your answers/);
  await applied;
  await settle();
  assert.equal(app.calls.applied, 1);
  assert.equal(app.calls.operations.length, 2);
  tree = app.render();
  assert.match(text(tree), /Recommendations updated with your answers/);
  assert.doesNotMatch(text(tree), /Apply my answers now/);

  // The full list is one tap away.
  button(tree, "See all tags").props.onClick();
  assert.equal(app.calls.showAll, 1);

  // A confident guess is asked as a check; Yes selects the matching slight
  // step without sending it, and Next sends it.
  {
    const guessed = harness({ result: { items: [item("g", "Guessed", { guess: "dislike", inferred_value: -0.3, confidence: 0.8 })] } });
    guessed.render();
    await settle();
    let view = guessed.render();
    assert.match(text(view), /Curator thinks you dislike “Guessed”\. Right\?/);
    assert.match(text(view), /If not, pick where you stand on the scale\./);
    button(view, "Yes").props.onClick();
    view = guessed.render();
    assert.equal(button(view, "Yes").props["aria-pressed"], true);
    assert.equal(nodes(view).find((node) => node.type === "sentiment-control").props.value, -0.5);
    assert.equal(guessed.calls.preferences.length, 0);
    button(view, "Next").props.onClick();
    assert.equal(JSON.stringify(guessed.calls.preferences), JSON.stringify([["g", { value: -0.5, blocked: false }]]));
  }

  // When no build runs, the answers are reported as saved instead.
  const unbuilt = harness({ result: { items: [item("u", "U")] }, built: false });
  unbuilt.render();
  await settle();
  tree = unbuilt.render();
  nodes(tree).find((node) => node.type === "sentiment-control").props.onChange({ value: -1, blocked: false });
  button(unbuilt.render(), "Next").props.onClick();
  await button(unbuilt.render(), "Apply my answers now").props.onClick();
  await settle();
  assert.match(text(unbuilt.render()), /Your answers are saved/);

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
