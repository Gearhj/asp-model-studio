# Activation handoff

Status: source complete and deployment staged; installation did not execute.

- Branch: `codex/nfl-personnel-prospective-capture-v1`
- Final source commit: use the branch head reported by Git after this evidence commit.
- Final deployment identity: `cbf3686a0c8ceb22dd135b5af9f3fb4738a8114a2e7ac969712992292404d20d`
- Final staged path: `C:\Users\james\asp-model-studio\.deployments\nfl-personnel-capture\cbf3686a0c8ceb22dd135b5af9f3fb4738a8114a2e7ac969712992292404d20d`
- Intended task: `ASP NFL Personnel Evidence Capture`
- Intended raw root: `C:\Users\james\asp-data-staging\nfl\personnel-captures-v1`
- Intended runtime root: `C:\Users\james\asp-model-studio\.runtime\nfl-personnel-capture`

The supported sequence remains builder, installer `Plan`, installer `Install`, explicit initial capture, and natural task observation. Do not install either predecessor deployment and do not create or manually register a task outside the installer.

The automatic approval review must see a direct visible authorization for the exact recurring S4U task and its bounded external requests. No approval or implementation work is needed from AISP.

Post-install incident: deployment `cbf3686a0c8ceb22dd135b5af9f3fb4738a8114a2e7ac969712992292404d20d` failed at package import before any provider request. The corrected successor identity is `3139cff08216d9e16fcaa5d012a23738605e14f66c3fffc4687f73ecda7f7dcf`; it uses a minimal isolated package initializer and passed 15 focused tests. Do not patch the predecessor bytes. Obtain direct authorization to replace its task binding with this successor, then rerun the initial capture and observe a later natural invocation.

Deployment `3139cff08216d9e16fcaa5d012a23738605e14f66c3fffc4687f73ecda7f7dcf` completed the initial capture, and its natural Python run returned `NOT_DUE`, but its wrapper used a .NET API absent from Windows PowerShell 5.1 and returned 1 while hashing the launcher receipt. A further immutable successor uses `SHA256.Create().ComputeHash`. Rebind only after its exact identity is reviewed and directly authorized.

## Final activation

James directly authorized deployment `da85acc26f5ce0e0edbe2c5a81ffeca318d9a868a243d071b0d5e8bc1067e422`. The supported installer replaced the one canonical task binding on September 17, 2026. The runtime deployment record and task action both bind that exact deployment. The task remained S4U, Limited, `IgnoreNew`, and scheduled every fifteen minutes with a fifteen-minute execution limit.

The first natural successor invocation began at `2026-09-17T16:29:51.0529147Z` and completed at `2026-09-17T16:29:54.7754825Z`. Python returned `NOT_DUE` with exit code 0. The PowerShell wrapper returned 0, Task Scheduler reported result 0, and immutable launcher receipt `e591afdd687028c8425eeff089cd9147d00b0d84b17c1cc80613087246479bf1` was written. The run made zero provider requests and zero AISP or exchange writes.

The authorized initial capture was not repeated. Capture receipt `f28188339ebef3f7ac31a7288f1b654f975695d4e36c9b6a6342ecad73d6f3f6`, projection `b824635535ab09af0347d02265f6478541e8177e69dc80174a3d5984ef100957`, and six raw objects remain the sole retained capture population. The immutable `3139cff...dcf` deployment remains available as audit history. Do not use it as the current binding because its Windows PowerShell 5.1 wrapper cannot produce a launcher receipt.

The machine-readable closeout is `ACTIVATION_RECEIPT.json`. No forecast, model, AISP, exchange, MLB publisher, backend, decision, position, settlement, or bankroll authority changed.
