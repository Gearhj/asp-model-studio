# server/splitting/split_router.py
# =============================================================================
# Split & Balancing Router for DS Workflow (Step06)
# =============================================================================
# Exposes the endpoint used by Step06:
#
#   POST /api/balancing_split/config
#
# The React Step06 currently sends:
#
#   {
#     split_strategy: "holdout" | "kfold",
#     k_folds: number,
#     balance_method: "undersample" | "smote" | "class_weight" | "none",
#     balance_ratio: "90/10" | "80/20" | ...
#   }
#
# We:
#   • Retrieve the current DataFrame + target from DATASTORE
#   • Use split_service to create dev splits (X_train, X_test, y_train, y_test)
#   • Store them back into DATASTORE.splits
#   • Return a lightweight ack + sizes (n_train, n_test)
# =============================================================================

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.dataset_store import DATASTORE
from .split_service import split_service


router = APIRouter()


class SplitConfigPayload(BaseModel):
    split_strategy: str = Field(
        "holdout",
        description="holdout|kfold",
        pattern=r"^(holdout|kfold)$",
    )
    k_folds: int = 5
    balance_method: str = Field(
        "none",
        description="undersample|smote|class_weight|none",
        pattern=r"^(undersample|smote|class_weight|none)$",
    )
    balance_ratio: str = Field(
        "80/20",
        description="string like '80/20' representing train/test or maj/min",
        pattern=r"^\d+/\d+$",
    )


def _require_df_and_target():
    """
    Use processed_df if available, else raw_df. Require a valid target.
    """
    df = None
    if DATASTORE.processed_df is not None:
        df = DATASTORE.processed_df
    elif DATASTORE.raw_df is not None:
        df = DATASTORE.raw_df

    if df is None:
        raise HTTPException(status_code=400, detail="No dataset loaded.")

    target = DATASTORE.target
    if target is None:
        raise HTTPException(
            status_code=400,
            detail="Target column is not set in DATASTORE.",
        )
    if target not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Target column '{target}' not found in dataset.",
        )

    return df, target


@router.post("/config")
def balancing_split_config(payload: SplitConfigPayload):
    """
    Save split/balancing config from Step06 and materialize the dev dataset.
    """
    if DATASTORE is None:
        raise HTTPException(status_code=500, detail="DATASTORE is not initialized.")

    df, target = _require_df_and_target()

    config = payload.model_dump()

    try:
        X_train, X_test, y_train, y_test, test_size = split_service.make_dev_split(
            df, target, config
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to create development split: {exc}",
        )

    # Persist splits in DATASTORE for Step07 training
    DATASTORE.set_splits(X_train, X_test, y_train, y_test)

    return {
        "ok": True,
        "config": config,
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
        "test_size": float(test_size),
    }
