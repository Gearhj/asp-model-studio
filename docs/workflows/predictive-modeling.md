# Predictive Modeling Workflow

The predictive modeling workflow supports regulated classification and regression model development.

## Core Stages

1. Project Context
2. Data Acquisition
3. Credit Bureau Data Review when applicable
4. EDA
5. Outliers
6. Missing Values
7. Feature Engineering
8. Balance and Split
9. Model Training
10. Evaluation
11. Interpretation
12. Scoring
13. Model Development Document
14. Model Implementation
15. Model Monitoring

## Expected Behavior

- Classification and regression modes should switch automatically from the target variable.
- The target variable should not be available as an engineered feature.
- Outlier handling should occur before missing value imputation.
- Model training toggles and grid search controls should remain selectable.
- RFE should expose a visible run action and save the selected final model.
- Navigation should save state, advance to the next step, and scroll the next page to top.

## Governance Output

The Model Development Document should summarize the final model and reserve raw click/update history for the Decision Journal appendix.
