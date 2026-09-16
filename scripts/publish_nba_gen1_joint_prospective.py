"""Create and publish one prospective NBA Gen 1 joint-distribution comparison.

This supplements the immutable point/Elo forecast.  It reuses its exact Ridge
expectations, the frozen chronological OOF residual population, and the frozen
close-score kernel.  It never fits a model, reads a target outcome, requests
odds, or grants operational authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd

from server.sports_nba_gen1.authority import reference, verified_bytes
from server.sports_nba_gen1.close_score import canonical_population, transform
from server.sports_nba_gen1.joint_residual import (
    DRAW_COUNT, ENGINE as BASELINE_ENGINE, eligible_bank, joint_counts,
    seed as joint_seed, simulate_pair, totals_query,
)

OUT = ROOT / "outputs/nba-gen1-joint-prospective-v1"
COMPLETE = OUT / "final"
EXCHANGE = Path("C:/Users/james/asp-model-exchange/nba-gen1-research-v1/joint-comparison-v1/packages/sha256")
POINT_PACKAGE = Path("C:/Users/james/asp-model-exchange/nba-gen1-research-v1/point-elo-v1/packages/sha256/85e3d7414ccaac4b79c524096af3f7fa894169041e143ee3dc5894002f53e2e0")
POINT_ID = "nba-point:1b0f9b6fa8d5ce8adc2532664afd941eaf889b6bdf6d6a8013295c43ba1e554f"
POINT_SHA = "27f766e341cc211317d61e7ed842d7bbff7521664da5b27a0776bfc5394a8767"
GAME_ID = "nba-espn:game:401909088"
AISP_GAME_ID = "f4465955-4d0a-4e7f-8a40-f8bcebe8f5da"
TIPOFF = "2026-10-20T19:00:00+00:00"
SCHEDULE_URL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_schedules/nba_schedule_2027.parquet"
OLD_SCHEDULE_SHA = "d4ffe0d974dbec227af1ea5d731e0f36426839a170bfd0bbffc39b65f933a090"
JOINT = ROOT / "outputs/nba-gen1-joint-residual-v1"
CLOSE = ROOT / "outputs/nba-gen1-close-score-v1/completed"
HISTORY = ROOT / "outputs/nba-gen1-long-gap-v1/current-history-coverage.json"
AUTHORITY = {"researchOnly": True, "funded": False, "wageringAuthority": False,
             "stakingAuthority": False, "schedulerAuthority": False,
             "productionAuthority": False, "promotion": False}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def blob(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def ref(path: Path) -> dict:
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": digest(raw), "bytes": len(raw)}


def immutable(path: Path, raw: bytes) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Refusing to replace immutable artifact: {path}")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return ref(path)


def read_bound(bound: dict) -> bytes:
    return verified_bytes(bound)


def current_schedule_capture() -> dict:
    receipt_path = OUT / "current-schedule-capture.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_bytes())
        read_bound(receipt["sourceObject"])
        return receipt
    started = now()
    with urlopen(Request(SCHEDULE_URL, headers={"User-Agent": "ASP-Model-Studio-NBA-Research/1.0"}), timeout=45) as response:
        status = response.status
        headers = {k: v for k, v in response.headers.items()
                   if k.lower() in {"content-length", "content-type", "etag", "last-modified", "date"}}
        raw = response.read(250_001)
    captured = now()
    if status != 200 or len(raw) > 250_000:
        raise ValueError(f"Bounded schedule acquisition failed: status={status}, bytes={len(raw)}")
    sha = digest(raw)
    source = OUT / "source/sha256" / sha / "nba_schedule_2027.parquet"
    immutable(source, raw)
    columns = ["id", "date", "game_date", "season", "season_type", "type_id", "type_abbreviation",
               "neutral_site", "status_type_name", "status_type_state", "status_type_completed",
               "home_id", "home_abbreviation", "home_display_name", "away_id", "away_abbreviation",
               "away_display_name"]
    frame = pd.read_parquet(source, columns=columns)
    target = frame[frame.id.astype(str) == "401909088"]
    if len(target) != 1:
        raise ValueError("Current schedule has no unique ESPN game 401909088")
    row = target.iloc[0]
    current_tipoff = pd.Timestamp(row.date).tz_convert("UTC").isoformat()
    checks = {
        "canonicalGameId": GAME_ID, "sourceGameId": int(row.id), "awayTeam": row.away_abbreviation,
        "homeTeam": row.home_abbreviation, "scheduledTipoffUtc": current_tipoff,
        "status": row.status_type_name, "statusState": row.status_type_state,
        "completed": bool(row.status_type_completed), "neutralSite": bool(row.neutral_site),
        "seasonEnd": int(row.season), "seasonType": int(row.season_type), "typeId": int(row.type_id),
        "typeAbbreviation": row.type_abbreviation,
    }
    required = (checks["awayTeam"] == "BOS" and checks["homeTeam"] == "DET" and
                current_tipoff == TIPOFF and checks["statusState"] == "pre" and
                not checks["completed"] and not checks["neutralSite"] and
                checks["seasonEnd"] == 2027 and checks["seasonType"] == 2 and checks["typeId"] == 1)
    if not required:
        raise ValueError("Current schedule conflicts with declared game/orientation/tipoff/status")
    dates = pd.to_datetime(frame.date, utc=True)
    prior_regular = frame[(dates < pd.Timestamp(TIPOFF)) & (frame.season == 2027) &
                          (frame.season_type == 2) & (frame.type_id == 1)]
    if len(prior_regular):
        raise ValueError("An intervening 2026-27 regular-season game exists before the target")
    old = ROOT / "outputs/nba-gen1-long-gap-v1/source/sha256" / OLD_SCHEDULE_SHA / "nba_schedule_2027.parquet"
    old_ref = ref(old)
    receipt = {
        "schema": "NBA_GEN1_CURRENT_SCHEDULE_CAPTURE_V1", "downloadStartedAtUtc": started,
        "capturedAtUtc": captured, "sourceCutoffUtc": captured, "url": SCHEDULE_URL,
        "httpStatus": status, "responseHeaders": headers, "requestCount": 1,
        "bytesDownloaded": len(raw), "knownCostUsd": 0, "sourceObject": ref(source),
        "originalScheduleObject": old_ref, "physicalBytesEqualOriginal": sha == OLD_SCHEDULE_SHA,
        "originalRevisionPreserved": True, "currentRevision": f"source-bytes-sha256:{sha}",
        "target": checks, "regularSeasonGamesBeforeTarget": 0,
        "outcomeColumnsRead": [], "accountsTrialsOrPurchases": 0,
        "licenseAndUse": "Existing admitted SportsDataverse/hoopR CC BY 4.0 schedule source; metadata used for current research forecast chronology.",
    }
    immutable(receipt_path, blob(receipt))
    return receipt


def pmf(values: np.ndarray) -> list[dict]:
    unique, counts = np.unique(values.astype(np.int64), return_counts=True)
    if int(counts.sum()) != len(values):
        raise AssertionError("PMF count mismatch")
    return [{"value": int(v), "count": int(c), "probability": float(c / len(values))}
            for v, c in zip(unique, counts)]


def interval(values: np.ndarray, level: int) -> dict:
    alpha = (1 - level / 100) / 2
    lo, hi = np.quantile(values, [alpha, 1 - alpha], method="inverted_cdf")
    return {"level": level / 100, "lower": int(lo), "upper": int(hi),
            "method": "central equal-tail inverted_cdf", "units": "points including overtime"}


def summarize(draws: np.ndarray) -> dict:
    home, away = draws[:, 0], draws[:, 1]
    total, margin = home + away, home - away
    if len(draws) != DRAW_COUNT or (draws < 0).any() or (home == away).any():
        raise ValueError("Invalid complete NBA population")
    p_home = float((home > away).mean())
    mean = float(total.mean())
    integer_line = float(round(mean))
    half_line = float(math.floor(mean) + 0.5)
    return {
        "drawCount": len(draws), "scoreUnits": "points including overtime",
        "probabilityUnits": "fractions from 0 to 1", "expectedScores": {
            "homeDET": float(home.mean()), "awayBOS": float(away.mean()),
            "total": mean, "homeMarginDET": float(margin.mean())},
        "winnerProbabilities": {"homeDET": p_home, "awayBOS": 1 - p_home, "tie": 0.0,
                                "homeMcse": float(math.sqrt(p_home * (1 - p_home) / len(draws))),
                                "awayMcse": float(math.sqrt(p_home * (1 - p_home) / len(draws)))},
        "pmfs": {"home": pmf(home), "away": pmf(away), "total": pmf(total), "margin": pmf(margin)},
        "intervals": {name: [interval(values, level) for level in (50, 80, 90)]
                      for name, values in (("home", home), ("away", away), ("total", total), ("margin", margin))},
        "illustrativeTotals": [totals_query(draws, integer_line), totals_query(draws, half_line)],
    }


def verify_point_package() -> tuple[dict, dict]:
    if digest((POINT_PACKAGE / "index.json").read_bytes()) != POINT_PACKAGE.name:
        raise ValueError("Point package address changed")
    index = json.loads((POINT_PACKAGE / "index.json").read_bytes())
    for entry in index["files"]:
        raw = (POINT_PACKAGE / entry["relativePath"]).read_bytes()
        if len(raw) != entry["bytes"] or digest(raw) != entry["sha256"]:
            raise ValueError("Point package child changed: " + entry["relativePath"])
    forecast = json.loads((POINT_PACKAGE / "forecast.json").read_bytes())
    if digest((POINT_PACKAGE / "forecast.json").read_bytes()) != POINT_SHA or forecast["forecastId"] != POINT_ID:
        raise ValueError("Original point/Elo forecast changed")
    return index, forecast


def copy_artifact(source: Path, target: Path) -> dict:
    return immutable(target, Path(source).read_bytes())


def build() -> dict:
    staged_path = COMPLETE / "staged-publication.json"
    if staged_path.exists():
        staged = json.loads(staged_path.read_bytes())
        verify_package(Path(staged["packageDirectory"]))
        return staged
    capture = current_schedule_capture()
    prior_stage = OUT / "completed/staged-publication.json"
    if prior_stage.exists() and not (OUT / "completed-local-stage.json").exists():
        immutable(OUT / "completed-local-stage.json", blob({
            "schema": "NBA_GEN1_JOINT_LOCAL_STAGE_PREDECESSOR_V1", "recordedAtUtc": now(),
            "predecessor": reference(prior_stage), "published": False,
            "reason": "Preserved local stage before adding full deterministic simulation replay to final package verification",
            "methodInputsAndSeedsChanged": False,
        }))
    point_index, point = verify_point_package()
    cutoff = capture["sourceCutoffUtc"]
    if not pd.Timestamp(cutoff) < pd.Timestamp(TIPOFF):
        raise ValueError("Current schedule capture missed target cutoff")
    history = json.loads(HISTORY.read_bytes())
    read_bound(reference(HISTORY))
    for bound in history["evidence"]:
        read_bound(bound)
    if not (history["regularSeasonMembershipComplete"] and history["membershipReview"]["historyLastDate"] == "2026-04-12"):
        raise ValueError("Historical membership is not complete through 2025-26")
    if capture["regularSeasonGamesBeforeTarget"] != 0:
        raise ValueError("Current-season game should enter target history")
    joint_method = json.loads((JOINT / "method-freeze.json").read_bytes())
    joint_index = json.loads((JOINT / "index.json").read_bytes())
    close_method = json.loads((CLOSE / "method-freeze.json").read_bytes())
    close_kernel_record = json.loads((CLOSE / "frozen-development-kernel.json").read_bytes())
    # The original method freeze retains the pre-storage-fix runner; the final
    # research index binds its preserved predecessor and the byte-verified
    # executable successor.  Use that completed authority for code checks.
    for bound in joint_index["code"] + joint_index["artifacts"] + [joint_method["residuals"],
            joint_method["provenance"], close_method["frozenDevelopmentKernel"]]:
        read_bound(bound)
    residuals = pd.read_parquet(joint_method["residuals"]["path"])
    bank = eligible_bank(residuals, point["game"]["game_date"], GAME_ID)
    if len(bank) != 7209 or str(bank.game_date.max()) != "2026-04-12":
        raise ValueError("Eligible residual population changed")
    expected = np.array([point["pointExpectations"]["home"], point["pointExpectations"]["away"]])
    execution_started = now()
    simulated, offset = simulate_pair(expected, bank[["residual_home", "residual_away"]].to_numpy(), GAME_ID)
    original_order = simulated["paired"]["draws"]
    baseline = canonical_population(original_order)
    close, effects = transform(baseline, GAME_ID, close_kernel_record["kernel"])
    if not (np.array_equal(baseline.sum(axis=1), close.sum(axis=1)) and
            np.array_equal(baseline[:, 0] > baseline[:, 1], close[:, 0] > close[:, 1])):
        raise AssertionError("Close-score invariants failed")
    if not np.array_equal(baseline[np.abs(baseline[:, 0]-baseline[:, 1]) > 8],
                          close[np.abs(baseline[:, 0]-baseline[:, 1]) > 8]):
        raise AssertionError("Close-score arm changed outer margins")
    baseline_summary, close_summary = summarize(baseline), summarize(close)
    if (baseline_summary["winnerProbabilities"] != close_summary["winnerProbabilities"] or
            baseline_summary["pmfs"]["total"] != close_summary["pmfs"]["total"] or
            baseline_summary["illustrativeTotals"] != close_summary["illustrativeTotals"]):
        raise AssertionError("Winner or total preservation defect")
    donor_indices = np.random.default_rng(joint_seed(GAME_ID, "paired-donors")).integers(len(bank), size=DRAW_COUNT)
    input_audit = {
        "schema": "NBA_GEN1_JOINT_PROSPECTIVE_INPUT_AUDIT_V1", "createdAtUtc": now(),
        "sourceCutoffUtc": cutoff, "gameId": GAME_ID, "aispGameId": AISP_GAME_ID,
        "pointForecast": ref(POINT_PACKAGE / "forecast.json"), "pointPackageIndex": ref(POINT_PACKAGE / "index.json"),
        "pointForecastPreserved": True, "pointForecastRestamped": False,
        "originalScheduleRevision": point["game"]["source_revision"], "currentScheduleCapture": reference(OUT / "current-schedule-capture.json"),
        "scheduleChanged": not capture["physicalBytesEqualOriginal"],
        "gameIdentityOrientationTipoffChanged": False, "currentSeasonRegularGamesBeforeTarget": 0,
        "historyLatestGameDate": "2026-04-12", "eligibleHistoricalGames": int(history["membershipReview"]["historyGames"]),
        "eligibleOofResidualDonors": len(bank), "residualLatestDate": str(bank.game_date.max()),
        "residualTrainingChronologyValid": bool((bank.training_last_date < bank.game_date).all()),
        "inputFeatureValuesSha256": point["inputFeatureValuesSha256"], "numericalFeatureChangesSincePointForecast": [],
        "restTreatment": point["restSupportAudit"],
        "restInterpretation": "Raw 190-day regular-season gaps remain season-opening unsupported rest; treated rest fields are unavailable, not physical-rest claims.",
        "outcomeInformationAccessed": False, "modelRefits": 0,
    }
    evaluation = {
        "schema": "NBA_GEN1_JOINT_PROSPECTIVE_EVALUATION_PLAN_V1", "createdAtUtc": now(),
        "gameId": GAME_ID, "aispGameId": AISP_GAME_ID, "arms": [BASELINE_ENGINE, close_method["engine"]],
        "status": "ONE_FROZEN_PROSPECTIVE_OBSERVATION_PENDING", "sharedFinalRequired": True,
        "governedFinalRule": "Score both arms once against the same eligible final revision after the game is final; retain final identity, revision and acquisition clock.",
        "metrics": ["joint energy score", "home/away/total/margin CRPS", "winner log loss", "binary Brier", "score/margin/total absolute error", "50/80/90 interval coverage"],
        "interpretation": "One game cannot establish superiority. Historical correction repaired close-margin support; broader improvement remains unproven.",
        "authority": AUTHORITY,
    }
    receipt = {
        "schema": "NBA_GEN1_JOINT_PROSPECTIVE_SIMULATION_RECEIPT_V1", "executionStartedAtUtc": execution_started,
        "executionCompletedAtUtc": now(), "sourceCutoffUtc": cutoff, "gameId": GAME_ID,
        "drawCountPerArm": DRAW_COUNT, "baselineEngine": BASELINE_ENGINE, "baselineMasterSeed": joint_method["masterSeed"],
        "closeScoreEngine": close_method["engine"], "closeKernelSha256": close_kernel_record["kernel"]["kernelSha256"],
        "residualBank": joint_method["residuals"], "eligibleResidualDonors": len(bank),
        "bankIdentitySha256": digest("\n".join(bank.game_id).encode()), "bankColumnCenter": offset.tolist(),
        "donorIndexInt64LeSha256": digest(donor_indices.astype("<i8").tobytes()),
        "originalTemporalBaselineScorePairsInt64LeSha256": digest(original_order.astype("<i8").tobytes()),
        "publishedPopulationOrder": "LEXICOGRAPHIC_HOME_AWAY_CELL_THEN_REPLICA",
        "pairedHomeAway": True, "independentMarginalConvolution": False, "drawsDiscarded": 0,
        "scoreCaps": False, "finalTiesPerArm": [int((baseline[:,0] == baseline[:,1]).sum()), int((close[:,0] == close[:,1]).sum())],
        "closeScoreEffects": effects, "allDrawTotalsPreserved": True, "allDrawWinnersPreserved": True,
        "allOuterMarginPairsPreserved": True, "winnerProbabilitiesIdentical": True,
        "totalPmfsIdentical": True, "totalLineProbabilitiesIdentical": True,
    }
    # Preserve the first stopped local packaging attempt. It created only
    # evidence copies, then failed before any forecast or population write.
    stopped = OUT / "build"
    if stopped.exists() and not (OUT / "build-attempt-1-failure.json").exists():
        immutable(OUT / "build-attempt-1-failure.json", blob({
            "schema": "NBA_GEN1_JOINT_BUILD_ATTEMPT_FAILURE_V1", "recordedAtUtc": now(),
            "failure": "Population Parquet parent directory was absent",
            "forecastsWritten": 0, "populationsWritten": 0, "published": False,
            "filesPreserved": [ref(p) for p in sorted(x for x in stopped.rglob("*") if x.is_file())],
            "resolution": "Use completed/build with explicit population parent creation; numerical method, inputs, seeds and arms unchanged.",
        }))
    build_root = COMPLETE / "build"
    if build_root.exists():
        raise ValueError("Uncommitted build directory already exists")
    build_root.mkdir(parents=True)
    immutable(build_root / "evidence/current-schedule-capture.json", blob(capture))
    copy_artifact(ROOT / "outputs/nba-gen1-long-gap-v1/future-schedule-evidence-qualified.json",
                  build_root / "evidence/original-schedule-evidence.json")
    copy_artifact(HISTORY, build_root / "evidence/history-coverage.json")
    immutable(build_root / "evidence/input-audit.json", blob(input_audit))
    immutable(build_root / "evidence/simulation-receipt.json", blob(receipt))
    immutable(build_root / "evidence/evaluation-plan.json", blob(evaluation))
    populations = {}
    summaries = {"baseline": baseline_summary, "close_score": close_summary}
    for name, draws in (("baseline", baseline), ("close-score", close)):
        frame = pd.DataFrame({"drawIndex": np.arange(DRAW_COUNT, dtype=np.int32),
                              "homeDET": draws[:,0].astype(np.int16), "awayBOS": draws[:,1].astype(np.int16)})
        path = build_root / f"populations/{name}-joint-draws.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False, compression="zstd")
        physical = ref(path)
        populations[name] = {"logicalScorePairsInt64LeSha256": digest(draws.astype("<i8").tobytes()),
                             "artifact": {"relativePath": f"populations/{name}-joint-draws.parquet",
                                          "sha256": physical["sha256"], "bytes": physical["bytes"]},
                             "drawCount": DRAW_COUNT}
    created = now()
    arms = []
    for key, label, engine in (("baseline", "paired residual baseline", BASELINE_ENGINE),
                               ("close-score", "close-score correction", close_method["engine"])):
        summary_key = "baseline" if key == "baseline" else "close_score"
        body = {
            "schema": "NBA_GEN1_JOINT_RESEARCH_FORECAST_V1", "createdAtUtc": created,
            "sourceCutoffUtc": cutoff, "publishedAtUtc": None, "game": point["game"], "aispGameId": AISP_GAME_ID,
            "arm": key, "label": label, "configurationIdentity": engine,
            "supplementsForecastId": POINT_ID, "supplementsForecastSha256": POINT_SHA,
            "ridgePointExpectations": point["pointExpectations"], "separateEloProbabilities": point["winnerProbabilities"],
            "jointSimulation": summaries[summary_key], "population": populations[key], "authority": AUTHORITY,
            "limitations": ["Historical donors are Category A finalized-record reconstruction with unknown original revision vintages",
                            "No player, lineup, injury, possession or box inputs", "Simulation MCSE is numerical precision, not model uncertainty",
                            "Joint-derived winner probability is separate from Elo", "First prospective joint comparison; no superiority claim"],
        }
        identity = digest(blob(body))
        body["forecastId"] = f"nba-joint:{identity}"
        arm_path = build_root / f"forecasts/{key}.json"
        immutable(arm_path, blob(body))
        physical_forecast = ref(arm_path)
        arms.append({"arm": key, "configurationIdentity": engine, "forecastId": body["forecastId"],
                     "forecast": {"relativePath": f"forecasts/{key}.json",
                                  "sha256": physical_forecast["sha256"], "bytes": physical_forecast["bytes"]},
                     "population": populations[key]})
    indexed_files = []
    for path in sorted(p for p in build_root.rglob("*") if p.is_file()):
        bound = ref(path)
        indexed_files.append({"relativePath": path.relative_to(build_root).as_posix(),
                              "sha256": bound["sha256"], "bytes": bound["bytes"]})
    index = {
        "schemaVersion": "NBA_GEN1_JOINT_COMPARISON_EXCHANGE_INDEX_V1", "createdAtUtc": created,
        "artifactKind": "PROSPECTIVE_RESEARCH_JOINT_DISTRIBUTION_COMPARISON", "game": point["game"],
        "aispGameId": AISP_GAME_ID, "sourceCutoffUtc": cutoff, "arms": arms,
        "pointEloForecast": {"forecastId": POINT_ID, "forecastSha256": POINT_SHA,
                             "packageIndexSha256": POINT_PACKAGE.name, "preserveExistingCard": True},
        "bindings": {"jointMethod": reference(JOINT / "method-freeze.json"),
                     "jointResearchIndex": reference(JOINT / "index.json"),
                     "closeMethod": reference(CLOSE / "method-freeze.json"),
                     "closeResearchIndex": reference(ROOT / "outputs/nba-gen1-close-score-v1/index.json"),
                     "frozenCloseKernel": reference(CLOSE / "frozen-development-kernel.json"),
                     "publisherExecutable": reference(Path(__file__))},
        "localStagePredecessor": reference(OUT / "completed/staged-publication.json") if
            (OUT / "completed/staged-publication.json").exists() else None,
        "files": indexed_files, "publicationClock": "Separate publication-receipt.json; forecast publishedAtUtc remains null.",
        "idempotency": {"key": ["forecastId", "forecastSha256"], "sameBytes": "NO_DUPLICATE",
                        "differentBytesSameId": "REJECT"}, "authority": AUTHORITY,
        "consumerAcknowledged": False, "forecastCount": 2,
    }
    index_raw = blob(index)
    package_sha = digest(index_raw)
    package = COMPLETE / "package/sha256" / package_sha
    for path in sorted(p for p in build_root.rglob("*") if p.is_file()):
        copy_artifact(path, package / path.relative_to(build_root))
    immutable(package / "index.json", index_raw)
    handoff = handoff_markdown(package_sha, index, summaries, populations)
    immutable(package / "CLAUDE_HANDOFF.md", handoff.encode("utf-8"))
    verify_package(package)
    staged = {"schema": "NBA_GEN1_JOINT_COMPARISON_STAGING_V1", "createdAtUtc": now(),
              "packageDirectory": str(package), "destinationDirectory": str(EXCHANGE / package_sha),
              "index": ref(package / "index.json"), "handoff": ref(package / "CLAUDE_HANDOFF.md"),
              "forecastCount": 2, "simulationCount": 2, "consumerAcknowledged": False}
    immutable(staged_path, blob(staged))
    return staged


def handoff_markdown(package_sha: str, index: dict, summaries: dict, populations: dict) -> str:
    b, c = summaries["baseline"], summaries["close_score"]
    destination = EXCHANGE / package_sha
    def line(q):
        x = b["illustrativeTotals"][q]
        return f"{x['line']}: Over {x['over']['win']:.4f}, push {x['over']['push']:.4f}, Under {x['under']['win']:.4f}"
    return f"""# CLAUDE_HANDOFF — NBA joint simulation early research comparison

Import `{destination / 'index.json'}`. Package/physical index SHA-256: `{package_sha}`.

Bind both arms idempotently to ESPN `401909088`, canonical `{GAME_ID}`, and AISP `{AISP_GAME_ID}`. Preserve the existing point/Elo card `{POINT_ID}`; this package supplements it with a separate **NBA joint simulation — early research comparison**. Verify raw bytes without newline normalization, index hash equals the package directory, then every indexed file and both population Parquets.

Both arms contain 10,000 paired full-game final-score draws including overtime, zero ties, complete home/away/total/margin PMFs and 50/80/90 intervals. Baseline configuration: `{BASELINE_ENGINE}`. Correction: `{index['arms'][1]['configurationIdentity']}`. The correction uses the frozen radius-eight kernel, changes only close margins, and preserves every winner, total and denominator. Winner probabilities, total PMFs and totals queries are therefore identical.

Baseline joint: BOS {b['winnerProbabilities']['awayBOS']:.4f}, DET {b['winnerProbabilities']['homeDET']:.4f}; expected BOS {b['expectedScores']['awayBOS']:.3f}, DET {b['expectedScores']['homeDET']:.3f}, total {b['expectedScores']['total']:.3f}. Close-score expected BOS {c['expectedScores']['awayBOS']:.3f}, DET {c['expectedScores']['homeDET']:.3f}. Separate Elo remains BOS 0.41887505293332616 / DET 0.5811249470666738; label it as an independent model output, never as the joint population.

Illustrative totals, not recorded sportsbook lines: {line(0)}; {line(1)}. Units are fractions from 0 to 1. Use each query's explicit win/push/loss fields.

Import by each arm's `(forecastId, forecast physical SHA-256)` and reject conflicting bytes. Store source cutoff and forecast creation separately from `publication-receipt.json` publication time. Display distributions, intervals, simulation MCSE and limitations. Keep wagering, funding, staking, scheduling and promotion disabled. This is the first prospective joint comparison and one pending observation, not evidence of superiority.

After actual import and display verification, write a consumer receipt under `{EXCHANGE.parents[1] / 'consumer-receipts'}` with package digest, both forecast IDs/hashes, ESPN/canonical/AISP identities, imported count, idempotent reimport result, display checks and times. Publication alone is not acknowledgement.
"""


def verify_package(package: Path) -> dict:
    package = Path(package).resolve()
    index_raw = (package / "index.json").read_bytes()
    if digest(index_raw) != package.name:
        raise ValueError("Package directory differs from physical index digest")
    index = json.loads(index_raw)
    for bound in index["bindings"].values():
        read_bound(bound)
    for entry in index["files"]:
        path = (package / entry["relativePath"]).resolve()
        if not path.is_relative_to(package):
            raise ValueError("Package child escapes root")
        raw = path.read_bytes()
        if len(raw) != entry["bytes"] or digest(raw) != entry["sha256"]:
            raise ValueError("Package child changed: " + entry["relativePath"])
    for arm in index["arms"]:
        raw = (package / f"forecasts/{arm['arm']}.json").read_bytes()
        if digest(raw) != arm["forecast"]["sha256"] or len(raw) != arm["forecast"]["bytes"]:
            raise ValueError("Forecast physical identity changed")
        pop = pd.read_parquet(package / f"populations/{arm['arm']}-joint-draws.parquet")
        draws = pop[["homeDET", "awayBOS"]].to_numpy(np.int64)
        pop_raw = (package / arm["population"]["artifact"]["relativePath"]).read_bytes()
        if (len(pop_raw) != arm["population"]["artifact"]["bytes"] or
                digest(pop_raw) != arm["population"]["artifact"]["sha256"]):
            raise ValueError("Population physical identity changed")
        if len(draws) != DRAW_COUNT or digest(draws.astype("<i8").tobytes()) != arm["population"]["logicalScorePairsInt64LeSha256"]:
            raise ValueError("Population logical identity changed")
        forecast = json.loads(raw)
        if forecast["forecastId"] != arm["forecastId"] or forecast["game"]["game_id"] != GAME_ID:
            raise ValueError("Forecast identity binding changed")
    # Independently replay both arms from the exact point expectations,
    # residual bank, game identity and frozen kernel. No outcome is loaded.
    _, point = verify_point_package()
    method = json.loads(read_bound(index["bindings"]["jointMethod"]))
    residuals = pd.read_parquet(method["residuals"]["path"])
    bank = eligible_bank(residuals, point["game"]["game_date"], GAME_ID)
    expected = np.array([point["pointExpectations"]["home"], point["pointExpectations"]["away"]])
    replayed, _ = simulate_pair(expected, bank[["residual_home", "residual_away"]].to_numpy(), GAME_ID)
    baseline = canonical_population(replayed["paired"]["draws"])
    kernel = json.loads(read_bound(index["bindings"]["frozenCloseKernel"]))["kernel"]
    corrected, effects = transform(baseline, GAME_ID, kernel)
    replay = {"baseline": baseline, "close-score": corrected}
    for arm in index["arms"]:
        draws = replay[arm["arm"]]
        if digest(draws.astype("<i8").tobytes()) != arm["population"]["logicalScorePairsInt64LeSha256"]:
            raise ValueError("Deterministic population replay differs")
        forecast = json.loads((package / arm["forecast"]["relativePath"]).read_bytes())
        if summarize(draws) != forecast["jointSimulation"]:
            raise ValueError("Deterministic forecast summary replay differs")
    if not (np.array_equal(baseline.sum(axis=1), corrected.sum(axis=1)) and
            np.array_equal(baseline[:,0] > baseline[:,1], corrected[:,0] > corrected[:,1]) and
            effects["noDrawDropped"] and effects["outerMarginsExact"]):
        raise ValueError("Replay failed correction invariants")
    return {"status": "VERIFIED", "index": ref(package / "index.json"), "files": len(index["files"]),
            "deterministicReplay": True, "replayedDrawsPerArm": DRAW_COUNT,
            "winnerTotalAndOuterMarginInvariants": True}


def publish() -> dict:
    staged = build()
    local_receipt = COMPLETE / "publication-receipt.json"
    if local_receipt.exists():
        receipt = json.loads(local_receipt.read_bytes())
        verify_package(Path(receipt["index"]["path"]).parent)
        return receipt
    source = Path(staged["packageDirectory"])
    target = Path(staged["destinationDirectory"])
    if target.parent.resolve() != EXCHANGE.resolve() or target.name != staged["index"]["sha256"]:
        raise ValueError("Unexpected exchange destination")
    if datetime.now(timezone.utc) >= datetime.fromisoformat(TIPOFF):
        raise ValueError("Target game has started")
    started = now()
    delivered = []
    for path in sorted(p for p in source.rglob("*") if p.is_file() and p.name != "index.json"):
        delivered.append(copy_artifact(path, target / path.relative_to(source)))
    delivered.append(copy_artifact(source / "index.json", target / "index.json"))
    verification = verify_package(target)
    receipt = {"schemaVersion": "NBA_GEN1_JOINT_COMPARISON_PUBLICATION_V1", "status": "PUBLISHED",
               "publicationStartedAtUtc": started, "publishedAtUtc": now(), "index": verification["index"],
               "handoff": ref(target / "CLAUDE_HANDOFF.md"), "files": delivered,
               "fileCount": len(delivered), "bytes": sum(x["bytes"] for x in delivered),
               "forecastCount": 2, "importedCount": 0, "displayConfirmedCount": 0,
               "consumerAcknowledged": False, "existingPointForecastChanged": False,
               "researchOnly": True, "wageringAuthority": False, "schedulerAuthority": False}
    raw = blob(receipt)
    immutable(target / "publication-receipt.json", raw)
    immutable(local_receipt, raw)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--capture", action="store_true")
    modes.add_argument("--build", action="store_true")
    modes.add_argument("--publish", action="store_true")
    modes.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.capture:
        result = current_schedule_capture()
    elif args.build:
        result = build()
    elif args.publish:
        result = publish()
    else:
        staged = json.loads((COMPLETE / "staged-publication.json").read_bytes())
        result = verify_package(Path(staged["packageDirectory"]))
        if (COMPLETE / "publication-receipt.json").exists():
            result["publication"] = publish()
    print(json.dumps(result, indent=2))
