"""Chronological UFC bout features for the Gen 1 research model.

The source is reconstructed finalized history.  Target-bout outcomes and statistics
are used only after the row's pre-bout feature vector has been emitted.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

MODEL_ID = "MMA_UFC_GEN1_WINNER_V1"
MODERN_START = "2010-01-01"
DEV_END = "2022-12-31"
VALIDATION_START = "2023-01-01"
VALIDATION_END = "2024-12-31"
OOT_START = "2025-01-01"
ELO_K = 24.0
ELO_SCALE = 400.0

NUMERIC_FEATURES = (
    "elo_diff",
    "experience_diff",
    "experience_total",
    "win_rate_diff",
    "finish_rate_diff",
    "ko_rate_diff",
    "submission_rate_diff",
    "recent_win_rate_diff",
    "layoff_days_diff",
    "layoff_missing_a",
    "layoff_missing_b",
    "avg_duration_minutes_diff",
    "sig_strikes_landed_per_min_diff",
    "sig_strikes_absorbed_per_min_diff",
    "takedowns_per_15_diff",
    "takedowns_allowed_per_15_diff",
    "submission_attempts_per_15_diff",
    "control_share_diff",
    "knockdowns_per_15_diff",
    "opponent_elo_diff",
    "weight_class_changes_diff",
    "rematch_count",
    "scheduled_rounds",
    "five_round_indicator",
    "calendar_year",
)
CATEGORICAL_FEATURES = ("weight_class",)
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


class GovernanceError(RuntimeError):
    """Raised when chronology or frozen-evidence requirements are violated."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_canonical_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value)
    path.write_bytes(payload)
    return {"path": str(path), "bytes": len(payload), "sha256": sha256_bytes(payload)}


def verify_frozen_design(path: Path, expected_sha256: str | None = None) -> str:
    payload = path.read_bytes()
    parsed = json.loads(payload)
    if parsed.get("modelId") != MODEL_ID or parsed.get("status") != "FROZEN_BEFORE_ASSESSMENT":
        raise GovernanceError("DESIGN_NOT_FROZEN")
    actual = sha256_bytes(payload)
    if expected_sha256 and actual != expected_sha256:
        raise GovernanceError("FROZEN_DESIGN_HASH_MISMATCH")
    return actual


def require_finalist_receipt(path: Path, digest_path: Path) -> str:
    expected = digest_path.read_text(encoding="ascii").strip()
    actual = sha256_file(path)
    if expected != actual:
        raise GovernanceError("FINALIST_RECEIPT_HASH_MISMATCH")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("status") != "IMMUTABLE_FINALIST_FROZEN" or receipt.get("ootOpened") is not False:
        raise GovernanceError("FINALIST_NOT_FROZEN_BEFORE_OOT")
    return actual


def load_clean_bouts(source_root: Path) -> pd.DataFrame:
    """Load the cleaned bout table and attach event dates.

    This loads finalized source rows but does not construct any feature from the
    target row. Callers must use the OOT gate before calculating 2025 metrics.
    """
    fights = pd.read_csv(source_root / "data" / "Fights.csv")
    events = pd.read_csv(source_root / "data" / "Events.csv", dtype={"Event_Id": str})
    events["event_date"] = pd.to_datetime(events["Date"], errors="raise")
    bouts = fights.merge(
        events[["Event_Id", "Name", "Location", "event_date"]],
        on="Event_Id",
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    if (bouts["_merge"] != "both").any():
        raise GovernanceError("ORPHAN_BOUT_EVENT")
    if bouts["Fight_Id"].duplicated().any():
        raise GovernanceError("DUPLICATE_FIGHT_ID")
    bouts = bouts.drop(columns=["_merge"])
    return bouts.sort_values(["event_date", "Event_Id", "Fight_Id"], kind="stable").reset_index(drop=True)


def outcome_class(row: pd.Series) -> str:
    r1, r2 = str(row["Result_1"]), str(row["Result_2"])
    method = str(row.get("Method", ""))
    if method.casefold() == "overturned" or (r1 == "NC" and r2 == "NC"):
        return "NO_CONTEST_OR_OVERTURNED"
    if r1 == "D" and r2 == "D":
        return "DRAW"
    if (r1, r2) in {("W", "L"), ("L", "W")}:
        return "DECISIVE"
    return "MISSING_OR_UNKNOWN_RESULT"


def scheduled_rounds(time_format: Any) -> int | None:
    value = str(time_format)
    if value.startswith("3 Rnd (5-5-5)"):
        return 3
    if value.startswith("5 Rnd (5-5-5-5-5)"):
        return 5
    return None


def fight_seconds(row: pd.Series) -> float:
    try:
        minutes, seconds = (int(part) for part in str(row["Fight_Time"]).split(":"))
        return max(1.0, (int(row["Round"]) - 1) * 300.0 + minutes * 60.0 + seconds)
    except (TypeError, ValueError):
        return math.nan


def _safe_rate(numerator: float, denominator: float, default: float = 0.0) -> float:
    return float(numerator / denominator) if denominator > 0 else default


@dataclass
class FighterState:
    elo: float = 1500.0
    bouts: int = 0
    wins: int = 0
    losses: int = 0
    finish_wins: int = 0
    ko_wins: int = 0
    submission_wins: int = 0
    total_seconds: float = 0.0
    sig_landed: float = 0.0
    sig_absorbed: float = 0.0
    takedowns: float = 0.0
    takedowns_allowed: float = 0.0
    submission_attempts: float = 0.0
    control_seconds: float = 0.0
    knockdowns: float = 0.0
    opponent_elo_sum: float = 0.0
    weight_class_changes: int = 0
    last_weight_class: str | None = None
    last_date: pd.Timestamp | None = None
    recent: deque[int] = field(default_factory=lambda: deque(maxlen=5))

    def snapshot(self, at_date: pd.Timestamp) -> dict[str, float]:
        minutes = self.total_seconds / 60.0
        per_15 = self.total_seconds / 900.0
        layoff = math.nan if self.last_date is None else float((at_date - self.last_date).days)
        return {
            "elo": self.elo,
            "experience": float(self.bouts),
            "win_rate": _safe_rate(self.wins, self.bouts, 0.5),
            "finish_rate": _safe_rate(self.finish_wins, self.wins),
            "ko_rate": _safe_rate(self.ko_wins, self.wins),
            "submission_rate": _safe_rate(self.submission_wins, self.wins),
            "recent_win_rate": _safe_rate(sum(self.recent), len(self.recent), 0.5),
            "layoff_days": layoff,
            "avg_duration_minutes": _safe_rate(minutes, self.bouts),
            "sig_landed_per_min": _safe_rate(self.sig_landed, minutes),
            "sig_absorbed_per_min": _safe_rate(self.sig_absorbed, minutes),
            "takedowns_per_15": _safe_rate(self.takedowns, per_15),
            "takedowns_allowed_per_15": _safe_rate(self.takedowns_allowed, per_15),
            "submission_attempts_per_15": _safe_rate(self.submission_attempts, per_15),
            "control_share": _safe_rate(self.control_seconds, self.total_seconds),
            "knockdowns_per_15": _safe_rate(self.knockdowns, per_15),
            "opponent_elo": _safe_rate(self.opponent_elo_sum, self.bouts, 1500.0),
            "weight_class_changes": float(self.weight_class_changes),
        }


def elo_probability(diff: float) -> float:
    return float(1.0 / (1.0 + 10.0 ** (-diff / ELO_SCALE)))


def _method_group(method: str) -> str:
    upper = method.upper()
    if upper.startswith("KO/TKO"):
        return "KO"
    if upper.startswith("SUB"):
        return "SUBMISSION"
    if "DEC" in upper:
        return "DECISION"
    return "OTHER"


def _update_state(
    state: FighterState,
    *,
    won: bool,
    method: str,
    duration: float,
    sig_landed: float,
    sig_absorbed: float,
    takedowns: float,
    takedowns_allowed: float,
    submission_attempts: float,
    control_seconds: float,
    knockdowns: float,
    opponent_elo: float,
    weight_class: str,
    at_date: pd.Timestamp,
) -> None:
    state.bouts += 1
    state.wins += int(won)
    state.losses += int(not won)
    state.recent.append(int(won))
    group = _method_group(method)
    if won and group != "DECISION":
        state.finish_wins += 1
    state.ko_wins += int(won and group == "KO")
    state.submission_wins += int(won and group == "SUBMISSION")
    if math.isfinite(duration):
        state.total_seconds += duration
    state.sig_landed += float(sig_landed)
    state.sig_absorbed += float(sig_absorbed)
    state.takedowns += float(takedowns)
    state.takedowns_allowed += float(takedowns_allowed)
    state.submission_attempts += float(submission_attempts)
    state.control_seconds += float(control_seconds)
    state.knockdowns += float(knockdowns)
    state.opponent_elo_sum += float(opponent_elo)
    if state.last_weight_class is not None and state.last_weight_class != weight_class:
        state.weight_class_changes += 1
    state.last_weight_class = weight_class
    state.last_date = at_date


def population_disposition(bouts: pd.DataFrame, fighter_ids: set[str]) -> pd.DataFrame:
    disposition = []
    for _, row in bouts.iterrows():
        reason = "ELIGIBLE"
        if row["event_date"] < pd.Timestamp(MODERN_START):
            reason = "PRE_MODERN_ERA"
        elif outcome_class(row) != "DECISIVE":
            reason = outcome_class(row)
        elif scheduled_rounds(row["Time Format"]) not in {3, 5}:
            reason = "NONSTANDARD_SCHEDULED_ROUNDS"
        elif str(row["Fighter_Id_1"]) not in fighter_ids or str(row["Fighter_Id_2"]) not in fighter_ids:
            reason = "MISSING_FIGHTER_DIMENSION"
        disposition.append({"Fight_Id": row["Fight_Id"], "event_date": row["event_date"], "reason": reason})
    return pd.DataFrame(disposition)


def build_feature_table(
    bouts: pd.DataFrame,
    fighter_ids: set[str],
    *,
    through_date: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create one canonical-orientation row using state strictly before each bout."""
    end = pd.Timestamp(through_date)
    if end >= pd.Timestamp(OOT_START):
        raise GovernanceError("OOT_FEATURE_BUILD_REQUIRES_EXPLICIT_GATE")
    return _build_feature_table_unchecked(bouts, fighter_ids, end=end)


def build_feature_table_after_finalist(
    bouts: pd.DataFrame,
    fighter_ids: set[str],
    *,
    through_date: str,
    finalist_receipt: Path,
    finalist_digest: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    require_finalist_receipt(finalist_receipt, finalist_digest)
    return _build_feature_table_unchecked(bouts, fighter_ids, end=pd.Timestamp(through_date))


def _build_feature_table_unchecked(
    bouts: pd.DataFrame,
    fighter_ids: set[str],
    *,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    states: defaultdict[str, FighterState] = defaultdict(FighterState)
    pair_counts: defaultdict[tuple[str, str], int] = defaultdict(int)
    records: list[dict[str, Any]] = []
    updates = 0
    skipped_updates = defaultdict(int)
    for _, row in bouts[bouts["event_date"] <= end].iterrows():
        fighter_1, fighter_2 = str(row["Fighter_Id_1"]), str(row["Fighter_Id_2"])
        disposition = outcome_class(row)
        rounds = scheduled_rounds(row["Time Format"])
        dimension_ok = fighter_1 in fighter_ids and fighter_2 in fighter_ids
        eligible = (
            row["event_date"] >= pd.Timestamp(MODERN_START)
            and disposition == "DECISIVE"
            and rounds in {3, 5}
            and dimension_ok
        )
        canonical_a, canonical_b = sorted((fighter_1, fighter_2))
        state_a, state_b = states[canonical_a], states[canonical_b]
        snap_a, snap_b = state_a.snapshot(row["event_date"]), state_b.snapshot(row["event_date"])
        if eligible:
            a_is_one = canonical_a == fighter_1
            a_result = str(row["Result_1"] if a_is_one else row["Result_2"])
            record: dict[str, Any] = {
                "fight_id": str(row["Fight_Id"]),
                "event_id": str(row["Event_Id"]),
                "event_date": row["event_date"],
                "fighter_a_id": canonical_a,
                "fighter_b_id": canonical_b,
                "fighter_a_name": str(row["Fighter_1"] if a_is_one else row["Fighter_2"]),
                "fighter_b_name": str(row["Fighter_2"] if a_is_one else row["Fighter_1"]),
                "target_a_win": int(a_result == "W"),
                "weight_class": str(row["Weight_Class"]),
                "scheduled_rounds": float(rounds),
                "five_round_indicator": float(rounds == 5),
                "calendar_year": float(row["event_date"].year),
                "rematch_count": float(pair_counts[(canonical_a, canonical_b)]),
            }
            for key in (
                "elo", "experience", "win_rate", "finish_rate", "ko_rate",
                "submission_rate", "recent_win_rate", "avg_duration_minutes",
                "sig_landed_per_min", "sig_absorbed_per_min", "takedowns_per_15",
                "takedowns_allowed_per_15", "submission_attempts_per_15",
                "control_share", "knockdowns_per_15", "opponent_elo",
                "weight_class_changes",
            ):
                public_name = {
                    "elo": "elo_diff",
                    "experience": "experience_diff",
                    "sig_landed_per_min": "sig_strikes_landed_per_min_diff",
                    "sig_absorbed_per_min": "sig_strikes_absorbed_per_min_diff",
                }.get(key, f"{key}_diff")
                record[public_name] = float(snap_a[key] - snap_b[key])
            record["experience_total"] = float(snap_a["experience"] + snap_b["experience"])
            layoff_a, layoff_b = snap_a["layoff_days"], snap_b["layoff_days"]
            record["layoff_missing_a"] = float(not math.isfinite(layoff_a))
            record["layoff_missing_b"] = float(not math.isfinite(layoff_b))
            record["layoff_days_diff"] = float(
                (layoff_a if math.isfinite(layoff_a) else 365.0)
                - (layoff_b if math.isfinite(layoff_b) else 365.0)
            )
            record["elo_probability_a"] = elo_probability(record["elo_diff"])
            records.append(record)

        # Only decisive, standard-duration bouts update the rolling state.
        if disposition != "DECISIVE" or rounds not in {3, 5} or not dimension_ok:
            skipped_updates[disposition if disposition != "DECISIVE" else "INELIGIBLE_STRUCTURE"] += 1
            continue
        a_elo, b_elo = states[fighter_1].elo, states[fighter_2].elo
        p_one = elo_probability(a_elo - b_elo)
        one_won = str(row["Result_1"]) == "W"
        states[fighter_1].elo = a_elo + ELO_K * (float(one_won) - p_one)
        states[fighter_2].elo = b_elo + ELO_K * (float(not one_won) - (1.0 - p_one))
        duration = fight_seconds(row)
        kwargs_one = dict(
            won=one_won,
            method=str(row["Method"]),
            duration=duration,
            sig_landed=float(row["STR_1"]),
            sig_absorbed=float(row["STR_2"]),
            takedowns=float(row["TD_1"]),
            takedowns_allowed=float(row["TD_2"]),
            submission_attempts=float(row["Sub. Att_1"]),
            control_seconds=float(row["Ctrl_1"]),
            knockdowns=float(row["KD_1"]),
            opponent_elo=b_elo,
            weight_class=str(row["Weight_Class"]),
            at_date=row["event_date"],
        )
        kwargs_two = dict(
            won=not one_won,
            method=str(row["Method"]),
            duration=duration,
            sig_landed=float(row["STR_2"]),
            sig_absorbed=float(row["STR_1"]),
            takedowns=float(row["TD_2"]),
            takedowns_allowed=float(row["TD_1"]),
            submission_attempts=float(row["Sub. Att_2"]),
            control_seconds=float(row["Ctrl_2"]),
            knockdowns=float(row["KD_2"]),
            opponent_elo=a_elo,
            weight_class=str(row["Weight_Class"]),
            at_date=row["event_date"],
        )
        _update_state(states[fighter_1], **kwargs_one)
        _update_state(states[fighter_2], **kwargs_two)
        pair_counts[(canonical_a, canonical_b)] += 1
        updates += 1

    table = pd.DataFrame(records)
    missing = sorted(set(ALL_FEATURES) - set(table.columns))
    if missing:
        raise GovernanceError(f"FEATURE_CONTRACT_MISSING:{','.join(missing)}")
    if table["fight_id"].duplicated().any():
        raise GovernanceError("DUPLICATE_MODEL_ROW")
    return table, {
        "rows": len(table),
        "stateUpdates": updates,
        "skippedUpdates": dict(sorted(skipped_updates.items())),
        "maxDate": str(end.date()),
        "featureCount": len(ALL_FEATURES),
        "targetStatisticsUsedBeforeTarget": False,
    }


def split_role(values: Iterable[pd.Timestamp]) -> list[str]:
    roles = []
    for value in values:
        if value <= pd.Timestamp(DEV_END):
            roles.append("DEVELOPMENT")
        elif value <= pd.Timestamp(VALIDATION_END):
            roles.append("VALIDATION")
        else:
            roles.append("FINAL_OOT")
    return roles


def feature_contract() -> dict[str, Any]:
    return {
        "modelId": MODEL_ID,
        "rowGrain": "one decisive UFC bout in deterministic canonical fighter-ID orientation",
        "cutoffSemantics": "all rolling state uses completed source rows with event_date strictly earlier than target event_date",
        "dateResolution": "calendar day; modern data has zero repeated fighter/date observations",
        "numericFeatures": list(NUMERIC_FEATURES),
        "categoricalFeatures": list(CATEGORICAL_FEATURES),
        "excludedCurrentSnapshotFields": ["fighter W/L/D", "belt", "Fighters Stats.csv aggregates"],
        "excludedUnsupportedFields": ["age/DOB", "rankings", "odds", "weigh-ins", "short notice", "injuries"],
        "targetBoutStats": "update-only after pre-bout vector emission",
        "orientation": "fighter_a_id=min(source fighter IDs); reverse query returns 1-p without rescoring",
        "probabilitySemantics": "P(canonical fighter A wins | decisive result, reconstructed pre-bout history)",
    }

