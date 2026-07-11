from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..security.security_store import active_user, audit_event

SQL_STUDIO_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "sql_studio"
QUERIES_DIR = SQL_STUDIO_ROOT / "queries"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_store() -> None:
    QUERIES_DIR.mkdir(parents=True, exist_ok=True)


def safe_id(value: str, fallback: str = "query") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug[:80] or fallback


def current_user_id() -> str:
    user = active_user() or {}
    return str(user.get("userId") or "local-user")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def list_queries() -> List[Dict[str, Any]]:
    ensure_store()
    queries = [read_json(path, {}) for path in QUERIES_DIR.glob("*.json")]
    return sorted([query for query in queries if query.get("queryId")], key=lambda item: item.get("updatedAt", ""), reverse=True)


def get_query(query_id: str) -> Dict[str, Any]:
    ensure_store()
    query = read_json(QUERIES_DIR / f"{safe_id(query_id)}.json", {})
    if not query:
        return {}
    return query


def save_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_store()
    timestamp = now_iso()
    name = str(payload.get("name") or "Untitled SQL Query").strip()
    query_id = str(payload.get("queryId") or f"sqlq_{safe_id(name)}_{int(time.time() * 1000)}")
    existing = get_query(query_id)
    query = {
        "queryId": query_id,
        "name": name,
        "description": payload.get("description") or "",
        "sql": payload.get("sql") or "",
        "sourceType": payload.get("sourceType") or "dataset_library_preview",
        "datasetRefs": payload.get("datasetRefs") or [],
        "parameters": payload.get("parameters") or [],
        "createdAt": existing.get("createdAt") or timestamp,
        "updatedAt": timestamp,
        "createdBy": existing.get("createdBy") or current_user_id(),
        "linkedProjectId": payload.get("linkedProjectId") or existing.get("linkedProjectId") or "",
        "tags": payload.get("tags") or existing.get("tags") or [],
    }
    write_json(QUERIES_DIR / f"{safe_id(query_id)}.json", query)
    audit_event("sql_studio.query.saved", "sql_query", query_id, "success", metadata={"name": name})
    return query


def delete_query(query_id: str) -> Dict[str, Any]:
    ensure_store()
    path = QUERIES_DIR / f"{safe_id(query_id)}.json"
    existed = path.exists()
    if existed:
        path.unlink()
    audit_event("sql_studio.query.deleted", "sql_query", query_id, "success" if existed else "not_found")
    return {"ok": True, "deleted": existed}

