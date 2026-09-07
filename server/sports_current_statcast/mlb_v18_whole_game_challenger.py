"""Minimum governed V18 PA-to-game challenger components.

The module is intentionally small: one scalar calibration challenger, a 246-raw to
273-treated template composer backed by the saved V18 pipelines, a transparent starter
hook, and a vectorized sequential simulator using the existing 24-state transition sampler.
It contains no provider calls and never reads the Final OOT partition.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5.whole_game_monte_carlo import FastTransitionSampler


RAW_FEATURE_COUNT = 246
TREATED_FEATURE_COUNT = 273
STATE_FEATURES = (
    "context_inning",
    "context_top_bottom",
    "context_outs_before",
    "context_base_mask_before",
    "context_batting_score_diff_before",
)
CALIBRATION_SCHEMA = "MLB_V18_TEMPERATURE_CALIBRATION_CHALLENGER_V1"
TEMPLATE_SCHEMA = "MLB_V18_PROSPECTIVE_TEMPLATE_V1"
SIMULATION_SCHEMA = "MLB_V18_PROSPECTIVE_WHOLE_GAME_SIMULATION_V1"


class V18WholeGameError(RuntimeError):
    pass


def apply_temperature(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    p = np.asarray(probabilities, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] != len(PA_CLASS_ORDER):
        raise V18WholeGameError("temperature scaling requires an N x 8 probability matrix")
    if not math.isfinite(temperature) or temperature <= 0:
        raise V18WholeGameError("temperature must be finite and positive")
    logits = np.log(np.clip(p, 1e-15, 1.0)) / temperature
    logits -= logits.max(axis=1, keepdims=True)
    scaled = np.exp(logits)
    return scaled / scaled.sum(axis=1, keepdims=True)


def fit_temperature(probabilities: np.ndarray, observed: np.ndarray) -> float:
    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(observed, dtype=np.int64)

    def objective(value: float) -> float:
        q = apply_temperature(p, value)
        return float(-np.log(np.clip(q[np.arange(len(y)), y], 1e-15, 1.0)).mean())

    result = minimize_scalar(
        objective, bounds=(0.5, 2.0), method="bounded", options={"xatol": 1e-10}
    )
    if not result.success:
        raise V18WholeGameError("temperature fit did not converge")
    return float(result.x)


def calibration_metrics(probabilities: np.ndarray, observed: np.ndarray) -> dict[str, Any]:
    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(observed, dtype=np.int64)
    n = len(y)
    truth = np.eye(len(PA_CLASS_ORDER), dtype=np.float64)[y]
    confidence = p.max(axis=1)
    correct = p.argmax(axis=1) == y
    band_index = np.minimum((confidence * 10).astype(np.int64), 9)
    bands: list[dict[str, Any]] = []
    for index in range(10):
        mask = band_index == index
        rows = int(mask.sum())
        mean = float(confidence[mask].mean()) if rows else None
        actual = float(correct[mask].mean()) if rows else None
        bands.append({
            "lower": index / 10.0,
            "upper": (index + 1) / 10.0,
            "observations": rows,
            "meanConfidence": mean,
            "observedAccuracy": actual,
            "absoluteGap": abs(mean - actual) if rows else None,
        })
    per_class = []
    for class_index, name in enumerate(PA_CLASS_ORDER):
        index = np.minimum((p[:, class_index] * 10).astype(np.int64), 9)
        weighted = 0.0
        for band in range(10):
            mask = index == band
            if mask.any():
                weighted += int(mask.sum()) * abs(
                    float(p[mask, class_index].mean())
                    - float((y[mask] == class_index).mean())
                )
        per_class.append({"class": name, "ece": weighted / n})
    return {
        "observations": n,
        "logLoss": float(-np.log(np.clip(p[np.arange(n), y], 1e-15, 1.0)).mean()),
        "multiclassBrier": float(np.square(p - truth).sum(axis=1).mean()),
        "topClassEce": float(sum(row["observations"] * (row["absoluteGap"] or 0.0) for row in bands) / n),
        "maximumPopulatedBandGap": float(max(row["absoluteGap"] for row in bands if row["observations"] >= 1000)),
        "maximumPerClassEce": float(max(row["ece"] for row in per_class)),
        "perClass": per_class,
        "reliabilityBands": bands,
    }


def chronological_temperature_study(oof: pd.DataFrame) -> tuple[dict[str, Any], np.ndarray]:
    columns = [f"probability_{name}" for name in PA_CLASS_ORDER]
    required = {"foldNumber", "observedClassIndex", *columns}
    if required - set(oof.columns):
        raise V18WholeGameError("saved V18 OOF schema is incomplete")
    p = oof.loc[:, columns].to_numpy(dtype=np.float64)
    y = oof["observedClassIndex"].to_numpy(dtype=np.int64)
    folds = oof["foldNumber"].to_numpy(dtype=np.int64)
    candidate = p.copy()
    fitted = []
    for fold in range(2, 6):
        train = folds < fold
        valid = folds == fold
        temperature = fit_temperature(p[train], y[train])
        candidate[valid] = apply_temperature(p[valid], temperature)
        fitted.append({
            "validationFold": fold,
            "temperature": temperature,
            "fitRows": int(train.sum()),
            "validationRows": int(valid.sum()),
            "fitSource": "STRICTLY_EARLIER_SAVED_OOF_FOLDS",
        })
    raw = calibration_metrics(p, y)
    calibrated = calibration_metrics(candidate, y)
    final_temperature = fit_temperature(p, y)
    # Calibration must improve across all three named calibration summaries.  A tiny
    # likelihood gain alone is insufficient to select the challenger.
    improves = (
        calibrated["topClassEce"] < raw["topClassEce"]
        and calibrated["maximumPopulatedBandGap"] < raw["maximumPopulatedBandGap"]
        and calibrated["maximumPerClassEce"] < raw["maximumPerClassEce"]
    )
    log_loss_safe = calibrated["logLoss"] <= raw["logLoss"] + 0.0001
    brier_safe = calibrated["multiclassBrier"] <= raw["multiclassBrier"] + 0.0001
    selected = bool(improves and log_loss_safe and brier_safe)
    evidence = {
        "schemaVersion": CALIBRATION_SCHEMA,
        "method": "SCALAR_MULTICLASS_TEMPERATURE_SCALING",
        "fitCount": 5,
        "crossTemporalFits": fitted,
        "deploymentFit": {
            "temperature": final_temperature,
            "fitRows": len(oof),
            "purpose": "PROSPECTIVE_RESEARCH_SHADOW_ONLY",
        },
        "raw": raw,
        "candidateCrossTemporal": calibrated,
        "selectionRule": {
            "allThreeCalibrationSummariesMustImprove": True,
            "maximumAllowedLogLossDamage": 0.0001,
            "maximumAllowedBrierDamage": 0.0001,
        },
        "checks": {
            "calibrationImproved": bool(improves),
            "logLossSafe": bool(log_loss_safe),
            "brierSafe": bool(brier_safe),
        },
        "selected": selected,
        "decision": "SELECT_TEMPERATURE_SCALING" if selected else "RETAIN_RAW_V18",
        "foldOnePolicy": "RAW_UNCALIBRATED_NO_EARLIER_OOF_CALIBRATION_FIT_EXISTS",
        "finalOotRowsRead": 0,
    }
    return evidence, candidate


def compose_raw_template(
    *,
    source_order: Sequence[str],
    batter_row: Mapping[str, Any],
    pitcher_row: Mapping[str, Any],
    state: Mapping[str, int],
) -> pd.DataFrame:
    if len(source_order) != RAW_FEATURE_COUNT or len(set(source_order)) != RAW_FEATURE_COUNT:
        raise V18WholeGameError("V18 saved pipeline must expose exactly 246 raw inputs")
    missing = set(source_order) - set(batter_row) - set(pitcher_row)
    if missing:
        raise V18WholeGameError("template evidence lacks raw inputs: " + ", ".join(sorted(missing)))
    output: dict[str, Any] = {}
    for name in source_order:
        if name.startswith("pitcher_") or name.startswith("fielding_"):
            output[name] = pitcher_row.get(name)
        else:
            output[name] = batter_row.get(name)
    for name in ("matchup_pitcher_throws_left", "matchup_pitcher_hand_missing"):
        output[name] = pitcher_row.get(name)
    left_batter = bool(output.get("matchup_batter_bats_left") or False)
    switch_batter = bool(output.get("matchup_batter_bats_switch") or False)
    left_pitcher = bool(output.get("matchup_pitcher_throws_left") or False)
    hand_missing = bool(output.get("matchup_batter_hand_missing") or False) or bool(
        output.get("matchup_pitcher_hand_missing") or False
    )
    output["matchup_platoon_advantage"] = None if hand_missing else int(
        switch_batter or left_batter != left_pitcher
    )
    for name in STATE_FEATURES:
        if name not in state:
            raise V18WholeGameError(f"simulated state is missing {name}")
        output[name] = int(state[name])
    frame = pd.DataFrame([{name: output[name] for name in source_order}], columns=source_order)
    if tuple(frame.columns) != tuple(source_order):
        raise V18WholeGameError("raw template order differs")
    return frame


def verify_template_all_folds(
    pipelines: Sequence[Any], batter_row: Mapping[str, Any], pitcher_row: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if len(pipelines) != 5:
        raise V18WholeGameError("exactly five saved V18 fold pipelines are required")
    evidence = []
    for index, pipeline in enumerate(pipelines, 1):
        raw = compose_raw_template(
            source_order=pipeline.ordered_features,
            batter_row=batter_row,
            pitcher_row=pitcher_row,
            state={
                "context_inning": 1,
                "context_top_bottom": index % 2,
                "context_outs_before": 0,
                "context_base_mask_before": 0,
                "context_batting_score_diff_before": 0,
            },
        )
        treated = pipeline.preprocessor.transform_frame(raw)
        probabilities = pipeline.predict_proba(raw)
        if treated.shape != (1, TREATED_FEATURE_COUNT):
            raise V18WholeGameError("saved preprocessor did not produce the registered 273 inputs")
        if probabilities.shape != (1, 8) or not np.allclose(probabilities.sum(1), 1.0):
            raise V18WholeGameError("saved V18 pipeline probability contract failed")
        evidence.append({
            "foldNumber": index,
            "rawInputs": raw.shape[1],
            "treatedInputs": treated.shape[1],
            "probabilitySum": float(probabilities.sum()),
            "side": "HOME" if index % 2 else "AWAY",
        })
    return evidence


def starter_removal_probability(
    inning: np.ndarray,
    batters_faced: np.ndarray,
    runs_allowed: np.ndarray,
    times_through_order: np.ndarray,
    pregame_expected_batters_faced: float = 23.0,
) -> np.ndarray:
    """Transparent, monotone baseline hook; it is a policy, not a fitted model."""
    z = (
        -5.25
        + 0.58 * np.maximum(np.asarray(inning, dtype=float) - 3.0, 0.0)
        + 0.16 * np.maximum(np.asarray(batters_faced, dtype=float) - pregame_expected_batters_faced + 4.0, 0.0)
        + 0.48 * np.asarray(runs_allowed, dtype=float)
        + 0.82 * np.maximum(np.asarray(times_through_order, dtype=float) - 1.0, 0.0)
    )
    probability = 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))
    probability = np.where(np.asarray(batters_faced) < 9, 0.0, probability)
    return np.clip(probability, 0.0, 0.95)


@dataclass
class V18StateProbabilityProvider:
    pipeline: Any
    away_batters: Sequence[Mapping[str, Any]]
    home_batters: Sequence[Mapping[str, Any]]
    away_starter: Mapping[str, Any]
    home_starter: Mapping[str, Any]
    away_bullpen: Sequence[Mapping[str, Any]]
    home_bullpen: Sequence[Mapping[str, Any]]
    temperature: float | None = None

    def __post_init__(self) -> None:
        if len(self.away_batters) != 9 or len(self.home_batters) != 9:
            raise V18WholeGameError("prospective batting orders must contain nine templates")
        if not self.away_bullpen or not self.home_bullpen:
            raise V18WholeGameError("each pregame team bullpen distribution must be nonempty")
        self._cache: dict[tuple[int, ...], np.ndarray] = {}
        self._treated_templates: dict[tuple[int, int, int], list[pd.Series]] = {}
        template_frames: list[pd.DataFrame] = []
        template_owners: list[tuple[int, int, int]] = []
        initial_state = {
            "context_inning": 1,
            "context_top_bottom": 0,
            "context_outs_before": 0,
            "context_base_mask_before": 0,
            "context_batting_score_diff_before": 0,
        }
        for is_top in (0, 1):
            batters = self.away_batters if is_top else self.home_batters
            starter = self.home_starter if is_top else self.away_starter
            bullpen = self.home_bullpen if is_top else self.away_bullpen
            for slot, batter in enumerate(batters):
                for is_bullpen, pitchers in ((0, (starter,)), (1, bullpen)):
                    for pitcher in pitchers:
                        template_frames.append(compose_raw_template(
                            source_order=self.pipeline.ordered_features,
                            batter_row=batter,
                            pitcher_row=pitcher,
                            state={**initial_state, "context_top_bottom": 0 if is_top else 1},
                        ))
                        template_owners.append((is_top, slot, is_bullpen))
        raw_templates = pd.concat(template_frames, ignore_index=True)
        treated_templates = self.pipeline.preprocessor.transform_frame(raw_templates)
        for owner, (_, row) in zip(template_owners, treated_templates.iterrows(), strict=True):
            self._treated_templates.setdefault(owner, []).append(row)
        # The fast path is authorized only when the five game-state fields are direct
        # treated inputs and reproduces the immutable wrapper on a non-default state.
        if any(name not in treated_templates.columns for name in STATE_FEATURES):
            raise V18WholeGameError("a dynamic game-state field is not directly executable")
        fixture_raw = compose_raw_template(
            source_order=self.pipeline.ordered_features,
            batter_row=self.away_batters[0],
            pitcher_row=self.home_starter,
            state={
                "context_inning": 7, "context_top_bottom": 0,
                "context_outs_before": 2, "context_base_mask_before": 5,
                "context_batting_score_diff_before": -3,
            },
        )
        fixture_treated = self.pipeline.preprocessor.transform_frame(fixture_raw)
        fixture_baseline = self._treated_templates[(1, 0, 0)][0]
        fast_fixture = fixture_baseline.to_frame().T
        fast_fixture.loc[:, list(STATE_FEATURES)] = fixture_treated.loc[:, list(STATE_FEATURES)].to_numpy()
        expected = self.pipeline.predict_proba(fixture_raw)
        actual = self._score_treated(fast_fixture)
        if not np.allclose(actual, expected, rtol=0.0, atol=1e-14):
            changed = []
            baseline = fixture_baseline
            candidate = fixture_treated.iloc[0]
            for name in treated_templates.columns:
                left, right = baseline[name], candidate[name]
                equal = (pd.isna(left) and pd.isna(right)) or left == right
                if not bool(equal):
                    changed.append(name)
            raise V18WholeGameError(
                "optimized state scoring differs from the saved V18 pipeline; changed treated fields: "
                + ", ".join(changed)
            )

    def _score_treated(self, frame: pd.DataFrame) -> np.ndarray:
        encoded = self.pipeline.preprocessor.encoder.transform(
            frame.loc[:, list(self.pipeline.preprocessor.ordered_features)]
        )
        classes = np.asarray(self.pipeline.estimator.classes_)
        if not np.array_equal(classes, np.arange(len(PA_CLASS_ORDER))):
            raise V18WholeGameError("V18 estimator class order differs from the governed order")
        probabilities = np.asarray(self.pipeline.estimator.predict_proba(encoded), dtype=np.float64)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        return probabilities

    def probabilities(
        self,
        *,
        top: np.ndarray,
        batting_pa: np.ndarray,
        inning: np.ndarray,
        outs: np.ndarray,
        base: np.ndarray,
        score_diff: np.ndarray,
        bullpen: np.ndarray,
    ) -> np.ndarray:
        n = len(top)
        result = np.empty((n, len(PA_CLASS_ORDER)), dtype=np.float64)
        keys = np.column_stack((
            top.astype(np.int64), batting_pa % 9, np.minimum(inning, 12), outs, base,
            np.clip(score_diff, -8, 8), bullpen.astype(np.int64),
        ))
        unique_keys = [tuple(int(value) for value in row) for row in np.unique(keys, axis=0)]
        pending_rows: list[pd.Series] = []
        pending_owners: list[tuple[int, ...]] = []
        for key in unique_keys:
            if key in self._cache:
                continue
            is_top, slot, inn, out, base_mask, diff, is_bullpen = key
            for template in self._treated_templates[(is_top, slot, is_bullpen)]:
                row = template.copy()
                row["context_inning"] = inn
                row["context_top_bottom"] = 0 if is_top else 1
                row["context_outs_before"] = out
                row["context_base_mask_before"] = base_mask
                row["context_batting_score_diff_before"] = diff
                pending_rows.append(row)
                pending_owners.append(key)
        if pending_rows:
            scored = self._score_treated(pd.DataFrame(pending_rows))
            grouped: dict[tuple[int, ...], list[np.ndarray]] = {}
            for owner, probability in zip(pending_owners, scored, strict=True):
                grouped.setdefault(owner, []).append(probability)
            for owner, rows in grouped.items():
                probability = np.asarray(rows).mean(axis=0)
                if self.temperature is not None:
                    probability = apply_temperature(probability[None, :], self.temperature)[0]
                self._cache[owner] = probability
        for key_values in np.unique(keys, axis=0):
            key = tuple(int(value) for value in key_values)
            mask = np.all(keys == key_values, axis=1)
            result[mask] = self._cache[key]
        return result


def simulate_prospective_game(
    *,
    game_id: str,
    provider: V18StateProbabilityProvider,
    transition_model: bt.TransitionModel,
    n_sims: int,
    master_seed: int,
    regulation: int = 9,
    trace_count: int = 1,
) -> dict[str, Any]:
    if n_sims <= 0 or trace_count < 0 or trace_count > min(n_sims, 5):
        raise V18WholeGameError("invalid simulation or trace count")
    import hashlib

    game_entropy = int.from_bytes(hashlib.sha256(game_id.encode("utf-8")).digest()[:8], "big")
    pa_seed, transition_seed, hook_seed = np.random.SeedSequence(
        [master_seed, game_entropy]
    ).spawn(3)
    pa_rng = np.random.default_rng(pa_seed)
    transition_rng = np.random.default_rng(transition_seed)
    hook_rng = np.random.default_rng(hook_seed)
    sampler = FastTransitionSampler(transition_model)

    inning = np.ones(n_sims, dtype=np.int64)
    top = np.ones(n_sims, dtype=bool)
    outs = np.zeros(n_sims, dtype=np.int64)
    base = np.zeros(n_sims, dtype=np.int64)
    away_score = np.zeros(n_sims, dtype=np.int64)
    home_score = np.zeros(n_sims, dtype=np.int64)
    away_pa = np.zeros(n_sims, dtype=np.int64)
    home_pa = np.zeros(n_sims, dtype=np.int64)
    pa_count = np.zeros(n_sims, dtype=np.int64)
    away_starter_active = np.ones(n_sims, dtype=bool)
    home_starter_active = np.ones(n_sims, dtype=bool)
    away_bf = np.zeros(n_sims, dtype=np.int64)
    home_bf = np.zeros(n_sims, dtype=np.int64)
    away_starter_runs = np.zeros(n_sims, dtype=np.int64)
    home_starter_runs = np.zeros(n_sims, dtype=np.int64)
    terminal = np.zeros(n_sims, dtype=bool)
    illegal = 0
    traces: list[list[dict[str, Any]]] = [[] for _ in range(trace_count)]

    for step in range(200):
        if terminal.all():
            break
        active = ~terminal
        pitching_home = top
        active_starter = np.where(pitching_home, home_starter_active, away_starter_active)
        bf = np.where(pitching_home, home_bf, away_bf)
        starter_runs = np.where(pitching_home, home_starter_runs, away_starter_runs)
        batting_pa = np.where(top, away_pa, home_pa)
        tto = bf // 9 + 1
        hook_p = starter_removal_probability(inning, bf, starter_runs, tto)
        change = active & active_starter & (hook_rng.random(n_sims) < hook_p)
        home_starter_active &= ~(change & pitching_home)
        away_starter_active &= ~(change & ~pitching_home)
        bullpen = np.where(pitching_home, ~home_starter_active, ~away_starter_active)

        diff = np.where(top, away_score - home_score, home_score - away_score)
        probabilities = provider.probabilities(
            top=top, batting_pa=batting_pa, inning=inning, outs=outs, base=base,
            score_diff=diff, bullpen=bullpen,
        )
        if not np.isfinite(probabilities).all() or not np.allclose(probabilities.sum(1), 1.0, atol=1e-12):
            raise V18WholeGameError("PA provider emitted invalid probabilities")
        u = pa_rng.random(n_sims)
        outcome_index = (np.cumsum(probabilities, axis=1) < u[:, None]).sum(axis=1)
        np.clip(outcome_index, 0, 7, out=outcome_index)
        transition = sampler.sample(outcome_index * 24 + outs * 8 + base, transition_rng.random(n_sims))
        outs_added, base_after, runs = transition[:, 0], transition[:, 1], transition[:, 2]
        for simulation in np.nonzero(active)[0]:
            item = (int(outs_added[simulation]), int(base_after[simulation]), int(runs[simulation]))
            if not bt.is_legal(int(outs[simulation]), int(base[simulation]), item):
                illegal += 1
        outs_after = outs + outs_added
        for simulation in range(trace_count):
            if active[simulation]:
                traces[simulation].append({
                    "pa": step + 1,
                    "inning": int(inning[simulation]),
                    "half": "TOP" if top[simulation] else "BOTTOM",
                    "battingOrderPosition": int(batting_pa[simulation] % 9 + 1),
                    "pitcherState": "TEAM_BULLPEN" if bullpen[simulation] else "STARTER",
                    "pitchingChange": bool(change[simulation]),
                    "outcome": PA_CLASS_ORDER[int(outcome_index[simulation])],
                    "outsBefore": int(outs[simulation]),
                    "outsAfter": int(outs_after[simulation]),
                    "baseMaskBefore": int(base[simulation]),
                    "baseMaskAfter": int(base_after[simulation]),
                    "runsScored": int(runs[simulation]),
                    "awayScoreAfter": int(away_score[simulation] + (runs[simulation] if top[simulation] else 0)),
                    "homeScoreAfter": int(home_score[simulation] + (runs[simulation] if not top[simulation] else 0)),
                })

        away_score += np.where(active & top, runs, 0)
        home_score += np.where(active & ~top, runs, 0)
        starter_run_credit = active & ~bullpen
        home_starter_runs += np.where(starter_run_credit & top, runs, 0)
        away_starter_runs += np.where(starter_run_credit & ~top, runs, 0)
        home_bf += (active & top & ~bullpen).astype(np.int64)
        away_bf += (active & ~top & ~bullpen).astype(np.int64)
        away_pa += (active & top).astype(np.int64)
        home_pa += (active & ~top).astype(np.int64)
        pa_count += active.astype(np.int64)

        walkoff = active & ~top & (inning >= regulation) & (home_score > away_score)
        ends = active & ~walkoff & (outs_after >= 3)
        cont = active & ~walkoff & (outs_after < 3)
        base = np.where(cont, base_after, base)
        outs = np.where(cont, outs_after, outs)
        end_bottom = ends & ~top & (inning >= regulation) & (away_score != home_score)
        end_top = ends & top & (inning >= regulation) & (home_score > away_score)
        become_terminal = walkoff | end_bottom | end_top
        switch = ends & ~become_terminal
        was_top = switch & top
        was_bottom = switch & ~top
        inning = np.where(was_bottom, inning + 1, inning)
        top = np.where(was_top, False, top)
        top = np.where(was_bottom, True, top)
        outs = np.where(switch, 0, outs)
        base = np.where(switch, 0, base)
        base = np.where(switch & (inning > regulation), 2, base)
        terminal |= become_terminal

    nonterminated = int((~terminal).sum())
    return {
        "schemaVersion": SIMULATION_SCHEMA,
        "gameId": game_id,
        "simulationCount": n_sims,
        "masterSeed": master_seed,
        "homeWinProbability": float((home_score > away_score).mean()),
        "meanAwayRuns": float(away_score.mean()),
        "meanHomeRuns": float(home_score.mean()),
        "meanTotalRuns": float((away_score + home_score).mean()),
        "meanRunDifferential": float((home_score - away_score).mean()),
        "oneRunRate": float((np.abs(home_score - away_score) == 1).mean()),
        "extraInningRate": float((inning > regulation).mean()),
        "pitchingChangeRateAway": float((~away_starter_active).mean()),
        "pitchingChangeRateHome": float((~home_starter_active).mean()),
        "nonterminationCount": nonterminated,
        "illegalStateCount": illegal,
        "awayRuns": away_score,
        "homeRuns": home_score,
        "innings": inning,
        "paCounts": pa_count,
        "traces": traces,
    }


__all__ = [
    "CALIBRATION_SCHEMA", "RAW_FEATURE_COUNT", "SIMULATION_SCHEMA", "STATE_FEATURES",
    "TEMPLATE_SCHEMA", "TREATED_FEATURE_COUNT", "V18StateProbabilityProvider",
    "V18WholeGameError", "apply_temperature", "calibration_metrics",
    "chronological_temperature_study", "compose_raw_template", "fit_temperature",
    "simulate_prospective_game", "starter_removal_probability", "verify_template_all_folds",
]
