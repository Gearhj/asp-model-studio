"""Hermetic tests for MLB_CATCHER_INFLUENCE_READINESS_V1 (readiness audit only).

No model training, no dataset access, no provider calls. These prove the exact
catcher-identity reconstruction, substitution/ambiguity handling, and the
strict prior-history sample counting (a target PA is never counted in its own
history), plus the readiness decision and the honest availability inventories.
"""

import unittest

from server.sports_phase4 import catcher_readiness as cr


def _fielding(game, team, player, *, season=2024, start=True, pos="2", ordinal=100):
    return cr.FieldingAppearance(
        game_id=game, team_id=team, player_uuid=player, season=season,
        game_date="2024-05-01", final_ordinal=ordinal, position_code=pos, is_start=start,
    )


def _pa(game, team, *, pitcher, batter, pa_index, season=2024, ordinal=100, role=None):
    return cr.PlateAppearanceRow(
        game_id=game, defense_team_id=team, season=season, game_date="2024-05-01",
        game_ordinal=ordinal, pa_index=pa_index, pitcher_uuid=pitcher, batter_uuid=batter,
        pitcher_role=role,
    )


class StartingCatcherReconstructionTest(unittest.TestCase):
    def test_single_catcher_start_is_deterministic(self):
        rows = [_fielding("g1", "t1", "cat_a"), _fielding("g1", "t1", "ss_x", pos="6")]
        [tg] = cr.reconstruct_starting_catchers(rows)
        self.assertEqual(tg.status, "DETERMINISTIC")
        self.assertEqual(tg.catcher_uuid, "cat_a")

    def test_two_catcher_starts_is_ambiguous_not_silently_picked(self):
        rows = [_fielding("g1", "t1", "cat_a"), _fielding("g1", "t1", "cat_b")]
        [tg] = cr.reconstruct_starting_catchers(rows)
        self.assertEqual(tg.status, "AMBIGUOUS")
        self.assertIsNone(tg.catcher_uuid)
        self.assertEqual(tg.candidate_catchers, ("cat_a", "cat_b"))

    def test_no_catcher_start_is_missing(self):
        rows = [_fielding("g1", "t1", "ss_x", pos="6")]
        [tg] = cr.reconstruct_starting_catchers(rows)
        self.assertEqual(tg.status, "MISSING")

    def test_letter_and_numeric_catcher_codes_both_recognized(self):
        for code in ("2", "C", "c"):
            [tg] = cr.reconstruct_starting_catchers([_fielding("g", "t", "cat", pos=code)])
            self.assertEqual(tg.status, "DETERMINISTIC", code)


class PlateAppearanceAssignmentTest(unittest.TestCase):
    def _starters(self, rows):
        return {(tg.game_id, tg.team_id): tg for tg in cr.reconstruct_starting_catchers(rows)}

    def test_no_substitution_assigns_starter_to_every_pa(self):
        starters = self._starters([_fielding("g1", "t1", "cat_a")])
        pas = [_pa("g1", "t1", pitcher="p", batter="b", pa_index=i) for i in range(3)]
        assigned = cr.assign_catcher_at_plate_appearances(pas, starters)
        self.assertTrue(all(a.status == "DETERMINISTIC" and a.catcher_uuid == "cat_a" for a in assigned))

    def test_substitution_splits_assignment_by_pa_index(self):
        starters = self._starters([_fielding("g1", "t1", "cat_a")])
        subs = {("g1", "t1"): [cr.CatcherSubstitution("g1", "t1", "cat_b", event_index=5, outgoing_catcher_uuid="cat_a")]}
        pas = [_pa("g1", "t1", pitcher="p", batter="b", pa_index=i) for i in (2, 5, 8)]
        assigned = cr.assign_catcher_at_plate_appearances(pas, starters, subs)
        self.assertEqual([a.catcher_uuid for a in assigned], ["cat_a", "cat_b", "cat_b"])

    def test_contradictory_substitution_is_ambiguous_not_forward_filled(self):
        starters = self._starters([_fielding("g1", "t1", "cat_a")])
        # Outgoing catcher does not match the active catcher -> contradictory chain.
        subs = {("g1", "t1"): [cr.CatcherSubstitution("g1", "t1", "cat_c", event_index=5, outgoing_catcher_uuid="cat_z")]}
        pas = [_pa("g1", "t1", pitcher="p", batter="b", pa_index=7)]
        [assigned] = cr.assign_catcher_at_plate_appearances(pas, starters, subs)
        self.assertEqual(assigned.status, "AMBIGUOUS")
        self.assertIsNone(assigned.catcher_uuid)

    def test_ambiguous_starter_makes_pas_ambiguous(self):
        starters = self._starters([_fielding("g1", "t1", "cat_a"), _fielding("g1", "t1", "cat_b")])
        [assigned] = cr.assign_catcher_at_plate_appearances([_pa("g1", "t1", pitcher="p", batter="b", pa_index=1)], starters)
        self.assertEqual(assigned.status, "AMBIGUOUS")

    def test_missing_starter_makes_pas_missing(self):
        [assigned] = cr.assign_catcher_at_plate_appearances([_pa("g9", "t9", pitcher="p", batter="b", pa_index=1)], {})
        self.assertEqual(assigned.status, "MISSING")


class PriorHistoryNoSelfInclusionTest(unittest.TestCase):
    def test_target_pa_never_counted_in_its_own_history(self):
        # Three PAs of the same battery at strictly increasing ordinals.
        events = [("battery_A", 10), ("battery_A", 20), ("battery_A", 30)]
        dist = cr.prior_pair_sample_distribution(events)
        # Prior counts must be 0, 1, 2 (never 1, 2, 3) -> band "0" holds exactly one.
        self.assertEqual(dist["bands"]["0"]["count"], 1)
        self.assertEqual(dist["population"], 3)
        self.assertEqual(dist["maxPriorSamples"], 2)

    def test_same_ordinal_ties_excluded_from_prior(self):
        # Two PAs of the same pair in the SAME game (same ordinal): neither is prior
        # to the other (bisect_left), so both have prior count 0.
        events = [("pair", 50), ("pair", 50)]
        dist = cr.prior_pair_sample_distribution(events)
        self.assertEqual(dist["bands"]["0"]["count"], 2)
        self.assertEqual(dist["maxPriorSamples"], 0)

    def test_distinct_pairs_do_not_share_history(self):
        events = [("a", 10), ("b", 20), ("a", 30)]
        dist = cr.prior_pair_sample_distribution(events)
        self.assertEqual(dist["uniquePairs"], 2)
        # "a" at 30 sees 1 prior; "b" sees 0; "a" at 10 sees 0.
        self.assertEqual(dist["bands"]["0"]["count"], 2)
        self.assertEqual(dist["bands"]["1-9"]["count"], 1)

    def test_bands_and_percentiles_present(self):
        events = [("p", i) for i in range(1, 60)]  # 59 sequential PAs, one pair
        dist = cr.prior_pair_sample_distribution(events)
        self.assertEqual(set(dist["bands"]), set(cr.SAMPLE_SIZE_BANDS))
        self.assertIn(">=25", dist["atLeast"])
        self.assertIsNotNone(dist["medianPriorSamples"])


class FallbackLevelTest(unittest.TestCase):
    def test_levels_partition_population_monotonically(self):
        prior_counts = [0, 5, 30, 80, 300]
        dist = cr.battery_fallback_distribution(prior_counts)
        by_level = {row["level"]: row["count"] for row in dist["levels"]}
        self.assertEqual(by_level["LEVEL_0_LEAGUE_GLOBAL"], 1)
        self.assertEqual(by_level["LEVEL_1_MAIN_EFFECTS"], 1)
        self.assertEqual(by_level["LEVEL_2_CATCHER_POOLED"], 1)
        self.assertEqual(by_level["LEVEL_3_BATTERY_POOLED"], 1)
        self.assertEqual(by_level["LEVEL_4_BATTERY_SPECIFIC"], 1)
        self.assertEqual(sum(by_level.values()), len(prior_counts))


class ReadinessDecisionTest(unittest.TestCase):
    def test_ready_requires_high_coverage_and_evidence(self):
        decision = cr.decide_readiness(
            starting_catcher_coverage_rate=0.99, pa_assignment_coverage_rate=0.95,
            identity_linkage_reliable=True, battery_distribution_present=True,
            feature_inventory_present=True,
        )
        self.assertEqual(decision["status"], "CATCHER_INFLUENCE_READY_FOR_RESEARCH_DESIGN")

    def test_partial_when_pa_assignment_incomplete(self):
        decision = cr.decide_readiness(
            starting_catcher_coverage_rate=0.95, pa_assignment_coverage_rate=0.60,
            identity_linkage_reliable=True, battery_distribution_present=True,
            feature_inventory_present=True,
        )
        self.assertEqual(decision["status"], "CATCHER_INFLUENCE_PARTIALLY_READY")

    def test_blocked_when_linkage_unreliable(self):
        decision = cr.decide_readiness(
            starting_catcher_coverage_rate=0.99, pa_assignment_coverage_rate=0.95,
            identity_linkage_reliable=False, battery_distribution_present=True,
            feature_inventory_present=True,
        )
        self.assertEqual(decision["status"], "CATCHER_INFLUENCE_DATA_AUDIT_BLOCKED")

    def test_all_terminal_statuses_are_governed(self):
        for rate_start, rate_pa, link in ((0.99, 0.95, True), (0.9, 0.6, True), (0.1, 0.1, False)):
            decision = cr.decide_readiness(
                starting_catcher_coverage_rate=rate_start, pa_assignment_coverage_rate=rate_pa,
                identity_linkage_reliable=link, battery_distribution_present=True,
                feature_inventory_present=True,
            )
            self.assertIn(decision["status"], cr.TERMINAL_STATUSES)


class InventoryAndPayloadTest(unittest.TestCase):
    def test_free_inventory_uses_governed_labels_only(self):
        allowed = {"AVAILABLE", "DERIVABLE", "PARTIALLY_AVAILABLE", "UNRELIABLE", "UNAVAILABLE"}
        self.assertTrue(all(item["label"] in allowed for item in cr.free_feature_inventory()))

    def test_premium_gaps_never_claim_availability(self):
        allowed = {"PREMIUM_TRACKING_LIKELY_REQUIRED", "NEW_DATA_SOURCE_REQUIRED", "CURRENTLY_UNAVAILABLE"}
        gaps = cr.premium_gap_inventory()
        self.assertTrue(all(g["classification"] in allowed for g in gaps))
        fields = {g["field"] for g in gaps}
        for required in ("catcher_framing", "catcher_pitch_selection_caller_identity", "abs_challenge_decision"):
            self.assertIn(required, fields)

    def test_audit_payload_has_no_fabricated_model_metrics(self):
        audit = cr.CatcherReadinessAudit(
            dataset_authority={"registrationId": "r"}, identity_bridge_authority={"registrationId": "b"},
            seasons=[2023, 2024, 2025], starting_catcher_coverage={}, pa_assignment_coverage={},
            battery_distribution={"population": 0}, battery_fallback={"levels": []},
            catcher_batter_distribution={"population": 0}, feature_inventory=cr.free_feature_inventory(),
            premium_gaps=cr.premium_gap_inventory(),
            decision={"status": "CATCHER_INFLUENCE_PARTIALLY_READY"},
            limitations=cr.DEFAULT_LIMITATIONS,
        )
        payload = audit.to_registry_payload(run_id="run_x", contract_sha="0" * 64)
        text = repr(payload).lower()
        # No fabricated *performance* metrics. (The design note legitimately states
        # "no coefficients estimated", so we scan for metric names, not that word.)
        for forbidden in ("logloss", "log_loss", "brier", "accuracy", "auc", "roc", "ece", "f1"):
            self.assertNotIn(forbidden, text)
        self.assertEqual(payload["terminalStatus"], "CATCHER_INFLUENCE_PARTIALLY_READY")
        self.assertEqual(payload["contractName"], "MLB_CATCHER_INFLUENCE_READINESS_V1")
        self.assertEqual(payload["futureModelDesign"]["status"], "DESIGN_ONLY_NOT_IMPLEMENTED")

    def test_future_design_estimates_nothing(self):
        design = cr.future_model_design()
        self.assertEqual([m["id"] for m in design["ablation"]], ["M0", "M1", "M2", "M3", "M4", "M5"])


class NoFuzzyNameJoinTest(unittest.TestCase):
    def test_input_contract_has_no_name_fields(self):
        # Identity is exact-canonical only: none of the normalized inputs carry a
        # player *name* field that could invite fuzzy matching.
        for dc in (cr.FieldingAppearance, cr.PlateAppearanceRow, cr.CatcherSubstitution):
            annotations = {name.lower() for name in getattr(dc, "__annotations__", {})}
            self.assertFalse(any("name" in a for a in annotations), dc.__name__)


if __name__ == "__main__":
    unittest.main()
