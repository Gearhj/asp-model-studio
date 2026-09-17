# Activation handoff

Status: source complete and deployment staged; installation did not execute.

- Branch: `codex/nfl-personnel-prospective-capture-v1`
- Reviewed implementation commit: `eead5f9dc8cbb9520e72ae7e4509ccf8f7794b11`
- Staged deployment: `C:\Users\james\asp-model-studio\.deployments\nfl-personnel-capture\279158e2223925bc3083289bf048656dc9a45b6db783e6f6afa757bfbbf4ccff`
- Deployment manifest SHA-256: `0ec6a1d4329304fb5c3b83568d980825c219f23c1c5e816acf35d6b12a53afe9`
- Intended task: `ASP NFL Personnel Evidence Capture`
- Intended raw root: `C:\Users\james\asp-data-staging\nfl\personnel-captures-v1`
- Intended runtime root: `C:\Users\james\asp-model-studio\.runtime\nfl-personnel-capture`

Because the schedule was refined after the first deployment build to three daily capture slots, rebuild from the final clean branch commit before installation. Do not install the predecessor deployment. The supported sequence remains builder, installer `Plan`, installer `Install`, explicit initial capture, and natural task observation. Do not create or manually register a task outside the installer.

The automatic approval review must see a direct visible authorization for the exact recurring S4U task and its bounded external requests. No approval or implementation work is needed from AISP.
