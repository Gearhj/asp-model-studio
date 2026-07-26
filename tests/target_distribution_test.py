"""Target Distribution bounded-aggregate tests.

Covers the server half of the performance correction: exact grouped counts from
the governed artifact, bounded result rows, cache behavior keyed by immutable
version + target, and the stratified sampling fallback with its disclosure
metadata. Builds its own temporary Parquet/CSV fixtures under a tmp dir and
removes them -- no large fixture is committed.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from server.analytics import result_cache, target_distribution_service as tds  # noqa: E402


def _make_rare_event_frame(rows: int, event_rate: float, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    events = max(1, int(round(rows * event_rate)))
    target = np.zeros(rows, dtype=np.int8)
    target[rng.choice(rows, size=events, replace=False)] = 1
    return pd.DataFrame({
        "Time": np.arange(rows, dtype=np.int64),
        "Amount": rng.gamma(2.0, 40.0, size=rows).round(2),
        "V1": rng.normal(size=rows).round(4),
        "Class": target,
    })


class TargetDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="atlas-target-dist-"))
        cls.frame = _make_rare_event_frame(170_884, 0.0021)
        cls.csv_path = cls.tmp / "data_full.csv"
        cls.frame.to_csv(cls.csv_path, index=False)
        cls.parquet_path = cls.tmp / "data_full.parquet"
        cls.frame.to_parquet(cls.parquet_path, index=False)
        cls.expected_events = int(cls.frame["Class"].sum())
        cls.expected_rows = len(cls.frame)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self) -> None:
        result_cache.RESULT_CACHE.invalidate_dataset("*")

    def _artifact(self, fmt: str = "csv") -> dict:
        path = self.csv_path if fmt == "csv" else self.parquet_path
        return {
            "path": path, "format": fmt, "versionId": f"v_test_{fmt}",
            "rowCount": self.expected_rows, "sizeBytes": path.stat().st_size,
        }

    def _compute(self, fmt: str = "csv", **overrides):
        artifact = self._artifact(fmt)
        artifact.update(overrides.pop("artifact", {}))
        with mock.patch.object(tds, "_resolve_version_artifact", return_value=artifact):
            kwargs = dict(
                user_scope="user-1", project_id="proj-1", dataset_id="ds-test",
                version_id=artifact["versionId"], target="Class", event_value=1, non_event_value=0,
            )
            kwargs.update(overrides)
            return tds.compute_target_distribution(**kwargs)

    # 1 / 8 -- exact binary counts from the server aggregate, rare-event accurate.
    def test_exact_binary_counts_are_computed_server_side(self):
        result = self._compute()
        self.assertEqual(result["resolution"], "exact")
        self.assertEqual(result["engine"], "duckdb")
        self.assertTrue(result["supported"])
        self.assertEqual(result["totalRowCount"], self.expected_rows)

        by_value = {row["value"]: row for row in result["classDistribution"]}
        self.assertEqual(by_value["1"]["count"], self.expected_events)
        self.assertEqual(by_value["0"]["count"], self.expected_rows - self.expected_events)
        # The rare-event rate must survive as a real, nonzero proportion.
        self.assertAlmostEqual(by_value["1"]["percent"], self.expected_events / self.expected_rows, places=9)
        self.assertGreater(by_value["1"]["percent"], 0.0)
        self.assertLess(by_value["1"]["percent"], 0.01)

    def test_parquet_and_csv_artifacts_agree_exactly(self):
        csv_result = self._compute("csv")
        result_cache.RESULT_CACHE.invalidate_dataset("*")
        parquet_result = self._compute("parquet")
        self.assertEqual(
            {r["value"]: r["count"] for r in csv_result["classDistribution"]},
            {r["value"]: r["count"] for r in parquet_result["classDistribution"]},
        )

    # 2 -- only bounded aggregate rows leave the server.
    def test_only_bounded_aggregate_rows_are_returned(self):
        result = self._compute()
        self.assertEqual(len(result["classDistribution"]), 2)
        self.assertLessEqual(len(result["classDistribution"]), tds.MAX_TARGET_CARDINALITY)
        # The target column itself is never present in the payload.
        import json

        serialized = json.dumps(result)
        self.assertLess(len(serialized), 4000, "aggregate payload must stay tiny")
        self.assertNotIn("rows", result)
        for row in result["classDistribution"]:
            self.assertEqual(set(row), {"value", "count", "percent"})

    def test_high_cardinality_target_is_reported_unsupported_not_returned(self):
        wide = pd.DataFrame({"Class": [f"c{i}" for i in range(tds.MAX_TARGET_CARDINALITY + 25)]})
        wide_path = self.tmp / "wide.csv"
        wide.to_csv(wide_path, index=False)
        artifact = {"path": wide_path, "format": "csv", "versionId": "v_wide", "rowCount": len(wide), "sizeBytes": wide_path.stat().st_size}
        with mock.patch.object(tds, "_resolve_version_artifact", return_value=artifact):
            result = tds.compute_target_distribution(
                user_scope="user-1", project_id="proj-1", dataset_id="ds-wide",
                version_id="v_wide", target="Class",
            )
        self.assertFalse(result["supported"])
        self.assertEqual(result["resolution"], "unsupported")
        self.assertEqual(result["classDistribution"], [])

    # 5 -- cache is used for the same immutable version + target.
    def test_repeat_query_is_served_from_cache(self):
        first = self._compute()
        self.assertFalse(first["cached"])
        second = self._compute()
        self.assertTrue(second["cached"])
        self.assertEqual(second["durationMs"], 0)
        self.assertEqual(
            {r["value"]: r["count"] for r in first["classDistribution"]},
            {r["value"]: r["count"] for r in second["classDistribution"]},
        )

    # 6 -- changing target invalidates the prior result.
    def test_changing_target_does_not_reuse_the_cached_result(self):
        self._compute()
        other = self._compute(target="Amount")
        self.assertFalse(other["cached"], "a different target must not hit the previous cache entry")
        self.assertEqual(other["target"], "Amount")

    # 7 -- changing version invalidates the prior result.
    def test_changing_version_does_not_reuse_the_cached_result(self):
        self._compute("csv")
        switched = self._compute("parquet")  # different versionId in the artifact
        self.assertFalse(switched["cached"], "a different version must not hit the previous cache entry")

    def test_cache_is_scoped_by_authorization(self):
        self._compute()
        other_user = self._compute(user_scope="user-2")
        self.assertFalse(other_user["cached"], "another user must not read a cached aggregate")

    # 3 (server half) -- the aggregate never touches full quality profiling.
    def test_aggregate_does_not_invoke_quality_profiling(self):
        with mock.patch("server.preprocessing.quality_profile_service.profile_active_dataset") as profiler:
            self._compute()
        profiler.assert_not_called()

    # 9 / 10 -- stratified, disclosed sampling; never labelled exact.
    def test_sampling_fallback_is_stratified_seeded_and_disclosed(self):
        artifact = self._artifact("csv")
        # Force the planner down the sampling path by declaring an oversized artifact.
        artifact["sizeBytes"] = tds.EXACT_MAX_CSV_BYTES + 1
        with mock.patch.object(tds, "_resolve_version_artifact", return_value=artifact), \
             mock.patch.object(tds, "SAMPLE_TARGET_ROWS", 20_000):
            result = tds.compute_target_distribution(
                user_scope="user-1", project_id="proj-1", dataset_id="ds-test",
                version_id=artifact["versionId"], target="Class", event_value=1, non_event_value=0,
            )
        self.assertEqual(result["resolution"], "sampled")
        self.assertNotEqual(result["resolution"], "exact")
        sampling = result["sampling"]
        self.assertEqual(sampling["samplingMethod"], "deterministic_stratified")
        self.assertEqual(sampling["seed"], tds.SAMPLE_SEED)
        self.assertGreater(sampling["sampledRowCount"], 0)
        self.assertEqual(sampling["sourceRowCount"], self.expected_rows)
        # The minority class must survive sampling.
        values = {row["value"] for row in result["classDistribution"]}
        self.assertIn("1", values, "stratified sampling must preserve the minority class")

    def test_force_exact_overrides_the_sampling_policy(self):
        artifact = self._artifact("csv")
        artifact["sizeBytes"] = tds.EXACT_MAX_CSV_BYTES + 1
        with mock.patch.object(tds, "_resolve_version_artifact", return_value=artifact):
            result = tds.compute_target_distribution(
                user_scope="user-1", project_id="proj-1", dataset_id="ds-test",
                version_id=artifact["versionId"], target="Class", event_value=1, non_event_value=0,
                force_exact=True,
            )
        self.assertEqual(result["resolution"], "exact")
        by_value = {row["value"]: row["count"] for row in result["classDistribution"]}
        self.assertEqual(by_value["1"], self.expected_events)

    def test_rare_event_default_never_samples_a_normal_sized_asset(self):
        result = self._compute()
        self.assertEqual(result["resolution"], "exact")
        self.assertNotIn("sampling", result)

    # 12 -- failures surface as errors the caller can retry, not silent wrong data.
    def test_missing_artifact_raises_rather_than_returning_empty_counts(self):
        artifact = self._artifact("csv")
        artifact["path"] = self.tmp / "does_not_exist.csv"
        with mock.patch.object(tds, "_resolve_version_artifact", return_value=artifact):
            with self.assertRaises(HTTPException) as ctx:
                tds.compute_target_distribution(
                    user_scope="user-1", project_id="proj-1", dataset_id="ds-test",
                    version_id="v_missing", target="Class",
                )
        self.assertEqual(ctx.exception.status_code, 500)

    def test_target_and_dataset_are_required(self):
        for overrides in ({"target": ""}, {"dataset_id": ""}):
            kwargs = {"user_scope": "u", "project_id": "p", "dataset_id": "ds", "version_id": "v", "target": "Class"}
            kwargs.update(overrides)
            with self.assertRaises(HTTPException) as ctx:
                tds.compute_target_distribution(**kwargs)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_target_identifier_is_quoted_against_injection(self):
        self.assertEqual(tds._quote_identifier('we"ird'), '"we""ird"')

    # Performance targets for the CLASS_TRAIN-equivalent asset.
    def test_meets_cold_and_warm_performance_targets(self):
        started = time.perf_counter()
        cold = self._compute("parquet")
        cold_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        warm = self._compute("parquet")
        warm_ms = (time.perf_counter() - started) * 1000

        self.assertFalse(cold["cached"])
        self.assertTrue(warm["cached"])
        print(f"\n  [perf] 170,884-row parquet cold={cold_ms:.0f} ms warm={warm_ms:.0f} ms")
        self.assertLess(cold_ms, 2000, f"cold aggregate must be under 2s (was {cold_ms:.0f} ms)")
        self.assertLess(warm_ms, 300, f"warm aggregate must be under 300ms (was {warm_ms:.0f} ms)")


class LargeParquetBenchmarkTests(unittest.TestCase):
    """Multi-million-row Parquet benchmark. The fixture is generated into a temp
    directory and deleted in tearDownClass -- nothing large is committed."""

    ROWS = 1_000_000

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="atlas-target-dist-big-"))
        cls.path = cls.tmp / "big.parquet"
        frame = _make_rare_event_frame(cls.ROWS, 0.0021, seed=11)
        frame.to_parquet(cls.path, index=False)
        cls.expected_events = int(frame["Class"].sum())

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_million_row_parquet_meets_interactive_target(self):
        result_cache.RESULT_CACHE.invalidate_dataset("*")
        artifact = {
            "path": self.path, "format": "parquet", "versionId": "v_big",
            "rowCount": self.ROWS, "sizeBytes": self.path.stat().st_size,
        }
        with mock.patch.object(tds, "_resolve_version_artifact", return_value=artifact):
            started = time.perf_counter()
            cold = tds.compute_target_distribution(
                user_scope="user-1", project_id="proj-1", dataset_id="ds-big",
                version_id="v_big", target="Class", event_value=1, non_event_value=0,
            )
            cold_ms = (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            warm = tds.compute_target_distribution(
                user_scope="user-1", project_id="proj-1", dataset_id="ds-big",
                version_id="v_big", target="Class", event_value=1, non_event_value=0,
            )
            warm_ms = (time.perf_counter() - started) * 1000

        by_value = {row["value"]: row["count"] for row in cold["classDistribution"]}
        self.assertEqual(by_value["1"], self.expected_events)
        self.assertEqual(cold["resolution"], "exact")
        self.assertTrue(warm["cached"])
        size_mb = self.path.stat().st_size / 1024 / 1024
        print(f"\n  [perf] {self.ROWS:,}-row parquet ({size_mb:.0f} MB) cold={cold_ms:.0f} ms warm={warm_ms:.0f} ms")
        self.assertLess(cold_ms, 2000, f"1M-row cold aggregate must be under 2s (was {cold_ms:.0f} ms)")
        self.assertLess(warm_ms, 300)


class FiveMillionRowBenchmarkTests(LargeParquetBenchmarkTests):
    """Same contract at 5M rows. Inherits the assertions; the fixture is still
    generated to a temp dir and deleted, so nothing large is committed."""

    ROWS = 5_000_000


if __name__ == "__main__":
    unittest.main(verbosity=2)
