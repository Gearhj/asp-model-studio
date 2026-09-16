"""Report frozen V19 clusters and semantic priors after all global folds finish.

This is a reader of saved research assets, not a fitting/inference runner. The
cluster object's saved label permutation is read to align metadata correctly;
the frozen semantic transformer runs once per validation fold for actual branch
coverage. No global estimator or candidate prediction array is loaded. Final incremental
performance is admitted only through a completed meta-study package reference.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import joblib
import numpy as np
import pandas as pd

from reproduce_mlb_v19_baseline import BASE, load_safe_cache
from run_mlb_v19_study import join_teams
from server.sports_current_statcast.mlb_regime_baseline import sha_file
from server.sports_current_statcast.mlb_v19_models import CLUSTER_COORDINATES, DOMAINS
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER

OUT = ROOT / "outputs/mlb-v19-current-state-specialists-v1"
DEST = OUT / "cluster-cold-start"
GAME_MAP = OUT / "game-context/sha256/b94fa31772a6d79e5f8b80ec414e0ec8b41a2dcf36b65c3fae9dba0e47bcfd9a/game-context.parquet"
GAME_SHA = "9a642b0f373ef27bb684f46304661929843e9d60bef8188d2341c6373790296d"
SPEC = OUT / "feature-quality/sha256/8e88e564a2e12e754f8c723d39a1864ef9bb4589b57c14134fe55063d2a98f25/cold-start-specification.json"
ATLAS = OUT / "baseline-atlas/sha256/d1b27325f5c2d0ac2ef048e282578cca12b5e09cb95827145a428fc594312b73/baseline-failure-atlas.json"


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return jsonable(value.tolist())
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def reference(path):
    path = path.resolve()
    return {"path": str(path), "sha256": sha_file(path), "bytes": path.stat().st_size}


def checked(entry):
    path = Path(entry["path"]).resolve()
    if not path.is_relative_to(OUT):
        raise ValueError("Only research-namespace fitted cluster artifacts are permitted")
    if path.stat().st_size != entry["bytes"] or sha_file(path) != entry["sha256"]:
        raise ValueError("Saved cluster artifact checksum/byte mismatch: " + str(path))
    return path


def store(name, value):
    raw = value.encode("utf-8") if isinstance(value, str) else canonical_json_bytes(jsonable(value))
    sha = hashlib.sha256(raw).hexdigest()
    path = DEST / "sha256" / sha / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Immutable report collision")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return reference(path)


def mean_feature_definitions():
    fields = []
    for domain, identity in DOMAINS.items():
        for outcome in PA_CLASS_ORDER:
            fields.append({"feature": f"v19_{domain}_p_{outcome}", "domain": domain,
                "kind": "HIERARCHICAL_CLASS_COMPOSITION_POSTERIOR_MEAN", "identityField": identity,
                "definition": f"(current prior-date {outcome} count + learned-decay prior-season counts + alpha*training-prefix population probability) / (effective prior-date exposure + alpha)",
                "meanPredictor": True, "uncertaintyOnly": False})
        fields.extend([
            {"feature": f"v19_{domain}_log_exposure", "domain": domain, "kind": "EXPOSURE",
             "identityField": identity, "definition": "log1p(current-season strictly prior-date PA count + sum of prior three season counts weighted by learned decay**lag)", "meanPredictor": True, "uncertaintyOnly": False},
            {"feature": f"v19_{domain}_archive_no_observation", "domain": domain, "kind": "SEMANTIC_ARCHIVE_ABSENCE",
             "identityField": identity, "definition": "No recorded current/prior-three-season PA in the bounded archive; explicitly not no career or rookie status", "meanPredictor": True, "uncertaintyOnly": False},
            {"feature": f"v19_{domain}_low_exposure", "domain": domain, "kind": "RELATIVE_EXPOSURE",
             "identityField": identity, "definition": "Effective decay-weighted prior exposure is smaller than the training-fitted concentration alpha", "meanPredictor": True, "uncertaintyOnly": False},
        ])
    return fields


def center_description(domain, values):
    if domain in {"BATTER", "STARTER_PROPENSITY", "RELIEVER_PROPENSITY", "TEAM_OFFENSE", "TEAM_DEFENSE"}:
        summary = []
        for suffix in ("STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "BIP_OUT"):
            key = next(key for key in values if key.endswith("_" + suffix))
            summary.append(f"{suffix}={values[key]:.4f}")
        return "; ".join(summary) + "; these are posterior-profile centroids, not outcome rates measured on validation"
    return "; ".join(f"{key}={value:.4f}" for key, value in values.items())


def unavailable_reasons(frame, labels, domain, fitted):
    absent = labels < 0
    if not fitted:
        return {"UNFITTED_DOMAIN": int(absent.sum())}
    if domain.endswith("PROPENSITY"):
        role = pd.to_numeric(frame.pitcher_gs_per_g, errors="coerce").to_numpy(dtype=float)
        known = np.isfinite(role)
        applies = role >= .5 if domain.startswith("STARTER") else role < .5
        return {"INAPPLICABLE_HISTORICAL_ROLE": int((absent & known & ~applies).sum()),
                "UNKNOWN_HISTORICAL_ROLE_PRIOR": int((absent & ~known).sum()),
                "OTHER_UNSUPPORTED_COORDINATES": int((absent & known & applies).sum())}
    return {"UNSUPPORTED_COORDINATES": int(absent.sum())}


def distribution(values):
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite semantic coverage values")
    return {"minimum": float(values.min()), "p25": float(np.quantile(values, .25)),
            "median": float(np.median(values)), "p75": float(np.quantile(values, .75)),
            "maximum": float(values.max()), "mean": float(values.mean())}


def semantic_coverage(asset, history, validation, expected_means, expected_uncertainty):
    """One frozen feature transform, no new parameters or global predictions."""
    means, uncertainty = asset.transform(history, validation)
    if list(means.columns) != expected_means or list(uncertainty.columns) != expected_uncertainty:
        raise ValueError("Semantic transform output ordering differs from persisted schema")
    if not np.isfinite(means.to_numpy()).all() or not np.isfinite(uncertainty.to_numpy()).all():
        raise ValueError("Actual semantic treatment coverage contains unhandled missing/nonfinite values")
    records = []
    for domain, identity in DOMAINS.items():
        absent = means[f"v19_{domain}_archive_no_observation"].to_numpy() == 1
        low = means[f"v19_{domain}_low_exposure"].to_numpy() == 1
        exposure = np.expm1(means[f"v19_{domain}_log_exposure"].to_numpy())
        dispersion = uncertainty[f"v19_{domain}_posterior_dispersion_only"].to_numpy()
        if np.any(exposure < 0) or np.any(dispersion < 0):
            raise ValueError("Negative semantic exposure or posterior dispersion")
        branches = {"NO_RECORDED_ARCHIVE_OBSERVATION": absent,
                    "ARCHIVE_OBSERVED_LOW_EFFECTIVE_EXPOSURE": ~absent & low,
                    "ARCHIVE_OBSERVED_SUFFICIENT_EFFECTIVE_EXPOSURE": ~absent & ~low}
        if sum(int(mask.sum()) for mask in branches.values()) != len(validation):
            raise ValueError("Semantic branch accounting is not exhaustive")
        count = lambda mask: {"PAs": int(mask.sum()), "games": int(validation.loc[mask, "canonicalGameId"].nunique()),
                              "distinctEntities": int(validation.loc[mask, identity].nunique())}
        records.append({"domain": domain, "identityField": identity, "validationPAs": len(validation),
            "validationDistinctEntities": int(validation[identity].nunique()),
            "mutuallyExclusiveBranches": {name: count(mask) for name, mask in branches.items()},
            "flagCounts": {"archive_no_observation": int(absent.sum()), "low_exposure": int(low.sum()),
                           "flagsMayOverlap": True},
            "effectiveExposureDistribution": distribution(exposure),
            "effectiveExposureDefinition": "Continuous decay-weighted exposure recovered from expm1(saved transform log_exposure); not an integer event-count assertion",
            "zeroEffectiveExposure": count(exposure == 0),
            "archivePresentButEffectiveExposureZero": count(~absent & (exposure == 0)),
            "posteriorDispersionOnlyDistribution": distribution(dispersion),
            "dispersionExcludedFromAllMeanModels": True,
            "baselineAnnualPriorMissingUsedToDefineTheseBranches": False,
            "careerOrRookieStatusInferred": False,
            "sourceHistoryAdmission": "Authenticated physically separated Development history; strictly prior game-date entity counts, unchanged training-fitted hyperparameters"})
    return records


def final_incremental_evidence():
    package_path = OUT / "evaluation/meta-study-package.json"
    if not package_path.exists():
        return {"status": "PENDING_COMPLETE_META_EVALUATION", "candidatePerformanceRead": False,
                "reason": "Cluster geometry/stability is not evidence of predictive improvement."}
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if package.get("matchedRows") != 494432 or package.get("matchedGames") != 6570:
        raise ValueError("Final evaluation does not identify the fixed matched population")
    entry = package["evaluationArtifacts"]["incrementalClusterComparison"]
    path = checked(entry)
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if set(evidence) != {"raw", "calibrated"}:
        raise ValueError("Incremental control must retain both equivalent probability scales")
    for scale in evidence:
        if evidence[scale]["observations"] != 494432 or evidence[scale]["games"] != 6570:
            raise ValueError("Incremental cluster comparison changed the matched population")
    return {"status": "COMPLETED_DECLARED_INCREMENTAL_CONTROL", "metaPackage": reference(package_path),
            "artifact": entry, "candidatePerformanceRead": True,
            "baselineControl": "REGIME_HGB", "clusterCandidate": "REGIME_CLUSTER_HGB",
            "comparison": evidence,
            "interpretation": "Raw compares the fixed global regime model with versus without cluster coordinates. Calibrated compares their independently earlier-OOF-calibrated outputs. Neither ARI nor visible centroid differences establishes predictive value."}


def markdown(document, artifact):
    lines = ["# V19 fitted clusters and semantic cold-start evidence", "",
             "This report reads completed research assets only. No cluster, scaler, prior, global model or calibration parameter is fitted or selected here.", "",
             f"Full machine evidence: `{artifact['path']}`; SHA-256 `{artifact['sha256']}`.", "",
             "## Actual fitted additions versus proposed policies", "",
             "The actual additions are 44 mean-prediction features: four domains (batter, pitcher, batting-team offense, fielding-team defense), each with eight class-composition posterior means, log effective exposure, bounded-archive no-observation state and low-exposure state. The original 246-field V18 contract and its frozen prior treatment remain separate. A semantic specification for all 246 fields is not 246 new fitted treatments.", "",
             "Four posterior-dispersion quantities are computed separately and excluded from every mean feature ordering. Their formula is the sum of class posterior variances, using the fitted concentration and effective prior exposure. They are not an empirically validated game-score interval adjustment. New source-derived workload, availability, transactions, weather and lineup-vintage quantities were not inserted into these historical fits.", "",
             "Counts are strictly prior game-date, excluding the entire current date. The decay-weighted current/prior-three-season archive is not a complete-career claim. Unknown source history is not a zero opportunity, and role identity is not medical availability.", "",
             "| Fold | Domain | Alpha | Carryover decay | Decay status | Hyperparameter sample PAs | Full training PAs |", "|---|---|---:|---:|---|---:|---:|"]
    for fold in document["folds"]:
        for domain, params in fold["semanticPriors"]["parameters"].items():
            lines.append(f"| {fold['fold']} | {domain} | {params['alpha']:.6f} | {params['decay']:.6f} | {params['decayStatus']} | {params['sampleRows']:,} | {params['trainingRows']:,} |")
    lines += ["", "Fold 1 cannot estimate previous-season decay from its single-season training prefix; its zero carryover is explicitly unidentifiable, not a learned finding that prior seasons have no value. Subsequent parameter values above are the saved training fits, never choices made using validation performance.", "",
             "## Fold-local geometry and stability", "",
              "Each supported domain uses one predeclared three-cluster KMeans system with training-only scaling and an outcome-independent hash-capped training sample. The table's ARI compares an earlier training subprefix system and the full training system on a later training subset; it is not validation performance or a cross-fold identity correspondence.", "",
              "| Fold | Domain | Training-sample PAs | Validation PAs supported | Validation PAs unavailable/inapplicable | Subprefix ARI | Sample-to-validation proportion TV |", "|---|---|---:|---:|---:|---:|---:|"]
    for fold in document["folds"]:
        for domain in fold["clusters"]:
            ari = "unavailable" if domain.get("subprefixStabilityARI") is None else f"{domain['subprefixStabilityARI']:.6f}"
            tv = "unavailable" if domain.get("sampleToValidationTotalVariation") is None else f"{domain['sampleToValidationTotalVariation']:.6f}"
            lines.append(f"| {fold['fold']} | {domain['domain']} | {domain.get('trainingSamplePAs', 0):,} | {domain['validationSupportedPAs']:,} | {domain['validationUnavailablePAs']:,} | {ari} | {tv} |")
    lines += ["", "## Actual semantic branch coverage", "",
              "These counts come from one frozen semantic transform per fold on the exact matched validation observations, with the authenticated safe Development history. They are not inferred from V18's annual-prior missing flags. The three branches are exclusive; the raw no-observation and low-exposure flags can overlap. Distinct entities and games are retained in the JSON.", "",
              "| Fold | Domain | No recorded archive observation PAs | Archive observed, low effective exposure PAs | Archive observed, sufficient effective exposure PAs | Mean effective exposure | Median dispersion-only |", "|---|---|---:|---:|---:|---:|---:|"]
    for fold in document["folds"]:
        for domain in fold["actualSemanticCoverage"]:
            branches = domain["mutuallyExclusiveBranches"]
            lines.append(f"| {fold['fold']} | {domain['domain']} | {branches['NO_RECORDED_ARCHIVE_OBSERVATION']['PAs']:,} | {branches['ARCHIVE_OBSERVED_LOW_EFFECTIVE_EXPOSURE']['PAs']:,} | {branches['ARCHIVE_OBSERVED_SUFFICIENT_EFFECTIVE_EXPOSURE']['PAs']:,} | {domain['effectiveExposureDistribution']['mean']:.3f} | {domain['posteriorDispersionOnlyDistribution']['median']:.8f} |")
    lines += ["", "Effective exposure is continuous because prior seasons receive learned decay weights. The JSON separately identifies an observed archive with zero effective exposure, possible when unidentifiable/fitted zero decay removes all previous-season contribution. Such a player is not relabeled as never observed. Posterior dispersion is computed but not used to alter means or to assert calibrated game-score interval coverage.", "",
              "The original clusters.json count vectors are in estimator-label order, whereas its centers and saved validation labels are in logical sorted order. The report authenticates feature-assets.joblib and reads its saved order vector to reindex the count vectors. No original file is rewritten and no cluster is refitted.", "",
              "Training proportions describe the capped training PA sample, not the entire training population. Validation proportions describe PA-weighted assignment frequencies. Total variation is half the sum of absolute differences of those aligned proportions. This is a composition-drift diagnostic: it does not track the same player's identity-stable cluster over time. Cluster numbers are local to their fitted fold; cluster 0 in one fold must not be equated to cluster 0 in another.", "",
              "Starter/reliever domains use historical annual GS/G propensity, not a current role announcement. The opposite historical role is inapplicable rather than source missing. Missing annual role and other unavailable coordinates are reported separately. Team defense centroids describe allowed-PA composition, not isolated fielder defense.", "",
              "Every logical center is retained in original units with ordered feature/value mappings, descriptive profile, training-sample count/proportion and validation PA/game counts. REST_TRAVEL centers describe scheduled venue/start proxies; MATCHUP centers describe encoded hand/platoon/calendar context. These are not discovered player identities or causal effects.", "",
              "## Predictive increment", ""]
    increment = document["incrementalPredictiveValue"]
    if increment["status"] == "PENDING_COMPLETE_META_EVALUATION":
        lines.append("Pending the completed meta-study package. No new candidate performance was read. Stability and interpretable centers alone do not demonstrate an improvement.")
    else:
        lines += ["Only the completed predeclared REGIME_CLUSTER_HGB minus REGIME_HGB comparison is used below. Negative deltas favor adding clusters; the intervals are descriptive reused-Development uncertainty, not independent confirmation.", "",
                  "| Probability scale | Delta log loss | Delta Brier | Game-cluster LL 95% interval | Four-week-block LL 95% interval |", "|---|---:|---:|---|---|"]
        for scale, row in increment["comparison"].items():
            intervals = []
            for key in ("gameClusterBootstrap", "calendarWeekBlockBootstrap"):
                interval = (row[key].get("intervals") or {}).get("logLoss")
                intervals.append(f"[{interval['lower']:.8f}, {interval['upper']:.8f}]" if interval else row[key]["status"])
            lines.append(f"| {scale} | {row['estimate']['logLoss']:.10f} | {row['estimate']['brier']:.10f} | {intervals[0]} | {intervals[1]} |")
    lines += ["", "## Unsupported families and inference limits", "",
              "No roster-linked historical bullpen-availability/fatigue clustering is supported. Actual relief usage, current injuries, transaction-driven role change, catcher effects, weather/roof, and minor-league translations remain unsupported in this historical model matrix. Forward-only evidence supplements do not become historical model features merely because their underlying games occurred in the past.", "",
              "Mean-invariance and complete candidate reload results belong to the per-fold verification receipts, referenced in this report. This reader requires all four global models in all five folds to be complete, authenticates their retained cluster labels and feature assets, verifies the 44 mean / four dispersion feature contracts and transforms each matched validation fold once for semantic branch coverage. It does not run a global estimator, simulation, provider request, AISP write or Final OOT read.", ""]
    return "\n".join(lines)


def build():
    completion_paths = [OUT / f"folds/fold-{fold}/complete.json" for fold in range(1, 6)]
    for fold, path in enumerate(completion_paths, 1):
        if not path.exists():
            raise ValueError(f"GLOBAL_FOLD_{fold}_INCOMPLETE_NO_REPORT_GENERATED")
    meta, raw, oof = load_safe_cache()
    if sha_file(GAME_MAP) != GAME_SHA:
        raise ValueError("Outcome-free team map checksum mismatch")
    raw = join_teams(raw).reset_index(drop=True)
    frame = raw.set_index("canonicalPaId", drop=False).loc[oof.canonicalPaId].reset_index(drop=True)
    if frame.homeTeamId.isna().any() or frame.awayTeamId.isna().any():
        raise ValueError("Cluster report lacks canonical team identity")
    assert len(frame) == 494432 and frame.canonicalGameId.nunique() == 6570
    assert np.array_equal(frame.canonicalGameId, oof.canonicalGameId)
    assert np.array_equal(frame.observedClassIndex, oof.observedClassIndex)
    mean_fields = mean_feature_definitions()
    expected_means = [field["feature"] for field in mean_fields]
    expected_uncertainty = [f"v19_{domain}_posterior_dispersion_only" for domain in DOMAINS]
    folds, all_references = [], [reference(BASE), reference(GAME_MAP), reference(SPEC), reference(ATLAS)]
    for fold, complete_path in enumerate(completion_paths, 1):
        directory = complete_path.parent
        complete = json.loads(complete_path.read_text(encoding="utf-8"))
        current = frame.foldNumber.eq(fold).to_numpy()
        validation = frame.loc[current].reset_index(drop=True)
        if complete["globalFitsCompleted"] != 4 or complete["validationRows"] != len(validation):
            raise ValueError("Incomplete declared global fold")
        entries = {Path(entry["path"]).name: entry for entry in complete["artifacts"]}
        asset_path = checked(entries["feature-assets.joblib"])
        label_path = checked(entries["cluster-labels.parquet"])
        labels = pd.read_parquet(label_path)
        if not np.array_equal(labels.canonicalPaId, validation.canonicalPaId):
            raise ValueError("Saved cluster assignments differ from matched validation order")
        # This object contains semantic priors/scalers/clusters, not a global
        # classifier. Cluster objects supply saved metadata/order only; the
        # frozen semantic transformer separately supplies actual branch counts.
        assets = joblib.load(asset_path)
        cluster_asset, semantic_asset = assets["clusters"], assets["semantic"]
        cluster_metadata_path = directory / "clusters.json"
        semantic_metadata_path = directory / "semantic-priors.json"
        cluster_metadata = json.loads(cluster_metadata_path.read_text(encoding="utf-8"))
        semantic_metadata = json.loads(semantic_metadata_path.read_text(encoding="utf-8"))
        if jsonable(cluster_asset.reports) != cluster_metadata["domains"]:
            raise ValueError("Saved cluster metadata differs from the fitted feature artifact")
        if jsonable(semantic_asset.parameters) != semantic_metadata["parameters"]:
            raise ValueError("Saved prior parameters differ from the fitted feature artifact")
        if semantic_metadata["featureOrder"] != expected_means or semantic_asset.feature_names != expected_means:
            raise ValueError("The declared 44 additional mean features differ")
        if semantic_metadata["uncertaintyOnlyExcludedFromMeans"] != expected_uncertainty:
            raise ValueError("The four excluded dispersion fields differ")
        assert cluster_metadata["fittedEnd"] < str(validation.game_date.min())
        coverage = semantic_coverage(semantic_asset, raw, validation, expected_means, expected_uncertainty)
        verifications = []
        for variant in ("SEMANTIC_HGB", "SEMANTIC_EXTRA_TREES", "REGIME_HGB", "REGIME_CLUSTER_HGB"):
            verified = json.loads(checked(entries[variant + "-verified.json"]).read_text(encoding="utf-8"))
            if (verified["modelReloadMismatchCount"] != 0 or verified["fullPipelineReloadMismatchCount"] != 0
                    or not verified["uncertaintyOnlyMeanInvariance"]):
                raise ValueError("Completed candidate did not prove reload/mean invariance")
            if set(expected_uncertainty).intersection(verified["orderedFeatures"]):
                raise ValueError("An uncertainty-only field entered a mean feature ordering")
            verifications.append({"variant": variant, "receipt": entries[variant + "-verified.json"],
                "modelReloadComparedRows": verified["modelReloadComparedRows"],
                "fullPipelineReloadComparedRows": verified["fullPipelineReloadComparedRows"],
                "uncertaintyOnlyMeanInvariance": True})
        domains = []
        for record in cluster_metadata["domains"]:
            domain = record["domain"]
            label = labels["cluster_" + domain].to_numpy(dtype=int)
            if not np.isin(label, [-1, 0, 1, 2]).all():
                raise ValueError("Cluster assignments violate the frozen three-component schema")
            supported = label >= 0
            base = {"domain": domain, "status": record["status"], "featureOrder": record.get("featureOrder", list(CLUSTER_COORDINATES[domain])),
                    "validationPAs": len(label), "validationGames": int(validation.canonicalGameId.nunique()),
                    "validationSupportedPAs": int(supported.sum()), "validationUnavailablePAs": int((~supported).sum()),
                    "validationUnavailableReasons": unavailable_reasons(validation, label, domain, domain in cluster_asset.models),
                    "subprefixStabilityARI": record.get("subprefixStabilityARI"),
                    "stabilityDefinition": "FULL_TRAINING_VS_EARLIER_TRAINING_SUBPREFIX_ASSIGNMENTS_ON_LATER_TRAINING_SUBSET; NOT_VALIDATION_GAIN",
                    "crossFoldLabelIdentityClaimed": False,
                    "samePlayerLongitudinalMembershipClaimed": False,
                    "architectureSelectedOnValidation": record.get("architectureSelectionOnValidation", False)}
            if record["status"] != "FITTED_TRAINING_ONLY":
                if supported.any():
                    raise ValueError("Unfitted domain unexpectedly has positive cluster labels")
                domains.append({**base, "clusters": [], "sampleToValidationTotalVariation": None})
                continue
            order = np.asarray(cluster_asset.models[domain][2], dtype=int)
            if sorted(order.tolist()) != [0, 1, 2]:
                raise ValueError("Saved cluster order is not a permutation")
            original_counts = np.asarray(record["clusterCounts"], dtype=int)
            logical_counts = original_counts[order]
            if int(logical_counts.sum()) != record["fitRows"]:
                raise ValueError("Cluster training sample counts do not reconcile")
            training_proportions = logical_counts / logical_counts.sum()
            validation_counts = np.bincount(label[supported], minlength=3)
            validation_proportions = validation_counts / supported.sum() if supported.any() else np.zeros(3)
            clusters = []
            for index in range(3):
                center = dict(zip(record["featureOrder"], record["centersOriginalUnits"][index]))
                mask = label == index
                clusters.append({"foldLocalClusterId": f"fold-{fold}:{domain}:{index}", "logicalLabel": index,
                    "originalEstimatorLabel": int(order[index]), "centerOriginalUnits": center,
                    "interpretation": center_description(domain, center), "trainingSamplePAs": int(logical_counts[index]),
                    "trainingSampleProportion": float(training_proportions[index]),
                    "validationPAs": int(mask.sum()), "validationGames": int(validation.loc[mask, "canonicalGameId"].nunique()),
                    "validationDistinctBatters": int(validation.loc[mask, "batterCanonicalPlayerId"].nunique()),
                    "validationDistinctPitchers": int(validation.loc[mask, "pitcherCanonicalPlayerId"].nunique()),
                    "validationProportionAmongSupportedPAs": float(validation_proportions[index]),
                    "validationMinusTrainingSampleProportion": float(validation_proportions[index] - training_proportions[index])})
            domains.append({**base, "trainingSamplePAs": record["fitRows"],
                "originalMetadataCountOrder": "ORIGINAL_ESTIMATOR_LABELS", "reportCountOrder": "LOGICAL_LABELS_MATCH_CENTERS_AND_VALIDATION",
                "savedLogicalToOriginalOrder": order.tolist(), "originalTrainingSampleCounts": original_counts.tolist(),
                "logicalTrainingSampleCounts": logical_counts.tolist(), "clusters": clusters,
                "sampleToValidationTotalVariation": float(.5 * np.abs(validation_proportions - training_proportions).sum()) if supported.any() else None,
                "driftEstimand": "CAPPED_TRAINING_SAMPLE_VS_VALIDATION_PA_WEIGHTED_COMPOSITION_NOT_SAME_PLAYER_DRIFT"})
        folds.append({"fold": fold, "fittedEnd": cluster_metadata["fittedEnd"],
                      "validationFirstDate": str(validation.game_date.min()), "validationLastDate": str(validation.game_date.max()),
                      "clusters": domains, "semanticPriors": semantic_metadata,
                      "actualSemanticCoverage": coverage,
                      "unsupportedDomains": cluster_metadata["unsupportedDomains"], "candidateReloadVerifications": verifications,
                      "sourceReferences": {"completion": reference(complete_path), "featureAssets": entries["feature-assets.joblib"],
                          "clusterLabels": entries["cluster-labels.parquet"], "clusterMetadata": reference(cluster_metadata_path),
                          "semanticMetadata": reference(semantic_metadata_path)}})
        all_references.extend(folds[-1]["sourceReferences"].values())
        del assets, cluster_asset, semantic_asset
    by_domain = defaultdict(list)
    for fold in folds:
        for record in fold["clusters"]:
            by_domain[record["domain"]].append({"fold": fold["fold"], "status": record["status"],
                "subprefixStabilityARI": record["subprefixStabilityARI"],
                "validationSupportedPAs": record["validationSupportedPAs"], "validationUnavailablePAs": record["validationUnavailablePAs"],
                "sampleToValidationTotalVariation": record.get("sampleToValidationTotalVariation")})
    document = {"schemaVersion": "MLB_V19_FITTED_CLUSTER_COLD_START_REPORT_V1", "matchedPAs": 494432, "matchedGames": 6570,
        "foldCount": 5, "classOrder": list(PA_CLASS_ORDER), "meanFeatureCount": 44, "meanFeatureDefinitions": mean_fields,
        "dispersionOnlyFeatureCount": 4, "dispersionOnlyFeatures": expected_uncertainty,
        "dispersionDefinition": "SUM_K posteriorMean_k*(1-posteriorMean_k)/(effectiveExposure+fittedAlpha+1)",
        "dispersionInterpretation": "Computed posterior uncertainty excluded from score/probability means; not a fitted game-score variance correction or established interval coverage.",
        "proposed246FieldPolicy": reference(SPEC),
        "implementedTreatmentScope": "44_ADDITIONAL_HIERARCHICAL_CLASS_COMPOSITION_AND_EXPOSURE_MEAN_FEATURES_PLUS4_EXCLUDED_DISPERSION; NOT246_NEW_FITTED_PRIORS",
        "sourceDerivedWorkloadUsedInHistoricalTraining": False, "folds": folds, "domainStability": dict(by_domain),
        "incrementalPredictiveValue": final_incremental_evidence(),
        "sourceReferences": all_references,
        "unsupportedClaims": ["Current bullpen availability clusters", "Injury/transaction role-change clusters", "Minor-league translations", "Identity-stable same-player drift across folds", "Historical source-publication vintages from retrospectively collected evidence"],
        "labelReindexing": "Original counts remain untouched. Saved fitted label permutation aligns their reporting with sorted centers and saved validation assignments.",
        "uncertaintyAndReloadScope": "References existing complete per-fold verification receipts; no additional global model execution in report builder.",
        "actions": {"clusterFits": 0, "priorFits": 0, "globalEstimatorLoads": 0, "modelPredictions": 0,
                    "frozenSemanticValidationTransforms": 5,
                    "providerCalls": 0, "aispWrites": 0, "finalOotPayloadReads": 0, "operationalDeploymentActions": 0},
        "producer": reference(Path(__file__).resolve())}
    artifact = store("cluster-cold-start-report.json", document)
    report = store("cluster-cold-start-report.md", markdown(document, artifact))
    manifest = store("manifest.json", {"schemaVersion": "MLB_V19_CLUSTER_COLD_START_MANIFEST_V1",
        "artifacts": {"data": artifact, "report": report}, "matchedPAs": 494432, "matchedGames": 6570,
        "folds": 5, "meanFeatures": 44, "dispersionOnlyFeatures": 4,
        "incrementalComparisonStatus": document["incrementalPredictiveValue"]["status"],
        "actions": document["actions"], "researchShadowOnly": True, "wageringAuthority": False})
    return {"manifest": manifest, "data": artifact, "report": report,
            "incrementalComparisonStatus": document["incrementalPredictiveValue"]["status"]}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
