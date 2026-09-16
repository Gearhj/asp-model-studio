from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.publish_cfb_gen1_current_v1 import verify_package
from server.sports_cfb_gen1.current import simulate_uncertainty_challenger
from server.sports_cfb_gen1.pipeline import FEATURE_COLUMNS, simulate_paired_residuals


OUT = ROOT / "outputs/cfb-gen1-current-v1"
HISTORICAL = ROOT / "outputs/cfb-gen1-v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def main() -> dict:
    source = json.loads((OUT / "cfbd-source-manifest.json").read_bytes())
    forecast = json.loads((OUT / "forecast/forecast.json").read_bytes())
    delivery = json.loads((OUT / "delivery-index.json").read_bytes())
    local_package = OUT / "packages/sha256" / delivery["packageDigest"]
    package_index = verify_package(local_package)
    exchange_package = Path(delivery["exchangePackage"])
    exchange_index = verify_package(exchange_package)
    require(package_index == exchange_index, "local and exchange indexes differ")

    require(source["usage"]["calls"] <= 25, "call cap exceeded")
    require(source["usage"]["responseBytes"] <= 50*1024*1024, "byte cap exceeded")
    require(source["usage"]["incrementalCostUsd"] == 0, "cost cap exceeded")
    for group in (source["requests"], source["termsEvidence"]):
        for item in group:
            path = Path(item["path"])
            require(path.stat().st_size == item["bytes"] and sha(path) == item["physicalSha256"], f"source byte mismatch: {path}")

    key = str(dotenv_values(ROOT / ".env.local").get("CFBD_API_KEY") or "").encode()
    require(bool(key), "credential disappeared before secret exclusion check")
    inspect = [Path(__file__), ROOT / "scripts/acquire_cfb_gen1_current_v1.py", ROOT / "scripts/run_cfb_gen1_current_v1.py", ROOT / "scripts/publish_cfb_gen1_current_v1.py", ROOT / "server/sports_cfb_gen1/current.py"]
    inspect.extend(path for path in OUT.rglob("*") if path.is_file() and "private-sources" not in path.parts)
    require(all(key not in path.read_bytes() for path in inspect), "credential present in code or nonprivate artifact")

    draws = pd.read_parquet(local_package / "baseline-joint-draws.parquet")
    pmfs = pd.read_parquet(local_package / "baseline-pmfs.parquet")
    require(len(draws) == 10_000, "draw count changed")
    require(not (draws.home_score == draws.away_score).any(), "final ties remain")
    require((draws.total == draws.home_score+draws.away_score).all(), "total does not reconcile")
    require((draws.home_margin == draws.home_score-draws.away_score).all(), "margin does not reconcile")
    require((pmfs.groupby("metric")["count"].sum() == 10_000).all(), "PMF mass does not reconcile")

    target = pd.Series({**forecast["featureValues"], **{
        "game_id": forecast["game"]["game_id"],
        "scheduled_at": pd.Timestamp(forecast["game"]["scheduled_at"]),
        "ridge_alpha100_pred_home": forecast["baseline"]["expectedHomePoints"],
        "ridge_alpha100_pred_away": forecast["baseline"]["expectedAwayPoints"],
        "ridge_alpha100_pred_margin": forecast["baseline"]["expectedHomeMargin"],
        "ridge_alpha100_pred_total": forecast["baseline"]["expectedTotal"],
    }})
    donors = pd.read_parquet(HISTORICAL / "data/season-forward-predictions.parquet")
    replay, _ = simulate_paired_residuals(target, donors, "ridge_alpha100")
    pd.testing.assert_frame_equal(draws, replay)
    baseline, ordinary, accounting = simulate_uncertainty_challenger(target, donors, "ridge_alpha100")
    pd.testing.assert_frame_equal(baseline, ordinary)
    require(accounting["disposition"] == "EXACT_BASELINE_ORDINARY", "ordinary fallback changed")

    model = joblib.load(HISTORICAL / "models/selected-through-2025.joblib")
    require(model["trainingThroughSeason"] == 2025 and model["parameters"] == {"alpha": 100.0}, "frozen point model changed")
    require(model["featureColumns"] == FEATURE_COLUMNS, "feature contract changed")
    require(pd.Timestamp(forecast["sourceCutoff"]) < pd.Timestamp(forecast["createdAt"]) < pd.Timestamp(forecast["game"]["scheduled_at"]), "forecast chronology failed")
    require(forecast["game"]["away_team"] == "Syracuse" and forecast["game"]["home_team"] == "Pittsburgh", "orientation changed")
    require(forecast["baseline"]["tieProbability"] == 0.0, "published tie probability changed")
    require(forecast["baseline"]["illustrativeTotals"][1]["push"] == 0.0, "half-point line has push mass")
    require(all(abs(item["over"]+item["push"]+item["under"]-1.0) < 1e-12 for item in forecast["baseline"]["illustrativeTotals"]), "totals probability mass failed")
    require(delivery["producedForecasts"] == 1 and delivery["publishedForecasts"] == 1, "publication counts changed")
    require(delivery["importConfirmedForecasts"] == 0 and delivery["displayConfirmedForecasts"] == 0, "unsupported consumer claim")

    result = {
        "schemaVersion": "CFB_GEN1_CURRENT_INDEPENDENT_REPLAY_VERIFICATION_V1",
        "checks": 25, "status": "PASS", "forecastId": forecast["forecastId"],
        "packageDigest": delivery["packageDigest"], "drawCount": len(draws),
        "sourceCalls": source["usage"]["calls"], "sourceBytes": source["usage"]["responseBytes"],
        "secretExcluded": True, "deterministicReplay": True, "exchangeMatchesLocal": True,
        "consumerAcknowledgement": None,
    }
    raw = json.dumps(result, sort_keys=True, indent=2).encode("utf-8")
    path = OUT / "independent-verification.json"
    path.write_bytes(raw)
    result["artifact"] = {"path": str(path.resolve()), "bytes": len(raw), "physicalSha256": sha(path)}
    return result


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True))
