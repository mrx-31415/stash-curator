// Synthetic second plugin: change argument counts and return theme-style arrays.
// Installed before Stash publishes PluginApi, so it precedes Curator registration.
(() => {
  const counts = window.__curatorPatchCounts = {};
  let currentApi;
  Object.defineProperty(window, "PluginApi", {
    configurable: true,
    get: () => currentApi,
    set: (api) => {
      currentApi = api;
      const { React } = api;
      const original = Object.fromEntries(["before", "instead", "after"].map((kind) => [kind, api.patch[kind].bind(api.patch)]));
      const surfaces = ["MainNavBar.MenuItems", "ScenePlayer", "HoverPopover", "FilteredSceneList",
        "FilteredPerformerList", "SceneList", "ScenePage", "PerformerPage", "SceneCard.Details",
        "SceneCard.Popovers", "SceneCard.Overlays", "PerformerCard.Overlays"];
      const arraySurfaces = new Set(["SceneCard.Details", "SceneCard.Popovers", "SceneCard.Overlays", "PerformerCard.Overlays"]);
      const themed = new Set();
      for (const name of surfaces) {
        original.before(name, (props) => window.__curatorExtraContext
          ? [props, { companion: true }, "companion-argument"] : [props]);
      }
      original.after("MainNavBar.MenuItems", (props, ...args) => {
        const result = args[args.length - 1];
        return React.cloneElement(result, {}, result.props.children,
          React.createElement("a", { href: "/scenes", "data-patch-companion": "navbar" }, "Companion"));
      });
      for (const kind of ["before", "instead", "after"]) {
        api.patch[kind] = (name, callback) => {
          original[kind](name, function (...args) {
            counts[name] = (counts[name] || 0) + 1;
            return callback.apply(this, args);
          });
          // Register inside Curator's continuation, so Curator receives an intact array.
          if (arraySurfaces.has(name) && !themed.has(name)) {
            themed.add(name);
            original.instead(name, function (...args) {
              const next = args.pop();
              const result = next.apply(this, args);
              return [
                React.createElement(React.Fragment, { key: "native" }, result,
                  React.createElement("span", { "data-patch-native": name })),
                React.createElement("span", { key: "companion", "data-patch-companion": name }),
              ];
            });
          }
        };
      }
    },
  });
})();
