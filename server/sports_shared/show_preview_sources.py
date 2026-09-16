"""Read-only adapters for already-published, immutable forecast evidence.

No model loaders or outcome readers belong in this module. Historical source
authority is retained, not recertified by a new preview wrapper.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

from .show_preview import NY, canonical, digest, physical, checked_file, utc, iso

NFL_MODEL = "7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd"
CFB_MODEL = "cb3f20293477100c202d48c174f1c3e706c943728697e1089bbb742453876bb6"
NBA_MODEL = "063e69ffb685a16bd784276fa94bce27f8e2d5e91f744e8c9a60a46f242f70ef"


def verify_source_outputs(source):
    """Independently bind published values to the unmodified source payload."""
    raw = checked_file(source["files"][0])
    doc = json.loads(raw)
    sport = source["sport"]
    if sport == "NFL":
        from server.sports_gold.nfl_shadow_exchange import validate_sports_forecast_bundle
        bundle = validate_sports_forecast_bundle(doc)
        f = next(r for r in bundle["forecasts"] if r["forecastId"] == source["source_forecast_id"])
        expected = {"away": f["expectedAwayScore"], "home": f["expectedHomeScore"]}
        probs = {"away_win": f["awayWinProbability"], "home_win": f["homeWinProbability"], "tie": f["tieProbability"]}
        model = f["engine"]["modelBinarySha256"]
        cut, created = f["sourceCutoffUtc"], f["availableAsOfUtc"]
        start, ref = f["scheduledStartUtc"], f["eventId"]
        forecast_sha = digest(canonical(f))
        teams = [f[side+"Team"]["abbreviation"] for side in ("away", "home")]
        count = f["simulator"]["completedSimulations"]
    elif sport == "CFB":
        f, b = doc, doc["baseline"]
        if f["schemaVersion"] != "CFB_GEN1_PROSPECTIVE_RESEARCH_FORECAST_V1" or b["configuration"] != "CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1":
            raise ValueError("CFB baseline identity differs")
        expected = {"away": b["expectedAwayPoints"], "home": b["expectedHomePoints"]}
        probs = {"away_win": b["ridgeAwayWinProbability"], "home_win": b["ridgeHomeWinProbability"], "tie": b["tieProbability"]}
        model = f["modelBindings"]["selectedModel"]["physicalSha256"]
        cut, created = f["sourceCutoff"], f["createdAt"]
        start, ref = f["game"]["scheduled_at"], "cfbd:"+str(f["game"]["game_id"])
        forecast_sha = digest(raw)
        teams = [f["game"][side+"_team"] for side in ("away", "home")]
        if teams != [source["game"][side]["name"] for side in ("away", "home")]:
            raise ValueError("CFB source orientation mismatch")
        teams = [source["game"][side]["abbreviation"] for side in ("away", "home")]
        count = b["drawCount"]
    elif sport == "NBA":
        f, j = doc, doc["jointSimulation"]
        if f["arm"] != "baseline" or f["configurationIdentity"] != "NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1":
            raise ValueError("NBA source not baseline")
        teams = [f["game"][side+"_team_code"] for side in ("away", "home")]
        expected = {side: j["expectedScores"][side+team] for side, team in zip(("away", "home"), teams)}
        probs = {side+"_win": j["winnerProbabilities"][side+team] for side, team in zip(("away", "home"), teams)}
        probs["tie"] = j["winnerProbabilities"]["tie"]
        model, cut, created = NBA_MODEL, f["sourceCutoffUtc"], f["createdAtUtc"]
        start, ref = f["game"]["scheduled_tipoff_utc"], f["game"]["game_id"]
        forecast_sha, count = digest(raw), j["drawCount"]
    elif sport == "MLB":
        from .mlb_show_preview_team import CONFIG, verify_point_source
        f = doc
        verify_point_source(f)
        availability = json.loads(checked_file(source["files"][4]))
        if availability["sourceFile"] != source["files"][0] or availability["availableAtUtc"] != source["source_available_utc"]:
            raise ValueError("MLB source availability differs")
        expected, probs = f["expectedScore"], f["probabilities"]
        model = f["modelFile"]["sha256"]
        cut, created = f["sourceCutoffUtc"], f["createdAtUtc"]
        start, ref = f["game"]["kickoff_utc"], f["game"]["source_game_ref"]
        forecast_sha, count = digest(raw), 0
        teams = [f["game"][side]["abbreviation"] for side in ("away", "home")]
        if source["model"]["model_version"] != CONFIG:
            raise ValueError("MLB preview model differs")
    else:
        raise ValueError("MLB preview not admitted: current feature/lineup authority missing")
    if (expected != source["expected_score"] or probs != source["probabilities"] or model != source["model"]["artifact_sha256"]
            or cut != source["source_cutoff_utc"] or created != source["source_created_utc"]
            or utc(start) != utc(source["game"]["kickoff_utc"]) or ref != source["game"]["source_game_ref"]
            or teams != [source["game"][side]["abbreviation"] for side in ("away", "home")]
            or count != source["simulation"]["draw_count"] or forecast_sha != source["source_forecast_sha256"]
            or f["forecastId"] != source["source_forecast_id"]):
        raise ValueError("source numerical forecast, identity or clocks were changed")


def game_identity(context, sport, ref, start, away, home):
    rows = context["rows"]
    matches = [r for r in rows if r["league"] == sport and utc(r["starts_at"]) == utc(start)]
    home_ids = {r["canonical_game_id"] for r in matches if r["is_home"] and r["abbreviation"] == home["abbreviation"]}
    away_ids = {r["canonical_game_id"] for r in matches if not r["is_home"] and r["abbreviation"] == away["abbreviation"]}
    matched = home_ids & away_ids
    if len(matched) > 1:
        raise ValueError("ambiguous canonical schedule")
    if sport != "CFB" and not matched:
        raise ValueError("exact consumer schedule/orientation unavailable")
    return {"canonical_game_id": next(iter(matched), None), "source_game_ref": ref,
            "slate_date": utc(start).astimezone(NY).date().isoformat(), "kickoff_utc": iso(start),
            "away": away, "home": home}


def evidence(cutoff, missing):
    codes = [r["code"] for r in missing]
    return {side: {"starter_status": "UNKNOWN", "lineup_status": "UNKNOWN",
                   "missing_evidence": codes, "source_cutoff_utc": cutoff,
                   "fallback_rule": "EXACT_FROZEN_SOURCE_REUSE_NO_PERSONNEL_SUBSTITUTION",
                   "uncertainty": "Current players, starters, injuries and lineups are not certified by this model."}
            for side in ("away", "home")}


def base(sport, source_id, source_schema, source_horizon, source_sha, cutoff, created,
         available, publication, files, context, game, model, feature_contract,
         simulation, scores, probabilities, distribution, semantics, limitations, extra_missing=()):
    missing = [{"code": "PLAYER_STATUS_UNAVAILABLE", "message": "No certified current player, starter, injury or lineup evidence enters this source forecast."},
               {"code": "PREVIEW_SOURCE_NOT_REFRESHED", "message": "Values reuse the named earlier source; information arriving after its cutoff is not included."},
               *extra_missing]
    return {"sport": sport, "league": sport, "season": 2026, "game": game,
            "source_forecast_id": source_id, "source_schema": source_schema,
            "source_horizon": source_horizon, "source_forecast_sha256": source_sha,
            "source_cutoff_utc": cutoff, "source_created_utc": created,
            "source_available_utc": available, "source_publication_utc": publication,
            "files": files, "availability_proof": {
                "method": "EXISTING_PUBLISHED_CONTENT_ADDRESSED_SOURCE_VERIFIED_BEFORE_PREVIEW_CREATION",
                "identity_projection_captured_utc": context["captured_utc"],
                "original_clocks_preserved": True, "forecast_not_regenerated": True},
            "model": model, "feature_contract": feature_contract, "simulation": simulation,
            "expected_score": scores, "probabilities": probabilities, "distribution": distribution,
            "forecast_output_semantics": semantics,
            "availability": {"starters": "UNKNOWN", "lineups": "UNKNOWN"},
            "missing_evidence": missing, "team_evidence": evidence(cutoff, missing), "limitations": limitations}


def nfl_source(bundle_path, forecast_id, context):
    from server.sports_gold.nfl_shadow_exchange import verify_sports_forecast_bundle
    path = Path(bundle_path)
    verified = verify_sports_forecast_bundle(path.parents[3], path.parent.name)
    bundle = verified.record
    f = next(x for x in bundle["forecasts"] if x["forecastId"] == forecast_id)
    if f["engine"]["modelBinarySha256"] != NFL_MODEL or f["engine"]["engineId"] != "NFL_M1_XGBOOST":
        raise ValueError("unapproved NFL source model")
    if f["features"]["readiness"]["isReady"] is not True:
        raise ValueError("NFL_SOURCE_INPUTS_PENDING")
    game = game_identity(context, "NFL", f["eventId"], f["scheduledStartUtc"],
                         {"abbreviation": f["awayTeam"]["abbreviation"], "name": f["awayTeam"]["displayName"]},
                         {"abbreviation": f["homeTeam"]["abbreviation"], "name": f["homeTeam"]["displayName"]})
    n = f["simulator"]["completedSimulations"]
    pairs = f["jointScoreDistribution"]
    counts = [round(r["probability"] * n) for r in pairs]
    if sum(counts) != n or any(abs(c/n-r["probability"]) > 1e-10 for c, r in zip(counts, pairs)):
        raise ValueError("NFL retained joint population does not reconcile")
    for side in ("away", "home"):
        mean = sum(r[side+"Score"] * c for r, c in zip(pairs, counts)) / n
        if abs(mean-f["expected"+side.title()+"Score"]) > 1e-8:
            raise ValueError("NFL retained mean mismatch")
    interval = f["predictionInterval"]
    level = str(round(100 * interval["confidenceLevel"]))
    distribution = {"margin_intervals": {level: {"lower": interval["marginLower"], "upper": interval["marginUpper"]}},
                    "total_intervals": {level: {"lower": interval["totalLower"], "upper": interval["totalUpper"]}},
                    "joint_source_field": "source-0.json.forecasts[forecastId].jointScoreDistribution",
                    "joint_population_sha256": digest(canonical(pairs)), "full_tail_retained": True}
    return base("NFL", f["forecastId"], f["schemaVersion"], f["snapshotType"], digest(canonical(f)),
                f["sourceCutoffUtc"], f["availableAsOfUtc"], bundle["generatedAtUtc"], bundle["generatedAtUtc"],
                [physical(path), physical(path.parent / "consumer-import-fixture.json")], context, game,
                {"model_id": f["engine"]["engineId"], "model_version": f["engine"]["engineVersion"], "artifact_sha256": NFL_MODEL},
                {"sha256": f["engine"]["featureContractSha256"], "feature_vector_sha256": f["features"]["featureVectorSha256"],
                 "input_count": 197, "source_feature_readiness": f["features"]},
                {"identity": f["simulator"]["simulatorId"], "version": f["simulator"]["simulatorVersion"],
                 "seed": f["simulator"]["seed"], "draw_count": n, "reused": True},
                {"away": f["expectedAwayScore"], "home": f["expectedHomeScore"]},
                {"away_win": f["awayWinProbability"], "home_win": f["homeWinProbability"], "tie": f["tieProbability"]},
                distribution, "All scores/probabilities reuse the original paired-residual final-score population, including modeled ties.",
                ["Equal retained score pairs produce tie mass; this is not an independently calibrated NFL overtime/tie model.",
                 "Frozen training, source revision and current-input limitations remain; no new source capture or inference.",
                 "No EPA challenger, personnel correction or market signal is used; MCSE measures sampling precision only."],
                [{"code": "FROZEN_IMPUTATION", "message": "Frozen training imputation covers: " + ', '.join(f['features']['missingFeatures'])}]
                if f["features"]["missingFeatures"] else [])


def cfb_source(package, context):
    directory = Path(package)
    idx = directory / "index.json"
    if digest(idx.read_bytes()) != directory.name:
        raise ValueError("CFB index physical address mismatch")
    index = json.loads(idx.read_bytes())
    for item in index["files"]:
        checked_file({"path": str(directory / item["path"]), "sha256": item["physicalSha256"], "bytes": item["bytes"]})
    path = directory / "forecast.json"
    f = json.loads(path.read_bytes())
    b = f["baseline"]
    if b["configuration"] != "CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1" or f["modelBindings"]["selectedModel"]["physicalSha256"] != CFB_MODEL:
        raise ValueError("CFB cluster/gap or unknown model is not admitted")
    published = json.loads((directory / "publication-receipt.json").read_bytes())["publishedAtUtc"]
    g = f["game"]
    # Team abbreviations are producer labels when AISP has no CFB schedule.
    team_codes = {"Syracuse": "SYR", "Pittsburgh": "PITT"}
    def team(name):
        return {"name": name, "abbreviation": team_codes.get(name, name.upper())}
    game = game_identity(context, "CFB", "cfbd:" + str(g["game_id"]), g["scheduled_at"], team(g["away_team"]), team(g["home_team"]))
    intervals = {dest: {str(r["level"]): {"lower": r["lower"], "upper": r["upper"]}
                        for r in b["intervals"] if r["metric"] == src}
                 for dest, src in (("margin_intervals", "home_margin"), ("total_intervals", "total"))}
    intervals.update(full_tail_retained=True, population_member="source-2.parquet")
    return base("CFB", f["forecastId"], f["schemaVersion"], "PROSPECTIVE_RESEARCH", digest(path.read_bytes()),
                f["sourceCutoff"], f["createdAt"], published, published,
                [physical(path), physical(idx), physical(directory / "baseline-joint-draws.parquet"),
                 physical(directory / "baseline-pmfs.parquet"), physical(directory / "publication-receipt.json")], context, game,
                {"model_id": "CFB_GEN1_RIDGE", "model_version": b["configuration"], "artifact_sha256": CFB_MODEL},
                {"sha256": f["modelBindings"]["featureContract"]["physicalSha256"], "input_count": 35},
                {"identity": b["configuration"], "draw_count": b["drawCount"],
                 "seed": int.from_bytes(bytes.fromhex(digest(f"20260914|{g['game_id']}|ridge_alpha100".encode()))[:8], "big") % (2**32-1),
                 "seed_disposition": "Derived metadata from existing pipeline._seed_for, master20260914 and ridge_alpha100; no new draws.", "reused": True},
                {"away": b["expectedAwayPoints"], "home": b["expectedHomePoints"]},
                {"away_win": b["ridgeAwayWinProbability"], "home_win": b["ridgeHomeWinProbability"], "tie": b["tieProbability"]},
                intervals, "Expected points are Ridge outputs; win probability is the separately calibrated Ridge-margin channel. Intervals use the retained paired-residual population, whose home-win probability is " + str(b['jointHomeWinProbability']) + ". They are not summaries of one shared estimator.",
                f["limitations"] + ["No new CFB challenger is enabled; the source's empty challenger field confers no preview authority.",
                                     "CFB source-game reference is retained when AISP has no canonical game; consumer binding remains required."],
                [{"code": "CONSUMER_GAME_BINDING_PENDING", "message": "No exact CFB canonical game exists in the read-only consumer schedule projection."}] if not game["canonical_game_id"] else [])


def nba_source(forecast_ref, population_ref, publication_ref, model_ref, feature_ref, context):
    """Capability for an eligible NBA baseline; not called to restamp BOS-DET."""
    f = json.loads(checked_file(forecast_ref))
    checked_file(population_ref)
    if f["arm"] != "baseline" or f["configurationIdentity"] != "NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1" or model_ref["sha256"] != NBA_MODEL:
        raise ValueError("unapproved NBA joint authority")
    receipt = json.loads(checked_file(publication_ref))
    published = receipt["publishedAtUtc"]
    g, j = f["game"], f["jointSimulation"]
    away, home = g["away_team_code"], g["home_team_code"]
    game = game_identity(context, "NBA", g["game_id"], g["scheduled_tipoff_utc"],
                         {"name": away, "abbreviation": away}, {"name": home, "abbreviation": home})
    intervals = {key+"_intervals": {str(round(r["level"]*100)): {"lower": r["lower"], "upper": r["upper"]}
                                     for r in j["intervals"][key]} for key in ("margin", "total")}
    intervals.update(full_tail_retained=True, population_member="source-1.parquet")
    return base("NBA", f["forecastId"], f["schema"], "PROSPECTIVE_JOINT_RESEARCH", forecast_ref["sha256"],
                f["sourceCutoffUtc"], f["createdAtUtc"], published, published,
                [forecast_ref, population_ref, publication_ref], context, game,
                {"model_id": "NBA_GEN1_JOINT_BASELINE", "model_version": f["configurationIdentity"], "artifact_sha256": NBA_MODEL},
                feature_ref, {"identity": f["configurationIdentity"], "draw_count": j["drawCount"], "master_seed": 20260914,
                              "seed": None, "seed_disposition": "Per-stream seeds inherited from original baseline simulation receipt; no new randomness.", "reused": True},
                {"away": j["expectedScores"]["away"+away], "home": j["expectedScores"]["home"+home]},
                {"away_win": j["winnerProbabilities"]["away"+away], "home_win": j["winnerProbabilities"]["home"+home], "tie": j["winnerProbabilities"]["tie"]},
                intervals, "Joint baseline population; published Elo remains a separate unchanged channel. Close-score challenger excluded.", f["limitations"])
