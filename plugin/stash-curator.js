(function () {
  "use strict";

  // ponytail: Stash re-evaluates plugin scripts after cache resets; hard refresh loads updates.
  if (window.__stashCuratorPluginLoaded) return;
  window.__stashCuratorPluginLoaded = true;

  const Api = window.PluginApi;
  const { React, ReactDOM, GQL, libraries } = Api;
  const { Button, ButtonGroup, Nav } = libraries.Bootstrap;
  const { NavLink, useHistory, useLocation } = libraries.ReactRouterDOM;
  const { FontAwesomeIcon } = libraries.ReactFontAwesome;
  const { faBalanceScale, faBed, faBroom, faBullseye, faChartLine, faCheckCircle, faCircleQuestion, faClock, faClone, faCog, faCompass, faCopy, faCrosshairs, faDatabase, faDice, faDownload, faExpandArrowsAlt, faExternalLinkAlt, faEyeSlash, faFilm, faFilter, faGlobe, faHeart, faHistory, faList, faMoon, faPlay, faPlayCircle, faSearch, faSortAmountDown, faStar, faSun, faSync, faTag, faThLarge, faThumbsDown, faThumbsUp, faUser, faVenus, faWrench, faXmark } = libraries.FontAwesomeSolid;
  const componentTransforms = window.StashCuratorComponentTransforms ||= {};

  function transformComponentProps(name, props) {
    return (componentTransforms[name] || []).reduce((value, transform) => transform(value), props);
  }
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
      value: "stretch",
      label: "Stretch",
      icon: faExpandArrowsAlt,
      description: "Mostly your taste, with one boundary gently challenged to find something new.",
    },
    {
      value: "blind_spots",
      label: "Blind Spots",
      icon: faEyeSlash,
      description: "Corroborated dark corners of your library — studios or tags you barely watch, worth teaching the model about.",
    },
    {
      value: "dormant",
      label: "Dormant",
      icon: faBed,
      description: "A performer, studio, or tag you used to watch a lot, parked for a while.",
    },
  ];
  const NAV_ITEMS = [
    ...LANES,
    {
      value: "curate",
      label: "Curate",
      icon: faBullseye,
      description: "Compare scenes, rate tags, and see how your feedback changes recommendations.",
    },
    {
      value: "expand",
      label: "Expand",
      icon: faGlobe,
      description: "Discover scenes and performers on Stash-box, ranked using your preferences.",
    },
    {
      value: "similar",
      label: "Similar",
      icon: faClone,
      description: "Preference-aware matches from your library or Stash-box.",
    },
    {
      value: "hunt",
      label: "Performer Hunt",
      icon: faCrosshairs,
      description: "Stash-box performers and their scenes, checked against your library.",
    },
    {
      value: "feedback",
      label: "Feedback history",
      icon: faThumbsUp,
      maintenance: true,
      description: "Review recent feedback, undo mistakes, or replace an action without rewriting history.",
    },
    {
      value: "history",
      label: "Recently recommended",
      icon: faHistory,
      maintenance: true,
      description: "Revisit recommendations you viewed, with the reasons recorded at the time.",
    },
    {
      value: "sentiment",
      label: "Sentiment review",
      icon: faBalanceScale,
      maintenance: true,
      description: "Review the model's sentiment estimates: least-appealing scenes first, with reasons and feedback on each card.",
    },
    {
      value: "prune",
      label: "Prune",
      icon: faBroom,
      maintenance: true,
      description: "Curator never deletes media; tagging is reversible, and Candidates, Explicit dislikes, and Model suspects are separate review queues.",
    },
    {
      value: "backups",
      label: "Backups",
      icon: faDatabase,
      maintenance: true,
      description: "Create, inspect, and safely restore Curator sidecar backups.",
    },
    {
      value: "tasks",
      label: "Tasks",
      icon: faList,
      maintenance: true,
      description: "Live status of background Curator jobs: queue position, progress, and results.",
    },
    {
      value: "diagnostics",
      label: "Diagnostics",
      icon: faWrench,
      maintenance: true,
      description: "Preview and export a privacy-safe status report for bug reports.",
    },
    {
      value: "settings",
      label: "Settings",
      icon: faCog,
      maintenance: true,
      description: "Sync, discovery, prune, and Whisparr integration settings, without leaving Curator.",
    },
    {
      value: "profiling",
      label: "Profiling",
      icon: faChartLine,
      maintenance: true,
      description: "Inspect render and query performance profiles captured during development.",
    },
  ];
  const PRIMARY_NAV_ITEMS = NAV_ITEMS.filter((item) => !item.maintenance);
  const MAINTENANCE_ITEMS = NAV_ITEMS.filter((item) => item.maintenance);
  const laneByValue = new Map(LANES.map((lane) => [lane.value, lane]));
  const RECOMMENDATIONS_NAV_ITEM = {
    value: "recommendations",
    label: "Recommendations",
    icon: faStar,
    description: "Strong matches, timely revisits, and discovery across six recommendation lanes.",
  };
  const MANAGE_NAV_ITEM = {
    value: "manage",
    label: "Manage",
    icon: faWrench,
    description: "Feedback history, recent recommendations, sentiment review, prune queues, backups, tasks, diagnostics, settings, and profiling.",
  };
  // Find groups the three "find new content" surfaces (Similar, Expand,
  // Performer Hunt) under one primary nav item with inner tabs (issue #192).
  // The inner surfaces keep their own URL ?view= lanes and filter state, so
  // old bookmarks and per-surface state still work; the wrapper is pure nav.
  const FIND_NAV_ITEM = {
    value: "find",
    label: "Find",
    icon: faSearch,
    description: "Find similar scenes in your library, discover Stash-box releases, and browse performer catalogs.",
  };
  const FIND_SECTIONS = NAV_ITEMS.filter(
    (item) => item.value === "similar" || item.value === "expand" || item.value === "hunt"
  );
  const FIND_SECTION_VALUES = new Set(FIND_SECTIONS.map((item) => item.value));
  // Curate's own sections. Before this split the view offered "Random round"
  // and "Pick-test a hypothesis" side by side, which are the same activity with
  // a different pair-selection filter — presenting a selection policy as if it
  // were a mode is what made "which one do I use?" unanswerable. These are
  // Curate's own sections. Before the split the view offered "Random round"
  // and "Pick-test a hypothesis" side by side, which are the same activity
  // with a different pair-selection filter — presenting a selection policy as
  // if it were a mode is what made "which one do I use?" unanswerable. The
  // "Test an idea" section (a tag-focused pair filter on the same stream
  // machinery) was dropped as a distinct surface (issue #191): Stream already
  // covers pair comparison. Tag sentiment is a real section here (issue
  // #241): direct tag teaching lives under Curate, not Manage. Section URL
  // values stay stable (stream / sentiment / progress) so old links keep
  // working; only labels and order changed.
  const CURATE_SECTIONS = [
    {
      value: "stream",
      label: "Pair picks",
      icon: faBullseye,
      description: "Endless two-scene comparisons; every pick teaches the model.",
    },
    {
      value: "sentiment",
      label: "Tag sentiment",
      icon: faTag,
      description: "Tell Curator how you feel about a tag directly.",
    },
    {
      value: "progress",
      label: "Impact",
      icon: faChartLine,
      description: "What your curation added up to, and what the model build moved.",
    },
  ];
  const TOP_NAV_ITEMS = [
    RECOMMENDATIONS_NAV_ITEM,
    FIND_NAV_ITEM,
    ...PRIMARY_NAV_ITEMS.filter((item) => !laneByValue.has(item.value) && !FIND_SECTION_VALUES.has(item.value)),
  ];
  const EVENT_QUEUE_KEY = "stash-curator:event-queue:v1";
  const THEME_STORAGE_KEY = "stash-curator:theme";
  const WALL_STORAGE_KEY = "stash-curator:preview-wall:v1";
  const WALL_CAP = 20;
  const RECOMMENDATION_VIEW_KEY = "stash-curator:recommendation-view:v1";
  const FIND_VIEW_KEY = "stash-curator:find-view:v1";
  const ROULETTE_ANIMATION_KEY = "stash-curator:roulette-animation:v1";
  let rouletteAnimationEnabled = true;
  try { rouletteAnimationEnabled = localStorage.getItem(ROULETTE_ANIMATION_KEY) !== "false"; } catch (_) {}
  function useRouletteAnimation() {
    const [enabled, setEnabled] = React.useState(rouletteAnimationEnabled);
    React.useEffect(() => {
      const update = (event) => {
        if (event.type === "storage") {
          if (event.key !== ROULETTE_ANIMATION_KEY && event.key !== null) return;
          rouletteAnimationEnabled = event.newValue !== "false";
        }
        setEnabled(rouletteAnimationEnabled);
      };
      window.addEventListener(ROULETTE_ANIMATION_KEY, update);
      window.addEventListener("storage", update);
      return () => { window.removeEventListener(ROULETTE_ANIMATION_KEY, update); window.removeEventListener("storage", update); };
    }, []);
    function change(value) {
      rouletteAnimationEnabled = value;
      try { localStorage.setItem(ROULETTE_ANIMATION_KEY, String(value)); } catch (_) {}
      window.dispatchEvent(new Event(ROULETTE_ANIMATION_KEY));
    }
    return [enabled, change];
  }
  function useFindView() {
    const [view, setView] = React.useState(() => {
      try { return window.localStorage.getItem(FIND_VIEW_KEY) === "thumbnails" ? "thumbnails" : "cards"; }
      catch { return "cards"; }
    });
    function changeView(value) {
      setView(value);
      try { window.localStorage.setItem(FIND_VIEW_KEY, value); } catch {}
    }
    return [view, changeView];
  }
  function readRecommendationView() {
    try {
      const value = window.localStorage.getItem(RECOMMENDATION_VIEW_KEY);
      if (["cards", "thumbnails", "wall"].includes(value)) return value;
    } catch {}
    return readWallMode() ? "wall" : "cards";
  }
  function writeRecommendationView(value) {
    try {
      window.localStorage.setItem(RECOMMENDATION_VIEW_KEY, value);
    } catch {
      // Storage can be unavailable; the selection still works for this session.
    }
  }
  function readWallMode() {
    try {
      return window.localStorage.getItem(WALL_STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  }
  function writeWallMode(value) {
    try {
      window.localStorage.setItem(WALL_STORAGE_KEY, value ? "1" : "0");
    } catch {
      // localStorage can be unavailable (private browsing); the toggle
      // still works for the session, it just won't persist.
    }
  }
  const CARD_SIZE_MIN = 14;
  const CARD_SIZE_MAX = 32;
  const CARD_SIZE_DEFAULT = 22;
  const TAG_PREFERENCE_QUEUE_KEY = "stash-curator:tag-preference-queue:v1";
  const ORIGIN_KEY = "stash-curator:origin:v1";
  const LANE_PLAYLIST_KEY = "stash-curator:lane-playlist:v1";
  let lanePlaylist = readLanePlaylist();
  let lanePlaylistPending = false;
  let lanePlaylistError = "";
  const lanePlaylistListeners = new Set();
  const SLATE_CACHE_KEY = "stash-curator:slates:v2";
  const ROTATION_KEY = "stash-curator:rotation:v2";
  const RELOAD_ROTATION_KEY = "stash-curator:recommendation-reloads:v1";
  const FILTER_PRESETS_KEY = "stash-curator:filter-presets:v1";
  const WHISPARR_LOGO = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAACXBIWXMAAAAyAAAAMgFOp+RzAAAAGXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAxZJREFUOI1tk0tMXHUYxX///713HjDMXB4zpdBBgVKSVobWQY10WGCsSVsTJxqbNF1pNy5cSWJ07cYmbeLapUl9JCbqommiLvoAKZA2pdQSmcnQQQp1nlCY6czc/73XRYXQxLM+38n3fecckUwm2YsHd5YTVsO6aFluTBOGBgLbbdiGIeallBNDrx78Yy9f7AikUilPtcgNlDfe1zqmD4ZO49WCAFTtEumNq6TLk0p6G7fa9vveiEaj1q5AKpXyVApkw97B8PHOCU0Ijf+D41pMrV+y8/WlfO/hSNQ0TSUBqkVuhL2D4cT+TzUhNBwUj6ozpDaucL/w/a6AFAZjXZ9pHd5D4Wy68DuA5lS9CadmfH6i5wtdCMHy1jUqao3uptfwG+3k64t0Nh19bpOeltfl6tbtrkwmm5HKUhf62hK6cqsslL6ju2mEaPMYQmgsln/msPkua5UZpta+wsV59jg0cByPYfCRtCyOvRBIsFD8kSOtZ/BoLQAsb/1GtOUVstvXmX18mWORcwgkAKuVafpD4yjLjUuJ0BZLvxBrP4sUOgCl+hK2bbNZ/xvbUYx2nadJDwNQUTkeby/QF3wT15YeiXSc7sBRNGmQq91jW62T3ZxESJdoYBQERPzDACjnKfO5b4mFz/13Cq4UQlil2gq56n1Mo5f5/A+EfAfoD54kvfkrh8y3AbDdOnfzl4nv+wCPbKaqyqA7DSkk92wsIv4h5v75mg5/L33Bt6jZRVp9vUh0LGeLu4VveCn8Hl4tBED6yVV0XdzR0fjkYXlmSrpSN309DJrvAPDEWiWgR1itTFO3N3i540N2Aua4ikx5Ugk/E3J4ZGBW91uT5UbGPtL2/q7XEV8MhGCff4j+4En2pnNq/ZItjPqtWHxgTgJEBzpOlOorheuPvrRdV+3UhJDxIoYM7A66KG6uXbBztb8KmfU/xwF0ANM01Ur+2gHZKW/+lP54pL/tuH4wdIpmvf1ZmVSRpc0rPNyYVsJozKzkH4wnk0n1XBt3sDCbHrUd96KtGBauMAAX4SrN4LbQmYjFB+b28v8FOo1CLH194s4AAAAASUVORK5CYII=";
  const similarityCache = new Map();
  // Stale similarity results must never outlive a code change: entries expire
  // after this TTL even if the page stays open, and the cache key is stamped
  // with the backend code hash so any plugin update busts it immediately.
  const SIMILARITY_CACHE_TTL_MS = 5 * 60 * 1000;
  const restoredCache = readSlateCache();
  const rotation = readRotation();
  const laneExclusions = new Map(restoredCache.exclusions.map(([lane, ids]) => [lane, new Set(ids)]));
  const slateCache = new Map(restoredCache.entries);
  const slateRequests = new Map();
  let cachedModelId = restoredCache.modelId;
  let cachedConfigUpdatedAtMs = restoredCache.configUpdatedAtMs;
  let cacheGeneration = 0;
  let modelUpdateTimer = null;
  let playSyncTimer = null;
  const localActivities = new Map();
  const activityListeners = new Set();

  function notifyActivities() {
    const snapshot = [...localActivities.values()];
    activityListeners.forEach((listener) => listener(snapshot));
  }

  function setLocalActivity(key, active, label) {
    if (active) localActivities.set(key, { key, label });
    else localActivities.delete(key);
    notifyActivities();
  }

  function useCuratorActivity(key, active, label) {
    React.useEffect(() => {
      setLocalActivity(key, active, label);
      return () => setLocalActivity(key, false, label);
    }, [key, active, label]);
  }

  function useLocalActivities() {
    const [activities, setActivities] = React.useState(() => [...localActivities.values()]);
    React.useEffect(() => {
      activityListeners.add(setActivities);
      return () => activityListeners.delete(setActivities);
    }, []);
    return activities;
  }

  function uuid() {
    return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  }

  // actionError adds an actionable hint to SQLite busy/lock failures (#109):
  // the working sidecar must live on local storage, not a network share.
  function actionError(message) {
    const text = String(message || "");
    if (/database is locked|database is busy|SQLITE_BUSY/i.test(text)) {
      return `${text} — Curator could not access its database. If this repeats, move the Sidecar database path to local storage and keep backups on the network share (plugin settings).`;
    }
    return text;
  }

  async function operation(args, timeoutMs = args.operation === "get_expand" ? 120000 : 30000) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
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
      error.message = actionError(error.message);
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function slateKey(lane, page = 1) {
    return `${cachedConfigUpdatedAtMs || 0}:${lane}:${page}`;
  }

  function readLanePlaylist() {
    try {
      const value = JSON.parse(sessionStorage.getItem(LANE_PLAYLIST_KEY) || "null");
      if (value && typeof value.id === "string" && laneByValue.has(value.lane) && value.request && Array.isArray(value.request.exclude_scene_ids) && Array.isArray(value.items) && value.items.length && value.items.every((item) => /^\d+$/.test(item.scene_id)) && Number.isInteger(value.index) && value.index >= 0 && value.index < value.items.length) return value;
    } catch (_) { /* An unavailable or stale queue must not affect ordinary playback. */ }
    return null;
  }
  function activeLanePlaylist(sceneId) {
    return lanePlaylist && location.pathname === `/scenes/${sceneId}` && new URLSearchParams(location.search).get("curator_playlist") === lanePlaylist.id && String(lanePlaylist.items[lanePlaylist.index].scene_id) === String(sceneId) ? lanePlaylist : null;
  }
  function notifyLanePlaylist() {
    lanePlaylistListeners.forEach((listener) => listener());
  }
  function saveLanePlaylist(value) {
    if (value) sessionStorage.setItem(LANE_PLAYLIST_KEY, JSON.stringify(value));
    else sessionStorage.removeItem(LANE_PLAYLIST_KEY);
    lanePlaylist = value;
    notifyLanePlaylist();
  }
  function playlistOrigins(slate, items) {
    return items.map((item) => ({ scene_id: String(item.scene_id), impression_id: item.impression_id || slate.impression_id, lane: slate.lane, impression_position: item.position, model_id: slate.model_id }));
  }
  function openPlaylistScene(playlist, history) {
    const origin = playlist.items[playlist.index];
    sessionStorage.setItem(ORIGIN_KEY, JSON.stringify(origin));
    saveLanePlaylist(playlist);
    const search = new URLSearchParams({ curator_playlist: playlist.id, autoplay: "true", continue: "false" });
    history.push(`/scenes/${origin.scene_id}?${search}`);
  }
  function createLanePlaylist(slate, items, filters) {
    const draw = rotationLane(slate.lane);
    const playlist = {
      id: uuid(), lane: slate.lane, index: 0, items: playlistOrigins(slate, items), finished: false,
      request: {
        lane: slate.lane, page: 1, count: slate.page_size, exploration: 0,
        mood_id: readMoodID(), together_mode: readTogetherMode(),
        draw_seed: draw.seed, draw_at_ms: draw.atMs,
        exclude_scene_ids: [...(laneExclusions.get(slate.lane) || [])],
        include_tags: (filters.includeTags || []).map((item) => item.name),
        exclude_tags: (filters.excludeTags || []).map((item) => item.name),
        performer_ids: (filters.performers || []).map((item) => String(item.id)),
        studio_ids: (filters.studios || []).map((item) => String(item.id)), gender: filters.gender || "",
      },
    };
    return playlist;
  }
  function startLanePlaylist(slate, items, filters, history) {
    if (!items.length) return;
    const playlist = createLanePlaylist(slate, items, filters);
    lanePlaylistError = "";
    openPlaylistScene(playlist, history);
  }
  async function existingPlaylistSceneIDs(items) {
    // findScene returns null for deleted entries; findScenes(scene_ids) rejects the batch.
    const declarations = items.map((_, index) => `$s${index}: ID!`).join(", ");
    const fields = items.map((_, index) => `s${index}: findScene(id: $s${index}) { id }`).join(" ");
    const response = await fetch("/graphql", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: `query PlaylistScenes(${declarations}) { ${fields} }`, variables: Object.fromEntries(items.map((item, index) => [`s${index}`, String(item.scene_id)])) }),
    });
    const result = await response.json();
    if (!response.ok || result.errors?.length) throw new Error(result.errors?.map((error) => error.message).join("; ") || "Could not load the next playlist scenes.");
    if (!result.data || Object.keys(result.data).length !== items.length) throw new Error("Could not load the next playlist scenes.");
    return new Set(Object.values(result.data).filter(Boolean).map((scene) => String(scene.id)));
  }
  async function nextLanePlaylist(sceneId, history) {
    const current = activeLanePlaylist(sceneId);
    if (!current || current.finished || lanePlaylistPending) return;
    lanePlaylistPending = true;
    lanePlaylistError = "";
    notifyLanePlaylist();
    try {
      let items = current.items;
      const excluded = new Set([...current.request.exclude_scene_ids.map(String), ...items.map((item) => item.scene_id)]);
      let verified = null;
      // Restart at page one after exclusions; advancing the page would skip unplayed picks.
      while (true) {
        if (current.index + 1 >= items.length) {
          const slate = await operation({ ...current.request, operation: "get_slate", exclude_scene_ids: [...excluded], context: { route: location.pathname, playlist: true } });
          if (activeLanePlaylist(sceneId) !== current) return;
          const candidates = slate.items.filter((item) => !excluded.has(String(item.scene_id)));
          if (!candidates.length) {
            saveLanePlaylist({ ...current, finished: true });
            return;
          }
          verified = await existingPlaylistSceneIDs(candidates);
          if (activeLanePlaylist(sceneId) !== current) return;
          candidates.forEach((item) => excluded.add(String(item.scene_id)));
          items = [...items, ...playlistOrigins(slate, candidates.filter((item) => verified.has(String(item.scene_id))))];
          continue;
        }
        const nextItem = items[current.index + 1];
        const existing = verified || await existingPlaylistSceneIDs([nextItem]);
        if (activeLanePlaylist(sceneId) !== current) return;
        if (existing.has(nextItem.scene_id)) break;
        items = items.filter((_, index) => index !== current.index + 1);
      }
      if (activeLanePlaylist(sceneId) !== current) return;
      const next = { ...current, index: current.index + 1, items, request: { ...current.request, exclude_scene_ids: [...excluded] } };
      openPlaylistScene(next, history);
    } catch (failure) {
      if (activeLanePlaylist(sceneId) === current) lanePlaylistError = failure.message;
    } finally {
      lanePlaylistPending = false;
      notifyLanePlaylist();
    }
  }

  function LanePlaylistControls({ sceneId }) {
    const history = useHistory();
    const [, update] = React.useState(0);
    const [host, setHost] = React.useState(null);
    React.useEffect(() => {
      const listener = () => update((value) => value + 1);
      lanePlaylistListeners.add(listener);
      return () => lanePlaylistListeners.delete(listener);
    }, []);
    React.useEffect(() => { setHost(document.querySelector(".scene-tabs .scene-toolbar")); }, [sceneId]);
    const playlist = activeLanePlaylist(sceneId);
    if (!playlist) return null;
    const content = React.createElement("div", { className: "scene-toolbar-group curator-playlist-controls", "aria-label": "Curator playlist" },
      React.createElement("span", { className: "curator-playlist-status", role: "status" },
        React.createElement(FontAwesomeIcon, { icon: faList, "aria-hidden": "true" }),
        laneByValue.get(playlist.lane).label,
        React.createElement("span", { className: "curator-playlist-count", title: "Position in playlist" }, playlist.index + 1),
        playlist.finished && "End of recommendations"
      ),
      React.createElement(ButtonGroup, { size: "sm", className: "curator-playlist-actions" },
        React.createElement(Button, { className: "curator-playlist-next", variant: "link", disabled: lanePlaylistPending || playlist.finished, "aria-busy": lanePlaylistPending, onClick: () => nextLanePlaylist(sceneId, history), title: "Play the next recommendation from this lane" }, React.createElement(FontAwesomeIcon, { icon: faPlay, "aria-hidden": "true" }), lanePlaylistPending ? "Loading…" : lanePlaylistError ? "Retry next" : "Next"),
        React.createElement(Button, { className: "curator-playlist-stop", variant: "link", title: "Stop playlist", "aria-label": "Stop playlist", onClick: () => { saveLanePlaylist(null); history.replace(`/scenes/${sceneId}`); } }, React.createElement(FontAwesomeIcon, { icon: faXmark, "aria-hidden": "true" }))
      ),
      lanePlaylistError && React.createElement("small", { className: "curator-playlist-error text-danger", role: "alert" }, lanePlaylistError)
    );
    return host ? ReactDOM.createPortal(content, host) : content;
  }
  Api.patch.before("ScenePlayer", function (props, ...args) {
    const history = useHistory();
    return [activeLanePlaylist(props.scene.id) ? { ...props, onNext: () => nextLanePlaylist(props.scene.id, history), onPrevious: undefined } : props, ...args];
  });

  function localDay() {
    const now = new Date();
    return `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;
  }

  function readRotation() {
    try {
      const value = JSON.parse(localStorage.getItem(ROTATION_KEY) || "null");
      if (value && typeof value.day === "string" && value.lanes && typeof value.lanes === "object") return value;
    } catch (_) { /* Browser storage may be unavailable. */ }
    return { day: localDay(), modelId: null, lanes: {} };
  }

  function saveRotation() {
    try { localStorage.setItem(ROTATION_KEY, JSON.stringify(rotation)); }
    catch (_) { /* In-memory rotation still works for this tab. */ }
  }

  function rotationLane(lane) {
    if (!rotation.lanes[lane]) {
      rotation.lanes[lane] = { seed: uuid(), atMs: Date.now() };
      saveRotation();
    }
    return rotation.lanes[lane];
  }

  function rotateDay() {
    const day = localDay();
    if (rotation.day === day) return false;
    Object.values(rotation.lanes).forEach((state) => {
      state.seed = uuid();
      state.atMs = Date.now();
    });
    rotation.day = day;
    saveRotation();
    clearSlateCache();
    return true;
  }

  function advanceRotation(lane) {
    const state = rotationLane(lane);
    state.seed = uuid();
    state.atMs = Date.now();
    saveRotation();
    clearSlateCache();
  }

  function rotateOnRepeatedReload(lane, page) {
    const navigation = window.performance?.getEntriesByType?.("navigation")?.[0];
    const identity = `${localDay()}:${lane}:${page}`;
    let count = 0;
    try {
      const previous = JSON.parse(sessionStorage.getItem(RELOAD_ROTATION_KEY) || "null");
      if (navigation?.type === "reload") {
        count = previous?.identity === identity && Number.isInteger(previous.count) ? previous.count + 1 : 1;
      }
      sessionStorage.setItem(RELOAD_ROTATION_KEY, JSON.stringify({ identity, count }));
    } catch (_) { return false; }
    return page === 1 && count > 0 && count % 2 === 0;
  }

  function readSlateCache() {
    try {
      const value = JSON.parse(sessionStorage.getItem(SLATE_CACHE_KEY) || "null");
      return value && Array.isArray(value.entries)
        ? {
            modelId: value.modelId || null,
            configUpdatedAtMs: Number.isFinite(value.configUpdatedAtMs) ? value.configUpdatedAtMs : null,
            entries: value.entries.filter((entry) => Array.isArray(entry) && entry.length === 2),
            exclusions: Array.isArray(value.exclusions) ? value.exclusions.filter((entry) => Array.isArray(entry) && Array.isArray(entry[1])) : [],
          }
        : { modelId: null, configUpdatedAtMs: null, entries: [], exclusions: [] };
    } catch (_) {
      return { modelId: null, configUpdatedAtMs: null, entries: [], exclusions: [] };
    }
  }

  function persistSlateCache() {
    try {
      sessionStorage.setItem(
        SLATE_CACHE_KEY,
        JSON.stringify({ modelId: cachedModelId, configUpdatedAtMs: cachedConfigUpdatedAtMs, entries: [...slateCache.entries()], exclusions: [...laneExclusions].map(([lane, ids]) => [lane, [...ids]]) })
      );
    } catch (_) {
      // The in-memory cache still works if browser storage is unavailable or full.
    }
  }

  function clearSlateCache(preservePosition = false) {
    if (!preservePosition) clearEndlessCache();
    slateCache.clear();
    slateRequests.clear();
    cachedModelId = null;
    if (preservePosition) persistSlateCache();
    else {
      cachedConfigUpdatedAtMs = null;
      sessionStorage.removeItem(SLATE_CACHE_KEY);
    }
    cacheGeneration += 1;
    similarityCache.clear();
  }

  function writePage(history, routeLocation, param, value, replace = false) {
    const route = new URLSearchParams(routeLocation.search);
    route.set(param, String(Math.max(1, Math.floor(Number(value) || 1))));
    history[replace ? "replace" : "push"]({ pathname: routeLocation.pathname, search: route.toString() });
  }

  function useUrlPage(param) {
    const history = useHistory();
    const routeLocation = useLocation();
    const raw = new URLSearchParams(routeLocation.search).get(param);
    const parsed = Number(raw);
    const page = Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
    React.useEffect(() => {
      if (raw !== null && parsed !== page) writePage(history, routeLocation, param, page, true);
    }, [param, raw, page, routeLocation.pathname, routeLocation.search]);
    return [page, (value, options = {}) => {
      const next = typeof value === "function" ? value(page) : value;
      if (Math.max(1, Math.floor(Number(next) || 1)) !== page || options.replace) {
        writePage(history, routeLocation, param, next, options.replace);
      }
    }];
  }

  // ── URL-backed view state (issue #134) ────────────────────────────────
  // useUrlState makes the URL the full source of truth for a panel's visible
  // result set: every result-affecting field is serialized to query params,
  // re-parsed on back/forward navigation, and re-seeded on remount. Fields
  // absent from the URL fall back to the panel's saved presets / defaults
  // (spec.defaults), exactly as before. User-initiated changes push (so
  // back/forward works); pure recovery writes (clamping, config-derived
  // defaults) use replace() to avoid history spam.
  // spec: {
  //   defaults: { field: value },
  //   fields: { field: { param, parse(search) -> value,
  //                      serialize(value) -> string | "" | {param: string} } },
  //   page: { param(state) -> paramName, parse(raw|null) -> value, serialize(value) -> string|"" },
  //   prune?(route, state),   // optional cleanup of stale params after serialization
  // }
  function parseUrlState(search, spec) {
    const state = { ...spec.defaults };
    for (const [key, field] of Object.entries(spec.fields)) {
      state[key] = field.parse(search);
    }
    if (spec.page) state.page = spec.page.parse(search.get(spec.page.param(state)));
    return state;
  }

  function urlStringField(param, defaultValue, validate = null) {
    return {
      param,
      parse: (search) => {
        const raw = search.get(param);
        if (raw === null || raw === "") return defaultValue;
        return validate && !validate(raw) ? defaultValue : raw;
      },
      serialize: (value) => (value === defaultValue ? "" : String(value)),
    };
  }

  function urlBoolField(param, defaultValue) {
    return {
      param,
      parse: (search) => {
        const raw = search.get(param);
        if (raw === null || raw === "") return defaultValue;
        return raw !== "0";
      },
      serialize: (value) => (value === defaultValue ? "" : value ? "1" : "0"),
    };
  }

  function urlNumberField(param, defaultValue) {
    return {
      param,
      parse: (search) => {
        const raw = search.get(param);
        if (raw === null || raw === "") return defaultValue;
        const parsed = Number(raw);
        return Number.isFinite(parsed) ? parsed : defaultValue;
      },
      serialize: (value) => (value === defaultValue ? "" : String(value)),
    };
  }

  function urlListField(param, defaultValue) {
    return {
      param,
      parse: (search) => {
        const raw = search.get(param);
        if (raw === null || raw === "") return defaultValue;
        try {
          const parsed = JSON.parse(raw);
          if (!Array.isArray(parsed)) return defaultValue;
          return parsed.filter((item) => item && (item.id !== undefined || item.name !== undefined));
        } catch (_) {
          return defaultValue;
        }
      },
      serialize: (value) => (value && value.length ? JSON.stringify(value.map((item) => ({ id: item.id, name: item.name }))) : ""),
    };
  }

  function urlPageSpec(param) {
    return {
      param: typeof param === "function" ? param : () => param,
      parse: (raw) => {
        const parsed = Number(raw);
        return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
      },
      serialize: (value) => (value === 1 ? "" : String(Math.max(1, Math.floor(Number(value) || 1)))),
    };
  }

  function useUrlState(spec) {
    const history = useHistory();
    const routeLocation = useLocation();
    const locationRef = React.useRef(routeLocation);
    React.useEffect(() => {
      locationRef.current = routeLocation;
    }, [routeLocation]);
    const [state, setState] = React.useState(() => parseUrlState(new URLSearchParams(routeLocation.search), spec));
    const stateRef = React.useRef(state);
    stateRef.current = state;
    const appliedSearchRef = React.useRef(routeLocation.search.replace(/^\?/, ""));
    // Re-seed from the URL on back/forward or any external navigation; our own
    // writes stamp appliedSearchRef first, so they are not re-applied here.
    React.useEffect(() => {
      const search = routeLocation.search.replace(/^\?/, "");
      if (search === appliedSearchRef.current) return;
      appliedSearchRef.current = search;
      setState(parseUrlState(new URLSearchParams(search), spec));
    }, [routeLocation.search]);
    function update(updater, options = {}) {
      const next = typeof updater === "function" ? updater(stateRef.current) : updater;
      const location = locationRef.current;
      const route = new URLSearchParams(appliedSearchRef.current);
      for (const [key, field] of Object.entries(spec.fields)) {
        const serialized = field.serialize(next[key]);
        if (serialized === null || serialized === undefined || serialized === "") {
          route.delete(field.param);
        } else if (typeof serialized === "object") {
          for (const [param, value] of Object.entries(serialized)) {
            if (value === null || value === undefined || value === "") route.delete(param);
            else route.set(param, value);
          }
        } else {
          route.set(field.param, serialized);
        }
      }
      const pageValue = spec.page.serialize(next.page);
      if (pageValue === null || pageValue === undefined || pageValue === "") route.delete(spec.page.param(next));
      else route.set(spec.page.param(next), pageValue);
      spec.prune?.(route, next);
      const search = route.toString();
      if (search === appliedSearchRef.current) {
        setState(next);
        return;
      }
      appliedSearchRef.current = search;
      setState(next);
      history[options.replace ? "replace" : "push"]({ pathname: location.pathname, search });
    }
    return [state, update];
  }

  function pagerPages(page, totalPages) {
    if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1);
    const values = [1, totalPages, page - 1, page, page + 1].filter((value) => value >= 1 && value <= totalPages);
    const pages = [...new Set(values)].sort((left, right) => left - right);
    return pages.flatMap((value, index) => index && value - pages[index - 1] > 1 ? [null, value] : [value]);
  }

  function Pager({ page, total, pageSize, hasMore, loading, onPage, label }) {
    const totalPages = total === undefined
      ? Math.max(page, page + (hasMore ? 1 : 0))
      : Math.max(1, Math.ceil(total / Math.max(1, pageSize || 1)));
    if (page === 1 && totalPages === 1) return null;
    return React.createElement(
      "nav",
      { className: "curator-pager", "aria-label": label },
      React.createElement(Button, { className: "curator-pager-mobile", size: "sm", variant: "secondary", disabled: loading || page === 1, onClick: () => onPage(1), "aria-label": "First page", title: "First page" }, "«"),
      React.createElement(Button, { size: "sm", variant: "secondary", disabled: loading || page === 1, onClick: () => onPage(page - 1), "aria-label": "Previous page", title: "Previous page" }, React.createElement("span", { className: "curator-pager-desktop" }, "Previous"), React.createElement("span", { className: "curator-pager-mobile", "aria-hidden": "true" }, "‹")),
      pagerPages(page, totalPages).map((value, index) => value === null
        ? React.createElement("span", { key: `ellipsis-${index}`, className: "curator-pager-ellipsis", "aria-hidden": "true" }, "…")
        : React.createElement(Button, { key: value, className: "curator-pager-page", size: "sm", variant: value === page ? "primary" : "secondary", disabled: loading || value === page, onClick: () => onPage(value), "aria-label": `Page ${value}`, "aria-current": value === page ? "page" : undefined }, value)),
      React.createElement("span", { className: "curator-pager-summary" }, `Page ${page} of ${totalPages}`),
      React.createElement(Button, { size: "sm", variant: "secondary", disabled: loading || page >= totalPages, onClick: () => onPage(page + 1), "aria-label": "Next page", title: "Next page" }, React.createElement("span", { className: "curator-pager-desktop" }, "Next"), React.createElement("span", { className: "curator-pager-mobile", "aria-hidden": "true" }, "›")),
      total !== undefined && React.createElement(Button, { className: "curator-pager-mobile", size: "sm", variant: "secondary", disabled: loading || page >= totalPages, onClick: () => onPage(totalPages), "aria-label": "Last page", title: "Last page" }, "»")
    );
  }

  function readMoodID() {
    const cookie = document.cookie.split(";").map((value) => value.trim()).find((value) => value.startsWith("curator_mood="));
    if (cookie !== undefined) {
      try { return decodeURIComponent(cookie.slice("curator_mood=".length)); } catch (_) { return ""; }
    }
    return document.cookie.split(";").some((cookie) => cookie.trim() === "curator_together=1") ? "together" : "";
  }

  function readTogetherMode() { return Boolean(readMoodID()); }

  function writeMoodID(id) {
    document.cookie = `curator_mood=${encodeURIComponent(id)}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}`;
  }

  let filterPresets = {};

  function readFilterPresets() { return filterPresets; }

  async function loadFilterPresets(stored) {
    let legacy;
    try { legacy = JSON.parse(localStorage.getItem(FILTER_PRESETS_KEY) || "null"); }
    catch (_) { legacy = null; }
    const merged = { ...stored };
    if (legacy && typeof legacy === "object") {
      for (const scope of ["recommendations", "similar", "expand", "hunt"]) {
        if (!legacy[scope]?.presets) continue;
        merged[scope] = {
          ...legacy[scope], ...stored[scope],
          presets: { ...legacy[scope].presets, ...stored[scope]?.presets },
        };
      }
      const result = await operation({ operation: "update_config", values: { saved_filters: merged } });
      filterPresets = result.config.saved_filters;
      // Keep the browser copy until the database confirms the import.
      try { localStorage.removeItem(FILTER_PRESETS_KEY); } catch (_) {}
    } else {
      filterPresets = merged;
    }
  }

  async function saveFilterPreset(scope, name, current, makeDefault) {
    // ponytail: simultaneous saves use the last write; use atomic preset updates if shared editing is needed.
    const data = await operation({ operation: "get_config" });
    const all = data.config.saved_filters || {};
    const previous = all[scope] || {};
    const next = { presets: { ...previous.presets, [name]: current }, default: makeDefault ? name : previous.default };
    const result = await operation({ operation: "update_config", values: { saved_filters: { ...all, [scope]: next } } });
    filterPresets = result.config.saved_filters;
    return filterPresets[scope];
  }

  function defaultFilters(scope) {
    const saved = readFilterPresets()[scope] || {};
    return saved.presets?.[saved.default] || {};
  }

  async function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(value);
    const input = document.createElement("textarea");
    input.value = value;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    const copied = document.execCommand("copy");
    input.remove();
    if (!copied) throw new Error("Copy failed");
  }

  // filters narrow a lane's already-classified candidates server-side (same
  // include/exclude tag, performer, studio, and gender shape as Similar).
  // Filtered slates aren't cached: the persistent slateCache is keyed only
  // by lane+page, and filter combinations change too often relative to how
  // long they stay open to be worth a filter-aware cache key.
  function loadSlate(lane, page = 1, prefetched = false, filters = null) {
    rotateDay();
    const togetherMode = readTogetherMode();
    const hasFilters = Boolean(filters && (filters.includeTags?.length || filters.excludeTags?.length || filters.performers?.length || filters.studios?.length || filters.gender));
    const key = slateKey(lane, page);
    if (!hasFilters && !togetherMode) {
      if (slateCache.has(key)) return Promise.resolve(slateCache.get(key));
      if (slateRequests.has(key)) return slateRequests.get(key);
    }
    const generation = cacheGeneration;
    const args = {
      operation: "get_slate",
      together_mode: togetherMode,
      mood_id: readMoodID(),
      lane,
      page,
      exclude_scene_ids: [...(laneExclusions.get(lane) || [])],
      draw_seed: rotationLane(lane).seed,
      draw_at_ms: rotationLane(lane).atMs,
      exploration: 0,
      context: { route: location.pathname, prefetched },
      ...(hasFilters ? {
        include_tags: (filters.includeTags || []).map((item) => item.name),
        exclude_tags: (filters.excludeTags || []).map((item) => item.name),
        performer_ids: (filters.performers || []).map((item) => String(item.id)),
        studio_ids: (filters.studios || []).map((item) => String(item.id)),
        gender: filters.gender || "",
      } : {}),
    };
    const request = operation(args)
      .then(async (initial) => {
        let data = initial;
        if (generation !== cacheGeneration) return data;
        const modelChanged = cachedModelId && cachedModelId !== data.model_id;
        const rotationModelChanged = rotation.modelId && rotation.modelId !== data.model_id;
        const configChanged = cachedConfigUpdatedAtMs !== null && cachedConfigUpdatedAtMs !== data.config_updated_at_ms;
        if (modelChanged || rotationModelChanged || configChanged) {
          clearSlateCache();
          if (modelChanged || rotationModelChanged) laneExclusions.clear();
          rotation.lanes = {};
          saveRotation();
          const draw = rotationLane(lane);
          data = await operation({ ...args, exclude_scene_ids: [...(laneExclusions.get(lane) || [])], draw_seed: draw.seed, draw_at_ms: draw.atMs });
        }
        rotation.modelId = data.model_id;
        saveRotation();
        cachedModelId = data.model_id;
        cachedConfigUpdatedAtMs = data.config_updated_at_ms;
        if (!hasFilters && !togetherMode) {
          slateCache.set(slateKey(lane, page), data);
          persistSlateCache();
        }
        return data;
      })
      .finally(() => slateRequests.delete(key));
    if (!hasFilters && !togetherMode) slateRequests.set(key, request);
    return request;
  }

  function prefetchLane(lane) {
    if (!laneByValue.has(lane) || cachedConfigUpdatedAtMs === null) return;
    loadSlate(lane, 1, true).catch(() => {
      // Opening the lane will retry and show any error in context.
    });
  }

  async function configurePlugin(values) {
    const response = await fetch("/graphql", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: 'mutation ConfigureCurator($input: Map!) { configurePlugin(plugin_id: "stash-curator", input: $input) }',
        variables: { input: values },
      }),
    });
    const payload = await response.json();
    if (!response.ok || payload.errors) {
      throw new Error(payload.errors?.[0]?.message || `HTTP ${response.status}`);
    }
    document.body.classList.toggle("curator-hide-card-badges", values.hideCardRatings === true);
    document.body.dataset.curatorDetailPageControls = ["small", "off"].includes(values.detailPageControls) ? values.detailPageControls : "large";
    return payload.data.configurePlugin;
  }

  // Curator's own get_config operation only echoes curator_config (the
  // subset of settings synced into the sidecar DB); raw plugin settings
  // like whisparrApiKey never pass through it. Query Stash directly for
  // those, mirroring plugin/backend.py's SETTINGS_QUERY.
  async function getPluginSettings() {
    const response = await fetch("/graphql", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: 'query CuratorPluginSettings { configuration { plugins(include: ["stash-curator"]) } }',
      }),
    });
    const payload = await response.json();
    if (!response.ok || payload.errors) {
      throw new Error(payload.errors?.[0]?.message || `HTTP ${response.status}`);
    }
    const settings = payload.data.configuration.plugins["stash-curator"] || {};
    document.body.classList.toggle("curator-hide-card-badges", settings.hideCardRatings === true);
    document.body.dataset.curatorDetailPageControls = ["small", "off"].includes(settings.detailPageControls) ? settings.detailPageControls : "large";
    return settings;
  }

  async function getStashBoxEndpoints() {
    const response = await fetch("/graphql", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "query CuratorStashBoxes { configuration { general { stashBoxes { name endpoint } } } }" }),
    });
    const payload = await response.json();
    if (!response.ok || payload.errors) {
      throw new Error(payload.errors?.[0]?.message || `HTTP ${response.status}`);
    }
    return payload.data.configuration.general.stashBoxes;
  }

  function formatTimeAgo(ms) {
    const minutes = Math.round((Date.now() - ms) / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  }

  async function runTask(taskName, automatic = false) {
    const response = await fetch("/graphql", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query:
          "mutation CuratorTask($task: String!, $args: Map!) { " +
          "runPluginTask(plugin_id: \"stash-curator\", task_name: $task, args_map: $args) }",
        variables: { task: taskName, args: { automatic } },
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
          ? runTask("Apply recent Curator feedback", true)
          : null)
        .catch(() => {}),
      delay
    );
  }

  // Curate's impact report diffs the two newest model builds, so it is only
  // meaningful once a build has actually consumed the picks just submitted.
  // Kick the update immediately (no debounce — the user is waiting on it) and
  // resolve when a different model is published, or when the wait times out.
  const MODEL_REFRESH_POLL_MS = 2000;
  const MODEL_REFRESH_TIMEOUT_MS = 180000;
  async function applyFeedbackAndAwaitBuild() {
    const before = await operation({ operation: "health" }).catch(() => null);
    const previousModelId = before && before.model_id;
    if (!before || (!before.model_update_ready && !before.model_rebuilding)) {
      // Below the update threshold: nothing will build, so don't stall on it.
      return false;
    }
    if (!before.model_rebuilding) {
      await runTask("Apply recent Curator feedback").catch(() => {});
    }
    const deadline = Date.now() + MODEL_REFRESH_TIMEOUT_MS;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, MODEL_REFRESH_POLL_MS));
      const health = await operation({ operation: "health" }).catch(() => null);
      if (!health) continue;
      if (health.model_id && health.model_id !== previousModelId) {
        clearSlateCache();
        return true;
      }
      if (!health.model_rebuilding && !health.model_update_ready) {
        // The build finished without changing the published model.
        return false;
      }
    }
    return false;
  }

  // Stash records plays without bumping scenes.updated_at, so only the play pass can bring
  // cooldown and recovery context up to date. It is cheap (a watermark query since the last
  // sync) and runs as an async Stash job, so coalesce bursts before firing it.
  function schedulePlaySync() {
    clearTimeout(playSyncTimer);
    playSyncTimer = setTimeout(() => {
      runTask("Sync recent plays", true).catch(() => {
        // Retry on the next play, route change, or online event.
      });
    }, 8000);
  }

  function performerNameFilter(items) {
    return items.reduce(
      (filter, item) => ({ name: { value: item.label, modifier: "EQUALS" }, ...(filter && { OR: filter }) }),
      null
    );
  }

  function formatSigned(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return `${number >= 0 ? "+" : "−"}${Math.abs(number).toFixed(2)}`;
  }

  function formatAppealValue(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return number < 0 ? `−${Math.abs(number).toFixed(2)}` : number.toFixed(2);
  }
  function clamp01(value) {
    return Math.max(0, Math.min(1, Number(value) || 0));
  }


  function scoreBar(value, signed = true) {
    const number = Number(value) || 0;
    const magnitude = signed ? clamp01(Math.abs(number)) : clamp01(number);
    const fillStyle = { width: `${Math.round(magnitude * 100)}%` };
    return React.createElement("div", { className: `curator-score-scale${signed ? " curator-score-scale-signed" : ""}`, role: "img", "aria-label": `${signed ? formatAppealValue(number) : number.toFixed(2)} on a ${signed ? "minus one to one" : "zero to one"} scale` }, React.createElement("span", { className: `curator-score-fill ${number < 0 ? "curator-score-negative" : "curator-score-positive"}`, style: fillStyle, "aria-hidden": "true" }));
  }

  function fingerprintPoint(index, value, count, radius = 78, centerX = 130, centerY = 108) {
    const angle = -Math.PI / 2 + (index * Math.PI * 2) / count;
    const distance = radius * clamp01(value);
    return `${centerX + Math.cos(angle) * distance},${centerY + Math.sin(angle) * distance}`;
  }

  function EvidenceFingerprint({ fingerprint }) {
    const rawAxes = fingerprint?.axes || [];
    const legacyMetadata = rawAxes.find((axis) => axis.name === "metadata_coverage");
    const axes = rawAxes.filter((axis) => axis.name !== "metadata_coverage");
    if (!fingerprint || axes.length === 0) return null;
    const metadata = fingerprint.metadata_coverage || (legacyMetadata && { available: legacyMetadata.available, value: legacyMetadata.value ?? legacyMetadata.confidence, scale: "0..1" });
    const supportPoints = axes.map((axis, index) => fingerprintPoint(index, axis.available ? axis.support : 0, axes.length)).join(" ");
    const cautionPoints = axes.map((axis, index) => fingerprintPoint(index, axis.available ? axis.caution : 0, axes.length)).join(" ");
    const axisPoint = (index, value = 1) => fingerprintPoint(index, value, axes.length, 88);
    const label = (axis) => axis.name.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
    return React.createElement(
      "div",
      { className: "curator-evidence-fingerprint", "aria-label": "Evidence fingerprint radar plot" },
      React.createElement("strong", null, "Evidence fingerprint"),
      React.createElement(
        "svg",
        { className: "curator-fingerprint-svg", viewBox: "0 0 260 220", role: "img", "aria-label": "Evidence fingerprint: support and caution by evidence family" },
        React.createElement("title", null, "Evidence fingerprint: support and caution by evidence family"),
        [0.33, 0.66, 1].map((value) => React.createElement("polygon", { key: value, className: "curator-fingerprint-ring", points: axes.map((_, index) => axisPoint(index, value)).join(" ") })),
        axes.map((axis, index) => React.createElement("line", { key: `${axis.name}-spoke`, className: axis.available ? "curator-fingerprint-spoke" : "curator-fingerprint-spoke curator-fingerprint-spoke-missing", x1: 130, y1: 108, x2: axisPoint(index).split(",")[0], y2: axisPoint(index).split(",")[1] })),
        React.createElement("polygon", { className: "curator-fingerprint-support-shape", points: supportPoints }),
        React.createElement("polygon", { className: "curator-fingerprint-caution-shape", points: cautionPoints }),
        axes.map((axis, index) => React.createElement("text", { key: `${axis.name}-label`, className: `curator-fingerprint-label${axis.available ? "" : " curator-fingerprint-label-missing"}`, x: axisPoint(index, 1.1).split(",")[0], y: axisPoint(index, 1.1).split(",")[1], textAnchor: "middle" }, label(axis)))
      ),
      React.createElement("div", { className: "curator-fingerprint-legend" }, React.createElement("span", { className: "curator-fingerprint-legend-support" }, "Support"), React.createElement("span", { className: "curator-fingerprint-legend-caution" }, "Caution"), React.createElement("span", { className: "curator-fingerprint-legend-confidence" }, `Confidence ${Math.round(clamp01(fingerprint.confidence) * 100)}%`)),
      React.createElement("div", { className: `curator-metadata-status${metadata?.available ? " curator-metadata-complete" : " curator-metadata-incomplete"}`, role: "status" }, metadata?.available ? "✓ Metadata covered" : "○ Metadata incomplete"),
      React.createElement("ul", { className: "curator-fingerprint-accessible" }, axes.map((axis) => React.createElement("li", { key: `${axis.name}-accessible` }, `${label(axis)}: ${axis.available ? `support ${Math.round(clamp01(axis.support) * 100)}%, caution ${Math.round(clamp01(axis.caution) * 100)}%` : "no evidence"}`)), React.createElement("li", null, metadata?.available ? "Metadata covered" : "Metadata incomplete"))
    );
  }

  function ScoreBreakdown({ explanation, item }) {
    const components = explanation?.components || [];
    const fallback = item ? [
      { name: "content_similarity", label: "Content similarity", value: Number(item.components?.content?.value || 0), scale: "-1..1", direction: "positive", available: true },
      { name: "performer_match", label: "Performer match", value: Number(item.components?.performer_identity?.value || 0) + Number(item.components?.performer_similarity?.value || 0), scale: "-1..1", direction: "positive", available: true },
      { name: "direct_feedback", label: "Direct feedback", value: Number(item.appeal || 0), scale: "-1..1", direction: "positive", available: true },
      { name: "model_confidence", label: "Model confidence", value: Number(item.confidence || 0), scale: "0..1", direction: "neutral", available: true },
    ] : [];
    const rows = components.length ? components : fallback;
    return React.createElement("div", { className: "curator-score-breakdown" }, rows.map((component) => React.createElement("div", { key: component.name, className: `curator-score-row${component.available === false ? " curator-score-row-missing" : ""}` }, React.createElement("div", { className: "curator-score-row-head" }, React.createElement("span", null, component.label), React.createElement("span", { className: `curator-score-value curator-score-${component.direction || "neutral"}` }, component.scale === "0..1" ? `${Math.round(clamp01(component.value) * 100)}%` : formatSigned(component.value))), component.available === false ? React.createElement("small", null, "No evidence in the current model") : scoreBar(component.value, component.scale !== "0..1"))));
  }

  function negativeNeighbors(item) {
    const component = item?.components?.content_neighbor;
    if (!(component?.value < 0) || !Number.isFinite(component.training_outcome_mean)) return [];
    return [...(item.neighbors || [])].filter((neighbor) => neighbor.weight > 0 && neighbor.outcome < component.training_outcome_mean)
      .sort((a, b) => b.weight * (component.training_outcome_mean - b.outcome) - a.weight * (component.training_outcome_mean - a.outcome)).slice(0, 2);
  }

  function cardReason(item, scene, evidenceScenes) {
    const qualification = item?.qualification || {};
    const unavailable = { summary: "The specific reason for this selection is unavailable.", details: [] };
    const name = (value) => typeof value === "string" ? value.trim() : "";
    if (item?.source_lane === "best_bets") {
      if (!qualification.unseen || !(qualification.corroborated || qualification.direct_reliable)) return unavailable;
      const components = item.components || {};
      const matches = [
        ...(components.content?.value > 0 ? components.content.top || [] : []).map((feature) => ({ ...feature, name: feature.metadata?.tag_name || feature.name })),
        ...(components.performer_identity?.value > 0 ? components.performer_identity.performers || [] : []).map((performer) => ({ ...performer, name: scene?.performers?.find((entry) => String(entry.id) === String(performer.performer_id))?.name })),
        ...(components.studio?.value > 0 ? components.studio.studios || [] : []).map((studio) => ({ ...studio, name: String(scene?.studio?.id) === String(studio.studio_id) ? scene?.studio?.name : "" })),
      ].filter((feature) => feature.value > 0 && name(feature.name)).sort((a, b) => b.value - a.value);
      const names = [...new Set(matches.map((feature) => name(feature.name)))].slice(0, 2).map((value) => `“${value}”`).join(" and ");
      return {
        teaser: names ? `Matches your preference for ${names}.` : "Strong current fit backed by positive evidence.",
        summary: names ? `Best bet because this unplayed scene matches positive preferences for ${names}.` : `Best bet because this unplayed scene has ${qualification.direct_reliable ? "reliable positive feedback" : "corroborating preference evidence"} and strong current fit.`,
        details: [qualification.direct_reliable ? "Reliable positive feedback on this scene supports the selection." : "Similar-scene evidence is corroborated by content or performer evidence.", "The scene also meets the lane's current-fit, confidence, and metadata requirements."],
      };
    }
    if (item?.source_lane === "revisit") {
      if (!(qualification.direct_appeal > 0 && qualification.recovery > 0)) return unavailable;
      return {
        teaser: "Positive history, with time to enjoy it again.",
        summary: "Revisit because you played this scene before, its recorded outcomes are positive overall, and its cooldown has eased.",
        details: [`Recorded preference: ${qualification.direct_appeal.toFixed(2)} (−1 to +1).`, "The selection uses positive scene history and cooldown recovery, rather than just similarity to other scenes."],
      };
    }
    if (item?.source_lane === "dormant") {
      const entity = qualification.dormant_entity;
      if (!name(entity?.name) || !Number.isFinite(qualification.days_since_played)) return unavailable;
      return {
        teaser: `Past preference for “${name(entity.name)}”; ${qualification.days_since_played} days since a play.`,
        summary: `Dormant because you had positive history with ${entity.type || ""} “${name(entity.name)}”, but no recorded play involving it for ${qualification.days_since_played} days.`,
        details: ["This is an unplayed scene connected to that past preference.", "The time away refers to the named performer, studio, or tag, not this scene."],
      };
    }
    if (item?.source_lane === "stretch") {
      const anchor = [...(qualification.anchor_features || [])].filter((feature) => name(feature.name)).sort((a, b) => b.value - a.value)[0];
      const challenge = name(qualification.challenged_feature?.name);
      const kind = qualification.challenge_kind || item.subtype;
      if (!anchor || !challenge || !["untested", "tested_negative"].includes(kind)) return unavailable;
      const boundary = kind === "untested"
        ? `the model has too little evidence about “${challenge}”`
        : `the model estimates a negative preference for “${challenge}”`;
      return {
        teaser: `Familiar “${name(anchor.name)}”, with ${kind === "untested" ? "less-tested" : "lower estimated preference for"} “${challenge}”.`,
        summary: `Stretch because “${name(anchor.name)}” is a familiar positive, while ${boundary}.`,
        details: [`Familiar anchor: ${name(anchor.name)}.`, `Selected challenge: ${challenge}. ${kind === "untested" ? "Insufficient evidence does not mean dislike." : "This is a model estimate, not necessarily an explicit dislike."}`],
      };
    }
    if (item?.source_lane === "blind_spots") {
      const facets = [...(qualification.dark_facets || [])].filter((facet) => name(facet.name)).sort((a, b) => b.darkness - a.darkness);
      const selected = [facets.find((facet) => facet.facet_type === "studio"), facets.find((facet) => facet.facet_type === "tag")];
      if (selected.some((facet) => !facet)) return unavailable;
      return {
        teaser: `Underexplored studio “${name(selected[0].name)}” and tag “${name(selected[1].name)}”.`,
        summary: `Blind spot because studio “${name(selected[0].name)}” and tag “${name(selected[1].name)}” are underexplored relative to the rest of your library.`,
        details: ["This scene had no recorded play when selected.", ...selected.map((facet) => `${facet.facet_type === "studio" ? "Studio" : "Tag"} “${name(facet.name)}”: ${Number.isInteger(facet.played_count) && Number.isInteger(facet.library_count) ? `${facet.played_count} of ${facet.library_count} scenes played` : "play counts unavailable"}.`), "Counts reflect the model's recorded viewing history; underexplored does not mean disliked."],
      };
    }
    if (item?.source_lane !== "score_review" || !(item.appeal < 0)) return null;
    const components = item.components || {};
    const directConfidence = Number(components.direct?.confidence || 0);
    const phrases = [];
    const subjects = [];
    const details = [];
    const quotedNames = (rows, resolve) => [...new Set([...rows].filter((row) => row.value < 0).sort((a, b) => a.value - b.value).map(resolve).map(name).filter(Boolean))].slice(0, 2).map((value) => `“${value}”`).join(" and ");
    for (const key of ["direct", "content", "structure", "performer_identity", "performer_similarity", "studio", "content_neighbor", "baseline"]) {
      if (!(components[key]?.value < 0) || (key === "direct" ? directConfidence <= 0 : directConfidence >= 1)) continue;
      const component = components[key];
      if (key === "content" || key === "structure") {
        const names = quotedNames(component.top || [], (feature) => feature.metadata?.tag_name || feature.name);
        if (names) subjects.push(names);
        phrases.push(names ? `the model associates ${names} with lower appeal` : `the ${key} estimate is negative, but its specific features are unavailable`);
      } else if (key === "performer_identity" || key === "performer_similarity") {
        const names = quotedNames(component.performers || [], (performer) => scene?.performers?.find((entry) => String(entry.id) === String(performer.performer_id))?.name);
        if (names) subjects.push(`${key === "performer_similarity" ? "profiles similar to" : "performer"} ${names}`);
        phrases.push(names
          ? key === "performer_identity" ? `its learned preference for performer ${names} is negative` : `evidence from profiles similar to performer ${names} lowers the estimate`
          : "the performer estimate is negative, but the contributing names are unavailable");
      } else if (key === "studio") {
        const names = quotedNames(component.studios || [], (studio) => String(scene?.studio?.id) === String(studio.studio_id) ? scene?.studio?.name : "");
        if (names) subjects.push(`studio ${names}`);
        phrases.push(names ? `its learned preference for studio ${names} is negative` : "the studio estimate is negative, but the studio name is unavailable");
      } else if (key === "content_neighbor") {
        const neighbors = negativeNeighbors(item);
        const titles = neighbors.map((neighbor) => name(evidenceScenes?.get(String(neighbor.scene_id))?.title)).filter(Boolean).map((title) => `“${title}”`).join(" and ");
        if (titles) subjects.push(`similar scenes ${titles}`);
        phrases.push(titles ? `similar scenes such as ${titles} had outcomes below your library average` : "similar scenes had outcomes below your library average (titles unavailable)");
        for (const neighbor of neighbors) {
          const title = name(evidenceScenes?.get(String(neighbor.scene_id))?.title);
          if (title) details.push(`“${title}”: recorded outcome ${Number(neighbor.outcome).toFixed(2)}, compared with library average ${component.training_outcome_mean.toFixed(2)} (−1 to +1).`);
        }
      } else if (key === "direct") {
        subjects.push("this scene's recorded outcomes");
        phrases.push("this scene's recorded ratings and viewing feedback combine to a negative outcome");
      } else {
        subjects.push("the learned library baseline");
        phrases.push("your recorded library outcomes give the model a negative starting estimate");
      }
    }
    if (!phrases.length) return { summary: "Negative estimate; the specific supporting evidence is unavailable.", details: [] };
    return {
      teaser: subjects.length ? `Lower estimated appeal from ${subjects.slice(0, 2).join(" and ")}.` : "Negative estimate; contributing names unavailable.",
      summary: `Negative because ${phrases.slice(0, 2).join("; ")}.${phrases.length > 2 ? " More evidence under “Why this?”." : ""}`,
      details: [...phrases.slice(2).map((phrase) => `${phrase.charAt(0).toUpperCase()}${phrase.slice(1)}.`), ...details, "These are model estimates, not necessarily explicit dislikes. Positive evidence can offset these signals; cooldown and Not now do not affect Appeal."],
    };
  }

  function findSceneSummary(item) {
    const payload = item.payload || {};
    const summary = payload.explanation?.summary || item.explanation?.summary;
    if (summary) return summary;
    const reasons = (payload.why || []).filter((value) => typeof value === "string" && value.trim());
    if (reasons.length && item.similarity !== undefined) return `Related to the source scene: ${reasons.join("; ")}.`;
    const signals = {
      "a performer you already enjoy": "Includes a performer with positive preference evidence.",
      "a performer close to your preferences": "Includes a performer whose profile matches your learned preferences.",
      "performer evidence reduced for the large compilation cast": "The large cast makes performer evidence less influential.",
    };
    const features = reasons.filter((reason) => !Object.hasOwn(signals, reason)).map((value) => `“${value}”`);
    const names = features.length > 1 ? `${features.slice(0, -1).join(", ")} and ${features.at(-1)}` : features[0];
    return [names && `Matches your learned preferences for ${names}.`, ...reasons.filter((reason) => Object.hasOwn(signals, reason)).map((reason) => signals[reason])].filter(Boolean).join(" ")
      || (item.sources?.includes("wildcard") ? "Popularity wildcard outside your usual preference matches." : "Specific match evidence is unavailable.");
  }

  function FindSceneReason({ item }) {
    return React.createElement("p", { className: "curator-selection-reason card-section" }, findSceneSummary(item));
  }

  function ExplanationView({ explanation, item, scene, evidenceScenes }) {
    if (!explanation) return null;
    const rows = explanation.evidence_rows?.length
      ? explanation.evidence_rows
      : (explanation.supporting_reasons || []).map((reason) => ({ ...reason, label: reasonLabel(reason.code) }));
    const lane = explanation.lane_context;
    const selection = cardReason(item, scene, evidenceScenes);
    return React.createElement(
      "div",
      { className: "curator-explanation-view" },
      selection && React.createElement("div", { className: "curator-lane-callout card-section" }, React.createElement("strong", null, selection.summary), selection.details.length > 0 && React.createElement("ul", null, selection.details.map((detail) => React.createElement("li", { key: detail }, detail)))),
      explanation.summary && React.createElement("p", { className: "curator-explanation" }, explanation.summary),
      React.createElement(EvidenceFingerprint, { fingerprint: explanation.evidence_fingerprint }),
      rows.length > 0 && React.createElement(
        "div",
        { className: "curator-evidence-rows" },
        React.createElement("strong", null, "Evidence"),
        React.createElement("div", { className: "curator-evidence-row-group" }, rows.map((row, index) => React.createElement("div", { key: `${row.code}-${index}`, className: `curator-evidence-row curator-evidence-${row.direction || "context"}` }, React.createElement("span", null, row.direction === "positive" ? "Supports" : row.direction === "negative" ? "Cautions" : "Context"), React.createElement("strong", null, row.label || reasonLabel(row.code)), row.confidence !== undefined && React.createElement("small", null, ` ${Math.round(clamp01(row.confidence) * 100)}% confidence`))))
      ),
      !selection && lane?.available && lane.source_lane && React.createElement("p", { className: "curator-lane-callout" }, `Selected for ${lane.source_lane.replaceAll("_", " ")} as ${lane.subtype || "a qualified match"}.`),
      // Issue #216: never render the Technical details disclosure empty —
      // ScoreBreakdown has rows only when the explanation carries components
      // or an item fallback exists.
      (explanation.components?.length || item) && React.createElement("details", { className: "curator-technical-details" }, React.createElement("summary", null, "Technical details"), React.createElement(ScoreBreakdown, { explanation, item }))
    );
  }

  function reasonLabel(code) {
    const labels = {
      "direct.positive": "Direct positive history", "direct.negative": "Direct negative history", "direct.residual": "Direct history adjustment",
      "appeal.performer_identity": "Performer match", "appeal.performer_similar": "Similar performer profile", "appeal.studio": "Studio appeal", "appeal.content_neighbor": "Similar scenes",
      "appeal.tag_positive": "Familiar content pattern", "appeal.tag_negative": "Less familiar content pattern", "appeal.tag_declared_positive": "Declared positive content preference", "appeal.tag_declared_negative": "Declared negative content preference",
      "fit.cooldown": "Scene cooldown", "fit.satiation": "Recent repetition", "fit.not_now": "Not now feedback", "eligibility.lane": "Eligible for this lane", "explore.challenge": "Lane challenge", "explore.coverage": "Library coverage gap", "dormant.entity": "Dormant preference",
    };
    const fallback = code.split(".").at(-1).replaceAll("_", " ");
    return labels[code] || fallback.charAt(0).toUpperCase() + fallback.slice(1);
  }

  const SENTIMENTS = [
    [-1, "Strong dislike", "curator-sentiment-danger"],
    [-0.5, "Slight dislike", "curator-sentiment-warning"],
    [0, "Neutral", "curator-sentiment-neutral"],
    [0.5, "Slight like", "curator-sentiment-like"],
    [1, "Strong like", "curator-sentiment-love"],
  ];

  // The 5-point spectrum spans stops 1-5 of the 6-stop track (stop 0 is
  // "Never"), i.e. positions 20%/40%/60%/80%/100% — a continuous value in
  // [-1, 1] (Taste Profile's model-inferred sentiment) maps onto that same
  // linear scale, skipping the "Never" slot since inference has no opinion
  // on hard exclusion.
  function sentimentValueToTrackPct(value) {
    return 20 + (Math.max(-1, Math.min(1, value)) + 1) * 40;
  }
  function nearestSentiment(value) {
    let best = SENTIMENTS[0];
    let bestDistance = Infinity;
    for (const entry of SENTIMENTS) {
      const distance = Math.abs(entry[0] - value);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = entry;
      }
    }
    return best;
  }
  function nearestSentimentLabel(value) {
    return nearestSentiment(value)[1];
  }
  const BELIEF_PHRASES = {
    "Strong dislike": "strongly dislike",
    "Slight dislike": "slightly dislike",
    "Neutral": "feel neutral about",
    "Slight like": "slightly like",
    "Strong like": "strongly like",
  };
  function beliefSentence(value) {
    return `I think you ${BELIEF_PHRASES[nearestSentimentLabel(value)]} this`;
  }

  // Design-mockup "confidence pips": 5 bars, filled left-to-right by how
  // much viewing history supports the model's inference for this tag.
  function ConfidencePips({ confidence }) {
    const on = Math.round(Math.max(0, Math.min(1, confidence)) * 5);
    return React.createElement(
      "div",
      { className: "curator-confidence-wrap" },
      React.createElement("span", { className: "curator-confidence-label" }, "Confidence"),
      React.createElement(
        "div",
        { className: "curator-confidence-pips", title: "How much viewing history supports this inference — more filled bars means more evidence" },
        [0, 1, 2, 3, 4].map((index) => React.createElement("span", { key: index, className: index < on ? "on" : "" }))
      )
    );
  }

  function SentimentScale() {
    return React.createElement("div", { className: "curator-sentiment-scale", "aria-hidden": true },
      ["Never (block)", ...SENTIMENTS.map(([, label]) => label)].map((label, index) =>
        React.createElement("span", { key: label, className: index === 0 ? "curator-sentiment-scale-never" : undefined, style: { left: `${index * 20}%` } }, label)
      )
    );
  }

  // "Never" is stop 0 on the same track as the 5
  // sentiment levels (not a separate toggle) — set apart visually with its
  // own color, per the #150 design brief. The visible track/stops/thumb are
  // a purely decorative rail; a fully transparent native range input sits
  // on top capturing clicks/drags/keyboard, so the control stays as
  // accessible as a plain <input type="range"> without hand-rolling pointer
  // math the way the original design mockup's static-HTML version did.
  // `inferredValue`, when given (only Taste Profile has this — it's the
  // model's own continuous estimate, distinct from the user's discrete
  // direct rating), renders as a small differently-colored tick on the same
  // track so the two can be compared at a glance.
  function TagSentimentControl({ tag, value, blocked, onChange, compact = false, inferredValue = null, showScale = compact }) {
    const rated = (value !== null && value !== undefined) || blocked;
    const stopIndex = blocked ? 0 : rated ? SENTIMENTS.findIndex(([score]) => score === value) + 1 : 3;
    const currentLabel = blocked ? "Never" : rated ? SENTIMENTS[stopIndex - 1][1] : "Not rated";
    const tierClass = blocked ? "curator-sentiment-never" : rated ? SENTIMENTS[stopIndex - 1][2] : "";
    function commit(index) {
      if (index === 0) onChange({ value: null, blocked: true });
      else onChange({ value: SENTIMENTS[index - 1][0], blocked: false });
    }
    function handleChange(event) {
      commit(Number(event.target.value));
    }
    // An unrated item is displayed with the thumb parked at stop 3
    // ("Neutral")'s position, purely as a resting point — there's no real
    // value yet. A native range input only fires input/change when its
    // value actually changes, so a click that resolves to that SAME stop
    // (i.e. clicking dead-center on "Neutral") is indistinguishable from a
    // no-op to the browser and silently does nothing. Recompute the
    // intended stop from click position and commit directly whenever it
    // matches the value already showing, which is exactly the case the
    // native event won't fire for.
    function handleClick(event) {
      const rect = event.currentTarget.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      const index = Math.round(ratio * 5);
      if (index === stopIndex) commit(index);
    }
    const hasModelEstimate = inferredValue !== null && inferredValue !== undefined;
    return React.createElement(
      "div",
      { className: `curator-sentiment curator-sentiment-slider${compact ? " curator-sentiment-compact" : ""}${showScale ? " curator-sentiment-labelled" : ""}`, role: "group", "aria-label": `Sentiment for ${tag.name}` },
      showScale && React.createElement(SentimentScale),
      React.createElement(
        "label",
        { className: `curator-sentiment-range-wrap${tierClass ? ` ${tierClass}` : ""}` },
        React.createElement(
          "span",
          { className: "curator-sentiment-track" },
          React.createElement(
            "span",
            { className: "curator-sentiment-rail", "aria-hidden": "true" },
            [0, 1, 2, 3, 4, 5].map((stop) => React.createElement("span", {
              key: stop,
              className: `curator-sentiment-stop${stop === 0 ? " curator-sentiment-stop-never" : ""}${rated && stopIndex === stop ? " curator-sentiment-stop-active" : ""}`,
              style: { left: `${(stop / 5) * 100}%` },
            })),
            hasModelEstimate && React.createElement("span", {
              className: "curator-sentiment-model-dot",
              style: { left: `${sentimentValueToTrackPct(inferredValue)}%` },
              title: `Model estimate: ${nearestSentimentLabel(inferredValue)} (${inferredValue.toFixed(2)})`,
            }),
            rated && React.createElement("span", { className: "curator-sentiment-thumb", style: { left: `${(stopIndex / 5) * 100}%` } })
          ),
          React.createElement("input", {
            type: "range",
            min: "0",
            max: "5",
            step: "1",
            className: "curator-sentiment-input",
            value: stopIndex,
            "aria-label": `Sentiment for ${tag.name}`,
            "aria-valuetext": currentLabel,
            onChange: handleChange,
            onClick: handleClick,
          })
        ),
        React.createElement("span", { className: "curator-sentiment-current" }, currentLabel)
      ),
      React.createElement(Button, { size: "sm", variant: "secondary", className: !rated ? "curator-sentiment-clear-placeholder" : undefined, "aria-label": "Clear answer", title: "Clear answer", onClick: () => onChange({ value: null, blocked: false }) }, compact ? "Clear" : "Clear answer")
    );
  }

  function readTagPreferenceQueue() {
    try {
      const value = JSON.parse(localStorage.getItem(TAG_PREFERENCE_QUEUE_KEY) || "[]");
      return Array.isArray(value) ? value : [];
    } catch (_) {
      return [];
    }
  }

  let flushingTagPreferences = false;
  async function flushTagPreferenceQueue() {
    if (flushingTagPreferences) return;
    const entries = readTagPreferenceQueue();
    if (!entries.length) return;
    flushingTagPreferences = true;
    try {
      await operation({ operation: "submit_tag_preferences", entries });
      const sent = new Set(entries.map((entry) => entry.preference_id));
      localStorage.setItem(TAG_PREFERENCE_QUEUE_KEY, JSON.stringify(readTagPreferenceQueue().filter((entry) => !sent.has(entry.preference_id))));
      clearSlateCache();
      scheduleModelUpdate();
    } catch (_) {
      // Retry on the next route, online event, or plugin page load.
    } finally {
      flushingTagPreferences = false;
    }
  }

  function submitTagPreference(tagId, {value, blocked}) {
    const queue = readTagPreferenceQueue();
    queue.push({ preference_id: uuid(), tag_id: tagId, value, blocked: !!blocked, occurred_at_ms: Date.now() });
    localStorage.setItem(TAG_PREFERENCE_QUEUE_KEY, JSON.stringify(queue));
    flushTagPreferenceQueue();
  }

  // RatingRows renders one sentiment row (name + compact TagSentimentControl).
  // Shared by the external, recommendation, and Similar cards' rating panels.
  function RatingRows({ rows, onAnswer, emptyLabel }) {
    if (!rows.length) {
      return React.createElement("small", null, emptyLabel);
    }
    return rows.map((row) =>
      React.createElement(
        "div",
        { key: row.key, className: "curator-external-tag-row" },
        React.createElement("strong", { className: "curator-external-tag-name", title: row.name }, row.name),
        React.createElement(TagSentimentControl, {
          tag: { name: row.name },
          value: row.direct_value,
          blocked: row.direct_blocked,
          compact: true,
          showScale: false,
          onChange: (value) => onAnswer(row, value),
        })
      )
    );
  }

  // RatingSection is one titled block of sentiment rows inside a rating panel.
  function RatingSection({ title, rows, onAnswer, emptyLabel }) {
    return React.createElement(
      "div",
      { className: "curator-rating-section" },
      rows.length > 0 ? React.createElement("div", { className: "curator-rating-scale-header" },
        React.createElement("strong", { className: "curator-rating-section-title" }, `${title} (${rows.length})`),
        React.createElement(SentimentScale),
        React.createElement("span", { className: "curator-rating-section-title" }, "Your rating")
      ) : React.createElement("strong", { className: "curator-rating-section-title" }, `${title} (0)`),
      React.createElement(RatingRows, { rows, onAnswer, emptyLabel })
    );
  }

  function RatingPopover({ anchor, onClose, children }) {
    return React.createElement(libraries.Bootstrap.Overlay, {
      show: true, target: anchor, placement: "bottom", flip: false,
      rootClose: true, onHide: onClose,
      popperConfig: { modifiers: [{ name: "preventOverflow", options: { padding: 8, altAxis: false } }] },
    }, React.createElement(libraries.Bootstrap.Popover, {
      id: "curator-rating-popover", className: "curator-rating-popover curator-page", role: "dialog", "aria-label": "Rate tags",
    }, children, React.createElement("div", { className: "curator-rating-footer" },
      React.createElement(Button, { size: "sm", variant: "link", "aria-label": "Collapse matching local tag ratings", onClick: onClose }, "Collapse")
    )));
  }

  // LocalRatingPanel is the "Rate tags" expander for local cards
  // (recommendation lanes and library Similar): the scene's classified tags
  // (get_scene_tag_choices). The toggle renders above the expanded list,
  // and the panel sits outside card-section
  // so the SFW Switch contract holds.
  function LocalRatingPanel({ sceneId }) {
    const [open, setOpen] = React.useState(false);
    const [anchor, setAnchor] = React.useState(null);
    const [tagChoices, setTagChoices] = React.useState(null);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState("");
    useCuratorActivity(`local-tags-${sceneId}`, loading, "Matching local tags…");
    async function toggle(event) {
      if (open) {
        setOpen(false);
        return;
      }
      setAnchor(event.currentTarget);
      setOpen(true);
      setLoading(true);
      setError("");
      try {
        const tagsResult = await operation({ operation: "get_scene_tag_choices", scene_id: sceneId });
        setTagChoices(tagsResult.items);
      } catch (failure) {
        setError(failure.message);
        setTagChoices([]);
      } finally {
        setLoading(false);
      }
    }
    function answerTag(row, {value, blocked}) {
      submitTagPreference(row.tag_id, {value, blocked});
      setTagChoices((current) => current.map((item) => item.tag_id === row.tag_id ? { ...item, direct_value: value, direct_blocked: !!blocked } : item));
    }
    return React.createElement(
      React.Fragment,
      null,
      React.createElement(
        Button,
        { className: "curator-icon-action", size: "sm", variant: open ? "primary" : "secondary", title: "Rate tags", "aria-label": "Rate tags", "aria-pressed": open, onClick: toggle },
        React.createElement(FontAwesomeIcon, { icon: faTag })
      ),
      open && React.createElement(
        RatingPopover,
        { anchor, onClose: () => setOpen(false) },
        React.createElement("div", { className: "curator-external-tag-rating" },
        React.createElement(
          "div",
          { className: "curator-external-tag-rating-header" },
          React.createElement("strong", null, "Rate tags")
        ),
        loading && React.createElement("small", { role: "status" }, "Matching local tags…"),
        error && React.createElement("small", { className: "text-danger", role: "status" }, error),
        !loading && !error && React.createElement(
          React.Fragment,
          null,
          React.createElement(RatingSection, { title: "Matching local tags", rows: tagChoices.map((tag) => ({ key: tag.tag_id, tag_id: tag.tag_id, name: tag.name, direct_value: tag.direct_value, direct_blocked: tag.direct_blocked })), onAnswer: answerTag, emptyLabel: "No matching local tags." })
        ))
      )
    );
  }

  const TASTE_PROFILE_PAGE_SIZE = 30;
  // `initialStatus` lets Curate open this as a queue ("Needs answer") rather
  // than the full ~1000-tag list Manage shows. `initialQuery` seeds the
  // search box so the Impact view's "Fix in Tag sentiment" action lands on
  // the tag in question.
  function TasteProfilePanel({ embedded = false, initialStatus = "all", initialQuery = "" } = {}) {
    const [data, setData] = React.useState(null);
    const [error, setError] = React.useState("");
    const [query, setQuery] = React.useState(initialQuery);
    const [sort, setSort] = React.useState("suggested");
    const [status, setStatus] = React.useState(initialStatus);
    const [page, setPage] = useUrlPage("page_taste");
    useCuratorActivity("taste", !data && !error, "Loading taste profile…");
    React.useEffect(() => {
      let active = true;
      operation({ operation: "get_taste_profile" }).then(
        (value) => active && setData(value),
        (failure) => active && setError(failure.message)
      );
      return () => { active = false; };
    }, []);
    function answer(tagId, {value, blocked}) {
      submitTagPreference(tagId, {value, blocked});
      setData((current) => ({ ...current, items: current.items.map((item) => item.tag_id === tagId ? { ...item, direct_value: value, direct_blocked: !!blocked, prompt: null } : item) }));
    }
    const visibleItems = data
      ? data.items
          .filter((item) =>
            item.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
            && (status === "all" || (status === "answered") === (item.direct_value !== null))
          )
      : [];
    if (sort !== "suggested") {
      visibleItems.sort((left, right) => {
        const difference = sort === "confidence"
          ? right.confidence - left.confidence
          : right.scene_count - left.scene_count;
        return difference || left.name.localeCompare(right.name);
      });
    }
    // Taste Profile can hold ~1,000 tags fetched in one get_taste_profile
    // call; rendering every visibleItems row unpaginated made the Manage
    // document tens of thousands of pixels tall (the root cause of the
    // "unbounded Manage page height" bug — see round 11's sticky section
    // list, which only masked the symptom). Paginate client-side since the
    // full filtered/sorted list is already in memory.
    React.useEffect(() => setPage(1, { replace: true }), [query, status, sort]);
    const totalPages = Math.max(1, Math.ceil(visibleItems.length / TASTE_PROFILE_PAGE_SIZE));
    React.useEffect(() => { if (page > totalPages) setPage(totalPages, { replace: true }); }, [page, totalPages]);
    const pageItems = visibleItems.slice((page - 1) * TASTE_PROFILE_PAGE_SIZE, page * TASTE_PROFILE_PAGE_SIZE);
    return React.createElement(
      "section",
      { className: "curator-taste", "aria-labelledby": embedded ? undefined : "curator-taste-title" },
      !embedded && React.createElement("h2", { id: "curator-taste-title" }, "Taste Profile"),
      React.createElement("p", null, "Declared answers are strong evidence, not hard exclusions. Clear an answer to return to behavior-derived inference."),
      React.createElement(
        "div",
        { className: "curator-taste-toolbar" },
        React.createElement("input", { className: "form-control form-control-sm", type: "search", value: query, onChange: (event) => setQuery(event.target.value), placeholder: "Search tags…", "aria-label": "Search taste profile tags" }),
        React.createElement("select", { className: "form-control form-control-sm", value: status, onChange: (event) => setStatus(event.target.value), "aria-label": "Filter taste profile tags" },
          React.createElement("option", { value: "all" }, "All tags"),
          React.createElement("option", { value: "unanswered" }, "Needs answer"),
          React.createElement("option", { value: "answered" }, "Answered")
        ),
        React.createElement("select", { className: "form-control form-control-sm", value: sort, onChange: (event) => setSort(event.target.value), "aria-label": "Sort taste profile" },
          React.createElement("option", { value: "suggested" }, "Suggested"),
          React.createElement("option", { value: "confidence" }, "Confidence"),
          React.createElement("option", { value: "scenes" }, "Scene count")
        )
      ),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      !data && !error && React.createElement("div", { role: "status" }, "Loading taste profile…"),
      data && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No supported tags are available yet."),
      data && data.items.length > 0 && visibleItems.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No tags match that search."),
      data && React.createElement(
        "div",
        { className: "curator-taste-list" },
        pageItems.map((item) =>
          React.createElement(
            "article",
            { key: item.tag_id, className: "curator-taste-item" },
            React.createElement("div", null,
              React.createElement("strong", null, React.createElement(NavLink, { to: `/tags/${item.tag_id}`, title: `Review scenes tagged ${item.name}` }, item.name)),
              item.prompt && React.createElement("span", { className: `badge ${item.prompt === "belief" ? nearestSentiment(item.inferred_value)[2] : "curator-sentiment-neutral"}` }, item.prompt === "belief" ? beliefSentence(item.inferred_value) : "I'm unsure"),
              React.createElement("small", null, `Inferred ${item.inferred_value.toFixed(2)} · confidence ${item.confidence.toFixed(2)} · support ${item.support.toFixed(1)} · ${item.scene_count} local scene${item.scene_count === 1 ? "" : "s"}`)
            ),
            React.createElement(ConfidencePips, { confidence: item.confidence }),
            React.createElement(TagSentimentControl, { tag: item, value: item.direct_value, blocked: item.direct_blocked, inferredValue: item.inferred_value, onChange: (value) => answer(item.tag_id, value) })
          )
        )
      ),
      data && visibleItems.length > 0 && React.createElement(Pager, { page, total: visibleItems.length, pageSize: TASTE_PROFILE_PAGE_SIZE, hasMore: page * TASTE_PROFILE_PAGE_SIZE < visibleItems.length, loading: false, onPage: setPage, label: "Taste profile pages" })
    );
  }

  function CurationVerdictBar({ label, rate, wins, appearances }) {
    return React.createElement(
      "div",
      { className: "curator-pick-verdict-card" },
      React.createElement("span", { className: "curator-pick-verdict-label" }, label),
      React.createElement(
        "div",
        { className: "curator-pick-verdict-track" },
        React.createElement("div", { className: "curator-pick-verdict-fill", style: { width: `${Math.max(0, Math.min(100, Math.round(rate * 100)))}%` } })
      ),
      React.createElement("span", { className: "curator-pick-verdict-count" }, `${wins}/${appearances}`)
    );
  }

  function PickSceneCard({ meta, picked, onPick, onFlag }) {
    return React.createElement(
      "button",
      { type: "button", className: `curator-pick-card${picked ? " curator-pick-selected" : ""}`, onClick: onPick, "aria-pressed": !!picked },
      React.createElement(
        "div",
        { className: "curator-pick-media" },
        React.createElement("video", { className: "curator-pick-video", src: `/scene/${meta.scene_id}/preview`, poster: `/scene/${meta.scene_id}/screenshot`, muted: true, loop: true, playsInline: true, autoPlay: true, preload: "auto" })
      ),
      React.createElement(
        "div",
        { className: "curator-pick-info" },
        React.createElement("img", { className: "curator-pick-cover", src: `/scene/${meta.scene_id}/screenshot`, alt: "" }),
        React.createElement(
          "div",
          { className: "curator-pick-info-body" },
          meta.title && React.createElement("div", { className: "curator-pick-title" }, meta.title),
          (meta.studio || meta.date) && React.createElement("div", { className: "curator-pick-meta" }, [meta.studio, meta.date].filter(Boolean).join(" · ")),
          meta.performers && meta.performers.length > 0 && React.createElement("div", { className: "curator-pick-performers" }, meta.performers.map((performer) => React.createElement("span", { key: performer.performer_id, className: "badge badge-secondary" }, performer.name))),
          meta.details && React.createElement("div", { className: "curator-pick-details" }, meta.details),
          meta.tags.length > 0 && React.createElement("div", { className: "curator-pick-tags" }, meta.tags.slice(0, 4).map((tag) => React.createElement("span", { key: tag.tag_id, className: "badge badge-light" }, tag.name))),
          React.createElement("span", { role: "button", className: "curator-pick-flag", onClick: (event) => { event.stopPropagation(); onFlag && onFlag(); }, title: "This scene's metadata is wrong — exclude it from the round and the model" }, "Metadata wrong")
        )
      )
    );
  }

  function fmtDelta(value) {
    const abs = Math.abs(value);
    const digits = abs >= 0.01 ? 3 : abs >= 0.001 ? 4 : 5;
    return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
  }

  function ImpactSceneCard({ entry, onCorrect }) {
    // Explain each mover in plain terms: what kind of thing changed, which way
    // the model's preference for it moved, and whether it connects to the
    // user's own feedback (via_feedback = rated/compared scenes carrying it).
    const why = (entry.contributors || []).map((contributor) => {
      if (contributor.kind === "direct") {
        return `your own feedback on this scene (${fmtDelta(contributor.delta)})`;
      }
      const directionWord = contributor.delta >= 0 ? "more preferred" : "less preferred";
      const via = typeof contributor.via_feedback === "number" ? contributor.via_feedback : 0;
      const viaText = via > 0
        ? ` · from ${via} of your ${via === 1 ? "scene" : "scenes"}`
        : " · no rated scene — from a pick or tag preference";
      return `${contributor.kind} "${contributor.name}" ${directionWord} (${fmtDelta(contributor.delta)})${viaText}`;
    }).join(" · ");
    // The scene's delta is the net of its whole feature set; the breakdown
    // splits it by source so the user can see whether a move came mainly from
    // a tag, a performer, the content/theme it belongs to, or their own
    // feedback on this scene.
    const bd = entry.breakdown || {};
    const breakdownParts = [];
    if (typeof bd.your_feedback === "number") breakdownParts.push(`your feedback ${fmtDelta(bd.your_feedback)}`);
    if (typeof bd.tag_preference === "number") breakdownParts.push(`tags ${fmtDelta(bd.tag_preference)}`);
    if (typeof bd.performer_preference === "number") breakdownParts.push(`performers ${fmtDelta(bd.performer_preference)}`);
    if (typeof bd.content_similarity === "number") breakdownParts.push(`content/theme ${fmtDelta(bd.content_similarity)}`);
    const breakdownText = breakdownParts.join(" · ");
    // Reversing the move: a wrongly promoted scene is corrected downward, a
    // wrongly demoted one upward.
    const direction = entry.delta >= 0 ? "down" : "up";
    const [marked, setMarked] = React.useState(false);
    const correct = async (event) => {
      event.preventDefault();
      try {
        await operation({ operation: "submit_impact_correction", scene_id: entry.scene_id, direction });
        setMarked(true);
        if (onCorrect) onCorrect();
      } catch (_) {
        // Keep the button enabled on failure so the user can retry.
      }
    };
    return React.createElement(
      "div",
      { className: "curator-impact-scene-row" },
      React.createElement(
        "a",
        { className: "curator-impact-scene", href: `/scenes/${entry.scene_id}`, target: "_blank", rel: "noopener noreferrer" },
        React.createElement("img", { className: "curator-impact-thumb", src: `/scene/${entry.scene_id}/screenshot`, alt: "", loading: "lazy" }),
        React.createElement("div", { className: "curator-impact-scene-body" },
          React.createElement("div", { className: "curator-impact-scene-title" }, entry.title || `Scene ${entry.scene_id}`),
          breakdownText && React.createElement("div", { className: "curator-impact-scene-why" }, "Move came from: ", breakdownText),
          why && React.createElement("div", { className: "curator-impact-scene-why", title: whyTitle }, "Details: ", why)
        ),
        React.createElement("span", { className: `curator-impact-delta ${entry.delta >= 0 ? "up" : "down"}` }, fmtDelta(entry.delta))
      ),
      React.createElement("button", {
        className: "curator-impact-correct",
        onClick: correct,
        disabled: marked,
        title: `Mark this ${entry.delta >= 0 ? "promotion" : "demotion"} as wrong`,
      }, marked ? "Marked" : "Wrong")
    );
  }

  function ImpactPerformerCard({ entry }) {
    return React.createElement(
      "a",
      { className: "curator-impact-person", href: `/performers/${entry.performer_id}`, target: "_blank", rel: "noopener noreferrer" },
      React.createElement("img", { className: "curator-impact-avatar", src: `/performer/${entry.performer_id}/image`, alt: "", loading: "lazy" }),
      React.createElement("span", { className: "curator-impact-person-name" }, entry.name || `Performer ${entry.performer_id}`),
      React.createElement("span", { className: `curator-impact-delta ${entry.delta >= 0 ? "up" : "down"}` }, fmtDelta(entry.delta))
    );
  }

  function ImpactTagCard({ entry }) {
    return React.createElement(
      "a",
      { className: "curator-impact-tag", href: `/tags/${entry.tag_id}`, target: "_blank", rel: "noopener noreferrer" },
      React.createElement("span", { className: "curator-impact-tag-name" }, entry.name || entry.tag_id),
      React.createElement("span", { className: `curator-impact-delta ${entry.delta >= 0 ? "up" : "down"}` }, fmtDelta(entry.delta))
    );
  }

  function ImpactList({ title, entries, renderer, tone }) {
    if (!entries || entries.length === 0) return null;
    return React.createElement(
      "div",
      { className: `curator-impact-list curator-impact-${tone}` },
      React.createElement("div", { className: "curator-impact-list-title" }, title),
      entries.map(renderer)
    );
  }

  function ImpactReport({ impact, onCorrect }) {
    const maxMove = (group) => Math.max(
      0,
      ...(group.promoted || []).map((entry) => Math.abs(entry.delta)),
      ...(group.demoted || []).map((entry) => Math.abs(entry.delta))
    );
    const weakNote = (group, label) => maxMove(group) < 0.005 && React.createElement("p", { className: "curator-impact-weak" }, `${label} barely moved this build — new picks since the previous build will show up here.`);
    return React.createElement(
      "div",
      { className: "curator-impact" },
      React.createElement("h4", { className: "curator-impact-heading" }, "What your picks moved"),
      React.createElement("p", { className: "curator-impact-ago" }, `Newest model built ${new Date(impact.published_at_ms).toLocaleString()} — the feedback since the previous build is what moved these.`),
      React.createElement("p", { className: "curator-impact-legend" },
        "A scene's delta is how much its appeal moved (−1 to 1). “Because” lists the tags/performers whose learned preference changed, tied back to how many of your rated/compared scenes carry each one."
      ),
      React.createElement(
        "div",
        { className: "curator-impact-groups" },
        React.createElement(
          "div",
          { className: "curator-impact-group" },
          React.createElement("div", { className: "curator-impact-group-label" }, "Scenes"),
            impact.scenes.promoted.length === 0 && impact.scenes.demoted.length === 0 && React.createElement("p", { className: "curator-impact-weak" }, "No scene moves came from your feedback this build — new picks since the previous build will show up here."),
          React.createElement("div", { className: "curator-impact-columns" },
            React.createElement(ImpactList, { title: "Promoted", entries: impact.scenes.promoted, renderer: (entry) => React.createElement(ImpactSceneCard, { key: entry.scene_id, entry, onCorrect }), tone: "up" }),
            React.createElement(ImpactList, { title: "Demoted", entries: impact.scenes.demoted, renderer: (entry) => React.createElement(ImpactSceneCard, { key: entry.scene_id, entry, onCorrect }), tone: "down" })
          )
        ),
        React.createElement(
          "div",
          { className: "curator-impact-group" },
          React.createElement("div", { className: "curator-impact-group-label" }, "Performers"),
          weakNote(impact.performers, "Performers"),
          React.createElement("div", { className: "curator-impact-columns" },
            React.createElement(ImpactList, { title: "Promoted", entries: impact.performers.promoted, renderer: (entry) => React.createElement(ImpactPerformerCard, { key: entry.performer_id, entry }), tone: "up" }),
            React.createElement(ImpactList, { title: "Demoted", entries: impact.performers.demoted, renderer: (entry) => React.createElement(ImpactPerformerCard, { key: entry.performer_id, entry }), tone: "down" })
          )
        ),
        React.createElement(
          "div",
          { className: "curator-impact-group" },
          React.createElement("div", { className: "curator-impact-group-label" }, "Tags"),
          weakNote(impact.tags, "Tags"),
          React.createElement("div", { className: "curator-impact-columns" },
            React.createElement(ImpactList, { title: "Promoted", entries: impact.tags.promoted, renderer: (entry) => React.createElement(ImpactTagCard, { key: entry.tag_id, entry }), tone: "up" }),
            React.createElement(ImpactList, { title: "Demoted", entries: impact.tags.demoted, renderer: (entry) => React.createElement(ImpactTagCard, { key: entry.tag_id, entry }), tone: "down" })
          )
        )
      )
    );
  }

  // ── Curate ────────────────────────────────────────────────────────────────

  const CURATE_STREAM_BUDGET = 10;
  // Fetch the next round this many pairs before the current one runs out, so
  // the stream never stalls on a round trip mid-flow.
  const CURATE_PREFETCH_MARGIN = 3;
  // An answer commits when the next one is given, or after this idle gap.
  // Buffering exactly one keeps single-step undo without needing a reversal
  // path for feedback that has already been written.
  const CURATE_COMMIT_IDLE_MS = 4000;
  // Long enough to read as a confirmation, short enough not to gate input:
  // the old 500ms lock cost five seconds of dead time every ten picks.
  const CURATE_FLASH_MS = 260;
  const LAST_ROUND_KEY = "stash-curator:last-pick-round:v1";

  function readLastRound() {
    try {
      const value = JSON.parse(localStorage.getItem(LAST_ROUND_KEY) || "null");
      return value && value.round_id ? value : null;
    } catch (_) {
      return null;
    }
  }

  function writeLastRound(roundId, dimension) {
    try {
      localStorage.setItem(LAST_ROUND_KEY, JSON.stringify({ round_id: roundId, dimension }));
    } catch (_) {
      // Progress falls back to "no comparisons yet" if storage is unavailable.
    }
  }

  // The tags carried by the pair currently on screen, offered as a compact
  // rate-strip so sentiment can be taught in context instead of only from the
  // separate Tag sentiment list.
  function PairTagSentiment({ pair }) {
    const [selected, setSelected] = React.useState(null);
    const [answers, setAnswers] = React.useState({});
    const tags = [];
    const seen = new Set();
    for (const scene of [pair.scene_a, pair.scene_b]) {
      for (const tag of scene.tags || []) {
        if (!seen.has(tag.tag_id)) {
          seen.add(tag.tag_id);
          tags.push(tag);
        }
      }
    }
    if (!tags.length) return null;
    function answer(tag, { value, blocked }) {
      submitTagPreference(tag.tag_id, { value, blocked });
      setAnswers((current) => ({ ...current, [tag.tag_id]: { value, blocked } }));
      setSelected(null);
    }
    return React.createElement(
      "div",
      { className: "curator-pick-tag-strip" },
      React.createElement("span", { className: "curator-pick-tag-strip-label" }, "Rate a tag while you're here"),
      React.createElement(
        "div",
        { className: "curator-pick-tag-strip-items" },
        tags.slice(0, 8).map((tag) => React.createElement(
          "div",
          { key: tag.tag_id, className: "curator-pick-tag-strip-item" },
          React.createElement(
            Button,
            {
              size: "sm",
              variant: selected === tag.tag_id ? "primary" : "secondary",
              onClick: () => setSelected(selected === tag.tag_id ? null : tag.tag_id),
            },
            tag.name,
            Object.hasOwn(answers, tag.tag_id) && React.createElement(FontAwesomeIcon, { icon: faCheckCircle })
          ),
          selected === tag.tag_id && React.createElement(TagSentimentControl, {
            tag,
            value: answers[tag.tag_id]?.value,
            blocked: answers[tag.tag_id]?.blocked,
            compact: true,
            onChange: (value) => answer(tag, value),
          })
        ))
      )
    );
  }

  // The comparison surface itself: two cards, the answer controls, and the
  // in-context tag strip. Shared by Stream and Test-an-idea so both flows
  // behave identically once a pair is on screen.
  function PickStage({ pair, flash, onAnswer, onBack, canGoBack, status }) {
    const flashWinner = flash && flash.pairId === pair.pair_id ? flash.winner : null;
    return React.createElement(
      "div",
      { className: "curator-pick-compare" },
      React.createElement("div", { className: "curator-pick-tally" }, status),
      React.createElement(
        "div",
        { className: "curator-pick-cards" },
        React.createElement(PickSceneCard, {
          meta: pair.scene_a,
          picked: flashWinner === "a",
          onPick: () => onAnswer("a"),
          onFlag: () => onAnswer("flag_a"),
        }),
        React.createElement("span", { className: "curator-pick-vs", "aria-hidden": "true" }, "vs"),
        React.createElement(PickSceneCard, {
          meta: pair.scene_b,
          picked: flashWinner === "b",
          onPick: () => onAnswer("b"),
          onFlag: () => onAnswer("flag_b"),
        })
      ),
      React.createElement(
        "div",
        { className: "curator-pick-controls" },
        React.createElement(
          "div",
          { className: "curator-pick-nav-group", role: "group", "aria-label": "Navigate picks" },
          React.createElement(Button, { size: "sm", variant: "secondary", disabled: !canGoBack, onClick: onBack, title: "Undo the previous answer (Backspace)" }, "Back")
        ),
        React.createElement(
          "div",
          { className: "curator-pick-answer-group", role: "group", "aria-label": "Rate this comparison", title: "Keys: ←/→ pick · ↑ equal · ↓ skip" },
          React.createElement(Button, { size: "sm", variant: "primary", title: "← pick", onClick: () => onAnswer("a") }, "← Left"),
          React.createElement(Button, { size: "sm", variant: "primary", title: "→ pick", onClick: () => onAnswer("b") }, "Right →"),
          React.createElement(Button, { size: "sm", variant: "secondary", title: "↑ equally appealing", onClick: () => onAnswer("tie") }, "Equal ↑"),
          React.createElement(Button, { size: "sm", variant: "secondary", title: "↓ no opinion", onClick: () => onAnswer("skip") }, "Skip ↓")
        )
      ),
      React.createElement(PairTagSentiment, { key: pair.pair_id, pair })
    );
  }

  // Shared answer plumbing for both pick flows: flash, keyboard, and a
  // single-pick commit buffer. Answers post as they happen — there is no
  // submit gate — but the most recent one stays uncommitted briefly so Back
  // can take it away without reversing feedback that already landed.
  function usePickAnswers({ onCommitted }) {
    const [flash, setFlash] = React.useState(null);
    const [pending, setPending] = React.useState(null);
    const [error, setError] = React.useState("");
    const pendingRef = React.useRef(null);
    pendingRef.current = pending;

    const commit = React.useCallback(async (entry) => {
      if (!entry) return;
      try {
        await operation({
          operation: "submit_curation_picks",
          round_id: entry.roundId,
          picks: [entry.pick],
        });
        writeLastRound(entry.roundId, entry.dimension);
        if (onCommitted) onCommitted(entry);
      } catch (failure) {
        setError(failure.message);
      }
    }, [onCommitted]);

    // Idle commit: an answer left alone is no longer being second-guessed.
    React.useEffect(() => {
      if (!pending) return;
      const timer = setTimeout(() => {
        commit(pending);
        setPending((current) => (current === pending ? null : current));
      }, CURATE_COMMIT_IDLE_MS);
      return () => clearTimeout(timer);
    }, [pending, commit]);

    // Navigating away must not silently drop the buffered answer.
    React.useEffect(() => () => commit(pendingRef.current), [commit]);

    return { flash, setFlash, pending, setPending, error, setError, commit };
  }

  function pickEntry(roundId, dimension, pairId, answer) {
    const pick = answer === "flag_a" || answer === "flag_b"
      ? { pair_id: pairId, winner: "flag", scene: answer === "flag_a" ? "a" : "b" }
      : { pair_id: pairId, winner: answer };
    return { roundId, dimension, pairId, answer, pick };
  }

  function CurateStream() {
    const [queue, setQueue] = React.useState([]);
    const [index, setIndex] = React.useState(0);
    const [tally, setTally] = React.useState({ left: 0, right: 0, tie: 0, skip: 0 });
    const [loading, setLoading] = React.useState(true);
    const [exhausted, setExhausted] = React.useState(false);
    const fetching = React.useRef(false);
    const { flash, setFlash, pending, setPending, error, setError, commit } = usePickAnswers({});
    useCuratorActivity("curate-stream", loading, "Finding comparisons…");

    const fetchMore = React.useCallback(async () => {
      if (fetching.current) return;
      fetching.current = true;
      try {
        const round = await operation({
          operation: "get_curation_picks",
          dimension: "orthogonal",
          budget: CURATE_STREAM_BUDGET,
          base_tag_id: "",
          context_tag_id: "",
        });
        const fetched = (round.pairs || []).map((pair) => ({ roundId: round.round_id, pair }));
        if (!fetched.length) setExhausted(true);
        else setQueue((current) => [...current, ...fetched]);
      } catch (failure) {
        setError(failure.message);
      } finally {
        fetching.current = false;
        setLoading(false);
      }
    }, [setError]);

    React.useEffect(() => { fetchMore(); }, [fetchMore]);
    React.useEffect(() => {
      if (!exhausted && !loading && queue.length - index <= CURATE_PREFETCH_MARGIN) fetchMore();
    }, [queue.length, index, exhausted, loading, fetchMore]);

    const entry = queue[index];

    function answer(value) {
      if (flash || !entry) return;
      setFlash({ pairId: entry.pair.pair_id, winner: value });
    }

    function back() {
      if (!pending || index === 0) return;
      setPending(null);
      setIndex((current) => current - 1);
      setTally((current) => {
        const key = { a: "left", b: "right", tie: "tie" }[pending.answer] || "skip";
        return { ...current, [key]: Math.max(0, current[key] - 1) };
      });
    }

    React.useEffect(() => {
      if (!flash) return;
      const timer = setTimeout(() => {
        const current = queue[index];
        setFlash(null);
        if (!current) return;
        // The previous answer is now settled; this one becomes the undoable one.
        commit(pending);
        setPending(pickEntry(current.roundId, "orthogonal", current.pair.pair_id, flash.winner));
        setTally((counts) => {
          const key = { a: "left", b: "right", tie: "tie" }[flash.winner] || "skip";
          return { ...counts, [key]: counts[key] + 1 };
        });
        setIndex((value) => value + 1);
      }, CURATE_FLASH_MS);
      return () => clearTimeout(timer);
    }, [flash]);

    React.useEffect(() => {
      function onKey(event) {
        if (flash || !entry) return;
        const key = { ArrowLeft: "a", ArrowRight: "b", ArrowUp: "tie", ArrowDown: "skip" }[event.key];
        if (key) {
          event.preventDefault();
          answer(key);
        } else if (event.key === "Backspace") {
          event.preventDefault();
          back();
        }
      }
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [entry, flash, pending, index]);

    const answered = tally.left + tally.right + tally.tie + tally.skip;
    return React.createElement(
      "div",
      { className: "curator-pick" },
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      loading && !entry && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Finding comparisons…")),
      !loading && !entry && exhausted && React.createElement(
        "div",
        { className: "alert alert-info" },
        React.createElement("p", null, answered > 0
          ? `That is every comparison your library can offer right now — ${answered} answered this session.`
          : "No useful comparisons are available yet. Rate a few scenes in Stash, sync your library, then try again."),
        React.createElement("p", null, "New scenes, and the next model build, open up more.")
      ),
      entry && React.createElement(PickStage, {
        pair: entry.pair,
        flash,
        onAnswer: answer,
        onBack: back,
        canGoBack: Boolean(pending) && index > 0,
        status: `${answered} answered · left ${tally.left} · right ${tally.right} · equal ${tally.tie} · skipped ${tally.skip}`,
      }),
      // Warm the next pair's stills so advancing does not flash empty cards.
      queue[index + 1] && React.createElement(
        "div",
        { className: "curator-pick-prefetch", "aria-hidden": "true" },
        [queue[index + 1].pair.scene_a, queue[index + 1].pair.scene_b].map((scene) =>
          React.createElement("img", { key: scene.scene_id, src: `/scene/${scene.scene_id}/screenshot`, alt: "", loading: "eager" })
        )
      )
    );
  }

  function CurateProgress({ onFixTag }) {
    const [verdict, setVerdict] = React.useState(null);
    const [impact, setImpact] = React.useState(null);
    const [profile, setProfile] = React.useState(null);
    const [error, setError] = React.useState("");
    const [applying, setApplying] = React.useState(false);
    const last = React.useRef(readLastRound()).current;
    useCuratorActivity("curate-progress", !verdict && !error && Boolean(last), "Loading your impact…");

    const refresh = React.useCallback(async () => {
      if (last) {
        try {
          setVerdict(await operation({
            operation: "get_curation_pair_verdict",
            round_id: last.round_id,
          }));
        } catch (failure) {
          setError(failure.message);
        }
      }
      try {
        setImpact(await operation({ operation: "get_curation_impact" }));
      } catch (_) {
        // Impact needs two model builds and their artifacts; absence is normal.
      }
      try {
        setProfile(await operation({ operation: "get_taste_profile" }));
      } catch (_) {
        // Needs a published model; the verdict and impact sections still work.
      }
    }, [last]);

    React.useEffect(() => { refresh(); }, [refresh]);

    async function applyNow() {
      setApplying(true);
      try {
        await applyFeedbackAndAwaitBuild();
        await refresh();
      } finally {
        setApplying(false);
      }
    }

    const items = (verdict && verdict.items) || [];
    const profileItems = (profile && profile.items) || [];
    const answeredTags = profileItems.filter((tag) => tag.direct_value !== null).length;
    const blockedTags = profileItems.filter((tag) => tag.direct_blocked).length;
    // Declared answers that still disagree with the model's inference are the
    // fastest teaching opportunities; surface the biggest gaps with a jump
    // straight to that tag's control in Tag sentiment.
    const divergences = profileItems
      .filter((tag) => tag.direct_value !== null
        && Math.abs(Number(tag.direct_value) - Number(tag.inferred_value)) >= 0.3)
      .sort((left, right) =>
        Math.abs(Number(right.direct_value) - Number(right.inferred_value))
        - Math.abs(Number(left.direct_value) - Number(left.inferred_value)))
      .slice(0, 12);
    return React.createElement(
      "div",
      { className: "curator-curate-verdict" },
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      !last && profileItems.length === 0 && !(impact && impact.available) && React.createElement("div", { className: "alert alert-info" }, "No comparisons yet. Answer a few in Pair picks and this fills in."),
      (verdict || profileItems.length > 0 || (impact && impact.available)) && React.createElement(
        "div",
        { className: "curator-impact-summary" },
        verdict && React.createElement("span", null, `${verdict.n_answered} comparisons answered`),
        profileItems.length > 0 && React.createElement("span", null, `${answeredTags} tags answered${blockedTags > 0 ? ` · ${blockedTags} blocked` : ""}`),
        impact && impact.available && React.createElement("span", null, `Model built ${formatTimeAgo(impact.published_at_ms)}`)
      ),
      verdict && React.createElement("p", { className: "curator-pick-verdict-summary" },
        `${verdict.n_answered} comparisons answered so far · win rates for the tags that differed between scenes`
      ),
      items.length > 0 && React.createElement(
        "div",
        { className: "curator-pick-verdict-grid" },
        items.slice(0, 12).map((item) => React.createElement(CurationVerdictBar, {
          key: item.tag_id || item.name,
          label: item.name,
          rate: item.win_rate,
          wins: item.wins,
          appearances: item.appearances,
        }))
      ),
      verdict && items.length === 0 && React.createElement("p", null, "No tag has appeared in enough comparisons to report on yet."),
      items.length > 0 && React.createElement("p", { className: "curator-pick-verdict-note" },
        "Rates start near 50% and separate as comparisons accumulate, so an early lead is a hint rather than a verdict."
      ),
      divergences.length > 0 && React.createElement(
        "section",
        { className: "curator-sentiment-divergence" },
        React.createElement("h3", null, "Where your answers and the model disagree"),
        React.createElement("p", { className: "curator-impact-weak" }, "Tags you answered directly where the model's inference still differs by at least 0.3. Straightening these out teaches the model fastest."),
        divergences.map((tag) => React.createElement(
          "div",
          { key: tag.tag_id, className: "curator-sentiment-divergence-row" },
          React.createElement("div", { className: "curator-sentiment-divergence-copy" },
            React.createElement("strong", null, tag.name),
            React.createElement("span", null, `Declared ${formatSigned(Number(tag.direct_value))} · inferred ${formatSigned(Number(tag.inferred_value))} · confidence ${tag.confidence.toFixed(2)}`)
          ),
          React.createElement(Button, { size: "sm", variant: "secondary", onClick: () => onFixTag(tag.tag_id) }, "Fix in Tag sentiment")
        ))
      ),
      React.createElement(
        "div",
        { className: "curator-pick-controls" },
        React.createElement(Button, { size: "sm", variant: "secondary", disabled: applying, onClick: applyNow },
          applying ? "Applying…" : "Apply my answers to the model now"
        )
      ),
      impact && impact.available && React.createElement(ImpactReport, { impact, onCorrect: refresh }),
      impact && !impact.available && React.createElement("p", { className: "curator-impact-weak" },
        "The impact report compares two model builds — it appears once Curator has built the model at least twice."
      )
    );
  }

  function CuratePanel({ section, onSelectSection, sentimentQuery }) {
    const active = CURATE_SECTIONS.find((item) => item.value === section) || CURATE_SECTIONS[0];
    const bodies = {
      stream: () => React.createElement(CurateStream),
      sentiment: () => React.createElement(TasteProfilePanel, { embedded: true, initialQuery: sentimentQuery }),
      progress: () => React.createElement(CurateProgress, { onFixTag: (tagId) => onSelectSection("sentiment", { sentTag: tagId }) }),
    };
    return React.createElement(
      "div",
      { className: "curator-curate" },
      React.createElement(
        "div",
        { className: "curator-curate-switcher", role: "tablist", "aria-label": "Curate sections" },
        CURATE_SECTIONS.map((item) => React.createElement(
          "button",
          {
            key: item.value,
            type: "button",
            className: "curator-lane-card",
            style: { "--lc": "var(--curator-hue-curate)" },
            "aria-pressed": item.value === active.value,
            "aria-label": item.label,
            onClick: () => onSelectSection(item.value),
            title: item.description,
          },
          React.createElement("span", { className: "curator-lane-card-icon" }, React.createElement(FontAwesomeIcon, { icon: item.icon })),
          React.createElement("span", { className: "curator-lane-card-name" }, item.label),
          React.createElement("span", { className: "curator-lane-card-desc" }, item.description)
        ))
      ),
      React.createElement(
        "div",
        { className: "curator-curate-head" },
        React.createElement("h2", null, active.label),
        React.createElement("p", null, active.description)
      ),
      bodies[active.value]()
    );
  }

  function TagSentimentFollowUp({ followUp, onDismiss }) {
    const [selected, setSelected] = React.useState(null);
    const [answers, setAnswers] = React.useState({});
    const [status, setStatus] = React.useState("");
    const [busy, setBusy] = React.useState(false);
    function answer(tag, {value, blocked}) {
      submitTagPreference(tag.tag_id, {value, blocked});
      setAnswers((current) => ({ ...current, [tag.tag_id]: {value, blocked} }));
      setSelected(null);
      setStatus(`${tag.name} answer queued`);
    }
    async function metadataWrong() {
      setBusy(true);
      try {
        await operation({
          operation: "submit_feedback",
          entries: [{
            feedback_id: uuid(),
            scene_id: followUp.scene_id,
            feedback_type: "metadata_wrong",
            value: "Do not train from this metadata",
            occurred_at_ms: Date.now(),
          }],
        });
        scheduleModelUpdate();
        onDismiss();
      } catch (error) {
        setStatus(error.message);
      } finally {
        setBusy(false);
      }
    }
    return React.createElement(
      "aside",
      { className: "curator-tag-follow-up alert alert-secondary", "aria-label": "Help Curator understand why" },
      React.createElement("div", { className: "curator-tag-follow-up-heading" },
        React.createElement("strong", null, "Help Curator understand why"),
        React.createElement(Button, { size: "sm", variant: "link", onClick: onDismiss, "aria-label": "Dismiss tag follow-up" }, "×")
      ),
      React.createElement("p", null, "Was a content tag part of the problem? This is optional."),
      followUp.items.map((tag) =>
        React.createElement(
          "div",
          { key: tag.tag_id, className: "curator-tag-follow-up-item" },
          React.createElement(Button, { size: "sm", variant: selected === tag.tag_id ? "primary" : "secondary", onClick: () => setSelected(selected === tag.tag_id ? null : tag.tag_id) }, tag.name),
          Object.hasOwn(answers, tag.tag_id) && React.createElement("small", null, `Answered: ${answers[tag.tag_id]?.blocked ? "Blocked" : SENTIMENTS.find(([value]) => value === answers[tag.tag_id]?.value)?.[1]}`),
          selected === tag.tag_id && React.createElement(TagSentimentControl, { tag, value: answers[tag.tag_id]?.value, blocked: answers[tag.tag_id]?.blocked, compact: true, onChange: (value) => answer(tag, value) })
        )
      ),
      React.createElement(
        "div",
        { className: "curator-tag-follow-up-actions" },
        React.createElement(Button, { size: "sm", variant: "link", onClick: onDismiss }, "None of these"),
        React.createElement(Button, { size: "sm", variant: "link", onClick: onDismiss }, "Something scene-specific"),
        React.createElement(Button, { size: "sm", variant: "link", disabled: busy, onClick: metadataWrong }, "Metadata is wrong"),
        React.createElement(Button, { size: "sm", variant: "link", onClick: onDismiss }, "Skip")
      ),
      status && React.createElement("small", { role: "status" }, status)
    );
  }

  // The always-visible match bar needs to be robust to whatever score
  // shape a caller has — RecommendationCard's final_utility, ExternalCard's
  // basic match score, and SimilarityPanel's rank_score are all "ranking
  // utility, not a probability" (per the cards' own copy) and can exceed 1,
  // and none reliably carry the similarity/appeal/multi-hop breakdown a
  // segmented bar would need — an earlier version tried a segmented bar
  // keyed off item.details.score_breakdown and it silently rendered empty
  // for real Similar-panel results, since that field isn't populated there.
  // A single clamped fill renders every surface's headline score on its
  // documented 0..1 scale: the lane rank is normalized to the lane's best
  // (issue #226 — the top of every lane reads 1.00), Similarity is a 0..1
  // match score, and Prune's appeal is −1..1 with negatives clamped to an
  // empty bar. The previous 1.2 ceiling existed for raw final_utility, which
  // bonuses could push above 1.0 — no current caller passes it (the rank
  // surface now receives the normalized lane_value). Anything that still
  // exceeds 1.0 gets a distinct "off the chart" treatment rather than
  // silently pinning to 100% again.
  function utilityBar(value) {
    const clipped = value > 1;
    const pct = Math.round(clamp01(value) * 100);
    return React.createElement("div", { className: "curator-score-bar" },
      React.createElement("span", { className: `curator-score-bar-seg curator-score-app${clipped ? " curator-score-bar-clipped" : ""}`, style: { width: pct + "%" }, title: `Utility ${value.toFixed(3)}` })
    );
  }

  // Shared explanation shell for RecommendationCard, ExternalCard, and
  // SimilarityPanel library matches. The backend supplies the conversational
  // summary, evidence rows, and typed score data; this shell keeps the same
  // progressive disclosure and accessible labels across every surface.
  // The intrinsic Appeal headline is always visible. Surface-specific
  // Similarity, Match, or lane rank stays separately labeled and unit-bearing;
  // the named component breakdown remains progressively disclosed.
  function EvidenceScore({ evidenceProps, evidenceContent, scoreBarContent, scoreSummary, scoreLabel = "Match", scoreHeadline, scoreHeadlineValue, scoreHeadlineBar, scoreContent, metadataContent, dateContent, descriptionContent, actionsContent }) {
    return React.createElement(
      "div",
      { className: "curator-score-stack" },
      (scoreHeadline || scoreHeadlineBar || dateContent || metadataContent) && React.createElement("div", { className: "curator-score-appeal-row" }, dateContent, scoreHeadline && !["Match", "Appeal"].includes(scoreHeadline) && React.createElement("span", { className: "curator-score-headline" }, scoreHeadline), scoreHeadlineBar && React.createElement("div", { className: "curator-score-headline-bar" }, scoreHeadlineBar), scoreHeadlineValue && React.createElement("strong", { className: "curator-score-headline-value" }, scoreHeadlineValue), metadataContent),
      scoreBarContent && React.createElement("div", { className: "curator-match-row" }, React.createElement("span", { className: "curator-match-label" }, scoreLabel), scoreBarContent, React.createElement("span", { className: "curator-match-value" }, scoreSummary)),
      descriptionContent,
      (evidenceContent !== null || scoreContent || actionsContent) && React.createElement("div", { className: "curator-why-row" },
        (evidenceContent !== null || scoreContent) && React.createElement("details", { className: "curator-evidence", ...evidenceProps }, React.createElement("summary", null, "Why this?"), evidenceContent, scoreContent),
        actionsContent
      )
    );
  }

  // The "external" action-set variant (Stash-box/Whisparr/shortlist), sibling
  // to Feedback's "local" variant (thumbs up/down + More menu).
  function ExternalActions({ item, kind, onShortlist, tagsAvailable, tagsActive, tagLoading, onRateTags, onShowScenes, whisparrEnabled, canWhisparr, whisparr, onAddToWhisparr }) {
    return React.createElement(
      "div",
      { className: "curator-prune-actions" },
      onShortlist && React.createElement(Button, { className: "curator-icon-action", size: "sm", variant: item.shortlisted ? "primary" : "secondary", title: item.shortlisted ? "Remove from shortlist" : "Add to shortlist", "aria-label": item.shortlisted ? "Remove from shortlist" : "Add to shortlist", onClick: () => onShortlist(item, kind) }, React.createElement(FontAwesomeIcon, { icon: faList })),
      kind === "scene" && React.createElement(Button, { className: "curator-icon-action", size: "sm", variant: tagsActive ? "primary" : "secondary", disabled: !tagsAvailable || tagLoading, title: "Rate tags", "aria-label": "Rate tags", onClick: onRateTags }, React.createElement(FontAwesomeIcon, { icon: faTag })),
      kind === "performer" && onShowScenes && React.createElement(Button, { className: "curator-icon-action", size: "sm", variant: "secondary", title: "Show this performer's scenes", "aria-label": "Show this performer's scenes", onClick: () => onShowScenes(item) }, React.createElement(FontAwesomeIcon, { icon: faFilm })),
      kind === "scene" && canWhisparr && React.createElement(Button, { className: "curator-icon-action curator-whisparr-action", size: "sm", variant: "secondary", disabled: !whisparrEnabled || whisparr?.status === "adding" || whisparr?.status === "sent" || whisparr?.status === "already_exists", title: !whisparrEnabled ? "Whisparr requires the StashDB endpoint and configured Whisparr credentials" : whisparr?.status === "error" ? "Retry sending to Whisparr" : "Send to Whisparr", "aria-label": !whisparrEnabled ? "Whisparr requires the StashDB endpoint and configured Whisparr credentials" : whisparr?.status === "error" ? "Retry sending to Whisparr" : "Send to Whisparr", onClick: onAddToWhisparr }, React.createElement("span", { className: "curator-whisparr-logo", "aria-hidden": "true" }, React.createElement("span", { className: "curator-whisparr-fallback" }, "W"), React.createElement("img", { src: WHISPARR_LOGO, alt: "", onError: (event) => event.currentTarget.remove() }))),
      whisparr && React.createElement("small", { className: `curator-whisparr-status ${whisparr.status === "error" ? "text-danger" : ""}`, role: "status" }, whisparr.message)
    );
  }

  function FindThumbnail({ image, imageKey, onImageError, title, href, kind, external = true }) {
    return React.createElement("article", { className: `curator-card curator-find-thumbnail curator-external-card curator-external-${kind} grid-card ${kind}-card` },
      React.createElement("div", { className: "curator-external-thumbnail thumbnail-section" },
        React.createElement("a", { className: `${kind}-card-link`, href, "aria-label": title, target: external ? "_blank" : undefined, rel: external ? "noreferrer" : undefined },
          image ? React.createElement("img", { key: imageKey, className: `${kind}-card-image`, src: image, onError: onImageError, loading: "lazy", alt: "" })
            : React.createElement("div", { className: "curator-card-placeholder" }, title)
        )
      ),
      React.createElement("div", { className: "card-section", hidden: true }, React.createElement("span", { className: "card-section-title" }, title))
    );
  }
  function PerformerHuntLink({ performer, external = false, className = "curator-performer-hunt" }) {
    const query = new URLSearchParams({ view: "hunt", performer: String(performer.id), label: performer.name || "" });
    if (external) query.set("ext", "1");
    const label = `Hunt scenes featuring ${performer.name || "this performer"}`;
    return React.createElement(NavLink, { className, to: `/plugins/stash-curator?${query}`, title: label, "aria-label": label, onClick: (event) => event.stopPropagation() }, React.createElement(FontAwesomeIcon, { icon: faCrosshairs }));
  }

  Api.patch.before("HoverPopover", function (props, ...args) {
    if (window.location.pathname !== "/plugins/stash-curator" || props.className !== "performer-count") return [props, ...args];
    const content = React.Children.map(props.content, (row) => {
      if (!React.isValidElement(row)) return row;
      const children = React.Children.toArray(row.props.children);
      const performer = children.find((child) => child?.props?.performer)?.props.performer;
      if (!performer) return row;
      return React.cloneElement(row, {}, React.Children.map(children, (child) => {
        if (!child?.props?.className?.split(" ").includes("performer-tag")) return child;
        return React.createElement("div", { className: "curator-performer-image-actions" }, child, React.createElement(PerformerHuntLink, { performer }));
      }));
    });
    return [{ ...props, content }, ...args];
  });

  function stashboxEntityURL(payload, kind, id, entity = payload) {
    try {
      const url = new URL(payload.curator_endpoint || "https://stashdb.org/graphql");
      if (!["https:", "http:"].includes(url.protocol)) return undefined;
      if (url.hostname === "theporndb.net" && kind === "performers" && entity.curator_site_performer) kind = "performer-sites";
      url.pathname = `${url.pathname.replace(/\/graphql\/?$/i, "").replace(/\/$/, "")}/${kind}/${encodeURIComponent(id)}`;
      url.search = "";
      url.hash = "";
      return url.href;
    } catch (_) {
      return undefined;
    }
  }

  function externalImageProps(images) {
    const urls = [...new Set((images || []).map((image) => image.url).filter((url) => typeof url === "string" && url))];
    return {
      key: urls.join("\n"),
      src: urls[0],
      onError: (event) => {
        const image = event.currentTarget;
        const next = urls.indexOf(image.getAttribute("src")) + 1;
        if (next > 0 && next < urls.length) image.src = urls[next];
        else image.style.visibility = "hidden";
      },
    };
  }

  function ExternalStudioLink({ payload }) {
    const [failed, setFailed] = React.useState(false);
    const studio = payload.studio;
    if (!studio?.name) return null;
    const image = externalImageProps(studio.images);
    return React.createElement("a", {
      className: !failed && image.src ? "sticky-studio sticky-studio--top" : "curator-external-studio-name",
      href: stashboxEntityURL(payload, "studios", studio.id), target: "_blank", rel: "noreferrer", title: studio.name,
    }, !failed && image.src ? React.createElement("img", {
      ...image, alt: studio.name, loading: "lazy", onError: (event) => {
        image.onError(event);
        if (event.currentTarget.style.visibility === "hidden") setFailed(true);
      },
    }) : studio.name);
  }

  function ExternalMetadataRow({ payload, items, kind }) {
    const [anchor, setAnchor] = React.useState(null);
    if (!items.length) return null;
    const performers = kind === "performer";
    function link(item, className) {
      const local = item.curator_local;
      return React.createElement(local ? NavLink : "a", {
        key: item.id, className, title: item.name,
        ...(local ? { to: `/${kind}s/${local.id}` } : { href: stashboxEntityURL(payload, `${kind}s`, item.id, item), target: "_blank", rel: "noreferrer" }),
      }, item.name);
    }
    const remaining = items.slice(2);
    const links = items.slice(0, 2).map((item, index) => performers
      ? React.createElement(React.Fragment, { key: item.id }, index ? ", " : null, link(item, "sticky-names__name"))
      : link(item, "sticky-pill sticky-pill--tag"));
    return React.createElement("div", { className: performers ? "sticky-names" : "sticky-pills sticky-pills--tag" },
      performers ? React.createElement("span", { className: "sticky-names__list" }, links) : links,
      remaining.length > 0 && React.createElement(Button, {
        className: `minimal curator-metadata-more ${performers ? "sticky-names__more" : "sticky-pill sticky-pill--more"}`,
        variant: "link", "aria-label": `Show ${remaining.length} more ${kind}${remaining.length === 1 ? "" : "s"}`, "aria-expanded": !!anchor,
        onClick: (event) => setAnchor(anchor ? null : event.currentTarget),
      }, `+${remaining.length}`),
      anchor && React.createElement(libraries.Bootstrap.Overlay, { show: true, target: anchor, placement: "top", rootClose: true, onHide: () => setAnchor(null) },
        React.createElement(libraries.Bootstrap.Popover, { id: `curator-${kind}s-${items[0].id}`, className: "curator-metadata-popover", "aria-label": `More ${kind}s` },
          React.createElement("div", { className: "sticky-popover-list" }, remaining.map((item) => link(item, `sticky-pill sticky-pill--${kind}`)))
        )
      )
    );
  }

  const ExternalCard = Api.register.component("stash-curator.ExternalCard", function ExternalCard(props) {
    const { HoverPopover } = Api.components;
    const { item, kind, gender, onShortlist, onShowScenes, onWhisparr, whisparrEnabled, thumbnails = false } = transformComponentProps("stash-curator.ExternalCard", props);
    const [whisparr, setWhisparr] = React.useState(null);
    const [tagChoices, setTagChoices] = React.useState(null);
    const [tagLoading, setTagLoading] = React.useState(false);
    const [tagError, setTagError] = React.useState("");
    const [ratingAnchor, setRatingAnchor] = React.useState(null);
    useCuratorActivity(`external-tags-${kind}-${item.id}`, tagLoading, "Matching local tags…");
    const payload = item.payload;
    if (!payload) return null;
    const imageProps = externalImageProps(payload.images);
    const image = imageProps.src;
    const href = stashboxEntityURL(payload, kind === "scene" ? "scenes" : "performers", item.id);
    const title = payload.title || payload.name || item.id;
    const localProfile = payload.curator_local ? { to: `/${kind}s/${payload.curator_local.id}`, title: `Open local ${kind} profile` } : { href, target: "_blank", rel: "noreferrer" };
    const TitleLink = localProfile.to ? NavLink : "a";
    const cast = kind === "scene" ? (payload.performers || []).map((value) => value.performer) : [];
    const people = gender ? cast.filter((person) => person.gender === gender) : cast;
    const tags = kind === "scene" ? payload.tags || [] : [];
    const stickyCards = !window.Sticky?.off && window.Sticky?.cards;
    const stickyScene = kind === "scene" && typeof stickyCards?.formatDate === "function";
    if (thumbnails) return React.createElement(FindThumbnail, { image, imageKey: imageProps.key, onImageError: imageProps.onError, title, href, kind });
    function metadataPopover(id, icon, label, count, content) {
      if (!count) return null;
      const trigger = React.createElement(Button, { className: "minimal curator-external-popover-button", size: "sm", title: label, "aria-label": `${count} ${label.toLowerCase()}` }, React.createElement(FontAwesomeIcon, { icon }), React.createElement("span", null, count));
      // Api.components.HoverPopover is undefined on a cold/direct navigation
      // to /plugins/stash-curator until some other part of Stash's own app
      // has mounted first (same root cause as CuratorControls' health-pill
      // guard) — fall back to the trigger alone rather than crashing the
      // whole card on an invalid element type.
      if (!HoverPopover) return trigger;
      return React.createElement(
        HoverPopover,
        { className: `curator-external-${id}-trigger`, enterDelay: 150, leaveDelay: 250, placement: "bottom", content: React.createElement("div", { className: `curator-external-popover-links curator-external-${id}-popover` }, content) },
        trigger
      );
    }
    const metadataControls = kind === "scene" && !stickyScene && React.createElement(
      ButtonGroup,
      { className: "card-popovers" },
      metadataPopover("tags", faTag, "Tags", tags.length, tags.map((tag) => React.createElement("span", { key: tag.id, className: "tag-item tag-link badge badge-secondary" }, React.createElement("a", { href: stashboxEntityURL(payload, "tags", tag.id), target: "_blank", rel: "noreferrer" }, tag.name)))),
      metadataPopover("performers", faUser, "Performers", cast.length, React.createElement(React.Fragment, null, people.map((person) => {
        const performerImage = externalImageProps(person.images);
        const PersonLink = person.curator_local ? NavLink : "a";
        const link = person.curator_local ? { to: `/performers/${person.curator_local.id}`, title: "Open local performer profile" } : { href: stashboxEntityURL(payload, "performers", person.id, person), target: "_blank", rel: "noreferrer", title: "Open external performer profile" };
        return React.createElement("div", { key: person.id, className: "performer-tag-container row" }, React.createElement("div", { className: "curator-performer-image-actions" }, React.createElement(PersonLink, { className: "performer-tag col m-auto zoom-2", ...link }, performerImage.src && React.createElement("img", { ...performerImage, className: "image-thumbnail", loading: "lazy", alt: person.name || "" })), React.createElement(PerformerHuntLink, { performer: person, external: true })), React.createElement(PersonLink, { className: "tag-item tag-link badge badge-secondary d-block", ...link }, person.name));
      }), cast.length > people.length && React.createElement("small", null, `+${cast.length - people.length} other performers`)))
    );
    async function addToWhisparr() {
      setWhisparr({ status: "adding", message: "Adding to Whisparr…" });
      try {
        const result = await onWhisparr(item.id);
        setWhisparr({ status: result.status, message: result.status === "already_exists" ? "Already in Whisparr." : "Added to Whisparr." });
      } catch (failure) {
        setWhisparr({ status: "error", message: failure.message });
      }
    }
    async function rateTags(event) {
      if (tagChoices !== null) {
        setTagChoices(null);
        return;
      }
      setRatingAnchor(event.currentTarget);
      setTagLoading(true);
      setTagError("");
      try {
        const tagsResult = await operation({ operation: "get_external_tag_choices", tags: tags.map((tag) => ({ id: tag.id, name: tag.name })) });
        setTagChoices(tagsResult.items);
      } catch (failure) {
        setTagError(failure.message);
        setTagChoices([]);
      } finally {
        setTagLoading(false);
      }
    }
    function answerTag(row, {value, blocked}) {
      submitTagPreference(row.tag_id, {value, blocked});
      setTagChoices((current) => current.map((item) => item.tag_id === row.tag_id ? { ...item, direct_value: value, direct_blocked: !!blocked } : item));
    }
    return React.createElement(
      "article",
      { className: `curator-card curator-compact-card curator-external-card curator-external-${kind} grid-card ${kind}-card${payload.curator_local ? " curator-external-local" : ""}` },
      item.sources?.includes("wildcard") && React.createElement("span", { className: "curator-wildcard-badge", title: "Popularity wildcard: selected outside preference-derived seeds." }, "Wildcard"),
      payload.curator_local && React.createElement("span", { className: "curator-local-badge", title: "Already in your local library" }, "In library"),
      payload.curator_local_match?.type === "phash" && React.createElement("span", { className: "curator-phash-badge", title: "A local scene has the same exact PHash. This is strong matching evidence, not guaranteed identity." }, "Likely local · exact PHash"),
      React.createElement("div", { className: `curator-external-thumbnail thumbnail-section ${kind === "scene" ? "video-section" : ""}` }, React.createElement("a", { className: `${kind}-card-link`, href, target: "_blank", rel: "noreferrer" }, image && React.createElement("img", { ...imageProps, className: `${kind}-card-image`, loading: "lazy", alt: "" })), kind === "scene" && !stickyScene && payload.studio?.name && React.createElement("span", { className: "curator-external-studio-overlay" }, payload.studio.name)),
      React.createElement("div", { className: "card-section" },
        stickyScene && React.createElement("div", { className: "sticky-card-top" },
          React.createElement(ExternalStudioLink, { key: payload.studio?.id, payload }),
          payload.studio?.name && payload.release_date && React.createElement("span", { className: "sticky-card-top__dot", "aria-hidden": true }, "·"),
          payload.release_date && React.createElement("span", { className: "sticky-date" }, stickyCards.formatDate(payload.release_date))
        ),
        React.createElement(TitleLink, localProfile, React.createElement("h5", { className: "card-section-title flex-aligned" }, title)),
        React.createElement("div", { className: "curator-card-affinity" }, React.createElement(EvidenceScore, {
          evidenceContent: null,
          scoreHeadline: item.appeal !== undefined ? "Appeal" : item.similarity === undefined ? "Match" : "Similarity",
          scoreHeadlineValue: item.appeal !== undefined ? formatSigned((Number(item.appeal) * 2) - 1) : Number(item.score || 0).toFixed(2),
          scoreHeadlineBar: item.appeal !== undefined ? scoreBar((Number(item.appeal) * 2) - 1, true) : utilityBar(Number(item.score || 0)),
        })),
        stickyScene && React.createElement(ExternalMetadataRow, { payload, items: people, kind: "performer" }),
        stickyScene && cast.length > people.length && React.createElement("small", null, `+${cast.length - people.length} other performers`)
      ),
      stickyScene && React.createElement("div", { className: "sticky-card-footer" }, React.createElement(ExternalMetadataRow, { payload, items: tags, kind: "tag" })),
      React.createElement("div", { className: "curator-card-body" }, (() => { const score = Number(item.score || 0); const label = item.similarity === undefined ? "Match" : "Similarity"; const detail = item.similarity === undefined ? `Match ${score.toFixed(2)} (0..1) · found via ${item.sources.join(", ")}` : `Similarity ${Number(item.similarity).toFixed(2)} (0..1) · Appeal ${formatSigned((Number(item.appeal || 0) * 2) - 1)}`; const fallbackExplanation = payload.why?.length ? { summary: kind === "scene" ? findSceneSummary(item) : payload.why.join(" · "), evidence_rows: payload.why.map((value) => ({ code: "external.fact", label: value, direction: "positive", confidence: 1 })) } : null; return React.createElement("div", { className: "curator-card-details" }, React.createElement(EvidenceScore, { evidenceContent: payload.explanation ? React.createElement(ExplanationView, { explanation: payload.explanation }) : fallbackExplanation ? React.createElement(ExplanationView, { explanation: fallbackExplanation }) : kind === "scene" ? React.createElement(FindSceneReason, { item }) : null, dateContent: !stickyScene && React.createElement("span", { className: "curator-card-date" }, payload.release_date || payload.birth_date || ""), metadataContent: metadataControls, descriptionContent: kind === "scene" && payload.details && React.createElement("p", { className: "card-section curator-card-description" }, payload.details), actionsContent: React.createElement(ExternalActions, { item, kind, onShortlist, tagsAvailable: tags.length > 0, tagsActive: tagChoices !== null, tagLoading, onRateTags: rateTags, onShowScenes, whisparrEnabled, canWhisparr: Boolean(onWhisparr), whisparr, onAddToWhisparr: addToWhisparr }), scoreBarContent: null, scoreLabel: label, scoreSummary: score.toFixed(2), scoreContent: React.createElement("p", null, detail) })); })()),
      kind === "scene" && tagChoices !== null && React.createElement(RatingPopover, { anchor: ratingAnchor, onClose: () => { setTagChoices(null); } }, React.createElement("div", { className: "curator-external-tag-rating" }, React.createElement("div", { className: "curator-external-tag-rating-header" }, React.createElement("strong", null, "Rate tags")), tagLoading && React.createElement("small", { role: "status" }, "Matching local tags…"), tagError && React.createElement("small", { className: "text-danger", role: "status" }, tagError), !tagLoading && !tagError && React.createElement(React.Fragment, null, React.createElement(RatingSection, { title: "Matching local tags", rows: tagChoices.map((tag) => ({ key: tag.tag_id, tag_id: tag.tag_id, name: tag.name, direct_value: tag.direct_value, direct_blocked: tag.direct_blocked })), onAnswer: answerTag, emptyLabel: "No matching local tags." }))))
    );
  });

  const SourceReference = Api.register.component("stash-curator.SourceReference", function SourceReference(props) {
    const { entity, type, fallback } = transformComponentProps("stash-curator.SourceReference", props);
    const href = `/${type}s/${entity?.id || fallback.id}`;
    const image = entity && (type === "scene" ? entity.paths?.screenshot : entity.image_path);
    const title = entity?.title || entity?.name || fallback.label;
    const details = !entity
      ? []
      : type === "scene"
        ? [...(entity.performers || []).map((item) => item.name), ...(entity.tags || []).slice(0, 3).map((item) => item.name)]
        : [entity.measurements, entity.hair_color, entity.birthdate].filter(Boolean);
    return React.createElement(
      NavLink,
      { className: `curator-source-reference curator-source-reference-${type} ${type}-card`, to: href },
      image && React.createElement("img", { className: `${type}-card-image`, src: image, alt: "" }),
      React.createElement("span", { className: "card-section" }, React.createElement("strong", { className: "card-section-title" }, title), details.length > 0 && React.createElement("small", null, details.join(" · ")))
    );
  });

  function Feedback({ item, onRemove, onThumbDown, compact = false }) {
    const [saved, setSaved] = React.useState("");
    const [reaction, setReaction] = React.useState("");
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
        if (feedbackType === "thumb_down" && onThumbDown) {
          const followUp = await operation({
            operation: "get_tag_sentiment_follow_up",
            scene_id: item.scene_id,
            limit: 3,
          }).catch(() => ({ scene_id: item.scene_id, items: [] }));
          onThumbDown(followUp);
        }
        setSaved(feedbackType === "thumb_up" || !onRemove ? "Saved" : "Removed from this view");
        setReaction(feedbackType);
        if (feedbackType !== "thumb_up") onRemove?.(item.scene_id);
      } catch (error) {
        setSaved(error.message);
      } finally {
        setBusy(false);
      }
    }
    return React.createElement(
      "div",
      { className: "curator-feedback", "data-reaction": compact ? reaction : undefined },
      React.createElement(Button, { className: "curator-feedback-button", variant: "link", size: "sm", disabled: busy, title: "Useful: strengthen recommendations like this one.", "aria-label": "Useful", onClick: () => send("thumb_up") }, React.createElement(FontAwesomeIcon, { icon: faThumbsUp })),
      React.createElement(Button, { className: "curator-feedback-button", variant: "link", size: "sm", disabled: busy, title: "Not for me: treat this recommendation as a poor match.", "aria-label": "Not for me", onClick: () => send("thumb_down") }, React.createElement(FontAwesomeIcon, { icon: faThumbsDown })),
      !compact && React.createElement(
        "details",
        { className: "curator-more" },
        React.createElement("summary", { className: "btn btn-secondary btn-sm", title: "More ways to refine this recommendation." }, "More"),
        React.createElement(
          "div",
          { className: "curator-more-menu" },
          React.createElement(Button, { size: "sm", variant: "link", title: "Hide this scene temporarily without treating it as a dislike.", onClick: () => send("not_now") }, "Not now"),
          React.createElement(Button, { size: "sm", variant: "link", title: "Permanently exclude this scene from Curator.", onClick: () => send("never_show") }, "Never show"),
          React.createElement(Button, { size: "sm", variant: "link", title: "Keep the scene, but do not learn from its current metadata.", onClick: () => send("metadata_wrong", "Do not train from this metadata") }, "Metadata is wrong"),
          React.createElement(Button, { size: "sm", variant: "link", title: "Add this scene to the library-removal review queue.", onClick: () => send("prune", "Review for removal") }, "Mark for pruning")
        )
      ),
      saved && React.createElement("small", { role: "status" }, saved)
    );
  }

  const FEEDBACK_LABELS = {
    thumb_up: "Thumbs Up",
    thumb_down: "Thumbs Down",
    not_now: "Not Now",
    never_show: "Never Show",
    metadata_wrong: "Metadata Wrong",
    prune: "Prune",
    curation_pair_winner: "Picked in Curate",
    curation_pair_loser: "Passed over in Curate",
  };

  function FeedbackHistoryRow({ item, scene, onCorrect }) {
    const [replacement, setReplacement] = React.useState("");
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState("");
    async function correct(feedbackType) {
      setBusy(true);
      setError("");
      try {
        await operation({
          operation: "correct_feedback",
          feedback_id: item.feedback_id,
          correction_id: uuid(),
          feedback_type: feedbackType || null,
        });
        scheduleModelUpdate();
        onCorrect();
      } catch (failure) {
        setError(failure.message);
      } finally {
        setBusy(false);
      }
    }
    return React.createElement(
      "div",
      { className: "curator-record-row curator-feedback-row" },
      React.createElement("span", { className: "curator-record-icon" }, React.createElement(FontAwesomeIcon, { icon: faThumbsUp })),
      React.createElement(
        "div",
        { className: "curator-record-main" },
        React.createElement(
          "div",
          { className: "curator-record-title" },
          scene
            ? React.createElement(NavLink, { to: `/scenes/${item.scene_id}` }, scene.title || `Scene ${item.scene_id}`)
            : React.createElement("span", { className: "text-muted" }, "Scene removed from Stash")
        ),
        React.createElement("div", { className: "curator-record-meta" }, `${FEEDBACK_LABELS[item.feedback_type] || item.feedback_type} · ${new Date(item.occurred_at_ms).toLocaleString()}`)
      ),
      item.reversed_by_id
        ? React.createElement("span", { className: "text-muted" }, "Corrected")
        : React.createElement(
            "div",
            { className: "curator-feedback-correction" },
            React.createElement(Button, { size: "sm", variant: "link", disabled: busy, onClick: () => correct(null) }, "Undo"),
            React.createElement(
              "select",
              { className: "form-control form-control-sm", value: replacement, disabled: busy, onChange: (event) => setReplacement(event.target.value), "aria-label": "Replacement feedback" },
              React.createElement("option", { value: "" }, "Replace with…"),
              Object.entries(FEEDBACK_LABELS).map(([value, label]) => React.createElement("option", { key: value, value }, label))
            ),
            React.createElement(Button, { size: "sm", variant: "link", disabled: busy || !replacement, onClick: () => correct(replacement) }, "Save"),
            error && React.createElement("small", { className: "text-danger" }, error)
          )
    );
  }

  function FeedbackHistoryPanel() {
    const [page, setPage] = useUrlPage("page_feedback");
    const [data, setData] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState("");
    const [version, setVersion] = React.useState(0);
    useCuratorActivity("feedback-history", loading, "Loading feedback history…");
    React.useEffect(() => {
      let active = true;
      setLoading(true);
      setError("");
      operation({ operation: "get_feedback_history", page }).then(
        (result) => active && (setData(result), setLoading(false)),
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => { active = false; };
    }, [page, version]);
    React.useEffect(() => {
      if (data?.page === page) {
        const last = Math.max(1, Math.ceil(data.total / data.page_size));
        if (page > last) setPage(last, { replace: true });
      }
    }, [data, page]);
    const ids = [...new Set(data?.items.map((item) => item.scene_id) || [])];
    const scenesQuery = GQL.useFindScenesQuery({
      variables: { filter: { per_page: Math.max(1, ids.length) }, scene_ids: ids.map(Number) },
      skip: ids.length === 0,
    });
    const scenes = new Map((scenesQuery.data?.findScenes?.scenes || []).map((scene) => [String(scene.id), scene]));
    return React.createElement(
      "section",
      { className: "curator-history-page" },
      loading && React.createElement("div", { role: "status" }, "Loading feedback history…"),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      data && !loading && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No feedback has been recorded yet."),
      data && data.items.length > 0 && React.createElement(
        "div",
        { className: "curator-record-list" },
        data.items.map((item) => React.createElement(FeedbackHistoryRow, { key: item.feedback_id, item, scene: scenes.get(String(item.scene_id)), onCorrect: () => setVersion((value) => value + 1) }))
      ),
      data && React.createElement(Pager, { page, total: data.total, pageSize: data.page_size, hasMore: page * data.page_size < data.total, loading, onPage: setPage, label: "Feedback history pages" })
    );
  }

  function wallLaneIcon(lane) {
    const known = laneByValue.get(lane);
    if (known) return known.icon;
    const map = { score_review: faBalanceScale, similar: faClone, prune: faBroom, curate: faBullseye, expand: faGlobe, hunt: faCrosshairs };
    return map[lane] || faCompass;
  }
  function MoodMenu({ moods, moodID, disabled, onSelect, onManage }) {
    const menu = React.useRef(null);
    const active = moods.find((mood) => mood.id === moodID);
    function close() {
      if (menu.current) {
        menu.current.open = false;
        menu.current.querySelector("summary")?.focus();
      }
    }
    function choose(id) { close(); onSelect(id); }
    return React.createElement("details", { className: "curator-mood-menu", ref: menu, onBlur: (event) => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false; }, onKeyDown: (event) => { if (event.key === "Escape") { event.preventDefault(); close(); } } },
      React.createElement("summary", { className: `btn btn-sm btn-${active ? "primary" : "secondary"}`, "aria-label": active ? `Active mood: ${active.name}` : "Choose a mood", "aria-disabled": disabled, title: active ? `Active mood: ${active.name}` : "Choose a mood", onClick: (event) => { if (disabled) event.preventDefault(); } }, React.createElement(FontAwesomeIcon, { icon: faHeart, "aria-hidden": "true" }), React.createElement("span", null, active ? active.name : "Moods")),
      React.createElement("div", { className: "curator-mood-options" },
        [{ id: "", name: "Off" }, ...moods].map((mood) => React.createElement("button", { key: mood.id, type: "button", disabled, className: "curator-mood-option", "aria-pressed": moodID === mood.id, title: mood.name, onClick: () => choose(mood.id) }, React.createElement("span", { className: "curator-mood-check", "aria-hidden": "true" }, moodID === mood.id ? "✓" : ""), React.createElement("span", null, mood.name))),
        React.createElement("button", { type: "button", disabled, className: "curator-mood-manage", onClick: () => { close(); onManage(); } }, React.createElement(FontAwesomeIcon, { icon: faCog, "aria-hidden": "true" }), " Manage moods…")
      )
    );
  }

  function PreviewWallToggle({ wall, onToggle }) {
    return React.createElement(Button, { size: "sm", variant: wall ? "primary" : "secondary", "aria-pressed": wall, title: wall ? "Show the full card grid" : "Show a wall of playing scene previews", "aria-label": wall ? "Show the full card grid" : "Show a wall of playing scene previews", onClick: onToggle }, React.createElement(FontAwesomeIcon, { icon: faThLarge }), " Wall");
  }
  function RecommendationViewSelector({ view, onChange, views = ["cards", "thumbnails", "wall"], label = "Recommendation view" }) {
    return React.createElement(ButtonGroup, { size: "sm", "aria-label": label },
      views.map((value) => React.createElement(Button, {
        key: value, variant: view === value ? "primary" : "secondary",
        "aria-pressed": view === value, onClick: () => onChange(value),
      }, value[0].toUpperCase() + value.slice(1)))
    );
  }
  function ThumbnailTile({ entry }) {
    const [hovered, setHovered] = React.useState(false);
    const { scene_id, scene } = entry;
    const title = scene?.title || `Scene ${scene_id}`;
    return React.createElement("article", {
      className: "curator-preview-tile",
      onMouseEnter: () => {
        if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) setHovered(true);
      },
      onMouseLeave: () => setHovered(false),
    }, React.createElement("a", { className: "curator-preview-link", href: `/scenes/${scene_id}`, "aria-label": title },
      React.createElement("div", { className: "card-section" },
        hovered
          ? React.createElement("video", { className: "curator-preview-video", src: `/scene/${scene_id}/preview`, poster: `/scene/${scene_id}/screenshot`, ref: (node) => { if (node) { node.muted = true; node.defaultMuted = true; } }, muted: true, loop: true, playsInline: true, autoPlay: true })
          : React.createElement("img", { className: "curator-preview-video", src: `/scene/${scene_id}/screenshot`, alt: "", loading: "lazy" })
      )
    ));
  }
  function PreviewTile({ entry, index }) {
    const [hovered, setHovered] = React.useState(false);
    const { scene_id, scene, affinity, lane } = entry;
    const title = scene?.title || `Scene ${scene_id}`;
    const hasAffinity = affinity !== undefined && affinity !== null;
    const label = hasAffinity ? formatAppealValue(affinity) : "";
    const sign = !hasAffinity || affinity === 0 ? "neutral" : affinity < 0 ? "negative" : "positive";
    const laneLabel = laneByValue.get(lane)?.label || "Curator";
    const laneColor = `var(--curator-hue-${lane}, var(--curator-accent))`;
    function onEnter() { setHovered(true); }
    function onLeave() { setHovered(false); }
    // Mute synchronously at attach (mobile requires muted *before* the autoplay
    // check) so playback starts silently; a separate effect re-mutes via
    // addEventListener if the SFW toggle unmutes/restarts the media outside
    // React. The media sits in card-section so Stash's SFW switch blurs it.
    const videoRef = React.useRef(null);
    function keepMuted(node) {
      if (!node) return;
      videoRef.current = node;
      node.muted = true;
      node.defaultMuted = true;
    }
    React.useEffect(() => {
      const el = videoRef.current;
      if (!el) return;
      const forceMuted = () => { el.muted = true; el.defaultMuted = true; };
      el.addEventListener("play", forceMuted);
      el.addEventListener("volumechange", forceMuted);
      return () => {
        el.removeEventListener("play", forceMuted);
        el.removeEventListener("volumechange", forceMuted);
      };
    }, []);
    return React.createElement("article", { className: `curator-preview-tile curator-affinity-${sign}`, onMouseEnter: onEnter, onMouseLeave: onLeave, onFocus: onEnter, onBlur: onLeave },
      React.createElement("a", { className: "curator-preview-link", href: `/scenes/${scene_id}`, title },
        React.createElement("div", { className: "card-section" },
          React.createElement("video", { ref: keepMuted, className: "curator-preview-video", src: `/scene/${scene_id}/preview`, poster: `/scene/${scene_id}/screenshot`, muted: true, defaultMuted: true, loop: true, playsInline: true, autoPlay: index < WALL_CAP, preload: index < WALL_CAP ? "auto" : "none" })
        )
      ),
      React.createElement("span", { className: "curator-preview-lane", style: { color: laneColor }, title: laneLabel, "aria-label": laneLabel }, React.createElement(FontAwesomeIcon, { icon: wallLaneIcon(lane) })),
      hovered && React.createElement("div", { className: "curator-preview-hover", onMouseEnter: onEnter, onMouseLeave: onLeave, onFocus: onEnter, onBlur: onLeave },
        hasAffinity && React.createElement("span", { className: "curator-preview-affinity", title: `Curator affinity ${label}`, "aria-label": `Curator affinity ${label}` }, React.createElement(FontAwesomeIcon, { icon: faCompass }), React.createElement("span", null, label)),
        React.createElement("span", { className: "curator-preview-hover-title" }, title)
      )
    );
  }
  function PreviewWall({ entries, thumbnails = false }) {
    return React.createElement("div", { className: "curator-preview-wall" }, entries.map((entry, index) => React.createElement(thumbnails ? ThumbnailTile : PreviewTile, { key: `${entry.scene_id}:${index}`, entry, index })));
  }
  function RecommendationWall({ visibleItems, scenes, lane, thumbnails = false }) {
    const entries = visibleItems.map((item) => ({
      scene_id: item.scene_id,
      scene: scenes.get(String(item.scene_id)),
      affinity: item.appeal,
      lane: item.source_lane || lane,
    }));
    return React.createElement(PreviewWall, { entries, thumbnails });
  }
  // Shared by Recommendations and Find. Keep only nearby batches on navigation.
  const ENDLESS_CACHE_KEY = "stash-curator:endless:v1";
  const endlessCache = new Map();
  let endlessGeneration = 0;
  function clearEndlessCache() {
    endlessGeneration++;
    endlessCache.clear();
    try { sessionStorage.removeItem(ENDLESS_CACHE_KEY); } catch (_) { /* Storage may be unavailable. */ }
  }
  function readEndlessCache(key) {
    try {
      if (!endlessCache.size) {
        const saved = JSON.parse(sessionStorage.getItem(ENDLESS_CACHE_KEY) || "[]");
        for (const [name, value] of saved) {
          if (Number.isInteger(value?.anchor?.page) && Array.isArray(value.pages) && value.pages.length &&
              value.pages.every((batch) => Number.isInteger(batch.page) && Array.isArray(batch.items))) endlessCache.set(name, value);
        }
      }
    } catch (_) { /* Ignore unavailable or corrupt storage. */ }
    return endlessCache.get(key) || null;
  }
  function saveEndlessCache(key, pages, anchor, filters = null) {
    const index = Math.max(0, pages.findIndex((batch) => batch.page === anchor.page));
    const start = Math.max(0, Math.min(index - 5, pages.length - 12));
    const value = { pages: pages.slice(start, start + 12), anchor, filters, configUpdatedAtMs: cachedConfigUpdatedAtMs };
    endlessCache.delete(key);
    endlessCache.set(key, value);
    while (endlessCache.size > 6) endlessCache.delete(endlessCache.keys().next().value);
    // Bound serialized storage too: remote payloads can be much larger than cards.
    let serialized = JSON.stringify([...endlessCache]);
    while (serialized.length > 1000000) {
      if (endlessCache.size > 1) endlessCache.delete(endlessCache.keys().next().value);
      else if (value.pages.length > 1) {
        const distance = (batch) => Math.abs(batch.page - anchor.page);
        if (distance(value.pages[0]) > distance(value.pages.at(-1))) value.pages.shift();
        else value.pages.pop();
      } else { endlessCache.delete(key); break; }
      serialized = JSON.stringify([...endlessCache]);
    }
    try { sessionStorage.setItem(ENDLESS_CACHE_KEY, JSON.stringify([...endlessCache])); } catch (_) { /* Memory still works. */ }
  }
  function endlessScrollParent(node) {
    for (let parent = node.parentElement; parent; parent = parent.parentElement) {
      if (/(auto|scroll)/.test(window.getComputedStyle(parent).overflowY) && parent.scrollHeight > parent.clientHeight) return parent;
    }
    return window;
  }
  function readEndlessRecommendationFilters() {
    readEndlessCache("");
    for (const value of [...endlessCache.values()].reverse()) {
      const filters = value.filters;
      if (filters && typeof filters.gender === "string" && ["includeTags", "excludeTags", "performers", "studios"].every((field) => Array.isArray(filters[field]))) return value;
    }
    return null;
  }
  function endlessBatchKey(first, identity) {
    if (identity[0] === "recommendations") return JSON.stringify([identity, cachedConfigUpdatedAtMs, first.model_id, first.mood_id, first.config_updated_at_ms, first.page_size]);
    return JSON.stringify([identity, cachedConfigUpdatedAtMs, first.model_id, first.mood_id, first.config_updated_at_ms, first.page_size, first.fetched_at_ms, first.total,
      first.items.map((item) => item.id || item.scene_id || item.entity_id)]);
  }
  function EndlessFindResults({ first, page = 1, pageSize, cacheKey, clientItems = null, loadPage, renderPage, metadata = false }) {
    const initial = React.useRef(readEndlessCache(cacheKey));
    const clientBatch = (number) => ({ ...first, page: number, items: clientItems.slice((number - 1) * pageSize, number * pageSize), has_more: number * pageSize < clientItems.length });
    const [pages, setPages] = React.useState(() => initial.current?.pages || [clientItems ? clientBatch(page) : { ...first, page }]);
    const [readyPages, setReadyPages] = React.useState(new Set());
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState("");
    const [restoring, setRestoring] = React.useState(Boolean(initial.current));
    const root = React.useRef(null), before = React.useRef(null), after = React.useRef(null);
    const busy = React.useRef(false), alive = React.useRef(true), current = React.useRef(null);
    const prepend = React.useRef(null);
    const requestedDirection = React.useRef(1);
    const generation = React.useRef(endlessGeneration);
    const anchor = React.useRef(initial.current?.anchor || null);
    const ready = !metadata || pages.every((batch) => readyPages.has(batch.page));
    const markReady = React.useCallback((number) => setReadyPages((old) => old.has(number) ? old : new Set([...old, number])), []);
    current.current = { pages: clientItems ? pages.map((batch) => clientBatch(batch.page)) : pages, restoring };
    React.useEffect(() => { if (clientItems) generation.current = endlessGeneration; }, [first]);
    React.useEffect(() => {
      alive.current = true;
      const capture = () => {
        if (current.current.restoring) return;
        const scroller = endlessScrollParent(root.current);
        const top = scroller === window ? 0 : scroller.getBoundingClientRect().top;
        const items = [...root.current.querySelectorAll("[data-endless-page]")].flatMap((batch) =>
          [...batch.querySelectorAll(":scope > .curator-grid > *, :scope > .curator-preview-wall > *")].map((node, index) => ({ node, index, page: Number(batch.dataset.endlessPage) })));
        const item = items.find(({ node }) => node.getBoundingClientRect().bottom > top) || items.at(-1);
        if (item) {
          anchor.current = { page: item.page, index: item.index, offset: item.node.getBoundingClientRect().top - top };
        }
      };
      const save = () => {
        capture();
        if (anchor.current && generation.current === endlessGeneration) saveEndlessCache(cacheKey, current.current.pages, anchor.current);
      };
      window.addEventListener("scroll", capture, { passive: true, capture: true });
      root.current.addEventListener("click", save, true);
      window.addEventListener("pagehide", save);
      capture();
      const node = root.current;
      return () => {
        // The DOM may already be detached at cleanup; use the last captured anchor.
        if (anchor.current && generation.current === endlessGeneration) saveEndlessCache(cacheKey, current.current.pages, anchor.current);
        alive.current = false;
        window.removeEventListener("scroll", capture, true);
        node.removeEventListener("click", save, true);
        window.removeEventListener("pagehide", save);
      };
    }, [cacheKey]);
    React.useEffect(() => {
      if (!ready || (!restoring && !prepend.current)) return undefined;
      const frame = requestAnimationFrame(() => {
        const saved = prepend.current || anchor.current;
        const batch = root.current.querySelector(`[data-endless-page="${saved.page}"]`);
        if (batch) {
          const node = batch.querySelectorAll(":scope > .curator-grid > *, :scope > .curator-preview-wall > *")[saved.index || 0] || batch;
          const scroller = endlessScrollParent(root.current);
          const top = scroller === window ? 0 : scroller.getBoundingClientRect().top;
          scroller.scrollBy({ top: node.getBoundingClientRect().top - top - saved.offset, behavior: "instant" });
        }
        prepend.current = null;
        setRestoring(false);
      });
      return () => cancelAnimationFrame(frame);
    }, [ready, restoring, pages]);
    async function more(direction = 1) {
      if (busy.current || restoring || !ready) return;
      const number = direction > 0 ? pages.at(-1).page + 1 : pages[0].page - 1;
      if (number < page || (direction > 0 && !pages.at(-1).has_more)) return;
      requestedDirection.current = direction;
      busy.current = true; setLoading(true); setError("");
      try {
        const batch = clientItems ? clientBatch(number) : await loadPage(number);
        if (!Array.isArray(batch?.items)) throw new Error("The next batch did not contain results.");
        if (first.model_id !== batch.model_id || first.config_updated_at_ms !== batch.config_updated_at_ms || first.fetched_at_ms !== batch.fetched_at_ms) throw new Error("Results changed. Refresh this list to continue.");
        if (!alive.current) return;
        if (direction < 0) {
          const batch = root.current.querySelector("[data-endless-page]");
          const node = batch.querySelectorAll(":scope > .curator-grid > *, :scope > .curator-preview-wall > *")[0] || batch;
          const scroller = endlessScrollParent(root.current);
          prepend.current = { page: pages[0].page, offset: node.getBoundingClientRect().top - (scroller === window ? 0 : scroller.getBoundingClientRect().top) };
        }
        setPages((old) => direction > 0 ? [...old, { ...batch, page: number }] : [{ ...batch, page: number }, ...old]);
      } catch (failure) { if (alive.current) setError(failure.message); }
      finally { busy.current = false; if (alive.current) setLoading(false); }
    }
    const next = React.useRef(null); next.current = more;
    React.useEffect(() => {
      if (loading || restoring || !ready || error || !window.IntersectionObserver) return undefined;
      const scroller = endlessScrollParent(root.current);
      const observer = new IntersectionObserver((events) => {
        for (const event of events) if (event.isIntersecting) next.current(event.target === before.current ? -1 : 1);
      }, { root: scroller === window ? null : scroller, rootMargin: `0px 0px ${Math.max(2400, window.innerHeight * 4)}px 0px` });
      if (pages.at(-1).has_more) observer.observe(after.current);
      if (pages[0].page > page) observer.observe(before.current);
      return () => observer.disconnect();
    }, [pages, loading, ready, restoring, error]);
    return React.createElement("div", { ref: root, className: "curator-grid curator-endless-results curator-find-endless" },
      pages[0].page > page && React.createElement("div", { ref: before }, React.createElement(Button, { disabled: loading || restoring || !ready, onClick: () => more(-1) }, "Load earlier results")),
      pages.map((batch) => React.createElement("div", { key: batch.page, "data-endless-page": batch.page }, renderPage(clientItems ? clientBatch(batch.page) : batch, markReady))),
      error && React.createElement("div", { role: "alert", className: "alert alert-danger" }, error),
      pages.at(-1).has_more && React.createElement("div", { ref: after }, React.createElement(Button, { disabled: loading || restoring || !ready, onClick: () => more(error ? requestedDirection.current : 1) }, loading ? "Loading…" : error ? "Retry" : "Load more"))
    );
  }

  function virtualWallRange(count, columns, rowHeight, top, viewportHeight) {
    const rows = Math.ceil(count / columns);
    const firstRow = Math.min(rows, Math.max(0, Math.floor(top / rowHeight) - 2));
    const lastRow = Math.min(rows, Math.max(firstRow, Math.ceil((top + viewportHeight) / rowHeight) + 2));
    return { first: firstRow * columns, last: Math.min(count, lastRow * columns), height: rows * rowHeight, offset: firstRow * rowHeight };
  }
  function EndlessRecommendationTile({ entry, thumbnails, index, seen }) {
    const node = React.useRef(null);
    React.useEffect(() => {
      let timer;
      const id = `impression:${entry.item.impression_id}:${entry.scene_id}`;
      if (seen.has(id) || !window.IntersectionObserver) return;
      const observer = new IntersectionObserver(([event]) => {
        clearTimeout(timer);
        if (event.intersectionRatio >= 0.5) timer = setTimeout(() => {
          if (seen.has(id)) return;
          seen.add(id);
          enqueue({ event_id: id, event_type: "qualified_impression", impression_id: entry.item.impression_id, scene_id: entry.scene_id, occurred_at_ms: Date.now() });
        }, 1000);
      }, { threshold: 0.5 });
      observer.observe(node.current);
      return () => { clearTimeout(timer); observer.disconnect(); };
    }, [entry, seen]);
    return React.createElement("div", { ref: node, "data-endless-item": String(entry.scene_id), onClick: (event) => {
      if (event.target.closest("a")) sessionStorage.setItem(ORIGIN_KEY, JSON.stringify({ scene_id: entry.scene_id, impression_id: entry.item.impression_id, lane: entry.slate.lane, impression_position: entry.item.position, model_id: entry.slate.model_id }));
    } }, React.createElement(thumbnails ? ThumbnailTile : PreviewTile, { entry, index }));
  }
  function EndlessRecommendations({ slate, visibleItems, scenes, lane, filters, thumbnails, cards = false, onRestart, onRemove, onThumbDown }) {
    const cacheKey = endlessBatchKey(slate, ["recommendations", lane, filters, rotationLane(lane), cards, thumbnails]);
    const saved = React.useRef(readEndlessCache(cacheKey));
    const [restoring, setRestoring] = React.useState(Boolean(saved.current));
    const snapshot = React.useRef(null);
    const anchor = React.useRef(saved.current?.anchor || null);
    const generation = React.useRef(endlessGeneration);
    const earlier = React.useRef(null);
    const [entries, setEntries] = React.useState(() => saved.current?.pages.flatMap((batch) => batch.items.map((entry) => ({ ...entry, slate: batch.slate }))) || visibleItems.map((item) => ({ scene_id: item.scene_id, scene: scenes.get(String(item.scene_id)), affinity: item.appeal, lane: item.source_lane || lane, item, slate })));
    const [lastPage, setLastPage] = React.useState(() => saved.current?.pages.at(-1).slate || slate);
    const [startPage, setStartPage] = React.useState(() => saved.current?.pages[0].page || slate.page);
    const [pending, setPending] = React.useState(null);
    const pendingDirection = React.useRef(1);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState("");
    const [geometry, setGeometry] = React.useState({ columns: 1, rowHeight: 200, top: 0, viewportHeight: window.innerHeight });
    const root = React.useRef(null);
    const grid = React.useRef(null);
    const more = React.useRef(null);
    const busy = React.useRef(false);
    const active = React.useRef(true);
    const seen = React.useRef(new Set());
    snapshot.current = { entries, restoring, geometry };
    React.useEffect(() => {
      const capture = () => {
        if (snapshot.current.restoring) return;
        const scroller = endlessScrollParent(root.current);
        const top = scroller === window ? 0 : scroller.getBoundingClientRect().top;
        const nodes = [...root.current.querySelectorAll("[data-endless-item]")];
        const node = nodes.find((element) => element.getBoundingClientRect().bottom > top) || nodes.at(-1);
        const entry = node && snapshot.current.entries.find((value) => String(value.scene_id) === node.dataset.endlessItem);
        if (entry) anchor.current = { page: entry.slate.page, item: String(entry.scene_id), offset: node.getBoundingClientRect().top - top };
      };
      const save = (captureNow = true) => {
        if (captureNow) capture();
        if (!anchor.current || generation.current !== endlessGeneration) return;
        const batches = new Map();
        for (const entry of snapshot.current.entries) {
          const { slate: batchSlate, ...value } = entry;
          if (!batches.has(batchSlate.page)) batches.set(batchSlate.page, { page: batchSlate.page, slate: { ...batchSlate, items: undefined }, items: [] });
          batches.get(batchSlate.page).items.push(value);
        }
        saveEndlessCache(cacheKey, [...batches.values()], anchor.current, filters);
      };
      window.addEventListener("scroll", capture, { passive: true, capture: true });
      const node = root.current;
      node.addEventListener("click", save, true);
      window.addEventListener("pagehide", save);
      capture();
      return () => {
        save(false);
        window.removeEventListener("scroll", capture, true);
        node.removeEventListener("click", save, true);
        window.removeEventListener("pagehide", save);
      };
    }, [cacheKey]);
    React.useEffect(() => {
      if (!restoring) return undefined;
      const frame = requestAnimationFrame(() => {
        const scroller = endlessScrollParent(root.current);
        const top = scroller === window ? 0 : scroller.getBoundingClientRect().top;
        const index = entries.findIndex((entry) => String(entry.scene_id) === anchor.current.item);
        if (index >= 0) {
          const node = cards && [...root.current.querySelectorAll("[data-endless-item]")].find((element) => element.dataset.endlessItem === anchor.current.item);
          const position = node ? node.getBoundingClientRect().top : root.current.getBoundingClientRect().top + Math.floor(index / geometry.columns) * geometry.rowHeight;
          scroller.scrollBy({ top: position - top - anchor.current.offset, behavior: "instant" });
        }
        setRestoring(false);
      });
      return () => cancelAnimationFrame(frame);
    }, [restoring, entries, geometry.columns, geometry.rowHeight, cards]);
    React.useEffect(() => {
      active.current = true;
      const node = root.current;
      if (!saved.current && node.getBoundingClientRect().top < 0) node.scrollIntoView({ block: "start" });
      return () => { active.current = false; };
    }, []);
    const ids = pending?.items.map((item) => Number(item.scene_id)) || [];
    const query = GQL.useFindScenesQuery({ variables: { filter: { per_page: Math.max(1, ids.length) }, scene_ids: ids }, skip: !ids.length });
    React.useEffect(() => {
      if (!pending || (ids.length && query.loading)) return;
      if (ids.length && query.error) {
        setError(query.error.message);
      } else if (!ids.length || query.data) {
        const nextScenes = new Map((query.data?.findScenes?.scenes || []).map((scene) => [String(scene.id), scene]));
        if (thumbnails) for (const item of pending.items) {
          if (!nextScenes.has(String(item.scene_id))) continue;
          const image = new Image();
          image.fetchPriority = "low";
          image.src = `/scene/${item.scene_id}/screenshot`;
        }
        setEntries((current) => {
          const existing = new Set(current.map((entry) => String(entry.scene_id)));
          const added = pending.items.filter((item) => !existing.has(String(item.scene_id)) && nextScenes.has(String(item.scene_id))).map((item) => ({ scene_id: item.scene_id, scene: nextScenes.get(String(item.scene_id)), affinity: item.appeal, lane: item.source_lane || lane, item, slate: pending }));
          return pendingDirection.current > 0 ? [...current, ...added] : [...added, ...current];
        });
        if (pendingDirection.current > 0) setLastPage(pending);
        else { setStartPage(pending.page); setRestoring(true); }
      } else return;
      setPending(null);
      setLoading(false);
      busy.current = false;
    }, [pending, query.loading, query.error, query.data]);
    React.useEffect(() => {
      if (cards) return;
      let frame;
      const measure = () => {
        frame = null;
        const style = window.getComputedStyle(grid.current);
        const tracks = style.gridTemplateColumns.split(" ");
        const columns = Math.max(1, tracks.length);
        const gap = parseFloat(style.columnGap) || 0;
        const width = parseFloat(tracks[0]) || (root.current.getBoundingClientRect().width - gap * (columns - 1)) / columns;
        const rowHeight = width * 9 / 16 + gap;
        setGeometry({ columns, rowHeight: Math.max(1, rowHeight), top: -root.current.getBoundingClientRect().top, viewportHeight: window.innerHeight });
      };
      const schedule = () => { if (frame == null) frame = requestAnimationFrame(measure); };
      measure();
      window.addEventListener("scroll", schedule, { passive: true, capture: true });
      window.addEventListener("resize", schedule);
      const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(schedule) : null;
      observer?.observe(root.current);
      return () => { cancelAnimationFrame(frame); observer?.disconnect(); window.removeEventListener("scroll", schedule, true); window.removeEventListener("resize", schedule); };
    }, [cards]);
    async function loadMore(prefetched = false, direction = 1) {
      if (busy.current || restoring || (direction > 0 && !lastPage.has_more)) return;
      const number = direction > 0 ? lastPage.page + 1 : startPage - 1;
      if (number < slate.page) return;
      if (direction < 0) {
        const node = root.current.querySelector("[data-endless-item]");
        const scroller = endlessScrollParent(root.current);
        if (node) anchor.current = { page: entries[0].slate.page, item: node.dataset.endlessItem, offset: node.getBoundingClientRect().top - (scroller === window ? 0 : scroller.getBoundingClientRect().top) };
      }
      pendingDirection.current = direction;
      busy.current = true;
      setLoading(true);
      setError("");
      try {
        const next = await loadSlate(lane, number, prefetched, filters);
        if (!active.current) return;
        if (next.model_id !== slate.model_id || next.config_updated_at_ms !== slate.config_updated_at_ms || next.mood_id !== slate.mood_id) {
          onRestart();
          return;
        }
        setPending(next);
      } catch (failure) {
        if (active.current) { setError(failure.message); setLoading(false); busy.current = false; }
      }
    }
    React.useEffect(() => {
      if (loading || restoring || error || !window.IntersectionObserver) return;
      const scroller = endlessScrollParent(root.current);
      const observer = new IntersectionObserver((events) => { for (const event of events) if (event.isIntersecting) loadMore(true, event.target === earlier.current ? -1 : 1); }, { root: scroller === window ? null : scroller, rootMargin: `0px 0px ${Math.max(2400, window.innerHeight * 4)}px 0px` });
      if (lastPage.has_more) observer.observe(more.current);
      if (startPage > slate.page) observer.observe(earlier.current);
      return () => observer.disconnect();
    }, [lastPage, startPage, loading, error, restoring, entries]);
    const range = virtualWallRange(entries.length, geometry.columns, geometry.rowHeight, geometry.top, geometry.viewportHeight);
    return React.createElement("div", { style: { position: "relative", paddingTop: startPage > slate.page ? "2.5rem" : 0 } },
      cards ? React.createElement("section", { ref: root, className: "curator-grid curator-endless-cards", "aria-label": "Recommendations" },
        entries.map((entry) => React.createElement(RecommendationCard, { key: String(entry.scene_id), item: entry.item, scene: entry.scene, slate: entry.slate, onRemove, onThumbDown }))
      ) : React.createElement("div", { ref: root, style: { position: "relative", height: range.height }, "aria-label": "Recommendations" },
        React.createElement("div", { ref: grid, className: "curator-preview-wall", style: { position: "absolute", top: range.offset, width: "100%" } },
          entries.slice(range.first, range.last).map((entry, index) => React.createElement(EndlessRecommendationTile, { key: String(entry.scene_id), entry, index, thumbnails, seen: seen.current }))
        )
      ),
      React.createElement("div", { ref: more, className: "curator-pager", "aria-live": "polite" },
        error && React.createElement("span", { className: "text-danger" }, error),
        loading ? React.createElement("span", { role: "status" }, "Loading more recommendations…")
          : lastPage.has_more ? React.createElement(Button, { size: "sm", variant: "secondary", onClick: () => loadMore(false, error ? pendingDirection.current : 1) }, error ? "Retry" : "Load more")
            : React.createElement("span", null, "End of recommendations")
      ),
      startPage > slate.page && React.createElement("div", { ref: earlier, style: { position: "absolute", top: 0 } }, React.createElement(Button, { disabled: loading || restoring, onClick: () => loadMore(false, -1) }, "Load earlier results"))
    );
  }
  function RecommendationCard({ item, scene, slate, onRemove, onThumbDown, evidenceScenes }) {
    const { SceneCard } = Api.components;
    const card = React.useRef(null);
    const [explanation, setExplanation] = React.useState(
      item.explanation
        ? { summary: typeof item.explanation === "string" ? item.explanation : item.explanation.summary, ...(typeof item.explanation === "object" ? item.explanation : {}), supporting_reasons: item.supporting_reasons || [] }
        : null
    );
    const [explanationLoading, setExplanationLoading] = React.useState(false);
    const [explanationError, setExplanationError] = React.useState("");
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
    async function explain(event) {
      if (!event.currentTarget.open || explanation || explanationLoading) return;
      setExplanationLoading(true);
      setExplanationError("");
      try {
        setExplanation(
          await operation({ operation: "get_explanation", scene_id: item.scene_id }, 60000)
        );
      } catch (failure) {
        setExplanationError(failure.message);
      } finally {
        setExplanationLoading(false);
      }
    }
    // score_review is a synthetic pseudo-lane (Sentiment review reuses this
    // card to page through the bottom of the model's score distribution,
    // not a real recommendation source) — it was never given a label,
    const laneLabel = item.source_lane === "score_review" ? "Sentiment review" : (laneByValue.get(item.source_lane)?.label || item.source_lane);
    const hasLaneRank = item.source_lane !== "score_review";
    return React.createElement(
      "article",
      { className: `curator-card curator-compact-card curator-source-${item.source_lane}`, onClickCapture: rememberOrigin, "data-endless-item": String(item.scene_id), ref: card },
      React.createElement(
        "span",
        { className: `curator-source-badge curator-lane-${item.source_lane}`, title: `Selected from ${laneLabel}`, "aria-label": `Selected from ${laneLabel}` },
        React.createElement(FontAwesomeIcon, { icon: laneByValue.get(item.source_lane)?.icon || faCompass }),
        React.createElement("span", null, laneLabel.toUpperCase())
      ),
      scene
        ? React.createElement(SceneCard, { scene, curatorAppeal: item.appeal })
        : React.createElement("div", { className: "curator-card-placeholder" }, `Scene ${item.scene_id}`),
      React.createElement(
        "div",
        { className: "curator-card-body" },
        React.createElement(
          "div",
          { className: "curator-card-details" },
          React.createElement(EvidenceScore, {
            evidenceProps: { onToggle: explain },
            evidenceContent: React.createElement(
              React.Fragment,
              null,
              hasLaneRank && React.createElement("p", { className: "curator-explanation" }, `Rank in ${laneLabel}: ${item.lane_value.toFixed(2)} (0..1)`),
              explanationLoading && React.createElement("small", { role: "status" }, "Explaining…"),
              explanationError && React.createElement("small", { className: "text-danger", role: "alert" }, explanationError),
              React.createElement(ExplanationView, { explanation: { ...explanation, scores: explanation?.scores || { appeal: { value: item.appeal, direction: item.appeal >= 0 ? "positive" : "negative" }, rank: { value: item.lane_value, available: hasLaneRank } }, lane_context: { available: hasLaneRank, display_lane: slate.lane, source_lane: item.source_lane, subtype: item.subtype, qualification: item.qualification } }, item, scene, evidenceScenes })
            ),
            descriptionContent: scene?.details && React.createElement("p", { className: "card-section curator-card-description curator-card-description-local" }, scene.details),
            actionsContent: React.createElement(React.Fragment, null, scene && React.createElement(LocalRatingPanel, { sceneId: item.scene_id }), React.createElement(Feedback, { item, onRemove, onThumbDown })),
            scoreHeadline: scene ? null : "Appeal",
            scoreHeadlineValue: scene ? null : formatAppealValue(item.appeal),
            scoreHeadlineBar: scene ? null : scoreBar(item.appeal, true),

          })
        )
      )
    );
  }

  function RecommendationHistoryRow({ item, scene }) {
    const [explanation, setExplanation] = React.useState(null);
    const [error, setError] = React.useState("");
    async function explain() {
      setError("");
      try {
        setExplanation(await operation({ operation: "get_explanation", scene_id: item.scene_id }));
      } catch (failure) {
        setError(failure.message);
      }
    }
    return React.createElement(
      "tr",
      null,
      React.createElement(
        "td",
        null,
        scene
          ? React.createElement(NavLink, { to: `/scenes/${item.scene_id}` }, scene.title || `Scene ${item.scene_id}`)
          : React.createElement("span", { className: "text-muted" }, "Scene removed from Stash")
      ),
      React.createElement("td", null, item.lane === "score_review" ? "Sentiment review" : (laneByValue.get(item.lane)?.label || item.lane)),
      React.createElement(
        "td",
        null,
        item.reason_snapshot.length
          ? item.reason_snapshot.map(reasonLabel).join(" · ")
          : "No reason snapshot recorded"
      ),
      React.createElement(
        "td",
        null,
        item.current_model && scene && !explanation && React.createElement(Button, { size: "sm", variant: "link", onClick: explain }, "Why this now?"),
        explanation && React.createElement("span", null, explanation.summary),
        error && React.createElement("small", { className: "text-danger" }, error)
      )
    );
  }

  function RecommendationHistoryPanel() {
    const historySpec = React.useMemo(() => ({
      defaults: { laneFilter: "", page: 1 },
      fields: { laneFilter: urlStringField("hist_lane", "", (value) => LANES.some((lane) => lane.value === value)) },
      page: urlPageSpec("page_history"),
    }), []);
    const [urlState, updateUrl] = useUrlState(historySpec);
    const { laneFilter, page } = urlState;
    const [data, setData] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState("");
    useCuratorActivity("recommendation-history", loading, "Loading recommendation history…");
    React.useEffect(() => {
      let active = true;
      setLoading(true);
      setError("");
      operation({ operation: "get_recommendation_history", page, lane: laneFilter || null }).then(
        (result) => active && (setData(result), setLoading(false)),
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => { active = false; };
    }, [page, laneFilter]);
    React.useEffect(() => {
      if (data?.page === page) {
        const last = Math.max(1, Math.ceil(data.total / data.page_size));
        if (page > last) updateUrl((s) => ({ ...s, page: last }), { replace: true });
      }
    }, [data, page]);
    const ids = [...new Set(data?.items.map((item) => item.scene_id) || [])];
    const scenesQuery = GQL.useFindScenesQuery({
      variables: { filter: { per_page: Math.max(1, ids.length) }, scene_ids: ids.map(Number) },
      skip: ids.length === 0,
    });
    const scenes = new Map((scenesQuery.data?.findScenes?.scenes || []).map((scene) => [String(scene.id), scene]));
    const groups = (data?.items || []).reduce((result, item) => {
      const date = new Date(item.shown_at_ms).toLocaleDateString();
      (result[date] ||= []).push(item);
      return result;
    }, {});
    return React.createElement(
      "section",
      { className: "curator-history-page" },
      React.createElement(
        "label",
        null,
        "Lane ",
        React.createElement(
          "select",
          { className: "form-control form-control-sm", value: laneFilter, onChange: (event) => updateUrl((s) => ({ ...s, laneFilter: event.target.value, page: 1 })), "aria-label": "Filter recommendation history by lane" },
          React.createElement("option", { value: "" }, "All lanes"),
          LANES.map((lane) => React.createElement("option", { key: lane.value, value: lane.value }, lane.label))
        )
      ),
      loading && React.createElement("div", { role: "status" }, "Loading recommendation history…"),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      data && !loading && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No qualified recommendations have been recorded yet."),
      Object.entries(groups).map(([date, items]) => React.createElement(
        "section",
        { key: date },
        React.createElement("h3", null, date),
        React.createElement(
          "div",
          { className: "table-responsive" },
          React.createElement(
            "table",
            { className: "table" },
            React.createElement("thead", null, React.createElement("tr", null, ["Scene", "Lane", "Reason shown", "Current explanation"].map((label) => React.createElement("th", { key: label, scope: "col" }, label)))),
            React.createElement("tbody", null, items.map((item) => React.createElement(RecommendationHistoryRow, { key: item.history_id, item, scene: scenes.get(String(item.scene_id)) })))
          )
        )
      )),
      data && React.createElement(Pager, { page, total: data.total, pageSize: data.page_size, hasMore: page * data.page_size < data.total, loading, onPage: (value) => updateUrl((s) => ({ ...s, page: value })), label: "Recommendation history pages" })
    );
  }

  function FilterTokens({ kind, label, values, onChange, disabled = false, searchBoth = false }) {
    const [query, setQuery] = React.useState("");
    const [remoteResults, setRemoteResults] = React.useState([]);
    const [remoteError, setRemoteError] = React.useState("");
    const variables = { filter: { q: query, per_page: 8 } };
    const tags = GQL.useFindTagsQuery({ variables, skip: kind !== "tag" || !query || disabled });
    const studios = GQL.useFindStudiosQuery({ variables, skip: kind !== "studio" || !query || disabled });
    const performers = GQL.useFindPerformersQuery({ variables, skip: kind !== "performer" || !query || disabled });
    // Remote tag search reuses the cached Stash-box catalog; performer search
    // queries Stash-box directly. Local completions render immediately.
    React.useEffect(() => {
      setRemoteResults([]);
      setRemoteError("");
      if (!["performer", "tag"].includes(kind) || !searchBoth || !query || disabled) {
        return undefined;
      }
      let active = true;
      const timer = setTimeout(() => {
        const request = kind === "tag" ? { operation: "get_external_tag_search", query } : { operation: "get_stashdb_performer_search", query, limit: 8 };
        operation(request).then(
          (result) => { if (active) { setRemoteResults(result.items || []); setRemoteError(result.ready === false ? "Refresh Expand cache to load Stash-box tags." : ""); } },
          (failure) => { if (active && kind === "tag") setRemoteError(failure.message || "Stash-box tag search unavailable."); }
        );
      }, 300);
      return () => { active = false; clearTimeout(timer); };
    }, [kind, searchBoth, query, disabled]);
    const localPerformers = kind === "performer" ? (performers.data?.findPerformers?.performers || []) : [];
    const options = kind === "performer"
      ? searchBoth
        ? (() => {
            const seen = new Set();
            const merged = [];
            for (const item of localPerformers) {
              const id = String(item.id);
              if (seen.has(id)) continue;
              seen.add(id);
              merged.push({ ...item, source: "local" });
            }
            for (const item of remoteResults) {
              const id = String(item.id);
              if (seen.has(id)) continue;
              seen.add(id);
              merged.push({ ...item, source: "remote", external: true });
            }
            return merged;
          })()
        : localPerformers
      : kind === "tag"
        ? (() => {
            const local = (tags.data?.findTags?.tags || []).map((item) => ({ ...item, source: "local" }));
            const seen = new Set(local.map((item) => item.name.toLowerCase()));
            return searchBoth ? [...local, ...remoteResults.filter((item) => {
              const name = item.name.toLowerCase();
              if (seen.has(name)) return false;
              seen.add(name);
              return true;
            }).map((item) => ({ ...item, id: `stashdb:${item.id}`, source: "remote", external: true }))] : local;
          })()
        : kind === "studio"
          ? studios.data?.findStudios?.studios || []
          : [];
    function add(item) {
      if (!values.some((value) => String(value.id) === String(item.id))) onChange([...values, item]);
      setQuery("");
    }
    function optionText(item) {
      return item.external && item.disambiguation ? `${item.name} (${item.disambiguation})` : item.name;
    }
    return React.createElement(
      "label",
      { className: "curator-token-filter" },
      React.createElement("span", null, label),
      React.createElement("div", { className: "curator-token-input" }, values.map((item) => React.createElement("button", { key: item.id, type: "button", title: `Remove ${item.name}`, onClick: () => onChange(values.filter((value) => value.id !== item.id)) }, item.name, " ×")), disabled ? null : React.createElement("input", { value: query, onChange: (event) => setQuery(event.target.value), onKeyDown: (event) => { if (event.key === "Enter" && options.length > 0) { event.preventDefault(); add(options[0]); } }, placeholder: values.length ? "Add…" : `Search ${label.toLowerCase()}…` })),
      query && options.length > 0 && React.createElement("div", { className: "curator-token-options" }, options.map((item) => React.createElement("button", { key: item.id, type: "button", onClick: () => add(item) }, React.createElement("span", { className: "curator-token-option-name" }, optionText(item)), searchBoth && React.createElement("span", { className: "curator-token-source-badge" }, item.source === "remote" ? "Stash-box" : "Library")))),
      remoteError && React.createElement("span", { role: "status" }, remoteError)
    );
  }

  function SavedFilters({ scope, current, onApply }) {
    const [saved, setSaved] = React.useState(() => readFilterPresets()[scope] || {});
    const [name, setName] = React.useState("");
    const [makeDefault, setMakeDefault] = React.useState(false);
    const [saving, setSaving] = React.useState(false);
    const [error, setError] = React.useState("");
    const [switchId] = React.useState(() => `curator-default-switch-${uuid()}`);
    const fields = [...Object.keys(current).sort(), "id", "name"];
    const selected = Object.keys(saved.presets || {}).find((key) => JSON.stringify(saved.presets[key], fields) === JSON.stringify(current, fields)) || "";
    async function save() {
      const clean = name.trim();
      if (!clean || saving) return;
      setSaving(true);
      setError("");
      try {
        setSaved(await saveFilterPreset(scope, clean, current, makeDefault));
        setName("");
      } catch (failure) { setError(failure.message); }
      finally { setSaving(false); }
    }
    return React.createElement(
      "div",
      { className: "curator-saved-filters" },
      React.createElement("select", { value: selected, disabled: saving, onChange: (event) => { const value = saved.presets?.[event.target.value]; if (value) onApply(value); }, "aria-label": "Load saved filter" }, React.createElement("option", { value: "" }, "Current filters (unsaved)"), Object.keys(saved.presets || {}).sort().map((value) => React.createElement("option", { key: value, value }, `${value}${saved.default === value ? " · default" : ""}`))),
      React.createElement("details", null,
        React.createElement("summary", null, "Save current filters"),
        React.createElement("div", { className: "curator-saved-filter-create" },
          React.createElement("input", { value: name, disabled: saving, onChange: (event) => setName(event.target.value), placeholder: "Filter name", "aria-label": "Filter name" }),
          React.createElement(
            "div",
            { className: "custom-control custom-switch curator-default-switch" },
            React.createElement("input", { type: "checkbox", className: "custom-control-input", id: switchId, checked: makeDefault, disabled: saving, onChange: (event) => setMakeDefault(event.target.checked) }),
            React.createElement("label", { className: "custom-control-label", htmlFor: switchId }, "Use by default")
          ),
          React.createElement(Button, { size: "sm", variant: "secondary", disabled: saving || !name.trim(), onClick: save }, saving ? "Saving…" : "Save filter"),
          error && React.createElement("span", { role: "alert" }, error)
        )
      ),
    );
  }

  // Shared filter panel for Similar/Expand/Hunt. The three views show
  // different field subsets (hunt only ever shows tags + hide-phash, with
  // no entityType gating at all, since it has no "scene vs performer"
  // split); variant captures that shape plus the couple of markup
  // differences (favorites button's aria-pressed/title, gender aria-label,
  // minimum-match range floor) that predate this extraction and aren't
  // being "fixed" here, just ported as-is. State mutation stays with the
  // caller (each already has its own updateUrl closures per field).
  function FilterBar({
    variant,
    entityType,
    source,
    includeTags, onIncludeTagsChange,
    excludeTags, onExcludeTagsChange,
    performers, onPerformersChange,
    studios, onStudiosChange,
    favoriteOnly, onToggleFavorite,
    hidePhashMatches, onToggleHidePhash,
    gender, onGenderChange,
    minimum, onMinimumChange,
    applyVisible = true, onApply,
  }) {
    const sceneGated = variant !== "hunt";
    const showScene = !sceneGated || entityType === "scene";
    const remoteTags = variant === "expand" || variant === "hunt" || (variant === "similar" && source === "stashdb");
    // Recommendations narrows a lane's already-classified local scenes: no
    // Stash-box-only concept (hide-phash), similarity score (minimum match),
    // or the "boost favorited performers" ranking knob (favorite-only) — all
    // three are about ranking a candidate against a source entity or a
    // remote catalog, not about narrowing a pre-picked set.
    const rankingOnly = variant !== "recommendations";
    const minimumMin = variant === "expand" ? "-1" : "0";
    const genderAriaLabel = variant === "expand" ? "External performer gender" : "Performer gender";
    const favoriteExtra = variant === "expand" ? { title: "Show only scenes containing a performer favorited in your local library", "aria-pressed": favoriteOnly } : {};
    return React.createElement(
      "div",
      { className: "curator-filter-panel-body curator-filter-panel" },
      React.createElement(
        "div",
        null,
        showScene && React.createElement(FilterTokens, { kind: "tag", label: "Include tags", searchBoth: remoteTags, values: includeTags, onChange: onIncludeTagsChange }),
        showScene && React.createElement(FilterTokens, { kind: "tag", label: "Exclude tags", searchBoth: remoteTags, values: excludeTags, onChange: onExcludeTagsChange }),
        sceneGated && showScene && React.createElement(FilterTokens, { kind: "performer", label: "Performers", values: performers, onChange: onPerformersChange }),
        sceneGated && showScene && React.createElement(FilterTokens, { kind: "studio", label: "Studios", values: studios, onChange: onStudiosChange }),
        rankingOnly && sceneGated && showScene && React.createElement(Button, { size: "sm", variant: favoriteOnly ? "primary" : "secondary", ...favoriteExtra, onClick: onToggleFavorite }, React.createElement(FontAwesomeIcon, { icon: faHeart }), " Favorites"),
        rankingOnly && showScene && React.createElement(Button, { size: "sm", variant: hidePhashMatches ? "primary" : "secondary", "aria-pressed": hidePhashMatches, title: "Hide remote scenes when a local file has the same exact PHash", onClick: onToggleHidePhash }, "Hide exact PHash matches"),
        sceneGated && React.createElement("label", { className: "curator-toolbar-select", title: "Limit results by performer gender" }, React.createElement(FontAwesomeIcon, { icon: faVenus }), React.createElement("select", { value: gender, onChange: onGenderChange, "aria-label": genderAriaLabel }, React.createElement("option", { value: "FEMALE" }, "Female"), React.createElement("option", { value: "MALE" }, "Male"), React.createElement("option", { value: "TRANSGENDER_FEMALE" }, "Trans female"), React.createElement("option", { value: "TRANSGENDER_MALE" }, "Trans male"), React.createElement("option", { value: "" }, "All genders"))),
        rankingOnly && sceneGated && showScene && React.createElement("label", { className: "curator-match-filter" }, React.createElement("span", null, `Minimum match ${minimum.toFixed(2)}`), React.createElement("input", { type: "range", className: "curator-range", min: minimumMin, max: "0.8", step: "0.05", value: minimum, onChange: onMinimumChange })),
        applyVisible && React.createElement(Button, { size: "sm", variant: "primary", onClick: onApply }, "Apply")
      )
    );
  }

  function relationshipChips(item) {
      const labels = {
        same_performer: "Same performer",
        similar_performer: "Similar performer",
        shared_content: "Shared content",
        similar_structure: "Similar structure",
        same_studio: "Same studio",
        multi_hop: item.details?.multi_hop_via || "Multi-hop",
      };
      const chips = item.relationships.map((value) =>
        React.createElement("span", { key: value, className: `curator-chip curator-chip-${value}` }, labels[value] || value)
      );
      if (item.details.shared_tags?.length) {
        chips.push(
          React.createElement("span", { key: "tags", className: "curator-chip curator-chip-tags" }, item.details.shared_tags.join(", "))
        );
      }
      return React.createElement("span", { className: "curator-chips" }, ...chips);
    }

  function SimilarLibraryResults({ result, entityType, findView, wall, endless, onRemove, onThumbDown, onReady }) {
    const { SceneCard, PerformerCard } = Api.components;
    const items = result.items || [];
    const ids = items.map((item) => item.entity_id);
    const sceneQuery = GQL.useFindScenesQuery({ variables: { filter: { per_page: Math.max(1, ids.length) }, scene_ids: ids.map(Number) }, skip: entityType !== "scene" || ids.length === 0 });
    const performerQuery = GQL.useFindPerformersQuery({ variables: { filter: { per_page: Math.max(1, ids.length) }, performer_filter: performerNameFilter(items) }, skip: entityType !== "performer" || ids.length === 0 });
    const query = entityType === "scene" ? sceneQuery : performerQuery;
    const entities = new Map((entityType === "scene" ? sceneQuery.data?.findScenes?.scenes || [] : performerQuery.data?.findPerformers?.performers || []).map((entity) => [String(entity.id), entity]));
    React.useEffect(() => { if (!ids.length || (!query.loading && !query.error && query.data)) onReady?.(result.page); }, [result.page, query.loading, query.error, query.data, onReady]);
    if (query.error) return React.createElement("div", { className: "alert alert-danger", role: "alert" }, "Could not load library details. ", React.createElement(Button, { size: "sm", onClick: () => query.refetch() }, "Retry details"));
    if (query.loading) return React.createElement("div", { className: "curator-loading", role: "status" }, "Loading library details…");
    if (entityType === "scene" && (findView === "thumbnails" || wall)) return React.createElement(PreviewWall, { entries: items.flatMap((item) => {
      const scene = entities.get(String(item.entity_id));
      return scene ? [{ scene_id: item.entity_id, scene, affinity: (item.appeal * 2) - 1, lane: "similar" }] : [];
    }), thumbnails: findView === "thumbnails" });
    return React.createElement("div", { className: `curator-grid${endless && findView === "cards" ? " curator-endless-cards" : ""}` }, items.map((item) => {
      const entity = entities.get(String(item.entity_id));
      if (!entity) return null;
      if (entityType === "performer" && findView === "thumbnails") return React.createElement(FindThumbnail, { key: item.entity_id, image: entity.image_path, title: entity.name || String(item.entity_id), href: `/performers/${item.entity_id}`, kind: "performer", external: false });
      const feedbackItem = { ...item, scene_id: item.entity_id, impression_id: result.impression_id };
      const body = React.createElement("div", { className: "curator-card-body" }, React.createElement("div", { className: "curator-card-details" }, React.createElement(EvidenceScore, { descriptionContent: entityType === "scene" && entity.details && React.createElement("p", { className: "card-section curator-card-description curator-card-description-local" }, entity.details), actionsContent: entityType === "scene" && React.createElement(React.Fragment, null, React.createElement(LocalRatingPanel, { sceneId: item.entity_id }), React.createElement(Feedback, { item: feedbackItem, onRemove, onThumbDown })), scoreHeadline: entityType === "scene" ? null : "Appeal", scoreHeadlineValue: entityType === "scene" ? null : formatAppealValue((item.appeal * 2) - 1), scoreHeadlineBar: entityType === "scene" ? null : scoreBar((item.appeal * 2) - 1, true), evidenceContent: item.explanation ? React.createElement(ExplanationView, { explanation: item.explanation, item }) : React.createElement(React.Fragment, null, entityType === "scene" && React.createElement(FindSceneReason, { item }), relationshipChips(item)), scoreBarContent: null, scoreLabel: "Similarity", scoreSummary: item.similarity.toFixed(2), scoreContent: React.createElement("p", null, `Similarity ${item.similarity.toFixed(2)} (0..1) · Appeal ${formatSigned((item.appeal * 2) - 1)} (−1..1)`) })));
      if (entityType === "performer") return React.createElement("article", { key: item.entity_id, className: "curator-card curator-compact-card" }, React.createElement(PerformerCard, { performer: entity }), body);
      function rememberOrigin(event) {
        if (event.target.closest("a")) sessionStorage.setItem(ORIGIN_KEY, JSON.stringify({ scene_id: item.entity_id, impression_id: result.impression_id, lane: "similar", impression_position: item.position, model_id: result.model_id }));
      }
      return React.createElement("article", { key: item.entity_id, className: "curator-card curator-compact-card", onClickCapture: rememberOrigin }, React.createElement(SceneCard, { scene: entity, curatorAppeal: (item.appeal * 2) - 1 }), body);
    }));
  }

  function SimilarityPanel({ endless: endlessSetting = false }) {
    const initialFilters = React.useMemo(() => defaultFilters("similar"), []);
    const similarSpec = React.useMemo(() => ({
      defaults: {
        entityType: "scene",
        source: "library",
        selected: null,
        gender: initialFilters.gender ?? "FEMALE",
        favoriteOnly: Boolean(initialFilters.favoriteOnly),
        includeTags: initialFilters.includeTags || [],
        excludeTags: initialFilters.excludeTags || [],
        filterPerformers: initialFilters.performers || [],
        filterStudios: initialFilters.studios || [],
        minimumSimilarity: initialFilters.minimum ?? 0.18,
        hidePhashMatches: initialFilters.hidePhashMatches !== false,
        includeOwned: true,
        excludedIds: [],
        fetchTick: 0,
        page: 1,
      },
      fields: {
        entityType: urlStringField("type", "scene", (value) => ["scene", "performer"].includes(value)),
        selected: {
          param: "id",
          parse: (search) => {
            const id = search.get("id");
            return id ? { id, label: search.get("label") || `#${id}` } : null;
          },
          serialize: (value) => value ? { id: String(value.id), label: value.label && value.label !== String(value.id) ? value.label : "" } : { id: "", label: "" },
        },
        source: urlStringField("sim_source", "library", (value) => ["library", "stashdb"].includes(value)),
        gender: urlStringField("sim_gender", initialFilters.gender ?? "FEMALE"),
        favoriteOnly: urlBoolField("sim_favorite", Boolean(initialFilters.favoriteOnly)),
        includeTags: urlListField("sim_include_tags", initialFilters.includeTags || []),
        excludeTags: urlListField("sim_exclude_tags", initialFilters.excludeTags || []),
        filterPerformers: urlListField("sim_performers", initialFilters.performers || []),
        filterStudios: urlListField("sim_studios", initialFilters.studios || []),
        minimumSimilarity: urlNumberField("sim_min_sim", initialFilters.minimum ?? 0.18),
        hidePhashMatches: urlBoolField("sim_hide_phash", initialFilters.hidePhashMatches !== false),
        includeOwned: urlBoolField("sim_include_owned", true),
        excludedIds: {
          param: "sim_excluded",
          parse: (search) => {
            const raw = search.get("sim_excluded");
            return raw ? raw.split(",").map((id) => id.trim()).filter(Boolean) : [];
          },
          serialize: (value) => (value && value.length ? value.join(",") : ""),
        },
        fetchTick: { param: "sim_fetch_tick", parse: () => 0, serialize: () => "" },
      },
      page: urlPageSpec("page_similar"),
    }), [initialFilters]);
    const [urlState, updateUrl] = useUrlState(similarSpec);
    const { entityType, source, selected, page, excludedIds, gender, favoriteOnly, includeTags, excludeTags, filterPerformers, filterStudios, minimumSimilarity, hidePhashMatches, includeOwned, fetchTick } = urlState;
    const [query, setQuery] = React.useState("");
    const [search, setSearch] = React.useState("");
    const [result, setResult] = React.useState(null);
    const [error, setError] = React.useState("");
    const [loading, setLoading] = React.useState(false);
    const [pageSize, setPageSize] = React.useState(20);
    const [filtersOpen, setFiltersOpen] = React.useState(false);
    const [whisparrEnabled, setWhisparrEnabled] = React.useState(false);
    const [followUps, setFollowUps] = React.useState([]);
    const [wall, setWall] = React.useState(readWallMode);
    function toggleWall() {
      setWall((value) => {
        const next = !value;
        writeWallMode(next);
        return next;
      });
    }
    const codeVersionRef = React.useRef("");
    const [findView, changeFindView] = useFindView();
    const endless = endlessSetting && (findView === "thumbnails" || source !== "library" || entityType !== "scene" || !wall);
    useCuratorActivity("similar", loading, "Finding close matches…");
    const sceneSearch = GQL.useFindScenesQuery({
      variables: { filter: { q: search, per_page: 8 } },
      skip: entityType !== "scene" || !search,
    });
    const performerSearch = GQL.useFindPerformersQuery({
      variables: { filter: { q: search, per_page: 8 } },
      skip: entityType !== "performer" || !search,
    });
    const externalItems = result?.items || [];
    const items = source === "stashdb"
      ? externalItems.slice((page - 1) * pageSize, page * pageSize)
      : externalItems;
    const candidates = entityType === "scene"
      ? sceneSearch.data?.findScenes?.scenes || []
      : performerSearch.data?.findPerformers?.performers || [];
    const sourceScene = GQL.useFindSceneQuery({ variables: { id: selected?.id || "0" }, skip: entityType !== "scene" || !selected });
    const sourcePerformer = GQL.useFindPerformerQuery({ variables: { id: selected?.id || "0" }, skip: entityType !== "performer" || !selected });
    const sourceEntity = entityType === "scene" ? sourceScene.data?.findScene : sourcePerformer.data?.findPerformer;

    // The fetch effect is the single driver for similarity requests: it runs
    // whenever the URL-backed selection/source/page/exclusions change (including
    // back/forward restores) and reads current filter values through
    // filterStateRef, so filters stay lazy (applied on the next fetch) exactly
    // as before.
    const continuationRequest = React.useRef(null);
    const filterStateRef = React.useRef({ gender, favoriteOnly, hidePhashMatches, includeTags, excludeTags, filterPerformers, filterStudios, minimumSimilarity });
    filterStateRef.current = { gender, favoriteOnly, hidePhashMatches, includeTags, excludeTags, filterPerformers, filterStudios, minimumSimilarity };
    const requestKey = selected
      ? [source, entityType, String(selected.id), selected.label || "", source === "stashdb" ? "s" : String(page), excludedIds.join(","), source === "stashdb" ? (includeOwned ? "1" : "0") : "s", fetchTick].join("|")
      : null;
    React.useEffect(() => {
      if (!requestKey) {
        setResult(null);
        setLoading(false);
        return undefined;
      }
      const filters = filterStateRef.current;
      const request = {
        operation: source === "library" ? "get_similar" : "get_external_similar",
        entity_type: entityType,
        entity_id: String(selected.id),
        gender: filters.gender,
        favorite_only: filters.favoriteOnly,
        hide_phash_matches: filters.hidePhashMatches,
        include_tags: filters.includeTags.map((item) => item.name),
        exclude_tags: filters.excludeTags.map((item) => item.name),
        performer_ids: filters.filterPerformers.map((item) => String(item.id)),
        performer_names: filters.filterPerformers.map((item) => item.name),
        studio_ids: filters.filterStudios.map((item) => String(item.id)),
        studio_names: filters.filterStudios.map((item) => item.name),
        minimum_similarity: filters.minimumSimilarity,
      };
      if (source === "stashdb") request.include_owned = includeOwned;
      if (source === "library") {
        request.page = page;
        request.exclude_scene_ids = excludedIds;
      }
      continuationRequest.current = request;
      let active = true;
      const cacheKey = JSON.stringify(request) + ":" + (codeVersionRef.current || "");
      const cached = similarityCache.get(cacheKey);
      if (cached && Date.now() - cached.ts < SIMILARITY_CACHE_TTL_MS) {
        setResult(cached.data);
        setLoading(false);
        return () => { active = false; };
      }
      if (cached) similarityCache.delete(cacheKey);
      setError("");
      setLoading(true);
      operation(request, source === "stashdb" ? 60000 : 30000).then(
        (data) => {
          similarityCache.set(cacheKey, { ts: Date.now(), data });
          if (similarityCache.size > 10) similarityCache.delete(similarityCache.keys().next().value);
          if (active) {
            setResult(data);
            setLoading(false);
          }
        },
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => { active = false; };
    }, [requestKey]);
    function applySaved(value) {
      updateUrl((s) => ({ ...s, gender: value.gender ?? "FEMALE", favoriteOnly: Boolean(value.favoriteOnly), includeTags: value.includeTags || [], excludeTags: value.excludeTags || [], filterPerformers: value.performers || [], filterStudios: value.studios || [], hidePhashMatches: value.hidePhashMatches !== false, minimumSimilarity: value.minimum ?? 0.18 }));
    }
    function choose(entity) {
      setFollowUps([]);
      setResult(null);
      updateUrl((s) => ({ ...s, selected: { id: String(entity.id), label: entity.title || entity.name || `#${entity.id}` }, page: 1, excludedIds: [] }));
    }
    React.useEffect(() => {
      operation({ operation: "get_config" }).then((data) => {
        codeVersionRef.current = data.code_version || "";
        if (initialFilters.gender === undefined) updateUrl((s) => ({ ...s, gender: data.config.expand_gender || "" }), { replace: true });
        setPageSize(data.config.page_size || 20);
        setWhisparrEnabled(data.whisparr_enabled);
      }, () => {});
    }, []);
    function switchType(value) {
      setFollowUps([]);
      setSearch("");
      setResult(null);
      updateUrl((s) => ({ ...s, entityType: value, selected: null, page: 1, excludedIds: [] }));
    }
    function switchSource(value) {
      setFollowUps([]);
      setResult(null);
      updateUrl((s) => ({ ...s, source: value, page: 1, excludedIds: [] }));
    }
    function changePage(nextPage) {
      updateUrl((s) => ({ ...s, page: nextPage }));
    }
    function removeSimilar(sceneId) {
      similarityCache.clear();
      updateUrl((s) => ({ ...s, excludedIds: [...new Set([...s.excludedIds, sceneId])] }));
    }
    function showFollowUp(followUp) {
      setFollowUps((current) => [...current.filter((item) => item.scene_id !== followUp.scene_id), followUp]);
    }
    React.useEffect(() => {
      if (!result) return;
      const total = source === "stashdb" ? externalItems.length : result.total;
      const last = Math.max(1, Math.ceil(total / (source === "stashdb" ? pageSize : result.page_size)));
      if (page > last) updateUrl((s) => ({ ...s, page: last }), { replace: true });
    }, [result, source, externalItems.length, page, pageSize]);
    async function shortlistExternal(item, kind) {
      try {
        await operation({ operation: "update_shortlist", entity_type: kind, external_id: item.id, selected: !item.shortlisted });
        clearEndlessCache();
        setResult((current) => ({ ...current, items: current.items.map((value) => value.id === item.id ? { ...value, shortlisted: !item.shortlisted } : value) }));
      } catch (failure) { setError(failure.message); }
    }
    const sendWhisparr = (id) => operation({ operation: "send_whisparr", external_id: id });
    const activeFilterCount = (includeTags?.length || 0) + (excludeTags?.length || 0) + (filterPerformers?.length || 0) + (filterStudios?.length || 0) + (favoriteOnly ? 1 : 0) + (hidePhashMatches ? 1 : 0);
    function renderSimilarPage(batch, onReady) {
      if (source === "library") return React.createElement(SimilarLibraryResults, { result: batch, entityType, findView, wall, endless, onRemove: removeSimilar, onThumbDown: showFollowUp, onReady });
      return React.createElement("div", { className: `curator-grid curator-external-grid${endless && findView === "cards" ? " curator-endless-cards" : ""}` }, batch.items.map((item) => React.createElement(ExternalCard, { key: item.id, item, kind: entityType, gender, thumbnails: findView === "thumbnails", onShortlist: shortlistExternal, onShowScenes: (item) => location.assign(`/plugins/stash-curator?view=hunt&performer=${item.id}&label=${encodeURIComponent(item.payload?.name || "")}`), onWhisparr: sendWhisparr, whisparrEnabled })));
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
        React.createElement("div", { className: "btn-group curator-similar-source-tabs", role: "group", "aria-label": "Similarity source" }, [["library", "Library", faDatabase], ["stashdb", "Stash-box", faCompass]].map(([value, label, icon]) => React.createElement(Button, { key: value, size: "sm", variant: source === value ? "primary" : "secondary", onClick: () => switchSource(value) }, React.createElement(FontAwesomeIcon, { icon }), ` ${label}`))),
        React.createElement(
          "form",
          { onSubmit: (event) => (event.preventDefault(), updateUrl((s) => ({ ...s, selected: null })), setResult(null), setSearch(query.trim())) },
          React.createElement("input", { className: "form-control form-control-sm", value: query, onChange: (event) => setQuery(event.target.value), placeholder: `Search for a ${entityType}…`, "aria-label": `Search for a ${entityType}` }),
          React.createElement(Button, { size: "sm", type: "submit", disabled: !query.trim() }, "Search")
        ),
        source === "stashdb" && React.createElement(Button, { className: "curator-include-owned", size: "sm", variant: includeOwned ? "primary" : "secondary", "aria-pressed": includeOwned, title: `Include ${entityType}s already in your library so the remote ranking can be compared with the local search`, "aria-label": includeOwned ? `Hide library ${entityType}s` : `Include library ${entityType}s`, onClick: () => updateUrl((s) => ({ ...s, includeOwned: !s.includeOwned, page: 1, excludedIds: [] })) }, "Local"),
        React.createElement(Button, { size: "sm", variant: filtersOpen ? "primary" : "secondary", "aria-expanded": filtersOpen, onClick: () => setFiltersOpen((value) => !value) }, React.createElement(FontAwesomeIcon, { icon: faFilter }), " Filters", activeFilterCount > 0 && React.createElement("span", { className: "curator-filter-count" }, activeFilterCount)),
        React.createElement(RecommendationViewSelector, { label: "Find view", views: source === "library" && entityType === "scene" ? ["cards", "thumbnails", "wall"] : ["cards", "thumbnails"], view: findView === "thumbnails" ? "thumbnails" : source === "library" && entityType === "scene" && wall ? "wall" : "cards", onChange: (value) => { changeFindView(value === "thumbnails" ? "thumbnails" : "cards"); if (wall !== (value === "wall")) toggleWall(); } }),
        React.createElement(SavedFilters, { scope: "similar", current: { gender, favoriteOnly, hidePhashMatches, includeTags, excludeTags, performers: filterPerformers, studios: filterStudios, minimum: minimumSimilarity }, onApply: applySaved })
      ),
      filtersOpen && React.createElement(FilterBar, {
        variant: "similar",
        entityType,
        source,
        includeTags, onIncludeTagsChange: (value) => updateUrl((s) => ({ ...s, includeTags: value })),
        excludeTags, onExcludeTagsChange: (value) => updateUrl((s) => ({ ...s, excludeTags: value })),
        performers: filterPerformers, onPerformersChange: (value) => updateUrl((s) => ({ ...s, filterPerformers: value })),
        studios: filterStudios, onStudiosChange: (value) => updateUrl((s) => ({ ...s, filterStudios: value })),
        favoriteOnly, onToggleFavorite: () => updateUrl((s) => ({ ...s, favoriteOnly: !s.favoriteOnly })),
        hidePhashMatches, onToggleHidePhash: () => updateUrl((s) => ({ ...s, hidePhashMatches: !s.hidePhashMatches })),
        gender, onGenderChange: (event) => updateUrl((s) => ({ ...s, gender: event.target.value })),
        minimum: minimumSimilarity, onMinimumChange: (event) => updateUrl((s) => ({ ...s, minimumSimilarity: Number(event.target.value) })),
        applyVisible: Boolean(selected),
        onApply: () => { clearEndlessCache(); updateUrl((s) => ({ ...s, excludedIds: [], page: 1, fetchTick: s.fetchTick + 1 })); },
      }),
      search && !selected && React.createElement(
        "div",
        { className: "curator-similar-candidates" },
        candidates.map((entity) => React.createElement(Button, { key: entity.id, size: "sm", variant: "secondary", onClick: () => choose(entity) }, entity.title || entity.name || `#${entity.id}`)),
        (sceneSearch.loading || performerSearch.loading) && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Searching…")),
        !sceneSearch.loading && !performerSearch.loading && candidates.length === 0 && React.createElement("p", null, "No matches found.")
      ),
      selected && React.createElement("div", { className: "curator-similar-reference" }, React.createElement("strong", null, "Comparing from"), React.createElement(SourceReference, { entity: sourceEntity, type: entityType, fallback: selected })),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Finding close matches…")),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      followUps.map((followUp) => React.createElement(TagSentimentFollowUp, { key: followUp.scene_id, followUp, onDismiss: () => setFollowUps((current) => current.filter((item) => item.scene_id !== followUp.scene_id)) })),
      result && (endless
        ? !loading && React.createElement(EndlessFindResults, { key: requestKey, cacheKey: endlessBatchKey(result, ["similar", continuationRequest.current, findView, wall, pageSize]), first: result, page, pageSize: source === "stashdb" ? pageSize : result.page_size || pageSize, clientItems: source === "stashdb" ? externalItems : null, metadata: source === "library", loadPage: (nextPage) => operation({ ...continuationRequest.current, page: nextPage }, 30000), renderPage: renderSimilarPage })
        : renderSimilarPage({ ...result, page, items })),
      result && !endless && React.createElement(Pager, { page, total: source === "stashdb" ? externalItems.length : result.total, pageSize: source === "stashdb" ? pageSize : result.page_size, hasMore: source === "stashdb" ? page * pageSize < externalItems.length : result.has_more, loading, onPage: changePage, label: "Similar pages" })
    );
  }

  function PrunePanel() {
    const { SceneCard } = Api.components;
    const pruneSpec = React.useMemo(() => ({
      defaults: { view: "candidates", aggressiveness: 0, page: 1 },
      fields: {
        view: urlStringField("prn_view", "candidates", (value) => ["candidates", "tagged", "explicit", "suspects", "breadth"].includes(value)),
        aggressiveness: urlNumberField("prn_aggr", 0),
      },
      page: urlPageSpec((state) => `page_prune_${state.view}`),
      prune(route, state) {
        for (const value of ["candidates", "tagged", "explicit", "suspects", "breadth"]) {
          if (value !== state.view) route.delete(`page_prune_${value}`);
        }
      },
    }), []);
    const [urlState, updateUrl] = useUrlState(pruneSpec);
    const { view, aggressiveness, page } = urlState;
    const [data, setData] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState("");
    const [version, setVersion] = React.useState(0);
    const [wall, setWall] = React.useState(readWallMode);
    function toggleWall() {
      setWall((value) => {
        const next = !value;
        writeWallMode(next);
        return next;
      });
    }
    useCuratorActivity("prune", loading, "Reviewing prune evidence…");
    React.useEffect(() => {
      let active = true;
      setLoading(true);
      operation({ operation: "get_prune_candidates", view, aggressiveness, page }).then(
        (result) => active && (setData(result), setLoading(false)),
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => { active = false; };
    }, [view, aggressiveness, page, version]);
    React.useEffect(() => {
      if (data?.page === page) {
        const last = Math.max(1, Math.ceil(data.total / data.page_size));
        if (page > last) updateUrl((s) => ({ ...s, page: last }), { replace: true });
      }
    }, [data, page]);
    const ids = data?.items.map((item) => item.scene_id) || [];
    const scenesQuery = GQL.useFindScenesQuery({
      variables: { filter: { per_page: Math.max(1, ids.length) }, scene_ids: ids.map(Number) },
      skip: ids.length === 0,
    });
    const scenes = new Map((scenesQuery.data?.findScenes?.scenes || []).map((scene) => [String(scene.id), scene]));
    const pruneWallEntries = wall && data
      ? data.items.map((item) => {
          const scene = scenes.get(String(item.scene_id));
          if (!scene) return null;
          return {
            scene_id: item.scene_id,
            scene,
            affinity: item.appeal,
            lane: "prune",
          };
        }).filter(Boolean)
      : [];
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
          [["candidates", "Candidates"], ["tagged", "Tagged"], ["explicit", "Explicit dislikes"], ["suspects", "Model suspects"], ["breadth", "Broad & unwatched"]].map(([value, label]) => React.createElement(Button, { key: value, size: "sm", variant: view === value ? "primary" : "secondary", onClick: () => updateUrl((s) => ({ ...s, view: value, page: 1 })) }, label))
        ),
        view !== "tagged" && view !== "breadth" && React.createElement("label", { className: "curator-prune-aggressiveness", title: "Move right to include less certain predicted dislikes." }, React.createElement("span", null, aggressiveness < 0.34 ? "Conservative" : aggressiveness < 0.67 ? "Balanced" : "Aggressive"), React.createElement("input", { type: "range", className: "curator-range", min: 0, max: 1, step: 0.05, value: aggressiveness, onChange: (event) => updateUrl((s) => ({ ...s, aggressiveness: Number(event.target.value), page: 1 })), "aria-label": "Prune prediction aggressiveness" })),
        view !== "tagged" && React.createElement(Button, { size: "sm", variant: "danger", disabled: !ids.length, onClick: tagPage }, `Tag visible (${ids.length})`),
        React.createElement(PreviewWallToggle, { wall, onToggle: toggleWall })
      ),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Reviewing prune evidence…")),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      data && !loading && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, view === "suspects" ? "No scenes cross this prediction threshold. Direct dislikes appear under Explicit dislikes; suspects need a rebuilt model with enough repeated negative evidence." : view === "breadth" ? "No studio in your library is both this broad and this unwatched." : "Nothing in this view."),
      data && (wall ? React.createElement(PreviewWall, { entries: pruneWallEntries }) : React.createElement(
        "div",
        { className: "curator-grid" },
        data.items.map((item) => {
          const scene = scenes.get(String(item.scene_id));
          if (!scene) return null;
          return React.createElement(
            "article",
            { key: item.scene_id, className: "curator-card" },
            item.tagged && React.createElement("span", { className: "curator-prune-badge", title: `Tagged ${data.tag_name}`, "aria-label": `Tagged ${data.tag_name}` }, React.createElement(FontAwesomeIcon, { icon: faBroom })),
            React.createElement(SceneCard, { scene }),
            React.createElement("div", { className: "curator-card-body" }, React.createElement("p", { className: "curator-similarity-reason" }, item.evidence.join(" · ")), React.createElement("div", { className: "curator-card-details" }, React.createElement(EvidenceScore, {
              evidenceContent: null,
              scoreBarContent: item.appeal !== null ? utilityBar(item.appeal) : null,
              scoreSummary: item.appeal !== null ? item.appeal.toFixed(2) : "—",
              scoreContent: React.createElement("p", null, item.confidence !== null ? `Confidence ${item.confidence.toFixed(2)}` : "Confidence —"),
            }))),
            React.createElement("div", { className: "curator-prune-actions" }, React.createElement(Button, { size: "sm", variant: item.tagged ? "secondary" : "danger", onClick: () => tag([item.scene_id], !item.tagged) }, item.tagged ? `Undo ${data.tag_name}` : `Tag ${data.tag_name}`), !item.tagged && (item.suspect || item.breadth) && !item.explicit && React.createElement(Button, { size: "sm", variant: "link", onClick: () => dismiss(item.scene_id) }, "Dismiss"))
          );
        })
      )),
      data && React.createElement(Pager, { page, total: data.total, pageSize: data.page_size, hasMore: data.has_more, loading, onPage: (value) => updateUrl((s) => ({ ...s, page: value })), label: "Prune pages" })
    );
  }

  function ExpandPanel({ initialType = "scene", huntOnly = false, endless = false }) {
    const initialFilters = React.useMemo(() => defaultFilters(huntOnly ? "hunt" : "expand"), []);
    const expandSpec = React.useMemo(() => huntOnly ? {
      defaults: {
        entityType: "hunt",
        sort: "match",
        performerId: null,
        favoriteOnly: false,
        gender: initialFilters.gender ?? "FEMALE",
        performers: [],
        studios: [],
        minimumScore: 0,
        performer: null,
        huntView: "unlinked",
        huntSort: "date",
        includeTags: initialFilters.includeTags || [],
        excludeTags: initialFilters.excludeTags || [],
        hidePhashMatches: initialFilters.hidePhashMatches !== false,
        page: 1,
      },
      fields: {
        performer: {
          param: "performer",
          parse: (search) => {
            const id = search.get("performer");
            return id ? { id, name: search.get("label") || id, external: search.get("ext") === "1" } : null;
          },
          serialize: (value) => value ? { performer: String(value.id), label: value.name && value.name !== String(value.id) ? value.name : "", ext: value.external ? "1" : "" } : { performer: "", label: "" },
        },
        huntView: urlStringField("hunt_view", "unlinked", (value) => ["all", "linked", "unlinked"].includes(value)),
        huntSort: urlStringField("hunt_sort", "date", (value) => ["date", "score"].includes(value)),
        includeTags: urlListField("hunt_include_tags", initialFilters.includeTags || []),
        excludeTags: urlListField("hunt_exclude_tags", initialFilters.excludeTags || []),
        hidePhashMatches: urlBoolField("hunt_hide_phash", initialFilters.hidePhashMatches !== false),
      },
      page: urlPageSpec("page_hunt"),
    } : {
      defaults: {
        entityType: "scene",
        sort: "match",
        performerId: null,
        gender: initialFilters.gender ?? "FEMALE",
        favoriteOnly: Boolean(initialFilters.favoriteOnly),
        includeTags: initialFilters.includeTags || [],
        excludeTags: initialFilters.excludeTags || [],
        performers: initialFilters.performers || [],
        studios: initialFilters.studios || [],
        minimumScore: initialFilters.minimum ?? 0,
        hidePhashMatches: initialFilters.hidePhashMatches !== false,
        page: 1,
      },
      fields: {
        entityType: urlStringField("exp_type", "scene", (value) => ["scene", "performer", "shortlist"].includes(value)),
        sort: urlStringField("exp_sort", "match", (value) => ["match", "newest"].includes(value)),
        performerId: urlStringField("exp_performer", null),
        gender: urlStringField("exp_gender", initialFilters.gender ?? "FEMALE"),
        favoriteOnly: urlBoolField("exp_favorite", Boolean(initialFilters.favoriteOnly)),
        includeTags: urlListField("exp_include_tags", initialFilters.includeTags || []),
        excludeTags: urlListField("exp_exclude_tags", initialFilters.excludeTags || []),
        performers: urlListField("exp_performers", initialFilters.performers || []),
        studios: urlListField("exp_studios", initialFilters.studios || []),
        minimumScore: urlNumberField("exp_min_score", initialFilters.minimum ?? 0),
        hidePhashMatches: urlBoolField("exp_hide_phash", initialFilters.hidePhashMatches !== false),
      },
      page: urlPageSpec((state) => `page_expand_${state.entityType}`),
      prune(route, state) {
        for (const type of ["scene", "performer", "shortlist"]) {
          if (type !== state.entityType) route.delete(`page_expand_${type}`);
        }
      },
    }, [huntOnly, initialFilters]);
    const [urlState, updateUrl] = useUrlState(expandSpec);
    const { entityType, sort, performerId, favoriteOnly, gender, includeTags, excludeTags, performers, studios, minimumScore, hidePhashMatches, page, performer: huntPerformer, huntView, huntSort } = urlState;
    const [filtersOpen, setFiltersOpen] = React.useState(false);
    const [filterVersion, setFilterVersion] = React.useState(0);
    const [data, setData] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState("");
    const [message, setMessage] = React.useState("");
    const [version, setVersion] = React.useState(0);
    const [whisparrEnabled, setWhisparrEnabled] = React.useState(false);
    const [pageSize, setPageSize] = React.useState(20);
    useCuratorActivity(huntOnly ? "performer-hunt" : "expand", loading, "Working");
    const [findView, changeFindView] = useFindView();
    const continuationRequest = React.useRef(null);
    React.useEffect(() => {
      let active = true;
      if (entityType === "hunt" && !huntPerformer) {
        setData(null);
        setLoading(false);
        setError("");
        return () => { active = false; };
      }
      setLoading(true);
      setError("");
      const request = entityType === "shortlist"
        ? { operation: "get_shortlist", page }
        : entityType === "hunt"
          ? { operation: "get_performer_hunt", performer_id: String(huntPerformer.id), include_tags: includeTags.map((item) => item.name), exclude_tags: excludeTags.map((item) => item.name) }
          : { operation: "get_expand", page, entity_type: entityType, sort, performer_id: performerId, favorite_only: favoriteOnly, hide_phash_matches: hidePhashMatches, gender, include_tags: includeTags.map((item) => item.name), exclude_tags: excludeTags.map((item) => item.name), performer_names: performers.map((item) => item.name), studio_names: studios.map((item) => item.name), minimum_score: minimumScore };
      continuationRequest.current = request;
      operation(request, entityType === "hunt" ? 60000 : undefined).then(
        (result) => {
          if (!active) return;
          setData(result);
          setLoading(false);
          if (entityType === "hunt" && result?.performer_name) {
            updateUrl((current) => current.performer && (current.performer.name === current.performer.id || !current.performer.name) ? { ...current, performer: { ...current.performer, name: result.performer_name } } : current);
          }
        },
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => { active = false; };
    }, [entityType, sort, performerId, favoriteOnly, hidePhashMatches, gender, filterVersion, version, page, huntPerformer?.id]);
    React.useEffect(() => {
      if (!data?.initializing || error || loading) return;
      const timer = setTimeout(() => setVersion((value) => value + 1), 3000);
      return () => clearTimeout(timer);
    }, [data, error, loading]);
    React.useEffect(() => {
      operation({ operation: "get_config" }).then((data) => {
        if (initialFilters.gender === undefined) updateUrl((s) => ({ ...s, gender: data.config.expand_gender || "" }), { replace: true });
        setWhisparrEnabled(data.whisparr_enabled);
        setPageSize(data.config.page_size || 20);
      }, () => {});
    }, []);
    function applySaved(value) {
      updateUrl((s) => ({ ...s, page: 1, gender: value.gender ?? "FEMALE", favoriteOnly: Boolean(value.favoriteOnly), includeTags: value.includeTags || [], excludeTags: value.excludeTags || [], performers: value.performers || [], studios: value.studios || [], hidePhashMatches: value.hidePhashMatches !== false, minimumScore: value.minimum ?? 0 }));
    }
    async function refresh() {
      clearEndlessCache();
      if (entityType === "hunt") {
        setVersion((value) => value + 1);
        return;
      }
      try {
        await runTask("Refresh Expand cache");
        setMessage("Expand refresh started — progress and results appear in Manage → Tasks.");
      } catch (failure) { setError(failure.message); }
    }
    function selectHuntPerformer(values) {
      setData(null);
      updateUrl((s) => ({ ...s, performer: values.at(-1) || null, page: 1 }));
    }
    function showPerformerScenes(item) {
      updateUrl((s) => ({ ...s, entityType: "scene", performerId: item.id }));
    }
    async function shortlist(item, kind) {
      try {
        await operation({ operation: "update_shortlist", entity_type: kind, external_id: item.id, selected: !item.shortlisted });
        clearEndlessCache();
        if (entityType === "hunt") {
          setData((current) => ({ ...current, items: current.items.map((value) => value.id === item.id ? { ...value, shortlisted: !item.shortlisted } : value) }));
        } else {
          setVersion((value) => value + 1);
        }
      } catch (failure) { setError(failure.message); }
    }
    const sendWhisparr = (id) => operation({ operation: "send_whisparr", external_id: id });
    const huntItemsRaw = entityType === "hunt"
      ? (data?.items || []).filter((item) => !hidePhashMatches || item.match_type !== "phash")
      : [];
    const huntCounts = {
      all: huntItemsRaw.length,
      linked: huntItemsRaw.filter((item) => item.linked_locally).length,
      unlinked: huntItemsRaw.filter((item) => !item.linked_locally).length,
    };
    const huntItems = entityType === "hunt"
      ? huntItemsRaw
        .filter((item) => huntView === "all" || item.linked_locally === (huntView === "linked"))
        .sort((left, right) => huntSort === "score"
          ? right.score - left.score || left.id.localeCompare(right.id)
          : String(right.payload.release_date || right.payload.production_date || "").localeCompare(String(left.payload.release_date || left.payload.production_date || "")) || left.id.localeCompare(right.id))
      : [];
    const visibleItems = entityType === "hunt"
      ? huntItems.slice((page - 1) * pageSize, page * pageSize)
      : data?.items || [];
    const huntHasMore = entityType === "hunt" && page * pageSize < huntItems.length;
    React.useEffect(() => {
      if (!data?.ready) return;
      const total = entityType === "hunt" ? huntItems.length : data.total;
      const size = entityType === "hunt" ? pageSize : data.page_size;
      if (entityType === "hunt" || data.page === page) {
        const last = Math.max(1, Math.ceil(total / Math.max(1, size)));
        if (page > last) updateUrl((s) => ({ ...s, page: last }), { replace: true });
      }
    }, [data, entityType, huntItems.length, page, pageSize]);
    function renderExpandPage(batch) {
      return React.createElement("div", { className: `curator-grid curator-external-grid${endless && findView === "cards" ? " curator-endless-cards" : ""}` }, batch.items.map((item) => {
        const kind = entityType === "shortlist" ? item.entity_type : entityType === "hunt" ? "scene" : entityType;
        return React.createElement(ExternalCard, { key: `${kind}-${item.id}`, item, kind, gender, thumbnails: findView === "thumbnails", onShortlist: shortlist, onShowScenes: showPerformerScenes, onWhisparr: sendWhisparr, whisparrEnabled });
      }));
    }
    const pager = data?.ready && !endless && React.createElement(Pager, { page, total: entityType === "hunt" ? huntItems.length : data.total, pageSize: entityType === "hunt" ? pageSize : data.page_size, hasMore: entityType === "hunt" ? huntHasMore : data.has_more, loading, onPage: (value) => updateUrl((s) => ({ ...s, page: value })), label: entityType === "hunt" ? "Performer Hunt pages" : entityType === "shortlist" ? "Shortlist pages" : "Expand pages" });
    const activeFilterCount = (includeTags?.length || 0) + (excludeTags?.length || 0) + (performers?.length || 0) + (studios?.length || 0) + (favoriteOnly ? 1 : 0) + (hidePhashMatches ? 1 : 0);
    return React.createElement(
      "section",
      { className: huntOnly ? "curator-hunt" : "curator-expand" },
      React.createElement(
        "div",
        { className: "curator-expand-toolbar" },
        React.createElement(RecommendationViewSelector, { view: findView, onChange: changeFindView, views: ["cards", "thumbnails"], label: "Find view" }),
        !huntOnly && React.createElement("div", { className: "btn-group", role: "group", "aria-label": "Explore external content" }, [["scene", "Scenes", faPlayCircle], ["performer", "Performers", faUser]].map(([value, label, icon]) => React.createElement(Button, { key: value, size: "sm", variant: entityType === value ? "primary" : "secondary", onClick: () => updateUrl((s) => ({ ...s, entityType: value, performerId: null })) }, React.createElement(FontAwesomeIcon, { icon }), ` ${label}`))),
        !huntOnly && React.createElement(Button, { className: "curator-shortlist-tab", size: "sm", variant: entityType === "shortlist" ? "primary" : "secondary", onClick: () => updateUrl((s) => ({ ...s, entityType: "shortlist", performerId: null })) }, React.createElement(FontAwesomeIcon, { icon: faList }), " Shortlist"),
        entityType === "scene" && React.createElement("label", { className: "curator-toolbar-select" }, React.createElement(FontAwesomeIcon, { icon: faSortAmountDown }), React.createElement("select", { value: sort, onChange: (event) => updateUrl((s) => ({ ...s, page: 1, sort: event.target.value })), "aria-label": "Sort Expand results" }, React.createElement("option", { value: "match" }, "Best match"), React.createElement("option", { value: "newest" }, "Newest"))),
        entityType !== "shortlist" && React.createElement(Button, { size: "sm", variant: filtersOpen ? "primary" : "secondary", "aria-expanded": filtersOpen, onClick: () => setFiltersOpen((value) => !value) }, React.createElement(FontAwesomeIcon, { icon: faFilter }), " Filters", activeFilterCount > 0 && React.createElement("span", { className: "curator-filter-count" }, activeFilterCount)),
        entityType === "hunt" && React.createElement(SavedFilters, { scope: "hunt", current: { hidePhashMatches, includeTags, excludeTags }, onApply: (value) => updateUrl((s) => ({ ...s, page: 1, hidePhashMatches: value.hidePhashMatches !== false, includeTags: value.includeTags || [], excludeTags: value.excludeTags || [] })) }),
        entityType !== "shortlist" && entityType !== "hunt" && React.createElement(SavedFilters, { scope: "expand", current: { gender, favoriteOnly, hidePhashMatches, includeTags, excludeTags, performers, studios, minimum: minimumScore }, onApply: applySaved }),
        performerId && React.createElement(Button, { size: "sm", variant: "link", onClick: () => updateUrl((s) => ({ ...s, page: 1, performerId: null })) }, "Clear performer filter"),
        React.createElement(Button, { className: "curator-icon-button", size: "sm", disabled: entityType === "hunt" && !huntPerformer, title: entityType === "hunt" ? "Refresh this performer's scenes directly from Stash-box." : "Refresh the bounded Stash-box candidate cache in a background task.", "aria-label": entityType === "hunt" ? "Refresh Performer Hunt" : "Refresh Expand cache", onClick: refresh }, React.createElement(FontAwesomeIcon, { icon: faSync })),
        data?.fetched_at_ms && React.createElement("small", null, `${Date.now() > data.expires_at_ms ? "Stale · " : ""}Updated ${new Date(data.fetched_at_ms).toLocaleString()}`)
      ),
      entityType === "hunt" && React.createElement(
        "div",
        { className: "curator-hunt-controls" },
        // Issue #218: the picker searches both local performers and Stash-box
        // performers. Local completions render immediately and Stash-box results
        // fill in as they arrive; each dropdown option is tagged by source.
        React.createElement(FilterTokens, { kind: "performer", searchBoth: true, label: huntPerformer?.external ? "External performer on Stash-box" : huntPerformer ? "Local performer with a Stash-box link" : "Search library or Stash-box performers", values: huntPerformer ? [huntPerformer] : [], onChange: selectHuntPerformer, disabled: Boolean(huntPerformer?.external) }),
        data?.ready && React.createElement("div", { className: "btn-group", role: "group", "aria-label": "Performer Hunt view" }, [["all", `All ${huntCounts.all}`], ["linked", `In library ${huntCounts.linked}`], ["unlinked", `Not linked locally ${huntCounts.unlinked}`]].map(([value, label]) => React.createElement(Button, { key: value, size: "sm", variant: huntView === value ? "primary" : "secondary", onClick: () => updateUrl((s) => ({ ...s, page: 1, huntView: value })) }, label))),
        data?.ready && React.createElement("label", { className: "curator-toolbar-select" }, React.createElement(FontAwesomeIcon, { icon: faSortAmountDown }), React.createElement("select", { value: huntSort, onChange: (event) => updateUrl((s) => ({ ...s, page: 1, huntSort: event.target.value })), "aria-label": "Sort Performer Hunt results" }, React.createElement("option", { value: "date" }, "Release date"), React.createElement("option", { value: "score" }, "Preference score")))
      ),
      entityType === "hunt" && data?.truncated && React.createElement("div", { className: "alert alert-warning" }, `Showing the first ${data.fetched_count.toLocaleString()} of ${data.stashdb_total.toLocaleString()} Stash-box scenes; the safety cap is ${data.limit.toLocaleString()}. Counts below apply to the fetched scenes.`),
      entityType === "hunt" && filtersOpen && React.createElement(FilterBar, {
        variant: "hunt",
        entityType,
        includeTags, onIncludeTagsChange: (value) => updateUrl((s) => ({ ...s, includeTags: value })),
        excludeTags, onExcludeTagsChange: (value) => updateUrl((s) => ({ ...s, excludeTags: value })),
        hidePhashMatches, onToggleHidePhash: () => updateUrl((s) => ({ ...s, hidePhashMatches: !s.hidePhashMatches })),
        onApply: () => (updateUrl((s) => ({ ...s, page: 1 })), setFiltersOpen(false)),
      }),
      entityType !== "shortlist" && entityType !== "hunt" && filtersOpen && React.createElement(FilterBar, {
        variant: "expand",
        entityType,
        includeTags, onIncludeTagsChange: (value) => updateUrl((s) => ({ ...s, includeTags: value })),
        excludeTags, onExcludeTagsChange: (value) => updateUrl((s) => ({ ...s, excludeTags: value })),
        performers, onPerformersChange: (value) => updateUrl((s) => ({ ...s, performers: value })),
        studios, onStudiosChange: (value) => updateUrl((s) => ({ ...s, studios: value })),
        favoriteOnly, onToggleFavorite: () => updateUrl((s) => ({ ...s, page: 1, favoriteOnly: !s.favoriteOnly })),
        hidePhashMatches, onToggleHidePhash: () => updateUrl((s) => ({ ...s, page: 1, hidePhashMatches: !s.hidePhashMatches })),
        gender, onGenderChange: (event) => updateUrl((s) => ({ ...s, page: 1, gender: event.target.value })),
        minimum: minimumScore, onMinimumChange: (event) => updateUrl((s) => ({ ...s, minimumScore: Number(event.target.value) })),
        onApply: () => { clearEndlessCache(); updateUrl((s) => ({ ...s, page: 1 })); setFilterVersion((value) => value + 1); },
      }),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      message && React.createElement("p", { role: "status" }, message),
      entityType === "hunt" && !huntPerformer && React.createElement("div", { className: "alert alert-info" }, "Select a local performer linked to Stash-box."),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Loading candidates…")),
      data?.initializing && !error && React.createElement("div", { className: "alert alert-info", role: "status" }, data.initializing_reason === "endpoint" ? "Preparing candidates from the selected Stash-box endpoint. Results will appear automatically when this finishes. Progress is available in Manage → Tasks." : "Checking your library for scenes you already own. Candidates will appear automatically when this finishes. Progress is available in Manage → Tasks."),
      data && !data.ready && !data.initializing && React.createElement("div", { className: "alert alert-info" }, React.createElement("p", null, "Expand has not been prepared yet — Stash-box candidates need to be collected first."), React.createElement(Button, { size: "sm", variant: "primary", onClick: refresh }, React.createElement(FontAwesomeIcon, { icon: faSync }), " Prepare now")),
      data?.ready && visibleItems.length === 0 && React.createElement("div", { className: "alert alert-info" }, entityType === "hunt" ? "No scenes match this view." : "No external candidates match these filters."),
      pager,
      data?.ready && (endless
        ? !loading && React.createElement(EndlessFindResults, { key: JSON.stringify([entityType, sort, performerId, favoriteOnly, hidePhashMatches, gender, filterVersion, version, page, huntPerformer?.id, huntView, huntSort, pageSize]), cacheKey: endlessBatchKey(data, ["expand", continuationRequest.current, findView, huntView, huntSort, pageSize]), first: data, page, pageSize: entityType === "hunt" ? pageSize : data.page_size || pageSize, clientItems: entityType === "hunt" ? huntItems : null, loadPage: (nextPage) => operation({ ...continuationRequest.current, page: nextPage }), renderPage: renderExpandPage })
        : renderExpandPage({ ...data, items: visibleItems })),
      pager
    );
  }

  function BackupPanel() {
    const [data, setData] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [busy, setBusy] = React.useState(false);
    const [message, setMessage] = React.useState("");
    const [error, setError] = React.useState("");
    useCuratorActivity("backups", loading || busy, loading ? "Loading backups…" : "Updating backups…");
    async function load() {
      setLoading(true);
      try {
        setData(await operation({ operation: "list_backups" }));
      } catch (failure) {
        setError(failure.message);
      } finally {
        setLoading(false);
      }
    }
    React.useEffect(() => { load(); }, []);
    async function create() {
      setBusy(true);
      setError("");
      try {
        const result = await operation({ operation: "create_backup" }, 120000);
        setMessage(`Backup created: ${result.backup_path}`);
        setData((current) => ({ ...current, items: result.items }));
      } catch (failure) {
        setError(failure.message);
      } finally {
        setBusy(false);
      }
    }
    async function restore(item) {
      if (!window.confirm(`Restore ${item.id}? Curator will first back up the current sidecar.`)) return;
      setBusy(true);
      setError("");
      try {
        const result = await operation({
          operation: "restore_backup",
          backup_id: item.id,
          confirmation: `RESTORE ${item.id}`,
        }, 120000);
        clearSlateCache();
        setMessage(`Restored from ${result.restored_from}. Safety backup: ${result.safety_backup}`);
        await load();
      } catch (failure) {
        setError(failure.message);
      } finally {
        setBusy(false);
      }
    }
    async function remove(item) {
      if (!window.confirm(`Delete completed Curator backup ${item.id}?`)) return;
      setBusy(true);
      setError("");
      try {
        const result = await operation({
          operation: "delete_backup",
          backup_id: item.id,
          confirmation: `DELETE ${item.id}`,
        });
        setMessage(`Deleted backup ${result.deleted}.`);
        setData((current) => ({ ...current, items: result.items }));
      } catch (failure) {
        setError(failure.message);
      } finally {
        setBusy(false);
      }
    }
    return React.createElement(
      "section",
      { className: "curator-backup-page" },
      React.createElement(Button, { size: "sm", disabled: busy, onClick: create }, busy ? "Working…" : "Create backup"),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, "Loading backups…"),
      data && React.createElement("p", null, "Backup directory: ", React.createElement("code", { className: "curator-mono" }, data.backup_directory)),
      message && React.createElement("div", { className: "alert alert-success", role: "status" }, message),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      data && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No Curator backups found."),
      data && data.items.length > 0 && React.createElement(
        "div",
        { className: "curator-record-list" },
        data.items.map((item) => React.createElement(
          "div",
          { key: item.id, className: "curator-record-row" },
          React.createElement("span", { className: "curator-record-icon" }, React.createElement(FontAwesomeIcon, { icon: faDatabase })),
          React.createElement(
            "div",
            { className: "curator-record-main" },
            React.createElement("div", { className: "curator-record-title" }, item.id),
            React.createElement("div", { className: "curator-record-meta" }, `${new Date(item.created_at_ms).toLocaleString()} · ${(item.size_bytes / 1048576).toFixed(1)} MB`)
          ),
          React.createElement(Button, { size: "sm", variant: "link", disabled: busy, onClick: () => restore(item) }, "Restore"),
          React.createElement(Button, { size: "sm", variant: "link", className: "curator-record-destructive", disabled: busy, onClick: () => remove(item) }, "Delete")
        ))
      )
    );
  }

  function flameGraphRows(node, rootTotal) {
    const rows = [];
    const rowHeight = 18;
    const maxDepth = 60;
    const minWidthPct = 0.15;
    const collect = (n, depth, x) => {
      if (depth > maxDepth) return;
      const widthPct = (n.total / rootTotal) * 100;
      if (widthPct < minWidthPct) return;
      rows.push({ node: n, depth, x, width: widthPct });
      let cx = x;
      for (const child of (n.children || [])) {
        collect(child, depth + 1, cx);
        cx += (child.total / rootTotal) * 100;
      }
    };
    collect(node, 0, 0);
    return { rows, rowHeight };
  }

  function truncateText(value, max) {
    if (!value || value.length <= max) return value || "";
    return `${value.slice(0, max - 1)}…`;
  }

  function ProfilingPanel() {
    const [profiles, setProfiles] = React.useState(null);
    const [selected, setSelected] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState("");
    const [pprofs, setPprof] = React.useState(null);
    const [pprofError, setPprofError] = React.useState("");
    const [pprofView, setPprofView] = React.useState(null);
    const [flameRoot, setFlameRoot] = React.useState(null);
    useCuratorActivity("profiling", loading, "Loading profiles…");

    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await operation({ operation: "list_profiles", limit: 200 });
        setProfiles(data);
        if (selected && !data.items.some((item) => item.trace_id === selected.trace_id)) {
          setSelected(null);
        }
      } catch (failure) {
        setError(failure.message);
      } finally {
        setLoading(false);
      }
    }

    React.useEffect(() => { load(); }, []);

    async function loadPprof() {
      setPprofError("");
      try {
        setPprof(await operation({ operation: "list_pprof_files" }));
      } catch (failure) {
        setPprofError(failure.message);
      }
    }

    React.useEffect(() => { loadPprof(); }, []);

    async function downloadPprof(name) {
      setPprofError("");
      try {
        const data = await operation({ operation: "get_pprof_file", name });
        const bytes = Uint8Array.from(atob(data.content_base64), (c) => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: "application/octet-stream" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = name;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 0);
      } catch (failure) {
        setPprofError(failure.message);
      }
    }

    async function viewPprof(name) {
      setPprofError("");
      try {
        const data = await operation({ operation: "get_pprof_summary", name });
        setPprofView(data);
        setFlameRoot(null);
      } catch (failure) {
        setPprofError(failure.message);
      }
    }

    async function clearPprof() {
      if (!window.confirm("Delete all captured CPU profiles?")) return;
      setPprofError("");
      try {
        await operation({ operation: "clear_pprof_files" });
        await loadPprof();
      } catch (failure) {
        setPprofError(failure.message);
      }
    }

    function formatSize(bytes) {
      if (bytes >= 1024 * 1024) {
        return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
      }
      return `${Math.max(1, Math.round(bytes / 1024))} KiB`;
    }

    const flame = flameRoot || pprofView?.flame;
    const flameTotal = flameRoot ? flameRoot.total : (pprofView?.total || 1);
    const flameData = flame ? flameGraphRows(flame, flameTotal) : { rows: [], rowHeight: 18 };
    const flameHeight = flameData.rows.length ? (Math.max(...flameData.rows.map((r) => r.depth)) + 1) * flameData.rowHeight : 0;
    const unit = pprofView?.unit_label || "";
    const flameRects = flameData.rows.map((row, index) => React.createElement("g", { key: index, onClick: () => setFlameRoot(row.node), style: { cursor: "pointer" } },
      React.createElement("rect", { x: row.x * 10, y: row.depth * flameData.rowHeight, width: Math.max(0.5, row.width * 10), height: flameData.rowHeight - 1, fill: `hsl(${(row.depth * 47) % 360}, 60%, 62%)` },
        React.createElement("title", null, `${row.node.name}\n${row.node.total.toFixed(1)} ${unit} total · ${row.node.self.toFixed(1)} ${unit} self${row.node.location ? ` · ${row.node.location}` : ""}`),
      ),
      row.width * 10 >= 12 && React.createElement("text", { x: row.x * 10 + 3, y: row.depth * flameData.rowHeight + 13, fontSize: 10, fill: "#fff" }, truncateText(row.node.name, Math.max(1, Math.floor(row.width * 10 / 6.5)))),
    ));

    const pprofSection = React.createElement("div", { className: "curator-pprof" },
      React.createElement("div", { className: "curator-profiling-toolbar" },
        React.createElement("h3", null, "CPU profiles"),
        React.createElement(Button, { size: "sm", variant: "secondary", onClick: loadPprof }, "Refresh"),
        React.createElement(Button, { size: "sm", variant: "danger", onClick: clearPprof, disabled: !pprofs?.items?.length }, "Clear"),
      ),
      !pprofs?.enabled && React.createElement("div", { className: "alert alert-info" }, "Capture is off. Enable \u201cCapture CPU profiles\u201d in the plugin settings, then run the operation to profile it."),
      pprofError && React.createElement("div", { className: "alert alert-danger" }, pprofError),
      pprofs && !pprofs.items.length && React.createElement("div", { className: "alert alert-info" }, "No CPU profiles captured yet."),
      pprofs?.items?.length > 0 && React.createElement("table", { className: "table table-sm" },
        React.createElement("thead", null, React.createElement("tr", null, React.createElement("th", null, "File"), React.createElement("th", null, "Size"), React.createElement("th", null, "Captured"), React.createElement("th", null, ""))),
        React.createElement("tbody", null, pprofs.items.map((item) => React.createElement("tr", { key: item.name },
          React.createElement("td", null, item.name),
          React.createElement("td", null, formatSize(item.size_bytes)),
          React.createElement("td", null, new Date(item.modified_ms).toLocaleString()),
          React.createElement("td", null, React.createElement(Button, { size: "sm", variant: "secondary", onClick: () => viewPprof(item.name) }, "View"), " ", React.createElement(Button, { size: "sm", variant: "secondary", onClick: () => downloadPprof(item.name) }, React.createElement(FontAwesomeIcon, { icon: faDownload }), " Download")),
        ))),
      ),
      pprofView && React.createElement("div", { className: "curator-pprof-detail" },
        React.createElement("div", { className: "curator-profiling-toolbar" },
          React.createElement("h4", null, pprofView.name),
          flameRoot ? React.createElement(Button, { size: "sm", variant: "secondary", onClick: () => setFlameRoot(null) }, "Back to root") : null,
        ),
        React.createElement("p", null, `${pprofView.kind} · ${pprofView.unit_label} · ${pprofView.sample_count} samples · ${pprofView.total.toFixed(1)} ${pprofView.unit_label}${pprofView.duration_ms ? ` · ${pprofView.duration_ms} ms captured` : ""}`),
        flameHeight > 0 && React.createElement("svg", { viewBox: `0 0 1000 ${flameHeight}`, preserveAspectRatio: "xMidYMid meet", className: "curator-flamegraph" }, flameRects),
        pprofView.top && pprofView.top.length > 0 && React.createElement("div", { className: "curator-profile-table-wrap" },
          React.createElement("h5", null, "Top functions"),
          React.createElement("table", { className: "table table-sm" },
            React.createElement("thead", null, React.createElement("tr", null, React.createElement("th", null, "#"), React.createElement("th", null, "Function"), React.createElement("th", null, `Flat (${pprofView.unit_label})`), React.createElement("th", null, "Flat %"), React.createElement("th", null, `Cum (${pprofView.unit_label})`), React.createElement("th", null, "Cum %"))),
            React.createElement("tbody", null, pprofView.top.map((row, index) => React.createElement("tr", { key: row.name },
              React.createElement("td", null, index + 1),
              React.createElement("td", null, row.name),
              React.createElement("td", null, row.flat.toFixed(1)),
              React.createElement("td", null, `${row.flat_pct.toFixed(1)}%`),
              React.createElement("td", null, row.cum.toFixed(1)),
              React.createElement("td", null, `${row.cum_pct.toFixed(1)}%`),
            ))),
          ),
        ),
      ),
    );


    async function inspect(traceId) {
      setError("");
      try {
        setSelected(await operation({ operation: "get_profile", trace_id: traceId }));
      } catch (failure) {
        setError(failure.message);
      }
    }

    async function clear() {
      if (!window.confirm("Clear all saved Curator profiles?")) return;
      try {
        await operation({ operation: "clear_profiles", confirmation: "CLEAR" });
        setSelected(null);
        await load();
      } catch (failure) {
        setError(failure.message);
      }
    }

    function exportTrace() {
      if (!selected) return;
      const blob = new Blob([JSON.stringify(selected.trace)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const operationName = selected.operation.replace(/[^a-z0-9_-]/gi, "-");
      link.download = `curator-${operationName}-${selected.trace_id}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    }

    const events = (selected?.trace?.traceEvents || []).filter((event) => event.ph === "X");
    const root = events[0];
    const spans = events.slice(1).sort((left, right) => right.dur - left.dur);
    const visibleSpans = spans.slice(0, 500);
    const total = Math.max(1, root?.dur || 1);
    const formatDuration = (microseconds) => microseconds >= 1000
      ? `${(microseconds / 1000).toFixed(1)} ms`
      : `${microseconds} µs`;

    return React.createElement(
      "section",
      { className: "curator-profiling", role: "tabpanel" },
      !profiles?.enabled && React.createElement("div", { className: "alert alert-info" }, "Profiling is disabled. Enable it in Curator's plugin settings to record new operations; saved profiles remain available."),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      React.createElement("div", { className: "curator-profiling-toolbar" }, React.createElement("h2", null, "Recent profiles"), React.createElement(Button, { size: "sm", variant: "secondary", onClick: load, disabled: loading }, "Refresh"), React.createElement(Button, { size: "sm", variant: "danger", onClick: clear, disabled: !profiles?.items?.length }, "Clear")),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, "Loading profiles…"),
      profiles && !loading && profiles.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No profiles have been recorded yet."),
      profiles?.items?.length > 0 && React.createElement("div", { className: "curator-profile-layout" },
        React.createElement("div", { className: "curator-profile-list", role: "list" }, profiles.items.map((item) => React.createElement("button", { key: item.trace_id, type: "button", className: selected?.trace_id === item.trace_id ? "active" : "", onClick: () => inspect(item.trace_id) }, React.createElement("strong", null, item.operation), React.createElement("span", null, `${item.kind} · ${formatDuration(item.duration_us)}`), React.createElement("small", null, `${new Date(item.started_at_ms).toLocaleString()} · ${item.status}${item.truncated ? " · truncated" : ""}`)))),
        selected && React.createElement("div", { className: "curator-profile-detail" },
          React.createElement("div", { className: "curator-profiling-toolbar" }, React.createElement("h2", null, selected.operation), React.createElement(Button, { size: "sm", variant: "secondary", onClick: exportTrace }, React.createElement(FontAwesomeIcon, { icon: faDownload }), " Export trace")),
          React.createElement("p", null, `${formatDuration(selected.duration_us)} · ${selected.span_count} spans · ${selected.status}`),
          React.createElement("div", { className: "curator-profile-timeline", "aria-label": "Trace timeline" }, spans.slice(0, 100).map((event, index) => React.createElement("div", { key: `${event.name}-${index}`, title: `${event.cat}: ${event.name} (${formatDuration(event.dur)})` }, React.createElement("span", { className: `curator-profile-${event.cat}`, style: { marginLeft: `${Math.max(0, ((event.ts - root.ts) / total) * 100)}%`, width: `${Math.max(0.4, (event.dur / total) * 100)}%` } })))),
          spans.length > visibleSpans.length && React.createElement("small", null, `Showing the 500 longest of ${spans.length} spans; export contains all spans.`),
          React.createElement("div", { className: "curator-profile-table-wrap" }, React.createElement("table", { className: "table table-sm curator-profile-table" }, React.createElement("thead", null, React.createElement("tr", null, React.createElement("th", null, "Category"), React.createElement("th", null, "Span"), React.createElement("th", null, "Duration"), React.createElement("th", null, "Details"))), React.createElement("tbody", null, visibleSpans.map((event, index) => React.createElement("tr", { key: `${event.name}-${index}` }, React.createElement("td", null, event.cat), React.createElement("td", null, event.name), React.createElement("td", null, formatDuration(event.dur)), React.createElement("td", null, [event.args?.statement, event.args?.peak_rss_kb && `peak ${event.args.peak_rss_kb} kB`, event.args?.heap_alloc_kb && `heap ${event.args.heap_alloc_kb} kB`].filter(Boolean).join(" · ")))))))
        ),
      pprofSection
      )
    );
  }

  function DiagnosticsPanel() {
    const [report, setReport] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [message, setMessage] = React.useState("");
    const [error, setError] = React.useState("");
    useCuratorActivity("diagnostics", loading, "Loading diagnostics…");
    async function load() {
      setLoading(true);
      setError("");
      try {
        setReport(await operation({ operation: "get_diagnostics" }));
      } catch (failure) {
        setError(failure.message);
      } finally {
        setLoading(false);
      }
    }
    React.useEffect(() => { load(); }, []);
    const preview = report ? JSON.stringify(report, null, 2) : "";
    async function copy() {
      try {
        await copyText(preview);
        setMessage("Diagnostics copied.");
      } catch (failure) {
        setError(failure.message);
      }
    }
    function download() {
      const url = URL.createObjectURL(new Blob([preview], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "stash-curator-diagnostics.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    }
    return React.createElement(
      "section",
      { className: "curator-diagnostics", role: "tabpanel" },
      React.createElement("p", null, "This allowlisted report excludes library metadata, identifiers, paths, URLs, credentials, preferences, and SQL. Profiling traces are separate and are not included."),
      React.createElement(
        "div",
        { className: "curator-profiling-toolbar" },
        React.createElement(Button, { size: "sm", variant: "secondary", onClick: load }, "Refresh"),
        React.createElement(Button, { size: "sm", variant: "secondary", disabled: !report, onClick: copy }, React.createElement(FontAwesomeIcon, { icon: faCopy }), " Copy"),
        React.createElement(Button, { size: "sm", variant: "secondary", disabled: !report, onClick: download }, React.createElement(FontAwesomeIcon, { icon: faDownload }), " Download JSON")
      ),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, "Loading diagnostics…"),
      message && React.createElement("div", { className: "alert alert-success", role: "status" }, message),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      report && React.createElement("pre", { className: "curator-diagnostics-preview" }, preview)
    );
  }

  function curatorTaskStage(job) {
    const description = String(job.description || "").toLowerCase();
    const progress = typeof job.progress === "number" ? job.progress : null;
    const stages = description.includes("local scene matches")
      ? [[0.7, "Checking your library"], [0.99, "Saving library matches"]]
      : description.includes("expand")
        ? [[0.04, "Checking your library"], [0.98, "Collecting Stash-box candidates"], [0.99, "Finishing"]]
      : description.includes("sync")
      ? [
          [0.03, "Synchronizing library metadata"],
          [0.58, "Rebuilding preference history"],
          [0.68, "Building the recommendation model"],
          [0.95, "Organizing recommendation lanes"],
          [0.97, "Preparing recommendation pages"],
          [0.99, "Finishing"],
        ]
      : description.includes("rebuild") || description.includes("feedback")
        ? [
            [0.1, "Building the recommendation model"],
            [0.95, "Organizing recommendation lanes"],
            [0.97, "Preparing recommendation pages"],
            [0.99, "Finishing"],
          ]
        : description.includes("prepare")
          ? [[0.05, "Preparing recommendation pages"], [0.99, "Finishing"]]
          : description.includes("backup")
            ? [[0.05, "Creating Curator backup"], [0.98, "Finishing"]]
            : description.includes("compact")
              ? [[0.1, "Compacting legacy data"], [0.98, "Finishing"]]
              : description.includes("vacuum")
                ? [[0.1, "Vacuuming the database"], [0.98, "Finishing"]]
                : description.includes("optional") || description.includes("dependenc")
                    ? [[0.05, "Creating the optional dependency environment"], [0.3, "Installing optional dependencies"], [0.95, "Finishing"]]
                    : [[0, "Working"]];
    if (progress === null) return "Working";
    let stage = "Starting task";
    stages.forEach(([threshold, label]) => {
      if (progress >= threshold) stage = label;
    });
    return stage;
  }

  const TASK_MODE_LABELS = {
    "local-matches": "Prepare local scene matches",
    "sync-build": "Sync and build recommendations",
    "full-sync-build": "Full sync and build recommendations",
    build: "Rebuild recommendation model",
    "force-build": "Force rebuild recommendation model",
    "update-model": "Apply recent Curator feedback",
    prepare: "Prepare recommendation pages",
    "sync-plays": "Sync recent plays",
    backup: "Backup Curator data",
    compact: "Compact legacy Curator data",
    vacuum: "Vacuum compacted Curator data",
    "expand-refresh": "Refresh Expand cache",
  };

  function taskModeLabel(job) {
    return TASK_MODE_LABELS[job?.job_type] || "Curator task";
  }

  // doneJob is a curator_job row that just completed; the indicator shows it
  // at 100% ("Done") until it ages out (issue #110: the final 1.0 marker
  // leaves Stash's queue before the 5 s poll can catch it, so the bar used
  // to freeze at the last sub-100% value and then revert to idle).
  function CuratorTaskIndicator({ activeJobs, activities, failure, doneJob, tasksHref }) {
    const running = activeJobs.length > 0 || activities.length > 0;
    const doneTask = !running && doneJob
      ? { key: `done-${doneJob.job_id}`, label: taskModeLabel(doneJob), progress: 1, stage: "Done" }
      : null;
    const tasks = [
      ...activeJobs.map((job) => ({
        key: `job-${job.id}`,
        label: job.description || "Curator task",
        progress: typeof job.progress === "number" ? Math.max(0, Math.min(job.progress, 1)) : null,
        stage: curatorTaskStage(job),
      })),
      ...activities.map((activity) => ({ ...activity, stage: activity.label })),
      ...(doneTask ? [doneTask] : []),
    ];
    const primary = tasks[0];
    const state = running ? "running" : failure ? "failed" : doneTask ? "done" : "idle";
    const progress = primary?.progress ?? null;
    const showTaskDetails = running || state === "failed" || state === "done";
    const detail = tasks.map((task) => `${task.label}: ${task.stage}`).join("; ");
    const label = running
      ? `${tasks.length} Curator task${tasks.length === 1 ? "" : "s"} running: ${detail}`
      : failure
        ? `Last Curator task failed: ${actionError(failure.error || "Open Tasks for details")}`
        : doneTask
          ? `Curator task complete: ${doneTask.label}`
          : "Curator is idle";
    return React.createElement(
      NavLink,
      { className: `curator-task-indicator curator-task-indicator-${state}`, to: tasksHref, title: `${label}. Open Tasks`, "aria-label": `${label}. Open Tasks` },
      React.createElement(
        "span",
        { className: "curator-task-progress", "aria-hidden": "true" },
        showTaskDetails && React.createElement(
          "span",
          { className: "curator-task-progress-meta" },
          React.createElement("strong", null, running ? progress === null ? "Working" : `${Math.round(progress * 100)}%` : doneTask ? "Done" : "Failed"),
          running && tasks.length > 1 && React.createElement("span", null, `${tasks.length} tasks`)
        ),
        React.createElement(
          "span",
          { className: `curator-task-progress-track${running && progress === null ? " curator-task-progress-indeterminate" : ""}` },
          React.createElement("span", { className: "curator-task-progress-fill", style: (running || doneTask) && progress !== null ? { width: `${Math.round(progress * 100)}%` } : undefined })
        ),
        showTaskDetails && React.createElement("span", { className: "curator-task-progress-detail" }, running ? primary?.stage : doneTask ? "Done" : failure.error || "Open Tasks for details")
      )
    );
  }

  // TasksPanel lists the worker-owned curator_job rows (decision 004): the
  // real status surface for background tasks, since Stash's own Tasks tab
  // only ever sees the instant enqueue jobs now.
  function TasksPanel() {
    const [jobs, setJobs] = React.useState([]);
    const [error, setError] = React.useState("");
    const [starting, setStarting] = React.useState("");
    const [message, setMessage] = React.useState("");
    function refresh() {
      operation({ operation: "get_job_status" }).then(
        (result) => { setError(""); setJobs(result.jobs || []); },
        (failure) => setError(failure.message)
      );
    }
    React.useEffect(() => {
      refresh();
      const timer = setInterval(refresh, 4000);
      return () => clearInterval(timer);
    }, []);
    const active = jobs.filter((job) => job.state === "queued" || job.state === "running");
    const finished = jobs.filter((job) => job.state !== "queued" && job.state !== "running");
    const running = active.length > 0;
    const last = jobs[0];
    function durationMs(job) {
      const end = typeof job.finished_at_ms === "number" ? job.finished_at_ms : Date.now();
      const start = typeof job.started_at_ms === "number" ? job.started_at_ms : end;
      return Math.max(0, end - start);
    }
    function formatDuration(ms) {
      const seconds = Math.round(ms / 1000);
      if (seconds < 60) return `${seconds}s`;
      const minutes = Math.floor(seconds / 60);
      if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
      return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
    }
    function summaryLine(job) {
      const summary = job.summary || {};
      const scenes = typeof summary.scene_count === "number" ? `${summary.scene_count} scenes` : "";
      if (job.job_type === "build" || job.job_type === "force-build" || job.job_type === "update-model" || job.job_type === "sync-build" || job.job_type === "full-sync-build") {
        return scenes ? `Model built · ${scenes}` : "Model built";
      }
      if (job.job_type === "backup") return "Backup created";
      if (job.job_type === "compact") return "Compaction finished";
      if (job.job_type === "expand-refresh") return "Stash-box candidates refreshed";
      if (job.job_type === "local-matches") return "Library check finished";
      if (job.job_type === "sync-plays") return "Play history synced";
      return scenes || "Done";
    }
    function taskRow(job) {
      const label = TASK_MODE_LABELS[job.job_type] || job.job_type;
      const pct = typeof job.progress === "number" ? Math.max(0, Math.min(job.progress, 1)) : null;
      const stateLabel = job.state === "complete" ? "Done" : job.state === "running" ? "Running" : job.state.charAt(0).toUpperCase() + job.state.slice(1);
      return React.createElement(
        "li",
        { key: job.job_id, className: `curator-task curator-task-${job.state}` },
        React.createElement(
          "div",
          { className: "curator-task-head" },
          React.createElement("strong", null, label),
          React.createElement("span", { className: `curator-task-state curator-task-state-${job.state}` }, stateLabel),
          React.createElement("span", { className: "curator-task-time" }, job.state === "running" ? `started ${formatTimeAgo(job.started_at_ms)}` : `took ${formatDuration(durationMs(job))}`)
        ),
        (job.state === "running" || job.state === "queued") && React.createElement(
          "div",
          { className: "curator-task-progress-track" },
          React.createElement("span", { className: "curator-task-progress-fill", style: pct !== null ? { width: `${Math.round(pct * 100)}%` } : undefined })
        ),
        React.createElement(
          "div",
          { className: "curator-task-meta" },
          (job.state === "running" || job.state === "queued")
            ? (pct !== null ? `${Math.round(pct * 100)}%` : job.state === "running" ? "Working" : "Queued")
            : summaryLine(job),
          job.error && React.createElement("span", { className: "curator-task-error" }, job.error)
        )
      );
    }

    async function start(taskName) {
      setStarting(taskName);
      setMessage("");
      try {
        await runTask(taskName);
        setMessage("Task started — progress appears below.");
        setTimeout(refresh, 1000);
      } catch (failure) {
        setMessage(failure.message);
      } finally {
        setStarting("");
      }
    }
    async function restartWorker() {
      // Restarting stops the resident worker with SIGTERM, which marks any
      // in-flight job cancelled — the guard op refuses unless force is set,
      // so confirm up front when a task is visibly running.
      const runningJob = active.find((job) => job.state === "running");
      if (runningJob && !window.confirm(
        `Restart the Curator worker? The running task (${TASK_MODE_LABELS[runningJob.job_type] || runningJob.job_type}) is cancelled and must be run again.`
      )) return;
      setStarting("Restart worker");
      setMessage("");
      try {
        const result = await operation(
          runningJob ? { operation: "restart_worker", force: true } : { operation: "restart_worker" }
        );
        if (result.refused) {
          setMessage(result.reason || "Restart refused — a Curator task is running.");
          setTimeout(refresh, 1000);
          return;
        }
        setMessage(
          result.restarted
            ? `Worker restarted${result.stopped_pid ? ` (stopped pid ${result.stopped_pid})` : ""}.`
            : "Worker was not running; ensured one is available."
        );
        setTimeout(refresh, 1000);
      } catch (failure) {
        setMessage(failure.message);
      } finally {
        setStarting("");
      }
    }
    return React.createElement(
      "div",
      { className: "curator-tasks-panel" },
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      React.createElement("p", null, "Tasks run in Curator's own background worker, so they keep going even after the Stash-side job completes — progress and results are shown here."),
      React.createElement(
        "div",
        { className: "curator-tasks-runnow" },
        React.createElement("span", null, "Run now"),
        React.createElement(Button, { size: "sm", variant: "secondary", disabled: Boolean(starting), onClick: () => start("Prepare local scene matches") }, starting === "Prepare local scene matches" ? "Starting…" : "Check local library"),
        React.createElement(Button, { size: "sm", variant: "primary", disabled: Boolean(starting), onClick: () => start("Sync and build recommendations") }, starting === "Sync and build recommendations" ? "Starting…" : "Sync and build recommendations"),
        React.createElement(Button, { size: "sm", variant: "outline-danger", disabled: Boolean(starting), onClick: () => start("Force rebuild recommendation model") }, starting === "Force rebuild recommendation model" ? "Starting…" : "Force rebuild model"),
        React.createElement(Button, { size: "sm", variant: "secondary", disabled: Boolean(starting), onClick: () => start("Force rebuild Expand cache") }, starting === "Force rebuild Expand cache" ? "Starting…" : "Force rebuild Expand cache")
      ),
      message && React.createElement("p", { className: "curator-header-message", role: "status" }, message),
      React.createElement(
        "div",
        { className: `curator-worker-status curator-worker-status-${running ? "running" : "idle"}` },
        React.createElement("span", { className: "curator-worker-status-dot", "aria-hidden": "true" }),
        React.createElement("strong", null, running ? "Worker running" : "Worker idle"),
        running
          ? `${active.length} task${active.length === 1 ? "" : "s"} active`
          : last
            ? `Last task: ${TASK_MODE_LABELS[last.job_type] || last.job_type} · ${formatTimeAgo(last.finished_at_ms || last.started_at_ms)}`
            : "No tasks yet"
      ),
      React.createElement(Button, { size: "sm", variant: "outline-secondary", disabled: Boolean(starting), onClick: restartWorker }, starting === "Restart worker" ? "Restarting…" : "Restart worker"),
      jobs.length === 0 && !error && React.createElement("p", { role: "status" }, "No tasks yet."),
      active.length > 0 && React.createElement(
        "section",
        { className: "curator-tasks-section" },
        React.createElement("h4", { className: "curator-tasks-section-title" }, "Active"),
        React.createElement("ul", { className: "curator-tasks-list" }, active.map(taskRow))
      ),
      finished.length > 0 && React.createElement(
        "details",
        { className: "curator-tasks-completed", open: active.length === 0 },
        React.createElement("summary", null, `Completed (${finished.length})`),
        React.createElement("ul", { className: "curator-tasks-list" }, finished.map(taskRow))
      )
    );
  }

  function CuratorControls({ onRefresh, theme, onToggleTheme, cardSize, onChangeCardSize, onOpenManage, manageDescription }) {
    const routeLocation = useLocation();
    const [jobs, setJobs] = React.useState([]);
    const [health, setHealth] = React.useState(null);
    const [message, setMessage] = React.useState("");
    const activities = useLocalActivities();

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
    // Poll continuously so the indicator and health pill update without a
    // manual refresh. The old effect armed a one-shot setTimeout when idle,
    // whose trigger (the active-job boolean) never changed after it fired —
    // so once one idle poll ran the chain never re-armed and the UI froze
    // until the user refreshed the page (a task started while idle never
    // appeared). A ref keeps the latest refreshStatus so a model change
    // still clears the slate cache / refreshes recommendations.
    const refreshRef = React.useRef(refreshStatus);
    refreshRef.current = refreshStatus;
    React.useEffect(() => {
      let cancelled = false;
      let timer;
      const poll = async () => {
        try {
          await refreshRef.current();
        } finally {
          if (!cancelled) timer = setTimeout(poll, 4000);
        }
      };
      poll();
      return () => {
        cancelled = true;
        clearTimeout(timer);
      };
    }, []);

    async function start(taskName) {
      try {
        await runTask(taskName);
        setMessage("Task started — progress and results appear in Manage → Tasks.");
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
    const activeJobs = health?.active_jobs || (health?.active_job ? [health.active_job] : []);
    const activeJob = activeJobs[0];
    const latestFailure = !activeJobs.length && jobs[0]?.state === "failed" ? jobs[0] : null;
    const recentlyDone =
      !activeJobs.length && jobs[0]?.state === "complete"
        ? jobs[0]
        : null;
    const [doneExpiredAt, setDoneExpiredAt] = React.useState(0);
    React.useEffect(() => {
      if (!recentlyDone) return undefined;
      const timer = setTimeout(
        () => setDoneExpiredAt(Date.now()),
        Math.max(0, recentlyDone.finished_at_ms + 15_000 - Date.now())
      );
      return () => clearTimeout(timer);
    }, [recentlyDone?.job_id]);
    const doneJob =
      recentlyDone && recentlyDone.finished_at_ms > doneExpiredAt ? recentlyDone : null;
    const setupChecklist = health && !health.ready && React.createElement(
      "section",
      { className: "curator-setup-checklist", "aria-labelledby": "curator-setup-heading" },
      React.createElement("h2", { id: "curator-setup-heading" }, "Finish Curator setup"),
      React.createElement(
        "ul",
        null,
        React.createElement("li", null, React.createElement(FontAwesomeIcon, { icon: health.sidecar_ready ? faCheckCircle : faWrench }), ` Sidecar and migrations: ${health.sidecar_ready ? `ready (schema ${health.database_schema})` : "needs attention"}`),
        React.createElement("li", null, React.createElement(FontAwesomeIcon, { icon: health.sync_ready ? faCheckCircle : faClock }), ` Library sync: ${health.sync_ready ? "complete" : activeJob ? "running" : "not started"}`),
        React.createElement("li", null, React.createElement(FontAwesomeIcon, { icon: health.ready ? faCheckCircle : faClock }), ` Recommendation model: ${health.model_rebuilding ? "building" : "not built"}`),
        React.createElement("li", null, React.createElement(FontAwesomeIcon, { icon: health.stashdb_available ? faCheckCircle : faGlobe }), ` Stash-box: ${health.stashdb_available ? "available" : "optional — not configured"}`)
      ),
      lastError && React.createElement("div", { className: "alert alert-danger" }, React.createElement("strong", null, "Initial sync failed: "), lastError.error, " Open Tasks for the full log, correct the problem, then retry."),
      React.createElement(
        "div",
        { className: "curator-setup-actions" },
        React.createElement(Button, { size: "sm", disabled: Boolean(activeJob), onClick: () => start("Sync and build recommendations") }, activeJob ? "Setup task running…" : "Sync and build recommendations"),
        React.createElement(NavLink, { className: "btn btn-secondary btn-sm", to: "/settings?tab=plugins" }, "Open plugin settings")
      )
    );

    // Api.components.HoverPopover is only registered once some other part of
    // Stash's own app has mounted first — on a cold/direct navigation to the
    // Curator page it can still be undefined here (confirmed empirically: it
    // reliably resolves in-app, but not on a fresh load of /plugins/stash-
    // curator). CuratorControls always renders, so fall back to the trigger
    // pill alone rather than crashing the whole page on an invalid element.
    const { HoverPopover } = Api.components;
    // "Synced" on its own only ever meant "has a sync ever completed" — it
    // never told you whether the model itself needs attention (pending
    // events not yet folded in, or a rebuild already underway), so the pill
    // could read "Synced" right when a rebuild would actually be useful.
    // Surface those states in both the pulse color and the label text
    // instead of only inside the hover popover.
    const pillState = running ? "running"
      : latestFailure ? "failed"
        : health?.model_rebuilding ? "rebuilding"
          : health?.model_pending ? "pending"
            : hasSynced ? "ready" : "idle";
    const pillLabel = {
      running: activeJob
        ? `${TASK_MODE_LABELS[activeJob.job_type] || "Curator task"}${activeJob.progress != null ? ` · ${Math.round(activeJob.progress * 100)}%` : ""}`
        : "Running",
      failed: "Failed",
      rebuilding: "Rebuilding",
      pending: `${health?.model_pending_events || 0} pending`,
      ready: "Synced",
      idle: "Not synced",
    }[pillState];
    const healthTrigger = React.createElement(
      NavLink,
      { className: "curator-health-pill", to: `${routeLocation.pathname}?view=manage&section=tasks`, title: "Open Tasks", "aria-label": `${pillLabel}. Open Tasks` },
      React.createElement("span", { className: `curator-health-pulse curator-health-pulse-${pillState}` }),
      React.createElement("span", { className: "curator-health-pill-label" }, pillLabel)
    );
    const healthControl = HoverPopover
      ? React.createElement(
          HoverPopover,
          {
            className: "curator-health-trigger",
            enterDelay: 150,
            leaveDelay: 250,
            placement: "bottom",
            content: React.createElement(
              "div",
              { className: "curator-health-panel", role: "status" },
              React.createElement("div", { className: "curator-health-row" }, React.createElement("span", null, "Sync"), React.createElement("b", null, running ? `Running ${running.job_type}` : hasSynced ? "Synced" : "Not synced")),
              React.createElement(CuratorTaskIndicator, { activeJobs, activities, failure: latestFailure, doneJob, tasksHref: `${routeLocation.pathname}?view=manage&section=tasks` }),
              React.createElement("div", { className: "curator-health-row" }, React.createElement("span", null, "Model"), React.createElement("b", null, health?.model_pending ? `${health.model_pending_events} waiting` : modelStatus)),
              React.createElement("div", { className: "curator-health-row" }, React.createElement("span", null, "Playback sessions captured"), React.createElement("b", null, health?.capture?.direct_playback_sessions || 0)),
              health?.last_sync_at_ms && React.createElement("div", { className: "curator-health-row" }, React.createElement("span", null, "Last sync"), React.createElement("b", null, new Date(health.last_sync_at_ms).toLocaleString()))
            ),
          },
          healthTrigger
        )
      : healthTrigger;
    // Native disclosure works with keyboard/touch and on cold loads before
    // Stash registers HoverPopover.
    const cardSizeControl = onChangeCardSize && React.createElement(
      "details",
      { className: "curator-card-size-trigger" },
      React.createElement("summary", { className: "curator-icon-button btn btn-sm", title: `Card size (${cardSize}rem)`, "aria-label": `Adjust card size: ${cardSize}rem` }, React.createElement(FontAwesomeIcon, { icon: faThLarge })),
      React.createElement(
        "div",
        { className: "curator-card-size-panel" },
        React.createElement("div", { className: "curator-card-size-head" }, React.createElement("label", { htmlFor: "curator-card-size-input" }, "Card size"), React.createElement("span", null, `${cardSize}rem`)),
        React.createElement("input", {
          id: "curator-card-size-input",
          type: "range",
          className: "curator-range",
          min: CARD_SIZE_MIN,
          max: CARD_SIZE_MAX,
          step: 1,
          value: cardSize,
          "aria-label": "Card size",
          onChange: (event) => onChangeCardSize(Number(event.target.value)),
        })
      )
    );
    return React.createElement(
      React.Fragment,
      null,
      React.createElement(
        "section",
        { className: "curator-controls" },
        healthControl,
        React.createElement(
          "div",
          { className: "curator-task-buttons" },
          React.createElement(Button, { className: "curator-icon-button", size: "sm", title: manageDescription || "Manage — settings, tasks, taste profile, backups, and diagnostics.", "aria-label": "Open Manage", onClick: onOpenManage }, React.createElement(FontAwesomeIcon, { icon: faWrench })),
          React.createElement(Button, { className: "curator-icon-button", size: "sm", title: theme === "light" ? "Switch to dark theme" : "Switch to light theme", "aria-label": theme === "light" ? "Switch to dark theme" : "Switch to light theme", onClick: onToggleTheme }, React.createElement(FontAwesomeIcon, { icon: theme === "light" ? faMoon : faSun })),
          cardSizeControl
        )
      ),
      setupChecklist,
      lastError && React.createElement("small", { className: "curator-header-message text-danger" }, lastError.error),
      message && React.createElement("p", { className: "curator-header-message", role: "status" }, message)
    );
  }

  // Score Review is an inspection surface (not a recommendation lane): it
  // pages through the bottom of the model's score distribution (least
  // appealing first) and reuses the slate card, so reasons, "Why this?", and
  // feedback work unchanged. Items mirror get_slate items; the backend op
  // get_score_review is the score-review half of issue #120. The surface
  // reviews the model's sentiment estimates (appeal, -1..1): least-appealing
  // scenes first by default, with a sort direction and an appeal threshold
  // control. URL state (sent_order / sent_max / page_sentiment) is the full
  // source of truth, per the URL-as-truth convention.
  function ScoreReviewPanel() {
    const sentimentSpec = React.useMemo(() => ({
      defaults: { order: "asc", maxAppeal: 0, page: 1 },
      fields: {
        order: urlStringField("sent_order", "asc", (value) => value === "asc" || value === "desc"),
        maxAppeal: urlNumberField("sent_max", 0),
      },
      page: urlPageSpec("page_sentiment"),
    }), []);
    const [urlState, updateUrl] = useUrlState(sentimentSpec);
    const { order, maxAppeal, page } = urlState;
    const threshold = Math.min(1, Math.max(-1, maxAppeal));
    const [data, setData] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState("");
    const [followUps, setFollowUps] = React.useState([]);
    const [wall, setWall] = React.useState(readWallMode);
    function toggleWall() {
      setWall((value) => {
        const next = !value;
        writeWallMode(next);
        return next;
      });
    }
    useCuratorActivity("score-review", loading, "Loading sentiment review…");
    React.useEffect(() => {
      let active = true;
      setLoading(true);
      setError("");
      operation({ operation: "get_score_review", page, count: 20, max_appeal: threshold, order }).then(
        (result) => active && (setData(result), setLoading(false)),
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => { active = false; };
    }, [page, order, threshold]);
    React.useEffect(() => {
      if (data?.page === page) {
        const last = Math.max(1, Math.ceil(data.total / data.page_size));
        if (page > last) updateUrl((s) => ({ ...s, page: last }), { replace: true });
      }
    }, [data, page]);
    const ids = [...new Set((data?.items || []).flatMap((item) => [String(item.scene_id), ...negativeNeighbors(item).map((neighbor) => String(neighbor.scene_id))]))];
    const scenesQuery = GQL.useFindScenesQuery({
      variables: { filter: { per_page: Math.max(1, ids.length) }, scene_ids: ids.map(Number) },
      skip: ids.length === 0,
    });
    const scenes = new Map((scenesQuery.data?.findScenes?.scenes || []).map((scene) => [String(scene.id), scene]));
    // The card renders its source badge from item.source_lane; the review
    // contract names the field "lane" (score_review), so normalize it here.
    const items = (data?.items || []).map((item) => ({ ...item, source_lane: item.lane || item.source_lane }));
    const resolved = !scenesQuery.loading && !scenesQuery.error && Boolean(scenesQuery.data);
    const visibleItems = resolved ? items.filter((item) => scenes.has(String(item.scene_id))) : items;
    const slate = data ? { lane: "score_review", model_id: data.model_version } : null;
    function showFollowUp(followUp) {
      setFollowUps((current) => [...current.filter((item) => item.scene_id !== followUp.scene_id), followUp]);
    }
    function remove(sceneId) {
      setData((current) => current && { ...current, items: current.items.filter((item) => item.scene_id !== sceneId) });
    }
    return React.createElement(
      "section",
      { className: "curator-score-review" },
      React.createElement(
        "div",
        { className: "curator-expand-toolbar" },
        React.createElement("label", { className: "curator-toolbar-select" }, React.createElement(FontAwesomeIcon, { icon: faSortAmountDown }), React.createElement("select", { value: order, onChange: (event) => updateUrl((s) => ({ ...s, order: event.target.value, page: 1 })), "aria-label": "Sort sentiment review" }, React.createElement("option", { value: "asc" }, "Least appealing first"), React.createElement("option", { value: "desc" }, "Most appealing first"))),
        React.createElement("label", { className: "curator-prune-aggressiveness", title: "Show scenes at or below this appeal threshold." }, React.createElement("span", null, `Appeal ≤ ${threshold.toFixed(2)}`), React.createElement("input", { type: "range", className: "curator-range", min: -1, max: 1, step: 0.05, value: threshold, onChange: (event) => updateUrl((s) => ({ ...s, maxAppeal: Number(event.target.value), page: 1 })), "aria-label": "Maximum appeal threshold" })),
        React.createElement(PreviewWallToggle, { wall, onToggle: toggleWall })
      ),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Loading sentiment review…")),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      followUps.map((followUp) => React.createElement(TagSentimentFollowUp, { key: followUp.scene_id, followUp, onDismiss: () => setFollowUps((current) => current.filter((item) => item.scene_id !== followUp.scene_id)) })),
      data && !loading && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No scenes below the current appeal threshold."),
      data && !loading && (wall
        ? React.createElement(RecommendationWall, { visibleItems, scenes, lane: "score_review" })
        : React.createElement("section", { className: "curator-grid", "aria-live": "polite" }, visibleItems.map((item) => React.createElement(RecommendationCard, { key: `${item.impression_id}:${item.scene_id}`, item, scene: scenes.get(String(item.scene_id)), evidenceScenes: scenes, slate, onRemove: remove, onThumbDown: showFollowUp })))
      ),
      data && React.createElement(Pager, { page, total: data.total, pageSize: data.page_size, hasMore: data.has_more, loading, onPage: (value) => updateUrl((s) => ({ ...s, page: value })), label: "Sentiment review pages" })
    );
  }

  // GH #151: settings a first version needs, grouped for the panel below.
  // Each entry's `key` is the camelCase name configurePlugin/stash-curator.yml
  // use; `configKey` (when present) is the snake_case name the same setting
  // is echoed back under from get_config's curator_config-backed `config`
  // object. Fields without a `configKey` aren't mirrored into curator_config
  // (see plugin/backend.py's _apply_plugin_settings) and are read back via
  // getPluginSettings() instead.
  const SETTINGS_GENDER_OPTIONS = [
    { value: "FEMALE", label: "Female" },
    { value: "MALE", label: "Male" },
    { value: "TRANSGENDER_FEMALE", label: "Trans female" },
    { value: "TRANSGENDER_MALE", label: "Trans male" },
    { value: "", label: "All genders" },
  ];
  const SETTINGS_FIELD_GROUPS = [
    {
      title: "Page settings",
      fields: [
        { key: "detailPageControls", type: "SELECT", default: "large", options: [{ value: "large", label: "Large" }, { value: "small", label: "Small" }, { value: "off", label: "Off" }], label: "Detail page controls", description: "Curator's expandable bar on scene and performer pages: Large (default), Small for compact icons and score, or Off to hide it." },
        { key: "hideCardRatings", type: "BOOLEAN", label: "Hide card ratings and confidence", description: "Hide Curator's badges on Stash scene and performer cards. Off by default." },
        { key: "pageSize", configKey: "page_size", type: "NUMBER", label: "Results per page", description: "Results per page, or per fetch when endless scrolling is enabled. Applies to recommendations, Similar, and Expand. Default 20." },
        { key: "recommendationEndlessScroll", configKey: "recommendation_endless_scroll", type: "BOOLEAN", label: "Virtual endless scrolling", description: "Load more results while scrolling in Recommendations and Find, in Cards, Thumbnails, and Wall. Cards retain expanded panels while the browser skips offscreen rendering. Off by default." },
      ],
    },
    {
      title: "Sync & model timing",
      fields: [
        { key: "rotationCooldownDays", configKey: "rotation_cooldown_days", type: "NUMBER", label: "Rotation cooldown (days)", description: "Days until a viewed but unpicked recommendation regains its full draw chance. Default 7; range 1-30." },
        { key: "syncPageSize", configKey: "sync_page_size", type: "NUMBER", label: "Sync page size", description: "Number of Stash records fetched per synchronization request. Default 250." },
        { key: "modelUpdateEventThreshold", configKey: "model_update_event_threshold", type: "NUMBER", label: "Actions before model update", description: "Rebuild after this many new playback or feedback actions. Default 5." },
        { key: "modelUpdateMaxWaitMinutes", configKey: "model_update_max_wait_minutes", type: "NUMBER", label: "Maximum model update delay (minutes)", description: "Rebuild pending preference changes after this delay. Default 30." },
        { key: "modelUpdateMinIntervalMinutes", configKey: "model_update_min_interval_minutes", type: "NUMBER", label: "Minimum model update interval (minutes)", description: "Minimum time between automatic preference-model rebuilds. Default 60." },
        { key: "autoTasksEnabled", configKey: "auto_tasks_enabled", type: "BOOLEAN", label: "Automatic background tasks", description: "Let the background worker apply pending model updates and sync recent plays on its own, without needing a browser tab open." },
      ],
    },
    {
      title: "Scheduling",
      fields: [
        { key: "scheduleExpandRefreshEnabled", configKey: "schedule_expand_refresh_enabled", type: "BOOLEAN", label: "Scheduled Expand refresh", description: "Refresh the Stash-box candidate cache so Expand and Performer Hunt stay current. Off by default; keeps the background worker resident while on." },
        { key: "scheduleExpandRefreshIntervalHours", configKey: "schedule_expand_refresh_interval_hours", type: "NUMBER", label: "Expand refresh interval (hours)", description: "How often the scheduled Expand refresh runs. Default 24." },
        { key: "scheduleExpandRefreshAtHour", configKey: "schedule_expand_refresh_at_hour", type: "NUMBER", optional: true, label: "Expand refresh hour of day", description: "Run at this hour (0-23, local time). Leave empty to run relative to when the schedule was enabled. Default 4 (04:00)." },
        { key: "scheduleSyncBuildEnabled", configKey: "schedule_sync_build_enabled", type: "BOOLEAN", label: "Scheduled sync and build", description: "Run a full sync and recommendation build on a schedule. Off by default." },
        { key: "scheduleSyncBuildIntervalHours", configKey: "schedule_sync_build_interval_hours", type: "NUMBER", label: "Sync and build interval (hours)", description: "How often the scheduled sync and build runs. Default 24." },
        { key: "scheduleSyncBuildAtHour", configKey: "schedule_sync_build_at_hour", type: "NUMBER", optional: true, label: "Sync and build hour of day", description: "Run at this hour (0-23, local time). Leave empty to run relative to enablement. Default 4 (04:00)." },
        { key: "scheduleBackupEnabled", configKey: "schedule_backup_enabled", type: "BOOLEAN", label: "Scheduled backup", description: "Create a sidecar backup on a schedule, just before a scheduled sync and build when both are due. Off by default." },
        { key: "scheduleBackupIntervalHours", configKey: "schedule_backup_interval_hours", type: "NUMBER", label: "Backup interval (hours)", description: "How often the scheduled backup runs. Default 24." },
        { key: "scheduleBackupAtHour", configKey: "schedule_backup_at_hour", type: "NUMBER", optional: true, label: "Backup hour of day", description: "Run at this hour (0-23, local time). Leave empty to run relative to enablement. Default 3 (03:00), just before a default 04:00 sync." },
      ],
    },
    {
      title: "Discovery",
      fields: [
        { key: "stashBoxEndpoint", type: "SELECT", default: "https://stashdb.org/graphql", label: "Stash-box endpoint", description: "Choose a server configured in Stash's Metadata Providers settings with a StashDB-compatible GraphQL API. Whisparr integration is available only with stashdb.org. ThePornDB's GraphQL support is limited, so Curator uses more limited REST queries instead: refreshes are slower and some thumbnails may be unavailable." },
        { key: "expandWildcard", configKey: "expand_wildcard", type: "BOOLEAN", label: "Expand popularity wildcard", description: "Include a small trending/popular sample outside preference-derived seeds." },
        { key: "expandGender", configKey: "expand_gender", type: "SELECT", options: SETTINGS_GENDER_OPTIONS, label: "External performer gender", description: "Default Stash-box gender filter for Expand and Similar. Default Female; choose All genders for no filter." },
        { key: "expandHorizonDays", configKey: "expand_horizon_days", type: "NUMBER", label: "Expand recent-release horizon (days)", description: "Recent-release window used by Expand. Default 90." },
        { key: "expandCandidateLimit", configKey: "expand_candidate_limit", type: "NUMBER", label: "Expand candidate limit", description: "Maximum Stash-box scenes fetched per Expand refresh, split across seed sources. Default 1000; raise to reduce fetch truncation at the cost of a slower refresh." },
        { key: "expandSimilarSeedTopK", configKey: "expand_similar_seed_top_k", type: "NUMBER", label: "Expand similar-performer seed top-K", description: "Chase look-alikes for the K strongest favourite performers into the Expand seed set. 0 disables. Default 20." },
        { key: "expandSimilarSeedPerFavorite", configKey: "expand_similar_seed_per_favorite", type: "NUMBER", label: "Expand similar-performer seeds per favourite", description: "How many closest look-alikes per favourite are added as Expand seeds. 0 disables. Default 5." },
      ],
    },
    {
      title: "Prune",
      fields: [
        { key: "pruneTagName", configKey: "prune_tag_name", type: "STRING", label: "Prune tag", description: "Tag applied by the Prune page. Default [Prune]." },
      ],
    },
    {
      title: "Tag analysis",
      fields: [
        { key: "ignoredTags", configKey: "ignored_tags", type: "STRING", label: "Ignored tags", description: "Comma-separated names of tags excluded from tag analysis. Auto-generated or metadata tags like [Timestamp: Synced] do not describe the scene; exact-name match only. Empty by default." },
      ],
    },
    {
      title: "Whisparr integration",
      fields: [
        { key: "whisparrUrl", type: "STRING", label: "Whisparr v3 URL", description: "Optional Whisparr base URL used by Expand scene actions." },
        { key: "whisparrApiKey", type: "PASSWORD", label: "Whisparr API key", description: "Optional Whisparr API key. It is used only by the plugin backend." },
        { key: "whisparrRootFolder", type: "STRING", label: "Whisparr root folder override", description: "Optional. Leave empty to use Whisparr's first configured root folder." },
        { key: "whisparrQualityProfileId", type: "NUMBER", optional: true, label: "Whisparr quality profile ID override", description: "Optional. Leave empty to use Whisparr's fallback (or first) quality profile." },
        { key: "whisparrSearchImmediately", type: "BOOLEAN", default: true, label: "Search Whisparr immediately", description: "Start a release search after adding a scene. Enabled by default." },
      ],
    },
    {
      title: "Storage",
      fields: [
        { key: "databasePath", type: "STRING", label: "Sidecar database path", description: "Absolute database filename on writable, persistent local storage. Leave empty to use the plugin's data directory. Changing this path does not move existing data." },
        { key: "backupPath", type: "STRING", label: "Backup directory", description: "Leave empty to store Curator backups beside the sidecar database." },
      ],
    },
    {
      title: "Development",
      fields: [
        { key: "profilingEnabled", type: "BOOLEAN", label: "Enable profiling", description: "Record recent Curator operation timings for the Profiling page." },
        { key: "pprofEnabled", type: "BOOLEAN", label: "Capture CPU profiles", description: "Write a Go CPU and heap profile per operation into the sidecar's profiles directory, browsable and downloadable from the Profiling page. Analyze with go tool pprof. Off by default; keep off unless investigating performance." },
      ],
    },
  ];

  function SettingsField({ field, value, saving, error, onSave }) {
    const [draft, setDraft] = React.useState(value ?? "");
    React.useEffect(() => { setDraft(value ?? ""); }, [value]);
    const inputId = `curator-setting-${field.key}`;
    function commitText() {
      const trimmed = String(draft).trim();
      const current = String(value ?? "");
      if (trimmed === current) return;
      if (field.type === "NUMBER") {
        if (trimmed === "") {
          if (field.optional) onSave("");
          else setDraft(current);
          return;
        }
        const num = Number(trimmed);
        if (Number.isNaN(num)) { setDraft(current); return; }
        onSave(num);
        return;
      }
      onSave(trimmed);
    }
    let control;
    if (field.type === "BOOLEAN") {
      control = React.createElement(
        "button",
        { id: inputId, type: "button", role: "switch", "aria-checked": Boolean(value), className: `curator-switch${value ? " curator-switch-on" : ""}`, disabled: saving, onClick: () => onSave(!value), title: value ? "On" : "Off" },
        React.createElement("span", { className: "curator-switch-thumb", "aria-hidden": "true" }),
        React.createElement("span", { className: "curator-switch-text", "aria-hidden": "true" }, value ? "On" : "Off")
      );
    } else if (field.type === "SELECT") {
      control = React.createElement(
        "select",
        { id: inputId, className: "form-control form-control-sm curator-settings-control", value: value ?? "", disabled: saving, onChange: (event) => onSave(event.target.value) },
        field.options.map((option) => React.createElement("option", { key: option.value, value: option.value, disabled: option.disabled }, option.label))
      );
    } else {
      control = React.createElement("input", {
        id: inputId,
        type: field.type === "PASSWORD" ? "password" : field.type === "NUMBER" ? "number" : "text",
        className: "form-control form-control-sm curator-settings-control",
        value: draft,
        disabled: saving,
        onChange: (event) => setDraft(event.target.value),
        onBlur: commitText,
        onKeyDown: (event) => { if (event.key === "Enter") event.target.blur(); },
      });
    }
    return React.createElement(
      "div",
      { className: "curator-record-row curator-settings-field" },
      React.createElement(
        "div",
        { className: "curator-record-main" },
        React.createElement("label", { className: "curator-record-title", htmlFor: inputId }, field.label),
        React.createElement("p", { className: "curator-record-meta" }, field.description),
        error && React.createElement("p", { className: "curator-record-meta curator-settings-field-error" }, error)
      ),
      control,
      saving && React.createElement("span", { className: "curator-settings-saving" }, "Saving…")
    );
  }

  function RouletteAnimationSetting({ compact = false }) {
    const [enabled, change] = useRouletteAnimation();
    return React.createElement(SettingsField, {
      field: { key: compact ? "rouletteAnimationPopup" : "rouletteAnimation", type: "BOOLEAN", label: "Animate roulette",
        description: compact ? "Applies to the next pick." : "Show the wheel and its sound effects. Off picks immediately with a brief fade. Saved in this browser; applies to the next pick." },
      value: enabled, onSave: change,
    });
  }
  function SettingsPanel({ diversityEnabled, diversitySaving, onToggleDiversity, onMoodsSaved, onConfigSaved }) {
    const [config, setConfig] = React.useState(null);
    const [raw, setRaw] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState("");
    const [savingKeys, setSavingKeys] = React.useState(() => new Set());
    const [fieldErrors, setFieldErrors] = React.useState({});
    const [editingMoodID, setEditingMoodID] = React.useState("");
    const [newMoodName, setNewMoodName] = React.useState("");
    const [togetherSaving, setTogetherSaving] = React.useState(false);
    const [stashBoxes, setStashBoxes] = React.useState([]);
    const togetherSaveInFlight = React.useRef(false);
    useCuratorActivity("settings", loading, "Loading settings…");
    React.useEffect(() => {
      let cancelled = false;
      Promise.all([operation({ operation: "get_config" }), getPluginSettings(), getStashBoxEndpoints()])
        .then(([configData, settingsData, boxes]) => {
          if (cancelled) return;
          setConfig(configData.config);
          setRaw(settingsData);
          setStashBoxes(boxes);
        })
        .catch((failure) => { if (!cancelled) setError(failure.message); })
        .finally(() => { if (!cancelled) setLoading(false); });
      return () => { cancelled = true; };
    }, []);
    async function saveMoods(next) {
      if (togetherSaveInFlight.current) return false;
      togetherSaveInFlight.current = true;
      setTogetherSaving(true);
      setError("");
      try {
        const data = await operation({ operation: "update_config", values: { moods: next } });
        clearSlateCache();
        setConfig(data.config);
        onMoodsSaved?.(data.config.moods);
        return true;
      } catch (failure) {
        setError(failure.message);
        return false;
      } finally {
        togetherSaveInFlight.current = false;
        setTogetherSaving(false);
      }
    }
    async function saveField(field, value) {
      setSavingKeys((current) => new Set(current).add(field.key));
      setFieldErrors((current) => ({ ...current, [field.key]: "" }));
      try {
        // Stash's configurePlugin REPLACES the stored plugins.settings map
        // (config.go's set() deletes before writing), so a single-key payload
        // would wipe every other setting. Send the full map we already hold.
        await configurePlugin({ ...raw, [field.key]: value });
        if (field.key === "stashBoxEndpoint") clearEndlessCache();
        if (field.configKey) {
          const data = await operation({ operation: "get_config" });
          cachedConfigUpdatedAtMs = data.updated_at_ms;
          setConfig(data.config);
          if (field.key === "recommendationEndlessScroll") onConfigSaved?.(data.config);
          setRaw(await getPluginSettings());
        } else {
          setRaw(await getPluginSettings());
        }
      } catch (failure) {
        setFieldErrors((current) => ({ ...current, [field.key]: failure.message }));
      } finally {
        setSavingKeys((current) => { const next = new Set(current); next.delete(field.key); return next; });
      }
    }
    if (loading) return React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Loading settings…"));
    if (!config || !raw) return React.createElement("div", { className: "alert alert-danger" }, error || "Unable to load settings.");
    const moods = config.moods || [];
    const editingMood = moods.find((mood) => mood.id === editingMoodID) || moods[0];
    async function addMood() {
      const mood = { id: uuid(), name: newMoodName.trim(), excluded_tags: [] };
      if (await saveMoods([...moods, mood])) { setEditingMoodID(mood.id); setNewMoodName(""); }
    }
    return React.createElement(
      "section",
      { className: "curator-settings-panel" },
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      React.createElement(
        "div",
        { className: "curator-settings-group" },
        React.createElement("h3", null, "Recommendations"),
        onToggleDiversity && diversityEnabled !== null && React.createElement(
          "div",
          { className: "curator-record-row curator-settings-field" },
          React.createElement(
            "div",
            { className: "curator-record-main" },
            React.createElement("span", { className: "curator-record-title" }, "Recommendation variety"),
            React.createElement("p", { className: "curator-record-meta" }, "Vary performers, studios, and similar content instead of pure score-first ordering.")
          ),
          React.createElement(
            Button,
            {
              size: "sm",
              variant: diversityEnabled ? "primary" : "secondary",
              disabled: diversitySaving,
              "aria-pressed": diversityEnabled,
              onClick: onToggleDiversity,
            },
            React.createElement(FontAwesomeIcon, { icon: faBalanceScale }),
            diversityEnabled ? " Balanced" : " Score-first"
          )
        ),
        React.createElement("div", { className: "curator-settings-together" },
          React.createElement("span", { className: "curator-record-title" }, "Moods"),
          React.createElement("p", { className: "curator-record-meta" }, "Each mood hides its excluded tags and their children. Changes save automatically."),
          React.createElement("fieldset", { className: "curator-together-picker", disabled: togetherSaving, "aria-busy": togetherSaving },
            React.createElement("div", { className: "curator-mood-create" },
              React.createElement("input", { className: "form-control form-control-sm", "aria-label": "New mood name", placeholder: "New mood name…", maxLength: 80, value: newMoodName, onChange: (event) => setNewMoodName(event.target.value), onKeyDown: (event) => { if (event.key === "Enter" && newMoodName.trim()) { event.preventDefault(); addMood(); } } }),
              React.createElement(Button, { size: "sm", disabled: !newMoodName.trim() || moods.length >= 50, onClick: addMood }, "Add mood")
            ),
            editingMood && React.createElement(React.Fragment, null,
              React.createElement("select", { className: "form-control form-control-sm", "aria-label": "Mood to edit", value: editingMood.id, onChange: (event) => setEditingMoodID(event.target.value) }, moods.map((mood) => React.createElement("option", { key: mood.id, value: mood.id }, mood.name))),
              React.createElement("div", { className: "curator-mood-create" },
                React.createElement("input", { key: editingMood.id + editingMood.name, className: "form-control form-control-sm", "aria-label": "Mood name", maxLength: 80, defaultValue: editingMood.name, onBlur: async (event) => { const input = event.target; const name = input.value.trim(); if (name === editingMood.name) return; if (!name || !await saveMoods(moods.map((mood) => mood.id === editingMood.id ? { ...mood, name } : mood))) input.value = editingMood.name; }, onKeyDown: (event) => { if (event.key === "Enter") event.target.blur(); } }),
                React.createElement(Button, { size: "sm", variant: "outline-danger", onClick: () => saveMoods(moods.filter((mood) => mood.id !== editingMood.id)) }, "Delete mood")
              ),
              React.createElement(FilterTokens, { kind: "tag", label: "Excluded tags", values: editingMood.excluded_tags, onChange: (tags) => saveMoods(moods.map((mood) => mood.id === editingMood.id ? { ...mood, excluded_tags: tags.map(({ id, name }) => ({ id: String(id), name })) } : mood)) })
            )
          ),
          togetherSaving && React.createElement("span", { className: "curator-settings-saving", role: "status" }, "Saving…")
        )
      ),
      React.createElement("div", { className: "curator-settings-group" },
        React.createElement("h3", null, "Playback"), React.createElement(RouletteAnimationSetting)),
      SETTINGS_FIELD_GROUPS.map((group) => React.createElement(
        "div",
        { key: group.title, className: "curator-settings-group" },
        React.createElement("h3", null, group.title),
        group.fields.map((field) => {
          const rawValue = raw ? raw[field.key] : undefined;
          const value = field.configKey
            ? config[field.configKey]
            : (rawValue === undefined || rawValue === null || rawValue === "") && field.default !== undefined ? field.default : rawValue;
          if (field.key === "stashBoxEndpoint") {
            const options = stashBoxes.map((box) => ({ value: box.endpoint, label: (box.name || box.endpoint.replace(/^https?:\/\//i, "").split("/")[0]) + (/^https?:\/\/theporndb\.net(?:[:/]|$)/i.test(box.endpoint) ? " (limited support)" : "") }));
            if (!options.some((option) => option.value === value)) {
              options.unshift({ value, label: stashBoxes.length ? "Selected endpoint (not configured)" : "No endpoints configured in Stash", disabled: true });
            }
            field = { ...field, options };
          }
          return React.createElement(SettingsField, {
            key: field.key,
            field,
            value,
            saving: savingKeys.has(field.key),
            error: fieldErrors[field.key],
            onSave: (next) => saveField(field, next),
          });
        })
      ))
    );
  }

  // Manage shell (GH #150 Package 3): a two-pane list/detail view that hosts
  // every maintenance-flagged NAV_ITEMS entry plus Profiling. Each panel is
  // mounted unmodified — this is pure relocation, not a rebuild.
  const MANAGE_BODIES = {
    feedback: () => React.createElement(FeedbackHistoryPanel),
    sentiment: () => React.createElement(ScoreReviewPanel),
    history: () => React.createElement(RecommendationHistoryPanel),
    backups: () => React.createElement(BackupPanel),
    diagnostics: () => React.createElement(DiagnosticsPanel),
    prune: () => React.createElement(PrunePanel),
    profiling: () => React.createElement(ProfilingPanel),
    settings: (extra) => React.createElement(SettingsPanel, extra),
    tasks: () => React.createElement(TasksPanel),
  };

  // The side-menu shell used by Manage: a section list on the left, the
  // active section's body on the right. (Curate uses the lane-card switcher
  // instead — see CuratePanel.)
  function SectionShell({ items, active, onSelect, navLabel, children }) {
    return React.createElement(
      "div",
      { className: "curator-manage-shell" },
      React.createElement(
        "nav",
        { className: "curator-manage-list", "aria-label": navLabel },
        items.map((item) => React.createElement(
          "button",
          {
            key: item.value,
            type: "button",
            className: "curator-manage-item",
            "aria-current": item.value === active.value ? "page" : undefined,
            onClick: () => onSelect(item.value),
            title: item.description,
          },
          React.createElement("span", { className: "curator-manage-item-icon" }, React.createElement(FontAwesomeIcon, { icon: item.icon })),
          React.createElement(
            "span",
            { className: "curator-manage-item-copy" },
            React.createElement("span", { className: "curator-manage-item-title" }, item.label),
            React.createElement("span", { className: "curator-manage-item-desc" }, item.description)
          )
        ))
      ),
      React.createElement(
        "section",
        { className: "curator-manage-detail", "aria-live": "polite" },
        React.createElement(
          "div",
          { className: "curator-manage-detail-head" },
          React.createElement("h2", null, active.label),
          React.createElement("p", null, active.description)
        ),
        children
      )
    );
  }

  function ManagePanel({ section, onSelectSection, diversityEnabled, diversitySaving, onToggleDiversity, onMoodsSaved, onConfigSaved }) {
    const items = MAINTENANCE_ITEMS;
    const active = items.find((item) => item.value === section) || items[0];
    const body = MANAGE_BODIES[active.value];
    return React.createElement(
      SectionShell,
      { items, active, onSelect: onSelectSection, navLabel: "Manage sections" },
      body && body({ diversityEnabled, diversitySaving, onToggleDiversity, onMoodsSaved, onConfigSaved })
    );
  }

  function createRouletteSession(slate, items, filters, scenes) {
    return {
      lane: slate.lane, request: createLanePlaylist(slate, items, filters).request,
      pool: items.map((item, index) => ({ item, origin: playlistOrigins(slate, [item])[0], scene: scenes.get(String(item.scene_id)), rank: index })),
      seen: new Set(), excluded: new Set(items.map((item) => String(item.scene_id))),
      slots: [], history: [], index: -1, rotation: 0, phase: "idle", token: 0, done: false,
    };
  }
  async function fillRoulette(session, count) {
    while (!session.done && session.pool.filter((entry) => !session.seen.has(entry.origin.scene_id)).length < count) {
      const slate = await operation({ ...session.request, operation: "get_slate", count,
        exclude_scene_ids: [...new Set([...session.request.exclude_scene_ids.map(String), ...session.excluded])],
        context: { route: location.pathname, roulette: true } });
      if (session.closed) return;
      const items = slate.items.filter((item) => !session.excluded.has(String(item.scene_id)));
      if (!items.length) { session.done = true; break; }
      const response = await fetch("/graphql", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: `query RouletteScenes(${items.map((_, i) => `$s${i}: ID!`).join(", ")}) { ${items.map((_, i) => `s${i}: findScene(id: $s${i}) { id title paths { screenshot } files { duration } }`).join(" ")} }`,
          variables: Object.fromEntries(items.map((item, i) => [`s${i}`, String(item.scene_id)])),
        }),
      });
      const result = await response.json();
      if (!response.ok || result.errors?.length || !result.data || Object.keys(result.data).length !== items.length) throw new Error("Could not load roulette scenes. Retry to continue.");
      if (session.closed) return;
      const origins = playlistOrigins(slate, items);
      items.forEach((item, i) => {
        session.excluded.add(String(item.scene_id));
        const scene = result.data[`s${i}`];
        if (scene?.files.length) session.pool.push({ item, origin: origins[i], scene, rank: session.pool.length });
      });
    }
    if (session.done && session.pool.length && session.pool.every((entry) => session.seen.has(entry.origin.scene_id))) {
      session.pool = []; session.seen.clear(); session.excluded.clear(); session.done = false;
      await fillRoulette(session, count);
    }
  }
  function rouletteShuffle(items) {
    const result = [...items];
    for (let i = result.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
  }
  function rouletteSlots(session, limit) {
    const available = session.pool.filter((entry) => !session.seen.has(entry.origin.scene_id));
    const candidates = new Map(session.pool.map((entry) => [entry.origin.scene_id, entry]));
    if (!session.slots.length) return rouletteShuffle(available).slice(0, limit);
    const present = new Set(session.slots.map((entry) => entry.origin.scene_id));
    const incoming = rouletteShuffle(available.filter((entry) => !present.has(entry.origin.scene_id)));
    const current = session.history[session.index]?.origin.scene_id;
    const slots = session.slots.map((entry) => {
      const id = entry.origin.scene_id;
      const candidate = candidates.get(id);
      if (candidate && entry.frame) candidate.frame ||= entry.frame;
      return id !== current && (session.seen.has(id) || !candidate) && incoming.length ? incoming.pop() : candidate || entry;
    });
    while (slots.length < limit && incoming.length) slots.push(incoming.pop());
    return slots;
  }
  function rouletteWinner(session, slots) {
    const candidates = new Set(session.pool.map((entry) => entry.origin.scene_id));
    let eligible = slots.filter((entry) => candidates.has(entry.origin.scene_id) && !session.seen.has(entry.origin.scene_id));
    const current = session.history[session.index]?.origin.scene_id;
    if (eligible.some((entry) => entry.origin.scene_id !== current)) eligible = eligible.filter((entry) => entry.origin.scene_id !== current);
    const weights = eligible.map((entry) => 1 - .3 * entry.rank / session.pool.length);
    let draw = Math.random() * weights.reduce((a, b) => a + b, 0);
    return eligible.find((_, i) => (draw -= weights[i]) <= 0) || eligible[eligible.length - 1];
  }
  function rouletteShape(root, session) {
    const stage = root.getBoundingClientRect();
    const slot = session.history[session.index].slot;
    const image = root.querySelectorAll(".curator-roulette-wheel-wrap image")[slot];
    // Compose the rotations before measuring, rather than rotating an intermediate bounding box.
    const box = image.getBBox(), matrix = image.getScreenCTM();
    const width = Math.abs(matrix.a) * box.width + Math.abs(matrix.c) * box.height;
    const height = Math.abs(matrix.b) * box.width + Math.abs(matrix.d) * box.height;
    const x = box.x + box.width / 2, y = box.y + box.height / 2;
    const left = matrix.a * x + matrix.c * y + matrix.e - width / 2;
    const top = matrix.b * x + matrix.d * y + matrix.f - height / 2;
    const rectangle = "polygon(0% 0%,100% 0%,100% 100%,0% 100%)";
    return { left: `${left - stage.left}px`, top: `${top - stage.top}px`,
      width: `${width}px`, height: `${height}px`, clipPath: rectangle, rectangle };
  }
  function createRouletteSound(audio) {
    // CC0 card shuffle by Brian MacIntosh; source/edit details: docs/assets/roulette-card-shuffle.md.
    const pcm = Uint8Array.from(atob("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DQDq/xgADADt/xoAJQACANr/6/8oAC4AAwD+/w8AAQAEAPf/FgAoAAgA+//5/xMADQD2//z/BwAXAPz//v8PAAMAKAAMAPf////3/yQALgAaAAgA6v/e/xcALAAPABEADAD6/w8ABAD1/yoAJQAAAPz/BAAQAAsA//8GAA8ADwAPAAMAHQD//+X/FwAaABwAGwACABYAGwD1/xEAKwARABMACAD8/wUABwAbACIAEgAXAPj/AAAcABcAJQAIAPb/DwAgAB8ABQAHABEAFQAjABwAEgD+//j/CAAWABYAEQAEABsAGAD5/xEAIwAYABsADgAAAAoADwABAAsAFAAMABkAHAAUABAAFQARAAkAEwAXAAMABwAVABUAGQAIAP7/LAAcAPT/DwAbABIA/f8BAA4AIAAYAAQAKAAQAAgADQAMACQAEwD8/wwAEgALABUAGAAYAAwADwAKABsAGQD9/wgACwAVAAwADwAWABMAHQAQAAYAHAATAAgADwAMAAsABQACACIAIAAJAAkADQAWABMADwD+/wsALAAJAPb/EQAPABUAFAAUABYADwADAP//FwARAAcACAARABoADwACABIAGgAQAAoABgAQABEAEAACAP7/EAAZABUAFgADAAUADQAKAA8ADwAIAP//DQAPAA8AFwAZAAoADgARAAwABwAGABIACAAIAAcADgADAAEAEgASAAYABwAAABIAHgD8/wgADwANAA4AFAALAP//CQAHAA0AGAAHAAMAEAAGAAMAAgD6/x0AGwD3/wcAAQALABEADAALAAQABAACAAoAHQAXAPn/AwALAP7//f8MAAsACAAOAP//AgANAAgAEAD7/w0AFQALAA4AAgADAP//AwD+/wwADwACAA4A/f8DAAQABwABAP7/BwAHAAwAAwAJAAUABQD+/wQADgAHAA0A+v/v/wgACQAIAAcABQABAPP/8v8PAA4AAgD5/wEACADy/wwADgAKAP3/9f8JAAYAAQD8//X/BgACAPv/EAAPAP3/AAD+/wcA/f/4//X/AQAJAPT//v8NAAcADAD2//j/AgD4/wIAAAADAAgA///t/wYACgD1/wUACwAAAP3/9f8JAPz/8/8BAP3/BQANAPn/+f8EAPb/AAD/////AgDz//n/BQADAAQA/P8IAAAA7v/1////DADz//T/BAD1//X/AQD9/wEA+v/2/wMABAACAPn/9f/7//b//f8EAPv/8P/+//3/9////wYACAD6//P/9f/+/wQA/P/5//r/BwD5//L/AAD3//j/+v8EAAIA9P/5//D/+/8HAPj//v8EAAUA+P/0//H/AwACAPb////5//z////w//n/AwD1//v/AQAGAPX/7/8DAAAA/v8DAP7/+v/8//j//f//////8//8////+v/2//H/CwAEAPn/9v/1//f/+//2//X/CAD+//j//v/1//z/9//4////AgABAPv/9v/2//r//f///wIA+f/3//j/+f///wAA/v/5//z///8DAAAA9f/1//r/BQAMAPP/8P///wQA9v/9/wUA/P/8//P/+P8BAPv/+//4////AQD9//j/+/8DAPr/+f/+/wEA///8/wQAAwD///z//P8BAP//+//8//f///8FAAEA/f/2/wEA///+///////9//z///8CAP3//f/9//r/AQD9/wAA/v/7//3//v/+//z//f8CAAQA//8AAP7//P8AAP7/AQD9//v/BwABAAEA///+////AAADAAAAAQD1//j/AgACAAQA/////wAA+v/+/wIA//8CAP7//f8EAAEAAgD6//3/AgD+/wUAAAAAAP3/+f8EAAIAAAACAAUAAQD8//3/AQADAAAAAAABAAEAAQAHAP///v8DAP7/AgAAAAAABgD7//7/BQACAAIAAgABAAIA///9//7/BQADAPv///8AAAMAAQACAAUA/v8BAAMAAgADAPz///8HAAYAAQAAAAEA//8BAAQAAgACAAIAAQAAAP7/AAACAAEAAAAAAAMABwD///3/AwACAAUA/////wgABAD+/wAAAAD//wMABAACAP////8BAAQAAQAAAAIAAgAFAAEAAQADAAIA//8BAAQAAwABAAAAAAADAAQAAAAGAAQAAAABAAAAAwAEAAIAAQAAAAAAAwACAAIAAwADAAEAAAABAAUAAgAAAAIAAgAAAAMAAgADAAUA//8CAAMAAAABAAIAAgADAAAAAAADAAMAAgABAAMAAQAAAAAAAQAEAAIAAAACAAEAAAABAAQAAQABAAAAAgAEAAEAAQABAAAAAwAEAAIAAQAAAAIAAAADAAIAAQAAAAEAAwABAAIAAQACAAEAAQABAAAAAgABAAAAAAACAAIAAQACAAIAAQAAAAIAAgADAAEA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GgA3AC4A///7/+z/0/8cABwAGgA2ADcARAABAAgA+P+9//f//f8VABgA9v8SAPP/zv/r//z/AgDx//7/IQDq/9P/4P/K/9v/1P/p/xYADgAfADAADgDz/8L/u//N/+P/EAAjAAQACQAgABQAJAA9ABkA5/+3/9T/7f/u/zwAYwBRAC8A+v/g/83/y/8EAB0AKAAmAB8AKwAJAAIA8//W/9j/zf/P//j/JQA6AEgANQD8/83/t/+v/8P/5f8HACQAFgAsABwACgAQANv/4f/X/9L/8f/n//f/FQA5AEIANwAdAOb/wP+//8z/9/8jADwAOgAlAAAA4//k//D/+f8MADEAGAD9//f/1v/7/xkAFQAXAO//8//v/+//BwAaACQAEwD7/+f/yP/L//z/CwAQAAMAGgARAPv/BwDw//T/5v/u/wMA7f8EABQAAgALAAQAAwAGAP3/+//w//D/+f8KABEABgAHAAYAAQADAA0ADgD3/wMA+P/x/wMA/v8ZABcA/P8CAPT/+v/8//7/DQD6//n/BwD0/wIAAgAGAAwA7//7/wAA9P/5/wEABwD8/wIABQABAAMA+//9/+j/7P/8//3/GwAUAAoABQDv//X/9f8CAAQA/P8AAPv/AwADABQAFwADAAEAAgD8/+r/+/8KAPz/AgAHAAsAAwADAAcACQAAAPD/9P/x//z/CgALAAsA/f/3//r/9/8EAAcAAAD///H/+f/6//f/BAAKAAsA+f/6////+f8EAA4ABgDy//D/AAACAAAACwAFAPr//v8AAAMACQD//wgAAADv/wIAAAD9/wQABAARAAoA+v8IAPf/8f8DAP3/CQAMAAAABgD4//D/AAABAAsABQD9//7/8v/4/wIACwAFAAEAAgD4//f////2/wAAAAACAAwA//8GAAUA8v/x//z//P8CAAcACwAIAPz/AAD///v/BQAGAAEA///1//r/AgABAAkABQAAAAAAAQAAAAEA/P8BAPz//P8DAAAABQD+////BAAAAAIAAwADAAEA9/////n/9v8CAAcACQAGAAEAAQD6//j////+////AgD+/wIAAQACAAMAAAD///7//f/6////AQAAAAcABAACAAAA+v/+//z/AgAEAAMAAgD///3///8BAAAAAAABAP7//v////z/BQAFAAUABgD9//3/+v/5////AQAFAAUABgADAP///f/7//3/AAACAAQAAQAAAAAA/f8AAAEAAAADAP7/AAD+//v/AgADAAEAAQAAAAAA/v/8/wAAAQAAAAEAAgAAAAEA/////////v8AAAAAAgABAAAAAAABAAAAAAAAAAAA//8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAA//8BAAAAAQAAAP//AAD//wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="), (char) => char.charCodeAt(0));
    function recording(bytes) {
      const buffer = audio.createBuffer(1, bytes.length / 2, 22050), samples = buffer.getChannelData(0);
      const view = new DataView(bytes.buffer);
      for (let i = 0; i < samples.length; ++i) samples[i] = view.getInt16(i * 2, true) / 32768;
      return buffer;
    }
    const shuffle = recording(pcm);
    // CC0 rising texture by AudioPapkin; edits: docs/assets/roulette-cinematic-sound.md.
    // CC0 heavy foley slam with chip accent; source/mix details: docs/assets/roulette-casino-slam.md.
    const impact = recording(Uint8Array.from(atob("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//AQD///3/jf/F/hr+g/3M/Nn71vr3+YH56fi396H2m/XM9Bj0C/Pn8pjysPGS8f7wiO8e7vPs6uws7KLq8+vD743xr++x7U7tq+0567nxhwHTCw8SXxHeE1sVlxbBGjkbkBzmHfIeghz9GU8ajBouHTUdWRwVHoQfnh56G1kY/hPWD1kRuhVxFHYOLg1/EPYU1hfZGDEZrRh6FP0OYA3GCwULOA7fEekSZhP6EycTPQ5lCc0FYAONBpoE7f3C9PfpRuSF4ALkAeSX4R3doN4c5L3fJNo52F7ZBeL/4KHZwNV22njmMOJB2XDXF9VN0xrVu9ZZ4BPwgP9bBQ383PV682j02PKm6R/i/OCs677+Ug8jDs0K7grBBi4H4gRYAFYBeAA8AKACNAg/DWgQihHoEUsNpwT1Aa8AP/+u/8YIXw0ZFCIbdhlTICIgAhmqEisSqhrKGSkPeA4JGbEcuBnPHbkq3DPcL4oljR+FHlgd8hV+DvIQ0iFnMWA4UDutPA49uTxdPHQ8zzUhJ0cciRZ+E88QXxDhEOYO4gyuC4EI2A15G4gedh8YIKcclBu+GI4adRpXHEQjTyRZIHkc1ha7FyEd1Bw4Gt8WExj9Gb8VZhLCEYkSwA6NCSMFF/l87ZfmuuO94avg890V31ffjeRG51XgItwU2nfcMdne05jThdO90VfRnNGV0JTQD9Ks0vXS1NNe1czVw9Sn1frW8tei2IzZK9t82+LacNyF3rLfyeGN5EvmHujw6hvuGvKx9d/3Jfu4/KYC3wxhDIoGEQRo/tz5iQ+IMf5CkUHiQ8ZKykw2T5pMq0q9R9tHqEoRRtk6JirTIWoXsRNKEywKQAPM80YBERQkEKwUPB8rJaMc9Bd9Ij8q8S2aKIogwSMhKvws+St9KfwmKCUCI38aRRn5FyoUPRc8Fp0VbRkeH6Yc2xe8F/cX/RYBGEIX3hWCGfUalxZ5DzoM/wF/7OPh6OER5PDkf+F74j3gKuDo2n3XeuTZ2gbM39ug3BDRddlBzAbGZMIRxrLhu9gr0IjGOLwtxAfAOc6u3ALmBNr0w+jIENQAzVfRK9Gc0MjfttQr123exOdf+UX6oev29XT1Yu8a9LHquPPY5JrVBO7Q+GP5du1f+YcI4/qaBzQCmPg4C3YKR/i69AoH0hL4JkElaBs0JasoAhnBA7MDYfi49l7v2+h88Cf2zg4LGLsVVQfI/Y/1BfAMAQoVowODAk/7T/YCEQgcLwPO3bXoHOW85Xfq6OOo48PV8tN83qXu9wapBkPuxe1N9Ib98hBtAor4n/NX+UwZjiAlD0QCzu143n7vKQJgA6kTJRwoHzcfPAnkAvf3tf/dHCAdcAM67v33kBUXG3MT7xGCDD/4sedr5YXodeHI3bvXK9KVz/3JQcVwxH3JI87oz+TPlczPxyTJkdIl2JnUwMwtycrJscqYyxbNWs952ATjkeXZ5Pngy+RZ6tvwGO7u5iPrNO8I/UIK3gLN7Fnl9ugK7xLwtuxB52Dm6+my6EXtKOzY6JfsFvFZ8531DPSA7BnqAuu37GrsTfDA97vz1/Pm8wbx0fHE8bb59P80/0ERYCksPfZJH0yLRdpFjFNfW/ZQulPTUYBIWlD/RlNHllajXk5YQ04sUMtN6kfZQepIrFILU+hRQU/UTP9LAE3/StVA0jXONRksrifcLkc2CzghO8oy+iZ0L38zgja2J24TjRC2FwISDvWN3W/b8+N174nvI+X/3gflQ/B38zzy7vAB8YfwF/DZ7qHtqe0l71rvHO/M7nXuce6J71vwp/AY8eTvavDV8H/w6/AK8irx2vbwBFwKegziCvoGGQav/3j11/EJ8ZHvePHB8yD2gPiN/FD9V/km91/15/UB9j31XvaS9uH2of1+BlsNgxE6FDEZ9Rx8HbcdCR5sIYUo0ysgMTIxTyw5KZMnhyQCJwErzyqLLnMwSzAlMPEtjyceI+gfkx1sFXAN7ATu9FLxHuzq8bD27/Lw77jr3+rm6anja+Bs5iDkjN7W25DYTdfN10LS4cs4zqHantZB1i3lIujL5uDnmvHh+8T+YAFRCqUWqxl5GlUavgvz/A34FwQtE0kWyhUFFFcStxOAFm0XkhSEEWoQDA8vETsTiBERC08AVPdn7gvrCOtn6nfuF/OZ7oDt3+qr55fnreQq19PLEM5e1pLdw9/H4cjni+vH6/Treetd68Xrdeya7Pzssu0T7rntcuth4+DVjtAr3kfoneKU2yHdl9+n38zdYd5x4Mviu+J529zaWeHc5X3qqO7L84j0UPEr7IPuIfmQ9N/q8+N05Snsb+QH00HLN8473UHoeO3o+7v/8AG7BsQEEQLSAEQAMgE+AgYCUQPHBLIHVgkvCcEMgRHHEZkO4AvUCuMKCgpZCQQMFA3UC2wLmgpnCdEH1AcBCEgH9wZOBnUG/Qb8BkEHiAfiB4MIegnaCckKTg4VDEQHngShAYz8lPiI8j/qK+c25eTlX92D3XXkvOYX7CfoZelY7ovn3t0I2DbUvdnT4hHcPtWv0t/Z+OqE7oLpPezm8Fvzfvvh/gz7tADDDJsS3RTVFLMULRWuFEsUWRBGA0v1Cu4x8PH1dQBBAzj7bfsP9270K/oZ/PfzsvFN9LL0cfl8APYLoxTbGM8ZoRkbFQIGQ/7P/Fr9e/2RA70U3R/DK5Uy1icoJc4mOh7wE2EKLwvyFLoUFgg0B9cVZR3iHtUc5B8vLKkxbifxF1wRbA/LDtgM2QW/AusG7BDaGFMYlxV+FzMfICYQJ4sm0yCJFeMPoA5GDhENvAqfCbwJHApgCd0HcAa0BZQF6QZRCzsQnBLmES0ObwqzCl0LWwgxCEcIQgnXC84LZwzmDIIOdRLtFDUXyBaIFagO2gGd+1D7cvnM+pH88/6WBHsDbgA2/Vf8LfsL87XpE+kD7/724wHVB14IiQSp+WfyPfAn8QbyNvI68GLqS+dA5RXlv+YA5pfiHN+N3e3bwNzs3Evc7dys3aLe0uCl5KPlF+TY39Dd7N674ZDmJum76Yzo9ejm6unt0/IF9Y7yRvFT7rfrhO619aT6ivo3/x8CUgOxA1ACcwV7EAggZijKK+kuay/tLzkzBDQmKkwidiF+ILIdsBwVHlcgYR2KF5AZyBrQGAYT3Q6VFkQflB7mHFci5yxIK50m6S24MxAzszG8LcIpGi5CNRA73zygOEwzDTNBNnc07ic1JDcmICW1KEgk2iEfKNAwCDagM2Ytly32MAoybTJlMiQyHDGnL7cuwi1aLGgrXyeKG1QRBw9RDncNVg1xDKwJoQU6ASD8O/Yr7ezkUOD63rfeNt4p3kfexN6j32niY+h98ET26PRR7nXopuaP52Lpn+4M9/j8yPze9ozwA/I8+AT5ovdn9+X4yfg/9yj3MviP/6sKjxBdD6EJBwr2Cd8FmwV0AoH/Jfg28/vvL/Ey+Vf1lO6Q71LyWPby+Wj2QvO485n42P9tATAAIQJ0BRII0QlaC0EL5AoeChQKGAvmC8sLfwhJA5wBowXjB7kIQwlzB28G2wVEA7f/aQJlBugFigO6/RP6yflv+s77t/tl+0758fbS9576Gv1N/ej2pOot4BzeCOjW8UnzmPS/9s/5A/5R/3376fiE+/n8BgHZBYgINgsOC+wIsgRp/sr1DPBe74j3FAOtBpkGMAUdBFAEiQQ6BI4CeACp/hf+6f1g/er8Tf1C/kL/xf/1/1sAdAB2/4L7/PT77TXnRN+K1r7PMs0tzErLAsu/y2vMec08zlLOaM0jxgTAm7/9vUy5/LO1rOuiH523m3eb0pvunTSgcaKMpAelU6UVqEytdq4Cq66p76rnq0GwerptwqjGNsWav6y6k7m2vKu/6MJNx77Kp8040AvTN9cU21jdmN+q4vfk/OYJ6UnrSe5r8EH2z/19/bv5F/lWAJ4MMhXUFWEaxiH0I0wjrCR2J4wrSi/lNIU7ID+9Pzk9tz0mPpdCHEaVQlxAxUKmRqFKKku3SaFFDkE3QQdCTED+PuVEhEvhTYpNt0z+TFlNvkxXTKJLwEeCR9lEJTrKMDcpViMYHk0ZoRJ/CysIlQUHBBUDMAY2CvcFoAUoBsr9T/b48g3x3uuX6J3nm+Nd3QjX8NL00ijVvdkn4EDgp+C54dPe9dy124jZctq424vbqt+W5SbqCOe923rX/tq83lziJujU7aDySvbP93P5ovnT+q/7x/m9+nb+uwLmCJsQXBpjJGYkhh+SHYEgrSRgKK0tYjCcMDc0VTWTM/0x1S5YLJwrSiunK3ssQyrjJ6IofSr3Jjok9yYlK1gwoDRHOaA8Sz5bP2I8szfjMqEvKy6LLewuuDAAMDcxvDK+MkU0iTSmMRAtJCf1G8ATgw6TChEJigZjBEcGww3jFsUa/RhnF/kVMRbNFuYUQhG3DLsIJAVlAsUBjQN3Axr9efZ88w/zvPJa8JPtdOsl6Xnnb+XH5H/qU/Es9gv3vfL57gLsI+nj6KnoQOeS54vm5uV244XdQdlw2AvZbNqr1xrSjs8azsDNjs+O0ZzS/tMR1cPVtdbY1sXXu9jg1uPUWNQD1anVu9fo2pvd9N4a4MvhK+Sy5tboVuuV7hHxEPEe7unpo+kd7TTxwPNo9gf6If1A/+T++f03/VP8QPxU/LT8lP35/UX7T/Ub9Df5jf6fAXkC8gEmATUAzv+IABkBigEcAQsASgARAT4BVgDw/mT9yPzO/Ob8Uv1E/mX9kvq3+K32CfaE9nP2RvZR9tr2lvds+Gz5NvqV+6D6N/ej9FL1FvtZ/rb+q/33+6r67vnJ+9383f3c/vP+J/iW7QLqm+0h86z0ufQV9n/4JPrg+hD8CP18/9MCOQaSCeEISgYdBjIGkQTOA1kDVgMgAw4Bnf9e/wT/vv5B/rj9Xf2M/Rj/GgIiBq0IqgvqELkWdhuyHO0e9Ru0Ek4H/Pk08LnpH+lO7H/qCOUG4TzgluHK5/zx3fkU/scBVQieDl4Rkg2gCtIL0g9/EGEQfhHHFKccniGYIiAgrR+hIWsiRCO7IkYgux4QHoEikSZVJO4a4RTpFxcYtRULEbkMVQvnCfkILwlLCrsLQww9DFYLTAlHB+YE+gGAACIBRQK8AUEAfQEHA6cCOgEYANz+yfxk++36UPvB+6r7kPsa+8T6j/q4+CP38/aC9wn46fYf9kP2/fZA+Hj6mP0u/2H/PP7n/P39TP+H/wEAVQCiALsB+QJIBKUGBQlaCZ4HkwXzApgCMgNTAUr/tPw49BPpl+qi8rP29/am8rzxiPVa9OXtYOml5zHlKuJT4OfeCd0y3e7en+BO4dLgQ+Ak4IvhmeN75aHnXeoJ7BHsputt61Xsd+0/7x/xs/Ay7gnsG+wX6vzoGep46/btLfDB8vP0TPfC+I/4cfnq+Tf6Nfsu/hQDfwY8CewFMP6a/pEEaQRO/wwEvwwSFB8eiiSKIg8fTRxlFb4MpwiECAAJnAfFAjT+ePll8u3tR+zx7GfuF+4L7Ufs/+0M8kj0VPaO+D/5wv7jBTMJ2wxAEXIUIRiaG5YdFx9vILEg6CB6ImIikiTtJKshRyGVJO8o9SZxJcEi5B83IUki4COZJ2MqSynNJ0wldCFCG1MPZAZHBAAElwJdAagAHQB0APr+uvvD9uftDurE62buYPCP77/tMevi6zzrQulQ6q/ofeX3413kQ+bt6PTtCvJy9Yf4Bfr7+gv7Bv3s/ej8NP2LAfUBfP7X/xAFGwuIDn8OiAgHCBEQZhUQFyEUURJvFkIaYxzrHhgk9StgMMEwPzMDNe83rT3UQDZEmkIlP448Uzu4O+A67jldOyc8yTvqPGA9qj+nQQhE6kVaQ01Cs0ItQ8M9+jpKN2crUyH/GrkZKhgvFM4OkwkMC8wPlBHFDsQGsv76+s742/Q18bbwEvGd8sX2HPjB9kD11/OB8VLv7PK++UcB0wnGCncHTQgoCxQSThanE/8N4wvdEe4WBxh3GZkYVBjmFF8TGxPzEoMTrBTEFboU2RIfEo4R5A8ZDvQMuQrIBz8GSQU/A4YA/Pqy8/XuEu9I9GL4VvsTAYoDhwPcAtYAmf6c9eDtMu648DPyvfEs8BHususO7GntMu6W7TDr9+do4pDdw9pr283emeBy3pza4Nc000fIkL1Ku0O73bpAvrTEIszfzKzMmc7Jz3DPbMswy9TMKs4vz5XQgdHh0KfQCtTf2O/bl9yG2lTaZN/T4+Xj7eJ06hrzhfo2/0YD2AhEDj0Q1Q8hES4SsxIqE2oTVBOWE8YTbRUwFwoYmxnrGrkaJBqGGu8bIB4nIIIgOx8SH5MgniJaI7Ih0h4WHB4akBg/FaoO7QdsAy4BtvzY+Cj5BfuG+2f4BfTY8ejv4+lb39HXZdUw1K7O5sFwt1CzabNZtfa0i7GTr0Oumq0mrs2uV7Bvs+W0NriUvPm9Lb5lv5vCzsV0x9bGOsaexlXGA8WuxzPP2dPx1KLWzNgU2VHaX9x338Xh9OQZ6z/xcfVr95v9MANjCnISBxYOFzcXTBccF5IYLBqRHH4fFCFqI2UkKiN2IYUecRzTGqkZJxkBGcoalRqNGHgY4RoMHeAdjB7AH5UgQCF+IMog7iMlJgUm2CQlJDMi7h1VGdAWDhTxD+cMTA2iDgkPQQ7yDYAObQ7IDY0MaQvNBQsAxP5r/nf8w/V07tfpOuic56Dm8uTs4gnjsOP340fj1OFB4QziOeTj5Gnkf+Sz5qzpA+vu6zTtU+9M83L4k/s6/J79Jf9OAyEMohbUHW8ghSHKISgjdSTKJC4kIiPGIpAhTiB4H94eJx5HHXgeXR2EF58OfAn0BYcETAVMBYgELwRaBrUGjwTnBBYDOQB5/F70Iu/X7KrrF+uY6YTnwOXi48nhiOCX3/re5t1Z3Mfapdm32WPaHNqN2HLX/tjX23Hc9dsT277aUtzE3lnhUeMN5Zzmkem57Hbu4++68JvyjPcn/Pr9dAPTCVsPpRJMFDAVAxYYFpASMw82DPQKDwp4CPgIngtmDjwOZA+dDyUOrgwfCjMIXgXhBMYDmgJYAhMBqQFiBHwGUggtCTcIbQfoBkgHAghAB5QGPwYIBQEENANWA1EDUwP2A/ADiwM4A20DaAJPAJT/+//NAMEAmwCEAKz71/Sn8RDxBvHd8PnvV/CZ8bTy5fNc9KP0OvRf9PD0rvQd9CjyP+/x7Kzrvupa6tvppuko6oLqXepy6jbr3+rW6SDpM+gR5xrn1+e75+fnAuip5jXmrua95vDl0+OX4h/hLuAM4KDfp99134Hf9t9a4YTj7+NG5Rbnt+jO6n/tnPHA9kr5sPqi/J79yP5h//UC3AWdBz0LjA8OFlsZVhylHoAetCDJIS0hziJ1J7ktYzVGOtU7cDuDPCg+9T8IQV8/JT0eOjw4MTbBM341fDWYMcYtoi5aMXsvUCw5LOgtDSziKO0mviWTJ0MqnCygLAAtHC1mK20piCk8LUownTUdPKRBhEbpR+9Hv0a6RExCaz6cOYk0LzDBLVMsjCmnJ1gmKyTNJDEmoyXxJo0pdionKzEstCw3K7Un1CPvIMMfGiCeH5MdsRz4HQgeDR36GywZSBcYFtwU4BQ+FfwVkhULFCITaBLkEfcQLRCvEOwPYg2NCjcH3QMtAnUB6QBb/yf9jfwW/dP9Yv2O/ED7hfiE9knzF+0Z6nfq1OqO6grpj+ig6MPooOby47HjWOM84c/e+d5W4Q/jwOUV6Z/rzvAE90f7EP5AAFADZQWvBuoIBQpbC94MlQ2YDuIP9A8cEjoS2hBTFG8UtRHiDWQGWgIaAvL/eAPsB9MGSAj4CLkKcg/XES4SIxPcEvsS5hWzFpIXNBhoFp4U6BRrFCUTHhPvDjQMKAuiB6wITQmxBpMHZQYIBJMEzAMhAdD9SPrg94P39/U684Twy+2e7BbsPuqr6CfoO+d05qblveRC5IzjFOMT4j/hSeCP3kDdCNwI2gHYptd02FXZ2toB3MPcVd2r3XXeu96N3kDdwtvB2rDZKtlq2arapt3q38/gZeAR3vTbntru2GHXstTo0V3RMtJM05HUfdVJ1rLYT9y83mrgjOKa5DblAOS74rTiM+F2373eqd6I4IXiiuOn5Xjoe+o97uXx/fOy9Jj0J/aY+F77Df28/hYBjgOGBYgGcQg9C68LhQmnB2QHnAi9CU0N2w8mDE8MNwu2CBwKywieDHMPnQ6rESQUthP/FHAUBRGFEeYPxA0+Do8M0QskDAQJCAWcAxgCrgIDBLwCxP9E/TT8ifwt/V779fvx/Zj/BgEIAMD8tPjG9V31RvcO+Ur6BfvU/dYB+gJoAzYC1Pwl9jXyJ/OI9j/4Cfni+XP7IfyY+iz6I/xr/sb+SP8bAGwB6AIiApv/Sv0q+234avVd85zw0+3t6iPqiept5zHpeu147T7vC/Gq7cHqgust62Tp5ukt6zDoPOTD5azowecX6Z7ssu4m8XvxNPRc9fb2Zvut+k79ugO0BwgKbg62Du0OKRXFFKMS1RT7FJsTXhU0FhUYsxgLHBoi9Bt9HhgiQx2DIzclZyAAHigjhSOgG9ggDCRbIcwhLSXtJIcggyG5HPgWdhq/GzIUPRRUGA0U+BT0GA4ajROgE+cYvBBWDQAP2QmSA7MHeQci/YD8Fv7p+c72q/iA83vrKu1n7GLkheFR4ibc4dYM1/PWPNNG0orUpdGdzmDO981TzTDRPtf52X/batyT3IPc2t7k4pXlwedd6RLpfOld66nu4fDx8Abyw/JU8sPxEvJf8eXx2fTk9SD3z/mB+w38bP3e/g3+Ev3q/Rv+4f4uAjsD7QHJAEoASP+H/bf6t/dU9hH2Lvdp+Pn6yfz8+z36Kvha9/P31Pr+/O39iQBgAy4FhAZlCMQK2ww4Dz8SGRV9FwwYmhZ4FfUVjhYWF1gXExeEFwEZFxo9GX8Y/hc7GLwaaR1nH+IfsSCcIi4kbCVVJo8nQyl5K5YsdSxSLFos+yxzLWksmirmKHcl6SEwIDwfyx5iH84g0CEiI9skFybuJvQnQikkKhsqXCnVJ34mOya0JfMk6STMJAQkNiXfJsom/SU4JuQl6CRgJDUjbyI6IG8d2hqKFsMTnRK2EC8QZRDnDugM+ApJCnEMeg47DjQMtAhsBTcCDf/f+8L4yfU48y/zMfM68hfx++6q7PnrZus47PXtmO6X8CfzGvXD9qr2Vfb59qf2NvcV+S769/om+076Yvq2/C/+tP9RAWUA5/8A/5X8xPmT9w/1+/JH9IL1OfWz89vyf/Nc8870cfVo9Q32lfW19qz4iPyuAGQEMAdiCeAL2AwQD+cQMRPrFXkYhh3ZILwhbSJsIn4jliTHIrogNSCTH7wbRxeFFHcRKA/JCugELQB7/Af5DPRd8Tvvb+wb63/rfeqK6KHnf+a45G7iHuCh3PHZp9jJ1enR88/wy1DFf73jtomz8a6Kq/SoiacTp5emqahrqQqoWqlFrYOxjLV3t5q4oLtDwSHH2smezCjQJtJK05LT9tJc0oHS9tEz0CTRVtKGzwvNYMxxyizLcsw3zsjR99OU0dnOQ8/fz9rPNs4+zArMAc5k0KHRZdIk0/DTzNMm00TTstK50Q7SitJd0tnToNR70gHSJtKR0+/WIdlA24jbtdov2xLck9504lTl4ecr627uqPF59Gzzg/BJ77/v4/EE8+n06/WI9bP2SvYe9UX3H/pf/GD/9f6K/J/9GwDm/4//nAExA2IDmgRbBv8GRQi6CpUK8gkkC6ULkglaCTgMAA20DowR/xFYEcsRchKvEHEPbA8CDQ8JTAihCYsJRgtpD1wR4BBgEaUQhQ1UDGsOGQ+yDx0ScBIaE7EUFRYjF8QXDhiaGLgZCxyiHYQePSD1IUYkFCYZJ3YnTih+KRYpniekJdAjhCF/HxAf1h2bHvIgFyKbITUg4x97Hw4e/xu4GpMaMhv0G1YcYh3MHWIcixmUFyUXYxbBFu8W/BSUE6cSMxHsDvkMdQz4C1EMJw1uDTMNkg3yDngQdhSYGD8a/hwHImUmGCjQJo4liCUcJtMmRidDKBQqtyykLwgz+DSWNQ02kTVjNE4z+zONNEU0MTV+Np43eDjsNw02hjOrMc0wYDBnMacxMzDbLiYu+SzqKhAqYSpAK1UrjSrfKJknUia/JIEjDCE/HtgaThmIGlccjx4EIakh5yHUIukigSRAJ7wplCtWLbgutC49LaMq4SZkIiQgCh0iF9AR6Q2wCdUErAD1/A76svYS8xbweuzu6MrmCeZI5T/kMON24jviB+IQ4qHh598p3SfbGtny1rfWwtWD09zQEM6izNPLAcr/yG/IsMdpx47HtcccyOTIpsgtyPzIw8tEz6DSEdWM1hPYatpo3dPgxuW+66LvofD98FbwJ/A+8SjzP/Rm9En2QPiV+e/6VfsJ+7n7wPzI/OX8vf3J/m7+If5Z/Xj6TPlD+tL7Hv5XAXIDogOBBMIFlAYqCNMJ7Qn+CEoI+wfyBlEFBwWXBVYGVQU0A0QCIgIpAi0BRQAMAIf/Zf91AJwBNgKLAm0C+AF0ARwBTQDq/vj9f/0V/S79Rv2z/PX6m/eD81vwwe4r7iLu9O3G7b/t8+1s73vxBfTh9sL65f5fAW0DzAQDBsEI6gvODhESuRMRE2IR/A4gDFsJEAg4B1wHpQdtB30GFAUrBN8CIwKxAfgALAEZAY0AJAFKAgUFSQiVCicM2wzWDYwO6w7LDVQL9AmkCAsHVQVnBAUEyQP4AisCR/8U+z/4RfT48MnvxPBx8kj0JvY/90b4efjO+P358Po//av+z/5o/ycAkwGDAkcCUwG+ACcAef/g/vD9I/7c/oT+8f3+/OH65vcM9jTzqfHz8Tjyg/M69Yf2mvf495b31PgI+yj+nQI3BMIDiAPEBI4HXwvGDXMMsgmZCIIKuQ2GEDUS7RLBEkYUlxWWFfcS5Q7ACxAJ3gaoAq//Mv1N++v5tfh7+KX46vji93n1LfSf8zXzFvT58yPzHfQn9Xz1tPVZ9K3yYvHd7jvr4efy5TPlkeQn4/Hgm99c39PffN/33XHb8tc61VfUW9V514zZMdsz3Kfc892o4BLj9uM942LioOGe4Qfjs+Sr5fPlDeZn5mjmUOYd5hzmNuZH5SzjVuG64Czgzd5J3TDdAN7O3kLgjOLV5Q7pr+rS6t/r6O7B8V30FPZR9wf4pPck99L2Zvb39X/0ffMk9OH0GPZu96n4EPqL/CH/+wEZBVEHEQnrCkYO1xKoF7QbKR+xIeIiwCMJJaYlCCY4Jw8pGizZLiMxPzQLN304ejhaOLk4izmMOpQ8rj4NQAFAfj5JPKg5ejcSNlI1dzTRMz0zMTKtMDUviS09LPkr8CqLKUMpQCkfKYEoqicrJxsm/CP/IGMdfBqBGKMX3RhiGqAafBpyG0McuhvXGaIXmxQ9EUQOcQuJCSgIugcoCeILQA7ZDkgNGAwiDGMNXw6vDTYMJwlJBuYElQMxA2sDxwIrAqkCQwNfA2UDLwMaBNYEhARjA0ABuv8K/nb8//tm/Pf8tf1D/lP9Q/yL/E/9ffxk+tL33PWp9lr4q/gG9zD2qPfp+UH9iwCTA+4GiAveEJIT6RRUFuEYhBtLHFobgxm/GHEa0xw/HlAe5hy7GlEXkRRKFDMVzBVCFRIV5xT9E4MT+BEHECMO9QvUCaAIzQgoCAEHKgadBy0K9Av2DGgN9g3fDS0MhghHBLT/CvsI92f02PIG8GHtWOs16efn9OWk4mPfpN1k21/XWNMV0IfOp827zOzLHczazMXM9c1q0FfSfNNy1cfXudlP21vcWN0q3Qnccdim01rOhMjzw8zArr88v02/Tr/Jv+DB9MNJxbDFysUjxqrGUccxx3jGGMcSyEnHZ8VHwzTBMcDxwC7CCMNpw0zDOsOsw0zFyMZ5xyjIvMhdyRPKy8oSy7PLgc1V0EvT9dWg2ETaCdtA3KPePOKx5W3nK+g56ZTq4uuD7N/s4+2c7w/xZvEZ8f/wi/G78ZfxefEm8mD0nve4+nP8mf5nATEEdQY6CMsJqQrSCwUNUw59DxYQvhDaEGUQ4Q/dDiANeQtXCgMKgApkCyoMNQyDC/sKYAr/CeUJWQrjCgAL1QreCvEMFg9CDyAOjQ36Db4NjgyqCtIIBwj9B/8GyQXYBGIFwwjGDDUQ/xQVGxEfWiCNHxUfuR+nIf0jUiMKIQQfWB1/G9wY3BahFwQavxyvHsIeOB3zGSQX4xRyE3kSthCHD4oPQBBlETkSPRL+EbQSZhJrES8R3BCTEOAO1wvECfgJcQsxDcUNUg2ODKkLqQpACeMIIQsyDzAU9heEGc8a6xvhHfcg5ySDKUcvrjXgOvA9+z30O2w6RTnpN5Y2HTb2Nx0810AERKZFAUazRqVH40eJR5ZHX0hrSSBKEUnaRiBFHkT7QrhBFUHlQNw/TT2VOuQ3yTRTMxIzCjORM38zFDKOMK8vWS94L8wvMC6iKqMmBiLzHAYXZRDNCmcGLgPy/477XfZx8MXptuIg3OLWutIk0CbPO83xyYPH1cZzxwnIbMh5ySnKq8n9yLPI3sg9yZvKqc2V0VbVedlO3WLhquV56hjvevHB8qbzC/VW95f5RPtn/Nb8ffwm+z/68vqN+wP9Wv9UAW0CbALMAbIAZABCAID/xv6a/bL8O/x5+8P7Xv08/zwBpAJMAlgBCwCx/Vb6Lfeg9ff1P/dp90X2ufO772vsCOlu57PmoebH56bpAuxs7uXwtPIz87nyKPJZ8hrz8fNO9ID1VPgp+rP6A/nI9uP0JfN/8uPxBPKk8fzxYvTD9y38wf/1AUgC8QJeA20DlgXmBQ4GSQfdB7sHOwdpBrgHeAo4DdkQvRKZEXoPlQ3hDFEMGwuRCDoGhQSrA1wEdAWPBRkFngNYAqsBgQBg/437uvZN8Xnrn+Wq4Z3fGd4u3XXbNNkV1xPWgtZk17HX29dc2EnZNNqd2oPaf9pg2sna3dum3ATdk9xy2wXaEtlw2SLbPd0/3rHc0NlN2KfXMdfR17jYHdox3IbeN+Bg4XzizONc5dLmXOjC6BroJOcm5hTmwOZt5+rnUuhm6avqQuv36iPqJOoY6+LrK+zF6wfr++uA7fzutfD48Rbz4fN59S734vhx+939hABbA0cGTQkvDCINWg2fDWENgg2UDvoQ/xGXEZ8RmhI0E/YSHRKjEJkPfA59DVgMUgwRDfAN8A+YETESaxK7Ej4TXRNuE24TYhNCEzcTsBLrEggUaBRDE5kRdRCjDr4NGA7ADrgQSRLtEhwTeBOXE+gRFBDZDoYNRgp6Bo8CLv+f/fX8c/1t/pD/HQACABkAdP9M/p/9Vv73/xYCLAWSB1AJWQloCHIH8Qd2CS4KAQulCzkLhQncByMGHgTKAk4Byv+O/h/9qfvI+aH3k/Wc8xryofGN8afxHfKM8uXyN/MZ9A71pfVb9h34sfr7/CP/vgEJBb4HqwixCNYIiAkSCwgNgQ4BD7MObg4DD4wQ9RHEEk8TChQsFQgWahYVFp0VFRVAFaEWRxiCGZgZfBgpF+MWbRcuGJ8YcxjFF3oWkhQuEtIPkQ3oC7kKsgkWCa0IqAi9CCsJkAkKCbQHxAW/A7gCgwJZAq4C/wMNBiUIkQkICg4KjgkPCfUIQQmmCV4Jowi3B0sHDgfCBkEGtASoAr//nPyS+Y338vZd9xj5cPr3+8P72/yA/dX7gP02/LX7h/tD+Fb4+fb79WT2X/UR9W70MfNL8v3xDPLb8o3zQfSw9Nj0kvXp9WP36vlo/Kb+Xf+g/7D/Mv8QAPsB1gNLBbMG3wdACRMKDQthDDYMWQwJDEAM4gy9C2ALTwmOB0QIagdiCJQKqQviDdIO8w/WEvgUfBYRGPIZIxtwGwgaLRjlFnkVrhTlE6ES7hB/EG4QqhBiEc8Qtw+IDnoMGQqsCAwI4gijCbALZQ3GDPYO6xAIEQsRvBCNEakR+hB4ETkOhAp5DGYL5ArjDaANdw2vDXYMKQzzCxQJJwf0BakCUwEMAZb+Q/yc+tP38faz9vn0vvNS8Qzvxe747dHrBuu969LsWu7e7pDtdOsJ6uDoXOeh5tXlSePH4QThrd8U3onbBNp62MjWhdXv1AXWlda615zZD9oN2mzbh9xw3KfdfOBy4tTjOOcY7GLuCO4u8FDxxvBs8RL05vd194/6kP8b/m/8bfzG/A36oPb+9Eby9u8N7KXqoOqO587oCOuk6jLrUey17fzuHe+57hjvYO9i8JrxJfJl8vzwJu/z7j3v3e6T7kbttuvD6o3puujo5oflmOW35THmwOSX47LjxeJU4jrib+Ip4k7hj+CK3wPfP97w3Rbeet3u3GTdNd7V3uXfC+HY4XvhK+E64Q7iluN95F/lleUW5innnOfs5jjmKOii6hLrquph6orqgOtA7Nzr3uom6mPpAunm6KTpseuX7e7vLPGP8VHx7+/473fxnvO89p77JwA+A/wFyQfkCAIKFQszC7sK6gmnCIEH5gWqBEIEcQQ9BqAI7QsgD7gQJhLvEjkTvRJCEt4RTBEgEpASqxEgElkTGxJzEXcSBxI/EkIUYBQXE+cTzxSeFD4UhBP8EVMQpRASEgYTYxRUF2UZ/xjsGBcZNxiTGCcaBBtcHNMe4yDAIdkh3iGEIfUguSAQIAMgkyB/IMIgOyH5In4l/yZQKO8oJigOJmgj0iCzHgwd5hubG20bVBzCHYgewR+mIIsgByCGH8ce0h3WHGwcAx2hHWsdNh2XHbwdqR1nHQMdkxuBGc0YSxjeFx0YeBi4GUkbwRsMG7IZxRh+GKEXuRawFYEUexU5F6cY3xqlHTgf+B+qIYMi7SEbITkgQx8xH3cgcyE5IuAjMSZwKAYrbCxFLEwsCS40MfYzkTZKOJ05cjpvOQI4OzeaNsA11zMXMVgvNi7zLNgrfCuqLO8u3jCsMFIuaCtmKXUnOSW4I2EioCCcHrcc7RrKGf0X1RVOFTwVtxQkE18Rrw/gDT8MpQrICJgGAwU1BAUDJACWAC3/1Poe+/75pPnE/BMAHfzo+18HDwZB/mj70va08V/vOO6a6jPq0+qd50rjI+Ax3P/XaNQg0lDSEtME1W3TO9Uk3Bvf4OBF42/lz+Kq36zgHOLH4JrgX+RT56Hqd+zG7s3xRvAz7WHqEehF5hjkIuLE4AbdCdw+383eUt/s4cHj+uTS43vjcOVB5+jmFuc26G7o4ul56lLqBeoq6fHpqutv7T7vuvBx7+zryuh35jPl/+PJ4mXgEN4S3I7ZRdng19HXP9qj2q3b7dvr3Orf6OE34ifiD+MU5MzlHuYz5ormE+ZW5f3ln+ad5Hfleuaw5ufnreku7R3wcPFP8A7vU+5Q7Wzri+lh6Djm7eNR4arfFeGu4lLiVuKX4cbiwOOt4nHkreXp5j3p3Olm6e/ut/Bz693v6O8M7LvwVe7b7TjzRPKi9nD4vPtAAfv9UAb0B7MGNg0xCqoLvQxeCkEKnwnWDKsOGguQD10OiAeOCh4E5gSuBNv8kgQ/AUr8j/sb9Jn0n+1N6dHv5+sh7gTyu++Z9Bf2L/ev+Uz58vy9/4cAkQOJAET96f4W/Y79Yv1T/k8Br/66/tz/LP4f/m/+t/7A/V383v4IAPz9d/3R/ID8yPzI+Fv1QvUm9Nn1qvX79X/6wPtD/YX9h/2D/QP7jfpG+bv3dvea9i337fdJ9wT4FvmQ+W37Z/wq/vj/BQC1Ae8BzQJvA2IBYALFAuEBNAKkANL+aQCvALIAMARQBBAEfgRpBJMFagUoBuUGCwb8BVgI1QpdDBEONxAnEycVVhb9FogWIRW4FDYVPRSTEq8R7BFtEkkUbRSGEasQmg/0DwQRhA5AEJkSdBJuFG8UTxYXGUcYuBhOGMYVCRVDE3gRlhErDycN4gz/CkgJ2AkuCrgKCg3iDhIQ3RC+EqQTQRMqFMQTqBIbEtwQ1g+BDg0NuAxFC/wJQQhkBvwF3QQqBLMCPAELAOb+Sv4v/+kArgEDAyAC/AHQAswCeAQgBH4D4gMkBNMEvgPgAWwAB/51/Bn8Z/sm+zj6ivlO+lf7Qv1m/+oA9wIrBCQF2waWBzMI5gfIB3oHJwYSBQsEywT2BUYH1QnRC5MMfg26DVoN/g0aDvEOUQ8/DvYOExCcEB8Qog3oC68Mww1oDY4LOwj9BGkCzQFzBF8FYwVsBp4GSQd1BngF5wNoAU8Apv6U/cP96f2K/QH8ofnX9nfzMPHO8HLvXu7f7SLs4OrS6W3opuZy5WnmE+h46d7qz+w97xbytPTK9qb4gvkY+3r8AP3P/eD8A/wx/NL8r/5M/0H+mf18/U3+2f/XADICBAR7BfEGEgnDCtUKrQp9CZMHNwfKBpgG4QeLCMYIHgkXCfwIPwgnB6QFVwR+A8oBPACP/6X/fgDwAFQBLwLuAdMANQDX/+P/9f97/4L+7/xn+2j5qfeY9473Nffl9zz4hfi8+Kf46fjS98f2KvZT9kD41Pl8+zT9Uv7C/rz+wP49/jX+8/6EAKsCvwNTBN0ENQWLBQ8GBQdHCAwKAQteCmoJIAiMBqwFeQTyAkUBcf+q/R77ZPhU9pn0O/Pw8XTwa/DR8DTwEu/W7G7rjOv363DtLO6L7mDvDu8H8PzwOvAc7+vsFetn6sXpt+kK6kLqPurI6c3qIezB7ADvg/AS8KLvZO6c7KjqvOjV51DnG+iY6sjrpuuW65fr+uzZ7rHv0fC48Tny+/La8obyXvIR8ifx0fDv8Uzz4fRq9bj1gPWW88PxavB87y/u3ezS6u3n0uSf4cbfKN8W37PfIuCr3zrfJt4F3DHahNjk1r3VNtVt1dPVaNZN12fXoNd12PbY+9nz2jrcq9764QXlWefH6Tjrrusu7LPsO+2t7qXvtO+C8BfxdvJX9Fn2yPgk+bv4CflF+eD7Sf8tAQwE7AW+Bo0Idgo2DesOQQ/qEGMSkBPTFI8VoRa+FlgWThZ2FlQXcxcuGH8ZRxpBHO4dBR8tILIfzB6MHvseMiCOIBAghx8YHyEfZB4EHfwafBihFhoVIBRDE7IRbhCTD0UPQxAyEXcSIhRPFUwWOxayFoEYFxo6G/YbNhxsHDkd0h1mHlMf+R99INIgdCHeIa8hwyFpIoYjRiTnJPMlaSdZKUcqASqKKWEpWSqKKisq7ClmKYcpQSouK4Msty6aMNExgzKVMjIzIzTmNOA1KTccOEA55DqLO048pD0RP/tAREIWQ/JDCUTYRNZFzUXZRe5EikOuQitBpD+QPmk9KTv5N/U0JDPmMpMzSDSdNLQ0EDT2Mw8zVTDwLbcrQCqXKc0ppipkK9UsMS45LlotZSxCKkco3iZmJdwkpSPAIqMilSJsIgwiGyJ9IW8fvByKGQ4XsBWHFPMToBM8E8ISXBJLElUSWREDD1AM4gnpB54G8gaJB84GjwQ/AXD9oPk690X1bPMf8h3wM+457YDsBuzk63nrj+qo6DXmpeNR4lPi2+F24e/gsOB54JPfIt4b3JTaCNpg2nfaMdpg2njbEtxJ2yPaKNhK1qrUydKj0WfRvtFW0tHS1dJm0unRIdKq0ojSSNKC0pLTftUH1xnYf9iP2ETZh9nV2ajZxNhQ2KvXyNco2FjYzdhY2Qraitp62ojaf9og2X7Y/ti62Yfaptof25Pc+N3w3UTcw9nu19XWndWg1NPTQtN/0mjS0tNW1YDW19Zi1ibWMNYV1tLVuNSn0k/Qcs48zhzP4M+e0F/R6dHs0WPRR9DNzq/NVsyhyknIR8UNwnK//L2qvMq6jbhBtsG00bODskWxVbC4r8evWLAvsc+xqrIZtLu1E7fjt2a4JLoJvVO/PsAlwETAD8Fzw0zHi8tI0KfTHNVO1sDXbdno2vTbM95n4ULkIuiB6yrt+u3E7Xnu2PBT9C348foF/Uf/swF9BC4HLwkrC6QMEw15DW8NGg2iDZ4PuBGEEvMR8RC7EKsQ4Q/vDvoNPA0gDYkMhQuiC5gMfA5eEDgRghEVEncTRBaQGc8bRx3BHQce4B5jH68fbSA3IWohRSEaIWshmCJjJIomSSj/KBoq1Cu1LP4tii/uMKoyVjMHM3IzWzT+NOQ14DURNcg0SjXbNoE4bzmyOSo5tTiROFc42zfLNgo28DTmM1ozQzKTMewxlzKmMrwxbzA6LxUvUi9aLiUtCiy3KmEpTCjDJ8kmuySLInYgjR7OHKAaoBiZFiMUSRE6DuIL0AnzB30FHgP2AWQAs/5T/DT50PdD98n1YvXL9LzyavHb8Nnx1PP59Gz1YvXJ9L/0IvUk9sH3EfjM9/33RvjB9yb4Zvok/ZL/EgHvAZkBKQEmAf4AJgBQ/er5i/Yf9I7y1fEn8ejucO0k7bbsQezR6yrrqOq56o7r4Oyr7hjwKvHS8v7zpPT/9Uz4Kfu7/ZX/JwHYAUgC0gORBaoGzwZ1BsYGzgf9CGQJswiYBwQH5gbcBtYGXQZ9BY0ENwMEAm4BkwBSACIBtQFiASUAvP52/Sf89PoZ+nb5J/nO+Yb64vo2+5n7qfwK/tX/zQF5A9oEqAUNBq0GNAjUCZgLbg2+DS0NcwwSC0cKCgpPCnELoAwbDpgO/A5UECwR1RGOERcRIRFUETYSWBP5E6MUxxSgFLwVjBZ9F1oY3hgxGmcadhmMGGsXdRYjFUcTOhH2DscN5QysCwIL1AoYDEcOBBBkESkSDBO2FAQW3RbOF2QY1BhYGQcaqxq6GiMb7htOHNUdcB8cHzAe3hzwG0kbnBr8GtUbnRyhHNMbKRvtGWMX0hQvEhoQTA7ECy0KowlmCogLXAvFCjUK3QhwCL0IZgi7CI0IdAj3CfsKFwxMDfgMoQyJC7AJVwm1CHkHdgc9B5UG/gW8BCQEUQTgBPUE9ANaBB0FOAVqBc8EnwQzBUMFKAUFBFgC6AF0Ae4AEQB3/tT9M/2k+9z53vft9pv2BfZg9RL0/PLk8mDzSfTW9Cn1l/X89fL2+/fN90v3FveJ9pr1KvXL9cT1APXr80zyxPBq79vuke5y7gzuB+7m7bPsAew+6tHnfOao5P3j5OWc5/Xpw+uK6mvpNOfb4rHfCN403arc1trS17DU7NG6z8nNFc1bzA7KCsf9xBPE3MOpwybCacDbvia9DLxnu2K7urvNu1+73bqDunS6n7oEu56667iWtyO3E7crtpa04rPjs5e0L7a8t2i4zrgIuYO4r7hLuQ+5mbgTuBS4jLnJui27x7zWvfS9Vb+jwF3CMMVbx+HI6MlMyrXKUcu6zInOoM8C0FTPMs6YzGHLzstAzY7PyNHf0zPWc9iY2s3cI9/94Bbi3+Ii5Aflr+XT5hroeerM7H7tVe1o7UrtHe187SPuUO+18P3xVvNO9dT3EPoj/Kf9Z/4v/j/9Zfy9+6n7FPyA/C79bf4AAGABPQKqApAC+wJ1BDMG1gdmCWELag1tD+YRfxPdE4IUfBTJFD0WUBaxFkAXvhavF90Y5BiTGa4apRveHCQetR76HnEflB8FH6oeyB4oHs4dTR7fHpof1x9KH/QeER7NHBIcqxv3G0QdSR+6IfwjeyVhJlwnxyirKt4srC0SLlEv0TCVMpAzqDOsMwA0cTTENH41NTekOY48RT80QhBGL0q0TWNQ/1L6VZhYNlqfW45cyl0FX5Rg+mL7ZLJm/2UXZTxmnmXaYsRgumBXYepf+lx8XfFeDV+dX35e1196YR5f913wXKparFgzWAJZdFi0WP9aiFvrWv1ZSVeFVQxUIlJcUWpQZFD9UOROQkzHS/tJRkh9SA1IokdyR5FHp0dJR+JG+EUPQ94/Pz0VOFo0UDI3L5UsJSqnJ2wlZiS7ImkihCJsIEgfAx1wGhMaMRlkGEsZnhn5GHgXiBWfE3YRmBC9D3MO1A0yDXYNPA4HDmcMxAqvCbEIdAeMBrYFKAStAokBkwAO/+37Lfn79x73uvZk9hz0+fDY7vbswe1p75Xu1u757iju3O5T7+TuEe6C7Gzrsupn6VXo7uZl5nHmkuY15hHlrOMq4lXhzd7c3BbdO93W3fDd/t3n3Zfc09r22NXWstQA0qnP5s2Ty2DKEcmHxu3EZMS1wuS/xr+uv6S9mL2Avg6/t7+Jv3e+Ob0/vaK9bL3MvsW/479OwZnDqcYoyUvKfcytzlTPZNAMzw3NLs0LzdLL9sk1yQrHrMTSwxzBxL7/vKu667m3uSG567jnuOq5ZLvhvAi+NL6tvcK737q4u4K7ArsTu8y7Or1avv+/i8HywVjDLMVrxl7I/8q9zfLPW9Dl0OzRDdLm0mnT+NNK1M7U79V81TfW59dC2tDdv+BG423lAOe551Loz+cr57bnnuct6ZLqHOpx6hrrM+198Hzz4vUs9zb4mvkY+xb9y/8oAqwE3wZ4CEcLBQ9WEoIUDhZ6F5AZCxx9Hg8hgyL5I0YlDiWMJLMk4yQwJXAlzyUfJt8ksCKaIEUfFB9AH2QfkiDCIQci4yFvIAgeKxwxHBIdeR3DHAUa7hZXFK8S7BBVD04Pug+tD9gOoQ0FDJcK1gl0CsoL8gwvDf8KZQiKBp0E1AIWAeT+avy9+V73bPZ09sr2ffbL9dX1evYb9/P3PPkU+j/6jPr9+rX7KP0a/oz+Qv+U/8T/1gDlAjkF2gaEBxEH8wUmBNkBTgJ/AvgBxAN9BGEHDgpOCf8Jqwp0CjoJewa/A+QCGQE9/0X+hPvD+vP4yvUM9bfz2PKO8yrzGfLG8ULxyvGk8Q/xUfHQ8OLwS/GX8HfuY+167M7sqe2b7THtcOtY7c3rquvi8E/xEPK+8HrwGfO693z6Y/shB2oJbQIvBYoHZAK7+WD1NfR69Lfz3/Du7+HyJPX/8gv3m/ph+b/6bf2ZAe4CYAIkAngGtASlAK8HBgUfATsBwP+KAlwCAgIlAV8D1AYUB9sGVAdVBxME6QcqCxIJHgeYBSAIhAQ1AEz/g/vT+2j7F/l8+139t/3y/jQBQAVJBQED0AUcCF8HMQlpCp4KgAopCUUKGQuKC3wLDwlJBsoEwwJL/9b87vkX+bL4A/em9+X3OvgZ+dX55vqh+8j6ofpl+aL3dPoX+1b6Qfv9+3n9aP+tAqkFrQcoCSELlwuCC3sMDAsYCygMJgyKDIkMvA6uEK8SCBa0FpkYShyuHdEdex1XHY4fYCHdIdkjhCRTJA0kkSLDIaYhXCKkIwckhSQuJpsmQSc6J30lYyV/JbkkziLPIcogkiCwIXohDyEdH+wdDR73HG0bVhvOGqoZMhjfFOMSMhGWET4SvRAqEE4PRw6HDF4KswglCHUIgAhGBpsExQTwAz4E6wPnA7wDCALCACj/Q/3C/AT+iP3t+xv5Y/fn9hD1k/RU9Gb0DfN38/30MfZu+Av5GvoO+jr6yvre+wD+4P4c//X/PwIQApYBMwOmA+kCNAMLA28CGgMFA9MB6P9AAO0AQQDY/7z/pf/G/nX/w/9w/sb82/tR+xL6C/mt9gT1PvNo8hPyJPE78i7xa++g72Dvle1G7Y/ude+S8Mvw+/C18cLyLPNG8rjxhfF98BXvku2r7MbsDu0D7Nzrs+2U7g7w1+8e8wf0le/79Az2j+8k8fH3EPYU8kP3YviQ9oL2xPeF9xL4XPu0/FT/K/6s/wQBTgC8ARX+PQGjAwn+Xf5TA78EswGn/wL/z/8X/9r7iP1p//X9EAAZAFz/dwDh/R8BzwOHAM0AnQG4ACb/TADMAFEAZQHVALMA/AB4AIL+C/9W/9D8oPpb+LX4M/f19LX1MPYc9k/20/Zi9TX1j/Rl8vLx8fDy7n3sRuwL7QLtoe6m8S/0D/X09fX2dPaM9Uj3YvkZ+5r9bABbAp0DAgdsCJ0JhwsLC5oKxQkuCvAKBAqGCWEJcgiEB6IGgQStAkABOv9//UH87vmH9zT30fbM9vP26PW49GvyQPEZ8eXxR/MI88TyuPJ48xz06vUU+IH3D/fI9iT3kvfY98b4rPjM+KT5Gfu9/ML9Hf8vAV8DZAbdCMYKHw02D/YQWRJVFI4W6RiiGiccgR19HksfYyCaIukjJiXrJYomPia9JT8m0CbIJ9ImhCYLJi0ljCaIKCsrYS3QLmkw/jFBMkAyGjMKNC41kzU3NUY1STTcMmgydDGmLzcs2imfJy8khSH4HiAczhmgGBIXQBWqEiMRbA9/DgsPmQ6eDtkN0Q1KDOoKdgoHCY0HIQSuAfX+HP0w+u/1B/VG89zxN/Hp7sTsKera53TmSOTM4sri1OGl33Xeb90a3L7bvNuF2gzZZNmC2Z3al9s124fbrtuC3I3dqd0f3APcEd113kXfH95Z3m3cHNyE3vrdjt1A3b/d+dxW3K7cm9xx3iDdNt3w3TzdaN7L3f/dNt7d303gL+Lt5X/m2+jB6enqbOtn7d/vpu9j8iP0tfVo+Dz5ovuk/2j/KgLOAwgGZAfz/VII7RBtCrMOqwtmDjYUnxHkEu0SThR1EkkY4xl7EUMRLglOC14TrBTeECcOghbnEP4QfQ/qCk4QpQz6D1MNfwtHDiQMgRF2DooMNRKSFKgU7hF4EpkYDRmFE0AVuxmzGvgY7RayGckZDxeVFukVBxU5Ez8TQBRNFL0PTg0FDpcJtAelBLYELwVEAvsBswDI/2v2nPQV91HyE+8D5uvlteSt3+Len9jj2E3UUs5H0DvMRMhUx4jFw8TOxh3FVsGHwFe+/bztu9G7DryjvM64+rj8vDm4aL3kvF2+pMFTuX/BU8DtvJG/P8OXyGjCcsRgxwnIYsblxvrKusxezivOpda01w/Uh9XX14jaOthe2iHeht1t3lzhXuKg42vkSOaN6ETppOw68DXz8/U8+U/8Yv+FAV4HRgzyDOkRmRLnEycXgxdXGwAesh9SI5olhScZKhMt5y9cMPIw7zLYMkkxuzOaMysywjQ5M9g1GzjANaM2GzW5Mzkw1C1bLwQqiSbXKDwmEyPWIUMgiSE6ITkfaiE5IdIg7iFCI0wmhCP0Ijsh3xxfHI8a9RmJGKAXwRVyFCYTeRJhEwcPXg77Cj8IxQlRBY8FGAV+A8EF/QPKA5kBmP7XANL8Jvml+Hn2gfUv89byh/O780jydfIi8SLvw/LL8KrxHfPA8SDzBO+B7xXxF/Bx8h30GfZK9zT4nfn6+VL79v2j/yoCEwSnBHMGNgYBBqUGNgbwB/IJ5QmtDEEQ5hDvEz0VXRTtFPwS0xMYFrUWxxj8GfMcmiDZIdkj5SV6JVwmOShsKPwpqCqGKzIthSxxLZwuIy0xLV0saCnUKC4mZCVbJdsi4iQ9JJEjciMMIU4hQB9KHkwelRzGHUwfmh7QHo4f+h6pHVUbgBrDGDEVoBODEb4Psg9oDlMOAg7RCwsLzQkVCRQIGwf8B1EH6wenCIAHCwh5B/IFuQVNBFMEjgStAp8CzQIQAg0CWAH2/3b/dP6r/hP9X/uI+7f4vvlE+gH6pvvO+xz9V/zY+dr4nfYG8+zy2PD/8QX0nvA98ULxg/Gm777vh/GT73rvoPCt887yrvO+9Ab0Z/PT8WTzsvHl8Y7ztPVf+P366/7u//8BGwNABqwKzA7uE3sWlRhSGPIYLxr6GR4c7ByPHM4c2BqkGMEWMhXXFFUT7xCeD44O8gv9CnQK4gdABjcFCwXhA6wB+wB3AP/+BfwE+Qz3XPRf8S7vPu077m7wpfAb8nPymvLS9Azzju/t7sbtmeuo6b/ngedT5nrky+Vw5rPlRuYP50nmLuWU5JDiCOGE4R3fg9xH3bHaj9m32tnaudum2hXbiNsE26TaJNnZ2EXaotjT1eHTJtAh0KjPOtD70avQrtGf0u3Sw9Rc2HHaVd0G363fv+OX42nhO+DI3cTb2Nry1zjWy9QE05LTP9MA1KjTstRg1DzUTNco193VLdQ+1Q7UktNC1aHTWdQ32FzcRt353irfvN2y3YDesd2g2r7c9d5i4E/hUONV5RXlZedb5q3mXudE56zo0+ho7l7xrfNH+Rr8qP+tALABFQPHA+cGmAeCB0QHVwj5CZ0JSQtCC64L+wxCDqIRuhLqFWsY9xmQHhwgsiKPJPMj4CM1IpMitiMRJKYk3SQcJOwjJiPgIHUgEx13GXwYbBapFZ4U9hMfFC4TQBO5E+MTLxWVFvIVvBSqFQAW9BV9F3oZxhzFHtIgkSInI40j7iJqI6QiyiF2IYUhPSEnIashHiD/H9ke3B1hHREcahv2GRkarhrQGuAYPxkbG7UXyBWiFVUUpxRnFF4UJBYgFoMWKRd1F74XMReWGMkYNhjcGI0YbBj/F0UW3xQgFJ0TlRMFFOwU2hQWFAQTQhL1EUYQbQ6HDV8M8AmAB0EGKwbTBqUH/gcBCS4KUQkxCcUK+AruCkQM1QqFCaMJyQeSByAGjAROBuEHdAl/CkgKmgqXCTUH0AfpBr0DfgL//63/3v/2/fD+rf1k/bP+fPva+uL7r/u8+9f7xPv0+sv6+voW+1X6IPon+tn4c/g89471O/XX8q7wdvBP773vie807p3uje127O3sVe2/7jPvSO0R7LTqxOrB60Lrk+vl6eLpi+ww7wHyNvOv9eb29vaE98T3qfe39pz2DvW789XyfvJH9JX19Pa39+v3zPeF9p31jvVu9ObyX/Kc8kLyc/B18KDvx+4h8Irvx+/I72rwu/GH8D3wnPCu8cvyzfE08D3xH/Kj8QnzMPJn8ZPxc/EY8kfwBPD+8Prv0e/y8H3x9PGC8oXy5fPt9Pf2L/kn+YX6o/s7/O38Iv1y/Xf+o//H/63/nv8dASoCSQLnAt4DJgUxBcoF4AYuCKQJOQrWCo8LoQyTDGgLqQsiDNQLBA0hDhQPIRDuEDMSJxLEEvITRRTaE0gU4xRaFVMW6BY2GYMYzxk7HdkdFiCDH1IgyCFhIqYj4iJkIuoghCBXIJ4fGh+gHuYdVBzoGusY1RdmFp4UShMjEZcOMA23DOsLzAuFC/UKuQkaCLoGjwXFBL8DzgKrAcMAjgDFAP7/Ef5H+5j4Z/fD9i/2tvXg9PzzO/RY9O70b/U+9JTzh/L18DPwf+/+7tTtAuz762rsyutK6+Ppq+dE5qPl0uXm5T7lZuW55Sbm1+Zq5g7mYubf5gfo6eg76bnpsOmS6hPs/+xn7iXvPu/j71Tw6vB08kD0+fVy97X4hvmy+UT6m/qJ+nb6Svop+gb6Zfk3+LT2iPW/9N/zD/Rq8wXzWvPx8n3zP/O083H04fOJ8xrzAvPx8vrzlPPQ8YHxXvDW7pjsp+pe6oHq+OpS6xrseO0Z77vw+vEU8zHzLPNQ84vySPL18snzePTA9Mj02vRU9Hfzn/Ji8pDyYvIx87fzKPTG9HH0gfSe9ID19/Z5+Dn6dvs3/B79r/5r/4MAcAFrARkBo/+o/x0AKABqAEb/df2N+w37a/uP+oL4T/bO9MPzQvMZ8y3zqfM59LP0xvVv9w35lvn++fH6pPuO/Oj82v2j/nj+lP4z/w8BiAHoAHYAwv9s/qP8UPvo+lj8U/0d/kT+MP4S/wAAMAJ+AwQEDwVPBoAH0gcfCJEIGgneCakK5go3CwgM2AybDT4OzQ8wEacRehKMEpESORNpE+sTVRTvFNIUuBRkFS4VuxX5FUkWwBYnFo0URRMnExgTWBQVFK0TIBRZE4ITeBPTEywU7xN0FD8U0RJ3EWAQiA8aD/cOFw9wDqkNTA2ODFsLbQqzCdcJAgpNCXQJegk+CokLnAttCzcLwArGCV8IfAYuBSYE7QI3AfD+Zf1t/AX8B/vQ+Yj4TPdz9p30NvNs8cHvVO8E76/vZ/DD8b/ziPVq9zP4Afhb9/P24Pa19of2ofbE9o72ofag9tX17PMt8jvxMPFr8kHzCfQi9fP2OPr9/AP/DQETA1wE6gS9BagGXAeyB7wHWgeqBjEG3wVABqYHOAilCMgJSwlsCNYHEgfgBhgGcQWjBigIhgmACx8MPw1gD5YQshEJEsMRRRH/EIsQPRCFEEEQixC1EKcQmhCDEE0RVRKPE2MU/hR9FRUWhxewGG4Z1hmaGUEZxxjmGDUZ6RgQGQAZbRh7Fy4WZhXuE2cRnA72CwgKTAgfB+UGSgb9BBgDCAGx//79tftB+iL5W/jZ90b3Wfek9+r3PfiF+GH49feM9zD3vvbE9br1UPbW9sj3z/j5+UP6VPpn+kT6D/ut+8j7v/zN/ZL+Kv90/4D/H/+b/+D/yP+LAIkBzgJ8A3QDkgOaA6gDBAT4A00E6QSdBGEEdwOsAXQAH/9R/QL8XvsZ/HT9m/5kACwBdQIBBcEFtwbcB28IKAu2DKYMDQ0DDhwSCRRmE8wTGxJ+Em4VuxawF3sX0RebGWUaIBvIG+Uccx0QHfMdvx45H9IeOR53Hjwf5CBOIi4kfyWbJtcnBSj9JzAnAybkJHAksiMWIyIj9SItI5wiMSLZIdUgiCBsILcfah/PH28grCGXIjgjViMuI0Uj2iIYIs4gsB9QH1EfSh/oHvseMyDRIbYiHSP8IkkiJiLOInEjriOWI6ci/yD/Hh4czxhZFWYSZhAED/QOjw+1DyUP8g2bC/oIKAdrBZEDJgED/6z93vvz+Qb4qPUr9KbzzfIZ8svwHO/Y7Uns9+pk6ZLoTujV5zPosejB6Wzqo+oK6lvoxOaz5OLiEuG332neBd0e3BDbP9p12czYlth+2GXXK9ZV1WzU6tN/057TaNMi01nTi9Ps08fTKdNp0lrRO9Cnz8POzs3BzFjLP8oQyfTHK8fXxr3GSsZLxWnECcSjw1fDMcPIw/PEVcX2xK3DOcLawW7CusP+xM/FJ8Zdxo7HbsjiyHjJU8kjyVHInsZ1xfLEbsQqxK7D18KEwvrBFcHFwOjAAMH3wF3BcsEKwVnBw8FOwhjDYsNFw3jDMsSixAzFoMUWxn7GDcf8x1bJ08rdy1bMkMxwzJvLFsviykfKIcksyNbIMspuy0zNY8870TrT7dSX1jjY69l13DXf7+GB5LfmGOkh6+frK+3k7i3wyPEj89H0JfYT9z/4+vg3+i78/f2d/0EBlgIfBIEF8gUAB/gILwtjDU4PjBEQFLsWGxmwGiwcgh2QHggfwR6dHm4ecB5JH0cgdiHzIRghlSATIM8fVyCFIFYhXCKMIzYlfyZZJ3wnoScvJygmciV/JP4jMCSiJG0kuiM0I3EijyKHIschUSEpIfIhOCKFIScgex4uHXIbqBmKGBwYMhi8GF0ZKxqRGn8aVhomGS8Y5xd/F2gXghfoFwwY+BYcFRQT6xCADocMYgv3CoYLIAyjDG8NTQ7nDjoP1g8KEMUPmA5mDasMlAt7CuoIJgdABUUE+AN3A3UDWwN/A8cD8QNkBLoE1gSGBAUEfwMFA3ICewHmAAsBbwFQAagA1f9T/w//+P7x/tn9If0m/cL8Lfy7+kb5oPi5+Kz4BPhF98z2yvb39kj3qve5+Nn55/oa/Fj8bPxu/DT8y/u3++f8t/6qAP8B8ALcAwYFowZGCIUKowxJDgsQvRFDE6IU2hV3FjkXWBj8GDMZdxlfGhAcFB6sH+wgqyLrJFgmxyb4JuEmFic/J0cnwCfnJ18o6ygpKRwpvii2KHooJihXJ1gmoya/J00oyCfbJq4lUiRiI54iMSGsH+8eqx4yH74f6R9lHzceqB1OHV8dkR3THEUbLxkVF3gVIxQ7E9ESSBISElkS6hISFC0ViRUhFaEU/BSEFT4VxBRaFKsUjRWxFfEUyhOOEh4RFA/mDAgL4QjWBoQEWQJXAbwARQDc/8//+/+QAMUBhAJPAi4C9gKDBMsGxAjGCWUK4wvzDaAPQBGuEroUlxfUGfsaFRw1HR0e7h5xH/sfkyCFIW4iAyOPIyQk1CRqJfAlZiZFJ4EojSnnKVwp6CgtKbgpOipsKmsqoyvTLSswJTJiM080ejQBNH4zETMOM7wzajR4NBs0VTNLMhcxgy8YLkgtxSxRLKcrYyopKPglpiSBI1si9yBlH0Me7xxUGxgaxxi4Fz8XthajFQwU8hEWEPgONw7XDYcNUA2JDI4L6ApPCuUJ5QjyBm8EngLUAZkB4QBx/yb+tvwy+1r5ofZy80nwke0Z7KLq5Oi35yjmfOT44rLhzuD835DeUdwA2m7XutQa0kbPisyuyfnGhMQKwoO/G73sur24Z7ZYs+mvxKycqq2oNqbmpEKjo6HBoVeheqAyoCqgu599n6WfmZ9dn5GeaJ5wnoCejp40nYiclpxHnPybHpv0mjqbO5vXm/ab5puFnPGdt59voXijvaSWpfGmzaiVqtarjaw+rKyrpatRrCKtPa62r4+wA7GusRGyk7Lhs9i0H7ZFuE26JLw2vrfAUcO4xXzHhMhryf3K/szCzlfQDdI91DHWsNcn2XvaI9w13iLgwOE944HkBuUA5XTkkeNA44TjuuOe4yfkSeXQ5i7pa+sq7Z/uxe+p8E/x4PHI8hj0KvWp9cT1N/bi9rb33fhe+WP5o/l/+ln7uftF/Pv87f1//4sBlwNjBRAHVwjdCOgIEgkRCXgI4gfYByYI7whrCYYJ/AmfCW4IGQcHBpsF5wUrBwYJZgvYDs8SYBanGX0cwR5xIMQhTSPPJG0mwSeVKFcpECoEK4YsdC77L28xbTPmNSI48znPOzA9Ej7WPgFA2kHoQ85FvEZCRy1I3kk0TAlOtE+cUXBTFVWPVkBYEFrZW8JdfV8FYathRGHTYC1hL2K8YhljSWOUY8tkG2YnZ9ZnI2j9ZwBn5GXIZCdjGGG8XlFcSFpaWKZWIVV2U/BRolCET4hO2k3GTSZObU43ThBOYk6BThxOUU3zS2ZK4EgeR5JFRETSQjRBXj+OPdM7Hjo+OH02WDVyNLMz8jI5MpYxQDAwLtMrNClVJmUjwyBqHowcrBqyGD0XDxYcFRoUPxKMD18MwQj1BJEBvP74+x75uPYf9bjz2fFs7zPt0+p56NvmMOWn43Hi2uBO3xLeKd0U3U3dOd353IPci9yc3Uvf++Bn4rfjyOQo5pLnwOhf6SfpSOn+6T/r0eyH7sLw3vLJ9PH1zPay9yX4JvmB+gv8iP3d/rMAJwJ7At8BJAHBANYAdwHmAUoCwgJWA+UDhARvBSYGewZNBroF4gQFBB0D/gJLA4kDVgTNBFEFcQW5BNsDMgOeA30EiAXtBTUFZQQrA/AB8QCL/3b9p/tW+lv4gvYS9P/wue7w7Azs6uok6a3nf+aA5WDkFuOQ4Rngvt6w3MraDdq02VzZY9mX2cvZdtli2DvXw9Ul1NnSztEC0VbQ7880z7fN8stkymzJ28ipyBXINMcLxn3EFMO1wTPA8L3Iu0+60blXusm6t7sHvTK+JL9dv4G/sr+XvyG/wb7nvma/Z8DQwX/DIcUVxrHGQ8eOx13H+sbrxvLGzMYRx8LHZsgnyW/JlsmRya7J1cozzFvNGc4uzwbQH9B90ETQ988u0PDQM9Ju00LUkdRK1QzWetbA1tDWttbG1njXhNgQ2YnZh9p925ncqd2y3prfleAA4lPjb+R45eDmZeiN6UPqo+qx6sjqn+sY7dju1+/l7yDwqPBu8Wryf/NM9Af1R/aG90z41PiQ+Y76XPvL+9f72PuK/IH9lf0g/ZX86PuE+3n7RvvY+p/6avpE+m36mvpb+rv5+vhb+Dz46Pj8+eD68Ps3/VD+wf6w/gL/uf89AEcA9f9A/2b+pv3S/D78rvvx+qL6YPq++fn4b/go+OP3Ffi1+Dn5jPmK+XX5hfnW+eX5ZPms+eb6aPyu/c7+ZgAQAssDiwXlBpUHzgclCKEIuQknC8UM1Q7XENQSihSxFVUWDhdXGOkZlRtJHeoegiB4ImckGCZjJ8EnyCciKA0p8SmlKuwrby3iLq4w0DLGNKw2lzjpOfg6fTtAO946pTq0OgU7ijuzO5U7yTsFPEg88TxUPSI9Fj1nPcs9zT1APcQ8eTxKPGI8ETw3O5I6ijrpOgo7dDqYOQ853jjoOOs40jgZOM02ejWWNHQ0ujQZNVE1pzQYMzYxZi9pLk4udi69Ltku0C6+Lg0u/SwXLFIrjiqVKTQpVSlJKScp6yjcKHAoiyeyJhAlpiJXIBQeVRwyG1QaEhpKGrkaCBv4GkUa3RgGF4QVdBRHEw0SSREREbcQfhAdEEUPbA6sDekMuQuhCsUJCwnRCLUIzwj4CJMIKgg+CD8IcwgUCccJSwrOCqQLaAwIDU0NJg3XDIwMjQyxDMcMvgzIDP0Mkw1oDlEPmBDEEd0SzRMXFQwXixjLGUkbIR0WH4kgiyGbItwjgiRGJC4juiFpIOEeRh3IG7MaThqqGiIb9xoRGhgZiRjDF68WTxXhE50SMxGVD5gN0gt9CgAJSAc6BZkCSf/u+yL55PY89SL0Q/NX8hnx8u4f7JHpNecp5VHjiOGV4AHgPd9E3rbdFd633t7eMd7z3CTcmtuE2kHZ9Nd61hbVz9O00ovRedD8z2jPg87azXLNPM0WzXPNYs7bztrOrs5izinOh81NzM/K9cg8x5TGr8a/xo3GBsa9xfLFZ8YTx6fHKch7yNbIesldysvLZs2XzsDP2tDJ0ajSeNNg1DnV7NWj1oLX19iX2m7cLN4+32TfQt8130LfYN+N38HfRuCI4aHjpOWu5mHnd+ge6qfryezb7TXvtPDd8cryuvPB9FL1G/Xo9Pr0SvVl9qL3mviR+VT6Evuo+xT8G/wp+5T57fdQ9tH0tPPf8mzyVPKB8rPyyPJr8w30x/Oi8v/wke+R7i3uUu6S7rDuke5t7tLuGfCS8X/yBvMA897ymvNb9Lz0EfU19Sr1/PTV9OP0RPXu9VT2TfYr9ij2PvaT9n/3Lfgy+Aj4M/jL+Ez5SfnL+Ff4hvh9+YD6M/ug+7n7+vuo/IP9Pv7Y/mP/9P+YAFAB6QGZAmIDJgT1BIYFTgZhByoItwhmCWsK5QvhDSwQBxMmFvgYYhugHVEgsiIJJfYnaSqNLIYuXjBCMtozBzULNow3fjl/O149Fj91QH1BSkL5QvpD80TwRdNGUEf9R7BISUm5SbFJlEmySa1JCEkcSI9H/UbhRdpERETGQz1DPEIIQRZA5j6wPZ08UjviOY04Xje9NS0zKTBgLdAqsiicJrEkZSPmISggWx4iHKIZLxdSFQ4UpRIvEccPBA4YDGEKoAjfBvIE9AJWAcP/Hv5d/Kn6Svk1+DD3uPWL89bwCO5w623p4ufm5dPj/eFU4CnfBd4B3Wfc3dvq2nLZbNgh2HfYJNlv2WfZ5thE2KHXtdbQ1bjUqtN603bTxdJO0lXSldLl0rfSi9LO0nvTj9RB1YDVA9bt1gLYLtmK2qnbONw/3K/bHNuD2hzaG9o22n7asdoG213bhdt52wfbXdrP2aXZs9l/2YDZ4NkN2lnarNrh2lHbJNxj3WreG9/y32bgYOA14Nrf098A4Ajg499i39Head4p3pHeoN9g4M3gWOHU4WXi2OKl4tDhvuAR4PDfL+Bz4KzgJuFw4VrhReGI4V3iw+Oy5YTnmehM6Y/p3+il54PmfeX344HiJuJN4szi2uMs5a3mDOgU6ezpQOtA7abuM+9e7xDvJ++/7zHwovAs8d/xnPJR8+nzevQF9WL1j/WP9Vf15vTM9Eb1Z/W49OnzSfO78mPyDfLA8dnxufF18WPxzfHN8i7zE/NK8+zz5PQU9mL3tPjQ+Zb6O/vJ+2n8CP0B/nr/jAAlAcUBzAIbBHIFwgZMCHQKsAyCDmIQlRKuFIQWURjBGZsaWBtzHOAdbh/3IE4iQSMMJN0k4SXWJkYnoCf0J2UojSnUKvkrbi20Lr4v7TA8MogzoTSxNSA2DTZrNsE2tDa3NhM3nTc9OPA4cDnlOdI6DDwlPQo+9z7fP6dAR0FIQYtAOT+NPeg7ezp7ORo5NDkpOb84NjgUOBE40jd6Nyk3vDYdNpg13jTDMysyLjBTLsgslCuSKoQpGygsJgIkQSJCIckg1iBEIYMhqSF4IesgSSBZH2oeiR36HJgc2xvYGowZCxjCFhoW6hXYFeIVixalF4AYOhmqGfAZORoUGp0ZxBi6F/cWVxZ+FXgUQRO+EZgQCxB3D6IO8A2TDYUNSQ1EDLQKHwm3B14G4gQUA/8Au/7e/Er7ePnN90X2avW99Ub2R/b29bj1bPX99MT0rvRt9Bz0kPMc8wjzivJz8XXw3e8e79ftcOwf693p0+jC5+zmdeY25h/myuWy5dflW+Wj5Dnkx+Mg4w7iu+A538/dIt3F3FXctNvy2nPa5dnw2MfX9da81mzW1tWT1ZnVydVi1uvW5dZ91hzWH9Z91tvWWtco2ErZvNpA3Gfdet6M3wzggOCm4EzgiuA84e/hoOIa47/jseTF5afmB+cg5zjnnOcS6LnnkOZm5X/k+OPh42TjR+IC4TngO+A24BDgMeCC4Mzg9+Aq4VrhS+FV4WPhNuE14UjhveEg45flXehH6kvrsuvW6x3sEOxr64DqWul56CPoOejL6InpYOr26kTr/evv7IXtru227XPuru9w8J/wXfD574nvP+8u7z/vxO/X8Jby7PQ+96f5ifx3/yMCWQQBBjQH+gfCCLMJjAo8C8ILiAy0DRcPmBCiESUSSxKMEvcSKhP0EmMSSRKmEj4TzxMvFPEUTxblFygZLRryGoUbDhyYHEAdeR2dHSoe1x5lH1wf1B78HcwcwhvXGsYZKhkcGTgZnRkFGmQaBRt0G1wbORt1G64bYhv7GrwaKBpoGe8Y8xiqGYMarBo9Gs8ZfRkCGQYZiRmJGS0ZuxibGKUY+hf8FhAWPxX7FIYV2RadGCEaQxv7HNgeHSA3IU8iHCNBIwkjZyKeIUMhRCHsISgjNiTZJAAl9SQlJWglXyW9JLgj6iJnIhwiTyKLIjMifiGZIKMf6B5DHo4dxxw8HDsclxxaHaQeEiAWIaghGyL4IgYk3iSrJaImpycwKB8o1CeGJ1gnyibAJXwkQyN3IpwhpyDFH+EeEB46HVYcDRuKGT0YDRfGFZAU4BMmE4kRqA+pDr4OLA86D+sOKw44DdUM5wz8DOQMawyLC7YKPQr3CRMKdwqnCtwKRwtXC+wKfQoKCikJjwe2BR8EOQNPA5cDoAOPA2EDLQNCA80D9AMnA8kBSACM/pP8Rvq298j1q/S+84nyZfHG8C7wdO9T7jfskemI52HmtuWd5F/ihN963LnZxddO1gLVytOy0hHS5NGa0f/QT9DzzxrQrtAl0V7RaNE20TnRNtEn0SDRz9CR0GzQNdAE0LfPbc8Xz+nO1s5EztjNRs73zl3Ps89j0FLRQNK20tbSVtM31IzV59ZF2OXZVtup3OPdg9+64Y3jm+QY5VLlqeWL5lrnHOin6SHr+us+7Pnr7Ots7Bftte3t7Zjt7OwU7MTrKezJ7IrtOu6a7ozud+7A7unuAO8A74nuxe3X7MrrjOqw6UHpv+hj6DXoVOjY6Ajqt+v87NXtqe5P7+XvUPD97/nuBu6J7T7tsuzx62Pru+qH6uHqN+tv64Lr6evO7N7trO5Z7xTwF/EX8pPyyfLE8mfy5PG78ZvxVfEu8QXxc/GE8i7zofM89Dj0jvOu8srxBfHy79fuxe2y7DDsPuwV7VTuOe8V8P3wr/Eb8qjyCPMd8w3z1fIC8zzzRvNg89PzUvST9BT1oPUj9r72ofcb+er6v/wn/kb/owDGAZwCQwN8A3YDdgMlA44CTwJgAgUD8AOQBGEFGwaXBgcHGQfxBlEHcggGCgsMTg5CEK8RchLbEtcTahXaFugXphhUGeMZ8hmqGWEZhxnIGZoZYhmJGc0ZmhlMGaMZjRpqGyccFh1JHnAf+R+WIFQh/SHVIiAjxyIIIiwhjiAXIJAfHx9bH1MgfSE0IvAhPyEQIUohmSHnIW4iDiN5I8QjuyNfIwYjmyLgIVIhzCDEHy8esBzeG5MbexvqGqIZKxhEF+oW0xYJF+0WNhbbFHwT0hIhEkMRbBCPD+4Okg5vDmwOLQ6iDQANTAzJC4kLYAt/C7sL3gs7DO8MfA3eDTwOSA4XDu0N2w3bDW0ObA8hEJ0QzxD/EG8R6RFiEssSHRM4EwMTqBLEEqAT8hRWFpAXfxjbGLgYgxhpGGUYhhjUGGwZ4hkwGskadhsIHIoc8xwzHWQdRR3iHH8cSxxlHH8chRyKHLcc9RxbHekdVB78HgMgUiFyIpIiuiGSIKIfPB8+HwIfnR6eHuceaB9VH30eXx1NHKgbARs7GvIYRReIFYgTERIYEdUPFQ7+C/8JIQhDBkoEJQLr/+n9S/zD+gT57vYO9TH0nfO28pfxJPCf7uDsIuuw6Y3oxucA5xXmNeUP5Lri2eHH4fXhjeEF4Xvg89+L3zbfjd+Y4NvhtOJE4zrkVOUc5n3mReZA5fbjLuMB4wnjX+Pk4y/kg+QW5X3l4eU55iDmA+YM5jnmouZJ507ohuly6nTqxOkk6TPokOa/5Bnj+eFs4angjN+r3n7eqt6S3izeXN1i3GLbUtqr2YPZpNkQ2nHa8NrF21ncwNwN3SfdX92K3cPdZd4Q37rfb+Df4BHh8uDX4NngfeDF3zffBN+x3nve2t5c37XfuN823zfeBt0J3OHabNnx16XWfdVy1G3TYdKr0YPR8dFm0mnSXdKW0hzTS9PX0gfS7dDFz/TOAM9nz7bPDNBl0PrQndFB0vvSc9Ot0/DTHdQ41FXUDdSF0/jSmtKx0rnSQNLr0UnS9NIx00DTWNMw01zT89OJ1OTULdWd1SnW+dZr2DPaZNvm2zPc4twS3i3fsd9l3zrf898I4TzileP95InmYuiE6t3sUO+M8Wbz5fQ29t/3wfmU+zz9Xv4o/9r/tQDvAVMDZARBBR0GsQbfBiIHDAhMCVAKEAtrC5cL7gtoDBIN1A17DgAPrQ/BEE0SShReFtEXkRgyGfcZuhpcG+0b1RxmHiYgSCHaIXQiYiNlJMYkaSSaI44ieiGGIB0giSBYIekhNyI4IjAilCJ4I3okwiRqJF4k9iQkJmAnciiNKUkqcyo9KrYptyi0JysnDCc+J68nZCgXKdIpnyonK4QrJywlLdctQS7CLm8vXDAeMdsxHzOpNII2cjhJOkM8HT5XP8g/iT8SPyU/oT8LQJFAEEE3QXJB8kFyQtNCNEMYRHdFzUYYSFZJvkreS3hMHE18TcBNIk6BTuZO005sTjpOSU6pTv5O7E5qTsZNRE0JTQNNEE3aTA1MMku5SipKQUmDSN9H7UaERS5EfkNAQ/ZCcUISQghCA0LlQaRBeUFbQS5B70CRQDRA3D9rP+Y+ND5HPR08HTt5OtM5Njl6OH43EjbuMx8xTC7MKzopOCcSJu4kgCMEIqsghx9LHsAc6BqcGD8WkhOoECwOygusCVMIjQfCBtQF1AQhBOQDhQP2AvQBkwDu/v/8XPvP+Q345fXH8zjysPDk7gftDuv76AfnB+Ud45rhBOAm3ifcO9rX2GzX8dX11DPUjNPH0g7SuNG30R/S2dKc013UK9WR1XHV9tRL1HPTXdKG0TDRAdGV0B7Q1M/Rz8TPg8/TzmTNnMuzyfnHpsbmxSXGAMc0yEHJ9cnmyubL68zqzVbO880ezaTMPc1YzvbO6c7mzsLP1NCF0dPRgtHo0B/QTc/LznrOEc5jzY7M/Mtuy97KqMrFyjjLbMsAy2jKCMpByi/LVsxdzTTO5853z9/P6M/Qz+TPx8+Nz3rPe89Hzy7PjM/8zz/Q+M8qzz3OPs1fzOLL9ctWzDnM5cv1y2XMe83eztnPPtBj0J/Qy9AI0ZjRL9Lb0k3T8NIc0mrRDtHV0KbQgdBd0F7Q6dAB0jLT9dNu1CfVMdZX10vYq9jT2EfZ39m62urbNN2F3s3feuBq4DngD+A74P3gAOJN48/kYuaa5wjo9+fM55HnNueq5gnmjeU05VHlC+Z95tjmm+fo6JXq3eu+7P7sA+1B7b3toe7B7yfxCfNP9Y33pflv+079zP82AhsEjAVkBgAHuwc5CM8I5wn9CpILsQv2C24MzQzuDOUM2AzCDLwMCQ3xDFgMAAziCwMM3gtJC9EKYQorChoKtgkkCccIJQkjChYL2AusDH8NgA5HD8wPoxCVEd4SQxQsFbcVKxalFlsXLRjQGCMZGxkbGRYZFRlaGdUZQhpHGlsarRoFG3cb3xsSHMcb2RrwGWUZxBgpGNkXFRjxGKkZ1hn1GTEaGRqaGdgYDhjiFj8V/BOgEg8Rvw+QDrwNWw1aDTwN1wyaDHgMLAy+C4kLrgvyCzcMZwxiDHsMyQwHDWcNow1WDfEMtgz0DKsNFQ4DDm0NfQyFC0EK+wgACC8HkQYiBgQGIQbdBfgE/AOiA/kDOwQMBLwDlgPDAx4EeASWBIIEjgRZBLgDOQP5AvQCGQM5A1wDNAN5AtoB2wFIArACzgLqAhwDZQPvA4kEHwXfBb8G/gf7CUcMRA7aDwgRJxKcEzsVjRZMF3oXeReUF6UXoxctGHgZ+RpKHCQdpR1nHmsfdSAFIdkguyDEIMggEiGcIQQiBCIAIh8iNCI/IkMiYSKnIv0icCNuJMQluiYrJywnzyYXJmolDCXmJAUlPCW4JYMmJCd5J2onFCfPJpkmAiZEJbckByQ2I58iSyI/Ik8iMCK3IYkgAh+1HTEdih1qHWMcbRscG2wbuBuRG/wahBprGlQaDBqBGcAYJxjlF94XuhdhF3QXbxjDGZIaCRtAG0QbShvuGlMa7xnzGX8aVhuJHNId1x7pHyIhFSKBIgoj3CNfJJEkeCQDJFUjiiKeIUAgyx7xHZIdUB3hHJkcshzqHH4dfB54Hx8ghiDhIBwhYCEbIjojPSSzJNYk/yQGJaUkTSNQIWkfsx1+HE8b2xmcGJoX0xZgFiIW8xWjFcIUPhObEdAPqg2pCwcKvgicB3kGOgX9A/kCwgEMAFf+8fyV+7v5YvcD9YnyCPDM7RHswuo+6Vbn5eRP4jHgk95Y3e7bQtqA2BDXuNYZ12XXY9fg1g3WMdUc1N7SidFo0LPPLs/WzlvOgc18zD7LmskMyMbGJsXswrrA2b4JvZ27vbrsuSq52bj4uB251rghuCu3C7bitP+zX7PGskqyxbEbsWOwha+Qro6tp6zLq6+qQakHqEanmabQpWqk66IpoqKhGqGfoI2g26CkoSKj5qTSptmoGKtfrZCv4rGzs7W0VLXXtWy2MrcQuAq5Vbrlu229Bb+OwH7BS8JHw2HEzsVkxy/JgMvbzdPPgdHj0jvUfNU01p7W4daR1rDVwtQT1APUrdRb1drVotYz2FDaDdx33RrfBeEB467kPebB5w/pWOqV66vsYe0Z7iHvJPAi8QvyGPNA9CL1C/bv9n73Kfgg+UD6XvtI/GX9uf6+/64AlgFnAj8D4gObBOAF7AdnCnkMoQ3WDXYN5wyUDH8MEAz+Cr8Jtwg5CDEIQQifCHcJhQqoCycN5Q68EIoSDhS0FbIXjBk9G6IcCB6IH7sgAiJSI5gkHCb7J0kqmSyeLnwwTjLwM3M10jbmN/I4bTqLPPQ+PkHqQgdEIEVsRqdHMUhnSJFIoUjOSO1IV0lqSsVLy0xlTehNbE6zToVOR05RTotOD0+YT+ZPmVCFURNSm1LGUi1ScFG5UNlPCk+lTs1OT0/YTw1Q1U9nTxdPzk6MTmVOH07BTSJNUky2SzRL40pdShNJVEdBRWJDHEISQQ5A8j4bPt89wj2UPVA9eTxWOwM6bTjLNhU1kjNHMjcxXDB6L5guii0HLJ0qqiktKTMpRykoKWMoDyfbJdEk7CNOI/kiviJpIrQhuSCRH3ceeB1ZHGcbnRryGacZuhn+GZQaFBv+GgkaTBiOFk4VaxSTE+8SpRKIEiASVhGEELcPLw+8DvoNMQ00DAAL/QkJCQ4IGAdKBpMFygTwA00D7wJFAl0BIgDL/sn9J/3B/C38jvvS+if69/ku+U73Y/Xv8wPzOPJ48fjwtfDa8KHxrPIb8+PybPID8kfx7O9E7pnsN+vN6WHoluey59Dna+cA5xXmdeSx4jfhXODc30LfS9793AncRttI2uHYHdeE1UbUZ9OP0nzRZ9BKz/nNlcxKyxDKFsk8yD3H6cX4w/LBZMAfv+m9v7zIu7C6C7kxt5e19LMusmqw2K6CrSus56quqcCo/Kdepw2ndKZ+pS2kEaOfolWiA6KpoUChtKAMoJSfX584n92eWp4UnkOeuZ5Sn9SfqKDnodaioKO6pEGmMqiSqv+sGK+jsMCxDLNQtGK1crZ2t4i4lLlxui27BbwivVK+bL9MwErBB8P4xN/GyMhzys3LBs3azizRONNU1cfXNtp73HnegeDm4ljlhueB6XPrVu357pTwZfL28xz1C/bD9mv3TPh5+cv64/uu/DT9JP31/In96f4mACIBlQJOBBwGngeWCEsJpAn0CVYKfgrTCkULMAy/DRQP/A9yELwQ5BCZENoPqA6LDf8MxwxwDEwMmgwGDWMNtQ0RDi0O/w3aDZ8NhQ10DfcMnQyYDOQMag2yDZQN/QxdDOILgQscC5MKjwpQCzMMlgx+DIgMxAxHDd8N2A2zDe8NTA6VDrkOGQ/SD8sQChJ7E+4UTBZ4F5sYuBmsGlAbcxuLG/gbtRyaHX4eIx+xH6ggEiLgIwEmRShaKngsty6tMIQyKzTVNcQ3aTmKOnI7TTxBPY4+GEBMQQtCikICQ7BDa0RQRYdGYkcSSAVJ8UnQSj9LZkufS3ZLVUugS5JM303fTmhPrU/rT8NPU0+JTmVNcUz8SxpMFUxaS3ZK50nDSdVJVEl2SGtH60UhRKVCsUHsQEFA1D+6P24/8T5bPls9DDyVOiY5GTgaN5M1HjQzM94ynDKhMQUwWC7tLHgrcik4J0AlryOwIvMhTiGtINEf7B79HcYcjRs2GqYYtxZoFN0SuxE3EM4OwQ2NDNsKPwm1BwMGiwT/Ag8BNf/R/f78mvx7/K/88/wU/Tj9N/0n/RL9vfxb/Av83PuK+6P6Nfpt+p761/oH+1r7e/se+676dPo8+tf5PfmY+BT4b/eT9pr1zvSD9Dz0mfP48tzybPMH9OzzL/Pj8XjwIO847fzqt+ig5knlSeSC4+biX+LU4f3gOOB+34neUt1h3Lnb6tpv2kXaFdrR2WPZH9km2RDZ29hv2LvXztZg1czTaNIM0WfPe83by7LK6MkpySbIv8YoxbTDiMKjwbLAg79Jvli9rrwFvAS7u7mjuAS4lLcAt4W2BbYQtc6z7rKZskuy7LGysfexo7Ias0yzs7M9tJ20hbTgswGzUrJMsrey7bLUsr2y8LKKs0y0qbS1tPe0k7WFtli3Nbh7uQK7m7z3vSi/Q8AGwT7B5sC3wCXBA8IVw+3DWMSKxNLEdcU9xv3Gccd0x5nH58c5yJzINckByrHKNMtuy1rLc8v3y3vMs8zgzNXMdcwszOnL98uqzKPNhs4Iz1jP38+80ADSctOw1L/V39bZ19HYL9r025/d0N4J4CPhH+Ly4jDjR+Np47rjVuQU5aLl4OUw5t3mCegz6THqeOsE7c/uxfDb8tL0dvb+94L5x/q5+7X8hv1T/qT/DAFBAmgDugT+BQQHBwggCXUK5Av/DC8O/A+kEdoSRRT4FR8YmxrYHLMeGiCFIbQisSM0JSgnMCmjKgkszC2HLxMxRjJBM9UzNDSUNEQ1fTbRNwQ56Tm+Ook7ZzybPYg+Ez9rP2U/aD/sPwxBxUKeREVGuEeiSOVIBElvSfpJb0pPS2pMIE20TUZOr04uT+BPYVB9UC1QkU9eTw5QNFFLUlhTm1T8VT9XO1ixWM5YHFnFWWBalFrTWl1bKVxKXTxeqF7RXhRfzV/yYNhhJ2JPYuBigWOzY6BjSWO/Yk9iCmLXYZdhPmEYYVZh42F6YkZiL2HWX8leLF5KXd5beFpcWcRYfVhaWEJY6VeLV0pXu1bUVbZUY1PyUXdQbk8CT4VOtk0eTbRMBkweSxBK6kiXR/ZFNkSkQjVBtz8gPjg8GDorOJk2WTWINDM0LTQNNFMzujGoLx0uCy3eK2AqbihSJh0kQSLcIJQfkh62HdEc5BujGroYZBbYE4YRoQ8SDqgMMwvlCYMI/ga9BZ4EewPxASYAcf5e/An6w/d69TLz0vB77mPsfurd6Frn6OWU5EDj1eHT33rdIdvM2BHXUdU00xDRKs+4zWzMMMvSyU3I6ca+xabEP8PBwarA4b/1vtW9qrxiu+25Qrijtmq1V7Rbs4CyYbHNryauA61SrHCrLqqFqJOmzKSNowGjwqIzogahe5+3nbqbopmVl7CVj5NZkWePsY3OjPeMuo34ji2QwpDHkE2QwY9kjyaPX4/oj7GQ65Gwk6eVNZcXmJKY5JhlmTaawpokm2Gbxpt3nDadNp4knxugXqGPooCjS6QGpeSl4Kaup7ioMqoHrM+tDK8gsPSwXrHQsUGy7rJVtJa2JrkMu3+8270NvwnAncDBwODAZMFqwkjDpMMdxNnEtMWjxojHlcimyWrKHMsNzELNV87tzkLP2M+60KjRVtKT0rLSDNOQ01HUidXk1hHYB9la2fbYCtgt1ynX8ddK2f7asNw63lbf59+e4LDhA+P4423k9+Rk5d7lxOYZ6InpwuoA7PvsYu3t7cTud+9V8GTxr/J49GT2Dvi7+dr7Qv6IAIYC2gNtBPQEsQXuBosI4Ar2DZcQmRKfFAcXlRkMHKkekyF/JFYnXyqmLeMwqzP+NYc4KTujPeQ/i0ErQx5FIUekSKNJsEquS2xM00zcTNdMQE3fTWtOKU9LUH1RFFJQUmhSVVImUsdRwVEjUplS71LhUr5SbFLeUVdR0VBhUO9PYk/qToxO0U3LTKBLh0rRSVxJCklkSH9HvEYhRntFXURCQ25C7kG2QWBBNEH3QIBAA0B0P7E+1j1EPRs9KT3YPCM8ojvNO6s8Yz2YPbE9+D1rPqk+qT5vPjk+ez74PjU/QT+lP2BAI0HUQXRCBEMiRGpF9EU6RmhGmEYTRw5IQUn0SUJKZ0qiSuBKz0qJSi1K1kmCSddIxkfwRqFGVEabRZxEqUPTQgpCd0EgQXxAMz+8Paw8+TsuO046QzkIOPs26jV7NOAysjGOMAsvtC2zLOQrOyvAKoMqTSrsKWwpryg2J4AlLCQ4I3UiLyGlH0kerBygGjAY4BW4E60R7Q8zDngMrgrLCBEHnwUkBDcCFQDs/an7vvkx+Pb2B/b69ObzGfMe8o/wqu7o7OvrQ+tN6hLpiOcf5vPk0+Ow4lXhw98i3pncM9vO2TTYmtbs1NHSMND2zIrJVsaCwwbBvb6RvIG65biktyG2ZLSUssWwLa/rrbasa6sqqt6ouqejpn+lx6SQpI+ksaT5pJClQqaUpoumgqZfpjimJ6blpUClVKR2owKjLqOho3Wk7qWlp5Opg6surYqulq+HsFGxDrLOsqmzbrTgtJi1p7bNt5e4trikuHO4fLh9uBm4BLhquDm5T7owu8W7S7yuvP+8db30vSO+Bb4Oviy+g74wv6i/2b8KwCbAC8Cwv1O/+77evnG/XcAswQLCNMP0xAbHmshayXvJJMnAyGPIz8f0xlvGScZdxqHGLseyx9fHrceRx1jH78baxlfHM8iDyVnLLc24zpDPkc86z9vOX86TzajMVMzQzPvNbs+80ObRGtN71HTVKdb21prXnNgd2sfbMt1y3urfm+Go48/lu+dQ6Zzqzuvm7Dru/O/v8Q/09vVJ94z4JvrE+0X9DP97AQsEjQYyCawL8g0uEEoSQRQ6Fk8YlxrsHL4ePSCbIUojtiVnKAkrIC3SLrUwvTL4NEg3ZjkzO7c8UD7+P9hBrUOCRbtH/kkDTPtNyE8gUf5RplKPU6VUolV2Vv5WaVfAVzZY6ViVWQVa6VmQWYJZ1VmTWoxbaVwwXQ9eGl8rYClh8GGtYktjWWPdYhFiT2H/YK1g0V/HXpZdRlwGW/ZZAVnkV41WV1VQVCJTt1GxT7xNKUyFSkFJb0joR59HcEc+R5ZGOEWxQ2pCekHsQIdATUBGQGdAgEBZQAFAeT+nPqs9gTwJO3E5/jfXNuI1HzVuNIgz5zJoMrMxYjGEMbsxuDGUMbUxKDKgMisz3DMdNLMzuTKuMSExCjEgMWQxDzLTMpAzijSSNV02tza7NtM2TzfZNwM4rDcUN7I2WTbMNSo1mDQjNMYzaTMDM3cysTHUMKIvGC6uLGQrVSpyKYcozSdgJzsn+SZ2JvklSyUeJLUisyEHISMgqR6BHDEa7BeQFUoTUxFiD00NSgtNCVcHJAWlAmIAnf7r/AH7Hflw9571TfPM8D7uw+ub6afn++WC5OziJOH93pXcAtpC17bUJdJBz2zM4cl6xxHFtMI+wJm98LpruBm287MostuwMbDor5+vLq9kri+tqqsWqmqo26bVpVOl5KRrpDukG6R7o3eifaGeoMqfDp/Ynlef558doOefz582oNGgdaH9oRKiyKGioZmhsqEHoqGiiKN5pFKlDqblpuyn6qjDqTCqc6r8qsSr2axMrgewr7H+skq02rV1t7O4uLnqumi8D77Bv5rBg8O1xf/Hh8lzyl7Ll8wUzobP8tBp0vXTg9Xc1vPXg9hM2OLX0Ncb2IPY8tiC2QTaT9pW2kzaPNoP2qTZytjn14fXv9fd15DXLtfE1mfWNNbD1RjVudRb1NHTe9PV063UndVj1pfWfNZ91uXWh9cI2LPYrdm/2k7bYtuY273brNtM2wbbTdvW24Dc/9wt3Vbdp90f3qneVt844NXgAuFJ4TDiU+Nh5Ibl1OZ/6GXqeOy27snwkfJE9Mf1A/cE+CT5nPpH/ET+KABtASMCnQJkAywEqAQfBQEGLwdOCHoJsQr2C0kNtA7vD7wQWRHwEb8S3hMJFT8WBhg1GgUcah2dHtIfByFgIt4jGCUzJownxyh9KRkqqyoTK3MryysULFEs0SyoLa0uETCzMSczYzRpNSw23zacNy44jzgKOaA5QzorOys87jyoPZE+Yz/zP5NAZ0GbQvtDSkWtRhBIkEksS+ZMkk76TwlRl1EDUkdScVLWUqZTrVQkVSpVJVUvVUVVWlV/VYBVqVX/VSFWOVboVTBVcFTKU2FTv1K4UbFQyE/0TktOfk1ZTDVLFUoDSTVIdUeiRthF+0T8Q/BCCkIbQeI/zT7uPS49dzyDO246kjmvOKc3wDYkNuU1ujUxNfMzBDIjMNEulC1eLH4rwSrbKcEobyfxJY0keCNvInohtiALIJ0fXR9JHzsfLh9BHyMf3B6HHioehx2YHMEb4Rr0GSYZeBi0F+gWJhaeFW8VWBU9FSUVFRXxFKkUKBS5E3sTPROOEnIRiBDQD9gOag2tC/gJUAiCBrgEMQOtARMAXv6n/Dz74vl5+Oz2S/Wz8xny0PD2703viO6w7cvspes86vzo/+co53HmcuV15LbjMeMM4wDj4uJ94gTiyuFo4aLgx98p39PeoN5p3gLea92Z3KbbytoP2m7Z8Nh42N/XeNcf13rWq9Xi1IfUQNR903TSXdFp0IfPW85szPvJnMfGxcvEO8Swwx3DksLrwRbBTMCWv/W+F775vLq7jrrKudC4ebcFtoC0CLNvsc6vj66+rW2tYK2RrSCu767HrzawGbB5rzuurqx2q8mqYKoFqrOpTqngqKOokKi0qOeoD6mLqRqqv6quq+esPa4lr76vQ7D/sBeyDLN1s6mzA7RWtKq0ELXJtSC3xLhxugG8B72Ivay9gb2CvbS9zL3QvQe+fL71vmC/C8AbwVDCb8MOxHbEEcXmxfvGDMj5yL3JecpIyy7MFc3izV/Omc79zmbPyc9W0OvQa9HF0RjSwNKI0yjUnNTS1OTUBNVK1czVctZ51/bYdtrR2y/d0t6e4Gri4OO85FLlr+Xe5UzmJedC6HDpk+qu64Hsqexv7FLssux87UDusu7R7gHvju9v8BjxbfED8hPzl/Qb9k73Yvgy+cX5lvrB+1r9Df/EAN4CBAUSB94IRwqxC2oNYQ82EaQSkhNgFEsVfhYZGLUZKBtlHKQdFx+4IFoi0SNRJQwn6CjYKqYs6i30LhEwODFaMm8zkDTVNU431jgyOmY7jzyqPdQ+J0CdQUJDyEToRfpG/Uf8SPBJ70pMTLRNTk8BUUxSXVN9VL1VylYoVx5XbVeFWCNarlvDXJNda14XX4lfDGCpYPtgRGHYYVRikGKXYopipGKpYopiX2JCYk9iJGKoYSdhsmA8YHhfb150XZ5cJlwZXERcX1z9W0ZbklrmWZpZuVkMWmVav1oSWxBbmFrQWTlZpFjbV/xWSFb3VaFV+1TcU2VSyFBNTzpOIU3hS6ZKckkkSMxGxEUBRSFE5kJ1Qf4/rj50PVA8dTvUOl86kDkBOBw2QzTYMioysTHwMD0wpC/BLqotbSwBK14pjyfJJRMkcyINIaofVx6KHRIdqRwKHFkb3hpeGqgZhRgnF/AVCBVLFHYT1BIuEmERbRBMD04Oow0yDYAMmgvcChAKHglbCOsHYgdzBnkFngTIAxcDTAIoAZ7/ff01+xj5JfeI9Rf07/Im8mPxq/AT8L3vWu/U7onuNu7g7YjtCe1q7I7rh+qE6Uno1+ay5azk1eNJ45ri6OEM4STgVt9j3p/dBd1O3Kjb59rf2ezYIdhL17fWL9aD1ezUYtQB1OPTZdT91BjV8dSw1EfUmtPW0gDSMdFF0NbOTc3dy33K/chYx6/F58OTwszBRMEHweHAz8DOwFDAT79RvpO9J73tvJ28KbyYuya7H7s0uwi7y7rbuiu7nrvLu4S7C7spugq5H7imt3W3g7fttyu4T7jEuE6547nZugC85bznvRe/NMBXwYzC6MMfxQbG48b7x1vJ+sr/zDLPD9FK0nLTw9S+1WbWydbm1gTXV9cU2FzZ1dpA3Jbdgd7p3hrfOd9M323fo9/036Dgn+GN4jfjjONx41bjW+Mk45niwuEF4dngKOHN4T3iAuKC4fzgleBv4HHgp+D54FbhyOFo4jbjxuP04/fj5uMA5ArkneM44xrja+M15DjlkebY54Houeih6Ijoseio6KnolOgk6MTnj+er5/jnVejN6E/p4umO6lTrE+yf7OfsDu0j7SrtLe0X7evsr+x17JPs+uxi7crtLu6S7s3u1O4L74LvBPDI8LnxcvIz80P0t/Xr9mb3w/cj+Jn4O/nE+UL66PrL+9/8B/4d/wsA2wChAV4C1wJCA5kDhwOCA5EDmgPKA0oESwWCBtUHCwn5CewKCgxODW4OMA/JD3MQUxEhEmsSahIxEugRExLQEs0TxRTAFc8WvheyGOUZDhv/G58cDh11HdYdjh6HH20gICGCIYQhoSEaItkiDySNJfkmKSgpKR4qyipYK+srgSxmLUIuwC7TLrou2S4cL3QvrS+uL18vsS7/LXwtKS34LKQsUSxWLE8sUCx8LFYs8Ct0K8Aq4ykRKZkopSj/KHcpHiqlKhkrxiuiLGgt3S03LpEu9C5eL8MvXTATMX4xizGbMTAy7TKSM1M0IzUNNvk2nzcsOMQ4VznQOcg5bjlwObY5zDmQOQI5gDguOPg3xTdVN+M2Zzb5NeY12DWBNfk0pTSRNKg0sjSSNKM0+zRTNX01hTWtNQc2MTYzNis2OzaRNuE2+zb2NvA29zbfNrU2ozaxNgI3TzesN5I4vzmyOgg7LjtzO1Y7+zpbOh45uDdeNh818TOOMjUx0C+QLtgtWy0KLcQsIyw8K10qpin8KF4osCedJl8lKCT0IqohDSAsHlYctRoKGTwXeRXUE1oSExGYD6ENZQvkCBMG9gIaALr9cfsX+bj2nPTG8hrxnu9J7gPtvetW6svoSucO5kjlz+Rj5Ark7eOP483iAeJc4cPgA+Bb39LeUd7I3QfdOtxZ23baw9kZ2VzYmtcy1yTX99aU1hvWc9XL1EzU/dO901zT2tJO0qXR29A90K3P/M40zljNn8xCzE/MmszhzBjNKs0yzVHNXc0ezfvM+syrzDnM/8s2zITMocy3zLnM48wuzXbNwM0Pzl3Odc5DzvPNB86AzvnOPs9PzznP+M6lzmTOLc6jzaDMlcutyvDJq8nsyUPKPsreyU/JvchjyN/HycZzxUHEQcNzwsHB7sAjwI2/I7+Ovoy9gbyAu4u6n7lUuNK2qLXktEO04bOxs3mzKLOvslOyzLHPsMGvDK/MrpWuEq4/rXOsBqzmqxasf6yrrNasVK3UrUau167Hr8iwfLEDsoGyOLP4s6m0PrXNtZO2WrcduBW5SLrIu129ub68v2/AgcHKwo7D38MCxDXEmMQ5xf3FmsYqx+/H7sg+ytDLVs3PzkjQrtFT00bVIdfA2B/acdsS3bTe89/d4ILhBOKY4l7jeOQl5gnoeumD6pvrOe1m77fxz/NY9bz2afgI+p/7Tf0Q/80AhwJSBDUGfwj1ClgN0A+DEjUVUhdFGRIbUBw8HfMd1x7vH88ghiEzIgQj6COPJB4ljiUDJt0m1CeAKAspmyklKukqBCxGLXEuUS/rL2Qw7DCRMTMy1DLqM2I12zYmOE85uDpJPKE9sD7EPwxBQEJBQy1EGkXeRXlGEUduR3tHsEc6SI5I00haSd1JGkoWSm5KBUtgS8ZL7kvCS4ZLO0tAS51LHUzWTJhNFE4jTuZNAU7BTsdPlFDnUOlQEFGQUWlSOlPeU6JURFW3VTtWtFbpVuxWH1eBV/tXq1h1WVFaD1uAW5hbaFvaWiJanllxWW1ZN1n3WOJYwlimWJ5YfFgNWF1XpVasVXxUjVOzUq5RZFDlTmZN4kucSoZJfEixRztHCUcrR1JHG0edRuxF8ET0Qz5DnEIbQsNBd0EGQX5AJ0CnP8I+tT3ZPCM8NjtHOn851DhyOC040TdgN7g2uDVjNNsyPjG3L54uDS6kLT0t9Cx/LL0rAytgKsUpHCkPKKMmSCVzJLEjpSJMIYIfmR3aG4wamBm8GO4XFxdBFmwVmBScE3wSWBH5D9MOCQ6ODWgNHw2qDAIMFQsQCgsJQQiFB5UGVAX/AxMDbwKcAVoA6P6q/cT86PuM+uL4ZvcO9qn0YPM58vTwru9Y7pTsauo56NLlZONm4a/fUt4N3aTbWtpL2V/YWNdV1n3Vr9TM093SWtLq0eTQrM+CzmvNVMz4yi7JaMfHxRPEeML7wHu/o72Cu6a5MbgXty+267Qts3mxFLC4riCtdqv9qfuoHKgDpyum36XIpZClE6VtpPSjzaPGo8Oj26Pvo+OjwKO/oxSklqTjpPSkcaVrpk2nyKfPp6qntqcsqLqo4qiQqP6nsqfGpwuoYaiTqAup9KkWqwGsf6zWrOus0KyvrIOsK6y4q1Gr9qqvql6q6albqSapO6lbqXypQ6kTqUipk6nuqXqqaKuhrL+tqa5Pr5Svvq/3ry2wXrCBsLmwD7GGsUmy/rJws92zTbSEtHW0SbRftPm03rWTtva2Q7eNt/O3iLhPuTi6OrsHvK28Kr1gvWC9Mr1Hva69NL7avky/lb88wC7BH8Iyw2vEx8Vox3DJmMuAzS/P6tD90hLV+tbE2Eza0Ntm3RffnuDs4UvjFeV75+TpU+zm7mDxkvNV9en2UvjA+U773/yG/hwAtwFZAwkF9wbRCGwKoQuKDHsNZg5gD5QQ5BHoEu0TLBWcFmAYIBpeG2Yc7B3XHxEiTSQHJocnOikKK2Asgi3LLsUvQDBcMIQw9zDsMVgz4TRLNmU3dDigOcs6+jvvPLI9TD6iPhs/OEDAQR9DQEQpRQFG0EZ5R9xH50cfSNBIwkm3SndLD0yGTNFMME2mTQ1OcE7TTlpPHlBEUdVSeVS+VYBWGFeWV+ZXJ1iMWC5ZzVkBWiFaeVoDW9lbjlzEXK1cd1xDXF1cglyBXH5cTlz+W6tbeVuBW2Zb9VpyWita9Fm3WTlZXVhjVzBWFlUYVN9S11E7UdZQdVCyT3pOUk2BTNpLU0vHShtKgEkoSQxJCEkDSe5Ipkj7RzxHukZIRtBFX0UNRdNEq0TBRPpEN0UhRU9E4UJiQShAHT9EPpw9HT2ePO875DqZOV04JTfdNcM0yDPQMsMxmjBsL1UuhC3YLCIsGyueKcsnxyUYJAQjMyJPIV4gix/nHkkefB1nHAMbjhn7FwkWCRRUEuUQhA/uDXYMNQu/CTEIrwYkBdwD0AKrAYEAhP+k/rX9h/wg+8D5NfiZ9hb1aPOc8dfvee6I7ZTsHOv/6MzmweTC4rDged423PbZ4tfT1cfTy9Gzz4DNJsuuyInG88SYwyfCosBhv1u+Bb1Fu1u5g7fctSy0hLJGsXmw468WryWula1LreusVax3q1WqGandp6SmwaUrpaWkMaS4o0Oj86KhojKi1aGKoSShnaAioBagZqDDoAKhMqG7oXiiMqP9o5ykIqWTpQWmmKbZpiynqKcZqL6obqktqgmrtqsIrH2sJq0Irk2vfLCHsX6yXLMptLS0MLWqtS+23LZ/twC4g7gIuc+5vbrNu+m8sL1EvsG+Ob+7v3DAPsHzwbvCxcMCxXXG/cdgyd7KkcxSzuDP99B/0drRMNJL0nnS+NLY0+/UHNZZ1zrYz9hX2ezZrdqY25jcUt2p3Z3dj9313YjeI9+33ybgQOBC4Grg3+Cd4S3ifuKS4nrilOIa487jcOQS5bHlReba5m7nP+jd6PfoSene6ZDqbetx7H/taO467+PvzfAb8nbzwPT29UX36fjd+v38L/9LAW8DggVtB4UJjgtmDUIPTxGUE18VfBZ/F6cYChqPG9scOx7UH3UhNiPzJMkmvSigKn8sMS7XL7ExljN0NQo3Wzi0OfU6JTw7PTc+cz/eQCVCfUMPRaxGN0i6SQlL4ktRTL5MhU2bTt1PBlEdUkdTcFRxVT9W+1awV5ZYsFnFWt5b8lwJXuJeZl8PYKtgJmGsYUNiDmOpY/Fj92PsY9ljpGNvYwpjSGKCYRNh/WBlYcthvWG4YeBhImIsYgZi8WGsYW1hBWGWYJJgpmCZYGtgbmB/YF9g8l9FX/1eNV+4X99fkF9KX+1eiV4gXvRdCF4NXh9e/12SXRhdjFzxW1tbulq7WW9YE1fIVb5Uy1PXUvBRW1EqUfxQgVCXT1lO0ExAS+RJuUjqR5RHakckR+pGnkZ9RqNGx0btRuxGj0azRSpEDELYP9Q94DvtOTI4iDbdNIQzSzIEMZ0vBC6qLI4rsioWKisp1icsJloktiIWIWsfkR0gGzoYQhVwEt0PZQ32Cs4IqgZ/BIECkQAK/479AvyQ+vH4OPdJ9TLzuPAT7qPrRekF5yLl5+Mk45ri1uGv4GHfG9433YTcwdvF2rLZFtmW2KPXMtZz1JXS0NBqz03OPs1RzLXLW8say8/KQcpHyQjIj8YKxdfDCcM5wk3BjsDGvxy/lL7Dvem8ErwNu+y5vbjFtwe3C7aqtPGyerGmsBiwX68nrresRKvcqcKo+Kdwp/CmOKaVpfikUKRdo/Whb6AInwCebZ0inQ6d35xrnBOci5vummGa0ZlxmeiYhJhrmDmYB5gJmFaYfJhBmBaYG5gZmB2YGJhImPqY6JnbmuabG501nrKe2p5tn5WgIKKzow+laKYpqOGp96qHq82r7ashrJisP61ZrsavMLGDsoKzMrTqtMC1fbYqt7y3HLhBuDO4WrjBuFu5Fbqvui27vLuMvGW93b0hvmK+rL75vtm+lr6cvrK+1L4Sv2+/H8AXwQXC/8IYxD/Ff8afx7HIA8pPyyvMoswUzZDN580ozpHOTM870FLRi9KT01/UTNVu1qXXyNjG2cba49tA3cneZuDp4SbjQORX5VjmJeff57fo6Ol+6z3t2e458MrxhPPh9Pr1J/d4+MT5G/vC/Ir+QgDwAY0DCwVxBr0H4AgHCjkLeQwfDiwQLBLvE7gVfhcIGUgacxuZHKYdzR4BICkhRCJMIyUkACX/JfcmoCcCKHIo8ShvKdYpFypSKukq0SufLIkthy5wL2UwYTFTMhkz1zOfNAs1ZzUYNv42+zfgOFs5YTlsOYQ5fzlEOb04OjgEOD44rjggOcA5NDpHOmA6mzr4OkY7djuSO4472DtrPPo8jj0SPng+Bj+zPzxAg0C4QDZB+0HMQm1DhUNCQz9DPUPoQlxCukEcQZtAUkAOQOI/EEBwQBFBxEFBQqFCuUKkQpJCVUL7QWJBa0CUP9M+7j0mPak8OTyJO506ezk/OBY3FjYyNVk0tTNrM2MzUjP7MpkyPzLVMXgxTDE6McAw7y8zL9Eu2S7yLu0utC5SLrYtsSxRKwkqDCkmKEcnbSaWJakk/SO5I0ojdSJhIWIg8B8FIC8gFSCdH9ceBx5ZHbcc7RsIG0ka8hkJGkgakBrzGlcbhBu8GwUcEhy1G9EajhlFGCcXJRYuFTQUUBOIEsAR6RDlDwMPXA6oDbQMdQsmCvwIOgi0B9oGqAVuBIQD8AKcApgCawLlASgBYAC5//L+C/4O/dn7lfoa+ab3n/Ye9gj2APbn9aD1NPWX9JPzZPJs8avwWvBT8BfwvO9+75Hv5e898IHwq/Bw8Abw2+/f7w7wW/DO8DHxcPGR8V7xKvH18Hfw3e+L76Tv5O9X8OLwQ/FO8Q/xqfAv8P/v6+/Q77jvtu/J76PvZ+8B70LuhO0F7WTsh+um6v3pdOnu6JHoKOjG533nEOe25nXmAuZ25d7kL+SW4wHjT+K44XPhGOGE4DDgLuBB4GDgYOBN4ITg4eBo4ePhF+JK4nbilOKa4obihuKU4qnix+LL4r3is+Km4rviueKL4nLiVOJh4t/ilON15GTlSeYq59TnWOjd6DfpNOk26WHpx+kq6k3qZepk6n3qxOoo66brGOyF7A/to+0f7m7uhu6k7u7uWu+W75bvqu8x8EDxb/Ki88X0vPWT9in3kfca+Mf4dfkK+oL6xfrc+ib71fuw/Gr9MP68/s/+sv5p/i/+Hf4F/uL90/2//Z79n/24/cv95/0w/nr+hf5O/gb+pv0N/Xv8wPu++tn5WPkZ+df4n/hz+Dr4Tfiy+Bn5h/nm+d/5kvlV+UH5RPki+eL4gvgC+JL3JvfL9qL2vfYW94L3f/f09or2VPYr9vz1s/U99ZD04/Mg8zPygfEU8aTwHPC575PvcO8O72julO3Y7JTsc+wu7Mzrf+t465XrpuuO64vrlOuK64Xrf+t863Drb+um6zzsFe3m7W/uu+4w7+XvtvBi8bXxKPIB8wn08PSc9Uf27PaV9yz4iPjK+Pv4NPmz+Vn64fpW+977hvxb/UH+Bv+8/10AxwDqAO4ACQE8AW8BiAGTAfEBmwI6A5MDnwO4A9ADtQNgA9QCVAL9AdUBvgGrAcgBDQJQAj8CAQKpAS0BpABCAEAATQBCABUAoP/0/l/+/v1t/dv8hfw2/Bj8d/wo/a79A/49/nv+if57/qH+tf7S/vb+Qf/y/5UA2QCtAD8A/f8cAG4AwwDcALEAgwBHAOj/ev/f/hD+Ov2f/Gj8d/yg/Lr8Cf3J/a/+kv9iABwBDgIMA9wDkgQYBZQFLwbZBnUHnQeVB8cH3gf7B10InwjNCCsJkAnKCd0J/QlfCu8KvgurDH0NOw7xDscPkxANETURWBHBEUISlxLxEo0TZRRdFfkVLRZMFnIWvBYZF2gXoxcNGLwYrRmiGlIb7xuNHHkdwx7zHxUhSyKAI8ok7SW7Jk8npifLJ7wneCdNJ10nkCepJ6gnwifzJ0QoiiiXKIsoiyiOKEoozCcpJ2cm+SX/JVUmoSarJpAmZSYRJowl7SQfJHkjFyOFIq4hhSBnH6weZB6bHtse0B6hHnweRR6zHfYchhwYHFIbYxqGGf0Yixj1F4YXYBdzF5gX1xcSGOUXTRdkFpgVJhXjFKkUfhSRFL8UoxQ0FKATARMpEiQRMhCADwEPMA4hDWcMEgznC6gLeQtkCzULEAsgC0kLqQsqDI4M6wwiDVQNkA2aDVANwgxNDDwMaAxRDO0Lcgv3CsUKrAp6CicKwgltCesIVQj0B8cHuwfMBwMIRQhYCCAIwwdcB9gGYAbmBWsF+ASfBJ4EzgTABEsEiAPEAh0CewHbAC0Amf86/x3/Nf9u/4//ev87/87+D/7Q/GT7VPrH+VP5qvjx9yr3o/ao9tT2z/Z89v31qPVf9fn0bfTK8yPzWvKM8YrwMu+37Ufs5+pt6Y7nheWz4zziI+H73/LePd6m3TPdqdz323DbK9si2zrbMNvR2gDa59jP18HWzNX+1C/UeNPU0g7SO9GP0B/Q2M+hz4bPfM9mz0XPKc8kz1DPfM+vzwjQX9CG0JnQ89CZ0W3SXtND1OXUXNXw1Y3WG9de123Xdter1wfYMth82PHYT9ls2VzZbNlj2RbZw9iz2OnYJNlh2ZLZrdmR2VvZctnT2YPaf9uJ3JXdtd7d39/ghuEr4g3j+eMh5W/mvecw6arq5+vr7Nztqu5p7zTw8/Bx8cHx5PHl8cjxnfGh8a7xr/Ga8Z/xzfEP8m7yx/L98uXyivI88jXyWvJc8jvyJfIt8mvywfIL82Tz3vNy9Pb0XvXC9RL2BvbN9ar1oPXm9VL21fZ39yH4+Pjq+f366vtj/In8ifyc/K/8jvw//CD8OvxG/Gv8pfzQ/OD8Av0h/bb87/s8++j67von+4f7qft8+0b7Efvh+sD6wPrp+gb7PPuw+y78hPya/IP8WvxV/I/89vws/T79dv3y/ZT+Cv9u/6H/qP+j/2X/E/+r/kH+Qf6D/q7+sv65/vz+Tv+J/6n/iv/u/gn+g/2S/fz9V/57/nn+cv68/iz/rf+TAJ8BpgLHA/IEKQZBByEI/AgdCpML4wzfDboOnQ+zEPURNRM/FBUV6BWzFnEXWRhlGZEaqhtFHH0crBwGHY8dLR6hHg0fXB9MH+geRR7ZHdodER47HmAeux4EHyMfYB+JH8cfRyCeIN8gQCG7ISsiSiIzIhYiEiIwIkIiSyJlIosivyLfIqAiFCKkIU0hGSEzIVchZiFNIeggVCC4Hz4fAB/XHoce9h0zHVkcsRsmG18aaRlQGDEX3xWBFGoTWhJ1EboQJxDtD8kPiw81D/wO4w6gDhYOIA27C1MKMgk9CKsHrAfuBywIWggyCMsHugcbCGMIdQhmCCwI5Qe2B4cHVwdCBzQH8gaEBiIGiAXJBCEEhQMcA8cCigJmAhkCxwGfAZQBkQFXAdsATACy/yj/r/4p/o397/xo/L77vfrK+Rb5cPgK+N/3rfdv9zT39fbe9g73L/cx9x73A/fl9qX2N/a29X/11/Wp9kv3d/eE9373a/dI9wz3mvYc9uP1yPWu9YH1RfUD9dH02fQe9X71ufXU9bz1efX99Gz08vNo88/yDPJf8fbw4PAu8Znx7/E78qXy5PLB8lryEPJg8kPzSvT+9FL1i/XE9Rn2cfap9v32Zfe697v3Tve09gD2ffVC9Vf1tPXw9Rb2cPb89oj3+/c9+Cz4z/dt91f3bfeZ99X3HfiU+B/5gPmI+ST5lvjz90b3xvag9sn2TfcB+J348/j5+Cf5Z/lb+ST53fie+HP4avih+ND4vPh7+Cr4Evg6+GP4l/j5+Hf57fl8+hn7q/tB/OL8pf0f/m7+9/6d/4wAowHFAgoEXwXPBlkIvwnOCqYLVQysDOEMQg2/DXwOWw9TEG0RVxIiE/ETrRRLFdUVYRbkFlwX8xeuGGMZCBqWGt8aFRt6G9obPRzMHIUdRR7WHh4fAR+nHnMejh7SHicfcB+DH5Mf1x8PIGkg+iBgIbkhGiJ/Iu4iPSOSI/AjNSReJCokYiNbInMhoCDoH1wf8R6eHkoe/B20HYMddR1BHQwdDB0LHRsdFx0DHRYdBR2eHLwblxrJGXUZbxmLGYEZgxnXGVMa0hofGzwbfxvtGz8cNhz4G8obzRsGHCocEhzaG6IbkxuWG5YbnxvCG90b6Rs/HJgc0xzfHJ0cjByIHEActhsQG4Ia3BnuGNIXwRbJFd8UBRRoEwMTyBLCEqUSgRJWEh8S7RGLERUR2hDNELAQaBACEMQPgw8MD3gOsA3gDCUMPAsrCvcIlAdPBlAFWQQxA/sB7wALAHn/U/9O/z//Ef/Z/sz+/v4W/+j+sP48/m/9hPyf+7j6wvm9+M73Cfck9u70Z/Pc8bbwwu8Y76vuMe7C7T7to+zW6+Lq9Okk6YnoHOi550Tn2eZR5pHlouSu4wXja+Lj4UPhPuBH33/e0t0v3WncbNtG2kDZc9jR1xjXC9Yl1a/Ug9QU1OfSNdFQz3XNvstByg/J5seIxhvF0cPmwnLCSMIswvbBosFTwUvBN8HRwAjA376kvW+8PbshujK5cLgEuMq3ibdOtyy3NLcrt9C2JLaftYe1p7XztVa2p7bvtji3lrf4tw6457eStzW3BbcAtxy3JrcYtxS3Lbd6t/G3irhRuVO6druavMm9G79EwMHA2sDDwKLAvMD7wJDBZ8JEw2HE7cXXx/zJJMz5zU7PIdC70FfRBtLZ0snT7dQ/1q3XE9kk2gfbvNsK3PLbkNsn2wLbS9vM2yPcbdzq3Grd691v3tPeWd/035vgi+Gn4u3jM+U35ibnGOg16VrqPus17DvtMu5E70DwBfG08VzyJ/Mh9Cj1DfbD9mz38PdY+MX4M/mW+er5jPpm+2X8jP2j/qv/wgDRAaQCcwNfBGoFogbZB/0ISgrkC4INyg7kDwoRShKdE/EUPBZyF4IYKRm6GXsaLhsJHOcc5x3mHosfFSBhIJcgyiAAIVYh4yG7IqEjqiQKJsgnnylPK90sKS5CLx8wxDBUMQ0yAzPFM0I0iDTpNIM1FjadNu02RzfzN9Y42TnjOto7tjyVPXU+Fz9vP7w/VEAvQQVCy0KHQzxE1UR7RT5GxkYRR09Hi0fTR3RIP0nHSTtK50rES19Mq0wBTYZNE05wTnxOUE5ETm1Oq07XTvtOG08MT8JOMU5oTZ1M+kuSS3BLaEteS2dLbUtAS8xKGEolSQBI/kZMRrdFBUUYRCpDZULYQYBBKEGaQOQ/7z7vPSw9lDwmPKU7FzukOi86mTm0OLY3zjbpNRU1GjT3MgAyPDGVMO0vSi+ULtstNi1sLKcrDitRKggpXyfYJaQkviP7IqMivSKcIgUiEyH4H9MeiB0THJUaMBn2F9EWxRXWFOgT6hKyEYoQmg+WDnkNUAxnC6sKCwpPCTUI9ga5BY0EWQM/AjYBIQAX/w7+8/zV++76SvrI+Wb5BPkR+FH2bPTC8hzxku8o7rLsIOvD6droIuhu53fmTeUH5LrieOEx4CbfYd7d3aXdad333D/cmNsE2xLa9Nj8117X89Zo1rLV0tQN1HLTwNLi0dvQlM8GzqbMtMsXy3bKucktycvIjchRyPzHwceVx2HHRcdBxyvH88aXxizG9MXgxZvF78QnxJvDJMPJwm3CF8ITwlPCucIhw4/DF8SrxEfF18VDxkDG6MWgxTbF0sTLxPXEGcVCxXrFy8VHxq3Gt8ayxuXGVMfQxxDI98e8x7PH38f1x/nHB8geyDfIKcjVx1PHAscGxy7HPsdix8THJshyyNTIfsmByszLKs0/zgnPts9B0OHQptF40lfTS9Rh1ZnWqddm2CHZBdoT2wfcsNw/3ffdFt954M/h/eIF5AvlOOZq53Homem36pfrkuzO7TjvXfAu8RLyM/OC9Lj1wPap94P4YvlG+j/7TPxZ/Vf+MP/7/40A+QBpAd8BcwIAA5cDKASaBP0EZQUGBvEGJwhmCSoKdgqbCuMKbwtoDKcN3w5EEKcRuRKdE2MUBxV2FX4VABU/FJkTBxOKEjgSCBIMEk8SpRLaEgMTJxM5EyYTvhIyEs8RxBEIEloSrBLeEhcTgxPPE/cTAxTGE0MTphIXEqIRbxGQEQ0SpBIDE0sTghPeE2wUuhTbFOUUvxSTFHIUkBTUFPkU8hTtFPIUDhVPFcUVkRZ6F0MYoBi8GOsYKhlyGcYZRhoJGxkcUR2NHtgfJiFaImMjPiQLJbslTCbSJkgnzyeRKFEpsinKKdUpDyp8KuUqUCuWK44rQyv/KuEqmiohKqUpTikiKTIpbimgKdspBSoEKskpeylHKQop1yjSKP8oLClNKXkpqynbKbUpbCk5Ka4o2ifiJrAlXyQpIzQieSH5IJIg/R8vH1Yecx2PHNAbChs4GnoZ8Ri1GL8Y5hgyGYEZqxncGa0ZFRlAGFQXkxbdFSMVUhSTE8cS2xESETsQJA/uDd0M6Qu7ClUJBgjyBi4GywXaBQ0GAAa1BUgFtAQMBEQDKQL5APb/K/+D/rn9v/yj+0v6z/hp9xD2AfV39EX0IPS18x/ziPKk8c3wdvBi8DbwxO8W70HuZ+2d7AbsguvX6jDqv+mi6cPp2enQ6dPpvelQ6bDoGuiJ5y7n4+Zz5iTmqOUQ5XfkkeOT4srhY+FI4R7h1OBy4APgoN9536/fCuBO4HrgnOCd4HHgOeAV4N/f0t844LHgDuFd4bzhEeIR4rzhReG34CXgmN8d3+Let96J3ojeud7n3vre7N7j3hPfa9/f30TgmeD84FLhoOE64hPjmeOx48Xj/eMx5F/kk+Tr5Fvlj+V15TvlCeW/5GHkD+TF46PjgOMm46XiLuLJ4TfhluAU4Mffot9d3w/fD98n3/veft4p3ibeFt4Q3jPeUt5f3mfeYd5L3lHes95G38/faeAJ4cfhiuIT40DjVuOb4/7jfeTs5Fnl7OV35rzm1+bw5t7mruaK5pfm0Ob15iTnjOcy6DPpWepu62rsM+0b7ljv2PDH8vX09/bK+HT68vsd/fL9xv7g/ysBfAKqA6oElAWMBnEHJgj9CP0JCQs+DI0N8A5ZEHoRpxIVFIEV8hYnGAgZzxlpGgUb7Rv+HBoeKh8TIM8ggCECIkIibSKTIsUiKiPCI20kFSWbJQ8mbSa1JvUmKSdMJ1AnQCccJ/Um6SbZJqMmMiaWJSwl4iRuJO0jjSN5I58j8yNxJP4kcSWwJcwlvyV+JSsl+CTRJJkkUSTuI44jOSPvIskiriKdInsiOyIKIsshaiEMIc4goCBhIEQgWSCBIJAggyBtIHEgmSCkII0giyDRIDIhaCFYIQ4hwSBwIBYguh9/H1UfPB9SH1QfUx85H+QeZh62HcYclxtQGh0ZKhhiF7sWQBbiFZkVZBVUFUIVQBVpFaEV1RXuFQwWMRZFFhgWyhV6FR4VlhTRE+0SIBKsEUgRxhA+ENcPog+jD7sP0g/VD4kPIA/LDqYOrg75DqUPLRBBEPsPhA/+DnYO/A2EDdgM/ws9C5QK9QlhCcMIFAiaB2sHVgcxB9QGJQYyBT8EZgOyAjECxgFwAeoARACZ/8z+6P3n/M77q/rQ+Tf5f/ir99T29fUJ9T30qfMX81zygPGf8LDvk+4e7abrgupK6f3n3Oa75YrkiOO74gXiV+HG4GrgSeBY4FDgBOCF3+LecN4+3jXeW95g3gvebt2a3MvbGNt72ubZU9nF2ADYE9dJ1rjVTtUR1QnVNtVh1WPVNNXK1HfUN9QC1B3UU9R/1MbUR9X/1crWmdd82H3Zm9qw24LcFN103a/d3d373QLeBd4x3rject8d4Ong4OHw4t/jWeRq5HfkueTL5K7koOSC5H3ktOTb5Njk1uQX5ZjlHeZz5rLm/+Yt51fnbOdj52jnY+dF5+jmSObT5eblduYr58DnUuju6K7pdOrs6gjrxepz6mnqm+rh6hLrGutE67nrf+xs7SDupu4X73nvAPCu8EjxxPEl8pPy5vIN82DzmPOs883zGfSb9Ar1dfX69Y32KfeP95n3rPf993H4DPmg+Sz6+PoM/CD98v2M/un+I/9u/7r/KwCjAPEAWgEUAvQClgP9AzIEWASgBMUEkwQyBAMEIQRcBHkEcwSbBN4EEAUqBRoFKAVyBcIFMga/Bj0HeAeSB7UH2gcLCEQIcgibCNIIKgnFCUMKXAogCu8JJwrVCtML2wy2DVIO2A5lD/MPPxA2EAQQyg/vD6wQxBHoEt4TtRSbFWwWBxdjF6QX9BcrGDwYWBivGPsYGxkBGbUYlhi+GAUZPBlVGTsZ4xh0GDQYSBilGAgZQRlPGToZRRloGaMZCBpZGpga7RpUG+AbVRxgHCwcAxz0G9gbcxv8GqQaaxp7GtYaVBvcG2YcyBztHOMcoxwwHKQbORsXGxwbNxtUG2gbkhvdGxIcBBy4G3UbXBtlG04b+BqbGmMaQxrmGUcZgxjMF0sXxRYlFnUV0xSAFKcU2BTcFCYVzhWXFiMXOhfzFpQWGBZuFfgUrBRtFF0UbxRyFGIUVBRTFD0UAxTWE+kTgxSJFXoWIBeHF+YXHhgUGOcXnhdZFzUXLhclFx0XExfvFqMWNRaVFc4UDxREE10SUhFEEFQPnw41Ds4NTQ3PDIMMcgyHDI8MdgxlDGoMZwwtDAUMEww3DGQMlQzQDCUNrg05Dn4OfQ5vDmkOfg7XDoYPYhAZEV8RKxGTEMUPAg8zDkMNRwxVC8cKbAoeCukJpgljCQMJhggZCOAH3gffB9EHqweIB3cHRwfTBl8GAga4BbsFFwadBg0HSgdABy4HIAfQBk0G3wVaBZcE+gN6A/4CtgJ1AhgCigHYAFUA9P+G/+v+Kf57/c78LvyZ+/P6TfqE+an47fcv91b2cfWe9Nzz9/L68fvwMfCa7zPv0e5L7t7tju1v7UTt3OxP7HPrceqj6dvo0Oex5qrl3+SE5I/ksuTB5Kzkh+Q65LrjU+MB483itOJz4hDis+F34UnhFeHz4M/gsuDI4OTg6+D54B/hNuEn4QHh1+B94Pbfg99U337fst/j3zLgfODb4Ebh3+G64njjGeSs5DvlpeWe5Tjl5uT05EjlpeW95aXli+VY5SLl9uQN5TvlOOUi5cjkFOQw40PieOHv4JLgcuCu4PzgNuFJ4T7hJOHz4LjggeCB4HHgIeDY36Tfnt/j3zPgNuDU3ynfe97t3Wfd5tyF3FPcVNx83OXcZt3s3Y7eEN9036jfr9/a3xzgc+DN4AzhPuGN4fjhSOKF4q7ix+LY4gLjXOPI4xPkK+RQ5KrkLOWm5bDlDOUF5BXjdeJW4qbiLePP45fkd+Ud5pPm+eZe59znUujA6O/o2Ojb6P/oTum96Tfq7eq262Ls+OxE7abtVu4372PwqfHr8gH03PS09Zv2pvee+Ez5w/kv+o36F/vT+438Sv3R/WP+Kv/Z/zcAMgAdACEANgBuALEAyQCnAJIA1QA8AaoBKwKgAicD0AN/BBYFdQVxBS4FDQUsBVYFeAWtBakFYgU3BScFRwWzBTwGvAYbB2MHdgdyB7EHNAjpCI8J+wlaCtMKbQsKDJEM4AzlDLgMfwxeDEkMSAxCDAwMuAtKC/IK0wryCmYL3QsNDAsMBQwEDPYLEAyTDGoNRw7lDlgPhQ+HD4cPYw9ND0sPaQ+SD50Pww8mENoQyRGzEqkTvhTKFa8WTBe2F/oXKRiAGOsYGxkDGcQYtBghGeIZhRrSGjwbBRz+HP8duR4rH8YfsSCwIYYi/yI0IzojKCM+I1wjhyO4I9Ej6CMbJGIkfiRmJG8kpCQLJZklGCayJmAnEiiUKLkosiieKNYoVCnVKV0qyiokK4Mr8CtkLM4sHi1qLfgtuy5oLwEwpDAlMVUxRjH2MIcwOTADMOMv2S/hL/Av5C/SL8IvnS+KL8cvOjCaMLEwmzCMMKMw9jA6MSExwzB+MFkwLzAFMMQvdC85L/Iupy5oLhgu4C2cLSotbSxvK3EqWyleKIYnkSabJcwkBSQoIyEiJSFZIH0fdx5DHfgb9xo2GmAZThhHF6EWLBbGFSwVIRQEEwAS/hAJEAcPxg1yDF0LnQrVCesIIwh8BwEHzgbKBg0HlQfqB+UHhwfZBi4GnAUABUkEXgOHAu4BSgGJAJX/lf7G/f/8H/xG+4r6u/mx+KL31PY89r/1KPV69Ojze/NF8/7yjvI28uzx1PHC8XHx0PAI8GnvB++v7hfuce3k7FfsqOu/6tvpAOkP6CPnT+aV5d7kLuSQ4xXj2OKY4kPiAOKv4XfhV+En4bng59/63jXet91t3UrdUN053eTcS9yG263astm32AjYrtdc1wLXzNag1lnW2NUO1SLUQ9Na0nLRk9Cnz6vOp83EzO7LUssQy+XKlMoCymXJ48iDyE3IBciwx2bHFMerxiHGgsXpxHnEDcSVwxPDh8I1wgzC7MHRwafBP8GiwBDAkr9Wv2W/rb86wMnAJMF8wc7BEcIqwv7B68HowQjChMJFwyjEucQOxWnF3sWhxmnHCciryH7JksqUy4PMgM1xzlDP/s930MrQQ9Hw0bzSk9M31LTUBNVn1eLVXtYv11fYt9kg21zcd92R3sXfAOHe4VbireIB43njKOTM5Erl4eW55qfnp+ip6XzqWes27MvsSu0G7gXvCvAG8QDy1fKQ81D0CvW09XH2OvcD+N341/kF+0H8g/3Q/hUARQFQAioDFwRRBZ4GDgi6CVsLtQzgDdMOlQ+QELQR2RLvE9YUpBVfFvUWdxfQFzAYqRgeGagZMhrFGlUbphvjG1Yc4RxnHdgdER4WHjAegx7rHk0fpR8dIKogJCFvIZoh9CGEIh8joiMFJEokhyQEJaUlPibQJjsnlScFKIsoIym4KUYq1ipuKwIsXiyULNksTC3WLSQuVC6rLjQv0S9bMM8wYTElMr4yNDOsM/AzCTQSNBs0LzQoNDA0SjRTNHE0sjT2NAs1/jTuNPQ0HjU/NXI12TVMNsA2MTeUN+I3IThUOIA4tDj0ODk5XTlwOYc5lzmTOWs5LDnnOKM4cDhWOGM4lDi0OK04gDgkOOs3uDdMN+g2ijbzNQQ1xTNpMjUxGTDiLoYtSSxJK3UquCnjKOcn9SYpJkkldCTBI/YiCSIFIQ4gFh8NHtscsBveGjsafxmfGLEXuxbcFdUUpBOZEsYRMxGwEDEQnA/2Dk8OkQ0IDcQMmgxmDAQMswuKCzQLhwqCCXEIiwfBBv8FHwVNBKADDwNoAr8BNAFnAGr/j/6//fn8afwn/EX8g/yK/Ff88vuM+yP7kfra+ej46/cb91X2kPX79Lb0oPSn9LT0vPSn9Hb0PvTq83fz/fKn8lzyEPK+8VPx6/By8N7vO++c7hLulu0d7ansT+wj7Azs2euB6//qZuq96eDoCuhf5+jmmOZR5hPmquUr5Zzk4eMH4ybiZuGs4Avgjd9B3zjfIN+u3gTeSt2o3Dzc2tty2wPbftrQ2RjZS9ha13rWz9VE1ZfU99N90wnTrtJs0iLSq9Eg0XnQ4M96zzrP9c6TzjjOzc1izQ3NtsxMzLzLEct9yubJPcmIyOTHg8dCxynHZMfRxyPIU8iKyMzIGcl7yQDKlcoZy53LKMy8zGXNAM5yzrXO584tz3DPzc9K0LnQTNHz0YPS8tJU063T8dNQ1K/UH9Ww1TvWsdY01/7X4djw2TbbftzA3ffeK+AR4aHhM+Lh4q3jleR35YPm2+dH6dHqhuxP7vTvXPG38gn0f/UL92n4sPnD+pb7VfwT/bv9Ov69/mL/TABCAQQCqgIoA6MDZgQ8BeMFiAZNBwcIiwjfCCUJgAnoCVoKyAoYC2QLpwsGDIMMBA1gDXMNYA1EDR0NEA1eDQcOvA5QD8QPDxBGEHkQkRB9EHIQrxDeENYQ9RBeEegRahLKEgQTJBMrEwUT9RIMEy4TjxMCFHEUyhQOFTsVKhX+FOAUyBSbFFcUIBQZFFQU2hR3FfcVURZ/FrMW4BbMFsIW4RYGFx4XIRcwF2YXtBcUGD8YABioF28XSxcsFwIXDBdSF7UXLxiGGOIYIRkqGVcZzxmiGoAbbRyFHZkeqB+DICAhlCEbIrQiJiOEI/EjYSStJMgkpSRuJDwkEST1I7EjdiNJI/oilSIUIochFSHoIOAg5SD9IO0gmCA5IPUf1B+wH3MfKx/QHoAeZx6BHsQe3x57HqkdlRxoG2QarRkzGc0YTBisF+QWMRbkFdgVlxUWFZ0URxQvFEEUORRCFGIURhTyE3MT5xJoEvQRjxEeEcMQihBYECUQxA9bDxkP+w6+DkoO6Q2kDXgNQQ0FDdkMsQyeDHMMIAyqCx4LjAoCCowJ/whFCKgHWgcPB90GyAaUBmAGGAauBRYFVQSJA7sCFAJuAbcA/v8y/1j+mv0k/fL8vPxf/BT8yPtg+8P6+/lG+YX4efdU9mP1sPRQ9Ef0cfSg9Nv0OfWE9aD1yPX69SP2SPZA9gn2uPVX9ar0r/Oy8tXxI/GZ8Dbw5u+376Pvdu8K723u5u1s7czsM+zL64LrNOuq6iLqxemd6ZHpZekn6dXocugF6JXnMefm5snmwObV5vHm2uae5i/mouUR5XrkC+Sv4y3jlOL64VrhyuBg4CbgKOAj4ALgAOAj4F7gpuDf4CDhc+GR4XXhZ+GL4dDhBeI74oPitOLK4tTiuuJl4u3hceHu4GPgyN9U3/jekN4b3o7dF93D3Jjcxdxa3f/dgt7s3hzfU9+U36/fvN+936bfbN8W39je2N4i36nfZuBn4WziWuM75OHkVOWu5fPlV+bS5lTnAejB6GTp5ek56mrqlOrY6knryutf7BTt4u237p/vj/B28U3y+PKt83P0DfWs9Vr26/aM91/4YvmA+or7i/x1/UP+A/+k/yAAfQDcAEABnAELAocC+gJhA74DHwSPBBgFlQX2BWEG9AaRByoItQhACe8JvQqXC28MNQ3TDX0OLw++D1oQKBEBErMSYxPpEzYUixTeFCsViBXmFUkWpRbxFlcXuhczGNYYYhnWGTEafxrSGkgbvRswHMAcNR2RHewdWR7EHh8fgB/cH0kg6iCrIVEi6SKGIxgkoSQpJdolwia/J5koJCmDKdIp8CkNKhMq5im9KZ0pkimDKUYp8yirKHwoXyg9KB4oFygiKEwomygHKUIpQyltKcwpMiqOKgMrbyvEK0Us4SxgLYgtQi3kLLkswCzlLPgs7CzZLJosMiynK+0qSCrpKaopTCnTKGYoCyikJygnnyYOJo8lJCXIJIMkOiT7I90jtyM+I20iiCGvINIf1B7jHSMdjBw0HPsbyhuxG6MbfRtXG0gbOxsGG8IanRqTGqQawhrYGvIaCxvnGsQarRqmGtMa/xoSG+kamxo3GpEZ2Rg/GN8XoxddFwIXgRbQFfIUFhR0E9YS4xGzEHcPNw4GDQQMGAsaChUJLwh/B9gGDAYZBUEEjAPdAiwCUwFZAEL/Bv64/D37w/mX+K/37/Yh9jP1RPQ78yjyEfH37xvvee7I7QLtPex968rqCupL6Z/oF+iZ5+7mAub55ALkFeMr4kHhYuCN363e7N023YXcCtyu20/b7dqn2k3a0tlW2cjYJthc17nWWNb61ZbVG9WG1CPUBtTz09rTvNO+07nTUNOg0gTShdED0Y/QV9Ao0N7Pn8+Vz6XPmc97z0PP/M7MztXOIs9uz5bPjM9yz1TPBM92ztnNRs2TzN/LcMtWy4/L/ct9zOjMPs13zX/Ns834zRHOFc5LzuLOj89G0OnQZtHK0QDSG9Ip0l/Su9Id03bTpdPk03DUPNUM1sbWftc92NPYMdl32YDZYdl32dnZUdq72jLbqNvw2yfcgtz+3J/dW94e3+TfxuC54X/iKeOv4wHkYuTy5JXlC+ZB5ormAOdz59fnMOh66K7o1+gO6VfpkunK6QDqXuoE653rHuyE7LvsL+3j7bDuh+8t8LvwOvG88VHyu/Id82/zh/Og89LzGfRh9KP0BPWM9Tf29vaN9wv4ffjW+CT5cfm0+dT55/kn+tT66vss/XP+yv8zAaACAQRGBYkGxQcJCXoKCwymDSwPchBzETkSxRIjE1kTnhMYFI4UChWZFRQWkBYRF5cXFBiJGN8Y8hj3GCwZlRkDGmIashofG6wbPRzVHEUdmh3gHQweIh4LHvUdJh6YHgQfPh9oH50f2x/8H8gfWB/THm8eLR7pHcAdyB0LHnYe8h59HxggpSAIITchLSENIfgg4SDpIPAguyBlIPwfhB8RH7QeRh62HSwdzByRHFcc7RtcGwMb+BomG0sbNxsBG8kavBrOGuMa7xrYGsMaxhrWGu4aDhtgG70b9RsWHEUcnxz5HF4d5x1sHvEeTx9wH1kf7h5nHuwdYh3JHCocfxvtGkUagxn4GIMYJBjTF48XfxeAF1QX7hZdFsIVYBUTFYUUuRP4Ek0SjhHFECAQuA9ND8kOFg5SDdgMqQyZDI8MhgxzDFEMIgz2C8ILmQuOC3cLNgvSCnIKPwogCu0JvAmVCaUJ3gn/CUQKgQp3CkwKCQq5CXsJQwnzCJ4IZwhJCEQIUghPCDYIQAiUCAMJVgl5CX0JkwnFCeoJ/wkPCh0KOwpHChsK6wnjCekJ6Qm5CYMJWgk3CTQJPQlcCWkJPgkACdoI3AjKCFcIjwfjBmMG6QVvBeMEcQT8A1gDtgIhAnQBwQAzAKr//v5H/sr9kf1S/fL8ifwR/Jf7Ofvc+mL60/lT+fP4efjf9yv3Zfa59ST1ufR49Cb0p/P08l3yFfIP8jfydPKu8s7y0PLY8vTy/vL48vLy7PLx8gbzJfNq88bzF/Rs9ND0KvV09cv1KvaW9hD3iPfv91j4l/ig+J74ivh++Hn4gfiL+Hr4UPg0+GX4lviF+FP4MfgT+Nn3lPc298b2bPYz9j32ZvZ69mv2F/bA9Zj1tvUk9s32o/dM+K748vga+UL5e/mR+ZL5ivlW+Sr5Cfna+LX4mfhy+Cf4sfc498z2U/bT9WT1IvUm9Wn1wfUG9g727PXC9Yb1QPUA9cj0bPTO8yLzyvKs8pDycPJM8hnywvFj8fzwlfA/8APw5O/77zvwXvBj8FXwP/BV8JrwzvDQ8JbwS/AL8N3v1u/I75HvKe+l7kXuJO4z7lPufe6i7r/u2e7T7svuwu6o7pjuhu607kPv++/D8F7x1PFC8o7yxfLW8rnyp/LE8gvzdvML9KL0//Q29Vv1a/VH9Rz1CvX29Bb1e/Xd9Rb2NvZR9mD2f/bG9kb38/dx+L74//hC+Z351/n6+fj50fmv+br5K/qo+vn6Xvvv+438MP3I/WH++/6N/wkAZQC0AOsAFAE3AWABdAFfATwBHgEyAU0BSgFIAV8BnAHQAfQBIAJpArkCBANKA4sDrQOzA8QD0APyA0kEtgQIBSkFSQVcBTwF6QRYBLQDHgOcAkACJgJCAlsCOQK9AQsBXQC7/xf/gP4R/tX9yf31/Xr+Cv9X/4r/uf/q/ygAaAChAL4ApABtACsA5v/d/xUAIADn/7//4/9PAKIA1wAoAYIB0wEGAgMCywGiAb8B5QESAmMCxQIWAykD+ALLAgIDjgMOBHYExQQFBVwFzgVwBiMHmwfCB9QHLAjZCKEJMwp+Cr8K+AodC1sLmAumC4kLTAsmCyoLOwtIC08LWAtqC4MLpQutC4sLZAtECyQLEQsTCyoLSQtVCzEL5gqRCi8KAQoDCt8JxAnJCesJCQrwCbgJownLCQQKDAoJChoKCwoBCg0KHgomCgwKwwlJCdUIgghGCBUI4geRB1IHWQd8B4kHgQdqBycHzwadBrMG4wb5BvgGCgc9B4gHwQfvB0MIwwhuCecJGAodCh8KYQq5CuwK4wrHCrAKowqYCnsKXwpJCjsKKAoGCrgJOAm7CHIIOAjUB3AHHAfFBmsGDQa5BXAFNwUOBeEEvgSzBKwEuAS0BHoEEAS9A5cDagM8AyoDTQN/A58DvQMBBGgEsQTMBNkEQQXXBVUGzwY1B44H3QdACJsIwwjcCCUJngkoCqEK4wr4CvkK6grYCusKFws4C24LwwseDIsM5QzvDMAMfAwoDNULhAtdC2kLiwuaC18LAwubChEKpgmhCdkJ6wnQCc0J8gkoChkK0gmaCV0JPQkTCccImAhmCD4IMQg4CE8IXwhqCFQICgi9B6IHiweBB58HpQe2B7gHaQf4BqkGiwaEBowGpwbxBiIHKgcNB68GRgbsBaoFcwUsBbwEIgSlA00DCgO+Al8CAwLMAbUBlQFuAUwBGgHyAMYAewA0AMr/Tf/g/nb+CP6C/dX8Fvxq+8L6N/qz+R/5afho9zr2+fT1803z3vKZ8mPyO/I98lryMvLf8Y7xIvG28HPwf/Ch8Mfw7vAZ8Xnx//GJ8uby8vLI8qPyvPIY85/zRfTs9H319/VX9rb2Bfc391b3Yfd796/39vdA+IX4pfiO+Ev47vdm98j2Rfai9fP0fPRG9F70nPTN9Oj0HfV+9eL1Evb+9QT2T/aR9rT2vPbO9gT3Yffg91L4o/jC+Mb4svhw+B/4y/eK94736Pc8+FX4dvjR+F350Pkl+mf6hPqD+o/65/pv+9z7Fvwt/EL8NfwI/NL7nvuD+5v72/vy++r72vvV+wz8SvxH/Aj8n/sU+4r6DPqU+S35y/h7+Dr49fec9zn35Pae9nT2W/Yw9gv26vXL9cn1xfW09Y/1XvUN9aL0OfTP81bzx/Jc8hLy1fF68ebwOfCn733vmu+179Hv8e/w78Lvke9k7yXv7e7Z7gXvSO+Y7+Dv9O/17+Dv3O/m7/zvIPAM8OPvzu/K79Hv4e/07xPwJfAq8EDwafC/8AXxKfE88S/xIfED8brwf/B58JLwuPDC8JHwOfDl76zvZ+/q7ojuh+7P7iTvUu9x74jvqO/X7w/wZvDA8BvxuPFQ8rryEPNp89fzJ/Sp9E71uPUN9kb2ZfZz9nb2fPZf9kf2Z/ah9gz3ofc5+Nf4dvkA+nz69/qJ+zr80Pw9/YP9rf30/Ur+o/4C/y//Qv9U/3T/tP+//5n/a/8s/xv/J/9J/4n/2P8jAGQAwgAFAf8A8wAhAWgByAEsAkoCXwKWAuYCSgOWA6oDkwN0A3UDhgOwAz8EDgXOBZEGfAdlCCsJ7wm9CnEL+gtEDFwMnQwrDdwNUQ57DqYO7Q5eD94PRBB9EKAQ1BA0EagR6REAEj0SjhLjEloT2hMyFJAUHhWyFVgWJhfiF2MY4RiUGaAazhuuHF0dCR69HmAf3h9TIKUg0iDkIAAhTiHCISMiUSJkIm4idiJ+In0idiJtIlsiKSKwIRghoiBDIKof1R7dHcgcwxvaGv4ZPxmtGBwYdhfTFiYWiRUjFdQUiBRIFB4UChQ0FHgUjxR2FFkUXxRUFD4UXxSXFLIUqBR1FB8UvRNZEwITqxJqElQSNRIRErURARFhEA8Q8A/mD/0PIRATEOAPnA94D44Phw9ZDyIPwg4hDloN0wyZDHkMWAwyDC8MNQwhDA0M9AuxC10L/gqjClgKFwq6CUQJ/AjcCK8IWQjqB3cH/AaIBiMGrwVWBTAFAwXHBG0EEgTGA3gDSwMkA/4CugJOAuUBgAEcAbYAagAlAN3/iP8l/6L+6v07/aL8Pvwj/BP8AvzZ+637oPuB+x37pvpO+iL6Ofpv+rn68/r5+s76ffo2+vf50vmv+XH5M/nn+J34Xfg6+E/4avhx+G/4Y/hv+IH4aPgI+IH3BveE9h72+fXw9db1s/Wu9bH1mvVf9Qn1ufSN9Gj0D/SY8x/z1fLH8unyPPOT87jzivNM8zrzMPMU8xLzSPOq8/fzCfQe9ED0aPR99H70gPRp9EL0KPT988Xzt/PN8+/z/vMF9C70YPRx9Fn0EfTM87LzofOf87Hzw/PZ8/rzOvRo9Hj0iPR89Fn0IfTg89Dz/vNJ9Lb0IvV39cL1BvZg9pb2nPal9on2VvYE9qH1bvWW9Qf2bvbA9hX3VfeF95j3fvdU9yT3KPdt98D3B/g6+FH4YPic+Of4GvlV+a/5MPrM+mX75/tg/N78bP0V/qD+1v6z/lL+3/1p/fz8sfxZ/Pb7rPuC+2/7cft6+4r7lPuP+5H7nfu8+xP8ivzb/An97fyg/Gf8Kvzw+6j7ZftA+yn7NvsK+4H6Avqh+Vn5AvmG+Bj4zfeq94D3QPf29qX2dvZr9oH2m/au9rn2vvbJ9sv2xPbP9u/2MPdz95b3uffZ9wD4Pfh6+Nb4bfki+qv6Ifuw+zj8tvwP/VD9ef2V/cn99/0Q/jj+TP46/hn+Af7b/Yz9Jf39/BD9Ef01/Vv9Z/2M/an9r/2S/Vr9Cv2Q/Av8mPtp+2b7SPsy+y37EfvR+pD6Vvoe+if6cfrA+ur69/rj+r36t/rG+sz6s/qe+p/6uPrB+s76IPuj+zP8hvyF/I78u/zN/KH8dvxs/IP8k/xr/DX8FPwI/CH8VPyN/PH8gf0J/pH+GP+P/9L/2f/u//j/3v+9/5//lv9i/9z+Yf4G/qn9Y/0z/dn8ZPwJ/Mr7mvt8+2f7Zvt9+4z7pPu/+7/7n/tv+1X7W/uJ+9L7G/yH/BL9rf1F/rb++P4w/1//jf/k/ywAQgBNAHQAowDtAGwB8QGRAkMD8QORBAMFWQW4BSgGfwaUBmQGLwYtBjAGBQbUBb0FtgWtBYMFSAUaBe0EvgSpBMUEIgXLBbMGmwdgCOoIQgmNCbcJzwnmCQIKQAqRCv4KfgvmCxMMEgzfC3YLPgszCxML4gqzCqcKxQoQC3gL/QuBDPoMZQ2jDdsN8g3zDQoOJA5RDpoO8A4UD8IOSA7kDWwN6AxjDPwLngtCC/sKxQrOCgALEAv5CuEK3QrlCvkK1Ap5Ci4K4gmKCUAJGwn7COkI9QgSCTcJPQlOCYYJ2QleCgsLvgtbDAQNtQ1ODqcOuA6sDpAObA5cDl4OQw4JDu4N8w32DQYOIA4FDpgN9AxNDNgLhAtMC0YLewvMC+sLzwuaC2ALIAvNCmwKAQqfCVoJKgnZCFQI0gdDB7IGVgYZBuAFqAWhBdkFKgaJBsUG3wbyBhsHWweTB6EHgwdTBxIHtgYyBp0F/ARNBKwDSgMXA9ICZgLRARQBSQCE/8X+Av5s/RT9wfw7/Jr7+fpQ+sv5bvkW+cL4h/h2+Gb4V/hx+Ir4dvhA+AT4Cfg0+Er4V/hP+Cz45ffA99L3APha+Mr4NvmW+eH5Gvpd+on6dfpF+i/6QvpH+nf64foR++n6rfqY+n76P/r0+aD5Yvlf+Wn5ZPlL+Qn5t/ho+DD48/d99w/30vak9mL2F/bT9a311fUJ9hD2DPYi9k32WPYh9sv1aPUg9Qf1/vQG9Ur1sPUA9jv2RvYz9gn2ufVv9Rn13PTC9Nb0MPWf9e31B/YR9vv1qPUq9Yr03vNg8wfzqPJQ8ijyOvJp8nzye/KZ8tvyKvOY8yH0pvQ/9eb1q/Z09xf4pvgv+b75O/qi+gD7QPto+3/7gft0+3v7zPti/AT9p/0//tr+bP/p/3sAGwHZAakCSQPaA24E4wQjBRQF0QSZBFsE/QO0A4QDTQP0ArgCvAK9ApcCQgLWAVgB5QCcAFUAHADq/6z/cv9A/yX/GP8S/wb/8P7k/tr+qP49/sf9TP3B/FX8G/zo+5f7Ofvr+qb6Ufr4+Zz5a/lt+Vb5P/lA+Wj5rPnN+c/5rvl++Wn5TvkT+bf4b/hr+J74v/jU+An5N/lI+TD5HPk5+Vz5h/m/+ez5LfqR+ur6P/uh+/b7Uvyh/Mn88PwS/S79Wv2X/e/9Xf7C/gD/GP8n/0//lf/h/xQAWwDJAE4B9gGuAlkDzwM2BKIE4QTxBOcE6QT8BBwFQAVEBSwFFQXvBOUECAUQBfoE5AToBPsE6AS9BJEEkATYBCsFUAVXBVsFbAWBBYQFgAWGBZkFsQW6BaMFbAUoBe8EvgSxBNYE/QQcBUAFfQW4BcYFtAWSBYYFsAUMBqMGXgcICJwIEwluCbMJwgmtCdkJNwqBCqoKxwoHC1kLuAsWDFMMdQyADHgMfQyXDNcMPQ2cDecNKA5YDmsOQg4GDvIN9w0MDhcOKw56DuYOMw98D9sPFRA4EEUQVBB9EJ0QsRCcEHAQQxD/D7IPeA9fDywPsw4WDo8NDA10DPALsQulC6YLkAtDC98KeAroCU4JxghpCFMIQQgICLYHawcsB8UGNAa9BV8F7wR0BA4E7AMCBAsE7wOvA1YD5gJqAu4BZwHmAGAA3f+E/1j/Rv8R/7/+if5i/iX+sP0m/Zr8Cvyk+0H7tPop+r35aPk6+Sv5HPn9+Ov45/jG+If4W/hc+Hv4rfju+Cf5Rflj+YD5k/my+df57vn5+RT6OvqL+vT6SPty+2L7RvtD+0L7HvvQ+nz6NPr1+dr51/nd+b/5avkP+cj4tPiq+GL46/dw9wT3jfYJ9or17/RX9BH08/Ov8zDzmfLu8SjxevDb713vGO/p7tDuxe607prua+457gnu7+3z7eTt0+2w7X/ta+1r7XnteO1z7aLt8+0d7inuE+7S7dDtI+6D7r/uyu7u7invUe9k71fvN+8X7xnvOO9r773vKPCY8OPwCfH78LfwXvD/78PvtO+U72fvU+9P73Hvse/l7wXwKvB48M7wGfFh8aXx6vEW8kPyfPK78ivzrvMc9Hf02fRR9dX1cfb19mL36Pdq+Pb4oflk+i371ftu/Bj9sP0j/n/+u/7n/hL/UP+6/04A3AAmATQBRAFoAZAB2gFCAp8CBgOCA+UDNwSzBEsFwgUVBnEGwAboBhAHVQfIBzwIpggVCZIJJQrNCnkL9gtBDH8MwwweDW4NmQ25DdEN+A0/DloOQw4TDuAN1Q3LDc0Nzw3CDbUNpg2zDdMN6A3fDdoN3A3lDQUOHQ4JDtENwA3YDfINHg5SDnEOng7iDkIPoQ/SD/gPHBA9EFQQXhBmEHAQohD1EF4RuRH1ERsSORJGEiQS1BFbEesQlxBLEAkQxA98D0APJQ8sDy8PJQ8hDykPSA+QD8EPvw+uD6EPfA9ADwcP1A6tDpsOnw68DuIODA8oDykPMg9YD50P8A8VEDEQdBDKEBkROBFUEXsRmxHLEewRBBIuEoAS3hJEE7kTIhRtFLEU3RT1FCkVcRW8FdoVwRWCFSAVwRSDFFcUWhR7FIcUhBRlFDcU4BNlE+4SbBL9EYwR9BBcENMPUg/fDmQO7Q2TDUUN+Qy7DHkMIgyvCzYLuwo+CtsJeQn6CHoI9AdtBxIHrAYZBl0FkgTdAyUDUwJ8Aa8A0v/2/jD+Z/22/B/8iPsG+7f6evou+r35LPmc+A74afd/9nX1m/TR8+jyHvJ88fvw0vDe8Ozw5/Df8NjwlfAg8KbvKu+l7jHuuu1O7RztH+0r7THtFu297F7sDuzJ65frguuO66frvOvL69Prs+ui67fr0OvY67rraOsM69Dqt+rI6ufqGOtP63LrcOtE6w7r0OqW6mDqUuqK6tfqLeuD69rrUuzj7Gvt1+0o7lXueu607hPvou9K8OHwHPEY8fjwsvBc8BrwHvBc8JfwsvCu8JbwfPBP8OnvX+/Z7lfuA+7T7cvtBu5h7sPuCu9M74/vxO8d8HfwxvAB8RfxCfHy8Ojw5/DY8LzwwPDZ8ODwxfCm8LTw6fBD8aLx+fFZ8rHyAPND84DzmfOP87/zG/Rc9ID0hPRr9GP0ZvR29KL00/T29BT1S/WY9ff1UPZ09ov2tfYA92j3tPfR97v3pve79/T3SPi2+Ez57/mR+h77evu6+wn8dPzA/PH8K/1n/bX9Gf5t/qP++P5m/8P/EQBqAOQAewErAsUCHQNLA3wDswPyA0AEoQQIBU0FfgWWBZwFpAXPBR4Gawa4BhkHkQcKCIwICAlsCdoJXwrjCkgLogv0Cy8MPAwgDPgLuguAC34LrgsNDHIMygxGDdgNXw6uDsIO4A4JDykPGw/hDrsOmg5oDjkOGg4gDicOEg70DdkN0A3kDe8NyA1SDZ4M9AtqCwwLywp4CicK5wmXCTIJ0wh9CEUIKAgHCMgHXQfhBm0GHgb0BcEFfQUpBdEEpASBBEIE/QPnAysEfQScBH0ENQQUBB0EMQQ1BDIELAQOBPcD7gPTA7UDuAPRA+sD7gPbA74DmwOZA6YDtQPZA/8DOgSNBNUEDgUrBT8FUAVDBTkFPgVGBWoFtwUlBqgGKwe3Bz8IwQg4CZgJAwpLCnQKqQqzCqcKtwrXCuYK5Ar0ChULKAsHC9UKnwpsClUKXQp5CoAKfgpbCgoKtgkdCUAIYgeoBkgGOAZLBo0G3QYOBxsH7QasBlwGDQbjBcsF0gXkBegF2QW0BX8FNwXfBHoEOwQhBCAEMwRrBMQEDwVDBWgFcwV0BVsFEwXNBJoEhQSIBIkEcQRVBEgEKwQKBO0DvAOUA3oDTgMwA0oDkAPZA/ED2wPGA6kDjAN8A3IDWAMuAwYDwAJcAhAC8wHsAf8BBwLXAZIBUwEpAfMArgB4ADsA7P+G/wn/iP4O/nT9pPzJ+yb7xfqG+kn6+PmK+Rb5yfh4+BL4nvf+9l324vWj9Yr1cfU09dL0ePQh9NTzjPNL8yPzD/P78uLy2/IC8zPzQvM/807zffPK8yr0evS49Pb0F/UH9df0j/Q59OjzuPO389Pz/fMy9F/0b/Rd9C/0+fPt8yP0fvTg9Dv1g/XC9fP1JfZb9pT21fb99iX3XPd090X3/Pbw9iv3bveH9373fvd292T3QfcO9/b24fa09p32nvaN9mj2NvbL9VX1AvW29F/0GvQG9P3z0POB80HzMPM5803zT/MW86zyTPIO8u/x3/Gt8W3xWfFb8VHxOvEW8dvw0PAB8UDxgvHA8fzxI/Jb8pHyl/Kx8vLyWPMB9Mr0evX09UT2rvZB98j3SvjH+F/5OPoN+7b7S/z0/IH9yv3z/RX+Mv5m/q3+//5r/8//KgCGAOgAUwHDAToCrAL4AigDOwM4A0YDZQNqAz0D/ALGAowCTAI5AlsCdwKIApYCtQL+AksDdwN2A24DeQN4A2EDTgNSA08DKQMAA9kCqQJsAkoCWQJkAjoC+QHVAdsBEQJvAs4CAQM2A5MDDgSEBNgEDAUeBRsFGwUhBSUFHQURBfcExASCBCAEtgN3A04DGgPtAtYCugKiApMCaQJPAlICPwIYAucBswGqAcIB6wE0ApEC/AJqA7AD0wP8AzgEdwSqBOQEQgWrBf0FQwaCBsQG/wYdB1kHxwdACKsIAQlWCaYJzgm6CZYJigmWCbsJ5QkOCkMKZwpwCkIK9gnfCf0JMQpBCkEKSApCCjwKKQr2CbMJcQlaCUcJGgn6COAI7QgfCS8JAgnRCLQIfwgeCKgHPwfHBkQGugUoBcEEkgR5BGYEdwR/BGYEQwQtBCwEJQQFBNcD1wMLBFEEtAQKBTUFPwU7BUYFTAU/BTAFJgURBfIEygR9BB4ExQNDA6wCFAJ5AQ4B4QDuAC0BXAFPARABsgA3AKP/I/+7/lX+7f1//QX9a/yh+7P6zvke+Yb47/dU98r2X/YJ9r/1cfUT9aP0L/S682zzU/NB8z/zWvON89jzLPRj9Gz0WfRI9EH0FfTJ84TzS/Mr8yDzF/MT8/3yz/Kl8oTyV/Ia8t3x1PEH8lHyxvI284zz5PMe9F30m/TM9Aj1TPWn9e/1O/ah9uf2HPdW9433vvcA+GD47PiW+S36rPo2+8H7F/xb/Jb8mfys/Ov8Wv0a/u3+q/9AAKoA6wAFAQgBCwE0AXIB2AFhAvcClwNOBCMFygVGBo4GvAYnB70HZwgECYoJIQq+CkkLsAvsCyIMWQyADKcM4AwqDW0Niw3BDSYOoA4cD2wPkQ+pD80P8g8CECsQbBCoEOcQGBEaEQwRABHzEPUQ6hDQELwQyRDnENoQpRBfEBEQww+DD0UP+w6zDnoOcQ6RDrwO6g4MDyMPFQ/dDqsOkA6VDsMO/Q4RDxwPOg9OD1gPZA97D5QPnQ+MD2YPLw/+DvIOEg9jD7MP7Q8qEFgQbRBgEEIQGRDUD50PeQ9RDycP/Q7IDpkOiQ6ADkwO5Q1wDQcNtgx+DGgMewyMDI4MlgyfDJ8MlAxxDGEMfAyJDHoMcAxbDDYMHgz4C8kLzgvtC/cLCAwFDP4LEAwVDBwMIAwrDD8MOgwlDAUM8Av1C/UL1wuECxoLuApbCgEKpQlbCTwJNAkjCSQJTgliCSAJkgjuB1YH7AabBjsG3AWPBVcFIwXXBFcErQMBA1sCxgEzAZgA//9n//H+iv4g/sT9X/0I/c/8l/xr/E38Ufxu/IX8qPzN/N781Py2/Hz8KPzT+3P7Hfvf+qX6XPob+uT5pvlk+Rr50fh2+B741/d79/X2cPYi9gT28PXc9ez1/fXt9bL1YPUj9cn0LPRu85fy0PFC8bbwJvCv7zzvwu5Q7v7tqu0v7bTsTez868zrwOu866frjOtu61LrTOtY62jrf+uU633rbuuk6/rrU+zD7CvtgO3k7VLunu6r7pfudO507pXure7A7sDute627r/ut+6Y7n7ugO6V7sTuCO8572/vt+8G8ErwePCh8Mzw6PAQ8TzxRfFa8Xrxp/Hx8SjySfJd8kPyEfLo8erxGPJB8nTyp/LC8t7y/fIq823zr/PS897z5fPV86LzaPM98yfzGfMG8/PyzfKm8qryyPIG803zWvNY81nzWPNU8zXzD/Pm8snyt/Jo8u7xmPFx8WjxavFk8ULx8vB38PHvdu8h7//uIu9178fvEPBK8KPwBvFD8WjxlvEA8oryD/OX8zP01/Rp9eL1ZPbd9kz37veZ+C35yPlk+gj7p/s7/MT8Gv1h/aX9wP3D/dH9E/6E/u3+Iv87/0r/R/8h/9L+if56/rf+EP84/zL/Fv/u/r7+jf5k/kv+OP5J/ov+0P4q/8r/pwCEAUYC/QKnAyIEZwS3BCMFbgWYBcoFAQYtBkgGUwZnBoAGkQadBooGUAYFBtQF0gXgBfYFDQbuBbUFrAXCBeoFEwYdBikGSwaGBu8GagfPBxEIMAg2CCEIAAj5BxwIWQiPCKgIrAi2COsIRgmjCf0JTAqgCt8KFwtdC5oL4wsiDE8MigzKDAQNQQ1xDYYNuA0kDpAOyA7VDtkO9A40D3IPmg+nD6MP1Q8nEF0QZhBMEEwQWxBfEHoQtBDvECYRMhEAEc0QshCYEI0QshDREMAQoxBaEO4PgQ8KD6YOZg5TDlkOUw5YDncOkw6cDnsOPA7/DcgNtg3EDbgNkw1pDUENNQ05DTINEg3eDK0MhgxmDDMM6AuZCzgLxQpNCuQJlAlGCfwIngjtBxMHQAaLBQAFiAQcBKkDOQP3AusCDAM5Az8DKQMXA/0C5wLVArQCgwJWAj4CIgLxAd0BzgGzAbYBtQGkAXMBCgGJABEAuv9x/zf/Qf9Z/zb/Af/a/rf+qP56/gz+gP0G/cH8rPzD/OH8AP0Y/R39Jf0+/Xr9wf38/SL+Hf4k/nX+3P4a/zH/Ef/s/u3+3v6m/lj+GP7y/c39qv22/e79Lf47/hD+1v23/an9nP2+/eH94f3T/c/96P0K/ir+T/6F/r3+1f65/p3+iv5n/kr+Iv4T/h/+F/4A/uj9z/2p/YD9Wf0m/d78mPx1/HP8WPz2+3L73/pH+sf5YvkY+d/4n/hG+N/3dfcH95T2Nfb39cL1jvVQ9fr0nfRJ9PHzmPNA8+nyiPIQ8qnxZvEr8ffwyfDD8OnwGvE28SLx/vDX8JjwZfBB8Dvwc/C/8AXxKfE08VvxpvEY8rvyU/O38wT0OfRv9LD02fTd9M30xfTB9Lz0tPSP9G30afRy9H70kfSf9Lb02/QA9Sf1RPVz9cX1CvY19kn2dPaT9oL2bvZn9nr2r/b29mL38/d1+O34VfmQ+aH5nPmQ+YH5e/l7+Yv51PlJ+rP6Gvtj+3H7ffui++H7VPz6/I399/1r/tz+If83/yj/Ev8O/yD/Nf89/1L/jP/v/1QAjQDCAPAACQEeAfkAuwCRAFsAPQBNAGIAfADAAAoBGgEIAQkBFQEaAQoB4wDKAMIAygDkAP4AGwEyARQB6AD5AGkBKAL6AsADdQQMBW4FiAWEBYgFhwV5BXEFhQXlBWcG9waFB/EHVQisCOMIAwkeCUgJfwmxCccJxwnkCRsKSwp4CpkKmwp2CjoKAAqyCVQJEQnzCAcJSQmTCcwJ6wkOCkoKiAqkCq8KrAqOCmYKQgoaCvAJ2gnXCb0JjwlwCWwJcwmECaAJ1gknCowK7wpQC60L1gvCC6QLngutC7MLrgunC60LyAveC/EL+QvuC9QLtgulC6ILsgu4C6sLnwuOC5ALpwu/C8sLxwu+C6oLfAs9CyYLOAtLCz4LLAtFC20LeQs6C9oKfAoNCqkJQAnYCIkILgjKB30HHge7BnMGJgbVBYUFRQUlBRgFPgV0BYMFXwUqBfoEqARjBEgEOAQpBAIErQNBA8sCWwIDArQBZAEEAcAAogBxADcABwDu//j/FwAxADgAQQBtALIA0ADCAKYAeAA2AOr/nv9l/z//N/9N/4L/xP/6/xMAEwAJAPX/3//J/7j/pf+X/47/ev9r/1r/Kf/3/uj+6/73/g7/LP9G/0X/O/83/zr/Nf8k//z+wP5+/kT+K/4j/hL+/v3j/av9fP2T/br9tv2j/ar91/0W/lH+cv59/m7+RP4S/tj9jP0n/c78mvxe/CH8A/z7++H7oPtF+/X65Pr0+tr6qfqa+qP6svre+v/63/qC+v35d/n8+JD4Lvjf97z3xPfq9xT4Qvh2+JH4pPiy+Lb4rviZ+JT4sfjo+An5EPkb+TL5Uflr+Yj5tPno+Qn6GPpC+oH6yvof+3n72Psl/Gz8rPzu/Dn9lP0U/q/+X//t/1QAxwA5AbABIAKNAugCMAODA88DAQQoBDEEDgTgA54DNAPPAnwCSgIuAgsC8wHxAScCXQJlAl0CUAJEAi0C7wGwAZQBkwGuAdgBDAJGAmcCYgJFAi0CIgICAugB8gHuAdYBrwGHAVkBEAHCAHsAMADv/8H/pP+K/2D/S/9P/zr/CP/T/q3+hP5L/g/+z/2U/XH9Vf1a/Xr9hf2D/X39gv2Y/aH9lf1g/ST98fy6/JP8afw2/BX8Avz++/774vuw+6j7uvvB+9X76vsO/Gf81vw1/Xn9sf34/Vn+mv60/ur+Jf9Q/2X/Zf9l/2n/i/+q/6f/dv8c/+H+vP6G/kH+9f2r/V/9Mv0b/fj8zPyZ/Gz8L/zm+5z7Rvv1+qn6g/py+mf6avpd+j/6Ffry+dz5xvmp+Yn5fPmE+X75a/ln+Xn5mfm1+cT5y/nT+fb5APrS+Zv5evl1+X75nfnM+e35/fkL+ib6Mfok+iX6QPpb+lf6bfrK+kr7tvvj++37F/xo/Mj8Hf1o/ab9xP3F/cb9xv2x/Wr97/xf/PX7v/uD+zz7+/q3+mr6GPrw+QL6Nvp7+sD6AvtA+3z7i/tw+0L7CPvb+rj6rvq8+t/6DPsy+037TPtN+1b7Z/uJ+8j7Ovym/OP88vwM/VP9lf3J/RX+a/6v/s/+6f4B/wD/8/7o/vT+B/8Y/xz/Dv/2/sn+i/5X/jT+HP4g/kv+cv5+/n7+gf6M/qn+6P4U//3+y/6V/mT+Vf5f/nH+c/5O/gX+zP3G/cL9vv3Z/Q7+Zv7E/g//R/+I/8D/wP+t/9T/+f/x/+D/4P8fAHgAwwD3ABQBTQGeAQACYAKNAnYCOAIUAiwChgIFA3gD2gNEBLYEEQVeBZQFoQWXBZsFwQXzBTwGmwbwBh4HIAcoBzAHIgcIB8kGZgbtBWEF8QSnBIMEhQStBNkE8QT/BP0E9QToBNUEuwSMBEIE6gOjA5ADpAPTAxYEQQRJBD0EKAT7A7YDeQNlA2UDRgMCA7oClwKQAocCcAJXAkICNgI0Ai4CPQJIAigC+gHLAboB0AHkAe8B6AHVAbcBfAE4AREBBgH+ANYAiwBZAEsANQARAP3//f/f/6b/hP9u/3T/lP+q/7H/wf/o//3/9f/K/6r/vf/X/+f/5v/u/xIAMgBWAH0AnACXAJAArwDSAO0A8QDqAO8ADAFOAZQB1QEEAggCEQJHApMCywL3AiIDJQMUAwYDAwP2As4CqwKjAswCAgMyA3IDsQPHA78DoAN0A1IDJAPpArMCgwJCAvgBwAF2AQMBhQAeAMX/S/+s/vn9Lv2C/CP82Pt9+yL71Pqb+mP6Hvra+a35kPlg+RT5s/hd+BP4zPew97L3v/fU9/n3QPif+Oz4+fjL+H/4TfhX+Hb4oPjS+AT5TfmK+dD5Jvpd+nj6fvqF+rP6CPtu++H7QPx6/Lz8FP1o/aD91P0p/or+2/4v/4n/5/9MAKgA6QApAY0B6wEaAkwCgwKsAtkCHwORA/kDJwQpBCUELAQVBOcDuAOLA2IDWgN/A7wDFQRxBMwEHgVeBaMF3gX1BeEFwAXEBeIFBAYaBicGHAbwBbwFjAVvBWwFjwXHBeQF9AUABvoF9QUABhAGJgZYBooGpwbOBg4HUgeZB9sHGQhvCL0IEgmMCQUKWApeCkgKOwoTCtcJrAmHCWQJKwn1COIIxAifCIMIYggvCN8HmQd2B0QH/Qa8BnkGKgbRBXcFNQUXBekErASIBIMEZwQZBLQDSgMKA+cCvgKOAk0CAQKnAUwB8ACdAGQAFgCj/zv/B//9/hb/Of9O/1D/M/8Q/xH/Gf8G/9n+pP5z/lb+X/55/p/+5f4p/0v/YP91/4j/r//5/0sArwAsAawBEAJBAkYCMQIvAlkCjgKzAuICFQNDA4gD5QNUBNcEagUGBmMGjQa0BugGSwfEBx8IXwiXCMgI/QgmCTIJGgkBCf8I8wjFCKIIiwhPCBUI7wfPB7gHgwcoB7sGSwbkBYMFFwWrBDwE7gPgA9YDsgOVA4EDXQMnA+4CpAJGAskBIAGEAA0Ao/87//z+7/7//vz+5f7F/oX+VP4n/ur9xf2j/W/9Rv0p/Qf90vyT/ET80Ptq+zr7PvtP+237nfu5+6r7k/uJ+4T7nPvH++P77Pv6+/378/vy+wf8Pvxw/Ij8tPz1/Dz9hf3D/QX+O/5o/qP+/P6J/xoAgQDCAAUBcAHoAVkCzgJDA6UDAwRFBH8E0gQqBYEFrgWnBZMFrwXjBekF4wUABjsGewauBs0G7AYEB/0G5gavBnEGPAbrBY8FHgWFBNADMQPDAngCSQIVAuIBxwG1AawBpAGWAZgBlQGHAYMBeAFnAVIBPQEoAQIBzQCSAEwAFwAGAPn/1/+Z/2v/fv+v/9b/9P/4/+v/7f/u/9H/gv8q//3+1/6y/oP+Sf4N/s39kf1c/TX9Cv3d/I/8E/yp+2L7Nfv++sD6jvpo+kT6CvrG+Xz5PvkM+db4l/hE+MX3MPeg9gT2XPXG9Ez0zvNQ89jyWvLs8bHxjvFd8RPxxfB38BjwtO9V7/fuoO427rXtSe0I7c7sqOyq7MDs4+wR7T/tdu3e7WPu1+4374Xvze8u8MLwYfH/8bDyRfPC80j0vfQd9YD13fU99pz2/fZ69wX4kvgZ+Xf5pvm0+ar5kvmV+cX59vkW+iD6O/qD+vf6fvv7+2b8rfzz/E39nf3c/f39Ev4q/jv+QP4b/t/9s/2m/cr9EP52/tX+Iv9s/5f/nv+b/6n/rf+u/7z/vf+9/7H/lP9o/yL/7P7K/p7+Zv4e/tj9nv1c/QL9nvxF/On7j/tF+/f6rPpy+kP6A/qc+fz4MviC9/z2f/b19Vz10/Rx9EL0I/QF9OvzwfOS817zHvPN8oDyTPIj8g7yD/Iu8mPykfKx8uTyJ/NP823zlPPI8yL0kfT99Fn1sPUa9nv25vZe99T3dfge+Z/5+fk5+oL65/pb+8X7D/w5/H38+PyN/Sn+xP5U/+z/hwAPAYkB7QE+AogC9QJ4A/MDbwTRBB0FcQXNBSgGiQb3BnQHBAiKCPUIUwmtCQMKVgqoCuwKKgtqC6sL8wtBDIIMrQy5DLoM0QwEDUsNkw3JDQAONw56DsYO9w4VDygPRQ92D6gPzQ/pDwwQQxCCEKwQvRCzEJIQgBCPEKoQyBDgEN0QsRBeEAAQsQ9+D1gPPw83DxUP2g6XDlUOEw7ZDbANqg3BDecNHA5MDk8OFw7EDVcN2wxgDNQLRwv1CtUKzAq6CogKWAozChEK1wmRCVQJFAnMCIsIWQgtCAUI3we8B50Hewc/B/UGyAarBrAG1AbgBs8GywbVBsYGmQZbBiIG/wXqBdMFxQXFBbwFiwVKBR8F7ASPBCUE4wPSA9kD2APEA7oDzgP9Az4EkQTdBA8FMQU+BT8FSAVzBaoF3wUdBjcGPwZSBnsGnwafBokGcgZ6BoUGdQZlBnYGoQbUBgoHHgcYB+4GqwZ5Bm4GfQaIBp8GpwaPBm0GRwYtBg4G4QWqBYYFXQUMBcMEcwQcBOQDrQNoAxgDugJKAskBOQGNAOT/WP/t/pX+If6O/fT8fvwm/MX7S/vM+lj63vlS+az4CviL9x/3w/Zu9gj2mvU+9cv0KfRl85jy3fEp8Yjw7e8673/u3+1i7dvsWezt64rrPusF687qcur+6ZTpSOkd6ffo3Ojk6CLpe+nJ6QrqQOpp6qXq8uo563zr0OtF7J/s2OwX7XftAe6o7krvzu9S8NfwYvHf8T/yp/Ie847z7fNI9Kv0JvWn9Sf2kvbp9jv3kvcE+GT4rfj9+G359Plj+sf6Ivtd+5D7v/vp+xf8Vfyz/BD9ZP2k/cL95v0J/hL+Df4B/vD92f3P/e/9G/4s/jn+Vf5y/mn+M/4H/u/94f3Q/ar9kP2N/Zv9qv3A/fT9Nf5q/pn+nv5m/jL+KP4U/un9x/3F/dX95v3x/fH99f3w/eH93f3J/aL9d/1R/Tr9Jv0U/fv85vzQ/Kz8dPwn/PT76fvt+//7JPxN/In85/xg/dL9Lv5x/of+jv6r/tr+Av8S/w7/Bv8N/0H/kf/m/0kAqwAOAW8BxwEPAlICoQL8AlgDpAPmA/wDBAQsBHEEwgT1BAsFNAV+Bb4F9gVABqEGBgdPB14HRQcwByYHLQdPB20HdgdbBxwH7wbhBusG/wYaB1oHugcqCIkIywj5CAUJ/QjyCOEI3QjtCBIJWAmuCRMKgwrkCiQLOws4Cz8LRQs5CxgL9QrpCuQK7goFCxoLJwtFC30LoQupC5gLlAukC8EL9AsmDFcMagxsDHMMWQweDMILNAumCi4K2gm/CboJwQm8CZIJVQkiCQ0J+Qi6CGYIHAjKB54HqAfEB90H0wevB4MHXgdQB04HOgcfBxUHDQf7BtcGnwZ2BlcGPgYqBv8FrQVpBUUFKgUkBSUFJwUgBQgF7wTHBKMEmQS6BAIFRgVYBT8FNAUzBSsFKAUwBTQFGgXwBN0EBAVqBdMFEwZOBo0G0wYRBywHNgdAB2QHowf3B0sIhQiiCKkIuwj1CFAJzwlICpEKxgrvCgsLMQtrC5YLoAuiC5cLeAtLCxQLzAqACiwKxQlICcUIbwhOCD4IJgj2B7UHcQcgB8wGdQYhBs8FfgUbBY0E/gOHAxMDhgLiAWMBHgHoAKQARwDq/6P/Uv8D/8/+tv67/tT+8/4K/wr/+v7r/sf+mv5w/jv+Dv7l/av9WP0G/cz8l/xc/B38yvuE+2j7f/vE+xD8U/yf/Pj8L/0s/RX9E/0T/Q39A/3o/Mf8rvy2/Mr8zPzA/Ir8T/w5/Dz8VPx4/Kn84PwC/Qn9A/0E/RH9Iv0o/Rv9//zd/Kz8W/wP/Nf7pft4+0L7G/v9+rr6XfoH+rf5evlY+TL5+fiz+HH4OvgX+PX3m/cP94f2I/bk9b/1l/Vv9XL1pfXb9fT14/Wl9WL1LvUd9TP1WfV99Yz1kPWY9Zv1ivVv9VP1KPUP9Qr1CvUU9RP1D/UR9RL1/vTT9Lz0sfSj9Kz0vvTG9NT09/QZ9Rb1BPXy9N30vvSc9IL0ZPRC9DX0FvTB817z4/Jp8hzy1PFz8RPx2fCW8Dzw3++B7znv7e6G7gLuZe3L7GfsSOxR7EfsKewj7DbsX+xv7Efs7euF61Hraeuw6xTseezV7B/tT+187aPtse3A7dXtA+5c7rzuEe9E713vi+/J7/vvCPDo777vre+j763v6O9T8NnwT/Gt8QPyZvLQ8jPzjPPi8zP0kvQF9X319fV89g73kPf29yn4VviD+LL49vhD+Z75BvqG+gr7i/v8+0v8dvyN/LP8y/zW/Pb8KP1s/cX9Sf7P/ir/gf/q/2YA9wCpAXsCUwMcBM4EbQUIBqQGQAfFBxYINghGCG4IpAjVCCIJlQkHCmEKhgptClMKXQpxCoIKfwp+Co8KpArJCvMKLguQC+oLHgw9DFMMggzGDO4MEA1CDYwN2Q0hDlwOiQ6oDtcONA+JD8sP4w/iD+sP/Q8gECkQExD2D80Pmw9bDw0PzQ6zDrQOvQ7PDugOEQ9HD3YPkA90DyUP1A6nDoUOTg4DDrENcQ0+DSANIw05DTwNGQ3zDNgMsQx/DGMMWQxiDHYMagxJDB8MBQwODB8MMAwtDCEMGwwjDCoMCgzTC4ELPAsbC/8K6grICrAK0AoNCxsL+ArXCsQKwArQCvQKJwtdC2wLUQs2CxML9griCrUKcgovCgMK2QmpCXkJUQksCRcJHgk7CWQJiQm7Ce0JLAp3CqkKvgrFCrUKhgpfCl0KhAq9CtsK5gr0CgwLFwv8Cs4KqgqfCpgKaAotCiMKSQpvCn0KYwo1CiAKJwoxCiUKJQoiChAK9Am+CW8JFgnXCKwIZQjuB3MHCgedBkQG9wWXBUIFDAXWBI8ESATjA2ED7AJsAvYBlAFBAf4AsgBSAOH/av/o/nn+E/65/Y39cv1T/S799/yf/EL88fuh+zP7nvoG+pH5M/nT+IL4TvgQ+Kz3IfeU9iL2y/Wi9Yv1cPU69e70vfSj9Hv0IPS182HzL/Mc8xTzEvMI8/Tyy/Ke8mjyHPLc8aPxWvH/8IjwEfDE76Tvoe++7/HvJPBC8FXwcPB88HPwZPBD8CrwJ/BF8Grwf/Cb8L/wBPFW8ZbxufHC8cLxzPHy8TDyiPLu8l/zx/MJ9C70SvRk9Hv0nfS59NH08vQZ9TT1SvVj9W/1ZvU79Qb11/Sr9H/0YvRW9Ev0SPRF9Ef0bPSi9MP00vTl9PH05PS+9Jv0mvS69Ob0/vQN9Sj1R/Vx9aP12vUT9kf2afZr9m72ifa29uv2MPeK9+D3MPh3+KD4o/ic+Kb4wvjn+P34Dfk6+Yr5/Plq+sD6/von+z/7Qfss+wD7z/q7+sf60/rS+sP6pfpo+gr6sPle+RX54fjQ+Nr4BPk3+U75Qfkx+Tj5Tflr+Z/51fn9+Rn6Nvpt+p76x/r4+iL7Kvsb+yX7QvtV+1n7VftZ+3b7oPvU+xX8T/yR/Nz8N/2a/eT9A/4I/gr+Ef4Z/hD+Cv4d/j7+Zf6G/o3+cv5Q/lP+Zf52/qj+/f5x/+7/WwDIADgBqQEKAlcCtgInA5UD8wM1BGcEjASrBNQEAAUwBVYFeAWPBacF3gUVBlQGmAbQBvcGJQdxB7oH+wcbCBcICggGCPcHtQdyB2kHmwfPBwwIWAiSCMAI1gjnCO0I0Qi3CJgIfAhgCFQIZwiHCKMItAjICNkI5QjjCO8IHglOCWwJewmNCaQJxQnhCfUJHQpQCnMKgwqpCtYK8wr3CtwKwwqpCpQKlAqXCooKgwqFCoIKhQqPCpkKrwrDCscK1QoMC2oL1Qs+DJQM2wwpDYYN7g06DlUOWA5lDoQOow6/DsQOwQ68DtAOBw9PD4kPsw/cDwEQNBB6EMgQGRFmEb8RBRImEisSHRIPEgcSBxLxEcwRohFxET0RCBHdEL4QqxCgEJUQfRBgEEQQDBDFD4oPbQ9YDzcPGQ/7DuIO0A6rDnIOMw4BDuMNuA1mDf0MlAxDDA4M4gu5C5gLnQvDC+oLAgwCDAAM+AvoC9ELpAtIC8wKQgqjCQkJZgjEB1AHEQfvBsgGpQaPBoQGhAaGBo8GogavBpoGXgYWBtMFlgU7BcwEYATyA3sD4gJGArsBOwHIAE8A2v9t/wT/rf5T/tX9P/21/DH8uftJ++P6m/po+j/6BPq0+VX5+PjB+Jz4d/hT+BX4xfd39yX33/al9lH22fVN9bz0LfSs8zLzuvJS8vLxkPFD8RXx6fCy8H7wSPAG8MjvlO9m7yzvC+8q70rvTO837xHv7u7Z7tXuzu637ofuWe5O7mLue+6T7pnuf+5Z7knuUe5P7jPuDe7r7ePt6e377T7uuu5H77nvCvA+8D7wH/Dz78XvnO+E73rva+9j72vvlu/c7xfwLfAw8D7wUPBp8KHwB/F98dHxD/JL8oXyrfK98rfyk/Jk8lDyXfKg8gXzWPOV88Hz5PP88/7z8/Pv8wP0L/Rk9Lb0FfVb9aT1AvZV9qD28/ZJ96T3AvhM+Hv4nvjS+AD5CvkB+fn48vgK+U/5kPmx+cL53/kH+jf6iPrx+mz74PsU/AT83PvH+7z7o/t9+0L7DfsR+0/7kPut+6b7iPtZ+y37Bvvq+uL64Prq+hH7QPti+2n7S/sV+9L6ofqZ+q36tvqb+nb6UPoX+uz52fnP+dr56vn8+SD6X/ql+uD6F/s4+0/7ifvc+zj8hvyo/MT8+fwz/WP9d/16/Wv9cP2j/fX9av71/on/GwCaAPcAVAHDATwCrQL6AjsDewPDAxkEawStBPUEUQWwBQcGUQaSBtMGGgdhB6IHzgfhB+AHxAegB38HagdgB0sHQAdIB2IHlgfVBzMIqggbCX4Jxwn+CTEKWgp3CpMKpQqwCqsKpwq6CtAK0wrPCtEKygrICuMKBAshCzELJAsbCxcLEQsXCyALIwsKC+YKxAqWCl4KOQowCigKIwoOCtkJnwlyCVYJTglNCToJFwnjCKIIYggRCLcHbgdGBycH+gbWBqIGZAYeBsQFcwUoBegErwRaBPkDuwOpA6kDjgNnA0wDPAM3AzMDMAMnAwoD3wLHAs0C3gLgAt4C1ALRAtkC1wLVAt8C6QL1AgsDFAMBA9YCmAJTAhcC5wHBAaoBnQGXAZoBqgG7Ac0B9AEpAmYCnwLJAgQDSgOOA9wDDgQ9BH0EtwTlBPcE5AS6BJcEjwSeBLIEwQTdBBcFagXHBRkGXQabBtYGBQcfByIHHAcaBwIH1AahBncGWAYkBtQFfwU4BQMF4AS/BJ0EfwRoBGAEUgRBBBwE4QOkA1sDDgO/AmoCLAIMAugBwQGvAbEByAHeAdEBqAGJAXsBWwEjAfAAwgCPAFEAIAAHABMAQQB5AKsAwgDAAL0AyADaAP0ANgFYAXMBowHpASECQAJVAk4CRwJOAkQCJwIGAuIBsQF6AVcBPwEYAewAtgB/AGUATwAvAAMA2P+r/3f/Qv8K/97+zP62/pr+l/6b/pb+jv5v/iP+0P2Z/ZT9jf1a/QX9lPwp/Nf7ifsm+8D6a/om+vT5t/lf+Q/50vie+Hf4TvgX+OH3rfd/90r3F/fw9tr25fby9uf2yPam9qT2uvbP9t/28/YG9w33FvcR9/D2wvaP9k32DPba9a71k/WI9YX1jfWh9aX1jPVz9WD1RfUh9Qj1G/VB9WH1fPWG9Xf1WvUz9RL1/vTQ9IX0RfQr9Cz0RfRp9Hf0dfRj9FH0XPSN9ML0yvTG9Mr01PTq9Pj06/Sy9Hn0W/RP9E30LfQC9OLz1fPY8+vzC/Qh9Dv0avSY9Kr0p/SY9Hz0VvQh9Orzw/O387fzqfO38/zzd/QY9av1GPZ09tz2P/ei9xf4gvgG+aT5Qfrp+nv74fsn/Hr88/x6/db9GP53/vz+m/9TACwBDQLdAosDGgSTBOUEGwVABWUFqQUbBqkGKwexBz4IywhaCc0JOQqqChQLdwvKCwIMKwxkDJcMsAy9DK0MkAx6DGcMTAwWDMoLbgsjC/YK0Qq1CpsKcwotCtAJWQnkCJ8IfQhRCBsI/wf6BwIIDQgQCPoHywejB5gHrAfBB8cHyQfRB+cH+QcPCC0IUAiACLgI7wgbCUEJYQl5CZoJtQnECb8JrwmcCZAJwAkJCi8KQwpTCoAKswriCj0LswsnDJAM5gw4DXoNog27DcMNvA2KDUQNJw0lDT8NZA1zDWkNUQ07DRsN+QzZDMIMsgyuDLIMngyHDIUMhgx2DEcMHQwQDBoMJwwuDEAMagyoDOAM7wzmDNwMzQy6DKQMlwyFDGUMSwwtDPQLtQuMC3YLeAuVC8oLAQwgDBkM8Au4C2oLGQvQCqoKrQqdCnoKfwqqCtcK/Qr5CtcKwArLCvQKGwsqCw8L2wqzCp8KjQqBCoMKfQpsClcKJQrKCWUJBwmzCIgIfgh6CIwIoAigCJEIfAhmCD8I+QecBzgH6Qa+BrwGwQasBnsGLQbhBY0FGwWjBDMExANJA8UCOgKYAesAVQDL/0//zv4s/mL9dPyQ+8P6C/qE+Qv5ffjs93j3F/ek9gX2XfXV9Hn0UPRH9EX0SvRV9Fz0YfRn9E/0C/S883LzGvOr8iTyjfEa8cDwbfAy8PXvsO9g7/3ul+4+7gru7u3P7aLtae067Qzt5OzX7Mrspext7EHsJ+z/683rqOt360jrNush6/zq0Oqy6qfqn+qG6nLqbupU6i7qD+r/6fXp2OnC6cTp6uka6jPqSOpg6oTqrOq+6tbq/uoX6zPrXuuZ693rIexS7Gnsheym7NvsDu037V3tcu167Yntue337RnuJu5B7n7uw+7s7g7vOe9t767v6+8u8Hrwv/Ds8BDxSPGW8eDxHvJP8mXyb/KJ8rjy3vIW827z3PNM9Jb0yfTh9Nr05/QU9U/1jfXA9dz16fUG9jH2XvaW9sz2+/Yj90z3iffh9yj4X/ip+PH4Gfkm+Tn5a/nB+S76l/ru+jr7gvvB+/37MPxf/Ib8nvy8/OT8Kv2I/cv98/37/f79FP4y/mP+nf7M/vL+J/+I/+f/MQBlAJEA2gAxAZYBCgJ7At8CMAN1A7kD6QMSBFUEswQUBW8FyAUZBnoG6QZSB7oHEQhpCMUIGgluCbwJCgpdCrAKDAtpC8ULIwyADOEMRw2fDdsNBw5BDpwODQ92D94PQRCPENQQDhE8EVERRBEfEegQvxC/EMwQxBCsEKMQlxBvED8QGhD8D9oPwA+xD7AP2g8nEGwQoBDWEA4RNBFWEXoRnBG1EcARxBHMEc8RuxGgEZwRpBGrEaoRnhGREYwRmxGoEZwRhhFaERQR4hDJELEQmhB9EE8QHhD8D+gP0Q+cD1IPFg/9DgoPJA8oDysPOA9UD5oP6w8hEEcQZRCFEJIQghB1EG0QcRB5EGoQTxAmEPYPvw9+D0YPEA/dDrMOgg5CDgYOyQ2aDYQNgg2GDYQNgg10DVINLg0HDeEMqwxWDPwLpAtZCzALEwvUCnEKCQqvCWAJ+wiaCFcILggMCNQHkAdUByQH6gayBowGZwZPBjoGKgY0BkwGXgZdBkQGJAb2BbsFjQVvBUQFBAXHBIwETwQTBNYDmgN7A4oDswPLA74DlwN0A2gDcwN7A2gDVwNbA2oDgQOSA4gDXAMYA88CfgIgArcBUAEKAd4A0ADaAN8A0ACvAJMAgwB0AFUAIADP/4H/VP80//z+rP5d/v79ov1X/fT8h/wl/ND7kvtb+yP76/q8+nv6Hvq9+VX59vip+Fn4+veS9zr3+/ay9ln2AvaW9Rf1oPQt9LzzNfO08kvy1PFk8QzxzPCH8DTw6e+y743vZ+9Q7zfvH+8a7w/v8+7S7sDuuO6z7qHugO5d7kTuSO5Z7n7utO7r7hzvLe8p7xTv9O7T7pnuVe4X7ujtx+287dntB+4+7nzuwe7w7vXu2O687rjuwO7X7ufu0+687rfu1+4M7y/vT+9s73fvce9h723vm+/H7/PvK/Bn8KLw3vAP8S/xVvGV8cPxx/Gx8aDxo/Gm8avxwPHg8f7xEvIs8ljykvLP8gbzLfNW83vzjfOr89nzFPRJ9G70jvSm9MD00PTo9Bn1SPVs9Yn1nPWu9bT1qfWX9YH1dPVo9VP1P/Ur9R31DvXw9Mz0qvSM9Iv0r/QB9Wf1w/X+9Rf2PfZt9oj2hPZf9jb2FPYA9vr18/UG9kn2kfbG9v72O/eA98b3CvhE+GT4cviD+LH47fgX+UH5cfmr+e75Ofqk+hb7ePvk+1X8yPxD/bH9Cf5M/n/+uv73/jP/dv+t//T/XgDYAEsBnwHvAUMCkwLkAjsDqAMaBJQENwXpBY4GJgexBzoItggNCU0JgAmoCdkJHQpfCpgKzwoFC0ELhQvOCwMMNQxyDKYM1AwCDTwNeA2oDeQNQw7ADjQPgw+/D/0PShCsEBcRfBHWESMSZBKUEqcSrBLDEgITSxOHE68TxRPcE+oT8xPnE8ITlROAE5ETuRPvExsUQxRpFIcUlxSVFIEUXRRIFD4UNRQ4FCgUCBTmE7YTexNPE0ITIhPtErwSlxKEEnMSWRJHEj4SOhIuEvsRrxFrETcRDRHUEH8QKRDqD8UPsQ+OD1UPLQ8jDx0P+g6uDjoOvg1aDfkMmgxGDOsLowtrCzYL/AqqCjgKrAkeCaYIRAjSB1AH0QZeBvIFkgVGBf4ExQSqBKEEnwSPBGQEJgTaA4QDLQPIAlgC1QFkASYB8wDFAJsAawBEACAA+f/b/9T/2//P/7n/pf+R/3D/R/8w/yz/Hv/7/tT+wv7B/sH+vP65/sv+4/71/gT/AP/4/vX+//4Z/zP/Mv8J/8r+nP5z/j/+GP7s/az9dP1c/Vr9VP1R/U/9Q/05/SD97/y1/H/8Sfz9+4v7+vpt+vf5kPki+az4R/jh92v3/fao9lr2DPbT9aD1ZfUp9ez0qvRv9D/0CPS382LzE/PN8o/yT/IW8gHyEPIY8hPyEPII8u/xy/Gn8Y/xcfFO8UrxWvFt8YPxmvGv8cfx4fHk8dzx3vHt8fzxCvIe8jjyUvJZ8kbyLvId8hjyF/Ij8jryMPIU8hbyP/J18qnyw/LH8ujyLPN086jz2vMS9E/0i/S19MH0qPSZ9LL04vQK9Sr1XfWb9eb1MPZ09tf2Vvfe90/4mvjL+Pf4JvlF+T75O/l1+dn5QPqO+sb6/fom+0P7bvuq+/b7SPyd/Pb8S/2M/bT91/3j/dj95v0W/nX++P6I/w4AeADCAPEACwEJAf8ACAFCAZUB1wEUAj4CTgJOAkECTAJtApECxQIGA1wDuQP0AxEENARxBKwE4AQWBVkFrgXzBTMGjAbpBjQHXAd0B5IHyQcXCGAImAjYCCgJegndCUsKrQrmCvgK+gr+ChkLUQueC/YLXAytDN4M9QzwDNAMnAxmDDQM/gvUC7MLhwtiC1sLZwtxC3ALXgtLCzELAwvdCsgKugq8CssK2wr6CikLVwttC2sLcQt3C4cLowuyC64LkQt+C44Lqgu5C6oLkQt6C0gLCQvMCokKSgoOCtEJngmLCZcJqgm5Cb8JzAnVCcoJwAnJCeIJDQo6ClAKUAoyCvsJygmvCZgJgwlyCVsJTglhCXsJfwltCTAJxghZCAUIwQeeB5MHhwduB0wHJQfsBq4GfQZTBjMGJgYWBukFsQVyBR4F1wSeBFQE6wNlA/MClwJLAh4C7AGzAXMBIwHtANsAwgCgAHoATwA/AEcAPQAUAN7/pP9k/yT/5P6l/nP+Pf7z/cH9tv3J/eD91f2v/Yj9gf13/VH9Jv3e/Ij8Nfz1+9H7q/uN+3f7aPtj+037KfsG+9n6uPqr+pj6dvpQ+jr6L/oj+g36A/oG+vr53Pme+Vb5Ivnz+LT4YvgH+Ln3dvcw9/v23va99pL2a/ZK9hf21fWn9Yb1cfVs9Wj1bfV99av13vUD9hH2/PXb9bL1d/VJ9TD1E/UK9Rz1PPVd9XX1ivWk9cr11vWw9ZH1cfU99RD19/Tt9Pf0GPVB9YD1u/XV9dP1uvWi9ZX1fvVS9SH1+PTY9Ln0jvRx9GH0SPQ39EL0TvQ79Cn0HPQB9ODzxfOr853zovOq87Tzu/O486TzkPOP86vzyvPU89zz4PPk8+Dz1vPC86Lzk/Oj88Pz3fPj89rz0PPK89bz//Ml9DP0P/Rg9Kb0DvV+9dr1JPZ29sT2CfdV97T3J/iP+Of4WPnQ+SX6bvrA+hb7cfvT+zL8mPwE/VH9hv2s/dL9E/5Z/oL+lf63/vr+Rf+P/7//4/8SAFYAuAAWAWUBogHBAcUBxQHXAfsBJAJJAloCYAJkAmACWAJVAlACXwKFAq0C1ALpAuoC7ALpAtsCuAJ4AjwCHwIhAkACbgKXArcC2gIMAzADQQNNA1ADUwNJAycD/QLTAs8C8QISAy4DRwNeA4wD3AMzBGAEewSlBOkEOQV1Ba4F8gVHBpsG6wY2B18HXQdVB14HZQd2B5YHrge8B7kHsAeqB60HxAfZB9YH1gftBwwIJQg9CFgIgAjBCP4IJglQCY4J4Qk+Cn8KoQqsCp8KhgpiCiQK0wmFCVkJTwlMCVwJegmLCZsJrgm5CbgJswmwCZwJgQl1CX8JmwmsCbsJvgnACdoJ8QkHCjUKdQq0Cu8KHwtFC1gLSwsoCwEL4grJCqkKigpnCjcKDwoBCgUK/QnnCdkJ6QkKCikKQwpIClIKYQpbCkkKSQp4CqgKtwqfCmUKNwotCh0K/AnoCdwJ2QnPCa8JjwlxCV0JTQk+CSgJDAnsCMEInwiYCJoIjgh3CHoIlwizCLkIpAh3CC4I8AfLB6oHjAdvB0UHBwfABoAGRAbzBZQFKQWvBC8EtQNWA/8CsQJ7Ak8CKAIJAvsBCQITAg4C/gHoAdwB2wHxARoCQwKAAsoCBgM5A24DrAPfA+kD5gP1AwME/APfA8IDqAORA44DkAOWA6kDoAN7A14DUgNLAyUD8ALWAtQCzAKnAnYCUQI4Ah8C9QHGAZ4BbQEtAfYA3QDZAOAA3ADPALcAmABuADgAGAATABYAGQAOAPb/0v+l/33/Yv9S/zn/Dv/2/vL+1/6i/nf+Tv4e/uT9kf0a/ZX8Nvz5+8r7n/uD+3b7dvuA+3b7V/sr+/b6tvph+gr6y/md+XX5XPlM+Tz5Lfkq+TD5J/kU+Qb5+vju+Nv4svh++FP4LvgU+P337Pf39yD4VPiD+Ln4/Pg2+UL5L/kV+fT4zviu+Kb4qPie+HD4Kvjw98r3r/eM93b3d/d493n3hPeb96P3nveb95r3mfeV9573n/d19zX3+/bM9rT2r/ao9pf2e/Zz9nn2gPZ/9nT2bPZj9ln2O/YG9tn1wPWt9Z31jPWF9Yf1kvWk9Z/1kPWE9Xr1ZPU49QD15vTf9Mr0xfTU9OD05PTw9PX07/T59Cr1bvWj9dH1+vUi9lD2dPaA9n/2fvZ59nH2cfaN9r726vYM9y33Vfd994r3jfeU96n3zPfy9xX4LfhB+Fr4dfiT+Kn4qvif+Jr4oPi3+O34KvlQ+Wr5cflt+YL5pPmy+bP5sfnC+eT5AfoY+hv6JfpP+oz6x/rw+hD7LftS+3P7gvuW+8j7//sr/G/8wPwN/Uz9j/3r/UD+aP51/nr+f/6O/rL+4f4G/xf/Hf85/2j/l//S/wkALwBjAKwAAQFZAa4BEAKLAgcDggPoAzkElwTzBDsFcQWNBZYFmwWyBeQFCwYgBjEGRwZjBnoGgQZ5BmkGWQZLBkgGWwaCBr8GBAdGB3UHnQfHB90H6AfuB/AHAAgTCDUIVQhjCHQIaAg+CBwI/gfXB6IHZAczBxIH9AbUBrgGrAabBnsGWwY0BhYG8wWvBWwFRgU5BT8FTwVbBVcFSQU6BSoFEAXnBLEEfgRKBAwE0wOrA5oDjANYAxkD8wL4AhoDNwNLA1YDbQOSA6MDpwOhA50DpQO0A+YDQwSoBAAFOAVLBV8FcAVwBYQFwgUWBmIGsgb3Bh8HKwcvB0QHZAd8B4YHhQeOB7cH8Qc3CIUI1ggNCS4JVQmCCbYJ/QlbCqwK5gokC2cLuwsiDI4M5wwiDUANRg0+DUENSw1bDXgNoQ3JDd4N5g3gDc4NvQ2iDXsNZA1iDVoNSg1DDT4NNw0cDeMMqwyADFQMLgwTDPcL1gurC38LPQvlCo0KLgrQCXgJGAmwCFUIDQjQB5YHXwc1BxEH+gbwBtwGsQZzBjIG6wWiBWEFGAXNBJIEcARDBPwDuANuAyAD0gJwAgcCtAFtASoB5wCvAIkAaQBVADoABwDL/47/T/8a/+b+q/59/kz+B/6n/Tr92Px//Cj83PuL+yv71PqN+kb6+Pmh+Vf5OPkv+R359/jM+Jn4WfgR+LT3RPfM9lT28vXG9bn1pPWM9W71UPU69Rf16fTM9NH09fQY9S31Q/VW9XH1lPWw9cr12fXn9fT18vXa9aj1fPVu9XX1f/WJ9Zr1u/Xl9QL2DvYO9g72Bvb/9fT13vXA9Zf1bvVE9Rb19PTj9Nz04PTz9Bj1NfU/9Uj1UvVi9Xb1jfWx9df16/Xw9eb10fWx9XX1JPXQ9Ij0S/QI9Mjzh/NJ8xzz+/Lo8uHy2/LR8sHynPJu8kvyKvL+8cLxffEq8erwwvCb8HHwOvAI8OTvxO+v76Xvo++b75rvuu/k7xjwS/B48LbwBPFS8Z3x4vEi8mryrfLf8gLzIvNQ84LzvvMH9Fj0mvTg9Er1z/VZ9sr2Ivd197f36/ck+Fr4ofgO+Yz5E/qT+gn7gvvl+zf8cfyl/Pv8Vf2w/Qv+Xv6W/rf+7P4s/2v/sv8FAHUAAAGJAQECWwKUAsQC9gI6A4UDxgMTBHkE4wQ4BX4FxQX0BRsGTAaGBtoGRAeWB8sHBggxCEwIbgigCNsIEwk/CVIJZQmGCZcJkQmTCaQJvQnkCRAKPwp0CqUKzgrpCu0K5ArYCs0K0QrwChALEQsHCwcLDgsBC9sKxQrECrEKiApWChkK0gmaCXMJYQlqCYEJoAm+Cc0J1wndCegJ8QnmCdQJvQm6CbsJpQmKCW0JaAlxCXAJYAlCCSMJAgngCL4IkwhsCFUIVQhXCFUIXQhuCGoISQgQCMUHhAdVB0QHTgdlB4MHngfEB+UH/AcTCB0ILwhUCHoIjAiMCIYIdQhnCFsIRQgpCBYIEQgWCBIIAwjzB/cHFggqCC4IKAgdCBUI+wfcB8YHvgfLB9MH2AfkB/sHJwhZCHUIdQhxCHsIhAiYCMcI9QgdCUoJegmkCcIJzQnSCdwJ6wn8CRAKMAo/CjEKFgr+CfEJ3Qm3CZUJfAltCU8JIAn0CLgIeghFCAIIqQdIB/IGogZNBvUFnAU4BdcEcQQIBK4DVwMAA7YCgwJGAvkBqwFgARABrwBVAAYAwv+B/zr/9f7P/r3+pP6T/of+Zv4q/uv9r/19/Vf9Sv1T/VL9TP1V/Wj9cv1g/Ub9Mf0e/Rv9GP0I/dj8jPw9/Pz7z/ul+4v7gPt7+3v7b/tU+z37JvsF+9r6o/pg+iP68/nB+Yn5Rfnv+JX4SvgN+Nz3rfd391X3Qfcw9xL34Pao9lj29PWU9Vn1OvUk9R31LfUz9R31C/UJ9SX1S/VZ9Wn1h/Wh9a31uvXZ9ev15fXR9b71wvXT9eH19vUM9iX2U/Z59n/2avZG9jr2QfZP9mb2ePaK9o/2j/ab9rr22vbd9rr2mfai9sr2Ffdw97b37fcn+H744fgz+Xf5ofnE+ff5J/pB+k76VPpe+mP6UvpU+nf6pPrC+r76r/qf+pz6pfqt+rX6zPr9+if7Svtu+4v7oPu1+8775Pv0+/v7AfwB/Pf79PsE/CH8Rfxh/HX8fvxw/FX8SfxX/HT8m/y6/Mr80/zd/Nj8z/zE/K/8pPyT/Hr8fPyM/J78uPzZ/AP9Mf1B/Tr9TP1u/Zr9z/0G/kP+hv7P/gz/PP9z/6H/xP/0/ysAZgCrAOAA+wABAQEBBAEIAQUB/gALASQBSQF4AZkBtgHRAdMBxwG+AbsBtAG/AesBLgJ7ArkC2wL0AhkDSgNoA34DmwO3A9gD9AMPBDwEdwS7BPMEGgU7BWgFqQXyBToGdwazBusGEgckBzEHOAdBB1IHbAeJB64H0gfmB/UH8wfVB74HsQemB6gHrgfGB+UH+wcJCBIIGwgfCBoI/gfaB8sHzwfWB9YHxwfIB+IHBgg0CF0IdAh6CHEIYwhTCDAIBgjgB7YHlQd6B2IHTQc8BzcHNAc/B2AHeweEB4gHgQdlBzkHAAfIBqkGqwa/BtcG6AbxBvQG8AbzBgQHHQctBzQHSQdnB5QH0QcbCGkIkwiUCI8IlAiICF8IKwj9B80HmwdrB0QHFgfpBtQGzgbSBuIG5QbEBqAGigZvBkgGHQbkBaMFdAVKBQkFywSTBHUEaQRKBDIEKgQPBNsDpQORA6YDtAOuA5cDcwNNAyUDAAPXAr0CwQLJAsACqgJ8AkACDALWAagBbwEyAf8A4QDrAPUA4gDNANYA7wD0AOgA5QDmANoAtgB5AEMAMgBFAFwAWgAsANf/ef84/wb/2v7J/rb+oP6R/o/+l/6T/n3+YP44/gD+wv2K/Wf9Sv0u/Rn9Ff0u/U/9aP2C/Z39yf0V/kT+QP4e/uL9tP2X/Wz9QP0d/RD9Cv3//Oj8w/yb/Gz8MPz4+8j7oPt3+1H7L/sR+wH77fq8+mr6FPrK+Yj5R/kJ+en43/jM+LD4ifhc+Cf49vfP96X3Xvf89o72JPbR9Zn1efVW9S31AfXY9ML0ovRs9DX0DfT88/Tz7/Ph88PznvOB83nziPOd86HzpvO388fzzfPe8wD0GfQ69G70nfTQ9BP1YfWq9fD1M/Z09rr29PYQ9yT3SPds95D3rffN9+73B/gs+GD4n/jw+ED5l/nm+SD6WPqH+rP62/r6+g37DvsZ+zv7VPtQ+0P7Kfvz+rT6ffpU+jf6OfpS+nL6m/rB+tT61vrP+sz6y/rC+rX6sfql+nv6NPrV+Xz5P/kY+f748Pj++Br5QPlr+ZX50/kX+lj6jPqq+rX6uPrF+tn65vry+vP67Pro+uT63Prg+vD6APsb+z/7ZPuU+9b7Ffxa/L/8NP2S/c396v33/Qv+Lv5h/pP+s/7a/iL/ff/R/w8APgBtAJ0AxADiAP4AHgFXAasBBwJiAq0C3gIAAyIDRwNhA2oDaQNrA3MDgQOXA5YDjAOQA5kDmgOSA58DxAP3Ay4EaAS0BAMFVQWoBfYFSgaWBtQGBQceBz4HbQeZB9oHHghZCJ0IzgjpCPoIFQk6CVAJXwl8CboJAQpLCqYK9wpDC5oL5QseDFcMiQyxDNwMCQ0yDVENbg2SDcIN/g0cDhQO9A3BDZcNgw1+DX4Nig2mDb0N0A3kDfEN9Q3sDd8N3w3fDdMNwQ2aDWANKg3yDMEMkQxTDBkM6gvIC8ELwQuoC3ALNgsVC/IKtgqICm0KTAoaCt8JvAmqCZsJfQlHCRYJ4wikCHQIWQhBCCQIEQgFCPAH0QekB1gHAQeuBksG3gViBd0EbgQNBK8DQgPGAloC9gGUAT4B8wC1AIQAVQAaAM7/eP8w//X+yf6m/oP+df55/nP+Yf5V/lX+XP5d/kH+EP7e/bz9n/1//VX9Mv01/Uv9XP1d/VT9VP1c/V79cf2f/cn94P3p/fL9Af73/ej97v3p/dD9rv2d/bX94f0P/i/+Q/5j/pT+v/7H/rb+pf6O/lr+E/7P/Z39fv1W/TH9AP2x/Gn8Pfwm/BH88fu2+2D7E/vY+p/6X/ol+vf5xfmH+Un5HvkV+SX5Jvkd+RL57vjD+KH4c/g9+AX4yPeN93P3fPeK9533xPfy9xb4MPhC+FD4VPhZ+Gz4h/iX+Jj4m/ik+Jb4avg5+Bf4APjy9+j31PfF99v3+vcH+AL46/fP96/3i/d393/3lvet97j3tve497T3lvds90j3M/c290X3Vfdc91/3b/eG96L3uPfA97/3x/fj9w34Vfit+AH5Pvlj+ZD5yfkH+jv6YvqB+qX63Poa+1L7d/uA+5P7q/vD++v7GPw4/E78efyt/M786PwP/Tf9Uv1r/YX9lv2d/ar9wf3U/eX9A/4a/g7+AP4I/iT+Sf5s/on+p/7n/j//kP/N/+//CQAWABYACwDf/5//Xv8X/9X+nv5q/j/+F/76/eH9y/3Q/er9F/5a/qL+6P4Z/zf/Tf9a/1z/W/9x/6z/9v81AF0AdACLAKQAnwB7AEIACgDr/97/6P8AABwANwBOAHAAkwCoAJ8AfgBgAFAATgBOAEQAIADh/5H/P//v/qr+dP45/gv+/v0H/hD+Ef4a/jf+aP6Y/rf+2f4L/0X/dv+Q/5b/mP+u/9T//v8jAFMAoQD4AEoBhgGiAbsB3gH+ARsCRQJ5ArcCAwNJA4MDvAP6AzMEUgRtBIIEfgR3BHkElQTCBPQEHAU7BV8FiQWwBdIFAQZNBrwGGwdYB4oHtgfjBw4ISwieCOQIIwlbCZEJ2AkvCoYKxwr4CioLSQtCCxoL7QrZCucKDQs9C2cLlgvSCwgMLAw4DC0MCQzVC7ILnwuNC38LeAuQC7gL3AsRDE8MgwyZDIgMXgwrDPsL4AviC+sL9wsFDA4MFwwGDNMLlwtdCy0L/grRCrYKpwqoCsEK3QryCgML/wrzCucK6Ar0CvAK1Qq2Cp4KhwpdCh0K1QmPCUQJ8QiSCCAIqAdAB/MGrQZjBhwG6QW1BXIFHgWzBD0E0ANoA+4CdAIFArcBdgEnAc4AYwD3/5j/QP/8/sv+rv6j/pX+hf57/m3+V/4w/gH+zf2K/Tr92fxr/Aj8tftu+0P7LfsW+/n62vq7+qP6jfpy+mn6dvqL+pn6mfqS+oz6kvqb+p76pPqi+pH6ffpz+nr6jPqg+rT6y/rw+iX7RPs5+yj7HvsY+wX70/qL+kz6IfoM+hH6J/pC+lz6X/pB+hX66fnW+c/5sfmP+Wv5OfkT+Qb5FPkX+fv42/jL+NH45/j/+Ab5Afnw+OD42fjF+LL4nfh3+ED4+Peg9z331vZ59iH20/Wg9Wv1K/Xu9Lf0hfRR9Cn0IfQp9DT0QfQ79Cj0HvQp9Dz0OvQo9CX0K/Q69En0VPRo9Hr0kPSk9Lr06PQg9WH1m/XK9fz1L/Zd9m72cPaL9r/28/Yj90v3c/ek98r34vf89yH4UviL+NH4G/ld+Zz53PkV+k36g/q1+uT6Gftb+5/72vsX/Fb8jvy9/PP8OP1v/YP9fP16/Z795f0v/m7+qv7m/hf/Pf9r/6D/0f/x//L/7v/3//L/2f+8/53/f/+D/77/DQBXAJ0A3AAGARoBFgH2AMEAkwB9AGgAXwB4AKYA3wATATEBQAE7ASIBEAELAR8BQgFwAbkBBAJHAn8CnwKeAokCZQI8AgkC2AHBAcgB1AG4AY0BeAFxAXABbwFoAW0BjgG+AeMB4wHXAeYBEgJCAlsCWQJFAjICKwIzAj4CQwI8AikCCgLwAegB8AEKAjECUAJmAm4CagJ2ApYCuALHAsoC0QLdAvACBgMSAyMDRgN7A74D/AM2BGAEcAR2BIgErATTBAcFOAVdBYsFwgUBBjUGYQaMBrIG2AYIB0gHiQevB70HzgfhB+0H9Af+Bw8IJAg+CFsIcQiKCK0IwQjICM0IvwiuCLIIvwjHCMsI0AjMCLkIrQiqCJAIYwhACCMIFggSCBQIGggiCCwINgg+CDUIJggTCPcH4AfgB/gHKQhfCHcIZgg6CA0I0AeCBygHyQZ3BkUGJwYFBuEFqQVtBTsFIQUaBQcF7QTQBKkEdwQ8BP8DwgOSA20DOwP0AqgCYgIWAsYBdQEtAfcA1QDEALoAuAC/ANkACQFJAZQBwQHFAbkBsgGwAbABrwGbAXkBUwEmAfUAwQCOAG4AXwBaAF8AbACAAKAAzwD3AAoBEwEkAUIBUwFVAVYBWQFfAVoBQwEbAfYA5gDoAPAA7QDYAL8AtgDKAOgAEAFHAXMBdgFgAVEBRQE3ASwBLwEzASkBIgEXAQoBAwH+AAEB+ADLAHsAJwDo/7z/l/9z/0v/H/8K/wX/8v7T/qz+fP5M/ij+Fv7//ef91v3B/aj9k/17/VP9Kv0D/cj8gfw+/P37wvuL+1T7LPsS+/P6vfpy+in65Pmw+Yr5bPla+VD5SvlA+TP5OPk8+Sb5AvnY+K74jvho+EH4IfgH+Of30vfI97f3q/e499T37/cX+Cz4Gfjz97/3jvd+94/3nPem97v3z/fN97X3oPeO9433m/es98D30Pfg9/f3HfhT+I/4zvj9+A35/vjl+Nf43fjv+Pj47fjn+AT5J/lB+U75S/lP+WH5gfmo+c35+fkp+mP6m/q8+sX6x/rb+vz6K/ta+4P7rvvM++T78vsC/DL8bfyW/Kb8r/zC/Nz89/wU/SP9J/0y/SX9D/37/Nr8xvy//MH8yfzf/Ar9Lf06/T/9Rf1R/Wr9g/2S/aH9s/3H/dX9y/2v/Yz9av1N/Tn9L/0d/RX9Ff0R/Q39B/0H/Qj9Bf0B/QD98/zQ/KH8ePxr/HH8dPxx/HT8fPyD/JP8lvx0/ET8Lvww/Ej8afx6/H78fvx//IL8ePxk/E38Svxe/HX8hvyZ/Lz84Pz+/DH9dv28/ff9F/4l/iv+L/5C/mn+mP62/sf+2/4H/z7/cv+5/wMAPwByAKEA0QD+ABkBNAFcAXcBigGrAdcB+QENAiUCQAJNAlICUgJTAmcCjgLJAhIDXAOeA9cDFARWBKAE4wQOBTQFVgV7BakFxgXXBfUFIAZJBlQGTwZWBnIGpwbcBgkHNQdbB4EHrAfEB74Huwe+B8IHuQexB8EH5AcUCD0IUAhACBgI7gfNB8YH1AfsBxIIUgiXCMcI8QgcCTgJSQlgCX4JlgmfCaUJygnuCe8J3gnDCaUJgwlmCUwJMAkhCR0JKgkqCRIJEAkSCQ4JEQkRCQ8JDwkSCSgJVAlwCWgJSgkxCSQJGgkLCfYI8AjuCOkI7gj0CPsI+AjtCO8I7gjtCPII5QjTCL8IpwiYCIcIcAhiCGEIXwhLCC0IGggLCPAHxQeWB3EHSwceB+wGrwZrBi8G+QXRBbcFrAWyBbQFsAWeBYIFcQVeBT0F/QSnBFUE/gOZAzkD6gKjAmcCNQIAAswBkQFUAREBxQB8ADUA7v+m/0z/6f6J/iz+1P2V/Wr9Qv0m/Qz99fzl/Mn8rvyO/GH8N/wT/Pj77fvx+wD8Cfz9++n7zvu0+5X7bftK+x377vrF+o76UPop+iL6Jfoq+jD6JfoE+tf5tfmi+Z/5p/mx+cP5y/nC+an5g/li+UT5Jfn7+Mz4nfiK+J74t/jV+O/4/vgG+RH5KflC+U75WPlm+Xr5lfmt+cb54fny+fT56vnU+bD5l/mT+Zb5pvmy+b750vnW+df55vn4+Qz6Hvo0+kb6S/pT+mr6kvq1+sj62Prv+gD7C/sQ+wL75PrC+pr6c/pj+mn6d/qS+r765/rx+vH69Pr7+gz7Dfv0+tH6rfqa+qL6ufrL+tT63/rr+u367Pr1+vr69Prs+ub62vrB+q76tvrE+tD62vrw+iH7Uvto+237avtl+237g/uU+5j7mvu1+9r7+/sX/DX8SfxZ/HD8hvyZ/K38x/zh/Pz8Lf11/bX94P3+/Q/+F/4a/iz+Sv5k/oH+pv7J/uz+Ev8r/z//T/9k/4P/rf/W//D/BwAhACgAKQA0AEoAaACFAJ4AqwC1AMkAzwC2AJAAdgBuAHAAcQB5AIkAnQCnAKkApgCiAKAAmwCVAIwAfwCBAI4AoACyALgArgCmAKsAsAC6ANQA+gAlAUkBbAGXAb8B3gHiAckBnAGHAZMBngGeAZwBpQG0AckB8wE2An8CvQL0Ah0DMQM+A0oDWwN2A5IDrwPNA98D1QOrA3oDUgM4AywDEgPtAtoC2wL3AhEDFQMGA+0C4gLtAvcC9gL2AgMDIQNKA2sDggOfA8kD6wPxA/ED+AMXBDkEQAQ3BCsEOgRZBHcEjQSQBJEEmgSzBMsE0QTHBKgEegRSBC8EBATcA7MDhgNYAzUDGQPwAr0CkQJ2AmwCbAJtAmcCXQJLAjUCFwLzAc8BuAGnAaMBtgHQAeoB9AHlAeEB9gEkAlgCeAKEApACnwK6At0C9AL3AuUCzwLDArgCrAKaAn8CWgI0AiICEQL6Ae8B6AHdAdMByQGqAXQBNAHtALQAgQBJAA4Azf+Q/2H/OP8E/8v+lP5p/kn+Jf4B/uL9wf2i/Yb9Yv0s/e38svyH/Gn8UPw1/B/8GPwZ/BL8/Pvu+/z7EPwa/Az8AvwG/Av8Fvwr/EX8Rfwo/Av89Pvp++z7+/sZ/EP8c/yY/Lf81fzs/AP9Gf0g/Rv9Df3//Pz8+/z4/PH85Pze/Nz87Pz8/Ab9Gf0y/Uv9U/1k/YP9mv2n/Z/9if17/X79gv2I/ZP9mP2h/bb9zf3p/Qr+Nv5e/nP+jP6y/tn+//4e/0D/Zf+C/47/jf+M/4z/jv+J/3n/X/86/xj/Cv8G/w3/D/8K/xn/J/8Y//r++f4U/zP/R/9F/0z/Z/+S/7j/wf+j/4L/av9H/yz/Hf8W/xP/Dv8H/wn/Dv8U/x3/Ef/w/s3+xf7f/hH/Rf9n/3f/ev9o/1D/Ov8w/yj/Ev8B//H+7P7w/ur+5P7j/u/+//4D/wz/F/8W/xL/B//3/uj+2f7O/sv+0/7m/u7+4v7B/or+S/4G/sn9qf2b/Yr9dv1s/Wf9aP1Y/UP9Lf0T/fv87Pzz/Pv8B/0Z/SL9LP0//Vv9ef2C/XX9Zf1U/T79Jf0g/Sz9NP0y/TH9PP1E/UH9Rv1V/XD9h/2F/YX9l/3A/QH+Rv6M/tL+Df83/03/WP9g/2b/cP+C/5f/sv/S/wIAPABvAIkAjACMAJ8AvQDZAOcA6ADmAOkA6ADjAOEA5wD2APAA1gDGAL8ArgCcAKYAxgDjAPMA/QAIARoBMwE+AT4BPgFPAW4BiAGbAaYBtQHLAecBAQIIAggCFQI7AmsCjgKhAqkCuwLaAv4CGwMpAz0DXAN9A5gDqwO8A8wD6QMLBC0ERwRcBHAEggSSBKQEsgS0BLkE1QQCBSUFKwUUBfwE+AQIBSIFNAU7BTkFMwUzBT4FUQVkBX4FmwWkBZ0FlwWTBY8FfQVuBV8FQgUeBQUF/gT6BOwE0gSpBHoEWAQ/BDIENQQ5BEwEYQRxBIMEmATCBPYEGwUxBUEFYAWBBZoFvAXaBekF6QXuBQQGFQYfBi0GQAZXBmAGVgZMBj8GMAYrBisGJQYZBhcGIAYdBgsG9gXRBZ4FbgVLBTwFMgUoBRQF/wT9BAcFEwUZBRQFCQXvBL8EgwRDBAsE6QPOA7gDqwOlA6wDrgOgA4YDcwN1A38DkgO0A9kD/wMeBCcEFQQCBPYD/AMCBOUDuwOlA7YD3gMFBBwEEQT3A+sD6gPYA7IDjANmA0UDHAPdApACMgLWAZEBbwFiAVEBOwEgAQwB7gC9AIYASQAOANz/vv+x/6//rP+b/4//kv+A/1D/Gv/p/r/+nv5w/jH+6P2i/XH9S/0T/cv8hvxa/EX8Nvwp/Bn8Afzn+9776fvv+977xPus+5D7dfth+0L7HPv6+uv69voH+w37Afvn+sD6lfpo+jj6B/rP+Zb5avlG+R358fjH+Jr4afg6+B74B/j19wD4C/gL+P736PfW99P35/cI+CD4Kfgs+Cn4JPgl+Cb4JPgh+CP4K/go+Cr4PvhZ+HP4g/iR+Kb4uPjD+NL47vgR+Tn5VPlj+Wn5cPmI+aL5vvnr+Sz6ePq++vD6Fvs++2z7jfuQ+4f7ivud+7T7xPvF+7f7tfvA+9f7/PsR/Bj8LPxW/I/8zPwJ/UD9e/22/eD9/P0C/uz91P3O/cP9uv26/bb9sf2n/Z/9kf2E/Yb9kP2i/bz9zv3a/d/92v3t/Rv+SP5i/mP+Uf47/hv+7P25/ZP9cP1N/Tz9Jf0J/fz8+/z6/O381PzB/LH8nvyf/KD8k/yI/Hb8X/xV/Gr8kfyy/MT8yPzI/Mr81Pz5/Cv9YP2g/eD9Ef46/mP+kv7F/vX+Jv9a/53/6f83AIIAwwD8ACgBRAFgAYQBtAHrASACTQJ8ArsC9gIiAzsDQgNJA1QDaQN1A2wDYwNjA3ADeQN4A30DggOEA48DogO5A9AD8QMfBE4EdwSNBKIExATiBPwEBwUDBfEE1ATLBMwEzATPBNoE9QQYBTkFTwVaBWoFdAV0BXMFYAU0BQkF+ATuBNUEuASZBHQETgQqBAYE3wO6A58DjAN8A10DQAMvAxoD/gLfArUCfAJBAhIC6gHCAaABfQFHAQcBxAB7ADgA/P+8/3n/Rv8k/wv/C/8h/zf/U/9r/3n/if+m/8b/1//Q/7v/p/+j/7T/yP/I/7b/rf+0/8X/2P/d/9f/x//C/8T/tf+k/5H/gf9+/33/e/+A/5D/qP/A/93//f8PAA0ACAANAB8ANgBEAEcAQAAuABkAAgDq/9r/1f/a/+n/9f8KADoAgADTABYBQAFXAW0BjQGqAbwBwAGyAaMBnwGfAaIBpQGbAZYBngGZAYcBZwFLATkBMQEqARIBDAEfAUEBeAGuAdYB9QEXAjoCSQJNAlICUgJPAlECXAJwAoECkQKXApUCmQKZApMCjAJ6AmECRgIrAgoC5wHGAaUBgQFZAS4BBgHkAL8AlgB6AHAAZQBfAGUAcgCEAIsAkQCSAH8ASgACAMn/pv+C/1//Vf9T/0z/Rf87/zP/MP8u/yn/Gf8M/wX/+/7q/s7+q/6N/nj+Xv41/gH+zv2i/Yv9jv2G/W39Tv04/Sz9FP3t/Mn8tPy2/LX8rvyi/I78c/xP/C78Dvz0++X7zfun+4X7ZPtB+yf7EPsQ+zf7ZfuK+7j79Psq/E78cvym/NT89PwO/S/9U/1y/Yb9if2T/an9zP35/S7+Yv6V/sL+1v7c/uz+//4S/yL/Kv8l/xH/+P7k/tr+2f7X/tD+w/67/rv+rP6O/nf+df6L/rX+2v7r/vH+//4e/0L/Xv9v/4D/nv/C/97/8//7//7/AgAGAA8ADQABAPf/3f+v/4j/cP9V/y3/A//X/pX+Rf74/cD9pv2R/Xr9YP1H/TP9GP35/NT8rvyO/HL8V/w1/A787vvd+8z7vPul+4T7bvte+2H7e/ub+8P7B/xW/Jz83PwU/Tn9RP1M/Vf9cP2a/b/93v30/RH+N/5V/mn+ef56/n/+mP61/tT+7P4D/yT/R/9y/6v/4/8BACAAUwCNANIACQE5AW4BqQHtASgCWgJ/ApEClwKaAqgCzwINA00DggOpA9ID8wMPBDAEWgSPBLgEzgTPBNAE4wQGBTUFYgWFBaMFxgXpBfsF9gXmBekFAQYhBkwGcgaRBpwGkQZ7BlQGLAYOBvAFyQWtBaMFngWfBaMFowWkBZ8FlgWCBVsFMwUVBe4EsQRlBCQE/wPpA9gDzAO/A6sDjQN2A20DaQNgA18DcwOZA8gD8QMTBC4ESQRVBEwESgRHBD4ELwQeBCIEMAQ9BEAENQQ2BFsEiwSuBLsErwSjBJsEhARhBDAE9QO/A5QDdwNmA1cDPQMXA+4CxwKmAoMCYgI+AhMC6AHKAa8BiQFkATkBCQHdAKsAegBVAD8AOwA1ACEACQDy/9n/pP9Z/xT/zf6E/jr+5/2Y/Vz9L/0I/dz8oPxR/AD8xvul+4P7XPs++zr7RvtZ+2v7bPta+zv7Kvsy+0H7Pfso+xb7E/sa+xr7DfsH+w/7Mvtd+3z7kfub+6j7uPvH+8/70/vb++n7+/sU/DP8U/xl/G38dfx9/Hb8YPxF/C/8K/wv/Dv8Q/xC/FT8cvyg/N/8Gf1I/V39Y/1r/W79gf2P/Yn9f/1p/VL9R/1I/VH9TP00/R39FP0j/TP9O/1G/VL9V/1U/U39Sv1N/VT9Z/2E/ZL9j/2H/Xr9c/1z/XT9g/2o/cf9zf25/Yr9V/0v/Qz94/y6/Jr8hPx2/Gz8V/w6/B78Avzw++b70/u6+6T7jvt9+3r7g/uI+4n7hvuM+6b7vPvE+8D7s/uv+7f7yvvp+wX8Gvww/Er8gPzG/AP9Mv1c/Yr9s/3J/d79/P0e/kn+gv6w/sv+4f7//iP/TP95/6n/3/8OAD8AewCxANkA7wD/ACEBVAGMAcgBAwI5AmsCngLMAu8CFwNXA6YDAgRYBJkE2QQeBV4FkQW3BdkF6QXwBfQF+gUQBisGUAZxBoYGqQbVBvEG/QYNBzEHYAeFB6sH3QcKCDIISghSCDkICQjXB5wHZgdBBzIHOwdMB1EHPQceBwkH+AbfBswGwga1BqYGoQajBqcGugbPBuEG7wb0BvQG7gbjBtsG0AbDBrEGngaKBm0GWAZMBlIGXgZgBl8GVgZMBkYGNgYZBvwF3QXJBcMFwAW3BaAFhAVzBWMFRwUeBf0E7wTvBO4E4ATHBKMEegRdBEoEKwQFBOQD0APQA9gD5gPwA/AD6QPoA+sD6APYA7oDlQNsA0YDHAP2AtUCtQKXAoACdgJgAjUCAQLeAc4BwgHBAckBzwHXAdQBzgHNAb8BrwGgAYUBZAE9ARIB8QDhAOYA8gAAARYBJgEtATMBMQE1ATsBNQEmARgBGAEfARUB9wDdANAAvACcAHsAXgBMAEkATQBOAEQAOAA0ADgARABPAFUAYABfAFcAUwA6ABUA8v/a/8f/rv+R/3j/Yv9W/1P/S/8+/yv/IP8f/x//E/8F//3+9v7g/r3+kP5J/vX9qf1v/TD94vyj/HD8Nvz2+8b7r/uZ+237PfsS++H6n/pQ+vn5l/lE+Qj50/in+H34WvhB+C74IvgU+Aj4CfgQ+Bz4Lvg++EX4P/gk+AT47/fw9wb4DfgJ+Pr37ff19wf4GPgp+Eb4dfih+ML42vjq+Pf4BPkE+fn4+PgK+TD5YfmX+dX5EPpM+on6x/r1+gn7EfsW+yn7Rftk+4n7rfvH+9D7xPut+5j7hft++4/7rfu++8D7w/u3+6j7nvuN+377gPuS+6P7qvui+5f7iPt1+2r7XftE+xj72/qk+oP6a/pH+hf67/nd+dr50Pm1+Zj5hvlu+Ub5JvkR+e/4v/iL+Fv4KPjp95/3Vvcc9+j2s/aI9mH2P/Yn9hv2Cvbo9bv1j/Vq9Uv1MfUc9Q71CfUL9Q71GfUl9S31PfVY9W/1ivW09d71B/Yi9jD2QfZW9nX2o/bR9gP3NPdY93X3iPeW96f3vvfW9+L39vcY+Dz4Y/iK+LD42/gU+VH5ifm8+d759vkJ+ib6VvqG+rT64voT+037j/vN+xH8X/yr/Pf8QP2H/c/9Ff5D/lv+gP6//hD/Zf+2/wMAUwCuAA0BYAGpAecBHQJJAm4CqgLzAjgDZgOAA6ADzQP+AywEVgR1BJkExwT2BCQFPwVVBW8FgAWLBZoFtgXgBQkGJgZBBloGewaYBqMGpAaoBrIGrga0BtEG8gYQBycHQQdvB6IH0Qf9BywIXgiMCMII/QgzCWsJnAnDCesJIwpqCqIKwgrbCusK7gr2CgYLDQsIC/4K9gr+Ch0LOAtBC1MLagt6C4ILegtrC2ULXQtECxcL5wrHCq4KlwqLCnEKVwpNCkUKMwoaCggK7QnMCawJjgl4CWUJWwldCWYJcwl9CYsJlgmeCaYJrwm0CasJlQl7CW8Jcwl4CYEJhQmCCYAJgAmBCYIJhAmBCXgJfQmSCagJuAnICdUJ0wnOCcwJwwm1CakJnAmYCaIJqwmrCaUJogmYCXwJUwkgCfYI2AjBCLcIswilCJYIjAiICH4IcQhnCFQIMAj7B8wHtQejB4EHVgcnB/YGyQaeBnwGZAZVBlEGTwZBBikGGQYFBu8F3wXABZ0FiwWNBZEFhwVlBS4F5gSLBDEE3wOWA1IDEAPNAocCRwIIAr4BbgEXAcAAcgApAOj/rf9v/zP/8v6r/mX+HP7N/Yr9Vv0X/dL8ifw3/O/7sftp+x/71PqP+lb6Hvrj+aT5bvlO+TD5CPnw+O34+vga+S75Mvkt+R35C/nz+Nn4w/is+J34m/iU+In4f/hs+FD4L/gR+Pn34/fU9873xve196j3mveR94X3bvdt93P3cfdn91X3SPc+9y33DPfx9uP22vbc9u72Dfcp90D3T/dS9133bPdz93b3fPeY98j3/fcq+EX4Xvh6+Ir4kvib+Kf4sfi6+Mv44Pjj+M/4uviv+KL4mfiV+IX4d/hs+Gf4bfh2+Hb4bPhR+C74Cvjd97n3oPeE9233Y/dW90j3SPdS9173bPd99433pPfO9/33Hfgt+Cz4L/hF+GX4hfin+Mv46vgE+Rn5KPkx+Uz5dfmc+cb58vka+kL6a/qM+q760/r9+i37Yvub+9L7CvxI/JD82/wa/Ur9cP2W/br91f3t/QP+Ff4o/kD+YP6T/sr+/f43/3j/t//r/xUANABWAHwAlwDAAAABRQGFAb8B+wEyAlgCbgJ6ApICsQLKAuMCDANVA7AD/gM0BGEEiASjBLQEuwS4BLsE1wQBBTIFZQWDBaEFxgXpBQkGJQZIBmsGiAajBrYGxQbVBuMG2wa5BpUGdwZfBkYGLwYpBikGJQYaBgkGAQYKBigGVgaPBsMG9QYiB0oHbwd/B4cHjQd6B18HUQdWB18HYgddB0wHMwcVB/YG3QbUBtgG3QbqBv4GFQcyB0YHSwdBBy4HHwcbByIHMAdAB0wHSgc7BygHEwcFB/oG7wbvBv4GHAc2Bz0HLwcHB90GvwapBpwGjwZ+BmcGUQZFBjoGJAb+BdEFrQWZBYoFfwVtBVkFTAU0BRQF7wTIBKwEoQSZBIoEdARTBDMEFQT6A+MD2APaA9IDtQOJA1EDGwPiAqECZAIjAtMBgQE1AfQAtQCAAFkAOAAgAA8ABgAKAAwABwD2/8//o/9//2n/Wf9E/zD/I/8a/wz/8f7I/p3+e/5l/lX+Rf4+/jz+PP42/iL+Av7V/aj9cv0z/fv8x/yc/Hv8Vvw3/CD8B/zi+6z7bvs2+/36vvp1+if63fmm+YL5YflE+Sn5F/kL+e34t/h2+Df4A/ja96/3e/dE9xr3//bj9sb2q/aR9nP2QvYE9tD1qPWF9Wn1V/VX9WL1dfWJ9Zf1oPWh9aD1pfWs9bb1xPXY9fX1D/Yq9kz2cfaX9rP20Pbu9gf3Gfcs90f3ZPeC95X3o/ez98r35/f39wH4DPgU+CD4K/gv+Db4Tfhx+Jj4vfjj+P/4Dfkn+WL5pfne+Q36NPpa+pD63Po1+4373/sr/ID82/ww/Yz97f1A/on+z/4c/2X/mf+//+L/BgA1AHIAvAAJAVEBiwGtAcMB1gH2ASACQwJkAoICmAKnArkCzALWAtoC4ALzAg8DJwM7A1cDeAOaA8ID9QMyBGgEiQSTBJwEogScBIcEcQRyBIIEnQTEBPYELAVVBWEFUwVDBTIFIwUmBS0FKQUhBRkFDwX6BOQE2gTaBOAE4QTcBOIE9gQRBScFNQU4BSYFBgXkBL4EnQSLBIEEgwSHBIIEdwRsBF4ETQRGBEoESwQ9BCkEFwT/A+4D7wP8Aw0EFgQgBDQETQRYBEcELAQVBAYEAQT+A/UD9wMKBB8ELQQsBCMEIwQlBCQEMgRMBGoEewSCBJQErATCBNoE9wQNBRQFEgUEBfoE+QT4BPsE/gT1BOsE4QTJBKYEggRpBGIEXAROBDkEIAQIBPQD3APIA7QDlwN9A3QDeQN3A3IDfQOKA5QDlgOZA6wDygPoA/oD9wP0A/QD9gMDBA8EHAQyBDwEMwQuBCwELgQlBAwEAwQDBAEE+QPvA+sD6APWA6oDdQM9AwQDzwKgAnACOQL7AbwBigFgAS0B8ACtAHUASwAsABAA6P/A/5P/Yf8p/+P+ov5p/jj+HP4G/vn9BP4Y/iP+Jv4g/gX+6P3V/c79x/23/aT9if10/Vz9Of0T/fn89vzz/OP8vfyX/Ir8g/xy/FP8MPwJ/Nn7qPt7+077Gfvg+qn6evpe+lH6QPon+gr65/nM+ab5gvlv+Wj5cfl2+XT5aPlb+U75Pfky+TD5IvkI+fv4+PgA+Qz5Bvn3+O347/gG+Sz5WfmT+eH5N/qC+r368Pof+037dfuV+7H70/v/+yf8Rvxn/H78fvx7/Hb8c/x1/G38XfxG/CT8//vh+8T7m/tq+zj7CPvf+rj6l/p8+lX6IPrj+ab5ePlO+SD58vjG+Kn4k/h1+FP4MPgL+PL34vfX98/3zPfJ98L3yvfi9/n3//fu9873rPeP93D3Uvc69yf3GPcQ9wv39fbS9qn2fPZR9i/2GvYN9hT2NfZg9oT2pPbI9gT3VPeh9+33OPiB+ND4IPlj+Zn5zfkI+kL6f/rP+i37jfvp+z/8jPzW/CP9eP3C/fz9PP6E/tL+Hv9b/43/t//m/ykAfADSACUBdQHEAQ8CUgKOArwC7AIrA2EDlAPGAwAESQSVBNgEFgVQBYkFwwXyBRgGOgZaBoEGqgbGBscGwga7Bq8GqwawBrsGxwbKBr4Guwa+BsQGzQbRBtEGyQa6BqcGnAabBpIGegZhBlsGXQZeBmUGcwZ7BnsGdwZvBmMGTQYyBhMG5wW1BYAFTgUsBQoF3wS4BJsEhwRoBEQEOgRIBFoEWwRSBFkEZwR0BH0EgwSHBIYEjwSYBJsEpgS/BO4EIgVFBVcFZwV8BZYFvQXwBSAGQAZbBncGkQa5BukGHwdZB5AHvQfOB9AHyQe4B6cHpQexB8YH5AcBCBoILghCCFEIVwhbCGMIaQhwCIIIpAjQCPMIDQkxCVMJawl3CXQJcAltCWUJYAlYCUsJOgkeCfkIygiWCGoIRggqCB8ILQhHCFMITAg/CCwIEAjvB9IHuweqB5sHkQeNB4UHdAdlB1YHQQclBwkH8gbgBs8GuwarBpEGcwZjBmIGZAZYBjoGCwbWBacFfQVTBSkF/gTTBLMEmwSCBFoEIQTpA6oDYQMeA+ACoQJbAg8CwQF7AT4B/AC5AHcAMwDw/6z/X/8J/6r+Q/7j/Y79Qf36/LD8Yfwb/Ov7zvu6+6j7k/t6+1b7KPsG+/b65vrP+rf6ofqP+oD6dvpr+lr6RPop+gX6z/mh+Yj5evl4+Xj5dvlx+Wz5XvlI+TT5JPkf+S75QflN+Vf5afmC+Z75sPmu+ab5pPmh+Yf5Xfk/+Sz5J/kk+Rf5/vje+Mn4xfi9+Jv4dvhk+GL4Y/hh+Gr4eviN+Kz4zPji+O349vj/+A75M/lf+YP5mPmf+av5vfnM+eD5/fka+jL6Ofo8+kH6QPo2+ir6Kfot+i36L/o1+kH6TfpP+kv6S/pS+l36ZPpg+lX6T/pW+nr6qfrI+tH6z/rJ+sj62fr1+hr7Qvtg+4j7uPve+/z7HvxE/Gb8ePx6/HT8aPxN/C/8Efz8+/f7/Pv++/b78Pvz+/b77/vj+9v72Pve+/j7H/w9/FD8XPxn/Gj8YPxY/EX8OfxB/FL8a/yE/Jz8t/zR/O/8DP0n/UT9Zv2X/cz9/v0t/lL+fv6u/tH+4v7s/vz+F/8z/07/Zf9+/6T/2P8OAEUAfAC1AOkAEQE2AVgBcgGKAZUBmAGeAbEB0QHqAQECHgIxAkECVgJuAoMClAKjAqwCuwLIAtUC2gLVAtMC2wL0AhYDMQNBA0wDXQN7A58DvQPQA9wD6APwA+wD7QP5AwkEGAQxBFkEfwSgBMAE4wQDBRMFFwUWBREF+gTUBK0EfgRPBCMEAgT5A/kDCAQZBB4EFgT1A84DqwOGA2kDVANGA0cDVANhA2kDdQODA30DZANCAxYD8QLZAtcC6AIAAxcDKAM1Az4DPwM3Ay8DHwMYAyMDLAMvAzEDPANJA1MDWwNUA0ADJAMKA/MC4QLnAgIDJwNIA1kDZQN0A4QDhQN9A3QDbgN4A5ADsAPNA+oDAwQNBBcEHAQbBBQEBwT/A/gD6QPaA80DvQOuA5kDiQOJA48DkAOKA4EDeANrA2EDVwNMAz4DKAMGA98CuwKYAmwCNwL8AbwBeQExAewArgB1AEMAFwDx/9X/wP+u/5f/h/+D/4T/ef9g/0P/Jv8H/+P+t/6P/nH+Sf4T/ur9zv2x/ZT9e/1i/Uv9Of0u/TD9N/0w/Q/96vzV/Mr8wvy6/Lb8s/y5/Mb80fzg/Oj86vzp/OT85fzr/PT8/Pz//Aj9Ef0O/RD9I/05/U79Zf16/Y39kv2G/XX9Y/1Z/VL9Tv1Y/V/9WP1R/U79Sv1E/T39NP0j/Q39/vz8/AX9Dv0J/fb85vzd/NL8wvyt/J38mvyi/Lb80vzt/Ar9KP08/Tr9L/02/VT9ev2a/bH9y/3y/R3+Q/5j/nP+ef6B/pD+pf63/tP+Bv9G/4D/pv+4/7b/qf+a/4P/Yv9E/z3/TP9b/2v/d/94/3b/f/+R/5j/nf+q/7b/wv/A/7D/of+R/37/aP9U/0v/Sv9G/zX/JP8Y/xD/Bf/2/vb+Cv8p/0v/Yf9m/2f/Xv9L/0D/MP8Q/+3+1f7O/sv+xP6t/oX+Yv5F/ij+CP7m/dP90/3c/eD93P3X/dr96v0F/iH+MP4x/ir+G/4E/vD96f3z/fv9/v0M/h/+JP4j/iX+K/40/jv+RP5Q/lb+Wv5f/mX+Z/5f/k3+O/40/iv+H/4g/jH+Pv45/iz+Lf49/kz+XP5v/n3+fv52/n3+kP6W/pX+nP6t/sL+zf7N/sz+x/7J/tT+1/7N/sP+vv7E/tX+3/7b/s7+v/68/sj+2v7u/gT/Gf8q/zj/RP9G/z7/KP8J//j+/f4I/w7/Ff8X/xP/D/8D/+v+zv6x/o7+av5S/kr+Tv5V/mL+cf56/oD+gv5//n7+ff5v/kf+Fv7q/cz9uf2g/X79X/1F/Tz9T/1v/Y/9r/3U/fr9G/4u/jr+TP5u/pf+vf7i/gP/I/9M/3v/pv/O////NABkAIUAmwC4ANgA+gAcAUQBfQHAAQQCOwJfAnwCkQKkAsUC6gINAzcDYQOTA8gD6wMABBIEHQQmBDUERgRhBIcEvQT0BCIFSAVnBYUFlwWfBZ8FlwWBBWIFSwVOBWgFggWPBZQFkAWIBYIFfQVpBT4FEgXqBMUEsQSvBLYEuwS6BLIErgSwBKgEmAR6BFcERAQ7BDkERARiBIYEqgTABMQEuAScBIEEawRfBGEEYwRWBEAEOQRKBGcEfASDBIAEegRxBGAEUARHBEEENwQvBCUEHAQZBBYEDgQOBBIEBQTzA/IDAAQUBBcEAQTgA70DmANwA0EDFQPsAswCuQKxArgCwgLNAtICzALFAsECvgK2AroC0wL7AiEDOgNNA1kDYgNrA2wDZgNbA1sDYgNmA2kDaANgA1kDXQNoA3IDggOXA6cDrgO2A8EDxwPIA78DuQOwA5MDcANTA0ADNwM1AzkDOAMrAxgDCgMEA/8C+ALzAuoC0QK6AqkClgJ/AloCKAL3AdsB0AHEAagBegE6AfkAyQClAH4AUAAsAB0AGAANAPX/4v/e/9n/zP+5/5n/ZP8u/wf/6v7Q/rX+of6W/pP+kv6N/oT+bf5O/iv+/v3Z/b79pv2Q/X79Z/1M/Sn9Av3d/LH8gPxX/EH8QfxK/GH8gfyc/Kj8m/yG/HD8Sfwb/PP70vu7+7D7s/uy+6r7qvuv+7H7r/ug+4r7e/ts+2P7VPs6+yr7KPsn+xv7Cvv0+tf6xfq3+qf6nfqV+pb6l/qH+nT6cfp++pT6q/q7+sP6zPrb+uv6+Pr/+vn69Prz+u366frq+uj62vrD+rL6rPqn+qP6pPq1+s/62/rc+uf6/PoG+wD78frU+qn6f/pk+lb6VPpQ+k36TPpL+lX6Z/p0+nf6cvpm+lP6Pvor+iL6Hvog+jD6Q/pU+mT6cfp9+on6m/qy+tj6D/tK+3P7jvuy+9n7+fsP/Br8HPwe/CL8Jvw0/Ej8YfyI/K78x/zN/MD8r/ye/JX8lfyY/KH8sPzD/Nj85/z0/PX86fzQ/KD8c/xY/Ev8TfxX/GD8cPyP/Lj82/zn/On87/z8/A79Fv0Q/QP9+fz8/P38+vz6/Pz8DP0l/T/9UP1h/XX9iv2r/dX9+/0d/kD+av6Z/s7+B/85/2z/pP/X/wYAOwB6AL0AAgFLAYoBwgEHAlgCpQLnAiYDaAOkA9kDDQREBIMExgQOBUsFcAWLBa0F1wUJBjcGUgZcBmIGdQaVBrQG0AbxBhcHPwduB6YH1AfvB/MH6gfqBwAIKQhcCH0IgAh1CGYITAgmCPwH0getB5MHfwdzB3QHdwd3B3YHdAd0B3cHfQeAB3wHdwduB2oHZgdcB18HcQeGB48HjgeLB40HmQenB7gHxgfMB9MH5QcECCQIOQhHCE8IUwhOCD0INQg8CEwIYghyCHcIdQhqCFsISAgwCBoIDggHCPgH4AfMB7wHtQesB5oHegdVBzwHIgcLB/0G9gb2BvkGAwcKBw8HGAcVB/oGyQaVBmQGMgYHBuEFugWUBXkFaQVhBVcFOwUSBeQEuASJBFUEIgTnA6sDhANoA0sDLgMSA/MC0gKmAnACQQIcAv8B7AHeAdYB0gHLAcIBqAF4AUUBDgHRAJYAYwA0AAsA8f/W/7H/jf9m/zr/Cv/O/oX+RP4S/u391P3K/b79p/2S/XP9QP0G/cv8l/xg/B785/u/+6P7kft7+1b7MvsY+/r61fqt+n/6Tvod+vj55PnV+bL5f/lA+fr4vPiE+Ev4E/jo9873uvel94n3YPc09wX31/ax9o72ZfY79hP27fXP9br1rvWj9ZD1bfVE9Sr1HvUc9Rf1APXi9Mn0vvTF9Mv0z/TR9NL02PTh9PH0A/US9R31IfUf9RX1A/Xo9Mz0uvS19Lj0xPTQ9Nr06vQB9R31N/VR9XD1i/Wu9dj1/fUY9jH2TPZi9n32oPbT9hD3TveO98v3B/g7+GP4g/il+M749vgc+Tz5ZvmX+cH56PkL+in6Pvpb+n/6ovrA+tn6+fog+1L7gfui+8P76PsJ/CX8N/xL/GL8c/x2/HH8a/xm/G78dfxr/GH8Yvxq/Hb8g/yT/KX8s/zD/NP83Pzg/OP86fzw/PL87Pzh/OL87/wC/Rf9K/0+/U79Xf1x/ZT9wP3n/RL+P/5o/oD+g/6J/pn+n/6h/q3+xf7z/jL/cv+q/9X/+/8aADMATQBwAJwAxgD0ACYBTgF2AaIBzAHxARUCNwJMAloCcgKTAr4C9wIrA1ADbQN8A38DgwOOA5gDoAO0A9ED/AM3BG8EpwThBBcFUQWNBcIF6gUIBiQGQQZbBncGmwa9BtsGAwcvB1AHXgdqB3UHgAeWB7YH4wcTCD8IZgiNCLYI2wj8CA8JFAkUCRQJHQkvCUcJZwmJCagJyAnkCfUJ9AngCcYJrwmfCZsJnwmpCbkJygndCeYJ2QnCCbEJswnBCckJwwmzCakJsQnMCfIJEgonCkAKWApZCkUKLwobCgQK6gnOCbIJnQmTCYMJcgllCVUJTAlMCUEJHQnyCNAItQirCK4IrgiwCKoIkgh5CGcIXAhXCE8ISAg/CDAIJAgUCPsH5gfcB9MHxAetB48HdwdmB2IHbAeAB5QHkAd5B2QHSgcwBxIH6wa+BocGRAb/BcMFjAVSBRUF1ASUBFEEDgTQA6ADeANKAxADzAKJAlQCJgL6AdIBrAGCAVcBLAEKAe0A0ACwAJAAeABmAFQANwALANz/rP+B/1v/NP8K/93+tf6R/nH+X/5Q/jH+A/7X/bf9mf14/Vn9Pv0k/RL9Bf3x/Nr8v/yr/J/8lvyJ/G38Tvwx/BT8+vvx+/D77Pvs++X7y/ul+4H7ZftO+zr7LPsi+xz7F/sG++z6zvqo+n76VPo2+i36Nvo/+jz6KvoH+tr5oPlX+Q35w/h0+Cr49PfP96/3l/eJ93/3afc79xf3Bff79vD24fbH9p/2d/ZH9hv2//Xv9eH1y/Wy9aH1o/Ww9cf16PUG9h32LfY09jj2QvZK9kv2UPZm9ov2sfbH9s721fbj9v32J/dQ93z3qPfP9/D3+vf29/H35/fc99P3zffP99738fcC+Bz4OfhV+HH4jviq+Lj4w/jN+NX45/j/+Bn5O/lk+Yf5pPm7+df5/Pkw+mv6mvq1+sL6yPrR+t/68/oH+xr7Kvs7+0/7Zvt4+4D7gvuA+3j7bvte+0v7RvtR+1/7Z/tv+3z7kPuu+8/78/sb/Dn8Rfw//DL8Lvwx/Dr8SPxe/Hr8nPzA/Nv89fwN/Rj9Gf0e/S79O/1F/U/9Yf2B/av90v3u/Qr+JP5B/mv+mP6+/tv+7v4D/yr/Wf+F/67/3f8ZAFUAjgC/AOAA/gAqAVsBjwHKAQECNQJuAqsC5QIdA1IDfQObA7EDygPvAx4ETgR0BJcEvgTqBB4FTQVsBYMFnAW/BeUFBAYgBjoGUwZ0BpoGvAbYBv0GMgduB6kH4gcQCC8ISwhnCIQInQi1CNQI9QgTCTQJVAlsCXsJhQmSCaIJtAnPCQAKOgp0CrIK5QoOCygLKwsqC0ELbgubC8EL5QsDDBgMIAwfDB8MJQwxDDMMNQw/DEgMVwxjDGcMawxxDHYMbgxhDF4MYgxlDGwMbgxnDGQMYwxhDFwMSww1DCQMEgzjC5cLRQv0CqoKbwo8Cg0K6wnbCdUJxQmWCVIJBwm/CIIIVAg3CCYIEwj5B90HvAegB4MHWwczBw4H6wa/Bn8GMQbiBaAFcwVKBSAF+gTWBLQEmQSIBHkEZQROBDgEJAQVBAME6gPSA7sDrAOnA6wDuQPIA9MDzQO5A6QDlgOEA28DUgM5AygDEwP+At4CtwKRAmYCQQIhAgAC6gHWAbcBkwFuAVUBSAE9ASwBDQHjALEAgABSACQA7v+x/37/VP8q/wX/5f7B/pv+cf5B/hL+2v2L/TD93fyZ/Fz8FPzB+2v7GvvY+qb6gvpa+ib69fnG+Yr5Qfn3+Lf4e/g5+PX3tfdz9zb3Cffl9rX2d/Y19vv11PW39Zz1dvVB9QX1y/Sc9H/0Y/RI9DX0FvTz89Dzp/N280PzFfP18u3y+fIW8zHzSfNc82XzZ/Nh81HzOvMq8yHzHfMf8ybzMPM880zzWvNf82DzZPNr83nzj/Os89Lz//Mr9FH0fPSq9Mb0zfTL9NL05/QL9UH1gfW+9fb1KfZU9m/2dvZ/9pP2qva99sv25PYC9xz3LPc090P3U/dm94H3ovfE9+j3Evg/+GX4fviT+LP42fj4+Bf5N/lf+Yn5qvnC+cr5xfm6+bX5tvmx+a75uvnR+ej5+fkP+jX6YvqK+qD6rfq++tT68PoZ+037ifvR+x38Zfyg/Mj85Pz7/Bb9MP1R/Yb9xP0L/lf+mf7R/gT/OP9s/5z/x//v/xgAOQBVAHIAlwDAAOIA/AAGAQQBCAEUASQBOQFUAXcBmgG9AecBDAIpAkUCZwKKAq0C1gIIA0MDhAO9A+8DIARTBH8EnASwBMYE3ATpBOwE6wTsBPIE/AQDBQwFHAUwBUoFaQWMBbQF3wUEBiQGSQZpBoUGnAa0BswG4wYBBxoHMgdGB1UHcgeSB7IH0AfkB/YHFAgzCEsIZQh9CJUIrQjBCNMI4gjsCPoIEQklCTgJTwllCXsJjAmWCZYJjwmTCacJxAnqCRYKPApZCmoKdgp/Cn8KeQp0CnEKcQp3CoQKjgqOCogKgwp9CmwKTgojCu4JwQmqCZ4JkQmCCXQJXgk5CQ4J4wi3CI0IXwgkCOYHuwelB5YHhAduB1IHLQf6BsIGjAZdBjoGGQb6Bd0FyQXFBcQFvQWuBY8FXgUiBecEtgSIBFsENAQaBAwEAQTvA8wDngN2A00DJAMCA+QCywK0ApwCiAJ5AlwCNAIEAtUBqQF2AUsBKwEVAQoBBwECAfIA3QDHAKkAhwBbACYA9v/V/8D/r/+f/5X/lP+U/4//ff9g/z7/Ff/y/tP+tf6f/ov+e/5s/lf+Rf5E/kn+S/5K/kT+Lv4O/vj95v3O/bn9of2O/X39bf1l/VP9Nf0T/fH81fy9/KP8ivxz/Fj8M/wQ/Pj75fvU+8f7vfu8+8H7u/uu+6n7pfuR+277SPsm+wv77/rQ+rb6n/qE+mv6Vfo3+gb6xfmP+Wn5U/lH+Tr5Nfky+TD5L/ko+R/5FvkX+Rf5EPkG+fP43fjQ+Mn4uviq+Jz4hPhr+Fz4VPhI+Dj4Mfgs+DT4QvhJ+FH4Yvh7+JD4nfin+Kv4s/jE+Nn48/gS+TD5SPlf+YL5qfnC+dX55vnu+fv5CvoL+gb6//n8+fv5+vn5+QT6JPpP+nb6lvq2+s763Prq+vr6DPsj+0L7YPt8+5T7nvum+7773vsI/Df8W/x8/J38wvzs/Bb9RP10/av96v0n/mb+oP7G/tH+0f7a/ub+7v74/gr/I/9F/23/k/+3/9n/+f8XACwAOAA/AEYATgBgAIAAogDBAOIABAEeATABPAFCATsBLwEpASwBOgFFAUkBTQFOAVEBUQFNAVABVgFWAVEBVgFmAXMBfQGMAagBywHiAekB7AHmAdcByAGzAZwBkAGRAZsBtAHXAfwBHgI2Aj4CQQI/AjgCQAJYAm4CewKCAoQCgQJ9An0CfAJ8AoECjwKsAsICxgLCAsICywLSAtcC5QL1AgkDKANMA20DjQO0A+kDIgRUBHoElAStBMIEywTZBPQEFAUqBTUFRAVbBXEFhAWPBZcFnAWVBYsFgwV/BYAFkAW0Bd4FBwYiBisGLAYwBj0GSQZUBmUGgAamBs0G6Ab3Bg4HLwdIB1MHVAdTB1MHVAdRB00HTwdZB2MHZQdrB3YHgweTB6YHtAe6B7oHuQfBB8wH1gfiB+wH8AfjB8UHoAd+B14HNwcEB8sGlQZpBj8GGgb9BdkFsgWPBV0FIgXhBJsEVAQYBO0DygOpA4YDWwMoA/YCwQKHAlMCIALiAZwBXgEoAfcAyQCdAHgAUAAtABoACADy/9b/o/9i/yL/6/64/ov+av5W/kj+O/4v/iH+B/7l/cb9qf2R/YD9b/1a/Un9Q/07/S/9JP0V/Q39Av3p/M38tPyp/J38kPyJ/IP8fvxz/Fz8Qvwm/AD81fuw+5z7lPuZ+6r7wfvR+9f73Pvh++37+vsF/A78C/z++/L77vvs++f72vvP+8r7zPvX+9v70vvB+7f7uvu++7n7q/uf+437dPtm+2D7Vvs/+xr7BfsA+/v67vrR+q/6kvp9+mv6XfpT+kv6QPo0+i/6Lfok+hb6A/rs+df5wPmn+Zj5nPmq+bP5sPmi+Zz5ofmu+b35xPnF+cP5uvms+ZP5c/ll+XD5hPmU+Zz5n/mf+aT5sfm6+bn5tPmr+af5qvm3+c355fkG+ib6R/ps+ob6l/ql+q76s/q8+s/66voN+zr7afuO+6X7sPu0+7X7wPva+/37IfxE/GL8ify//Pv8Mf1g/Yv9t/3l/RD+Ov5X/mL+ZP5p/n3+lf6t/sX+4P4I/zP/W/+B/6P/w//g//7/HwA/AGAAiwC9ANYA1ADJALgArQCrAKgAnwCVAJEAlwCrANEACAFAAXUBqwHTAewBAAIVAiwCQAJNAlACUwJlAoUCqgLQAusC9ALnAs8CtwKuArYCwQLNAt4C8QIBAwQD/wL5AvMC9ALyAugC4QLiAvACBgMeAzMDOwM/A0QDQgNDA0cDRAM5AyYDEgMOAw4DBwP7AugC0AK5AqoCogKaApUClgKXApQCkwKbAqACkwJ4AlgCOAIRAuoBygG7AbYBtgG7AboBtgG0AbQBswG8AdEB6QH8AQsCHgItAjgCRQJRAmMCfQKQAqACuQLgAhEDQgNxA6EDzAPlA/ID/QP6A+oD5AP3AxoEPwRjBH4EjgSnBL4EyQTRBNYE3wTqBO8E6wTcBMkEugS2BLgEuwS9BMYE2wTyBP4E/AT8BAoFGQUcBRQFEgUeBSsFNwU6BSQF+gTNBKgEgwRgBEsEPQQqBBUEAgT5A/kD8QPcA70DlANvA1ADOAMpAyIDHAMbAyUDLQMsAy8DLgMdAwkD9QLfAskCrQKSAn0CbAJdAkwCOgImAhQCBgL5Ae0B3QHJAa4BhwFjAUwBPQExASABCgHwAM8ArgCTAHsAXAA5ABcA9v/X/7b/k/9y/1n/RP84/zP/Mf8l/wf/6/7W/sH+qv6H/l7+PP4j/hH++/3k/cn9rf2T/X39cP1u/XP9ef1//Yf9if2H/Yv9k/2c/ab9qf2g/Y39eP1o/WL9X/1k/W39c/19/YD9ev1y/Wb9U/09/Sv9If0T/Qj9Bv0L/RH9E/0T/Rn9Jv02/UX9U/1e/W39gP2c/bj90/31/Rz+Rf5q/oX+nP62/t3+EP8//2D/b/97/5v/y//2/xkALwAvACgAIwAlAC0ANgA3ADcAQgBRAF8AcAB7AG8AWgBKAD8AOgBDAFQAXABeAFsAUQBAACcAFQARABsAMgBDAEsAVABZAFMAQQArACIAIwAlAB8ACgDz/9v/wf+v/6n/sf+3/7n/rv+c/5T/kP+R/47/fP9l/0b/JP8K//D+0P6p/oL+Zv5Q/kH+OP4n/g7++f3q/eD91f3P/dT90f2+/aH9iP1+/X79gv1+/XT9cP1s/WT9Xv1Q/Tz9N/04/S39I/0d/SH9Mv1N/XT9l/2t/b39x/3T/eL97/35/QT+GP4z/kv+Yf5s/nT+eP5u/mb+XP5O/kT+Q/5J/lD+U/5S/kv+S/5T/lf+Vf5J/jv+Ov4+/j3+Lv4W/v/97f3p/e797P3j/d792f3J/bb9qv2c/Yz9gv12/W39d/2Q/aX9sf2x/az9qP2m/Z/9mP2R/Yf9f/18/XL9UP0h/fT8yvyi/IP8avxV/EL8MPws/Df8RPxE/DX8JfwY/A38/vvw++n73fvJ+7H7mPuN+4r7ivuO+5n7rfvD+9v7+PsO/CH8Q/xy/J/8yfzu/A/9KP04/UT9Uf1g/Xf9l/27/dn99/0W/jb+U/5q/oD+kv6o/sj+9v4y/27/of/O//P/FgA4AFIAaAB6AIcAmwCtALYAwADOANkA2QDSANMA3QDrAPYABQEeATgBUQFjAXEBgAGSAaYBvAHUAeQB6AHpAegB5wHhAdkB2QHjAe0B8QHsAeQB1gHDAbcBsgGoAZkBhQFxAWoBaAFkAVwBSwE9ATABIAERAQkBEwEkAS4BLwEpAScBLgE7AUwBXgF7AZQBqQHIAegB/wENAhUCIwI+AmQCjQLAAv8CPgNtA5IDsQPCA8oD1QPoA/4DEwQwBEgEXQRuBHYEeAR5BIIEjQSSBJkEsgTfBA8FMQVBBUwFVgVbBWAFawV5BX4FeAVuBWMFWAVWBVkFXgVkBW0FdAV1BW0FXgVHBSkFDwX5BOgE3QTUBM0EzwTVBNcE0wTRBNME2gTiBOgE6wTtBOYE1wTHBLkEsASvBLkEwQTCBLYEpASYBJAEjwSZBKoEvQTJBNkE8wQFBQkFCAUKBQYF+gTtBNsExgS2BLEEtAS7BLUEoASHBGcEPQQPBOkDxAOcA3sDXAM6AxcD9ALQAq0CiwJmAjcCCgLjAbsBlgF5AWYBUAEtAQYB3gCqAGgAJADq/8P/o/9//1//PP8b/wL/6/7P/rT+n/6J/mv+Tv41/hr+/P3k/dH9v/2n/ZL9gv1v/V39Tv1J/U79Uf1T/WH9df2A/Xn9a/1f/VH9SP1E/T79Mv0z/UL9Tf1U/Vr9Xv1e/Vr9Vf1T/Vz9Y/1k/WP9W/1G/TX9Mf0z/Tf9O/0+/T39O/06/Tj9N/1B/Vf9af1z/X39hP2G/Y79lf2Y/Zj9lv2U/ZH9k/2Q/Yf9d/1c/Tz9If0T/Qv9Bv38/Or80vy4/Kb8mfyH/H/8fvx//Ib8ivx//GH8QPwo/Bn8DvwC/P77APwB/Pr77vvc+8n7vPu0+6v7p/ur+6/7r/us+7D7v/vL+877yPu7+6z7nvuY+5z7p/u2+8X71vvk++r78/sA/Ab8CPwK/Bj8NPxa/If8svzV/PL8Cv0m/Uf9Yv10/YD9kP2k/bn9yf3S/dz96/34/fv9/P0A/g7+I/4z/kX+Xf56/pL+lf6Q/pX+pf60/sL+z/7Y/uj+Df9A/3L/k/+i/6j/sP+8/8T/zv/e/+////8RACYAMQAsAB8AEQAIAAMABQAQACEANQBIAFAASwBHAEcASgBTAGIAdACJAKIAxwDwABgBPgFmAZABtgHjARoCUQKBAqQCxALgAvoCFwMsA0YDagORA7kD4AMCBBwEPARmBI8EtATRBOUE+gQNBRsFKQU5BU4FZAV9BZYFpgWtBasFoQWQBX4FbAVcBVEFSAU8BS4FIgUUBQcF9QTUBKYEawQtBPQDvgOTA24DRgMfA/gC0QKrAoUCZgJIAjACFQLxAc8BrQGVAYgBgAGAAX4BcwFdAUkBRwFTAWABawFzAXYBdQFsAWMBWQFRAVABVAFXAVMBSQE/ATwBPwFLAV0BbgGBAZEBnQGfAZgBigFuAVEBOwEqARwBDgEDAQYBFQEkAS0BQgFeAXgBkQGlAa8BpQGYAY4BfgFtAWUBXAFNATcBGQH+AOgA0AC4AKMAlQCKAIUAiQCTAJYAjAB3AFsAMwAGANX/pP96/1D/Kf8J/+X+uf6M/mf+TP41/iP+F/4S/hX+Gf4g/i/+Pv5O/lz+Zv5s/nD+e/6J/pL+k/6N/on+jf6a/qz+u/67/rL+pP6T/n7+Z/5R/jj+JP4c/hv+G/4T/gr+/f3k/cv9vf2v/aT9m/2O/Yb9if2O/Y/9i/2H/YD9b/1d/Uz9M/0L/dv8sfyU/H/8a/xa/E/8SPw2/Br8APzx++T7zPur+4f7cvtu+3H7ePt8+3v7b/tU+zD7Cvvu+tr6yfq9+rb6svqp+pn6kvqc+qb6oPqO+nz6cfpm+lb6Rvo++kD6RvpF+jv6KvoU+gD69Pnr+dr5wvmv+af5nvmT+Y35jvmf+bz54PkG+iP6O/pW+nb6mvrB+uv6HftZ+5/76fsr/Fv8fPyc/Lz84/wR/Tv9W/13/Zj9vP3a/fD9Af4R/iP+Of5U/nj+oP7D/uj+EP8x/0b/Tv9W/2v/hP+e/7b/0v/o//P/+v8CAA8AKgBPAHMAjQCdALAAzADmAOsA2ADNANMA3QDnAPcAFgE6AVUBbAF4AYABhQGHAYoBiQGFAYIBgAGHAZYBrAHEAd4B9gEKAiICOwJQAmYCgQKfAroC0QLpAgADDAMeA0cDfgOsA8UD0QPhAwMELQRWBHoEnQS+BN8E+wQPBSMFNgVIBVMFYgV8BZgFtAXNBeIF9QX+BQcGDQYPBg8GBQb4BfQF8QXgBbsFjQVlBUwFPgUwBR4FEwUFBfcE4gTBBJwEfQRpBFUENgQZBAUE8gPkA9oDzAO1A50DigN3A2QDUAM9AzEDLAMqAx0DDAP9AukC1wLPAtMC2gLmAvsCHQNCA1oDZQNkA2MDbgN8A4EDdANhA1cDVANNA0EDMAMgAxoDGAMVAw0DAgMEAxEDIwM/A2QDigOpA8ID3wP6AwsEEgQOBAQE/APwA98D0wPIA7YDpAOTA4QDfgOEA5IDogOsA7YDwgPCA7YDpAORA3gDTwMhA/QCywKnAoMCaAJZAk0CQAIsAhEC9gHXAawBbgEtAfsA3QDNAMQAtwCpAKIAlAB7AFIAIgD9/+D/wf+f/3n/Rv8P/+L+uf6I/lL+H/72/dj9w/2z/ar9nP2J/Xj9a/1e/Vf9Vv1Q/Uf9PP0v/Rz9Bf3u/Nf8yfy8/LH8qfyn/Kr8qfyt/LX8wPzM/NH80fzQ/M/8yfzA/Lz8tfyu/KT8l/yJ/Hj8c/x3/Hz8ivya/KT8qfys/K38rvyu/K78r/yr/KX8oPyc/J38pPyv/Lz8zPzb/OD81/zD/Kf8hPxj/D38G/z7+9j7t/uW+3T7UPsq+wL74frV+tP6y/rD+r/6t/qq+p/6kPp8+mn6V/pG+jj6Lfop+if6Kfo7+ln6dvqM+pb6nPqx+sr65foG+yL7QPtf+377o/u++9f79fsU/D38W/xf/FT8RPxB/E38XPxu/Hr8ePxo/Fb8SvxB/Db8I/wK/Pn78fvz+/f7AfwS/B78IPwY/Av8BfwP/B/8MPw//E38VvxY/FH8SfxH/EX8P/w4/C/8KPwk/Cr8QPxf/HX8ePx2/Hn8gvyR/J/8qPyy/Lf8ufzE/NX84/zp/Oz8+fwT/TH9Sv1i/YH9qP3M/ez9Bf4c/jP+Q/5O/lD+V/5u/pD+tf7c/gr/Qv98/7P/7P8gAFAAfwCuAOEAEQE/AXABnwHHAe4BGwJJAnUCowLMAvACFQNCA3IDngPBA94D9QMHBBgELwRIBGEEdwSMBKAEsAS3BLYEtgSwBKgEoASWBI4EjASTBKAErwS2BLEEoASIBGkESQQvBBkECgQABPQD6wPkA+YD8AMABBkEKQQtBCsEKQQzBEEEUgRrBIcEmQShBKYEpQScBJEEjwSYBKkEuwTLBNsE6ATzBPkE+wT6BPkE+wQDBRUFLwVQBWwFdQV3BYAFkgWtBcUF1QXhBekF8AX7BREGOwZwBqIGwQbQBt0G5gbqBvEG+wb8BvYG7gboBucG6gbwBvAG8QYBBxYHKQc4Bz8HOQctBx4HCAfvBtgGxAa8Br4GwgbHBsIGtgauBqgGoQaSBoAGcAZmBmAGUAYtBgEG3QXABZ0FcgU+BQMF0wS7BLUEsgSnBJwEmASdBKgErASdBIAEXAQ2BBcE/wPuA90DzQPEA8QDxwPEA7gDpQOLA3UDagNoA2kDawNuA28DZgNSAzcDGAP4As8CpQKDAmYCSAIsAhIC9QHWAbkBnwGJAXABTAEhAfYA1gDBALAAoACMAHkAbQBiAFQASQBHAE0AUQBOAEAAKwAbAA0A9//e/8z/u/+j/43/ef9n/17/WP9R/0r/QP8n//z+yf6Y/m/+TP4w/hH+7v3P/bD9lP11/Ur9E/3h/Lv8lvxo/DL89/u9+4b7T/sT+9P6nPpt+jz6Dfrw+eP53vnU+cX5vfm0+aL5h/lw+V35SPkx+Rr5Bvn1+Oj41Pi2+Jz4h/h5+Gv4YPhj+Gb4YPha+Fz4a/iG+J/4q/in+Jj4ifiA+Hr4dfh2+Hv4gfiF+I34oPi0+Mj43Pjq+PD47fjs+PL4/PgF+QX5+Pjy+P34A/n/+P34AfkH+Qz5E/kb+R35GfkR+Qj5CvkZ+TX5T/lm+YL5oPm8+df57fn9+Qz6F/oe+iz6OvpG+lP6X/po+nb6ifql+sf65fr/+hT7GvsX+xv7LvtD+1D7Xvt2+477ovuy+8j74fv5+xH8J/w8/Ez8TfxD/Dn8Ovw+/D/8QfxI/E/8W/xs/IT8ovy+/M780/zU/NH8zvzN/ND83vz5/CL9S/1o/Xb9fv2E/Yv9lP2c/aj9uf3G/c/92f3g/eX97/3//Rj+N/5W/mz+fP6U/rb+2P76/iL/Rf9d/3j/mf+7/9z//v8kAFQAgACaAK0AwgDdAPUACQEiAT8BXQF9AZoBsgHNAfABGgJEAm0CkgKuAsAC0ALhAvQCBgMSAxsDIAMoAzsDTQNYA10DXwNXA0gDPgM4AzMDLAMfAxIDBAP8Av4CDgMuA1EDbwOEA5gDuAPjAwkEJAQ6BEsEWgRqBHsEkQSkBK4EuATHBNsE9gQXBT8FYQV8BZEFmAWbBZwFnwWmBasFtAW+BcoF4AX1BfoF7AXKBaIFggVnBU8FQgU7BTQFKgUcBREFBQX+BAEFBQUIBf4E7QTqBPUECAUXBRcFCgX3BOwE4QTVBM4EygTKBMwExQS1BKcEnwSYBJIEkgSQBIYEfQR2BGgESQQmBBMEDAQHBAAE+gPvA90DxgOqA40DcANUAzwDJwMMA+4C2QLKArsCrgKkApoChwJoAkcCMAIgAg8C/AHmAdEBxAG2AaMBkAF+AW0BWQFBAScBDAH3AOYAzgCwAJAAdABkAFsATgA4ABsA/f/X/6f/c/9I/y3/HP8M/+7+yf6o/oj+Zf5D/iH++v3U/bD9kP1z/U39JP0A/eL8z/y8/Kn8l/yE/HT8YPxM/EL8PPw4/Dj8P/xI/FH8Yfxu/HX8ffyK/Jz8s/zM/N787Pz5/AL9Bv0I/Qj9Af30/O/87/zv/PH88fzn/M/8sfya/In8ePxp/F78Xvxk/GX8Zfxh/Fv8VfxQ/Ej8P/w9/Eb8UvxX/Fn8YPxm/GP8W/xR/Ef8Q/xH/Er8TvxV/GH8cfyC/JD8j/yJ/IP8ePxv/Gb8XvxU/Eb8Pfw0/C78Kfwj/CL8H/wY/BX8FPwR/Ab89/v3+wj8Gvwk/CP8HfwX/Bb8H/wt/Dr8Svxk/Ij8rPzK/Of8/fwL/Rn9Kf0+/Vn9eP2N/ZT9oP22/cb9zv3P/cn9yv3Y/fH9EP4u/k7+bv6H/pz+sv7I/uH++f4R/yn/Q/9Y/2j/dv+D/5j/tv/Y//b/EAAoAD4AUQBhAG4AgwCgAMEA4gD9ABEBHgEsAUIBVgFmAXYBjwG0AdkB9AEKAhsCJQIpAigCJgIvAjwCRwJWAmcCdwKFAo4CkgKTApAChwKAAogCmwKrArMCtQK/AtAC4wL2Ag0DJwM6A0EDPwM9A0ADRANEA0cDVQNsA4QDnwO6A9MD7wMPBCwERwRdBG0EggSYBK4EzATqBAQFGAUrBT4FRwVKBUEFMwUkBREF9wTaBMYEtgSkBI0EdQRmBGEEXgRUBEcEPQQ8BDgEKAQYBAoE+QPlA8wDsQOYA4EDaQNSA0EDNAMoAx8DGAMNAwMD+ALsAuQC1wLEArQCqAKbAowCgwJ6Am4CYAJRAj0CHwIDAu0B1QG/AbABqAGdAY4BewFqAV0BSAEwARkBBAH1AO8A+AADARQBLgFDAU0BUAFbAWwBdgF+AYIBgAGFAZIBoQG1AckB1QHcAd8B3AHZAdoB4AHuAQcCIQIuAjICMwIxAjICNwI5AjMCIgIRAgMC+QHzAesB4gHZAdIBygHCAb4BwQHMAdkB2AHNAbwBpQGQAYABcAFcAUIBKgEfARUBBAHsANcAxwCwAJcAgQBqAFcATgBDACsACgDt/9n/yf+3/6j/of+f/6D/nf+N/3T/XP9P/0n/Qf8x/xr/AP/m/sn+q/6K/mz+U/43/ij+Jf4b/gH+3P3C/bb9qv2a/YL9Z/1S/UD9Nf0y/Sz9If0V/Qn9//z4/PT87vzq/PD8/PwM/Rv9I/0p/TX9SP1a/Wj9bv1t/Wv9b/11/Xv9jP2m/cD92f3w/QL+E/4m/jX+PP49/jb+Mf47/lD+Y/5v/nT+c/5r/mj+df6H/pr+qv63/sj+2/7o/ur+5P7Y/sb+s/6g/pL+kP6Z/qD+n/6a/pD+fv5r/lj+TP5K/k7+Uv5U/lX+Sf4z/iH+D/4A/vr9AP4P/iP+Nv49/jr+Lv4g/hn+Gf4Y/hT+EP4I/gL+Af4F/g7+Ff4X/hH+B/4D/gr+Ev4J/u/91f3B/av9kf1z/VT9P/03/S79JP0h/R/9Gf0V/RT9F/0V/Qv9+fzm/N380/zB/Kr8jPxy/GX8WvxG/Cz8Evz9++374PvV+837zPvP+9f73vvn+/D78vvx++775PvW+8v7yvvT++j7EPxA/Gv8j/yu/M786fz//Bb9MP1R/X39q/3T/fL9D/4s/kL+Uv5n/of+sf7h/gb/KP9N/3f/pf/R//b/EwAuAEgAWABdAGEAXQBWAF8AfACbALgAzwDeAOoA9AAAAQYBAQEBAQQBDAEeAS0BOQFGAVkBZQFmAWQBWwFWAVQBSwE9ASoBGQEJAfMA1gC+ALYAugDEAMgAzADQANMA0wDJALwArACYAI8AkgCWAJEAiACAAH8AewB7AHwAdABpAFkASgA6ACoAGgAFAPP/4//S/8f/vP+x/6//u//T/+//CgAlAD0AUQBqAIAAjgCXAJ4ApgCuALwAzwDfAO8AAgEQARkBFwEUARgBHQEkATYBWwGNAb0B6wEUAjgCTgJSAk0CRgJFAkUCRAJIAlcCdQKSAqoCtwK9AskC2QLoAvUCAAMMAxoDJgMqAy4DNwNBA0oDVANhA3UDkQO2A9YD7QMDBBgEJgQxBDkEQARMBE8ERAQ3BDYESgRqBIkEqwTKBNoE3gTpBPYE+QTyBOgE3ATTBMsEvwSxBKAEigRyBFwETARFBEAEOgQxBCkEIQQQBPQD0QOqA38DVwM8AyYDDwP0AtQCrQKAAlsCPwIeAvsB2gG6AaABjwF8AVwBLAH1ALkAfABFABAA3v+z/47/a/9J/yP/Af/q/tn+yP65/rD+o/6Q/nn+av5l/mL+Wv5Q/kf+Sv5K/jj+IP4E/ur92P3N/cT9vv26/bT9rP2n/aL9lv2N/Y79l/2r/cD9y/3Y/ev9/f0F/g3+HP4s/kH+XP56/pX+rv7N/u3+C/8s/0P/U/9l/3j/kP+v/8//7P8EABUAIwA0AEMATgBTAFcAXwBmAGgAXwBPAEAANgAxAC0AKAAfABIAAgDr/9L/vP+q/5z/j/98/2L/SP8t/w7/7f7L/qz+k/6E/nr+bP5d/k7+PP4r/iL+G/4L/vf93/3F/a/9mv2I/Xr9av1b/U/9Qf01/Sr9Hv0V/RX9GP0d/Rr9Dv32/NX8vfyv/Kv8pvyX/In8gfx6/Hf8dvx8/Ij8jfyN/Jj8tPzb/Pj8Cv0e/S/9P/1X/Xf9l/2x/cv94/33/Q3+Jf5C/l7+df6I/pn+qv65/sn+1v7h/uz+9P75/vf+9v76/gL/Df8c/yT/Iv8l/zD/N/9A/1P/bf+M/6//yv/a/93/0//R/+P/AQAZACcAMAAzADUARABVAGAAcgCBAIwAnACuAL8AzADYAOEA4gDjAOsA8wD7AP8AAgELARIBGwEmASoBLQEvATUBQAFJAVIBWQFcAWABXwFZAVYBUgFMAUYBRAFIAUcBQAEwARcBAgH4APsAAgEKARIBEwEOAQUB8wDeAMwAvwDAAMgAyAC/ALkAtACvAKAAgwBXACMA+f/W/7P/l/9+/2H/Q/8m/wb/6P7L/q/+m/6H/nH+Xv5J/jD+Ef7y/df9vf2o/Zn9l/2f/aX9qv20/b79yf3U/dv94/3v/QX+H/4u/jX+Of47/j3+QP5I/k7+U/5d/mP+Z/5v/nL+cv55/nv+d/56/oH+iP6U/qj+vf7O/uL+/P4a/zr/Xf9//6H/yf/w/wsAHQApADUARABNAE4AVQBkAHIAeQB9AIEAgQB8AHMAawBrAHoAjQCfALIAxwDkAPkABwETARMBEgEbAScBLQEsAS8BPAFNAVcBXQFlAW4BcAFvAXABcgF9AY0BlwGSAX8BagFaAUwBPwEyAR4B+wDZAL0ArACjAJ4AngCcAJUAhgB5AHQAcwBwAGgAXQBRAEwAUABZAGgAfgCQAJoAmQCTAJQAnACnALcAwwDKAM4A1gDlAPAA+AD7APMA5wDbANEAywDHAMQAxQDJANIA1QDTANYA2gDdAN8A4QDgAOAA4wDqAPgACAEQARYBGgEZAR0BIwEoATIBQAFWAWwBdQF4AXoBfwGGAYgBjAGTAZ8BsAG/Ac8B4wH9ARwCOQJTAnACjwKqAsMC4AL9AhMDHwMiAysDPgNPA1gDZQN9A5gDrAOzA7QDrwOqA6cDpgOjA5sDkwOQA44DggNzA2gDYANeA2UDbANrA2cDZANdA1IDQwM3AzMDOANAAz8DOwMxAx8DFAMWAx0DHwMWAwcD+ALrAt8C1ALQAskCuAKqAqkCswLBAscCwgK2AqUCkgJ4AlgCOwIhAggC6gHGAaYBiwFyAV4BTQFBATgBLgEvAToBQgE9AS0BGwEKAfkA7ADiANgA0QDHAL8AvgC+ALQAnwCJAHsAcABnAFcAQgA3ADEAMQAqABkAEAAQABAACAD7//H/8f/y//r////+//n/5v/J/6f/f/9d/0T/J/8J/+z+0f63/pb+ef5s/mP+Xv5Z/lT+Tf5E/kf+UP5d/m3+fv6J/on+gP52/nD+Yf5K/jb+JP4K/un9yP2p/Y/9ef1g/Uj9OP0u/SH9Ev0G/fb84PzE/KT8i/x6/HH8avxh/Fr8XPxj/G38efyC/IX8f/xv/GL8WPxN/EL8Ofw1/DT8Lfwj/B38H/wj/CX8Kvwq/CH8Gfwb/CP8KPwp/CX8J/wp/CX8HfwN/Pj75fvZ+9T70fvQ+877yvvL+9P73/vm++L73fvb+9z72vvO+8L7v/u8+7r7tPuu+7D7tvuy+6P7mPuS+4v7gvt8+3r7dfty+3b7hfua+6z7ufvB+8f7y/vW++77Bvwa/C78Rvxf/HP8hPyU/KL8q/yv/Ln8zPzi/Pv8Ev0q/UL9W/12/Yn9k/2P/YX9fP15/Xj9dv14/YP9mP2u/br9u/28/bz9t/2u/av9t/3F/cv9y/3N/dr97f0G/iz+Vf55/pP+q/7I/uT+/P4Z/zn/Wv99/5f/rP+9/8r/0//W/9z/6P/+/x8APQBTAGAAbACDAKMAxADhAPoAGQFBAWYBiAGeAaEBmwGXAZ4BsgHKAd8B6AHsAfIB/gEOAhQCEwIVAiECNwJSAm0CggKXAq4CxQLQAs8C0gLVAtUC0wLNAsoCzALPAtYC3wLpAvIC+AIBAwkDCgMGAwED+ALrAuIC4gLiAt0C0QLIAsgC0ALcAu8CAgMUAyYDNwNKA1YDUwNLAz4DLwMoAyIDGQMPAwAD9QLsAt8C1wLWAtoC3wLkAvICDAMvA1EDaQN4A4IDhwOIA4ADbgNcA04DRgNDA0MDSANMA0kDOwMmAxYDCwMAA/YC8wLzAvYC/gILAxcDHQMbAxUDDQMFA/oC7gLlAuAC2QLOAr0CqAKYAowChgKFAogCjAKZArACygLhAu4C7gLkAtQCwwK1AqcClwKIAn8CeQJzAnACbAJmAmECVwJIAjECFQL7Ad8BxQG3Aa4BowGaAZMBjAGGAXwBdQF4AYMBjQGQAZoBogGjAZ4BkQGEAXkBcAFtAW4BdgGAAYkBkgGcAaYBrwG2AboBvAHBAc0B3QHtAfoBAwIIAgcCAALyAd4BxgGpAYkBbQFUATYBFQHwAMwArwCYAI0AiwCFAHwAaABMADMAHQALAPz/6P/M/63/l/+J/3v/af9W/0b/Nv8j/xD/Af/3/u7+5f7e/tX+y/7C/r7+v/7L/uH+8/71/un+2P7H/rf+q/6c/or+ef5n/lf+UP5G/jn+Mv4w/in+G/4K/vn98P3s/eb93/3X/c79yf3J/cf9wP22/af9lv2L/Yj9i/2M/Yf9gf1+/X39e/13/XP9a/1k/WP9Yv1d/VT9TP1J/U/9YP1v/Xj9e/2C/Zj9tf3T/er9+v0H/g3+Bf70/ef93v3V/cr9tP2e/Yz9fP1w/V/9UP1H/T/9Pv1C/Uj9Tf1P/Vn9a/18/Yj9k/2c/aH9pf2v/bn9wf3F/cj91P3g/e399P3y/ev96P3t/fv9DP4Z/ij+N/5C/kn+Sv5M/lT+Xf5k/m/+f/6M/pf+qP65/sj+0P7Q/sv+x/7N/tn+5f7v/v3+Cv8S/xb/Hf8n/yr/H/8O///+/P4D/w//Hv80/0z/Yf94/4r/kP+W/6T/t//H/9H/0v/G/7f/rP+j/5T/gf9t/1z/UP9T/1n/Wv9d/2D/Wf9Q/0r/P/8y/yT/FP8D/+7+1/69/qP+if5s/k7+Nf4g/hH+Bf77/e/96v3u/fT99/36/fj97/3l/eP96/37/Q/+Jv5A/ln+b/6G/pv+sv7E/tb+7f4A/w3/HP8x/0//cf+N/53/p/+1/8H/x//I/8v/1//s/woAKABBAFIAXQBrAHgAggCLAJoAqACzAL8AywDcAPQADQEjATcBTQFoAYABlQGrAcUB3wHyAf4BDQIgAi4COAJGAlcCaAJ3AoUCjAKJAoMChAKPAp0CqAKuArUCwQLMAtcC4wLvAv0CCQMSAxsDJQMqAygDKQMxAz4DTwNYA14DXwNeA2EDXgNNAzIDGAMHAwAD+wLyAukC4ALYAtEC0ALZAt0C0wK7AqgCowKhAp8CmgKbAqQCpgKfApQCiwKGAoUCigKOAo4CkAKbAqsCsgKuAqECkQJ9AmUCTwJCAjgCKQIUAv4B7wHmAdoB0AHMAckBxQG4AaYBlQGDAXIBYgFaAVEBQQExASQBEwH6AN4AyAC5AKoAmwCOAIcAgwB6AHAAYgBKAC0AEwD7/+T/yf+s/4v/bP9S/z7/K/8c/wv/9v7l/t3+0P62/pn+ev5V/jj+J/4h/ib+MP47/kL+SP5L/kn+Sf5J/kr+Tv5N/kb+R/5R/lj+WP5S/lT+X/5u/oL+kv6f/qf+qP6n/qn+tv7I/tr+6f70/vn++/79/v3+Av8Q/xz/Hv8e/xz/Ff8U/xn/JP8x/z7/TP9a/2f/cv95/4L/if+P/5P/l/+Z/5f/k/+L/4b/hf+D/4P/jP+a/6f/t//E/8P/s/+l/6j/sP+1/7v/wf/G/8n/yf/J/9D/0//L/8D/uP+0/7b/u//B/8L/vP+4/7n/t/+s/53/lP+V/5j/m/+b/5b/kP+I/3z/bf9h/2D/b/+A/4r/kP+S/5H/kP+V/5X/kf+N/4z/kv+Y/6H/qv+z/7n/uP+1/7n/wv/K/9H/3P/n/+3/7//t/+r/6//w//P/8f/w/+//6P/h/+T/7f/6/wgAEgAbACAAIQAfABkAFQAUAA8ACAAGAA4AGgAiAC0ANwA8ADoANQA0ADYANwBBAFUAbgCMAKwAyQDhAOwA7wDrAOgA6wD0AAMBEgEdASIBJQEnASQBHQEYARABBAH4AOwA5wDrAPIA+gD9AP0A9wDnANUAxQCzAJwAhABsAE0ALgAYAAIA6f/P/7j/pP+Q/3f/Wf88/yj/HP8P/wP/9/7k/tH+wv61/qb+lv6J/oH+gP6E/oj+hf56/mv+Y/5c/lD+Qv40/iv+Kf4o/iv+L/4w/iv+I/4i/ir+Nf5A/kn+VP5h/mn+dP6A/oz+m/6n/qT+kv6B/n3+gP6E/or+jv6S/pb+mv6g/qn+u/7N/tb+3P7n/vz+GP8w/0b/Yv+C/6D/tf/E/9j/8f8IABwAKgA6AEgAVwBsAIEAkwCiAK0AtwC5ALwAwQDHAM8AzgDDAK8AmwCPAIsAiAB8AGUASQAuAA8A8P/b/8v/uf+o/5r/jv+C/3L/Yv9W/03/QP8r/xT/Av/1/uv+5f7b/sv+uP6q/qH+mf6P/of+hv6H/ob+g/5//nf+af5b/k3+O/4h/gD+4f3R/c/9zP3C/bv9s/2s/aL9lP2G/XT9Zv1g/Vz9Wv1W/Vf9Xv1p/Xn9hv2Q/Zj9n/2l/aj9q/2v/b39z/3i/f79Gv44/ln+cv6A/of+jf6a/rH+0/75/hb/LP9D/17/d/+N/6X/vf/W/+z/+/8HABUAJAA3AE0AXgBtAHoAhQCPAJYAmgCYAI4AfABqAFsAUABHAEMAQAA9ADUAJQATAAUA/f/4//P/8v/2/wEADAAWACQAMwBEAFgAbgCBAJMApgC7ANIA5gDzAAABFgEuAUABUwFnAXcBgQGBAX4BfQGCAY0BmAGhAakBsQG2AbcBvgHFAcwB0gHRAc8BzgHJAbwBpwGRAYABdgFyAXIBdAFxAWcBWQFNAUQBOgEpARUBAwH0AOUA1wDJALoArQCeAIoAdwBpAFsATAA8ADIALAAhABcADgAGAAAA/v8AAAYACQALABMAIAAxAEAATwBdAGwAfwCOAJoAqgC7AM4A3QDpAPYABgEZASoBNQFAAUcBTAFRAVkBZAF0AYsBpwG+AcwB2gHpAf0BEgIjAjICQQJTAmgCfwKTAqcCuwLQAukCBQMeAzEDOwNEA1ADXwNyA4cDmgOpA7QDvwPGA8cDyAPFA7cDoAOHA3MDYwNQAz4DNQMxAy4DKgMiAxYDBQP1AugC4wLgAtYCyQK2AqECjwKDAn4CewJ6AnUCZwJYAkkCOQIpAhcCAwLvAdwByAG4Aa8BqAGgAZUBigGFAYIBfAF0AW0BZwFcAVABPgErARUB8gDLAKYAhwBuAFgARQA0ACIAGQAUAA8ACgABAPX/5P/V/9P/2v/g/97/3//p//D/7f/m/9//1//S/9D/0v/V/93/8P8DABEAIQArACwAIgAUAAoAAAD2/+P/zf+4/6P/lf+N/4z/jv+H/3f/Z/9Z/0P/Jv8K//j+6v7g/tf+z/7I/rz+sP6s/qz+sv66/sD+yP7R/tn+3v7Y/sv+tv6i/pX+hv5//oL+hv6O/pr+q/66/sH+xf7N/tz+6P7t/vX+A/8V/yT/Mf87/0T/Sf9G/0L/PP82/y//Jf8d/w3/8v7S/rv+q/6d/oz+dv5g/kj+L/4Z/gj+Af77/fP94f3F/a/9qP2l/aH9n/2a/Y39fv12/XH9Yf1F/Sv9H/0g/Sj9L/0y/TP9Nv0+/UT9QP04/S79Iv0W/Q39DP0N/Qn9/fzv/OL82fzT/M78zfzN/Mz8zfzQ/Nv86/z8/A39Gv0i/Sr9Of1Q/XP9m/2+/dz9/P0b/jT+Tv5q/of+pv7H/uz+Dv8r/0n/Zf99/4//nf+r/7r/zv/q/woAKABDAF8AeACFAIkAjgCRAJAAiACCAIUAjwCXAJ4AsADMAO4ACAEWASABLAE4AUIBTwFdAWgBbgF3AYUBlwGnAbABtwG3AbIBsgG5AcgB2QHjAekB8AH6AQMCDAISAhQCEwIRAg8CEgIcAiECHwIfAiICIgIeAh0CHgIbAhUCEwIUAhUCHAIlAiMCFAL7AdsBxQG5Aa4BowGXAY0BiAGHAYgBiwGIAYIBewF5AX0BhAGIAYQBfgF+AYgBmgGuAcMB0wHkAfoBCgIUAhwCJgI2AkMCUwJoAnwCiAKIAoICeQJ0AnUCdgJ1AnUCdAJvAmICSwIsAgsC5wHCAZsBegFfAUgBMgEXAfoA4QDHAKgAjQB5AGoAXABTAE0ARwBAADUALQAqAC4APwBUAGUAbwB2AH0AfwB7AHcAbABgAFgAVgBbAGQAcgB8AIAAfwCAAIIAgwCCAHcAbQBpAGUAXgBTAEUAMgAhABMAAwDx/9//0//H/7X/n/+I/3P/Wf86/yH/E/8J/wL//f4A/wL/+f7q/t3+0/7K/r/+r/6k/p/+mv6Q/of+g/58/nT+b/5n/mD+Wf5R/kv+Rv5G/lL+Yv5u/nH+cP5w/mv+Xf5M/jz+Kv4Z/g/+CP4F/gH+9v3n/df9xf2u/ZX9e/1b/Tf9Gf0G/fv88vzv/PL89vz4/Pb89fz8/AH9Bv0P/Rv9KP01/Uf9W/11/Yj9jf2L/Yj9h/2M/Zb9oP2p/bP9wP3U/ev9BP4Z/iv+Of5B/kb+R/5I/lP+Y/50/oD+jP6b/qf+s/69/sb+yf7D/rj+s/6x/rH+t/6//sn+1/7q/vz+B/8Q/xn/If8q/zH/M/8x/zD/NP8w/yv/J/8j/yb/Jv8k/yD/Gf8P/wH/8/7x/vv+C/8Y/x//Kv85/0f/U/9g/23/fP+M/5j/nP+V/4T/cv9p/27/gv+f/7r/yv/U/9n/3f/e/9v/2f/X/9b/0v/U/93/5//v//X//P8GAA8AFgAbABkAFQAZACQAMgA/AEwAWgBnAHIAcgBoAF4AVwBTAFIAUwBVAF4AbQB3AHoAegB1AGUATAA1ACwAMAAxACsAJAAlACwALQApACQAIQAgABwAGgAaABYACwD5/+v/2//M/7//tf+0/73/xv/H/8P/wP/I/9f/5f/z/wEAEQAkADsAUQBkAHUAgwCNAJAAjQCFAHsAewB/AIIAhgCIAIcAhACBAH4AdgBpAF8AVgBNAEgAQgA9ADUAIgARAAEA8v/t//D/9P/3//L/6v/p//T/CQAZACMAMgA/AEsAVgBaAFkAWgBlAHYAggCLAJYAogCuALUAtgC1ALgAvQDCAMgA0QDXANgA2gDgAOQA6QDsAOsA6QDpAOwA7ADqAOwA7wDrANwAygDDAMUAxwDLANEA2QDeAOIA6ADwAPsABAEMARUBGwEjAS4BNgE7ATwBPAE6ATYBOAFAAUYBSwFJAT0BLgEmATIBSAFdAWsBcgF6AYcBjwGMAX8BbAFZAUABJAEQAQUB/QDyAOYA1QC+AKgAmACOAIcAgwB/AHcAcgBxAG4AZwBbAFQAVABTAFEAVQBhAHQAigChAL4A3AD4AA0BIgFGAXIBlwGvAbwByQHdAewB8QHyAe0B6AHoAe0B8gH2AfsBBgIMAgYC+gHwAeoB4wHbAdMB0AHQAdIB2AHfAecB6QHlAd0B1wHWAdIBwgGwAaUBoQGdAZUBkQGLAX8BdAFqAWABWQFRAUwBSQFGAUYBSQFPAVQBVAFOAUIBMgEjARIB+gDcAMIAsgCoAKYApQCjAJ0AmACZAJsAngCgAKAAnACYAJcAmQCaAJwAnQCfAKMAqgC0AL0AvgC2ALEArgCpAKwAsACzALQAsACuAK8AsACwALMAtQC0ALIAsQCzALEArACnAKcArACuAKwApgCXAIAAZQBMADkAIgAEAOn/1//G/7j/rv+o/6D/lP9+/2f/Xf9b/1z/Xv9c/1L/Sf9J/03/Tv9I/zz/Nv8+/1L/aP95/4b/jP+P/5L/lP+W/5f/lP+N/4f/hf+G/47/mv+i/6X/pP+d/5P/jP+I/4b/iP+N/5D/j/+S/5X/lf+S/4n/ef9o/1b/QP8l/wb/5/7P/sD+t/6r/p7+jP6A/nj+b/5p/mj+a/5x/nX+d/50/mr+Yf5a/lT+T/5L/kj+Q/4+/jv+Ov40/iT+Ff4F/vH92v3C/bD9qP2i/aT9r/25/br9t/22/bP9pf2R/Xz9bP1i/V/9Zv10/YT9kf2W/Zj9l/2Z/aH9q/22/b/9y/3a/ej99v0E/hL+HP4k/i3+Of5O/mT+ef6Q/qn+uv7J/tf+3/7j/uf+6v7w/vz+D/8g/zL/QP9N/1v/Z/9q/2T/XP9Y/1f/WP9a/17/Zv9y/4L/jf+T/5X/lP+Q/4n/gf96/3X/b/9p/1//UP9A/zP/Jv8Y/wj/9f7h/tD+wv6v/pn+iP55/m7+Zf5Z/kv+O/4t/ib+Jf4i/h7+Hf4d/h7+JP4y/kT+U/5e/mP+Yv5Z/k/+S/5L/kv+Qv43/i7+Kv4r/in+Kf4l/h/+Jf4v/jv+SP5O/k7+T/5Z/m7+h/6d/qv+tv7B/sn+0P7d/vH+Cv8h/z3/YP+G/6j/wP/Y/+//AQANABUAGgAfACYAMQBCAFgAbQB/AIoAkwCdAKQApgChAJ4ApwCzAMQA2ADpAPQA8gDlANMAwACvAJ4AlACMAIAAdABqAGkAcAB4AH4AfwCEAI4AmQClALUAywDgAPAAAQEXASwBOgE/AUQBTQFeAXMBhQGVAagBvAHNAdsB6QH4AQgCFQIdAiQCNAJHAlMCWgJgAmoCeQKLApgCogKwAsAC0wLmAvsCEAMZAxkDGgMaAxoDGgMbAxoDFwMZAx8DJQMzA0cDWANkA3ADfAODA4EDdQNmA1oDUANDAzUDKQMdAxIDCAP/AvwC/gIMAxwDIgMhAxsDFQMOAwYD/gL6AvoC+AL4AvwC/wIIAxEDEQMJAwIDBAMOAxwDIwMhAxsDEgMNAwcDAAP7AvQC6wLhAtgCyAKzAp4CjAJ9AnICZgJbAlACPwItAhoCBQLtAdIBtgGcAYUBcgFiAVEBQgEzASYBFQH7AOUA2wDVAMsAvQCzAKwAowCYAIoAeQBqAF4AVgBUAFoAYABlAGwAegCKAI4AhAB4AHIAcABtAGgAYgBgAF8AXwBeAFgATwBEADYAJgAYAA0ACQAEAPz/9//5//3/9//q/9z/0v/N/8X/sv+d/5H/iP99/3H/Yv9T/0L/Mv8m/x7/Gf8S/wn/+f7d/r/+pf6K/m/+Vf4//iz+Gv4I/vT93f3I/bf9rf2s/a/9s/25/cL9y/3T/dn92f3W/dr95f3t/fT9+v38/fb96P3W/cj9wf2//cT9yv3S/dr95P31/QP+Df4N/gP+9f3n/d/93f3Z/dD9wP2v/aD9j/2C/Xv9dv11/Xb9dv1z/W/9af1h/Vr9VP1M/UT9Q/1G/UL9OP0y/Tj9Q/1M/VH9T/1J/UT9Q/1E/UH9N/0q/Rv9Dv39/PD86fze/NT80vzT/NT82vzn/PP8Af0Q/SP9N/1L/Vn9Xv1i/WL9Y/1q/Xb9gv2E/Xz9dP1w/W/9a/1h/Vj9T/1K/U79X/16/Zz9w/3r/RL+Nv5a/nn+jv6e/rL+zv7z/hv/QP9f/3n/jf+e/7D/wf/Q/97/5v/r/+//7//k/9P/yP/A/7j/q/+Z/4n/eP9r/1v/TP9E/z//Of8x/y//Mf8v/yr/Iv8W/wP/7v7c/tf+2f7c/tj+0f7R/tT+3P7m/uv+5/7l/uf+6f7y/gb/Gv8v/0H/Uf9f/2n/cf93/37/hP+E/4P/g/+A/4P/kf+k/7D/sf+x/7H/s/+8/8D/uf+x/7X/xf/T/9j/2v/h/+z/9/8DABYAKwBCAGEAfwCVAKUArQC0AMQA2QDtAAEBGAEzAVYBfAGgAb8B3QH5AQ4CHQIrAjkCSAJZAmsCgQKYArECyALZAucC7gLyAvcCAwMVAyUDLQMyAzwDSANRA1sDbAN/A5IDpgO6A8gD0wPgA/MDBQQSBBsEIQQkBCMEIgQjBB4EFQQIBPYD5QPVA9AD1gPWA9ID0APPA8wDxAO4A6gDlQOCA2wDVwM/AyMDCAPzAuYC3ALVAswCvAKzArgCvQK6ArICqgKlAqUCqgKvArQCuQK5ArMCsAKuAqcCnQKbAp0CngKfAqECoAKbApUCkAKRApECiAJ5AmkCXQJSAkcCQQI+AjgCLQIZAgEC6QHPAbMBkQFuAU8BMgETAfMA1QC6AJ4AfABfAEwAPQAyACgAHAAOAPv/6f/b/8//xv/E/7//tf+s/6f/q/+t/6b/of+e/5v/mv+k/7f/zv/e/+P/5//s/+z/6P/e/9D/y//L/8f/wv+8/7T/rv+w/7f/uf+0/6z/p/+j/57/lv+O/4v/iv+G/4D/e/9z/2b/V/9H/zX/I/8W/wn//v75/vf+8v7q/tz+xf6t/pX+ev5m/lf+SP5A/j7+Qf5D/j/+OP4s/h7+Fv4P/gb+Af7+/f39+f3y/ez94f3X/dT90P3J/b39rv2h/Zn9k/2S/Zn9pf2r/av9qv2l/Z79l/2N/X39bf1f/VH9Qf0s/Rn9Df0G/f389Pzt/Ov86Pzk/N381vzV/Nv84fzh/OL84/zo/PL8/fwM/Rj9Hv0l/S/9OP07/Tn9Ov09/T39O/06/T39RP1P/Vb9VP1Q/Uz9R/1A/Tr9Ov1A/Uj9U/1e/WT9cf2G/Z/9tv3H/dP92v3l/fb9Cf4d/jD+Rf5e/nn+j/6k/rz+2P73/hL/Lv9F/13/gP+j/8L/4f///yEAQABfAHkAigCXAJ4ApgCqAKcAnwCZAJQAjwCKAIkAkACdAKsAtwDAAMcAzADSANUA0gDPANMA3gDpAPUABAESARgBFwEVARgBIAEnASsBLQEoAScBKgEvATIBLwEsASoBJAEeARkBGAEeASMBJQEiARwBHAEdAR4BJQEyAUMBVAFlAXIBdwF5AXYBbwFoAWMBYAFfAWEBawF6AYcBkAGRAZABkQGUAZsBngGdAZoBkwGTAZYBlQGVAZUBlgGUAY8BjQGYAa8BxgHXAeMB7wH6AQcCFgIjAjECPgJLAlkCaAJ3AoEChwKOApQCmAKcAqECqgK1ArwCwQLFAsMCwQLBAsACvwK4Aq4CpgKkAqECmAKKAnkCbAJlAmECYAJaAlECSgJFAkECOwIuAiACEwIGAvgB6QHbAc0BxgHJAdAB1AHTAcsBvgGuAZsBiAF5AWsBWQFBAS8BJgEoATEBOAFDAUsBTAFJAUYBRAFGAUsBTgFOAVEBXAFpAW0BbAFuAXYBfwGCAYIBfwF5AXABZQFgAV0BVwFLAUEBPQE4ATMBLAEgARUBCQH2ANsAvwCjAI8AgwB/AHkAbABfAFEAQAAtABgAAQDo/9T/w/+0/6z/qP+k/6P/qv+x/7P/r/+p/6X/of+Z/4r/ev9q/1n/R/8y/xz/Bv/w/t/+1P7N/sT+tv6r/p/+lP6K/n3+cf5l/lf+Sf41/iT+Hv4Y/g/+BP76/fP96v3c/c79xv3A/bT9p/2Y/Yz9hf2E/Yf9if2H/YD9d/1t/Wb9aP1x/YL9lf2f/Zv9j/2D/X39dv1o/Vf9Sf1A/Tr9N/04/Tf9MP0f/Qz9/Pzv/Ob83fzY/Nn83vzc/M78u/yn/JD8dvxa/D38J/wX/BD8EPwO/Az8DPwF/Pz79vv2+/r7/Pv5+/T78Pvv+/L7+Pv8+/r79Pvy+/b7+vv++wX8D/wb/Cr8O/xL/F78d/yP/KH8rfy2/L38xPzP/Nz85/zw/Pv8C/0b/SX9Kf0s/TX9Q/1W/Wb9cv1+/Yr9l/2m/bn9yv3g/f79H/5E/mj+jP6v/tD+6/4C/x3/Of9Q/2L/cv+D/5v/uv/Y/+r/8f/z//b//v8PACIANgBLAGEAdACDAJEAnQCkAKcAqACtALgAxwDTAN0A6AD4AA4BIQEyAUMBUAFaAWABZwFwAXkBgAGHAZIBpQG/AdsB9gEQAicCMwI2AjUCNAIwAioCJwIlAiMCHwIXAhECDAIJAgQC/AH2AfAB6AHqAfAB8wH3Af8BCwIWAh0CJAInAicCKAIsAjUCRAJSAloCZAJqAm4CegKIAo8CkQKRApACjwKKAoICeQJuAmcCYQJcAlkCUQJIAkMCRAJJAlMCYgJzAoAChgKLApACmQKgAqQCqQKjApcClQKbAqQCpwKqArACtAKxArUCvwLRAu0CCgMkAzcDQwNUA2oDfwOEA4IDfwN9A38DgAN8A24DXQNPA0gDRAM6Ay0DHwMWAxADCQMCA/gC7wLrAu0C8QLzAvQC8gLrAuIC2gLRAscCuQKoApoCjwKHAoECfgKHAo8CjQJ9AmMCRwItAhwCEAIGAv0B+AH4AfgB8AHkAdoB0wHNAcsBygHKAcMBtAGkAZcBjwGKAYoBkAGRAYsBggF2AWsBZgFeAVIBRAE2AS0BKQEmASABFgEJAfwA9gD0APIA7gDqAOcA4wDfANYAzQDJAMIAuQC3AL0AxADHAMYAxQDEALwAsQCnAJkAiQB1AGIAUwBDAC8AGgAGAPP/5P/U/8H/rv+c/4z/f/9y/2f/Wv9J/zP/Gf8B/+3+2f7F/rL+nv6I/nb+bP5m/l7+VP5E/jD+If4a/hb+E/4O/gf+/P3t/d790P29/ab9kf2A/XT9bP1f/U/9R/1J/VT9XP1i/Wf9bf1y/XH9a/1i/Vb9SP07/TH9K/0o/SL9GP0L/QD9/fz//AH9Cf0Q/RL9FP0b/Sr9Pv1R/WL9b/16/YT9iP2F/X39c/1s/Wr9Z/1l/WL9Wf1N/UL9P/1E/VD9Xv1t/YD9lf2m/bH9uP2//cX9yv3T/eH98P36/QL+Cf4L/hD+FP4V/hL+Cf79/fH94f3Q/cD9tP2q/aD9nv2d/Zv9mf2W/Yv9gP19/X39gf2D/YL9ff12/XL9bv1q/Wf9Yv1Z/VH9Tf1O/VD9U/1U/VL9Tv1M/VH9W/1k/W39fP2T/an9vP3P/eH98f0B/hD+HP4l/jH+Pv5M/lf+X/5j/mT+av53/or+oP6z/sX+2f7q/vn+Cv8d/zH/Qf9M/1D/Uv9Y/13/Zv9w/3X/e/+D/43/mf+j/6//u/+9/7j/r/+n/6f/r/+5/77/v/+//7//x//Z/+n/9P8DABQAIAAsADgARgBUAGQAewCWAK4AvADFANAA3wDvAPsAAgEEAQsBGwEqATMBNQE2ATcBOwFDAVEBYQFvAXoBiAGaAawBwAHNAc8ByQHEAcMBwQG8AbQBqwGjAZ4BnQGiAaYBqgGsAawBrQGwAboBzAHgAfMBAQIGAgYCBQICAgUCDQIVAhMCCgIDAv0B+AH5AfsBAAIHAg0CFQIZAhUCDwIMAgoCBAL3Ae4B7QHtAeoB6wHxAfEB7AHnAeQB3wHaAdkB3gHlAe4B+AEFAhYCIgIiAhgCCgL/AfgB9QHuAd0BzwHHAcEBvAG2AbABqwGpAakBrwG3AcIB0wHnAfoBBwINAhECEwIUAhQCFAIVAhICCwIDAvwB+AH4AfoB/wEEAgYCCAILAgwCCAICAvsB7wHhAdUBywG/Aa0BmwGLAX8BcwFlAVkBTAFEAUABOgE3ATcBNgE2ATUBMQEqASQBIQEeARgBDwH/AOoA2ADLAMAAtwCtAKMAmgCRAIkAgwB8AHIAZABZAFMASgBAADUALAAlABsADQD///P/6f/f/9f/0P/G/7v/rv+h/5T/hP90/2b/WP9K/zr/JP8L//X+5v7b/tH+yP7D/sL+wv7C/sD+vP6y/qj+of6h/qb+q/60/rr+uf6y/qj+nv6Y/pL+jf6L/ov+kP6V/pn+oP6n/qz+r/6u/rD+uf7D/sz+0P7V/tz+4/7o/un+6v7p/ub+5/7t/vL+9f73/vf+/f4G/wz/Ef8V/xn/H/8l/yv/Mv87/0T/Sf9P/1j/Y/9s/3j/hf+P/5n/pP+t/7X/v//N/9r/5//w/+//4P/I/7D/m/+M/4D/cv9k/1j/UP9L/0b/RP9C/zz/N/8z/y3/J/8g/xv/E/8F//P+3/7Q/sj+xv7H/sz+0v7Z/t3+2v7W/tH+z/7O/sz+y/7G/sL+wP6//sL+xP7H/tD+2f7g/un+8/7//gv/Fv8g/yn/Nf9G/1L/WP9a/2L/b/9//43/m/+p/7T/u/+9/7r/tv+w/63/s/+7/8H/xP/C/8L/xv/I/8v/0P/Y/+P/6//0//7/BAAMABIAFQAZACAAKgA3AEUAUwBgAG8AgACRAKAAqQCqAKYApgCsALcAxwDSANYA1gDaAOYA8QD4APwA/wAEAQUBAgH9APYA8ADqAOoA7ADpAOEA2QDTAM0AwgCyAKIAnACbAJcAkACJAIMAfwCFAJAAmgCoALcAyADdAPMABgEWASEBIAEdARoBHAEhAScBLAEwATMBNQE4AT0BQwFKAU8BVAFcAWQBbgF5AYABhAGJAY4BkwGVAZMBjAGFAX8BfgGAAX8BeAFuAWIBUgFCATkBMQEpASEBGQEOAf8A7QDaAMwAwAC6ALgAtQCzALEAsACwAK8ArQCrAKMAlgCHAHsAdQB3AH8AhgCFAIUAhwCEAIIAgAB9AHkAcABkAFgATwBQAFYAWwBkAGsAbgBrAGEAVABDADUAJwAaABQAFQAbACcAMgA3ADsAOAAtACAAFwARAAoABAD///v/+P/5//r/+v/6//L/5P/X/83/yf/K/8z/zf/O/87/zf/P/9f/3f/g/+D/2f/L/7r/qP+W/4X/dv9v/2//dP99/4P/hf+D/37/dv9s/2X/Xv9V/0j/Ov8y/zH/L/8o/yH/HP8Y/xf/F/8W/xj/GP8T/w3/B/8E/wn/Ff8g/yj/LP8u/y3/Jf8b/xL/CP8F/w3/G/8p/zb/Rf9S/17/Y/9i/2f/dP+E/5T/pf+y/7r/v/+//8D/xf/O/9X/2v/j/+z/8P/t/+L/1f/J/8D/vf+9/7//x//U/97/5//u/+n/4P/b/97/6P/v/+//7f/u//D/9P/2//X/8v/u/+r/4//d/9r/3P/g/9//1v/J/8H/v//A/8D/vf+6/73/xf/I/8T/xP/I/9H/2v/c/9z/4P/o/+v/6f/o/+j/5P/i/+P/5v/s/+3/5//j/+P/4//i/+P/5P/j/+T/5v/m/+b/4//g/9n/0f/K/8H/uv+3/7f/uP+8/7v/s/+k/5P/g/9x/1//T/9D/zb/Jf8S/wX//f74/vP+8P7u/vD+9v75/vX+7v7o/uL+3v7c/tz+3/7g/t/+1v7P/s/+1/7g/t7+0/7K/sj+xP64/q7+rP6u/qz+pf6a/oz+gv5+/n3+ff59/nz+d/5v/mb+Wf5L/kL+Ov4v/iT+Hv4e/h3+F/4M/gT+A/4H/hH+IP4v/jv+R/5U/l7+Zf5s/nD+bv5t/m/+cv51/nb+df55/oD+hP6E/oD+eP5w/m3+cf52/nz+hv6V/qb+tv7H/tb+5P7x/gH/Ef8Z/xr/HP8n/zn/S/9X/2D/af9x/3z/g/+H/43/l/+i/6r/sP+y/7L/sP+x/7T/sv+u/6z/rP+u/7T/wf/N/9L/0v/N/8f/wv+9/7v/vP/B/8f/y//J/8L/v//C/8X/w//C/8j/0f/Y/97/5f/s//f/BwAZAC4AQQBRAGEAcwCDAI0AkwCWAJkAoQCrALIAtAC3AL4AxwDNANIA1QDaAOQA7gD4AAQBDwEXARsBGAEZAR4BIQEqATkBTAFeAWoBdgGBAYoBkQGXAZ8BpwGvAbYBuQG7AcYB1AHeAeUB6QHuAfMB/AELAhwCKwI5AkwCZQJ5AoMCiAKEAn8CfgJ7AnYCbQJmAl8CVwJRAk8CTgJMAk8CWwJnAmwCbgJsAmgCZQJjAmECYQJkAmcCagJqAmACUQJDAjMCKQInAisCMQIzAi8CLQIyAjYCOgI9AkACQwJKAlECVgJXAlMCTgJMAkkCQgI0AiQCFAIIAgAC+QHuAd8B0AHGAbsBrgGeAYwBewFwAWoBaAFqAWYBWgFIATYBKAEeARUBCgH+APQA6QDeANAAuQCiAJQAjQCFAHkAaABUAD4ALQAgABEAAADv/+b/4v/e/9n/0v/N/8j/wv+9/7X/qv+f/5H/gf9y/2n/Z/9i/1n/UP9J/0T/PP8x/yj/Jf8k/yH/F/8N/wP/9v7t/u3+9/4E/wz/Ef8h/zr/U/9n/3X/f/+I/5D/nf+s/7r/yP/V/+P/+P8TADUAVgByAIgAmACqAMEA1QDiAOoA7wD0APwABwEZASwBPQFNAVcBXAFfAWEBXwFcAV8BaQFyAXUBcAFoAWEBVQFCAS4BIAEWARABDQENAREBEgEPAQYB/ADvAN0AxgCvAKEAngCdAJsAlwCPAIYAfwB0AGgAWwBPAEQANQAqACUAIQAdABoAHAAdABkAEAAAAOj/z/+8/7P/sv+w/6//sv+4/8D/v/+6/7P/q/+n/6X/pP+l/6n/sP+x/6f/mf+N/4H/df9n/1n/Tf9G/0T/R/9M/1L/U/9R/1H/UP9K/z//Nv8x/y3/J/8h/xj/C/8A//L+2/7C/q7+pf6m/qb+n/6U/oj+gP57/nj+dv50/nT+eP5//ob+kP6a/qf+s/69/sX+zf7Q/s3+yv7K/s3+0/7X/tX+0f7P/tH+1v7Z/tz+5P7w/v3+Bv8P/x3/K/83/0H/TP9V/1f/Vf9S/1L/U/9U/1j/Xf9h/2D/WP9R/0r/Rv9E/0T/Q/9D/0j/S/9M/0j/Rf9G/0X/Qf87/zX/N/8+/0b/Sv9H/0X/Rf9H/0j/Q/8z/xz/Bf/w/t7+z/7E/rv+s/6u/qn+ov6Y/pH+iv6A/nj+cv5u/m/+cv51/nX+cv5t/mL+U/5B/i7+H/4R/gH+7P3c/dT90v3S/dT90v3T/db93P3j/en98f39/Qn+Ev4X/hr+Hf4g/if+Mf4+/kj+Tv5N/kn+S/5V/mf+eP6C/o/+pP66/s3+4f7v/vz+CP8O/xD/Ff8f/y7/PP9J/1j/aP92/3//gf99/3b/cP9w/3P/c/9u/2j/Zv9j/2H/ZP9o/23/dP9+/4v/lf+e/6r/uP/E/8r/yv/G/7//uP+4/7v/wP/D/8X/yf/O/9D/zv/F/7r/sf+n/57/lv+U/5f/mv+d/6D/of+c/5P/jP+I/4T/gf96/3D/av9l/1//WP9S/07/Sf9D/0D/Qf9L/1v/av91/4D/jP+X/5//of+d/5X/if93/2P/V/9T/1b/Wf9Y/1H/Sv9H/0f/SP9G/0T/Sv9T/2D/cP+B/5b/qP+4/8P/zP/U/93/5f/m/+L/3f/a/93/5P/q//T/AAAIAAkACAAHAAYADAAWACIALQAzADYAPwBQAGMAdgCGAJcAqAC7ANEA6AABARsBMgFGAV0BcwGDAY4BlwGYAZgBngGpAbgByAHXAekB/QERAiACLwI4AjwCPwI/Aj0CPgJEAksCTgJQAlMCUgJRAlECUgJPAkYCPAIwAiQCFwIKAgMCAwIIAggCAAL0AegB3wHWAcoBuwGuAaUBogGlAaMBnAGUAYwBfgFvAWQBXAFXAVMBTgFJAUEBOQEvASMBFQEBAekA0QC9AKsAmACFAHEAXQBQAEsARQA+ADMAIwATAAkAAAD1/+n/3v/Y/9b/0f/K/8D/vf/D/83/1f/X/9X/0//R/8z/y//P/9T/2v/i/+///v8QAB8AKQAxADsAQgBLAFUAXgBpAHYAhACTAKAAqQCvALcAwADGAMUAyADVAOgA+QAAAQIBAwEFAQUBAwH/APgA7wDpAOgA5gDjAOAA4ADfANwA1gDSANMA1gDdAOUA6wDtAPEA9wD2APAA6QDoAOkA6gDpAOsA8gD4AAABDgEfATEBPwFNAVcBXAFeAWEBZQFqAW4BcAFuAWkBZAFbAVEBRgE6AS8BJgEfARkBEgENAQcBBAEFAQkBDAEGAfsA9ADsAOQA2wDQAMgAxwDGALwArQCdAI8AiQCEAH0AdQBqAFwASwA2ABsA/P/f/8j/s/+j/5r/mP+c/6P/qP+s/7H/tf+2/7X/tf+2/7j/vP/A/8f/z//Z/+P/6v/w//H/8f/w/+3/7P/r/+//9v///wkAEAAXABoAFQAKAPr/6v/d/9P/yf/B/7v/t/+1/7L/sP+t/6n/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FAAYABsAIgAsADYAQgBNAFUAWgBcAF0AXwBgAGMAZwBsAHMAewCCAIkAjQCQAJcAngCkAKoAsgC9AMkA2ADpAPcABAENAREBEQENAQoBCgEJAQgBBwEIAQwBEwEcASQBKgExATkBQAFHAU8BWAFeAWMBZgFnAWgBaQFsAXMBeQF/AYUBiQGMAY0BiwGHAYMBfwF+AX4BgAGCAYIBgAF7AXMBawFkAV8BWQFVAVABTAFIAUEBOAEtASYBIgEdARYBCwEAAfoA+QD3APAA5QDZANAAyQDDAL8AvAC5ALUArQCiAJkAkwCMAIIAegB1AHMAcQBvAG8AcgBzAGwAYQBVAEwARQBCAD8APQA6ADUAMgAyADYAOgA+AEEARABIAEoATABNAE4ATQBLAEgAQwBBAD8AOwA0ACwAIwAfACAAJgAvADgAPwBDAEgATQBUAFsAXgBfAFsAVABOAEwATABOAFMAVABQAEsARgBDAEIAQQBBAEMARwBLAEsASgBIAEcARgBDAD4ANwAyADIANgA5ADgANwA2ADYAOQA8ADsAOQA2ADIAMgA0ADkAPgBAAD4AOAA3ADcANgA1ADMAMgAzADQANgA1ADMANAAzAC4AJQAbABQADgAGAP3/9//1//L/7//u/+3/7f/u/+v/5P/e/9r/1//T/83/yP/A/7n/sv+o/6H/mP+M/4H/eP9x/2v/Zv9i/1z/U/9G/zj/LP8m/yP/If8e/xj/EP8L/wr/C/8N/w7/EP8S/xD/Df8L/wv/EP8Y/x//I/8n/yn/KP8o/yj/KP8o/yn/K/8t/y3/K/8o/yb/Jf8p/y//M/82/zj/Ov87/zz/O/84/zP/Mv8z/zP/Mf8v/y7/L/8v/zD/Mv81/zv/Rv9R/1r/ZP9v/3z/hf+J/4r/if+I/4f/iP+Q/5r/of+n/67/tf++/8f/0P/X/9v/4v/p/+//9f/5//7/AwAHAA0AFQAdACEAIwAlACQAIgAiACAAGQAQAAgAAQD7/+//4v/W/87/y//G/8H/u/+1/6z/o/+c/5j/mP+X/5j/mf+Y/5b/lf+R/4v/iv+L/43/jv+L/4f/gv99/37/hf+N/5L/lP+W/5r/nf+f/5//o/+q/7D/tv+4/7n/uv+5/7v/v//B/8T/yv/S/9r/4f/o/+3/7v/u//H/9v/8/wYAFQAkAC8ANwA8AEAAQwBIAE4A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kwCaAKEApwCtALIAtQC2ALcAuAC6AL0AvQC9AL4AvgDAAMUAzADUANwA4gDnAOkA6QDoAOgA7ADyAPcA+gD9AAABBQEKAQ8BEgESARIBEwEWARoBHQEgASQBKQEuATIBNAEyAS4BKgEmASIBHwEcARwBHwEjASYBJwEnASYBIgEdARcBEAEIAQMBAAEAAQEBAwEFAQcBBwEFAQQBBQEIAQwBDQEMAQcBAAH8AAABBQEJAQ4BFQEbASABIwEhARwBEwEJAQAB+QD0APEA8QDuAOkA4QDbANUAzgDIAMEAugCyAKoAogCZAJEAiAB8AHEAZwBeAFYATgBGAD0ANgAxAC8ALQAqACgAJwAoACkAKQApACgAJgAlACYAJwApACkAJQAeABgAEwAMAAEA8//m/9z/0v/K/8T/vv+4/7P/r/+s/6r/p/+k/6H/nf+Z/5f/mP+a/5r/mv+Y/5b/lv+W/5f/l/+X/5r/nf+f/57/nP+Y/5X/k/+T/5P/lv+b/6H/pP+m/6v/sv+3/7z/wP/E/8n/zP/O/9H/1f/Y/9v/3//g/9//3//c/9n/1//W/9f/1//X/9j/2f/Z/9X/0P/M/8f/wv+8/7b/sv+t/6j/pP+h/53/mf+W/5L/jf+H/4P/gf+A/33/ev91/23/Zf9f/1n/Uf9J/0f/R/9G/0H/Ov80/y7/J/8j/yH/IP8g/x3/Gf8V/xL/Ef8R/xP/GP8e/yT/J/8q/yz/Lf8r/yn/KP8r/zH/OP9A/0f/Tf9S/1f/XP9i/2n/b/91/3r/f/+E/4f/jP+R/5P/k/+T/5X/nP+m/7T/wf/O/9r/4//p//D/+f8CAAgADQAQABIAFAAWABgAHAAhACcAKwAuADEAMwA2ADsAPwBBAEEAQQBEAEkAUQBZAF8AZgBuAHQAeQB8AIAAgQB/AH0AewB5AHUAdAB1AHMAcABvAHIAdgB3AHgAeQB+AIEAgAB7AHMAawBoAGkAbABvAG8AbQBqAGgAZwBnAGcAZwBpAG0AdAB8AIQAigCNAIwAhwCDAIIAgwCBAHsAdwB0AG8AagBnAGkAbABsAGsAaABkAGEAXQBaAFoAWgBZAFgAWABaAF4AYwBjAGEAXgBZAFYAVQBVAFUAUgBNAEcAQgA9ADYALwApACQAHgAXABEADAAHAAIAAAD//////f/5//P/7v/r/+n/5v/h/9v/1v/Q/8f/v/+6/7b/tv+4/7j/tv+z/6//rP+s/6v/qf+q/67/tP+6/7//w//F/8P/wf/C/8b/yv/N/9H/1f/W/9X/0v/P/8z/yv/I/8X/xf/E/8P/wv/C/8P/xv/I/8n/yf/I/8j/xv/F/8P/wf/B/8D/wP/A/7//v//A/8L/xv/M/9L/1v/Y/9j/2P/Y/9j/2f/a/9z/3v/i/+b/6P/o/+f/6P/s/+7/8f/1//n//P/6//X/8f/w/+//7P/l/9z/1P/N/8b/w//B/8L/wv+//7r/s/+s/6r/qf+m/6P/nv+Y/5L/jf+J/4X/g/+C/4T/hv+F/3//ef92/3X/df91/3P/cf9y/3X/d/97/3v/eP91/2//Z/9e/1j/Vf9W/1r/YP9m/23/cv90/3b/ef98/3//gv+I/5D/l/+c/57/nv+h/6P/pf+l/6T/oP+f/6L/pf+o/6r/q/+s/6//sv+1/7f/t/+5/7//yf/U/97/5//v//X/+f/8//z/+f/0/+3/5//i/93/3P/d/93/2v/W/9T/1v/Z/9n/2//c/9r/1v/S/87/yf/F/8H/v//A/8D/v/+//7//v//B/8T/xv/J/8//1f/d/+b/8f/4//7/AwAHAAkACgALAA4AEwAZAB8AJAAqAC4AMAAyADMANAA1ADgAPABAAEUATABTAFYAVQBSAEsARABAAEEARQBKAEwATQBMAEwATwBTAFoAYQBlAGcAZwBlAGIAYABeAFwAWQBZAFsAXABfAGAAXgBWAEoAPgA0AC4AJwAhAB0AHQAgACYAKwAuADEAMgAxADAALwAwADMAOwBDAEoATwBTAFYAVgBUAFEATABLAEsASwBKAEQAPQA4ADIALQApACcAJQAlACkAMQA5AEEASABPAFQAWABZAFkAWgBdAGIAZABjAGQAaQByAHsAgwCKAJAAlACWAJkAnACfAKMApQCoAK4AtQC6ALwAvwDEAMwA0gDVANYA2ADaAN4A4QDjAOUA6QDtAPQA/gAHAQ8BEwETARIBEAEPAQ4BDAEJAQUBAwEDAQMBBgELAREBFQEYARwBIAEgAR4BHQEcARwBHAEaARgBFgETAQ4BCQEDAfwA9QDrAN8A0QDDALUApwCcAJUAkACLAIIAeABuAGQAWQBQAEoARgBBADwANwAzAC4AKQAiABwAGgAaABkAFwAWABUAFQAUABMA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Zv9o/2z/cf91/3j/e/9+/4D/gf+C/4L/g/+D/4L/g/+I/43/k/+Z/5z/nf+e/5//oP+f/5z/mf+X/5f/l/+Z/5r/mf+Z/5r/nf+f/6H/pv+t/7X/vP/D/8n/zf/N/83/0P/U/9f/2f/a/9z/4P/l/+r/7//z//n//f///////P/4//L/6v/i/9z/1v/T/9P/1v/W/9X/1f/V/9P/0P/N/8n/xf/E/8L/wP+9/7n/t/+0/7D/rf+o/6L/nP+V/5D/i/+E/37/eP9x/2r/Yv9c/1j/Vf9U/1H/Tv9L/0r/SP9F/0D/PP84/zb/Nv86/z//RP9G/0f/SP9F/z//OP80/zL/L/8s/yv/LP8u/zD/Mf8x/zH/Mf8w/y7/LP8q/yn/KP8n/yr/MP84/z7/Qf9C/0P/Rf9L/1P/W/9i/2b/af9s/2//cP9x/3L/dv94/3z/gP+F/4v/kf+W/5v/nv+k/6v/tf++/8X/y//Q/9T/1//W/9T/1f/Y/93/3//d/9v/2f/Z/9n/2v/a/9v/3P/e/93/2//b/9v/2//a/9n/2v/e/+L/4//i/+P/5v/r//H/+f8AAAMABQAKABIAGQAeACEAJQAqAC8ANgA8AEIARQBHAEgASQBLAFAAVABYAFkAWgBeAGIAZQBoAGsAbgBuAGwAZwBlAGcAawBvAHIAdQB5AH4AggCEAIUAhwCIAIcAggB9AHkAeQB9AIEAggCCAIAAfgCAAIMAhACFAIUAhwCKAI0AjwCUAJkAmgCaAJoAmwCdAKIAqQCuALIAtQC0ALEArwCwALEArwCvALAAsgC1ALkAvQDCAMUAxgDGAMUAxADGAMcAyADLAM8A0QDSANQA1gDWANUA1ADWANkA3QDfAOAA4ADhAOMA4wDhAN4A3QDcANoA2ADXANQA0QDOAMkAxQDAALsAtgC0ALYAuQC9AMEAxgDLANAA1ADXANoA2wDeAOMA5wDqAO0A8QDzAPMA8gDvAOwA6wDuAPEA8wDzAPMA9QD4APkA9wDyAO4A6gDjANsA0wDKAMIAuwCzAKsAowCaAJEAiAB9AHQAbgBpAGUAYgBgAF0AWQBTAEsAQwA8ADcANAAyADMANQA3ADgANwA0AC8AKwAoACYAIwAgAB8AHwAeABoAFgAUABMAEAALAAQA/v/8//v/+v/5//n//P8BAAUABAABAP3//v8AAAIABAAEAAIAAAD8//r/+f/5//n/9//1//P/8v/w/+//7//x//T/+v/+/wAAAAD///7///////7//f/9////AwAEAAIAAAD///7//P/6//j/9v/1//T/8v/v/+v/6P/k/+D/2//Y/9b/1P/T/9D/y//F/7//uf+0/7H/s/+3/7v/vf+9/7//wP+//7v/tv+w/6z/qv+o/6T/nv+Y/5P/kP+O/4z/if+H/4b/hP+C/37/ev91/3H/bv9s/2z/bP9q/2n/Z/9l/2T/Zf9m/2f/aP9r/27/cP9z/3T/dP91/3X/dP9x/27/av9n/2X/Y/9i/2T/av9y/3j/ev95/3z/gP+E/4f/iP+L/5D/lv+c/5//nv+d/5v/mf+Y/5n/m/+e/6P/qf+w/7b/u//A/8T/xv/K/87/0f/T/9f/3P/h/+X/6v/w//X/+P/5//n/+f/4//j/+f/6//7/AgAFAAcABwAHAAkACwAMAA0ADAAMAAwACgAJAAkACQAIAAUAAwACAAIAAQD///z//P/8//3///8BAAQABwALAA0AEAARAA8ADQAMAAsACQAHAAcABgAGAAcAAwD7//P/6//l/+D/3//h/+P/5P/j/+D/2//V/8//yP/D/8H/wP/A/77/vP+7/73/wP/A/7//vP+7/7v/u/+8/7v/uv+7/77/wP/C/8P/xP/C/8H/wP+//8D/wf/C/8X/yf/P/9X/2//i/+f/6//s/+3/7v/w//P/9f/2//j/+P/5//j/+P/3//X/8f/q/+X/4//h/+H/4//i/9//3v/e/+D/5f/q/+7/8f/y//L/8//0//b/9v/1//L/7//v/+//8//2//v///8DAAUABQAEAAQABAADAAEAAAABAAQABAADAAMAAgACAAEA///9//3/+v/3//X/9P/y//D/7v/t/+3/7P/q/+b/5P/k/+P/5P/m/+n/7f/x//P/9v/7////BAAIAAkACAAIAAoADAAQABIAFAAVABUAFgAUABIAEAAMAAcABAADAAUABgAEAP//9//v/+f/3//a/9X/0f/P/8//0P/Q/9H/z//K/8b/xf/I/8v/zP/N/8//0f/U/9f/2P/X/9T/0f/P/87/y//I/8b/xv/G/8j/y//P/9P/2P/c/9//4v/o/+7/9P/7/wIACAANABIAFgAaABsAGwAeACIAJQAlACMAJAAmACsAMQA4AD4ARQBMAFEAVgBgAGoAdAB+AIgAkQCZAKEApwCpAKoAqQCrAK4AtAC4ALoAugC4ALoAvAC/AMEAwwDDAMAAvAC4ALYAtgC2ALgAugC7ALoAtwCzALAArACnAKQAoACaAJMAigCDAH0AdgBvAGgAYgBbAFQASwBDADwANwAyACwAJgAhAB0AGgAVAA8ACgAGAAMAAQABAAAA///9//v/+f/2//L/6//m/+X/5v/m/+X/5f/l/+X/5P/g/93/2v/Y/9X/0v/S/9H/z//O/83/yv/D/7n/sf+q/6L/nP+X/5H/jf+H/4H/fP96/3v/ff9+/33/ef92/3T/c/91/3f/d/92/3X/df91/3X/dP90/3T/dP91/3X/c/9x/3H/cv90/3j/ff+A/4L/g/+C/3//ff98/33/fv+C/4f/i/+Q/5P/lv+Z/5j/lv+U/5P/k/+R/47/jf+O/5D/k/+U/5T/l/+b/53/nf+c/5v/m/+a/5r/mv+a/5n/mP+X/5b/lf+T/4//if+E/37/ev94/3j/d/92/3P/cP9r/2b/Yf9c/1f/U/9P/0z/Sf9H/0b/Q/8//zn/M/8u/yn/Jf8h/x7/HP8Y/xX/E/8Q/wr/Bf8C/wH/AP///v/+//4A/wL/Bv8N/xX/Hv8l/yz/Nf8+/0P/Rf9F/0b/SP9M/1P/Wv9h/2b/af9t/3L/dv96/37/g/+H/4v/jv+T/5j/nf+g/6P/qP+w/7j/wv/N/9f/3//o//P//v8GAAoADwAVAB4AJwAwADoAQwBOAFoAZgBwAHgAfgCDAIgAjgCTAJQAlACUAJQAlwCbAKMArAC0ALkAuwC+AMIAyADNANEA1ADWANUA1QDTANEA0QDRANIA1ADUANQA1ADUANQA1ADWANkA3ADhAOcA7ADwAPIA8wDyAPAA7ADoAOUA5ADjAOMA5ADlAOYA5wDpAOoA7ADtAO8A8gDzAPIA7gDnAOAA2ADQAMsAxgC+ALgAswCvAKsApgCjAJ8AmgCVAJAAjgCNAI8AkACQAI8AiwCJAIkAigCMAJAAkgCSAJIAlACXAJYAkwCQAI4AjQCIAIEAewB5AHsAewB7AHgAdgB2AHYAdQB1AHYAdgB1AHUAdQB1AHMAcQBwAG8AbgBrAGsAawBrAGkAZgBiAFsAVABPAEwASQBEAD0ANQAwAC4ALgArACgAJgAlACMAIQAeABsAGAAYABkAGQAYABsAIAAjACQAJAAkACYAKAAoACgAJwAnACkAKgArACoAKgArACwALwAyADQANwA6ADsAOgA6ADoAOgA6ADkANwA2ADUAMwAxAC8ALQAoACUAJAAmACUAIQAbABMAEAANAAgAAwD+//v/+P/3//T/7v/m/+D/3P/Z/9X/zv/J/8X/w//A/7//wP/D/8j/zP/P/9L/1v/Z/9v/3f/c/9r/1v/T/9D/zv/O/9H/1f/W/9X/1f/W/9r/3v/k/+z/9P/8/wIABwALAA0ADgANAAoACAAGAAMAAQAAAAEABQAIAAwADgAPAA4ADQANAA0ADAAMAA0ADQAQABEADwANAAsADAAMAAoABwAEAAMAAwADAAQABgAIAAwAEQAVABYAEwAQAA0ACgAGAAIA////////AQABAP3/+P/y/+z/6f/p/+r/6//q/+r/6P/m/+X/5P/i/9//3v/e/+D/4//k/+P/4P/c/9r/2//d/9//4//m/+b/5v/n/+n/6P/m/+P/4P/e/93/3P/d/97/3//c/9f/0f/N/8n/x//H/8b/xP/E/8T/w//E/8T/xP/E/8T/wv/A/8D/wP/D/8n/zf/P/9L/1v/Z/97/4//m/+j/5//l/+P/4//i/9//3P/Z/9f/0//N/8j/xf/D/8L/v/++/77/vf+5/7X/r/+o/6H/nP+X/5L/i/+D/33/d/9y/2z/af9o/2n/af9p/2n/aP9n/2b/Z/9p/2v/a/9r/2r/af9n/2X/ZP9l/2X/Y/9i/2H/YP9f/1//Yf9o/3H/e/+D/4j/jP+P/5H/k/+W/5n/nP+d/57/oP+j/6f/rP+y/7b/uP+6/73/v//A/8D/v/+9/7v/uv+8/8H/xf/H/8f/xf/C/8L/xv/M/9H/1f/Y/9r/3P/b/9n/1//Z/+D/5v/t//P/9//6//z//f/8//j/8v/v/+//8f/0//n//v8BAAMAAwAFAAYABAABAAAA/////////////wIABwAOABMAGQAiAC0AOQBCAEkATgBRAFUAWQBbAFsAWwBbAFoAWABWAFYAWQBfAGUAaQBtAG8AcgBzAHIAbwBrAGkAaQBqAGkAaQBpAG4AdgB7AH0AfAB7AHkAeAB4AHkAegB8AH0AfAB9AIEAhACGAIUAhACCAIEAgQB/AH4AegB2AHIAcABsAGUAXQBUAE8ASgBEAD8APAA8AD0AOwA6ADkAOQA6ADkANAAuACcAHwAYABMADwAJAAMA/f/3//L/7v/t/+v/6f/o/+j/6//v/+//7//v/+7/7P/p/+X/3//Z/9P/zf/I/8H/uv+0/7T/tf+2/7f/uf+8/7//v/+9/7z/u/+5/7j/uP+3/7b/t/+6/73/v/++/73/vf+//8P/xf/G/8b/xf/F/8b/xf/C/7z/tf+u/6j/pv+k/6P/o/+l/6X/pf+l/6P/of+f/5r/k/+N/4f/gf9+/3z/d/9z/3D/b/9u/23/bv9v/3L/c/91/3f/eP95/3v/fP99/3z/ev94/3f/df90/3H/bf9o/2P/Yv9h/2D/X/9e/13/XP9c/1z/XP9c/1//Yv9l/2n/b/91/3n/ev98/3//gf+E/4b/if+N/5T/nP+k/6v/sf+3/7v/vf/A/8P/yP/P/9b/2//f/+H/4//m/+n/6v/q/+n/5v/i/+D/3//c/9v/3P/f/+L/5P/l/+T/5P/j/+H/4P/f/97/3P/Z/9P/zv/L/8r/yP/E/8H/vv++/8D/wf/C/8L/w//G/8f/yf/K/8r/y//M/83/zf/M/8z/zf/P/9L/1//c/+H/4//m/+r/7v/z//r/AgAHAAsADwAUABgAHAAdABsAGwAcABwAHAAcAB0AHQAeACMAKgAzAD4ASgBXAGMAbQB1AHsAgACFAIoAjwCTAJQAlgCYAJ0AogClAKYApgCmAKcAqQCsAK0AqwCsAK4ArwCxALIAtAC3ALkAugC6ALsAwADGAMwA0gDYAN0A3wDeANsA1wDWANgA3ADiAOYA6QDsAO4A7gDsAOwA7QDtAO8A8wD4AP0AAgEGAQgBCAEKAQwBDQEOAQ0BDQEOAQ8BDgEJAQUBAAH8APYA7gDmAN4A2ADSAM0AxwDDAMAAvgC8ALYAsACqAKIAmgCTAI0AhwCDAH8AewB4AHQAcgBwAG0AaQBmAGUAZABiAF8AWwBZAFoAWwBbAFsAWwBcAFwAWwBZAFYAUABGADwANQAvACkAIQAZABIACwAFAAIA///6//P/6//l/+H/3//d/9r/1//X/9b/1v/V/9T/0P/J/8X/xP/F/8f/yP/J/8n/y//K/8j/xv/D/77/u/+4/7f/uv++/8D/v/+//7//wf/E/8n/zP/Q/9b/2//f/+P/5//p/+v/7P/r/+j/5v/m/+T/4v/i/+T/6P/s/+//8P/z//b/+v/+/wEAAgADAAgADwAWABsAGwAYABYAFQATABEADQAKAAcAAwABAP///v/+//3/+f/1//H/7P/n/+L/3P/V/8//yf/C/7z/t/+z/7D/rv+r/6X/nv+Y/5P/jv+L/4f/g/9//3v/d/92/3b/dv92/3L/bP9o/2P/Xf9Y/1L/TP9H/0T/Q/9E/0f/SP9H/0X/Qf88/zf/NP8y/zH/MP8t/yv/Lf8w/zL/M/8z/zP/NP81/zX/NP80/zj/O/89/z7/Pv8+/z7/Pf8+/z//P/9B/0X/Sf9L/0z/Tv9S/1X/Wf9f/2X/af9s/27/cv92/3n/e/99/3//gf+D/4X/hv+H/4v/jf+Q/5P/l/+c/6D/pf+r/7H/t/+7/77/wP/D/8j/zf/Q/9L/1P/W/9b/1v/Z/93/4P/h/+T/5//r/+//8f/z//P/9P/0//X/9//4//n//P///wMABQAGAAkADAANAA0ADQANAA0ADQALAAoACgAIAAQAAAD9//n/9f/w/+r/5P/h/97/3P/Z/9j/2P/Z/9z/3v/f/+D/4f/g/97/2//Y/9P/zv/M/83/0P/U/9X/1f/V/9T/1P/W/9v/4P/m/+z/8//6////BQAOABYAGwAeAB8AIgAmACwAMQA1ADkAPgBDAEgASgBKAEoATABPAFEAUABOAE0ATABLAEkARwBCADsANgAyADAAMAAwAC8ALQAsAC8AMQAwAC4ALwAyADMAMwAyADIANAA2ADgAOQA6ADsAPAA9AD4APgA8ADwAPQA+AD8AQABDAEkAUABUAFYAWQBcAFwAWgBXAFYAVwBYAFcAVQBUAFYAWQBbAFsAWgBaAFoAXABfAGIAYwBhAGAAYgBkAGkAcAB1AHoAfwCCAIMAhACCAIAAfgB+AH8AgQCBAIIAggCFAIcAiACHAIUAgwCEAIcAjQCTAJcAmQCbAJsAmwCZAJgAmQCbAJoAlwCVAJUAlQCWAJMAkQCQAI4AjQCLAIoAiwCLAI0AjQCMAIwAjQCMAIoAiACHAIcAiACKAI0AjwCPAI8AkQCTAJYAlgCWAJcAmACYAJgAmQCcAKAAogCiAKMApAClAKUApQClAKMAoQCfAJ4AnwChAKEAogCiAKMApQCnAKgApwCmAKMAoACeAJwAmQCVAJMAkACNAIkAhACBAIAAgQCAAH0AegB3AHUAdAB0AHUAcwBwAGkAYwBeAFoAVQBQAEsARgBCAD8APAA5ADQALgAmAB4AFgARAAwABQD///n/9P/v/+z/5//k/+P/4f/c/9T/y//C/7b/q/+h/5f/iv99/3L/aP9f/1X/TP9F/0H/PP81/y7/KP8j/yH/Hv8d/xv/F/8T/w//C/8G/wH/+/71/vH+7f7p/ub+5f7k/uP+4v7g/t7+3/7g/uL+5P7k/uX+5v7n/un+6v7s/u3+7v7w/vL+9P71/vj+/f4F/w3/E/8Y/xv/HP8d/yD/Iv8k/yb/J/8n/yr/L/82/zz/Qf9G/0v/UP9V/1v/Yf9m/2r/bv9y/3j/f/+F/4r/j/+V/5z/ov+l/6b/pf+l/6X/pf+l/6f/qv+t/6//sP+u/6r/p/+l/6T/of+d/5z/nP+d/53/n/+i/6P/o/+j/6L/of+e/5z/m/+Z/5b/kf+K/4H/eP9x/2r/Zf9g/1v/V/9U/1H/T/9O/03/TP9J/0X/QP87/zj/NP8y/zH/Mv81/zj/PP8//0H/Q/9G/0n/Sv9M/03/T/9R/1T/Vv9X/1n/XP9h/2f/a/9v/3L/df95/33/gv+F/4n/jv+U/5v/of+o/63/sv+3/7z/wf/H/83/0//Y/93/4//p/+//9////wgAEgAaACEAJwAtADIANQA4ADoAPQBCAEgAUABYAGAAZwBuAHIAdQB3AHoAfAB+AIEAgwCGAIoAjgCRAJQAlACVAJUAlgCWAJcAmQCcAJ8AoACfAJwAmQCXAJUAkwCTAJQAlgCXAJgAmgCdAKAAogCkAKUApwCqAK4AsgC2ALwAwgDJANAA1QDbAOIA6ADsAO8A8gD2APwAAgEJAQ0BDwEOAQwBCQEHAQUBBQEFAQUBBgEFAQQBAgEAAQAB/wD9APoA9gDzAO4A6gDmAOEA3ADWANEAzADGAMAAugCzAK0ApwCiAJ8AmwCVAI8AiACCAHoAcgBsAGcAZABhAF0AWQBVAFIATwBNAE0ATgBPAFIAVQBXAFkAWgBcAF4AYQBlAGcAagBtAG8AcwB4AH4AggCGAIoAjQCRAJQAlwCaAJ4AoQCkAKkArgCzALgAvAC/AMEAwgDCAMMAxQDFAMUAxgDHAMcAxwDGAMYAxgDGAMUAxADCAL8AvAC6ALgAtwC2ALgAuwC/AMMAxQDGAMQAwQC7ALMArACmAJ8AmACRAIoAhAB9AHUAbABkAF0AVQBNAEYAPwA4ADAAKQAiABsAFAALAAMA+//z/+z/5P/d/9j/0//N/8j/w/+//7v/uP+1/7H/rf+p/6X/of+d/5j/lP+S/5D/jf+L/4r/iP+I/4j/if+L/4z/jP+M/4v/i/+L/43/j/+R/5P/lP+V/5X/k/+Q/4z/h/+C/3//fv9+/33/fP97/3v/e/96/3j/dv91/3T/df91/3b/ef97/37/f/+A/4H/gf+C/4H/gP+A/4H/gv+E/4b/h/+G/4T/g/+C/4P/hf+G/4n/jP+O/5H/k/+V/5b/l/+X/5f/lv+V/5P/kf+S/5P/k/+R/47/i/+I/4X/f/94/3D/af9h/1v/Vf9R/0//Tv9M/0n/Rv9D/z//PP88/z3/Pv8+/z//P/9A/0D/QP9B/0L/Q/9E/0T/Q/9A/zz/Of81/zL/MP8x/zL/M/8y/zH/Mf8w/zH/MP8w/y//Lf8r/yn/Kf8p/yj/Jv8k/yX/Jf8l/yP/Iv8i/yL/I/8l/yn/Lv8z/zf/O/8//0L/RP9E/0P/Rf9H/0j/Sv9M/0//Uv9V/1f/Wf9a/1z/X/9i/2b/a/9w/3T/eP98/4D/hP+K/5H/mf+i/6n/sf+5/8D/yP/P/9T/2P/d/+P/6P/u//P/9//8/wEABwANABIAFwAcAB4AIAAhACQAKAAsADAAMgA0ADYAOgA+AEEARABGAEgASwBPAFMAWQBhAGgAbwB1AHkAfgCCAIUAhgCHAIYAhQCFAIYAiACKAIsAiwCLAIsAigCJAIgAhgCEAIEAfgB6AHYAcgBtAGkAYwBeAFoAVgBUAFEATgBMAEgAQwA+ADoANgAxACwAJgAiAB4AGgAXABcAGAAZABoAGgAZABgAFwAYABgAGgAbABsAHAAcABsAGgAaABkAGQAaAB0AIQAmACsALwAwADIANAA3ADoAPQA+AEAAQgBFAEgATABRAFQAVwBaAFwAXwBjAGcAbAByAHcAfACCAIgAjQCTAJkAnQCfAKIApACnAKsArwC0ALgAvADAAMUAygDOANEA1gDZANwA3gDhAOMA5QDmAOcA6QDqAOoA6wDsAOwA6wDpAOgA5gDmAOUA4wDhAOAA3wDeAN0A2gDYANcA1gDVANQA0wDSAM8AywDGAMAAuQC0AK8AqwCmAKIAngCaAJUAjwCJAIMAfgB7AHkAdwB1AHMAcQBwAG8AbABpAGUAYABbAFYAUgBNAEgARABAADwANwAzAC8AKgAkAB4AGAASAA0ACAACAPv/8//u/+v/6P/m/+T/4//i/+D/3v/c/9n/1v/S/83/yf/H/8T/wf++/7v/t/+z/7H/r/+t/6z/qv+o/6b/o/+f/5z/mf+W/5L/jv+K/4f/hf+E/4X/h/+J/4v/jf+O/5D/kv+U/5b/mP+Z/5r/nv+h/6X/qP+q/6z/rv+x/7P/tf+3/7r/vP++/8D/wP/C/8X/yf/M/9D/1P/Z/97/4f/l/+n/7P/v//L/9f/4//v//P/+//7//v/9//v/+P/1//L/7v/p/+P/3f/X/9L/zf/J/8T/v/+5/7X/sf+s/6j/ov+e/5r/l/+V/5H/jf+J/4X/gf99/3v/ef94/3b/dP9z/3H/cP9u/2z/a/9q/2n/aP9n/2f/aP9p/2v/bP9t/2//cf90/3f/ef96/3v/fP9+/3//gP+B/4P/hv+I/4n/jP+O/5H/k/+V/5j/m/+f/6P/pv+q/63/r/+x/7P/tv+6/73/wv/H/83/0v/W/9v/4P/l/+r/8P/1//n//P///wEAAwAFAAcACQAJAAgABwAHAAcABwAIAAoADgATABoAHwAlACkAKwAtAC8AMgA1ADkAPQBBAEQARwBLAE8AUgBWAFoAXgBiAGYAagBtAHAAcwB2AHgAegB7AH0AgACEAIgAjACQAJIAlACWAJcAlwCWAJUAkwCTAJIAkQCRAJEAkwCUAJYAlwCWAJYAlQCTAJAAjQCJAIUAggB/AHsAdwB0AHAAbABnAGAAWwBWAFIATgBLAEkASQBIAEcASABIAEcARgBFAEQAQgBBAD8APQA7ADoAOgA5ADcANgA0ADMAMgAyADEAMAAuAC4ALQAsACkAJwAlACQAIgAiACIAIgAiACIAIgAjACUAJQAlACYAJgAmACUAJQAmACcAKQArAC0AMAAyADUAOQA6ADsAOgA4ADUAMQAuACsAKAAlACEAHQAcABoAGQAXABUAEgAQAA4ACgAFAAEA/v/7//j/9f/y/+//7f/r/+n/5v/j/97/2f/U/87/yP/C/73/uP+z/67/q/+o/6X/ov+d/5j/kv+N/4f/gf97/3b/cP9r/2X/YP9b/1f/Uv9L/0T/Pv84/zT/MP8s/yr/Kf8n/yX/JP8j/yP/I/8j/yP/I/8j/yT/JP8k/yT/JP8j/yL/If8h/yH/Iv8l/yj/LP8v/zP/N/88/0H/Rv9J/0z/Tv9Q/1L/U/9V/1b/Wf9c/17/YP9i/2P/ZP9l/2f/af9s/2//cv92/3r/f/+C/4X/h/+J/4v/jf+P/5L/lf+X/5j/mv+c/57/oP+i/6T/p/+o/6r/rP+u/7H/sv+0/7f/uf+7/73/wP/E/8f/y//P/9P/2P/e/+T/6v/v//b//f8DAAgADQASABcAHQAiACgALQAyADYAOgA9AEEAQwBEAEYASABKAEwATQBNAEwASwBJAEkASABIAEgASABHAEYARABDAEIAQgBBAEEAQQBCAEEAPwA9ADsAOQA2ADUAMwAyADAALgAqACYAJAAhAB4AHAAbABoAGQAYABgAGAAZABsAHQAhACUAKAAtADIANgA6AD0AQABCAEQARwBLAE8AVABZAF0AYgBlAGgAagBtAHAAcwB3AHkAewB8AHwAfQB+AIAAgQCCAIQAhwCKAIwAjwCSAJUAlwCZAJsAnACcAJ0AngChAKIAowCkAKUApwCnAKcApgCmAKcApwCmAKUApQClAKUApQCjAKIAowCkAKUApQCkAKMAoQCfAJ0AmgCXAJMAkQCQAI4AjACKAIoAiQCIAIcAhQCEAIIAgAB+AHwAewB6AHkAeQB5AHgAdgB1AHMAcgBvAG0AawBpAGYAYwBjAGIAYQBfAFwAWQBVAFAATABIAEMAPwA6ADUALwArACcAIQAcABcAEgANAAgAAwD+//r/9//z//D/7f/s/+n/5v/j/+D/3f/Y/9T/z//L/8j/x//G/8T/wv/B/7//vf+8/7v/uv+5/7j/uP+3/7X/s/+x/7H/sv+y/7P/tP+2/7f/t/+2/7X/s/+y/7D/rf+q/6b/o/+g/5//nf+d/5z/m/+b/5r/mf+Y/5b/lf+U/5P/kv+R/5L/lP+W/5n/m/+d/6D/of+h/6H/ov+i/6P/pP+m/6f/qP+o/6f/pv+m/6f/p/+n/6b/pv+k/6L/n/+d/5r/mP+W/5L/jv+K/4j/hv+D/4L/gf+B/4H/gP9+/3z/e/96/3r/e/99/37/gP+C/4P/g/+D/4T/hP+E/4T/hf+F/4X/hP+E/4X/hv+I/4n/i/+M/47/kP+R/5L/k/+V/5b/l/+Y/5n/mv+a/5r/mf+Z/5n/mf+a/5v/m/+c/57/of+k/6b/qP+p/6v/rv+w/7T/uP+9/8P/yP/O/9X/3f/k/+n/7P/w//L/9P/1//b/9v/3//j/+f/5//n/+v/6//v//P/8//3/AAACAAYACgAPABQAGQAfACYALAAxADYAOgA+AEEARABGAEoATgBSAFcAXABhAGUAagBuAHMAdgB4AHoAfAB/AIIAhQCIAIoAjACOAI4AjwCQAJIAkwCUAJUAlwCYAJoAmwCbAJwAnACaAJkAlwCWAJMAkACOAIwAjACMAIoAiACDAH4AeQB1AHEAbABpAGYAYgBhAF4AWQBVAFIATwBLAEgARgBEAEIAQgBCAEIAQwBDAEMAQwBDAEMAQwBFAEcASgBMAE4AUABRAFMAVQBVAFYAVgBXAFkAWwBeAGAAYQBiAGMAZABlAGUAZgBnAGgAaQBqAG0AbwByAHQAdwB5AHwAfgCBAIQAhgCIAIoAiwCMAIwAjACNAI0AjgCQAJMAlQCWAJcAmACaAJoAmwCcAJ4AnwCgAKAAnwCeAJ0AmgCYAJUAkwCRAJAAjgCMAIsAigCJAIgAhgCFAIMAggCBAH8AfQB8AHoAeAB2AHQAcwByAHAAbgBsAGsAaABmAGQAYwBhAGAAXwBdAFsAWQBXAFMATwBLAEgARAA/ADsANwAyAC4AKwAnACQAIAAcABkAFgAUABEADwAMAAgABAAAAPv/9f/v/+j/4v/b/9T/zf/H/8L/vP+3/7P/rv+q/6X/of+d/5j/lP+P/4r/hv+C/3//fP96/3j/d/92/3b/df91/3X/c/9z/3L/cv9y/3H/cf9x/3D/b/9v/27/bf9s/2z/bf9t/2//cP9y/3T/df92/3f/eP96/3v/ff9//4D/gf+C/4L/gv+C/4L/g/+E/4b/h/+I/4j/if+J/4r/iv+K/4r/i/+M/4z/jP+L/4r/iP+H/4b/hf+E/4H/f/98/3n/d/91/3L/b/9r/2f/Y/9f/1v/WP9W/1X/VP9U/1T/U/9R/1D/Tf9L/0n/SP9H/0X/Rf9E/0T/RP9E/0P/Q/9D/0L/Qv9C/0L/Qv9C/0H/QP8//z//Pv89/z3/Pv8//0D/Qf9D/0X/R/9J/0r/TP9N/0//UP9S/1L/U/9T/1T/Vf9V/1b/WP9b/13/YP9j/2b/aP9q/23/bv9w/3H/cv9z/3T/dv94/3v/ff+A/4P/hv+J/4z/kP+U/5r/n/+j/6f/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NAAvACsAJgAkACEAIAAeABwAGgAYABYAFAATABEAEAAPAA4ADAAJAAcABQACAAAA/f/6//f/8//w/+3/6//o/+b/4//f/9z/2P/V/9H/z//N/8z/zP/L/8v/y//L/8v/yv/I/8b/xP/D/8P/wv/B/8D/wP/A/8D/wP/B/8L/w//F/8f/yv/M/87/0f/U/9f/2v/c/97/4f/j/+b/6f/r/+z/7v/w//L/8//0//b/+P/6//z//v///wAAAAABAAIAAwADAAQABAAFAAUABQAFAAYABwAHAAgACgALAAwADQAOAA4ADQAMAAwACwAMAA0ADwAPABAAEQARABIAEwAUABYAGAAaABwAHQAfACEAIwAkACUAJgAoACgAKQAqACsAKwAsAC0ALQAtAC4ALgAuAC0ALQAtACwALAArACoAKQApACkAKQApACkAKQApACkAKgAqACsALAAuADAAMgAyADMANAA0ADIAMQAvAC4ALQArACoAKAAmACUAJAAjACIAIAAfAB0AGwAZABgAFwAWABUAFAATABIAEAAOAAsACAAFAAEA///9//r/9//1//L/7//t/+n/5//k/+L/4P/f/97/2//a/9j/1v/V/9X/1P/T/9L/0v/R/8//zv/M/8v/yv/J/8j/x//H/8f/x//I/8n/yv/L/8z/zf/P/9H/0v/U/9X/1v/W/9f/2P/a/9v/3P/e/9//4f/j/+P/4//k/+T/5f/m/+f/6P/q/+v/7P/u/+7/7v/v/+//7//w//D/8f/x//L/8//z//T/9f/1//b/9v/2//X/9v/3//f/9//3//f/9//3//j/+P/4//n/+P/3//f/9f/0//T/9P/0//X/9f/1//b/9v/4//j/+P/4//j/9//2//T/8//y//L/8v/x//D/7//u/+3/7f/s/+v/7P/s/+v/6//q/+r/6f/p/+n/6f/p/+n/6f/p/+n/6f/p/+n/6f/q/+v/7P/u//D/8f/z//T/9f/1//b/9//5//v//f8BAAQABgAJAAsADAANAA4ADgAPAA8ADwAPAA8ADwAPAA8ADwAPAA8ADwAPAA8ADwAPAA8AEAARABIAFAAWABgAGgAcAB4AHwAgACAAHwAfAB4AHQAdAB0AHgAeAB0AHAAbABoAGQAZABgAFgAVABQAEgARABAADgANAAwACwAJAAgABgAFAAMAAAD+//z/+v/3//T/8v/w/+7/7P/r/+r/6v/q/+r/6v/q/+r/6v/q/+r/6//t/+7/7//v/+//7//v//D/8f/y//T/9v/3//n/+//9//7///8AAAAAAAAAAAAA///+//7//f/8//z//P/8//3//f/+//7//v/9//v/+v/5//j/+P/3//b/9f/0//T/8//z//T/9f/2//b/9//3//f/9v/3//j/+P/5//r/+v/7//v//P/9////AQADAAUACAAKAAwADgARABQAFwAbAB4AIQAkACcAKQAsAC4AMAAzADYAOAA7AD0APwBBAEMARQBHAEcASABJAEoASwBMAEwATQBOAE8AUABSAFMAVABWAFgAWgBcAF0AXwBgAGIAZABlAGcAaABpAGkAaQBoAGcAZQBjAGIAXwBdAFsAWgBZAFcAVQBUAFEATgBLAEkARwBFAEMAQQA+ADwAOQA2ADQAMQAuACwAKwAqACkAKAAnACUAJAAiACAAHwAeAB0AHAAbABoAGQAXABYAFQAVABQAEwATABIAEgARAA8ADgAMAAkABwAEAAIA///8//r/+P/2//X/8//x//H/7//v/+//7//v/+//8P/w//D/8f/y//L/8v/y//L/8f/w/+//7//v/+7/7v/u/+7/7v/u/+3/7f/u/+7/7//w//H/8f/x//H/8v/y//P/8//1//b/9//5//r//P/9//7///8BAAIAAwAEAAUABQAGAAYABQAEAAQAAwACAAEAAQABAAAAAAAAAP///v/9//3//P/8//z//P/8//3//v///wAAAQACAAMABAAEAAQABAADAAIAAAD9//r/9//0//H/7v/q/+b/4v/e/9n/1f/Q/8v/xv/C/77/u/+3/7P/sf+u/6v/qP+l/6P/oP+e/5z/m/+a/5n/mf+Z/5j/l/+W/5T/kv+Q/43/i/+I/4X/gv+A/33/ev94/3b/dP9y/3H/cP9v/27/bf9s/2v/bP9s/2z/bf9v/3D/cv91/3f/ev98/3//gf+D/4T/hv+I/4v/jv+S/5b/mf+d/6L/pv+p/63/sf+2/7r/v//E/8j/zP/Q/9T/2P/b/93/3//h/+P/5f/n/+n/6//s/+7/7//x//L/8//1//f/+f/7//3///8BAAMABQAGAAcACAAJAAoACgALAAwADQAOAA8AEQASABMAFAAWABcAGQAbAB0AHwAfACAA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1P/T/9L/0f/Q/9D/z//O/87/zf/M/8r/yf/I/8b/xf/D/8L/wv/B/7//vv++/7z/u/+6/7n/uP+3/7f/tv+1/7T/tP+z/7P/s/+y/7H/r/+u/6z/q/+p/6j/p/+l/6T/o/+i/6L/of+h/6D/n/+f/57/nv+e/57/n/+g/6H/o/+l/6f/qP+q/6z/rv+w/7P/tP+2/7j/u/+8/77/wP/C/8T/xf/H/8n/yv/L/8z/zP/N/83/zf/O/8//0P/S/9P/0//U/9X/1f/V/9b/1//Y/9n/2v/b/9z/3f/e/97/3//g/+H/4v/j/+P/5P/l/+f/6P/q/+z/7f/v//H/8//1//b/9//3//f/+P/5//r//P/9//7/AAADAAUABwAKAAwADwARABQAFgAZABsAHQAgACIAJAAlACcAKQArAC0ALgAvADAAMQAyADMAMwA0ADUANwA4ADkAOgA7ADwAPAA9AD0APQA9AD0APQA9AD4APgA+AD4APgA/AD4APgA+AD4APgA+AD8AQABBAEIAQwBFAEYARgBHAEcARwBIAEkASgBLAEwATABNAE0ATgBPAE8AUQBSAFIAUgBTAFQAVQBVAFUAVgBWAFcAVwBYAFcAVwBYAFcAVwBWAFYAVgBWAFYAVQBUAFQAUwBTAFMAUgBSAFIAUgBRAFEAUQBRAFEAUQBSAFIAUgBSAFIAUgBSAFEAUQBRAFEAUQBRAFIAUgBSAFIAUwBUAFUAVgBXAFcAVwBXAFcAVwBWAFYAVgBVAFUAVABUAFQAUwBSAFIAUQBRAFEAUQBRAFEAUABPAE4ATQBMAEsASgBJAEcARQBDAEEAQAA+AD0APAA6ADgANwA1ADMAMQAuACwAKQAmACQAIQAeABsAGAAVABMAEQAPAA0ACwAJAAgABgAEAAEA///8//n/9//1//P/8P/t/+v/6P/l/+P/4P/d/9r/1//U/9L/z//M/8n/x//G/8T/wf+//73/vP+6/7n/t/+1/7T/sv+v/63/q/+q/6j/p/+l/6P/of+f/53/m/+a/5n/mP+X/5X/lP+T/5L/kf+Q/47/jf+L/4r/iP+H/4X/hP+E/4T/hP+D/4P/gv+C/4H/f/9+/33/fP98/3v/e/97/3r/ev96/3r/ef95/3n/ef94/3j/d/93/3f/eP94/3n/ev96/3v/e/98/33/ff99/33/fv9+/3//gP+B/4L/hP+G/4j/iv+M/47/kP+S/5P/lf+X/5n/m/+d/57/oP+g/6L/o/+k/6b/p/+p/6v/rP+u/7D/sf+z/7X/t/+5/7z/vv+//8H/wv/D/8T/xf/G/8j/yP/K/8z/zf/O/9D/0f/S/9P/0//U/9T/1P/V/9X/1f/W/9b/1v/W/9f/2P/Z/9r/3P/d/9//4P/h/+H/4v/i/+P/5P/k/+X/5f/l/+b/5v/n/+j/6P/p/+r/6//t/+7/7//w//H/8v/0//X/9f/1//X/9v/3//j/+f/6//v//P/8//3//v/+////AAABAAEAAgADAAQABQAGAAcACQAKAAsADgAPABEAEgATABQAFgAXABkAGgAcAB0AHgAgACEAIgAkACUAJwAoACoAKwAtAC8AMAAyADMANAA2ADcAOAA5ADoAOwA8ADwAPAA9AD4APwBBAEMARQBGAEgASQBLAEwATgBPAFEAUgBUAFUAVwBYAFgAWQBaAFwAXQBeAF8AXwBfAF8AXwBeAF4AXQBcAFsAWgBaAFkAWQBZAFgAWABYAFcAVwBXAFYAVQBVAFQAUwBSAFEAUABQAE8ATgBNAEwASwBKAEoASQBIAEgARwBHAEYARgBFAEQAQwBCAEEAQQBAAEAAQABAAD8APwA+AD4APQA9ADwAPAA7ADsAPAA9AD4APwBAAEEAQgBDAEQARQBGAEcARwBIAEkASgBLAEsATABMAE0ATQBNAE0ATQBNAE0ATgBOAE4ATwBPAFAAUABPAE8ATwBOAE0ATABLAEoASQBHAEYARQBDAEIAQQBAAD8APgA9AD0APAA7ADoAOAA3ADcANgA2ADUANAA0ADMAMgAxAC8ALQAsACsAKgAqACoAKQAoACcAJgAlACMAIgAgAB4AHAAaABgAFgAUABIAEAAOAAwACgAJAAcABgAFAAUABAADAAEA///9//v/+f/4//f/9f/z//H/7v/r/+j/5v/j/+D/3f/a/9j/1f/T/9H/zv/M/8r/yP/H/8X/xP/D/8L/wP+//77/vf+7/7r/uf+4/7f/tf+0/7L/sf+w/6//r/+t/6z/rP+r/6v/qv+q/6r/qv+q/6r/qv+q/6n/qf+o/6j/p/+n/6j/qP+o/6n/qf+p/6n/qf+p/6r/qv+r/63/rv+v/7D/sf+z/7T/tf+3/7n/uv+9/7//wf/D/8X/x//J/8v/zf/Q/9P/1f/X/9n/2//d/9//4P/i/+T/5v/o/+r/7P/t/+7/8P/y//T/9v/5//v//f///wEAAgAEAAUABwAIAAkACQAKAAoACgALAAsACgAJAAgACAAHAAYABQAFAAMAAQAAAP7//f/7//n/+P/3//b/9f/0//P/8f/w/+//7v/s/+r/6f/o/+f/5f/k/+L/4P/f/97/3f/d/93/3f/d/93/3f/d/9z/3P/b/9r/2f/Y/9f/1//X/9b/1v/W/9b/1v/W/9b/1//Y/9n/2v/b/9z/3v/f/+H/4//l/+b/6P/q/+z/7//x//P/9v/4//r//P/+/wAAAwAFAAgACgAMAA4AEAARABIAEwATABQAFAAUABUAFQAWABYAFwAXABcAFwAXABcAFgAWABYAFQATABIAEQAPAA4ADAALAAoACgAJAAgACAAIAAcABwAGAAYABgAGAAYABgAGAAYABgAGAAcABwAIAAkACgALAAwADQAOAA8AEAASABIAFAAUABUAFQAVABYAFgAWABYAFgAXABcAFwAYABgAGAAZABkAGQAZABgAGAAYABgAFwAXABYAFQAUABMAEgARABAADwAOAA0ADAALAAkACQAIAAcABgAGAAUABQAFAAYABwAHAAgACAAIAAgACAAIAAkACgALAAwADQANAA4ADwAPAA8ADgAOAA0ADQANAAwADAAMAAsACwALAAsACwAMAA0ADQAOAA8AEAARABIAEwAUABUAFgAXABkAGgAbABwAHgAfAB8AIAAhACIAIwAjACQAJgAmACcAKAApACkAKQAqACoAKwArACwALQAtAC0ALgAuAC0ALQAtAC0ALQAtAC0ALQAtAC0ALQAtAC0ALgAvAC8AMAAwADAAMQAxADEAMQAxADIAMgAyADIAMwAzADIAMgAyADIAMwAzADMAMwAyADIAMgAxADAAMAAvAC4ALQAsACsAKgAqACoAKgApACkAKgAqACkAKQApACkAKAAoACgAKAAnACcAJwAmACYAJgAlACUAJQAkACQAIwAiACEAIAAfAB8AHgAdABsAGgAZABcAFgAWABUAEwASABAADgAMAAoACQAGAAUAAwACAAAA///+//3/+//5//f/9f/z//D/7v/s/+r/6f/n/+X/5P/j/+L/4f/g/97/3P/a/9n/1//W/9X/1P/T/9L/0v/R/9D/0P/Q/9D/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7v/v//D/8f/x//H/8v/y//P/9P/1//b/9//3//j/+f/5//r/+//7//z//P/8//3//f/9//7///8AAAAAAQABAAIAAgACAAMAAwAEAAQABQAGAAYABgAHAAcABwAIAAgACAAIAAgACAAIAAcABwAHAAcABwAHAAYABgAFAAUABQAFAAQABAAEAAQABAAEAAQABAADAAMAAwADAAMAAwAEAAQABAAFAAUABgAGAAYABgAGAAcABwAHAAcACAAIAAkACQAKAAoACwAMAAwADQAOAA4ADwAPABAAEAARABIAEgATABQAFQAWABcAGAAZABoAGwAdAB0AHgAfAB8AIAAhACEAIgAjACMAJAAlACUAJQAmACYAJgAnACcAJwAnACgAKAAoACkAKQApACoAKgAqACoAKQApACkAKQApACgAKAAoACgAJwAmACYAJQAkACMAIwAiACEAIAAgAB8AHwAeAB4AHgAdAB0AHAAbABoAGQAXABYAFQATABIAEQAQAA4ADAAKAAgABgAEAAIA///9//v/+f/3//X/8//y//D/7v/t/+v/6v/p/+j/5//n/+b/5v/l/+X/5f/l/+T/5P/j/+L/4f/h/+D/3//f/9//3//f/+D/4P/h/+H/4f/i/+P/4//k/+T/5f/l/+b/5//o/+n/6v/r/+z/7P/t/+7/7//w//L/8//0//X/9v/4//n/+v/7//3//v///wAAAQACAAMABAAFAAYACAAJAAoADAANAA4AEAAQABEAEgATABMAFAAVABYAFwAYABkAGgAaABoAGwAbABsAGwAbABsAGwAaABoAGgAZABkAGAAYABcAFgAVABQAEwASABEAEAAPAA0ADAALAAkACAAHAAUABAACAAEAAAD///7//f/8//v/+f/4//f/9v/1//T/8v/x/+//7v/s/+r/6P/n/+b/5f/j/+L/4f/g/9//3v/d/93/3P/c/9v/2//b/9r/2v/a/9r/2v/Z/9n/2f/Y/9j/2P/Y/9j/2f/Z/9n/2f/Z/9r/2v/a/9n/2f/Z/9n/2f/a/9r/2//c/9z/3f/e/9//4P/g/+D/4f/i/+L/4//k/+X/5v/n/+j/6f/q/+v/7P/t/+7/7v/v//D/8f/y//P/9P/1//b/9//4//n/+v/7//z//f/9//7//v/////////////////+//7//f/9//z/+//7//r/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BwAIAAoACwANAA8AEQASABQAFgAYABkAGwAdAB4AIAAiACMAJQAnACgAKgArAC0ALgAvADEAMgAzADUANgA4ADkAOgA7ADwAPgA/AEAAQQBCAEMARABEAEUARgBGAEcARwBIAEgASQBKAEoASwBLAEsATABMAE0ATQBNAE4ATgBPAE8ATwBQAFAAUQBRAFIAUgBSAFMAUwBUAFQAVABUAFUAVQBVAFUAVQBUAFQAVABUAFQAUwBTAFIAUgBRAFEAUABQAE8ATgBNAEwASwBKAEkASABHAEUARABDAEEAQAA+AD0AOwA5ADgANgA0ADMAMQAvAC0ALAAqACkAJwAlACQAIgAhAB8AHgAcABoAGAAWABUAEwARAA8ADQAMAAoACAAGAAQAAwABAP///f/8//r/+P/3//X/8//y//D/7v/s/+v/6f/o/+f/5f/k/+P/4//i/+H/4P/f/97/3v/d/93/3P/c/9z/3P/c/9z/3P/c/9z/3P/c/9z/3P/c/9z/3P/d/93/3v/e/97/3//f/+D/4P/h/+H/4v/i/+P/5P/k/+X/5v/n/+j/6f/q/+v/7P/t/+7/8P/x//L/8//1//b/9//4//n/+//8//z//f/+//////8AAAEAAQACAAIAAwADAAMAAwADAAQABAAEAAQAAwADAAMAAwADAAIAAgACAAEAAQAAAP/////+//3//P/8//v/+v/5//n/+P/3//b/9f/0//P/8v/x//D/7v/t/+z/6//q/+j/5//m/+X/5P/j/+L/4P/f/97/3f/c/9v/2v/Z/9j/1//X/9b/1f/V/9X/1P/U/9T/1P/T/9P/0//T/9P/0//S/9L/0v/S/9L/0v/S/9L/0//T/9P/0//T/9T/1P/U/9T/1P/V/9X/1v/W/9b/1//X/9j/2P/Y/9n/2f/a/9r/2//b/9z/3P/d/93/3v/f/+D/4f/i/+P/5P/m/+f/6P/q/+v/7f/v//D/8f/z//T/9v/3//j/+f/6//v//f/+////AAABAAIAAwAEAAUABgAHAAkACgALAA0ADgAQABEAEwAUABUAFgAYABkAGgAbABsAHAAdAB4AHwAgACAAIQAiACMAIwAkACQAJQAmACYAJwAnACgAKAApACkAKQAqACoAKgAqACsAKwArACsAKwArACwALAAsACwALQAtAC0ALQAtAC0ALQAtAC0ALQAtACwALAAsACwAKwArACsAKwAqACoAKgAqACkAKQApACkAKQAoACgAKAAoACgAKAAoACgAKAAoACcAJwAnACcAJgAmACYAJQAlACQAJAAkACMAIwAjACMAIwAiACIAIgAiACIAIgAiACIAIgAiACIAIgAiACMAIwAjACMAIwAkACQAJAAkACQAJAAlACUAJQAlACUAJQAlACUAJQAkACQAJAAkACMAIwAiACIAIQAgACAAHwAeAB0AHAAcABsAGwAaABoAGgAZABkAGAAYABcAFgAWABYAFQAVABQAFAATABMAEgASABEAEAAQAA8ADwAOAA4ADQAMAAwACwAKAAoACQAIAAgABwAGAAYABQAEAAQAAwACAAEAAQAAAP///v/9//z/+//6//n/+P/3//b/9f/0//T/8//y//H/8f/x//D/8P/v/+//7//u/+7/7v/t/+3/7f/s/+z/7P/s/+v/6//r/+r/6v/q/+n/6f/o/+j/5//n/+b/5v/m/+X/5f/l/+T/5P/k/+T/4//j/+P/4//i/+L/4v/h/+H/4f/g/+D/4P/f/97/3v/d/93/3P/c/9v/2v/a/9n/2P/Y/9f/1v/V/9X/1P/U/9P/0//S/9L/0f/R/9D/0P/P/8//z//O/87/zv/N/83/zf/N/83/zP/M/8z/zP/M/8z/zP/M/8z/zP/L/8v/zP/M/8z/zP/M/8z/zP/M/8z/zP/M/8z/zP/M/8z/zP/N/83/zf/N/83/zv/O/87/z//P/9D/0P/Q/9H/0f/S/9L/0//T/9P/1P/U/9T/1f/V/9X/1v/W/9f/1//Y/9j/2f/Z/9r/2v/b/9v/2//c/93/3f/e/9//3//g/+H/4v/j/+P/5P/l/+b/5//n/+j/6f/q/+v/7P/t/+7/7//w//L/8//0//X/9v/3//n/+v/7//3//v8AAAEAAwAEAAYABwAIAAoACwAMAA0ADgAQABEAEgATABMAFAAVABYAFgAXABcAGAAZABoAGwAbABwAHQAeAB8AHwAgACEAIgAiACMAIwAkACUAJQAmACYAJwAoACgAKQApACoAKgArACsALAAsAC0ALQAtAC4ALgAvAC8ALwAvADAAMAAwADEAMQAxADEAMQAxADEAMQAxADEAMQAxADEAMQAxADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMQAxADEAMQAxADEAMQAyADIAMgAyADIAMgAyADIAMgAyADEAMQAxADIAMgAyADIAMgAyADIAMgAyADIAMgAyADIAMgAyADEAMQAxADEAMAAwAC8ALwAvAC4ALgAtAC0ALAAsACsAKwAqACoAKQApACgAJwAnACYAJQAkACQAIwAiACEAIAAfAB4AHgAdABwAGwAaABkAGAAXABcAFgAVABQAEwASABEAEAAPAA0ADAALAAoACQAIAAcABQAEAAMAAgAAAP///v/8//v/+f/4//b/9f/0//L/8f/w/+//7v/t/+z/7P/r/+r/6f/p/+j/5//n/+b/5v/l/+T/5P/j/+L/4v/h/+H/4P/f/9//3v/e/93/3f/d/9z/3P/b/9v/2//a/9r/2v/Z/9n/2f/Z/9n/2f/Z/9n/2f/a/9r/2v/b/9v/2//c/9z/3P/d/93/3f/d/93/3v/e/97/3v/e/97/3v/e/97/3v/e/93/3f/c/9z/2//b/9r/2f/Z/9j/1//W/9b/1f/U/9P/0v/R/9D/0P/P/87/zf/M/8z/y//K/8r/yf/J/8j/x//H/8b/xv/F/8X/xf/E/8T/xP/E/8T/xP/E/8P/w//D/8P/w//E/8T/xP/E/8T/xf/F/8X/xf/G/8b/xv/G/8f/x//I/8j/yf/J/8r/y//L/8z/zf/O/8//0P/R/9L/0//U/9X/1v/X/9j/2P/Z/9r/2//b/9z/3f/e/97/3//f/+D/4P/h/+H/4v/i/+L/4//j/+T/5P/l/+b/5v/n/+j/6f/p/+r/6//r/+z/7f/u/+//8P/x//L/8v/z//T/9f/2//f/+P/4//n/+v/7//z//f/+////AAABAAIAAwAEAAUABQAGAAcACAAJAAoACwAMAA0ADgAPABAAEQASABMAFAAVABYAFwAYABgAGQAaABsAHAAcAB0AHgAfACAAIAAhACEAIgAiACMAIwAkACQAJQAlACYAJgAmACcAJwAnACgAKAAoACkAKQApACkAKQAqACoAKgAqACsAKwArACsAKwArACsALAAsACwALAAsAC0ALQAtAC0ALQAtAC0ALgAuAC4ALgAvAC8ALwAvAC8AMAAwADAAMAAwADEAMQAxADEAMgAyADIAMwAzADMANAA0ADQANQA1ADUANQA1ADUANQA2ADYANgA2ADYANwA3ADcANwA4ADgAOQA5ADkAOgA6ADsAOwA8ADwAPQA9AD4APgA+AD4APgA+AD4APgA+AD4APgA+AD4APQA9AD0APQA9AD0APQA9AD0APQA9AD0APQA8ADwAPAA8ADsAOwA7ADoAOgA5ADkAOAA4ADcANwA2ADUANQA0ADMAMwAyADEAMAAvAC4ALQAtACwAKwAqACkAKAAoACcAJgAlACQAIwAiACEAIAAfAB4AHQAcABoAGQAYABcAFgAVABQAEwASABEAEAAPAA4ADQAMAAsACgAJAAgABwAGAAQAAwACAAEAAAD///7//f/8//v/+v/5//j/9v/1//T/8//x//D/7//u/+z/6//q/+j/5//m/+X/4//i/+H/4P/f/93/3P/b/9r/2P/X/9b/1f/T/9L/0f/Q/8//zf/M/8v/yf/I/8f/xf/E/8P/wv/A/7//vv+9/7z/u/+6/7n/uP+3/7b/tf+0/7T/s/+y/7L/sf+x/7D/sP+w/7D/sP+v/6//r/+v/6//r/+v/6//r/+w/7D/sP+w/7D/sf+x/7H/sf+x/7L/sv+y/7L/s/+z/7T/tP+0/7X/tf+2/7b/tv+2/7b/t/+3/7f/t/+3/7f/t/+4/7j/uP+5/7n/uf+5/7r/uv+7/7v/vP+8/73/vv++/7//wP/B/8H/wv/D/8T/xf/G/8f/yP/K/8v/zf/O/9D/0f/T/9T/1v/X/9n/2v/c/93/3v/g/+H/4//k/+X/5//o/+n/6v/r/+z/7f/u/+//8P/x//L/8v/z//P/9P/1//X/9v/2//f/9//4//j/+f/6//r/+//7//z//P/8//3//f/9//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v//////////////AAAAAAAAAQABAAIAAgADAAMABAAFAAYABwAHAAgACgALAAwADQAOAA8AEQASABMAFQAWABgAGQAaABwAHQAeAB8AIQAiACMAJAAmACcAKAApACoAKwAsAC0ALgAvAC8AMAAxADIAMwA0ADUANgA4ADkAOgA7ADwAPQA+AD8AQABBAEIAQwBEAEUARgBHAEgASQBKAEsATABNAE4ATwBPAFAAUQBSAFIAUwBTAFQAVABUAFUAVQBVAFUAVgBWAFYAVgBWAFYAVgBWAFYAVgBWAFUAVQBVAFUAVQBUAFQAVABUAFMAUwBSAFIAUQBQAE8ATwBOAE0ATABLAEoASQBIAEcARgBFAEQAQwBCAEEAQAA+AD0APAA7ADoAOQA4ADcANgA1ADQAMwAxADAALwAtACwAKwApACgAJgAlACMAIgAhAB8AHgAcABoAGQAXABUAFAASABAADwANAAwACgAJAAcABgAEAAMAAQAAAP7//f/7//r/+P/3//b/9P/z//L/8P/v/+7/7f/s/+v/6v/p/+j/5//m/+X/5P/j/+L/4v/h/+D/3//e/97/3f/c/9v/2//a/9r/2f/Y/9j/1//X/9b/1v/V/9X/1P/U/9P/0//T/9P/0v/S/9L/0v/S/9H/0f/R/9H/0f/R/9H/0f/R/9D/0P/Q/9D/0P/Q/9D/z//P/8//z//P/8//z//P/8//z//P/8//z//P/8//z//Q/9D/0P/Q/9D/0P/Q/9D/0f/R/9H/0f/R/9H/0v/S/9L/0v/S/9L/0v/S/9L/0v/S/9L/0//T/9P/0//T/9T/1P/U/9T/1f/V/9X/1v/W/9b/1//X/9f/2P/Y/9n/2f/a/9r/2v/b/9v/2//c/9z/3f/d/97/3v/f/9//4P/g/+H/4f/i/+L/4//j/+P/5P/k/+X/5f/m/+b/5//n/+j/6P/p/+n/6v/r/+v/7P/t/+7/7v/v//D/8f/x//L/8//0//X/9v/3//j/+f/6//v//P/9//7///8AAAEAAgADAAQABQAGAAgACQAKAAsADAANAA4ADwAQABEAEgATABQAFQAWABcAGAAZABoAGgAbABwAHAAdAB4AHwAfACAAIQAiACIAIwAkACQAJQAmACYAJwAnACgAKQApACoAKwArACwALQAtAC4ALwAwADAAMQAyADIAMwA0ADQANQA1ADYANgA3ADcAOAA4ADkAOQA5ADoAOgA6ADsAOwA7ADwAPAA8ADwAPAA8ADwAPAA8ADwAPAA7ADsAOwA7ADoAOgA6ADkAOQA5ADgANwA3ADYANgA1ADQAMwAyADIAMQAwAC4ALQAsACsAKgApACgAJwAmACQAIwAiACEAIAAeAB0AHAAbABoAGQAXABYAFQAUABMAEgARABAADwAOAA0ADAALAAsACgAJAAgACAAHAAYABQAEAAMAAwACAAEAAAD//////v/9//z/+//7//r/+f/5//j/9//3//b/9f/1//T/9P/z//P/8v/y//L/8f/x//H/8f/x//D/8P/w//D/8P/v/+//7//v/+7/7v/u/+3/7f/s/+z/6//q/+r/6f/p/+j/5//n/+b/5f/k/+P/4v/h/+H/4P/f/97/3f/c/9v/2v/Y/9f/1v/V/9P/0v/R/9D/zv/N/8z/y//K/8n/yP/H/8b/xf/E/8P/wv/C/8H/wP+//77/vv+9/73/vP+8/7z/vP+7/7v/u/+7/7v/u/+7/7v/vP+8/7z/vf+9/77/vv++/7//v//A/8D/wP/B/8H/wv/C/8P/w//E/8T/xf/F/8b/x//H/8j/yP/J/8r/yv/L/8v/zP/M/83/zf/O/87/z//Q/9D/0f/S/9P/1P/U/9X/1v/X/9j/2f/a/9z/3f/d/97/3//g/+H/4v/j/+T/5f/m/+b/5//o/+n/6v/r/+z/7f/u/+7/7//w//H/8v/z//T/9f/1//b/9//3//j/+f/5//r/+//7//z//f/+//7//////wAAAQABAAIAAgADAAMABAAEAAUABQAGAAYABwAHAAgACAAIAAkACQAKAAoACgALAAwADAANAA0ADgAPAA8AEAARABIAEwAUABUAFgAXABgAGQAaABsAHAAdAB4AHwAgACIAIwAkACUAJgAoACkAKgArAC0ALgAvADAAMQAyADMANAA1ADYANwA4ADkAOgA7ADwAPQA+AD8AQABBAEEAQgBDAEQARABFAEYARgBHAEgASQBJAEoASgBLAEsASwBMAEwATQBNAE0ATQBOAE4ATgBOAE4ATgBOAE4ATgBOAE0ATQBNAE0ATABMAEwASwBLAEoASgBJAEkASABHAEYARgBFAEQAQwBCAEEAQAA+AD0APAA7ADoAOQA4ADYANQA0ADMAMQAwAC8ALQAsACsAKgApACcAJgAlACQAIwAiACEAIAAfAB4AHQAdABwAGwAaABkAGAAYABcAFgAWABUAFAAUABMAEwASABIAEQARABAAEAAQAA8ADwAOAA4ADgANAA0ADAAMAAwACwALAAoACgAJAAkACAAHAAcABgAGAAUABQAEAAQAAwACAAIAAQAAAAAA///+//3//P/7//r/+f/4//f/9//2//X/9P/0//P/8v/y//H/8P/w/+//7//u/+7/7v/t/+3/7P/s/+v/6//q/+r/6f/o/+j/5//m/+b/5f/k/+P/4//i/+H/4P/f/9//3v/d/9z/2//a/9n/2P/X/9b/1f/U/9P/0//S/9H/0P/Q/8//zv/N/83/zP/L/8r/yv/J/8n/yP/I/8f/x//G/8b/xv/F/8X/xf/F/8X/xf/F/8X/xv/G/8b/xv/H/8f/x//I/8j/yf/J/8r/yv/L/8v/y//M/8z/zf/O/87/z//Q/9D/0f/S/9P/1P/V/9b/1//Y/9n/2v/b/9z/3f/e/9//4P/h/+L/4//k/+X/5f/m/+f/6P/p/+n/6v/r/+z/7P/t/+7/7//v//D/8f/x//L/8//z//T/9f/1//b/9v/2//b/9v/3//f/9//3//f/9//3//f/9//4//j/+P/4//j/9//3//f/9//3//f/9//2//b/9v/2//b/9v/2//X/9f/1//X/9f/1//T/9P/0//T/8//z//P/8//z//P/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8//z//P/8//0//T/9f/1//b/9//3//j/+f/5//r/+//8//z//f/+////AAABAAIAAwAEAAUABgAHAAgACQAKAAsADAAOAA8AEAARABMAFAAVABcAGAAZABoAGwAcAB4AHwAgACAAIQAiACMAJAAkACUAJQAmACYAJwAnACgAKAAoACgAKAAoACgAKAAoACcAJwAnACYAJgAlACUAJQAkACQAIwAjACMAIgAiACIAIQAhACEAIAAgAB8AHgAeAB0AHAAbABsAGgAZABkAGAAXABcAFgAWABUAFAAUABMAEgASABEAEAAQAA8ADgAOAA0ADQAMAAsACwAKAAoACgAJAAkACQAIAAgACAAIAAcABwAHAAcABgAGAAYABQAFAAUABAAEAAQAAwADAAMAAwACAAIAAgACAAIAAQABAAEAAQABAAEAAAAAAAAAAAAAAAAAAAAAAAAA/////////////////v/+//7//v////////////////8AAAAAAAABAAEAAQACAAIAAwAEAAQABAAFAAYABgAHAAcACAAJAAkACgAKAAsADAAMAA0ADQAOAA8ADwAQABEAEQASABIAEwATABQAFAAVABUAFgAWABYAFwAXABgAGAAYABgAGQAZABkAGQAZABkAGQAZABkAGQAZABkAGQAZABkAGQAYABgAGAAXABcAFwAXABYAFgAWABUAFQAUABQAFAATABMAEgARABEAEAAQAA8ADgAOAA0ADQAMAAsACwAKAAkACQAIAAgABwAGAAYABQAEAAQAAwADAAIAAgABAAEAAQAAAAAAAAD//////////////v/+//7//v/+//7//v/+//////////////////////////////8AAAAAAAAAAAAAAAAAAAEAAQABAAEAAQABAAEAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAMAAwADAAMAAwAEAAQABAAEAAQABQAFAAUABQAFAAUABAAEAAQABAAEAAQABAAEAAQABAADAAMAAwADAAMAAgACAAIAAQABAAAAAAD//////v/+//3//P/7//v/+v/5//j/9//3//b/9f/0//P/8v/x//D/7//u/+3/7P/r/+r/6f/o/+f/5f/k/+P/4v/h/+D/3//e/93/3P/b/9r/2f/Z/9j/1//W/9b/1f/V/9T/1P/T/9P/0v/S/9H/0f/R/9D/0P/P/8//zv/O/87/zf/N/83/zP/M/8v/y//K/8r/yv/J/8n/yf/J/8n/yf/J/8n/yf/J/8n/yv/K/8v/y//M/83/zf/O/8//z//Q/9D/0f/S/9L/0//U/9X/1f/W/9f/2P/Y/9n/2v/b/9v/3P/d/97/3v/f/+D/4f/h/+L/4//j/+T/5P/l/+b/5v/n/+j/6P/p/+r/6v/r/+z/7P/t/+3/7v/v/+//8P/w//D/8f/x//L/8v/y//L/8//z//P/8//0//T/9P/1//X/9f/2//b/9v/3//f/9//3//j/+P/4//j/+f/5//n/+v/6//v/+//8//z//f/9//7//////wAAAAABAAIAAgADAAMABAAFAAUABgAHAAcACAAJAAkACgALAAwADAANAA4ADgAPABAAEAARABEAEgATABMAFAAUABUAFQAVABYAFgAXABcAGAAYABkAGQAZABoAGgAaABsAGwAbABwAHAAcABwAHAAcABwAHAAcABwAHAAcABwAGwAbABsAGwAaABoAGgAZABkAGQAZABgAGAAYABgAGAAXABcAFwAWABYAFgAVABUAFQAUABQAFAAUABMAEwATABMAEgASABIAEgARABEAEQARABEAEAAQABAAEAAPAA8ADwAPAA8ADwAPAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAPAA8ADwAPAA8ADwAPAA8AEAAQABAAEAARABEAEQASABIAEgATABMAEwAUABQAFAAVABUAFQAWABYAFgAWABcAFwAXABcAFwAXABcAFwAXABcAFwAXABcAFgAWABYAFgAWABYAFQAVABUAFAAUABQAEwATABMAEgASABEAEQAQABAAEAAPAA8ADgAOAA4ADQANAA0ADAAMAAwACwALAAsACgAKAAkACQAIAAgABwAHAAYABgAFAAQABAADAAIAAQABAAAA///+//7//f/9//z//P/7//v/+v/6//n/+f/5//j/+P/4//j/+P/3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/+P/4//j/+P/5//n/+f/6//r/+//7//z//P/9//3//v//////AAAAAAEAAQACAAIAAwADAAQABAAFAAYABgAHAAcACAAIAAkACgAKAAsACwAMAAwADAANAA0ADgAOAA4ADgAOAA8ADwAPAA8ADwAPAA8ADwAOAA4ADgAOAA4ADQANAA0ADQAMAAwADAALAAsACwAKAAoACgAJAAkACQAJAAgACAAIAAcABwAGAAYABgAFAAUABQAEAAQABAADAAMAAwACAAIAAgABAAEAAQAAAAAAAAD///////////7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+////////////AAAAAAAAAAAAAAEAAQABAAIAAgACAAMAAwADAAQABAAEAAUABQAFAAYABgAHAAcABwAIAAgACQAJAAoACgALAAsADAANAA0ADgAPAA8AEAAQABEAEQASABIAEwATABMAFAAUABQAFQAVABUAFgAWABYAFgAWABYAFwAXABcAFwAXABYAFgAWABYAFQAVABUAFAAUABMAEwASABIAEQARABAAEAAPAA4ADQANAAwACwAKAAkACAAHAAYABQAEAAMAAgABAAAA/v/9//z/+//6//n/9//2//X/9P/z//L/8v/x//D/7//v/+7/7f/t/+z/7P/r/+v/6//q/+r/6v/p/+n/6f/p/+j/6P/o/+f/5//n/+f/5//m/+b/5v/m/+b/5v/m/+b/5f/l/+X/5v/m/+b/5v/m/+b/5v/m/+b/5//n/+f/5//o/+j/6P/o/+j/6P/o/+j/6f/p/+n/6f/p/+n/6f/p/+n/6f/o/+j/6P/o/+j/6P/o/+j/5//n/+f/5//m/+b/5v/m/+X/5f/l/+X/5f/k/+T/5P/k/+T/5P/j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4v/i/+L/4v/i/+L/4v/i/+L/4v/i/+L/4v/i/+L/4v/i/+L/4v/i/+L/4//j/+P/4//j/+P/4//j/+T/5P/k/+T/5P/k/+T/5f/l/+X/5f/m/+b/5v/n/+f/5//o/+j/6f/p/+n/6v/q/+v/6//s/+3/7f/u/+7/7//v//D/8P/x//L/8v/z//T/9P/1//b/9v/3//f/+P/5//n/+v/6//v/+//8//z//f/9//7//v//////AAAAAAEAAQABAAIAAgADAAMAAwAEAAQABQAFAAYABgAHAAcACAAIAAkACQAKAAoACwALAAwADAANAA0ADQAOAA4ADwAPABAAEAARABEAEgASABIAEwATABMAFAAUABUAFQAVABYAFgAWABcAFwAYABgAGAAZABkAGgAaABoAGwAbABsAGwAbABwAHAAcABwAHAAcAB0AHQAdAB0AHQAdAB0AHQAdAB0AHQAdAB4AHgAeAB4AHgAeAB4AHgAeAB4AHgAeAB4AHgAeAB8AHwAfAB8AHwAgACAAIAAgACEAIQAhACEAIgAiACIAIwAjACMAJAAkACQAJQAlACUAJQAmACYAJgAmACYAJgAmACYAJgAmACYAJgAmACYAJgAmACYAJgAmACYAJgAmACUAJQAlACUAJQAlACQAJAAkACQAIwAjACMAIgAiACIAIQAhACEAIAAgAB8AHwAfAB4AHgAdAB0AHAAcABsAGwAaABoAGQAZABgAGAAXABcAFgAVABUAFAATABMAEgARABEAEAAPAA4ADgANAAwADAALAAoACgAJAAgABwAHAAYABQAFAAQAAwACAAEAAAAAAP///v/9//z/+//6//n/+P/4//f/9v/1//T/8//z//L/8f/w//D/7//u/+7/7f/s/+z/6//q/+r/6f/p/+j/6P/n/+f/5v/m/+b/5f/l/+X/5P/k/+T/5P/k/+T/5P/j/+P/4//j/+P/4//j/+T/5P/k/+T/5P/k/+T/5P/k/+T/5P/k/+T/5P/k/+P/4//j/+P/4//j/+P/4v/i/+L/4v/i/+L/4//j/+P/4//j/+P/4//j/+T/5P/k/+T/5P/l/+X/5f/l/+X/5f/m/+b/5v/m/+b/5v/m/+f/5//n/+f/5//n/+f/6P/o/+j/6P/o/+j/6P/p/+n/6f/p/+n/6v/q/+r/6//r/+v/7P/s/+z/7f/t/+3/7v/u/+7/7v/v/+//7//w//D/8P/w//D/8f/x//H/8f/x//H/8f/x//L/8v/y//L/8v/z//P/8//z//P/9P/0//T/9P/0//X/9f/1//X/9f/2//b/9v/2//b/9//3//f/9//4//j/+P/4//n/+f/5//r/+v/6//v/+//7//z//P/8//3//f/+//7//v//////AAAAAAEAAQACAAMAAwAEAAQABQAFAAYABgAGAAcABwAIAAgACAAJAAkACgAKAAoACwALAAsADAAMAA0ADQANAA4ADgAOAA8ADwAPABAAEAAQABAAEAARABEAEQARABIAEgASABIAEwATABMAFAAUABQAFAAUABUAFQAVABYAFgAWABYAFwAXABcAGAAYABgAGAAZABkAGQAZABoAGgAaABoAGgAbABsAGwAbABsAGwAbABsAGwAbABsAGgAaABoAGgAaABkAGQAZABgAGAAYABcAFwAWABYAFQAVABQAEwATABIAEgARABEAEAAPAA8ADgAOAA0ADAAMAAsACgAKAAkACAAIAAcABgAGAAUABQAEAAMAAwACAAIAAQABAAAAAAD//////v/+//7//f/9//z//P/8//v/+//7//r/+v/6//n/+f/5//j/+P/4//j/+P/4//f/9//3//f/9//3//f/9//3//f/9//3//f/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/6//r/+v/6//r/+v/7//v/+//7//v/+//8//z//P/8//z//P/9//3//f/9//3//f/+//7//v/+//7//v//////////////AAAAAAAAAAABAAEAAQABAAEAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgABAAEAAQABAAEAAQAAAAAAAAAAAAAA//////////////7//v/+//7//v/+//7//v/9//3//f/9//3//f/8//z//P/8//z//P/8//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+v/6//r/+v/6//r/+v/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/6//r/+v/6//r/+//7//v/+//8//z//P/9//3//v/+//////8AAAAAAQABAAIAAgADAAMABAAEAAUABQAGAAYABgAHAAcACAAIAAgACQAJAAoACgAKAAsACwALAAsADAAMAAwADAANAA0ADQANAA0ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgANAA0ADQANAA0ADQAMAAwADAAMAAwADAALAAsACwAKAAoACgAJAAkACQAIAAgACAAIAAgABwAHAAcABwAGAAYABgAGAAUABQAFAAQABAAEAAMAAwADAAMAAgACAAIAAQABAAEAAQAAAAAAAAD///////////7//v/+//7//v/9//3//f/9//z//P/8//z/+//7//v/+//7//r/+v/6//r/+v/5//n/+f/5//j/+P/4//j/9//3//f/9//3//b/9v/2//b/9f/1//X/9f/1//X/9f/1//T/9P/0//T/9P/0//P/8//z//P/8//z//P/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//H/8f/x//H/8f/x//H/8f/x//H/8f/x//H/8f/x//H/8f/w//D/8P/w//D/8P/w//D/8P/w//D/8P/w//H/8f/x//H/8f/x//H/8f/x//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/z//P/8//z//P/8//z//P/8//z//P/9P/0//T/9P/0//X/9f/1//X/9f/2//b/9v/2//f/9//3//j/+P/4//n/+f/5//r/+v/6//r/+//7//v/+//7//z//P/8//z//P/9//3//f/9//3//v/+//7//v/+////////////AAAAAAAAAAABAAEAAQABAAEAAgACAAIAAgADAAMAAwADAAQABAAEAAQABAAFAAUABQAFAAYABgAGAAYABwAHAAcABwAHAAgACAAIAAgACAAIAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAKAAoACgAKAAoACgAKAAsACwALAAsACwALAAsACwALAAsACwALAAsACwAMAAwADAAMAAwADAAMAAwADQANAA0ADQANAA4ADgAOAA4ADwAPAA8ADwAPAA8AEAAQABAAEAAQABAAEAAQABAAEAAQABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEQARABEAEAAQABAAEAAQABAAEAAQAA8ADwAPAA8ADwAOAA4ADgAOAA4ADQANAA0ADQAMAAwADAAMAAwACwALAAsACwAKAAoACgAKAAkACQAJAAkACAAIAAgACAAIAAcABwAHAAcABwAGAAYABgAGAAUABQAFAAUABAAEAAQABAAEAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAIAAgACAAIAAgACAAIAAgACAAIAAQABAAEAAQABAAEAAQABAAAAAAAAAAAAAAAAAP///////////v/+//7//v/+//3//f/9//3//f/9//z//P/8//z//P/8//z//P/8//v/+//7//v/+//7//v/+//7//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+f/5//n/+f/5//n/+f/5//n/+P/4//j/+P/4//j/9//3//f/9//3//b/9v/2//b/9v/2//X/9f/1//X/9P/0//T/9P/z//P/8//z//P/8v/y//L/8v/y//H/8f/x//H/8f/x//D/8P/w//D/8P/w//D/8P/w//D/8P/w//D/8P/w//D/8P/w//D/8P/x//H/8f/x//H/8f/x//H/8f/x//H/8f/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//L/8v/y//P/8//z//P/8//z//P/8//z//P/8//z//P/8//z//P/8//z//T/9P/0//T/9P/0//T/9P/0//T/9P/0//T/9P/0//T/9P/0//T/9P/0//T/9P/0//T/9P/0//T/9P/0//T/9P/0//T/9f/1//X/9f/1//X/9f/1//X/9v/2//b/9v/2//f/9//3//f/+P/4//j/+f/5//n/+f/6//r/+v/6//v/+//7//z//P/8//z//f/9//3//v/+//7///////////8AAAAAAAABAAEAAgACAAIAAwADAAMABAAEAAQABAAFAAUABQAFAAYABgAGAAYABwAHAAcABwAHAAcABwAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAcABwAHAAcABwAHAAcABwAHAAYABgAGAAYABgAGAAYABgAGAAYABgAGAAYABgAGAAYABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABgAGAAYABgAGAAYABgAHAAcABwAHAAcABwAHAAcACAAIAAgACAAIAAgACQAJAAkACQAJAAoACgAKAAoACwALAAsACwALAAwADAAMAAwADQANAA0ADQAOAA4ADgAPAA8ADwAPABAAEAAQABAAEQARABEAEQARABEAEQARABEAEgASABIAEgASABIAEgASABIAEQARABEAEQARABEAEQARABEAEAAQABAAEAAQAA8ADwAPAA4ADgAOAA4ADQANAA0ADAAMAAsACwALAAoACgAKAAkACQAIAAgABwAHAAYABgAGAAUABQAEAAQAAwADAAMAAgACAAEAAQAAAAAA//////7//v/+//3//f/8//z//P/7//v/+//7//r/+v/6//r/+f/5//n/+f/5//n/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//j/+P/5//n/+f/5//n/+f/5//n/+f/5//r/+v/6//r/+v/6//r/+//7//v/+//7//z//P/8//z//P/8//3//f/9//3//f/9//7//v/+//7///////////8AAAAAAAAAAAEAAQABAAIAAgACAAIAAwADAAMAAwAEAAQABAAEAAUABQAFAAUABgAGAAYABgAGAAcABwAHAAcABwAIAAgACAAIAAgACAAIAAgACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAgACAAIAAgACAAIAAgABwAHAAcABwAHAAcABgAGAAYABgAGAAYABQAFAAUABQAFAAQABAAEAAQABAAEAAQAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQAAwADAAMAAwADAAMAAwADAAMAAwADAAIAAgACAAIAAgACAAIAAQABAAEAAQAAAAAAAAAAAP////////7//v/+//3//f/9//z//P/8//v/+//6//r/+v/5//n/+f/4//j/9//3//f/9v/2//X/9f/1//T/9P/z//P/8//y//L/8v/y//H/8f/x//H/8P/w//D/8P/w//D/7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//w//D/8P/w//D/8P/w//H/8f/x//H/8f/y//L/8v/y//L/8//z//P/8//z//T/9P/0//T/9f/1//X/9f/2//b/9v/2//f/9//3//f/+P/4//j/+P/5//n/+f/5//r/+v/6//r/+//7//v//P/8//z//P/9//3//f/9//7//v/+//7//v//////////////AAAAAAAAAAAAAAEAAQABAAEAAQABAAIAAgACAAIAAgACAAMAAwADAAMAAwADAAMAAwAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAUABQAFAAYABgAGAAYABgAGAAYABgAGAAYABgAGAAYABgAHAAcABwAHAAcABwAHAAcABwAIAAgACAAIAAgACAAIAAgACAAIAAkACQAJAAkACQAJAAkACQAJAAoACgAKAAoACgAKAAoACgAKAAsACwALAAsACwALAAsACwALAAsADAAMAAwADAAMAAwADAAMAA0ADQANAA0ADQANAA0ADQAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAPAA8ADwAPAA8ADwAPAA8ADwAPAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA0ADQANAA0ADQANAA0ADAAMAAwADAAMAAsACwALAAsACgAKAAoACgAJAAkACQAJAAgACAAIAAgABwAHAAcABwAGAAYABgAGAAUABQAFAAUABQAEAAQABAAEAAMAAwADAAMAAwACAAIAAgACAAEAAQABAAEAAAAAAAAAAAAAAP///////////v/+//7//v/+//3//f/9//3//f/8//z//P/8//v/+//7//v/+v/6//r/+v/5//n/+f/5//j/+P/4//j/9//3//f/9//2//b/9v/2//X/9f/1//X/9P/0//T/9P/0//P/8//z//P/8//y//L/8v/y//L/8f/x//H/8f/x//H/8P/w//D/8P/w//D/8P/w/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//8P/w//D/8P/w//D/8P/x//H/8f/x//H/8v/y//L/8v/z//P/8//z//P/9P/0//T/9P/0//X/9f/1//X/9f/2//b/9v/2//b/9v/2//f/9//3//f/9//3//f/9//3//f/9//4//j/+P/4//j/+P/4//j/+P/4//j/+P/4//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+f/5//n/+v/6//r/+v/6//r/+v/6//r/+v/6//v/+//7//v/+//7//v//P/8//z//P/8//z//f/9//3//f/+//7//v/+//7///////////8AAAAAAAAAAAEAAQABAAEAAgACAAIAAwADAAMAAwAEAAQABAAFAAUABQAFAAYABgAGAAYABwAHAAcABwAIAAgACAAIAAgACQAJAAkACQAJAAoACgAKAAoACgAKAAoACwALAAsACwALAAsACwALAAsADAAMAAwADAAMAAwADAAMAAwADAAMAAwADQANAA0ADQANAA0ADQANAA0ADQANAA0ADQANAA0ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgAOAA4ADgANAA0ADQANAA0ADQANAA0ADQAMAAwADAAMAAwADAAMAAsACwALAAsACwALAAoACgAKAAoACgAKAAkACQAJAAkACQAJAAgACAAIAAgACAAIAAgABwAHAAcABwAHAAYABgAGAAYABQAFAAUABQAFAAQABAAEAAMAAwADAAMAAgACAAIAAgABAAEAAQAAAAAAAAAAAP////////7//v/+//7//v/9//3//f/9//z//P/8//z//P/7//v/+//7//v/+//6//r/+v/6//r/+v/6//n/+f/5//n/+f/5//n/+f/5//n/+P/4//j/+P/4//j/+P/4//j/+P/3//f/9//3//f/9//3//f/9//3//f/9//3//f/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//X/9f/1//X/9f/1//X/9f/1//X/9f/1//X/9f/1//X/9f/1//X/9f/1//X/9f/1//X/9f/1//X/9f/1//X/9f/1//X/9f/1//X/9f/1//X/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//b/9v/2//f/9//3//f/9//3//f/9//3//j/+P/4//j/+P/4//n/+f/5//n/+f/6//r/+v/6//r/+//7//v/+//8//z//P/8//3//f/9//3//v/+//7//v///////////wAAAAAAAAEAAQABAAEAAgACAAIAAgADAAMAAwADAAQABAAEAAQABAAFAAUABQAFAAUABgAGAAYABgAGAAYABwAHAAcABwAHAAcABwAHAAcACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAKAAoACgAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAIAAgACAAIAAgACAAIAAgACAAIAAgABwAHAAcABwAHAAcABwAGAAYABgAGAAYABgAFAAUABQAFAAUABQAEAAQABAAEAAQABAADAAMAAwADAAMAAwACAAIAAgACAAIAAgABAAEAAQABAAEAAQABAAAAAAAAAAAAAAAAAAAA//////////////////////7//v/+//7//v/+//7//v/+//7//v/+//7//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/8//z//P/8//z//P/8//z//P/8//z//P/8//z//P/7//v/+//7//v/+//7//v/+//7//v/+//7//v/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+v/6//r/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//z//P/8//z//P/8//z//P/8//z//P/8//z//P/8//z//P/8//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//////////////////////////////////////////////////////////////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAEAAQABAAEAAQABAAEAAQACAAIAAgACAAIAAgACAAIAAwADAAMAAwADAAMAAwAEAAQABAAEAAQABAAEAAUABQAFAAUABQAFAAUABgAGAAYABgAGAAYABgAGAAYABgAGAAcABwAHAAcABwAHAAcABwAHAAcABwAHAAcABwAHAAcABwAHAAcABwAHAAcABwAHAAYABgAGAAYABgAGAAYABgAGAAYABQAFAAUABQAFAAUABQAEAAQABAAEAAQABAADAAMAAwADAAMAAwADAAMAAgACAAIAAgACAAIAAgACAAIAAgABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAwADAAMAAwADAAMAAwADAAMAAwACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgABAAEAAQABAAEAAQABAAEAAQABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///////////////////////////////////////////////////v/+//7//v/+//7//v/+//7//v///////////////////////////////////////////////////////////////////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/////////////////////////////////////////////////////////////////////////v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v////////////////////////////////////////////////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///////////////////////////////////////////////////+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//v/+//7//v/+//7//v/+/////////////////wAAAAAAAAAAAAAAAAEAAQABAAEAAQABAAIAAgACAAIAAgADAAMAAwADAAMABAAEAAQABAAEAAQABQAFAAUABQAFAAUABQAGAAYABgAGAAYABgAGAAYABwAHAAcABwAHAAcABwAHAAcABwAHAAcABwAHAAcABwAHAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAcABwAHAAcABwAHAAcABwAHAAcABwAHAAcABwAHAAcABgAGAAYABgAGAAYABgAGAAYABQAFAAUABQAFAAUABQAFAAUABAAEAAQABAAEAAQABAAEAAMAAwADAAMAAwADAAMAAwACAAIAAgACAAIAAgACAAIAAgACAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///////////////////////////////////////////////////v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//z//P/8//z//P/8//z//P/8//z//P/8//z//P/8//z//P/8//z//P/8//z/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//8//z//P/8//z//P/8//z//P/8//z//P/8//z//P/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/+//7//v/+//7//v/+//7//v/+//7//v///////////////////////////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAwADAAMAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAQABAAEAAQABAAEAAQABAAEAAQABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///////////////////////////////////v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//f/9//3//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+/////////////////////////////////////////////////////////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD////////////////////////////////////////////////////////////////////////+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+/////////////////////////////////////////////////////////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////7//v/+//7//v/+//7//v/+//7//v/+//7//v/+//7//v/+/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQABAAEAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"), char => char.charCodeAt(0)));
    const riser = recording(Uint8Array.from(atob("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"), char => char.charCodeAt(0)));
    const output = audio.createGain(), voices = new Set();
    let swells = [];
    output.gain.value = .7; output.connect(audio.destination);
    const noise = audio.createBuffer(1, audio.sampleRate, audio.sampleRate);
    const samples = noise.getChannelData(0);
    for (let i = 0; i < samples.length; ++i) samples[i] = Math.random() * 2 - 1;
    function voice(from, to, duration, volume, type = "sine", delay = 0, swell = false) {
      const start = audio.currentTime + delay, gain = audio.createGain();
      const source = type === "noise" || type === "riser" ? audio.createBufferSource() : audio.createOscillator();
      let filter;
      if (type === "noise" || type === "riser") {
        source.buffer = type === "riser" ? riser : noise; source.loop = true;
        if (type === "riser") source.playbackRate.value = .8;
        filter = audio.createBiquadFilter(); filter.type = type === "riser" ? "lowpass" : "bandpass"; filter.Q.value = .7;
        source.connect(filter); filter.connect(gain);
      } else { source.type = type; source.connect(gain); }
      const pitch = filter ? filter.frequency : source.frequency;
      pitch.setValueAtTime(from, start);
      gain.gain.setValueAtTime(.0001, start);
      if (!swell) {
        pitch.exponentialRampToValueAtTime(to, start + duration);
        gain.gain.linearRampToValueAtTime(volume, start + Math.min(.025, duration * .2));
        gain.gain.exponentialRampToValueAtTime(.0001, start + duration);
      }
      gain.connect(output); voices.add(source);
      source.onended = () => { voices.delete(source); source.disconnect(); filter?.disconnect(); gain.disconnect(); };
      source.start(start);
      if (!swell) source.stop(start + duration);
      return { pitch, gain: gain.gain, from, to, volume };
    }
    function play(buffer, volume, rate = 1) {
      const source = audio.createBufferSource(), gain = audio.createGain();
      source.buffer = buffer; source.playbackRate.value = rate;
      gain.gain.value = volume; source.connect(gain); gain.connect(output); voices.add(source);
      source.onended = () => { voices.delete(source); source.disconnect(); gain.disconnect(); };
      source.start(audio.currentTime);
    }
    return {
      stop() { voices.forEach((source) => { source.stop(); source.disconnect(); }); voices.clear(); swells = []; },
      mute(value) { output.gain.setValueAtTime(value ? 0 : .7, audio.currentTime); if (value) this.stop(); },
      gather(seconds = 1.5) {
        play(shuffle, .75, Math.max(.85, Math.min(1.2, shuffle.duration / (seconds + .1))));
        this.spin(seconds); this.progress(0);
      },
      spin(seconds) { if (!seconds || swells.length) return; swells = [voice(450, 6500, seconds, .24, "riser", 0, true), voice(320, 3400, seconds, .06, "noise", 0, true)]; },
      progress(value) { value = .18 + .82 * value; swells.forEach(({ pitch, gain, from, to, volume }) => {
        pitch.setTargetAtTime(from * Math.pow(to / from, value), audio.currentTime, .015);
        gain.setTargetAtTime(.0001 + volume * value, audio.currentTime, .015);
      }); },
      tick() { voice(1700, 900, .045, .12, "noise"); voice(850, 460, .055, .045); },
      land() {
        this.stop(); play(impact, 1.1);
      },
      reveal() { voice(1100, 180, .45, .065, "noise"); },
    };
  }
  const rouletteTimestamp = () => {};
  function RouletteActions({ entry, disabled, onOpen }) {
    const loading = Api.hooks.useLoadComponents([Api.loadableComponents.Scene]);
    const query = GQL.useFindSceneQuery({ variables: { id: entry.origin.scene_id } });
    const [updateScene] = Api.utils.StashService.useSceneUpdate();
    const [incrementO] = Api.utils.StashService.useSceneIncrementO(entry.origin.scene_id);
    const [saving, setSaving] = React.useState(false);
    const [error, setError] = React.useState("");
    const [oBurst, setOBurst] = React.useState(0);
    const scene = query.data?.findScene;
    async function save(action) {
      setSaving(true); setError("");
      try { await action(); }
      catch (failure) { setError(failure.message); }
      finally { setSaving(false); }
    }
    if (loading) return null;
    return React.createElement("fieldset", { className: "curator-roulette-actions", disabled: disabled || saving || !scene, "aria-label": "Scene actions" },
      React.createElement(Feedback, { item: { ...entry.item, scene_id: entry.origin.scene_id, impression_id: entry.origin.impression_id }, compact: true }),
      React.createElement("span", { className: "curator-roulette-rating", "aria-label": "Scene rating" },
        React.createElement(Api.components.RatingSystem, { value: scene?.rating100, disabled: disabled || saving || !scene, clickToRate: true, withoutContext: true,
          onSetRating: (rating100) => save(() => updateScene({ variables: { input: { id: scene.id, rating100 } } })) })),
      React.createElement(Button, { className: "curator-roulette-o", variant: "dark", size: "sm", "aria-label": "Increment O counter", title: "Increment O counter", onClick: () => save(async () => { await incrementO(); setOBurst((value) => value + 1); }) },
        React.createElement(Api.components.SweatDrops), " ", scene?.o_counter ?? 0,
        oBurst > 0 && React.createElement("span", { key: oBurst, className: "curator-roulette-o-burst", "aria-hidden": "true" }, [0, 1, 2].map((i) => React.createElement("i", { key: i, style: { "--drop": i } })))),
      React.createElement("a", { className: "btn btn-dark btn-sm", href: `/scenes/${entry.origin.scene_id}`, target: "_blank", rel: "noopener noreferrer", "aria-disabled": disabled, tabIndex: disabled ? -1 : undefined,
        onClick: (event) => { if (disabled) event.preventDefault(); else onOpen(); } }, "Open scene ↗"),
      error && React.createElement("small", { className: "text-danger", role: "status" }, error));
  }
  function RouletteScene({ entry, onNext, onPrevious, onComplete, onError }) {
    const loadingPlayer = Api.hooks.useLoadComponents([Api.loadableComponents.ScenePlayer]);
    const query = GQL.useFindSceneQuery({ variables: { id: entry.origin.scene_id }, fetchPolicy: "network-only" });
    const scene = query.data?.findScene;
    const playbackScene = React.useMemo(() => scene && { ...scene, resume_time: entry.time }, [scene, entry.time]);
    React.useEffect(() => {
      if (query.error || (!query.loading && (!scene || !scene.files.length))) onError("This scene is unavailable. Try Next or return to recommendations.");
    }, [query.error, query.loading, scene, onError]);
    if (loadingPlayer || query.loading || !scene?.files.length) return null;
    return React.createElement("div", { className: "curator-roulette-scene", "data-roulette-scene": scene.id, "data-roulette-attempt": entry.attempt || 0 },
      React.createElement(Api.components.ScenePlayer, { scene: playbackScene, autoplay: false, permitLoop: false,
        hideScrubberOverride: true, initialTimestamp: entry.time, sendSetTimestamp: rouletteTimestamp,
        onComplete, onNext, onPrevious }));
  }
  function RoulettePlayer({ session, onClose }) {
    const [animateWheel] = useRouletteAnimation();
    const animationPreference = React.useRef(animateWheel);
    animationPreference.current = animateWheel;
    const dialog = React.useRef(null), stage = React.useRef(null), player = React.useRef(null);
    const controller = React.useRef(null);
    const [entry, setEntry] = React.useState(null);
    const [view, setView] = React.useState({ phase: "loading", error: "", muted: false, index: -1 });
    const next = React.useCallback(() => controller.current?.next(), []);
    const previous = React.useCallback(() => controller.current?.previous(), []);
    const completed = React.useCallback(() => controller.current?.complete(), []);
    const failed = React.useCallback((message) => controller.current?.fail(message), []);
    React.useEffect(() => {
      const root = stage.current, host = player.current, wheel = root.querySelector("svg");
      const spinner = root.querySelector(".curator-roulette-spinner"), wrap = root.querySelector(".curator-roulette-wheel-wrap");
      const pointer = root.querySelector(".curator-roulette-pointer-tip"), sources = new Map();
      document.querySelectorAll(".curator-page [data-endless-item]").forEach((node) => {
        const image = node.querySelector("img, video"), bounds = image?.getBoundingClientRect();
        if (bounds?.width && bounds.height && bounds.bottom > 0 && bounds.top < innerHeight && bounds.right > 0 && bounds.left < innerWidth) sources.set(node.dataset.endlessItem, bounds);
      });
      const reduced = matchMedia("(prefers-reduced-motion: reduce)");
      let animated = animationPreference.current && !reduced.matches;
      const focus = document.activeElement, overflow = document.body.style.overflow;
      let muted = false, error = "", media = null, ready = null, frame = 0, markerOwner = null;
      let audio = null, sound = null, lastTick = 0, retrySpin = true, loadTimer, hideTimer;
      try { muted = localStorage.getItem("curator-roulette-muted") === "true"; } catch (_) {}
      const publish = (phase = session.phase) => {
        session.phase = phase; root.dataset.phase = phase;
        root.dataset.animated = String(animated);
        wake();
        if (!session.closed) setView({ phase, error, muted, index: session.index });
      };
      function wake() {
        clearTimeout(hideTimer); root.classList.remove("curator-roulette-quiet");
        if (session.closed) return;
        hideTimer = setTimeout(() => {
          if (session.phase === "playing" && media && !media.paused && !media.ended && media.readyState >= 3) root.classList.add("curator-roulette-quiet");
        }, 2700);
      }
      const resetShape = () => {
        spinner.getAnimations({ subtree: true }).forEach((animation) => animation.cancel());
        spinner.querySelectorAll(".curator-roulette-flight, .curator-roulette-hit").forEach((node) => node.remove());
        wheel.style.removeProperty("opacity");
        [host, spinner, wrap].forEach((node) => { node.getAnimations().forEach((animation) => animation.cancel()); node.removeAttribute("style"); });
      };
      const remember = () => { if (media && session.index >= 0) session.history[session.index].time = media.currentTime; };
      const fullShape = (rectangle) => {
        const aspect = media?.videoWidth / media?.videoHeight || 16 / 9;
        const width = Math.min(root.clientWidth, root.clientHeight * aspect), height = width / aspect;
        return { left: `${(root.clientWidth - width) / 2}px`, top: `${(root.clientHeight - height) / 2}px`, width: `${width}px`, height: `${height}px`, clipPath: rectangle };
      };
      const cue = (name, ...args) => {
        if (!animated || muted || document.hidden || audio?.state !== "running") return;
        const now = audio.currentTime;
        if (name === "tick") { if (now - lastTick < .055) return; lastTick = now; }
        sound?.[name](...args);
      };
      const enableAudio = () => {
        if (muted || !animated) return;
        try { if (!audio) { audio = new AudioContext(); sound = createRouletteSound(audio); } audio.resume().catch(() => {}); } catch (_) {}
      };
      function renderWheel(slots) {
        const svg = (name, attrs, parent) => {
          const node = document.createElementNS("http://www.w3.org/2000/svg", name);
          Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
          parent.appendChild(node); return node;
        };
        const step = Math.PI * 2 / slots.length, tangent = Math.tan(Math.PI / Math.max(3, slots.length));
        // Leave space between the inner corners of adjacent 16:9 cards.
        const width = Math.min(360, 480 * tangent / (1 + 9 / 16 * tangent) * .92), height = width * 9 / 16;
        root.style.setProperty("--curator-roulette-card-width", String(width));
        root.style.setProperty("--curator-roulette-card-top", String((60 - height / 2) / 600));
        root.style.setProperty("--curator-roulette-outer-inset", `${(60 - height / 2 - 12) / 6}%`);
        root.style.setProperty("--curator-roulette-inner-inset", `${(60 + height / 2 + 12) / 6}%`);
        // Keep slot nodes stable when their spent candidate is replenished.
        if (wheel.children.length !== slots.length) {
          wheel.replaceChildren();
          slots.forEach((_, i) => {
            const angle = -Math.PI / 2 + i * step, cx = 300 + 240 * Math.cos(angle), cy = 300 + 240 * Math.sin(angle);
            const group = svg("g", { class: "curator-roulette-slot", transform: `rotate(${i * 360 / slots.length} ${cx} ${cy})` }, wheel);
            const bounds = { x: cx - width / 2, y: cy - height / 2, width, height };
            svg("image", { ...bounds, preserveAspectRatio: "xMidYMid slice" }, group);
            svg("rect", { ...bounds, class: "curator-roulette-wedge" }, group);
            svg("title", {}, group);
          });
        }
        slots.forEach((candidate, i) => {
          const group = wheel.children[i], image = group.querySelector("image");
          image.setAttribute("href", candidate.frame || candidate.scene?.paths?.screenshot || "");
          group.querySelector("title").textContent = candidate.scene?.title || "Untitled scene";
          group.dataset.scene = candidate.origin.scene_id;
          group.querySelector("rect").classList.toggle("selected", session.seen.has(candidate.origin.scene_id));
          group.classList.toggle("winning", !["spinning", "rewinding"].includes(session.phase) && session.history[session.index]?.origin.scene_id === candidate.origin.scene_id);
        });
      }
      async function assemble(slots, token) {
        publish("assembling");
        const stageBounds = root.getBoundingClientRect(), diameter = wrap.getBoundingClientRect().width;
        const size = Math.min(root.clientWidth * .84, root.clientHeight * .64);
        const offset = root.clientHeight * .48 - size / 2 - (wrap.getBoundingClientRect().top - stageBounds.top);
        const assembled = `translateX(-50%) translateY(${offset}px) scale(${size / diameter})`;
        wrap.style.transform = assembled;
        wheel.style.opacity = "0";
        // Measure every destination before adding animated cards to avoid layout per card.
        const targets = Array.from(wheel.children, (group) => {
          const image = group.querySelector("image"), matrix = image.getScreenCTM(), box = image.getBBox();
          const x = box.x + box.width / 2, y = box.y + box.height / 2;
          const width = box.width * Math.hypot(matrix.a, matrix.b), height = width * 9 / 16;
          const endX = matrix.a * x + matrix.c * y + matrix.e - stageBounds.left;
          const endY = matrix.b * x + matrix.d * y + matrix.f - stageBounds.top;
          const angle = Math.atan2(matrix.b, matrix.a) * 180 / Math.PI;
          return { width, height, endX, endY, angle, src: image.getAttribute("href") };
        });
        const flights = slots.map((candidate, i) => {
          const { width, height, endX, endY, angle, src } = targets[i];
          const source = sources.get(candidate.origin.scene_id);
          const startX = source ? source.left + source.width / 2 - stageBounds.left : i % 2 ? -180 : root.clientWidth + 180;
          const startY = source ? source.top + source.height / 2 - stageBounds.top : root.clientHeight * (.25 + (i % 5) * .12);
          const card = document.createElement("div"), thumbnail = document.createElement("img");
          card.className = "curator-roulette-flight scene-card";
          card.style.width = `${width}px`; card.style.height = `${height}px`;
          thumbnail.className = "scene-card-image card-section"; thumbnail.alt = "";
          thumbnail.src = src; card.appendChild(thumbnail); spinner.appendChild(card);
          const transform = (cx, cy, rotation = 0, scale = 1) => `translate(${cx - width / 2}px, ${cy - height / 2}px) rotate(${rotation}deg) scale(${scale})`;
          const animation = card.animate([
            { transform: transform(startX, startY, 0, (source?.width || 220) / width), opacity: source ? 1 : 0 },
            { transform: transform(root.clientWidth * (.35 + (i % 4) * .1), root.clientHeight * (.35 + (i % 3) * .12), i % 2 ? 12 : -12, 1.7), opacity: 1, offset: .38 },
            { transform: transform(endX, endY, angle), opacity: 1 },
          ], { duration: 1000, delay: i * 22, easing: "cubic-bezier(.22,.7,.18,1)", fill: "both" });
          return { card, animation };
        });
        await Promise.all(flights.map(({ animation }) => animation.ready.catch(() => {})));
        if (session.closed || token !== session.token) return;
        const gather = () => {
          if (!session.closed && token === session.token && session.phase === "assembling" && !document.hidden) cue("gather", 1 + (slots.length - 1) * .022);
        };
        if (audio?.state === "suspended") audio.resume().then(gather).catch(() => {});
        else gather();
        await Promise.all(flights.map(({ animation }) => animation.finished.catch(() => {})));
        flights.forEach(({ card }) => card.remove()); wheel.style.removeProperty("opacity");
        if (session.closed || token !== session.token) return;
        const zoom = wrap.animate([{ transform: assembled }, { transform: "translateX(-50%) scale(1)" }],
          { duration: 850, easing: "cubic-bezier(.22,.7,.18,1)", fill: "forwards" });
        await zoom.finished.catch(() => {});
        wrap.style.removeProperty("transform"); zoom.cancel();
      }
      async function reveal() {
        if (!ready || !media || media.readyState < 2 || session.closed) return;
        const selected = session.history[session.index], container = media.closest("[data-roulette-scene]");
        if (container?.dataset.rouletteScene !== selected.origin.scene_id || container.dataset.rouletteAttempt !== String(selected.attempt || 0)) return;
        const { token, shape } = ready; ready = null; clearTimeout(loadTimer);
        if (token !== session.token) return;
        media.muted = muted;
        attachPlayer(location.pathname, { sceneId: session.history[session.index].origin.scene_id, origin: session.history[session.index].origin, root: host });
        media.play().catch(() => { if (token === session.token) { error = "Playback paused by your browser. Press Play to continue."; publish(); } });
        if (shape && animated) {
          const { rectangle, ...start } = shape, target = fullShape(rectangle);
          Object.assign(host.style, start); publish("revealing");
          cue("reveal");
          const timing = { duration: 1300, easing: "cubic-bezier(.4,0,.2,1)", fill: "forwards" };
          const animation = host.animate([start, target], timing);
          spinner.animate([{ transform: "scale(1)", opacity: 1 }, { transform: `scale(${Math.min(.45, parseFloat(target.height) / root.clientHeight * .7)})`, opacity: 0 }], timing);
          await animation.finished.catch(() => {});
          if (session.closed || token !== session.token) return;
        }
        if (!animated && !reduced.matches) {
          publish("revealing");
          await host.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 220, easing: "ease-out" }).finished.catch(() => {});
          if (session.closed || token !== session.token) return;
        }
        resetShape(); publish("playing");
      }
      function bind() {
        const element = host.querySelector("video");
        if (element !== media) {
          if (media) {
            media.removeEventListener("loadeddata", reveal); media.removeEventListener("error", mediaError); media.removeEventListener("volumechange", volumeChanged);
            ["playing", "pause", "waiting", "ended"].forEach((event) => media.removeEventListener(event, wake));
          }
          media = element;
          if (media) {
            // Stash preloads nothing; load a frame even when the browser blocks autoplay.
            media.preload = "auto"; media.muted = muted;
            media.addEventListener("loadeddata", reveal); media.addEventListener("error", mediaError); media.addEventListener("volumechange", volumeChanged);
            ["playing", "pause", "waiting", "ended"].forEach((event) => media.addEventListener(event, wake));
            const native = Api.utils.InteractiveUtils.getPlayer();
            if (native && native !== markerOwner && native.el()?.contains(media)) {
              markerOwner = native;
              const markers = native.markers?.();
              // Stash's cleanup requests markers after disposal, recreating them against a removed element.
              if (markers) native.one("dispose", () => { native.markers = () => markers; });
              const play = native.play;
              native.play = function (...args) {
                const pending = play.apply(this, args);
                // Stash ignores this promise; Roulette reports failures through its controls.
                pending?.catch(() => {});
                return pending;
              };
            }
          }
        }
        reveal();
      }
      function mediaError() { fail("This scene could not play. Try Next or return to recommendations."); }
      function volumeChanged() {
        // Native player initialization can restore a stale mute setting during the reveal.
        if (session.phase !== "playing") { media.muted = muted; return; }
        muted = media.muted;
        sound?.mute(muted);
        try { localStorage.setItem("curator-roulette-muted", String(muted)); } catch (_) {}
        publish();
      }
      function fail(message) {
        if (session.closed) return;
        error = message; ready = null; clearTimeout(loadTimer); sound?.stop(); resetShape(); publish("error");
      }
      function loadEntry(selected, shape, token) {
        clearTimeout(loadTimer); ready = { token, shape };
        loadTimer = setTimeout(() => {
          if (token === session.token && ready) fail("This scene is taking too long to load. Retry or try Next.");
        }, 30000);
        setEntry(selected);
      }
      async function spin(first = false) {
        const token = ++session.token;
        animated = animationPreference.current && !reduced.matches;
        retrySpin = true;
        error = ""; publish("loading");
        try {
          await fillRoulette(session, innerWidth < 760 ? 16 : 24);
          if (session.closed || token !== session.token) return;
          const slots = rouletteSlots(session, innerWidth < 760 ? 16 : 24), winner = rouletteWinner(session, slots);
          if (!winner) { publish("exhausted"); return; }
          const winnerIndex = slots.indexOf(winner);
          if (!session.slots.length) { session.slots = slots; renderWheel(slots); }
          resetShape();
          wheel.querySelectorAll(".winning").forEach((node) => node.classList.remove("winning"));
          if (first && animated) await assemble(slots, token);
          if (session.closed || token !== session.token) return;
          publish("spinning");
          const start = session.rotation, step = 360 / slots.length;
          const alignment = ((-winnerIndex * step - start) % 360 + 360) % 360;
          const target = start + (first ? 720 : 360) + alignment, duration = !animated ? 0 : first ? 3800 : 2600;
          cue("spin", duration / 1000);
          const started = performance.now(); let previousSector = -1;
          await new Promise((resolve) => {
            function rotate(now) {
              if (session.closed || token !== session.token) { resolve(); return; }
              const t = duration ? Math.min(1, (now - started) / duration) : 1;
              const ease = t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
              session.rotation = start + (target - start) * ease;
              wheel.style.transform = `rotate(${session.rotation}deg)`;
              wrap.style.setProperty("--camera-zoom", String(1 + .07 * ease));
              wrap.style.setProperty("--spin-progress", String(t));
              wrap.style.setProperty("--roulette-orbit", `${session.rotation % 360}deg`);
              if (animated) cue("progress", t);
              if (session.slots !== slots && t > 0) { session.slots = slots; renderWheel(slots); }
              const sector = Math.floor(session.rotation / step);
              if (sector !== previousSector) {
                previousSector = sector; if (animated) cue("tick");
                if (animated && !pointer.getAnimations().length) pointer.animate([
                  { transform: "rotate(-9deg)" }, { transform: "rotate(5deg)", offset: .55 }, { transform: "rotate(0deg)" },
                ], { duration: 130, easing: "ease-out" });
              }
              if (t < 1) frame = requestAnimationFrame(rotate); else resolve();
            }
            frame = requestAnimationFrame(rotate);
          });
          if (session.closed || token !== session.token) return;
          cue("land"); session.seen.add(winner.origin.scene_id);
          session.history.splice(session.index + 1);
          const previous = session.history[session.index];
          const selected = { ...winner, time: 0, slot: winnerIndex, slots: [...slots], rotation: session.rotation,
            attempt: winner.origin.scene_id === previous?.origin.scene_id ? (previous.attempt || 0) + 1 : 0 };
          session.history.push(selected); session.index = session.history.length - 1;
          renderWheel(slots);
          wheel.children[winnerIndex].classList.add("winning");
          if (animated) {
            publish("celebrating");
            const { left, top, width, height } = rouletteShape(root, session), hit = document.createElement("div");
            hit.className = "curator-roulette-hit"; Object.assign(hit.style, { left, top, width, height }); spinner.appendChild(hit);
            // Composite a small outline instead of repainting the entire SVG wheel each frame.
            await hit.animate([
              { opacity: .35, transform: "scale(1)" },
              { opacity: 1, transform: "scale(1.035)", offset: .48 },
              { opacity: .65, transform: "scale(1)" },
            ], { duration: 650, easing: "ease-in-out" }).finished.catch(() => {});
            hit.remove();
            if (session.closed || token !== session.token) return;
          }
          publish("landing");
          retrySpin = false;
          finishTracker(false); media?.pause();
          loadEntry(selected, animated ? rouletteShape(root, session) : null, token);
        } catch (failure) { if (token === session.token) fail(failure.message); }
      }
      async function foldCurrent() {
        root.dataset.animated = String(animated);
        const current = session.history[session.index];
        if (current && session.phase === "playing" && animated) {
          const token = ++session.token;
          session.slots = [...current.slots]; session.rotation = current.rotation; renderWheel(session.slots);
          wheel.style.transform = `rotate(${session.rotation}deg)`;
          const { rectangle, ...target } = rouletteShape(root, session);
          const start = fullShape(rectangle); Object.assign(host.style, start); publish("returning");
          const timing = { duration: 1100, easing: "cubic-bezier(.4,0,.2,1)", fill: "forwards" };
          const animation = host.animate([start, target], timing);
          spinner.animate([{ transform: "scale(.45)", opacity: 0 }, { transform: "scale(1)", opacity: 1 }], timing);
          await animation.finished.catch(() => {});
          if (session.closed || token !== session.token) return false;
        }
        media?.pause(); remember(); finishTracker(false);
        if (current && media?.readyState >= 2) {
          try {
            const canvas = document.createElement("canvas"); canvas.width = Math.min(640, media.videoWidth);
            canvas.height = canvas.width * media.videoHeight / media.videoWidth;
            canvas.getContext("2d").drawImage(media, 0, 0, canvas.width, canvas.height); current.frame = canvas.toDataURL("image/jpeg");
            current.slots[current.slot].frame = current.frame;
            const candidate = session.pool.find((entry) => entry.origin.scene_id === current.origin.scene_id);
            if (candidate) candidate.frame = current.frame;
            const image = wheel.querySelectorAll("image")[current.slot]; image?.setAttribute("href", current.frame);
          } catch (_) { /* A cross-origin stream keeps its screenshot. */ }
        }
        return true;
      }
      async function advance() {
        if (!["playing", "error"].includes(session.phase)) return;
        animated = animationPreference.current && !reduced.matches;
        sound?.stop(); enableAudio(); remember();
        if (await foldCurrent()) await spin();
      }
      async function back() {
        if (!["playing", "error", "exhausted"].includes(session.phase) || session.index < 1) return;
        animated = animationPreference.current && !reduced.matches;
        const rewind = session.phase === "playing" && animated;
        sound?.stop(); enableAudio(); remember();
        if (!await foldCurrent()) return;
        const selected = session.history[session.index - 1], token = ++session.token;
        if (rewind) {
          publish("rewinding"); resetShape();
          const delta = ((selected.rotation - session.rotation) % 360 + 540) % 360 - 180;
          const animation = wheel.animate([
            { transform: `rotate(${session.rotation}deg)` },
            { transform: `rotate(${session.rotation + delta}deg)` },
          ], { duration: 700, easing: "cubic-bezier(.4,0,.2,1)", fill: "forwards" });
          frame = requestAnimationFrame(() => {
            if (session.closed || token !== session.token) return;
            session.slots = [...selected.slots]; renderWheel(session.slots);
          });
          await animation.finished.catch(() => {});
          if (session.closed || token !== session.token) return;
        }
        --session.index;
        session.slots = [...selected.slots]; session.rotation = selected.rotation;
        wheel.style.transform = `rotate(${session.rotation}deg)`; resetShape(); error = ""; publish("landing");
        renderWheel(session.slots);
        retrySpin = false;
        loadEntry(selected, rewind ? rouletteShape(root, session) : null, token);
      }
      function close() {
        session.closed = true; ++session.token; sound?.stop(); remember(); media?.pause(); finishTracker(false);
        if (document.fullscreenElement === root) document.exitFullscreen().catch(() => {});
        onClose();
      }
      controller.current = {
        next: advance, previous: back, fail, close,
        pause() { media?.pause(); remember(); },
        complete() { finishTracker(true); advance(); },
        mute() { muted = !muted; if (media) media.muted = muted; try { localStorage.setItem("curator-roulette-muted", String(muted)); } catch (_) {} enableAudio(); sound?.mute(muted); publish(); },
        fullscreen() { wake(); const action = document.fullscreenElement ? document.exitFullscreen() : root.requestFullscreen?.(); action?.catch(() => { error = "Fullscreen is unavailable in this browser."; publish(); }); },
        retry() {
          if (retrySpin) { session.done = false; spin(!session.history.length); return; }
          error = ""; media?.pause(); finishTracker(false); publish("landing");
          const selected = session.history[session.index];
          selected.attempt = (selected.attempt || 0) + 1; loadEntry({ ...selected }, null, ++session.token);
        },
      };
      const activityEvents = ["pointermove", "pointerdown", "keydown", "focusin"];
      const visibilityChanged = () => { if (document.hidden) sound?.stop(); };
      document.addEventListener("visibilitychange", visibilityChanged);
      activityEvents.forEach((event) => root.addEventListener(event, wake, true));
      const observer = new MutationObserver(bind); observer.observe(host, { childList: true, subtree: true });
      dialog.current.showModal(); document.body.style.overflow = "hidden"; enableAudio(); spin(true);
      return () => {
        session.closed = true; ++session.token; cancelAnimationFrame(frame); clearTimeout(loadTimer); clearTimeout(hideTimer); observer.disconnect();
        activityEvents.forEach((event) => root.removeEventListener(event, wake, true));
        document.removeEventListener("visibilitychange", visibilityChanged);
        remember(); media?.pause(); finishTracker(false); resetShape();
        if (media) {
          media.removeEventListener("loadeddata", reveal); media.removeEventListener("error", mediaError); media.removeEventListener("volumechange", volumeChanged);
          ["playing", "pause", "waiting", "ended"].forEach((event) => media.removeEventListener(event, wake));
        }
        sound?.stop(); audio?.close().catch(() => {}); document.body.style.overflow = overflow;
        if (document.fullscreenElement === root) document.exitFullscreen().catch(() => {});
        if (focus?.isConnected) focus.focus();
      };
    }, [session, onClose]);
    const busy = ["loading", "assembling", "spinning", "rewinding", "celebrating", "landing", "revealing", "returning"].includes(view.phase);
    return ReactDOM.createPortal(React.createElement("dialog", { ref: dialog, className: "curator-roulette-dialog", "aria-label": "Roulette player", onCancel: (event) => { event.preventDefault(); controller.current?.close(); } },
      React.createElement("div", { ref: stage, className: "curator-roulette-stage", "data-phase": view.phase, "data-intro": view.index < 0, onKeyDownCapture: (event) => {
        if (event.key.toLowerCase() === "f" && !event.ctrlKey && !event.altKey && !event.metaKey) {
          event.preventDefault(); event.stopPropagation(); controller.current?.fullscreen();
        }
      } },
        React.createElement("div", { className: "curator-roulette-spinner", "aria-hidden": "true" },
          React.createElement("div", { className: "curator-roulette-wheel-wrap scene-card" }, React.createElement("svg", { className: "scene-card-image card-section", viewBox: "0 0 600 600" }),
            React.createElement("div", { className: "curator-roulette-aura" }, [0, 1, 2].map((i) => React.createElement("i", { key: i, style: { "--ring": i } }))),
            React.createElement("div", { className: "curator-roulette-pointer" }, React.createElement("div", { className: "curator-roulette-pointer-tip" }))) ),
        React.createElement("div", { ref: player, className: "curator-roulette-player" },
          entry && React.createElement(RouletteScene, { key: `${entry.origin.scene_id}:${entry.attempt || 0}`, entry, onNext: next, onPrevious: previous, onComplete: completed, onError: failed })),
        React.createElement("header", { className: "curator-roulette-hud" },
          React.createElement("span", null, "ROULETTE · ", laneByValue.get(session.lane).label),
          React.createElement("div", null,
            React.createElement(Button, { variant: "dark", size: "sm", "aria-pressed": view.muted, onClick: () => controller.current.mute() }, view.muted ? "Unmute" : "Mute"),
            React.createElement(libraries.Bootstrap.Dropdown, { alignRight: true, className: "curator-roulette-settings" },
              React.createElement(libraries.Bootstrap.Dropdown.Toggle, { id: "curator-roulette-settings", variant: "dark", size: "sm", "aria-label": "Roulette settings", title: "Roulette settings" }, React.createElement(FontAwesomeIcon, { icon: faCog })),
              React.createElement(libraries.Bootstrap.Dropdown.Menu, null, React.createElement(RouletteAnimationSetting, { compact: true }))),
            React.createElement(Button, { variant: "dark", size: "sm", onClick: () => controller.current.fullscreen() }, "Fullscreen"),
            React.createElement(Button, { variant: "dark", size: "sm", onClick: () => controller.current.close() }, "Exit"))),
        React.createElement("div", { className: "curator-roulette-controls" },
          React.createElement("div", { className: "curator-roulette-status", role: "status", "aria-live": "polite" },
          view.error || (view.phase === "loading" ? "Loading contenders…" : view.phase === "assembling" ? "Gathering your lane…" : view.phase === "spinning" ? "Spinning…" : view.phase === "rewinding" ? "Returning to your previous pick…" : view.phase === "celebrating" ? "Your pick" : view.phase === "landing" ? "Loading selected scene…" : view.phase === "exhausted" ? "No recommendations qualify right now." : entry?.scene?.title || "Untitled scene")),
          entry && React.createElement(RouletteActions, { key: entry.origin.scene_id, entry, disabled: busy || view.phase !== "playing", onOpen: () => controller.current.pause() }),
          React.createElement("div", { className: "curator-roulette-navigation" },
          React.createElement(Button, { variant: "dark", disabled: busy || view.index < 1, onClick: previous }, "Back"),
          React.createElement(Button, { variant: "primary", disabled: busy || view.phase === "exhausted", onClick: next }, "Next"),
          view.phase === "error" && React.createElement(Button, { variant: "dark", onClick: () => controller.current.retry() }, "Retry"),
          view.phase === "exhausted" && React.createElement(Button, { variant: "primary", onClick: () => controller.current.retry() }, "Retry")))
      )), document.body);
  }

  function CuratorPage() {
    React.useEffect(() => {
      const heartbeat = () => {
        if (document.visibilityState === "visible") {
          operation({ operation: "page_activity" }).catch(() => {});
        }
      };
      heartbeat();
      const timer = setInterval(heartbeat, 20000);
      document.addEventListener("visibilitychange", heartbeat);
      return () => {
        clearInterval(timer);
        document.removeEventListener("visibilitychange", heartbeat);
      };
    }, []);
    const history = useHistory();
    const routeLocation = useLocation();
    const [roulette, setRoulette] = React.useState(null);
    const closeRoulette = React.useCallback(() => setRoulette(null), []);
    React.useEffect(() => { setRoulette(null); }, [routeLocation.key]);
    const route = new URLSearchParams(routeLocation.search);
    const requestedView = route.get("view") || "for_you";
    const loadingComponents = Api.hooks.useLoadComponents([Api.loadableComponents.SceneCard, Api.loadableComponents.PerformerCard]);
    // "?view=<maintenance item>" (taste, feedback, backups, …) keeps working
    // as a soft alias into Manage forever — it resolves lane/currentSection
    // directly with no history.replace, so old bookmarks render identically
    // without ever rewriting the address bar to the canonical ?section= form.
    const lane = requestedView === "manage" || MAINTENANCE_ITEMS.some((item) => item.value === requestedView)
      ? "manage"
      : PRIMARY_NAV_ITEMS.some((item) => item.value === requestedView) ? requestedView : "for_you";
    const currentSection = lane === "manage"
      ? route.get("section") || (MAINTENANCE_ITEMS.some((item) => item.value === requestedView) ? requestedView : MAINTENANCE_ITEMS[0].value)
      : null;
    // Curate has its own sections on the same ?section= param. Resolve against
    // Curate's own list so a section left over from Manage cannot leak in.
    const curateSection = lane === "curate"
      ? (CURATE_SECTIONS.some((item) => item.value === route.get("section"))
        ? route.get("section")
        : CURATE_SECTIONS[0].value)
      : null;
    const [slate, setSlate] = React.useState(null);
    const [lastSyncAtMs, setLastSyncAtMs] = React.useState(null);
    React.useEffect(() => {
      let active = true;
      operation({ operation: "health" }).then(
        (result) => active && setLastSyncAtMs(result.last_sync_at_ms || null),
        () => {}
      );
      return () => { active = false; };
    }, []);
    const [error, setError] = React.useState("");
    const [loading, setLoading] = React.useState(true);
    const [rotatingLane, setRotatingLane] = React.useState(null);
    const [rotationMessage, setRotationMessage] = React.useState("");
    const [refreshKey, setRefreshKey] = React.useState(0);
    const [page, setPage] = useUrlPage(laneByValue.has(lane) ? `page_${lane}` : "page_for_you");
    const [configReady, setConfigReady] = React.useState(false);
    const [moods, setMoods] = React.useState([]);
    const [moodID, setMoodID] = React.useState(readMoodID);
    const togetherMode = Boolean(moodID);
    function selectMood(next) {
      writeMoodID(next);
      clearSlateCache();
      setMoodID(next);
      setSlate(null);
      setFollowUps([]);
      setRotatingLane(null);
      setLoading(true);
      setPage(1);
      setRefreshKey((value) => value + 1);
    }
    function applyMoods(next, reset = true) {
      setMoods(next);
      const selected = readMoodID();
      const valid = next.some((mood) => mood.id === selected) ? selected : "";
      if (reset || valid !== moodID) selectMood(valid);
    }
    const restoredSlateFilters = React.useMemo(readEndlessRecommendationFilters, []);
    const initialSlateFilters = React.useMemo(() => restoredSlateFilters?.filters || defaultFilters("recommendations"), []);
    const [filtersOpen, setFiltersOpen] = React.useState(false);
    const [filterIncludeTags, setFilterIncludeTags] = React.useState(initialSlateFilters.includeTags || []);
    const [filterExcludeTags, setFilterExcludeTags] = React.useState(initialSlateFilters.excludeTags || []);
    const [filterPerformers, setFilterPerformers] = React.useState(initialSlateFilters.performers || []);
    const [filterStudios, setFilterStudios] = React.useState(initialSlateFilters.studios || []);
    const [filterGender, setFilterGender] = React.useState(initialSlateFilters.gender || "");
    const slateFilters = { includeTags: filterIncludeTags, excludeTags: filterExcludeTags, performers: filterPerformers, studios: filterStudios, gender: filterGender };
    const activeSlateFilterCount = filterIncludeTags.length + filterExcludeTags.length + filterPerformers.length + filterStudios.length + (filterGender ? 1 : 0);
    function applySavedSlateFilters(value, resetPage = true) {
      setFilterIncludeTags(value.includeTags || []);
      setFilterExcludeTags(value.excludeTags || []);
      setFilterPerformers(value.performers || []);
      setFilterStudios(value.studios || []);
      setFilterGender(value.gender || "");
      if (resetPage) setPage(1);
    }
    const [diversityEnabled, setDiversityEnabled] = React.useState(null);
    const [diversitySaving, setDiversitySaving] = React.useState(false);
    const [endlessEnabled, setEndlessEnabled] = React.useState(false);
    const [recommendationView, setRecommendationView] = React.useState(readRecommendationView);
    function changeRecommendationView(value) {
      setRecommendationView(value);
      writeRecommendationView(value);
      if (endlessEnabled) setPage(1);
    }
    const endless = endlessEnabled;
    function applyDisplayConfig(config) {
      setEndlessEnabled(Boolean(config.recommendation_endless_scroll));
      clearSlateCache();
      setPage(1);
      setRefreshKey((value) => value + 1);
    }
    const [followUps, setFollowUps] = React.useState([]);
    const [theme, setTheme] = React.useState(() => {
      try {
        return window.localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
      } catch {
        return "dark";
      }
    });
    function toggleTheme() {
      setTheme((current) => {
        const next = current === "light" ? "dark" : "light";
        try {
          window.localStorage.setItem(THEME_STORAGE_KEY, next);
        } catch {
          // localStorage can be unavailable (private browsing); the toggle
          // still works for the session, it just won't persist.
        }
        return next;
      });
    }
    const [cardSize, setCardSize] = React.useState(() => {
      try {
        const stored = Number(window.localStorage.getItem(CARD_SIZE_STORAGE_KEY));
        return stored >= CARD_SIZE_MIN && stored <= CARD_SIZE_MAX ? stored : CARD_SIZE_DEFAULT;
      } catch {
        return CARD_SIZE_DEFAULT;
      }
    });
    function changeCardSize(value) {
      setCardSize(value);
      try {
        window.localStorage.setItem(CARD_SIZE_STORAGE_KEY, String(value));
      } catch {
        // localStorage can be unavailable (private browsing); the change
        // still works for the session, it just won't persist.
      }
    }

    React.useEffect(() => {
      setFollowUps([]);
      setRotatingLane(null);
      setRotationMessage("");
    }, [lane]);

    React.useEffect(() => {
      if (!laneByValue.has(lane) || !rotateOnRepeatedReload(lane, page)) return;
      advanceRotation(lane);
      setRotatingLane(lane);
    }, []);

    React.useEffect(() => {
      let active = true;
      operation({ operation: "get_config" }).then(
        async (data) => {
          if (!active) return;
          if (cachedConfigUpdatedAtMs !== data.updated_at_ms) clearSlateCache();
          try { await loadFilterPresets(data.config.saved_filters || {}); }
          catch (failure) { if (active) setError(`Could not load saved filters: ${failure.message}`); return; }
          if (!active) return;
          if (restoredSlateFilters?.configUpdatedAtMs !== data.updated_at_ms) applySavedSlateFilters(defaultFilters("recommendations"), false);
          cachedConfigUpdatedAtMs = data.updated_at_ms;
          setDiversityEnabled(Boolean(data.config.diversity_enabled));
          setEndlessEnabled(Boolean(data.config.recommendation_endless_scroll));
          applyMoods(data.config.moods || [], false);
          persistSlateCache();
          setConfigReady(true);
        },
        (failure) => active && setError(`Could not load saved filters: ${failure.message}`)
      );
      return () => { active = false; };
    }, []);

    React.useEffect(() => {
      let active = true;
      if (!configReady) return () => { active = false; };
      if (!laneByValue.has(lane)) {
        setSlate(null);
        setLoading(false);
        setError("");
        return () => { active = false; };
      }
      rotateDay();
      const cached = activeSlateFilterCount === 0 && !togetherMode ? slateCache.get(slateKey(lane, page)) : null;
      if (rotatingLane !== lane) setSlate(cached || null);
      setLoading(!cached);
      setError("");
      loadSlate(lane, page, false, slateFilters).then(
        (data) => {
          if (!active) return;
          if (data.mood_id !== undefined && data.mood_id !== moodID) { selectMood(data.mood_id); return; }
          if (data.moods) setMoods(data.moods);
          setSlate(data);
          if (rotatingLane === lane) {
            setRotationMessage(data.items.length ? "Fresh set ready" : "No more scenes in this lane");
            setRotatingLane(null);
          }
          setLoading(false);
        },
        (failure) => {
          if (!active) return;
          setError(failure.message);
          if (rotatingLane === lane) setSlate(null);
          setRotatingLane(null);
          setLoading(false);
        }
      );
      return () => {
        active = false;
      };
    }, [lane, page, refreshKey, configReady, moodID, filterIncludeTags, filterExcludeTags, filterPerformers, filterStudios, filterGender]);
    React.useEffect(() => {
      if (!laneByValue.has(lane)) return;
      let timer;
      function schedule() {
        const now = new Date();
        timer = setTimeout(() => {
          if (rotateDay()) {
            setPage(1);
            setRefreshKey((value) => value + 1);
          }
          schedule();
        }, new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1) - now + 100);
      }
      schedule();
      return () => clearTimeout(timer);
    }, [lane, page]);
    React.useEffect(() => {
      if (slate?.page === page) {
        const last = Math.max(1, Math.ceil(slate.total / slate.page_size));
        if (page > last) setPage(last, { replace: true });
      }
    }, [slate, page]);

    const laneOption = NAV_ITEMS.find((option) => option.value === lane);

    const ids = laneByValue.has(lane) ? slate?.items.map((item) => item.scene_id) || [] : [];
    const scenesQuery = GQL.useFindScenesQuery({
      variables: {
        filter: { per_page: Math.max(1, ids.length) },
        scene_ids: ids.map(Number),
      },
      skip: ids.length === 0,
    });
    const scenes = new Map(
      (scenesQuery.data?.findScenes?.scenes || []).map((scene) => [String(scene.id), scene])
    );
    // A scene deleted in Stash lingers in the model until the next sync; hide it rather than
    // draw a placeholder card. Only once the lookup resolved, or everything looks deleted.
    const resolved = !scenesQuery.loading && !scenesQuery.error && Boolean(scenesQuery.data);
    const visibleItems = resolved
      ? (slate?.items || []).filter((item) => scenes.has(String(item.scene_id)))
      : slate?.items || [];
    useCuratorActivity("recommendations", loading || loadingComponents || scenesQuery.loading, loading ? `Preparing ${laneOption?.label || "recommendations"}…` : "Loading scene cards…");
    function remove(sceneId) {
      clearSlateCache();
      const excluded = laneExclusions.get(lane) || new Set();
      excluded.add(sceneId);
      laneExclusions.set(lane, excluded);
      persistSlateCache();
      setLoading(true);
      setRefreshKey((value) => value + 1);
    }
    function showFollowUp(followUp) {
      setFollowUps((current) => [...current.filter((item) => item.scene_id !== followUp.scene_id), followUp]);
    }
    function refresh() {
      clearSlateCache();
      laneExclusions.clear();
      setPage(1);
      setRefreshKey((value) => value + 1);
    }
    function showSomethingElse() {
      advanceRotation(lane);
      try { sessionStorage.removeItem(RELOAD_ROTATION_KEY); } catch (_) { /* Storage may be unavailable. */ }
      setRotatingLane(lane);
      setRotationMessage("");
      setPage(1);
      setRefreshKey((value) => value + 1);
    }
    function openView(view) {
      if (view === lane) return;
      setFollowUps([]);
      route.set("view", view);
      // ?section= belongs to whichever sectioned view set it; switching views
      // must not carry Manage's section into Curate or the other way round.
      for (const param of ["performer", "label", "id", "type", "section"]) route.delete(param);
      history.push({ pathname: routeLocation.pathname, search: route.toString() });
    }
    function openManage(section) {
      if (lane === "manage" && section === currentSection) return;
      setFollowUps([]);
      route.set("view", "manage");
      if (section) route.set("section", section); else route.delete("section");
      for (const param of ["performer", "label", "id", "type"]) route.delete(param);
      history.push({ pathname: routeLocation.pathname, search: route.toString() });
    }
    function openCurate(section, extra) {
      if (lane === "curate" && section === curateSection && (!extra || !extra.sentTag)) return;
      setFollowUps([]);
      route.set("view", "curate");
      if (section) route.set("section", section); else route.delete("section");
      // The Impact view's "Fix in Tag sentiment" jumps pre-seed the panel's
      // search via ?sent_tag=; plain section switches drop it again.
      if (extra && extra.sentTag) route.set("sent_tag", extra.sentTag); else route.delete("sent_tag");
      for (const param of ["performer", "label", "id", "type"]) route.delete(param);
      history.push({ pathname: routeLocation.pathname, search: route.toString() });
    }
    async function toggleDiversity() {
      const nextEnabled = !diversityEnabled;
      setDiversitySaving(true);
      setError("");
      try {
        // Same replace-semantics guard as saveField: spread the stored map so
        // toggling variety cannot erase the other plugins.settings keys.
        const raw = await getPluginSettings();
        await configurePlugin({ ...raw, diversityDisabled: !nextEnabled });
        const data = await operation({ operation: "get_config" });
        clearSlateCache();
        cachedConfigUpdatedAtMs = data.updated_at_ms;
        setDiversityEnabled(Boolean(data.config.diversity_enabled));
        persistSlateCache();
        setPage(1);
        setLoading(true);
        setRefreshKey((value) => value + 1);
      } catch (failure) {
        setError(failure.message);
      } finally {
        setDiversitySaving(false);
      }
    }

    return React.createElement(
      "main",
      { className: "curator-page container-fluid", "data-theme": theme, style: { "--curator-card-min-width": `${cardSize}rem` } },
      roulette && React.createElement(RoulettePlayer, { session: roulette, onClose: closeRoulette }),
      React.createElement(
        "header",
        { className: "curator-header" },
        React.createElement("div", { className: "curator-brand", title: "Navigate your library, guided by your taste." }, React.createElement("span", { className: "curator-brand-mark", "aria-hidden": "true" }, React.createElement(FontAwesomeIcon, { icon: faCompass })), React.createElement("h1", null, "Curator")),
        React.createElement(
          "div",
          { className: "curator-navigation" },
          React.createElement(
            Nav,
            { variant: "tabs", role: "tablist", className: "curator-tabs" },
            TOP_NAV_ITEMS.map((option) => {
              const active = option.value === "recommendations" ? laneByValue.has(lane)
                : option.value === "find" ? FIND_SECTION_VALUES.has(lane)
                : lane === option.value;
              const onClick = option.value === "recommendations"
                ? () => { if (!laneByValue.has(lane)) openView("for_you"); }
                : option.value === "find"
                  ? () => { if (!FIND_SECTION_VALUES.has(lane)) openView(FIND_SECTIONS[0].value); }
                  : () => openView(option.value);
              return React.createElement(
                Nav.Link,
                { key: option.value, as: "button", className: `curator-nav-${option.value}`, active, onClick, role: "tab", title: option.description, "aria-label": `${option.label}: ${option.description}`, "aria-selected": active },
                React.createElement(FontAwesomeIcon, { icon: option.icon }),
                React.createElement("span", null, option.label)
              );
            })
          )
        ),
        React.createElement(CuratorControls, { onRefresh: refresh, theme, onToggleTheme: toggleTheme, cardSize, onChangeCardSize: changeCardSize, onOpenManage: () => openManage(currentSection || MAINTENANCE_ITEMS[0].value), manageDescription: MANAGE_NAV_ITEM.description })
      ),
      laneByValue.has(lane) && React.createElement(
        "div",
        { className: "curator-lane-switcher", role: "tablist", "aria-label": "Recommendation lane" },
        LANES.map((laneItem) => React.createElement(
          "button",
          {
            key: laneItem.value,
            type: "button",
            className: "curator-lane-card",
            style: { "--lc": `var(--curator-hue-${laneItem.value})` },
            "aria-pressed": lane === laneItem.value,
            onClick: () => openView(laneItem.value),
            onMouseEnter: () => prefetchLane(laneItem.value),
            onFocus: () => prefetchLane(laneItem.value),
            title: laneItem.description,
          },
          React.createElement("span", { className: "curator-lane-card-icon" }, React.createElement(FontAwesomeIcon, { icon: laneItem.icon })),
          React.createElement("span", { className: "curator-lane-card-name" }, laneItem.label),
          React.createElement("span", { className: "curator-lane-card-desc" }, laneItem.description)
        ))
      ),
      FIND_SECTION_VALUES.has(lane) && React.createElement(
        "div",
        { className: "curator-find-switcher", role: "tablist", "aria-label": "Find content" },
        FIND_SECTIONS.map((section) => React.createElement(
          "button",
          {
            key: section.value,
            type: "button",
            className: "curator-lane-card",
            style: { "--lc": `var(--curator-hue-${section.value})` },
            "aria-pressed": lane === section.value,
            "aria-label": section.label,
            onClick: () => openView(section.value),
            title: section.description,
          },
          React.createElement("span", { className: "curator-lane-card-icon" }, React.createElement(FontAwesomeIcon, { icon: section.icon })),
          React.createElement("span", { className: "curator-lane-card-name" }, section.label),
          React.createElement("span", { className: "curator-lane-card-desc" }, section.description)
        ))
      ),
      laneOption && lane !== "curate" && React.createElement(
        "div",
        { className: "curator-view-guidance" },
        React.createElement(
          "div",
          { className: "curator-view-copy" },
          React.createElement("h1", null, laneByValue.has(lane) ? "Recommendations" : laneOption.label),
          React.createElement("p", null, laneOption.description),
          laneByValue.has(lane) && React.createElement(
            "details",
            { className: "curator-view-help" },
            React.createElement(
              "summary",
              { "aria-label": "What do Appeal and Rank mean?", title: "What do Appeal and Rank mean?" },
              React.createElement(FontAwesomeIcon, { icon: faCircleQuestion })
            ),
            React.createElement("p", null, "Appeal is the model's estimate of how much you'll like a scene, on a −1..1 scale. Rank in this lane is relative to the lane's best — 1.00 is the top of the lane, so it measures ordering utility, not probability. A scene can rank high while its appeal is moderate: rank includes recency and cooldown, appeal is how much you'd like it now.")
          ),
          laneByValue.has(lane) && slate && React.createElement(
            "p",
            { className: "curator-view-stats", role: "status" },
            `${slate.total} in rotation`,
            lastSyncAtMs && ` · Model refreshed ${formatTimeAgo(lastSyncAtMs)}`,
            rotationMessage && ` · ${rotationMessage}`
          )
        ),
        React.createElement(
          "div",
          { className: "curator-view-actions" },
          laneByValue.has(lane) && slate && React.createElement(Button, { size: "sm", variant: "primary", disabled: loading || !resolved || !visibleItems.length || slate.lane !== lane, onClick: () => { try { startLanePlaylist(slate, visibleItems, slateFilters, history); } catch (failure) { setError(failure.message); } }, title: "Play these recommendations and keep fetching more from this lane" }, React.createElement(FontAwesomeIcon, { icon: faPlay }), " Play lane"),
          laneByValue.has(lane) && slate && React.createElement(Button, { className: "curator-roulette-launch", size: "sm", variant: "secondary", disabled: loading || !resolved || !visibleItems.length || slate.lane !== lane, onClick: () => setRoulette(createRouletteSession(slate, visibleItems, slateFilters, scenes)), title: "Spin for a recommendation from this lane" }, React.createElement(FontAwesomeIcon, { icon: faDice, "aria-hidden": "true" }), " Roulette"),
          laneByValue.has(lane) && React.createElement(MoodMenu, { moods, moodID, disabled: !configReady, onSelect: selectMood, onManage: () => openManage("settings") }),
          laneByValue.has(lane) && diversityEnabled !== null && React.createElement(
            Button,
            {
              className: "curator-diversity-toggle",
              size: "sm",
              variant: diversityEnabled ? "primary" : "secondary",
              disabled: diversitySaving,
              "aria-pressed": diversityEnabled,
              "aria-label": diversityEnabled ? "Disable recommendation variety" : "Enable recommendation variety",
              title: diversityEnabled ? "Switch to the model's score-first order" : "Vary performers, studios, and similar content",
              onClick: toggleDiversity,
            },
            React.createElement(FontAwesomeIcon, { icon: faBalanceScale }),
            diversityEnabled ? " Balanced" : " Score-first"
          ),
          laneByValue.has(lane) && slate && React.createElement(Button, { className: "curator-rotate-button", size: "sm", variant: "secondary", disabled: loading || !slate.items.length, onClick: showSomethingElse, "aria-busy": rotatingLane === lane, title: "Show me something else", "aria-label": "Show me something else" }, React.createElement(FontAwesomeIcon, { icon: faSync, className: rotatingLane === lane ? "curator-rotate-icon-spinning" : "curator-rotate-icon" }), " ", rotatingLane === lane ? "Finding…" : "New picks"),
          laneByValue.has(lane) && React.createElement(RecommendationViewSelector, { view: recommendationView, onChange: changeRecommendationView }),
          laneByValue.has(lane) && React.createElement(Button, { size: "sm", variant: filtersOpen ? "primary" : "secondary", "aria-expanded": filtersOpen, onClick: () => setFiltersOpen((value) => !value) }, React.createElement(FontAwesomeIcon, { icon: faFilter }), " Filters", activeSlateFilterCount > 0 && React.createElement("span", { className: "curator-filter-count" }, activeSlateFilterCount)),
          configReady && laneByValue.has(lane) && React.createElement(SavedFilters, { scope: "recommendations", current: { includeTags: filterIncludeTags, excludeTags: filterExcludeTags, performers: filterPerformers, studios: filterStudios, gender: filterGender }, onApply: applySavedSlateFilters })
        )
      ),
      laneByValue.has(lane) && filtersOpen && React.createElement(FilterBar, {
        variant: "recommendations",
        entityType: "scene",
        includeTags: filterIncludeTags, onIncludeTagsChange: (value) => setFilterIncludeTags(value),
        excludeTags: filterExcludeTags, onExcludeTagsChange: (value) => setFilterExcludeTags(value),
        performers: filterPerformers, onPerformersChange: (value) => setFilterPerformers(value),
        studios: filterStudios, onStudiosChange: (value) => setFilterStudios(value),
        gender: filterGender, onGenderChange: (event) => setFilterGender(event.target.value),
        onApply: () => { setPage(1); setFiltersOpen(false); },
      }),
      followUps.map((followUp) => React.createElement(TagSentimentFollowUp, { key: followUp.scene_id, followUp, onDismiss: () => setFollowUps((current) => current.filter((item) => item.scene_id !== followUp.scene_id)) })),
      configReady && lane === "similar" && !loadingComponents && React.createElement(SimilarityPanel, { endless: endlessEnabled }),
      lane === "curate" && React.createElement(CuratePanel, { section: curateSection, onSelectSection: openCurate, sentimentQuery: route.get("sent_tag") || "" }),
      configReady && lane === "expand" && React.createElement(ExpandPanel, { key: "expand", endless: endlessEnabled }),
      configReady && lane === "hunt" && React.createElement(ExpandPanel, { key: "hunt", initialType: "hunt", huntOnly: true, endless: endlessEnabled }),
      // Prune renders scene cards directly, same as SimilarityPanel above, so
      // it keeps its pre-existing !loadingComponents gate even though it now
      // mounts inside ManagePanel rather than as its own top-level branch.
      lane === "manage" && (currentSection !== "prune" || !loadingComponents) && React.createElement(ManagePanel, { section: currentSection, onSelectSection: openManage, diversityEnabled, diversitySaving, onToggleDiversity: toggleDiversity, onMoodsSaved: applyMoods, onConfigSaved: applyDisplayConfig }),
      error && React.createElement("div", { className: "alert alert-danger" }, error, React.createElement("p", null, "Run “Sync and build recommendations” from Tasks if no model exists yet."), React.createElement(Button, { size: "sm", variant: "primary", onClick: () => runTask("Sync and build recommendations") }, React.createElement(FontAwesomeIcon, { icon: faSync }), " Sync and build now")),
      laneByValue.has(lane) && scenesQuery.error && React.createElement("div", { className: "alert alert-danger" }, scenesQuery.error.message),
      laneByValue.has(lane) && loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, rotatingLane === lane ? "Finding another set of qualified scenes…" : "Loading recommendations…")),
      laneByValue.has(lane) && slate && !loading &&
        React.createElement(
          React.Fragment,
          null,
          visibleItems.length === 0 && React.createElement("div", { className: "alert alert-info" }, React.createElement("p", null, togetherMode ? "No recommendations match Mood mode in this lane." : "Nothing qualifies for this lane right now."), !togetherMode && React.createElement(Button, { size: "sm", variant: "secondary", onClick: () => runTask("Rebuild recommendation model") }, React.createElement(FontAwesomeIcon, { icon: faWrench }), " Rebuild model")),
          endless
            ? resolved && React.createElement(EndlessRecommendations, { key: `${slate.impression_id}:${recommendationView}`, slate, visibleItems, scenes, lane, filters: slateFilters, thumbnails: recommendationView === "thumbnails", cards: recommendationView === "cards", onRestart: refresh, onRemove: remove, onThumbDown: showFollowUp })
            : recommendationView !== "cards"
              ? React.createElement(RecommendationWall, { visibleItems, scenes, lane, thumbnails: recommendationView === "thumbnails" })
            : React.createElement(
              "section",
              { className: "curator-grid curator-grid-enter", role: "tabpanel", "aria-live": "polite" },
              visibleItems.map((item) => React.createElement(RecommendationCard, { key: `${item.impression_id}:${item.scene_id}`, item, scene: scenes.get(String(item.scene_id)), slate, onRemove: remove, onThumbDown: showFollowUp }))
            ),
          !endless && React.createElement(Pager, { page, total: slate.total, pageSize: slate.page_size, hasMore: slate.has_more, loading, onPage: setPage, label: `${laneOption.label} pages` })
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
        clearSlateCache(true);
        scheduleModelUpdate();
        schedulePlaySync();
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

  // ponytail: getPlayer() resolves one registered Video.js wrapper, which goes stale when Stash
  // rebuilds the player for a scene. Bind the media element itself and re-bind when it changes,
  // so a replaced player cannot silently record a session that observed nothing.
  function mediaElement() {
    const player = Api.utils.InteractiveUtils.getPlayer();
    const root = player && !player.isDisposed?.() ? player.el?.() : null;
    return root?.querySelector("video") || document.querySelector(".video-js video, video.vjs-tech");
  }

  function attachPlayer(pathname, embedded = null) {
    const match = pathname.match(/^\/scenes\/(\d+)/);
    if (!match && !embedded) {
      finishTracker(false);
      return;
    }
    const sceneId = embedded ? String(embedded.sceneId) : match[1];
    if (tracker?.value.scene_id === sceneId) return;
    finishTracker(false);
    let origin = null;
    try {
      origin = JSON.parse(sessionStorage.getItem(ORIGIN_KEY) || "null");
    } catch (_) {}
    if (embedded) origin = embedded.origin;
    if (origin?.scene_id !== sceneId) origin = null;
    if (origin && !embedded) sessionStorage.removeItem(ORIGIN_KEY);
    const value = {
      session_id: uuid(),
      scene_id: sceneId,
      started_at_ms: Date.now(),
      active_seconds: 0,
      origin: origin ? "curator" : "stash",
      source_route: pathname,
      start_position_seconds: 0,
      maximum_position_seconds: 0,
      final_position_seconds: 0,
      played_ranges: [],
      seek_destinations_seconds: [],
      ...(origin || {}),
    };
    let media = null;
    let playing = false;
    let positioned = false;
    let lastWall = performance.now();
    let rangeStart = null;
    function position() {
      return Number(media?.currentTime || 0);
    }
    function tick() {
      const now = performance.now();
      if (playing) value.active_seconds += Math.min(5, Math.max(0, (now - lastWall) / 1000));
      lastWall = now;
      // A replaced or removed element reports nothing; keep the last position we did observe.
      if (!media) return;
      const current = position();
      // Stash resumes part-way into a scene, so the opening position is only known once the
      // media reports one. Until then a zero would understate everything watched before it.
      if (!positioned && current > 0) {
        positioned = true;
        value.start_position_seconds = current;
      }
      value.final_position_seconds = current;
      value.maximum_position_seconds = Math.max(value.maximum_position_seconds, current);
    }
    function closeRange() {
      if (rangeStart === null) return;
      const end = Math.max(rangeStart, position());
      value.played_ranges.push({ start_seconds: rangeStart, end_seconds: end });
      rangeStart = null;
    }
    const handlers = {
      play: () => { lastWall = performance.now(); },
      playing: () => { tick(); playing = true; rangeStart ??= position(); },
      waiting: () => { tick(); playing = false; closeRange(); },
      pause: () => { tick(); playing = false; closeRange(); },
      timeupdate: tick,
      seeking: () => { tick(); closeRange(); },
      seeked: () => { value.seek_destinations_seconds.push(position()); if (playing) rangeStart = position(); },
      ended: () => finishTracker(true),
    };
    function unbind() {
      if (!media) return;
      Object.entries(handlers).forEach(([event, handler]) => media.removeEventListener(event, handler));
      media = null;
    }
    function bind(element) {
      if (media === element) return;
      tick();
      closeRange();
      playing = false;
      unbind();
      media = element;
      Object.entries(handlers).forEach(([event, handler]) => media.addEventListener(event, handler));
      if (!media.paused) handlers.playing();
      else tick();
    }
    // Playback can begin long after navigation, and the element can be replaced mid-scene.
    const watch = setInterval(() => {
      if (location.pathname !== pathname) return;
      const element = embedded ? embedded.root.querySelector("video") : mediaElement();
      if (element && element.isConnected) bind(element);
      else if (media && !media.isConnected) { tick(); closeRange(); playing = false; unbind(); }
    }, 500);
    tracker = {
      value,
      tick,
      closeRange,
      detach: () => {
        clearInterval(watch);
        unbind();
      },
    };
    const element = embedded ? embedded.root.querySelector("video") : mediaElement();
    if (element?.isConnected) bind(element);
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
  Api.patch.instead("SceneCard.Details", function (props, ...args) {
    const next = args.pop();
    const result = next.call(this, props, ...args);
    if (props.curatorAppeal === undefined) return result;
    // Themes may replace the popover slot; Details keeps the native metadata.
    return React.createElement(React.Fragment, null, React.createElement("div", { className: "curator-card-affinity" }, React.createElement(EvidenceScore, {
      evidenceContent: null,
      scoreHeadline: "Appeal",
      scoreHeadlineValue: formatAppealValue(props.curatorAppeal),
      scoreHeadlineBar: scoreBar(props.curatorAppeal, true),
    })), result);
  });

  Api.patch.after("MainNavBar.MenuItems", function (props, ...args) {
    const result = args[args.length - 1];
    if (!React.isValidElement(result)) return result;
    const children = React.Children.toArray(result.props.children);
    if (!children.some((child) => child?.type === CuratorNavItem)) {
      children.push(React.createElement(CuratorNavItem, { key: "stash-curator" }));
    }
    return React.cloneElement(result, {}, children);
  });
  // Circular gauge around the affinity value (replaces the flat bar). The ring
  // fill tracks |affinity| and the value is tinted by sign.
  function CuratorAffinityGauge({ value, detail, confidenceLabel, label = "affinity" }) {
    const radius = 15;
    const circumference = 2 * Math.PI * radius;
    const magnitude = value === null ? 0 : Math.min(1, Math.abs(value));
    const offset = circumference * (1 - magnitude);
    const sign = value === null || value === 0 ? "neutral" : value < 0 ? "negative" : "positive";
    const valueLabel = value === null ? "—" : formatAppealValue(value);
    const color = sign === "positive" ? "#5cc19c" : sign === "negative" ? "#e0645c" : "#adb5bd";
    const description = `Curator ${label} ${valueLabel}${detail ? `. ${detail}` : ""}`;
    return React.createElement("span", { className: `curator-affinity-gauge curator-affinity-${sign}`, title: description, "aria-label": description, tabIndex: detail ? 0 : undefined },
      React.createElement("svg", { className: "curator-affinity-gauge-ring", viewBox: "0 0 36 36", "aria-hidden": "true" },
        React.createElement("circle", { cx: 18, cy: 18, r: radius, fill: "none", stroke: "rgba(127,127,127,0.25)", strokeWidth: 3 }),
        React.createElement("circle", { cx: 18, cy: 18, r: radius, fill: "none", stroke: color, strokeWidth: 3, strokeDasharray: String(circumference), strokeDashoffset: String(offset), strokeLinecap: "round", transform: "rotate(-90 18 18)" })
      ),
      confidenceLabel ? React.createElement("span", { className: "curator-affinity-readout" },
        React.createElement("span", { className: "curator-affinity-gauge-value" }, valueLabel),
        React.createElement("small", { className: "curator-affinity-confidence" }, confidenceLabel)
      ) : React.createElement("span", { className: "curator-affinity-gauge-value" }, valueLabel)
    );
  }
  function CuratorContextControls({ type, id, label, details, className = "" }) {
    if (type === "scene") return React.createElement(CuratorSceneAffinityPill, { id, label, score: details?.score, className: className || "curator-scene-page-pill" });
    const raw = type === "scene" ? details?.score?.appeal : details?.affinity;
    const noEvidence = type === "performer" && details !== null && details !== undefined && raw == null;
    const value = typeof raw === "number" ? raw : noEvidence ? 0 : null;
    const confidenceLabel = type === "performer" && details ? noEvidence ? "No evidence" : typeof details.confidence === "number" ? `Confidence ${Math.round(clamp01(details.confidence) * 100)}%` : "Confidence unavailable" : null;
    const confidence = confidenceLabel ? ` ${confidenceLabel}.` : "";
    const evidence = details?.affinity_details;
    const affinityDetail = type === "performer" && value !== null ? noEvidence ? "No evidence yet; contributes zero to recommendations. This is not a learned neutral preference." : `Combined performer preference used in recommendations.${evidence ? ` Scene evidence ${formatAppealValue(evidence.learned)}; Favorite and rating ${formatAppealValue(evidence.prior)}; Similar performers ${formatAppealValue(evidence.similarity || 0)} (inferred).` : ""}${confidence}` : null;
    const query = new URLSearchParams({ view: "similar", type, id: String(id), label: label || "" });
    return React.createElement("div", { className: `curator-context-group${type === "performer" ? " curator-context-group-performer" : ""}${className ? ` ${className}` : ""}`, role: "group", "aria-label": "Curator actions", onClick: (event) => event.stopPropagation() },
        type === "performer" && React.createElement("span", { className: "curator-context-brand", title: "Curator", "aria-hidden": true }, React.createElement(FontAwesomeIcon, { icon: faCompass })),
        type === "performer" && React.createElement(CuratorAffinityGauge, { value, detail: affinityDetail, confidenceLabel }),
        React.createElement(NavLink, { className: "curator-context-button curator-context-button-similar", to: `/plugins/stash-curator?${query}`, title: `Find similar ${type}s with Curator`, "aria-label": `Find similar ${type}s with Curator` }, React.createElement(FontAwesomeIcon, { icon: faClone })),
        type === "performer" && React.createElement(PerformerHuntLink, { performer: { id, name: label }, className: "curator-context-button curator-context-button-hunt" }),
        type !== "performer" && React.createElement(CuratorAffinityGauge, { value, detail: affinityDetail })
    );
  }
  function CuratorContextLink({ type, id, label, scene }) {
    const [details, setDetails] = React.useState(null);
    const [error, setError] = React.useState(false);
    React.useEffect(() => {
      let active = true;
      setDetails(null);
      setError(false);
      operation({ operation: "get_inspector_entity", entity_type: type, entity_id: String(id), include_similar: false, include_evidence: type === "performer" })
        .then((data) => { if (active) setDetails(data); })
        .catch(() => { if (active) setError(true); });
      return () => { active = false; };
    }, [type, id]);
    return React.createElement(CuratorEntityPanel, { type, id, label, details, error, scene });
  }
  function CuratorEntityPanel({ type, id, label, details, error, scene }) {
    const [host, setHost] = React.useState(null);
    React.useEffect(() => {
      const anchor = document.querySelector(type === "scene" ? ".scene-tabs .scene-toolbar" : "#performer-page .performer-head .quality-group");
      const page = document.querySelector(type === "scene" ? "#scene-page" : "#performer-page");
      if (!anchor && !page) return;
      const container = document.createElement("div");
      container.className = "curator-entity-panel-host";
      const toolbarGroup = type === "scene" ? anchor?.querySelector(".scene-toolbar-group:last-child") || anchor : anchor;
      function position() {
        const inline = toolbarGroup && document.body.dataset.curatorDetailPageControls === "small" && !container.querySelector(".curator-entity-panel")?.open;
        container.classList.toggle("curator-entity-panel-inline", !!inline);
        if (inline) toolbarGroup.append(container);
        else if (anchor) anchor.after(container);
        else page.append(container);
      }
      position();
      const observer = new MutationObserver(position);
      observer.observe(document.body, { attributes: true, attributeFilter: ["data-curator-detail-page-controls"] });
      container.addEventListener("toggle", position, true);
      setHost(container);
      return () => {
        observer.disconnect();
        container.removeEventListener("toggle", position, true);
        container.remove();
      };
    }, [type, id]);
    return host ? ReactDOM.createPortal(React.createElement(CuratorEntityPanelContent, { type, id, label, details, error, scene }), host) : null;
  }
  function CuratorEntityPanelContent({ type, id, label, details, error, scene }) {
    const performer = type === "performer";
    const score = details?.score;
    const contributions = details?.affinity_details;
    const confidence = performer ? details?.confidence : score?.confidence;
    const value = performer ? details?.affinity : score?.appeal;
    const tiles = performer ? [
      ["Affinity", value, "Combined performer preference; a signed score, not a percentage."],
      ["Scene evidence", contributions?.learned, "Learned from their scenes, weighted by confidence."],
      ["Favorite & rating", contributions?.prior, "Your explicit performer preferences."],
      ["Similar performers", contributions?.similarity, "Inferred from performers with similar profiles."],
    ] : [
      ["Appeal", value, "Long-term preference on a -1 to +1 scale."],
      ["Current Fit", score?.current_fit, "Suitability now, including cooldown and recent repetition."],
      ["Direct history", score?.direct_confidence > 0 ? score.direct_appeal : null, score?.direct_confidence > 0 ? "Preference evidence from this scene's own history." : "No direct history evidence yet."],
    ];
    return React.createElement("details", { className: "curator-entity-panel", "aria-label": "Curator affinity details" },
      React.createElement("summary", { className: "curator-entity-summary" },
        React.createElement(CuratorContextControls, { type, id, label, details, className: "curator-entity-actions" }),
        (error || !details) && React.createElement("small", null, error ? "Unavailable" : "Loading…")
      ),
      error ? React.createElement("p", { role: "alert" }, "Curator details could not be loaded. Check that a recommendation model is available, then reload this page.")
        : !details ? React.createElement("p", { role: "status" }, "Loading Curator details…")
        : React.createElement(React.Fragment, null,
          React.createElement("div", { className: "curator-entity-tiles" },
            ...tiles.map(([label, number, description]) => React.createElement("div", { key: label, className: "curator-entity-tile" },
              React.createElement("span", null, label),
              React.createElement("strong", { className: Number.isFinite(number) ? number > 0 ? "curator-entity-positive" : number < 0 ? "curator-entity-negative" : "" : "" }, Number.isFinite(number) ? formatAppealValue(number) : "—"),
              React.createElement("small", null, description)
            )),
            React.createElement("div", { className: "curator-entity-tile" }, React.createElement("span", null, "Confidence"), React.createElement("strong", null, Number.isFinite(confidence) ? `${Math.round(clamp01(confidence) * 100)}%` : "—"), React.createElement("small", null, "Strength of evidence, not a probability of enjoyment."))
          ),
          value == null && React.createElement("p", null, "No preference evidence yet. This is different from a learned neutral preference."),
          performer ? React.createElement(CuratorPerformerSpecifics, { details }) : React.createElement(CuratorSceneSpecifics, { details, scene }),
          !performer && details.explanation && React.createElement("details", { className: "curator-entity-evidence" }, React.createElement("summary", null, "Why this score?"), React.createElement(ExplanationView, { explanation: details.explanation })),
          !performer && score?.neighbors?.length > 0 && React.createElement("details", { className: "curator-entity-evidence" },
            React.createElement("summary", null, "Scenes behind this estimate"),
            React.createElement(CuratorSceneEvidence, { neighbors: score.neighbors })
          )
        )
    );
  }
  function curatorSignalLabels(signals) {
    const labels = { ...FEEDBACK_LABELS, scene_rating: "Stash scene rating", curation_rating: "Curate rating", historical_play: "Imported viewing history", viewing: "Viewing history", viewing_session: "Tracked viewing session" };
    return [...new Set(signals || [])].map((signal) => labels[signal] || signal.replaceAll("_", " ")).join(", ") || "Signal types unavailable";
  }
  function CuratorPerformerSpecifics({ details }) {
    const profile = details.profile || {};
    const evidence = details.evidence;
    return React.createElement("div", { className: "curator-entity-specifics" },
      React.createElement("h4", null, "What influenced this?"),
      React.createElement("p", null, `Favorite: ${profile.favorite ? "yes" : "no"}. Stash rating: ${profile.rating100 == null ? "unrated" : `${profile.rating100}/100`}.`),
      React.createElement("h5", null, "Similar performers used by the model"),
      evidence?.performers?.length ? React.createElement("ul", null, evidence.performers.map((match) => React.createElement("li", { key: match.performer_id },
        React.createElement(NavLink, { to: `/performers/${match.performer_id}` }, match.name || `Performer ${match.performer_id}`),
        ` · similarity ${Number(match.similarity).toFixed(2)} · preference signal ${formatSigned(match.affinity)} · confidence ${Math.round(clamp01(match.confidence) * 100)}%`
      ))) : React.createElement("p", null, evidence ? "No similar-performer sources in this model." : "Source details are unavailable in the installed backend."),
      React.createElement("h5", null, "Scenes with learning evidence"),
      evidence?.scenes?.length ? React.createElement(React.Fragment, null,
        React.createElement("p", { className: "curator-entity-note" }, "Up to eight scenes with the strongest evidence weight. These are learning inputs, not a list of explicit performer likes or dislikes."),
        React.createElement("ul", null, evidence.scenes.map((entry) => React.createElement("li", { key: entry.scene_id },
          React.createElement(NavLink, { to: `/scenes/${entry.scene_id}` }, entry.title || `Scene ${entry.scene_id}`),
          ` · ${curatorSignalLabels(entry.direct.signals)} · learning signal ${formatSigned(entry.direct.learning_outcome)} · evidence weight ${Number(entry.direct.learning_evidence).toFixed(2)}`
        )))
      ) : React.createElement("p", null, evidence ? "No scene learning inputs available in this model." : "Scene evidence details are unavailable in the installed backend.")
    );
  }
  function CuratorSceneSpecifics({ details, scene }) {
    const components = details.score?.components || {};
    const identity = components.performer_identity?.performers || [];
    const similar = components.performer_similarity?.performers || [];
    const matches = similar.flatMap((entry) => entry.matches || []);
    const ids = [...new Set([...identity, ...matches].map((entry) => entry.performer_id).filter(Boolean))];
    const { data, error } = GQL.useFindPerformersQuery({ variables: { filter: { per_page: Math.max(1, ids.length) }, performer_ids: ids.map(Number) }, skip: !ids.length });
    const names = new Map([...(scene?.performers || []), ...(data?.findPerformers?.performers || [])].map((performer) => [String(performer.id), performer.name]));
    const rows = [];
    for (const feature of components.content?.top || []) {
      if (!Number.isFinite(feature.value) || Math.abs(feature.value) < 0.000001) continue;
      const name = feature.metadata?.tag_name || feature.name;
      rows.push(React.createElement("li", { key: `content-${feature.feature_id || name}` }, `${name || "Unnamed content feature"}: content signal ${formatSigned(feature.value)}${feature.affinity_metadata?.declared_preference != null ? " (includes your declared preference)" : " (learned)"}.`));
    }
    for (const entry of identity) {
      if (!Number.isFinite(entry.value) || Math.abs(entry.value) < 0.000001) continue;
      rows.push(React.createElement("li", { key: `performer-${entry.performer_id}` },
        React.createElement(NavLink, { to: `/performers/${entry.performer_id}` }, names.get(String(entry.performer_id)) || `Performer ${entry.performer_id}`),
        `: performer signal ${formatSigned(entry.value)} (scene evidence ${formatSigned(entry.learned)}, favorite/rating ${formatSigned(entry.prior)}).`
      ));
    }
    for (const entry of similar) {
      if (!Number.isFinite(entry.value) || Math.abs(entry.value) < 0.000001) continue;
      rows.push(React.createElement("li", { key: `similar-${entry.performer_id}` }, `Similar-performer inference ${formatSigned(entry.value)} for ${names.get(String(entry.performer_id)) || `performer ${entry.performer_id}`}: `,
        ...(entry.matches || []).map((match, index) => React.createElement("span", { key: match.performer_id }, index > 0 ? "; " : "", React.createElement(NavLink, { to: `/performers/${match.performer_id}` }, names.get(String(match.performer_id)) || `Performer ${match.performer_id}`), ` (similarity ${Number(match.similarity).toFixed(2)}, preference ${formatSigned(match.affinity)})`))
      ));
    }
    for (const studio of components.studio?.studios || []) {
      if (!Number.isFinite(studio.value) || Math.abs(studio.value) < 0.000001) continue;
      rows.push(React.createElement("li", { key: `studio-${studio.studio_id}` }, React.createElement(NavLink, { to: `/studios/${studio.studio_id}` }, String(scene?.studio?.id) === String(studio.studio_id) ? scene.studio.name : `Studio ${studio.studio_id}`), `: studio signal ${formatSigned(studio.value)}.`));
    }
    if (details.score?.direct_confidence > 0) rows.push(React.createElement("li", { key: "direct" }, `This scene's history: ${curatorSignalLabels(components.direct?.signals)}. Direct preference ${formatSigned(details.score.direct_appeal)}, evidence weight ${Number(components.direct?.effective_evidence || 0).toFixed(2)}.`));
    for (const [key, label] of [["cooldown", "Recent viewing cooldown"], ["satiation", "Recent repetition"], ["not_now", "Not now feedback"]]) {
      const value = components.fit?.[key];
      if (Number.isFinite(value) && value > 0) rows.push(React.createElement("li", { key }, `${label}: reduces Current Fit by ${formatAppealValue(value)}.`));
    }
    return React.createElement("div", { className: "curator-entity-specifics" }, React.createElement("h4", null, "What influenced this?"),
      error && React.createElement("p", null, "Performer names could not be loaded; profile links are still available."),
      rows.length ? React.createElement(React.Fragment, null, React.createElement("ul", null, ...rows), React.createElement("p", { className: "curator-entity-note" }, "These are model inputs. Family weighting and score bounds mean the individual signals do not add directly to Appeal.")) : React.createElement("p", null, "No specific contributing inputs are available in this model."));
  }
  function CuratorSceneEvidence({ neighbors }) {
    const { data, loading, error } = GQL.useFindScenesQuery({ variables: { filter: { per_page: neighbors.length }, scene_ids: neighbors.map((neighbor) => Number(neighbor.scene_id)) } });
    const scenes = new Map((data?.findScenes?.scenes || []).map((scene) => [String(scene.id), scene]));
    return React.createElement("div", null,
      loading && React.createElement("p", { role: "status" }, "Loading scene titles…"),
      error && React.createElement("p", null, "Scene titles could not be loaded; links are still available."),
      React.createElement("ul", null, neighbors.map((neighbor) => React.createElement("li", { key: neighbor.scene_id },
        React.createElement(NavLink, { to: `/scenes/${neighbor.scene_id}` }, scenes.get(String(neighbor.scene_id))?.title || `Scene ${neighbor.scene_id}`),
        ` · similarity ${Number(neighbor.similarity).toFixed(2)} · history signal ${formatAppealValue(neighbor.outcome)}`
      )))
    );
  }
  let performerAffinitiesPending = null;
  function loadPerformerAffinities() {
    if (!performerAffinitiesPending) {
      performerAffinitiesPending = operation({ operation: "get_performer_affinities" })
        .finally(() => { performerAffinitiesPending = null; });
    }
    return performerAffinitiesPending;
  }
  const PERFORMER_AFFINITY_SORT = "curator_affinity";
  let performerSortIds = null;
  let performerSortInstalled = false;
  function configureAffinityFilter(filter, type = PERFORMER_AFFINITY_SORT) {
    const options = filter.options.criterionOptions;
    let option = options.find((item) => item.type === type);
    if (!option) {
      const textOption = options.find((item) => item.type === "name" || item.type === "title");
      option = new textOption.constructor({
        type, messageID: type,
        inputType: "number", defaultModifier: "GREATER_THAN",
        modifierOptions: ["GREATER_THAN", "LESS_THAN", "EQUALS", "NOT_EQUALS", "IS_NULL", "NOT_NULL"],
      });
      const makeCriterion = option.makeCriterionFn;
      option.makeCriterionFn = (type, config) => {
        const criterion = makeCriterion(type, config);
        criterion.isValid = function () {
          return this.modifier === "IS_NULL" || this.modifier === "NOT_NULL"
            || (String(this.value ?? "").trim() !== "" && Number.isFinite(Number(this.value)));
        };
        criterion.toCriterionInput = function () { return { modifier: this.modifier, value: Number(this.value) }; };
        return criterion;
      };
      // Stash's filter dialog and URL parser use the shared criterion registry.
      options.push(option);
    }
    filter.criteria = filter.criteria.map((criterion) => {
      if (criterion.criterionOption.type !== type || criterion.criterionOption.messageID === type) return criterion;
      const restored = option.makeCriterion();
      restored.fromDecodedParams(criterion.toQueryParams());
      return restored;
    });
    return filter;
  }
  function matchesPerformerAffinity(value, criterion) {
    if (!criterion) return true;
    const known = Number.isFinite(value);
    if (criterion.modifier === "IS_NULL") return !known;
    if (criterion.modifier === "NOT_NULL") return known;
    if (!Number.isFinite(criterion.value)) throw new Error("Enter a valid Curator affinity value.");
    if (!known) return false;
    switch (criterion.modifier) {
      case "GREATER_THAN": return value > criterion.value;
      case "LESS_THAN": return value < criterion.value;
      case "EQUALS": return value === criterion.value;
      case "NOT_EQUALS": return value !== criterion.value;
      default: throw new Error("Unsupported Curator affinity comparison.");
    }
  }
  function matchingPerformerSortIds(client, variables, context) {
    const affinitySort = variables.filter?.sort === PERFORMER_AFFINITY_SORT;
    const filter = { ...variables.filter, page: 1, per_page: -1,
      ...(affinitySort ? { sort: "name", direction: "ASC" } : {}) };
    const { [PERFORMER_AFFINITY_SORT]: ignored, ...performerFilter } = variables.performer_filter || {};
    const queryVariables = { filter, performer_filter: performerFilter };
    const key = JSON.stringify(queryVariables);
    // shortcut: matching IDs can lag edits by 30 seconds; invalidate on edits if this becomes noticeable.
    if (!performerSortIds || performerSortIds.key !== key || performerSortIds.expires < Date.now()) {
      const entry = { key, expires: Date.now() + 30000 };
      entry.promise = client.query({
        query: libraries.Apollo.gql`query CuratorPerformerSortIds($filter: FindFilterType, $performer_filter: PerformerFilterType) {
          findPerformers(filter: $filter, performer_filter: $performer_filter) { performers { id } }
        }`,
        variables: queryVariables, context, fetchPolicy: "no-cache",
      }).then((result) => result.data.findPerformers.performers.map((performer) => String(performer.id)))
        .catch((error) => { if (performerSortIds === entry) performerSortIds = null; throw error; });
      performerSortIds = entry;
    }
    return performerSortIds.promise;
  }
  async function affinitySortedPerformers(client, request) {
    const variables = request.variables;
    const context = request.getContext();
    const [matchingIds, details] = await Promise.all([
      matchingPerformerSortIds(client, variables, context), loadPerformerAffinities(),
    ]);
    const direction = variables.filter?.direction === "ASC" ? 1 : -1;
    const ids = matchingIds.filter((id) => matchesPerformerAffinity(details.affinities[id]?.affinity, variables.performer_filter?.[PERFORMER_AFFINITY_SORT]));
    if (variables.filter?.sort === PERFORMER_AFFINITY_SORT) ids.sort((left, right) => {
      const a = details.affinities[left]?.affinity;
      const b = details.affinities[right]?.affinity;
      const hasA = Number.isFinite(a), hasB = Number.isFinite(b);
      if (hasA !== hasB) return hasA ? -1 : 1;
      return hasA ? direction * (a - b) : 0;
    });
    const perPage = variables.filter?.per_page ?? 40;
    const page = variables.filter?.page ?? 1;
    const pageIds = perPage < 0 ? ids : ids.slice((page - 1) * perPage, page * perPage);
    if (!pageIds.length) return { data: { findPerformers: { __typename: "FindPerformersResultType", count: ids.length, performers: [] } } };
    const result = await client.query({
      query: request.query, context, fetchPolicy: "no-cache",
      variables: { ...variables, performer_ids: pageIds.map(Number), performer_filter: null,
        filter: { ...variables.filter, page: 1, per_page: pageIds.length, sort: "name" } },
    });
    const performers = new Map(result.data.findPerformers.performers.map((performer) => [String(performer.id), performer]));
    return { ...result, data: { ...result.data, findPerformers: { ...result.data.findPerformers,
      count: ids.length, performers: pageIds.map((id) => performers.get(id)).filter(Boolean) } } };
  }
  function installPerformerAffinitySort() {
    if (performerSortInstalled) return;
    const client = Api.utils.StashService.getClient();
    const { ApolloLink, Observable } = libraries.Apollo;
    const adapter = new ApolloLink((request, forward) => {
      if (request.operationName !== "FindPerformers" || (request.variables.filter?.sort !== PERFORMER_AFFINITY_SORT && !request.variables.performer_filter?.[PERFORMER_AFFINITY_SORT])) return forward(request);
      return new Observable((observer) => {
        let active = true;
        affinitySortedPerformers(client, request).then(
          (result) => { if (active) { observer.next(result); observer.complete(); } },
          (error) => { if (active) observer.error(error); }
        );
        return () => { active = false; };
      });
    });
    client.setLink(adapter.concat(client.link));
    performerSortInstalled = true;
  }
  Api.patch.before("FilteredPerformerList", function (props, ...args) {
    installPerformerAffinitySort();
    const existingHook = props.filterHook;
    return [{ ...props, filterHook: (filter) => {
      configureAffinityFilter(filter);
      return existingHook ? existingHook(filter) : filter;
    } }, ...args];
  });
  function addPerformerAffinitySortOption(element) {
    if (!React.isValidElement(element)) return;
    const filter = element.props.filter;
    if (filter?.options?.criterionOptions) configureAffinityFilter(filter);
    if (/^\/performers\/?$/.test(window.location.pathname) && filter?.options?.sortByOptions && !filter.options.sortByOptions.some((option) => option.value === PERFORMER_AFFINITY_SORT)) {
      filter.options = { ...filter.options, sortByOptions: [...filter.options.sortByOptions,
        { value: PERFORMER_AFFINITY_SORT, messageID: PERFORMER_AFFINITY_SORT }] };
    }
    React.Children.forEach(element.props.children, addPerformerAffinitySortOption);
  }
  function CuratorPerformerSortLocale({ children }) {
    const intl = libraries.Intl.useIntl();
    return React.createElement(libraries.Intl.IntlProvider, {
      ...intl, messages: { ...intl.messages, [PERFORMER_AFFINITY_SORT]: "Curator affinity" },
    }, children);
  }
  Api.patch.after("FilteredPerformerList", function (props, ...args) {
    const result = args[args.length - 1];
    addPerformerAffinitySortOption(result);
    return React.createElement(CuratorPerformerSortLocale, null, result);
  });
  const SCENE_AFFINITY_SORT = "curator_appeal";
  let sceneSortInstalled = false;
  async function affinitySortedScenes(client, request) {
    const variables = request.variables;
    const affinitySort = variables.filter?.sort === SCENE_AFFINITY_SORT;
    const { [SCENE_AFFINITY_SORT]: savedCriterion, ...sceneFilter } = variables.scene_filter || {};
    let criterion = savedCriterion;
    // A cold playlist URL can be decoded before the list registers its criterion.
    if (criterion && criterion.modifier !== "IS_NULL" && criterion.modifier !== "NOT_NULL") {
      const value = typeof criterion.value === "string" && criterion.value.trim() !== "" ? Number(criterion.value) : criterion.value;
      if (!Number.isFinite(value)) throw new Error("Enter a valid Curator Appeal value.");
      criterion = { ...criterion, value };
    }
    const details = await operation({
      operation: "get_scene_affinity_page", scene_ids: variables.scene_ids,
      filter: { ...variables.filter, ...(affinitySort ? { sort: "title", direction: "ASC" } : {}) },
      scene_filter: sceneFilter, criterion, sort: affinitySort,
      direction: variables.filter?.direction || "DESC", page: variables.filter?.page ?? 1,
      per_page: variables.filter?.per_page ?? 40,
    }, 120000);
    const metadata = { __typename: "FindScenesResultType", count: details.count, duration: details.duration, filesize: details.filesize };
    if (!details.scene_ids.length) return { data: { findScenes: { ...metadata, scenes: [] } } };
    const result = await client.query({
      query: request.query, context: request.getContext(), fetchPolicy: "no-cache",
      variables: { ...variables, scene_ids: details.scene_ids.map(Number), scene_filter: null,
        filter: { ...variables.filter, page: 1, per_page: details.scene_ids.length, sort: "title" } },
    });
    const scenes = new Map(result.data.findScenes.scenes.map((scene) => [String(scene.id), scene]));
    return { ...result, data: { ...result.data, findScenes: { ...result.data.findScenes, ...metadata,
      scenes: details.scene_ids.map((id) => scenes.get(id)).filter(Boolean) } } };
  }
  function installSceneAffinitySort() {
    if (sceneSortInstalled) return;
    const client = Api.utils.StashService.getClient();
    const { ApolloLink, Observable } = libraries.Apollo;
    const adapter = new ApolloLink((request, forward) => {
      if (request.operationName !== "FindScenes" || (request.variables.filter?.sort !== SCENE_AFFINITY_SORT && !request.variables.scene_filter?.[SCENE_AFFINITY_SORT])) return forward(request);
      return new Observable((observer) => {
        let active = true;
        affinitySortedScenes(client, request).then(
          (result) => { if (active) { observer.next(result); observer.complete(); } },
          (error) => { if (active) observer.error(error); }
        );
        return () => { active = false; };
      });
    });
    client.setLink(adapter.concat(client.link));
    sceneSortInstalled = true;
  }
  installSceneAffinitySort();
  Api.patch.before("FilteredSceneList", function (props, ...args) {
    installSceneAffinitySort();
    const existingHook = props.filterHook;
    return [{ ...props, filterHook: (filter) => {
      configureAffinityFilter(filter, SCENE_AFFINITY_SORT);
      return existingHook ? existingHook(filter) : filter;
    } }, ...args];
  });
  function addSceneAffinitySortOption(element) {
    if (!React.isValidElement(element)) return;
    const filter = element.props.filter;
    if (filter?.options?.criterionOptions) configureAffinityFilter(filter, SCENE_AFFINITY_SORT);
    if (filter?.options?.sortByOptions && !filter.options.sortByOptions.some((option) => option.value === SCENE_AFFINITY_SORT)) {
      filter.options = { ...filter.options, sortByOptions: [...filter.options.sortByOptions,
        { value: SCENE_AFFINITY_SORT, messageID: SCENE_AFFINITY_SORT }] };
    }
    React.Children.forEach(element.props.children, addSceneAffinitySortOption);
  }
  function CuratorSceneSortLocale({ children }) {
    const intl = libraries.Intl.useIntl();
    return React.createElement(libraries.Intl.IntlProvider, {
      ...intl, messages: { ...intl.messages, [SCENE_AFFINITY_SORT]: "Curator Appeal" },
    }, children);
  }
  Api.patch.after("FilteredSceneList", function (props, ...args) {
    const result = args[args.length - 1];
    addSceneAffinitySortOption(result);
    return React.createElement(CuratorSceneSortLocale, null, result);
  });
  const SceneAffinityContext = React.createContext(null);
  function CuratorSceneAffinityCards({ ids, children }) {
    const [details, setDetails] = React.useState(null);
    React.useEffect(() => {
      let active = true;
      setDetails(null);
      operation({ operation: "get_scene_affinities", scene_ids: JSON.parse(ids) })
        .then((data) => { if (active) setDetails(data.affinities); })
        .catch(() => { if (active) setDetails(null); });
      return () => { active = false; };
    }, [ids]);
    return React.createElement(SceneAffinityContext.Provider, { value: details }, children);
  }
  Api.patch.after("SceneList", function (props, ...args) {
    const result = args[args.length - 1];
    return React.createElement(CuratorSceneAffinityCards, { ids: JSON.stringify(props.scenes.map((scene) => String(scene.id))) }, result);
  });
  function CuratorSceneAffinityPill({ id, label, score: providedScore, className = "curator-scene-card-badge" }) {
    const details = React.useContext(SceneAffinityContext);
    if (!details && providedScore === undefined) return null;
    const score = providedScore === undefined ? details[String(id)] : providedScore;
    const confidenceLabel = score ? `Confidence ${Math.round(clamp01(score.confidence) * 100)}%` : "No estimate";
    const query = new URLSearchParams({ view: "similar", type: "scene", id: String(id), label: label || `Scene ${id}` });
    return React.createElement("div", { className: `curator-context-group curator-context-group-scene ${className}`, role: "group", "aria-label": "Curator scene affinity and Similar", onClick: (event) => event.stopPropagation() },
      React.createElement("span", { className: "curator-context-brand", title: "Curator Appeal", "aria-hidden": true }, React.createElement(FontAwesomeIcon, { icon: faCompass })),
      React.createElement(CuratorAffinityGauge, { value: score?.appeal ?? null, label: "Appeal", confidenceLabel,
        detail: score ? `Long-term scene Appeal on a -1 to +1 scale. ${confidenceLabel}. Current Fit and lane ranking are separate.` : "No published estimate for this scene." }),
      React.createElement(NavLink, { className: "curator-context-button curator-context-button-similar", to: `/plugins/stash-curator?${query}`, title: "Find similar scenes with Curator", "aria-label": "Find similar scenes with Curator" }, React.createElement(FontAwesomeIcon, { icon: faClone }))
    );
  }
  Api.patch.instead("SceneCard.Overlays", function (props, ...args) {
    const next = args.pop();
    const result = next.call(this, props, ...args);
    if (props.curatorAppeal !== undefined || props.scene?.id == null) return result;
    return React.createElement(React.Fragment, null,
      result, React.createElement(CuratorSceneAffinityPill, { id: props.scene.id, label: props.scene.title })
    );
  });
  function CuratorPerformerCardBadge({ performer }) {
    const [details, setDetails] = React.useState(null);
    React.useEffect(() => {
      let active = true;
      setDetails(null);
      loadPerformerAffinities()
        .then((data) => { if (active) setDetails(data.affinities[String(performer.id)] || { affinity: null, confidence: null }); })
        .catch(() => { if (active) setDetails(null); });
      return () => { active = false; };
    }, [performer.id]);
    return React.createElement(CuratorContextControls, { type: "performer", id: performer.id, label: performer.name, details, className: "curator-performer-card-badge" });
  }
  Api.patch.instead("PerformerCard.Overlays", function (props, ...args) {
    const next = args.pop();
    const result = next.call(this, props, ...args);
    if (!/^\/performers\/?$/.test(window.location.pathname) || props.performer?.id == null) return result;
    return React.createElement(React.Fragment, null,
      result,
      React.createElement(CuratorPerformerCardBadge, { key: "curator-performer-affinity", performer: props.performer })
    );
  });
  Api.patch.instead("ScenePage", function (props, ...args) {
    const next = args.pop();
    const result = next.call(this, props, ...args);
    return React.createElement(React.Fragment, null, result, React.createElement(CuratorContextLink, { type: "scene", id: props.scene.id, label: props.scene.title || `Scene ${props.scene.id}`, scene: props.scene }), React.createElement(LanePlaylistControls, { sceneId: props.scene.id }));
  });
  Api.patch.instead("PerformerPage", function (props, ...args) {
    const next = args.pop();
    const result = next.call(this, props, ...args);
    return React.createElement(React.Fragment, null, result, React.createElement(CuratorContextLink, { type: "performer", id: props.performer.id, label: props.performer.name || `Performer ${props.performer.id}` }));
  });
  Api.Event.addEventListener("stash:location", (event) => {
    attachPlayer(event.detail.data.location.pathname);
    flushQueue();
  });
  getPluginSettings().catch((error) => console.warn("Curator could not load card display settings:", error.message));
  window.addEventListener("online", flushQueue);
  window.addEventListener("online", flushTagPreferenceQueue);
  window.addEventListener("pagehide", () => finishTracker(false));
  attachPlayer(location.pathname);
  flushQueue();
  flushTagPreferenceQueue();
  // Mirror Stash's SFW blur onto the preview wall. Stash's own scene-card
  // classes break custom wall tiles, so detect SFW from whether the wall media
  // is actually blurred and apply a strong Curator-side blur when it is. Stash
  // mutates the DOM often, so the check is debounced.
  let sfwTimer = null;
  function syncSfwBlur() {
    clearTimeout(sfwTimer);
    sfwTimer = setTimeout(() => {
      const media = document.querySelectorAll(".curator-preview-tile .card-section, .curator-preview-tile .curator-preview-video");
      let blurred = false;
      for (const el of media) {
        const filter = window.getComputedStyle(el).filter;
        if (filter && filter !== "none") { blurred = true; break; }
      }
      document.body.classList.toggle("curator-sfw", blurred);
    }, 100);
  }
  if (typeof MutationObserver !== "undefined") {
    new MutationObserver(syncSfwBlur).observe(document.body, { attributes: true, childList: true, subtree: true });
    syncSfwBlur();
  }
})();
