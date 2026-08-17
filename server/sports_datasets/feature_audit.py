from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import pyarrow.parquet as pq

from .constants import MANIFEST_SHA
from .consumer import ManifestValidationError, ValidatedPackage, _format_utc_now


FEATURE_CONTRACT_VERSION = "MLB_PA_FEATURE_VIEW_V1"
TARGET_SEASONS = (2023, 2024, 2025)
EXPECTED_PA_ROWS = {2023: 184_104, 2024: 182_449, 2025: 182_926}
MAX_AUDIT_ROWS = 1_000_000


def build_mlb_pa_feature_audit(validated: ValidatedPackage) -> dict[str, Any]:
    """Prove the exact package-local Y−1 join blocker without inferring a bridge."""

    manifest = validated.manifest
    if manifest["manifest_sha256"] != MANIFEST_SHA:
        raise ManifestValidationError("FEATURE_AUDIT_MANIFEST_MISMATCH", "Feature audit requires the approved source manifest")

    eligible_batter_prior_ids: dict[int, set[str]] = {season: set() for season in TARGET_SEASONS}
    eligible_pitcher_prior_ids: dict[int, set[str]] = {season: set() for season in TARGET_SEASONS}
    eligible_batter_prior_rows: dict[int, int] = {season: 0 for season in TARGET_SEASONS}
    eligible_pitcher_prior_rows: dict[int, int] = {season: 0 for season in TARGET_SEASONS}
    prior_namespace_kinds: set[str] = set()
    scanned_prior_rows = 0
    for partition in manifest["partitions"]:
        if partition["family"] != "player_prior":
            continue
        path = validated.package_root / partition["package_relative_uri"]
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(
            batch_size=32_768,
            columns=[
                "canonical_player_id",
                "player_id",
                "lahman_player_id",
                "eligible_from_season",
                "same_season_predictor_eligible",
                "domain",
                "season",
            ],
            use_threads=False,
        ):
            scanned_prior_rows += batch.num_rows
            if scanned_prior_rows > MAX_AUDIT_ROWS:
                raise ManifestValidationError("FEATURE_AUDIT_ROW_LIMIT", "Feature identity audit exceeded its bounded row limit")
            for row in batch.to_pylist():
                canonical = row.get("canonical_player_id")
                player_id = row.get("player_id")
                lahman = row.get("lahman_player_id")
                eligible_from = row.get("eligible_from_season")
                domain = row.get("domain")
                prior_season = row.get("season")
                if row.get("same_season_predictor_eligible") is not False:
                    raise ManifestValidationError("FEATURE_AUDIT_SAME_SEASON_PRIOR", "player_prior contains same-season predictor eligibility")
                if type(prior_season) is not int or type(eligible_from) is not int or prior_season + 1 != eligible_from:
                    raise ManifestValidationError("FEATURE_AUDIT_Y_MINUS_1_RULE", "player_prior season and eligible_from_season do not prove Y-1 eligibility")
                if canonical:
                    prior_namespace_kinds.add("ASP_CANONICAL_UUID" if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", str(canonical)) else "ASP_CANONICAL_OTHER")
                if player_id:
                    prior_namespace_kinds.add("PLAYER_ID")
                if lahman:
                    prior_namespace_kinds.add("LAHMAN_PLAYER_ID")
                if eligible_from in TARGET_SEASONS and domain == "BATTING":
                    eligible_batter_prior_rows[eligible_from] += 1
                    if canonical:
                        eligible_batter_prior_ids[eligible_from].add(str(canonical))
                if eligible_from in TARGET_SEASONS and domain == "PITCHING":
                    eligible_pitcher_prior_rows[eligible_from] += 1
                    if canonical:
                        eligible_pitcher_prior_ids[eligible_from].add(str(canonical))

    pa_rows: dict[int, int] = defaultdict(int)
    batter_matches: dict[int, int] = defaultdict(int)
    pitcher_matches: dict[int, int] = defaultdict(int)
    pa_namespaces: set[str] = set()
    scanned_pa_rows = 0
    for partition in manifest["partitions"]:
        if partition["family"] != "plate_appearance" or partition["season"] not in TARGET_SEASONS:
            continue
        path = validated.package_root / partition["package_relative_uri"]
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(
            batch_size=32_768,
            columns=["season", "batter_id", "pitcher_id", "identity_namespace", "canonical_identity_resolved"],
            use_threads=False,
        ):
            scanned_pa_rows += batch.num_rows
            if scanned_pa_rows > MAX_AUDIT_ROWS:
                raise ManifestValidationError("FEATURE_AUDIT_ROW_LIMIT", "Feature identity audit exceeded its bounded row limit")
            for row in batch.to_pylist():
                season = row.get("season")
                if season not in TARGET_SEASONS:
                    raise ManifestValidationError("FEATURE_AUDIT_SEASON_MISMATCH", "Plate-appearance row season differs from its governed partition")
                pa_rows[season] += 1
                namespace = row.get("identity_namespace")
                if namespace:
                    pa_namespaces.add(str(namespace))
                if row.get("canonical_identity_resolved") is not False:
                    raise ManifestValidationError("FEATURE_AUDIT_PA_CANONICAL_RESOLUTION", "Plate appearances unexpectedly claim canonical identity resolution")
                if row.get("batter_id") in eligible_batter_prior_ids[season]:
                    batter_matches[season] += 1
                if row.get("pitcher_id") in eligible_pitcher_prior_ids[season]:
                    pitcher_matches[season] += 1

    if dict(pa_rows) != EXPECTED_PA_ROWS:
        raise ManifestValidationError("FEATURE_AUDIT_PA_COUNT_MISMATCH", "Feature audit plate-appearance counts differ from frozen authority")
    if any(batter_matches[season] or pitcher_matches[season] for season in TARGET_SEASONS):
        raise ManifestValidationError("FEATURE_AUDIT_BRIDGE_CONTRADICTION", "Unexpected cross-namespace identity matches require a governed bridge review")
    if pa_namespaces != {"RETROSHEET"}:
        raise ManifestValidationError("FEATURE_AUDIT_PA_NAMESPACE_MISMATCH", "Plate-appearance identity namespace differs from RETROSHEET")

    per_season = [
        {
            "season": season,
            "plateAppearanceRows": pa_rows[season],
            "eligibleBattingPriorRows": eligible_batter_prior_rows[season],
            "eligiblePitchingPriorRows": eligible_pitcher_prior_rows[season],
            "eligibleUniqueBatterPriorCanonicalIds": len(eligible_batter_prior_ids[season]),
            "eligibleUniquePitcherPriorCanonicalIds": len(eligible_pitcher_prior_ids[season]),
            "batterYMinus1JoinMatches": batter_matches[season],
            "batterYMinus1JoinDenominator": pa_rows[season],
            "pitcherYMinus1JoinMatches": pitcher_matches[season],
            "pitcherYMinus1JoinDenominator": pa_rows[season],
        }
        for season in TARGET_SEASONS
    ]
    return {
        "contractVersion": FEATURE_CONTRACT_VERSION,
        "status": "BLOCKED",
        "method": "PACKAGE_ONLY_EXACT_NAMESPACE_MEMBERSHIP_AUDIT_V1",
        "sourceManifestSha": MANIFEST_SHA,
        "observedNamespaces": {
            "plateAppearance": sorted(pa_namespaces),
            "playerPrior": sorted(prior_namespace_kinds),
        },
        "perSeasonRows": per_season,
        "joinEvidence": {
            "rule": "Target season Y uses exact role-specific player_prior rows with eligible_from_season == Y (therefore source season Y-1); exact identifiers only.",
            "batterMatches": sum(batter_matches.values()),
            "batterDenominator": sum(pa_rows.values()),
            "pitcherMatches": sum(pitcher_matches.values()),
            "pitcherDenominator": sum(pa_rows.values()),
            "inferenceOrFuzzyMatchingUsed": False,
            "sameSeasonPredictorEligibleObserved": False,
            "plateAppearanceCanonicalIdentityResolvedObserved": False,
        },
        "checks": {
            "roleSpecificPriorSets": True,
            "eligibleFromEqualsTargetSeason": True,
            "priorSeasonPlusOneEqualsEligibleFromSeason": True,
            "sameSeasonPredictorEligibilityUniversallyFalse": True,
            "plateAppearanceNamespaceRetrosheetOnly": True,
            "plateAppearanceCanonicalIdentityResolvedUniversallyFalse": True,
        },
        "unsafeContext": {
            "classification": "EXCLUDED_ENHANCED_TIMING_RISK",
            "families": ["bullpen_usage", "play_transition", "starter_usage", "weather"],
            "fields": ["player_game_batting.actual_starting_lineup", "player_game_pitching.actual_start_flag"],
            "actualHistoricalEvidenceUsed": False,
        },
        "missingBridge": {
            "isMissing": True,
            "requiredArtifact": "PACKAGE_BOUND_RETROSHEET_TO_ASP_CANONICAL_PLAYER_ID_BRIDGE",
            "reason": "Plate appearances use RETROSHEET identifiers while player_prior uses ASP canonical UUID identities; the package declares no governed cross-family bridge.",
        },
        "auditedAt": _format_utc_now(),
    }
