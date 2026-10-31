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

// Records observed elements; fire() delivers intersection entries.
const observers = [];
class FakeObserver {
  constructor(callback, options) { this.callback = callback; this.options = options; this.watched = new Set(); observers.push(this); }
  observe(element) { this.watched.add(element); }
  unobserve(element) { this.watched.delete(element); }
}
// Fake card elements, one per scene id: the dataset the store marks and a
// 100px-tall box whose top is relative to an 800px viewport.
const elementsById = new Map();
const el = (id) => elementsById.get(id) || elementsById.set(id, {
  id, dataset: {}, top: 0,
  getBoundingClientRect() { return { top: this.top, height: 100, bottom: this.top + 100 }; },
}).get(id);
const mark = (id) => [el(id).dataset.curatorSweep, el(id).dataset.curatorSweepReason];
// Delivers an intersection entry for an element at the given top.
const fire = (element, visible, top = element.top) => {
  element.top = top;
  observers.forEach((observer) => observer.watched.has(element)
    && observer.callback([{ target: element, isIntersecting: visible, boundingClientRect: element.getBoundingClientRect(), rootBounds: { top: 0 } }]));
};
// On screen below the middle, then scrolled up so its centre passes it.
let activeStore = null;
const scrollPast = (element) => { fire(element, true, 500); element.top = 200; activeStore.scan(); };
const wait = () => new Promise((resolve) => setTimeout(resolve, 150));
// Values built inside the vm context belong to another realm.
const plain = (value) => JSON.parse(JSON.stringify(value));
const scene = (id, extra = {}) => ({ id, score: 0.5, sources: ["tags"], payload: { title: `Scene ${id}`, tags: [], performers: [] }, ...extra });

function harness() {
  const calls = { operations: [], cleared: 0, scheduled: 0 };
  const context = {
    Button: "button", ButtonGroup: "group", NavLink: "a", FontAwesomeIcon: "icon",
    faThumbsDown: "down", faClock: "clock", faBroom: "broom", FIND_SWEEP_KEY: "stash-curator:find-sweep:v1", faList: "list", faTag: "tag", faFilm: "film", faUser: "user",
    WHISPARR_LOGO: "",
    faEyeSlash: "eye-slash",
    // Rendering helpers outside the loaded slices; createElement never calls them.
    EvidenceScore: "evidence", ExplanationView: "explanation", FindSceneReason: "reason", PerformerHuntLink: "hunt-link",
    formatSigned: String, scoreBar: () => null, utilityBar: () => null,
    libraries: { Bootstrap: { Overlay: "overlay", Popover: "popover" } },
    window: {},
    IntersectionObserver: FakeObserver, setTimeout, clearTimeout,
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
  // Scrolling down selects a card once its centre moves above the middle of
  // the viewport. Kept scenes (shortlisted, Whisparr'd, hidden, restored) are
  // marked from the start and never candidates; unmounting forgets a card.
  const app = harness();
  app.context.React = createRuntime().React;
  app.context.window = { innerHeight: 800 };
  const store = app.context.createSweepStore();
  activeStore = store;
  let notified = 0;
  store.subscribe(() => { notified += 1; });
  const items = {
    a: scene("a"), b: scene("b"), c: scene("c", { shortlisted: true }), d: scene("d", { in_whisparr: true }),
    e: scene("e", { dismissed: "not_now" }), f: scene("f"), g: scene("g"), h: scene("h"), never: scene("never"),
  };
  const cleanups = Object.fromEntries(Object.entries(items).map(([id, item]) => [id, store.observe(el(id), item)]));
  assert.equal(store.observe(null, items.a), undefined);
  assert.equal(observers[0].options.threshold, 0);
  // Kept cards show it before any scrolling; the rest are unmarked.
  assert.deepEqual(mark("c"), ["keep", "Shortlisted"]);
  assert.deepEqual(mark("d"), ["keep", "In Whisparr"]);
  assert.deepEqual(mark("a"), [undefined, undefined]);
  for (const id of ["a", "b", "c", "d", "e", "f", "g", "h"]) scrollPast(el(id));
  // On screen, but its centre has not passed the middle: not selected.
  fire(el("never"), true, 500);
  el("never").top = 420;
  store.scan();
  assert.equal(plain(store.candidates({})).includes("never"), false);
  // Above the middle from the start, then scrolled back down: not selected.
  const up = store.observe(el("up"), scene("up"));
  fire(el("up"), true, 100);
  el("up").top = 150;
  store.scan();
  assert.equal(plain(store.candidates({})).includes("up"), false);
  up();
  store.keep("f", "In Whisparr");
  assert.deepEqual(plain(store.candidates({ g: "not_interested", h: "restored" })), ["a", "b"]);
  // Selected cards are dashed to hide; kept ones carry the reason.
  store.setDismissals({ g: "not_interested", h: "restored" });
  assert.deepEqual(mark("a"), ["hide", undefined]);
  assert.deepEqual(mark("c"), ["keep", "Shortlisted"]);
  assert.deepEqual(mark("e"), ["keep", "Hidden"]);
  assert.deepEqual(mark("f"), ["keep", "In Whisparr"]);
  assert.deepEqual(mark("g"), [undefined, undefined], "a dismissed card is a stub, not marked");
  assert.deepEqual(mark("h"), ["keep", "Restored"]);
  assert.deepEqual(mark("never"), [undefined, undefined], "unselected cards are not dashed");
  store.setDismissals({});
  // An undone shortlist releases its keep.
  store.keep("a", "Shortlisted");
  assert.deepEqual(mark("a"), ["keep", "Shortlisted"]);
  store.keep("a", null);
  assert.deepEqual(mark("a"), ["hide", undefined]);
  // A later shortlist arrives as a new item snapshot.
  store.update({ ...items.b, shortlisted: true });
  assert.deepEqual(plain(store.candidates({})), ["a", "g", "h"]);
  assert.deepEqual(mark("b"), ["keep", "Shortlisted"]);
  cleanups.a();
  assert.deepEqual(plain(store.candidates({})), ["g", "h"]);
  assert.deepEqual(mark("a"), [undefined, undefined], "an unmounted card loses its mark");
  // Never on screen (already above when first observed): not selected; flung
  // from the screen past its top between frames: selected.
  const flung = store.observe(el("flung"), scene("flung"));
  fire(el("flung"), false, -900);
  assert.equal(plain(store.candidates({})).includes("flung"), false);
  fire(el("flung"), true, 600);
  fire(el("flung"), false, -300);
  assert.equal(plain(store.candidates({})).includes("flung"), true);
  flung();
  // The end of a paged list selects what is on screen.
  const stopEnd = store.observeEnd(el("end"));
  assert.equal(store.observeEnd(null), undefined);
  fire(el("end"), false);
  assert.equal(plain(store.candidates({})).includes("never"), false);
  fire(el("end"), true);
  assert.equal(plain(store.candidates({})).includes("never"), true);
  assert.deepEqual(mark("never"), ["hide", undefined]);
  stopEnd();
  assert.equal(observers[0].watched.has(el("end")), false);
  await wait();
  assert.ok(notified >= 1 && notified <= 3, "notifications are batched");

  // The view hook sweeps the candidates as one Not now, then Undo returns
  // exactly the swept scenes to undecided.
  const runtime = createRuntime();
  app.context.React = runtime.React;
  app.context.operation = async (args) => {
    app.calls.operations.push(args);
    return { external_ids: args.external_ids.filter((id) => id !== "gone"), kind: args.kind ?? null };
  };
  let state = runtime.render(() => app.context.useExternalDismissals());
  const sweep = state.sweep;
  for (const id of ["x", "y", "gone"]) sweep.observe(el(id), scene(id));
  let tree;
  let bar = () => runtime.render(() => app.context.useExternalDismissals()).sweepBar();
  const renderBar = () => { const element = bar(); return element.type(element.props); };
  const barOf = (node) => nodes(node).find((child) => child.props?.className === "curator-sweep-bar");
  tree = renderBar();
  assert.equal(tree.props.className, "curator-sweep-end", "the end marker always renders");
  assert.equal(barOf(tree), undefined, "nothing seen yet");
  activeStore = sweep;
  for (const id of ["x", "y", "gone"]) scrollPast(el(id));
  tree = renderBar();
  const button = nodes(tree).find((node) => node.type === "button" && text(node).includes("3 seen"));
  assert.ok(button, text(tree));
  await button.props.onClick();
  await settle();
  assert.deepEqual(plain(app.calls.operations.at(-1)), { operation: "update_external_dismissal", external_ids: ["x", "y", "gone"], kind: "not_now" });
  state = runtime.render(() => app.context.useExternalDismissals());
  assert.deepEqual(plain(state.dismissals), { x: "not_now", y: "not_now" });
  tree = renderBar();
  assert.match(text(tree), /2 hidden/);
  // "gone" left the cache: still undecided, still offered.
  assert.ok(nodes(tree).some((node) => node.type === "button" && text(node).includes("1 seen")));
  await byText(tree, "Undo").props.onClick();
  await settle();
  assert.deepEqual(plain(app.calls.operations.at(-1)), { operation: "update_external_dismissal", external_ids: ["x", "y"], kind: null });
  state = runtime.render(() => app.context.useExternalDismissals());
  assert.deepEqual(plain(state.dismissals), {});
  tree = renderBar();
  assert.doesNotMatch(text(tree), /hidden/);
  assert.ok(nodes(tree).some((node) => node.type === "button" && text(node).includes("3 seen")));
  assert.equal(app.calls.cleared, 2);

  // The toolbar toggle: on by default, remembered per browser; off gives the
  // cards no sweep (clearing their marks) and drops the bar.
  const stored = {};
  app.context.window = { localStorage: { getItem: (key) => stored[key] ?? null, setItem: (key, value) => { stored[key] = value; } } };
  const toggleRuntime = createRuntime();
  app.context.React = toggleRuntime.React;
  let toggled = toggleRuntime.render(() => app.context.useExternalDismissals());
  assert.ok(toggled.sweep);
  let toggle = toggled.sweepToggle();
  assert.equal(toggle.props["aria-pressed"], true);
  toggle.props.onClick();
  toggled = toggleRuntime.render(() => app.context.useExternalDismissals());
  assert.equal(toggled.sweep, undefined);
  assert.equal(toggled.sweepBar(true), null);
  assert.equal(toggled.sweepToggle().props["aria-pressed"], false);
  assert.equal(stored["stash-curator:find-sweep:v1"], "off");
  const reloaded = createRuntime();
  app.context.React = reloaded.React;
  assert.equal(reloaded.render(() => app.context.useExternalDismissals()).sweep, undefined);
  app.context.window = {};

  // A scene card registers its element once mounted; shortlisting or sending
  // to Whisparr keeps it out of the sweep, and a saved Whisparr send shows
  // as already sent after a reload.
  const cardRuntime = createRuntime();
  app.context.React = cardRuntime.React;
  const registered = [];
  const kept = [];
  const fakeSweep = {
    observe: (element, item) => { if (!element) return undefined; registered.push([element, item.id]); return () => registered.push(["gone", item.id]); },
    update: () => {}, keep: (id, reason) => kept.push([id, reason]),
  };
  const shortlisted = [];
  const card = (props = {}) => cardRuntime.render(() => app.context.ExternalCard({
    item: scene("card", props.item), kind: "scene", sweep: fakeSweep, onDismiss: async () => {},
    onShortlist: async (item) => shortlisted.push(item.id), onWhisparr: async () => ({ status: "sent" }), whisparrEnabled: true, ...props.extra,
  }));
  tree = card();
  assert.deepEqual(registered, []);
  tree.props.ref("card-element");
  tree = card();
  assert.deepEqual(registered, [["card-element", "card"]]);
  const actionsOf = (node) => nodes(node).filter((child) => child.props?.actionsContent)
    .flatMap((child) => nodes(child.props.actionsContent)).find((child) => child.type === app.context.ExternalActions).props;
  await actionsOf(tree).onShortlist(scene("card"), "scene");
  assert.deepEqual(kept, [["card", "Shortlisted"]]);
  assert.deepEqual(shortlisted, ["card"]);
  await actionsOf(tree).onAddToWhisparr();
  assert.deepEqual(kept, [["card", "Shortlisted"], ["card", "In Whisparr"]]);
  const sentRuntime = createRuntime();
  app.context.React = sentRuntime.React;
  tree = sentRuntime.render(() => app.context.ExternalCard({ item: scene("sent", { in_whisparr: true }), kind: "scene", onWhisparr: async () => ({}), whisparrEnabled: true }));
  assert.equal(actionsOf(tree).whisparr.status, "already_exists");
  // Thumbnails register too, and a hidden one is dimmed in place.
  const thumbRuntime = createRuntime();
  app.context.React = thumbRuntime.React;
  tree = thumbRuntime.render(() => app.context.ExternalCard({ item: scene("thumb"), kind: "scene", thumbnails: true, sweep: fakeSweep, dismissal: "not_now" }));
  const thumbnail = tree.type(tree.props);
  assert.ok(thumbnail.props.className.includes("curator-find-thumbnail-hidden"));
  tree.props.articleRef("thumb-element");
  thumbRuntime.render(() => app.context.ExternalCard({ item: scene("thumb"), kind: "scene", thumbnails: true, sweep: fakeSweep, dismissal: "not_now" }));
  assert.deepEqual(registered.at(-1), ["thumb-element", "thumb"]);
  // Performer cards never join the sweep.
  const performerRuntime = createRuntime();
  app.context.React = performerRuntime.React;
  const before = registered.length;
  tree = performerRuntime.render(() => app.context.ExternalCard({ item: { ...scene("p"), payload: { name: "P", images: [] } }, kind: "performer", sweep: fakeSweep }));
  tree.props.ref("performer-element");
  performerRuntime.render(() => app.context.ExternalCard({ item: { ...scene("p"), payload: { name: "P", images: [] } }, kind: "performer", sweep: fakeSweep }));
  assert.equal(registered.length, before);

  // On a phone held upright Stash's navbar is at the bottom; the bar lifts above it.
  app.context.window = { innerHeight: 800 };
  app.context.document = { querySelector: () => ({ getBoundingClientRect: () => ({ top: 744 }) }) };
  assert.equal(app.context.bottomNavbarHeight(), 56);
  app.context.document = { querySelector: () => ({ getBoundingClientRect: () => ({ top: 0 }) }) };
  assert.equal(app.context.bottomNavbarHeight(), 0);
})().catch((error) => { console.error(error); process.exit(1); });
