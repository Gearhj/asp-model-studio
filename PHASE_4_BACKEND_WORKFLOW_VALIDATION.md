# Phase 4 Backend Workflow Validation

Date: 2026-07-03

## Scope

Validated the predictive-modeling backend path against the running local ATLAS API at `http://127.0.0.1:8001/api`.

## Environment Check

`GET /api/health`

Result:

```json
{"ok":true,"status":"running"}
```

## Dataset Load

Endpoint: `POST /api/data/set_sample`

Synthetic classification dataset:

- Rows: 600
- Columns: 5
- Target: `Class`
- Features: `Amount`, `V1`, `V2`, `V3`

Result:

```json
{"ok":true,"n_rows":600,"n_cols":5,"columns":["Class","Amount","V1","V2","V3"],"target":"Class"}
```

## Model Training

Endpoint: `POST /api/model/train`

Payload summary:

- Models: `logreg`, `rf`
- K folds: 5
- Max parallel models: 2
- Calibration: enabled
- Grid search: enabled
- Search depth: `quick`

Result:

- Status: `trained`
- Train rows: 420
- Test rows: 180
- Problem type: classification

Key metrics:

| Model | AUC | PR-AUC | Accuracy | F1 | KS |
|---|---:|---:|---:|---:|---:|
| Logistic Regression | 0.9997 | 0.9989 | 0.9833 | 0.9639 | 0.9928 |
| Random Forest | 0.9948 | 0.9854 | 0.9667 | 0.9250 | 0.9472 |

## Evaluation Endpoint

Endpoint: `GET /api/eval/curves?model=logreg`

Result:

```json
{
  "ok": true,
  "metrics": {
    "precision": 0.9756,
    "recall": 0.9524,
    "f1": 0.9639,
    "auc": 0.9997,
    "pr_auc": 0.9989
  }
}
```

## Persistence Validation

Browser project reopen behavior is covered by `npm run test:persistence`, including:

- predictive snapshot save and restore
- Experimental Design snapshot save and restore
- compact Monte Carlo persistence
- corrupted registry handling
- legacy Recent Projects migration
- import validation
- artifact restore-status classification

## Notes and Limitations

- This validation exercised the backend API and persistence utilities directly. It did not use an interactive browser file picker.
- The `/api/data/set_sample` endpoint is the current frontend-compatible dataset load path.
- The `/api/data/upload_csv` endpoint now has upload guardrails but should be separately validated with large-file fixtures before hosted deployment.
