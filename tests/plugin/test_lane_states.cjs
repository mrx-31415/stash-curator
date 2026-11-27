const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
let timers = [];
const context = {
  React: {
    createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }),
    useState: (initial) => [initial, () => {}],
    useEffect: (effect) => { timers.push(effect); },
  },
  Button: "Button", FontAwesomeIcon: "icon", faWrench: "wrench", setInterval: () => 1, clearInterval: () => {}, Math, Array,
};
vm.runInNewContext(source.slice(source.indexOf("  // Placeholder cards that shimmer while a lane loads"), source.indexOf("  // A short-lived toast after a card is hidden.")), context);
const text = (node) => typeof node === "string" ? node : (node?.children || []).map(text).join("");
const all = (node) => (node && typeof node === "object" ? [node, ...(node.children || []).flatMap(all)] : []);

const loading = context.LaneSkeleton({});
assert.equal(all(loading).find((node) => node.props.role === "status").children[0], "Loading recommendations…");
assert.equal(all(loading).filter((node) => node.props.className === "curator-skeleton-card").length, 8);
assert.equal(all(loading).find((node) => node.props.className === "curator-grid").props["aria-hidden"], "true", "placeholders are hidden from screen readers");
const rotating = context.LaneSkeleton({ message: "Finding another set of qualified scenes…" });
assert.equal(all(rotating).find((node) => node.props.role === "status").children[0], "Finding another set of qualified scenes…");

const lanes = ["for_you", "best_bets", "new_arrivals", "revisit", "stretch", "blind_spots", "dormant"];
for (const lane of lanes) assert.ok(source.includes(`    ${lane}: [`), `${lane} has its own empty state`);
const opened = [];
let rebuilt = 0;
const revisit = context.LaneEmpty({ lane: "revisit", onOpenLane: (lane) => opened.push(lane), onRebuild: () => { rebuilt += 1; } });
assert.match(text(revisit), /Nothing to revisit yet/);
all(revisit).find((node) => node.type === "Button" && text(node) === "Try For You instead").props.onClick();
assert.deepEqual(opened, ["for_you"]);
all(revisit).find((node) => node.type === "Button" && /Rebuild model/.test(text(node))).props.onClick();
assert.equal(rebuilt, 1);
const forYou = context.LaneEmpty({ lane: "for_you", onOpenLane: () => {}, onRebuild: () => {} });
assert.ok(!all(forYou).some((node) => text(node) === "Try For You instead"), "For You doesn't point at itself");
assert.match(text(context.LaneEmpty({ lane: "unknown", onOpenLane: () => {}, onRebuild: () => {} })), /Nothing qualifies for this lane right now\./);
