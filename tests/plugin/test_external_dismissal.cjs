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
    Fragment: "fragment",
    createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat() } }),
    useState(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = typeof initial === "function" ? initial() : initial;
      return [hooks[index], (value) => { hooks[index] = typeof value === "function" ? value(hooks[index]) : value; }];
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
const byLabel = (tree, label) => nodes(tree).find((node) => node.type === "button" && node.props["aria-label"] === label);
const byText = (tree, label) => nodes(tree).find((node) => node.type === "button" && text(node).trim() === label);

const ITEM = {
  id: "ext-1", score: 0.5, sources: ["tags"],
  payload: {
    title: "Remote scene",
    tags: [{ id: "r-rough", name: "Rough" }, { id: "r-lace", name: "Lace" }],
    // Only performers and studios linked to the library can carry a reason.
    performers: [
      { performer: { id: "ext-p1", name: "Local Performer", gender: "FEMALE", curator_local: { id: "p1" }, images: [] } },
      { performer: { id: "ext-p2", name: "Remote Only", gender: "FEMALE", images: [] } },
      // Outside the view's gender filter: never a chip.
      { performer: { id: "ext-m1", name: "Male Cast", gender: "MALE", curator_local: { id: "m1" }, images: [] } },
    ],
    studio: { id: "ext-st", name: "Local Studio", curator_local: { id: "st1" } },
  },
};

function harness() {
  const calls = { operations: [], cleared: 0, scheduled: 0 };
  const context = {
    Button: "button", ButtonGroup: "group", NavLink: "a", FontAwesomeIcon: "icon",
    faThumbsDown: "down", faClock: "clock", faList: "list", faTag: "tag", faFilm: "film", faUser: "user",
    WHISPARR_LOGO: "",
    faEyeSlash: "eye-slash",
    // Rendering helpers outside the loaded slices; createElement never calls them.
    EvidenceScore: "evidence", ExplanationView: "explanation", FindSceneReason: "reason", PerformerHuntLink: "hunt-link",
    formatSigned: String, scoreBar: () => null, utilityBar: () => null,
    libraries: { Bootstrap: { Overlay: "overlay", Popover: "popover" } },
    window: {},
    Date, JSON, Set, Map, Error, Object, Math, Number, String, Promise, URL, encodeURIComponent,
    Api: { register: { component: (_name, component) => component }, patch: { before: () => {} }, components: {} },
    transformComponentProps: (_name, props) => props,
    useCuratorActivity: () => {},
    clearEndlessCache: () => { calls.cleared += 1; },
    uuid: () => "answer-1",
    scheduleModelUpdate: () => { calls.scheduled += 1; },
    loadPerformerAffinities: async () => ({ affinities: {} }),
    stashQuery: async () => ({ findScenes: { count: 100 } }),
    operation: async (args) => {
      calls.operations.push(args);
      if (args.operation === "get_external_tag_choices") {
        return { items: [
          { tag_id: "rough", name: "Rough", direct_value: null, direct_blocked: false },
          { tag_id: "lace", name: "Lace", direct_value: null, direct_blocked: false },
        ] };
      }
      if (args.operation === "get_taste_profile") {
        return { items: ["rough", "lace"].map((tag_id) => ({ tag_id, role: "content", inferred_value: -0.2, scene_count: 5 })) };
      }
      return { affinities: {} };
    },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("  const SENTIMENTS ="), source.indexOf("  const BELIEF_PHRASES")), context);
  vm.runInContext(source.slice(source.indexOf("  // Instant estimates of what an answer does"), source.indexOf("  function CurateProgress(")), context);
  // The Find summary and its "Ranked lower" line.
  vm.runInContext(source.slice(source.indexOf("  // \"Ranked lower: you're not into"), source.indexOf("  function FindSceneReason(")), context);
  vm.runInContext(source.slice(source.indexOf("  function ExternalActions("), source.indexOf("  const SourceReference =")) + "\nglobalThis.ExternalCard = ExternalCard;", context);
  return { context, calls };
}

(async () => {
  // Scene cards offer both dismissals; performer cards and views without a
  // handler (Shortlist) offer neither.
  const app = harness();
  app.context.React = createRuntime().React;
  const actions = (props) => app.context.ExternalActions({ item: ITEM, kind: "scene", tagsAvailable: true, ...props });
  const chosen = [];
  let tree = actions({ onDismiss: (kind) => chosen.push(kind) });
  byLabel(tree, "Not interested").props.onClick();
  byLabel(tree, "Not now").props.onClick();
  assert.deepEqual(chosen, ["not_interested", "not_now"]);
  assert.equal(byLabel(actions({}), "Not interested"), undefined);
  assert.equal(byLabel(actions({ kind: "performer", onDismiss: () => {} }), "Not now"), undefined);

  // The view hook stores the dismissal, clears the endless cache, and only
  // Not interested opens the follow-up; Undo marks the scene restored, which
  // overrides a dismissed marker from the server until the next fetch.
  const runtime = createRuntime();
  app.context.React = runtime.React;
  let state = runtime.render(() => app.context.useExternalDismissals());
  await state.dismiss(ITEM, "not_now");
  state = runtime.render(() => app.context.useExternalDismissals());
  assert.equal(state.dismissals["ext-1"], "not_now");
  assert.equal(state.followUpFor("ext-1"), null);
  await state.dismiss(ITEM, "not_interested");
  state = runtime.render(() => app.context.useExternalDismissals());
  // The follow-up belongs to the dismissed card only.
  assert.equal(state.followUpFor("ext-1").type, app.context.ExternalDismissFollowUp);
  assert.equal(state.followUpFor("ext-other"), null);
  await state.dismiss(ITEM, null);
  state = runtime.render(() => app.context.useExternalDismissals());
  assert.equal(state.dismissals["ext-1"], "restored");
  assert.equal(state.followUpFor("ext-1"), null);
  assert.deepEqual(app.calls.operations.filter((call) => call.operation === "update_external_dismissal").map((call) => call.kind),
    ["not_now", "not_interested", null]);
  assert.equal(app.calls.cleared, 3);

  // A dismissed card renders as a stub whose Undo calls back with null.
  const cardRuntime = createRuntime();
  app.context.React = cardRuntime.React;
  const undone = [];
  const followUp = { type: "follow-up", props: { children: [] } };
  const renderStub = () => cardRuntime.render(() => app.context.ExternalCard({ item: ITEM, kind: "scene", dismissal: "not_interested", followUp, onDismiss: async (item, kind) => undone.push([item.id, kind]) }));
  tree = renderStub();
  // The popover waits for the stub element, then anchors under it.
  assert.equal(nodes(tree).find((node) => node.type === "overlay"), undefined);
  tree.props.ref("stub-element");
  tree = renderStub();
  const overlay = nodes(tree).find((node) => node.type === "overlay");
  assert.equal(overlay.props.target, "stub-element");
  assert.equal(overlay.props.placement, "bottom");
  assert.ok(nodes(overlay).includes(followUp));
  assert.match(text(tree), /Remote scene/);
  assert.match(text(tree), /Not interested · hidden from Find\./);
  assert.ok(tree.props.className.includes("scene-card"));
  assert.ok(!nodes(tree).find((node) => node.props?.className === "card-section").props.children.some((child) => child?.type === "button"));
  await byText(tree, "Undo").props.onClick();
  assert.deepEqual(undone, [["ext-1", null]]);

  // With Hide dismissed scenes off, an earlier dismissal comes back as a
  // full card: a Hidden badge and Show again instead of the dismiss buttons.
  const hiddenRuntime = createRuntime();
  app.context.React = hiddenRuntime.React;
  const shown = [];
  const hiddenCard = (dismissal) => hiddenRuntime.render(() => app.context.ExternalCard({ item: { ...ITEM, dismissed: "not_now" }, kind: "scene", dismissal, onDismiss: async (item, kind) => shown.push([item.id, kind]) }));
  // The card's actions sit in EvidenceScore's actionsContent prop.
  const cardActions = (card) => nodes(card).filter((node) => node.props?.actionsContent)
    .flatMap((node) => nodes(node.props.actionsContent))
    .filter((node) => node.type === app.context.ExternalActions)
    .flatMap((node) => nodes(node.type(node.props)));
  const actionButton = (card, match) => cardActions(card).find((node) => node.type === "button" && match(node));
  tree = hiddenCard(undefined);
  assert.ok(tree.props.className.includes("curator-external-hidden"));
  assert.match(text(tree), /Hidden · Not now/);
  assert.equal(actionButton(tree, (node) => node.props["aria-label"] === "Not interested"), undefined);
  await actionButton(tree, (node) => text(node).trim() === "Show again").props.onClick();
  assert.deepEqual(shown, [["ext-1", null]]);
  // Once restored in this view it is an ordinary card again.
  tree = hiddenCard("restored");
  assert.ok(!tree.props.className.includes("curator-external-hidden"));
  assert.ok(actionButton(tree, (node) => node.props["aria-label"] === "Not interested"));

  // The follow-up offers the scene's local performers, content tags, and
  // studio; Done sends them as one negative external reason answer.
  const followRuntime = createRuntime();
  app.context.React = followRuntime.React;
  let dismissed = 0;
  const follow = () => followRuntime.render(() => app.context.ExternalDismissFollowUp({ item: ITEM, gender: "FEMALE", onDismiss: () => { dismissed += 1; } }));
  follow();
  await settle();
  await settle();
  tree = follow();
  assert.match(text(tree), /What put you off\?/);
  const chips = nodes(tree).filter((node) => node.type === app.context.ReasonChip);
  // "Remote Only" is not in the library: her chip is a StashDB performer dislike.
  assert.deepEqual(chips.map((node) => text(node).trim()), ["Local Performer", "Remote Only", "Lace", "Rough", "Local Studio"]);
  assert.equal(byText(tree, "Done").props.disabled, true);
  for (const index of [0, 1, 3, 4]) chips[index].props.onClick();
  tree = follow();
  await byText(tree, "Done").props.onClick();
  const submitted = app.calls.operations.filter((call) => call.operation === "submit_external_scene_reasons");
  assert.equal(JSON.stringify(submitted), JSON.stringify([{
    operation: "submit_external_scene_reasons",
    entries: [{
      answer_id: "answer-1", external_id: "ext-1", polarity: -1,
      reasons: [{ subject_type: "performer", subject_id: "p1" }, { subject_type: "tag", subject_id: "rough" }, { subject_type: "studio", subject_id: "st1" }],
      occurred_at_ms: submitted[0].entries[0].occurred_at_ms,
    }],
  }]));
  assert.equal(app.calls.scheduled, 1);
  assert.equal(JSON.stringify(app.calls.operations.filter((call) => call.operation === "update_external_performer_dislike")),
    JSON.stringify([{ operation: "update_external_performer_dislike", performer_id: "ext-p2", name: "Remote Only", disliked: true }]));

  // Find cards say why a disliked performer's scene ranks lower.
  const disliked = { payload: { why: ["Lace"], curator_performer_dislike: { names: ["A", "B"], penalty: 0.1 } }, sources: [] };
  assert.equal(app.context.findSceneSummary(disliked), "Matches your learned preferences for “Lace”. Ranked lower: you're not into A and B.");
  assert.equal(app.context.findSceneSummary({ payload: { why: ["Lace"] }, sources: [] }), "Matches your learned preferences for “Lace”.");
  assert.equal(dismissed, 1);

  // Nothing local to offer: the follow-up closes itself.
  const emptyRuntime = createRuntime();
  app.context.React = emptyRuntime.React;
  let closed = 0;
  const empty = () => emptyRuntime.render(() => app.context.ExternalDismissFollowUp({ item: { ...ITEM, id: "ext-2", payload: { title: "No tags", tags: [] } }, onDismiss: () => { closed += 1; } }));
  const original = app.context.operation;
  app.context.operation = async (args) => (args.operation === "get_external_tag_choices" ? { items: [] } : original(args));
  empty();
  await settle();
  await settle();
  assert.equal(empty(), null);
  assert.equal(closed, 1);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
