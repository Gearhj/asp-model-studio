# ATLAS Monitoring & Production Control Center Report

## 1. Scope
Implemented a governed Monitoring & Production Control Center for persisted ATLAS analytical assets. The build adds production monitoring persistence, APIs, portfolio UI, plan detail UI, registry integration, project overview integration, management dashboard rollups, tests, and clean-copy sync readiness.

## 2. Outcome
ATLAS now has a first-class monitoring layer for production performance, data drift, decision stability, alerts, remediation actions, evidence capture, documentation mapping, sharing, and revalidation triggers.

## 3. Backend Persistence
Added migration `0008_monitoring_production_control.sql` with:
- `monitoring_plans`
- `monitoring_metrics`
- `monitoring_runs`
- `monitoring_observations`
- `monitoring_alerts`
- `monitoring_actions`
- `monitoring_baselines`
- `monitoring_events`

The migration includes indexes for project, plan, status, owner, alert, observation, run, and event queries.

## 4. Repository Layer
Added `MonitoringRepository` and registered it in `PersistenceService`.

Repository coverage includes plans, metrics, runs, observations, alerts, actions, baselines, events, and project-level lookups.

## 5. Monitoring Templates
Added default monitoring templates for:
- Predictive Modeling
- Credit Risk
- Optimization
- Time Series Forecasting
- LLM / Generative AI
- Experimentation
- Generic workflow assets

Templates include governed metrics such as AUC, PR-AUC, KS, PSI, VSI, approval rate, adverse impact ratio, objective value, constraint breaches, MAPE, WAPE, hallucination rate, citation accuracy, conversion rate, guardrail breaches, and evidence completeness.

## 6. API Layer
Added `/api/monitoring` endpoints for:
- Portfolio summary
- Plan create/list/detail/update
- Project plan create/detail
- Plan activate/pause/retire
- Metric create/update/delete/seed
- Run create/start/complete/fail
- Observation list/create
- Alert create/update/acknowledge/resolve/accept-risk/close
- Revalidation review trigger
- Action create/update/complete
- Baseline create
- Template list/detail
- Project events

## 7. Security
Monitoring endpoints use the existing `require_user` dependency. Service methods enforce role gates for owner and validation-style actions.

## 8. Audit And Evidence
Monitoring actions write to:
- `audit_log`
- `monitoring_events`
- `evidence_artifacts`
- `notifications`
- `decision_journal` for accepted risk and revalidation review triggers

## 9. No Fake Production Data
The UI does not fabricate production monitoring observations. The “Run Monitoring” action creates and starts a governed run. Observations must be recorded through persisted metric observation endpoints or future production ingestion.

## 10. Monitoring Center UI
Added `MonitoringCenter.tsx` with:
- Dark command-center hero
- Portfolio KPI cards
- Plan status distribution
- Alert severity distribution
- Workflow breach distribution
- Recent activity
- Filterable plan table
- Open alert queue
- Empty states for no monitoring plans

## 11. Monitoring Plan Detail UI
Added `MonitoringPlanDetail.tsx` with:
- Plan hero and owner/status/cadence facts
- Activate, pause, retire, seed metrics, run monitoring, share, and export actions
- Governed metric threshold table
- Latest run summary
- Trend visuals based on persisted observations
- Observation table
- Alert actions
- Remediation action list
- Evidence and documentation mapping

## 12. Project Overview Integration
Project Overview now shows a Production Monitoring card with:
- Create monitoring plan
- Open monitoring plan
- Start monitoring run
- Plan status, owner, cadence, last run, next run, alerts, metrics

## 13. Registry Integration
Registry assets now expose monitoring rollups:
- Monitoring status
- Open monitoring alerts
- Last monitoring run
- Next monitoring due

The backend registry service derives these fields from persisted monitoring plans, runs, and alerts.

## 14. Registry Asset Detail Integration
Registry Asset Detail now includes a production control section that can create or open the monitoring plan and summarize plan status, cadence, owner, open alerts, and next run.

## 15. Management Dashboard Integration
Management Dashboard now includes production monitoring metrics:
- Assets under monitoring
- Missing monitoring plans
- Open monitoring alerts
- Monitoring runs
- Revalidation triggers

## 16. Navigation
Added Monitoring Center to the Management sidebar group and registered routes:
- `/monitoring`
- `/monitoring/:monitoringPlanId`
- `/project-monitoring/:projectId`

## 17. Sharing
Monitoring plans are shareable through the existing governed sharing dialog as resource type `monitoring_plan`.

## 18. Export
Monitoring Plan Detail supports exports for:
- Monitoring package JSON
- Observations CSV
- Alerts CSV

## 19. Revalidation Trigger
Monitoring alerts can create a revalidation review action and decision journal record. Direct validation-case linking is intentionally left as a future extension when a validation case exists.

## 20. Visual Design
The Monitoring Center and plan detail pages follow the current ATLAS command-center styling with dark headers, light operational panels, compact management KPIs, and status-coded cards.

## 21. Regression Tests Added
Added:
- `tests/monitoringCenter.test.mjs`
- `tests/monitoring_backend_test.py`
- `npm run test:monitoring-center`

## 22. Validation Results
Passed:
- `npx tsc -b`
- `npm run test:monitoring-center`
- `npm run test:registry-dashboard`
- `npm run test:validation-center`
- `npm run test:admin-sharing`
- `npm run test:sqlite-persistence`
- `npm run test:regression`
- `npm run test:persistence`
- `npm run build`

## 23. Build Notes
The Vite build completed successfully. Existing chunk-size and browserslist warnings remain informational and are not introduced by this monitoring work.

## 24. Known Follow-Up
Manual browser QA should verify:
- Monitoring Center route loads with persisted data.
- Project Overview can create a plan.
- Registry Asset Detail can create and open a plan.
- Monitoring Plan Detail can seed metrics, start a run, share the plan, export reports, and handle alerts.

## 25. Acceptance Position
The Monitoring & Production Control Center is implemented as a governed persistence-backed ATLAS module and is ready for manual acceptance testing.

Clean-copy sync was completed with `npm run sync:atlas` after an elevated rerun. Robocopy returned code 3, indicating files were copied and extra destination files were detected.
