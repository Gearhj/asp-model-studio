import { loadDecisionJournal, type DecisionJournalEntry } from "./decisionJournal";
import { generateBureauPythonCode } from "./creditBureau";
import { loadExperiments } from "./experimentTracking";
import { buildGovernanceReport } from "./governanceReport";
import { inferLocalProblemType, loadLocalDataset } from "./localDataset";
import { loadProjectContext, summarizeRegulatoryContext } from "./projectContext";
import { loadDataAccessMetadata } from "./enterpriseDataAccess";
import { BRAND } from "../config/brand";

export const USER_PYTHON_CODE_KEY = "modeling-tool-user-python-code";
export const USER_STEP_PYTHON_CODE_KEY = "modeling-tool-user-python-code-by-step";

type NotebookCell = {
  cell_type: "markdown" | "code";
  metadata: Record<string, unknown>;
  source: string;
  execution_count?: number | null;
  outputs?: unknown[];
};

type Notebook = {
  cells: NotebookCell[];
  metadata: {
    kernelspec: { display_name: string; language: string; name: string };
    language_info: { name: string; version: string };
  };
  nbformat: 4;
  nbformat_minor: 5;
};

export type NotebookSection = {
  sectionKey: string;
  routes: string[];
  title: string;
  explanation: string;
  code: string;
  decisionMatchers: string[];
  outputPlaceholder: string;
  includeUserCode?: boolean;
};

function markdown(source: string): NotebookCell {
  return { cell_type: "markdown", metadata: {}, source };
}

function code(source: string): NotebookCell {
  return { cell_type: "code", metadata: {}, source, execution_count: null, outputs: [] };
}

function safeJson(value: unknown) {
  return JSON.stringify(value ?? null, null, 2);
}

function formatDecisionNotes(entries: DecisionJournalEntry[], matchers: string[]) {
  const normalized = matchers.map((matcher) => matcher.toLowerCase());
  const rows = entries.filter((entry) => {
    const haystack = [entry.workflowStep, entry.actionType, entry.subject].join(" ").toLowerCase();
    return normalized.some((matcher) => haystack.includes(matcher));
  });
  if (!rows.length) return "- No decision journal notes captured for this section.";
  return rows
    .slice(0, 15)
    .map(
      (entry) =>
        `- ${entry.timestamp} | ${entry.workflowStep} | ${entry.subject}: ${entry.previousValue} -> ${entry.newValue}. Rationale: ${entry.userReason || "Not documented"}`
    )
    .join("\n");
}

function customPythonCode() {
  try {
    return localStorage.getItem(USER_PYTHON_CODE_KEY) || "";
  } catch {
    return "";
  }
}

function customPythonCodeByStep() {
  try {
    const parsed = JSON.parse(localStorage.getItem(USER_STEP_PYTHON_CODE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function selectedFeatureList() {
  const dataset = loadLocalDataset();
  return dataset?.selected_columns?.length
    ? dataset.selected_columns
    : dataset?.headers.filter((header) => header !== dataset.target) ?? [];
}

function readLocalStorageJson(key: string) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null");
  } catch {
    return null;
  }
}

function buildSections(): NotebookSection[] {
  const context = loadProjectContext();
  const dataset = loadLocalDataset();
  const problemType = inferLocalProblemType(dataset) ?? "classification";
  const experiments = loadExperiments();
  const champion = experiments.find((experiment) => experiment.champion) ?? experiments[0] ?? null;
  const features = selectedFeatureList();
  const missingConfig = readLocalStorageJson("modeling-tool-missing-config") ?? {};
  const outlierConfig = readLocalStorageJson("modeling-tool-outlier-methods") ?? {};
  const balanceMethod = localStorage.getItem("balanceMethod") ?? "none";
  const splitStrategy = localStorage.getItem("splitStrategy") ?? "holdout";
  const balanceRatio = localStorage.getItem("balanceRatio") ?? "";
  const dataAccess = loadDataAccessMetadata();

  return [
    {
      sectionKey: "project_context",
      routes: ["/step00"],
      title: "Project Context",
      explanation:
        "This section records the business and governance context that should control downstream modeling decisions.",
      decisionMatchers: ["project context", "project_context"],
      outputPlaceholder: "Review the printed project context and confirm it matches the approved model development plan.",
      code: `PROJECT_CONTEXT = ${safeJson(context)}

print("Project:", PROJECT_CONTEXT.get("projectName") or "Not documented")
print("Model type:", PROJECT_CONTEXT.get("modelType"))
print("Regulatory environment:", ", ".join(PROJECT_CONTEXT.get("regulatoryEnvironment", [])))
print("Primary success metric:", PROJECT_CONTEXT.get("primarySuccessMetric") or "Not documented")`,
    },
    {
      sectionKey: "data_loading",
      routes: ["/step01"],
      title: "Data Loading",
      explanation:
        "Load the same development data used in the workbench. Replace the CSV path with the controlled training file location.",
      decisionMatchers: ["data acquisition", "target"],
      outputPlaceholder: "Dataset shape, target field, and first records should display here.",
      code: `${dataAccess?.generatedPython ? `${dataAccess.generatedPython}\n` : `from pathlib import Path
import json
import numpy as np
import pandas as pd

TRAIN_CSV_PATH = Path("TRAIN.csv")  # Replace with governed training data path.
df = pd.read_csv(TRAIN_CSV_PATH)
`}

DATA_ACCESS_METADATA = ${safeJson(dataAccess)}
TARGET = ${safeJson(dataset?.target ?? "target")}
SELECTED_FEATURES = ${safeJson(features)}
PROBLEM_TYPE = ${safeJson(problemType)}

print("Rows:", len(df))
print("Columns:", len(df.columns))
print("Target:", TARGET)
print("Data source:", DATA_ACCESS_METADATA.get("sourceLabel") if DATA_ACCESS_METADATA else "Not documented")
print("Dataset version:", DATA_ACCESS_METADATA.get("version") if DATA_ACCESS_METADATA else "Not documented")
display(df.head())`,
    },
    {
      sectionKey: "credit_bureau_handling",
      routes: ["/step01b"],
      title: "Credit Bureau Handling",
      explanation:
        "Identify and treat credit bureau special values separately from ordinary missing values and numeric outliers.",
      decisionMatchers: ["credit bureau", "bureau", "special value"],
      outputPlaceholder: "Special value profiles, selected treatments, and transformation documentation should display here.",
      code: `${generateBureauPythonCode()}

bureau_profile = profile_bureau_special_values(df, target=TARGET)
display(bureau_profile)

df, bureau_treatment_documentation = apply_bureau_special_value_treatments(df)
display(bureau_treatment_documentation)`,
    },
    {
      sectionKey: "eda",
      routes: ["/step02"],
      title: "EDA",
      explanation:
        "Reproduce core exploratory diagnostics: target distribution, missingness, descriptive statistics, and pairwise/correlation review.",
      decisionMatchers: ["eda", "exploratory"],
      outputPlaceholder: "EDA tables and charts should display here.",
      code: `import matplotlib.pyplot as plt

display(df[SELECTED_FEATURES + [TARGET]].describe(include="all").T)
missing = df[SELECTED_FEATURES + [TARGET]].isna().mean().sort_values(ascending=False)
display(missing.to_frame("missing_rate"))

if PROBLEM_TYPE == "classification":
    target_rate = df[TARGET].mean() if pd.api.types.is_numeric_dtype(df[TARGET]) else df[TARGET].value_counts(normalize=True)
    print("Target distribution:")
    display(target_rate)
else:
    df[TARGET].hist(bins=40)
    plt.title("Target distribution")
    plt.show()`,
    },
    {
      sectionKey: "missing_values",
      routes: ["/step04"],
      title: "Missing Values",
      explanation:
        "Apply the missing-value strategy selected in the workflow. Review high-missingness fields before exclusion or imputation.",
      decisionMatchers: ["missing", "imputation"],
      outputPlaceholder: "Missingness before and after imputation should display here.",
      code: `MISSING_CONFIG = ${safeJson(missingConfig)}

print("Missing config:", json.dumps(MISSING_CONFIG, indent=2))
print("Missing before:", int(df[SELECTED_FEATURES].isna().sum().sum()))

for feature in SELECTED_FEATURES:
    strategy = (MISSING_CONFIG.get(feature, {}) or {}).get("strategy", "Median")
    if feature not in df.columns:
        continue
    if strategy.lower() == "drop":
        df = df[df[feature].notna()].copy()
    elif strategy.lower() == "constant":
        constant = (MISSING_CONFIG.get(feature, {}) or {}).get("constantValue", 0)
        df[feature] = df[feature].fillna(constant)
    elif pd.api.types.is_numeric_dtype(df[feature]):
        df[feature] = df[feature].fillna(df[feature].median())
    else:
        mode = df[feature].mode(dropna=True)
        df[feature] = df[feature].fillna(mode.iloc[0] if len(mode) else "Missing")

print("Missing after:", int(df[SELECTED_FEATURES].isna().sum().sum()))`,
    },
    {
      sectionKey: "outliers",
      routes: ["/step03"],
      title: "Outliers",
      explanation:
        "Recreate selected outlier handling. Amount-like variables should be reviewed carefully because tail values may be predictive.",
      decisionMatchers: ["outlier", "cap", "amount"],
      outputPlaceholder: "Outlier thresholds and capped value counts should display here.",
      code: `OUTLIER_CONFIG = ${safeJson(outlierConfig)}

def cap_iqr(series, multiplier=1.5):
    q1, q3 = series.quantile([0.25, 0.75])
    iqr = q3 - q1
    return series.clip(q1 - multiplier * iqr, q3 + multiplier * iqr)

for feature, method in OUTLIER_CONFIG.items():
    if feature not in df.columns or not pd.api.types.is_numeric_dtype(df[feature]):
        continue
    before = df[feature].copy()
    if "3" in str(method):
        df[feature] = cap_iqr(df[feature], 3.0)
    elif "iqr" in str(method).lower() or "cap" in str(method).lower():
        df[feature] = cap_iqr(df[feature], 1.5)
    print(feature, method, "changed rows:", int((before != df[feature]).sum()))`,
    },
    {
      sectionKey: "feature_engineering",
      routes: ["/step05"],
      title: "Feature Engineering",
      explanation:
        "Rebuild encoded, scaled, binned, interaction, and rule-based features. Add any custom feature engineering code below.",
      decisionMatchers: ["feature", "encoding", "scaling", "custom_python"],
      outputPlaceholder: "Feature engineering output schema should display here.",
      includeUserCode: true,
      code: `# Generated feature engineering scaffold.
# Add or replace with the exact governed transformations from the workflow.
X = df[SELECTED_FEATURES].copy()
y = df[TARGET].copy()

numeric_features = X.select_dtypes(include=[np.number]).columns.tolist()
categorical_features = [col for col in X.columns if col not in numeric_features]

print("Numeric features:", numeric_features)
print("Categorical features:", categorical_features)
print("Feature matrix shape before encoding:", X.shape)`,
    },
    {
      sectionKey: "train_test_split",
      routes: ["/step06"],
      title: "Train/Test Split",
      explanation:
        "Reproduce the selected train/test or cross-validation split. Use time-based or OOT validation when production performance depends on future populations.",
      decisionMatchers: ["split", "holdout", "kfold"],
      outputPlaceholder: "Train and validation sample sizes should display here.",
      code: `from sklearn.model_selection import train_test_split

SPLIT_STRATEGY = ${safeJson(splitStrategy)}
test_size = 0.20

stratify = y if PROBLEM_TYPE == "classification" and y.nunique() <= 20 else None
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=test_size, random_state=42, stratify=stratify
)

print("Split strategy:", SPLIT_STRATEGY)
print("Train rows:", len(X_train))
print("Test rows:", len(X_test))`,
    },
    {
      sectionKey: "balancing",
      routes: ["/step06"],
      title: "Balancing",
      explanation:
        "Apply the selected balancing method to the training split only. Holdout, TEST, and OOT data should not be balanced.",
      decisionMatchers: ["balancing", "balance", "smote", "undersample", "class weight"],
      outputPlaceholder: "Class distribution before and after balancing should display here.",
      code: `BALANCE_METHOD = ${safeJson(balanceMethod)}
BALANCE_RATIO = ${safeJson(balanceRatio)}

print("Balance method:", BALANCE_METHOD)
if PROBLEM_TYPE == "classification":
    print("Training target distribution before balancing:")
    display(y_train.value_counts(normalize=True).to_frame("share"))
    # Implement governed balancing here. Examples: class_weight in model params, random undersampling, or SMOTE.
else:
    print("Balancing is not applicable to regression targets.")`,
    },
    {
      sectionKey: "model_training",
      routes: ["/step07"],
      title: "Model Training",
      explanation:
        "Train candidate models and record hyperparameters, runtime, and metrics. The scaffold includes common transparent and challenger models.",
      decisionMatchers: ["model training", "model_selected", "hyperparameter"],
      outputPlaceholder: "Candidate model leaderboard should display here.",
      code: `from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, average_precision_score, f1_score, mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

if PROBLEM_TYPE == "classification":
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    estimators = {
        "Logistic Regression": LogisticRegression(max_iter=1000, class_weight="balanced"),
        "Random Forest": RandomForestClassifier(n_estimators=200, random_state=42, class_weight="balanced_subsample"),
    }
else:
    from sklearn.linear_model import LinearRegression
    from sklearn.ensemble import RandomForestRegressor
    estimators = {
        "Linear Regression": LinearRegression(),
        "Random Forest Regressor": RandomForestRegressor(n_estimators=200, random_state=42),
    }

preprocess = ColumnTransformer(
    transformers=[
        ("num", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]), numeric_features),
        ("cat", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]), categorical_features),
    ],
    remainder="drop",
)

results = []
fitted_models = {}
for name, estimator in estimators.items():
    pipe = Pipeline([("preprocess", preprocess), ("model", estimator)])
    pipe.fit(X_train, y_train)
    fitted_models[name] = pipe
    if PROBLEM_TYPE == "classification":
        score = pipe.predict_proba(X_test)[:, 1] if hasattr(pipe.named_steps["model"], "predict_proba") else pipe.predict(X_test)
        pred = (score >= 0.5).astype(int)
        results.append({"model": name, "auc": roc_auc_score(y_test, score), "pr_auc": average_precision_score(y_test, score), "f1": f1_score(y_test, pred)})
    else:
        pred = pipe.predict(X_test)
        rmse = mean_squared_error(y_test, pred) ** 0.5
        results.append({"model": name, "rmse": rmse, "mae": mean_absolute_error(y_test, pred), "r2": r2_score(y_test, pred)})

leaderboard = pd.DataFrame(results).sort_values("auc" if PROBLEM_TYPE == "classification" else "rmse", ascending=PROBLEM_TYPE != "classification")
display(leaderboard)`,
    },
    {
      sectionKey: "evaluation",
      routes: ["/step08"],
      title: "Evaluation",
      explanation:
        "Evaluate champion and challenger models using metrics aligned to the target type and business objective.",
      decisionMatchers: ["evaluation", "champion"],
      outputPlaceholder: "ROC/PR or residual diagnostics should display here.",
      code: `CHAMPION_MODEL_NAME = ${safeJson(champion?.modelType ?? null)}
if CHAMPION_MODEL_NAME not in fitted_models:
    CHAMPION_MODEL_NAME = leaderboard.iloc[0]["model"]
champion_model = fitted_models[CHAMPION_MODEL_NAME]

print("Champion model:", CHAMPION_MODEL_NAME)
if PROBLEM_TYPE == "classification":
    from sklearn.metrics import classification_report, confusion_matrix, RocCurveDisplay, PrecisionRecallDisplay
    score = champion_model.predict_proba(X_test)[:, 1] if hasattr(champion_model.named_steps["model"], "predict_proba") else champion_model.predict(X_test)
    pred = (score >= 0.5).astype(int)
    print(classification_report(y_test, pred))
    display(pd.DataFrame(confusion_matrix(y_test, pred), index=["Actual 0", "Actual 1"], columns=["Pred 0", "Pred 1"]))
    RocCurveDisplay.from_predictions(y_test, score)
    PrecisionRecallDisplay.from_predictions(y_test, score)
else:
    pred = champion_model.predict(X_test)
    residuals = y_test - pred
    display(pd.DataFrame({"actual": y_test, "predicted": pred, "residual": residuals}).head())
    plt.scatter(pred, residuals, alpha=0.35)
    plt.axhline(0, color="black", linewidth=1)
    plt.title("Residuals vs Predicted")
    plt.show()`,
    },
    {
      sectionKey: "interpretation",
      routes: ["/step09"],
      title: "Interpretation",
      explanation:
        "Review feature importance, SHAP/PDP-style effects, sensitivity analysis, RFE, and VIF where applicable.",
      decisionMatchers: ["interpretation", "rfe", "final model", "challenge"],
      outputPlaceholder: "Feature importance and interpretation diagnostics should display here.",
      code: `model_step = champion_model.named_steps["model"]
print("Model object:", model_step)

if hasattr(model_step, "feature_importances_"):
    feature_names = champion_model.named_steps["preprocess"].get_feature_names_out()
    importance = pd.DataFrame({"feature": feature_names, "importance": model_step.feature_importances_})
    display(importance.sort_values("importance", ascending=False).head(25))
elif hasattr(model_step, "coef_"):
    feature_names = champion_model.named_steps["preprocess"].get_feature_names_out()
    coefs = np.ravel(model_step.coef_)
    display(pd.DataFrame({"feature": feature_names, "coefficient": coefs}).assign(abs_coef=lambda x: x["coefficient"].abs()).sort_values("abs_coef", ascending=False).head(25))
else:
    print("Model-specific importance is not available. Use permutation importance or SHAP in the governed environment.")`,
    },
    {
      sectionKey: "scoring",
      routes: ["/step10"],
      title: "Scoring",
      explanation:
        "Score holdout TEST and OOT datasets using the same fitted preprocessing pipeline and model object.",
      decisionMatchers: ["scoring", "oot", "test", "psi", "vsi"],
      outputPlaceholder: "TEST and OOT score summaries, PSI, and VSI should display here.",
      code: `TEST_CSV_PATH = Path("TEST.csv")
OOT_CSV_PATH = Path("OOT.csv")

def score_dataset(path, model):
    if not path.exists():
        print(f"Missing scoring file: {path}")
        return None
    scoring_df = pd.read_csv(path)
    scores = model.predict(scoring_df[SELECTED_FEATURES])
    out = scoring_df.copy()
    out["prediction"] = scores
    if PROBLEM_TYPE == "classification" and hasattr(model.named_steps["model"], "predict_proba"):
        out["score"] = model.predict_proba(scoring_df[SELECTED_FEATURES])[:, 1]
    display(out[["prediction"] + (["score"] if "score" in out.columns else [])].describe())
    return out

test_scored = score_dataset(TEST_CSV_PATH, champion_model)
oot_scored = score_dataset(OOT_CSV_PATH, champion_model)`,
    },
    {
      sectionKey: "governance_summary",
      routes: ["/governance-report"],
      title: "Governance Summary",
      explanation:
        "Summarize governance evidence, open risks, decision rationale, experiment lineage, and validation readiness.",
      decisionMatchers: ["governance", "challenge_response", "experiment", "decision"],
      outputPlaceholder: "Governance summary and audit trail notes should display here.",
      code: `GOVERNANCE_REPORT_MARKDOWN = ${safeJson(buildGovernanceReport().markdown)}

print(GOVERNANCE_REPORT_MARKDOWN[:3000])

with open("model_governance_report.md", "w", encoding="utf-8") as f:
    f.write(GOVERNANCE_REPORT_MARKDOWN)

print("Wrote model_governance_report.md")`,
    },
  ];
}

export function getNotebookSections() {
  return buildSections();
}

export function buildWorkflowNotebook(): Notebook {
  const entries = loadDecisionJournal();
  const legacyUserCode = customPythonCode().trim();
  const userCodeByStep = customPythonCodeByStep();
  const sections = buildSections();
  const cells: NotebookCell[] = [
    markdown(`# ${BRAND.productName}

## ${BRAND.productSubtitle}

${BRAND.shortDescription}

### End-to-End Workflow Notebook

Generated: ${new Date().toISOString()}

This notebook reproduces the governed modeling workflow from project context through governance summary. Replace placeholder file paths with controlled data locations before execution.`),
  ];

  sections.forEach((section, index) => {
    cells.push(
      markdown(`## ${index + 1}. ${section.title}

${section.explanation}

### Decision Journal Notes
${formatDecisionNotes(entries, section.decisionMatchers)}`),
      code(section.code)
    );

    const userStepCode = (userCodeByStep[section.sectionKey] ?? "").trim();
    const userCode = userStepCode || (section.includeUserCode ? legacyUserCode : "");
    if (userCode.trim()) {
      cells.push(
        markdown(`### User-Edited Python Code

This cell contains Python code edited in the platform for this workflow section.`),
        code(userCode)
      );
    }

    cells.push(markdown(`### Output Placeholder

${section.outputPlaceholder}`));
  });

  return {
    cells,
    metadata: {
      kernelspec: { display_name: "Python 3", language: "python", name: "python3" },
      language_info: { name: "python", version: "3.x" },
    },
    nbformat: 4,
    nbformat_minor: 5,
  };
}

export function exportWorkflowNotebookJson() {
  return JSON.stringify(buildWorkflowNotebook(), null, 2);
}

export function exportWorkflowPythonScript() {
  return buildWorkflowNotebook()
    .cells.map((cell) => {
      if (cell.cell_type === "markdown") {
        return cell.source
          .split("\n")
          .map((line) => `# ${line}`.trimEnd())
          .join("\n");
      }
      return cell.source;
    })
    .join("\n\n");
}
