"""D3 probabilistic plate-appearance provider (D3_PROBABILISTIC_PA_PROVIDER_V1).

Phase 5C simulation-input component. This provider does not train, refit, or modify D3. It
LOADS the already-governed, data-only D3 model-state and preprocessor JSON artifacts
(hash-verified before any deserialization), reconstructs the exact governed scoring path
(``FoldPreprocessor`` + multinomial-logistic softmax), and returns the frozen eight-class PA
probability vector for a simulation-time invocation context.

Temporal contract preserved: the cumulative batter/pitcher B-state is history strictly
before the game date, so it is FROZEN per game and never accumulates within a simulated
game; only the current game-state context (inning / half / outs / base mask / score
differential) varies per plate appearance. No target PA result, no later PA evidence, no
current-game cumulative player evidence, and no final score enter the feature vector.

There is one D3 model per temporal fold: the 2024 fold (trained on 2023) scores 2024 games;
the 2025 fold (trained on 2023-2024) scores 2025 games. The provider selects the model by the
game's season, reproducing the frozen ``raw_D3`` predictions bit-for-bit.

No whole-game Monte Carlo, no win/run-line/total probabilities, no betting logic, no network
or provider calls. Data-only artifacts (JSON) — no pickle/joblib/executable deserialization.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_modeling.training import FoldPreprocessor, MultinomialCandidateModel
from server.sports_phase4.dynamic_contract import (
    BATTER_CUMULATIVE_FEATURES,
    CANDIDATE_FEATURES,
    PHASE3_FEATURE_CONTENT_SHA,
    PHASE3_FEATURE_CONTRACT_SHA,
    PITCHER_CUMULATIVE_FEATURES,
    STATE_VALUE_COLUMNS,
    dynamic_state_contract_sha,
)

PA_PROVIDER_CONTRACT_NAME = "D3_PROBABILISTIC_PA_PROVIDER_V1"
PA_PROVIDER_SCHEMA_VERSION = "D3_PROBABILISTIC_PA_PROVIDER_V1"
D3_CANDIDATE_ID = "D3"

# Immutable eight-class order (index -> label). Never reordered.
CLASS_ORDER: tuple[str, ...] = tuple(PA_CLASS_ORDER)
D3_FEATURE_NAMES: tuple[str, ...] = tuple(CANDIDATE_FEATURES["D3"])
CONTEXT_FEATURE_NAMES: tuple[str, ...] = (
    "context_inning",
    "context_top_bottom",
    "context_outs_before",
    "context_base_mask_before",
    "context_batting_score_diff_before",
)

# Pinned governed D3 authority: exact content-addressed SHA-256 of each data-only artifact.
# Hash verification happens BEFORE deserialization (governed security rule). These are the
# artifacts persisted by MLB_DYNAMIC_PLAYER_STATE_V1 (selected challenger candidate D3).
D3_MODEL_ARTIFACT_SHA: Mapping[int, str] = {
    2024: "af6c0a464bb768536c37b866103ac3abadeb1824f4d6bcf5435cb4092087238f",
    2025: "722aeed943449591f3d784b287f1dd70723a1b0eeff2dbebba288fb87954a8be",
}
D3_PREPROCESSOR_ARTIFACT_SHA: Mapping[int, str] = {
    2024: "3a159b7123e08ea9ab0fe3a97abd8aa74fefa359e3032e487c4c925c5dfcfbea",
    2025: "83024194f1b03e8f6200fedbac47e393d79d3df85131b3cbe8e01d2ce653cf91",
}
D3_STATE_TABLE_SHA = "6117988df812bb35dc0fdafd7f8b78d0c0a62a8454e598e4271f2da148bf3b03"
D3_FOLD_PREDICTION_SHA: Mapping[int, str] = {
    2024: "d7a692988bc58ef5d8aff070d62403b0f6a73e46d28ee2d69221112f002e7ad5",
    2025: "3b262e600697a3be6d6fb7889b457d8f46a50f68876d2f0ba314404f89f71ee1",
}
D3_MODEL_FILENAME = {2024: "model-D3-validate-2024.json", 2025: "model-D3-validate-2025.json"}
D3_PREPROCESSOR_FILENAME = {
    2024: "preprocessor-D3-validate-2024.json",
    2025: "preprocessor-D3-validate-2025.json",
}

PROBABILITY_SUM_TOLERANCE = 1e-9
SUPPORTED_SEASONS: tuple[int, ...] = (2024, 2025)


class PAProviderError(RuntimeError):
    """Fail-closed error for authority, artifact-integrity, or invocation faults."""


# --------------------------------------------------------------------------------------
# Hash-verified, data-only artifact loading (no pickle / joblib / executable deserialization)
# --------------------------------------------------------------------------------------
def _content_addressed_path(namespace_root: Path, sha: str, filename: str) -> Path:
    if not (isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
        raise PAProviderError("artifact SHA-256 must be lowercase 64-hex")
    safe = PurePosixPath(filename)
    if safe.is_absolute() or any(part in {"", ".", ".."} for part in safe.parts) or len(safe.parts) != 1:
        raise PAProviderError("artifact filename is unsafe")
    return namespace_root / "objects" / "sha256" / sha[:2] / sha / filename


def _load_verified_json(namespace_root: Path, sha: str, filename: str) -> dict[str, Any]:
    path = _content_addressed_path(namespace_root, sha, filename)
    if not path.is_file():
        raise PAProviderError(f"governed D3 artifact is missing: {filename}")
    content = path.read_bytes()
    observed = hashlib.sha256(content).hexdigest()
    if observed != sha:  # verify BEFORE json.loads
        raise PAProviderError(f"governed D3 artifact SHA mismatch for {filename}")
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise PAProviderError("governed D3 artifact envelope must be a JSON object")
    return value


def _reconstruct_fold_model(
    namespace_root: Path, season: int
) -> MultinomialCandidateModel:
    """Load and verify the data-only D3 model/preprocessor JSON and rebuild the scorer."""

    if season not in D3_MODEL_ARTIFACT_SHA:
        raise PAProviderError(f"no governed D3 fold model for season {season}")
    from sklearn.linear_model import LogisticRegression

    model_env = _load_verified_json(
        namespace_root, D3_MODEL_ARTIFACT_SHA[season], D3_MODEL_FILENAME[season]
    )
    prep_env = _load_verified_json(
        namespace_root, D3_PREPROCESSOR_ARTIFACT_SHA[season], D3_PREPROCESSOR_FILENAME[season]
    )
    if model_env.get("artifactType") != "DYNAMIC_MODEL_STATE":
        raise PAProviderError("D3 model artifact type differs")
    if prep_env.get("artifactType") != "DYNAMIC_PREPROCESSOR_STATE":
        raise PAProviderError("D3 preprocessor artifact type differs")
    mp = model_env["payload"]
    pp = prep_env["payload"]
    if mp.get("candidateId") != D3_CANDIDATE_ID or pp.get("candidateId") != D3_CANDIDATE_ID:
        raise PAProviderError("D3 artifact candidate identity differs")
    if int(mp.get("validationSeason")) != season or int(pp.get("validationSeason")) != season:
        raise PAProviderError("D3 artifact fold season differs")
    if mp.get("featureContentSha") != PHASE3_FEATURE_CONTENT_SHA:
        raise PAProviderError("D3 artifact feature-content authority differs")

    model = mp["model"]
    prep = pp["preprocessor"]
    if list(model.get("classOrder", [])) != list(CLASS_ORDER):
        raise PAProviderError("D3 model class order differs from frozen authority")
    if list(model.get("classes", [])) != list(range(len(CLASS_ORDER))):
        raise PAProviderError("D3 model class indices differ")
    if tuple(prep.get("featureNames", ())) != D3_FEATURE_NAMES:
        raise PAProviderError("D3 preprocessor feature contract differs")

    preprocessor = FoldPreprocessor(
        feature_names=tuple(prep["featureNames"]),
        numeric_state={k: dict(v) for k, v in prep["numericState"].items()},
    )
    estimator = LogisticRegression()
    estimator.coef_ = np.asarray(model["coefficients"], dtype=np.float64)
    estimator.intercept_ = np.asarray(model["intercepts"], dtype=np.float64)
    estimator.classes_ = np.asarray(model["classes"], dtype=np.int64)
    estimator.n_iter_ = np.asarray([int(model["nIter"])], dtype=np.int32)
    if estimator.coef_.shape != (len(CLASS_ORDER), len(prep["expandedFeatureNames"])):
        raise PAProviderError("D3 coefficient matrix shape differs from expanded features")
    return MultinomialCandidateModel(
        preprocessor, estimator, float(model["C"]), int(model["maxIter"])
    )


# --------------------------------------------------------------------------------------
# Frozen prior-date player B-state resolver
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PlayerStateResolver:
    """Frozen (game_date, role, canonical_uuid) -> cumulative B-state feature vector.

    Backed by the governed dynamic-player-state B_CUMULATIVE table. The row always exists
    for a player with a target PA on that date (missing-history players are shrunk to the
    role-league prior and carry ``missing_history=1``), so the governed missing-history
    policy is used directly and no league-average fallback is invented.
    """

    _by_key: Mapping[tuple[str, str, str], tuple[float, ...]]
    state_table_sha: str

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        *,
        state_table_sha: str,
    ) -> "PlayerStateResolver":
        by_key: dict[tuple[str, str, str], tuple[float, ...]] = {}
        for row in records:
            if row.get("state_kind") != "B_CUMULATIVE":
                continue
            key = (str(row["game_date"]), str(row["role"]), str(row["canonical_player_uuid"]))
            values = tuple(
                float(row[name]) if row[name] is not None and not _is_nan(row[name]) else math.nan
                for name in STATE_VALUE_COLUMNS
            )
            if key in by_key and by_key[key] != values:
                raise PAProviderError("duplicate conflicting B-state key")
            by_key[key] = values
        return cls(_by_key=by_key, state_table_sha=state_table_sha)

    def has(self, canonical_uuid: str, role: str, game_date: str) -> bool:
        return (str(game_date), str(role), str(canonical_uuid)) in self._by_key

    def resolve(self, canonical_uuid: str, role: str, game_date: str) -> tuple[float, ...]:
        key = (str(game_date), str(role), str(canonical_uuid))
        values = self._by_key.get(key)
        if values is None:
            raise PAProviderError(
                f"unresolved governed B-state for {role} {canonical_uuid} @ {game_date}"
            )
        return values

    def missing_history(self, canonical_uuid: str, role: str, game_date: str) -> bool:
        values = self.resolve(canonical_uuid, role, game_date)
        idx = STATE_VALUE_COLUMNS.index("missing_history")
        return bool(values[idx] > 0.5)


def _is_nan(value: Any) -> bool:
    try:
        return isinstance(value, float) and math.isnan(value)
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------------------
# Invocation context and response
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PAInvocationContext:
    """Simulation-time invocation context for one plate appearance."""

    game_id: str
    game_date: str
    season: int
    inning: int
    top: bool  # True = top half (visitor batting), matches top_bottom == 0
    outs_before: int
    base_mask_before: int
    batting_score_diff_before: int
    batter_uuid: str
    pitcher_uuid: str

    def context_top_bottom(self) -> int:
        return 0 if self.top else 1


@dataclass(frozen=True)
class PAProbabilityResponse:
    class_order: tuple[str, ...]
    probabilities: tuple[float, ...]
    model_authority: str
    feature_contract_authority: str
    preprocessing_authority: str
    fold_season: int
    batter_missing_history: bool
    pitcher_missing_history: bool
    warnings: tuple[str, ...] = ()
    valid: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "classOrder": list(self.class_order),
            "probabilities": list(self.probabilities),
            "modelAuthority": self.model_authority,
            "featureContractAuthority": self.feature_contract_authority,
            "preprocessingAuthority": self.preprocessing_authority,
            "foldSeason": self.fold_season,
            "batterMissingHistory": self.batter_missing_history,
            "pitcherMissingHistory": self.pitcher_missing_history,
            "warnings": list(self.warnings),
            "valid": self.valid,
        }


def validate_probability_vector(probabilities: Sequence[float]) -> tuple[bool, tuple[str, ...]]:
    warnings: list[str] = []
    arr = np.asarray(probabilities, dtype=np.float64)
    if arr.shape != (len(CLASS_ORDER),):
        warnings.append("EXPECTED_EIGHT_CLASS_VECTOR")
        return False, tuple(warnings)
    if not np.all(np.isfinite(arr)):
        warnings.append("NON_FINITE_PROBABILITY")
    if np.any(arr < 0.0):
        warnings.append("NEGATIVE_PROBABILITY")
    if np.any(arr > 1.0):
        warnings.append("PROBABILITY_ABOVE_ONE")
    if abs(float(arr.sum()) - 1.0) > PROBABILITY_SUM_TOLERANCE:
        warnings.append("PROBABILITY_SUM_NOT_ONE")
    return (len(warnings) == 0), tuple(warnings)


# --------------------------------------------------------------------------------------
# The provider
# --------------------------------------------------------------------------------------
class D3ProbabilisticPAProvider:
    """Loads governed D3 fold models once and scores simulation-time contexts.

    Model and preprocessor are loaded exactly once per season fold and reused across all PA
    calls (no per-PA model loading). ``score_batch`` builds one feature matrix and issues a
    single vectorized model call, the throughput path for future batched Monte Carlo.
    """

    def __init__(
        self,
        *,
        models: Mapping[int, MultinomialCandidateModel],
        resolver: PlayerStateResolver,
    ) -> None:
        self._models = dict(models)
        self._resolver = resolver
        self._model_authority = dynamic_state_contract_sha()

    @classmethod
    def from_runtime(
        cls,
        *,
        dynamic_namespace_root: Path,
        resolver: PlayerStateResolver,
        seasons: Sequence[int] = SUPPORTED_SEASONS,
    ) -> "D3ProbabilisticPAProvider":
        if resolver.state_table_sha != D3_STATE_TABLE_SHA:
            raise PAProviderError("player-state authority differs from pinned D3 state table")
        models = {
            int(season): _reconstruct_fold_model(dynamic_namespace_root, int(season))
            for season in seasons
        }
        return cls(models=models, resolver=resolver)

    @property
    def model_authority(self) -> str:
        return self._model_authority

    def _model_for(self, season: int) -> MultinomialCandidateModel:
        model = self._models.get(int(season))
        if model is None:
            raise PAProviderError(f"no loaded D3 fold model for season {season}")
        return model

    def _feature_values(
        self, contexts: Sequence[PAInvocationContext]
    ) -> dict[str, np.ndarray]:
        n = len(contexts)
        values: dict[str, np.ndarray] = {
            "context_inning": np.array([c.inning for c in contexts], dtype=np.float64),
            "context_top_bottom": np.array([c.context_top_bottom() for c in contexts], dtype=np.float64),
            "context_outs_before": np.array([c.outs_before for c in contexts], dtype=np.float64),
            "context_base_mask_before": np.array([c.base_mask_before for c in contexts], dtype=np.float64),
            "context_batting_score_diff_before": np.array(
                [c.batting_score_diff_before for c in contexts], dtype=np.float64
            ),
        }
        batter_state = np.empty((n, len(STATE_VALUE_COLUMNS)), dtype=np.float64)
        pitcher_state = np.empty((n, len(STATE_VALUE_COLUMNS)), dtype=np.float64)
        for i, c in enumerate(contexts):
            batter_state[i, :] = self._resolver.resolve(c.batter_uuid, "BATTER", c.game_date)
            pitcher_state[i, :] = self._resolver.resolve(c.pitcher_uuid, "PITCHER", c.game_date)
        for j, name in enumerate(STATE_VALUE_COLUMNS):
            values[f"batter_b_{name}"] = batter_state[:, j]
            values[f"pitcher_b_{name}"] = pitcher_state[:, j]
        return values

    def score_batch(
        self, contexts: Sequence[PAInvocationContext]
    ) -> list[PAProbabilityResponse]:
        if not contexts:
            return []
        seasons = {int(c.season) for c in contexts}
        if len(seasons) != 1:
            raise PAProviderError("score_batch requires a single season fold")
        season = seasons.pop()
        model = self._model_for(season)
        feature_values = self._feature_values(contexts)
        mask = np.ones(len(contexts), dtype=bool)
        matrix = model.predict_proba(feature_values, mask)
        prep_authority = _sha_of_state(model.preprocessor.state())
        responses: list[PAProbabilityResponse] = []
        for i, c in enumerate(contexts):
            probs = tuple(float(x) for x in matrix[i, :])
            valid, warnings = validate_probability_vector(probs)
            responses.append(
                PAProbabilityResponse(
                    class_order=CLASS_ORDER,
                    probabilities=probs,
                    model_authority=self._model_authority,
                    feature_contract_authority=PHASE3_FEATURE_CONTRACT_SHA,
                    preprocessing_authority=prep_authority,
                    fold_season=season,
                    batter_missing_history=self._resolver.missing_history(
                        c.batter_uuid, "BATTER", c.game_date
                    ),
                    pitcher_missing_history=self._resolver.missing_history(
                        c.pitcher_uuid, "PITCHER", c.game_date
                    ),
                    warnings=warnings,
                    valid=valid,
                )
            )
        return responses

    def score(self, context: PAInvocationContext) -> PAProbabilityResponse:
        return self.score_batch([context])[0]

    def sample_class(
        self, context: PAInvocationContext, rng: np.random.Generator
    ) -> tuple[str, PAProbabilityResponse]:
        response = self.score(context)
        if not response.valid:
            raise PAProviderError(f"cannot sample from invalid D3 vector: {response.warnings}")
        idx = int(rng.choice(len(CLASS_ORDER), p=np.asarray(response.probabilities)))
        return CLASS_ORDER[idx], response


def _sha_of_state(state: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


__all__ = [
    "PA_PROVIDER_CONTRACT_NAME",
    "PA_PROVIDER_SCHEMA_VERSION",
    "CLASS_ORDER",
    "D3_FEATURE_NAMES",
    "CONTEXT_FEATURE_NAMES",
    "D3_MODEL_ARTIFACT_SHA",
    "D3_PREPROCESSOR_ARTIFACT_SHA",
    "D3_STATE_TABLE_SHA",
    "D3_FOLD_PREDICTION_SHA",
    "SUPPORTED_SEASONS",
    "PAProviderError",
    "PlayerStateResolver",
    "PAInvocationContext",
    "PAProbabilityResponse",
    "D3ProbabilisticPAProvider",
    "validate_probability_vector",
]
