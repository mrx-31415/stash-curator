const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
let patch;
const context = {
  URLSearchParams,
  window: { location: { pathname: "/plugins/stash-curator" } },
  Api: { patch: { before: (name, callback) => { assert.equal(name, "HoverPopover"); patch = callback; } } },
  React: {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    Children: {
      map: (children, callback) => children == null ? children : (Array.isArray(children) ? children : [children]).map(callback),
      toArray: (children) => Array.isArray(children) ? [...children] : [children],
    },
    isValidElement: (element) => Boolean(element?.type),
    cloneElement: (element, props, children) => ({ ...element, props: { ...element.props, ...props, children } }),
  },
  NavLink: "NavLink", FontAwesomeIcon: "Icon", faCrosshairs: "crosshairs",
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function PerformerHuntLink("), source.indexOf("  const ExternalCard =")), context);
const performer = { id: "17", name: "A & B / C" };
function checkLink(props, external) {
  const link = context.PerformerHuntLink(props);
  const query = new URL(link.props.to, "http://example.test").searchParams;
  assert.equal(query.get("view"), "hunt");
  assert.equal(query.get("performer"), props.performer.id);
  assert.equal(query.get("label"), props.performer.name);
  assert.equal(query.get("ext"), external ? "1" : null);
  assert.equal(link.props.title, link.props["aria-label"]);
  assert.equal(link.props.children.length, 1, "link must be icon only");
  let stopped = false;
  link.props.onClick({ stopPropagation: () => { stopped = true; } });
  assert(stopped);
}
checkLink({ performer }, false);
checkLink({ performer: { id: "stashdb-uuid", name: performer.name }, external: true }, true);

const image = { type: "a", props: { href: "/performers/17", className: "performer-tag col m-auto zoom-2" } };
const name = { type: "PerformerLink", props: { performer, linkType: "scene" } };
const row = { type: "div", props: { children: [image, name], className: "performer-tag-container row" } };
const props = { className: "performer-count", content: [row], children: "trigger", leaveDelay: 100 };
const extra = {};
const patched = patch(props, extra);
assert.equal(patched[1], extra);
assert.equal(patched[0].children, "trigger");
assert.equal(patched[0].leaveDelay, 100);
const children = patched[0].content[0].props.children;
assert.equal(children[0].props.className, "curator-performer-image-actions");
assert.equal(children[0].props.children[0], image, "preserve the image's profile link");
assert.equal(children[0].props.children[1].type, context.PerformerHuntLink);
assert.equal(children[0].props.children[1].props.performer, performer);
assert.equal(children[1], name, "leave the name and its full width unchanged");
assert.equal(row.props.children[1], name, "do not mutate native content");
assert.equal(patch({ ...props, className: "tag-count" })[0].content, props.content);
context.window.location.pathname = "/scenes";
assert.equal(patch(props)[0], props, "ordinary Stash browsing must stay unchanged");

// Exercise the actual external cast markup, including a locally matched StashDB performer.
Object.assign(context, {
  kind: "scene", ButtonGroup: "ButtonGroup", faTag: "tag", faUser: "user", tags: [],
  cast: [{ id: "stashdb-uuid", name: performer.name, curator_local: { id: "17" } }],
  metadataPopover: (id, icon, label, count, content) => ({ id, content }),
});
context.people = context.cast;
vm.runInContext(source.slice(source.indexOf("    const metadataControls ="), source.indexOf("    async function addToWhisparr()")) + "\nthis.metadataControls = metadataControls;", context);
const externalRow = context.metadataControls.props.children[1].content.props.children[0][0];
assert.equal(externalRow.props.children[0].props.className, "curator-performer-image-actions");
const externalActions = externalRow.props.children[0].props.children;
assert.equal(externalActions[0].props.to, "/performers/17");
checkLink(externalActions[1].props, true);
assert.equal(externalRow.props.children[1].props.to, "/performers/17");
assert.equal(externalRow.props.children[1].props.children[0], performer.name);
const css = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.css"), "utf8");
const iconStyle = css.slice(css.indexOf(".curator-performer-hunt {"), css.indexOf(".curator-performer-hunt:hover"));
assert.match(iconStyle, /position: absolute/);
assert.match(iconStyle, /color: var\(--curator-hue-hunt\)/);
console.log("PASS: Hunt icons overlay images without taking name width or changing profile links");
