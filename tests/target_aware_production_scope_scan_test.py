from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TargetAwareProductionScopeScanTest(unittest.TestCase):
    """Static guard against reopening a full-target preprocessing fallback."""

    def _source(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def _calls(self, relative: str, names: set[str]) -> list[str]:
        tree = ast.parse(self._source(relative), filename=relative)
        matches: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else ""
            )
            if name in names:
                matches.append(ast.unparse(node))
        return matches

    def test_target_aware_calls_receive_development_materializations(self):
        expectations = {
            "server/preprocessing/outlier_service.py": {
                "information_value": ("development_series",),
            },
            "server/preprocessing/missing_router.py": {
                "information_value": ("development_feature",),
                "_informative_missingness": ("development_feature",),
            },
            "server/preprocessing/governed_profile_service.py": {
                "compute_predictor_iv": ("development_session",),
            },
            "server/preprocessing/bureau_detection_service.py": {
                "_event_rate": ("target_analysis_target",),
                "_event_count": ("target_analysis_target",),
            },
        }
        for relative, calls in expectations.items():
            for call_name, required_tokens in calls.items():
                rendered = self._calls(relative, {call_name})
                self.assertTrue(
                    rendered,
                    f"Expected at least one {call_name} call in {relative}.",
                )
                for call in rendered:
                    self.assertTrue(
                        any(token in call for token in required_tokens),
                        f"Target-aware call is not development-bound: {relative}: {call}",
                    )

        # EDA consumes the immutable durable predictor authorization. It must
        # not recompute deterministic target sources and publish a different
        # inventory under the same authorization identifier.
        self.assertEqual(
            self._calls(
                "server/eda/workspace_service.py",
                {"_detect_frame_target_sources"},
            ),
            [],
        )

    def test_reachable_preprocessing_paths_have_no_full_target_fallback(self):
        sources = {
            relative: self._source(relative)
            for relative in (
                "server/preprocessing/outlier_router.py",
                "server/preprocessing/outlier_service.py",
                "server/preprocessing/missing_router.py",
                "server/preprocessing/feature_profile_service.py",
                "server/preprocessing/governed_profile_service.py",
                "server/preprocessing/bureau_detection_router.py",
                "server/preprocessing/bureau_detection_service.py",
                "server/eda/workspace_service.py",
            )
        }
        joined = "\n".join(sources.values())
        for forbidden in (
            '"target_analysis_scope": "full_dataset_pre_partition"',
            "target_analysis_target = df[target",
            "information_value(feature, full_target",
            "compute_predictor_iv(session,",
            "full_population_target_fallback",
        ):
            self.assertNotIn(
                forbidden,
                joined,
                f"A prohibited full-target fallback reappeared: {forbidden}",
            )

        self.assertIn(
            "structural = source.drop(columns=[scope.target]",
            sources["server/preprocessing/outlier_router.py"],
        )
        self.assertIn(
            ').drop(columns=[scope.target], errors="ignore")',
            sources["server/preprocessing/missing_router.py"],
        )
        self.assertIn(
            "resolve_development_analysis_scope(",
            sources["server/preprocessing/feature_profile_service.py"],
        )
        self.assertIn(
            "development_session",
            sources["server/preprocessing/governed_profile_service.py"],
        )
        self.assertIn(
            "get_raw_active_df(include_target=False)",
            sources["server/preprocessing/bureau_detection_service.py"],
        )
        self.assertNotIn(
            "full_dataset_pre_partition",
            sources["server/preprocessing/bureau_detection_router.py"],
        )
        self.assertIn(
            "factory_df = development.copy(deep=True)",
            sources["server/eda/workspace_service.py"],
        )
        target_preview = sources["server/eda/workspace_service.py"].split(
            "def _target_predictor_preview", 1
        )[1].split("def target_by_predictor", 1)[0]
        self.assertNotIn('"scope": "full_dataset_aggregates"', target_preview)
        self.assertIn(
            '"target_directed_scope": "development_population"',
            target_preview,
        )

    def test_only_data_acquisition_keeps_a_labeled_full_target_exception(self):
        governed = self._source(
            "server/preprocessing/governed_profile_service.py"
        )
        quality = self._source(
            "server/preprocessing/quality_profile_service.py"
        )
        self.assertIn("sole full-target exception", governed)
        self.assertIn("Data Acquisition", governed)
        self.assertIn("compute_quality(session, mapping, target)", governed)
        self.assertIn("profileScope", quality)
        self.assertNotIn("information_value", quality)

    def test_shared_scope_emits_canonical_audit_keys(self):
        scope_source = self._source("server/preprocessing/development_scope.py")
        for key in (
            "analytical_scope",
            "population_id",
            "population_count",
            "partition_id",
            "partition_revision",
            "holdout_excluded",
            "source_checksum",
            "actor",
            "timestamp",
        ):
            self.assertIn(f'"{key}"', scope_source)
        self.assertIn('identity.get("dataset_content_hash")', scope_source)
        self.assertIn('"holdout_excluded": True', scope_source)
        self.assertIn(
            '"analytical_scope": "development_population"', scope_source
        )

    def test_exported_notebook_defers_target_aware_eda_until_development_scope(self):
        notebook = self._source("src/lib/notebookExport.ts")
        for forbidden in (
            "display(df[SELECTED_FEATURES + [TARGET]].describe",
            "df[SELECTED_FEATURES + [TARGET]].isna()",
            "target_rate = df[TARGET]",
            "df[TARGET].hist",
            "y = df[TARGET].copy()",
            "profile_bureau_special_values(df, target=TARGET)",
        ):
            self.assertNotIn(
                forbidden,
                notebook,
                f"Exported notebook reopened pre-partition target access: {forbidden}",
            )

        self.assertIn(
            "y_development = df.iloc[list(DEVELOPMENT_POSITIONS)][TARGET].copy()",
            notebook,
        )
        self.assertIn(
            "Target-directed EDA scope: exact governed development population only.",
            notebook,
        )
        self.assertIn(
            "profile_bureau_special_values(bureau_development_frame, target=None)",
            notebook,
        )
        self.assertIn(
            "target-aware bureau comparison must be returned by the governed backend",
            notebook,
        )
        self.assertNotIn("y.iloc[list(TRAINING_POSITIONS)]", notebook)
        self.assertNotIn("y.iloc[list(VALIDATION_POSITIONS)]", notebook)
        self.assertNotIn("y = df[TARGET]", notebook)
        self.assertIn(
            "y_train = df.iloc[list(TRAINING_POSITIONS)][TARGET].copy()",
            notebook,
        )
        self.assertIn(
            "y_validation = df.iloc[list(VALIDATION_POSITIONS)][TARGET].copy()",
            notebook,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
