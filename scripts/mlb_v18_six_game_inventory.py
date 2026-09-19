"""Read retained original V18 predictions and reconciled wager authority only.

No acquisition, model execution, live database, or nonselected outcomes. One
game uses its exact decision-named object if selected, otherwise its latest
original object published by T-15. The caller performs the later outcome join.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_current_statcast import mlb_starter_duration_quarantine as quarantine

PA_SHA = "44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b"
TRANSITION_SHA = "0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253"
RETAINED_SOURCE_AS_OF_UTC = "2026-09-19T15:17:03.359113Z"
ET = ZoneInfo("America/New_York")
TEAM_IDS = dict(zip("ARI ATL BAL BOS CHC CWS CIN CLE COL DET HOU KC LAA LAD MIA MIL MIN NYM NYY OAK PHI PIT SD SEA SF STL TB TEX TOR WSH".split(),
                    [109,144,110,111,112,145,113,114,115,116,117,118,108,119,146,158,142,121,147,133,143,134,135,136,137,138,139,140,141,120]))
TEAM_IDS.update({"AZ":109,"ATH":133,"CHW":145,"KCR":118,"SDP":135,"SFG":137,"TBR":139,"WSN":120})


def stamp(value):
    value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("NAIVE_SOURCE_CLOCK")
    return value.astimezone(timezone.utc)


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path":str(path), "bytes":len(raw), "sha256":hashlib.sha256(raw).hexdigest()}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _metadata_gate(runtime, path):
    """Project identity metadata before retaining any authority outcome values."""
    quarantine.LEDGER = runtime / "server/artifacts/governance/mlb-final-oot-quarantine-v1.json"
    quarantine.LEDGER_ARCHIVE = quarantine.LEDGER.parent / "mlb-final-oot-quarantine-history/sha256"
    quarantine.quarantine_ledger()
    keys = ("position_id", "game_id", "sport", "kickoff_utc", "era", "producer_forecast_id", "mlbam_game_pk")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        identities = [{key:r[key] for key in keys} for r in csv.DictReader(stream)]
    if len({r["position_id"] for r in identities}) != len(identities):
        raise ValueError("DUPLICATE_AUTHORITY_POSITION")
    mlb = [r for r in identities if r["sport"].upper() == "MLB"]
    for r in mlb:
        day = stamp(r["kickoff_utc"]).astimezone(ET).date().isoformat()
        if "2026-08-14" <= day <= "2026-08-27":
            raise ValueError("SEALED_DATE_AUTHORITY_OUTCOMES_NOT_ADMITTED")
    aliases = [r[k] for r in mlb for k in ("game_id", "mlbam_game_pk") if r[k]]
    if not all(quarantine.final_oot_eligible_key_mask(aliases)):
        raise ValueError("QUARANTINED_AUTHORITY_ID_OUTCOMES_NOT_ADMITTED")
    return identities


def _summary(values):
    ordered = sorted(values)
    def quantile(q):
        z = (len(ordered)-1)*q
        lo = int(z)
        return ordered[lo] + (ordered[min(lo+1,len(ordered)-1)]-ordered[lo])*(z-lo)
    return {"n":len(values),"mean":statistics.mean(values),"sd":statistics.pstdev(values),
            "min":ordered[0],"max":ordered[-1],
            "quantiles":{str(q):quantile(q) for q in (.05,.1,.25,.5,.75,.9,.95)}}


def load_inventory(runtime, authority):
    """Return (rows, exclusions, references), with original wager_* columns.

    Scope is retained September 10-18 local-date pipeline forecasts. This is
    prediction support, not assertion of final outcome availability; missing
    target finals are retained for the caller's coverage/exclusion ledger.
    references is a dictionary containing source bindings, identity receipt,
    legacy position identities, and population counts. Target outcomes occur
    only in selected wager_* fields after the authority identity gate.
    """
    runtime, authority = Path(runtime), Path(authority)
    if authority.is_dir():
        authority = authority / "consumer-followup/historical_positions_outcomes_export.csv"
    pipeline = runtime / "outputs/mlb-v18-current-state-pipeline-v1"
    identities = _metadata_gate(runtime, authority)
    with authority.open(newline="",encoding="utf-8-sig") as stream:
        positions = list(csv.DictReader(stream))
    v18_positions = [r for r in positions if "MLB V18" in r["era"]]
    if len({r['game_id'] for r in v18_positions}) != len(v18_positions):
        raise ValueError('MULTIPLE_SELECTED_POSITIONS_REQUIRE_EXPLICIT_SEPARATE_POSITION_GRAIN')
    selected = {r["game_id"]:r for r in v18_positions}
    if len(selected) != 31:
        raise ValueError("EXPECTED_RECONCILED_V18_31_POSITIONS")
    refs = {str(authority):reference(authority), str(quarantine.LEDGER):reference(quarantine.LEDGER)}
    handoff_paths = set()
    source_as_of = stamp(RETAINED_SOURCE_AS_OF_UTC)
    receipt_counts = Counter()
    for day in sorted(pipeline.joinpath("slates").iterdir()):
        if not "2026-09-10" <= day.name <= "2026-09-18":
            continue
        for file in day.joinpath("sha256").glob("*/slate-result.json"):
            receipt = read_json(file)
            receipt_counts["inspected"] += 1
            if not receipt.get("generatedAt"):
                receipt_counts["missing_source_clock_excluded"] += 1
                continue
            if stamp(receipt["generatedAt"]) > source_as_of:
                receipt_counts["after_retained_source_as_of_excluded"] += 1
                continue
            receipt_counts["within_retained_source_as_of"] += 1
            if receipt.get("handoffPath"):
                handoff_paths.add(pipeline / receipt["handoffPath"])
                refs[str(file)] = reference(file)
    publications = {}
    for path in sorted(handoff_paths):
        obj = read_json(path)
        clock = stamp(obj["generatedAt"])
        if clock > source_as_of:
            receipt_counts["handoffs_after_retained_source_as_of_excluded"] += 1
            continue
        for item in obj.get("forecasts", []):
            sha = item["objectSha256"]
            if sha not in publications or clock < publications[sha][0]:
                publications[sha] = (clock,path,item)
    candidates, exclusions, parsed = {}, [], {}
    for sha, (published,path,item) in sorted(publications.items()):
        file = pipeline / "objects/sha256" / sha / "forecast.json"
        fc = read_json(file)  # prediction-only immutable object, no outcome
        start = stamp(fc["scheduledStart"])
        day = start.astimezone(ET).date().isoformat()
        identity = {"game_id":fc["gameId"],"source_game_id":str(fc["sourceGameId"]),"forecast_identity":"mlb-v18-daily-"+sha,"local_game_date":day}
        reason = None
        if not "2026-09-10" <= day <= "2026-09-18":
            reason = "OUTSIDE_DECLARED_SEPTEMBER_PIPELINE_SCOPE"
        elif not all(quarantine.final_oot_eligible_key_mask([fc["gameId"],str(fc["sourceGameId"])])):
            reason = "PERMANENT_WHOLE_GAME_QUARANTINE"
        elif fc.get("parentAuthority",{}).get("paModelSha256") != PA_SHA or fc.get("parentAuthority",{}).get("transitionModelSha256") != TRANSITION_SHA:
            reason = "SEPARATE_NUMERICAL_IDENTITY"
        elif fc.get("simulation",{}).get("count") != 5000:
            reason = "SEPARATE_DRAW_CONFIGURATION"
        elif published > start-timedelta(minutes=15) or stamp(fc["forecastCreatedAt"]) > start-timedelta(minutes=15):
            reason = "NOT_PROVEN_PUBLISHED_AND_CREATED_BY_T15"
        if reason:
            exclusions.append({**identity,"reason":reason,"published_at":published.isoformat()})
            continue
        parsed[sha] = fc
        rank = (stamp(fc["forecastCreatedAt"]),published,sha)
        game = fc["gameId"]
        if game not in candidates or rank > candidates[game][0]:
            candidates[game] = (rank,sha)
    for game,position in selected.items():
        sha = position["producer_forecast_id"].removeprefix("mlb-v18-daily-")
        if sha not in parsed:
            raise ValueError("SELECTED_EXACT_FORECAST_NOT_ELIGIBLE:"+sha)
        if parsed[sha]["gameId"] != game or str(parsed[sha]["sourceGameId"]) != position["mlbam_game_pk"]:
            raise ValueError("SELECTED_EXACT_IDENTITY_MISMATCH")
        candidates[game] = (None,sha)
    chosen = {sha for _,sha in candidates.values()}
    for sha,fc in parsed.items():
        if sha not in chosen:
            exclusions.append({"game_id":fc["gameId"],"source_game_id":str(fc["sourceGameId"]),"forecast_identity":"mlb-v18-daily-"+sha,"reason":"SUPERSEDED_BY_DECLARED_ONE_GAME_RULE"})
    rows = []
    for game,(_,sha) in sorted(candidates.items()):
        fc = parsed[sha]
        directory = pipeline / "objects/sha256" / sha
        manifest_path = directory / "manifest.json"
        manifest = read_json(manifest_path)
        if manifest.get("objectSha256") != sha or manifest.get("gameId") != game:
            raise ValueError("MANIFEST_IDENTITY_MISMATCH")
        refs[str(manifest_path)] = reference(manifest_path)
        artifact_refs = {}
        for artifact in manifest["artifacts"]:
            path = directory / artifact["relativePath"]
            ref = reference(path)
            if ref["sha256"] != artifact["sha256"] or ref["bytes"] != artifact["bytes"]:
                raise ValueError("ORIGINAL_ARTIFACT_HASH_MISMATCH:"+str(path))
            refs[str(path)] = ref
            artifact_refs[artifact["relativePath"]] = ref
        execution = read_json(directory / "execution-inputs.json")
        population = execution["population"]
        home,away = population["homeRuns"],population["awayRuns"]
        if len(home) != 5000 or len(away) != 5000 or any(h==a for h,a in zip(home,away)):
            raise ValueError("INVALID_ORIGINAL_PAIRED_POPULATION")
        phome = sum(h>a for h,a in zip(home,away))/5000
        if abs(phome-fc["probabilities"]["homeWin"])>1e-12:
            raise ValueError("ORIGINAL_PROBABILITY_RECONCILIATION_FAILURE")
        for side,values in (("home",home),("away",away)):
            if abs(statistics.mean(values)-fc["expectations"][side+"Runs"])>1e-10:
                raise ValueError("ORIGINAL_SCORE_MEAN_RECONCILIATION_FAILURE")
        pub,handoff_path,item = publications[sha]
        refs[str(handoff_path)] = reference(handoff_path)
        position = selected.get(game)
        capture,created,start = (stamp(fc[k]) for k in ("capturedAt","forecastCreatedAt","scheduledStart"))
        row = {"game_id":game,"source_game_id":str(fc["sourceGameId"]),"mlbam_game_pk":str(fc["sourceGameId"]),
               "forecast_identity":"mlb-v18-daily-"+sha,"forecast_object_sha256":sha,"forecast_dir":str(directory),
               "position_id":position["position_id"] if position else "", "selected":bool(position),
               "population":"SELECTED_V18_POSITION" if position else "NONSELECTED_RETAINED_PRODUCER_COMPARATOR",
               "local_game_date":start.astimezone(ET).date().isoformat(),"scheduled_start":start.isoformat(),
               "input_captured_at":capture.isoformat(),"forecast_created_at":created.isoformat(),
               "reference_cutoff_utc":min(capture,created).isoformat(),"decision_cutoff_utc":(start-timedelta(minutes=15)).isoformat(),
               "cutoff_utc":min(capture,created).isoformat(),
               "original_handoff_at":pub.isoformat(),"original_handoff_path":str(handoff_path),
               "handoff_clock_meaning":"RETAINED_HANDOFF_GENERATED_AT_PUBLICATION_CLOCK_PROXY_NOT_ATOMIC_EXPOSURE_PROOF",
               "availability_qualification":"DECISION_NAMED_FORECAST_CONSUMER_RECORD_EXISTS_EXACT_COMMIT_TIME_NOT_RETAINED" if position else "ORIGINAL_HANDOFF_GENERATED_BY_T15_ATOMIC_EXPOSURE_AND_CONSUMER_IMPORT_NOT_ESTABLISHED",
               "comparison_time_rule":"EXACT_DECISION_NAMED_FORECAST" if position else "LATEST_ORIGINAL_PUBLISHED_BY_T15",
               "pa_model_sha256":PA_SHA,"transition_model_sha256":TRANSITION_SHA,"simulation_count":5000,
               "v18_home":statistics.mean(home),"v18_away":statistics.mean(away),"v18_total":statistics.mean(home)+statistics.mean(away),
               "v18_home_mean":statistics.mean(home),"v18_away_mean":statistics.mean(away),
               "v18_margin":statistics.mean(home)-statistics.mean(away),"p_home_win":phome,
               "distribution_ref":{**artifact_refs["execution-inputs.json"],"home_json_pointer":"/population/homeRuns","away_json_pointer":"/population/awayRuns","pairing":"ARRAY_INDEX"},
               "distribution_summary":{"home":_summary(home),"away":_summary(away),"total":_summary([h+a for h,a in zip(home,away)]),"margin":_summary([h-a for h,a in zip(home,away)])},
               "numerical_identity_status":"EXACT_ORIGINAL_OBJECT_AND_ALL_CHILD_HASHES_VERIFIED",
               "historical_deployment_attestation":"NOT_RETAINED_NOT_INFERRED_FROM_CURRENT_OWNER"}
        for side in ("home","away"):
            team = fc["teams"][side.upper()]
            row[side+"_team"] = team["abbreviation"]
            row[side+"_team_name"] = team["name"]
            row[side+"_team_uuid"] = team["uuid"]
            row[side+"_team_mlbam_id"] = TEAM_IDS.get(team["abbreviation"])
            row[side+"_team_id"] = TEAM_IDS.get(team["abbreviation"])
            if row[side+"_team_id"] is None:
                raise ValueError("UNSUPPORTED_ORIGINAL_TEAM_ABBREVIATION:"+team["abbreviation"])
        if position:
            decision = stamp(position["decision_timestamp_utc"])
            if max(capture,created,pub)>decision:
                raise ValueError("SELECTED_CLOCK_AFTER_DECISION")
            predicted_side = phome if position["selected_side"].lower()=="home" else 1-phome
            if abs(predicted_side-float(position["p_win_raw"]))>1e-10:
                raise ValueError("SELECTED_RAW_PROBABILITY_MISMATCH")
            row.update({"wager_"+k:v for k,v in position.items()})
            row["uncertainty_defect_selection"] = position["reconstructed_gates_pass"].lower()=="false"
            row["uncertainty_defect_label"] = "RECONSTRUCTED_DIAGNOSTIC_NOT_ORIGINAL_DECISION"
            for dest,source in {"selected_side":"selected_side","odds_american":"locked_american_odds","odds_decimal":"locked_decimal_odds","stake":"stake","wager_result":"result","profit_actual":"net_profit_original","expected_profit_raw":"expected_profit_raw","expected_profit_controlling":"expected_profit_controlling"}.items():
                row[dest] = position[source]
        else:
            row["uncertainty_defect_selection"] = False
        rows.append(row)
    if sum(r["selected"] for r in rows)!=31 or sum(r["uncertainty_defect_selection"] for r in rows)!=7:
        raise ValueError("AUTHORITY_POPULATION_CHANGED")
    return rows,exclusions,{"sources":list(refs.values()),"retainedSourceAsOfUtc":RETAINED_SOURCE_AS_OF_UTC,"source_receipt_metadata_counts":dict(receipt_counts),"identity_gate":{"scope":"SEPTEMBER_OPERATIONAL_EXPLORATORY_NOT_FINAL_OOT","authority_rows":len(identities),"quarantine_applied_before_authority_outcome_admission":True,"sealed_outcomes_loaded":0},
                            "legacy_positions":[r for r in identities if "MLB V18" not in r["era"]],
                            "counts":{"original_published_objects":len(publications),"selected":31,"nonselected":len(rows)-31,"uncertainty_defect_selections":7,"exclusions":dict(Counter(r["reason"] for r in exclusions))}}
