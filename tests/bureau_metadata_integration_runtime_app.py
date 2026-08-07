"""Isolated production router host for dataset-version bureau metadata acceptance.

This subprocess-only module composes the production catalog, binding, crosswalk,
semantic-annotation, Evidence Center, and MDD implementations over authorities
that were pinned before import.  It has no live-project or live-service fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from fastapi import Depends, HTTPException, Request

from server.bureau_metadata import catalog_binding_router, crosswalk_router
from server.bureau_metadata.catalog_binding_router import router as binding_router
from server.bureau_metadata.crosswalk_router import router as crosswalk_router_api
from server.bureau_metadata.operational_service import get_operational_catalog_service
from server.persistence import service as persistence_service_module
from server.security.security_store import require_user
from tests.bureau_metadata_integrated_runtime_app import app
from tests.bureau_metadata_isolated_runtime_app import _synthetic_user, service
from tests.bureau_metadata_reverse_isolation_guard import (
    SyntheticReverseIsolationGuard,
)


_EVENT_FILE = "bureau-metadata-integration-events.jsonl"
_VIOLATION_FILE = "integrated-network-isolation-violation.jsonl"
_LOG_ROOT = Path(os.environ["ATLAS_ISOLATED_LOG_ROOT"]).resolve(strict=True)
_REVERSE_ISOLATION_GUARD = SyntheticReverseIsolationGuard(
    expected_run_id=os.environ["ATLAS_ISOLATED_ACCEPTANCE_RUN_ID"],
    frontend_origin=os.environ["ATLAS_ISOLATED_BUREAU_FRONTEND_ORIGIN"],
    violation_path=_LOG_ROOT / _VIOLATION_FILE,
)
_PROJECTS: Mapping[str, Mapping[str, Any]] = {
    "synthetic-project-alpha-001": {
        "principal": "synthetic-project-user-alpha",
        "dataset_id": "synthetic-dataset-alpha-001",
        "dataset_version_id": "synthetic-version-alpha-001",
        "authorized_predictors": ("SYN000", "SYN004"),
    },
    "synthetic-project-beta-002": {
        "principal": "synthetic-project-user-beta",
        "dataset_id": "synthetic-dataset-beta-002",
        "dataset_version_id": "synthetic-version-beta-002",
        "authorized_predictors": (
            "SYN000",
            "ALIAS_SCORE",
            "SYN004",
            "AMBIGUOUS_FIELD",
            "LOCAL_ONLY",
            "SYN005",
        ),
    },
    "synthetic-project-gamma-003": {
        "principal": "synthetic-project-user-gamma",
        "dataset_id": "synthetic-dataset-gamma-003",
        "dataset_version_id": "synthetic-version-gamma-003",
        "authorized_predictors": ("SYN000", "SYN004"),
    },
    "synthetic-project-delta-004": {
        "principal": "synthetic-project-user-delta",
        "dataset_id": "synthetic-dataset-delta-004",
        "dataset_version_id": "synthetic-version-delta-004",
        "authorized_predictors": ("LOCAL_A", "LOCAL_B"),
    },
    "synthetic-project-epsilon-005": {
        "principal": "synthetic-project-user-epsilon",
        "dataset_id": "synthetic-dataset-epsilon-005",
        "dataset_version_id": "synthetic-version-epsilon-005",
        "authorized_predictors": ("SYN000", "SYN004"),
    },
}


def _install_synthetic_crosswalk_candidate_fixture() -> None:
    """Add bounded alias/ambiguity evidence only for isolated Project B.

    The production foundation deliberately has no institutional-alias authority.
    Browser acceptance needs to exercise that governed state, so this synthetic
    subprocess decorates only the already-bounded candidate rows returned for
    Project B's exact principal.  It never changes a catalog definition.
    """

    original = service.catalogs.build_dataset_crosswalk_candidates_exact

    def candidates(
        context: Any,
        catalog_key: Any,
        catalog_checksum: str,
        fields: Any,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        payload = dict(
            original(
                context,
                catalog_key,
                catalog_checksum,
                fields,
                **kwargs,
            )
        )
        if str(getattr(context, "principal_id", "")) != "synthetic-project-user-beta":
            return payload
        rows = [dict(row) for row in tuple(payload.get("mappings") or ())]
        for row in rows:
            field = str(row.get("dataset_field") or "")
            if field == "ALIAS_SCORE":
                row.update(
                    {
                        "candidate_attribute_code": "SYN001",
                        "match_status": "approved_institutional_alias",
                        "confidence": 0.99,
                        "ambiguity": [],
                        "institutional_alias_reference": "synthetic-alias-policy-beta-v1",
                        "required_analyst_confirmation": True,
                    }
                )
            elif field == "AMBIGUOUS_FIELD":
                row.update(
                    {
                        "candidate_attribute_code": "SYN002",
                        "match_status": "multiple_possible_matches",
                        "confidence": 0.72,
                        "ambiguity": ["SYN002", "SYN003"],
                        "institutional_alias_reference": None,
                        "required_analyst_confirmation": True,
                    }
                )
        payload["mappings"] = rows
        checksum_payload = {key: value for key, value in payload.items() if key != "crosswalk_checksum"}
        payload["crosswalk_checksum"] = hashlib.sha256(
            json.dumps(
                checksum_payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return payload

    service.catalogs.build_dataset_crosswalk_candidates_exact = candidates  # type: ignore[method-assign]


_install_synthetic_crosswalk_candidate_fixture()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fixture(project_id: str) -> Mapping[str, Any]:
    try:
        return _PROJECTS[project_id]
    except KeyError as exc:
        raise PermissionError("Synthetic project access denied.") from exc


def _authorize_modeling_scope(
    user: Mapping[str, Any], project_id: str, permission: str
) -> str:
    fixture = _fixture(project_id)
    if (
        str(user.get("userId") or "") != fixture["principal"]
        or permission not in {"view", "edit"}
    ):
        raise PermissionError("Synthetic project access denied.")
    return project_id


def _active_identity(
    project_id: str, *, user: Mapping[str, Any], require_artifact: bool
) -> dict[str, Any]:
    if require_artifact is not True:
        raise RuntimeError("Synthetic exact artifact verification is required.")
    _authorize_modeling_scope(user, project_id, "view")
    fixture = _fixture(project_id)
    return {
        "project_id": project_id,
        "dataset_id": fixture["dataset_id"],
        "dataset_version_id": fixture["dataset_version_id"],
        "activation_revision": 1,
        "dataset_schema_hash": _schema_checksum(project_id),
    }


def _schema_checksum(project_id: str) -> str:
    import hashlib

    fixture = _fixture(project_id)
    payload = json.dumps(
        {"project_id": project_id, "fields": list(fixture["authorized_predictors"])},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _SyntheticPredictorAuthorizations:
    def get_current_exact(
        self,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        target_contract_id: str | None = None,
    ) -> dict[str, Any]:
        fixture = _fixture(project_id)
        if (dataset_id, dataset_version_id) != (
            fixture["dataset_id"],
            fixture["dataset_version_id"],
        ):
            raise RuntimeError("Synthetic predictor authorization identity mismatch.")
        expected_target_contract = f"synthetic-target-contract-{project_id}"
        if target_contract_id is not None and target_contract_id != expected_target_contract:
            raise RuntimeError("Synthetic target contract identity mismatch.")
        return {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "authorized_predictors": list(fixture["authorized_predictors"]),
            "target": "synthetic_outcome",
            "target_source_excluded": ["synthetic_outcome"],
        }


_PREDICTORS = _SyntheticPredictorAuthorizations()


class _SyntheticDatasets:
    def get_version(self, dataset_version_id: str) -> dict[str, Any] | None:
        for project_id, fixture in _PROJECTS.items():
            if fixture["dataset_version_id"] != dataset_version_id:
                continue
            columns = []
            for field in fixture["authorized_predictors"]:
                contradictory = (
                    project_id == "synthetic-project-beta-002"
                    and field == "SYN000"
                )
                columns.append(
                    {
                        "name": field,
                        "data_type": "string" if contradictory else "integer",
                        "dtype": "string" if contradictory else "int64",
                        "min": -20 if contradictory else 0,
                        "max": 1_200 if contradictory else 101,
                    }
                )
            return {
                "project_id": project_id,
                "dataset_id": fixture["dataset_id"],
                "dataset_version_id": dataset_version_id,
                "schema_json": {"columns": columns},
                "profile_json": {"schema": columns},
            }
        return None


class _SyntheticSpecialValueReviews:
    def get_exact(
        self, project_id: str, dataset_id: str, dataset_version_id: str
    ) -> dict[str, Any]:
        fixture = _fixture(project_id)
        if (dataset_id, dataset_version_id) != (
            fixture["dataset_id"],
            fixture["dataset_version_id"],
        ):
            raise RuntimeError("Synthetic special-value identity mismatch.")
        variables = []
        for field in fixture["authorized_predictors"]:
            contradictory = (
                project_id == "synthetic-project-beta-002" and field == "SYN000"
            )
            variables.append(
                {
                    "variable": field,
                    "datatype": "string" if contradictory else "int64",
                    "special_values": [
                        {
                            "value": -20 if contradictory else 901,
                            "count": 12,
                        }
                    ],
                }
            )
        return {
            "activation_revision": 1,
            "predictor_authorization_id": (
                f"synthetic-predictor-authorization-{project_id}"
            ),
            "target_contract_id": f"synthetic-target-contract-{project_id}",
            "detection_json": {
                "structural_scope": "full_governed_population_predictors_only",
                "final_holdout_accessed": False,
                "variables": variables,
            },
        }


_DATASETS = _SyntheticDatasets()
_SPECIAL_VALUE_REVIEWS = _SyntheticSpecialValueReviews()


def _persistence_facade() -> Any:
    return SimpleNamespace(
        predictor_authorizations=_PREDICTORS,
        datasets=_DATASETS,
        special_value_reviews=_SPECIAL_VALUE_REVIEWS,
    )


def _verify_predictors(
    record: Mapping[str, Any], *, project_id: str, dataset_id: str, dataset_version_id: str
) -> dict[str, Any]:
    fixture = _fixture(project_id)
    if (
        record.get("project_id") != project_id
        or record.get("dataset_id") != dataset_id
        or record.get("dataset_version_id") != dataset_version_id
    ):
        raise RuntimeError("Synthetic predictor authorization verification failed.")
    return {
        **dict(record),
        "target_contract_id": f"synthetic-target-contract-{project_id}",
        "predictor_authorization_id": f"synthetic-predictor-authorization-{project_id}",
        "excluded_predictors": {"synthetic_outcome": "target"},
    }


class _BoundedProjectionRepository:
    def __init__(self, root: Path, id_field: str) -> None:
        self.root = root.resolve(strict=True)
        self.id_field = id_field

    def upsert(self, record: Mapping[str, Any]) -> dict[str, Any]:
        identity = str(record.get(self.id_field) or "").strip()
        if not identity or len(identity) > 256:
            raise ValueError("Synthetic documentation projection identity is invalid.")
        import hashlib

        destination = self.root / (
            self.id_field.replace("_", "-")
            + "-"
            + hashlib.sha256(identity.encode("utf-8")).hexdigest()
            + ".json"
        )
        encoded = json.dumps(dict(record), sort_keys=True, separators=(",", ":")).encode("utf-8")
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, destination)
        return dict(record)

    def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        """Return only bounded synthetic projections for one exact project."""

        exact_project = str(project_id or "").strip()
        if exact_project not in _PROJECTS:
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(self.root.glob(f"{self.id_field.replace('_', '-')}-*.json")):
            if len(records) >= 100:
                raise RuntimeError("Synthetic projection inventory exceeded its bound.")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping) and payload.get("project_id") == exact_project:
                records.append(dict(payload))
        return records


class _SyntheticProjects:
    def get(self, project_id: str) -> dict[str, Any] | None:
        fixture = _PROJECTS.get(project_id)
        if fixture is None:
            return None
        return {
            "project_id": project_id,
            "owner_user_id": fixture["principal"],
            "classification": "synthetic_isolated_acceptance",
        }


_DOCUMENTATION_PERSISTENCE = SimpleNamespace(
    projects=_SyntheticProjects(),
    evidence=_BoundedProjectionRepository(
        Path(os.environ["ATLAS_EVIDENCE_ROOT"]), "evidence_id"
    ),
    documentation=_BoundedProjectionRepository(
        Path(os.environ["ATLAS_ISOLATED_DOCUMENTATION_REGISTRY_ROOT"]),
        "package_id",
    ),
)


# Patch only authorities imported by the production router adapters.  The
# durable binding/crosswalk repositories and documentation persistence remain
# the production SQLite implementations under isolated pre-import roots.
catalog_binding_router.authorize_modeling_scope = _authorize_modeling_scope
catalog_binding_router.durable_active_dataset_identity = _active_identity
catalog_binding_router.get_persistence_service = _persistence_facade
catalog_binding_router.verify_durable_predictor_authorization = _verify_predictors
crosswalk_router.get_persistence_service = _persistence_facade
crosswalk_router.verify_durable_predictor_authorization = _verify_predictors
persistence_service_module.get_persistence_service = lambda: _DOCUMENTATION_PERSISTENCE

app.dependency_overrides[require_user] = _synthetic_user
app.dependency_overrides[get_operational_catalog_service] = lambda: service
app.include_router(binding_router, prefix="/api")
app.include_router(crosswalk_router_api, prefix="/api")


def _event_category(path: str, method: str, status: int) -> str:
    if path.endswith("/binding/preview"):
        return "binding_preview"
    if path.endswith("/crosswalk/preview"):
        return "crosswalk_preview"
    if path.endswith("/crosswalk/decisions"):
        return "decision_write"
    if path.endswith("/crosswalk/binding-link"):
        return "binding_link_retry"
    if path.endswith("/bureau-metadata/annotations") or path.endswith("/semantic-annotations"):
        return "semantic_batch"
    if "/attributes" in path and method == "GET":
        return "catalog_search_or_lookup"
    if path.endswith("/revoke"):
        return "entitlement_revoke"
    if status == 409:
        return "conflict"
    if status in {400, 422}:
        return "malformed"
    return "other"


@app.middleware("http")
async def record_integration_event(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        row = {
            "schema_version": "1.0",
            "classification": "synthetic_bureau_metadata_integration_event",
            "occurred_at": _utc_now(),
            "method": request.method[:8],
            "category": _event_category(
                request.url.path, request.method, int(response.status_code)
            ),
            "status": int(response.status_code),
            "reverse_isolation_guard_verified": True,
        }
        with (_LOG_ROOT / _EVENT_FILE).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return response


@app.middleware("http")
async def enforce_reverse_integration_isolation(request: Request, call_next):
    return await _REVERSE_ISOLATION_GUARD.middleware(request, call_next)


_BROWSER_SPECIAL_VALUE_REVIEWS: dict[str, dict[str, Any]] = {}


def _browser_detection_variables(project_id: str) -> list[dict[str, Any]]:
    fixture = _fixture(project_id)
    variables: list[dict[str, Any]] = []
    for index, field in enumerate(fixture["authorized_predictors"]):
        contradictory = project_id == "synthetic-project-beta-002" and field == "SYN000"
        value = -20 if contradictory else 901
        count = 24 + index
        variables.append(
            {
                "variable": field,
                "confidence": 0.97,
                "reasons": ["Synthetic isolated structural acceptance evidence"],
                "datatype": "string" if contradictory else "int64",
                "special_value_count": count,
                "special_value_frequency": count / 1_000,
                "ordinary_value_count": 1_000 - count,
                "null_count": 0,
                "parse_failure_count": 0,
                "likely_bureau": True,
                "special_values": [
                    {
                        "value": value,
                        "definition": (
                            "Observed value outside the provider datatype and ordinary range"
                            if contradictory
                            else "Synthetic observed special code"
                        ),
                        "count": count,
                        "frequency": count / 1_000,
                        "event_count": None,
                        "event_rate": None,
                        "regular_event_rate": None,
                        "event_rate_delta": None,
                        "recommended_handling": "preserve_informative",
                    }
                ],
            }
        )
    return variables


def _browser_special_value_review(
    project_id: str,
    variables: list[dict[str, Any]],
) -> dict[str, Any]:
    fixture = _fixture(project_id)
    fingerprint = hashlib.sha256(
        json.dumps(
            {"project_id": project_id, "variables": variables},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "special_value_review_id": f"synthetic-special-review-{project_id}",
        "project_id": project_id,
        "dataset_id": fixture["dataset_id"],
        "dataset_version_id": fixture["dataset_version_id"],
        "activation_revision": 1,
        "predictor_authorization_id": f"synthetic-predictor-authorization-{project_id}",
        "target_contract_id": f"synthetic-target-contract-{project_id}",
        "analysis_partition_id": None,
        "analysis_partition_revision": None,
        "development_partition_id": None,
        "analysis_partition_assignment_hash": None,
        "analysis_partition_artifact_hash": None,
        "development_target_checksum": None,
        "source_checksum": fingerprint,
        "structural_scope": "full_governed_population_predictors_only",
        "target_analysis_scope": "not_available",
        "target_evidence_available": False,
        "target_evidence_status": "unavailable",
        "target_evidence_unavailable_reason": (
            "Synthetic browser acceptance does not perform target-directed analysis."
        ),
        "full_governed_population_rows": 1_000,
        "development_rows": 0,
        "detection_fingerprint": fingerprint,
        "status": "not_started",
        "detected_count": len(variables),
        "reviewed_count": 0,
        "open_count": len(variables),
        "open_items": [str(item["variable"]) for item in variables],
        "blocks_confirmation": True,
        "blocks_continuation": True,
        "confirmation_allowed": False,
        "revision": 1,
        "variable_decisions": [],
        "reviewer_rationale": "",
        "confirmed_at": None,
        "updated_at": _utc_now(),
        "authority": "backend_durable_exact_version",
        "browser_cache_authority": False,
    }


def _validate_browser_review_scope(
    *,
    user: Mapping[str, Any],
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
) -> Mapping[str, Any]:
    try:
        _authorize_modeling_scope(user, project_id, "view")
        fixture = _fixture(project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Project access denied.") from exc
    if (dataset_id, dataset_version_id) != (
        fixture["dataset_id"],
        fixture["dataset_version_id"],
    ):
        raise HTTPException(status_code=409, detail="Exact dataset identity is contradictory.")
    return fixture


@app.post("/api/data/bureau-detection")
async def synthetic_bureau_detection(
    request: Request,
    user: Mapping[str, Any] = Depends(_synthetic_user),
) -> Mapping[str, Any]:
    body = await request.json()
    if not isinstance(body, Mapping):
        raise HTTPException(status_code=422, detail="Synthetic detection input is invalid.")
    project_id = str(body.get("project_id") or "")
    dataset_id = str(body.get("expected_dataset_id") or "")
    dataset_version_id = str(body.get("expected_dataset_version_id") or "")
    _validate_browser_review_scope(
        user=user,
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
    )
    variables = _browser_detection_variables(project_id)
    review = _browser_special_value_review(project_id, variables)
    _BROWSER_SPECIAL_VALUE_REVIEWS[project_id] = review
    return {
        "ok": True,
        "scope": "full_dataset",
        "analysis_scope": "mixed_governed_scopes",
        "structural_scope": "full_governed_population_predictors_only",
        "row_count": 1_000,
        "full_governed_population_rows": 1_000,
        "target": str(body.get("target") or "synthetic_outcome"),
        "event_value": body.get("event_value"),
        "detected": True,
        "confidence": 0.97,
        "manual_declaration": str(body.get("manual_declaration") or "auto"),
        "reasons": ["Synthetic isolated structural acceptance evidence"],
        "likely_variable_count": len(variables),
        "variables_with_special_values": len(variables),
        "rows_with_special_values": sum(int(item["special_value_count"]) for item in variables),
        "variables": variables,
        "metadata_source": "synthetic_isolated_backend_authority",
        "reviewed_at": _utc_now(),
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "activation_revision": 1,
        "predictor_authorization_id": review["predictor_authorization_id"],
        "target_contract_id": review["target_contract_id"],
        "correlation_id": f"synthetic-detection-{project_id}",
        "target_analysis_scope": "not_available",
        "analysis_partition_id": None,
        "analysis_partition_revision": None,
        "development_partition_id": None,
        "analysis_partition_assignment_hash": None,
        "analysis_partition_artifact_hash": None,
        "development_target_checksum": None,
        "scope_contract": {
            "structural_evidence": "full_governed_population_predictors_only",
            "target_evidence": "not_available",
            "single_scope_inference_allowed": False,
        },
        "structural_evidence": {
            "scope": "full_governed_population_predictors_only",
            "population_count": 1_000,
            "target_accessed": False,
            "measures": ["special_value_count", "special_value_frequency"],
        },
        "target_evidence": {
            "available": False,
            "status": "unavailable",
            "scope": "not_available",
            "population_id": None,
            "population_count": 0,
            "analysis_partition_id": None,
            "analysis_partition_revision": None,
            "assignment_hash": None,
            "artifact_hash": None,
            "source_checksum": None,
            "development_target_checksum": None,
            "holdout_excluded": True,
            "final_holdout_accessed": False,
            "measures": [],
        },
        "final_holdout_accessed": False,
        "special_value_review": review,
    }


@app.get("/api/data/special-value-review")
def synthetic_special_value_review(
    project_id: str,
    expected_dataset_id: str,
    expected_dataset_version_id: str,
    user: Mapping[str, Any] = Depends(_synthetic_user),
) -> Mapping[str, Any]:
    _validate_browser_review_scope(
        user=user,
        project_id=project_id,
        dataset_id=expected_dataset_id,
        dataset_version_id=expected_dataset_version_id,
    )
    review = _BROWSER_SPECIAL_VALUE_REVIEWS.get(project_id)
    if review is None:
        raise HTTPException(
            status_code=404,
            detail="The exact synthetic special-value review is not initialized.",
        )
    return {"ok": True, "special_value_review": review}


@app.get("/api/isolated/integration-projects")
def integration_projects(
    user: Mapping[str, Any] = Depends(_synthetic_user),
) -> Mapping[str, Any]:
    principal = str(user.get("userId") or "")
    visible = [
        {
            "project_id": project_id,
            "dataset_id": fixture["dataset_id"],
            "dataset_version_id": fixture["dataset_version_id"],
        }
        for project_id, fixture in _PROJECTS.items()
        if fixture["principal"] == principal
    ]
    return {"ok": True, "projects": visible}


@app.get("/api/isolated/runtime-metrics")
def runtime_metrics() -> Mapping[str, Any]:
    try:
        import psutil  # type: ignore[import-not-found]

        process = psutil.Process(os.getpid())
        handles = process.num_handles() if hasattr(process, "num_handles") else None
        return {
            "ok": True,
            "rss_bytes": int(process.memory_info().rss),
            "handles": int(handles) if handles is not None else None,
            "available": True,
            "reverse_isolation_guard": _REVERSE_ISOLATION_GUARD.metrics(),
        }
    except Exception:
        return {
            "ok": True,
            "rss_bytes": None,
            "handles": None,
            "available": False,
            "reverse_isolation_guard": _REVERSE_ISOLATION_GUARD.metrics(),
        }


@app.get(
    "/api/isolated/canonical-eda-handoff/{project_id}/{dataset_id}/{dataset_version_id}"
)
def canonical_eda_handoff(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    user: Mapping[str, Any] = Depends(_synthetic_user),
) -> Mapping[str, Any]:
    _authorize_modeling_scope(user, project_id, "view")
    payload = crosswalk_router.resolve_exact_semantic_handoff_for_user(
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        user=user,
        operational=service,
    )
    return {
        "ok": True,
        "classification": "synthetic_canonical_da_to_eda_handoff",
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "bureau_semantic_annotations": payload,
        "development_only": True,
        "final_holdout_accessed": False,
        "training_started": False,
    }


@app.get("/api/isolated/project-integration-identity/{project_id}")
def project_integration_identity(
    project_id: str,
    user: Mapping[str, Any] = Depends(_synthetic_user),
) -> Mapping[str, Any]:
    try:
        _authorize_modeling_scope(user, project_id, "view")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Project access denied.") from exc
    fixture = _fixture(project_id)
    return {
        "ok": True,
        "project_id": project_id,
        "dataset_id": fixture["dataset_id"],
        "dataset_version_id": fixture["dataset_version_id"],
        "activation_revision": 1,
    }
