"""Seed a fresh user + regression project with two completed lightweight
regression training runs (Linear Regression + Decision Tree Regressor) via
direct HTTP calls to the already-running dev backend, bypassing the
(separately verified) Regression Stage A workflow UI steps. Mirrors
seedTrainedProject.py's classification pattern. Used by Regression Stage B
tests that need to reach Evaluation/Interpretation/Scoring quickly while
still exercising the real UI for the behavior under test. Prints one JSON
line to stdout: {project_id, cookies, dataset_version, manifest_version, ...}.
"""
import json
import sys
import time
import uuid

import pandas as pd
import httpx

BASE = "http://127.0.0.1:8001/api"
DATA_FILE = r"C:\Users\james\ds-workflow-starter\tests\e2e\data\e2e_audit_regression_dev.csv"
TARGET = "MedHouseVal"

s = httpx.Client(timeout=180.0)


def step(name: str) -> None:
    print(f"[seed-reg] {name}", file=sys.stderr, flush=True)


suffix = uuid.uuid4().hex[:10]
project_name = sys.argv[1] if len(sys.argv) > 1 else "E2E Seeded Regression Project"
email = f"e2e-seedreg-{suffix}@atlas-e2e.local"

step("register")
r = s.post(f"{BASE}/auth/register", json={
    "email": email, "displayName": f"E2E Seed Reg {suffix}",
    "password": "AtlasE2ePassw0rd!", "role": "data_scientist",
})
r.raise_for_status()
user = r.json()["user"]

step("create project")
r = s.post(f"{BASE}/projects", json={"projectName": project_name, "projectType": "predictive-modeling"})
r.raise_for_status()
project_id = r.json()["project"]["projectId"]

df = pd.read_csv(DATA_FILE)
headers = list(df.columns)
selected_columns = [c for c in headers if c != TARGET]
rows = df.to_dict(orient="records")

step("set_sample")
r = s.post(f"{BASE}/data/set_sample", json={
    "project_id": project_id, "headers": headers, "rows": rows,
    "target": TARGET, "selected_columns": selected_columns,
})
r.raise_for_status()

step("outliers/apply")
r = s.post(f"{BASE}/outliers/apply", json={
    "project_id": project_id, "config": {}, "global_method": "IQR_1_5",
    "target": TARGET, "problem_type": "regression",
})
r.raise_for_status()

step("missing/apply")
r = s.post(f"{BASE}/missing/apply", json={"project_id": project_id, "config": {}, "problem_type": "regression"})
r.raise_for_status()

step("features/manifest")
r = s.post(f"{BASE}/features/manifest", json={"project_id": project_id, "features": [], "pipeline_steps": [], "dataset_version": ""})
r.raise_for_status()
manifest_version = r.json().get("manifest_version") or ""

step("features/materialize")
r = s.post(f"{BASE}/features/materialize", json={"project_id": project_id, "manifest_version": manifest_version})
r.raise_for_status()

step("balancing_split/config")
r = s.post(f"{BASE}/balancing_split/config", json={
    "project_id": project_id, "split_strategy": "holdout", "test_size": 0.2,
    "random_seed": 42, "stratify": False, "balance_method": "none",
    "problem_type": "regression", "event_value": None,
    "selected_features": selected_columns, "feature_manifest_version": manifest_version,
    "dataset_version": "",
})
r.raise_for_status()
split_id = r.json().get("split_id") or ""

step("model/train/jobs (linreg + dt_reg)")
r = s.post(f"{BASE}/model/train/jobs", json={
    "models": ["linreg", "dt_reg"], "k_folds": 2, "max_parallel": 1, "calibrate": False,
    "target": TARGET, "event_value": None, "non_event_value": None, "problem_type": "regression",
    "dataset_version": "", "feature_manifest_version": manifest_version, "split_id": split_id,
    "project_id": project_id,
})
r.raise_for_status()
job_id = r.json().get("job_id")

deadline = time.time() + 180
status = None
while time.time() < deadline:
    r = s.get(f"{BASE}/model/train/jobs/{job_id}", params={"project_id": project_id})
    r.raise_for_status()
    status = r.json().get("overall_status")
    if status in ("complete", "failed", "cancelled", "interrupted"):
        break
    time.sleep(2)

print(json.dumps({
    "email": email, "user_id": user["userId"], "project_id": project_id,
    "cookies": dict(s.cookies), "training_status": status, "job_id": job_id,
    "manifest_version": manifest_version, "split_id": split_id, "target": TARGET,
}))
