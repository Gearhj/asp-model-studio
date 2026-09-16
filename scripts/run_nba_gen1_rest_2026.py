"""Freeze, assess, then separately refit one declared NBA rest correction.

Freeze never opens 2026 evidence. Assessment consumes only an independently
admitted, identity-frozen normalized population, using the three frozen models.
No acquisition, simulator, model selection, publication or scheduler is started.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_nba_gen1.authority import reference, verified_bytes, RESEARCH_FLAGS
from server.sports_nba_gen1.recent_features import FEATURE_COLUMNS, build_recent_features
from server.sports_nba_gen1.recent_study import (
    now, save, predict, assess, pair_interval, fit_bound as fit_original_bound,
)
from server.sports_nba_gen1.rest_study import (
    code_bindings, fit_bound as fit_rest_bound, grouped_results,
)


VERSION = "NBA_GEN1_REST_FIXED_2026_ASSESSMENT_V1"
MODEL_IDS = ("elo", "ridge_a100", "ridge_a100_rest")


def project_context(events):
    """Project only known date-context metadata into the unchanged feature API."""
    allowed = {"game_id", "game_date", "season_end", "team_ids", "classification", "source_row_numbers"}
    projected = []
    for event in events:
        if not isinstance(event, dict) or set(event) - allowed - {"source_game_id"}:
            raise ValueError("Context projection rejects outcome fields and unknown metadata")
        if "source_game_id" in event:
            source_id = event["source_game_id"]
            if (isinstance(source_id, bool) or not isinstance(source_id, int) or source_id < 0
                    or event.get("game_id") != f"nba-espn:game:{source_id}"):
                raise ValueError("Context source-game alias does not bind its canonical ESPN identity")
        projected.append({key: value for key, value in event.items() if key in allowed})
    return projected


def verify_references(value):
    if isinstance(value, dict):
        if {"path", "sha256", "bytes"}.issubset(value):
            verified_bytes(value)
        else:
            for item in value.values():
                verify_references(item)
    elif isinstance(value, list):
        for item in value:
            verify_references(item)


def _load(path):
    return json.loads(Path(path).read_bytes())


def _capture_runner(root, label):
    """Retain the exact driver bytes; later fixes cannot erase execution code."""
    original = Path(__file__).resolve()
    bound = reference(original)
    path = root / "execution-code" / bound["sha256"] / original.name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = verified_bytes(bound)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("Immutable execution-code collision")
    if not path.exists():
        path.write_bytes(raw)
    return {"purpose": label, "retainedRunner": reference(path), "numericalModules": code_bindings()}


def _declaration(root):
    path = root / "declaration.json"
    value = _load(path)
    if (value.get("configuration") != "NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1"
            or value["roles"]["newAssessmentSeason"] != 2026
            or value["roles"]["newAssessmentTrainingSeasons"] != list(range(2020, 2026))):
        raise ValueError("The fixed one-treatment, 2026 assessment declaration is required")
    return value, reference(path)


def _frozen(root):
    path = root / "assessment-2026-freeze.json"
    value = _load(path)
    verify_references(value)
    if (value.get("schema") != VERSION + "_FREEZE"
            or value.get("trainingThroughSeasonEnd") != 2025
            or value.get("outcomes2026Accessed") is not False
            or set(value.get("models", {})) != set(MODEL_IDS)):
        raise ValueError("Exact pre-2026-outcome model freeze required")
    _, declaration_ref = _declaration(root)
    if value["declaration"] != declaration_ref:
        raise ValueError("Study declaration changed after model freeze")
    return value, reference(path)


def freeze(root):
    root = Path(root).resolve()
    path = root / "assessment-2026-freeze.json"
    if path.exists():
        _, bound = _frozen(root)
        return {"status": "REUSED_FROZEN_MODELS_NO_NEW_FIT", "freeze": bound}
    _, declaration_ref = _declaration(root)
    prior = root.parent / "nba-gen1-recent-v1"
    feature_path = prior / "holdout/features.parquet"
    prior_receipt_path = prior / "post-assessment-refit/receipt.json"
    prior_receipt = _load(prior_receipt_path)
    original_models = {name: prior_receipt["models"][name] for name in ("elo", "ridge_a100")}
    verify_references(original_models)
    code = _capture_runner(root, "FREEZE_OLD_HISTORY_ONLY")
    start = save(root / "assessment-2026-freeze-start.json", {
        "createdAtUtc": now(), "declaration": declaration_ref,
        "oldFeatures": reference(feature_path), "oldRefitReceipt": reference(prior_receipt_path),
        "code": code, "source2026FilesOpened": False,
    })
    # The only feature/outcome population read in this stage is the completed,
    # previously assessed 2020-2025 historical study. No 2026 file is opened.
    features = pd.read_parquet(feature_path)
    if len(features) != 7059 or set(features.season_end) != set(range(2020, 2026)):
        raise ValueError("The exact 7,059-game prior historical population is required")
    train = features[features.target_eligible].copy()
    if len(train) != 6952 or train.neutral_site.any():
        raise ValueError("The exact 6,952 oriented training games are required")
    ids = train.game_id.astype(str).tolist()
    for name, bound in original_models.items():
        if bound["trainingGameIds"] != ids or bound["trainingLastDate"] != str(train.game_date.max()):
            raise ValueError(f"Original {name} does not bind the common frozen training population")
    model, correction = fit_rest_bound(train, root / "assessment-2026-frozen-models")
    if list(model.training_game_ids) != ids:
        raise ValueError("Rest model training identities differ from the original models")
    value = {
        "schema": VERSION + "_FREEZE", "createdAtUtc": now(), "declaration": declaration_ref,
        "executionStart": start, "code": code, "trainingThroughSeasonEnd": 2025,
        "trainingLastDate": str(train.game_date.max()), "trainingGames": len(train),
        "historyGames": len(features), "outcomes2026Accessed": False,
        "oldFeatures": reference(feature_path), "oldRefitReceipt": reference(prior_receipt_path),
        "models": {**original_models, "ridge_a100_rest": correction},
        "comparison": "All eligible oriented 2026 games; no further configuration selection or tuning.",
        "winnerChannel": "UNCHANGED_CHRONOLOGICAL_ELO_FOR_ALL_THREE_POINT_ARMS",
        "distributionStatus": "No joint distribution: existing overtime evidence gate remains unchanged.",
        "authority": RESEARCH_FLAGS,
    }
    return {"status": "FROZEN_BEFORE_2026_OUTCOME_ACCESS", "freeze": save(path, value),
            "trainingGames": len(train), "ordinaryRestMaximumDays": model.rest_support["maximumDays"]}


def _admitted_new_population(root, frozen_ref):
    reconciliation_path = root / "reconciliation-2026.json"
    reconciliation = _load(reconciliation_path)
    verify_references(reconciliation)
    if reconciliation.get("modelFreeze") != frozen_ref:
        raise ValueError("Normalized 2026 evidence must bind this exact model freeze")
    cohort_ref = reconciliation["cohort"]
    cohort = json.loads(verified_bytes(cohort_ref))
    games_ref = reconciliation["gamesArtifact"]
    games = pd.read_parquet(games_ref["path"])
    if set(games.season_end) != {2026} or games.game_id.duplicated().any():
        raise ValueError("Normalized source must contain one intact row per admitted 2026 game")
    admitted = pd.DataFrame(cohort["admittedGames"])
    if (admitted.empty or admitted.game_id.duplicated().any()
            or set(admitted.season_end) != {2026}):
        raise ValueError("A unique metadata-frozen 2026 game population is required")
    if set(games.game_id) != set(admitted.game_id):
        raise ValueError("2026 normalized identities differ from the metadata-frozen cohort")
    if set(games.loc[games.target_eligible, "game_id"]) != set(admitted.loc[admitted.target_eligible, "game_id"]):
        raise ValueError("2026 oriented targets differ from the metadata-frozen cohort")
    metadata = ("season_end", "game_date", "home_team_id", "away_team_id", "home_team_code",
                "away_team_code", "neutral_site", "orientation", "target_eligible")
    left, right = games.set_index("game_id").sort_index(), admitted.set_index("game_id").sort_index()
    for column in metadata:
        if not np.array_equal(left[column].to_numpy(), right[column].to_numpy()):
            raise ValueError(f"Normalized 2026 {column} differs from its frozen metadata")
    if games.loc[games.target_eligible, "neutral_site"].any():
        raise ValueError("A neutral game entered the 2026 oriented assessment")
    return games, reconciliation, {
        "reconciliation": reference(reconciliation_path), "cohort": cohort_ref, "games": games_ref,
    }


def assess_2026(root):
    root = Path(root).resolve()
    frozen, frozen_ref = _frozen(root)
    folder = root / "assessment-2026"
    receipt_path = folder / "receipt.json"
    if receipt_path.exists():
        value = _load(receipt_path)
        verify_references(value)
        return {"status": "REUSED_IMMUTABLE_2026_ASSESSMENT", "receipt": reference(receipt_path)}
    if folder.exists():
        raise ValueError("Partial 2026 assessment exists; inspect it rather than repeat silently")
    # Verify the normalization and its metadata/source/model bindings before
    # opening the new score rows. Record the driver prior to their first read.
    recon_ref = reference(root / "reconciliation-2026.json")
    recon = json.loads(verified_bytes(recon_ref))
    verify_references(recon)
    if recon.get("modelFreeze") != frozen_ref:
        raise ValueError("2026 normalization is bound to a different model freeze")
    folder.mkdir(parents=True)
    start = save(folder / "execution-start.json", {
        "createdAtUtc": now(), "freeze": frozen_ref, "reconciliation": recon_ref,
        "code": _capture_runner(root, "ONE_FIXED_2026_ASSESSMENT"),
        "status": "BEFORE_OPENING_NORMALIZED_2026_SCORE_ROWS",
    })
    new_games, new_reconciliation, new_refs = _admitted_new_population(root, frozen_ref)
    prior = root.parent / "nba-gen1-recent-v1/holdout"
    old_games = pd.read_parquet(prior / "games.parquet")
    old_features = pd.read_parquet(frozen["oldFeatures"]["path"])
    old_reconciliation = _load(prior / "reconciliation.json")
    if set(old_games.game_id) & set(new_games.game_id):
        raise ValueError("New and old game identities overlap")
    if not (new_games.game_date > old_games.game_date.max()).all():
        raise ValueError("New season dates do not follow the frozen training population")
    games = pd.concat((old_games, new_games), ignore_index=True, sort=False)
    # Retain the heterogeneous publisher keys as opaque strings in the combined
    # history. Original integer ESPN IDs and source bytes remain untouched in
    # the bound new-population artifact; no game/team identity is reconstructed.
    games["source_game_id"] = games.source_game_id.astype(str)
    contexts = project_context(old_reconciliation["contextOnlyEvents"] + new_reconciliation["contextOnlyEvents"])
    features, feature_audit = build_recent_features(games, context_events=contexts)
    expected = old_features.set_index("game_id").sort_index()
    rebuilt = features.set_index("game_id").loc[expected.index].sort_index()
    old_values = expected[list(FEATURE_COLUMNS)].to_numpy(float)
    rebuilt_values = rebuilt[list(FEATURE_COLUMNS)].to_numpy(float)
    if len(expected) != 7059 or not np.array_equal(old_values, rebuilt_values, equal_nan=True):
        raise ValueError("Adding 2026 history changed the original 7,059 rows' 78 numeric inputs")
    target = features[(features.season_end == 2026) & features.target_eligible].copy()
    ledger = pd.concat([predict(frozen["models"][name], target) for name in MODEL_IDS], ignore_index=True)
    if ledger.duplicated(["game_id", "model_id"]).any():
        raise ValueError("Duplicate 2026 assessment game/model rows")
    if not ledger.groupby("game_id").p_home_win.nunique().eq(1).all():
        raise ValueError("Independent frozen Elo winner probabilities differ between point arms")
    correction = joblib.load(frozen["models"]["ridge_a100_rest"]["artifact"]["path"])
    rest_audit = correction.support_audit(target)
    rest_audit["season_end"] = 2026
    games.to_parquet(folder / "games.parquet", index=False)
    features.to_parquet(folder / "features.parquet", index=False)
    ledger.to_parquet(folder / "predictions.parquet", index=False)
    rest_audit.to_parquet(folder / "rest-input-audit.parquet", index=False)
    context_ref = save(folder / "history-context.json", {
        "schema": VERSION + "_HISTORY_CONTEXT", "contextOnlyEvents": contexts,
        "projection": "Known identity/date fields only for unchanged feature API; duplicate ESPN source_game_id alias validated and retained in original reconciliation.",
        "oldReconciliation": reference(prior / "reconciliation.json"), "newReconciliation": new_refs["reconciliation"],
        "newSourceAcquisition": reference(root / "acquisition-2026.json"),
    })
    result = assess(ledger)
    result.update(
        pairedCorrectionVersusOriginal=pair_interval(ledger, "ridge_a100_rest", "ridge_a100"),
        supportGroups=grouped_results(ledger, rest_audit),
        status="FIXED_NEW_2026_CATEGORY_A_HISTORICAL_ASSESSMENT_NOT_PROSPECTIVE",
        noFurtherSelection=True, noScoreClipping=True,
        ordinaryRestMaximumDays=correction.rest_support["maximumDays"],
    )
    artifacts = {
        "executionStart": start, "games": reference(folder / "games.parquet"),
        "features": reference(folder / "features.parquet"), "predictions": reference(folder / "predictions.parquet"),
        "restInputAudit": reference(folder / "rest-input-audit.parquet"), "historyContext": context_ref,
        "assessment": save(folder / "assessment.json", result),
        "featureAudit": save(folder / "feature-audit.json", feature_audit),
    }
    verification = {
        "original7059FeatureRowsExactlyUnchanged": True, "numericFeaturesCompared": len(FEATURE_COLUMNS),
        "commonOrientedAssessmentGames": len(target), "sameEloProbabilitiesAllArms": True,
        "historyStrictlyEarlier": bool((ledger.history_latest_game_date < ledger.game_date).all()),
        "probabilityMassMaximumError": float(abs(ledger.p_home_win + ledger.p_away_win + ledger.p_tie - 1).max()),
        "originalForecastsReplaced": False, "simulationDraws": 0, "jointDistributionValidated": False,
    }
    if not verification["historyStrictlyEarlier"]:
        raise ValueError("Current or future game outcomes entered a target's feature history")
    artifacts["verification"] = save(folder / "verification.json", verification)
    receipt = {
        "schema": VERSION + "_ASSESSMENT_RECEIPT", "createdAtUtc": now(), "freeze": frozen_ref,
        "evidenceClass": "A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION", "assessmentSeasonEnd": 2026,
        "distinctAssessmentGames": len(target), "source": new_refs, "artifacts": artifacts,
        "authority": RESEARCH_FLAGS, "prospectiveForecastsPublished": 0,
        "distributionStatus": "No joint energy, CRPS, intervals or tie-resolution assessment without required overtime evidence.",
    }
    return {"status": "ASSESSED_FIXED_2026_POPULATION_ONCE", "receipt": save(receipt_path, receipt),
            "overall": result["overall"], "verification": verification}


def refit(root):
    root = Path(root).resolve()
    folder = root / "current-research"
    receipt_path = folder / "receipt.json"
    if receipt_path.exists():
        value = _load(receipt_path)
        verify_references(value)
        return {"status": "REUSED_CURRENT_RESEARCH_REFIT", "receipt": reference(receipt_path)}
    frozen, frozen_ref = _frozen(root)
    assessment_ref = reference(root / "assessment-2026/receipt.json")
    assessment = json.loads(verified_bytes(assessment_ref))
    verify_references(assessment)
    if assessment.get("freeze") != frozen_ref or assessment.get("assessmentSeasonEnd") != 2026:
        raise ValueError("Completed immutable assessment of this model freeze is required before refit")
    if folder.exists():
        raise ValueError("Partial current-research refit exists; inspect rather than overwrite")
    folder.mkdir(parents=True)
    start = save(folder / "execution-start.json", {
        "createdAtUtc": now(), "completedAssessment": assessment_ref, "freeze": frozen_ref,
        "code": _capture_runner(root, "SEPARATE_POST_ASSESSMENT_REFIT"),
        "selection": "Already declared rest-Ridge alpha100 plus unchanged chronological Elo recipe; no new selection.",
    })
    features = pd.read_parquet(assessment["artifacts"]["features"]["path"])
    if set(features.season_end) != set(range(2020, 2027)):
        raise ValueError("Refit requires all admitted historical seasons through 2026")
    train = features[features.target_eligible].copy()
    _, corrected = fit_rest_bound(train, folder / "models")
    elo = fit_original_bound({"id": "elo", "family": "elo", "params": {}}, train, folder / "models")
    acquisition_ref = reference(root / "acquisition-2026.json")
    acquisition = json.loads(verified_bytes(acquisition_ref))
    acquired = acquisition.get("acquiredAtUtc", acquisition.get("completedAtUtc", acquisition.get("capturedAtUtc")))
    if acquired is None:
        raise ValueError("Actual new-source acquisition clock must remain explicit")
    history = {
        "games": assessment["artifacts"]["games"], "features": assessment["artifacts"]["features"],
        "contextMetadata": assessment["artifacts"]["historyContext"], "acquisition": acquisition_ref,
        "sourceReconciliation": assessment["source"]["reconciliation"],
    }
    value = {
        "schema": VERSION + "_CURRENT_RESEARCH_REFIT", "createdAtUtc": now(),
        "executionStart": start, "completedAssessment": assessment_ref, "freeze": frozen_ref,
        "configurationIdentity": "NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1",
        "models": {"ridge_a100_rest": corrected, "elo": elo}, "history": history,
        "trainingThroughSeasonEnd": 2026, "trainingGames": len(train), "historyGames": len(features),
        "latestRecordedGameDate": str(features.game_date.max()), "sourceAcquiredAtUtc": acquired,
        "evidenceClass": "A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION", "authority": RESEARCH_FLAGS,
        "futureScheduleAvailable": False, "genuineFutureForecastPublished": False,
        "winnerChannel": "Independent chronological Elo; expected scores come from rest-Ridge, not a joint simulation population.",
        "distributionStatus": "No joint home/away draws or validated score distributions; existing overtime prerequisites remain missing.",
        "numericalModules": code_bindings(),
    }
    return {"status": "REFITTED_SEPARATE_CURRENT_RESEARCH_ARTIFACTS", "receipt": save(receipt_path, value),
            "trainingGames": len(train), "latestRecordedGameDate": value["latestRecordedGameDate"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("freeze", "assess", "refit"), required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/nba-gen1-long-gap-v1")
    args = parser.parse_args()
    result = {"freeze": freeze, "assess": assess_2026, "refit": refit}[args.stage](args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
