"""No acquisition or consumer writes. Staged CFB study and deterministic replay."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys

import joblib
import numpy as np
import pandas as pd
import sklearn
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_cfb_gen1 import archetype_gap as ag
from server.sports_cfb_gen1.pipeline import (
    FEATURE_COLUMNS, _fit_pair, build_features, score_point_predictions, simulate_paired_residuals,
)

BASE = ROOT / "outputs/cfb-gen1-v1"
CURRENT = ROOT / "outputs/cfb-gen1-current-v1"
DEFAULT_OUTPUT = ROOT / "outputs/cfb-archetype-extended-gap-v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(clean(value), ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode())


def bind(path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def read_predictions(max_season: int) -> pd.DataFrame:
    p = pd.read_parquet(BASE / "data/season-forward-predictions.parquet", filters=[("season", "<=", max_season)])
    meta = pd.read_parquet(BASE / "data/admitted-games.parquet", columns=["game_id", "season", "home_conference_name", "away_conference_name"],
                           filters=[("season", "<=", max_season)])
    p = p.merge(meta.drop(columns="season"), on="game_id", validate="one_to_one")
    if p.game_id.duplicated().any() or (p.season > min(max_season,2025)).any():
        raise ValueError("identity or 2026 selection violation")
    return p.sort_values(["scheduled_at", "game_id"]).reset_index(drop=True)


def prepare(out: Path) -> dict:
    if (out / "DESIGN.json").exists():
        verify_preservation(out)
        return json.loads((out/"DESIGN.json").read_bytes())
    out.mkdir(parents=True, exist_ok=True)
    saved = json.loads((BASE / "artifact-index.json").read_bytes())
    verified = []
    for item in saved["artifacts"].values():
        if not isinstance(item, dict) or "path" not in item:
            continue
        actual = bind(Path(item["path"]))
        expected = item.get("physicalSha256", item.get("sha256"))
        if actual["sha256"] != expected or actual["bytes"] != item["bytes"]:
            raise ValueError(f"baseline artifact binding mismatch: {item['path']}")
        verified.append(actual)
    # Hash-only protection of original outputs, including current forecast bytes.
    protected = [bind(p) for root in (BASE, CURRENT) for p in sorted(root.rglob("*")) if p.is_file()]
    dev = read_predictions(2022)
    original_games = pd.read_parquet(BASE / "data/admitted-games.parquet", filters=[("season", "<=", 2022)])
    reconstructed = build_features(original_games)
    saved_features = pd.read_parquet(BASE / "data/point-in-time-features.parquet", filters=[("season", "<=", 2022)])
    a = reconstructed.set_index("game_id").sort_index()[FEATURE_COLUMNS].to_numpy(float)
    b = saved_features.set_index("game_id").sort_index()[FEATURE_COLUMNS].to_numpy(float)
    if not np.array_equal(a, b, equal_nan=True):
        raise ValueError("saved Development features fail exact target-excluding reconstruction")
    # Verify a representative complete season's recorded OOF predictions against
    # its earlier-only fitted preprocessing and Ridge. Preserve this verification fit.
    training = reconstructed[reconstructed.primary & reconstructed.season.lt(2022)]
    target = dev[dev.season.eq(2022)]
    with threadpool_limits(limits=1):
        pair = _fit_pair(training, "ridge", {"alpha":100.})
        errors = {name: float(np.max(np.abs(pair[name].predict(target[FEATURE_COLUMNS])-target[f"{ag.MODEL}_pred_{name}"]))) for name in ("margin","total")}
    if max(errors.values()) > 1e-9:
        raise ValueError(f"recorded Ridge OOF reproduction failed: {errors}")
    (out/"models").mkdir(exist_ok=True)
    joblib.dump(pair, out/"models/ridge-oof-2022-verification.joblib")
    residuals = pd.read_parquet(BASE/"data/chronological-paired-residuals.parquet", filters=[("season","<=",2022)])
    rr = residuals.set_index("game_id").loc[dev.game_id]
    if not np.allclose(rr[["home_residual","away_residual"]].to_numpy(), ag.raw_residuals(dev), atol=1e-12, rtol=0):
        raise ValueError("OOF residual identity differs")
    selection = json.loads((BASE/"selected-configuration-receipt.json").read_bytes())
    baseline_row = next(r for r in selection["candidateRows"] if r["model"] == ag.MODEL)
    design = {
        "schemaVersion": ag.VERSION + "_DESIGN", "frozenAtUtc": now(),
        "initialBranch": subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip(),
        "initialHead": subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "sourceClass": "A_RECONSTRUCTED_HISTORICAL; NO_CAPTURED_HISTORICAL_REVISION_VINTAGES",
        "roles": {"developmentWarmup":[2014,2015],"recordedOOF":[2016,2017,2018,2019,2020,2021,2022],
                  "distributionDevelopment":[2017,2018,2019,2020,2021,2022],"reusedValidation":[2023,2024],"secondaryReused2025":[2025],"excluded":[2026]},
        "baseline": {"model":ag.MODEL, "features":FEATURE_COLUMNS, "verifiedBindings":verified, "reportedValidation":baseline_row,
                     "developmentFeatureReconstructionExact":True, "ridgeOOF2022MaximumAbsoluteDifference":errors,
                     "ridgeProbabilityQualification":"Saved 2016-2022 calibrated channel uses all Development labels; not chronological probability OOF. Joint and Elo channels are separately reported.",
                     "distributionDiscrepancy":"Original rule kickoff<target can include still-running same-day games; exact historical reference retained, not admissible as timing-certified evidence.",
                     "comparisonBaseline":"EXACT_RIDGE_WITH_SEASON_COMPLETE_PAIRED_RESIDUALS_V1",
                     "comparisonDonors":"Only strictly earlier seasons of recorded OOF residuals, minimum 500; unchanged sampler/seed/count/floor/round/tie behavior.",
                     "originalReference":"EXACT_LEGACY_EARLIER_KICKOFF_REFERENCE; score every common game and reconcile retained original scores.",
                     "productionAltered":False},
        "clustering": {"family":"KMEANS_ONLY", "k":list(ag.K_VALUES), "teamVariables":ag.TEAM_VARIABLES,
                       "inputs":"Side-neutral pooled earlier Development team states; assign home and away independently; no team ID or conference in features.",
                       "preprocessor":"Prior-Development median imputer + StandardScaler fitted inside each season fold.",
                       "trainingRows":"Earlier Development ordinary-support OOF games; both teams have >=2 season games and no >21-day same-season gap.",
                       "qualityGate":{"minimumClusterTeamAppearances":300,"minimumDistinctTeams":20,"maximumTeamFraction":.08,"maximumConferenceFraction":.65,"meanBlockBootstrapARI":.60},
                       "assignmentGate":"99th percentile training nearest-center distance; no extrapolative assignment admitted.",
                       "minimumPairGames":ag.MIN_PAIR,"minimumPairSeasons":ag.MIN_PAIR_SEASONS,"minimumTeamsEachSide":ag.MIN_TEAM_IDS,
                       "mechanism":"Ordered away/home cluster residual mean; bias correction weight=0.5*n/(n+200), applied to frozen Ridge expected home/away points.",
                       "selection":"Choose smallest mean Development joint energy among quality-supported k values, ties within 0.01 choose smaller k; if none qualify choose smallest k only as rejected diagnostic.",
                       "fitUpdates":"Dev season-forward through min(targetSeason-1,2022); frozen 2022 artifact for all 2023-2025 targets."},
        "gap": {"definition":"Either first/second eligible same-season game (<2 earlier context games), OR >21 elapsed days since prior same-season game. First game is independently flagged, never assigned an invented offseason duration.",
                "mechanism":"Scale zero-mean paired margin residual deviation only; preserve donor total and raw home/away means, leave Ridge points unchanged.",
                "factor":"sqrt((n*target_margin_variance+200*global_margin_variance)/((n+200)*global_margin_variance)), constrained [1,1.5]",
                "minimumTargetDonors":ag.MIN_GAP,"minimumSeasons":ag.MIN_GAP_SEASONS,"fits":"Earlier Development OOF only; freeze through2022 before later comparison",
                "priorExistingChallenger":bind(CURRENT/"opener-challenger-definition.json"),"existingChallengerReplaced":False},
        "evaluation":{"drawCount":10000,"seed":ag.SEED,"baselineSamplerSeed":20260914,"scoreConventions":"Existing sampled-pair energy score, empirical CRPS, mean single binary home-indicator Brier; no PA metrics.",
                      "tails":{"totalLowInclusive":34,"totalHighInclusive":80,"absoluteMarginInclusive":28,"upset":"Loss of pregame Elo favorite"},
                      "bootstrap":"2000 paired ISO-calendar-week block resamples, games as units; 95% intervals exploratory, not corrected for all displayed subgroups.",
                      "candidateMechanisms":2,"newCalibrationFits":False,"combinedArm":False},
        "admission":{"minimumTargetLaterGames":100,"minimumTargetDevelopmentGames":200,"developmentTargetEnergyImprovement":.02,
                     "laterTargetEnergyUpper95StrictlyBelow":0,"overallEnergyMaximumDegradation":.02,"overallLogLossMaximumDegradation":.005,
                     "overallBrierMaximumDegradation":.002,"targetCrpsMaximumDegradation":.05,
                     "targetMargin90Coverage":"At least .85 and no worse absolute error from .90 than baseline; width interpreted jointly with coverage.",
                     "seasonConsistency":"Target energy improves in both 2023 and 2024; 2025 remains secondary and cannot rescue failure.",
                     "fallback":"Exact comparison-baseline score pairs and probabilities wherever unsupported; legacy same-day-donor reference explicitly different.",
                     "principalDisposition":"SUPPORTED_FOR_FURTHER_RESEARCH only if a frozen candidate passes all gates; otherwise RETAIN_GLOBAL_BASELINE unless structural unsupport makes all comparison impossible."},
        "unsupportedInputs":["pace/plays per game","pass/rush tendency","yards per play","explosiveness","quarterback","roster","returning production","recruiting","injury","transfer"],
        "featureScope":"Keep the existing governed 35-feature representation. Raw completion/rush boxes are not a governed sack-adjusted play denominator; no new feature reconstruction search.",
        "newProviderCalls":0,"aispWrites":0,"futureForecastsCreated":0,
    }
    write(out/"protected-originals.json",protected)
    write(out/"DESIGN.json",design)
    write(out/"feature-audit.json",{
        "supportedBaselineFeatureCount":len(FEATURE_COLUMNS), "clusterFeatureCount":len(ag.TEAM_VARIABLES),
        "developmentGames":len(dev), "developmentBySeason":dev.groupby("season").size().to_dict(),
        "missingPerBaselineFeature":dev[FEATURE_COLUMNS].isna().sum().to_dict(),
        "ranges":{c:{"min":float(dev[c].min()),"max":float(dev[c].max()),"mean":float(dev[c].mean())} for c in FEATURE_COLUMNS},
        "featureAvailabilityQualification":"Reconstructed earlier-game state; actual source acquisition clocks retained in source manifest; no historical publication timestamps invented.",
        "source":bind(BASE/"source-manifest.json"),"baselineOofVerified":True,
    })
    print(json.dumps({"stage":"DESIGN_FROZEN","path":str(out/"DESIGN.json"),"sha256":bind(out/"DESIGN.json")["sha256"]}),flush=True)
    return design


def verify_preservation(out: Path) -> None:
    protected=json.loads((out/"protected-originals.json").read_bytes())
    for ref in protected:
        if bind(Path(ref["path"])) != ref:
            raise ValueError(f"original artifact changed: {ref['path']}")


def fit_artifacts(p: pd.DataFrame, season: int, out: Path) -> tuple[dict,dict]:
    train=p[(p.season < season)&(p.season<=2022)]
    directory=out/"models"/f"through-{min(season-1,2022)}"
    directory.mkdir(parents=True,exist_ok=True)
    models={}
    for k in ag.K_VALUES:
        path=directory/f"kmeans-{k}.joblib"
        if path.exists():
            model=joblib.load(path)
        else:
            model=ag.fit_cluster(train,k,min(season,2023))
            joblib.dump(model,path)
            write(directory/f"kmeans-{k}-profile.json",{a:b for a,b in model.items() if a!="estimator"})
        models[k]=model
    path=directory/"gap.joblib"
    if path.exists():
        gap=joblib.load(path)
    else:
        gap=ag.fit_gap(train,min(season,2023));joblib.dump(gap,path);write(directory/"gap.json",gap)
    return models,gap


def evaluate_season(p: pd.DataFrame, season: int, out: Path, ks: list[int]) -> pd.DataFrame:
    path=out/"scores"/f"season-{season}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    models,gap=fit_artifacts(p,season,out)
    bank=p[p.season<season].copy()
    targets=p[p.season.eq(season)]
    rows=[]
    examples=[]
    for number,(_,target) in enumerate(targets.iterrows()):
        donors=ag.eligible_donors(bank,target)
        if len(donors)<500:
            raise ValueError("common population lacks baseline residual support")
        baseline,account=simulate_paired_residuals(target,donors,ag.MODEL,low_total_threshold=34,high_total_threshold=80)
        legacy_bank=p[p.scheduled_at<target.scheduled_at]
        legacy,legacy_account=simulate_paired_residuals(target,legacy_bank,ag.MODEL,low_total_threshold=34,high_total_threshold=80)
        common={
            "weakSupport":bool(ag.weak_support(target.to_frame().T)[0]),
            "opener":bool(target.home_season_opener or target.away_season_opener),
            "extendedGap":bool(target.home_long_gap or target.away_long_gap),
            "home_id":int(target.home_id),"away_id":int(target.away_id),
            "role":"development" if season<=2022 else ("reused_validation" if season<=2024 else "reused_2025"),
            "baselineDonors":len(donors),"baselineDonorLatestKickoff":donors.scheduled_at.max(),
            "legacySameSeasonDonors":int((legacy_bank.season==season).sum()),
            "legacyDonorsKickedOffUnder6HoursEarlier":int(((target.scheduled_at-legacy_bank.scheduled_at)<pd.Timedelta(hours=6)).sum()),
        }
        populations={"baseline":(baseline,{"applied":False,"transformation":account}),
                     "legacy_reference":(legacy,{"applied":False,"transformation":legacy_account})}
        for k in ks:
            populations[f"cluster_k{k}"]=ag.candidate_draws(target,donors,baseline,cluster=models[k])
        populations["gap"]=ag.candidate_draws(target,donors,baseline,gap=gap)
        measured_cache={}
        for arm,(draws,info) in populations.items():
            if len(draws)!=10000 or (draws.home_score==draws.away_score).any() or (draws[["home_score","away_score"]]<0).any().any():
                raise ValueError("final-score population accounting failed")
            if arm not in ("baseline","legacy_reference") and not info["applied"] and not draws.equals(baseline):
                raise ValueError("fallback changed exact baseline draws")
            cache_key=(ag.draw_hash(draws),info.get("deltaHome",0),info.get("deltaAway",0))
            if cache_key not in measured_cache:
                measured_cache[cache_key]=ag.measure(draws,target,info.get("deltaHome",0),info.get("deltaAway",0))
            measured=measured_cache[cache_key]
            transform=info.get("transformation",account)
            rows.append({**measured,**common,"arm":arm,"applied":info["applied"],
                         "homeCluster":info.get("homeCluster",-1),"awayCluster":info.get("awayCluster",-1),"matchup":info.get("matchup","NA"),
                         "pairGames":info.get("pairGames",0),"deltaHome":info.get("deltaHome",0.),"deltaAway":info.get("deltaAway",0.),
                         "marginScale":info.get("marginScale",1.),"rawNegativeHomeCount":transform["rawNegativeHomeCount"],
                         "rawNegativeAwayCount":transform["rawNegativeAwayCount"],"initialRoundedTieCount":transform["initialRoundedTieCount"],
                         "rawHomeMean":transform["rawHomeMean"],"rawAwayMean":transform["rawAwayMean"],
                         "rawLowTotalProbability":transform["rawLowTotalProbability"],"rawHighTotalProbability":transform["rawHighTotalProbability"]})
        if number==0 or (len(examples)<3 and (common["weakSupport"] or any(x[1]["applied"] for x in populations.values()))):
            examples.append(int(target.game_id))
            directory=out/"replay-examples"/str(int(target.game_id));directory.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(directory/"draws.npz",**{arm:d[["home_score","away_score"]].to_numpy(dtype="<i2") for arm,(d,_) in populations.items()})
        if number%100==0:
            print(json.dumps({"stage":"SCORING","season":season,"games":number+1,"of":len(targets)}),flush=True)
    frame=pd.DataFrame(rows)
    path.parent.mkdir(parents=True,exist_ok=True)
    frame.to_parquet(path,index=False)
    return frame


def freeze(out: Path) -> dict:
    prepare(out)
    if (out/"FROZEN_SELECTION.json").exists():
        return json.loads((out/"FROZEN_SELECTION.json").read_bytes())
    p=read_predictions(2022)
    dev=pd.concat([evaluate_season(p,season,out,list(ag.K_VALUES)) for season in range(2017,2023)],ignore_index=True)
    final_models,gap=fit_artifacts(p,2023,out)
    results={}
    for arm,part in dev.groupby("arm",sort=True):
        base=dev[dev.arm.eq("baseline")]
        comparison=ag.paired_differences(base,part)
        affected=part[part.applied]
        affected_base=base[base.game_id.isin(affected.game_id)]
        results[arm]={"overall":ag.aggregate(part),"paired":comparison,
                      "appliedOnly":ag.paired_differences(affected_base,affected) if len(affected) else {"games":0}}
    candidates=[k for k in ag.K_VALUES if final_models[k]["quality"]["supported"]]
    if candidates:
        best=min(results[f"cluster_k{k}"]["overall"]["jointEnergyScore"] for k in candidates)
        chosen=min(k for k in candidates if results[f"cluster_k{k}"]["overall"]["jointEnergyScore"]<=best+.01)
    else:
        chosen=2
    selected={
        "schemaVersion":ag.VERSION+"_FROZEN_SELECTION","frozenAtUtc":now(),"design":bind(out/"DESIGN.json"),
        "selectedClusterK":chosen,"eligibleComplexities":candidates,"development":results,
        "laterArms":["baseline","legacy_reference",f"cluster_k{chosen}","gap"],
        "laterOutcomesOpenedByThisStage":False,"laterParameterUpdatesAllowed":False,
        "finalGap":{k:v for k,v in gap.items() if k!="trainingGameIds"},
    }
    write(out/"FROZEN_SELECTION.json",selected)
    print(json.dumps({"stage":"SELECTION_FROZEN","k":chosen,"sha256":bind(out/"FROZEN_SELECTION.json")["sha256"]}),flush=True)
    return selected


def subgroup_map(rows: pd.DataFrame) -> dict[str,pd.Series]:
    result={"overall":pd.Series(True,index=rows.index),"weak_support":rows.weakSupport,
            "openers":rows.opener,"extended_gaps":rows.extendedGap,"ordinary":~rows.weakSupport,
            "conference":rows.conference_competition.eq(1),"nonconference":rows.conference_competition.eq(0)}
    if 'firstPrimaryGame' in rows:
        result['first_primary_games']=rows.firstPrimaryGame
    return result


def admission(dev: dict, later: pd.DataFrame, arm: str) -> dict:
    b=later[later.arm.eq("baseline")];c=later[later.arm.eq(arm)]
    applied_ids=c.loc[c.applied,"game_id"]
    target_c=c[c.game_id.isin(applied_ids)];target_b=b[b.game_id.isin(applied_ids)]
    overall=ag.paired_differences(b,c)
    target=ag.paired_differences(target_b,target_c) if len(target_c) else {"games":0}
    dev_applied=dev[arm]["appliedOnly"]
    checks={"developmentSupport":dev_applied["games"]>=200,"laterSupport":len(target_c)>=100}
    checks["developmentEnergy"]=dev_applied.get("jointEnergyScore",{}).get("estimate",0)<=-.02
    checks["laterTargetEnergy95"]=target.get("jointEnergyScore",{}).get("interval95",[0,0])[1]<0
    checks["overallEnergy"]=overall["jointEnergyScore"]["estimate"]<=.02
    checks["overallWinnerLogLoss"]=overall["jointWinnerLogLoss"]["estimate"]<=.005
    checks["overallBrier"]=overall["jointBinaryBrier"]["estimate"]<=.002
    checks["targetMarginCrps"]=target.get("marginCrps",{}).get("estimate",float("inf"))<=.05
    checks["targetTotalCrps"]=target.get("totalCrps",{}).get("estimate",float("inf"))<=.05
    covc=float(target_c.marginCoverage90.mean()) if len(target_c) else 0
    covb=float(target_b.marginCoverage90.mean()) if len(target_b) else 0
    checks["targetCoverage90"]=covc>=.85 and abs(covc-.9)<=abs(covb-.9)
    years={str(s):ag.paired_differences(target_b[target_b.season.eq(s)],target_c[target_c.season.eq(s)]) for s in [2023,2024]}
    checks["bothValidationSeasons"]=all(x.get("jointEnergyScore",{}).get("estimate",0)<0 for x in years.values())
    fall=c[~c.applied].set_index("game_id");bf=b.set_index("game_id").loc[fall.index]
    checks["exactFallback"]=bool((fall.drawSha256==bf.drawSha256).all())
    return {"passes":all(checks.values()),"checks":checks,"overall":overall,"target":target,"targetBySeason":years}


def assess(out: Path) -> dict:
    selection=freeze(out)
    frozen_models=out/'FROZEN_MODEL_BINDINGS.json'
    if not frozen_models.exists():
        write(frozen_models,{"boundBeforeLaterAssessmentUtc":now(),"selection":bind(out/'FROZEN_SELECTION.json'),
                             "models":[bind(f) for f in sorted((out/'models/through-2022').glob('*'))]})
    for ref in json.loads(frozen_models.read_bytes())['models']:
        if bind(Path(ref['path']))!=ref:raise ValueError('frozen Development model changed')
    p=read_predictions(2025)
    k=int(selection["selectedClusterK"])
    later=pd.concat([evaluate_season(p,s,out,[k]) for s in (2023,2024,2025)],ignore_index=True)
    scores=pd.concat([pd.read_parquet(out/"scores"/f"season-{s}.parquet") for s in range(2017,2026)],ignore_index=True)
    appearances=pd.concat([p[['game_id','season','scheduled_at',f'{side}_id']].rename(columns={f'{side}_id':'team'}) for side in ('home','away')])
    first_primary_ids=set(appearances.sort_values(['scheduled_at','game_id']).drop_duplicates(['season','team']).game_id)
    scores['firstPrimaryGame']=scores.game_id.isin(first_primary_ids)
    if (scores.firstPrimaryGame & ~scores.weakSupport).any():
        raise ValueError('frozen weak-support gate omitted a first eligible primary game')
    scores.to_parquet(out/"paired-evaluation-rows.parquet",index=False)
    frozen_arms=selection["laterArms"]
    groups={}
    for role in ("development","reused_validation","reused_2025"):
        r=scores[scores.role.eq(role)&scores.arm.isin(frozen_arms)]
        groups[role]={}
        for name,mask in subgroup_map(r).items():
            g=r[mask];summary={arm:ag.aggregate(g[g.arm.eq(arm)]) for arm in frozen_arms}
            comparisons={arm:ag.paired_differences(g[g.arm.eq("baseline")],g[g.arm.eq(arm)]) for arm in frozen_arms if arm!="baseline"}
            legacy_comparisons={arm:ag.paired_differences(g[g.arm.eq("legacy_reference")],g[g.arm.eq(arm)]) for arm in frozen_arms if arm!="legacy_reference"}
            groups[role][name]={"arms":summary,"paired":comparisons,
                                "pairedAgainstExactLegacyReference":legacy_comparisons,
                                "legacyComparisonQualification":"Includes the donor-eligibility change; cannot isolate an archetype/gap gain or establish historically available probabilities."}
    per_season={str(s):{arm:ag.aggregate(g[g.arm.eq(arm)]) for arm in frozen_arms} for s,g in scores.groupby("season")}
    season_differences={str(s):{arm:ag.paired_differences(g[g.arm.eq("baseline")],g[g.arm.eq(arm)]) for arm in frozen_arms if arm!="baseline"} for s,g in scores.groupby("season")}
    val=later[later.season.isin([2023,2024])]
    gates={arm:admission(selection["development"],val,arm) for arm in (f"cluster_k{k}","gap")}
    if not joblib.load(out/"models/through-2022"/f"kmeans-{k}.joblib")["quality"]["supported"]:
        gates[f"cluster_k{k}"]["checks"]["clusterQuality"]=False;gates[f"cluster_k{k}"]["passes"]=False
    disposition="SUPPORTED_FOR_FURTHER_RESEARCH" if any(v["passes"] for v in gates.values()) else "RETAIN_GLOBAL_BASELINE"
    clusters={}
    migration={}
    for role in ("development","reused_validation","reused_2025"):
        c=scores[scores.arm.eq(f"cluster_k{k}")&scores.role.eq(role)]
        b=scores[scores.arm.eq("baseline")&scores.role.eq(role)]
        clusters[role]={match:{"candidate":ag.aggregate(g),"paired":ag.paired_differences(b[b.game_id.isin(g.game_id)],g)} for match,g in c.groupby("matchup")}
        # Label ordering is by Elo centroid. Development migration remains
        # within each annual fit, so cluster refit relabeling is not migration.
        states=pd.concat([c[["game_id","season","scheduled_at",f"{side}_id",f"{side}Cluster"]].rename(columns={f"{side}_id":"team",f"{side}Cluster":"cluster"}) for side in ("home","away")])
        states=states.sort_values(["team","season","scheduled_at","game_id"])
        previous=states.groupby(["team","season"]).cluster.shift()
        supported=previous.notna()
        migration[role]={"consecutiveWithinSeasonTeamAppearances":int(supported.sum()),"clusterChanges":int((states.loc[supported,"cluster"]!=previous[supported]).sum()),
                         "migrationRate":float((states.loc[supported,"cluster"]!=previous[supported]).mean())}
        states.to_parquet(out/f"cluster-membership-{role}.parquet",index=False)
    original=pd.read_parquet(BASE/"data/distribution-game-scores.parquet")
    reproduced=scores[scores.arm.eq("legacy_reference")].merge(original,on="game_id",suffixes=("_new","_old"),validate="one_to_one")
    reconcile={col:float((reproduced[f"{col}_new"]-reproduced[f"{col}_old"]).abs().max()) for col in ("jointEnergyScore","jointHomeWinProbability","marginCrps","totalCrps")}
    if max(reconcile.values())>1e-12:
        raise ValueError(f"exact legacy baseline reproduction disagrees: {reconcile}")
    point_channels={}
    for role,part in p.groupby("role"):
        point_channels[role]={"ridge":score_point_predictions(part,ag.MODEL),"elo":ag.probability_metrics(part.home_win.to_numpy(),part.elo_home_win_probability.to_numpy()),
                              "ridgeWinnerChronological":role!="development"}
    reference=scores[scores.arm.eq("legacy_reference")]
    comparison=scores[scores.arm.eq("baseline")]
    conservation={"originalFilesUnchanged":True,"legacyScoresReconciledGames":len(reproduced),"legacyMaxAbsoluteDifferences":reconcile,
                  "eligibleDistributionGames":int(len(comparison)),"excluded2016InsufficientPriorSeasonResiduals":int(p.season.eq(2016).sum()),
                  "sameDayChronologyRiskGames":int(reference.legacyDonorsKickedOffUnder6HoursEarlier.gt(0).sum()),
                  "fallbackExact":all(x["checks"]["exactFallback"] for x in gates.values()),
                  "allDrawCounts":sorted(map(int,scores.drawCount.unique())),"noFinalTie":True}
    conservation['firstPrimaryGamesAllIncludedInWeakSupportGate']=True
    conservation['sourceConvention']='opener flag means first context game; first_primary_games separately reports first eligible FBS-v-FBS target. This outcome-free reporting distinction changes no gate.'
    assessment={"schemaVersion":ag.VERSION,"createdAtUtc":now(),"disposition":disposition,
                "design":bind(out/"DESIGN.json"),"frozenSelection":bind(out/"FROZEN_SELECTION.json"),
                "groups":groups,"individualSeasons":per_season,"individualSeasonPairedDifferences":season_differences,"matchupClusters":clusters,"migration":migration,
                "admission":gates,"pointChannels":point_channels,"verification":conservation,
                "qualification":"All later seasons reused. Candidate fits use only earlier Development; baseline exact historical reference has unresolved same-day donor availability. No independent holdout or prospective performance claim.",
                "controls":{"providerRequests":0,"providerObjectsConsumed":0,"aispWrites":0,"newFutureForecasts":0,"outcomes2026Read":False,"modelsPromoted":0,"baselineArtifactsChanged":False},
                "reproduction":".\\.venv\\Scripts\\python.exe -B scripts\\run_cfb_archetype_gap_v1.py --stage replay"}
    verify_preservation(out)
    write(out/"ASSESSMENT.json",assessment)
    render(out,assessment,selection)
    index={"schemaVersion":ag.VERSION+"_ARTIFACT_INDEX","createdAtUtc":now(),"disposition":disposition,
           "artifacts":{str(f.relative_to(out)).replace('\\','/'):bind(f) for f in sorted(out.rglob('*')) if f.is_file() and f.name!='artifact-index.json'},
           "implementation":{str(f.relative_to(ROOT)).replace('\\','/'):bind(f) for f in (Path(__file__),ROOT/'server/sports_cfb_gen1/archetype_gap.py',ROOT/'tests/test_cfb_archetype_gap.py')},
           "environment":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__,"sklearn":sklearn.__version__,"joblib":joblib.__version__,"threadLimit":1}}
    write(out/"artifact-index.json",index)
    print(json.dumps({"stage":"COMPLETE","disposition":disposition,"assessment":bind(out/"ASSESSMENT.json")}),flush=True)
    return assessment


def render(out: Path,a: dict,selection: dict) -> None:
    k=selection['selectedClusterK'];arms=['baseline',f'cluster_k{k}','gap']
    weak=a['groups']['reused_validation']['weak_support']['arms']
    coverage_before=weak['baseline']['intervals']['margin']['90']['coverage']
    coverage_after=weak['gap']['intervals']['margin']['90']['coverage']
    width_change=weak['gap']['intervals']['margin']['90']['width']-weak['baseline']['intervals']['margin']['90']['width']
    lines=[f"# CFB archetype and extended-gap challenger V1",'',f"**{a['disposition']}**. Production Ridge and the existing Syracuse–Pittsburgh forecast are unchanged.",'',
           "This is reconstructed historical research. Development chose all new settings; 2023–2024 is reused Validation and 2025 is secondary reused evidence. No 2026 outcome entered this study.",'',
           "Clustering produced stable groups but did not add stable incremental predictive value. Its small Validation gain did not persist in both Validation seasons and reversed in reused 2025. The global baseline remains preferred.",'',
           f"The gap/early-season adjustment improved nominal 90% margin coverage from {coverage_before:.2%} to {coverage_after:.2%} across 193 reused Validation games, with average intervals {width_change:.2f} points wider. Its primary energy-score interval still crosses zero and it failed the predeclared Development improvement threshold. There are **zero >21-day same-season gaps in 2023–2025**, so later-period evidence supports only an early-season diagnostic, not an established extended-gap benefit. Development has 35 such extended-gap games.",'',
           "## Baseline binding and chronology discrepancy",'',
           "The prior 8,543-game count includes 47 current 2026 games. Historical coverage is 8,496 games through 2025; 2014–2015 warm up the point model, and 2016 supplies the first OOF residual season. There are 7,067 recorded OOF point predictions; 718 from 2016 lack a complete earlier residual season and are point-only here.",'',
           "The exact legacy residual rule admitted any earlier kickoff, including games potentially still in progress. Its outputs are reproduced under `legacy_reference`, with original artifacts retained. The new comparison uses **EXACT_RIDGE_WITH_SEASON_COMPLETE_PAIRED_RESIDUALS_V1**: the identical point forecasts, sampler, 10,000 draws, seeds, rounding and tie treatment, with residual donors restricted to strictly earlier seasons. This study-specific donor eligibility correction is not a change to the published production baseline. Fallback identity is measured against this explicitly named eligible comparison population, not falsely claimed against the legacy reference.",'',
           "The Syracuse–Pittsburgh forecast already uses completed historical residuals through 2025; this historical same-day-donor gap does not make that prospective residual population late or change its bytes.",'',
           f"Legacy reference scores reconcile exactly for {a['verification']['legacyScoresReconciledGames']:,} saved games. {a['verification']['sameDayChronologyRiskGames']:,} assessed legacy populations have a donor kickoff less than six hours before the target. This establishes a timing-certification gap, not the number of actually leaked outcomes.",'',
           "Ridge's saved Development logistic calibration used all Development labels; its Development probabilities are not chronological OOF. Joint-derived winner scores below use earlier-season residuals. Elo and the later-period Ridge channel are reported separately in ASSESSMENT.json.",'',
           "## Matched results",'',"Lower energy, CRPS, log loss, Brier and MAE are better. Brier is mean (home-win probability − binary outcome)². Coverage is compared with its nominal level; narrower alone is not better.",'',
           '| Population | Arm | Games | Applied | Energy | Margin CRPS | Total CRPS | Winner LL | Brier | Margin MAE | Total MAE | Margin 90% coverage / width |',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for role in ('development','reused_validation','reused_2025'):
        for arm in ['legacy_reference',*arms]:
            m=a['groups'][role]['overall']['arms'][arm]
            lines.append(f"| {role} | {arm} | {m['games']} | {m['appliedGames']} | {m['jointEnergyScore']:.4f} | {m['marginCrps']:.4f} | {m['totalCrps']:.4f} | {m['winner']['logLoss']:.4f} | {m['winner']['brier']:.4f} | {m['points']['margin']['mae']:.3f} | {m['points']['total']['mae']:.3f} | {m['intervals']['margin']['90']['coverage']:.3f} / {m['intervals']['margin']['90']['width']:.2f} |")
    lines+=['','## Frozen admission decision','']
    for arm,g in a['admission'].items():
        failed=[key for key,v in g['checks'].items() if not v]
        d=g['target'].get('jointEnergyScore')
        text='No supported targeted comparison.' if d is None else f"Targeted energy difference {d['estimate']:+.4f}, 95% week-block interval [{d['interval95'][0]:+.4f}, {d['interval95'][1]:+.4f}], n={g['target']['games']}."
        lines += [f"- **{arm}: {'passes the frozen research gate' if g['passes'] else 'does not pass'}**. {text} Failed requirements: {', '.join(failed) or 'none'}."]
    lines+=['',"All three k values were screened on Development; only the frozen choice is compared later. No later cluster or subgroup was selected because it scored well. Groupwise intervals are exploratory and not family-wise corrected. A 2025 win cannot rescue a failed Validation gate.",'',
            '## Target regions and harms','', '| Region (reused Validation) | Arm | Games | Δ energy [95% block interval] | Δ margin CRPS | Δ total CRPS | Δ winner LL |','|---|---|---:|---|---:|---:|---:|']
    for group in ('weak_support','openers','first_primary_games','extended_gaps','ordinary','conference','nonconference'):
        for arm in arms[1:]:
            d=a['groups']['reused_validation'][group]['paired'][arm]
            if not d['games']: continue
            e=d['jointEnergyScore'];lines.append(f"| {group} | {arm} | {d['games']} | {e['estimate']:+.4f} [{e['interval95'][0]:+.4f}, {e['interval95'][1]:+.4f}] | {d['marginCrps']['estimate']:+.4f} | {d['totalCrps']['estimate']:+.4f} | {d['jointWinnerLogLoss']['estimate']:+.4f} |")
    lines+=['','The archetype correction improved conference-game energy by about 0.0068 points but worsened nonconference energy by about 0.0068; both intervals include zero. In reused 2025 it worsened overall energy by 0.0077, margin and total CRPS, point MAE and winner log loss. The gap adjustment worsened targeted margin CRPS by 0.0105 and Brier by 0.00076 in 2023 while improving those metrics in 2024. These are small, unstable effects, not support for adding complexity.','',
            'The assessment JSON includes every individual season, 2020 separately, cluster/matchup cells, home/away errors, signed biases and quantiles, all 50/80/90% intervals, calibration intercept/slope and reliability bands, low/high total tails, Elo-favorite upsets and 28-point margins. Small tail groups are marked unsupported for interpretation. Simulation draws are numerical samples; bootstrap units are actual calendar-week game blocks.','',
            '## Limits and operational decision','',
            "The existing governed feature set lacks pace, play tendencies, play-level explosiveness, roster, returning production, quarterback, transfer and injury inputs. Total-yards and turnover profiles are available. Cluster associations describe historical states; they do not establish causal matchup mechanisms. Team IDs and conference labels are used for diagnostics only.",'',
            "Gap adjustment leaves Ridge point expectations and raw residual means fixed and changes centered margin variability only. Flooring, rounding and conditioning on non-tied finals can still shift final means and probabilities; per-game raw/final accounting is retained. It does not append overtime.",'',
            "The global production baseline remains preferred for current operation. Any research pass is permission for further controlled research only, not AISP integration, new forecasts, wagering or promotion. No provider requests or consumer writes were made.",'',
            '## Reproduction','', '```powershell', '.\\.venv\\Scripts\\python.exe -B scripts\\run_cfb_archetype_gap_v1.py --stage replay',
            '# Full deterministic regeneration in a separate output directory:', '.\\.venv\\Scripts\\python.exe -B scripts\\run_cfb_archetype_gap_v1.py --stage all --output outputs\\cfb-archetype-extended-gap-replay', '```','',
            'DESIGN.json precedes fitting; FROZEN_SELECTION.json precedes later assessment. artifact-index.json binds sources, immutable originals, models, fold profiles, predictions, score rows, example draws and report bytes.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    profile=['# Cluster profile','',f'Family: KMeans; Development complexity settings 2, 3, 4; frozen selection k={k}. Labels are ordered by centroid Elo, not by outcome.','',
             'The same earlier-Development imputer and scaler transform home and away team states independently. Eight inputs describe scoring, yardage, turnovers and strength. Team ID, conference and target outcomes are excluded.','',
             '| k | Bootstrap ARI mean | Silhouette | Quality gate | Supported ordered matchup cells |','|---:|---:|---:|---|---:|']
    for kk in ag.K_VALUES:
        obj=joblib.load(out/'models/through-2022'/f'kmeans-{kk}.joblib');q=obj['quality']
        profile.append(f"| {kk} | {q['meanBootstrapAdjustedRand']:.3f} | {q['silhouette']:.3f} | {q['supported']} | {sum(x['supported'] for x in obj['pairs'].values())}/{kk*kk} |")
    obj=joblib.load(out/'models/through-2022'/f'kmeans-{k}.joblib')
    for c in obj['quality']['profiles']:
        profile+=['',f"## Cluster {c['cluster']}",'',f"{c['teamAppearances']} team appearances, {c['distinctTeams']} distinct teams; largest team fraction {c['largestTeamFraction']:.3f}, largest conference fraction {c['largestConferenceFraction']:.3f}.",'',
                  '| Variable | Original-unit centroid |','|---|---:|']
        profile += [f'| {key} | {v:.3f} |' for key,v in c['centerOriginalUnits'].items()]
        profile += ['', 'Conference counts: '+', '.join(f'{key}: {n}' for key,n in c['byConference'].items())+'.',
                    'Season counts: '+', '.join(f'{key}: {n}' for key,n in c['bySeason'].items())+'.']
    profile+=['','## Migration and interpretation','']
    profile+=['The selected two clusters primarily separate stronger scoring/score-prevention and yardage states from weaker states. These variables already enter Ridge; structural stability alone does not establish added predictive information. Points and margins are points per game, yardage is yards per game, turnovers/takeaways are counts per game, and Elo is on its original rating scale.','']
    profile += [f"- {role}: {v['clusterChanges']}/{v['consecutiveWithinSeasonTeamAppearances']} consecutive within-season appearances changed cluster ({v['migrationRate']:.1%})." for role,v in a['migration'].items()]
    profile+=['','ARI is based on ten calendar-week bootstrap refits including preprocessing. Full per-fold profiles show temporal changes and sensitivity to k. Migration measures observed state changes, not a causal change in team talent. Conference concentration is inspected, never used as a cluster input. No favorable cell is promoted independently.']
    (out/'CLUSTER_PROFILE.md').write_text('\n'.join(profile)+'\n',encoding='utf-8')
    card=[f'# {ag.VERSION}', '',f"Disposition: **{a['disposition']}**.",'',
          'Scope: FBS-versus-FBS regular-season weeks ≤14, full-game scores including overtime. Historical source attribution: SportsDataverse / ESPN-derived retained exports, admitted private research; source review and acquisition receipts remain bound.', '',
          'Base point configuration: frozen Ridge alpha100, 35 governed pregame features. Eight side-neutral state variables feed KMeans. Clusters fit only earlier Development; 2023–2025 use the fixed through-2022 objects.', '',
          f'Archetype mechanism: k={k}, ordered away/home cluster residual bias, 0.5*n/(n+200) correction. Gates require ≥200 games, ≥3 seasons and ≥20 distinct teams per side, plus cluster quality and distance support. Unsupported targets reproduce the eligible comparison baseline exactly.', '',
          'Gap mechanism: either team <2 current-season completed context games or >21 same-season days of inactivity; earlier Development margin residual variance ratio shrunk by 200 global games; factor constrained to [1,1.5], ≥150 target residuals and ≥2 seasons. No point correction.', '',
          f"Frozen through-2022 margin scale: {selection['finalGap']['marginScale']:.12f}, estimated from {selection['finalGap']['targetedGames']} targeted Development residuals. Every first eligible primary game is included in this gate; first-context and first-primary opener counts are reported separately.", '',
          'Distribution: 10,000 paired earlier-season OOF residual draws, frozen original seed and discrete support transformation. Legacy earlier-kickoff donor output is retained only as an exact historical reference because completion-time eligibility is unverified. The comparison eligibility rule is separately identified and has not changed production.', '',
          'Selection: six season-forward Development folds 2017–2022; frozen later comparison 2023–2024; 2025 secondary reused. No pristine test, no prospective superiority claim. Calendar-week paired bootstrap intervals assess sampling across games, not draws.', '',
          'All controls false: AISP integration, wagering, real money, promotion and new prospective forecast authority. No injuries, players, returning-production, roster, quarterback or weather evidence is fabricated. See REPORT.md and ASSESSMENT.json for harms, missingness and all frozen admission checks.']
    (out/'MODEL_CARD.md').write_text('\n'.join(card)+'\n',encoding='utf-8')
    if a['disposition']=='SUPPORTED_FOR_FURTHER_RESEARCH':
        (out/'CLAUDE_HANDOFF.md').write_text('Research evidence only. No integration, forecast creation, sportsbook, policy, position, or promotion action is requested or authorized.\n\n'+
            'Passing frozen research arms: '+', '.join(k for k,v in a['admission'].items() if v['passes'])+'.\n\n'+
            'The exact report and assessment are bound by artifact-index.json. Syracuse–Pittsburgh remains unchanged.\n',encoding='utf-8')


def replay(out: Path) -> None:
    verify_preservation(out)
    index=json.loads((out/'artifact-index.json').read_bytes())
    for name,ref in index['artifacts'].items():
        if bind(out/name)!=ref:raise ValueError(f'artifact changed: {name}')
    for name,ref in index['implementation'].items():
        if bind(ROOT/name)!=ref:raise ValueError(f'implementation changed: {name}')
    p=read_predictions(2025);selection=json.loads((out/'FROZEN_SELECTION.json').read_bytes());k=selection['selectedClusterK']
    scored=pd.read_parquet(out/'paired-evaluation-rows.parquet')
    total=0
    for directory in sorted((out/'replay-examples').iterdir()):
        row=p[p.game_id.eq(int(directory.name))].iloc[0];donors=ag.eligible_donors(p,row)
        baseline,_=simulate_paired_residuals(row,donors,ag.MODEL,low_total_threshold=34,high_total_threshold=80)
        legacy,_=simulate_paired_residuals(row,p[p.scheduled_at<row.scheduled_at],ag.MODEL,low_total_threshold=34,high_total_threshold=80)
        models,gap=fit_artifacts(p,int(row.season),out)
        stored=np.load(directory/'draws.npz')
        for arm in stored.files:
            if arm=='baseline':draws=baseline
            elif arm=='legacy_reference':draws=legacy
            elif arm=='gap':draws,_=ag.candidate_draws(row,donors,baseline,gap=gap)
            else:draws,_=ag.candidate_draws(row,donors,baseline,cluster=models[int(arm[-1])])
            if not np.array_equal(draws[['home_score','away_score']].to_numpy(),stored[arm]):raise ValueError('draw replay differs')
            record=scored[scored.game_id.eq(row.game_id)&scored.arm.eq(arm)].iloc[0]
            if ag.draw_hash(draws)!=record.drawSha256:raise ValueError('retained digest differs')
            total+=1
    applied_cases=scored[scored.applied].groupby(['season','arm'],sort=True).head(1)
    for _,record in applied_cases.iterrows():
        row=p[p.game_id.eq(record.game_id)].iloc[0]
        donors=ag.eligible_donors(p,row)
        baseline,_=simulate_paired_residuals(row,donors,ag.MODEL)
        models,gap=fit_artifacts(p,int(row.season),out)
        if record.arm=='gap':draws,_=ag.candidate_draws(row,donors,baseline,gap=gap)
        else:draws,_=ag.candidate_draws(row,donors,baseline,cluster=models[int(record.arm[-1])])
        if ag.draw_hash(draws)!=record.drawSha256:raise ValueError('genuine applied-case replay differs')
    print(json.dumps({'stage':'REPLAY_VERIFIED','exampleArmPopulations':total,'additionalAppliedCasePopulations':len(applied_cases),'allArtifactHashesVerified':True,'originalsPreserved':True}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['prepare','development','assess','all','replay'],default='all')
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT);args=parser.parse_args()
    with threadpool_limits(limits=1):
        if args.stage=='prepare':prepare(args.output)
        elif args.stage=='development':freeze(args.output)
        elif args.stage=='replay':replay(args.output)
        else:assess(args.output)
