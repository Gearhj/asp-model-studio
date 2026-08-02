from __future__ import annotations

import json
import os
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    default = Path(__file__).resolve().parents[1] / "artifacts" / "vif_resolution_plans"
    return Path(os.getenv("ATLAS_VIF_PLAN_ROOT", str(default)))


def _safe(value: Any) -> str:
    text = str(value or "").strip()
    if not text or any(part in text for part in ("..", "/", "\\")):
        raise ValueError("VIF plan identity contains an invalid path component.")
    return text


def _scope(project_id: str, dataset_id: str, dataset_version_id: str) -> Path:
    return _root() / _safe(project_id) / _safe(dataset_id) / _safe(dataset_version_id)


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def save_generated_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Persist one immutable analytical plan under exact dataset identity."""

    scope = _scope(plan["project_id"], plan["dataset_id"], plan["dataset_version_id"])
    plan_id = _safe(plan["plan_id"])
    path = scope / "plans" / f"{plan_id}.json"
    with _LOCK:
        existing = _read(path)
        if existing is not None:
            return deepcopy(existing)
        record = {
            **deepcopy(plan),
            "status": "generated",
            "created_at": plan.get("created_at") or _now(),
            "updated_at": plan.get("created_at") or _now(),
            "decision_history": [],
        }
        _write_atomic(path, record)
        return deepcopy(record)


def get_plan(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    plan_id: str,
) -> dict[str, Any] | None:
    path = _scope(project_id, dataset_id, dataset_version_id) / "plans" / f"{_safe(plan_id)}.json"
    with _LOCK:
        value = _read(path)
    return deepcopy(value) if value else None


def record_plan_decision(
    *,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    plan_id: str,
    action: str,
    selected_cluster_ids: list[str],
    rationale: str,
    modifications: dict[str, Any],
    recommendations: list[dict[str, Any]],
    actor_id: str,
) -> dict[str, Any]:
    """Record a disposition and optional draft FE recommendations.

    Recommendations are deliberately stored in a separate queue. This function
    never calls the Feature Manifest or mutates a dataset.
    """

    scope = _scope(project_id, dataset_id, dataset_version_id)
    plan_path = scope / "plans" / f"{_safe(plan_id)}.json"
    with _LOCK:
        plan = _read(plan_path)
        if plan is None:
            raise ValueError("The exact VIF resolution plan was not found.")
        disposition_id = f"{plan_id}:{action}:{','.join(sorted(selected_cluster_ids))}"
        if any(row.get("disposition_id") == disposition_id for row in plan.get("decision_history", [])):
            return deepcopy(plan)
        decision = {
            "disposition_id": disposition_id,
            "action": action,
            "selected_cluster_ids": sorted(set(selected_cluster_ids)),
            "rationale": str(rationale or "").strip(),
            "modifications": deepcopy(modifications),
            "recorded_at": _now(),
            "recorded_by": actor_id,
            "recommendation_count": len(recommendations),
        }
        plan.setdefault("decision_history", []).append(decision)
        plan["status"] = {
            "accept_complete": "accepted",
            "accept_selected": "partially_accepted",
            "modify": "modified",
            "reject": "rejected",
            "defer": "deferred",
            "send_to_feature_engineering": "sent_to_feature_engineering",
        }[action]
        plan["updated_at"] = decision["recorded_at"]
        if recommendations:
            queue_record = {
                "ok": True,
                "recommendation_contract": "draft_feature_engineering_recommendations",
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "source_plan_id": plan_id,
                "status": "draft",
                "governed_feature_set_changed": False,
                "dataset_mutated": False,
                "recommendations": deepcopy(recommendations),
                "created_at": decision["recorded_at"],
                "created_by": actor_id,
            }
            queue_path = scope / "feature_recommendations" / f"{_safe(plan_id)}.json"
            existing_queue = _read(queue_path)
            if existing_queue is not None:
                merged = {
                    str(item.get("recommendation_id")): item
                    for item in existing_queue.get("recommendations", [])
                    if item.get("recommendation_id")
                }
                merged.update(
                    {
                        str(item.get("recommendation_id")): item
                        for item in recommendations
                        if item.get("recommendation_id")
                    }
                )
                queue_record = {
                    **existing_queue,
                    "status": "draft",
                    "recommendations": list(merged.values()),
                    "updated_at": decision["recorded_at"],
                    "governed_feature_set_changed": False,
                    "dataset_mutated": False,
                }
            _write_atomic(queue_path, queue_record)
            plan["feature_recommendation_reference"] = str(queue_path.relative_to(_root()))
        _write_atomic(plan_path, plan)
        return deepcopy(plan)


def get_feature_recommendations(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    plan_id: str,
) -> dict[str, Any] | None:
    path = (
        _scope(project_id, dataset_id, dataset_version_id)
        / "feature_recommendations"
        / f"{_safe(plan_id)}.json"
    )
    with _LOCK:
        value = _read(path)
    return deepcopy(value) if value else None


def list_feature_recommendations(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
) -> list[dict[str, Any]]:
    directory = _scope(project_id, dataset_id, dataset_version_id) / "feature_recommendations"
    with _LOCK:
        if not directory.exists():
            return []
        values = [
            value
            for path in sorted(directory.glob("*.json"))
            if (value := _read(path)) is not None
        ]
    return deepcopy(values)
