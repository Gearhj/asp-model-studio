"""Seed a user + project with a completed classification training run and a
SAVED FINAL MODEL, using a real CSV file through the product's large-file
import path (/data/upload_csv). Built for Stage B.7 (Scoring/TEST/OOT audit);
reusable for any scoring-flow test that needs to start at a ready final model.

Usage:
  python tests/e2e/helpers/seedScoringProject.py "<project name>" <csv_path> [keep_features]

Prints one JSON line to stdout: {email, user_id, project_id, cookies,
training_status, rfe_rows, final_ready, timings}.
Progress and timings go to stderr.
"""
import json
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8001/api"

project_name = sys.argv[1] if len(sys.argv) > 1 else "E2E Scoring Seeded Project"
csv_path = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\james\FAAI\CLASS_TRAIN.csv"
keep_features = int(sys.argv[3]) if len(sys.argv) > 3 else 10
target = "Class"

s = httpx.Client(timeout=600.0)
suffix = uuid.uuid4().hex[:10]
email = f"e2e-scoring-{suffix}@atlas-e2e.local"
timings = {}


def step(name):
    print(f"[seed] {name}", file=sys.stderr, flush=True)


def timed(name, fn):
    step(name)
    t0 = time.perf_counter()
    result = fn()
    timings[name] = round(time.perf_counter() - t0, 2)
    return result


r = timed("register", lambda: s.post(f"{BASE}/auth/register", json={
    "email": email, "displayName": f"E2E Scoring {suffix}",
    "password": "AtlasE2ePassw0rd!", "role": "data_scientist"}))
r.raise_for_status()
user = r.json()["user"]

r = timed("create project", lambda: s.post(f"{BASE}/projects", json={
    "projectName": project_name, "projectType": "predictive-modeling"}))
r.raise_for_status()
project_id = r.json()["project"]["projectId"]

with open(csv_path, "rb") as fh:
    r = timed("upload_csv", lambda: s.post(
        f"{BASE}/data/upload_csv",
        data={"project_id": project_id},
        files={"file": ("CLASS_TRAIN.csv", fh, "text/csv")},
    ))
r.raise_for_status()
upload = r.json()
assert upload.get("target") == target, upload.get("target")

r = timed("outliers/apply", lambda: s.post(f"{BASE}/outliers/apply", json={
    "project_id": project_id, "config": {}, "global_method": "IQR_1_5",
    "target": target, "problem_type": "classification"}))
r.raise_for_status()

r = timed("missing/apply", lambda: s.post(f"{BASE}/missing/apply", json={
    "project_id": project_id, "config": {}, "problem_type": "classification"}))
r.raise_for_status()

r = timed("features/manifest", lambda: s.post(f"{BASE}/features/manifest", json={
    "project_id": project_id, "features": [], "pipeline_steps": [], "dataset_version": ""}))
r.raise_for_status()
manifest_version = r.json().get("manifest_version") or ""

r = timed("features/materialize", lambda: s.post(f"{BASE}/features/materialize", json={
    "project_id": project_id, "manifest_version": manifest_version}))
r.raise_for_status()

selected_columns = [c for c in upload["columns"] if c != target]
r = timed("balancing_split/config", lambda: s.post(f"{BASE}/balancing_split/config", json={
    "project_id": project_id, "split_strategy": "holdout", "test_size": 0.2,
    "random_seed": 42, "stratify": True, "balance_method": "none",
    "problem_type": "classification", "event_value": 1,
    "selected_features": selected_columns, "feature_manifest_version": manifest_version,
    "dataset_version": ""}))
r.raise_for_status()
split_id = r.json().get("split_id") or ""

r = timed("model/train/jobs", lambda: s.post(f"{BASE}/model/train/jobs", json={
    "models": ["logreg"], "k_folds": 2, "max_parallel": 1, "calibrate": False,
    "target": target, "event_value": 1, "non_event_value": 0,
    "problem_type": "classification", "dataset_version": "",
    "feature_manifest_version": manifest_version, "split_id": split_id,
    "project_id": project_id}))
r.raise_for_status()
job_id = r.json().get("job_id")

step("poll training")
t0 = time.perf_counter()
status = None
deadline = time.time() + 600
while time.time() < deadline:
    r = s.get(f"{BASE}/model/train/jobs/{job_id}", params={"project_id": project_id})
    r.raise_for_status()
    status = r.json().get("overall_status")
    if status in ("complete", "failed", "cancelled", "interrupted"):
        break
    time.sleep(3)
timings["training"] = round(time.perf_counter() - t0, 2)

context = f"project_id={project_id}&dataset_version=&target={target}&problem_type=classification"
r = timed("interpretation/rfe", lambda: s.get(
    f"{BASE}/interpretation/rfe?model=logreg&keep={keep_features}&{context}"))
r.raise_for_status()
rfe = r.json()
rfe_rows = len(rfe.get("rows") or rfe.get("ranking") or [])

r = timed("rfe/save_final", lambda: s.post(f"{BASE}/interpretation/rfe/save_final", json={
    "model": "logreg", "keep": keep_features, "project_id": project_id,
    "dataset_version": "", "target": target, "problem_type": "classification"}))
r.raise_for_status()
save_final = r.json()
assert save_final.get("ok"), save_final

r = timed("model/final/status", lambda: s.get(
    f"{BASE}/model/final/status", params={"project_id": project_id}))
r.raise_for_status()
final_status = r.json()

print(json.dumps({
    "email": email, "user_id": user["userId"], "project_id": project_id,
    "cookies": dict(s.cookies), "training_status": status, "job_id": job_id,
    "rfe_rows": rfe_rows, "final_ready": final_status.get("ready"),
    "final_metadata": final_status.get("metadata"), "timings": timings,
}))
