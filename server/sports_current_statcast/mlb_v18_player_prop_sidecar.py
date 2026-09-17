"""Passive named-player counters for an unchanged MLB V18 simulation population.

The collector consumes the simulator's existing event-observer stream.  It has
no model, RNG, filesystem, provider, publication, or settlement dependency.
Names are display metadata only; joins use frozen canonical player identities.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import zlib
from typing import Any, Mapping, Sequence

import numpy as np

from server.sports_modeling.metrics import PA_CLASS_ORDER


SCHEMA_VERSION = "ASP_MLB_V18_PLAYER_PROP_POPULATION_V1"
PROBABILITY_SCHEMA = "ASP_MLB_V18_PLAYER_PROP_PROBABILITY_V1"
TEAM_ORDER = ("AWAY", "HOME")
BATTER_STATS = ("PA", "SINGLE", "DOUBLE", "TRIPLE", "HOME_RUN", "HITS", "TOTAL_BASES")
PITCHER_STATS = ("BATTERS_FACED", "STRIKEOUTS")
SUPPORTED_PROPS = {
    "BATTER_TO_RECORD_1_PLUS_HIT": "HITS",
    "BATTER_HITS": "HITS",
    "BATTER_TOTAL_BASES": "TOTAL_BASES",
    "BATTER_HOME_RUN": "HOME_RUN",
    "BATTER_HOME_RUNS": "HOME_RUN",
    "STARTING_PITCHER_STRIKEOUTS": "STRIKEOUTS",
}


class PlayerPropSidecarError(ValueError):
    """Fail-closed player-prop population or query error."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_identity(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlayerPropSidecarError("IDENTITY_INCOMPLETE", f"{field} is required")
    return value


def _encode_vector(values: np.ndarray) -> dict[str, Any]:
    array = np.asarray(values, dtype="<u2")
    if array.ndim != 1 or (array < 0).any():
        raise PlayerPropSidecarError("INVALID_COUNT_VECTOR", "counts must be one-dimensional nonnegative integers")
    raw = array.tobytes(order="C")
    return {
        "encoding": "BASE64_ZLIB_UINT16_LE_V1",
        "count": int(array.size),
        "rawSha256": sha256_bytes(raw),
        "data": base64.b64encode(zlib.compress(raw, level=9)).decode("ascii"),
    }


def _decode_vector(value: Mapping[str, Any], expected_count: int) -> np.ndarray:
    if value.get("encoding") != "BASE64_ZLIB_UINT16_LE_V1" or int(value.get("count", -1)) != expected_count:
        raise PlayerPropSidecarError("VECTOR_ENCODING_INVALID", "count-vector encoding or length differs")
    try:
        raw = zlib.decompress(base64.b64decode(str(value["data"]), validate=True))
    except Exception as error:
        raise PlayerPropSidecarError("VECTOR_ENCODING_INVALID", "count vector cannot be decoded") from error
    if sha256_bytes(raw) != value.get("rawSha256") or len(raw) != expected_count * 2:
        raise PlayerPropSidecarError("VECTOR_HASH_MISMATCH", "decoded count vector differs from its binding")
    return np.frombuffer(raw, dtype="<u2").astype(np.int64)


class PlayerPropCollector:
    """Collect only statistics directly observable on completed V18 PA events."""

    def __init__(self, n_sims: int) -> None:
        if isinstance(n_sims, bool) or int(n_sims) != n_sims or n_sims <= 0:
            raise PlayerPropSidecarError("INVALID_DRAW_COUNT", "n_sims must be a positive integer")
        self.n_sims = int(n_sims)
        self.batters = np.zeros((self.n_sims, 2, 9, len(BATTER_STATS)), dtype=np.uint16)
        self.starters = np.zeros((self.n_sims, 2, len(PITCHER_STATS)), dtype=np.uint16)
        self.anonymous_relief = np.zeros((self.n_sims, 2, len(PITCHER_STATS)), dtype=np.uint16)
        self.outcomes = np.zeros((self.n_sims, 2, len(PA_CLASS_ORDER)), dtype=np.uint16)
        self._last_pa = np.zeros(self.n_sims, dtype=np.int16)
        self._class = {name: index for index, name in enumerate(PA_CLASS_ORDER)}
        self._finalized = False

    def allocated_bytes(self) -> int:
        """Exact NumPy storage allocated by the passive collector."""
        return int(sum(value.nbytes for value in (
            self.batters, self.starters, self.anonymous_relief,
            self.outcomes, self._last_pa,
        )))

    def __call__(self, simulation: int, event: Mapping[str, Any]) -> None:
        if self._finalized:
            raise PlayerPropSidecarError("COLLECTOR_FINALIZED", "events cannot follow finalization")
        s = int(simulation)
        if not 0 <= s < self.n_sims:
            raise PlayerPropSidecarError("EVENT_INVALID", "simulation index is outside the population")
        pa = int(event.get("pa", -1))
        if pa != int(self._last_pa[s]) + 1:
            raise PlayerPropSidecarError("EVENT_SEQUENCE_INVALID", "completed PA sequence is missing or duplicated")
        half = str(event.get("half"))
        if half not in {"TOP", "BOTTOM"}:
            raise PlayerPropSidecarError("EVENT_INVALID", "half must be TOP or BOTTOM")
        batting = 0 if half == "TOP" else 1
        pitching = 1 - batting
        slot = int(event.get("battingOrderPosition", 0)) - 1
        outcome = str(event.get("outcome"))
        pitcher_state = str(event.get("pitcherState"))
        if not 0 <= slot < 9 or outcome not in self._class or pitcher_state not in {"STARTER", "TEAM_BULLPEN"}:
            raise PlayerPropSidecarError("EVENT_INVALID", "event identity or class is unsupported")
        row = self.batters[s, batting, slot]
        row[0] += 1
        if outcome == "SINGLE":
            row[1] += 1; row[5] += 1; row[6] += 1
        elif outcome == "DOUBLE":
            row[2] += 1; row[5] += 1; row[6] += 2
        elif outcome == "TRIPLE":
            row[3] += 1; row[5] += 1; row[6] += 3
        elif outcome == "HOME_RUN":
            row[4] += 1; row[5] += 1; row[6] += 4
        pitcher = self.starters if pitcher_state == "STARTER" else self.anonymous_relief
        pitcher[s, pitching, 0] += 1
        if outcome == "STRIKEOUT":
            pitcher[s, pitching, 1] += 1
        self.outcomes[s, batting, self._class[outcome]] += 1
        self._last_pa[s] = pa

    def finalize(self, population: Mapping[str, Any], *, diagnostic_arrays: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if self._finalized or int(population.get("simulationCount", -1)) != self.n_sims:
            raise PlayerPropSidecarError("FINALIZATION_INVALID", "population count differs or collector was reused")
        saved_pa = np.asarray(population.get("paCounts"))
        if saved_pa.shape != (self.n_sims,):
            raise PlayerPropSidecarError("POPULATION_INVALID", "saved PA counts are unavailable")
        batter_pa = self.batters[..., 0].sum(axis=(1, 2)).astype(np.int64)
        hits = self.batters[..., 1:5].sum(axis=-1)
        total_bases = (self.batters[..., 1] + 2*self.batters[..., 2]
                       + 3*self.batters[..., 3] + 4*self.batters[..., 4])
        class_total = self.outcomes.sum(axis=(1, 2)).astype(np.int64)
        checks = {
            "batterPAEqualSavedPA": bool(np.array_equal(batter_pa, saved_pa)),
            "outcomeCountsEqualSavedPA": bool(np.array_equal(class_total, saved_pa)),
            "batterHitsEqualComponentHits": bool(np.array_equal(self.batters[..., 5], hits)),
            "batterTotalBasesEqualComponents": bool(np.array_equal(self.batters[..., 6], total_bases)),
            "batterPAEqualTeamOutcomeCounts": bool(np.array_equal(self.batters[..., 0].sum(axis=2), self.outcomes.sum(axis=-1))),
            "starterPlusAnonymousReliefBFEqualOpponentPA": bool(np.array_equal(
                self.starters[..., 0] + self.anonymous_relief[..., 0],
                self.batters[..., 0].sum(axis=2)[:, ::-1])),
        }
        if diagnostic_arrays is not None:
            completed = np.asarray(diagnostic_arrays["completed_pa"]).sum(axis=2)
            outcomes = np.asarray(diagnostic_arrays["outcome_counts"]).sum(axis=2)
            checks["teamPAEqualPassiveDiagnostics"] = bool(np.array_equal(self.batters[..., 0].sum(axis=2), completed))
            checks["teamOutcomesEqualPassiveDiagnostics"] = bool(np.array_equal(self.outcomes, outcomes))
            checks["starterBFEqualPassiveDiagnostics"] = bool(np.array_equal(
                self.starters[..., 0], np.asarray(diagnostic_arrays["starter_final_bf"])))
        if not all(checks.values()):
            failed = ", ".join(name for name, passed in checks.items() if not passed)
            raise PlayerPropSidecarError("ACCOUNTING_MISMATCH", failed)
        self._finalized = True
        return {
            "checks": checks,
            "allPassed": True,
            "completedPATotal": int(batter_pa.sum()),
            "completedPAByBattingTeam": self.batters[..., 0].sum(axis=(0, 2)).astype(int).tolist(),
            "starterBFByPitchingTeam": self.starters[..., 0].sum(axis=0).astype(int).tolist(),
            "anonymousReliefBFByPitchingTeam": self.anonymous_relief[..., 0].sum(axis=0).astype(int).tolist(),
        }


def _participants(lineups: Mapping[str, Sequence[Mapping[str, Any]]], starters: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    batters: list[dict[str, Any]] = []
    pitchers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for side in TEAM_ORDER:
        rows = list(lineups.get(side) or [])
        if len(rows) != 9:
            raise PlayerPropSidecarError("LINEUP_BINDING_INVALID", f"{side} lineup must contain nine players")
        for slot, row in enumerate(rows, 1):
            player_id = _require_identity(row.get("playerId"), "lineup.playerId")
            if player_id in seen or int(row.get("battingOrderPosition", -1)) != slot:
                raise PlayerPropSidecarError("LINEUP_BINDING_INVALID", "canonical player or batting slot is duplicated/misaligned")
            seen.add(player_id)
            batters.append({"side": side, "battingOrderPosition": slot, "playerId": player_id,
                            "mlbamId": _require_identity(row.get("mlbamId"), "lineup.mlbamId"),
                            "displayName": str(row.get("displayName") or ""),
                            "teamId": _require_identity(row.get("teamId"), "lineup.teamId"),
                            "modelTemplatePlayerId": _require_identity(row.get("modelTemplatePlayerId"), "lineup.modelTemplatePlayerId")})
        starter = starters.get(side) or {}
        pitchers.append({"side": side, "role": "STARTING_PITCHER",
                         "playerId": _require_identity(starter.get("playerId"), "starter.playerId"),
                         "mlbamId": _require_identity(starter.get("mlbamId"), "starter.mlbamId"),
                         "displayName": str(starter.get("displayName") or ""),
                         "teamId": _require_identity(starter.get("teamId"), "starter.teamId"),
                         "modelTemplatePlayerId": _require_identity(starter.get("modelTemplatePlayerId"), "starter.modelTemplatePlayerId")})
    return batters, pitchers


def build_sidecar(*, collector: PlayerPropCollector, accounting: Mapping[str, Any], binding: Mapping[str, Any],
                  lineups: Mapping[str, Sequence[Mapping[str, Any]]], starters: Mapping[str, Mapping[str, Any]],
                  created_at: str) -> tuple[bytes, str]:
    required = ("gameId", "sourceGameId", "forecastId", "forecastObjectSha256", "populationSha256",
                "modelId", "modelArtifactSha256", "transitionArtifactSha256", "sourceCutoff",
                "forecastCreatedAt", "simulationCount", "masterSeed")
    if any(name not in binding or binding[name] in (None, "") for name in required):
        raise PlayerPropSidecarError("BINDING_INCOMPLETE", "sidecar binding is incomplete")
    if int(binding["simulationCount"]) != collector.n_sims:
        raise PlayerPropSidecarError("DRAW_COUNT_MISMATCH", "binding and collector counts differ")
    batters, pitchers = _participants(lineups, starters)
    batter_rows = []
    for participant in batters:
        team = TEAM_ORDER.index(participant["side"])
        slot = participant["battingOrderPosition"] - 1
        batter_rows.append({**participant, "statistics": {
            stat: _encode_vector(collector.batters[:, team, slot, index])
            for index, stat in enumerate(BATTER_STATS)}})
    pitcher_rows = []
    for participant in pitchers:
        team = TEAM_ORDER.index(participant["side"])
        pitcher_rows.append({**participant, "statistics": {
            stat: _encode_vector(collector.starters[:, team, index])
            for index, stat in enumerate(PITCHER_STATS)}})
    document = {
        "schemaVersion": SCHEMA_VERSION,
        "createdAt": _require_identity(created_at, "createdAt"),
        "binding": dict(binding),
        "definitions": {
            "teamOrder": list(TEAM_ORDER), "paClassOrder": list(PA_CLASS_ORDER),
            "batterStatistics": list(BATTER_STATS), "startingPitcherStatistics": list(PITCHER_STATS),
            "hits": "SINGLE + DOUBLE + TRIPLE + HOME_RUN",
            "totalBases": "SINGLE + 2*DOUBLE + 3*TRIPLE + 4*HOME_RUN",
            "startingPitcher": "Counts only opponent completed PAs while simulator pitcherState is STARTER.",
            "anonymousRelief": "Existing TEAM_BULLPEN mixture remains anonymous; no named-reliever props are supported.",
        },
        "batters": batter_rows,
        "startingPitchers": pitcher_rows,
        "anonymousReliefSummary": {side: {
            stat: _encode_vector(collector.anonymous_relief[:, i, j])
            for j, stat in enumerate(PITCHER_STATS)} for i, side in enumerate(TEAM_ORDER)},
        "accounting": dict(accounting),
        "limitations": [
            "Population is conditional on the frozen confirmed starting lineups and named starters.",
            "No bench, pinch-hitter, defensive-substitution, injury, late-scratch, cancellation, postponement, or sportsbook void model exists.",
            "Starting-pitcher removal follows the unchanged V18 hook; relief uses anonymous team templates.",
            "This sidecar has no calibration, wagering, publication, decision, or model-promotion authority.",
        ],
        "authority": {"researchOnly": True, "exchangePublication": False, "aispAssessment": False,
                      "wagering": False, "modelPromotion": False},
    }
    payload = canonical_json_bytes(document)
    return payload, sha256_bytes(payload)


def verify_sidecar(payload: bytes, expected_sha256: str) -> dict[str, Any]:
    if sha256_bytes(payload) != expected_sha256:
        raise PlayerPropSidecarError("SIDECAR_HASH_MISMATCH", "physical bytes differ from expected SHA-256")
    try:
        document = json.loads(payload)
    except Exception as error:
        raise PlayerPropSidecarError("SIDECAR_INVALID", "sidecar is not valid JSON") from error
    if canonical_json_bytes(document) != payload or document.get("schemaVersion") != SCHEMA_VERSION:
        raise PlayerPropSidecarError("SIDECAR_INVALID", "sidecar is noncanonical or has the wrong schema")
    n = int((document.get("binding") or {}).get("simulationCount", 0))
    if n <= 0 or len(document.get("batters") or []) != 18 or len(document.get("startingPitchers") or []) != 2:
        raise PlayerPropSidecarError("SIDECAR_INVALID", "participant population is incomplete")
    for row in list(document["batters"]) + list(document["startingPitchers"]):
        for vector in row["statistics"].values():
            _decode_vector(vector, n)
    return document


def evaluate_player_prop(payload: bytes, expected_sha256: str, query: Mapping[str, Any]) -> dict[str, Any]:
    """Pure empirical settlement over one exact named-player draw vector."""
    document = verify_sidecar(payload, expected_sha256)
    expected_binding = query.get("expectedBinding") or {}
    for field in ("gameId", "forecastId", "populationSha256"):
        if field in expected_binding and expected_binding[field] != document["binding"].get(field):
            raise PlayerPropSidecarError("QUERY_BINDING_MISMATCH", f"{field} differs from the sidecar")
    expected_lineup = query.get("expectedLineupObservationId")
    if expected_lineup is not None:
        side = str(query.get("side", "")).upper()
        actual = ((document["binding"].get("lineupAuthorities") or {}).get(side) or {}).get("observationId")
        if side not in TEAM_ORDER or actual != expected_lineup:
            raise PlayerPropSidecarError("LINEUP_REVISION_MISMATCH", "query lineup revision differs from the sidecar")
    prop = str(query.get("propType", "")).upper()
    statistic = SUPPORTED_PROPS.get(prop)
    if statistic is None:
        raise PlayerPropSidecarError("PROP_UNSUPPORTED", "requested prop is not directly retained")
    player_id = _require_identity(query.get("playerId"), "query.playerId")
    role = "startingPitchers" if prop == "STARTING_PITCHER_STRIKEOUTS" else "batters"
    matches = [row for row in document[role] if row["playerId"] == player_id]
    if len(matches) != 1:
        raise PlayerPropSidecarError("PLAYER_NOT_IN_FROZEN_ROLE", "player is not uniquely bound to the required frozen role")
    row = matches[0]
    n = int(document["binding"]["simulationCount"])
    values = _decode_vector(row["statistics"][statistic], n)
    selection = str(query.get("selection", "")).upper()
    if prop in {"BATTER_HITS", "BATTER_TO_RECORD_1_PLUS_HIT"} and selection == "YES":
        line = 0.5
        selection = "OVER"
        requested = {"propType": "BATTER_TO_RECORD_1_PLUS_HIT", "selection": "YES", "line": 0.5}
    elif prop in {"BATTER_HOME_RUN", "BATTER_HOME_RUNS"} and selection in {"YES", "NO"}:
        line = 0.5
        selection = "OVER" if selection == "YES" else "UNDER"
        requested = {"propType": "BATTER_HOME_RUN", "selection": str(query["selection"]).upper(), "line": 0.5}
    else:
        try:
            line = float(query.get("line"))
        except (TypeError, ValueError) as error:
            raise PlayerPropSidecarError("LINE_INVALID", "line must be an integer or half-integer") from error
        if not math.isfinite(line) or line < 0 or line * 2 != math.floor(line * 2):
            raise PlayerPropSidecarError("LINE_INVALID", "line must be a nonnegative integer or half-integer")
        if selection not in {"OVER", "UNDER"}:
            raise PlayerPropSidecarError("SELECTION_INVALID", "selection must be OVER or UNDER")
        requested = {"propType": prop, "selection": selection, "line": line}
    delta = values - line
    if selection == "UNDER":
        delta = -delta
    win = int((delta > 0).sum()); loss = int((delta < 0).sum()); push = int((delta == 0).sum())
    if win + loss + push != n:
        raise PlayerPropSidecarError("PROBABILITY_MASS_MISMATCH", "settlement counts do not reconcile")
    pwin, ploss, ppush = win/n, loss/n, push/n
    return {
        "schemaVersion": PROBABILITY_SCHEMA,
        "status": "SUPPORTED_CONDITIONAL_EMPIRICAL_POPULATION",
        "probabilityUnits": "FRACTION_0_TO_1",
        "binding": {**document["binding"], "sidecarSha256": expected_sha256},
        "player": {key: row[key] for key in ("side", "role", "playerId", "mlbamId", "displayName") if key in row},
        "market": requested,
        "counts": {"win": win, "loss": loss, "push": push, "void": None},
        "probabilities": {"pWin": pwin, "pLoss": ploss, "pPush": ppush, "pVoid": None},
        "drawCount": n,
        "winProbabilityMonteCarloStandardError": math.sqrt(pwin * (1-pwin) / n),
        "voidStatus": "UNSUPPORTED",
        "conditionality": "Conditional on the frozen player starting in the bound lineup/role and the game being graded under compatible house rules.",
        "authority": {"researchOnly": True, "displayAssessmentAuthorized": False, "fairPriceAuthorized": False,
                      "edgeAuthorized": False, "decisionAuthorized": False, "positionAuthorized": False},
    }


__all__ = ["BATTER_STATS", "PITCHER_STATS", "PlayerPropCollector", "PlayerPropSidecarError",
           "SCHEMA_VERSION", "build_sidecar", "canonical_json_bytes", "evaluate_player_prop",
           "sha256_bytes", "verify_sidecar"]
