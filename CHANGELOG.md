# Changelog

## [0.15.0](https://github.com/mrx-31415/stash-curator/compare/v0.14.0...v0.15.0) (2026-08-20)


### Features

* add the Dormant lane (lane redesign stage 3) ([cf4d185](https://github.com/mrx-31415/stash-curator/commit/cf4d18561aee0b77adefc4106381dd49ec0d6008))
* **core:** return build memory to the OS when the daemon goes idle ([5cc7d4f](https://github.com/mrx-31415/stash-curator/commit/5cc7d4f11bd9abbea7df3a41c03fb8ff46cda50a))
* **core:** run the background worker at low CPU and I/O priority ([7434743](https://github.com/mrx-31415/stash-curator/commit/743474389f8a419f37da712634d39cb2b1be7f12))
* replace the Adventure lane with Blind Spots (lane redesign stage 2) ([3a9d26a](https://github.com/mrx-31415/stash-curator/commit/3a9d26a27a1cc61a7435f11fb965604f985d3a71))
* replace the Discover lane with Stretch (lane redesign stage 1) ([eaecc5f](https://github.com/mrx-31415/stash-curator/commit/eaecc5f229b1bcc8a7f57038bd5e8f36b7b20dbb))
* route the Blind Spots breadth-ceiling signal to pruning (lane redesign stage 4) ([e5804e0](https://github.com/mrx-31415/stash-curator/commit/e5804e0f84d177920bf106c71a92ae9a5d5365d2))


### Bug Fixes

* fail closed when worker coordination breaks ([a6449be](https://github.com/mrx-31415/stash-curator/commit/a6449be9babb8c0e15b690492352ae063713ee38))
* **model:** bound score components without collapsing ordering at the cap ([b40f397](https://github.com/mrx-31415/stash-curator/commit/b40f3971be69222d97200e8d70855574abc7c1b8))
* **model:** stop pairwise pick confidence saturating at the ceiling ([f312768](https://github.com/mrx-31415/stash-curator/commit/f3127687823bc783abfcba59f3e3639c2ff9051e))
* reject stale daemon pid reuse ([5ae7f76](https://github.com/mrx-31415/stash-curator/commit/5ae7f761559c03e70a6f653462e95091a171c885))
* rotate daemon after plugin updates ([49af01c](https://github.com/mrx-31415/stash-curator/commit/49af01ccd8ad77d35c09c77696f6e55ad8c831fd))
* tolerate short-stage perf jitter ([3ec27cd](https://github.com/mrx-31415/stash-curator/commit/3ec27cd6f7d9aafe268a770c328d48c91cf80836))


### Documentation

* correct the lane-redesign doc's migration number and pruning framing ([5eecf42](https://github.com/mrx-31415/stash-curator/commit/5eecf4294bd55a415220c1e4fdd7348dd65b746a))

## [0.14.0](https://github.com/mrx-31415/stash-curator/compare/v0.13.0...v0.14.0) (2026-08-18)


### Features

* **curate:** side-menu sections, endless Stream, ties, in-context sentiment ([255342a](https://github.com/mrx-31415/stash-curator/commit/255342a87d2ee187bdd503965ae8e18d9d1ce2d2))
* **model:** pairwise affinity accumulation, coverage normalization, drop ELO ([2a7cddc](https://github.com/mrx-31415/stash-curator/commit/2a7cddc673106f5353d2461ae512d4d5ab4e1ccc)), closes [#165](https://github.com/mrx-31415/stash-curator/issues/165)


### Bug Fixes

* **curate:** apply picks to the model, keep them out of absolute appeal ([7ff8991](https://github.com/mrx-31415/stash-curator/commit/7ff8991dc96533d41e0ee8e419bdeee9e2d3d6f4)), closes [#163](https://github.com/mrx-31415/stash-curator/issues/163)
* **curate:** ship ELO table drop as migration 0033 ([2fe5d6f](https://github.com/mrx-31415/stash-curator/commit/2fe5d6fe3a74f40bd9ec9c370fbb1865de754e24))

## [0.13.0](https://github.com/mrx-31415/stash-curator/compare/v0.12.0...v0.13.0) (2026-08-17)


### Features

* automatic model updates and play sync in the background worker ([802ac0d](https://github.com/mrx-31415/stash-curator/commit/802ac0d18d6d8eadd54533d7716f068034bcca7c))
* background task worker with queue, detached daemon, and live progress ([2e30e6a](https://github.com/mrx-31415/stash-curator/commit/2e30e6aaf71d0d8c82956bdf5f991c84dc83a8e7))
* **plugin:** in-plugin Settings panel under Manage ([#158](https://github.com/mrx-31415/stash-curator/issues/158)) ([fc0c1a2](https://github.com/mrx-31415/stash-curator/commit/fc0c1a2d37f264cfffbafbca9fcbe79908ed2d05))
* schedule hour-of-day anchors, Manage list scroll, and text-in-toggle switches ([63bfb17](https://github.com/mrx-31415/stash-curator/commit/63bfb174fd6128f919f43b2ab47dd83d96498ffe))
* scheduled background tasks for expand refresh, sync-build, and backup ([042cf65](https://github.com/mrx-31415/stash-curator/commit/042cf65d3865a6bf478c984444ef53b58f8d1a2f))


### Bug Fixes

* **plugin:** Curator Tasks section as the worker task-feedback surface ([cf26775](https://github.com/mrx-31415/stash-curator/commit/cf2677529be2f21a03b1012a9dbc0f5bbe40db44))
* **plugin:** let Enter add the top match in tag/performer/studio filter inputs ([#156](https://github.com/mrx-31415/stash-curator/issues/156)) ([adf6a11](https://github.com/mrx-31415/stash-curator/commit/adf6a11ac9e332a86c6c2921cc0a99a0b1e25847))
* **plugin:** resolve routeLocation scope in CuratorControls ([675e3ed](https://github.com/mrx-31415/stash-curator/commit/675e3ed93c8dc7db2e4338af84d141531107131a))
* **plugin:** scale card icons/text with card-size slider ([c2895ba](https://github.com/mrx-31415/stash-curator/commit/c2895ba291d90e7d381d434e40ee1e20f686c29f))

## [0.12.0](https://github.com/mrx-31415/stash-curator/compare/v0.11.0...v0.12.0) (2026-08-16)


### Features

* curation loop with pairwise picks and ELO-style feedback ([#147](https://github.com/mrx-31415/stash-curator/issues/147)) ([4375240](https://github.com/mrx-31415/stash-curator/commit/43752402c6c221eb2f15a3bc988876d8d74b3bda))
* **plugin:** close the [#150](https://github.com/mrx-31415/stash-curator/issues/150)/[#152](https://github.com/mrx-31415/stash-curator/issues/152) visual and UX redesign gap ([#155](https://github.com/mrx-31415/stash-curator/issues/155)) ([9ff74ea](https://github.com/mrx-31415/stash-curator/commit/9ff74eab5a02b5bd5d3bd7273b9bbd0d20364911))

## [0.11.0](https://github.com/mrx-31415/stash-curator/compare/v0.10.0...v0.11.0) (2026-08-13)


### Features

* sentiment-review surface with sort direction and appeal threshold ([#141](https://github.com/mrx-31415/stash-curator/issues/141)) ([79602bf](https://github.com/mrx-31415/stash-curator/commit/79602bf07c89c1ed4fd6ff415b4c24a4bb5faecc))

## [0.10.0](https://github.com/mrx-31415/stash-curator/compare/v0.9.2...v0.10.0) (2026-08-13)


### Features

* mirror derived artifact cache into backup storage ([#136](https://github.com/mrx-31415/stash-curator/issues/136)) ([2dcf5b2](https://github.com/mrx-31415/stash-curator/commit/2dcf5b218c2d2491497bb336a7261d4c9a499fd2))
* score-review op sorted by model appeal ([#138](https://github.com/mrx-31415/stash-curator/issues/138)) ([cbb1bfb](https://github.com/mrx-31415/stash-curator/commit/cbb1bfbcdf868a162d35ae1aa19204fc731070bd))


### Bug Fixes

* re-annotate expand candidates against current links at serve time ([#137](https://github.com/mrx-31415/stash-curator/issues/137)) ([2695973](https://github.com/mrx-31415/stash-curator/commit/26959733b66a89f316a20cb294b0478855de4296))
* URL carries full view state for expand/similar/history/prune; add score-review view ([#139](https://github.com/mrx-31415/stash-curator/issues/139)) ([9b5399e](https://github.com/mrx-31415/stash-curator/commit/9b5399efaf4398f74a350be308f91019832deaf0))

## [0.9.2](https://github.com/mrx-31415/stash-curator/compare/v0.9.1...v0.9.2) (2026-08-12)


### Performance Improvements

* batch artifact inserts into multi-row statements ([#132](https://github.com/mrx-31415/stash-curator/issues/132)) ([9821904](https://github.com/mrx-31415/stash-curator/commit/9821904174b7e8e243409c3fc7c3f803af08b13b))

## [0.9.1](https://github.com/mrx-31415/stash-curator/compare/v0.9.0...v0.9.1) (2026-08-12)


### Performance Improvements

* parallelize the similar op's independent reads on a read-only pool ([#130](https://github.com/mrx-31415/stash-curator/issues/130)) ([3e03ba8](https://github.com/mrx-31415/stash-curator/commit/3e03ba861e71954e87e9467adb90cb4a7f572df9))

## [0.9.0](https://github.com/mrx-31415/stash-curator/compare/v0.8.1...v0.9.0) (2026-08-12)


### Features

* instrument build stages with timings, memory, and a perf budget gate ([#128](https://github.com/mrx-31415/stash-curator/issues/128)) ([c9c2b5e](https://github.com/mrx-31415/stash-curator/commit/c9c2b5e9f7db60eff082c6558b02bc6f376d2a78))

## [0.8.1](https://github.com/mrx-31415/stash-curator/compare/v0.8.0...v0.8.1) (2026-08-12)


### Performance Improvements

* parallelize lane classification, scoring, feature construction, and the links walk ([#125](https://github.com/mrx-31415/stash-curator/issues/125)) ([b90a52b](https://github.com/mrx-31415/stash-curator/commit/b90a52b9db36d9b5a6e336a758d60cec0c899b07))
* switch SQLite to mattn/go-sqlite3 (cgo) and tune readonly artifact opens ([#127](https://github.com/mrx-31415/stash-curator/issues/127)) ([5b70838](https://github.com/mrx-31415/stash-curator/commit/5b70838c54f5f64526e367cb5bd453c83b92486d))

## [0.8.0](https://github.com/mrx-31415/stash-curator/compare/v0.7.0...v0.8.0) (2026-08-12)


### Features

* description-term ratings, remote term ranking, busy-lock retry, and task progress fixes ([45d48a8](https://github.com/mrx-31415/stash-curator/commit/45d48a8bacb3bcb7a564d8354cf8e9112c897482))

## [0.7.0](https://github.com/mrx-31415/stash-curator/compare/v0.6.0...v0.7.0) (2026-08-11)


### Features

* **backend:** port the frontend-parity ops and entity hook to the Go core (Slice 4) ([#114](https://github.com/mrx-31415/stash-curator/issues/114)) ([d6878c8](https://github.com/mrx-31415/stash-curator/commit/d6878c8fa0580d17aea8ca7eb9b04a1bbd413154))
* **backend:** port the network-layer ops and write-path handover (Slices 2–3) ([#108](https://github.com/mrx-31415/stash-curator/issues/108)) ([7d629c3](https://github.com/mrx-31415/stash-curator/commit/7d629c38de7f3b7f21ba8486c15cabc8772052f2))
* **backend:** port the write path, task modes, and model build to the Go core (Slice 3) ([#112](https://github.com/mrx-31415/stash-curator/issues/112)) ([24ca7b4](https://github.com/mrx-31415/stash-curator/commit/24ca7b42c2738dbabdd3b8e3ebcb78e8deecb778))
* multi-hop pagerank in the compiled core ([5cc231f](https://github.com/mrx-31415/stash-curator/commit/5cc231faaf804f27c4c06e1b04825abadeab1973))
* port raw transport and sidecar parity foundation to curator-core ([e2a0254](https://github.com/mrx-31415/stash-curator/commit/e2a0254f6e2c261e8412a3b64c7606f8f37fcfef))
* port the read-path interactive ops to curator-core ([b974b25](https://github.com/mrx-31415/stash-curator/commit/b974b25555d3fe3d615b124f8d6840e7a95ffea2))
* profile the compiled core stages inside the plugin trace ([e3a0d70](https://github.com/mrx-31415/stash-curator/commit/e3a0d70689b61084f2ea8c4e083a2d6a479550a5))
* record operation profiles in the ported backend ops ([ccdb3b7](https://github.com/mrx-31415/stash-curator/commit/ccdb3b75073f87cd4e09711cebab51ae5e0384f3))
* remove optional-deps venv — compiled core is now required ([031d16e](https://github.com/mrx-31415/stash-curator/commit/031d16e3f5bc6ef9d39786ffd5ddf5c56946edb8))
* run the installed plugin through the curator-core exec launcher ([e7a034c](https://github.com/mrx-31415/stash-curator/commit/e7a034c9aa69276c8064085ce2fccc9b822c538e))


### Bug Fixes

* close attachBuildSources rows before creating the temp views ([b30790e](https://github.com/mrx-31415/stash-curator/commit/b30790eeadd23c34a679d798ac93c4386cf5b04d))
* fall back to a plain-path attach when URI opens fail ([0ff1e04](https://github.com/mrx-31415/stash-curator/commit/0ff1e042488cf436568aa3882770aa14a8a248e0))
* fall back to a shared-lock attach when the immutable open fails ([996f3ba](https://github.com/mrx-31415/stash-curator/commit/996f3bad9131ed303dff369aff0722732a3105bd))
* pin backend connections to a single sqlite connection ([b172b56](https://github.com/mrx-31415/stash-curator/commit/b172b56d7ef9d2a271ff4fd079d6efba1f34ee69))


### Documentation

* add the Slice 4 handover (frontend parity and fallback removal) ([7fac931](https://github.com/mrx-31415/stash-curator/commit/7fac93128899e137f764d3d7b8f36dbb18796230))
* hand over the Slice-1 read-path backend port ([8c6e35c](https://github.com/mrx-31415/stash-curator/commit/8c6e35ca8f26add362733c874ff44d62bee6cdbf))
* mark the read-path backend port and exec launcher delivered ([ec8c766](https://github.com/mrx-31415/stash-curator/commit/ec8c76621ae296d13e4f4021d6b4ec713449a1a8))
* plan the full Go backend as a slice sequence ([#102](https://github.com/mrx-31415/stash-curator/issues/102)) ([0a4ba1a](https://github.com/mrx-31415/stash-curator/commit/0a4ba1acb16aeecebdaca1e6dae79c2ce6c479cd))
* reflect the merged Go backend and the tolerance-based differential gates ([190d206](https://github.com/mrx-31415/stash-curator/commit/190d2066cc51e6fd666965432151e913181acc42))

## [0.6.0](https://github.com/mrx-31415/stash-curator/compare/v0.5.1...v0.6.0) (2026-08-10)


### Features

* accelerate similarity stages with an optional compiled Go core ([3afcb54](https://github.com/mrx-31415/stash-curator/commit/3afcb54f8c245f85e88aafaee17bf435441a4b1d))
* make Expand refresh incremental ([c6f82d7](https://github.com/mrx-31415/stash-curator/commit/c6f82d763f07d95fa98b46f8ba0ab68aa27a740a))
* ship the compiled core as per-arch binaries in the plugin zip ([80650c2](https://github.com/mrx-31415/stash-curator/commit/80650c2680d5311e5db992076d0bc6024285f876))
* sync changed entities immediately via Stash hooks ([#90](https://github.com/mrx-31415/stash-curator/issues/90)) ([249d85e](https://github.com/mrx-31415/stash-curator/commit/249d85ebe0fd66fd6f6394fb3a2dc45a07a3e9a6))
* sync recent plays automatically after playback ([2fb9b2b](https://github.com/mrx-31415/stash-curator/commit/2fb9b2b3242ea616460cf0034148240b1e7e52e1))


### Bug Fixes

* batch eligibility probes and cache slate lane counts ([c22de23](https://github.com/mrx-31415/stash-curator/commit/c22de23cc499adaee0aedae6ebc38246c5ac0e04))
* fall back to full Expand refresh when StashDB lacks the updated_at filter ([2788049](https://github.com/mrx-31415/stash-curator/commit/27880495fdbcdb5fe0c15c49ca70ca37a308d5ee))
* keep StashDB similar cards from crashing the page ([2e168d7](https://github.com/mrx-31415/stash-curator/commit/2e168d71ebe332fbc6c20692b8d812c78a7e5166))


### Documentation

* clarify product behavior and onboarding ([10ead56](https://github.com/mrx-31415/stash-curator/commit/10ead56fb8f14e5461c7a26d042d49f605f646f1))
* describe incremental Expand refresh with fallback ([37f2de8](https://github.com/mrx-31415/stash-curator/commit/37f2de813fb8231c3c4bfbb169e5f2d8370c4557))
* record compiled-core Phase 2 delivery ([27fe6b7](https://github.com/mrx-31415/stash-curator/commit/27fe6b7429e5bae09048d6e338a66fb6e35f895a))

## [0.5.1](https://github.com/mrx-31415/stash-curator/compare/v0.5.0...v0.5.1) (2026-08-08)


### Bug Fixes

* clarify task progress display ([a41954c](https://github.com/mrx-31415/stash-curator/commit/a41954c9781086981d2ba15c6fb8e6f94a84cbcd))

## [0.5.0](https://github.com/mrx-31415/stash-curator/compare/v0.4.2...v0.5.0) (2026-08-08)


### Features

* consolidate task progress and tag rating controls ([ea68a86](https://github.com/mrx-31415/stash-curator/commit/ea68a86c087cd02dd28a485d97896a50df4b0a08))


### Bug Fixes

* broader expected phrases for taste/feedback/backups tabs ([812b9ce](https://github.com/mrx-31415/stash-curator/commit/812b9ce516e5f5891d7a1264f2d76b0072b5723a))
* hoist scoreBar to module scope for ExternalCard and ExpandPanel ([#78](https://github.com/mrx-31415/stash-curator/issues/78)) ([64f1679](https://github.com/mrx-31415/stash-curator/commit/64f1679daa3e2e5802527459c0c6e56d776cc131))
* use contextlib.suppress instead of bare try/except/pass ([ba9bb14](https://github.com/mrx-31415/stash-curator/commit/ba9bb14b76a219faf397e4c3a0f41b3ef6440cb4))
* use taxonomy aliases when matching external tags to local tags ([#80](https://github.com/mrx-31415/stash-curator/issues/80)) ([28d2897](https://github.com/mrx-31415/stash-curator/commit/28d289700a9f348bb97ced72c94ac2c5c249ed1b))

## [0.4.2](https://github.com/mrx-31415/stash-curator/compare/v0.4.1...v0.4.2) (2026-08-08)


### Bug Fixes

* sentiment button colors, expand setup button, and StashDB details field ([#76](https://github.com/mrx-31415/stash-curator/issues/76)) ([4ffe45b](https://github.com/mrx-31415/stash-curator/commit/4ffe45b0e588bd1058f37b8d889d69d7371d9f91))

## [0.4.1](https://github.com/mrx-31415/stash-curator/compare/v0.4.0...v0.4.1) (2026-08-08)


### Bug Fixes

* shorten Block button label and sort taste profile by sign then magnitude ([#74](https://github.com/mrx-31415/stash-curator/issues/74)) ([2db1394](https://github.com/mrx-31415/stash-curator/commit/2db13941523688f514a7423f1ae8403a6b2f9c71))

## [0.4.0](https://github.com/mrx-31415/stash-curator/compare/v0.3.0...v0.4.0) (2026-08-08)


### Features

* add hard Block / Never level for tag sentiment preferences ([#64](https://github.com/mrx-31415/stash-curator/issues/64)) ([a365806](https://github.com/mrx-31415/stash-curator/commit/a36580619ed9f25e978027fe16c68e5d08c20030))
* add Local toggle for StashDB similar scenes ([#63](https://github.com/mrx-31415/stash-curator/issues/63)) ([6388956](https://github.com/mrx-31415/stash-curator/commit/6388956227f351823d73e6780f742307b783ac20))
* add Local toggle for StashDB similar scenes ([#63](https://github.com/mrx-31415/stash-curator/issues/63)) ([11599df](https://github.com/mrx-31415/stash-curator/commit/11599df513bbc4b78dd3e0221b1c2be3c6c20827))
* add score_breakdown to Similar result details ([7012b76](https://github.com/mrx-31415/stash-curator/commit/7012b7687dcde76c9d618299f73a2d60a6e771ea))
* add score_breakdown to Similar result details ([88ad0b3](https://github.com/mrx-31415/stash-curator/commit/88ad0b31b80a2c834ec1e77a4885492dd207aacf))
* expand tag filters to include child tags (descendants) in Expand, Similar, and Performer Hunt ([#65](https://github.com/mrx-31415/stash-curator/issues/65)) ([474cdc0](https://github.com/mrx-31415/stash-curator/commit/474cdc0834a8f7329382427c4263673acfc491a1))
* multi-hop affinity with performer-collaboration graph ([dda4368](https://github.com/mrx-31415/stash-curator/commit/dda4368c7dce401b59c9145d69c8282434ee77fc))
* show scene descriptions on scene cards ([#66](https://github.com/mrx-31415/stash-curator/issues/66)) ([4149d05](https://github.com/mrx-31415/stash-curator/commit/4149d051da454556bab73f54933e057fe991e1ce))
* show score breakdown in Similar card ([7493137](https://github.com/mrx-31415/stash-curator/commit/7493137cffda553a9fb59c33d82ade10f878e789))
* show score breakdown in Similar card ([c6b6d1e](https://github.com/mrx-31415/stash-curator/commit/c6b6d1e63dec9c53879f16ea8e02d4b98678d6f4))
* TF-IDF description terms as content features ([087ea82](https://github.com/mrx-31415/stash-curator/commit/087ea82d3632386c67236fcfa52bef238c7fc2ad))
* visual score bar, influence chips, and multi-hop path labels ([7ca6809](https://github.com/mrx-31415/stash-curator/commit/7ca6809a0111056e5335b8b2cbe4466512b7c473))
* visual score bar, influence chips, and multi-hop path labels ([c214fb8](https://github.com/mrx-31415/stash-curator/commit/c214fb8b25a3a81d20ad280ad1ab9e5570e1f78e))


### Bug Fixes

* boost description term weight in content vectors ([a3885b1](https://github.com/mrx-31415/stash-curator/commit/a3885b1b822025688cea7b28facd5657db0a1205))


### Performance Improvements

* read precomputed performer edges instead of O(n^2) loop ([e0b1d41](https://github.com/mrx-31415/stash-curator/commit/e0b1d41593bfda297a7d22fc0c5e5f1b1a1a097b))

## [0.3.0](https://github.com/mrx-31415/stash-curator/compare/v0.2.0...v0.3.0) (2026-08-07)


### Features

* browse a similar performer's full catalog in Performer Hunt ([6b3f72e](https://github.com/mrx-31415/stash-curator/commit/6b3f72e6ff35d0985cb877d6c36b14b49f7291cc))


### Bug Fixes

* gate remote scene performer credit on content overlap ([16c2300](https://github.com/mrx-31415/stash-curator/commit/16c2300c593171eda7422a1832d4a7455cef8739))
* let remote performer similarity include library performers ([a92efc8](https://github.com/mrx-31415/stash-curator/commit/a92efc8a7e60bcaca0f10d6d9307aefaf2cee082))
* make library performers prominent in remote similarity results ([a5ab524](https://github.com/mrx-31415/stash-curator/commit/a5ab524b0fd7ad9cc1d7c62a24746b937bc1dd54))
* retrieve closer remote similar matches ([#54](https://github.com/mrx-31415/stash-curator/issues/54)) ([20a2465](https://github.com/mrx-31415/stash-curator/commit/20a24655ace140f1b23d099147dfb73c4df9ff39))
* show similar source switch up front and keep reference portrait ([2267282](https://github.com/mrx-31415/stash-curator/commit/22672820e024e2d64ce223dafab78ad0715489a6))


### Performance Improvements

* fetch only the requested scene in inspector and explain lookups ([72d7717](https://github.com/mrx-31415/stash-curator/commit/72d7717521580a1190bf192842de2bff9a4744fe))

## [0.2.0](https://github.com/mrx-31415/stash-curator/compare/v0.1.0...v0.2.0) (2026-08-06)


### Features

* automate releases with release-please and one version source ([fa8fe6f](https://github.com/mrx-31415/stash-curator/commit/fa8fe6f6678f1998c0db442e0c4aab8a329157e5))


### Bug Fixes

* let release-please bump the runtime __version__ ([eb47945](https://github.com/mrx-31415/stash-curator/commit/eb479451322eed8c3028516ec79cb744294608d2))
