"""Server-side Gen-3 dataset registry, project binding, run authority, and governed execution
(Phase 7A.1). Realizes the invariant UI = SERVER = TRAINING = RESULT authority, fail-closed on any
mismatch — additively, WITHOUT touching the D3/C4-serving cockpit execution path.

The scientist selects an EXACT immutable dataset version; the server resolves it from the registry,
issues a project dataset binding, then a run authority carrying every contract/version/content digest,
validates it fail-closed immediately before training, executes the GOVERNED pipeline on the exact
registered object (never opening the sealed 2025 object), and binds immutable run evidence that echoes
the same authority. Retries get new opaque run ids but the same canonical effective-config fingerprint.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
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


class AuthorityError(CockpitError):
    """Fail-closed authority/binding/run violation."""


# --------------------------------------------------------------------------- helpers
def _env_sha() -> str:
    import pandas, sklearn, pyarrow
    return sha256_bytes(canonical_json_bytes({"python": sys.version.split()[0], "pyarrow": pyarrow.__version__,
                                              "numpy": np.__version__, "pandas": pandas.__version__, "sklearn": sklearn.__version__}))


def _code_revision() -> tuple[str, bool]:
    import subprocess
    try:
        rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT).decode().strip())
        return rev, dirty
    except Exception:
        return "UNKNOWN", True


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".tmp-{uuid.uuid4().hex}"
    tmp.write_bytes(canonical_json_bytes(payload) if isinstance(payload, (dict, list)) else json.dumps(payload).encode())
    os.replace(tmp, path)


def _contained(root: Path, child: Path) -> Path:
    root = root.resolve()
    p = (root / child).resolve()
    if root not in p.parents and p != root:
        raise AuthorityError("path escapes authorized root")
    return p


# --------------------------------------------------------------------------- catalog / registration (Gate 1/2)
def _gen2_catalog_entry() -> dict[str, Any]:
    path = _feature_view_path()
    meta = pq.read_schema(path).metadata or {}
    content_sha = (meta.get(b"featureContentSha") or b"").decode() or hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "datasetVersionId": f"mlb-pa-feature-view:sha256:{content_sha}",
        "label": "MLB FD1 Gen-2 Feature View",
        "generation": "GEN2",
        "status": "GOVERNED_MODELING_DATASET",
        "selectable": True,
        "logicalContentSha256": content_sha,
        "physicalParquetSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "objectPath": str(path),
        "seasons": [2023, 2024, 2025],
        "developmentSeasons": [2023], "validationSeason": 2024, "sealedSeasons": [2025],
        "rows": 549_479, "featureCount": len(FEATURE_NAMES), "target": "outcome",
        "targetContractId": None, "temporalContractId": None,
    }


def _gen3_catalog_entries() -> list[dict[str, Any]]:
    reg = _read_json(GEN3_ROOT / "registration.json")
    contracts = reg["contracts"]
    research = {
        "datasetVersionId": reg["registrationId"],
        "label": "MLB Gen-3 Base Research View",
        "generation": "GEN3", "status": "GOVERNED_RESEARCH_DATASET", "selectable": True,
        "logicalContentSha256": reg["research"]["logicalContentSha256"],
        "physicalParquetSha256": reg["research"]["physicalParquetSha256"],
        "objectPath": str(GEN3_ROOT / "objects" / "sha256" / reg["research"]["logicalContentSha256"] / "research.parquet"),
        "seasons": [2021, 2022, 2023, 2024],
        "developmentSeasons": [2021, 2022, 2023], "validationSeason": 2024, "sealedSeasons": [2025],
        "rows": reg["research"]["rows"], "featureCount": len(FEATURE_NAMES), "target": "outcome",
        "targetContractId": contracts["target"], "featureSchemaId": contracts["featureSchema"],
        "temporalContractId": contracts["temporal"], "populationContractId": contracts["population"],
        "preprocessingContractId": contracts["preprocessing"], "knowledgeTimeContractId": contracts["knowledgeTime"],
        "contractBundleSha256": reg["contractBundleSha256"],
        "quarantineLedgerSha256": reg["quarantineLedgerSha256"], "quarantineTotal": reg["quarantineTotal"],
        "sourceDatasetId": GC.PARENT_DATASET_ID, "partitionAuthoritySha256": GC.PARENT_PARTITION_AUTHORITY_SHA,
        "bridgeManifestSha256": GC.PARENT_BRIDGE_MANIFEST_SHA,
    }
    sealed = {
        "datasetVersionId": f"mlb-pa-gen3-sealed-2025:sha256:{reg['sealed2025']['logicalContentSha256']}",
        "label": "MLB Gen-3 Sealed 2025 OOT Evidence",
        "generation": "GEN3_SEALED", "status": "SEALED_OOT_RESTRICTED", "selectable": False,
        "logicalContentSha256": reg["sealed2025"]["logicalContentSha256"],
        "seasons": [2025], "developmentSeasons": [], "validationSeason": None, "sealedSeasons": [2025],
        "rows": reg["sealed2025"]["rows"], "target": "outcome",
        "restriction": "NOT selectable for ordinary development; structural registration/lineage only",
    }
    return [research, sealed]


def catalog() -> list[dict[str, Any]]:
    return [_gen2_catalog_entry(), *_gen3_catalog_entries()]


def register_gen3() -> dict[str, Any]:
    """Idempotently write the Gen-3 (+ sealed) versions into the ASP dataset registry."""
    reg = _read_json(ASP_REGISTRY) if ASP_REGISTRY.is_file() else {"datasets": []}
    existing = {d.get("datasetVersionId") for d in reg.get("datasets", [])}
    added = []
    for entry in catalog():
        if entry["datasetVersionId"] not in existing:
            reg["datasets"].append({k: v for k, v in entry.items() if k != "objectPath"})
            added.append(entry["datasetVersionId"])
    _write_json_atomic(ASP_REGISTRY, reg)
    return {"registered": [d["datasetVersionId"] for d in reg["datasets"]], "added": added}


def _resolve_version(dataset_version_id: str) -> dict[str, Any]:
    if not isinstance(dataset_version_id, str) or not _ID_RE.match(dataset_version_id):
        raise AuthorityError("invalid dataset version id")
    for entry in catalog():
        if entry["datasetVersionId"] == dataset_version_id:
            return entry
    raise AuthorityError(f"dataset version not found in registry: {dataset_version_id}")


def _verify_object(entry: Mapping[str, Any]) -> Path:
    path = Path(entry["objectPath"]) if entry.get("objectPath") else None
    if path is None or not path.is_file() or path.is_symlink():
        raise AuthorityError("registered object missing or is a link")
    seasons = set(pq.read_table(path, columns=["season"])["season"].to_pylist())
    if 2025 in seasons or 2026 in seasons:
        # Gen-2 view legitimately contains 2025 as its OWN frozen season; the executor never uses it.
        if entry["generation"] != "GEN2":
            raise AuthorityError("sealed season present in a research object")
    return path


# --------------------------------------------------------------------------- project dataset binding (Gate 4)
def create_binding(*, actor: str, project_id: str, dataset_version_id: str,
                   expected_content_sha: str | None = None) -> dict[str, Any]:
    entry = _resolve_version(dataset_version_id)
    if not entry.get("selectable", False):
        raise AuthorityError("dataset version is not selectable for ordinary development")
    if expected_content_sha and expected_content_sha != entry["logicalContentSha256"]:
        raise AuthorityError("client-asserted content sha does not match the registered object")
    _verify_object(entry)
    binding_id = uuid.uuid4().hex
    contracts = GC.all_contracts()
    binding = {
        "schemaVersion": "PROJECT_MODELING_DATASET_BINDING_V1",
        "bindingId": binding_id, "actor": actor, "projectId": project_id,
        "datasetVersionId": dataset_version_id, "datasetContentSha256": entry["logicalContentSha256"],
        "generation": entry["generation"], "featureViewId": dataset_version_id,
        "targetContractId": contracts["target"]["id"], "targetContractSha256": contracts["target"]["sha256"],
        "populationContractId": contracts["population"]["id"], "populationContractSha256": contracts["population"]["sha256"],
        "temporalContractId": contracts["temporal"]["id"], "temporalContractSha256": contracts["temporal"]["sha256"],
        "featureContractId": contracts["baseFeature"]["id"], "featureContractSha256": contracts["baseFeature"]["sha256"],
        "preprocessingContractId": contracts["preprocessing"]["id"], "preprocessingContractSha256": contracts["preprocessing"]["sha256"],
        "developmentSeasons": entry["developmentSeasons"], "validationSeason": entry["validationSeason"],
        "sealedSeasons": entry["sealedSeasons"], "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "revision": 1, "status": "ACTIVE",
    }
    _write_json_atomic(_contained(STATE_ROOT / "bindings" / project_id, f"{binding_id}.json"), binding)
    _write_json_atomic(STATE_ROOT / "bindings" / project_id / "active.json", {"bindingId": binding_id})
    return binding


def get_binding(*, project_id: str, binding_id: str) -> dict[str, Any]:
    if not _OPAQUE_RE.match(binding_id or ""):
        raise AuthorityError("invalid binding id")
    path = _contained(STATE_ROOT / "bindings" / project_id, f"{binding_id}.json")
    if not path.is_file():
        raise AuthorityError("binding not found for project")
    return _read_json(path)


def active_binding(*, project_id: str) -> dict[str, Any] | None:
    ptr = STATE_ROOT / "bindings" / project_id / "active.json"
    if not ptr.is_file():
        return None
    return get_binding(project_id=project_id, binding_id=_read_json(ptr)["bindingId"])


# --------------------------------------------------------------------------- run authority (Gate 5/6/7)
_ALLOWED_FAMILIES = {"governed_logistic", "governed_hgb"}


def _effective_hyperparameters(model_family: str, hyper: Mapping[str, Any]) -> dict[str, Any]:
    if model_family == "governed_logistic":
        return {"penalty": "l2", "solver": "lbfgs", "maxIter": DEFAULT_MAX_ITER, "tol": DEFAULT_TOLERANCE,
                "cGrid": list(C_GRID), "cSelection": "chronological_dev_inner_split_0.8"}
    return {"maxIter": int(hyper.get("maxIter", 200)), "learningRate": float(hyper.get("learningRate", 0.1)),
            "earlyStopping": False, "randomState": 20260819}


def issue_run_authority(*, actor: str, project_id: str, binding_id: str, model_family: str,
                        hyperparameters: Mapping[str, Any] | None = None, seed: int = 20260819) -> dict[str, Any]:
    if model_family not in _ALLOWED_FAMILIES:
        raise AuthorityError(f"unsupported model family: {model_family}")
    binding = get_binding(project_id=project_id, binding_id=binding_id)
    entry = _resolve_version(binding["datasetVersionId"])
    if entry["logicalContentSha256"] != binding["datasetContentSha256"]:
        raise AuthorityError("binding is stale: registered content sha changed")
    eff_hyper = _effective_hyperparameters(model_family, hyperparameters or {})
    rev, dirty = _code_revision()
    env_sha = _env_sha()
    effective_config = {
        "datasetVersionId": binding["datasetVersionId"], "datasetContentSha256": binding["datasetContentSha256"],
        "featureViewId": binding["featureViewId"], "targetContractSha256": binding["targetContractSha256"],
        "populationContractSha256": binding["populationContractSha256"], "temporalContractSha256": binding["temporalContractSha256"],
        "featureContractSha256": binding["featureContractSha256"], "preprocessingContractSha256": binding["preprocessingContractSha256"],
        "featureSet": list(FEATURE_NAMES), "modelFamily": model_family, "effectiveHyperparameters": eff_hyper,
        "seed": seed, "developmentSeasons": binding["developmentSeasons"], "validationSeason": binding["validationSeason"],
        "codeRevision": rev, "environmentSha256": env_sha,
    }
    config_sha = sha256_bytes(canonical_json_bytes(effective_config))
    authority = {
        "schemaVersion": "MODEL_EXPERIMENT_RUN_AUTHORITY_V1",
        "runAuthorityId": uuid.uuid4().hex, "actor": actor, "projectId": project_id,
        "bindingId": binding_id, "authorityRevision": 1,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "canonicalEffectiveConfigSha256": config_sha, "dirtyTree": dirty,
        **effective_config,
        "targetContractId": binding["targetContractId"], "populationContractId": binding["populationContractId"],
        "temporalContractId": binding["temporalContractId"], "featureContractId": binding["featureContractId"],
        "preprocessingContractId": binding["preprocessingContractId"], "generation": binding["generation"],
    }
    _write_json_atomic(_contained(STATE_ROOT / "authorities" / project_id, f"{authority['runAuthorityId']}.json"), authority)
    return authority


def get_run_authority(*, project_id: str, run_authority_id: str) -> dict[str, Any]:
    if not _OPAQUE_RE.match(run_authority_id or ""):
        raise AuthorityError("invalid run authority id")
    path = _contained(STATE_ROOT / "authorities" / project_id, f"{run_authority_id}.json")
    if not path.is_file():
        raise AuthorityError("run authority not found for project")
    return _read_json(path)


# --------------------------------------------------------------------------- validation (Gate 8) + execution (9/11/13)
def _validate_authority(authority: Mapping[str, Any], project_id: str, actor: str) -> tuple[dict[str, Any], Path]:
    if authority.get("projectId") != project_id:
        raise AuthorityError("run authority does not belong to this project")
    entry = _resolve_version(authority["datasetVersionId"])
    if entry["logicalContentSha256"] != authority["datasetContentSha256"]:
        raise AuthorityError("STALE authority: registered content sha changed")
    contracts = GC.all_contracts()
    checks = {
        "targetContractSha256": contracts["target"]["sha256"],
        "populationContractSha256": contracts["population"]["sha256"],
        "temporalContractSha256": contracts["temporal"]["sha256"],
        "featureContractSha256": contracts["baseFeature"]["sha256"],
        "preprocessingContractSha256": contracts["preprocessing"]["sha256"],
    }
    for field, expected in checks.items():
        if authority.get(field) != expected:
            raise AuthorityError(f"FORGED/STALE authority: {field} mismatch")
    if list(authority.get("featureSet", [])) != list(FEATURE_NAMES):
        raise AuthorityError("FORGED authority: feature set mismatch")
    if authority.get("modelFamily") not in _ALLOWED_FAMILIES:
        raise AuthorityError("unsupported model family in authority")
    # recompute the canonical effective-config fingerprint and require exact match (forgery rejection)
    recomputed = sha256_bytes(canonical_json_bytes({
        "datasetVersionId": authority["datasetVersionId"], "datasetContentSha256": authority["datasetContentSha256"],
        "featureViewId": authority["featureViewId"], "targetContractSha256": authority["targetContractSha256"],
        "populationContractSha256": authority["populationContractSha256"], "temporalContractSha256": authority["temporalContractSha256"],
        "featureContractSha256": authority["featureContractSha256"], "preprocessingContractSha256": authority["preprocessingContractSha256"],
        "featureSet": list(authority["featureSet"]), "modelFamily": authority["modelFamily"],
        "effectiveHyperparameters": authority["effectiveHyperparameters"], "seed": authority["seed"],
        "developmentSeasons": authority["developmentSeasons"], "validationSeason": authority["validationSeason"],
        "codeRevision": authority["codeRevision"], "environmentSha256": authority["environmentSha256"],
    }))
    if recomputed != authority["canonicalEffectiveConfigSha256"]:
        raise AuthorityError("FORGED authority: canonical effective-config sha does not verify")
    path = _verify_object(entry)
    return entry, path


def _load_authorized_frame(entry: Mapping[str, Any], path: Path):
    cols = ["plate_appearance_id", "game_id", "game_date", "season", "outcome", *FEATURE_NAMES]
    table = pq.read_table(path, columns=cols)
    seasons = np.asarray(table["season"].to_pylist(), dtype=np.int64)
    fv = {n: np.asarray(table[n].to_pylist(), dtype=np.float64) for n in FEATURE_NAMES}
    return fv, seasons, np.asarray(table["outcome"].to_pylist(), dtype=object), np.asarray(table["game_date"].to_pylist(), dtype=object)


def execute(*, actor: str, project_id: str, run_authority_id: str) -> dict[str, Any]:
    authority = get_run_authority(project_id=project_id, run_authority_id=run_authority_id)
    entry, path = _validate_authority(authority, project_id, actor)
    dev_seasons = list(authority["developmentSeasons"])
    val_season = int(authority["validationSeason"])
    sealed = set(entry.get("sealedSeasons") or [])

    fv, seasons, labels, dates = _load_authorized_frame(entry, path)
    # Gate 13: the training/validation frames must contain NO sealed season row.
    if sealed & set(int(s) for s in seasons if int(s) in sealed) and entry["generation"] != "GEN2":
        raise AuthorityError("sealed season present in authorized object")
    dev_mask = np.isin(seasons, dev_seasons)
    val_mask = seasons == val_season
    if int(val_mask.sum()) == 0 or int(dev_mask.sum()) == 0:
        raise AuthorityError("authorized development/validation population is empty")
    if 2025 in set(int(s) for s in seasons[dev_mask]) or 2025 in set(int(s) for s in seasons[val_mask]):
        raise AuthorityError("2025 leaked into an executed fold")
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
        convergence = {"solver": "lbfgs", "converged": True, "nIter": n_iter, "maxIter": DEFAULT_MAX_ITER, "selectedC": c_star}
    else:
        pre = FoldPreprocessor.fit(fv, FEATURE_NAMES, dev_mask)
        est = HistGradientBoostingClassifier(max_iter=int(authority["effectiveHyperparameters"]["maxIter"]),
                                             learning_rate=float(authority["effectiveHyperparameters"]["learningRate"]),
                                             early_stopping=False, random_state=int(authority["seed"]))
        est.fit(pre.transform(fv, dev_mask), encoded[dev_mask])
        proba = np.zeros((int(val_mask.sum()), len(PA_CLASS_ORDER))); proba[:, est.classes_] = est.predict_proba(pre.transform(fv, val_mask))
        convergence = {"earlyStopping": False, "nIter": int(est.n_iter_), "maxIter": int(authority["effectiveHyperparameters"]["maxIter"])}

    metrics = evaluate_multiclass(labels[val_mask], proba)
    runtime = round(time.time() - t0, 2)
    scalar_metrics = {k: float(metrics[k]) for k in ("logLoss", "brierScore", "topLabelEce", "top1Accuracy", "macroF1")}
    run_id = uuid.uuid4().hex   # unique per attempt (retries differ); config fingerprint stays constant
    preproc_fp = sha256_bytes(canonical_json_bytes(pre.state()))
    evidence = {
        "schemaVersion": "MODEL_EXPERIMENT_RUN_EVIDENCE_V1",
        "experimentRunId": run_id, "runAuthorityId": authority["runAuthorityId"], "projectId": project_id, "actor": actor,
        "canonicalEffectiveConfigSha256": authority["canonicalEffectiveConfigSha256"],
        "datasetVersionId": authority["datasetVersionId"], "datasetContentSha256": authority["datasetContentSha256"],
        "featureViewId": authority["featureViewId"], "generation": authority["generation"],
        "targetContractId": authority["targetContractId"], "temporalContractId": authority["temporalContractId"],
        "populationContractId": authority["populationContractId"], "featureContractId": authority["featureContractId"],
        "preprocessingContractId": authority["preprocessingContractId"],
        "developmentSeasons": dev_seasons, "developmentRows": int(dev_mask.sum()),
        "validationSeason": val_season, "validationRows": int(val_mask.sum()),
        "seasonsInObject": sorted(set(int(s) for s in seasons)), "sealedSeasonsLoaded": [],
        "modelFamily": authority["modelFamily"], "effectiveHyperparameters": authority["effectiveHyperparameters"],
        "seed": authority["seed"], "classOrder": list(PA_CLASS_ORDER), "convergence": convergence,
        "preprocessorFingerprint": preproc_fp, "metrics": scalar_metrics, "runtimeSeconds": runtime,
        "codeRevision": authority["codeRevision"], "environmentSha256": authority["environmentSha256"],
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "COMPLETE",
    }
    # append-only immutable evidence (never overwrite a prior run id)
    out = _contained(STATE_ROOT / "runs" / project_id, f"{run_id}.json")
    if out.exists():
        raise AuthorityError("run id collision")
    _write_json_atomic(out, evidence)
    # Result-authority echo assertion (Gate 11): result identity must equal the run authority identity.
    assert evidence["runAuthorityId"] == authority["runAuthorityId"]
    assert evidence["canonicalEffectiveConfigSha256"] == authority["canonicalEffectiveConfigSha256"]
    assert evidence["datasetContentSha256"] == authority["datasetContentSha256"]
    return evidence


def get_run(*, project_id: str, run_id: str) -> dict[str, Any]:
    if not _OPAQUE_RE.match(run_id or ""):
        raise AuthorityError("invalid run id")
    path = _contained(STATE_ROOT / "runs" / project_id, f"{run_id}.json")
    if not path.is_file():
        raise AuthorityError("run not found for project")
    return _read_json(path)


def list_runs(*, project_id: str) -> list[dict[str, Any]]:
    d = STATE_ROOT / "runs" / project_id
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        r = _read_json(f)
        out.append({k: r[k] for k in ("experimentRunId", "runAuthorityId", "datasetVersionId", "generation",
                                      "modelFamily", "metrics", "createdAt", "developmentRows", "validationRows")})
    return out


# --------------------------------------------------------------------------- activation (Gate 14)
def activate_candidate(*, actor: str, project_id: str, run_id: str) -> dict[str, Any]:
    run = get_run(project_id=project_id, run_id=run_id)
    activation = {
        "schemaVersion": "CANDIDATE_ACTIVATION_V1", "projectId": project_id, "actor": actor,
        "experimentRunId": run_id, "runAuthorityId": run["runAuthorityId"],
        "resultFingerprint": sha256_bytes(canonical_json_bytes(run["metrics"])),
        "datasetVersionId": run["datasetVersionId"], "activatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_json_atomic(_contained(STATE_ROOT / "activations" / project_id, f"{run_id}.json"), activation)
    _write_json_atomic(STATE_ROOT / "activations" / project_id / "active.json", {"experimentRunId": run_id})
    return activation
