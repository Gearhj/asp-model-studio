"""Phase 7D.5A (Workstream H) — the ordinary champion-reference path never opens the combined final2025 artifact.

Proves the ordinary path reads only a 2024-only source, the migration derives a 2024-only reference with no 2025
value, and no 2025 metric is exposed. Hermetic (temp runtime for the migration); never opens real sealed 2025.
"""
from __future__ import annotations

import inspect
import json

import server.sports_cockpit.engine as E
from scripts import migrate_champion_2024_reference as MIG


def test_champion_reference_source_does_not_reference_the_combined_artifact():
    src = inspect.getsource(E._champion_reference)
    assert "experiment-metrics" not in src, "ordinary champion reference must not read the combined final2025 artifact"
    assert "final2025" not in src


def test_champion_reference_never_globs_the_combined_artifact(monkeypatch):
    opened = []
    orig = E.glob.glob

    def guarded(pattern, *a, **k):
        if "experiment-metrics" in str(pattern):
            opened.append(str(pattern))
        return orig(pattern, *a, **k)

    monkeypatch.setattr(E.glob, "glob", guarded)
    ref = E._champion_reference()
    assert opened == [], f"ordinary path opened the combined artifact: {opened}"
    assert ref["val2024"]["logLoss"] is not None
    assert "2025" not in json.dumps(ref["val2024"])           # no 2025 value in the exposed reference
    assert ref["sealed2025"] == "RESTRICTED_ARCHIVAL_AUDIT_EVIDENCE"


def test_migration_produces_a_2024_only_reference(tmp_path):
    # a hermetic combined artifact carrying BOTH a 2024 value and a sealed final2025 section
    obj = tmp_path / "sports-modeling" / "mlb-pa-v1" / "objects" / "sha256" / "deadbeef"
    obj.mkdir(parents=True)
    combined = {"payload": {"candidates": [{"candidateId": "C4", "aggregateMetrics": {
        "validation2024": {"logLoss": 1.2345, "brierScore": 0.5, "topLabelEce": 0.01},
        "final2025": {"logLoss": 9.9999, "brierScore": 0.9}}}]}}
    (obj / "experiment-metrics.json").write_text(json.dumps(combined), encoding="utf-8")

    out = MIG.migrate(tmp_path)
    assert out["val2024"] == {"logLoss": 1.2345, "brierScore": 0.5, "topLabelEce": 0.01}
    ref = json.loads((tmp_path / "sports-modeling" / "champion-2024-reference" / f"reference-sha256-{out['referenceSha256']}.json").read_text())
    assert ref["schemaVersion"] == "MLB_CHAMPION_2024_REFERENCE_V1"
    assert "2025" not in json.dumps(ref) and "final2025" not in json.dumps(ref)   # no 2025 leaked
    assert "9.9999" not in json.dumps(ref)                    # the sealed 2025 value never entered
    # idempotent: a second run is a byte no-op
    out2 = MIG.migrate(tmp_path)
    assert out2["referenceSha256"] == out["referenceSha256"]
