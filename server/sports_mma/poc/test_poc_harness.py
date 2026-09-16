from __future__ import annotations
import unittest
from dataclasses import replace
import json
from pathlib import Path

from .adapters import (LiveGate, build_plan, normalize_api_sports_synthetic,
                       normalize_odds_synthetic, synthetic_capture)
from .harness import (AppendOnlyLedger, BudgetError, BudgetGuard, ValidationError,
                      require_pipeline_sport, validate_bundle, validate_latency, validate_schema)
from .models import (BoutVersion, Capture, EvidenceBundle, EventVersion, Fighter,
                     OddsSnapshot, ResultRevision, digest, schema_fingerprint)

T0="2026-09-18T16:00:00Z"; NOW="2026-09-20T16:00:00Z"; HEX="a"*64

def bundle()->EvidenceBundle:
    capture=Capture("cap-1","MMA","SYNTHETIC","fixture://card","2026-09-18T15:55:00Z",HEX,123,HEX)
    fighters=[Fighter("f-1","MMA","Alpha Fighter",{"synthetic":"sf-1"},("Alpha",)),Fighter("f-2","MMA","Beta Fighter",{"synthetic":"sf-2"},("Beta",))]
    event=EventVersion("e-1","MMA",1,"SYNTHETIC UFC","2026-09-19T21:00:00Z","2026-09-18T15:50:00Z",{"synthetic":"se-1"},"SCHEDULED")
    bout=BoutVersion("b-1","e-1","MMA",1,"f-1","f-2","Flyweight",5,"2026-09-18T15:50:00Z",{"synthetic":"sb-1"})
    odds=OddsSnapshot("b-1","MMA","SYNTHETIC","SyntheticBook","h2h","us","2026-09-18T15:58:00Z","2026-09-18T15:54:00Z",{"f-1":.55,"f-2":.45},"cap-1")
    result=ResultRevision("b-1","MMA",1,"FINAL","f-1","DECISION",5,"5:00","2026-09-19T23:10:00Z","cap-1",True,(1,2,3,4,5))
    return EvidenceBundle(T0,[capture],fighters,[event],[bout],[odds],[result])

class PocHarnessTest(unittest.TestCase):
    def test_synthetic_provider_adapters_and_real_payload_rejection(self):
        root=Path(__file__).with_name("fixtures")
        api=json.loads((root/"api_sports_synthetic.json").read_text(encoding="utf-8")); cap=synthetic_capture("API_SPORTS_MMA_SYNTHETIC","fixture://api",api,"2026-09-30T15:55:00Z")
        fighters,event,bouts=normalize_api_sports_synthetic(api,cap); self.assertEqual((len(fighters),len(bouts)),(2,1)); self.assertEqual(event.canonical_event_id,bouts[0].canonical_event_id)
        odds=json.loads((root/"the_odds_synthetic.json").read_text(encoding="utf-8")); ocap=synthetic_capture("THE_ODDS_API_SYNTHETIC","fixture://odds",odds,"2026-09-30T15:58:00Z")
        snapshot=normalize_odds_synthetic(odds,bouts[0].canonical_bout_id,ocap); self.assertAlmostEqual(sum(snapshot.outcomes.values()),1)
        with self.assertRaisesRegex(ValidationError,"NON_SYNTHETIC"): synthetic_capture("X","fixture://bad",{"event":{}},T0)
    def test_dry_plan_is_zero_network_and_exact_ceiling(self):
        plan=build_plan(); self.assertFalse(plan["liveExecution"]); self.assertEqual(plan["networkCalls"],0)
        self.assertEqual(plan["apiSports"]["requests"],80); self.assertEqual(plan["theOddsApi"]["credits"],80)
    def test_live_gate_requires_flag_rights_and_both_credentials(self):
        with self.assertRaisesRegex(ValidationError,"FLAG"): LiveGate.credentials({},execute_live=False)
        with self.assertRaisesRegex(ValidationError,"RIGHTS"): LiveGate.credentials({},execute_live=True)
        with self.assertRaisesRegex(ValidationError,"CREDENTIALS"): LiveGate.credentials({"MMA_POC_RIGHTS_APPROVED":"YES"},execute_live=True)
        self.assertEqual(LiveGate.credentials({"MMA_POC_RIGHTS_APPROVED":"YES","MMA_API_SPORTS_KEY":"x","MMA_THE_ODDS_API_KEY":"y"},execute_live=True),("x","y"))
    def test_budget_guards_fail_closed(self):
        g=BudgetGuard(); g.reserve_api_sports(80)
        with self.assertRaises(BudgetError): g.reserve_api_sports(1)
        with self.assertRaises(BudgetError): BudgetGuard().reserve_odds(1,region="uk",market="h2h")
        g2=BudgetGuard(); g2.reserve_odds(80,region="us",market="h2h")
        with self.assertRaises(BudgetError): g2.reserve_odds(1,region="us",market="h2h")
    def test_valid_synthetic_bundle(self): self.assertEqual(validate_bundle(bundle(),now=NOW),[])
    def test_alias_conflict_orphans_postcutoff_and_result_completeness(self):
        b=bundle(); b.fighters[1]=replace(b.fighters[1],aliases=("Alpha",)); b.bouts[0]=replace(b.bouts[0],canonical_event_id="missing",blue_fighter_id="missing",observed_at="2026-09-18T17:00:00Z"); b.results[0]=replace(b.results[0],method=None,round_stats_complete=False)
        errors=validate_bundle(b,now=NOW)
        for code in ("FIGHTER_ALIAS_AMBIGUITY","ORPHAN_BOUT_EVENT","ORPHAN_BOUT_FIGHTER","POST_CUTOFF_BOUT_EVIDENCE","RESULT_INCOMPLETE","ROUND_STATS_INCOMPLETE"): self.assertIn(code,errors)
    def test_schema_drift_and_all_latency_classes(self):
        validate_schema("same","same")
        with self.assertRaisesRegex(ValidationError,"SCHEMA_DRIFT"): validate_schema("new","old")
        for kind,minutes in (("schedule_change",15),("odds",10),("result",5),("statistics",15)):
            validate_latency(kind,"2026-09-18T15:00:00Z",f"2026-09-18T15:{minutes:02d}:00Z")
            with self.assertRaises(ValidationError): validate_latency(kind,"2026-09-18T15:00:00Z","2026-09-18T15:16:00Z")
    def test_append_only_supported_bout_changes(self):
        for reason,changes in (("OPPONENT_REPLACEMENT",{"blue_fighter_id":"f-3"}),("CANCELLATION",{"status":"CANCELLED"}),("SCHEDULED_ROUNDS_CHANGE",{"scheduled_rounds":3}),("WEIGHT_CLASS_CHANGE",{"weight_class":"Catchweight"}),("CORRECTION",{"weight_class":"Bantamweight"}),("PARTICIPANT_ORIENTATION_CHANGE",{"red_fighter_id":"f-2","blue_fighter_id":"f-1"})):
            ledger=AppendOnlyLedger(); first=bundle().bouts[0]; ledger.add_bout(first); ledger.add_bout(replace(first,version=2,predecessor_version=1,change_reason=reason,**changes)); self.assertEqual(len(ledger.bouts),2)
    def test_bad_revision_is_rejected(self):
        ledger=AppendOnlyLedger(); first=bundle().bouts[0]; ledger.add_bout(first)
        with self.assertRaises(ValidationError): ledger.add_bout(replace(first,version=3,predecessor_version=1,change_reason="CORRECTION",weight_class="X"))
    def test_mma_cannot_enter_other_sports_and_reverse(self):
        for sport in ("MLB","NFL","NBA","CFB"):
            with self.assertRaisesRegex(ValidationError,"CROSS_SPORT"): require_pipeline_sport("MMA",sport)
            with self.assertRaisesRegex(ValidationError,"CROSS_SPORT"): require_pipeline_sport(sport,"MMA")

if __name__=="__main__": unittest.main()
