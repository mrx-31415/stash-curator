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

  // Stash's sprite VTT: "HH:MM:SS.mmm --> HH:MM:SS.mmm" then
  // "sprite.jpg#xywh=x,y,w,h", one cue per thumbnail.
  function parseVtt(text) {
    const seconds = (stamp) => stamp.split(":").reduce((total, part) => total * 60 + parseFloat(part), 0);
    const cues = [];
    const pattern = /([\d:.]+)\s*-->\s*([\d:.]+)\s*\n[^\n#]*#xywh=(\d+),(\d+),(\d+),(\d+)/g;
    for (const match of text.matchAll(pattern)) {
      cues.push({ start: seconds(match[1]), end: seconds(match[2]), x: +match[3], y: +match[4], w: +match[5], h: +match[6] });
    }
    return cues;
  }

  function spriteCue(cues, time) {
    return cues.find((cue) => time >= cue.start && time < cue.end) || cues[cues.length - 1] || null;
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
  function withTimeout(promise, ms) {
    let timer;
    return Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Finding the start took too long; the server may be busy")), ms);
      }),
    ]).finally(() => clearTimeout(timer));
  }

  // While the model is still downloading on first use, keep waiting (the
  // strip shows the download) instead of failing.
  async function analyseOnServer(id) {
    for (;;) {
      try {
        return await withTimeout(operation({ op: "analyse", scene_id: id }), ANALYSIS_TIMEOUT_MS);
      } catch (error) {
        if (!/still downloading/i.test(error.message)) throw error;
        await sleep(2000);
      }
    }
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
        samples: hit.samples || [],
        threshold: hit.threshold,
      }));
      queue = run.catch(() => {});
      known.set(id, run);
      run.catch(() => known.delete(id));
    }
    return known.get(id);
  }

  // Where to jump: just before the detected start, for a smoother way in.
  // The search lands within seconds, so a short lead-in is enough.
  async function leadIn() {
    const value = Number((await settings()).plugin.leadIn);
    return Number.isFinite(value) && value >= 0 ? Math.min(value, 60) : 3;
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
    known.set(view.id, Promise.resolve({ start, duration, cached: true, marked: true, samples: view.samples, threshold: view.threshold }));
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

  // ── scan strip ─────────────────────────────────────────────────────────

  // A thin strip under the video showing the frames the server scored: one
  // bar each, as tall as the model was sure the action had started, orange
  // past the threshold and grey before it. It fills in live while a scene is
  // being worked out and flashes a line at the start once it is found. The
  // × hides it for this tab; Settings → "Hide the scan chart" for good.
  const STRIP_HIDDEN_KEY = "auto-seek:strip-hidden";
  // Auto Seek's logo (docs/assets/auto-seek.svg) as a self-contained image:
  // inline, its gradient, clip and glow references (url(#id)) resolve
  // against Stash's <base href> in some browsers and break.
  const STRIP_ICON = `<img class="auto-seek-strip-icon" alt="" src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 128 128%22%3E %3Cdefs%3E%3ClinearGradient id=%22g%22 x1=%2214%22 y1=%2210%22 x2=%22114%22 y2=%22118%22 gradientUnits=%22userSpaceOnUse%22%3E%3Cstop stop-color=%22%23ffcf3f%22/%3E%3Cstop offset=%22.55%22 stop-color=%22%23ff9a1f%22/%3E%3Cstop offset=%221%22 stop-color=%22%23ff5c39%22/%3E%3C/linearGradient%3E %3Cfilter id=%22glow%22 filterUnits=%22userSpaceOnUse%22 x=%220%22 y=%220%22 width=%22128%22 height=%22128%22%3E%3CfeGaussianBlur stdDeviation=%222.6%22 result=%22b%22/%3E%3CfeMerge%3E%3CfeMergeNode in=%22b%22/%3E%3CfeMergeNode in=%22SourceGraphic%22/%3E%3C/feMerge%3E%3C/filter%3E%3CclipPath id=%22k%22%3E%3Crect x=%2220%22 y=%2224%22 width=%2288%22 height=%2264%22 rx=%2213%22/%3E%3C/clipPath%3E%3CclipPath id=%22behind%22%3E%3Crect width=%2272%22 height=%22128%22/%3E%3C/clipPath%3E%3CclipPath id=%22ahead%22%3E%3Crect x=%2272%22 width=%2256%22 height=%22128%22/%3E%3C/clipPath%3E%3ClinearGradient id=%22t%22 x1=%2222%22 x2=%2272%22 gradientUnits=%22userSpaceOnUse%22%3E%3Cstop stop-color=%22%23ffb81f%22 stop-opacity=%220%22/%3E%3Cstop offset=%221%22 stop-color=%22%23ffb81f%22 stop-opacity=%22.42%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width=%22128%22 height=%22128%22 rx=%2234%22 fill=%22url(%23g)%22/%3E%3Crect x=%2220%22 y=%2224%22 width=%2288%22 height=%2264%22 rx=%2213%22 fill=%22%231b1208%22/%3E%3Cg clip-path=%22url(%23k)%22%3E%3Crect x=%2222%22 y=%2224%22 width=%2250%22 height=%2264%22 fill=%22url(%23t)%22/%3E%3Cg clip-path=%22url(%23ahead)%22%3E%3Cpath d=%22M44 38l18 18-18 18M64 38l18 18-18 18%22 fill=%22none%22 stroke=%22%23ffb81f%22 stroke-width=%228%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22 opacity=%22.3%22/%3E%3C/g%3E%3Cg clip-path=%22url(%23behind)%22%3E%3Cpath d=%22M44 38l18 18-18 18M64 38l18 18-18 18%22 fill=%22none%22 stroke=%22%23fff%22 stroke-width=%228%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22/%3E%3C/g%3E%3Cpath d=%22M72 24V88%22 stroke=%22%23ffd25a%22 stroke-width=%223.5%22 filter=%22url(%23glow)%22/%3E%3C/g%3E%3Crect x=%2224.0%22 y=%22108.5%22 width=%224%22 height=%223.5%22 rx=%222%22 fill=%22%231b1208%22 opacity=%220.42%22/%3E%3Crect x=%2231.6%22 y=%22108.5%22 width=%224%22 height=%223.5%22 rx=%222%22 fill=%22%231b1208%22 opacity=%220.42%22/%3E%3Crect x=%2239.2%22 y=%22108.5%22 width=%224%22 height=%223.5%22 rx=%222%22 fill=%22%231b1208%22 opacity=%220.42%22/%3E%3Crect x=%2246.8%22 y=%22108.5%22 width=%224%22 height=%223.5%22 rx=%222%22 fill=%22%231b1208%22 opacity=%220.42%22/%3E%3Crect x=%2254.4%22 y=%22107.6%22 width=%224%22 height=%224.4%22 rx=%222%22 fill=%22%231b1208%22 opacity=%220.46%22/%3E%3Crect x=%2262.0%22 y=%22103.0%22 width=%224%22 height=%229.0%22 rx=%222%22 fill=%22%231b1208%22 opacity=%220.63%22/%3E%3Crect x=%2269.6%22 y=%2298.0%22 width=%224%22 height=%2214.0%22 rx=%222%22 fill=%22%23fff%22 opacity=%221.00%22/%3E%3Crect x=%2277.2%22 y=%22102.2%22 width=%224%22 height=%229.8%22 rx=%222%22 fill=%22%231b1208%22 opacity=%220.66%22/%3E%3Crect x=%2284.8%22 y=%22107.3%22 width=%224%22 height=%224.7%22 rx=%222%22 fill=%22%231b1208%22 opacity=%220.46%22/%3E%3Crect x=%2292.4%22 y=%22108.4%22 width=%224%22 height=%223.6%22 rx=%222%22 fill=%22%231b1208%22 opacity=%220.42%22/%3E%3Crect x=%22100.0%22 y=%22108.5%22 width=%224%22 height=%223.5%22 rx=%222%22 fill=%22%231b1208%22 opacity=%220.42%22/%3E%3C/svg%3E">`;

  function stripDismissed() {
    try { return sessionStorage.getItem(STRIP_HIDDEN_KEY) === "1"; } catch (error) { return false; }
  }

  async function ensureStrip(view) {
    if (view.strip?.isConnected) return view.strip;
    if (stripDismissed() || (await settings()).plugin.hideScanChart === true || current !== view) return null;
    const wrapper = view.video.closest(".video-wrapper");
    if (!wrapper?.parentElement || view.strip?.isConnected) return view.strip?.isConnected ? view.strip : null;
    document.querySelectorAll(".auto-seek-strip").forEach((old) => old.remove());
    const strip = document.createElement("div");
    strip.className = "auto-seek-strip";
    strip.innerHTML =
      '<div class="auto-seek-strip-bars"><span class="auto-seek-strip-line"></span><b class="auto-seek-strip-flag" hidden></b></div>' +
      `<span class="auto-seek-strip-label">${STRIP_ICON}<span></span></span>` +
      '<div class="auto-seek-strip-peek" hidden><span class="auto-seek-strip-peek-image"></span><span class="auto-seek-strip-peek-text"></span></div>' +
      '<button type="button" class="auto-seek-strip-close" aria-label="Hide the scan chart" title="Hide (Settings → Plugins → Auto Seek hides it for good)">×</button>';
    strip.querySelector(".auto-seek-strip-label").addEventListener("click", () => strip.classList.toggle("is-quiet"));
    strip.querySelector(".auto-seek-strip-close").addEventListener("click", () => {
      try { sessionStorage.setItem(STRIP_HIDDEN_KEY, "1"); } catch (error) { /* hidden on this page only */ }
      strip.remove();
    });
    wrapper.after(strip);
    view.strip = strip;
    view.stripDrawn = 0;
    attachPeek(view, strip);
    alignStrip(view);
    // Keep the bars over the matching spot of the seek bar as the page resizes.
    view.stripResize?.disconnect();
    view.stripResize = new ResizeObserver(() => alignStrip(view));
    view.stripResize.observe(strip);
    return strip;
  }

  // Line the bars up with Stash's seek bar, so a bar sits over the moment it
  // was taken from (the seek bar is inset by the player's buttons).
  function alignStrip(view) {
    const bars = view.strip?.querySelector(".auto-seek-strip-bars");
    const holder = view.video.closest(".video-js")?.querySelector(".vjs-progress-holder");
    if (!bars || !holder) return;
    const seek = holder.getBoundingClientRect();
    const strip = view.strip.getBoundingClientRect();
    if (!seek.width || !strip.width) return;
    bars.style.marginLeft = `${seek.left - strip.left}px`;
    bars.style.width = `${seek.width}px`;
  }

  // Add the frames not drawn yet; `samples` only ever grows.
  function paintStrip(view, { samples = [], duration, threshold }, pace = 90) {
    const bars = view.strip?.querySelector(".auto-seek-strip-bars");
    if (!bars || !(duration > 0)) return;
    if (threshold != null) bars.querySelector(".auto-seek-strip-line").style.bottom = `${100 * threshold}%`;
    view.stripPending ||= [];
    if (samples.length < view.stripDrawn) {
      bars.querySelectorAll("i").forEach((bar) => bar.remove());
      view.stripPending = [];
      view.stripDrawn = 0;
    }
    // Frames arrive in clumps (they are cut in parallel); they join a queue
    // that adds one bar at a steady pace, so the strip visibly works through
    // the scene frame by frame.
    view.stripPending.push(...samples.slice(view.stripDrawn).map(([time, score]) => ({ time, score, duration, threshold })));
    view.stripDrawn = samples.length;
    if (!view.stripTimer) drainStrip(view, bars, pace);
  }

  function drainStrip(view, bars, pace) {
    const next = view.stripPending.shift();
    if (!next) {
      view.stripTimer = null;
      view.stripIdle?.();
      return;
    }
    const { time, score, duration, threshold } = next;
    const bar = document.createElement("i");
    if (threshold != null && score >= threshold) bar.className = "hit";
    bar.style.left = `${Math.min(100, Math.max(0, (100 * time) / duration))}%`;
    bar.style.height = `${22 + 78 * score}%`; // a visible stub even at 0
    bar.dataset.time = time;
    bar.dataset.score = score;
    bars.appendChild(bar);
    view.stripTimer = setTimeout(() => drainStrip(view, bars, pace), pace);
  }

  // Resolves once every queued bar is on the strip.
  function stripSettled(view) {
    if (!view.stripTimer && !view.stripPending?.length) return Promise.resolve();
    return new Promise((resolve) => {
      const previous = view.stripIdle;
      view.stripIdle = () => { view.stripIdle = null; previous?.(); resolve(); };
    });
  }

  // ── strip preview: Stash's own seek-bar sprite, when the scene has one ──

  const spriteCache = new Map();
  function sceneSprite(id) {
    if (!spriteCache.has(id)) {
      spriteCache.set(id, (async () => {
        const data = await graphql(
          "query AutoSeekSprite($id: ID!) { autoSeekSprite: findScene(id: $id) { paths { vtt sprite } } }",
          { id },
        );
        const paths = data.autoSeekSprite?.paths;
        if (!paths?.vtt || !paths?.sprite) return null;
        const response = await fetch(paths.vtt, { credentials: "same-origin" });
        if (!response.ok) return null;
        return { sprite: paths.sprite, cues: parseVtt(await response.text()) };
      })().catch(() => null));
    }
    return spriteCache.get(id);
  }

  // Exact frames for the preview, cut by the server once per bar and kept.
  const frameCache = new Map();
  let peekTimer = null;
  async function exactFrame(id, time) {
    const key = `${id}:${time}`;
    if (!frameCache.has(key)) {
      frameCache.set(key, operation({ op: "frame", scene_id: id, time })
        .then((frame) => (frame.jpeg ? `data:image/jpeg;base64,${frame.jpeg}` : null))
        .catch(() => null));
    }
    const url = await frameCache.get(key);
    if (url) frameCache.set(key, url); // later hovers read the URL at once
    return url;
  }

  function showImage(image, source) {
    image.hidden = !source;
    if (!source) return;
    const { url, cue } = source;
    image.style.backgroundImage = `url("${url}")`;
    if (cue) {
      image.style.width = `${cue.w}px`;
      image.style.height = `${cue.h}px`;
      image.style.backgroundSize = "";
      image.style.backgroundPosition = `-${cue.x}px -${cue.y}px`;
    } else {
      image.style.width = "160px";
      image.style.height = "90px";
      image.style.backgroundSize = "cover";
      image.style.backgroundPosition = "center";
    }
  }

  function attachPeek(view, strip) {
    const bars = strip.querySelector(".auto-seek-strip-bars");
    const peek = strip.querySelector(".auto-seek-strip-peek");
    const image = peek.querySelector(".auto-seek-strip-peek-image");
    const text = peek.querySelector(".auto-seek-strip-peek-text");
    const show = async (event) => {
      const box = bars.getBoundingClientRect();
      let nearest = null;
      let distance = 10; // px: a bar is only a few pixels wide
      for (const bar of bars.querySelectorAll("i")) {
        const x = bar.getBoundingClientRect().left + bar.offsetWidth / 2;
        if (Math.abs(x - event.clientX) < distance) { nearest = bar; distance = Math.abs(x - event.clientX); }
      }
      if (!nearest) { peek.hidden = true; return; }
      const time = Number(nearest.dataset.time);
      const score = Number(nearest.dataset.score);
      text.textContent = `${formatTime(time)} · ${Math.round(100 * score)}%`;
      peek.style.left = `${Math.min(Math.max(nearest.getBoundingClientRect().left - box.left, 60), box.width - 60)}px`;
      peek.hidden = false;
      peek.dataset.time = String(time);
      // The seek-bar sprite first (instant, but its nearest thumbnail can be
      // tens of seconds away), then the exact frame from the server.
      const exact = frameCache.get(`${view.id}:${time}`);
      if (typeof exact === "string") { showImage(image, { url: exact }); return; }
      const sprite = await sceneSprite(view.id);
      const cue = sprite && spriteCue(sprite.cues, time);
      if (peek.dataset.time !== String(time)) return;
      showImage(image, cue ? { url: sprite.sprite, cue } : null);
      clearTimeout(peekTimer);
      peekTimer = setTimeout(async () => {
        const url = await exactFrame(view.id, time);
        if (url && peek.dataset.time === String(time) && !peek.hidden) showImage(image, { url });
      }, 120);
    };
    bars.addEventListener("pointermove", show);
    bars.addEventListener("pointerdown", show);
    bars.addEventListener("pointerleave", () => { peek.hidden = true; });
  }

  function labelStrip(view, text) {
    const label = view.strip?.querySelector(".auto-seek-strip-label span");
    if (label) label.textContent = text;
  }

  async function showStart(view, flash) {
    if (!view.samples?.length || !(await ensureStrip(view))) return;
    // A cached answer fills in quickly; a live one keeps its pace.
    paintStrip(view, { samples: view.samples, duration: view.duration, threshold: view.threshold }, view.stripDrawn ? 90 : 25);
    await stripSettled(view);
    const flag = view.strip.querySelector(".auto-seek-strip-flag");
    flag.hidden = false;
    flag.classList.toggle("marked", Boolean(view.marked));
    flag.style.left = `${Math.min(100, Math.max(0, (100 * view.start) / view.duration))}%`;
    labelStrip(view, view.marked ? `Your start · ${formatTime(view.start)}` : `Starts at ${formatTime(view.start)}`);
    view.strip.classList.remove("is-busy");
    // Once found, the words step aside after a moment so they don't cover
    // the bars; hovering the strip (or tapping the logo) brings them back.
    view.strip.classList.remove("is-quiet");
    clearTimeout(view.quietTimer);
    view.quietTimer = setTimeout(() => view.strip?.classList.add("is-quiet"), 4000);
    if (flash) {
      view.strip.classList.remove("is-found");
      void view.strip.offsetWidth; // restart the animation
      view.strip.classList.add("is-found");
    }
  }

  // While the server works, poll what it has scored so far.
  // What the server is doing, in words.
  function phaseText(progress) {
    const mb = (bytes) => Math.round((bytes || 0) / 1e6);
    switch (progress.phase) {
      case "downloading":
        return `Downloading the model, ${mb(progress.received)} of ${mb(progress.total)} MB (first time only)…`;
      case "waiting-download":
        return progress.error ? `The model download failed: ${progress.error}` : "Preparing to download the model (first time only)…";
      case "loading": return "Loading the model…";
      case "sampling": return "Looking through the scene…";
      case "zooming": return "Zooming in…";
      case "pinpointing": return "Pinpointing the start…";
      default: return "Finding where the action starts…";
    }
  }

  function watchProgress(view) {
    let stopped = false;
    (async () => {
      await sleep(250);
      while (!stopped && current === view && view.state === "busy") {
        try {
          const progress = await operation({ op: "progress", scene_id: view.id });
          if (!stopped && progress.phase && (await ensureStrip(view))) {
            view.strip.classList.add("is-busy");
            labelStrip(view, phaseText(progress));
            if (progress.samples?.length) paintStrip(view, progress);
          }
        } catch (error) { /* the result itself will arrive or fail */ }
        await sleep(200);
      }
    })();
    return () => { stopped = true; };
  }

  // Look the start point up (or work it out) and keep the view in step.
  function resolve(view) {
    if (view.promise) return view.promise;
    const stopWatching = view.state === "busy" ? watchProgress(view) : () => {};
    view.promise = startPoint(view.id).then(
      async (result) => {
        stopWatching();
        view.target = Math.max(0, result.start - (await leadIn()));
        view.marked = Boolean(result.marked);
        view.start = result.start;
        view.duration = result.duration;
        view.samples = result.samples || [];
        view.threshold = result.threshold;
        view.state = "ready";
        render();
        showStart(view, true).catch(() => {});
        return view.target;
      },
      (error) => {
        stopWatching();
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
    // The strip shows at once, saying it is working, until bars arrive.
    ensureStrip(view).then((strip) => {
      if (strip && view.state === "busy") {
        strip.classList.add("is-busy");
        labelStrip(view, "Finding where the action starts…");
      }
    }).catch(() => {});
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
      document.querySelectorAll(".auto-seek-strip").forEach((strip) => strip.remove());
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
