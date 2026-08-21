"""Phase 7D — behavioral acceptance for the Phase 7B acquisition gate.

Hermetic + isolated (never touches shared .runtime): builds a temporary canonical registry + immutable
object roots with REAL published Gen-3 research/sealed objects (one carrying an extra synthetic research
feature and an authorized advanced feature-set), then exercises the PRODUCTION resolver/authority/evidence
code. Proves: one immutable registry as sole resolver; complete object verification + path containment +
cache safety; generation-specific feature contracts + advanced-feature propagation into the run; canonical
2024-only feature-family ablation with paired uncertainty; atomic content-addressed evidence + manifest
anchoring + child tamper rejection; loadable fitted HGB estimator; activation that rejects fabricated /
non-COMPLETE / tampered runs; and run-authority reconstruction/forgery rejection. No 2025 is ever scored.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from server.sports_cockpit import gen3_authority as A
from server.sports_modeling import gen3_contracts as C
from server.sports_modeling.gen3_publish import publish_object
from server.sports_modeling.feature_contract import FEATURE_NAMES
from server.sports_modeling.metrics import PA_CLASS_ORDER

_CATEG = {"context_top_bottom": [0, 1], "context_outs_before": [0, 1, 2], "context_base_mask_before": list(range(8))}
SYNTH = "synthetic_signal"
RESEARCH_SEASONS = [2021, 2022, 2023, 2024]


def _table(seasons, per_class=14, seed=1, with_synth=True):
    rng = np.random.default_rng(seed)
    rows = []
    for s in seasons:
        for ci, cls in enumerate(PA_CLASS_ORDER):
            for k in range(per_class):
                r = {"plate_appearance_id": f"{s}-{ci}-{k}-{rng.integers(1e9)}", "game_id": f"g{s}-{k % 5}",
                     "game_date": f"{s}-0{1 + (k % 2)}-15", "season": s, "outcome": cls,
                     "batter_canonical_player_uuid": f"b{k%7}", "pitcher_canonical_player_uuid": f"p{k%7}"}
                for f in FEATURE_NAMES:
                    r[f] = float(rng.choice(_CATEG[f])) if f in _CATEG else (float(rng.integers(1, 10)) if f == "context_inning" else float(rng.random()))
                if with_synth:
                    r[SYNTH] = float(ci) + 0.01 * rng.random()   # a genuinely informative synthetic feature
                rows.append(r)
    cols = {k: [r[k] for r in rows] for k in rows[0]}
    fields = [("plate_appearance_id", pa.string()), ("game_id", pa.string()), ("game_date", pa.string()),
              ("season", pa.int16()), ("outcome", pa.string()), ("batter_canonical_player_uuid", pa.string()),
              ("pitcher_canonical_player_uuid", pa.string()), *[(f, pa.float64()) for f in FEATURE_NAMES]]
    if with_synth:
        fields.append((SYNTH, pa.float64()))
    schema = pa.schema(fields)
    return pa.table({k: (pa.array(v, pa.int16()) if k == "season" else v) for k, v in cols.items()}, schema=schema)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    gen3 = tmp_path / "gen3"; gen2 = tmp_path / "gen2"
    monkeypatch.setattr(A, "GEN3_ROOT", gen3)
    monkeypatch.setattr(A, "GEN2_ROOT", gen2)
    monkeypatch.setattr(A, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(A, "ASP_REGISTRY", tmp_path / "registry.json")
    A._VERIFIED_OBJECT_CACHE.clear()
    contracts = C.all_contracts()
    bundle = C.contract_bundle_sha_for("GEN3")
    research = _table(RESEARCH_SEASONS, with_synth=True)
    sealed = _table([2025], per_class=6, seed=9, with_synth=True)
    prov = {"datasetId": C.PARENT_DATASET_ID}
    mr = publish_object(gen3, research, object_kind="research", contracts=contracts, contract_bundle_sha=bundle,
                        provenance_extra={**prov, "seasons": RESEARCH_SEASONS})
    ms = publish_object(gen3, sealed, object_kind="sealed-2025", contracts=contracts, contract_bundle_sha=bundle,
                        provenance_extra={**prov, "seasons": [2025]})
    per_season = {int(s): int(pc.sum(pc.cast(pc.equal(research["season"], s), pa.int64())).as_py()) for s in RESEARCH_SEASONS}
    per_season[2025] = sealed.num_rows
    reg = {"schemaVersion": "MLB_GEN3_REGISTRATION_V1", "contractBundleSha256": bundle,
           "registrationId": f"mlb-pa-gen3-research:sha256:{mr['logicalContentSha256']}",
           "contracts": {k: v["id"] for k, v in contracts.items()},
           "research": {"logicalContentSha256": mr["logicalContentSha256"], "physicalParquetSha256": mr["physicalParquetSha256"],
                        "schemaSha256": mr["schemaSha256"], "rows": research.num_rows, "seasons": RESEARCH_SEASONS},
           "sealed2025": {"logicalContentSha256": ms["logicalContentSha256"], "physicalParquetSha256": ms["physicalParquetSha256"],
                          "rows": sealed.num_rows, "seasons": [2025]},
           "perSeasonRows": {str(k): v for k, v in per_season.items()},
           # Phase 7B advanced feature-set authorized for THIS dataset version (base + synthetic family)
           "featureSets": {"advanced": [*FEATURE_NAMES, SYNTH]}}
    gen3.mkdir(parents=True, exist_ok=True)
    (gen3 / "registration.json").write_text(json.dumps(reg), encoding="utf-8")
    # a minimal Gen-2 registration so catalog() resolves all four entries
    g2r = _table([2023, 2024], with_synth=False)
    g2s = _table([2025], per_class=6, with_synth=False)
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
    A.migrate_registry()
    return {"gen3": gen3, "researchId": reg["registrationId"], "synth": SYNTH}


# ---------------- A. registry sole resolver ----------------
def test_registry_is_sole_resolver_with_four_entries_and_zero_opens(hermetic):
    A.reset_object_open_log()
    cat = A.catalog()
    assert A.object_open_log() == []
    gens = sorted(e["generation"] for e in cat)
    assert gens == ["GEN2", "GEN2_SEALED", "GEN3", "GEN3_SEALED"]
    assert sum(1 for e in cat if e["selectable"]) == 2
    reg = json.loads(A.ASP_REGISTRY.read_text())
    assert reg["schemaVersion"] == "ASP_DATASET_REGISTRY_V3" and reg.get("migrationId")


# ---------------- C. object verifier ----------------
def test_object_verifier_containment_and_tamper(hermetic):
    e = next(x for x in A.catalog() if x["generation"] == "GEN3")
    A._verify_object(e)                      # baseline passes
    A.reset_object_open_log()
    evil = {**e, "objectPath": str(Path("C:/Windows/System32/evil.parquet"))}
    with pytest.raises(A.AuthorityError):
        A._verify_object(evil)
    assert A.object_open_log() == []         # outside-root rejected BEFORE any open
    with pytest.raises(A.AuthorityError):    # forged logical sha
        A._verify_object({**e, "logicalContentSha256": "0" * 64})
    with pytest.raises(A.AuthorityError):    # sealed refused to ordinary capability
        A._verify_object(next(x for x in A.catalog() if x["generation"] == "GEN3_SEALED"))


def test_verification_cache_rejects_same_size_substitution(hermetic):
    e = next(x for x in A.catalog() if x["generation"] == "GEN3")
    path, _ = A._verify_object(e)            # warms the cache
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF             # flip a byte (same size)
    path.write_bytes(bytes(data))
    with pytest.raises(A.AuthorityError):    # physical SHA recomputed -> cache miss -> tamper
        A._verify_object(e)


# ---------------- D/Gate 11. advanced-feature propagation ----------------
def test_advanced_feature_enters_the_canonical_run(hermetic):
    proj = "p7d-prop"
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=hermetic["researchId"])
    base = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                                 hyperparameters={"maxIter": 20}, feature_set="base")
    adv = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                                hyperparameters={"maxIter": 20}, feature_set="advanced")
    assert base["featureSetSha256"] != adv["featureSetSha256"]
    assert base["canonicalEffectiveConfigSha256"] != adv["canonicalEffectiveConfigSha256"]
    assert hermetic["synth"] not in base["featureSet"]
    assert adv["featureSet"].count(hermetic["synth"]) == 1 and adv["featureSet"][-1] == hermetic["synth"]
    ev_base = A.execute(actor="t@asp", project_id=proj, run_authority_id=base["runAuthorityId"])
    ev_adv = A.execute(actor="t@asp", project_id=proj, run_authority_id=adv["runAuthorityId"])
    assert ev_base["preprocessorFingerprint"] != ev_adv["preprocessorFingerprint"]
    assert ev_adv["sealedSeasonsAccessed"] == [] and 2025 not in ev_adv["seasonsInObject"]
    # a client cannot name an unregistered/arbitrary feature set
    with pytest.raises(A.AuthorityError):
        A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                              hyperparameters={"maxIter": 20}, feature_set="arbitrary_injection")


# ---------------- E/Gate 12. canonical 2024-only feature-family ablation ----------------
def test_feature_family_ablation_is_2024_only_and_paired(hermetic):
    proj = "p7d-abl"
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=hermetic["researchId"])
    out = A.run_feature_family_ablation(actor="t@asp", project_id=proj, binding_id=b["bindingId"],
                                        model_family="governed_hgb", control_feature_set="base",
                                        challenger_feature_set="advanced", hyperparameters={"maxIter": 20},
                                        bootstrap_iterations=200)
    assert out["validationSeason"] == 2024 and out["featureFamilyAdded"] == [hermetic["synth"]]
    assert out["controlRunId"] != out["challengerRunId"]
    assert out["controlFeatureSetSha256"] != out["challengerFeatureSetSha256"]
    assert out["uncertainty"]["method"] == "PAIRED_GAME_CLUSTER_BOOTSTRAP" and out["uncertainty"]["iterations"] == 200
    assert "comparisonManifestSha256" in out and "2025" not in json.dumps(out["classConditionalLogLossDelta"])


# ---------------- F/G/Gate 16. evidence + activation integrity ----------------
def test_evidence_activation_and_estimator(hermetic):
    proj = "p7d-evi"
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=hermetic["researchId"])
    au = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                               hyperparameters={"maxIter": 20})
    ev = A.execute(actor="t@asp", project_id=proj, run_authority_id=au["runAuthorityId"]); rid = ev["experimentRunId"]
    assert type(A.load_fitted_estimator(project_id=proj, run_id=rid)).__name__ == "HistGradientBoostingClassifier"
    A.activate_candidate(actor="t@asp", project_id=proj, run_id=rid)
    assert A.get_active_candidate(project_id=proj)["experimentRunId"] == rid
    # fabricated run (no authority/evidence) rejected
    fake = {"experimentRunId": "0" * 32, "status": "COMPLETE", "projectId": proj, "bindingId": b["bindingId"],
            "bindingRevision": b["revision"], "runAuthorityId": "1" * 32, "canonicalEffectiveConfigSha256": "z"}
    A._write_json_atomic(A._state(proj, "runs", "0" * 32 + ".json"), fake)
    with pytest.raises(A.AuthorityError):
        A.activate_candidate(actor="t@asp", project_id=proj, run_id="0" * 32)
    # coordinated child+manifest tamper is caught because the run anchors the manifest sha
    bdir = A._state(proj, "evidence", rid)
    (bdir / "diagnostics.json").write_bytes(b'{"tampered":true}')
    man = json.loads((bdir / "evidence-manifest.json").read_text())
    man["diagnosticsSha256"] = A.sha256_bytes(b'{"tampered":true}')
    man["children"]["diagnostics"]["sha256"] = man["diagnosticsSha256"]
    A._write_json_atomic(bdir / "evidence-manifest.json", man)
    with pytest.raises(A.AuthorityError):
        A.get_active_candidate(project_id=proj)   # manifest sha no longer matches the run anchor


# ---------------- H/Gate 17. authority reconstruction / forgery ----------------
def test_authority_forgery_rejected(hermetic):
    proj = "p7d-auth"
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=hermetic["researchId"])
    au = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                               hyperparameters={"maxIter": 20})
    for field, val in (("generation", "GEN2"), ("bindingRevision", 999), ("seed", 42)):
        forged = {**A.get_run_authority(project_id=proj, run_authority_id=au["runAuthorityId"]), field: val}
        A._write_json_atomic(A._state(proj, "authorities", forged["runAuthorityId"] + ".json"), forged)
        with pytest.raises(A.AuthorityError):
            A.execute(actor="t@asp", project_id=proj, run_authority_id=forged["runAuthorityId"])
        A._write_json_atomic(A._state(proj, "authorities", au["runAuthorityId"] + ".json"), au)  # restore
