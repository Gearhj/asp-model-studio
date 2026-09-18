"""Private, network-free paired CFB research collection; never a publisher."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import pipeline
from .lifecycle import atomic_json, immutable, owner_lock
from .opponent_strength import fit_strength, predict_strength
from .strength_study import clean


def now():
    return datetime.now(timezone.utc).isoformat()


def utc(value):
    value = pd.Timestamp(value)
    if value.tzinfo is None:
        raise ValueError("UTC-aware timestamp required")
    return value.tz_convert("UTC")


def canonical(value):
    return json.dumps(clean(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def reference(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def verified(bound):
    data = Path(bound["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != bound["sha256"] or len(data) != bound["bytes"]:
        raise ValueError("Physical binding mismatch: " + bound["path"])
    return data


def read(bound):
    return json.loads(verified(bound))


def save_bytes(out, data, name):
    digest = hashlib.sha256(data).hexdigest()
    path = Path(out) / "objects" / "sha256" / digest / name
    return immutable(path, data)


def save_json(out, value, name):
    return save_bytes(out, canonical(value), name)


def save_frame(out, frame, name):
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    return save_bytes(out, buffer.getvalue(), name)


def load_protocol(out):
    pointer = json.loads((Path(out) / "FROZEN_PROTOCOL.json").read_text())
    protocol = read(pointer["protocol"])
    for binding in protocol["codeBindings"]:
        verified(binding)
    for name in ("historicalDecision", "historicalSelection", "candidateManifest", "coveragePreflight", "candidateHistoryCompatibility", "protocolText"):
        verified(protocol[name])
    return pointer["protocol"], protocol


def eligible_strength_history(candidate, source, target):
    """Keep the frozen 48h law and require genuinely observed current finals."""
    origin = utc(target["scheduled_at"]).floor("D")
    history = candidate["historicalPrimary"].copy()
    if not history.season.le(2025).all():
        raise ValueError("Historical fit includes a later season")
    current = source["currentHistory"].copy()
    if len(current):
        if not current.season.eq(2026).all() or not current.is_final.all():
            raise ValueError("Current state requires source-declared 2026 finals")
        captured = pd.to_datetime(current.source_captured_at, utc=True)
        if captured.isna().any() or (captured > utc(source["inputCutoffUtc"])).any():
            raise ValueError("Current final was not observed by original input cutoff")
        if (captured > utc(source["observedAtUtc"])).any():
            raise ValueError("Future evidence capture")
        history = pd.concat([history, current], ignore_index=True)
    if history.game_id.duplicated().any():
        raise ValueError("Duplicate historical/current game identity")
    history["scheduled_at"] = pd.to_datetime(history.scheduled_at, utc=True)
    eligible = history.is_final & history.primary & history.scheduled_at.le(origin-pd.Timedelta(hours=48))
    eligible &= np.isfinite(history[["home_score", "away_score"]].to_numpy(float)).all(axis=1)
    return history.loc[eligible].sort_values(["scheduled_at", "game_id"]).copy()


def predict_candidate(candidate, source):
    target = pd.Series(source["target"])
    history = eligible_strength_history(candidate, source, target)
    strength = fit_strength(history, 2026, 4.0, dynamic=True, opponent_adjusted=True)
    extra = predict_strength(strength, pd.DataFrame([source["target"]])).iloc[0]
    features = source["featureRow"].copy()
    if len(features) != 1:
        raise ValueError("One compatible baseline feature row required")
    if "feature_max_source_game_date" in features and pd.notna(features.iloc[0].feature_max_source_game_date):
        if utc(features.iloc[0].feature_max_source_game_date) > utc(target.scheduled_at).floor("D")-pd.Timedelta(hours=48):
            raise ValueError("Gen1 feature history differs from frozen embargo")
    for key in ("strength_pred_margin", "strength_pred_total"):
        features[key] = extra[key]
    points = {"pred_"+key: float(model.predict(features[candidate["columns"]])[0])
              for key, model in candidate["models"].items()}
    points["pred_home"] = (points["pred_total"]+points["pred_margin"])/2
    points["pred_away"] = (points["pred_total"]-points["pred_margin"])/2
    points["calibratedHomeWinProbability"] = float(candidate["calibrator"].predict_proba(
        np.array([[points["pred_margin"]]]))[0, 1])
    label = "ridge_alpha100"
    donors = candidate["residualDonors"].copy()
    if not donors.season.le(2025).all() or not (pd.to_datetime(donors.scheduled_at, utc=True) < utc(target.scheduled_at)).all():
        raise ValueError("Residual donor chronology violation")
    for side in ("home", "away"):
        donors[f"{label}_pred_{side}"] = donors["pred_"+side]
        target[f"{label}_pred_{side}"] = points["pred_"+side]
    draws, accounting = pipeline.simulate_paired_residuals(target, donors, label, draw_count=10000)
    support = {key: int(extra[key]) for key in ("home_current_support", "away_current_support", "home_prior_support", "away_prior_support")}
    support["low_support"] = int(target.week) <= 3 or min(support["home_current_support"], support["away_current_support"]) < 2
    support["zero_prior_support"] = min(support["home_prior_support"], support["away_prior_support"]) == 0
    return {"points": points, "draws": draws, "features": features, "strength": strength,
            "history": history, "support": support, "accounting": accounting}


def validate_enrollment(protocol, target, produced_at):
    t = utc(produced_at)
    if not utc(protocol["frozenAtUtc"]) <= t < utc(protocol["enrollmentEndsAtUtc"]):
        raise ValueError("Outside frozen enrollment window")
    kickoff = utc(target["scheduled_at"])
    if kickoff >= utc(protocol["kickoffBeforeUtc"]) or t >= kickoff-pd.Timedelta(minutes=30):
        raise ValueError("Forecast cutoff has passed or game outside window")
    if int(target["season"]) != 2026 or not 1 <= int(target["week"]) <= 14:
        raise ValueError("Game outside prospective primary scope")


def pair_index(out):
    path = Path(out) / "PAIRS.json"
    indexed = read(json.loads(path.read_text())["index"])["pairs"] if path.exists() else {}
    pairs = {}
    for accepted in sorted((Path(out) / "enrollments").glob("*/accepted.json")):
        journal = json.loads(accepted.read_text())
        commit = read(journal["commit"])
        pair = read(commit["pair"])
        confirmed = utc(journal["durablePairConfirmedAtUtc"])
        if not utc(commit["committedAtUtc"]) <= confirmed < utc(commit["cutoffUtc"]):
            raise ValueError("Journal does not confirm pre-cutoff durable pair")
        if confirmed >= utc(pair["sources"]["currentEligibilityValidUntilUtc"]):
            raise ValueError("Journal confirmation followed canonical lease expiry")
        if journal["protocol"] != pair["protocol"] or commit["protocol"] != pair["protocol"]:
            raise ValueError("Enrollment journal protocol mismatch")
        pairs[str(commit["gameId"])] = journal["commit"]
    if any(pairs.get(gid) != bound for gid, bound in indexed.items()):
        raise ValueError("Pair index differs from immutable enrollment journal")
    return pairs


def collect(out, clock=now):
    from .prospective_sources import load_discovery, load_pair_source
    out = Path(out)
    protocol_ref, protocol = load_protocol(out)
    started = clock()
    if utc(started) >= utc(protocol["enrollmentEndsAtUtc"]):
        return {"disposition": "ENROLLMENT_CLOSED", "captured": 0, "providerCalls": 0}
    if (out / "STOP_ENROLLMENT.json").exists():
        return {"disposition": "STOPPED_BY_FROZEN_RULE", "captured": 0, "providerCalls": 0}
    manifest = read(protocol["candidateManifest"])
    candidate_ref = manifest["candidate"]
    candidate = joblib.load(io.BytesIO(verified(candidate_ref)))
    snapshot = load_discovery(protocol["discoveryPointer"], as_of_utc=started)
    admitted = read(snapshot["document"]["inputVersion"])
    starts = {str(row["gameId"]): utc(row["target"]["scheduled_at"]) for row in admitted["games"]}
    packages = sorted(snapshot["packages"], key=lambda row: (starts[str(row["gameId"])], int(row["gameId"])))
    pairs, attempts, new = pair_index(out), [], []
    for package in packages:
        if str(package["gameId"]) in pairs:
            continue
        try:
            journal_root = out / "enrollments" / str(int(package["gameId"]))
            if (journal_root / "reservation.json").exists():
                raise ValueError("INTERRUPTED_COMMIT_RESERVED_NO_REENROLLMENT")
            source = load_pair_source(snapshot, package, as_of_utc=clock(), minimum_lead_minutes=30)
            target = source["target"]
            gid = str(target["game_id"])
            if gid in pairs:
                continue
            validate_enrollment(protocol, target, clock())
            if source["forecast"]["modelBindings"] != protocol["canonicalModelBindings"]:
                raise ValueError("Canonical Gen1 model identity changed during the frozen pilot")
            if source["bindings"]["historicalGames"] != protocol["canonicalHistoricalGames"]:
                raise ValueError("Canonical historical input identity changed during the frozen pilot")
            if utc(source["inputCutoffUtc"]) > utc(source["observedAtUtc"]):
                raise ValueError("Input snapshot acquired after research observation")
            predicted = predict_candidate(candidate, source)
            baseline_draws = source["baselineDraws"]
            if len(baseline_draws) != 10000:
                raise ValueError("Canonical Gen1 distribution must contain 10000 draws")
            artifacts = {
                "gen1Draws": save_frame(out, baseline_draws, "gen1-draws.parquet"),
                "bDraws": save_frame(out, predicted["draws"], "b-draws.parquet"),
                "features": save_frame(out, predicted["features"], "features.parquet"),
                "strengthHistory": save_frame(out, predicted["history"], "strength-history.parquet"),
                "strengthState": save_json(out, predicted["strength"], "strength-state.json")}
            produced = clock()
            validate_enrollment(protocol, target, produced)
            if utc(produced) >= utc(source["bindings"]["currentEligibilityValidUntilUtc"]):
                raise ValueError("Canonical eligibility lease expired during private fitting")
            pair = {"schema": "CFB_PRIVATE_PROSPECTIVE_PAIR_V1", "protocol": protocol_ref,
                    "candidateManifest": protocol["candidateManifest"], "candidateArtifact": candidate_ref,
                    "createdAtUtc": produced, "observedAtUtc": source["observedAtUtc"],
                    "canonicalEligibilityEvaluatedAtUtc": source["currentEligibilityEvaluatedAtUtc"],
                    "originalInputCutoffUtc": source["inputCutoffUtc"], "target": target,
                    "support": predicted["support"], "gen1Points": source["baselinePoints"],
                    "bPoints": predicted["points"], "sources": source["bindings"],
                    "originalForecast": source["forecast"], "originalPublicationReceipt": source["packageReceipt"],
                    "discovery": snapshot["manifest"], "artifacts": artifacts,
                    "candidateSimulationAccounting": predicted["accounting"],
                    "productionAuthority": False, "privateResearchOnly": True, "providerCalls": 0}
            pair_ref = save_json(out, pair, "pair.json")
            immutable(journal_root / "reservation.json", canonical({"protocol": protocol_ref, "pair": pair_ref}))
            committed = clock()
            validate_enrollment(protocol, target, committed)
            if utc(committed) >= utc(source["bindings"]["currentEligibilityValidUntilUtc"]):
                raise ValueError("Canonical eligibility lease expired before private commit")
            receipt = {"schema": "CFB_PRIVATE_PAIR_COMMIT_V1", "pair": pair_ref, "committedAtUtc": committed,
                       "cutoffUtc": (utc(target["scheduled_at"])-pd.Timedelta(minutes=30)).isoformat(),
                       "protocol": protocol_ref, "gameId": int(gid)}
            receipt_ref = save_json(out, receipt, "pair-commit.json")
            # Recheck after both immutable pair and commit receipt are durable.
            confirmed = clock()
            validate_enrollment(protocol, target, confirmed)
            if utc(confirmed) >= utc(source["bindings"]["currentEligibilityValidUntilUtc"]):
                raise ValueError("Canonical eligibility lease expired after durable write")
            # This journal records an already durable pre-cutoff pair. A crash
            # before this marker leaves a reservation and never substitutes a
            # later source revision; a crash after it is recoverable into index.
            immutable(journal_root / "accepted.json", canonical({"protocol": protocol_ref,
                "commit": receipt_ref, "durablePairConfirmedAtUtc": confirmed}))
            pairs[gid] = receipt_ref
            index_ref = save_json(out, {"protocol": protocol_ref, "pairs": pairs, "updatedAtUtc": clock()}, "pair-index.json")
            atomic_json(out / "PAIRS.json", {"index": index_ref})
            new.append({"gameId": int(gid), "pair": pair_ref, "commit": receipt_ref})
        except (ValueError, KeyError, FileNotFoundError) as exc:
            attempts.append({"package": clean(package), "reason": str(exc)})
    if pairs:
        index_ref = save_json(out, {"protocol": protocol_ref, "pairs": pairs, "updatedAtUtc": clock()}, "pair-index.json")
        atomic_json(out / "PAIRS.json", {"index": index_ref})
    result = {"schema": "CFB_PRIVATE_COLLECTION_TICK_V1", "startedAtUtc": started,
              "completedAtUtc": clock(), "protocol": protocol_ref, "discovery": snapshot["manifest"],
              "captured": len(new), "totalEnrolled": len(pairs), "newPairs": new, "excludedAttempts": attempts,
              "disposition": "CAPTURED" if new else "NO_NEW_ELIGIBLE_PAIR", "providerCalls": 0,
              "providerBytes": 0, "productionWrites": 0}
    tick_ref = save_json(out, result, "collection-tick.json")
    atomic_json(out / "COLLECTION_CURRENT.json", {"receipt": tick_ref})
    return result


def run_tick(out):
    from .prospective_assessment import monitor_and_assess
    out = Path(out)
    with owner_lock(out / "private-research.lock"):
        # Apply any due harm-stop assessment before enrolling more games.
        assessment = monitor_and_assess(out)
        result = collect(out)
        result["assessment"] = assessment
        return result
