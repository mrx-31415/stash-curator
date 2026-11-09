"use strict";

const assert = require("node:assert/strict");
const { createIncognito, STORAGE_KEY } = require("../../incognito/incognito.js");

// Mirrors the enable/stop/send contract of Stash's ScenePlayer/track-activity.ts.
class TrackActivity {
  constructor(player) {
    this.player = player;
    this.enabled = false;
    this.intervalID = undefined;
    this.sent = 0;
  }
  start() {
    if (this.enabled && !this.intervalID) this.intervalID = 1;
  }
  stop() {
    if (this.intervalID) {
      this.intervalID = undefined;
      this.sendActivity();
    }
  }
  sendActivity() {
    if (!this.enabled) return;
    this.sent += 1;
  }
  setEnabled(enabled) {
    this.enabled = enabled;
    if (!enabled) this.stop();
    else if (!this.player.paused) this.start();
  }
}

function makePlayer(paused = false) {
  const player = { paused, isDisposed: () => false, usingPlugin: (name) => name === "trackActivity" };
  const tracker = new TrackActivity(player);
  player.trackActivity = () => tracker;
  return { player, tracker };
}

function memoryStorage(initial = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (key) => (key in data ? data[key] : null),
    setItem: (key, value) => { data[key] = String(value); },
    removeItem: (key) => { delete data[key]; },
  };
}

function freshClass() {
  // Each scenario gets its own prototype so wrapping does not leak between them.
  return class extends TrackActivity {};
}

// Found before Stash enables tracking: the ScenePlayer's setEnabled(true) is held off.
{
  const players = [];
  const incognito = createIncognito({ storage: memoryStorage(), findPlayers: () => players });
  const { player, tracker } = makePlayer();
  Object.setPrototypeOf(tracker, freshClass().prototype);
  players.push(player);
  incognito.set(true);
  tracker.setEnabled(true);
  assert.equal(tracker.enabled, false);
  tracker.stop();
  assert.equal(tracker.sent, 0);
  incognito.set(false);
  assert.equal(tracker.enabled, true, "Stash's own setting returns when incognito ends");
  assert.ok(tracker.intervalID, "a playing scene resumes tracking");
}

// Turned on mid-play: the pending chunk is dropped, not sent.
{
  const players = [];
  const incognito = createIncognito({ storage: memoryStorage(), findPlayers: () => players });
  const { player, tracker } = makePlayer();
  Object.setPrototypeOf(tracker, freshClass().prototype);
  tracker.setEnabled(true);
  assert.ok(tracker.intervalID);
  players.push(player);
  incognito.scan();
  incognito.set(true);
  assert.equal(tracker.enabled, false);
  assert.equal(tracker.sent, 0);
}

// Stash's "Track activity" off stays off after incognito ends.
{
  const players = [];
  const incognito = createIncognito({ storage: memoryStorage(), findPlayers: () => players });
  const { player, tracker } = makePlayer();
  Object.setPrototypeOf(tracker, freshClass().prototype);
  players.push(player);
  incognito.scan();
  tracker.setEnabled(false);
  incognito.set(true);
  incognito.set(false);
  assert.equal(tracker.enabled, false);
}

// A player created after the first one is gated from its first setEnabled, and
// persisted state survives a reload.
{
  const Track = freshClass();
  const storage = memoryStorage({ [STORAGE_KEY]: "1" });
  const players = [];
  const incognito = createIncognito({ storage, findPlayers: () => players });
  assert.equal(incognito.isActive(), true);
  const first = makePlayer();
  Object.setPrototypeOf(first.tracker, Track.prototype);
  players.push(first.player);
  incognito.scan();
  first.player.trackActivity = () => null;
  const second = makePlayer();
  Object.setPrototypeOf(second.tracker, Track.prototype);
  second.tracker.setEnabled(true);
  assert.equal(second.tracker.enabled, false);
  incognito.set(false);
  assert.equal(second.tracker.enabled, true);
  assert.equal(storage.data[STORAGE_KEY], undefined);
}

// Players not yet using the plugin are not initialised by the scan.
{
  let calls = 0;
  const player = { isDisposed: () => false, usingPlugin: () => false, trackActivity: () => { calls += 1; } };
  const incognito = createIncognito({ storage: null, findPlayers: () => [player] });
  assert.equal(incognito.scan(), false);
  assert.equal(calls, 0);
}

console.log("incognito: all assertions passed");
