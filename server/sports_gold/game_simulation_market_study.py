"""Phase 7B6 pregame-only game simulation and SHADOW market study.

The study consumes the immutable Phase 7B5 walk-forward evidence and the current
verified Gold/Silver authorities.  It does not rebuild a data layer or fit a PA
model.  Each historical game is simulated from exactly the recorded starting nine
and starting pitcher.  The lineup cycles and the announced starter is held constant;
actual substitutions and actual reliever choices are never simulation inputs.

Historical sportsbook coverage is explicitly zero.  The market output is therefore
an append-only schema/SHADOW board with ``NO_BET`` decisions and no ROI calculation.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
import time
import uuid
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix
from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5.game_initialization import RngLineage
from server.sports_phase5.whole_game_monte_carlo import (
    DEFAULT_REGULATION,
    MAX_TEAM_PA,
    FastTransitionSampler,
    GameContribs,
    GameSimResult,
    simulate_game,
)

from .contracts import GOLD_FEATURES
from .game_market_mvp import (
    KELLY_MULTIPLIER,
    MARKET_FAMILY_ORDER,
    MAX_DAILY_EXPOSURE_FRACTION,
    MAX_POSITION_FRACTION,
    MAX_SAME_GAME_EXPOSURE_FRACTION,
    NORMAL_UNIT_FRACTION,
    MarketFamily,
    market_mvp_contract,
    zero_historical_market_coverage,
)
from .game_probability_adapter import (
    CANONICAL_CONTEXT,
    E10,
    LINEUP_SIZE,
    SCHEMA_VERSION as ADAPTER_SCHEMA_VERSION,
    StartingLineupProbabilityProvider,
    TEMPLATE_COLUMNS,
    build_pregame_probability_adapter,
)
from .game_simulation_inputs import (
    GameSimulationInputs,
    GameTruth,
    PredictionCohort,
    PregameGame,
    load_game_simulation_inputs,
)
from .models import FittedFixedModel
from .publication import verify_gold
from .walk_forward_ensemble import (
    DIRECT_GOLD,
    WALK_FORWARD_COMPONENT_ORDER,
    WALK_FORWARD_EMPIRICAL_COMPONENTS,
    FittedWalkForwardStacker,
)
from .walk_forward_state import (
    ChronologicalDirectLedger,
    fit_walk_forward_state,
)


SCHEMA_VERSION = "MLB_GOLD_GAME_SIMULATION_MARKET_MVP_STUDY_V1"
REQUEST_SCHEMA_VERSION = "MLB_GOLD_GAME_SIMULATION_MARKET_MVP_REQUEST_V1"
RESULT_SCHEMA_VERSION = "MLB_GOLD_GAME_SIMULATION_MARKET_MVP_RESULT_V1"
MASTER_SEED = 20_260_818
SIMULATIONS_PER_GAME = 1_000
STABILITY_PREFIXES: tuple[int, ...] = (100, 250, 500, 1_000)
COMPARISON_BOOTSTRAP_ITERATIONS = 2_000
COMPARISON_BOOTSTRAP_SEED = MASTER_SEED
EXPECTED_STUDY_SHA256 = (
    "558d836e0080f7375a9884c1d370b164b0b109d64a23f50806d657b6c7b8a647"
)
EXPECTED_TRANSITION_MODEL_SHA256 = (
    "4f312af6c61c191b8ca19a71b35d8da12a587f204fb19b257715af9b7a3459e4"
)
EXPECTED_COHORT_GAMES: Mapping[str, int] = {
    "FOLD_1": 1_403,
    "FOLD_2": 1_406,
    "FOLD_3": 1_382,
    "FOLD_4": 1_393,
    "FOLD_5": 1_396,
    "HOLDOUT": 183,
}
EXPECTED_DIRECT_MODEL_SHA256: Mapping[str, str] = {
    "FOLD_1": "d4af35b3730c698ff94d58790c6a079353ae6742731dbbeecf4a4bd7b3144456",
    "FOLD_2": "135a4ba53fb16ffc339d0ce28cf642d4cb294493a29bc977f4d1accd157e0d4b",
    "FOLD_3": "d28ed377d550ac765fc4ccddb869c582f61bda3497da06020bfef4b75776a3f7",
    "FOLD_4": "dc924d1bbff771d3ce598ba537a135362122a5e080bd437277da554df99f17f1",
    "FOLD_5": "4ef36393fddb382037008867c8e72ce61e4312f487515022395a5ab17d2b877d",
    "HOLDOUT": "18575b4dbbd422d53ad00ec3a20005e6809d7472126de4e111918466ecb2a9ef",
}
EXPECTED_E10_SHA256 = "2bd6d977f29aa80bb0bcbea083e5260230ed371188e7037c73dd4b56394019c4"
COHORT_ORDER: tuple[str, ...] = (*tuple(f"FOLD_{i}" for i in range(1, 6)), "HOLDOUT")
CANDIDATE_ORDER: tuple[str, ...] = (DIRECT_GOLD, E10)
FOLD_CANDIDATES: tuple[str, ...] = (DIRECT_GOLD,)
HOLDOUT_CANDIDATES: tuple[str, ...] = (DIRECT_GOLD, E10)
RUN_QUANTILES: tuple[int, ...] = (5, 10, 25, 50, 75, 90, 95)
RUN_INTERVAL_LEVELS: tuple[float, ...] = (0.50, 0.80, 0.90, 0.95)
_CONTEXT_FEATURES = tuple(CANONICAL_CONTEXT) + ("context_top_bottom",)
_BATTER_FEATURES = tuple(
    name
    for name in GOLD_FEATURES
    if (name.startswith("batter_") or name.startswith("matchup_batter_"))
    and name != "matchup_batter_bats_left"
)
_PITCHER_FEATURES = tuple(
    name
    for name in GOLD_FEATURES
    if name.startswith("pitcher_") or name.startswith("matchup_pitcher_")
)
_MATCHUP_FEATURES = (
    "matchup_batter_bats_left",
    "matchup_batter_bats_switch",
    "matchup_batter_hand_missing",
    "matchup_pitcher_throws_left",
    "matchup_pitcher_hand_missing",
    "matchup_platoon_advantage",
)


class GameSimulationMarketStudyError(RuntimeError):
    """A fixed Phase 7B6 identity, temporal, or result invariant differed."""


def candidates_for_cohort(cohort_id: str) -> tuple[str, ...]:
    """Return the fixed truthful candidate inventory for one evaluation cohort."""

    if cohort_id not in COHORT_ORDER:
        raise GameSimulationMarketStudyError(f"unknown cohort: {cohort_id}")
    return HOLDOUT_CANDIDATES if cohort_id == "HOLDOUT" else FOLD_CANDIDATES


class PregameFeatureIndex:
    """Compact immutable lookup of governed on-or-before player snapshots."""

    def __init__(self, frame: pd.DataFrame) -> None:
        required = {
            "game_date",
            "batterCanonicalPlayerId",
            "pitcherCanonicalPlayerId",
            "matchup_batter_bats_left",
            *_BATTER_FEATURES,
            *_PITCHER_FEATURES,
        }
        if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
            raise GameSimulationMarketStudyError("Gold feature frame is incomplete")
        self._features: dict[str, tuple[str, ...]] = {
            "batter": _BATTER_FEATURES,
            "pitcher": _PITCHER_FEATURES,
        }
        self._values: dict[str, dict[tuple[str, str], tuple[Any, ...]]] = {}
        self._dates: dict[str, dict[str, tuple[str, ...]]] = {}
        for role, id_column in (
            ("batter", "batterCanonicalPlayerId"),
            ("pitcher", "pitcherCanonicalPlayerId"),
        ):
            features = self._features[role]
            source = frame.loc[:, [id_column, "game_date", *features]].copy()
            source[id_column] = source[id_column].astype(str)
            source["game_date"] = source["game_date"].astype(str)
            if source[id_column].str.strip().eq("").any():
                raise GameSimulationMarketStudyError(f"Gold {role} identity is blank")
            unique = source.drop_duplicates()
            if unique.duplicated([id_column, "game_date"]).any():
                raise GameSimulationMarketStudyError(
                    f"pregame Gold feature snapshot is not invariant for {role} and date"
                )
            values: dict[tuple[str, str], tuple[Any, ...]] = {}
            dates: dict[str, list[str]] = {}
            for row in unique.itertuples(index=False, name=None):
                player, day, *feature_values = row
                key = (str(player), str(day))
                values[key] = tuple(feature_values)
                dates.setdefault(str(player), []).append(str(day))
            self._values[role] = values
            self._dates[role] = {
                player: tuple(sorted(set(player_dates)))
                for player, player_dates in dates.items()
            }

        stance = frame.loc[
            :,
            [
                "batterCanonicalPlayerId",
                "game_date",
                "matchup_batter_bats_left",
                "matchup_batter_hand_missing",
                "matchup_pitcher_throws_left",
                "matchup_pitcher_hand_missing",
            ],
        ].copy()
        stance["batterCanonicalPlayerId"] = stance["batterCanonicalPlayerId"].astype(
            str
        )
        stance["game_date"] = stance["game_date"].astype(str)
        for column in (
            "matchup_batter_bats_left",
            "matchup_batter_hand_missing",
            "matchup_pitcher_throws_left",
            "matchup_pitcher_hand_missing",
        ):
            stance[column] = pd.to_numeric(stance[column], errors="coerce")
        valid = (
            stance["batterCanonicalPlayerId"].str.strip().ne("")
            & stance["matchup_batter_bats_left"].isin((0.0, 1.0))
            & stance["matchup_batter_hand_missing"].eq(0.0)
            & stance["matchup_pitcher_throws_left"].isin((0.0, 1.0))
            & stance["matchup_pitcher_hand_missing"].eq(0.0)
        )
        observations = (
            stance.loc[
                valid,
                [
                    "batterCanonicalPlayerId",
                    "game_date",
                    "matchup_pitcher_throws_left",
                    "matchup_batter_bats_left",
                ],
            ]
            .drop_duplicates()
            .groupby(
                [
                    "batterCanonicalPlayerId",
                    "game_date",
                    "matchup_pitcher_throws_left",
                ],
                sort=False,
                as_index=False,
            )["matchup_batter_bats_left"]
            .agg(["nunique", "first"])
            .reset_index()
        )
        observations = observations.loc[observations["nunique"].eq(1)].copy()
        by_hand: dict[tuple[str, int], list[tuple[str, int]]] = {}
        by_career: dict[str, list[tuple[str, int, int]]] = {}
        for row in observations.itertuples(index=False):
            player = str(row.batterCanonicalPlayerId)
            day = str(row.game_date)
            pitcher_hand = int(row.matchup_pitcher_throws_left)
            bats_left = int(row.first)
            by_hand.setdefault((player, pitcher_hand), []).append((day, bats_left))
            by_career.setdefault(player, []).append((day, bats_left, pitcher_hand))
        self._stance_by_hand: dict[
            tuple[str, int], tuple[tuple[str, ...], tuple[int, ...]]
        ] = {}
        for key, raw in by_hand.items():
            ordered = tuple(sorted(raw))
            self._stance_by_hand[key] = (
                tuple(item[0] for item in ordered),
                tuple(item[1] for item in ordered),
            )
        self._stance_career: dict[
            str,
            tuple[tuple[str, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]],
        ] = {}
        for player, raw in by_career.items():
            ordered = tuple(sorted(raw))
            prefix_masks: list[int] = []
            mask = 0
            for _day, bats_left, _pitcher_hand in ordered:
                mask |= 1 << bats_left
                prefix_masks.append(mask)
            self._stance_career[player] = (
                tuple(item[0] for item in ordered),
                tuple(item[1] for item in ordered),
                tuple(item[2] for item in ordered),
                tuple(prefix_masks),
            )

    def lookup(
        self, *, player_id: str, score_date: str, role: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if role not in self._features:
            raise ValueError("role must be batter or pitcher")
        player = str(player_id)
        days = self._dates[role].get(player, ())
        score_day = str(score_date)
        # A Gold row dated on the game date is an authorized pre-PA snapshot: its
        # player features were themselves built only from completed prior history.
        # Keep that established lookup contract and use an empty-history batter
        # representation only when no on-or-before snapshot exists at all.
        position = bisect_right(days, score_day) - 1
        if position < 0:
            if role == "batter":
                cold_start = {name: float("nan") for name in self._features[role]}
                cold_start.update(
                    {
                        "batter_prior_missing": 1.0,
                        "batter_prior_pa_count": 0.0,
                        "batter_last100_pa_count": 0.0,
                        "batter_last100_insufficient": 1.0,
                        "batter_last100_whiff_missing": 1.0,
                        "matchup_batter_bats_switch": 0.0,
                        "matchup_batter_hand_missing": 1.0,
                    }
                )
                return cold_start, {
                    "playerId": player,
                    "role": "BATTER",
                    "sourceKind": "ROLE_COLD_START_NO_PRIOR_GOLD_SNAPSHOT",
                    "sourceDate": None,
                    "scoreDate": score_day,
                    "sameDayStrictPriorFeatureSnapshot": False,
                    "fallbackDays": None,
                    "sameDayRowsUsed": 0,
                    "futureRowsUsed": 0,
                    "coldStart": True,
                }
            raise GameSimulationMarketStudyError(
                f"no pregame Gold feature snapshot for {role} {player} on {score_date}"
            )
        source_date = days[position]
        if source_date > score_day:
            raise GameSimulationMarketStudyError(
                "pregame Gold feature snapshot is after the score date"
            )
        values = self._values[role][(player, source_date)]
        row = dict(zip(self._features[role], values, strict=True))
        fallback = int((pd.Timestamp(score_date) - pd.Timestamp(source_date)).days)
        return row, {
            "playerId": player,
            "role": role.upper(),
            "sourceKind": (
                "TARGET_DATE_GOVERNED_GOLD_SNAPSHOT"
                if fallback == 0
                else "MOST_RECENT_PRIOR_GOLD_SNAPSHOT"
            ),
            "sourceDate": source_date,
            "scoreDate": score_day,
            "sameDayStrictPriorFeatureSnapshot": fallback == 0,
            "fallbackDays": fallback,
            "sameDayRowsUsed": 0,
            "futureRowsUsed": 0,
            "coldStart": False,
        }

    def lookup_batter_stance(
        self,
        *,
        batter_id: str,
        score_date: str,
        opposing_pitcher_throws_left: Any,
        opposing_pitcher_hand_missing: Any,
    ) -> tuple[dict[str, int], dict[str, Any]]:
        """Resolve realized stance using observations strictly before ``score_date``."""

        player = str(batter_id)
        day = str(score_date)
        try:
            pitcher_left_value = float(opposing_pitcher_throws_left)
            pitcher_missing_value = float(opposing_pitcher_hand_missing)
        except (TypeError, ValueError) as exc:
            raise GameSimulationMarketStudyError(
                "announced starter hand evidence is invalid"
            ) from exc
        if (
            not math.isfinite(pitcher_left_value)
            or not math.isfinite(pitcher_missing_value)
            or pitcher_left_value not in (0.0, 1.0)
            or pitcher_missing_value not in (0.0, 1.0)
        ):
            raise GameSimulationMarketStudyError(
                "announced starter hand evidence is invalid"
            )
        announced_hand = int(pitcher_left_value)

        def result(
            *,
            bats_left: int,
            hand_missing: int,
            source_kind: str,
            source_date: str | None,
            source_pitcher_hand: int | None,
        ) -> tuple[dict[str, int], dict[str, Any]]:
            if source_date is not None and not source_date < day:
                raise GameSimulationMarketStudyError(
                    "batter stance evidence is not strictly prior"
                )
            return (
                {
                    "matchup_batter_bats_left": bats_left,
                    "matchup_batter_hand_missing": hand_missing,
                },
                {
                    "batterId": player,
                    "scoreDate": day,
                    "announcedPitcherThrowsLeft": announced_hand,
                    "sourceKind": source_kind,
                    "sourceDate": source_date,
                    "sourcePitcherThrowsLeft": source_pitcher_hand,
                    "strictlyPrior": source_date is not None,
                    "sameDayRowsUsed": 0,
                    "futureRowsUsed": 0,
                    "batsLeft": bats_left,
                    "handMissing": hand_missing,
                },
            )

        if pitcher_missing_value == 1.0:
            return result(
                bats_left=0,
                hand_missing=1,
                source_kind="ANNOUNCED_STARTER_HAND_MISSING",
                source_date=None,
                source_pitcher_hand=None,
            )

        hand_dates, hand_values = self._stance_by_hand.get(
            (player, announced_hand), ((), ())
        )
        hand_position = bisect_left(hand_dates, day) - 1
        if hand_position >= 0:
            return result(
                bats_left=hand_values[hand_position],
                hand_missing=0,
                source_kind="MOST_RECENT_PRIOR_SAME_PITCHER_HAND",
                source_date=hand_dates[hand_position],
                source_pitcher_hand=announced_hand,
            )

        career_dates, career_values, career_hands, prefix_masks = (
            self._stance_career.get(player, ((), (), (), ()))
        )
        career_position = bisect_left(career_dates, day) - 1
        if career_position >= 0 and prefix_masks[career_position] in (1, 2):
            return result(
                bats_left=career_values[career_position],
                hand_missing=0,
                source_kind="SINGLE_UNAMBIGUOUS_PRIOR_CAREER_STANCE",
                source_date=career_dates[career_position],
                source_pitcher_hand=career_hands[career_position],
            )
        return result(
            bats_left=0,
            hand_missing=1,
            source_kind="PRIOR_CAREER_STANCE_AMBIGUOUS_OR_UNAVAILABLE",
            source_date=None,
            source_pitcher_hand=None,
        )


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(_json_safe(value)))


def _artifact_bytes(study_root: Path, relative: str, expected_sha: str) -> bytes:
    evidence = (
        json.loads((study_root / "manifest.json").read_text(encoding="utf-8"))
        .get("artifacts", {})
        .get(relative)
    )
    if not isinstance(evidence, Mapping) or evidence.get("sha256") != expected_sha:
        raise GameSimulationMarketStudyError(
            f"persisted artifact authority differs: {relative}"
        )
    path = (study_root / relative).resolve()
    if (
        study_root.resolve() not in path.parents
        or not path.is_file()
        or path.is_symlink()
    ):
        raise GameSimulationMarketStudyError(
            f"persisted artifact path differs: {relative}"
        )
    content = path.read_bytes()
    if (
        len(content) != int(evidence.get("bytes", -1))
        or _sha256_bytes(content) != expected_sha
    ):
        raise GameSimulationMarketStudyError(
            f"persisted artifact bytes differ: {relative}"
        )
    return content


def load_frozen_models(
    study_root: Path, cohort_id: str
) -> tuple[FittedFixedModel, FittedWalkForwardStacker | None, dict[str, Any]]:
    """Load the hash-pinned Direct artifact and E10 only for the final holdout."""

    if cohort_id not in COHORT_ORDER:
        raise GameSimulationMarketStudyError(f"unknown cohort: {cohort_id}")
    root = Path(study_root).resolve()
    if root.name != EXPECTED_STUDY_SHA256:
        raise GameSimulationMarketStudyError("Phase 7B5 study identity differs")
    direct_name = (
        "models/final-direct48.joblib"
        if cohort_id == "HOLDOUT"
        else f"models/{cohort_id}-direct48.joblib"
    )
    direct_bytes = _artifact_bytes(
        root, direct_name, EXPECTED_DIRECT_MODEL_SHA256[cohort_id]
    )
    direct = joblib.load(io.BytesIO(direct_bytes))
    if (
        type(direct) is not FittedFixedModel
        or tuple(direct.feature_names) != tuple(GOLD_FEATURES)
        or direct.preprocessor is None
    ):
        raise GameSimulationMarketStudyError(
            "frozen Direct Gold artifact contract differs"
        )
    evidence: dict[str, Any] = {
        "direct": {
            "relativePath": direct_name,
            "sha256": EXPECTED_DIRECT_MODEL_SHA256[cohort_id],
        }
    }
    if cohort_id != "HOLDOUT":
        return direct, None, evidence

    e10_bytes = _artifact_bytes(root, "models/e10-stacker.joblib", EXPECTED_E10_SHA256)
    stacker = joblib.load(io.BytesIO(e10_bytes))
    if type(stacker) is not FittedWalkForwardStacker:
        raise GameSimulationMarketStudyError("frozen E10 artifact contract differs")
    if not np.array_equal(
        np.asarray(stacker.estimator.classes_, dtype=np.int64),
        np.arange(len(PA_CLASS_ORDER), dtype=np.int64),
    ):
        raise GameSimulationMarketStudyError("frozen E10 class order differs")
    evidence["e10"] = {
        "relativePath": "models/e10-stacker.joblib",
        "sha256": EXPECTED_E10_SHA256,
        "evaluationScope": "FINAL_UNTOUCHED_HOLDOUT_ONLY",
    }
    return direct, stacker, evidence


def require_strict_chronological_e10_oof(study_root: Path) -> None:
    """Reject the accepted single meta-fitted E10 as five-fold OOF evidence.

    Phase 7B5 fitted one E10 stacker after concatenating all five OOF component
    blocks and their labels.  That artifact is valid for the later untouched
    holdout, but it is not out-of-fold with respect to any of the five rows used
    to fit it.  Phase 7B6 explicitly requires chronological five-fold E10 inputs,
    so the game study must stop before simulation rather than relabel those rows.
    """

    root = Path(study_root).resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GameSimulationMarketStudyError(
            "Phase 7B5 manifest is invalid before E10 OOF verification"
        ) from exc
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise GameSimulationMarketStudyError(
            "Phase 7B5 artifact inventory is missing before E10 OOF verification"
        )
    combined = "models/e10-stacker.joblib"
    per_fold = tuple(f"models/FOLD_{index}-e10-stacker.joblib" for index in range(1, 6))
    if combined in artifacts and not all(
        relative in artifacts for relative in per_fold
    ):
        raise GameSimulationMarketStudyError(
            "PHASE7B6_E10_CHRONOLOGICAL_OOF_UNAVAILABLE: the accepted E10 stacker "
            "was fit once on the combined five-fold OOF labels; no fold-specific "
            "earlier-only E10 artifacts exist, so FOLD_1..FOLD_5 E10 game results "
            "cannot be reported as strictly out-of-fold"
        )
    raise GameSimulationMarketStudyError(
        "PHASE7B6_E10_CHRONOLOGICAL_OOF_UNVERIFIED: no governed verifier for "
        "fold-specific earlier-only E10 artifacts exists"
    )


def load_transition_sampler(
    repository_root: Path,
) -> tuple[FastTransitionSampler, dict[str, Any]]:
    """Load the exact existing Phase 5 transition model without touching season data."""

    root = Path(repository_root).resolve()
    authority = (
        root / ".runtime" / "asp-model-studio" / "sports-phase5" / "base-out-transition"
    )
    matches = tuple(
        sorted(
            authority.glob(
                f"*model-sha256-{EXPECTED_TRANSITION_MODEL_SHA256[:16]}.json"
            )
        )
    )
    if len(matches) != 1 or matches[0].is_symlink():
        raise GameSimulationMarketStudyError("transition model path authority differs")
    content = matches[0].read_bytes()
    if _sha256_bytes(content) != EXPECTED_TRANSITION_MODEL_SHA256:
        raise GameSimulationMarketStudyError("transition model bytes differ")
    try:
        model = bt.TransitionModel.from_dict(json.loads(content.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise GameSimulationMarketStudyError("transition model is invalid") from exc
    return FastTransitionSampler(model), {
        "contract": "MLB_BASE_OUT_TRANSITION_MODEL_V1",
        "sha256": EXPECTED_TRANSITION_MODEL_SHA256,
        "bytes": len(content),
        "path": str(matches[0]),
    }


def _player_feature_row(
    index: PregameFeatureIndex,
    *,
    player_id: str,
    score_date: str,
    role: str,
) -> tuple[pd.Series, dict[str, Any]]:
    values, evidence = index.lookup(
        player_id=player_id, score_date=score_date, role=role
    )
    return pd.Series(values), evidence


def _platoon_advantage(row: Mapping[str, Any]) -> float:
    batter_missing = float(row["matchup_batter_hand_missing"]) != 0.0
    pitcher_missing = float(row["matchup_pitcher_hand_missing"]) != 0.0
    if batter_missing or pitcher_missing:
        return 0.0
    batter_left = float(row["matchup_batter_bats_left"]) != 0.0
    batter_switch = float(row["matchup_batter_bats_switch"]) != 0.0
    pitcher_left = float(row["matchup_pitcher_throws_left"]) != 0.0
    return float(batter_switch or (batter_left != pitcher_left))


def build_pregame_templates(
    gold_frame: pd.DataFrame | PregameFeatureIndex,
    game: PregameGame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Build 18 starting-matchup rows from governed pregame Gold features."""

    index = (
        gold_frame
        if isinstance(gold_frame, PregameFeatureIndex)
        else PregameFeatureIndex(gold_frame)
    )
    if int(game.season) not in {2022, 2023, 2024} or str(game.game_date)[:4] in {
        "2025",
        "2026",
    }:
        raise GameSimulationMarketStudyError("pregame template season is prohibited")
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    stance_sources: list[dict[str, Any]] = []
    sides = (
        ("AWAY", game.away.batting_order, game.home.starting_pitcher_id, 0),
        ("HOME", game.home.batting_order, game.away.starting_pitcher_id, 1),
    )
    for side, batting_order, opposing_starter, top_bottom in sides:
        if len(batting_order) != 9 or len(set(batting_order)) != 9:
            raise GameSimulationMarketStudyError(
                "starting batting order is not exactly nine unique players"
            )
        pitcher, pitcher_evidence = _player_feature_row(
            index,
            player_id=opposing_starter,
            score_date=game.game_date,
            role="pitcher",
        )
        sources.append(pitcher_evidence)
        for slot, batter_id in enumerate(batting_order, start=1):
            batter, batter_evidence = _player_feature_row(
                index,
                player_id=batter_id,
                score_date=game.game_date,
                role="batter",
            )
            sources.append(batter_evidence)
            stance, stance_evidence = index.lookup_batter_stance(
                batter_id=str(batter_id),
                score_date=game.game_date,
                opposing_pitcher_throws_left=pitcher["matchup_pitcher_throws_left"],
                opposing_pitcher_hand_missing=pitcher["matchup_pitcher_hand_missing"],
            )
            stance_sources.append(stance_evidence)
            values: dict[str, Any] = {
                "plate_appearance_id": (
                    f"phase7b6:pregame:{game.canonical_game_id}:{side.lower()}:{slot}"
                ),
                "game_id": game.prediction_game_id,
                "batting_side": side,
                "batting_order_slot": slot,
                "batterCanonicalPlayerId": str(batter_id),
                "pitcherCanonicalPlayerId": str(opposing_starter),
                **dict(CANONICAL_CONTEXT),
                "context_top_bottom": top_bottom,
            }
            for feature in GOLD_FEATURES:
                if feature in values:
                    continue
                if feature == "matchup_batter_bats_left":
                    continue
                if feature.startswith("batter_") or feature.startswith(
                    "matchup_batter_"
                ):
                    values[feature] = batter[feature]
                elif feature.startswith("pitcher_") or feature.startswith(
                    "matchup_pitcher_"
                ):
                    values[feature] = pitcher[feature]
                elif feature == "matchup_platoon_advantage":
                    continue
                else:
                    raise GameSimulationMarketStudyError(
                        f"unassigned Gold feature: {feature}"
                    )
            values.update(stance)
            values["matchup_platoon_advantage"] = _platoon_advantage(values)
            rows.append(values)
    template = pd.DataFrame(rows).loc[:, list(TEMPLATE_COLUMNS)]
    state_frame = template.loc[
        :,
        ["plate_appearance_id", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId"],
    ].copy()
    state_frame.insert(1, "game_date", game.game_date)
    fallback_days = [
        int(item["fallbackDays"])
        for item in sources
        if item["fallbackDays"] is not None
    ]
    cold_start_sources = [item for item in sources if bool(item.get("coldStart"))]
    return (
        template,
        state_frame,
        {
            "sourcePolicy": (
                "TARGET_DATE_GOVERNED_GOLD_SNAPSHOT_ELSE_LATEST_PRIOR_"
                "PLAYER_SNAPSHOT_ELSE_ROLE_COLD_START"
            ),
            "sourceRecords": len(sources),
            "sameDaySourceRecords": int(sum(value == 0 for value in fallback_days)),
            "priorFallbackSourceRecords": int(
                sum(value > 0 for value in fallback_days)
            ),
            "coldStartSourceRecords": len(cold_start_sources),
            "coldStartPlayerFeatureEvidence": cold_start_sources,
            "playerFeatureSameDayRowsUsed": int(
                sum(int(item["sameDayRowsUsed"]) for item in sources)
            ),
            "playerFeatureFutureRowsUsed": int(
                sum(int(item["futureRowsUsed"]) for item in sources)
            ),
            "maximumFallbackDays": max(fallback_days, default=0),
            "batterStancePolicy": (
                "STRICTLY_PRIOR_OBSERVED_STANCE_BY_BATTER_AND_ANNOUNCED_PITCHER_HAND_"
                "ELSE_SINGLE_UNAMBIGUOUS_PRIOR_CAREER_STANCE_ELSE_MISSING"
            ),
            "batterStanceLookups": len(stance_sources),
            "batterStanceSourceCounts": dict(
                sorted(Counter(item["sourceKind"] for item in stance_sources).items())
            ),
            "batterStanceSameDayRowsUsed": int(
                sum(int(item["sameDayRowsUsed"]) for item in stance_sources)
            ),
            "batterStanceFutureRowsUsed": int(
                sum(int(item["futureRowsUsed"]) for item in stance_sources)
            ),
            "batterStanceEvidence": stance_sources,
            "batterSwitchFeaturePolicy": "FROZEN_GOLD_VALUE_NO_INFERENCE",
            "actualSubstitutionRowsUsed": 0,
            "actualRelieverRowsUsed": 0,
            "outcomeColumnsRead": 0,
        },
    )


def _dummy_contribs() -> GameContribs:
    zeros = np.zeros((MAX_TEAM_PA, len(PA_CLASS_ORDER)), dtype=np.float64)
    zeros.setflags(write=False)
    return GameContribs(zeros, zeros, zeros, zeros, DEFAULT_REGULATION)


def _frozen_probability_cards(values: Any) -> np.ndarray:
    matrix = validate_probability_matrix(values, class_order=PA_CLASS_ORDER)
    if matrix.shape != (LINEUP_SIZE, len(PA_CLASS_ORDER)):
        raise GameSimulationMarketStudyError(
            "pregame Direct probability-card shape differs"
        )
    contiguous = np.ascontiguousarray(matrix, dtype=np.float64)
    return np.frombuffer(contiguous.tobytes(), dtype=np.float64).reshape(
        contiguous.shape
    )


def _direct_only_provider(
    template: pd.DataFrame,
    canonical_direct: np.ndarray,
) -> tuple[StartingLineupProbabilityProvider, dict[str, Any]]:
    """Build the fold-only Direct provider without evaluating the E10 stacker."""

    matrix = validate_probability_matrix(canonical_direct, class_order=PA_CLASS_ORDER)
    if matrix.shape != (2 * LINEUP_SIZE, len(PA_CLASS_ORDER)):
        raise GameSimulationMarketStudyError(
            "canonical pregame Direct scoring shape differs"
        )
    row_ids = tuple(template["plate_appearance_id"].astype(str).tolist())
    away_batters = tuple(
        template.iloc[:LINEUP_SIZE]["batterCanonicalPlayerId"].astype(str).tolist()
    )
    home_batters = tuple(
        template.iloc[LINEUP_SIZE:]["batterCanonicalPlayerId"].astype(str).tolist()
    )
    home_starters = tuple(
        template.iloc[:LINEUP_SIZE]["pitcherCanonicalPlayerId"].astype(str).unique()
    )
    away_starters = tuple(
        template.iloc[LINEUP_SIZE:]["pitcherCanonicalPlayerId"].astype(str).unique()
    )
    if (
        len(row_ids) != 2 * LINEUP_SIZE
        or len(set(row_ids)) != len(row_ids)
        or len(away_batters) != LINEUP_SIZE
        or len(set(away_batters)) != LINEUP_SIZE
        or len(home_batters) != LINEUP_SIZE
        or len(set(home_batters)) != LINEUP_SIZE
        or len(home_starters) != 1
        or len(away_starters) != 1
    ):
        raise GameSimulationMarketStudyError(
            "Direct-only pregame participant identity differs"
        )
    provider = StartingLineupProbabilityProvider(
        candidate_id=DIRECT_GOLD,
        away_cards=_frozen_probability_cards(matrix[:LINEUP_SIZE]),
        home_cards=_frozen_probability_cards(matrix[LINEUP_SIZE:]),
        away_batter_ids=away_batters,
        home_batter_ids=home_batters,
        away_announced_starter_id=away_starters[0],
        home_announced_starter_id=home_starters[0],
    )
    record = {
        "schemaVersion": ADAPTER_SCHEMA_VERSION,
        "gameId": str(template.iloc[0]["game_id"]),
        "templateRowCount": 2 * LINEUP_SIZE,
        "rowIds": list(row_ids),
        "classOrder": list(PA_CLASS_ORDER),
        "cardShapePerSide": [LINEUP_SIZE, len(PA_CLASS_ORDER)],
        "canonicalPregameContext": {
            **dict(CANONICAL_CONTEXT),
            "awayContextTopBottom": 0,
            "homeContextTopBottom": 1,
        },
        "battingOrderPolicy": "STARTING_LINEUP_CYCLED",
        "pitcherPolicy": "ANNOUNCED_STARTER_HELD_CONSTANT",
        "substitutionsUsed": False,
        "actualRelieversUsed": False,
        "targetOutcomeColumnsAccepted": False,
        "targetContextValuesRead": False,
        "candidateInventory": [DIRECT_GOLD],
        "e10Evaluated": False,
        "researchLimitation": (
            "STATIC_CANONICAL_PREGAME_CARDS_CYCLE_STARTERS_ONLY_AND_DO_NOT_"
            "MODEL_SUBSTITUTIONS_RELIEVERS_FATIGUE_OR_TIMES_THROUGH_ORDER"
        ),
    }
    return provider, record


def _discrete_distribution(values: np.ndarray, *, key: str) -> list[dict[str, Any]]:
    counts = Counter(int(value) for value in np.asarray(values).tolist())
    total = int(sum(counts.values()))
    return [
        {key: value, "count": count, "probability": count / total}
        for value, count in sorted(counts.items())
    ]


def _joint_distribution(away: np.ndarray, home: np.ndarray) -> list[dict[str, Any]]:
    counts = Counter(
        zip(np.asarray(away).tolist(), np.asarray(home).tolist(), strict=True)
    )
    total = int(sum(counts.values()))
    return [
        {
            "awayRuns": int(pair[0]),
            "homeRuns": int(pair[1]),
            "count": count,
            "probability": count / total,
        }
        for pair, count in sorted(counts.items())
    ]


def _distribution_uncertainty(values: np.ndarray) -> dict[str, Any]:
    sample = np.asarray(values, dtype=np.float64)
    if sample.ndim != 1 or sample.size == 0 or not np.isfinite(sample).all():
        raise GameSimulationMarketStudyError("run uncertainty sample is invalid")
    quantiles = {
        f"p{percentile}": float(np.percentile(sample, percentile))
        for percentile in RUN_QUANTILES
    }
    intervals = []
    for level in RUN_INTERVAL_LEVELS:
        tail = (1.0 - level) / 2.0
        intervals.append(
            {
                "nominalCoverage": level,
                "lower": float(np.quantile(sample, tail)),
                "upper": float(np.quantile(sample, 1.0 - tail)),
            }
        )
    return {
        "method": "EMPIRICAL_MONTE_CARLO_DRAWS",
        "drawCount": int(sample.size),
        "standardDeviation": float(sample.std(ddof=0)),
        "quantiles": quantiles,
        "centralPredictionIntervals": intervals,
    }


def _stability(result: GameSimResult) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for count in STABILITY_PREFIXES:
        if count > result.n_sims:
            continue
        away = np.asarray(result.away_runs[:count], dtype=np.float64)
        home = np.asarray(result.home_runs[:count], dtype=np.float64)
        rows.append(
            {
                "simulations": count,
                "homeWinProbability": float(np.mean(home > away)),
                "expectedAwayRuns": float(away.mean()),
                "expectedHomeRuns": float(home.mean()),
                "expectedTotalRuns": float((away + home).mean()),
                "expectedRunDifference": float((home - away).mean()),
            }
        )
    final = rows[-1]
    return {
        "prefixes": rows,
        "maximumAbsoluteDriftVsFinal": {
            field: max(abs(float(row[field]) - float(final[field])) for row in rows)
            for field in (
                "homeWinProbability",
                "expectedAwayRuns",
                "expectedHomeRuns",
                "expectedTotalRuns",
                "expectedRunDifference",
            )
        },
    }


def summarize_game_simulation(
    result: GameSimResult,
    *,
    cohort_id: str,
    candidate_id: str,
    game: PregameGame,
    truth: GameTruth,
    adapter_record: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert one raw simulation into distributions plus evaluation truth."""

    if result.game_id != game.prediction_game_id or result.n_sims <= 0:
        raise GameSimulationMarketStudyError("simulation result identity differs")
    away = np.asarray(result.away_runs, dtype=np.int64)
    home = np.asarray(result.home_runs, dtype=np.int64)
    if away.shape != (result.n_sims,) or home.shape != away.shape:
        raise GameSimulationMarketStudyError("simulation score arrays differ")
    first_mask = result.first_five_complete
    if (
        result.nonterminated != 0
        or result.illegal_states != 0
        or np.any(away == home)
        or first_mask.shape != (result.n_sims,)
        or not first_mask.all()
    ):
        raise GameSimulationMarketStudyError(
            "simulation did not terminate legally with complete first-five evidence"
        )
    first_away = np.asarray(result.first_five_away_runs[first_mask], dtype=np.int64)
    first_home = np.asarray(result.first_five_home_runs[first_mask], dtype=np.int64)
    if first_away.size == 0:
        raise GameSimulationMarketStudyError(
            "simulation produced no first-five snapshots"
        )
    return {
        "schemaVersion": "MLB_GOLD_GAME_SIMULATION_RESULT_V1",
        "cohortId": cohort_id,
        "candidateId": candidate_id,
        "canonicalGameId": game.canonical_game_id,
        "predictionGameId": game.prediction_game_id,
        "awayTeamId": game.away.canonical_team_id,
        "homeTeamId": game.home.canonical_team_id,
        "gameDate": game.game_date,
        "season": game.season,
        "nSimulations": result.n_sims,
        "classOrder": list(PA_CLASS_ORDER),
        "pregamePolicy": dict(adapter_record),
        "homeWinProbability": float(np.mean(home > away)),
        "awayWinProbability": float(np.mean(away > home)),
        "expectedHomeRuns": float(home.mean()),
        "expectedAwayRuns": float(away.mean()),
        "expectedTotalRuns": float((away + home).mean()),
        "expectedRunDifference": float((home - away).mean()),
        "awayRunDistribution": _discrete_distribution(away, key="awayRuns"),
        "homeRunDistribution": _discrete_distribution(home, key="homeRuns"),
        "jointScoreDistribution": _joint_distribution(away, home),
        "runDifferenceDistribution": _discrete_distribution(
            home - away, key="homeMinusAway"
        ),
        "totalRunsDistribution": _discrete_distribution(home + away, key="totalRuns"),
        "runUncertainty": {
            "awayRuns": _distribution_uncertainty(away),
            "homeRuns": _distribution_uncertainty(home),
            "totalRuns": _distribution_uncertainty(home + away),
            "homeMinusAwayRuns": _distribution_uncertainty(home - away),
        },
        "firstFive": {
            "completedSimulations": int(first_mask.sum()),
            "completionRate": float(first_mask.mean()),
            "homeWinProbability": float(np.mean(first_home > first_away)),
            "awayWinProbability": float(np.mean(first_away > first_home)),
            "tieProbability": float(np.mean(first_home == first_away)),
            "expectedHomeRuns": float(first_home.mean()),
            "expectedAwayRuns": float(first_away.mean()),
            "expectedTotalRuns": float((first_home + first_away).mean()),
            "expectedRunDifference": float((first_home - first_away).mean()),
            "awayRunDistribution": _discrete_distribution(first_away, key="awayRuns"),
            "homeRunDistribution": _discrete_distribution(first_home, key="homeRuns"),
            "jointScoreDistribution": _joint_distribution(first_away, first_home),
            "runDifferenceDistribution": _discrete_distribution(
                first_home - first_away, key="homeMinusAway"
            ),
            "totalRunsDistribution": _discrete_distribution(
                first_home + first_away, key="totalRuns"
            ),
            "runUncertainty": {
                "awayRuns": _distribution_uncertainty(first_away),
                "homeRuns": _distribution_uncertainty(first_home),
                "totalRuns": _distribution_uncertainty(first_home + first_away),
                "homeMinusAwayRuns": _distribution_uncertainty(first_home - first_away),
            },
        },
        "truth": {
            "awayRuns": truth.away_runs,
            "homeRuns": truth.home_runs,
            "homeWon": truth.home_runs > truth.away_runs,
            "firstFiveAvailable": truth.first_five_available,
            "firstFiveAwayRuns": truth.first_five_away_runs,
            "firstFiveHomeRuns": truth.first_five_home_runs,
            "firstFiveSource": truth.first_five_source,
        },
        "simulationStability": _stability(result),
        "nonterminated": int(result.nonterminated),
        "illegalStates": int(result.illegal_states),
    }


def _calibration_bins(
    y: np.ndarray, probability: np.ndarray, bins: int = 10
) -> dict[str, Any]:
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows: list[dict[str, Any]] = []
    ece = 0.0
    for index in range(bins):
        mask = (probability >= edges[index]) & (
            probability <= edges[index + 1]
            if index == bins - 1
            else probability < edges[index + 1]
        )
        if not mask.any():
            continue
        predicted = float(probability[mask].mean())
        observed = float(y[mask].mean())
        count = int(mask.sum())
        ece += count / len(y) * abs(predicted - observed)
        rows.append(
            {
                "lower": float(edges[index]),
                "upper": float(edges[index + 1]),
                "count": count,
                "meanPrediction": predicted,
                "observedHomeWinRate": observed,
            }
        )
    return {
        "method": "FIXED_10_EQUAL_WIDTH_HOME_WIN_BINS",
        "ece": float(ece),
        "bins": rows,
    }


def game_level_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate one candidate over an exact game inventory."""

    if not records:
        raise GameSimulationMarketStudyError("game metric population is empty")
    ids = [str(row["canonicalGameId"]) for row in records]
    if len(ids) != len(set(ids)):
        raise GameSimulationMarketStudyError(
            "game metric population contains duplicates"
        )
    p_home = np.asarray(
        [row["homeWinProbability"] for row in records], dtype=np.float64
    )
    y_home = np.asarray([row["truth"]["homeWon"] for row in records], dtype=np.float64)
    if not np.isfinite(p_home).all() or np.any((p_home < 0.0) | (p_home > 1.0)):
        raise GameSimulationMarketStudyError("moneyline probabilities are invalid")
    clipped = np.clip(p_home, 1e-15, 1.0 - 1e-15)
    away_truth = np.asarray(
        [row["truth"]["awayRuns"] for row in records], dtype=np.float64
    )
    home_truth = np.asarray(
        [row["truth"]["homeRuns"] for row in records], dtype=np.float64
    )
    away_pred = np.asarray(
        [row["expectedAwayRuns"] for row in records], dtype=np.float64
    )
    home_pred = np.asarray(
        [row["expectedHomeRuns"] for row in records], dtype=np.float64
    )
    first = [row for row in records if bool(row["truth"]["firstFiveAvailable"])]
    if first:
        first_prob = np.asarray(
            [
                [
                    row["firstFive"]["awayWinProbability"],
                    row["firstFive"]["tieProbability"],
                    row["firstFive"]["homeWinProbability"],
                ]
                for row in first
            ],
            dtype=np.float64,
        )
        first_truth = np.asarray(
            [
                (
                    0
                    if row["truth"]["firstFiveAwayRuns"]
                    > row["truth"]["firstFiveHomeRuns"]
                    else (
                        2
                        if row["truth"]["firstFiveHomeRuns"]
                        > row["truth"]["firstFiveAwayRuns"]
                        else 1
                    )
                )
                for row in first
            ],
            dtype=np.int64,
        )
        first_one_hot = np.eye(3, dtype=np.float64)[first_truth]
        first_away_truth = np.asarray(
            [row["truth"]["firstFiveAwayRuns"] for row in first], dtype=np.float64
        )
        first_home_truth = np.asarray(
            [row["truth"]["firstFiveHomeRuns"] for row in first], dtype=np.float64
        )
        first_away_pred = np.asarray(
            [row["firstFive"]["expectedAwayRuns"] for row in first], dtype=np.float64
        )
        first_home_pred = np.asarray(
            [row["firstFive"]["expectedHomeRuns"] for row in first], dtype=np.float64
        )
        first_away_error = first_away_pred - first_away_truth
        first_home_error = first_home_pred - first_home_truth
        first_total_error = first_away_error + first_home_error
        first_difference_error = first_home_error - first_away_error
        chosen = np.clip(first_prob[np.arange(len(first)), first_truth], 1e-15, 1.0)
        first_metrics: dict[str, Any] = {
            "availableGames": len(first),
            "coverage": len(first) / len(records),
            "threeWayLogLoss": float(-np.log(chosen).mean()),
            "summedBrier": float(
                np.mean(np.sum((first_prob - first_one_hot) ** 2, axis=1))
            ),
            "winnerTieAccuracy": float(
                np.mean(np.argmax(first_prob, axis=1) == first_truth)
            ),
            "awayRunMae": float(np.mean(np.abs(first_away_error))),
            "homeRunMae": float(np.mean(np.abs(first_home_error))),
            "meanTeamRunMae": float(
                np.mean(np.abs(np.concatenate((first_away_error, first_home_error))))
            ),
            "runDifferenceMae": float(np.mean(np.abs(first_difference_error))),
            "totalRunMae": float(np.mean(np.abs(first_total_error))),
            "awayRunRmse": float(np.sqrt(np.mean(first_away_error**2))),
            "homeRunRmse": float(np.sqrt(np.mean(first_home_error**2))),
            "runDifferenceRmse": float(np.sqrt(np.mean(first_difference_error**2))),
            "totalRunRmse": float(np.sqrt(np.mean(first_total_error**2))),
            "awayRunBias": float(first_away_error.mean()),
            "homeRunBias": float(first_home_error.mean()),
            "runDifferenceBias": float(first_difference_error.mean()),
            "totalRunBias": float(first_total_error.mean()),
        }
    else:
        first_metrics = {
            "availableGames": 0,
            "coverage": 0.0,
            "status": "NOT_ESTIMABLE",
        }
    away_error = away_pred - away_truth
    home_error = home_pred - home_truth
    total_error = away_error + home_error
    difference_error = home_error - away_error
    stability_fields = (
        "homeWinProbability",
        "expectedAwayRuns",
        "expectedHomeRuns",
        "expectedTotalRuns",
        "expectedRunDifference",
    )
    return {
        "gameCount": len(records),
        "moneylineLogLoss": float(
            -np.mean(y_home * np.log(clipped) + (1.0 - y_home) * np.log(1.0 - clipped))
        ),
        "moneylineBrier": float(np.mean((p_home - y_home) ** 2)),
        "calibration": _calibration_bins(y_home, p_home),
        "winnerAccuracy": float(np.mean((p_home >= 0.5) == y_home.astype(bool))),
        "awayRunMae": float(np.mean(np.abs(away_error))),
        "homeRunMae": float(np.mean(np.abs(home_error))),
        "meanTeamRunMae": float(
            np.mean(np.abs(np.concatenate((away_error, home_error))))
        ),
        "runDifferenceMae": float(np.mean(np.abs(difference_error))),
        "totalRunMae": float(np.mean(np.abs(total_error))),
        "awayRunRmse": float(np.sqrt(np.mean(away_error**2))),
        "homeRunRmse": float(np.sqrt(np.mean(home_error**2))),
        "runDifferenceRmse": float(np.sqrt(np.mean(difference_error**2))),
        "totalRunRmse": float(np.sqrt(np.mean(total_error**2))),
        "awayRunBias": float(away_error.mean()),
        "homeRunBias": float(home_error.mean()),
        "runDifferenceBias": float(difference_error.mean()),
        "totalRunBias": float(total_error.mean()),
        "firstFive": first_metrics,
        "simulationStability": {
            field: {
                "meanMaximumAbsoluteDriftVsFinal": float(
                    np.mean(
                        [
                            row["simulationStability"]["maximumAbsoluteDriftVsFinal"][
                                field
                            ]
                            for row in records
                        ]
                    )
                ),
                "maximumAbsoluteDriftVsFinal": float(
                    np.max(
                        [
                            row["simulationStability"]["maximumAbsoluteDriftVsFinal"][
                                field
                            ]
                            for row in records
                        ]
                    )
                ),
            }
            for field in stability_fields
        },
        "nonterminated": int(sum(int(row["nonterminated"]) for row in records)),
        "illegalStates": int(sum(int(row["illegalStates"]) for row in records)),
    }


def unavailable_shadow_board(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return every ordinary and team-specific market slot as honest NO_BET."""

    ordinary_slots = [
        (family, None)
        for family in MARKET_FAMILY_ORDER
        if family is not MarketFamily.TEAM_TOTAL
    ]
    team_total_slots = [
        (MarketFamily.TEAM_TOTAL, str(record["homeTeamId"])),
        (MarketFamily.TEAM_TOTAL, str(record["awayTeamId"])),
    ]
    slots = [*ordinary_slots, *team_total_slots]
    readiness = {
        "status": "NOT_READY",
        "isReady": False,
        "score": 0,
        "threshold": 100,
        "missingInputs": [
            "SCHEDULED_START_UTC",
            "FORECAST_CUTOFF_UTC",
            "GOVERNED_TIMESTAMPED_TWO_SIDED_QUOTES",
        ],
        "reasonCodes": [
            "HISTORICAL_ODDS_INSUFFICIENT",
            "HISTORICAL_PREGAME_TIMESTAMPS_UNAVAILABLE",
            "NO_GOVERNED_PERSISTED_TWO_SIDED_QUOTE",
            "RESEARCH_SHADOW_ONLY",
        ],
    }
    explanations = [
        {
            "code": "RETROSPECTIVE_RESEARCH_FORECAST",
            "summary": "Research-only game distribution; not a live forecast.",
            "detail": (
                "Probabilities and expected scores come from the governed retrospective "
                "simulation, but scheduled-start and forecast-cutoff timestamps are unavailable."
            ),
        },
        {
            "code": "MARKET_QUOTES_UNAVAILABLE",
            "summary": "No historical market qualification is available.",
            "detail": (
                "No governed persisted timestamped two-sided sportsbook quote exists, so every "
                "market slot is NO_BET with zero stake and no fabricated price."
            ),
        },
    ]

    return {
        "schemaVersion": "MLB_SHADOW_MARKET_BOARD_UNAVAILABLE_V1",
        "canonicalGameId": record["canonicalGameId"],
        "gameDate": record["gameDate"],
        "homeTeamId": record["homeTeamId"],
        "awayTeamId": record["awayTeamId"],
        "matchup": {
            "awayTeamId": record["awayTeamId"],
            "homeTeamId": record["homeTeamId"],
        },
        "scheduledStartUtc": None,
        "scheduledStartAuthority": "UNAVAILABLE",
        "forecastGeneratedAtUtc": None,
        "forecastGeneratedAtAuthority": "UNAVAILABLE_IN_HISTORICAL_SOURCE",
        "forecastCutoffUtc": None,
        "forecastCutoffAuthority": "UNAVAILABLE_IN_HISTORICAL_SOURCE",
        "forecastTimestampAvailable": False,
        "candidateId": record["candidateId"],
        "aspProbabilities": {
            "homeWinProbability": record["homeWinProbability"],
            "awayWinProbability": record["awayWinProbability"],
            "firstFiveHomeWinProbability": record["firstFive"]["homeWinProbability"],
            "firstFiveAwayWinProbability": record["firstFive"]["awayWinProbability"],
            "firstFiveTieProbability": record["firstFive"]["tieProbability"],
        },
        "expectedScore": {
            "home": record["expectedHomeRuns"],
            "away": record["expectedAwayRuns"],
            "total": record["expectedTotalRuns"],
            "homeMinusAway": record["expectedRunDifference"],
            "firstFiveHome": record["firstFive"]["expectedHomeRuns"],
            "firstFiveAway": record["firstFive"]["expectedAwayRuns"],
            "firstFiveTotal": record["firstFive"]["expectedTotalRuns"],
            "firstFiveHomeMinusAway": record["firstFive"]["expectedRunDifference"],
        },
        "uncertainty": {
            "fullGameRuns": record["runUncertainty"],
            "firstFiveRuns": record["firstFive"]["runUncertainty"],
            "simulationStability": record["simulationStability"],
        },
        "readiness": readiness,
        "displayStatus": "RESEARCH_SHADOW_NOT_READY",
        "explanations": explanations,
        "explanation": (
            "Retrospective research distribution is displayable, but historical pregame "
            "timestamps and governed two-sided quotes are unavailable; all markets remain NO_BET."
        ),
        "rows": [
            {
                "marketFamily": family.value,
                "evaluatedMarket": family.value,
                "subjectTeamId": subject_team_id,
                "evaluatedSubjectTeamId": subject_team_id,
                "state": "NO_BET",
                "reasonCodes": [
                    "HISTORICAL_ODDS_INSUFFICIENT",
                    "NO_GOVERNED_PERSISTED_TWO_SIDED_QUOTE",
                ],
                "sportsbookId": None,
                "quoteTimestampUtc": None,
                "selection": None,
                "line": None,
                "price": None,
                "americanOdds": None,
                "decimalOdds": None,
                "noVigProbability": None,
                "edge": None,
                "expectedValuePerUnit": None,
                "aspHomeWinProbability": record["homeWinProbability"],
                "aspAwayWinProbability": record["awayWinProbability"],
                "quarterKellyFraction": None,
                "stakeFraction": 0.0,
                "stakeNormalUnits": 0.0,
                "virtualStakeFraction": 0.0,
                "kellyMultiplier": KELLY_MULTIPLIER,
                "normalUnitFraction": NORMAL_UNIT_FRACTION,
                "maximumPositionFraction": MAX_POSITION_FRACTION,
                "maximumSameGameExposureFraction": MAX_SAME_GAME_EXPOSURE_FRACTION,
                "maximumDailyExposureFraction": MAX_DAILY_EXPOSURE_FRACTION,
                "parlaysAllowed": False,
                "explanation": (
                    "Historical odds are insufficient; price-derived values are null and the "
                    "research-only virtual stake is zero."
                ),
            }
            for family, subject_team_id in slots
        ],
        "sameGameExposureFraction": 0.0,
        "dailyExposureFraction": 0.0,
        "virtualPolicyCaps": {
            "kellyMultiplier": KELLY_MULTIPLIER,
            "normalUnitFraction": NORMAL_UNIT_FRACTION,
            "maximumPositionFraction": MAX_POSITION_FRACTION,
            "maximumSameGameExposureFraction": MAX_SAME_GAME_EXPOSURE_FRACTION,
            "maximumDailyExposureFraction": MAX_DAILY_EXPOSURE_FRACTION,
            "normalUnitIsMinimumStake": False,
            "bankrollAmount": None,
        },
        "maximumSameGameExposureFraction": MAX_SAME_GAME_EXPOSURE_FRACTION,
        "maximumDailyExposureFraction": MAX_DAILY_EXPOSURE_FRACTION,
        "parlaysAllowed": False,
        "shadowOnly": True,
        "historicalRoiReported": False,
        "executionAllowed": False,
    }


def _load_gold_feature_frame(gold_root: Path) -> pd.DataFrame:
    verified = verify_gold(Path(gold_root))
    columns = [
        "canonicalPaId",
        "plate_appearance_id",
        "canonicalGameId",
        "game_id",
        "game_date",
        "season",
        "outcome",
        "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId",
        *GOLD_FEATURES,
    ]
    frame = pq.read_table(Path(verified["path"]), columns=columns).to_pandas()
    if len(frame) != int(verified["rowCount"]) or set(
        pd.to_numeric(frame["season"])
    ) != {2021, 2022, 2023, 2024}:
        raise GameSimulationMarketStudyError("verified Gold feature population differs")
    if frame["plate_appearance_id"].duplicated().any():
        raise GameSimulationMarketStudyError("Gold PA identity is duplicated")
    return frame


def _global_direct_ledger(
    frame: pd.DataFrame,
    inputs: GameSimulationInputs,
) -> ChronologicalDirectLedger:
    lookup = {
        str(value): index
        for index, value in enumerate(frame["plate_appearance_id"].tolist())
    }
    if len(lookup) != len(frame):
        raise GameSimulationMarketStudyError("Gold ledger identity is duplicated")
    initial_cutoff = (
        pd.to_datetime(frame["game_date"]).min() - pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")
    probabilities = np.full(
        (len(frame), len(PA_CLASS_ORDER)), 1.0 / len(PA_CLASS_ORDER), dtype=np.float64
    )
    availability = np.zeros(len(frame), dtype=np.bool_)
    cutoffs = np.full(len(frame), initial_cutoff, dtype=object)
    fold_request = {str(item["foldId"]): item for item in inputs.study.request["folds"]}
    assigned: set[str] = set()
    for cohort_id in COHORT_ORDER[:-1]:
        cohort = inputs.cohorts[cohort_id]
        direct = cohort.probability_matrices[DIRECT_GOLD]
        cutoff = str(fold_request[cohort_id]["trainEnd"])
        for offset, row_id in enumerate(cohort.row_ids):
            if row_id in assigned or row_id not in lookup:
                raise GameSimulationMarketStudyError(
                    "OOF Direct ledger identity differs"
                )
            position = lookup[row_id]
            probabilities[position] = direct[offset]
            availability[position] = True
            cutoffs[position] = cutoff
            assigned.add(row_id)
    if len(assigned) != sum(
        inputs.cohorts[name].row_count for name in COHORT_ORDER[:-1]
    ):
        raise GameSimulationMarketStudyError("OOF Direct ledger reconciliation differs")
    return ChronologicalDirectLedger.aligned(
        frame, probabilities, cutoffs, availability=availability
    )


def _cohort_direct_by_id(cohort: PredictionCohort) -> dict[str, np.ndarray]:
    matrix = validate_probability_matrix(
        cohort.probability_matrices[DIRECT_GOLD], class_order=PA_CLASS_ORDER
    )
    return {row_id: matrix[index] for index, row_id in enumerate(cohort.row_ids)}


def _score_and_advance_observed_day(
    engine: Any,
    day_frame: pd.DataFrame,
    direct_by_id: Mapping[str, np.ndarray],
    cutoff: str,
) -> None:
    ids = tuple(day_frame["plate_appearance_id"].astype(str).tolist())
    try:
        probabilities = np.vstack([direct_by_id[row_id] for row_id in ids])
    except KeyError as exc:
        raise GameSimulationMarketStudyError(
            "daily Direct ledger row is missing"
        ) from exc
    ledger = ChronologicalDirectLedger.aligned(
        day_frame,
        probabilities,
        cutoff,
        availability=np.ones(len(day_frame), dtype=np.bool_),
    )
    engine.score_day(day_frame, ledger)
    engine.advance_day(day_frame)


def _simulate_cohort(
    *,
    cohort: PredictionCohort,
    inputs: GameSimulationInputs,
    frame: pd.DataFrame,
    feature_index: PregameFeatureIndex,
    full_ledger: ChronologicalDirectLedger,
    direct_model: FittedFixedModel,
    e10_stacker: FittedWalkForwardStacker | None,
    transition_sampler: FastTransitionSampler,
    progress: Callable[[str], None],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dates = pd.to_datetime(frame["game_date"], format="%Y-%m-%d", errors="raise")
    training = dates.lt(pd.Timestamp(cohort.start_date)).to_numpy(dtype=np.bool_)
    candidates = candidates_for_cohort(cohort.cohort_id)
    engine = None
    direct_by_id: Mapping[str, np.ndarray] = {}
    cutoff: str | None = None
    if cohort.cohort_id == "HOLDOUT":
        if e10_stacker is None:
            raise GameSimulationMarketStudyError("holdout E10 stacker is missing")
        engine = fit_walk_forward_state(frame, full_ledger, training_mask=training)
        direct_by_id = _cohort_direct_by_id(cohort)
        cutoff = str(inputs.study.request["folds"][-1]["validationEnd"])
    elif e10_stacker is not None:
        raise GameSimulationMarketStudyError(
            "E10 must not be loaded for a five-fold cohort"
        )
    cohort_ids = set(cohort.row_ids)
    target = frame.loc[frame["plate_appearance_id"].astype(str).isin(cohort_ids)].copy()
    if len(target) != cohort.row_count or set(
        target["canonicalGameId"].astype(str)
    ) != set(cohort.canonical_game_ids):
        raise GameSimulationMarketStudyError(
            f"cohort Gold population differs: {cohort.cohort_id}"
        )
    records: list[dict[str, Any]] = []
    templates = 0
    fallback_records = 0
    dummy = _dummy_contribs()
    for score_date in sorted(target["game_date"].astype(str).unique().tolist()):
        day_frame = target.loc[target["game_date"].astype(str).eq(score_date)].copy()
        game_ids = sorted(day_frame["canonicalGameId"].astype(str).unique().tolist())
        progress(f"{cohort.cohort_id} {score_date}: simulate {len(game_ids)} games")
        for canonical_game_id in game_ids:
            game = inputs.games[canonical_game_id]
            truth = inputs.truth[canonical_game_id]
            template, state_frame, template_evidence = build_pregame_templates(
                feature_index, game
            )
            canonical_direct = direct_model.predict_proba(template)
            if cohort.cohort_id == "HOLDOUT":
                assert (
                    engine is not None
                    and cutoff is not None
                    and e10_stacker is not None
                )
                target_ledger = ChronologicalDirectLedger.aligned(
                    state_frame,
                    canonical_direct,
                    cutoff,
                    availability=np.ones(len(state_frame), dtype=np.bool_),
                )
                snapshot = engine.score_snapshot(state_frame, target_ledger)
                adapter = build_pregame_probability_adapter(
                    template,
                    stored_row_ids=tuple(template["plate_appearance_id"].tolist()),
                    stored_components=snapshot.probability_matrices,
                    stored_reliability=snapshot.reliability,
                    direct_model=direct_model,
                    e10_stacker=e10_stacker,
                )
                providers = {
                    candidate: adapter.provider(candidate) for candidate in candidates
                }
                adapter_record = {
                    **adapter.record(),
                    "candidateInventory": list(candidates),
                    "e10Evaluated": True,
                    **template_evidence,
                }
            else:
                provider, direct_record = _direct_only_provider(
                    template, canonical_direct
                )
                providers = {DIRECT_GOLD: provider}
                adapter_record = {**direct_record, **template_evidence}
            templates += 1
            fallback_records += int(template_evidence["priorFallbackSourceRecords"])
            for candidate in candidates:
                result = simulate_game(
                    game_id=game.prediction_game_id,
                    contribs=dummy,
                    fold=None,
                    transition_sampler=transition_sampler,
                    rng_lineage=RngLineage(MASTER_SEED, game.prediction_game_id),
                    n_sims=SIMULATIONS_PER_GAME,
                    check_legality=True,
                    probability_provider=providers[candidate],
                )
                records.append(
                    summarize_game_simulation(
                        result,
                        cohort_id=cohort.cohort_id,
                        candidate_id=candidate,
                        game=game,
                        truth=truth,
                        adapter_record=adapter_record,
                    )
                )
        if engine is not None:
            assert cutoff is not None
            _score_and_advance_observed_day(engine, day_frame, direct_by_id, cutoff)
    expected = EXPECTED_COHORT_GAMES[cohort.cohort_id]
    if templates != expected or len(records) != expected * len(candidates):
        raise GameSimulationMarketStudyError(
            f"cohort game result reconciliation differs: {cohort.cohort_id}"
        )
    return records, {
        "cohortId": cohort.cohort_id,
        "trainingRows": int(training.sum()),
        "scoreRows": cohort.row_count,
        "gameCount": templates,
        "candidateInventory": list(candidates),
        "candidateResultCount": len(records),
        "stateHistoryEndDay": engine.history_end_day if engine is not None else None,
        "stateUse": (
            "D_MINUS_1_E10_HOLDOUT_ONLY"
            if engine is not None
            else "NOT_USED_DIRECT_ONLY_FOLD"
        ),
        "pregameFeatureFallbackRecords": fallback_records,
        "actualSubstitutionsUsed": 0,
        "actualRelieversUsed": 0,
    }


def _metric_groups(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for cohort_id in COHORT_ORDER:
        candidates = candidates_for_cohort(cohort_id)
        output[cohort_id] = {
            candidate: game_level_metrics(
                [
                    row
                    for row in records
                    if row["cohortId"] == cohort_id and row["candidateId"] == candidate
                ]
            )
            for candidate in candidates
        }
    output["FIVE_FOLD_DIRECT_OOF"] = {
        DIRECT_GOLD: game_level_metrics(
            [
                row
                for row in records
                if row["cohortId"] != "HOLDOUT" and row["candidateId"] == DIRECT_GOLD
            ]
        )
    }
    output["DIRECT_ALL_STRICTLY_OUT_OF_SAMPLE"] = {
        DIRECT_GOLD: game_level_metrics(
            [row for row in records if row["candidateId"] == DIRECT_GOLD]
        )
    }
    return output


def paired_holdout_log_loss_bootstrap(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Paired whole-game uncertainty for E10 minus Direct holdout log loss."""

    by_candidate: dict[str, dict[str, Mapping[str, Any]]] = {}
    for candidate in HOLDOUT_CANDIDATES:
        selected = [
            row
            for row in records
            if row["cohortId"] == "HOLDOUT" and row["candidateId"] == candidate
        ]
        mapped = {str(row["canonicalGameId"]): row for row in selected}
        if len(selected) != len(mapped):
            raise GameSimulationMarketStudyError(
                f"holdout bootstrap contains duplicate games for {candidate}"
            )
        by_candidate[candidate] = mapped
    direct = by_candidate[DIRECT_GOLD]
    e10 = by_candidate[E10]
    if set(direct) != set(e10) or len(direct) != EXPECTED_COHORT_GAMES["HOLDOUT"]:
        raise GameSimulationMarketStudyError(
            "paired holdout candidate game inventory differs"
        )
    game_ids = tuple(sorted(direct))
    y = np.asarray(
        [bool(direct[game_id]["truth"]["homeWon"]) for game_id in game_ids],
        dtype=np.float64,
    )
    if any(
        bool(direct[game_id]["truth"]["homeWon"])
        != bool(e10[game_id]["truth"]["homeWon"])
        for game_id in game_ids
    ):
        raise GameSimulationMarketStudyError(
            "paired holdout truth differs by candidate"
        )

    def per_game_loss(candidate_records: Mapping[str, Mapping[str, Any]]) -> np.ndarray:
        probability = np.asarray(
            [candidate_records[game_id]["homeWinProbability"] for game_id in game_ids],
            dtype=np.float64,
        )
        if not np.isfinite(probability).all() or np.any(
            (probability < 0.0) | (probability > 1.0)
        ):
            raise GameSimulationMarketStudyError(
                "paired holdout moneyline probability is invalid"
            )
        clipped = np.clip(probability, 1e-15, 1.0 - 1e-15)
        return -(y * np.log(clipped) + (1.0 - y) * np.log(1.0 - clipped))

    delta = per_game_loss(e10) - per_game_loss(direct)
    rng = np.random.default_rng(COMPARISON_BOOTSTRAP_SEED)
    indices = rng.integers(
        0,
        len(delta),
        size=(COMPARISON_BOOTSTRAP_ITERATIONS, len(delta)),
    )
    replicates = delta[indices].mean(axis=1)
    lower, upper = np.quantile(replicates, [0.025, 0.975]).tolist()
    point = float(delta.mean())
    includes_zero = bool(lower <= 0.0 <= upper)
    if includes_zero:
        verdict = "GAME_ENGINE_COMPARISON_INCONCLUSIVE"
    elif upper < 0.0:
        verdict = "E10_LOWER_HOLDOUT_MONEYLINE_LOG_LOSS"
    else:
        verdict = "DIRECT_GOLD_LOWER_HOLDOUT_MONEYLINE_LOG_LOSS"
    return {
        "method": "PAIRED_WHOLE_GAME_NONPARAMETRIC_BOOTSTRAP",
        "samplingUnit": "CANONICAL_GAME",
        "evaluationScope": "FINAL_UNTOUCHED_HOLDOUT_ONLY",
        "gameCount": len(delta),
        "iterations": COMPARISON_BOOTSTRAP_ITERATIONS,
        "seed": COMPARISON_BOOTSTRAP_SEED,
        "difference": "E10_MINUS_DIRECT_GOLD_MONEYLINE_LOG_LOSS",
        "pointEstimate": point,
        "confidenceLevel": 0.95,
        "confidenceInterval": {"lower": float(lower), "upper": float(upper)},
        "includesZero": includes_zero,
        "verdict": verdict,
        "selectionUsesFiveFoldResults": False,
        "promotionAuthorized": False,
    }


def _daily_boards(
    records: Sequence[Mapping[str, Any]],
    candidate_ids: Sequence[str] | str,
) -> list[dict[str, Any]]:
    candidates = (
        (candidate_ids,) if isinstance(candidate_ids, str) else tuple(candidate_ids)
    )
    if candidates != HOLDOUT_CANDIDATES:
        raise GameSimulationMarketStudyError(
            "SHADOW board candidates must be both holdout engines"
        )
    selected = [
        row
        for row in records
        if row["cohortId"] == "HOLDOUT" and row["candidateId"] in candidates
    ]
    game_boards = [unavailable_shadow_board(row) for row in selected]
    expected = EXPECTED_COHORT_GAMES["HOLDOUT"] * len(candidates)
    expected_rows_per_board = len(MARKET_FAMILY_ORDER) + 1
    if len(game_boards) != expected or any(
        len(board["rows"]) != expected_rows_per_board for board in game_boards
    ):
        raise GameSimulationMarketStudyError("SHADOW board reconciliation differs")
    identities = [
        (str(board["candidateId"]), str(board["canonicalGameId"]))
        for board in game_boards
    ]
    if len(identities) != len(set(identities)):
        raise GameSimulationMarketStudyError("SHADOW game board identity is duplicated")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for board in game_boards:
        key = (str(board["gameDate"]), str(board["candidateId"]))
        grouped.setdefault(key, []).append(board)
    daily_boards: list[dict[str, Any]] = []
    for (board_date, candidate_id), games in sorted(grouped.items()):
        ordered = sorted(games, key=lambda item: str(item["canonicalGameId"]))
        row_count = sum(len(game["rows"]) for game in ordered)
        daily_boards.append(
            {
                "schemaVersion": "MLB_SHADOW_DAILY_MARKET_BOARD_UNAVAILABLE_V1",
                "boardDate": board_date,
                "candidateId": candidate_id,
                "gameCount": len(ordered),
                "marketFamilyCount": len(MARKET_FAMILY_ORDER),
                "rowCount": row_count,
                "stateCounts": {
                    "NO_BET": row_count,
                    "WATCH": 0,
                    "QUALIFIED_BET": 0,
                },
                "dailyExposureFraction": 0.0,
                "maximumDailyExposureFraction": MAX_DAILY_EXPOSURE_FRACTION,
                "virtualPolicyCaps": {
                    "kellyMultiplier": KELLY_MULTIPLIER,
                    "normalUnitFraction": NORMAL_UNIT_FRACTION,
                    "maximumPositionFraction": MAX_POSITION_FRACTION,
                    "maximumSameGameExposureFraction": MAX_SAME_GAME_EXPOSURE_FRACTION,
                    "maximumDailyExposureFraction": MAX_DAILY_EXPOSURE_FRACTION,
                    "normalUnitIsMinimumStake": False,
                    "bankrollAmount": None,
                },
                "readiness": {
                    "status": "NOT_READY",
                    "reasonCodes": ["HISTORICAL_ODDS_INSUFFICIENT"],
                },
                "games": ordered,
                "allStates": "NO_BET",
                "allStakeFractions": 0.0,
                "parlaysAllowed": False,
                "shadowOnly": True,
                "historicalRoiReported": False,
                "executionAllowed": False,
            }
        )
    if sum(board["gameCount"] for board in daily_boards) != expected:
        raise GameSimulationMarketStudyError("daily SHADOW game inventory differs")
    if {board["candidateId"] for board in daily_boards} != set(candidates):
        raise GameSimulationMarketStudyError("daily SHADOW candidate inventory differs")
    return daily_boards


def _report_markdown(results: Mapping[str, Any]) -> str:
    fold_direct = results["gameLevelMetrics"]["FIVE_FOLD_DIRECT_OOF"][DIRECT_GOLD]
    direct_all = results["gameLevelMetrics"]["DIRECT_ALL_STRICTLY_OUT_OF_SAMPLE"][
        DIRECT_GOLD
    ]
    holdout = results["gameLevelMetrics"]["HOLDOUT"]
    comparison = results["holdoutPaEngineComparison"]
    interval = comparison["confidenceInterval"]
    evidence_by_cohort = {
        str(item["cohortId"]): item for item in results["cohortEvidence"]
    }
    lines = [
        "# Phase 7B6 — AISP Game Forecast Export MVP",
        "",
        f"Status: **{results['status']}**",
        "",
        "## Governed population",
        "",
        f"- Five-fold Direct OOF games: {results['population']['fiveFoldDirectOofGames']:,}",
        f"- Final holdout games: {results['population']['holdoutGames']:,}",
        f"- Direct all strictly out-of-sample games: {results['population']['directAllStrictlyOutOfSampleGames']:,}",
        f"- Persisted candidate-game records: {results['population']['candidateGameResultCount']:,}",
        "- Pregame policy: starting nine cycled; announced starter held constant; no actual substitutions or relievers.",
        "",
        "## Six-cohort Direct evidence",
        "",
        "| Cohort | PA rows | Games | ML LL | ML Brier | Calibration | ECE | Winner acc | Away MAE | Home MAE | Team MAE | Total MAE | Run-diff MAE | F5 coverage | F5 LL | F5 Brier | F5 acc | F5 total MAE | F5 run-diff MAE | Max sim Δp |",
        "|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cohort_id in COHORT_ORDER:
        metric = results["gameLevelMetrics"][cohort_id][DIRECT_GOLD]
        first = metric["firstFive"]
        evidence = evidence_by_cohort[cohort_id]
        lines.append(
            f"| {cohort_id} | {int(evidence['scoreRows']):,} | {metric['gameCount']:,} | "
            f"{metric['moneylineLogLoss']:.9f} | {metric['moneylineBrier']:.9f} | "
            f"{metric['calibration']['method']} | {metric['calibration']['ece']:.9f} | "
            f"{metric['winnerAccuracy']:.9f} | {metric['awayRunMae']:.9f} | "
            f"{metric['homeRunMae']:.9f} | {metric['meanTeamRunMae']:.9f} | "
            f"{metric['totalRunMae']:.9f} | {metric['runDifferenceMae']:.9f} | "
            f"{first['coverage']:.9f} | {first['threeWayLogLoss']:.9f} | "
            f"{first['summedBrier']:.9f} | {first['winnerTieAccuracy']:.9f} | "
            f"{first['totalRunMae']:.9f} | {first['runDifferenceMae']:.9f} | "
            f"{metric['simulationStability']['homeWinProbability']['maximumAbsoluteDriftVsFinal']:.9f} |"
        )
    lines.extend(
        [
            "",
            f"- Direct five-fold OOF moneyline log loss: {fold_direct['moneylineLogLoss']:.9f}",
            f"- Direct all-out-of-sample moneyline log loss: {direct_all['moneylineLogLoss']:.9f}",
            "- E10 is intentionally absent from FOLD_1 through FOLD_5 because its accepted stacker was meta-fit on the combined five-fold labels.",
            "",
            "## Final untouched holdout Direct-vs-E10 comparison",
            "",
            "| Engine | ML LL | ML Brier | Calibration | ECE | Winner acc | Away MAE | Home MAE | Team MAE | Total MAE | Run-diff MAE | F5 coverage | F5 LL | F5 Brier | F5 acc | F5 total MAE | F5 run-diff MAE | Max sim Δp |",
            "|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for candidate in HOLDOUT_CANDIDATES:
        metric = holdout[candidate]
        first = metric["firstFive"]
        lines.append(
            f"| {candidate} | {metric['moneylineLogLoss']:.9f} | "
            f"{metric['moneylineBrier']:.9f} | {metric['calibration']['method']} | "
            f"{metric['calibration']['ece']:.9f} | {metric['winnerAccuracy']:.9f} | "
            f"{metric['awayRunMae']:.9f} | {metric['homeRunMae']:.9f} | "
            f"{metric['meanTeamRunMae']:.9f} | {metric['totalRunMae']:.9f} | "
            f"{metric['runDifferenceMae']:.9f} | {first['coverage']:.9f} | "
            f"{first['threeWayLogLoss']:.9f} | {first['summedBrier']:.9f} | "
            f"{first['winnerTieAccuracy']:.9f} | {first['totalRunMae']:.9f} | "
            f"{first['runDifferenceMae']:.9f} | "
            f"{metric['simulationStability']['homeWinProbability']['maximumAbsoluteDriftVsFinal']:.9f} |"
        )
    lines.extend(
        [
            "",
            f"Paired holdout log-loss delta (E10 - Direct): **{comparison['pointEstimate']:.9f}**.",
            f"Fixed-seed paired 95% whole-game bootstrap CI: **[{interval['lower']:.9f}, {interval['upper']:.9f}]**.",
            f"Comparison verdict: **{comparison['verdict']}**.",
            "Five-fold results were not used to select between Direct and E10. Both remain authorized only for future RESEARCH_SHADOW evaluation; neither is promoted.",
            "",
            "## Distributions and simulation uncertainty",
            "",
            "Every game record includes away/home marginal run distributions, joint score, home-minus-away run difference, total runs, first-five counterparts, empirical standard deviations, fixed quantiles, central 50/80/90/95% prediction intervals, and 100/250/500/1000-draw stability summaries.",
            "",
            "## Sportsbook and SHADOW board",
            "",
            "Historical odds status: **HISTORICAL_ODDS_INSUFFICIENT**.",
            "",
            "No governed persisted historical sportsbook odds were available. No historical no-vig benchmark, edge/EV backtest, CLV, staking result, or ROI is reported. Date-and-candidate daily boards retain every detailed game and market slot, remain SHADOW-only, and mark every historical example NO_BET with zero stake.",
            "",
            "## Limitations",
            "",
            "- Static pregame probability cards do not model fatigue, times-through-order, substitutions, or bullpen deployment.",
            "- Retrosheet start records identify the historical starters but carry no captured-at timestamp.",
            "- This is research-only and no model or betting decision was promoted.",
            "",
            "## Exact consumer next step",
            "",
            "ASP Sports Predictor should consume the content-addressed game-distribution schema and implement prospective, timestamped two-sided quote capture into the SHADOW ledger. It must keep qualification thresholds unset until a separately governed prospective policy is approved.",
            "",
            "AISP_GAME_FORECAST_EXPORT_MVP_COMPLETE",
            "",
        ]
    )
    return "\n".join(lines)


def _implementation_inventory(repository_root: Path) -> list[dict[str, Any]]:
    relatives = (
        "server/sports_gold/game_simulation_market_study.py",
        "server/sports_gold/game_simulation_inputs.py",
        "server/sports_gold/game_probability_adapter.py",
        "server/sports_gold/game_market_mvp.py",
        "server/sports_gold/walk_forward_state.py",
        "server/sports_phase5/whole_game_monte_carlo.py",
    )
    result = []
    for relative in relatives:
        path = Path(repository_root) / relative
        size, digest = _sha256_file(path)
        result.append({"relativePath": relative, "bytes": size, "sha256": digest})
    return result


def _fd1_truth_authority(
    root: Path,
    partitions: Mapping[int, Sequence[Path]],
    inputs: GameSimulationInputs,
) -> dict[str, Any]:
    resolved_root = Path(root).resolve()
    files: list[dict[str, Any]] = []
    for season in sorted(partitions):
        if int(season) not in {2022, 2023, 2024}:
            raise GameSimulationMarketStudyError(
                f"FD1 season rejected before authority hashing: {season}"
            )
        for raw in sorted((Path(value) for value in partitions[season]), key=str):
            path = raw.resolve()
            if (
                resolved_root not in path.parents
                or f"season={season}" not in path.parts
            ):
                raise GameSimulationMarketStudyError(
                    "FD1 partition authority escapes its season"
                )
            size, digest = _sha256_file(path)
            files.append(
                {
                    "season": int(season),
                    "relativePath": str(path.relative_to(resolved_root)).replace(
                        "\\", "/"
                    ),
                    "bytes": size,
                    "sha256": digest,
                }
            )
    truth = [
        {
            "canonicalGameId": game_id,
            "awayRuns": value.first_five_away_runs,
            "homeRuns": value.first_five_home_runs,
            "source": value.first_five_source,
        }
        for game_id, value in sorted(inputs.truth.items())
        if value.first_five_available
    ]
    return {
        "schemaVersion": "MLB_GOLD_PHASE7B6_FD1_FIRST_FIVE_AUTHORITY_V1",
        "root": str(resolved_root),
        "seasons": [2022, 2023, 2024],
        "partitionCount": len(files),
        "partitions": files,
        "firstFiveGameCount": len(truth),
        "firstFiveTruthSha256": _sha256_bytes(canonical_json_bytes(truth)),
    }


def _verify_existing(final_root: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    try:
        manifest = json.loads(
            (final_root / "manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GameSimulationMarketStudyError(
            "existing Phase 7B6 manifest is invalid"
        ) from exc
    if manifest.get("request") != request:
        raise GameSimulationMarketStudyError("existing Phase 7B6 request differs")
    expected_request_sha = _sha256_bytes(canonical_json_bytes(request))
    if (
        manifest.get("requestSha256") != expected_request_sha
        or final_root.name != expected_request_sha
    ):
        raise GameSimulationMarketStudyError(
            "existing Phase 7B6 request address differs"
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise GameSimulationMarketStudyError(
            "existing Phase 7B6 artifact inventory is missing"
        )
    actual = {
        str(path.relative_to(final_root)).replace("\\", "/")
        for path in final_root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual != set(artifacts):
        raise GameSimulationMarketStudyError(
            "existing Phase 7B6 file inventory differs"
        )
    for relative, evidence in artifacts.items():
        size, digest = _sha256_file(final_root / relative)
        if size != int(evidence["bytes"]) or digest != evidence["sha256"]:
            raise GameSimulationMarketStudyError(
                f"existing Phase 7B6 artifact differs: {relative}"
            )
    results = json.loads((final_root / "results.json").read_text(encoding="utf-8"))
    if _sha256_bytes(canonical_json_bytes(results)) != manifest.get("resultsSha256"):
        raise GameSimulationMarketStudyError(
            "existing Phase 7B6 result identity differs"
        )
    return results


def run_game_simulation_market_mvp(
    *,
    gold_root: Path,
    silver_root: Path,
    study_root: Path,
    fd1_play_transition_root: Path,
    fd1_partitions: Mapping[int, Sequence[Path]],
    repository_root: Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Execute the one fixed research-only Phase 7B6 study."""

    notify = progress or (lambda _message: None)
    repo = Path(repository_root).resolve()
    if Path(study_root).resolve().name != EXPECTED_STUDY_SHA256:
        raise GameSimulationMarketStudyError(
            "Phase 7B5 source study is not the accepted request"
        )
    inputs = load_game_simulation_inputs(
        gold_root=Path(gold_root),
        silver_root=Path(silver_root),
        study_root=Path(study_root),
        fd1_play_transition_root=Path(fd1_play_transition_root),
        fd1_partitions=fd1_partitions,
    )
    if tuple(inputs.cohorts) != COHORT_ORDER or any(
        inputs.cohorts[name].game_count != EXPECTED_COHORT_GAMES[name]
        for name in COHORT_ORDER
    ):
        raise GameSimulationMarketStudyError("fixed cohort inventory differs")
    frame = _load_gold_feature_frame(Path(gold_root))
    feature_index = PregameFeatureIndex(frame)
    full_ledger = _global_direct_ledger(frame, inputs)
    transition_sampler, transition_record = load_transition_sampler(repo)
    fd1_authority = _fd1_truth_authority(
        Path(fd1_play_transition_root), fd1_partitions, inputs
    )
    request = {
        "schemaVersion": REQUEST_SCHEMA_VERSION,
        "sourcePhase7B5RequestSha256": EXPECTED_STUDY_SHA256,
        "sourceGold": dict(inputs.gold_identity),
        "sourceSilver": {
            name: dict(value) for name, value in inputs.silver_identities.items()
        },
        "sourceStudyArtifacts": dict(inputs.study.artifact_sha256),
        "transitionModel": transition_record,
        "firstFiveTruthAuthority": fd1_authority,
        "cohorts": [
            {
                "cohortId": name,
                "startDate": inputs.cohorts[name].start_date,
                "endDate": inputs.cohorts[name].end_date,
                "paRows": inputs.cohorts[name].row_count,
                "games": inputs.cohorts[name].game_count,
                "candidateIds": list(candidates_for_cohort(name)),
            }
            for name in COHORT_ORDER
        ],
        "paEngines": list(CANDIDATE_ORDER),
        "candidatePolicy": {
            "fiveFold": list(FOLD_CANDIDATES),
            "holdout": list(HOLDOUT_CANDIDATES),
            "reason": "E10_META_FIT_LABELS_OVERLAP_FIVE_FOLD_COMPONENT_OOF_ROWS",
            "e10FiveFoldReported": False,
            "selectionUsesFiveFoldResults": False,
        },
        "classOrder": list(PA_CLASS_ORDER),
        "simulation": {
            "masterSeed": MASTER_SEED,
            "simulationsPerGame": SIMULATIONS_PER_GAME,
            "stabilityPrefixes": list(STABILITY_PREFIXES),
            "commonRandomNumbersAcrossEngines": True,
        },
        "holdoutComparisonUncertainty": {
            "method": "PAIRED_WHOLE_GAME_NONPARAMETRIC_BOOTSTRAP",
            "iterations": COMPARISON_BOOTSTRAP_ITERATIONS,
            "seed": COMPARISON_BOOTSTRAP_SEED,
            "difference": "E10_MINUS_DIRECT_GOLD_MONEYLINE_LOG_LOSS",
            "confidenceLevel": 0.95,
        },
        "participantPolicy": {
            "battingOrder": "STARTING_LINEUP_CYCLED",
            "pitcher": "ANNOUNCED_STARTER_HELD_CONSTANT",
            "actualSubstitutionsUsed": False,
            "actualRelieversUsed": False,
        },
        "market": market_mvp_contract(),
        "historicalOddsCoverage": list(zero_historical_market_coverage()),
        "implementation": _implementation_inventory(repo),
        "bronzeRebuildRequested": False,
        "silverRebuildRequested": False,
        "goldRebuildRequested": False,
        "paModelFitRequested": False,
        "promotionRequested": False,
        "parlaysAllowed": False,
        "prohibitedSeasons": [2025, 2026],
    }
    request_sha = _sha256_bytes(canonical_json_bytes(request))
    final_root = (
        Path(gold_root).resolve()
        / "game-simulation-market-studies"
        / "sha256"
        / request_sha
    )
    if final_root.exists():
        return _verify_existing(final_root, request)
    staging = final_root.parent / f".staging-{request_sha}-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    _write_json(staging / "request.json", request)
    started = time.perf_counter()
    records: list[dict[str, Any]] = []
    cohort_evidence: list[dict[str, Any]] = []
    model_evidence: dict[str, Any] = {}
    try:
        for cohort_id in COHORT_ORDER:
            notify(
                f"{cohort_id}: load "
                + (
                    "frozen Direct/E10 and reconstruct D-1 state"
                    if cohort_id == "HOLDOUT"
                    else "frozen Direct only"
                )
            )
            direct, e10, models = load_frozen_models(Path(study_root), cohort_id)
            model_evidence[cohort_id] = models
            cohort_records, evidence = _simulate_cohort(
                cohort=inputs.cohorts[cohort_id],
                inputs=inputs,
                frame=frame,
                feature_index=feature_index,
                full_ledger=full_ledger,
                direct_model=direct,
                e10_stacker=e10,
                transition_sampler=transition_sampler,
                progress=notify,
            )
            records.extend(cohort_records)
            cohort_evidence.append(evidence)
        expected_games = sum(EXPECTED_COHORT_GAMES.values())
        expected_records = sum(
            EXPECTED_COHORT_GAMES[name] * len(candidates_for_cohort(name))
            for name in COHORT_ORDER
        )
        if len(records) != expected_records:
            raise GameSimulationMarketStudyError(
                "combined game-result inventory differs"
            )
        metrics = _metric_groups(records)
        comparison = paired_holdout_log_loss_bootstrap(records)
        boards = _daily_boards(records, HOLDOUT_CANDIDATES)
        results: dict[str, Any] = {
            "schemaVersion": RESULT_SCHEMA_VERSION,
            "status": "AISP_GAME_FORECAST_EXPORT_MVP_COMPLETE",
            "requestSha256": request_sha,
            "population": {
                "fiveFoldDirectOofGames": sum(
                    EXPECTED_COHORT_GAMES[name] for name in COHORT_ORDER[:-1]
                ),
                "holdoutGames": EXPECTED_COHORT_GAMES["HOLDOUT"],
                "directAllStrictlyOutOfSampleGames": expected_games,
                "candidateGameResultCount": expected_records,
            },
            "candidateInventory": {
                name: list(candidates_for_cohort(name)) for name in COHORT_ORDER
            },
            "cohortEvidence": cohort_evidence,
            "frozenModelEvidence": model_evidence,
            "gameLevelMetrics": metrics,
            "holdoutPaEngineComparison": comparison,
            "gameEngineComparisonVerdict": comparison["verdict"],
            "researchShadowAuthorization": {
                "candidateIds": list(HOLDOUT_CANDIDATES),
                "scope": "FUTURE_RESEARCH_SHADOW_ONLY",
                "promotionAuthorized": False,
                "selectionUsesFiveFoldResults": False,
            },
            "sportsbookBenchmark": {
                "status": "HISTORICAL_ODDS_INSUFFICIENT",
                "coveredGames": 0,
                "reason": "NO_GOVERNED_PERSISTED_HISTORICAL_SPORTSBOOK_QUOTES",
                "historicalBettingRoiReported": False,
            },
            "shadowMarket": {
                "historicalCoverage": list(zero_historical_market_coverage()),
                "candidateIds": list(HOLDOUT_CANDIDATES),
                "boardGranularity": "DATE_AND_CANDIDATE",
                "boardCount": len(boards),
                "gameBoardCount": sum(int(board["gameCount"]) for board in boards),
                "rowCount": sum(int(board["rowCount"]) for board in boards),
                "allStates": "NO_BET",
                "allStakeFractions": 0.0,
                "marketContract": market_mvp_contract(),
            },
            "limitations": [
                "STARTING_LINEUP_CYCLED_WITHOUT_SUBSTITUTIONS",
                "ANNOUNCED_STARTER_HELD_CONSTANT_WITHOUT_BULLPEN_POLICY",
                "STATIC_PREGAME_PA_CARDS_DO_NOT_RESPOND_TO_SIMULATED_CONTEXT",
                "RETROSHEET_START_RECORDS_HAVE_NO_CAPTURE_TIMESTAMP",
                "NO_GOVERNED_HISTORICAL_SPORTSBOOK_ODDS",
                "E10_EVALUATED_ON_FINAL_UNTOUCHED_HOLDOUT_ONLY",
            ],
            "consumerNextStep": "ASP Sports Predictor should consume the content-addressed game distribution schema and prospectively capture timestamped two-sided SHADOW quotes before any market threshold is governed.",
            "paModelsFit": 0,
            "modelsPromoted": 0,
            "historicalRoiReported": False,
            "uses2025Or2026": False,
        }
        with (staging / "game-results.jsonl").open(
            "w", encoding="utf-8", newline="\n"
        ) as stream:
            for record in records:
                stream.write(canonical_json_bytes(record).decode("utf-8") + "\n")
        _write_json(staging / "shadow-market-boards.json", boards)
        _write_json(staging / "results.json", results)
        _write_json(
            staging / "execution.json",
            {
                "schemaVersion": "MLB_GOLD_GAME_SIMULATION_MARKET_MVP_EXECUTION_V1",
                "artifactRoot": str(final_root),
                "elapsedSeconds": float(time.perf_counter() - started),
                "scientificResultIdentity": "EXCLUDED_FROM_RESULTS_SHA256",
            },
        )
        (staging / "experiment-report.md").write_text(
            _report_markdown(results), encoding="utf-8", newline="\n"
        )
        artifacts: dict[str, Any] = {}
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            relative = str(path.relative_to(staging)).replace("\\", "/")
            if relative == "manifest.json":
                continue
            size, digest = _sha256_file(path)
            artifacts[relative] = {"bytes": size, "sha256": digest}
        manifest = {
            "schemaVersion": "MLB_GOLD_GAME_SIMULATION_MARKET_MVP_MANIFEST_V1",
            "request": request,
            "requestSha256": request_sha,
            "resultsSha256": _sha256_bytes(canonical_json_bytes(results)),
            "artifacts": artifacts,
        }
        _write_json(staging / "manifest.json", manifest)
        final_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final_root)
        return results
    except Exception:
        # Preserve staging evidence for diagnosis; no accepted address is created.
        raise


__all__ = [
    "CANDIDATE_ORDER",
    "COMPARISON_BOOTSTRAP_ITERATIONS",
    "COMPARISON_BOOTSTRAP_SEED",
    "COHORT_ORDER",
    "FOLD_CANDIDATES",
    "GameSimulationMarketStudyError",
    "HOLDOUT_CANDIDATES",
    "PregameFeatureIndex",
    "MASTER_SEED",
    "RESULT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "SIMULATIONS_PER_GAME",
    "build_pregame_templates",
    "candidates_for_cohort",
    "game_level_metrics",
    "load_frozen_models",
    "load_transition_sampler",
    "paired_holdout_log_loss_bootstrap",
    "require_strict_chronological_e10_oof",
    "run_game_simulation_market_mvp",
    "summarize_game_simulation",
    "unavailable_shadow_board",
]
