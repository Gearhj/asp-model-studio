from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from fastapi import HTTPException, UploadFile


ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "datasets"
REGISTRY_PATH = ARTIFACT_ROOT / "registry.json"
USERS_PATH = ARTIFACT_ROOT / "users.json"
PROJECT_LINKS_PATH = ARTIFACT_ROOT / "project_links.json"
MAX_DATASET_UPLOAD_BYTES = int(os.getenv("ATLAS_DATASET_LIBRARY_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024)))
MAX_PROFILE_ROWS = int(os.getenv("ATLAS_DATASET_LIBRARY_MAX_PROFILE_ROWS", "100000"))
MAX_SAMPLE_ROWS = int(os.getenv("ATLAS_DATASET_LIBRARY_MAX_SAMPLE_ROWS", "5000"))
MAX_PREVIEW_ROWS = int(os.getenv("ATLAS_DATASET_LIBRARY_MAX_PREVIEW_ROWS", "100"))
ALLOWED_EXTENSIONS = {".csv", ".txt"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_store() -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_PATH.exists():
        write_json(REGISTRY_PATH, {"datasets": []})
    if not PROJECT_LINKS_PATH.exists():
        write_json(PROJECT_LINKS_PATH, {"links": []})
    if not USERS_PATH.exists():
        write_json(
            USERS_PATH,
            {
                "currentUserId": "local-user",
                "users": [
                    {
                        "userId": "local-user",
                        "displayName": "Local ATLAS User",
                        "email": "local.user@atlas.local",
                        "role": "admin",
                    },
                    {
                        "userId": "analyst",
                        "displayName": "Analyst User",
                        "email": "analyst@atlas.local",
                        "role": "user",
                    },
                    {
                        "userId": "validator",
                        "displayName": "Model Validator",
                        "email": "validator@atlas.local",
                        "role": "user",
                    },
                ],
            },
        )


def read_json(path: Path, default: Any) -> Any:
    ensure_store()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def safe_slug(value: str, fallback: str = "dataset") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug[:80] or fallback


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def load_users() -> Dict[str, Any]:
    return read_json(USERS_PATH, {})


def save_users(payload: Dict[str, Any]) -> None:
    write_json(USERS_PATH, payload)


def current_user() -> Dict[str, Any]:
    payload = load_users()
    user_id = payload.get("currentUserId") or "local-user"
    users = payload.get("users") or []
    found = next((user for user in users if user.get("userId") == user_id), None)
    if found:
        return found
    return {"userId": "local-user", "displayName": "Local ATLAS User", "email": "local.user@atlas.local", "role": "admin"}


def list_users() -> List[Dict[str, Any]]:
    return list(load_users().get("users") or [])


def switch_user(user_id: str) -> Dict[str, Any]:
    payload = load_users()
    users = payload.get("users") or []
    user = next((item for item in users if item.get("userId") == user_id), None)
    if not user:
        raise HTTPException(status_code=404, detail="Unknown local ATLAS user.")
    payload["currentUserId"] = user_id
    save_users(payload)
    return user


def load_registry() -> Dict[str, Any]:
    return read_json(REGISTRY_PATH, {"datasets": []})


def save_registry(registry: Dict[str, Any]) -> None:
    write_json(REGISTRY_PATH, registry)


def load_links() -> Dict[str, Any]:
    return read_json(PROJECT_LINKS_PATH, {"links": []})


def save_links(links: Dict[str, Any]) -> None:
    write_json(PROJECT_LINKS_PATH, links)


def user_can_access(dataset: Dict[str, Any], user: Optional[Dict[str, Any]] = None, write: bool = False) -> bool:
    active = user or current_user()
    user_id = active.get("userId")
    if active.get("role") == "admin":
        return True
    if dataset.get("ownerUserId") == user_id:
        return True
    grants = dataset.get("access") or []
    allowed = {"admin", "editor"} if write else {"admin", "editor", "viewer"}
    return any(grant.get("userId") == user_id and grant.get("role") in allowed for grant in grants)


def require_dataset(dataset_id: str, write: bool = False) -> Dict[str, Any]:
    registry = load_registry()
    dataset = next((item for item in registry.get("datasets", []) if item.get("datasetId") == dataset_id), None)
    if not dataset or dataset.get("archived"):
        raise HTTPException(status_code=404, detail="Dataset not found.")
    if not user_can_access(dataset, write=write):
        raise HTTPException(status_code=403, detail="You do not have access to this dataset.")
    return dataset


def list_accessible_datasets(include_archived: bool = False) -> List[Dict[str, Any]]:
    user = current_user()
    datasets = load_registry().get("datasets", [])
    return [
        summarize_dataset(item)
        for item in datasets
        if (include_archived or not item.get("archived")) and user_can_access(item, user=user)
    ]


def dataset_dir(dataset_id: str) -> Path:
    return ARTIFACT_ROOT / dataset_id


def version_dir(dataset_id: str, version_id: str) -> Path:
    return dataset_dir(dataset_id) / "versions" / version_id


def summarize_dataset(dataset: Dict[str, Any]) -> Dict[str, Any]:
    versions = dataset.get("versions") or []
    latest = versions[-1] if versions else None
    return {
        "datasetId": dataset.get("datasetId"),
        "name": dataset.get("name"),
        "description": dataset.get("description"),
        "domain": dataset.get("domain"),
        "sourceType": dataset.get("sourceType"),
        "ownerUserId": dataset.get("ownerUserId"),
        "ownerDisplayName": dataset.get("ownerDisplayName"),
        "createdAt": dataset.get("createdAt"),
        "updatedAt": dataset.get("updatedAt"),
        "archived": bool(dataset.get("archived")),
        "access": dataset.get("access") or [],
        "versionCount": len(versions),
        "latestVersion": latest,
        "linkedProjects": dataset.get("linkedProjects") or [],
    }


def infer_dtype(series: pd.Series) -> str:
    non_missing = series.dropna()
    if non_missing.empty:
        return "empty"
    numeric = pd.to_numeric(non_missing, errors="coerce")
    if numeric.notna().mean() >= 0.9:
        return "numeric"
    parsed_dates = pd.to_datetime(non_missing.astype(str).head(200), errors="coerce")
    if parsed_dates.notna().mean() >= 0.8:
        return "datetime"
    return "categorical"


def profile_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    sample = df.head(MAX_PROFILE_ROWS)
    rows = int(df.shape[0])
    columns = int(df.shape[1])
    schema: List[Dict[str, Any]] = []
    warnings: List[str] = []
    target_candidates: List[str] = []
    for column in df.columns:
        series = sample[column]
        dtype = infer_dtype(series)
        missing_count = int(series.isna().sum() + (series.astype(str).str.strip() == "").sum())
        missing_pct = missing_count / max(1, len(series))
        distinct = int(series.nunique(dropna=True))
        entry: Dict[str, Any] = {
            "name": str(column),
            "dtype": dtype,
            "missingCountSample": missing_count,
            "missingPctSample": missing_pct,
            "distinctSample": distinct,
        }
        if dtype == "numeric":
            numeric = pd.to_numeric(series, errors="coerce")
            entry.update(
                {
                    "min": clean_number(numeric.min()),
                    "max": clean_number(numeric.max()),
                    "mean": clean_number(numeric.mean()),
                    "std": clean_number(numeric.std()),
                }
            )
        if missing_pct >= 0.2:
            warnings.append(f"{column} has high missingness in the profiled sample ({missing_pct:.1%}).")
        if str(column).lower() in {"target", "class", "label", "y", "response"} or distinct <= 20:
            target_candidates.append(str(column))
        schema.append(entry)
    duplicate_sample_rows = int(sample.duplicated().sum()) if len(sample) else 0
    if duplicate_sample_rows:
        warnings.append(f"{duplicate_sample_rows:,} duplicate rows detected in the profiled sample.")
    return {
        "rowCount": rows,
        "columnCount": columns,
        "profiledRows": int(sample.shape[0]),
        "schema": schema,
        "targetCandidates": target_candidates[:25],
        "warnings": warnings,
        "duplicateRowsSample": duplicate_sample_rows,
        "createdAt": now_iso(),
    }


def clean_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        return numeric
    except Exception:
        return None


def records_from_df(df: pd.DataFrame) -> List[Dict[str, Any]]:
    return json.loads(df.where(pd.notna(df), None).to_json(orient="records"))


def write_csv_sample(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.head(MAX_SAMPLE_ROWS).to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


async def create_dataset_from_upload(
    file: UploadFile,
    name: Optional[str] = None,
    description: str = "",
    domain: str = "General",
    source_type: str = "upload",
) -> Dict[str, Any]:
    filename = os.path.basename(file.filename or "dataset.csv")
    extension = os.path.splitext(filename)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Dataset Library currently accepts CSV or TXT delimited files.")
    content = await file.read()
    if len(content) > MAX_DATASET_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Dataset exceeds {MAX_DATASET_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.")
    digest = sha256_bytes(content)
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to profile dataset CSV: {exc}")
    if df.empty:
        raise HTTPException(status_code=400, detail="Dataset has no rows.")
    user = current_user()
    ts = str(int(time.time() * 1000))
    dataset_name = (name or Path(filename).stem or "Dataset").strip()
    dataset_id = f"ds_{safe_slug(dataset_name)}_{digest[:8]}"
    version_id = f"v_{ts}_{digest[:8]}"
    if (dataset_dir(dataset_id)).exists():
        dataset_id = f"{dataset_id}_{ts[-5:]}"
    profile = profile_dataframe(df)
    vdir = version_dir(dataset_id, version_id)
    vdir.mkdir(parents=True, exist_ok=True)
    write_json(vdir / "metadata.json", {"datasetId": dataset_id, "versionId": version_id, "originalFilename": filename})
    write_json(vdir / "schema.json", {"columns": profile["schema"]})
    write_json(vdir / "profile.json", profile)
    write_json(vdir / "preview.json", {"rows": records_from_df(df.head(MAX_PREVIEW_ROWS)), "columns": [str(c) for c in df.columns]})
    write_json(
        vdir / "lineage.json",
        {
            "sourceType": source_type,
            "originalFilename": filename,
            "registeredBy": user.get("userId"),
            "registeredAt": now_iso(),
            "hash": digest,
        },
    )
    write_csv_sample(vdir / "data_sample.csv", df)
    version_summary = {
        "versionId": version_id,
        "createdAt": now_iso(),
        "createdBy": user.get("userId"),
        "originalFilename": filename,
        "hash": digest,
        "rowCount": int(df.shape[0]),
        "columnCount": int(df.shape[1]),
        "profilePath": str((vdir / "profile.json").relative_to(ARTIFACT_ROOT)),
        "previewPath": str((vdir / "preview.json").relative_to(ARTIFACT_ROOT)),
        "samplePath": str((vdir / "data_sample.csv").relative_to(ARTIFACT_ROOT)),
        "warnings": profile.get("warnings", []),
    }
    dataset = {
        "datasetId": dataset_id,
        "name": dataset_name,
        "description": description,
        "domain": domain,
        "sourceType": source_type,
        "ownerUserId": user.get("userId"),
        "ownerDisplayName": user.get("displayName"),
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "archived": False,
        "access": [{"userId": user.get("userId"), "role": "admin"}],
        "versions": [version_summary],
        "linkedProjects": [],
    }
    registry = load_registry()
    registry["datasets"] = [item for item in registry.get("datasets", []) if item.get("datasetId") != dataset_id] + [dataset]
    save_registry(registry)
    return summarize_dataset(dataset)


async def add_dataset_version(dataset_id: str, file: UploadFile) -> Dict[str, Any]:
    dataset = require_dataset(dataset_id, write=True)
    filename = os.path.basename(file.filename or "dataset.csv")
    extension = os.path.splitext(filename)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Dataset Library currently accepts CSV or TXT delimited files.")
    content = await file.read()
    if len(content) > MAX_DATASET_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Dataset exceeds {MAX_DATASET_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.")
    digest = sha256_bytes(content)
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to profile dataset CSV: {exc}")
    ts = str(int(time.time() * 1000))
    version_id = f"v_{ts}_{digest[:8]}"
    profile = profile_dataframe(df)
    vdir = version_dir(dataset_id, version_id)
    vdir.mkdir(parents=True, exist_ok=True)
    write_json(vdir / "metadata.json", {"datasetId": dataset_id, "versionId": version_id, "originalFilename": filename})
    write_json(vdir / "schema.json", {"columns": profile["schema"]})
    write_json(vdir / "profile.json", profile)
    write_json(vdir / "preview.json", {"rows": records_from_df(df.head(MAX_PREVIEW_ROWS)), "columns": [str(c) for c in df.columns]})
    write_json(vdir / "lineage.json", {"sourceType": dataset.get("sourceType"), "originalFilename": filename, "registeredBy": current_user().get("userId"), "registeredAt": now_iso(), "hash": digest})
    write_csv_sample(vdir / "data_sample.csv", df)
    version_summary = {
        "versionId": version_id,
        "createdAt": now_iso(),
        "createdBy": current_user().get("userId"),
        "originalFilename": filename,
        "hash": digest,
        "rowCount": int(df.shape[0]),
        "columnCount": int(df.shape[1]),
        "profilePath": str((vdir / "profile.json").relative_to(ARTIFACT_ROOT)),
        "previewPath": str((vdir / "preview.json").relative_to(ARTIFACT_ROOT)),
        "samplePath": str((vdir / "data_sample.csv").relative_to(ARTIFACT_ROOT)),
        "warnings": profile.get("warnings", []),
    }
    registry = load_registry()
    for item in registry.get("datasets", []):
        if item.get("datasetId") == dataset_id:
            item.setdefault("versions", []).append(version_summary)
            item["updatedAt"] = now_iso()
            dataset = item
            break
    save_registry(registry)
    return version_summary


def create_metadata_only_dataset(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = str(payload.get("name") or "Registered Dataset")
    user = current_user()
    ts = str(int(time.time() * 1000))
    dataset_id = f"ds_{safe_slug(name)}_{ts[-8:]}"
    dataset = {
        "datasetId": dataset_id,
        "name": name,
        "description": str(payload.get("description") or ""),
        "domain": str(payload.get("domain") or "General"),
        "sourceType": str(payload.get("sourceType") or "registered"),
        "ownerUserId": user.get("userId"),
        "ownerDisplayName": user.get("displayName"),
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "archived": False,
        "access": [{"userId": user.get("userId"), "role": "admin"}],
        "versions": [],
        "linkedProjects": [],
        "sourceInfo": payload.get("sourceInfo") or {},
    }
    registry = load_registry()
    registry["datasets"] = registry.get("datasets", []) + [dataset]
    save_registry(registry)
    return summarize_dataset(dataset)


def read_version_artifact(dataset_id: str, version_id: str, name: str, default: Any) -> Any:
    require_dataset(dataset_id)
    path = version_dir(dataset_id, version_id) / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Dataset version artifact {name} was not found.")
    return read_json(path, default)


def list_versions(dataset_id: str) -> List[Dict[str, Any]]:
    dataset = require_dataset(dataset_id)
    return list(dataset.get("versions") or [])


def latest_version_id(dataset: Dict[str, Any]) -> Optional[str]:
    versions = dataset.get("versions") or []
    return versions[-1].get("versionId") if versions else None


def share_dataset(dataset_id: str, grants: Iterable[Dict[str, str]]) -> Dict[str, Any]:
    require_dataset(dataset_id, write=True)
    valid_users = {user.get("userId") for user in list_users()}
    clean_grants = []
    for grant in grants:
        user_id = grant.get("userId")
        role = grant.get("role")
        if user_id not in valid_users or role not in {"viewer", "editor", "admin"}:
            continue
        clean_grants.append({"userId": user_id, "role": role})
    registry = load_registry()
    updated = None
    for item in registry.get("datasets", []):
        if item.get("datasetId") == dataset_id:
            owner_grant = {"userId": item.get("ownerUserId"), "role": "admin"}
            item["access"] = [owner_grant] + [grant for grant in clean_grants if grant.get("userId") != owner_grant["userId"]]
            item["updatedAt"] = now_iso()
            updated = item
            break
    save_registry(registry)
    return summarize_dataset(updated or require_dataset(dataset_id))


def archive_dataset(dataset_id: str) -> Dict[str, Any]:
    require_dataset(dataset_id, write=True)
    registry = load_registry()
    updated = None
    for item in registry.get("datasets", []):
        if item.get("datasetId") == dataset_id:
            item["archived"] = True
            item["updatedAt"] = now_iso()
            updated = item
            break
    save_registry(registry)
    return summarize_dataset(updated or require_dataset(dataset_id))


def link_project(project_id: str, dataset_id: str, version_id: Optional[str], role: str = "modeling") -> Dict[str, Any]:
    dataset = require_dataset(dataset_id)
    resolved_version = version_id or latest_version_id(dataset)
    if not resolved_version:
        raise HTTPException(status_code=400, detail="Dataset has no version to link.")
    link = {
        "projectId": project_id,
        "datasetId": dataset_id,
        "versionId": resolved_version,
        "datasetRole": role,
        "linkedAt": now_iso(),
        "linkedBy": current_user().get("userId"),
    }
    links = load_links()
    links["links"] = [
        item
        for item in links.get("links", [])
        if not (item.get("projectId") == project_id and item.get("datasetId") == dataset_id and item.get("datasetRole") == role)
    ] + [link]
    save_links(links)
    registry = load_registry()
    for item in registry.get("datasets", []):
        if item.get("datasetId") == dataset_id:
            linked = [existing for existing in item.get("linkedProjects", []) if existing.get("projectId") != project_id]
            linked.append({"projectId": project_id, "versionId": resolved_version, "datasetRole": role})
            item["linkedProjects"] = linked
            item["updatedAt"] = now_iso()
    save_registry(registry)
    return link


def project_dataset_links(project_id: str) -> List[Dict[str, Any]]:
    datasets = {item.get("datasetId"): item for item in load_registry().get("datasets", [])}
    output = []
    for link in load_links().get("links", []):
        if link.get("projectId") != project_id:
            continue
        dataset = datasets.get(link.get("datasetId"))
        if not dataset or not user_can_access(dataset):
            continue
        output.append({**link, "dataset": summarize_dataset(dataset)})
    return output


def unlink_project_dataset(project_id: str, dataset_id: str) -> Dict[str, Any]:
    links = load_links()
    before = len(links.get("links", []))
    links["links"] = [item for item in links.get("links", []) if not (item.get("projectId") == project_id and item.get("datasetId") == dataset_id)]
    save_links(links)
    registry = load_registry()
    for item in registry.get("datasets", []):
        if item.get("datasetId") == dataset_id:
            item["linkedProjects"] = [link for link in item.get("linkedProjects", []) if link.get("projectId") != project_id]
            item["updatedAt"] = now_iso()
    save_registry(registry)
    return {"ok": True, "removed": before - len(links.get("links", []))}


def diagnostics() -> Dict[str, Any]:
    ensure_store()
    registry = load_registry()
    links = load_links()
    datasets = registry.get("datasets", [])
    active = [item for item in datasets if not item.get("archived")]
    checks = [
        {
            "id": "artifact_root",
            "label": "Dataset artifact root",
            "status": "pass" if ARTIFACT_ROOT.exists() else "fail",
            "detail": str(ARTIFACT_ROOT),
        },
        {
            "id": "registry",
            "label": "Dataset registry",
            "status": "pass" if isinstance(datasets, list) else "fail",
            "detail": f"{len(datasets)} total dataset records.",
        },
        {
            "id": "users",
            "label": "Local users",
            "status": "pass" if list_users() else "fail",
            "detail": f"{len(list_users())} local user records.",
        },
        {
            "id": "project_links",
            "label": "Project links",
            "status": "pass",
            "detail": f"{len(links.get('links', []))} project-dataset links.",
        },
        {
            "id": "acl",
            "label": "Access control",
            "status": "pass",
            "detail": "Dataset list/detail endpoints filter by owner, grants, or admin role.",
        },
    ]
    return {
        "ok": True,
        "generatedAt": now_iso(),
        "currentUser": current_user(),
        "artifactRoot": str(ARTIFACT_ROOT),
        "datasetCount": len(active),
        "archivedCount": len(datasets) - len(active),
        "projectLinkCount": len(links.get("links", [])),
        "checks": checks,
    }
