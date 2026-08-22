"""Phase 7D.2 — code/environment content closure (Gate 11) and legacy 2025 retirement (Gate 12).

Hermetic behavioral matrices E (drift) and F (sealed legacy). No sealed data is opened; the code-identity
probes create + delete temp files in the working tree and restore it.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from server.sports_cockpit import engine as E
from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit import modeling as M

REPO = Path(__file__).resolve().parents[1]
_HAS_V2 = (REPO / ".runtime/asp-model-studio/sports-modeling/mlb-pa-gen3-v2/registration.json").is_file()


# ============================================================ Gate 11 — code/environment content closure
def test_code_identity_binds_untracked_content_and_excludes_audit_reports():
    base = A._code_identity()
    assert base["codeRevision"] != "UNKNOWN" and base["worktreeContentSha256"] != "UNKNOWN"
    assert A._code_identity()["worktreeContentSha256"] == base["worktreeContentSha256"]  # stable
    # (1) an untracked scientific file's CONTENT is bound; changing it changes the identity
    probe = REPO / ("_phase7d2_probe_" + uuid.uuid4().hex[:8] + ".py")
    probe.write_text("x = 1\n", encoding="utf-8")
    try:
        s1 = A._code_identity()["worktreeContentSha256"]
        assert s1 != base["worktreeContentSha256"]
        probe.write_text("x = 2\n", encoding="utf-8")
        assert A._code_identity()["worktreeContentSha256"] != s1
    finally:
        probe.unlink(missing_ok=True)
    # (2) a named audit Markdown report is excluded (does not change the identity)
    rep = REPO / "docs" / ("PHASE_7D2_PROBE_" + uuid.uuid4().hex[:8] + "_REPORT.md")
    rep.write_text("# probe\n", encoding="utf-8")
    try:
        assert A._is_excluded_audit_report(str(rep.relative_to(REPO)).replace("\\", "/"))
        assert A._code_identity()["worktreeContentSha256"] == base["worktreeContentSha256"]
    finally:
        rep.unlink(missing_ok=True)
    assert A._code_identity()["worktreeContentSha256"] == base["worktreeContentSha256"]  # restored


def test_unknown_code_or_environment_is_rejected():
    with pytest.raises(A.StaleAuthorityError):
        A._require_known_code_env({"codeRevision": "UNKNOWN", "worktreeContentSha256": "abc"}, "envsha")
    with pytest.raises(A.StaleAuthorityError):
        A._require_known_code_env({"codeRevision": "abc", "worktreeContentSha256": "UNKNOWN"}, "envsha")
    with pytest.raises(A.StaleAuthorityError):
        A._require_known_code_env({"codeRevision": "abc", "worktreeContentSha256": "def"}, "UNKNOWN")


# ============================================================ Gate 12 — sealed-legacy matrix (F)
def test_all_legacy_execution_functions_are_retired_before_data_open():
    assert issubclass(M.LegacyModelingRetiredError, E.CockpitError)
    with pytest.raises(M.LegacyModelingRetiredError):
        M.champion_baseline()
    with pytest.raises(M.LegacyModelingRetiredError):
        M.run_experiment({"features": ["batter_avg"], "family": "logistic"}, persist=False)
    with pytest.raises(M.LegacyModelingRetiredError):
        M.run_ablation({"baseConfig": {"features": list(E.ALL_FEATURES), "family": "logistic"}})
    with pytest.raises(M.LegacyModelingRetiredError):
        M.run_autopilot({"features": list(E.ALL_FEATURES)}, budget="quick", persist=False)
    with pytest.raises(M.LegacyModelingRetiredError):
        M._fit_and_evaluate(None, list(E.ALL_FEATURES), "logistic", {}, None, None)
    # fit_cockpit_model is RETAINED (2023-only fit for the simulator; never fits/scores 2025)
    assert not isinstance(getattr(M, "fit_cockpit_model", None), type(None))


def test_retired_message_points_to_the_canonical_path():
    with pytest.raises(M.LegacyModelingRetiredError) as exc:
        M.run_experiment({}, persist=False)
    assert "gen3_authority" in str(exc.value)


def test_champion_reference_carries_no_2025_metric():
    ref = E._champion_reference()
    assert "frozen2025" not in ref and "final2025" not in ref
    assert "frozen2025" not in json.dumps(ref)
    assert ref["val2024"]["logLoss"] > 0
    assert ref["sealed2025"] == "RESTRICTED_ARCHIVAL_AUDIT_EVIDENCE"


def test_champion_reference_fallback_has_no_frozen_constant():
    assert "frozen2025" not in E.CHAMPION_REFERENCE_FALLBACK
    assert "final2025" not in E.CHAMPION_REFERENCE_FALLBACK


@pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")
def test_canonical_research_path_is_2024_only_no_frozen():
    proj = "test-7d2-" + uuid.uuid4().hex[:12]
    dsid = {c["generation"]: c["datasetVersionId"] for c in A.catalog()}["GEN3"]
    A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=dsid)
    pop = A.binding_population(project_id=proj)
    assert pop["validationSeason"] == 2024 and pop["sealedSeasons"] == [2025]
    assert 2025 not in pop["developmentSeasons"]
    assert "frozen2025" not in json.dumps(pop) and "final2025" not in json.dumps(pop)
