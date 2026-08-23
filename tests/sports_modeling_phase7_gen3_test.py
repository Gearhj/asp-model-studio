"""Phase 7 — Gen-3 development-population extension tests.

Covers: the Gen-3 temporal contract invariants, the Gen-3 builder's season/population gate, 2021
prior-blindness, exact prior-coverage parity with the frozen Gen-2 view on 2023-2025, explicit
quarantine of 2021/2022 anomalies (never silent), the leakage guarantee that 2025 is never a
development season, and 2026 is untouched. Parquet-dependent checks skip cleanly if the Gen-3 view has
not been materialized (build via scripts/phase7_build_gen3.py).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.sports_modeling import feature_view_gen3 as G3
from server.sports_modeling.feature_view import EXPECTED_PRIOR_COVERAGE
from server.sports_modeling.feature_contract import EXPECTED_SEASON_ROWS as GEN2_SEASON_ROWS
from server.sports_modeling.feature_view import FeatureViewIntegrityError

REPO = Path(__file__).resolve().parents[1]
from tests._runtime_probe import GEN3_V1_PARQUET as GEN3_PARQUET, GEN3_V1_RECON as RECON, HAS_REAL_GEN3_V1 as _HAS_GEN3  # real Gen-3 v1 view
skip_gen3 = pytest.mark.skipif(not _HAS_GEN3, reason="Gen-3 feature view not materialized")


# ---------------- temporal contract invariants (no data needed) ----------------
def test_gen3_temporal_contract_invariants():
    assert G3.GEN3_TARGET_SEASONS == (2021, 2022, 2023, 2024, 2025)
    assert G3.GEN3_DEVELOPMENT_SEASONS == (2021, 2022, 2023)
    assert G3.GEN3_VALIDATION_SEASON == 2024
    assert G3.GEN3_SECONDARY_OOT_SEASON == 2025
    assert G3.GEN3_PROSPECTIVE_SEALED_SEASON == 2026
    # frozen 2025 is NEVER a development season; 2026 is not part of the executable target set
    assert 2025 not in G3.GEN3_DEVELOPMENT_SEASONS
    assert 2026 not in G3.GEN3_TARGET_SEASONS
    # accepts both the primary and prior-only populations (widened vs Gen-2), nothing else
    assert G3._ACCEPTED_POPULATIONS == {"GEN2_PRIMARY_2023_2025", "GEN2_PRIOR_ONLY_2021_2022"}


def test_gen3_builder_rejects_out_of_range_seasons():
    import pyarrow as pa
    with pytest.raises(FeatureViewIntegrityError):
        G3.build_gen3_feature_table([pa.table({"x": [1]})], pa.table({"x": [1]}),
                                    retrosheet_aliases={"a": "b"}, dimension_uuids=frozenset({"b"}),
                                    seasons=(2019, 2020))


# ---------------- materialized-view checks ----------------
@skip_gen3
def test_gen3_view_covers_2021_2025_and_reconciliation_present():
    import json
    recon = json.loads(RECON.read_text())
    assert set(int(s) for s in recon["seasonRows"]) == {2021, 2022, 2023, 2024, 2025}
    # 2023-2025 development-matrix rows are unchanged from the Gen-2 contract (parity of counts)
    for s in (2023, 2024, 2025):
        assert recon["seasonRows"][str(s)] == GEN2_SEASON_ROWS[s]
    # 2021 + 2022 add > 360k new executable development rows (more than doubling 2023-only development)
    added = recon["seasonRows"]["2021"] + recon["seasonRows"]["2022"]
    assert added > 360_000


@skip_gen3
def test_2021_is_fully_prior_blind_and_2022_2023_are_prior_valid():
    import json
    recon = json.loads(RECON.read_text())
    # every 2021 target PA is prior-blind (no <=2020 player_prior exists)
    assert recon["priorEligible"]["2021:BATTER"] == 0 and recon["priorEligible"]["2021:PITCHER"] == 0
    assert recon["priorMissing"]["2021:BATTER"] == recon["seasonRows"]["2021"]
    # 2022 targets resolve valid priors for the majority of rows
    assert recon["priorEligible"]["2022:BATTER"] > 100_000


@skip_gen3
def test_gen3_2023_2025_prior_coverage_matches_frozen_gen2_authority():
    import json
    recon = json.loads(RECON.read_text())
    # exact reproduction of the frozen Gen-2 EXPECTED_PRIOR_COVERAGE proves identical base-feature semantics
    for (season, role), (eligible, missing) in EXPECTED_PRIOR_COVERAGE.items():
        assert recon["priorEligible"][f"{season}:{role}"] == eligible
        assert recon["priorMissing"][f"{season}:{role}"] == missing


@skip_gen3
def test_2021_2022_anomalies_are_explicitly_quarantined_not_silently_dropped():
    import json
    recon = json.loads(RECON.read_text())
    q = recon["quarantined"]
    # convention + extra-inning anomalies exist only in 2021/2022 and are counted with reasons
    assert any(k.startswith("2021:") for k in q) and any(k.startswith("2022:") for k in q)
    assert not any(k.startswith(("2023:", "2024:", "2025:")) for k in q)
    assert recon["quarantinedTotal"] == sum(q.values())
    # reconciliation closes: materialized + quarantined == registered source for each of 2021/2022
    assert recon["seasonRows"]["2021"] + sum(v for k, v in q.items() if k.startswith("2021:")) == 181_818
    assert recon["seasonRows"]["2022"] + sum(v for k, v in q.items() if k.startswith("2022:")) == 182_052


@skip_gen3
def test_gen3_schema_has_the_22_base_features_target_and_season():
    import pyarrow.parquet as pq
    schema = pq.read_schema(GEN3_PARQUET)
    names = set(schema.names)
    from server.sports_cockpit.engine import ALL_FEATURES
    for f in ALL_FEATURES:
        assert f in names, f"missing base feature {f}"
    assert {"outcome", "season", "plate_appearance_id"}.issubset(names)
