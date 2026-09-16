"""Read-only contract/schedule projection for the bounded preview producer."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_shared.show_preview import canonical, digest, immutable, physical


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--through", required=True)
    p.add_argument("--aisp-root", type=Path, default=Path(r"C:\Users\james\ai-sports-predictor"))
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    with urlopen("http://127.0.0.1:8010/api/v1/show-board/contract", timeout=15) as response:
        raw = response.read()
    immutable(a.output / "consumer-live-contract.json", raw)
    validator = a.aisp_root / "server/app/show_preview/contract.py"
    immutable(a.output / "consumer-contract.py", validator.read_bytes())
    sys.path.insert(0, str(a.aisp_root / "server"))
    from app.db.session import engine
    from sqlalchemy import text
    query = """SELECT g.id::text canonical_game_id,l.code league,g.starts_at,
      gt.is_home,t.abbreviation,t.name FROM games g
      JOIN leagues l ON l.id=g.league_id JOIN game_teams gt ON gt.game_id=g.id
      JOIN teams t ON t.id=gt.team_id WHERE l.code IN ('MLB','NFL','NBA','CFB')
      AND g.starts_at >= :lo AND g.starts_at < :hi ORDER BY g.starts_at,g.id,gt.is_home"""
    now = datetime.now(timezone.utc)
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        assert connection.execute(text("SHOW transaction_read_only")).scalar() == "on"
        rows = [dict(r) for r in connection.execute(text(query), {"lo": now, "hi": a.through}).mappings()]
        connection.rollback()
    for row in rows:
        row["starts_at"] = row["starts_at"].isoformat()
    receipt = {"schema": "ASP_SHOW_PREVIEW_IDENTITY_PROJECTION_V1", "captured_utc": now.isoformat(),
               "through_utc": a.through, "query": query, "outcome_columns_read": [],
               "transaction_read_only": True, "aisp_writes": 0, "rows": rows,
               "local_http_requests_this_capture": 1, "local_http_response_bytes": len(raw),
               "external_provider_calls": 0, "external_bytes": 0, "cost_usd": 0,
               "consumer_live_contract": physical(a.output / "consumer-live-contract.json"),
               "consumer_validator": physical(validator), "validator_snapshot": physical(a.output / "consumer-contract.py")}
    immutable(a.output / "context.json", canonical(receipt))
    print(json.dumps({"context": physical(a.output / "context.json"), "schedule_team_rows": len(rows),
                      "local_http_bytes": len(raw)}, indent=2))


if __name__ == "__main__":
    main()
