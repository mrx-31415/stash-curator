/* Standalone interaction study: sample photo clips, no Stash calls. */
"use strict";
const $ = (id) => document.getElementById(id);
const titles = ["The quiet between", "Somewhere unexpected", "Golden hour", "A different perspective", "Off the beaten path", "Stay a little longer", "Into the open", "A change of scenery", "After the rain", "Nothing but time", "Worth the detour", "One more moment", "Far from here", "The long way home", "Another horizon", "Just around the bend", "Under open skies", "No particular destination", "Out of the ordinary", "The slower road", "Something worth finding", "Before the world wakes", "A moment apart", "Follow the light"];
const scenes = titles.map((title, id) => ({ id, title, image: `assets/${String(id).padStart(2, "0")}.jpg`, video: `assets/${String(id).padStart(2, "0")}.mp4` }));
const state = { lane: "For You", pool: scenes, seen: new Set(), history: [], index: -1, phase: "idle", rotation: 0, token: 0, roulette: true };
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
let audio, muted = false, hideTimer, lastTick = 0;
try { muted = localStorage.getItem("curator-roulette-muted") === "true"; } catch { /* Storage may be unavailable in a private preview. */ }

function syncMute() {
  $("mute").setAttribute("aria-pressed", String(muted));
  $("mute").setAttribute("aria-label", muted ? "Unmute roulette sound" : "Mute roulette sound");
  document.querySelector(".mute-slash").hidden = !muted;
  $("video").muted = muted;
}
function enableAudio() {
  if (muted) return;
  try { audio ||= new AudioContext(); audio.resume().catch(() => {}); } catch { /* Sound is optional. */ }
}
function tone(landing = false) {
  if (muted || !audio || audio.state !== "running") return;
  const now = audio.currentTime;
  if (!landing && now - lastTick < .065) return;
  lastTick = now;
  const oscillator = audio.createOscillator(), gain = audio.createGain();
  oscillator.type = "sine";
  oscillator.frequency.setValueAtTime(landing ? 660 : 900, now);
  oscillator.frequency.exponentialRampToValueAtTime(landing ? 440 : 540, now + .035);
  gain.gain.setValueAtTime(landing ? .045 : .018, now);
  gain.gain.exponentialRampToValueAtTime(.0001, now + (landing ? .25 : .045));
  oscillator.connect(gain).connect(audio.destination);
  oscillator.start(now); oscillator.stop(now + .28);
}
function phase(value) {
  state.phase = value;
  $("stage").dataset.phase = value;
  $("exhausted").hidden = value !== "exhausted";
  $("previous").disabled = state.index < 1;
}
function announce(message) { $("announcement").textContent = message; }
function rememberTime() {
  if (state.history[state.index]) state.history[state.index].time = $("video").currentTime;
}
function poolFor(lane) {
  return lane === "Best Bets" ? scenes.slice(0, 8) : lane === "Revisit" ? scenes.slice(16) : scenes;
}
function renderCards() {
  $("cards").replaceChildren(...state.pool.map((scene, i) => {
    const card = document.createElement("article"); card.className = "card";
    card.innerHTML = `<div class="card-image"><img src="${scene.image}" alt="Sample contender ${i + 1}" loading="eager"><span class="rank">${state.lane}</span></div><h2>${scene.title}</h2><p>Sample photo clip · 10 sec</p>`;
    return card;
  }));
  $("lane-caption").textContent = state.lane;
  $("lane-caption").nextElementSibling.textContent = `${state.pool.length} contenders · no repeats this session`;
}
function buildWheel(contenders) {
  const point = (r, a) => [300 + r * Math.cos(a), 300 + r * Math.sin(a)].join(" ");
  const step = 2 * Math.PI / contenders.length;
  const path = (a, b) => {
    const middle = (a + b) / 2;
    return `M ${point(280, a)} A 280 280 0 0 1 ${point(280, middle)} A 280 280 0 0 1 ${point(280, b)} L ${point(175, b)} A 175 175 0 0 0 ${point(175, middle)} A 175 175 0 0 0 ${point(175, a)} Z`;
  };
  $("wheel").innerHTML = `<defs>${contenders.map((scene, i) => {
    const a = -Math.PI / 2 + i * step - step / 2, b = a + step;
    return `<clipPath id="segment-${i}"><path d="${path(a, b)}"/></clipPath>`;
  }).join("")}</defs>${contenders.map((scene, i) => {
    const a = -Math.PI / 2 + i * step, x = 300 + 228 * Math.cos(a), y = 300 + 228 * Math.sin(a);
    const start = a - step / 2, end = a + step / 2;
    const size = contenders.length < 5 ? 600 : 360;
    return `<g><g clip-path="url(#segment-${i})"><image class="wheel-thumbnail" style="--slot-angle:${i * 360 / contenders.length}deg" href="${scene.frame || scene.image}" x="${size === 600 ? 0 : x - size / 2}" y="${size === 600 ? 0 : y - size / 2}" width="${size}" height="${size}" preserveAspectRatio="xMidYMid slice"/></g><path class="wedge" data-scene="${scene.id}" fill="transparent" d="${path(start, end)}"/><title>${scene.title}</title></g>`;
  }).join("")}`;
}
function shuffle(items) {
  const result = [...items];
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function resetPlayerShape() {
  for (const element of [$("video"), $("spinner")]) {
    element.getAnimations().forEach((animation) => animation.cancel());
    element.removeAttribute("style");
  }
}
function winnerShape(contenders, winnerIndex) {
  const stage = $("stage").getBoundingClientRect();
  const wheel = document.querySelector(".wheel-wrap").getBoundingClientRect();
  const image = document.querySelectorAll("#wheel image")[winnerIndex];
  const x = Number(image.getAttribute("x")), y = Number(image.getAttribute("y"));
  const size = Number(image.getAttribute("width")), scale = wheel.width / 600;
  const degrees = ((state.rotation + 180) % 360) - 180, rotation = degrees * Math.PI / 180;
  const dx = (x + size / 2 - 300) * scale, dy = (y + size / 2 - 300) * scale;
  const centerX = wheel.left - stage.left + wheel.width / 2 + dx * Math.cos(rotation) - dy * Math.sin(rotation);
  const centerY = wheel.top - stage.top + wheel.height / 2 + dx * Math.sin(rotation) + dy * Math.cos(rotation);
  const step = 2 * Math.PI / contenders.length;
  const start = -Math.PI / 2 + winnerIndex * step - step / 2;
  const outline = [], rectangle = [];
  for (let edge = 0; edge < 2; edge++) {
    for (let i = 0; i <= 32; i++) {
      const t = edge ? 1 - i / 32 : i / 32, angle = start + step * t;
      const radius = edge ? 175 : 280;
      const px = 300 + radius * Math.cos(angle) - x - size / 2;
      const py = 300 + radius * Math.sin(angle) - y - size / 2;
      outline.push(`${50 + (px * Math.cos(rotation) - py * Math.sin(rotation)) / size * 100}% ${50 + (px * Math.sin(rotation) + py * Math.cos(rotation)) / size * 100}%`);
      rectangle.push(`${t * 100}% ${edge * 100}%`);
    }
  }
  return {
    left: `${centerX - size * scale / 2}px`, top: `${centerY - size * scale / 2}px`,
    width: `${size * scale}px`, height: `${size * scale}px`,
    transform: "rotate(0deg)", clipPath: `polygon(${outline.join(",")})`,
    rectangle: `polygon(${rectangle.join(",")})`,
  };
}
function playerShape(rectangle) {
  const video = $("video"), stage = $("stage");
  const aspect = video.videoWidth / video.videoHeight || 16 / 9;
  const width = Math.min(stage.clientWidth, stage.clientHeight * aspect), height = width / aspect;
  return {
    left: `${(stage.clientWidth - width) / 2}px`, top: `${(stage.clientHeight - height) / 2}px`,
    width: `${width}px`, height: `${height}px`, transform: "rotate(0deg)", clipPath: rectangle,
  };
}
async function expandWinner(shape, token) {
  const video = $("video"), stage = $("stage");
  const { rectangle, ...start } = shape, target = playerShape(rectangle);
  const timing = { duration: reduced.matches ? 1 : 1300, easing: "cubic-bezier(.4,0,.2,1)", fill: "forwards" };
  phase("revealing");
  const expansion = video.animate([start, target], timing);
  $("spinner").animate([{ transform: "scale(1)" }, { transform: `scale(${Math.min(.45, parseFloat(target.height) / stage.clientHeight * .7)})` }], timing);
  await expansion.finished.catch(() => {});
  if (token !== state.token) return;
  phase("playing"); resetPlayerShape(); wake();
}
async function returnToWheel() {
  const entry = state.history[state.index];
  if (!entry?.wheel) return true;
  const token = ++state.token, video = $("video");
  resetPlayerShape();
  const { contenders, winnerIndex, rotation } = entry.wheel;
  buildWheel(contenders); state.rotation = rotation;
  $("wheel").style.setProperty("--wheel-rotation", `${rotation}deg`);
  document.querySelector(".wheel-wrap").style.setProperty("--camera-zoom", "1");
  document.querySelector(`[data-scene="${entry.scene.id}"]`).classList.add("winner");
  const { rectangle, ...target } = winnerShape(contenders, winnerIndex);
  const start = playerShape(rectangle);
  Object.assign(video.style, start); phase("returning");
  const timing = { duration: reduced.matches ? 1 : 1100, easing: "cubic-bezier(.4,0,.2,1)", fill: "forwards" };
  const contraction = video.animate([start, target], timing);
  $("spinner").animate([{ transform: `scale(${Math.min(.45, parseFloat(start.height) / $("stage").clientHeight * .7)})` }, { transform: "scale(1)" }], timing);
  await contraction.finished.catch(() => {});
  if (token !== state.token) return false;
  video.pause(); rememberTime();
  if (video.readyState >= 2) {
    try {
      const frame = document.createElement("canvas");
      frame.width = video.videoWidth; frame.height = video.videoHeight;
      frame.getContext("2d").drawImage(video, 0, 0);
      entry.scene.frame = frame.toDataURL();
      document.querySelectorAll("#wheel image")[winnerIndex].setAttribute("href", entry.scene.frame);
    } catch { /* Keep the poster if frame capture is unavailable. */ }
  }
  phase("docked");
  return true;
}
async function spin(first = false) {
  if (["spinning", "landing", "revealing", "returning"].includes(state.phase)) return;
  rememberTime(); $("video").pause(); resetPlayerShape(); $("playback-error").hidden = true;
  const available = state.pool.filter((scene) => !state.seen.has(scene.id));
  if (!available.length) { phase("exhausted"); announce("You’ve played every available pick."); $("restart").focus(); return; }
  const token = ++state.token;
  if (first) scenes.forEach((scene) => { delete scene.frame; });
  const previous = first ? null : state.history[state.index]?.wheel;
  const contenders = previous ? [...previous.contenders] : shuffle(available).slice(0, innerWidth < 760 ? 16 : 24);
  const present = new Set(contenders.map((scene) => scene.id));
  const incoming = shuffle(available.filter((scene) => !present.has(scene.id)));
  const currentId = state.history[state.index]?.scene.id, replacements = [];
  contenders.forEach((scene, index) => {
    if (scene.id !== currentId && state.seen.has(scene.id) && incoming.length) {
      contenders[index] = incoming.pop(); replacements.push(index);
    }
  });
  const eligible = contenders.flatMap((scene, index) => state.seen.has(scene.id) ? [] : [index]);
  if (!eligible.length) { phase("exhausted"); announce("No unplayed picks remain on this wheel."); return; }
  // Mild rank weighting leaves most of the draw to chance.
  const weights = eligible.map((index) => 1 - .3 * state.pool.indexOf(contenders[index]) / state.pool.length);
  let draw = Math.random() * weights.reduce((a, b) => a + b, 0), winnerIndex = eligible[0];
  for (let i = 0; i < weights.length; i++) { draw -= weights[i]; if (draw <= 0) { winnerIndex = eligible[i]; break; } }
  const winner = contenders[winnerIndex];
  if (!previous) buildWheel(contenders);
  phase("spinning"); wake();
  let refreshed = !replacements.length;
  const camera = document.querySelector(".wheel-wrap");
  camera.style.setProperty("--camera-zoom", "1");
  $("spin-caption").textContent = first ? "Something good is coming." : "A fresh chance. Same good taste.";
  announce(`Spinning ${state.lane}. ${available.length} contenders remaining.`);
  const start = state.rotation, step = 360 / contenders.length;
  const alignment = ((-winnerIndex * step - start) % 360 + 360) % 360;
  const target = start + (first ? 720 : 360) + alignment;
  const duration = reduced.matches ? 100 : first ? 3800 : 2600;
  await new Promise((resolve) => {
    const started = performance.now(); let previousSector = -1;
    function frame(now) {
      if (token !== state.token) { resolve(); return; }
      const t = Math.min(1, (now - started) / duration);
      const eased = t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      state.rotation = reduced.matches ? target : start + (target - start) * eased;
      $("wheel").style.setProperty("--wheel-rotation", `${state.rotation}deg`);
      camera.style.setProperty("--camera-zoom", reduced.matches ? "1" : String(1 + .16 * eased));
      if (!refreshed && (reduced.matches || state.rotation - start >= step)) {
        const images = $("wheel").querySelectorAll("image"), slots = $("wheel").querySelectorAll(".wedge");
        for (const index of replacements) {
          images[index].setAttribute("href", contenders[index].frame || contenders[index].image);
          slots[index].dataset.scene = contenders[index].id;
          slots[index].parentNode.querySelector("title").textContent = contenders[index].title;
        }
        refreshed = true;
      }
      const sector = Math.floor((state.rotation + step / 2) / step);
      if (sector !== previousSector && !reduced.matches) {
        tone(); previousSector = sector;
        const pointer = document.querySelector(".pointer");
        pointer.classList.remove("tick"); void pointer.offsetWidth; pointer.classList.add("tick");
      }
      if (t < 1) requestAnimationFrame(frame); else resolve();
    }
    requestAnimationFrame(frame);
  });
  if (token !== state.token) return;
  phase("landing"); tone(true);
  document.querySelectorAll(".wedge.winner").forEach((slot) => slot.classList.remove("winner"));
  document.querySelector(`[data-scene="${winner.id}"]`).classList.add("winner");
  $("spin-caption").textContent = "There it is.";
  await wait(reduced.matches ? 1 : 100);
  if (token !== state.token) return;
  state.seen.add(winner.id);
  state.history.splice(state.index + 1);
  state.history.push({ scene: winner, time: 0, wheel: { contenders, winnerIndex, rotation: state.rotation } }); state.index = state.history.length - 1;
  playCurrent(winnerShape(contenders, winnerIndex));
}
async function playCurrent(shape = null) {
  const entry = state.history[state.index]; if (!entry) return;
  const token = ++state.token;
  const video = $("video");
  resetPlayerShape();
  if (shape) {
    const { rectangle, ...start } = shape;
    Object.assign(video.style, start);
  }
  const previousSource = video.src;
  video.removeAttribute("src"); video.load();
  if (previousSource.startsWith("blob:")) URL.revokeObjectURL(previousSource);
  video.onloadedmetadata = () => { video.currentTime = entry.time; };
  video.poster = entry.scene.image;
  video.muted = muted; phase(shape ? "landing" : "playing");
  $("playing-title").textContent = entry.scene.title;
  $("position").textContent = `${state.seen.size} / ${state.pool.length}`;
  $("pause").textContent = "Pause"; $("pause").setAttribute("aria-label", "Pause playback");
  announce(`Playing ${entry.scene.title}.`); wake();
  try {
    // Blob playback permits seeking on basic static servers without Range support.
    const response = await fetch(entry.scene.video);
    if (!response.ok) throw new Error("Sample clip unavailable");
    const clip = await response.blob();
    if (token !== state.token) return;
    video.src = URL.createObjectURL(clip);
    await video.play();
    if (token !== state.token) return;
    if (shape) await expandWinner(shape, token);
  } catch {
    if (token !== state.token) return;
    if (shape) await expandWinner(shape, token);
    if (token !== state.token) return;
    $("pause").textContent = "Play"; $("pause").setAttribute("aria-label", "Play selected scene");
    $("playback-error").textContent = "Playback paused by your browser. Press Play to continue.";
    $("playback-error").hidden = false;
  }
}
function wake() {
  $("stage").classList.remove("quiet"); clearTimeout(hideTimer);
  hideTimer = setTimeout(() => { if (!$("video").paused) $("stage").classList.add("quiet"); }, 2700);
}
function launch(roulette = true) {
  enableAudio(); state.roulette = roulette; state.seen.clear(); state.history = []; state.index = -1;
  $("mode-lane").textContent = state.lane;
  $("experience").showModal(); document.body.classList.add("engaged");
  if (roulette) spin(true);
  else { state.history.push({ scene: state.pool[0], time: 0 }); state.seen.add(state.pool[0].id); state.index = 0; playCurrent(); }
}
async function exit() {
  ++state.token; rememberTime(); $("video").pause(); resetPlayerShape(); phase("idle"); clearTimeout(hideTimer);
  document.body.classList.remove("engaged"); $("experience").close();
  if (document.fullscreenElement) await document.exitFullscreen().catch(() => {});
  $("launch").focus();
}
async function next() {
  if (state.phase !== "playing") return;
  if (state.roulette) { if (await returnToWheel()) spin(); }
  else {
    rememberTime(); const scene = state.pool.find((item) => !state.seen.has(item.id));
    if (!scene) { $("video").pause(); phase("exhausted"); return; }
    state.seen.add(scene.id); state.history.splice(state.index + 1); state.history.push({ scene, time: 0 }); state.index++; playCurrent();
  }
}
$("launch").onclick = () => launch(); $("play-lane").onclick = () => launch(false);
$("next-scene").onclick = next;
$("previous").onclick = () => { if (state.phase !== "playing" || state.index < 1) return; rememberTime(); state.index--; playCurrent(); };
$("exit").onclick = exit; $("return").onclick = exit;
$("experience").addEventListener("cancel", (event) => { event.preventDefault(); exit(); });
$("restart").onclick = () => { state.seen.clear(); state.history = []; state.index = -1; phase("idle"); spin(true); };
$("mute").onclick = () => {
  muted = !muted; syncMute(); enableAudio();
  try { localStorage.setItem("curator-roulette-muted", String(muted)); } catch { /* Optional preference. */ }
};
$("pause").onclick = () => {
  const video = $("video");
  if (video.paused) video.play().then(() => { $("playback-error").hidden = true; }).catch(() => { announce("Playback unavailable. Try Next."); });
  else video.pause();
  wake();
};
$("video").addEventListener("play", () => { $("pause").textContent = "Pause"; $("pause").setAttribute("aria-label", "Pause playback"); });
$("video").addEventListener("pause", () => { $("pause").textContent = "Play"; $("pause").setAttribute("aria-label", "Resume playback"); wake(); });
$("video").addEventListener("ended", next);
$("video").addEventListener("error", () => {
  if (state.phase !== "playing") return;
  $("playback-error").textContent = "This sample clip could not load. Try Next or return to recommendations.";
  $("playback-error").hidden = false; wake();
});
$("video").addEventListener("timeupdate", () => {
  const video = $("video"); if (!Number.isFinite(video.duration)) return;
  $("seek").value = video.currentTime / video.duration * 100;
  $("remaining").textContent = `0:${String(Math.ceil(video.duration - video.currentTime)).padStart(2, "0")}`;
});
$("seek").oninput = () => { const video = $("video"); if (Number.isFinite(video.duration)) video.currentTime = video.duration * Number($("seek").value) / 100; wake(); };
$("fullscreen").onclick = async () => {
  try { if (document.fullscreenElement) await document.exitFullscreen(); else await $("stage").requestFullscreen(); }
  catch { announce("Fullscreen is unavailable in this browser."); }
};
$("stage").addEventListener("pointermove", wake); $("stage").addEventListener("pointerdown", wake); $("stage").addEventListener("keydown", wake);
document.querySelectorAll(".lane").forEach((button) => button.onclick = () => {
  state.lane = button.dataset.lane; state.pool = poolFor(state.lane);
  document.querySelectorAll(".lane").forEach((lane) => { lane.classList.toggle("active", lane === button); lane.setAttribute("aria-pressed", String(lane === button)); });
  renderCards();
});
syncMute(); renderCards();
