# Activation handoff

Status: capture owner installed and operational.

- Branch: `codex/nfl-personnel-prospective-capture-v1`
- Active deployment identity: `da85acc26f5ce0e0edbe2c5a81ffeca318d9a868a243d071b0d5e8bc1067e422`
- Active deployment path: `C:\Users\james\asp-model-studio\.deployments\nfl-personnel-capture\da85acc26f5ce0e0edbe2c5a81ffeca318d9a868a243d071b0d5e8bc1067e422`
- Active task: exactly one canonical `ASP NFL Personnel Evidence Capture` owner, configured as S4U, Limited, and `IgnoreNew`
- Raw root: `C:\Users\james\asp-data-staging\nfl\personnel-captures-v1`
- Runtime root: `C:\Users\james\asp-model-studio\.runtime\nfl-personnel-capture`
- Retained successful initial capture: receipt `f28188339ebef3f7ac31a7288f1b654f975695d4e36c9b6a6342ecad73d6f3f6`; projection `b824635535ab09af0347d02265f6478541e8177e69dc80174a3d5984ef100957`
- First natural successor invocation: Python `NOT_DUE`, wrapper exit 0, Task Scheduler result 0, launcher receipt `e591afdd687028c8425eeff089cd9147d00b0d84b17c1cc80613087246479bf1`

The supported activation sequence is complete. Future replacement or rollback must continue to use the supported installer; do not create or manually register a competing task.

No approval or implementation work is needed from AISP for the active capture owner.

## Chronological audit history

1. Deployment `cbf3686a0c8ceb22dd135b5af9f3fb4738a8114a2e7ac969712992292404d20d` failed at package import before any provider request. Its immutable bytes and failure evidence remain retained.
2. Deployment `3139cff08216d9e16fcaa5d012a23738605e14f66c3fffc4687f73ecda7f7dcf` used the corrected isolated package initializer and completed the successful initial capture. Its first natural Python run returned `NOT_DUE`, but its wrapper used a .NET API absent from Windows PowerShell 5.1 and returned 1 while hashing the launcher receipt. Its immutable bytes, failure evidence, initial capture receipt, and projection remain retained. It is not the current deployment.

## Final activation

James directly authorized deployment `da85acc26f5ce0e0edbe2c5a81ffeca318d9a868a243d071b0d5e8bc1067e422`. The supported installer replaced the one canonical task binding on September 17, 2026. The runtime deployment record and task action both bind that exact deployment. The task remained S4U, Limited, `IgnoreNew`, and scheduled every fifteen minutes with a fifteen-minute execution limit.

The first natural successor invocation began at `2026-09-17T16:29:51.0529147Z` and completed at `2026-09-17T16:29:54.7754825Z`. Python returned `NOT_DUE` with exit code 0. The PowerShell wrapper returned 0, Task Scheduler reported result 0, and immutable launcher receipt `e591afdd687028c8425eeff089cd9147d00b0d84b17c1cc80613087246479bf1` was written. The run made zero provider requests and zero AISP or exchange writes.

The authorized initial capture was not repeated. Capture receipt `f28188339ebef3f7ac31a7288f1b654f975695d4e36c9b6a6342ecad73d6f3f6`, projection `b824635535ab09af0347d02265f6478541e8177e69dc80174a3d5984ef100957`, and six raw objects remain the sole retained capture population. The immutable `3139cff...dcf` deployment remains available as audit history. Do not use it as the current binding because its Windows PowerShell 5.1 wrapper cannot produce a launcher receipt.

The machine-readable closeout is `ACTIVATION_RECEIPT.json`. No forecast, model, AISP, exchange, MLB publisher, backend, decision, position, settlement, or bankroll authority changed.
