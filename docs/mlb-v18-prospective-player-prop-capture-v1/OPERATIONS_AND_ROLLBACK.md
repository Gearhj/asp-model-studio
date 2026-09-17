# Operations and rollback

## Verify the staged deployment

```powershell
& 'C:\Users\james\asp-model-studio\.deployments\mlb-v18-unattended\b8cae23dde745d0d5f5cf4d160b4970d2892c38b\scripts\install_mlb_v18_unattended.ps1' `
  -Mode Plan `
  -RepositoryRoot 'C:\Users\james\asp-model-studio' `
  -CodeRoot 'C:\Users\james\asp-model-studio\.deployments\mlb-v18-unattended\b8cae23dde745d0d5f5cf4d160b4970d2892c38b'
```

Plan must report exactly one canonical task, S4U, least privilege, the five-
minute trigger, `IgnoreNew`, and the b8cae23 code root. Wait for task state
`Ready`; never interrupt or manually start the task.

## Activated owner

The supported installer completed with `-Mode Install -Force` after explicit
authorization and Administrator elevation. It preserved a predecessor manifest
and updated only the canonical task and shared deployment manifest. Do not
repeat installation merely to refresh clocks or receipts.

The following activation checks passed:

- deployment manifest and task action bind b8cae23 exactly;
- only `ASP MLB V18 Research Publisher` owns this workflow;
- the natural launcher receipt reports `python_exit_code=0`;
- two natural no-due ticks bind the successor identity; a normal
  `BOUNDED_TICK_COMPLETED` remains pending the first governed window;
- the existing T-60/T-45/T-30/T-15/T-5 contract remains present;
- no duplicate 5,000-draw inference was run for unchanged inputs;
- ordinary forecast artifacts remain immutable;
- capture failure, if any, is isolated and has a content-addressed receipt.

Verify prospective packages without loading outcomes:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' `
  'C:\Users\james\asp-model-studio\.deployments\mlb-v18-unattended\b8cae23dde745d0d5f5cf4d160b4970d2892c38b\scripts\verify_mlb_v18_prospective_player_prop_capture.py' `
  --root 'C:\Users\james\asp-model-studio\outputs\mlb-v18-player-prop-prospective-v1'
```

Zero packages is valid until a genuinely new eligible forecast is produced.

## Stop and rollback conditions

Rollback if the successor changes numerical forecast bytes, causes the ordinary
publisher to fail, creates a second owner, violates first-pitch chronology,
registers a late capture as prospective, or produces a failed natural launcher
or bounded tick.

Use the previous immutable deployment with the same supported installer:

```powershell
& 'C:\Users\james\asp-model-studio\.deployments\mlb-v18-unattended\77d39e1ae08e05be82e19bdb0bab21999fba1d3b\scripts\install_mlb_v18_unattended.ps1' `
  -Mode Install `
  -RepositoryRoot 'C:\Users\james\asp-model-studio' `
  -CodeRoot 'C:\Users\james\asp-model-studio\.deployments\mlb-v18-unattended\77d39e1ae08e05be82e19bdb0bab21999fba1d3b'
```

Again, wait for task state `Ready` and then observe a natural invocation. Never
manual-start the task to manufacture a receipt. Preserve successor failure
receipts and private capture objects for diagnosis; do not rewrite discovery or
delete predecessor artifacts.

## Study-role operations

Captures remain `DEVELOPMENT` until all frozen family-specific minimums are
met. Results are stored later under a separate governed result identity. No
Validation outcomes may be read during Development. A date-atomic Development
closure and frozen assessment method are prerequisites for Validation. Final
OOT is not part of this study.
