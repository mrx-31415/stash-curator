const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
let patch;
const context = {
  URLSearchParams,
  window: { location: { pathname: "/plugins/stash-curator" } },
  Api: { patch: { before: (name, callback) => { assert.equal(name, "HoverPopover"); patch = callback; } } },
  React: {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    Children: {
      map: (children, callback) => children == null ? children : (Array.isArray(children) ? children : [children]).map(callback),
      toArray: (children) => Array.isArray(children) ? [...children] : [children],
    },
    isValidElement: (element) => Boolean(element?.type),
    cloneElement: (element, props, ...children) => ({ ...element, props: { ...element.props, ...props, ...(children.length ? { children: children.length === 1 ? children[0] : children } : {}) } }),
  },
  NavLink: "NavLink", FontAwesomeIcon: "Icon", faCrosshairs: "crosshairs",
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function PerformerHuntLink("), source.indexOf("  const ExternalCard =")), context);
const performer = { id: "17", name: "A & B / C" };
function checkLink(props, external) {
  const link = context.PerformerHuntLink(props);
  const query = new URL(link.props.to, "http://example.test").searchParams;
  assert.equal(query.get("view"), "hunt");
  assert.equal(query.get("performer"), props.performer.id);
  assert.equal(query.get("label"), props.performer.name);
  assert.equal(query.get("ext"), external ? "1" : null);
  assert.equal(link.props.title, link.props["aria-label"]);
  assert.equal(link.props.children.length, 1, "link must be icon only");
  let stopped = false;
  link.props.onClick({ stopPropagation: () => { stopped = true; } });
  assert(stopped);
}
checkLink({ performer }, false);
checkLink({ performer: { id: "stashdb-uuid", name: performer.name }, external: true }, true);

const image = { type: "a", props: { href: "/performers/17", className: "performer-tag col m-auto zoom-2" } };
const name = { type: "PerformerLink", props: { performer, linkType: "scene" } };
const row = { type: "div", props: { children: [image, name], className: "performer-tag-container row" } };
const props = { className: "performer-count", content: [row], children: "trigger", leaveDelay: 100 };
const extra = {};
const patched = patch(props, extra);
assert.equal(patched[1], extra);
assert.equal(patched[0].children, "trigger");
assert.equal(patched[0].leaveDelay, 100);
const children = patched[0].content[0].props.children;
assert.equal(children[0].props.className, "curator-performer-image-actions");
assert.equal(children[0].props.children[0], image, "preserve the image's profile link");
assert.equal(children[0].props.children[1].type, context.PerformerHuntLink);
assert.equal(children[0].props.children[1].props.performer, performer);
assert.equal(children[1], name, "leave the name and its full width unchanged");
assert.equal(row.props.children[1], name, "do not mutate native content");
assert.equal(patch({ ...props, className: "tag-count" })[0].content, props.content);
context.window.location.pathname = "/scenes";
assert.equal(patch(props)[0], props, "ordinary Stash browsing must stay unchanged");

// Exercise the actual external cast markup, including a locally matched StashDB performer.
Object.assign(context, {
  kind: "scene", ButtonGroup: "ButtonGroup", faTag: "tag", faUser: "user", tags: [],
  cast: [{ id: "stashdb-uuid", name: performer.name, curator_local: { id: "17" } }],
  metadataPopover: (id, icon, label, count, content) => ({ id, content }),
});
context.people = context.cast;
vm.runInContext(source.slice(source.indexOf("    const metadataControls ="), source.indexOf("    async function addToWhisparr()")) + "\nthis.metadataControls = metadataControls;", context);
const externalRow = context.metadataControls.props.children[1].content.props.children[0][0];
assert.equal(externalRow.props.children[0].props.className, "curator-performer-image-actions");
const externalActions = externalRow.props.children[0].props.children;
assert.equal(externalActions[0].props.to, "/performers/17");
checkLink(externalActions[1].props, true);
assert.equal(externalRow.props.children[1].props.to, "/performers/17");
assert.equal(externalRow.props.children[1].props.children[0], performer.name);
const css = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.css"), "utf8");
const iconStyle = css.slice(css.indexOf(".curator-performer-hunt {"), css.indexOf(".curator-performer-hunt:hover"));
assert.match(iconStyle, /position: absolute/);
assert.match(iconStyle, /color: var\(--curator-hue-hunt\)/);
console.log("PASS: Hunt icons overlay images without taking name width or changing profile links");

let state;
Object.assign(context, {
  faClone: "clone",
  faCompass: "compass",
  ReactDOM: { createPortal: (element, host) => ({ element, host }) },
  formatAppealValue: (value) => value.toFixed(2),
  clamp01: (value) => Math.max(0, Math.min(1, value)),
});
context.React.useState = () => [state.shift(), () => {}];
context.React.useEffect = () => {};
let cardPatch;
context.Api.patch.before = (name) => { assert.equal(name, "FilteredPerformerList"); };
context.Api.patch.after = (name, callback) => {
  assert.ok(["PerformerCard", "FilteredPerformerList"].includes(name));
  if (name === "PerformerCard") cardPatch = callback;
};
vm.runInContext(source.slice(source.indexOf("  function CuratorAffinityGauge("), source.indexOf('  Api.patch.after("ScenePage"')), context);
function pageControls(type, details) {
  const host = {};
  state = [host, details];
  const portal = context.CuratorContextLink({ type, id: performer.id, label: performer.name, target: "fixture" });
  return { ...portal, element: context.CuratorContextControls(portal.element.props) };
}
const performerControls = pageControls("performer", { affinity: 0.767, confidence: 0.90, affinity_details: { learned: 0.527, prior: 0.24 } }).element;
assert.match(performerControls.props.className, /curator-context-group-performer/);
assert.equal(performerControls.props.role, "group");
const [brand, gauge, similar, hunt] = performerControls.props.children;
assert.equal(brand.type, "span");
assert.equal(brand.props.children[0].props.icon, "compass");
assert.equal(brand.props["aria-hidden"], true);
assert.equal(similar.props.children[0].props.icon, "clone");
const similarQuery = new URL(similar.props.to, "http://example.test").searchParams;
assert.equal(similarQuery.get("view"), "similar");
assert.equal(similarQuery.get("type"), "performer");
assert.equal(similarQuery.get("id"), performer.id);
assert.equal(hunt.type, context.PerformerHuntLink);
checkLink(hunt.props, false);
assert.equal(context.PerformerHuntLink(hunt.props).props.className, "curator-context-button curator-context-button-hunt");
assert.equal(gauge.props.value, 0.767);
const renderedGauge = context.CuratorAffinityGauge(gauge.props);
assert.match(renderedGauge.props.title, /preference used in recommendations/);
assert.match(renderedGauge.props.title, /Scene evidence 0.53; Favorite and rating 0.24; Similar performers 0.00 \(inferred\)/);
assert.match(renderedGauge.props.title, /Confidence 90%/);
assert.equal(renderedGauge.props.children[1].props.children[1].props.children[0], "Confidence 90%");
assert.equal(renderedGauge.props["aria-label"], renderedGauge.props.title);
assert.equal(renderedGauge.props.tabIndex, 0);
const unavailable = pageControls("performer", null).element.props.children[1];
assert.equal(unavailable.props.value, null);
assert.equal(unavailable.props.confidenceLabel, null);
assert.equal(context.CuratorAffinityGauge(unavailable.props).props.children[1].props.children[0], "—");
const noEvidence = pageControls("performer", { affinity: null, confidence: null }).element.props.children[1];
assert.equal(noEvidence.props.value, 0);
assert.equal(noEvidence.props.confidenceLabel, "No evidence");
const emptyGauge = context.CuratorAffinityGauge(noEvidence.props);
assert.equal(emptyGauge.props.children[1].props.children[0].props.children[0], "0.00");
assert.equal(emptyGauge.props.children[1].props.children[1].props.children[0], "No evidence");
assert.match(emptyGauge.props.title, /contributes zero/);
const neutral = pageControls("performer", { affinity: 0, confidence: 0.7 }).element.props.children[1];
const inferred = pageControls("performer", { affinity: 0.3, confidence: 0.6, affinity_details: { learned: 0, prior: 0, similarity: 0.3 } }).element.props.children[1];
assert.equal(inferred.props.value, 0.3);
assert.match(inferred.props.detail, /Similar performers 0.30 \(inferred\)/);
assert.equal(inferred.props.confidenceLabel, "Confidence 60%");
assert.equal(neutral.props.value, 0);
assert.equal(neutral.props.confidenceLabel, "Confidence 70%", "learned neutral preference differs from missing evidence");
assert.match(pageControls("performer", { affinity: -0.3, confidence: 0 }).element.props.children[1].props.detail, /Confidence 0%/);
assert.match(pageControls("performer", { affinity: 0.2 }).element.props.children[1].props.detail, /Confidence unavailable/);
const sceneControls = pageControls("scene", { score: { appeal: -0.4 } }).element;
assert.equal(sceneControls.props.className, "curator-context-group");
assert.equal(sceneControls.props.children[0], false, "scene pages must not gain a Curator brand marker");
assert.equal(sceneControls.props.children[1], false, "scene pages must not gain a leading performer score");
assert.equal(sceneControls.props.children[3], false, "scene pages must not gain a performer Hunt action");
assert.equal(sceneControls.props.children[4].props.value, -0.4);
state = [null, null];
assert.equal(context.CuratorContextLink({ type: "performer", id: "17", target: "fixture" }), null);
const effects = [];
context.React.useEffect = (effect) => effects.push(effect);
let request;
context.operation = (args) => { request = args; return Promise.resolve({}); };
pageControls("performer", null);
effects[1]();
assert.equal(request.include_similar, false, "the pill must skip the full similar-performer scan");
console.log("PASS: performer pages group Similar, Hunt, and an explained affinity gauge");

context.window.location.pathname = "/performers";
const nativeOverlays = { type: "NativeOverlays", props: {} };
const nativeCard = { type: "GridCard", props: { className: "performer-card", image, title: name, overlays: nativeOverlays } };
const enhancedCard = cardPatch({ performer }, null, nativeCard);
assert.equal(enhancedCard.props.className, nativeCard.props.className);
assert.equal(enhancedCard.props.image, image);
assert.equal(enhancedCard.props.title, name);
assert.equal(enhancedCard.props.overlays.props.children[0], nativeOverlays);
assert.equal(enhancedCard.props.overlays.props.children[1].type, context.CuratorPerformerCardBadge);
assert.equal(enhancedCard.props.overlays.props.children[1].props.performer, performer);
assert.equal(nativeCard.props.overlays, nativeOverlays, "preserve native overlays without mutation");
assert.equal(cardPatch({ performer }, nativeCard).props.overlays.props.children[0], nativeOverlays, "accept the native hook's variable render arguments");
context.window.location.pathname = "/plugins/stash-curator";
assert.equal(cardPatch({ performer }, null, nativeCard), nativeCard, "limit native card badges to the performer grid");
const cardControls = context.CuratorContextControls({ type: "performer", id: performer.id, label: performer.name, details: { affinity: -0.3 }, className: "curator-performer-card-badge" });
assert.match(cardControls.props.className, /curator-performer-card-badge/);
assert.equal(cardControls.props.children[1].props.value, -0.3);
let stopped = false;
cardControls.props.onClick({ stopPropagation: () => { stopped = true; } });
assert(stopped, "card controls must not trigger the native card's click handler");

async function checkSharedAffinityRequest() {
  let calls = 0;
  let finish;
  context.operation = (args) => {
    assert.equal(args.operation, "get_performer_affinities");
    calls++;
    return new Promise((resolve) => { finish = resolve; });
  };
  const first = context.loadPerformerAffinities();
  const second = context.loadPerformerAffinities();
  assert.equal(first, second, "cards mounting together share one request");
  assert.equal(calls, 1);
  finish({ affinities: { "17": { affinity: 0.62, confidence: 0.85 } } });
  assert.equal((await first).affinities["17"].affinity, 0.62);
  const nextPage = context.loadPerformerAffinities();
  assert.equal(calls, 2, "later page loads fetch fresh model data");
  finish({ affinities: {} });
  await nextPage;
  let cardDetails;
  effects.length = 0;
  context.React.useState = () => [null, (value) => { cardDetails = value; }];
  context.CuratorPerformerCardBadge({ performer });
  effects[0]();
  const cardRequest = context.loadPerformerAffinities();
  finish({ affinities: {} });
  await cardRequest;
  assert.equal(cardDetails.affinity, null, "a successful batch without a row is no evidence, not unavailable");
  const emptyCard = context.CuratorContextControls({ type: "performer", details: cardDetails });
  assert.equal(emptyCard.props.children[1].props.value, 0);
  assert.equal(emptyCard.props.children[1].props.confidenceLabel, "No evidence");
  console.log("PASS: performer-grid badges preserve native cards and share a fresh affinity request");
}
checkSharedAffinityRequest().catch((error) => { console.error(error); process.exitCode = 1; });
