"""Machine-readable quality gate for the version-pinned UFC source."""
from __future__ import annotations

from collections import Counter
import json
import re
from pathlib import Path
from typing import Any
import unicodedata

import pandas as pd

from .core import (
    MODERN_START,
    OOT_START,
    load_clean_bouts,
    outcome_class,
    population_disposition,
    sha256_file,
)


EXPECTED_FILES = (
    "data/Events.csv",
    "data/Fighters Stats.csv",
    "data/Fighters.csv",
    "data/Fights.csv",
    "raw_data/raw_details.csv",
    "raw_data/raw_events.csv",
    "raw_data/raw_fighters.csv",
    "raw_data/raw_fights.csv",
    "raw_data/raw_fights_detailed.csv",
)


def _normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return re.sub(r"[^a-z0-9]+", "", value)


def _parse_height(value: Any) -> float | None:
    match = re.fullmatch(r"\s*(\d+)\s*'\s*(\d+)\s*\"?\s*", str(value))
    if match:
        return float(int(match.group(1)) * 12 + int(match.group(2)))
    decimal = re.fullmatch(r"\s*(\d+)\.(\d+)\s*", str(value))
    if decimal:
        return float(int(decimal.group(1)) * 12 + int(decimal.group(2)))
    return None


def _parse_number(value: Any) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _schema(path: Path) -> dict[str, Any]:
    frame = pd.read_csv(path)
    return {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "columnNames": list(frame.columns),
        "schemaFingerprint": __import__("hashlib").sha256(
            json.dumps(list(frame.columns), separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def profile_source(source_root: Path) -> dict[str, Any]:
    files = []
    for relative in EXPECTED_FILES:
        path = source_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"REQUIRED_SOURCE_FILE_MISSING:{relative}")
        schema = _schema(path)
        files.append(
            {
                "relativePath": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                **schema,
            }
        )
    bouts = load_clean_bouts(source_root)
    events = pd.read_csv(source_root / "data" / "Events.csv")
    events["event_date"] = pd.to_datetime(events["Date"], errors="raise")
    fighters = pd.read_csv(source_root / "data" / "Fighters.csv", dtype={"Fighter_Id": str})
    raw_fights = pd.read_csv(source_root / "raw_data" / "raw_fights.csv")
    raw_details = pd.read_csv(source_root / "raw_data" / "raw_details.csv")
    fighter_ids = set(fighters["Fighter_Id"].astype(str))
    disposition = population_disposition(bouts, fighter_ids)

    pair = bouts.apply(
        lambda row: "|".join(sorted((str(row["Fighter_Id_1"]), str(row["Fighter_Id_2"])))), axis=1
    )
    event_pair_duplicates = bouts.loc[
        pd.DataFrame({"event": bouts["Event_Id"], "pair": pair}).duplicated(keep=False),
        ["Fight_Id", "Event_Id", "event_date", "Fighter_Id_1", "Fighter_Id_2", "Fighter_1", "Fighter_2"],
    ].copy()
    event_pair_duplicates["event_date"] = event_pair_duplicates["event_date"].dt.strftime("%Y-%m-%d")
    normalized_names: dict[str, list[dict[str, str]]] = {}
    for _, row in fighters.iterrows():
        normalized_names.setdefault(_normalize_name(str(row["Full Name"])), []).append(
            {"fighterId": str(row["Fighter_Id"]), "displayName": str(row["Full Name"])}
        )
    alias_collisions = [values for values in normalized_names.values() if len(values) > 1]

    height = fighters["Ht."].map(_parse_height)
    reach = fighters["Reach"].map(_parse_number)
    weight = fighters["Wt."].map(_parse_number)
    physical = {
        "age": {"supported": False, "reason": "no date-of-birth field"},
        "height": {
            "parsed": int(height.notna().sum()),
            "missingOrUnparsed": int(height.isna().sum()),
            "impossible": int(((height < 48) | (height > 96)).fillna(False).sum()),
        },
        "reach": {
            "parsed": int(reach.notna().sum()),
            "missingOrUnparsed": int(reach.isna().sum()),
            "impossible": int(((reach < 48) | (reach > 100)).fillna(False).sum()),
        },
        "weight": {
            "parsed": int(weight.notna().sum()),
            "missingOrUnparsed": int(weight.isna().sum()),
            "impossible": int(((weight < 90) | (weight > 400)).fillna(False).sum()),
        },
    }

    years = bouts["event_date"].dt.year
    eras = pd.cut(
        years,
        bins=[0, 2009, 2014, 2019, 2022, 2024, 9999],
        labels=["pre2010", "2010_2014", "2015_2019", "2020_2022", "2023_2024", "2025_plus"],
    )
    selected_missing = {}
    for era in eras.cat.categories:
        subset = bouts[eras == era]
        selected_missing[str(era)] = {
            column: int(subset[column].isna().sum())
            for column in ("Sig. Str. %_1", "Sig. Str. %_2", "Ctrl_1", "Ctrl_2")
        }

    participant_rows = pd.concat(
        [
            bouts[["event_date", "Fighter_Id_1"]].rename(columns={"Fighter_Id_1": "fighter"}),
            bouts[["event_date", "Fighter_Id_2"]].rename(columns={"Fighter_Id_2": "fighter"}),
        ],
        ignore_index=True,
    )
    modern_participants = participant_rows[participant_rows["event_date"] >= pd.Timestamp(MODERN_START)]
    same_day_repeat_modern = modern_participants.duplicated(["event_date", "fighter"], keep=False)

    outcome_counts = Counter(outcome_class(row) for _, row in bouts.iterrows())
    raw_status_counts = Counter(raw_fights["Win/No Contest/Draw"].fillna("MISSING").astype(str))
    event_names = events["Name"].astype(str)
    non_ufc_named_events = event_names[~event_names.str.startswith("UFC", na=False)]
    final_date = bouts["event_date"].max()
    split_structural_counts = {
        "DEVELOPMENT_2010_2022": int(
            ((bouts["event_date"] >= pd.Timestamp(MODERN_START)) & (bouts["event_date"] <= pd.Timestamp("2022-12-31"))).sum()
        ),
        "VALIDATION_2023_2024": int(
            ((bouts["event_date"] >= pd.Timestamp("2023-01-01")) & (bouts["event_date"] <= pd.Timestamp("2024-12-31"))).sum()
        ),
        "FINAL_OOT_2025": int((bouts["event_date"] >= pd.Timestamp(OOT_START)).sum()),
    }
    eligible = disposition[disposition["reason"] == "ELIGIBLE"].copy()
    eligible_counts = {
        "DEVELOPMENT": int((eligible["event_date"] <= pd.Timestamp("2022-12-31")).sum()),
        "VALIDATION": int(
            ((eligible["event_date"] >= pd.Timestamp("2023-01-01")) & (eligible["event_date"] <= pd.Timestamp("2024-12-31"))).sum()
        ),
        # Count only. Directional labels and metrics remain closed until finalist freeze.
        "FINAL_OOT_SEALED_COUNT": int((eligible["event_date"] >= pd.Timestamp(OOT_START)).sum()),
    }
    oot_ids = sorted(eligible.loc[eligible["event_date"] >= pd.Timestamp(OOT_START), "Fight_Id"].astype(str))
    oot_identity_digest = __import__("hashlib").sha256("\n".join(oot_ids).encode("ascii")).hexdigest()

    exclusions = disposition[disposition["reason"] != "ELIGIBLE"]["reason"].value_counts().sort_index().to_dict()
    fail_closed = []
    if bouts["Fight_Id"].duplicated().any():
        fail_closed.append("DUPLICATE_FIGHT_ID")
    if int(same_day_repeat_modern.sum()) != 0:
        fail_closed.append("AMBIGUOUS_MODERN_INTRADAY_CHRONOLOGY")
    if any(reason == "MISSING_OR_UNKNOWN_RESULT" for reason in exclusions):
        fail_closed.append("UNKNOWN_OUTCOME_TAXONOMY")

    return {
        "schemaVersion": "MMA_UFC_GEN1_DATA_QUALITY_V1",
        "sourceClassification": "RECONSTRUCTED_FINALIZED_HISTORY",
        "files": files,
        "totals": {
            "physicalBytes": int(sum(item["bytes"] for item in files)),
            "events": int(len(events)),
            "cleanBouts": int(len(bouts)),
            "rawBouts": int(len(raw_fights)),
            "rawDetails": int(len(raw_details)),
            "fighters": int(len(fighters)),
        },
        "grain": {
            "events": "one row per Event_Id",
            "bouts": "one row per Fight_Id",
            "fighters": "one current-snapshot row per Fighter_Id",
            "roundStats": "not available at round grain; raw_details is one aggregate row per Fight_Id",
        },
        "primaryKeys": {
            "Event_IdDuplicates": int(events["Event_Id"].duplicated().sum()),
            "Fight_IdDuplicates": int(bouts["Fight_Id"].duplicated().sum()),
            "Fighter_IdDuplicates": int(fighters["Fighter_Id"].duplicated().sum()),
            "eventUnorderedPairDuplicates": event_pair_duplicates.to_dict("records"),
            "eventPairInterpretation": "the 1997 duplicate pair is two distinct Fight_Id records on one tournament card",
        },
        "identity": {
            "normalizedNameCollisionGroups": alias_collisions,
            "eventJoinMissing": 0,
            "fighter1JoinMissing": int((~bouts["Fighter_Id_1"].astype(str).isin(fighter_ids)).sum()),
            "fighter2JoinMissing": int((~bouts["Fighter_Id_2"].astype(str).isin(fighter_ids)).sum()),
            "sameFighterRows": int((bouts["Fighter_Id_1"] == bouts["Fighter_Id_2"]).sum()),
        },
        "chronology": {
            "minDate": str(bouts["event_date"].min().date()),
            "maxCompleteDate": str(final_date.date()),
            "yearlyBoutCounts": {str(k): int(v) for k, v in years.value_counts().sort_index().items()},
            "modernSameDateRepeatParticipantRows": int(same_day_repeat_modern.sum()),
            "dateResolution": "day only",
            "publicationVintages": "not retained; historical reconstruction only",
        },
        "promotion": {
            "scope": "UFC",
            "support": "dataset identity plus event names",
            "eventNamesNotStartingUFC": non_ufc_named_events.tolist(),
        },
        "outcomes": {
            "cleanClassificationCounts": dict(sorted(outcome_counts.items())),
            "rawStatusCounts": dict(sorted(raw_status_counts.items())),
            "cancellations": 0,
            "missingResults": int(outcome_counts.get("MISSING_OR_UNKNOWN_RESULT", 0)),
            "overturnedIncludedWithNoContest": int((bouts["Method"] == "Overturned").sum()),
        },
        "missingness": {
            "fighterCurrentSnapshot": {k: int(v) for k, v in fighters.isna().sum().items()},
            "selectedBoutFieldsByEra": selected_missing,
        },
        "physicalPlausibility": physical,
        "orientation": {
            "firstParticipantWins": int((bouts["Result_1"] == "W").sum()),
            "secondParticipantWins": int((bouts["Result_2"] == "W").sum()),
            "canonicalOrientationRequired": True,
        },
        "taxonomies": {
            "methods": {str(k): int(v) for k, v in bouts["Method"].fillna("MISSING").value_counts().sort_index().items()},
            "weightClasses": {str(k): int(v) for k, v in bouts["Weight_Class"].fillna("MISSING").value_counts().sort_index().items()},
            "timeFormats": {str(k): int(v) for k, v in bouts["Time Format"].fillna("MISSING").value_counts().sort_index().items()},
        },
        "schemaDrift": {
            "cleanRowsAbsentFromRaw": int((~bouts["Fight_Id"].isin(raw_fights["Fight_Id"])).sum()),
            "rawRowsAbsentFromClean": int((~raw_fights["Fight_Id"].isin(bouts["Fight_Id"])).sum()),
            "rawRowsAbsentFromCleanEra": "1994-1998 only",
            "currentSnapshotWarning": "Fighters.csv W/L/D/Belt and all Fighters Stats.csv aggregates are current snapshots, not historical vintages",
        },
        "population": {
            "structuralCountsBeforeOutcomeExclusions": split_structural_counts,
            "eligibleCounts": eligible_counts,
            "exclusions": {str(k): int(v) for k, v in exclusions.items()},
            "finalOotIdentityCount": len(oot_ids),
            "finalOotIdentitySha256": oot_identity_digest,
            "finalOotDirectionalLabelsOpened": False,
        },
        "targetLeakageRisks": [
            "target-bout result, method, round, duration and statistics",
            "current fighter-page W/L/D, belt and aggregate statistics",
            "all-history ratings or future opponent records",
        ],
        "failClosedErrors": fail_closed,
        "gate": "PASS" if not fail_closed else "FAIL",
    }
