"""Verified, read-only Phase 7B6 whole-game input materialization.

This module intentionally stops at the data boundary.  It does not simulate games,
choose participants, fit a model, or evaluate a market.  In particular, it never
exposes the realized per-PA batter/pitcher sequence as a prospective participant
policy.  The only participant authority returned here is the Retrosheet ``start``
record: nine ordered batters and one starting pitcher per side.

The Phase 7B5 holdout NPZ was written with an object-dtype ``rowIds`` member.  Loading
that member would require pickle.  This module never does so.  Holdout row identities
are reconstructed from the independently verified Gold object and reconciled to the
request's frozen identity hashes and the persisted label order.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .publication import verify_gold
from .silver_inputs import read_verified_columns, resolve_current_silver
from ..sports_silver.canonical_ids import canonical_team_id as canonical_team_id_from_abbrev


SCHEMA_VERSION = "MLB_GOLD_GAME_SIMULATION_INPUTS_V1"
ALLOWED_SEASONS = (2022, 2023, 2024)
FORBIDDEN_SEASONS = (2025, 2026)
CLASS_COUNT = 8

_STUDY_INPUT_ARTIFACTS = (
    "request.json",
    "predictions/walk-forward-oof.npz",
    "predictions/walk-forward-oof-reliability.npz",
    "predictions/final-holdout.npz",
    "predictions/final-holdout-reliability.npz",
)
_GOLD_IDENTITY_COLUMNS = (
    "plate_appearance_id",
    "canonicalGameId",
    "game_id",
    "game_date",
    "season",
    "outcome",
)
_LINEUP_COLUMNS = (
    "canonicalGameId",
    "retroGameId",
    "playerCanonicalPlayerId",
    "recordType",
    "season",
    "homeAway",
    "battingOrder",
    "fieldPosition",
)
_DIM_GAME_COLUMNS = (
    "canonicalGameId",
    "mlbamGamePk",
    "gameDate",
    "season",
    "homeTeam",
    "awayTeam",
    "gameType",
    "retrosheetGameId",
    "gameNumber",
    "reconciliationStatus",
)
_TEAM_GAME_COLUMNS = (
    "canonicalGameId",
    "retroGameId",
    "canonicalTeamId",
    "homeAway",
    "season",
    "gameDate",
    "gameNumber",
    "parkId",
    "runsScored",
    "runsAllowed",
)
_FD1_FIVE_COLUMNS = (
    "game_id",
    "season",
    "play_number",
    "inning",
    "top_bottom",
    "visiting_score_before",
    "home_score_before",
)


class GameSimulationInputError(RuntimeError):
    """A Phase 7B6 input violated its fixed authority or temporal boundary."""


@dataclass(frozen=True)
class VerifiedStudy:
    root: Path
    request: Mapping[str, Any]
    manifest: Mapping[str, Any]
    artifact_sha256: Mapping[str, str]


@dataclass(frozen=True)
class PredictionCohort:
    cohort_id: str
    start_date: str
    end_date: str
    row_ids: tuple[str, ...]
    canonical_game_ids_by_row: tuple[str, ...]
    game_ids_by_row: tuple[str, ...]
    game_ids: tuple[str, ...]
    canonical_game_ids: tuple[str, ...]
    labels: tuple[str, ...]
    probability_matrices: Mapping[str, np.ndarray]
    reliability: Mapping[str, np.ndarray]

    @property
    def row_count(self) -> int:
        return len(self.row_ids)

    @property
    def game_count(self) -> int:
        return len(self.canonical_game_ids)


@dataclass(frozen=True)
class TeamPregame:
    canonical_team_id: str
    batting_order: tuple[str, ...]
    starting_pitcher_id: str


@dataclass(frozen=True)
class PregameGame:
    canonical_game_id: str
    prediction_game_id: str
    retrosheet_game_id: str
    mlbam_game_pk: str | None
    game_date: str
    season: int
    game_type: str
    game_number: int
    park_id: str
    away: TeamPregame
    home: TeamPregame
    source_timing: str = "RETROSHEET_ACTUAL_START_RECORD_NO_ANNOUNCED_AT"


@dataclass(frozen=True)
class GameTruth:
    canonical_game_id: str
    away_runs: int
    home_runs: int
    first_five_away_runs: int | None = None
    first_five_home_runs: int | None = None
    first_five_source: str | None = None

    @property
    def first_five_available(self) -> bool:
        return self.first_five_away_runs is not None and self.first_five_home_runs is not None


@dataclass(frozen=True)
class GameSimulationInputs:
    schema_version: str
    study: VerifiedStudy
    gold_identity: Mapping[str, Any]
    silver_identities: Mapping[str, Mapping[str, object]]
    cohorts: Mapping[str, PredictionCohort]
    games: Mapping[str, PregameGame]
    truth: Mapping[str, GameTruth]


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _identity_inventory_sha256(values: Sequence[Any]) -> str:
    normalized = sorted({str(value) for value in values})
    if not normalized or any(not value.strip() for value in normalized):
        raise GameSimulationInputError("identity inventory is empty or blank")
    return hashlib.sha256(("\n".join(normalized) + "\n").encode("utf-8")).hexdigest()


def _contained_file(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise GameSimulationInputError(f"study artifact path is unsafe: {relative}")
    path = (root / rel).resolve()
    if root != path and root not in path.parents:
        raise GameSimulationInputError(f"study artifact escapes root: {relative}")
    if not path.is_file():
        raise GameSimulationInputError(f"study artifact is missing: {relative}")
    return path


def verify_phase7b5_study(study_root: Path, *, verify_all: bool = True) -> VerifiedStudy:
    """Verify the immutable Phase 7B5 request and every manifest-bound artifact byte."""

    root = Path(study_root).resolve()
    manifest_path = _contained_file(root, "manifest.json")
    request_path = _contained_file(root, "request.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GameSimulationInputError("Phase 7B5 JSON is invalid") from exc
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise GameSimulationInputError("Phase 7B5 artifact manifest is missing")
    required = set(_STUDY_INPUT_ARTIFACTS)
    if not required.issubset(artifacts):
        raise GameSimulationInputError(
            f"Phase 7B5 input artifacts are missing: {sorted(required - set(artifacts))}"
        )
    selected = tuple(sorted(artifacts)) if verify_all else _STUDY_INPUT_ARTIFACTS
    verified: dict[str, str] = {}
    for relative in selected:
        evidence = artifacts.get(relative)
        if not isinstance(evidence, dict):
            raise GameSimulationInputError(f"artifact evidence is invalid: {relative}")
        path = _contained_file(root, relative)
        size, digest = _sha256_file(path)
        if size != int(evidence.get("bytes", -1)) or digest != evidence.get("sha256"):
            raise GameSimulationInputError(f"artifact bytes differ: {relative}")
        verified[relative] = digest
    request_sha = hashlib.sha256(request_path.read_bytes()).hexdigest()
    if root.name != request_sha or verified.get("request.json") != request_sha:
        raise GameSimulationInputError("study address differs from canonical request bytes")
    if manifest.get("request") is not None and manifest.get("request") != request:
        raise GameSimulationInputError("manifest-embedded request differs")
    return VerifiedStudy(
        root=root,
        request=MappingProxyType(request),
        manifest=MappingProxyType(manifest),
        artifact_sha256=MappingProxyType(verified),
    )


def _readonly(values: np.ndarray) -> np.ndarray:
    # NPZ members already materialize as owned arrays.  Fold slices may safely retain
    # that array as their base; avoiding a second 800+ MB copy keeps the real OOF load
    # bounded without weakening immutability at the public view.
    result = np.ascontiguousarray(values)
    result.setflags(write=False)
    return result


def _probability_key(raw: str) -> str | None:
    if raw == "null":
        return "CLASS_FREQUENCY_NULL"
    if raw == "base22":
        return "MATCHED_BASE"
    if raw.startswith("component__"):
        return raw.removeprefix("component__")
    if raw.startswith("ensemble__"):
        return raw.removeprefix("ensemble__")
    return None


def _load_npz_arrays(path: Path, *, rows: int, probability_file: bool) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    try:
        with np.load(path, allow_pickle=False) as package:
            for raw in package.files:
                # The holdout rowIds object member is deliberately never accessed.
                if raw in {"rowIds", "labels"}:
                    continue
                values = np.asarray(package[raw])
                if values.shape[0] != rows:
                    raise GameSimulationInputError(f"NPZ row count differs: {path.name}:{raw}")
                if probability_file:
                    method = _probability_key(raw)
                    if method is None:
                        raise GameSimulationInputError(f"unknown probability member: {raw}")
                    if values.shape != (rows, CLASS_COUNT):
                        raise GameSimulationInputError(f"probability shape differs: {raw}")
                    numeric = np.asarray(values, dtype=np.float64)
                    if (
                        not np.isfinite(numeric).all()
                        or np.any(numeric < 0.0)
                        or not np.allclose(numeric.sum(axis=1), 1.0, rtol=0.0, atol=1e-12)
                    ):
                        raise GameSimulationInputError(f"probability contract differs: {raw}")
                    if method in result:
                        raise GameSimulationInputError(f"duplicate method id: {method}")
                    result[method] = _readonly(numeric)
                else:
                    if values.dtype.kind == "O":
                        raise GameSimulationInputError(f"object reliability member rejected: {raw}")
                    result[raw] = _readonly(values)
    except (OSError, ValueError) as exc:
        raise GameSimulationInputError(f"safe NPZ load failed: {path.name}") from exc
    return result


def _npz_labels(path: Path, *, expected_rows: int) -> tuple[str, ...]:
    try:
        with np.load(path, allow_pickle=False) as package:
            values = np.asarray(package["labels"])
    except (OSError, ValueError, KeyError) as exc:
        raise GameSimulationInputError(f"safe label load failed: {path.name}") from exc
    if values.shape != (expected_rows,) or values.dtype.kind == "O":
        raise GameSimulationInputError(f"label contract differs: {path.name}")
    labels = tuple(str(value) for value in values.tolist())
    if any(not label for label in labels):
        raise GameSimulationInputError("prediction labels contain blanks")
    return labels


def _npz_oof_row_ids(path: Path, *, expected_rows: int) -> tuple[str, ...]:
    try:
        with np.load(path, allow_pickle=False) as package:
            values = np.asarray(package["rowIds"])
    except (OSError, ValueError, KeyError) as exc:
        raise GameSimulationInputError("OOF row IDs are not safely loadable") from exc
    if values.shape != (expected_rows,) or values.dtype.kind == "O":
        raise GameSimulationInputError("OOF row ID contract differs")
    row_ids = tuple(str(value) for value in values.tolist())
    if len(set(row_ids)) != len(row_ids) or any(not value for value in row_ids):
        raise GameSimulationInputError("OOF row IDs are duplicated or blank")
    return row_ids


def _prediction_sources(study: VerifiedStudy, gold: pd.DataFrame) -> tuple[
    list[tuple[str, str, str, pd.DataFrame]], pd.DataFrame
]:
    request = study.request
    required = set(_GOLD_IDENTITY_COLUMNS)
    if not required.issubset(gold.columns):
        raise GameSimulationInputError(f"Gold identity columns missing: {sorted(required-set(gold.columns))}")
    frame = gold.loc[:, list(_GOLD_IDENTITY_COLUMNS)].copy()
    for column in ("plate_appearance_id", "canonicalGameId", "game_id", "game_date", "outcome"):
        frame[column] = frame[column].astype(str)
        if frame[column].str.strip().eq("").any():
            raise GameSimulationInputError(f"Gold identity column is blank: {column}")
    frame["season"] = pd.to_numeric(frame["season"], errors="raise").astype(np.int64)
    if frame["plate_appearance_id"].duplicated().any():
        raise GameSimulationInputError("Gold PA identity is duplicated")
    if not set(frame["season"]).issubset(ALLOWED_SEASONS + (2021,)):
        raise GameSimulationInputError("Gold contains a forbidden season")
    folds = request.get("folds")
    holdout = request.get("holdout")
    if not isinstance(folds, list) or len(folds) != 5 or not isinstance(holdout, dict):
        raise GameSimulationInputError("Phase 7B5 split request differs")
    parts: list[tuple[str, str, str, pd.DataFrame]] = []
    for item in folds:
        cohort_id = str(item["foldId"])
        start, end = str(item["validationStart"]), str(item["validationEnd"])
        target = frame.loc[frame["game_date"].between(start, end)].copy()
        if len(target) != int(item["validationRows"]):
            raise GameSimulationInputError(f"Gold fold row count differs: {cohort_id}")
        parts.append((cohort_id, start, end, target))
    start, end = str(holdout["startDate"]), str(holdout["endDate"])
    target = frame.loc[frame["game_date"].between(start, end)].copy()
    if len(target) != int(holdout["rowCount"]) or target["canonicalGameId"].nunique() != int(
        holdout["gameCount"]
    ):
        raise GameSimulationInputError("Gold holdout population differs")
    identity = request.get("holdoutIdentity") or {}
    if (
        _identity_inventory_sha256(target["plate_appearance_id"].tolist())
        != identity.get("plateAppearanceIdInventorySha256")
        or _identity_inventory_sha256(target["game_id"].tolist())
        != identity.get("gameIdInventorySha256")
    ):
        raise GameSimulationInputError("Gold holdout identity inventory differs")
    return parts, target


def _cohort(
    cohort_id: str,
    start: str,
    end: str,
    frame: pd.DataFrame,
    matrices: Mapping[str, np.ndarray],
    reliability: Mapping[str, np.ndarray],
) -> PredictionCohort:
    games = frame[["canonicalGameId", "game_id"]].drop_duplicates()
    if games["canonicalGameId"].duplicated().any() or games["game_id"].duplicated().any():
        raise GameSimulationInputError(f"game identity is not one-to-one: {cohort_id}")
    return PredictionCohort(
        cohort_id=cohort_id,
        start_date=start,
        end_date=end,
        row_ids=tuple(frame["plate_appearance_id"].tolist()),
        canonical_game_ids_by_row=tuple(frame["canonicalGameId"].tolist()),
        game_ids_by_row=tuple(frame["game_id"].tolist()),
        game_ids=tuple(sorted(games["game_id"].tolist())),
        canonical_game_ids=tuple(sorted(games["canonicalGameId"].tolist())),
        labels=tuple(frame["outcome"].tolist()),
        probability_matrices=MappingProxyType(dict(matrices)),
        reliability=MappingProxyType(dict(reliability)),
    )


def load_prediction_cohorts(
    study: VerifiedStudy,
    gold_identity_frame: pd.DataFrame,
) -> Mapping[str, PredictionCohort]:
    """Safely bind every Phase 7B5 probability row to a verified Gold PA identity."""

    fold_parts, holdout = _prediction_sources(study, gold_identity_frame)
    oof_frame = pd.concat([part for _, _, _, part in fold_parts], ignore_index=True)
    oof_path = study.root / "predictions" / "walk-forward-oof.npz"
    holdout_path = study.root / "predictions" / "final-holdout.npz"
    oof_ids = _npz_oof_row_ids(oof_path, expected_rows=len(oof_frame))
    expected_oof_ids = tuple(oof_frame["plate_appearance_id"].tolist())
    if oof_ids != expected_oof_ids:
        raise GameSimulationInputError("OOF row identity order differs from Gold")
    oof_labels = _npz_labels(oof_path, expected_rows=len(oof_frame))
    holdout_labels = _npz_labels(holdout_path, expected_rows=len(holdout))
    if oof_labels != tuple(oof_frame["outcome"].tolist()):
        raise GameSimulationInputError("OOF labels differ from Gold")
    if holdout_labels != tuple(holdout["outcome"].tolist()):
        raise GameSimulationInputError("holdout labels differ from Gold-derived order")
    oof_prob = _load_npz_arrays(oof_path, rows=len(oof_frame), probability_file=True)
    oof_rel = _load_npz_arrays(
        study.root / "predictions" / "walk-forward-oof-reliability.npz",
        rows=len(oof_frame),
        probability_file=False,
    )
    hold_prob = _load_npz_arrays(holdout_path, rows=len(holdout), probability_file=True)
    hold_rel = _load_npz_arrays(
        study.root / "predictions" / "final-holdout-reliability.npz",
        rows=len(holdout),
        probability_file=False,
    )
    if "DIRECT_GOLD" not in oof_prob or "E10" not in oof_prob:
        raise GameSimulationInputError("OOF Direct Gold or E10 is missing")
    if "DIRECT_GOLD" not in hold_prob or "E10" not in hold_prob:
        raise GameSimulationInputError("holdout Direct Gold or E10 is missing")
    result: dict[str, PredictionCohort] = {}
    offset = 0
    for cohort_id, start, end, part in fold_parts:
        stop = offset + len(part)
        result[cohort_id] = _cohort(
            cohort_id,
            start,
            end,
            part,
            {key: _readonly(value[offset:stop]) for key, value in oof_prob.items()},
            {key: _readonly(value[offset:stop]) for key, value in oof_rel.items()},
        )
        offset = stop
    if offset != len(oof_frame):
        raise GameSimulationInputError("OOF fold slicing did not reconcile")
    result["HOLDOUT"] = _cohort(
        "HOLDOUT",
        str(study.request["holdout"]["startDate"]),
        str(study.request["holdout"]["endDate"]),
        holdout,
        hold_prob,
        hold_rel,
    )
    return MappingProxyType(result)


def _required_text(value: Any, name: str) -> str:
    parsed = str(value).strip()
    if not parsed or parsed.lower() in {"nan", "none"}:
        raise GameSimulationInputError(f"{name} is blank")
    return parsed


def _strict_int(value: Any, name: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise GameSimulationInputError(f"{name} is not an integer") from exc
    return parsed


def build_pregame_games(
    target_games: pd.DataFrame,
    lineup: pd.DataFrame,
    dim_game: pd.DataFrame,
    team_game: pd.DataFrame,
) -> tuple[Mapping[str, PregameGame], Mapping[str, GameTruth]]:
    """Build exact pregame records using only ``recordType=start`` lineup rows."""

    needed = {str(value) for value in target_games["canonicalGameId"].tolist()}
    if not needed:
        raise GameSimulationInputError("target game inventory is empty")
    starts = lineup.loc[lineup["recordType"].astype(str).eq("start")].copy()
    starts = starts.loc[starts["canonicalGameId"].astype(str).isin(needed)]
    starts["battingOrderInt"] = pd.to_numeric(starts["battingOrder"], errors="raise").astype(int)
    starts["fieldPositionInt"] = pd.to_numeric(starts["fieldPosition"], errors="raise").astype(int)
    dims = dim_game.loc[dim_game["canonicalGameId"].astype(str).isin(needed)].copy()
    teams = team_game.loc[team_game["canonicalGameId"].astype(str).isin(needed)].copy()

    # Build positional indexes once.  Re-filtering each full authority frame for
    # every one of the 7,163 governed games is quadratic in practice (especially
    # for the 143,260-row lineup table) and makes the bounded real load unusable.
    def grouped_positions(frame: pd.DataFrame) -> Mapping[str, np.ndarray]:
        keys = frame["canonicalGameId"].astype(str)
        return {
            str(key): np.asarray(positions, dtype=np.int64)
            for key, positions in keys.groupby(keys, sort=False).indices.items()
        }

    target_positions = grouped_positions(target_games)
    dim_positions = grouped_positions(dims)
    team_positions = grouped_positions(teams)
    lineup_positions = grouped_positions(starts)

    def group(frame: pd.DataFrame, positions: Mapping[str, np.ndarray], game_id: str) -> pd.DataFrame:
        index = positions.get(game_id)
        return frame.iloc[0:0] if index is None else frame.iloc[index]

    games: dict[str, PregameGame] = {}
    truth: dict[str, GameTruth] = {}
    for game_id in sorted(needed):
        target = group(target_games, target_positions, game_id).drop_duplicates()
        d = group(dims, dim_positions, game_id)
        t = group(teams, team_positions, game_id)
        l = group(starts, lineup_positions, game_id)
        if len(target) != 1 or len(d) != 1 or len(t) != 2 or len(l) != 20:
            raise GameSimulationInputError(f"game authority cardinality differs: {game_id}")
        dim = d.iloc[0]
        if str(dim["reconciliationStatus"]) != "MATCHED_EXACT" or str(dim["gameType"]) != "R":
            raise GameSimulationInputError(f"game is not exact regular-season authority: {game_id}")
        side_records: dict[str, TeamPregame] = {}
        team_rows: dict[str, pd.Series] = {}
        for side in ("away", "home"):
            side_lineup = l.loc[l["homeAway"].astype(str).eq(side)]
            batters = side_lineup.loc[side_lineup["battingOrderInt"].between(1, 9)].sort_values(
                "battingOrderInt"
            )
            pitcher = side_lineup.loc[
                side_lineup["battingOrderInt"].eq(0)
                & side_lineup["fieldPositionInt"].eq(1)
            ]
            side_team = t.loc[t["homeAway"].astype(str).eq(side)]
            if (
                len(side_lineup) != 10
                or len(batters) != 9
                or batters["battingOrderInt"].tolist() != list(range(1, 10))
                or batters["playerCanonicalPlayerId"].astype(str).nunique() != 9
                or len(pitcher) != 1
                or len(side_team) != 1
            ):
                raise GameSimulationInputError(f"pregame side authority differs: {game_id}:{side}")
            team_row = side_team.iloc[0]
            expected_team = dim["awayTeam" if side == "away" else "homeTeam"]
            canonical_team_id = _required_text(team_row["canonicalTeamId"], "canonicalTeamId")
            # dim_game carries the governed Statcast/window-stable abbreviation,
            # while fact_team_game carries its canonical hashed identity.  Compare
            # them through the accepted canonical-ID primitive rather than treating
            # the two distinct namespaces as identical strings.
            if canonical_team_id != canonical_team_id_from_abbrev(
                _required_text(expected_team, "dim team")
            ):
                raise GameSimulationInputError(f"Silver team identity differs: {game_id}:{side}")
            side_records[side] = TeamPregame(
                canonical_team_id=canonical_team_id,
                batting_order=tuple(
                    _required_text(value, "starting batter")
                    for value in batters["playerCanonicalPlayerId"].tolist()
                ),
                starting_pitcher_id=_required_text(
                    pitcher.iloc[0]["playerCanonicalPlayerId"], "starting pitcher"
                ),
            )
            team_rows[side] = team_row
        away, home = team_rows["away"], team_rows["home"]
        away_runs = _strict_int(away["runsScored"], "away runs")
        home_runs = _strict_int(home["runsScored"], "home runs")
        if (
            _strict_int(away["runsAllowed"], "away runs allowed") != home_runs
            or _strict_int(home["runsAllowed"], "home runs allowed") != away_runs
        ):
            raise GameSimulationInputError(f"final score mirror differs: {game_id}")
        parks = {_required_text(value, "parkId") for value in t["parkId"].tolist()}
        if len(parks) != 1:
            raise GameSimulationInputError(f"park identity differs: {game_id}")
        retro = _required_text(dim["retrosheetGameId"], "retrosheetGameId")
        if set(t["retroGameId"].astype(str)) != {retro}:
            raise GameSimulationInputError(f"Retrosheet game identity differs: {game_id}")
        prediction_game_id = _required_text(target.iloc[0]["game_id"], "prediction game_id")
        if prediction_game_id != f"retrosheet:game:{retro}":
            raise GameSimulationInputError(f"Gold/Retrosheet game identity differs: {game_id}")
        games[game_id] = PregameGame(
            canonical_game_id=game_id,
            prediction_game_id=prediction_game_id,
            retrosheet_game_id=retro,
            mlbam_game_pk=(
                None
                if str(dim["mlbamGamePk"]).strip().lower() in {"", "nan", "none"}
                else str(dim["mlbamGamePk"])
            ),
            game_date=_required_text(dim["gameDate"], "gameDate"),
            season=_strict_int(dim["season"], "season"),
            game_type="R",
            game_number=_strict_int(dim["gameNumber"], "gameNumber"),
            park_id=next(iter(parks)),
            away=side_records["away"],
            home=side_records["home"],
        )
        truth[game_id] = GameTruth(game_id, away_runs, home_runs)
    if set(games) != needed or set(truth) != needed:
        raise GameSimulationInputError("game input population did not reconcile")
    return MappingProxyType(games), MappingProxyType(truth)


def _validate_fd1_paths(
    play_transition_root: Path,
    partitions: Mapping[int, Sequence[Path]],
) -> tuple[tuple[int, Path], ...]:
    root = Path(play_transition_root).resolve()
    if not root.is_dir():
        raise GameSimulationInputError("FD1 play_transition root is missing")
    normalized: list[tuple[int, Path]] = []
    for raw_season, raw_paths in partitions.items():
        season = int(raw_season)
        if season not in ALLOWED_SEASONS:
            raise GameSimulationInputError(f"FD1 season rejected before open: {season}")
        if not raw_paths:
            raise GameSimulationInputError(f"FD1 explicit partition list is empty: {season}")
        marker = f"season={season}"
        for raw_path in raw_paths:
            supplied = Path(raw_path)
            if any(part.lower() in {"season=2025", "season=2026"} for part in supplied.parts):
                raise GameSimulationInputError("2025/2026 FD1 path rejected before open")
            if supplied.is_symlink():
                raise GameSimulationInputError(f"FD1 partition symlink rejected: {supplied}")
            path = supplied.resolve()
            if root not in path.parents or marker not in path.parts:
                raise GameSimulationInputError(f"FD1 path-season containment differs: {path}")
            if path.suffix.lower() != ".parquet" or not path.is_file():
                raise GameSimulationInputError(f"FD1 partition is not a regular parquet: {path}")
            normalized.append((season, path))
    if not normalized:
        raise GameSimulationInputError("no explicit FD1 partitions supplied")
    return tuple(sorted(normalized, key=lambda item: (item[0], str(item[1]))))


def load_fd1_first_five_truth(
    play_transition_root: Path,
    partitions: Mapping[int, Sequence[Path]],
    target_game_ids: Sequence[str],
) -> Mapping[str, tuple[int, int]]:
    """Load first-five scores from only explicitly allowlisted 2022--2024 FD1 files."""

    paths = _validate_fd1_paths(play_transition_root, partitions)
    targets = {str(value) for value in target_game_ids}
    frames: list[pd.DataFrame] = []
    for expected_season, path in paths:
        table = pq.read_table(path, columns=list(_FD1_FIVE_COLUMNS))
        frame = table.to_pandas()
        observed = {int(value) for value in frame["season"].tolist()}
        if observed != {expected_season}:
            raise GameSimulationInputError(f"FD1 partition season differs: {path}")
        frames.append(frame.loc[frame["game_id"].astype(str).isin(targets)])
    if not frames:
        return MappingProxyType({})
    frame = pd.concat(frames, ignore_index=True)
    if frame.empty:
        return MappingProxyType({})
    frame["play_number_int"] = pd.to_numeric(frame["play_number"], errors="raise").astype(int)
    frame["inning_int"] = pd.to_numeric(frame["inning"], errors="raise").astype(int)
    if frame.duplicated(["game_id", "play_number_int"]).any():
        raise GameSimulationInputError("FD1 play identity is duplicated")
    truth: dict[str, tuple[int, int]] = {}
    for game_id, game in frame.groupby("game_id", sort=True):
        after_five = game.loc[game["inning_int"].gt(5)].sort_values("play_number_int")
        if after_five.empty:
            continue
        first = after_five.iloc[0]
        if _strict_int(first["inning"], "FD1 inning") != 6:
            raise GameSimulationInputError(f"FD1 first-five boundary skips inning six: {game_id}")
        if _strict_int(first["top_bottom"], "FD1 top_bottom") != 0:
            raise GameSimulationInputError(f"FD1 first-five boundary skips top of inning six: {game_id}")
        truth[str(game_id)] = (
            _strict_int(first["visiting_score_before"], "FD1 visiting score"),
            _strict_int(first["home_score_before"], "FD1 home score"),
        )
    return MappingProxyType(truth)


def load_game_simulation_inputs(
    *,
    gold_root: Path,
    silver_root: Path,
    study_root: Path,
    fd1_play_transition_root: Path | None = None,
    fd1_partitions: Mapping[int, Sequence[Path]] | None = None,
    verify_all_study_artifacts: bool = True,
) -> GameSimulationInputs:
    """Materialize the bounded Phase 7B6 inputs without simulation or fitting."""

    study = verify_phase7b5_study(study_root, verify_all=verify_all_study_artifacts)
    verified_gold = verify_gold(Path(gold_root))
    manifest_sha = hashlib.sha256(Path(verified_gold["manifestPath"]).read_bytes()).hexdigest()
    if (
        verified_gold["logicalContentSha256"] != study.request.get("goldLogicalContentSha256")
        or manifest_sha != study.request.get("goldManifestSha256")
    ):
        raise GameSimulationInputError("Phase 7B5 request does not bind the verified Gold object")
    gold_frame = pq.read_table(
        Path(verified_gold["path"]), columns=list(_GOLD_IDENTITY_COLUMNS)
    ).to_pandas()
    cohorts = load_prediction_cohorts(study, gold_frame)
    target_rows = pd.concat(
        [
            pd.DataFrame(
                {
                    "canonicalGameId": cohort.canonical_game_ids_by_row,
                    "game_id": cohort.game_ids_by_row,
                }
            )
            for cohort in cohorts.values()
        ],
        ignore_index=True,
    ).drop_duplicates()
    if target_rows["canonicalGameId"].duplicated().any() or target_rows["game_id"].duplicated().any():
        raise GameSimulationInputError("target game identity is not one-to-one")

    lineup_handle = resolve_current_silver(Path(silver_root), "fact_lineup_participation")
    dim_handle = resolve_current_silver(Path(silver_root), "dim_game")
    team_handle = resolve_current_silver(Path(silver_root), "fact_team_game")
    lineup = read_verified_columns(
        lineup_handle, _LINEUP_COLUMNS, seasons=ALLOWED_SEASONS
    ).to_pandas()
    dim_game = read_verified_columns(
        dim_handle, _DIM_GAME_COLUMNS, seasons=ALLOWED_SEASONS
    ).to_pandas()
    team_game = read_verified_columns(
        team_handle, _TEAM_GAME_COLUMNS, seasons=ALLOWED_SEASONS
    ).to_pandas()
    games, truth = build_pregame_games(target_rows, lineup, dim_game, team_game)

    if (fd1_play_transition_root is None) != (fd1_partitions is None):
        raise GameSimulationInputError("FD1 root and explicit partitions must be supplied together")
    if fd1_play_transition_root is not None and fd1_partitions is not None:
        by_retro = load_fd1_first_five_truth(
            fd1_play_transition_root,
            fd1_partitions,
            [game.prediction_game_id for game in games.values()],
        )
        updated = dict(truth)
        for canonical_game_id, game in games.items():
            value = by_retro.get(game.prediction_game_id)
            if value is not None:
                updated[canonical_game_id] = replace(
                    updated[canonical_game_id],
                    first_five_away_runs=value[0],
                    first_five_home_runs=value[1],
                    first_five_source="FD1_PLAY_TRANSITION_FIRST_TOP_SIX_SCORE_BEFORE",
                )
        truth = MappingProxyType(updated)

    return GameSimulationInputs(
        schema_version=SCHEMA_VERSION,
        study=study,
        gold_identity=MappingProxyType(
            {
                "datasetVersionId": verified_gold["datasetVersionId"],
                "logicalContentSha256": verified_gold["logicalContentSha256"],
                "manifestSha256": manifest_sha,
                "rowCount": int(verified_gold["rowCount"]),
                "seasons": list(verified_gold["seasons"]),
            }
        ),
        silver_identities=MappingProxyType(
            {
                handle.table_name: MappingProxyType(handle.identity())
                for handle in (lineup_handle, dim_handle, team_handle)
            }
        ),
        cohorts=cohorts,
        games=games,
        truth=truth,
    )


__all__ = [
    "ALLOWED_SEASONS",
    "FORBIDDEN_SEASONS",
    "GameSimulationInputError",
    "GameSimulationInputs",
    "GameTruth",
    "PredictionCohort",
    "PregameGame",
    "SCHEMA_VERSION",
    "TeamPregame",
    "VerifiedStudy",
    "build_pregame_games",
    "load_fd1_first_five_truth",
    "load_game_simulation_inputs",
    "load_prediction_cohorts",
    "verify_phase7b5_study",
]
