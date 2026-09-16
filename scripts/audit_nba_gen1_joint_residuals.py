"""Bind corrected NBA OOF residuals and audit Development support only.

No fitting, prediction regeneration, proper-score assessment, source intake or
publication. The full residual table is uncentered; the support audit centers
each target's eligible earlier-date paired bank exactly once, as documented.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import joblib
import numpy as np
import pandas as pd
from server.sports_nba_gen1.authority import reference, verified_bytes
from server.sports_nba_gen1.distribution import game_seed
from server.sports_nba_gen1.rest_support import FittedRestPointModel

ORIGINAL = REPO / "outputs/nba-gen1-long-gap-v1"
OUTPUT = REPO / "outputs/nba-gen1-joint-residual-v1"
CONFIG = "NBA_GEN1_DEVELOPMENT_SUPPORT_AUDIT_V1"
DRAW_COUNT = 10_000
MASTER_SEED = 20260914
MINIMUM_DONORS = 200


def now():
    return datetime.now(timezone.utc).isoformat()


def save_new(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if path.exists():
        raise ValueError(f"Preserve existing successor evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return reference(path)


def digest_ids(values):
    return hashlib.sha256(json.dumps(list(values), separators=(",", ":")).encode()).hexdigest()


def provenance():
    paths, frames, summaries = {}, [], []
    # Only identity/date metadata is needed from the shared feature population.
    metadata_path = ORIGINAL / "assessment-2026/games.parquet"
    metadata = pd.read_parquet(metadata_path, columns=["game_id", "game_date", "season_end", "home_team_id", "away_team_id", "neutral_site"])
    assert not metadata.game_id.duplicated().any()
    meta = metadata.set_index("game_id")
    paths["trainingAndDonorIdentityMetadata"] = reference(metadata_path)
    columns = ["game_id", "season_end", "game_date", "home_team_id", "away_team_id", "home_team_code", "away_team_code",
               "home_score", "away_score", "expected_home_score", "expected_away_score", "home_residual", "away_residual",
               "model_id", "model_sha256", "home_elo", "away_elo", "p_home_win", "home_rest_days", "away_rest_days",
               "home_season_games_played", "away_season_games_played", "history_latest_game_date", "history_identity_sha256"]
    for stage, expected_years in (("development", [2021, 2022, 2023]), ("reused-diagnostics", [2024, 2025]), ("assessment-2026", [2026])):
        folder = ORIGINAL / stage
        ledger_path, audit_path = folder / "predictions.parquet", folder / "rest-input-audit.parquet"
        receipt_path = folder / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        paths[f"{stage}.receipt"] = reference(receipt_path)
        if stage == "assessment-2026":
            freeze = json.loads(verified_bytes(receipt["freeze"]))
            bindings = {"2026": freeze["models"]["ridge_a100_rest"]}
            paths["assessment-2026.modelFreeze"] = receipt["freeze"]
            assert receipt["assessmentSeasonEnd"] == 2026
            pred_binding, rest_binding = receipt["artifacts"]["predictions"], receipt["artifacts"]["restInputAudit"]
        else:
            model_path = folder / "models.json"
            model_binding = receipt["artifacts"]["models.json"]
            bindings = json.loads(verified_bytes(model_binding))
            paths[f"{stage}.modelBindings"] = reference(model_path)
            pred_binding, rest_binding = receipt["artifacts"]["predictions.parquet"], receipt["artifacts"]["rest-input-audit.parquet"]
        assert reference(ledger_path) == pred_binding and reference(audit_path) == rest_binding
        paths[f"{stage}.predictions"] = pred_binding
        paths[f"{stage}.restAudit"] = rest_binding
        ledger = pd.read_parquet(ledger_path, columns=columns)
        ledger = ledger[ledger.model_id.eq("ridge_a100_rest")].copy()
        audit = pd.read_parquet(audit_path)
        assert set(ledger.season_end) == set(expected_years) and not ledger.game_id.duplicated().any()
        assert not audit.game_id.duplicated().any()
        for year in expected_years:
            part = ledger[ledger.season_end.eq(year)].copy()
            bound = bindings[str(year)]
            verified_bytes(bound["artifact"])
            model = joblib.load(bound["artifact"]["path"])
            assert isinstance(model, FittedRestPointModel) and model.params == {"alpha": 100.0}
            assert model.training_identity_sha256 == bound["trainingIdentitySha256"]
            assert list(model.training_game_ids) == bound["trainingGameIds"]
            assert set(part.model_sha256) == {bound["artifact"]["sha256"]}
            train_meta = meta.loc[list(model.training_game_ids)]
            assert not train_meta.neutral_site.any() and (train_meta.season_end < year).all()
            assert str(train_meta.game_date.max()) == bound["trainingLastDate"]
            assert (part.game_date > bound["trainingLastDate"]).all()
            assert not set(part.game_id).intersection(model.training_game_ids)
            assert (part.history_latest_game_date < part.game_date).all()
            donor_meta = meta.loc[part.game_id]
            for side in ("home", "away"):
                assert donor_meta[f"{side}_team_id"].tolist() == part[f"{side}_team_id"].tolist()
            scores = part[["home_score", "away_score"]].to_numpy(float)
            points = part[["expected_home_score", "expected_away_score"]].to_numpy(float)
            assert np.isfinite(scores).all() and np.isfinite(points).all() and (points > 0).all()
            assert (scores == np.floor(scores)).all() and (scores >= 0).all() and (scores[:, 0] != scores[:, 1]).all()
            residuals = scores - points
            np.testing.assert_array_equal(residuals, part[["home_residual", "away_residual"]].to_numpy(float))
            selected_audit = audit.set_index("game_id").loc[part.game_id]
            out = part.rename(columns={"home_score": "actual_home_score", "away_score": "actual_away_score",
                                       "home_residual": "residual_home", "away_residual": "residual_away",
                                       "p_home_win": "p_home_win_elo", "home_rest_days": "home_raw_rest_days", "away_rest_days": "away_raw_rest_days",
                                       "model_sha256": "model_artifact_sha256"}).copy()
            out["model_training_identity_sha256"] = model.training_identity_sha256
            out["training_last_date"] = bound["trainingLastDate"]
            out["training_games"] = len(model.training_game_ids)
            out["source_stage"] = stage
            out["evidence_class"] = "A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION"
            for side in ("home", "away"):
                np.testing.assert_array_equal(out[f"{side}_raw_rest_days"].to_numpy(), selected_audit[f"raw_{side}_rest_days"].to_numpy())
                out[f"{side}_rest_reason"] = selected_audit[f"{side}_reason"].to_numpy()
                out[f"{side}_treated_rest_days"] = selected_audit[f"treated_{side}_rest_days"].to_numpy()
            out["both_ordinary_rest_supported"] = selected_audit.both_ordinary_supported.to_numpy(bool)
            out["either_season_opener"] = (out.home_season_games_played.eq(0) | out.away_season_games_played.eq(0))
            out["early_season"] = (out.home_season_games_played.lt(10) | out.away_season_games_played.lt(10))
            frames.append(out)
            summaries.append({"seasonEnd": year, "sourceStage": stage, "donorGames": len(out),
                              "firstDonorDate": out.game_date.min(), "lastDonorDate": out.game_date.max(),
                              "modelArtifact": bound["artifact"], "modelTrainingIdentitySha256": model.training_identity_sha256,
                              "trainingGames": len(model.training_game_ids), "trainingLastDate": bound["trainingLastDate"],
                              "trainingGameIdsSha256": digest_ids(model.training_game_ids),
                              "trainingEndsBeforeEveryDonorDate": True, "trainingDonorIntersection": 0,
                              "allFeatureHistoryDatesBeforeDonorDates": True, "residualArithmeticExact": True})
    result = pd.concat(frames, ignore_index=True).sort_values(["game_date", "game_id"]).reset_index(drop=True)
    assert len(result) == 7209 and not result.game_id.duplicated().any()
    assert len(result[result.season_end.eq(2021)]) == 1080
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "residuals.parquet"
    if path.exists():
        raise ValueError("Preserve existing residual population")
    result.to_parquet(path, index=False)
    identity = digest_ids(result.game_id.tolist())
    numerical = np.ascontiguousarray(result[["residual_home", "residual_away"]].to_numpy(dtype="<f8"))
    receipt = {"schema": "NBA_GEN1_CORRECTED_OOF_RESIDUAL_PROVENANCE_V1", "createdAtUtc": now(),
               "configurationIdentity": "NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1",
               "pointComponentIdentity": "NBA_GEN1_ORDINARY_REST_RIDGE_A100_V1", "residualDefinition": "actual minus original saved chronological OOF prediction, columns HOME then AWAY, uncentered",
               "residuals": reference(path), "populationIdentitySha256": identity, "logicalResidualPairsFloat64Sha256": hashlib.sha256(numerical.tobytes()).hexdigest(),
               "donorGames": len(result), "bySeason": summaries, "inputs": paths,
               "checks": {"uniqueWholeGameRows": True, "exactOriginalResidualArithmetic": True, "earlierTrainingAndTargetDisjointness": True,
                          "preservedHomeAwayOrientation": True, "allDonorsFromCorrectedChronologicalModels": True, "allHistoryRefitUsed": False,
                          "inputsUnchanged": all(reference(Path(bound["path"])) == bound for bound in paths.values())},
               "donorAvailability": {"earliestSeasonEnd": 2021, "earliestSeasonDonors": 1080, "minimumEarlierDateDonors": MINIMUM_DONORS,
                                     "rule": "For target date D use donors game_date<D only; exclude same-date and target-game donors. Original revision vintages are unverified; this is Category A chronology, not contemporaneous capture certification."},
               "roles": {"2021-2023": "Development; remedy and support diagnostics already inspected", "2024-2025": "Reused historical diagnostic seasons; not untouched", "2026": "Previously assessed recent season; no new OOT claim"},
               "notPerformed": ["model fitting", "point prediction regeneration", "proper-score assessment", "calibration", "source acquisition", "forecast publication"],
               "script": reference(Path(__file__))}
    receipt_ref = save_new(OUTPUT / "residual-provenance.json", receipt)
    print(json.dumps({"residualProvenance": receipt_ref, "residuals": reference(path), "donorGames": len(result)}), flush=True)
    return result


def support_audit(residuals):
    development = residuals[residuals.season_end.le(2023)].copy()
    records, ineligible = [], []
    for target in development.itertuples():
        bank_rows = development[development.game_date.lt(target.game_date)]
        if len(bank_rows) < MINIMUM_DONORS:
            ineligible.append({"gameId": target.game_id, "gameDate": target.game_date, "earlierDateDonors": len(bank_rows)})
            continue
        bank = bank_rows[["residual_home", "residual_away"]].to_numpy(float)
        seed = game_seed(target.game_id, CONFIG, MASTER_SEED)
        children = np.random.SeedSequence(seed).spawn(3)
        pair_rng, round_rng = np.random.default_rng(children[0]), np.random.default_rng(children[1])
        indices = pair_rng.integers(0, len(bank), size=DRAW_COUNT)
        center = bank.mean(axis=0)
        latent = np.array([target.expected_home_score, target.expected_away_score]) + (bank - center)[indices]
        nonnegative = np.maximum(latent, 0)
        base = np.floor(nonnegative)
        stochastic = (base + (round_rng.random((DRAW_COUNT, 2)) < nonnegative - base)).astype(np.int64)
        nearest = np.floor(nonnegative + .5).astype(np.int64)
        record = {"game_id": target.game_id, "game_date": target.game_date, "season_end": target.season_end,
                  "donor_games": len(bank), "last_donor_date": bank_rows.game_date.max(), "seed": seed, "draw_count": DRAW_COUNT,
                  "center_home": float(center[0]), "center_away": float(center[1]),
                  "latent_negative_home": int((latent[:, 0] < 0).sum()), "latent_negative_away": int((latent[:, 1] < 0).sum()),
                  "latent_negative_either": int((latent < 0).any(axis=1).sum()),
                  "latent_equal_scores": int((latent[:, 0] == latent[:, 1]).sum()),
                  "latent_margin_abs_lt_one": int((np.abs(latent[:, 0] - latent[:, 1]) < 1).sum()),
                  "minimum_latent_home": float(latent[:, 0].min()), "minimum_latent_away": float(latent[:, 1].min()),
                  "actual_home_score": int(target.actual_home_score), "actual_away_score": int(target.actual_away_score),
                  "actual_abs_margin_one": bool(abs(target.actual_home_score - target.actual_away_score) == 1)}
        for name, rounded in (("nearest", nearest), ("stochastic", stochastic)):
            record[f"{name}_ties"] = int((rounded[:, 0] == rounded[:, 1]).sum())
            record[f"{name}_one_point_margins"] = int((np.abs(rounded[:, 0] - rounded[:, 1]) == 1).sum())
            record[f"{name}_zero_score_draws"] = int((rounded == 0).any(axis=1).sum())
            record[f"{name}_mean_shift_home"] = float((rounded[:, 0] - latent[:, 0]).mean())
            record[f"{name}_mean_shift_away"] = float((rounded[:, 1] - latent[:, 1]).mean())
        records.append(record)
    table = pd.DataFrame(records)
    path = OUTPUT / "development-support-by-game.parquet"
    if path.exists():
        raise ValueError("Preserve existing Development support audit")
    table.to_parquet(path, index=False)
    groups = []
    for label, frame in [("ALL_ELIGIBLE_DEVELOPMENT", table)] + [(str(year), frame) for year, frame in table.groupby("season_end")]:
        n = len(frame) * DRAW_COUNT
        groups.append({"group": label, "games": len(frame), "draws": n, "firstTargetDate": frame.game_date.min(), "lastTargetDate": frame.game_date.max(),
                       "minimumEarlierDateDonors": int(frame.donor_games.min()), "maximumEarlierDateDonors": int(frame.donor_games.max()),
                       "minimumLatentHomeAway": [float(frame.minimum_latent_home.min()), float(frame.minimum_latent_away.min())],
                       "latentNegativeHomeAway": [int(frame.latent_negative_home.sum()), int(frame.latent_negative_away.sum())],
                       "latentNegativeEitherCount": int(frame.latent_negative_either.sum()),
                       "actualMinimumHomeAwayScore": [int(frame.actual_home_score.min()), int(frame.actual_away_score.min())],
                       "actualOnePointFinalGames": int(frame.actual_abs_margin_one.sum()), "actualOnePointFinalFraction": float(frame.actual_abs_margin_one.mean()),
                       **{name: {"ties": int(frame[f"{name}_ties"].sum()), "tieFraction": float(frame[f"{name}_ties"].sum() / n),
                                 "onePointMargins": int(frame[f"{name}_one_point_margins"].sum()), "onePointMarginFraction": float(frame[f"{name}_one_point_margins"].sum() / n),
                                 "zeroScoreDraws": int(frame[f"{name}_zero_score_draws"].sum()),
                                 "meanShiftHomeAwayFromLatent": [float(frame[f"{name}_mean_shift_home"].mean()), float(frame[f"{name}_mean_shift_away"].mean())]}
                          for name in ("nearest", "stochastic")}})
    value = {"schema": "NBA_GEN1_DEVELOPMENT_RESIDUAL_SUPPORT_AUDIT_V1", "createdAtUtc": now(),
             "population": reference(OUTPUT / "residuals.parquet"), "perGameAudit": reference(path), "script": reference(Path(__file__)),
             "scope": "Development 2021-2023 only; same-date/target exclusion; no proper-score comparison or tuning. Later residuals are retained solely for governed later use and were not used in this support audit.",
             "sourceDevelopmentGames": len(development), "eligibleTargetGames": len(table), "unsupportedTargetGames": len(ineligible),
             "unsupportedTargets": ineligible, "groups": groups,
             "sampling": {"drawsPerEligibleGame": DRAW_COUNT, "minimumEarlierDateDonors": MINIMUM_DONORS, "masterSeed": MASTER_SEED,
                          "gameSeedEngine": "NBA_GEN1_PAIRED_RESIDUAL_V1", "configuration": CONFIG,
                          "rng": "NumPy PCG64; SeedSequence child0 residual pair and child1 stochastic rounding; same sampled latent pairs for both audit roundings",
                          "residualCentering": "Subtract eligible-bank pooled HOME and AWAY means once; retain original oriented pair",
                          "nearest": "floor(max(latent,0)+0.5), no tie treatment yet",
                          "stochastic": "floor(max(latent,0)) plus Bernoulli fractional component, separate coordinate uniforms as existing simulator, no tie treatment yet",
                          "retainedLatentPopulations": False, "purpose": "Support-count diagnosis only; these draws are not published or evaluated forecasts"},
             "supportRecommendation": {"treatment": "Nearest Euclidean projection onto nonnegative untied integer HOME/AWAY score lattice; retain each original residual draw and its mass, no rejection or filtering, no unsupported OT append",
                                       "tieCase": "After nearest coordinate rounding, select the closest legal one-point neighbor to the original latent pair; use a reproducible symmetric seeded tie-break only among exact equal-distance minimizers",
                                       "limitation": "A support projection introduces one-point mass and can shift score means/winner probabilities. Actual Development one-point frequency is descriptive evidence, not an optimized target. The shifts and proper scores still require the separately declared assessment.",
                                       "notClaimed": "No observed OT mechanism, no preserved point means by construction, no guaranteed accuracy improvement"},
             "laterSeasonOutcomeScoresAssessedHere": False, "newModelFits": 0, "sourceRequests": 0}
    print(json.dumps({"developmentSupportAudit": save_new(OUTPUT / "development-support-audit.json", value), "groups": groups}), flush=True)


if __name__ == "__main__":
    support_audit(provenance())
