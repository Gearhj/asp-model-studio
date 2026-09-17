# Installation plan

- Task: `ASP NFL Personnel Evidence Capture`
- Marker: `ASP_NFL_PERSONNEL_EVIDENCE_OWNER_V1`
- Principal: current Windows user, S4U, least privilege (`Limited`)
- Overlap: Task Scheduler `IgnoreNew` plus an atomic runtime lock
- Tick: every 15 minutes; the runner spends network budget only at admitted slots
- Capture slots: Monday/Tuesday 15:15 ET; Wednesday-Sunday 07:15, 11:15, 15:15 ET
- Runtime ceiling: 15 minutes
- Network ceiling: six requests/capture, 28 requests/UTC day, zero retries
- Bytes/storage: 64 MiB/capture, 2 GiB retained
- State: `C:\Users\james\asp-model-studio\.runtime\nfl-personnel-capture`
- Raw evidence: `C:\Users\james\asp-data-staging\nfl\personnel-captures-v1`
- Schedule: registered local Foundation, outcome-free column projection

The installer has `Plan` and `Install` modes. `Plan` performs deployment verification and emits intended state without changing the machine. `Install` writes the nonsecret local rights acknowledgement, registers or replaces exactly the canonical task, writes the runtime deployment manifest, and verifies S4U, Limited, IgnoreNew, action binding, and owner count. If verification fails and no prior task existed, it removes the new task and restores the previous runtime files.

This task is separate from `ASP MLB V18 Research Publisher` and `ASP Backend 8010`. Neither is modified.
