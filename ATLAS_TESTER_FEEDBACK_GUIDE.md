# ATLAS Private Tester Feedback Guide

## What ATLAS Is

ATLAS is a local enterprise data science, AI/ML, decision intelligence, optimization, evidence, governance, and documentation platform. This private build is intended for trusted data science testers to evaluate real workflows, analytical controls, traceability, and usability.

## Data Safety

Use synthetic or non-sensitive data only. Do not upload customer data, account data, personal information, confidential model inputs, credentials, or regulated production artifacts.

## Suggested Test Paths

1. Create and reopen a Predictive Modeling project.
2. Complete a Transportation / Logistics Optimization project using the registered input bundle.
3. Review an Experimental Design or A/B Testing workflow from context through documentation.
4. Inspect Dataset Library lineage and project links.
5. Capture evidence, review Project Overview readiness, and open Model Evidence Center.
6. Generate a documentation package, export an artifact, and inspect Decision Journal history.
7. Refresh the browser, restart ATLAS, and confirm the project reopens from the ATLAS database.

## Feedback Questions

- What were you trying to accomplish?
- Which route, project, workflow, and step were active?
- What did you expect to happen?
- What actually happened?
- Could you recover without restarting or losing work?
- Was the evidence or decision trail understandable?
- Which control, table, chart, label, or message caused uncertainty?
- How severe is the issue: low, medium, high, or blocking?

Use the **Tester feedback** control in the private demo banner. ATLAS records route, project, workflow, step, user, issue type, severity, expected behavior, actual behavior, notes, and timestamp in SQLite. If the backend is unavailable, the browser keeps a local fallback submission.

## Known Limitations

- This is a local private demo, not a production deployment.
- Browser-generated exports are tracked as `client_generated`; they do not claim a server file path.
- Large regulated source artifacts are intentionally not stored in browser snapshots.
- Some analytical libraries and optional algorithms depend on the local Python environment.
- Hosted identity, enterprise SSO, remote object storage, and production secret management are outside this local test build.

## Reporting Outside ATLAS

Include the route, project ID, workflow type, step ID, timestamp, issue severity, expected result, actual result, and a screenshot when useful. Never include sensitive source data in screenshots or notes.
