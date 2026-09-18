"""Private prospective outcome monitoring and scheduled paired assessment.

Monitoring admits immutable source-result revisions without opening draw files or
computing performance. Only a due, one-time assessment opens paired populations.
Nothing here fits a model, acquires data, publishes forecasts or settles AISP.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd

from . import pipeline
from . import prospective_collection as collection
from .prospective_sources import load_final_evidence


METRICS = ("jointEnergyScore", "jointWinnerLogLoss", "jointBinaryBrier", "marginCrps", "totalCrps",
           "scoreAbsoluteError", "marginAbsoluteError", "totalAbsoluteError")
GUARDRAILS = {"jointWinnerLogLoss": 0.005, "jointBinaryBrier": 0.002,
              "marginCrps": 0.05, "totalCrps": 0.05}
now = collection.now


def require(value, message):
    if not bool(value):
        raise ValueError(message)


def _index(out, filename, key, protocol_ref):
    path = Path(out) / filename
    if not path.exists():
        return {}
    document = collection.read(collection.read(collection.reference(path))["index"])
    require(document["protocol"] == protocol_ref, "Research index protocol binding differs")
    return document[key]


def _put_index(out, filename, key, value, protocol_ref, clock):
    bound = collection.save_json(out, {"protocol": protocol_ref, key: value, "updatedAtUtc": clock},
                                 filename.lower().replace(".json", "-index.json"))
    collection.atomic_json(Path(out) / filename, {"index": bound})
    return bound


def _validate_protocol(protocol):
    expected = {"overall": {"minimumGames": 80, "minimumUtcDates": 6, "minimumIsoWeeks": 2},
                "low_support": {"minimumGames": 40, "minimumUtcDates": 3, "minimumIsoWeeks": 2}}
    require(collection.utc(protocol["acquisitionExpiresAtUtc"]) == collection.utc("2026-10-01T00:00:00Z"),
            "Acquisition expiry must remain frozen")
    for group, values in expected.items():
        require(all(protocol["adequacy"][group][key] == value for key, value in values.items()),
                "Unexpected adequacy configuration")
    require(protocol["adequacy"]["zero_prior_support"].get("descriptiveOnly") is True,
            "Zero-prior support remains descriptive only")
    uncertainty = protocol.get("uncertainty", {})
    require(uncertainty.get("bootstrapReplicates", 2000) == 2000 and uncertainty.get("seed", 20260918) == 20260918,
            "Unexpected bootstrap configuration")
    require(protocol.get("guardrails", GUARDRAILS) == GUARDRAILS, "Unexpected metric guardrails")
    signal = protocol.get("pilotSignal", {})
    for key, value in (("minimumEnergyImprovement", .10), ("lowSupportMaximumMeanDegradation", .05),
                       ("lowSupportMaximumUpper95", .15)):
        require(signal.get(key, value) == value, "Unexpected pilot signal threshold")
    harm = protocol.get("interimHarmStop", {})
    for key, value in (("minimumGames", 30), ("energyDegradation", .5), ("marginCrpsDegradation", .5)):
        require(harm.get(key, value) == value, "Unexpected interim harm-stop threshold")
    schedule = protocol["assessmentSchedule"]
    require(len({row["id"] for row in schedule}) == len(schedule), "Duplicate assessment id")
    expected_dates = {"interim": "2026-09-22T16:00:00Z", "final": "2026-10-01T12:00:00Z",
                      "closure": "2026-10-02T12:00:00Z"}
    require({item["kind"] for item in schedule} == set(expected_dates) and len(schedule) == 3,
            "Exactly the frozen interim/final/closure schedule is required")
    for item in schedule:
        require(collection.utc(item["atUtc"]) == collection.utc(expected_dates[item["kind"]]),
                "Unexpected assessment schedule")


def _pair(protocol_ref, protocol, game_id, commit_ref):
    commit = collection.read(commit_ref)
    pair = collection.read(commit["pair"])
    target = pair["target"]
    require(commit["protocol"] == pair["protocol"] == protocol_ref, "Pair protocol binding differs")
    require(int(commit["gameId"]) == int(target["game_id"]) == int(game_id), "Pair game identity differs")
    collection.validate_enrollment(protocol, target, pair["createdAtUtc"])
    collection.validate_enrollment(protocol, target, commit["committedAtUtc"])
    require(collection.utc(pair["createdAtUtc"]) <= collection.utc(commit["committedAtUtc"]),
            "Pair creation follows durable commit")
    if "originalInputCutoffUtc" in pair:
        require(collection.utc(pair["originalInputCutoffUtc"]) <= collection.utc(pair["createdAtUtc"]),
                "Pair input was not available before prediction")
    require(collection.utc(commit["cutoffUtc"]) == collection.utc(target["scheduled_at"]) - pd.Timedelta(minutes=30),
            "Pair cutoff differs from target")
    support = pair["support"]
    counts = [support[key] for key in ("home_current_support", "away_current_support", "home_prior_support", "away_prior_support")]
    require(all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in counts),
            "Invalid frozen pair support count")
    require(support["low_support"] is (int(target["week"]) <= 3 or min(counts[:2]) < 2),
            "Frozen low-support classification differs")
    require(support["zero_prior_support"] is (min(counts[2:]) == 0),
            "Frozen zero-prior classification differs")
    return commit, pair


def _outcome(row, target, commit, expiry, observed_at):
    require(row.get("completed") is True and row.get("sourceCompleted") is True, "Final status must be literal true")
    for result_key, target_key in (("sourceGameId", "game_id"), ("homeTeamId", "home_id"), ("awayTeamId", "away_id")):
        require(int(row[result_key]) == int(target[target_key]), "Final identity/orientation differs from pair")
    kickoff = collection.utc(target["scheduled_at"])
    require(collection.utc(row["scheduledKickoffUtc"]) == kickoff, "Final kickoff revision differs from pair")
    require(int(row.get("season", target["season"])) == int(target["season"]) == 2026, "Final season differs")
    captured = collection.utc(row["capturedAtUtc"])
    require(captured < expiry, "Final capture is outside acquisition authorization")
    require(captured <= observed_at, "Final capture is in the future")
    require(captured > kickoff and captured > collection.utc(commit["committedAtUtc"]),
            "Final capture must follow prediction and kickoff")
    points = []
    for key in ("homeFinalPoints", "awayFinalPoints"):
        value = row[key]
        require(not isinstance(value, (bool, np.bool_)) and isinstance(value, (int, float, np.integer, np.floating))
                and np.isfinite(value) and value >= 0 and value == np.floor(value), "Invalid final points")
        points.append(int(value))
    require(points[0] != points[1], "Tied CFB final is unsupported")
    return {"status": "SOURCE_FINAL", "gameId": int(target["game_id"]), "season": 2026,
            "homeTeamId": int(target["home_id"]), "awayTeamId": int(target["away_id"]),
            "scheduledKickoffUtc": kickoff.isoformat(), "homeFinalPoints": points[0], "awayFinalPoints": points[1]}


def _append_revision(out, protocol_ref, revisions, game_id, semantic, captured_at, observed_at, bindings, pair_commit):
    existing = revisions.get(game_id, [])
    previous = collection.read(existing[-1]) if existing else None
    if previous:
        require(previous["protocol"] == protocol_ref and previous["pairCommit"] == pair_commit,
                "Previous outcome protocol or pair binding differs")
    if previous and previous["result"] == semantic:
        return False
    if previous:
        require(collection.utc(captured_at) > collection.utc(previous["sourceCapturedAtUtc"]),
                "Conflicting or regressing outcome revision clock")
    revision = {"schema": "CFB_PRIVATE_RESEARCH_OUTCOME_REVISION_V1", "protocol": protocol_ref,
                "pairCommit": pair_commit, "result": semantic, "sourceCapturedAtUtc": captured_at,
                "admittedAtUtc": observed_at, "sourceBindings": bindings,
                "predecessor": existing[-1] if existing else None,
                "revisionNumber": len(existing) + 1,
                "admissionMeaning": "Private research admission of verified source final; not AISP canonical admission or settlement",
                "bothModelsUseIdenticalOutcomeRevision": True, "productionAuthority": False}
    bound = collection.save_json(out, revision, "outcome-revision.json")
    revisions[game_id] = [*existing, bound]
    return True


def monitor_outcomes(out, protocol_ref, protocol, pairs, clock):
    revisions = _index(out, "OUTCOMES.json", "revisions", protocol_ref)
    expiry, observed = collection.utc(protocol["acquisitionExpiresAtUtc"]), collection.utc(clock)
    admitted, rejected = [], []
    source = None
    try:
        source = load_final_evidence(protocol["finalEvidencePointer"], as_of_utc=clock)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        rejected.append({"stage": "source", "reason": str(exc)})
    if source is not None:
        rows = {str(row["sourceGameId"]): row for row in source["rows"]}
        require(len(rows) == len(source["rows"]), "Duplicate source final identity")
        document_clocks = {row["capturedAtUtc"] for row in source["rows"]}
        document_clock = next(iter(document_clocks)) if len(document_clocks) == 1 else None
        for game_id, commit_ref in pairs.items():
            try:
                commit, pair = _pair(protocol_ref, protocol, game_id, commit_ref)
                if game_id in rows:
                    row = rows[game_id]
                    try:
                        semantic = _outcome(row, pair["target"], commit, expiry, observed)
                    except ValueError as exc:
                        # A verified source can subsequently revise identity or
                        # schedule. Never silently fall back to its old final.
                        capture = collection.utc(row["capturedAtUtc"])
                        if (capture < expiry and capture <= observed
                                and capture > collection.utc(pair["target"]["scheduled_at"])
                                and capture > collection.utc(commit["committedAtUtc"])):
                            semantic = {"status": "WITHHELD_SOURCE_FINAL_INCOMPATIBLE", "gameId": int(game_id),
                                        "reason": str(exc)}
                            if _append_revision(out, protocol_ref, revisions, game_id, semantic,
                                                row["capturedAtUtc"], clock, source["bindings"], commit_ref):
                                admitted.append({"gameId": int(game_id), "revision": revisions[game_id][-1]})
                        raise
                    changed = _append_revision(out, protocol_ref, revisions, game_id, semantic,
                                               row["capturedAtUtc"], clock, source["bindings"], commit_ref)
                    if changed:
                        admitted.append({"gameId": int(game_id), "revision": revisions[game_id][-1]})
                elif game_id in revisions and document_clock is not None:
                    # A complete admitted final population can retract a former
                    # final. Preserve that event rather than silently scoring it.
                    previous = collection.read(revisions[game_id][-1])
                    capture = collection.utc(document_clock)
                    if capture > collection.utc(previous["sourceCapturedAtUtc"]) and capture < expiry and capture <= observed:
                        semantic = {"status": "WITHHELD_SOURCE_FINAL_ABSENT", "gameId": int(game_id)}
                        if _append_revision(out, protocol_ref, revisions, game_id, semantic, document_clock,
                                            clock, source["bindings"], commit_ref):
                            admitted.append({"gameId": int(game_id), "revision": revisions[game_id][-1]})
            except (ValueError, KeyError, FileNotFoundError) as exc:
                rejected.append({"gameId": int(game_id), "reason": str(exc)})
        if admitted:
            _put_index(out, "OUTCOMES.json", "revisions", revisions, protocol_ref, clock)
    active = {game_id: collection.read(values[-1])["result"]["status"] for game_id, values in revisions.items() if values}
    result = {"schema": "CFB_PRIVATE_OUTCOME_MONITOR_V1", "observedAtUtc": clock, "protocol": protocol_ref,
              "enrolledPairs": len(pairs), "activeSourceFinals": sum(value == "SOURCE_FINAL" for value in active.values()),
              "newRevisions": admitted, "rejectedEvidence": rejected,
              "sourceBindings": source["bindings"] if source else None,
              "metricsComputed": False, "drawPopulationsRead": False, "modelFits": 0, "providerCalls": 0}
    bound = collection.save_json(out, result, "outcome-monitor.json")
    collection.atomic_json(Path(out) / "OUTCOME_MONITOR_CURRENT.json", {"receipt": bound})
    return revisions, result, bound


def select_revision(revisions, logical_cutoff):
    eligible = []
    for bound in revisions:
        revision = collection.read(bound)
        if collection.utc(revision["sourceCapturedAtUtc"]) <= logical_cutoff:
            eligible.append((collection.utc(revision["sourceCapturedAtUtc"]), int(revision["revisionNumber"]), bound, revision))
    if not eligible:
        return None
    _, _, bound, revision = max(eligible, key=lambda value: (value[0], value[1]))
    return bound, revision


def _draws(bound):
    frame = pd.read_parquet(io.BytesIO(collection.verified(bound)))
    require(len(frame) == 10000, "Each paired model must retain 10000 draws")
    values = frame[["home_score", "away_score"]].to_numpy(float)
    require(np.isfinite(values).all() and (values >= 0).all() and (values == np.floor(values)).all(),
            "Invalid paired score support")
    require((values[:, 0] != values[:, 1]).all(), "Tied CFB draw unsupported")
    for key, expected in (("home_margin", values[:, 0] - values[:, 1]), ("total", values.sum(axis=1))):
        if key in frame:
            require(np.array_equal(frame[key].to_numpy(), expected), "Inconsistent draw-derived metric")
        frame[key] = expected.astype(np.int16)
    return frame


def score_pair(pair, result, outcome_ref):
    target = pd.Series(pair["target"])
    target["scheduled_at"] = collection.utc(target.scheduled_at)
    target["home_score"], target["away_score"] = result["homeFinalPoints"], result["awayFinalPoints"]
    target["home_margin"] = target.home_score - target.away_score
    target["total_points"] = target.home_score + target.away_score
    target["home_win"] = float(target.home_score > target.away_score)
    scores = []
    for arm, artifact, points_name in (("baseline", "gen1Draws", "gen1Points"), ("B", "bDraws", "bPoints")):
        values = pipeline.score_distribution(_draws(pair["artifacts"][artifact]), target)
        points = pair[points_name]
        values.update({"arm": arm, "outcomeRevisionSha256": outcome_ref["sha256"],
                       "low_support": bool(pair["support"]["low_support"]),
                       "zero_prior_support": bool(pair["support"]["zero_prior_support"])})
        errors = {}
        for key, observed in (("home", target.home_score), ("away", target.away_score),
                              ("margin", target.home_margin), ("total", target.total_points)):
            error = float(points["pred_" + key]) - observed
            require(np.isfinite(error), "Nonfinite retained point forecast")
            errors[key] = error
            values[key + "AbsoluteError"] = abs(error)
            values[key + "SquaredError"] = error ** 2
            values[key + "Error"] = error
        values["scoreAbsoluteError"] = (abs(errors["home"]) + abs(errors["away"])) / 2
        values["scoreSquaredError"] = (errors["home"] ** 2 + errors["away"] ** 2) / 2
        scores.append(values)
    return scores


def paired_statistics(rows, repetitions=2000):
    if rows.empty:
        return {"games": 0, "utcDates": 0, "isoWeeks": 0, "metrics": {}, "perWeek": [], "gameBootstrapSensitivity": {}}
    base = rows[rows.arm.eq("baseline")].set_index("game_id").sort_index()
    candidate = rows[rows.arm.eq("B")].set_index("game_id").sort_index()
    require(base.index.equals(candidate.index) and base.index.is_unique, "Paired assessment population differs")
    require(base.outcomeRevisionSha256.equals(candidate.outcomeRevisionSha256), "Models used different outcome revisions")
    for column in ("scheduled_at", "low_support", "zero_prior_support"):
        require(base[column].equals(candidate[column]), "Paired assessment metadata differs")
    difference = candidate[list(METRICS)].to_numpy(float) - base[list(METRICS)].to_numpy(float)
    require(np.isfinite(difference).all(), "Nonfinite paired assessment metric")
    date = base.scheduled_at.dt.strftime("%Y-%m-%d")
    week = base.scheduled_at.dt.strftime("%G-W%V")
    generator = np.random.default_rng(20260918)
    sum_draws = np.zeros((repetitions, len(METRICS)))
    counts = np.zeros(repetitions)
    per_week = []
    for key in sorted(week.unique()):
        in_week = week.eq(key)
        dates = sorted(date[in_week].unique())
        sums = np.array([difference[(in_week & date.eq(day)).to_numpy()].sum(axis=0) for day in dates])
        sizes = np.array([(in_week & date.eq(day)).sum() for day in dates])
        picks = generator.integers(0, len(dates), (repetitions, len(dates)))
        sum_draws += sums[picks].sum(axis=1)
        counts += sizes[picks].sum(axis=1)
        week_effect = difference[in_week.to_numpy()].mean(axis=0)
        per_week.append({"isoWeek": key, "games": int(in_week.sum()), "utcDates": len(dates),
                         "metrics": {metric: float(week_effect[j]) for j, metric in enumerate(METRICS)}})
    bootstrap = sum_draws / counts[:, None]
    # Unstratified paired-game sensitivity is deliberately not the primary CI.
    game_generator = np.random.default_rng(20260919)
    game_bootstrap = np.zeros_like(bootstrap)
    for start in range(0, repetitions, 100):
        amount = min(100, repetitions - start)
        sample = game_generator.integers(0, len(base), (amount, len(base)))
        game_bootstrap[start:start + amount] = difference[sample].mean(axis=1)
    return {"games": len(base), "utcDates": int(date.nunique()), "isoWeeks": int(week.nunique()),
            "bootstrapReplicates": repetitions, "direction": "B_MINUS_GEN1",
            "primaryMethod": "PAIRED_UTC_DATE_BLOCKS_STRATIFIED_BY_ISO_WEEK",
            "metrics": {metric: {"delta": float(difference[:, j].mean()),
                                  "gen1Mean": float(base[metric].mean()), "bMean": float(candidate[metric].mean()),
                                  "low95": float(np.quantile(bootstrap[:, j], .025)),
                                  "high95": float(np.quantile(bootstrap[:, j], .975))} for j, metric in enumerate(METRICS)},
            "perWeek": per_week,
            "gameBootstrapSensitivity": {metric: {"low95": float(np.quantile(game_bootstrap[:, j], .025)),
                                                  "high95": float(np.quantile(game_bootstrap[:, j], .975))}
                                         for j, metric in enumerate(METRICS)},
            "limitations": "Few UTC dates and at most two scheduled ISO weeks; UTC midnight can split the same football slate. Cross-date/team dependence and season transport remain unresolved. Game bootstrap is sensitivity only; draws are never independent observations."}


def _adequate(statistics, rules):
    return (statistics["games"] >= rules["minimumGames"] and statistics["utcDates"] >= rules["minimumUtcDates"]
            and statistics["isoWeeks"] >= rules["minimumIsoWeeks"])


def decide(kind, groups, protocol):
    overall, low = groups["overall"], groups["low_support"]
    adequate_overall = _adequate(overall, protocol["adequacy"]["overall"])
    adequate_low = _adequate(low, protocol["adequacy"]["low_support"])
    decision = {"overallAdequate": adequate_overall, "lowSupportAdequate": adequate_low,
                "zeroPriorSupportDisposition": "INSUFFICIENT_SUBGROUP_EVIDENCE_DESCRIPTIVE_CASES_ONLY",
                "productionAuthority": False, "broadShadowRecommendation": False,
                "promotionAuthority": False, "stopEnrollment": False}
    if not overall["games"]:
        decision["disposition"] = "NO_ELIGIBLE_PAIRED_FINALS"
        return decision
    if kind == "interim":
        harm = (overall["games"] >= 30 and overall["metrics"]["jointEnergyScore"]["delta"] >= .5
                and overall["metrics"]["marginCrps"]["delta"] >= .5)
        decision.update(disposition="INTERIM_HARM_STOP_ENROLLMENT" if harm else "INTERIM_DESCRIPTIVE_NO_POSITIVE_STOP",
                        stopEnrollment=harm)
        return decision
    gates = {"overallAdequate": adequate_overall, "lowSupportAdequate": adequate_low}
    gates["energyImprovementAtLeast010"] = overall["metrics"]["jointEnergyScore"]["delta"] <= -.10
    gates["energyUpper95BelowZero"] = overall["metrics"]["jointEnergyScore"]["high95"] < 0
    for metric, threshold in GUARDRAILS.items():
        gates[metric + "Guardrail"] = overall["metrics"][metric]["delta"] <= threshold
    gates["lowSupportMeanNoHarm"] = bool(low["games"]) and low["metrics"]["jointEnergyScore"]["delta"] <= .05
    gates["lowSupportUpper95NoHarm"] = bool(low["games"]) and low["metrics"]["jointEnergyScore"]["high95"] <= .15
    if not adequate_overall:
        disposition = "INCOMPLETE_OVERALL_EVIDENCE"
    elif not adequate_low:
        disposition = "INCOMPLETE_SUBGROUP_EVIDENCE"
    elif all(gates.values()):
        disposition = "PROMISING_PROSPECTIVE_PILOT"
    else:
        disposition = "NO_PROMISING_PROSPECTIVE_PILOT_SIGNAL"
    decision.update(disposition=disposition, gates=gates)
    return decision


def _assessment(out, protocol_ref, protocol, entry, pairs, revisions, observed_at, monitor_ref):
    cutoff = min(collection.utc(entry["atUtc"]), collection.utc(protocol["acquisitionExpiresAtUtc"]))
    rows, population, pending = [], [], []
    for game_id, commit_ref in pairs.items():
        try:
            commit, pair = _pair(protocol_ref, protocol, game_id, commit_ref)
            selected = select_revision(revisions.get(game_id, []), cutoff)
            if selected is None or selected[1]["result"]["status"] != "SOURCE_FINAL":
                pending.append({"gameId": int(game_id), "reason": "NO_ELIGIBLE_SOURCE_FINAL_AT_LOGICAL_CUTOFF"})
                continue
            outcome_ref, outcome = selected
            require(outcome["protocol"] == protocol_ref and outcome["pairCommit"] == commit_ref, "Outcome pair binding differs")
            paired_rows = score_pair(pair, outcome["result"], outcome_ref)
            rows.extend(paired_rows)
            population.append({"gameId": int(game_id), "pairCommit": commit_ref, "pair": commit["pair"], "outcomeRevision": outcome_ref})
        except (ValueError, KeyError, FileNotFoundError) as exc:
            pending.append({"gameId": int(game_id), "reason": str(exc)})
    scores = pd.DataFrame(rows)
    groups = {"overall": paired_statistics(scores)}
    for group in ("low_support", "zero_prior_support"):
        subset = scores[scores[group]] if len(scores) else scores
        groups[group] = paired_statistics(subset)
    decision = decide(entry["kind"], groups, protocol)
    receipt = {"schema": "CFB_PRIVATE_PROSPECTIVE_ASSESSMENT_V1", "assessmentId": entry["id"], "kind": entry["kind"],
               "protocol": protocol_ref, "dueAtUtc": entry["atUtc"], "executedAtUtc": observed_at,
               "logicalSourceCaptureCutoffUtc": cutoff.isoformat(),
               "cutoffMeaning": "Latest admitted source revision captured by min(scheduled assessment time, acquisition expiry); actual execution clock remains separate and is never backdated.",
               "monitorReceipt": monitor_ref, "enrolledPairs": len(pairs), "pairedFinalGames": len(population),
               "pairedPopulation": population, "pendingOrRejectedPairs": pending, "groups": groups,
               "decision": decision, "scores": collection.save_frame(out, scores, "paired-assessment-scores.parquet") if len(scores) else None,
               "earlierHarmStopPresent": (Path(out) / "STOP_ENROLLMENT.json").exists(),
               "metricsComputed": bool(len(scores)),
               "modelFits": 0, "providerCalls": 0, "productionWrites": 0, "consumerSettlementWrites": 0}
    return collection.save_json(out, receipt, "assessment.json"), receipt


def monitor_and_assess(out, clock=now):
    out = Path(out)
    observed_at = clock()
    protocol_ref, protocol = collection.load_protocol(out)
    _validate_protocol(protocol)
    pairs = collection.pair_index(out)
    revisions, monitor, monitor_ref = monitor_outcomes(out, protocol_ref, protocol, pairs, observed_at)
    completed = _index(out, "ASSESSMENTS.json", "assessments", protocol_ref)
    produced = []
    for entry in sorted(protocol["assessmentSchedule"], key=lambda item: collection.utc(item["atUtc"])):
        if entry["id"] in completed or collection.utc(entry["atUtc"]) > collection.utc(observed_at):
            continue
        bound, receipt = _assessment(out, protocol_ref, protocol, entry, pairs, revisions, observed_at, monitor_ref)
        if receipt["decision"]["stopEnrollment"]:
            stop = {"schema": "CFB_PRIVATE_FROZEN_HARM_STOP_V1", "protocol": protocol_ref, "assessment": bound,
                    "recordedAtUtc": observed_at, "resumeAutomatically": False,
                    "scope": "Stop private research enrollment only; leave authorized production owner unchanged"}
            stop_ref = collection.save_json(out, stop, "stop-enrollment.json")
            collection.atomic_json(out / "STOP_ENROLLMENT.json", {"receipt": stop_ref})
        # Persist a harm stop before the one-time assessment index. A failed
        # stop write must not make a later retry skip the required stop.
        completed[entry["id"]] = bound
        _put_index(out, "ASSESSMENTS.json", "assessments", completed, protocol_ref, observed_at)
        produced.append({"id": entry["id"], "receipt": bound, "disposition": receipt["decision"]["disposition"],
                         "metricsComputed": receipt["metricsComputed"]})
    future = [item["atUtc"] for item in protocol["assessmentSchedule"] if item["id"] not in completed]
    return {"disposition": "ASSESSMENT_RECORDED" if produced else "MONITORED_PENDING_ASSESSMENT" if future else "SCHEDULED_ASSESSMENTS_COMPLETE",
            "monitorReceipt": monitor_ref, "enrolledPairs": len(pairs), "activeSourceFinals": monitor["activeSourceFinals"],
            "newOutcomeRevisions": len(monitor["newRevisions"]), "assessmentReceipts": produced,
            "nextAssessmentAtUtc": min(future, key=collection.utc) if future else None,
            "rejectedEvidence": monitor["rejectedEvidence"], "metricsComputedThisTick": any(item["metricsComputed"] for item in produced),
            "modelFits": 0, "providerCalls": 0}
