"""Rebuild the bounded, saved-evidence diagnosis. No model execution."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
STEPS=[
    "outputs/mlb-v18-empirical-diagnosis-v1/lineage/build_lineage.py",
    "scripts/diagnose_mlb_v18_pa_v1.py",
    "scripts/diagnose_mlb_v18_calibration_leads_v1.py",
    "scripts/diagnose_mlb_v18_whole_game_v1.py",
    "scripts/enrich_mlb_v18_pa_cases_v1.py",
    "scripts/render_mlb_v18_diagnostic_tables_v1.py",
    "scripts/build_mlb_v18_diagnosis_report_v1.py",
    "scripts/manifest_mlb_v18_diagnosis_v1.py",
]
if __name__=="__main__":
    for step in STEPS:
        print("Running "+step,flush=True)
        subprocess.run([sys.executable,str(ROOT/step)],cwd=ROOT,check=True)
