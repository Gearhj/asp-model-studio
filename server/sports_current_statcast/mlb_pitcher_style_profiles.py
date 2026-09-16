"""Prior-date pitcher style research derivative of retained Development evidence.

This module does not change the eligibility of Bronze/Silver sources.  It reads
only identity/completion metadata and a fixed pitch-telemetry projection; no PA
result, score, future substitution, or target-start pitch enters a profile.
Historical capture occurred in 2026, so prior-event reconstruction is not a
claim that the archived classifications were published before the old start.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from server.sports_current_statcast.mlb_starter_duration_quarantine import (
    LEDGER, final_oot_eligible_key_mask, quarantine_ledger, reference,
)
from server.sports_silver import bronze_authority as ba
from server.sports_datasets.consumer import canonical_json_bytes

SCHEMA = "MLB_PRIOR_PITCHER_STYLE_PROFILE_V1"
SOURCE_YEARS = (2022, 2023, 2024)
PROFILE_WINDOW_DAYS = 365
MIN_PITCHES = 200
MIN_PRIOR_DATES = 3
MIN_MEASUREMENT_PITCHES = 30
GROUPS = ("FF", "SI", "FC", "SL_ST", "CU_KC", "CH", "FS_FO", "OTHER", "UNKNOWN")
TYPE_GROUP = {"FF": "FF", "FA": "FF", "SI": "SI", "FT": "SI", "FC": "FC",
              "SL": "SL_ST", "ST": "SL_ST", "SV": "SL_ST", "CU": "CU_KC", "KC": "CU_KC",
              "CH": "CH", "FS": "FS_FO", "FO": "FS_FO"}
MEASUREMENTS = {
    "speed_median_mph": ("release_speed", .5), "speed_p90_mph": ("release_speed", .9),
    "pfx_x_median_ft": ("pfx_x", .5), "pfx_z_median_ft": ("pfx_z", .5),
    "release_x_median_ft": ("release_pos_x", .5), "release_z_median_ft": ("release_pos_z", .5),
    "extension_median_ft": ("release_extension", .5),
}
STYLE_FEATURES = ["style_throws_left"] + ["style_" + g + "_" + suffix
    for g in GROUPS for suffix in ("usage", *MEASUREMENTS)]
IDENTITY_COLUMNS = ["game_pk", "game_date", "game_type", "pitcher", "at_bat_number", "pitch_number"]
TELEMETRY_COLUMNS = ["p_throws", "pitch_type", *dict.fromkeys(v[0] for v in MEASUREMENTS.values())]
SILVER_ROOT = Path("C:/Users/james/asp-data-staging/mlb-silver-v1")
PLAYER_MANIFEST = "ab06c88e7d4fa6e78b397c8a4dfbbc2c8a21a51c03f50fd78ee49de232fb0aaf"
GAME_MANIFEST = "69e6e71d47fabca688c93ef351189e1de1a61cbd95995bf2612eddba5dfd4882"


def _verify(path: Path, expected: str, size: int | None = None) -> dict:
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected or (size is not None and path.stat().st_size != size):
        raise ValueError("PROFILE_SOURCE_BYTES_DIFFER: " + str(path))
    return {"path": str(path.resolve()), "sha256": actual, "bytes": path.stat().st_size}


def _silver_identity(root: Path, digest: str, columns: list[str], refs: list[dict]) -> pd.DataFrame:
    directory = root / "objects/sha256" / digest
    manifest_path = directory / "publication-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    # Silver publication's own identifier is a semantic manifest hash. The
    # immutable child has an independent physical checksum and byte count.
    semantic = hashlib.sha256(canonical_json_bytes({k: v for k, v in manifest.items() if k != "manifestSha256"})).hexdigest()
    if (semantic != digest or manifest.get("manifestSha256") != digest or manifest.get("modelEligible") is not False
            or manifest.get("quarantine") != "QUARANTINED"):
        raise ValueError("PROFILE_SILVER_IDENTITY_AUTHORITY_DIFFER")
    refs.append(reference(manifest_path))
    child = manifest["children"]["object.parquet"]
    path = directory / "object.parquet"
    refs.append(_verify(path, child["sha256"], child["bytes"]))
    return pq.ParquetFile(path).read(columns=columns).to_pandas()


def identity_mask(frame: pd.DataFrame, *, permitted_game_pks: set[str]) -> np.ndarray:
    """Whole-game gate, before accessing any pitch-telemetry payload columns."""
    keys = frame.game_pk.astype(str)
    dates = frame.game_date.astype(str).str[:10]
    if keys.isin(("", "nan", "None", "<NA>")).any() or not dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise ValueError("PROFILE_SOURCE_IDENTITY_REQUIRED")
    quarantine = np.asarray(final_oot_eligible_key_mask(keys), dtype=bool)
    return (quarantine & dates.str[:4].isin([str(y) for y in SOURCE_YEARS]).to_numpy()
            & ~dates.between("2026-08-14", "2026-08-27").to_numpy()
            & frame.game_type.eq("R").to_numpy() & keys.isin(permitted_game_pks).to_numpy())


def require_matching_identity(first: pd.DataFrame, second: pd.DataFrame) -> None:
    """Compare every identity value in original row order under named columns.

    pandas.read_csv(usecols=...) keeps source-header order, not usecols order.
    Both projections must therefore use the same declared column order. Row
    order, index, dtypes and values remain exact comparisons.
    """
    if not first[IDENTITY_COLUMNS].equals(second[IDENTITY_COLUMNS]):
        raise ValueError("PROFILE_IDENTITY_CHANGED_BETWEEN_PASSES")


def _warmup_games(bronze: dict, root: Path, refs: list[dict]) -> tuple[set[str], dict]:
    parts = [p for p in bronze["partitions"] if p.get("source") == "retrosheet"
             and p.get("year") == 2022 and "/game-logs/" in p["relativePath"]]
    if len(parts) != 1:
        raise ValueError("PROFILE_2022_COMPLETION_AUTHORITY_REQUIRED")
    part = parts[0]
    path = root / part["relativePath"]
    refs.append(_verify(path, part["fileSha256"], part["fileSizeBytes"]))
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("gl2022.txt")
    expected = part.get("archiveMemberSha256", {}).get("gl2022.txt")
    if expected and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("PROFILE_2022_GAMELOG_MEMBER_DIFFER")
    # Only date, doubleheader number, home-team identity, completion information.
    # Score/outcome columns are never materialized.
    meta = pd.read_csv(io.BytesIO(raw), header=None, usecols=[0, 1, 6, 13], dtype=str, keep_default_na=False)
    if not meta[0].str.fullmatch(r"2022\d{4}").all():
        raise ValueError("PROFILE_2022_GAMELOG_DATE_SCOPE_DIFFER")
    keys = "retrosheet:game:" + meta[6] + meta[0] + meta[1]
    held = keys[meta[13].ne("")].tolist()
    return set(keys[meta[13].eq("")]), {"year": 2022, "games": len(meta), "heldCompletionGames": held,
        "completionRule": "Retrosheet completion information field13 is empty; no suspended/resumed game enters warmup"}


def load_permitted_pitches(*, permitted_prior_game_ids: set[str], target_pitcher_ids: set[str],
                          bronze_root: Path = ba.DEFAULT_BRONZE_ROOT,
                          silver_root: Path = SILVER_ROOT) -> tuple[pd.DataFrame, dict[str, str], dict]:
    """Read fixed 2022–24 telemetry with identity-first, known-completion gates.

    Caller supplies the whole-game supported 2023/24 pool from the corrected
    duration cohort, not merely a list of pitchers or selected favorable starts.
    """
    bronze_root, silver_root = Path(bronze_root), Path(silver_root)
    ledger = quarantine_ledger()
    if len(ledger["games"]) != 9:
        raise ValueError("PROFILE_REQUIRES_ALL_NINE_PERMANENT_EXCLUSIONS")
    bronze = ba.verify_bronze_manifest(bronze_root)
    refs = [reference(bronze_root / "manifests/bronze-manifest.json"), reference(LEDGER)]
    players = _silver_identity(silver_root, PLAYER_MANIFEST,
        ["retrosheetId", "mlbamId", "canonicalPlayerId", "resolutionStatus"], refs)
    players = players[players.resolutionStatus.eq("MATCHED_EXACT")].dropna(subset=["retrosheetId", "mlbamId"])
    players = players[players.retrosheetId.ne("") & players.mlbamId.ne("")]
    players["pitcherId"] = "retrosheet:player:" + players.retrosheetId.astype(str)
    players = players[players.pitcherId.isin(target_pitcher_ids)]
    if players.pitcherId.duplicated().any() or players.mlbamId.duplicated().any():
        raise ValueError("PROFILE_AMBIGUOUS_PLAYER_BRIDGE")
    mapping = dict(zip(players.pitcherId, players.mlbamId.astype(str)))
    games = _silver_identity(silver_root, GAME_MANIFEST,
        ["canonicalGameId", "mlbamGamePk", "gameDate", "retrosheetGameId", "resolutionStatus"], refs)
    games["sourceGameId"] = "retrosheet:game:" + games.retrosheetGameId.fillna("").astype(str)
    games = games[games.resolutionStatus.eq("MATCHED_EXACT")]
    warmup, warmup_receipt = _warmup_games(bronze, bronze_root, refs)
    permitted = set(permitted_prior_game_ids)
    if any(not x.startswith("retrosheet:game:") or x[-9:-5] not in ("2023", "2024") for x in permitted):
        raise ValueError("PROFILE_PRIOR_GAME_SCOPE_NOT_2023_2024")
    games = games[games.sourceGameId.isin(permitted | warmup)]
    if games.sourceGameId.duplicated().any() or games.mlbamGamePk.duplicated().any():
        raise ValueError("PROFILE_AMBIGUOUS_GAME_BRIDGE")
    game_pks = set(games.mlbamGamePk.astype(str))
    if not all(final_oot_eligible_key_mask(game_pks)):
        raise ValueError("PROFILE_PRIOR_POOL_CONTAINS_QUARANTINE")
    parts = [p for p in bronze["partitions"] if p.get("source") == "statcast"
             and p.get("year") in SOURCE_YEARS and p.get("scope") == "regular" and p.get("rowCount", 0)]
    frames, accounting, source_refs = [], [], []
    wanted_mlbam = set(mapping.values())
    for part in sorted(parts, key=lambda p: p["minDate"]):
        if (part["minDate"] != part["maxDate"] or part["minDate"][:4] != str(part["year"])
                or part["status"] != "COMPLETE"):
            raise ValueError("PROFILE_PHYSICAL_DATE_PARTITION_REQUIRED")
        if not set(IDENTITY_COLUMNS + TELEMETRY_COLUMNS).issubset(part["columnNames"]):
            raise ValueError("PROFILE_DECLARED_TELEMETRY_SCHEMA_MISSING")
        path = (bronze_root / part["relativePath"]).resolve()
        if not path.is_relative_to(bronze_root.resolve()):
            raise ValueError("PROFILE_SOURCE_PATH_ESCAPE")
        source_ref = _verify(path, part["fileSha256"], part["fileSizeBytes"])
        source_refs.append({**source_ref, "partitionId": part["partitionId"], "date": part["minDate"],
            "captureAtUtc": part["retrievalUtc"], "recordedAtUtc": part["recordedAtUtc"],
            "schemaFingerprint": part["schemaFingerprint"]})
        identities = pd.read_csv(path, usecols=IDENTITY_COLUMNS, dtype=str, keep_default_na=False)
        if len(identities) != part["rowCount"] or not identities.game_date.eq(part["minDate"]).all():
            raise ValueError("PROFILE_DECLARED_IDENTITY_ROW_SCOPE_DIFFER")
        gate = identity_mask(identities, permitted_game_pks=game_pks)
        gate &= identities.pitcher.isin(wanted_mlbam).to_numpy()
        selected = np.flatnonzero(gate)
        accounting.append({"partitionId": part["partitionId"], "identityRows": len(identities),
                           "selectedPitchRows": len(selected)})
        if not len(selected):
            continue
        # The file is physically date-homogeneous, verified, and all protected
        # game identities have been rejected above before this projection.
        # No result column is requested in either pass.
        frame = pd.read_csv(path, usecols=IDENTITY_COLUMNS + TELEMETRY_COLUMNS, dtype=str, keep_default_na=False)
        require_matching_identity(identities, frame)
        frame = frame.iloc[selected].copy()
        frame["sourceRowIndex"] = selected
        frame["sourcePartitionId"] = part["partitionId"]
        frame["sourceCaptureAtUtc"] = part["retrievalUtc"]
        frames.append(frame)
    pitches = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=IDENTITY_COLUMNS + TELEMETRY_COLUMNS)
    if pitches.duplicated(["game_pk", "at_bat_number", "pitch_number"]).any():
        raise ValueError("PROFILE_DUPLICATE_PITCH_NATURAL_KEY")
    return pitches, mapping, {"sourceRefs": refs, "pitchSourceRefs": source_refs,
        "partitionAccounting": accounting, "warmupCompletion": warmup_receipt,
        "permitted2023_2024GameCount": len(permitted), "matchedPriorGameCount": len(game_pks),
        "pitcherIdentityMappings": mapping, "selectedPitchRows": len(pitches),
        "unmappedPitchers": sorted(target_pitcher_ids - set(mapping))}


def _pitch_group(code: str) -> str:
    return "UNKNOWN" if code in ("", "nan", "None", "<NA>") else TYPE_GROUP.get(code, "OTHER")


def profiles_from_pitches(starts: pd.DataFrame, pitches: pd.DataFrame,
                         pitcher_mapping: dict[str, str]) -> pd.DataFrame:
    """Pure prior-window aggregation, also usable with synthetic fixtures."""
    needed = {"startId", "pitcherId", "gameDate", "gameId"}
    if not needed.issubset(starts) or starts.startId.duplicated().any():
        raise ValueError("PROFILE_TARGET_IDENTITY_REQUIRED")
    if not starts.gameDate.astype(str).str[:4].isin(("2023", "2024")).all():
        raise ValueError("PROFILE_TARGET_OUTSIDE_DECLARED_DEVELOPMENT")
    data = pitches.copy()
    if len(data) and not identity_mask(data, permitted_game_pks=set(data.game_pk.astype(str))).all():
        raise ValueError("PROFILE_UNGATED_SOURCE_DATE_OR_GAME")
    for column in dict.fromkeys(v[0] for v in MEASUREMENTS.values()):
        data[column] = pd.to_numeric(data[column], errors="coerce")
        data.loc[~np.isfinite(data[column]), column] = np.nan
    # Invalid/nonpositive velocity is unsupported telemetry, never an inferred
    # intentional walk; its actual pitch record still belongs in usage counts.
    data.loc[data.release_speed.le(0), "release_speed"] = np.nan
    data["dateOrdinal"] = pd.to_datetime(data.game_date, format="%Y-%m-%d").astype("int64") // 86400000000000
    data["pitchGroup"] = data.pitch_type.astype(str).map(_pitch_group)
    by_pitcher = {str(pid): g.sort_values(["dateOrdinal", "game_pk", "at_bat_number", "pitch_number"])
                  for pid, g in data.groupby("pitcher", sort=False)}
    records = []
    for row in starts[["startId", "pitcherId", "gameDate", "gameId"]].itertuples(index=False):
        rec = {"startId": row.startId, "pitcherId": row.pitcherId, "gameId": row.gameId,
               "gameDate": row.gameDate, **dict.fromkeys(STYLE_FEATURES, np.nan)}
        mlbam = pitcher_mapping.get(row.pitcherId)
        day = pd.Timestamp(row.gameDate).value // 86400000000000
        prior = by_pitcher.get(mlbam)
        if prior is not None:
            prior = prior[(prior.dateOrdinal >= day-PROFILE_WINDOW_DAYS) & (prior.dateOrdinal < day)]
        n = 0 if prior is None else len(prior)
        dates = [] if not n else sorted(prior.game_date.unique())
        hands = [] if not n else sorted(set(prior.p_throws) - {""})
        reasons = []
        if mlbam is None:
            reasons.append("PITCHER_IDENTITY_UNMAPPED")
        if n < MIN_PITCHES:
            reasons.append("FEWER_THAN_200_PRIOR_PITCHES")
        if len(dates) < MIN_PRIOR_DATES:
            reasons.append("FEWER_THAN_3_PRIOR_APPEARANCE_DATES")
        if len(hands) != 1 or hands[0] not in ("L", "R"):
            reasons.append("THROWING_HAND_MISSING_OR_INCONSISTENT")
        rec.update(profileSupported=not reasons, profileUnsupportedReason=";".join(reasons) or None,
            profilePitchCount=n, profilePriorDateCount=len(dates), pitcherMlbamId=mlbam,
            profileEarliestGameDate=dates[0] if dates else None, profileLatestGameDate=dates[-1] if dates else None,
            profileWindowDays=PROFILE_WINDOW_DAYS, profileThrowingHand=hands[0] if len(hands) == 1 else None)
        counts, measurement_support, exact_type_stats = {}, {}, {}
        if n:
            if len(hands) == 1 and hands[0] in ("L", "R"):
                rec["style_throws_left"] = float(hands[0] == "L")
            for group in GROUPS:
                group_rows = prior[prior.pitchGroup.eq(group)]
                counts[group] = len(group_rows)
                rec[f"style_{group}_usage"] = len(group_rows)/n
                for suffix, (source, quantile) in MEASUREMENTS.items():
                    values = group_rows[source].dropna().to_numpy(dtype=float)
                    measurement_support[f"{group}_{suffix}"] = len(values)
                    if len(values) >= MIN_MEASUREMENT_PITCHES:
                        rec[f"style_{group}_{suffix}"] = float(np.quantile(values, quantile, method="linear"))
            for code, group_rows in prior.groupby("pitch_type", dropna=False):
                stats = {"pitchCount": len(group_rows), "usage": len(group_rows)/n, "measurements": {}}
                for suffix, (source, quantile) in MEASUREMENTS.items():
                    values = group_rows[source].dropna().to_numpy(dtype=float)
                    stats["measurements"][suffix] = {"n": len(values), "value": float(np.quantile(values, quantile, method="linear"))
                        if len(values) >= MIN_MEASUREMENT_PITCHES else None}
                exact_type_stats[code or "UNKNOWN"] = stats
            if not np.isclose(sum(rec[f"style_{g}_usage"] for g in GROUPS), 1, atol=1e-12):
                raise ValueError("PROFILE_USAGE_DOES_NOT_RECONCILE")
        rec["profileGroupPitchCountsJson"] = json.dumps(counts, sort_keys=True)
        rec["profileMeasurementSupportJson"] = json.dumps(measurement_support, sort_keys=True)
        rec["profileSourcePitchTypeStatsJson"] = json.dumps(exact_type_stats, sort_keys=True)
        rec["profilePriorGamePksJson"] = json.dumps(sorted(prior.game_pk.unique()) if n else [])
        rec["profileSourcePartitionsJson"] = json.dumps(sorted(prior.sourcePartitionId.unique()) if n and "sourcePartitionId" in prior else [])
        rec["profileLatestCaptureAtUtc"] = max(prior.sourceCaptureAtUtc) if n and "sourceCaptureAtUtc" in prior else None
        records.append(rec)
    return pd.DataFrame(records)


def build_profiles(starts: pd.DataFrame, *, permitted_prior_game_ids: set[str],
                   bronze_root: Path = ba.DEFAULT_BRONZE_ROOT, silver_root: Path = SILVER_ROOT) -> tuple[pd.DataFrame, dict]:
    """Build one governed research derivative; the caller publishes its bytes."""
    pitches, mapping, source = load_permitted_pitches(permitted_prior_game_ids=permitted_prior_game_ids,
        target_pitcher_ids=set(starts.pitcherId), bronze_root=bronze_root, silver_root=silver_root)
    profiles = profiles_from_pitches(starts, pitches, mapping)
    coverage = profiles.profileUnsupportedReason.fillna("SUPPORTED").value_counts().to_dict()
    measurement_coverage = {f: {"finiteSupportedStarts": int(np.isfinite(profiles.loc[profiles.profileSupported, f]).sum()),
        "missingSupportedStarts": int(profiles.loc[profiles.profileSupported, f].isna().sum())} for f in STYLE_FEATURES}
    manifest = {"schemaVersion": SCHEMA, "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "modelEligible": False, "productionAuthority": False, "sourceEligibilityFlagsUnchanged": True,
        "researchPurpose": "Prior-only pitcher-style duration A/B/C Development comparison explicitly requested by James",
        "governance": {
            "bronzeLabel": "QUARANTINED BRONZE SOURCE EVIDENCE; NOT REGISTERED; NOT MODEL-ELIGIBLE; NOT FEATURE-ELIGIBLE; NOT APPROVED FOR TRAINING",
            "interpretation": "Source layer remains quarantined. This is a separately validated research derivative, not direct raw-source fitting or production registration.",
            "sourceRights": ["PUBLIC RESEARCH SOURCE", "ATTRIBUTION REQUIRED", "COMMERCIAL RIGHTS UNCLEAR"],
            "governingPaths": [str(Path(ba.__file__).resolve()), "docs/PHASE_7B0_BRONZE_DATA_LANDING_REPORT.md",
                "docs/PHASE_7B1_FULL_CORPUS_SILVER.md", "server/sports_silver/contracts.py",
                "docs/MLB_STARTER_SURVIVAL_HIERARCHY_DECLARATION_V1.json"],
            "sourceAttribution": "MLB Advanced Media / Baseball Savant; Retrosheet; Chadwick Bureau",
            "rawRedistribution": False, "newProviderRequests": 0},
        "featureNames": STYLE_FEATURES, "groups": list(GROUPS), "sourceTypeGrouping": TYPE_GROUP,
        "units": {"speed": "mph, out-of-hand Statcast", "movementAndRelease": "feet; raw catcher's perspective, no hand sign-flip",
            "usage": "fraction of all prior eligible recorded pitches including unknown types"},
        "windowDays": PROFILE_WINDOW_DAYS, "dateRule": "targetDate-365 <= source gameDate < targetDate; complete prior games only; all same-day excluded",
        "supportRule": {"minimumPitches": MIN_PITCHES, "minimumPriorDates": MIN_PRIOR_DATES,
            "minimumFinitePerMeasurement": MIN_MEASUREMENT_PITCHES, "hand": "one consistent L or R among observed hand values"},
        "uncertifiedHistoricalKnowledgeTime": True,
        "timingQualification": "Retrospective prior-event features from source revisions captured in August2026; original pitch publication/revision clocks unavailable. Not a historical pregame-vintage claim.",
        "measurementChanges": ["2022–24 are after the2020 Hawk-Eye change; no TrackMan/Hawk-Eye pooling",
            "SL/ST/SV share one modeled group because sweeper classification was introduced in2023; exact source codes retained descriptively",
            "2026 plate_x/plate_z changed from front to middle of plate and sz_top/sz_bot changed to ABS definitions; no location/command proxy used",
            "Movement is measured shape, not pitch effectiveness; no great-curve labels or outcome/location features"],
        "references": ["https://baseballsavant.mlb.com/csv-docs", "https://www.mlb.com/glossary/pitch-types/sweeper",
            "https://www.mlb.com/news/2020-statcast-update-includes-pose-tracking-capabilities"],
        "coverageByDisposition": coverage, "measurementCoverage": measurement_coverage,
        "starts": len(profiles), "supportedStarts": int(profiles.profileSupported.sum()),
        "distinctPitchers": int(profiles.pitcherId.nunique()), **source}
    return profiles, manifest
