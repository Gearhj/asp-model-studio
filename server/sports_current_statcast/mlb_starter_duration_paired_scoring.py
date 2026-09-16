"""One-game scoring of frozen duration pairs and narrowly scoped persisted finals.

No provider, model, simulation, position or write interface exists here. Simulation
indices are Monte Carlo replicates within one game, never independent game trials.
The publisher authenticates pair/model/input/population hashes before this layer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA = "MLB_STARTER_DURATION_PAIRED_SCORING_V1"
WIN_LOGLOSS_FLOOR = 1e-12
MINIMUM_PILOT_START = datetime(2026, 9, 11, tzinfo=timezone.utc)
ARM_LABELS = {"reference": "REFERENCE_EXISTING_HOOK", "challenger": "CHALLENGER_HGB_DURATION"}

# IDs and scheduled start are supplied only after the saved-pair timing guard.
# No joins to forecasts, policies, positions, settlements or feature payloads.
FINAL_METADATA_QUERY = """
select g.id::text game_id, g.starts_at, g.status::text game_status,
 g.final_at game_final_at,
 o.id::text outcome_id, o.outcome_status, o.revision, o.created_at outcome_created_at,
 o.final_at outcome_final_at
from games g
left join lateral (
 select f.id, f.outcome_status, f.revision, f.created_at, f.final_at
 from game_final_outcomes f
 where f.game_id=g.id and f.created_at <= :query_started_at
 order by f.revision desc, f.created_at desc, f.id desc limit 1
) o on true
where g.id::text=:game_id and g.starts_at=:declared_start
 and g.starts_at >= :minimum_start and g.starts_at < :query_started_at
"""

FINAL_QUERY = """
select g.id::text game_id, g.starts_at, g.status::text game_status,
 g.final_at game_final_at,
 o.id::text outcome_id, o.outcome_status, o.revision, o.created_at outcome_created_at,
 o.home_score outcome_home_score, o.away_score outcome_away_score, o.final_at outcome_final_at
from games g
left join lateral (
 select f.id, f.outcome_status, f.revision, f.created_at, f.home_score, f.away_score, f.final_at
 from game_final_outcomes f
 where f.game_id=g.id and f.created_at <= :query_started_at
 order by f.revision desc, f.created_at desc, f.id desc limit 1
) o on true
where g.id::text=:game_id and g.starts_at=:declared_start
 and g.starts_at >= :minimum_start and g.starts_at < :query_started_at
 and o.id is not null and upper(o.outcome_status::text)='FINAL'
   and o.final_at > g.starts_at and o.final_at <= :query_started_at
   and o.home_score is not null and o.away_score is not null
"""

STARTER_FINAL_QUERY = """
with ranked as (
 select h.*, dense_rank() over (
  partition by h.player_id,h.source_version_id order by h.revision desc,h.created_at desc
 ) latest_rank
 from player_game_history_observations h
 where h.game_id::text=:game_id and h.role::text='PITCHER'
  and h.player_id::text in (:home_player_id,:away_player_id)
  and h.created_at <= :query_started_at and h.retrieved_at <= :query_started_at
)
select h.id::text observation_id,h.game_id::text game_id,h.player_id::text player_id,
 h.team_id::text team_id,h.final_outcome_id::text final_outcome_id,
 h.role::text role,h.started,h.revision,h.supersedes_observation_id::text supersedes_observation_id,
 h.created_at,h.event_at,h.evidence_end_at,h.retrieved_at,h.source_record_id,
 h.payload_checksum,h.identity_checksum,h.source_mode::text source_mode,h.stat_schema_version,
 h."values"->'pitching'->>'battersFaced' actual_bf,
 h."values"->'pitching'->>'outs' actual_outs,
 h."values"->'pitching'->>'inningsPitched' actual_innings,
 h."values"->'actual_starting_pitcher' actual_starting_pitcher,
 h."values"->>'starter_provenance' starter_provenance,
 h.source_version_id::text source_version_id,h.checkpoint_id::text checkpoint_id,
 c.source_version_id::text checkpoint_source_version_id,c.status::text checkpoint_status,
 c.source_mode::text checkpoint_source_mode,c.temporal_semantics::text checkpoint_temporal_semantics,
 c.requested_at checkpoint_requested_at,c.completed_at checkpoint_completed_at,
 c.identity_checksum checkpoint_identity_checksum,c.query_fingerprint,c.schema_version checkpoint_schema_version,
 c.code_revision,c.raw_references,c.raw_checksums,
 s.source_key,s.dataset_version,s.provider_name,s.source_mode::text source_version_mode,
 s.source_classification::text source_classification,s.quality_tier::text source_quality_tier,
 s.evaluation_eligible,s.identity_checksum source_identity_checksum,s.documentation_uri
from ranked h
left join history_backfill_checkpoints c on c.id=h.checkpoint_id
left join historical_source_versions s on s.id=h.source_version_id
where h.latest_rank=1
order by h.player_id,h.source_version_id,h.id
"""


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    return parsed.astimezone(timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _score_integer(value: Any) -> int:
    if value is None or isinstance(value, (bool, np.bool_)):
        raise ValueError("Observed score must be a nonnegative integer")
    result = float(value)
    if not np.isfinite(result) or result < 0 or result != np.floor(result):
        raise ValueError("Observed score must be a nonnegative integer")
    return int(result)


def _population(values: Any) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if (result.ndim != 1 or len(result) < 2 or not np.isfinite(result).all()
            or (result < 0).any() or (result != np.floor(result)).any()):
        raise ValueError("At least two finite nonnegative integer score draws required")
    return result


def empirical_crps(values: np.ndarray, observation: float) -> float:
    """Exact E|X-y| - E|X-X'|/2 for the supplied empirical distribution."""
    ordered = np.sort(np.asarray(values, dtype=float))
    n = len(ordered)
    dispersion = np.dot(2*np.arange(1, n+1)-n-1, ordered) / n**2
    return float(np.abs(ordered-observation).mean()-dispersion)


def joint_energy_score(home: np.ndarray, away: np.ndarray, observed: Sequence[int]) -> float:
    """Euclidean energy score; exact empirical V-statistic, no tail cutoff.

    Unlike Manhattan distance, the Euclidean norm distinguishes joint dependence.
    Duplicate joint scores are compressed, and distance blocks bound memory.
    """
    support, counts = np.unique(np.column_stack((home, away)), axis=0, return_counts=True)
    weights = counts/counts.sum()
    first = np.dot(weights, np.linalg.norm(support-np.asarray(observed), axis=1))
    second = 0.0
    for start in range(0, len(support), 128):
        block = support[start:start+128]
        distances = np.linalg.norm(block[:, None, :]-support[None, :, :], axis=2)
        second += float(np.dot(weights[start:start+128], distances@weights))
    return float(first-second/2)


def _mc(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=float)
    return {"mean": float(values.mean()), "monteCarloStandardError": float(values.std(ddof=1)/np.sqrt(len(values)))}


def _marginal(values: np.ndarray, observed: int) -> dict:
    predicted = float(values.mean())
    error = predicted-observed
    intervals = {}
    for level in (0.5, 0.8, 0.9):
        lower, upper = np.quantile(values, [(1-level)/2, (1+level)/2], method="inverted_cdf")
        intervals[str(level)] = {"lower": int(lower), "upper": int(upper),
            "width": int(upper-lower), "covered": bool(lower <= observed <= upper)}
    return {"observed": observed, "predictedMean": predicted, "signedError": error,
        "absoluteError": abs(error), "squaredError": error**2,
        "crps": empirical_crps(values, observed), "centralPredictionIntervals": intervals,
        **{k: v for k, v in _mc(values).items() if k != "mean"}}


def _final_identity(final: Mapping) -> dict:
    # Retrieval clocks are deliberately excluded: reading the same final again
    # does not create a new score identity. Revised source outcomes remain linked.
    return {name: final.get(name) for name in ("gameId", "status", "homeScore", "awayScore", "finalAt",
        "sourceOutcomeId", "sourceRevision", "sourceCreatedAt", "lineageBasis",
        "homeStarterBf", "awayStarterBf", "homeStarterOuts", "awayStarterOuts", "starterEvidence")}


def score_pair(pair: Mapping, population: Mapping, final: Mapping) -> dict:
    """Score one authenticated pair; caller persists results by scoreIdentity.

    Keys: pair gameId/commonPairId/scheduledStartUtc; population reference and
    challenger, each with homeRuns/awayRuns in their saved common draw order;
    final gameId/status/homeScore/awayScore and available source lineage.
    """
    start, now = _utc(pair["scheduledStartUtc"]), datetime.now(timezone.utc)
    if start < MINIMUM_PILOT_START or start >= now:
        raise ValueError("Only already-started prospective pilot games may be scored")
    if not pair.get("commonPairId") or not pair.get("gameId") or str(final.get("gameId")) != str(pair["gameId"]):
        raise ValueError("Exact common-pair and final game identity required")
    if str(final.get("status", "")).upper() != "FINAL":
        raise ValueError("Persisted FINAL evidence required; not an unfinished or canceled result")
    if final.get("finalAt") and not start < _utc(final["finalAt"]) <= now:
        raise ValueError("Final timestamp must follow scheduled start and not exceed actual current time")
    home, away = _score_integer(final.get("homeScore")), _score_integer(final.get("awayScore"))
    if home == away:
        raise ValueError("Tied/unsupported final cannot be scored as a completed MLB winner")
    observed = {"homeRuns": home, "awayRuns": away, "homeMargin": home-away, "totalRuns": home+away}
    draws, arms, population_identity, n = {}, {}, {}, None
    for key, label in ARM_LABELS.items():
        arm = population[key]
        h, a = _population(arm["homeRuns"]), _population(arm["awayRuns"])
        if h.shape != a.shape or (n is not None and len(h) != n):
            raise ValueError("Equal completed simulation effort and aligned arm arrays required")
        if (h == a).any():
            raise ValueError("Unfinished/tied simulation cannot enter a completed-game forecast")
        n = len(h)
        population_identity[key] = {"rows": n, "orderedScoreArrays": {
            name: hashlib.sha256(values.astype("<f8", copy=False).tobytes()).hexdigest()
            for name, values in (("homeRuns", h), ("awayRuns", a))},
            "identityEncoding": "little-endian float64, saved draw order"}
        draw = {"homeRuns": h, "awayRuns": a, "homeMargin": h-a, "totalRuns": h+a,
                "homeWinProbability": (h > a).astype(float)}
        p = float(draw["homeWinProbability"].mean())
        scored_p = float(np.clip(p, WIN_LOGLOSS_FLOOR, 1-WIN_LOGLOSS_FLOOR))
        y = int(home > away)
        arms[key] = {"arm": label, "simulations": n,
            "homeWinProbability": p, "observedHomeWin": y,
            "winnerLogLoss": float(-np.log(scored_p if y else 1-scored_p)),
            "winnerBrier": (p-y)**2, "winnerScoringProbability": scored_p,
            "winnerMonteCarloStandardError": _mc(draw["homeWinProbability"])["monteCarloStandardError"],
            "marginals": {name: _marginal(draw[name], outcome) for name, outcome in observed.items()},
            "jointEuclideanEnergyScore": joint_energy_score(h, a, (home, away))}
        # Only explicitly supplied final starter evidence is scored. No inferred
        # actual hooks, pitch counts or relief exposure are manufactured.
        arms[key]["starterDuration"] = {}
        for name in ("homeStarterBf", "awayStarterBf", "homeStarterOuts", "awayStarterOuts"):
            if name in arm and final.get(name) is not None:
                if not final.get("starterEvidence"):
                    raise ValueError("Actual starter duration requires explicit final starter lineage")
                values = _population(arm[name])
                if len(values) != n:
                    raise ValueError("Starter duration draw count differs")
                arms[key]["starterDuration"][name] = _marginal(values, _score_integer(final[name]))
                population_identity[key]["orderedScoreArrays"][name] = hashlib.sha256(values.astype("<f8", copy=False).tobytes()).hexdigest()
        draws[key] = draw
    r, c = arms["reference"], arms["challenger"]
    delta = {name: c[name]-r[name] for name in ("winnerLogLoss", "winnerBrier", "jointEuclideanEnergyScore")}
    delta["marginals"] = {name: {metric: c["marginals"][name][metric]-r["marginals"][name][metric]
        for metric in ("predictedMean", "signedError", "absoluteError", "squaredError", "crps")}
        for name in observed}
    paired_mc = {name: {"challengerMinusReference": (result := _mc(draws["challenger"][name]-draws["reference"][name]))["mean"],
        "pairedMonteCarloStandardError": result["monteCarloStandardError"]} for name in draws["reference"]}
    final_identity = _final_identity(final)
    return {"schemaVersion": SCHEMA, "commonPairId": pair["commonPairId"], "gameId": pair["gameId"],
        "scheduledStartUtc": start.isoformat(), "status": "SCORED_ONE_MATCHED_GAME",
        "scoreIdentity": _digest({"schema": SCHEMA, "commonPairId": pair["commonPairId"],
            "population": population_identity, "final": final_identity}),
        "scoredPopulationIdentity": population_identity,
        "final": dict(final), "finalIdentitySha256": _digest(final_identity), "arms": arms,
        "challengerMinusReference": delta, "pairedMonteCarlo": paired_mc,
        "accounting": {"matchedGames": 1, "pairs": 1, "simulationDrawsPerArm": n,
            "deduplicateAcrossFinalCorrectionsBy": "gameId + commonPairId; latest final revision supersedes, never adds a game"},
        "definitions": {"winnerBrier": "Binary home-win squared error, not twice the binary score",
            "winnerLogLossFloor": WIN_LOGLOSS_FLOOR, "forecastProbabilitiesModified": False,
            "signedError": "predicted mean minus observed; home margin is home minus away",
            "crps": "Exact empirical marginal CRPS, all saved score support; no distribution cap",
            "jointScore": "Euclidean energy score E||X-y|| - 0.5 E||X-X'|| for saved empirical joint scores",
            "intervals": "Central discrete inverse-CDF prediction intervals; coverage is one Boolean per game",
            "monteCarlo": "Conditional simulation sampling uncertainty only; same saved draw indices paired",
            "acrossGameConfidenceInterval": None,
            "limitation": "One pair is one game; no inferred wagering edge, causal managerial optimum or market comparison"},
        "authority": {"researchOnly": True, "wageringAuthority": False, "aispRowsModified": 0,
                      "providerCalls": 0, "fits": 0}}


def eligible_final_queries(pairs: Sequence[Mapping], *, now: datetime) -> tuple[list[dict], list[dict]]:
    """Pure guard used before any connection or outcome query is opened."""
    now = _utc(now)
    eligible, withheld, seen = [], [], set()
    for pair in pairs:
        game_id, pair_id = str(pair["gameId"]), str(pair["commonPairId"])
        start = _utc(pair["scheduledStartUtc"])
        if (game_id, pair_id) in seen:
            continue
        seen.add((game_id, pair_id))
        reason = "OUTSIDE_PROSPECTIVE_PILOT" if start < MINIMUM_PILOT_START else "NOT_STARTED" if start >= now else None
        item = {"gameId": game_id, "commonPairId": pair_id, "scheduledStartUtc": start.isoformat()}
        (withheld if reason else eligible).append({**item, **({"reason": reason} if reason else {})})
    return eligible, withheld


def _serialized(value: Any) -> Any:
    return value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) else value


def _final_metadata_ready(row: Mapping, *, queried_at: datetime) -> tuple[bool, str]:
    """No score values are inspected to decide whether a score query is allowed."""
    revisioned = row["outcome_id"] is not None
    if not revisioned:
        return False, "PROVENANCE_BEARING_FINAL_REQUIRED" if str(row["game_status"]).upper() == "FINAL" else "PERSISTED_FINAL_NOT_AVAILABLE"
    status = row["outcome_status"] if revisioned else row["game_status"]
    if str(status).upper() != "FINAL":
        return False, "PERSISTED_FINAL_NOT_AVAILABLE"
    final_at = row["outcome_final_at"] if revisioned else row["game_final_at"]
    if final_at is None:
        return False, "PERSISTED_FINAL_TIMESTAMP_UNAVAILABLE"
    if not _utc(row["starts_at"]) < _utc(final_at) <= _utc(queried_at):
        return False, "PERSISTED_FINAL_TIMESTAMP_INELIGIBLE"
    if revisioned and (row["revision"] is None or row["outcome_created_at"] is None
                       or _utc(row["outcome_created_at"]) > _utc(queried_at)):
        return False, "PERSISTED_FINAL_REVISION_LINEAGE_UNAVAILABLE"
    return True, "PERSISTED_FINAL_METADATA_READY"


def _expected_starters(pair: Mapping) -> dict:
    """Read only the authenticated saved pregame identities; never alter the pair."""
    descriptor = pair.get("inputs")
    if not isinstance(descriptor, Mapping):
        raise ValueError("FROZEN_STARTER_IDENTITY_DESCRIPTOR_UNAVAILABLE")
    digest = str(descriptor.get("sha256", ""))
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("FROZEN_INPUT_CONTENT_ADDRESS_INVALID")
    root = Path(__file__).resolve().parents[2] / "outputs/mlb-starter-duration-paired-research-v1/objects/sha256"
    path = Path(descriptor["path"]).resolve()
    if path != root / digest / "paired-inputs.json":
        raise ValueError("FROZEN_STARTER_INPUT_PATH_NOT_AUTHORIZED")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest or len(raw) != descriptor["bytes"]:
        raise ValueError("FROZEN_STARTER_INPUT_CHECKSUM_MISMATCH")
    inputs = json.loads(raw)
    pregame = inputs["pregameEvidence"]
    game = pregame["game"]
    if str(inputs["gameId"]) != str(pair["gameId"]) or str(game["game_id"]) != str(pair["gameId"]) or _utc(game["starts_at"]) != _utc(pair["scheduledStartUtc"]):
        raise ValueError("FROZEN_STARTER_GAME_IDENTITY_MISMATCH")
    duration = inputs["durationInputs"]["starterInputs"]
    if sorted(r["side"] for r in duration) != ["AWAY", "HOME"] or sorted(r["side"] for r in pregame["sides"]) != ["AWAY", "HOME"]:
        raise ValueError("FROZEN_BOTH_STARTER_SIDES_REQUIRED")
    sides = {}
    for side in pregame["sides"]:
        label, starter, team = side["side"], side["starter"], side["team"]
        same = next(r for r in duration if r["side"] == label)
        if str(same["starterMlbamId"]) != str(starter["mlbamId"]):
            raise ValueError("FROZEN_STARTER_IDENTITY_MISMATCH")
        mappings = {str(r["mlbam_id"]) for r in pregame["teamIdentityCrosswalk"] if r["team_id"] == team["uuid"]}
        if len(mappings) != 1:
            raise ValueError("FROZEN_TEAM_IDENTITY_UNRESOLVED")
        sides[label] = {"playerId": starter["uuid"], "teamId": team["uuid"], "mlbamId": str(starter["mlbamId"]),
                       "sourceTeamId": next(iter(mappings)), "sourceGameId": str(game["source_game_id"])}
    return {"inputReference": dict(descriptor), "sides": sides}


def _valid_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def _starter_final_evidence(rows: Sequence[Mapping], expected: Mapping, final: Mapping, *, queried_at: datetime) -> dict:
    """Source observations are hashed as retrieved, not misrepresented as raw verification."""
    result = {"status": "SUPPORTED", "sides": {}, "inputReference": expected["inputReference"],
              "finalOutcomeId": final["sourceOutcomeId"], "finalRevision": final["sourceRevision"],
              "querySha256": hashlib.sha256(STARTER_FINAL_QUERY.encode()).hexdigest(),
              "rawSourceBytesIndependentlyRehashed": False,
              "checksumMeaning": "Stored provider/checkpoint checksums retained as lineage; canonicalEvidenceSha256 hashes this exact database projection, not reconstructed source DTOs"}
    for label, identity in expected["sides"].items():
        candidates = [dict(r) for r in rows if str(r["player_id"]) == identity["playerId"]]
        side = {"expectedStarter": dict(identity), "status": "UNSUPPORTED", "reason": None, "sourceRecords": []}
        result["sides"][label] = side
        if not candidates:
            side["reason"] = "PERSISTED_ACTUAL_STARTER_HISTORY_NOT_AVAILABLE"
            result["status"] = "PARTIAL_OR_UNSUPPORTED"
            continue
        values, reasons = [], []
        for row in candidates:
            expected_record = ":".join((identity["sourceGameId"], identity["mlbamId"], identity["sourceTeamId"], "PITCHER"))
            if (str(row["game_id"]) != str(final["gameId"]) or str(row["team_id"]) != identity["teamId"]
                    or str(row["final_outcome_id"]) != str(final["sourceOutcomeId"]) or row["source_record_id"] != expected_record):
                reasons.append("ACTUAL_STARTER_GAME_TEAM_OR_FINAL_REVISION_MISMATCH")
                continue
            if row["role"] != "PITCHER" or row["started"] is not True or row["actual_starting_pitcher"] is not True or not row["starter_provenance"]:
                reasons.append("EXPLICIT_ACTUAL_STARTER_ATTRIBUTION_UNAVAILABLE")
                continue
            if (row["source_mode"] != "LIVE" or row["source_version_mode"] != "LIVE"
                    or row["source_classification"] != "OFFICIAL_PRIMARY" or row["evaluation_eligible"] is not True
                    or row["source_quality_tier"] == "EXCLUDED"):
                reasons.append("STARTER_SOURCE_EVALUATION_AUTHORITY_UNAVAILABLE")
                continue
            if (row["checkpoint_status"] != "SUCCEEDED" or row["checkpoint_source_mode"] != "LIVE"
                    or row["checkpoint_temporal_semantics"] != "RETROSPECTIVE_RECONSTRUCTION"
                    or row["checkpoint_source_version_id"] != row["source_version_id"]):
                reasons.append("SUCCESSFUL_MATCHING_STARTER_SOURCE_CHECKPOINT_UNAVAILABLE")
                continue
            if (not all(_valid_sha(row.get(k)) for k in ("payload_checksum", "identity_checksum", "checkpoint_identity_checksum", "source_identity_checksum"))
                    or not row["raw_references"] or not isinstance(row["raw_references"], list)
                    or not isinstance(row["raw_checksums"], list) or len(row["raw_references"]) != len(row["raw_checksums"])
                    or not all(_valid_sha(s) for s in row["raw_checksums"])):
                reasons.append("STARTER_SOURCE_CHECKSUM_LINEAGE_INCOMPLETE")
                continue
            try:
                if (not _utc(row["checkpoint_requested_at"]) <= _utc(row["checkpoint_completed_at"]) <= queried_at
                        or any(_utc(row[k]) > queried_at for k in ("created_at", "retrieved_at", "evidence_end_at"))
                        or not _utc(final["scheduledStartUtc"]) <= _utc(row["evidence_end_at"])):
                    reasons.append("STARTER_SOURCE_CLOCKS_INELIGIBLE")
                    continue
                bf, outs = _score_integer(row["actual_bf"]), _score_integer(row["actual_outs"])
                from server.sports_current_statcast.mlb_starter_survival_data import innings_notation_to_outs
                if innings_notation_to_outs(row["actual_innings"]) != outs:
                    reasons.append("ACTUAL_STARTER_OUTS_INNINGS_MISMATCH")
                    continue
            except (ValueError, TypeError, KeyError):
                reasons.append("ACTUAL_STARTER_BF_OUTS_OR_CLOCKS_UNSUPPORTED")
                continue
            projected = {k: _serialized(v) for k, v in row.items()}
            side["sourceRecords"].append({"databaseEvidence": projected, "canonicalEvidenceSha256": _digest(projected)})
            values.append((bf, outs))
        if reasons or len(set(values)) != 1:
            side["reason"] = "AMBIGUOUS_ACTUAL_STARTER_EVIDENCE" if len(set(values)) > 1 else ";".join(sorted(set(reasons))) or "PERSISTED_ACTUAL_STARTER_HISTORY_NOT_AVAILABLE"
            result["status"] = "PARTIAL_OR_UNSUPPORTED"
        else:
            side.update(status="SUPPORTED", actualBf=values[0][0], actualOuts=values[0][1])
    return result


def read_persisted_finals(pairs: Sequence[Mapping], *, database_url: str) -> dict:
    """Read exact eligible game finals from an explicitly supplied local AISP URL.

    No credential logging/configuration writes; uses a verified read-only
    transaction and rollback. No connection is opened if every pair is future.
    """
    queried_at = datetime.now(timezone.utc)
    eligible, withheld = eligible_final_queries(pairs, now=queried_at)
    records = []
    metadata_queries = final_queries = starter_queries = 0
    pairs_by_identity = {(str(p["gameId"]), str(p["commonPairId"])): p for p in pairs}
    if eligible:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql" or url.host not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Only the explicitly configured local PostgreSQL read-only interface is allowed")
        engine = create_engine(url, future=True)
        try:
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                    if str(connection.exec_driver_sql("SHOW transaction_read_only").scalar()).lower() != "on":
                        raise RuntimeError("Read-only transaction was not established")
                    for item in eligible:
                        parameters = {"game_id": item["gameId"],
                            "declared_start": _utc(item["scheduledStartUtc"]), "minimum_start": MINIMUM_PILOT_START,
                            "query_started_at": queried_at}
                        metadata = connection.execute(text(FINAL_METADATA_QUERY), parameters).mappings().one_or_none()
                        metadata_queries += 1
                        if metadata is None:
                            records.append({**item, "status": "GAME_OR_SCHEDULE_IDENTITY_NOT_MATCHED"})
                            continue
                        ready, reason = _final_metadata_ready(metadata, queried_at=queried_at)
                        if not ready:
                            records.append({**item, "status": "AWAITING_FINAL", "reason": reason,
                                "sourceStatus": str(metadata["outcome_status"] if metadata["outcome_id"] is not None else metadata["game_status"]).upper(),
                                "sourceOutcomeId": metadata["outcome_id"], "sourceRevision": metadata["revision"],
                                "sourceCreatedAt": _serialized(metadata["outcome_created_at"]),
                                "outcomeValuesRead": False})
                            continue
                        # Recheck final-only predicates inside the score query.
                        # A correction between these two statements cannot expose
                        # a reverted/nonfinal result or revive an older final.
                        row = connection.execute(text(FINAL_QUERY), parameters).mappings().one_or_none()
                        final_queries += 1
                        if row is None:
                            records.append({**item, "status": "AWAITING_FINAL", "reason": "FINAL_CHANGED_OR_SCORE_INCOMPLETE",
                                            "outcomeValuesRead": False})
                            continue
                        row = {name: _serialized(value) for name, value in row.items()}
                        revisioned = row["outcome_id"] is not None
                        status = row["outcome_status"] if revisioned else row["game_status"]
                        prefix = "outcome" if revisioned else "game"
                        final = {**item, "status": str(status).upper(),
                            "homeScore": row[f"{prefix}_home_score"], "awayScore": row[f"{prefix}_away_score"],
                            "finalAt": row[f"{prefix}_final_at"], "sourceOutcomeId": row["outcome_id"],
                            "sourceRevision": row["revision"], "sourceCreatedAt": row["outcome_created_at"],
                            "canonicalGameStatus": row["game_status"],
                            "lineageBasis": "LATEST_REVISIONED_GAME_FINAL_OUTCOME" if revisioned else "CANONICAL_GAME_FINAL_SCORE"}
                        if final["status"] != "FINAL" or final["homeScore"] is None or final["awayScore"] is None:
                            final["sourceStatus"] = final["status"]
                            final["status"] = "AWAITING_FINAL"
                        else:
                            # Optional duration truth is queried only after the
                            # same revisioned final has been admitted for both
                            # arms. A missing optional table cannot abort scoring.
                            savepoint = None
                            try:
                                expected = _expected_starters(pairs_by_identity[(item["gameId"], item["commonPairId"])])
                                savepoint = connection.begin_nested()
                                starter_queries += 1
                                actual_rows = connection.execute(text(STARTER_FINAL_QUERY), {
                                    "game_id": item["gameId"], "query_started_at": queried_at,
                                    "home_player_id": expected["sides"]["HOME"]["playerId"],
                                    "away_player_id": expected["sides"]["AWAY"]["playerId"]}).mappings().all()
                                evidence = _starter_final_evidence(actual_rows, expected, final, queried_at=queried_at)
                                savepoint.commit()
                                savepoint = None
                                final["starterEvidence"] = evidence
                                for label, observed in evidence["sides"].items():
                                    if observed["status"] == "SUPPORTED":
                                        final[label.lower()+"StarterBf"] = observed["actualBf"]
                                        final[label.lower()+"StarterOuts"] = observed["actualOuts"]
                            except Exception as error:
                                if savepoint is not None:
                                    savepoint.rollback()
                                # Do not expose driver arguments or credentials.
                                # Diagnostic identifiers below are metadata only.
                                diagnostic = getattr(getattr(error, "orig", None), "diag", None)
                                missing = {k: value for k in ("table_name", "column_name", "sqlstate")
                                           if isinstance(value := getattr(diagnostic, k, None), str)
                                           and len(value) < 128 and value.replace("_", "").isalnum()}
                                final["starterEvidence"] = {"status": "ACTUAL_STARTER_BF_UNAVAILABLE",
                                    "reason": "OPTIONAL_STARTER_EVIDENCE_UNAVAILABLE:"+type(error).__name__,
                                    "sourceDiagnostic": missing, "actualDurationsInferred": False}
                        records.append(final)
                finally:
                    transaction.rollback()
        except Exception as error:
            # Driver errors can include URL/connection arguments. Keep credentials
            # out of the public receipt; supported caller can inspect locally.
            raise RuntimeError(f"LOCAL_FINAL_READ_FAILED:{type(error).__name__}") from None
        finally:
            engine.dispose()
    retrieved_at = datetime.now(timezone.utc).isoformat()
    source = {"system": "AISP", "interface": "POSTGRES_SELECT_ONLY", "queryStartedAt": queried_at.isoformat(),
        "retrievedAt": retrieved_at, "querySha256": hashlib.sha256(FINAL_QUERY.encode()).hexdigest(),
        "metadataQuerySha256": hashlib.sha256(FINAL_METADATA_QUERY.encode()).hexdigest(),
        "finalReadGate": "STATUS_AND_PROVENANCE_TIMING_METADATA_FIRST_THEN_FINAL_ONLY_SQL",
        "queriedGameIds": sorted({item["gameId"] for item in eligible}),
        "readOnlyTransactionVerified": bool(eligible), "queriesExecuted": metadata_queries + final_queries + starter_queries,
        "metadataQueriesExecuted": metadata_queries, "finalScoreQueriesExecuted": final_queries,
        "optionalStarterQueriesExecuted": starter_queries,
        "optionalStarterQuerySha256": hashlib.sha256(STARTER_FINAL_QUERY.encode()).hexdigest(),
        "aispRowsModified": 0, "providerCalls": 0}
    payload = {"schemaVersion": "MLB_DURATION_PAIRED_PERSISTED_FINALS_V1", "source": source,
        "records": records, "withheldWithoutOutcomeRead": withheld}
    return {**payload, "receiptSha256": _digest(payload)}
