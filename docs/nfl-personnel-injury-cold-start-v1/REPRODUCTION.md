# Reproduction

From the branch worktree, using the existing project environment:

```powershell
C:/Users/james/asp-model-studio/.venv/Scripts/python.exe -m scripts.audit_nfl_personnel_injury_v1
C:/Users/james/asp-model-studio/.venv/Scripts/python.exe -m scripts.capture_nfl_personnel_evidence_v1 --season 2026
C:/Users/james/asp-model-studio/.venv/Scripts/python.exe -m pytest tests/test_nfl_personnel_evidence.py -q
```

The audit opens only identity, schedule-without-score, roster, depth, injury, draft and snap metadata through 2024. It does not open 2023–2026 outcomes. The capture command shown is plan-only and performs no network I/O.
