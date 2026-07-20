# ATLAS Private Tester Guide

## Safety

Use synthetic or non-sensitive data only. Do not upload customer, account, employee, transaction, or other regulated records into the private demo environment.

## Start Demo Mode

Open ATLAS with `?demo=1`, for example `http://127.0.0.1:5174/project-overview?demo=1`. The safety banner remains active in that browser until local site data is cleared or `atlas-private-demo-mode` is removed from local storage.

## Transportation Optimization Walkthrough

1. Open the completed Transportation / Logistics project.
2. Review the management summary on Project Overview.
3. Walk through all 14 optimization steps and confirm each status is understandable.
4. Inspect the solution, scenario, sensitivity, validation, recommendation, and implementation outputs.
5. On Documentation, capture remaining evidence, generate the Markdown report, inspect all 20 sections, and test each export.
6. Open Model Evidence Center and inspect optimization artifact references, timestamps, workflow steps, and source run references.

## Feedback

Select **Tester feedback** in the demo banner. Describe the page, action, expected result, and actual result. ATLAS stores the entry in the current browser and downloads a JSON record that can be sent through the tester's agreed secure feedback channel.

Do not include source data, access credentials, absolute local paths, or confidential business information in feedback.
