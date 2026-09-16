# NFL drive survival specification V1

This is a separate research component. The frozen legal play engine and its original donors remain unchanged.

## Index and labels

The prediction index is the legal state immediately BEFORE a recorded decision transition. A decision is a live scrimmage snap, punt/field-goal decision, or the baseline-supported presnap no-play penalty. Penalties do not increment snap counts or consume clock. Timeouts, replay/admin markers, tries and kickoffs are retained in audit/score accounting and excluded from drive risk rows. Kneels and spikes retain their categories.

Order uses retained `order_sequence`, then play ID for deterministic ties; play ID alone is not event chronology. Identity is game ID plus fixed drive. Drive endpoint metadata must resolve within the retained group. Unsupported compounds, ambiguous penalties, absent endpoints, inconsistent clocks or terminal labels exclude the whole drive. No observed complete drive is labelled censored merely because it ends at halftime.

Nine mutually exclusive classes: CONTINUE, TOUCHDOWN, FIELD_GOAL_MADE, FIELD_GOAL_MISSED_OR_BLOCKED, PUNT, OFFENSIVE_TURNOVER, TURNOVER_ON_DOWNS, SAFETY, END_OF_HALF_OR_GAME. Offensive turnovers take precedence over return touchdowns. Blocked kicks are not supported by the frozen legal donor model; their drives are explicitly excluded, so the combined missed/blocked category is supported here by misses. A half/game-ending non-scoring final decision receives END_OF_HALF_OR_GAME when confirmed by the retained end transition. Its interval includes runoff to the observed boundary.

Source completed-drive result, length, points, end clock and final scores are labels/checks ONLY. Features are an explicit numeric whitelist from preplay state and earlier decisions in the same drive. No team ID, completed-drive summary, future field/clock/score, player, weather or market field enters the hazard classifier.

## Frozen mechanism

One StandardScaler plus L2 multinomial logistic model, C=0.1, max_iter=600. All preprocessing and fitting use complete earlier seasons only. No candidate tuning uses 2023, 2024, 2025 or 2026. The 2024 comparison reloads the exact corrected through-2023 baseline artifact. Earlier baseline folds use identical original code/configuration with season-restricted donors. Teams/priors remain the baseline's chronological hierarchical mixtures; the hazard adds no team-ID effects.

Raw model continuation probability is p(CONTINUE). Termination hazard is 1-p(CONTINUE). Conditional cause probability is p(cause)/(1-p(CONTINUE)) where the denominator is nonzero.

Integration is fixed: 75% ordinary baseline sampling; 25% branch draws 16 complete original baseline joint-play proposals. Learned cause probabilities are projected to causes represented by those proposals, normalized, and allocated equally among proposals of each cause. Select one original proposal without changing yards, clock, turnovers, kicks or any transition. This finite-proposal integrated marginal distribution is NOT claimed to equal raw classifier hazards. Absent-cause projected probability and fallback counts are retained.

Full earlier-training feature min/max bounds and regulation-only support are fixed gates. Zero weight, unsupported state and overtime call the original sampler without consuming an additional RNG draw; fallback is exact. The normal hazard branch introduces extra RNG draws and diverging paths. Pairing refers to initial game seeds, not guaranteed event-by-event coupling or model uncertainty.

Drive future rollouts use only the selected origin's recorded preplay state. All subsequent fields evolve from sampled plays. Starts and midpoints are selected by fixed identity hash, not their outcomes. They are retrospective conditional diagnostics; full games start from pregame team identities and season alone. Runout ends at the first terminal cause, retains defensive scoring, and excludes ensuing tries. Offensive points before tries are 6 TD, 3 FG, 0 otherwise. Net points have a separate simulation output; they are not scored against a terminal-label proxy that ignores defensive return scores.

## Assessment and support

200 original legal full-game draws per arm/target; 128 complete drive futures per origin. Full joint home/away pairs are retained. Three-class NFL Brier is SUM of squared home/away/tie errors. No binary MLB conversion, score clipping, score rounding or tied-draw removal. Existing regular-season overtime remains intact; postseason full-game simulation remains unsupported.

Current-play baseline hazards use 128 original donor proposals. The integrated probability estimate uses the same proposals grouped into eight 16-proposal sets, reducing comparison noise. Conditional NLL score stabilization is Jeffreys 0.5 per class applied identically to 128*p for both arms. Raw probabilities, raw NLL with explicit numerical floor, zero counts, Brier and classifier scores remain separately available. This scoring convention does not alter forecasts.

Cumulative incidence is evaluated at 1,3,5,10,20 future decision transitions from evolved-state rollouts. The discrete integrated Brier equivalent is the equal-weight average, over these five horizons, of the sum of the eight cause-specific squared incidence errors. Actual games/calendar football weeks are uncertainty units. Simulation draws measure numerical precision only.

No new prospective forecast, operational fit, AISP import, provider call, betting decision or wagering authority belongs to this study.
