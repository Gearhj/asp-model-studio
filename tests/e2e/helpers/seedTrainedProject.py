"""Seed a fresh user + project with a completed classification training run via
direct HTTP calls to the already-running dev backend, bypassing the (separately
verified) early workflow UI steps. Used by regression tests that need to reach
Interpretation quickly while still exercising the real UI for the behavior under
test. Prints one JSON line to stdout: {project_id, cookies, dataset_version, ...}.
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pandas as pd
import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE = os.getenv("ASP_MODEL_STUDIO_API_BASE", "http://127.0.0.1:8101/api").rstrip("/")
DATA_FILE = REPO_ROOT / "tests" / "e2e" / "data" / "e2e_audit_classification_dev.csv"

s = httpx.Client(timeout=120.0)


def step(name: str) -> None:
    # Progress goes to stderr so stdout stays a single JSON line for the consuming test.
    print(f"[seed] {name}", file=sys.stderr, flush=True)

suffix = uuid.uuid4().hex[:10]
project_name = sys.argv[1] if len(sys.argv) > 1 else "E2E Seeded Project"
email = f"e2e-seed-{suffix}@atlas-e2e.local"

step("register")
r = s.post(f"{BASE}/auth/register", json={
    "email": email, "displayName": f"E2E Seed {suffix}",
    "password": "AtlasE2ePassw0rd!", "role": "data_scientist",
})
r.raise_for_status()
user = r.json()["user"]

step("create project")
r = s.post(f"{BASE}/projects", json={"projectName": project_name, "projectType": "predictive-modeling"})
r.raise_for_status()
project_id = r.json()["project"]["projectId"]

df = pd.read_csv(DATA_FILE)
target = "Class"
headers = list(df.columns)
selected_columns = [c for c in headers if c != target]
rows = df.to_dict(orient="records")

step("set_sample")
r = s.post(f"{BASE}/data/set_sample", json={
    "project_id": project_id, "headers": headers, "rows": rows,
    "target": target, "selected_columns": selected_columns,
})
r.raise_for_status()

step("outliers/apply")
r = s.post(f"{BASE}/outliers/apply", json={
    "project_id": project_id, "config": {}, "global_method": "IQR_1_5",
    "target": target, "problem_type": "classification",
})
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
    "project_id": project_id, "split_strategy": "holdout", "test_size": 0.2,
    "random_seed": 42, "stratify": True, "balance_method": "none",
    "problem_type": "classification", "event_value": 1,
    "selected_features": selected_columns, "feature_manifest_version": manifest_version,
    "dataset_version": "",
})
r.raise_for_status()
split_id = r.json().get("split_id") or ""

step("model/train/jobs")
r = s.post(f"{BASE}/model/train/jobs", json={
    "models": ["logreg"], "k_folds": 2, "max_parallel": 1, "calibrate": False,
    "target": target, "event_value": 1, "non_event_value": 0, "problem_type": "classification",
    "dataset_version": "", "feature_manifest_version": manifest_version, "split_id": split_id,
    "project_id": project_id,
})
r.raise_for_status()
job_id = r.json().get("job_id")

deadline = time.time() + 120
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
}))
