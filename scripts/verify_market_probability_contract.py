"""Deterministic local verification; no providers, models, exchange, or AISP."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_shared.market_probabilities import (
    JointScorePopulation,
    evaluate_market,
    evaluate_same_game_joint,
)


DOCS = ROOT / "docs" / "aisp-market-probability-contract-v1"


def main() -> None:
    fixture = json.loads((DOCS / "fixtures" / "golden-vectors.json").read_bytes())
    for name in ("request.schema.json", "response.schema.json"):
        schema = json.loads((DOCS / "schemas" / name).read_bytes())
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ValueError(f"schema declaration differs: {name}")
    matrix = json.loads((DOCS / "capability-matrix.json").read_bytes())
    if {row["sport"] for row in matrix["sports"]} != {"MLB", "NFL", "NBA", "CFB"}:
        raise ValueError("four-sport capability matrix differs")
    population = JointScorePopulation.from_cells(**fixture["population"])
    if population.population_sha256 != fixture["expectedPopulationSha256"]:
        raise ValueError("golden population identity differs")
    results = []
    for vector in fixture["vectors"]:
        result = (
            evaluate_market(population, vector["leg"])
            if vector["kind"] == "single"
            else evaluate_same_game_joint(population, vector["legs"])
        )
        if result["counts"] != vector["expectedCounts"]:
            raise ValueError(f"golden vector differs: {vector['name']}")
        results.append({"name": vector["name"], "counts": result["counts"]})
    print(json.dumps({
        "status": "VERIFIED",
        "populationSha256": population.population_sha256,
        "vectors": results,
        "providerCalls": 0,
        "modelRuns": 0,
        "aispWrites": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
