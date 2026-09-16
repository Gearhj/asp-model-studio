"""Freeze one score-limited rule from declared FD1 Development scoring evidence.

This reads only the 2021--2023 play_transition partitions. It does not read any
forecast, September 12 diagnostic, validation partition, or challenger result.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_datasets.consumer import canonical_json_bytes, semantic_manifest_sha

MANIFEST = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
SOURCE = Path(r"C:/Users/james/asp-model-exchange/datasets/mlb-fd1") / f"sha256-{MANIFEST}"
OUT = ROOT / "outputs/mlb-v18-score-limited-v1/development-rule"
SEASONS = (2021, 2022, 2023)
CONFIGURATION = "V18_SCORE_LIMITED_DEV_P99_V1"
IDENTITY_COLUMNS = ["game_id", "retrosheet_game_id", "game_date", "season", "game_type",
                    "regulation_innings", "pbp_quality", "game_suspended",
                    "final_available_date", "population_category", "source_key"]
RUN_COLUMNS = ["game_id", "play_number", "inning", "top_bottom", "outs_before", "outs_after",
               "visiting_score_before", "home_score_before", "visiting_score_after", "home_score_after",
               "runs_scored", "pa_outcome"]


def now():
    return datetime.now(timezone.utc).isoformat()


def ref(path):
    path = Path(path)
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def put(value, name):
    raw = canonical_json_bytes(value)
    digest = hashlib.sha256(raw).hexdigest()
    path = OUT / "objects/sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, "Immutable declaration conflict"
    else:
        path.write_bytes(raw)
    return ref(path)


def pointer(value, name):
    path = OUT / name
    raw = canonical_json_bytes(value)
    if path.exists():
        assert path.read_bytes() == raw, "Frozen pointer already exists with different bytes"
    else:
        path.write_bytes(raw)


def main():
    current = OUT / "current.json"
    if current.exists():
        print(current.read_text())
        return
    manifest_path = SOURCE / "sports-dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert semantic_manifest_sha(manifest) == MANIFEST
    rights_path = SOURCE / "source-rights.json"
    rights = json.loads(rights_path.read_text(encoding="utf-8"))
    assert "INTERNAL_DERIVED_ANALYTICS" in rights["package_allowed_purposes"]
    expected_rights = next(x for x in manifest["package_artifacts"] if x["logical_uri"] == "source-rights.json")
    assert ref(rights_path)["sha256"] == expected_rights["sha256"]
    partitions = [x for x in manifest["partitions"] if x["family"] == "play_transition" and x["season"] in SEASONS]
    assert {x["season"] for x in partitions} == set(SEASONS)
    metadata_frames, sources = [], []
    for part in partitions:
        path = SOURCE / part["package_relative_uri"]
        assert f"season={part['season']}" in path.parts
        bound = ref(path)
        assert bound["sha256"] == part["file_sha256"] and bound["bytes"] == part["byte_count"]
        metadata = pq.ParquetFile(path).read(columns=IDENTITY_COLUMNS).to_pandas()
        assert len(metadata) == part["row_count"] and set(metadata.season) == {part["season"]}
        metadata_frames.append(metadata)
        sources.append(bound | {"season": part["season"], "rows": len(metadata),
                                 "partitionId": part["partition_id"]})
    meta = pd.concat(metadata_frames, ignore_index=True)
    identities = meta[IDENTITY_COLUMNS].drop_duplicates()
    for key in ("game_id", "retrosheet_game_id"):
        identities[f"{key}_eligible"] = final_oot_eligible_key_mask(identities[key].astype(str).tolist())
    blocked_ids = sorted(identities.loc[~identities.game_id_eligible | ~identities.retrosheet_game_id_eligible, "game_id"].unique())
    assert not identities.game_date.str[:4].astype(int).isin([2024, 2025, 2026]).any()
    eligible = identities[
        identities.game_id_eligible & identities.retrosheet_game_id_eligible
        & identities.pbp_quality.eq("FULL") & identities.game_type.eq("regular")
        & identities.regulation_innings.isin([7, 9])
        & identities.final_available_date.notna()
        & identities.final_available_date.le("2023-10-01")
    ].copy()
    # Conflicting game-level metadata is unsupported, not silently reduced to a row.
    counts = eligible.groupby("game_id").size()
    conflict_ids = counts[counts != 1].index.tolist()
    eligible = eligible[~eligible.game_id.isin(conflict_ids)]
    eligible_ids = set(eligible.game_id)
    declaration = {
        "schemaVersion": "MLB_V18_SCORE_LIMIT_DEVELOPMENT_SELECTION_V1", "declaredAtUtc": now(),
        "configurationId": CONFIGURATION, "seasons": list(SEASONS),
        "developmentAuthority": ref(ROOT / "docs/contracts/MLB_BASE_OUT_TRANSITION_MODEL_V1.md"),
        "authorityInstruction": "Development 2021–2023; out-of-time validation 2024; frozen final 2025.",
        "sourceManifest": ref(manifest_path), "sourceManifestSemanticSha256": MANIFEST,
        "sourceRights": ref(rights_path), "sources": sources,
        "quarantine": ref(ROOT / "server/artifacts/governance/mlb-final-oot-quarantine-v1.json"),
        "identityOnlyGateBeforeRunColumns": True, "identityColumns": IDENTITY_COLUMNS,
        "inputGames": int(identities.game_id.nunique()), "inputPlayRecords": len(meta),
        "quarantinedGameIds": blocked_ids, "quarantinedGames": len(blocked_ids),
        "quarantinedPlayRecords": int(meta.game_id.isin(blocked_ids).sum()),
        "metadataConflictIds": conflict_ids, "eligibleBeforeOutcomeCompletenessGames": len(eligible_ids),
        "eligibleGameIdentities": eligible.to_dict("records"),
        "selection": "All declared Development 2021–2023 regular FULL-ledger games with known final date through 2023-10-01; regulation 7 or 9. No forecast-performance selection.",
        "completenessRule": "Contiguous whole-game play numbers from 1; contiguous played halves from top 1; zero initial score; every score delta equals runs_scored for batting team; score continuity across plays; nonfinal halves end in 3 outs; natural untied terminal at/after scheduled regulation. Otherwise exclude entire game from both quantiles.",
        "halfInningDenominator": "One observation per actually played (game, inning, batting team) with at least one play, including zero-run and walkoff halves. Unplayed home halves are absent, never zero-filled.",
        "teamGameDenominator": "Two team scores per certified completed game; sum every run-bearing play including non-PA events, not just terminal PA outcomes.",
        "quantile": {"probability": 0.99, "method": "numpy.quantile(method='linear')", "rounding": "math.ceil"},
        "rule": {"symmetricTeams": True, "strictlyExceedsLimitExcluded": True, "equalToLimitAccepted": True,
                 "excludeEntireOriginalDraw": True, "noClippingOrResimulation": True,
                 "minimumAcceptedDraws": 1000, "requiredOriginalDrawCount": 5000,
                 "winnerPick": "HOME if pHome>0.5; AWAY if pHome<0.5; exact0.5 no pick"},
        "forbiddenInputs": ["forecast performance", "September 12 outcomes", "2024 validation partitions", "2025 retired partitions", "2026 Final OOT"],
        "historicalReceiptInspectionDisclosure": "Before selecting this cohort, a read of an old published replay summary unexpectedly displayed preexisting 2024/2025 sample results. No raw 2024/2025 partition was opened and no value from that receipt enters this derivation.",
        "modelChronology": "This historical scoring-prior derivation does not repair or certify inherited V18 training or feature chronology.",
        "providerRequests": 0, "providerBytes": 0, "providerCost": 0,
        "script": ref(Path(__file__)),
    }
    saved_selection = OUT / "selection-before-outcomes.json"
    if saved_selection.exists():
        selection_ref = json.loads(saved_selection.read_text(encoding="utf-8"))
        prior = json.loads(Path(selection_ref["path"]).read_text(encoding="utf-8"))
        assert ref(Path(selection_ref["path"])) == selection_ref
        assert prior["eligibleGameIdentities"] == declaration["eligibleGameIdentities"]
        assert prior["sources"] == sources and prior["quarantine"] == declaration["quarantine"]
    else:
        selection_ref = put(declaration, "selection-before-outcomes.json")
        pointer(selection_ref, "selection-before-outcomes.json")
    # All identity gates and the selection receipt exist before any run columns open.
    if blocked_ids:
        raise ValueError("Protected identities in selected Development files; selective approved loading required")
    frames = [pq.ParquetFile(Path(x["path"])).read(columns=RUN_COLUMNS).to_pandas() for x in sources]
    frame = pd.concat(frames, ignore_index=True)
    frame = frame[frame.game_id.isin(eligible_ids)].sort_values(["game_id", "play_number"], kind="stable")
    meta_by_game = eligible.set_index("game_id")
    all_half_runs, all_team_runs, games, excluded = [], [], [], []
    season_counts = Counter()
    non_pa_rows = non_pa_runs = 0
    pa_classes = {"STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH"}
    for gid, group in frame.groupby("game_id", sort=True):
        reasons = []
        gmeta = meta_by_game.loc[gid]
        values = group[RUN_COLUMNS[1:-1]].to_numpy()
        if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
            reasons.append("NONINTEGER_OR_MISSING_STATE")
        play = group.play_number.to_numpy()
        if not np.array_equal(play, np.arange(1, len(group) + 1)):
            reasons.append("NONCONTIGUOUS_PLAY_NUMBER")
        before = group[["visiting_score_before", "home_score_before"]].to_numpy()
        after = group[["visiting_score_after", "home_score_after"]].to_numpy()
        runs = group.runs_scored.to_numpy()
        # event_from_row() in the existing replay engine is authoritative: FD1
        # top_bottom=0 means visiting/top. The old Markdown contract reverses it.
        top = 1 - group.top_bottom.to_numpy()
        delta = after - before
        if not np.array_equal(before[0], [0, 0]) or not np.array_equal(before[1:], after[:-1]):
            reasons.append("SCORE_CONTINUITY")
        if not ((runs >= 0).all() and np.array_equal(delta[:, 0], runs * top)
                and np.array_equal(delta[:, 1], runs * (1-top))):
            reasons.append("RUN_SCORE_DELTA_MISMATCH")
        half_index = (group.inning.to_numpy() - 1) * 2 + (1 - top)
        half_ids = pd.unique(half_index)
        if not np.array_equal(half_ids, np.arange(half_ids[-1] + 1)):
            reasons.append("NONCONTIGUOUS_PLAYED_HALF")
        half_ends = group.loc[np.r_[half_index[1:] != half_index[:-1], True]]
        if not half_ends.iloc[:-1].outs_after.eq(3).all():
            reasons.append("INCOMPLETE_INTERIOR_HALF")
        last = group.iloc[-1]
        regulation = int(gmeta.regulation_innings)
        terminal = int(last.inning) >= regulation and after[-1, 0] != after[-1, 1]
        if int(last.top_bottom) == 0:
            terminal = terminal and int(last.outs_after) == 3 and after[-1, 1] > after[-1, 0]
        else:
            terminal = terminal and ((after[-1, 1] > after[-1, 0]) or int(last.outs_after) == 3)
        if not terminal:
            reasons.append("INCOMPLETE_OR_SHORTENED_WITHOUT_CERTIFIED_NATURAL_TERMINAL")
        if reasons:
            excluded.append({"gameId": gid, "gameDate": gmeta.game_date, "reasons": reasons})
            continue
        half = group.groupby(["inning", "top_bottom"], sort=True).runs_scored.sum()
        team = group.groupby("top_bottom").runs_scored.sum()
        assert int(team.loc[0]) == int(after[-1, 0]) and int(team.loc[1]) == int(after[-1, 1])
        all_half_runs.extend(map(int, half.tolist()))
        all_team_runs.extend([int(after[-1, 0]), int(after[-1, 1])])
        nonpa = ~group.pa_outcome.isin(pa_classes)
        non_pa_rows += int(nonpa.sum())
        non_pa_runs += int(group.loc[nonpa, "runs_scored"].sum())
        games.append({"gameId": gid, "gameDate": gmeta.game_date, "season": int(gmeta.season),
                      "playedHalfInnings": len(half), "playRecords": len(group),
                      "regulationInnings": regulation, "terminalInning": int(last.inning),
                      "suspendedThenCompleted": bool(gmeta.game_suspended)})
        season_counts[int(gmeta.season)] += 1
    assert len(all_team_runs) == 2 * len(games) and all_half_runs
    inning_quantile = float(np.quantile(all_half_runs, 0.99, method="linear"))
    game_quantile = float(np.quantile(all_team_runs, 0.99, method="linear"))
    accounting = {
        "schemaVersion": "MLB_V18_SCORE_LIMIT_DEVELOPMENT_ACCOUNTING_V1", "createdAtUtc": now(),
        "derivationScript": ref(Path(__file__)),
        "halfMappingAuthority": ref(ROOT / "server/sports_phase5/game_replay.py"),
        "halfMapping": "top_bottom=0 is visitor/top; top_bottom=1 is home/bottom, as implemented by existing event_from_row and reconciled against every score delta. The old Markdown replay contract states the reverse; it is not used for this mapping.",
        "selection": selection_ref, "games": games, "completenessExcludedGames": excluded,
        "retainedGames": len(games), "gamesBySeason": dict(season_counts),
        "retainedPlayRecords": int(sum(g["playRecords"] for g in games)),
        "playedHalfInnings": len(all_half_runs), "teamGames": len(all_team_runs),
        "runCountHistogramPlayedHalfInnings": dict(sorted(Counter(all_half_runs).items())),
        "runCountHistogramTeamGames": dict(sorted(Counter(all_team_runs).items())),
        "nonPaPlayRecordsIncluded": non_pa_rows, "nonPaRunsIncluded": non_pa_runs,
        "regulationSevenGamesIncluded": sum(g["regulationInnings"] == 7 for g in games),
        "extraInningGamesIncluded": sum(g["terminalInning"] > g["regulationInnings"] for g in games),
        "suspendedThenCompletedGamesIncluded": sum(g["suspendedThenCompleted"] for g in games),
        "dateRange": {"minimum": min(g["gameDate"] for g in games), "maximum": max(g["gameDate"] for g in games)},
        "reconciliation": {"allRunsEqualFinalScoreDeltas": True, "twoTeamObservationsPerGame": True,
                           "unplayedHalfInningsZeroFilled": False, "paOnlyFilteringApplied": False},
    }
    accounting_ref = put(accounting, "source-accounting.json")
    rule = {
        "schemaVersion": "MLB_V18_SCORE_LIMIT_RULE_V1", "configurationId": CONFIGURATION,
        "frozenAtUtc": now(), "selection": selection_ref, "sourceAccounting": accounting_ref,
        "maxRunsPerTeamPerPlayedHalfInning": math.ceil(inning_quantile),
        "maxRunsPerTeamPerGame": math.ceil(game_quantile),
        "limits": {"maxRunsPerPlayedHalfInning": math.ceil(inning_quantile), "maxRunsPerTeamGame": math.ceil(game_quantile)},
        "minimumRetainedDraws": 1000, "strictExceeds": True, "symmetric": True,
        "outcomePerformanceExamined": False,
        "developmentQuantiles": {"playedHalfInningRunsP99": inning_quantile, "teamGameRunsP99": game_quantile,
                                 "method": "numpy.quantile(method='linear') then math.ceil", "probability": 0.99},
        "developmentPopulation": {k: accounting[k] for k in ("retainedGames", "playedHalfInnings", "teamGames", "gamesBySeason", "dateRange")},
        "acceptanceRule": "Accept the original complete draw iff every played half-inning for both teams is <= the inning limit AND both team final scores are <= the game limit. Preserve each accepted draw unchanged; do not clip, stop, manufacture ties, or resimulate.",
        "minimumAcceptedDraws": 1000, "requiredOriginalDrawCount": 5000,
        "winnerPick": declaration["rule"]["winnerPick"],
        "thresholdOptimization": False, "forecastPerformanceReadBeforeFreeze": False,
        "researchOnly": True, "productionAuthority": False, "promotionAuthority": False,
        "attribution": "The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org. ASP transformation: pooled historical run-count quantiles on the declared Development cohort.",
        "limitations": ["Initial historical research thresholds, not optimized settings.", "2021–2022 prior-only history and 2023 Development are pooled as declared; historical scoring environments and scheduled game lengths differ.", "Inherited V18 chronology remains uncertified."],
        "command": ".venv/Scripts/python.exe -B scripts/derive_mlb_v18_score_limits_v1.py",
    }
    rule_ref = put(rule, "rule.json")
    pointer({"rule": rule_ref, "sourceAccounting": accounting_ref, "selection": selection_ref}, "current.json")
    print(json.dumps({"rule": rule_ref, "limits": [math.ceil(inning_quantile), math.ceil(game_quantile)],
                      "games": len(games), "halfInnings": len(all_half_runs), "teamGames": len(all_team_runs),
                      "completenessExclusions": len(excluded)}, indent=2))


if __name__ == "__main__":
    main()
