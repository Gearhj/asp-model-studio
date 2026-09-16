"""Explicit prospective authorization for unchanged, frozen V18 mathematics.

This is a transform-only capability, never a fitting or Final OOT exception.
The publisher authenticates a complete source snapshot before issuing this
typed authority; inference retains its real event date and immutable digest.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import re
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


ATTR = "MLB_V18_PROSPECTIVE_FRAME_AUTHORITY_V1"
LEGACY_SEMANTIC_SHA = "b4bba155dc6b9b12c38ecf7c6d4b9ba3e2dff9e0bab7e74c7c67be80f44c121d"
# Exact successor hash, not a blanket checksum bypass. Original source remains
# immutable in commit d68ac6b1eea3f1174d929c74984312d9dd51436d.
PROSPECTIVE_SEMANTIC_SHA = "327354b46506ee1e60763c8e2ae13996a774dc93a6afaa96a15574f23a3d84a5"
LEGACY_INTERACTION_SHA = "f065b8df5c7f8326dc7c1bb0557d6f613a719f8f5be72171e573a6e55cd94925"
PROSPECTIVE_INTERACTION_SHA = "e5d4fb41938d580e085311a4832a461227480b90c55d720d1174b8ecb33bd3f5"


class ProspectiveAuthorityError(ValueError):
    pass


def _utc(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ProspectiveAuthorityError("Prospective evidence timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ProspectiveFrameAuthority:
    event_id: str
    game_date: str
    evidence_cutoff_utc: str
    kickoff_utc: str
    snapshot_sha256: str
    authorized_at_utc: str
    venue_timezone: str

    def validate(self) -> None:
        cutoff, kickoff, authorized = (_utc(self.evidence_cutoff_utc), _utc(self.kickoff_utc), _utc(self.authorized_at_utc))
        now = datetime.now(timezone.utc)
        if not self.event_id or re.fullmatch(r"[0-9a-f]{64}", self.snapshot_sha256) is None:
            raise ProspectiveAuthorityError("Canonical event and verified source snapshot SHA-256 required")
        if not cutoff <= authorized <= now < kickoff:
            raise ProspectiveAuthorityError("Prospective source cutoff/authorization must precede current pregame execution")
        try:
            expected_date = kickoff.astimezone(ZoneInfo(self.venue_timezone)).date().isoformat()
        except (ValueError, KeyError) as exc:
            raise ProspectiveAuthorityError("Explicit valid venue timezone required") from exc
        if self.game_date != expected_date or self.game_date <= "2026-08-27":
            raise ProspectiveAuthorityError("Only the real post-Final-OOT event date is authorized")


def has_prospective_authority(frame: pd.DataFrame) -> bool:
    """Validate metadata/date/identities before any numerical payload access."""
    authority = frame.attrs.get(ATTR)
    if authority is None:
        return False
    if not isinstance(authority, ProspectiveFrameAuthority):
        raise ProspectiveAuthorityError("An explicit typed prospective authority is required")
    authority.validate()
    forbidden = [str(name) for name in frame.columns if str(name).lower() in {
        "outcome", "target", "observedclassindex", "label", "y", "home_win", "away_win"
    } or str(name).lower().startswith(("target_", "outcome_", "closing_"))]
    if forbidden:
        raise ProspectiveAuthorityError("Target/outcome columns prohibited in prospective transform")
    if "game_date" not in frame:
        raise ProspectiveAuthorityError("Real game_date is required")
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if dates.isna().any() or not dates.eq(pd.Timestamp(authority.game_date)).all():
        raise ProspectiveAuthorityError("Prospective rows must use their actual authorized event date")
    if "canonicalGameId" in frame and not frame.canonicalGameId.astype(str).eq(authority.event_id).all():
        raise ProspectiveAuthorityError("Prospective event identity mismatch")
    return True


def authorize_frame(frame: pd.DataFrame, authority: ProspectiveFrameAuthority) -> pd.DataFrame:
    """Attach authorization without rewriting any date, identity or feature."""
    result = frame.copy()
    existing = result.attrs.get(ATTR)
    if existing is not None and existing != authority:
        raise ProspectiveAuthorityError("A different prospective snapshot authority is already attached")
    result.attrs[ATTR] = authority
    has_prospective_authority(result)
    return result


def semantic_code_compatible(fitted_sha: str, current_sha: str) -> bool:
    """Only the reviewed V1 guard-only successor can consume the old fit."""
    return (fitted_sha, current_sha) == (LEGACY_SEMANTIC_SHA, PROSPECTIVE_SEMANTIC_SHA)


def interaction_code_compatible(fitted_configuration_sha: str, current_configuration: dict) -> bool:
    """Numerical configuration must remain identical; only the pinned code changes."""
    from ..sports_datasets.consumer import canonical_json_bytes
    if current_configuration.get("implementationSha256") != PROSPECTIVE_INTERACTION_SHA:
        return False
    legacy = {**current_configuration, "implementationSha256": LEGACY_INTERACTION_SHA}
    return hashlib.sha256(canonical_json_bytes(legacy)).hexdigest() == fitted_configuration_sha


class ProspectiveFrozenPreprocessor:
    """Instance-local delegation; never mutate the pickle or global functions."""
    def __init__(self, frozen: Any, authority: ProspectiveFrameAuthority):
        authority.validate()
        self.frozen = frozen
        self.authority = authority
        self.encoder = frozen.encoder
        self.ordered_features = frozen.ordered_features
        self.source_columns = frozen.source_columns

    def transform_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        return self.frozen.transform_frame(authorize_frame(frame, self.authority))

    def transform(self, frame: pd.DataFrame) -> Any:
        return self.encoder.transform(self.transform_frame(frame))

    def get_feature_names_out(self, input_features: Any = None) -> Any:
        return self.frozen.get_feature_names_out(input_features)


def wrap_prospective_pipeline(pipeline: Any, authority: ProspectiveFrameAuthority) -> Any:
    """Adapter consumed directly by V18StateProbabilityProvider; no date spoofing."""
    from .stage3_corrected_preprocessing_artifacts import FrozenCorrectedPreprocessor
    from .stage3_model_laboratory import Stage3FittedPipeline
    if not isinstance(pipeline, Stage3FittedPipeline) or not isinstance(pipeline.preprocessor, FrozenCorrectedPreprocessor):
        raise ProspectiveAuthorityError("The accepted frozen corrected V18 pipeline is required")
    return Stage3FittedPipeline(ordered_features=pipeline.ordered_features, target_order=pipeline.target_order,
        preprocessor=ProspectiveFrozenPreprocessor(pipeline.preprocessor, authority), estimator=pipeline.estimator)


def load_prospective_pipeline(model_path: str | Path, expected_sha256: str,
                              authority: ProspectiveFrameAuthority) -> Any:
    """Hash-authenticate the accepted local fold-5 artifact before unpickling."""
    import joblib
    from .mlb_v18_daily_slate import PA_MODEL_SHA256
    path = Path(model_path).resolve()
    root = Path(__file__).resolve().parents[2]
    if expected_sha256 != PA_MODEL_SHA256 or not path.is_relative_to(root):
        raise ProspectiveAuthorityError("Accepted V18 artifact identity and Model Studio path required")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ProspectiveAuthorityError("Accepted V18 artifact SHA-256 mismatch")
    return wrap_prospective_pipeline(joblib.load(path), authority)
