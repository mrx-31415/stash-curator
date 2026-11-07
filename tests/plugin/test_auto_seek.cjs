const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../auto-seek/auto-seek.js"), "utf8");
const context = { Math, String, Number, parseFloat };
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  // ── pure helpers"), source.indexOf("  // ── end pure helpers")), context);
const { formatTime, parseVtt, spriteCue } = context;
const plain = (value) => JSON.parse(JSON.stringify(value));

// Times on the toasts and the pill: m:ss, with hours when needed.
assert.equal(formatTime(372), "6:12");
assert.equal(formatTime(3725), "1:02:05");
assert.equal(formatTime(-3), "0:00");

// The browser no longer scores frames: no model or runtime is loaded here.
for (const gone of ["onnxruntime", "InferenceSession", "indexedDB", "createImageBitmap"]) {
  assert.ok(!source.includes(gone), `${gone} is still referenced`);
}

// Stash's sprite VTT: the cue covering a time gives the thumbnail's place in the sprite.
const cues = parseVtt("WEBVTT\n\n00:00:00.000 --> 00:00:10.000\nsprite.jpg#xywh=0,0,160,90\n\n00:00:10.000 --> 00:01:00.500\nsprite.jpg#xywh=160,0,160,90\n");
assert.equal(cues.length, 2);
assert.deepEqual(plain(spriteCue(cues, 42)), { start: 10, end: 60.5, x: 160, y: 0, w: 160, h: 90 });
assert.equal(spriteCue(cues, 5).x, 0);
