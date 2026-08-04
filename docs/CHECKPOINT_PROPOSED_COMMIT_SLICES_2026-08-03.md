# ATLAS controlled-checkpoint proposed commit slices

Date: 2026-08-03  
Status: proposal only; no command in this document was executed

## Safety contract

- These manifests cover the 175 source, migration, reusable-test, and report paths present in the protected pre-audit working-tree baseline.
- They deliberately exclude all 46 runtime-authority, Dataset Library authority, evidence/MDD, browser-audit, and generated-test paths listed in `CHECKPOINT_NEVER_STAGE_MANIFEST_2026-08-03.md`.
- Never replace an exact manifest with `git add .`, `git add -A`, or `git add -u`.
- Each slice requires human diff review and the listed prerequisite gates before staging. The current checkpoint verdict is blocking, so none of these slices is approved for staging yet.

## Dependency order

```text
S1 governed authority and migrations
  -> S2 project-scoped routing and context
       -> S3 Data Acquisition UX and reproducibility
            -> S4 EDA development scope and Target Intelligence
       -> S5 validation design and training lineage

S5 functional acceptance also requires S3 and S4 to be green.
```

The current persistence package imports the Analysis Partition, predictor-authorization, and special-value repositories together. Dataset activation and invalidation consumers depend on the same authority layer. Consequently migrations 0024-0027 and those repositories cannot safely be split into independently staged intermediate states.

## S1 — governed identity and Analysis Partition authority

Prerequisites: security/storage-isolation foundation; fresh/upgrade/idempotent migration checks; database-integrity review.  
Current gate: blocked by the non-atomic migration-runner finding.

```bash
git add -- \
  scripts/run_security_tests.py \
  server/core/metadata_router.py \
  server/datasets/dataset_identity.py \
  server/main.py \
  server/persistence/repositories/__init__.py \
  server/persistence/repositories/holdout_governance_repository.py \
  server/persistence/repositories/model_registry_repository.py \
  server/persistence/repositories/project_dataset_activation_repository.py \
  server/persistence/repositories/analysis_partition_repository.py \
  server/persistence/repositories/predictor_authorization_repository.py \
  server/persistence/repositories/special_value_review_repository.py \
  server/persistence/service.py \
  server/analysis_partition/__init__.py \
  server/analysis_partition/router.py \
  server/analysis_partition/service.py \
  server/analysis_partition/types.py \
  server/persistence/migrations/0024_analysis_partitions.sql \
  server/persistence/migrations/0025_analysis_partition_product_completion.sql \
  server/persistence/migrations/0026_analysis_partition_reset_coordination.sql \
  server/persistence/migrations/0027_special_value_reviews.sql \
  server/preprocessing/bureau_detection_router.py \
  server/preprocessing/bureau_detection_service.py \
  server/preprocessing/bureau_detection_types.py \
  server/preprocessing/predictor_authorization.py \
  server/preprocessing/special_value_review_service.py \
  tests/activation_runtime_revision_consistency_test.py \
  tests/canonical_dataset_identity_test.py \
  tests/datasetLibrary.test.mjs \
  tests/model_registry_test.py \
  tests/pretraining_artifact_invalidation_test.py \
  tests/project_dataset_activation_persistence_test.py \
  tests/userManagement.test.mjs \
  tests/analysis_partition_contract_test.py \
  tests/analysis_partition_documentation_gate_test.py \
  tests/analysis_partition_fixture.py \
  tests/analysis_partition_legacy_compatibility_test.py \
  tests/analysis_partition_product_completion_test.py \
  tests/analysis_partition_product_matrix_test.py \
  tests/analysis_partition_validation_reuse_test.py \
  tests/predictor_authorization_contract_test.py \
  tests/special_value_review_contract_test.py \
  tests/bureau_detection_exact_binding_test.py \
  docs/ANALYSIS_PARTITION_PRODUCT_COMPLETION_REPORT_2026-08-03.md
```

Count: 43 paths.

## S2 — project-scoped routing and authoritative Project Context

Depends on: S1.  
Reason: the route helper must ship with every changed consumer so no intermediate commit mixes project-scoped and legacy navigation.

```bash
git add -- \
  src/apps/ModelingApp.tsx \
  src/components/CopilotCard.tsx \
  src/components/ModeSwitcher.tsx \
  src/components/PredictiveIdentityProvider.tsx \
  src/components/Sidebar.tsx \
  src/components/StepShell.tsx \
  src/lib/breadcrumbs.ts \
  src/lib/localProjects.ts \
  src/lib/modelDevelopmentDocument.ts \
  src/lib/projectContext.ts \
  src/lib/projectContextPersistence.ts \
  src/lib/serverPersistence.ts \
  src/lib/useProjectContextAutosave.ts \
  src/lib/authReturnPath.ts \
  src/lib/authoritativeProjectContext.ts \
  src/lib/projectContextMetadata.ts \
  src/lib/projectScopedRoutes.ts \
  src/state/useWorkflowStore.ts \
  src/steps/AuthPages.tsx \
  src/steps/CreditRiskStudio.tsx \
  src/steps/Dashboard.tsx \
  src/steps/IntelligentWorkbench.tsx \
  src/steps/ModelDiagnostics.tsx \
  src/steps/ModelDocumentationStudio.tsx \
  src/steps/NewProject.tsx \
  src/steps/NotebookExport.tsx \
  src/steps/ProjectOverview.tsx \
  src/steps/ProjectUtilityPages.tsx \
  src/steps/Step00_ProjectContext.tsx \
  src/steps/Step04_Outliers.tsx \
  src/steps/Step06_Train.tsx \
  src/steps/Step08_Evaluation.tsx \
  src/steps/Step10_Scoring.tsx \
  src/steps/Step11_ModelDevelopmentDocument.tsx \
  tests/e2e/open-project-registry.spec.ts \
  tests/e2e/predictive-identity-readiness.spec.ts \
  tests/e2e/predictive-route-integrity-matrix.spec.ts \
  tests/e2e/project-context-backend-restart.integration.ts \
  tests/e2e/project-context-backend-restart.playwright.config.ts \
  tests/e2e/project-context-backend-restart.vite.config.ts \
  tests/e2e/project-context-hydration.spec.ts \
  tests/e2e/project-context-stability-soak.spec.ts \
  tests/e2e/project-scoped-composition-lifecycle.spec.ts \
  tests/openProjectRoute.test.mjs \
  tests/predictiveIdentityReadiness.test.mjs \
  tests/predictiveModelingCommandCenter.test.mjs \
  tests/predictiveModelingRepair.test.mjs \
  tests/projectContextPersistence.test.mjs \
  tests/regression.test.mjs \
  tests/authReturnPath.test.mjs \
  tests/authoritativeProjectContext.test.mjs \
  tests/projectContextMetadata.test.mjs \
  tests/projectScopedPredictiveNavigation.test.mjs \
  tests/projectScopedRoutes.test.mjs \
  tests/project_context_backend_restart_soak_test.py \
  tests/project_context_browser_restart_integration_test.py \
  tests/project_context_hydration_authority_test.py \
  docs/PROJECT_CONTEXT_P0_OVERNIGHT_REPORT_2026-08-03.md
```

Count: 58 paths.

## S3 — Data Acquisition UX and reproducibility

Depends on: S1 and S2.  
Reason: the page consumes the governed activation, target, predictor, and Analysis Partition contracts established upstream.

```bash
git add -- \
  package.json \
  src/components/BureauReviewPanel.tsx \
  src/components/StepPythonPanel.tsx \
  src/components/code/CodeLanguageTabs.tsx \
  src/components/code/CodeWorkspacePanel.tsx \
  src/components/dataAcquisition/DatasetLoadProgressPanel.tsx \
  src/components/dataAcquisition/DataAcquisitionSectionNav.tsx \
  src/lib/bureauDetection.ts \
  src/lib/notebookExport.ts \
  src/lib/dataAcquisitionReproducibility.ts \
  src/steps/Step01_DataAcquisition.tsx \
  tests/codeWorkspaceUx.test.mjs \
  tests/dataAcquisition.test.mjs \
  tests/dataAcquisitionStatus.test.mjs \
  tests/dataAcquisitionUx.test.mjs \
  tests/dataAcquisitionValidationSimplification.test.mjs \
  tests/data_acquisition_validation_simplification_test.py \
  tests/analysisPartitionProductCompletionFrontend.test.mjs \
  tests/analysisPartitionResetUxContract.test.mjs \
  tests/bureauDetectionExactBinding.test.mjs \
  tests/dataAcquisitionReproducibility.test.mjs \
  tests/dataAcquisitionUxRefinement.test.mjs \
  tests/data_acquisition_reproducibility_context_test.py \
  docs/DATA_ACQUISITION_INFORMATION_ARCHITECTURE_REPORT_2026-08-03.md
```

Count: 24 paths.

## S4 — EDA development scope and Target Intelligence

Depends on: S1, S2, and S3.  
Current gate: blocked by full-population target-directed preprocessing findings that must be resolved before a checkpoint is approved.

```bash
git add -- \
  server/analytics/analysis_scope.py \
  server/analytics/target_intelligence_router.py \
  server/eda/analytical_contract.py \
  server/eda/documentation_service.py \
  server/eda/eda_router.py \
  server/eda/workspace_service.py \
  src/components/documentation/EdaDocumentationLiveLink.tsx \
  src/components/eda/TargetIntelligenceWorkspace.tsx \
  src/components/eda/TargetVisualInsights.tsx \
  src/components/ui/AtlasWorkflow.tsx \
  src/lib/edaDocumentationApi.ts \
  src/lib/targetIntelligence.ts \
  src/lib/targetIntelligenceApi.ts \
  src/lib/workflowSafety.ts \
  src/lib/dataScope.ts \
  src/lib/edaWorkspaceReadiness.ts \
  src/steps/Step02_EDA.tsx \
  tests/analysisScope.test.mjs \
  tests/analysis_scope_test.py \
  tests/edaAnalyticalScopeLabels.test.mjs \
  tests/edaWorkspaceNavigation.test.mjs \
  tests/eda_governed_analytical_contract_test.py \
  tests/eda_phase1_predictor_authorization_test.py \
  tests/eda_predictor_visual_contract_test.py \
  tests/evidenceCanonicalIdentity.test.mjs \
  tests/targetIntelligence.test.mjs \
  tests/target_intelligence_test.py \
  tests/edaEntryReadinessContract.test.mjs \
  tests/edaPartialReadinessFrontend.test.mjs \
  tests/eda_http_transport_contract_test.py \
  tests/target_intelligence_partition_evidence_test.py \
  tests/e2e/eda-project-scoped-entry.spec.ts
```

Count: 32 paths.

## S5 — Validation Design and training lineage

Depends on: S1 and S2 for compilation; S3 and S4 for functional acceptance.  
Reason: browser validation drafts do not own row membership. The exact Analysis Partition owns the development/final-holdout boundary, and fold-local execution must carry that identity into candidate lineage.

```bash
git add -- \
  server/splitting/split_router.py \
  server/splitting/split_service.py \
  server/training/candidate_contract.py \
  server/training/trainer.py \
  server/training/trainer_router.py \
  server/training/training_job_service.py \
  server/training/training_preflight_service.py \
  src/lib/preparationGovernance.ts \
  src/steps/Step06_BalancingSplit.tsx \
  tests/experimentCanonicalIdentity.test.mjs \
  tests/featureEngineeringProgressionContract.test.mjs \
  tests/model_training_preflight_authority_test.py \
  tests/split_atomicity_test.py \
  tests/validation_design_training_contract_test.py \
  tests/validation_segregation_of_duties_test.py \
  tests/vif_resolution_plan_test.py \
  tests/training_validation_policy_execution_test.py \
  tests/validation_design_partition_target_authority_test.py
```

Count: 18 paths.

## Reconciliation with earlier reports

The Data Acquisition information-architecture report proposed a single broader slice. Current import coupling supersedes that boundary: its authority/repository/migration portion belongs in S1, while the UI and reproducibility consumers belong in S3. This keeps every proposed intermediate state import-complete. Live authority JSON, generated evidence, audit screenshots, and test output are inputs or outputs of these features, never source dependencies to stage.

## Proposed morning decision

Do not approve S1 or any dependent slice while the checkpoint verdict remains blocking. After the migration and source-scope defects are repaired in a separate authorized task, rerun the complete checkpoint gate, review S1 first, and stage only the exact reviewed manifest.
