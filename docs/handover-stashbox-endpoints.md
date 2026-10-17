# Stash-box endpoints and ThePornDB follow-up

## Compatible endpoints

The endpoint setting uses servers already configured in Stash. Its dropdown shows
configured names, falling back to the hostname when unnamed. StashDB remains the
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

## Separate commit: ThePornDB REST support

The configured ThePornDB Stash-box endpoint was tested. Its GraphQL searchScene and
findScene operations work, but queryScenes returned a null scene list in the tested
discovery requests. Filters use strings rather than Stash-box criterion objects,
and queryTagCategories is absent. The compatible-endpoint commit reports an unsupported
discovery schema before constructing large filter requests.

Read-only REST probes succeeded with the existing provider key as a Bearer token.
Scene listing and pagination worked; a nonexistent performer filter returned no
scenes. A sampled scene UUID was shared between REST and GraphQL.

The separate REST adapter translates the existing discovery queries and normalizes
responses for the existing scorer. Its native implementation is `core/theporndb.go`;
the Python oracle is `curator/theporndb.py`. The configured key is reused as a Bearer
token for `https://api.theporndb.net`; it is never sent to the browser.

REST scenes, parent performers, sites and tags share GraphQL UUIDs. Scene filters
require numeric parent-performer, site and tag IDs. Site performer profiles resolve
to their parent UUID when linked. Unlinked profiles retain their own UUID and website
route, but have no supported scene filter and return no Performer Hunt results.
Unknown filter IDs never result in an unfiltered request.

Virtual pages preserve the callers' limits over the REST API's 100-row page cap.
There is no trustworthy updated-at filter; refresh falls back to the complete
configured discovery window. Taxonomy is a flat tag list with no provider categories.
Relevance and profile-similarity retrieval feed the existing scorer; the latter is
not a co-star query. Whisparr remains disabled for this provider.

The [official API specification](https://api.theporndb.net/specs?openapi.json) differs
from live validation: sort values use lowercase (`asc_name`, `most_relevant`), while
gender and ethnicity use title case (`Female`, `Caucasian`). Synthetic shared fixtures
cover normalization, filters, pagination and complete backend operation parity.

Identity lookups run concurrently and share in-flight results for duplicate IDs.
Discovery starts with the top 16 library performers, chases at most four favorites
with four additions each, and caps the final performer seeds at 32 and studio seeds
at eight. Numeric identity mappings persist for seven days; the tag list for 30 days,
in `data/theporndb-identities.json`. The cache contains no API keys or full profiles.
Search and scene responses also populate these mappings, avoiding redundant lookups.
Each operation starts REST requests at most once per second, shares a four-request
limit and a cooldown after HTTP 429. Requests retry up to three times, respecting
Retry-After seconds or waiting 60 seconds when the header is absent. A terminal
lookup error stops queued filter lookups.

Initial bulk-ID live probes hit provider rate limits. The bounded revision passes
the automated gates and a limited live cold/warm refresh check. The endpoint dropdown
marks ThePornDB as having limited support and explains the slower refreshes, potentially
missing thumbnails, and unavailable Whisparr integration. Some primary image URLs
returned 404 while alternate URLs worked; external cards, thumbnail tiles, and cast
images now try each distinct available URL on failure. Images remain blank when no
working URL is available. External GraphQL discovery requests allow 90 seconds;
local Stash requests retain the 30-second timeout. No automatic retries are added.

The REST adapter has been installed for manual testing. The live check used a
reduced candidate limit; default-size and sustained workloads are not verified.
