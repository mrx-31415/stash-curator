(function () {
  "use strict";

  const Api = window.PluginApi;
  const { React, GQL, libraries } = Api;
  const { Button, Nav } = libraries.Bootstrap;
  const { NavLink } = libraries.ReactRouterDOM;
  const { FontAwesomeIcon } = libraries.ReactFontAwesome;
  const { faBullseye, faCheckCircle, faClock, faCog, faCompass, faDatabase, faHistory, faPlay, faSearch, faStar, faSync, faThumbsDown, faThumbsUp, faWrench } = libraries.FontAwesomeSolid;
  const LANES = [
    {
      value: "for_you",
      label: "For You",
      icon: faStar,
      description: "A balanced shelf of strong matches, timely revisits, and a little discovery.",
    },
    {
      value: "best_bets",
      label: "Best Bets",
      icon: faBullseye,
      description: "The strongest unwatched matches for when you want a dependable choice now.",
    },
    {
      value: "revisit",
      label: "Revisit",
      icon: faHistory,
      description: "Scenes you have enjoyed before, brought back after enough time away.",
    },
    {
      value: "discover",
      label: "Discover",
      icon: faSearch,
      description: "Mostly your taste, with one boundary gently challenged to find something new.",
    },
    {
      value: "adventure",
      label: "Adventure",
      icon: faCompass,
      description: "Deliberate long shots that explore gaps in the model—and possible pruning candidates.",
    },
  ];
  const NAV_ITEMS = [
    ...LANES,
    {
      value: "similar",
      label: "Similar",
      icon: faSearch,
      description: "Start from a scene or performer and find close, preference-aware matches.",
    },
    {
      value: "prune",
      label: "Prune",
      icon: faWrench,
      description: "Review explicit dislikes and high-confidence poor matches for library cleanup.",
    },
    {
      value: "expand",
      label: "Expand",
      icon: faCompass,
      description: "Find promising scenes and performers beyond your library.",
    },
  ];
  const laneByValue = new Map(LANES.map((lane) => [lane.value, lane]));
  const EVENT_QUEUE_KEY = "stash-curator:event-queue:v1";
  const ORIGIN_KEY = "stash-curator:origin:v1";
  const SLATE_CACHE_KEY = "stash-curator:slates:v1";
  const restoredCache = readSlateCache();
  const slateCache = new Map(restoredCache.entries);
  const slateRequests = new Map();
  let cachedModelId = restoredCache.modelId;
  let cacheGeneration = 0;
  let modelUpdateTimer = null;

  function uuid() {
    return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  }

  async function operation(args) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch("/graphql", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
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
    } catch (error) {
      if (error.name === "AbortError") throw new Error("Curator operation timed out");
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function slateKey(lane) {
    return `${lane}:0`;
  }

  function readSlateCache() {
    try {
      const value = JSON.parse(sessionStorage.getItem(SLATE_CACHE_KEY) || "null");
      return value && Array.isArray(value.entries)
        ? { modelId: value.modelId || null, entries: value.entries.filter((entry) => Array.isArray(entry) && entry.length === 2) }
        : { modelId: null, entries: [] };
    } catch (_) {
      return { modelId: null, entries: [] };
    }
  }

  function persistSlateCache() {
    try {
      sessionStorage.setItem(
        SLATE_CACHE_KEY,
        JSON.stringify({ modelId: cachedModelId, entries: [...slateCache.entries()] })
      );
    } catch (_) {
      // The in-memory cache still works if browser storage is unavailable or full.
    }
  }

  function clearSlateCache() {
    slateCache.clear();
    slateRequests.clear();
    cachedModelId = null;
    sessionStorage.removeItem(SLATE_CACHE_KEY);
    cacheGeneration += 1;
  }

  function loadSlate(lane, prefetched = false) {
    const key = slateKey(lane);
    if (slateCache.has(key)) return Promise.resolve(slateCache.get(key));
    if (slateRequests.has(key)) return slateRequests.get(key);
    const generation = cacheGeneration;
    const request = operation({
      operation: "get_slate",
      lane,
      exploration: 0,
      context: { route: location.pathname, prefetched },
    })
      .then((data) => {
        if (generation !== cacheGeneration) return data;
        if (cachedModelId && cachedModelId !== data.model_id) clearSlateCache();
        cachedModelId = data.model_id;
        slateCache.set(key, data);
        persistSlateCache();
        return data;
      })
      .finally(() => slateRequests.delete(key));
    slateRequests.set(key, request);
    return request;
  }

  async function prefetchLanes(activeLane) {
    const generation = cacheGeneration;
    for (const option of LANES) {
      if (generation !== cacheGeneration) return;
      if (option.value === activeLane) continue;
      try {
        await loadSlate(option.value, true);
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
      React.createElement(Button, { className: "curator-feedback-button", variant: "link", size: "sm", disabled: busy, title: "Useful: strengthen recommendations like this one.", "aria-label": "Useful", onClick: () => send("thumb_up") }, React.createElement(FontAwesomeIcon, { icon: faThumbsUp })),
      React.createElement(Button, { className: "curator-feedback-button", variant: "link", size: "sm", disabled: busy, title: "Not for me: treat this recommendation as a poor match.", "aria-label": "Not for me", onClick: () => send("thumb_down") }, React.createElement(FontAwesomeIcon, { icon: faThumbsDown })),
      React.createElement(
        "details",
        { className: "curator-more" },
        React.createElement("summary", { className: "btn btn-secondary btn-sm", title: "More ways to refine this recommendation." }, "More"),
        React.createElement(
          "div",
          { className: "curator-more-menu" },
          React.createElement(Button, { size: "sm", title: "Hide this scene temporarily without treating it as a dislike.", onClick: () => send("not_now") }, "Not now"),
          React.createElement(Button, { size: "sm", title: "Permanently exclude this scene from Curator.", onClick: () => send("never_show") }, "Never show"),
          React.createElement(Button, { size: "sm", title: "Keep the scene, but do not learn from its current metadata.", onClick: () => send("metadata_wrong", "Do not train from this metadata") }, "Metadata is wrong"),
          React.createElement(Button, { size: "sm", title: "Add this scene to the library-removal review queue.", onClick: () => send("prune", "Review for removal") }, "Mark for pruning")
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
      { className: `curator-card curator-source-${item.source_lane}`, onClickCapture: rememberOrigin, ref: card },
      React.createElement(
        "span",
        { className: `curator-source-badge curator-lane-${item.source_lane}`, title: `Selected from ${laneByValue.get(item.source_lane)?.label || item.source_lane}`, "aria-label": `Selected from ${laneByValue.get(item.source_lane)?.label || item.source_lane}` },
        React.createElement(FontAwesomeIcon, { icon: laneByValue.get(item.source_lane)?.icon || faCompass })
      ),
      scene
        ? React.createElement(SceneCard, { scene })
        : React.createElement("div", { className: "curator-card-placeholder" }, `Scene ${item.scene_id}`),
      React.createElement(
        "div",
        { className: "curator-card-body" },
        React.createElement(
          "div",
          { className: "curator-card-details" },
          React.createElement(
            "details",
            { className: "curator-evidence" },
            React.createElement("summary", null, "Why this?"),
            React.createElement("p", { className: "curator-explanation" }, item.explanation),
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
            React.createElement("summary", null, `Score · ${item.final_utility.toFixed(2)}`),
            React.createElement(ScoreNode, { name: "appeal", value: item.appeal }),
            React.createElement(ScoreNode, { name: "current_fit", value: item.current_fit }),
            React.createElement(ScoreNode, { name: "confidence", value: item.confidence }),
            React.createElement(ScoreNode, { name: "components", value: item.components }),
            React.createElement(ScoreNode, { name: "diversity_penalties", value: item.penalties }),
            React.createElement(ScoreNode, { name: "diversity_bonuses", value: item.bonuses })
          ),
          React.createElement(Feedback, { item, onRemove })
        )
      )
    );
  }

  function SimilarityPanel({ initialType = "scene", initialId = null, initialLabel = null }) {
    const { SceneCard, PerformerCard } = Api.components;
    const [entityType, setEntityType] = React.useState(initialType);
    const [source, setSource] = React.useState("library");
    const [query, setQuery] = React.useState("");
    const [search, setSearch] = React.useState("");
    const [selected, setSelected] = React.useState(null);
    const [result, setResult] = React.useState(null);
    const [error, setError] = React.useState("");
    const [loading, setLoading] = React.useState(false);
    const sceneSearch = GQL.useFindScenesQuery({
      variables: { filter: { q: search, per_page: 8 } },
      skip: entityType !== "scene" || !search,
    });
    const performerSearch = GQL.useFindPerformersQuery({
      variables: { filter: { q: search, per_page: 8 } },
      skip: entityType !== "performer" || !search,
    });
    const items = result?.items || [];
    const ids = source === "library" ? items.map((item) => item.entity_id) : [];
    const similarScenes = GQL.useFindScenesQuery({
      variables: { filter: { per_page: Math.max(1, ids.length) }, scene_filter: idFilter(ids) },
      skip: entityType !== "scene" || ids.length === 0,
    });
    const similarPerformers = GQL.useFindPerformersQuery({
      variables: { filter: { per_page: Math.max(1, ids.length) }, performer_filter: idFilter(ids) },
      skip: entityType !== "performer" || ids.length === 0,
    });
    const entities = new Map(
      ((entityType === "scene"
        ? similarScenes.data?.findScenes?.scenes
        : similarPerformers.data?.findPerformers?.performers) || []
      ).map((entity) => [String(entity.id), entity])
    );
    const candidates = entityType === "scene"
      ? sceneSearch.data?.findScenes?.scenes || []
      : performerSearch.data?.findPerformers?.performers || [];

    function load(id, label, type = entityType, nextSource = source) {
      setSelected({ id: String(id), label: label || `#${id}` });
      setLoading(true);
      setError("");
      operation({ operation: nextSource === "library" ? "get_similar" : "get_external_similar", entity_type: type, entity_id: String(id) }).then(
        (data) => (setResult(data), setLoading(false)),
        (failure) => (setError(failure.message), setLoading(false))
      );
    }
    function choose(entity) {
      load(entity.id, entity.title || entity.name || `#${entity.id}`);
    }
    React.useEffect(() => {
      if (initialId) load(initialId, initialLabel, initialType, "library");
    }, []);
    function switchType(value) {
      setEntityType(value);
      setSearch("");
      setSelected(null);
      setResult(null);
    }
    function switchSource(value) {
      setSource(value);
      if (selected) load(selected.id, selected.label, entityType, value);
    }
    function relationshipText(item) {
      const labels = {
        same_performer: "Same performer",
        similar_performer: "Similar performer",
        shared_content: "Shared content",
        similar_structure: "Similar structure",
        same_studio: "Same studio",
      };
      const parts = item.relationships.map((value) => labels[value] || value);
      if (item.details.shared_tags?.length) parts.push(item.details.shared_tags.join(", "));
      return parts.join(" · ");
    }
    return React.createElement(
      "section",
      { className: "curator-similar" },
      React.createElement(
        "div",
        { className: "curator-similar-search" },
        React.createElement(
          "div",
          { className: "btn-group", role: "group", "aria-label": "Similarity type" },
          ["scene", "performer"].map((value) => React.createElement(Button, { key: value, size: "sm", variant: entityType === value ? "primary" : "secondary", onClick: () => switchType(value) }, value === "scene" ? "Scenes" : "Performers"))
        ),
        React.createElement(
          "form",
          { onSubmit: (event) => (event.preventDefault(), setSearch(query.trim())) },
          React.createElement("input", { className: "form-control form-control-sm", value: query, onChange: (event) => setQuery(event.target.value), placeholder: `Search for a ${entityType}…`, "aria-label": `Search for a ${entityType}` }),
          React.createElement(Button, { size: "sm", type: "submit", disabled: !query.trim() }, "Search")
        )
      ),
      search && !selected && React.createElement(
        "div",
        { className: "curator-similar-candidates" },
        candidates.map((entity) => React.createElement(Button, { key: entity.id, variant: "link", onClick: () => choose(entity) }, entity.title || entity.name || `#${entity.id}`)),
        !sceneSearch.loading && !performerSearch.loading && candidates.length === 0 && React.createElement("p", null, "No matches found.")
      ),
      selected && React.createElement("p", { className: "curator-similar-source" }, `Similar to ${selected.label}`),
      selected && React.createElement("div", { className: "btn-group curator-similar-source-tabs", role: "group", "aria-label": "Similarity source" }, [["library", "Library"], ["stashdb", "StashDB"]].map(([value, label]) => React.createElement(Button, { key: value, size: "sm", variant: source === value ? "primary" : "secondary", onClick: () => switchSource(value) }, label))),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Finding close matches…"), React.createElement("div", { className: "curator-progress", "aria-hidden": "true" })),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      result && source === "library" && React.createElement(
        "div",
        { className: "curator-grid" },
        items.map((item, position) => {
          const entity = entities.get(String(item.entity_id));
          if (!entity) return null;
          const body = React.createElement("div", { className: "curator-card-body" }, React.createElement("p", { className: "curator-similarity-reason" }, relationshipText(item)), React.createElement("small", null, `Similarity ${item.similarity.toFixed(2)} · predicted appeal ${item.appeal.toFixed(2)}`));
          if (entityType === "performer") return React.createElement("article", { key: item.entity_id, className: "curator-card" }, React.createElement(PerformerCard, { performer: entity }), body);
          const feedbackItem = { ...item, scene_id: item.entity_id, impression_id: result.impression_id };
          function rememberOrigin(event) {
            if (!event.target.closest("a")) return;
            sessionStorage.setItem(ORIGIN_KEY, JSON.stringify({ scene_id: item.entity_id, impression_id: result.impression_id, lane: "similar", impression_position: position, model_id: result.model_id }));
          }
          return React.createElement("article", { key: item.entity_id, className: "curator-card", onClickCapture: rememberOrigin }, React.createElement(SceneCard, { scene: entity }), body, React.createElement("div", { className: "curator-similar-feedback" }, React.createElement(Feedback, { item: feedbackItem, onRemove: () => setResult((current) => ({ ...current, items: current.items.filter((value) => value.entity_id !== item.entity_id) })) })));
        })
      ),
      result && source === "stashdb" && React.createElement(
        "div",
        { className: "curator-grid curator-external-grid" },
        items.map((item) => {
          const payload = item.payload;
          const image = payload.images?.find((value) => value.url)?.url;
          const href = `https://stashdb.org/${entityType === "scene" ? "scenes" : "performers"}/${item.id}`;
          return React.createElement("article", { key: item.id, className: "curator-card curator-external-card" }, image && React.createElement("a", { href, target: "_blank", rel: "noreferrer" }, React.createElement("img", { src: image, loading: "lazy", alt: "" })), React.createElement("div", { className: "curator-card-body" }, React.createElement("h3", null, React.createElement("a", { href, target: "_blank", rel: "noreferrer" }, payload.title || payload.name || item.id)), React.createElement("small", null, `Similarity ${item.similarity.toFixed(2)} · preference-aware rank ${item.score.toFixed(2)}`)), React.createElement("div", { className: "curator-prune-actions" }, React.createElement("a", { className: "btn btn-secondary btn-sm", href, target: "_blank", rel: "noreferrer" }, "Open StashDB"), entityType === "performer" && React.createElement(NavLink, { className: "btn btn-secondary btn-sm", to: `/plugins/stash-curator?view=expand&performer=${item.id}` }, "Show scenes")));
        })
      )
    );
  }

  function PrunePanel() {
    const { SceneCard } = Api.components;
    const [view, setView] = React.useState("candidates");
    const [broader, setBroader] = React.useState(false);
    const [page, setPage] = React.useState(1);
    const [data, setData] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState("");
    const [version, setVersion] = React.useState(0);
    React.useEffect(() => {
      let active = true;
      setLoading(true);
      operation({ operation: "get_prune_candidates", view, broader, page }).then(
        (result) => active && (setData(result), setLoading(false)),
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => { active = false; };
    }, [view, broader, page, version]);
    const ids = data?.items.map((item) => item.scene_id) || [];
    const scenesQuery = GQL.useFindScenesQuery({
      variables: { filter: { per_page: Math.max(1, ids.length) }, scene_filter: idFilter(ids) },
      skip: ids.length === 0,
    });
    const scenes = new Map((scenesQuery.data?.findScenes?.scenes || []).map((scene) => [String(scene.id), scene]));
    function refresh() { setVersion((value) => value + 1); }
    async function tag(sceneIds, tagged) {
      try {
        await operation({ operation: "set_prune_tag", scene_ids: sceneIds, tagged });
        clearSlateCache();
        refresh();
      } catch (failure) { setError(failure.message); }
    }
    async function dismiss(sceneId) {
      try {
        await operation({ operation: "dismiss_prune_candidate", scene_id: sceneId });
        refresh();
      } catch (failure) { setError(failure.message); }
    }
    function tagPage() {
      if (ids.length && window.confirm(`Add ${data.tag_name} to these ${ids.length} scenes?`)) tag(ids, true);
    }
    return React.createElement(
      "section",
      { className: "curator-prune-page" },
      React.createElement(
        "div",
        { className: "curator-prune-toolbar" },
        React.createElement(
          "div",
          { className: "btn-group", role: "group", "aria-label": "Prune view" },
          [["candidates", "Candidates"], ["tagged", "Tagged"], ["explicit", "Explicit dislikes"], ["suspects", "Model suspects"]].map(([value, label]) => React.createElement(Button, { key: value, size: "sm", variant: view === value ? "primary" : "secondary", onClick: () => (setView(value), setPage(1)) }, label))
        ),
        React.createElement("label", { title: "Include lower-confidence predicted dislikes." }, React.createElement("input", { type: "checkbox", checked: broader, onChange: (event) => (setBroader(event.target.checked), setPage(1)) }), " Broader"),
        view !== "tagged" && React.createElement(Button, { size: "sm", variant: "danger", disabled: !ids.length, onClick: tagPage }, `Tag visible (${ids.length})`)
      ),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Reviewing prune evidence…"), React.createElement("div", { className: "curator-progress", "aria-hidden": "true" })),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      data && !loading && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "Nothing in this view."),
      data && React.createElement(
        "div",
        { className: "curator-grid" },
        data.items.map((item) => {
          const scene = scenes.get(String(item.scene_id));
          if (!scene) return null;
          return React.createElement(
            "article",
            { key: item.scene_id, className: "curator-card" },
            item.tagged && React.createElement("span", { className: "curator-prune-badge", title: `Tagged ${data.tag_name}`, "aria-label": `Tagged ${data.tag_name}` }, React.createElement(FontAwesomeIcon, { icon: faWrench })),
            React.createElement(SceneCard, { scene }),
            React.createElement("div", { className: "curator-card-body" }, React.createElement("p", { className: "curator-similarity-reason" }, item.evidence.join(" · ")), item.appeal !== null && React.createElement("small", null, `Appeal ${item.appeal.toFixed(2)} · confidence ${item.confidence.toFixed(2)}`)),
            React.createElement("div", { className: "curator-prune-actions" }, React.createElement(Button, { size: "sm", variant: item.tagged ? "secondary" : "danger", onClick: () => tag([item.scene_id], !item.tagged) }, item.tagged ? `Undo ${data.tag_name}` : `Tag ${data.tag_name}`), !item.tagged && item.suspect && !item.explicit && React.createElement(Button, { size: "sm", variant: "link", onClick: () => dismiss(item.scene_id) }, "Dismiss"))
          );
        })
      ),
      data && data.total > data.page_size && React.createElement("nav", { className: "curator-prune-pager", "aria-label": "Prune pages" }, React.createElement(Button, { size: "sm", disabled: page === 1, onClick: () => setPage((value) => value - 1) }, "Previous"), React.createElement("span", null, `Page ${page} of ${Math.ceil(data.total / data.page_size)}`), React.createElement(Button, { size: "sm", disabled: page * data.page_size >= data.total, onClick: () => setPage((value) => value + 1) }, "Next"))
    );
  }

  function ExpandPanel({ initialPerformerId = null }) {
    const [entityType, setEntityType] = React.useState("scene");
    const [sort, setSort] = React.useState("match");
    const [performerId, setPerformerId] = React.useState(initialPerformerId);
    const [data, setData] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState("");
    const [message, setMessage] = React.useState("");
    const [version, setVersion] = React.useState(0);
    React.useEffect(() => {
      let active = true;
      setLoading(true);
      operation(entityType === "shortlist" ? { operation: "get_shortlist" } : { operation: "get_expand", entity_type: entityType, sort, performer_id: performerId }).then(
        (result) => active && (setData(result), setLoading(false)),
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => { active = false; };
    }, [entityType, sort, performerId, version]);
    async function refresh() {
      try {
        const id = await runTask("Refresh Expand cache");
        setMessage(`Started Stash job ${id}. Progress is available in Tasks.`);
      } catch (failure) { setError(failure.message); }
    }
    function showPerformerScenes(id) {
      setEntityType("scene");
      setPerformerId(id);
    }
    async function shortlist(item, kind) {
      try {
        await operation({ operation: "update_shortlist", entity_type: kind, external_id: item.id, selected: !item.shortlisted });
        setVersion((value) => value + 1);
      } catch (failure) { setError(failure.message); }
    }
    async function sendWhisparr(id) {
      try {
        const result = await operation({ operation: "send_whisparr", external_id: id });
        setMessage(result.status === "already_exists" ? "Already in Whisparr." : "Sent to Whisparr.");
      } catch (failure) { setError(failure.message); }
    }
    return React.createElement(
      "section",
      { className: "curator-expand" },
      React.createElement(
        "div",
        { className: "curator-expand-toolbar" },
        React.createElement("div", { className: "btn-group", role: "group", "aria-label": "Expand result type" }, [["scene", "Scenes"], ["performer", "Performers"], ["shortlist", "Shortlist"]].map(([value, label]) => React.createElement(Button, { key: value, size: "sm", variant: entityType === value ? "primary" : "secondary", onClick: () => (setEntityType(value), setPerformerId(null)) }, label))),
        entityType === "scene" && React.createElement("select", { className: "form-control form-control-sm curator-expand-sort", value: sort, onChange: (event) => setSort(event.target.value), "aria-label": "Sort Expand results" }, React.createElement("option", { value: "match" }, "Best match"), React.createElement("option", { value: "newest" }, "Newest")),
        performerId && React.createElement(Button, { size: "sm", variant: "link", onClick: () => setPerformerId(null) }, "Clear performer filter"),
        React.createElement(Button, { className: "curator-icon-button", size: "sm", title: "Refresh the bounded StashDB candidate cache in a background task.", "aria-label": "Refresh Expand cache", onClick: refresh }, React.createElement(FontAwesomeIcon, { icon: faSync })),
        data?.fetched_at_ms && React.createElement("small", null, `${Date.now() > data.expires_at_ms ? "Stale · " : ""}Updated ${new Date(data.fetched_at_ms).toLocaleString()}`)
      ),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Loading Expand cache…"), React.createElement("div", { className: "curator-progress", "aria-hidden": "true" })),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      message && React.createElement("p", { role: "status" }, message),
      data && !data.ready && React.createElement("div", { className: "alert alert-info" }, "Expand has not been prepared yet. Use refresh to collect candidates from StashDB."),
      data?.ready && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No external candidates match these filters."),
      data?.ready && React.createElement(
        "div",
        { className: "curator-grid curator-external-grid" },
        data.items.map((item) => {
          const payload = item.payload;
          const kind = entityType === "shortlist" ? item.entity_type : entityType;
          const image = payload.images?.find((value) => value.url)?.url;
          const wildcard = item.sources.includes("wildcard");
          const name = payload.title || payload.name || item.id;
          const href = `https://stashdb.org/${kind === "scene" ? "scenes" : "performers"}/${item.id}`;
          const people = kind === "scene" ? (payload.performers || []).map((value) => value.performer.name).join(", ") : "";
          return React.createElement(
            "article",
            { key: item.id, className: "curator-card curator-external-card" },
            wildcard && React.createElement("span", { className: "curator-wildcard-badge", title: "Popularity wildcard: selected outside preference-derived seeds." }, "Wildcard"),
            image && React.createElement("a", { href, target: "_blank", rel: "noreferrer" }, React.createElement("img", { src: image, loading: "lazy", alt: "" })),
            React.createElement("div", { className: "curator-card-body" }, React.createElement("h3", null, React.createElement("a", { href, target: "_blank", rel: "noreferrer" }, name)), people && React.createElement("p", { className: "curator-external-meta" }, people), payload.studio?.name && React.createElement("p", { className: "curator-external-meta" }, payload.studio.name), payload.why?.length && React.createElement("p", null, `Why: ${payload.why.join(", ")}.`), React.createElement("small", null, `Match ${item.score.toFixed(2)} · via ${item.sources.join(", ")}`)),
            React.createElement("div", { className: "curator-prune-actions" }, React.createElement("a", { className: "btn btn-secondary btn-sm", href, target: "_blank", rel: "noreferrer" }, "Open StashDB"), React.createElement(Button, { size: "sm", title: "Copy the StashDB ID", onClick: () => navigator.clipboard.writeText(item.id) }, "Copy ID"), React.createElement(Button, { size: "sm", onClick: () => shortlist(item, kind) }, item.shortlisted ? "Remove shortlist" : "Shortlist"), kind === "performer" && React.createElement(Button, { size: "sm", onClick: () => showPerformerScenes(item.id) }, "Show scenes"), kind === "scene" && React.createElement(Button, { size: "sm", variant: "primary", title: "Send this scene to the configured Whisparr v3 instance.", onClick: () => sendWhisparr(item.id) }, "Send to Whisparr"))
          );
        })
      )
    );
  }

  function CuratorControls({ onRefresh }) {
    const [jobs, setJobs] = React.useState([]);
    const [health, setHealth] = React.useState(null);
    const [message, setMessage] = React.useState("");

    async function refreshStatus() {
      try {
        const [currentHealth, jobStatus] = await Promise.all([
          operation({ operation: "health" }),
          operation({ operation: "get_job_status" }),
        ]);
        setHealth(currentHealth);
        if (cachedModelId && currentHealth.model_id !== cachedModelId) {
          clearSlateCache();
          onRefresh();
        }
        setJobs(jobStatus.jobs);
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
    const running = health?.active_job ? jobs.find((job) => job.state === "running") : null;
    const latestModelSuccess = jobs.find(
      (job) => job.state === "complete"
        && ["sync-build", "full-sync-build", "build", "update-model"].includes(job.job_type)
        && job.summary?.model_id
    );
    const lastError = jobs.find(
      (job) => job.state === "failed"
        && ["sync-build", "full-sync-build"].includes(job.job_type)
        && job.finished_at_ms > (health?.last_sync_at_ms || 0)
        && job.finished_at_ms > (latestModelSuccess?.finished_at_ms || 0)
    );
    const hasSynced = Boolean(health?.last_sync_at_ms);
    const modelStatus = health?.model_rebuilding
      ? "Rebuilding"
      : health?.model_pending
        ? `${health.model_pending_events} waiting`
        : health?.ready
          ? "Ready"
          : "Not built";
    const activeJob = health?.active_job;
    const progress = typeof activeJob?.progress === "number" ? activeJob.progress : null;

    return React.createElement(
      "section",
      { className: "curator-controls" },
      React.createElement(
        "div",
        { className: "curator-status", role: "status" },
        React.createElement("span", { title: running ? `Running ${running.job_type}` : hasSynced ? "Library synchronized" : "Library has not been synchronized" }, React.createElement(FontAwesomeIcon, { icon: faDatabase }), running ? "Running" : hasSynced ? "Synced" : "Not synced"),
        React.createElement("span", { title: health?.model_pending ? "Playback and feedback are batched before rebuilding the preference model." : modelStatus }, React.createElement(FontAwesomeIcon, { icon: health?.model_pending ? faClock : health?.ready ? faCheckCircle : faWrench }), modelStatus),
        React.createElement("span", { title: "Playback sessions captured by Curator" }, React.createElement(FontAwesomeIcon, { icon: faPlay }), health?.capture?.direct_playback_sessions || 0),
        health?.last_sync_at_ms && React.createElement("span", { title: `Last sync ${new Date(health.last_sync_at_ms).toLocaleString()}` }, React.createElement(FontAwesomeIcon, { icon: faClock }), new Date(health.last_sync_at_ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))
      ),
      activeJob &&
        React.createElement(
          "div",
          { className: "curator-active-job" },
          React.createElement("span", null, activeJob.description),
          progress !== null && React.createElement("strong", null, `${Math.round(progress * 100)}%`),
          React.createElement("div", { className: "curator-job-progress" }, React.createElement("span", { style: { width: `${Math.round((progress || 0) * 100)}%` } })),
          React.createElement(NavLink, { to: "/settings?tab=tasks" }, "View tasks")
        ),
      React.createElement(
        "div",
        { className: "curator-task-buttons" },
        React.createElement(Button, { className: "curator-icon-button", size: "sm", title: "Sync library: fetch changed Stash metadata and refresh recommendations.", "aria-label": "Sync library", onClick: () => start("Sync and build recommendations") }, React.createElement(FontAwesomeIcon, { icon: faSync })),
        React.createElement(Button, { className: "curator-icon-button", size: "sm", title: "Rebuild model from the existing synchronized data.", "aria-label": "Rebuild model", onClick: () => start("Rebuild recommendation model") }, React.createElement(FontAwesomeIcon, { icon: faWrench })),
        React.createElement(NavLink, { className: "btn btn-secondary btn-sm curator-icon-button", title: "Open Curator's plugin settings.", "aria-label": "Plugin settings", to: "/settings?tab=plugins" }, React.createElement(FontAwesomeIcon, { icon: faCog }))
      ),
      lastError && React.createElement("small", { className: "text-danger" }, lastError.error),
      message && React.createElement("p", { role: "status" }, message)
    );
  }

  function CuratorPage() {
    const route = new URLSearchParams(location.search);
    const requestedView = route.get("view") || "for_you";
    const loadingComponents = Api.hooks.useLoadComponents([Api.loadableComponents.SceneCard, Api.loadableComponents.PerformerCard]);
    const [lane, setLane] = React.useState(() => NAV_ITEMS.some((item) => item.value === requestedView) ? requestedView : "for_you");
    const [slate, setSlate] = React.useState(null);
    const [error, setError] = React.useState("");
    const [loading, setLoading] = React.useState(true);
    const [refreshKey, setRefreshKey] = React.useState(0);

    React.useEffect(() => {
      let active = true;
      if (!laneByValue.has(lane)) {
        setSlate(null);
        setLoading(false);
        setError("");
        return () => { active = false; };
      }
      const cached = slateCache.get(slateKey(lane));
      setSlate(cached || null);
      setLoading(!cached);
      setError("");
      loadSlate(lane).then(
        (data) => {
          if (!active) return;
          setSlate(data);
          setLoading(false);
          prefetchLanes(lane);
        },
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => {
        active = false;
      };
    }, [lane, refreshKey]);

    const laneOption = NAV_ITEMS.find((option) => option.value === lane);

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
      operation({ operation: "replace_item", lane, exploration: 0, exclude_scene_ids: excluded }).then(
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
        React.createElement("div", { className: "curator-brand" }, React.createElement("h1", null, "Stash Curator"), React.createElement("p", { className: "curator-tagline" }, "Navigate your library, guided by your taste.")),
        React.createElement(
          Nav,
          { variant: "tabs", role: "tablist", className: "curator-tabs" },
          NAV_ITEMS.map((option) =>
            React.createElement(
              Nav.Link,
              { key: option.value, as: "button", className: `curator-lane-${option.value}`, active: lane === option.value, onClick: () => setLane(option.value), role: "tab", title: option.description, "aria-label": `${option.label}: ${option.description}`, "aria-selected": lane === option.value },
              React.createElement(FontAwesomeIcon, { icon: option.icon }),
              React.createElement("span", null, option.label)
            )
          )
        ),
        React.createElement(CuratorControls, { onRefresh: refresh })
      ),
      lane === "similar" && !loadingComponents && React.createElement(SimilarityPanel, { initialType: route.get("type") || "scene", initialId: route.get("id"), initialLabel: route.get("label") }),
      lane === "prune" && !loadingComponents && React.createElement(PrunePanel),
      lane === "expand" && React.createElement(ExpandPanel, { initialPerformerId: route.get("performer") }),
      (loading || loadingComponents || scenesQuery.loading) &&
        React.createElement(
          "div",
          { className: "curator-loading", role: "status" },
          React.createElement("span", null, loading ? `Preparing ${laneOption?.label || "recommendations"}…` : "Loading scene cards…"),
          React.createElement("div", { className: "curator-progress", "aria-hidden": "true" })
        ),
      error && React.createElement("div", { className: "alert alert-danger" }, error, React.createElement("p", null, "Run “Sync and build recommendations” from Tasks if no model exists yet.")),
      scenesQuery.error && React.createElement("div", { className: "alert alert-danger" }, scenesQuery.error.message),
      laneByValue.has(lane) && slate && !loading &&
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
        clearSlateCache();
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
  function CuratorContextLink({ type, id, label }) {
    const query = new URLSearchParams({ view: "similar", type, id: String(id), label: label || "" });
    return React.createElement(NavLink, { className: "btn btn-primary curator-context-link", to: `/plugins/stash-curator?${query}`, title: `Find similar ${type}s with Curator` }, React.createElement(FontAwesomeIcon, { icon: faSearch }), ` Similar ${type}s`);
  }
  Api.patch.after("ScenePage", function (props, _, result) {
    return React.createElement(React.Fragment, null, result, React.createElement(CuratorContextLink, { type: "scene", id: props.scene.id, label: props.scene.title || `Scene ${props.scene.id}` }));
  });
  Api.patch.after("PerformerPage", function (props, _, result) {
    return React.createElement(React.Fragment, null, result, React.createElement(CuratorContextLink, { type: "performer", id: props.performer.id, label: props.performer.name || `Performer ${props.performer.id}` }));
  });
  Api.Event.addEventListener("stash:location", (event) => {
    attachPlayer(event.detail.data.location.pathname);
    flushQueue();
  });
  window.addEventListener("online", flushQueue);
  window.addEventListener("pagehide", () => finishTracker(false));
  attachPlayer(location.pathname);
  flushQueue();
  function scheduleModelMaintenance() {
    operation({ operation: "health" })
      .then((health) => {
        if (health.model_update_ready && !health.model_rebuilding) {
          return runTask("Apply recent Curator feedback");
        }
        return null;
      })
      .catch(() => {});
  }
  scheduleModelMaintenance();
  setInterval(scheduleModelMaintenance, 15 * 60 * 1000);
})();
