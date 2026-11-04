const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const block = source.slice(source.indexOf("  const RANKING_RESULT_PICKS"), source.indexOf("  function rankingViewingLabel("));

// Just enough React to run the bridge: hooks in call order, effects once,
// and a re-render on every state update.
function harness(overrides = {}) {
  const hooks = [];
  let index = 0;
  const effects = [];
  let output = null;
  let component = null;
  const render = () => {
    index = 0;
    output = component();
    effects.splice(0).forEach((effect) => effect());
  };
  const React = {
    useState(initial) {
      const key = index++;
      if (!(key in hooks)) hooks[key] = initial;
      return [hooks[key], (value) => { hooks[key] = typeof value === "function" ? value(hooks[key]) : value; render(); }];
    },
    useRef(initial) {
      const key = index++;
      if (!(key in hooks)) hooks[key] = { current: initial };
      return hooks[key];
    },
    useEffect(effect) {
      const key = index++;
      if (!(key in hooks)) { hooks[key] = true; effects.push(effect); }
    },
    createElement: (type, props) => ({ type, props }),
  };
  class Element { constructor() { this.isConnected = true; } }
  const document = new EventTarget();
  const calls = [];
  const affinities = {
    1: { affinity_details: { learned: 0.3, similarity: 0, learned_confidence: 0.8, similarity_confidence: 0 } },
    2: { affinity_details: { learned: -0.1, similarity: 0, learned_confidence: 0.8, similarity_confidence: 0 } },
  };
  const context = vm.createContext({
    React,
    ReactDOM: { createPortal: (element, slot) => ({ portal: element, slot }) },
    Element,
    document,
    location: { pathname: "/performers" },
    getPluginSettings: async () => ({}),
    loadPerformerAffinities: async () => { calls.push("affinities"); return { affinities }; },
    stashQuery: async (query) => {
      calls.push(query.includes("CuratorRankingTraits") ? "traits" : "scenes");
      return query.includes("CuratorRankingTraits")
        ? { findPerformers: { performers: [] } }
        : { findScenes: { scenes: [{ id: "7", title: "Scene" }] } };
    },
    operation: async (args) => { calls.push(args); return { items: [{ scene_id: "7" }] }; },
    laneSlateRequest: (slate, filters) => ({ lane: slate.lane, performer_ids: filters.performers.map((p) => p.id) }),
    SCENE_REASON_SCENES_QUERY: "query Scenes",
    RankingVerdict: "RankingVerdict",
    RankingPicks: "RankingPicks",
    Math: Object.assign(Object.create(Math), { random: () => 0.99 }),
    ...overrides,
  });
  vm.runInContext(`${block}\nthis.Bridge = RankingBridge;`, context);
  component = context.Bridge;
  render();
  return { context, document, Element, calls, current: () => output };
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const match = (slot, extra = {}) => new CustomEvent("stash-ranking:match", { detail: {
  source: "test", itemType: "performer", slot,
  winner: { id: "1", name: "Winner" }, loser: { id: "2", name: "Loser" }, ...extra,
} });

test("a performer match renders the verdict into the event's slot", async () => {
  const { document, Element, current } = harness();
  const slot = new Element();
  document.dispatchEvent(match(slot));
  await settle();
  const shown = current();
  assert.equal(shown.slot, slot);
  assert.equal(shown.portal.type, "RankingVerdict");
  assert.equal(shown.portal.props.verdict.tier, "dependable");
  assert.equal(shown.portal.props.tally.agreed, 1);
  assert.match(shown.portal.props.line, /\S/);
});

test("other item types and events without a slot render nothing", async () => {
  const { document, Element, current } = harness();
  document.dispatchEvent(match(new Element(), { itemType: "scene" }));
  await settle();
  assert.equal(current(), null);
  document.dispatchEvent(match(null));
  await settle();
  assert.equal(current(), null);
});

test("the tally runs across one slot and restarts with a new one", async () => {
  const { document, Element, current } = harness();
  const slot = new Element();
  document.dispatchEvent(match(slot));
  await settle();
  document.dispatchEvent(match(slot));
  await settle();
  assert.equal(current().portal.props.tally.agreed, 2);
  document.dispatchEvent(match(new Element()));
  await settle();
  assert.equal(current().portal.props.tally.agreed, 1);
});

test("a result shows the session's picks and hands over the plugin's close", async () => {
  const { document, Element, calls, current } = harness();
  const slot = new Element();
  document.dispatchEvent(match(slot));
  await settle();
  const close = () => {};
  const resultSlot = new Element();
  document.dispatchEvent(new CustomEvent("stash-ranking:result", { detail: {
    source: "test", itemType: "performer", kind: "champion", item: { id: "1", name: "Winner" }, slot: resultSlot, close,
  } }));
  await settle();
  const shown = current();
  assert.equal(shown.slot, resultSlot);
  assert.equal(shown.portal.type, "RankingPicks");
  assert.equal(shown.portal.props.close, close);
  assert.equal(shown.portal.props.tally.agreed, 1);
  const slate = calls.find((call) => call.operation === "get_slate");
  assert.deepEqual(JSON.parse(JSON.stringify(slate.performer_ids)), ["1"]);
  assert.equal(slate.context.surface, "ranking:test");
});

const undo = (slot, winner = "1", loser = "2") => new CustomEvent("stash-ranking:undo", { detail: {
  source: "test", itemType: "performer", slot, winner: { id: winner, name: "Winner" }, loser: { id: loser, name: "Loser" },
} });

test("an undo takes the last match out of the tally and says so", async () => {
  const { document, Element, current } = harness();
  const slot = new Element();
  document.dispatchEvent(match(slot));
  await settle();
  document.dispatchEvent(match(slot));
  await settle();
  assert.equal(current().portal.props.tally.agreed, 2);
  document.dispatchEvent(undo(slot));
  await settle();
  const shown = current().portal.props;
  assert.equal(shown.verdict.tier, "undo");
  assert.equal(shown.verdict.voice, "undoAgreed");
  assert.equal(shown.tally.agreed, 1);
  assert.equal(shown.kicker, null);
  // The next match counts from the restored state.
  document.dispatchEvent(match(slot));
  await settle();
  assert.equal(current().portal.props.tally.agreed, 2);
});

test("an undo of a match the session never saw changes nothing", async () => {
  const { document, Element, current } = harness();
  const slot = new Element();
  document.dispatchEvent(match(slot));
  await settle();
  document.dispatchEvent(undo(slot, "3", "4"));
  await settle();
  assert.equal(current().portal.props.verdict.voice, "undo");
  assert.equal(current().portal.props.tally.agreed, 1);
});

test("a draw counts as close, not as the first performer winning", async () => {
  const { document, Element, current } = harness();
  document.dispatchEvent(match(new Element(), { draw: true }));
  await settle();
  const shown = current().portal.props;
  assert.equal(shown.verdict.voice, "draw");
  assert.equal(shown.tally.close, 1);
  assert.equal(shown.tally.agreed, 0);
});

test("a sessionId keeps one session across new slots, and an undo between screens still counts", async () => {
  const { document, Element, current } = harness();
  document.dispatchEvent(match(new Element(), { sessionId: "bracket-1" }));
  await settle();
  document.dispatchEvent(match(new Element(), { sessionId: "bracket-1" }));
  await settle();
  assert.equal(current().portal.props.tally.agreed, 2);
  const between = new CustomEvent("stash-ranking:undo", { detail: {
    source: "test", itemType: "performer", sessionId: "bracket-1", slot: null,
    winner: { id: "1", name: "Winner" }, loser: { id: "2", name: "Loser" },
  } });
  document.dispatchEvent(between);
  await settle();
  assert.equal(current(), null);
  document.dispatchEvent(match(new Element(), { sessionId: "bracket-1" }));
  await settle();
  assert.equal(current().portal.props.tally.agreed, 2);
  document.dispatchEvent(match(new Element(), { sessionId: "bracket-2" }));
  await settle();
  assert.equal(current().portal.props.tally.agreed, 1);
});

test("a result opens with Curator's take on the champion and the run", async () => {
  const { document, Element, current } = harness();
  const slot = new Element();
  document.dispatchEvent(match(slot));
  await settle();
  document.dispatchEvent(new CustomEvent("stash-ranking:result", { detail: {
    source: "test", itemType: "performer", kind: "champion", item: { id: "1", name: "Winner" }, slot: new Element(),
  } }));
  await settle();
  const { messages } = current().portal.props;
  assert.match(messages[0].text, /Winner/);
  assert.match(messages[1].text, /1 of (your )?1/);
  assert.equal(messages.length, 2);
});

test("the close button hides the comments until the plugin reopens", async () => {
  const { document, Element, current } = harness();
  const slot = new Element();
  document.dispatchEvent(match(slot));
  await settle();
  current().portal.props.dismiss();
  assert.equal(current(), null);
  document.dispatchEvent(match(slot));
  await settle();
  assert.equal(current(), null);
  document.dispatchEvent(match(new Element()));
  await settle();
  assert.equal(current().portal.type, "RankingVerdict");
});

test("Hide comments in ranking plugins keeps the strip away", async () => {
  const { document, Element, current } = harness({ getPluginSettings: async () => ({ hideRankingComments: true }) });
  document.dispatchEvent(match(new Element()));
  await settle();
  assert.equal(current(), null);
});

test("a pick arriving after its result screen counts but never clears the result", async () => {
  const { document, Element, current } = harness();
  document.dispatchEvent(match(new Element(), { sessionId: "b1" }));
  await settle();
  document.dispatchEvent(new CustomEvent("stash-ranking:result", { detail: {
    source: "test", itemType: "performer", kind: "champion", sessionId: "b1", item: { id: "1", name: "Winner" }, slot: new Element(),
  } }));
  document.dispatchEvent(match(null, { sessionId: "b1" }));
  await settle();
  const shown = current().portal;
  assert.equal(shown.type, "RankingPicks");
  assert.equal(shown.props.tally.agreed, 2);
});

test("quick picks all count, and only the last is shown", async () => {
  const { document, Element, current } = harness();
  const slot = new Element();
  document.dispatchEvent(match(slot));
  document.dispatchEvent(match(slot));
  document.dispatchEvent(match(slot));
  await settle();
  assert.equal(current().portal.props.tally.agreed, 3);
});

test("the dismiss button's class is not a verdict's class", () => {
  const tiers = [...source.matchAll(/curator-ranking-\$\{verdict\.tier\}/g)];
  assert.ok(tiers.length > 0);
  const tierNames = Object.keys(JSON.parse(source.match(/const RANKING_MOODS = (\{[^}]*\})/)[1].replace(/(\w+):/g, '"$1":')));
  const button = source.match(/className: "curator-ranking-(\w+)", onClick: dismiss/)[1];
  assert.ok(!tierNames.includes(button), button);
});

function pure(extra = {}) {
  const context = vm.createContext({ Math, Date, ...extra });
  const start = source.indexOf("  const RANKING_CLEAR");
  vm.runInContext(`${source.slice(start, source.indexOf("  function RankingBridge(", start))}
this.api = { rankingPick, rankingFactVoice, rankingPlays, RANKING_LINES, RANKING_FACTS };`, context);
  return context.api;
}

test("every line of a kind plays before any repeats, across page loads", () => {
  const store = new Map();
  const localStorage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const { rankingPick, RANKING_LINES } = pure({ localStorage });
  const size = RANKING_LINES.agree.length;
  const first = Array.from({ length: size }, () => rankingPick(RANKING_LINES, "agree"));
  assert.equal(new Set(first).size, size);
  // A new page load picks up the deck where it was left.
  const again = pure({ localStorage });
  const next = again.rankingPick(again.RANKING_LINES, "agree");
  assert.notEqual(next, first[first.length - 1]);
});

test("fact lines say only what the play history supports", () => {
  const random = Object.assign(Object.create(Math), { random: () => 0 });
  const { rankingFactVoice, rankingPlays } = pure({ Math: random });
  const now = Date.parse("2026-11-03T12:00:00Z");
  const plays = rankingPlays([
    { play_count: 9, o_counter: 0, last_played_at: "2025-01-10T00:00:00Z", performers: [{ id: "2" }] },
    { play_count: 1, o_counter: 0, last_played_at: "2026-11-02T00:00:00Z", performers: [{ id: "1" }] },
  ]);
  const surprise = rankingFactVoice(plays, "surprise", { id: "1" }, { id: "2" }, now);
  assert.ok(["factContrast", "factStale"].includes(surprise.voice));
  assert.equal(surprise.values.lp, "9");
  assert.equal(surprise.values.wpp, "only 1");
  assert.equal(surprise.values.lwhen, "January 2025");
  // One play is no history to boast about; a watch yesterday is recent.
  const agreed = rankingFactVoice(plays, "agree", { id: "1" }, { id: "2" }, now);
  assert.equal(agreed.voice, "factRecent");
  assert.equal(agreed.values.wago, "yesterday");
  assert.equal(rankingFactVoice(plays, "unknown", { id: "1" }, { id: "2" }, now), null);
  assert.equal(rankingFactVoice(null, "agree", { id: "1" }, { id: "2" }, now), null);
});

test("library, studio and shared-scene facts come from real counts", () => {
  const random = Object.assign(Object.create(Math), { random: () => 0 });
  const { rankingFactVoice, rankingPlays } = pure({ Math: random });
  const now = Date.parse("2026-11-03T12:00:00Z");
  const plays = rankingPlays([
    { play_count: 6, o_counter: 0, last_played_at: "2026-01-01T00:00:00Z", studio: { name: "Studio A" }, performers: [{ id: "1" }, { id: "2" }] },
    { play_count: 2, o_counter: 0, last_played_at: "2026-01-01T00:00:00Z", studio: { name: "Studio B" }, performers: [{ id: "1" }] },
  ]);
  const taste = { byId: new Map([["1", { scenes: 12 }]]), lean: new Map() };
  const voice = rankingFactVoice(plays, "agree", { id: "1" }, { id: "2" }, now, taste);
  assert.equal(voice.values.wu, "10");
  assert.equal(voice.values.studio, "Studio A");
  assert.equal(voice.values.sn, "6");
  assert.equal(voice.values.tn, "1");
  assert.equal(voice.values.tscenes, "scene");
});

test("picking the much lower rated one is an upset", async () => {
  const { document, Element, current } = harness();
  const slot = new Element();
  // Past the opener, an upset: 42 against 70 before the match, 28 behind.
  document.dispatchEvent(match(slot));
  await settle();
  document.dispatchEvent(match(slot, {
    winner: { id: "1", name: "Winner", rating: 50, change: 8 },
    loser: { id: "3", name: "Other", rating: 62, change: -8 },
  }));
  await settle();
  assert.equal(current().portal.props.kicker.kind, "upset");
  assert.match(current().portal.props.kicker.text, /\b28\b/);
});
