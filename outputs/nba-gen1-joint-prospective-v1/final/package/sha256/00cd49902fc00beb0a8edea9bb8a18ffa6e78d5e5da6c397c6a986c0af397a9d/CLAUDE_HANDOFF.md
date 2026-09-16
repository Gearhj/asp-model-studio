# CLAUDE_HANDOFF — NBA joint simulation early research comparison

Import `C:\Users\james\asp-model-exchange\nba-gen1-research-v1\joint-comparison-v1\packages\sha256\00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d\index.json`. Package/physical index SHA-256: `00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d`.

Bind both arms idempotently to ESPN `401909088`, canonical `nba-espn:game:401909088`, and AISP `f4465955-4d0a-4e7f-8a40-f8bcebe8f5da`. Preserve the existing point/Elo card `nba-point:1b0f9b6fa8d5ce8adc2532664afd941eaf889b6bdf6d6a8013295c43ba1e554f`; this package supplements it with a separate **NBA joint simulation — early research comparison**. Verify raw bytes without newline normalization, index hash equals the package directory, then every indexed file and both population Parquets.

Both arms contain 10,000 paired full-game final-score draws including overtime, zero ties, complete home/away/total/margin PMFs and 50/80/90 intervals. Baseline configuration: `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1`. Correction: `NBA_GEN1_CLOSE_MARGIN_PARITY_TRANSPORT_R8_V1`. The correction uses the frozen radius-eight kernel, changes only close margins, and preserves every winner, total and denominator. Winner probabilities, total PMFs and totals queries are therefore identical.

Baseline joint: BOS 0.4381, DET 0.5619; expected BOS 112.026, DET 113.895, total 225.921. Close-score expected BOS 112.017, DET 113.904. Separate Elo remains BOS 0.41887505293332616 / DET 0.5811249470666738; label it as an independent model output, never as the joint population.

Illustrative totals, not recorded sportsbook lines: 226.0: Over 0.4821, push 0.0213, Under 0.4966; 225.5: Over 0.5034, push 0.0000, Under 0.4966. Units are fractions from 0 to 1. Use each query's explicit win/push/loss fields.

Import by each arm's `(forecastId, forecast physical SHA-256)` and reject conflicting bytes. Store source cutoff and forecast creation separately from `publication-receipt.json` publication time. Display distributions, intervals, simulation MCSE and limitations. Keep wagering, funding, staking, scheduling and promotion disabled. This is the first prospective joint comparison and one pending observation, not evidence of superiority.

After actual import and display verification, write a consumer receipt under `C:\Users\james\asp-model-exchange\nba-gen1-research-v1\joint-comparison-v1\consumer-receipts` with package digest, both forecast IDs/hashes, ESPN/canonical/AISP identities, imported count, idempotent reimport result, display checks and times. Publication alone is not acknowledgement.
