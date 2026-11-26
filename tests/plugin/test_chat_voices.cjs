const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const TABLES = { page: "PAGE_CHAT_LINES", joined: "PAGE_CHAT_JOINED", clauses: "PAGE_CHAT_CLAUSES", lines: "RANKING_LINES", kickers: "RANKING_KICKERS", wrap: "RANKING_WRAP", facts: "RANKING_FACTS" };

function literal(name) {
  const start = source.indexOf(`  const ${name} = {`);
  assert.ok(start >= 0, `${name} is defined`);
  const end = source.indexOf("\n  };\n", start);
  // Through JSON, so tables from the sandbox compare as plain values here.
  return JSON.parse(JSON.stringify(vm.runInNewContext(`(${source.slice(source.indexOf("{", start), end + 4)})`)));
}
const classic = Object.fromEntries(Object.entries(TABLES).map(([part, name]) => [part, literal(name)]));
const voices = literal("CHAT_VOICES");
const holes = (line) => line.match(/\{[A-Za-z0-9]+\}/g) || [];
// What the code fills for a key: every placeholder its Classic lines use.
const filled = (part, key) => new Set(classic[part][key].flatMap(holes));
// A voice's own tables and its rare ones, as [where, key, lines].
const everyTable = (voice) => [
  ...Object.entries(voice).filter(([part]) => part !== "rare").map(([part, table]) => [part, part, table]),
  ...Object.entries(voice.rare || {}).map(([part, table]) => [`rare.${part}`, part, table]),
];

test("every voice is offered in settings and the manifest", () => {
  const manifest = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.yml"), "utf8");
  for (const name of Object.keys(voices)) {
    assert.ok(source.includes(`{ value: "${name}", label:`), `${name} is a settings option`);
    assert.ok(manifest.includes(` ${name}`), `${name} is named in the manifest`);
  }
});

test("each voice covers every chat line, with variety, and only fills what the code supplies", () => {
  for (const [name, voice] of Object.entries(voices)) {
    if (name === "classic") continue;
    for (const [part, table] of Object.entries(classic)) {
      assert.ok(voice[part], `${name} has ${part}`);
      for (const [key, lines] of Object.entries(table)) {
        const own = voice[part][key];
        assert.ok(Array.isArray(own), `${name}.${part}.${key} is written`);
        assert.ok(own.length >= Math.min(2, lines.length), `${name}.${part}.${key} has variety`);
        assert.equal(new Set(own).size, own.length, `${name}.${part}.${key} has no repeats`);
        for (const line of own) {
          assert.ok(line.trim(), `${name}.${part}.${key} has no blank line`);
          for (const hole of holes(line)) assert.ok(filled(part, key).has(hole), `${name}.${part}.${key} fills ${hole}: ${line}`);
          if (part === "joined") assert.ok(line.includes("{c}"), `${name}.joined.${key} leaves room for its reason: ${line}`);
          if (part === "clauses") assert.ok(!/[.!?]$/.test(line), `${name}.clauses.${key} is a clause: ${line}`);
        }
      }
    }
    for (const [where, part, table] of everyTable(voice)) {
      assert.ok(classic[part], `${name}.${where} is a chat table`);
      for (const [key, own] of Object.entries(table)) {
        assert.ok(classic[part][key], `${name}.${where}.${key} is a key the code uses`);
        if (!where.startsWith("rare.")) continue;
        // A rare line stands in for a usual one, so it fills the same slots.
        for (const line of own) for (const hole of holes(line)) assert.ok(filled(part, key).has(hole), `${name}.${where}.${key} fills ${hole}: ${line}`);
        assert.ok(!own.some((line) => voice[part][key].includes(line)), `${name}.${where}.${key} isn't a usual line`);
      }
    }
    assert.ok(Object.keys(voice.rare || {}).length, `${name} has rare lines`);
  }
});

test("no voice remarks on the hour, fakes a friendship or takes credit", () => {
  const rude = /\b(tonight|midnight|late one|late-night|up late|early start|bedtime|sleep|coffee|missed you|I love|awkward|take some credit|called it|knew it|homework|pushed down|buried|deserves better|sits low|order fool|than it should)\b/i;
  // Saying good morning is fine, where the code picks the line by the hour.
  const hours = /\b(morning|afternoon|evening|night)\b/i;
  const timed = new Set(["page.morning", "page.afternoon", "page.evening", "page.morningDays", "page.afternoonDays", "page.eveningDays", "kickers.morning", "kickers.afternoon", "kickers.evening"]);
  for (const [name, voice] of Object.entries(voices)) {
    if (name === "classic") continue;
    for (const [part, , table] of everyTable(voice)) {
      for (const [key, lines] of Object.entries(table)) {
        for (const line of lines) {
          assert.doesNotMatch(line, rude, `${name}.${part}.${key}: ${line}`);
          if (!timed.has(`${part}.${key}`)) assert.doesNotMatch(line, hours, `${name}.${part}.${key}: ${line}`);
        }
        if (timed.has(`${part}.${key}`)) {
          const hour = key.replace("Days", "");
          for (const line of lines) assert.match(line, new RegExp(`\\b${hour}\\b`, "i"), `${name}.${part}.${key} names its hour: ${line}`);
        }
      }
    }
  }
});

test("a card further down is another good one, never better than the top", () => {
  // Curator made the order: calling a lower card its best contradicts it.
  const ranks = /\b(surest|strongest|best|favourite|finest|top|higher|above|lower than|should be)\b/i;
  for (const [name, voice] of Object.entries(voices)) {
    const tables = name === "classic" ? classic : voice;
    for (const part of ["page", "joined"]) for (const line of tables[part].gem) assert.doesNotMatch(line, ranks, `${name}.${part}.gem: ${line}`);
  }
});

test("switching voices rewrites the tables and Classic restores them", () => {
  const start = source.indexOf("  // Curator's voices: the same chat");
  const end = source.indexOf("  function loadPerformerAffinities() {");
  const store = new Map();
  const context = vm.createContext({
    localStorage: { getItem: (key) => store.get(key) ?? null, setItem: (key, value) => store.set(key, value) },
    ...Object.fromEntries(Object.entries(TABLES).map(([part, name]) => [name, structuredClone(classic[part])])),
  });
  const boot = source.slice(source.indexOf("  try { applyChatVoice(localStorage"), source.indexOf("  getPluginSettings().then(ensureHomeDefaults)"));
  context.CHAT_RARE = new Map();
  vm.runInContext(`${source.slice(start, end)}${boot}; globalThis.voice = { applyChatVoice, CHAT_VOICE_DEFAULT };`, context);
  const { applyChatVoice, CHAT_VOICE_DEFAULT } = context.voice;
  const lines = () => JSON.parse(vm.runInContext("JSON.stringify(PAGE_CHAT_LINES)", context));
  assert.deepEqual(lines().topPick, voices[CHAT_VOICE_DEFAULT].page.topPick, "the default voice applies on load");
  assert.equal(applyChatVoice("clerk"), "clerk");
  assert.deepEqual(lines().topPick, voices.clerk.page.topPick);
  assert.equal(store.get("stash-curator:chat-voice:v1"), "clerk", "the choice is remembered in this browser");
  assert.equal(applyChatVoice("classic"), "classic");
  assert.deepEqual(lines().topPick, classic.page.topPick);
  assert.equal(applyChatVoice("nonsense"), CHAT_VOICE_DEFAULT, "an unknown voice falls back to the default");
});

test("a rare line now and then, from its own deck, and only for the voice that has it", () => {
  const start = source.indexOf("  const RANKING_DECKS_KEY");
  const end = source.indexOf("  function rankingLine(");
  const store = new Map();
  const context = vm.createContext({ localStorage: { getItem: (key) => store.get(key) ?? null, setItem: (key, value) => store.set(key, value) } });
  vm.runInContext(`${source.slice(start, end)}; globalThis.pick = { rankingPick, CHAT_RARE, CHAT_RARE_ODDS };`, context);
  const { rankingPick, CHAT_RARE, CHAT_RARE_ODDS } = context.pick;
  const table = { day: ["Welcome back."] };
  let roll = 0.5;
  vm.runInContext("Math.random = () => globalThis.roll()", Object.assign(context, { roll: () => roll }));
  assert.equal(rankingPick(table, "day", "page:day"), "Welcome back.", "no rare lines, no surprise");
  CHAT_RARE.set(table, { day: ["Ah, there you are.", "Pull up a chair."] });
  assert.equal(rankingPick(table, "day", "page:day"), "Welcome back.", "the usual line, most of the time");
  roll = 0.5 / CHAT_RARE_ODDS;
  const rare = [rankingPick(table, "day", "page:day"), rankingPick(table, "day", "page:day")];
  assert.deepEqual([...rare].sort(), ["Ah, there you are.", "Pull up a chair."], "rare lines come from a deck, so both show before either repeats");
  CHAT_RARE.clear();
  assert.equal(rankingPick(table, "day", "page:day"), "Welcome back.");
});
