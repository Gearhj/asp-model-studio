"""Export already-persisted AISP forecasts, complete quotes, and finals read-only."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_shared.model_vs_market_benchmark import (
    NO_VIG_METHOD,
    score_benchmark,
    validate_observation,
)

# Load the quarantine gate directly so this read-only exporter does not import
# the much larger current-Statcast runtime merely to apply an identity mask.
_CANONICAL_IDS = types.ModuleType("server.sports_silver.canonical_ids")
def _canonical_game_id(value: object) -> str:
    payload = json.dumps(
        ["ASP_MLB_CANONICAL_ID_V1", "game", [str(value)]],
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return f"game-{hashlib.sha256(payload).hexdigest()[:24]}"
_CANONICAL_IDS.canonical_game_id = _canonical_game_id
sys.modules.setdefault("server.sports_silver.canonical_ids", _CANONICAL_IDS)
_QUARANTINE_PATH = ROOT / "server/sports_current_statcast/mlb_starter_duration_quarantine.py"
_QUARANTINE_SPEC = importlib.util.spec_from_file_location("_model_vs_market_quarantine", _QUARANTINE_PATH)
if _QUARANTINE_SPEC is None or _QUARANTINE_SPEC.loader is None:
    raise RuntimeError("MLB quarantine gate cannot be loaded")
_QUARANTINE = importlib.util.module_from_spec(_QUARANTINE_SPEC)
_QUARANTINE_SPEC.loader.exec_module(_QUARANTINE)
final_oot_eligible_key_mask = _QUARANTINE.final_oot_eligible_key_mask
quarantine_reference = _QUARANTINE.reference


def iso(value: Any) -> str:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None:
        raise ValueError("Timestamp lacks timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def immutable_json(path: Path, value: Any) -> dict[str, Any]:
    raw = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError(f"Immutable artifact differs: {path}")
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def american_to_decimal(value: int) -> float:
    return 1 + (100 / abs(value) if value < 0 else value / 100)


def _complete_mlb_books(connection, game_id: Any, home_team_id: Any, away_team_id: Any, as_of: Any) -> list[dict[str, Any]]:
    from sqlalchemy import text

    rows = connection.execute(text("""
        select s.id snapshot_id,s.sportsbook_id,b.name sportsbook,s.source provider,
               s.observed_at,s.available_as_of,s.american_odds,s.decimal_odds,
               o.participant_team_id
        from markets m join market_outcomes o on o.market_id=m.id
        join odds_snapshots s on s.market_outcome_id=o.id
        join sportsbooks b on b.id=s.sportsbook_id
        where m.game_id=:game_id and m.market_type='MONEYLINE' and m.period='full_game'
          and s.source_mode='LIVE' and s.available_as_of<=:as_of
          and o.participant_team_id in (:home,:away)
        order by s.available_as_of desc,s.observed_at desc,s.id desc
    """), {"game_id": game_id, "as_of": as_of, "home": home_team_id, "away": away_team_id}).mappings().all()
    # Require both sides from the same provider/book acquisition batch. This
    # avoids combining independently timed legs merely because both are old.
    grouped: dict[tuple[Any, Any, Any], dict[Any, Any]] = {}
    for row in rows:
        key = (row["sportsbook_id"], row["provider"], row["available_as_of"])
        grouped.setdefault(key, {}).setdefault(row["participant_team_id"], row)
    quotes = []
    seen_books = set()
    for (book_id, provider, available), sides in sorted(grouped.items(), key=lambda item: item[0][2], reverse=True):
        if book_id in seen_books or home_team_id not in sides or away_team_id not in sides:
            continue
        home, away = sides[home_team_id], sides[away_team_id]
        seen_books.add(book_id)
        quotes.append({
            "provider": provider,
            "sportsbook": home["sportsbook"],
            "marketType": "FULL_GAME_MONEYLINE",
            "period": "FULL_GAME",
            "home": {
                "snapshotId": str(home["snapshot_id"]),
                "decimalOdds": float(home["decimal_odds"] or american_to_decimal(home["american_odds"])),
                "observedAtUtc": iso(home["observed_at"]),
                "availableAsOfUtc": iso(home["available_as_of"]),
            },
            "away": {
                "snapshotId": str(away["snapshot_id"]),
                "decimalOdds": float(away["decimal_odds"] or american_to_decimal(away["american_odds"])),
                "observedAtUtc": iso(away["observed_at"]),
                "availableAsOfUtc": iso(away["available_as_of"]),
            },
        })
    return sorted(quotes, key=lambda row: (row["sportsbook"], row["provider"]))


def _mlb_rows(connection) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from sqlalchemy import text

    candidates = [dict(row) for row in connection.execute(text("""
        with ranked as (
          select d.game_id,d.recommended_at,d.recommendation,d.phase,d.shadow_forecast_id,
                 sf.forecast_id,sf.event_id,sf.source_event_id,sf.engine_id,sf.engine_version,
                 sf.available_as_of_utc,sf.full_home_win_probability,sf.full_away_win_probability,
                 sf.full_expected_home_score,sf.full_expected_away_score,g.starts_at,
                 row_number() over(partition by d.game_id order by d.recommended_at desc,d.id desc) rank
          from shadow_experiment_decisions d
          join shadow_forecasts sf on sf.id=d.shadow_forecast_id
          join games g on g.id=d.game_id
          where d.sport='BASEBALL_MLB' and d.market='MONEYLINE' and d.phase='FINAL_PREGAME'
            and d.source_mode='LIVE' and d.odds_snapshot_id is not null
            and d.slate_date>=date '2026-08-28'
            and d.recommended_at<=g.starts_at-interval '15 minutes'
        ) select * from ranked where rank=1 order by starts_at,game_id
    """)).mappings()]
    keys = [str(row["source_event_id"] or row["event_id"]) for row in candidates]
    mask = final_oot_eligible_key_mask(keys)
    admitted = [row for row, keep in zip(candidates, mask, strict=True) if keep]
    removed = [key for key, keep in zip(keys, mask, strict=True) if not keep]
    game_ids = [row["game_id"] for row in admitted]
    if not game_ids:
        return [], {"identityCandidates": len(candidates), "quarantineRemoved": removed, "finalsLoaded": 0}
    teams = connection.execute(text("""
        select game_id,team_id,is_home from game_teams where game_id=any(:ids)
    """), {"ids": game_ids}).mappings().all()
    orientations: dict[Any, dict[str, Any]] = {}
    for row in teams:
        orientations.setdefault(row["game_id"], {})["home" if row["is_home"] else "away"] = row["team_id"]
    # Outcome access occurs only after the identity mask above.
    finals = connection.execute(text("""
        select distinct on (game_id) game_id,id,revision,outcome_status,home_score,away_score,
               label_available_at,payload_checksum,source_record_id
        from game_final_outcomes where game_id=any(:ids) and official=true
        order by game_id,revision desc,id desc
    """), {"ids": game_ids}).mappings().all()
    final_by_game = {row["game_id"]: row for row in finals}
    observations = []
    for row in admitted:
        orientation = orientations.get(row["game_id"], {})
        final = final_by_game.get(row["game_id"])
        if set(orientation) != {"home", "away"} or final is None or final["outcome_status"] != "FINAL":
            continue
        quotes = _complete_mlb_books(
            connection, row["game_id"], orientation["home"], orientation["away"], row["recommended_at"]
        )
        if not quotes:
            continue
        observation = {
            "schemaVersion": "MODEL_VS_MARKET_OBSERVATION_V1",
            "observationId": f"MLB:{row['source_event_id']}:{row['forecast_id']}:DECISION_TIME",
            "sport": "MLB",
            "season": 2026,
            "eventId": str(row["source_event_id"] or row["event_id"]),
            "eventStartUtc": iso(row["starts_at"]),
            "supportCohort": "AISP_LIVE_FINAL_PREGAME_FROM_2026-08-28",
            "decisionStatus": row["recommendation"],
            "evidenceRole": "PROSPECTIVE_ACCUMULATION",
            "forecast": {
                "forecastId": row["forecast_id"], "engineId": row["engine_id"],
                "engineVersion": row["engine_version"], "availableAtUtc": iso(row["available_as_of_utc"]),
                "homeWinProbability": float(row["full_home_win_probability"]),
                "awayWinProbability": float(row["full_away_win_probability"]), "tieProbability": 0.0,
                "expectedHomeScore": float(row["full_expected_home_score"]),
                "expectedAwayScore": float(row["full_expected_away_score"]),
            },
            "market": {"horizon": "DECISION_TIME", "asOfUtc": iso(row["recommended_at"]), "noVigMethod": NO_VIG_METHOD, "homeMarginLine": None, "totalLine": None, "quotes": quotes},
            "final": {
                "identity": f"aisp-game-final:{final['id']}", "revision": int(final["revision"]),
                "status": "FINAL", "availableAtUtc": iso(final["label_available_at"]),
                "homeScore": int(final["home_score"]), "awayScore": int(final["away_score"]),
                "sourceRecordId": final["source_record_id"], "payloadSha256": final["payload_checksum"],
            },
        }
        observations.append(validate_observation(observation))
    return observations, {
        "identityCandidates": len(candidates), "quarantineRemoved": removed,
        "quarantineRef": quarantine_reference(ROOT / "server/artifacts/governance/mlb-final-oot-quarantine-v1.json"),
        "finalsLoaded": len(finals), "matchedCompleteObservations": len(observations),
        "sealedAugust14Through27Read": False,
    }


def _nfl_rows(connection) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from sqlalchemy import text

    rows = [dict(row) for row in connection.execute(text("""
        with ranked as (
          select d.*,sf.forecast_id external_forecast_id,sf.engine_id,sf.engine_version,
                 sf.source_event_id,sf.available_as_of_utc,sf.scheduled_start_utc,
                 sf.full_home_win_probability,sf.full_away_win_probability,
                 sf.full_expected_home_score,sf.full_expected_away_score,
                 row_number() over(partition by d.event_id order by d.evaluated_at desc,d.id desc) rank
          from shadow_board_decisions d join shadow_forecasts sf on sf.id=d.shadow_forecast_id
          where d.market='FULL_GAME_MONEYLINE' and d.has_quote=true
            and d.odds_snapshot_id is not null and d.opposite_odds_snapshot_id is not null
            and d.evaluated_at<=sf.scheduled_start_utc-interval '15 minutes'
        ) select * from ranked where rank=1 order by scheduled_start_utc,event_id
    """)).mappings()]
    final_ids = [str(row["source_event_id"]).removeprefix("nflverse:") for row in rows]
    finals = connection.execute(text("""
        select * from nfl_final_observations where source_event_id=any(:ids) and status='FINAL'
    """), {"ids": final_ids}).mappings().all() if final_ids else []
    final_by_event = {row["source_event_id"]: row for row in finals}
    observations = []
    for row in rows:
        final_id = str(row["source_event_id"]).removeprefix("nflverse:")
        final = final_by_event.get(final_id)
        if final is None:
            continue
        snapshots = connection.execute(text("""
            select s.id,s.source,s.observed_at,s.available_as_of,s.decimal_odds,s.american_odds,b.name
            from odds_snapshots s join sportsbooks b on b.id=s.sportsbook_id
            where s.id in (:one,:two)
        """), {"one": row["odds_snapshot_id"], "two": row["opposite_odds_snapshot_id"]}).mappings().all()
        snapshot_by_id = {item["id"]: item for item in snapshots}
        side = snapshot_by_id[row["odds_snapshot_id"]]
        opposite = snapshot_by_id[row["opposite_odds_snapshot_id"]]
        home, away = (side, opposite) if row["selection"] == "HOME" else (opposite, side)
        kickoff = row["scheduled_start_utc"]
        horizon = "DECISION_TIME" if kickoff - timedelta(minutes=30) <= row["evaluated_at"] <= kickoff - timedelta(minutes=15) else "CAPTURED_EARLY_UNCLASSIFIED"
        home_probability = float(row["full_home_win_probability"])
        away_probability = float(row["full_away_win_probability"])
        observation = {
            "schemaVersion": "MODEL_VS_MARKET_OBSERVATION_V1",
            "observationId": f"NFL:{row['event_id']}:{row['external_forecast_id']}:{horizon}",
            "sport": "NFL", "season": 2026, "eventId": row["event_id"],
            "eventStartUtc": iso(kickoff), "supportCohort": "AISP_NFL_PERSISTED_QUOTE_CAPTURE_V1",
            "decisionStatus": row["recommendation"], "evidenceRole": "PROSPECTIVE_ACCUMULATION",
            "forecast": {
                "forecastId": row["external_forecast_id"], "engineId": row["engine_id"],
                "engineVersion": row["engine_version"], "availableAtUtc": iso(row["available_as_of_utc"]),
                "homeWinProbability": home_probability, "awayWinProbability": away_probability,
                "tieProbability": 1.0 - home_probability - away_probability,
                "expectedHomeScore": float(row["full_expected_home_score"]),
                "expectedAwayScore": float(row["full_expected_away_score"]),
            },
            "market": {
                "horizon": horizon, "asOfUtc": iso(row["evaluated_at"]), "noVigMethod": NO_VIG_METHOD,
                "homeMarginLine": None, "totalLine": None,
                "quotes": [{
                    "provider": home["source"], "sportsbook": home["name"],
                    "marketType": "FULL_GAME_MONEYLINE", "period": "FULL_GAME",
                    "home": {"snapshotId": str(home["id"]), "decimalOdds": float(home["decimal_odds"] or american_to_decimal(home["american_odds"])), "observedAtUtc": iso(home["observed_at"]), "availableAsOfUtc": iso(home["available_as_of"])},
                    "away": {"snapshotId": str(away["id"]), "decimalOdds": float(away["decimal_odds"] or american_to_decimal(away["american_odds"])), "observedAtUtc": iso(away["observed_at"]), "availableAsOfUtc": iso(away["available_as_of"])},
                }],
            },
            "final": {
                "identity": f"nfl-final:{final['payload_checksum']}", "revision": 1,
                "status": "FINAL", "availableAtUtc": iso(final["retrieved_at"]),
                "homeScore": int(final["home_score"]), "awayScore": int(final["away_score"]),
                "sourceRecordId": final["source_event_id"], "payloadSha256": final["payload_checksum"],
            },
        }
        observations.append(validate_observation(observation))
    return observations, {"quoteBoundCandidates": len(rows), "governedFinalsLoaded": len(finals), "matchedCompleteObservations": len(observations)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aisp-root", type=Path, default=Path(r"C:\Users\james\ai-sports-predictor"))
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/model-vs-market-benchmark-v1")
    parser.add_argument("--scored-at-utc")
    args = parser.parse_args()
    sys.path.insert(0, str((args.aisp_root / "server").resolve()))
    from app.db.session import engine

    scored_at = args.scored_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with engine.connect() as connection:
        from sqlalchemy import text
        connection.execute(text("SET TRANSACTION READ ONLY"))
        mlb, mlb_coverage = _mlb_rows(connection)
        nfl, nfl_coverage = _nfl_rows(connection)
        connection.rollback()
    observations = sorted(mlb + nfl, key=lambda row: (row["sport"], row["eventStartUtc"], row["eventId"]))
    report = score_benchmark(observations, scored_at_utc=scored_at)
    report["sourceCoverage"] = {
        "MLB": mlb_coverage, "NFL": nfl_coverage,
        "NBA": {"matchedCompleteObservations": 0, "reason": "CURRENT_FORECAST_HAS_NO_FINAL_OR_PERSISTED_COMPLETE_MONEYLINE"},
        "CFB": {"matchedCompleteObservations": 0, "reason": "CURRENT_FORECAST_HAS_NO_FINAL_OR_PERSISTED_COMPLETE_MONEYLINE"},
    }
    report["controls"] = {
        "transactionReadOnly": True, "providerRequests": 0, "providerObjectsConsumed": 0,
        "aispWrites": 0, "modelsFit": 0, "sealedMlbAugust14Through27Read": False,
        "historicalOddsAcquired": False, "thresholdsTuned": False,
    }
    observation_payload = {"schemaVersion": "MODEL_VS_MARKET_OBSERVATION_SET_V1", "observations": observations}
    observation_raw = canonical_json_bytes(observation_payload)
    report["observationSet"] = {"sha256": hashlib.sha256(observation_raw).hexdigest(), "bytes": len(observation_raw), "games": len(observations)}
    report_raw = canonical_json_bytes(report)
    address = hashlib.sha256(report_raw).hexdigest()
    directory = args.output_root / "sha256" / address
    observations_ref = immutable_json(directory / "observations.json", observation_payload)
    report_ref = immutable_json(directory / "benchmark.json", report)
    run = {
        "schemaVersion": "MODEL_VS_MARKET_BENCHMARK_DELIVERY_V1", "createdAtUtc": scored_at,
        "address": address, "benchmark": report_ref, "observations": observations_ref,
        "matchedGames": len(observations), "bySport": {sport: report["coverage"]["bySport"][sport] for sport in ("MLB", "NFL", "NBA", "CFB")},
        "providerRequests": 0, "providerObjectsConsumed": 0, "aispWrites": 0, "modelsFit": 0,
    }
    run_ref = immutable_json(directory / "delivery.json", run)
    print(json.dumps({**run, "delivery": run_ref}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
