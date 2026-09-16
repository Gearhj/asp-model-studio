# Published COLâ€“DET package verification

PASS: one supported game, two applied candidate arms, no fallback. All 46 publication-listed files match exact hashes/lengths; both object/handoff identities reconcile. All 24 retained arrays have 5,000 integer draws. Original baseline run/inning/PA arrays match exactly, and both candidate distributions reconcile with their draws.

Actual exchange publication: 2026-09-13T14:49:55.812807+00:00, 3904.187 seconds before the original 2026-09-13T15:55:00Z cutoff. The original snapshot cutoff is 14:19:21.763801Z; its earlier PA-history cutoff is 14:17:44.879433Z. Duration's evidence cutoff is 14:19:08.921550Z and its as-of remains the original snapshot clock.

All authority/activation flags remain false. Consumer imports confirmed: 0; no exact-package acknowledgement file was present. No database, provider, model loading, simulation or outcome access occurred. This verifies capture and publication, not predictive improvement.

Reproduce: `.venv/Scripts/python.exe -B outputs/mlb-v18-survival-starter-coverage-v1/comparisons/publication-verification-20260913/verify_publication.py`
