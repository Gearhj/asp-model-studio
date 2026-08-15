from __future__ import annotations

import hashlib
import importlib
import json
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping
from unittest.mock import patch

from server.analysis_partition.service import analysis_partition_service
from server.analysis_partition.types import (
    AnalysisPartitionConfirmRequest,
    AnalysisPartitionPreviewRequest,
)
from server.persistence.db import Database
from server.persistence.service import PersistenceService
from server.preprocessing.special_value_review_service import (
    detection_fingerprint,
    initial_review_state,
    public_review_contract,
)


partition_router = importlib.import_module("server.analysis_partition.router")


class GovernedAnalysisFixture:
    """Isolated durable Data Acquisition + Analysis Partition test authority.

    Production EDA intentionally has no checkpoint, split, first-version, or
    full-population fallback. Older service tests therefore install the exact
    durable pre-EDA contracts explicitly in a temporary SQLite database.
    """

    def __init__(
        self,
        *,
        project_id: str,
        owner: str = "governed-analysis-test",
    ) -> None:
        root = Path(__file__).resolve().parents[1] / ".tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.database_path = root / f"governed_analysis_{uuid.uuid4().hex}.db"
        self.database = Database(self.database_path)
        self.database.initialize()
        self.persistence = PersistenceService(self.database)
        self.project_id = project_id
        self.owner = owner
        self.persistence.projects.upsert(
            {
                "project_id": project_id,
                "project_name": "Governed Analysis Fixture",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": owner,
                "created_by": owner,
                "updated_by": owner,
            }
        )
        self._previous_repository = analysis_partition_service._repository
        analysis_partition_service._repository = self.persistence.analysis_partitions
        self._persistence_patch = patch(
            "server.persistence.service.get_persistence_service",
            return_value=self.persistence,
        )
        self._persistence_patch.start()

    @staticmethod
    def _hash(payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def install(
        self,
        store: Any,
        *,
        dataset_id: str,
        dataset_version_id: str,
        target: str,
        authorized_predictors: Iterable[str],
        positive_value: Any = 1,
        negative_value: Any = 0,
        development_share: float = 0.8,
        random_seed: int = 42,
        stratification_policy: str = "target",
        target_sources: Iterable[str] = (),
        excluded_predictors: Mapping[str, str] | None = None,
        reset_existing: bool = False,
    ) -> dict[str, Any]:
        predictors = [str(value) for value in authorized_predictors]
        sources = sorted({str(value) for value in target_sources})
        excluded = dict(excluded_predictors or {})
        # Production authorization values arrive through JSON/Pydantic as
        # JSON-native scalars. Normalize numpy/pandas test inputs before the
        # contract is hashed so the durable manifest can reproduce its own
        # checksum after the repository JSON round-trip.
        positive_value = (
            positive_value.item()
            if hasattr(positive_value, "item")
            else positive_value
        )
        negative_value = (
            negative_value.item()
            if hasattr(negative_value, "item")
            else negative_value
        )
        for source in sources:
            excluded.setdefault(source, "Deterministic source of modeling target")
        target_contract_payload = {
            "project_id": self.project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "target": target,
            "positive_value": positive_value,
            "negative_value": negative_value,
        }
        target_contract_id = (
            f"target-contract-{self._hash(target_contract_payload)[:20]}"
        )
        target_source_fields = [
            {
                "field": source,
                "target": target,
                "relationship": "governed_upstream_target_source",
                "mapping": [],
            }
            for source in sources
        ]
        authorization_base = {
            **target_contract_payload,
            "target_contract_id": target_contract_id,
            "authorized_predictors": sorted(predictors),
            "excluded_predictors": excluded,
            "selected_predictors": sorted(predictors),
            "target_source_excluded": sources,
            "target_source_detection_scope": (
                "registered_population_pre_partition"
                if sources
                else "registered_population_pre_partition_no_source_detected"
            ),
            "target_source_fields": target_source_fields,
            "source": "data_acquisition",
        }
        authorization_id = (
            f"predictor-auth-{self._hash(authorization_base)[:20]}"
        )
        authorization_payload = {
            **authorization_base,
            "predictor_authorization_id": authorization_id,
            "manifest_version": authorization_id,
            "artifact_hash": authorization_id.removeprefix("predictor-auth-"),
            "status": "current",
            "created_by": self.owner,
        }
        self.persistence.predictor_authorizations.set_current(
            authorization_payload
        )
        raw_frame = getattr(store, "raw_df", None)
        if raw_frame is None:
            raise AssertionError("Synthetic governed analysis fixture requires a raw frame.")
        synthetic_content_hash = hashlib.sha256(
            raw_frame.to_json(
                orient="split",
                date_format="iso",
                default_handler=str,
            ).encode("utf-8")
        ).hexdigest()
        activation_revision = int(store.meta.get("activation_revision") or 1)
        store.meta.update(
            {
                "project_id": self.project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "activation_revision": activation_revision,
                "target_contract_id": target_contract_id,
                "predictor_authorization_id": authorization_id,
                "predictor_authorization": authorization_payload,
                "predictor_authorization_manifest": authorization_payload,
                "selected_columns": predictors,
                "dataset_content_hash": synthetic_content_hash,
            }
        )
        # HTTP EDA handoff tests need the exact third durable Data Acquisition
        # prerequisite as well.  This synthetic fixture has no detected
        # special values, so its authoritative review is ``not_required``;
        # no decisions or governed production state are fabricated.
        detection = {
            "project_id": self.project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "predictor_authorization_id": authorization_id,
            "target_contract_id": target_contract_id,
            "target": target,
            "manual_declaration": "",
            "detected": False,
            "variables": [],
        }
        review_state = initial_review_state(detection)
        review_row = self.persistence.special_value_reviews.sync_detection(
            {
                "project_id": self.project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "activation_revision": activation_revision,
                "predictor_authorization_id": authorization_id,
                "target_contract_id": target_contract_id,
                "detection_fingerprint": detection_fingerprint(detection),
                "detection": detection,
                "actor_user_id": self.owner,
                **review_state,
            }
        )
        special_value_review = public_review_contract(review_row)
        store.meta.update(
            {
                "special_value_review": special_value_review,
                "special_value_review_id": special_value_review[
                    "special_value_review_id"
                ],
                "special_value_review_revision": special_value_review[
                    "revision"
                ],
            }
        )
        problem_type = (
            "regression"
            if str(stratification_policy).strip().lower() == "none"
            else "classification"
        )
        preview_request = AnalysisPartitionPreviewRequest(
            project_id=self.project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            target_contract_id=target_contract_id,
            target=target,
            positive_value=positive_value,
            negative_value=negative_value,
            predictor_authorization_id=authorization_id,
            problem_type=problem_type,
            development_share=development_share,
            holdout_share=1.0 - development_share,
            random_seed=random_seed,
            stratification_policy=stratification_policy,
            stratification_field=(
                target if stratification_policy == "target" else ""
            ),
        )
        preview = analysis_partition_service.preview(store, preview_request)[
            "preview"
        ]
        current = (
            self.persistence.analysis_partitions.get_current(self.project_id)
            if reset_existing
            else None
        )
        response = analysis_partition_service.confirm(
            store,
            AnalysisPartitionConfirmRequest(
                project_id=self.project_id,
                dataset_id=dataset_id,
                dataset_version_id=dataset_version_id,
                target_contract_id=target_contract_id,
                target=target,
                positive_value=positive_value,
                negative_value=negative_value,
                predictor_authorization_id=authorization_id,
                problem_type=problem_type,
                development_share=development_share,
                holdout_share=1.0 - development_share,
                random_seed=random_seed,
                stratification_policy=stratification_policy,
                stratification_field=(
                    target if stratification_policy == "target" else ""
                ),
                preview_fingerprint=preview["preview_fingerprint"],
                selection_rationale=(
                    "Synthetic test fixture accepts this governed split warning."
                    if preview.get("rationale_required")
                    else ""
                ),
                reset_existing=reset_existing,
                reset_reason=(
                    "Isolated test fixture explicitly replaced membership."
                    if reset_existing
                    else ""
                ),
                acknowledge_invalidation=reset_existing,
                expected_current_partition_id=(
                    str(current["analysis_partition_id"])
                    if current is not None
                    else ""
                ),
                expected_current_revision=(
                    int(current["revision"])
                    if current is not None
                    else None
                ),
            ),
            {"userId": self.owner},
        )
        with (
            patch.object(
                partition_router,
                "get_persistence_service",
                return_value=self.persistence,
            ),
            patch.object(partition_router, "audit_event"),
        ):
            evidence_ref = partition_router._record_partition_evidence(
                response, {"userId": self.owner}
            )
            mdd_ref = partition_router._record_partition_mdd(
                response, {"userId": self.owner}, evidence_ref
            )
        documentation_authority = (
            self.persistence.analysis_partitions.get_current(self.project_id)
        )
        assert documentation_authority is not None
        self.persistence.analysis_partitions.update_documentation_status(
            response["analysis_partition"]["analysis_partition_id"],
            expected_current=documentation_authority,
            evidence_status="recorded",
            evidence_ref=evidence_ref,
            mdd_status="recorded",
            mdd_ref=mdd_ref,
        )
        record = analysis_partition_service.current(
            self.project_id,
            dataset_id,
            dataset_version_id,
            target=target,
            target_contract_id=target_contract_id,
            predictor_authorization_id=authorization_id,
            require_documentation_ready=True,
        )
        X_dev, X_holdout, y_dev, y_holdout = (
            analysis_partition_service.materialize_validation(
                store,
                record,
                authorized_predictors=predictors,
            )
        )
        # Compatibility projection for tests that inspect old split fields.
        # Production EDA never reads these objects.
        store.set_splits(X_dev, X_holdout, y_dev, y_holdout)
        canonical_request = {
            "project_id": self.project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "activation_revision": activation_revision,
            "expected_dataset_id": dataset_id,
            "expected_dataset_version_id": dataset_version_id,
            "dataset_version": dataset_version_id,
            "target_contract_id": target_contract_id,
            "target": target,
            "positive_value": positive_value,
            "negative_value": negative_value,
            "event_value": positive_value,
            "non_event_value": negative_value,
            "problem_type": problem_type,
            "predictor_authorization_id": authorization_id,
            "analysis_partition_id": record["analysis_partition_id"],
            "analysis_partition_revision": int(record["revision"]),
            "special_value_review_id": special_value_review[
                "special_value_review_id"
            ],
            "special_value_review_revision": int(
                special_value_review["revision"]
            ),
        }
        return {
            **response,
            "record": record,
            "authorization": authorization_payload,
            "special_value_review": special_value_review,
            "canonical_request": canonical_request,
        }

    def close(self) -> None:
        self._persistence_patch.stop()
        analysis_partition_service._repository = self._previous_repository
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)
