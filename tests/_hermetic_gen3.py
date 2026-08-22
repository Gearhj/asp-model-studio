"""Shared hermetic Gen-3 authority builder for the Phase 7D.4 closure batteries (B2-full / B6 / Gates 14-16).

Builds a temporary, throwaway canonical registry + immutable object roots with REAL published Gen-3 (2021-2024)
+ Gen-2 (2023-2024) research/sealed objects through the ACTUAL production publisher (server.sports_modeling.
gen3_publish.publish_object) — no test-only substitute publisher, no hand-constructed receipts, no monkeypatched
verifier. The Gen-3 research object additionally carries a real ``prior_pa_count`` column and its safe derived
``log1p_prior_pa_count`` feature; the advanced feature set is registered as a complete MLB_FEATURE_SET_CONTRACT_V2
(base prefix + one leakage-validated advanced semantic contract). No external download, no Bronze, no real 2025.

Isolation is the proven four-attribute monkeypatch (STATE_ROOT / GEN3_ROOT / GEN2_ROOT / ASP_REGISTRY); the
shared development .runtime is never touched.
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from server.sports_cockpit import gen3_authority as A
from server.sports_modeling import feature_semantics as FS
from server.sports_modeling import gen3_contracts as C
from server.sports_modeling.gen3_publish import publish_object
from server.sports_modeling.feature_contract import FEATURE_NAMES
from server.sports_modeling.metrics import PA_CLASS_ORDER

_CATEG = {"context_top_bottom": [0, 1], "context_outs_before": [0, 1, 2], "context_base_mask_before": list(range(8))}
ADVANCED_FEATURE = "log1p_prior_pa_count"
ADVANCED_FAMILY = "reliability_sample_size"
RESEARCH_SEASONS = [2021, 2022, 2023, 2024]


def advanced_semantic_contract(feature_id: str = ADVANCED_FEATURE, *, leakage: str = "SAFE_HISTORICAL_AS_OF",
                               knowledge_time: str = FS.HISTORICAL_AS_OF_CUTOFF,
                               source_columns: list[str] | None = None, family_id: str = ADVANCED_FAMILY) -> dict[str, Any]:
    """The complete immutable MLB_FEATURE_SEMANTIC_CONTRACT_V1 for the safe derived feature
    ``prior_pa_count -> log1p_prior_pa_count`` (or a deliberately-leaky variant for the rejection tests)."""
    return FS.build_semantic_contract(
        feature_id=feature_id, display_name=f"log1p prior PA count ({feature_id})", family_id=family_id,
        knowledge_time_class=knowledge_time,
        as_of_rule="prior-season plate-appearance count resolved strictly before the target PA knowledge time",
        source_object_ids=[C.PARENT_DATASET_ID], source_receipt_shas=list(FS._SOURCE_RECEIPT_SHAS),
        source_columns=source_columns or ["prior_pa_count"],
        canonical_derivation="log1p(prior_pa_count): monotone stabilizing transform of the prior-season PA count",
        derivation_code_digest="hermetic_log1p_prior_pa_count_v1", derivation_version="RELIABILITY_SAMPLE_SIZE_V1",
        window_rule="full prior-season aggregate as-of the eligibility cutoff", allowed_seasons=RESEARCH_SEASONS,
        missingness_semantics="governed fill with prior-missing indicator when no eligible prior",
        leakage_classification=leakage)


def advanced_feature_set_spec(*, feature_id: str = ADVANCED_FEATURE, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """A registered MLB_FEATURE_SET_CONTRACT_V2 spec: the exact base prefix + one advanced feature + its semantic
    contract (the shape ``_resolve_feature_set`` requires for a non-base set)."""
    return {"contractVersion": FS.FEATURE_SET_CONTRACT_VERSION,
            "exactFinalOrderedFeatureIds": [*FEATURE_NAMES, feature_id],
            "semanticContracts": [contract or advanced_semantic_contract(feature_id)]}


def _table(seasons, per_class=14, seed=1, with_advanced=True):
    rng = np.random.default_rng(seed)
    rows = []
    for s in seasons:
        for ci, cls in enumerate(PA_CLASS_ORDER):
            for k in range(per_class):
                r = {"plate_appearance_id": f"{s}-{ci}-{k}-{rng.integers(1_000_000_000)}", "game_id": f"g{s}-{k % 5}",
                     "game_date": f"{s}-0{1 + (k % 2)}-15", "season": s, "outcome": cls,
                     "batter_canonical_player_uuid": f"b{k % 7}", "pitcher_canonical_player_uuid": f"p{k % 7}"}
                for f in FEATURE_NAMES:
                    r[f] = float(rng.choice(_CATEG[f])) if f in _CATEG else (
                        float(rng.integers(1, 10)) if f == "context_inning" else float(rng.random()))
                if with_advanced:
                    prior_pa = float(rng.integers(0, 700))               # a real prior-season PA count
                    r["prior_pa_count"] = prior_pa
                    r[ADVANCED_FEATURE] = float(np.log1p(prior_pa)) + 0.001 * float(ci)  # safe derived + faint signal
                rows.append(r)
    cols = {k: [r[k] for r in rows] for k in rows[0]}
    fields = [("plate_appearance_id", pa.string()), ("game_id", pa.string()), ("game_date", pa.string()),
              ("season", pa.int16()), ("outcome", pa.string()), ("batter_canonical_player_uuid", pa.string()),
              ("pitcher_canonical_player_uuid", pa.string()), *[(f, pa.float64()) for f in FEATURE_NAMES]]
    if with_advanced:
        fields += [("prior_pa_count", pa.float64()), (ADVANCED_FEATURE, pa.float64())]
    schema = pa.schema(fields)
    return pa.table({k: (pa.array(v, pa.int16()) if k == "season" else v) for k, v in cols.items()}, schema=schema)


def build_hermetic_gen3(tmp_path, monkeypatch, *, advanced_spec: dict[str, Any] | None = None,
                        migrate: bool = True) -> dict[str, Any]:
    """Publish real Gen-3 + Gen-2 objects into isolated temp roots through the ACTUAL publisher, register the
    advanced V2 feature set, migrate the canonical registry, and return handles. `advanced_spec` overrides the
    registered advanced feature-set (used by the leaky-variant production-path rejection tests). `migrate=False`
    leaves the sidecars unmigrated so a concurrency test can race the FIRST canonical registry migration.

    The physical layout (tmp_path/sports-modeling/... + tmp_path/artifacts/datasets/registry.json) is EXACTLY
    what ``ASP_MODEL_STUDIO_RUNTIME_ROOT=<tmp_path>`` resolves to, so a subprocess launched with that env var
    resolves the SAME roots — this is the shared substrate for the interprocess / HTTP / isolated-root batteries."""
    gen3 = tmp_path / "sports-modeling" / "mlb-pa-gen3-v2"
    gen2 = tmp_path / "sports-modeling" / "mlb-pa-gen2-v1"
    monkeypatch.setattr(A, "GEN3_ROOT", gen3)
    monkeypatch.setattr(A, "GEN2_ROOT", gen2)
    monkeypatch.setattr(A, "STATE_ROOT", gen3 / "authority")
    monkeypatch.setattr(A, "ASP_REGISTRY", tmp_path / "artifacts" / "datasets" / "registry.json")
    A._VERIFIED_OBJECT_CACHE.clear()
    contracts = C.all_contracts()
    bundle = C.contract_bundle_sha_for("GEN3")
    research = _table(RESEARCH_SEASONS, with_advanced=True)
    sealed = _table([2025], per_class=6, seed=9, with_advanced=True)
    prov = {"datasetId": C.PARENT_DATASET_ID}
    mr = publish_object(gen3, research, object_kind="research", contracts=contracts, contract_bundle_sha=bundle,
                        provenance_extra={**prov, "seasons": RESEARCH_SEASONS})
    ms = publish_object(gen3, sealed, object_kind="sealed-2025", contracts=contracts, contract_bundle_sha=bundle,
                        provenance_extra={**prov, "seasons": [2025]})
    per_season = {int(s): int(pc.sum(pc.cast(pc.equal(research["season"], s), pa.int64())).as_py()) for s in RESEARCH_SEASONS}
    per_season[2025] = sealed.num_rows
    spec = advanced_spec if advanced_spec is not None else advanced_feature_set_spec()
    reg = {"schemaVersion": "MLB_GEN3_REGISTRATION_V1", "contractBundleSha256": bundle,
           "registrationId": f"mlb-pa-gen3-research:sha256:{mr['logicalContentSha256']}",
           "contracts": {k: v["id"] for k, v in contracts.items()},
           "research": {"logicalContentSha256": mr["logicalContentSha256"], "physicalParquetSha256": mr["physicalParquetSha256"],
                        "schemaSha256": mr["schemaSha256"], "rows": research.num_rows, "seasons": RESEARCH_SEASONS},
           "sealed2025": {"logicalContentSha256": ms["logicalContentSha256"], "physicalParquetSha256": ms["physicalParquetSha256"],
                          "rows": sealed.num_rows, "seasons": [2025]},
           "perSeasonRows": {str(k): v for k, v in per_season.items()},
           "featureSets": {"advanced": spec}}
    gen3.mkdir(parents=True, exist_ok=True)
    (gen3 / "registration.json").write_text(json.dumps(reg), encoding="utf-8")
    g2r = _table([2023, 2024], with_advanced=False)
    g2s = _table([2025], per_class=6, with_advanced=False)
    c2 = C.gen2_contracts(); b2 = C.contract_bundle_sha_for("GEN2")
    m2r = publish_object(gen2, g2r, object_kind="gen2-research", contracts=c2, contract_bundle_sha=b2, provenance_extra={"seasons": [2023, 2024]})
    m2s = publish_object(gen2, g2s, object_kind="gen2-sealed-2025", contracts=c2, contract_bundle_sha=b2, provenance_extra={"seasons": [2025]})
    ps2 = {2023: int(pc.sum(pc.cast(pc.equal(g2r["season"], 2023), pa.int64())).as_py()),
           2024: int(pc.sum(pc.cast(pc.equal(g2r["season"], 2024), pa.int64())).as_py()), 2025: g2s.num_rows}
    reg2 = {"schemaVersion": "MLB_GEN2_REGISTRATION_V1", "contractBundleSha256": b2,
            "registrationId": f"mlb-pa-gen2-research:sha256:{m2r['logicalContentSha256']}",
            "contracts": {k: v["id"] for k, v in c2.items()},
            "research": {"logicalContentSha256": m2r["logicalContentSha256"], "physicalParquetSha256": m2r["physicalParquetSha256"],
                         "schemaSha256": m2r["schemaSha256"], "rows": g2r.num_rows, "seasons": [2023, 2024]},
            "sealed2025": {"logicalContentSha256": m2s["logicalContentSha256"], "physicalParquetSha256": m2s["physicalParquetSha256"],
                           "rows": g2s.num_rows, "seasons": [2025]},
            "perSeasonRows": {str(k): v for k, v in ps2.items()}}
    (gen2 / "registration.json").write_text(json.dumps(reg2), encoding="utf-8")
    if migrate:
        A.migrate_registry()
    return {"gen3Root": gen3, "gen2Root": gen2, "researchId": reg["registrationId"],
            "advancedFeature": ADVANCED_FEATURE, "advancedFamily": ADVANCED_FAMILY, "runtimeRoot": tmp_path}
