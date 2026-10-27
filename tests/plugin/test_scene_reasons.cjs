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
    { id: "utility", name: "[Utility]" }, { id: "answered", name: "Answered" }],
  ...extra,
});

const IMPACT = {
  available: true,
  tags: { promoted: [{ id: "t1", name: "Lace", delta: 0.05 }], demoted: [{ id: "t2", name: "Gaping", delta: -0.12 }] },
  performers: { promoted: [{ performer_id: "p1", name: "Performer One", delta: 0.09 }], demoted: [] },
  scenes: { promoted: [{ scene_id: "s1", title: "Up", delta: 0.2 }], demoted: [{ scene_id: "s2", title: "Down", delta: -0.3 }] },
};

function harness({ candidates, storage, impact = IMPACT }) {
  const runtime = createRuntime();
  const calls = { operations: [], answers: [], graphql: [] };
  const store = storage || new Map();
  const context = {
    React: runtime.React,
    Button: "button",
    Date, JSON, Set, Map, Error, Object, Math, Number, String, Promise, setTimeout, clearTimeout,
    keepPreviewMuted: () => {},
    loadPerformerAffinities: async () => ({ affinities: {
      p4: { affinity: 0.1, confidence: 0.5, affinity_details: { learned: 0.05, learned_confidence: 0.5 } },
    } }),
    uuid: () => "uuid-1",
    scheduleModelUpdate: () => { calls.scheduled = (calls.scheduled || 0) + 1; },
    useCuratorActivity: () => {},
    submitSceneReason: (entry) => calls.answers.push(entry),
    applyFeedbackAndAwaitBuild: async () => { calls.applied = (calls.applied || 0) + 1; return true; },
    formatSigned: (value) => `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}`,
    localStorage: {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, value) => store.set(key, value),
    },
    // Like the backend: excluded scenes never come back.
    operation: async (args) => {
      calls.operations.push(args);
      if (args.operation === "get_curation_impact") return impact;
      if (args.operation === "get_studio_affinities") {
        return { affinities: { st4: { affinity: -0.2, confidence: 0.4, affinity_details: { learned: -0.2, prior: 0, learned_confidence: 0.4 } } } };
      }
      if (args.operation === "get_taste_profile") {
        // "answered" has a Tag sentiment answer, so it is never a chip.
        return { items: [
          { tag_id: "liked", inferred_value: 0.6, scene_count: 50, direct_value: null },
          { tag_id: "disliked", inferred_value: -0.7, scene_count: 10, direct_value: null },
          { tag_id: "plain", inferred_value: 0, scene_count: 5, direct_value: null },
          { tag_id: "answered", inferred_value: 0.9, scene_count: 2, direct_value: 1 },
          // A workflow tag (a bracketed sync marker, say) is in the profile but never a chip.
          { tag_id: "utility", inferred_value: 0, scene_count: 1, direct_value: null, role: "workflow_administrative" },
        ].map((item) => ({ role: "content", ...item })) };
      }
      const excluded = new Set(args.exclude_scene_ids);
      return { items: (candidates[args.mode] || []).filter((id) => !excluded.has(id)).map((id) => ({ scene_id: id })) };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      if (body.query.includes("CuratorSceneCount")) {
        return { ok: true, json: async () => ({ data: { findScenes: { count: 100 } } }) };
      }
      calls.graphql.push(body.variables);
      return { ok: true, json: async () => ({ data: { findScenes: { scenes: body.variables.ids.map((id) => scene(String(id))) } } }) };
    },
  };
  vm.createContext(context);
  // The shared sentiment words (nearestSentimentLabel) the estimates use.
  vm.runInContext(source.slice(source.indexOf("  const SENTIMENTS ="), source.indexOf("  const BELIEF_PHRASES")), context);
  vm.runInContext(source.slice(source.indexOf("  // Instant estimates of what an answer does"), source.indexOf("  function CurateProgress(")), context);
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
    ["Performer 1", "Liked", "Plain", "Disliked", "Answered", "Studio 1", "Just this scene"]);
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
  // A flip offers two strengths, mild preselected; the choice is sent.
  assert.equal(button(tree, "Not that good").props["aria-pressed"], true);
  assert.equal(button(tree, "Not for me").props["aria-pressed"], false);
  button(tree, "Not for me").props.onClick();
  tree = app.render();
  assert.equal(button(tree, "Not for me").props["aria-pressed"], true);
  button(tree, "Next").props.onClick();
  assert.equal(JSON.stringify(app.calls.answers[1]),
    JSON.stringify({ scene_id: "2", polarity: -1, flipped: true, reasons: [], flip_strength: "strong" }));
  // The next card starts unflipped and mild again; no strength is sent without a flip.
  tree = app.render();
  assert.equal(button(tree, "Not for me"), undefined);

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
    assert.deepEqual(labels, ["Performer 8", "Disliked", "Plain", "Liked", "Answered", "Studio 8", "Just this scene"]);
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
  // Ranking: a rare liked tag beats a common one with stronger taste; then the
  // rarest unanswered tags; answered tags last; non-content tags never.
  {
    const app = harness({ candidates: {} });
    const info = (value, scenes, answered = false) => ({ value, scenes, answered });
    const taste = {
      total: 1000,
      tags: new Map([
        ["common-like", info(0.8, 400)], ["rare-like", info(0.4, 5)], ["answered", info(0.9, 3, true)],
        ["rare-plain", info(0, 2)], ["mid-plain", info(0, 50)], ["common-plain", info(0, 600)],
      ]),
    };
    const tags = ["common-like", "rare-like", "answered", "rare-plain", "mid-plain", "common-plain", "utility"]
      .map((id) => ({ id, name: id }));
    const picked = app.context.sceneReasonTags({ tags }, taste, "hits").map((tag) => tag.id);
    assert.equal(JSON.stringify(picked),
      JSON.stringify(["rare-like", "common-like", "rare-plain", "mid-plain", "common-plain", "answered"]));
    // When unanswered tags run out, answered ones fill the rest, rarest first.
    const few = ["rare-like", "answered", "common-answered", "utility"].map((id) => ({ id, name: id }));
    taste.tags.set("common-answered", info(0.9, 500, true));
    assert.equal(JSON.stringify(app.context.sceneReasonTags({ tags: few }, taste, "hits").map((tag) => tag.id)),
      JSON.stringify(["rare-like", "answered", "common-answered"]));
    // Without a profile, every tag is offered alphabetically.
    assert.equal(app.context.sceneReasonTags({ tags }, null, "hits").length, tags.length);
    // Cards show six, then "+ N more" until expanded.
    const ranked = Array.from({ length: 9 }, (_, i) => ({ id: `t${i}`, name: `T${i}` }));
    assert.equal(app.context.shownReasonTags(ranked, false).length, 6);
    assert.equal(text(app.context.moreReasonTagsChip(ranked, false, () => {})).trim(), "+ 3 more");
    assert.equal(app.context.shownReasonTags(ranked, true).length, 9);
    assert.equal(app.context.moreReasonTagsChip(ranked, true, () => {}), false);
  }
  // The missing-tag search offers only content tags when a profile is loaded.
  {
    const runtime = createRuntime();
    const app = harness({ candidates: {} });
    app.context.React = { ...runtime.React, Fragment: "fragment" };
    app.context.fetch = async () => ({ ok: true, json: async () => ({ data: { findTags: { tags: [
      { id: "content-tag", name: "Content tag" }, { id: "attribute-tag", name: "Attribute tag" },
    ] } } }) });
    const taste = { total: 10, tags: new Map([["content-tag", { value: 0, scenes: 1, answered: false }]]) };
    const render = () => runtime.render(() => app.context.MissingTagPicker({ picked: [], taste, onPick: () => {} }));
    let view = render();
    nodes(view).find((node) => node.type === "input").props.onChange({ target: { value: "tag" } });
    render();
    await new Promise((resolve) => setTimeout(resolve, 260));
    view = render();
    const options = nodes(view).filter((node) => node.props?.role === "option").map((node) => text(node).trim());
    assert.equal(JSON.stringify(options), JSON.stringify(["Content tag"]));
  }
  // Every fifth answer updates the model in the background; a published build
  // shows "What your answers moved" above the card.
  {
    const app = harness({ candidates: { hits: ["1", "2", "3", "4", "5", "6", "7", "8"] } });
    app.render();
    await settle();
    await settle();
    let view = app.render();
    assert.ok(!nodes(view).some((node) => node.type === app.context.WhatMoved));
    for (let answer = 0; answer < 5; answer++) {
      nodes(app.render()).find((node) => node.type === app.context.ReasonChip).props.onClick();
      button(app.render(), "Next").props.onClick();
      if (answer === 0) assert.ok(button(app.render(), "Apply my answers now"));
    }
    await settle();
    view = app.render();
    assert.equal(app.calls.applied, 1);
    const card = nodes(view).find((node) => node.type === app.context.WhatMoved);
    assert.equal(card.props.refreshKey, 1);
    assert.equal(button(view, "Apply my answers now"), undefined);
  }

  // The card lists the biggest tag, performer, and scene moves, links the full
  // report, and stays quiet without a comparison.
  {
    const renderCard = async (impact) => {
      const runtime = createRuntime();
      const app = harness({ candidates: {}, impact });
      app.context.React = runtime.React;
      runtime.render(() => app.context.WhatMoved({ refreshKey: 1, onDismiss: () => {} }));
      await settle();
      return runtime.render(() => app.context.WhatMoved({ refreshKey: 1, onDismiss: () => {} }));
    };
    const card = await renderCard(IMPACT);
    assert.match(text(card), /What your answers moved/);
    assert.match(text(card), /Lace \+0\.05/);
    assert.match(text(card), /Gaping −0\.12/);
    assert.match(text(card), /Performer One \+0\.09/);
    const scenes = nodes(card).filter((node) => node.type === "a" && String(node.props.className).includes("curator-moved-scene"));
    assert.equal(JSON.stringify(scenes.map((node) => node.props.href)), JSON.stringify(["/scenes/s1", "/scenes/s2"]));
    assert.ok(nodes(card).some((node) => node.props?.href === "/plugins/stash-curator?view=curate&section=progress"));
    assert.equal(await renderCard({ available: false }), null);
    const quiet = await renderCard({ available: true, tags: { promoted: [], demoted: [] }, performers: {}, scenes: {} });
    assert.match(text(quiet), /Nothing moved noticeably/);
  }
  // Instant estimates mirror the model's blends (checked against real
  // rebuilds): an answer replaces inherited evidence; a reason keeps it.
  {
    const app = harness({ candidates: {} });
    const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} vs ${expected}`);
    // Own evidence only: (0.2 * 2 + 1 * 8) / 10.
    near(app.context.estimateTagAnswer({ value: 0.2, support: 2, direct: null, inherited: null }, 1).after, 0.84);
    // Inherited 0.5 at 4 on own 0.0 at 4 (value 0.25, support 8): the answer drops it: (0 + -0.5 * 8) / 12.
    near(app.context.estimateTagAnswer({ value: 0.25, support: 8, direct: null, inherited: 0.5 }, -0.5).after, -1 / 3);
    // A reason keeps it: own (0 + 2) / (6 + 1), then blended with 0.5 at 4.
    near(app.context.estimateTagReason({ value: 0.25, support: 8, direct: null, inherited: 0.5 }, 1).after,
      ((2 / 7) * 6 + 0.5 * 4) / 10);
    // An answered tag: learned part (0.6 * 10 - 1 * 8) / 2 = -1, plus a reason, then the answer again.
    near(app.context.estimateTagReason({ value: 0.6, support: 10, direct: 1, inherited: null }, 1).after,
      (((-1 * 2 + 2) / 5) * 4 + 8) / 12);
  }

  // Picking tag chips shows their estimated effect under the card.
  {
    const app = harness({ candidates: { misses: ["4"] } });
    nodes(app.render()).length;
    await settle();
    await settle();
    button(app.render(), "Misses").props.onClick();
    app.render();
    await settle();
    await settle();
    nodes(app.render()).find((node) => node.type === app.context.ReasonChip && text(node).trim() === "Disliked").props.onClick();
    const view = app.render();
    assert.match(text(view), /Disliked: (stays Dislike|Dislike → Strong dislike)/);
  }
  // Performers and studios get the same estimate (checked against real
  // rebuilds). Picked chips show an arrow; the line under the card says it in
  // the Tag sentiment scale's words.
  {
    const app = harness({ candidates: { misses: ["4"] } });
    app.render();
    await settle();
    await settle();
    button(app.render(), "Misses").props.onClick();
    app.render();
    await settle();
    await settle();
    let view = app.render();
    const chipNamed = (tree, label) => nodes(tree).find((node) => node.type === app.context.ReasonChip && text(node).trim().startsWith(label));
    assert.equal(chipNamed(view, "Performer 4").props.trend, null, "no arrow before a chip is picked");
    chipNamed(view, "Performer 4").props.onClick();
    view = app.render();
    assert.equal(chipNamed(view, "Performer 4").props.trend, "down", "a miss lowers Curator's view");
    // +0.10 → about −0.20: still Neutral in words, but clearly lower.
    assert.match(text(view), /Performer 4: Neutral, a bit lower/);
    chipNamed(view, "Studio 4").props.onClick();
    view = app.render();
    assert.equal(chipNamed(view, "Studio 4").props.trend, "down");
    assert.match(text(view), /Studio 4: (Neutral|Slight dislike) → (Slight dislike|Dislike)/);
    // The arrow renders inside the chip with a readable label.
    const chip = app.context.ReasonChip({ pressed: true, onClick: () => {}, tone: "miss", trend: "down", children: "X" });
    const arrow = nodes(chip).find((node) => String(node.props?.className).includes("curator-reason-trend-down"));
    assert.equal(text(arrow).trim(), "↓");
    assert.equal(arrow.props["aria-label"], "Curator will like it less");
    // The estimate itself: learned 0.05 at confidence 0.5 (support 3 ln 2).
    const support = 3 * Math.log(2);
    const affinity = (0.1 * (1 + support) - 2) / (3 + support);
    const expected = 0.1 - 0.05 + affinity * (1 - Math.exp(-(support + 2) / 3));
    const estimate = app.context.estimateLearnedReason({ value: 0.1, learned: 0.05, learnedConfidence: 0.5 }, -1);
    assert.ok(Math.abs(estimate.after - expected) < 1e-9);
    // Words: same word means "stays".
    assert.equal(app.context.estimateText("Lace", { before: 0.5, after: 0.53 }), "Lace: stays Slight like");
    assert.equal(app.context.estimateText("Lace", { before: 0.5, after: 0.8 }), "Lace: Slight like → Like");
    assert.equal(app.context.estimateText("Lace", { before: 0.1, after: 0.2 }), "Lace: Neutral, a bit higher");
  }
  console.log("PASS: why-these queue, reasons, flip, skips, modes, the thumb follow-up, tag ranking, the tag search, what moved, estimates, and chip bars");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
