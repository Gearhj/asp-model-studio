"""Phase 6E — PA development population authority.

The registered FD1 dataset spans 2021-2025, but the manifest temporal contract classifies 2021-2022
as PRIOR_ONLY_HISTORY (Y-1 prior construction only; the prior_only population is contractually
prohibited from PRIMARY_2023_2025_TARGET_TRAINING). The PA modeling matrix (feature view) is 2023-2025:
development=2023, validation=2024, frozen final=2025.

These tests prove the backend authorities cannot silently disagree with that governed window, that the
frozen 2025 season is never a development season, that 2024 remains validation, and that extending the
displayed source-evidence span did NOT change the feature contract (feature names / target / seasons).
No models are trained; no heavy modeling is exercised.
"""

from __future__ import annotations

import pytest

from server.sports_modeling import feature_contract as FC
from server.sports_cockpit import engine as E

# --- Frozen feature-contract authority (no materialized view required) ------------------------------


def test_feature_contract_seasons_are_2023_2025_only():
    assert FC.TARGET_SEASONS == (2023, 2024, 2025)
    assert 2021 not in FC.TARGET_SEASONS
    assert 2022 not in FC.TARGET_SEASONS
    assert dict(FC.EXPECTED_SEASON_ROWS) == {2023: 184_104, 2024: 182_449, 2025: 182_926}
    assert FC.EXPECTED_TOTAL_ROWS == 549_479
    assert sum(FC.EXPECTED_SEASON_ROWS.values()) == FC.EXPECTED_TOTAL_ROWS


def test_feature_contract_definitions_unchanged_by_the_audit():
    # Feature-contract test: reconciling the displayed development window must not change the feature
    # taxonomy, the target taxonomy, or the season set the modeling matrix is built from.
    assert len(FC.FEATURE_NAMES) == 22
    assert FC.FEATURE_NAMES[0] == "context_inning"
    assert FC.FEATURE_NAMES[-1] == "pitcher_prior_missing"
    payload = FC.feature_contract_payload()
    assert payload["seasons"] == [2023, 2024, 2025]
    # target taxonomy is the frozen 8-class order, unchanged
    assert payload["classOrder"] == list(FC.PA_CLASS_ORDER)
    assert len(payload["classOrder"]) == 8


def test_engine_development_constants_agree_with_governed_window():
    assert E.DEV_SEASON == 2023
    assert E.VAL_SEASON == 2024
    assert E.FROZEN_SEASON == 2025
    assert E.TARGET_SEASONS == (2023, 2024, 2025)


# --- Engine payload authority (requires the materialized feature view) ------------------------------

_HAS_VIEW = True
try:
    from tests._runtime_probe import IS_SYNTHETIC_SEED as _IS_SYNTHETIC_SEED
    E._feature_view_path()
    _HAS_VIEW = not _IS_SYNTHETIC_SEED   # real D3/Gen-2 view only; a synthetic seed fails real-data assertions
except Exception:
    _HAS_VIEW = False

view_required = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")


@view_required
def test_population_payload_reports_2023_development_only():
    pop = E.population_payload()
    tp = pop["temporalPolicy"]
    assert tp["development"] == [2023]
    assert tp["validation"] == 2024
    assert tp["frozenFinal"] == 2025
    assert 2025 not in tp["development"]  # frozen season is never development
    # per-season roles: exactly 2023/2024/2025, no 2021/2022 leaked into the matrix
    seasons = {row["season"]: row["role"] for row in pop["perSeason"]}
    assert seasons == {2023: "development", 2024: "validation", 2025: "frozen_final"}
    assert pop["totalRows"] == 549_479


@view_required
def test_population_payload_declares_source_vs_development_authority():
    src = E.population_payload()["sourceEvidence"]
    assert src["registeredSeasons"] == [2021, 2022, 2023, 2024, 2025]
    assert src["priorOnlyHistory"] == [2021, 2022]
    assert src["modelingDevelopment"] == [2023]
    assert src["validation"] == 2024
    assert src["frozenFinal"] == 2025
    assert "PRIOR_ONLY_HISTORY" in src["note"]


@view_required
def test_source_evidence_two_layer_counts_and_roles():
    # Phase 6E.1 — Data & Population shows registered evidence (2021-2025) AND the modeling matrix
    # (2023-2025) as two distinct layers, with every season's role visible.
    src = E.population_payload()["sourceEvidence"]
    assert src["registeredTotalRows"] == 913_349
    assert src["priorHistoryTotalRows"] == 363_870
    assert src["modelingTotalRows"] == 549_479
    assert src["priorHistoryTotalRows"] + src["modelingTotalRows"] == src["registeredTotalRows"]
    roles = {row["season"]: row["role"] for row in src["perSeason"]}
    counts = {row["season"]: row["rows"] for row in src["perSeason"]}
    assert roles == {
        2021: "PRIOR_HISTORY", 2022: "PRIOR_HISTORY",
        2023: "DEVELOPMENT", 2024: "VALIDATION", 2025: "FROZEN_FINAL",
    }
    assert counts == {2021: 181_818, 2022: 182_052, 2023: 184_104, 2024: 182_449, 2025: 182_926}


@view_required
def test_lineage_waterfall_does_not_drop_prior_history():
    # The funnel must show the prior-history split, not a quality "drop", and start at 913,349.
    wf = E.population_payload()["waterfall"]
    assert wf[0]["rows"] == 913_349 and wf[0]["kind"] == "source"
    kinds = {w["kind"] for w in wf}
    assert "prior" in kinds  # prior-history stage is present as its own parallel role
    prior_stage = next(w for w in wf if w["kind"] == "prior")
    assert prior_stage["rows"] == 363_870
    final_stage = next(w for w in wf if w["kind"] == "final")
    assert final_stage["rows"] == 184_104  # development target population (2023)


@view_required
def test_matrix_contains_no_prior_only_history_rows():
    # Identity/leakage: 2021-2022 remain prior-only; the modeling matrix must contain only 2023-2025.
    frame = E.load_frame()
    seasons = set(int(s) for s in frame["season"].unique().tolist())
    assert seasons == {2023, 2024, 2025}
    assert 2021 not in seasons and 2022 not in seasons


@view_required
def test_objective_and_preview_agree_on_the_same_temporal_window():
    obj = E.objective_payload()
    assert list(obj["seasons"]) == [2023, 2024, 2025]
    assert obj["totalRows"] == 549_479
    prev = E.data_preview(limit=5)
    assert prev["seasons"] == [2023, 2024, 2025]
    roles = {s["role"]: s["season"] for s in prev["splitCounts"]}
    assert roles == {"development": 2023, "validation": 2024, "frozen_final": 2025}
