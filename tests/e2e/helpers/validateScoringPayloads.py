"""Stage B.7 independent metric validation.

Reads the raw backend scoring payloads captured by
predictive-modeling-scoring-oot.spec.ts (test-results/e2e/logs/b7_*.json) and
independently recomputes the key classification metrics and Prediction PSI
from the per-row scored output, comparing against the values the backend
reported. Writes test-results/e2e/logs/b7_metric_validation.json and prints a
summary table. Read-only with respect to the app; requires numpy/sklearn from
the project venv.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    accuracy_score,
    roc_auc_score,
    roc_curve,
)

ROOT = Path(__file__).resolve().parents[3]
LOGS = ROOT / "test-results" / "e2e" / "logs"
TOL = 1e-6


def load(name: str) -> dict:
    return json.loads((LOGS / name).read_text(encoding="utf-8"))


def extract_scores_and_actuals(payload: dict) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    rows = payload.get("scored_rows") or []
    if not rows:
        raise SystemExit(f"payload has no scored_rows (scope={payload.get('scored_row_scope')})")
    frame = pd.DataFrame(rows)
    score_col = next((c for c in ("adjusted_score", "score", "predicted_probability", "model_score") if c in frame.columns), None)
    label_col = next((c for c in ("prediction", "predicted_class", "predicted_label") if c in frame.columns), None)
    target_col = payload.get("target_column") or (payload.get("model") or {}).get("target")
    actual_col = target_col if target_col and target_col in frame.columns else ("actual" if "actual" in frame.columns else None)
    scores = pd.to_numeric(frame[score_col], errors="coerce").to_numpy(dtype=float)
    labels = pd.to_numeric(frame[label_col], errors="coerce").to_numpy(dtype=float) if label_col else None
    actuals = pd.to_numeric(frame[actual_col], errors="coerce").to_numpy(dtype=float) if actual_col else None
    return scores, labels, actuals


def psi_like_backend(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """Mirror EVAL._stability_index_numeric exactly."""
    exp = pd.Series(expected).dropna()
    act = pd.Series(actual).dropna()
    quantiles = np.unique(np.quantile(exp, np.linspace(0, 1, bins + 1)))
    internal = quantiles[1:-1]
    edges = np.concatenate(([-np.inf], np.unique(internal), [np.inf]))
    exp_counts = pd.cut(exp, edges, include_lowest=True, duplicates="drop").value_counts(sort=False).to_numpy()
    act_counts = pd.cut(act, edges, include_lowest=True, duplicates="drop").value_counts(sort=False).to_numpy()
    exp_pct = np.clip(exp_counts.astype(float) / max(float(exp_counts.sum()), 1.0), 1e-6, None)
    act_pct = np.clip(act_counts.astype(float) / max(float(act_counts.sum()), 1.0), 1e-6, None)
    return float(np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct)))


def validate_partition(name: str, payload: dict, csv_rows: int | None) -> dict:
    scores, labels, actuals = extract_scores_and_actuals(payload)
    reported = payload.get("metrics") or {}
    out: dict = {
        "partition": name,
        "reported_rows": payload.get("rows"),
        "scored_rows_len": len(scores),
        "csv_rows": csv_rows,
        "row_count_matches_csv": csv_rows is None or payload.get("rows") == csv_rows,
        "prob_min": float(np.nanmin(scores)),
        "prob_max": float(np.nanmax(scores)),
        "prob_in_unit_interval": bool(np.nanmin(scores) >= 0.0 and np.nanmax(scores) <= 1.0),
        "checks": {},
    }
    if labels is not None:
        agree_05 = float(np.mean((scores >= 0.5).astype(float) == labels))
        out["label_agreement_with_0.5_threshold"] = agree_05
    if actuals is not None and reported:
        y = actuals.astype(int)
        recomputed = {
            "auc": float(roc_auc_score(y, scores)),
            "pr_auc": float(average_precision_score(y, scores)),
            "brier_score": float(brier_score_loss(y, scores)),
            "event_rate": float(np.mean(y)),
        }
        if labels is not None:
            recomputed.update({
                "accuracy": float(accuracy_score(y, labels)),
                "precision": float(precision_score(y, labels, zero_division=0)),
                "recall": float(recall_score(y, labels, zero_division=0)),
                "f1": float(f1_score(y, labels, zero_division=0)),
            })
            out["confusion_recomputed"] = confusion_matrix(y, labels).tolist()
            out["confusion_reported"] = reported.get("confusion")
        fpr, tpr, _ = roc_curve(y, scores)
        recomputed["ks"] = float(np.max(tpr - fpr))
        for key, mine in recomputed.items():
            theirs = reported.get(key)
            out["checks"][key] = {
                "backend": theirs,
                "independent": mine,
                "match": theirs is not None and abs(float(theirs) - mine) < 1e-6,
            }
    return out


def capture(seed_file: str) -> None:
    """Capture the raw scoring payloads out-of-band with the seeded session.
    Playwright cannot read these response bodies (full scored output for
    100k+ rows is evicted from the CDP inspector cache), so validation
    fetches them directly from the same endpoints with the same cookie."""
    import httpx

    seed = json.loads(Path(seed_file).read_text(encoding="utf-8").strip().splitlines()[-1])
    base = "http://127.0.0.1:8001/api"
    client = httpx.Client(timeout=900.0, cookies=seed["cookies"])
    LOGS.mkdir(parents=True, exist_ok=True)

    r = client.post(f"{base}/score/development-split", params={
        "project_id": seed["project_id"], "dataset_type": "train",
        "model": "final", "correction_method": "none"})
    r.raise_for_status()
    (LOGS / "b7_train_payload.json").write_text(r.text, encoding="utf-8")
    print("train rows:", r.json().get("rows"))

    for name, csv_path, dataset_type in (
        ("b7_test_payload.json", r"C:\Users\james\FAAI\CLASS_TEST.csv", "test"),
        ("b7_oot_payload.json", r"C:\Users\james\FAAI\CLASS_OOT.csv", "oot"),
    ):
        with open(csv_path, "rb") as fh:
            resp = client.post(
                f"{base}/score/upload",
                params={"project_id": seed["project_id"], "dataset_type": dataset_type,
                        "model": "final", "correction_method": "none"},
                files={"file": (Path(csv_path).name, fh, "text/csv")},
            )
        resp.raise_for_status()
        (LOGS / name).write_text(resp.text, encoding="utf-8")
        body = resp.json()
        print(dataset_type, "rows:", body.get("rows"), "psi:", (body.get("psi") or {}).get("value"))


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "capture":
        capture(sys.argv[2])
        return 0
    train = load("b7_train_payload.json")
    test = load("b7_test_payload.json")
    oot = load("b7_oot_payload.json")

    results = {
        "train": validate_partition("TRAIN(dev split)", train, None),
        "test": validate_partition("TEST", test, 56961),
        "oot": validate_partition("OOT", oot, 56962),
    }

    # Prediction PSI: backend reference is the model's scores on the DEV TRAIN
    # split, which is exactly what b7_train_payload's scored rows contain
    # (same split, same model, same correction method "none").
    train_scores, _, _ = extract_scores_and_actuals(train)
    for name, payload in (("test", test), ("oot", oot)):
        backend_psi = (payload.get("psi") or {}).get("value")
        upload_scores, _, _ = extract_scores_and_actuals(payload)
        mine = psi_like_backend(train_scores, upload_scores)
        results[name]["psi_check"] = {
            "backend": backend_psi,
            "independent": mine,
            "abs_diff": None if backend_psi is None else abs(backend_psi - mine),
            "match_1e-9": backend_psi is not None and abs(backend_psi - mine) < 1e-9,
            "status_reported": (payload.get("psi") or {}).get("status"),
        }
        results[name]["vsi_count"] = len(payload.get("vsi") or [])
        results[name]["vsi_scope"] = payload.get("vsi_scope")
        results[name]["stability_reference"] = payload.get("stability_reference")
        results[name]["vsi_top5"] = (payload.get("vsi") or [])[:5]

    (LOGS / "b7_metric_validation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    failures = []
    for part, res in results.items():
        for key, check in (res.get("checks") or {}).items():
            if not check["match"]:
                failures.append(f"{part}.{key}: backend={check['backend']} independent={check['independent']}")
        psi = res.get("psi_check")
        if psi and not psi["match_1e-9"]:
            failures.append(f"{part}.psi: backend={psi['backend']} independent={psi['independent']}")
        if not res.get("prob_in_unit_interval"):
            failures.append(f"{part}: probabilities outside [0,1]")
        if not res.get("row_count_matches_csv"):
            failures.append(f"{part}: rows {res['reported_rows']} != csv {res['csv_rows']}")

    print(json.dumps({p: {k: v for k, v in r.items() if k in ("reported_rows", "csv_rows", "prob_in_unit_interval", "label_agreement_with_0.5_threshold")} for p, r in results.items()}, indent=2))
    if failures:
        print("MISMATCHES:")
        for failure in failures:
            print(" -", failure)
        return 1
    print("ALL INDEPENDENT METRIC AND PSI CHECKS MATCH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
