"""Private replay instrumentation, extending the retained EXP-027 collector.

No source/outcome/model loads, RNG draws, or simulator changes occur here.
Use ReplayDiagnostics.wrap_provider/provider + event_observer, then finalize.
Runs while a pitching state is active are NOT official pitcher responsibility.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from types import ModuleType
from typing import Any, Mapping

import numpy as np

from server.sports_current_statcast.mlb_v18_population_diagnostics import (
    PopulationDiagnostics, PopulationDiagnosticsError,
)
from server.sports_current_statcast.mlb_v18_population_boundaries import enrich_boundaries

SCHEMA = "MLB_V18_PRIVATE_REPLAY_INSTRUMENTATION_V1"


class ReplayDiagnostics(PopulationDiagnostics):
    """Reuse EXP-027 accounting; add only replay-specific projections/events."""

    def __init__(self, n_sims: int, *, regulation: int = 9):
        super().__init__(n_sims, regulation=regulation)
        self._walkoff_runs = np.zeros(self.n_sims, dtype=np.int32)
        self._walkoff_needed = self._walkoff_runs.copy()
        self._walkoff_nonhr_excess = self._walkoff_runs.copy()
        self._walkoff_outcome = np.full(self.n_sims, -1, dtype=np.int8)
        self._third_out_runs = np.zeros((self.n_sims, 2), dtype=np.int32)
        self._third_out_run_events = self._third_out_runs.copy()
        self._removal_outs = np.full((self.n_sims, 2), -1, dtype=np.int32)
        self._removal_runs = self._removal_outs.copy()
        self._removal_base_mask = self._removal_outs.copy()

    def __call__(self, simulation: int, event: Mapping[str, Any]) -> None:
        # Parent validates exact provider row, sequence, conservation and state.
        # It consumes no RNG and never mutates event/provider arrays.
        super().__call__(simulation, event)
        s = int(simulation)
        batting = 0 if event["half"] == "TOP" else 1
        pitching = 1 - batting
        runs = int(event["runsScored"])
        if bool(event["pitchingChange"]):
            self._removal_outs[s, pitching] = self._by_inning["starter_outs_by_inning"][s, pitching].sum()
            self._removal_runs[s, pitching] = self._by_inning["runs_while_starter_active"][s, pitching].sum()
            self._removal_base_mask[s, pitching] = int(event["baseMaskBefore"])
        if int(event["outsAfter"]) == 3 and runs:
            self._third_out_runs[s, batting] += runs
            self._third_out_run_events[s, batting] += 1
        if (batting == 1 and int(event["inning"]) >= self.regulation
                and int(event["homeScoreAfter"]) > int(event["awayScoreAfter"])):
            needed = int(event["awayScoreAfter"]) - (int(event["homeScoreAfter"]) - runs) + 1
            if needed < 1:
                raise PopulationDiagnosticsError("walkoff began from an already winning home state")
            self._walkoff_runs[s] = runs
            self._walkoff_needed[s] = needed
            self._walkoff_outcome[s] = self._class_indices[str(event["outcome"])]
            if event["outcome"] != "HOME_RUN":
                self._walkoff_nonhr_excess[s] = max(0, runs - needed)

    def finalize(self, population: Mapping[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        arrays, metadata = super().finalize(population)
        arrays, metadata = enrich_boundaries(arrays, metadata)
        runs = arrays["runs"]
        started = arrays["half_innings_started"]
        terminal = arrays["terminal_reason"]
        final = np.column_stack([arrays["away_runs"], arrays["home_runs"]])
        regulation_scores = runs[:, :, :self.regulation].sum(axis=2)
        innings = np.asarray(arrays["innings"])
        skipped = (np.zeros(self.n_sims, dtype=bool) if started.shape[2] < self.regulation else
                   ((terminal == 3) & (innings == self.regulation)
                    & (started[:, 1, self.regulation - 1] == 0)))
        projections = {
            "joint_regulation_scores": regulation_scores,
            "joint_final_scores": final,
            "joint_extra_inning_runs": runs[:, :, self.regulation:].sum(axis=2),
            "team_completed_pa": arrays["completed_pa"].sum(axis=2),
            "team_regulation_pa": arrays["completed_pa"][:, :, :self.regulation].sum(axis=2),
            "team_extra_inning_pa": arrays["completed_pa"][:, :, self.regulation:].sum(axis=2),
            "team_batting_half_opportunities": started.sum(axis=2),
            "team_regulation_half_opportunities": started[:, :, :self.regulation].sum(axis=2),
            "team_extra_half_opportunities": started[:, :, self.regulation:].sum(axis=2),
            "starter_outs_total": arrays["starter_outs_by_inning"].sum(axis=2),
            "starter_runs_while_active_total": arrays["runs_while_starter_active"].sum(axis=2),
            "relief_bf_total": arrays["anonymous_relief_bf_by_inning"].sum(axis=2),
            "relief_outs_total": arrays["anonymous_relief_outs_by_inning"].sum(axis=2),
            "relief_runs_while_active_total": arrays["runs_while_anonymous_relief_active"].sum(axis=2),
            "starter_removal_outs": self._removal_outs.copy(),
            "starter_removal_runs_while_active": self._removal_runs.copy(),
            "starter_removal_base_mask": self._removal_base_mask.copy(),
            "regulation_complete": ((terminal != 4) | (innings > self.regulation)),
            "skipped_bottom_regulation": skipped,
            "skipped_bottom_ninth": skipped if self.regulation == 9 else np.zeros(self.n_sims, dtype=bool),
            "extras_entered": innings > self.regulation,
            "extras_observed": started[:, :, self.regulation:].sum(axis=(1, 2)) > 0,
            "walkoff": terminal == 1,
            "walkoff_transition_runs": self._walkoff_runs.copy(),
            "walkoff_runs_needed_to_win": self._walkoff_needed.copy(),
            "walkoff_nonhr_excess_credit": self._walkoff_nonhr_excess.copy(),
            "walkoff_outcome_index": self._walkoff_outcome.copy(),
            "third_out_runs_by_batting_team": self._third_out_runs.copy(),
            "third_out_scoring_events_by_batting_team": self._third_out_run_events.copy(),
        }
        checks = {
            "regulationPlusExtrasEqualsFinal": bool(np.array_equal(regulation_scores + projections["joint_extra_inning_runs"], final)),
            "walkoffCountersMatchTerminal": bool(np.array_equal(self._walkoff_runs > 0, terminal == 1)),
            "hookOutsEqualFinalStarterOuts": bool(np.array_equal(self._removal_outs[self._removed], projections["starter_outs_total"][self._removed])),
            "hookActiveRunsEqualFinalStarterActiveRuns": bool(np.array_equal(self._removal_runs[self._removed], projections["starter_runs_while_active_total"][self._removed])),
        }
        if not all(checks.values()):
            raise PopulationDiagnosticsError("replay projection accounting failed: " + str(checks))
        arrays.update(projections)
        metadata["replayInstrumentation"] = {
            "schema": SCHEMA, "baseCollector": "Existing EXP-027 PopulationDiagnostics plus enrich_boundaries",
            "addedArrays": {name: {"shape": list(v.shape), "dtype": str(v.dtype)} for name, v in projections.items()},
            "checks": checks, "allPassed": True,
            "definitions": {
                "teamAxes": "AWAY, HOME. Score/PA/opportunity arrays are batting-side; starter/relief arrays are pitching-side.",
                "joint_regulation_scores": "Runs through the regulation innings; skipped home half stays unplayed. Censored draws are identified by regulation_complete and terminal_reason.",
                "battingOpportunities": "Number of half innings with at least one observed PA; not potential lineup turns, fixed 27 outs, or source-observed opportunities.",
                "starter_removal_outs": "Starter outs before the first relief PA; -1 if no observed hook. Original starter_removal_reason and BF/PA/inning coordinates are retained.",
                "starter_removal_base_mask": "Aggregate occupied bases at the observed hook; not inherited runner identity or responsibility.",
                "runExposure": "Runs scored on transitions while STARTER or anonymous TEAM_BULLPEN was active. Includes inherited runners; NOT official pitcher runs/earned runs or responsibility.",
                "walkoff_nonhr_excess_credit": "Terminal non-HOME_RUN transition runs exceeding those needed to take the lead. Observational counter only; the engine and score are unchanged.",
                "third_out_runs": "Positive runs on transitions recording the third out. Timing/force/batter-runner identities are absent; this is NOT a count of illegal runs.",
                "extras": "extras_entered matches loop inning state; extras_observed requires an observed extra-inning PA. They can differ in censored draws.",
            },
            "extraRngDraws": 0, "modelOrEngineChanged": False,
        }
        return arrays, metadata


def compact_draw_records(arrays: Mapping[str, np.ndarray]) -> list[dict[str, Any]]:
    """Joinable projections for CSV; full original EXP-027 arrays stay available."""
    fields = ["joint_regulation_scores", "joint_final_scores", "joint_extra_inning_runs",
              "team_completed_pa", "team_regulation_pa", "team_extra_inning_pa",
              "team_batting_half_opportunities", "starter_final_bf", "starter_outs_total",
              "starter_runs_while_active_total", "relief_bf_total", "relief_outs_total",
              "relief_runs_while_active_total", "starter_removal_reason", "starter_removal_pa",
              "starter_removal_bf", "starter_removal_inning", "starter_removal_outs",
              "starter_removal_runs_while_active", "starter_removal_base_mask",
              "third_out_runs_by_batting_team", "third_out_scoring_events_by_batting_team"]
    scalar = ["innings", "pa_counts", "terminal_reason", "regulation_complete", "walkoff",
              "skipped_bottom_ninth", "skipped_bottom_regulation", "extras_entered", "extras_observed",
              "walkoff_transition_runs", "walkoff_runs_needed_to_win", "walkoff_nonhr_excess_credit", "walkoff_outcome_index"]
    records = []
    for i in range(len(arrays["pa_counts"])):
        row = {"draw_index": i, **{key: np.asarray(arrays[key])[i].item() for key in scalar}}
        for key in fields:
            for j, side in enumerate(("away", "home")):
                row[f"{side}_{key}"] = np.asarray(arrays[key])[i, j].item()
        records.append(row)
    return records


def _json_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


class _TrackedGenerator:
    def __init__(self, generator: Any, seed: Any, label: str):
        self._generator = generator
        self.label = label
        self.seed = {"entropy": deepcopy(seed.entropy), "spawnKey": list(seed.spawn_key)}
        self.initial_state = deepcopy(generator.bit_generator.state)
        self.calls = 0
        self.values = 0

    def random(self, *args: Any, **kwargs: Any) -> Any:
        result = self._generator.random(*args, **kwargs)
        self.calls += 1
        self.values += int(np.size(result))
        return result

    def record(self) -> dict[str, Any]:
        return {"label": self.label, "seed": self.seed, "randomCalls": self.calls,
                "randomValues": self.values, "initialState": self.initial_state,
                "finalState": deepcopy(self._generator.bit_generator.state)}


class _RandomNamespace:
    def __init__(self, original: Any, audit: "RNGStreamAudit"):
        self.original, self.audit = original, audit

    def __getattr__(self, name: str) -> Any:
        return getattr(self.original, name)

    def default_rng(self, seed: Any) -> _TrackedGenerator:
        if len(self.audit.streams) >= 3:
            raise RuntimeError("unexpected fourth simulator RNG stream")
        tracked = _TrackedGenerator(self.original.default_rng(seed), seed,
                                    ("pa", "transition", "hook")[len(self.audit.streams)])
        self.audit.streams.append(tracked)
        return tracked


class _NumpyNamespace:
    def __init__(self, original: Any, audit: "RNGStreamAudit"):
        self.original = original
        self.random = _RandomNamespace(original.random, audit)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.original, name)


class RNGStreamAudit:
    """Temporarily proxy this engine module's NumPy name, not global NumPy.

    Use only in a private, serial research process. No model/production hook is
    installed. The three original Generator.random calls delegate exactly once;
    reading their state does not advance the generator.
    """

    def __init__(self, engine_module: ModuleType):
        self.engine = engine_module
        self.streams: list[_TrackedGenerator] = []
        self._original = None

    def __enter__(self) -> "RNGStreamAudit":
        if self._original is not None or self.streams or isinstance(self.engine.np, _NumpyNamespace):
            raise RuntimeError("RNG audit cannot be nested or reused")
        self._original = self.engine.np
        self.engine.np = _NumpyNamespace(self._original, self)
        return self

    def __exit__(self, *_: Any) -> None:
        self.engine.np = self._original
        self._original = None

    def receipt(self) -> dict[str, Any]:
        if self._original is not None or len(self.streams) != 3:
            raise RuntimeError("receipt requires a finished three-stream invocation")
        record = {"schema": "MLB_V18_THREE_RNG_STREAM_AUDIT_V1",
                  "streams": [stream.record() for stream in self.streams], "additionalDraws": 0}
        return json.loads(json.dumps(record, sort_keys=True, default=_json_value))

    def assert_equivalent(self, other: "RNGStreamAudit") -> dict[str, Any]:
        first, second = self.receipt(), other.receipt()
        if first != second:
            raise AssertionError("original/instrumented RNG calls, value counts, seeds or states differ")
        raw = json.dumps(first, sort_keys=True, separators=(",", ":")).encode()
        return {"allThreeStreamsIdentical": True, "callsCountsAndEndStatesMatch": True,
                "receiptSha256": hashlib.sha256(raw).hexdigest(), "streams": first["streams"]}
