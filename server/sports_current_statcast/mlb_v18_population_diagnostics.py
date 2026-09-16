"""Passive population counters for the existing V18 event-observer interface.

No model, source, outcome, RNG, fitting, or simulator dependency is invoked here.
Use ``collector.wrap_provider(provider)`` as the simulator provider, pass the
collector itself as ``event_observer``, then save the arrays and JSON metadata
returned by ``collector.finalize(population)``. The provider wrapper returns the
original probability object unchanged after exactly one delegated call.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from server.sports_modeling.metrics import PA_CLASS_ORDER


SCHEMA_VERSION = "MLB_V18_PASSIVE_POPULATION_DIAGNOSTICS_V1"
TEAM_ORDER = ("AWAY", "HOME")
TRANSITION_CATEGORIES = (
    "BASES_EMPTY_BEFORE", "RUNNERS_ON_BEFORE", "RISP_BEFORE",
    "NO_OUT_PA", "ONE_OUT_PA", "MULTIOUT_PA_PROXY", "RUN_SCORING_PA",
    "BASE_OCCUPANCY_INCREASE_CONTINUING", "BASE_OCCUPANCY_DECREASE_CONTINUING",
    "BASE_OCCUPANCY_UNCHANGED_CONTINUING", "THIRD_OUT_PA", "RISP_NO_RUN_PA",
)
REMOVAL_REASONS = {
    0: "UNFINALIZED", 1: "PRE_PA_BERNOULLI_HOOK",
    2: "GAME_END_ACTIVE", 3: "SIMULATION_LIMIT_ACTIVE",
}
TERMINAL_REASONS = {
    0: "UNFINALIZED", 1: "WALKOFF", 2: "END_BOTTOM_UNTIED",
    3: "END_TOP_HOME_AHEAD", 4: "SIMULATION_LIMIT",
}


class PopulationDiagnosticsError(ValueError):
    """Observer data cannot be reconciled to the supplied simulation population."""


class _ObservedProvider:
    def __init__(self, provider: Any, collector: "PopulationDiagnostics") -> None:
        self._provider = provider
        self._collector = collector

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    def probabilities(self, **state: Any) -> Any:
        result = self._provider.probabilities(**state)
        self._collector._record_provider_result(result, state)
        return result


class PopulationDiagnostics:
    """Collect simulated, state-conditional predictions and sampled transitions.

    Team axes always mean [AWAY, HOME]. Batting and pitching arrays explicitly
    identify which team's side is indexed. Inning index zero denotes inning 1.
    A collector belongs to one simulator invocation; do not share it across runs.
    Pass the same ``regulation`` value to this collector and the simulator.
    """

    def __init__(self, n_sims: int, *, regulation: int = 9) -> None:
        if isinstance(n_sims, bool) or int(n_sims) != n_sims or n_sims <= 0:
            raise PopulationDiagnosticsError("n_sims must be a positive integer")
        if isinstance(regulation, bool) or int(regulation) != regulation or regulation <= 0:
            raise PopulationDiagnosticsError("regulation must be a positive integer")
        self.n_sims = int(n_sims)
        self.regulation = int(regulation)
        self._capacity = max(16, self.regulation)
        self._by_inning: dict[str, np.ndarray] = {}
        shape = (self.n_sims, 2, self._capacity)
        for name in (
            "completed_pa", "runs", "outs_recorded", "half_innings_started",
            "half_innings_completed", "runners_lob_third_out",
            "starter_bf_by_inning", "anonymous_relief_bf_by_inning",
            "starter_outs_by_inning", "anonymous_relief_outs_by_inning",
            "runs_while_starter_active", "runs_while_anonymous_relief_active",
            "non_pa_event_count",
        ):
            self._by_inning[name] = np.zeros(shape, dtype=np.int32)
        for name in ("outcome_counts", "outcome_runs"):
            self._by_inning[name] = np.zeros(shape + (len(PA_CLASS_ORDER),), dtype=np.int32)
        self._by_inning["probability_sums"] = np.zeros(
            shape + (len(PA_CLASS_ORDER),), dtype=np.float64
        )
        self._by_inning["transition_counts"] = np.zeros(
            shape + (len(TRANSITION_CATEGORIES),), dtype=np.int32
        )
        self._starter_bf = np.zeros((self.n_sims, 2), dtype=np.int32)
        self._removed = np.zeros((self.n_sims, 2), dtype=bool)
        self._removal_pa = np.full((self.n_sims, 2), -1, dtype=np.int32)
        self._removal_bf = self._removal_pa.copy()
        self._removal_inning = self._removal_pa.copy()
        self._terminal_reason = np.zeros(self.n_sims, dtype=np.int8)
        self._last_pa = np.zeros(self.n_sims, dtype=np.int32)
        self._last_batch = np.zeros(self.n_sims, dtype=np.int32)
        self._batch = 0
        self._probabilities: np.ndarray | None = None
        self._provider_state: Mapping[str, Any] | None = None
        self._wrapped = False
        self._finalized = False
        self._class_indices = {name: index for index, name in enumerate(PA_CLASS_ORDER)}

    def wrap_provider(self, provider: Any) -> Any:
        if self._wrapped or self._batch or self._finalized:
            raise PopulationDiagnosticsError("one provider per unused collector is required")
        self._wrapped = True
        return _ObservedProvider(provider, self)

    def _record_provider_result(self, result: Any, state: Mapping[str, Any]) -> None:
        if self._finalized:
            raise PopulationDiagnosticsError("collector already finalized")
        values = np.asarray(result)
        if values.shape != (self.n_sims, len(PA_CLASS_ORDER)):
            raise PopulationDiagnosticsError("provider result must be n_sims by eight classes")
        if (
            not np.isfinite(values).all() or (values < 0).any() or (values > 1).any()
            or not np.allclose(values.sum(axis=1), 1.0, rtol=0.0, atol=1e-10)
        ):
            raise PopulationDiagnosticsError("provider probabilities are invalid")
        required = ("top", "batting_pa", "inning", "outs", "base", "score_diff", "bullpen")
        if any(name not in state or np.shape(state[name]) != (self.n_sims,) for name in required):
            raise PopulationDiagnosticsError("provider state shape differs from simulation count")
        # Retain read-only references during this batch. Never alter array flags,
        # values, normalization, input states, provider caches, or RNG streams.
        self._probabilities = values
        self._provider_state = state
        self._batch += 1

    def _ensure_inning(self, inning: int) -> None:
        if inning <= self._capacity:
            return
        capacity = max(inning, self._capacity * 2)
        for name, values in self._by_inning.items():
            shape = values.shape[:2] + (capacity,) + values.shape[3:]
            expanded = np.zeros(shape, dtype=values.dtype)
            expanded[:, :, :self._capacity, ...] = values
            self._by_inning[name] = expanded
        self._capacity = capacity

    def __call__(self, simulation: int, event: Mapping[str, Any]) -> None:
        s = int(simulation)
        if self._finalized or self._provider_state is None or self._probabilities is None:
            raise PopulationDiagnosticsError("event requires a current, unfinalized provider batch")
        if not 0 <= s < self.n_sims or self._last_batch[s] == self._batch:
            raise PopulationDiagnosticsError("invalid or duplicate event simulation index")
        if self._terminal_reason[s]:
            raise PopulationDiagnosticsError("event follows a terminal game state")
        half = str(event["half"])
        if half not in ("TOP", "BOTTOM"):
            raise PopulationDiagnosticsError("unknown half inning")
        batting = 0 if half == "TOP" else 1
        pitching = 1 - batting
        inning = int(event["inning"])
        pa = int(event["pa"])
        before, after = int(event["outsBefore"]), int(event["outsAfter"])
        bases, next_bases = int(event["baseMaskBefore"]), int(event["baseMaskAfter"])
        runs = int(event["runsScored"])
        pitcher = str(event["pitcherState"])
        change = bool(event["pitchingChange"])
        if pitcher not in ("STARTER", "TEAM_BULLPEN"):
            raise PopulationDiagnosticsError("unsupported pitcher state")
        outs_added = after - before
        if (
            inning < 1 or pa != self._last_pa[s] + 1
            or not 0 <= before <= 2 or not before <= after <= 3
            or not 0 <= bases <= 7 or not 0 <= next_bases <= 7 or runs < 0
        ):
            raise PopulationDiagnosticsError("invalid event state or completed-PA sequence")
        state = self._provider_state
        away, home = int(event["awayScoreAfter"]), int(event["homeScoreAfter"])
        pre_pa_diff = away - home - runs if half == "TOP" else home - away - runs
        if (
            bool(state["top"][s]) != (half == "TOP")
            or int(state["inning"][s]) != inning or int(state["outs"][s]) != before
            or int(state["base"][s]) != bases
            or bool(state["bullpen"][s]) != (pitcher == "TEAM_BULLPEN")
            or int(event["battingOrderPosition"]) != int(state["batting_pa"][s]) % 9 + 1
            or int(state["score_diff"][s]) != pre_pa_diff
        ):
            raise PopulationDiagnosticsError("event does not match its pre-sampling provider row")
        class_index = self._class_indices.get(str(event["outcome"]))
        if class_index is None:
            raise PopulationDiagnosticsError("unknown PA class")
        runners_before, runners_after = bases.bit_count(), next_bases.bit_count()
        residual = runners_before + 1 - outs_added - runs - runners_after
        if (after == 3 and (next_bases != 0 or residual < 0)) or (after < 3 and residual != 0):
            raise PopulationDiagnosticsError("transition violates aggregate runner conservation")
        if change:
            if pitcher != "TEAM_BULLPEN" or self._removed[s, pitching]:
                raise PopulationDiagnosticsError("invalid or repeated starter-removal event")
            self._removed[s, pitching] = True
            self._removal_pa[s, pitching] = pa
            self._removal_bf[s, pitching] = self._starter_bf[s, pitching]
            self._removal_inning[s, pitching] = inning
        if (pitcher == "TEAM_BULLPEN") != bool(self._removed[s, pitching]):
            raise PopulationDiagnosticsError("pitcher state lacks the observed removal event")
        self._ensure_inning(inning)
        i = inning - 1
        key = (s, batting, i)
        pkey = (s, pitching, i)
        arrays = self._by_inning
        arrays["completed_pa"][key] += 1
        arrays["outcome_counts"][key + (class_index,)] += 1
        arrays["probability_sums"][key] += self._probabilities[s]
        arrays["outcome_runs"][key + (class_index,)] += runs
        arrays["runs"][key] += runs
        arrays["outs_recorded"][key] += outs_added
        arrays["half_innings_started"][key] = 1
        if pitcher == "STARTER":
            self._starter_bf[s, pitching] += 1
            arrays["starter_bf_by_inning"][pkey] += 1
            arrays["starter_outs_by_inning"][pkey] += outs_added
            arrays["runs_while_starter_active"][pkey] += runs
        else:
            arrays["anonymous_relief_bf_by_inning"][pkey] += 1
            arrays["anonymous_relief_outs_by_inning"][pkey] += outs_added
            arrays["runs_while_anonymous_relief_active"][pkey] += runs
        categories = arrays["transition_counts"][key]
        categories[0 if bases == 0 else 1] += 1
        if bases & 6:
            categories[2] += 1
            if runs == 0:
                categories[11] += 1
        categories[3 + min(outs_added, 2)] += 1
        if runs > 0:
            categories[6] += 1
        if after == 3:
            categories[10] += 1
            arrays["half_innings_completed"][key] += 1
            arrays["runners_lob_third_out"][key] += residual
        else:
            category = 7 if runners_after > runners_before else 8 if runners_after < runners_before else 9
            categories[category] += 1
        if inning >= self.regulation:
            if half == "BOTTOM" and home > away:
                self._terminal_reason[s] = 1
            elif half == "BOTTOM" and after == 3 and home != away:
                self._terminal_reason[s] = 2
            elif half == "TOP" and after == 3 and home > away:
                self._terminal_reason[s] = 3
        self._last_pa[s] = pa
        self._last_batch[s] = self._batch

    def finalize(self, population: Mapping[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        """Reconcile once, returning NPZ-ready arrays and JSON-ready definitions.

        Raises on missing events or inconsistent population fields. Does not
        mutate the supplied population or provider; a finalized collector cannot
        receive further events. Missing removal coordinates use -1, never zero BF.
        """
        if self._finalized or int(population["simulationCount"]) != self.n_sims:
            raise PopulationDiagnosticsError("finalization count differs or collector already finalized")
        saved: dict[str, np.ndarray] = {}
        for source, target in (("awayRuns", "away_runs"), ("homeRuns", "home_runs"),
                               ("innings", "innings"), ("paCounts", "pa_counts")):
            values = np.asarray(population[source])
            if values.shape != (self.n_sims,) or not np.isfinite(values).all():
                raise PopulationDiagnosticsError("invalid saved population array: " + source)
            saved[target] = values.copy()
        max_inning = int(saved["innings"].max())
        self._ensure_inning(max_inning)
        arrays = {name: values[:, :, :max_inning, ...].copy()
                  for name, values in self._by_inning.items()}
        arrays.update(saved)
        completed = arrays["completed_pa"]
        runs = arrays["runs"]
        probability_error = float(np.max(np.abs(arrays["probability_sums"].sum(axis=-1) - completed)))
        nonterminated = self._terminal_reason == 0
        checks = {
            "classCountsEqualCompletedPA": bool(np.array_equal(arrays["outcome_counts"].sum(axis=-1), completed)),
            "classProbabilityMassEqualsCompletedPA": probability_error <= 1e-8,
            "completedPAEqualSavedDraws": bool(np.array_equal(completed.sum(axis=(1, 2)), saved["pa_counts"])),
            "eventSequenceEqualsSavedPA": bool(np.array_equal(self._last_pa, saved["pa_counts"])),
            "awayRunsEqualSavedDraws": bool(np.array_equal(runs[:, 0].sum(axis=1), saved["away_runs"])),
            "homeRunsEqualSavedDraws": bool(np.array_equal(runs[:, 1].sum(axis=1), saved["home_runs"])),
            "classRunsEqualTotalRuns": bool(np.array_equal(arrays["outcome_runs"].sum(axis=-1), runs)),
            "pitcherExposureEqualsOpposingCompletedPA": bool(np.array_equal(
                arrays["starter_bf_by_inning"] + arrays["anonymous_relief_bf_by_inning"], completed[:, ::-1])),
            "pitcherRunsEqualOpposingRuns": bool(np.array_equal(
                arrays["runs_while_starter_active"] + arrays["runs_while_anonymous_relief_active"], runs[:, ::-1])),
            "pitcherOutsEqualOpposingOuts": bool(np.array_equal(
                arrays["starter_outs_by_inning"] + arrays["anonymous_relief_outs_by_inning"], arrays["outs_recorded"][:, ::-1])),
            "basePresenceCategoryPartitionEqualsPA": bool(np.array_equal(arrays["transition_counts"][..., :2].sum(axis=-1), completed)),
            "outsAddedCategoryPartitionEqualsPA": bool(np.array_equal(arrays["transition_counts"][..., 3:6].sum(axis=-1), completed)),
            "continuingOrThirdOutCategoryPartitionEqualsPA": bool(np.array_equal(arrays["transition_counts"][..., 7:11].sum(axis=-1), completed)),
            "starterBFMatchesFinalExposure": bool(np.array_equal(arrays["starter_bf_by_inning"].sum(axis=2), self._starter_bf)),
            "removedStarterBFEqualsFinalBF": bool(np.array_equal(self._removal_bf[self._removed], self._starter_bf[self._removed])),
            "homeRemovalRateEqualsPopulation": bool(np.isclose(self._removed[:, 1].mean(), population["pitchingChangeRateHome"], rtol=0, atol=1e-12)),
            "awayRemovalRateEqualsPopulation": bool(np.isclose(self._removed[:, 0].mean(), population["pitchingChangeRateAway"], rtol=0, atol=1e-12)),
            "nonterminationCountEqualsPopulation": int(nonterminated.sum()) == int(population["nonterminationCount"]),
        }
        if not all(checks.values()):
            raise PopulationDiagnosticsError("population accounting failed: " + ", ".join(k for k, v in checks.items() if not v))
        removal_reason = np.where(self._removed, 1, np.where(nonterminated[:, None], 3, 2)).astype(np.int8)
        arrays.update({
            "starter_final_bf": self._starter_bf.copy(),
            "starter_removal_pa": self._removal_pa.copy(),
            "starter_removal_bf": self._removal_bf.copy(),
            "starter_removal_inning": self._removal_inning.copy(),
            "starter_removal_reason": removal_reason,
            "terminal_reason": np.where(nonterminated, 4, self._terminal_reason).astype(np.int8),
        })
        definitions = {
            "teamOrder": list(TEAM_ORDER), "paClassOrder": list(PA_CLASS_ORDER),
            "inningIndex": "Zero-based array index; index 0 is inning 1; unplayed cells are zero.",
            "completedPA": "Every observer event completes one simulated PA; one outcome per PA.",
            "probabilitySums": "Sum of the original provider's eight probabilities immediately before each sampled PA, on evolving simulated states. These are not observed-PA conditional forecasts.",
            "outcomeRuns": "Runs on transitions labeled with each sampled PA class, not individual runner attribution.",
            "pitchingTeamArrays": ["starter_bf_by_inning", "anonymous_relief_bf_by_inning", "starter_outs_by_inning", "anonymous_relief_outs_by_inning", "runs_while_starter_active", "runs_while_anonymous_relief_active", "starter_final_bf", "starter_removal_pa", "starter_removal_bf", "starter_removal_inning", "starter_removal_reason"],
            "otherTeamArrays": "Batting team; population away/home runs are separate draw vectors.",
            "starterRemovalReasons": REMOVAL_REASONS,
            "starterRemovalCoordinates": "A hook change occurs BEFORE starter_removal_pa (global game PA, one-based), at starter_removal_inning with starter_removal_bf prior starter BF. All three are -1 for GAME_END_ACTIVE/SIMULATION_LIMIT_ACTIVE because no removal occurred. starter_final_bf remains available.",
            "terminalReasons": TERMINAL_REASONS,
            "runExposure": "Runs while the active pitcher state is STARTER or TEAM_BULLPEN, including inherited runners. Not official runs charged to a pitcher.",
            "anonymousRelief": "BF and run exposure of the existing anonymous TEAM_BULLPEN mixture; no named reliever identity or availability inference.",
            "transitionCategoryOrder": list(TRANSITION_CATEGORIES),
            "transitionCategories": {
                "BASES_EMPTY_BEFORE": "baseMaskBefore == 0",
                "RUNNERS_ON_BEFORE": "baseMaskBefore != 0",
                "RISP_BEFORE": "baseMaskBefore & 6 != 0",
                "NO_OUT_PA": "outsAfter - outsBefore == 0",
                "ONE_OUT_PA": "outsAfter - outsBefore == 1",
                "MULTIOUT_PA_PROXY": "outsAfter - outsBefore >= 2; not grounded into double play or exact runner outs",
                "RUN_SCORING_PA": "runsScored > 0",
                "BASE_OCCUPANCY_INCREASE_CONTINUING": "outsAfter < 3 and popcount(baseMaskAfter) > popcount(baseMaskBefore)",
                "BASE_OCCUPANCY_DECREASE_CONTINUING": "outsAfter < 3 and popcount(baseMaskAfter) < popcount(baseMaskBefore)",
                "BASE_OCCUPANCY_UNCHANGED_CONTINUING": "outsAfter < 3 and equal occupied-base counts",
                "THIRD_OUT_PA": "outsAfter == 3",
                "RISP_NO_RUN_PA": "baseMaskBefore & 6 != 0 and runsScored == 0",
            },
            "categoryOverlap": "Categories overlap; only empty/runners-on and no/one/multi-out partitions separately sum to completed PA. Continuing occupancy categories plus THIRD_OUT_PA form a third partition.",
            "runnersLOBThirdOut": "Aggregate surviving runners = popcount(baseMaskBefore) + 1 - (outsAfter-outsBefore) - runsScored on third-out transitions with baseMaskAfter=0. Excludes incomplete/walkoff half innings. Includes automatic extra-inning runners present in the base mask; not exact runner identities, individual LOB, or an official box-score statistic.",
            "halfInningsCompleted": "Observer transitions recording the third out; unplayed bottom halves and walkoffs without a third out are not completed half innings.",
            "nonPAEventCount": {"status": "NOT_MODELED", "valueMeaning": "Structural zero: the existing simulator emits only completed-PA events. Not an empirical claim that no non-PA events occur."},
            "limitations": [
                "No exact runner paths, runner identities, grounded double-play attribution, stolen bases, caught stealing, pickoffs, wild pitches, passed balls, or separate non-PA state transitions are represented.",
                "Base occupancy changes count occupied bases, not how far particular runners advanced.",
                "Run scoring on inherited runners is attributed to the active simulation pitcher state, not baseball pitcher responsibility.",
                "Probability sums and event counts are simulated-state expectations and simulated outcomes; neither substitutes for genuine pre-PA forecasts paired with actual PA outcomes.",
                "GAME_END_ACTIVE means no modeled removal before game end, not a prediction of a later removal time.",
            ],
        }
        metadata = {
            "schemaVersion": SCHEMA_VERSION, "simulationCount": self.n_sims,
            "regulationInnings": self.regulation, "maxRecordedInning": max_inning,
            "providerCalls": self._batch, "definitions": definitions,
            "arrays": {name: {"shape": list(value.shape), "dtype": str(value.dtype)} for name, value in arrays.items()},
            "accounting": {"checks": checks, "allPassed": True,
                           "maximumProbabilityMassError": probability_error,
                           "completedPATotal": int(completed.sum()),
                           "completedPAByBattingTeam": completed.sum(axis=(0, 2)).tolist(),
                           "runsByBattingTeam": runs.sum(axis=(0, 2)).tolist(),
                           "nonterminatedDraws": int(nonterminated.sum())},
            "passivity": {"extraRandomDraws": 0, "providerCallsPerWrapperCall": 1,
                          "originalProbabilityObjectReturned": True,
                          "providerProbabilityMutation": False, "providerInputMutation": False},
        }
        self._finalized = True
        return arrays, metadata


__all__ = ["PopulationDiagnostics", "PopulationDiagnosticsError", "SCHEMA_VERSION",
           "TEAM_ORDER", "TRANSITION_CATEGORIES", "REMOVAL_REASONS", "TERMINAL_REASONS"]
