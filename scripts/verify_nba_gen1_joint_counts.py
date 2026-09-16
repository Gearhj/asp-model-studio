"""Verify retained NBA joint counts after all six assessment receipts exist.

No draws are generated, observations loaded, or proper scores recalculated.
Existing season receipts are physically verified before any Parquet access.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import is_integer_dtype


ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "outputs/nba-gen1-joint-residual-v1"
ARMS = ("paired", "benchmark")
SEASONS = tuple(range(2021, 2027))
DRAW_COUNT = 10_000
FILES = (
    "paired-joint-counts.parquet", "benchmark-joint-counts.parquet",
    "scores.parquet", "support-effects.parquet", "populations.parquet",
    "donor-banks.parquet",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def physical(path: Path) -> dict:
    path = path.resolve(strict=True)
    checksum, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            checksum.update(chunk)
            size += len(chunk)
    return {"path": str(path), "sha256": checksum.hexdigest(), "bytes": size}


def verify_ref(expected: dict) -> dict:
    actual = physical(Path(expected["path"]))
    require(actual == {key: expected[key] for key in actual}, f"Physical binding changed: {actual['path']}")
    return actual


def read_metadata(path: Path) -> tuple[dict, dict]:
    # Record the delivered physical bytes before parsing metadata, with no
    # newline normalization. Immutable producer refs are checked separately.
    bound = physical(path)
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == bound["sha256"], f"File changed during read: {path}")
    return json.loads(raw), bound


def check_metadata(frame: pd.DataFrame, expected: pd.DataFrame, label: str) -> None:
    require(len(frame) == len(expected), f"{label}: wrong game count")
    require(not frame.game_id.duplicated().any(), f"{label}: duplicate game identity")
    require(not frame.game_index.duplicated().any(), f"{label}: duplicate global game index")
    actual = frame.set_index("game_id").sort_index()
    target = expected.set_index("game_id").sort_index()
    require(actual.index.equals(target.index), f"{label}: declared cohort mismatch")
    for column in ("game_index", "game_date", "season_end"):
        require(np.array_equal(actual[column].to_numpy(), target[column].to_numpy()), f"{label}: {column} mismatch")


def totals_example(root: Path, method: dict, retained: pd.DataFrame,
                   saved: pd.Series, bound: dict, example: dict) -> dict:
    require(example["game_id"] == method["demonstration"]["gameId"], "Totals example changed declared game")
    require(example["drawCount"] == DRAW_COUNT, "Totals example has wrong denominator")
    require(example["game_index"] == int(saved.game_index), "Totals example game-index mismatch")
    require(example["evidence"] == "REUSED_HISTORICAL_ASSESSMENT_NOT_ORIGINAL_PREGAME_FORECAST", "Totals example lost historical qualification")
    integer_totals = retained.home_score.to_numpy(np.int64) + retained.away_score.to_numpy(np.int64)
    frequencies = pd.DataFrame({"total": integer_totals, "count": retained["count"].to_numpy(np.int64)}).groupby("total", sort=True)["count"].sum()
    expected_pmf = [{"total": int(total), "count": int(count), "probability": int(count) / DRAW_COUNT}
                    for total, count in frequencies.items()]
    require(example["integerTotalFrequency"] == expected_pmf, "Totals PMF differs from original paired cells")
    require(int(frequencies.sum()) == DRAW_COUNT, "Totals PMF lost population mass")
    require(example["jointExpectedHome"] == saved.home_mean and example["jointExpectedAway"] == saved.away_mean,
            "Totals example expected scores differ from retained population")
    require(example["jointDerivedHomeWinProbability"] == saved.home_win_probability, "Totals example winner probability mismatch")
    require(example["central80TotalInterval"] == [int(saved.total_80_lower), int(saved.total_80_upper)], "Totals example interval mismatch")
    lines = method["demonstration"]["illustrativeLines"]
    require(lines == [225, 225.5], "Unexpected frozen totals demonstration lines")
    require(len(example["queries"]) == len(lines), "Totals query count mismatch")
    query_results = []
    for line, query in zip(lines, example["queries"]):
        over = int(frequencies[frequencies.index > line].sum())
        push = int(frequencies[frequencies.index == line].sum())
        under = int(frequencies[frequencies.index < line].sum())
        require(over + push + under == DRAW_COUNT, f"Totals line {line}: count accounting failure")
        require(query["line"] == line and query["drawCount"] == DRAW_COUNT, "Totals line/denominator mismatch")
        require(query["probabilityUnits"] == "FRACTIONS_0_TO_1", "Totals probability units are not fractions")
        require(query["lineClassification"] == "ILLUSTRATIVE_NOT_RECORDED_MARKET", "Totals line is not identified as illustrative")
        expected_over = {"win": over / DRAW_COUNT, "push": push / DRAW_COUNT, "loss": under / DRAW_COUNT}
        expected_under = {"win": under / DRAW_COUNT, "push": push / DRAW_COUNT, "loss": over / DRAW_COUNT}
        require(query["over"] == expected_over and query["under"] == expected_under, "Totals query does not match full paired population")
        require(abs(sum(expected_over.values()) - 1) <= 1e-15, "Totals probabilities do not sum to one")
        require(abs(expected_under["win"] - (1 - expected_over["win"] - expected_over["push"])) <= 1e-15, "Under complement lost push mass")
        if line % 1:
            require(push == 0, "Half-point total incorrectly has a push")
        query_results.append({"line": line, "overCount": over, "pushCount": push, "underCount": under,
                              "over": expected_over, "under": expected_under})
    return {"artifact": bound, "gameId": example["game_id"], "gameIndex": int(saved.game_index),
            "drawCount": DRAW_COUNT, "integerTotalCells": len(frequencies), "queries": query_results,
            "pairedPopulationPmfExact": True, "probabilityUnits": "FRACTIONS_0_TO_1"}


def verify(root: Path) -> dict:
    root = root.resolve(strict=True)
    output = root / "count-accounting-verification.json"
    require(not output.exists(), f"Refusing to replace existing verification: {output}")
    method, method_ref = read_metadata(root / "method-freeze.json")
    cohort, cohort_ref = read_metadata(root / "cohort-games.json")
    require(method["drawCountPerGamePerArm"] == DRAW_COUNT, "Unexpected frozen draw count")
    require(set(map(int, method["cohort"]["seasons"])) == set(SEASONS), "All six declared assessment seasons are required")
    expected = pd.DataFrame(cohort["eligible"]).sort_values(["game_date", "game_id"]).reset_index(drop=True)
    require(not expected.game_id.duplicated().any(), "Duplicate game in declared eligible cohort")
    require(len(expected) == method["cohort"]["eligibleGames"], "Frozen eligible game count changed")
    require(hashlib.sha256("\n".join(expected.game_id).encode()).hexdigest() == method["cohort"]["eligibleIdentitySha256"], "Frozen eligible identity changed")
    require(set(expected.season_end) == set(SEASONS), "Declared cohort seasons mismatch")
    require(not set(expected.game_id).intersection(item["game_id"] for item in cohort["unsupported"]), "Unsupported target entered cohort")
    expected["game_index"] = np.arange(len(expected), dtype=np.int64)
    receipt_paths = sorted((root / "assessment").glob("*/receipt.json"))
    require({path.parent.name for path in receipt_paths} == {str(year) for year in SEASONS}, "All six completed season receipts required; no partial validation")
    receipts, bound_files = {}, []
    # Complete physical verification of ALL season artifacts before reading any
    # Parquet, including files not interpreted by this accounting-only checker.
    for receipt_path in receipt_paths:
        receipt, receipt_ref = read_metadata(receipt_path)
        year = int(receipt_path.parent.name)
        require(receipt["schema"] == "NBA_GEN1_JOINT_RESIDUAL_SEASON_ASSESSMENT_V1", "Unexpected season receipt schema")
        require(verify_ref(receipt["method"]) == method_ref, "Season receipt uses a different frozen method")
        require(receipt["configurations"] == 2 and receipt["drawsPerConfigurationPerGame"] == DRAW_COUNT, "Season receipt arm/denominator mismatch")
        require(receipt["games"] == int(method["cohort"]["seasons"][str(year)]), "Season receipt cohort size mismatch")
        artifacts = receipt["artifacts"]
        require(len(artifacts) == len(FILES) and {Path(item["path"]).name for item in artifacts} == set(FILES), "Missing or duplicate season artifact")
        for item in artifacts:
            require(Path(item["path"]).resolve().parent == receipt_path.parent, "Season artifact escapes its receipt folder")
            bound_files.append(verify_ref(item))
        receipts[year] = {"receipt": receipt_ref, "folder": receipt_path.parent}
    example, example_ref = read_metadata(root / "totals-demonstration.json")
    summaries, demonstration = [], None
    for year in SEASONS:
        folder = receipts[year]["folder"]
        declared = expected[expected.season_end == year]
        metadata = ["game_id", "game_index", "game_date", "season_end", "configuration", "draw_count"]
        scores = pd.read_parquet(folder / "scores.parquet", columns=metadata + [
            "home_mean", "away_mean", "total_mean", "margin_mean", "home_win_probability", "away_win_probability", "tie_probability", "one_point_probability", "total_80_lower", "total_80_upper"])
        populations = pd.read_parquet(folder / "populations.parquet", columns=metadata + ["joint_cells", "joint_counts_int64_le_sha256"])
        require(set(scores.configuration) == set(ARMS) and set(populations.configuration) == set(ARMS), "Unexpected/missing arm in saved summaries")
        for arm in ARMS:
            label = f"{year}/{arm}"
            scored = scores[scores.configuration == arm]
            population = populations[populations.configuration == arm]
            check_metadata(scored, declared, label + " scores")
            check_metadata(population, declared, label + " populations")
            require((scored.draw_count == DRAW_COUNT).all() and (population.draw_count == DRAW_COUNT).all(), label + ": saved denominator mismatch")
            scored = scored.set_index("game_index", drop=False)
            population = population.set_index("game_index", drop=False)
            counts = pd.read_parquet(folder / (arm + "-joint-counts.parquet"))
            require(list(counts.columns) == ["game_index", "home_score", "away_score", "count"], label + ": unexpected count schema")
            require(all(is_integer_dtype(counts[column]) for column in counts), label + ": noninteger count/score/index storage")
            require(not counts.isna().any().any(), label + ": null score/cell metadata")
            require((counts[["home_score", "away_score"]] >= 0).all().all(), label + ": negative final score")
            require((counts.home_score != counts.away_score).all(), label + ": tied final score")
            require(((counts["count"] > 0) & (counts["count"] <= DRAW_COUNT)).all(), label + ": invalid cell count")
            require(not counts.duplicated(["game_index", "home_score", "away_score"]).any(), label + ": duplicate joint cell")
            require(set(counts.game_index) == set(declared.game_index), label + ": retained population cohort differs")
            for index, cells in counts.groupby("game_index", sort=True):
                saved, manifest = scored.loc[index], population.loc[index]
                n = int(cells["count"].sum())
                require(n == DRAW_COUNT, f"{label}/{index}: population count {n}, expected {DRAW_COUNT}")
                require(len(cells) == manifest.joint_cells, f"{label}/{index}: joint cell count differs")
                pairs = cells[["home_score", "away_score", "count"]].to_numpy(np.int64)
                # np.unique in the frozen runner retains lexicographic cell order.
                require(np.array_equal(np.lexsort((pairs[:, 1], pairs[:, 0])), np.arange(len(pairs))), f"{label}/{index}: changed original joint-cell ordering")
                require(hashlib.sha256(pairs.astype("<i8").tobytes()).hexdigest() == manifest.joint_counts_int64_le_sha256, f"{label}/{index}: retained joint digest mismatch")
                # Python integer sums avoid overflow even for extreme scores.
                weighted_home = sum(int(h) * int(c) for h, _, c in pairs)
                weighted_away = sum(int(a) * int(c) for _, a, c in pairs)
                means = {"home_mean": weighted_home / n, "away_mean": weighted_away / n,
                         "total_mean": (weighted_home + weighted_away) / n,
                         "margin_mean": (weighted_home - weighted_away) / n}
                for column, value in means.items():
                    require(value == saved[column], f"{label}/{index}: {column} not exactly reproduced")
                home_wins = sum(int(c) for h, a, c in pairs if h > a)
                one_point = sum(int(c) for h, a, c in pairs if abs(int(h) - int(a)) == 1)
                require(home_wins / n == saved.home_win_probability, f"{label}/{index}: winner probability mismatch")
                require(1 - home_wins / n == saved.away_win_probability and saved.tie_probability == 0, f"{label}/{index}: winner support/accounting mismatch")
                require(one_point / n == saved.one_point_probability, f"{label}/{index}: one-point mass mismatch")
                if arm == "paired" and saved.game_id == method["demonstration"]["gameId"]:
                    require(demonstration is None, "Duplicate totals demonstration population")
                    demonstration = totals_example(root, method, cells, saved, example_ref, example)
            summaries.append({"seasonEnd": year, "arm": arm, "games": len(declared), "jointCells": len(counts),
                              "retainedDraws": len(declared) * DRAW_COUNT, "countPerGame": DRAW_COUNT,
                              "declaredCohortExact": True, "uniqueNonnegativeUntiedIntegerCells": True,
                              "originalJointDigestsExact": True, "weightedMeansAndWinnerProbabilitiesExact": True})
            del counts
    require(demonstration is not None, "Declared totals demonstration population is missing")
    report = {"schema": "NBA_GEN1_JOINT_COUNT_ACCOUNTING_VERIFICATION_V1",
              "verifiedAtUtc": datetime.now(timezone.utc).isoformat(), "method": method_ref, "declaredCohort": cohort_ref,
              "verifier": physical(Path(__file__)), "seasonReceipts": [receipts[y]["receipt"] for y in SEASONS],
              "physicallyVerifiedSeasonArtifacts": bound_files, "games": len(expected), "configurations": len(ARMS),
              "populations": len(expected) * len(ARMS), "retainedDraws": len(expected) * len(ARMS) * DRAW_COUNT,
              "allChecksPassed": True, "seasonArms": summaries, "totalsDemonstration": demonstration,
              "scope": "Only retained joint-count and forecast-summary accounting. No regenerated draws, observations read, proper scores recomputed, source requests, or original-file changes."}
    raw = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    with output.open("xb") as handle:
        handle.write(raw)
    return {"verification": physical(output), "allChecksPassed": True, "games": len(expected), "populations": len(expected) * len(ARMS)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), indent=2, allow_nan=False))
