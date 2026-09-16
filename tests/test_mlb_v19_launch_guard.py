"""One regression for all three launch boundaries; no source or model loads."""
import importlib
from pathlib import Path

import pytest

from server.sports_current_statcast.mlb_v19_launch_guard import HOLD_ID, V19StudyIntegrityHold


def test_original_date_only_attempt_cannot_load_fit_evaluate_or_package(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))

    def forbidden(*args, **kwargs):
        pytest.fail("An integrity-held entry point reached data loading or fitting")

    # A permissive external setting cannot change this code-pinned hold.
    monkeypatch.setenv("MLB_V19_SUSPENDED_GAME_AVAILABILITY_HOLD_V1", "false")
    for name, argument, stage in (
        ("run_mlb_v19_study", [1], "GLOBAL_STUDY"),
        ("evaluate_mlb_v19_study", 1, "META_FIT_AND_EVALUATION"),
        ("package_mlb_v19_study", "SEMANTIC_HGB", "EXECUTABLE_CANDIDATE_PACKAGING"),
    ):
        module = importlib.import_module(name)
        monkeypatch.setattr(module, "load_safe_cache", forbidden)
        if hasattr(module, "fitted"):
            monkeypatch.setattr(module, "fitted", forbidden)
        with pytest.raises(V19StudyIntegrityHold, match=HOLD_ID) as error:
            module.main(argument)
        assert stage in str(error.value)
        assert "successor study authority" in str(error.value)
