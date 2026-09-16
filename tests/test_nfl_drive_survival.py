import unittest
from unittest.mock import Mock
import numpy as np
import pandas as pd
from server.sports_nfl_m1.drive_survival import (CAUSES,FEATURES,features,fit_hazard,
    historical_cause,SurvivalAdapter,sample_cause,legal_state,reconstruct,READ_COLUMNS,drive_rollout)
from server.sports_nfl_m1.play_engine import apply_play,assert_state

def state(**kw):
    s=dict(phase='SCRIMMAGE',season=2024,quarter=1,quarter_seconds=800.,half_seconds=1700.,
           down=1,yards_to_go=10.,yardline_100=60.,score_differential=0.,home=1,
           drive_start_yard=60.,prior_snaps=0,elapsed=0.,recent_pass_fraction=0.,
           offense_team='A',defense_team='B')
    s.update(kw);return s

def donor(**kw):
    s=dict(type='RUSH',seconds=20.,yards=4.,air_yards=None,return_yards=0.,fumble=False,
           fumble_lost=False,kick_success=None,touchback=False)
    s.update(kw);return s

class Boundaries(unittest.TestCase):
    def test_midpoint_uses_exact_preceding_play_types(self):
        class Base:
            def sample(self,s,rng,scenario='BASE'):return donor()
        h=Mock();h.supported.return_value=False
        m=SurvivalAdapter(Base(),h,home_team='A')
        s=state(quarter=2,quarter_seconds=10,half_seconds=10,prior_snaps=3,
                recent_pass_fraction=1/3,home_team='A',away_team='B')
        with self.assertRaises(ValueError):drive_rollout(m,s,1)
        s['recent_pass_flags']=[1,0,0]
        out=drive_rollout(m,s,1)
        self.assertEqual(out['cause'],8)
        self.assertEqual(m._last['history'][-3:],[0,0,False])

    def test_independent_proper_score_examples(self):
        from scripts.run_nfl_drive_survival_v1 import crps,game_metrics
        self.assertAlmostEqual(crps([0,2],1),.5)
        m=game_metrics([[3,0],[0,3]],3,0)
        self.assertAlmostEqual(m['energy'],np.sqrt(18)/4)
        self.assertAlmostEqual(m['brier'],.5)
        self.assertAlmostEqual(m['marginCrps'],1.5)
        self.assertEqual(m['totalCrps'],0.)

    def test_source_order_score_and_endpoint_censoring(self):
        common={k:None for k in READ_COLUMNS}
        common.update(season=2020,game_id='2020_01_A_B',game_date='2020-09-01',week=1,season_type='REG',
            home_team='B',away_team='A',home_score=3,away_score=0,posteam='B',defteam='A',
            fixed_drive=1.,drive_end_transition='FIELD_GOAL',drive_game_clock_end='09:55',
            drive_play_id_started=3.,drive_play_id_ended=2.,qtr=1.,down=3.,ydstogo=5.,
            yardline_100=20.,quarter_seconds_remaining=600.,half_seconds_remaining=1500.,
            score_differential=0.,play_deleted=0.,total_home_score=0.,total_away_score=0.,
            desc='',incomplete_pass=1.,play_type='pass',play_id=3.,order_sequence=1.)
        field=dict(common,play_id=2.,order_sequence=2.,down=4.,field_goal_attempt=1.,
             incomplete_pass=0.,play_type='field_goal',field_goal_result='made',
             total_home_score=3.,quarter_seconds_remaining=597.,half_seconds_remaining=1497.)
        r,d,g,a=reconstruct(pd.DataFrame([field,common]))
        self.assertTrue(g.score_reconciled.all());self.assertEqual(r.play_id.tolist(),[3.,2.])
        self.assertEqual(r.cause.tolist(),[0,2]);self.assertTrue(d.eligible.all())
        bad=dict(common,drive_play_id_started=999.);badfield=dict(field,drive_play_id_started=999.)
        r,d,_,_=reconstruct(pd.DataFrame([bad,badfield]))
        self.assertEqual(len(r),0);self.assertEqual(d.exclusion.iloc[0],'TRUNCATED_DRIVE_ENDPOINT_NOT_RETAINED')

    def test_target_exclusion(self):
        s=state();x=features(s)
        s.update(final_score=99,final_cause=1,drive_points=70,drive_length=2,next_yard=0)
        np.testing.assert_array_equal(x,features(s));self.assertEqual(len(x),len(FEATURES))

    def test_chronology_and_fold_local_scaling(self):
        data=[]
        for i in range(120):
            data.append(dict(**state(season=2020,yardline_100=20+i%60),cause=i%len(CAUSES)))
        f=pd.DataFrame(data);h=fit_hazard(f,2020)
        np.testing.assert_allclose(h.scaler.mean_,np.stack([features(s) for s in data]).mean(0))
        self.assertFalse(h.supported(state(season=2020)))
        with self.assertRaises(ValueError):fit_hazard(f,2019)
        with self.assertRaises(ValueError):fit_hazard(f.assign(season=2026),2026)
        p=h.predict(data[0]);self.assertAlmostEqual(p.sum(),1);self.assertTrue((p>=0).all())

    def test_exclusive_causes(self):
        self.assertEqual(historical_cause(dict(interception=1,touchdown=1,posteam='A',td_team='B')),5)
        self.assertEqual(historical_cause(dict(touchdown=1,posteam='A',td_team='A')),1)
        self.assertEqual(historical_cause(dict(field_goal_attempt=1,field_goal_result='blocked')),3)
        self.assertEqual(historical_cause(dict(fourth_down_failed=1)),6)

    def test_no_play_and_clock_end(self):
        s=state(quarter=2,quarter_seconds=1,half_seconds=1)
        self.assertEqual(sample_cause(s,donor()),8)
        self.assertEqual(sample_cause(state(quarter=1,quarter_seconds=1,half_seconds=901),donor()),0)
        pen=donor(type='PENALTY',penalty=dict(no_play=True,offense=True,yards=5))
        a,o=apply_play(legal_state(s),pen,season=2024)
        self.assertEqual(o['seconds'],0);self.assertEqual(a['down'],1)
        assert_state(a)

    def test_exact_fallback_rng(self):
        class Base:
            def sample(self,s,rng,scenario='BASE'):return donor(yards=int(rng.integers(9)))
        b=Base();h=Mock();h.supported.return_value=False
        for weight in (0,.25):
            c=SurvivalAdapter(b,h,weight=weight,home_team='A')
            r1=np.random.default_rng(41);r2=np.random.default_rng(41)
            self.assertEqual(b.sample(state(),r1),c.sample(state(),r2))
            self.assertEqual(r1.random(),r2.random())

    def test_projected_selection_is_original_legal_donor(self):
        class Base:
            def sample(self,s,rng,scenario='BASE'):return donor(yards=int(rng.choice([0,4,70])))
        h=Mock();h.supported.return_value=True;h.predict.return_value=np.ones(len(CAUSES))/len(CAUSES)
        c=SurvivalAdapter(Base(),h,weight=1,home_team='A')
        vals=[]
        for seed in range(30):
            c.reset();d=c.sample(state(),np.random.default_rng(seed));vals.append(d)
            self.assertIn(d['yards'],[0,4,70]);a,o=apply_play(legal_state(state()),d,season=2024);assert_state(a)
        c.reset();self.assertEqual(vals[0],c.sample(state(),np.random.default_rng(0)))

if __name__=='__main__':unittest.main()
