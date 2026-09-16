"""Hash only the new diagnostic artifacts and scripts, never sealed sources."""
from pathlib import Path
import hashlib
import json
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"outputs/mlb-v18-empirical-diagnosis-v1"
SCRIPT_NAMES=["diagnose_mlb_v18_pa_v1.py","diagnose_mlb_v18_calibration_leads_v1.py","diagnose_mlb_v18_whole_game_v1.py","enrich_mlb_v18_pa_cases_v1.py","render_mlb_v18_diagnostic_tables_v1.py","build_mlb_v18_diagnosis_report_v1.py","run_mlb_v18_empirical_diagnosis_v1.py","manifest_mlb_v18_diagnosis_v1.py"]
def record(p):
    raw=p.read_bytes()
    return {"path":str(p.resolve()),"relativePath":str(p.relative_to(ROOT)).replace('\\','/'),"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)}
if __name__=="__main__":
    paths=sorted(p for p in OUT.rglob('*') if p.is_file() and p!=OUT/'artifact-manifest.json' and '__pycache__' not in p.parts)
    scripts=[ROOT/'scripts'/s for s in SCRIPT_NAMES]
    manifest={"schemaVersion":"MLB_V18_EMPIRICAL_DIAGNOSIS_V1","generatedAtUtc":datetime.now(timezone.utc).isoformat(),"branch":"codex/mlb-starter-duration-source-intake-v1","committedHead":"9ca94e9c0135cde7d2b852560d59a43fa45a5c17","artifacts":[record(p) for p in paths],"scripts":[record(p) for p in scripts],"inputEvidenceManifests":["pa/input-manifest.json","pa/calibration-lead-input-manifest.json","pa/case-enrichment-input-manifest.json","whole-game/artifact-manifest.json","lineage/pa-lineage.json"],"scope":{"savedPredictionsOnly":True,"modelFits":0,"modelInference":0,"forecastSimulations":0,"providerRequests":0,"aispMutations":0,"operatingTaskChanges":0,"finalOotPayloadReads":0,"remainingSealedOotKeys":13837},"reproduceCommand":r".\.venv\Scripts\python.exe scripts/run_mlb_v18_empirical_diagnosis_v1.py"}
    (OUT/'artifact-manifest.json').write_text(json.dumps(manifest,indent=2)+"\n",encoding='utf-8')
    print(f"Manifest: {len(paths)} diagnostic files, {len(scripts)} scripts")
