# Changelog

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
