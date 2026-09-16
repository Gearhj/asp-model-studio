from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    with (ROOT / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    providers = load("PROVIDER_MATRIX.json")
    fields = load("FIELD_COVERAGE_MATRIX.json")
    schema = load("CANONICAL_SCHEMA.json")
    ids = {item["id"] for item in providers["providers"]}
    required = {"api_sports_mma", "sportsgameodds", "the_odds_api", "ufcstats", "ufc_com", "thesportsdb", "sportradar_mma"}
    assert required <= ids, sorted(required - ids)
    assert {item["evidenceLevel"] for item in providers.get("claims", [])} <= set(providers["evidenceLevels"])
    measured = next(item for item in providers["providers"] if item["id"] == "thesportsdb")["measurements"]
    assert measured["responseBytes"] == 14361 + 1982 + 1982
    assert measured["successfulRequests"] == 3 and measured["costUsd"] == 0
    assert len(fields["fields"]) >= 20
    assert schema["changeRules"]["opponentReplacement"].startswith("close prior bout version")
    print(json.dumps({"status":"PASS","providers":len(ids),"fields":len(fields["fields"]),"providerCalls":3,"providerBytes":measured["responseBytes"]}, separators=(",", ":")))


if __name__ == "__main__":
    main()
