const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const context = {
  React: { createElement: (type, props, ...children) => ({ type, props, children }) },
  EvidenceFingerprint() {}, ScoreBreakdown() {},
};
vm.runInNewContext(source.slice(source.indexOf("  function negativeNeighbors("), source.indexOf("  function reasonLabel(")), context);
const { cardReason, ExplanationView } = context;
const { FindSceneReason } = context;
assert.equal(FindSceneReason({ item: { payload: { why: ["Tag A", "Tag B"] } } }).children[0], "Matches your learned preferences for “Tag A” and “Tag B”.");
assert.match(FindSceneReason({ item: { payload: { why: ["a performer you already enjoy"] } } }).children[0], /^Includes a performer with positive preference evidence/);
assert.match(FindSceneReason({ item: { payload: { why: ["performer evidence reduced for the large compilation cast"] } } }).children[0], /^The large cast makes performer evidence less influential/);
assert.equal(FindSceneReason({ item: { similarity: 0.8, payload: { why: ["Shares Tag A", "Same performer"] } } }).children[0], "Related to the source scene: Shares Tag A; Same performer.");
assert.equal(FindSceneReason({ item: { explanation: { summary: "Same performer and shared content." } } }).children[0], "Same performer and shared content.");
assert.equal(FindSceneReason({ item: { payload: { explanation: { summary: "Named shared tags." }, why: ["Fallback"] } } }).children[0], "Named shared tags.");
assert.match(FindSceneReason({ item: { sources: ["wildcard"] } }).children[0], /Popularity wildcard/);
assert.match(FindSceneReason({ item: {} }).children[0], /unavailable/);
assert.match(FindSceneReason({ item: {} }).props.className, /card-section/);

const expandSource = source.slice(source.indexOf("  function ExpandPanel("), source.indexOf("  function BackupPanel("));
assert.equal(expandSource.match(/^      pager,?$/gm).length, 2);
const pagerDefinition = expandSource.match(/^    const pager = (.*);$/m)[1];
let nextState;
Object.assign(context, { Pager() {}, page: 2, entityType: "scene", data: { ready: true, total: 60, page_size: 20, has_more: true }, loading: false, updateUrl: (change) => { nextState = change({ page: 2, sort: "newest" }); } });
const pager = vm.runInNewContext(pagerDefinition, context);
assert.equal(pager.props.page, 2);
assert.equal(pager.props.total, 60);
assert.equal(pager.props.label, "Expand pages");
pager.props.onPage(3);
assert.equal(nextState.page, 3);
assert.equal(nextState.sort, "newest");
context.Button = "button";
vm.runInNewContext(source.slice(source.indexOf("  function pagerPages("), source.indexOf("  function readFilterPresets(")), context);
for (const page of [1, 4, 10]) {
  for (const loading of [false, true]) {
    let destination;
    const rendered = context.Pager({ page, total: 200, pageSize: 20, loading, onPage: (value) => { destination = value; } });
    for (const [label, target, disabled] of [["First page", 1, page === 1], ["Last page", 10, page === 10]]) {
      const button = rendered.children.find((child) => child?.props?.["aria-label"] === label);
      assert.equal(button.props.disabled, loading || disabled);
      button.props.onClick();
      assert.equal(destination, target);
    }
  }
}
assert.equal(context.Pager({ page: 1, total: 0, pageSize: 20 }), null);
assert.ok(!context.Pager({ page: 2, hasMore: true }).children.some((child) => child?.props?.["aria-label"] === "Last page"));
const stretch = {
  lane: "for_you", source_lane: "stretch", subtype: "untested",
  qualification: {
    anchor_features: [{ name: "Weak anchor", value: 0.1 }, { name: "Anchor", value: 0.3 }],
    challenged_feature: { name: "Challenge" }, challenge_kind: "untested",
  },
};
assert.match(cardReason(stretch).summary, /Stretch because “Anchor”.*too little evidence.*“Challenge”/);
assert.equal(cardReason(stretch).teaser, "Familiar “Anchor”, with less-tested “Challenge”.");
stretch.qualification.challenge_kind = "tested_negative";
assert.match(cardReason(stretch).summary, /estimates a negative preference/);
assert.match(cardReason(stretch).teaser, /lower estimated preference/);
assert.match(cardReason({ source_lane: "stretch" }).summary, /unavailable/);

const blind = { source_lane: "blind_spots", qualification: { dark_facets: [
  { facet_type: "tag", name: "Tag", darkness: 0.8, played_count: 0, library_count: 28 },
  { facet_type: "tag", name: "Other tag", darkness: 0.7, played_count: 1, library_count: 35 },
  { facet_type: "studio", name: "Studio", darkness: 0.6, played_count: 2, library_count: 40 },
] } };
assert.match(cardReason(blind).summary, /studio “Studio” and tag “Tag”.*relative to/);
assert.match(cardReason(blind).teaser, /^Underexplored studio “Studio” and tag “Tag”/);
assert.match(cardReason(blind).details.join(" "), /2 of 40 scenes played.*0 of 28 scenes played/);
assert.match(cardReason({ source_lane: "blind_spots", qualification: { dark_facets: [blind.qualification.dark_facets[0]] } }).summary, /unavailable/);

const review = { source_lane: "score_review", appeal: -0.4, components: {
  direct: { value: -0.8, confidence: 0.5 },
  content: { value: -0.2, top: [{ name: "Named tag", value: -0.1 }, { name: "Positive", value: 0.1 }] },
  studio: { value: 0.1 }, baseline: { value: -0.1 },
  fit: { cooldown: -1, not_now: -1 },
} };
assert.match(cardReason(review).summary, /recorded ratings.*“Named tag”/);
assert.match(cardReason(review).details.join(" "), /negative starting estimate/);
assert.doesNotMatch(cardReason(review).summary, /studio|cooldown|Not now/);
assert.doesNotMatch(cardReason(review).summary, /“Positive”/);
review.components.direct.confidence = 0;
assert.doesNotMatch(cardReason(review).summary, /recorded ratings/);
review.components.direct.confidence = 1;
assert.doesNotMatch(cardReason(review).summary, /Named tag|starting estimate/);
assert.equal(cardReason({ ...review, appeal: 0 }), null);
assert.equal(cardReason({ ...review, appeal: 0.3 }), null);
assert.match(cardReason({ source_lane: "score_review", appeal: -0.1 }).summary, /unavailable/);
assert.match(cardReason({ source_lane: "best_bets" }).summary, /unavailable/);

const scene = { performers: [{ id: "p1", name: "Alex" }, { id: "p2", name: "Positive performer" }], studio: { id: "s1", name: "Example studio" } };
const specific = { source_lane: "score_review", appeal: -0.3, components: {
  performer_identity: { value: -0.1, performers: [{ performer_id: "p1", value: -0.3 }, { performer_id: "p2", value: 0.2 }] },
  studio: { value: -0.1, studios: [{ studio_id: "s1", value: -0.2 }] },
  content_neighbor: { value: -0.1, training_outcome_mean: 0.6 },
}, neighbors: [
  { scene_id: "n1", outcome: 0.2, weight: 0.8 },
  { scene_id: "n2", outcome: 0.9, weight: 1 },
  { scene_id: "n3", outcome: -1, weight: 0 },
] };
const evidenceScenes = new Map([["n1", { title: "Earlier scene" }], ["n2", { title: "Above average" }], ["n3", { title: "Zero weight" }]]);
const named = cardReason(specific, scene, evidenceScenes);
assert.equal(named.teaser, "Lower estimated appeal from performer “Alex” and studio “Example studio”.");
assert.match(named.summary, /performer “Alex”.*studio “Example studio”.*Why this/);
assert.match(named.details.join(" "), /“Earlier scene”.*below your library average/);
assert.doesNotMatch(named.summary, /Positive performer|Above average|Zero weight|negative outcomes/);
assert.match(named.details.join(" "), /0.20.*0.60/);
assert.match(cardReason(specific).summary, /names are unavailable.*studio name is unavailable/);
assert.match(cardReason(specific).details.join(" "), /titles unavailable/);
specific.components.performer_similarity = specific.components.performer_identity;
assert.match(cardReason(specific, scene).summary, /profiles similar to performer “Alex”/);
const expanded = JSON.stringify(ExplanationView({ explanation: {}, item: specific, scene, evidenceScenes }));
assert.match(expanded, /Earlier scene/);
const reviewPanel = source.slice(source.indexOf("  function ScoreReviewPanel("), source.indexOf("  function ScoreReviewPanel(") + 8500);
assert.match(reviewPanel, /negativeNeighbors\(item\)/);
assert.match(reviewPanel, /evidenceScenes: scenes/);
assert.match(reviewPanel, /scene_ids: ids.map\(Number\)/);
assert.doesNotMatch(source, /idFilter\(/);

const best = { source_lane: "best_bets", lane: "for_you", qualification: { unseen: true, corroborated: true }, components: {
  content: { value: 0.2, top: [{ name: "Liked tag", value: 0.3 }, { name: "Disliked tag", value: -0.1 }] },
  performer_identity: { value: 0.1, performers: [{ performer_id: "p1", value: 0.1 }] },
} };
assert.match(cardReason(best, scene).summary, /Best bet.*“Liked tag”.*“Alex”/);
assert.equal(cardReason(best, scene).teaser, "Matches your preference for “Liked tag” and “Alex”.");
assert.doesNotMatch(cardReason(best, scene).summary, /Disliked tag/);
assert.match(cardReason({ source_lane: "revisit", qualification: { direct_appeal: 0.5, recovery: 0.2 } }).summary, /played this scene before.*cooldown has eased/);
assert.match(cardReason({ source_lane: "revisit", qualification: {} }).summary, /unavailable/);
assert.match(cardReason({ source_lane: "dormant", qualification: { dormant_entity: { type: "studio", name: "Old favorite" }, days_since_played: 180 } }).summary, /studio “Old favorite”.*180 days/);
assert.match(cardReason({ source_lane: "dormant" }).summary, /unavailable/);

// A generic explanation without lane context must preserve the card's own facts.
const rendered = JSON.stringify(ExplanationView({ explanation: { summary: "General evidence", lane_context: { available: false } }, item: stretch }));
assert.match(rendered, /Stretch because/);
assert.match(rendered, /Selected challenge/);
assert.match(rendered, /card-section/);
assert.match(rendered, /General evidence/);
assert.match(source, /className: "curator-selection-reason card-section"/);
assert.match(source, /selection.teaser \|\| selection.summary/);
// The expanded explanation keeps the full summary, not the clamped teaser.
assert.match(rendered, /Stretch because/);
assert.doesNotMatch(rendered, /Familiar “Anchor”, with/);
