"""Focused synthetic mechanics checks; these are not forecasting evidence."""
import unittest
import numpy as np
from server.sports_shared import mlb_matchup_shrinkage as m


def game(gid, day, completion=None, away="A", home="H", a=3, h=4):
    return {"id":gid,"date":day,"completion_date":completion or day,"season":2023,
            "away":away,"home":home,"away_score":a,"home_score":h}


class MatchupTest(unittest.TestCase):
    def setUp(self):
        self.config = {"window":4,"halfLifeDays":180,"priorStrength":32,"minimumCount":2,"sameParkOnlyWeight":.5}
        self.base = np.array([[.6,4.2,4.7]])

    def test_excludes_target_prior_day_late_completion_and_future(self):
        target=game("t","2023-06-10")
        rows=[game("ok","2023-06-08"),game("prior","2023-06-09"),
              game("suspended","2023-06-01","2023-06-09"),target,game("future","2023-06-11")]
        pool=m.donor_pools(rows,[target],{r["id"]:"P" for r in rows})[0]
        self.assertEqual(pool["ids"],["ok"])

    def test_orientation_survives_reversed_venue(self):
        target=game("t","2023-06-10")
        donor=game("d","2023-06-01",away="H",home="A",a=9,h=1)
        pool=m.donor_pools([donor,target],[target],{"d":"Q","t":"P"})[0]
        np.testing.assert_array_equal(pool["runs"],[[1,9]])

    def test_insufficient_history_is_exact_fallback(self):
        t=game("t","2023-06-10")
        pools=m.donor_pools([t],[t],{"t":"P"})
        out,audit=m.h2h_forecast(self.base,pools,self.config)
        self.assertEqual(out.tobytes(),self.base.tobytes())
        self.assertFalse(audit[0]["supported"])

    def test_shrinkage_probability_identity_and_replay(self):
        target=game("t","2023-06-10")
        rows=[game("d1","2023-06-01",a=1,h=2),game("d2","2023-06-02",a=3,h=4),target]
        pools=m.donor_pools(rows,[target],{r["id"]:"P" for r in rows})
        out,a=m.h2h_forecast(self.base,pools,self.config)
        again,b=m.h2h_forecast(self.base,pools,self.config)
        self.assertEqual(out.tobytes(),again.tobytes())
        self.assertEqual(a,b)
        self.assertEqual(out[0,0],self.base[0,0])
        self.assertAlmostEqual(out[0,0]+(1-out[0,0]),1)
        self.assertTrue(all(0 < w < .5 for w in a[0]["weights"]))
        self.assertTrue(np.all(out[0,1:] <= self.base[0,1:]))

    def test_more_uncertain_donors_receive_less_weight(self):
        pools=[{"ids":["a","b"],"completionDates":["2023-06-01"]*2,"ages":np.array([3,3]),
                "samePark":np.array([True,True]),"runs":np.array([[4.,0.],[4.,8.]])}]
        _,audit=m.h2h_forecast(self.base,pools,self.config)
        self.assertGreater(audit[0]["weights"][0],audit[0]["weights"][1])

    def test_actual_starter_cannot_bypass_admission(self):
        target=game("t","2023-06-10")
        out,audit=m.starter_forecast(self.base,[target])
        self.assertEqual(out.tobytes(),self.base.tobytes())
        self.assertFalse(audit[0]["supported"])
        with self.assertRaisesRegex(ValueError,"NO_DEVELOPMENT"):
            m.starter_forecast(self.base,[target],bindings={"actualStarter":"hindsight"})

    def test_count_score_zero_and_no_invented_distributions(self):
        r=game("t","2023-06-10",a=0,h=4)
        f=np.array([[.6,2.,4.]])
        result=m.metrics([r],f)
        self.assertAlmostEqual(result["poissonDeviance"],2.)
        self.assertIsNone(result["crps"])
        self.assertIsNone(result["intervalCoverage50_80_90"])

    def test_protected_season_rejected_before_load(self):
        with self.assertRaisesRegex(ValueError,"registered historical"):
            m.load_anchor([2026])

    def test_fixed_tail_membership(self):
        r=[game("a","2023-06-10"),game("b","2023-06-11")]
        baseline=np.array([[.6,6.,6.],[.6,3.,3.]])
        candidate=np.array([[.6,3.,3.],[.6,6.,6.]])
        thresholds={"riskBin":[9,10],"team90":5.,"total90":10.}
        result=m.slices(r,candidate,thresholds,reference_forecasts=baseline)
        self.assertEqual(result["upperTotalDecile"]["expectedAway"],3.)


if __name__ == "__main__":
    unittest.main()
