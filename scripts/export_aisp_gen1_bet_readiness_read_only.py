"""Export existing AISP Gen 1 decision evidence in a read-only transaction.

This script issues SELECT statements only, calls no provider, and writes only to
the caller-supplied Model Studio output path.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


SCHEMA_VERSION = "AISP_GEN1_BET_READINESS_READ_ONLY_EXPORT_V1"

QUERY = """
select
  e.id::text experiment_id, e.version experiment_version, e.name experiment_name,
  e.decision_policy, e.recommendation_policy_version, e.staking_policy_version,
  d.id::text decision_id, d.game_id::text event_id, g.starts_at event_start,
  g.status::text event_status, g.home_score game_home_score, g.away_score game_away_score,
  g.final_at game_final_at, d.phase::text phase, d.market, d.period, d.selection,
  d.line, d.sportsbook, d.american_odds, d.decimal_odds,
  d.quote_observed_at, d.forecast_id::text forecast_id,
  d.forecast_generated_at, d.forecast_cutoff, d.forecast_version,
  mv.id::text model_version_id, mv.name model_name, mv.version model_version,
  mv.identity_checksum model_identity_checksum,
  d.recommended_at, d.model_probability, d.no_vig_probability, d.edge,
  d.expected_value, d.readiness, d.uncertainty, d.recommendation,
  d.recommendation_reason, d.qualification_reasons, d.evidence,
  outcome.outcome_status, outcome.home_score outcome_home_score,
  outcome.away_score outcome_away_score, outcome.final_at outcome_final_at,
  p.id::text position_id, p.stake position_stake, p.decimal_odds position_decimal_odds,
  p.placed_at position_placed_at, p.status::text position_status, p.result::text position_result,
  pr.result::text settlement_result, pr.settled_at position_settled_at,
  pr.profit_loss, pr.closing_decimal_odds, pr.closing_line_value, pr.beat_close
from shadow_experiment_decisions d
join shadow_experiments e on e.id=d.experiment_id
join games g on g.id=d.game_id
left join forecasts f on f.id=d.forecast_id
left join model_versions mv on mv.id=f.model_version_id
left join official_asp_positions p on p.shadow_decision_id=d.id
left join position_results pr on pr.position_id=p.id
left join lateral (
  select o.outcome_status, o.home_score, o.away_score, o.final_at
  from game_final_outcomes o where o.game_id=g.id
  order by o.revision desc, o.created_at desc limit 1
) outcome on true
where d.sport='BASEBALL_MLB'
order by d.recommended_at, d.id
"""


def _value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _decision(row: dict[str, Any]) -> dict[str, Any]:
    value = {key: _value(item) for key, item in row.items()}
    outcome = None
    if value["outcome_status"] is not None:
        outcome = {"status": str(value["outcome_status"]).upper(), "homeScore": value["outcome_home_score"],
                   "awayScore": value["outcome_away_score"], "finalAt": value["outcome_final_at"],
                   "lineageBasis": "LATEST_REVISIONED_GAME_FINAL_OUTCOME"}
    elif str(value["event_status"]).lower() == "final" and value["game_home_score"] is not None and value["game_away_score"] is not None:
        outcome = {"status": "FINAL", "homeScore": value["game_home_score"],
                   "awayScore": value["game_away_score"], "finalAt": value["game_final_at"],
                   "lineageBasis": "CANONICAL_GAME_FINAL_SCORE"}
    position = None
    if value["position_id"] is not None:
        settlement = None
        if value["settlement_result"] is not None:
            settlement = {"result": value["settlement_result"], "settledAt": value["position_settled_at"],
                          "profitLoss": value["profit_loss"], "closingDecimalOdds": value["closing_decimal_odds"],
                          "closingLineValue": value["closing_line_value"], "beatClose": value["beat_close"]}
        position = {"positionId": value["position_id"], "stake": value["position_stake"],
                    "decimalOdds": value["position_decimal_odds"], "placedAt": value["position_placed_at"],
                    "status": value["position_status"], "result": value["position_result"], "settlement": settlement}
    return {
        "experimentId": value["experiment_id"], "experimentVersion": value["experiment_version"],
        "experimentName": value["experiment_name"], "decisionPolicy": value["decision_policy"],
        "recommendationPolicyVersion": value["recommendation_policy_version"],
        "stakingPolicyVersion": value["staking_policy_version"], "decisionId": value["decision_id"],
        "eventId": value["event_id"], "eventStart": value["event_start"], "eventStatus": value["event_status"],
        "phase": value["phase"], "market": value["market"], "period": value["period"],
        "selection": value["selection"], "line": value["line"], "sportsbook": value["sportsbook"],
        "americanOdds": value["american_odds"], "decimalOdds": value["decimal_odds"],
        "quoteObservedAt": value["quote_observed_at"], "forecastId": value["forecast_id"],
        "forecastGeneratedAt": value["forecast_generated_at"], "forecastCutoff": value["forecast_cutoff"],
        "forecastVersion": value["forecast_version"], "modelVersionId": value["model_version_id"],
        "modelName": value["model_name"], "modelVersion": value["model_version"],
        "modelIdentityChecksum": value["model_identity_checksum"], "recommendedAt": value["recommended_at"],
        "modelProbability": value["model_probability"], "noVigProbability": value["no_vig_probability"],
        "edge": value["edge"], "expectedValue": value["expected_value"], "readiness": value["readiness"],
        "uncertainty": value["uncertainty"], "recommendation": value["recommendation"],
        "recommendationReason": value["recommendation_reason"],
        "qualificationReasons": value["qualification_reasons"] or [], "evidence": value["evidence"],
        "outcome": outcome, "position": position,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aisp-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(args.aisp_root / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("AISP DATABASE_URL is unavailable")
    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    extracted_at = datetime.now(UTC)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            rows = connection.execute(text(QUERY)).mappings().all()
        finally:
            transaction.rollback()
    payload = {
        "schemaVersion": SCHEMA_VERSION, "extractedAt": extracted_at.isoformat(),
        "source": {"system": "AISP", "interface": "POSTGRES_SELECT_ONLY",
                   "readOnlyTransaction": True, "aispRowsModified": 0, "providerCalls": 0,
                   "querySha256": hashlib.sha256(QUERY.encode("utf-8")).hexdigest()},
        "decisions": [_decision(dict(row)) for row in rows],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    print(json.dumps({"output": str(args.output.resolve()), "decisions": len(rows),
                      "distinctEvents": len({row["eventId"] for row in payload["decisions"]}),
                      "exportSha256": hashlib.sha256(raw).hexdigest(), "aispRowsModified": 0,
                      "providerCalls": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
