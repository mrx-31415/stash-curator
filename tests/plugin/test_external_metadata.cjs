const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../plugin/stash-curator.js"), "utf8");
const React = {
  Fragment: "fragment",
  createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat(Infinity).filter(Boolean) }),
  useState: (initial) => [initial, () => {}],
};
const context = {
  React, URL, window: {}, NavLink: "NavLink", Button: "Button", ButtonGroup: "ButtonGroup",
  FontAwesomeIcon: "Icon", faTag: "tag", faUser: "user",
  libraries: { Bootstrap: { Overlay: "Overlay", Popover: "Popover" } },
  Api: { components: {}, register: { component: (_, component) => component } },
  transformComponentProps: (_, props) => props,
  useCuratorActivity: () => {}, utilityBar: () => null,
  EvidenceScore: "EvidenceScore", FindSceneReason: "FindSceneReason", ExternalActions: "ExternalActions",
  FindThumbnail: "FindThumbnail", PerformerHuntLink: "PerformerHuntLink",
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function stashboxEntityURL("), source.indexOf("  const ExternalCard =")), context);
const ExternalCard = vm.runInContext(source.slice(source.indexOf("  const ExternalCard ="), source.indexOf("  const SourceReference =")) + "\nExternalCard;", context);
function nodes(node) {
  return node && typeof node === "object" ? [node, ...(node.children || []).flatMap(nodes)] : [];
}
const people = [
  { id: "remote-1", name: "Local person", curator_local: { id: "local-42" } },
  { id: "remote-2", name: "Remote person" },
  { id: "remote-3", name: "Another person" },
];
const payload = { title: "Example scene", curator_endpoint: "https://example.test/graphql", studio: { id: "studio-1", name: "Example studio" }, release_date: "2026-10-01", performers: people.map((performer) => ({ performer })), tags: [{ id: "tag-1", name: "First tag" }, { id: "tag-2", name: "Second tag" }, { id: "tag-3", name: "Third tag" }] };
const props = { kind: "scene", item: { id: "scene-1", score: 0.6, sources: [], payload } };

// Ordinary themes keep the original metadata controls and studio overlay.
let card = nodes(ExternalCard(props));
assert.ok(card.some((node) => node.props.className === "curator-external-studio-overlay"));
assert.ok(card.find((node) => node.type === "EvidenceScore" && node.props.metadataContent));
assert.ok(!card.some((node) => node.type === context.ExternalMetadataRow));

context.window.Sticky = { cards: { formatDate: () => "Oct 2026" } };
card = nodes(ExternalCard(props));
assert.ok(card.some((node) => node.props.className === "sticky-date" && node.children[0] === "Oct 2026"));
assert.equal(card.find((node) => node.type === context.ExternalStudioLink).props.payload, payload);
assert.ok(!card.some((node) => node.props.className === "curator-external-studio-overlay"));
assert.equal(card.filter((node) => node.type === "EvidenceScore" && node.props.scoreHeadline).length, 1);
assert.ok(!card.some((node) => node.type === "EvidenceScore" && node.props.metadataContent));
assert.equal(card.find((node) => node.props.className === "card-section").children[2].props.className, "curator-card-affinity");
assert.equal(card.filter((node) => node.type === context.ExternalMetadataRow).length, 2);
assert.equal(ExternalCard({ ...props, thumbnails: true }).type, "FindThumbnail");
context.window.Sticky.off = true;
assert.ok(nodes(ExternalCard(props)).some((node) => node.props.className === "curator-external-studio-overlay"));
context.window.Sticky = { cards: {} };
assert.ok(nodes(ExternalCard(props)).some((node) => node.props.className === "curator-external-studio-overlay"));

// Cached rows without studio images keep a name; failed logos do too.
assert.equal(context.ExternalStudioLink({ payload }).children[0], "Example studio");
let failed = false;
React.useState = () => [failed, (value) => { failed = value; }];
const logoPayload = { ...payload, studio: { ...payload.studio, images: [{ url: "https://example.test/logo.png" }, { url: "https://example.test/logo-2.png" }] } };
let studio = context.ExternalStudioLink({ payload: logoPayload });
assert.equal(studio.props.href, "https://example.test/studios/studio-1");
const logo = studio.children[0];
assert.equal(logo.props.src, "https://example.test/logo.png");
assert.equal(logo.props.alt, "Example studio");
const image = { src: logo.props.src, getAttribute() { return this.src; }, style: {} };
logo.props.onError({ currentTarget: image });
assert.equal(image.src, "https://example.test/logo-2.png");
assert.equal(failed, false);
logo.props.onError({ currentTarget: image });
assert.equal(failed, true);
assert.equal(context.ExternalStudioLink({ payload: logoPayload }).children[0], "Example studio");

// Keep local IDs on local links and external IDs on the selected provider.
let anchor = null;
React.useState = () => [anchor, (value) => { anchor = value; }];
const rowProps = { payload, items: people, kind: "performer" };
let row = nodes(context.ExternalMetadataRow(rowProps));
assert.equal(row.find((node) => node.type === "NavLink").props.to, "/performers/local-42");
const remote = row.find((node) => node.type === "a");
assert.equal(remote.props.href, "https://example.test/performers/remote-2");
assert.equal(remote.props.target, "_blank");
assert.equal(remote.props.rel, "noreferrer");
assert.equal(row.filter((node) => ["NavLink", "a"].includes(node.type)).length, 2);
row.find((node) => node.type === "Button").props.onClick({ currentTarget: {} });
row = nodes(context.ExternalMetadataRow(rowProps));
assert.equal(row.find((node) => node.type === "Overlay").props.rootClose, true);
assert.ok(row.some((node) => node.props.href === "https://example.test/performers/remote-3"));
row.find((node) => node.type === "Overlay").props.onHide();
assert.equal(anchor, null);
assert.equal(context.ExternalMetadataRow({ ...rowProps, items: [] }), null);

row = nodes(context.ExternalMetadataRow({ payload, items: payload.tags, kind: "tag" }));
assert.ok(row.some((node) => node.props.href === "https://example.test/tags/tag-1"));
assert.equal(row.find((node) => node.type === "Button").props["aria-label"], "Show 1 more tag");
