# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: dataset-library-action-parity.spec.ts >> Dataset Library: Card and Detailed View action parity >> the same authorized action set is reachable from both views
- Location: tests\e2e\dataset-library-action-parity.spec.ts:63:3

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: locator('body')
Timeout: 60000ms
Expected pattern: /Linked "CLASS_TRAIN" to the current project/i
Received string:  "
    HomeAtlas HomeProjectsNew ProjectOpen ProjectTemplatesManagementManagement DashboardModel / Decision RegistryValidation QueueMonitoring CenterModel Evidence CenterAudit LogShared with MeNotificationsData and AnalysisDataset LibrarySQL Data StudioAnalytics WorkbenchChart StudioNotebook StudioModel LifecycleModel DiagnosticsModel Documentation StudioCredit Risk StudioCurrent ProjectE2E Dataset Action Parity 1785181714386OverviewWorkflowProject ContextData AcquisitionEDAOutliersMissing ValuesFeature EngineeringBalance & SplitModel TrainingEvaluationInterpretationScoringDocumentation ReviewModel ImplementationModel MonitoringExperimentsDecision JournalGovernanceNotebookExportsAdministrationAccountUser AdministrationAdmin ConsoleSettingsSystem DiagnosticsATLAS/E2E Dataset Action Parity 1785181714386/Dataset LibraryLocal onlyDual-mode modelingGuided mode emphasizes visual workflow steps, recommended defaults, explanations, and guardrails.GuidedPower UserAtlas HomeContextTrainEvaluate0 of 14 steps0%NotificationsJamesDataset LibraryRegister governed datasets once, preserve versions and lineage, then link approved data assets to ATLAS projects.Signed in as James (data_scientist)Upload DatasetRegister MetadataRefreshAllTrainingTestOOTScored OutputsSQL ResultsRegressionClassificationUploadedMetadata-onlyLinked to Current ProjectUnlinkedAll OwnersJamesCard ViewDetailed ViewCLASS_TRAINNo description provided.uploadRows170,884Columns31Versions1Owner: JamesUpdated: 7/27/2026, 3:48:41 PMLatest version: v_1784989835930_982c7a7dOpenLink to ProjectSQLOpen in SQL Data StudioMore ActionsAtlas Guide RecommendationRule-based guide. LLM-ready interface.Rule-based - 2 detected conditionsModel ID00001-1785181714386ProjectE2E Dataset Action Parity 1785181714386PageWorkflowModeGuidedTaskgeneric classificationTargetNot selectedChallenge ModeChallenge risky modeling decisions.Recommended Next StepsComplete the project context firstDefine the required Model ID #, project name, business objective, intended use, target, population, costs, and governance environment before locking modeling choices.Why this matters: A regulated model cannot be evaluated only as a technical artifact; success metrics, thresholds, explainability, and documentation need to trace back to business use.Start by loading the development datasetNo active dataset is visible to the Copilot. Load a CSV and select the target before making preprocessing or modeling decisions.Why this matters: Every downstream recommendation depends on the target, sample size, feature schema, and target distribution.·········
"

Call log:
  - Expect "toContainText" with timeout 60000ms
  - waiting for locator('body')
    3 × locator resolved to <body>…</body>
      - unexpected value "
    HomeAtlas HomeProjectsNew ProjectOpen ProjectTemplatesManagementManagement DashboardModel / Decision RegistryValidation QueueMonitoring CenterModel Evidence CenterAudit LogShared with MeNotificationsData and AnalysisDataset LibrarySQL Data StudioAnalytics WorkbenchChart StudioNotebook StudioModel LifecycleModel DiagnosticsModel Documentation StudioCredit Risk StudioCurrent ProjectE2E Dataset Action Parity 1785181714386OverviewWorkflowProject ContextData AcquisitionEDAOutliersMissing ValuesFeature EngineeringBalance & SplitModel TrainingEvaluationInterpretationScoringDocumentation ReviewModel ImplementationModel MonitoringExperimentsDecision JournalGovernanceNotebookExportsAdministrationAccountUser AdministrationAdmin ConsoleSettingsSystem DiagnosticsATLAS/E2E Dataset Action Parity 1785181714386/Dataset LibraryLocal onlyDual-mode modelingGuided mode emphasizes visual workflow steps, recommended defaults, explanations, and guardrails.GuidedPower UserAtlas HomeContextTrainEvaluate0 of 14 steps0%NotificationsJamesDataset LibraryRegister governed datasets once, preserve versions and lineage, then link approved data assets to ATLAS projects.Signed in as James (data_scientist)Upload DatasetRegister MetadataRefreshAllTrainingTestOOTScored OutputsSQL ResultsRegressionClassificationUploadedMetadata-onlyLinked to Current ProjectUnlinkedAll OwnersJamesCard ViewDetailed ViewCLASS_TRAINNo description provided.uploadRows170,884Columns31Versions1Owner: JamesUpdated: 7/26/2026, 6:06:56 PMLatest version: v_1784989835930_982c7a7dOpenLink to ProjectSQLOpen in SQL Data StudioMore ActionsAtlas Guide RecommendationRule-based guide. LLM-ready interface.Rule-based - 2 detected conditionsModel ID00001-1785181714386ProjectE2E Dataset Action Parity 1785181714386PageWorkflowModeGuidedTaskgeneric classificationTargetNot selectedChallenge ModeChallenge risky modeling decisions.Recommended Next StepsComplete the project context firstDefine the required Model ID #, project name, business objective, intended use, target, population, costs, and governance environment before locking modeling choices.Why this matters: A regulated model cannot be evaluated only as a technical artifact; success metrics, thresholds, explainability, and documentation need to trace back to business use.Start by loading the development datasetNo active dataset is visible to the Copilot. Load a CSV and select the target before making preprocessing or modeling decisions.Why this matters: Every downstream recommendation depends on the target, sample size, feature schema, and target distribution.
    
  

"
    2 × locator resolved to <body>…</body>
      - unexpected value "
    HomeAtlas HomeProjectsNew ProjectOpen ProjectTemplatesManagementManagement DashboardModel / Decision RegistryValidation QueueMonitoring CenterModel Evidence CenterAudit LogShared with MeNotificationsData and AnalysisDataset LibrarySQL Data StudioAnalytics WorkbenchChart StudioNotebook StudioModel LifecycleModel DiagnosticsModel Documentation StudioCredit Risk StudioCurrent ProjectE2E Dataset Action Parity 1785181714386OverviewWorkflowProject ContextData AcquisitionEDAOutliersMissing ValuesFeature EngineeringBalance & SplitModel TrainingEvaluationInterpretationScoringDocumentation ReviewModel ImplementationModel MonitoringExperimentsDecision JournalGovernanceNotebookExportsAdministrationAccountUser AdministrationAdmin ConsoleSettingsSystem DiagnosticsATLAS/E2E Dataset Action Parity 1785181714386/Dataset LibraryLocal onlyDual-mode modelingGuided mode emphasizes visual workflow steps, recommended defaults, explanations, and guardrails.GuidedPower UserAtlas HomeContextTrainEvaluate0 of 14 steps0%NotificationsJamesDataset LibraryRegister governed datasets once, preserve versions and lineage, then link approved data assets to ATLAS projects.Signed in as James (data_scientist)Upload DatasetRegister MetadataRefreshAllTrainingTestOOTScored OutputsSQL ResultsRegressionClassificationUploadedMetadata-onlyLinked to Current ProjectUnlinkedAll OwnersJamesCard ViewDetailed ViewCLASS_TRAINNo description provided.uploadRows170,884Columns31Versions1Owner: JamesUpdated: 7/26/2026, 6:06:56 PMLatest version: v_1784989835930_982c7a7dOpenLink to ProjectSQLOpen in SQL Data StudioMore ActionsWorking...Atlas Guide RecommendationRule-based guide. LLM-ready interface.Rule-based - 2 detected conditionsModel ID00001-1785181714386ProjectE2E Dataset Action Parity 1785181714386PageWorkflowModeGuidedTaskgeneric classificationTargetNot selectedChallenge ModeChallenge risky modeling decisions.Recommended Next StepsComplete the project context firstDefine the required Model ID #, project name, business objective, intended use, target, population, costs, and governance environment before locking modeling choices.Why this matters: A regulated model cannot be evaluated only as a technical artifact; success metrics, thresholds, explainability, and documentation need to trace back to business use.Start by loading the development datasetNo active dataset is visible to the Copilot. Load a CSV and select the target before making preprocessing or modeling decisions.Why this matters: Every downstream recommendation depends on the target, sample size, feature schema, and target distribution.
    
  

"
    108 × locator resolved to <body>…</body>
        - unexpected value "
    HomeAtlas HomeProjectsNew ProjectOpen ProjectTemplatesManagementManagement DashboardModel / Decision RegistryValidation QueueMonitoring CenterModel Evidence CenterAudit LogShared with MeNotificationsData and AnalysisDataset LibrarySQL Data StudioAnalytics WorkbenchChart StudioNotebook StudioModel LifecycleModel DiagnosticsModel Documentation StudioCredit Risk StudioCurrent ProjectE2E Dataset Action Parity 1785181714386OverviewWorkflowProject ContextData AcquisitionEDAOutliersMissing ValuesFeature EngineeringBalance & SplitModel TrainingEvaluationInterpretationScoringDocumentation ReviewModel ImplementationModel MonitoringExperimentsDecision JournalGovernanceNotebookExportsAdministrationAccountUser AdministrationAdmin ConsoleSettingsSystem DiagnosticsATLAS/E2E Dataset Action Parity 1785181714386/Dataset LibraryLocal onlyDual-mode modelingGuided mode emphasizes visual workflow steps, recommended defaults, explanations, and guardrails.GuidedPower UserAtlas HomeContextTrainEvaluate0 of 14 steps0%NotificationsJamesDataset LibraryRegister governed datasets once, preserve versions and lineage, then link approved data assets to ATLAS projects.Signed in as James (data_scientist)Upload DatasetRegister MetadataRefreshAllTrainingTestOOTScored OutputsSQL ResultsRegressionClassificationUploadedMetadata-onlyLinked to Current ProjectUnlinkedAll OwnersJamesCard ViewDetailed ViewCLASS_TRAINNo description provided.uploadRows170,884Columns31Versions1Owner: JamesUpdated: 7/27/2026, 3:48:41 PMLatest version: v_1784989835930_982c7a7dOpenLink to ProjectSQLOpen in SQL Data StudioMore ActionsAtlas Guide RecommendationRule-based guide. LLM-ready interface.Rule-based - 2 detected conditionsModel ID00001-1785181714386ProjectE2E Dataset Action Parity 1785181714386PageWorkflowModeGuidedTaskgeneric classificationTargetNot selectedChallenge ModeChallenge risky modeling decisions.Recommended Next StepsComplete the project context firstDefine the required Model ID #, project name, business objective, intended use, target, population, costs, and governance environment before locking modeling choices.Why this matters: A regulated model cannot be evaluated only as a technical artifact; success metrics, thresholds, explainability, and documentation need to trace back to business use.Start by loading the development datasetNo active dataset is visible to the Copilot. Load a CSV and select the target before making preprocessing or modeling decisions.Why this matters: Every downstream recommendation depends on the target, sample size, feature schema, and target distribution.
    
  

"

```

```yaml
- complementary:
  - img "ATLAS logo"
  - button "Collapse navigation":
    - img
  - navigation:
    - text: Home
    - link "Atlas Home":
      - /url: /dashboard
      - img
      - text: Atlas Home
    - text: Projects
    - link "New Project":
      - /url: /projects/new
      - img
      - text: New Project
    - link "Open Project":
      - /url: /projects/open
      - img
      - text: Open Project
    - link "Templates":
      - /url: /templates
      - img
      - text: Templates
    - text: Management
    - link "Management Dashboard":
      - /url: /management-dashboard
      - img
      - text: Management Dashboard
    - link "Model / Decision Registry":
      - /url: /registry
      - img
      - text: Model / Decision Registry
    - link "Validation Queue":
      - /url: /validation
      - img
      - text: Validation Queue
    - link "Monitoring Center":
      - /url: /monitoring
      - img
      - text: Monitoring Center
    - link "Model Evidence Center":
      - /url: /model-evidence-center
      - img
      - text: Model Evidence Center
    - link "Audit Log":
      - /url: /audit
      - img
      - text: Audit Log
    - link "Shared with Me":
      - /url: /sharing
      - img
      - text: Shared with Me
    - link "Notifications":
      - /url: /notifications
      - img
      - text: Notifications
    - text: Data and Analysis
    - link "Dataset Library":
      - /url: /datasets
      - img
      - text: Dataset Library
    - link "SQL Data Studio":
      - /url: /sql-data-studio
      - img
      - text: SQL Data Studio
    - link "Analytics Workbench":
      - /url: /analytics
      - img
      - text: Analytics Workbench
    - link "Chart Studio":
      - /url: /chart-studio
      - img
      - text: Chart Studio
    - link "Notebook Studio":
      - /url: /notebook-studio
      - img
      - text: Notebook Studio
    - text: Model Lifecycle
    - link "Model Diagnostics":
      - /url: /model-diagnostics
      - img
      - text: Model Diagnostics
    - link "Model Documentation Studio":
      - /url: /model-document-studio
      - img
      - text: Model Documentation Studio
    - link "Credit Risk Studio":
      - /url: /credit-risk-studio
      - img
      - text: Credit Risk Studio
    - text: Current Project E2E Dataset Action Parity 1785181714386
    - link "Overview":
      - /url: /project-overview
      - img
      - text: Overview
    - button "Workflow":
      - img
      - img
      - text: Workflow
    - link "Project Context":
      - /url: /step00
    - link "Data Acquisition":
      - /url: /step01
    - link "EDA":
      - /url: /step02
    - link "Outliers":
      - /url: /step03
    - link "Missing Values":
      - /url: /step04
    - link "Feature Engineering":
      - /url: /step05
    - link "Balance & Split":
      - /url: /step06
    - link "Model Training":
      - /url: /step07
    - link "Evaluation":
      - /url: /step08
    - link "Interpretation":
      - /url: /step09
    - link "Scoring":
      - /url: /step10
    - link "Documentation Review":
      - /url: /step11
    - link "Model Implementation":
      - /url: /step12
    - link "Model Monitoring":
      - /url: /step13
    - link "Experiments":
      - /url: /experiments
      - img
      - text: Experiments
    - link "Decision Journal":
      - /url: /journal
      - img
      - text: Decision Journal
    - link "Governance":
      - /url: /governance-report
      - img
      - text: Governance
    - link "Notebook":
      - /url: /notebook-export
      - img
      - text: Notebook
    - link "Exports":
      - /url: /exports
      - img
      - text: Exports
    - text: Administration
    - link "Account":
      - /url: /account
      - img
      - text: Account
    - link "User Administration":
      - /url: /admin/users
      - img
      - text: User Administration
    - link "Admin Console":
      - /url: /admin
      - img
      - text: Admin Console
    - link "Settings":
      - /url: /settings
      - img
      - text: Settings
    - link "System Diagnostics":
      - /url: /system/diagnostics
      - img
      - text: System Diagnostics
- banner:
  - navigation "Breadcrumb":
    - list:
      - listitem:
        - link "ATLAS":
          - /url: /dashboard
      - listitem: E2E Dataset Action Parity 1785181714386
      - listitem: Dataset Library
  - img
  - text: Local only
  - img
  - text: Dual-mode modeling
  - button "Guided"
  - button "Power User":
    - img
    - text: Power User
  - text: 0 of 14 steps 0%
  - progressbar
  - link "Notifications":
    - /url: /notifications
  - button "James"
- main:
  - img "ATLAS logo"
  - img
  - heading "Dataset Library" [level=1]
  - paragraph: Register governed datasets once, preserve versions and lineage, then link approved data assets to ATLAS projects.
  - paragraph:
    - img
    - text: Signed in as James (data_scientist)
  - img
  - text: Upload Dataset
  - link "Register Metadata":
    - /url: /datasets/register
    - img
    - text: Register Metadata
  - button "Refresh":
    - img
    - text: Refresh
  - img
  - textbox:
    - /placeholder: Search by dataset, owner, source, linked project, or type
    - text: CLASS_TRAIN
  - combobox:
    - option "All" [selected]
    - option "Training"
    - option "Test"
    - option "OOT"
    - option "Scored Outputs"
    - option "SQL Results"
    - option "Regression"
    - option "Classification"
    - option "Uploaded"
    - option "Metadata-only"
    - option "Linked to Current Project"
    - option "Unlinked"
  - combobox:
    - option "All Owners" [selected]
    - option "James"
  - button "Card View"
  - button "Detailed View":
    - img
    - text: Detailed View
  - article:
    - 'link "CLASS_TRAIN No description provided. upload Rows 170,884 Columns 31 Versions 1 Owner: James Updated: 7/27/2026, 3:48:41 PM Latest version: v_1784989835930_982c7a7d"':
      - /url: /datasets/ds_class_train_982c7a7d_35930
      - heading "CLASS_TRAIN" [level=2]
      - paragraph: No description provided.
      - text: "upload Rows 170,884 Columns 31 Versions 1 Owner: James Updated: 7/27/2026, 3:48:41 PM Latest version: v_1784989835930_982c7a7d"
    - link "Open CLASS_TRAIN":
      - /url: /datasets/ds_class_train_982c7a7d_35930
      - text: Open
    - button "Link CLASS_TRAIN to the current project": Link to Project
    - link "Open CLASS_TRAIN in SQL Data Studio":
      - /url: /sql-data-studio?datasetId=ds_class_train_982c7a7d_35930
      - text: Open in SQL Data Studio
    - button "More actions for CLASS_TRAIN": More Actions
  - complementary:
    - button "Compact ATLAS Guide":
      - img
    - complementary:
      - img
      - heading "Atlas Guide Recommendation" [level=2]
      - paragraph: Rule-based guide. LLM-ready interface.
      - text: Rule-based - 2 detected conditions Model ID 00001-1785181714386 Project E2E Dataset Action Parity 1785181714386 Page Workflow Mode Guided Task generic classification Target Not selected Challenge Mode Challenge risky modeling decisions.
      - checkbox "Challenge Mode Challenge risky modeling decisions."
      - heading "Recommended Next Steps" [level=3]
      - article:
        - img
        - text: Complete the project context first
        - paragraph: "Define the required Model ID #, project name, business objective, intended use, target, population, costs, and governance environment before locking modeling choices."
        - paragraph: "Why this matters: A regulated model cannot be evaluated only as a technical artifact; success metrics, thresholds, explainability, and documentation need to trace back to business use."
      - article:
        - img
        - text: Start by loading the development dataset
        - paragraph: No active dataset is visible to the Copilot. Load a CSV and select the target before making preprocessing or modeling decisions.
        - paragraph: "Why this matters: Every downstream recommendation depends on the target, sample size, feature schema, and target distribution."
```

# Test source

```ts
  92  |     const detailedIds = await renderedActionIds(page, `dataset-row-actions-${DATASET_ID}`);
  93  |     console.log("DETAILED_VIEW_ACTIONS:", JSON.stringify(detailedIds));
  94  |     for (const id of ALL_ACTION_IDS) {
  95  |       expect(detailedIds, `Detailed View is missing ${id}`).toContain(id);
  96  |     }
  97  |     await shot(page, testInfo, "parity-01-detailed-view-actions");
  98  | 
  99  |     // ---------- 5-6. Card View: the SAME ids, directly or via More Actions ----
  100 |     await page.getByRole("button", { name: "Card View" }).click();
  101 |     const cardPrimaryIds = await renderedActionIds(page, `dataset-card-actions-${DATASET_ID}`);
  102 |     console.log("CARD_VIEW_PRIMARY_ACTIONS:", JSON.stringify(cardPrimaryIds));
  103 |     expect(cardPrimaryIds).toEqual(expect.arrayContaining(["open", "link-project", "sql-studio"]));
  104 |     await shot(page, testInfo, "parity-02-card-view-primary-actions");
  105 | 
  106 |     // Search text must survive the view switch.
  107 |     await expect(search).toHaveValue("CLASS_TRAIN");
  108 | 
  109 |     const card = page.getByTestId(`dataset-card-actions-${DATASET_ID}`);
  110 |     const moreTrigger = card.getByTestId("dataset-more-actions-trigger");
  111 |     await expect(moreTrigger).toBeVisible();
  112 | 
  113 |     // Keyboard opening: focus the trigger and press Enter.
  114 |     await moreTrigger.focus();
  115 |     await page.keyboard.press("Enter");
  116 |     const menu = page.getByTestId("dataset-more-actions-menu");
  117 |     await expect(menu).toBeVisible();
  118 |     await expect(moreTrigger).toHaveAttribute("aria-expanded", "true");
  119 |     const overflowIds = await menu.locator("[data-dataset-action]").evaluateAll((nodes) =>
  120 |       nodes.map((node) => node.getAttribute("data-dataset-action") || ""),
  121 |     );
  122 |     console.log("CARD_VIEW_OVERFLOW_ACTIONS:", JSON.stringify(overflowIds));
  123 |     await shot(page, testInfo, "parity-03-card-view-more-actions-menu");
  124 | 
  125 |     // Arrow-key navigation moves focus inside the menu.
  126 |     await page.keyboard.press("ArrowDown");
  127 |     await expect(menu.locator(":focus")).toHaveCount(1);
  128 | 
  129 |     // Escape closes and returns focus to the trigger.
  130 |     await page.keyboard.press("Escape");
  131 |     await expect(menu).toBeHidden();
  132 |     await expect(moreTrigger).toBeFocused();
  133 | 
  134 |     // ---------- 6. PARITY ASSERTION ------------------------------------------
  135 |     const cardAll = [...cardPrimaryIds.filter((id) => id !== ""), ...overflowIds].filter(
  136 |       (id, index, list) => id && list.indexOf(id) === index,
  137 |     );
  138 |     expect(
  139 |       cardAll.slice().sort(),
  140 |       "Card View and Detailed View must expose the same action ids",
  141 |     ).toEqual(detailedIds.slice().sort());
  142 | 
  143 |     // ---------- 7. SQL Studio from Card View carries the dataset identity ----
  144 |     await page.getByTestId(`dataset-card-actions-${DATASET_ID}`).locator('[data-dataset-action="sql-studio"]').click();
  145 |     await expect(page).toHaveURL(new RegExp(`/sql-data-studio\\?datasetId=${DATASET_ID}`), { timeout: 60_000 });
  146 |     console.log("SQL_STUDIO_URL_FROM_CARD:", page.url());
  147 | 
  148 |     // ---------- 8. Link to Project: verify the TRUTHFUL authorized state ----
  149 |     //
  150 |     // The first credentialed run failed here for a real reason: the signed-in
  151 |     // user's current project was "Untitled ATLAS Project", which the backend
  152 |     // refuses with "You do not have access to link datasets to this project."
  153 |     // The action was offered anyway. It is now disabled with that exact reason.
  154 |     //
  155 |     // To exercise the SUCCESS path honestly, create a project through normal
  156 |     // product behaviour so the signed-in user owns it -- never by bypassing
  157 |     // authorization.
  158 |     await createPredictiveModelingProject(page, {
  159 |       name: `E2E Dataset Action Parity ${Date.now()}`,
  160 |       modelId: `00001-${Date.now()}`,
  161 |     });
  162 | 
  163 |     await page.goto("/datasets");
  164 |     await page.getByPlaceholder(/Search by dataset/i).fill("CLASS_TRAIN");
  165 | 
  166 |     // Detailed View state for the same action, for the cross-view comparison.
  167 |     await page.getByRole("button", { name: "Detailed View" }).click();
  168 |     const detailedLink = page
  169 |       .getByTestId(`dataset-row-actions-${DATASET_ID}`)
  170 |       .locator('[data-dataset-action="link-project"]');
  171 |     await expect(detailedLink).toBeVisible({ timeout: 30_000 });
  172 |     const detailedEnabled = await detailedLink.getAttribute("data-action-enabled");
  173 |     const detailedReason = await detailedLink.getAttribute("data-disabled-reason");
  174 | 
  175 |     await page.getByRole("button", { name: "Card View" }).click();
  176 |     const linkAction = page
  177 |       .getByTestId(`dataset-card-actions-${DATASET_ID}`)
  178 |       .locator('[data-dataset-action="link-project"]');
  179 |     await expect(linkAction).toBeVisible();
  180 |     const cardEnabled = await linkAction.getAttribute("data-action-enabled");
  181 |     const cardReason = await linkAction.getAttribute("data-disabled-reason");
  182 |     console.log("LINK_TO_PROJECT_STATE:", JSON.stringify({ detailedEnabled, cardEnabled, detailedReason, cardReason }));
  183 | 
  184 |     // Both views must agree on enabled state AND on the reason.
  185 |     expect(cardEnabled, "Link to Project enabled state must match across views").toBe(detailedEnabled);
  186 |     expect(cardReason, "Link to Project disabled reason must match across views").toBe(detailedReason);
  187 | 
  188 |     if (cardEnabled === "true") {
  189 |       // Authorized: the link must actually succeed.
  190 |       expect(cardReason).toBeNull();
  191 |       await linkAction.click();
> 192 |       await expect(page.locator("body")).toContainText(/Linked "CLASS_TRAIN" to the current project/i, {
      |                                          ^ Error: expect(locator).toContainText(expected) failed
  193 |         timeout: 60_000,
  194 |       });
  195 |     } else {
  196 |       // Unauthorized: the action must state the server's real reason, and must
  197 |       // never silently fail after being offered.
  198 |       expect(cardReason, "a disabled Link to Project must explain why").toBeTruthy();
  199 |       expect(cardReason).toBe("You do not have access to link datasets to this project.");
  200 |     }
  201 | 
  202 |     // ---------- 9. No uncaught page errors caused by this phase --------------
  203 |     console.log("PARITY_FAILED_RESPONSES:", JSON.stringify(log.failedResponses));
  204 |     expect(log.pageErrors, `uncaught page errors: ${log.pageErrors.join(" | ")}`).toEqual([]);
  205 | 
  206 |     await dump();
  207 |   });
  208 | });
  209 | 
```