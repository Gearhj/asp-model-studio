"""Bounded team-only MLB preview research. No acquisition, scheduler or AISP writes.

Historical date reconstruction is NOT a publication-vintage certification.
Raw sources remain quarantined; only this separately identified research
derivative is fitted. 2025/2026 source partitions are never opened here.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import zipfile

import numpy as np
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

from .show_preview import canonical, digest, immutable, physical, clocks, utc

CONFIG = "MLB_TEAM_LOGISTIC_C1_POISSON_A1_SHOW_PREVIEW_V1"
FEATURES = [side + "_" + name for side in ("away", "home") for name in (
    "recent60_rf_shrunk20", "recent60_ra_shrunk20", "recent60_win_shrunk20",
    "prior_season_rf_shrunk40", "prior_season_ra_shrunk40", "prior_season_win_shrunk40",
    "recent_support_fraction", "season_support_fraction")]
FEATURE_CONTRACT = {"schema": "MLB_TEAM_SHOW_PREVIEW_FEATURE_CONTRACT_V1", "orderedFeatures": FEATURES,
    "designSha256": "0e96d068e13fd3a697b6a8179d679fba2aca1ff953ed65362f7c03b793d555f2",
    "cutoff": "16:00 America/New_York previous calendar day; exclude that whole calendar day from score histories",
    "prior": "prior-season team means shrunk by 40 games to the mean of all earlier-season team-game records",
    "recent": "last up to 60 completed current-season games, shrunk by 20 games to prior",
    "units": "runs per team game; win fraction; support divided by 60 or 162",
    "missingPriorTeam": "earlier league prior; no invented player evidence",
    "missingCurrentHistory": "unavailable unless owner certifies complete source coverage; zero games only at a genuine season opening"}
BRONZE_SHA = "fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a"


def retained_population(bronze, silver, metadata_receipt):
    """Verify identities and season-only receipt before selecting any scores.

Retain final scores only, no box statistics, pitchers, target lineups or odds.
Completion dates delay historical donors; calendar days <= D-2 are eligible.
The conservative day exclusion gives up every preceding-day result, including
afternoon games which might actually have been available by 16:00 ET.
"""
    inspected = json.loads(Path(metadata_receipt).read_bytes())
    if inspected["outcome_values_retained"] is not False:
        raise ValueError("identity-first receipt required")
    inspected_ids = {r["gameId"]: r for r in inspected["rows"]}
    if not inspected_ids or any(r["season"] not in range(2019, 2025) for r in inspected_ids.values()):
        raise ValueError("sealed season rejected before outcome access")
    mp = Path(bronze) / "manifests/bronze-manifest.json"
    raw = mp.read_bytes()
    if digest(raw) != BRONZE_SHA:
        raise ValueError("bronze manifest changed")
    manifest = json.loads(raw)
    import pyarrow.parquet as pq
    dp = Path(silver) / "objects/sha256/1afa766640c202742f270184b81a26056080c79a2a726279e1cb961b7e78e456/object.parquet"
    # This projection contains identity only; no scores or PA outcomes.
    dims = pq.read_table(dp, columns=["canonicalGameId", "retrosheetGameId", "season", "gameType", "reconciliationStatus"]).to_pylist()
    if any(int(r["season"]) not in range(2019, 2025) for r in dims):
        raise ValueError("unexpected identity season")
    exact = {r["retrosheetGameId"]: r["canonicalGameId"] for r in dims
             if r["gameType"] == "R" and r["reconciliationStatus"] == "MATCHED_EXACT"}
    rows, exclusions, refs = [], [], [physical(mp), physical(dp), physical(metadata_receipt)]
    for part in manifest["partitions"]:
        if part["source"] != "retrosheet" or part.get("scope") != "game-logs":
            continue
        year = part["year"]
        if year not in range(2019, 2025):
            raise ValueError("sealed partition rejected before open")
        path = Path(bronze) / part["relativePath"]
        content = path.read_bytes()
        if digest(content) != part["fileSha256"]:
            raise ValueError("source archive changed")
        refs.append({**physical(path), "acquired_utc": part["retrievalUtc"], "season": year})
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for line, f in enumerate(csv.reader(io.StringIO(z.read(f"gl{year}.txt").decode("latin-1")))):
                if len(f) != 161 or int(f[0][:4]) != year:
                    raise ValueError("source schema/season mismatch")
                gid = f[6] + f[0] + f[1]
                meta = inspected_ids[gid]
                if gid not in exact or meta["forfeit"] or meta["protest"]:
                    exclusions.append({"gameId": gid, "reason": "IDENTITY_OR_DISPUTED_RESULT"})
                    continue
                day = datetime.strptime(f[0], "%Y%m%d").date()
                completion = datetime.strptime(meta["completion"], "%Y%m%d").date() if meta["completion"] else day
                away, home = int(f[9]), int(f[10])
                if away == home or min(away, home) < 0:
                    exclusions.append({"gameId": gid, "reason": "TIE_OR_INVALID_SCORE"})
                    continue
                rows.append({"id": gid, "canonical_id": exact[gid], "date": day.isoformat(),
                             "completion_date": completion.isoformat(), "season": year,
                             "away": f[3], "home": f[6], "away_score": away, "home_score": home,
                             "source_archive_sha256": part["fileSha256"], "source_line": line,
                             "source_acquired_utc": part["retrievalUtc"], "historical_publication_utc": None,
                             "timing_class": "RECONSTRUCTED_FINAL_RECORDS_UNCERTIFIED_VINTAGES"})
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("duplicate game")
    return sorted(rows, key=lambda r: (r["date"], r["id"])), exclusions, refs


def feature_matrix(history, targets):
    """Only completed dates strictly earlier than the preview calendar date.

No timestamp is imputed. Date bounds are reconstructed historical eligibility,
not observed source availability. Prospective input certification is separate.
"""
    if not history:
        raise ValueError("no earlier league history; no invented run prior")
    histories = {}
    league = []
    for r in history:
        for side, other in (("away", "home"), ("home", "away")):
            value = [r[side + "_score"], r[other + "_score"], float(r[side + "_score"] > r[other + "_score"])]
            item = (r["completion_date"], r["season"], value, r["id"])
            histories.setdefault(r[side], []).append(item)
            league.append(item)
    def arrays(items):
        items = sorted(items, key=lambda r: (r[0], r[3]))
        return (np.array([r[0] for r in items]), np.array([r[1] for r in items]),
                np.array([r[2] for r in items], dtype=float), np.array([r[3] for r in items]))
    pools = {k: arrays(v) for k, v in histories.items()}
    ld, ly, lv, _ = arrays(league)
    values, audits = [], []
    for target in targets:
        year = int(target["season"])
        boundary = (date.fromisoformat(target["date"]) - timedelta(days=1)).isoformat()
        # Prior league data can contain history seasons, but no current/future year.
        prior_league = lv[(ld < boundary) & (ly < year)]
        if len(prior_league) == 0:
            raise ValueError("no earlier league history; no invented run prior")
        league_prior = prior_league.mean(axis=0)
        vector, supports, donor_last = [], [], []
        for side in ("away", "home"):
            ds, ys, vs, ids = pools.get(target[side], (np.array([], dtype=str), np.array([]), np.empty((0, 3)), np.array([])))
            eligible = ds < boundary
            if np.any(ids[eligible] == target["id"]):
                raise ValueError("target leaks into its features")
            prior = vs[eligible & (ys == year - 1)]
            rate = (prior.sum(axis=0) + 40 * league_prior) / (len(prior) + 40)
            current = vs[eligible & (ys == year)]
            recent = current[-60:]
            recent_rate = (recent.sum(axis=0) + 20 * rate) / (len(recent) + 20)
            vector.extend([*recent_rate, *rate, len(recent)/60, len(current)/162])
            supports.append(len(current))
            donor_last.append(str(ds[eligible][-1]) if np.any(eligible) else None)
        values.append(vector)
        audits.append({"gameId": target["id"], "cutoffUtc": clocks(target["date"])["publish_by_utc"],
                       "excludedDatesOnOrAfter": boundary, "latestDonorCompletionDates": donor_last,
                       "currentSeasonSupport": supports, "historicalAvailabilityCertified": False})
    x = np.asarray(values)
    if x.shape != (len(targets), len(FEATURES)) or not np.isfinite(x).all():
        raise ValueError("invalid feature matrix")
    return x, audits


def fit(x, rows):
    y = np.array([r["home_score"] > r["away_score"] for r in rows], dtype=int)
    models = {"winner": make_pipeline(StandardScaler(), LogisticRegression(C=1, max_iter=1000, random_state=20260915))}
    models["winner"].fit(x, y)
    for side in ("away", "home"):
        models[side] = make_pipeline(StandardScaler(), PoissonRegressor(alpha=1, max_iter=1000, tol=1e-8))
        models[side].fit(x, [r[side+"_score"] for r in rows])
    return models


def predict(models, x):
    return np.column_stack((models["winner"].predict_proba(x)[:, 1],
                            models["away"].predict(x), models["home"].predict(x)))


def metrics(rows, predictions):
    p, away, home = predictions.T
    y = np.array([r["home_score"] > r["away_score"] for r in rows], dtype=float)
    a, h = np.array([[r["away_score"], r["home_score"]] for r in rows]).T
    ll = -(y*np.log(p)+(1-y)*np.log1p(-p))
    brier = (p-y)**2
    reliability = []
    for lo in np.arange(0, 1, .1):
        mask = (p >= lo) & (p < lo+.1+1e-14)
        if mask.any():
            reliability.append({"lower": float(lo), "n": int(mask.sum()), "predicted": float(p[mask].mean()), "observed": float(y[mask].mean())})
    result = {"n": len(rows), "logLoss": float(ll.mean()), "binaryBrier": float(brier.mean()),
              "auc": float(roc_auc_score(y, p)), "accuracy": float(((p >= .5) == y).mean()),
              "awayMAE": float(np.abs(away-a).mean()), "homeMAE": float(np.abs(home-h).mean()),
              "totalMAE": float(np.abs(away+home-a-h).mean()),
              "probabilityMean": float(p.mean()), "homeWinRate": float(y.mean()),
              "reliability": reliability,
              "ece10": sum(r["n"]*abs(r["predicted"]-r["observed"]) for r in reliability)/len(rows)}
    return result, np.column_stack((ll, brier, np.abs(away+home-a-h)))


def paired_week_uncertainty(rows, differences):
    weeks = [date.fromisoformat(r["date"]).isocalendar()[:2] for r in rows]
    unique = sorted(set(weeks))
    blocks = [differences[[i for i, w in enumerate(weeks) if w == week]] for week in unique]
    rng = np.random.default_rng(20260915)
    means = np.array([np.concatenate([blocks[i] for i in rng.integers(0, len(blocks), len(blocks))]).mean(axis=0) for _ in range(1000)])
    return {"unit": "ISO calendar-week blocks", "blocks": len(blocks), "replicates": 1000,
            "candidateMinusBenchmark": {name: {"mean": float(differences[:, i].mean()),
                "lower95": float(np.quantile(means[:, i], .025)), "upper95": float(np.quantile(means[:, i], .975))}
                for i, name in enumerate(("logLoss", "binaryBrier", "totalMAE"))}}


def require_current_inputs(evidence, now):
    """Fail closed: an old fitted artifact never invents current team evidence."""
    if evidence.get("schema") != "MLB_TEAM_PREVIEW_CURRENT_INPUTS_V1":
        raise ValueError("CURRENT_TEAM_HISTORY_AND_SCHEDULE_REQUIRED")
    cutoff = utc(clocks(evidence["game"]["slate_date"])["publish_by_utc"])
    if utc(now) > cutoff:
        raise ValueError("PREVIEW_DEADLINE_MISSED")
    if evidence.get("inputAvailabilityCertified") is not True:
        raise ValueError("CURRENT_HISTORY_VINTAGE_UNCERTIFIED")
    if evidence.get("lineupStatus") != "UNKNOWN" or evidence.get("starterStatus") != "UNKNOWN":
        raise ValueError("team-only model must disclose unsupported personnel")
    if not evidence.get("missingEvidence"):
        raise ValueError("personnel missingness must be disclosed")
    for ref in evidence.get("sourceFiles", []):
        from .show_preview import checked_file
        checked_file(ref)
    if not evidence.get("sourceFiles"):
        raise ValueError("CURRENT_SOURCE_BINDINGS_REQUIRED")
    for row in evidence.get("history", []):
        # A captured FINAL observation proves completion by that instant without
        # pretending it is the actual last-out timestamp.
        completion = row.get("completedAtUtc")
        if completion is None:
            if row.get("status") != "FINAL" or not row.get("completionConfirmedAtUtc"):
                raise ValueError("FINAL_COMPLETION_EVIDENCE_REQUIRED")
            completion = row["completionConfirmedAtUtc"]
        if not utc(completion) <= utc(row["capturedAtUtc"]) <= utc(evidence["sourceCutoffUtc"]) <= utc(now):
            raise ValueError("history source chronology differs")
    if not evidence.get("history"):
        raise ValueError("CURRENT_TEAM_HISTORY_REQUIRED")
    rows = evidence["history"]
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("DUPLICATE_HISTORY_GAME")
    if evidence["awayRetrosheetCode"] == evidence["homeRetrosheetCode"]:
        raise ValueError("TEAM_IDENTITY_COLLISION")
    for row in rows:
        if row["away"] == row["home"] or int(row["date"][:4]) != int(row["season"]):
            raise ValueError("history identity or season mismatch")
        if not all(np.isfinite(row[s+"_score"]) and row[s+"_score"] >= 0 for s in ("away", "home")):
            raise ValueError("invalid historical score")
    # Full coverage is required. A few recent daily receipts are not a season.
    if evidence.get("historyComplete") is not True or evidence.get("priorSeasonComplete") is not True:
        raise ValueError("SEASON_HISTORY_COMPLETENESS_REQUIRED")
    if evidence.get("protectedPayloadsUsed") is not False:
        raise ValueError("PROTECTED_PAYLOADS_PROHIBITED")
    # Bind each normalized historical fact to an immutable admitted owner export.
    # This seam accepts no unsigned caller-only vector or certification boolean.
    from .show_preview import checked_file
    owner = json.loads(checked_file(evidence["ownerExport"]))
    if owner.get("schema") != "MLB_TEAM_PREVIEW_ADMITTED_HISTORY_V1":
        raise ValueError("ADMITTED_OWNER_EXPORT_REQUIRED")
    for field in ("history", "historyComplete", "priorSeasonComplete", "sourceCutoffUtc", "game", "sourceFiles",
                  "awayRetrosheetCode", "homeRetrosheetCode"):
        if owner.get(field) != evidence.get(field):
            raise ValueError("owner export differs: " + field)
    if not owner.get("admissionReceipt") or owner.get("use") != "CURRENT_PREVIEW_FEATURE_CONSTRUCTION_ONLY":
        raise ValueError("OWNER_ADMISSION_REQUIRED")
    admission = json.loads(checked_file(owner["admissionReceipt"]))
    if admission.get("protectedPayloadsUsed") is not False or admission.get("eligibleForPreviewFeatures") is not True:
        raise ValueError("OWNER_ADMISSION_NOT_ELIGIBLE")
    return evidence


def point_source(input_path, model_path, assessment_path, output, now):
    """Generate once, then let the existing preview publisher reuse this source.

This does not acquire the missing owner export or grant it source permission.
"""
    import joblib
    from .show_preview import checked_file, iso
    input_path, model_path, assessment_path = map(Path, (input_path, model_path, assessment_path))
    inputs = require_current_inputs(json.loads(input_path.read_bytes()), now)
    assessment = json.loads(assessment_path.read_bytes())
    if assessment["configuration"] != CONFIG or assessment["selection"]["numericalGatePassed"] is not True:
        raise ValueError("FROZEN_ASSESSMENT_GATE_NOT_PASSED")
    ref = next((r for r in assessment["artifacts"] if r["path"] == str(model_path.resolve())), None)
    if ref is None:
        raise ValueError("MODEL_NOT_BOUND_TO_ASSESSMENT")
    checked_file(ref)
    bindings = {"inputFile": physical(input_path), "modelFile": physical(model_path),
                "assessmentFile": physical(assessment_path), "configuration": CONFIG}
    path = Path(output) / "point-sources" / (digest(canonical(bindings)) + ".json")
    if path.exists():
        retained = json.loads(path.read_bytes())
        if any(retained[k] != value for k, value in bindings.items()):
            raise ValueError("source identity collision")
        verify_point_source(retained)
        retain_source_availability(path, now)
        return path
    fitted = joblib.load(model_path)
    if fitted["configuration"] != CONFIG or fitted["features"] != FEATURES:
        raise ValueError("model/feature contract differs")
    game = inputs["game"]
    target = {"id": game["source_game_ref"], "date": game["slate_date"], "season": int(game["slate_date"][:4]),
              "away": inputs["awayRetrosheetCode"], "home": inputs["homeRetrosheetCode"]}
    matrix, audit = feature_matrix(inputs["history"], [target])
    probability, away, home = predict(fitted["models"], matrix)[0].tolist()
    body = {"schemaVersion": "MLB_TEAM_PREVIEW_POINT_SOURCE_V1", "configuration": CONFIG,
            "purpose": "PREVIEW_MODEL_SOURCE", "modelFile": physical(model_path),
            "assessmentFile": physical(assessment_path), "inputFile": physical(input_path),
            "sourceCutoffUtc": inputs["sourceCutoffUtc"], "game": game,
            "featureValues": matrix[0].tolist(), "featureNames": FEATURES, "featureAudit": audit,
            "expectedScore": {"away": away, "home": home},
            "probabilities": {"away_win": 1-probability, "home_win": probability, "tie": 0.},
            "drawCount": 0, "distribution": None, "researchOnly": True}
    body["createdAtUtc"] = iso(now)
    body["forecastId"] = "mlb-team-preview-point:" + digest(canonical(body))
    immutable(path, canonical(body))
    verify_point_source(json.loads(path.read_bytes()))
    retain_source_availability(path, now)
    return path


def retain_source_availability(path, now):
    """Observe source bytes after write/verification, separately from creation."""
    from .show_preview import iso, checked_file
    receipt = Path(path).with_suffix(".availability.json")
    if receipt.exists():
        retained = json.loads(receipt.read_bytes())
        if retained["sourceFile"] != physical(path):
            raise ValueError("source availability binding differs")
        checked_file(retained["sourceFile"])
    else:
        # Future logical clocks occur only in explicitly isolated test fixtures.
        observed = max(utc(now), datetime.now(timezone.utc))
        immutable(receipt, canonical({"schema": "MLB_TEAM_PREVIEW_SOURCE_AVAILABILITY_V1",
            "sourceFile": physical(path), "availableAtUtc": iso(observed),
            "basis": "PHYSICAL_SOURCE_READ_VERIFIED_AFTER_WRITE"}))
    return receipt


def verify_point_source(f):
    from .show_preview import checked_file
    if f.get("schemaVersion") != "MLB_TEAM_PREVIEW_POINT_SOURCE_V1" or f.get("configuration") != CONFIG:
        raise ValueError("unadmitted MLB source schema/configuration")
    if f["forecastId"] != "mlb-team-preview-point:" + digest(canonical({k:v for k,v in f.items() if k != "forecastId"})):
        raise ValueError("MLB source identity mismatch")
    for name in ("modelFile", "assessmentFile", "inputFile"):
        checked_file(f[name])
    a = json.loads(checked_file(f["assessmentFile"]))
    if not a["selection"]["numericalGatePassed"] or f["modelFile"] not in a["artifacts"]:
        raise ValueError("model does not bind passed assessment")
    require_current_inputs(json.loads(checked_file(f["inputFile"])), f["createdAtUtc"])
    if f["drawCount"] != 0 or f["distribution"] is not None or f["researchOnly"] is not True:
        raise ValueError("point model cannot supply a joint population")
    if f["featureNames"] != FEATURES:
        raise ValueError("feature order differs")
    import joblib
    inputs = json.loads(checked_file(f["inputFile"]))
    g = f["game"]
    if g != inputs["game"] or f["sourceCutoffUtc"] != inputs["sourceCutoffUtc"]:
        raise ValueError("input game or cutoff differs")
    x, audit = feature_matrix(inputs["history"], [{"id": g["source_game_ref"], "date": g["slate_date"],
        "season": int(g["slate_date"][:4]), "away": inputs["awayRetrosheetCode"], "home": inputs["homeRetrosheetCode"]}])
    if x[0].tolist() != f["featureValues"] or audit != f["featureAudit"]:
        raise ValueError("feature reconstruction differs")
    model = joblib.load(f["modelFile"]["path"])
    p, away, home = predict(model["models"], x)[0].tolist()
    if f["expectedScore"] != {"away": away, "home": home} or f["probabilities"] != {"away_win": 1-p, "home_win": p, "tie": 0.}:
        raise ValueError("model numerical replay differs")


def preview_source(path):
    """Adapt the admitted immutable point source to the existing exchange."""
    from .show_preview_sources import base
    path = Path(path)
    f = json.loads(path.read_bytes())
    verify_point_source(f)
    cut, created = f["sourceCutoffUtc"], f["createdAtUtc"]
    availability_path = path.with_suffix(".availability.json")
    availability = json.loads(availability_path.read_bytes())
    if availability["sourceFile"] != physical(path):
        raise ValueError("source availability binding differs")
    result = base("MLB", f["forecastId"], f["schemaVersion"], "PREVIEW_MODEL_SOURCE", digest(path.read_bytes()),
        cut, created, availability["availableAtUtc"], None,
        [physical(path), f["modelFile"], f["assessmentFile"], f["inputFile"], physical(availability_path)],
        {"captured_utc": cut}, f["game"],
        {"model_id": "MLB_TEAM_PREVIEW", "model_version": CONFIG, "artifact_sha256": f["modelFile"]["sha256"]},
        {"sha256": digest(canonical(FEATURE_CONTRACT)), "definition": FEATURE_CONTRACT,
         "feature_vector_sha256": digest(canonical(f["featureValues"])), "input_count": len(FEATURES)},
        {"identity": None, "seed": None, "draw_count": 0, "reused": False},
        f["expectedScore"], f["probabilities"], None,
        "Logistic winner probabilities and separate Poisson expected runs; no joint simulation or total-line probabilities.",
        ["Team-only reconstructed-history research model, distinct from final V18.",
         "No starter, lineup, injury, park or weather adjustment. Player information is unknown.",
         "Historical revision vintages and historical preview availability were not certified; 2024 assessment is reused Validation."])
    result["season"] = int(f["game"]["slate_date"][:4])
    result["preview_evidence_certified"] = True
    result["availability_proof"] = {"method": "ADMITTED_CURRENT_OWNER_EXPORT_AND_NEW_POINT_MODEL_SOURCE",
        "source_input_file": f["inputFile"], "source_created_utc": created,
        "source_availability_receipt": physical(availability_path),
        "wrapper_reuses_new_point_prediction": True, "simulation_generated": False}
    for evidence in result["team_evidence"].values():
        evidence["fallback_rule"] = "FROZEN_TEAM_HISTORY_SHRINKAGE_NO_PLAYER_SUBSTITUTION"
    return result
