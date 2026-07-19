(function () {
  "use strict";

  const Api = window.PluginApi;
  const { React, GQL, libraries } = Api;
  const { Button, Nav } = libraries.Bootstrap;
  const { NavLink } = libraries.ReactRouterDOM;
  const { FontAwesomeIcon } = libraries.ReactFontAwesome;
  const { faCompass } = libraries.FontAwesomeSolid;
  const LANES = [
    {
      value: "for_you",
      label: "For You",
      description: "A balanced shelf of strong matches, timely revisits, and a little discovery.",
    },
    {
      value: "best_bets",
      label: "Best Bets",
      description: "The strongest unwatched matches for when you want a dependable choice now.",
    },
    {
      value: "revisit",
      label: "Revisit",
      description: "Scenes you have enjoyed before, brought back after enough time away.",
    },
    {
      value: "discover",
      label: "Discover",
      description: "Mostly your taste, with one boundary gently challenged to find something new.",
    },
    {
      value: "adventure",
      label: "Adventure",
      description: "Deliberate long shots that explore gaps in the model—and possible pruning candidates.",
    },
  ];
  const EVENT_QUEUE_KEY = "stash-curator:event-queue:v1";
  const ORIGIN_KEY = "stash-curator:origin:v1";
  const slateCache = new Map();
  const slateRequests = new Map();
  let cachedModelId = null;
  let cacheGeneration = 0;
  let modelUpdateTimer = null;

  function uuid() {
    return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  }

  async function operation(args) {
    const response = await fetch("/graphql", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query:
          "mutation CuratorOperation($args: Map!) { " +
          "runPluginOperation(plugin_id: \"stash-curator\", args: $args) }",
        variables: { args },
      }),
    });
    const payload = await response.json();
    if (!response.ok || payload.errors) {
      throw new Error(payload.errors?.[0]?.message || `HTTP ${response.status}`);
    }
    return payload.data.runPluginOperation;
  }

  function slateKey(lane, exploration) {
    return `${lane}:${lane === "for_you" ? exploration : 0}`;
  }

  function clearSlateCache() {
    slateCache.clear();
    slateRequests.clear();
    cachedModelId = null;
    cacheGeneration += 1;
  }

  function loadSlate(lane, exploration, prefetched = false) {
    const key = slateKey(lane, exploration);
    if (slateCache.has(key)) return Promise.resolve(slateCache.get(key));
    if (slateRequests.has(key)) return slateRequests.get(key);
    const generation = cacheGeneration;
    const request = operation({
      operation: "get_slate",
      lane,
      exploration,
      context: { route: location.pathname, prefetched },
    })
      .then((data) => {
        if (generation !== cacheGeneration) return data;
        if (cachedModelId && cachedModelId !== data.model_id) clearSlateCache();
        cachedModelId = data.model_id;
        slateCache.set(key, data);
        return data;
      })
      .finally(() => slateRequests.delete(key));
    slateRequests.set(key, request);
    return request;
  }

  async function prefetchLanes(activeLane, exploration) {
    const generation = cacheGeneration;
    for (const option of LANES) {
      if (generation !== cacheGeneration) return;
      if (option.value === activeLane) continue;
      try {
        await loadSlate(option.value, option.value === "for_you" ? exploration : 0, true);
      } catch (_) {
        // Opening the lane will retry and show any error in context.
      }
    }
  }

  async function runTask(taskName) {
    const response = await fetch("/graphql", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query:
          "mutation CuratorTask($task: String!) { " +
          "runPluginTask(plugin_id: \"stash-curator\", task_name: $task) }",
        variables: { task: taskName },
      }),
    });
    const payload = await response.json();
    if (!response.ok || payload.errors) {
      throw new Error(payload.errors?.[0]?.message || `HTTP ${response.status}`);
    }
    return payload.data.runPluginTask;
  }

  function scheduleModelUpdate(delay = 2500) {
    clearTimeout(modelUpdateTimer);
    modelUpdateTimer = setTimeout(
      () => operation({ operation: "health" })
        .then((health) => health.model_update_ready && !health.model_rebuilding
          ? runTask("Apply recent Curator feedback")
          : null)
        .catch(() => {}),
      delay
    );
  }

  function idFilter(ids) {
    return ids.reduce(
      (filter, id) => ({ id: { value: Number(id), modifier: "EQUALS" }, ...(filter && { OR: filter }) }),
      null
    );
  }

  function ScoreNode({ name, value }) {
    if (value === null || value === undefined) return null;
    if (typeof value !== "object") {
      return React.createElement(
        "div",
        { className: "curator-score-leaf" },
        React.createElement("span", null, name.replaceAll("_", " ")),
        React.createElement("code", null, typeof value === "number" ? value.toFixed(3) : String(value))
      );
    }
    if (Array.isArray(value)) return null;
    return React.createElement(
      "details",
      { className: "curator-score-node" },
      React.createElement("summary", null, name.replaceAll("_", " ")),
      React.createElement(
        "div",
        { className: "curator-score-children" },
        Object.entries(value).map(([key, child]) =>
          React.createElement(ScoreNode, { key, name: key, value: child })
        )
      )
    );
  }

  function Feedback({ item, onRemove }) {
    const [saved, setSaved] = React.useState("");
    const [busy, setBusy] = React.useState(false);
    async function send(feedbackType, value) {
      setBusy(true);
      try {
        await operation({
          operation: "submit_feedback",
          entries: [
            {
              feedback_id: uuid(),
              scene_id: item.scene_id,
              feedback_type: feedbackType,
              value,
              occurred_at_ms: Date.now(),
              impression_id: item.impression_id,
            },
          ],
        });
        scheduleModelUpdate();
        setSaved(feedbackType === "thumb_up" ? "Saved" : "Removed from this view");
        if (feedbackType !== "thumb_up") onRemove(item.scene_id);
      } catch (error) {
        setSaved(error.message);
      } finally {
        setBusy(false);
      }
    }
    return React.createElement(
      "div",
      { className: "curator-feedback" },
      React.createElement(Button, { size: "sm", disabled: busy, onClick: () => send("thumb_up") }, "Useful 👍"),
      React.createElement(Button, { size: "sm", disabled: busy, onClick: () => send("thumb_down") }, "Not for me 👎"),
      React.createElement(
        "details",
        { className: "curator-more" },
        React.createElement("summary", { className: "btn btn-secondary btn-sm" }, "More"),
        React.createElement(
          "div",
          { className: "curator-more-menu" },
          React.createElement(Button, { size: "sm", onClick: () => send("not_now") }, "Not now"),
          React.createElement(Button, { size: "sm", onClick: () => send("never_show") }, "Never show"),
          React.createElement(Button, { size: "sm", onClick: () => send("metadata_wrong", "Do not train from this metadata") }, "Metadata is wrong"),
          React.createElement(Button, { size: "sm", onClick: () => send("prune", "Review for removal") }, "Mark for pruning")
        )
      ),
      saved && React.createElement("small", { role: "status" }, saved)
    );
  }

  function RecommendationCard({ item, scene, slate, onRemove }) {
    const { SceneCard } = Api.components;
    const card = React.useRef(null);
    React.useEffect(() => {
      let timer;
      let qualified = false;
      function record() {
        if (qualified) return;
        qualified = true;
        enqueue({
          event_id: `impression:${item.impression_id}:${item.scene_id}`,
          event_type: "qualified_impression",
          impression_id: item.impression_id,
          scene_id: item.scene_id,
          occurred_at_ms: Date.now(),
        });
      }
      if (!window.IntersectionObserver) {
        record();
        return undefined;
      }
      const observer = new IntersectionObserver(
        ([entry]) => {
          clearTimeout(timer);
          if (entry.intersectionRatio >= 0.5) timer = setTimeout(record, 1000);
        },
        { threshold: 0.5 }
      );
      observer.observe(card.current);
      return () => {
        clearTimeout(timer);
        observer.disconnect();
      };
    }, [item.impression_id, item.scene_id]);
    function rememberOrigin(event) {
      if (!event.target.closest("a")) return;
      sessionStorage.setItem(
        ORIGIN_KEY,
        JSON.stringify({
          scene_id: item.scene_id,
          impression_id: item.impression_id,
          lane: slate.lane,
          impression_position: item.position,
          model_id: slate.model_id,
        })
      );
    }
    return React.createElement(
      "article",
      { className: "curator-card", onClickCapture: rememberOrigin, ref: card },
      scene
        ? React.createElement(SceneCard, { scene })
        : React.createElement("div", { className: "curator-card-placeholder" }, `Scene ${item.scene_id}`),
      React.createElement(
        "div",
        { className: "curator-card-body" },
        React.createElement("div", { className: "curator-take-label" }, "Curator's take"),
        React.createElement("p", { className: "curator-explanation" }, item.explanation),
        React.createElement(
          "div",
          { className: "curator-card-details" },
          React.createElement(
            "details",
            { className: "curator-evidence" },
            React.createElement("summary", null, "Why this?"),
            React.createElement(
              "ul",
              null,
              item.supporting_reasons.map((reason, index) =>
                React.createElement(
                  "li",
                  { key: `${reason.code}-${index}` },
                  `${reason.code.replaceAll(".", " · ")} (${reason.magnitude.toFixed(2)})`
                )
              )
            )
          ),
          React.createElement(
            "details",
            { className: "curator-score" },
            React.createElement("summary", null, "How the score was built"),
            React.createElement(ScoreNode, {
              name: "total",
              value: {
                final_utility: item.final_utility,
                appeal: item.appeal,
                current_fit: item.current_fit,
                confidence: item.confidence,
                components: item.components,
                diversity_penalties: item.penalties,
                diversity_bonuses: item.bonuses,
              },
            })
          )
        ),
        React.createElement(Feedback, { item, onRemove })
      )
    );
  }

  function CuratorControls({ onRefresh }) {
    const [config, setConfig] = React.useState(null);
    const [jobs, setJobs] = React.useState([]);
    const [pruning, setPruning] = React.useState([]);
    const [exclusions, setExclusions] = React.useState([]);
    const [message, setMessage] = React.useState("");

    async function refreshStatus() {
      try {
        const [configuration, jobStatus, pruningQueue, exclusionList] = await Promise.all([
          operation({ operation: "get_config" }),
          operation({ operation: "get_job_status" }),
          operation({ operation: "get_pruning_queue" }),
          operation({ operation: "get_exclusions" }),
        ]);
        setConfig(configuration.config);
        setJobs(jobStatus.jobs);
        setPruning(pruningQueue.items);
        setExclusions(exclusionList.items);
      } catch (error) {
        setMessage(error.message);
      }
    }
    React.useEffect(() => {
      refreshStatus();
      const timer = setInterval(refreshStatus, 5000);
      return () => clearInterval(timer);
    }, []);

    async function start(taskName) {
      try {
        const id = await runTask(taskName);
        setMessage(`Started Stash job ${id}`);
        setTimeout(refreshStatus, 1000);
      } catch (error) {
        setMessage(error.message);
      }
    }
    async function save(event) {
      event.preventDefault();
      try {
        const result = await operation({ operation: "update_config", values: config });
        setConfig(result.config);
        setMessage("Settings saved");
        onRefresh();
      } catch (error) {
        setMessage(error.message);
      }
    }
    async function reset() {
      if (!confirm("Reset all Curator sidecar data? Your Stash library is not changed.")) return;
      try {
        await operation({ operation: "reset", confirmation: "RESET" });
        setMessage("Curator data reset");
        onRefresh();
      } catch (error) {
        setMessage(error.message);
      }
    }
    async function decidePruning(sceneId, state) {
      try {
        await operation({ operation: "update_pruning", scene_id: sceneId, state });
        setMessage(state === "keep" ? "Scene kept" : "Marked for manual removal from Stash");
        refreshStatus();
        onRefresh();
      } catch (error) {
        setMessage(error.message);
      }
    }
    async function restore(sceneId) {
      try {
        await operation({ operation: "reverse_exclusion", scene_id: sceneId });
        setExclusions((items) => items.filter((item) => item.scene_id !== sceneId));
        setMessage("Scene may be recommended again");
        onRefresh();
      } catch (error) {
        setMessage(error.message);
      }
    }
    function numberField(key, label, step) {
      return React.createElement(
        "label",
        null,
        label,
        React.createElement("input", {
          className: "form-control",
          type: "number",
          min: 0,
          step: step || 1,
          value: config?.[key] ?? "",
          onChange: (event) => setConfig({ ...config, [key]: Number(event.target.value) }),
        })
      );
    }

    return React.createElement(
      "details",
      { className: "curator-controls" },
      React.createElement("summary", null, "Jobs and settings"),
      React.createElement(
        "div",
        { className: "curator-task-buttons" },
        React.createElement(Button, { onClick: () => start("Sync and build recommendations") }, "Sync + build"),
        React.createElement(Button, { onClick: () => start("Rebuild recommendation model") }, "Rebuild"),
        React.createElement(Button, { onClick: () => start("Backup Curator data") }, "Backup")
      ),
      config &&
        React.createElement(
          "form",
          { className: "curator-config", onSubmit: save },
          numberField("page_size", "Scenes per lane"),
          numberField("sync_page_size", "Sync page size"),
          numberField("debounce_ms", "Model quiet period (ms)"),
          numberField("auto_sync_hours", "Automatic sync interval (hours; 0 disables)", 0.5),
          React.createElement(Button, { type: "submit", variant: "primary" }, "Save settings"),
          React.createElement(Button, { type: "button", variant: "danger", onClick: reset }, "Reset Curator data")
        ),
      jobs.length > 0 &&
        React.createElement(
          "table",
          { className: "table table-sm curator-jobs" },
          React.createElement("tbody", null, jobs.map((job) => React.createElement("tr", { key: job.job_id }, React.createElement("td", null, job.job_type), React.createElement("td", null, job.state), React.createElement("td", null, job.error || ""))))
        ),
      pruning.length > 0 &&
        React.createElement(
          "section",
          { className: "curator-pruning" },
          React.createElement("h3", null, "Pruning review"),
          pruning.map((item) =>
            React.createElement(
              "div",
              { key: item.scene_id },
              React.createElement(NavLink, { to: `/scenes/${item.scene_id}` }, item.title || `Scene ${item.scene_id}`),
              React.createElement(Button, { size: "sm", onClick: () => decidePruning(item.scene_id, "keep") }, "Keep"),
              item.state === "review"
                ? React.createElement(Button, { size: "sm", variant: "danger", onClick: () => decidePruning(item.scene_id, "remove") }, "Mark ready for removal")
                : React.createElement("span", null, "Ready for manual deletion in Stash")
            )
          )
        ),
      exclusions.length > 0 &&
        React.createElement(
          "section",
          { className: "curator-pruning" },
          React.createElement("h3", null, "Never show"),
          exclusions.map((item) =>
            React.createElement(
              "div",
              { key: item.scene_id },
              React.createElement(NavLink, { to: `/scenes/${item.scene_id}` }, item.title || `Scene ${item.scene_id}`),
              React.createElement(Button, { size: "sm", onClick: () => restore(item.scene_id) }, "Allow again")
            )
          )
        ),
      message && React.createElement("p", { role: "status" }, message)
    );
  }

  function CuratorPage() {
    const loadingComponents = Api.hooks.useLoadComponents([Api.loadableComponents.SceneCard]);
    const [lane, setLane] = React.useState("for_you");
    const [slate, setSlate] = React.useState(null);
    const [error, setError] = React.useState("");
    const [loading, setLoading] = React.useState(true);
    const [exploration, setExploration] = React.useState(0);
    const [refreshKey, setRefreshKey] = React.useState(0);

    React.useEffect(() => {
      let active = true;
      const cached = slateCache.get(slateKey(lane, exploration));
      setSlate(cached || null);
      setLoading(!cached);
      setError("");
      loadSlate(lane, exploration).then(
        (data) => {
          if (!active) return;
          setSlate(data);
          setLoading(false);
          prefetchLanes(lane, exploration);
        },
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => {
        active = false;
      };
    }, [lane, exploration, refreshKey]);

    const laneOption = LANES.find((option) => option.value === lane);

    const ids = slate?.items.map((item) => item.scene_id) || [];
    const scenesQuery = GQL.useFindScenesQuery({
      variables: {
        filter: { per_page: Math.max(1, ids.length) },
        scene_filter: idFilter(ids),
      },
      skip: ids.length === 0,
    });
    const scenes = new Map(
      (scenesQuery.data?.findScenes?.scenes || []).map((scene) => [String(scene.id), scene])
    );
    function remove(sceneId) {
      const excluded = slate.items.map((item) => item.scene_id);
      clearSlateCache();
      setSlate((current) => ({ ...current, items: current.items.filter((item) => item.scene_id !== sceneId) }));
      operation({ operation: "replace_item", lane, exploration, exclude_scene_ids: excluded }).then(
        (replacement) =>
          setSlate((current) => ({
            ...current,
            items: [
              ...current.items,
              ...replacement.items.filter(
                (candidate) => !current.items.some((item) => item.scene_id === candidate.scene_id)
              ),
            ],
          })),
        () => {}
      );
    }
    function refresh() {
      clearSlateCache();
      setRefreshKey((value) => value + 1);
    }

    return React.createElement(
      "main",
      { className: "curator-page container-fluid" },
      React.createElement(
        "header",
        { className: "curator-header" },
        React.createElement("div", null, React.createElement("h1", null, "Stash Curator"), React.createElement("p", { className: "curator-tagline" }, "Navigate your library, guided by your taste.")),
        React.createElement(CuratorControls, { onRefresh: refresh })
      ),
      React.createElement(
        Nav,
        { variant: "tabs", role: "tablist", className: "curator-tabs" },
        LANES.map((option) =>
          React.createElement(Nav.Link, { key: option.value, as: "button", active: lane === option.value, onClick: () => setLane(option.value), role: "tab", "aria-selected": lane === option.value }, option.label)
        )
      ),
      React.createElement(
        "section",
        { className: "curator-lane-intro" },
        React.createElement("p", null, laneOption?.description),
        lane === "for_you" &&
        React.createElement(
          "label",
          { className: "curator-exploration" },
          React.createElement("span", null, "Familiar"),
          React.createElement("input", {
            type: "range",
            min: -1,
            max: 1,
            step: 1,
            value: exploration,
            "aria-label": "For You exploration level",
            onChange: (event) => setExploration(Number(event.target.value)),
          }),
          React.createElement("span", null, "Adventurous")
        ),
      ),
      (loading || loadingComponents || scenesQuery.loading) &&
        React.createElement(
          "div",
          { className: "curator-loading", role: "status" },
          React.createElement("span", null, loading ? `Preparing ${laneOption?.label || "recommendations"}…` : "Loading scene cards…"),
          React.createElement("div", { className: "curator-progress", "aria-hidden": "true" })
        ),
      slate?.rebuilding && React.createElement("div", { className: "alert alert-info", role: "status" }, "Curator is rebuilding its model. These recommendations use the previous completed model."),
      slate?.model_pending && !slate.rebuilding && React.createElement("div", { className: "alert alert-info", role: "status" }, "Your recent choices are waiting to be folded into the model."),
      error && React.createElement("div", { className: "alert alert-danger" }, error, React.createElement("p", null, "Run “Sync and build recommendations” from Tasks if no model exists yet.")),
      scenesQuery.error && React.createElement("div", { className: "alert alert-danger" }, scenesQuery.error.message),
      slate && !loading &&
        React.createElement(
          React.Fragment,
          null,
          slate.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "Nothing qualifies for this lane right now."),
          React.createElement(
            "section",
            { className: "curator-grid", role: "tabpanel", "aria-live": "polite" },
            slate.items.map((item) => React.createElement(RecommendationCard, { key: item.scene_id, item, scene: scenes.get(String(item.scene_id)), slate, onRemove: remove }))
          )
        )
    );
  }

  function readQueue() {
    try {
      const value = JSON.parse(localStorage.getItem(EVENT_QUEUE_KEY) || "[]");
      return Array.isArray(value) ? value : [];
    } catch (_) {
      return [];
    }
  }

  function queueId(entry) {
    return entry.session_id || entry.event_id;
  }

  let flushing = false;
  async function flushQueue() {
    if (flushing) return;
    const entries = readQueue();
    if (!entries.length) return;
    flushing = true;
    try {
      await operation({ operation: "submit_events", entries });
      if (entries.some((entry) => entry.event_type !== "qualified_impression")) {
        scheduleModelUpdate();
      }
      const sent = new Set(entries.map(queueId));
      localStorage.setItem(EVENT_QUEUE_KEY, JSON.stringify(readQueue().filter((entry) => !sent.has(queueId(entry)))));
    } catch (_) {
      // Durable queue retries on the next route, online event, or plugin page load.
    } finally {
      flushing = false;
    }
  }

  function enqueue(entry) {
    const queue = readQueue();
    if (!queue.some((item) => queueId(item) === queueId(entry))) queue.push(entry);
    localStorage.setItem(EVENT_QUEUE_KEY, JSON.stringify(queue));
    flushQueue();
  }

  let tracker = null;
  function finishTracker(naturalCompletion) {
    if (!tracker) return;
    tracker.tick();
    tracker.closeRange();
    tracker.detach();
    const value = tracker.value;
    tracker = null;
    enqueue({ ...value, ended_at_ms: Date.now(), natural_completion: naturalCompletion });
  }

  function attachPlayer(pathname) {
    const match = pathname.match(/^\/scenes\/(\d+)/);
    if (!match) {
      finishTracker(false);
      return;
    }
    const sceneId = match[1];
    if (tracker?.value.scene_id === sceneId) return;
    finishTracker(false);
    function findPlayer(attempt = 0) {
      if (location.pathname !== pathname || tracker?.value.scene_id === sceneId) return;
      const player = Api.utils.InteractiveUtils.getPlayer();
      if (!player) {
        if (attempt < 20) setTimeout(() => findPlayer(attempt + 1), 250);
        return;
      }
      let origin = null;
      try {
        origin = JSON.parse(sessionStorage.getItem(ORIGIN_KEY) || "null");
      } catch (_) {}
      if (origin?.scene_id !== sceneId) origin = null;
      if (origin) sessionStorage.removeItem(ORIGIN_KEY);
      const started = Date.now();
      const handlers = {};
      const value = {
        session_id: uuid(),
        scene_id: sceneId,
        started_at_ms: started,
        active_seconds: 0,
        origin: origin ? "curator" : "stash",
        source_route: pathname,
        start_position_seconds: Number(player.currentTime() || 0),
        maximum_position_seconds: Number(player.currentTime() || 0),
        final_position_seconds: Number(player.currentTime() || 0),
        played_ranges: [],
        seek_destinations_seconds: [],
        ...(origin || {}),
      };
      let playing = false;
      let lastWall = performance.now();
      let rangeStart = null;
      function tick() {
        const now = performance.now();
        if (playing) value.active_seconds += Math.min(5, Math.max(0, (now - lastWall) / 1000));
        lastWall = now;
        const position = Number(player.currentTime() || 0);
        value.final_position_seconds = position;
        value.maximum_position_seconds = Math.max(value.maximum_position_seconds, position);
      }
      function closeRange() {
        if (rangeStart === null) return;
        const end = Number(player.currentTime() || rangeStart);
        if (end >= rangeStart) value.played_ranges.push({ start_seconds: rangeStart, end_seconds: end });
        rangeStart = null;
      }
      handlers.play = () => { lastWall = performance.now(); };
      handlers.playing = () => { tick(); playing = true; rangeStart ??= Number(player.currentTime() || 0); };
      handlers.waiting = () => { tick(); playing = false; closeRange(); };
      handlers.pause = () => { tick(); playing = false; closeRange(); };
      handlers.timeupdate = tick;
      handlers.seeking = () => { tick(); closeRange(); };
      handlers.seeked = () => { value.seek_destinations_seconds.push(Number(player.currentTime() || 0)); if (playing) rangeStart = Number(player.currentTime() || 0); };
      handlers.ended = () => finishTracker(true);
      Object.entries(handlers).forEach(([event, handler]) => player.on(event, handler));
      tracker = {
        value,
        tick,
        closeRange,
        detach: () => Object.entries(handlers).forEach(([event, handler]) => player.off(event, handler)),
      };
      if (!player.paused()) handlers.playing();
    }
    setTimeout(findPlayer, 250);
  }

  Api.register.route("/plugins/stash-curator", CuratorPage);
  function CuratorNavItem() {
    return React.createElement(
      Nav.Link,
      { as: "div", eventKey: "/plugins/stash-curator", className: "col-4 col-sm-3 col-md-2 col-lg-auto" },
      React.createElement(
        NavLink,
        { exact: true, to: "/plugins/stash-curator", activeClassName: "active", className: "btn minimal p-4 p-xl-2 d-flex d-xl-inline-block flex-column justify-content-between align-items-center" },
        React.createElement(FontAwesomeIcon, { icon: faCompass, className: "fa-icon nav-menu-icon d-block d-xl-inline mb-2 mb-xl-0" }),
        React.createElement("span", null, "Curator")
      )
    );
  }
  Api.patch.after("MainNavBar.MenuItems", function (props, _, result) {
    const children = React.Children.toArray(props.children);
    if (!children.some((child) => child.key === "stash-curator")) {
      children.push(React.createElement(CuratorNavItem, { key: "stash-curator" }));
    }
    return React.isValidElement(result) ? React.cloneElement(result, {}, children) : result;
  });
  Api.Event.addEventListener("stash:location", (event) => {
    attachPlayer(event.detail.data.location.pathname);
    flushQueue();
  });
  window.addEventListener("online", flushQueue);
  window.addEventListener("pagehide", () => finishTracker(false));
  attachPlayer(location.pathname);
  flushQueue();
  function scheduleSync() {
    operation({ operation: "health" })
      .then((health) => {
        if (health.sync_due) return runTask("Sync and build recommendations");
        if (health.model_update_ready && !health.model_rebuilding) {
          return runTask("Apply recent Curator feedback");
        }
        return null;
      })
      .catch(() => {});
  }
  scheduleSync();
  setInterval(scheduleSync, 15 * 60 * 1000);
})();
