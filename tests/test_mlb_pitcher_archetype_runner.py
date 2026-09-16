"""Focused checks for the new experiment's identity and receipt boundaries."""
import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import run_mlb_pitcher_archetype_survival as runner


def example():
    identity = pd.DataFrame([{"startId": "start-1", "gameId": "game-1", "pitcherId": "pitcher-1",
                              "gameDate": "2024-05-10", "eligible": True}])
    row = {**identity.iloc[0].to_dict(), **dict.fromkeys(runner.STYLE_FEATURES, np.nan),
           "profileSupported": True, "profilePitchCount": 300, "profilePriorDateCount": 4,
           "profileLatestGameDate": "2024-05-08", "style_throws_left": 1.0}
    row.update({f"style_{g}_usage": float(g == "FF") for g in runner.GROUPS})
    return identity, pd.DataFrame([row])


def test_profile_identity_and_cutoff_are_checked_before_training():
    identity, profile = example()
    runner.validate_profiles(profile, identity)
    for field, wrong in (("pitcherId", "different-pitcher"), ("gameId", "different-game"),
                         ("gameDate", "2024-05-11")):
        bad = profile.copy()
        bad[field] = wrong
        with pytest.raises(ValueError, match="BINDING_CHANGED"):
            runner.validate_profiles(bad, identity)
    bad = profile.copy()
    bad["profileLatestGameDate"] = "2024-05-10"
    with pytest.raises(ValueError, match="CUTOFF_OR_SUPPORT_FAILED"):
        runner.validate_profiles(bad, identity)


def test_profile_support_and_mass_cannot_be_replaced_by_imputation():
    identity, profile = example()
    bad = profile.copy()
    bad["profilePitchCount"] = 199
    with pytest.raises(ValueError, match="CUTOFF_OR_SUPPORT_FAILED"):
        runner.validate_profiles(bad, identity)
    bad = profile.copy()
    bad["style_FF_usage"] = .9
    with pytest.raises(ValueError, match="USAGE_MASS_CHANGED"):
        runner.validate_profiles(bad, identity)


def test_changed_cached_code_or_declaration_fails_closed(monkeypatch):
    # The new behavior is descriptor comparison. Existing reference() handles
    # physical hashing; keep this test entirely in memory under Windows ACLs.
    root = Path("fixture-archetype-cache").resolve()
    paths = [root / (name + ".py") for name in ("runner", "builder", "model")]
    current = {str(p): {"path": str(p), "sha256": "1" * 64, "bytes": 16}
               for p in paths + [root / "declaration.json"]}
    monkeypatch.setattr(runner, "reference", lambda p: dict(current[str(p)]))
    monkeypatch.setattr(runner, "CODE", paths)
    refs = [runner.reference(path) for path in paths]
    runner.verify_code(refs, stage="fit")
    current[str(paths[2])]["sha256"] = "2" * 64
    with pytest.raises(ValueError, match="CODE_CHANGED_REVIEW_REQUIRED"):
        runner.verify_code(refs, stage="fit")
    # Unused model-code changes do not invalidate the profile builder bytes.
    runner.verify_code(refs, stage="profiles")
    monkeypatch.setattr(runner, "OUT", root)
    record = {"schemaVersion": "FIXTURE", "declaration": runner.reference(root / "declaration.json")}
    runner.require_declaration(record, "FIXTURE")
    wrong = copy.deepcopy(record)
    wrong["declaration"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="DECLARATION_OR_SCHEMA_CHANGED"):
        runner.require_declaration(wrong, "FIXTURE")
