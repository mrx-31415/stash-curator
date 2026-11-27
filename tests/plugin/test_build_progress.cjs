const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const context = {
  React: { createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }) },
  FontAwesomeIcon: "icon", faCheckCircle: "check", Button: "Button", Date, Math, Set, String, Number,
};
vm.runInNewContext(source.slice(source.indexOf("  // A model build's real phases"), source.indexOf("  const TASK_MODE_LABELS = {")), context);
const states = (phases) => phases.map((phase) => phase.state[0]).join("");
const labels = (phases) => [...phases.map((phase) => phase.label)];

// A rebuild: the model's own phases mapped onto 0.03..0.95, then lanes and pages.
const rebuild = (progress, extra = {}) => context.buildPhases({ job_type: "update-model", state: "running", progress, ...extra });
assert.equal(JSON.stringify(labels(rebuild(0))), JSON.stringify(["Describing your scenes", "Learning from your plays and ratings", "Weighing tags, performers and studios", "Scoring your library", "Saving the model", "Organizing recommendation lanes", "Preparing recommendation pages"]));
assert.equal(states(rebuild(0)), "appppp" + "p");
// Features end at model 0.25 → task 0.03 + 0.92 * 0.25 = 0.26.
assert.equal(states(rebuild(0.27)), "dappppp");
assert.equal(states(rebuild(0.5)), "dddappp");
assert.equal(states(rebuild(0.9316)), "ddddapp", "the build log's last model progress is still saving");
assert.equal(states(rebuild(0.96)), "dddddap");
assert.equal(states(rebuild(0.98)), "dddddda");
assert.equal(states(rebuild(0.5, { state: "complete" })), "ddddddd");
const scoring = rebuild(0.5).find((phase) => phase.state === "active");
assert.ok(scoring.fraction > 0.3 && scoring.fraction < 0.4, `scoring is a third through (${scoring.fraction})`);

// A sync-and-build syncs first and maps the model onto 0.68..0.95.
const sync = (progress) => context.buildPhases({ job_type: "sync-build", state: "running", progress });
assert.equal(labels(sync(0))[0], "Syncing your library from Stash");
assert.equal(labels(sync(0)).length, 9);
assert.equal(states(sync(0.3)), "appppppp" + "p");
assert.equal(states(sync(0.6)), "dapppppp" + "p");
assert.equal(states(sync(0.7)), "ddapppp" + "pp");
// The nav indicator only has a description; it gets the same stages.
assert.equal(context.curatorTaskStage({ description: "Sync and build recommendations", progress: 0.6 }), "Rebuilding your play history");
assert.equal(context.curatorTaskStage({ description: "Rebuild recommendation model", progress: 0.5 }), "Scoring your library");
assert.equal(context.curatorTaskStage({ description: "Backup Curator data", progress: 0.5 }), "Creating Curator backup");
assert.equal(context.buildPhases({ job_type: "backup" }), null);

// Time left: from the last run of the same kind, else extrapolated.
assert.equal(context.buildTimeLeft({ progress: 0.5, started_at_ms: 0 }, 90000, 30000), 60);
assert.equal(context.buildTimeLeft({ progress: 0.5, started_at_ms: 0 }, 0, 30000), 30);
assert.equal(context.buildTimeLeft({ progress: 0.01, started_at_ms: 0 }, 0, 30000), null);
assert.equal(context.formatSecondsLeft(94), "About 1 min 34 s left");
assert.equal(context.formatSecondsLeft(62), "About 1 min left");
assert.equal(context.formatSecondsLeft(3), "Almost done");

const view = context.ModelBuildProgress({ job: { job_type: "build", state: "running", progress: 0.5, started_at_ms: Date.now() - 30000 }, previousMs: 90000 });
const items = view.children.find((child) => child.type === "ol").children;
assert.equal(items.length, 7);
assert.match(items[3].props.className, /is-active/);
assert.ok(items[3].children.some((child) => child?.props?.className === "curator-build-phase-bar"));

// Tasks shows the view while a build runs and a result when it finishes.
const tasks = source.slice(source.indexOf("  function TasksPanel("), source.indexOf("  function CuratorControls("));
assert.match(tasks, /building && React\.createElement\(ModelBuildProgress/);
assert.match(tasks, /!building && doneBuild && React\.createElement\(ModelBuildDone/);
