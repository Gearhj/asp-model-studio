"""Small independent numerical identities; no live forecasts or outcomes."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_mlb_v18_distribution_diagnosis import crps,energy,pit_fraction,logit_fit

class Diagnostics(unittest.TestCase):
    def test_crps_matches_pairwise_definition(self):
        for x,y in [([0,0,1,4],2),([2,2,2],2),([0,1,1,5],8)]:
            a=np.array(x)
            expected=np.abs(a-y).mean()-.5*np.abs(a[:,None]-a[None,:]).mean()
            self.assertAlmostEqual(crps(x,y),expected)
    def test_energy_preserves_pairing_and_duplicate_mass(self):
        x=np.array([[0,1],[0,1],[3,2],[4,8]],dtype=float);y=np.array([2,3])
        brute=np.linalg.norm(x-y,axis=1).mean()-.5*np.linalg.norm(x[:,None,:]-x[None,:,:],axis=2).mean()
        self.assertAlmostEqual(energy(x,y),brute)
    def test_discrete_pit_interval_mass(self):
        np.testing.assert_allclose(pit_fraction(.15,.35),[0,.25,.5,.25,0,0,0,0,0,0])
        self.assertAlmostEqual(pit_fraction(1,1)[-1],1)
        np.testing.assert_allclose(pit_fraction(0,1),np.full(10,.1))
    def test_diagnostic_logit_stationary_solution(self):
        p=np.array([.2,.2,.4,.4,.6,.6,.8,.8]);y=np.array([0,1,0,1,0,1,0,1])
        fit=logit_fit(p,y)
        np.testing.assert_allclose(fit,[0,0],atol=1e-4)

if __name__=='__main__':unittest.main()
