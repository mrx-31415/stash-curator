const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const storage = new Map();
let state;
const context = {
  window: { localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) } },
  React: {
    useState: initial => [state = typeof initial === "function" ? initial() : initial, value => { state = value; }],
    createElement: (type, props, ...children) => ({ type, props, children }),
  },
  Button: "button", ButtonGroup: "group",
};
vm.runInNewContext(source.slice(source.indexOf("  const FIND_VIEW_KEY"), source.indexOf("  function readRecommendationView")), context);
assert.equal(context.useFindView()[0], "cards");
context.useFindView()[1]("thumbnails");
assert.equal(state, "thumbnails");
assert.equal(context.useFindView()[0], "thumbnails");
assert.equal(storage.get("stash-curator:recommendation-view:v1"), undefined);
context.window.localStorage = { getItem: () => { throw Error("blocked"); }, setItem: () => { throw Error("blocked"); } };
assert.equal(context.useFindView()[0], "cards");
context.useFindView()[1]("thumbnails");
assert.equal(state, "thumbnails");

vm.runInNewContext(source.slice(source.indexOf("  function FindThumbnail("), source.indexOf("  const ExternalCard")), context);
for (const kind of ["scene", "performer"]) {
  const tile = context.FindThumbnail({ kind, image: "fixture.jpg", title: "Fixture", href: "/fixture" });
  assert.ok(tile.props.className.includes(`${kind}-card`));
  const link = tile.children[0].children[0];
  assert.equal(link.props["aria-label"], "Fixture");
  assert.equal(link.props.rel, "noreferrer");
  assert.equal(link.children[0].props.loading, "lazy");
  assert.equal(link.children[0].props.className, `${kind}-card-image`);
  assert.equal(tile.children[1].props.hidden, true);
  assert.equal(tile.children[1].children[0].props.className, "card-section-title");
}
const local = context.FindThumbnail({ kind: "performer", title: "Missing image", href: "/performers/fixture", external: false });
assert.equal(local.children[0].children[0].props.target, undefined);
assert.equal(local.children[0].children[0].children[0].children[0], "Missing image");

vm.runInNewContext(source.slice(source.indexOf("  function RecommendationViewSelector("), source.indexOf("  function virtualWallRange(")), context);
let selected;
const selector = context.RecommendationViewSelector({ view: "thumbnails", views: ["cards", "thumbnails"], label: "Find view", onChange: value => { selected = value; } });
assert.equal(selector.props["aria-label"], "Find view");
assert.equal(selector.children[0].length, 2);
assert.equal(selector.children[0][1].props["aria-pressed"], true);
selector.children[0][0].props.onClick();
assert.equal(selected, "cards");
assert.equal(context.RecommendationViewSelector({ view: "cards" }).children[0].length, 3);

Object.assign(context, { Api: { components: {}, register: { component: (_, component) => component } }, transformComponentProps: (_, props) => props, useCuratorActivity: () => {} });
vm.runInNewContext(source.slice(source.indexOf("  const ExternalCard"), source.indexOf("  function Feedback(")) + "\nglobalThis.testExternalCard = ExternalCard;", context);
const external = context.testExternalCard({ item: { id: "fixture", payload: { title: "Fixture", images: [{ url: "fixture.jpg" }] } }, kind: "scene", thumbnails: true });
assert.equal(external.type, context.FindThumbnail);
assert.equal(external.props.image, "fixture.jpg");
assert.equal(external.props.href, "https://stashdb.org/scenes/fixture");
assert.equal(context.testExternalCard({ item: { id: "fixture" }, kind: "scene", thumbnails: true }), null);
const externalSource = source.slice(source.indexOf("  const ExternalCard"), source.indexOf("  const SourceReference"));
for (const name of externalSource.match(/\bfa[A-Z]\w+/g)) context[name] = {};
Object.assign(context, {
  FontAwesomeIcon: "icon", NavLink: "link", ExternalActions: "actions",
  FindSceneReason: "reason", ExplanationView: "explanation", EvidenceScore: "score",
  findSceneSummary: () => "Match summary", formatSigned: () => "+0.8",
  formatAppealValue: () => "+0.8", scoreBar: () => null,
  utilityBar: () => context.React.createElement("div", { className: "curator-score-bar" }),
  LocalRatingPanel: "rating", Feedback: "feedback",
});
function nodes(tree) {
  return tree && typeof tree === "object" ? [tree, ...(tree.children || []).flat(Infinity).flatMap(nodes)] : [];
}
const item = { id: "fixture", score: 0.8, appeal: 0.9, sources: ["learned"], payload: {
  title: "Fixture", release_date: "2026-01-01", why: ["Tag A"], tags: [{ id: "tag", name: "Tag A" }],
  performers: [{ performer: { id: "performer", name: "Performer" } }],
} };
const card = context.testExternalCard({ item, kind: "scene" });
assert.ok(card.props.className.includes("curator-compact-card"));
assert.equal(nodes(card).filter(node => node.type === "reason").length, 0);
const score = nodes(card).find(node => node.type === "score");
assert.equal(score.props.evidenceContent.props.explanation.summary, "Match summary");
assert.equal(score.props.metadataContent.props.className, "card-popovers");
assert.ok(!nodes(nodes(card).find(node => node.props?.className === "scene-card__details")).some(node => node.props?.className === "card-popovers"));
vm.runInNewContext(source.slice(source.indexOf("  function EvidenceScore("), source.indexOf("  function ExternalActions(")), context);
const scoreTree = context.EvidenceScore(score.props);
const primaryRow = nodes(scoreTree).find(node => node.props?.className === "curator-score-appeal-row");
assert.equal(primaryRow.children[0].children[0], "2026-01-01");
assert.equal(primaryRow.children.at(-1), score.props.metadataContent);
assert.equal(nodes(scoreTree).filter(node => node.props?.className === "curator-match-row").length, 0);
const whyRow = nodes(scoreTree).find(node => node.props?.className === "curator-why-row");
assert.ok(whyRow.children.includes(score.props.actionsContent));
assert.ok(nodes(whyRow).find(node => node.type === "details").children.includes(score.props.scoreContent));
assert.ok(!nodes(scoreTree).some(node => node.props?.className === "curator-score"));
assert.ok(!source.slice(source.indexOf("  function ExternalActions("), source.indexOf("  function FindThumbnail(")).includes("Copy StashDB ID"));
assert.ok(!nodes(context.EvidenceScore({ scoreHeadline: "Match", scoreHeadlineBar: "bar", evidenceContent: null })).some(node => node.props?.className === "curator-score-headline"));
assert.ok(!nodes(context.EvidenceScore({ scoreHeadline: "Appeal", scoreHeadlineBar: "bar", evidenceContent: null })).some(node => node.props?.className === "curator-score-headline"));
assert.ok(!nodes(context.EvidenceScore({ scoreBarContent: "bar", evidenceContent: null })).some(node => node.props?.className === "card-popovers"));
context.EvidenceScore = "score";
const missing = context.testExternalCard({ item: { ...item, payload: { title: "No evidence" } }, kind: "scene" });
assert.equal(nodes(missing).find(node => node.type === "score").props.evidenceContent.type, "reason");
context.React.useEffect = () => {};
context.Api.components.SceneCard = "scene";
context.GQL = {
  useFindScenesQuery: () => ({ loading: false, data: { findScenes: { scenes: [{ id: "1" }] } } }),
  useFindPerformersQuery: () => ({}),
};
context.performerNameFilter = () => ({});
vm.runInNewContext(source.slice(source.indexOf("  function relationshipChips("), source.indexOf("  function SimilarityPanel(")), context);
const localItem = { entity_id: "1", appeal: 0.9, similarity: 0.8, relationships: [], details: { shared_tags: [] }, explanation: { summary: "Shared evidence" } };
const localCard = context.SimilarLibraryResults({ result: { page: 1, items: [localItem] }, entityType: "scene", findView: "cards" });
assert.equal(nodes(localCard).filter(node => node.type === "reason").length, 0);
assert.equal(nodes(localCard).find(node => node.type === "score").props.evidenceContent.props.explanation, localItem.explanation);
const fallback = context.SimilarLibraryResults({ result: { page: 1, items: [{ ...localItem, explanation: null }] }, entityType: "scene", findView: "cards" });
assert.equal(nodes(nodes(fallback).find(node => node.type === "score").props.evidenceContent).filter(node => node.type === "reason").length, 1);
context.React.useRef = initial => ({ current: initial });
context.laneByValue = new Map([["for_you", { label: "For You" }]]);
context.faCompass = {};
vm.runInNewContext(source.slice(source.indexOf("  function RecommendationCard("), source.indexOf("  function RecommendationHistoryRow(")), context);
const recommendationItem = { scene_id: "1", source_lane: "for_you", impression_id: "fixture", appeal: 0.8, lane_value: 0.9 };
const recommendation = context.RecommendationCard({ item: recommendationItem, scene: { id: "1" }, slate: { lane: "for_you" } });
assert.ok(recommendation.props.className.includes("curator-compact-card"));
assert.ok(!nodes(recommendation).some(node => node.props?.className?.includes("curator-selection-reason")));
const recommendationScore = nodes(recommendation).find(node => node.type === "score");
assert.equal(recommendationScore.props.scoreBarContent, undefined);
assert.ok(nodes(recommendationScore.props.actionsContent).some(node => node.type === "rating"));
assert.ok(nodes(recommendationScore.props.actionsContent).some(node => node.type === "feedback"));
assert.ok(!nodes(recommendation).some(node => node.type === "rating"));
assert.equal(nodes(recommendation).find(node => node.type === "scene").props.curatorAppeal, 0.8);
context.React.cloneElement = (element, props) => ({ ...element, props: { ...element.props, ...props } });
context.Api.patch = { after: (_, callback) => { context.patchNativeCard = callback; } };
vm.runInNewContext(source.slice(source.indexOf('  Api.patch.after("SceneCard",'), source.indexOf('  Api.patch.after("MainNavBar.MenuItems",')), context);
const native = { type: "native", props: { details: "native-details", popovers: "native-popovers" } };
assert.equal(context.patchNativeCard({}, null, native), native);
const patched = context.patchNativeCard({ curatorAppeal: 0.8 }, null, native);
assert.equal(patched.props.details, null);
const nativeScore = nodes(patched.props.popovers).find(node => node.type === "score");
assert.equal(nativeScore.props.metadataContent, "native-popovers");
assert.ok(nodes(nativeScore.props.dateContent).some(node => node.children?.includes("native-details")));
assert.ok(nodes(recommendationScore.props.evidenceContent).some(node => node.children?.includes("Rank in For You: 0.90 (0..1)")));
assert.equal(nodes(recommendationScore.props.evidenceContent).find(node => node.type === "explanation").props.item, recommendationItem);
const review = context.RecommendationCard({ item: { ...recommendationItem, source_lane: "score_review" }, scene: { id: "1" }, slate: { lane: "score_review" } });
assert.ok(!nodes(nodes(review).find(node => node.type === "score").props.evidenceContent).some(node => node.children?.some(child => typeof child === "string" && child.startsWith("Rank in"))));
console.log("Compact Find/recommendation cards, primary score, metadata and collapsed rank checks passed");
