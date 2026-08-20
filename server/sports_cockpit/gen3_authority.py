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
STATE_ROOT = GEN3_ROOT / "authority"
ASP_REGISTRY = RUNTIME_ROOT / "artifacts" / "datasets" / "registry.json"
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,200}$")
_OPAQUE_RE = re.compile(r"^[0-9a-f]{32}$")
_ALLOWED_FAMILIES = {"governed_logistic", "governed_hgb"}


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


# --------------------------------------------------------------------------- catalog / registration (A2-06 read of registry)
def _gen2_catalog_entry() -> dict[str, Any]:
    path = _feature_view_path()
    meta = pq.read_schema(path).metadata or {}
    content_sha = (meta.get(b"featureContentSha") or b"").decode() or hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "datasetVersionId": f"mlb-pa-feature-view:sha256:{content_sha}", "label": "MLB FD1 Gen-2 Feature View",
        "generation": "GEN2", "status": "GOVERNED_MODELING_DATASET", "selectable": True,
        "logicalContentSha256": content_sha, "physicalParquetSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "objectPath": str(path), "seasons": [2023, 2024, 2025],
        "developmentSeasons": [2023], "validationSeason": 2024, "sealedSeasons": [2025],
        "rows": 549_479, "featureCount": len(FEATURE_NAMES), "target": "outcome",
    }


def _gen3_catalog_entries() -> list[dict[str, Any]]:
    reg = _read_json(GEN3_ROOT / "registration.json")
    contracts = reg["contracts"]
    research = {
        "datasetVersionId": reg["registrationId"], "label": "MLB Gen-3 Base Research View",
        "generation": "GEN3", "status": "GOVERNED_RESEARCH_DATASET", "selectable": True,
        "logicalContentSha256": reg["research"]["logicalContentSha256"], "physicalParquetSha256": reg["research"]["physicalParquetSha256"],
        "objectPath": str(GEN3_ROOT / "objects" / "sha256" / reg["research"]["logicalContentSha256"] / "research.parquet"),
        "seasons": [2021, 2022, 2023, 2024], "developmentSeasons": [2021, 2022, 2023], "validationSeason": 2024,
        "sealedSeasons": [2025], "rows": reg["research"]["rows"], "featureCount": len(FEATURE_NAMES), "target": "outcome",
        "contractBundleSha256": reg["contractBundleSha256"], "quarantineLedgerSha256": reg["quarantineLedgerSha256"],
        "quarantineTotal": reg["quarantineTotal"], "sourceDatasetId": GC.PARENT_DATASET_ID,
    }
    sealed = {
        "datasetVersionId": f"mlb-pa-gen3-sealed-2025:sha256:{reg['sealed2025']['logicalContentSha256']}",
        "label": "MLB Gen-3 Sealed 2025 OOT Evidence", "generation": "GEN3_SEALED",
        "status": "SEALED_OOT_RESTRICTED", "selectable": False,
        "logicalContentSha256": reg["sealed2025"]["logicalContentSha256"], "seasons": [2025],
        "developmentSeasons": [], "validationSeason": None, "sealedSeasons": [2025], "rows": reg["sealed2025"]["rows"],
        "target": "outcome", "restriction": "NOT selectable for ordinary development; structural registration/lineage only",
    }
    return [research, sealed]


def catalog() -> list[dict[str, Any]]:
    return [_gen2_catalog_entry(), *_gen3_catalog_entries()]


def register_gen3() -> dict[str, Any]:
    """Explicit registry write (admin/build action). The catalog is READ from the registry by consumers."""
    reg = _read_json(ASP_REGISTRY) if ASP_REGISTRY.is_file() else {"datasets": []}
    existing = {d.get("datasetVersionId") for d in reg.get("datasets", [])}
    for entry in catalog():
        if entry["datasetVersionId"] not in existing:
            reg["datasets"].append({k: v for k, v in entry.items() if k != "objectPath"})
    _write_json_atomic(ASP_REGISTRY, reg)
    return {"registered": [d["datasetVersionId"] for d in reg["datasets"]]}


def _resolve_version(dataset_version_id: str) -> dict[str, Any]:
    if not isinstance(dataset_version_id, str) or not _ID_RE.match(dataset_version_id):
        raise AuthorityError("invalid dataset version id")
    for entry in catalog():
        if entry["datasetVersionId"] == dataset_version_id:
            return entry
    raise AuthorityError(f"dataset version not found in registry: {dataset_version_id}")


# --------------------------------------------------------------------------- object integrity (A2-05)
def _verify_object(entry: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Verify the exact registered content-addressed object before it is opened. Returns (path, receipt)."""
    path = Path(entry["objectPath"]) if entry.get("objectPath") else None
    if path is None or not path.is_file() or path.is_symlink():
        raise AuthorityError("registered object missing or is a link")
    physical = hashlib.sha256(path.read_bytes()).hexdigest()
    if entry.get("physicalParquetSha256") and physical != entry["physicalParquetSha256"]:
        raise AuthorityError("registered object bytes differ from the registry receipt (tampered)")
    schema = pq.read_schema(path)
    md = pq.read_metadata(path)
    rows = int(md.num_rows)
    if entry.get("rows") and rows != entry["rows"]:
        raise AuthorityError("registered object row count differs from the registry")
    seasons = sorted(set(int(s) for s in pq.read_table(path, columns=["season"])["season"].to_pylist()))
    if seasons != sorted(set(entry["seasons"])):
        raise AuthorityError("registered object season set differs from the registry")
    schema_sha = sha256_bytes(canonical_json_bytes([{"name": f.name, "type": str(f.type)} for f in schema]))
    receipt = {"physicalParquetSha256": physical, "logicalContentSha256": entry["logicalContentSha256"],
               "schemaSha256": schema_sha, "rows": rows, "seasons": seasons, "generation": entry["generation"],
               "verifiedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
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
    table = pq.read_table(path, columns=cols)
    seasons = np.asarray(table["season"].to_pylist(), dtype=np.int64)
    fv = {n: np.asarray(table[n].to_pylist(), dtype=np.float64) for n in FEATURE_NAMES}
    return fv, seasons, np.asarray(table["outcome"].to_pylist(), dtype=object), np.asarray(table["game_date"].to_pylist(), dtype=object)


def execute(*, actor: str, project_id: str, run_authority_id: str) -> dict[str, Any]:
    authority = get_run_authority(project_id=project_id, run_authority_id=run_authority_id)
    entry, path, receipt = _validate_authority(authority, project_id)
    dev_seasons = list(authority["developmentSeasons"]); val_season = int(authority["validationSeason"])
    sealed = set(entry.get("sealedSeasons") or [])

    fv, seasons, labels, dates = _load_authorized_frame(path)
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
        convergence = {"solver": "lbfgs", "converged": True, "nIter": n_iter, "maxIter": DEFAULT_MAX_ITER, "selectedC": c_star}
    else:
        eff = authority["effectiveHyperparameters"]
        pre = FoldPreprocessor.fit(fv, FEATURE_NAMES, dev_mask)
        est = HistGradientBoostingClassifier(max_iter=int(eff["maxIter"]), learning_rate=float(eff["learningRate"]),
                                             max_depth=eff.get("maxDepth"), early_stopping=False, random_state=int(authority["seed"]))
        est.fit(pre.transform(fv, dev_mask), encoded[dev_mask])
        proba = np.zeros((int(val_mask.sum()), len(PA_CLASS_ORDER))); proba[:, est.classes_] = est.predict_proba(pre.transform(fv, val_mask))
        model_repr = {"estimator": "HistGradientBoostingClassifier", "nIter": int(est.n_iter_)}
        convergence = {"earlyStopping": False, "nIter": int(est.n_iter_), "maxIter": int(eff["maxIter"])}

    metrics = evaluate_multiclass(labels[val_mask], proba)
    scalar_metrics = {k: float(metrics[k]) for k in ("logLoss", "brierScore", "topLabelEce", "top1Accuracy", "macroF1")}
    run_id = uuid.uuid4().hex
    preproc_fp = sha256_bytes(canonical_json_bytes(pre.state()))
    model_fp = sha256_bytes(canonical_json_bytes(model_repr))
    pred_fp = hashlib.sha256(np.ascontiguousarray(proba, dtype=np.float64).tobytes()).hexdigest()
    metric_fp = sha256_bytes(canonical_json_bytes(scalar_metrics))
    code = _code_identity()
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
