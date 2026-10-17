# Stash-box endpoints and ThePornDB follow-up

## Compatible endpoints

The endpoint setting uses servers already configured in Stash. StashDB remains the
default. Changing the selection invalidates the discovery and local-match caches;
opening Expand queues preparation and hides candidates from the previous source.
Successful preparation replaces the rebuildable discovery cache atomically.

External payloads retain their source for links. Shortlists are isolated by endpoint
(migration 42), including when providers share an entity ID. Legacy entries belong
to StashDB. Whisparr is restricted to StashDB selection and StashDB scene payloads.

Authenticated FansDB probes passed scene, performer and taxonomy queries, structured
filters, pagination and trending/popularity queries. JAVStash's live public schema
matches the relevant contract; authenticated discovery still needs verification.
The original request is [forum post 23](https://discourse.stashapp.cc/t/stash-curator/17689/23).

## Next commit: ThePornDB REST support

The configured ThePornDB Stash-box endpoint was tested. Its GraphQL searchScene and
findScene operations work, but queryScenes returned a null scene list in the tested
discovery requests. Filters use strings rather than Stash-box criterion objects,
and queryTagCategories is absent. The current implementation reports an unsupported
discovery schema before constructing large filter requests.

Read-only REST probes succeeded with the existing provider key as a Bearer token.
Scene listing and pagination worked; a nonexistent performer filter returned no
scenes. A sampled scene UUID was shared between REST and GraphQL.

Use the [official API specification](https://api.theporndb.net/specs?openapi.json).
The next implementation needs to:

- Translate discovery filters and pagination into REST requests.
- Normalize scenes, images, hashes and performer attributes for the existing scorer.
- Distinguish UUIDs from the numeric scene, performer, site and tag IDs used in filters.
- Handle missing tag categories without importing another provider's taxonomy.
- Verify owned-scene matching, links, shortlists, result limits and missing attributes.
- Keep Whisparr disabled for ThePornDB.

Prefer adapting retrieval and normalization to the existing scoring flow. REST
support is not included in the compatible-endpoint change.
