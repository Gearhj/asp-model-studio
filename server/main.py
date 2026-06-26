# server/main.py
# =============================================================================
# DS Workflow Backend (Modular, Package-Aware)
# =============================================================================

from __future__ import annotations

from typing import Dict, Any, List
import io

import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Core in-memory store
from .core.dataset_store import DATASTORE

# Modular routers
from .core.metadata_router import router as metadata_router
from .eda.eda_router import router as eda_router
from .preprocessing.outlier_router import router as outlier_router
from .splitting.split_router import router as split_router
from .training.trainer_router import router as trainer_router
from .evaluation.eval_router import router as eval_router
from .stela_router import router as stela_router


def create_app() -> FastAPI:
    """
    Application factory for the DS Workflow backend.

    Keeps main.py thin:
      - CORS + app creation
      - healthcheck
      - CSV upload endpoint
      - router wiring
    """
    app = FastAPI(
        title="DS Workflow API",
        version="0.1.0",
        description="Backend API for the DS Workflow (regulated ML pipeline).",
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
        # You can tighten this later; keeping "*" for now is simplest in dev.
        "*",
    ]

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

    # -------------------------------------------------------------------------
    # Data Acquisition – optional CSV upload endpoint (Step01 alternative)
    # -------------------------------------------------------------------------
    @app.post("/api/data/upload_csv")
    async def upload_csv(file: UploadFile = File(...)) -> Dict[str, Any]:
        """
        Upload a CSV file and store it as the RAW dataset in DATASTORE.

        NOTE: Your current Step01_DataAcquisition.tsx uses /api/data/set_sample
        with JSON rows. This endpoint is kept for compatibility / future use.
        """
        try:
            content = await file.read()
            df = pd.read_csv(io.BytesIO(content))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read CSV: {exc}")

        if df.empty:
            raise HTTPException(status_code=400, detail="Uploaded CSV has no rows.")

        DATASTORE.set_raw(df)

        return {
            "ok": True,
            "rows": int(df.shape[0]),
            "cols": int(df.shape[1]),
            "columns": [str(c) for c in df.columns],
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
    app.include_router(metadata_router, prefix="/api", tags=["Metadata"])
    app.include_router(eda_router, prefix="/api/eda", tags=["EDA"])
    app.include_router(outlier_router, prefix="/api/outliers", tags=["Outliers"])
    app.include_router(split_router, prefix="/api/balancing_split", tags=["Splitting & Balancing"])
    app.include_router(trainer_router, prefix="/api", tags=["Training"])
    app.include_router(eval_router, prefix="/api", tags=["Evaluation"])
    app.include_router(stela_router, prefix="/api", tags=["STELA"])

    return app


app = create_app()
