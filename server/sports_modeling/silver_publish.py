"""Phase 7D.5A (Workstreams B + C) — immutable, semantically-bound, QUARANTINED Silver publication authority.

Binds the actual point-in-time transformation (server.sports_modeling.silver_transform) and its produced VALUES to
a full semantic contract chain — never just feature names/order — and publishes an immutable, content-addressed,
create-once Silver object that is registered SILVER_NORMALIZED / QUARANTINED / NOT_MODEL_ELIGIBLE. It fails closed
on: caller-supplied advanced values that disagree with the production recomputation; the old target-contaminated
formula; a V2->V1 feature-set downgrade; empty semantic/family/set children; and any attempt to make Silver model
eligible. No model training, activation, or comparison is possible for a quarantined Silver object.
"""
from __future__ import annotations

import math
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..sports_cockpit.path_containment import ContainmentError, contained_no_reparse
from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from . import feature_semantics as FS
from . import gen3_contracts as GC
from . import silver_transform as ST
from .silver_transform import LOG1P_PRIOR_PA_COUNT, PRIOR_PA_COUNT, SilverTransformError

SILVER_TRANSFORM_RECEIPT = "MLB_SILVER_TRANSFORMATION_RECEIPT_V1"
SILVER_STATUS = "SILVER_NORMALIZED"
SILVER_QUARANTINE = "QUARANTINED"
SILVER_FAMILY_ID = "silver_prior_pa_reliability"
_ADV = (PRIOR_PA_COUNT, LOG1P_PRIOR_PA_COUNT)
_HEX64 = __import__("re").compile(r"^[0-9a-f]{64}$")


class SilverPublishError(RuntimeError):
    """A Silver publication precondition failed (fail-closed)."""


class DatasetNotModelEligibleError(RuntimeError):
    """A quarantined Silver dataset was offered to a model-eligible path (fail-closed)."""


# --------------------------------------------------------------------------- semantic authority (no V1 downgrade)
def silver_semantic_contracts(*, source_object_id: str, source_receipt_sha: str) -> dict[str, dict[str, Any]]:
    """Complete point-in-time semantic contracts for BOTH produced features (prior_pa_count is an intermediate
    semantic feature bound even though the model may use only log1p_prior_pa_count)."""
    common = dict(family_id=SILVER_FAMILY_ID, knowledge_time_class=FS.HISTORICAL_AS_OF_CUTOFF,
                  leakage_classification="SAFE_HISTORICAL_AS_OF",
                  as_of_rule=("aggregate over plate appearances for the SAME batter whose governed chronological key "
                              "is STRICTLY EARLIER than the current PA; the current PA never counts itself"),
                  source_object_ids=[source_object_id], source_receipt_shas=[source_receipt_sha],
                  derivation_code_digest=ST.TRANSFORM_ID, derivation_version=ST.TRANSFORM_ID,
                  window_rule="strictly-earlier same-batter PA history", allowed_seasons=[2021, 2022, 2023, 2024])
    prior = FS.build_semantic_contract(
        feature_id=PRIOR_PA_COUNT, display_name="Prior PA count (strictly earlier, same batter)",
        source_columns=[ST.BATTER_KEY, "game_date", "game_id", "at_bat_number", "plate_appearance_id"],
        partition_columns=[ST.BATTER_KEY],
        order_columns=["game_date", "game_id", "at_bat_number", "plate_appearance_id"],
        derivation_type="POINT_IN_TIME_COUNT_AGGREGATION",
        canonical_derivation="count of strictly-earlier plate appearances for the same batter", **common)
    log1p = FS.build_semantic_contract(
        feature_id=LOG1P_PRIOR_PA_COUNT, display_name="log1p(prior PA count)", derivation_type="DECLARED_DERIVATION",
        source_columns=[PRIOR_PA_COUNT], canonical_derivation="log1p(prior_pa_count) — no additive/outcome term", **common)
    return {PRIOR_PA_COUNT: prior, LOG1P_PRIOR_PA_COUNT: log1p}


def silver_family_contract(contracts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return FS.feature_family_contract(SILVER_FAMILY_ID, list(_ADV), contracts)


def silver_feature_set_v2(*, dataset_version_id: str, dataset_content_sha: str, base_feature_ids: Sequence[str],
                          contracts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    final = [*base_feature_ids, *_ADV]
    return FS.feature_set_contract_v2(dataset_version_id=dataset_version_id, dataset_content_sha=dataset_content_sha,
                                      ordered_base_feature_ids=list(base_feature_ids), optional_family_ids=[SILVER_FAMILY_ID],
                                      final_ordered_feature_ids=final, contracts=dict(contracts), name="silver_advanced")


# --------------------------------------------------------------------------- value digest (binds VALUES, not names)
def value_digest(rows: Sequence[Mapping[str, Any]], feature_ids: Sequence[str], *, id_col: str) -> str:
    """Deterministic digest over (row identity, ordered advanced feature names, canonical serialized values). One
    changed value invalidates it."""
    payload = {"schemaVersion": "MLB_SILVER_VALUE_DIGEST_V1", "featureIds": list(feature_ids),
               "rows": [[str(r[id_col]), *[_canon_num(r[f]) for f in feature_ids]] for r in rows]}
    return sha256_bytes(canonical_json_bytes(payload))


def _canon_num(x: Any) -> str:
    return repr(float(x))     # stable textual form so the digest is exact and reproducible


# --------------------------------------------------------------------------- transform + independent value check
def _recompute_and_check(source_rows: Sequence[Mapping[str, Any]], supplied: Mapping[str, Sequence[float]] | None,
                         id_col: str) -> list[dict[str, float]]:
    """Recompute the point-in-time features from the AUTHORIZED source columns (target excluded). If the caller
    supplied advanced columns, they must EQUAL the recomputation or publication fails closed (Test 10 / old-formula
    rejection)."""
    recomputed = ST.compute_prior_pa(source_rows)
    if supplied is not None:
        for i, feat in enumerate(_ADV):
            if feat in supplied:
                col = list(supplied[feat])
                if len(col) != len(recomputed):
                    raise SilverPublishError("supplied advanced column length mismatch")
                for j, v in enumerate(col):
                    if not math.isclose(float(v), recomputed[j][feat], rel_tol=0, abs_tol=1e-12):
                        raise SilverPublishError(
                            f"supplied '{feat}' value at row {j} ({v}) != production recomputation "
                            f"({recomputed[j][feat]}); refusing to trust caller-supplied advanced values")
    return recomputed


# --------------------------------------------------------------------------- immutable publication
def _silver_objects_root(silver_root: Path) -> Path:
    return Path(silver_root) / "objects" / "sha256"


def publish_silver(*, silver_root: Path, source_object_id: str, source_receipt_sha: str, source_manifest_sha: str,
                   source_physical_sha: str, source_logical_sha: str, source_schema_sha: str,
                   source_rows: Sequence[Mapping[str, Any]], base_feature_ids: Sequence[str],
                   season_of_row, id_col: str = "plate_appearance_id", generation: str = "GEN3",
                   supplied_advanced: Mapping[str, Sequence[float]] | None = None,
                   feature_set_downgrade_v1: bool = False, allow_empty_semantic: bool = False) -> dict[str, Any]:
    """Transform -> value-verify -> receipt + semantic V2 -> immutable quarantined Silver publication. Returns the
    registration record. Fails closed on target presence, value mismatch (incl. the old leaky formula), a V1
    downgrade, or empty semantic children."""
    if feature_set_downgrade_v1:
        raise SilverPublishError("V2->V1 feature-set downgrade is forbidden for a non-base Silver object")
    if any(ST.TARGET_COLUMN in r for r in source_rows[:1]):
        raise SilverPublishError("source rows must not carry the target column 'outcome'")

    recomputed = _recompute_and_check(source_rows, supplied_advanced, id_col)
    # assemble the output table: source columns + the two produced features, in stable input order
    out_rows = []
    for r, feats in zip(source_rows, recomputed):
        out_rows.append({**{k: r[k] for k in r}, PRIOR_PA_COUNT: feats[PRIOR_PA_COUNT],
                         LOG1P_PRIOR_PA_COUNT: feats[LOG1P_PRIOR_PA_COUNT]})
    contracts = silver_semantic_contracts(source_object_id=source_object_id, source_receipt_sha=source_receipt_sha)
    for c in contracts.values():
        FS.validate_feature_semantic_contract(c)                       # leakage validator on the produced features
    family = silver_family_contract(contracts)
    full_contracts = {**FS.all_feature_semantic_contracts(), **contracts}
    fsc = silver_feature_set_v2(dataset_version_id=f"silver:{source_object_id}", dataset_content_sha=source_logical_sha,
                                base_feature_ids=base_feature_ids, contracts=full_contracts)
    sem_children = {"featureSemanticContracts": {k: contracts[k] for k in _ADV},
                    "featureFamilyContract": family, "featureSetContractV2": fsc}
    if not allow_empty_semantic and (not sem_children["featureSemanticContracts"] or not family or not fsc):
        raise SilverPublishError("refusing to publish Silver with empty semantic/family/set children")

    vdigest = value_digest(out_rows, _ADV, id_col=id_col)
    seasons = sorted({int(season_of_row(r)) for r in source_rows})
    if 2025 in seasons or 2026 in seasons:
        raise SilverPublishError("SEAL VIOLATION: sealed season present in a Silver source")

    # build the immutable object bytes (parquet) deterministically
    table = _rows_to_table(out_rows)
    sink = pa.BufferOutputStream()
    pq.write_table(table.replace_schema_metadata(None).combine_chunks(), sink, compression="none",
                   row_group_size=max(1, table.num_rows), use_dictionary=False, write_statistics=False, store_schema=True)
    obj_bytes = sink.getvalue().to_pybytes()
    physical = sha256_bytes(obj_bytes)
    schema_sha = sha256_bytes(canonical_json_bytes([{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in table.schema]))
    logical = sha256_bytes(canonical_json_bytes({"schemaVersion": "MLB_SILVER_OBJECT_V1", "schemaSha256": schema_sha,
                                                 "rows": table.num_rows, "valueDigest": vdigest}))

    receipt_body = {
        "receiptContract": SILVER_TRANSFORM_RECEIPT, "receiptVersion": "1.0.0", "transformId": ST.TRANSFORM_ID,
        "generation": generation, "sourceObjectId": source_object_id, "sourceManifestSha256": source_manifest_sha,
        "sourcePhysicalSha256": source_physical_sha, "sourceLogicalSha256": source_logical_sha, "sourceSchemaSha256": source_schema_sha,
        "governedChronologicalKey": ST.governed_sort_key(sorted(source_rows[0].keys())),
        "temporalContractSha256": GC.temporal_contract()["sha256"], "populationContractSha256": GC.population_contract()["sha256"],
        "knowledgeTimeContractSha256": GC.knowledge_time_contract()["sha256"],
        "semanticContractShas": {k: contracts[k]["sha256"] for k in _ADV},
        "featureFamilySha256": family["sha256"], "featureFamilyId": family["id"],
        "featureSetV2Sha256": fsc["sha256"], "featureSetV2Id": fsc["id"],
        "orderedOutputFeatures": list(fsc["payload"]["exactFinalOrderedFeatureIds"]),
        "producedAdvancedFeatures": list(_ADV), "rowIdentityColumn": id_col, "valueDigestSha256": vdigest,
        "outputPhysicalSha256": physical, "outputLogicalSha256": logical, "outputSchemaSha256": schema_sha,
        "rowCount": table.num_rows, "perSeasonRows": _per_season(source_rows, season_of_row),
        "codeIdentity": ST.TRANSFORM_ID, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    receipt_sha = sha256_bytes(canonical_json_bytes(receipt_body))
    receipt = {**receipt_body, "receiptSha256": receipt_sha}

    manifest_body = {
        "manifestContract": "MLB_SILVER_PUBLICATION_MANIFEST_V1", "status": SILVER_STATUS, "quarantine": SILVER_QUARANTINE,
        "modelEligible": False, "approvedForTraining": False, "transformReceiptSha256": receipt_sha,
        "outputPhysicalSha256": physical, "outputLogicalSha256": logical, "outputSchemaSha256": schema_sha,
        "valueDigestSha256": vdigest, "rowCount": table.num_rows, "orderedOutputFeatures": receipt_body["orderedOutputFeatures"],
    }
    manifest_sha = sha256_bytes(canonical_json_bytes(manifest_body))
    manifest = {**manifest_body, "manifestSha256": manifest_sha}

    final = _silver_objects_root(silver_root) / manifest_sha
    if final.exists():                                              # content-addressed create-once
        existing = final / "manifest.json"
        if existing.is_file() and existing.read_bytes() == canonical_json_bytes(manifest):
            return _register(silver_root, source_object_id, manifest_sha, receipt_sha, table.num_rows, seasons)
        raise SilverPublishError("Silver content-address conflict (divergent bytes)")
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = final.parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        (staging / "object.parquet").write_bytes(obj_bytes)
        (staging / "transform-receipt.json").write_bytes(canonical_json_bytes(receipt))
        (staging / "feature-semantic-contracts.json").write_bytes(canonical_json_bytes(sem_children["featureSemanticContracts"]))
        (staging / "feature-family-contract.json").write_bytes(canonical_json_bytes(family))
        (staging / "feature-set-contract.json").write_bytes(canonical_json_bytes(fsc))
        (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        if final.exists():
            raise SilverPublishError("Silver content-address conflict (published during staging)")
        os.replace(staging, final)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return _register(silver_root, source_object_id, manifest_sha, receipt_sha, table.num_rows, seasons)


def _rows_to_table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    cols = {k: [r[k] for r in rows] for k in rows[0]}
    fields = []
    for k in rows[0]:
        v0 = rows[0][k]
        fields.append((k, pa.float64() if isinstance(v0, float) else (pa.int64() if isinstance(v0, int) else pa.string())))
    return pa.table({k: cols[k] for k, _ in fields}, schema=pa.schema(fields))


def _per_season(rows, season_of_row) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        s = str(int(season_of_row(r)))
        out[s] = out.get(s, 0) + 1
    return out


# --------------------------------------------------------------------------- quarantine registry + model barrier
def _silver_registry_path(silver_root: Path) -> Path:
    return Path(silver_root) / "silver-registry.json"


def _register(silver_root: Path, source_object_id: str, manifest_sha: str, receipt_sha: str, rows: int,
              seasons: list[int]) -> dict[str, Any]:
    import json
    p = _silver_registry_path(silver_root)
    reg = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"schemaVersion": "MLB_SILVER_REGISTRY_V1", "datasets": {}}
    dsid = f"silver:{source_object_id}:sha256:{manifest_sha}"
    entry = {"datasetVersionId": dsid, "status": SILVER_STATUS, "quarantine": SILVER_QUARANTINE, "modelEligible": False,
             "approvedForTraining": False, "manifestSha256": manifest_sha, "transformReceiptSha256": receipt_sha,
             "rows": rows, "seasons": seasons, "sourceObjectId": source_object_id}
    reg["datasets"][dsid] = entry
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.parent / f".tmp-{uuid.uuid4().hex}"; tmp.write_bytes(canonical_json_bytes(reg)); os.replace(tmp, p)
    return entry


def is_quarantined_silver(silver_root: Path, dataset_version_id: str) -> bool:
    import json
    p = _silver_registry_path(silver_root)
    if not p.is_file():
        return False
    reg = json.loads(p.read_text(encoding="utf-8"))
    e = (reg.get("datasets") or {}).get(dataset_version_id)
    return bool(e and (not e.get("modelEligible") or e.get("quarantine") == SILVER_QUARANTINE))


def assert_model_eligible(silver_root: Path, dataset_version_id: str) -> None:
    """The model-eligibility barrier: a quarantined Silver dataset may never enter a model-eligible path."""
    if str(dataset_version_id).startswith("silver:") or is_quarantined_silver(silver_root, dataset_version_id):
        raise DatasetNotModelEligibleError(
            f"DATASET_NOT_MODEL_ELIGIBLE: {dataset_version_id} is a QUARANTINED Silver dataset; model training / "
            "binding / activation / comparison is not authorized (SILVER_QUARANTINED)")


# --------------------------------------------------------------------------- verification (recompute value digest)
def verify_silver(silver_root: Path, manifest_sha: str) -> dict[str, Any]:
    """Reload the published Silver object + receipt, recompute the value digest from the object bytes, and cross-
    check receipt/manifest identities. Reparse-safe. One changed value invalidates it."""
    import json
    root = _silver_objects_root(silver_root)
    final = contained_no_reparse(root / manifest_sha, [root])
    for name in ("manifest.json", "transform-receipt.json", "object.parquet"):
        contained_no_reparse(final / name, [root])                 # reparse rejection before any open
    manifest = json.loads((final / "manifest.json").read_bytes().decode("utf-8"))
    if sha256_bytes(canonical_json_bytes({k: v for k, v in manifest.items() if k != "manifestSha256"})) != manifest_sha:
        raise SilverPublishError("Silver manifest sha does not match its content address (tampered)")
    receipt = json.loads((final / "transform-receipt.json").read_bytes().decode("utf-8"))
    body = {k: v for k, v in receipt.items() if k != "receiptSha256"}
    if sha256_bytes(canonical_json_bytes(body)) != receipt.get("receiptSha256") \
            or receipt.get("receiptSha256") != manifest.get("transformReceiptSha256"):
        raise SilverPublishError("Silver transform receipt sha does not verify")
    obj_bytes = (final / "object.parquet").read_bytes()
    if sha256_bytes(obj_bytes) != receipt["outputPhysicalSha256"]:
        raise SilverPublishError("Silver object bytes differ from the receipt (tampered)")
    table = pq.read_table(pa.BufferReader(obj_bytes))
    id_col = receipt["rowIdentityColumn"]
    rows = table.to_pylist()
    recomputed_digest = value_digest(rows, receipt["producedAdvancedFeatures"], id_col=id_col)
    if recomputed_digest != receipt["valueDigestSha256"]:
        raise SilverPublishError("Silver value digest recomputed from the published object does not verify (tampered)")
    if manifest.get("modelEligible") or manifest.get("approvedForTraining"):
        raise SilverPublishError("Silver manifest must remain model-ineligible / not-approved-for-training")
    return {"manifest": manifest, "receipt": receipt, "valueDigestSha256": recomputed_digest, "objectDir": final}
