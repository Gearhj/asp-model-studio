# Predictive Workflow Confirmation Inventory

This inventory defines where ATLAS persists drafts, where it requires a
governed confirmation, and where navigation is merely a consequence of a
successful backend action. The objective is to preserve auditability without
asking an analyst to approve the same decision more than once.

| Workflow page | User action | Why it exists | Persistence and evidence | Navigation behavior | Classification |
|---|---|---|---|---|---|
| Data Acquisition | Import and register dataset | Establishes the governed data object and immutable version used downstream. | Backend dataset record, immutable version, import evidence. | Remains on Data Acquisition until the target contract is ready. | Necessary backend action |
| Data Acquisition | Confirm target and event mapping | Defines the supervised-learning outcome and excludes deterministic target-source fields. | Backend target contract, Decision Journal entry, Evidence Center item, MDD linkage. | Unlocks downstream preparation. | Necessary governed confirmation |
| Data Acquisition | Save Special-Value Treatment draft | Lets an analyst pause after choosing variable defaults or explicit value overrides. | Browser draft plus draft evidence state; does not claim final approval. | No navigation. | Necessary draft action |
| Data Acquisition | Confirm Special-Value Treatment | Confirms one governed treatment contract after all required override/destructive rationales are present. | Review timestamp, reviewer, defaults, overrides, semantic separation, Evidence Center item, Decision Journal entry, MDD content. | No forced navigation; the main workflow controls progression. | Necessary governed confirmation |
| EDA | Record or dismiss an analytical finding | Captures the analyst's disposition of a specific signal. | Finding disposition, rationale when required, Decision Journal and EDA evidence. | No navigation. | Necessary decision |
| EDA | Complete EDA | Confirms the aggregate EDA conclusions and documentation package once. | EDA completion record, report evidence, MDD linkage. | Continues to preparation. | Necessary governed confirmation |
| Outliers | Select treatment | Configures a draft ordinary-value policy; bureau special values remain outside the ordinary-outlier scope. | Auto-saved draft only. | No navigation. | Draft setting, no confirmation |
| Outliers | Preview impact | Provides non-destructive consequence evidence before materialization. | Preview artifact and metrics. | No navigation. | Necessary analytical action |
| Outliers | Apply treatment and continue | Materializes the confirmed ordinary-value policy and records the resulting dataset artifact. | Backend application, hashes, evidence, MDD linkage. | Continues only after success. | Necessary backend action plus single confirmation |
| Missing Values | Select treatment | Configures null-missingness rules while preserving bureau specials and parse failures as separate concepts. | Auto-saved draft only. | No navigation. | Draft setting, no confirmation |
| Missing Values | Validate policy | Checks feasibility and downstream compatibility without changing the dataset. | Validation result and blockers. | No navigation. | Necessary analytical action |
| Missing Values | Apply treatment and continue | Materializes the governed null-missingness policy once. | Backend application, hashes, evidence, MDD linkage. | Continues only after success. | Necessary backend action plus single confirmation |
| Feature Engineering | Save feature draft | Persists feature definitions and rationales without representing them as built. | Draft feature contract. | No navigation. | Necessary draft action |
| Feature Engineering | Preview transformations | Evaluates domains, collisions, lineage, distributions, and bureau-special behavior before materialization. | Preview result and validation diagnostics. | No navigation. | Necessary analytical action |
| Feature Engineering | Materialize features | Creates the engineered dataset artifact using the backend contract. | Materialization ID, content hashes, lineage, audit and evidence artifacts. | No automatic navigation. | Necessary backend action |
| Feature Engineering | Confirm feature manifest and continue | Confirms the exact training predictor manifest once after successful materialization. | Manifest version/hash, reviewer/timestamp, Decision Journal, Evidence Center, MDD linkage. | Continues to Training and Validation Design. | Necessary governed confirmation |
| Training and Validation Design | Edit holdout, CV, balancing, or optional external data | Builds the recommended draft contract: 20% untouched holdout and stratified 5-fold CV inside training by default. | Auto-saved browser draft; no self-approval checkboxes. | No navigation. | Draft setting, no confirmation |
| Training and Validation Design | Create Validation Design & Continue | Validates and persists the population split, exact folds, protections, optional external references, evidence, and MDD handoff in one action. | Backend Validation Design and population IDs, exact fold bindings, Evidence Center item, Decision Journal entry, MDD linkage. | Continues to Model Training only after success. | Necessary backend action plus single confirmation |
| Model Training | Launch a model run | Executes an explicitly configured candidate against the inherited Validation Design. | Immutable run record, parameters, logs, metrics, artifacts. | No navigation. | Necessary execution action |
| Model Training | Propose champion or challenger | Records a model-governance proposal; it does not silently approve deployment. | Proposal record, rationale, comparison evidence, Decision Journal and MDD linkage. | No forced navigation. | Necessary governed proposal |

## Removed redundant confirmations

- Validation-strategy card selection was removed from the standard path. The
  default is always an untouched holdout plus cross-validation inside training.
- Separate checkboxes for holdout protection, CV approval, schema review, and
  target mapping were removed. These are deterministic validation gates, not
  analyst attestations.
- Separate Save Design, Approve Design, and Continue controls were collapsed
  into **Create Validation Design & Continue**.
- TEST and OOT selection moved into a closed advanced section because neither
  is required for the standard workflow.
- The final predictor contract remains available on the page, but is compact
  and collapsed because Feature Engineering already owns its primary review.

## Governing principle

ATLAS asks for rationale only when a user overrides a recommendation, chooses a
destructive/custom treatment, disposes of a finding contrary to the analytical
signal, or proposes a governed model decision. Backend validation errors and
deterministic safety gates produce precise blockers; they do not become
self-attestation checkboxes.
