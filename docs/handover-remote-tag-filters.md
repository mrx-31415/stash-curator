# Remote tag filters handover

The change adds local + cached StashDB tag search to Include/Exclude
tags in Expand, Performer Hunt, and StashDB Similar. Library Similar and
recommendations keep local-only search. Names and aliases use the existing
taxonomy and filtering flow; no migration or new dependency is needed.

Implementation: [picker](../plugin/stash-curator.js),
[Go search](../core/frontend.go), [dispatch](../core/backend.go),
[Python oracle](../curator/api.py), [oracle dispatch](../plugin/backend.py).
The search returns eight matches, labels their source, keeps local duplicates,
and requests an Expand cache refresh when the StashDB catalog is absent.

Regression checks: [backend](../tests/core/test_backend_slice2.py) and
[picker](../tests/plugin/test_remote_tag_filters.cjs), invoked by
[pytest](../tests/plugin/test_remote_tag_filters.py).
Public behavior is documented in [Using Curator](using-curator.md).

Local worktree verification: 239 backend comparisons and three focused checks passed;
`scripts/verify full` passed with 653 tests, 25 deselected, two existing oracle
warnings, archive validation, and a 25.38-second performance check.

This work package was installed locally; all 11 installed archive files match.
Earlier mood/card changes were preserved separately. The remote-tag work shares
some files with those changes; keep the scopes separate when staging.
After installation, refresh Stash, refresh Expand's cache if prompted, and test
excluding a StashDB-only tag on both the first and second use.
