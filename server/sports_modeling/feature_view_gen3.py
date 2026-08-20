"""Gen-3 point-in-time PA feature view (Phase 7).

A governed, PARALLEL feature-view pathway that extends the executable development population to
2021-2023 without touching the frozen Gen-2 contract (``feature_view.build_mlb_pa_feature_view_v1`` is
deliberately locked to 2023-2025 by the Phase-6E PRIOR_ONLY_HISTORY contract). This builder reuses the
EXACT identity resolution, prior lookup, and per-row feature math from ``feature_view`` — it only relaxes
the season gate (2021-2025) and the ``population_category`` gate (accepting both
``GEN2_PRIMARY_2023_2025`` and ``GEN2_PRIOR_ONLY_2021_2022``). By construction, the 2023-2025 rows it
produces are identical to the frozen Gen-2 view (verified in tests), so the base-feature semantics are the
same across every season — the requirement for a fair training-volume ablation.

Scientific note: ``player_prior`` begins at season=2021 (eligible_from 2022), so every 2021 target PA is
legitimately prior-blind (``batter_prior_missing = pitcher_prior_missing = True``). 2022 and 2023 targets
are fully prior-valid. Nothing here fits models, selects features, or touches 2025 for selection.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import pyarrow as pa

from .feature_view import (
    BATTER_FEATURES,
    PITCHER_FEATURES,
    FeatureViewIntegrityError,
    _arrow_schema,
    _batting_features,
    _pitching_features,
    _PA_COLUMNS,
    _prior_lookup,
    _require_columns,
)
from .metrics import PA_CLASS_ORDER

GEN3_TARGET_SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)
GEN3_DEVELOPMENT_SEASONS: tuple[int, ...] = (2021, 2022, 2023)
GEN3_VALIDATION_SEASON = 2024
GEN3_SECONDARY_OOT_SEASON = 2025
GEN3_PROSPECTIVE_SEALED_SEASON = 2026
_ACCEPTED_POPULATIONS = {"GEN2_PRIMARY_2023_2025", "GEN2_PRIOR_ONLY_2021_2022"}


def build_gen3_feature_table(
    plate_appearance_tables: Sequence[pa.Table],
    player_prior_table: pa.Table,
    *,
    retrosheet_aliases: Mapping[str, str],
    dimension_uuids: frozenset[str],
    seasons: Sequence[int] = GEN3_TARGET_SEASONS,
) -> tuple[pa.Table, dict[str, Any]]:
    """Materialize the Gen-3 feature table for ``seasons`` (subset of 2021-2025).

    Returns ``(table, reconciliation)``. Faithful to the Gen-2 per-row math; only the season and
    population gates are widened. No frozen row-count assertions — observed counts are returned for
    reconciliation instead.
    """
    target_seasons = tuple(int(s) for s in seasons)
    if not target_seasons or any(s not in GEN3_TARGET_SEASONS for s in target_seasons):
        raise FeatureViewIntegrityError("gen3 seasons must be a non-empty subset of 2021-2025")
    if not dimension_uuids or not retrosheet_aliases:
        raise FeatureViewIntegrityError("a non-empty exact identity bridge is required")

    pa_table = pa.concat_tables(
        [t.select(_PA_COLUMNS) for t in plate_appearance_tables], promote_options="none"
    )
    prior_lookup = _prior_lookup(
        player_prior_table, dimension_uuids=dimension_uuids, target_seasons=target_seasons
    )
    values = pa_table.to_pydict()
    output: dict[str, list[Any]] = {field.name: [] for field in _arrow_schema()}
    seen_pa_ids: set[str] = set()
    season_counts: Counter[int] = Counter()
    prior_missing = {(s, role): 0 for s in target_seasons for role in ("BATTER", "PITCHER")}
    prior_eligible = {(s, role): 0 for s in target_seasons for role in ("BATTER", "PITCHER")}
    # Fail-closed quarantine (Phase 7A Gate 2): rows with a structural, outcome-independent anomaly are
    # excluded from the modeling view with an explicit reason and a ROW-LEVEL LEDGER entry — never
    # silently dropped, never outcome/metric-conditioned. Truly corrupt lineage still hard-fails.
    quarantine: Counter[tuple[int, str]] = Counter()
    quarantine_ledger: list[dict[str, Any]] = []

    for index in range(pa_table.num_rows):
        season = values["season"][index]
        if not isinstance(season, int) or season not in target_seasons:
            continue  # partition set may include seasons outside the requested subset
        pa_id = values["plate_appearance_id"][index]
        game_id = values["game_id"][index]
        game_date = values["game_date"][index]
        outcome = values["outcome"][index]
        if (
            not isinstance(pa_id, str) or not pa_id or pa_id in seen_pa_ids
            or not isinstance(game_id, str) or not game_id
            or not isinstance(game_date, str) or not game_date.startswith(f"{season:04d}-")
        ):
            raise FeatureViewIntegrityError("plate_appearance lineage keys are null, duplicated, or invalid")
        seen_pa_ids.add(pa_id)
        if outcome not in PA_CLASS_ORDER:
            raise FeatureViewIntegrityError("plate_appearance outcome is outside the frozen class order")
        # Gen-3 population/timing gate: accept primary + prior-only, same strict leakage semantics.
        if (
            values["population_category"][index] not in _ACCEPTED_POPULATIONS
            or values["strict_population"][index] != "GEN2_STRICT_DEPLOYABLE_RECONSTRUCTION"
            or values["canonical_identity_resolved"][index] is not False
            or values["timing_risk_label"][index] != "RETROSPECTIVE_EVENT_OUTCOME_TIMING_RISK"
            or values["target_only_not_pregame_feature"][index] is not True
            or values["strict_same_game_pregame_eligible"][index] is not False
            or values["enhanced_research_eligible"][index] is not True
        ):
            raise FeatureViewIntegrityError("plate_appearance population or timing evidence differs")

        inning = values["inning"][index]
        top_bottom = values["top_bottom"][index]
        outs_before = values["outs_before"][index]
        base_mask = values["base_mask_before"][index]
        visiting_score = values["visiting_score_before"][index]
        home_score = values["home_score_before"][index]
        # Schema V2 (Gate 2): legitimate innings 15-16 are INCLUDED (Gen-2 V1 capped at 14). context_inning
        # is int16 and the feature semantics are unchanged; excluding long games conditioned the target
        # population, so those 27 real PAs are now materialized.
        if (
            not isinstance(inning, int) or inning < 1 or inning > 16
            or top_bottom not in (0, 1) or outs_before not in (0, 1, 2)
            or not isinstance(base_mask, int) or base_mask < 0 or base_mask > 7
            or not isinstance(visiting_score, int) or visiting_score < 0
            or not isinstance(home_score, int) or home_score < 0
        ):
            raise FeatureViewIntegrityError("pre-terminal plate-appearance state is null or out of range")
        expected_batting_team = (
            values["visiting_team_id"][index] if top_bottom == 0 else values["home_team_id"][index]
        )
        if values["batting_team_id"][index] != expected_batting_team:
            # Batting-team convention anomaly: the stored batting_team_id conflicts with the
            # home/visitor-by-half convention that score_difference depends on. The exact cause is not
            # proven by a persisted source flag, so we fail closed rather than emit a possibly signed-
            # wrong score feature. Zero such rows exist in 2023-2025. Recorded in the row-level ledger.
            quarantine[(season, "BATTING_TEAM_CONVENTION_ANOMALY")] += 1
            quarantine_ledger.append({
                "plate_appearance_id": pa_id, "game_id": game_id, "season": season,
                "reasonCode": "BATTING_TEAM_CONVENTION_ANOMALY",
                "reasonDetail": "batting_team_id conflicts with home/visitor-by-half convention used for score_difference",
                "decisionRuleVersion": "MLB_GEN3_POPULATION_CONTRACT_V1",
            })
            continue
        score_difference = (
            visiting_score - home_score if top_bottom == 0 else home_score - visiting_score
        )

        batter_key = values["batter_id"][index]
        pitcher_key = values["pitcher_id"][index]
        batter_uuid = retrosheet_aliases.get(batter_key)
        pitcher_uuid = retrosheet_aliases.get(pitcher_key)
        if (
            not isinstance(batter_key, str) or not isinstance(pitcher_key, str)
            or batter_uuid not in dimension_uuids or pitcher_uuid not in dimension_uuids
        ):
            # Unresolved batter/pitcher identity → fail-closed quarantine (never a silent target row).
            quarantine[(season, "IDENTITY_UNRESOLVED")] += 1
            continue

        batter_prior = prior_lookup.get((season, batter_uuid, "BATTING"))
        pitcher_prior = prior_lookup.get((season, pitcher_uuid, "PITCHING"))
        for role, prior in (("BATTER", batter_prior), ("PITCHER", pitcher_prior)):
            if prior is None:
                prior_missing[(season, role)] += 1
            else:
                prior_eligible[(season, role)] += 1
        batter_values = _batting_features(batter_prior[2]) if batter_prior else {}
        pitcher_values = _pitching_features(pitcher_prior[2]) if pitcher_prior else {}

        row = {
            "plate_appearance_id": pa_id, "game_id": game_id, "game_date": game_date,
            "season": season, "outcome": outcome,
            "batter_canonical_player_uuid": batter_uuid,
            "pitcher_canonical_player_uuid": pitcher_uuid,
            "batter_prior_season": batter_prior[0] if batter_prior else None,
            "batter_prior_eligible_from_season": batter_prior[1] if batter_prior else None,
            "pitcher_prior_season": pitcher_prior[0] if pitcher_prior else None,
            "pitcher_prior_eligible_from_season": pitcher_prior[1] if pitcher_prior else None,
            "context_inning": inning, "context_top_bottom": top_bottom,
            "context_outs_before": outs_before, "context_base_mask_before": base_mask,
            "context_batting_score_diff_before": score_difference,
            **{n: batter_values.get(n) for n in BATTER_FEATURES if not n.endswith("_missing")},
            "batter_prior_missing": batter_prior is None,
            **{n: pitcher_values.get(n) for n in PITCHER_FEATURES if not n.endswith("_missing")},
            "pitcher_prior_missing": pitcher_prior is None,
        }
        for name in output:
            output[name].append(row[name])
        season_counts[season] += 1

    table = pa.Table.from_pydict(output, schema=_arrow_schema()).sort_by(
        [("season", "ascending"), ("game_date", "ascending"),
         ("game_id", "ascending"), ("plate_appearance_id", "ascending")]
    )
    reconciliation = {
        "seasons": target_seasons,
        "seasonRows": dict(sorted(season_counts.items())),
        "rowCount": table.num_rows,
        "priorEligible": {f"{s}:{r}": prior_eligible[(s, r)] for (s, r) in sorted(prior_eligible)},
        "priorMissing": {f"{s}:{r}": prior_missing[(s, r)] for (s, r) in sorted(prior_missing)},
        "quarantined": {f"{s}:{reason}": n for (s, reason), n in sorted(quarantine.items())},
        "quarantinedTotal": int(sum(quarantine.values())),
        "quarantineLedger": quarantine_ledger,
    }
    return table, reconciliation
