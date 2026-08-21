"""Server-side Gen-3 dataset registry, project binding, run authority, and governed execution
(Phase 7A.1 → hardened in 7A.3). Realizes UI = ACTIVE BINDING = RUN AUTHORITY = OBJECT RECEIPT =
TRAINING = RESULT, fail-closed on any mismatch — additively, WITHOUT touching the D3/C4-serving path.

7A.3 hardening: safe opaque project storage keys (no raw projectId in a path, A2-02); generation-specific
contract bundles (A2-04); object-integrity verification before load (A2-05); binding revision / CAS /
supersession (A2-06); code+worktree+environment identity recomputed at execution (A2-11); complete
contract/receipt echo in result evidence (A2-10); strict resource bounds on model hyperparameters
(A2-13). Callers pass an ALREADY-AUTHORIZED canonical project id (the route enforces the project ACL).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pyarrow.parquet as pq
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_modeling import gen3_contracts as GC
from ..sports_modeling.feature_contract import C_GRID, FEATURE_NAMES
from ..sports_modeling.metrics import PA_CLASS_ORDER, encode_labels, evaluate_multiclass
from ..sports_modeling.training import (
    DEFAULT_MAX_ITER, DEFAULT_TOLERANCE, FoldPreprocessor, chronological_date_atomic_split,
)
from .engine import CockpitError, REPO_ROOT, RUNTIME_ROOT, _feature_view_path

GEN3_ROOT = RUNTIME_ROOT / "sports-modeling" / "mlb-pa-gen3-v2"
GEN2_ROOT = RUNTIME_ROOT / "sports-modeling" / "mlb-pa-gen2-v1"
STATE_ROOT = GEN3_ROOT / "authority"
ASP_REGISTRY = RUNTIME_ROOT / "artifacts" / "datasets" / "registry.json"
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,200}$")
_OPAQUE_RE = re.compile(r"^[0-9a-f]{32}$")
_ALLOWED_FAMILIES = {"governed_logistic", "governed_hgb"}


# Object-open instrumentation (Gate 13): every read of a registered object parquet is recorded here so a
# hermetic test can behaviorally prove the sealed 2025 object is opened 0 times by the ordinary workflow.
_OBJECT_OPEN_LOG: list[str] = []


def reset_object_open_log() -> None:
    _OBJECT_OPEN_LOG.clear()


def object_open_log() -> list[str]:
    return list(_OBJECT_OPEN_LOG)


def _record_open(path) -> Path:
    p = Path(path)
    _OBJECT_OPEN_LOG.append(str(p.resolve()))
    return p


class AuthorityError(CockpitError):
    """Fail-closed authority/binding/run violation (route maps to HTTP 422)."""


class StaleAuthorityError(AuthorityError):
    """A superseded binding or drifted code/environment was used (route maps to HTTP 409)."""


# --------------------------------------------------------------------------- safe storage (A2-02)
def _project_key(project_id: str) -> str:
    """Opaque, deterministic storage key derived from the AUTHORIZED canonical project id. Never a raw
    projectId in a filesystem path — no separators, drive letters, dots, or reparse semantics survive."""
    cleaned = str(project_id or "").strip()
    if not cleaned:
        raise AuthorityError("project id is required")
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:32]


def _state(project_id: str, *parts: str) -> Path:
    """Resolve a path strictly beneath the single fixed STATE_ROOT/<project-key>/ — containment checked."""
    root = STATE_ROOT.resolve()
    p = (root / _project_key(project_id)).joinpath(*parts).resolve()
    if root != p and root not in p.parents:
        raise AuthorityError("resolved authority path escapes the fixed root")
    return p


# --------------------------------------------------------------------------- identity helpers
def _env_sha() -> str:
    import pandas, sklearn, pyarrow
    return sha256_bytes(canonical_json_bytes({"python": sys.version.split()[0], "pyarrow": pyarrow.__version__,
                                              "numpy": np.__version__, "pandas": pandas.__version__, "sklearn": sklearn.__version__}))


def _code_identity() -> dict[str, Any]:
    """Current git HEAD + a CONTENT digest of the worktree diff (not merely a dirty boolean, A2-11)."""
    try:
        rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
        diff = subprocess.check_output(["git", "diff", "HEAD"], cwd=REPO_ROOT)
        untracked = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT)
        worktree_sha = hashlib.sha256(diff + b"\x00" + untracked).hexdigest()
        return {"codeRevision": rev, "worktreeContentSha256": worktree_sha, "dirty": bool(diff.strip() or untracked.strip())}
    except Exception:
        return {"codeRevision": "UNKNOWN", "worktreeContentSha256": "UNKNOWN", "dirty": True}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".tmp-{uuid.uuid4().hex}"
    tmp.write_bytes(canonical_json_bytes(payload))
    os.replace(tmp, path)


# --------------------------------------------------------------------------- catalog (Gate 4/7: registry-resolved; opens NO modeling/sealed object on ordinary reads)
def _registration(root: Path) -> dict[str, Any]:
    reg_path = root / "registration.json"
    if not reg_path.is_file():
        raise AuthorityError(f"dataset registration not found: {reg_path}")
    return _read_json(reg_path)


def _object_path(root: Path, sha: str, object_kind: str) -> str:
    return str(root / "objects" / "sha256" / sha / f"{object_kind}.parquet")


def _gen2_catalog_entries() -> list[dict[str, Any]]:
    """Gen-2 research (2023-2024) + sealed (2025) resolved from the immutable Gen-2 registration. The old
    combined 2023-2025 object is NEVER opened here (physical seal, Gate 7)."""
    reg = _registration(GEN2_ROOT)
    ps = {int(k): int(v) for k, v in reg.get("perSeasonRows", {}).items()}
    r = reg["research"]
    research = {
        "datasetVersionId": reg["registrationId"], "label": "MLB Gen-2 Research View (2023-2024)",
        "generation": "GEN2", "objectKind": "gen2-research", "status": "GOVERNED_RESEARCH_DATASET", "selectable": True,
        "logicalContentSha256": r["logicalContentSha256"], "physicalParquetSha256": r["physicalParquetSha256"],
        "schemaSha256": r.get("schemaSha256"), "objectPath": _object_path(GEN2_ROOT, r["logicalContentSha256"], "gen2-research"),
        "contractBundleSha256": reg["contractBundleSha256"], "contracts": reg["contracts"],
        "seasons": [2023, 2024], "developmentSeasons": [2023], "validationSeason": 2024, "sealedSeasons": [2025],
        "developmentRows": ps.get(2023, 0), "validationRows": ps.get(2024, 0), "sealedRows": ps.get(2025, 0),
        "perSeasonRows": ps, "rows": r["rows"], "featureCount": len(FEATURE_NAMES), "target": "outcome",
        "sourceDatasetId": GC.PARENT_DATASET_ID, "sealMigrationAuditSha256": reg.get("sealMigrationAuditSha256"),
    }
    s = reg["sealed2025"]
    sealed = {
        "datasetVersionId": f"mlb-pa-gen2-sealed-2025:sha256:{s['logicalContentSha256']}",
        "label": "MLB Gen-2 Sealed 2025 Frozen Final", "generation": "GEN2_SEALED", "objectKind": "gen2-sealed-2025",
        "status": "SEALED_OOT_RESTRICTED", "selectable": False, "logicalContentSha256": s["logicalContentSha256"],
        "seasons": [2025], "developmentSeasons": [], "validationSeason": None, "sealedSeasons": [2025],
        "rows": s["rows"], "target": "outcome",
        "restriction": "NOT selectable for ordinary development; structural registration/lineage only",
    }
    return [research, sealed]


def _gen3_catalog_entries() -> list[dict[str, Any]]:
    reg = _registration(GEN3_ROOT)
    r = reg["research"]
    ps = {int(k): int(v) for k, v in reg.get("perSeasonRows", {}).items()}
    research = {
        "datasetVersionId": reg["registrationId"], "label": "MLB Gen-3 Base Research View (2021-2024)",
        "generation": "GEN3", "objectKind": "research", "status": "GOVERNED_RESEARCH_DATASET", "selectable": True,
        "logicalContentSha256": r["logicalContentSha256"], "physicalParquetSha256": r["physicalParquetSha256"],
        "schemaSha256": r.get("schemaSha256"), "objectPath": _object_path(GEN3_ROOT, r["logicalContentSha256"], "research"),
        "contractBundleSha256": reg["contractBundleSha256"], "contracts": reg["contracts"],
        "seasons": [2021, 2022, 2023, 2024], "developmentSeasons": [2021, 2022, 2023], "validationSeason": 2024,
        "sealedSeasons": [2025],
        "developmentRows": ps.get(2021, 0) + ps.get(2022, 0) + ps.get(2023, 0),
        "validationRows": ps.get(2024, 0), "sealedRows": reg["sealed2025"]["rows"], "perSeasonRows": ps,
        "rows": r["rows"], "featureCount": len(FEATURE_NAMES), "target": "outcome",
        "quarantineLedgerSha256": reg.get("quarantineLedgerSha256"), "quarantineTotal": reg.get("quarantineTotal"),
        "sourceDatasetId": GC.PARENT_DATASET_ID,
    }
    s = reg["sealed2025"]
    sealed = {
        "datasetVersionId": f"mlb-pa-gen3-sealed-2025:sha256:{s['logicalContentSha256']}",
        "label": "MLB Gen-3 Sealed 2025 OOT Evidence", "generation": "GEN3_SEALED", "objectKind": "sealed-2025",
        "status": "SEALED_OOT_RESTRICTED", "selectable": False, "logicalContentSha256": s["logicalContentSha256"],
        "seasons": [2025], "developmentSeasons": [], "validationSeason": None, "sealedSeasons": [2025],
        "rows": s["rows"], "target": "outcome",
        "restriction": "NOT selectable for ordinary development; structural registration/lineage only",
    }
    return [research, sealed]


def catalog() -> list[dict[str, Any]]:
    """The canonical modeling-dataset catalog, resolved ONLY from immutable registrations. It opens no
    modeling or sealed object and reads no target rows (Gate 4/7)."""
    return [*_gen2_catalog_entries(), *_gen3_catalog_entries()]


def register_gen3() -> dict[str, Any]:
    """Explicit canonical-registry write (admin/build action). Consumers resolve dataset versions from the
    per-generation registrations (`catalog()`); this snapshot is the authoritative external listing and is
    rewritten to EXACTLY the current catalog. Superseded/lineage objects remain immutable on disk but are
    not resolvable by any ordinary route (Gate 1/4)."""
    reg = {"schemaVersion": "ASP_DATASET_REGISTRY_V2",
           "updatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "datasets": [{k: v for k, v in entry.items() if k != "objectPath"} for entry in catalog()]}
    _write_json_atomic(ASP_REGISTRY, reg)
    return {"registered": [d["datasetVersionId"] for d in reg["datasets"]]}


def _resolve_version(dataset_version_id: str) -> dict[str, Any]:
    if not isinstance(dataset_version_id, str) or not _ID_RE.match(dataset_version_id):
        raise AuthorityError("invalid dataset version id")
    for entry in catalog():
        if entry["datasetVersionId"] == dataset_version_id:
            return entry
    raise AuthorityError(f"dataset version not found in registry: {dataset_version_id}")


# --------------------------------------------------------------------------- physical sealed-data policy (Gate 7)
def _reject_sealed_target_read(entry: Mapping[str, Any]) -> None:
    """Ordinary scientist execution/catalog resolvers may NEVER open a sealed object's target rows. Only an
    explicit admin/build authority (the publisher) reads sealed target data."""
    gen = str(entry.get("generation", ""))
    if gen.endswith("_SEALED") or not entry.get("selectable", False) or not entry.get("objectPath"):
        raise AuthorityError("SEAL VIOLATION: ordinary resolver may not open a sealed / non-selectable object")


# --------------------------------------------------------------------------- object integrity (Gate 6: complete receipt verification)
_VERIFIED_OBJECT_CACHE: dict[tuple, dict[str, Any]] = {}


def _verify_object(entry: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Independently verify the exact registered content-addressed RESEARCH object before its modeling rows
    are used. Fail-closed before any row is returned (Gate 6): path/link escape, physical SHA,
    publisher-compatible schema SHA (incl. nullability), round-trip-stable LOGICAL content SHA, embedded
    Parquet identity metadata (object kind / bundle / logical sha), generation-correct contract bundle and
    all contract ids, row count, exact season set (no sealed season leaked), target column, and governed
    feature names. Ordinary callers may only verify research objects (Gate 7). Verified receipts are cached
    by (resolved path, file stat, expected logical sha); any file change invalidates the cache."""
    from ..sports_modeling.gen3_publish import logical_content_sha as _pub_logical, _schema_sha as _pub_schema
    _reject_sealed_target_read(entry)
    path = Path(entry["objectPath"])
    if path.is_symlink() or not path.is_file():
        raise AuthorityError("registered object missing or is a link")
    st = path.stat()
    cache_key = (str(path.resolve()), st.st_mtime_ns, st.st_size, entry["logicalContentSha256"])
    cached = _VERIFIED_OBJECT_CACHE.get(cache_key)
    if cached is not None:
        _record_open(path)  # record the authorized (cached) open for instrumentation
        return path, dict(cached)
    _record_open(path)
    physical = hashlib.sha256(path.read_bytes()).hexdigest()
    if entry.get("physicalParquetSha256") and physical != entry["physicalParquetSha256"]:
        raise AuthorityError("registered object bytes differ from the registry receipt (tampered)")
    table = pq.read_table(path)
    md = table.schema.metadata or {}
    rows = table.num_rows
    if entry.get("rows") and rows != entry["rows"]:
        raise AuthorityError("registered object row count differs from the registry")
    schema_sha = _pub_schema(table)
    if entry.get("schemaSha256") and schema_sha != entry["schemaSha256"]:
        raise AuthorityError("registered object schema digest differs from the registry")
    bundle = entry.get("contractBundleSha256") or GC.contract_bundle_sha_for(entry["generation"])
    logical = _pub_logical(table.replace_schema_metadata(None), contract_bundle_sha=bundle, schema_sha=schema_sha)
    if logical != entry["logicalContentSha256"]:
        raise AuthorityError("registered object LOGICAL content sha does not verify (tampered/mismatched)")

    def _m(k: str) -> str:
        return (md.get(k.encode()) or b"").decode()
    if _m("logicalContentSha256") and _m("logicalContentSha256") != entry["logicalContentSha256"]:
        raise AuthorityError("embedded logicalContentSha256 disagrees with the registry")
    if _m("contractBundleSha256") and _m("contractBundleSha256") != bundle:
        raise AuthorityError("embedded contractBundleSha256 disagrees with the registry")
    if _m("objectKind") and entry.get("objectKind") and _m("objectKind") != entry["objectKind"]:
        raise AuthorityError("embedded objectKind disagrees with the registry")
    if bundle != GC.contract_bundle_sha_for(entry["generation"]):
        raise AuthorityError("registered contract bundle is not the generation-correct bundle")
    contracts = GC.contracts_for_generation(entry["generation"])
    if entry.get("contracts"):
        for name, cid in {k: v["id"] for k, v in contracts.items()}.items():
            if entry["contracts"].get(name) != cid:
                raise AuthorityError(f"registered contract '{name}' is not the generation-correct identity")
    seasons = sorted(set(int(s) for s in table.column("season").to_pylist())) if "season" in table.schema.names else []
    if entry.get("seasons") and seasons != sorted(set(entry["seasons"])):
        raise AuthorityError("registered object season set differs from the registry")
    leaked = set(int(s) for s in (entry.get("sealedSeasons") or [])) & set(seasons)
    if leaked:
        raise AuthorityError(f"SEAL VIOLATION: sealed season(s) {sorted(leaked)} present in a research object")
    names = set(table.schema.names)
    if "outcome" not in names:
        raise AuthorityError("target column 'outcome' absent from the registered object")
    missing = [f for f in FEATURE_NAMES if f not in names]
    if missing:
        raise AuthorityError(f"registered object missing governed feature columns: {missing[:5]}")
    receipt = {"physicalParquetSha256": physical, "logicalContentSha256": logical, "schemaSha256": schema_sha,
               "contractBundleSha256": bundle, "objectKind": entry.get("objectKind"), "rows": rows,
               "seasons": seasons, "generation": entry["generation"], "featureCount": len(FEATURE_NAMES),
               "verifiedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _VERIFIED_OBJECT_CACHE[cache_key] = dict(receipt)
    return path, receipt


# --------------------------------------------------------------------------- binding lifecycle (A2-06)
def _active_pointer(project_id: str) -> dict[str, Any] | None:
    ptr = _state(project_id, "active-binding.json")
    return _read_json(ptr) if ptr.is_file() else None


def create_binding(*, actor: str, project_id: str, dataset_version_id: str,
                   expected_content_sha: str | None = None, expected_revision: int | None = None) -> dict[str, Any]:
    entry = _resolve_version(dataset_version_id)
    if not entry.get("selectable", False):
        raise AuthorityError("dataset version is not selectable for ordinary development")
    if expected_content_sha and expected_content_sha != entry["logicalContentSha256"]:
        raise AuthorityError("client-asserted content sha does not match the registered object")
    _verify_object(entry)
    contracts = GC.contracts_for_generation(entry["generation"])
    prev = _active_pointer(project_id)
    if expected_revision is not None and (prev or {}).get("revision", 0) != expected_revision:
        raise StaleAuthorityError("binding CAS failed: expected revision does not match the active binding")
    revision = int((prev or {}).get("revision", 0)) + 1
    binding_id = uuid.uuid4().hex
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if prev:  # supersede the previous active binding revision (A2-06)
        prev_path = _state(project_id, "bindings", f"{prev['bindingId']}.json")
        if prev_path.is_file():
            pb = _read_json(prev_path)
            pb.update({"status": "SUPERSEDED", "supersededBy": binding_id, "supersededAt": now})
            _write_json_atomic(prev_path, pb)
    binding = {
        "schemaVersion": "PROJECT_MODELING_DATASET_BINDING_V1", "bindingId": binding_id, "revision": revision,
        "status": "ACTIVE", "actor": actor, "projectId": project_id,
        "datasetVersionId": dataset_version_id, "datasetContentSha256": entry["logicalContentSha256"],
        "generation": entry["generation"],
        "contractBundleSha256": GC.contract_bundle_sha_for(entry["generation"]),
        "targetContractId": contracts["target"]["id"], "targetContractSha256": contracts["target"]["sha256"],
        "populationContractId": contracts["population"]["id"], "populationContractSha256": contracts["population"]["sha256"],
        "temporalContractId": contracts["temporal"]["id"], "temporalContractSha256": contracts["temporal"]["sha256"],
        "featureContractId": contracts["baseFeature"]["id"], "featureContractSha256": contracts["baseFeature"]["sha256"],
        "preprocessingContractId": contracts["preprocessing"]["id"], "preprocessingContractSha256": contracts["preprocessing"]["sha256"],
        "knowledgeTimeContractId": contracts["knowledgeTime"]["id"], "knowledgeTimeContractSha256": contracts["knowledgeTime"]["sha256"],
        "developmentSeasons": entry["developmentSeasons"], "validationSeason": entry["validationSeason"],
        "sealedSeasons": entry["sealedSeasons"], "createdAt": now,
    }
    _write_json_atomic(_state(project_id, "bindings", f"{binding_id}.json"), binding)
    _write_json_atomic(_state(project_id, "active-binding.json"), {"bindingId": binding_id, "revision": revision})
    _invalidate_downstream(project_id, binding_id)  # A2-08/A2-09
    return binding


def get_binding(*, project_id: str, binding_id: str) -> dict[str, Any]:
    if not _OPAQUE_RE.match(binding_id or ""):
        raise AuthorityError("invalid binding id")
    path = _state(project_id, "bindings", f"{binding_id}.json")
    if not path.is_file():
        raise AuthorityError("binding not found for project")
    return _read_json(path)


def active_binding(*, project_id: str) -> dict[str, Any] | None:
    ptr = _active_pointer(project_id)
    if not ptr:
        return None
    b = get_binding(project_id=project_id, binding_id=ptr["bindingId"])
    return b if b.get("status") == "ACTIVE" else None


def binding_population(*, project_id: str) -> dict[str, Any] | None:
    """Generation-aware population authority for the active binding (Gate 1/2/3). Derived purely from the
    binding + registry catalog + generation contracts — no object is opened, so the sealed 2025 object is
    never touched and no 2025 distribution is exposed."""
    b = active_binding(project_id=project_id)
    if b is None:
        return None
    entry = _resolve_version(b["datasetVersionId"])
    contracts = GC.contracts_for_generation(b["generation"])
    kt = contracts["knowledgeTime"]["payload"]
    dev_rows = int(entry.get("developmentRows") or 0)
    val_rows = int(entry.get("validationRows") or 0)
    waterfall = [
        {"stage": "Registered source evidence", "rows": int(entry.get("rows") or 0), "kind": "source"},
        {"stage": f"Development ({','.join(str(s) for s in entry['developmentSeasons'])})", "rows": dev_rows, "kind": "development"},
        {"stage": f"Validation ({entry['validationSeason']})", "rows": val_rows, "kind": "validation"},
        {"stage": f"Sealed ({','.join(str(s) for s in entry['sealedSeasons'])})", "rows": int(entry.get("sealedRows") or 0), "kind": "sealed"},
    ]
    # Gate 23: per-season rows are the REGISTERED receipts, never fabricated by equal division.
    per_season = {int(k): int(v) for k, v in (entry.get("perSeasonRows") or {}).items()}
    seasons = [
        *[{"season": s, "role": "DEVELOPMENT", "rows": per_season.get(int(s))} for s in entry["developmentSeasons"]],
        {"season": entry["validationSeason"], "role": "VALIDATION", "rows": per_season.get(int(entry["validationSeason"]), val_rows)},
        *[{"season": s, "role": "SEALED", "rows": None} for s in entry["sealedSeasons"]],   # sealed rows not exposed as a modeling season
    ]
    return {
        "bindingId": b["bindingId"], "bindingRevision": b["revision"], "generation": b["generation"],
        "label": entry.get("label"), "datasetVersionId": b["datasetVersionId"],
        "registrationId": b["datasetVersionId"].split(":")[0], "datasetContentSha256": b["datasetContentSha256"],
        "featureViewId": b.get("featureViewId") or b["datasetVersionId"], "target": "outcome", "targetClasses": list(PA_CLASS_ORDER),
        "classCount": len(PA_CLASS_ORDER), "targetContractId": b["targetContractId"], "targetContractSha256": b["targetContractSha256"],
        "developmentSeasons": entry["developmentSeasons"], "developmentRows": dev_rows,
        "validationSeason": entry["validationSeason"], "validationRows": val_rows,
        "sealedSeasons": entry["sealedSeasons"], "sealedState": "SEALED / UNAVAILABLE TO DEVELOPMENT",
        "featureCount": int(entry.get("featureCount") or 0), "registeredRows": int(entry.get("rows") or 0),
        "temporalContractId": b["temporalContractId"], "temporalContractSha256": b["temporalContractSha256"],
        "preprocessingContractId": b["preprocessingContractId"], "preprocessingContractSha256": b["preprocessingContractSha256"],
        "knowledgeTimeContractId": b["knowledgeTimeContractId"], "knowledgeTimeSafetyClass": kt.get("safetyClass", "CONDITIONAL_PRE_TERMINAL_PA_STATE"),
        "featureContractId": b["featureContractId"], "populationContractId": b["populationContractId"],
        "contractBundleSha256": b.get("contractBundleSha256"),
        "quarantineTotal": entry.get("quarantineTotal"), "quarantineLedgerSha256": entry.get("quarantineLedgerSha256"),
        "sourceDatasetId": entry.get("sourceDatasetId") or GC.PARENT_DATASET_ID,
        "waterfall": waterfall, "seasons": seasons,
    }


def _require_active_binding(project_id: str, binding_id: str) -> dict[str, Any]:
    b = get_binding(project_id=project_id, binding_id=binding_id)
    ptr = _active_pointer(project_id) or {}
    if b.get("status") != "ACTIVE" or ptr.get("bindingId") != binding_id:
        raise StaleAuthorityError("binding is superseded or is not the active binding revision")
    return b


# --------------------------------------------------------------------------- downstream invalidation (A2-08/09)
def _invalidate_downstream(project_id: str, new_binding_id: str) -> None:
    """On a dataset binding change, the active candidate + downstream review become STALE server-side."""
    act = _state(project_id, "active-candidate.json")
    if act.is_file():
        rec = _read_json(act)
        rec.update({"status": "STALE", "invalidatedByBinding": new_binding_id,
                    "invalidatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        _write_json_atomic(_state(project_id, "activations", f"{rec['experimentRunId']}.json"), rec)
        act.unlink()


# --------------------------------------------------------------------------- resource bounds (A2-13)
def _validate_hyperparameters(family: str, hyper: Mapping[str, Any]) -> dict[str, Any]:
    def num(v):
        f = float(v)
        if not math.isfinite(f):
            raise AuthorityError("hyperparameter must be a finite number")
        return f
    if family == "governed_logistic":
        return {"penalty": "l2", "solver": "lbfgs", "maxIter": DEFAULT_MAX_ITER, "tol": DEFAULT_TOLERANCE,
                "cGrid": list(C_GRID), "cSelection": "chronological_dev_inner_split_0.8"}
    max_iter = int(num(hyper.get("maxIter", 200)))
    lr = num(hyper.get("learningRate", 0.1))
    if not (10 <= max_iter <= 1000):
        raise AuthorityError("governed_hgb maxIter must be in [10, 1000]")
    if not (0.001 <= lr <= 1.0):
        raise AuthorityError("governed_hgb learningRate must be in [0.001, 1.0]")
    max_depth = hyper.get("maxDepth")
    if max_depth is not None:
        max_depth = int(num(max_depth))
        if not (1 <= max_depth <= 16):
            raise AuthorityError("governed_hgb maxDepth must be in [1, 16]")
    return {"maxIter": max_iter, "learningRate": lr, "maxDepth": max_depth, "earlyStopping": False, "randomState": 20260819}


# --------------------------------------------------------------------------- run authority (A2-04/06/10/11/13)
def issue_run_authority(*, actor: str, project_id: str, binding_id: str, model_family: str,
                        hyperparameters: Mapping[str, Any] | None = None, seed: int = 20260819) -> dict[str, Any]:
    if model_family not in _ALLOWED_FAMILIES:
        raise AuthorityError(f"unsupported model family: {model_family}")
    binding = _require_active_binding(project_id, binding_id)  # only the current active binding may authorize
    entry = _resolve_version(binding["datasetVersionId"])
    if entry["logicalContentSha256"] != binding["datasetContentSha256"]:
        raise StaleAuthorityError("binding is stale: registered content sha changed")
    eff_hyper = _validate_hyperparameters(model_family, hyperparameters or {})
    code = _code_identity()
    env_sha = _env_sha()
    effective_config = {
        "datasetVersionId": binding["datasetVersionId"], "datasetContentSha256": binding["datasetContentSha256"],
        "generation": binding["generation"], "targetContractSha256": binding["targetContractSha256"],
        "populationContractSha256": binding["populationContractSha256"], "temporalContractSha256": binding["temporalContractSha256"],
        "featureContractSha256": binding["featureContractSha256"], "preprocessingContractSha256": binding["preprocessingContractSha256"],
        "knowledgeTimeContractSha256": binding["knowledgeTimeContractSha256"],
        "featureSet": list(FEATURE_NAMES), "modelFamily": model_family, "effectiveHyperparameters": eff_hyper,
        "seed": seed, "developmentSeasons": binding["developmentSeasons"], "validationSeason": binding["validationSeason"],
        "codeRevision": code["codeRevision"], "worktreeContentSha256": code["worktreeContentSha256"], "environmentSha256": env_sha,
    }
    config_sha = sha256_bytes(canonical_json_bytes(effective_config))
    authority = {
        "schemaVersion": "MODEL_EXPERIMENT_RUN_AUTHORITY_V1", "runAuthorityId": uuid.uuid4().hex, "actor": actor,
        "projectId": project_id, "bindingId": binding_id, "bindingRevision": binding["revision"], "authorityRevision": 1,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "canonicalEffectiveConfigSha256": config_sha,
        **effective_config, "contractBundleSha256": binding["contractBundleSha256"],
        "targetContractId": binding["targetContractId"], "populationContractId": binding["populationContractId"],
        "temporalContractId": binding["temporalContractId"], "featureContractId": binding["featureContractId"],
        "preprocessingContractId": binding["preprocessingContractId"], "knowledgeTimeContractId": binding["knowledgeTimeContractId"],
    }
    _write_json_atomic(_state(project_id, "authorities", f"{authority['runAuthorityId']}.json"), authority)
    return authority


def get_run_authority(*, project_id: str, run_authority_id: str) -> dict[str, Any]:
    if not _OPAQUE_RE.match(run_authority_id or ""):
        raise AuthorityError("invalid run authority id")
    path = _state(project_id, "authorities", f"{run_authority_id}.json")
    if not path.is_file():
        raise AuthorityError("run authority not found for project")
    return _read_json(path)


def _validate_authority(authority: Mapping[str, Any], project_id: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    if authority.get("projectId") != project_id:
        raise AuthorityError("run authority does not belong to this project")
    _require_active_binding(project_id, authority["bindingId"])  # superseded binding cannot execute (A2-06)
    entry = _resolve_version(authority["datasetVersionId"])
    if entry["logicalContentSha256"] != authority["datasetContentSha256"]:
        raise StaleAuthorityError("registered content sha changed since authority issue")
    contracts = GC.contracts_for_generation(authority["generation"])  # generation-correct (A2-04)
    for field, key in (("targetContractSha256", "target"), ("populationContractSha256", "population"),
                       ("temporalContractSha256", "temporal"), ("featureContractSha256", "baseFeature"),
                       ("preprocessingContractSha256", "preprocessing"), ("knowledgeTimeContractSha256", "knowledgeTime")):
        if authority.get(field) != contracts[key]["sha256"]:
            raise AuthorityError(f"FORGED/STALE authority: {field} mismatch for {authority['generation']}")
    if list(authority.get("featureSet", [])) != list(FEATURE_NAMES):
        raise AuthorityError("FORGED authority: feature set mismatch")
    if authority.get("modelFamily") not in _ALLOWED_FAMILIES:
        raise AuthorityError("unsupported model family in authority")
    # A2-11: recompute current code/environment and require the authority still represents this software.
    code = _code_identity()
    if authority.get("codeRevision") != code["codeRevision"] or authority.get("worktreeContentSha256") != code["worktreeContentSha256"] \
            or authority.get("environmentSha256") != _env_sha():
        raise StaleAuthorityError("code/worktree/environment drifted since authority issue; re-issue required")
    # recompute + require the canonical effective-config fingerprint (forgery rejection)
    recomputed = sha256_bytes(canonical_json_bytes({
        "datasetVersionId": authority["datasetVersionId"], "datasetContentSha256": authority["datasetContentSha256"],
        "generation": authority["generation"], "targetContractSha256": authority["targetContractSha256"],
        "populationContractSha256": authority["populationContractSha256"], "temporalContractSha256": authority["temporalContractSha256"],
        "featureContractSha256": authority["featureContractSha256"], "preprocessingContractSha256": authority["preprocessingContractSha256"],
        "knowledgeTimeContractSha256": authority["knowledgeTimeContractSha256"], "featureSet": list(authority["featureSet"]),
        "modelFamily": authority["modelFamily"], "effectiveHyperparameters": authority["effectiveHyperparameters"],
        "seed": authority["seed"], "developmentSeasons": authority["developmentSeasons"], "validationSeason": authority["validationSeason"],
        "codeRevision": authority["codeRevision"], "worktreeContentSha256": authority["worktreeContentSha256"], "environmentSha256": authority["environmentSha256"],
    }))
    if recomputed != authority["canonicalEffectiveConfigSha256"]:
        raise AuthorityError("FORGED authority: canonical effective-config sha does not verify")
    path, receipt = _verify_object(entry)  # A2-05: integrity before load
    return entry, path, receipt


def _load_authorized_frame(path: Path):
    cols = ["plate_appearance_id", "game_id", "game_date", "season", "outcome", *FEATURE_NAMES]
    table = pq.read_table(_record_open(path), columns=cols)
    seasons = np.asarray(table["season"].to_pylist(), dtype=np.int64)
    fv = {n: np.asarray(table[n].to_pylist(), dtype=np.float64) for n in FEATURE_NAMES}
    ids = np.asarray(table["plate_appearance_id"].to_pylist(), dtype=object)
    return (fv, seasons, np.asarray(table["outcome"].to_pylist(), dtype=object),
            np.asarray(table["game_date"].to_pylist(), dtype=object), ids)


def _write_evidence_bundle(*, project_id: str, run_id: str, proba, val_labels, val_encoded, val_ids, val_dates,
                           full_metrics: Mapping[str, Any], model_artifact: Mapping[str, Any],
                           preprocessor_state: Mapping[str, Any]) -> dict[str, Any]:
    """Persist the immutable, independently-recomputable MODEL_RUN_EVIDENCE_BUNDLE_V1 (Gate 16). Children:
    validation predictions (raw float64), validation target + row identifiers, full diagnostics
    (confusion / per-class / reliability), the fitted preprocessor state, and the model artifact
    (logistic: full coefficients; tree ensemble: structural params). No 2025 row/prediction/metric appears
    — only the authorized 2024 validation fold is persisted."""
    bdir = _state(project_id, "evidence", run_id)
    bdir.mkdir(parents=True, exist_ok=True)
    pred_bytes = np.ascontiguousarray(proba, dtype=np.float64).tobytes()
    pred_sha = hashlib.sha256(pred_bytes).hexdigest()
    (bdir / "validation_predictions.f64").write_bytes(pred_bytes)
    val_target = {"schemaVersion": "MODEL_RUN_VALIDATION_TARGET_V1", "validationSeason": 2024,
                  "rowIds": [str(x) for x in val_ids], "gameDates": [str(x) for x in val_dates],
                  "labels": [str(x) for x in val_labels], "encoded": [int(x) for x in val_encoded],
                  "classOrder": list(PA_CLASS_ORDER)}
    vt_bytes = canonical_json_bytes(val_target); vt_sha = sha256_bytes(vt_bytes)
    (bdir / "validation_target.json").write_bytes(vt_bytes)
    diag_bytes = canonical_json_bytes(full_metrics); diag_sha = sha256_bytes(diag_bytes)
    (bdir / "diagnostics.json").write_bytes(diag_bytes)
    pre_bytes = canonical_json_bytes(dict(preprocessor_state)); pre_sha = sha256_bytes(pre_bytes)
    (bdir / "preprocessor.json").write_bytes(pre_bytes)
    model_bytes = canonical_json_bytes(dict(model_artifact)); model_sha = sha256_bytes(model_bytes)
    (bdir / "model.json").write_bytes(model_bytes)
    children = {
        "predictions": {"file": "validation_predictions.f64", "sha256": pred_sha, "dtype": "float64",
                        "shape": [int(proba.shape[0]), int(proba.shape[1])]},
        "validationTarget": {"file": "validation_target.json", "sha256": vt_sha, "rows": int(len(val_ids))},
        "diagnostics": {"file": "diagnostics.json", "sha256": diag_sha},
        "preprocessor": {"file": "preprocessor.json", "sha256": pre_sha},
        "model": {"file": "model.json", "sha256": model_sha},
    }
    manifest = {"schemaVersion": "MODEL_RUN_EVIDENCE_BUNDLE_V1", "runId": run_id, "children": children,
                "predictionSha256": pred_sha, "validationTargetSha256": vt_sha, "diagnosticsSha256": diag_sha,
                "preprocessorSha256": pre_sha, "modelSha256": model_sha}
    man_bytes = canonical_json_bytes(manifest); man_sha = sha256_bytes(man_bytes)
    (bdir / "evidence-manifest.json").write_bytes(man_bytes)
    manifest["manifestSha256"] = man_sha
    return manifest


def load_evidence_diagnostics(*, project_id: str, run_id: str) -> dict[str, Any]:
    """Downstream (Evaluation/Calibration) resolves full immutable diagnostics from the evidence bundle by
    run id — never a browser result. Verifies each child's sha before returning (checksum-before-use)."""
    if not _OPAQUE_RE.match(run_id or ""):
        raise AuthorityError("invalid run id")
    bdir = _state(project_id, "evidence", run_id)
    man_path = bdir / "evidence-manifest.json"
    if not man_path.is_file():
        raise AuthorityError("evidence bundle not found for run")
    manifest = _read_json(man_path)
    diag_path = bdir / manifest["children"]["diagnostics"]["file"]
    diag_bytes = diag_path.read_bytes()
    if sha256_bytes(diag_bytes) != manifest["diagnosticsSha256"]:
        raise AuthorityError("evidence diagnostics failed checksum verification")
    return {"manifest": manifest, "diagnostics": json.loads(diag_bytes.decode("utf-8"))}


def recompute_validation_logloss(*, project_id: str, run_id: str) -> dict[str, Any]:
    """Independently recompute the 2024 validation log loss from the persisted prediction + target artifacts
    (Gate 29 acceptance) — not from any stored metric JSON. Verifies child checksums first."""
    from sklearn.metrics import log_loss
    bdir = _state(project_id, "evidence", run_id)
    manifest = _read_json(bdir / "evidence-manifest.json")
    pred_meta = manifest["children"]["predictions"]
    pred_bytes = (bdir / pred_meta["file"]).read_bytes()
    if hashlib.sha256(pred_bytes).hexdigest() != manifest["predictionSha256"]:
        raise AuthorityError("prediction artifact failed checksum verification")
    proba = np.frombuffer(pred_bytes, dtype=np.float64).reshape(pred_meta["shape"])
    vt_bytes = (bdir / manifest["children"]["validationTarget"]["file"]).read_bytes()
    if sha256_bytes(vt_bytes) != manifest["validationTargetSha256"]:
        raise AuthorityError("validation target artifact failed checksum verification")
    vt = json.loads(vt_bytes.decode("utf-8"))
    encoded = np.asarray(vt["encoded"], dtype=np.int64)
    ll = float(log_loss(encoded, proba, labels=list(range(len(PA_CLASS_ORDER)))))
    return {"recomputedLogLoss": ll, "validationRows": int(len(encoded)), "runId": run_id}


def execute(*, actor: str, project_id: str, run_authority_id: str) -> dict[str, Any]:
    authority = get_run_authority(project_id=project_id, run_authority_id=run_authority_id)
    entry, path, receipt = _validate_authority(authority, project_id)
    dev_seasons = list(authority["developmentSeasons"]); val_season = int(authority["validationSeason"])
    sealed = set(entry.get("sealedSeasons") or [])

    fv, seasons, labels, dates, ids = _load_authorized_frame(path)
    seasons_in_object = sorted(set(int(s) for s in seasons))
    if entry["generation"] != "GEN2" and (sealed & set(seasons_in_object)):
        raise AuthorityError("sealed season present in a research object")
    dev_mask = np.isin(seasons, dev_seasons); val_mask = seasons == val_season
    if int(val_mask.sum()) == 0 or int(dev_mask.sum()) == 0:
        raise AuthorityError("authorized development/validation population is empty")
    for s in sealed:  # A2-04/A2-03: a sealed season may never enter dev or val, for any generation
        if s in set(int(x) for x in seasons[dev_mask]) or s in set(int(x) for x in seasons[val_mask]):
            raise AuthorityError(f"sealed season {s} leaked into an executed fold")
    encoded = encode_labels(labels)

    import warnings
    t0 = time.time()
    if authority["modelFamily"] == "governed_logistic":
        inner_train, inner_val, _ = chronological_date_atomic_split(dates, dev_mask, training_fraction=0.8)
        tuning = []
        for c in C_GRID:
            pre_i = FoldPreprocessor.fit(fv, FEATURE_NAMES, inner_train)
            est_i = LogisticRegression(C=float(c), penalty="l2", solver="lbfgs", max_iter=DEFAULT_MAX_ITER, tol=DEFAULT_TOLERANCE)
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always", ConvergenceWarning); est_i.fit(pre_i.transform(fv, inner_train), encoded[inner_train])
            if any(issubclass(x.category, ConvergenceWarning) for x in w) or int(np.max(est_i.n_iter_)) >= DEFAULT_MAX_ITER:
                raise AuthorityError("FAIL-CLOSED: logistic did not converge during C tuning")
            m_i = evaluate_multiclass(labels[inner_val], est_i.predict_proba(pre_i.transform(fv, inner_val)))
            tuning.append({"C": float(c), "logLoss": m_i["logLoss"], "brier": m_i["brierScore"]})
        c_star = min(tuning, key=lambda t: (t["logLoss"], t["brier"], t["C"]))["C"]
        pre = FoldPreprocessor.fit(fv, FEATURE_NAMES, dev_mask)
        est = LogisticRegression(C=float(c_star), penalty="l2", solver="lbfgs", max_iter=DEFAULT_MAX_ITER, tol=DEFAULT_TOLERANCE)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", ConvergenceWarning); est.fit(pre.transform(fv, dev_mask), encoded[dev_mask])
        n_iter = int(np.max(est.n_iter_))
        if any(issubclass(x.category, ConvergenceWarning) for x in w) or n_iter >= DEFAULT_MAX_ITER:
            raise AuthorityError("FAIL-CLOSED: logistic did not converge on full development fold")
        proba = est.predict_proba(pre.transform(fv, val_mask))
        model_repr = {"estimator": "LogisticRegression", "C": c_star, "coefShape": list(est.coef_.shape)}
        # Full fitted-estimator artifact (Gate 16E) — coefficients enable independent reconstruction.
        model_artifact = {"estimator": "LogisticRegression", "penalty": "l2", "solver": "lbfgs",
                          "C": float(c_star), "maxIter": DEFAULT_MAX_ITER, "tol": DEFAULT_TOLERANCE,
                          "classes": [int(x) for x in est.classes_], "featureOrder": list(FEATURE_NAMES),
                          "coef": est.coef_.tolist(), "intercept": est.intercept_.tolist()}
        convergence = {"solver": "lbfgs", "converged": True, "nIter": n_iter, "maxIter": DEFAULT_MAX_ITER, "selectedC": c_star}
    else:
        eff = authority["effectiveHyperparameters"]
        pre = FoldPreprocessor.fit(fv, FEATURE_NAMES, dev_mask)
        est = HistGradientBoostingClassifier(max_iter=int(eff["maxIter"]), learning_rate=float(eff["learningRate"]),
                                             max_depth=eff.get("maxDepth"), early_stopping=False, random_state=int(authority["seed"]))
        est.fit(pre.transform(fv, dev_mask), encoded[dev_mask])
        proba = np.zeros((int(val_mask.sum()), len(PA_CLASS_ORDER))); proba[:, est.classes_] = est.predict_proba(pre.transform(fv, val_mask))
        model_repr = {"estimator": "HistGradientBoostingClassifier", "nIter": int(est.n_iter_)}
        # Structural estimator artifact (Gate 16E) — a tree ensemble has no closed-form coefficients; the
        # persisted validation predictions are the authoritative independently-recomputable artifact.
        model_artifact = {"estimator": "HistGradientBoostingClassifier", "maxIter": int(eff["maxIter"]),
                          "learningRate": float(eff["learningRate"]), "maxDepth": eff.get("maxDepth"),
                          "randomState": int(authority["seed"]), "nIter": int(est.n_iter_),
                          "classes": [int(x) for x in est.classes_], "featureOrder": list(FEATURE_NAMES)}
        convergence = {"earlyStopping": False, "nIter": int(est.n_iter_), "maxIter": int(eff["maxIter"])}

    metrics = evaluate_multiclass(labels[val_mask], proba)
    scalar_metrics = {k: float(metrics[k]) for k in ("logLoss", "brierScore", "topLabelEce", "top1Accuracy", "macroF1")}
    run_id = uuid.uuid4().hex
    preproc_fp = sha256_bytes(canonical_json_bytes(pre.state()))
    model_fp = sha256_bytes(canonical_json_bytes(model_repr))
    pred_fp = hashlib.sha256(np.ascontiguousarray(proba, dtype=np.float64).tobytes()).hexdigest()
    metric_fp = sha256_bytes(canonical_json_bytes(scalar_metrics))
    # Gate 15 — recheck code/environment AFTER the fit and BEFORE publishing evidence. A worktree/env that
    # drifted during the fit fails closed (FAILED_STALE_AUTHORITY); no COMPLETE evidence is written.
    code = _code_identity()
    if code["codeRevision"] != authority["codeRevision"] or code["worktreeContentSha256"] != authority["worktreeContentSha256"] \
            or _env_sha() != authority["environmentSha256"]:
        _write_json_atomic(_state(project_id, "runs", f"{run_id}.json"),
                           {"schemaVersion": "MODEL_EXPERIMENT_RUN_EVIDENCE_V1", "experimentRunId": run_id,
                            "runAuthorityId": authority["runAuthorityId"], "projectId": project_id,
                            "status": "FAILED_STALE_AUTHORITY", "failureClass": "CODE_OR_ENVIRONMENT_DRIFT_DURING_FIT",
                            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        raise StaleAuthorityError("code/worktree/environment drifted during the fit; run failed closed")
    # Gate 16 — persist the complete immutable, independently-recomputable evidence bundle.
    bundle = _write_evidence_bundle(project_id=project_id, run_id=run_id, proba=proba, val_labels=labels[val_mask],
                                    val_encoded=encoded[val_mask], val_ids=ids[val_mask], val_dates=dates[val_mask],
                                    full_metrics=metrics, model_artifact=model_artifact, preprocessor_state=pre.state())
    # A2-10 — complete authority + receipt echo. Every id + sha the run authority carries is echoed.
    evidence = {
        "schemaVersion": "MODEL_EXPERIMENT_RUN_EVIDENCE_V1", "experimentRunId": run_id, "runAuthorityId": authority["runAuthorityId"],
        "projectId": project_id, "actor": actor, "canonicalEffectiveConfigSha256": authority["canonicalEffectiveConfigSha256"],
        "bindingId": authority["bindingId"], "bindingRevision": authority["bindingRevision"], "generation": authority["generation"],
        "datasetVersionId": authority["datasetVersionId"], "datasetContentSha256": authority["datasetContentSha256"],
        "contractBundleSha256": authority["contractBundleSha256"], "objectReceipt": receipt,
        "targetContractId": authority["targetContractId"], "targetContractSha256": authority["targetContractSha256"],
        "populationContractId": authority["populationContractId"], "populationContractSha256": authority["populationContractSha256"],
        "temporalContractId": authority["temporalContractId"], "temporalContractSha256": authority["temporalContractSha256"],
        "featureContractId": authority["featureContractId"], "featureContractSha256": authority["featureContractSha256"],
        "preprocessingContractId": authority["preprocessingContractId"], "preprocessingContractSha256": authority["preprocessingContractSha256"],
        "knowledgeTimeContractId": authority["knowledgeTimeContractId"], "knowledgeTimeContractSha256": authority["knowledgeTimeContractSha256"],
        "developmentSeasons": dev_seasons, "developmentRows": int(dev_mask.sum()),
        "validationSeason": val_season, "validationRows": int(val_mask.sum()),
        "seasonsInObject": seasons_in_object, "sealedSeasonsAccessed": [],
        "modelFamily": authority["modelFamily"], "effectiveHyperparameters": authority["effectiveHyperparameters"],
        "seed": authority["seed"], "classOrder": list(PA_CLASS_ORDER), "convergence": convergence,
        "preprocessorFingerprint": preproc_fp, "modelFingerprint": model_fp, "predictionFingerprint": pred_fp,
        "metricFingerprint": metric_fp, "metrics": scalar_metrics, "runtimeSeconds": round(time.time() - t0, 2),
        "evidenceBundleSha256": bundle["manifestSha256"], "predictionSha256": bundle["predictionSha256"],
        "validationTargetSha256": bundle["validationTargetSha256"], "diagnosticsSha256": bundle["diagnosticsSha256"],
        "modelSha256": bundle["modelSha256"], "preprocessorSha256": bundle["preprocessorSha256"],
        "codeRevision": code["codeRevision"], "worktreeContentSha256": code["worktreeContentSha256"], "environmentSha256": _env_sha(),
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "COMPLETE",
    }
    out = _state(project_id, "runs", f"{run_id}.json")
    if out.exists():
        raise AuthorityError("run id collision")
    _write_json_atomic(out, evidence)
    assert evidence["runAuthorityId"] == authority["runAuthorityId"]
    assert evidence["canonicalEffectiveConfigSha256"] == authority["canonicalEffectiveConfigSha256"]
    assert evidence["datasetContentSha256"] == authority["datasetContentSha256"] == receipt["logicalContentSha256"]
    return evidence


def run_authorized_suite(*, actor: str, project_id: str, binding_id: str,
                         candidates: list[Mapping[str, Any]], source: str = "suite") -> dict[str, Any]:
    """Autopilot / tuning migration (A2/Gate 8-9): every candidate goes through the SINGLE authorized path
    (active-binding-checked run authority -> object-verified execution -> immutable run evidence). No
    legacy binding-free execution; never scores 2025. Bounded to <= 8 candidates per call."""
    if not isinstance(candidates, list) or not (1 <= len(candidates) <= 8):
        raise AuthorityError("suite requires 1..8 candidates")
    _require_active_binding(project_id, binding_id)  # blocked without a current active binding
    results = []
    for spec in candidates:
        family = spec.get("family", "governed_hgb")
        hyper = spec.get("hyperparameters") or {}
        au = issue_run_authority(actor=actor, project_id=project_id, binding_id=binding_id,
                                 model_family=family, hyperparameters=hyper)
        ev = execute(actor=actor, project_id=project_id, run_authority_id=au["runAuthorityId"])
        results.append({"label": spec.get("label", family), "source": source, "runAuthorityId": au["runAuthorityId"],
                        "experimentRunId": ev["experimentRunId"], "modelFamily": family, "generation": ev["generation"],
                        "metrics": ev["metrics"], "developmentRows": ev["developmentRows"],
                        "validationRows": ev["validationRows"], "sealedSeasonsAccessed": ev["sealedSeasonsAccessed"]})
    ok = [r for r in results if "logLoss" in r["metrics"]]
    best = min(ok, key=lambda r: r["metrics"]["logLoss"]) if ok else None
    return {"source": source, "candidateCount": len(results), "candidates": results,
            "best": best["experimentRunId"] if best else None,
            "bestLogLoss": best["metrics"]["logLoss"] if best else None}


def get_run(*, project_id: str, run_id: str) -> dict[str, Any]:
    if not _OPAQUE_RE.match(run_id or ""):
        raise AuthorityError("invalid run id")
    path = _state(project_id, "runs", f"{run_id}.json")
    if not path.is_file():
        raise AuthorityError("run not found for project")
    return _read_json(path)


def list_runs(*, project_id: str) -> list[dict[str, Any]]:
    d = _state(project_id, "runs")
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        r = _read_json(f)
        out.append({k: r[k] for k in ("experimentRunId", "runAuthorityId", "datasetVersionId", "generation",
                                      "modelFamily", "metrics", "createdAt", "developmentRows", "validationRows")})
    return out


# --------------------------------------------------------------------------- active candidate (A2-09/A2-14)
def activate_candidate(*, actor: str, project_id: str, run_id: str) -> dict[str, Any]:
    run = get_run(project_id=project_id, run_id=run_id)
    # the run must be for the CURRENT active binding revision (no stale candidate activation)
    if run["bindingId"] != (_active_pointer(project_id) or {}).get("bindingId"):
        raise StaleAuthorityError("run does not belong to the active binding revision")
    activation = {
        "schemaVersion": "ACTIVE_CANDIDATE_REVIEW_V1", "projectId": project_id, "actor": actor,
        "experimentRunId": run_id, "runAuthorityId": run["runAuthorityId"], "bindingId": run["bindingId"],
        "bindingRevision": run["bindingRevision"], "generation": run["generation"],
        "datasetVersionId": run["datasetVersionId"], "datasetContentSha256": run["datasetContentSha256"],
        "resultFingerprint": sha256_bytes(canonical_json_bytes({
            "metrics": run["metricFingerprint"], "prediction": run["predictionFingerprint"],
            "preprocessor": run["preprocessorFingerprint"], "model": run["modelFingerprint"]})),
        "activatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "ACTIVE",
    }
    _write_json_atomic(_state(project_id, "activations", f"{run_id}.json"), activation)
    _write_json_atomic(_state(project_id, "active-candidate.json"), activation)
    return activation


def get_active_candidate(*, project_id: str) -> dict[str, Any] | None:
    """Downstream stages resolve the active candidate here by run id — never a browser/last-file result."""
    p = _state(project_id, "active-candidate.json")
    if not p.is_file():
        return None
    act = _read_json(p)
    # verify the referenced run still exists and its parent fingerprints match (A2-14)
    run = get_run(project_id=project_id, run_id=act["experimentRunId"])
    if run["runAuthorityId"] != act["runAuthorityId"] or run["datasetContentSha256"] != act["datasetContentSha256"]:
        raise AuthorityError("active candidate parent fingerprints do not verify")
    return {**act, "run": {k: run[k] for k in ("experimentRunId", "runAuthorityId", "datasetVersionId", "generation",
                                               "developmentSeasons", "validationSeason", "metrics", "objectReceipt")}}


def active_candidate_evaluation(*, project_id: str) -> dict[str, Any] | None:
    """Gate 18/19 — Evaluation and Calibration resolve the project's ACTIVE CANDIDATE and its immutable
    2024-validation evidence bundle (full diagnostics: metrics, confusion, per-class, reliability), plus an
    INDEPENDENT log-loss recomputation from the persisted prediction/target artifacts. No browser result and
    no 2025 row is involved. Returns None when no candidate is active."""
    act = get_active_candidate(project_id=project_id)
    if act is None:
        return None
    run_id = act["experimentRunId"]
    run = get_run(project_id=project_id, run_id=run_id)
    bundle = load_evidence_diagnostics(project_id=project_id, run_id=run_id)
    recomputed = recompute_validation_logloss(project_id=project_id, run_id=run_id)
    diagnostics = bundle["diagnostics"]
    # calibrator artifact is not fit in this phase — Calibration shows RAW diagnostics, CALIBRATOR NOT CONFIGURED
    return {
        "runId": run_id, "runAuthorityId": run["runAuthorityId"], "generation": run["generation"],
        "datasetVersionId": run["datasetVersionId"], "datasetContentSha256": run["datasetContentSha256"],
        "developmentSeasons": run["developmentSeasons"], "developmentRows": run.get("developmentRows"),
        "validationSeason": run["validationSeason"], "validationRows": run.get("validationRows"),
        "modelFamily": run["modelFamily"], "featureCount": run.get("objectReceipt", {}).get("featureCount"),
        "preprocessingContractId": run.get("preprocessingContractId"),
        "calibrationStatus": "RAW_UNCALIBRATED", "calibratorConfigured": False,
        "evidenceBundleSha256": run.get("evidenceBundleSha256"), "predictionSha256": run.get("predictionSha256"),
        "diagnosticsSha256": run.get("diagnosticsSha256"), "resultFingerprint": act.get("resultFingerprint"),
        "metrics": run["metrics"], "diagnostics": diagnostics,
        "independentRecomputedLogLoss": recomputed["recomputedLogLoss"],
        "recomputationMatchesStored": abs(recomputed["recomputedLogLoss"] - float(run["metrics"]["logLoss"])) < 1e-9,
        "validationLabel": "2024 validation (2025 sealed — never scored)",
    }
