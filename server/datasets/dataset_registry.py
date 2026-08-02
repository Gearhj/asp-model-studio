from __future__ import annotations

import csv
import copy
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import pandas as pd
from fastapi import HTTPException, UploadFile

from .dataset_storage import (
    DatasetLibraryPaths,
    DatasetLibraryStorage,
    DatasetStorageError,
    DatasetStoreMissingError,
    atomic_write_json,
    library_write_lock,
    read_json_strict,
    sha256_file,
)
from ..security.security_store import (
    active_user,
    audit_event,
    get_user,
    list_users as security_list_users,
    security_diagnostics,
)


# ATLAS_DATASET_LIBRARY_ROOT (dataset lifecycle audit): lets standalone test/script
# processes point at an isolated artifact root instead of the shared dev backend's
# real server/artifacts/datasets/registry.json -- same cross-process clobbering risk
# ATLAS_CHECKPOINT_PATH (Stage 6.1) exists to avoid, applied here for the same reason.
ARTIFACT_ROOT = Path(os.getenv("ATLAS_DATASET_LIBRARY_ROOT", str(Path(__file__).resolve().parents[1] / "artifacts" / "datasets")))
REGISTRY_PATH = ARTIFACT_ROOT / "registry.json"
USERS_PATH = ARTIFACT_ROOT / "users.json"
PROJECT_LINKS_PATH = ARTIFACT_ROOT / "project_links.json"
MAX_DATASET_UPLOAD_BYTES = int(os.getenv("ATLAS_DATASET_LIBRARY_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024)))
MAX_PROFILE_ROWS = int(os.getenv("ATLAS_DATASET_LIBRARY_MAX_PROFILE_ROWS", "100000"))
MAX_SAMPLE_ROWS = int(os.getenv("ATLAS_DATASET_LIBRARY_MAX_SAMPLE_ROWS", "5000"))
MAX_PREVIEW_ROWS = int(os.getenv("ATLAS_DATASET_LIBRARY_MAX_PREVIEW_ROWS", "100"))
DATASET_LIBRARY_BACKUP_RETENTION = int(
    os.getenv("ATLAS_DATASET_LIBRARY_BACKUP_RETENTION", "20")
)
ALLOWED_EXTENSIONS = {".csv", ".txt"}
SAFE_ARTIFACT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DEFAULT_ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "datasets"
DEFAULT_PERSISTENCE_PATH = Path(__file__).resolve().parents[1] / "data" / "atlas_local.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_artifact_segment(value: str) -> bool:
    normalized = str(value or "")
    return bool(
        normalized not in {".", ".."}
        and SAFE_ARTIFACT_SEGMENT_RE.fullmatch(normalized)
    )


def _dataset_test_mode_enabled() -> bool:
    return (
        os.getenv("ATLAS_ENV", "").strip().casefold() in {"test", "testing"}
        or os.getenv("ATLAS_TEST_MODE", "").strip().casefold()
        in {"1", "true", "yes"}
        or bool(os.getenv("PYTEST_CURRENT_TEST"))
    )


def _mutation_storage_preflight() -> DatasetLibraryStorage:
    """Bind every mutator to the current, physically safe configured root.

    Dataset Registry caches paths at import time. Tests and embedded callers can
    subsequently change their environment, so a mutation must prove that the
    cached authorities still match the configured root before creating even an
    artifact directory. ``from_environment`` also rejects linked and physical
    aliases of the checked-in live root.
    """

    environment_paths = DatasetLibraryPaths.from_environment(
        backup_root=os.getenv("ATLAS_DATASET_LIBRARY_BACKUP_ROOT") or None
    )
    cached_root = ARTIFACT_ROOT.expanduser().resolve()
    cached_paths = {
        "root": cached_root,
        "registry": REGISTRY_PATH.expanduser().resolve(),
        "project links": PROJECT_LINKS_PATH.expanduser().resolve(),
        "users": USERS_PATH.expanduser().resolve(),
    }
    expected_paths = {
        "root": environment_paths.root,
        "registry": environment_paths.registry_path,
        "project links": environment_paths.project_links_path,
        "users": environment_paths.users_path,
    }
    mismatched = [
        label
        for label, cached_path in cached_paths.items()
        if cached_path != expected_paths[label]
    ]
    if mismatched:
        raise DatasetStorageError(
            "Dataset Library cached paths do not match the current configured "
            f"root ({', '.join(mismatched)}). Rebind paths before mutation."
        )
    storage = DatasetLibraryStorage(environment_paths)
    if _dataset_test_mode_enabled():
        storage.assert_test_storage_isolated()
    storage.assert_no_pending_recovery()
    return storage


def _durable_dataset_authority_exists() -> bool:
    """Read-only guard against bootstrapping over surviving durable links."""

    configured_database = os.getenv("ATLAS_SQLITE_PATH")
    if configured_database:
        database_path = Path(configured_database).expanduser().resolve()
    elif ARTIFACT_ROOT.expanduser().resolve() == DEFAULT_ARTIFACT_ROOT.resolve():
        database_path = DEFAULT_PERSISTENCE_PATH.resolve()
    else:
        return False
    if not database_path.exists():
        return False
    uri = f"file:{database_path.as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            for table in (
                "project_dataset_links",
                "active_modeling_dataset_versions",
            ):
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                if exists and connection.execute(
                    f'SELECT 1 FROM "{table}" LIMIT 1'
                ).fetchone():
                    return True
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DatasetStoreMissingError(
            "The Dataset Library registry is missing and durable dataset "
            f"authority could not be verified ({type(exc).__name__})."
        ) from exc
    return False


def ensure_store() -> None:
    _mutation_storage_preflight()
    if not REGISTRY_PATH.exists():
        surviving_entries = (
            [
                child
                for child in ARTIFACT_ROOT.iterdir()
                if child.name != ".dataset-library.lock"
            ]
            if ARTIFACT_ROOT.exists()
            else []
        )
        if surviving_entries or _durable_dataset_authority_exists():
            raise DatasetStoreMissingError(
                "The Dataset Library registry is missing while catalog evidence "
                "still exists. Run the read-only reconciliation command; ATLAS "
                "will not replace the missing catalog with an empty registry."
            )
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        write_json(REGISTRY_PATH, {"datasets": []}, create_backup=False)
    if not PROJECT_LINKS_PATH.exists():
        registry = read_json_strict(REGISTRY_PATH, "datasets")
        if registry.get("datasets") or _durable_dataset_authority_exists():
            raise DatasetStoreMissingError(
                "The Dataset Library project-link store is missing for a "
                "non-empty catalog or surviving durable dataset authority. "
                "Run reconciliation before changing links."
            )
        write_json(PROJECT_LINKS_PATH, {"links": []}, create_backup=False)
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
            create_backup=False,
        )


def read_json(path: Path, default: Any) -> Any:
    ensure_store()
    expected_root_key = None
    if path == REGISTRY_PATH:
        expected_root_key = "datasets"
    elif path == PROJECT_LINKS_PATH:
        expected_root_key = "links"
    elif path == USERS_PATH:
        expected_root_key = "users"
    return read_json_strict(path, expected_root_key)


def write_json(
    path: Path,
    payload: Any,
    *,
    create_backup: Optional[bool] = None,
) -> None:
    _mutation_storage_preflight()
    authoritative_document = path in {
        REGISTRY_PATH,
        PROJECT_LINKS_PATH,
        USERS_PATH,
    }
    atomic_write_json(
        path,
        payload,
        backup_root=os.getenv("ATLAS_DATASET_LIBRARY_BACKUP_ROOT") or None,
        retention=DATASET_LIBRARY_BACKUP_RETENTION,
        create_backup=(
            authoritative_document
            if create_backup is None
            else bool(create_backup)
        ),
    )


def _canonical_document_hash(payload: Any) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    return hashlib.sha256((rendered + "\n").encode("utf-8")).hexdigest()


def _library_storage() -> DatasetLibraryStorage:
    return _mutation_storage_preflight()


def _mutate_registry_and_links_transaction(
    *,
    operation_type: str,
    reason: str,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str | None,
    mutator: Callable[[Dict[str, Any], Dict[str, Any]], Any],
) -> Any:
    """Crash-detectable two-document projection update with compensation."""

    storage = _library_storage()
    with storage.exclusive_lock():
        ensure_store()
        registry_before_bytes = REGISTRY_PATH.read_bytes()
        links_before_bytes = PROJECT_LINKS_PATH.read_bytes()
        registry_before = read_json_strict(REGISTRY_PATH, "datasets")
        links_before = read_json_strict(PROJECT_LINKS_PATH, "links")
        registry_after = copy.deepcopy(registry_before)
        links_after = copy.deepcopy(links_before)
        outcome = mutator(registry_after, links_after)
        if registry_after == registry_before and links_after == links_before:
            return outcome

        registry_before_hash = sha256_bytes(registry_before_bytes)
        links_before_hash = sha256_bytes(links_before_bytes)
        registry_after_hash = (
            registry_before_hash
            if registry_after == registry_before
            else _canonical_document_hash(registry_after)
        )
        links_after_hash = (
            links_before_hash
            if links_after == links_before
            else _canonical_document_hash(links_after)
        )
        backup = storage.create_backup_bundle(
            reason=reason,
            include_paths=(REGISTRY_PATH, PROJECT_LINKS_PATH),
            retention_limit=DATASET_LIBRARY_BACKUP_RETENTION,
            defer_retention=True,
        )
        actor = current_user()
        journal = {
            "kind": "atlas_dataset_library_recovery_journal",
            "formatVersion": 1,
            "status": "prepared",
            "operationId": f"dataset-projection-{uuid.uuid4().hex}",
            "operationType": operation_type,
            "createdAt": now_iso(),
            "actorUserId": actor.get("userId"),
            "reason": reason,
            "projectId": project_id,
            "datasetId": dataset_id,
            "datasetVersionId": dataset_version_id,
            "backupBundleName": Path(str(backup["bundlePath"])).name,
            "backupManifestSha256": backup["manifestSha256"],
            "before": {
                "registrySha256": registry_before_hash,
                "projectLinksSha256": links_before_hash,
            },
            "expectedAfter": {
                "registrySha256": registry_after_hash,
                "projectLinksSha256": links_after_hash,
            },
        }
        previous_journal_hash = (
            sha256_file(storage.paths.recovery_journal_path)
            if storage.paths.recovery_journal_path.exists()
            else None
        )
        storage.write_recovery_journal(
            journal,
            expected_sha256=previous_journal_hash,
        )
        links_write_attempted = False
        registry_write_attempted = False
        try:
            if links_after != links_before:
                links_write_attempted = True
                storage.atomic_write_json(
                    PROJECT_LINKS_PATH,
                    links_after,
                    expected_sha256=links_before_hash,
                )
            if registry_after != registry_before:
                registry_write_attempted = True
                storage.atomic_write_json(
                    REGISTRY_PATH,
                    registry_after,
                    expected_sha256=registry_before_hash,
                )
            if (
                sha256_file(REGISTRY_PATH) != registry_after_hash
                or sha256_file(PROJECT_LINKS_PATH) != links_after_hash
            ):
                raise RuntimeError(
                    "Dataset Library projection transaction failed verification."
                )
        except Exception as mutation_error:
            try:
                registry_live_hash = sha256_file(REGISTRY_PATH)
                links_live_hash = sha256_file(PROJECT_LINKS_PATH)
                if registry_live_hash != registry_before_hash:
                    if (
                        not registry_write_attempted
                        or registry_live_hash != registry_after_hash
                    ):
                        raise RuntimeError(
                            "Dataset Library registry changed outside the "
                            "prepared projection transaction."
                        )
                    storage.atomic_restore_json_bytes(
                        REGISTRY_PATH,
                        registry_before_bytes,
                        expected_sha256=registry_live_hash,
                    )
                if links_live_hash != links_before_hash:
                    if (
                        not links_write_attempted
                        or links_live_hash != links_after_hash
                    ):
                        raise RuntimeError(
                            "Dataset Library project links changed outside the "
                            "prepared projection transaction."
                        )
                    storage.atomic_restore_json_bytes(
                        PROJECT_LINKS_PATH,
                        links_before_bytes,
                        expected_sha256=links_live_hash,
                    )
                if (
                    sha256_file(REGISTRY_PATH) != registry_before_hash
                    or sha256_file(PROJECT_LINKS_PATH) != links_before_hash
                ):
                    raise RuntimeError(
                        "Dataset Library projection compensation did not restore both documents."
                    )
                journal["status"] = "aborted"
                journal["resolvedAt"] = now_iso()
                journal["failureType"] = type(mutation_error).__name__
                storage.write_recovery_journal(
                    journal,
                    expected_sha256=sha256_file(
                        storage.paths.recovery_journal_path
                    ),
                )
            except Exception as compensation_error:
                raise RuntimeError(
                    "Dataset Library projection transaction is incomplete; "
                    "the prepared journal was left in place."
                ) from compensation_error
            raise

        journal["status"] = "committed"
        journal["resolvedAt"] = now_iso()
        storage.write_recovery_journal(
            journal,
            expected_sha256=sha256_file(storage.paths.recovery_journal_path),
        )
        try:
            storage.prune_backup_bundles(
                retention_limit=DATASET_LIBRARY_BACKUP_RETENTION
            )
        except DatasetStorageError:
            # The committed data mutation remains valid. Retention can be
            # retried by maintenance without weakening the journal proof.
            pass
        return outcome


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
    found = active_user()
    if found:
        return found
    fallback = get_user("local-user")
    if fallback:
        return fallback
    return {"userId": "local-user", "displayName": "Local ATLAS User", "email": "local.user@atlas.local", "role": "admin"}


def list_users() -> List[Dict[str, Any]]:
    return security_list_users()


def switch_user(user_id: str) -> Dict[str, Any]:
    raise HTTPException(status_code=410, detail="Development user switching was replaced by authentication.")


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
    allowed = {"owner", "editor"} if write else {"owner", "editor", "viewer", "auditor"}
    return any(grant.get("userId") == user_id and grant.get("role") in allowed for grant in grants)


def require_dataset(dataset_id: str, write: bool = False) -> Dict[str, Any]:
    registry = load_registry()
    dataset = next((item for item in registry.get("datasets", []) if item.get("datasetId") == dataset_id), None)
    if not dataset or dataset.get("archived"):
        raise HTTPException(status_code=404, detail="Dataset not found.")
    if not user_can_access(dataset, write=write):
        audit_event("access.denied", "dataset", dataset_id, "denied", reason="Dataset ACL denied")
        raise HTTPException(status_code=403, detail="You do not have access to this dataset.")
    audit_event("dataset.viewed", "dataset", dataset_id, "success")
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
    if not _valid_artifact_segment(dataset_id) or not _valid_artifact_segment(version_id):
        raise HTTPException(status_code=400, detail="Dataset artifact identifier is not valid.")
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
        "sourceInfo": dataset.get("sourceInfo") or {},
        "datasetRole": dataset.get("datasetRole") or dataset.get("sourceInfo", {}).get("datasetRole"),
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
    _mutation_storage_preflight()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.head(MAX_SAMPLE_ROWS).to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def write_csv_full(path: Path, df: pd.DataFrame) -> None:
    _mutation_storage_preflight()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def write_version_manifest(
    vdir: Path,
    *,
    dataset_id: str,
    version_id: str,
) -> Dict[str, Any]:
    """Bind an immutable version directory to checksummed artifact members."""

    artifact_names = (
        "metadata.json",
        "schema.json",
        "profile.json",
        "preview.json",
        "lineage.json",
        "data_full.csv",
        "data_sample.csv",
    )
    files = {}
    for artifact_name in artifact_names:
        artifact_path = vdir / artifact_name
        if not artifact_path.is_file():
            raise DatasetStoreMissingError(
                f"Dataset version artifact is missing before manifest creation: "
                f"{artifact_name}"
            )
        files[artifact_name] = {
            "sha256": sha256_file(artifact_path),
            "sizeBytes": artifact_path.stat().st_size,
        }
    manifest = {
        "formatVersion": 1,
        "kind": "atlas_dataset_version_manifest",
        "datasetId": dataset_id,
        "versionId": version_id,
        "createdAt": now_iso(),
        "contentHash": files["data_full.csv"]["sha256"],
        "schemaHash": files["schema.json"]["sha256"],
        "files": files,
    }
    write_json(vdir / "manifest.json", manifest, create_backup=False)
    return manifest


async def create_dataset_from_upload(
    file: UploadFile,
    name: Optional[str] = None,
    description: str = "",
    domain: str = "General",
    source_type: str = "upload",
) -> Dict[str, Any]:
    _mutation_storage_preflight()
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
    write_csv_full(vdir / "data_full.csv", df)
    write_csv_sample(vdir / "data_sample.csv", df)
    manifest = write_version_manifest(
        vdir,
        dataset_id=dataset_id,
        version_id=version_id,
    )
    version_summary = {
        "versionId": version_id,
        "createdAt": now_iso(),
        "createdBy": user.get("userId"),
        "originalFilename": filename,
        "hash": digest,
        "schemaHash": manifest["schemaHash"],
        "rowCount": int(df.shape[0]),
        "columnCount": int(df.shape[1]),
        "profilePath": str((vdir / "profile.json").relative_to(ARTIFACT_ROOT)),
        "previewPath": str((vdir / "preview.json").relative_to(ARTIFACT_ROOT)),
        "fullDataPath": str((vdir / "data_full.csv").relative_to(ARTIFACT_ROOT)),
        "samplePath": str((vdir / "data_sample.csv").relative_to(ARTIFACT_ROOT)),
        "manifestPath": str((vdir / "manifest.json").relative_to(ARTIFACT_ROOT)),
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
        "access": [{"userId": user.get("userId"), "role": "owner"}],
        "versions": [version_summary],
        "linkedProjects": [],
    }
    with library_write_lock(ARTIFACT_ROOT):
        registry = load_registry()
        registry["datasets"] = [
            item
            for item in registry.get("datasets", [])
            if item.get("datasetId") != dataset_id
        ] + [dataset]
        save_registry(registry)
    audit_event("dataset.created", "dataset", dataset_id, "success", metadata={"name": dataset_name, "versionId": version_id})
    summary = summarize_dataset(dataset)
    # Creation APIs return the exact version created by this operation. This
    # field is intentionally distinct from the descriptive `latestVersion`
    # projection, which must never drive activation.
    summary["created_dataset_version_id"] = version_id
    summary["createdDatasetVersionId"] = version_id
    summary["created_version"] = version_summary
    return summary


def create_dataset_from_dataframe(
    df: pd.DataFrame,
    name: str,
    description: str = "",
    domain: str = "Model Outputs",
    source_type: str = "scored_output",
    source_info: Optional[Dict[str, Any]] = None,
    dataset_role: str = "scored_output",
) -> Dict[str, Any]:
    _mutation_storage_preflight()
    if df.empty:
        raise HTTPException(status_code=400, detail="Scored output has no rows to register.")
    user = current_user()
    normalized = df.copy()
    normalized.columns = [str(column) for column in normalized.columns]
    content = normalized.to_csv(index=False).encode("utf-8")
    digest = sha256_bytes(content)
    ts = str(int(time.time() * 1000))
    dataset_name = (name or "Scored Output").strip()
    dataset_id = f"ds_{safe_slug(dataset_name)}_{digest[:8]}"
    version_id = f"v_{ts}_{digest[:8]}"
    if dataset_dir(dataset_id).exists():
        dataset_id = f"{dataset_id}_{ts[-5:]}"
    profile = profile_dataframe(normalized)
    vdir = version_dir(dataset_id, version_id)
    vdir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "datasetId": dataset_id,
        "versionId": version_id,
        "originalFilename": f"{safe_slug(dataset_name)}.csv",
        "datasetRole": dataset_role,
        "sourceInfo": source_info or {},
    }
    write_json(vdir / "metadata.json", metadata)
    write_json(vdir / "schema.json", {"columns": profile["schema"]})
    write_json(vdir / "profile.json", profile)
    write_json(vdir / "preview.json", {"rows": records_from_df(normalized.head(MAX_PREVIEW_ROWS)), "columns": [str(c) for c in normalized.columns]})
    write_json(
        vdir / "lineage.json",
        {
            "sourceType": source_type,
            "datasetRole": dataset_role,
            "registeredBy": user.get("userId"),
            "registeredAt": now_iso(),
            "hash": digest,
            "sourceInfo": source_info or {},
        },
    )
    write_csv_full(vdir / "data_full.csv", normalized)
    write_csv_sample(vdir / "data_sample.csv", normalized)
    manifest = write_version_manifest(
        vdir,
        dataset_id=dataset_id,
        version_id=version_id,
    )
    version_summary = {
        "versionId": version_id,
        "createdAt": now_iso(),
        "createdBy": user.get("userId"),
        "originalFilename": f"{safe_slug(dataset_name)}.csv",
        "hash": digest,
        "schemaHash": manifest["schemaHash"],
        "rowCount": int(normalized.shape[0]),
        "columnCount": int(normalized.shape[1]),
        "profilePath": str((vdir / "profile.json").relative_to(ARTIFACT_ROOT)),
        "previewPath": str((vdir / "preview.json").relative_to(ARTIFACT_ROOT)),
        "fullDataPath": str((vdir / "data_full.csv").relative_to(ARTIFACT_ROOT)),
        "samplePath": str((vdir / "data_sample.csv").relative_to(ARTIFACT_ROOT)),
        "manifestPath": str((vdir / "manifest.json").relative_to(ARTIFACT_ROOT)),
        "warnings": profile.get("warnings", []),
    }
    dataset = {
        "datasetId": dataset_id,
        "name": dataset_name,
        "description": description,
        "domain": domain,
        "sourceType": source_type,
        "datasetRole": dataset_role,
        "sourceInfo": source_info or {},
        "ownerUserId": user.get("userId"),
        "ownerDisplayName": user.get("displayName"),
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "archived": False,
        "access": [{"userId": user.get("userId"), "role": "owner"}],
        "versions": [version_summary],
        "linkedProjects": [],
    }
    with library_write_lock(ARTIFACT_ROOT):
        registry = load_registry()
        registry["datasets"] = [
            item
            for item in registry.get("datasets", [])
            if item.get("datasetId") != dataset_id
        ] + [dataset]
        save_registry(registry)
    audit_event(
        "dataset.scored_output.created",
        "dataset",
        dataset_id,
        "success",
        metadata={"name": dataset_name, "versionId": version_id, "rowCount": int(normalized.shape[0])},
    )
    summary = summarize_dataset(dataset)
    # Creation APIs return the exact version created by this operation. This
    # field is intentionally distinct from the descriptive `latestVersion`
    # projection, which must never drive activation.
    summary["created_dataset_version_id"] = version_id
    summary["createdDatasetVersionId"] = version_id
    summary["created_version"] = version_summary
    return summary


async def add_dataset_version(dataset_id: str, file: UploadFile) -> Dict[str, Any]:
    _mutation_storage_preflight()
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
    write_csv_full(vdir / "data_full.csv", df)
    write_csv_sample(vdir / "data_sample.csv", df)
    manifest = write_version_manifest(
        vdir,
        dataset_id=dataset_id,
        version_id=version_id,
    )
    version_summary = {
        "versionId": version_id,
        "createdAt": now_iso(),
        "createdBy": current_user().get("userId"),
        "originalFilename": filename,
        "hash": digest,
        "schemaHash": manifest["schemaHash"],
        "rowCount": int(df.shape[0]),
        "columnCount": int(df.shape[1]),
        "profilePath": str((vdir / "profile.json").relative_to(ARTIFACT_ROOT)),
        "previewPath": str((vdir / "preview.json").relative_to(ARTIFACT_ROOT)),
        "fullDataPath": str((vdir / "data_full.csv").relative_to(ARTIFACT_ROOT)),
        "samplePath": str((vdir / "data_sample.csv").relative_to(ARTIFACT_ROOT)),
        "manifestPath": str((vdir / "manifest.json").relative_to(ARTIFACT_ROOT)),
        "warnings": profile.get("warnings", []),
    }
    with library_write_lock(ARTIFACT_ROOT):
        registry = load_registry()
        for item in registry.get("datasets", []):
            if item.get("datasetId") == dataset_id:
                item.setdefault("versions", []).append(version_summary)
                item["updatedAt"] = now_iso()
                dataset = item
                break
        save_registry(registry)
    audit_event("dataset.version.created", "dataset_version", version_id, "success", metadata={"datasetId": dataset_id})
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
        "access": [{"userId": user.get("userId"), "role": "owner"}],
        "versions": [],
        "linkedProjects": [],
        "sourceInfo": payload.get("sourceInfo") or {},
    }
    with library_write_lock(ARTIFACT_ROOT):
        registry = load_registry()
        registry["datasets"] = registry.get("datasets", []) + [dataset]
        save_registry(registry)
    audit_event("dataset.created", "dataset", dataset_id, "success", metadata={"name": name, "metadataOnly": True})
    return summarize_dataset(dataset)


def read_version_artifact(dataset_id: str, version_id: str, name: str, default: Any) -> Any:
    dataset = require_dataset(dataset_id)
    if not _valid_artifact_segment(name) or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Dataset artifact name is not valid.")
    versions = {str(version.get("versionId")) for version in dataset.get("versions") or []}
    if version_id not in versions:
        raise HTTPException(status_code=404, detail="Dataset version was not found for this dataset.")
    path = version_dir(dataset_id, version_id) / name
    try:
        path.resolve().relative_to(version_dir(dataset_id, version_id).resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Dataset artifact path is not valid.") from exc
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
        if user_id not in valid_users or role not in {"viewer", "editor", "owner", "auditor"}:
            continue
        clean_grants.append({"userId": user_id, "role": role})
    with library_write_lock(ARTIFACT_ROOT):
        registry = load_registry()
        updated = None
        for item in registry.get("datasets", []):
            if item.get("datasetId") == dataset_id:
                owner_grant = {
                    "userId": item.get("ownerUserId"),
                    "role": "owner",
                }
                item["access"] = [owner_grant] + [
                    grant
                    for grant in clean_grants
                    if grant.get("userId") != owner_grant["userId"]
                ]
                item["updatedAt"] = now_iso()
                updated = item
                break
        save_registry(registry)
    audit_event("dataset.shared", "dataset", dataset_id, "success", metadata={"grants": clean_grants})
    return summarize_dataset(updated or require_dataset(dataset_id))


def dataset_access(dataset_id: str) -> List[Dict[str, str]]:
    dataset = require_dataset(dataset_id)
    return list(dataset.get("access") or [])


def grant_dataset_access(dataset_id: str, user_id: str, role: str) -> Dict[str, Any]:
    if role not in {"owner", "editor", "viewer", "auditor"}:
        raise HTTPException(status_code=400, detail="Unsupported dataset permission.")
    dataset = require_dataset(dataset_id, write=True)
    grants = [grant for grant in dataset.get("access", []) if grant.get("userId") != user_id]
    grants.append({"userId": user_id, "role": role})
    return share_dataset(dataset_id, grants)


def revoke_dataset_access(dataset_id: str, user_id: str) -> Dict[str, Any]:
    require_dataset(dataset_id, write=True)
    with library_write_lock(ARTIFACT_ROOT):
        registry = load_registry()
        updated = None
        for item in registry.get("datasets", []):
            if item.get("datasetId") == dataset_id:
                if item.get("ownerUserId") == user_id:
                    raise HTTPException(
                        status_code=400,
                        detail="Dataset owner access cannot be revoked.",
                    )
                item["access"] = [
                    grant
                    for grant in item.get("access", [])
                    if grant.get("userId") != user_id
                ]
                item["updatedAt"] = now_iso()
                updated = item
                break
        save_registry(registry)
    audit_event("dataset.access.revoked", "dataset", dataset_id, "success", metadata={"targetUserId": user_id})
    return summarize_dataset(updated or require_dataset(dataset_id))


def archive_dataset(dataset_id: str) -> Dict[str, Any]:
    require_dataset(dataset_id, write=True)
    with library_write_lock(ARTIFACT_ROOT):
        registry = load_registry()
        updated = None
        for item in registry.get("datasets", []):
            if item.get("datasetId") == dataset_id:
                item["archived"] = True
                item["updatedAt"] = now_iso()
                updated = item
                break
        save_registry(registry)
    audit_event("dataset.archived", "dataset", dataset_id, "success")
    return summarize_dataset(updated or require_dataset(dataset_id))


def link_project(project_id: str, dataset_id: str, version_id: str, role: str = "modeling") -> Dict[str, Any]:
    dataset = require_dataset(dataset_id)
    resolved_version = str(version_id or "").strip()
    if not resolved_version:
        raise HTTPException(
            status_code=422,
            detail="An exact Dataset Library versionId is required; ATLAS will not select the latest version automatically.",
        )
    if not any(
        str(version.get("versionId") or "") == resolved_version
        for version in (dataset.get("versions") or [])
        if isinstance(version, dict)
    ):
        other_dataset_owns_version = any(
            str(version.get("versionId") or "") == resolved_version
            for item in load_registry().get("datasets", [])
            if isinstance(item, dict) and item.get("datasetId") != dataset_id
            for version in (item.get("versions") or [])
            if isinstance(version, dict)
        )
        raise HTTPException(
            status_code=409 if other_dataset_owns_version else 404,
            detail=(
                "The requested version belongs to another dataset."
                if other_dataset_owns_version
                else "Dataset version not found."
            ),
        )
    link = {
        "projectId": project_id,
        "datasetId": dataset_id,
        "versionId": resolved_version,
        "datasetRole": role,
        "linkedAt": now_iso(),
        "linkedBy": current_user().get("userId"),
    }
    def apply_link(
        registry: Dict[str, Any],
        links: Dict[str, Any],
    ) -> Dict[str, Any]:
        links["links"] = [
            item
            for item in links.get("links", [])
            if not (
                item.get("projectId") == project_id
                and item.get("datasetId") == dataset_id
                and item.get("datasetRole") == role
            )
        ] + [link]
        matched_dataset = False
        for item in registry.get("datasets", []):
            if item.get("datasetId") == dataset_id:
                matched_dataset = True
                if not any(
                    str(version.get("versionId") or "") == resolved_version
                    for version in (item.get("versions") or [])
                    if isinstance(version, dict)
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "The requested Dataset Library version changed "
                            "before the project link could be recorded."
                        ),
                    )
                linked = [
                    existing
                    for existing in item.get("linkedProjects", [])
                    if existing.get("projectId") != project_id
                ]
                linked.append(
                    {
                        "projectId": project_id,
                        "versionId": resolved_version,
                        "datasetRole": role,
                    }
                )
                item["linkedProjects"] = linked
                item["updatedAt"] = now_iso()
                break
        if not matched_dataset:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The requested Dataset Library asset changed before the "
                    "project link could be recorded."
                ),
            )
        return link

    return _mutate_registry_and_links_transaction(
        operation_type="link_project",
        reason="Before linking an exact Dataset Library version to a project",
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_version_id=resolved_version,
        mutator=apply_link,
    )


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
    def apply_unlink(
        registry: Dict[str, Any],
        links: Dict[str, Any],
    ) -> Dict[str, Any]:
        before = len(links.get("links", []))
        links["links"] = [
            item
            for item in links.get("links", [])
            if not (
                item.get("projectId") == project_id
                and item.get("datasetId") == dataset_id
            )
        ]
        for item in registry.get("datasets", []):
            if item.get("datasetId") == dataset_id:
                linked_before = item.get("linkedProjects", [])
                linked_after = [
                    link
                    for link in linked_before
                    if link.get("projectId") != project_id
                ]
                if linked_after != linked_before:
                    item["linkedProjects"] = linked_after
                    item["updatedAt"] = now_iso()
        removed = before - len(links.get("links", []))
        return {"ok": True, "removed": removed}

    return _mutate_registry_and_links_transaction(
        operation_type="unlink_project_dataset",
        reason="Before removing a Dataset Library project link",
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_version_id=None,
        mutator=apply_unlink,
    )


def unlink_all_project_datasets(project_id: str) -> Dict[str, int]:
    """Remove every dataset link for `project_id` -- the project-deletion half of the
    Phase 7 retention rule (dataset lifecycle audit): deleting a project must remove
    ITS links, never the shared Library assets or other projects' links to them.
    Mirrors session_checkpoint.discard_modeling_scopes's "GC on delete" pattern.
    """
    def apply_unlink_all(
        registry: Dict[str, Any],
        links: Dict[str, Any],
    ) -> Dict[str, int]:
        remaining = [
            item
            for item in links.get("links", [])
            if item.get("projectId") != project_id
        ]
        removed = len(links.get("links", [])) - len(remaining)
        links["links"] = remaining
        if removed:
            for item in registry.get("datasets", []):
                linked = item.get("linkedProjects") or []
                if any(link.get("projectId") == project_id for link in linked):
                    item["linkedProjects"] = [
                        link
                        for link in linked
                        if link.get("projectId") != project_id
                    ]
                    item["updatedAt"] = now_iso()
        return {"removedLinks": removed}

    result = _mutate_registry_and_links_transaction(
        operation_type="unlink_all_project_datasets",
        reason="Before removing every Dataset Library link for a project",
        project_id=project_id,
        dataset_id="*",
        dataset_version_id=None,
        mutator=apply_unlink_all,
    )
    removed = result["removedLinks"]
    if removed:
        audit_event(
            "dataset.project_links.removed",
            "project",
            project_id,
            "success",
            metadata={"removedLinks": removed},
        )
    return result


def find_similar_datasets(
    name: str,
    target: Optional[str] = None,
    row_count: Optional[int] = None,
    column_count: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Reviewable duplicate suggestions for the Data Acquisition registration flow
    (Phase 4 item 9): candidates the CALLER can already see, ranked by how many of
    name/target/row-count/column-count match -- never auto-selected, never used to
    silently substitute a different asset for the one the user is registering."""
    candidates = list_accessible_datasets()
    needle = (name or "").strip().lower()
    scored: List[tuple[int, Dict[str, Any]]] = []
    for dataset in candidates:
        latest = dataset.get("latestVersion") or {}
        score = 0
        if needle and needle == str(dataset.get("name") or "").strip().lower():
            score += 2
        elif needle and needle in str(dataset.get("name") or "").strip().lower():
            score += 1
        if target and target == (dataset.get("sourceInfo") or {}).get("target"):
            score += 1
        if row_count is not None and latest.get("rowCount") == row_count:
            score += 1
        if column_count is not None and latest.get("columnCount") == column_count:
            score += 1
        if score > 0:
            scored.append((score, dataset))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [dataset for _, dataset in scored[:5]]


def register_workspace_dataset(
    df: pd.DataFrame,
    name: str,
    project_id: str,
    description: str = "",
    domain: str = "General",
    tags: Optional[List[str]] = None,
    target: Optional[str] = None,
    source_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Register the CURRENT project workspace dataset (already-uploaded DATASTORE
    state, transformed or not) as a durable, versioned Dataset Library asset, and
    link it to the originating project. This is the previously-missing path the
    dataset lifecycle audit exists to add: `create_metadata_only_dataset` (the old
    `/datasets/register`) never attached real data, so nothing an analyst uploaded
    into a project workspace could become a reusable asset without going through
    the separate, unrelated direct-to-Library upload endpoint.
    """
    source_info = {
        "projectId": project_id,
        "target": target,
        "tags": tags or [],
        "originalSource": source_meta or {},
    }
    dataset = create_dataset_from_dataframe(
        df,
        name=name,
        description=description,
        domain=domain,
        source_type="workspace_upload",
        source_info=source_info,
        dataset_role="development",
    )
    version_id = str(
        dataset.get("created_dataset_version_id")
        or dataset.get("createdDatasetVersionId")
        or ""
    )
    if version_id:
        link_project(project_id, dataset["datasetId"], version_id, "development")
    return dataset


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
            "detail": "Configured Dataset Library storage is reachable.",
        },
        {
            "id": "registry",
            "label": "Dataset registry",
            "status": "pass" if isinstance(datasets, list) else "fail",
            "detail": f"{len(datasets)} total dataset records.",
        },
        {
            "id": "users",
            "label": "Authenticated users",
            "status": "pass" if list_users() else "fail",
            "detail": f"{len(list_users())} authenticated user records.",
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
    try:
        security = security_diagnostics()
        for check in security.get("checks", []):
            checks.append(
                {
                    "id": f"security_{check.get('id')}",
                    "label": f"Security: {check.get('label')}",
                    "status": check.get("status", "warning"),
                    "detail": check.get("detail", ""),
                }
            )
    except Exception as exc:
        checks.append(
            {
                "id": "security_diagnostics",
                "label": "Security diagnostics",
                "status": "fail",
                "detail": f"Security diagnostics failed: {exc}",
            }
        )
    try:
        from ..analytics.analytics_store import diagnostics as analytics_diagnostics

        analytics = analytics_diagnostics()
        for check in analytics.get("checks", []):
            checks.append(
                {
                    "id": f"analytics_{check.get('id')}",
                    "label": f"Analytics: {check.get('label')}",
                    "status": check.get("status", "warning"),
                    "detail": check.get("detail", ""),
                }
            )
    except Exception as exc:
        checks.append(
            {
                "id": "analytics_diagnostics",
                "label": "Analytics diagnostics",
                "status": "fail",
                "detail": f"Analytics diagnostics failed: {exc}",
            }
        )
    try:
        from ..charts.chart_store import chart_diagnostics

        charts = chart_diagnostics()
        for check in charts.get("checks", []):
            checks.append(
                {
                    "id": f"chart_studio_{check.get('id')}",
                    "label": f"Chart Studio: {check.get('label')}",
                    "status": check.get("status", "warning"),
                    "detail": check.get("detail", ""),
                }
            )
    except Exception as exc:
        checks.append(
            {
                "id": "chart_studio_diagnostics",
                "label": "Chart Studio diagnostics",
                "status": "fail",
                "detail": f"Chart Studio diagnostics failed: {exc}",
            }
        )
    return {
        "ok": True,
        "generatedAt": now_iso(),
        "currentUser": current_user(),
        "artifactRoot": "Configured (path redacted)",
        "datasetCount": len(active),
        "archivedCount": len(datasets) - len(active),
        "projectLinkCount": len(links.get("links", [])),
        "checks": checks,
    }
