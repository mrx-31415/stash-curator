(function (root) {
  "use strict";

  // Incognito: a navbar toggle that stops this browser from recording plays.
  //
  // Stash's player records activity through its video.js `trackActivity` plugin, which
  // sends sceneSaveActivity (resume point, play duration) and sceneAddPlay (play count,
  // history) only while enabled. Incognito wraps that plugin's setEnabled so it stays
  // disabled while incognito is on and returns to Stash's own setting when it is off.
  // Manual edits (the play-count button, the History tab) are untouched.
  //
  // Other plugins read the state through `window.StashIncognito.isActive()` and the
  // `stash-incognito` window event (detail: { active }).

  const STORAGE_KEY = "stash-incognito:active";
  const EVENT = "stash-incognito";
  const WRAPPED = "__stashIncognitoWrapped";
  const REQUESTED = "__stashIncognitoRequested";

  function readStored(storage) {
    try {
      return storage?.getItem(STORAGE_KEY) === "1";
    } catch (_) {
      return false;
    }
  }

  function createIncognito(options = {}) {
    const storage = options.storage === undefined ? root.localStorage : options.storage;
    const findPlayers = options.findPlayers || (() => []);
    let active = readStored(storage);
    const trackers = new Set();

    function apply(tracker) {
      tracker[WRAPPED].call(tracker, tracker[REQUESTED] && !active);
    }

    // Wrapping the prototype covers every later player, since the ScenePlayer enables
    // tracking through setEnabled after it creates one.
    function guard(tracker) {
      if (!tracker || typeof tracker !== "object") return false;
      const proto = Object.getPrototypeOf(tracker);
      if (!proto[WRAPPED]) {
        const original = proto.setEnabled;
        if (typeof original !== "function") return false;
        Object.defineProperty(proto, WRAPPED, { value: original });
        proto.setEnabled = function (enabled) {
          trackers.add(this);
          this[REQUESTED] = !!enabled;
          return original.call(this, !!enabled && !active);
        };
      }
      if (!trackers.has(tracker)) {
        trackers.add(tracker);
        // A tracker found after Stash enabled it keeps Stash's choice for when incognito ends.
        if (!(REQUESTED in tracker)) tracker[REQUESTED] = tracker.enabled === true;
        apply(tracker);
      }
      return true;
    }

    function scan() {
      let guarded = false;
      for (const player of findPlayers()) {
        if (!player || player.isDisposed?.() || !player.usingPlugin?.("trackActivity")) continue;
        guarded = guard(player.trackActivity()) || guarded;
      }
      return guarded;
    }

    function set(next) {
      next = !!next;
      if (next === active) return active;
      active = next;
      try {
        if (active) storage?.setItem(STORAGE_KEY, "1");
        else storage?.removeItem(STORAGE_KEY);
      } catch (_) {
        // Without storage the toggle still holds for this page load.
      }
      scan();
      for (const tracker of trackers) {
        if (tracker.player === null) trackers.delete(tracker);
        else apply(tracker);
      }
      root.dispatchEvent?.(new root.CustomEvent(EVENT, { detail: { active } }));
      return active;
    }

    return {
      isActive: () => active,
      set,
      toggle: () => set(!active),
      scan,
      guard,
    };
  }

  function stashPlayers() {
    const players = new Set();
    try {
      const current = root.PluginApi?.utils?.InteractiveUtils?.getPlayer?.();
      if (current) players.add(current);
    } catch (_) {}
    for (const element of root.document.querySelectorAll(".video-js")) {
      if (element.player) players.add(element.player);
    }
    return players;
  }

  function install() {
    const api = root.PluginApi;
    const { React } = api;
    const { Button } = api.libraries.Bootstrap;
    const { FontAwesomeIcon } = api.libraries.ReactFontAwesome;
    const { faUserSecret } = api.libraries.FontAwesomeSolid;

    const incognito = createIncognito({ findPlayers: stashPlayers });
    root.StashIncognito = { isActive: incognito.isActive, set: incognito.set, toggle: incognito.toggle };

    // Players appear as scene pages mount; each check is one class lookup.
    const observer = new root.MutationObserver(() => incognito.scan());
    observer.observe(root.document.body, { childList: true, subtree: true });
    incognito.scan();

    function IncognitoButton() {
      const [active, setActive] = React.useState(incognito.isActive());
      React.useEffect(() => {
        const update = (event) => setActive(!!event.detail?.active);
        root.addEventListener(EVENT, update);
        setActive(incognito.isActive());
        return () => root.removeEventListener(EVENT, update);
      }, []);
      const title = active ? "Incognito on: plays are not recorded" : "Incognito off: plays are recorded";
      return React.createElement(
        Button,
        {
          className: `minimal d-flex align-items-center align-self-center mr-2 incognito-toggle${active ? " active" : ""}`,
          title,
          "aria-label": title,
          "aria-pressed": active,
          onClick: () => incognito.toggle(),
        },
        React.createElement(FontAwesomeIcon, { icon: faUserSecret })
      );
    }

    // Before-hooks may change the argument count; the rendered children are always last.
    api.patch.after("MainNavBar.UtilityItems", function (...args) {
      const result = args[args.length - 1];
      return React.createElement(React.Fragment, null, React.createElement(IncognitoButton, { key: "incognito" }), result);
    });
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { createIncognito, STORAGE_KEY, EVENT };
  } else if (root.PluginApi) {
    install();
  }
})(typeof window !== "undefined" ? window : globalThis);
