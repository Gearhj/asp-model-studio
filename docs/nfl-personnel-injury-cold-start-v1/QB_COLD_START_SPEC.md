# Quarterback cold-start specification

The expected quarterback must come from a timestamped pregame record tied to the target team and game. Display-name matching is forbidden. `firstNflStart` means zero governed starts strictly before the feature cutoff; it is not inferred from the realized target-game starter. `rookie` requires a governed rookie-season field. A missing draft row is `DRAFT_STATUS_UNKNOWN`, never undrafted.

Prior performance uses completed earlier games only and records player-season attempts, starts, EPA/dropback, success, sack, interception and CPOE support where governed. The initial shrinkage order is current player-season, player prior seasons, experience cohort, then league prior. The implemented pure helper currently performs transparent player-history plus league-prior shrinkage; cohort estimation remains blocked until a prospective expected-QB population exists.

Existing M1 lagged passer mixtures remain team usage context. They do not identify the expected target starter and are not duplicated or relabelled here.
