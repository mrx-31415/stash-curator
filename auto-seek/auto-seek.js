(function () {
  "use strict";

  if (window.__autoSeekLoaded) return;
  window.__autoSeekLoaded = true;

  // The server finds the start points (auto_seek.py: frames cut by Stash's
  // ffmpeg, scored by an image model); this script reads them, asks for one
  // when a scene has none yet, and drives the player.
  const PLUGIN_ID = "auto-seek";
  const ENSURED_KEY = "auto-seek:ensured";
  // A scene takes a few seconds on a typical server; a busy one can queue it
  // behind the background task's ffmpeg runs.
  const ANALYSIS_TIMEOUT_MS = 120000;

  // ── pure helpers (tests/plugin/test_auto_seek.cjs) ─────────────────────

  function formatTime(seconds) {
    const s = Math.max(0, Math.round(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const rest = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${rest}` : `${m}:${rest}`;
  }

  // ── end pure helpers ───────────────────────────────────────────────────

  async function graphql(query, variables) {
    const response = await fetch("/graphql", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
    });
    const payload = await response.json();
    if (!response.ok || payload.errors) throw new Error(payload.errors?.[0]?.message || `HTTP ${response.status}`);
    return payload.data;
  }

  function operation(args) {
    return graphql(
      `mutation AutoSeekOperation($args: Map!) { runPluginOperation(plugin_id: "${PLUGIN_ID}", args: $args) }`,
      { args },
    ).then((data) => data.runPluginOperation);
  }

  let settingsPromise = null;
  function settings() {
    settingsPromise ||= graphql(`query AutoSeekSettings { configuration { plugins(include: ["${PLUGIN_ID}"]) } }`)
      .then((data) => ({ plugin: data.configuration.plugins[PLUGIN_ID] || {} }))
      .catch(() => ({ plugin: {} }));
    return settingsPromise;
  }

  // ── server-side files ──────────────────────────────────────────────────

  // Ask the backend once per tab to fetch the model if it hasn't yet; the
  // operation returns immediately and the download continues on the server.
  async function ensureServerFiles() {
    try {
      if (sessionStorage.getItem(ENSURED_KEY)) return;
      sessionStorage.setItem(ENSURED_KEY, "1");
    } catch (error) { /* storage blocked: ask anyway */ }
    const { plugin } = await settings();
    if (plugin.disableDownload === true) return;
    const current = await operation({ op: "status" });
    if (!current.ready && !current.downloading) await operation({ op: "ensure" });
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  // ── start points ───────────────────────────────────────────────────────

  // The server's answer: the cached start, or one worked out now. Fails after
  // a while rather than keeping the viewer waiting for ever.
  function analyseOnServer(id) {
    let timer;
    return Promise.race([
      operation({ op: "analyse", scene_id: id }),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Finding the start took too long; the server may be busy")), ANALYSIS_TIMEOUT_MS);
      }),
    ]).finally(() => clearTimeout(timer));
  }

  // One analysis at a time, remembered per scene for this tab.
  const known = new Map();
  let queue = Promise.resolve();
  function startPoint(id) {
    if (!known.has(id)) {
      const run = queue.then(() => analyseOnServer(id)).then((hit) => ({
        start: hit.start,
        duration: hit.duration,
        marked: hit.model === "user",
      }));
      queue = run.catch(() => {});
      known.set(id, run);
      run.catch(() => known.delete(id));
    }
    return known.get(id);
  }

  // Where to jump: a few seconds before the detected start, for a smoother way in.
  async function leadIn() {
    const value = Number((await settings()).plugin.leadIn);
    return Number.isFinite(value) && value >= 0 ? Math.min(value, 60) : 8;
  }

  // ── player ─────────────────────────────────────────────────────────────

  function sceneIdFrom(pathname) {
    const match = /^\/scenes\/(\d+)\/?$/.exec(pathname);
    return match ? match[1] : null;
  }

  const TARGET_ICON =
    '<svg class="auto-seek-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/>' +
    '<circle cx="12" cy="12" r="4.5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></svg>';

  const FLAG_ICON =
    '<svg class="auto-seek-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 21V4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>' +
    '<path d="M6 4h11l-2.5 4L17 12H6" fill="currentColor"/></svg>';

  // The viewer's own answer: the action starts where the player is now. It
  // replaces the computed start for this scene from now on (the backend
  // keeps it apart from the cache, so a new model doesn't undo it), and,
  // next to the computed start, is a label for training a better model.
  async function markStart(view) {
    const { video } = view;
    const start = video.currentTime;
    const duration = Math.max(video.duration || 0, start);
    const before = { marked: view.marked, start: view.start };
    // Answer the tap at once; the save follows (a busy server can take seconds).
    known.set(view.id, Promise.resolve({ start, duration, cached: true, marked: true }));
    view.promise = null;
    view.dismissed = true; // already there; no "Skip intro" now
    resolve(view).catch(() => {});
    operation({ op: "mark", scene_id: view.id, start, duration }).catch((error) => {
      known.delete(view.id);
      view.promise = null;
      resolve(view).catch(() => {});
      toast(view, `Couldn't save the start: ${error.message}`);
    });
    // Undo puts back an earlier mark, or else the computed start.
    toast(view, `Start set to ${formatTime(start)}`, async () => {
      const restore = before.marked
        ? { op: "mark", scene_id: view.id, start: before.start, duration }
        : { op: "unmark", scene_id: view.id };
      await operation(restore).catch(() => {});
      known.delete(view.id);
      view.promise = null;
      resolve(view).catch(() => {});
    });
  }

  // The scene page's state: its player, our controls, and what is known.
  let current = null;

  function render() {
    const view = current;
    if (!view) return;
    const label = {
      busy: "Finding where the action starts…",
      ready: view.target == null ? "Skip intro" : `Skip intro (to ${formatTime(view.target)}${view.marked ? ", your mark" : ""})`,
      error: `Auto Seek: ${view.error}`,
    }[view.state];
    view.button.dataset.state = view.state;
    view.button.title = label;
    view.button.querySelector(".vjs-control-text").textContent = label;
    // The pill only offers itself while there is still an intro to skip, or
    // while it is holding playback for the start point.
    const before = view.target == null ? view.video.currentTime < 120 : view.video.currentTime < view.target - 2;
    const show = view.holding || view.needsTap || (view.state !== "error" && !view.dismissed && before);
    view.pill.hidden = !show;
    // While the server works the start out the pill shimmers; once it shows
    // its arrow, a tap jumps straight there.
    view.pill.dataset.state = view.state;
    view.pill.title = label;
    view.pill.querySelector(".auto-seek-pill-text").textContent = view.holding
      ? "Starting…"
      : view.needsTap ? `Play from ${formatTime(view.target)}` : "Skip intro";
    view.pill.querySelector(".auto-seek-pill-arrow").hidden = view.state !== "ready";
  }

  // Stash's player is video.js. Seeking and playing through it, rather than
  // on the bare <video>, keeps its own state (and its handling of
  // transcoded streams) in step; the element is the fallback.
  function playerOf(view) {
    return view.video.closest(".video-js")?.player ?? null;
  }

  function setTime(view, time) {
    view.ourSeek = true;
    const player = playerOf(view);
    if (player) player.currentTime(time); else view.video.currentTime = time;
  }

  function playVideo(view) {
    const player = playerOf(view);
    return Promise.resolve(player ? player.play() : view.video.play());
  }

  function pauseVideo(view) {
    const player = playerOf(view);
    if (player) player.pause(); else view.video.pause();
  }

  function seekPlayer(view, time) {
    const before = view.video.currentTime;
    setTime(view, time);
    view.dismissed = true;
    render();
    toast(view, `Skipped to ${formatTime(time)}`, () => setTime(view, before));
  }

  function toast(view, text, undo) {
    const host = view.video.closest(".video-js");
    if (!host) return;
    host.querySelector(".auto-seek-toast")?.remove();
    const box = document.createElement("div");
    box.className = "auto-seek-toast";
    box.textContent = text;
    if (undo) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Undo";
      button.onclick = () => { undo(); box.remove(); };
      box.append(" ", button);
    }
    host.appendChild(box);
    setTimeout(() => box.remove(), 6000);
  }

  // Look the start point up (or work it out) and keep the view in step.
  function resolve(view) {
    view.promise ||= startPoint(view.id).then(
      async (result) => {
        view.target = Math.max(0, result.start - (await leadIn()));
        view.marked = Boolean(result.marked);
        view.start = result.start;
        view.state = "ready";
        render();
        return view.target;
      },
      (error) => {
        view.state = "error";
        view.error = error.message;
        view.promise = null;
        render();
        throw error;
      },
    );
    return view.promise;
  }

  // Hold playback until the start point is known, then jump there and play,
  // so the intro never plays while the analysis runs. Browsers only allow
  // audible playback straight after a tap, so a paused player is started and
  // stopped at once while the tap still counts; that lets the later play()
  // through. Gives up after `maxWaitMs` and plays from where it is.
  async function playFromStart(view, maxWaitMs) {
    const { video } = view;
    view.holding = true;
    view.tookOver = false;
    view.userSeeked = false;
    render();
    if (video.paused) await Promise.race([playVideo(view).catch(() => {}), sleep(1000)]);
    pauseVideo(view);
    // Stash's player may jump to the scene's resume point when playback
    // first starts; that is not the viewer moving.
    view.userSeeked = false;
    const target = await Promise.race([resolve(view).catch(() => null), sleep(maxWaitMs).then(() => null)]);
    view.holding = false;
    if (current !== view) return;
    // Jump unless the viewer moved on their own meanwhile, or is already past
    // the start (a resume point beyond the intro wins).
    if (target != null && !view.userSeeked && video.currentTime < target) seekPlayer(view, target);
    // Playing, or the viewer pressed play or pause themselves while it waited:
    // leave play and pause alone.
    if (!video.paused || view.tookOver) {
      render();
      return;
    }
    try {
      await playVideo(view);
    } catch (error) {
      view.needsTap = target != null;
    }
    render();
  }

  function onSkip(event) {
    event.stopPropagation();
    const view = current;
    if (!view || view.holding) return;
    const { video } = view;
    if (view.needsTap) {
      view.needsTap = false;
      playVideo(view).catch(() => {});
      render();
      return;
    }
    if (view.state === "error") { view.state = "busy"; render(); }
    if (view.target != null) {
      seekPlayer(view, view.target);
      if (video.paused) playVideo(view).catch(() => {});
      return;
    }
    if (video.paused) {
      playFromStart(view, 60000);
      return;
    }
    // Already playing: keep going and jump once the start is known.
    view.userSeeked = false;
    resolve(view).then((target) => {
      if (current === view && !view.userSeeked && video.currentTime < target) seekPlayer(view, target);
    }, () => {});
  }

  async function onFirstPlay(view) {
    if (view.autoDone || view.holding) return;
    view.autoDone = true;
    const { plugin } = await settings();
    if (plugin.autoSkip !== true || view.video.currentTime > 15) return;
    if (view.target != null) {
      if (!view.userSeeked && view.video.currentTime < view.target - 2) seekPlayer(view, view.target);
      return;
    }
    playFromStart(view, 30000);
  }

  function attach(id, video, bar) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "vjs-control vjs-button auto-seek-button";
    button.innerHTML = `${TARGET_ICON}<span class="vjs-control-text"></span>`;
    bar.insertBefore(button, bar.querySelector(".vjs-fullscreen-control"));
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "vjs-control vjs-button auto-seek-mark";
    marker.title = "The action starts here: skip to this point from now on";
    marker.innerHTML = `${FLAG_ICON}<span class="vjs-control-text">${marker.title}</span>`;
    bar.insertBefore(marker, button);
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = "auto-seek-pill";
    pill.innerHTML = '<span class="auto-seek-pill-text">Skip intro</span> <span class="auto-seek-pill-arrow" aria-hidden="true">›</span>';
    video.closest(".video-js").appendChild(pill);
    const view = { id, video, button, marker, pill, state: "busy", target: null, error: null, promise: null, autoDone: false, ourSeek: false, userSeeked: false, holding: false, needsTap: false, dismissed: false };
    current = view;
    button.addEventListener("click", onSkip);
    marker.addEventListener("click", (event) => { event.stopPropagation(); markStart(view); });
    pill.addEventListener("click", onSkip);
    video.addEventListener("seeking", () => {
      if (view.ourSeek) view.ourSeek = false; else if (video.currentTime > 1) view.userSeeked = true;
    });
    video.addEventListener("timeupdate", render);
    // The viewer pressing play or pause (a control, a tap on the picture, or
    // the keyboard) while playback is held ends the hold.
    const host = video.closest(".video-js");
    const takeOver = () => {
      if (!view.holding || view.tookOver) return;
      view.tookOver = true;
      view.holding = false;
      render();
    };
    // A tap on the picture only shows the controls on touch screens; with a
    // mouse, a click there toggles playback.
    const toggles = window.matchMedia?.("(pointer: fine)").matches
      ? ".vjs-play-control, .vjs-big-play-button, .vjs-tech, video"
      : ".vjs-play-control, .vjs-big-play-button";
    host.addEventListener("click", (event) => { if (event.target.closest(toggles)) takeOver(); }, true);
    host.addEventListener("keydown", (event) => { if (event.key === " " || event.key === "k") takeOver(); }, true);
    video.addEventListener("playing", () => onFirstPlay(view));
    render();
    // Work it out right away, so a click finds the answer ready.
    resolve(view).catch(() => {});
  }

  let observer = null;
  function onLocation(pathname) {
    observer?.disconnect();
    observer = null;
    const id = sceneIdFrom(pathname);
    if (!id) {
      current = null;
      return;
    }
    // Start right away; the player mounts a moment later and finds it running.
    startPoint(id).catch(() => {});
    const tryAttach = () => {
      const bar = document.querySelector(".video-js .vjs-control-bar");
      const video = document.querySelector(".video-js video");
      if (!bar || !video) return false;
      if (current?.id === id && current.button.isConnected && current.video === video) return true;
      bar.querySelector(".auto-seek-button")?.remove();
      bar.querySelector(".auto-seek-mark")?.remove();
      video.closest(".video-js").querySelector(".auto-seek-pill")?.remove();
      attach(id, video, bar);
      return true;
    };
    if (tryAttach()) return;
    observer = new MutationObserver(() => { if (tryAttach()) { observer.disconnect(); observer = null; } });
    observer.observe(document.body, { childList: true, subtree: true });
    setTimeout(() => { observer?.disconnect(); observer = null; }, 30000);
  }

  window.PluginApi?.Event?.addEventListener("stash:location", (event) => onLocation(event.detail.data.location.pathname));
  onLocation(location.pathname);
  setTimeout(() => ensureServerFiles().catch((error) => console.warn("Auto Seek:", error.message)), 3000);
})();
