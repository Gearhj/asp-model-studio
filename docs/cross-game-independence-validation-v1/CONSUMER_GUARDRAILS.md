# Proposed consumer guardrails

These are recommendations only. This study writes nothing to AISP and grants no decision, position or stake authority.

1. Keep cross-game calculation disabled by default.
2. Keep same-game legs on paired-draw intersection only; never multiply their marginals.
3. Do not enable any sport or segment from v1: no examined category passed every frozen numerical criterion.
4. If a future category passes, require exactly two different canonical games, distinct teams, independently bound eligible forecast revisions, and an explicit `INDEPENDENCE_ASSUMPTION` label.
5. Return no empirical joint draw count or joint-population MCSE for a cross-game product.
6. Fail closed for shared teams/doubleheaders, same-game identity, postseason or tournament linkage, sequential incentive linkage, shared uncertain player/roster evidence, ambiguous identity, missing eligible revision, known common-source failure, unsupported market semantics, or stale/missing calibration certification.
7. Do not mix forecast horizons or silently replace a leg with a newer revision. Display the exact forecast ID, model configuration and cutoff for each leg.
8. Do not show more precision than the validated calibration interval supports. No v1 category supports a product probability for display.
9. Revalidate constituent single-game calibration and cross-game residual dependence. A low correlation alone is insufficient.
10. Do not infer applicability to three or more legs from a two-leg result.

## Prospective evidence needed

Collect immutable controlling forecast IDs, physical creation/publication times, source cutoffs, scheduled starts, revision lineage and predeclared dependency flags before outcomes. Preserve shared-team, venue, weather-input, tournament/standings, player/roster and known source-incident fields. Freeze the eligible category and apply the existing v1 gate once coverage reaches at least 500 games, 50 dates and 1,000 pairs, with at least two reliability bands of 200 pairs and 20 dates each.
