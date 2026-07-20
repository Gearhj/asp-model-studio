export type WorkflowStepStatus = "pending" | "in_progress" | "complete" | "skipped";

export type WorkflowStep = {
  id: string;
  label: string;
  shortLabel?: string;
  route: string;
  description: string;
  status?: WorkflowStepStatus;
  required?: boolean;
};

export type ProjectType =
  | "predictive-modeling"
  | "experimental-design"
  | "ab-testing"
  | "optimization"
  | "time_series_forecasting"
  | "llm_generative_ai"
  | "forecasting"
  | "segmentation"
  | "reinforcement-learning"
  | "time-series"
  | "nlp"
  | "computer-vision"
  | "graph-analytics"
  | "custom-workflow";

export type WorkflowDefinition = {
  id: string;
  label: string;
  description: string;
  projectType: ProjectType;
  steps: WorkflowStep[];
};

export type WorkflowTemplate = {
  id: string;
  workflowId: string;
  label: string;
  description: string;
  projectType: ProjectType;
  commonUseCases: string[];
  governanceIntensity: "low" | "medium" | "high";
};

export type ExperimentalDesignJourneyStep = {
  id: string;
  route: string;
  label: string;
  shortLabel: string;
  stepNumber: number;
  totalSteps: number;
  question: string;
  purpose: string;
  transition: string;
  output: string;
  nextLabel?: string;
  nextQuestion?: string;
};

const predictiveModelingSteps: WorkflowStep[] = [
  {
    id: "step00",
    label: "Project Context",
    shortLabel: "Context",
    route: "/step00",
    description: "Define the modeling mission, intended use, business target, eligible population, and outcome windows before selecting data.",
    required: true,
  },
  {
    id: "step01",
    label: "Data Acquisition",
    shortLabel: "Data",
    route: "/step01",
    description: "Connect to governed data, upload files, select the target, inspect columns, and persist the sample.",
    required: true,
  },
  {
    id: "step02",
    label: "EDA",
    shortLabel: "EDA",
    route: "/step02",
    description: "Review distributions, box plots, correlations, and pairwise relationships.",
    required: true,
  },
  {
    id: "step03",
    label: "Outliers",
    shortLabel: "Outliers",
    route: "/step03",
    description: "Choose per-feature detection and capping methods for numeric fields.",
  },
  {
    id: "step04",
    label: "Missing Values",
    shortLabel: "Missing",
    route: "/step04",
    description: "Assign imputation or drop strategies for numeric and categorical variables after outlier treatment choices are documented.",
    required: true,
  },
  {
    id: "step05",
    label: "Feature Engineering",
    shortLabel: "Features",
    route: "/step05",
    description: "Create encodings, scaling choices, bins, interactions, and rule features.",
  },
  {
    id: "step06",
    label: "Balance & Split",
    shortLabel: "Split",
    route: "/step06",
    description: "Set holdout or cross-validation strategy and class balancing behavior.",
    required: true,
  },
  {
    id: "step07",
    label: "Model Training",
    shortLabel: "Train",
    route: "/step07",
    description: "Select candidate models, submit training, and review basic run metrics.",
    required: true,
  },
  {
    id: "step08",
    label: "Evaluation",
    shortLabel: "Evaluate",
    route: "/step08",
    description: "Compare model metrics, curves, lift, residual diagnostics, and validation results before final RFE model selection.",
    required: true,
  },
  {
    id: "step09",
    label: "Interpretation",
    shortLabel: "Interpret",
    route: "/step09",
    description: "Review feature importance, PDP, SHAP-style impacts, sensitivity, model details, and RFE to establish the verified final model before scoring.",
    required: true,
  },
  {
    id: "step10",
    label: "Scoring",
    shortLabel: "Score",
    route: "/step10",
    description: "Score TRAIN, TEST, and OOT data with the final model selected in Interpretation, review stability, and prepare final production outputs.",
  },
  {
    id: "step11",
    label: "Documentation Review",
    shortLabel: "Document",
    route: "/step11",
    description: "Review documentation readiness and open the Model Documentation Studio for governed artifacts.",
    required: true,
  },
  {
    id: "step12",
    label: "Model Implementation",
    shortLabel: "Implement",
    route: "/step12",
    description: "Document implementation ownership, target environment, approvals, packaging, and production handoff after the model has been developed.",
    required: true,
  },
  {
    id: "step13",
    label: "Model Monitoring",
    shortLabel: "Monitor",
    route: "/step13",
    description: "Define monitoring cadence, select production monitoring metrics, and review monitored production models and escalations.",
    required: true,
  },
];

const creditRiskStudioSteps: WorkflowStep[] = predictiveModelingSteps;

function placeholderSteps(workflowId: string, labels: Array<[string, string]>) {
  return labels.map(([label, description], index) => ({
    id: `${workflowId}-${index + 1}`,
    label,
    shortLabel: label.split(" ")[0],
    route: `/workflow/${workflowId}/${index + 1}`,
    description,
    required: index === 0 || index === labels.length - 1,
  }));
}

const timeSeriesForecastingSteps: WorkflowStep[] = placeholderSteps("time_series_forecasting", [
  ["Project Context", "Define the time-dependent business problem, forecast horizon, monitored outcome, operating cadence, and governance boundary."],
  ["Data Acquisition", "Load or register time-indexed data and map the date field, target field, entity grain, and optional exogenous drivers."],
  ["Time Series Profile", "Review target behavior, trend, seasonality, volatility, outliers, autocorrelation, and structural breaks before modeling."],
  ["Feature & Calendar Design", "Create lags, rolling statistics, calendar flags, trend terms, event flags, and future-known feature controls."],
  ["Backtest Design", "Define temporal splits, rolling or expanding windows, forecast horizon, gap period, folds, and evaluation metrics."],
  ["Model Configuration", "Select baseline, statistical, machine-learning, and anomaly-detection candidates with reproducible settings."],
  ["Train & Backtest", "Run time-aware training and backtesting, compare fold results, export run configuration, and capture warnings."],
  ["Forecast Results", "Review champion forecasts, prediction intervals, entity-level forecasts, and business implications."],
  ["Diagnostics & Stability", "Validate residual behavior, error by horizon, drift, interval coverage, anomalies, and segment stability."],
  ["Scenario & Stress Testing", "Stress forecasts under demand shocks, seasonality changes, downturns, fraud spikes, outages, and custom future drivers."],
  ["Recommendation & Monitoring Plan", "Translate forecast evidence into a recommendation, monitoring thresholds, reforecast triggers, and escalation plan."],
  ["Documentation", "Generate an audit-ready Time Series & Forecasting package with evidence inventory, Python, and SAS-compatible code."],
]);

const llmGenerativeAiSteps: WorkflowStep[] = placeholderSteps("llm_generative_ai", [
  ["Use Case & Risk Context", "Define the LLM use case, users, allowed behavior, customer impact, sensitive data, human review, and governance boundary."],
  ["Data & Knowledge Sources", "Register source documents, text datasets, policies, procedures, transcripts, cases, or knowledge bases."],
  ["Task Design & Output Schema", "Define the exact LLM task, output contract, citations, fallback behavior, review criteria, labels, or extraction fields."],
  ["Prompt & Instruction Design", "Design system instructions, developer guidance, user prompt templates, examples, guardrails, and response format."],
  ["Retrieval / RAG Configuration", "Configure chunking, embeddings, retrieval, reranking, metadata filters, citations, and no-source fallback behavior."],
  ["Evaluation Dataset", "Create or upload golden test cases, expected answers, labels, source references, adversarial prompts, and edge cases."],
  ["LLM Evaluation", "Score correctness, groundedness, citations, safety, refusal behavior, extraction quality, classification metrics, and reviewer agreement."],
  ["Safety, Compliance & Red-Team Review", "Review prompt injection, leakage, hallucination, unsupported answer risk, privacy, UDAAP, fair lending, and escalation controls."],
  ["Human Review & Quality Control", "Define reviewer workflow, sampling strategy, override capture, escalation handling, and quality thresholds."],
  ["Deployment & Monitoring Plan", "Define deployment boundaries, version controls, monitoring metrics, incident escalation, and re-evaluation triggers."],
  ["Recommendation & Approval", "Translate evaluation, safety, retrieval, and human-review evidence into a business recommendation and approval record."],
  ["Documentation", "Generate an audit-ready LLM / Generative AI package with prompt registry, source registry, evidence, Python, and SQL/SAS templates."],
]);

export const experimentalDesignJourney: ExperimentalDesignJourneyStep[] = [
  {
    id: "experimental-design-1",
    route: "/workflow/experimental-design/1",
    label: "Project Context",
    shortLabel: "Project",
    stepNumber: 1,
    totalSteps: 12,
    question: "What business problem are we solving?",
    purpose: "Define the business objective, population, constraints, governance expectations, and intended decision use.",
    transition: "Because you are starting the experiment, ATLAS will first establish the charter that anchors every design choice.",
    output: "A documented experiment charter.",
    nextLabel: "Research Question",
    nextQuestion: "What statistical question are we trying to answer?",
  },
  {
    id: "experimental-design-2",
    route: "/workflow/experimental-design/2",
    label: "Research Question",
    shortLabel: "Research",
    stepNumber: 2,
    totalSteps: 12,
    question: "What statistical question are we trying to answer?",
    purpose: "Translate the business objective into a measurable hypothesis, response variable, and decision rule.",
    transition: "Because the project context is documented, ATLAS will now convert the business objective into statistical logic.",
    output: "A testable hypothesis and decision rule.",
    nextLabel: "Factors",
    nextQuestion: "What variables can influence the outcome?",
  },
  {
    id: "experimental-design-3",
    route: "/workflow/experimental-design/3",
    label: "Factors",
    shortLabel: "Factors",
    stepNumber: 3,
    totalSteps: 12,
    question: "What variables can influence the outcome?",
    purpose: "Identify controllable experimental factors and separate them from measured covariates.",
    transition: "Because the statistical question is framed, ATLAS will now identify which variables define the experiment.",
    output: "A factor and covariate inventory.",
    nextLabel: "Levels",
    nextQuestion: "What settings should each variable take?",
  },
  {
    id: "experimental-design-4",
    route: "/workflow/experimental-design/4",
    label: "Levels",
    shortLabel: "Levels",
    stepNumber: 4,
    totalSteps: 12,
    question: "What settings should each variable take?",
    purpose: "Define realistic, measurable factor settings that become treatment combinations.",
    transition: "Because the factors are defined, ATLAS will now turn them into deployable treatment settings.",
    output: "A treatment matrix.",
    nextLabel: "Blocking",
    nextQuestion: "What unwanted variation should we control?",
  },
  {
    id: "experimental-design-5",
    route: "/workflow/experimental-design/5",
    label: "Blocking",
    shortLabel: "Blocking",
    stepNumber: 5,
    totalSteps: 12,
    question: "What unwanted variation should we control?",
    purpose: "Identify nuisance variation that could obscure treatment effects without turning too many customer segments into separate treatment cells.",
    transition: "Because treatment settings are known, ATLAS will now check whether nuisance variation should be controlled.",
    output: "A blocking or stratification decision.",
    nextLabel: "Randomization",
    nextQuestion: "How do we eliminate allocation bias?",
  },
  {
    id: "experimental-design-6",
    route: "/workflow/experimental-design/6",
    label: "Randomization",
    shortLabel: "Randomization",
    stepNumber: 6,
    totalSteps: 12,
    question: "How do we eliminate allocation bias?",
    purpose: "Assign treatments fairly and reproducibly across eligible experimental units.",
    transition: "Because nuisance variation is reviewed, ATLAS will now define fair treatment assignment.",
    output: "A reproducible assignment plan.",
    nextLabel: "Sample Size",
    nextQuestion: "Do we have enough data to detect a meaningful effect?",
  },
  {
    id: "experimental-design-7",
    route: "/workflow/experimental-design/7",
    label: "Sample Size",
    shortLabel: "Sample",
    stepNumber: 7,
    totalSteps: 12,
    question: "Do we have enough data to detect a meaningful effect?",
    purpose: "Balance statistical power, minimum practical effect, and operational capacity.",
    transition: "Because randomization is defined, ATLAS will now test whether the design is adequately powered.",
    output: "A power and sample-size recommendation.",
    nextLabel: "Monte Carlo Simulation",
    nextQuestion: "What outcomes should we expect before running the experiment?",
  },
  {
    id: "experimental-design-8",
    route: "/workflow/experimental-design/8",
    label: "Monte Carlo Simulation",
    shortLabel: "Monte",
    stepNumber: 8,
    totalSteps: 12,
    question: "What outcomes should we expect before running the experiment?",
    purpose: "Stress-test the design under uncertainty before launch.",
    transition: "Because the sample plan is defined, ATLAS will now simulate expected power and decision risk.",
    output: "A design validation simulation.",
    nextLabel: "Experiment Run Plan",
    nextQuestion: "How will we execute and monitor the experiment?",
  },
  {
    id: "experimental-design-9",
    route: "/workflow/experimental-design/9",
    label: "Experiment Run Plan",
    shortLabel: "Run Plan",
    stepNumber: 9,
    totalSteps: 12,
    question: "How will we execute and monitor the experiment?",
    purpose: "Execute and monitor the experiment while preserving treatment integrity.",
    transition: "Because launch risk is simulated, ATLAS will now document execution controls and monitoring checks.",
    output: "A controlled run plan.",
    nextLabel: "ANOVA",
    nextQuestion: "What mattered statistically?",
  },
  {
    id: "experimental-design-10",
    route: "/workflow/experimental-design/10",
    label: "ANOVA",
    shortLabel: "ANOVA",
    stepNumber: 10,
    totalSteps: 12,
    question: "What mattered statistically?",
    purpose: "Estimate main effects, interactions, residual variation, and statistical evidence.",
    transition: "Because the experiment has an execution plan, ATLAS will now define the statistical evidence structure.",
    output: "An ANOVA model and interpretation plan.",
    nextLabel: "Optimization",
    nextQuestion: "What configuration should we deploy?",
  },
  {
    id: "experimental-design-11",
    route: "/workflow/experimental-design/11",
    label: "Optimization",
    shortLabel: "Optimization",
    stepNumber: 11,
    totalSteps: 12,
    question: "What configuration should we deploy?",
    purpose: "Select the best treatment configuration supported by evidence and constraints.",
    transition: "Because statistical effects are planned, ATLAS will now frame the constrained deployment decision.",
    output: "A recommended treatment configuration.",
    nextLabel: "Documentation",
    nextQuestion: "What evidence package proves the decision is defensible?",
  },
  {
    id: "experimental-design-12",
    route: "/workflow/experimental-design/12",
    label: "Documentation",
    shortLabel: "Documentation",
    stepNumber: 12,
    totalSteps: 12,
    question: "What evidence package proves the decision is defensible?",
    purpose: "Package assumptions, design choices, execution controls, analytical results, limitations, and recommendations.",
    transition: "Because the design decision is framed, ATLAS will now assemble the governance-ready evidence package.",
    output: "An audit-ready experimental design report.",
  },
];

const experimentalDesignSteps: WorkflowStep[] = experimentalDesignJourney.map((step, index) => ({
  id: step.id,
  label: step.label,
  shortLabel: step.shortLabel,
  route: step.route,
  description: step.purpose,
  required: index === 0 || index === experimentalDesignJourney.length - 1,
}));

export const workflowDefinitions: WorkflowDefinition[] = [
  {
    id: "predictive-modeling",
    label: "Predictive Modeling",
    description: "Regulated supervised model development from source data to documented champion model.",
    projectType: "predictive-modeling",
    steps: predictiveModelingSteps,
  },
  {
    id: "credit-risk-studio",
    label: "Credit Risk Studio",
    description: "Credit risk model development with RFE interpretation before final scoring.",
    projectType: "predictive-modeling",
    steps: creditRiskStudioSteps,
  },
  {
    id: "ab-testing",
    label: "A/B Testing",
    description: "Plan, validate, analyze, document, and monitor controlled A/B experiments.",
    projectType: "ab-testing",
    steps: placeholderSteps("ab-testing", [
      ["Project Context", "Define experiment name, objective, owners, hypothesis, decision context, dates, risk, and governance notes."],
      ["Data Acquisition and Experiment Mapping", "Select or upload the experiment dataset, map unit, treatment, control, outcome, exposure, segment, and date/time fields, then validate the mapping."],
      ["Experiment Setup", "Define experiment type, design, treatment, control, assignment unit, randomization unit, analysis unit, and windows."],
      ["Population and Eligibility", "Document eligible population, inclusion and exclusion criteria, missingness handling, duplicates, spillover, and representativeness."],
      ["Treatment / Control Design", "Define treatment and control columns, values, descriptions, assignment method, allocation ratio, randomization notes, and contamination risk."],
      ["Randomization Check", "Check sample ratio, treatment/control sizes, exposure balance, segment balance, missingness balance, and randomization concerns."],
      ["Metrics Setup", "Define primary, secondary, guardrail, segment metrics, success event, confidence level, and multiple-testing policy."],
      ["Power and Sample Size", "Calculate binary proportion sample size, current power status, and detectable effect with current sample."],
      ["Experiment EDA", "Review treatment/control counts, outcome distribution, conversion by group, exposure distribution, missingness, duplicates, and segment sizes."],
      ["Experiment Analysis", "Estimate conversion rates, absolute lift, relative lift, standard error, confidence interval, p-value, and decision flags."],
      ["Segment Analysis", "Evaluate lift by day and hour segments with multiple-comparison warnings and sample-size flags."],
      ["Business Impact", "Translate lift into incremental conversions, revenue, cost, net impact, ROI, and break-even lift."],
      ["Decision Recommendation", "Document launch, keep control, run longer, segmented rollout, inconclusive, or do-not-launch decision with reviewer notes."],
      ["Documentation Review", "Map experiment evidence to Model Documentation Studio sections and appendices."],
      ["Post-Decision Plan", "Define the post-decision strategy for run-longer tests, holdout continuation, slow rollouts, segmented rollouts, keep-control decisions, or full treatment launches."],
    ]),
  },
  {
    id: "experimental-design",
    label: "Experimental Design",
    description: "Design and analyze multi-factor experiments with blocking, randomization, and interaction review.",
    projectType: "experimental-design",
    steps: experimentalDesignSteps,
  },
  {
    id: "optimization",
    label: "Optimization",
    description: "Build governed, data-backed optimization studies from source data through a validated decision and implementation plan.",
    projectType: "optimization",
    steps: placeholderSteps("optimization", [
      ["Project Context", "Define the business decision, accountable owner, population, decision cadence, value measure, risk appetite, and governance boundary."],
      ["Data Acquisition", "Choose a generic single-table optimizer, the transportation and logistics template, or manual formulation, then register every required governed full-dataset input."],
      ["Formulation Readiness", "Validate full-artifact scope, schema mapping, normalized decision grain, coefficient coverage, bounds, generated constraints, and whether the formulation is ready to solve."],
      ["Objective Function", "Choose maximize or minimize, define the unit of value, baseline, optimization horizon, and transparent mathematical objective."],
      ["Decision Variables", "Review or create controllable variables, lower and upper bounds, integer requirements, groups, and objective or risk coefficients."],
      ["Constraints & Business Rules", "Encode capacity, budget, policy, regulatory, concentration, service, and minimum-performance requirements."],
      ["Solver Configuration", "Select LP, MILP, or risk-adjusted nonlinear optimization with tolerances, runtime limits, and reproducibility controls."],
      ["Baseline & Scenarios", "Define the current-state baseline and alternative demand, capacity, risk, cost, and stress assumptions."],
      ["Optimize", "Run the governed solver and review objective improvement, decision values, feasibility, binding constraints, runtime, and optimality evidence."],
      ["Sensitivity & Tradeoffs", "Stress objective coefficients, bounds, and constraints to identify unstable decisions, shadow tradeoffs, and robust operating ranges."],
      ["Validation", "Validate mathematical feasibility, business-rule conformance, stability, independent replication, and out-of-sample or backtest evidence."],
      ["Decision Recommendation", "Translate the optimized solution into an accountable recommendation with alternatives, limitations, approvals, and residual risks."],
      ["Implementation & Monitoring", "Define rollout, system integration, human overrides, fallback actions, KPI and constraint monitoring, drift triggers, and re-optimization cadence."],
      ["Documentation", "Generate an audit-ready optimization package containing data lineage, formulation, solver evidence, results, sensitivity, validation, decision, and monitoring artifacts."],
    ]),
  },
  {
    id: "time_series_forecasting",
    label: "Time Series & Forecasting",
    description: "Forecast, monitor, diagnose, and document time-dependent outcomes with temporal splits, backtesting, intervals, anomaly review, and monitoring evidence.",
    projectType: "time_series_forecasting",
    steps: timeSeriesForecastingSteps,
  },
  {
    id: "llm_generative_ai",
    label: "LLM / Generative AI",
    description: "Build, evaluate, govern, and document language-model workflows including RAG, prompt design, extraction, summarization, classification, and human review.",
    projectType: "llm_generative_ai",
    steps: llmGenerativeAiSteps,
  },
  {
    id: "reinforcement-learning",
    label: "Reinforcement Learning",
    description: "Frame policy-learning projects with environment, rewards, simulation, and policy validation.",
    projectType: "reinforcement-learning",
    steps: placeholderSteps("reinforcement-learning", [
      ["Project Context", "Define policy objective, constraints, and permitted use."],
      ["Environment Definition", "Document the environment and episode structure."],
      ["State Space", "Define available state features and observability limits."],
      ["Action Space", "Define possible actions and policy constraints."],
      ["Reward Function", "Specify reward, penalties, and delayed outcomes."],
      ["Offline Data", "Review logged policy data and counterfactual limits."],
      ["Simulation", "Build or document simulation assumptions."],
      ["Policy Learning", "Train or evaluate candidate policies."],
      ["Policy Evaluation", "Assess off-policy metrics, safety, and robustness."],
      ["Deployment Plan", "Define controlled rollout, monitoring, and fallback."],
      ["Documentation", "Generate RL documentation."],
    ]),
  },
  {
    id: "computer-vision",
    label: "Computer Vision",
    description: "Build image and video workflows for classification, detection, segmentation, or quality review.",
    projectType: "computer-vision",
    steps: placeholderSteps("computer-vision", [
      ["Project Context", "Define the visual task, intended use, risk level, and operational workflow."],
      ["Image Source Review", "Document image/video sources, acquisition devices, resolution, consent, and retention."],
      ["Annotation Strategy", "Define labels, bounding boxes, masks, QA process, and reviewer agreement."],
      ["Data Quality", "Review blur, lighting, occlusion, duplicate images, class imbalance, and corrupted files."],
      ["Preprocessing and Augmentation", "Choose resizing, normalization, cropping, augmentation, and leakage controls."],
      ["Model Selection", "Compare baseline CNN, transfer learning, detection, segmentation, or multimodal approaches."],
      ["Evaluation", "Review accuracy, F1, AUC, mAP, IoU, confusion patterns, and threshold tradeoffs."],
      ["Error Analysis", "Inspect failure cases by class, device, lighting, demographic proxy, and operational scenario."],
      ["Deployment and Monitoring", "Define latency, hardware, drift, image quality, and human review monitoring."],
      ["Computer Vision Documentation", "Generate computer vision model documentation."],
    ]),
  },
  {
    id: "graph-analytics",
    label: "Graph Analytics",
    description: "Analyze entities, relationships, communities, influence, fraud rings, and network risk.",
    projectType: "graph-analytics",
    steps: placeholderSteps("graph-analytics", [
      ["Project Context", "Define the graph objective, entities, relationships, and intended business action."],
      ["Entity and Edge Definition", "Document node types, edge types, directionality, weights, and time validity."],
      ["Graph Construction", "Define linkage rules, deduplication, identity resolution, and graph refresh cadence."],
      ["Network Quality", "Review isolated nodes, giant components, degree outliers, duplicate edges, and suspicious linkage artifacts."],
      ["Feature Engineering", "Create centrality, community, neighborhood, path, and temporal graph features."],
      ["Method Selection", "Choose community detection, link prediction, node classification, embeddings, or rules."],
      ["Validation", "Review stability, known-case capture, precision/recall, community coherence, and leakage controls."],
      ["Investigation Workflow", "Define alerting, case review, explainability, and analyst feedback capture."],
      ["Monitoring Plan", "Monitor graph growth, degree distribution, component drift, and model/action performance."],
      ["Graph Analytics Documentation", "Generate graph analytics study documentation."],
    ]),
  },
];

export const projectTypeOptions: Array<{ value: ProjectType; label: string; description: string }> = [
  { value: "predictive-modeling", label: "Predictive Modeling", description: "Classification or regression model development." },
  { value: "ab-testing", label: "Experimentation", description: "Design, run, analyze, and document controlled experiments, including A/B tests and experimental designs." },
  { value: "optimization", label: "Optimization", description: "Objective, constraints, and solver-driven decisions." },
  { value: "time_series_forecasting", label: "Time Series & Forecasting", description: "Forecast, monitor, and diagnose time-dependent outcomes with trend, seasonality, lag, anomaly, stability, and backtesting controls." },
  { value: "llm_generative_ai", label: "LLM / Generative AI", description: "Build, evaluate, govern, and document language-model workflows including RAG, prompt design, extraction, summarization, classification, and human review." },
  { value: "graph-analytics", label: "Graph Analytics", description: "Network, entity, relationship, and graph-based analytical workflows." },
  { value: "computer-vision", label: "Computer Vision", description: "Image and video model workflows." },
  { value: "reinforcement-learning", label: "Reinforcement Learning", description: "Policy learning and decision optimization." },
  { value: "custom-workflow", label: "Custom Workflow", description: "User-defined workflow steps." },
];

export const workflowTemplates: WorkflowTemplate[] = [
  {
    id: "predictive-modeling",
    workflowId: "predictive-modeling",
    label: "Predictive Modeling",
    description: "General supervised modeling workflow with governance-ready documentation.",
    projectType: "predictive-modeling",
    commonUseCases: ["Credit risk", "Response modeling", "Attrition", "Regression"],
    governanceIntensity: "medium",
  },
  {
    id: "regulated-credit-model",
    workflowId: "predictive-modeling",
    label: "Regulated Credit Model",
    description: "Predictive modeling template tuned for SR 11-7, fair lending, FCRA, ECOA, and model validation.",
    projectType: "predictive-modeling",
    commonUseCases: ["Application risk", "Account management", "Collections", "Line assignment"],
    governanceIntensity: "high",
  },
  {
    id: "fraud-detection-model",
    workflowId: "predictive-modeling",
    label: "Fraud Detection Model",
    description: "Rare-event predictive modeling template with lift, recall, PR-AUC, and OOT stability emphasis.",
    projectType: "predictive-modeling",
    commonUseCases: ["Transaction fraud", "Synthetic identity", "AML/KYC alerts"],
    governanceIntensity: "high",
  },
  {
    id: "ab-test",
    workflowId: "ab-testing",
    label: "A/B Test",
    description: "Experiment workflow for controlled treatment comparisons.",
    projectType: "ab-testing",
    commonUseCases: ["Pricing test", "Marketing offer", "UX experiment", "Policy test"],
    governanceIntensity: "medium",
  },
  {
    id: "experimental-design",
    workflowId: "experimental-design",
    label: "Experimental Design",
    description: "Multi-factor experimental design workflow.",
    projectType: "experimental-design",
    commonUseCases: ["Factor screening", "Process optimization", "Treatment interactions"],
    governanceIntensity: "medium",
  },
  {
    id: "optimization",
    workflowId: "optimization",
    label: "Optimization",
    description: "Business optimization workflow with constraints and sensitivity review.",
    projectType: "optimization",
    commonUseCases: ["Offer optimization", "Resource allocation", "Collections strategy"],
    governanceIntensity: "medium",
  },
  {
    id: "time_series_forecasting",
    workflowId: "time_series_forecasting",
    label: "Time Series & Forecasting",
    description: "Forecast, backtest, monitor, diagnose, and document time-dependent financial-services outcomes.",
    projectType: "time_series_forecasting",
    commonUseCases: ["Transaction volume", "Fraud spikes", "Loss forecasting", "Liquidity trends", "Call center demand"],
    governanceIntensity: "medium",
  },
  {
    id: "reinforcement-learning",
    workflowId: "reinforcement-learning",
    label: "Reinforcement Learning",
    description: "Policy-learning workflow with simulation and safety review.",
    projectType: "reinforcement-learning",
    commonUseCases: ["Next best action", "Adaptive treatments", "Dynamic pricing"],
    governanceIntensity: "high",
  },
  {
    id: "llm_generative_ai",
    workflowId: "llm_generative_ai",
    label: "LLM / Generative AI",
    description: "Governed language-model workflow for RAG, prompt design, classification, extraction, summarization, and human review.",
    projectType: "llm_generative_ai",
    commonUseCases: ["Policy Q&A", "Complaint classification", "Narrative extraction", "Case summarization", "Analyst copilots"],
    governanceIntensity: "high",
  },
  {
    id: "computer-vision",
    workflowId: "computer-vision",
    label: "Computer Vision",
    description: "Image and video analytics workflow.",
    projectType: "computer-vision",
    commonUseCases: ["Image classification", "Object detection", "Quality review"],
    governanceIntensity: "high",
  },
  {
    id: "graph-analytics",
    workflowId: "graph-analytics",
    label: "Graph Analytics",
    description: "Network/entity analytics workflow.",
    projectType: "graph-analytics",
    commonUseCases: ["Fraud rings", "Entity resolution", "Community detection"],
    governanceIntensity: "high",
  },
];

export function getWorkflowDefinition(workflowId: string | undefined) {
  return workflowDefinitions.find((workflow) => workflow.id === workflowId) ?? workflowDefinitions[0];
}

export function getWorkflowForProjectType(projectType: ProjectType) {
  return workflowDefinitions.find((workflow) => workflow.projectType === projectType) ?? workflowDefinitions[0];
}

export function createCustomWorkflow(name: string, stepNames: string[]): WorkflowDefinition {
  const id = "custom-workflow";
  return {
    id,
    label: name.trim() || "Custom Workflow",
    description: "Locally configured custom ATLAS workflow.",
    projectType: "custom-workflow",
    steps: stepNames
      .filter((stepName) => stepName.trim())
      .map((stepName, index) => ({
        id: `${id}-${index + 1}`,
        label: stepName.trim(),
        shortLabel: stepName.trim().split(" ")[0],
        route: `/workflow/${id}/${index + 1}`,
        description: `Complete and document ${stepName.trim()}.`,
        required: true,
      })),
  };
}
