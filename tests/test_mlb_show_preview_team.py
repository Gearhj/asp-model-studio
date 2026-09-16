"""Focused chronology and isolated synthetic exchange tests; no real publication."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import unittest
import uuid

import joblib
import numpy as np
from server.sports_shared import show_preview as p
from server.sports_shared import mlb_show_preview_team as m

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/mlb-show-preview-feasibility-v1"


class MLBPreviewTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / "outputs/show-preview-focused-tests" / ("mlb-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.now = p.utc("2026-09-16T19:15:00Z")
        self.rows = [{"id": "synthetic-history-"+str(i), "date": day, "completion_date": day,
                      "season": int(day[:4]), "away": "A", "home": "H", "away_score": 3+i%4,
                      "home_score": 4+i%3, "completedAtUtc": day+"T23:00:00Z",
                      "capturedAtUtc": "2026-09-16T18:00:00Z"}
                     for i, day in enumerate(("2024-07-01", "2025-07-01", "2026-09-10", "2026-09-11"))]
        self.target = {"id": "synthetic-target", "date": "2026-09-17", "season": 2026, "away": "A", "home": "H"}

    def test_previous_day_target_future_and_suspended_excluded(self):
        x, _ = m.feature_matrix(self.rows, [self.target])
        for day, completion in (("2026-09-16", "2026-09-16"), ("2026-09-17", "2026-09-17"),
                                ("2026-09-18", "2026-09-18"), ("2026-09-01", "2026-09-20")):
            row = {**self.rows[0], "id": "later", "date": day, "completion_date": completion,
                   "season": 2026, "home_score": 1000}
            after, _ = m.feature_matrix(self.rows+[row], [self.target])
            np.testing.assert_array_equal(x, after)
        # Retained previous-day afternoon games are deliberately excluded too.
        self.assertEqual(p.clocks("2026-11-03")["publish_by_utc"], "2026-11-02T21:00:00Z")

    def test_league_prior_fallback_and_no_invented_history(self):
        target = {**self.target, "away": "UNKNOWN"}
        x, audit = m.feature_matrix(self.rows, [target])
        self.assertTrue(np.isfinite(x).all())
        self.assertEqual(audit[0]["currentSeasonSupport"][0], 0)
        with self.assertRaises(ValueError):
            m.feature_matrix([], [target])

    def packet(self):
        game = {"canonical_game_id": None, "source_game_ref": "synthetic:mlb:only", "slate_date": "2026-09-17",
                "kickoff_utc": "2026-09-17T23:00:00Z", "away": {"abbreviation": "A", "name": "Synthetic Away"},
                "home": {"abbreviation": "H", "name": "Synthetic Home"}}
        evidence = {"schema": "MLB_TEAM_PREVIEW_CURRENT_INPUTS_V1", "syntheticFixtureOnly": True,
            "inputAvailabilityCertified": True, "lineupStatus": "UNKNOWN", "starterStatus": "UNKNOWN",
            "missingEvidence": ["LINEUPS_UNKNOWN", "STARTERS_UNKNOWN"], "game": game,
            "sourceCutoffUtc": "2026-09-16T18:00:00Z", "history": self.rows,
            "historyComplete": True, "priorSeasonComplete": True, "protectedPayloadsUsed": False,
            "awayRetrosheetCode": "A", "homeRetrosheetCode": "H"}
        raw = self.root / "synthetic-history.json"
        p.immutable(raw, p.canonical({"syntheticFixtureOnly": True, "rows": self.rows}))
        evidence["sourceFiles"] = [p.physical(raw)]
        admission = self.root / "synthetic-admission.json"
        p.immutable(admission, p.canonical({"syntheticFixtureOnly": True, "protectedPayloadsUsed": False, "eligibleForPreviewFeatures": True}))
        owner = {k:evidence[k] for k in ("history", "historyComplete", "priorSeasonComplete", "sourceCutoffUtc", "game", "sourceFiles", "awayRetrosheetCode", "homeRetrosheetCode")}
        owner.update(schema="MLB_TEAM_PREVIEW_ADMITTED_HISTORY_V1", use="CURRENT_PREVIEW_FEATURE_CONSTRUCTION_ONLY", admissionReceipt=p.physical(admission))
        path = self.root / "synthetic-owner.json"
        p.immutable(path, p.canonical(owner))
        evidence["ownerExport"] = p.physical(path)
        path = self.root / "synthetic-inputs.json"
        p.immutable(path, p.canonical(evidence))
        return path, evidence

    def test_current_input_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "CURRENT_TEAM_HISTORY"):
            m.require_current_inputs({}, self.now)
        _, e = self.packet()
        for key, value in (("lineupStatus", "CONFIRMED"), ("historyComplete", False),
                           ("protectedPayloadsUsed", True), ("inputAvailabilityCertified", False)):
            bad = deepcopy(e); bad[key] = value
            with self.assertRaises(ValueError): m.require_current_inputs(bad, self.now)
        with self.assertRaisesRegex(ValueError, "DEADLINE"):
            m.require_current_inputs(e, "2026-09-16T20:00:01Z")
        bad = deepcopy(e)
        bad["history"][0]["completedAtUtc"] = None
        with self.assertRaisesRegex(ValueError, "FINAL_COMPLETION"):
            m.require_current_inputs(bad, self.now)
        bad = deepcopy(e);bad["awayRetrosheetCode"] = "UNBOUND_TEAM"
        with self.assertRaisesRegex(ValueError, "owner export differs"):
            m.require_current_inputs(bad, self.now)
        bad = deepcopy(e);bad["history"].append(bad["history"][0])
        with self.assertRaisesRegex(ValueError, "DUPLICATE_HISTORY"):
            m.require_current_inputs(bad, self.now)

    def test_real_fitted_model_isolated_contract_publication_replay(self):
        input_path, _ = self.packet()
        source = m.point_source(input_path, OUT / "model-trained-through-2023.joblib", OUT / "ASSESSMENT.json", self.root, self.now)
        before = source.read_bytes()
        repeated = m.point_source(input_path, OUT / "model-trained-through-2023.joblib", OUT / "ASSESSMENT.json", self.root, "2026-09-16T19:16:00Z")
        self.assertEqual(source, repeated)
        self.assertEqual(before, repeated.read_bytes())
        bound = m.preview_source(source)
        validator = p.consumer_validator(ROOT / "outputs/multisport-show-preview-producer-v1/context/consumer-contract.py",
             "1a6771cb0fbf7c41cdc1e05e09141a7a4db513b82a7993399aec64fc6ea9f275")
        result = p.publish([bound], self.root, validator, now_fn=lambda:self.now)
        discovery = Path(result["discovery"]["path"]).read_bytes()
        again = p.publish([bound], self.root, validator, now_fn=lambda:self.now)
        self.assertEqual(again["results"][0]["disposition"], "REUSED_BYTE_IDENTICAL")
        self.assertEqual(discovery, Path(result["discovery"]["path"]).read_bytes())
        doc = p.verify_package(self.root / p.TREE / result["results"][0]["package_path"], validator, self.now)
        self.assertEqual(doc["horizon"], "SHOW_PREVIEW")
        self.assertEqual(doc["simulation"]["draw_count"], 0)
        self.assertIsNone(doc["distribution"])
        self.assertAlmostEqual(sum(doc["probabilities"].values()), 1)
        tampered = json.loads(before);tampered["probabilities"]["home_win"] += .01
        with self.assertRaises(ValueError): m.verify_point_source(tampered)

    def test_retained_validation_numerical_reproduction(self):
        features = json.loads((OUT / "feature-audit.json").read_bytes())
        pred = json.loads((OUT / "predictions.json").read_bytes())
        selected = [(i, a) for i,a in enumerate(features["audits"]) if a["gameId"][3:7] == "2024"]
        model = joblib.load(OUT / "model-trained-through-2023.joblib")
        actual = m.predict(model["models"], np.array([features["values"][i] for i,a in selected]))
        by_id = {r["gameId"]:r["candidate"] for r in pred if r["season"] == 2024}
        expected = np.array([[by_id[a["gameId"]][k] for k in ("pHome", "expectedAway", "expectedHome")] for i,a in selected])
        np.testing.assert_array_equal(actual, expected)


if __name__ == "__main__": unittest.main()
