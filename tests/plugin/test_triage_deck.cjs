const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");

// A minimal hook runtime: state and refs persist by call order, effects run
// after each render when their dependencies change, and unmount runs every
// cleanup.
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
    useRef(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = { current: initial };
      return hooks[index];
    },
    useEffect(effect, deps) {
      const index = cursor++;
      const previous = hooks[index];
      if (!previous || !deps || deps.some((dep, i) => dep !== previous.deps[i])) {
        hooks[index] = { deps, cleanup: previous?.cleanup };
        pendingEffects.push(() => {
          hooks[index].cleanup?.();
          hooks[index].cleanup = effect();
        });
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
    unmount() {
      hooks.forEach((hook) => hook?.cleanup?.());
    },
  };
}

const children = (node) => (node && typeof node === "object" ? node.props?.children || [] : []);
const nodes = (node) => (node && typeof node === "object" ? [node, ...children(node).flatMap(nodes)] : []);
const text = (node) => (node == null || node === false ? "" : typeof node === "object" ? children(node).map(text).join(" ") : String(node));
// Values built inside the vm context come from another realm.
const plain = (value) => JSON.parse(JSON.stringify(value));
const settle = () => new Promise((resolve) => setImmediate(resolve));

function scene(id, extra = {}) {
  return { id, score: 0.5, sources: ["tags"], payload: { title: `Scene ${id}`, images: [{ url: `https://img/${id}.jpg` }], tags: [], performers: [] }, ...extra };
}

function harness({ whisparrEnabled = true } = {}) {
  let clock = 1000, timerId = 0;
  const timers = new Map();
  const listeners = {};
  const calls = { operations: [], whisparr: [], patches: [], pages: [] };
  const context = {
    Button: "button", FontAwesomeIcon: "icon", WHISPARR_LOGO: "",
    faThumbsDown: "down", faClock: "clock", faList: "list", faForward: "forward", faRotateLeft: "undo", faExternalLinkAlt: "external",
    ExternalDismissFollowUp: "follow-up", NavLink: "navlink", PerformerHuntLink: "hunt",
    externalImageProps: (images) => ({ key: "", src: images?.[0]?.url, onError: () => {} }),
    stashboxEntityURL: () => "https://stashdb.org/scenes/x",
    findSceneSummary: () => "Matches your preferences.",
    clearEndlessCache: () => {},
    operation: async (args) => { calls.operations.push(args); return {}; },
    performance: { now: () => clock },
    setTimeout: (callback, ms) => { timers.set(++timerId, { at: clock + ms, callback }); return timerId; },
    clearTimeout: (id) => timers.delete(id),
    requestAnimationFrame: () => 0,
    cancelAnimationFrame: () => {},
    navigator: {},
    Image: function Image() {},
    window: {
      matchMedia: () => ({ matches: false }),
      addEventListener: (type, listener) => { listeners[type] = listener; },
      removeEventListener: (type) => { delete listeners[type]; },
    },
    Math, Set, Map, Number, String, Boolean, Object, Promise, JSON, Error,
  };
  context.React = createRuntime().React;
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("  // Deck: one Stash-box scene at a time"), source.indexOf("  const SourceReference =")), context);
  const runtime = createRuntime();
  context.React = runtime.React;
  return {
    context, calls, runtime,
    advance(ms) {
      clock += ms;
      for (const [id, timer] of [...timers].sort((a, b) => a[1].at - b[1].at)) {
        if (timer.at <= clock) { timers.delete(id); timer.callback(); }
      }
    },
    key(type, key, extra = {}) {
      listeners[type]({ key, repeat: false, shiftKey: false, target: { tagName: "BODY" }, preventDefault() {}, ...extra });
    },
    deck(props) {
      const all = {
        first: { page: 1, has_more: false, items: [scene("a"), scene("b"), scene("c")] },
        loadPage: async (page) => { calls.pages.push(page); return { page, has_more: false, items: [] }; },
        gender: "", whisparrEnabled,
        onWhisparr: async (id) => { calls.whisparr.push(id); return { status: "sent" }; },
        onItemChange: (id, change) => calls.patches.push([id, change]),
        ...props,
      };
      return () => runtime.render(() => context.TriageDeck(all));
    },
  };
}

// The top card is the DeckCard element that is not the peeking back card.
const top = (tree) => nodes(tree).find((node) => typeof node.type === "function" && node.type.name === "DeckCard" && !node.props.back);
const title = (tree) => top(tree)?.props.item.payload.title;
const drag = (tree) => top(tree).props.handlers;
// Rendered DeckCard content, for checks inside the card.
const card = (tree) => top(tree).type(top(tree).props);
// The hint's steps as [state, prefix, label], read from the rendered DeckHint.
const hint = (tree) => {
  const element = top(tree).props.hint;
  if (!element) return null;
  return nodes(element.type(element.props)).filter((node) => node.props?.className?.startsWith?.("curator-deck-hint-step"))
    .map((node) => [node.props.className.match(/curator-deck-hint-(current|passed)/)?.[1] || "", ...children(node).filter(Boolean).map(text)]);
};
const button = (tree, label) => nodes(tree).find((node) => node.type === "button" && node.props["aria-label"] === label);
const pointer = (x, y, extra = {}) => ({ pointerId: 1, pointerType: "touch", button: 0, clientX: x, clientY: y, currentTarget: { offsetWidth: 400 }, ...extra });

(async () => {
  // The zone and action rules: a short drag is nothing, the threshold is a
  // quarter of the card, holding upgrades left always and right only with
  // Whisparr configured, and up is Skip.
  {
    const { context } = harness();
    assert.equal(context.deckZone(-50, 0, 400), null);
    assert.equal(context.deckZone(-120, 10, 400), "left");
    assert.equal(context.deckZone(120, -20, 400), "right");
    assert.equal(context.deckZone(20, -120, 400), "up");
    assert.equal(context.deckAction("left", false, true), "not_now");
    assert.equal(context.deckAction("left", true, true), "not_interested");
    assert.equal(context.deckAction("right", true, true), "whisparr");
    assert.equal(context.deckAction("right", true, false), "shortlist");
    assert.equal(context.deckAction("up", true, true), "skip");
  }

  // Buttons act on the top card, the card animates out, and Undo restores
  // both the dismissal and the position.
  {
    const app = harness();
    const render = app.deck();
    let tree = render();
    assert.equal(title(tree), "Scene a");
    button(tree, "Not now").props.onClick();
    await settle();
    app.advance(200);
    tree = render();
    assert.equal(title(tree), "Scene b");
    assert.deepEqual(plain(app.calls.operations.at(-1)), { operation: "update_external_dismissal", external_id: "a", kind: "not_now" });
    assert.deepEqual(plain(app.calls.patches.at(-1)), ["a", { dismissed: "not_now" }]);
    assert.match(text(tree), /1 reviewed/);
    button(tree, "Undo").props.onClick();
    await settle();
    tree = render();
    assert.equal(title(tree), "Scene a");
    assert.deepEqual(plain(app.calls.operations.at(-1)), { operation: "update_external_dismissal", external_id: "a", kind: null });
  }

  // Keys: a tap is the light action on release, a hold past the bar is the
  // strong one, Shift is instant, and Up skips without an operation.
  {
    const app = harness();
    const render = app.deck();
    render();
    app.key("keydown", "ArrowLeft");
    render();
    app.advance(100);
    app.key("keyup", "ArrowLeft");
    await settle();
    app.advance(200);
    assert.equal(app.calls.operations.at(-1).kind, "not_now");
    render();
    app.key("keydown", "ArrowLeft");
    render();
    app.advance(800);
    app.key("keyup", "ArrowLeft");
    await settle();
    app.advance(200);
    assert.equal(app.calls.operations.at(-1).kind, "not_interested");
    let tree = render();
    // Not interested asks what put you off before the next card.
    assert.equal(nodes(tree).some((node) => node.type === "follow-up"), true);
    const count = app.calls.operations.length;
    app.key("keydown", "ArrowUp");
    assert.equal(app.calls.operations.length, count, "the follow-up blocks deck keys");
  }

  // Hold right sends to Whisparr only after a grace period; Undo inside it
  // cancels the request, and leaving the deck flushes one still pending.
  {
    const app = harness();
    const render = app.deck();
    render();
    app.key("keydown", "ArrowRight", { shiftKey: true });
    await settle();
    app.advance(200);
    let tree = render();
    assert.equal(title(tree), "Scene b");
    assert.deepEqual(plain(app.calls.whisparr), []);
    button(tree, "Undo").props.onClick();
    await settle();
    app.advance(5000);
    assert.deepEqual(plain(app.calls.whisparr), [], "Undo cancelled the send");
    tree = render();
    assert.equal(title(tree), "Scene a");
    app.key("keydown", "ArrowRight", { shiftKey: true });
    app.advance(3200);
    assert.deepEqual(plain(app.calls.whisparr), ["a"]);
    render();
    app.key("keydown", "ArrowRight", { shiftKey: true });
    app.advance(200);
    app.runtime.unmount();
    assert.deepEqual(plain(app.calls.whisparr), ["a", "b"]);
  }

  // Without Whisparr configured, holding right still only shortlists.
  {
    const app = harness({ whisparrEnabled: false });
    const render = app.deck();
    render();
    app.key("keydown", "ArrowRight");
    render();
    app.advance(900);
    app.key("keyup", "ArrowRight");
    await settle();
    assert.deepEqual(plain(app.calls.operations.at(-1)), { operation: "update_shortlist", entity_type: "scene", external_id: "a", selected: true });
    assert.deepEqual(plain(app.calls.whisparr), []);
  }

  // Touch: a tap opens details; a drag held past the bar is the strong action;
  // a drag released inside the threshold springs back.
  {
    const app = harness();
    const render = app.deck();
    let tree = render();
    // The title links to the scene on Stash-box and keeps its pointer to itself.
    const titleLink = nodes(card(tree)).find((node) => node.props?.className === "curator-deck-title-link");
    assert.equal(titleLink.props.href, "https://stashdb.org/scenes/x");
    assert.equal(titleLink.props.target, "_blank");
    let stopped = false;
    titleLink.props.onPointerDown({ stopPropagation: () => { stopped = true; } });
    assert.equal(stopped, true);
    drag(tree).onPointerDown(pointer(200, 200));
    drag(tree).onPointerUp(pointer(202, 201));
    tree = render();
    assert.equal(top(tree).props.expanded, true);
    assert.equal(nodes(card(tree)).some((node) => node.props?.className === "curator-deck-link"), true);
    drag(tree).onPointerDown(pointer(200, 200));
    drag(tree).onPointerMove(pointer(150, 205));
    drag(tree).onPointerUp(pointer(150, 205));
    tree = render();
    assert.equal(app.calls.operations.length, 0);
    // The hint names both outcomes throughout: before the threshold, while
    // the hold runs, and once the strong action has taken over.
    drag(tree).onPointerDown(pointer(200, 200));
    drag(tree).onPointerMove(pointer(150, 202));
    tree = render();
    assert.deepEqual(plain(hint(tree)), [["", "Swipe for", "Not now"], ["", "Then hold for", "Not interested"]]);
    drag(tree).onPointerMove(pointer(40, 210));
    app.advance(400);
    drag(tree).onPointerMove(pointer(30, 212));
    tree = render();
    assert.deepEqual(plain(hint(tree)), [["current", "Release for", "Not now"], ["", "Keep holding for", "Not interested"]]);
    app.advance(400);
    tree = render();
    assert.deepEqual(plain(hint(tree)), [["passed", "Not now"], ["current", "Release for", "Not interested"]]);
    drag(tree).onPointerUp(pointer(30, 212));
    await settle();
    assert.equal(app.calls.operations.at(-1).kind, "not_interested");
  }

  // Performers show as previews with a Hunt link; the row keeps its own
  // pointer so tapping a performer never starts a swipe.
  {
    const app = harness();
    const performers = [
      { performer: { id: "p-local", name: "Local One", gender: "FEMALE", curator_local: { id: "7" }, images: [{ url: "https://img/p1.jpg" }] } },
      { performer: { id: "p-remote", name: "Remote Two", gender: "FEMALE", images: [] } },
      { performer: { id: "p-male", name: "Other", gender: "MALE", images: [] } },
    ];
    const item = scene("a", { payload: { title: "Scene a", images: [], tags: [], performers } });
    const tree = app.deck({ gender: "FEMALE", first: { page: 1, has_more: false, items: [item] } })();
    const row = nodes(card(tree)).find((node) => node.props?.className === "curator-deck-people");
    let stopped = false;
    row.props.onPointerDown({ stopPropagation: () => { stopped = true; } });
    assert.equal(stopped, true);
    const hunts = nodes(row).filter((node) => node.type === "hunt");
    assert.deepEqual(hunts.map((node) => [node.props.performer.id, node.props.external]), [["p-local", true], ["p-remote", true]]);
    assert.equal(nodes(row).find((node) => node.type === "navlink")?.props.to, "/performers/7");
    assert.match(text(row), /\+1 other performers/);
  }

  // Expand pages forward as the queue runs low; scenes already dismissed and
  // duplicates from a shifted page are left out.
  {
    const app = harness();
    const render = app.deck({
      first: { page: 2, has_more: true, items: [scene("a"), scene("gone", { dismissed: "not_now" })] },
      loadPage: async (page) => { app.calls.pages.push(page); return { page, has_more: false, items: [scene("a"), scene("d")] }; },
    });
    render();
    await settle();
    let tree = render();
    assert.deepEqual(plain(app.calls.pages), [3]);
    assert.equal(title(tree), "Scene a");
    app.key("keydown", "ArrowUp");
    app.advance(200);
    tree = render();
    assert.equal(title(tree), "Scene d");
    app.key("keydown", "ArrowUp");
    app.advance(200);
    tree = render();
    assert.match(text(tree), /every scene matching these filters/);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
