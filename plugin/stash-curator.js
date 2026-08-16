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
  const { faDev } = libraries.FontAwesomeBrands;
  const { faBalanceScale, faBroom, faBullseye, faCheckCircle, faClock, faClone, faCog, faCompass, faCopy, faCrosshairs, faDatabase, faDownload, faExternalLinkAlt, faFilm, faFilter, faGlobe, faHeart, faHistory, faList, faMoon, faPlay, faPlayCircle, faSearch, faSortAmountDown, faStar, faSun, faSync, faTag, faThumbsDown, faThumbsUp, faUser, faUserCheck, faVenus, faWrench, faXmark } = libraries.FontAwesomeSolid;
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
      value: "curate",
      label: "Curate",
      icon: faBullseye,
      description: "Compare scenes in pairs to teach the model fast, or review tag sentiment.",
    },
    {
      value: "similar",
      label: "Similar",
      icon: faClone,
      description: "Choose a scene or performer, then compare preference-aware matches from your Library or StashDB.",
    },
    {
      value: "expand",
      label: "Expand",
      icon: faGlobe,
      description: "External metadata candidates scored locally. Wildcard items are selected outside preference-derived seeds.",
    },
    {
      value: "hunt",
      label: "Performer Hunt",
      icon: faCrosshairs,
      description: "Find scenes listed for a performer on StashDB and compare them with exact links in your library.",
    },
    {
      value: "taste",
      label: "Taste Profile",
      icon: faTag,
      maintenance: true,
      description: "Review what Curator has inferred and directly teach it how you feel about tags.",
    },
    {
      value: "sentiment",
      label: "Sentiment review",
      icon: faBalanceScale,
      maintenance: true,
      description: "Review the model's sentiment estimates: least-appealing scenes first, with reasons and feedback on each card.",
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
      description: "Revisit qualified recommendations with the reasons recorded when each card appeared.",
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
      value: "diagnostics",
      label: "Diagnostics",
      icon: faWrench,
      maintenance: true,
      description: "Preview and export a privacy-safe status report for bug reports.",
    },
    {
      value: "profiling",
      label: "Profiling",
      icon: faDev,
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
    description: "A balanced shelf of strong matches, timely revisits, and a little discovery, split into five lanes.",
  };
  const MANAGE_NAV_ITEM = {
    value: "manage",
    label: "Manage",
    icon: faWrench,
    description: "Feedback history, taste profile, sentiment review, recent recommendations, backups, diagnostics, prune queues, and profiling.",
  };
  const TOP_NAV_ITEMS = [
    RECOMMENDATIONS_NAV_ITEM,
    ...PRIMARY_NAV_ITEMS.filter((item) => !laneByValue.has(item.value)),
    MANAGE_NAV_ITEM,
  ];
  const EVENT_QUEUE_KEY = "stash-curator:event-queue:v1";
  const THEME_STORAGE_KEY = "stash-curator:theme";
  const TAG_PREFERENCE_QUEUE_KEY = "stash-curator:tag-preference-queue:v1";
  const TERM_PREFERENCE_QUEUE_KEY = "stash-curator:term-preference-queue:v1";
  const ORIGIN_KEY = "stash-curator:origin:v1";
  const PICKS_STATE_KEY = "stash-curator:picks-state:v1";
  const CURATE_NUDGE_KEY = "stash-curator:curate-nudge:v1";
  // The For You nudge retires after this many submitted rounds: by then the
  // Curate flow is discovered and the impact report is the better hook.
  const MAX_NUDGE_ROUNDS = 3;
  const SLATE_CACHE_KEY = "stash-curator:slates:v1";
  const FILTER_PRESETS_KEY = "stash-curator:filter-presets:v1";
  const WHISPARR_LOGO = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAACXBIWXMAAAAyAAAAMgFOp+RzAAAAGXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAxZJREFUOI1tk0tMXHUYxX///713HjDMXB4zpdBBgVKSVobWQY10WGCsSVsTJxqbNF1pNy5cSWJ07cYmbeLapUl9JCbqommiLvoAKZA2pdQSmcnQQQp1nlCY6czc/73XRYXQxLM+38n3fecckUwm2YsHd5YTVsO6aFluTBOGBgLbbdiGIeallBNDrx78Yy9f7AikUilPtcgNlDfe1zqmD4ZO49WCAFTtEumNq6TLk0p6G7fa9vveiEaj1q5AKpXyVApkw97B8PHOCU0Ijf+D41pMrV+y8/WlfO/hSNQ0TSUBqkVuhL2D4cT+TzUhNBwUj6ozpDaucL/w/a6AFAZjXZ9pHd5D4Wy68DuA5lS9CadmfH6i5wtdCMHy1jUqao3uptfwG+3k64t0Nh19bpOeltfl6tbtrkwmm5HKUhf62hK6cqsslL6ju2mEaPMYQmgsln/msPkua5UZpta+wsV59jg0cByPYfCRtCyOvRBIsFD8kSOtZ/BoLQAsb/1GtOUVstvXmX18mWORcwgkAKuVafpD4yjLjUuJ0BZLvxBrP4sUOgCl+hK2bbNZ/xvbUYx2nadJDwNQUTkeby/QF3wT15YeiXSc7sBRNGmQq91jW62T3ZxESJdoYBQERPzDACjnKfO5b4mFz/13Cq4UQlil2gq56n1Mo5f5/A+EfAfoD54kvfkrh8y3AbDdOnfzl4nv+wCPbKaqyqA7DSkk92wsIv4h5v75mg5/L33Bt6jZRVp9vUh0LGeLu4VveCn8Hl4tBED6yVV0XdzR0fjkYXlmSrpSN309DJrvAPDEWiWgR1itTFO3N3i540N2Aua4ikx5Ugk/E3J4ZGBW91uT5UbGPtL2/q7XEV8MhGCff4j+4En2pnNq/ZItjPqtWHxgTgJEBzpOlOorheuPvrRdV+3UhJDxIoYM7A66KG6uXbBztb8KmfU/xwF0ANM01Ur+2gHZKW/+lP54pL/tuH4wdIpmvf1ZmVSRpc0rPNyYVsJozKzkH4wnk0n1XBt3sDCbHrUd96KtGBauMAAX4SrN4LbQmYjFB+b28v8FOo1CLH194s4AAAAASUVORK5CYII=";
  const similarityCache = new Map();
  // Stale similarity results must never outlive a code change: entries expire
  // after this TTL even if the page stays open, and the cache key is stamped
  // with the backend code hash so any plugin update busts it immediately.
  const SIMILARITY_CACHE_TTL_MS = 5 * 60 * 1000;
  const restoredCache = readSlateCache();
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

  async function operation(args, timeoutMs = 30000) {
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

  function readCurateNudge() {
    try {
      const value = JSON.parse(localStorage.getItem(CURATE_NUDGE_KEY) || "null");
      return { rounds: Number(value && value.rounds) || 0, dismissed: !!(value && value.dismissed) };
    } catch (_) {
      return { rounds: 0, dismissed: false };
    }
  }
  function bumpCurateRounds() {
    const state = readCurateNudge();
    localStorage.setItem(CURATE_NUDGE_KEY, JSON.stringify({ rounds: state.rounds + 1, dismissed: state.dismissed }));
  }
  function dismissCurateNudge() {
    const state = readCurateNudge();
    localStorage.setItem(CURATE_NUDGE_KEY, JSON.stringify({ rounds: state.rounds, dismissed: true }));
  }
  function readPicksState() {
    try {
      const value = JSON.parse(localStorage.getItem(PICKS_STATE_KEY) || "null");
      if (!value || typeof value !== "object" || !value.round) {
        return null;
      }
      return {
        round: value.round,
        answers: value.answers && typeof value.answers === "object" ? value.answers : {},
      };
    } catch (_) {
      return null;
    }
  }

  function writePicksState(state) {
    try {
      localStorage.setItem(PICKS_STATE_KEY, JSON.stringify(state));
    } catch (_) {
      // In-memory state still works if storage is unavailable.
    }
  }

  function clearPicksState() {
    try {
      localStorage.removeItem(PICKS_STATE_KEY);
    } catch (_) {
      // Nothing to recover; the panel resets in memory regardless.
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

  function clearSlateCache() {
    slateCache.clear();
    slateRequests.clear();
    cachedModelId = null;
    cachedConfigUpdatedAtMs = null;
    sessionStorage.removeItem(SLATE_CACHE_KEY);
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
      React.createElement(Button, { size: "sm", disabled: loading || page === 1, onClick: () => onPage(page - 1), "aria-label": "Previous page" }, "Previous"),
      pagerPages(page, totalPages).map((value, index) => value === null
        ? React.createElement("span", { key: `ellipsis-${index}`, className: "curator-pager-ellipsis", "aria-hidden": "true" }, "…")
        : React.createElement(Button, { key: value, size: "sm", variant: value === page ? "primary" : "secondary", disabled: loading || value === page, onClick: () => onPage(value), "aria-label": `Page ${value}`, "aria-current": value === page ? "page" : undefined }, value)),
      React.createElement("span", { className: "curator-pager-summary" }, `Page ${page} of ${totalPages}`),
      React.createElement(Button, { size: "sm", disabled: loading || page >= totalPages, onClick: () => onPage(page + 1), "aria-label": "Next page" }, "Next")
    );
  }

  function readFilterPresets() {
    try { return JSON.parse(localStorage.getItem(FILTER_PRESETS_KEY) || "{}") || {}; }
    catch (_) { return {}; }
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

  function loadSlate(lane, page = 1, prefetched = false) {
    const key = slateKey(lane, page);
    if (slateCache.has(key)) return Promise.resolve(slateCache.get(key));
    if (slateRequests.has(key)) return slateRequests.get(key);
    const generation = cacheGeneration;
    const request = operation({
      operation: "get_slate",
      lane,
      page,
      exclude_scene_ids: [...(laneExclusions.get(lane) || [])],
      exploration: 0,
      context: { route: location.pathname, prefetched },
    })
      .then((data) => {
        if (generation !== cacheGeneration) return data;
        const modelChanged = cachedModelId && cachedModelId !== data.model_id;
        const configChanged = cachedConfigUpdatedAtMs !== null && cachedConfigUpdatedAtMs !== data.config_updated_at_ms;
        if (modelChanged || configChanged) {
          clearSlateCache();
          if (modelChanged) laneExclusions.clear();
        }
        cachedModelId = data.model_id;
        cachedConfigUpdatedAtMs = data.config_updated_at_ms;
        slateCache.set(slateKey(lane, page), data);
        persistSlateCache();
        return data;
      })
      .finally(() => slateRequests.delete(key));
    slateRequests.set(key, request);
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
    return payload.data.configurePlugin;
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

  // Stash records plays without bumping scenes.updated_at, so only the play pass can bring
  // cooldown and recovery context up to date. It is cheap (a watermark query since the last
  // sync) and runs as an async Stash job, so coalesce bursts before firing it.
  function schedulePlaySync() {
    clearTimeout(playSyncTimer);
    playSyncTimer = setTimeout(() => {
      runTask("Sync recent plays").catch(() => {
        // Retry on the next play, route change, or online event.
      });
    }, 8000);
  }

  function idFilter(ids) {
    return ids.reduce(
      (filter, id) => ({ id: { value: Number(id), modifier: "EQUALS" }, ...(filter && { OR: filter }) }),
      null
    );
  }

  function performerNameFilter(items) {
    return items.reduce(
      (filter, item) => ({ name: { value: item.label, modifier: "EQUALS" }, ...(filter && { OR: filter }) }),
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

  function reasonLabel(code) {
    const labels = {
      "appeal.performer_identity": "Performer match",
      "appeal.content_neighbor": "Similar content",
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

  // A single 6-stop control: "Never" is stop 0 on the same track as the 5
  // sentiment levels (not a separate toggle) — set apart visually with its
  // own color and a divider line, per the #150 design brief, but still one
  // continuous range input rather than a track plus an out-of-band button.
  function TagSentimentControl({ tag, value, blocked, onChange, compact = false }) {
    const rated = (value !== null && value !== undefined) || blocked;
    const stopIndex = blocked ? 0 : rated ? SENTIMENTS.findIndex(([score]) => score === value) + 1 : 3;
    const currentLabel = blocked ? "Never" : rated ? SENTIMENTS[stopIndex - 1][1] : "Not rated";
    const tierClass = blocked ? "curator-sentiment-never" : rated ? SENTIMENTS[stopIndex - 1][2] : "";
    function handleChange(event) {
      const index = Number(event.target.value);
      if (index === 0) onChange({ value: null, blocked: true });
      else onChange({ value: SENTIMENTS[index - 1][0], blocked: false });
    }
    return React.createElement(
      "div",
      { className: `curator-sentiment curator-sentiment-slider${compact ? " curator-sentiment-compact" : ""}`, role: "group", "aria-label": `Sentiment for ${tag.name}` },
      React.createElement(
        "label",
        { className: `curator-sentiment-range-wrap${tierClass ? ` ${tierClass}` : ""}` },
        !compact && React.createElement("span", { className: "curator-sentiment-current" }, currentLabel),
        React.createElement(
          "span",
          { className: "curator-sentiment-track" },
          React.createElement("span", { className: "curator-sentiment-divider", "aria-hidden": "true" }),
          React.createElement("input", {
            type: "range",
            min: "0",
            max: "5",
            step: "1",
            className: `curator-sentiment-range${!rated ? " curator-sentiment-range-unset" : ""}${blocked ? " curator-sentiment-range-blocked" : ""}`,
            value: stopIndex,
            "aria-label": `Sentiment for ${tag.name}`,
            "aria-valuetext": currentLabel,
            onChange: handleChange,
          })
        )
      ),
      (rated || compact) && React.createElement(Button, { size: "sm", variant: "link", className: compact && !rated ? "curator-sentiment-clear-placeholder" : undefined, "aria-label": "Clear answer", title: "Clear answer", onClick: () => onChange({ value: null, blocked: false }) }, compact ? "Clear" : "Clear answer")
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

  function readTermPreferenceQueue() {
    try {
      const value = JSON.parse(localStorage.getItem(TERM_PREFERENCE_QUEUE_KEY) || "[]");
      return Array.isArray(value) ? value : [];
    } catch (_) {
      return [];
    }
  }

  let flushingTermPreferences = false;
  async function flushTermPreferenceQueue() {
    if (flushingTermPreferences) return;
    const entries = readTermPreferenceQueue();
    if (!entries.length) return;
    flushingTermPreferences = true;
    try {
      await operation({ operation: "submit_term_preferences", entries });
      const sent = new Set(entries.map((entry) => entry.preference_id));
      localStorage.setItem(TERM_PREFERENCE_QUEUE_KEY, JSON.stringify(readTermPreferenceQueue().filter((entry) => !sent.has(entry.preference_id))));
      clearSlateCache();
      scheduleModelUpdate();
    } catch (_) {
      // Retry on the next route, online event, or plugin page load.
    } finally {
      flushingTermPreferences = false;
    }
  }

  function submitTermPreference(term, {value, blocked}) {
    const queue = readTermPreferenceQueue();
    queue.push({ preference_id: uuid(), term, value, blocked: !!blocked, occurred_at_ms: Date.now() });
    localStorage.setItem(TERM_PREFERENCE_QUEUE_KEY, JSON.stringify(queue));
    flushTermPreferenceQueue();
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
        React.createElement("strong", { className: "curator-external-tag-name" }, row.name),
        React.createElement(TagSentimentControl, {
          tag: { name: row.name },
          value: row.direct_value,
          blocked: row.direct_blocked,
          compact: true,
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
      React.createElement("strong", { className: "curator-rating-section-title" }, `${title} (${rows.length})`),
      React.createElement(RatingRows, { rows, onAnswer, emptyLabel })
    );
  }

  // LocalRatingPanel is the "Rate tags & terms" expander for local cards
  // (recommendation lanes and library Similar): the scene's classified tags
  // (get_scene_tag_choices) plus its built description terms. The toggle
  // renders above the expanded list, and the panel sits outside card-section
  // so the SFW Switch contract holds.
  function LocalRatingPanel({ sceneId }) {
    const [open, setOpen] = React.useState(false);
    const [tagChoices, setTagChoices] = React.useState(null);
    const [termChoices, setTermChoices] = React.useState(null);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState("");
    useCuratorActivity(`local-tags-${sceneId}`, loading, "Matching local tags…");
    async function toggle() {
      if (open) {
        setOpen(false);
        return;
      }
      setOpen(true);
      setLoading(true);
      setError("");
      try {
        const [tagsResult, termsResult] = await Promise.all([
          operation({ operation: "get_scene_tag_choices", scene_id: sceneId }),
          operation({ operation: "get_scene_description_tokens", scene_id: sceneId }),
        ]);
        setTagChoices(tagsResult.items);
        setTermChoices(termsResult.items);
      } catch (failure) {
        setError(failure.message);
        setTagChoices([]);
        setTermChoices([]);
      } finally {
        setLoading(false);
      }
    }
    function answerTag(row, {value, blocked}) {
      submitTagPreference(row.tag_id, {value, blocked});
      setTagChoices((current) => current.map((item) => item.tag_id === row.tag_id ? { ...item, direct_value: value, direct_blocked: !!blocked } : item));
    }
    function answerTerm(row, {value, blocked}) {
      submitTermPreference(row.term, {value, blocked});
      setTermChoices((current) => current.map((item) => item.term === row.term ? { ...item, direct_value: value, direct_blocked: !!blocked } : item));
    }
    return React.createElement(
      React.Fragment,
      null,
      React.createElement(
        Button,
        { className: "curator-icon-action", size: "sm", variant: open ? "primary" : "secondary", title: "Rate tags & terms", "aria-label": "Rate tags & terms", "aria-pressed": open, onClick: toggle },
        React.createElement(FontAwesomeIcon, { icon: faTag })
      ),
      open && React.createElement(
        "div",
        { className: "curator-external-tag-rating" },
        React.createElement(
          "div",
          { className: "curator-external-tag-rating-header" },
          React.createElement("strong", null, "Rate tags & terms"),
          React.createElement(Button, { size: "sm", variant: "link", className: "curator-external-tag-rating-close", "aria-label": "Collapse matching local tag ratings", title: "Collapse matching local tag ratings", onClick: toggle }, "Collapse")
        ),
        loading && React.createElement("small", { role: "status" }, "Matching local tags…"),
        error && React.createElement("small", { className: "text-danger", role: "status" }, error),
        !loading && !error && React.createElement(
          React.Fragment,
          null,
          React.createElement(RatingSection, { title: "Matching local tags", rows: tagChoices.map((tag) => ({ key: tag.tag_id, tag_id: tag.tag_id, name: tag.name, direct_value: tag.direct_value, direct_blocked: tag.direct_blocked })), onAnswer: answerTag, emptyLabel: "No matching local tags." }),
          React.createElement(RatingSection, { title: "Description terms", rows: termChoices.map((term) => ({ key: term.term, term: term.term, name: term.term, direct_value: term.direct_value, direct_blocked: term.direct_blocked })), onAnswer: answerTerm, emptyLabel: "No description terms in the model." })
        )
      )
    );
  }

  function TasteProfilePanel({ embedded = false } = {}) {
    const [data, setData] = React.useState(null);
    const [error, setError] = React.useState("");
    const [query, setQuery] = React.useState("");
    const [sort, setSort] = React.useState("suggested");
    const [status, setStatus] = React.useState("all");
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
    return React.createElement(
      "section",
      { className: "curator-taste", "aria-labelledby": embedded ? undefined : "curator-taste-title" },
      !embedded && React.createElement("h2", { id: "curator-taste-title" }, "Taste Profile"),
      !embedded && React.createElement("p", null, "Declared answers are strong evidence, not hard exclusions. Clear an answer to return to behavior-derived inference."),
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
        visibleItems.map((item) =>
          React.createElement(
            "article",
            { key: item.tag_id, className: "curator-taste-item" },
            React.createElement("div", null,
              React.createElement("strong", null, item.name),
              item.prompt && React.createElement("span", { className: "badge badge-info" }, item.prompt === "belief" ? `I think you ${item.inferred_value >= 0 ? "like" : "dislike"} this` : "I'm unsure"),
              React.createElement("small", null, `Inferred ${item.inferred_value.toFixed(2)} · confidence ${item.confidence.toFixed(2)} · support ${item.support.toFixed(1)} · ${item.scene_count} local scene${item.scene_count === 1 ? "" : "s"}`)
            ),
            React.createElement(TagSentimentControl, { tag: item, value: item.direct_value, blocked: item.direct_blocked, onChange: (value) => answer(item.tag_id, value) })
          )
        )
      )
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

  function ImpactSceneCard({ entry }) {
    const why = (entry.contributors || []).map((contributor) => `${contributor.name} ${fmtDelta(contributor.delta)}`).join(" · ");
    return React.createElement(
      "a",
      { className: "curator-impact-scene", href: `/scenes/${entry.scene_id}`, target: "_blank", rel: "noopener noreferrer" },
      React.createElement("img", { className: "curator-impact-thumb", src: `/scene/${entry.scene_id}/screenshot`, alt: "", loading: "lazy" }),
      React.createElement("div", { className: "curator-impact-scene-body" },
        React.createElement("div", { className: "curator-impact-scene-title" }, entry.title || `Scene ${entry.scene_id}`),
        React.createElement("div", { className: "curator-impact-scene-meta" }, [entry.studio, entry.date].filter(Boolean).join(" · ")),
        why && React.createElement("div", { className: "curator-impact-scene-why" }, "Because: ", why)
      ),
      React.createElement("span", { className: `curator-impact-delta ${entry.delta >= 0 ? "up" : "down"}` }, fmtDelta(entry.delta))
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

  function ImpactReport({ impact }) {
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
      React.createElement(
        "div",
        { className: "curator-impact-groups" },
        React.createElement(
          "div",
          { className: "curator-impact-group" },
          React.createElement("div", { className: "curator-impact-group-label" }, "Scenes"),
            impact.scenes.promoted.length === 0 && impact.scenes.demoted.length === 0 && React.createElement("p", { className: "curator-impact-weak" }, "No scene moves came from your feedback this build — new picks since the previous build will show up here."),
          React.createElement("div", { className: "curator-impact-columns" },
            React.createElement(ImpactList, { title: "Promoted", entries: impact.scenes.promoted, renderer: (entry) => React.createElement(ImpactSceneCard, { key: entry.scene_id, entry }), tone: "up" }),
            React.createElement(ImpactList, { title: "Demoted", entries: impact.scenes.demoted, renderer: (entry) => React.createElement(ImpactSceneCard, { key: entry.scene_id, entry }), tone: "down" })
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

  function CurateNudge({ onOpen, onDismiss }) {
    return React.createElement(
      "div",
      { className: "curator-curate-nudge" },
      React.createElement(FontAwesomeIcon, { icon: faBullseye, className: "curator-curate-nudge-icon" }),
      React.createElement("div", { className: "curator-curate-nudge-body" },
        React.createElement("strong", null, "Teach the model what you like"),
        React.createElement("p", null, "Compare scenes in pairs — each pick sharpens the model for all tags, performers, and studios, and you get a report of what your picks moved.")
      ),
      React.createElement(Button, { size: "sm", variant: "primary", onClick: onOpen }, "Open Curate"),
      React.createElement("button", { type: "button", className: "curator-curate-nudge-dismiss", onClick: onDismiss, title: "Don't show this again", "aria-label": "Dismiss" }, React.createElement(FontAwesomeIcon, { icon: faXmark }))
    );
  }

  function CuratePanel() {
    const restoredPicks = React.useRef(readPicksState()).current;
    const [picksRound, setPicksRound] = React.useState(restoredPicks ? restoredPicks.round : null);
    const [picksAnswers, setPicksAnswers] = React.useState(restoredPicks ? restoredPicks.answers : {});
    const [picksVerdict, setPicksVerdict] = React.useState(null);
    const [picksImpact, setPicksImpact] = React.useState(null);
    const [picksError, setPicksError] = React.useState("");
    const [picksBusy, setPicksBusy] = React.useState(false);
    const [flash, setFlash] = React.useState(null); // {pairId, winner} while the outline shows
    const [picksUndo, setPicksUndo] = React.useState([]); // [{pairId, winner}] for Forward
    const FLASH_MS = 500;
    const [curateTab, setCurateTab] = React.useState("pick");
    const [tags, setTags] = React.useState(null);
    const [suggestions, setSuggestions] = React.useState(null);
    const [suggestionError, setSuggestionError] = React.useState("");
    useCuratorActivity("curate", !tags && !picksError, "Loading curation tools…");
    React.useEffect(() => {
      let active = true;
      operation({ operation: "get_taste_profile" }).then(
        (value) => {
          if (active) {
            setTags(value.items);
            loadSuggestions(value.items);
          }
        },
        (failure) => active && setPicksError(failure.message)
      );
      return () => { active = false; };
    }, []);
    async function loadSuggestions(profileItems) {
      const items = profileItems || tags || [];
      const ratedLow = items
        .filter((item) =>
          (item.direct_value !== null && item.direct_value < 0)
          || (item.direct_value === null && Number(item.inferred_value) < -0.05)
        )
        .sort((a, b) => Number(b.scene_count) - Number(a.scene_count))
        .slice(0, 5);
      if (!ratedLow.length) {
        setSuggestions([]);
        return;
      }
      setSuggestionError("");
      const results = await Promise.all(ratedLow.map((tag) =>
        operation({ operation: "get_tag_context_candidates", tag_id: tag.tag_id, min_support: 20 })
          .then((value) => value.items.map((item) => ({
            base_tag_id: tag.tag_id,
            base_name: tag.name,
            context_tag_id: item.tag_id,
            context_name: item.name,
            cooccurrence: item.cooccurrence,
            contrast: item.contrast,
          })))
          .catch(() => [])
      ));
      const flat = results.flat();
      flat.sort((a, b) =>
        (a.contrast === null ? 1 : 0) - (b.contrast === null ? 1 : 0)
        || (b.contrast ?? -Infinity) - (a.contrast ?? -Infinity)
        || (b.cooccurrence - a.cooccurrence)
      );
      const MAX_SUGGESTIONS_PER_BASE = 3;
      const perBase = {};
      const capped = [];
      for (const suggestion of flat) {
        const key = suggestion.base_tag_id;
        if ((perBase[key] || 0) >= MAX_SUGGESTIONS_PER_BASE) {
          continue;
        }
        perBase[key] = (perBase[key] || 0) + 1;
        capped.push(suggestion);
        if (capped.length >= 8) {
          break;
        }
      }
      setSuggestions(capped);
    }
    function generatePicks(dimension, baseTag, contextTag) {
      setPicksBusy(true);
      setPicksError("");
      operation({
        operation: "get_curation_picks",
        dimension,
        budget: 10,
        base_tag_id: baseTag,
        context_tag_id: contextTag,
      }).then(
        (value) => {
          setPicksRound(value);
          setPicksAnswers({});
          setPicksVerdict(null);
          setPicksBusy(false);
        },
        (failure) => { setPicksError(failure.message); setPicksBusy(false); }
      );
    }
    function answerPicks(pairId, winner) {
      if (flash) {
        return; // input is locked while the selection outline shows
      }
      setPicksUndo([]);
      setFlash({ pairId, winner });
    }
    function backPicks() {
      if (flash || !picksRound) {
        return;
      }
      const answeredCount = Object.keys(picksAnswers).length;
      if (answeredCount === 0) {
        return;
      }
      const lastPairId = picksRound.pairs[answeredCount - 1].pair_id;
      const winner = picksAnswers[lastPairId];
      setPicksAnswers((current) => {
        const next = { ...current };
        delete next[lastPairId];
        return next;
      });
      setPicksUndo((current) => [...current, { pairId: lastPairId, winner }]);
    }
    function forwardPicks() {
      if (flash || picksUndo.length === 0) {
        return;
      }
      const entry = picksUndo[picksUndo.length - 1];
      setPicksUndo((current) => current.slice(0, -1));
      setPicksAnswers((current) => ({ ...current, [entry.pairId]: entry.winner }));
    }
    React.useEffect(() => {
      if (!flash) {
        return;
      }
      const timer = setTimeout(() => {
        const pairId = flash.pairId;
        const winner = flash.winner;
        setFlash(null);
        setPicksAnswers((current) => ({ ...current, [pairId]: winner }));
      }, FLASH_MS);
      return () => clearTimeout(timer);
    }, [flash]);
    React.useEffect(() => {
      if (picksRound) {
        writePicksState({ round: picksRound, answers: picksAnswers });
      }
    }, [picksRound, picksAnswers]);
    React.useEffect(() => {
      if (curateTab !== "pick" || !picksRound || picksVerdict || picksRound.pairs.length === 0) {
        return;
      }
      const answeredCount = Object.keys(picksAnswers).length;
      if (answeredCount >= picksRound.pairs.length) {
        return;
      }
      const pairId = picksRound.pairs[answeredCount].pair_id;
      function onKey(event) {
        if (flash) {
          return;
        }
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          answerPicks(pairId, "a");
        } else if (event.key === "ArrowRight") {
          event.preventDefault();
          answerPicks(pairId, "b");
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          answerPicks(pairId, "similar");
        } else if (event.key === "ArrowDown") {
          event.preventDefault();
          answerPicks(pairId, "skip");
        }
      }
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [curateTab, picksRound, picksVerdict, picksAnswers, flash]);
    async function submitPicks() {
      const entries = Object.entries(picksAnswers)
        .filter(([, winner]) => winner !== "similar")
        .map(([pairId, winner]) => {
          if (winner === "flag_a" || winner === "flag_b") {
            return { pair_id: pairId, winner: "flag", scene: winner === "flag_a" ? "a" : "b" };
          }
          return { pair_id: pairId, winner };
        });
      if (!entries.length) {
        setPicksError("Answer at least one comparison before submitting.");
        return;
      }
      setPicksBusy(true);
      setPicksError("");
      try {
        await operation({
          operation: "submit_curation_picks",
          round_id: picksRound.round_id,
          picks: entries,
        });
        const result = await operation({
          operation: "get_curation_pair_verdict",
          round_id: picksRound.round_id,
        });
        setPicksVerdict(result);
        bumpCurateRounds();
        try {
          const impact = await operation({ operation: "get_curation_impact" });
          setPicksImpact(impact);
        } catch (_) {
          // Impact is best-effort: it needs two model builds and their artifacts.
        }
      } catch (failure) {
        setPicksError(failure.message);
      } finally {
        setPicksBusy(false);
      }
    }
    function pickCellLabel(cell) {
      const base = picksRound && picksRound.base_tag && picksRound.base_tag.name;
      const context = picksRound && picksRound.context_tag && picksRound.context_tag.name;
      if (base && context) {
        const labels = {
          "L&T": `${base} + ${context}`,
          "L&!T": `${base} without ${context}`,
          "!L&T": `${context} without ${base}`,
          "neither": "Neither",
        };
        return labels[cell] || cell;
      }
      return cell;
    }
    function startRound() {
      clearPicksState();
      setPicksRound(null);
      setPicksAnswers({});
      setPicksVerdict(null);
      setFlash(null);
      setPicksUndo([]);
    }
    return React.createElement(
      "section",
      { className: "curator-curate", "aria-labelledby": "curator-curate-title" },
      React.createElement("h2", { id: "curator-curate-title" }, "Curate"),
      React.createElement("p", null, "Pick the scene you prefer in each pair — every choice teaches the model about all tags, performers, and studios the scenes carried."),
      React.createElement(
        "div",
        { className: "curator-curate-tabs", role: "tablist", "aria-label": "Curate views" },
        React.createElement(Button, { size: "sm", variant: curateTab === "pick" ? "primary" : "secondary", role: "tab", "aria-selected": curateTab === "pick", onClick: () => setCurateTab("pick") }, "Pick"),
        React.createElement(Button, { size: "sm", variant: curateTab === "tags" ? "primary" : "secondary", role: "tab", "aria-selected": curateTab === "tags", onClick: () => setCurateTab("tags") }, "Tag sentiment")
      ),
      curateTab === "tags" && React.createElement(TasteProfilePanel),
      curateTab === "pick" && !picksRound && React.createElement(
        "div",
        { className: "curator-curate-started" },
        React.createElement("h3", null, "Compare two scenes"),
        React.createElement("p", null, "Each pair varies one factor at a time — your pick tells the model which way you lean. No wrong answers; Skip when it feels like a coin flip."),
        picksError && React.createElement("div", { className: "alert alert-danger" }, picksError),
        React.createElement(
          "div",
          { className: "curator-curate-quick" },
          React.createElement(
            "div",
            { className: "curator-curate-quick-block" },
            React.createElement("strong", null, "Random round"),
            React.createElement(
              "div",
              { className: "curator-curate-suggestion" },
              React.createElement("span", { className: "curator-curate-suggestion-text" }, "10 random pairs", React.createElement("small", null, "Widest coverage across your library")),
              React.createElement(Button, { size: "sm", variant: "primary", disabled: picksBusy, onClick: () => generatePicks("orthogonal", "", "") }, "Generate")
            )
          ),
          React.createElement(
            "div",
            { className: "curator-curate-quick-block" },
            React.createElement("strong", null, "Pick-test a hypothesis"),
            suggestions && suggestions.length === 0 && React.createElement("small", null, "No hypotheses yet — the Tag sentiment tab and your rated scenes generate them."),
            (suggestions || []).map((suggestion) =>
              React.createElement(
                "div",
                { key: `pick-${suggestion.base_tag_id}:${suggestion.context_tag_id}`, className: "curator-curate-suggestion" },
                React.createElement("span", { className: "curator-curate-suggestion-text" }, `${suggestion.base_name} + ${suggestion.context_name}`),
                React.createElement(Button, { size: "sm", variant: "primary", disabled: picksBusy, onClick: () => generatePicks("tag", suggestion.base_tag_id, suggestion.context_tag_id) }, "Pick-test")
              )
            )
          )
        )
      ),
      curateTab === "pick" && picksRound && React.createElement(
        "div",
        { className: "curator-pick" },
        React.createElement(
          "div",
          { className: "curator-curate-batch-header" },
          React.createElement("strong", null, picksRound.dimension === "tag"
            ? `${(picksRound.base_tag && picksRound.base_tag.name) || "?"} + ${(picksRound.context_tag && picksRound.context_tag.name) || "?"}`
            : "Random round"),
          React.createElement("span", null, `${Object.keys(picksAnswers).length}/${picksRound.pairs.length} compared`),
          React.createElement(Button, { size: "sm", variant: "link", onClick: startRound }, "New round")
        ),
        picksError && React.createElement("div", { className: "alert alert-danger" }, picksError),
        picksVerdict && React.createElement(
          "div",
          { className: "curator-curate-verdict" },
          React.createElement("h3", null, picksVerdict.dimension === "tag" ? "Pick verdict" : "Round verdict"),
          React.createElement("p", { className: "curator-pick-verdict-summary" },
            `${picksVerdict.n_answered} comparisons · left ${Object.values(picksAnswers).filter((w) => w === "a").length} · right ${Object.values(picksAnswers).filter((w) => w === "b").length}`,
            picksVerdict.dimension === "orthogonal" && " · win rates for the tags that differed between scenes"
          ),
          picksVerdict.dimension === "tag" && (() => {
            const byCell = {};
            picksVerdict.cells.forEach((cell) => { byCell[cell.cell] = cell; });
            const withCtx = byCell["L&T"] || { wins: 0 };
            const withoutCtx = byCell["L&!T"] || { wins: 0 };
            const total = withCtx.wins + withoutCtx.wins;
            let headline;
            if (withCtx.wins > withoutCtx.wins) {
              headline = `You preferred ${pickCellLabel("L&T")} — ${withCtx.wins} to ${withoutCtx.wins} across ${total} comparisons.`;
            } else if (withoutCtx.wins > withCtx.wins) {
              headline = `You preferred ${pickCellLabel("L&!T")} — ${withoutCtx.wins} to ${withCtx.wins} across ${total} comparisons.`;
            } else {
              headline = `No clear preference — ${total} comparisons.`;
            }
            const rate = (wins) => (total > 0 ? wins / total : 0);
            return React.createElement(
              "div",
              null,
              React.createElement("p", { className: "curator-pick-verdict-headline" }, headline),
              React.createElement(
                "div",
                { className: "curator-pick-verdict-rows" },
                React.createElement(
                  "div",
                  { className: "curator-pick-verdict-row" },
                  React.createElement("span", { className: "curator-pick-verdict-row-label" }, pickCellLabel("L&T")),
                  React.createElement(
                    "div",
                    { className: "curator-pick-verdict-track" },
                    React.createElement("div", { className: "curator-pick-verdict-fill", style: { width: `${Math.round(rate(withCtx.wins) * 100)}%` } })
                  ),
                  React.createElement("span", { className: "curator-pick-verdict-count" }, withCtx.wins)
                ),
                React.createElement(
                  "div",
                  { className: "curator-pick-verdict-row" },
                  React.createElement("span", { className: "curator-pick-verdict-row-label" }, pickCellLabel("L&!T")),
                  React.createElement(
                    "div",
                    { className: "curator-pick-verdict-track" },
                    React.createElement("div", { className: "curator-pick-verdict-fill", style: { width: `${Math.round(rate(withoutCtx.wins) * 100)}%` } })
                  ),
                  React.createElement("span", { className: "curator-pick-verdict-count" }, withoutCtx.wins)
                )
              ),
              React.createElement("p", { className: "curator-pick-verdict-note" },
                "Pairs were matched to isolate this one relationship. Every pick also teaches the model about all tags, performers, and studios the scenes carried: shared features cancel, differing ones get the signal."
              )
            );
          })(),
          picksVerdict.dimension !== "tag" && (picksVerdict.items || []).length > 0 && (() => {
            const leftCount = Object.values(picksAnswers).filter((w) => w === "a").length;
            const rightCount = Object.values(picksAnswers).filter((w) => w === "b").length;
            const answered = leftCount + rightCount;
            const lopsided = answered > 0 && Math.min(leftCount, rightCount) * 10 < answered * 3;
            const items = picksVerdict.items.slice().sort((a, b) =>
              b.win_rate - a.win_rate || b.appearances - a.appearances
            );
            return React.createElement(
              "div",
              null,
              React.createElement(
                "div",
                { className: "curator-pick-verdict-grid" },
                items.slice(0, 12).map((item) =>
                  React.createElement(CurationVerdictBar, { key: item.tag_id || item.name, label: item.name, rate: item.win_rate, wins: item.wins, appearances: item.appearances })
                )
              ),
              lopsided && React.createElement("p", { className: "curator-pick-verdict-note" },
                `Picks were one-sided (left ${leftCount} · right ${rightCount}) — win rates mostly reflect the side you favored, so tags can't be discriminated yet. Varied picks will separate them.`
              ),
              !lopsided && answered > 0 && React.createElement("p", { className: "curator-pick-verdict-note" },
                `Evenly split (left ${leftCount} · right ${rightCount}) — most tags won every comparison they appeared in, so these rates are still coarse. Keep comparing; each round sharpens them.`
              )
            );
          })(),
          picksVerdict.dimension !== "tag" && picksVerdict.items.length === 0 && React.createElement("p", null, "No tag had enough appearances to report yet."),
          picksImpact && picksImpact.available && React.createElement(ImpactReport, { impact: picksImpact })
        ),
        !picksVerdict && picksRound.pairs.length === 0 && React.createElement("p", null, "No candidate pairs above zero information — try a different dimension or rate more scenes first."),
        !picksVerdict && picksRound.pairs.length > 0 && (() => {
          const answeredCount = Object.keys(picksAnswers).length;
          const currentPair = answeredCount < picksRound.pairs.length ? picksRound.pairs[answeredCount] : null;
          const leftCount = Object.values(picksAnswers).filter((w) => w === "a").length;
          const rightCount = Object.values(picksAnswers).filter((w) => w === "b").length;
          if (!currentPair) {
            return React.createElement(
              "div",
              { className: "curator-pick-done" },
              React.createElement("p", null, `All ${picksRound.pairs.length} compared — left ${leftCount}, right ${rightCount}.`),
              React.createElement(
                "div",
                { className: "curator-pick-controls" },
                React.createElement(Button, { size: "sm", variant: "secondary", disabled: flash, onClick: backPicks, title: "Undo the last pick" }, "Back"),
                React.createElement(Button, { size: "sm", variant: "primary", disabled: picksBusy, onClick: submitPicks }, picksBusy ? "Submitting…" : "Submit picks")
              )
            );
          }
          const answer = picksAnswers[currentPair.pair_id];
          return React.createElement(
            "div",
            { className: "curator-pick-compare" },
            React.createElement("div", { className: "curator-pick-tally" }, `left ${leftCount} · right ${rightCount} · compared ${answeredCount}/${picksRound.pairs.length}`),
            React.createElement(
              "div",
              { className: "curator-pick-cards" },
              React.createElement(PickSceneCard, { meta: currentPair.scene_a, picked: answer === "a" || (flash && flash.pairId === currentPair.pair_id && flash.winner === "a"), onPick: () => answerPicks(currentPair.pair_id, "a"), onFlag: () => answerPicks(currentPair.pair_id, "flag_a") }),
              React.createElement("span", { className: "curator-pick-vs", "aria-hidden": "true" }, "vs"),
              React.createElement(PickSceneCard, { meta: currentPair.scene_b, picked: answer === "b" || (flash && flash.pairId === currentPair.pair_id && flash.winner === "b"), onPick: () => answerPicks(currentPair.pair_id, "b"), onFlag: () => answerPicks(currentPair.pair_id, "flag_b") })
            ),
            React.createElement(
              "div",
              { className: "curator-pick-controls" },
              React.createElement(
                "div",
                { className: "curator-pick-nav-group", role: "group", "aria-label": "Navigate picks" },
                React.createElement(Button, { size: "sm", variant: "secondary", disabled: answeredCount === 0 || flash, onClick: backPicks, title: "Undo the previous pick" }, "Back"),
                React.createElement(Button, { size: "sm", variant: "secondary", disabled: picksUndo.length === 0 || flash, onClick: forwardPicks, title: "Redo the undone pick" }, "Forward")
              ),
              React.createElement(
                "div",
                { className: "curator-pick-answer-group", role: "group", "aria-label": "Rate this comparison" },
                React.createElement(Button, { size: "sm", variant: "primary", onClick: () => answerPicks(currentPair.pair_id, "a") }, "← Left"),
                React.createElement(Button, { size: "sm", variant: "primary", onClick: () => answerPicks(currentPair.pair_id, "b") }, "Right →"),
                React.createElement(Button, { size: "sm", variant: "secondary", onClick: () => answerPicks(currentPair.pair_id, "similar") }, "Similar ↑"),
                React.createElement(Button, { size: "sm", variant: "secondary", onClick: () => answerPicks(currentPair.pair_id, "skip") }, "Skip ↓"),
                React.createElement("span", { className: "curator-pick-hint" }, "Keys: ", React.createElement("kbd", null, "←/→"), " pick · ", React.createElement("kbd", null, "↑"), " similar · ", React.createElement("kbd", null, "↓"), " skip")
              )
            )
          );
        })()
      )
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
          selected === tag.tag_id && React.createElement(TagSentimentControl, { tag, value: answers[tag.tag_id]?.value, blocked: answers[tag.tag_id]?.blocked, onChange: (value) => answer(tag, value) })
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

  function scoreBar(item) {
    const bd = item.details?.score_breakdown || {};
    const sim = bd.similarity || 0;
    const app = bd.appeal || 0;
    const mh = bd.multi_hop || 0;
    const total = sim + app + mh || 1;
    const pct = (v) => Math.round(v / total * 100);
    return React.createElement("div", { className: "curator-score-bar" },
      React.createElement("span", { className: "curator-score-bar-seg curator-score-sim", style: { width: pct(sim) + "%" }, title: `Similarity ${sim.toFixed(3)}` }),
      React.createElement("span", { className: "curator-score-bar-seg curator-score-app", style: { width: pct(app) + "%" }, title: `Appeal ${app.toFixed(3)}` }),
      mh > 0 && React.createElement("span", { className: "curator-score-bar-seg curator-score-mh", style: { width: pct(mh) + "%" }, title: `Multi-hop ${mh.toFixed(4)}` })
    );
  }

  // Shared "Why this?"/"Score · X" details shell, used by RecommendationCard,
  // ExternalCard, and SimilarityPanel's library-match grid. The shell (the
  // two <details>/<summary> elements) is genuinely identical across all
  // three; what goes inside each is not (RecommendationCard lazy-loads its
  // explanation on toggle and shows a ScoreNode tree, the other two are
  // static), so content stays fully caller-supplied via props rather than
  // forcing those shapes into a shared config.
  function EvidenceScore({ evidenceProps, evidenceContent, scoreSummary, scoreContent }) {
    return React.createElement(
      React.Fragment,
      null,
      evidenceContent !== null && React.createElement("details", { className: "curator-evidence", ...evidenceProps }, React.createElement("summary", null, "Why this?"), evidenceContent),
      React.createElement("details", { className: "curator-score" }, React.createElement("summary", null, `Score · ${scoreSummary}`), scoreContent)
    );
  }

  // The "external" action-set variant (StashDB/Whisparr/shortlist), sibling
  // to Feedback's "local" variant (thumbs up/down + More menu).
  function ExternalActions({ href, item, kind, copied, onCopy, onShortlist, tagsAvailable, tagsActive, tagLoading, onRateTags, onShowScenes, whisparrEnabled, canWhisparr, whisparr, onAddToWhisparr }) {
    return React.createElement(
      "div",
      { className: "curator-prune-actions" },
      React.createElement("a", { className: "btn btn-secondary btn-sm curator-icon-action", href, target: "_blank", rel: "noreferrer", title: "Open on StashDB", "aria-label": "Open on StashDB" }, React.createElement(FontAwesomeIcon, { icon: faExternalLinkAlt })),
      React.createElement(Button, { className: "curator-icon-action", size: "sm", title: copied ? "Copied" : "Copy StashDB ID", "aria-label": copied ? "Copied" : "Copy StashDB ID", onClick: onCopy }, React.createElement(FontAwesomeIcon, { icon: copied ? faCheckCircle : faCopy })),
      onShortlist && React.createElement(Button, { className: "curator-icon-action", size: "sm", variant: item.shortlisted ? "primary" : "secondary", title: item.shortlisted ? "Remove from shortlist" : "Add to shortlist", "aria-label": item.shortlisted ? "Remove from shortlist" : "Add to shortlist", onClick: () => onShortlist(item, kind) }, React.createElement(FontAwesomeIcon, { icon: faList })),
      kind === "scene" && React.createElement(Button, { className: "curator-icon-action", size: "sm", variant: tagsActive ? "primary" : "secondary", disabled: !tagsAvailable || tagLoading, title: "Rate tags & terms", "aria-label": "Rate tags & terms", onClick: onRateTags }, React.createElement(FontAwesomeIcon, { icon: faTag })),
      kind === "performer" && onShowScenes && React.createElement(Button, { className: "curator-icon-action", size: "sm", title: "Show this performer's scenes", "aria-label": "Show this performer's scenes", onClick: () => onShowScenes(item) }, React.createElement(FontAwesomeIcon, { icon: faFilm })),
      kind === "scene" && canWhisparr && React.createElement(Button, { className: "curator-icon-action curator-whisparr-action", size: "sm", variant: "primary", disabled: !whisparrEnabled || whisparr?.status === "adding" || whisparr?.status === "sent" || whisparr?.status === "already_exists", title: !whisparrEnabled ? "Configure Whisparr in plugin settings" : whisparr?.status === "error" ? "Retry sending to Whisparr" : "Send to Whisparr", "aria-label": !whisparrEnabled ? "Whisparr is not configured" : whisparr?.status === "error" ? "Retry sending to Whisparr" : "Send to Whisparr", onClick: onAddToWhisparr }, React.createElement("span", { className: "curator-whisparr-logo", "aria-hidden": "true" }, React.createElement("span", { className: "curator-whisparr-fallback" }, "W"), React.createElement("img", { src: WHISPARR_LOGO, alt: "", onError: (event) => event.currentTarget.remove() }))),
      whisparr && React.createElement("small", { className: `curator-whisparr-status ${whisparr.status === "error" ? "text-danger" : ""}`, role: "status" }, whisparr.message)
    );
  }

  const ExternalCard = Api.register.component("stash-curator.ExternalCard", function ExternalCard(props) {
    const { HoverPopover } = Api.components;
    const { item, kind, gender, onShortlist, onShowScenes, onWhisparr, whisparrEnabled } = transformComponentProps("stash-curator.ExternalCard", props);
    const [copied, setCopied] = React.useState(false);
    const [whisparr, setWhisparr] = React.useState(null);
    const [tagChoices, setTagChoices] = React.useState(null);
    const [termChoices, setTermChoices] = React.useState(null);
    const [tagLoading, setTagLoading] = React.useState(false);
    const [tagError, setTagError] = React.useState("");
    useCuratorActivity(`external-tags-${kind}-${item.id}`, tagLoading, "Matching local tags…");
    const payload = item.payload;
    if (!payload) return null;
    const image = payload.images?.find((value) => value.url)?.url;
    const href = `https://stashdb.org/${kind === "scene" ? "scenes" : "performers"}/${item.id}`;
    const title = payload.title || payload.name || item.id;
    const localProfile = payload.curator_local ? { to: `/${kind}s/${payload.curator_local.id}`, title: `Open local ${kind} profile` } : { href, target: "_blank", rel: "noreferrer" };
    const TitleLink = localProfile.to ? NavLink : "a";
    const cast = kind === "scene" ? (payload.performers || []).map((value) => value.performer) : [];
    const people = gender ? cast.filter((person) => person.gender === gender) : cast;
    const tags = kind === "scene" ? payload.tags || [] : [];
    function metadataPopover(id, icon, label, count, content) {
      if (!count) return null;
      return React.createElement(
        HoverPopover,
        { className: `curator-external-${id}-trigger`, enterDelay: 150, leaveDelay: 250, placement: "bottom", content: React.createElement("div", { className: `curator-external-popover-links curator-external-${id}-popover` }, content) },
        React.createElement(Button, { className: "minimal curator-external-popover-button", size: "sm", title: label, "aria-label": `${count} ${label.toLowerCase()}` }, React.createElement(FontAwesomeIcon, { icon }), React.createElement("span", null, count))
      );
    }
    const metadataControls = kind === "scene" && React.createElement(
      ButtonGroup,
      { className: "card-popovers" },
      metadataPopover("tags", faTag, "Tags", tags.length, tags.map((tag) => React.createElement("span", { key: tag.id, className: "tag-item tag-link badge badge-secondary" }, React.createElement("a", { href: `https://stashdb.org/tags/${tag.id}`, target: "_blank", rel: "noreferrer" }, tag.name)))),
      metadataPopover("performers", faUser, "Performers", cast.length, React.createElement(React.Fragment, null, people.map((person) => {
        const performerImage = person.images?.find((value) => value.url)?.url;
        const PersonLink = person.curator_local ? NavLink : "a";
        const link = person.curator_local ? { to: `/performers/${person.curator_local.id}`, title: "Open local performer profile" } : { href: `https://stashdb.org/performers/${person.id}`, target: "_blank", rel: "noreferrer", title: "Open StashDB performer profile" };
        return React.createElement("div", { key: person.id, className: "performer-tag-container row" }, React.createElement(PersonLink, { className: "performer-tag col m-auto zoom-2", ...link }, performerImage && React.createElement("img", { className: "image-thumbnail", src: performerImage, loading: "lazy", alt: person.name || "" })), React.createElement(PersonLink, { className: "tag-item tag-link badge badge-secondary d-block", ...link }, person.name));
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
    async function rateTags() {
      if (tagChoices !== null) {
        setTagChoices(null);
        setTermChoices(null);
        return;
      }
      setTagLoading(true);
      setTagError("");
      try {
        const [tagsResult, termsResult] = await Promise.all([
          operation({
            operation: "get_external_tag_choices",
            tags: tags.map((tag) => ({ id: tag.id, name: tag.name })),
          }),
          operation({ operation: "get_scene_description_tokens", scene_id: item.id }),
        ]);
        setTagChoices(tagsResult.items);
        setTermChoices(termsResult.items);
      } catch (failure) {
        setTagError(failure.message);
        setTagChoices([]);
        setTermChoices([]);
      } finally {
        setTagLoading(false);
      }
    }
    function answerTag(row, {value, blocked}) {
      submitTagPreference(row.tag_id, {value, blocked});
      setTagChoices((current) => current.map((item) => item.tag_id === row.tag_id ? { ...item, direct_value: value, direct_blocked: !!blocked } : item));
    }
    function answerTerm(row, {value, blocked}) {
      submitTermPreference(row.term, {value, blocked});
      setTermChoices((current) => current.map((item) => item.term === row.term ? { ...item, direct_value: value, direct_blocked: !!blocked } : item));
    }
    return React.createElement(
      "article",
      { className: `curator-card curator-external-card curator-external-${kind} grid-card ${kind}-card${payload.curator_local ? " curator-external-local" : ""}` },
      item.sources?.includes("wildcard") && React.createElement("span", { className: "curator-wildcard-badge", title: "Popularity wildcard: selected outside preference-derived seeds." }, "Wildcard"),
      payload.curator_local && React.createElement("span", { className: "curator-local-badge", title: "Already in your local library" }, "In library"),
      payload.curator_local_match?.type === "phash" && React.createElement("span", { className: "curator-phash-badge", title: "A local scene has the same exact PHash. This is strong matching evidence, not guaranteed identity." }, "Likely local · exact PHash"),
      React.createElement("div", { className: `curator-external-thumbnail thumbnail-section ${kind === "scene" ? "video-section" : ""}` }, React.createElement("a", { className: `${kind}-card-link`, href, target: "_blank", rel: "noreferrer" }, image && React.createElement("img", { className: `${kind}-card-image`, src: image, loading: "lazy", alt: "" })), kind === "scene" && payload.studio?.name && React.createElement("span", { className: "curator-external-studio-overlay" }, payload.studio.name)),
      React.createElement("div", { className: "card-section" }, React.createElement(TitleLink, localProfile, React.createElement("h5", { className: "card-section-title flex-aligned" }, title)), React.createElement("div", { className: kind === "scene" ? "scene-card__details" : "curator-external-details" }, React.createElement("span", null, payload.release_date || payload.birth_date || ""), metadataControls), kind === "scene" && payload.details && React.createElement("p", { className: "curator-card-description" }, payload.details)),
      React.createElement("div", { className: "curator-card-body" }, (() => { let scoreDetail; if (item.similarity === undefined) { scoreDetail = `Match ${item.score.toFixed(2)} · found via ${item.sources.join(", ")}`; } else { scoreDetail = `Similarity ${item.similarity.toFixed(2)}` + (item.appeal !== undefined ? ` · appeal ${item.appeal.toFixed(2)}` : ""); const mh = item.details && item.details.score_breakdown && item.details.score_breakdown.multi_hop; if (mh > 0) scoreDetail += " + multi-hop " + mh.toFixed(4); } return React.createElement("div", { className: "curator-card-details" }, React.createElement(EvidenceScore, { evidenceContent: payload.why?.length ? React.createElement("p", { className: "curator-explanation" }, payload.why.join(" · ")) : null, scoreSummary: item.score.toFixed(2), scoreContent: React.createElement(React.Fragment, null, scoreBar(item), React.createElement("p", null, scoreDetail)) })); })()),
      React.createElement(ExternalActions, { href, item, kind, copied, onCopy: async () => { try { await copyText(item.id); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch (_) { setCopied(false); } }, onShortlist, tagsAvailable: tags.length > 0, tagsActive: tagChoices !== null, tagLoading, onRateTags: rateTags, onShowScenes, whisparrEnabled, canWhisparr: Boolean(onWhisparr), whisparr, onAddToWhisparr: addToWhisparr }),
      kind === "scene" && tagChoices !== null && React.createElement("div", { className: "curator-external-tag-rating" }, React.createElement("div", { className: "curator-external-tag-rating-header" }, React.createElement("strong", null, "Rate tags & terms"), React.createElement(Button, { size: "sm", variant: "link", className: "curator-external-tag-rating-close", "aria-label": "Collapse matching local tag ratings", title: "Collapse matching local tag ratings", onClick: rateTags }, "Collapse")), tagLoading && React.createElement("small", { role: "status" }, "Matching local tags…"), tagError && React.createElement("small", { className: "text-danger", role: "status" }, tagError), !tagLoading && !tagError && React.createElement(React.Fragment, null, React.createElement(RatingSection, { title: "Matching local tags", rows: tagChoices.map((tag) => ({ key: tag.tag_id, tag_id: tag.tag_id, name: tag.name, direct_value: tag.direct_value, direct_blocked: tag.direct_blocked })), onAnswer: answerTag, emptyLabel: "No matching local tags." }), React.createElement(RatingSection, { title: "Description terms", rows: termChoices.map((term) => ({ key: term.term, term: term.term, name: term.term, direct_value: term.direct_value, direct_blocked: term.direct_blocked })), onAnswer: answerTerm, emptyLabel: "No description terms in the model." })))
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

  function Feedback({ item, onRemove, onThumbDown }) {
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
        if (feedbackType === "thumb_down" && onThumbDown) {
          const followUp = await operation({
            operation: "get_tag_sentiment_follow_up",
            scene_id: item.scene_id,
            limit: 3,
          }).catch(() => ({ scene_id: item.scene_id, items: [] }));
          onThumbDown(followUp);
        }
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

  const FEEDBACK_LABELS = {
    thumb_up: "Thumbs Up",
    thumb_down: "Thumbs Down",
    not_now: "Not Now",
    never_show: "Never Show",
    metadata_wrong: "Metadata Wrong",
    prune: "Prune",
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
      "tr",
      null,
      React.createElement(
        "td",
        null,
        scene
          ? React.createElement(NavLink, { to: `/scenes/${item.scene_id}` }, scene.title || `Scene ${item.scene_id}`)
          : React.createElement("span", { className: "text-muted" }, "Scene removed from Stash")
      ),
      React.createElement("td", null, FEEDBACK_LABELS[item.feedback_type] || item.feedback_type),
      React.createElement("td", null, new Date(item.occurred_at_ms).toLocaleString()),
      React.createElement(
        "td",
        null,
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
              React.createElement(Button, { size: "sm", disabled: busy || !replacement, onClick: () => correct(replacement) }, "Save"),
              error && React.createElement("small", { className: "text-danger" }, error)
            )
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
      variables: { filter: { per_page: Math.max(1, ids.length) }, scene_filter: idFilter(ids) },
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
        { className: "table-responsive" },
        React.createElement(
          "table",
          { className: "table" },
          React.createElement("thead", null, React.createElement("tr", null, ["Scene", "Action", "Time", "Correction"].map((label) => React.createElement("th", { key: label, scope: "col" }, label)))),
          React.createElement("tbody", null, data.items.map((item) => React.createElement(FeedbackHistoryRow, { key: item.feedback_id, item, scene: scenes.get(String(item.scene_id)), onCorrect: () => setVersion((value) => value + 1) })))
        )
      ),
      data && React.createElement(Pager, { page, total: data.total, pageSize: data.page_size, hasMore: page * data.page_size < data.total, loading, onPage: setPage, label: "Feedback history pages" })
    );
  }

  function RecommendationCard({ item, scene, slate, onRemove, onThumbDown }) {
    const { SceneCard } = Api.components;
    const card = React.useRef(null);
    const [explanation, setExplanation] = React.useState(
      item.explanation
        ? { summary: item.explanation, supporting_reasons: item.supporting_reasons || [] }
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
      scene?.details && React.createElement("p", { className: "curator-card-description curator-card-description-local" }, scene.details),
      React.createElement(
        "div",
        { className: "curator-card-body" },
        scene && React.createElement(LocalRatingPanel, { sceneId: item.scene_id }),
        React.createElement(
          "div",
          { className: "curator-card-details" },
          React.createElement(EvidenceScore, {
            evidenceProps: { onToggle: explain },
            evidenceContent: React.createElement(
              React.Fragment,
              null,
              explanationLoading && React.createElement("small", { role: "status" }, "Explaining…"),
              explanationError && React.createElement("small", { className: "text-danger", role: "alert" }, explanationError),
              explanation && React.createElement("p", { className: "curator-explanation" }, explanation.summary),
              explanation && React.createElement(
                "ul",
                null,
                explanation.supporting_reasons.map((reason, index) =>
                  React.createElement(
                    "li",
                    { key: `${reason.code}-${index}` },
                    `${reasonLabel(reason.code)} (${reason.magnitude.toFixed(2)})`
                  )
                )
              )
            ),
            scoreSummary: item.final_utility.toFixed(2),
            scoreContent: React.createElement(
              React.Fragment,
              null,
              React.createElement(ScoreNode, { name: "appeal", value: item.appeal }),
              React.createElement(ScoreNode, { name: "current_fit", value: item.current_fit }),
              React.createElement(ScoreNode, { name: "confidence", value: item.confidence }),
              React.createElement(ScoreNode, { name: "components", value: item.components }),
              React.createElement(ScoreNode, { name: "diversity_penalties", value: item.penalties }),
              React.createElement(ScoreNode, { name: "diversity_bonuses", value: item.bonuses })
            ),
          }),
          React.createElement(Feedback, { item, onRemove, onThumbDown })
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
      React.createElement("td", null, laneByValue.get(item.lane)?.label || item.lane),
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
      variables: { filter: { per_page: Math.max(1, ids.length) }, scene_filter: idFilter(ids) },
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

  function FilterTokens({ kind, label, values, onChange, disabled = false }) {
    const [query, setQuery] = React.useState("");
    const variables = { filter: { q: query, per_page: 8 } };
    const tags = GQL.useFindTagsQuery({ variables, skip: kind !== "tag" || !query || disabled });
    const studios = GQL.useFindStudiosQuery({ variables, skip: kind !== "studio" || !query || disabled });
    const performers = GQL.useFindPerformersQuery({ variables, skip: kind !== "performer" || !query || disabled });
    const options = kind === "tag"
      ? tags.data?.findTags?.tags || []
      : kind === "studio"
        ? studios.data?.findStudios?.studios || []
        : performers.data?.findPerformers?.performers || [];
    function add(item) {
      if (!values.some((value) => String(value.id) === String(item.id))) onChange([...values, item]);
      setQuery("");
    }
    return React.createElement(
      "label",
      { className: "curator-token-filter" },
      React.createElement("span", null, label),
      React.createElement("div", { className: "curator-token-input" }, values.map((item) => React.createElement("button", { key: item.id, type: "button", title: `Remove ${item.name}`, onClick: () => onChange(values.filter((value) => value.id !== item.id)) }, item.name, " ×")), disabled ? null : React.createElement("input", { value: query, onChange: (event) => setQuery(event.target.value), placeholder: values.length ? "Add…" : `Search ${label.toLowerCase()}…` })),
      query && options.length > 0 && React.createElement("div", { className: "curator-token-options" }, options.map((item) => React.createElement("button", { key: item.id, type: "button", onClick: () => add(item) }, item.name)))
    );
  }

  function SavedFilters({ scope, current, onApply }) {
    const [saved, setSaved] = React.useState(() => readFilterPresets()[scope] || {});
    const [name, setName] = React.useState("");
    const [makeDefault, setMakeDefault] = React.useState(false);
    function save() {
      const clean = name.trim();
      if (!clean) return;
      const all = readFilterPresets();
      const next = { presets: { ...(all[scope]?.presets || {}), [clean]: current }, default: makeDefault ? clean : all[scope]?.default };
      all[scope] = next;
      localStorage.setItem(FILTER_PRESETS_KEY, JSON.stringify(all));
      setSaved(next);
      setName("");
    }
    return React.createElement(
      "div",
      { className: "curator-saved-filters" },
      React.createElement("select", { value: "", onChange: (event) => { const value = saved.presets?.[event.target.value]; if (value) onApply(value); }, "aria-label": "Load saved filter" }, React.createElement("option", { value: "" }, "Saved filters…"), Object.keys(saved.presets || {}).sort().map((value) => React.createElement("option", { key: value, value }, `${value}${saved.default === value ? " · default" : ""}`))),
      React.createElement("input", { value: name, onChange: (event) => setName(event.target.value), placeholder: "Filter name", "aria-label": "Filter name" }),
      React.createElement("label", null, React.createElement("input", { type: "checkbox", checked: makeDefault, onChange: (event) => setMakeDefault(event.target.checked) }), " Default"),
      React.createElement(Button, { size: "sm", disabled: !name.trim(), onClick: save }, "Save")
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
    includeTags, onIncludeTagsChange,
    excludeTags, onExcludeTagsChange,
    performers, onPerformersChange,
    studios, onStudiosChange,
    favoriteOnly, onToggleFavorite,
    hidePhashMatches, onToggleHidePhash,
    gender, onGenderChange,
    minimum, onMinimumChange,
    savedCurrent, onApplySaved,
    applyVisible = true, onApply,
  }) {
    const sceneGated = variant !== "hunt";
    const showScene = !sceneGated || entityType === "scene";
    const minimumMin = variant === "expand" ? "-0.2" : "0";
    const genderAriaLabel = variant === "expand" ? "External performer gender" : "Performer gender";
    const favoriteExtra = variant === "expand" ? { title: "Show only scenes containing a performer favorited in your local library", "aria-pressed": favoriteOnly } : {};
    return React.createElement(
      "div",
      { className: "curator-filter-panel-body curator-filter-panel" },
      React.createElement(
        "div",
        null,
        showScene && React.createElement(FilterTokens, { kind: "tag", label: "Include tags", values: includeTags, onChange: onIncludeTagsChange }),
        showScene && React.createElement(FilterTokens, { kind: "tag", label: "Exclude tags", values: excludeTags, onChange: onExcludeTagsChange }),
        sceneGated && showScene && React.createElement(FilterTokens, { kind: "performer", label: "Performers", values: performers, onChange: onPerformersChange }),
        sceneGated && showScene && React.createElement(FilterTokens, { kind: "studio", label: "Studios", values: studios, onChange: onStudiosChange }),
        sceneGated && showScene && React.createElement(Button, { size: "sm", variant: favoriteOnly ? "primary" : "secondary", ...favoriteExtra, onClick: onToggleFavorite }, React.createElement(FontAwesomeIcon, { icon: faHeart }), " Favorites"),
        showScene && React.createElement(Button, { size: "sm", variant: hidePhashMatches ? "primary" : "secondary", "aria-pressed": hidePhashMatches, title: "Hide remote scenes when a local file has the same exact PHash", onClick: onToggleHidePhash }, React.createElement(FontAwesomeIcon, { icon: faClone }), " Hide exact PHash matches"),
        sceneGated && React.createElement("label", { className: "curator-toolbar-select", title: "Limit results by performer gender" }, React.createElement(FontAwesomeIcon, { icon: faVenus }), React.createElement("select", { value: gender, onChange: onGenderChange, "aria-label": genderAriaLabel }, React.createElement("option", { value: "FEMALE" }, "Female"), React.createElement("option", { value: "MALE" }, "Male"), React.createElement("option", { value: "TRANSGENDER_FEMALE" }, "Trans female"), React.createElement("option", { value: "TRANSGENDER_MALE" }, "Trans male"), React.createElement("option", { value: "" }, "All genders"))),
        sceneGated && showScene && React.createElement("label", { className: "curator-match-filter" }, React.createElement("span", null, `Minimum match ${minimum.toFixed(2)}`), React.createElement("input", { type: "range", min: minimumMin, max: "0.8", step: "0.05", value: minimum, onChange: onMinimumChange })),
        (sceneGated ? showScene : true) && React.createElement(SavedFilters, { scope: variant, current: savedCurrent, onApply: onApplySaved }),
        applyVisible && React.createElement(Button, { size: "sm", variant: "primary", onClick: onApply }, "Apply")
      )
    );
  }

  function SimilarityPanel() {
    const { SceneCard, PerformerCard } = Api.components;
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
    const codeVersionRef = React.useRef("");
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
    const ids = source === "library" ? items.map((item) => item.entity_id) : [];
    const similarScenes = GQL.useFindScenesQuery({
      variables: { filter: { per_page: Math.max(1, ids.length) }, scene_filter: idFilter(ids) },
      skip: entityType !== "scene" || ids.length === 0,
    });
    const similarPerformers = GQL.useFindPerformersQuery({
      variables: { filter: { per_page: Math.max(1, ids.length) }, performer_filter: performerNameFilter(items) },
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
    const sourceScene = GQL.useFindSceneQuery({ variables: { id: selected?.id || "0" }, skip: entityType !== "scene" || !selected });
    const sourcePerformer = GQL.useFindPerformerQuery({ variables: { id: selected?.id || "0" }, skip: entityType !== "performer" || !selected });
    const sourceEntity = entityType === "scene" ? sourceScene.data?.findScene : sourcePerformer.data?.findPerformer;

    // The fetch effect is the single driver for similarity requests: it runs
    // whenever the URL-backed selection/source/page/exclusions change (including
    // back/forward restores) and reads current filter values through
    // filterStateRef, so filters stay lazy (applied on the next fetch) exactly
    // as before.
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
        setResult((current) => ({ ...current, items: current.items.map((value) => value.id === item.id ? { ...value, shortlisted: !item.shortlisted } : value) }));
      } catch (failure) { setError(failure.message); }
    }
    const sendWhisparr = (id) => operation({ operation: "send_whisparr", external_id: id });
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
    const activeFilterCount = (includeTags?.length || 0) + (excludeTags?.length || 0) + (filterPerformers?.length || 0) + (filterStudios?.length || 0) + (favoriteOnly ? 1 : 0) + (hidePhashMatches ? 1 : 0);
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
        React.createElement("div", { className: "btn-group curator-similar-source-tabs", role: "group", "aria-label": "Similarity source" }, [["library", "Library", faDatabase], ["stashdb", "StashDB", faCompass]].map(([value, label, icon]) => React.createElement(Button, { key: value, size: "sm", variant: source === value ? "primary" : "secondary", onClick: () => switchSource(value) }, React.createElement(FontAwesomeIcon, { icon }), ` ${label}`))),
        React.createElement(
          "form",
          { onSubmit: (event) => (event.preventDefault(), updateUrl((s) => ({ ...s, selected: null })), setResult(null), setSearch(query.trim())) },
          React.createElement("input", { className: "form-control form-control-sm", value: query, onChange: (event) => setQuery(event.target.value), placeholder: `Search for a ${entityType}…`, "aria-label": `Search for a ${entityType}` }),
          React.createElement(Button, { size: "sm", type: "submit", disabled: !query.trim() }, "Search")
        ),
        source === "stashdb" && React.createElement(Button, { className: "curator-include-owned", size: "sm", variant: includeOwned ? "primary" : "secondary", "aria-pressed": includeOwned, title: `Include ${entityType}s already in your library so the remote ranking can be compared with the local search`, "aria-label": includeOwned ? `Hide library ${entityType}s` : `Include library ${entityType}s`, onClick: () => updateUrl((s) => ({ ...s, includeOwned: !s.includeOwned, page: 1, excludedIds: [] })) }, React.createElement(FontAwesomeIcon, { icon: faUserCheck }), " Local"),
        React.createElement(Button, { size: "sm", variant: filtersOpen ? "primary" : "secondary", "aria-expanded": filtersOpen, onClick: () => setFiltersOpen((value) => !value) }, React.createElement(FontAwesomeIcon, { icon: faFilter }), " Filters", activeFilterCount > 0 && React.createElement("span", { className: "curator-filter-count" }, activeFilterCount))
      ),
      filtersOpen && React.createElement(FilterBar, {
        variant: "similar",
        entityType,
        includeTags, onIncludeTagsChange: (value) => updateUrl((s) => ({ ...s, includeTags: value })),
        excludeTags, onExcludeTagsChange: (value) => updateUrl((s) => ({ ...s, excludeTags: value })),
        performers: filterPerformers, onPerformersChange: (value) => updateUrl((s) => ({ ...s, filterPerformers: value })),
        studios: filterStudios, onStudiosChange: (value) => updateUrl((s) => ({ ...s, filterStudios: value })),
        favoriteOnly, onToggleFavorite: () => updateUrl((s) => ({ ...s, favoriteOnly: !s.favoriteOnly })),
        hidePhashMatches, onToggleHidePhash: () => updateUrl((s) => ({ ...s, hidePhashMatches: !s.hidePhashMatches })),
        gender, onGenderChange: (event) => updateUrl((s) => ({ ...s, gender: event.target.value })),
        minimum: minimumSimilarity, onMinimumChange: (event) => updateUrl((s) => ({ ...s, minimumSimilarity: Number(event.target.value) })),
        savedCurrent: { gender, favoriteOnly, hidePhashMatches, includeTags, excludeTags, performers: filterPerformers, studios: filterStudios, minimum: minimumSimilarity },
        onApplySaved: applySaved,
        applyVisible: Boolean(selected),
        onApply: () => updateUrl((s) => ({ ...s, excludedIds: [], page: 1, fetchTick: s.fetchTick + 1 })),
      }),
      search && !selected && React.createElement(
        "div",
        { className: "curator-similar-candidates" },
        candidates.map((entity) => React.createElement(Button, { key: entity.id, variant: "link", onClick: () => choose(entity) }, entity.title || entity.name || `#${entity.id}`)),
        !sceneSearch.loading && !performerSearch.loading && candidates.length === 0 && React.createElement("p", null, "No matches found.")
      ),
      selected && React.createElement("div", { className: "curator-similar-reference" }, React.createElement("strong", null, "Comparing from"), React.createElement(SourceReference, { entity: sourceEntity, type: entityType, fallback: selected })),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Finding close matches…")),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      followUps.map((followUp) => React.createElement(TagSentimentFollowUp, { key: followUp.scene_id, followUp, onDismiss: () => setFollowUps((current) => current.filter((item) => item.scene_id !== followUp.scene_id)) })),
      result && source === "library" && React.createElement(
        "div",
        { className: "curator-grid" },
        items.map((item) => {
          const entity = entities.get(String(item.entity_id));
          if (!entity) return null;
          const body = React.createElement("div", { className: "curator-card-body" }, entityType === "scene" && React.createElement(LocalRatingPanel, { sceneId: item.entity_id }), React.createElement("div", { className: "curator-card-details" }, React.createElement(EvidenceScore, { evidenceContent: React.createElement("p", { className: "curator-explanation" }, relationshipChips(item)), scoreSummary: item.rank_score.toFixed(2), scoreContent: React.createElement(React.Fragment, null, scoreBar(item), React.createElement("p", null, `Similarity ${item.similarity.toFixed(2)} · predicted appeal ${item.appeal.toFixed(2)}`)) })));
          if (entityType === "performer") return React.createElement("article", { key: item.entity_id, className: "curator-card" }, React.createElement(PerformerCard, { performer: entity }), body);
          const feedbackItem = { ...item, scene_id: item.entity_id, impression_id: result.impression_id };
          function rememberOrigin(event) {
            if (!event.target.closest("a")) return;
            sessionStorage.setItem(ORIGIN_KEY, JSON.stringify({ scene_id: item.entity_id, impression_id: result.impression_id, lane: "similar", impression_position: item.position, model_id: result.model_id }));
          }
          return React.createElement("article", { key: item.entity_id, className: "curator-card", onClickCapture: rememberOrigin }, React.createElement(SceneCard, { scene: entity }), entity.details && React.createElement("p", { className: "curator-card-description curator-card-description-local" }, entity.details), body, React.createElement("div", { className: "curator-similar-feedback" }, React.createElement(Feedback, { item: feedbackItem, onRemove: removeSimilar, onThumbDown: showFollowUp })));
        })
      ),
      result && source === "stashdb" && React.createElement(
        "div",
        { className: "curator-grid curator-external-grid" },
        items.map((item) => React.createElement(ExternalCard, { key: item.id, item, kind: entityType, gender, onShortlist: shortlistExternal, onShowScenes: (item) => location.assign(`/plugins/stash-curator?view=hunt&performer=${item.id}&label=${encodeURIComponent(item.payload?.name || "")}`), onWhisparr: sendWhisparr, whisparrEnabled }))
      ),
      result && React.createElement(Pager, { page, total: source === "stashdb" ? externalItems.length : result.total, pageSize: source === "stashdb" ? pageSize : result.page_size, hasMore: source === "stashdb" ? page * pageSize < externalItems.length : result.has_more, loading, onPage: changePage, label: "Similar pages" })
    );
  }

  function PrunePanel() {
    const { SceneCard } = Api.components;
    const pruneSpec = React.useMemo(() => ({
      defaults: { view: "candidates", aggressiveness: 0, page: 1 },
      fields: {
        view: urlStringField("prn_view", "candidates", (value) => ["candidates", "tagged", "explicit", "suspects"].includes(value)),
        aggressiveness: urlNumberField("prn_aggr", 0),
      },
      page: urlPageSpec((state) => `page_prune_${state.view}`),
      prune(route, state) {
        for (const value of ["candidates", "tagged", "explicit", "suspects"]) {
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
          [["candidates", "Candidates"], ["tagged", "Tagged"], ["explicit", "Explicit dislikes"], ["suspects", "Model suspects"]].map(([value, label]) => React.createElement(Button, { key: value, size: "sm", variant: view === value ? "primary" : "secondary", onClick: () => updateUrl((s) => ({ ...s, view: value, page: 1 })) }, label))
        ),
        view !== "tagged" && React.createElement("label", { className: "curator-prune-aggressiveness", title: "Move right to include less certain predicted dislikes." }, React.createElement("span", null, aggressiveness < 0.34 ? "Conservative" : aggressiveness < 0.67 ? "Balanced" : "Aggressive"), React.createElement("input", { type: "range", min: 0, max: 1, step: 0.05, value: aggressiveness, onChange: (event) => updateUrl((s) => ({ ...s, aggressiveness: Number(event.target.value), page: 1 })), "aria-label": "Prune prediction aggressiveness" })),
        view !== "tagged" && React.createElement(Button, { size: "sm", variant: "danger", disabled: !ids.length, onClick: tagPage }, `Tag visible (${ids.length})`)
      ),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Reviewing prune evidence…")),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      data && !loading && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, view === "suspects" ? "No scenes cross this prediction threshold. Direct dislikes appear under Explicit dislikes; suspects need a rebuilt model with enough repeated negative evidence." : "Nothing in this view."),
      data && React.createElement(
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
            React.createElement("div", { className: "curator-card-body" }, React.createElement("p", { className: "curator-similarity-reason" }, item.evidence.join(" · ")), item.appeal !== null && React.createElement("small", null, `Appeal ${item.appeal.toFixed(2)} · confidence ${item.confidence.toFixed(2)}`)),
            React.createElement("div", { className: "curator-prune-actions" }, React.createElement(Button, { size: "sm", variant: item.tagged ? "secondary" : "danger", onClick: () => tag([item.scene_id], !item.tagged) }, item.tagged ? `Undo ${data.tag_name}` : `Tag ${data.tag_name}`), !item.tagged && item.suspect && !item.explicit && React.createElement(Button, { size: "sm", variant: "link", onClick: () => dismiss(item.scene_id) }, "Dismiss"))
          );
        })
      ),
      data && React.createElement(Pager, { page, total: data.total, pageSize: data.page_size, hasMore: data.has_more, loading, onPage: (value) => updateUrl((s) => ({ ...s, page: value })), label: "Prune pages" })
    );
  }

  function ExpandPanel({ initialType = "scene", huntOnly = false }) {
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
            return id ? { id, name: search.get("label") || id, external: true } : null;
          },
          serialize: (value) => value ? { performer: String(value.id), label: value.name && value.name !== String(value.id) ? value.name : "" } : { performer: "", label: "" },
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
      operation(request, entityType === "hunt" ? 60000 : 30000).then(
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
      if (entityType === "hunt") {
        setVersion((value) => value + 1);
        return;
      }
      try {
        const id = await runTask("Refresh Expand cache");
        setMessage(`Started Stash job ${id}. Progress is available in Tasks.`);
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
    const activeFilterCount = (includeTags?.length || 0) + (excludeTags?.length || 0) + (performers?.length || 0) + (studios?.length || 0) + (favoriteOnly ? 1 : 0) + (hidePhashMatches ? 1 : 0);
    return React.createElement(
      "section",
      { className: huntOnly ? "curator-hunt" : "curator-expand" },
      React.createElement(
        "div",
        { className: "curator-expand-toolbar" },
        !huntOnly && React.createElement("div", { className: "btn-group", role: "group", "aria-label": "Explore external content" }, [["scene", "Scenes", faPlayCircle], ["performer", "Performers", faUser]].map(([value, label, icon]) => React.createElement(Button, { key: value, size: "sm", variant: entityType === value ? "primary" : "secondary", onClick: () => updateUrl((s) => ({ ...s, entityType: value, performerId: null })) }, React.createElement(FontAwesomeIcon, { icon }), ` ${label}`))),
        !huntOnly && React.createElement(Button, { className: "curator-shortlist-tab", size: "sm", variant: entityType === "shortlist" ? "primary" : "secondary", onClick: () => updateUrl((s) => ({ ...s, entityType: "shortlist", performerId: null })) }, React.createElement(FontAwesomeIcon, { icon: faList }), " Shortlist"),
        entityType === "scene" && React.createElement("label", { className: "curator-toolbar-select" }, React.createElement(FontAwesomeIcon, { icon: faSortAmountDown }), React.createElement("select", { value: sort, onChange: (event) => updateUrl((s) => ({ ...s, page: 1, sort: event.target.value })), "aria-label": "Sort Expand results" }, React.createElement("option", { value: "match" }, "Best match"), React.createElement("option", { value: "newest" }, "Newest"))),
        entityType !== "shortlist" && React.createElement(Button, { size: "sm", variant: filtersOpen ? "primary" : "secondary", "aria-expanded": filtersOpen, onClick: () => setFiltersOpen((value) => !value) }, React.createElement(FontAwesomeIcon, { icon: faFilter }), " Filters", activeFilterCount > 0 && React.createElement("span", { className: "curator-filter-count" }, activeFilterCount)),
        performerId && React.createElement(Button, { size: "sm", variant: "link", onClick: () => updateUrl((s) => ({ ...s, page: 1, performerId: null })) }, "Clear performer filter"),
        React.createElement(Button, { className: "curator-icon-button", size: "sm", disabled: entityType === "hunt" && !huntPerformer, title: entityType === "hunt" ? "Refresh this performer's scenes directly from StashDB." : "Refresh the bounded StashDB candidate cache in a background task.", "aria-label": entityType === "hunt" ? "Refresh Performer Hunt" : "Refresh Expand cache", onClick: refresh }, React.createElement(FontAwesomeIcon, { icon: faSync })),
        data?.fetched_at_ms && React.createElement("small", null, `${Date.now() > data.expires_at_ms ? "Stale · " : ""}Updated ${new Date(data.fetched_at_ms).toLocaleString()}`)
      ),
      entityType === "hunt" && React.createElement(
        "div",
        { className: "curator-hunt-controls" },
        React.createElement(FilterTokens, { kind: "performer", label: huntPerformer?.external ? "External performer on StashDB" : "Local performer with a StashDB link", values: huntPerformer ? [huntPerformer] : [], onChange: selectHuntPerformer, disabled: Boolean(huntPerformer?.external) }),
        data?.ready && React.createElement("div", { className: "btn-group", role: "group", "aria-label": "Performer Hunt view" }, [["all", `All ${huntCounts.all}`], ["linked", `In library ${huntCounts.linked}`], ["unlinked", `Not linked locally ${huntCounts.unlinked}`]].map(([value, label]) => React.createElement(Button, { key: value, size: "sm", variant: huntView === value ? "primary" : "secondary", onClick: () => updateUrl((s) => ({ ...s, page: 1, huntView: value })) }, label))),
        data?.ready && React.createElement("label", { className: "curator-toolbar-select" }, React.createElement(FontAwesomeIcon, { icon: faSortAmountDown }), React.createElement("select", { value: huntSort, onChange: (event) => updateUrl((s) => ({ ...s, page: 1, huntSort: event.target.value })), "aria-label": "Sort Performer Hunt results" }, React.createElement("option", { value: "date" }, "Release date"), React.createElement("option", { value: "score" }, "Preference score")))
      ),
      entityType === "hunt" && data?.truncated && React.createElement("div", { className: "alert alert-warning" }, `Showing the first ${data.fetched_count.toLocaleString()} of ${data.stashdb_total.toLocaleString()} StashDB scenes; the safety cap is ${data.limit.toLocaleString()}. Counts below apply to the fetched scenes.`),
      entityType === "hunt" && filtersOpen && React.createElement(FilterBar, {
        variant: "hunt",
        entityType,
        includeTags, onIncludeTagsChange: (value) => updateUrl((s) => ({ ...s, includeTags: value })),
        excludeTags, onExcludeTagsChange: (value) => updateUrl((s) => ({ ...s, excludeTags: value })),
        hidePhashMatches, onToggleHidePhash: () => updateUrl((s) => ({ ...s, hidePhashMatches: !s.hidePhashMatches })),
        savedCurrent: { hidePhashMatches, includeTags, excludeTags },
        onApplySaved: (value) => updateUrl((s) => ({ ...s, page: 1, hidePhashMatches: value.hidePhashMatches !== false, includeTags: value.includeTags || [], excludeTags: value.excludeTags || [] })),
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
        savedCurrent: { gender, favoriteOnly, hidePhashMatches, includeTags, excludeTags, performers, studios, minimum: minimumScore },
        onApplySaved: applySaved,
        onApply: () => (updateUrl((s) => ({ ...s, page: 1 })), setFilterVersion((value) => value + 1)),
      }),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      message && React.createElement("p", { role: "status" }, message),
      entityType === "hunt" && !huntPerformer && React.createElement("div", { className: "alert alert-info" }, "Select a local performer linked to StashDB."),
      data && !data.ready && React.createElement("div", { className: "alert alert-info" }, React.createElement("p", null, "Expand has not been prepared yet — StashDB candidates need to be collected first."), React.createElement(Button, { size: "sm", variant: "primary", onClick: refresh }, React.createElement(FontAwesomeIcon, { icon: faSync }), " Prepare now")),
      data?.ready && visibleItems.length === 0 && React.createElement("div", { className: "alert alert-info" }, entityType === "hunt" ? "No scenes match this view." : "No external candidates match these filters."),
      data?.ready && React.createElement(
        "div",
        { className: "curator-grid curator-external-grid" },
        visibleItems.map((item) => {
          const kind = entityType === "shortlist" ? item.entity_type : entityType === "hunt" ? "scene" : entityType;
          return React.createElement(ExternalCard, { key: `${kind}-${item.id}`, item, kind, gender, onShortlist: shortlist, onShowScenes: showPerformerScenes, onWhisparr: sendWhisparr, whisparrEnabled });
        })
      ),
      data?.ready && React.createElement(Pager, { page, total: entityType === "hunt" ? huntItems.length : data.total, pageSize: entityType === "hunt" ? pageSize : data.page_size, hasMore: entityType === "hunt" ? huntHasMore : data.has_more, loading, onPage: (value) => updateUrl((s) => ({ ...s, page: value })), label: entityType === "hunt" ? "Performer Hunt pages" : entityType === "shortlist" ? "Shortlist pages" : "Expand pages" })
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
      data && React.createElement("p", null, `Backup directory: ${data.backup_directory}`),
      message && React.createElement("div", { className: "alert alert-success", role: "status" }, message),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      data && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No Curator backups found."),
      data && data.items.length > 0 && React.createElement(
        "div",
        { className: "table-responsive" },
        React.createElement(
          "table",
          { className: "table" },
          React.createElement("thead", null, React.createElement("tr", null, ["Created", "Size", "File", "Action"].map((label) => React.createElement("th", { key: label, scope: "col" }, label)))),
          React.createElement("tbody", null, data.items.map((item) => React.createElement(
            "tr",
            { key: item.id },
            React.createElement("td", null, new Date(item.created_at_ms).toLocaleString()),
            React.createElement("td", null, `${(item.size_bytes / 1048576).toFixed(1)} MB`),
            React.createElement("td", null, item.id),
            React.createElement("td", null, React.createElement(Button, { size: "sm", disabled: busy, onClick: () => restore(item) }, "Restore"), " ", React.createElement(Button, { size: "sm", variant: "danger", disabled: busy, onClick: () => remove(item) }, "Delete"))
          )))
        )
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
        React.createElement(Button, { size: "sm", onClick: loadPprof }, "Refresh"),
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
          React.createElement("td", null, React.createElement(Button, { size: "sm", onClick: () => viewPprof(item.name) }, "View"), " ", React.createElement(Button, { size: "sm", onClick: () => downloadPprof(item.name) }, React.createElement(FontAwesomeIcon, { icon: faDownload }), " Download")),
        ))),
      ),
      pprofView && React.createElement("div", { className: "curator-pprof-detail" },
        React.createElement("div", { className: "curator-profiling-toolbar" },
          React.createElement("h4", null, pprofView.name),
          flameRoot ? React.createElement(Button, { size: "sm", onClick: () => setFlameRoot(null) }, "Back to root") : null,
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
      React.createElement("div", { className: "curator-profiling-toolbar" }, React.createElement("h2", null, "Recent profiles"), React.createElement(Button, { size: "sm", onClick: load, disabled: loading }, "Refresh"), React.createElement(Button, { size: "sm", variant: "danger", onClick: clear, disabled: !profiles?.items?.length }, "Clear")),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, "Loading profiles…"),
      profiles && !loading && profiles.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No profiles have been recorded yet."),
      profiles?.items?.length > 0 && React.createElement("div", { className: "curator-profile-layout" },
        React.createElement("div", { className: "curator-profile-list", role: "list" }, profiles.items.map((item) => React.createElement("button", { key: item.trace_id, type: "button", className: selected?.trace_id === item.trace_id ? "active" : "", onClick: () => inspect(item.trace_id) }, React.createElement("strong", null, item.operation), React.createElement("span", null, `${item.kind} · ${formatDuration(item.duration_us)}`), React.createElement("small", null, `${new Date(item.started_at_ms).toLocaleString()} · ${item.status}${item.truncated ? " · truncated" : ""}`)))),
        selected && React.createElement("div", { className: "curator-profile-detail" },
          React.createElement("div", { className: "curator-profiling-toolbar" }, React.createElement("h2", null, selected.operation), React.createElement(Button, { size: "sm", onClick: exportTrace }, React.createElement(FontAwesomeIcon, { icon: faDownload }), " Export trace")),
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
        React.createElement(Button, { size: "sm", onClick: load }, "Refresh"),
        React.createElement(Button, { size: "sm", disabled: !report, onClick: copy }, React.createElement(FontAwesomeIcon, { icon: faCopy }), " Copy"),
        React.createElement(Button, { size: "sm", disabled: !report, onClick: download }, React.createElement(FontAwesomeIcon, { icon: faDownload }), " Download JSON")
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
    const stages = description.includes("sync")
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
                : description.includes("expand")
                  ? [[0.05, "Collecting StashDB candidates"], [0.98, "Finishing"]]
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
    "sync-build": "Sync and build recommendations",
    "full-sync-build": "Full sync and build recommendations",
    build: "Rebuild recommendation model",
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
  function CuratorTaskIndicator({ activeJobs, activities, failure, doneJob }) {
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
      { className: `curator-task-indicator curator-task-indicator-${state}`, to: "/settings?tab=tasks", title: `${label}. Open Tasks`, "aria-label": `${label}. Open Tasks` },
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

  function CuratorControls({ onRefresh, onProfiling, profilingActive, theme, onToggleTheme }) {
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
    React.useEffect(() => {
      refreshStatus();
    }, []);
    React.useEffect(() => {
      // One extra poll shortly after the last active job leaves Stash's queue
      // so the completed curator_job row (and its summary) is picked up.
      if (!health?.active_jobs?.length && !health?.active_job) {
        const timer = setTimeout(refreshStatus, 5000);
        return () => clearTimeout(timer);
      }
      const timer = setInterval(refreshStatus, 5000);
      return () => clearInterval(timer);
    }, [Boolean(health?.active_jobs?.length || health?.active_job)]);

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
        React.createElement("li", null, React.createElement(FontAwesomeIcon, { icon: health.stashdb_available ? faCheckCircle : faGlobe }), ` StashDB: ${health.stashdb_available ? "available" : "optional — not configured"}`)
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
    const healthTrigger = React.createElement(
      "button",
      { type: "button", className: "curator-health-pill", "aria-label": "Curator sync and task status" },
      React.createElement("span", { className: `curator-health-pulse curator-health-pulse-${running ? "running" : latestFailure ? "failed" : hasSynced ? "ready" : "idle"}` }),
      React.createElement("span", { className: "curator-health-pill-label" }, running ? "Running" : hasSynced ? "Synced" : "Not synced")
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
              React.createElement(CuratorTaskIndicator, { activeJobs, activities, failure: latestFailure, doneJob }),
              React.createElement("div", { className: "curator-health-row" }, React.createElement("span", null, "Model"), React.createElement("b", null, health?.model_pending ? `${health.model_pending_events} waiting` : modelStatus)),
              React.createElement("div", { className: "curator-health-row" }, React.createElement("span", null, "Playback sessions captured"), React.createElement("b", null, health?.capture?.direct_playback_sessions || 0)),
              health?.last_sync_at_ms && React.createElement("div", { className: "curator-health-row" }, React.createElement("span", null, "Last sync"), React.createElement("b", null, new Date(health.last_sync_at_ms).toLocaleString()))
            ),
          },
          healthTrigger
        )
      : healthTrigger;
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
          React.createElement(Button, { className: "curator-icon-button", size: "sm", title: "Use after Stash library changes. Sync changed metadata and history, then refresh recommendations.", "aria-label": "Sync library changes and refresh recommendations", onClick: () => start("Sync and build recommendations") }, React.createElement(FontAwesomeIcon, { icon: faSync })),
          React.createElement(Button, { className: "curator-icon-button", size: "sm", title: "Force a recommendation refresh from already-synced data. Does not contact Stash.", "aria-label": "Rebuild recommendations without syncing Stash", onClick: () => start("Rebuild recommendation model") }, React.createElement(FontAwesomeIcon, { icon: faWrench })),
          React.createElement(Button, { className: "curator-icon-button curator-profiling-button", size: "sm", variant: profilingActive ? "primary" : "secondary", title: "Open performance profiles.", "aria-label": "Open performance profiles", "aria-pressed": profilingActive, onClick: onProfiling }, React.createElement(FontAwesomeIcon, { icon: faDev })),
          React.createElement(Button, { className: "curator-icon-button", size: "sm", title: theme === "light" ? "Switch to dark theme" : "Switch to light theme", "aria-label": theme === "light" ? "Switch to dark theme" : "Switch to light theme", onClick: onToggleTheme }, React.createElement(FontAwesomeIcon, { icon: theme === "light" ? faMoon : faSun })),
          React.createElement(NavLink, { className: "btn btn-secondary btn-sm curator-icon-button", title: "Open Curator's plugin settings.", "aria-label": "Plugin settings", to: "/settings?tab=plugins" }, React.createElement(FontAwesomeIcon, { icon: faCog }))
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
    const ids = data?.items.map((item) => item.scene_id) || [];
    const scenesQuery = GQL.useFindScenesQuery({
      variables: { filter: { per_page: Math.max(1, ids.length) }, scene_filter: idFilter(ids) },
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
        React.createElement("label", { className: "curator-prune-aggressiveness", title: "Show scenes at or below this appeal threshold." }, React.createElement("span", null, `Appeal ≤ ${threshold.toFixed(2)}`), React.createElement("input", { type: "range", min: -1, max: 1, step: 0.05, value: threshold, onChange: (event) => updateUrl((s) => ({ ...s, maxAppeal: Number(event.target.value), page: 1 })), "aria-label": "Maximum appeal threshold" }))
      ),
      loading && React.createElement("div", { className: "curator-loading", role: "status" }, React.createElement("span", null, "Loading sentiment review…")),
      error && React.createElement("div", { className: "alert alert-danger" }, error),
      followUps.map((followUp) => React.createElement(TagSentimentFollowUp, { key: followUp.scene_id, followUp, onDismiss: () => setFollowUps((current) => current.filter((item) => item.scene_id !== followUp.scene_id)) })),
      data && !loading && data.items.length === 0 && React.createElement("div", { className: "alert alert-info" }, "No scenes below the current appeal threshold."),
      data && !loading && React.createElement(
        "section",
        { className: "curator-grid", "aria-live": "polite" },
        visibleItems.map((item) => React.createElement(RecommendationCard, { key: `${item.impression_id}:${item.scene_id}`, item, scene: scenes.get(String(item.scene_id)), slate, onRemove: remove, onThumbDown: showFollowUp }))
      ),
      data && React.createElement(Pager, { page, total: data.total, pageSize: data.page_size, hasMore: data.has_more, loading, onPage: (value) => updateUrl((s) => ({ ...s, page: value })), label: "Sentiment review pages" })
    );
  }

  // Manage shell (GH #150 Package 3): a two-pane list/detail view that hosts
  // every maintenance-flagged NAV_ITEMS entry plus Profiling. Each panel is
  // mounted unmodified — this is pure relocation, not a rebuild.
  const MANAGE_BODIES = {
    feedback: () => React.createElement(FeedbackHistoryPanel),
    taste: () => React.createElement(TasteProfilePanel, { embedded: true }),
    sentiment: () => React.createElement(ScoreReviewPanel),
    history: () => React.createElement(RecommendationHistoryPanel),
    backups: () => React.createElement(BackupPanel),
    diagnostics: () => React.createElement(DiagnosticsPanel),
    prune: () => React.createElement(PrunePanel),
    profiling: () => React.createElement(ProfilingPanel),
  };

  function ManagePanel({ section, onSelectSection }) {
    const items = MAINTENANCE_ITEMS;
    const active = items.find((item) => item.value === section) || items[0];
    const body = MANAGE_BODIES[active.value];
    return React.createElement(
      "div",
      { className: "curator-manage-shell" },
      React.createElement(
        "nav",
        { className: "curator-manage-list", "aria-label": "Manage sections" },
        items.map((item) => React.createElement(
          "button",
          {
            key: item.value,
            type: "button",
            className: "curator-manage-item",
            "aria-current": item.value === active.value ? "page" : undefined,
            onClick: () => onSelectSection(item.value),
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
        body && body()
      )
    );
  }

  function CuratorPage() {
    const history = useHistory();
    const routeLocation = useLocation();
    const route = new URLSearchParams(routeLocation.search);
    const requestedView = route.get("view") || "for_you";
    const loadingComponents = Api.hooks.useLoadComponents([Api.loadableComponents.SceneCard, Api.loadableComponents.PerformerCard]);
    const [nudgeDismissed, setNudgeDismissed] = React.useState(false);
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
    const [slate, setSlate] = React.useState(null);
    const [error, setError] = React.useState("");
    const [loading, setLoading] = React.useState(true);
    const [refreshKey, setRefreshKey] = React.useState(0);
    const [page, setPage] = useUrlPage(laneByValue.has(lane) ? `page_${lane}` : "page_for_you");
    const [configReady, setConfigReady] = React.useState(false);
    const [diversityEnabled, setDiversityEnabled] = React.useState(null);
    const [diversitySaving, setDiversitySaving] = React.useState(false);
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

    React.useEffect(() => setFollowUps([]), [lane]);

    React.useEffect(() => {
      let active = true;
      operation({ operation: "get_config" }).then(
        (data) => {
          if (!active) return;
          if (cachedConfigUpdatedAtMs !== data.updated_at_ms) clearSlateCache();
          cachedConfigUpdatedAtMs = data.updated_at_ms;
          setDiversityEnabled(Boolean(data.config.diversity_enabled));
          persistSlateCache();
          setConfigReady(true);
        },
        () => active && setConfigReady(true)
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
      const cached = slateCache.get(slateKey(lane, page));
      setSlate(cached || null);
      setLoading(!cached);
      setError("");
      loadSlate(lane, page).then(
        (data) => {
          if (!active) return;
          setSlate(data);
          setLoading(false);
        },
        (failure) => active && (setError(failure.message), setLoading(false))
      );
      return () => {
        active = false;
      };
    }, [lane, page, refreshKey, configReady]);
    React.useEffect(() => {
      if (slate?.page === page) {
        const last = Math.max(1, Math.ceil(slate.total / slate.page_size));
        if (page > last) setPage(last, { replace: true });
      }
    }, [slate, page]);

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
    function openView(view) {
      if (view === lane) return;
      setFollowUps([]);
      route.set("view", view);
      for (const param of ["performer", "label", "id", "type"]) route.delete(param);
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
    async function toggleDiversity() {
      const nextEnabled = !diversityEnabled;
      setDiversitySaving(true);
      setError("");
      try {
        await configurePlugin({ diversityDisabled: !nextEnabled });
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
      { className: "curator-page container-fluid", "data-theme": theme },
      React.createElement(
        "header",
        { className: "curator-header" },
        React.createElement("div", { className: "curator-brand" }, React.createElement("span", { className: "curator-brand-mark", "aria-hidden": "true" }, React.createElement(FontAwesomeIcon, { icon: faCompass })), React.createElement("div", null, React.createElement("h1", null, "Stash Curator"), React.createElement("p", { className: "curator-tagline" }, "Navigate your library, guided by your taste."))),
        React.createElement(
          "div",
          { className: "curator-navigation" },
          React.createElement(
            Nav,
            { variant: "tabs", role: "tablist", className: "curator-tabs" },
            TOP_NAV_ITEMS.map((option) => {
              const active = option.value === "recommendations" ? laneByValue.has(lane)
                : option.value === "manage" ? lane === "manage"
                : lane === option.value;
              const onClick = option.value === "recommendations"
                ? () => { if (!laneByValue.has(lane)) openView("for_you"); }
                : option.value === "manage"
                  ? () => { if (lane !== "manage") openManage(currentSection || MAINTENANCE_ITEMS[0].value); }
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
        React.createElement(CuratorControls, { onRefresh: refresh, onProfiling: () => openManage("profiling"), profilingActive: lane === "manage" && currentSection === "profiling", theme, onToggleTheme: toggleTheme })
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
      laneOption && lane !== "curate" && React.createElement(
        "div",
        { className: "curator-view-guidance" },
        React.createElement(
          "div",
          { className: "curator-view-copy" },
          React.createElement("h1", null, laneByValue.has(lane) ? "Recommendations" : laneOption.label),
          React.createElement("p", null, laneOption.description),
          laneByValue.has(lane) && React.createElement("p", null, "The colored corner icon identifies the source lane; Score is ranking utility, not a probability.")
        ),
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
        )
      ),
      followUps.map((followUp) => React.createElement(TagSentimentFollowUp, { key: followUp.scene_id, followUp, onDismiss: () => setFollowUps((current) => current.filter((item) => item.scene_id !== followUp.scene_id)) })),
      lane === "similar" && !loadingComponents && React.createElement(SimilarityPanel),
      lane === "curate" && React.createElement(CuratePanel),
      lane === "expand" && React.createElement(ExpandPanel, { key: "expand" }),
      lane === "hunt" && React.createElement(ExpandPanel, { key: "hunt", initialType: "hunt", huntOnly: true }),
      // Prune renders scene cards directly, same as SimilarityPanel above, so
      // it keeps its pre-existing !loadingComponents gate even though it now
      // mounts inside ManagePanel rather than as its own top-level branch.
      lane === "manage" && (currentSection !== "prune" || !loadingComponents) && React.createElement(ManagePanel, { section: currentSection, onSelectSection: openManage }),
      error && React.createElement("div", { className: "alert alert-danger" }, error, React.createElement("p", null, "Run “Sync and build recommendations” from Tasks if no model exists yet."), React.createElement(Button, { size: "sm", variant: "primary", onClick: () => start("Sync and build recommendations") }, React.createElement(FontAwesomeIcon, { icon: faSync }), " Sync and build now")),
      scenesQuery.error && React.createElement("div", { className: "alert alert-danger" }, scenesQuery.error.message),
      lane === "for_you" && !nudgeDismissed && !readCurateNudge().dismissed && readCurateNudge().rounds < MAX_NUDGE_ROUNDS && React.createElement(CurateNudge, { onOpen: () => openView("curate"), onDismiss: () => { dismissCurateNudge(); setNudgeDismissed(true); } }),
      laneByValue.has(lane) && slate && !loading &&
        React.createElement(
          React.Fragment,
          null,
          visibleItems.length === 0 && React.createElement("div", { className: "alert alert-info" }, React.createElement("p", null, "Nothing qualifies for this lane right now."), React.createElement(Button, { size: "sm", variant: "secondary", onClick: () => start("Rebuild recommendation model") }, React.createElement(FontAwesomeIcon, { icon: faWrench }), " Rebuild model")),
          React.createElement(
            "section",
            { className: "curator-grid", role: "tabpanel", "aria-live": "polite" },
            visibleItems.map((item) => React.createElement(RecommendationCard, { key: `${item.impression_id}:${item.scene_id}`, item, scene: scenes.get(String(item.scene_id)), slate, onRemove: remove, onThumbDown: showFollowUp }))
          ),
          React.createElement(Pager, { page, total: slate.total, pageSize: slate.page_size, hasMore: slate.has_more, loading, onPage: setPage, label: `${laneOption.label} pages` })
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

  function attachPlayer(pathname) {
    const match = pathname.match(/^\/scenes\/(\d+)/);
    if (!match) {
      finishTracker(false);
      return;
    }
    const sceneId = match[1];
    if (tracker?.value.scene_id === sceneId) return;
    finishTracker(false);
    let origin = null;
    try {
      origin = JSON.parse(sessionStorage.getItem(ORIGIN_KEY) || "null");
    } catch (_) {}
    if (origin?.scene_id !== sceneId) origin = null;
    if (origin) sessionStorage.removeItem(ORIGIN_KEY);
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
      const element = mediaElement();
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
    const element = mediaElement();
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
  Api.patch.after("MainNavBar.MenuItems", function (props, _, result) {
    const children = React.Children.toArray(props.children);
    if (!children.some((child) => child.key === "stash-curator")) {
      children.push(React.createElement(CuratorNavItem, { key: "stash-curator" }));
    }
    return React.isValidElement(result) ? React.cloneElement(result, {}, children) : result;
  });
  function CuratorContextLink({ type, id, label, target }) {
    const [host, setHost] = React.useState(null);
    React.useEffect(() => {
      setHost(document.querySelector(target));
    }, [target]);
    const query = new URLSearchParams({ view: "similar", type, id: String(id), label: label || "" });
    if (!host) return null;
    return ReactDOM.createPortal(React.createElement(NavLink, { className: "btn minimal curator-context-link curator-brand-mark", to: `/plugins/stash-curator?${query}`, title: `Find similar ${type}s with Curator`, "aria-label": `Find similar ${type}s with Curator` }, React.createElement(FontAwesomeIcon, { icon: faCompass })), host);
  }
  Api.patch.after("ScenePage", function (props, _, result) {
    return React.createElement(React.Fragment, null, result, React.createElement(CuratorContextLink, { type: "scene", id: props.scene.id, label: props.scene.title || `Scene ${props.scene.id}`, target: ".scene-tabs .scene-toolbar .scene-toolbar-group:last-child" }));
  });
  Api.patch.after("PerformerPage", function (props, _, result) {
    return React.createElement(React.Fragment, null, result, React.createElement(CuratorContextLink, { type: "performer", id: props.performer.id, label: props.performer.name || `Performer ${props.performer.id}`, target: "#performer-page .name-icons" }));
  });
  Api.Event.addEventListener("stash:location", (event) => {
    attachPlayer(event.detail.data.location.pathname);
    flushQueue();
  });
  window.addEventListener("online", flushQueue);
  window.addEventListener("online", flushTagPreferenceQueue);
  window.addEventListener("pagehide", () => finishTracker(false));
  attachPlayer(location.pathname);
  flushQueue();
  flushTagPreferenceQueue();
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
