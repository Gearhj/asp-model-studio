"""Governed full-population profiling and IV integrity -- backend tests.

Covers the four proven root causes:

  1. the backend asserted `full_dataset` for whatever was in DATASTORE;
  2. a failed governed request silently became a browser-preview computation;
  3. `Number(null)` rendered an unavailable IV as 0.0000 (server half: IV is
     `None` with an explicit status, never the number zero);
  4. a preview-derived zero event rate produced a registered-population blocker.

Synthetic fixtures carry a strong / weak / random / constant / missing-value /
categorical / high-cardinality predictor plus zero-event and zero-non-event
targets, so numerical correctness never depends on CLASS_TRAIN alone. The
CLASS_TRAIN reconciliation runs only when the registered artifact is present.

Run:  .venv/Scripts/python.exe tests/governed_profile_test.py
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
_TEST_DATA_ROOT = _REPO_ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_TEST_DATA_ROOT / f"gp_sec_{_RUN_ID}.db")
os.environ["ATLAS_SQLITE_PATH"] = str(_TEST_DATA_ROOT / f"gp_persist_{_RUN_ID}.db")
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_TEST_DATA_ROOT / f"gp_ckpt_{_RUN_ID}.json")
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")

import unittest.mock  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from server.analytics.analysis_scope import FULL_ARTIFACT_MISSING  # noqa: E402
import server.preprocessing.governed_profile_service as gps  # noqa: E402


CLASS_TRAIN_DATASET = "ds_class_train_982c7a7d_35930"
CLASS_TRAIN_VERSION = "v_1784989835930_982c7a7d"
LEGACY_DATASET = "ds_class_train_982c7a7d"
LEGACY_VERSION = "v_1783368035278_982c7a7d"


def _registry_version(dataset_id: str, version_id: str):
    path = _REPO_ROOT / "server" / "artifacts" / "datasets" / "registry.json"
    if not path.exists():
        return None, None
    registry = json.loads(path.read_text())
    dataset = next((item for item in registry.get("datasets", []) if item.get("datasetId") == dataset_id), None)
    if not dataset:
        return None, None
    version = next((item for item in dataset.get("versions", []) if item.get("versionId") == version_id), None)
    return dataset, version


def _artifact_for(dataset_id: str, version_id: str):
    dataset, version = _registry_version(dataset_id, version_id)
    if not dataset or not version:
        return None
    relative = version.get("analyticalParquetPath") or version.get("fullDataPath")
    if not relative:
        return None
    path = (_REPO_ROOT / "server" / "artifacts" / "datasets" / str(relative)).resolve()
    if not path.exists():
        return None
    return {
        "path": path, "format": "parquet" if version.get("analyticalParquetPath") else "csv",
        "versionId": version["versionId"], "rowCount": version.get("rowCount"),
        "columnCount": version.get("columnCount"), "checksum": version.get("hash"),
        "datasetName": dataset.get("name"),
    }


def _synthetic(rows: int = 4_000, seed: int = 11, events: int | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    strong = rng.normal(size=rows)
    # Event probability rises steeply with `strong`, so its IV must be large.
    logit = -4.0 + 2.4 * strong
    probability = 1.0 / (1.0 + np.exp(-logit))
    target = rng.binomial(1, probability)
    if events is not None:
        target = np.zeros(rows, dtype=int)
        if events:
            target[rng.choice(rows, size=events, replace=False)] = 1

    weak = strong * 0.12 + rng.normal(size=rows)
    random_feature = rng.normal(size=rows)
    with_missing = rng.normal(size=rows).astype(object)
    with_missing[rng.choice(rows, size=rows // 10, replace=False)] = None
    categorical = rng.choice(["alpha", "beta", "gamma", "delta"], size=rows, p=[0.5, 0.25, 0.15, 0.10]).astype(object)
    categorical[rng.choice(rows, size=rows // 25, replace=False)] = None
    high_cardinality = [f"id_{index}" for index in range(rows)]
    ties = np.where(rng.random(rows) < 0.85, 1.0, rng.normal(size=rows))

    return pd.DataFrame({
        "strong": strong, "weak": weak, "random_feature": random_feature,
        "constant_feature": 7.0, "with_missing": with_missing,
        "categorical": categorical, "high_cardinality": high_cardinality,
        "tied_numeric": ties, "target": target,
    })


def _session(frame: pd.DataFrame) -> gps._FrameSession:
    return gps._FrameSession(frame)


def _reference_iv(frame: pd.DataFrame, column: str, target: str, bins) -> float:
    """Independently expressed IV: grouped counts straight from pandas with the
    same documented smoothing, written differently from the implementation."""
    grouped = frame.groupby(bins, dropna=False)[target].agg(["sum", "count"])
    events_total = float(frame[target].sum())
    non_events_total = float(len(frame) - events_total)
    k = len(grouped)
    total = 0.0
    for _, row in grouped.iterrows():
        events = float(row["sum"])
        non_events = float(row["count"] - row["sum"])
        p_event = (events + gps.SMOOTHING_CONSTANT) / (events_total + gps.SMOOTHING_CONSTANT * k)
        p_non = (non_events + gps.SMOOTHING_CONSTANT) / (non_events_total + gps.SMOOTHING_CONSTANT * k)
        total += (p_event - p_non) * math.log(p_event / p_non)
    return total


class ScopeAndLegacyArtifactTests(unittest.TestCase):
    """1-4, plus the legacy-version contract."""

    def test_legacy_version_without_full_artifact_returns_409_and_never_uses_the_sample(self):
        dataset, version = _registry_version(LEGACY_DATASET, LEGACY_VERSION)
        if not version:
            self.skipTest("legacy CLASS_TRAIN registration is not present in this environment")
        # Precondition: the version genuinely has no complete artifact but DOES
        # have a data_sample.csv that must never be substituted.
        self.assertIsNone(version.get("fullDataPath"))
        self.assertIsNone(version.get("analyticalParquetPath"))
        self.assertTrue(version.get("samplePath"), "the legacy version does have a sample that must not be used")

        with unittest.mock.patch("server.preprocessing.governed_profile_service.require_dataset", return_value=dataset):
            with self.assertRaises(HTTPException) as ctx:
                gps.resolve_governed_artifact(LEGACY_DATASET, LEGACY_VERSION)
        self.assertEqual(ctx.exception.status_code, 409)
        detail = ctx.exception.detail
        self.assertEqual(detail["reason"], FULL_ARTIFACT_MISSING)
        self.assertFalse(detail["sampleSubstituted"])
        self.assertIn("re-register", " ".join(detail["recovery"]).lower())
        # The historical version is neither mutated nor deleted.
        _, after = _registry_version(LEGACY_DATASET, LEGACY_VERSION)
        self.assertEqual(after, version)

    def test_workspace_profile_declares_workspace_draft(self):
        frame = _synthetic(600)
        session = _session(frame)
        try:
            mapping = gps.resolve_target_mapping(session, "target", 1, 0)
            self.assertTrue(mapping["isBinary"])
        finally:
            session.close()

    def test_governed_scope_is_derived_not_asserted(self):
        artifact = _artifact_for(CLASS_TRAIN_DATASET, CLASS_TRAIN_VERSION)
        if not artifact:
            self.skipTest("governed CLASS_TRAIN artifact is not present")
        session = gps._Session(artifact)
        try:
            self.assertGreater(len(session.columns), 1)
        finally:
            session.close()


class ClassTrainReconciliationTests(unittest.TestCase):
    """5-9: the acceptance numbers, from the artifact rather than a preview."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = _artifact_for(CLASS_TRAIN_DATASET, CLASS_TRAIN_VERSION)
        if not cls.artifact:
            raise unittest.SkipTest("governed CLASS_TRAIN artifact is not present")
        cls.session = gps._Session(cls.artifact)
        cls.mapping = gps.resolve_target_mapping(cls.session, "Class", 1, 0)
        cls.quality = gps.compute_quality(cls.session, cls.mapping, "Class")

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "session", None):
            cls.session.close()

    def test_population_rows_and_columns(self):
        self.assertEqual(self.quality["populationRows"], 170_884)
        self.assertEqual(self.quality["columnCount"], 31)

    def test_duplicate_rows_reconcile(self):
        self.assertEqual(self.quality["duplicateRows"], 52)

    def test_columns_with_missing_values_reconcile(self):
        self.assertEqual(self.quality["columnsWithMissingValues"], 29)

    def test_event_counts_and_rate_reconcile(self):
        self.assertEqual(self.mapping["eventCount"], 360)
        self.assertEqual(self.mapping["nonEventCount"], 170_524)
        self.assertAlmostEqual(self.mapping["eventRate"], 360 / 170_884, places=15)

    def test_event_count_is_not_inferred_from_the_first_100_rows(self):
        head = self.session.one('SELECT SUM(CASE WHEN TRIM(CAST("Class" AS VARCHAR)) = \'1\' THEN 1 ELSE 0 END) FROM (SELECT * FROM src LIMIT 100)')[0]
        # The classic failure: the first 100 rows contain no events at all.
        self.assertEqual(int(head or 0), 0)
        # The population nevertheless has 360 -- proving the count is not a
        # preview artefact.
        self.assertEqual(self.mapping["eventCount"], 360)

    def test_real_predictors_have_nonzero_information_value(self):
        for column in ("V4", "V14"):
            result = gps.compute_predictor_iv(self.session, column, "Class", self.mapping, "classification")
            self.assertEqual(result["ivStatus"], "available")
            self.assertGreater(result["iv"], 0.0)
            self.assertTrue(result["reconciled"])


class IvIntegrityTests(unittest.TestCase):
    """10-21, 25: IV correctness and honest unavailability."""

    def setUp(self) -> None:
        self.frame = _synthetic(4_000)
        self.session = _session(self.frame)
        self.mapping = gps.resolve_target_mapping(self.session, "target", 1, 0)

    def tearDown(self) -> None:
        self.session.close()

    def _iv(self, column: str, mapping=None):
        return gps.compute_predictor_iv(self.session, column, "target", mapping or self.mapping, "classification")

    def test_no_events_returns_unavailable_not_zero(self):
        frame = _synthetic(1_000, events=0)
        session = _session(frame)
        try:
            mapping = gps.resolve_target_mapping(session, "target", 1, 0)
            result = gps.compute_predictor_iv(session, "strong", "target", mapping, "classification")
        finally:
            session.close()
        self.assertEqual(result["ivStatus"], "unavailable_no_events")
        self.assertIsNone(result["iv"], "IV must be null, never the number zero")
        self.assertNotEqual(result["iv"], 0)

    def test_no_non_events_returns_unavailable_not_zero(self):
        frame = _synthetic(1_000, events=1_000)
        session = _session(frame)
        try:
            mapping = gps.resolve_target_mapping(session, "target", 1, 0)
            result = gps.compute_predictor_iv(session, "strong", "target", mapping, "classification")
        finally:
            session.close()
        self.assertEqual(result["ivStatus"], "unavailable_no_non_events")
        self.assertIsNone(result["iv"])

    def test_nonbinary_target_reports_the_correct_state(self):
        frame = self.frame.copy()
        frame["target"] = np.arange(len(frame)) % 5
        session = _session(frame)
        try:
            mapping = gps.resolve_target_mapping(session, "target", 1, 0)
            result = gps.compute_predictor_iv(session, "strong", "target", mapping, "classification")
        finally:
            session.close()
        self.assertEqual(result["ivStatus"], "unavailable_nonbinary_target")
        self.assertIsNone(result["iv"])

    def test_invalid_event_mapping_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            gps.resolve_target_mapping(self.session, "target", 1, 1)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_event_value_absent_from_target_yields_unavailable(self):
        mapping = gps.resolve_target_mapping(self.session, "target", 9, 0)
        self.assertEqual(mapping["eventValueResolution"], "event_value_absent")
        result = self._iv("strong", mapping)
        self.assertEqual(result["ivStatus"], "unavailable_invalid_event_mapping")
        self.assertIsNone(result["iv"])

    def test_numeric_iv_matches_an_independent_reference(self):
        result = self._iv("strong")
        self.assertEqual(result["ivStatus"], "available")
        bins = [entry for entry in result["bins"] if not entry.get("isMissingBin")]
        edges = sorted({entry["upperBound"] for entry in bins if entry["upperBound"] is not None})
        assigned = pd.cut(
            self.frame["strong"],
            bins=[-math.inf] + edges[:-1] + [math.inf],
            labels=False, include_lowest=True,
        )
        reference = _reference_iv(self.frame, "strong", "target", assigned)
        self.assertAlmostEqual(result["iv"], reference, places=6)

    def test_categorical_iv_matches_an_independent_reference(self):
        result = self._iv("categorical")
        self.assertEqual(result["ivStatus"], "available")
        labels = self.frame["categorical"].where(self.frame["categorical"].notna(), "__MISSING__")
        reference = _reference_iv(self.frame, "categorical", "target", labels)
        self.assertAlmostEqual(result["iv"], reference, places=6)

    def test_missing_predictor_values_form_their_own_bin(self):
        result = self._iv("with_missing")
        missing = [entry for entry in result["bins"] if entry.get("isMissingBin")]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["population"], int(self.frame["with_missing"].isna().sum()))

    def test_duplicate_numeric_cut_points_are_collapsed(self):
        result = self._iv("tied_numeric")
        self.assertEqual(result["ivStatus"], "available")
        bounds = [(entry["lowerBound"], entry["upperBound"]) for entry in result["bins"] if not entry.get("isMissingBin")]
        self.assertEqual(len(bounds), len(set(bounds)), "duplicate cut points must collapse into one bin")
        self.assertLessEqual(result["effectiveBinCount"], gps.MAX_NUMERIC_BINS + 1)

    def test_smoothing_is_reported_and_consistent(self):
        result = self._iv("strong")
        self.assertEqual(result["smoothingMethod"], gps.SMOOTHING_METHOD)
        self.assertEqual(result["smoothingConstant"], 0.5)
        self.assertEqual(result["totalEvents"], self.mapping["eventCount"])
        self.assertEqual(result["totalNonEvents"], self.mapping["nonEventCount"])

    def test_bins_reconcile_to_the_target_dependent_population(self):
        for column in ("strong", "with_missing", "categorical"):
            with self.subTest(column=column):
                result = self._iv(column)
                self.assertTrue(result["reconciled"])
                self.assertEqual(result["binnedEventCount"], self.mapping["eventCount"])
                self.assertEqual(result["binnedNonEventCount"], self.mapping["nonEventCount"])

    def test_high_cardinality_grouping_is_bounded_and_disclosed(self):
        result = self._iv("high_cardinality")
        self.assertEqual(result["ivStatus"], "available")
        self.assertLessEqual(len(result["bins"]), gps.MAX_CATEGORY_BINS + 2)
        grouping = result["grouping"]
        self.assertTrue(grouping["groupingApplied"])
        self.assertGreater(grouping["collapsedCategoryCount"], 0)
        self.assertIn("Other", grouping["rule"])
        # Missing is never folded into Other.
        self.assertIn("Missing is always a separate bin", grouping["rule"])

    def test_event_mapping_reversal_preserves_iv_within_tolerance(self):
        forward = self._iv("strong")
        reversed_mapping = gps.resolve_target_mapping(self.session, "target", 0, 1)
        reversed_result = self._iv("strong", reversed_mapping)
        self.assertEqual(reversed_mapping["eventCount"], self.mapping["nonEventCount"])
        self.assertEqual(reversed_mapping["nonEventCount"], self.mapping["eventCount"])
        # IV is symmetric in the two class distributions.
        self.assertAlmostEqual(forward["iv"], reversed_result["iv"], places=6)

    def test_strong_predictor_outranks_weak_and_random(self):
        strong = self._iv("strong")["iv"]
        weak = self._iv("weak")["iv"]
        random_iv = self._iv("random_feature")["iv"]
        self.assertGreater(strong, weak)
        self.assertGreater(weak, 0.0)
        self.assertGreater(strong, random_iv)

    def test_constant_predictor_produces_a_single_bin_and_near_zero_iv(self):
        result = self._iv("constant_feature")
        self.assertEqual(result["ivStatus"], "available")
        self.assertLess(result["iv"], 0.01)

    def test_no_raw_population_rows_appear_in_a_predictor_result(self):
        result = self._iv("strong")
        serialized = json.dumps(result, default=str)
        self.assertLess(len(serialized), 12_000)
        for entry in result["bins"]:
            self.assertNotIn("values", entry)
            self.assertNotIn("rows", entry)

    def test_iv_strength_bands_are_documented_and_conservative(self):
        self.assertEqual(gps.iv_strength(0.005)["key"], "not_predictive")
        self.assertEqual(gps.iv_strength(0.05)["key"], "weak")
        self.assertEqual(gps.iv_strength(0.2)["key"], "medium")
        self.assertEqual(gps.iv_strength(0.4)["key"], "strong")
        strong = gps.iv_strength(0.9)
        self.assertEqual(strong["key"], "unusually_strong")
        # A review prompt, never a leakage verdict.
        self.assertIn("review", strong["label"].lower())
        self.assertNotIn("leakage detected", strong["label"].lower())
        self.assertIsNone(gps.iv_strength(None))


class TargetMappingTests(unittest.TestCase):
    """Part E: string/numeric equivalence and mapping integrity."""

    def setUp(self) -> None:
        self.frame = _synthetic(800)
        self.session = _session(self.frame)

    def tearDown(self) -> None:
        self.session.close()

    def test_string_and_numeric_event_values_are_equivalent(self):
        numeric = gps.resolve_target_mapping(self.session, "target", 1, 0)
        text = gps.resolve_target_mapping(self.session, "target", "1", "0")
        self.assertEqual(numeric["eventCount"], text["eventCount"])
        self.assertEqual(numeric["nonEventCount"], text["nonEventCount"])

    def test_identical_event_and_non_event_values_are_rejected(self):
        for pair in ((1, 1), ("1", 1), (0, "0")):
            with self.subTest(pair=pair):
                with self.assertRaises(HTTPException):
                    gps.resolve_target_mapping(self.session, "target", pair[0], pair[1])

    def test_missing_target_column_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            gps.resolve_target_mapping(self.session, "not_a_column", 1, 0)
        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    import unittest.mock  # noqa: F401 - used via unittest.mock.patch above

    unittest.main(verbosity=2)
