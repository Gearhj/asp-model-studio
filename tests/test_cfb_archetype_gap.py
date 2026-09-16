from copy import deepcopy
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from server.sports_cfb_gen1 import archetype_gap as ag
from server.sports_cfb_gen1.pipeline import build_features, empirical_crps, simulate_paired_residuals

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs/cfb-gen1-v1"


class ArchetypeGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = pd.read_parquet(BASE / "data/season-forward-predictions.parquet", filters=[("season", "<=", 2021)])
        cls.target = cls.p[cls.p.season.eq(2021)].iloc[0].copy()
        cls.donors = ag.eligible_donors(cls.p, cls.target)

    def test_donors_exclude_same_season_future_and_target(self):
        donors = ag.eligible_donors(self.p, self.target)
        self.assertLess(donors.season.max(), self.target.season)
        self.assertNotIn(self.target.game_id, set(donors.game_id))
        with self.assertRaises(ValueError):
            later = self.target.copy(); later.season = 2026
            ag.eligible_donors(self.p, later)
        with self.assertRaises(ValueError):
            ag.fit_gap(self.p[self.p.season.eq(2021)], 2021)

    def test_target_outcome_does_not_enter_target_features(self):
        games = pd.read_parquet(BASE / "data/admitted-games.parquet", filters=[("season", "==", 2014)]).head(180)
        cutoff = games.scheduled_at.sort_values().iloc[100]
        first = build_features(games)
        changed = games.copy()
        for name in ["home_score", "away_score", "home_margin", "total_points", "home_total_yards", "away_total_yards", "home_turnovers", "away_turnovers"]:
            changed.loc[changed.scheduled_at >= cutoff, name] = 999.
        second = build_features(changed)
        cols = [c for c in first if c.startswith("elo_") or c.endswith("_season") or c.endswith("_trailing5")]
        a = first.loc[first.scheduled_at <= cutoff].set_index("game_id")[cols]
        b = second.loc[second.scheduled_at <= cutoff].set_index("game_id")[cols]
        pd.testing.assert_frame_equal(a,b)

    def test_cluster_input_excludes_identifiers_outcomes_and_context_labels(self):
        frame = self.p.head(200).copy()
        before = ag.team_states(frame, "home")
        for col in ("game_id", "home_id", "away_id", "home_score", "away_score", "home_margin", "home_win", "conference_competition"):
            frame[col] = 987654
        pd.testing.assert_frame_equal(before, ag.team_states(frame,"home"))
        self.assertEqual(list(before.columns), ag.TEAM_VARIABLES)

    def test_fold_local_scaling_and_deterministic_assignment(self):
        states = ag.team_states(self.p[self.p.season.lt(2018)],"home")
        one = ag._fit_kmeans(states,2,ag.SEED)
        two = ag._fit_kmeans(states,2,ag.SEED)
        np.testing.assert_array_equal(one.predict(states),two.predict(states))
        np.testing.assert_allclose(one.named_steps["scale"].mean_, states.mean().to_numpy())
        future = states.copy()+10000
        expected = one.named_steps["scale"].mean_.copy()
        one.predict(future)
        np.testing.assert_array_equal(expected,one.named_steps["scale"].mean_)

    def test_exact_fallback_and_non_tied_probability_mass(self):
        base,_=simulate_paired_residuals(self.target,self.donors,ag.MODEL,draw_count=512)
        gap=ag.fit_gap(self.p[self.p.season.lt(2021)],2021)
        gap["supported"]=False
        challenger,info=ag.candidate_draws(self.target,self.donors,base,gap=gap,draw_count=512)
        self.assertFalse(info["applied"])
        pd.testing.assert_frame_equal(base,challenger)
        self.assertEqual(ag.draw_hash(base),ag.draw_hash(challenger))
        self.assertFalse((challenger.home_score==challenger.away_score).any())
        over=(challenger.total>55).mean();under=(challenger.total<55).mean();push=(challenger.total==55).mean()
        self.assertEqual(over+under+push,1.)

    def test_gap_transform_preserves_raw_total_and_means(self):
        r=ag.raw_residuals(self.donors)
        m=r[:,0]-r[:,1];correction=.2*(m-m.mean())
        altered=r+np.column_stack([correction/2,-correction/2])
        np.testing.assert_allclose(altered.sum(axis=1),r.sum(axis=1),atol=1e-12,rtol=0)
        np.testing.assert_allclose(altered.mean(axis=0),r.mean(axis=0),atol=1e-12,rtol=0)
        base,_=simulate_paired_residuals(self.target,self.donors,ag.MODEL,draw_count=512)
        gap=ag.fit_gap(self.p[self.p.season.lt(2021)],2021);gap.update(supported=True,marginScale=1.2)
        one,_=ag.candidate_draws(self.target,self.donors,base,gap=gap,draw_count=512)
        two,_=ag.candidate_draws(self.target,self.donors,base,gap=gap,draw_count=512)
        pd.testing.assert_frame_equal(one,two)
        future=deepcopy(gap);future["trainingLatestKickoff"]=self.target.scheduled_at.isoformat()
        with self.assertRaises(ValueError):ag.candidate_draws(self.target,self.donors,base,gap=future,draw_count=512)

    def test_independent_crps_and_brier_conventions(self):
        x=np.array([0.,7.,14.,21.]);y=10.
        brute=np.abs(x-y).mean()-.5*np.abs(x[:,None]-x[None,:]).mean()
        self.assertAlmostEqual(empirical_crps(x,y),brute)
        metrics=ag.probability_metrics(np.array([1.,0.]),np.array([.6,.4]))
        self.assertAlmostEqual(metrics["brier"],.16)


if __name__=="__main__":
    unittest.main()
