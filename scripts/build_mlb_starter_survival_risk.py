"""Materialize the predeclared 2023/24 starter cohort without fitting a model."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_datasets.consumer import canonical_json_bytes, semantic_manifest_sha
from server.sports_silver import bronze_authority as ba
from server.sports_phase5.game_replay import event_from_row, replay_game
from server.sports_current_statcast.mlb_starter_survival_data import (
    SCHEMA, parse_event_member, align_raw_fd1, start_risks, add_pregame_history,
)

OUT = ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1/duration-data"
FD1_SHA = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
FD1 = Path("C:/Users/james/asp-model-exchange/datasets/mlb-fd1") / ("sha256-"+FD1_SHA)
DECLARATION = ROOT / "docs/MLB_STARTER_SURVIVAL_HIERARCHY_DECLARATION_V1.json"
DECLARATION_SHA = "51b886ecb20137ea7e8ab0ce1abb8601c3f86df0dfe77dae95d07d8ca01bcc9d"
HOLD_SHA = "04547a356104206a904f38dfa2049f9c67ee2d1822ef39d67cae9d585d6fb985"
HOLD = ROOT / f".runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/{HOLD_SHA}.json"
CONTEXT = Path("C:/Users/james/asp-data-staging/mlb-current-statcast-context-gold-v2")
CONTEXT_SHA = "4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e"
COLUMNS = ["game_id", "game_date", "retrosheet_game_id", "play_number", "plate_appearance_id",
           "inning", "top_bottom", "outs_before", "outs_after", "base_mask_before", "base_mask_after",
           "visiting_score_before", "visiting_score_after", "home_score_before", "home_score_after",
           "runs_scored", "batter_id", "pitcher_id", "pa_outcome", "pa_terminal_token", "event_text",
           "regulation_innings", "pbp_quality", "automatic_runner_placement_before", "automatic_runner_base",
           "game_suspended", "resumed_segment", "game_type", "row_checksum", "retrosheet_event_date",
           "suspension_completion_date", "final_available_date"]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ref(path):
    return {"path": str(path.resolve()), "sha256": sha(path), "bytes": path.stat().st_size}


def verify(path, expected, size=None):
    if not path.is_file() or sha(path) != expected or (size is not None and path.stat().st_size != size):
        raise ValueError("Source checksum/byte mismatch: "+str(path))


def parquet_bytes(frame):
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False, compression="zstd")
    return buffer.getvalue()


def frozen_write(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Immutable artifact conflict: "+str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def main():
    verify(DECLARATION, DECLARATION_SHA)
    sources = [ref(DECLARATION), ref(Path(__file__)),
               ref(ROOT / "server/sports_current_statcast/mlb_starter_survival_data.py"),
               ref(ROOT / "server/sports_phase5/game_replay.py")]
    verify(HOLD, HOLD_SHA)
    hold = json.loads(HOLD.read_text(encoding="utf-8"))
    if hold["heldRows"] != 56 or len(hold["heldObservations"]) != 56:
        raise ValueError("Frozen eligibility hold differs")
    sources.append(ref(HOLD))
    wanted = {r["canonicalPaId"]: r for r in hold["heldObservations"] if r["gameDate"] < "2025-01-01"}
    if len(wanted) != 7:
        raise ValueError("2023/24 eligibility scope differs")
    context_path = CONTEXT / f"publications/sha256/{CONTEXT_SHA}/manifest.json"
    verify(context_path, CONTEXT_SHA)
    sources.append(ref(context_path))
    context_manifest = json.loads(context_path.read_text(encoding="utf-8"))
    hold_bridge = []
    for partition in context_manifest["partitions"]:
        if partition["season"] not in (2023, 2024):
            continue
        if not "2023-01-01" <= partition["minimumDate"] <= partition["maximumDate"] <= "2024-12-31":
            raise ValueError("Identity bridge date scope differs")
        path = CONTEXT / partition["relativePath"]
        verify(path, partition["sha256"], partition["byteCount"])
        sources.append(ref(path))
        bridge = pq.ParquetFile(path).read(columns=["canonicalPaId", "canonicalGameId", "plate_appearance_id", "game_date"]).to_pandas()
        for row in bridge[bridge.canonicalPaId.isin(wanted)].to_dict("records"):
            expected = wanted[row["canonicalPaId"]]
            if row["canonicalGameId"] != expected["canonicalGameId"] or row["game_date"] != expected["gameDate"]:
                raise ValueError("Held PA identity/date bridge differs")
            hold_bridge.append(row)
    if len(hold_bridge) != 7 or {r["canonicalPaId"] for r in hold_bridge} != set(wanted):
        raise ValueError("Held PA source bridge incomplete")
    held_source_ids = {r["plate_appearance_id"] for r in hold_bridge}
    manifest_path = FD1 / "sports-dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if semantic_manifest_sha(manifest) != FD1_SHA:
        raise ValueError("FD1 manifest authority mismatch")
    sources.append(ref(manifest_path))
    for artifact in manifest["package_artifacts"]:
        if artifact["logical_uri"] in ("source-rights.json", "attribution.md"):
            path = FD1 / artifact["logical_uri"]
            verify(path, artifact["sha256"], artifact["byte_count"])
            sources.append(ref(path))
    bronze = ba.verify_bronze_manifest()
    sources.append(ref(ba.DEFAULT_BRONZE_ROOT / "manifests/bronze-manifest.json"))
    raw, logs = {}, {}
    for part in ba.partitions(bronze, source="retrosheet"):
        if part.year not in (2023, 2024):
            continue
        path = part.absolute_path(ba.DEFAULT_BRONZE_ROOT)
        verify(path, part.file_sha256)
        sources.append(ref(path))
        with zipfile.ZipFile(path) as archive:
            if "/events/" in part.relative_path:
                for member in sorted(archive.namelist()):
                    if member.upper().endswith((".EVA", ".EVN")):
                        games = parse_event_member(archive.read(member).decode("latin1"), member)
                        if set(raw) & set(games):
                            raise ValueError("Duplicate source games")
                        for game in games.values():
                            game["sourceSha256"] = part.file_sha256
                        raw.update(games)
            elif "/game-logs/" in part.relative_path:
                member = f"gl{part.year}.txt"
                for line, row in enumerate(csv.reader(io.StringIO(archive.read(member).decode("latin1"))), 1):
                    if len(row) != 161:
                        raise ValueError("Gamelog schema differs")
                    gid = row[6]+row[0]+row[1]
                    logs[gid] = {"completion": row[13], "awayScore": int(row[9]), "homeScore": int(row[10]),
                                 "totalOuts": int(row[11]), "sourceSha256": part.file_sha256,
                                 "member": member, "line": line}
    selected = [p for p in manifest["partitions"] if p["family"] == "play_transition" and p["season"] in (2023, 2024)]
    if len(selected) != 15 or any(not ("2023-01-01" <= p["minimum_date"] <= p["maximum_date"] <= "2024-12-31") for p in selected):
        raise ValueError("Unexpected physically separate Development partition scope")
    risks, starts, accounting, timing = [], [], [], []
    seen_games = set()
    for partition in sorted(selected, key=lambda p: (p["season"], p["month"])):
        path = FD1 / partition["package_relative_uri"]
        if not path.resolve().is_relative_to(FD1.resolve()):
            raise ValueError("Unsafe source path")
        verify(path, partition["file_sha256"], partition["byte_count"])
        sources.append(ref(path))
        table = pq.ParquetFile(path).read(columns=COLUMNS)
        if table.num_rows != partition["row_count"]:
            raise ValueError("Partition row count differs")
        groups = {}
        for row in table.to_pylist():
            if not "2023-01-01" <= row["game_date"] <= "2024-12-31":
                raise ValueError("Unexpected payload date")
            groups.setdefault(row["retrosheet_game_id"], []).append(row)
        for gid, events in sorted(groups.items()):
            if gid in seen_games:
                raise ValueError("Game split across source partitions")
            seen_games.add(gid)
            events.sort(key=lambda row: row["play_number"])
            game, log = raw.get(gid), logs.get(gid)
            reason = None
            if game is None or log is None:
                reason = "EXACT_RAW_EVENT_OR_GAMELOG_IDENTITY_MISSING"
            elif game["info"].get("gametype") != "regular" or any(r["game_type"] != "regular" for r in events):
                reason = "NOT_REGULAR_SEASON"
            elif gid == "NYN202309280":
                reason = "REVERTED_UNCOMPLETED_FINALIZATION_UNKNOWN"
            elif log["completion"] or any(r["game_suspended"] or r["resumed_segment"] for r in events):
                reason = "SUSPENDED_RESUMED_WHOLE_GAME_HELD"
            if gid in ("NYN202309280", "BOS202406260"):
                timing.append({"gameId": gid, "partitionSha256": partition["file_sha256"],
                               "sourceSha256": game["sourceSha256"] if game else None,
                               "terminalPaIdentities": [r["plate_appearance_id"] for r in events if r["pa_terminal_token"]],
                               "terminalCountsByInning": dict(Counter(r["inning"] for r in events if r["pa_terminal_token"])),
                               "retrosheetEventDates": sorted(set(r["retrosheet_event_date"] for r in events)),
                               "comments": game["comments"] if game else [],
                               "identityCaveat": "FD1 source PA IDs only; no claim of opaque V18 canonical-PA crosswalk",
                               "gameLog": log})
            replay_status = None
            aligned = None
            if reason is None:
                try:
                    aligned = align_raw_fd1(game, events)
                    replay = replay_game([event_from_row(r) for r in events])
                    replay_status = replay.classification
                    final = events[-1]
                    if replay.classification != "EXACT_REPLAY":
                        reason = "FD1_"+replay.classification
                    elif (int(final["home_score_after"]), int(final["visiting_score_after"])) != (log["homeScore"], log["awayScore"]):
                        reason = "FINAL_SCORE_GAMELOG_MISMATCH"
                    elif sum(int(r["outs_after"])-int(r["outs_before"]) for r in events) != log["totalOuts"]:
                        reason = "PITCHING_OUTS_GAMELOG_MISMATCH"
                except ValueError as error:
                    reason = str(error)
            game_starts = []
            for side in (0, 1):
                if reason is None:
                    risk_rows, summary = start_risks(game, aligned, side, complete=True)
                    risks.extend(risk_rows)
                else:
                    summary = {"startId": "retrosheet:game:"+gid+":"+str(side), "gameId": "retrosheet:game:"+gid,
                               "sourceGameId": gid, "gameDate": events[0]["game_date"], "homePitcher": side,
                               "calendarMonth": int(events[0]["game_date"][5:7]),
                               "pitcherId": game["starters"].get(side) if game else None,
                               "eligible": False, "endpoint": "UNKNOWN", "exclusionReason": reason,
                               "totalBf": None, "totalOuts": None, "midPaChange": False}
                summary["sourcePartitionSha256"] = partition["file_sha256"]
                summary["rawEventArchiveSha256"] = game["sourceSha256"] if game else None
                starts.append(summary)
                game_starts.append(summary)
            accounting.append({"gameId": "retrosheet:game:"+gid, "gameDate": events[0]["game_date"],
                               "sourcePartitionSha256": partition["file_sha256"], "eventCount": len(events),
                               "replayClassification": replay_status, "gameExclusionReason": reason,
                               "eligibleStarts": sum(s["eligible"] for s in game_starts),
                               "startReasons": [s["exclusionReason"] for s in game_starts]})
        print(json.dumps({"partition": str(path.name), "games": len(seen_games), "riskRows": len(risks)}), flush=True)
    # Source-complete accounting includes raw/log games without an FD1 play ledger.
    for gid in sorted((set(raw) | set(logs))-seen_games):
        game = raw.get(gid)
        day = game["info"].get("date", "").replace("/", "-") if game else f"{gid[3:7]}-{gid[7:9]}-{gid[9:11]}"
        accounting.append({"gameId": "retrosheet:game:"+gid, "gameDate": day, "eligibleStarts": 0,
                           "gameExclusionReason": "FD1_EVENT_LEDGER_MISSING", "eventCount": 0})
        for side in (0, 1):
            starts.append({"startId": "retrosheet:game:"+gid+":"+str(side), "gameId": "retrosheet:game:"+gid,
                           "sourceGameId": gid, "gameDate": day, "homePitcher": side,
                           "calendarMonth": int(day[5:7]), "pitcherId": game["starters"].get(side) if game else None,
                           "eligible": False, "endpoint": "UNKNOWN", "exclusionReason": "FD1_EVENT_LEDGER_MISSING",
                           "totalBf": None, "totalOuts": None, "midPaChange": False})
    starts_df, risks_df = pd.DataFrame(starts), pd.DataFrame(risks)
    intersect = risks_df[risks_df.plateAppearanceId.isin(held_source_ids)]
    held_starts = set(intersect.startId)
    for row in hold_bridge:
        matching = intersect[intersect.plateAppearanceId.eq(row["plate_appearance_id"])]
        row["supportedRiskStartIdsExcluded"] = matching.startId.tolist()
        row["disposition"] = "ENTIRE_START_EXCLUDED_BEFORE_HISTORIES" if len(matching) else "NOT_A_PRELIMINARY_SUPPORTED_STARTER_RISK_ROW"
    starts_df.loc[starts_df.startId.isin(held_starts), ["eligible", "endpoint", "exclusionReason"]] = [False, "UNKNOWN", "FROZEN_V18_ELIGIBILITY_HOLD_INTERSECTING_START"]
    risks_df = risks_df[~risks_df.startId.isin(held_starts)].copy()
    if risks_df.plateAppearanceId.isin(held_source_ids).any():
        raise ValueError("Held PA survived risk eligibility")
    # Synchronize the per-game accounting after the outcome-independent hold.
    final_by_game = {gid: group for gid, group in starts_df.groupby("gameId")}
    for game in accounting:
        group = final_by_game[game["gameId"]]
        game["eligibleStarts"] = int(group.eligible.sum())
        game["startReasons"] = [None if pd.isna(v) else v for v in group.exclusionReason]
    starts_df, risks_df = add_pregame_history(starts_df, risks_df)
    for frame in (starts_df, risks_df):
        frame["split"] = frame.gameDate.map(lambda d: "TRAIN" if d < "2024-01-01" else "CALIBRATION" if d <= "2024-06-30" else "TEST")
    starts_df["realizedBf"], starts_df["realizedOuts"] = starts_df.totalBf, starts_df.totalOuts
    starts_df = starts_df.sort_values(["gameDate", "startId"]).reset_index(drop=True)
    risks_df = risks_df.sort_values(["gameDate", "startId", "bf"]).reset_index(drop=True)
    if risks_df.riskId.duplicated().any() or starts_df.startId.duplicated().any():
        raise ValueError("Nonunique output identity")
    eligible = starts_df[starts_df.eligible]
    grouped = risks_df.groupby("startId", sort=False)
    expected = eligible.set_index("startId")
    if not grouped.size().eq(expected.totalBf.reindex(grouped.size().index)).all():
        raise ValueError("Risk count does not reconcile to realized BF")
    if not grouped.tail(1).set_index("startId").endpoint.sort_index().equals(expected.endpoint.sort_index()):
        raise ValueError("Final risk endpoint differs from observed stint endpoint")
    if not grouped.bf.max().eq(grouped.size()).all() or risks_df.bf.min() != 1:
        raise ValueError("Risk BF clock is not contiguous from one")
    counts = {"sourceGames": len(accounting), "sourceStarts": len(starts_df), "eligibleStarts": len(eligible),
              "eligibleGames": int(eligible.gameId.nunique()), "riskRows": len(risks_df),
              "endpointCounts": risks_df.endpoint.value_counts().to_dict(),
              "excludedStartsByReason": starts_df.loc[~starts_df.eligible, "exclusionReason"].value_counts().to_dict(),
              "eligibleStartsBySplit": eligible.split.value_counts().to_dict(),
              "riskRowsBySplit": risks_df.split.value_counts().to_dict(),
              "shortStartsBfLe9Retained": int(eligible.totalBf.le(9).sum()),
              "observedPitchCountSupportedRiskRows": int(risks_df.observedPitches.notna().sum())}
    artifacts = {"risk.parquet": parquet_bytes(risks_df), "starts.parquet": parquet_bytes(starts_df),
                 "game-accounting.json": canonical_json_bytes(accounting), "timing-only-evidence.json": canonical_json_bytes(timing),
                 "frozen-eligibility-hold-reconciliation.json": canonical_json_bytes({"frozenHoldSha256": HOLD_SHA, "originalHeldPaCount": 56,
                     "heldPasWithin2023And2024": 7, "excludedStarts": sorted(held_starts), "identityBridge": hold_bridge,
                     "remaining49OutsideDurationSourceScope": True, "targetValuesReadForBridge": 0})}
    report = {"schemaVersion": SCHEMA, "declaration": sources[0], "sources": sources, "counts": counts,
              "sourceMode": "RETROSPECTIVE_RECONSTRUCTION_NOT_HISTORICAL_PREGAME_VINTAGE",
              "historyAvailability": "Strictly earlier completed calendar dates, excluding all unsupported starts/games; no exact publication timestamps claimed",
              "ordering": "After supported completed PA. Inning-break score remains current after-PA score. Non-PA outs accumulated separately. BF>=1 supported complete-case estimand.",
              "endpointMeaning": {"CONTINUE": "Starter subsequently faces another observed batter opportunity", "REMOVAL": "Replacement/substitution establishes all-cause removal", "GAME_END": "Complete game ends before another starter opportunity", "UNKNOWN": "Unsupported or incomplete observation excluded whole stint"},
              "rights": {"allowedPurpose": "LOCAL_PRIVATE_MODEL_DEVELOPMENT", "attributionRequired": True, "commercialRightsReviewRequired": True,
                         "rawRedistributionAllowed": False, "sourceRightsReference": str(FD1 / "source-rights.json")},
              "limitations": ["Observed physical pitch counts are optional diagnostics, excluded from model feature ceiling. Automatic balls/strikes are not physical pitches; unknown pitch symbols make counts null.",
                              "No elapsed wall-clock timestamps, preannounced restrictions, roster readiness, bullpen availability, manager intentions, or historical publication vintages.",
                              "Current realized short stints do not establish opener role. First-history and missing rest remain missing with explicit flags.",
                              "Zero-BF and non-PA terminal stints lack the supported BF>=1 PA-boundary endpoint and are explicitly excluded.",
                              "Retrospective complete-case observation does not identify optimal pitcher usage or authorize prospective game forecasting."],
              "artifacts": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in artifacts.items()},
              "activity": {"fits": 0, "providerCalls": 0, "finalOotReads": 0, "aispWrites": 0, "productionPublication": False}}
    report_bytes = canonical_json_bytes(report)
    digest = hashlib.sha256(report_bytes).hexdigest()
    bundle = OUT / "sha256" / digest
    for name, data in artifacts.items():
        frozen_write(bundle / name, data)
    frozen_write(bundle / "manifest.json", report_bytes)
    print(json.dumps({"manifest": str(bundle / "manifest.json"), "sha256": digest, "counts": counts}, indent=2), flush=True)


if __name__ == "__main__":
    main()
