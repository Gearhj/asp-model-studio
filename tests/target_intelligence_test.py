"""EDA Target Intelligence, Phase 1 -- backend tests.

Covers the analytical half (exact class balance, the documented rare-event
thresholds, the Wilson score interval, and bounded target-by-predictor
aggregates) and the governance half (authorization, cross-project and
cross-user denial, cache isolation, stale-version separation, durable findings,
and the bounded evidence limit).

The 170,884-row / 360-event fixture reproduces the measured CLASS_TRAIN shape so
the authoritative figures in the brief are asserted directly rather than
approximated. It is generated into a temp directory and deleted -- nothing large
is committed.

Run:  .venv/Scripts/python.exe tests/target_intelligence_test.py
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
_TEST_DATA_ROOT = _REPO_ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_target_intel_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_target_intel_persistence_{_RUN_ID}.db"
_CHECKPOINT_PATH = _TEST_DATA_ROOT / f"atlas_target_intel_checkpoint_{_RUN_ID}.json"
_LIBRARY_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_target_intel_library_{_RUN_ID}_"))
_BACKUP_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_target_intel_backups_{_RUN_ID}_"))
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_LIBRARY_ROOT)
os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(_BACKUP_ROOT)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.analytics import result_cache  # noqa: E402
from server.analytics import target_distribution_service as tds  # noqa: E402
from server.analytics import target_intelligence_service as tis  # noqa: E402
from server.core.dataset_store import get_scoped_dataset_store  # noqa: E402
from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402
from server.datasets import dataset_registry  # noqa: E402


def _bind_dataset_library_paths() -> None:
    """Rebind every cached Dataset Library path to this UUID-owned root."""
    expected_root = _LIBRARY_ROOT.resolve()
    expected_backup_root = _BACKUP_ROOT.resolve()
    os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(expected_root)
    os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(expected_backup_root)
    dataset_registry.ARTIFACT_ROOT = expected_root
    dataset_registry.REGISTRY_PATH = dataset_registry.ARTIFACT_ROOT / "registry.json"
    dataset_registry.USERS_PATH = dataset_registry.ARTIFACT_ROOT / "users.json"
    dataset_registry.PROJECT_LINKS_PATH = (
        dataset_registry.ARTIFACT_ROOT / "project_links.json"
    )
    assert Path(os.environ["ATLAS_DATASET_LIBRARY_ROOT"]).resolve() == expected_root
    assert Path(os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"]).resolve() == expected_backup_root
    assert dataset_registry.ARTIFACT_ROOT.resolve() == expected_root
    assert dataset_registry.REGISTRY_PATH.resolve() == expected_root / "registry.json"
    assert dataset_registry.USERS_PATH.resolve() == expected_root / "users.json"
    assert dataset_registry.PROJECT_LINKS_PATH.resolve() == expected_root / "project_links.json"


def _bind_checkpoint_path() -> None:
    """Keep this suite isolated even when ``server.main`` was imported first."""
    expected = _CHECKPOINT_PATH.resolve()
    os.environ["ATLAS_CHECKPOINT_PATH"] = str(expected)
    checkpoint.CHECKPOINT_PATH = expected
    assert Path(os.environ["ATLAS_CHECKPOINT_PATH"]).resolve() == expected
    assert checkpoint.CHECKPOINT_PATH.resolve() == expected


_bind_dataset_library_paths()
_bind_checkpoint_path()


def setUpModule() -> None:
    _bind_dataset_library_paths()
    _bind_checkpoint_path()


def tearDownModule() -> None:
    _cleanup_db_files()
    shutil.rmtree(_LIBRARY_ROOT, ignore_errors=True)
    shutil.rmtree(_BACKUP_ROOT, ignore_errors=True)


# The measured CLASS_TRAIN figures the brief treats as authoritative.
CLASS_TRAIN_ROWS = 170_884
CLASS_TRAIN_EVENTS = 360
CLASS_TRAIN_NON_EVENTS = 170_524
CLASS_TRAIN_EVENT_RATE = 360 / 170_884  # 0.002106692259...


def _cleanup_db_files() -> None:
    for base in (_SECURITY_DB_PATH, _PERSISTENCE_DB_PATH):
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{base}{suffix}")
            for attempt in range(25):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt < 24:
                        time.sleep(0.2)
    _CHECKPOINT_PATH.unlink(missing_ok=True)
    shutil.rmtree(_BACKUP_ROOT, ignore_errors=True)


def _class_train_frame() -> pd.DataFrame:
    """170,884 rows with exactly 360 events, a target-correlated numeric
    predictor, a numeric predictor with missing values, and a long-tailed
    categorical predictor with missing values."""
    rng = np.random.default_rng(20260725)
    target = np.zeros(CLASS_TRAIN_ROWS, dtype=np.int8)
    # V4 drives the event: the highest V4 rows carry most of the events, so the
    # quantile-band analysis has a real, monotone-ish signal to detect.
    v4 = rng.normal(size=CLASS_TRAIN_ROWS)
    event_index = np.argsort(v4)[-(CLASS_TRAIN_EVENTS * 6):]
    chosen = rng.choice(event_index, size=CLASS_TRAIN_EVENTS, replace=False)
    target[chosen] = 1

    amount = rng.gamma(2.0, 40.0, size=CLASS_TRAIN_ROWS).round(2)
    amount[rng.choice(CLASS_TRAIN_ROWS, size=1_500, replace=False)] = np.nan

    # 40 categories with a heavy head, so top-N + Other is genuinely exercised.
    categories = np.array([f"seg_{i:02d}" for i in range(40)])
    weights = 1.0 / (np.arange(1, 41) ** 1.6)
    segment = rng.choice(categories, size=CLASS_TRAIN_ROWS, p=weights / weights.sum()).astype(object)
    segment[rng.choice(CLASS_TRAIN_ROWS, size=900, replace=False)] = None

    return pd.DataFrame({
        "Time": np.arange(CLASS_TRAIN_ROWS, dtype=np.int64),
        "V4": v4.round(6),
        "Amount": amount,
        "Segment": segment,
        "Class": target,
    })


class WilsonIntervalTests(unittest.TestCase):
    """5 -- the interval is checked against independently calculated values."""

    def test_matches_published_wilson_values(self):
        # Textbook Wilson 95% bounds: 50/100 is published as 0.4038 to 0.5962,
        # 1/10 as 0.0179 to 0.4042. Asserted at published precision.
        fifty = tis.wilson_score_interval(50, 100, 0.95)
        self.assertAlmostEqual(fifty["lowerBound"], 0.4038, places=4)
        self.assertAlmostEqual(fifty["upperBound"], 0.5962, places=4)

        one_in_ten = tis.wilson_score_interval(1, 10, 0.95)
        self.assertAlmostEqual(one_in_ten["lowerBound"], 0.0179, places=4)
        self.assertAlmostEqual(one_in_ten["upperBound"], 0.4042, places=4)

    def test_class_train_event_rate_interval(self):
        interval = tis.wilson_score_interval(CLASS_TRAIN_EVENTS, CLASS_TRAIN_ROWS, 0.95)
        self.assertEqual(interval["method"], "Wilson score interval")
        self.assertEqual(interval["confidenceLevel"], 0.95)
        self.assertEqual(interval["eventCount"], CLASS_TRAIN_EVENTS)
        self.assertEqual(interval["totalCount"], CLASS_TRAIN_ROWS)
        self.assertAlmostEqual(interval["pointEstimate"], CLASS_TRAIN_EVENT_RATE, places=12)
        # Independently calculated by hand from the Wilson formula.
        self.assertAlmostEqual(interval["lowerBound"], 0.0019002089, places=9)
        self.assertAlmostEqual(interval["upperBound"], 0.0023355603, places=9)
        self.assertLess(interval["lowerBound"], CLASS_TRAIN_EVENT_RATE)
        self.assertGreater(interval["upperBound"], CLASS_TRAIN_EVENT_RATE)
        self.assertIn("does not measure model-performance uncertainty", interval["explanation"])

    def test_interval_is_recomputed_independently_by_the_test(self):
        """Recomputes the bounds from the formula with an independent expression
        so a regression in the implementation cannot pass by matching itself."""
        events, total, z = CLASS_TRAIN_EVENTS, CLASS_TRAIN_ROWS, 1.959963984540054
        p = events / total
        a = z * z / total
        expected_center = (p + a / 2) / (1 + a)
        expected_half = (z * math.sqrt(p * (1 - p) / total + a / (4 * total))) / (1 + a)
        interval = tis.wilson_score_interval(events, total, 0.95)
        self.assertAlmostEqual(interval["lowerBound"], expected_center - expected_half, places=12)
        self.assertAlmostEqual(interval["upperBound"], expected_center + expected_half, places=12)

    def test_bounds_stay_inside_the_unit_interval_for_zero_and_full_counts(self):
        zero = tis.wilson_score_interval(0, 5_000, 0.95)
        self.assertEqual(zero["pointEstimate"], 0.0)
        self.assertGreaterEqual(zero["lowerBound"], 0.0)
        full = tis.wilson_score_interval(5_000, 5_000, 0.95)
        self.assertLessEqual(full["upperBound"], 1.0)

    def test_unsupported_confidence_level_is_refused(self):
        with self.assertRaises(HTTPException) as ctx:
            tis.wilson_score_interval(10, 100, 0.93)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_empty_population_returns_no_interval_rather_than_dividing_by_zero(self):
        interval = tis.wilson_score_interval(0, 0, 0.95)
        self.assertIsNone(interval["pointEstimate"])
        self.assertIsNone(interval["lowerBound"])


class ImbalanceAssessmentTests(unittest.TestCase):
    """4 -- the documented rare-event thresholds."""

    def test_class_train_is_an_extreme_rare_event(self):
        assessment = tis.assess_class_balance(CLASS_TRAIN_EVENTS, CLASS_TRAIN_NON_EVENTS)
        # Headline describes the CONFIGURED EVENT's prevalence.
        self.assertEqual(assessment["label"], "Extreme rare event")
        self.assertEqual(assessment["severity"], "critical")
        self.assertTrue(assessment["eventIsRare"])
        self.assertFalse(assessment["eventIsMajority"])
        # Class imbalance is a separate statement.
        self.assertEqual(assessment["classImbalance"]["label"], "Extreme imbalance")
        self.assertAlmostEqual(assessment["minorityShare"], CLASS_TRAIN_EVENT_RATE, places=12)
        # 170,524 / 360 = 473.677..., explicitly oriented.
        self.assertAlmostEqual(assessment["nonEventsPerEvent"], 473.6777777, places=5)
        self.assertAlmostEqual(assessment["imbalanceRatio"], 473.6777777, places=5)
        self.assertEqual(assessment["ratioOrientation"], "non-events per event")
        self.assertEqual(assessment["minorityClass"], "event")

    def test_each_documented_imbalance_tier_is_reachable(self):
        cases = [
            (500, 500, "Balanced"),
            (250, 750, "Mild imbalance"),
            (100, 900, "Moderate imbalance"),
            (20, 980, "Severe imbalance"),
            (5, 9_995, "Extreme imbalance"),
        ]
        for events, non_events, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(tis.assess_class_balance(events, non_events)["classImbalance"]["label"], expected)

    def test_imbalance_tier_boundaries_are_inclusive_lower_bounds(self):
        # Exactly 1% minority share is Severe, not Extreme.
        self.assertEqual(tis.assess_class_balance(10, 990)["classImbalance"]["label"], "Severe imbalance")
        # Exactly 40% is Balanced.
        self.assertEqual(tis.assess_class_balance(400, 600)["classImbalance"]["label"], "Balanced")

    def test_guidance_is_analytical_and_never_selects_a_treatment(self):
        implications = tis.assess_class_balance(CLASS_TRAIN_EVENTS, CLASS_TRAIN_NON_EVENTS)["implications"]
        joined = " ".join(implications).lower()
        self.assertIn("accuracy will be misleading", joined)
        self.assertIn("stratified splitting", joined)
        self.assertIn("pr-auc", joined)
        self.assertIn("compare treatment alternatives", joined)
        # Nothing here may read as a decision that has already been made.
        for banned in ("smote has been enabled", "class weights have been set", "undersampled the", "threshold has been set"):
            self.assertNotIn(banned, joined)

    def test_empty_population_is_reported_as_not_evaluated(self):
        self.assertEqual(tis.assess_class_balance(0, 0)["label"], "Not evaluated")


class TargetIntelligenceAggregateTests(unittest.TestCase):
    """2, 3, 6-11, 15, 16 -- exact aggregates over the governed artifact."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="atlas-target-intel-"))
        frame = _class_train_frame()
        cls.parquet_path = cls.tmp / "class_train.parquet"
        frame.to_parquet(cls.parquet_path, index=False)
        cls.frame = frame

        # A separate frame carrying missing target values.
        gapped = frame.head(1_000).copy()
        gapped.loc[gapped.index[:37], "Class"] = np.nan
        cls.gapped_path = cls.tmp / "gapped.parquet"
        gapped.to_parquet(cls.gapped_path, index=False)
        cls.gapped_missing = 37

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self) -> None:
        result_cache.RESULT_CACHE.invalidate_dataset("*")

    def _artifact(self, path: Path, version_id: str, rows: int) -> dict:
        return {
            "path": path, "format": "parquet", "versionId": version_id,
            "rowCount": rows, "sizeBytes": path.stat().st_size,
        }

    def _patched(self, artifact: dict):
        """Both modules resolve the artifact; both must be redirected."""
        return mock.patch.multiple(
            "server.analytics.target_distribution_service",
            _resolve_version_artifact=mock.DEFAULT,
        ), mock.patch.object(tis, "_resolve_version_artifact", return_value=artifact)

    def _assessment(self, **overrides):
        artifact = self._artifact(self.parquet_path, "v_class_train", CLASS_TRAIN_ROWS)
        artifact.update(overrides.pop("artifact", {}))
        kwargs = dict(
            user_scope="user-1", project_id="proj-1", dataset_id="ds-class-train",
            version_id=artifact["versionId"], target="Class", event_value=1, non_event_value=0,
        )
        kwargs.update(overrides)
        with mock.patch.object(tds, "_resolve_version_artifact", return_value=artifact), \
             mock.patch.object(tis, "_resolve_version_artifact", return_value=artifact):
            return tis.compute_target_assessment(**kwargs)

    def _by_predictor(self, **overrides):
        artifact = self._artifact(self.parquet_path, "v_class_train", CLASS_TRAIN_ROWS)
        artifact.update(overrides.pop("artifact", {}))
        kwargs = dict(
            user_scope="user-1", project_id="proj-1", dataset_id="ds-class-train",
            version_id=artifact["versionId"], target="Class", predictor="V4",
            analysis_type="numeric_quantile", event_value=1,
        )
        kwargs.update(overrides)
        with mock.patch.object(tds, "_resolve_version_artifact", return_value=artifact), \
             mock.patch.object(tis, "_resolve_version_artifact", return_value=artifact):
            return tis.compute_target_by_predictor(**kwargs)

    # 2 / 3 -----------------------------------------------------------------
    def test_exact_class_counts_and_event_rate(self):
        result = self._assessment()
        balance = result["classBalance"]
        self.assertTrue(result["supported"])
        self.assertEqual(balance["resolution"], "exact")
        self.assertEqual(balance["eventCount"], CLASS_TRAIN_EVENTS)
        self.assertEqual(balance["nonEventCount"], CLASS_TRAIN_NON_EVENTS)
        self.assertEqual(balance["totalModelingPopulation"], CLASS_TRAIN_ROWS)
        self.assertAlmostEqual(balance["eventRate"], CLASS_TRAIN_EVENT_RATE, places=12)
        # Explicitly NOT the earlier incorrect constant.
        self.assertNotAlmostEqual(balance["eventRate"], 0.0021067178, places=9)
        self.assertAlmostEqual(balance["eventRate"] * 100, 0.2106692259, places=8)

    # 4 (over the real aggregate) -------------------------------------------
    def test_imbalance_ratio_over_the_exact_aggregate(self):
        result = self._assessment()
        self.assertAlmostEqual(result["classBalance"]["imbalanceRatio"], 473.6777777, places=5)
        self.assertEqual(result["imbalance"]["label"], "Extreme rare event")
        self.assertEqual(result["imbalance"]["classImbalance"]["label"], "Extreme imbalance")

    # 5 (wired through the endpoint payload) --------------------------------
    def test_assessment_carries_the_confidence_interval(self):
        interval = self._assessment()["confidenceInterval"]
        self.assertAlmostEqual(interval["lowerBound"], 0.0019002089, places=9)
        self.assertAlmostEqual(interval["upperBound"], 0.0023355603, places=9)

    # 6 ---------------------------------------------------------------------
    def test_missing_target_rows_are_counted_not_silently_dropped(self):
        artifact = self._artifact(self.gapped_path, "v_gapped", 1_000)
        with mock.patch.object(tds, "_resolve_version_artifact", return_value=artifact), \
             mock.patch.object(tis, "_resolve_version_artifact", return_value=artifact):
            result = tis.compute_target_assessment(
                user_scope="user-1", project_id="proj-1", dataset_id="ds-gapped",
                version_id="v_gapped", target="Class", event_value=1, non_event_value=0,
            )
        self.assertEqual(result["classBalance"]["missingTargetCount"], self.gapped_missing)

    # 7 ---------------------------------------------------------------------
    def test_numeric_quantile_bands_are_correct(self):
        result = self._by_predictor(bands=10)
        self.assertEqual(result["analysisType"], "numeric_quantile")
        self.assertEqual(result["resolution"], "exact")
        self.assertEqual(len(result["rows"]), 10)

        # Every row is aggregate-only: no predictor or target values escape.
        for row in result["rows"]:
            self.assertNotIn("values", row)
            self.assertLessEqual(row["eventCount"], row["population"])

        # Bands partition the non-missing population exactly.
        self.assertEqual(sum(row["population"] for row in result["rows"]), CLASS_TRAIN_ROWS)
        self.assertEqual(sum(row["eventCount"] for row in result["rows"]), CLASS_TRAIN_EVENTS)
        # NTILE keeps band populations balanced to within one row.
        sizes = {row["population"] for row in result["rows"]}
        self.assertLessEqual(max(sizes) - min(sizes), 1)
        # Bands are ordered and their ranges do not overlap.
        for lower, upper in zip(result["rows"], result["rows"][1:]):
            self.assertLessEqual(lower["upperBound"], upper["lowerBound"])
        # The fixture concentrates events in the highest V4 bands.
        self.assertEqual(result["summary"]["highest"]["label"], "Q10")

        boxes = result["boxPlotByTarget"]
        self.assertEqual({row["targetClass"] for row in boxes}, {"event", "non_event"})
        self.assertEqual(sum(row["population"] for row in boxes), CLASS_TRAIN_ROWS)
        for row in boxes:
            self.assertLessEqual(row["minimum"], row["q1"])
            self.assertLessEqual(row["q1"], row["median"])
            self.assertLessEqual(row["median"], row["q3"])
            self.assertLessEqual(row["q3"], row["maximum"])
            self.assertGreaterEqual(row["whiskerLow"], row["minimum"])
            self.assertLessEqual(row["whiskerHigh"], row["maximum"])
            self.assertGreaterEqual(row["outlierCount"], 0)
            self.assertNotIn("values", row)

    def test_band_count_is_bounded(self):
        self.assertEqual(len(self._by_predictor(bands=999)["rows"]), tis.MAX_BANDS)
        result_cache.RESULT_CACHE.invalidate_dataset("*")
        self.assertEqual(len(self._by_predictor(bands=1)["rows"]), tis.MIN_BANDS)

    # 8 / 10 ----------------------------------------------------------------
    def test_categorical_groups_and_top_n_disclosure(self):
        result = self._by_predictor(predictor="Segment", analysis_type="categorical", top_categories=5)
        self.assertEqual(result["analysisType"], "categorical")
        self.assertEqual(len(result["rows"]), 5)
        self.assertTrue(result["topNApplied"])
        self.assertIsNotNone(result["otherGroup"])
        self.assertEqual(result["otherGroup"]["category"], "Other")
        self.assertEqual(result["otherGroup"]["collapsedCategoryCount"], 40 - 5)
        self.assertEqual(result["distinctCategoryCount"], 40)
        # The disclosure is present in the analytical summary, not only in a flag.
        self.assertTrue(any("Other" in item for item in result["summary"]["limitations"]))
        # Populations and events reconcile against the exact class aggregate.
        total_population = sum(row["population"] for row in result["rows"]) + result["otherGroup"]["population"] + result["missingGroup"]["population"]
        total_events = sum(row["eventCount"] for row in result["rows"]) + result["otherGroup"]["eventCount"] + result["missingGroup"]["eventCount"]
        self.assertEqual(total_population, CLASS_TRAIN_ROWS)
        self.assertEqual(total_events, CLASS_TRAIN_EVENTS)

    # 9 ---------------------------------------------------------------------
    def test_missing_group_is_separate_and_never_collapsed_into_other(self):
        result = self._by_predictor(predictor="Segment", analysis_type="categorical", top_categories=2)
        missing = result["missingGroup"]
        self.assertIsNotNone(missing)
        self.assertEqual(missing["category"], "Missing")
        self.assertEqual(missing["population"], 900)
        self.assertTrue(missing["isMissingGroup"])
        self.assertFalse(missing.get("isOtherGroup"))

    def test_numeric_missing_group_is_reported_and_can_be_excluded(self):
        with_missing = self._by_predictor(predictor="Amount", bands=5)
        self.assertIsNotNone(with_missing["missingGroup"])
        self.assertEqual(with_missing["missingGroup"]["population"], 1_500)
        self.assertIsNotNone(with_missing["summary"]["missingEffect"])

        result_cache.RESULT_CACHE.invalidate_dataset("*")
        without_missing = self._by_predictor(predictor="Amount", bands=5, include_missing=False)
        self.assertIsNone(without_missing["missingGroup"])
        self.assertFalse(without_missing["includeMissing"])

    # 11 --------------------------------------------------------------------
    def test_bounded_result_limits_are_enforced(self):
        result = self._by_predictor(predictor="Segment", analysis_type="categorical", top_categories=999)
        self.assertLessEqual(len(result["rows"]), tis.MAX_TOP_CATEGORIES)
        payload = json.dumps(result)
        self.assertLess(len(payload), 24_000, "the bounded payload must stay small")
        # No key anywhere carries raw rows.
        self.assertNotIn('"records"', payload)

    def test_identifier_like_predictor_is_refused_rather_than_returned(self):
        with self.assertRaises(HTTPException) as ctx:
            self._by_predictor(predictor="Time", analysis_type="categorical")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("identifier", ctx.exception.detail)

    def test_target_cannot_be_analyzed_against_itself(self):
        with self.assertRaises(HTTPException) as ctx:
            self._by_predictor(predictor="Class")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_unsupported_analysis_type_is_refused(self):
        with self.assertRaises(HTTPException) as ctx:
            self._by_predictor(analysis_type="crosstab")
        self.assertEqual(ctx.exception.status_code, 400)

    # Summary conservatism ---------------------------------------------------
    def test_small_groups_are_excluded_from_the_highest_lowest_ranking(self):
        result = self._by_predictor(bands=20)
        summary = result["summary"]
        self.assertIn("monotonicity", summary)
        self.assertIsNotNone(summary["interpretation"])
        self.assertIn("does not establish predictive value", summary["interpretation"])
        if summary["smallGroupCount"]:
            self.assertTrue(any("excluded from the highest/lowest ranking" in item for item in summary["limitations"]))

    # 15 --------------------------------------------------------------------
    def test_cache_is_isolated_by_authorization_scope(self):
        first = self._assessment()
        self.assertFalse(first["cached"])
        same_user = self._assessment()
        self.assertTrue(same_user["cached"])
        other_user = self._assessment(user_scope="user-2")
        self.assertFalse(other_user["cached"], "another user must not read a cached target aggregate")

    def test_predictor_cache_is_isolated_by_authorization_scope(self):
        self.assertFalse(self._by_predictor()["cached"])
        self.assertTrue(self._by_predictor()["cached"])
        self.assertFalse(self._by_predictor(user_scope="user-2")["cached"])

    # 16 --------------------------------------------------------------------
    def test_a_different_version_is_a_different_result(self):
        self._by_predictor()
        other = self._by_predictor(artifact={"versionId": "v_class_train_b"}, version_id="v_class_train_b")
        self.assertFalse(other["cached"], "a different version must not hit the previous cache entry")
        self.assertEqual(other["versionId"], "v_class_train_b")

    def test_a_different_predictor_is_a_different_result(self):
        self._by_predictor()
        other = self._by_predictor(predictor="Amount")
        self.assertFalse(other["cached"])
        self.assertEqual(other["predictor"], "Amount")

    # Performance ------------------------------------------------------------
    def test_meets_cold_and_warm_performance_targets(self):
        started = time.perf_counter()
        cold = self._assessment()
        cold_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        warm = self._assessment()
        warm_ms = (time.perf_counter() - started) * 1000
        self.assertFalse(cold["cached"])
        self.assertTrue(warm["cached"])
        print(f"\n  [perf] target assessment cold={cold_ms:.0f} ms warm={warm_ms:.0f} ms")
        self.assertLess(cold_ms, 2000)
        self.assertLess(warm_ms, 300)

    def test_target_by_predictor_meets_interactive_targets(self):
        started = time.perf_counter()
        numeric = self._by_predictor(bands=10)
        numeric_ms = (time.perf_counter() - started) * 1000
        result_cache.RESULT_CACHE.invalidate_dataset("*")
        started = time.perf_counter()
        categorical = self._by_predictor(predictor="Segment", analysis_type="categorical")
        categorical_ms = (time.perf_counter() - started) * 1000
        numeric_bytes = len(json.dumps(numeric).encode("utf-8"))
        categorical_bytes = len(json.dumps(categorical).encode("utf-8"))
        print(
            f"\n  [perf] target-by-predictor numeric={numeric_ms:.0f} ms ({numeric_bytes} B) "
            f"categorical={categorical_ms:.0f} ms ({categorical_bytes} B)"
        )
        self.assertLess(numeric_ms, 2500)
        self.assertLess(categorical_ms, 2500)
        self.assertLess(numeric_bytes, 12_000)
        self.assertLess(categorical_bytes, 12_000)


# ---------------------------------------------------------------------------
# Endpoint-level governance
# ---------------------------------------------------------------------------


def _register(label: str) -> TestClient:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post("/api/auth/register", json={
        "email": f"{label}-{suffix}@atlas-target-intel-test.local",
        "displayName": f"Target Intelligence {label} {suffix}",
        "password": "TargetIntelPass!1",
        "role": "data_scientist",
    })
    assert response.status_code == 200, response.text
    return client


def _create_project(client: TestClient, name: str) -> str:
    response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


class FullPopulationTargetByPredictorTests(unittest.TestCase):
    """The endpoint uses the exact registered version and development split.

    These cases began as legacy in-memory-twin coverage.  The fixture now
    provisions the governed identity and split that target-directed EDA
    requires, while retaining the bounded-shape and validation assertions.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    def setUp(self) -> None:
        self.client = _register("fullpop")
        self.project_id = _create_project(self.client, "Full Population Target Project")
        rows = []
        for index in range(1_200):
            rows.append({
                "score": float(index % 300),
                "segment": None if index % 100 == 0 else f"seg_{index % 25}",
                "target": "event" if index % 60 == 0 else "non_event",
            })
        frame = pd.DataFrame(rows)
        _bind_dataset_library_paths()
        upload = self.client.post(
            "/api/datasets/upload",
            files={
                "file": (
                    "target_by_predictor.csv",
                    frame.to_csv(index=False).encode("utf-8"),
                    "text/csv",
                )
            },
            data={
                "name": f"Target by predictor {uuid.uuid4().hex[:8]}",
                "description": "Governed endpoint test fixture",
                "domain": "general",
                "projectId": self.project_id,
            },
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        dataset = upload.json()["dataset"]
        self.dataset_id = dataset["datasetId"]
        self.dataset_version_id = (
            dataset.get("latestVersion") or dataset["versions"][-1]
        )["versionId"]

        activation = self.client.post(
            f"/api/datasets/{self.dataset_id}/versions/{self.dataset_version_id}/activate",
            params={"project_id": self.project_id},
        )
        self.assertEqual(activation.status_code, 200, activation.text)

        target = self.client.post("/api/data/set_target", json={
            "project_id": self.project_id,
            "target": "target",
            "selected_columns": ["score", "segment"],
            "expected_dataset_id": self.dataset_id,
            "expected_dataset_version_id": self.dataset_version_id,
        })
        self.assertEqual(target.status_code, 200, target.text)

        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200, me.text)
        user_id = me.json()["user"]["userId"]
        scoped_store = get_scoped_dataset_store((user_id, self.project_id))
        manifest_version = f"fm-target-by-predictor-{uuid.uuid4().hex[:10]}"
        with scoped_store.state_lock:
            scoped_store.meta["feature_manifest"] = {
                "project_id": self.project_id,
                "dataset_id": self.dataset_id,
                "dataset_version_id": self.dataset_version_id,
                "manifest_version": manifest_version,
                "features": [
                    {
                        "feature_name": feature,
                        "selected": True,
                        "eligibility_status": "eligible",
                        "origin": "original",
                    }
                    for feature in ("score", "segment")
                ],
            }

        split = self.client.post("/api/balancing_split/config", json={
            "project_id": self.project_id,
            "split_strategy": "holdout",
            "test_size": 0.2,
            "random_seed": 42,
            "stratify": True,
            "balance_method": "none",
            "problem_type": "classification",
            "event_value": "event",
            "selected_features": ["score", "segment"],
            "feature_manifest_version": manifest_version,
            "dataset_id": self.dataset_id,
            "dataset_version_id": self.dataset_version_id,
            "fold_method": "none",
            "holdout_protection_confirmed": True,
        })
        self.assertEqual(split.status_code, 200, split.text)
        self.development_rows = int(len(scoped_store.X_train))
        self.development_events = int(scoped_store.y_train.eq("event").sum())
        self.development_missing_segments = int(
            scoped_store.X_train["segment"].isna().sum()
        )

    def _run(self, **overrides):
        body = {
            "project_id": self.project_id, "target": "target", "event_value": "event",
            "predictor": "score", "analysis_type": "numeric_quantile", "bands": 10,
            "expected_dataset_id": self.dataset_id,
            "expected_dataset_version_id": self.dataset_version_id,
        }
        body.update(overrides)
        return self.client.post("/api/eda/target-by-predictor", json=body)

    def test_numeric_bands_reconcile_against_the_population(self):
        response = self._run()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["resolution"], "exact")
        self.assertEqual(body["engine"], "governed_eda_analytical_contract")
        self.assertEqual(body["source"], "eda_exact_development_population")
        self.assertEqual(len(body["rows"]), 10)
        self.assertEqual(sum(row["population"] for row in body["rows"]), self.development_rows)
        self.assertEqual(sum(row["eventCount"] for row in body["rows"]), self.development_events)
        self.assertFalse(body["analysisScope"]["finalHoldoutAccessed"])
        self.assertIn("interpretation", body["summary"])

    def test_categorical_groups_disclose_top_n_and_missing(self):
        response = self._run(predictor="segment", analysis_type="categorical", top_categories=5)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["rows"]), 5)
        self.assertTrue(body["topNApplied"])
        self.assertEqual(body["otherGroup"]["category"], "Other")
        self.assertEqual(body["missingGroup"]["category"], "Missing")
        self.assertEqual(body["missingGroup"]["population"], self.development_missing_segments)
        total = sum(row["population"] for row in body["rows"]) + body["otherGroup"]["population"] + body["missingGroup"]["population"]
        self.assertEqual(total, self.development_rows)

    def test_only_grouped_counts_are_returned(self):
        body = self._run().json()
        payload = json.dumps(body)
        self.assertLess(len(payload), 60_000)
        for row in body["rows"]:
            self.assertEqual(
                set(row) - {
                    "band", "lowerBound", "upperBound", "meanValue",
                    "isMissingGroup", "isBureauSpecialGroup", "governedBinLabel",
                },
                {"label", "population", "eventCount", "eventRate", "smallGroup"},
            )

    def test_target_cannot_be_analyzed_against_itself(self):
        response = self._run(predictor="target")
        self.assertEqual(response.status_code, 400, response.text)

    def test_unknown_predictor_is_refused(self):
        self.assertEqual(self._run(predictor="not_a_column").status_code, 400)

    def test_cross_project_denial(self):
        other_client = _register("fullpop-other")
        other_project = _create_project(other_client, "Other Full Population Project")
        response = self.client.post("/api/eda/target-by-predictor", json={
            "project_id": other_project, "target": "target", "predictor": "score",
            "expected_dataset_id": self.dataset_id,
            "expected_dataset_version_id": self.dataset_version_id,
        })
        self.assertIn(response.status_code, (403, 404), response.text)


class TargetIntelligenceEndpointTests(unittest.TestCase):
    """1, 12-14, 17, 18."""

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    def setUp(self) -> None:
        self.client = _register("owner")
        self.project_id = _create_project(self.client, "Target Intelligence Test Project")

    # 1 ---------------------------------------------------------------------
    def test_project_context_target_definitions_are_retrieved(self):
        context = {
            "targetDefinition": "A confirmed fraudulent card transaction within the performance window.",
            "populationDefinition": "All settled card transactions for active accounts.",
            "observationWindow": "24 months of transaction history prior to scoring.",
            "performanceWindow": "60 days after the transaction date.",
            "businessObjective": "Reduce fraud loss without increasing false declines.",
            "fraudDetails": {"approvedUses": "Fraud triage queue prioritization."},
        }
        put = self.client.put(f"/api/projects/{self.project_id}", json={
            "projectName": "Target Intelligence Test Project",
            "projectType": "predictive-modeling",
            "metadata": {"projectContext": context, "projectContextRevision": "rev-1"},
        })
        self.assertEqual(put.status_code, 200, put.text)

        got = self.client.get(f"/api/projects/{self.project_id}")
        self.assertEqual(got.status_code, 200, got.text)
        stored = got.json()["project"]["metadata"]["projectContext"]
        self.assertEqual(stored["targetDefinition"], context["targetDefinition"])
        self.assertEqual(stored["populationDefinition"], context["populationDefinition"])
        self.assertEqual(stored["observationWindow"], context["observationWindow"])
        self.assertEqual(stored["performanceWindow"], context["performanceWindow"])
        self.assertEqual(stored["fraudDetails"]["approvedUses"], "Fraud triage queue prioritization.")

    # 12 --------------------------------------------------------------------
    def test_unauthenticated_requests_are_rejected(self):
        anonymous = TestClient(app)
        for path, payload in (
            ("/api/analytics/target-assessment", {"projectId": self.project_id, "datasetId": "ds", "target": "Class"}),
            ("/api/analytics/target-by-predictor", {"projectId": self.project_id, "datasetId": "ds", "target": "Class", "predictor": "V4"}),
            ("/api/analytics/target-findings", {"projectId": self.project_id, "title": "x"}),
        ):
            with self.subTest(path=path):
                response = anonymous.post(path, json=payload)
                self.assertIn(response.status_code, (401, 403), response.text)

    # 13 --------------------------------------------------------------------
    def test_cross_project_access_is_denied(self):
        other_client = _register("other-owner")
        other_project = _create_project(other_client, "Someone Else's Project")
        response = self.client.post("/api/analytics/target-assessment", json={
            "projectId": other_project, "datasetId": "ds-any", "target": "Class",
        })
        self.assertEqual(response.status_code, 403, response.text)

    def test_cross_project_finding_write_is_denied(self):
        other_client = _register("other-writer")
        other_project = _create_project(other_client, "Other Writer Project")
        response = self.client.post("/api/analytics/target-findings", json={
            "projectId": other_project, "title": "Injected finding", "target": "Class",
        })
        self.assertEqual(response.status_code, 403, response.text)

    # 14 --------------------------------------------------------------------
    def test_cross_user_finding_read_is_denied(self):
        # A draft finding: no dataset/version is claimed, so no registered asset
        # has to exist for this authorization check.
        created = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "workspaceFingerprint": "wsfp_test",
            "target": "Class", "title": "Event rate is extremely low", "severity": "warning",
        })
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["finding"]["scopeMode"], "workspace_draft")

        intruder = _register("intruder")
        response = intruder.get("/api/analytics/target-findings", params={"projectId": self.project_id})
        self.assertEqual(response.status_code, 403, response.text)

    def test_cross_project_finding_update_is_denied_even_with_a_valid_id(self):
        created = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "workspaceFingerprint": "wsfp_test",
            "target": "Class", "title": "Original finding",
        }).json()["finding"]
        second_project = _create_project(self.client, "Second Project Owned By Same User")
        response = self.client.put(
            f"/api/analytics/target-findings/{created['targetFindingId']}",
            json={"projectId": second_project, "title": "Rewritten through another project"},
        )
        self.assertEqual(response.status_code, 403, response.text)

    # 17 --------------------------------------------------------------------
    def test_findings_persist_and_carry_their_analytical_identity(self):
        # Draft persistence. Governed persistence against a genuinely registered
        # version is covered in tests/analysis_scope_test.py, which registers a
        # real Dataset Library asset.
        created = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "workspaceFingerprint": "wsfp_class_train",
            "target": "Class", "analysisType": "target_by_numeric_quantile",
            "title": "Q10 of V4 concentrates events", "detail": "Highest band holds most events.",
            "severity": "review", "metadata": {"eventRate": CLASS_TRAIN_EVENT_RATE},
        })
        self.assertEqual(created.status_code, 200, created.text)
        finding = created.json()["finding"]
        self.assertEqual(finding["scopeMode"], "workspace_draft")
        # A draft finding never claims a dataset version.
        self.assertIsNone(finding["datasetId"])
        self.assertIsNone(finding["versionId"])
        self.assertEqual(finding["workspaceFingerprint"], "wsfp_class_train")
        self.assertEqual(finding["scopeLabel"], "Draft Finding")
        self.assertEqual(finding["target"], "Class")
        self.assertEqual(finding["status"], "open")
        self.assertTrue(finding["createdAt"])
        self.assertTrue(finding["createdByUserId"])

        # Reviewed, then resolved.
        reviewed = self.client.put(f"/api/analytics/target-findings/{finding['targetFindingId']}",
                                   json={"projectId": self.project_id, "status": "reviewed"})
        self.assertEqual(reviewed.json()["finding"]["status"], "reviewed")
        resolved = self.client.put(f"/api/analytics/target-findings/{finding['targetFindingId']}",
                                   json={"projectId": self.project_id, "status": "resolved", "title": "Edited title"})
        self.assertEqual(resolved.json()["finding"]["status"], "resolved")
        self.assertEqual(resolved.json()["finding"]["title"], "Edited title")

        # A fresh client for the same user reads the durable record back.
        listed = self.client.get("/api/analytics/target-findings", params={
            "projectId": self.project_id, "scopeMode": "workspace_draft",
            "workspaceFingerprint": "wsfp_class_train", "target": "Class",
        })
        self.assertEqual(listed.status_code, 200, listed.text)
        ids = [item["targetFindingId"] for item in listed.json()["findings"]]
        self.assertIn(finding["targetFindingId"], ids)

    def test_draft_findings_are_scoped_to_their_workspace_fingerprint(self):
        self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "workspaceFingerprint": "wsfp_a", "target": "Class", "title": "On upload A",
        })
        other_workspace = self.client.get("/api/analytics/target-findings", params={
            "projectId": self.project_id, "scopeMode": "workspace_draft", "workspaceFingerprint": "wsfp_b",
        })
        self.assertEqual(other_workspace.json()["findings"], [])

    def test_a_fabricated_dataset_version_is_refused_rather_than_stored(self):
        response = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "datasetId": "ds-does-not-exist", "versionId": "v-fake",
            "target": "Class", "title": "Crafted governed finding",
        })
        self.assertIn(response.status_code, (403, 404), response.text)

    def test_invalid_severity_and_status_are_refused(self):
        for payload in ({"severity": "catastrophic"}, {"status": "archived"}):
            with self.subTest(payload=payload):
                response = self.client.post("/api/analytics/target-findings", json={
                    "projectId": self.project_id, "title": "x", **payload,
                })
                self.assertEqual(response.status_code, 400, response.text)

    # 18 --------------------------------------------------------------------
    def test_evidence_payload_is_bounded_by_row_count(self):
        response = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "title": "Oversized",
            "metadata": {"rows": [{"group": str(i), "population": i} for i in range(200)]},
        })
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("bounded result-row limit", response.json()["detail"])

    def test_evidence_payload_is_bounded_by_serialized_size(self):
        response = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "title": "Oversized bytes",
            "metadata": {"blob": "x" * 200_000},
        })
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("bounded-summary limit", response.json()["detail"])

    def test_bounded_metadata_within_the_limit_is_accepted(self):
        response = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "title": "Within limits",
            "metadata": {"rows": [{"group": f"Q{i}", "eventRate": 0.002} for i in range(10)]},
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["finding"]["metadata"]["rows"]), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
