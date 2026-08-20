"""FastAPI router for the interactive MLB PA modeling cockpit (Phase 6A).

Every endpoint computes from the real materialized feature view and the shared evaluation
authority. Heavy actions (experiment run, autopilot, simulate) execute synchronously and
return real metrics — there is no fabricated success path.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from . import engine as E
from . import modeling as M
from . import simulation as S
from . import gen3_authority as G3A
from .engine import ALL_FEATURES, CockpitError
from ..security.security_store import require_user
from ..core.modeling_scope import authorize_modeling_scope

router = APIRouter()


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except G3A.StaleAuthorityError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CockpitError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"required artifact unavailable: {exc}")


def _actor(user: dict) -> str:
    return str(user.get("email") or user.get("userId") or user.get("id") or "unknown")


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
            {"role": "development", "seasons": [E.DEV_SEASON], "rows": next(s["rows"] for s in pop["perSeason"] if s["season"] == E.DEV_SEASON)},
            {"role": "validation", "seasons": [E.VAL_SEASON], "rows": next(s["rows"] for s in pop["perSeason"] if s["season"] == E.VAL_SEASON)},
            {"role": "frozen_final", "seasons": [E.FROZEN_SEASON], "rows": next(s["rows"] for s in pop["perSeason"] if s["season"] == E.FROZEN_SEASON)},
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
    return _guard(M.champion_baseline)


@router.post("/cockpit/experiment/run")
def experiment_run(config: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return _guard(M.run_experiment, config)


@router.get("/cockpit/experiments")
def experiments() -> dict[str, Any]:
    return {"experiments": _guard(M.list_experiments), "champion": _guard(M.champion_baseline)}


@router.get("/cockpit/experiments/{experiment_id}")
def experiment(experiment_id: str) -> dict[str, Any]:
    rec = _guard(M.get_experiment, experiment_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return rec


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


@router.post("/cockpit/gen3/run-authority")
def gen3_run_authority(payload: dict[str, Any] = Body(...), user: dict = Depends(require_user)) -> dict[str, Any]:
    pid = authorize_modeling_scope(user, payload.get("projectId"), "edit")
    return _guard(G3A.issue_run_authority, actor=_actor(user), project_id=pid,
                  binding_id=payload.get("bindingId", ""), model_family=payload.get("modelFamily", ""),
                  hyperparameters=payload.get("hyperparameters") or {}, seed=int(payload.get("seed", 20260819)))


@router.post("/cockpit/gen3/execute")
def gen3_execute(payload: dict[str, Any] = Body(...), user: dict = Depends(require_user)) -> dict[str, Any]:
    pid = authorize_modeling_scope(user, payload.get("projectId"), "edit")
    return _guard(G3A.execute, actor=_actor(user), project_id=pid, run_authority_id=payload.get("runAuthorityId", ""))


@router.post("/cockpit/gen3/run-suite")
def gen3_run_suite(payload: dict[str, Any] = Body(...), user: dict = Depends(require_user)) -> dict[str, Any]:
    # Authorized autopilot / tuning: every candidate uses the single server-authorized run path.
    pid = authorize_modeling_scope(user, payload.get("projectId"), "edit")
    return _guard(G3A.run_authorized_suite, actor=_actor(user), project_id=pid,
                  binding_id=payload.get("bindingId", ""), candidates=payload.get("candidates") or [],
                  source=str(payload.get("source", "suite")))


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
    return _guard(G3A.activate_candidate, actor=_actor(user), project_id=pid, run_id=payload.get("runId", ""))


@router.get("/cockpit/gen3/active-candidate/{project_id}")
def gen3_active_candidate(project_id: str, user: dict = Depends(require_user)) -> dict[str, Any]:
    pid = authorize_modeling_scope(user, project_id, "view")
    c = _guard(G3A.get_active_candidate, project_id=pid)
    if c is None:
        raise HTTPException(status_code=404, detail="no active candidate for project")
    return c


@router.post("/cockpit/autopilot")
def autopilot(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    config = payload.get("config") or {}
    budget = payload.get("budget", "standard")
    if budget not in ("quick", "standard", "deep"):
        raise HTTPException(status_code=422, detail="budget must be quick, standard, or deep")
    return _guard(M.run_autopilot, config, budget)


@router.post("/cockpit/simulate")
def simulate(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    config = payload.get("config") or {}
    season = int(payload.get("season", E.VAL_SEASON))
    n_games = int(payload.get("nGames", 60))
    n_sims = int(payload.get("nSims", 200))
    mode = str(payload.get("mode", "quick")).lower()
    if mode == "full":
        return _guard(S.simulate_full_impact, config, season=season, n_games=n_games, n_sims=n_sims)
    return _guard(S.simulate_impact, config, season=season, n_games=n_games, n_sims=n_sims)


@router.post("/cockpit/eligibility")
def eligibility(config: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from . import provider as PROV
    return _guard(PROV.simulator_eligibility, config)


@router.post("/cockpit/provider/verify")
def provider_verify(config: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from . import provider as PROV
    return _guard(PROV.verify_fold_reproduces_model, config)


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
    return _guard(M.run_ablation, payload)


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
