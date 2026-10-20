const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require("node:path").join(__dirname, "../../plugin/stash-curator.js"), "utf8");
{
  const saved = new Map(), states = [], cleanup = [], events = new EventTarget();
  let storageBlocked = false;
  const preferences = {
    window: events, Event,
    localStorage: {
      getItem: key => saved.get(key) ?? null,
      setItem(key, value) { if (storageBlocked) throw new Error("Storage unavailable"); saved.set(key, value); },
    },
    React: {
      useState(value) { const state = { value }; states.push(state); return [value, next => { state.value = next; }]; },
      useEffect(effect) { cleanup.push(effect()); },
    },
  };
  vm.createContext(preferences);
  vm.runInContext(source.slice(source.indexOf("  const ROULETTE_ANIMATION_KEY"), source.indexOf("  function useFindView")), preferences);
  const [enabled, change] = preferences.useRouletteAnimation();
  preferences.useRouletteAnimation();
  assert.equal(enabled, true);
  change(false);
  assert.ok(states.every(state => state.value === false));
  assert.equal(saved.get("stash-curator:roulette-animation:v1"), "false");
  events.dispatchEvent(Object.assign(new Event("storage"), { key: "unrelated", newValue: "true" }));
  assert.ok(states.every(state => state.value === false));
  events.dispatchEvent(Object.assign(new Event("storage"), { key: "stash-curator:roulette-animation:v1", newValue: "true" }));
  assert.ok(states.every(state => state.value === true));
  storageBlocked = true;
  change(false);
  assert.equal(preferences.useRouletteAnimation()[0], false); // Failed persistence still works for this session.
  cleanup.forEach(dispose => dispose());
}
const requests = [];
let batches = [], missing = new Set(), graphqlError = false, closeDuringLoad = false, active;
const context = {
  atob,
  location: { pathname: "/plugins/stash-curator" }, uuid: () => "session",
  rotationLane: () => ({ seed: "seed", atMs: 123 }), laneExclusions: new Map([["best_bets", new Set(["99"])]]),
  readMoodID: () => "mood", readTogetherMode: () => true,
  operation: async (request) => {
    requests.push(request);
    if (closeDuringLoad) active.closed = true;
    return batches.shift();
  },
  fetch: async (_, options) => {
    if (graphqlError) throw new Error("Network unavailable");
    const { variables } = JSON.parse(options.body);
    return { ok: true, json: async () => ({ data: Object.fromEntries(Object.entries(variables).map(([key, id]) => [key, missing.has(id) ? null : { id, title: "Scene", files: [{}] }])) }) };
  },
  React: { useCallback() {} },
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function playlistOrigins("), source.indexOf("  function startLanePlaylist(")), context);
vm.runInContext(source.slice(source.indexOf("  function createRouletteSession("), source.indexOf("  const rouletteTimestamp")), context);
const sources = [], buses = [];
const parameter = () => ({
  value: 0, events: [],
  setValueAtTime(value, time) { this.events.push({ value, time }); },
  linearRampToValueAtTime(value, time) { this.events.push({ value, time }); },
  setTargetAtTime(value, time) { this.events.push({ value, time }); },
  exponentialRampToValueAtTime(value, time) { assert.ok(value > 0); this.events.push({ value, time }); },
});
const node = () => ({ connect() {}, disconnect() { this.disconnected = true; } });
const sound = context.createRouletteSound({
  currentTime: 2, sampleRate: 8000, destination: {},
  createBuffer: (_, size, rate) => {
    const data = new Float32Array(size);
    return { duration: size / rate, getChannelData: () => data };
  },
  createGain: () => { const gain = { ...node(), gain: parameter() }; buses.push(gain); return gain; },
  createBiquadFilter: () => ({ ...node(), frequency: parameter(), Q: parameter() }),
  createBufferSource: () => makeSource(),
  createOscillator: () => makeSource(),
});
function makeSource() {
  const source = { ...node(), frequency: parameter(), playbackRate: parameter(), start(at) { this.started = at; }, stop(at) { this.stopped = at ?? "now"; } };
  sources.push(source); return source;
}
sound.gather(1.5);
assert.equal(sources.length, 3); // Shuffle and a quiet continuous swoosh start together.
assert.ok(sources[0].buffer.duration > 1.2);
assert.ok(sources[0].buffer.getChannelData(0).some(value => Math.abs(value) > .2));
assert.ok(sources[0].playbackRate.value >= .85 && sources[0].playbackRate.value <= 1.2);
assert.notEqual(sources[0].loop, true);
const spinFirst = 1, spinBus = 2, assembledSources = sources.length;
sound.spin(3.8); sound.tick();
assert.equal(sources.length, assembledSources + 2); // Spin carries on the same swoosh, without restarting.
assert.ok(sources.slice(spinFirst, spinFirst + 2).every(source => source.stopped === undefined));
sound.progress(.75);
const earlyPeak = buses[spinBus].gain.events.at(-1).value;
sound.progress(1);
assert.ok(buses[spinBus].gain.events.at(-1).value > earlyPeak);
assert.ok(sources[spinFirst].buffer.getChannelData(0).some(value => Math.abs(value) > .2));
assert.equal(sources[spinFirst].loop, true); // Recorded texture keeps rising until the actual landing.
const landingFirst = sources.length;
sound.land();
assert.ok(sources.slice(0, landingFirst).every(source => source.stopped === "now" && source.disconnected));
assert.equal(sources.length, landingFirst + 1); // Recorded clunk, heartbeat and glow share one cancellable buffer.
assert.equal(sources[landingFirst].buffer.duration, 4);
assert.equal(sources[landingFirst].playbackRate.value, 1);
assert.equal(sources[landingFirst].stopped, undefined); // Let the recording's full decay finish.
sound.mute(true);
assert.equal(buses[0].gain.events.at(-1).value, 0);
assert.ok(sources.every(source => source.stopped === "now"));
sound.mute(false);
sound.progress(1);
assert.equal(sources.length, landingFirst + 1); // Unmuting cannot restart a cancelled build-up.
sound.spin(0); assert.equal(sources.length, landingFirst + 1);
sound.reveal(); sound.stop(); sound.stop();
assert.equal(sources.at(-1).stopped, "now");
sources.forEach(source => source.onended());
const item = (id) => ({ scene_id: String(id), position: id });
const slate = (ids, impression = "first") => ({ lane: "best_bets", page_size: 2, model_id: "model", impression_id: impression, items: ids.map(item) });
const filters = { includeTags: [{ name: "A" }], excludeTags: [{ name: "B" }], performers: [{ id: 2 }], studios: [{ id: 3 }], gender: "FEMALE" };
const create = (ids) => context.createRouletteSession(slate(ids), slate(ids).items, filters, new Map(ids.map(id => [String(id), { id: String(id), files: [{}] }])));
const plain = (value) => JSON.parse(JSON.stringify(value));
(async () => {
  const shape = context.rouletteShape({
    getBoundingClientRect: () => ({ left: 30, top: 10 }),
    querySelectorAll: () => [{
      getBBox: () => ({ x: 10, y: 20, width: 160, height: 90 }),
      getScreenCTM: () => ({ a: 2, b: 0, c: 0, d: 2, e: 100, f: 50 }),
      getBoundingClientRect: () => ({ left: 50, top: 20, width: 400, height: 400 }),
    }],
  }, { history: [{ slot: 0 }], index: 0 });
  assert.equal(shape.left, "90px");
  assert.equal(shape.top, "80px");
  assert.equal(shape.width, "320px");
  assert.equal(shape.height, "180px");

  const session = create([1, 2]);
  assert.deepEqual(plain(session.request), {
    lane: "best_bets", page: 1, count: 2, exploration: 0, mood_id: "mood", together_mode: true,
    draw_seed: "seed", draw_at_ms: 123, exclude_scene_ids: ["99"],
    include_tags: ["A"], exclude_tags: ["B"], performer_ids: ["2"], studio_ids: ["3"], gender: "FEMALE",
  });
  batches = [slate([2, 3, 4], "second")]; missing.add("3");
  await context.fillRoulette(session, 3);
  assert.deepEqual(plain(session.pool.map(entry => entry.origin.scene_id)), ["1", "2", "4"]);
  assert.equal(session.pool[2].origin.impression_id, "second");
  assert.equal(session.pool[2].origin.impression_position, 4);
  assert.deepEqual(plain(requests[0].exclude_scene_ids), ["99", "1", "2"]);
  assert.equal(requests[0].page, 1);

  session.slots = context.rouletteSlots(session, 3);
  const original = [...session.slots];
  assert.equal(new Set(original).size, 3);
  session.history = [{ origin: original[0].origin }]; session.index = 0;
  session.seen.add(original[0].origin.scene_id);
  session.seen.add(original[1].origin.scene_id);
  batches = [slate([5, 6])];
  await context.fillRoulette(session, 3);
  const replacement = context.rouletteSlots(session, 3);
  assert.equal(session.slots[1], original[1]); // Planning a spin does not change a stationary wheel.
  assert.equal(replacement[0], original[0]); // Protect the current pick's slot.
  assert.notEqual(replacement[1], original[1]);
  assert.equal(replacement[2], original[2]);
  for (let i = 0; i < 100; i++) assert.ok(!session.seen.has(context.rouletteWinner(session, replacement).origin.scene_id));
  replacement.forEach(entry => session.seen.add(entry.origin.scene_id));
  assert.equal(context.rouletteWinner(session, replacement), undefined);

  const retry = create([1]);
  batches = [slate([7])]; graphqlError = true;
  await assert.rejects(context.fillRoulette(retry, 2), /Network unavailable/);
  assert.ok(!retry.excluded.has("7")); // A failed hydration can be retried without losing candidates.
  graphqlError = false; batches = [slate([7])];
  await context.fillRoulette(retry, 2);
  assert.equal(retry.pool.length, 2);
  batches = [slate([])];
  await context.fillRoulette(retry, 3);
  assert.ok(retry.done);
  const count = requests.length;
  await context.fillRoulette(retry, 3);
  assert.equal(requests.length, count);

  const continuous = create([1, 2, 3]);
  continuous.slots = [...continuous.pool];
  continuous.slots[0].frame = "saved-frame";
  continuous.history = [{ origin: continuous.slots[0].origin }]; continuous.index = 0;
  continuous.pool.forEach(entry => continuous.seen.add(entry.origin.scene_id));
  batches = [slate([]), slate([1, 4], "new-round"), slate([])];
  await context.fillRoulette(continuous, 3);
  const renewed = context.rouletteSlots(continuous, 3);
  assert.equal(continuous.seen.size, 0);
  assert.equal(renewed[0].origin.scene_id, "1");
  assert.equal(renewed[0].frame, "saved-frame");
  assert.equal(context.rouletteWinner(continuous, renewed).origin.scene_id, "4");
  assert.equal(context.rouletteWinner(continuous, renewed).origin.impression_id, "new-round");
  assert.ok(!continuous.pool.some(entry => entry.origin.scene_id === "2"));

  const single = create([1]);
  single.slots = [...single.pool];
  single.history = [{ origin: single.slots[0].origin }]; single.index = 0; single.seen.add("1");
  batches = [slate([]), slate([1], "single-round")];
  await context.fillRoulette(single, 1);
  assert.equal(context.rouletteWinner(single, context.rouletteSlots(single, 1)).origin.scene_id, "1");
  single.seen.add("1"); batches = [slate([]), slate([])];
  await context.fillRoulette(single, 2);
  assert.equal(context.rouletteWinner(single, context.rouletteSlots(single, 2)), undefined);
  assert.equal(single.pool.length, 0);
  single.done = false; batches = [slate([1, 5])];
  await context.fillRoulette(single, 2);
  assert.equal(context.rouletteSlots(single, 2).length, 2);
  assert.equal(context.rouletteWinner(single, context.rouletteSlots(single, 2)).origin.scene_id, "5");

  active = create([1]); closeDuringLoad = true; batches = [slate([8])];
  await context.fillRoulette(active, 2);
  assert.equal(active.pool.length, 1);
  assert.ok(!active.excluded.has("8"));
  console.log("Roulette scope, continuous rounds, provenance, stable slots, retry and cancellation passed");
})();
