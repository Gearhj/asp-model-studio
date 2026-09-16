"""Read-only model audit; all new artifacts remain in one research directory."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'outputs/multisport-feature-engineering-audit-v1'

def now():return datetime.now(timezone.utc).isoformat()
def ref(path):
    p=Path(path);h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return dict(path=str(p.resolve()),sha256=h.hexdigest(),bytes=p.stat().st_size)
def write(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes((json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2)+'\n').encode('utf-8'))
def declare():
    p=OUT/'AUDIT_DESIGN.json'
    if p.exists():raise ValueError('Audit declaration already frozen')
    weights=dict(incrementalValue=25,demonstratedWeakness=15,historicalDepth=8,
        prospectiveAvailability=10,pointInTimeIntegrity=10,licensingCost=5,
        identityReliability=5,missingness=5,implementationEffort=5,
        maintainability=4,interpretability=3,leakageRisk=5)
    assert sum(weights.values())==100
    write(p,dict(schemaVersion='MULTISPORT_FEATURE_ENGINEERING_AUDIT_V1',createdAtUtc=now(),
        startingBranch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
        startingHead=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        precedingStudy=ref(ROOT/'outputs/nfl-drive-competing-risks-v1/artifact-index.json'),
        scope=['MLB','NFL','NBA','CFB'],responseFormat='Explicit user-requested Markdown/CSV/JSON research artifacts; no dashboard or consumer handoff.',
        restrictions=dict(providerRequests=0,sportsbookRequests=0,aispWrites=0,productionRefits=0,
            prospectivePublications=0,schedulerChanges=0,sealedCohortAccess=0,calendar2026OutcomeAccess=0),
        outcomePolicy='No MLB outcome payload will be opened. For other sports, select admitted chronological populations and freeze empirical roles before reading their labels. Exclude every calendar-2026 outcome and every genuinely sealed partition. Current published feature contracts/forecast inputs may be inspected without outcomes.',
        empiricalPlan='Reuse trustworthy retained evidence; standardized linear coefficients and descriptive tree importance first. Freeze at most eight feature-family assessments per model, fixed hyperparameters and deterministic sample/seed, after metadata/Development review and before reused later outcomes. Skip unsupported chronology or unavailable matrices explicitly. No simulation regeneration.',
        uncertainty='Games/seasons or calendar blocks; no simulation-draw assessment units. Correlated-family permutation/ablation estimates are associational and may be unstable.',
        priorityWeights=weights,priorityScale='1 to 5; higher is more favorable, including lower cost/effort/missingness/leakage risk.',
        priorityFormula='sum(weight_i * score_i)/100, on a 1-to-5 scale.',
        principalEligibilityGate='A proposed predictive challenger cannot win on score alone when its source, lawful use, historical identity or prospective timing is unusable. Explicitly mark such prerequisites; no acquisition occurs here.',
        allowedNextAction='Recommend exactly one next challenger; do not implement it.',seed=9152601))
    print(json.dumps(ref(p)))

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['declare'],required=True)
    a=p.parse_args()
    if a.stage=='declare':declare()
if __name__=='__main__':main()
