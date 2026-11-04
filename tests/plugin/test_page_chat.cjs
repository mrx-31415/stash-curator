const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const block = source.slice(source.indexOf("  const PAGE_CHAT_KEY"), source.indexOf("  function PageChat("));
const DAY = 86400000;

// Walks each table in order, like the real shuffled decks do.
function cycling() {
  const at = {};
  return (table, key) => { at[key] = (at[key] ?? -1) + 1; return table[key][at[key] % table[key].length]; };
}

function load(pick = cycling()) {
  const context = vm.createContext({
    rankingPick: pick,
    rankingAgo: (ms, now) => `${Math.floor((now - ms) / DAY)} days ago`,
    rankingWhen: () => "March",
    rankingViewing: (affinities, id) => affinities[id] || { value: 0, basis: "none" },
  });
  vm.runInContext(`${block}; globalThis.chat = { pageChatVisit, pageChatWelcome, pageChatSceneNote, pageChatLine, pageChatLaneIntro, pageChatStudios, pageChatShelf, pageChatLaneTalk, pageChatRef, pageChatShortTitle, PAGE_CHAT_LINES };`, context);
  return context.chat;
}

test("a visit starts after half an hour away and counts consecutive days", () => {
  const { pageChatVisit } = load();
  const now = new Date(2026, 10, 4, 20).getTime();
  const first = pageChatVisit(null, now);
  assert.equal(first.visit.fresh, true);
  assert.equal(first.visit.previous, null);
  assert.equal(pageChatVisit(first.record, now + 10 * 60000).visit.fresh, false);
  const days = [3, 2, 1].map((back) => new Date(now - back * DAY).toDateString());
  const later = pageChatVisit({ last: now - DAY, days }, now).visit;
  assert.equal(later.fresh, true);
  assert.equal(later.streak, 4);
  assert.equal(pageChatVisit({ last: now - 3 * DAY, days: [days[0]] }, now).visit.streak, 1);
});

test("a reload inside a visit keeps its greeting and the visit before it", () => {
  const { pageChatVisit } = load();
  const now = new Date(2026, 10, 4, 20).getTime();
  const opened = pageChatVisit({ last: now - 4 * DAY, days: [] }, now);
  const greeted = { ...opened.record, welcomed: opened.visit.start };
  const reloaded = pageChatVisit(greeted, now + 5 * 60000).visit;
  assert.equal(reloaded.fresh, false);
  assert.equal(reloaded.welcomed, true);
  assert.equal(reloaded.previous, now - 4 * DAY);
  assert.equal(pageChatVisit(opened.record, now + 5 * 60000).visit.welcomed, false);
  assert.deepEqual([...pageChatVisit({ ...greeted, lanes: ["best_bets"] }, now + 5 * 60000).visit.lanes], ["best_bets"]);
  assert.equal(pageChatVisit({ ...greeted, lanes: ["best_bets"] }, now + DAY).visit.lanes.length, 0);
});

test("the welcome follows up with what's true, new scenes weighted highest", () => {
  const { pageChatWelcome } = load();
  const now = new Date(2026, 10, 4, 20).getTime();
  const visit = { previous: now - 4 * DAY, streak: 5 };
  const first = () => 0;
  assert.equal(pageChatWelcome(visit, { count: 12 }, now, first)[0].key, "days");
  assert.equal(pageChatWelcome(visit, { count: 12 }, now, first)[1].key, "newScenes");
  assert.equal(pageChatWelcome(visit, { count: 12, regular: "Ann" }, now, first)[1].values.p, "Ann");
  assert.equal(pageChatWelcome(visit, { count: 0 }, now, first)[1].key, "streak");
  assert.equal(pageChatWelcome(visit, { count: 0 }, now, () => 0.99)[1].key, "evening");
  assert.equal(pageChatWelcome({ previous: null, streak: 1 }, {}, now, first)[0].key, "first");
  assert.equal(pageChatWelcome({ previous: now - 3600000, streak: 1 }, {}, now, first).length, 1);
});

test("a lane talks about what its shelf holds", () => {
  const { pageChatShelf, pageChatLaneTalk } = load();
  const now = Date.UTC(2026, 10, 4);
  const ann = { id: 1, name: "Ann" };
  const scenes = [
    { id: 1, title: "Opening", play_count: 0, performers: [ann], studio: { name: "North" }, files: [{ duration: 600 }] },
    { id: 2, title: "Second", play_count: 4, performers: [ann], studio: { name: "North" }, files: [{ duration: 540 }] },
    { id: 3, title: "Third", play_count: 0, performers: [ann], studio: { name: "North" }, files: [{ duration: 660 }] },
    { id: 4, title: "Fourth", play_count: 0, performers: [], studio: { name: "South" }, files: [{ duration: 700 }] },
  ];
  const facts = new Map(scenes.map((scene) => [String(scene.id), scene]));
  const items = scenes.map((scene) => ({ scene_id: scene.id }));
  const keys = (options) => Array.from(options, ([, spec]) => spec.key).sort();
  assert.deepEqual(keys(pageChatShelf("for_you", items, facts, {}, now)), ["mostPlayed", "performerRun", "quick", "studioRun", "topPick", "unplayed", "unplayedOne"]);
  // A card ranked low for its appeal is worth pointing at.
  const ranked = items.map((item, index) => ({ ...item, appeal: index === 3 ? 0.6 : 0.4 }));
  const gem = pageChatShelf("for_you", ranked, facts, {}, now, () => 0).find(([, spec]) => spec.key === "gem");
  assert.equal(gem[1].values.r, "the fourth one");
  const regulars = pageChatShelf("for_you", items, facts, { affinities: { 1: { value: 0.2, basis: "watched" } } }, now);
  assert.equal(regulars.find(([, spec]) => spec.key === "regulars")[1].values.n, 3);
  const first = pageChatLaneTalk("revisit", items, facts, {}, [], { first: true, random: () => 0 });
  assert.ok(["revisit", "revisitFact"].includes(first[0].key));
  assert.equal(first.length, 2);
  const redraw = pageChatLaneTalk("for_you", items, facts, {}, [], { redraw: true, random: () => 0 });
  assert.equal(redraw[0].key, "freshDraw");
  assert.notEqual(redraw[1].key, "topPick");
  const again = pageChatLaneTalk("for_you", items, facts, {}, ["topPick", "performerRun", "studioRun", "quick"], { random: () => 0 });
  assert.ok(["unplayed", "mostPlayed"].includes(again[0].key));
});

test("a card note says only what is true, the rarer kinds first", () => {
  const { pageChatSceneNote } = load();
  const now = Date.UTC(2026, 10, 4);
  const affinities = { 1: { value: 0.2, basis: "watched" }, 2: { value: 0.03, basis: "guessed" } };
  const plays = new Map([["1", { plays: 9 }]]);
  const scene = { play_count: 0, performers: [{ id: 1, name: "Ann" }] };
  assert.equal(pageChatSceneNote(scene, { affinities, plays, now }).key, "dependable");
  assert.equal(pageChatSceneNote({ ...scene, resume_time: 754 }, { affinities, plays, now }).values.t, "12:34");
  assert.equal(pageChatSceneNote({ play_count: 0, performers: [{ id: 2, name: "Bea" }] }, { affinities, plays, now }).key, "newFace");
  assert.equal(pageChatSceneNote({ play_count: 6, last_played_at: new Date(now - 10 * DAY).toISOString(), performers: [] }, { now }).key, "favourite");
  assert.equal(pageChatSceneNote({ play_count: 4, last_played_at: new Date(now - 200 * DAY).toISOString(), performers: [] }, { now }).key, "staleFavourite");
  assert.equal(pageChatSceneNote({ play_count: 1, created_at: new Date(now - DAY).toISOString(), performers: [] }, { now }), null);
  assert.equal(pageChatSceneNote({ play_count: 0, performers: [] }, { now }), null);
});

test("cards are named the way a person would point at them", () => {
  const { pageChatRef, pageChatShortTitle } = load();
  const scenes = [
    { title: "Big Buck Bunny: Morning", performers: [{ id: 1, name: "Ann Lee" }], studio: { name: "North" } },
    { title: "A Very Long Title That Nobody Would Ever Say Out Loud", performers: [{ id: 1, name: "Ann Lee" }, { id: 2, name: "Bea Fox" }], studio: { name: "North" } },
    { title: "Studio - Third", performers: [], studio: { name: "South" } },
  ];
  const ways = (index) => new Set(Array.from({ length: 4 }, (_, n) => pageChatRef(index, scenes, () => n / 4)));
  assert.deepEqual([...ways(0)].sort(), ["Morning", "the top one"]);
  assert.deepEqual([...ways(1)].sort(), ["the Bea one", "the second one"]);
  assert.deepEqual([...ways(2)].sort(), ["Third", "that South one", "the third one"]);
  assert.ok(!pageChatRef(1, scenes, () => 0.99, ["performer"]).includes("Bea"));
  assert.equal(pageChatShortTitle("One Two Three Four Five"), null);
});

test("a line that won't fit gives way to another from the deck, or to silence", () => {
  const { pageChatLine, PAGE_CHAT_LINES } = load();
  const longest = Math.max(...PAGE_CHAT_LINES.revisit.map((line) => line.length));
  const shortest = Math.min(...PAGE_CHAT_LINES.revisit.map((line) => line.length));
  const short = pageChatLine({ key: "revisit" }, (text) => text.length < longest);
  assert.ok(short.text.length < longest);
  assert.equal(pageChatLine({ key: "revisit" }, (text) => text.length < shortest), null);
  const fact = pageChatLine({ key: "revisitFact", values: { t: "A very long title that will not fit", ago: "x", when: "y" }, fallback: { key: "revisit" } }, (text) => text.length <= shortest);
  assert.equal(fact.key, "revisit");
  // In a tight space the fitting lines take turns.
  const seen = new Set(Array.from({ length: 6 }, () => pageChatLine({ key: "again" }, (text) => text.length < 40).text));
  assert.ok(seen.size > 1);
});

test("big studios hold at least a fifth of all plays", () => {
  const { pageChatStudios } = load();
  const studios = pageChatStudios([
    { play_count: 6, studio: { name: "North" } }, { play_count: 20, studio: { name: "South" } }, { play_count: 3, studio: { name: "East" } },
  ]);
  assert.deepEqual([...studios.big].sort(), ["North", "South"]);
});
