"""Classification counterpart to seedScoringRunProject.py -- seeds a fresh user
+ classification project with a trained model, a saved final model, and
durable Scoring Runs for TRAIN, TEST, and OOT. Used by the Visual Intelligence
Production Integration Playwright suite's classification path.

Prints one JSON line to stdout: {project_id, cookies, scoring_run_ids: {...}}.
"""
import json
import sys
import time
import uuid

import pandas as pd
import httpx

BASE = "http://127.0.0.1:8001/api"
DATA_FILE = r"C:\Users\james\ds-workflow-starter\tests\e2e\data\e2e_audit_classification_dev.csv"
OOT_FILE = r"C:\Users\james\ds-workflow-starter\tests\e2e\data\e2e_audit_classification_oot.csv"
TARGET = "Class"

s = httpx.Client(timeout=180.0)


def step(name: str) -> None:
    print(f"[seed-scoring-class] {name}", file=sys.stderr, flush=True)


suffix = uuid.uuid4().hex[:10]
project_name = sys.argv[1] if len(sys.argv) > 1 else "E2E Seeded Classification Scoring Run Project"
email = f"e2e-seedscoringclass-{suffix}@atlas-e2e.local"

step("register")
r = s.post(f"{BASE}/auth/register", json={
    "email": email, "displayName": f"E2E Seed Scoring Class {suffix}",
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
r = s.post(f"{BASE}/outliers/apply", json={"project_id": project_id, "config": {}, "global_method": "IQR_1_5", "target": TARGET, "problem_type": "classification"})
r.raise_for_status()

step("missing/apply")
r = s.post(f"{BASE}/missing/apply", json={"project_id": project_id, "config": {}, "problem_type": "classification"})
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
    "project_id": project_id, "split_strategy": "holdout", "test_size": 0.2, "random_seed": 42, "stratify": True,
    "balance_method": "none", "problem_type": "classification", "event_value": 1,
    "selected_features": selected_columns, "feature_manifest_version": manifest_version, "dataset_version": "",
})
r.raise_for_status()
split_id = r.json().get("split_id") or ""

step("model/train/jobs (logreg)")
r = s.post(f"{BASE}/model/train/jobs", json={
    "models": ["logreg"], "k_folds": 2, "max_parallel": 1, "calibrate": False,
    "target": TARGET, "event_value": 1, "non_event_value": 0, "problem_type": "classification",
    "dataset_version": "", "feature_manifest_version": manifest_version, "split_id": split_id, "project_id": project_id,
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
assert status == "complete", f"training did not complete: {status}"

step("model/save_final (logreg)")
r = s.post(f"{BASE}/model/save_final", json={"project_id": project_id, "model": "logreg"})
r.raise_for_status()
assert r.json().get("ok"), r.json()

step("score TRAIN (development-split)")
r = s.post(f"{BASE}/score/development-split", params={"project_id": project_id, "dataset_type": "train"})
r.raise_for_status()
train_result = r.json()
assert train_result.get("ok"), train_result

step("score TEST (development-split)")
r = s.post(f"{BASE}/score/development-split", params={"project_id": project_id, "dataset_type": "test"})
r.raise_for_status()
test_result = r.json()
assert test_result.get("ok"), test_result

step("score OOT (upload)")
with open(OOT_FILE, "rb") as handle:
    r = s.post(
        f"{BASE}/score/upload",
        params={"project_id": project_id, "dataset_type": "oot"},
        files={"file": ("oot.csv", handle, "text/csv")},
    )
r.raise_for_status()
oot_result = r.json()
assert oot_result.get("ok"), oot_result

print(json.dumps({
    "email": email, "user_id": user["userId"], "project_id": project_id,
    "cookies": dict(s.cookies), "training_status": status,
    "scoring_run_ids": {
        "train": train_result.get("scoringRunId"),
        "test": test_result.get("scoringRunId"),
        "oot": oot_result.get("scoringRunId"),
    },
    "target": TARGET,
}))
