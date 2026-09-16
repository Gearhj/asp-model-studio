"""Phase 7D.5A.1 — explicit season-role authority + sealed-2025 rejection, exercised through the PRODUCTION
resolvers (not source greps).

Proves development / validation / sealed roles are separate and explicitly named; that sealed 2025 is never an
ordinary modeling, research, selection, or DTO season; that the ordinary fit/score resolvers fail closed before any
data open when pointed at the sealed object; that a quarantined Silver publish containing 2025 or 2026 fails; that
sealed-object authority is reachable only through the explicit sealed-governance path; and that the ambiguous
``TARGET_SEASONS`` engine name is eliminated. Constant/Silver checks are hermetic; catalog checks run against the
production registry (real .runtime OR the committed governed seed) so none of these is a skippable behavior.
"""
from __future__ import annotations

import pytest

from server.sports_cockpit import engine as E
from server.sports_cockpit import gen3_authority as A
from server.sports_modeling import feature_contract as FC
from server.sports_modeling import gen3_contracts as GC
from server.sports_modeling import silver_publish as SP
from server.sports_modeling.feature_contract import FEATURE_NAMES


# ---------------------------------------------------------------- explicit roles are separate (constants)
def test_engine_roles_are_explicit_and_separate():
    assert E.DEVELOPMENT_SEASONS == (2023,)
    assert E.VALIDATION_SEASONS == (2024,)
    assert E.SEALED_EVIDENCE_SEASONS == (2025,)
    assert E.MODELING_SEASONS == (2023, 2024)                       # ordinary fit + validate
    assert E.ALL_GOVERNED_SEASONS == (2023, 2024, 2025)
    # the three roles are pairwise disjoint; sealed never overlaps modeling
    assert set(E.DEVELOPMENT_SEASONS).isdisjoint(E.VALIDATION_SEASONS)
    assert set(E.MODELING_SEASONS).isdisjoint(E.SEALED_EVIDENCE_SEASONS)


def test_ambiguous_target_seasons_name_is_eliminated():
    # the dangerous engine constant is gone (not aliased to another meaning)
    assert not hasattr(E, "TARGET_SEASONS")
    # the feature contract keeps TARGET_SEASONS only as the FULL physical inventory, made explicit
    assert FC.TARGET_SEASONS == (2023, 2024, 2025)
    assert FC.ALL_GOVERNED_SEASONS == FC.TARGET_SEASONS
    assert FC.MODELING_SEASONS == (2023, 2024) and 2025 not in FC.MODELING_SEASONS
    assert FC.SEALED_EVIDENCE_SEASONS == (2025,)


def test_engine_and_feature_contract_modeling_windows_agree():
    assert E.MODELING_SEASONS == FC.MODELING_SEASONS               # one ordinary-modeling meaning across layers
    assert E.SEALED_EVIDENCE_SEASONS == FC.SEALED_EVIDENCE_SEASONS


# ---------------------------------------------------------------- Gen-2 vs Gen-3 roles both governed, distinct
def test_gen3_development_is_2021_2023_and_validation_2024():
    assert GC.GEN3_DEVELOPMENT_SEASONS == (2021, 2022, 2023)
    assert 2024 not in GC.GEN3_DEVELOPMENT_SEASONS                 # 2024 is validation, not development
    assert 2025 not in GC.GEN3_DEVELOPMENT_SEASONS                 # sealed, not development
    assert 2025 not in GC.GEN3_RESEARCH_SEASONS                    # ordinary research frame excludes sealed


def test_gen2_and_gen3_roles_are_distinct_and_each_correct():
    # Gen-2 cockpit: development=2023, validation=2024. Gen-3: development=2021-2023, validation=2024.
    assert E.DEVELOPMENT_SEASONS == (2023,)                        # Gen-2 development
    assert GC.GEN3_DEVELOPMENT_SEASONS == (2021, 2022, 2023)       # Gen-3 development (different, explicit)
    assert E.DEVELOPMENT_SEASONS != GC.GEN3_DEVELOPMENT_SEASONS    # not collapsed into one global tuple
    # neither treats 2025 as development/research
    assert 2025 not in E.MODELING_SEASONS and 2025 not in GC.GEN3_RESEARCH_SEASONS


# ---------------------------------------------------------------- ordinary DTO never exposes sealed 2025
def test_ordinary_modeling_window_excludes_sealed_season():
    assert 2025 not in E.MODELING_SEASONS
    # any list an ordinary DTO builds from the modeling window cannot contain the sealed season
    assert 2025 not in list(E.MODELING_SEASONS)


# ---------------------------------------------------------------- sealed catalog governance (production registry)
def _sealed_entries():
    return [e for e in A.catalog() if str(e.get("generation", "")).endswith("_SEALED")]


def test_ordinary_dataset_selection_excludes_sealed_objects():
    cat = A.catalog()
    sealed = _sealed_entries()
    assert sealed, "expected sealed catalog entries (real or seeded)"
    for e in sealed:
        assert e["selectable"] is False                            # never ordinary-selectable
        assert e["status"] == "SEALED_OOT_RESTRICTED"
        assert "objectPath" not in e                               # no ordinary object path is exposed
    # the ordinary selectable set is research-only — no sealed generation leaks in
    selectable = [e["generation"] for e in cat if e.get("selectable")]
    assert selectable and all(not g.endswith("_SEALED") for g in selectable)


def test_ordinary_research_resolver_refuses_sealed_generation():
    # verified_research_object resolves only a SELECTABLE research entry; a sealed generation has none
    with pytest.raises(A.AuthorityError):
        A.verified_research_object("GEN3_SEALED")
    with pytest.raises(A.AuthorityError):
        A.verified_research_object("GEN2_SEALED")


def test_fit_binding_on_a_sealed_object_fails_before_any_open(tmp_path, monkeypatch):
    # attempting to bind (the first step of ordinary fit/score) to a sealed dataset id fails closed, before
    # the object is ever opened — 2025 can never enter an ordinary modeling run this way
    monkeypatch.setattr(A, "STATE_ROOT", tmp_path / "authority")
    A.reset_object_open_log()
    sealed = _sealed_entries()
    assert sealed
    with pytest.raises(A.AuthorityError):
        A.create_binding(actor="roles@asp", project_id="roles-sealed-fit",
                         dataset_version_id=sealed[0]["datasetVersionId"])
    assert A.object_open_log() == []                               # rejected BEFORE any data open


# ---------------------------------------------------------------- quarantined Silver rejects sealed/2026 seasons
def _silver_rows(season_override=None):
    rows = []
    for s in (2023, 2024):
        for b in ("b1", "b2"):
            for ab in range(2):
                r = {"plate_appearance_id": f"pa-{s}-{b}-{ab}", "game_id": f"{s}-g{b}",
                     "game_date": f"{s}-04-0{ab+1}", "at_bat_number": ab,
                     "batter_canonical_player_uuid": b, "season": s}
                for i, f in enumerate(FEATURE_NAMES):
                    r[f] = float((s + ab + i) % 5) / 10.0
                rows.append(r)
    if season_override is not None:
        rows[0]["season"] = season_override
    return rows


@pytest.mark.parametrize("bad_season", [2025, 2026])
def test_quarantined_silver_publish_rejects_sealed_or_future_season(tmp_path, bad_season):
    # a governed source carrying a sealed/prospective season cannot even be published as a source (fail-closed)
    rows = _silver_rows(bad_season)
    with pytest.raises((SP.SourceAuthorityError, SP.SilverPublishError)):
        SP.publish_source_object(source_root=tmp_path / "src", rows=rows, dataset_version_id="bad",
                                 season_of_row=lambda r: r["season"])
