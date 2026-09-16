# Deterministic checks and manual producer

From `C:\Users\james\asp-model-studio`:

```powershell
.\.venv\Scripts\python.exe scripts\run_mlb_show_preview_feasibility_v1.py assess
.\.venv\Scripts\python.exe -B -m unittest tests.test_mlb_show_preview_team -v
.\.venv\Scripts\python.exe scripts\run_mlb_show_preview_feasibility_v1.py check-current --inputs <admitted-current-inputs.json>
.\.venv\Scripts\python.exe scripts\run_mlb_show_preview_feasibility_v1.py produce --inputs <admitted-current-inputs.json>
```

`assess` reuses the retained assessment after checking bound physical artifacts. The retained-prediction test independently recomputes all 2,429 Validation predictions and requires exact numerical equality. For a fresh isolated refit, copy FROZEN_DESIGN.json and historical-identity-inspection.json into a new output directory and pass `assess --out <directory>`; it reads only the pinned2019-2024 archives and uses the same locked configuration.

`produce` is a callable manual entry point, not an installed scheduler. It binds the assessed model-trained-through-2023.joblib. It requires an independently admitted owner export and complete history; a caller boolean or invented current vector is insufficient. The source is content-addressed by model, assessment and input bindings; repeats preserve its creation time. The common preview publisher performs consumer validation, immutable publication and atomic discovery. It will not convert a late call into an on-time preview.

The tests publish synthetic artifacts only under ignored `outputs/show-preview-focused-tests/`. They never write to the real exchange or AISP. Such packages must never be imported as forecasts.

Activation stays inactive: after the exact input export has been admitted and checked, wire this callable into the existing preview owner's15:15 America/New_York invocation, with16:00 stop and16:30 optional consumer freeze. Do not create a second Windows task or alter finalV18 checkpoints. No activation occurred in this assignment.
