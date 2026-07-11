# server/main.py
# =============================================================================
# ATLAS Backend (Modular, Package-Aware)
# =============================================================================

from __future__ import annotations

from typing import Dict, Any, List
import io
import os

import pandas as pd
from fastapi import Depends, FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

# Core in-memory store
from .core.dataset_store import DATASTORE
from .core.session_checkpoint import load_checkpoint, save_checkpoint

# Modular routers
from .core.metadata_router import _infer_target, router as metadata_router
from .core.utils import df_to_records
from .eda.eda_router import router as eda_router
from .preprocessing.outlier_router import router as outlier_router
from .preprocessing.missing_router import router as missing_router
from .splitting.split_router import router as split_router
from .training.trainer_router import router as trainer_router
from .evaluation.eval_router import router as eval_router
from .python_execution import router as python_execution_router
from .datasets.dataset_router import router as dataset_library_router
from .security.security_router import router as security_router
from .security.security_store import init_security_store, require_user
from .analytics.analytics_router import router as analytics_router
from .charts.chart_router import router as chart_router
from .model_diagnostics.diagnostics_router import router as model_diagnostics_router
from .model_documentation.documentation_router import router as model_documentation_router
from .notebooks.notebook_router import router as notebook_router
from .scoring.scoring_router import router as scoring_router
from .projects.project_router import router as project_registry_router
from .sql_studio.sql_router import router as sql_studio_router
from .evidence.evidence_router import router as evidence_router
from .credit_risk.credit_risk_router import router as credit_risk_router

MAX_UPLOAD_BYTES = int(os.getenv("ATLAS_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024)))
MAX_UPLOAD_ROWS = int(os.getenv("ATLAS_MAX_UPLOAD_ROWS", "500000"))
MAX_UPLOAD_COLUMNS = int(os.getenv("ATLAS_MAX_UPLOAD_COLUMNS", "750"))
MAX_UPLOAD_SAMPLE_ROWS = int(os.getenv("ATLAS_MAX_UPLOAD_SAMPLE_ROWS", "5000"))
ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".txt"}
PUBLIC_API_PATHS = {
    "/api/health",
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

    # -------------------------------------------------------------------------
    # CORS – support local Vite dev + fall back to permissive for now
    # -------------------------------------------------------------------------
    origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    extra_origins = [origin.strip() for origin in os.getenv("ATLAS_CORS_ORIGINS", "").split(",") if origin.strip()]
    origins.extend(extra_origins)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {"ok": True, "status": "running"}

    @app.on_event("startup")
    def restore_session_checkpoint() -> None:
        init_security_store()
        load_checkpoint()

    # -------------------------------------------------------------------------
    # Data Acquisition – optional CSV upload endpoint (Step01 alternative)
    # -------------------------------------------------------------------------
    @app.post("/api/data/upload_csv")
    async def upload_csv(file: UploadFile = File(...), _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
        """
        Upload a CSV file and store it as the RAW dataset in DATASTORE.

        NOTE: Your current Step01_DataAcquisition.tsx uses /api/data/set_sample
        with JSON rows. This endpoint is kept for compatibility / future use.
        """
        filename = file.filename or ""
        extension = os.path.splitext(filename)[1].lower()
        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Only CSV or TXT delimited uploads are accepted by this endpoint.")

        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Upload is too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            )

        try:
            df = pd.read_csv(io.BytesIO(content))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read CSV: {exc}")

        if df.empty:
            raise HTTPException(status_code=400, detail="Uploaded CSV has no rows.")
        if int(df.shape[0]) > MAX_UPLOAD_ROWS:
            raise HTTPException(status_code=413, detail=f"Uploaded CSV has too many rows. Maximum is {MAX_UPLOAD_ROWS:,}.")
        if int(df.shape[1]) > MAX_UPLOAD_COLUMNS:
            raise HTTPException(status_code=413, detail=f"Uploaded CSV has too many columns. Maximum is {MAX_UPLOAD_COLUMNS:,}.")

        DATASTORE.set_raw(df)
        target = _infer_target(df)
        columns = [str(c) for c in df.columns]
        selected_columns = [col for col in columns if col != target]
        DATASTORE.meta["selected_columns"] = selected_columns
        DATASTORE.meta["source"] = {
            "kind": "backend_csv_import",
            "filename": filename,
            "rows": int(df.shape[0]),
            "columns": int(df.shape[1]),
            "target": target,
            "selected_columns": selected_columns,
        }
        save_checkpoint()
        sample_df = df.head(max(1, min(MAX_UPLOAD_SAMPLE_ROWS, int(df.shape[0]))))

        return {
            "ok": True,
            "source": "backend_csv_import",
            "filename": filename,
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
    app.include_router(eda_router, prefix="/api/eda", tags=["EDA"], dependencies=authenticated)
    app.include_router(outlier_router, prefix="/api/outliers", tags=["Outliers"], dependencies=authenticated)
    app.include_router(missing_router, prefix="/api/missing", tags=["Missing Values"], dependencies=authenticated)
    app.include_router(split_router, prefix="/api/balancing_split", tags=["Splitting & Balancing"], dependencies=authenticated)
    app.include_router(trainer_router, prefix="/api", tags=["Training"], dependencies=authenticated)
    app.include_router(eval_router, prefix="/api", tags=["Evaluation"], dependencies=authenticated)
    app.include_router(python_execution_router, prefix="/api", tags=["Python Execution"], dependencies=authenticated)
    app.include_router(security_router, prefix="/api", tags=["Security"])
    app.include_router(dataset_library_router, prefix="/api", tags=["Dataset Library"], dependencies=authenticated)
    app.include_router(project_registry_router, prefix="/api", tags=["Project Registry"], dependencies=authenticated)
    app.include_router(analytics_router, prefix="/api", tags=["Analytics Workbench"], dependencies=authenticated)
    app.include_router(chart_router, prefix="/api", tags=["Chart Studio"], dependencies=authenticated)
    app.include_router(scoring_router, prefix="/api", tags=["Scoring"], dependencies=authenticated)
    app.include_router(model_diagnostics_router, prefix="/api", tags=["Model Diagnostics"], dependencies=authenticated)
    app.include_router(model_documentation_router, prefix="/api", tags=["Model Documentation Studio"], dependencies=authenticated)
    app.include_router(notebook_router, prefix="/api", tags=["Notebook Studio"], dependencies=authenticated)
    app.include_router(sql_studio_router, prefix="/api", tags=["SQL Data Studio"], dependencies=authenticated)
    app.include_router(evidence_router, prefix="/api", tags=["Evidence Graph"], dependencies=authenticated)
    app.include_router(credit_risk_router, prefix="/api", tags=["Credit Risk Studio"], dependencies=authenticated)

    assert_api_routes_authenticated(app)
    return app


app = create_app()
