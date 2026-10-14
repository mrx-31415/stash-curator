const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
let states, effects, request, updates;
const container = { remove: () => { container.removed = true; } };
let inserted, position;
const context = {
  React: {
    Fragment: "fragment",
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState: () => { const index = updates.length; updates.push(undefined); return [states.shift(), (value) => { updates[index] = value; }]; },
    useEffect: (effect) => effects.push(effect),
  },
  ReactDOM: { createPortal: (element, host) => ({ element, host }) },
  document: { querySelector: (selector) => selector.includes(".scene-toolbar") || selector.includes(".quality-group") ? { after: (node) => { inserted = node; position = "after-ratings"; } } : null, createElement: () => container },
  operation: (args) => { request = args; return context.pending; },
  CuratorContextControls() {}, CuratorAffinityGauge() {}, ExplanationView() {}, FontAwesomeIcon: "icon", faCompass: "compass", NavLink: "link",
  clamp01: (value) => Math.max(0, Math.min(1, value)),
  formatAppealValue: (value) => `${value > 0 ? "+" : ""}${value.toFixed(2)}`,
  formatSigned: (value) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}`,
  FEEDBACK_LABELS: { thumb_up: "Thumbs Up", thumb_down: "Thumbs Down" },
  GQL: { useFindScenesQuery: () => ({ data: { findScenes: { scenes: [{ id: "12", title: "Evidence scene" }] } } }), useFindPerformersQuery: () => ({ data: { findPerformers: { performers: [{ id: "4", name: "Source performer" }] } } }) },
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function CuratorContextLink("), source.indexOf("  let performerAffinitiesPending")), context);
const text = (node) => node == null || node === false ? "" : typeof node === "object" ? (Array.isArray(node) ? node : node.props?.children || []).map(text).join(" ") : String(node);
const nodes = (node) => node && typeof node === "object" ? [node, ...(Array.isArray(node) ? node : node.props?.children || []).flatMap(nodes)] : [];
const panel = (type, details, error = false) => context.CuratorEntityPanelContent({ type, id: "12", label: "Example", details, error });
assert.match(text(panel("performer", null)), /Loading Curator details/);
assert.match(text(panel("scene", null, true)), /could not be loaded/);
assert.doesNotMatch(text(panel("scene", null, true)), /Loading/);
assert.match(text(panel("performer", { affinity: null, confidence: null })), /No preference evidence yet/);
const neutral = text(panel("performer", { affinity: 0, confidence: 0 }));
assert.match(neutral, /0.00/); assert.match(neutral, /0%/); assert.doesNotMatch(neutral, /No preference evidence/);
const performer = panel("performer", { affinity: 0.8, confidence: 0.9, affinity_details: { learned: 0.5, prior: 0.4, similarity: -0.1 } });
assert.equal(performer.type, "details");
assert.equal(performer.props.open, undefined, "panel must start collapsed");
assert.equal(performer.props.children[0].type, "summary");
const summaryControls = nodes(performer.props.children[0]).find((node) => node.type === context.CuratorContextControls);
assert.equal(summaryControls.props.details.affinity, 0.8);
assert.equal(summaryControls.props.details.confidence, 0.9);
assert.equal(summaryControls.props.id, "12");
assert.equal(summaryControls.props.className, "curator-entity-actions");
assert.match(text(performer), /\+0.80/); assert.match(text(performer), /90%/);
assert.match(text(performer), /-0.10/);
assert.ok(nodes(performer).some((node) => node.props?.className === "curator-entity-negative"));
const explanation = { summary: "Supported by viewing evidence" };
const neighbors = [{ scene_id: "12", similarity: 0.8, outcome: -0.5 }];
const scene = panel("scene", { score: { appeal: 0.6, current_fit: 0.2, direct_appeal: 0, confidence: 0.7, neighbors }, explanation });
assert.match(text(scene), /Current Fit/); assert.match(text(scene), /\+0.60/); assert.match(text(scene), /\+0.20/);
assert.match(text(scene), /No direct history evidence yet/);
assert.doesNotMatch(text(panel("scene", { score: { appeal: 0, direct_appeal: 0, direct_confidence: 0.7 } })), /No direct history evidence yet/);
assert.equal(nodes(scene).find((node) => node.type === context.ExplanationView).props.explanation, explanation);
const evidence = context.CuratorSceneEvidence({ neighbors });
assert.equal(nodes(evidence).find((node) => node.type === "link").props.to, "/scenes/12");
assert.match(text(evidence), /Evidence scene/); assert.match(text(evidence), /history signal -0.50/);
context.GQL.useFindScenesQuery = () => ({ error: true });
assert.match(text(context.CuratorSceneEvidence({ neighbors })), /Scene 12/);
const specificPerformer = context.CuratorPerformerSpecifics({ details: { profile: { favorite: 1, rating100: 90 }, evidence: { performers: [{ performer_id: "4", name: "Source performer", similarity: 0.8, affinity: -0.5, confidence: 0.7 }], scenes: [{ scene_id: "12", title: "Training scene", direct: { signals: ["thumb_down"], learning_outcome: -0.4, learning_evidence: 1.5 } }] } } });
assert.match(text(specificPerformer), /Favorite: yes.*90\/100/);
assert.match(text(specificPerformer), /Source performer.*preference signal -0.50/);
assert.match(text(specificPerformer), /Training scene.*Thumbs Down.*learning signal -0.40/);
const specificScene = context.CuratorSceneSpecifics({ scene: { performers: [{ id: "3", name: "Cast member" }] }, details: { score: { components: {
  content: { top: [{ name: "tag:example", metadata: { tag_name: "Example tag" }, value: -0.2 }] },
  performer_identity: { performers: [{ performer_id: "3", value: 0.4, learned: 0.3, prior: 0.1 }] },
  performer_similarity: { performers: [{ performer_id: "3", value: 0.2, matches: [{ performer_id: "4", similarity: 0.8, affinity: 0.3 }] }] },
  fit: { cooldown: 0.2, satiation: 0 },
} } } });
assert.match(text(specificScene), /Example tag: content signal -0.20/);
assert.match(text(specificScene), /Cast member.*scene evidence \+0.30/);
assert.match(text(specificScene), /Source performer.*similarity 0.80/);
assert.match(text(specificScene), /cooldown: reduces Current Fit by \+0.20/);
assert.doesNotMatch(text(specificScene), /Recent repetition/);

(async () => {
  for (const type of ["scene", "performer"]) {
    states = [null]; updates = []; effects = [];
    context.CuratorEntityPanel({ type, id: "12" });
    const cleanup = effects[0]();
    assert.equal(inserted, container);
    assert.equal(position, "after-ratings");
    cleanup(); assert.equal(container.removed, true);
  }
  let resolve;
  context.pending = new Promise((done) => { resolve = done; });
  states = [null, false]; updates = []; effects = [];
  const page = context.CuratorContextLink({ type: "scene", id: "12", target: "toolbar" });
  assert.equal(page.type, context.CuratorEntityPanel, "detail pages must only render one consolidated panel");
  const cleanup = effects[0]();
  assert.equal(request.include_similar, false); assert.equal(request.entity_id, "12");
  cleanup(); resolve({ score: { appeal: 1 } }); await context.pending; await Promise.resolve();
  assert.equal(updates[0], null, "ignore stale responses after navigation");
  context.pending = Promise.reject(new Error("Unavailable"));
  states = [null, false]; updates = []; effects = [];
  context.CuratorContextLink({ type: "performer", id: "12", target: "toolbar" });
  effects[0](); await context.pending.catch(() => {}); await Promise.resolve();
  assert.equal(updates[1], true, "request errors must differ from missing evidence");
  console.log("PASS: entity panels show truthful scores, evidence links, loading/errors, and ignore stale responses");
})().catch((error) => { console.error(error); process.exitCode = 1; });
