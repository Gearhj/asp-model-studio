"""Bounded metadata-only timing inventory; never repairs, fits, or opens OOT.

Reads 2023/24 Retrosheet archives, a result-free schedule authority projection,
and the physically isolated Development cache's identity columns only. Outputs
are immutable evidence of a timing blocker, not a certified timing correction.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_silver import bronze_authority as ba
from server.sports_silver.canonical_ids import canonical_game_id

RAW = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache/raw-development.parquet"
RAW_SHA = "d5fdb7bcbe058f34334483a21b14e83129d19c1727d20eddb469c18668ff3b82"
SCHEDULE = Path("C:/Users/james/asp-data-staging/mlb-current-statcast-bronze-v1/manifests/mlb-stats-api-schedule-authority.json")
SCHEDULE_SHA = "44c43a48dda5895dcc19417a1c51b18ccdaed9dd83b3c1b8d50826e42be69c4d"
TRAIN_ENDS = ("2023-10-01", "2024-07-06", "2025-04-15", "2025-07-27", "2026-05-01")
OUT = ROOT / "outputs/mlb-v19-current-state-specialists-v1/timing-blocker/sha256"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def iso(value):
    return value[:4] + "-" + value[4:6] + "-" + value[6:8]


def main():
    assert sha(RAW) == RAW_SHA and sha(SCHEDULE) == SCHEDULE_SHA
    columns = ["canonicalGameId", "game_id", "game_date", "foldNumber"]
    frame = pd.read_parquet(RAW, columns=columns)
    assert frame.game_date.astype(str).between("2023-03-30", "2026-08-06").all()
    manifest = ba.verify_bronze_manifest()
    known, unresolved, sources, comments = [], [], [], {}
    parts = [p for p in ba.partitions(manifest, source="retrosheet") if p.year in (2023, 2024)]
    for part in parts:
        path = part.absolute_path(ba.DEFAULT_BRONZE_ROOT)
        assert sha(path) == part.file_sha256
        sources.append({"path": str(path), "sha256": part.file_sha256, "bytes": path.stat().st_size})
        with zipfile.ZipFile(path) as archive:
            if "/game-logs/" in part.relative_path:
                member = f"gl{part.year}.txt"
                for line, row in enumerate(csv.reader(io.StringIO(archive.read(member).decode("latin1"))), 1):
                    assert len(row) == 161
                    if row[13]:
                        gid = row[6] + row[0] + row[1]
                        completion = row[13].split(",")[0]
                        assert re.fullmatch(r"\d{8}", completion)
                        known.append({"sourceGameId": gid, "gameDate": iso(row[0]),
                                      "completionDateProxy": iso(completion), "authority": "RETROSHEET_GAMELOG_COMPLETION_FIELD_13_ZERO_BASED",
                                      "sourcePath": str(path), "sourceSha256": part.file_sha256,
                                      "member": member, "lineOneBased": line})
            else:
                for member in sorted(n for n in archive.namelist() if n.upper().endswith((".EVA", ".EVN"))):
                    gid = None
                    for line, value in enumerate(archive.read(member).decode("latin1").splitlines(), 1):
                        if value.startswith("id,"):
                            gid = value[3:]
                        if gid and value.startswith('com,"Suspend='):
                            date = value.split("=", 1)[1].split(",")[0]
                            comments[gid] = {"completionDateProxy": iso(date), "sourcePath": str(path),
                                             "sourceSha256": part.file_sha256, "member": member, "lineOneBased": line}
                        if gid and "Game was not completed" in value:
                            unresolved.append({"sourceGameId": gid, "gameDate": iso(gid[3:11]),
                                               "reason": "SUSPENDED_NOT_COMPLETED_RETROSPECTIVE_SCORE_REVERSION_DATE_UNAVAILABLE",
                                               "sourcePath": str(path), "sourceSha256": part.file_sha256,
                                               "member": member, "lineOneBased": line})
    for record in known:
        support = comments.get(record["sourceGameId"])
        assert support and support["completionDateProxy"] == record["completionDateProxy"]
        record["independentEventComment"] = support
    schedule = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    for game in schedule["completedGames"]:
        if not "2025-01-01" <= game["gameDate"] <= "2026-08-06":
            continue
        final = [o for o in game["scheduleObservations"] if o["detailedState"] in ("Final", "Completed Early")]
        dates = sorted({o["scheduleDate"] for o in final})
        assert dates
        if dates[-1] > game["gameDate"]:
            known.append({"sourceGameId": str(game["gamePk"]), "canonicalGameId": canonical_game_id(str(game["gamePk"])),
                          "gameDate": game["gameDate"], "completionDateProxy": dates[-1],
                          "authority": "LATEST_ENUMERATED_FINAL_SCHEDULE_DATE_NOT_OBSERVED_COMPLETION_TIMESTAMP",
                          "sourcePath": str(SCHEDULE), "sourceSha256": SCHEDULE_SHA,
                          "scheduleObservations": final})
    for record in known + unresolved:
        if "canonicalGameId" not in record:
            rows = frame[frame.game_id.eq("retrosheet:game:" + record["sourceGameId"])]
            assert rows.canonicalGameId.nunique() == 1
            record["canonicalGameId"] = rows.canonicalGameId.iloc[0]
        rows = frame[frame.canonicalGameId.eq(record["canonicalGameId"])]
        assert rows.game_date.eq(record["gameDate"]).all() and rows.foldNumber.nunique() == 1
        record["safePaCount"] = len(rows)
        record["originalFoldNumber"] = int(rows.foldNumber.iloc[0])
        record["directOuterTrainingCutoffCrossings"] = [
            i + 1 for i, end in enumerate(TRAIN_ENDS)
            if record["gameDate"] <= end < record.get("completionDateProxy", record["gameDate"])
        ]
    known.sort(key=lambda r: (r["gameDate"], r["sourceGameId"]))
    proposed_mask = pd.Series(False, index=frame.index)
    for record in known:
        proposed_mask |= frame.game_date.between(record["gameDate"], record["completionDateProxy"])
    proposed_mask &= frame.foldNumber.gt(0)
    evidence = {
        "schemaVersion": "MLB_V19_KNOWN_SUSPENDED_GAME_TIMING_BLOCKER_V1",
        "status": "KNOWN_TIMING_DEFECT_CONFIRMED_NOT_EXHAUSTIVE_ADMISSIBILITY_CERTIFICATION",
        "rawDevelopment": {"path": str(RAW), "sha256": RAW_SHA, "columnsRead": columns, "rows": len(frame)},
        "sourceArtifacts": sources + [{"path": str(SCHEDULE), "sha256": SCHEDULE_SHA, "bytes": SCHEDULE.stat().st_size}],
        "knownDelayedGames": known, "unknownFinalizationGames": unresolved,
        "knownDelayedGameCount": len(known), "knownDelayedPaCount": sum(r["safePaCount"] for r in known),
        "unresolvedFinalizationPaCount": sum(r["safePaCount"] for r in unresolved),
        "outerTrainingEndDates": list(TRAIN_ENDS),
        "proposedKnownIntervalMaskOnly": {
            "status": "NOT_APPLIED_NOT_AN_ADMISSIBILITY_CERTIFICATE", "dateEndpoints": "INCLUSIVE_SUSPENSION_AND_COMPLETION",
            "validationRows": int(proposed_mask.sum()), "validationGames": int(frame.loc[proposed_mask, "canonicalGameId"].nunique()),
            "validationRowsByFold": {str(k): int(v) for k, v in frame.loc[proposed_mask].groupby("foldNumber").size().items()},
        },
        "narrowConclusion": {
            "knownBosCutoffDefectRepairableFromLocalMetadata": True,
            "entireOriginalRegisteredComparisonRestoredByMaskOnly": False,
            "exhaustiveSourceAvailabilityContractEstablished": False,
            "frozenV18ExactNumericalReproductionRemainsEvidenceOfNumericalReproductionOnly": True,
            "recommendation": "STOP_COMPARATIVE_SELECTION_PRESERVE_ATTEMPTS_AND_REPAIR_SOURCE_AVAILABILITY_BEFORE_ANY_NEW_FITS",
            "missingProof": [
                "The 2026 safe metadata projection does not retain resumeDate/resumedFrom; no certificate establishes that latest enumerated Final listing exhaustively captures every late completion.",
                "Retrospectively retrieved completion dates are not historical publication/knowledge timestamps; NYN202309280 score reversion has no locally established finalization date in inspected evidence.",
                "Frozen last100/last250 and previous-game context features were composed by original game date; excluding validation dates alone does not rebuild or certify their source ordering and availability lineage.",
                "Delaying fold2 to Aug27 creates a new post-availability frozen-model sensitivity, not the accepted July6-trained chronological experiment; no modified-fold comparison was executed.",
            ],
        },
        "bounds": {"newFits": 0, "candidateMetricsRead": 0, "providerCalls": 0, "ootPayloadBytesRead": 0,
                   "mixed2026RawScheduleRead": False, "historicalArtifactsModified": False, "aispActivity": False},
    }
    data = canonical_json_bytes(evidence)
    digest = hashlib.sha256(data).hexdigest()
    path = OUT / digest / "timing-evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data
    else:
        with path.open("xb") as stream:
            stream.write(data)
    assert sha(path) == digest
    print(json.dumps({"path": str(path), "sha256": digest, "knownGames": len(known),
                      "knownPa": evidence["knownDelayedPaCount"], "unknownPa": evidence["unresolvedFinalizationPaCount"],
                      "proposedMask": evidence["proposedKnownIntervalMaskOnly"]}, indent=2))


if __name__ == "__main__":
    main()
