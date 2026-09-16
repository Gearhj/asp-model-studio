"""Local saved-forecast diagnosis only. No DB, inference, fit, or simulations.

The identity stage precedes outcome loading. The market export is accepted only
when its identity-only schedule member covers every declared event and excludes
the sealed interval. All canonical/MLBAM aliases are checked with the governance
helper. Forecast selection is written before the outcome member is opened.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask, quarantine_ledger
from server.sports_silver.canonical_ids import canonical_game_id

OUT = ROOT / "outputs/mlb-v18-empirical-diagnosis-v1/whole-game"
MARKET = ROOT / "outputs/market-intelligence-rff-v1/source/sha256/df6ded6fa0356ff12c6e1d33dcb816cff12660c4f627b733a9336e04caefaa27"
MARKET_MANIFEST_SHA256 = "df6ded6fa0356ff12c6e1d33dcb816cff12660c4f627b733a9336e04caefaa27"
READS = {}


def read(path):
    path = Path(path)
    b = path.read_bytes()
    READS[str(path.relative_to(ROOT))] = {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}
    return json.loads(b)


def stamp(s):
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    assert t.tzinfo is not None
    return t.astimezone(timezone.utc)


def eligible_dates(s):
    from zoneinfo import ZoneInfo
    t = stamp(s)
    return all(not "2026-08-14" <= t.astimezone(z).date().isoformat() <= "2026-08-27"
               for z in (timezone.utc, ZoneInfo("America/New_York")))


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8")


def table(name, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with (OUT / name).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v for k, v in row.items()})


def member(manifest, name):
    meta = manifest["files"][name]
    path = MARKET / meta["path"]
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == meta["sha256"] and len(raw) == meta["bytes"]
    READS[str(path.relative_to(ROOT))] = {"sha256": meta["sha256"], "bytes": len(raw)}
    plain = gzip.decompress(raw)
    assert hashlib.sha256(plain).hexdigest() == meta["uncompressedSha256"]
    rows = json.loads(plain)
    assert len(rows) == meta["rowCount"]
    return rows


def validate_forecast_evidence(f, manifest, snapshot):
    """Identity and chronology guards, checked before any outcome member opens."""
    original = f.get("schemaVersion") == "MLB_V18_PROSPECTIVE_WHOLE_GAME_SIMULATION_V1"
    assert f["gameId"] == snapshot["game"]["game_id"], "FORECAST_SNAPSHOT_GAME_ID_MISMATCH"
    if "gameId" in manifest:
        assert manifest["gameId"] == f["gameId"], "MANIFEST_GAME_ID_MISMATCH"
    else:
        assert original, "MANIFEST_GAME_ID_REQUIRED_FOR_DAILY_SCHEMA"
    if "sourceGameId" in f:
        assert str(f["sourceGameId"]) == str(snapshot["game"]["source_game_id"]), "MLBAM_ALIAS_MISMATCH"
    else:
        assert original, "MLBAM_ALIAS_REQUIRED_FOR_DAILY_SCHEMA"
    assert stamp(f["scheduledStart"]) == stamp(snapshot["game"]["starts_at"]), "SCHEDULED_START_MISMATCH"
    assert stamp(f["capturedAt"]) == stamp(snapshot["capturedAt"]), "CAPTURE_CLOCK_MISMATCH"
    created=f.get("forecastCreatedAt")
    if created:
        assert stamp(f["capturedAt"]) <= stamp(created) < stamp(f["scheduledStart"]), "CAPTURE_CREATION_START_ORDER_INVALID"
        cutoff=f.get("sourceCutoff") or {}
        for key in ("evidenceAvailableAt", "snapshotCapturedAt"):
            if cutoff.get(key):
                assert stamp(cutoff[key]) <= stamp(created), "SOURCE_CUTOFF_AFTER_CREATION"
    else:
        assert stamp(f["capturedAt"]) < stamp(f["scheduledStart"]), "CAPTURE_NOT_PREGAME"
    return ("ORIGINAL_BUNDLE_SCHEMA_HAS_NO_MANIFEST_GAME_ID_OR_FORECAST_MLBAM_ALIAS; "
            "use manifest-authenticated snapshot gameId/MLBAM/start with matching forecast gameId/start; "
            "timezone-aware starts compared as exact UTC instants" if original else
            "MANIFEST_SNAPSHOT_FORECAST_GAME_IDS_AND_MLBAM_ALIAS_AGREE; exact UTC scheduled start and capture clocks agree")


def normalize(p, manifest, snapshot, family):
    f = read(p)
    expected=next(x for x in manifest["artifacts"] if x["relativePath"]==p.name)
    actual=READS[str(p.relative_to(ROOT))]
    assert actual["sha256"]==expected["sha256"] and actual["bytes"]==expected["bytes"]
    old = "meanHomeRuns" in f
    snapshot_name = "aisp-pregame-snapshot.json" if old else "pregame-evidence.json"
    expected_snapshot = next(x for x in manifest["artifacts"] if x["relativePath"] == snapshot_name)
    actual_snapshot = READS[str((p.parent / snapshot_name).relative_to(ROOT))]
    assert actual_snapshot["sha256"] == expected_snapshot["sha256"] and actual_snapshot["bytes"] == expected_snapshot["bytes"], "SNAPSHOT_MANIFEST_HASH_OR_BYTES_MISMATCH"
    identity_linkage = validate_forecast_evidence(f, manifest, snapshot)
    source = str(snapshot["game"]["source_game_id"])
    assert all(final_oot_eligible_key_mask([source, f["gameId"]]))
    start = f["scheduledStart"]
    assert eligible_dates(start)
    ds = ({"homeRuns": f["homeRunDistribution"], "awayRuns": f["awayRunDistribution"],
           "homeMinusAwayRuns": f["runDifferentialDistribution"], "totalRuns": f["totalRunDistribution"]}
          if old else f["distributions"])
    means = ({"homeRuns": f["meanHomeRuns"], "awayRuns": f["meanAwayRuns"],
              "homeMinusAwayRuns": f["meanRunDifferential"], "totalRuns": f["meanTotalRuns"]}
             if old else f["expectations"])
    parent = f.get("parentAuthority", {})
    pa = parent.get("paModelSha256") or next(x["sha256"] for x in manifest["paModels"] if x["foldNumber"] == 5)
    transition = parent.get("transitionModelSha256") or manifest["transition"]["sha256"]
    teams = f.get("teams") or {s["side"]: s["team"] for s in snapshot["sides"]}
    created = f.get("forecastCreatedAt")
    captured = f["capturedAt"]
    when = created or captured
    valid = stamp(when) < stamp(start) and stamp(captured) < stamp(start)
    record = {"forecast_path": str(p.relative_to(ROOT)), "forecast_sha256": READS[str(p.relative_to(ROOT))]["sha256"],
              "game_id": f["gameId"], "mlbam_game_pk": source,
              "game_date": stamp(start).astimezone(__import__('zoneinfo').ZoneInfo("America/New_York")).date().isoformat(),
              "scheduled_start": stamp(start).isoformat(), "captured_at": stamp(captured).isoformat(),
              "created_at": stamp(created).isoformat() if created else None,
              "forecast_horizon_hours": (stamp(start)-stamp(when)).total_seconds()/3600,
              "capture_horizon_hours": (stamp(start)-stamp(captured)).total_seconds()/3600,
              "family": family, "lineage": family + ':' + str(manifest.get("bundleSha256", parent.get("bundleSha256", ""))),
              "pa_fold": 5, "pa_model_sha256": pa, "transition_fold": 4, "transition_sha256": transition,
              "away_team": teams["AWAY"]["abbreviation"], "home_team": teams["HOME"]["abbreviation"],
              "home_probability": f["homeWinProbability"] if old else f["probabilities"]["homeWin"],
              "home_runs": means["homeRuns"], "away_runs": means["awayRuns"],
              "home_margin": means["homeMinusAwayRuns"], "total_runs": means["totalRuns"],
              "pregame_candidate": valid,
              "identity_linkage": identity_linkage,
              "capture_creation_source_cutoff_checks_passed": bool(created),
              "timing_status": "CREATION_BEFORE_SCHEDULED_START_TRAINING_TIMING_UNCERTAIN" if created and valid else "PREGAME_CAPTURE_COMPLETION_TIME_UNVERIFIED_TRAINING_TIMING_UNCERTAIN",
              "lineup_modes": [s.get("lineupAuthority", {}).get("status") for s in snapshot["sides"]],
              "starter_ids": [s.get("starter", {}).get("mlbamId") for s in snapshot["sides"]],
              "lineup_players": [str(x["mlbam"]) for s in snapshot["sides"] for x in s.get("lineup", []) if x.get("mlbam")],
              "starter_hands": [s.get("starter", {}).get("throws") for s in snapshot["sides"]],
              "venue": snapshot["game"].get("venue"), "temperature_f": (snapshot.get("weather") or {}).get("temperature_f"),
              "wind_mph": (snapshot.get("weather") or {}).get("wind_mph"),
              "source_cutoff": f.get("sourceCutoff"), "limitations": f.get("knownLimitations", manifest.get("limitations", [])),
              "saved_marginals": list(ds), "saved_joint_distribution": False, "outcome_status": "NOT_YET_READ"}
    for name, rows in ds.items():
        v = np.array([x["value"] for x in rows], float); w = np.array([x["probability"] for x in rows], float)
        assert np.all(w >= 0) and abs(w.sum()-1) < 1e-9
        assert abs(v@w - means[name]) < 1e-9
    return record, ds


def quantile(v, w, q):
    idx = np.argsort(v); v, w = v[idx], w[idx]
    return float(v[min(np.searchsorted(np.cumsum(w), q, side="left"), len(v)-1)])


def marginal(ds, y):
    v = np.array([x["value"] for x in ds], float); w = np.array([x["probability"] for x in ds], float)
    mean = float(v@w)
    result = {"observed": y, "mean": mean, "signed_error": mean-y, "absolute_error": abs(mean-y),
              "sd": float(np.sqrt(((v-mean)**2)@w)),
              "crps": float(np.abs(v-y)@w - .5*(np.abs(v[:,None]-v[None,:]) * w[:,None] * w[None,:]).sum()),
              "pmf_at_observed": float(w[v==y].sum())}
    # Zero finite-empirical probability is reported, never smoothed or floored.
    result["discrete_log_score"] = -float(np.log(result["pmf_at_observed"])) if result["pmf_at_observed"] > 0 else None
    result["zero_probability_observation"] = result["pmf_at_observed"] == 0
    for level in (.5, .8, .9):
        lo, hi = quantile(v,w,(1-level)/2), quantile(v,w,(1+level)/2)
        result[f"lower_{int(level*100)}"] = lo; result[f"upper_{int(level*100)}"] = hi
        result[f"covered_{int(level*100)}"] = lo <= y <= hi
        result[f"width_{int(level*100)}"] = hi-lo
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frozen_manifest = json.loads((OUT / "artifact-manifest.json").read_text(encoding="utf-8")) if (OUT / "artifact-manifest.json").exists() else None
    frozen_inputs = frozen_manifest["input_files"] if frozen_manifest else None
    ledger = quarantine_ledger()
    records, distributions = [], {}
    for family in ("mlb-v18-daily-slate", "mlb-v18-current-state-pipeline-v1"):
        for mp in sorted((ROOT / "outputs" / family / "objects/sha256").glob("*/manifest.json")):
            if frozen_inputs is not None and str(mp.relative_to(ROOT)) not in frozen_inputs: continue
            m = read(mp)
            if not (mp.parent/"forecast.json").is_file(): continue
            assert all(final_oot_eligible_key_mask([m["gameId"]]))
            snapshot = read(mp.parent/"pregame-evidence.json")  # no outcome columns
            assert all(final_oot_eligible_key_mask([snapshot["game"]["source_game_id"]]))
            assert eligible_dates(snapshot["game"]["starts_at"])
            r, ds = normalize(mp.parent/"forecast.json", m, snapshot, family)
            records.append(r); distributions[r["forecast_sha256"]] = ds
    for mp in sorted((ROOT/"outputs/mlb-v18-whole-game-challenger/sha256").glob("*/manifest.json")):
        if frozen_inputs is not None and str(mp.relative_to(ROOT)) not in frozen_inputs: continue
        m = read(mp); snapshot = read(mp.parent/"aisp-pregame-snapshot.json")
        assert all(final_oot_eligible_key_mask([snapshot["game"]["source_game_id"]])) and eligible_dates(snapshot["game"]["starts_at"])
        r,ds=normalize(mp.parent/"prospective-forecast.json",m,snapshot,"whole-game-prototype")
        records.append(r); distributions[r["forecast_sha256"]]=ds
    # Deterministic selection within versions; cross-version rows never multiply games.
    records.sort(key=lambda r: (r["created_at"] or r["captured_at"], r["forecast_sha256"]))
    seen=set()
    for r in records:
        k=(r["game_id"],r["lineage"])
        r["selected_within_lineage"]=r["pregame_candidate"] and k not in seen
        if r["selected_within_lineage"]: seen.add(k)
    primary={}
    for r in records:
        if r["selected_within_lineage"]:
            key=(r["created_at"] or r["captured_at"],r["forecast_sha256"],r["lineage"],r["forecast_path"])
            if r["game_id"] not in primary or key < primary[r["game_id"]][0]:
                primary[r["game_id"]]=(key,r["forecast_path"])
    for r in records:
        r["selected_primary_game"] = r["game_id"] in primary and primary[r["game_id"]][1] == r["forecast_path"]
    assert sum(r["selected_primary_game"] for r in records)==len(primary)
    write("review-compliance-addendum.json",{
        "change_status":"REVIEW_GUARD_AND_PROTOCOL_COMPLIANCE_AFTER_INITIAL_FINDINGS",
        "original_selection_and_version_metrics_preserved":True,
        "primary_game_selection":"One earliest selected candidate across lineages per game, using original creation-or-exploratory-capture timestamp, then immutable forecast SHA256, lineage and path. Creation-unverified forecasts remain exploratory. This is accounting, not a new pooled performance estimate.",
        "casebook_additions":"Retain original seven cases; include largest winner log loss and median sum-of-team-absolute-errors case (ties gameId), as required by root protocol. Added examples are labeled protocol-compliance inclusions after initial findings.",
        "guards":"Require capturedAt <= forecastCreatedAt < scheduledStart and saved sourceCutoff evidenceAvailableAt/snapshotCapturedAt <= creation when creation exists; authenticate snapshot bytes/SHA and cross-check game IDs, MLBAM aliases, exact UTC start/capture clocks. Original prototype schema omissions explicitly labeled.",
        "no_duplicate_observed_games_pooled":True})
    # Prototype duplicate bundle variants remain a separate stratum from daily outputs.
    protocol={"declared_at_utc": datetime.now(timezone.utc).isoformat(),
      "selection": "Per game and immutable version lineage, earliest forecastCreatedAt strictly before scheduled start, ties by forecast SHA256. If createdAt is absent, earliest capturedAt defines a separate exploratory capture cohort; completion before start is unverified. All statuses/decisions included; no price, NO_BET, position, or result filter.",
      "horizon": "Full game including extras; lead hours from actual creation timestamp where saved, otherwise capture lead only. Scheduled start is a proxy for first pitch.",
      "cases": "Within daily-slate outcome-supported cohort: union of top three absolute total errors, top three absolute home-margin errors, plus two smallest sum-of-team-absolute-errors; ties date/gameId. Describe all scored rows, selected severe and successful cases are examples, not independent evidence.",
      "slices": ["lineup certainty", "starter handedness", "park", "pregame forecast confidence (<.60/.60-.70/>=.70 favorite probability)", "date", "family/immutable version"],
      "confirmation": "Date cohorts and chronological halves descriptive. Recurrence requires multiple supported later dates/weeks; sparse whole-game dates cannot confirm any subgroup. No adaptively selected subgroup is independently confirmed.",
      "uncertainty": "Descriptive equal-game metrics and 2000 game-resampling bootstrap mean intervals when n>=5; no temporal-block interval when fewer than four distinct weeks. Bootstrap resampling observed games is not forecast simulation.",
      "sealed_dates": ["2026-08-14","2026-08-27"], "quarantine": ledger,
      "authoritative_reduced_oot_count": 13837, "oot_outcomes_read":0,
      "selection_identity_records": [{k:r[k] for k in ("game_id","mlbam_game_pk","game_date","forecast_sha256","lineage","selected_within_lineage")} for r in records]}
    if (OUT / "selection-before-outcomes.json").exists():
        original_protocol = json.loads((OUT / "selection-before-outcomes.json").read_text(encoding="utf-8"))
        assert original_protocol["selection_identity_records"] == protocol["selection_identity_records"], "Frozen selection must be preserved; use a new analysis namespace for new forecasts"
    else:
        write("selection-before-outcomes.json",protocol)
    # This member contains schedule/status metadata only, never final scores.
    mm=read(MARKET/"manifest.json")
    assert READS[str((MARKET/"manifest.json").relative_to(ROOT))]["sha256"]==MARKET_MANIFEST_SHA256, "UNTRUSTED_MARKET_EXPORT_MANIFEST"
    assert mm["sealedBoundary"]["excludedDatesInclusive"]==["2026-08-14","2026-08-27"]
    metadata=member(mm,"game_state_observations")
    safe_ids={x["event_id"] for x in metadata}
    alias_by_id={}
    starts_by_id={}
    for x in metadata:
        assert x["source"] == "MLB_STATS_API" and str(x["source_record_id"]).isdigit(), "MLBAM_IDENTITY_AUTHORITY_REQUIRED"
        alias_by_id.setdefault(x["event_id"],set()).add(str(x["source_record_id"]))
        starts_by_id.setdefault(x["event_id"],set()).add(stamp(x["scheduled_at"]).isoformat())
    assert set(alias_by_id)==safe_ids and all(len(v)==1 for v in alias_by_id.values()), "AMBIGUOUS_OR_MISSING_EXPORT_MLBAM_ALIAS"
    export_aliases={k:next(iter(v)) for k,v in alias_by_id.items()}
    assert len(set(export_aliases.values()))==len(safe_ids), "ONE_MLBAM_GAME_MAPPED_TO_MULTIPLE_EVENTS"
    canonical_aliases={k:canonical_game_id(v) for k,v in export_aliases.items()}
    assert all(final_oot_eligible_key_mask(list(export_aliases.values())+list(canonical_aliases.values()))), "QUARANTINED_EXPORT_GAME_ALIAS"
    assert all(x.get("scheduled_at") and eligible_dates(x["scheduled_at"]) for x in metadata)
    assert len(safe_ids)==mm["files"]["events"]["rowCount"], "Cannot establish every export event from identity-only schedule metadata"
    # Independently map local forecast aliases through MLBAM before outcome access.
    assert all(final_oot_eligible_key_mask([r["mlbam_game_pk"] for r in records]))
    assert all(export_aliases[r["game_id"]]==r["mlbam_game_pk"] for r in records if r["game_id"] in export_aliases), "LOCAL_FORECAST_EXPORT_ALIAS_MISMATCH"
    export_gate={"identity_only_member":"game_state_observations.json.gz","rows":len(metadata),"unique_events":len(safe_ids),
      "all_schedule_dates_outside_seal":True,"local_forecast_mlbam_aliases_checked":len(records),
      "all_export_mlbam_aliases_checked":len(export_aliases),"all_export_canonical_aliases_checked":len(canonical_aliases),
      "source_manifest_pinned_sha256":MARKET_MANIFEST_SHA256,
      "permanent_excluded_local_candidates":0,"sealed_local_candidates":0,
      "manifest_files_matched_by_sha256":True,"eligible_event_ids":sorted(safe_ids),
      "event_alias_and_schedule_identity":[{"event_id":k,"mlbam_game_pk":export_aliases[k],"canonical_game_id":canonical_aliases[k],"schedule_instants_utc":sorted(starts_by_id[k])} for k in sorted(safe_ids)]}
    write("export-identity-gate-before-outcomes.json",export_gate)
    events=member(mm,"events")
    assert {e["event_id"] for e in events}==safe_ids
    assert all(eligible_dates(e["event_start"]) for e in events)
    assert all(stamp(e["event_start"]).isoformat() in starts_by_id[e["event_id"]] for e in events), "EVENT_START_NOT_BOUND_TO_IDENTITY_METADATA"
    event_map={e["event_id"]:e for e in events}
    final_observations=member(mm,"final_state_observations")
    assert {e["event_id"] for e in final_observations}.issubset(safe_ids)
    final_by_id={e["observation_id"]:e for e in final_observations}
    other_forecasts=member(mm,"forecasts")
    from collections import Counter
    reference_inventory={"rows":len(other_forecasts),"models":dict(Counter(x['model_name']+'|'+x['model_version'] for x in other_forecasts)),
       "v18_rows":sum('V18' in x['model_name'].upper() for x in other_forecasts),
       "comparison_status":"Only separately versioned AISP ensemble probability forecasts are present; identical input/horizon compatibility with saved V18 has not been established. No comparator fit or correction was performed."}
    write("other-saved-forecast-inventory.json",reference_inventory)
    scored=[]; flat=[]
    for r in records:
        e=event_map.get(r["game_id"])
        if e is None:
            r["outcome_status"]="NO_EVENT_IN_LOCAL_EXPORT"; continue
        assert stamp(e["event_start"])==stamp(r["scheduled_start"])
        if e["event_status"] != "FINAL" or e["home_score"] is None or e["away_score"] is None or not e.get("outcome_available_at"):
            r["outcome_status"]="NO_PROVENANCED_FINAL"; continue
        assert e["home_team_abbreviation"]==r["home_team"] and e["away_team_abbreviation"]==r["away_team"]
        h,a=int(e["home_score"]),int(e["away_score"])
        assert h!=a and h>=0 and a>=0
        assert stamp(e["outcome_available_at"])>stamp(r["scheduled_start"])
        o=final_by_id[e["outcome_observation_id"]]
        assert o["event_id"]==r["game_id"] and o["status"].upper()=="FINAL"
        assert str(o["source_record_id"])==r["mlbam_game_pk"]
        assert o["home_score"]==h and o["away_score"]==a and o["source"]==e["outcome_source"]
        assert max(stamp(o[k]) for k in ("observed_at","available_as_of","created_at") if o.get(k))==stamp(e["outcome_available_at"])
        r["outcome_status"]="MATCHED_STORED_FINAL_OBSERVATION_CANONICAL_SCORE"
        p=r["home_probability"]; y=int(h>a)
        scores={name:marginal(distributions[r["forecast_sha256"]][name],obs) for name,obs in
                (("homeRuns",h),("awayRuns",a),("homeMinusAwayRuns",h-a),("totalRuns",h+a))}
        row={**r,"actual_home_runs":h,"actual_away_runs":a,"observed_home_win":y,
             "winner_log_loss":-float(np.log(max(1e-12,p if y else 1-p))),"winner_brier":float((p-y)**2),
             "outcome_available_at":e["outcome_available_at"],"outcome_source":e["outcome_source"],
             "outcome_observation_id":e["outcome_observation_id"],"outcome_availability_basis":e["outcome_availability_basis"],"scores":scores}
        scored.append(row)
        flat.append({**{k:v for k,v in row.items() if k!="scores"},**{f"{n}_{k}":v for n,s in scores.items() for k,v in s.items()}})
    table("forecast-inventory.csv", records); table("all-version-game-errors.csv",flat); write("scored-games.json",scored)
    groups={}
    for r in scored:
        if r["selected_within_lineage"]: groups.setdefault(r["lineage"],[]).append(r)
    summaries=[]
    for lineage,rs in groups.items():
        summary={"lineage":lineage,"games":len(rs),"dates":sorted({r["game_date"] for r in rs}),
                 "weeks":sorted({stamp(r["scheduled_start"]).strftime('%G-W%V') for r in rs}),
                 "teams":len({r[k] for r in rs for k in ("away_team","home_team")}),
                 "players_in_saved_pregame_lineups":len({p for r in rs for p in r["lineup_players"]}),
                 "mean_home_probability":float(np.mean([r["home_probability"] for r in rs])),
                 "observed_home_win_rate":float(np.mean([r["observed_home_win"] for r in rs])),
                 "winner_log_loss":float(np.mean([r["winner_log_loss"] for r in rs])),
                 "winner_brier":float(np.mean([r["winner_brier"] for r in rs])),
                 "finding_status":"INSUFFICIENT_TEMPORAL_SUPPORT_EXPLORATORY", "timing_status":rs[0]["timing_status"],
                 "compatible_saved_reference":None,"marginals":{}}
        for n in ("homeRuns","awayRuns","homeMinusAwayRuns","totalRuns"):
            errors=np.array([r["scores"][n]["signed_error"] for r in rs]); sds=np.array([r["scores"][n]["sd"] for r in rs])
            sm={"bias":float(errors.mean()),"mae":float(np.abs(errors).mean()),"rmse":float(np.sqrt((errors**2).mean())),
                "signed_error_quantiles":dict(zip(["q05","q25","q50","q75","q95"],map(float,np.quantile(errors,[.05,.25,.5,.75,.95])))),
                "positive_errors":int((errors>0).sum()),"negative_errors":int((errors<0).sum()),
                "absolute_errors_ge_3":int((np.abs(errors)>=3).sum()),"absolute_errors_ge_5":int((np.abs(errors)>=5).sum()),
                "crps":float(np.mean([r["scores"][n]["crps"] for r in rs])),
                "forecast_sd_range":[float(sds.min()),float(sds.max())],
                "zero_probability_observations":sum(r["scores"][n]["zero_probability_observation"] for r in rs)}
            for level in (50,80,90):
                sm[f"coverage_{level}"]=float(np.mean([r["scores"][n][f"covered_{level}"] for r in rs]))
                sm[f"mean_width_{level}"]=float(np.mean([r["scores"][n][f"width_{level}"] for r in rs]))
            if len(rs)>=5:
                rng=np.random.default_rng(91818)
                boot=errors[rng.integers(0,len(rs),(2000,len(rs)))].mean(axis=1)
                sm["game_bootstrap_bias_interval_95"]=list(map(float,np.quantile(boot,[.025,.975])))
                sm["leave_one_game_out_bias_range"]=[float((errors.sum()-errors.max())/(len(errors)-1)),float((errors.sum()-errors.min())/(len(errors)-1))]
            summary["marginals"][n]=sm
        summaries.append(summary)
    write("metrics-by-version.json", summaries)
    daily=[r for r in scored if r["family"]=="mlb-v18-daily-slate" and r["selected_within_lineage"]]
    regime=[]; calibration=[]
    for name,fn in (("all",lambda r:"all"),("date",lambda r:r["game_date"]),
                    ("starter_hands",lambda r:'/'.join(str(x) for x in r["starter_hands"])),
                    ("confidence",lambda r:'<.60' if max(r["home_probability"],1-r["home_probability"])<.6 else '.60-.70' if max(r["home_probability"],1-r["home_probability"])<.7 else '>=.70'),
                    ("lineup_modes",lambda r:'/'.join(str(x) for x in r["lineup_modes"])),
                    ("park",lambda r:str(r["venue"]))):
        for value in sorted({fn(r) for r in daily}):
            rs=[r for r in daily if fn(r)==value]
            regime.append({"slice":name,"value":value,"games":len(rs),"dates":sorted({r["game_date"] for r in rs}),"weeks":len({stamp(r["scheduled_start"]).strftime('%G-W%V') for r in rs}),
              "teams":len({r[k] for r in rs for k in ("away_team","home_team")}),
              "total_bias":float(np.mean([r["scores"]["totalRuns"]["signed_error"] for r in rs])),
              "margin_bias":float(np.mean([r["scores"]["homeMinusAwayRuns"]["signed_error"] for r in rs])),
              "winner_log_loss":float(np.mean([r["winner_log_loss"] for r in rs])),
              "winner_brier":float(np.mean([r["winner_brier"] for r in rs])),
              "observable_pregame":True,"timing_status":"PREGAME_CAPTURE_COMPLETION_TIME_UNVERIFIED_TRAINING_TIMING_UNCERTAIN",
              "finding_status":"INSUFFICIENT_SUPPORT", "reference_comparison":"NONE_SAVED_COMPATIBLE"})
    for lo,hi in ((0,.4),(.4,.5),(.5,.6),(.6,.7),(.7,1.000001)):
        rs=[r for r in daily if lo<=r["home_probability"]<hi]
        if rs: calibration.append({"lower":lo,"upper":min(hi,1),"games":len(rs),"mean_probability":float(np.mean([r["home_probability"] for r in rs])),"observed_frequency":float(np.mean([r["observed_home_win"] for r in rs]))})
    table("regimes.csv",regime);table("winner-calibration.csv",calibration)
    severe={r["game_id"] for metric in ("totalRuns","homeMinusAwayRuns") for r in sorted(daily,key=lambda x:(-x["scores"][metric]["absolute_error"],x["game_date"],x["game_id"]))[:3]}
    good={r["game_id"] for r in sorted(daily,key=lambda x:(sum(x["scores"][m]["absolute_error"] for m in ("homeRuns","awayRuns")),x["game_id"]))[:2]}
    initial_cases=severe|good
    winner_case=sorted(daily,key=lambda r:(-r["winner_log_loss"],r["game_id"]))[0]["game_id"] if daily else None
    median_order=sorted(daily,key=lambda r:(sum(r["scores"][m]["absolute_error"] for m in ("homeRuns","awayRuns")),r["game_id"]))
    median_case=median_order[len(median_order)//2]["game_id"] if median_order else None
    additional_cases={x for x in (winner_case,median_case) if x is not None}
    cases=[]
    for r in daily:
        if r["game_id"] in initial_cases|additional_cases:
            reasons=[]
            if r["game_id"] in severe: reasons.append("SEVERE_BY_DECLARED_TOTAL_OR_MARGIN_METRIC")
            if r["game_id"] in good: reasons.append("SMALLEST_TEAM_RUN_ABSOLUTE_ERROR")
            if r["game_id"] == winner_case: reasons.append("LARGEST_WINNER_LOG_LOSS_ROOT_PROTOCOL")
            if r["game_id"] == median_case: reasons.append("MEDIAN_TEAM_RUN_ABSOLUTE_ERROR_ROOT_PROTOCOL")
            cases.append({**r,"case_selection":";".join(reasons), "initial_casebook_inclusion":r["game_id"] in initial_cases,
                          "additional_inclusion_status":None if r["game_id"] in initial_cases else "ADDITIONAL_PROTOCOL_COMPLIANCE_INCLUSION_AFTER_INITIAL_FINDINGS",
                          "causal_status":"HYPOTHESES_ONLY_NO_POSTGAME_PLAYER_OR_INPUT_ATTRIBUTION",
                          "hypothesis":"Projected lineups, fixed batting order, historical template carry-forward, and anonymous relief mixture are documented limitations shared with successful cases. These game scores alone do not identify which caused the miss."})
    write("casebook.json",cases)
    lines=["# Whole-game casebook", "", "Initial severe/low-error selection was fixed before outcome access. The original seven cases are retained; the largest winner-loss and median-error examples required by the root protocol were added during review after the initial findings. Added rows are labeled. These saved Sept 8 daily forecasts have pregame captures but unverified completion clocks and unresolved training chronology. Stored final game-state observations supply outcomes; the export has no rows in the official-outcomes table. Cases do not establish causes or recurrence.", "", "|Date|Matchup|Case|Predicted away–home|Actual away–home|Total error|Margin error|P(home)|", "|---|---|---|---:|---:|---:|---:|---:|"]
    for r in cases:
        label = 'Severe' if r['game_id'] in severe else 'Successful example' if r['game_id'] in good else 'Added: winner loss' if r['game_id']==winner_case else 'Added: median error'
        lines.append(f"|{r['game_date']}|{r['away_team']}–{r['home_team']}|{label}|{r['away_runs']:.2f}–{r['home_runs']:.2f}|{r['actual_away_runs']}–{r['actual_home_runs']}|{r['scores']['totalRuns']['signed_error']:+.2f}|{r['scores']['homeMinusAwayRuns']['signed_error']:+.2f}|{r['home_probability']:.3f}|")
    lines += ["", "Successful examples are matched to severe examples on game date, fitted PA/transition artifacts, and projected-lineup status for both teams. Their teams and parks differ: they are contextual comparisons, not causal controls.", "", "The JSON companion contains full forecast hashes, paths, final observation IDs, lineup and starter metadata, interval coverage and marginal CRPS. All explanations remain hypotheses. These same input limitations occur in successful cases; no fault is attributed to the PA estimator, calibration, or simulator from aggregate game scores alone."]
    (OUT/"casebook.md").write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Snapshot existing paired scorer; never invoke it or read its raw final query.
    if frozen_manifest and (OUT/"paired-study-existing-receipt.json").exists():
        saved_pair_snapshot=json.loads((OUT/"paired-study-existing-receipt.json").read_text(encoding="utf-8"))
        pair_receipt=read(saved_pair_snapshot["source"]["path"])
    else:
        pp=ROOT/"outputs/mlb-starter-duration-paired-research-v1/monitoring/current.json"
        locator=read(pp); monitor=read(locator["latest"]["path"])
        pair_receipt=read(monitor["scoring"]["path"])
        write("paired-study-existing-receipt.json",{"source":monitor["scoring"],"receipt":pair_receipt,"reused_only":True,"competing_scoring_performed":False})
    plots(daily,calibration)
    summary={"ordinary_forecast_objects":len(records),"unique_ordinary_games":len({r["game_id"] for r in records}),
      "selected_game_version_rows":sum(r["selected_within_lineage"] for r in records),
      "selected_primary_games":sum(r["selected_primary_game"] for r in records),
      "selected_primary_games_with_final":sum(r["selected_primary_game"] for r in scored),
      "no_duplicate_observed_games_pooled":True,
      "unique_games_with_final":len({r["game_id"] for r in scored}),"version_rows_with_final":len(scored),
      "creation_timestamp_qualified_objects":sum(r["created_at"] is not None and r["pregame_candidate"] for r in records),
      "creation_timestamp_qualified_with_final":sum(r["created_at"] is not None and r["selected_within_lineage"] for r in scored),
      "casebook_games":len(cases),"final_source":"Stored final game-state observation matched to canonical score in local immutable Sept10 export; no official final table rows.",
      "final_oot_reads":0,"original_oot_observations":14067,"permanent_removed_observations":230,"sealed_reduced_oot_observations":13837,
      "recurring_weakness_established":False,"recurring_strength_established":False,
      "missing":["Two Sept10 current-pipeline games lack final evidence at export capture; all 15 Sept11 games absent from Sep10 export","Exact completion/publication clocks for Sep8 and prototype forecasts","Saved joint ordinary score populations for joint energy score","Multiple later independent dates/weeks for recurrence and temporal-block uncertainty","Lineage-compatible saved reference whole-game forecasts","Postgame realized lineups/pitching/substitutions for causal case attribution"],
      "paired_completed_games":pair_receipt.get("matchedGames"),"paired_scoring_as_of":pair_receipt.get("scoredAt")}
    write("summary.json",summary)
    validation=[]
    from server.sports_current_statcast.mlb_starter_duration_paired_scoring import empirical_crps
    for r in scored:
        for name,ds in distributions[r["forecast_sha256"]].items():
            # Exactly expand the existing histogram; this does not generate new draws.
            population=np.repeat([x['value'] for x in ds],np.rint(np.array([x['probability'] for x in ds])*5000).astype(int))
            validation.append(abs(empirical_crps(population,r['scores'][name]['observed'])-r['scores'][name]['crps']))
    assert max(validation,default=0)<1e-12
    write("validation.json",{"existing_empirical_crps_reconciliations":len(validation),"max_absolute_difference":max(validation,default=0),"forecast_marginal_normalization_and_saved_means_verified":True,"forecast_and_snapshot_manifest_sha_bytes_verified":len(records),"identity_and_schedule_linkage_verified":len(records),"capture_creation_source_cutoff_order_verified":sum(r["created_at"] is not None for r in records),"primary_selection_unique_games":len(primary),"no_duplicate_observed_games_pooled":True,"original_casebook_cases_preserved":len(initial_cases),"protocol_compliance_additional_cases":len(additional_cases-initial_cases),"final_observation_identity_score_and_timestamp_reconciled":len(scored),"zero_raw_quarantined_outcomes_read":True})
    write("artifact-manifest.json",{"script":str(Path(__file__).relative_to(ROOT)),"script_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"command":r".\.venv\Scripts\python.exe scripts/diagnose_mlb_v18_whole_game_v1.py","replay_policy":"When the manifest exists, its ordinary input paths and original selection are frozen; original paired scoring receipt is reused. New publisher forecasts require a distinct analysis namespace.","input_files":READS,
      "output_files":{p.name:{"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size} for p in OUT.iterdir() if p.is_file() and p.name!="artifact-manifest.json"},
      "activities":{"provider_calls":0,"database_access":0,"forecast_inference":0,"forecast_simulations":0,"model_fits":0,"model_or_policy_mutations":0}})
    print(json.dumps(summary,indent=2))


def plots(rs,calibration):
    if not rs:return
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(2,2,figsize=(11,8),layout='constrained')
    for ax,name,title in zip(axs.flat,('awayRuns','homeRuns','homeMinusAwayRuns','totalRuns'),('Away runs','Home runs','Home margin','Total runs')):
        vals=np.sort([r['scores'][name]['signed_error'] for r in rs]);ax.step(vals,np.arange(1,len(vals)+1)/len(vals),where='post')
        ax.axvline(0,color='grey',ls='--');ax.set(title=title,xlabel='Predicted minus observed runs',ylabel='Empirical cumulative fraction',ylim=(0,1.03));ax.grid(alpha=.2)
    fig.suptitle(f'Sept 8 saved daily forecasts: {len(rs)} games, one date\nExploratory; capture timestamps do not verify completion or training chronology')
    fig.savefig(OUT/'empirical-error-ecdf.png',dpi=160);plt.close(fig)
    fig,axs=plt.subplots(1,2,figsize=(11,4.6),layout='constrained')
    axs[0].plot([0,1],[0,1],color='gray',ls='--')
    for r in calibration:
        axs[0].scatter(r['mean_probability'],r['observed_frequency'],s=35+25*r['games'])
        axs[0].annotate('n='+str(r['games']),(r['mean_probability'],r['observed_frequency']),xytext=(5,5),textcoords='offset points')
    axs[0].set(xlabel='Mean predicted home win probability',ylabel='Observed home win fraction',xlim=(0,1),ylim=(-.05,1.1),title='Descriptive probability bands')
    for r in rs:axs[1].scatter(r['scores']['totalRuns']['sd'],r['scores']['totalRuns']['absolute_error'])
    axs[1].set(xlabel='Saved total-run distribution SD',ylabel='Absolute total-run error',title='Does saved spread track errors?')
    fig.suptitle(f'{len(rs)} games on one date: no recurring calibration or variance conclusion')
    fig.savefig(OUT/'winner-calibration-and-spread.png',dpi=160);plt.close(fig)


if __name__=='__main__':main()
