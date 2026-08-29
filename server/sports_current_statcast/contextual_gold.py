"""Immutable Gold-48 contextual extension (feature engineering only).

The publisher copies the exact current Gold rows and columns, appends a
deterministic team/game context projection, and publishes new content-addressed
objects.  It never imports an estimator, scorer, calibrator, or promoter.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from collections import defaultdict
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_gold.contracts import GOLD_CLASS_ORDER, GOLD_FEATURES
from .contextual_features import (
    CONTEXT_AUTHORITY_VERSION,
    CONTEXT_FEATURES,
    CONTEXT_FEATURE_VERSION,
    EXCLUDED_INTERACTIONS,
    FEATURE_SPECS,
    FUTURE_ABLATION_FAMILIES,
    GAME_CONTEXT_FEATURES,
    HOLIDAY_RULES_VERSION,
    INTERACTION_FEATURES,
    MISSING_FLAG_FEATURES,
    MLB_TEAM_AUTHORITIES,
    ORDERED_GOLD_PLUS_CONTEXT_FEATURES,
    RIVALRY_AUTHORITY_STATUS,
    TEAM_CONTEXT_FEATURES,
    GameContextInput,
    TeamAuthority,
    VenueAuthority,
    build_game_context_rows,
)
from .contextual_sources import ContextSourceBundle, ContextSourceGame, load_context_source_bundle
from .gold import CURRENT_GOLD_DATASET_ID, verify_current_gold
from .pipeline import _load_json, _write_json_atomic


CONTEXT_GOLD_CONTRACT = "MLB_CURRENT_STATCAST_CONTEXT_GOLD_V2"
CONTEXT_GOLD_DATASET_ID = "gold-table:gold_mlb_current_pa_context_v2"
CONTEXT_TEAM_GAME_CONTRACT = "MLB_PREGAME_TEAM_GAME_CONTEXT_V1"
CONTEXT_VERIFICATION_RECEIPT_CONTRACT = "MLB_CONTEXTUAL_GOLD_DEEP_VERIFICATION_RECEIPT_V1"
DEFAULT_CURRENT_GOLD_ROOT = Path(r"C:\Users\james\asp-data-staging\mlb-current-statcast-gold-v1")
DEFAULT_CONTEXT_GOLD_ROOT = Path(r"C:\Users\james\asp-data-staging\mlb-current-statcast-context-gold-v2")
DEFAULT_AUTHORITY_PATH = Path(__file__).with_name("mlb_context_authorities_v1.json")
DEFAULT_RIVALRY_PATH = Path(__file__).resolve().parents[2] / "docs" / "MLB_RIVALRY_MAPPING_PROPOSAL_V1.json"

_CATEGORICAL_CONTEXT = frozenset({
    "game_day_of_week", "season_phase", "holiday_name", "holiday_region", "rivalry_pair",
})
_LINEAGE_FIELDS = (
    "context_source_cutoff", "context_derivation_cutoff_exclusive",
    "batting_prior_game_identity", "fielding_prior_game_identity",
    "batting_previous_venue", "fielding_previous_venue",
    "batting_missing_reason", "fielding_missing_reason",
    "distance_calculation_version", "holiday_calendar_version",
    "rivalry_map_version", "context_feature_version",
)


class ContextualGoldError(RuntimeError):
    """Contextual Gold evidence failed a fixed identity or PIT invariant."""


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parquet_bytes(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    pq.write_table(
        table.replace_schema_metadata(None), sink, compression="zstd", compression_level=9,
        use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6",
        row_group_size=65_536,
    )
    return sink.getvalue().to_pybytes()


def _write_addressed_parquet(root: Path, data: bytes) -> tuple[str, Path]:
    sha = sha256_bytes(data)
    path = Path(root) / "objects" / "sha256" / f"{sha}.parquet"
    if path.is_file():
        if _sha_file(path) != sha:
            raise ContextualGoldError("context object differs from its content address")
        return sha, path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return sha, path


def _load_static_authorities(
    path: Path = DEFAULT_AUTHORITY_PATH,
) -> tuple[dict[str, VenueAuthority], dict[str, TeamAuthority], dict[str, Any]]:
    raw_bytes = Path(path).read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))
    if payload.get("authorityContract") != CONTEXT_AUTHORITY_VERSION:
        raise ContextualGoldError("static context authority contract differs")
    venues: dict[str, VenueAuthority] = {}
    alias_owner: dict[str, str] = {}
    for item in payload.get("venues") or []:
        key = str(item.get("venueKey") or "")
        if not key:
            raise ContextualGoldError("static venue lacks venueKey")
        venue = VenueAuthority(
            venue_id=key,
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            timezone_name=item.get("timeZone"),
            altitude_feet=item.get("altitudeFeet"),
            country=str(item.get("country") or "US"),
            region=str(item.get("region") or "") or None,
        )
        aliases = [key]
        aliases.extend(f"RETROSHEET:{value}" for value in item.get("retrosheetParkIds") or [])
        aliases.extend(f"MLB_STATS_API:{value}" for value in item.get("mlbVenueIds") or [])
        for alias in aliases:
            prior = alias_owner.get(alias)
            if prior is not None and prior != key:
                raise ContextualGoldError(f"venue alias has two authorities: {alias}")
            alias_owner[alias] = key
            venues[alias] = venue
    teams = dict(MLB_TEAM_AUTHORITIES)
    declared_teams = payload.get("teams") or {}
    if set(declared_teams) != set(teams):
        raise ContextualGoldError("static team authority differs from canonical 30-team alignment")
    for team_id, declared in declared_teams.items():
        expected = teams[team_id]
        if (
            str(declared.get("league")) != expected.league
            or str(declared.get("division"))[0] != expected.division[0]
            or declared.get("homeTimeZone") != expected.home_timezone_name
        ):
            raise ContextualGoldError(f"static team authority differs: {team_id}")
    return venues, teams, {
        "authorityContract": payload["authorityContract"],
        "authorityVersion": payload["authorityVersion"],
        "sha256": sha256_bytes(raw_bytes),
        "distanceMethod": payload["distanceMethod"],
        "venueCount": len(payload.get("venues") or []),
        "teamCount": len(teams),
        "path": Path(path).resolve().relative_to(Path(__file__).resolve().parents[2]).as_posix(),
    }


def _load_rivalry_proposal(path: Path = DEFAULT_RIVALRY_PATH) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("status") != RIVALRY_AUTHORITY_STATUS or payload.get("active") is not False:
        raise ContextualGoldError("rivalry proposal must remain inactive and unapproved")
    return {
        "mappingContract": payload.get("mappingContract"),
        "mappingVersion": payload.get("mappingVersion"),
        "status": payload.get("status"),
        "active": False,
        "proposedPairCount": len(payload.get("proposedPairs") or []),
        "sha256": sha256_bytes(raw),
        "path": Path(path).resolve().relative_to(Path(__file__).resolve().parents[2]).as_posix(),
    }


def _legacy_start_utc(
    source: ContextSourceGame, venue: VenueAuthority | None,
) -> datetime | None:
    if source.scheduled_start_utc is not None:
        return source.scheduled_start_utc.astimezone(timezone.utc)
    if not source.start_time_local or venue is None or not venue.timezone_name:
        return None
    normalized = source.start_time_local.replace(" ", "").upper()
    parsed_time: time | None = None
    for pattern in ("%I:%M%p", "%I%p", "%H:%M"):
        try:
            parsed_time = datetime.strptime(normalized, pattern).time()
            break
        except ValueError:
            continue
    if parsed_time is None:
        return None
    local = datetime.combine(source.game_date, parsed_time, tzinfo=ZoneInfo(venue.timezone_name))
    return local.astimezone(timezone.utc)


def _context_inputs(
    bundle: ContextSourceBundle,
    venues: Mapping[str, VenueAuthority],
) -> tuple[list[GameContextInput], dict[str, ContextSourceGame]]:
    season_starts = {
        season: min(game.game_date for game in bundle.games if game.season == season)
        for season in {game.season for game in bundle.games}
    }
    inputs: list[GameContextInput] = []
    sources: dict[str, ContextSourceGame] = {}
    for source in bundle.games:
        if source.canonical_game_id in sources:
            raise ContextualGoldError(f"duplicate context game identity: {source.canonical_game_id}")
        venue = venues.get(source.venue_key)
        start = _legacy_start_utc(source, venue)
        inputs.append(GameContextInput(
            canonical_game_id=source.canonical_game_id,
            game_date=source.game_date,
            home_team_id=source.home_team_id,
            away_team_id=source.away_team_id,
            venue_id=source.venue_key,
            scheduled_start_utc=start,
            # No landed authority has an exact actual end timestamp.  Duration
            # remains a separate prior-game workload fact and is never used to
            # fabricate actual_end_utc.
            actual_end_utc=None,
            duration_minutes=source.duration_minutes,
            innings_played=source.innings_played,
            series_game_number=source.series_game_number,
            games_in_series=source.games_in_series,
            doubleheader_game_number=source.doubleheader_game_number,
            is_home_opener=source.is_home_opener,
            season_start_date=season_starts[source.season],
        ))
        sources[source.canonical_game_id] = source
    inputs.sort(key=lambda game: (game.game_date, game.doubleheader_game_number or 0, game.canonical_game_id))
    return inputs, sources


def _team_context(
    inputs: Sequence[GameContextInput],
    *,
    venues: Mapping[str, VenueAuthority],
    teams: Mapping[str, TeamAuthority],
    sources: Mapping[str, ContextSourceGame],
    distance_version: str,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], int]]:
    by_season: dict[int, list[GameContextInput]] = defaultdict(list)
    source_seasons = {source.canonical_game_id: source.season for source in sources.values()}
    for game in inputs:
        by_season[source_seasons[game.canonical_game_id]].append(game)
    rows: list[dict[str, Any]] = []
    index: dict[tuple[str, str], int] = {}
    input_by_id = {game.canonical_game_id: game for game in inputs}
    for season in sorted(by_season):
        history = by_season[season]
        for game in history:
            away, home = build_game_context_rows(game, history=history, venues=venues, teams=teams)
            for raw in (away, home):
                key = (game.canonical_game_id, str(raw["team_id"]))
                if key in index:
                    raise ContextualGoldError(f"duplicate team-game context: {key}")
                prior_id = str(raw.get("prior_game_id") or "")
                prior_game = input_by_id.get(prior_id)
                source = sources[game.canonical_game_id]
                row = {
                    **raw,
                    "season": season,
                    "game_date": game.game_date.isoformat(),
                    "home_team_id": game.home_team_id,
                    "away_team_id": game.away_team_id,
                    "venue_id": game.venue_id,
                    "previous_venue_id": prior_game.venue_id if prior_game else None,
                    "source_game_id": source.source_game_id,
                    "source_partition_id": source.source_partition_id,
                    "source_sha256": source.source_sha256,
                    "source_cutoff": source.source_cutoff,
                    "derivation_cutoff_exclusive": game.game_date.isoformat(),
                    "distance_calculation_version": distance_version,
                    "holiday_calendar_version": HOLIDAY_RULES_VERSION,
                    "rivalry_map_version": "MLB_RIVALRY_MAPPING_V1_PROPOSED",
                }
                index[key] = len(rows)
                rows.append(row)
    return rows, index


def _context_type(name: str) -> pa.DataType:
    return pa.string() if name in _CATEGORICAL_CONTEXT else pa.float64()


def _team_table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    metadata_fields = (
        "canonical_game_id", "team_id", "opponent_team_id", "season", "game_date",
        "home_team_id", "away_team_id", "venue_id", "previous_venue_id", "prior_game_id",
        "source_game_id", "source_partition_id", "source_sha256", "source_cutoff",
        "derivation_cutoff_exclusive", "distance_calculation_version",
        "holiday_calendar_version", "rivalry_map_version", "context_feature_version",
        "history_cutoff_rule", "rivalry_authority_status", "missing_reason",
    )
    raw_features = (*GAME_CONTEXT_FEATURES, *TEAM_CONTEXT_FEATURES, *INTERACTION_FEATURES, *MISSING_FLAG_FEATURES)
    arrays: list[pa.Array] = []
    fields: list[pa.Field] = []
    for name in metadata_fields:
        values = [
            row.get("missing_reason_category")
            if name == "missing_reason" else row.get(name)
            for row in rows
        ]
        if name == "season":
            arrays.append(pa.array(values, type=pa.int16()))
            fields.append(pa.field(name, pa.int16(), False))
        else:
            arrays.append(pa.array(values, type=pa.string()))
            fields.append(pa.field(name, pa.string(), name not in {"canonical_game_id", "team_id", "season", "game_date"}))
    for name in raw_features:
        values = [row.get(name) for row in rows]
        dtype = _context_type(name)
        arrays.append(pa.array(values, type=dtype))
        fields.append(pa.field(name, dtype, True))
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def _take(table: pa.Table, name: str, indices: Sequence[int]) -> pa.ChunkedArray:
    return table[name].take(pa.array(indices, type=pa.int64()))


def _append_context(
    core: pa.Table,
    *,
    team_table: pa.Table,
    index: Mapping[tuple[str, str], int],
    sources: Mapping[str, ContextSourceGame],
    distance_version: str,
) -> pa.Table:
    required = {"canonicalGameId", "context_top_bottom", "game_date", "datasetRole", *GOLD_FEATURES}
    missing = sorted(required - set(core.column_names))
    if missing:
        raise ContextualGoldError(f"source Gold partition lacks required columns: {missing}")
    games = [str(value) for value in core["canonicalGameId"].to_pylist()]
    top_bottom = [int(value) for value in core["context_top_bottom"].to_pylist()]
    batting_indices: list[int] = []
    fielding_indices: list[int] = []
    home_indices: list[int] = []
    for game_id, half in zip(games, top_bottom):
        source = sources.get(game_id)
        if source is None:
            raise ContextualGoldError(f"Gold game is absent from context source authority: {game_id}")
        batting_team = source.away_team_id if half == 0 else source.home_team_id
        fielding_team = source.home_team_id if half == 0 else source.away_team_id
        try:
            batting_indices.append(index[(game_id, batting_team)])
            fielding_indices.append(index[(game_id, fielding_team)])
            home_indices.append(index[(game_id, source.home_team_id)])
        except KeyError as exc:
            raise ContextualGoldError(f"team-game projection is incomplete: {exc.args[0]}") from exc
    output = core.replace_schema_metadata(None)
    for name in GAME_CONTEXT_FEATURES:
        output = output.append_column(name, _take(team_table, name, home_indices))
    for name in (*TEAM_CONTEXT_FEATURES, *INTERACTION_FEATURES, *MISSING_FLAG_FEATURES):
        output = output.append_column(f"batting_{name}", _take(team_table, name, batting_indices))
    for name in (*TEAM_CONTEXT_FEATURES, *INTERACTION_FEATURES, *MISSING_FLAG_FEATURES):
        output = output.append_column(f"fielding_{name}", _take(team_table, name, fielding_indices))
    lineage = {
        "context_source_cutoff": pa.array([sources[game].source_cutoff for game in games], type=pa.string()),
        "context_derivation_cutoff_exclusive": core["game_date"].cast(pa.string()),
        "batting_prior_game_identity": _take(team_table, "prior_game_id", batting_indices),
        "fielding_prior_game_identity": _take(team_table, "prior_game_id", fielding_indices),
        "batting_previous_venue": _take(team_table, "previous_venue_id", batting_indices),
        "fielding_previous_venue": _take(team_table, "previous_venue_id", fielding_indices),
        "batting_missing_reason": _take(team_table, "missing_reason", batting_indices),
        "fielding_missing_reason": _take(team_table, "missing_reason", fielding_indices),
        "distance_calculation_version": pa.array([distance_version] * core.num_rows, type=pa.string()),
        "holiday_calendar_version": pa.array([HOLIDAY_RULES_VERSION] * core.num_rows, type=pa.string()),
        "rivalry_map_version": pa.array(["MLB_RIVALRY_MAPPING_V1_PROPOSED"] * core.num_rows, type=pa.string()),
        "context_feature_version": pa.array([CONTEXT_FEATURE_VERSION] * core.num_rows, type=pa.string()),
    }
    for name in _LINEAGE_FIELDS:
        output = output.append_column(name, lineage[name])
    expected_order = [*core.column_names, *CONTEXT_FEATURES, *_LINEAGE_FIELDS]
    if output.column_names != expected_order:
        raise ContextualGoldError("context columns are not appended in the exact contract order")
    return output


def _coverage_update(
    totals: dict[str, dict[str, int]], table: pa.Table,
) -> None:
    roles = [str(value) for value in table["datasetRole"].to_pylist()]
    months = [str(value)[:7] for value in table["game_date"].to_pylist()]
    seasons = [str(value) for value in table["season"].to_pylist()]
    for name in ORDERED_GOLD_PLUS_CONTEXT_FEATURES:
        column = table[name]
        valid = pc.invert(pc.is_null(column)).to_pylist()
        item = totals.setdefault(name, defaultdict(int))
        for ok, role, month, season in zip(valid, roles, months, seasons):
            item["rows"] += 1
            item[f"role:{role}:rows"] += 1
            item[f"season:{season}:rows"] += 1
            item[f"month:{month}:rows"] += 1
            if ok:
                item["present"] += 1
                item[f"role:{role}:present"] += 1
                item[f"season:{season}:present"] += 1
                item[f"month:{month}:present"] += 1


def _coverage_manifest(totals: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name in ORDERED_GOLD_PLUS_CONTEXT_FEATURES:
        item = totals[name]
        ratio = lambda present, rows: (float(present) / float(rows) if rows else 0.0)
        role = lambda value: ratio(item.get(f"role:{value}:present", 0), item.get(f"role:{value}:rows", 0))
        output[name] = {
            "overall": ratio(item.get("present", 0), item.get("rows", 0)),
            "development": role("DEVELOPMENT_SELECTION"),
            "finalOot": role("FINAL_OOT"),
            "bySeason": {
                key.split(":")[1]: ratio(item.get(key.replace(":rows", ":present"), 0), value)
                for key, value in sorted(item.items()) if key.startswith("season:") and key.endswith(":rows")
            },
            "byMonth": {
                key.split(":")[1]: ratio(item.get(key.replace(":rows", ":present"), 0), value)
                for key, value in sorted(item.items()) if key.startswith("month:") and key.endswith(":rows")
            },
        }
    return output


def _load_gold_manifest(root: Path, manifest_sha: str | None) -> tuple[str, Path, dict[str, Any]]:
    root = Path(root).resolve()
    verified = verify_current_gold(root, manifest_sha)
    sha = str(verified["manifestSha256"])
    path = root / "publications" / "sha256" / sha / "manifest.json"
    manifest = _load_json(path)
    if manifest.get("datasetId") != CURRENT_GOLD_DATASET_ID:
        raise ContextualGoldError("source Gold dataset identity differs")
    if manifest.get("featureNames") != list(GOLD_FEATURES) or manifest.get("featureCount") != 48:
        raise ContextualGoldError("source Gold-48 contract differs")
    if int(manifest.get("modelsFitted") or 0) != 0 or manifest.get("modelPromoted") is not False:
        raise ContextualGoldError("source Gold model-free status differs")
    return sha, path, manifest


def _prior_manifest(root: Path, manifest_sha: str | None) -> dict[str, Any] | None:
    if manifest_sha is None:
        locator = Path(root) / "current.json"
        if not locator.is_file():
            return None
        manifest_sha = str(_load_json(locator).get("manifestSha256") or "")
    path = Path(root) / "publications" / "sha256" / str(manifest_sha) / "manifest.json"
    if not path.is_file() or _sha_file(path) != manifest_sha:
        raise ContextualGoldError("prior contextual manifest is not content-addressed")
    manifest = _load_json(path)
    if manifest.get("datasetId") != CONTEXT_GOLD_DATASET_ID:
        raise ContextualGoldError("prior contextual dataset identity differs")
    return manifest


def _atomic_current(
    root: Path,
    manifest_sha: str,
    manifest_path: Path,
    receipt_sha: str,
    receipt_path: Path,
) -> None:
    prior: dict[str, Any] = {}
    locator = Path(root) / "current.json"
    if locator.is_file():
        prior = _load_json(locator)
    history = [str(value) for value in prior.get("historicalManifestSha256s") or []]
    old = str(prior.get("manifestSha256") or "")
    if old and old != manifest_sha and old not in history:
        history.append(old)
    _write_json_atomic(locator, {
        "datasetId": CONTEXT_GOLD_DATASET_ID,
        "manifestSha256": manifest_sha,
        "currentManifestSha256": manifest_sha,
        "historicalManifestSha256s": history,
        "manifestRelativePath": manifest_path.resolve().relative_to(Path(root).resolve()).as_posix(),
        "verificationReceiptSha256": receipt_sha,
        "verificationReceiptRelativePath": receipt_path.resolve().relative_to(Path(root).resolve()).as_posix(),
    })


def _receipt_bindings(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Compact immutable identities checked by the Stage 2 read path."""

    return {
        "sourceGoldManifestSha256": str((manifest.get("sourceGold") or {}).get("manifestSha256") or ""),
        "sourceAuthoritiesSha256": sha256_bytes(canonical_json_bytes(manifest.get("sourceAuthorities") or {})),
        "rivalryMappingSha256": sha256_bytes(canonical_json_bytes(manifest.get("rivalryMapping") or {})),
        "partitionBindingsSha256": sha256_bytes(canonical_json_bytes(manifest.get("partitions") or [])),
        "teamGameContextSha256": str((manifest.get("teamGameContext") or {}).get("sha256") or ""),
        "featureContractSha256": sha256_bytes(canonical_json_bytes({
            "coreFeatureNames": manifest.get("coreFeatureNames"),
            "contextFeatureNames": manifest.get("contextFeatureNames"),
            "featureNames": manifest.get("featureNames"),
            "featureSpecs": manifest.get("featureSpecs"),
            "featureFamilies": manifest.get("featureFamilies"),
            "interactions": manifest.get("interactions"),
        })),
    }


def _write_verification_receipt(
    root: Path,
    manifest_sha: str,
    manifest: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> tuple[str, Path]:
    receipt = {
        "receiptContract": CONTEXT_VERIFICATION_RECEIPT_CONTRACT,
        "datasetId": CONTEXT_GOLD_DATASET_ID,
        "manifestSha256": manifest_sha,
        **_receipt_bindings(manifest),
        "verified": verification.get("verified") is True,
        "rowCount": int(verification.get("rowCount") or -1),
        "teamGameRowCount": int(verification.get("teamGameRowCount") or -1),
        "coreFeatureCount": int(verification.get("coreFeatureCount") or -1),
        "addedFeatureCount": int(verification.get("addedFeatureCount") or -1),
        "totalFeatureCount": int(verification.get("totalFeatureCount") or -1),
        "modelsFitted": int(verification.get("modelsFitted") or 0),
    }
    if not receipt["verified"]:
        raise ContextualGoldError("deep verification did not authorize a receipt")
    body = canonical_json_bytes(receipt)
    sha = sha256_bytes(body)
    path = Path(root) / "verification-receipts" / "sha256" / sha / "receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() != body:
        raise ContextualGoldError("verification receipt differs at its content address")
    if not path.is_file():
        path.write_bytes(body)
    return sha, path


def build_contextual_gold(
    *,
    current_gold_root: Path = DEFAULT_CURRENT_GOLD_ROOT,
    output_root: Path = DEFAULT_CONTEXT_GOLD_ROOT,
    current_gold_manifest_sha256: str | None = None,
    source_bundle: ContextSourceBundle | None = None,
    recompute_dates: Sequence[str] | None = None,
    prior_manifest_sha256: str | None = None,
    publish_current: bool = True,
) -> dict[str, Any]:
    """Build the immutable contextual extension with zero model operations."""

    gold_sha, _gold_path, gold = _load_gold_manifest(Path(current_gold_root), current_gold_manifest_sha256)
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    authorities_path = DEFAULT_AUTHORITY_PATH
    venues, teams, static_authority = _load_static_authorities(authorities_path)
    rivalry = _load_rivalry_proposal()
    bundle = source_bundle or load_context_source_bundle()
    inputs, sources = _context_inputs(bundle, venues)
    team_rows, team_index = _team_context(
        inputs, venues=venues, teams=teams, sources=sources,
        distance_version=str(static_authority["distanceMethod"]),
    )
    team_table = _team_table(team_rows)
    team_bytes = _parquet_bytes(team_table)
    team_sha, team_path = _write_addressed_parquet(output, team_bytes)

    normalized_dates = sorted({str(value) for value in (recompute_dates or ())})
    affected_seasons = {int(value[:4]) for value in normalized_dates if len(value) >= 4}
    prior = _prior_manifest(output, prior_manifest_sha256) if (prior_manifest_sha256 or normalized_dates) else None
    prior_by_season = {
        int(item["season"]): item for item in (prior or {}).get("partitions") or []
    }
    partitions: list[dict[str, Any]] = []
    coverage_totals: dict[str, dict[str, int]] = {}
    source_by_season = {int(item["season"]): item for item in gold.get("partitions") or []}
    if set(source_by_season) != {2023, 2024, 2025, 2026}:
        raise ContextualGoldError("source Gold seasons differ from 2023--2026")
    for season in (2023, 2024, 2025, 2026):
        source_partition = source_by_season[season]
        source_path = Path(current_gold_root) / str(source_partition["relativePath"])
        if not source_path.is_file() or _sha_file(source_path) != source_partition["sha256"]:
            raise ContextualGoldError("source Gold partition SHA differs")
        reused = prior_by_season.get(season)
        can_reuse = bool(
            prior is not None and season not in affected_seasons and reused
            and reused.get("sourceGoldPartitionSha256") == source_partition["sha256"]
        )
        if can_reuse:
            object_path = output / str(reused["relativePath"])
            if not object_path.is_file() or _sha_file(object_path) != reused["sha256"]:
                raise ContextualGoldError("reused contextual partition SHA differs")
            table = pq.read_table(object_path)
            partitions.append(dict(reused))
        else:
            core = pq.read_table(source_path)
            table = _append_context(
                core, team_table=team_table, index=team_index, sources=sources,
                distance_version=str(static_authority["distanceMethod"]),
            )
            data = _parquet_bytes(table)
            sha, object_path = _write_addressed_parquet(output, data)
            dates = [str(value) for value in table["game_date"].to_pylist()]
            partitions.append({
                "season": season,
                "rowCount": table.num_rows,
                "minimumDate": min(dates),
                "maximumDate": max(dates),
                "sha256": sha,
                "byteCount": len(data),
                "relativePath": object_path.relative_to(output).as_posix(),
                "sourceGoldPartitionSha256": source_partition["sha256"],
            })
        _coverage_update(coverage_totals, table)
    coverage = _coverage_manifest(coverage_totals)
    manifest = {
        "manifestContract": CONTEXT_GOLD_CONTRACT,
        "manifestVersion": 2,
        "datasetId": CONTEXT_GOLD_DATASET_ID,
        "status": "RESEARCH_ONLY_FEATURE_EVIDENCE",
        "modelsFitted": 0,
        "modelsScored": 0,
        "modelsCalibrated": 0,
        "modelPromoted": False,
        "rowCount": sum(int(item["rowCount"]) for item in partitions),
        "coreFeatureCount": 48,
        "addedFeatureCount": len(CONTEXT_FEATURES),
        "totalFeatureCount": len(ORDERED_GOLD_PLUS_CONTEXT_FEATURES),
        "coreFeatureNames": list(GOLD_FEATURES),
        "contextFeatureNames": list(CONTEXT_FEATURES),
        "featureNames": list(ORDERED_GOLD_PLUS_CONTEXT_FEATURES),
        "classOrder": list(GOLD_CLASS_ORDER),
        "sourceGold": {
            "datasetId": CURRENT_GOLD_DATASET_ID,
            "manifestSha256": gold_sha,
            "rowCount": int(gold["rowCount"]),
            "featureCount": int(gold["featureCount"]),
            "dateCoverage": gold["dateCoverage"],
            "temporalContract": gold["temporalContract"],
            "partitionSha256s": [item["sha256"] for item in gold["partitions"]],
        },
        "sourceAuthorities": {**dict(bundle.authorities), "staticVenueTeam": static_authority},
        "teamGameContext": {
            "contract": CONTEXT_TEAM_GAME_CONTRACT,
            "rowCount": team_table.num_rows,
            "sha256": team_sha,
            "byteCount": len(team_bytes),
            "relativePath": team_path.relative_to(output).as_posix(),
            "naturalKey": ["canonical_game_id", "team_id"],
        },
        "featureSpecs": {name: dict(FEATURE_SPECS.get(name) or {}) for name in CONTEXT_FEATURES},
        "featureFamilies": {name: list(features) for name, features in FUTURE_ABLATION_FAMILIES.items()},
        "featureCoverage": coverage,
        "interactions": [
            {
                "name": name,
                "status": "INACTIVE_PENDING_RIVALRY_APPROVAL" if name == "home_x_rivalry" else "MATERIALIZED",
                "reason": "Explicit bounded interaction; future chronological ablation candidate.",
            }
            for name in INTERACTION_FEATURES
        ] + [
            {"name": name, "status": "EXCLUDED_SOURCE_UNAVAILABLE", "reason": reason}
            for name, reason in EXCLUDED_INTERACTIONS.items()
        ],
        "rivalryMapping": rivalry,
        "pointInTime": {
            "historyCutoff": "source.game_date < target.game_date; same-date games including doubleheaders are excluded",
            "targetScheduleFacts": "venue/start/series facts only from the exact landed game identity",
            "priorResults": "prior innings/duration only after a strictly earlier completed date",
            "actualEndTimestamp": "never inferred; null when no authoritative timestamp exists",
            "travelOrigin": "previous eligible game venue; never nominal home city",
            "finalOotTreatment": "features may use earlier completed history; no OOT outcome was used for feature choice",
        },
        "circadianFormula": {
            "score": "abs(time_zone_change_hours) + local_body_clock_offset_hours + early_start_after_eastward_travel + late_start_after_westward_travel + morning_body_clock_game + max(0, 24 - hours_since_previous_game_start) / 24",
            "recoveryBasis": "scheduled start-to-start hours; exact prior end time is not fabricated",
            "directionBasis": "previous and target venue UTC offsets evaluated at target first pitch, avoiding false DST travel",
        },
        "missingnessPolicy": {
            "dropRows": False,
            "targetInformedImputation": False,
            "futureTreatment": "training-fold-only neutral or hierarchical priors",
        },
        "coverage": coverage,
        "partitions": partitions,
        "recomputedTargetDates": normalized_dates,
        "limitations": [
            "Travel, circadian, holiday, and rivalry variables are measurable hypotheses, not established causes.",
            "No exact historical game-end timestamp authority exists; hours-since-previous-end remains null and explicitly flagged.",
            "Venue altitude is not in the reviewed V1 authority; altitude-change remains null and explicitly flagged.",
            "Historical schedule snapshots do not carry original pregame knowledge timestamps; deterministic schedule facts are bound to landed source bytes.",
            "Rivalry pairs are proposed but unapproved; subjective rivalry fields and interactions remain null/inactive.",
            "No model was fitted, scored, calibrated, selected, or promoted.",
        ],
    }
    if manifest["rowCount"] != int(gold["rowCount"]):
        raise ContextualGoldError("contextual row count differs from source Gold")
    body = canonical_json_bytes(manifest)
    manifest_sha = sha256_bytes(body)
    manifest_path = output / "publications" / "sha256" / manifest_sha / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.is_file() and manifest_path.read_bytes() != body:
        raise ContextualGoldError("contextual manifest differs at its content address")
    if not manifest_path.is_file():
        manifest_path.write_bytes(body)
    verification = verify_contextual_gold(
        output,
        manifest_sha,
        current_gold_root=Path(current_gold_root),
        _source_bundle=bundle,
    )
    receipt_sha, receipt_path = _write_verification_receipt(
        output, manifest_sha, manifest, verification
    )
    if publish_current:
        _atomic_current(
            output, manifest_sha, manifest_path, receipt_sha, receipt_path
        )
    return {
        **manifest,
        "manifestSha256": manifest_sha,
        "manifestPath": str(manifest_path),
        "verificationReceiptSha256": receipt_sha,
        "verificationReceiptPath": str(receipt_path),
    }


def _tables_equal(left: pa.Table, right: pa.Table) -> bool:
    return left.combine_chunks().replace_schema_metadata(None).equals(
        right.combine_chunks().replace_schema_metadata(None), check_metadata=False
    )


def verify_contextual_gold(
    output_root: Path = DEFAULT_CONTEXT_GOLD_ROOT,
    manifest_sha256: str | None = None,
    *,
    current_gold_root: Path = DEFAULT_CURRENT_GOLD_ROOT,
    _source_bundle: ContextSourceBundle | None = None,
) -> dict[str, Any]:
    root = Path(output_root).resolve()
    if manifest_sha256 is None:
        locator = _load_json(root / "current.json")
        manifest_sha256 = str(locator.get("manifestSha256") or "")
    manifest_path = root / "publications" / "sha256" / str(manifest_sha256) / "manifest.json"
    if not manifest_path.is_file() or _sha_file(manifest_path) != manifest_sha256:
        raise ContextualGoldError("contextual manifest is not content-addressed")
    manifest = _load_json(manifest_path)
    expected_feature_specs = {
        name: dict(FEATURE_SPECS.get(name) or {}) for name in CONTEXT_FEATURES
    }
    expected_families = {
        name: list(features) for name, features in FUTURE_ABLATION_FAMILIES.items()
    }
    expected_interactions = [
        {
            "name": name,
            "status": (
                "INACTIVE_PENDING_RIVALRY_APPROVAL"
                if name == "home_x_rivalry"
                else "MATERIALIZED"
            ),
            "reason": "Explicit bounded interaction; future chronological ablation candidate.",
        }
        for name in INTERACTION_FEATURES
    ] + [
        {"name": name, "status": "EXCLUDED_SOURCE_UNAVAILABLE", "reason": reason}
        for name, reason in EXCLUDED_INTERACTIONS.items()
    ]
    if (
        manifest.get("manifestContract") != CONTEXT_GOLD_CONTRACT
        or manifest.get("datasetId") != CONTEXT_GOLD_DATASET_ID
        or manifest.get("status") != "RESEARCH_ONLY_FEATURE_EVIDENCE"
        or int(manifest.get("coreFeatureCount") or -1) != 48
        or int(manifest.get("addedFeatureCount") or -1) != len(CONTEXT_FEATURES)
        or int(manifest.get("totalFeatureCount") or -1) != len(ORDERED_GOLD_PLUS_CONTEXT_FEATURES)
        or manifest.get("coreFeatureNames") != list(GOLD_FEATURES)
        or manifest.get("featureNames") != list(ORDERED_GOLD_PLUS_CONTEXT_FEATURES)
        or manifest.get("contextFeatureNames") != list(CONTEXT_FEATURES)
        or manifest.get("classOrder") != list(GOLD_CLASS_ORDER)
        or manifest.get("featureSpecs") != expected_feature_specs
        or manifest.get("featureFamilies") != expected_families
        or manifest.get("interactions") != expected_interactions
    ):
        raise ContextualGoldError("contextual feature contract differs")
    if any(int(manifest.get(key) or 0) != 0 for key in ("modelsFitted", "modelsScored", "modelsCalibrated")) or manifest.get("modelPromoted") is not False:
        raise ContextualGoldError("contextual publication invoked a model operation")
    source = manifest.get("sourceGold") or {}
    source_sha = str(source.get("manifestSha256") or "")
    verify_current_gold(Path(current_gold_root), source_sha)
    source_manifest_path = Path(current_gold_root) / "publications" / "sha256" / source_sha / "manifest.json"
    source_manifest = _load_json(source_manifest_path)
    if (
        source.get("datasetId") != CURRENT_GOLD_DATASET_ID
        or int(source.get("rowCount") or -1) != int(source_manifest.get("rowCount") or -2)
        or int(source.get("featureCount") or -1) != 48
        or source.get("partitionSha256s")
        != [item.get("sha256") for item in source_manifest.get("partitions") or []]
        or source.get("temporalContract") != source_manifest.get("temporalContract")
    ):
        raise ContextualGoldError("contextual source-Gold authority differs")

    venues, teams, static_authority = _load_static_authorities()
    rivalry = _load_rivalry_proposal()
    source_bundle = _source_bundle or load_context_source_bundle()
    expected_authorities = {**dict(source_bundle.authorities), "staticVenueTeam": static_authority}
    if manifest.get("sourceAuthorities") != expected_authorities:
        raise ContextualGoldError("contextual source authority bytes differ")
    if manifest.get("rivalryMapping") != rivalry:
        raise ContextualGoldError("contextual rivalry authority bytes differ")
    inputs, context_sources = _context_inputs(source_bundle, venues)
    expected_team_rows, expected_team_index = _team_context(
        inputs,
        venues=venues,
        teams=teams,
        sources=context_sources,
        distance_version=str(static_authority["distanceMethod"]),
    )
    expected_team_table = _team_table(expected_team_rows)

    source_by_season = {int(item["season"]): item for item in source_manifest.get("partitions") or []}
    if set(source_by_season) != {2023, 2024, 2025, 2026}:
        raise ContextualGoldError("contextual source-Gold seasons differ")
    rows = 0
    seen: set[str] = set()
    for item in manifest.get("partitions") or []:
        season = int(item["season"])
        path = root / str(item["relativePath"])
        if not path.is_file() or _sha_file(path) != item["sha256"]:
            raise ContextualGoldError("contextual partition SHA differs")
        table = pq.read_table(path)
        if table.num_rows != int(item["rowCount"]):
            raise ContextualGoldError("contextual partition row count differs")
        if table.column_names[-(len(CONTEXT_FEATURES) + len(_LINEAGE_FIELDS)):] != [*CONTEXT_FEATURES, *_LINEAGE_FIELDS]:
            raise ContextualGoldError("contextual appended column order differs")
        source_item = source_by_season[season]
        if item.get("sourceGoldPartitionSha256") != source_item.get("sha256"):
            raise ContextualGoldError("context partition is not bound to exact source Gold bytes")
        source_table = pq.read_table(Path(current_gold_root) / str(source_item["relativePath"]))
        if not _tables_equal(table.select(source_table.column_names), source_table):
            raise ContextualGoldError("existing Gold row values changed in contextual publication")
        expected_projection = _append_context(
            source_table,
            team_table=expected_team_table,
            index=expected_team_index,
            sources=context_sources,
            distance_version=str(static_authority["distanceMethod"]),
        )
        if not _tables_equal(table, expected_projection):
            raise ContextualGoldError(
                "contextual PA projection differs from exact team/game authority"
            )
        identities = [str(value) for value in table["canonicalPaId"].to_pylist()]
        if len(set(identities)) != len(identities) or any(value in seen for value in identities):
            raise ContextualGoldError("contextual PA identities are not one-to-one")
        seen.update(identities)
        for name in CONTEXT_FEATURES:
            if pa.types.is_floating(table.schema.field(name).type):
                values = table[name].to_pylist()
                if any(value is not None and not math.isfinite(float(value)) for value in values):
                    raise ContextualGoldError(f"context feature is non-finite: {name}")
        rows += table.num_rows
    team = manifest.get("teamGameContext") or {}
    team_path = root / str(team.get("relativePath") or "")
    if not team_path.is_file() or _sha_file(team_path) != team.get("sha256"):
        raise ContextualGoldError("team-game context object SHA differs")
    if (
        team.get("contract") != CONTEXT_TEAM_GAME_CONTRACT
        or team.get("naturalKey") != ["canonical_game_id", "team_id"]
    ):
        raise ContextualGoldError("team-game context contract differs")
    team_table = pq.read_table(team_path)
    if not _tables_equal(team_table, expected_team_table):
        raise ContextualGoldError("team-game contextual values do not recompute exactly")
    keys = list(zip(team_table["canonical_game_id"].to_pylist(), team_table["team_id"].to_pylist()))
    if team_table.num_rows != int(team.get("rowCount") or -1) or len(set(keys)) != len(keys):
        raise ContextualGoldError("team-game natural key does not reconcile")
    for name in (
        "rivalry_pair", "rivalry_game", "home_rivalry_game",
        "friday_night_home_rivalry", "weekend_home_rivalry", "home_x_rivalry",
    ):
        if int(pc.count(team_table[name], mode="only_valid").as_py() or 0) != 0:
            raise ContextualGoldError("inactive rivalry feature contains a value")
    if set(team_table["rivalry_mapping_missing"].to_pylist()) != {1.0}:
        raise ContextualGoldError("inactive rivalry mapping flag differs")
    if rows != int(manifest.get("rowCount") or -1) or rows != int(source.get("rowCount") or -2):
        raise ContextualGoldError("contextual/source Gold row counts differ")
    return {
        "datasetId": CONTEXT_GOLD_DATASET_ID,
        "manifestSha256": str(manifest_sha256),
        "sourceGoldManifestSha256": source_sha,
        "rowCount": rows,
        "teamGameRowCount": team_table.num_rows,
        "coreFeatureCount": 48,
        "addedFeatureCount": len(CONTEXT_FEATURES),
        "totalFeatureCount": len(ORDERED_GOLD_PLUS_CONTEXT_FEATURES),
        "modelsFitted": 0,
        "verified": True,
    }


def issue_contextual_verification_receipt(
    output_root: Path = DEFAULT_CONTEXT_GOLD_ROOT,
    manifest_sha256: str | None = None,
    *,
    current_gold_root: Path = DEFAULT_CURRENT_GOLD_ROOT,
) -> dict[str, Any]:
    """Deep-verify an existing immutable publication and bind its receipt current.

    This is the metadata-only migration path for publications created before
    verification receipts existed. It never rewrites a manifest or data object.
    """

    root = Path(output_root).resolve()
    locator = _load_json(root / "current.json")
    sha = str(manifest_sha256 or locator.get("manifestSha256") or "")
    if sha != str(locator.get("manifestSha256") or ""):
        raise ContextualGoldError("receipt may be issued only for the current contextual manifest")
    manifest_path = root / "publications" / "sha256" / sha / "manifest.json"
    if not manifest_path.is_file() or _sha_file(manifest_path) != sha:
        raise ContextualGoldError("receipt target manifest is not content-addressed")
    manifest = _load_json(manifest_path)
    verification = verify_contextual_gold(
        root, sha, current_gold_root=Path(current_gold_root)
    )
    receipt_sha, receipt_path = _write_verification_receipt(
        root, sha, manifest, verification
    )
    _atomic_current(root, sha, manifest_path, receipt_sha, receipt_path)
    return {
        **verification,
        "verificationReceiptSha256": receipt_sha,
        "verificationReceiptPath": str(receipt_path),
    }


def _validate_verification_receipt(
    root: Path,
    current: Mapping[str, Any],
    manifest_sha: str,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    receipt_sha = str(current.get("verificationReceiptSha256") or "")
    relative = str(current.get("verificationReceiptRelativePath") or "")
    if not receipt_sha or not relative:
        raise ContextualGoldError("current contextual verification receipt is missing")
    receipt_path = Path(root) / relative
    expected_path = Path(root) / "verification-receipts" / "sha256" / receipt_sha / "receipt.json"
    if receipt_path.resolve() != expected_path.resolve():
        raise ContextualGoldError("current contextual verification receipt path differs")
    if not receipt_path.is_file() or _sha_file(receipt_path) != receipt_sha:
        raise ContextualGoldError("current contextual verification receipt is not content-addressed")
    receipt = _load_json(receipt_path)
    if (
        receipt.get("receiptContract") != CONTEXT_VERIFICATION_RECEIPT_CONTRACT
        or receipt.get("datasetId") != CONTEXT_GOLD_DATASET_ID
        or receipt.get("manifestSha256") != manifest_sha
        or receipt.get("verified") is not True
        or int(receipt.get("modelsFitted") or 0) != 0
        or int(receipt.get("rowCount") or -1) != int(manifest.get("rowCount") or -2)
        or int(receipt.get("teamGameRowCount") or -1)
        != int((manifest.get("teamGameContext") or {}).get("rowCount") or -2)
        or int(receipt.get("coreFeatureCount") or -1) != int(manifest.get("coreFeatureCount") or -2)
        or int(receipt.get("addedFeatureCount") or -1) != int(manifest.get("addedFeatureCount") or -2)
        or int(receipt.get("totalFeatureCount") or -1) != int(manifest.get("totalFeatureCount") or -2)
        or any(receipt.get(key) != value for key, value in _receipt_bindings(manifest).items())
    ):
        raise ContextualGoldError("current contextual verification receipt bindings differ")
    return receipt


def contextual_feature_review(
    output_root: Path = DEFAULT_CONTEXT_GOLD_ROOT,
    *,
    source_gold_manifest_sha256: str | None = None,
    current_gold_root: Path = DEFAULT_CURRENT_GOLD_ROOT,
) -> dict[str, Any] | None:
    """Small semantically verified review payload for the Stage 2 UI."""

    locator = Path(output_root) / "current.json"
    if not locator.is_file():
        return None
    current = _load_json(locator)
    sha = str(current.get("manifestSha256") or "")
    path = Path(output_root) / "publications" / "sha256" / sha / "manifest.json"
    expected_manifest_relative = path.resolve().relative_to(Path(output_root).resolve()).as_posix()
    if (
        current.get("currentManifestSha256") != sha
        or current.get("manifestRelativePath") != expected_manifest_relative
    ):
        raise ContextualGoldError("current contextual manifest locator bindings differ")
    if not path.is_file() or _sha_file(path) != sha:
        raise ContextualGoldError("current contextual review manifest differs")
    manifest = _load_json(path)
    source_sha = str((manifest.get("sourceGold") or {}).get("manifestSha256") or "")
    if source_gold_manifest_sha256 is not None and source_sha != source_gold_manifest_sha256:
        return None
    verification = _validate_verification_receipt(
        Path(output_root).resolve(), current, sha, manifest
    )
    coverage = manifest.get("featureCoverage") or {}

    def family_for(name: str) -> str:
        if name in GOLD_FEATURES:
            return "CORE_GOLD_48"
        if name in GAME_CONTEXT_FEATURES:
            return "CALENDAR"
        raw = name.removeprefix("batting_").removeprefix("fielding_")
        if raw in INTERACTION_FEATURES:
            return "INTERACTION"
        if raw in MISSING_FLAG_FEATURES:
            return "MISSINGNESS"
        if any(token in raw for token in ("travel", "road_trip", "home_stand", "venue")):
            return "REST_TRAVEL"
        if any(token in raw for token in ("circadian", "body_clock", "time_zone", "early_start", "late_start")):
            return "CIRCADIAN"
        if any(token in raw for token in ("league", "division", "opponent", "rivalry", "rematch")):
            return "DIVISION_RIVALRY"
        return "REST_TRAVEL"

    def feature_definition(name: str) -> str:
        if name in GOLD_FEATURES:
            return "Existing immutable Gold-48 predictor; definition remains governed by the current Gold feature contract."
        return name.replace("_", " ").capitalize() + "; deterministic candidate feature under the contextual V2 contract."

    def proxy_warning(name: str) -> str | None:
        raw = name.removeprefix("batting_").removeprefix("fielding_")
        if "rivalry" in raw:
            return "Subjective rivalry authority is not approved; this field remains inactive/null."
        if any(token in raw for token in ("travel", "circadian", "body_clock", "overnight")):
            return "Schedule/geography proxy only; it is not an observation of player travel, sleep, or fatigue."
        if "holiday" in raw:
            return "Venue-calendar proxy only; it does not measure motivation or crowd effects."
        return None

    features = []
    for name in ORDERED_GOLD_PLUS_CONTEXT_FEATURES:
        item = coverage.get(name) or {}
        family = family_for(name)
        features.append({
            "name": name,
            "family": family,
            "category": "CORE_GOLD_48" if name in GOLD_FEATURES else "CONTEXTUAL_CANDIDATE",
            "definition": feature_definition(name),
            "sourceLineage": (
                f"{CURRENT_GOLD_DATASET_ID}@{source_sha}" if name in GOLD_FEATURES
                else "exact team-game schedule/venue authority plus strictly prior-date completed-game context"
            ),
            "pointInTimeTreatment": (
                "Existing Gold point-in-time contract" if name in GOLD_FEATURES
                else "Target pregame schedule facts or source.game_date < target.game_date; same-date excluded"
            ),
            "coverageOverall": float(item.get("overall") or 0.0),
            "coverageDevelopment": float(item.get("development") or 0.0),
            "coverageFinalOot": float(item.get("finalOot") or 0.0),
            "proxyWarning": proxy_warning(name),
            "includedByDefault": name in GOLD_FEATURES,
        })
    families = [
        {
            "name": name,
            "featureCount": len(values),
            "orderedFeatures": list(values),
            "includedByDefault": name.startswith("A_") or name.startswith("A "),
        }
        for name, values in (manifest.get("featureFamilies") or {}).items()
    ]
    return {
        "status": manifest["status"],
        "verified": bool(verification.get("verified")),
        "datasetId": manifest["datasetId"],
        "manifestSha256": sha,
        "sourceGoldManifestSha256": source_sha,
        "rowCount": int(manifest["rowCount"]),
        "coreFeatureCount": int(manifest["coreFeatureCount"]),
        "addedFeatureCount": int(manifest["addedFeatureCount"]),
        "totalFeatureCount": int(manifest["totalFeatureCount"]),
        "teamGameRowCount": int((manifest.get("teamGameContext") or {}).get("rowCount") or 0),
        "rivalryMappingStatus": str((manifest.get("rivalryMapping") or {}).get("status") or "MISSING"),
        "features": features,
        "families": families,
        "interactions": list(manifest.get("interactions") or []),
        "warnings": list(manifest.get("limitations") or []),
    }


__all__ = [
    "CONTEXT_GOLD_DATASET_ID",
    "ContextualGoldError",
    "build_contextual_gold",
    "contextual_feature_review",
    "issue_contextual_verification_receipt",
    "verify_contextual_gold",
]
