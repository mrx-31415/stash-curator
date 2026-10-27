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
  // Curate's own sections. Tag questions and Tag sentiment teach tags directly
  // (issue #241: under Curate, not Manage). Pair picks were retired; an old
  // section=stream link falls back to the first section. Section URL values
  // stay stable (sentiment / progress) so links keep working.
  const CURATE_SECTIONS = [
    {
      value: "questions",
      label: "Tag questions",
      icon: faCircleQuestion,
      description: "A few quick questions about the tags that would change your recommendations most.",
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
  // meaningful once a build has actually consumed the answers just submitted.
  // Kick the update immediately (no debounce — the user is waiting on it) and
  // resolve when a different model is published, or when the wait times out.
  const MODEL_REFRESH_POLL_MS = 2000;
  const MODEL_REFRESH_TIMEOUT_MS = 180000;
  // An explicit "apply now": send queued tag answers, then build whenever any
  // feedback is pending, even below the automatic update threshold.
  async function applyFeedbackAndAwaitBuild() {
    await flushTagPreferenceQueue();
    const before = await operation({ operation: "health" }).catch(() => null);
    const previousModelId = before && before.model_id;
    if (!before || (!before.model_pending && !before.model_rebuilding)) {
      // Nothing new to apply, so don't stall on a build that won't start.
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
    [-0.75, "Dislike", "curator-sentiment-dislike"],
    [-0.5, "Slight dislike", "curator-sentiment-warning"],
    [0, "Neutral", "curator-sentiment-neutral"],
    [0.5, "Slight like", "curator-sentiment-like"],
    [0.75, "Like", "curator-sentiment-fond"],
    [1, "Strong like", "curator-sentiment-love"],
  ];

  // The sentiment levels span stops 1..N of an evenly spaced track whose
  // stop 0 is "Never". A continuous value in [-1, 1] (Taste Profile's
  // model-inferred sentiment) is placed between the two levels around it,
  // since the levels' values are not evenly spaced; the "Never" slot is
  // skipped because inference has no opinion on hard exclusion.
  const SENTIMENT_STOPS = SENTIMENTS.length;
  const NEUTRAL_STOP = SENTIMENTS.findIndex(([score]) => score === 0) + 1;
  function sentimentStopPct(stop) {
    return (stop / SENTIMENT_STOPS) * 100;
  }
  function sentimentValueToTrackPct(value) {
    const clamped = Math.max(-1, Math.min(1, value));
    let index = 1;
    while (index < SENTIMENTS.length - 1 && SENTIMENTS[index][0] < clamped) index++;
    const [low, high] = [SENTIMENTS[index - 1][0], SENTIMENTS[index][0]];
    return sentimentStopPct(index + (clamped - low) / (high - low));
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
    "Dislike": "dislike",
    "Slight dislike": "slightly dislike",
    "Neutral": "feel neutral about",
    "Slight like": "slightly like",
    "Like": "like",
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
        React.createElement("span", { key: label, className: index === 0 ? "curator-sentiment-scale-never" : undefined, style: { left: `${sentimentStopPct(index)}%` } }, label)
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
  function TagSentimentControl({ tag, value, blocked, onChange, compact = false, inferredValue = null, showScale = compact, large = false }) {
    const rated = (value !== null && value !== undefined) || blocked;
    const stopIndex = blocked ? 0 : rated ? SENTIMENTS.findIndex(([score]) => score === value) + 1 : NEUTRAL_STOP;
    const currentLabel = blocked ? "Never" : rated ? SENTIMENTS[stopIndex - 1][1] : "Not rated";
    const tierClass = blocked ? "curator-sentiment-never" : rated ? SENTIMENTS[stopIndex - 1][2] : "";
    function commit(index) {
      if (index === 0) onChange({ value: null, blocked: true });
      else onChange({ value: SENTIMENTS[index - 1][0], blocked: false });
    }
    function handleChange(event) {
      commit(Number(event.target.value));
    }
    // The track takes pointer input itself: a tap or drag anywhere on it
    // snaps to the nearest drawn stop and always commits, so tapping the
    // stop an unrated item rests on (Neutral) still answers. A native range
    // ignores taps on its track on some phones, and its thumb sits half a
    // thumb in from each end, away from the drawn end stops. The native
    // input stays for keyboards and screen readers.
    function stopAt(event) {
      const rect = event.currentTarget.getBoundingClientRect();
      return Math.round(Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)) * SENTIMENT_STOPS);
    }
    function handlePointerDown(event) {
      event.currentTarget.setPointerCapture?.(event.pointerId);
      commit(stopAt(event));
    }
    function handlePointerMove(event) {
      if (!event.currentTarget.hasPointerCapture?.(event.pointerId)) return;
      const index = stopAt(event);
      if (index !== stopIndex) commit(index);
    }
    const hasModelEstimate = inferredValue !== null && inferredValue !== undefined;
    return React.createElement(
      "div",
      { className: `curator-sentiment curator-sentiment-slider${compact ? " curator-sentiment-compact" : ""}${showScale ? " curator-sentiment-labelled" : ""}${large ? " curator-sentiment-large" : ""}`, role: "group", "aria-label": `Sentiment for ${tag.name}` },
      showScale && React.createElement(SentimentScale),
      React.createElement(
        "label",
        { className: `curator-sentiment-range-wrap${tierClass ? ` ${tierClass}` : ""}` },
        React.createElement(
          "span",
          { className: "curator-sentiment-track", onPointerDown: handlePointerDown, onPointerMove: handlePointerMove },
          React.createElement(
            "span",
            { className: "curator-sentiment-rail", "aria-hidden": "true" },
            Array.from({ length: SENTIMENT_STOPS + 1 }, (_, stop) => stop).map((stop) => React.createElement("span", {
              key: stop,
              className: `curator-sentiment-stop${stop === 0 ? " curator-sentiment-stop-never" : ""}${rated && stopIndex === stop ? " curator-sentiment-stop-active" : ""}`,
              style: { left: `${sentimentStopPct(stop)}%` },
            })),
            hasModelEstimate && React.createElement("span", {
              className: "curator-sentiment-model-dot",
              style: { left: `${sentimentValueToTrackPct(inferredValue)}%` },
              title: `Model estimate: ${nearestSentimentLabel(inferredValue)} (${inferredValue.toFixed(2)})`,
            }),
            rated && React.createElement("span", { className: "curator-sentiment-thumb", style: { left: `${sentimentStopPct(stopIndex)}%` } })
          ),
          React.createElement("input", {
            type: "range",
            min: "0",
            max: String(SENTIMENT_STOPS),
            step: "1",
            className: "curator-sentiment-input",
            value: stopIndex,
            "aria-label": `Sentiment for ${tag.name}`,
            "aria-valuetext": currentLabel,
            onChange: handleChange,
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

  // One flush runs at a time and drains answers queued while it was in
  // flight, so quick successive answers are not left behind until the next
  // page load. Callers can await the returned promise.
  let tagPreferenceFlush = null;
  function flushTagPreferenceQueue() {
    if (!tagPreferenceFlush) {
      tagPreferenceFlush = drainTagPreferenceQueue().finally(() => { tagPreferenceFlush = null; });
    }
    return tagPreferenceFlush;
  }

  async function drainTagPreferenceQueue() {
    for (let entries = readTagPreferenceQueue(); entries.length; entries = readTagPreferenceQueue()) {
      try {
        await operation({ operation: "submit_tag_preferences", entries });
      } catch (_) {
        // Retry on the next route, online event, or plugin page load.
        return;
      }
      const sent = new Set(entries.map((entry) => entry.preference_id));
      localStorage.setItem(TAG_PREFERENCE_QUEUE_KEY, JSON.stringify(readTagPreferenceQueue().filter((entry) => !sent.has(entry.preference_id))));
      clearSlateCache();
      scheduleModelUpdate();
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

  function fmtDelta(value) {
    const abs = Math.abs(value);
    const digits = abs >= 0.01 ? 3 : abs >= 0.001 ? 4 : 5;
    return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
  }

  function ImpactSceneCard({ entry, onCorrect }) {
    // Explain each mover in plain terms: what kind of thing changed, which way
    // the model's preference for it moved, and whether it connects to the
    // user's own feedback (via_feedback = rated scenes carrying it).
    const why = (entry.contributors || []).map((contributor) => {
      if (contributor.kind === "direct") {
        return `your own feedback on this scene (${fmtDelta(contributor.delta)})`;
      }
      const directionWord = contributor.delta >= 0 ? "more preferred" : "less preferred";
      const via = typeof contributor.via_feedback === "number" ? contributor.via_feedback : 0;
      const viaText = via > 0
        ? ` · from ${via} of your ${via === 1 ? "scene" : "scenes"}`
        : " · no rated scene — from a tag preference";
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
    const weakNote = (group, label) => maxMove(group) < 0.005 && React.createElement("p", { className: "curator-impact-weak" }, `${label} barely moved this build — new feedback since the previous build will show up here.`);
    return React.createElement(
      "div",
      { className: "curator-impact" },
      React.createElement("h4", { className: "curator-impact-heading" }, "What your feedback moved"),
      React.createElement("p", { className: "curator-impact-ago" }, `Newest model built ${new Date(impact.published_at_ms).toLocaleString()} — the feedback since the previous build is what moved these.`),
      React.createElement("p", { className: "curator-impact-legend" },
        "A scene's delta is how much its appeal moved (−1 to 1). “Because” lists the tags/performers whose learned preference changed, tied back to how many of your rated scenes carry each one."
      ),
      React.createElement(
        "div",
        { className: "curator-impact-groups" },
        React.createElement(
          "div",
          { className: "curator-impact-group" },
          React.createElement("div", { className: "curator-impact-group-label" }, "Scenes"),
            impact.scenes.promoted.length === 0 && impact.scenes.demoted.length === 0 && React.createElement("p", { className: "curator-impact-weak" }, "No scene moves came from your feedback this build — new feedback since the previous build will show up here."),
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

  // Tag questions: unanswered tags ranked by how much one answer would change
  // what For You shows (leverage x reach, from get_tag_questions). Answers go
  // through the ordinary Tag sentiment path; skips are remembered per browser.
  const TAG_QUESTION_BATCH = 5;
  const TAG_QUESTION_SKIP_KEY = "stash-curator:tag-question-skips:v1";
  const TAG_QUESTION_SKIP_MS = 30 * 86_400_000;

  function readTagQuestionSkips() {
    try {
      const stored = JSON.parse(localStorage.getItem(TAG_QUESTION_SKIP_KEY) || "{}");
      const now = Date.now();
      return Object.fromEntries(Object.entries(stored).filter(([, at]) => now - Number(at) < TAG_QUESTION_SKIP_MS));
    } catch (_) {
      return {};
    }
  }

  function rememberTagQuestionSkip(tagId) {
    try {
      localStorage.setItem(TAG_QUESTION_SKIP_KEY, JSON.stringify({ ...readTagQuestionSkips(), [tagId]: Date.now() }));
    } catch (_) {
      // Without storage a skipped tag can come back on the next batch.
    }
  }

  // What a tag means and what it looks like, read from Stash: the tag's
  // description and any markers carrying it. A marker clip shows the moment
  // itself, which a scene thumbnail often misses. Markers in the example
  // scenes come first, then markers elsewhere in the library.
  const TAG_QUESTION_MEDIA_QUERY =
    "query CuratorTagQuestionMedia($id: ID!, $tags: [ID!]) { " +
    "findTag(id: $id) { description } " +
    "findSceneMarkers(scene_marker_filter: { tags: { value: $tags, modifier: INCLUDES } }, " +
    "filter: { per_page: 40, sort: \"random\" }) { scene_markers { id seconds stream screenshot scene { id } } } }";

  async function fetchTagQuestionMedia(tagId) {
    const response = await fetch("/graphql", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: TAG_QUESTION_MEDIA_QUERY, variables: { id: tagId, tags: [tagId] } }),
    });
    const payload = await response.json();
    if (!response.ok || payload.errors) {
      throw new Error(payload.errors?.[0]?.message || `HTTP ${response.status}`);
    }
    return {
      description: (payload.data.findTag?.description || "").trim(),
      markers: payload.data.findSceneMarkers?.scene_markers || [],
    };
  }

  // Up to TAG_QUESTION_TILES clips: marker moments first (one per scene,
  // example scenes before others), then the example scenes' own previews.
  const TAG_QUESTION_TILES = 6;
  function tagQuestionTiles(examples, markers) {
    const exampleSet = new Set(examples);
    const seen = new Set();
    const tiles = [];
    const ordered = [...markers].sort((left, right) =>
      Number(!exampleSet.has(left.scene.id)) - Number(!exampleSet.has(right.scene.id)));
    for (const marker of ordered) {
      if (tiles.length >= TAG_QUESTION_TILES || seen.has(marker.scene.id)) continue;
      seen.add(marker.scene.id);
      tiles.push({
        key: `marker-${marker.id}`,
        href: `/scenes/${marker.scene.id}?t=${Math.floor(Number(marker.seconds) || 0)}`,
        video: marker.stream,
        poster: marker.screenshot,
        marker: true,
      });
    }
    for (const sceneId of examples) {
      if (tiles.length >= TAG_QUESTION_TILES || seen.has(sceneId)) continue;
      seen.add(sceneId);
      tiles.push({ key: `scene-${sceneId}`, href: `/scenes/${sceneId}`, video: `/scene/${sceneId}/preview`, poster: `/scene/${sceneId}/screenshot`, marker: false });
    }
    return tiles;
  }

  function keepTagQuestionClipMuted(node) {
    if (node) {
      node.muted = true;
      node.defaultMuted = true;
    }
  }

  function TagQuestionMedia({ item }) {
    const [media, setMedia] = React.useState(null);
    React.useEffect(() => {
      let current = true;
      setMedia(null);
      fetchTagQuestionMedia(item.tag_id)
        .then((result) => { if (current) setMedia(result); })
        // Without Stash's answer the scene previews alone still work.
        .catch(() => { if (current) setMedia({ description: "", markers: [] }); });
      return () => { current = false; };
    }, [item.tag_id]);
    const tiles = tagQuestionTiles(item.examples || [], (media && media.markers) || []);
    return React.createElement(
      React.Fragment,
      null,
      media && media.description && React.createElement("p", { className: "curator-tag-question-description" }, media.description),
      React.createElement(
        "div",
        { className: "curator-tag-question-examples" },
        tiles.map((tile) => React.createElement(
          "a",
          { key: tile.key, className: "curator-tag-question-example scene-card", href: tile.href, title: tile.marker ? "Open scene at this moment" : "Open scene" },
          React.createElement("video", {
            ref: keepTagQuestionClipMuted,
            className: "scene-card-image card-section",
            src: tile.video,
            poster: tile.poster,
            muted: true,
            loop: true,
            playsInline: true,
            autoPlay: true,
            preload: "metadata",
          }),
          tile.marker && React.createElement("span", { className: "curator-tag-question-marker" }, "Marker")
        ))
      )
    );
  }

  // A confident guess is asked as a check ("Right?"), with Yes picking the
  // matching slight step; the scale stays available to correct it.
  const TAG_QUESTION_GUESS_VALUE = { like: 0.5, dislike: -0.5 };

  function tagQuestionHeading(item) {
    return item.guess
      ? `Curator thinks you ${item.guess} “${item.name}”. Right?`
      : `More or less of “${item.name}”?`;
  }

  function tagQuestionReason(item) {
    const share = Math.max(1, Math.round(Number(item.reach) * 100));
    const belief = item.guess
      ? "If not, pick where you stand on the scale"
      : Number(item.confidence) < 0.35
        ? "Curator has little evidence about it yet"
        : "Curator has no clear view of it yet";
    return `On about ${share}% of what For You would show you. ${belief}.`;
  }

  // A chosen answer stays on screen until Next, so a tap that landed on the
  // wrong stop can be corrected before it is sent.
  function TagQuestions({ onShowAllTags }) {
    const [items, setItems] = React.useState(null);
    const [index, setIndex] = React.useState(0);
    const [choice, setChoice] = React.useState(null);
    const [answered, setAnswered] = React.useState(0);
    const [error, setError] = React.useState("");
    const [applying, setApplying] = React.useState(false);
    const [notice, setNotice] = React.useState("");
    useCuratorActivity("tag-questions", items === null && !error, "Finding useful questions…");

    const load = React.useCallback(async () => {
      setError("");
      try {
        const result = await operation({ operation: "get_tag_questions", limit: 10 });
        const skips = readTagQuestionSkips();
        setItems((result.items || []).filter((item) => !skips[item.tag_id]).slice(0, TAG_QUESTION_BATCH));
        setIndex(0);
        setChoice(null);
      } catch (failure) {
        setItems([]);
        setError(failure.message);
      }
    }, []);
    React.useEffect(() => { load(); }, [load]);

    function next(item) {
      submitTagPreference(item.tag_id, choice);
      setAnswered((count) => count + 1);
      setChoice(null);
      setNotice("");
      setIndex((current) => current + 1);
    }
    function skip(item) {
      rememberTagQuestionSkip(item.tag_id);
      setChoice(null);
      setNotice("");
      setIndex((current) => current + 1);
    }
    async function applyNow() {
      setApplying(true);
      setNotice("");
      try {
        const built = await applyFeedbackAndAwaitBuild();
        setAnswered(0);
        await load();
        setNotice(built
          ? "Recommendations updated with your answers. Impact shows what moved."
          : "Your answers are saved. Curator will include them in the next model update.");
      } finally {
        setApplying(false);
      }
    }

    if (items === null) return null;
    const item = items[index];
    const controls = React.createElement(
      "div",
      { className: "curator-curate-actions" },
      answered > 0 && React.createElement(Button, { size: "sm", variant: "primary", disabled: applying, onClick: applyNow },
        applying ? "Applying…" : "Apply my answers now"),
      React.createElement(Button, { size: "sm", variant: "secondary", disabled: applying, onClick: load }, "More questions"),
      onShowAllTags && React.createElement(Button, { size: "sm", variant: "link", onClick: onShowAllTags }, "See all tags")
    );
    return React.createElement(
      "div",
      { className: "curator-tag-questions" },
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      notice && React.createElement("div", { className: "alert alert-info", role: "status" }, notice),
      applying && React.createElement("div", { className: "alert alert-info", role: "status" },
        "Rebuilding recommendations with your answers. This usually takes under a minute."),
      !error && items.length === 0 && React.createElement("div", { className: "alert alert-info" },
        "No questions right now. Every tag in your current recommendations is either answered, skipped, or too rare to matter. Tag sentiment lists all tags."),
      item && React.createElement(
        "section",
        { key: item.tag_id, className: "curator-tag-question", "aria-labelledby": `curator-tag-question-${item.tag_id}` },
        React.createElement("p", { className: "curator-tag-question-progress", "aria-live": "polite" }, `Question ${index + 1} of ${items.length}`),
        React.createElement("h3", { id: `curator-tag-question-${item.tag_id}` }, tagQuestionHeading(item)),
        React.createElement("p", { className: "curator-tag-question-reason" }, tagQuestionReason(item)),
        React.createElement(TagQuestionMedia, { item }),
        React.createElement(
          "div",
          { className: "curator-tag-question-answer" },
          React.createElement(TagSentimentControl, {
            tag: item,
            value: choice && choice.value,
            blocked: !!(choice && choice.blocked),
            inferredValue: item.inferred_value,
            showScale: true,
            large: true,
            // Clear goes back to no answer; it is not sent.
            onChange: (picked) => setChoice(picked.value === null && !picked.blocked ? null : picked),
          })
        ),
        React.createElement(
          "div",
          { className: "curator-curate-actions" },
          item.guess && React.createElement(Button, {
            size: "sm",
            variant: "outline-primary",
            "aria-pressed": !!choice && !choice.blocked && choice.value === TAG_QUESTION_GUESS_VALUE[item.guess],
            onClick: () => setChoice({ value: TAG_QUESTION_GUESS_VALUE[item.guess], blocked: false }),
          }, "Yes"),
          React.createElement(Button, { size: "sm", variant: "primary", disabled: !choice, onClick: () => next(item) }, "Next"),
          React.createElement(Button, { size: "sm", variant: "secondary", onClick: () => skip(item) }, "Skip")
        )
      ),
      !item && items.length > 0 && React.createElement("p", { className: "curator-tag-question-done", "aria-live": "polite" },
        answered > 0
          ? `${answered} answer${answered === 1 ? "" : "s"} queued. They change recommendations after the next model update.`
          : "You skipped this batch."),
      controls
    );
  }

  // Answer review: your own tag answers that most disagree with what your
  // viewing alone suggests (get_answer_review). Keep remembers the answer as
  // checked in this browser until it changes or 180 days pass; a change is an
  // ordinary Tag sentiment answer, and Clear hands the tag back to viewing.
  const ANSWER_REVIEW_KEPT_KEY = "stash-curator:answer-review-kept:v1";
  const ANSWER_REVIEW_KEPT_MS = 180 * 86_400_000;

  function readAnswerReviewKept() {
    try {
      const stored = JSON.parse(localStorage.getItem(ANSWER_REVIEW_KEPT_KEY) || "{}");
      const now = Date.now();
      return Object.fromEntries(Object.entries(stored).filter(([, at]) => now - Number(at) < ANSWER_REVIEW_KEPT_MS));
    } catch (_) {
      return {};
    }
  }

  function rememberAnswerReviewKept(tagId) {
    try {
      localStorage.setItem(ANSWER_REVIEW_KEPT_KEY, JSON.stringify({ ...readAnswerReviewKept(), [tagId]: Date.now() }));
    } catch (_) {
      // Without storage a kept answer can come back on the next batch.
    }
  }

  function answerReviewReason(item) {
    const confidence = Number(item.learned_confidence) >= 0.8 ? "fairly sure" : "a tentative read";
    return `Your viewing on its own points to ${nearestSentimentLabel(Number(item.learned_value))} (${confidence}). You answered ${formatTimeAgo(Number(item.answered_at_ms))}.`;
  }

  function AnswerReview({ onShowAllTags }) {
    const [items, setItems] = React.useState(null);
    const [total, setTotal] = React.useState(0);
    const [index, setIndex] = React.useState(0);
    const [choice, setChoice] = React.useState(null);
    const [changed, setChanged] = React.useState(0);
    const [error, setError] = React.useState("");
    const [applying, setApplying] = React.useState(false);
    const [notice, setNotice] = React.useState("");
    useCuratorActivity("answer-review", items === null && !error, "Finding answers to review…");

    const load = React.useCallback(async () => {
      setError("");
      try {
        const result = await operation({ operation: "get_answer_review", limit: 10 });
        const kept = readAnswerReviewKept();
        // A kept answer returns once it has been changed since.
        const fresh = (result.items || []).filter((item) => !(kept[item.tag_id] > Number(item.answered_at_ms)));
        setItems(fresh.slice(0, TAG_QUESTION_BATCH));
        setTotal(Number(result.candidate_count) || 0);
        setIndex(0);
        setChoice(fresh.length ? { value: fresh[0].answer, blocked: false } : null);
      } catch (failure) {
        setItems([]);
        setError(failure.message);
      }
    }, []);
    React.useEffect(() => { load(); }, [load]);

    function advance() {
      const following = items[index + 1];
      setNotice("");
      setChoice(following ? { value: following.answer, blocked: false } : null);
      setIndex(index + 1);
    }
    function keep(item) {
      rememberAnswerReviewKept(item.tag_id);
      advance();
    }
    function save(item) {
      submitTagPreference(item.tag_id, choice);
      setChanged((count) => count + 1);
      advance();
    }
    async function applyNow() {
      setApplying(true);
      setNotice("");
      try {
        const built = await applyFeedbackAndAwaitBuild();
        setChanged(0);
        await load();
        setNotice(built
          ? "Recommendations updated with your changes. Impact shows what moved."
          : "Your changes are saved. Curator will include them in the next model update.");
      } finally {
        setApplying(false);
      }
    }

    if (items === null) return null;
    const item = items[index];
    const differs = item && choice && (choice.blocked || choice.value !== item.answer);
    return React.createElement(
      "div",
      { className: "curator-tag-questions" },
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      notice && React.createElement("div", { className: "alert alert-info", role: "status" }, notice),
      applying && React.createElement("div", { className: "alert alert-info", role: "status" },
        "Rebuilding recommendations with your changes. This usually takes under a minute."),
      !error && items.length === 0 && React.createElement("div", { className: "alert alert-info" },
        "Nothing to review right now. Your answers either agree with your viewing, or viewing has too little evidence to compare."),
      item && React.createElement(
        "section",
        { key: item.tag_id, className: "curator-tag-question", "aria-labelledby": `curator-answer-review-${item.tag_id}` },
        React.createElement("p", { className: "curator-tag-question-progress", "aria-live": "polite" },
          `Answer ${index + 1} of ${items.length} · ${total} answer${total === 1 ? "" : "s"} can be compared with your viewing`),
        React.createElement("h3", { id: `curator-answer-review-${item.tag_id}` },
          `You said “${nearestSentimentLabel(Number(item.answer))}” for “${item.name}”. Still right?`),
        React.createElement("p", { className: "curator-tag-question-reason" }, answerReviewReason(item)),
        React.createElement(TagQuestionMedia, { item }),
        React.createElement(
          "div",
          { className: "curator-tag-question-answer" },
          React.createElement(TagSentimentControl, {
            tag: item,
            value: choice && !choice.blocked ? choice.value : null,
            blocked: !!(choice && choice.blocked),
            inferredValue: item.learned_value,
            showScale: true,
            large: true,
            // Clear here means "let viewing decide": the answer is removed on Save.
            onChange: (picked) => setChoice(picked),
          })
        ),
        choice && !choice.blocked && choice.value === null && React.createElement("p", { className: "curator-tag-question-reason" },
          "Saving clears your answer, so viewing decides this tag again."),
        React.createElement(
          "div",
          { className: "curator-curate-actions" },
          React.createElement(Button, { size: "sm", variant: "primary", disabled: !differs, onClick: () => save(item) }, "Save change"),
          React.createElement(Button, { size: "sm", variant: "outline-primary", disabled: differs, onClick: () => keep(item) }, "Keep"),
          React.createElement(Button, { size: "sm", variant: "secondary", onClick: advance }, "Skip")
        )
      ),
      !item && items.length > 0 && React.createElement("p", { className: "curator-tag-question-done", "aria-live": "polite" },
        changed > 0
          ? `${changed} change${changed === 1 ? "" : "s"} queued. They change recommendations after the next model update.`
          : "Nothing changed in this batch."),
      React.createElement(
        "div",
        { className: "curator-curate-actions" },
        changed > 0 && React.createElement(Button, { size: "sm", variant: "primary", disabled: applying, onClick: applyNow },
          applying ? "Applying…" : "Apply my changes now"),
        React.createElement(Button, { size: "sm", variant: "secondary", disabled: applying, onClick: load }, "More answers"),
        onShowAllTags && React.createElement(Button, { size: "sm", variant: "link", onClick: onShowAllTags }, "See all tags")
      )
    );
  }

  // Tag questions has two modes: new questions about unanswered tags, and a
  // review of answers already given.
  function TagQuestionsSection({ onShowAllTags }) {
    const [mode, setMode] = React.useState("new");
    return React.createElement(
      React.Fragment,
      null,
      React.createElement(
        "div",
        { className: "btn-group curator-tag-question-modes", role: "group", "aria-label": "Tag questions mode" },
        [["new", "New questions"], ["review", "Review my answers"]].map(([value, label]) => React.createElement(Button, {
          key: value, size: "sm", variant: mode === value ? "primary" : "secondary", "aria-pressed": mode === value, onClick: () => setMode(value),
        }, label))
      ),
      mode === "review"
        ? React.createElement(AnswerReview, { onShowAllTags })
        : React.createElement(TagQuestions, { onShowAllTags })
    );
  }

  function CurateProgress({ onFixTag }) {
    const [impact, setImpact] = React.useState(null);
    const [profile, setProfile] = React.useState(null);
    const [error, setError] = React.useState("");
    const [applying, setApplying] = React.useState(false);
    const [loaded, setLoaded] = React.useState(false);
    useCuratorActivity("curate-progress", !loaded && !error, "Loading your impact…");

    const refresh = React.useCallback(async () => {
      try {
        setImpact(await operation({ operation: "get_curation_impact" }));
      } catch (_) {
        // Impact needs two model builds and their artifacts; absence is normal.
      }
      try {
        setProfile(await operation({ operation: "get_taste_profile" }));
      } catch (_) {
        // Needs a published model; the impact section still works.
      }
      setLoaded(true);
    }, []);

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
      loaded && profileItems.length === 0 && !(impact && impact.available) && React.createElement("div", { className: "alert alert-info" }, "Nothing to report yet. Answer a few tags in Tag sentiment and this fills in."),
      (profileItems.length > 0 || (impact && impact.available)) && React.createElement(
        "div",
        { className: "curator-impact-summary" },
        profileItems.length > 0 && React.createElement("span", null, `${answeredTags} tags answered${blockedTags > 0 ? ` · ${blockedTags} blocked` : ""}`),
        impact && impact.available && React.createElement("span", null, `Model built ${formatTimeAgo(impact.published_at_ms)}`)
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
        { className: "curator-curate-actions" },
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
      questions: () => React.createElement(TagQuestionsSection, { onShowAllTags: () => onSelectSection("sentiment") }),
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
    // Key by the lane the slate was served for: on a lane switch this renders
    // once with the new lane prop but the previous lane's slate, and keying by
    // the prop saved those items as the new lane's restore point.
    const slateLane = slate.lane || lane;
    const cacheKey = endlessBatchKey(slate, ["recommendations", slateLane, filters, rotationLane(slateLane), cards, thumbnails]);
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
    async function download(item) {
      setBusy(true);
      setError("");
      try {
        const parts = [];
        let offset = 0;
        for (;;) {
          setMessage(`Downloading ${item.id}: ${Math.floor((offset / Math.max(item.size_bytes, 1)) * 100)}%`);
          const chunk = await operation({ operation: "download_backup", backup_id: item.id, offset }, 120000);
          const bytes = Uint8Array.from(atob(chunk.content_base64), (c) => c.charCodeAt(0));
          parts.push(bytes);
          offset += bytes.length;
          if (chunk.done) break;
          if (!bytes.length) throw new Error("Backup download stopped before the end of the file.");
        }
        const url = URL.createObjectURL(new Blob(parts, { type: "application/vnd.sqlite3" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = item.id.replace(/\.backup$/, "");
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 0);
        setMessage(`Downloaded ${item.id}.`);
      } catch (failure) {
        setMessage("");
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
          React.createElement(Button, { size: "sm", variant: "link", disabled: busy, title: "Download this backup as a SQLite file for debugging.", onClick: () => download(item) }, "Download"),
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
        { key: "scheduleExpandRefreshIntervalHours", configKey: "schedule_expand_refresh_interval_hours", type: "NUMBER", label: "Expand refresh interval (hours)", description: "How often the scheduled Expand refresh runs. Default 24. With an hour of day set, runs start at that hour and repeat every interval (6 at 04:00 = 04, 10, 16, 22)." },
        { key: "scheduleExpandRefreshAtHour", configKey: "schedule_expand_refresh_at_hour", type: "NUMBER", optional: true, label: "Expand refresh hour of day", description: "Run at this hour (0-23, local time). Leave empty to run relative to when the schedule was enabled. Default 4 (04:00)." },
        { key: "scheduleSyncBuildEnabled", configKey: "schedule_sync_build_enabled", type: "BOOLEAN", label: "Scheduled sync and build", description: "Run a full sync and recommendation build on a schedule. Off by default." },
        { key: "scheduleSyncBuildIntervalHours", configKey: "schedule_sync_build_interval_hours", type: "NUMBER", label: "Sync and build interval (hours)", description: "How often the scheduled sync and build runs. Default 24. With an hour of day set, runs start at that hour and repeat every interval (6 at 04:00 = 04, 10, 16, 22)." },
        { key: "scheduleSyncBuildAtHour", configKey: "schedule_sync_build_at_hour", type: "NUMBER", optional: true, label: "Sync and build hour of day", description: "Run at this hour (0-23, local time). Leave empty to run relative to enablement. Default 4 (04:00)." },
        { key: "scheduleBackupEnabled", configKey: "schedule_backup_enabled", type: "BOOLEAN", label: "Scheduled backup", description: "Create a sidecar backup on a schedule, just before a scheduled sync and build when both are due. Off by default." },
        { key: "scheduleBackupIntervalHours", configKey: "schedule_backup_interval_hours", type: "NUMBER", label: "Backup interval (hours)", description: "How often the scheduled backup runs. Default 24. With an hour of day set, runs start at that hour and repeat every interval (6 at 04:00 = 04, 10, 16, 22)." },
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
    // CC0 light clunk with baked heartbeat/glow; source/mix details: docs/assets/roulette-latch-reveal.md.
    const impact = recording(Uint8Array.from(atob("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zf/O/9H/1//c/93/3f/d/97/4f/h/93/2f/W/9L/y//C/7v/uP+3/7T/rv+m/6H/mf+M/4D/df90/3v/g/+J/4z/kf+a/6P/rf+3/8j/3P/v//7/CgATABgAHgAjACIAIQAhAB4AFwALAP3/8P/j/9f/z//K/8P/vv+7/7f/uP/C/9H/3f/m/+3/8v/5/wMAEQAgAC8AOQBBAEkAUQBaAGEAZwBpAGcAZQBmAG4AdwCCAIsAjgCUAJ0ApgCpAKsAqwCpAKkApwCkAKEAoQCnAKoApwCjAJ8AmgCVAJAAiQCGAIwAlQCdAKIApACnAK4AtwDAAMYAzgDYAOIA7gD2APkA/QAAAQMBAwH+APIA4gDSAMQAswCaAH0AYwBPAEAAMAAhABcAEAAOABMAGgAdAB0AGwAWABMAFAAWABsAIgAmACAAFgANAAQA+P/t/9//1P/O/8b/v/+9/77/wf/E/8T/wv/B/77/tf+p/53/k/+M/4b/f/93/2//Zv9b/1T/Tv9F/z7/OP80/zH/Mf8w/zL/QP9R/1//af9x/33/if+R/5T/mf+k/67/t//C/8r/zv/P/83/xf+6/6z/mv+L/3//dP9o/13/U/9O/03/Sv9E/0P/Sf9R/1j/YP9o/3T/gP+J/5L/nP+j/6n/rv+w/7H/r/+m/53/l/+X/5j/mv+f/6P/p/+q/6v/r/+0/7b/tP+0/7L/r/+q/6T/o/+j/6D/nP+Z/5j/l/+T/4r/g/+B/4b/i/+O/5T/n/+o/7P/wv/O/9r/5f/x/wEAEgAgAC0APABJAFAAUgBSAFUAWwBbAFcAUQBIAD8ANQAoABsAFQATABMAGAAkADEAOwBJAFwAcQCGAJcAogCuALsAxQDNANcA4gDsAO8A7ADnAOQA3wDZANYA1gDdAOQA6gDxAPkAAQEEAQQBAwEBAfgA6gDdANQAzwDKAMMAugC0AKwAnwCUAI4AhwB9AHQAbwBsAGgAZQBgAFoAWwBgAGMAZwBsAG8AbQBvAHYAfAB+AH8AegBzAGoAWQBDADEAHwAJAPX/4f/L/7r/rv+g/5b/kf+S/5j/nv+k/6n/qf+m/6j/rP+x/7n/w//K/9D/0//R/83/zP/M/8j/w//A/77/u/+6/7v/vP/C/8j/yf/L/9D/0//T/9b/1//Y/9n/2v/Y/9j/2v/Z/9f/1v/R/8v/w/+6/7L/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TABRAFQAVABQAEoAQgA3ACoAGwAMAP3/7f/d/83/v/+y/6f/n/+a/5n/mv+f/6b/sf+9/8r/2f/n//X/AQAMABUAHQAjACYAKAApACcAJQAhABsAFQAOAAYA///5//L/7f/p/+b/5P/j/+L/4//j/+L/4f/g/97/2v/X/9P/z//K/8b/w//A/77/vP+7/7z/vf/A/8X/zP/U/97/6v/2/wIADwAbACYALwA2ADoAPAA6ADYALwAmABoADgAAAPL/4//U/8X/t/+r/6D/mP+T/5L/k/+Y/5//qv+2/8T/0//i//H//v8KABUAHwAmACsALgAwADEALwAsACgAIwAdABYAEAAJAAQA///8//r/+f/5//r/+//9//7///8AAP///v/8//n/9v/z//H/7v/s/+r/6f/p/+n/6//u//L/+P8AAAkAFAAgAC0AOgBGAFIAWwBjAGkAawBrAGgAYgBaAE8AQwA1ACcAGAAJAPr/6//e/9P/yf/D/8D/wP/D/8n/0f/c/+n/9v8DABEAHgAqADQAPABDAEgASwBLAEsASQBFAEAAOgAzACwAJAAcABUADwAKAAcABAADAAIAAgACAAMAAwADAAEAAAD9//n/9v/y/+7/6//n/+T/4v/g/9//3//g/+L/5v/s//T//f8IABMAHgAqADUAQABIAE0AUABRAE8ASgBCADgALAAfABEAAgDz/+T/1f/H/7v/sf+p/6X/pP+m/6v/sv+8/8j/1f/i//D//f8IABMAHAAiACcAKgAsACwAKgAnACIAHAAVAA0ABgD+//f/8P/r/+f/5P/i/+H/4P/h/+H/4f/i/+H/4P/e/9v/2P/U/9D/zf/K/8f/xP/C/8H/wP/B/8P/xv/M/9P/3P/n//L//v8JABUAIAApADAANQA3ADcANAAtACUAGwAPAAMA9f/n/9r/zP+//7P/qv+j/57/nf+f/6T/rP+2/8L/0P/f/+7//P8IABQAHwAnAC4AMwA3ADgAOAA2ADMALwAqACQAHQAWABAACgAFAAEAAAD///////8AAAIAAwAEAAQABQAEAAMAAQD+//z/+f/2//P/8f/v/+7/7f/u/+//8v/3//3/BQAOABkAJQAwADwARwBRAFgAXgBhAGAAXgBYAFAARgA7AC8AIAASAAMA9f/n/9v/0P/I/8L/v/+//8P/yf/R/9z/6f/2/wMAEAAdACkAMgA6AEAARQBHAEgASABFAEEAPAA2AC8AJwAfABgAEQALAAYAAwABAP///////wAAAQACAAMAAgABAP///f/7//f/9P/w/+3/6v/n/+T/4v/h/+H/4//m/+v/8f/5/wIADAAWACEALAA1AD0AQgBGAEYARAA/ADgALgAjABYACAD7/+z/3f/P/8H/tv+s/6X/of+g/6L/p/+u/7f/w//P/9z/6f/1/wEACwASABkAHQAfACEAIQAeABsAFgAQAAkAAgD7//P/7f/n/+L/3v/c/9r/2v/b/9z/3v/g/+H/4v/i/+H/4P/e/9z/2v/X/9T/0v/P/87/zP/L/8v/zf/Q/9X/3P/k/+7/+f8EABAAGwAmADAAOAA9AEAAQAA+ADkAMQAoAB4AEgAFAPj/6//e/9L/x/++/7j/tP+z/7X/uv/C/8v/1//k//H///8LABgAIwAsADQAOQA9AD8APwA+ADwAOAAzACwAJQAeABcAEAAKAAUAAQD///3//P/9//7/AAABAAMAAwAEAAQAAwABAP///P/6//f/9P/x/+//7P/r/+r/6//t//D/9v/8/wQADQAYACMALgA4AEIASgBPAFIAUwBRAEwARQA8ADEAJQAZAAsA/f/w/+P/1//N/8b/wf++/7//w//I/9H/2//n//P/AAANABkAJAAtADUAOgA+AEEAQQBAAD4AOgA0AC4AJwAfABgAEQAKAAUAAQD9//v/+v/6//v//P/+/wAAAQACAAEAAQAAAP7/+//4//X/8f/u/+v/5//l/+P/4v/i/+X/6P/u//T//P8FAA4AGAAhACoAMQA3ADoAOwA5ADUALwAmABwADwADAPb/5//Z/8z/v/+1/6z/pv+j/6L/pP+p/7D/uf/E/9D/3f/p//X/AAAJABEAFwAbAB4AHwAfAB0AGgAVAA8ACQACAPv/9f/v/+n/5f/h/9//3v/e/+D/4v/k/+f/6f/r/+3/7f/t/+z/6//p/+f/5f/i/9//3f/b/9r/2f/a/93/4P/m/+z/9f/+/wcAEgAcACYALwA3ADwAPwA/AD0AOAAxACgAHgASAAYA+f/t/+D/1P/K/8L/vP+4/7j/uf++/8X/zf/Y/+T/8f/+/woAFQAgACgALwA1ADgAOgA7ADkANgAyAC0AJwAgABkAEgAMAAYAAgD///z/+//6//v//f///wEABAAGAAcACAAIAAgABwAFAAMAAAD+//v/+P/2//T/8//z//T/9v/7/wAABgAOABgAIgAsADYAPwBHAEwAUABRAE8ASwBFAD0AMwAoABsADwACAPb/6v/f/9b/z//K/8j/yf/M/9H/2P/h/+3/+P8DAA8AGgAjACwAMgA3ADoAOwA7ADkANQAxACsAJAAdABUADQAGAAAA+v/1//H/7v/t/+3/7f/v//H/8v/1//b/9//3//b/9P/y//D/7f/q/+b/4v/f/9z/2v/Y/9n/2v/d/+H/5//u//b///8JABIAGwAjACkALQAvAC4AKwAlAB4AFQAKAP//8//m/9r/zv/D/7r/s/+u/6z/q/+u/7P/uv/D/87/2f/m//L//f8HABAAGAAeACIAJQAmACUAIwAfABoAFQAOAAgAAQD7//X/8P/s/+j/5v/l/+b/5//p/+z/7//y//T/9v/4//j/+P/3//X/8//x/+3/6//o/+X/4//i/+L/5P/m/+r/7//2//7/BwAQABoAIwAsADMAOAA7ADsAOgA2ADAAKAAeABMACAD8//D/5P/a/9H/yf/E/8H/wP/B/8X/zP/U/97/6f/1/wAACwAXACAAKAAuADMANgA3ADcANQAyAC0AJwAiABsAFQAPAAkABAD///z/+v/4//j/+f/8//7/AQAEAAcACQALAAwADQAMAAsACAAGAAMAAQD+//v/+f/3//b/9//5//v///8FAAsAEwAcACUALgA2AD4AQwBGAEcARgBDAD0ANQAsACEAFQAJAP3/8f/m/9z/0//N/8n/xv/H/8n/zv/V/97/5//y//3/BwASABsAIgAoAC0AMAAwADAALgAqACYAIAAaABMADAAFAP//+f/z/+//6//p/+f/6P/p/+v/7v/x//T/9v/4//n/+v/5//j/9v/z//D/7f/q/+b/4//h/9//3//f/+L/5f/q//D/9////wcAEAAZACEAJwArAC0ALQArACYAHwAXAA4AAwD4/+z/4f/W/8z/xP++/7n/t/+3/7n/vf/D/8v/1f/f/+v/9v8AAAkAEgAZAB4AIgAjACMAIgAgABwAFwARAAsABQD///n/8//u/+n/5f/j/+L/4v/j/+b/6f/s//D/8//2//j/+f/5//n/+P/2//P/8f/t/+r/6P/l/+T/4//k/+X/6P/t//L/+v8BAAoAEwAcACQALAAxADUANgA1ADIALQAmAB4AFAAJAP//9f/r/+L/2v/T/8//zP/M/83/0f/X/9//6f/z//7/CAATAB0AJgAtADQAOAA6ADsAOgA4ADUAMQArACYAIAAZABMADQAHAAMAAAD9//z/+//8//7/AAADAAcACgANAA8AEAARABAADwANAAoABwADAAAA/P/5//f/9f/1//X/9v/5//3/AgAJABAAGAAhACgALwA0ADgAOQA4ADYAMAApACEAFwAMAAIA9//s/+L/2f/S/8z/yP/H/8f/yv/O/9T/3P/l//D/+f8DAAwAFAAbACEAJQAnACgAJwAlACIAHQAYABIADAAFAP//+v/0/+//6v/n/+X/5P/l/+b/6f/s//D/8//3//r/+//9//3//P/7//j/9f/y/+//6//o/+X/4//i/+L/4//m/+n/7//1//z/BAAMABQAHAAhACYAKAApACcAIwAdABYADQADAPr/7//l/9v/0//L/8X/wf+//7//wf/F/8v/0v/b/+X/7//5/wIACgASABgAHQAgACEAIQAgAB0AGQAVAA8ACgAEAP7/+f/0/+//6//n/+X/5f/m/+j/6//u//L/9v/6//7/AQADAAQABAADAAIA///9//r/9//0//L/8P/u/+7/7//x//T/+f///wUADQAVAB4AJQAsADIANQA3ADYAMwAvACgAIAAXAA4ABAD6//H/6f/i/9z/1//V/9T/1f/Z/93/5P/s//X//v8IABEAGgAhACcALAAvADEAMQAvAC0AKQAlAB8AGgAUAA4ACAACAP7/+f/1//L/8f/x//L/9f/3//v//v8CAAUACAALAAwADAALAAoABwAEAAEA/v/6//f/9f/y//H/8f/x//P/9//7/wEACAAPABcAHwAlACoALwAxADAALgAqACQAHQAUAAsAAQD4/+//5//f/9n/1P/R/8//z//R/9b/3P/j/+v/9P/9/wYADgAWABwAIQAkACYAJgAlACMAIAAcABcAEQALAAYAAAD6//X/8P/s/+n/5//m/+f/6f/s/+//8//3//r//v8AAAEAAgABAAAA/f/7//j/9P/w/+z/6f/m/+T/4//j/+T/5//r//D/9v/9/wUADAASABgAHQAgACAAHwAcABcAEQAJAAEA+P/v/+b/3v/X/9D/zP/I/8f/x//J/8z/0v/Z/+H/6v/z//z/BAAMABMAGQAdAB8AIAAgAB8AHAAZABUAEAALAAYAAQD8//f/8v/u/+z/6v/p/+r/7P/v//P/9//8/wAAAwAHAAkACwALAAsACQAHAAQAAgD+//v/+P/1//P/8v/y//L/9P/4//3/AgAJABAAGAAfACUAKgAtAC8ALwAtACkAIwAcABQADAAEAPz/9P/s/+b/4f/d/9v/2v/b/97/4//o//D/9////wgADwAYAB4AIwAnACoAKwArACkAJwAjAB8AGgAVAA8ACQAEAP7/+f/1//L/8P/u/+7/8P/y//X/+f/+/wEABQAJAAsADQANAA0ADAAJAAcABAAAAP3/+v/2//P/8f/w//D/8f/0//j//f8CAAkADwAXAB0AIgAmACgAKQAnACQAHwAZABEACQABAPn/8f/p/+P/3f/Z/9b/1f/V/9f/2//g/+b/7f/1//z/BAALABIAFwAbAB0AHwAfAB0AGwAYABQADwAKAAUAAAD6//T/7//r/+f/5P/j/+L/4//l/+j/7P/x//X/+f/9/wAAAgACAAMAAgAAAP7//P/4//T/8f/t/+r/6P/m/+b/5//p/+z/8f/2//z/AwAJABAAFgAbAB4AHwAfAB0AGQATAA0ABgD///f/8P/p/+L/3f/Z/9b/1f/V/9f/2v/f/+X/7P/z//v/AwAKABAAFgAbAB4AIAAhACAAHgAcABgAFQAQAAsABwABAPz/+P/z//D/7f/s/+v/7P/u//H/9f/6//7/AgAGAAoADAAOAA8ADwANAAsACAAGAAIA/v/7//f/9P/y//H/8f/y//T/+P/9/wMACQAPABYAGwAgACMAJQAmACQAIQAcABYADwAJAAEA+v/0/+3/6P/j/+D/3v/e/9//4v/m/+v/8f/4////BgANABQAGQAeACEAIwAkACQAIwAhAB0AGgAVABEADAAGAAEA/f/5//X/8//w//D/8P/y//X/+P/8/wAABQAIAAwADwARABIAEgARAA8ADQAJAAYAAQD+//r/9v/0//L/8f/x//P/9v/5//7/BAAJAA8AFQAaAB0AIAAgAB8AHAAYABMADAAGAP//+P/x/+r/5f/g/9z/2f/Z/9n/2//e/+P/6P/u//T/+/8BAAcADAARABQAFwAXABcAFgAUABEADgAKAAUAAAD7//f/8f/t/+n/5v/k/+P/4//l/+f/6v/u//P/+P/8/wAAAwAGAAcACAAHAAYABAACAP7/+//3//P/7//t/+r/6f/p/+v/7f/w//b/+/8AAAYADAARABYAGQAaABoAGQAWABIADQAHAAEA+v/0/+7/6v/k/+H/3v/e/97/3//i/+b/7P/x//f//f8EAAoADwAUABcAGgAbABwAGwAZABcAFAAQAAwACAADAP//+v/2//L/7//t/+z/7P/t/+//8v/2//r///8DAAcACwAPABEAEgASABEADwANAAkABgACAP7/+v/4//T/8//y//P/9f/4//z/AQAGAAwAEgAXABwAHwAhACIAIQAfABwAFwASAAwABgAAAPr/9f/x/+3/6//p/+n/6v/s/+//9P/5//7/BAAJAA8AFAAYABwAHgAgACAAHwAeABwAGQAVABEADAAHAAMA/v/5//X/8v/v/+7/7f/t/+//8v/1//n//f8BAAUACQAMAA4ADwAPAA8ADQALAAcAAwD///v/9//z/+//7f/r/+v/7P/u//L/9v/6////BQAKAA4AEgAUABUAFQATABEADQAIAAMA/f/4//L/7f/o/+X/4v/g/9//4P/i/+X/6f/t//L/9//9/wIABwALAA8AEQATABQAFAATABEADwAMAAgABAAAAPv/9//z/+//7P/p/+j/5//o/+n/7P/v//P/+P/8/wEABQAIAAsADQAOAA4ADQALAAgABQABAPz/+P/0//D/7v/s/+z/7P/u//H/9P/5//7/AwAHAAwAEAATABUAFQAVABMAEAAMAAcAAgD9//j/8//v/+v/6P/n/+b/5v/o/+r/7v/x//b/+v8AAAUACQANABEAEwAVABcAFgAWABUAEgAQAAwACQAFAAAA/P/4//X/8v/v/+7/7f/t/+//8f/1//j//P8BAAYACgAOABEAFAAVABYAFgAUABEADgAKAAUAAQD9//r/9//1//P/9P/1//f/+f/9/wIABgAMABAAFAAXABoAGwAaABkAFgATAA8ACgAGAAEA/P/4//T/8v/v/+//7//v//H/9P/3//r///8DAAcACwAPABIAFQAWABgAGAAXABYAFAARAA4ACQAGAAIA/f/5//b/8v/w/+7/7P/t/+7/7//y//X/+f/+/wIABgAKAA0AEAASABIAEgAQAA4ACwAGAAIA/v/5//X/8v/v/+3/7P/s/+7/8P/0//j//P8AAAQACQAMAA4AEAAQABAADgALAAgABAAAAPv/9//z/+//7P/q/+n/6f/p/+v/7f/w//P/9//7////AwAGAAkADAANAA8ADwAPAA4ADAAKAAcABAAAAPz/+P/0//H/7v/r/+r/6P/o/+n/6//t//H/9f/5//3/AgAGAAkADAAOABAAEAAQAA0ACwAHAAMA/v/6//X/8f/v/+z/6//r/+z/7v/x//X/+f/9/wIABQAJAAwADgAPAA8ADwAMAAoABwADAAAA/P/4//X/8v/w/+//7//w//H/8//2//n//P///wQABwAKAA0AEAASABMAFAAUABMAEgAQAA0ACgAHAAMAAAD8//j/9v/z//L/8f/x//H/8v/1//j//P8AAAQACAANABEAFAAXABgAGQAZABcAFAARAAwACAADAP//+//4//X/8//z//P/9P/2//n//f8BAAQACAAMAA8AEQATABMAEwARAA8ADQAJAAYAAgD+//v/+P/2//T/9P/0//X/9v/4//r//f8AAAMABgAIAAsADQAPAA8AEAAQABAADgAMAAoABwAEAAAA/P/5//X/8//x/+7/7f/t/+3/7v/w//P/9v/6//7/AwAHAAsADgARABMAFAAUABMAEAANAAkABAAAAPv/9//z//D/7v/t/+3/7f/v//H/9P/4//z/AAADAAUACAAKAAsADAALAAkACAAFAAIA/v/7//j/9f/0//L/8v/y//L/9P/1//f/+f/8//7/AQADAAYABwAJAAoACgAKAAoACQAIAAYAAwD///z/+f/2//L/8P/u/+z/6//q/+v/6//t//D/8//4//v/AAAEAAgACwAPABEAEwAUABMAEQAOAAoABgABAPz/+P/0//H/7v/t/+z/7f/u//D/8//2//r//v8BAAQABwAJAAsACwAMAAsACgAIAAYAAgAAAP3/+//6//j/+P/4//n/+v/7//z//v8BAAMABgAHAAkACwAMAA0ADgAOAA4ADQAMAAoACAAFAAIA///7//n/9//1//P/8v/x//L/8v/0//b/+f/9/wEABQAJAA4AEQAVABgAGQAaABoAGAAVABIADQAIAAMA///7//f/9P/y//H/8P/x//L/9P/3//v//f8BAAQABgAJAAsADAANAA0ADAAKAAgABQADAAEA/v/9//z//P/7//z//P/9//7/AAACAAMABQAHAAgACQAKAAsACwALAAsACwAJAAgABgADAAAA/f/6//f/9f/z//H/8P/v/+//8P/x//T/9v/5//3/AQAFAAkADQARABQAFgAXABcAFQATAA8ACwAGAAIA/f/4//T/8f/u/+z/6//r/+z/7f/w//P/9f/5//z///8BAAMABAAFAAYABgAFAAMAAQD///3/+//5//j/+P/4//j/+P/6//r/+//9//7/AAABAAIAAwAEAAQABAAFAAQABAADAAIAAAD9//v/+f/2//P/8f/v/+7/7f/t/+3/7v/v//H/9P/3//v///8DAAgADAAPABMAFgAXABgAFwAVABIADgAJAAUAAAD8//j/9P/y//D/7//u/+7/8P/y//T/9//7//7/AAACAAUABwAJAAoACgAKAAkABwAGAAQAAgABAAAAAAAAAAAAAQABAAIABAAEAAYABgAHAAgACAAJAAkACQAJAAkACAAIAAYABQACAAAA/f/6//j/9v/1//P/8v/y//L/8v/0//b/+P/7//7/AgAGAAoADgASABYAGAAaABsAGwAZABYAEgAOAAkABAAAAPz/+P/1//L/8P/v/+//8P/x//P/9f/4//v//v8AAAIABQAHAAgACQAJAAgABwAGAAQABAACAAIAAQABAAIAAgADAAMABAAFAAUABQAGAAYABgAGAAUABQAFAAUABAADAAIAAAD///z/+f/3//X/8//x//D/7//v/+//7//w//L/9P/3//r//v8CAAYACQANABEAFAAWABcAFwAWABMADwALAAYAAgD9//n/9f/x/+7/7P/q/+r/6v/r/+3/7//y//T/9v/6//z//v8BAAMABAAFAAUABAADAAIAAQABAAAAAAAAAAAAAQACAAMAAwADAAQABAAFAAQABAAEAAMAAwACAAIAAgABAAAA///9//v/+P/3//X/8//y//D/8P/w//D/8f/y//T/9v/5//z///8DAAcACwAPABIAFgAYABkAGgAZABcAEwAPAAsABgACAP7/+f/1//L/8P/u/+3/7f/t/+7/8P/y//T/9//6//3///8CAAMABQAGAAcABgAHAAYABQAFAAUABQAFAAYABgAHAAcACAAIAAgACAAIAAcABwAGAAUABQAEAAMAAwACAAIAAAD+//z/+v/5//f/9f/1//T/8//z//P/9P/1//f/+f/7//7/AQAFAAkADAARABQAGAAaABwAHAAcABoAFwATAA8ACgAGAAEA/f/5//X/8v/w/+7/7v/u/+//7//x//P/9f/4//r//v8AAAIABAAFAAYABgAHAAYABgAGAAYABgAHAAcABwAIAAgACAAIAAgACAAHAAYABQAEAAMAAQABAAAA///+//3/+//6//j/9v/0//P/8f/w/+//7//v/+//8P/x//L/9f/3//r//f8BAAQACAALAA8AEwAVABcAGAAYABYAFAARAAwACAADAP//+//2//P/7//t/+v/6v/p/+r/6v/s/+3/8P/y//T/9//7//3///8BAAIABAAEAAUABQAFAAUABgAHAAgACAAIAAkACQAJAAkACQAIAAYABQAEAAMAAQD//////v/9//z/+v/5//f/9v/0//P/8v/x//D/8P/w//H/8f/z//X/9//5//z///8DAAYACQANABEAFAAXABkAGwAbABoAGAAVABEADQAIAAMA///7//f/8//x/+7/7f/s/+z/7P/t/+//8f/z//b/+P/7//3/AAACAAQABQAHAAgACQAKAAoACwAMAA0ADQAOAA8ADwAPAA4ADgAMAAsACQAHAAUABAACAAEAAAD+//3/+//6//n/9//2//X/9P/z//P/8v/y//P/9P/2//f/+f/7//7/AQAEAAgACwAOABIAFQAYABsAHAAcABsAGgAXABMADwAKAAUAAQD8//j/9P/x/+7/7f/r/+v/6v/r/+z/7f/v//L/9P/2//n//P/+/wEAAwAEAAUABwAHAAkACgALAAwADAANAA4ADgAOAA0ADAALAAkABwAFAAMAAQD+//3/+//6//j/9//1//T/8v/x//D/7//v/+7/7v/v/+//8f/y//T/9v/5//v//v8BAAUACAALAA8AEgAVABcAGQAaABkAFwAVABIADgAJAAUAAQD8//j/9P/w/+3/6//q/+j/6P/o/+n/6v/s/+7/8P/z//X/+f/7//7/AAADAAUABgAHAAkACgAMAA4ADgAPABAAEAAQABAADwANAAsACAAGAAMAAQD///3/+//5//f/9v/0//P/8v/w//D/7//v/+7/7//v//D/8v/z//X/+P/6//3///8DAAYACQANABAAFAAWABkAGwAbABsAGgAYABUAEgANAAkABAAAAPz/+P/0//H/7v/t/+v/6//q/+v/7P/t/+//8f/z//f/+f/8////AgAEAAYACQALAA0ADwARABIAEwAVABUAFQAWABUAFAASABAADgALAAcABAACAP///f/7//j/9v/1//P/8v/y//D/8P/w//D/8P/x//L/8//1//f/+f/8//7/AQAEAAcACgAOABAAFAAWABkAGwAcABwAGwAZABYAEwAPAAoABQABAP3/+P/0//H/7v/r/+r/6f/o/+j/6P/p/+v/7P/v//L/9P/4//v//f8AAAMABQAIAAoADQAPABAAEgATABQAFAAUABQAEwARAA8ADAAJAAYAAgD///z/+f/2//T/8v/w/+//7v/s/+z/6//r/+v/7P/t/+7/8P/x//T/9v/5//z//v8CAAUACAALAA4AEQAUABYAGAAZABkAGQAXABUAEgAOAAoABQABAP3/+P/0//D/7f/r/+n/5//m/+b/5v/n/+j/6f/s/+7/8f/0//f/+//+/wEABAAHAAoADQAPABEAEwAVABYAFgAXABcAFgAUABIADwALAAgABAAAAP3/+v/3//T/8v/w/+//7f/s/+z/7P/s/+z/7v/u//D/8f/0//b/+f/8//7/AgAFAAcACwAOABEAFAAXABkAGwAcABwAHAAbABkAFgATAA8ACgAGAAEA/f/5//X/8f/v/+z/6v/p/+j/6P/o/+n/6v/t/+//8v/0//j/+////wIABQAJAAwADwASABUAFgAZABoAGwAbABsAGQAYABYAEwAPAAsABwADAP//+//3//T/8f/v/+7/7P/r/+v/6//r/+z/7P/t/+//8f/z//X/+P/7//7/AQAEAAcACgANABAAEwAWABgAGQAbABsAGwAaABgAFQASAA8ACgAFAAEA/f/4//T/8f/t/+v/6f/n/+b/5v/m/+b/5//o/+r/7f/w//P/9//7////AgAFAAoADQARABMAFgAYABoAGwAbABsAGgAYABYAEwAPAAsABgACAP7/+f/2//L/7//s/+r/6f/o/+j/5//o/+j/6v/q/+z/7v/x//P/9v/6//z/AAADAAYACQAMAA8AEQAUABYAFwAZABoAGgAZABcAFQASAA8ACgAGAAEA/f/5//T/8f/t/+v/6P/n/+X/5P/k/+T/5f/m/+j/6v/t//H/9P/4//z/AQAFAAkADQAQABQAFwAZABsAHQAdAB0AHQAbABkAFgATAA4ACQAEAAAA+//3//P/8P/s/+r/6f/o/+f/5//o/+j/6v/r/+3/7//y//X/+P/7//7/AgAFAAgADAAOABEAFAAWABgAGgAbABwAHAAbABoAGAAVABIADgAJAAUAAAD8//j/9P/x/+3/6//p/+f/5v/l/+b/5v/m/+j/6v/s//D/9P/4//z/AAAFAAkADgASABYAGAAbAB4AHwAgACEAIAAfABwAGQAWABEADAAHAAEA/f/4//P/7//s/+n/6P/m/+b/5v/m/+f/6P/q/+z/7v/x//T/9//7//7/AgAFAAgADAAPABIAFAAWABgAGQAbABsAGwAbABoAGAAVABIADwAKAAYAAQD9//n/9P/x/+3/6//o/+b/5f/k/+P/4//j/+X/5v/o/+z/7//0//j//f8BAAYACwAPABMAFwAaABwAHgAgACAAIAAfAB0AGgAVABEADAAHAAEA/P/2//H/7f/p/+b/5P/i/+L/4v/i/+P/5f/m/+j/6//u//H/9f/5//z/AAAEAAcACwAOABAAEwAVABcAGAAZABoAGgAZABkAFwAVABIADwALAAYAAgD+//n/9f/y/+7/6//o/+b/5f/k/+P/4//j/+T/5f/n/+r/7f/y//b//P8AAAYACgAQABQAGAAcAB8AIQAjACMAIwAiACEAHgAaABUAEAAKAAUA///5//P/7//q/+f/5f/j/+L/4v/i/+P/5f/n/+n/6//v//L/9v/6//7/AgAFAAkADQAQABMAFQAXABkAGgAbABsAHAAbABsAGQAXABUAEQANAAkABQAAAPz/+P/0//D/7f/q/+j/5v/l/+P/4//j/+P/5P/m/+j/7P/w//X/+v///wQACgAPABQAGQAcACAAIgAlACUAJgAlACMAIAAdABgAEwANAAcAAAD6//T/7//q/+b/5P/h/+D/4P/h/+H/4v/l/+f/6v/t//H/9f/5//3/AQAFAAkADAAQABMAFQAXABgAGgAaABsAGwAaABoAGAAWABQAEQANAAkABQABAPz/+P/0//D/7f/q/+f/5f/j/+L/4f/g/+D/4f/i/+X/6P/s//D/9v/7/wEABgAMABEAFgAbAB4AIQAkACUAJQAlACQAIQAeABkAFAAOAAcAAQD7//T/7v/p/+T/4f/f/93/3f/d/97/3//h/+T/5//q/+7/8v/3//z/AAAEAAgADAAPABMAFQAXABkAGQAaABoAGwAaABoAGAAXABUAEgAOAAoABgACAP7/+f/1//H/7v/r/+j/5v/k/+L/4f/g/+D/4P/i/+T/5v/q/+//9P/6/wAABgAMABEAFwAbACAAIwAmACcAKAAoACcAJQAiAB0AGAASAAsABAD+//b/8P/q/+b/4v/f/93/3f/c/93/3//h/+P/5//q/+7/8//3//z/AQAFAAkADgARABQAFwAZABoAGwAcABwAHAAcABsAGgAZABYAFAAQAA0ACAAEAAAA/P/4//T/8P/t/+r/6P/l/+T/4v/h/+D/4P/h/+P/5f/p/+3/8//4//7/BQAKABEAFgAcACAAJAAnACkAKgArACkAJwAlACAAGwAVAA4ABgD///j/8f/r/+X/4f/e/9v/2v/a/9v/3P/e/+H/5P/n/+z/8P/1//r///8DAAgADAAQABQAFgAYABoAGgAbABsAGwAaABoAGQAXABUAEgAPAAwABwAEAP///P/4//P/8P/s/+n/5v/k/+L/4P/f/97/3v/e/9//4v/l/+n/7v/0//v/AQAHAA4AFAAaAB4AIwAmACgAKgArACoAKAAlACIAHQAXABAACAABAPn/8v/r/+X/4P/c/9r/2P/Y/9j/2v/c/97/4v/l/+r/7//0//n//v8DAAgADQARABUAFwAZABsAGwAcABwAHAAbABsAGQAYABYAFAARAA0ACQAGAAEA/f/5//X/8v/u/+v/6P/l/+P/4f/g/9//3v/e/9//4f/k/+j/7f/z//n///8GAA0AEwAZAB8AIwAnACoALAAtAC0ALAApACUAIAAaABQADAAEAP3/9f/t/+f/4f/d/9r/2P/Y/9j/2f/b/93/4f/l/+n/7v/0//n///8DAAkADgASABYAGQAbAB0AHQAeAB4AHQAdABwAGwAZABcAFQASAA8ACwAHAAMA///7//f/8//w/+z/6f/m/+T/4v/g/9//3v/d/97/3//i/+b/6//w//f//f8EAAsAEQAYAB4AIwAnACoALQAuAC4ALQArACcAIgAdABYADgAGAP3/9v/t/+f/4f/c/9j/1v/V/9X/1v/X/9r/3f/h/+b/6//x//b//P8CAAcADAARABUAGAAbABwAHQAdAB0AHQAbABsAGgAYABYAFAARAA4ACwAGAAMA///7//f/8//w/+z/6f/n/+T/4v/f/97/3f/c/9z/3f/g/+P/5//t//P/+v8BAAgADwAVABwAIQAmACoALQAvAC8ALgAtACoAJQAfABgAEQAIAAAA+P/v/+j/4f/c/9j/1f/T/9P/0//V/9f/2//f/+T/6f/v//X/+/8AAAYADAARABUAGQAcAB0AHgAeAB4AHgAcABwAGgAZABcAFQASAA8ADAAIAAQAAAD9//n/9f/y/+7/6//o/+X/4//h/97/3f/c/9z/3f/f/+L/5v/s//L/+f8AAAYADgAVABwAIgAnACsALwAxADIAMQAwAC0AKQAjAB0AFQAMAAQA+//z/+v/5P/e/9n/1v/T/9P/0//U/9f/2v/e/+P/6P/u//T/+/8BAAYADAASABYAGgAdAB8AIAAhACAAHwAeAB0AHAAaABgAFQATABAADAAJAAUAAgD+//r/9v/z/+//7P/p/+b/4//h/9//3f/c/9v/3P/d/+D/5P/p/+//9v/9/wQACwASABkAIAAlACoALgAxADIAMgAxAC4AKgAlAB8AFwAOAAYA/f/0/+z/5P/d/9j/1P/S/9D/0P/R/9P/1v/b/9//5f/r//H/+P///wQACwAQABUAGQAcAB8AIAAgACAAIAAeAB0AGwAZABcAFQASAA8ADAAJAAUAAgD+//r/9//z/+//7P/p/+b/4//h/97/3P/b/9r/2v/b/97/4f/m/+z/8v/6/wAACAAPABcAHgAkACkALQAwADIAMwAyADAALQAoACEAGgARAAgA///2/+3/5f/e/9n/1P/Q/8//zv/P/9H/1P/Y/93/4v/p/+//9//9/wMACgAQABYAGgAdACAAIQAiACIAIQAgAB4AHAAbABgAFgATABEADQAKAAYAAwAAAPz/+f/1//H/7v/r/+j/5f/i/+D/3v/c/9v/2//b/93/4f/l/+v/8f/4////BgAOABYAHQAkACoALgAyADQANgA1ADMAMAArACUAHgAWAAwAAwD6//H/6P/h/9r/1f/R/87/zv/O/8//0v/W/9v/4f/n/+3/9f/8/wMACQAQABUAGgAeACEAIgAjACMAIgAhAB8AHQAbABkAFgAUABEADQAKAAcABAAAAP3/+f/2//L/7//s/+n/5v/j/+D/3v/c/9r/2v/a/9z/3//j/+j/7v/1//z/BAALABMAGwAiACgALQAxADQANgA2ADQAMgAtACgAIAAYAA8ABQD8//P/6v/i/9v/1f/Q/83/y//L/8z/z//T/9j/3f/k/+r/8v/5/wEABwAOABQAGQAdACEAIgAjACMAIwAhACAAHgAbABkAFgATABAADQAKAAYAAwAAAP3/+f/2//P/7//s/+j/5v/i/+D/3f/b/9n/2f/Z/9r/3f/g/+X/6//x//n/AAAIABEAGAAgACYALAAwADQANgA3ADYAMwAwACoAIwAbABIACAD///b/7P/j/9v/1f/Q/83/y//K/8v/zf/Q/9X/2//h/+n/8P/4////BgANABQAGgAeACIAJAAlACUAJQAjACIAHwAdABsAFwAVABEADgALAAgABQACAP7/+//4//X/8f/u/+r/6P/k/+L/3//d/9v/2v/a/9v/3f/g/+T/6v/w//j///8GAA8AFwAfACYALAAxADUANwA5ADgANgAzAC0AJwAfABYADAACAPn/7//m/97/1//R/83/yv/J/8n/y//O/9P/2f/f/+b/7v/2//7/BQANABMAGQAeACIAJQAmACcAJgAlACMAIQAeABwAGAAVABIADgALAAgABQACAP///P/4//X/8v/u/+v/6P/l/+L/3//d/9v/2f/Z/9n/2//e/+L/5//u//T//P8DAAsAFAAcACMAKgAvADQANwA4ADkANwA0AC8AKQAiABgADwAFAPv/8f/o/9//1//R/8z/yP/H/8b/yP/L/8//1f/b/+P/6v/z//v/AgAKABEAGAAdACEAJAAmACcAJgAlACQAIQAeABwAGAAVABEADgALAAgABQACAP///P/5//X/8v/v/+z/6P/m/+L/4P/d/9v/2f/Z/9n/2v/d/+D/5f/r//L/+f8BAAkAEQAZACIAKQAuADMANwA5ADoAOQA2ADIALAAlABwAEwAIAP//9f/r/+L/2v/S/83/yf/G/8b/xv/J/87/0//Z/+D/6P/w//n/AQAJABEAGAAdACIAJQAnACgAKAAnACYAIwAgAB0AGgAWABMADwAMAAkABQADAAAA/f/6//f/8//w/+3/6v/n/+T/4f/e/9z/2v/Z/9n/2v/c/9//5P/p//D/9////wYADwAXACAAJwAuADMANwA6ADsAOgA4ADQALwAoACAAFgAMAAIA+P/u/+T/3P/U/83/yf/G/8X/xf/H/8v/0P/W/97/5v/u//f///8HAA8AFgAdACIAJgAoACkAKQApACcAJQAiAB4AGwAXABMAEAAMAAkABgADAAAA/f/6//f/9P/x/+7/6//n/+X/4f/f/9z/2v/Z/9j/2f/b/97/4v/n/+3/9P/8/wQADAAVAB0AJQAsADIANgA5ADsAOwA5ADYAMQAqACIAGQAPAAUA+//w/+b/3f/V/87/yf/F/8P/w//E/8j/zf/T/9r/4v/q//T//P8FAA0AFQAbACEAJQAoACoAKgAqACgAJgAjAB8AHAAYABQAEAAMAAkABgADAAAA/f/7//f/9f/x/+//6//o/+X/4v/f/93/2v/Z/9j/2f/a/93/4P/l/+v/8v/5/wEACQASABsAIwAqADEANQA5ADsAPAA7ADgAMwAtACYAHAATAAgA/v/0/+r/4P/X/9D/yf/F/8P/wv/D/8X/yv/Q/9f/3//o//H/+/8DAAsAFAAbACEAJQApACsALAArACoAKAAlACEAHgAZABUAEQANAAoABgADAAEA/v/7//n/9f/z//D/7f/q/+b/5P/g/97/2//a/9n/2f/a/9z/4P/k/+n/8P/4////BwAQABkAIQApAC8ANQA5ADwAPQA9ADoANgAwACkAIAAXAAwAAgD4/+3/4//Z/9L/y//G/8L/wf/C/8T/yP/N/9T/3P/l/+7/+P8BAAkAEgAZACAAJQApACsALQAsACsAKQAmACMAHgAaABYAEgANAAoABgADAAAA/v/7//j/9v/z//D/7f/q/+f/5P/h/97/3P/a/9n/2f/Z/9v/3v/i/+f/7f/0//z/BAANABUAHgAmAC0AMwA4ADsAPQA9ADsANwAyACsAIwAaABAABQD7//D/5f/b/9P/y//G/8L/wP/A/8L/xf/K/9H/2f/i/+v/9f/+/wcAEAAYAB8AJAApACwALQAuAC0AKwAoACQAIAAcABcAEwAOAAsABwAEAAEA/v/8//n/9v/z//H/7v/r/+j/5f/i/9//3P/a/9n/2P/Z/9r/3f/h/+b/6//y//r/AQAKABMAHAAkACsAMgA3ADsAPQA+ADwAOQA0AC4AJgAdABMACAD+//T/6f/e/9X/zf/H/8L/wP+//8D/w//I/87/1v/f/+j/8v/8/wUADgAWAB4AJAApACwALgAvAC4ALQAqACYAIgAeABkAFAAQAAwACAAEAAEA///8//r/9//0//L/7//s/+n/5v/j/+D/3v/b/9r/2f/Z/9v/3P/g/+T/6v/w//j///8HABAAGQAiACoAMAA2ADoAPQA+AD4AOwA3ADEAKQAhABcADAABAPf/7P/i/9j/z//I/8L/v/++/77/wP/F/8v/0v/b/+T/7v/5/wIACwAUABwAIwAoACwALwAwAC8ALgArACgAIwAfABoAFQAQAAwACAAEAAEA/v/8//n/9//0//L/7//s/+n/5v/j/+D/3v/c/9r/2f/Z/9r/2//e/+P/6P/u//X//f8EAA0AFgAfACcALgA0ADkAPAA+AD4APAA4ADMALAAjABkADwAEAPr/7//k/9r/0f/J/8P/v/+9/73/vv/D/8j/z//Y/+H/6//2////CQASABoAIQAnACwALwAwADAALwAtACkAJQAgABwAFgARAA0ACQAEAAEA///8//n/9//1//L/8P/t/+r/5//k/+L/3//c/9v/2v/Z/9r/2//e/+H/5v/s//P/+/8CAAsAFAAcACUALAAzADgAPAA+AD8APQA6ADUALwAnAB4AEwAIAP7/8//o/93/1P/M/8X/wP+9/7z/vf/A/8b/zf/V/97/6P/z//3/BgAQABkAIQAnACwALwAxADIAMQAuACsAJwAjAB0AGAATAA4ACgAFAAIA///9//r/9//1//P/8P/u/+v/6P/l/+L/4P/d/9z/2v/a/9r/3P/d/+D/5f/q//H/+f8AAAgAEQAaACIAKgAxADcAOwA+AD8APgA7ADcAMQApACEAFwAMAAEA9v/r/+D/1v/N/8b/wf+9/7v/u/++/8P/yf/R/9r/5f/v//r/BAANABYAHwAmACsALwAxADIAMQAwAC0AKQAkAB8AGgAUAA8ACgAGAAIA///8//r/9//1//L/8f/u/+v/6f/m/+P/4P/e/9z/2v/a/9n/2v/c/9//5P/o/+7/9v/+/wUADgAXAB8AJwAvADUAOQA9AD4APgA8ADkAMwAsACQAGgAQAAQA+v/u/+P/2f/Q/8f/wf+9/7v/u/+8/8D/x//O/9f/4f/r//b/AQAKABQAHQAkACoALwAyADMAMwAxAC4AKwAmACEAHAAWABAACwAHAAMAAAD9//r/+P/1//P/8f/v/+z/6f/n/+T/4f/f/93/2//a/9r/2//c/9//4v/n/+3/9P/7/wMADAAUAB0AJQAtADMAOQA9AD4APwA+ADsANgAvACcAHgATAAgA/f/y/+f/3P/T/8r/w/++/7v/uv+7/77/xP/L/9T/3v/o//P//v8IABIAGwAjACoALwAyADQANAAzADAALQAoACMAHgAYABIADQAIAAMAAAD9//r/+P/1//T/8f/u/+3/6v/n/+X/4v/g/97/3P/b/9r/2//c/97/4f/m/+z/8v/5/wEACQASABoAIwAqADEANwA7AD4APwA+ADwANwAxACoAIQAXAAwAAQD2/+r/3//V/8z/xf+//7v/uf+6/7z/wf/I/9D/2v/k/+//+/8FAA8AGQAhACgALgAyADQANQA0ADIALgAqACQAHwAZABMADgAJAAQAAAD9//r/9//1//P/8f/u/+3/6v/o/+X/4v/g/97/3f/b/9v/2//c/97/4f/l/+r/8P/3//7/BgAOABcAIAAoAC8ANQA6AD0APwA+AD0AOQAzACwAJAAaAA8ABAD5/+3/4v/Y/87/x//A/7v/uf+5/7v/v//F/83/1v/g/+z/9/8CAAwAFgAfACcALQAyADQANgA1ADMAMAAsACcAIQAbABUADwAKAAUAAQD+//v/+P/1//P/8f/w/+3/6//o/+b/5P/h/9//3f/c/9v/2//c/97/4P/k/+n/7//1//3/BAAMABUAHQAlAC0AMwA5AD0APgA/AD4AOwA1AC8AJwAeABMACAD9//H/5v/b/9H/yf/C/73/uf+4/7r/vf/C/8r/0//d/+j/9P///wkAFAAdACUALAAxADUANgA2ADUAMgAuACkAIwAdABgAEQAMAAYAAgD///v/+P/2//P/8f/w/+3/7P/p/+f/5P/i/+D/3v/d/9v/2//c/93/4P/j/+j/7f/z//v/AgAKABIAGgAjACoAMQA3ADsAPgA/AD4AOwA3ADEAKQAgABYACwAAAPX/6v/e/9T/y//D/77/uv+4/7j/u//A/8f/z//Z/+T/8P/7/wYAEQAaACMAKwAwADQANgA2ADYAMwAvACoAJQAfABkAEwANAAcAAgD///v/+P/1//P/8f/v/+3/7P/p/+f/5f/i/+D/3v/d/9z/2//c/93/3//i/+f/7P/y//n///8HAA8AFwAgACgALwA1ADkAPAA+AD4APQA5ADMALAAjABoADwADAPn/7f/i/9f/zv/G/7//uv+4/7j/uv++/8T/zP/W/+D/7P/4/wMADgAYACEAKQAvADQANgA4ADcANAAxACwAJwAhABsAFQAOAAkABAD///z/+P/2//P/8f/v/+7/7P/p/+j/5v/j/+H/3//e/93/3P/c/93/3//i/+b/6//w//f//v8FAA0AFQAeACUALQAzADgAPAA+AD4APQA6ADUALwAmAB0AEwAHAPz/8f/l/9v/0f/I/8H/vP+5/7j/uf+8/8L/yf/S/93/6P/0/wAACwAVAB8AJwAuADMANgA3ADgANgAyAC4AKgAkAB0AFwARAAoABQAAAPz/+f/2//P/8f/v/+3/7P/q/+j/5v/k/+L/4P/f/93/3f/c/93/3//h/+X/6v/v//X//P8DAAoAEgAbACMAKgAxADYAOgA9AD4APgA7ADcAMAApACAAFQAKAP//9P/p/97/0//L/8P/vf+5/7f/uP+6/7//xv/P/9n/5P/w//z/BwASABwAJQAsADIANgA4ADgANwA0ADAAKwAmACAAGQASAA0ABgABAP7/+f/2//P/8f/v/+3/7P/q/+j/5//k/+L/4f/f/97/3f/c/93/3//h/+X/6P/u//P/+v8BAAgAEAAYACAAJwAuADQAOQA8AD4APgA7ADgAMwArACMAGQAOAAMA+P/s/+H/1//O/8X/v/+6/7j/t/+5/73/xP/M/9X/4P/t//j/BAAPABoAIwArADEANQA4ADkAOAA1ADIALQAnACIAGwAVAA4ACAACAP7/+v/3//P/8f/v/+3/7P/q/+n/5//l/+P/4v/g/97/3v/d/97/3v/h/+T/6P/t//L/+f///wYADgAVAB4AJQAsADIANwA7AD0APgA9ADkANAAtACUAHAASAAcA/P/w/+X/2v/R/8j/wf+7/7j/t/+4/7z/wf/J/9L/3f/o//X/AAALABcAIQApADAANQA4ADkAOAA3ADMALwAqACMAHgAXABAACQAEAP//+//3//T/8f/v/+3/7P/q/+n/5//l/+P/4v/g/9//3v/d/97/3//h/+P/5//s//H/9//9/wQACwATABsAIgApADAANQA6ADwAPQA9ADoANgAvACgAHwAVAAoA///0/+j/3v/U/8v/w/+9/7n/t/+3/7r/v//G/8//2f/l//D//P8IABQAHgAnAC4ANAA3ADkAOQA4ADUAMQAsACYAIAAZABIACwAFAAAA/P/3//T/8f/v/+3/7P/q/+n/5//m/+T/4//h/9//3v/e/97/3//g/+P/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9//7////AwAIAA0AEgAXAB0AIQAmACoALQAvADAAMQAvACsAJwAhABoAEwAKAAEA+P/v/+X/3P/U/83/x//D/8D/v//A/8T/yf/Q/9n/4//u//n/BAAOABgAIQApAC8ANAA3ADgAOAA2ADMALgApACIAHAAUAA0ABgAAAPr/9P/w/+z/6f/m/+X/4//j/+L/4v/i/+L/4v/j/+T/5f/n/+n/7P/v//P/9v/6////AgAHAAwAEQAWABsAIAAkACgAKwAuAC8ALwAuACwAKAAiABwAFQANAAQA+//y/+n/4P/X/9D/yf/F/8H/wP/B/8P/yP/O/9b/4P/r//X/AAALABUAHgAmAC0AMgA2ADgAOAA2ADMALwAqACQAHgAXAA8ACAACAPz/9v/x/+3/6v/n/+X/5P/i/+L/4v/h/+L/4v/j/+T/5f/n/+n/7P/v//L/9v/6//7/AQAGAAsADwAUABkAHgAjACYAKgAsAC4ALwAuACsAKAAjAB4AFgAPAAYA/v/1/+z/4//b/9L/zP/H/8P/wf/B/8P/x//N/9X/3v/n//L//f8HABIAGwAkACsAMAA0ADcANwA2ADQAMAAsACYAIAAZABEACwAEAP7/+P/z/+//6//o/+X/5P/j/+L/4f/h/+H/4v/j/+T/5f/n/+n/7P/v//H/9f/5//3/AQAFAAoADgATABgAHAAhACQAKAArACwALQAtACsAKAAkAB8AGAARAAkAAAD4/+//5v/d/9X/z//J/8X/w//C/8P/x//M/9P/2//k/+//+v8EAA4AGAAgACgALgAzADUANwA2ADQAMQAtACgAIgAbABQADQAGAP//+v/0/+//6//o/+b/5P/j/+L/4f/h/+H/4v/j/+T/5f/n/+n/6//u//H/9f/4//3/AAAEAAgADQASABYAGwAfACMAJgApACsALAAsACsAKAAkACAAGgATAAsAAgD6//L/6f/g/9j/0f/M/8f/xf/D/8T/xv/L/9L/2f/i/+z/9/8AAAsAFAAeACUALAAxADQANgA2ADUAMgAuACkAIwAdABYADwAIAAEA/P/2//H/7P/p/+b/5P/j/+L/4f/h/+H/4v/j/+T/5f/m/+n/6//u//H/9P/4//z///8DAAgADAAQABUAGQAeACIAJQAoACoAKwArACoAKAAlACAAGwAVAA0ABQD9//X/7P/j/9v/1P/O/8n/xv/E/8T/x//K/9D/2P/g/+n/8//9/wcAEQAaACMAKQAvADMANQA1ADUAMwAvACsAJQAfABgAEQAKAAMA/v/4//P/7v/q/+f/5f/j/+L/4f/h/+H/4f/i/+P/5f/m/+n/6//t//H/9P/4//v///8CAAcACwAPABMAGAAcACAAIwAmACgAKgAqACoAKAAlACEAHAAWAA8ABwD///f/7//m/97/1//R/8v/yP/G/8b/x//K/8//1v/e/+f/8P/6/wQADQAXAB8AJwAtADEANAA1ADQAMwAwACsAJgAhABoAEwAMAAUA///6//T/8P/r/+j/5f/j/+L/4f/h/+H/4f/i/+P/5f/m/+n/6//t//D/8//3//v///8CAAYACgAOABMAFwAbAB8AIgAlACcAKAApACkAKAAlACEAHQAXABAACQABAPr/8f/p/+H/2v/T/87/yv/I/8f/x//K/87/1f/b/+T/7v/3/wEACgAUABwAJAAqAC8AMgA0ADQAMwAwAC0AKAAiABwAFQAPAAcAAQD8//b/8f/t/+n/5v/k/+L/4f/h/+D/4f/i/+P/5P/m/+j/6v/t//D/8//2//r//v8BAAUACQANABIAFgAZAB0AIQAjACYAJwAoACgAJwAlACIAHQAYABEACwADAPz/9P/s/+T/3f/W/9D/zP/J/8j/yP/K/87/1P/a/+L/6//0//7/BwAQABkAIQAoAC0AMAAzADMAMwAxAC0AKQAkAB4AFwARAAoAAwD+//j/8//u/+r/5//k/+P/4f/h/+D/4f/i/+P/5P/m/+j/6v/t//D/8//2//r//f8AAAQACAAMABAAFAAYABwAHwAiACQAJgAnACcAJwAkACIAHgAZABMADAAFAP7/9v/u/+f/3//Z/9P/zv/L/8n/yf/L/87/0v/Z/+D/6P/y//r/BAANABYAHgAlACsALwAxADMAMgAxAC4AKgAlAB8AGQASAAwABQD///r/9P/w/+z/6P/l/+P/4f/h/+D/4P/h/+P/5P/m/+f/6v/s/+//8v/2//n//f8AAAMACAALABAAEwAXABsAHgAhACMAJQAmACYAJQAkACIAHgAaABQADgAHAAAA+P/x/+n/4v/b/9b/0f/N/8v/yv/L/87/0v/Y/9//5//v//j/AQAKABMAGwAiACgALQAvADEAMQAwAC4AKwAmACEAGwAVAA4ACAABAPz/9//y/+3/6f/m/+P/4v/h/+D/4P/h/+L/5P/l/+f/6v/s/+//8v/1//j//P8AAAMABwAKAA8AEgAWABkAHQAfACIAJAAlACUAJQAkACEAHgAaABUADwAJAAIA+//0/+z/5f/e/9j/0//P/83/zP/M/87/0v/X/93/5P/t//X//v8HABAAGAAfACUAKgAuADAAMQAwAC4ALAAnACIAHQAXABAACgADAP7/+f/z/+7/6v/n/+T/4v/h/+D/4f/h/+L/4//l/+f/6f/r/+7/8f/1//j//P///wIABgAKAA4AEQAVABgAHAAeACAAIgAjACQAJAAjACEAHgAbABYAEAAKAAMA/f/2/+//5//g/9v/1f/R/8//zf/N/8//0v/W/9z/4//r//P//P8EAA0AFQAcACMAKAAsAC4AMAAwAC4ALAAoACMAHgAYABIADAAFAAAA+//1//D/7P/o/+X/5P/i/+H/4P/h/+H/4//k/+b/6P/r/+7/8f/0//j/+//+/wIABQAJAA0AEQAUABcAGgAdAB8AIQAiACMAIwAiACEAHgAbABcAEQALAAUA///4//H/6v/j/93/2P/U/9H/z//P/8//0v/W/9v/4v/p//H/+f8BAAkAEgAZACAAJQAqAC0ALwAvAC4ALAApACUAIAAaABQADgAIAAEA/f/3//L/7f/p/+f/5P/i/+H/4P/h/+H/4v/k/+b/6P/r/+3/8P/0//f/+v/+/wEABQAIAAwAEAATABYAGQAcAB4AIAAhACIAIgAiACAAHgAbABcAEgAMAAYAAAD6//P/7P/m/9//2v/W/9L/0P/Q/9D/0v/W/9r/4P/n/+//9////wcADwAXAB0AIwAnACsALQAuAC0ALAApACUAIQAcABYADwAKAAMA/v/5//T/7//r/+j/5f/i/+L/4f/h/+H/4v/k/+X/5//q/+3/8P/z//f/+v/+/wEABAAHAAsADwASABUAGAAbAB0AHwAgACEAIQAgACAAHgAbABcAEgANAAcAAgD8//X/7v/o/+L/3P/Y/9X/0v/R/9H/0//W/9r/4P/m/+3/9f/8/wQADAATABoAIAAlACkALAAtAC0ALAApACYAIgAdABcAEgAMAAUAAAD7//b/8f/s/+n/5v/j/+L/4f/h/+H/4v/j/+X/5//p/+z/7//y//b/+f/9/wAAAwAHAAoADgARABUAFwAaABwAHgAgACAAIAAgAB8AHQAbABcAEwAOAAkAAwD9//f/8P/q/+X/3v/a/9b/1P/T/9L/1P/W/9r/3//l/+v/8//6/wIACQARABgAHgAjACcAKgAsACwAKwApACcAIwAeABkAEwANAAcAAgD9//j/8//u/+r/5//k/+P/4f/h/+H/4v/j/+T/5//p/+z/7//y//X/+f/8////AgAGAAkADQAQABQAFwAZABwAHQAfAB8AIAAgAB8AHQAaABcAEwAPAAkABAD///n/8//s/+f/4f/d/9n/1v/U/9T/1f/X/9r/3v/k/+r/8f/4////BwANABUAGwAgACQAKAAqACsAKwApACcAIwAfABoAFQAPAAkABAD///r/9P/w/+z/6P/l/+P/4v/h/+H/4v/j/+T/5v/o/+v/7v/x//X/+P/8////AgAFAAkADAAPABMAFgAYABsAHAAeAB4AHwAfAB4AHAAaABcAEwAPAAoABQAAAPr/9f/u/+n/4//f/9v/2P/W/9X/1f/X/9r/3v/j/+n/7//2//3/BQALABIAGAAeACIAJgAoACoAKgApACcAJAAgABsAFgARAAsABQAAAPz/9v/y/+3/6v/n/+T/4//i/+H/4v/i/+T/5f/o/+r/7f/x//T/+P/7//7/AQAEAAgACwAPABIAFQAXABkAHAAdAB4AHgAeAB4AHAAaABcAFAAPAAsABgABAPz/9v/w/+v/5v/h/93/2v/Y/9f/1//Y/9r/3v/j/+j/7v/1//v/AgAIAA8AFQAbACAAIwAmACgAKQAoACcAJAAhAB0AGAASAA0ABwACAP3/+P/0/+//6//o/+X/4//i/+L/4f/i/+T/5f/n/+r/7f/w//P/9//7//7/AQAEAAcACgAOABEAFAAXABkAGwAcAB0AHgAdAB0AGwAZABcAFAAQAAsABwACAP3/+P/y/+3/6P/j/9//2//Z/9j/2P/Z/9v/3v/i/+f/7f/z//r/AAAGAA0AEwAYAB0AIQAkACcAKAAnACYAJAAhAB0AGQAUAA4ACQAEAP//+v/1//H/7f/p/+b/5P/j/+L/4v/i/+P/5f/n/+n/7P/v//P/9v/6//3/AAADAAYACgANABAAEwAVABgAGgAbABwAHQAdABwAGwAZABcAFAAQAAwABwADAP7/+f/0/+//6v/l/+H/3v/b/9r/2v/a/9z/3v/i/+f/7P/y//j//v8EAAoAEAAWABsAHwAiACUAJgAnACYAJAAiAB4AGgAVABAACwAFAAAA/P/3//P/7v/r/+j/5v/k/+L/4v/i/+P/5P/m/+n/6//v//L/9f/5//3/AAADAAYACQAMAA8AEgAVABcAGQAbABwAHAAcABwAGwAZABYAEwAQAAwACAAEAP//+v/2//D/7P/n/+P/4P/d/9v/2//b/9z/3//i/+f/6//x//f//P8CAAgADgATABgAHAAgACMAJQAlACUAJAAhAB8AGwAWABEADAAHAAIA/v/5//X/8P/s/+n/5//l/+T/4v/i/+P/5P/m/+j/6//u//H/9f/4//z///8CAAUACAAMAA8AEgAUABcAGAAaABsAHAAcABsAGgAYABYAEwAQAAwACAAEAAAA+//3//L/7f/p/+X/4f/f/93/3P/c/93/4P/i/+b/6//w//b/+/8AAAYACwARABYAGgAeACEAIwAkACQAIwAhAB8AGwAXABMADgAJAAMA///7//b/8v/u/+v/6P/m/+T/4//j/+P/5P/l/+f/6v/t//H/9P/4//v//v8BAAQABwALAA4AEAAUABYAFwAZABoAGwAbABsAGQAYABYAEwAQAAwACQAFAAEA/f/4//P/7//r/+f/4//h/9//3v/e/97/4P/j/+b/6//v//T/+v///wQACQAPABMAGAAcAB8AIQAjACMAIwAhAB8AHAAYABQADwAKAAUAAQD9//j/9P/w/+z/6f/n/+X/5P/j/+P/5P/l/+f/6f/t//D/8//3//r//v8AAAQABwAKAA0AEAATABUAFwAZABoAGwAbABoAGQAYABYAEwAQAA0ACQAFAAEA/f/5//X/8f/s/+j/5f/i/+D/3//f/+D/4f/k/+f/6//v//T/+f/9/wMABwAMABEAFQAZAB0AHwAhACIAIgAhAB8AHAAZABUAEAAMAAcAAgD///r/9v/y/+7/6//o/+b/5f/k/+P/5P/l/+f/6f/s/+//8//2//n//f8AAAMABgAJAAwADwASABQAFgAYABkAGgAaABoAGQAXABUAEwAQAAwACQAFAAIA/v/6//b/8v/u/+r/5//k/+L/4f/g/+H/4v/k/+f/6//v//P/+P/8/wEABQAKAA8AEwAXABoAHQAfACAAIQAgAB8AHAAZABUAEQANAAgABAAAAPz/9//0//D/7f/q/+j/5f/k/+T/5P/l/+b/6f/r/+7/8v/1//n//P///wIABQAIAAsADgARABMAFgAXABkAGgAaABoAGAAXABUAEgAQAA0ACQAFAAIA///7//f/8//v/+v/6P/m/+T/4v/i/+L/4//l/+f/6//v//L/9//7////BAAIAA0AEQAVABgAGwAdAB8AHwAfAB4AHAAaABYAEgAOAAoABQABAP7/+f/1//L/7v/r/+n/5v/l/+T/5P/l/+b/6P/r/+7/8f/0//j/+////wEABAAHAAsADQAQABMAFQAXABgAGQAaABkAGAAXABUAEgAQAAwACQAGAAMA///8//j/9P/w/+3/6v/n/+X/5P/j/+P/5P/m/+j/6//v//L/9v/6//7/AwAGAAsADwASABYAGQAbAB0AHgAeAB4AHAAaABYAEwAPAAsABwACAP//+//3//P/8P/t/+r/5//m/+X/5f/l/+b/6P/q/+3/8P/0//f/+//+/wAAAwAGAAoADAAPABIAFAAWABgAGAAZABkAGAAXABUAEgAQAA0ACQAGAAMAAAD8//n/9f/y/+7/6//p/+b/5f/k/+T/5f/n/+n/6//v//L/9v/6//3/AgAFAAkADQAQABQAFwAaABsAHQAdAB0AGwAZABcAEwAQAAwACAAEAAAA/f/5//X/8f/u/+z/6f/n/+b/5f/l/+b/6P/q/+z/7//z//b/+f/9/wAAAgAGAAkADAAPABEAEwAVABcAGAAZABkAGAAXABQAEgAPAAwACgAGAAMAAAD8//n/9v/z/+//7P/q/+j/5v/m/+b/5v/o/+n/7P/v//L/9v/5//3/AQAEAAcACwAOABIAFQAXABoAGwAbABsAGwAZABcAFAARAA0ACQAGAAEA/v/7//f/8//w/+3/6v/o/+f/5v/m/+b/5//p/+z/7//y//X/+f/8////AgAFAAgACwANABAAEwAUABYAGAAYABgAFwAWABQAEgAPAA0ACQAGAAMAAAD9//r/9//0//H/7v/r/+r/5//n/+f/5//p/+r/7f/v//P/9f/5//z///8CAAUACQAMABAAEgAVABcAGQAaABoAGgAZABcAFAARAA4ACgAHAAMAAAD9//n/9f/y/+//7P/p/+j/5//m/+b/5//p/+v/7v/x//T/+P/7//7/AQAEAAcACgANAA8AEgAUABUAFwAYABgAFwAWABQAEgAPAAwACgAGAAMAAAD+//v/9//0//H/7//t/+v/6f/o/+j/6f/q/+v/7f/w//P/9v/5//v///8CAAQACAALAA4AEQATABYAFwAZABkAGQAYABcAFAASAA8ACwAIAAQAAQD+//r/9//z//D/7v/r/+n/6P/n/+f/5//p/+v/7f/w//T/9//6//3/AAADAAYACQAMAA4AEQATABUAFgAXABgAFwAWABQAEgAQAA0ACgAGAAMAAAD+//v/+P/1//L/8P/u/+z/6v/p/+r/6v/q/+z/7v/x//P/9v/5//v//v8BAAQABgAJAAwADgARABQAFQAXABcAGAAXABYAFAASAA8ADAAJAAUAAgD///z/+f/1//L/7//s/+v/6f/o/+f/6P/p/+v/7f/w//P/9v/5//z/AAACAAUACAALAA0AEAASABUAFgAXABcAFwAWABQAEgAQAA0ACgAHAAMAAQD+//v/+P/2//P/8f/v/+3/6//r/+r/6//s/+3/7//x//P/9v/5//v//f8AAAMABQAHAAoADQAPABIAFAAVABYAFwAWABYAFAASABAADQAKAAcAAwABAP7/+v/3//T/8f/u/+v/6v/o/+j/6P/p/+v/7f/v//L/9f/4//z///8BAAQABwAKAA0ADwASABQAFQAWABcAFwAWABQAEgAQAA0ACgAHAAQAAQD+//v/+f/2//T/8f/v/+7/7f/s/+z/7P/t/+7/8P/y//T/9//5//v//f8AAAIABAAGAAkACwAOABAAEgATABUAFQAVABUAFAASABAADQALAAgABAABAP///P/5//X/8v/w/+3/6//q/+n/6f/p/+r/7P/v//H/9P/3//r//v8AAAMABgAJAAwADgARABMAFQAWABcAFgAWABQAEgAQAA0ACgAHAAQAAQD///z/+f/2//T/8v/w/+//7f/t/+z/7f/t/+//8f/z//X/9//5//v//f///wEAAwAFAAcACQAMAA4AEAARABMAFAAUABQAEwASABAADQALAAgABgADAAAA/v/6//f/9P/x/+//7P/r/+r/6f/q/+r/7P/u//D/9P/3//r//f8AAAIABQAIAAsADQAQABIAFAAVABYAFgAWABQAEwAQAA0ACgAHAAQAAQD///z/+f/3//X/8v/x//D/7v/u/+7/7v/v//D/8v/0//b/9//6//z//f///wEAAwAEAAYACAAKAAwADgAQABEAEgASABMAEgARAA8ADgALAAkABwAEAAEA///8//n/9v/z//D/7v/s/+v/6v/q/+v/7P/u//D/8//2//n//P///wEABAAHAAoADAAPABIAEwAVABUAFgAVABQAEwAQAA4ACgAIAAQAAQD///z/+v/3//X/8//x//D/7//v/+7/7//w//H/8v/0//b/+P/6//z//f///wEAAwAEAAUABwAJAAoADAAOAA8AEQARABIAEQARAA8ADQAMAAoABwAFAAIAAAD+//r/+P/0//L/7//t/+z/6//r/+v/7P/u//D/8v/1//j/+//+/wAAAwAGAAkADAAOABEAEgAUABUAFgAVABQAEwAQAA4ACwAIAAUAAgD///z/+v/3//X/8//y//D/8P/w/+//7//x//L/8//1//f/+f/7//z//f///wAAAgADAAQABgAHAAkACgAMAA4ADgAQABAAEAAQAA8ADQAMAAoACAAGAAMAAQD///z/+f/2//T/8f/v/+3/7P/s/+v/7P/u/+//8f/0//f/+v/9////AgAFAAgACwANABAAEgATABUAFQAVABQAEwAQAA4ACwAIAAUAAgD///3/+v/3//X/9P/y//H/8P/w//D/8P/x//L/9P/2//j/+v/7//3//v///wEAAgADAAQABQAGAAcACQAKAAwADQAOAA4ADwAPAA4ADQAMAAoACQAHAAQAAgAAAP7/+//4//X/8//w/+//7f/s/+z/7f/u/+//8f/z//b/+f/8////AQAEAAcACgAMAA8AEQASABQAFAAVABQAEwARAA4ADAAIAAYAAgD///3/+v/4//X/9P/y//H/8f/w//H/8f/y//T/9f/3//n/+v/8//3//v8AAAEAAgADAAMABAAFAAYABwAJAAoACwAMAA0ADQAOAA0ADQAMAAsACQAHAAUAAwABAP///P/6//f/9P/y//D/7//t/+3/7f/u/+//8f/z//X/+P/7//7/AAACAAYACAALAA4AEAASABMAFAAUABQAEgARAA8ADAAJAAYAAgAAAP3/+v/4//b/9P/z//L/8f/x//L/8v/z//T/9f/3//n/+//9//7///8AAAEAAgADAAMAAwAEAAUABgAHAAgACgAKAAsADAANAAwADAALAAoACQAIAAYABAACAAAA/v/7//n/9v/0//L/8P/v/+7/7f/u/+//8f/y//X/9//6//3///8CAAUABwAKAA0ADwARABIAFAAUABQAEwARAA8ADAAJAAYAAwAAAP7/+//4//b/9P/z//L/8f/y//L/8v/z//X/9v/4//r//P/9////AAABAAEAAgADAAMAAwADAAQABQAFAAYACAAJAAkACgALAAwACwALAAoACQAIAAYABQADAAEA///9//r/+P/1//P/8v/w/+//7v/v/+//8P/y//T/9v/5//z//v8BAAMABgAJAAwADgAQABIAEwATABMAEgARAA8ADQAKAAcAAwAAAP7/+//5//b/9P/z//L/8f/x//L/8//0//X/9//5//v//f/+////AAABAAIAAgADAAMAAwADAAMABAAEAAUABgAHAAgACQAJAAoACwAKAAoACQAIAAcABgAEAAIAAAD+//z/+f/3//X/8//x//D/8P/v//D/8P/y//T/9v/4//v//v8AAAIABQAIAAsADQAPABEAEgATABMAEgARAA8ADQAKAAcABAABAP7/+//5//b/9f/z//L/8v/y//L/8//0//b/+P/5//v//f///wAAAQACAAIAAwADAAMAAwACAAIAAwADAAQABQAFAAYABwAIAAkACQAKAAkACQAIAAcABgAFAAMAAQAAAP7/+//5//f/9f/z//H/8f/w//D/8P/y//P/9f/3//r//f///wEABAAHAAoADAAOABAAEQASABIAEgARAA8ADQALAAgABAABAP7/+//5//b/9f/z//L/8v/y//L/8//1//b/+P/6//z//v///wAAAgACAAMAAwADAAMAAwACAAIAAgACAAMAAwAEAAUABQAHAAcACAAIAAkACAAIAAcABgAFAAQAAgAAAP///f/6//j/9v/0//P/8v/x//H/8f/y//P/9f/3//n/+//+/wEAAwAGAAgACwANAA8AEQASABIAEgARABAADgALAAgABQABAP///P/5//f/9f/0//L/8v/y//P/9P/1//b/+f/6//3//v8AAAEAAgADAAMABAAEAAMAAwACAAIAAgABAAEAAQACAAMABAAFAAYABgAHAAgACAAIAAcABwAGAAQAAwABAAAA/v/8//r/+P/2//T/8//y//H/8f/y//P/9P/2//j/+v/9/wAAAgAEAAcACgAMAA4AEAARABIAEgARABAADQALAAgABQACAP///f/6//f/9f/z//L/8v/y//L/9P/1//f/+f/7//3///8AAAIAAwADAAQABAAEAAQAAwADAAIAAQABAAEAAAABAAEAAgADAAQABQAGAAYABwAHAAcABwAGAAUABAACAAEAAAD9//v/+v/4//b/9P/z//L/8v/y//P/9P/2//f/+v/8////AAADAAYACQALAA0ADwAQABEAEQARABAADQAMAAkABgACAAAA/f/6//f/9f/0//P/8v/y//P/9P/1//f/+f/7//3///8BAAIAAwAEAAUABQAFAAQAAwADAAIAAQABAAAAAAAAAAEAAQACAAIABAAFAAUABgAGAAcABwAGAAYABQADAAIAAAD///7/+//5//j/9v/0//P/8//z//P/9P/1//f/+f/7//7/AAACAAUABwAKAAwADgAPABAAEQAQAA8ADgAMAAkABwADAAAA/v/6//j/9v/0//P/8v/y//P/9P/1//f/+f/7//7/AAABAAMABAAFAAYABgAFAAUABAADAAIAAQAAAAAA/////wAAAAAAAAIAAgADAAQABQAGAAYABgAGAAYABQAEAAMAAQAAAP7//f/7//n/9//2//X/9P/z//P/9P/1//b/+P/6//3///8BAAMABgAJAAsADQAPABAAEAAQAA8ADgAMAAoABwAEAAEA/v/7//j/9v/0//P/8v/y//L/9P/1//f/+f/7//7/AAABAAMABQAGAAYABwAGAAYABQADAAIAAQAAAP/////+/////////wAAAQACAAMABAAFAAUABgAGAAYABgAFAAQAAwABAAAA/v/9//v/+f/3//b/9f/0//T/9P/1//b/9//5//z//v8AAAIABQAIAAoADAAOAA8ADwAQAA8ADgAMAAoACAAEAAEA///8//n/9v/0//P/8v/y//L/8//1//f/+f/8//7/AAABAAQABQAGAAcABwAHAAYABQAEAAMAAQAAAP///v/+//7//v/+//7///8BAAIAAwADAAUABgAGAAYABgAFAAUABAACAAEAAAD+//3/+//4//f/9v/1//X/9P/1//b/9//5//v//f///wEABAAGAAkACwANAA4ADwAPAA8ADgANAAsACAAFAAIA///8//n/9//1//P/8v/y//L/8//1//f/+f/7//7/AAACAAQABgAHAAgACAAIAAcABgAFAAMAAgAAAP///v/9//z//P/8//3//v///wAAAgACAAQABQAFAAYABgAGAAUABQAEAAIAAQD///7//P/7//j/9//2//X/9f/1//b/9//4//r//P/+/wAAAgAFAAcACgALAA0ADgAOAA8ADgANAAsACAAGAAIAAAD9//r/9//1//P/8v/y//L/8//1//b/+f/7//7/AAACAAUABgAIAAkACQAJAAgABwAFAAQAAgAAAP///f/8//z/+//7//z//f/+////AAACAAMABAAFAAUABgAGAAYABgAEAAQAAgABAP///v/8//r/+f/3//b/9v/1//b/9//4//n/+//9////AQAEAAYACAAKAAwADQAOAA4ADgANAAsACQAGAAMAAAD+//r/+P/1//T/8v/y//L/8//0//f/+P/7//7/AAACAAUABwAIAAkACgAKAAkACAAGAAQAAgABAP///f/8//v/+v/6//r/+//8//7//v8AAAIAAgAEAAUABgAGAAYABgAFAAUAAwACAAEA///+//v/+v/4//f/9v/2//b/9v/3//j/+v/8//7/AAACAAUABwAJAAsADAANAA4ADQANAAsACQAGAAMAAQD+//v/+P/2//T/8//y//L/8//0//b/+P/7//7/AAACAAUABwAJAAoACwAKAAoACQAHAAUAAwABAP///f/8//r/+v/5//n/+v/7//z//f/+/wAAAgADAAQABQAGAAcABwAGAAYABQADAAIAAQD///7/+//6//j/9//3//b/9v/3//j/+f/7//3/AAABAAQABgAIAAoADAANAA0ADQAMAAsACgAHAAQAAQD///z/+f/2//T/8//y//L/8//0//X/+P/7//7/AAACAAUACAAJAAsACwALAAsACgAIAAYABAABAAAA/v/8//r/+f/4//j/+P/5//r//P/9////AQACAAQABQAGAAcABwAHAAYABgAFAAMAAgAAAP///f/7//r/+f/3//f/9v/3//j/+f/6//z//v8AAAIABQAHAAkACgAMAAwADQAMAAsACgAHAAUAAgD///z/+v/3//X/8//y//P/8//0//X/+P/6//3/AAACAAUACAAJAAsADAAMAAwACwAJAAcABQACAAAA/v/7//r/+P/3//f/9//4//n/+v/8//7/AAABAAIABAAGAAcABwAIAAcABwAGAAUAAwACAAAA/v/9//v/+f/4//j/9//4//f/+P/6//v//f8AAAEAAwAGAAcACQALAAwADAAMAAsACgAIAAUAAgAAAP3/+v/4//X/9P/z//L/8//z//X/9//6//3/AAACAAUABwAKAAsADAANAAwACwAKAAgABQADAAAA///8//r/+P/3//b/9v/2//f/+f/6//z//v8AAAIAAwAFAAYABwAIAAgACAAHAAYABQADAAEAAAD+//3/+//5//n/+P/4//f/+P/5//r//P/+/wAAAgAEAAYACAAKAAsACwAMAAsACgAHAAUAAwAAAP7/+//4//b/9P/z//L/8//z//X/9//5//3///8CAAUABwAKAAwADQAOAA0ADAALAAgABgADAAEA///8//r/+P/2//X/9f/1//b/9//5//v//f///wEAAwAEAAYABwAIAAgACQAIAAgABgAFAAMAAQAAAP7//P/7//n/+P/3//f/+P/5//r/+//9////AQADAAUABwAJAAoACwAKAAoACQAIAAYAAwABAP///P/5//f/9P/z//P/8//z//X/9//5//z///8BAAUACAAKAAwADQAOAA4ADQAMAAoABwAFAAIAAAD9//r/+P/2//X/9P/0//T/9f/3//n/+//9////AgADAAYABwAIAAkACQAJAAkACAAGAAQAAwABAAAA/f/8//r/+f/4//f/9//4//n/+v/8//7/AAACAAQABgAIAAkACgALAAoACQAIAAYABAABAP///P/6//j/9f/0//P/8//z//X/9v/5//z///8BAAQABwAKAAwADgAPAA8ADgANAAsACAAGAAIAAAD9//r/+P/2//T/8//z//P/9P/1//j/+f/8//7/AAACAAUABgAIAAkACgAKAAoACQAIAAYABAACAAAA///+//v/+v/5//j/9//4//n/+v/7//3///8AAAIABQAHAAgACQAKAAoACQAIAAYABAACAP///f/6//j/9v/0//P/8//z//T/9v/4//v//v8BAAQABwAKAA0ADgAPAA8ADwAOAAwACgAHAAMAAQD+//v/+P/2//T/8//y//L/8//0//X/9//6//3///8BAAQABgAIAAkACgALAAoACgAJAAgABgAEAAIAAAD///z/+//6//n/+P/3//j/+f/6//z//v8AAAEAAwAFAAcACAAJAAkACQAIAAYABAACAAAA/v/7//n/9v/1//T/8//z//T/9f/4//v//v8AAAMABwAKAAwADgAQABAAEAAPAA0ACwAIAAQAAQD///z/+f/2//T/8v/x//H/8f/z//T/9v/5//v//v8AAAIABQAHAAkACgALAAsACwAKAAkABwAGAAQAAQAAAP///P/6//n/+P/4//j/+P/5//v//P///wAAAgAEAAYABwAIAAkACAAHAAYABAACAAAA/v/8//n/9//1//T/8//z//T/9f/4//r//f8AAAMABwAJAAwADgAQABEAEAAPAA4ACwAJAAYAAgAAAPz/+f/2//T/8v/x//D/8P/x//L/9f/3//n//f///wIABAAHAAkACgALAAwADAALAAoACQAHAAUABAABAP///v/7//r/+f/4//f/+P/5//r/+//+////AQADAAUABgAHAAgACAAHAAYABAADAAEA///8//r/+P/2//X/9P/0//T/9f/3//r//f8AAAIABgAJAAwADwAQABEAEQAQAA8ADQAKAAcAAwAAAP3/+v/3//T/8v/w/+//7//w//H/8//1//j/+//+/wEAAwAGAAgACgAMAAwADQAMAAwACgAJAAcABAADAAEA///9//v/+f/4//j/9//4//n/+v/9//7/AAABAAQABQAGAAcABwAHAAYABAADAAEA///9//v/+f/2//X/9P/0//T/9f/3//n//P///wIABQAJAAwADgAQABIAEgARABAADgALAAgABAABAP7/+v/3//T/8v/w/+//7v/v/+//8f/z//b/+f/9////AgAFAAgACgAMAA0ADQANAA0ADAAKAAkABgAEAAIAAAD///z/+v/5//j/9//4//j/+f/7//3///8AAAIABAAFAAYABwAGAAYABAADAAEA///+//v/+f/3//b/9f/0//T/9f/3//n/+////wEABQAIAAwADgAQABIAEgASABEADwAMAAkABgACAP///P/4//X/8v/w/+7/7v/u/+7/8P/y//T/+P/7//7/AQAEAAcACQAMAA0ADgAOAA4ADQAMAAoACAAGAAQAAQD///7//P/5//j/+P/3//j/+f/6//v//v8AAAEAAwAEAAUABgAGAAUABAADAAIAAAD+//z/+v/4//b/9f/1//T/9f/3//n/+//+/wEABAAIAAsADgAQABIAEgASABEAEAANAAoABwADAAAA/f/5//X/8v/w/+7/7f/t/+3/7v/w//L/9v/5//3/AAADAAYACQAMAA0ADgAPAA8ADgANAAwACQAIAAUAAwAAAP///P/6//n/+P/3//f/+P/5//r//P///wAAAQADAAQABQAFAAUABAADAAIAAAD+//3/+v/5//f/9v/1//X/9v/2//j/+//+/wAAAwAHAAsADgAQABIAEwATABIAEQAOAAsACAAEAAEA/v/6//b/8//w/+7/7f/s/+z/7f/v//H/9P/3//v///8BAAUACAALAAwADgAPABAADwAOAA0ADAAJAAcABAACAAAA/v/7//n/+P/3//f/9//4//r/+//+////AAACAAMABAAEAAQABAADAAIAAAD///3/+//5//j/9//1//X/9v/2//j/+v/9/wAAAwAGAAoADgAQABIAEwATABMAEgAPAAwACQAFAAIA/v/7//f/8//w/+7/7P/r/+v/7P/t/+//8v/2//n//f8AAAQABwAKAA0ADgAQABAAEAAPAA4ADQALAAgABgADAAEA///9//r/+f/3//f/9//3//n/+//8//7/AAABAAIAAwAEAAQAAwADAAIAAAD///7/+//6//j/9//2//b/9v/2//j/+v/9/wAAAwAGAAkADQAQABIAEwAUABMAEgAQAA0ACgAHAAIA///8//j/9P/x/+7/7P/r/+r/6//s/+3/8f/0//f/+////wMABgAJAAwADgAQABAAEQARABAADgANAAoACAAFAAIAAAD+//v/+f/4//f/9v/3//j/+f/7//z//v8AAAEAAgADAAMAAwACAAIAAQD///7//P/7//n/+P/2//b/9v/3//j/+v/9////AgAGAAkADAAPABIAEwAUABQAEwARAA4ACwAIAAMAAAD9//n/9f/x/+7/7P/q/+r/6v/r/+z/7//y//b/+v/+/wEABQAIAAsADgAQABEAEgASABEAEAAOAAwACQAHAAQAAQD///3/+v/4//f/9v/3//f/+P/6//z//f///wAAAQACAAIAAwACAAEAAQD///7//P/7//r/+P/3//b/9//3//j/+v/8////AQAFAAkADAAPABIAEwAUABQAEwASAA8ADAAJAAUAAQD+//r/9f/y/+//7P/q/+n/6f/p/+v/7f/w//T/+P/8/wAAAwAHAAsADQAQABEAEgATABIAEQAQAA0ACwAJAAUAAgAAAP7/+//5//j/9v/2//b/9//5//v//P/+////AAABAAEAAgACAAEAAQD///7//f/7//r/+f/4//f/9//3//j/+v/8//7/AQAEAAgACwAOABEAEwAUABUAFAATABAADQAKAAYAAgD///v/9v/z/+//7P/q/+n/6P/o/+r/7P/u//L/9v/6//7/AgAGAAoADQAPABEAEgATABMAEgARAA8ADQAKAAcABAABAP///P/6//j/9//2//b/9v/4//n/+v/8//7/AAAAAAEAAQABAAEAAQD//////f/8//v/+f/4//f/9//4//j/+v/8//7/AQAEAAcACwAOABEAEwAUABUAFAATABEADwALAAgAAwAAAPz/9//z//D/7f/q/+n/6P/o/+n/6v/t//D/9P/4//3/AQAEAAkADAAPABEAEwATABQAEwASABAADgAMAAkABgACAAAA/v/7//j/9//2//b/9v/3//j/+v/7//3//v///wAAAQABAAEAAAAAAP7//v/8//v/+v/5//j/+P/4//j/+v/7//7/AAADAAYACgANABAAEwAUABUAFQAUABIAEAAMAAkABQABAP3/+P/0//H/7f/q/+n/5//n/+j/6f/r/+//8v/3//v///8DAAcACwAOABEAEwAUABUAFAAUABIAEAANAAsACAAEAAEA///8//r/9//2//X/9f/2//f/+P/6//v//f/+////AAAAAAAAAAD///7//v/9//v/+v/5//n/+P/4//n/+v/8//7/AAADAAYACgANABAAEgAUABUAFQAUABMAEAANAAoABgACAP7/+f/2//H/7v/r/+n/5//n/+f/6P/q/+3/8f/1//n//v8CAAYACgAOABAAEwAUABUAFQAVABMAEgAPAAwACQAGAAMAAAD9//r/+f/3//X/9f/1//b/9//5//r//P/9//7//////wAAAAD///7//v/9//z/+//6//n/+f/5//n/+v/7//3/AAACAAUACQAMAA8AEgATABUAFQAUABMAEQAOAAsABwADAP//+//2//P/7//s/+n/5//m/+b/5//p/+z/7//z//j//P8BAAQACQAMABAAEgAUABUAFgAWABUAEwAQAA4ACwAIAAQAAQD+//v/+f/3//X/9f/1//X/9v/4//n/+v/8//3//v////////////7//v/9//z/+//6//r/+f/5//n/+v/8//3///8CAAUACAAMAA4AEQATABUAFQAVABQAEgAPAAwACAAEAAAA/P/4//T/7//s/+n/5//m/+X/5v/o/+r/7f/y//b/+v///wMABwALAA8AEgAUABYAFwAWABYAFAASAA8ADQAJAAYAAgAAAP3/+v/3//b/9f/1//X/9f/2//j/+f/7//z//f/+/////v////7//v/9//z//P/7//r/+v/6//r/+//8//3/AAACAAUACAALAA4AEQATABQAFQAVABQAEwAQAA0ACQAGAAEA/f/5//T/8P/t/+r/6P/m/+X/5f/m/+n/7P/v//T/+P/9/wEABgAKAA4AEQAUABYAFwAXABcAFQAUABEADgALAAgABAABAP7/+//5//b/9f/0//T/9f/2//f/+P/5//v//P/9//7//v/+//7//v/9//3//P/7//r/+v/6//r/+//8//3/AAABAAQABwAKAA0AEAASABQAFQAWABUAEwARAA4ACgAGAAIA/v/6//b/8f/u/+r/5//m/+X/5f/m/+j/6v/u//L/9v/8/wAABAAJAA0AEQATABYAFwAYABgAFgAVABMAEAANAAkABgACAP///P/5//f/9f/0//T/9P/1//b/9//4//r/+//8//3//v/+//7//v/9//3//P/8//v/+//6//v/+//8//7///8BAAQABwAKAA0AEAASABQAFQAVABUAFAASAA8ACwAIAAMAAAD7//f/8v/u/+v/6P/m/+T/5P/l/+b/6f/s//D/9f/6////AwAHAAwAEAATABYAFwAYABgAGAAWABQAEQAOAAsACAADAAAA/v/6//j/9v/0//T/9P/0//X/9v/3//j/+v/7//z//f/9//3//f/9//3//P/8//v/+//7//v/+//8//7///8BAAMABgAJAAwADwASABMAFQAVABUAFAATABAADAAJAAQAAQD8//j/8//v/+z/6f/m/+X/5P/k/+X/6P/r/+//8//4//3/AQAGAAsADwASABUAFwAZABkAGQAXABYAEwAQAA0ACQAGAAIA///8//n/9v/1//T/8//z//T/9f/2//f/+P/6//v//P/9//3//f/9//z//P/8//v/+//7//z//P/9//7///8BAAMABgAJAAwADgARABMAFQAVABUAFQATABAADgAKAAYAAQD+//n/9f/w/+z/6f/m/+X/5P/k/+X/5v/p/+3/8f/2//v/AAAEAAkADgARABUAFwAYABkAGQAYABcAFAASAA4ACwAHAAMAAAD9//r/9//1//T/8//z//P/9P/1//b/9//5//r/+//8//z//P/8//z//P/8//z/+//7//z//P/9//7///8BAAMABgAJAAsADgARABIAFAAVABUAFQATABEADwALAAcAAwD+//r/9v/x/+3/6v/n/+X/4//j/+T/5v/o/+v/7//0//n//v8DAAcADAAQABQAFwAZABoAGgAZABgAFgATABAADAAJAAQAAQD+//v/+P/2//T/8//z//L/8//0//X/9v/4//j/+v/7//v//P/8//z//P/8//z//P/8//z//f/9//////8BAAMABQAIAAsADQAQABIAFAAVABUAFQAUABIADwAMAAgABAAAAPz/9//y/+7/6//n/+X/5P/j/+P/5f/m/+r/7v/y//f//P8BAAYACwAPABMAFgAZABoAGgAaABkAFwAVABIADgAKAAcAAgD///z/+f/2//X/8//y//L/8v/z//T/9f/2//j/+f/6//v/+//7//z//P/8//z//P/8//z//f/+////AAABAAMABQAIAAsADQAPABIAEwAVABUAFQAUABMAEAANAAkABQABAP3/+P/z//D/7P/o/+b/5P/j/+P/5P/m/+n/7P/x//X/+////wQACQAOABIAFQAZABoAGwAbABoAGAAWABMAEAAMAAgABAABAP7/+v/3//X/8//y//H/8v/y//P/9P/1//b/9//5//n/+//7//v/+//8//z//P/8//3//f/+////AAABAAMABQAIAAoADQAPABEAEwAUABUAFQAUABMAEAANAAoABgACAP7/+f/1//D/7f/p/+b/5P/j/+L/4//l/+f/6//v//T/+f/+/wIACAANABEAFQAXABoAGwAbABsAGgAXABUAEgAOAAoABgACAP///P/5//b/9P/y//H/8f/x//L/8//0//X/9v/4//n/+v/6//v/+//8//z//P/9//3//f/+////AAACAAMABQAHAAoADAAPABEAEgAUABUAFQAVABMAEQAOAAsABwADAP//+v/2//H/7v/q/+f/5P/j/+L/4//k/+b/6v/t//L/9//8/wEABgALABAAFAAXABoAGwAbABsAGgAYABYAEwAPAAwACAADAAAA/f/5//f/9P/y//H/8P/x//H/8v/z//T/9v/2//j/+f/6//r/+//7//z//P/8//3//v///wAAAAACAAMABQAIAAoADAAOABAAEgAUABQAFQAVABQAEgAPAAwACAAEAAAA/P/3//L/7//r/+f/5f/j/+L/4//k/+b/6P/r//D/9f/6/wAABAAKAA4AEwAWABkAGwAcABwAGwAaABcAFQARAA4ACQAFAAEA/v/7//j/9f/z//H/8f/w//D/8f/y//P/9P/1//f/+P/5//n/+v/7//v//P/8//3//v///wAAAAACAAMABQAIAAoADAAOABAAEgATABQAFQAVABQAEgAQAA0ACQAFAAEA/f/4//T/7//r/+j/5f/j/+L/4v/j/+T/5//q/+//8//5//7/AwAIAA0AEgAVABgAGwAcABwAHAAbABkAFgATAA8ACwAHAAMA///8//n/9v/z//L/8P/w//D/8P/x//L/8//0//X/9//4//n/+v/6//v//P/8//3//v///wAAAQACAAQABQAHAAoADAAOABAAEgATABQAFQAVABQAEgAQAA0ACgAGAAIA/v/5//X/8f/s/+n/5v/k/+L/4v/i/+T/5v/p/+3/8f/3//z/AQAGAAwAEAAUABgAGwAcABwAHAAcABoAFwAUABEADQAJAAUAAQD+//r/9//0//L/8P/w/+//7//w//H/8v/z//T/9v/3//j/+f/6//v/+//8//3//v///wAAAQACAAQABQAHAAoACwANAA8AEQATABQAFAAUABQAEwARAA4ACwAHAAMA///6//b/8v/t/+r/5//k/+P/4v/i/+P/5f/o/+z/8P/1//v/AAAEAAoADwATABcAGgAbAB0AHQAcABsAGQAWABIADwAKAAYAAgD///v/+P/1//P/8f/v/+//7//v//D/8f/y//P/9P/2//f/+P/5//r/+//8//3//v///wAAAQACAAQABQAHAAoACwANAA8AEQATABQAFAAVABQAEwARAA8ACwAIAAQAAAD8//f/8//v/+v/5//l/+P/4v/h/+P/5P/n/+r/7v/z//j//v8CAAgADQASABYAGQAbAB0AHQAdABwAGgAXABQAEAAMAAgABAAAAP3/+f/2//P/8f/v/+//7v/v/+//8P/x//L/8//1//b/9//4//r/+//8//3//v///wAAAQADAAQABgAIAAoACwANAA8AEQASABMAFAAUABQAEwARAA8ADAAJAAUAAQD9//j/9P/w/+z/6P/l/+P/4v/i/+L/5P/m/+n/7f/y//f//P8BAAYADAAQABUAGAAbAB0AHQAdAB0AGwAYABUAEgANAAoABQABAP7/+v/3//T/8v/w/+//7v/u/+7/7//w//H/8v/0//X/9v/4//n/+v/7//3//v///wAAAQADAAQABgAIAAoACwANAA8AEAASABMAFAAUABQAEwASAA8ADQAKAAYAAgD+//r/9f/x/+3/6f/m/+T/4v/i/+L/4//l/+j/7P/w//X/+v8AAAUACgAPABQAFwAaABwAHQAeAB0AHAAaABcAEwAQAAsABwADAP///P/4//X/8v/w/+//7v/t/+7/7v/v//D/8f/y//T/9f/3//j/+v/7//z//v///wAAAQADAAUABgAIAAoADAANAA8AEQASABMAFAAUABQAEwASABAADQAKAAYAAwD///v/9v/y/+7/6v/n/+T/4//i/+L/4//k/+f/6v/v//T/+f/+/wMACAAOABIAFgAZABwAHQAeAB4AHAAbABgAFAARAA0ACQAEAAEA/f/5//b/8//x/+//7v/t/+3/7f/u/+//8P/x//P/9P/2//f/+f/6//z//v///wAAAgADAAUABgAIAAoADAANAA8AEQASABMAEwAUABQAEwASABAADgALAAcABAAAAPz/9//z/+//6//o/+X/4//i/+L/4v/k/+b/6f/t//L/9//9/wIABwAMABEAFQAZABsAHQAeAB4AHQAcABkAFgATAA4ACwAGAAIA/v/7//f/9P/x/+//7v/t/+3/7f/t/+7/7//w//L/8//1//b/+P/6//v//f///wAAAQADAAUABgAIAAoADAANAA8AEQASABMAEwAUABQAEwASABAADgALAAgABAABAP3/+P/0//D/7P/p/+b/5P/i/+L/4v/j/+X/6P/s//H/9f/7/wAABQAKAA8AFAAXABoAHAAeAB8AHgAcABoAFwAUABEADAAIAAMAAAD8//j/9f/y//D/7v/t/+z/7P/s/+3/7v/v//D/8v/0//b/9//5//v//f/+/wAAAQADAAUABwAIAAoADAANAA8AEAASABMAFAAUABQAEwASABEADwAMAAkABQACAP3/+v/1//H/7f/p/+f/5P/j/+L/4v/j/+X/5//r/+//9P/5////AwAJAA4AEgAWABoAHAAeAB4AHgAdABsAGAAVABIADQAKAAUAAQD+//r/9v/z//H/7//t/+z/7P/s/+z/7f/u//D/8f/z//X/9v/4//r//P/+////AQADAAUABwAIAAoADAAOAA8AEQASABMAFAAUABQAEwASABEADwAMAAkABgACAP//+//2//L/7v/q/+f/5f/j/+L/4v/j/+T/5v/q/+7/8//4//3/AgAHAAwAEQAVABkAGwAdAB4AHgAeABwAGgAXABMAEAALAAcAAgD///v/9//0//H/7//t/+z/6//r/+v/7P/t/+//8P/y//P/9v/3//n/+//+////AQADAAQABwAIAAoADAAOAA8AEQASABMAFAAUABQAEwATABEADwANAAoABgADAP//+//4//P/7//s/+j/5f/j/+L/4v/i/+T/5v/p/+3/8f/2//v/AAAFAAoAEAAUABcAGgAdAB4AHgAeAB0AGwAYABUAEQAMAAgABAAAAPz/+f/1//L/8P/u/+z/6//r/+v/6//s/+3/7//w//L/9f/2//j/+//9////AQACAAUABgAJAAoADAAOAA8AEQASABMAFAAUABQAEwATABEADwANAAoABwAEAAAA/P/5//T/8P/s/+n/5v/k/+L/4v/i/+P/5f/o/+z/8P/1//r///8EAAkADgASABYAGgAcAB4AHwAeAB0AHAAZABYAEgAPAAoABQABAP7/+v/2//P/8P/u/+z/6//r/+r/6//r/+z/7v/v//H/8//1//j/+v/8//7/AAACAAQABgAIAAoADAAOABAAEQASABMAFAAUABQAEwATABEAEAANAAsABwAEAAEA/f/6//X/8f/u/+r/5//l/+P/4v/i/+P/5f/n/+v/7//z//j//f8CAAcADAARABUAGQAbAB0AHgAeAB4AHQAaABcAFAAQAAsABwADAP//+//4//T/8f/v/+3/6//q/+r/6v/r/+v/7f/v//D/8v/0//f/+f/7//7/AAACAAQABgAIAAoADAAOABAAEQASABMAFAAUABQAEwATABIAEAAOAAsACAAFAAIA/v/6//b/8v/v/+v/6P/l/+P/4v/i/+P/5P/n/+r/7v/y//f//P8BAAYACwAQABQAFwAaAB0AHgAfAB4AHQAbABgAFQARAA0ACQAEAAAA/f/5//X/8v/w/+3/7P/q/+r/6v/q/+v/7P/u/+//8f/z//b/+P/7//3///8BAAQABgAIAAoADAAOABAAEQASABMAFAAUABQAFAATABIAEAAOAAsACQAGAAIA///7//f/8//v/+z/6f/m/+T/4//i/+P/5P/m/+n/7f/x//b/+////wQACQAOABMAFgAaABwAHgAfAB4AHQAbABkAFgASAA8ACgAGAAIA/v/6//f/8//w/+7/7P/q/+r/6f/p/+r/6//s/+7/8P/y//T/9//6//z///8BAAMABgAIAAoADAAOABAAEgASABQAFAAUABQAFAATABIAEAAOAAwACQAGAAMA///8//j/9P/w/+3/6f/n/+X/4//i/+P/5P/m/+j/7P/w//T/+f/+/wMABwANABEAFQAZABsAHQAeAB4AHgAdABoAFwAUABAADAAIAAMA///8//j/9P/x/+//7f/r/+n/6f/p/+n/6v/r/+3/7//x//P/9v/5//z//v8BAAMABQAIAAoADAAOABAAEgATABQAFQAVABUAFAATABIAEQAPAAwACgAGAAMAAAD9//n/9f/x/+3/6v/o/+X/5P/j/+P/5P/l/+j/6//v//P/+P/9/wEABgALABAAFAAXABsAHAAeAB4AHgAdABsAGAAVABEADgAJAAUAAQD9//r/9v/z//D/7f/r/+r/6f/o/+j/6f/q/+z/7f/w//L/9f/4//r//f8AAAIABQAHAAoADAAOABAAEgATABQAFQAVABUAFAAUABIAEQAPAAwACgAHAAQAAQD9//r/9f/y/+7/6//o/+b/5P/j/+P/5P/l/+f/6v/u//L/9//7/wAABQAJAA4AEwAWABkAHAAeAB4AHgAdABwAGQAWABMADwALAAcAAgD///v/9//0//H/7v/s/+r/6f/o/+j/6P/p/+v/7P/v//H/9P/3//r//P///wIABAAHAAoADAAOABAAEgATABQAFQAVABUAFQAUABMAEQAPAA0ACwAHAAQAAQD+//r/9//z/+//7P/p/+b/5f/j/+P/5P/k/+f/6v/t//H/9f/6////AwAIAA0AEQAVABgAGwAdAB4AHgAdABwAGgAXABQAEAAMAAgAAwAAAP3/+f/1//L/7//s/+r/6f/o/+j/6P/o/+r/7P/t//D/8v/2//j//P///wEABAAGAAkADAAOABAAEgATABQAFQAWABUAFQAUABMAEQAPAA0ACwAIAAQAAQD+//v/9//z//D/7f/p/+f/5f/k/+P/5P/l/+b/6f/s//D/9P/5//3/AgAHAAsAEAAUABcAGgAcAB0AHgAeAB0AGgAYABUAEQAOAAoABQABAP7/+v/2//P/8P/t/+v/6f/o/+f/5//o/+n/6v/s/+//8f/0//f/+//+/wAAAwAGAAkACwAOABAAEgATABUAFgAWABYAFQAUABMAEgAQAA4ACwAJAAUAAgD///z/+P/0//H/7f/q/+j/5v/k/+P/5P/l/+b/6P/r/+//8//4//z/AQAFAAoADgATABYAGQAcAB0AHgAeAB0AGwAZABYAEwAPAAsABgADAP//+//4//T/8f/u/+v/6v/o/+f/5//n/+j/6f/r/+7/8P/z//b/+v/9/wAAAgAFAAgACwANABAAEgATABUAFgAWABYAFgAVABQAEgAQAA4ACwAJAAYAAwAAAPz/+f/1//L/7v/r/+j/5v/l/+T/5P/l/+b/6P/r/+//8v/3//v///8EAAgADQARABUAGAAaABwAHQAdAB0AHAAZABcAFAAQAAwACAAEAAAA/f/5//X/8v/v/+z/6v/o/+f/5//n/+f/6P/q/+z/7//y//X/+P/8////AQAFAAgACwANABAAEgAUABUAFgAXABcAFgAVABQAEwARAA4ADAAJAAYAAwAAAP3/+f/2//L/7//s/+n/5//l/+X/5P/k/+b/6P/q/+7/8f/2//r//v8DAAcACwAQABQAFwAaABsAHQAdAB0AHAAaABgAFQARAA4ACgAGAAEA/v/7//f/8//w/+3/6//p/+f/5//m/+f/6P/p/+v/7v/x//T/9//7//7/AQAEAAcACgANAA8AEgAUABUAFgAXABcAFwAWABUAEwARAA8ADQAKAAcAAwAAAP7/+v/2//P/8P/t/+r/6P/m/+X/5P/k/+b/5//q/+3/8P/1//n//f8BAAYACgAPABIAFgAZABsAHAAdAB0AHAAbABgAFgATAA8ACwAHAAMAAAD8//j/9P/x/+7/7P/p/+j/5//m/+b/5//o/+r/7f/w//L/9v/5//3/AAADAAYACQANAA8AEgAUABUAFgAXABgAFwAWABUAFAASAA8ADQAKAAcABAABAP7/+//3//T/8f/t/+r/6P/m/+X/5P/l/+b/5//p/+z/8P/z//j//P8AAAQACQANABEAFQAYABoAGwAcAB0AHAAbABkAFwAUABAADAAJAAQAAQD9//n/9v/y/+//7P/q/+j/5//m/+b/5v/o/+n/6//u//H/9f/4//z///8CAAUACQAMAA8AEQATABUAFwAXABgAGAAXABYAFAASABAADQAKAAgABQABAP//+//4//T/8f/u/+v/6f/n/+X/5f/l/+b/5//p/+v/7//z//f/+////wMACAAMABAAEwAWABkAGwAcABwAHAAbABkAFwAUABEADgAKAAUAAgD///v/9//0//D/7f/r/+n/5//m/+b/5v/n/+j/6//t//D/8//3//v//v8BAAUACAALAA4AEQATABUAFgAXABgAGAAXABYAFQATABEADgALAAgABQACAP///P/5//X/8v/v/+z/6f/n/+b/5f/l/+X/5//p/+v/7v/y//b/+v/+/wIABgALAA4AEgAVABgAGgAbABwAHAAbABoAGAAVABIADwALAAcABAAAAPz/+f/1//L/7v/r/+n/5//m/+b/5v/m/+j/6v/s/+//8v/1//n//f8AAAMABwALAA4AEAATABUAFwAYABgAGAAYABcAFQATABEADgAMAAkABQACAP///P/5//b/8v/v/+z/6v/o/+b/5v/l/+X/5//p/+v/7v/x//X/+f/9/wEABQAJAA4AEQAUABcAGQAbABsAHAAbABoAGAAWABMAEAAMAAgABAABAP7/+v/2//P/7//s/+r/6P/n/+b/5f/m/+f/6P/r/+3/8f/0//j//P///wIABgAKAA0AEAATABUAFwAYABgAGQAYABcAFgAUABIADwAMAAoABgADAAAA/f/6//b/8//w/+3/6v/o/+f/5v/l/+b/5//o/+r/7f/x//T/+P/8/wEABAAIAAwAEAATABYAGAAaABsAGwAbABoAGQAWABQAEQANAAoABgACAP//+//3//T/8P/u/+v/6f/n/+b/5f/l/+f/5//q/+z/8P/z//b/+v/+/wEABQAJAAwAEAASABUAFwAYABkAGQAZABgAFgAVABMAEAANAAoABwADAAEA/v/6//f/8//w/+7/6//p/+f/5v/m/+b/5//o/+r/7f/w//T/9//7/wAAAwAHAAsADwASABUAFwAZABoAGwAbABoAGQAXABUAEQAOAAsABwADAAAA/f/5//X/8v/v/+z/6f/o/+b/5f/l/+b/5//o/+v/7v/x//X/+f/9/wAABAAIAAwADwASABUAFgAYABkAGQAZABgAFwAVABMAEQAOAAsACAAEAAEA/v/7//j/9P/x/+7/6//q/+j/5//m/+b/5v/o/+r/7P/v//P/9v/6////AgAGAAoADgARABQAFgAYABoAGgAaABoAGQAXABUAEwAPAAwACAAFAAEA/v/6//f/8//w/+3/6v/o/+b/5v/l/+X/5v/o/+r/7f/w//P/+P/8/wAAAwAHAAsADgARABQAFgAYABkAGQAZABkAGAAWABQAEQAPAAsACAAFAAIA///7//j/9f/x/+//7P/q/+j/5//m/+b/5//o/+n/7P/v//L/9v/6//7/AQAFAAkADQAQABMAFQAXABkAGgAaABoAGQAYABYAEwAQAA0ACgAGAAMA///8//j/9f/x/+7/6//p/+f/5v/l/+X/5v/n/+n/7P/v//L/9v/6////AgAGAAoADQARABMAFgAYABkAGgAaABkAGAAXABUAEgAPAAwACQAFAAIA///8//j/9f/y/+//7f/q/+n/5//n/+b/5//o/+r/7P/u//L/9f/5//3/AAAEAAgADAAPABIAFAAXABgAGQAaABoAGQAYABYAFAARAA4ACwAHAAMAAAD9//n/9v/y/+//7P/p/+j/5v/l/+X/5f/n/+j/6//u//H/9f/5//3/AQAEAAkADAAQABMAFgAXABkAGgAaABoAGQAXABUAEwAQAA0ACgAGAAMAAAD9//n/9v/z//D/7f/r/+n/6P/n/+f/5//o/+n/7P/u//H/9f/5//z///8DAAcACwAOABEAEwAWABcAGQAZABkAGQAYABYAFAASAA8ADAAIAAQAAQD+//r/9//0//D/7v/r/+j/5//m/+X/5f/m/+f/6v/s//D/9P/3//z/AAADAAgACwAPABIAFQAXABkAGgAaABoAGQAYABYAFAARAA4ACgAHAAMAAAD9//r/9v/z//D/7v/r/+n/6P/n/+f/5//o/+n/6//t//D/9P/4//z///8CAAYACQANABAAEgAVABcAGAAZABkAGQAYABcAFQASABAADQAJAAYAAwD///z/+P/1//H/7//s/+r/5//m/+X/5f/m/+f/6f/s/+//8v/3//r///8CAAYACwAOABEAFAAXABgAGgAaABoAGgAZABcAFAASAA8ACwAIAAQAAQD+//r/9//0//H/7v/s/+r/6P/n/+f/5//o/+n/6//t//D/8//3//r//v8CAAUACQAMAA8AEQAUABYAFwAYABgAGAAYABcAFQATABAADgAKAAcAAwAAAP3/+v/2//P/8P/t/+r/6P/m/+X/5f/l/+b/6P/r/+3/8f/0//n//f8BAAUACQANABAAFAAWABgAGgAaABsAGgAZABgAFQATABAADAAJAAUAAQD///v/9//0//H/7//s/+r/6f/o/+f/5//o/+n/6//t//D/8//2//r//f8BAAQACAALAA4AEQATABUAFgAXABgAGAAYABYAFQATABEADgALAAgABAABAP//+//3//T/8f/u/+v/6f/n/+b/5f/l/+b/6P/p/+z/8P/z//j//P8AAAMACAAMABAAEwAWABgAGQAaABsAGgAaABgAFgATABEADQAJAAYAAgD///z/+P/1//L/7//t/+v/6f/o/+f/5//o/+n/6//t/+//8v/2//r//f8AAAQABwAKAA0AEAASABQAFgAWABcAGAAXABYAFQAUABEADwAMAAkABgADAAAA/P/5//b/8v/v/+z/6v/o/+b/5f/l/+b/5//o/+v/7v/y//b/+//+/wMABgALAA4AEgAVABcAGQAaABsAGwAaABkAFwAUABIADgAKAAcAAwD///z/+f/1//L/7//t/+v/6f/o/+j/5//o/+n/6v/s/+//8v/1//n//P///wMABgAJAAwADwARABMAFQAWABcAFwAXABYAFQAUABIAEAANAAoABwADAAAA/v/6//f/8//w/+3/6//o/+f/5v/l/+X/5v/o/+r/7f/x//T/+f/+/wEABQAKAA0AEQAUABYAGQAaABsAGwAaABkAGAAVABIADwALAAgABAAAAP3/+f/2//P/8P/t/+z/6v/p/+j/6P/o/+n/6v/s/+//8f/0//j//P///wIABQAIAAsADgAQABMAFAAVABYAFgAWABYAFQAUABIAEAAOAAsACAAEAAEA///7//j/9f/x/+7/7P/p/+j/5v/l/+X/5v/n/+n/7P/v//P/9//8/wAABAAJAAwAEAATABYAGAAaABsAGwAbABoAGQAWABMAEAAMAAkABQABAP7/+v/3//P/8f/u/+z/6v/p/+j/6P/o/+n/6v/s/+//8f/0//f/+//+/wIABAAIAAsADQAQABIAEwAVABUAFgAWABYAFQAUABIAEAAOAAwACAAGAAIAAAD9//n/9v/z//D/7f/q/+n/5//m/+b/5v/n/+j/6//u//L/9v/6////AgAHAAsADwASABUAGAAZABsAGwAbABoAGQAXABQAEQANAAoABgACAP//+//3//T/8f/u/+z/6v/p/+j/6P/o/+n/6v/s/+7/8f/0//f/+//+/wEABAAHAAoADAAPABEAEgAUABQAFQAWABUAFQAUABIAEQAPAAwACgAHAAMAAQD+//v/9//0//H/7v/s/+n/6P/m/+b/5v/m/+j/6v/t//H/9f/5//3/AQAFAAoADgARABUAFwAZABsAGwAbABsAGgAXABUAEgAOAAoABwADAP///P/4//X/8v/v/+z/6//p/+j/6P/o/+n/6v/r/+7/8P/z//b/+v/9/wAAAwAGAAkADAAOABAAEgATABQAFQAVABUAFAAUABMAEQAPAA0ACgAIAAQAAQD///z/+f/1//L/7//t/+r/6P/n/+b/5v/m/+j/6f/s/+//8//3//z/AAAEAAkADAAQABQAFgAZABoAGwAcABsAGgAYABYAEwAPAAsACAAEAAAA/f/5//b/8v/w/+3/6//q/+j/6P/o/+n/6v/r/+3/8P/z//b/+f/9/wAAAwAFAAgACwANAA8AEQASABMAFAAUABUAFAAUABIAEQAPAA0ACwAIAAUAAgAAAP3/+v/3//T/8P/u/+v/6f/o/+b/5v/m/+f/6f/r/+7/8v/2//r///8CAAcACwAPABMAFQAYABoAGwAcABwAGwAZABcAFAAQAAwACQAFAAEA/v/6//b/8//w/+7/6//q/+n/6P/o/+n/6v/r/+3/8P/y//b/+f/8////AgAFAAgACgANAA8AEQASABMAEwAUABQAEwATABIAEQAQAA4ACwAJAAYAAwABAP7/+//4//X/8v/v/+z/6v/o/+f/5v/m/+f/6P/q/+3/8f/1//n//v8BAAUACgAOABEAFQAYABoAGwAcABwAGwAZABcAFQARAA4ACgAGAAIA/v/7//f/9P/w/+7/6//q/+n/6P/o/+n/6f/r/+3/7//y//X/+P/8//7/AgAEAAcACgAMAA4AEAARABIAEwATABMAEwATABIAEQAQAA0ADAAJAAcABAABAP///P/5//b/8//w/+7/6//p/+j/5//m/+f/6P/q/+z/7//z//j//P8AAAQACAANABAAFAAXABkAGgAcABwAGwAaABgAFgASAA8ACwAHAAMA///8//j/9P/x/+7/7P/q/+n/6P/o/+n/6f/r/+3/7//y//X/+P/7//7/AQAEAAcACQAMAA0ADwAQABIAEgATABMAEwASABIAEQAQAA4ADAAKAAgABQACAAAA/f/6//f/9P/x/+//7P/q/+j/5//n/+f/6P/p/+z/7//y//b/+v///wIABwALAA8AEwAWABgAGgAbABwAHAAaABkAFwAUABAADQAIAAQAAAD9//n/9f/y/+//7f/q/+n/6P/o/+j/6f/r/+z/7v/x//T/9//6//7/AQADAAYACQALAA0ADwAQABEAEgASABIAEwASABIAEQAPAA4ADAAKAAgABgADAAEA/v/7//n/9f/z//D/7f/r/+n/6P/n/+f/5//p/+v/7v/x//X/+f/9/wEABQAKAA4AEgAVABgAGgAbABwAHAAbABkAFwAUABEADgAJAAUAAQD+//r/9v/z/+//7f/r/+n/6f/o/+j/6f/r/+z/7v/x//T/9//6//3/AAADAAYACAAKAAwADgAPABEAEQARABIAEgARABEAEQAPAA4ADQAKAAkABgAEAAEA///9//r/9//0//H/7v/s/+r/6f/n/+f/5//o/+r/7f/w//P/9//8/wAABAAIAAwAEAAUABcAGAAaABsAHAAbABoAGAAVABIADwAKAAYAAgD///v/9v/z//D/7f/r/+r/6f/p/+j/6f/q/+z/7v/w//P/9v/6//3/AAACAAUACAAKAAwADgAPABAAEQARABIAEQASABEAEAAPAA4ADQALAAkABwAFAAIAAAD+//v/+P/1//L/8P/t/+v/6f/o/+j/6P/o/+r/7P/v//L/9v/7////AgAHAAsADwATABUAGQAaABsAHAAbABoAGQAWABMAEAAMAAgAAwAAAPz/+P/0//H/7v/s/+r/6f/o/+n/6f/q/+v/7v/w//P/9v/5//z///8CAAQABwAJAAsADQAOABAAEAARABEAEQARABAAEAAPAA4ADAALAAoABwAFAAMAAQD+//z/+f/2//P/8f/u/+z/6v/p/+j/6P/o/+r/6//u//H/9f/5//3/AQAFAAoADQARABUAFwAaABsAHAAbABsAGQAXABQAEAANAAkABAABAP3/+f/1//L/7//s/+r/6f/o/+n/6f/q/+v/7f/v//L/9f/4//z///8BAAQABwAJAAsADQAOAA8AEAAQABEAEAARABAADwAPAA4ADAALAAoABwAGAAMAAgD///3/+v/3//X/8v/v/+3/6//q/+j/6P/o/+n/6//t//D/9P/3//z/AAAEAAgADAAQABQAFgAZABoAGwAcABsAGgAYABUAEgAOAAoABgABAP7/+v/2//L/7//t/+v/6f/p/+j/6f/p/+v/7f/v//L/9f/4//v//v8BAAMABgAIAAsADAAOAA8ADwAQABAAEAAQABAADwAPAA4ADAALAAoACAAHAAQAAgAAAP7/+//4//b/8//x/+7/7P/q/+n/6f/p/+n/6//t/+//8//2//v//v8CAAcACgAPABIAFQAYABoAGwAcABsAGgAYABUAEwAPAAsABwACAP//+//3//P/8P/t/+v/6v/p/+j/6f/p/+v/7f/v//H/9f/3//v//v8AAAMABgAIAAoADAANAA4ADwAPAA8AEAAQAA8ADwAOAA0ADAALAAoACAAHAAQAAwABAP///P/6//f/9P/y/+//7f/s/+r/6f/p/+n/6v/s/+//8v/1//n//v8BAAUACQAOABEAFAAXABkAGgAbABsAGgAZABYAFAAQAAwACAAEAAAA/P/4//T/8f/u/+v/6v/p/+j/6f/p/+v/7P/u//H/9P/3//r//f8AAAMABQAHAAoACwANAA4ADwAPAA8ADwAPAA8ADwAOAA0ADAALAAoACAAGAAUAAwABAP///f/7//j/9f/z//D/7v/s/+v/6v/p/+r/6v/s/+7/8f/0//f//P8AAAQACAALABAAEwAWABkAGgAbABsAGgAZABcAFAARAA0ACgAFAAEA/f/5//X/8v/v/+z/6v/p/+j/6f/p/+r/7P/u//D/9P/3//r//f///wIABQAHAAkACwAMAA4ADgAPAA8ADwAPAA8ADgANAA0ADAALAAoACAAHAAYAAwACAAAA/v/8//n/9//0//H/7//t/+z/6//q/+r/6v/s/+3/8P/z//b/+//+/wIABgALAA8AEgAVABgAGQAaABsAGgAZABgAFQASAA4ACwAHAAIA/v/6//b/8//w/+3/6//q/+j/6f/p/+r/6//u//D/8//2//n//P///wEABAAHAAgACwAMAA0ADgAOAA8ADwAOAA4ADgANAAwADAALAAoACQAHAAYABAADAAAA///9//r/+P/1//P/8P/u/+3/6//q/+r/6v/s/+3/7//y//X/+f/9/wEABAAJAAwAEQAUABcAGQAaABsAGwAaABgAFgATAA8ACwAIAAMA///8//f/9P/w/+3/6//q/+n/6f/p/+r/6//t//D/8v/2//j//P///wEABAAGAAkACgAMAA0ADgAOAA4ADwAOAA4ADQANAAwACwAKAAkACQAHAAYABAADAAEAAAD9//v/+f/3//T/8f/w/+7/7P/r/+r/6//r/+3/7//x//T/+P/8////AwAIAAwADwATABYAFwAZABoAGwAaABkAFgAUABEADQAIAAUAAQD9//n/9f/x/+7/7P/q/+n/6f/p/+r/6//t/+//8v/1//j/+//+/wEAAwAGAAcACgALAAwADQAOAA4ADgAOAA4ADQAMAAwACwAKAAkACAAHAAYABQADAAIAAAD+//z/+v/3//X/8//x/+//7f/s/+v/6//s/+3/7v/w//T/9//7//7/AgAFAAkADgARABQAFwAZABoAGgAaABkAFwAUABEADgAKAAUAAQD+//r/9v/y/+//7P/r/+n/6f/p/+n/6v/t/+//8f/0//j/+//9/wAAAgAFAAgACgALAAwADQAOAA4ADQAOAA0ADQAMAAsACwAKAAkACAAHAAYABQADAAIAAAD///3/+//5//b/9P/y//D/7v/t/+z/6//s/+z/7v/w//L/9v/5//3/AAAEAAkADQAQABMAFgAYABkAGgAaABkAFwAVABIADwALAAcAAwD///v/9//z//D/7f/r/+r/6f/p/+n/6v/s/+7/8f/0//f/+v/9/wAAAgAEAAcACQAKAAwADQANAA0ADgANAA0ADAAMAAsACgAKAAkACAAHAAYABQAEAAIAAQAAAP7//P/5//j/9f/z//H/7//u/+3/7P/s/+3/7v/v//L/9f/4//z///8CAAcACgAPABIAFQAXABkAGgAaABkAGAAWABMAEAAMAAgABAAAAPz/+P/0//H/7v/s/+r/6f/p/+n/6v/s/+7/8P/z//b/+f/9////AgAEAAcACQAKAAwADQANAA4ADgANAA0ADAALAAsACgAJAAkACAAHAAYABQAEAAIAAQAAAP///f/6//n/9v/0//L/8P/u/+7/7f/s/+3/7v/v//H/9P/3//r//v8BAAUACgANABEAFAAWABgAGQAaABkAGAAWABQAEQANAAoABQABAP7/+f/1//L/7//s/+v/6f/p/+n/6v/r/+3/8P/z//b/+f/8////AQAEAAYACAAKAAsADAANAA0ADgANAAwADAALAAsACgAJAAgACAAHAAYABQAEAAMAAgAAAP///f/7//r/+P/1//P/8f/w/+7/7f/t/+3/7v/v//H/8//2//n//f8AAAQACAALAA8AEgAVABcAGQAZABkAGAAXABQAEgAOAAsABgACAP//+//2//P/8P/t/+v/6v/p/+n/6v/r/+3/7//y//X/+P/7//7/AQADAAUACAAKAAsADAANAA0ADQANAAwADAALAAoACgAJAAgABwAHAAYABQAEAAMAAgAAAAAA/v/8//r/+P/2//T/8v/x/+//7v/u/+3/7v/v//D/8//1//j//P///wIABgAKAA4AEQAUABYAGAAZABkAGAAXABUAEgAPAAwACAADAP///P/4//T/8f/u/+z/6v/q/+n/6v/r/+3/7//y//T/+P/7//7/AAACAAUACAAJAAsADAANAA0ADQAMAAwADAALAAoACQAJAAgABwAGAAYABQAEAAMAAgABAAAA///9//v/+f/4//X/8//y//D/7//u/+7/7v/v//D/8v/0//f/+v/+/wEABQAJAAwAEAATABUAFwAYABgAGAAXABYAEwAQAA0ACQAFAAEA/f/5//X/8v/v/+z/6//q/+n/6v/r/+3/7v/x//T/9//6//3/AAACAAUABwAJAAsADAAMAA0ADQANAAwACwALAAoACQAIAAcABwAGAAUABAAEAAMAAgABAAAA///+//z/+v/4//f/9P/z//H/8P/v/+7/7v/v//D/8v/0//b/+f/9/wAAAwAHAAsADgARABQAFgAYABgAGAAXABYAFAARAA4ACgAGAAIA/v/7//b/8//w/+3/6//q/+n/6v/r/+z/7v/w//P/9//5//3///8CAAQABwAIAAoACwAMAA0ADQAMAAwACwAKAAoACQAIAAcABgAGAAUABAAEAAMAAgABAAAA///+//3/+//5//j/9f/0//L/8f/w/+//7//w//D/8f/z//b/+P/8////AgAGAAkADQAQABMAFQAXABgAGAAYABYAFAARAA8ACwAHAAMA///8//f/9P/x/+7/7P/r/+r/6v/q/+z/7f/w//P/9f/5//z///8BAAQABgAIAAoACwAMAAwADQAMAAwACwAKAAkACQAIAAcABgAFAAUABAAEAAMAAgABAAEAAAD///3//P/6//n/9v/1//P/8v/x//D/8P/v//D/8f/z//X/+P/6//7/AQAEAAgACwAPABIAFAAWABcAFwAXABYAFQASAA8ADAAIAAQAAQD9//n/9f/y/+//7f/r/+r/6v/q/+z/7f/v//L/9f/4//v//v8BAAMABgAIAAkACwAMAAwADQAMAAwACwAKAAkACQAIAAcABgAFAAUABAADAAMAAgABAAEAAAD///7//P/7//n/+P/2//T/8//x//H/8P/w//D/8f/z//X/9//5//3/AAADAAYACgANABAAEwAVABYAFwAXABYAFQATABAADQAJAAUAAgD+//r/9v/z//D/7v/s/+v/6v/q/+z/7f/v//L/9P/4//v//v8AAAIABQAHAAkACwALAAwADQAMAAwACwAKAAoACQAHAAcABgAFAAQABAADAAIAAgABAAEAAAD//////f/8//r/+f/3//X/9P/y//H/8f/w//H/8f/y//T/9v/5//v///8BAAUACAAMAA8AEgAUABUAFgAXABYAFQATABEADgAKAAcAAwD///z/9//0//H/7v/s/+v/6v/r/+v/7f/v//H/9P/3//r//f8AAAIABQAHAAkACgALAAwADAAMAAwACwALAAkACQAHAAYABgAFAAQABAADAAIAAgABAAEAAAAAAP///v/8//v/+v/4//b/9f/z//L/8v/x//H/8v/y//T/9v/4//v//v8BAAMABwAKAA0AEAATABQAFgAWABYAFQAUABEADwALAAgAAwAAAP3/+f/1//L/7//t/+z/6//r/+v/7f/u//H/8//2//n//f///wEABAAGAAgACgALAAwADAAMAAwACwALAAkACQAHAAcABQAFAAQAAwADAAIAAQABAAEAAAAAAP///v/9//z/+v/5//f/9v/0//P/8v/y//H/8v/z//T/9f/3//r//f8AAAIABQAJAAwADwASABQAFQAWABYAFQAUABIADwAMAAkABQABAP7/+v/2//P/8P/u/+z/6//r/+v/7P/u//D/8//2//n//P///wEAAwAGAAgACgAKAAsADAAMAAwACwALAAoACAAHAAYABQAEAAQAAwACAAIAAgABAAAAAAAAAAAA///+//z/+//5//j/9//1//T/8//y//L/8v/z//P/9f/3//n//P///wEABAAIAAsADgAQABMAFAAVABYAFQAUABIAEAANAAoABgACAP//+//4//T/8f/v/+3/7P/r/+v/7P/u//D/8v/1//j/+//+/wEAAwAFAAcACQAKAAsADAAMAAwACwAKAAkACAAHAAYABQAEAAQAAwACAAIAAQABAAEAAAAAAAAA///+//3//P/6//n/+P/2//X/9P/z//P/8v/z//T/9f/2//j/+//+/wAAAwAGAAkADAAPABIAEwAUABUAFQAUABMAEAAOAAoABwADAAAA/f/5//b/8v/w/+7/7f/s/+z/7P/t/+//8v/0//f/+v/+/wAAAgAFAAcACQAKAAsACwAMAAsACwAKAAkACAAHAAYABQAEAAMAAgACAAEAAQABAAAAAAAAAAAA//////7//P/7//r/+f/3//b/9f/0//P/8//z//T/9f/2//j/+v/9////AgAEAAgACwAOABAAEgAUABQAFQAUABMAEQAOAAsACAAFAAEA/v/6//f/8//x/+//7f/s/+z/7P/t/+//8f/0//f/+v/9////AgAEAAYACAAKAAsACwAMAAsACwAKAAkACAAHAAYABQAEAAMAAgACAAEAAQAAAAAAAAAAAAAAAAD///7//f/8//v/+v/4//f/9v/1//T/9P/0//T/9f/2//j/+f/8//7/AQADAAcACgAMAA8AEQATABQAFAAUABMAEQAPAAwACQAGAAEA///7//j/9f/y//D/7v/t/+z/7f/t/+//8f/z//b/+f/8////AQAEAAYACAAJAAoACwALAAsACwAKAAkACQAHAAYABQAEAAMAAgABAAEAAQAAAAAAAAAAAAAAAAD//////v/9//z/+v/5//j/9//1//X/9P/0//X/9f/2//f/+f/7//7/AAACAAUACAALAA0AEAASABMAEwATABMAEQAPAA0ACgAGAAMAAAD8//n/9v/z//H/7//t/+3/7f/t/+//8f/z//X/+P/8//7/AQADAAUABwAJAAoACwALAAsACwAKAAkACQAIAAYABQAEAAMAAgABAAEAAAAAAAAAAAAAAAAAAAAAAP///v/9//z/+//6//n/+P/2//b/9f/1//X/9f/2//f/+f/6//z///8BAAQABwAKAAwADgARABIAEwATABIAEQAQAA0ACwAHAAQAAQD+//v/9//0//L/7//u/+3/7f/u/+7/8P/y//X/+P/7//7/AAACAAUABwAIAAoACwALAAsACwAKAAkACQAIAAYABQAEAAMAAgABAAAAAAAAAAAAAAAAAAAAAAAAAAAA///+//3//P/7//r/+P/4//b/9v/1//X/9v/2//f/+P/6//z//v8AAAMABQAIAAsADQAQABEAEgATABIAEgAQAA4ACwAIAAUAAgD///z/+P/1//P/8P/v/+7/7f/u/+7/8P/y//T/9//6//3/AAACAAQABgAIAAkACgALAAsACwAKAAkACQAHAAcABQAEAAMAAgABAAAAAAAAAAAAAAAAAAAAAAAAAP/////+//7//f/8//r/+f/4//f/9//2//b/9v/2//f/+P/5//v//v///wEABAAHAAoADAAPABAAEQASABIAEQAQAA4ADAAJAAYAAwAAAP3/+v/2//T/8f/w/+//7v/u/+//8P/y//T/9//5//z///8BAAQABgAHAAkACgALAAsACwAKAAkACQAHAAcABQAEAAMAAgABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///7//f/8//v/+v/5//j/9//3//b/9v/2//f/+P/5//v//P/+/wAAAwAGAAgACwANAA8AEAARABIAEQAQAA4ADAAKAAcAAwABAP7/+//3//X/8//x/+//7//v/+//8P/y//T/9v/5//z//v8BAAMABQAHAAkACgAKAAsACwAKAAkACQAIAAcABgAEAAMAAgABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///7//v/9//z/+//6//n/+P/3//f/9//3//f/+P/5//r//P/9/wAAAgAEAAcACgAMAA4AEAAQABEAEQAQAA4ADQAKAAcABAABAP///P/5//b/9P/x//D/7//u/+//8P/x//P/9v/4//v//v8AAAIABQAHAAgACQAKAAoACgAKAAkACQAIAAcABgAEAAMAAgABAAAAAAAAAP//AAD//wAAAAAAAAAAAAAAAP///v/+//3//P/7//r/+f/4//j/9//3//j/+P/5//r/+//9////AQADAAYACAALAAwADgAQABAAEAAQAA8ADQALAAgABQACAAAA/f/6//f/9f/y//H/8P/w/+//8P/x//P/9f/4//v//f8AAAIABAAGAAgACQAKAAoACgAKAAkACQAIAAcABgAEAAMAAgABAAAAAAAAAP//////////AAAAAAAAAAAAAP/////+//3//f/8//v/+v/5//j/+P/4//j/+P/5//r/+//8//7/AAACAAUABwAJAAwADQAPAA8AEAAPAA8ADQALAAgABgADAAAA/v/7//j/9v/z//L/8P/w//D/8P/x//P/9f/3//r//f///wEAAwAFAAcACAAJAAoACgAKAAkACQAIAAcABgAFAAMAAgABAAAAAAD///////////////8AAAAAAAAAAP////////7//f/8//z/+//6//n/+f/4//j/+f/5//n/+v/8//7///8BAAQABgAIAAoADAAOAA8ADwAPAA4ADQAMAAkABwAEAAEA///8//n/9//0//P/8f/x//D/8P/x//P/9P/3//r//P///wEAAwAFAAcACAAJAAoACgAJAAkACAAIAAcABgAFAAMAAgABAAAAAAD////////+/////////wAAAAAAAAAAAAD///7//v/9//z//P/7//r/+f/5//n/+P/5//n/+v/8//3//v8AAAIABQAHAAkADAANAA4ADwAOAA4ADQAMAAoABwAFAAIAAAD9//r/+P/2//P/8v/x//D/8f/x//P/9f/2//n//P/+/wAAAgAEAAYACAAJAAkACQAKAAkACQAIAAcABgAFAAMAAgABAAAAAAD//////v////7/////////AAAAAAAAAAAAAP///v/+//3//P/8//v/+v/5//n/+f/5//r/+v/7//3//v8AAAIAAwAGAAgACgAMAA0ADgAOAA4ADQAMAAoACAAFAAMAAAD+//v/+f/2//T/8//y//L/8f/y//P/9P/3//j/+//+/wAAAgAEAAYABwAIAAkACQAKAAkACQAIAAcABgAFAAMAAgABAAAAAAD//////v/+/////v//////AAAAAAAAAAAAAAAA///+//7//f/8//z/+//6//r/+v/5//r/+v/7//z//f///wEAAgAFAAcACQAKAAwADQAOAA0ADQAMAAoACAAGAAQAAQD///3/+v/3//b/9P/z//L/8v/y//P/9P/2//n/+v/9////AQADAAUABwAIAAkACQAJAAkACAAIAAcABgAFAAMAAgABAAAAAAD///7//v/+//7////+////AAAAAAAAAAAAAAAAAAD///7//v/9//z//P/7//r/+v/6//r/+v/7//z//f/+/wAAAgADAAYACAAKAAsADAANAA0ADQALAAoACAAHAAQAAgAAAP3/+//4//b/9f/z//P/8v/y//P/9P/2//j/+v/8////AQACAAQABgAHAAgACQAJAAgACAAIAAcABgAFAAMAAgABAAAAAAD///7//v/+//3//v////////8AAAAAAAAAAAAAAAAAAP///v/+//3//P/8//v/+//6//r/+v/7//v//f/+////AQACAAUABgAJAAoACwAMAA0ADAAMAAoACQAHAAUAAwAAAP7//P/5//j/9f/0//P/8//z//P/9f/2//f/+v/8//7/AAACAAQABgAHAAgACAAJAAgACAAIAAcABgAFAAQAAwABAAAAAAD///7//v/9//7//f/+//7///8AAAAAAAAAAAAAAAAAAP/////+//7//f/8//z/+//7//r/+//7//v//P/9//7/AAACAAMABQAHAAkACgALAAwADAALAAoACQAIAAUAAwABAP///f/6//j/9v/1//T/8//0//T/9f/2//f/+v/8//7/AAACAAMABQAGAAcACAAIAAkACAAIAAcABgAFAAQAAgABAAAAAAD///7//v/9//7//f/+//7//////wAAAAAAAAAAAAAAAAAA//////7//v/9//z//P/7//v/+v/7//v//P/9//7///8BAAMABAAGAAgACQAKAAsACwALAAoACQAIAAYABAABAAAA/f/8//n/9//2//X/9P/0//T/9f/2//f/+v/7//7///8BAAMABAAGAAcACAAIAAgACAAIAAcABgAFAAQAAwABAAAAAAD///7//v/9//3//v/9//7//v///wAAAAAAAAAAAAAAAAAAAAD//////v/+//3//P/8//v/+//7//v//P/8//7///8AAAIAAwAFAAcACAAJAAoACwAKAAoACQAIAAYABAACAAAA/v/9//r/+P/3//b/9f/0//X/9f/2//j/+f/7//3///8BAAIABAAFAAYABwAIAAgABwAHAAcABgAFAAQAAwABAAEAAAD///7//v/9//3//v/9//7//v///wAAAAAAAAAAAAAAAAAAAAAAAP/////+//7//f/8//z//P/7//v//P/8//3//v///wEAAgAEAAYABwAIAAkACgAKAAoACQAIAAYABQADAAEA///+//v/+f/4//f/9v/1//X/9v/2//f/+f/7//3//v8AAAIAAwAFAAYABwAHAAgABwAHAAcABgAFAAQAAwABAAEAAAD///7//v/9//3//f/9//7//v//////AAAAAAAAAAAAAAEAAQAAAAAA//////7//v/9//z//P/8//v//P/8//3//v///wAAAgADAAUABgAHAAgACQAKAAkACQAIAAcABQADAAEA///+//z/+v/5//f/9v/1//b/9v/3//j/+f/7//z//v8AAAIAAwAEAAUABgAHAAcABwAHAAcABgAFAAQAAwACAAEAAAD///7//v/9//3//P/9//3//v/+//////8AAAAAAAABAAEAAAAAAAEAAAD//////v/+//3//P/8//v//P/8//z//v/+////AQACAAMABQAGAAcACAAIAAkACQAIAAcABQAEAAIAAQD+//3/+//5//j/9//3//b/9v/3//j/+f/6//z//v///wEAAgAEAAUABgAHAAcABwAHAAYABgAFAAQAAwACAAEAAAD//////v/9//3//P/9//3//v/+//////8AAAAAAAABAAEAAQABAAAAAQAAAAAA///+//7//f/9//z//P/8//z//f/+////AAABAAIABAAFAAYABwAIAAgACAAIAAcABgAEAAIAAQD///7//P/6//n/+P/3//f/9//3//j/+f/6//z//v///wEAAgADAAUABQAGAAYABwAHAAYABgAFAAQAAwACAAEAAAD//////v/9//3//P/9//3//f/+//////8AAAAAAAABAAEAAQACAAEAAQABAAAA//////7//v/9//3//P/8//z//f/9//////8BAAEAAwAEAAUABwAHAAgACAAHAAYABgAEAAMAAQAAAP7//f/7//r/+f/4//f/+P/4//j/+f/6//z//v///wAAAQADAAQABQAGAAYABwAGAAYABgAFAAQAAwACAAEAAAD//////v/9//3//P/8//3//f/+//7//////wAAAQABAAEAAgACAAEAAQABAAEAAAD//////v/+//3//f/8//z//f/9//7///8AAAEAAgAEAAQABgAGAAcABwAHAAYABQAFAAMAAgABAP///v/8//v/+v/5//n/+P/4//n/+v/7//z//f/+/wAAAQACAAQABAAFAAYABgAGAAYABQAFAAQAAwACAAEAAAD//////v/9//3//f/8//3//f/9//7//////wAAAQABAAEAAgACAAIAAgABAAEAAQAAAP/////+//3//f/9//z//f/9//7//////wAAAQACAAQABQAFAAYABwAGAAYABQAFAAMAAgABAP///v/9//v/+v/6//n/+f/5//n/+v/7//z//f///wAAAQACAAMABAAFAAYABgAGAAUABQAFAAQAAwACAAEAAAD//////v/9//3//f/8//3//f/9//7//////wAAAAABAAEAAgACAAMAAgACAAEAAQAAAAAA///+//7//f/9//z//f/9//3//v//////AQABAAMABAAFAAUABgAGAAYABQAEAAQAAgABAAAA///+//z/+//6//r/+f/5//r/+v/7//z//f/+////AQACAAMABAAEAAUABQAGAAUABQAEAAQAAwACAAEAAAD//////v/9//3//f/8//z//f/9//7//////wAAAAABAAIAAgACAAIAAwACAAIAAQABAAAAAAD///7//v/9//z//f/9//3//v//////AAABAAIAAwAEAAQABQAFAAUABQAEAAQAAgACAAEA///+//3//P/7//r/+v/6//r/+//7//z//v/+////AQABAAIAAwAEAAUABQAFAAUABQAEAAMAAwACAAEAAAD//////v/+//3//P/8//z//f/9//3//v//////AAABAAEAAgACAAMAAgADAAIAAgABAAEAAAAAAP///v/+//3//f/9//3//f/+//////8AAAEAAgADAAQABAAFAAUABQAEAAMAAwACAAEAAAD///7//f/8//v/+//6//v/+//8//z//v/+////AAABAAIAAwAEAAQABQAFAAQABAAEAAMAAgACAAEAAAD//////v/+//3//P/8//3//P/9//3//v//////AAABAAEAAgADAAMAAwADAAMAAgACAAEAAQAAAP/////+//7//f/9//3//f/9//7///8AAAAAAQACAAMAAwAEAAQABAAEAAMAAwACAAEAAAD//////f/9//z//P/8//v/+//8//3//v/+////AAABAAIAAwADAAQABAAEAAUABAAEAAMAAgACAAEAAAD//////v/+//3//P/8//z//f/9//3//v//////AAABAAEAAgADAAMAAwAEAAMAAwACAAIAAQAAAAAA///+//7//f/9//3//f/9//7//////wAAAAABAAIAAwADAAQABAADAAMAAgACAAEAAQD//////v/9//z//P/8//z//P/8//3//v/+////AAABAAIAAgADAAMABAAEAAQABAADAAMAAgABAAEAAAD//////v/+//3//f/8//z//f/9//3//f////////8AAAEAAgADAAMAAwAEAAQAAwADAAIAAQABAAAAAAD///7//v/9//3//f/9//3//v//////AAABAAEAAgACAAMAAwADAAMAAwACAAEAAQAAAP/////+//3//f/9//z//f/9//3//v//////AAABAAEAAgADAAMABAAEAAQAAwADAAMAAgACAAEAAAD//////v/+//3//f/8//z//P/9//3//f/+////AAAAAAEAAQADAAMAAwADAAQABAADAAMAAgABAAAAAAAAAP///v/9//3//f/9//3//f/+//////8AAAEAAQACAAIAAwADAAIAAgACAAIAAQAAAP////////7//f/9//3//f/9//7/////////AAABAAIAAgADAAMAAwADAAMAAwADAAMAAgABAAEAAAD//////v/+//3//f/8//z//P/8//3//f/+//////8AAAEAAgACAAMABAAEAAQABAAEAAMAAwACAAEAAAAAAP/////+//3//f/9//3//f/+//7//////wAAAAABAAEAAgACAAIAAgACAAIAAQAAAAAA/////////v/+//3//v/+//7//////wAAAAABAAIAAgACAAMAAwADAAMAAwACAAIAAgABAAEAAAD//////v/+//3//f/8//z//P/8//3//f/+//////8AAAEAAQACAAMABAAEAAUABAAEAAQAAwACAAEAAQAAAP/////+//3//f/9//3//f/9//7//v///wAAAAAAAAEAAQACAAIAAQACAAIAAQABAAAAAAAAAP///v////7//v///////////wAAAAABAAIAAQACAAIAAgADAAMAAgACAAIAAQABAAEAAAD///7//v/9//3//f/8//z//P/9//3//f/+//////8AAAEAAQACAAMABAAEAAUABQAEAAQABAADAAIAAQAAAAAA///+//7//f/9//3//f/9//3//v/+////AAAAAAAAAQABAAEAAgABAAIAAQABAAEAAAD//wAA//////////////////8AAAAAAQABAAIAAQACAAIAAgADAAIAAgACAAIAAQABAAAAAAD///7//v/9//3//f/8//z//P/8//3//f/+//7///8AAAAAAQACAAMABAAEAAUABQAFAAQABAADAAMAAgABAAAAAAD///7//f/9//3//P/9//3//f/+//7///8AAAAAAAABAAEAAQABAAEAAQABAAEAAAAAAP////8AAAAA//8AAP//AAAAAAEAAQABAAIAAQACAAIAAgACAAIAAgACAAEAAQABAAAAAAD//////v/9//3//P/8//z//P/8//z//f/+//7//////wEAAQACAAMABAAEAAUABQAFAAUABQAEAAMAAgABAAAAAAD///7//v/9//3//P/8//3//f/9//7//v///wAAAAAAAAEAAQABAAEAAQABAAEAAQAAAAAAAAAAAAAAAAAAAAAAAAABAAEAAQACAAEAAQACAAIAAgACAAIAAgABAAEAAQAAAAAA//////7//v/9//3//P/8//z//P/8//3//f/+//7//////wAAAQACAAMAAwAEAAUABQAGAAUABQAEAAQAAwACAAEAAAAAAP///v/9//3//P/8//z//P/9//3//v/+//////8AAAAAAAABAAEAAQABAAEAAQAAAAEAAAAAAAAAAAAAAAAAAQABAAEAAgABAAIAAQABAAIAAgACAAEAAQABAAAAAQAAAAAA//////7//v/9//z//P/8//z//P/8//z//f/9//7//////wAAAQABAAMAAwAEAAUABQAGAAYABQAFAAQAAwADAAEAAAAAAP///v/+//3//P/8//z//P/8//3//f/9//7//////wAA//8AAAEAAQABAAEAAQABAAAAAQAAAAAAAAAAAAEAAQABAAEAAgABAAIAAgACAAIAAgACAAEAAQABAAAAAQAAAP////////7//v/9//z//P/8//z//P/8//z//f/9//7//////wAAAQABAAMAAwAEAAUABQAGAAYABQAFAAUABAADAAIAAQAAAAAA///+//3//P/8//z//P/8//z//P/9//7//v/+////AAD//wAAAAABAAEAAQABAAEAAAAAAAEAAQABAAEAAQABAAIAAgACAAMAAgADAAIAAgACAAEAAQABAAEAAAD////////+//7//f/9//3//P/8//z//P/8//z//f/9//7//////wAAAQABAAIAAwAEAAUABQAGAAYABgAFAAUABAADAAMAAQAAAAAA///+//3//f/8//z//P/8//z//P/8//3//f/+//7/////////AAAAAAEAAQABAAEAAQABAAEAAQABAAEAAgACAAIAAwACAAMAAgACAAMAAgACAAEAAQAAAAAAAAD////////+//7//f/9//3//P/8//z/+//8//z//f/9//7//////wAAAQABAAIAAwAEAAUABQAGAAYABgAGAAUABQAEAAMAAgABAAAAAAD+//7//f/8//z//P/7//z/+//8//z//f/9//7//v////////8AAAAAAQABAAEAAQABAAEAAgACAAIAAwADAAMAAwADAAMAAwACAAMAAgACAAEAAQAAAAAAAAD////////+//3//f/9//z/+//8//z/+//8//z//P/9//7//////wAAAQABAAIAAwAEAAQABQAGAAYABgAGAAYABQAEAAMAAwABAAAAAAD///7//f/8//z//P/7//v/+//8//v//P/9//3//v/+//////8AAAAAAAABAAEAAQABAAIAAgACAAIAAwADAAMABAADAAMABAADAAIAAgACAAEAAQAAAAAAAAD//////v/9//3//f/8//z/+//7//v/+//8//z//P/9//7//////wAAAQABAAIAAwAEAAQABQAGAAYABwAGAAYABgAFAAQAAwACAAEAAAD///7//f/9//z//P/7//v/+//7//v/+//8//z//f/+//7//////wAAAAABAAEAAQABAAIAAwADAAMAAwAEAAQABAAEAAQAAwAEAAMAAgACAAEAAQAAAAAAAAD//////v/+//3//P/8//z/+//7//v/+//7//z//P/9//7//v///wAAAQABAAIAAwAEAAQABQAGAAYABwAHAAYABgAFAAQABAACAAEAAAAAAP///v/9//z//P/7//v/+//6//r/+//7//z//P/9//7//v//////AAABAAEAAQACAAIAAwADAAMABAAEAAQABAAFAAQABQAEAAQAAwACAAEAAQAAAAAAAAD///7//v/9//z//P/8//v//P/7//v/+//7//z//P/9//7//v//////AAABAAIAAwADAAQABQAGAAYABgAHAAYABgAGAAUABAADAAIAAQAAAP///v/9//3//P/7//v/+v/7//v/+v/7//v//P/8//3//v/+//////8AAAEAAQACAAIAAwADAAQABAAFAAUABQAFAAUABAAFAAQAAwACAAIAAQAAAAAAAAD///7//f/9//z//P/8//v/+//6//v/+//7//z//P/9//7//v//////AAABAAIAAwADAAQABQAGAAYABgAHAAcABgAGAAUABAADAAIAAQAAAAAA///9//3//P/7//v/+v/6//r/+v/6//v/+//7//z//f/+//////8AAAEAAQACAAIAAwAEAAQABQAFAAUABQAFAAYABQAFAAQAAwADAAIAAQAAAAAA//////7//f/9//z/+//7//v/+v/7//r/+//7//z//P/9//3//v//////AAABAAIAAgADAAQABQAGAAYABgAHAAYABwAGAAYABQAEAAMAAQAAAAAA///+//3//P/7//v/+v/6//r/+f/5//r/+v/7//v//P/9//7//////wAAAQACAAIAAwAEAAQABQAFAAYABgAGAAYABgAFAAUABAADAAIAAQAAAAAA//////3//f/8//z/+//7//r/+v/7//r/+//7//v//P/9//3//v//////AAABAAIAAgADAAQABQAFAAYABwAHAAcABgAGAAYABQAEAAMAAgABAAAAAAD+//3//P/8//v/+v/6//n/+v/5//n/+v/6//v//P/9//3//////wAAAQACAAIAAwAEAAUABQAGAAYABwAHAAcABgAGAAUABAAEAAIAAQAAAAAA///+//3//f/8//z/+//6//r/+v/6//r/+v/6//v//P/8//3//v//////AAABAAEAAgADAAQABQAFAAYABwAHAAcABwAHAAYABQAEAAQAAgABAAAAAAD///7//f/8//v/+v/6//r/+f/5//n/+f/6//r/+//8//3//v///wAAAQABAAIAAwAEAAUABQAGAAYABwAHAAcABwAGAAYABQAEAAMAAgABAAAA///+//3//P/8//v/+//6//r/+f/5//r/+v/6//v//P/8//3//v//////AAABAAEAAgADAAQABQAFAAYABwAHAAcABwAHAAYABgAFAAQAAwABAAAAAAD///7//f/8//v/+//6//n/+f/4//j/+f/5//r/+v/7//z//f//////AAABAAIAAwAEAAUABgAGAAcACAAIAAgABwAHAAYABgAEAAQAAgABAAAA///+//3//P/8//v/+//6//n/+v/6//n/+v/6//r/+//8//3//v//////AAABAAEAAgADAAQABQAFAAYABgAHAAcABwAHAAYABgAFAAQAAwACAAEAAAAAAP7//f/9//v/+//6//n/+f/4//n/+P/5//n/+v/7//z//f/+////AAABAAIAAwAEAAUABgAHAAcACAAIAAgACAAHAAcABgAFAAQAAwABAAAAAAD+//3//P/8//v/+v/5//r/+f/5//r/+f/6//r/+//8//3//v//////AAABAAEAAgADAAQABQAFAAYABgAHAAcABwAHAAcABgAGAAUABAADAAEAAAAAAP///v/8//z/+//6//n/+f/5//j/+P/4//n/+f/6//v//P/9//////8BAAEAAwAEAAUABgAHAAcACAAIAAkACQAIAAgABgAGAAUAAwACAAEA//////3//P/7//r/+v/6//n/+P/5//j/+f/6//r/+//8//z//v//////AAABAAEAAgADAAQABQAFAAYABgAHAAcABwAIAAcABgAGAAUABAADAAIAAQAAAP///v/9//z/+//6//n/+f/5//j/9//4//j/+f/6//r/+//9//7///8AAAEAAgAEAAUABgAHAAgACQAJAAkACQAJAAgABwAGAAUABAACAAEAAAD///3//P/7//r/+v/5//j/+f/4//j/+f/5//r/+v/7//z//f/+////AAABAAEAAgADAAQABQAGAAYABgAHAAcABwAIAAcABwAGAAUABAADAAIAAQAAAAAA/v/9//z/+//6//r/+f/4//f/+P/3//j/+P/5//r/+//8//3///8AAAEAAgAEAAUABgAHAAgACQAJAAoACQAJAAkACAAHAAYABAADAAEAAAD///7//P/7//r/+f/5//n/+P/3//j/+P/5//n/+v/7//z//f/+////AAABAAEAAgADAAQABQAGAAYABgAHAAcABwAIAAcABwAGAAYABQAEAAMAAQAAAAAA///+//3//P/6//r/+f/4//f/+P/3//f/+P/4//n/+v/7//3//v8AAAAAAgADAAUABgAHAAgACQAKAAoACgAKAAkACAAIAAYABQADAAEAAAD///7//P/7//r/+f/5//j/9//4//f/+P/4//n/+f/7//z//f/+////AAABAAEAAgADAAQABQAGAAYABgAHAAgABwAHAAgABwAGAAYABQAEAAMAAgABAAAA///+//3//P/7//r/+f/4//f/9//3//f/9//4//j/+v/7//z//f///wAAAgADAAQABgAHAAgACQAKAAoACwAKAAoACQAIAAcABQAEAAIAAQAAAP7//P/7//r/+f/4//j/9//4//f/9//4//n/+f/6//v//P/9////AAAAAAEAAgADAAQABQAGAAYABgAHAAcACAAHAAgABwAHAAYABQAEAAMAAgABAAAAAAD+//3//P/7//r/+f/4//f/9//3//f/9//3//j/+f/6//z//f/+/wAAAQACAAQABQAHAAgACQAKAAsACwALAAoACgAJAAgABgAEAAMAAQAAAP///f/7//r/+f/4//j/9//3//b/9//3//j/+f/6//v//P/9////AAAAAAEAAgADAAQABQAGAAYABwAHAAcACAAHAAgABwAGAAYABQAFAAQAAgACAAAAAAD///3//P/7//r/+f/4//j/9//2//b/9//3//f/+f/5//v//f/+////AQACAAMABQAHAAgACQAKAAsACwALAAsACgAJAAgABwAFAAMAAQAAAP///f/7//r/+f/4//f/9//2//f/9v/3//f/+P/5//v/+//9//7/AAAAAAEAAgADAAQABQAGAAYABwAHAAcABwAIAAgABwAHAAYABQAFAAQAAwACAAEAAAD///7//f/8//r/+v/4//j/9//2//b/9v/3//f/+P/5//r/+//9////AAABAAMABQAHAAgACQAKAAsADAALAAsACwAKAAkABwAGAAQAAgABAP///f/8//r/+f/4//f/9v/2//b/9v/3//f/+P/5//r/+//9//7///8AAAEAAgADAAQABQAGAAYABwAHAAcACAAHAAgABwAHAAcABgAFAAQAAwACAAEAAAAAAP7//f/8//v/+v/5//j/9//3//b/9v/2//f/9//4//n/+//8////AAABAAMABQAGAAgACQAKAAsADAAMAAwADAALAAoACAAHAAQAAwABAAAA/v/8//r/+f/4//f/9v/2//X/9v/2//f/9//4//r/+//8//7///8AAAEAAgADAAQABQAGAAYABwAHAAcACAAHAAgACAAHAAcABgAFAAUAAwADAAEAAAAAAP///f/8//v/+v/5//j/9//3//b/9v/2//b/9//4//n/+v/8//3///8BAAIABAAGAAgACQALAAsADAANAAwADAALAAoACQAHAAYABAABAAAA/v/8//r/+f/4//f/9v/1//X/9f/2//b/9//4//n/+v/8//3///8AAAEAAgADAAQABQAGAAYABwAHAAgACAAHAAgACAAHAAcABgAFAAUABAADAAEAAQAAAP///v/9//v/+v/5//j/9//3//b/9v/2//b/9v/3//j/+v/7//3///8AAAEABAAFAAcACQAKAAsADAANAA0ADAAMAAsACQAIAAYABQACAAAA///9//v/+f/4//f/9v/1//X/9f/1//b/9v/3//n/+v/7//3//////wEAAgADAAQABQAGAAYABwAHAAcACAAHAAgABwAHAAcABgAFAAUABAADAAIAAQAAAP///v/9//z/+//6//n/9//3//b/9v/2//b/9v/3//j/+f/7//z//v8AAAEAAwAFAAcACAAKAAsADAANAAwADQAMAAsACgAIAAcABQACAAEA///9//z/+f/4//f/9v/1//X/9f/1//X/9v/3//j/+v/7//z//v8AAAAAAQADAAQABQAGAAYABwAHAAcACAAHAAgABwAHAAcABgAGAAUABAADAAIAAQAAAAAA///+//z/+//6//n/+P/3//f/9v/2//b/9v/3//j/+f/6//z//v///wEAAgAEAAYACAAKAAoADAAMAA0ADQAMAAwACgAJAAcABQAEAAEAAAD+//z/+v/5//f/9v/1//X/9f/1//X/9v/3//j/+f/7//z//v///wAAAQADAAQABQAGAAYABwAHAAcACAAHAAgABwAHAAcABgAFAAUABAADAAMAAgAAAAAA///+//3//P/7//n/+f/4//f/9//2//b/9v/3//f/+P/6//v//f///wAAAgAEAAYABwAJAAoACwAMAA0ADQAMAAwACwAJAAgABQAEAAIAAAD///z/+v/5//j/9v/1//X/9f/1//X/9v/3//j/+f/6//z//f///wAAAQACAAMABAAFAAYABwAHAAcACAAHAAgABwAHAAcABgAGAAUABAADAAMAAQABAAAA///+//3//P/7//r/+f/4//f/9//2//b/9v/3//f/+P/5//v//P/+/wAAAQADAAUABwAIAAoACwAMAAwADQAMAAwACwAKAAgABwAFAAIAAAD///3/+//5//j/9//2//X/9f/1//X/9v/3//f/+f/6//v//f///wAAAQACAAMABAAFAAYABgAHAAcABwAIAAgABwAHAAYABgAFAAUABAADAAMAAgABAAAAAAD///7//P/8//r/+f/5//j/9//3//b/9v/3//f/+P/5//r//P/+////AAACAAQABgAIAAkACwALAAwADQANAAwACwAKAAgABwAFAAMAAQAAAP7//P/6//j/9//2//X/9f/1//X/9f/2//f/+f/6//v//f/+/wAAAAACAAMABAAFAAYABgAHAAcABwAIAAcABwAHAAYABgAFAAUABAADAAMAAgABAAAAAAD///7//f/8//v/+v/5//j/9//3//f/9//3//f/+P/5//r/+//9////AAACAAQABQAHAAkACgALAAwADAANAAwACwAKAAkACAAFAAQAAQAAAP///P/6//n/+P/2//b/9f/1//X/9f/2//f/+P/5//v//P/+/wAAAAABAAMABAAFAAYABgAHAAcABwAHAAcABgAHAAYABgAFAAUABAADAAMAAgABAAAAAAD///7//f/9//v/+v/5//n/+P/3//f/9//3//f/+P/5//r/+//9//7/AAABAAMABQAGAAgACgALAAsADAAMAAsACwAKAAkACAAGAAQAAgAAAP///f/7//n/+P/3//b/9f/1//X/9f/2//f/+P/5//r//P/+////AAABAAIABAAEAAYABgAGAAcABwAHAAcABwAGAAYABgAFAAUABAAEAAMAAgABAAAAAAAAAP///v/9//z/+//6//n/+P/4//f/9//3//f/+P/4//r/+//8//7/AAAAAAIABAAGAAcACQAKAAsADAALAAwACwALAAkACAAHAAUAAwABAAAA/v/8//r/+P/3//b/9v/1//X/9f/2//f/+P/5//r//P/9////AAABAAIAAwAEAAUABgAGAAcABwAHAAcABwAGAAYABgAFAAUABAAEAAMAAgABAAEAAAAAAP///v/9//z/+//6//r/+f/4//j/9//3//f/+P/4//n/+v/8//3///8AAAIAAwAFAAcACAAKAAoACwAMAAwACwALAAoACAAHAAUAAwABAAAA///8//r/+f/4//f/9v/1//b/9f/2//f/9//5//r/+//9//7/AAAAAAIAAwAEAAUABgAGAAcABgAHAAYABwAGAAYABQAFAAUABAADAAMAAgABAAEAAAAAAP///v/+//3/+//7//r/+f/5//j/+P/4//j/+P/4//n/+v/7//3///8AAAEAAwAEAAYACAAJAAoACwALAAwACwALAAoACQAHAAYABAACAAAA///9//z/+f/4//f/9v/2//b/9f/2//f/9//4//r/+//8//7/AAAAAAEAAwAEAAUABQAGAAcABgAHAAYABwAGAAYABQAFAAUABAADAAMAAgACAAEAAAAAAP/////+//3//P/7//v/+v/5//j/+P/4//j/+P/4//n/+v/7//z//v8AAAAAAgAEAAUABwAIAAoACgALAAsACwALAAoACQAIAAYABAACAAEA///9//z/+v/5//j/9//2//X/9f/2//f/9//4//n/+//8//7///8AAAEAAgADAAQABQAGAAYABwAGAAYABwAGAAYABQAFAAQABAADAAMAAgABAAEAAAAAAAAA///+//3//f/7//v/+v/5//n/+P/4//j/+P/5//n/+v/7//z//v///wAAAgADAAUABgAIAAkACgAKAAsACwAKAAoACQAIAAYABQADAAEAAAD///z/+//5//j/9//2//b/9f/2//b/9//4//n/+v/8//3///8AAAEAAgADAAQABQAFAAYABwAGAAcABwAGAAYABQAFAAQABAADAAMAAgABAAEAAAAAAAAA///+//7//f/8//v/+v/6//n/+f/5//j/+P/5//n/+v/7//z//f///wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"), char => char.charCodeAt(0)));
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
        this.stop(); play(impact, 1.4);
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
      function focusPlayback(pointer = false) {
        const active = document.activeElement;
        if (root.querySelector(".curator-roulette-settings.show") || active?.matches("input, textarea, select, [contenteditable=true]")) return;
        if (!pointer && active?.closest(".curator-roulette-hud, .curator-roulette-controls") && active.matches(":focus-visible")) return;
        const native = Api.utils.InteractiveUtils.getPlayer();
        if (session.phase === "playing" && native?.el()?.contains(media)) native.focus();
        else if (pointer) root.focus({ preventScroll: true });
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
        resetShape(); publish("playing"); focusPlayback();
      }
      function bind() {
        const element = host.querySelector("video");
        if (element !== media) {
          if (media) {
            media.removeEventListener("loadeddata", reveal); media.removeEventListener("error", mediaError); media.removeEventListener("volumechange", volumeChanged);
            ["playing", "pause", "waiting", "ended", "canplay", "seeked"].forEach((event) => media.removeEventListener(event, wake));
          }
          media = element;
          if (media) {
            // Stash preloads nothing; load a frame even when the browser blocks autoplay.
            media.preload = "auto"; media.muted = muted;
            media.addEventListener("loadeddata", reveal); media.addEventListener("error", mediaError); media.addEventListener("volumechange", volumeChanged);
            ["playing", "pause", "waiting", "ended", "canplay", "seeked"].forEach((event) => media.addEventListener(event, wake));
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
        focus() { if (!session.closed && root.isConnected) focusPlayback(true); },
        hotkeys(event) {
          if (session.phase !== "playing" || event.metaKey || event.defaultPrevented) return false;
          const target = event.target;
          if (target.closest(".video-js, input, textarea, select, [contenteditable=true], [role=slider], .dropdown-menu")) return false;
          if (target.closest(".curator-roulette-hud, .curator-roulette-controls") && target.matches(":focus-visible")) return false;
          if (![" ", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "m", "l", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "[", "]"].includes(event.key)) return false;
          const native = Api.utils.InteractiveUtils.getPlayer(), handler = native?.options()?.userActions?.hotkeys;
          if (typeof handler !== "function" || !native.el()?.contains(media)) return false;
          native.focus(); handler.call(native, event); return true;
        },
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
          ["playing", "pause", "waiting", "ended", "canplay", "seeked"].forEach((event) => media.removeEventListener(event, wake));
        }
        sound?.stop(); audio?.close().catch(() => {}); document.body.style.overflow = overflow;
        if (document.fullscreenElement === root) document.exitFullscreen().catch(() => {});
        if (focus?.isConnected) focus.focus();
      };
    }, [session, onClose]);
    const busy = ["loading", "assembling", "spinning", "rewinding", "celebrating", "landing", "revealing", "returning"].includes(view.phase);
    return ReactDOM.createPortal(React.createElement("dialog", { ref: dialog, className: "curator-roulette-dialog", "aria-label": "Roulette player", onCancel: (event) => { event.preventDefault(); controller.current?.close(); } },
      React.createElement("div", { ref: stage, className: "curator-roulette-stage", tabIndex: -1, "data-phase": view.phase, "data-intro": view.index < 0,
      onClickCapture: (event) => {
        if (event.detail > 0 && event.target.closest(".curator-roulette-hud button, .curator-roulette-controls button, .curator-roulette-controls a")) requestAnimationFrame(() => controller.current?.focus());
      }, onKeyDownCapture: (event) => {
        if (event.target.closest("input, textarea, select, [contenteditable=true], .dropdown-menu")) return;
        if (event.key.toLowerCase() === "f" && !event.ctrlKey && !event.altKey && !event.metaKey) {
          event.preventDefault(); event.stopPropagation(); controller.current?.fullscreen();
        } else if (controller.current?.hotkeys(event.nativeEvent)) {
          event.preventDefault(); event.stopPropagation();
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
          React.createElement("div", { className: "curator-roulette-controls" },
            React.createElement("div", { className: "curator-roulette-status", role: "status", "aria-live": "polite" },
            view.error || (view.phase === "loading" ? "Loading contenders…" : view.phase === "assembling" ? "Gathering your lane…" : view.phase === "spinning" ? "Spinning…" : view.phase === "rewinding" ? "Returning to your previous pick…" : view.phase === "celebrating" ? "Your pick" : view.phase === "landing" ? "Loading selected scene…" : view.phase === "exhausted" ? "No recommendations qualify right now." : entry?.scene?.title || "Untitled scene")),
            entry && React.createElement(RouletteActions, { key: entry.origin.scene_id, entry, disabled: busy || view.phase !== "playing", onOpen: () => controller.current.pause() })),
          React.createElement("div", null,
            React.createElement("div", { className: "curator-roulette-navigation" },
              React.createElement(Button, { variant: "dark", disabled: busy || view.index < 1, onClick: previous }, "Back"),
              React.createElement(Button, { variant: "primary", disabled: busy || view.phase === "exhausted", onClick: next }, "Next"),
              view.phase === "error" && React.createElement(Button, { variant: "dark", onClick: () => controller.current.retry() }, "Retry"),
              view.phase === "exhausted" && React.createElement(Button, { variant: "primary", onClick: () => controller.current.retry() }, "Retry")),
            React.createElement(Button, { variant: "dark", size: "sm", "aria-pressed": view.muted, onClick: () => controller.current.mute() }, view.muted ? "Unmute" : "Mute"),
            React.createElement(libraries.Bootstrap.Dropdown, { alignRight: true, className: "curator-roulette-settings" },
              React.createElement(libraries.Bootstrap.Dropdown.Toggle, { id: "curator-roulette-settings", variant: "dark", size: "sm", "aria-label": "Roulette settings", title: "Roulette settings" }, React.createElement(FontAwesomeIcon, { icon: faCog })),
              React.createElement(libraries.Bootstrap.Dropdown.Menu, null, React.createElement(RouletteAnimationSetting, { compact: true }))),
            React.createElement(Button, { variant: "dark", size: "sm", onClick: () => controller.current.fullscreen() }, "Fullscreen"),
            React.createElement(Button, { variant: "dark", size: "sm", onClick: () => controller.current.close() }, "Exit")))
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
  // Pages use after, not instead: Stash wraps each later instead patch in a new
  // Proxy per render, so a plugin rendering its continuation as <Original />
  // would remount the page (and reset its tabs) whenever it re-renders.
  Api.patch.after("ScenePage", function (props, ...args) {
    const result = args[args.length - 1];
    return React.createElement(React.Fragment, null, result, React.createElement(CuratorContextLink, { type: "scene", id: props.scene.id, label: props.scene.title || `Scene ${props.scene.id}`, scene: props.scene }), React.createElement(LanePlaylistControls, { sceneId: props.scene.id }));
  });
  Api.patch.after("PerformerPage", function (props, ...args) {
    const result = args[args.length - 1];
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
