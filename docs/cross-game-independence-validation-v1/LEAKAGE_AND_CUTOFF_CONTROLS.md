# Leakage and cutoff controls

The [study design](STUDY_DESIGN.json) was frozen at `2026-09-16T17:24:00Z`, before outcome rows were loaded or metrics calculated. It fixed populations, pair rules, seed, bootstrap count, segments and practical tolerances.

A pre-metric source-code review found that CFB Development calibrated probabilities had been fit using the complete 2016–22 Development outcomes. Those same rows could not serve as probability targets. [METHODOLOGY_AMENDMENT.json](METHODOLOGY_AMENDMENT.json), recorded before calculation, replaces them with reused 2023–24 Validation predictions whose calibrator was fixed on Development. No threshold changed.

Chronology controls by sport:

- **NFL:** five season-forward OOF folds, one target season per fold. Only schedule identity/type/time/team fields enrich the prediction ledger. Historical per-game physical publication clocks are not retained.
- **NBA:** target rows use only an earlier `history_latest_game_date`. The model row is the corrected `ridge_a100_rest` Development prediction. Historical physical publication clocks are not retained.
- **CFB:** every non-null `feature_max_source_game_date` is earlier than kickoff. Eighty-one null rows represent no prior eligible game in either current team state and use governed opener/prior defaults. The target is reused Validation, not fresh OOT.

No model was refit or rerun. No current forecast was regenerated. No current-season model-selection outcome, MLB population, sealed payload or Final OOT outcome was opened. The MLB whole-game quarantine remains untouched.

These checks establish chronological reconstruction, not prospective publication certification. The evidence is class A historical development/research evidence. It cannot establish that an exact forecast revision physically existed before each historical game.
