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
