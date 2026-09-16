# Proposed score-limited V3 candidate contract

This is a separate research configuration, `mlb-v18-score-limited-v1`.
No current AISP consumer support or import is claimed.

The narrow extension to `server/app/shadow_import/mlb_ensemble_candidate.py`
is to accept `AISP_MLB_ENSEMBLE_CANDIDATE_HANDOFF_V3` and permit `SCORE_LIMIT`
under V3 only, preserving V1/V2 behavior. Keep the existing V1 child forecast
and object-manifest schemas, frozen-system authority and per-game baseline
binding checks, immutable hashes, identity checks and false authority flags.

`SCORE_LIMIT` is post-simulation whole-game filtering. It is neither DURATION,
TRANSITION nor CALIBRATION. The rule excludes an entire original draw when any
played half-inning exceeds the half-inning limit OR either team's final score
exceeds the team-game limit. Equality is accepted; both teams use identical
limits. Scores, event sequences and stopping behavior are never modified.

`baselineBinding.simulationCount` remains 5000. The child
`simulation.simulationCount` and `retainedSimulationCount` equal the actual
accepted count; `sourceSimulationCount` remains 5000. Every candidate marginal,
expectation and win probability uses the accepted count as its denominator.
No retained draw means no supported forecast. This configuration also refuses
fewer than the rule's fixed minimum retained draws (initially 1000).

The checksummed `accepted-population.npz` contains the unchanged 5000 baseline
scores, innings and PA counts; ascending `accepted_indices`; a length-5000
Boolean `acceptance_mask`; and the indexed candidate subsets. The consumer
should verify the mask/index equality, candidate array equality to each
baseline array indexed by accepted indices, unchanged frozen-baseline arrays,
integer nonnegative scores, terminal non-ties, counts and probability mass.
Full inning arrays remain in `source-population.npz`; the source-sidecar binds
these to the exact ordinary V18 baseline. Other per-draw summaries are linked
through these original indices. Only the original representative trace was
retained; this package does not claim full event sequences were stored.

The candidate's `publishedAt` is the immutable local comparison freeze, as in
the existing candidate convention, and is explicitly labelled. The later
exchange publication receipt supplies the actual delivery time. Prospective
classification requires rule publication before filtering, source capture
before the original policy cutoff, and comparison freeze plus package creation
before that same cutoff. The rule is not backdated to baseline publication.

Verify the exact package against the existing baseline authority and ordinary
baseline import. File it as research evidence under its distinct configuration;
display the source count, retained count, exclusion rate, integer limits,
Monte Carlo precision and false authority flags. Return an import receipt with
the exact handoff/configuration/forecast/baseline identities. Research import
and display are not production activation or promotion. No AISP settings,
positions, bankroll, selection policy or existing component studies change.
