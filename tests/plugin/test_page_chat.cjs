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
    rankingLikedTraits: (taste, performer) => taste.liked[performer.id] || [],
    RANKING_TRAIT_NAMES: { redhead: ["redheads", "gingers"] },
    operation: async () => globalThis.profile,
  });
  vm.runInContext(`${block}; globalThis.chat = { pageChatVisit, pageChatWelcome, pageChatSceneNote, pageChatLine, pageChatLaneIntro, pageChatStudios, pageChatShelf, pageChatTalk, pageChatRef, pageChatShortTitle, pageChatExpandShelf, pageChatHuntShelf, pageChatSimilarShelf, pageChatExternalNote, pageChatReaction, pageChatSceneQuery, pageChatSceneShelf, pageChatPerformerShelf, pageChatUsualTag, pageChatInsightsShelf, pageChatInsightsNote, pageChatDay, pageChatContentTags, PAGE_CHAT_LINES, PAGE_CHAT_MOODS };`, context);
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
  const { pageChatShelf, pageChatTalk, pageChatLaneIntro } = load();
  const pageChatLaneTalk = (lane, items, facts, context, recent, options) => pageChatTalk(
    pageChatShelf(lane, items, facts, context, Date.now(), options.random), () => pageChatLaneIntro(lane, items, facts, Date.now(), options.random), recent, options);
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

// A Stash-box scene as get_expand and get_performer_hunt serve it.
// Objects made inside the VM have another realm's prototype.
const plain = (value) => JSON.parse(JSON.stringify(value));

function external(id, { title = `Scene ${id}`, performers = [], studio = null, released = null, ...rest } = {}) {
  return { id: String(id), payload: { title, studio: studio && { name: studio }, release_date: released, performers: performers.map((performer) => ({ performer })) }, ...rest };
}

test("Expand talks about your regulars, studios and release dates in what you don't have", () => {
  const { pageChatExpandShelf } = load();
  const now = Date.UTC(2026, 10, 4);
  const day = (back) => new Date(now - back * DAY).toISOString().slice(0, 10);
  const ann = { id: "a", name: "Ann", curator_local: { id: 1 } };
  const bea = { id: "b", name: "Bea", curator_local: { id: 2, favorite: true } };
  const cat = { id: "c", name: "Cat", curator_local: { id: 3 } };
  const items = [
    external(1, { performers: [ann, bea], studio: "North", released: day(3) }),
    external(2, { performers: [ann, bea], studio: "North", released: day(400) }),
    external(3, { performers: [cat], studio: "South", released: day(4000), in_whisparr: true }),
    external(4, { performers: [], studio: "South", released: day(20), in_whisparr: true }),
  ];
  const context = {
    affinities: { 1: { value: 0.2, basis: "watched" }, 3: { value: 0.05, basis: "guessed" } },
    plays: new Map([["1", { plays: 12 }]]),
    studios: { big: new Set(["North"]) },
  };
  const shelf = new Map(pageChatExpandShelf(items, context, now, () => 0).map(([, spec]) => [spec.key, spec]));
  assert.deepEqual(plain(shelf.get("expandRegular").values), { p: "Ann", n: 2 });
  assert.equal(shelf.get("expandFavourite").values.p, "Bea");
  assert.equal(shelf.get("expandUnwatched").values.p, "Cat");
  assert.deepEqual(plain(shelf.get("expandStudio").values), { s: "North", n: 2 });
  assert.equal(shelf.get("expandNewRelease").scene, 0);
  assert.equal(shelf.get("expandDeepCut").values.y, 2015);
  assert.equal(shelf.get("whisparrRun").values.n, 2);
  // Without viewing evidence nobody is called a regular.
  assert.ok(!pageChatExpandShelf(items, {}, now).some(([, spec]) => spec.key === "expandRegular"));
});

test("a hunt counts what you own of the performer's catalogue", () => {
  const { pageChatHuntShelf } = load();
  const now = Date.UTC(2026, 10, 4);
  const day = (back) => new Date(now - back * DAY).toISOString().slice(0, 10);
  const ann = { id: "a", name: "Ann", curator_local: { id: 1 } };
  const items = [
    external(1, { performers: [ann], released: day(10), linked_locally: true }),
    external(2, { performers: [ann], released: day(100) }),
    external(3, { performers: [ann], released: day(2000) }),
  ];
  const data = { performer_id: "a", performer_name: "Ann", items };
  const keys = (options) => new Map(options.map(([, spec]) => [spec.key, spec]));
  const shelf = keys(pageChatHuntShelf(data, { affinities: { 1: { value: 0.2, basis: "watched" } } }, now, () => 0));
  assert.deepEqual(plain(shelf.get("huntOwned").values), { p: "Ann", n: 3, own: 1 });
  assert.ok(shelf.has("huntRegular"));
  assert.equal(shelf.get("huntRecent").values.n, 2);
  assert.equal(shelf.get("huntFirst").values.y, 2021);
  // On screen the hunt sorts and filters itself: no "the first one".
  assert.equal(shelf.get("expandNewRelease").values.r, "Scene 1");
  assert.ok(keys(pageChatHuntShelf({ ...data, items: items.map((item) => ({ ...item, linked_locally: true })) }, {}, now)).has("huntComplete"));
  assert.ok(keys(pageChatHuntShelf({ ...data, items: items.slice(1) }, {}, now)).has("huntNone"));
  assert.equal(pageChatHuntShelf({ items: [] }, {}, now).length, 0);
});

test("Similar talks about the seed and what its matches share with it", () => {
  const { pageChatSimilarShelf } = load();
  const now = Date.UTC(2026, 10, 4);
  const ann = { id: 1, name: "Ann" };
  const seed = { id: 9, play_count: 7, performers: [ann], studio: { name: "North" } };
  const scenes = [
    { id: 1, title: "One", play_count: 0, performers: [ann], studio: { name: "North" } },
    { id: 2, title: "Two", play_count: 0, performers: [ann], studio: { name: "North" } },
    { id: 3, title: "Three", play_count: 0, performers: [], studio: { name: "South" } },
  ];
  const facts = new Map(scenes.map((scene) => [String(scene.id), scene]));
  const items = scenes.map((scene, index) => ({ scene_id: scene.id, appeal: 0.2, similarity: index === 2 ? 0.9 : 0.6 }));
  const shelf = pageChatSimilarShelf(seed, items, facts, {}, now, () => 0);
  const byKey = new Map(shelf.map(([, spec]) => [spec.key, spec]));
  assert.equal(byKey.get("seedLoved").values.n, 7);
  assert.deepEqual(plain(byKey.get("sharedPerformer").values), { p: "Ann", n: 2 });
  assert.deepEqual(plain(byKey.get("sameStudio").values), { s: "North", n: 2 });
  assert.equal(byKey.get("closest").scene, 2);
  // The shelf's own run of Ann would repeat the shared-performer line.
  assert.ok(!byKey.has("performerRun"));
  assert.ok(pageChatSimilarShelf({ ...seed, play_count: 0 }, items, facts, {}, now).some(([, spec]) => spec.key === "seedUnplayed"));
});

test("a Stash-box card note prefers what's rare: owned, in Whisparr, just out", () => {
  const { pageChatExternalNote } = load();
  const now = Date.UTC(2026, 10, 4);
  const ann = { id: "a", name: "Ann", curator_local: { id: 1 } };
  const context = { affinities: { 1: { value: 0.2, basis: "watched" } } };
  assert.equal(pageChatExternalNote(external(1, { performers: [ann], linked_locally: true }), context, now).key, "ownedNote");
  assert.equal(pageChatExternalNote(external(1, { performers: [ann] }), context, now).values.p, "Ann");
  assert.equal(pageChatExternalNote(external(1, { released: "2012-05-01" }), {}, now).values.y, 2012);
  assert.equal(pageChatExternalNote(external(1), {}, now), null);
});

test("Curate answers I saw coming, or didn't, get a word back now and then", () => {
  const { pageChatReaction } = load();
  const tag = (value, inferred, blocked = false) => ({ kind: "tag", name: "Lace", value, inferred, blocked });
  assert.equal(pageChatReaction(tag(-0.5, 0.4), 1).key, "answerSurprise");
  assert.equal(pageChatReaction(tag(0.5, 0.4), 1, () => 0).key, "calledLike");
  assert.equal(pageChatReaction(tag(-0.5, -0.4), 1, () => 0).key, "calledDislike");
  assert.equal(pageChatReaction(tag(0.5, 0.4), 1, () => 0.9), null);
  assert.equal(pageChatReaction(tag(0.5, 0.02), 1, () => 0), null);
  assert.equal(pageChatReaction(tag(null, 0.4, true), 1).key, "answerBlocked");
  assert.deepEqual(plain(pageChatReaction(tag(0.5, 0.02), 10).values), { n: 10 });
  assert.equal(pageChatReaction({ kind: "reason", flipped: true, reasons: 1 }, 2).key, "reasonFlip");
  assert.equal(pageChatReaction({ kind: "reason", flipped: false, reasons: 4 }, 2, () => 0).key, "reasonRich");
});

test("every line a view can say has a deck and a face", () => {
  const { PAGE_CHAT_LINES, PAGE_CHAT_MOODS } = load();
  for (const key of Object.keys(PAGE_CHAT_LINES)) {
    assert.ok(PAGE_CHAT_LINES[key].length, key);
    if (key !== "off" && !["first", "again", "day", "days", "weeks", "streak", "newScenes", "newScene", "morning", "afternoon", "evening", "night"].includes(key)) assert.ok(PAGE_CHAT_MOODS[key], `${key} has no mood`);
  }
  for (const section of ["questions", "reasons", "sentiment", "progress"]) assert.ok(PAGE_CHAT_LINES[`curate_${section}`], section);
});

// A synthetic scene page: Ann (a regular) and Bea (never played) in a
// scene tagged Lace and Rain from North, as the inspector and Stash see it.
const NOW = Date.UTC(2026, 10, 4, 12);
const ago = (days) => new Date(NOW - days * DAY).toISOString();
const ann = { id: "1", name: "Ann" };
const bea = { id: "2", name: "Bea" };
const lace = { id: "10", name: "Lace" };
const rain = { id: "11", name: "Rain" };
function pageScene(overrides = {}) {
  return { id: "50", title: "Series: Opening", play_count: 0, resume_time: 0, last_played_at: null, created_at: ago(40), performers: [ann, bea], tags: [lace, rain], studio: { id: "7", name: "North" }, ...overrides };
}
function pageDetails({ fit = {}, score = {}, similar = [] } = {}) {
  return {
    model_id: "m1",
    score: {
      appeal: 0.6, general_appeal: 0.4, direct_appeal: 0, direct_confidence: 0, confidence: 0.6,
      neighbors: [{ scene_id: "60", similarity: 0.8, outcome: 0.5 }],
      components: {
        content: { top: [{ value: 0.2, metadata: { tag_name: "Lace" } }, { value: -0.1, metadata: { tag_name: "Rain" } }] },
        performer_identity: { performers: [{ performer_id: "1", value: 0.3 }, { performer_id: "2", value: 0 }] },
        performer_similarity: { performers: similar },
        studio: { studios: [{ studio_id: "7", value: 0.1 }] },
        fit: { cooldown: 0, satiation: 0, not_now: 0, ...fit },
      },
      ...score,
    },
  };
}
const played = (id, people, tags, plays = 1, last = 90) => ({ id, play_count: plays, last_played_at: ago(last), performers: people.map((each) => ({ id: each.id })), tags: tags.map((each) => ({ id: each.id })) });

test("the scene page pairs two reasons: a regular in a tag you watch", () => {
  const { pageChatSceneShelf, pageChatSceneQuery } = load();
  const scene = pageScene();
  const details = pageDetails();
  const { query, variables } = pageChatSceneQuery(scene, details, NOW);
  // Only the liked tag is counted; disliked Rain isn't asked about.
  assert.match(query, /tag0: findScenes/);
  assert.doesNotMatch(query, /tag1/);
  assert.deepEqual(plain(variables.people), ["1", "2"]);
  assert.deepEqual(plain(variables.near), [60]);
  const data = {
    total: { count: 20 },
    // This very scene's own play must not count as evidence for itself.
    mine: { scenes: [played("50", [ann], [lace], 9), played("51", [ann], [lace], 2), played("52", [ann], [lace]), played("53", [ann], [])] },
    tag0: { count: 6 },
    studio: { scenes: [{ id: "51", play_count: 4 }, { id: "52", play_count: 3 }] },
    near: { scenes: [{ id: "60", title: "Series: Closing", play_count: 4, last_played_at: ago(30) }] },
    recent: { scenes: [] },
  };
  const shelf = new Map(pageChatSceneShelf(scene, details, data, NOW).map(([, spec]) => [spec.key, spec]));
  assert.deepEqual(plain(shelf.get("scenePairing").values), { p: "Ann", t: "Lace", n: 2 });
  assert.deepEqual(plain(shelf.get("scenePairing").links), { p: "/performers/1", t: "/tags/10" });
  assert.deepEqual(plain(shelf.get("sceneTagNeighbor").links), { t: "/tags/10", r: "/scenes/60" });
  assert.deepEqual(plain(shelf.get("scenePerformerStudio").values), { p: "Ann", pf: "Ann", n: 3, s: "North", m: 7 });
  assert.deepEqual(plain(shelf.get("sceneTagNeighbor").values), { t: "Lace", r: "Closing", n: 4 });
  // A single reason only speaks when nothing pairs up.
  assert.ok(!shelf.has("scenePerformer") && !shelf.has("sceneTag"));
  const untagged = { scenes: data.mine.scenes.map((each) => ({ ...each, tags: [] })) };
  const alone = new Map(pageChatSceneShelf(scene, details, { ...data, mine: untagged, tag0: { count: 1 }, studio: { scenes: [] }, near: { scenes: [] } }, NOW).map(([, spec]) => [spec.key, spec]));
  assert.deepEqual(plain(alone.get("scenePerformer").values), { p: "Ann", n: 3, m: 4 });
});

test("the scene page says when recent viewing is behind a rest or a run", () => {
  const { pageChatSceneShelf } = load();
  const scene = pageScene();
  const week = [played("51", [ann], [lace], 1, 1), played("52", [ann], [lace], 1, 3), played("54", [], [lace], 1, 10)];
  const data = { total: { count: 20 }, mine: { scenes: week }, recent: { scenes: week }, tag0: { count: 6 } };
  const tired = new Map(pageChatSceneShelf(scene, pageDetails({ fit: { satiation: -0.04 } }), data, NOW).map(([, spec]) => [spec.key, spec]));
  assert.deepEqual(plain(tired.get("sceneSatiated").values), { p: "Ann", n: 2 });
  // The rest explains the dip; a cheerful "streak" line would contradict it.
  assert.ok(!tired.has("scenePerformerRun"));
  const fresh = new Map(pageChatSceneShelf(scene, pageDetails(), data, NOW).map(([, spec]) => [spec.key, spec]));
  assert.deepEqual(plain(fresh.get("sceneTagRun").values), { t: "Lace", n: 3, p: "Ann" });
  assert.deepEqual(plain(fresh.get("scenePerformerRun").values), { p: "Ann", n: 2 });
});

test("the scene page names a new face's lookalike, or admits it has nothing", () => {
  const { pageChatSceneShelf } = load();
  const similar = [{ performer_id: "2", matches: [{ performer_id: "3", similarity: 0.9, affinity: 0.4 }] }];
  const cy = { id: "3" };
  const data = {
    total: { count: 20 },
    mine: { scenes: [played("61", [cy], []), played("62", [cy], []), played("63", [cy], [])] },
    matches: { performers: [{ id: "3", name: "Cy" }] },
  };
  const scene = pageScene({ performers: [bea] });
  const face = new Map(pageChatSceneShelf(scene, pageDetails({ similar }), data, NOW).map(([, spec]) => [spec.key, spec]));
  assert.deepEqual(plain(face.get("sceneNewFace").values), { p: "Bea", q: "Cy", n: 3, qf: "Cy" });
  const blank = new Map(pageChatSceneShelf(pageScene({ performers: [ann, bea] }), pageDetails({ score: { confidence: 0.1 } }), { total: { count: 20 } }, NOW).map(([, spec]) => [spec.key, spec]));
  assert.deepEqual(plain(blank.get("sceneRadar").values), { k: 2, s: "North" });
  const resting = pageChatSceneShelf(pageScene({ play_count: 2, resume_time: 754, last_played_at: ago(2) }), pageDetails({ fit: { cooldown: -0.2 } }), {}, NOW);
  const keys = new Map(resting.map(([, spec]) => [spec.key, spec]));
  assert.equal(keys.get("sceneResume").values.t, "12:34");
  assert.equal(keys.get("sceneCooldown").values.when, `on ${new Date(NOW - 2 * DAY).toLocaleString("en", { weekday: "long" })}`);
});

test("a performer's usual tag is what sets your picks apart, not what they always are", () => {
  const { pageChatPerformerShelf, pageChatUsualTag } = load();
  const scene = (id, plays, tags, last = 100) => ({ id, play_count: plays, last_played_at: plays ? ago(last) : null, created_at: ago(200), tags });
  // Rain is on every scene they make: it describes them, not your choice.
  const all = [scene("1", 2, [lace, rain]), scene("2", 1, [lace, rain]), scene("3", 3, [lace, rain]), scene("4", 0, [rain]), scene("5", 0, [rain])];
  const content = new Set(["10", "11", "12"]);
  const usual = pageChatUsualTag(all.filter((each) => each.play_count), all, content);
  assert.equal(usual.tag.name, "Lace");
  assert.equal(usual.others, 0);
  const everywhere = all.map((each) => ({ ...each, tags: [lace, rain] }));
  assert.equal(pageChatUsualTag(everywhere.filter((each) => each.play_count), everywhere, content), null);
  // A tag Curator files as a performer attribute never counts, even when
  // tagged unevenly enough to look like a choice; without roles, nothing does.
  assert.equal(pageChatUsualTag(all.filter((each) => each.play_count), all, new Set(["11"])), null);
  assert.equal(pageChatUsualTag(all.filter((each) => each.play_count), all, null), null);
  // Without at least two unplayed scenes there's nothing to contrast with.
  const seen = all.slice(0, 4);
  assert.equal(pageChatUsualTag(seen.filter((each) => each.play_count), seen, content), null);
  const shelf = new Map(pageChatPerformerShelf({ id: "1", name: "Ann", favorite: true }, {}, { theirs: { scenes: all } }, { content, now: NOW }).map(([, spec]) => [spec.key, spec]));
  assert.deepEqual(plain(shelf.get("performerUsual").values), { p: "Ann", pf: "Ann", all: 5, n: 3, m: 6, u: 2, waiting: "2 Ann scenes are", t: "Lace", a: "all", b: "none" });
  assert.equal(shelf.get("performerIdleFavourite").values.waiting, "2 Ann scenes are");
  const busy = [scene("1", 1, [], 1), scene("2", 1, [], 2)];
  const streak = new Map(pageChatPerformerShelf({ id: "1", name: "Ann" }, {}, { theirs: { scenes: busy } }, { now: NOW }).map(([, spec]) => [spec.key, spec]));
  assert.equal(streak.get("performerStreak").values.n, 2);
  const taste = { liked: { 1: ["redhead"] }, byId: new Map([["1", { gender: "FEMALE" }]]), lean: new Map([["FEMALE", { lifts: new Map([["redhead", 2.04]]) }]]) };
  const trait = pageChatPerformerShelf({ id: "1", name: "Ann" }, {}, { theirs: { scenes: busy } }, { taste, now: NOW }).find(([, spec]) => spec.key === "performerTrait")[1];
  assert.deepEqual(plain(trait.values), { p: "Ann", pf: "Ann", all: 2, n: 2, m: 2, u: 0, waiting: "0 Ann scenes are", trait: "redheads", x: "2.0" });
  const fresh = { theirs: { scenes: [scene("1", 0, [])] }, similar: { count: 4 } };
  const evidence = { evidence: { performers: [{ performer_id: "9", name: "Cy", affinity: 0.3 }] } };
  const similar = new Map(pageChatPerformerShelf({ id: "2", name: "Bea" }, evidence, fresh, { now: NOW }).map(([, spec]) => [spec.key, spec]));
  assert.deepEqual(plain(similar.get("performerSimilar").values), { p: "Bea", pf: "Bea", all: 1, n: 4, m: 0, u: 1, waiting: "1 Bea scene is", q: "Cy", qf: "Cy" });
  assert.ok(!similar.has("performerBlank"));
});

test("Insights talks about the taste summary and a row's peak", () => {
  const { pageChatInsightsShelf, pageChatInsightsNote } = load();
  const summary = {
    totals: { plays: 300, scenes_played: 200, library_scenes: 800 },
    windows: [{ end_ms: Date.UTC(2026, 2, 31) }, { end_ms: Date.UTC(2026, 5, 30) }, { end_ms: Date.UTC(2026, 8, 30) }],
    likes: [{ tag_id: "10", name: "Lace", watched_scenes: 60, answer: null, trend: [0.2, 0.4, 0.3] }, { tag_id: "11", name: "Rain", watched_scenes: 30, answer: 1, trend: [null, 0.1, 0.2] }],
    shift: { rising: [{ name: "Rain", before: 0.12, recent: 0.31 }], fading: [] },
    apart: { more: [{ tag_id: "11", name: "Rain", library_share: 0.04, watched_share: 0.18 }], passed: [] },
    dormant: [{ entity_type: "tag", name: "Fog" }, { entity_type: "performer", name: "Ann", play_count: 23, last_played_at_ms: Date.UTC(2026, 2, 10) }],
    rediscovered: [{ scene_id: "5", longest_gap_ms: 425 * DAY }],
    reasons: { hits: [{ name: "Lace", answers: 6 }] },
  };
  const scenes = new Map([["5", { title: "Series: Return" }]]);
  const shelf = new Map(pageChatInsightsShelf(summary, scenes, NOW).map(([, spec]) => [spec.key, spec]));
  assert.deepEqual(plain(shelf.get("insightTop").values), { t: "Lace", pct: "30%", n: "200" });
  assert.deepEqual(plain(shelf.get("insightRising").values), { t: "Rain", a: "12%", b: "31%" });
  assert.deepEqual(plain(shelf.get("insightAgrees").values), { t: "Rain", pct: "15%" });
  assert.equal(shelf.get("insightDormant").values.p, "Ann");
  assert.deepEqual(plain(shelf.get("insightRediscovered").values), { r: "Return", m: 14 });
  assert.equal(shelf.get("insightCoverage").values.pct, "25%");
  assert.equal(pageChatInsightsNote(summary, "like:10").key, "insightPeak");
  assert.equal(pageChatInsightsNote(summary, "like:10").values.pct, "40%");
  assert.equal(pageChatInsightsNote(summary, "like:11").key, "insightPeakNow");
  assert.equal(pageChatInsightsNote(summary, "more:11").values.b, "18%");
  assert.equal(pageChatInsightsShelf({ totals: { scenes_played: 0 } }).length, 0);
});

test("every scene, performer and Insights line fills completely", () => {
  const { PAGE_CHAT_LINES, pageChatLine } = load();
  const values = { newest: "the newest", one: "one", p: "Ann", pf: "Ann", q: "Cy", qf: "Cy", kn: "3 of the 4", o: "only 1 of the other 6", more: "2 more are", waiting: "2 Ann scenes are", t: "Lace", s: "North", r: "Closing", x: "Lace", n: 3, m: 7, k: 2, u: 2, d: 4, all: 9, a: "4%", b: "18%", pct: "30%", when: "on Sunday", since: "March", ago: "3 days ago", trait: "redheads" };
  const keys = Object.keys(PAGE_CHAT_LINES).filter((key) => /^(scene[A-Z]|performer[A-Z]|insight)/.test(key));
  assert.ok(keys.length > 30);
  for (const key of keys) {
    for (let i = 0; i < PAGE_CHAT_LINES[key].length; i++) {
      const line = pageChatLine({ key, values }, () => true);
      assert.ok(line && !line.text.includes("{"), `${key}: ${line?.text}`);
      // The scene page never claims a taste of its own.
      assert.doesNotMatch(line.text, /\bI'd (pick|choose|go for)\b/, key);
      assert.doesNotMatch(line.text, /since (on|in) /, key);
    }
  }
});

test("names in a line link to their Stash page", () => {
  const { pageChatLine, pageChatPerformerShelf } = load();
  const line = pageChatLine({ key: "scenePairing", values: { p: "Ann", t: "Lace", n: 2 }, links: { p: "/performers/1", t: "/tags/10" } }, () => true);
  const ranges = plain(line.links);
  assert.deepEqual(ranges.map((range) => line.text.slice(range.start, range.end)), ["Ann", "Lace"]);
  assert.deepEqual(ranges.map((range) => range.to), ["/performers/1", "/tags/10"]);
  // A line without links has no ranges, and unlinked values stay plain.
  assert.deepEqual(plain(pageChatLine({ key: "sceneResume", values: { t: "1:00" } }, () => true).links), []);
  const scene = (id, plays, created) => ({ id, play_count: plays, last_played_at: plays ? ago(1) : null, created_at: ago(created), tags: [] });
  const waiting = pageChatPerformerShelf({ id: "1", name: "Ann" }, {}, { theirs: { scenes: [scene("1", 1, 90), scene("2", 1, 90), scene("3", 0, 20), scene("4", 0, 5)] } }, { now: NOW })
    .find(([, spec]) => spec.key === "performerWaiting")[1];
  assert.equal(waiting.links.newest, "/scenes/4");
  assert.equal(waiting.links.p, undefined, "a performer's own page doesn't link to itself");
});

test("the usual-tag line only counts tags about the scene, not its cast", async () => {
  const chat = load();
  globalThis.profile = { items: [
    { tag_id: "10", role: "content", describes_performer: false },
    { tag_id: "11", role: "content", describes_performer: true },
    { tag_id: "12", role: "performer_attribute", describes_performer: true },
  ] };
  assert.deepEqual([...await chat.pageChatContentTags()], ["10"]);
});

test("a performer page finds what you pick them in: a co-star, a studio, a go-to scene", () => {
  const { pageChatPerformerShelf } = load();
  const cy = { id: "3", name: "Cy Moss" };
  const dee = { id: "4", name: "Dee Lane" };
  const north = { id: "7", name: "North" };
  const south = { id: "8", name: "South" };
  const scene = (id, plays, partner, studio, title = `Series: Part ${id}`) => ({
    id, title, play_count: plays, last_played_at: plays ? ago(20 + Number(id)) : null, created_at: ago(300),
    tags: [], performers: [ann, partner], studio,
  });
  const all = [
    scene("1", 5, cy, north), scene("2", 1, cy, north), scene("3", 1, cy, north), scene("4", 1, dee, south),
    ...Array.from({ length: 12 }, (_, index) => scene(String(10 + index), 0, dee, south)),
  ];
  const shelf = new Map(pageChatPerformerShelf(ann, {}, { theirs: { scenes: all } }, { now: NOW }).map(([weight, spec]) => [spec.key, { weight, spec }]));
  assert.deepEqual(plain(shelf.get("performerCoStar").spec.values).q, "Cy Moss");
  assert.equal(shelf.get("performerCoStar").spec.values.a, "75%");
  assert.equal(shelf.get("performerCoStar").spec.values.b, "none");
  assert.equal(shelf.get("performerCoStar").spec.links.q, "/performers/3");
  assert.equal(shelf.get("performerStudio").spec.values.s, "North");
  assert.deepEqual(plain(shelf.get("performerGoTo").spec.values).r, "Part 1");
  assert.equal(shelf.get("performerGoTo").spec.links.r, "/scenes/1");
  assert.equal(shelf.get("performerLast").spec.values.r, "Part 1");
  assert.equal(shelf.get("performerBacklog").spec.values.u, 12);
  // The plain count is the fallback, outweighed by anything specific.
  assert.ok(shelf.get("performerRegular").weight < Math.min(...[...shelf.values()].filter((entry) => entry.spec.key !== "performerRegular").map((entry) => entry.weight)));
});

test("a scene that scores low gets hesitation, not a confident hunch", () => {
  const { pageChatSceneShelf } = load();
  const scene = pageScene();
  const data = {
    total: { count: 20 },
    mine: { scenes: [played("51", [ann], [lace], 4), played("52", [ann], [lace], 2), played("53", [ann], [])] },
    tag0: { count: 6 },
  };
  const keys = (appeal) => new Map(pageChatSceneShelf(scene, pageDetails({ score: { appeal } }), data, NOW).map(([, spec]) => [spec.key, spec]));
  assert.ok(keys(0.6).has("scenePairing"));
  // Middling: the same reasons, measured.
  const mild = keys(0.3);
  assert.ok(mild.has("scenePairingMild") && !mild.has("scenePairing"));
  // Low: Ann is a plus, but Rain (a tag the model holds against it) drags.
  const low = keys(0.05);
  assert.ok(![...low.keys()].some((key) => /^scene(Pairing|Performer|Tag|Studio|Neighbor)/.test(key)), [...low.keys()].join());
  assert.deepEqual(plain(low.get("sceneMixedPerformer").values), { p: "Ann", m: 7, t: "Rain" });
  assert.equal(low.get("sceneMixedPerformer").links.t, "/tags/11");
});

test("counts of times read naturally", () => {
  const { pageChatLine } = load();
  assert.match(pageChatLine({ key: "sceneNeighbor", values: { r: "Closing", n: 2 } }, (text) => text.includes("times") || text.includes("twice")).text, /twice/);
  assert.doesNotMatch(pageChatLine({ key: "sceneNeighbor", values: { r: "Closing", n: 2 } }, () => true).text, /\b2 times\b/);
});
