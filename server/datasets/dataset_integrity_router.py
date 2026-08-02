"""Administrator-only Dataset Library reconciliation diagnostics."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ..persistence import get_persistence_service
from ..security.security_store import list_users, require_user
from .dataset_integrity import run_bounded_integrity_scan


router = APIRouter()


@router.get("/admin/dataset-library/reconciliation")
def dataset_library_reconciliation(
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Return a fresh, bounded report without exposing it to non-admin users."""

    if str(user.get("role") or "").casefold() != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin role is required for Dataset Library reconciliation.",
        )
    known_users = {
        str(item.get("userId") or ""): item
        for item in list_users()
        if item.get("userId")
    }
    persistence = get_persistence_service()
    integrity = run_bounded_integrity_scan(
        database=persistence.database,
        user_resolver=known_users.get,
    )
    return {"ok": True, **integrity}


__all__ = ["router"]
