"""Immutable Development completion authority and outcome-free integrity impact.

No model loading, inference, fitting, metric selection, network, or AISP access.
The mixed 2026 raw schedule is never opened; metadata-only uncertainty remains.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_silver import bronze_authority as ba
from server.sports_silver.canonical_ids import canonical_game_id
from server.sports_current_statcast.mlb_v18_development_timing import (
    SCHEMA, project_contributions, training_prefix_mask, contribution_day_blocks,
    potential_prior_exposure, interdate_reorder_impact,
)

OUT = ROOT / "outputs/mlb-v18-conditional-champion-v1/development-integrity"
RAW = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache/raw-development.parquet"
RAW_SHA = "d5fdb7bcbe058f34334483a21b14e83129d19c1727d20eddb469c18668ff3b82"
LEDGER_SHA = "5bbcdf6c7cae0332b903db18b410a6bae2da05da6871e2125688c6e8394b0e6b"
LEDGER = ROOT / f"outputs/mlb-v19-current-state-specialists-v1/timing-blocker/sha256/{LEDGER_SHA}/timing-evidence.json"
SCHEDULE = Path("C:/Users/james/asp-data-staging/mlb-current-statcast-bronze-v1/manifests/mlb-stats-api-schedule-authority.json")
SCHEDULE_SHA = "44c43a48dda5895dcc19417a1c51b18ccdaed9dd83b3c1b8d50826e42be69c4d"
COMPARISON_SHA = "12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d"
COMPARISON = ROOT / f"outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-{COMPARISON_SHA}.json"
STUDY = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory/corrected-hgb-recovery-1/study.json"
RUNTIME = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory"
CONTEXT = ROOT / "outputs/mlb-v19-current-state-specialists-v1/game-context/sha256/b94fa31772a6d79e5f8b80ec414e0ec8b41a2dcf36b65c3fae9dba0e47bcfd9a/game-context.parquet"
CONTEXT_SHA = "9a642b0f373ef27bb684f46304661929843e9d60bef8188d2341c6373790296d"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ref(path):
    return {"path": str(path.resolve()), "sha256": sha(path), "bytes": path.stat().st_size}


def verified(path, expected):
    if sha(path) != expected:
        raise ValueError(f"Source bytes differ: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def iso(value):
    return value[:4] + "-" + value[4:6] + "-" + value[6:8]


def parquet_bytes(frame):
    stream = io.BytesIO()
    frame.to_parquet(stream, index=False, compression="zstd")
    return stream.getvalue()


def build_authority(games, ledger, schedule):
    """Retained all-game source coverage; no inferred observed-publication clocks."""
    sources = [ref(LEDGER), ref(SCHEDULE)]
    manifest = ba.verify_bronze_manifest()
    legacy = {}
    for part in ba.partitions(manifest, source="retrosheet"):
        if part.year not in (2023, 2024) or "/game-logs/" not in part.relative_path:
            continue
        path = part.absolute_path(ba.DEFAULT_BRONZE_ROOT)
        if sha(path) != part.file_sha256:
            raise ValueError("Governed Retrosheet completion bytes differ")
        sources.append(ref(path))
        with zipfile.ZipFile(path) as archive:
            member = f"gl{part.year}.txt"
            for line, row in enumerate(csv.reader(io.StringIO(archive.read(member).decode("latin1"))), 1):
                if len(row) != 161:
                    raise ValueError("Retrosheet game-log field count differs")
                gid = row[6] + row[0] + row[1]
                legacy[gid] = {"eventDate": iso(row[0]), "completionDate": iso(row[13].split(",")[0]) if row[13] else iso(row[0]),
                               "sourceSha256": part.file_sha256, "sourceMember": member, "sourceLine": line,
                               "basis": "EXPLICIT_RETROSHEET_COMPLETION_DATE" if row[13] else "RETROSHEET_FINAL_GAMELOG_DATE_RECONSTRUCTION"}
    unresolved = {r["canonicalGameId"]: r for r in ledger["unknownFinalizationGames"]}
    snap = next(s for s in schedule["snapshots"] if s["startDate"] == "2025-03-18" and s["endDate"] == "2025-09-28")
    path = SCHEDULE.parent.parent / snap["rawRelativePath"]
    if "2026" in str(path) or sha(path) != snap["rawSha256"]:
        raise ValueError("Only the hash-pinned 2025 raw schedule may be opened")
    raw25 = json.loads(path.read_text(encoding="utf-8"))
    sources.append(ref(path))
    by25, links = {}, []
    for day in raw25["dates"]:
        for game in day["games"]:
            if game.get("status", {}).get("detailedState") not in ("Final", "Completed Early"):
                continue
            cid = canonical_game_id(str(game["gamePk"]))
            by25.setdefault(cid, []).append((day["date"], game))
            if game.get("resumeDate"):
                links.append({"canonicalGameId": cid, "gamePk": game["gamePk"], "originalDate": game["officialDate"],
                              "originalScheduledAt": game["gameDate"], "resumeDate": game["resumeDate"],
                              "sourceSha256": snap["rawSha256"]})
    for link in links:
        candidates = by25[link["canonicalGameId"]]
        if not any(g.get("resumedFrom") == link["originalScheduledAt"] and g.get("gameDate") == link["resumeDate"] for _, g in candidates):
            raise ValueError("Explicit 2025 original/resumption link is not reciprocal")
    by_current = {canonical_game_id(str(g["gamePk"])): g for g in schedule["completedGames"]}
    records = []
    for game in games.itertuples(index=False):
        item = {"canonicalGameId": game.canonicalGameId, "sourceGameId": game.game_id,
                "eventDate": game.game_date, "completionDate": None, "completionDateLowerBound": None,
                "observedPublicationAt": None, "timingStatus": "UNKNOWN_SOURCE_COMPLETION_AVAILABILITY",
                "sourceSha256": None, "sourceMember": None, "sourceLine": None,
                "basis": None, "exclusionReason": None}
        if game.canonicalGameId in unresolved:
            item.update(timingStatus="REVERTED_UNCOMPLETED_FINALIZATION_UNKNOWN", basis="RETAINED_RETROSHEET_COMMENT",
                        sourceSha256=unresolved[game.canonicalGameId]["sourceSha256"],
                        exclusionReason="FINALIZATION_DATE_UNKNOWN_NO_CONTRIBUTIONS")
        elif game.game_date < "2025-01-01":
            original = legacy.get(game.game_id.removeprefix("retrosheet:game:"))
            if original and original["eventDate"] == game.game_date:
                item.update(original)
                item["timingStatus"] = "RECONSTRUCTED_COMPLETION_DATE_NOT_OBSERVED_RELEASE"
            else:
                item["exclusionReason"] = "EXACT_GAMELOG_DATE_IDENTITY_UNAVAILABLE"
        elif game.game_date < "2026-01-01":
            observations = by25.get(game.canonicalGameId, [])
            if observations and all(g["officialDate"] == game.game_date for _, g in observations):
                item.update(completionDate=max(d for d, _ in observations), sourceSha256=snap["rawSha256"],
                            timingStatus="RECONSTRUCTED_COMPLETION_DATE_NOT_OBSERVED_RELEASE",
                            basis="FINAL_2025_SCHEDULE_LISTING_WITH_EXPLICIT_RESUMPTION_LINK_CHECK")
            else:
                item["exclusionReason"] = "EXACT_2025_SCHEDULE_DATE_IDENTITY_UNAVAILABLE"
        else:
            metadata = by_current.get(game.canonicalGameId)
            listed = [o["scheduleDate"] for o in (metadata or {}).get("scheduleObservations", [])
                      if o["detailedState"] in ("Final", "Completed Early")]
            item.update(timingStatus="SAFE_2026_FINALIZATION_UNCERTIFIED", sourceSha256=SCHEDULE_SHA,
                        completionDateLowerBound=max(listed) if listed else None,
                        basis="RETAINED_RESULT_FREE_SCHEDULE_PROJECTION_ONLY",
                        exclusionReason="RESUME_FIELDS_AND_EXHAUSTIVE_COMPLETION_PROOF_NOT_RETAINED_IN_SAFE_PROJECTION")
        records.append(item)
    return pd.DataFrame(records), sources, links


def main():
    ledger, schedule = verified(LEDGER, LEDGER_SHA), verified(SCHEDULE, SCHEDULE_SHA)
    if sha(RAW) != RAW_SHA or sha(CONTEXT) != CONTEXT_SHA:
        raise ValueError("Safe Development identity source differs")
    columns = ["canonicalPaId", "canonicalGameId", "game_id", "game_date", "foldNumber", "context_inning",
               "batterCanonicalPlayerId", "pitcherCanonicalPlayerId"]
    frame = pd.read_parquet(RAW, columns=columns)
    games = frame[["canonicalGameId", "game_id", "game_date"]].drop_duplicates().sort_values(["game_date", "canonicalGameId"])
    authority, sources, links25 = build_authority(games, ledger, schedule)
    projected = project_contributions(frame, authority)
    team = pd.read_parquet(CONTEXT, columns=["canonicalGameId", "homeTeamId", "awayTeamId"])
    projected = projected.merge(team, on="canonicalGameId", validate="many_to_one", sort=False)
    if projected.homeTeamId.isna().any() or projected.awayTeamId.isna().any():
        raise ValueError("Exact game/team identity unavailable")
    delayed = ledger["knownDelayedGames"]
    projected["potentialBatterPriorExposure"] = potential_prior_exposure(projected, delayed, "batterCanonicalPlayerId")
    projected["potentialPitcherPriorExposure"] = potential_prior_exposure(projected, delayed, "pitcherCanonicalPlayerId")
    context_exposure = np.zeros(len(projected), dtype=bool)
    interval = np.zeros(len(projected), dtype=bool)
    for source in delayed:
        target = projected[projected.canonicalGameId.eq(source["canonicalGameId"])].iloc[0]
        teams = {target.homeTeamId, target.awayTeamId}
        temporal = projected.game_date.gt(source["gameDate"]) & projected.game_date.le(source["completionDateProxy"])
        context_exposure |= (temporal & (projected.homeTeamId.isin(teams) | projected.awayTeamId.isin(teams))).to_numpy()
        interval |= projected.game_date.between(source["gameDate"], source["completionDateProxy"]).to_numpy()
    projected["potentialTeamContextExposure"] = context_exposure
    projected["potentialKnownFeatureExposure"] = projected[["potentialBatterPriorExposure", "potentialPitcherPriorExposure", "potentialTeamContextExposure"]].any(axis=1)
    projected["knownSuspensionIntervalCalendarMask"] = interval
    reorder, blocks = [], []
    for role in ("batterCanonicalPlayerId", "pitcherCanonicalPlayerId"):
        impact = interdate_reorder_impact(projected, role)
        ids = set(impact.pop("affectedPaIds"))
        projected[role + "ReorderExposed"] = projected.canonicalPaId.isin(ids)
        reorder.append(impact)
        role_blocks = contribution_day_blocks(projected, role, "2026-08-07").rename(columns={role: "entityId"})
        role_blocks["role"] = role
        blocks.append(role_blocks)
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    if comparison["resultChecksum"] != COMPARISON_SHA:
        raise ValueError("Frozen V18 comparison identity differs")
    fitted, fold_impacts = comparison["treatmentExecution"]["fittedFoldArtifacts"], []
    for fold in study["folds"]:
        n, end = int(fold["foldNumber"]), fold["trainEnd"]
        train = projected.game_date.between(fold["trainStart"], end)
        valid = projected.foldNumber.eq(n)
        crossing_ids = [r["canonicalGameId"] for r in delayed if r["gameDate"] <= end < r["completionDateProxy"]]
        crossing = train & projected.canonicalGameId.isin(crossing_ids)
        bos_later = crossing & projected.canonicalGameId.eq("game-80cc05dfeda2a0d757afd91f") & projected.context_inning.ge(3)
        local = next(r for r in fitted if r["foldNumber"] == n)
        prep = local["localResearchArtifact"]["preprocessing"]
        prep_path = RUNTIME / prep["relativePath"]
        if sha(prep_path) != prep["sha256"] or prep_path.stat().st_size != prep["bytes"]:
            raise ValueError("Frozen fitted-preprocessing bytes differ")
        fold_impacts.append({"foldNumber": n, "trainStart": fold["trainStart"], "trainEnd": end,
            "safeTrainingRows": int(train.sum()), "safeValidationRows": int(valid.sum()),
            "knownDelayedGameTrainingRowsRequiringWholeGameQuarantine": int(crossing.sum()),
            "provenFutureTrainingLabelsMinimum": int(bos_later.sum()),
            "minimumLabelCountBasis": "BOS202406260_INNINGS_GE_3_CERTAINLY_AFTER_JUNE26_SUSPENSION; OTHER_RESUMPTION_PAS_NOT_INFERRED",
            "unknownCompletionTrainingRowsExcludedFromDateReconstruction": int((train & ~projected.reconstructedDateEligible).sum()),
            "potentialKnownHistoricalFeatureExposureTrainingRows": int((train & projected.potentialKnownFeatureExposure).sum()),
            "validationDelayedGames": int(projected.loc[valid & projected.canonicalGameId.isin([r['canonicalGameId'] for r in delayed]), "canonicalGameId"].nunique()),
            "validationDelayedGameRows": int((valid & projected.canonicalGameId.isin([r['canonicalGameId'] for r in delayed])).sum()),
            "potentialKnownFeatureExposureValidationRows": int((valid & projected.potentialKnownFeatureExposure).sum()),
            "potentialKnownFeatureExposureValidationGames": int(projected.loc[valid & projected.potentialKnownFeatureExposure, "canonicalGameId"].nunique()),
            "conservativeCalendarIntervalValidationRows": int((valid & interval).sum()),
            "conservativeCalendarIntervalValidationGames": int(projected.loc[valid & interval, "canonicalGameId"].nunique()),
            "fittedPreprocessing": ref(prep_path), "priorFittedChecksum": local["priorFittedChecksum"],
            "semanticFittedChecksum": local["semanticFittedChecksum"],
            "preprocessingDisposition": "POTENTIALLY_AFFECTED_HISTORICAL_INPUT_TIMING_NOT_REFITTED_OR_NUMERICALLY_CHANGED",
            "frozenModel": local["localResearchArtifact"]["model"]})
    sources += [ref(RAW), ref(CONTEXT), ref(STUDY), ref(COMPARISON)]
    flags = projected[["canonicalPaId", "canonicalGameId", "game_date", "foldNumber", "completionDate", "timingStatus",
        "historyContributionNotBeforeDate", "reconstructedDateEligible", "observedPublicationAvailable",
        "potentialBatterPriorExposure", "potentialPitcherPriorExposure", "potentialTeamContextExposure",
        "potentialKnownFeatureExposure", "knownSuspensionIntervalCalendarMask",
        "batterCanonicalPlayerIdReorderExposed", "pitcherCanonicalPlayerIdReorderExposed"]].copy()
    flags["candidateConservativeRowEligibility"] = flags.reconstructedDateEligible & ~flags.knownSuspensionIntervalCalendarMask
    flags["certifiedHistoricalMetricEligibility"] = False
    cohort_bytes = parquet_bytes(flags)
    cohort_sha = hashlib.sha256(cohort_bytes).hexdigest()
    authority_receipt = {"schemaVersion": SCHEMA, "scope": "DEVELOPMENT_ONLY_DIAGNOSTIC_NOT_FROZEN_V18_REPLACEMENT",
        "predecessor": ref(LEDGER), "sourceArtifacts": sources, "targetPayloadColumnsRead": [],
        "gameCount": len(authority), "timingStatuses": authority.groupby("timingStatus").size().to_dict(),
        "known2025ExplicitReciprocalResumeLinks": links25,
        "contributionRule": "Known completion date is eligible only at a strictly later calendar date; opt-in date reconstruction only. Unknown completion excluded. Observed source-publication timestamps remain NULL.",
        "orderingRule": "Whole-game blocks ordered by completion day, not original date. Same-day blocks remain an explicit unordered bucket; actual PA chronology and exact last-N windows are not invented.",
        "strictDefault": "Observed-publication proof required by default; no rows meet it in this retrospectively retrieved source projection.",
        "originalEventDatePreserved": True, "unknownDatesImputed": 0, "knownDelayedGames": delayed,
        "unknownFinalizationGames": ledger["unknownFinalizationGames"],
        "historicalMetricsCertification": False}
    impact = {"schemaVersion": "MLB_V18_DEVELOPMENT_INTEGRITY_IMPACT_V1", "cohortIdentity": "completion-diagnostic-" + cohort_sha,
        "cohortSha256": cohort_sha, "cohortStatus": "NEW_DIAGNOSTIC_PROJECTION_NOT_ORIGINAL_ACCEPTED_COMPARISON",
        "safePaCount": len(projected), "safeGameCount": len(games), "knownDelayedGames": len(delayed),
        "knownDelayedPaRows": ledger["knownDelayedPaCount"], "unknownRevertedGamePaRows": ledger["unresolvedFinalizationPaCount"],
        "paRowsByTimingStatus": projected.groupby("timingStatus").size().to_dict(), "foldImpacts": fold_impacts,
        "rollingOrderImpact": reorder,
        "exactRollingHistoryValueReconstruction": {"performed": False, "reason": "Safe identity cache lacks full PA occurrence/resumption timestamps and within-completion-day ordering. Partial-order changes are measured; exact last100/250 feature changes are not claimed."},
        "candidateConservativeRowEligibilityCount": int(flags.candidateConservativeRowEligibility.sum()),
        "certifiedHistoricalMetricEligibleRows": 0,
        "sensitivity": {"performed": False, "reason": "All required historical source-availability and fitted-feature provenance proofs are not established. No reduced-cohort performance is reported as clean validation."},
        "metricsRemainUsable": ["Stored numerical V18 results as historically preserved outputs with an explicit temporal-integrity qualification", "Exact artifact/prediction reproduction as a numerical property", "Outcome-independent impact counts and partial-order diagnostics in this new projection"],
        "claimsWithdrawnOrQualified": ["Clean five-fold point-in-time validation", "An unbiased original July6-trained fold2 prospective score", "A fully repaired historical feature matrix or exact last-N history values", "Superiority or selection conclusions from incomplete V19 fits"],
        "remainingProof": ["Safe2026 complete resumption/finalization metadata projection retaining explicit links and unknown/reverted dispositions", "NYN202309280 finalization/score-reversion availability date", "Historical source-publication clocks or an explicitly accepted reconstructed-availability protocol", "Occurrence/resumption ordering for complete frozen rolling/context-feature lineage"],
        "prospectiveChampionDecision": "This historical limitation does not itself block the user's separately authorized prospective conditional champion registration.",
        "bounds": {"fits": 0, "inferenceCalls": 0, "providerCalls": 0, "cost": 0, "finalOotPayloadBytesRead": 0,
                   "mixed2026RawPayloadRead": False, "aispWrites": 0, "historicalArtifactsOverwritten": 0}}
    table_rows = []
    for f in fold_impacts:
        table_rows.append(f"| {f['foldNumber']} | {f['knownDelayedGameTrainingRowsRequiringWholeGameQuarantine']} | {f['provenFutureTrainingLabelsMinimum']} | {f['potentialKnownHistoricalFeatureExposureTrainingRows']} | {f['potentialKnownFeatureExposureValidationRows']} / {f['potentialKnownFeatureExposureValidationGames']} |")
    report = "\n".join(["# V18 Development completion authority and integrity impact", "",
        "This is a new, separately versioned diagnostic projection. Frozen V18, its preprocessing and its accepted results are unchanged. It is not a repaired five-fold model evaluation.", "",
        "## Completion authority", "", f"{len(authority):,} games / {len(projected):,} physically isolated Development PAs. Fourteen known delayed games carry1,033 PAs; NYN202309280 has61 PAs with unknown finalization and remains excluded. 2023/24 Retrosheet dates and four reciprocal2025 resumption links are retained. Safe2026 listing lower bounds remain uncertified, with no completion date invented.", "",
        "Known dates contribute only on a strictly later calendar date in explicitly selected reconstructed-date diagnostics. All observed publication timestamps remain NULL. Strict observed-availability mode admits no rows. Original game dates remain unchanged. Same-completion-day games are explicitly unordered; no exact within-day PA order or rolling feature values are manufactured.", "",
        "## Measured impact", "", "| Fold | Whole-game future-label quarantine rows | Proven future labels, minimum | Potential training-feature exposure rows | Potential validation-feature exposure rows / games |", "| --- | ---: | ---: | ---: | ---: |", *table_rows, "",
        "BOS202406260 is the sole known direct outer-training-cutoff crossing:70 game PAs enter the July6-ended prefix, including55 inning3-or-later PAs certainly played after suspension. The remaining15 are not all asserted to be future labels. Whole-game quarantine is deliberately conservative.", "",
        "Potential exposure counts use only identity and date relationships. They are not counts of numerical feature differences. All five fitted preprocessing objects are flagged for historical-input timing review; their hashes and prior/semantic fitted identities are recorded without changing their bytes.", "",
        *[f"- {r['entity']}: {r['paRowsInReversedBlocks']:,} PAs in {r['entityGameBlocksWithProvenInterdateReversal']:,} entity/game blocks have a proven inter-date ordering reversal ({r['reversedBlockPairs']:,} reversed pairs). Same-day ambiguity: {r['sameCompletionDayAmbiguousEntityGameBlocks']:,} blocks." for r in reorder], "",
        "## Admissibility", "", f"Diagnostic cohort identity: completion-diagnostic-{cohort_sha}. Candidate conservative row eligibility: {int(flags.candidateConservativeRowEligibility.sum()):,}; certified historical metric eligibility:0. These candidate rows are not claimed to form a valid reduced-cohort comparison.", "",
        "No sensitivity metrics were run because2026 resumption completeness, the reverted-game finalization date, historical publication availability, and complete frozen-history feature provenance are not established. Delaying a fold or excluding calendar intervals would define a new protocol, not restore the original experiment.", "",
        "Stored performance remains a historical numerical result, explicitly qualified; exact reload remains numerical evidence. Clean point-in-time validation and completed V19 model-selection claims are not supportable. The user-authorized prospective conditional champion activation can proceed with this limitation disclosed.", "",
        "No fits, inference, provider requests/costs, Final OOT payload reads, mixed2026 raw-schedule reads, AISP writes or historical overwrites occurred.", ""])
    payloads = {"completion-authority.json": canonical_json_bytes(authority_receipt),
        "game-completion-authority.parquet": parquet_bytes(authority), "pa-diagnostic-projection.parquet": cohort_bytes,
        "entity-game-completion-blocks.parquet": parquet_bytes(pd.concat(blocks, ignore_index=True)),
        "integrity-impact.json": canonical_json_bytes(impact), "REPORT.md": report.encode("utf-8")}
    manifest = {"schemaVersion": "MLB_V18_DEVELOPMENT_INTEGRITY_MANIFEST_V1", "status": "BOUNDED_DATE_PROJECTION_COMPLETE_HISTORICAL_METRICS_UNCERTIFIED",
        "cohortIdentity": impact["cohortIdentity"], "predecessor": ref(LEDGER),
        "artifacts": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in payloads.items()},
        "code": [ref(ROOT / "server/sports_current_statcast/mlb_v18_development_timing.py"), ref(Path(__file__))],
        "bounds": impact["bounds"]}
    manifest_data = canonical_json_bytes(manifest)
    digest = hashlib.sha256(manifest_data).hexdigest()
    directory = OUT / "sha256" / digest
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in {**payloads, "manifest.json": manifest_data}.items():
        target = directory / name
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError("Immutable Development integrity artifact conflict")
        else:
            with target.open("xb") as stream:
                stream.write(data)
    for name, meta in manifest["artifacts"].items():
        if sha(directory / name) != meta["sha256"] or (directory / name).stat().st_size != meta["bytes"]:
            raise ValueError("Published Development integrity bytes differ")
    pd.testing.assert_frame_equal(pd.read_parquet(directory / "pa-diagnostic-projection.parquet"), flags)
    print(json.dumps({"path": str(directory / "manifest.json"), "sha256": digest,
                      "impactPath": str(directory / "integrity-impact.json"),
                      "timingStatuses": impact["paRowsByTimingStatus"], "foldImpacts": fold_impacts,
                      "rollingOrderImpact": reorder, "candidateRows": impact["candidateConservativeRowEligibilityCount"]}, indent=2))


if __name__ == "__main__":
    main()
