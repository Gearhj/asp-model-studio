"""FastAPI router for the interactive MLB PA modeling cockpit (Phase 6A).

Every endpoint computes from the real materialized feature view and the shared evaluation
authority. Heavy actions (experiment run, autopilot, simulate) execute synchronously and
return real metrics — there is no fabricated success path.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from . import engine as E
from . import modeling as M
from . import simulation as S
from . import gen3_authority as G3A
from .engine import ALL_FEATURES, CockpitError
from .cockpit_dtos import (
    ActiveCandidateResponseV2, ModelCalibrationResponseV2, ModelEvaluationResponseV2,
    ModelRegistryEvidenceResponseV2,
)
from ..security.security_store import require_user
from ..core.modeling_scope import authorize_modeling_scope

router = APIRouter()


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except G3A.BusyError as exc:
        raise HTTPException(status_code=429, detail=str(exc))          # Gate 22 — trusted-local serial bound
    except G3A.StaleAuthorityError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CockpitError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"required artifact unavailable: {exc}")


def _actor(user: dict) -> str:
    return str(user.get("email") or user.get("userId") or user.get("id") or "unknown")


# Phase 7C Gate 11/26 — legacy binding-free model execution and 2025-scoring endpoints are RETIRED. They
# had no project ACL, no active binding, no run authority, and scored the sealed 2025 season. All scientist
# model execution now flows exclusively through the server-authorized Gen-3 path (/cockpit/gen3/*).
_RETIRED_DETAIL = ("This endpoint was retired by the canonical authority cutover (Phase 7C). "
                   "Model execution now flows exclusively through the server-authorized run path "
                   "(/cockpit/gen3/bind -> run-authority -> execute -> activate); 2025 is sealed.")


def _gone(detail: str | None = None):
    raise HTTPException(status_code=410, detail=detail or _RETIRED_DETAIL)


@router.get("/cockpit/objective")
def objective() -> dict[str, Any]:
    return _guard(E.objective_payload)


@router.get("/cockpit/population")
def population() -> dict[str, Any]:
    return _guard(E.population_payload)


@router.get("/cockpit/profile")
def profile(force: bool = False) -> dict[str, Any]:
    return _guard(E.feature_profile, force)


@router.get("/cockpit/data-preview")
def data_preview(season: int | None = None, limit: int = 25, sample: str = "head") -> dict[str, Any]:
    # Gate 22: the preview reads the research object only (2023-2024). The sealed 2025 season is never
    # previewable — even a request for it is refused, and no 2025 row is resident in the engine frame.
    if season is not None and int(season) == E.FROZEN_SEASON:
        raise HTTPException(status_code=410, detail="2025 is sealed; preview is restricted to research seasons (2023-2024).")
    return _guard(E.data_preview, season=season, limit=limit, sample=sample)


@router.get("/cockpit/profile/feature/{name}")
def feature_detail(name: str) -> dict[str, Any]:
    if name not in ALL_FEATURES:
        raise HTTPException(status_code=404, detail=f"unknown feature: {name}")
    return _guard(E.feature_detail, name)


@router.get("/cockpit/correlation")
def correlation() -> dict[str, Any]:
    return _guard(E.correlation_summary)


@router.get("/cockpit/target-analysis")
def target_analysis() -> dict[str, Any]:
    return _guard(E.target_analysis)


@router.post("/cockpit/outliers")
def outliers(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    policy = payload.get("policy") or {"globalMethod": "iqr", "params": {"k": 3.0}}
    features = payload.get("features")
    return _guard(M.outlier_summary, policy, features)


@router.post("/cockpit/missing")
def missing(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    policy = payload.get("policy") or {"globalMethod": "median"}
    features = payload.get("features")
    return _guard(M.missing_summary, policy, features)


@router.get("/cockpit/temporal-split")
def temporal_split() -> dict[str, Any]:
    pop = _guard(E.population_payload)
    return {
        "schemaVersion": E.COCKPIT_SCHEMA_VERSION,
        "policy": "SEASON_HOLDOUT_ROLLING_ORIGIN",
        "supported": [
            {"id": "SEASON_HOLDOUT", "label": "Season holdout", "recommended": True, "active": True},
            {"id": "ROLLING_ORIGIN", "label": "Rolling origin", "recommended": True, "active": False},
            {"id": "EXPANDING_WINDOW", "label": "Expanding window", "recommended": True, "active": False},
            {"id": "DATE_HOLDOUT", "label": "Date holdout", "recommended": False, "active": False},
            {"id": "RANDOM", "label": "Random split", "recommended": False, "active": False,
             "warning": "NOT RECOMMENDED FOR TEMPORAL SPORTS FORECASTING"},
        ],
        "folds": [
            {"role": "development", "seasons": [E.DEV_SEASON], "rows": next((s["rows"] for s in pop["perSeason"] if s["season"] == E.DEV_SEASON), None)},
            {"role": "validation", "seasons": [E.VAL_SEASON], "rows": next((s["rows"] for s in pop["perSeason"] if s["season"] == E.VAL_SEASON), None)},
            # 2025 is a SEALED fold: it is never resident in the research frame; its row count is not exposed here.
            {"role": "frozen_final", "seasons": [E.FROZEN_SEASON], "rows": None, "state": "SEALED"},
        ],
        "leakageGuards": [
            {"guard": "Frozen 2025 excluded from fitting/tuning/selection", "status": "ENFORCED"},
            {"guard": "Fold-local preprocessing (fit on development only)", "status": "ENFORCED"},
            {"guard": "Target column never used as a predictor", "status": "ENFORCED"},
            {"guard": "Prior-season player state only (no same-game future stats)", "status": "ENFORCED_BY_FEATURE_CONTRACT"},
            {"guard": "Identity/game IDs excluded from predictors", "status": "ENFORCED"},
        ],
    }


@router.post("/cockpit/temporal-split/preview")
def temporal_split_preview(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    policy = payload.get("policy") or "SEASON_HOLDOUT"
    boundary_date = payload.get("boundaryDate")
    return _guard(E.temporal_split_preview, policy, boundary_date)


@router.get("/cockpit/model-families")
def model_families() -> dict[str, Any]:
    fams = []
    for fam, available in M.AVAILABLE_FAMILIES.items():
        fams.append(
            {
                "id": fam,
                "label": M.E_family_label(fam),
                "available": available,
                "simulatorEligible": fam in M.SIMULATOR_ELIGIBLE_FAMILIES,
                "status": "AVAILABLE" if available else "NOT_INSTALLED",
            }
        )
    return {"schemaVersion": E.COCKPIT_SCHEMA_VERSION, "families": fams}


@router.get("/cockpit/champion")
def champion() -> dict[str, Any]:
    # Retired: reproduced the champion by fitting and scoring 2025 on the combined object.
    return _gone()


@router.post("/cockpit/experiment/run")
def experiment_run(config: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return _gone()


@router.get("/cockpit/experiments")
def experiments() -> dict[str, Any]:
    return _gone()


@router.get("/cockpit/experiments/{experiment_id}")
def experiment(experiment_id: str) -> dict[str, Any]:
    return _gone()


# ---------------------------------------------------------------- Gen-3 server authority (Phase 7A.1/7A.3)
# Additive. Every route enforces the canonical PROJECT ACL (A2-01): authorize_modeling_scope resolves the
# authorized canonical project id (401 unauth / 403 no permission / 404 unknown project) and ONLY that id
# is passed to the service, which derives an opaque storage key (A2-02). UI = ACTIVE BINDING = RUN
# AUTHORITY = OBJECT RECEIPT = TRAINING = RESULT; StaleAuthorityError -> 409. The D3/C4-serving
# /cockpit/experiment/run path and the sealed 2025 object are never touched. Registration is an explicit
# build/admin action (scripts/phase7a_build_gen3.py), never a route/UI side effect (A2-06/Gate 6).
@router.get("/cockpit/gen3/catalog")
def gen3_catalog(user: dict = Depends(require_user)) -> dict[str, Any]:
    return {"datasets": _guard(G3A.catalog)}


@router.post("/cockpit/gen3/bind")
def gen3_bind(payload: dict[str, Any] = Body(...), user: dict = Depends(require_user)) -> dict[str, Any]:
    pid = authorize_modeling_scope(user, payload.get("projectId"), "edit")
    return _guard(G3A.create_binding, actor=_actor(user), project_id=pid,
                  dataset_version_id=payload.get("datasetVersionId", ""),
                  expected_content_sha=payload.get("expectedContentSha"),
                  expected_revision=payload.get("expectedRevision"))


@router.get("/cockpit/gen3/binding/{project_id}")
def gen3_active_binding(project_id: str, user: dict = Depends(require_user)) -> dict[str, Any]:
    pid = authorize_modeling_scope(user, project_id, "view")
    b = _guard(G3A.active_binding, project_id=pid)
    if b is None:
        raise HTTPException(status_code=404, detail="no active binding for project")
    return b


@router.get("/cockpit/gen3/population/{project_id}")
def gen3_population(project_id: str, user: dict = Depends(require_user)) -> dict[str, Any]:
    # Generation-aware Data & Population authority derived from the active binding (no object opened).
    pid = authorize_modeling_scope(user, project_id, "view")
    p = _guard(G3A.binding_population, project_id=pid)
    if p is None:
        raise HTTPException(status_code=404, detail="no active binding for project")
    return p


# Gate 23 — strict typed request schemas for the canonical Phase 7B execution paths: unknown fields, bool
# masquerading as int, fractional/NaN/Inf integers, and huge/negative values are rejected with 422.
class RunAuthorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectId: StrictStr
    bindingId: StrictStr
    modelFamily: StrictStr
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    seed: StrictInt = Field(default=20260819, ge=0, le=2**32 - 1)
    featureSet: StrictStr = "base"


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectId: StrictStr
    runAuthorityId: StrictStr


class AblationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectId: StrictStr
    bindingId: StrictStr
    modelFamily: StrictStr = "governed_logistic"
    controlFeatureSet: StrictStr = "base"
    challengerFeatureSet: StrictStr
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    seed: StrictInt = Field(default=20260819, ge=0, le=2**32 - 1)
    bootstrapIterations: StrictInt = Field(default=1000, ge=100, le=5000)


@router.post("/cockpit/gen3/run-authority")
def gen3_run_authority(req: RunAuthorityRequest, user: dict = Depends(require_user)) -> dict[str, Any]:
    pid = authorize_modeling_scope(user, req.projectId, "edit")
    return _guard(G3A.issue_run_authority, actor=_actor(user), project_id=pid,
                  binding_id=req.bindingId, model_family=req.modelFamily,
                  hyperparameters=req.hyperparameters, seed=req.seed, feature_set=req.featureSet)


@router.post("/cockpit/gen3/execute")
def gen3_execute(req: ExecuteRequest, user: dict = Depends(require_user)) -> dict[str, Any]:
    pid = authorize_modeling_scope(user, req.projectId, "edit")
    return _guard(G3A.execute, actor=_actor(user), project_id=pid, run_authority_id=req.runAuthorityId)


@router.post("/cockpit/gen3/run-suite")
def gen3_run_suite(payload: dict[str, Any] = Body(...), user: dict = Depends(require_user)) -> dict[str, Any]:
    # Authorized autopilot / tuning: every candidate uses the single server-authorized run path.
    pid = authorize_modeling_scope(user, payload.get("projectId"), "edit")
    return _guard(G3A.run_authorized_suite, actor=_actor(user), project_id=pid,
                  binding_id=payload.get("bindingId", ""), candidates=payload.get("candidates") or [],
                  source=str(payload.get("source", "suite")))


@router.post("/cockpit/gen3/feature-family-ablation")
def gen3_feature_family_ablation(req: AblationRequest, user: dict = Depends(require_user)) -> dict[str, Any]:
    # Gate 12 — canonical 2024-only feature-family ablation (control vs challenger differ only by the
    # registered feature-family contract); paired game-cluster bootstrap; immutable comparison manifest.
    pid = authorize_modeling_scope(user, req.projectId, "edit")
    return _guard(G3A.run_feature_family_ablation, actor=_actor(user), project_id=pid, binding_id=req.bindingId,
                  model_family=req.modelFamily, control_feature_set=req.controlFeatureSet,
                  challenger_feature_set=req.challengerFeatureSet, hyperparameters=req.hyperparameters,
                  seed=req.seed, bootstrap_iterations=req.bootstrapIterations)


@router.get("/cockpit/gen3/runs/{project_id}")
def gen3_runs(project_id: str, user: dict = Depends(require_user)) -> dict[str, Any]:
    pid = authorize_modeling_scope(user, project_id, "view")
    return {"runs": _guard(G3A.list_runs, project_id=pid)}


@router.get("/cockpit/gen3/run/{project_id}/{run_id}")
def gen3_run(project_id: str, run_id: str, user: dict = Depends(require_user)) -> dict[str, Any]:
    pid = authorize_modeling_scope(user, project_id, "view")
    return _guard(G3A.get_run, project_id=pid, run_id=run_id)


@router.post("/cockpit/gen3/activate")
def gen3_activate(payload: dict[str, Any] = Body(...), user: dict = Depends(require_user)) -> dict[str, Any]:
    pid = authorize_modeling_scope(user, payload.get("projectId"), "edit")
    return _guard(G3A.activate_candidate, actor=_actor(user), project_id=pid, run_id=payload.get("runId", ""),
                  expected_binding_revision=payload.get("expectedBindingRevision"))


# B9 / Gate 9 — the four scientific reads return STRICT, versioned, backend-authoritative V2 DTOs
# (extra="forbid"). A renamed/missing/misnested/unexpected field fails construction here (a fail-closed
# server error), never a silently-truncated "successful" payload. All are resolved only through the canonical
# chain verifier in the service layer; 2025 never appears. The TypeScript client compiles against these exact
# shapes (src/sports/cockpit/cockpitApiV2.ts).
@router.get("/cockpit/gen3/active-candidate/{project_id}", response_model=ActiveCandidateResponseV2)
def gen3_active_candidate(project_id: str, user: dict = Depends(require_user)) -> ActiveCandidateResponseV2:
    pid = authorize_modeling_scope(user, project_id, "view")
    c = _guard(G3A.get_active_candidate, project_id=pid)
    if c is None:
        raise HTTPException(status_code=404, detail="no active candidate for project")
    r = c["run"]
    return ActiveCandidateResponseV2(
        status=str(c.get("status", "ACTIVE")), runId=c["runId"], runAuthorityId=r["runAuthorityId"],
        datasetVersionId=r["datasetVersionId"], generation=r["generation"], modelFamily=r["modelFamily"],
        developmentSeasons=list(r["developmentSeasons"]), developmentRows=int(r["developmentRows"]),
        validationSeason=int(r["validationSeason"]), validationRows=int(r["validationRows"]),
        runReceiptSha256=r["runReceiptSha256"], bundleManifestSha256=r["bundleManifestSha256"],
        bindingId=c["bindingId"], bindingRevision=int(c["bindingRevision"]),
        activationRevision=int(c["activationRevision"]), activatedAt=c["activatedAt"],
        preprocessingContractId=r["preprocessingContractId"])


@router.get("/cockpit/gen3/evaluation/{project_id}", response_model=ModelEvaluationResponseV2)
def gen3_evaluation(project_id: str, user: dict = Depends(require_user)) -> ModelEvaluationResponseV2:
    # Gate 9/18/19 — Evaluation consumes the active candidate's immutable 2024-validation evidence bundle
    # (verified aggregate + per-class + confusion + reliability + independent log-loss recompute). Never a
    # browser result; never 2025.
    pid = authorize_modeling_scope(user, project_id, "view")
    ev = _guard(G3A.active_candidate_evaluation, project_id=pid)
    if ev is None:
        raise HTTPException(status_code=404, detail="no active candidate for project")
    return ModelEvaluationResponseV2.model_validate(ev)


@router.get("/cockpit/gen3/calibration/{project_id}", response_model=ModelCalibrationResponseV2)
def gen3_calibration(project_id: str, user: dict = Depends(require_user)) -> ModelCalibrationResponseV2:
    # Gate 9/19 — Calibration honestly reports the RAW / uncalibrated condition + the candidate's raw
    # 2024-validation reliability curves from the verified V2 bundle. No fabricated calibrator; never 2025.
    pid = authorize_modeling_scope(user, project_id, "view")
    cal = _guard(G3A.active_candidate_calibration, project_id=pid)
    if cal is None:
        raise HTTPException(status_code=404, detail="no active candidate for project")
    return ModelCalibrationResponseV2.model_validate(cal)


@router.get("/cockpit/gen3/registry-evidence/{project_id}", response_model=ModelRegistryEvidenceResponseV2)
def gen3_registry_evidence(project_id: str, user: dict = Depends(require_user)) -> ModelRegistryEvidenceResponseV2:
    # Gate 9 — the active candidate's immutable registry record + model card: content-addressed identities and
    # digests resolved from the verified V2 bundle/receipt (never inferred, never decorative). Never 2025.
    pid = authorize_modeling_scope(user, project_id, "view")
    reg = _guard(G3A.active_candidate_registry_evidence, project_id=pid)
    if reg is None:
        raise HTTPException(status_code=404, detail="no active candidate for project")
    return ModelRegistryEvidenceResponseV2.model_validate(reg)


@router.get("/cockpit/gen3/recompute/{project_id}/{run_id}")
def gen3_recompute(project_id: str, run_id: str, user: dict = Depends(require_user)) -> dict[str, Any]:
    # Independent validation log-loss recomputation from the persisted prediction/target artifacts (Gate 29).
    pid = authorize_modeling_scope(user, project_id, "view")
    return _guard(G3A.recompute_validation_logloss, project_id=pid, run_id=run_id)


@router.post("/cockpit/autopilot")
def autopilot(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    # Retired: binding-free autopilot scored 2025. Use the authorized /cockpit/gen3/run-suite.
    return _gone()


@router.post("/cockpit/simulate")
def simulate(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    # Retired: binding-free whole-game simulation accepted the sealed 2025 season and used local config.
    return _gone("Authoritative simulation impact is not configured for this candidate. The legacy "
                 "binding-free simulator (which accepted 2025) was retired by the Phase 7C cutover.")


@router.post("/cockpit/eligibility")
def eligibility(config: dict[str, Any] = Body(...)) -> dict[str, Any]:
    # Retired with the legacy simulator (fed it a binding-free config).
    return _gone()


@router.post("/cockpit/provider/verify")
def provider_verify(config: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return _gone()


@router.get("/cockpit/segmentation/summary")
def seg_summary(population: str = "BATTERS") -> dict[str, Any]:
    from . import segmentation as SEG
    return _guard(SEG.population_summary, population)


@router.post("/cockpit/segmentation/kmeans")
def seg_kmeans(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    from . import segmentation as SEG
    return _guard(SEG.run_kmeans, payload.get("population", "BATTERS"), payload.get("features") or [],
                  int(payload.get("kMin", 2)), int(payload.get("kMax", 10)))


@router.post("/cockpit/segmentation/pca")
def seg_pca(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    from . import segmentation as SEG
    return _guard(SEG.pca_scatter, payload.get("population", "BATTERS"), payload.get("features") or [], int(payload.get("k", 4)))


@router.post("/cockpit/segmentation/dbscan")
def seg_dbscan(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    from . import segmentation as SEG
    eps = payload.get("eps")
    min_samples = payload.get("minSamples")
    return _guard(SEG.run_dbscan, payload.get("population", "BATTERS"), payload.get("features") or [],
                  float(eps) if eps else None, int(min_samples) if min_samples else None)


@router.get("/cockpit/segmentation/grid-guidance")
def seg_grid_guidance(population: str = "BATTERS") -> dict[str, Any]:
    from . import segmentation as SEG
    return _guard(SEG.grid_guidance, population)


@router.post("/cockpit/segmentation/stability")
def seg_stability(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    from . import segmentation as SEG
    return _guard(SEG.cluster_stability, payload.get("population", "BATTERS"), payload.get("features") or [], int(payload.get("k", 4)))


@router.post("/cockpit/segmentation/grid")
def seg_grid(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from . import segmentation as SEG
    return _guard(SEG.grid_3x3, payload.get("population", "BATTERS"), payload["dimX"], payload["dimY"])


@router.get("/cockpit/feature/kinds")
def feature_kinds() -> dict[str, Any]:
    from . import features_builder as FB
    return {
        "schemaVersion": E.COCKPIT_SCHEMA_VERSION,
        "kinds": list(FB.FEATURE_KINDS),
        "calendarSubkinds": list(FB.CALENDAR_SUBKINDS),
        "calendarUnavailable": list(FB.CALENDAR_UNAVAILABLE),
        "baseFeatures": list(E.ALL_FEATURES),
    }


@router.post("/cockpit/feature/profile")
def feature_profile_engineered(spec: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from . import features_builder as FB
    return _guard(FB.profile_engineered, spec)


@router.post("/cockpit/feature/ablation")
def feature_ablation(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    # Retired (Gate 21): the legacy ablation fit two models and used the sealed-2025 delta in its verdict.
    return _gone("Feature ablation is not configured on the canonical authority in this phase. The legacy "
                 "ablation (which scored 2025 and used it in the verdict) was retired by the Phase 7C cutover.")


@router.get("/cockpit/feature-catalog")
def feature_catalog() -> dict[str, Any]:
    """Available sports feature families in the governed data plus honestly-labeled roadmap."""
    return {
        "schemaVersion": E.COCKPIT_SCHEMA_VERSION,
        "available": [
            {"family": "Game context", "features": list(E.CONTEXT_FEATURES), "status": "AVAILABLE"},
            {"family": "Batter prior state", "features": list(E.BATTER_FEATURES), "status": "AVAILABLE"},
            {"family": "Pitcher prior state", "features": list(E.PITCHER_FEATURES), "status": "AVAILABLE"},
        ],
        "roadmap": [
            {"family": "Calendar / schedule (day/week/month, All-Star, postseason)", "status": "DERIVABLE_NEXT"},
            {"family": "Handedness / platoon", "status": "DERIVABLE_NEXT"},
            {"family": "Pitch-sequence (E1) / batter-pitcher interaction (E2)", "status": "RESEARCHED_MARGINAL"},
            {"family": "Rest / workload (participation layer)", "status": "AVAILABLE_IN_PARTICIPATION_LAYER"},
            {"family": "Premium contact quality", "status": "UNAVAILABLE_PREMIUM"},
            {"family": "Umpire", "status": "UNAVAILABLE"},
            {"family": "Weather", "status": "UNAVAILABLE"},
            {"family": "Park factors", "status": "UNAVAILABLE"},
            {"family": "Manager tendencies", "status": "UNAVAILABLE"},
        ],
    }
