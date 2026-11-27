const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const context = {
  React: { createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }) },
  FontAwesomeIcon: "icon", faArrowTrendUp: "up", faArrowTrendDown: "down", faCheckCircle: "check", Button: "Button",
  formatSigned: (value) => `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}`,
  formatTimeAgo: () => "5 minutes ago",
};
vm.runInNewContext(source.slice(source.indexOf("  function movementReason("), source.indexOf("  const CARD_LEAVE_MS")), context);
const text = (node) => typeof node === "string" ? node : (node?.children || []).map(text).join("");

const impact = {
  available: true,
  scenes: {
    promoted: [
      { scene_id: 5, delta: 0.21, contributors: [{ kind: "tag", name: "Outdoor", delta: 0.15 }, { kind: "direct", name: "", delta: 0.02 }] },
      { scene_id: "8", delta: 0.09, contributors: [{ kind: "direct", name: "", delta: 0.09 }] },
      { scene_id: "9", delta: 0.0001, contributors: [{ kind: "tag", name: "Tiny", delta: 0.0001 }] },
    ],
    demoted: [{ scene_id: "2", delta: -0.12, contributors: [{ kind: "performer", name: "Performer A", delta: -0.1 }] }],
  },
};
const index = context.movementIndex(impact);
assert.deepEqual([...index.keys()], ["5", "8", "2"], "string ids, and a negligible move is left out");
assert.equal(index.get("5").reason, "your answer on Outdoor");
assert.equal(index.get("8").reason, "your feedback on it");
assert.equal(index.get("2").reason, "your answers about Performer A");
assert.equal(context.movementIndex({ available: true }).size, 0);
assert.equal(context.movementReason({ contributors: [] }), "");

const badge = context.MovementBadge({ movement: index.get("5") });
assert.match(badge.props.className, /is-up/);
assert.equal(badge.props["aria-label"], "Moved up after the last update, because of your answer on Outdoor");
assert.equal(text(badge), "+0.21");
assert.match(context.MovementBadge({ movement: index.get("2") }).props.className, /is-down/);

const banner = context.MovementBanner({ movement: { scenes: index, publishedAtMs: 0 }, onDismiss: () => {} });
assert.match(text(banner), /Recommendations updated 5 minutes ago\. Your feedback moved 3 scenes: 2 moved up and 1 moved down\./);

// Badges show once per model: the hook checks and records the model it showed.
const hook = source.slice(source.indexOf("  function useModelMovement("), source.indexOf("  function MovementBadge("));
assert.match(hook, /if \(seen === modelId\) return undefined;/);
assert.match(hook, /impact\.newer_model_id !== modelId/);
assert.match(hook, /localStorage\.setItem\(MOVEMENT_SEEN_KEY, modelId\)/);
