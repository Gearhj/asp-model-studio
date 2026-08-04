# server/main.py
# =============================================================================
# ATLAS Backend (Modular, Package-Aware)
# =============================================================================

from __future__ import annotations

from typing import Dict, Any, List
import io
import logging
import os

import pandas as pd
from fastapi import Depends, FastAPI, Form, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

# Core in-memory store
from .core.dataset_store import DATASTORE
from .core.modeling_scope import authorize_modeling_scope
from .core.pretraining_invalidation import invalidate_downstream_training_state
from .core.result_store import RESULTS
from .core.session_checkpoint import load_checkpoint, schedule_checkpoint_save, shutdown_checkpoint_writer

# Modular routers
from .core.metadata_router import _infer_target, router as metadata_router
from .core.utils import df_to_records
from .eda.eda_router import router as eda_router
from .analysis_partition.router import router as analysis_partition_router
from .preprocessing.outlier_router import router as outlier_router
from .preprocessing.missing_router import router as missing_router
from .preprocessing.preparation_documentation_router import router as preparation_documentation_router
from .preprocessing.quality_profile_router import router as quality_profile_router
from .preprocessing.feature_profile_router import router as feature_profile_router
from .preprocessing.governed_profile_router import router as governed_profile_router
from .preprocessing.bureau_detection_router import router as bureau_detection_router
from .splitting.split_router import router as split_router
from .training.trainer_router import router as trainer_router
from .features.feature_router import router as feature_router
from .evaluation.eval_router import router as eval_router
from .python_execution import router as python_execution_router
from .datasets.dataset_router import router as dataset_library_router
from .datasets.dataset_integrity import run_bounded_integrity_scan
from .datasets.dataset_integrity_router import router as dataset_integrity_router
from .datasets.dataset_registry import create_dataset_from_dataframe, link_project
from .datasets.dataset_identity import (
    invalidate_dataset_identity,
    resolve_registered_version,
    stamp_active_dataset_identity,
)
from .security.security_router import router as security_router
from .admin.router import router as admin_router
from .sharing.router import router as sharing_router
from .notifications.router import router as notifications_router
from .security.security_store import (
    ATLAS_CORS_ORIGINS,
    ATLAS_HOSTED_MODE,
    ActiveUserContextMiddleware,
    AtlasUserContextError,
    init_security_store,
    list_users,
    require_user,
    validate_security_configuration,
)
from .analytics.analytics_router import router as analytics_router
from .analytics.analytics_queries_router import router as analytics_queries_router
from .analytics.target_intelligence_router import router as target_intelligence_router
from .charts.chart_router import router as chart_router
from .model_diagnostics.diagnostics_router import router as model_diagnostics_router
from .model_documentation.documentation_router import router as model_documentation_router
from .notebooks.notebook_router import router as notebook_router
from .scoring.scoring_router import router as scoring_router
from .scoring_runs.scoring_runs_router import router as scoring_runs_router
from .model_registry.model_registry_router import router as model_registry_router
from .projects.project_router import router as project_registry_router
from .sql_studio.sql_router import router as sql_studio_router
from .evidence.evidence_router import router as evidence_router
from .credit_risk.credit_risk_router import router as credit_risk_router
from .experimentation.ab_router import router as experimentation_router
from .experimental_design.router import router as experimental_design_router
from .optimization.optimization_router import router as optimization_router
from .persistence import get_persistence_service, initialize_persistence
from .persistence.persistence_router import router as persistence_router
from .persistence.repositories.project_dataset_activation_repository import (
    project_dataset_activation_lock,
)
from .registry.router import router as registry_router
from .validation.router import router as validation_router
from .monitoring.router import router as monitoring_router
from .analytics_engine.router import router as analytics_engine_router

MAX_UPLOAD_BYTES = int(os.getenv("ATLAS_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024)))
MAX_UPLOAD_ROWS = int(os.getenv("ATLAS_MAX_UPLOAD_ROWS", "500000"))
MAX_UPLOAD_COLUMNS = int(os.getenv("ATLAS_MAX_UPLOAD_COLUMNS", "750"))
MAX_UPLOAD_SAMPLE_ROWS = int(os.getenv("ATLAS_MAX_UPLOAD_SAMPLE_ROWS", "5000"))
ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".txt", ".json"}
LOGGER = logging.getLogger("atlas.data_upload")
PUBLIC_API_PATHS = {
    "/api/health",
    "/api/persistence/health",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/request-password-reset",
    "/api/auth/reset-password",
}


def _has_require_user_dependency(route: APIRoute) -> bool:
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        if dependency.call is require_user:
            return True
        pending.extend(dependency.dependencies)
    return False


def assert_api_routes_authenticated(app: FastAPI) -> None:
    unsecured = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not path.startswith("/api/") or path in PUBLIC_API_PATHS:
            continue
        if not _has_require_user_dependency(route):
            unsecured.append(path)
    if unsecured:
        raise RuntimeError(f"Unauthenticated API routes are not allowed: {', '.join(sorted(set(unsecured)))}")


def create_app() -> FastAPI:
    """
    Application factory for the ATLAS backend.

    Keeps main.py thin:
      - CORS + app creation
      - healthcheck
      - CSV upload endpoint
      - router wiring
    """
    app = FastAPI(
        title="ATLAS API",
        version="0.1.0",
        description="Backend API for ATLAS regulated AI/ML model development.",
    )

    @app.exception_handler(AtlasUserContextError)
    async def atlas_user_context_error(_request: Request, exc: AtlasUserContextError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    # -------------------------------------------------------------------------
    # CORS – support local Vite dev + fall back to permissive for now
    # -------------------------------------------------------------------------
    local_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    origins = list(ATLAS_CORS_ORIGINS) if ATLAS_HOSTED_MODE else [*local_origins, *ATLAS_CORS_ORIGINS]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Restores ACTIVE_USER propagation into route handler bodies and their
    # dependencies (Depends(require_user) alone cannot do this -- see
    # ActiveUserContextMiddleware's docstring). Required for DATASTORE/
    # RESULTS's per-user scoping to work at all during real requests.
    app.add_middleware(ActiveUserContextMiddleware)

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {"ok": True, "status": "running"}

    @app.on_event("startup")
    def restore_session_checkpoint() -> None:
        summary = validate_security_configuration()
        if summary["warnings"]:
            print("ATLAS local security settings: " + "; ".join(summary["warnings"]))
        init_security_store()
        security_users = list_users()
        # Persistence initialization is a startup authority.  A failed schema
        # migration must stop startup instead of serving requests against a
        # partially upgraded database or a legacy fallback.
        initialize_persistence()
        service = get_persistence_service()
        persistence_database = service.database
        for security_user in security_users:
            service.sync_user(security_user)
        try:
            known_users = {
                str(security_user.get("userId") or ""): security_user
                for security_user in security_users
                if security_user.get("userId")
            }
            integrity = run_bounded_integrity_scan(
                database=persistence_database,
                user_resolver=known_users.get,
            )
            app.state.dataset_library_integrity = integrity
            LOGGER.info(
                "Dataset Library startup integrity scan completed: status=%s records=%s",
                integrity["status"],
                integrity["reconciliation"]["record_count"],
            )
        except Exception as exc:  # pragma: no cover - startup must remain available
            app.state.dataset_library_integrity = {
                "status": "scan_failed",
                "error_type": type(exc).__name__,
                "automatic_recovery_performed": False,
            }
            LOGGER.error(
                "Dataset Library startup integrity scan failed safely: %s",
                type(exc).__name__,
            )
        load_checkpoint()

    @app.on_event("shutdown")
    def flush_session_checkpoint() -> None:
        # Stage 6.1: scheduled (debounced) checkpoint saves may still be
        # pending when the process stops; flush them so the most recent
        # draft mutations survive an ordinary shutdown.
        shutdown_checkpoint_writer()

    # -------------------------------------------------------------------------
    # Data Acquisition – optional CSV upload endpoint (Step01 alternative)
    # -------------------------------------------------------------------------
    @app.post("/api/data/upload_csv")
    async def upload_csv(
        file: UploadFile = File(...),
        project_id: str = Form(...),
        user: Dict[str, Any] = Depends(require_user),
    ) -> Dict[str, Any]:
        """
        Upload a CSV file and store it as the RAW dataset in DATASTORE.

        NOTE: Your current Step01_DataAcquisition.tsx uses /api/data/set_sample
        with JSON rows. This endpoint is kept for compatibility / future use.
        """
        authorize_modeling_scope(user, project_id, "edit")
        filename = file.filename or ""
        extension = os.path.splitext(filename)[1].lower()
        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Only CSV, TXT, or JSON uploads are accepted by this endpoint.")

        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Upload is too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            )

        try:
            df = (
                pd.read_json(io.BytesIO(content))
                if extension == ".json"
                else pd.read_csv(io.BytesIO(content))
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read CSV: {exc}")

        if df.empty:
            raise HTTPException(status_code=400, detail="Uploaded CSV has no rows.")
        if int(df.shape[0]) > MAX_UPLOAD_ROWS:
            raise HTTPException(status_code=413, detail=f"Uploaded CSV has too many rows. Maximum is {MAX_UPLOAD_ROWS:,}.")
        if int(df.shape[1]) > MAX_UPLOAD_COLUMNS:
            raise HTTPException(status_code=413, detail=f"Uploaded CSV has too many columns. Maximum is {MAX_UPLOAD_COLUMNS:,}.")

        # Phase 2A: a new upload becomes an immutable registered version before
        # it can enter governed modeling state. No browser-generated identifier
        # is accepted as a substitute for this backend identity.
        dataset = create_dataset_from_dataframe(
            df,
            name=os.path.splitext(os.path.basename(filename))[0] or "Uploaded Dataset",
            description="Registered automatically from Data Acquisition upload.",
            domain="Predictive Modeling",
            source_type="data_acquisition_upload",
            source_info={"projectId": project_id, "originalFilename": filename},
            dataset_role="development",
        )
        dataset_id = str(dataset.get("datasetId") or "")
        dataset_version_id = str(
            dataset.get("created_dataset_version_id")
            or dataset.get("createdDatasetVersionId")
            or ""
        )
        if not dataset_id or not dataset_version_id:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Dataset registration did not return the exact immutable "
                    "version created by this upload."
                ),
            )
        resolved = resolve_registered_version(
            dataset_id,
            dataset_version_id,
            user=user,
        )
        actor_user_id = str(user.get("userId") or "").strip()
        if not actor_user_id:
            raise HTTPException(
                status_code=401,
                detail="An authenticated user is required for dataset activation.",
            )
        scoped_store = DATASTORE.current()
        scoped_results = RESULTS.current()
        activation_guard = project_dataset_activation_lock(project_id)
        activation_guard.acquire()
        try:
            activation = get_persistence_service().project_dataset_activations.activate_exact(
                project_id=project_id,
                dataset_id=dataset_id,
                dataset_version_id=dataset_version_id,
                actor_user_id=actor_user_id,
                metadata={
                    "datasetRole": "development",
                    "requestedDatasetVersionId": dataset_version_id,
                    "source": "data_acquisition_upload",
                },
            )
        except BaseException:
            activation_guard.release()
            raise
        active_selection = activation.get("active_selection") or {}
        identity = {
            **resolved,
            "project_id": project_id,
            "project_link": activation.get("link") or {},
            "active_selection": active_selection,
            "activation_revision": int(active_selection.get("activation_revision") or 0),
        }
        with scoped_store.state_lock:
            try:
                scoped_store.set_raw(df)
                target = _infer_target(df)
                scoped_store.set_target(target)
                columns = [str(c) for c in df.columns]
                selected_columns = [col for col in columns if col != target]
                scoped_store.meta["selected_columns"] = selected_columns
                canonical = stamp_active_dataset_identity(
                    identity,
                    store=scoped_store,
                )
                scoped_store.meta["activation_revision"] = identity["activation_revision"]
                scoped_store.meta["source"] = {
                    "kind": "dataset_library",
                    "dataset_id": canonical["dataset_id"],
                    "dataset_version_id": canonical["dataset_version_id"],
                    "datasetId": canonical["dataset_id"],
                    "versionId": canonical["dataset_version_id"],
                    "filename": filename,
                    "rows": int(df.shape[0]),
                    "columns": int(df.shape[1]),
                    "target": target,
                    "selected_columns": selected_columns,
                }
                invalidate_downstream_training_state(
                    "A newly uploaded exact Dataset Library version was activated.",
                    store=scoped_store,
                    result_store=scoped_results,
                    split_status="not_created",
                    # set_raw already advanced the guarded revision.
                    bump_revision=False,
                )
            except Exception as exc:
                try:
                    get_persistence_service().project_dataset_activations.record_contradiction(
                        project_id=project_id,
                        actor_user_id=actor_user_id,
                        reason="Runtime workspace hydration failed after durable upload activation.",
                        metadata={"operation": "upload_csv"},
                    )
                except Exception as contradiction_exc:  # pragma: no cover - diagnostic best effort
                    LOGGER.error(
                        "Unable to persist upload activation contradiction for project=%s: %s",
                        project_id,
                        contradiction_exc,
                    )
                invalidate_dataset_identity(
                    "The durable uploaded dataset selection could not be hydrated into the workspace.",
                    store=scoped_store,
                    clear_frames=True,
                )
                activation_guard.release()
                raise HTTPException(
                    status_code=500,
                    detail="The uploaded dataset was registered but its exact version was not activated because workspace hydration failed.",
                ) from exc
        activation_guard.release()
        try:
            link_project(project_id, dataset_id, dataset_version_id, "development")
        except Exception as exc:  # pragma: no cover - legacy projection is best effort
            LOGGER.warning(
                "Durable upload activation succeeded but legacy link projection failed "
                "for project=%s dataset=%s version=%s: %s",
                project_id,
                dataset_id,
                dataset_version_id,
                exc,
            )
        schedule_checkpoint_save()
        sample_df = df.head(max(1, min(MAX_UPLOAD_SAMPLE_ROWS, int(df.shape[0]))))

        return {
            "ok": True,
            "source": "backend_csv_import",
            "filename": filename,
            "project_id": canonical["project_id"],
            "dataset_id": canonical["dataset_id"],
            "dataset_version_id": canonical["dataset_version_id"],
            "created_dataset_version_id": dataset_version_id,
            "created_version": dataset.get("created_version"),
            "datasetId": canonical["dataset_id"],
            "versionId": canonical["dataset_version_id"],
            "rows": int(df.shape[0]),
            "rows_loaded": int(df.shape[0]),
            "row_count": int(df.shape[0]),
            "cols": int(df.shape[1]),
            "columns": columns,
            "headers": columns,
            "target": target,
            "selected_columns": selected_columns,
            "sample_rows": df_to_records(sample_df),
            "sample_row_count": int(sample_df.shape[0]),
            "max_upload_mb": int(MAX_UPLOAD_BYTES // (1024 * 1024)),
            "activation_revision": int(active_selection.get("activation_revision") or 0),
            "link": activation.get("link") or {},
            "active_selection": active_selection,
        }

    # -------------------------------------------------------------------------
    # Router registration
    # -------------------------------------------------------------------------
    # These provide:
    #   • /api/columns, /api/data/get_sample, /api/data/set_sample  – Metadata
    #   • /api/eda/*             – EDA endpoints
    #   • /api/outliers/*        – Outlier summary (Step03)
    #   • /api/balancing_split/* – Dev split & balancing (Step06)
    #   • /api/model/train       – Training (Step07)
    #   • /api/train/last        – Last training summary (Step07/08)
    #   • /api/evaluation/*      – ROC, PR, Deciles (Step08)
    authenticated = [Depends(require_user)]
    app.include_router(metadata_router, prefix="/api", tags=["Metadata"], dependencies=authenticated)
    app.include_router(
        analysis_partition_router,
        prefix="/api/analysis-partitions",
        tags=["Analysis Partition"],
        dependencies=authenticated,
    )
    app.include_router(eda_router, prefix="/api/eda", tags=["EDA"], dependencies=authenticated)
    app.include_router(outlier_router, prefix="/api/outliers", tags=["Outliers"], dependencies=authenticated)
    app.include_router(missing_router, prefix="/api/missing", tags=["Missing Values"], dependencies=authenticated)
    app.include_router(preparation_documentation_router, prefix="/api", tags=["Preparation Documentation"], dependencies=authenticated)
    app.include_router(quality_profile_router, prefix="/api", tags=["Data Quality"], dependencies=authenticated)
    app.include_router(feature_profile_router, prefix="/api", tags=["Feature Profiling"], dependencies=authenticated)
    app.include_router(governed_profile_router, prefix="/api", tags=["Governed Target Profiling"], dependencies=authenticated)
    app.include_router(bureau_detection_router, prefix="/api", tags=["Bureau Detection"], dependencies=authenticated)
    app.include_router(split_router, prefix="/api/balancing_split", tags=["Splitting & Balancing"], dependencies=authenticated)
    app.include_router(trainer_router, prefix="/api", tags=["Training"], dependencies=authenticated)
    app.include_router(feature_router, prefix="/api", tags=["Feature Engineering"], dependencies=authenticated)
    app.include_router(eval_router, prefix="/api", tags=["Evaluation"], dependencies=authenticated)
    app.include_router(python_execution_router, prefix="/api", tags=["Python Execution"], dependencies=authenticated)
    app.include_router(admin_router, prefix="/api", tags=["Admin"])
    app.include_router(sharing_router, prefix="/api", tags=["Sharing"])
    app.include_router(notifications_router, prefix="/api", tags=["Notifications"])
    app.include_router(security_router, prefix="/api", tags=["Security"])
    app.include_router(dataset_library_router, prefix="/api", tags=["Dataset Library"], dependencies=authenticated)
    app.include_router(dataset_integrity_router, prefix="/api", tags=["Dataset Library Integrity"], dependencies=authenticated)
    app.include_router(project_registry_router, prefix="/api", tags=["Project Registry"], dependencies=authenticated)
    app.include_router(persistence_router, prefix="/api", tags=["Persistence"])
    app.include_router(registry_router, prefix="/api", tags=["Registry"], dependencies=authenticated)
    app.include_router(validation_router, prefix="/api", tags=["Validation"], dependencies=authenticated)
    app.include_router(monitoring_router, tags=["Monitoring"], dependencies=authenticated)
    app.include_router(analytics_engine_router, tags=["Statistical & Analytical Engine"])
    app.include_router(analytics_router, prefix="/api", tags=["Analytics Workbench"], dependencies=authenticated)
    app.include_router(analytics_queries_router, prefix="/api", tags=["Enterprise Analytical Data Plane"], dependencies=authenticated)
    app.include_router(target_intelligence_router, prefix="/api", tags=["EDA Target Intelligence"], dependencies=authenticated)
    app.include_router(chart_router, prefix="/api", tags=["Chart Studio"], dependencies=authenticated)
    app.include_router(scoring_router, prefix="/api", tags=["Scoring"], dependencies=authenticated)
    app.include_router(scoring_runs_router, prefix="/api", tags=["Persistent Scoring Runs"], dependencies=authenticated)
    app.include_router(model_registry_router, prefix="/api", tags=["Model Registry"], dependencies=authenticated)
    app.include_router(model_diagnostics_router, prefix="/api", tags=["Model Diagnostics"], dependencies=authenticated)
    app.include_router(model_documentation_router, prefix="/api", tags=["Model Documentation Studio"], dependencies=authenticated)
    app.include_router(notebook_router, prefix="/api", tags=["Notebook Studio"], dependencies=authenticated)
    app.include_router(sql_studio_router, prefix="/api", tags=["SQL Data Studio"], dependencies=authenticated)
    app.include_router(evidence_router, prefix="/api", tags=["Evidence Graph"], dependencies=authenticated)
    app.include_router(credit_risk_router, prefix="/api", tags=["Credit Risk Studio"], dependencies=authenticated)
    app.include_router(experimentation_router, prefix="/api", tags=["Experimentation"], dependencies=authenticated)
    app.include_router(experimental_design_router, prefix="/api", tags=["Experimental Design"], dependencies=authenticated)
    app.include_router(optimization_router, prefix="/api", tags=["Optimization"], dependencies=authenticated)

    assert_api_routes_authenticated(app)
    return app


app = create_app()
