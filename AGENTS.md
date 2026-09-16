# Permanent MLB evaluation exclusion

Before any future MLB Final OOT model comparison, component evaluation,
calibration decision or promotion claim, apply the whole-game quarantine in
`server/artifacts/governance/mlb-final-oot-quarantine-v1.json` to identity metadata
before loading outcomes. Never remove its three `PROSPECTIVE_FEATURE_CONSTRUCTION`
exclusions, including by changing the pitcher, model, component or game-ID alias.
Use `mlb_starter_duration_quarantine.final_oot_eligible_key_mask` for canonical or
MLBAM keys and `require_reduced_final_oot_report` before issuing any OOT report.
Preserve the remaining August 14–27, 2026 payload sealed unless James
separately authorizes evaluation. Any future OOT report must disclose removed
games/observations and the reduced cohort, not claim original untouched Final OOT.
The starter-history source exception grants no evaluation, tuning or promotion.

The identity-only accounting receipt is
`outputs/mlb-starter-duration-paired-research-v1/quarantine-key-accounting/objects/sha256/47b1af811219ef30c94225c511b9b8a8860443066f39d28b0e4b155f2201baa8.json`:
230 of the original 14,067 observations are permanently excluded, leaving 13,837.
This is a key count, not authorization to read or evaluate the reduced cohort.
