export type FinancialDomain =
  | "credit_risk"
  | "fraud_aml"
  | "marketing_profitability"
  | "model_risk_governance"
  | "portfolio_risk"
  | "decision_strategy";

export type RegulatoryRelevance = {
  adverseAction?: boolean;
  fairLending?: boolean;
  modelRisk?: boolean;
  explainability?: boolean;
  pricingDecision?: boolean;
};

export type CreditRiskContext = {
  productType?: string;
  modelPurpose?: string;
  targetWindow?: string;
  targetEvent?: string;
  scorecardStyle?: string;
  pdoConfigured?: boolean;
  baseOddsConfigured?: boolean;
  baseScoreConfigured?: boolean;
};

export type CreditRiskChecklistItem = {
  technique: string;
  label: string;
  category: string;
  required: boolean;
  status: string;
  count: number;
  ready: number;
  documentationSections: string[];
};

export type CreditRiskEvidenceChecklist = {
  domain: "credit_risk";
  label: string;
  totalRequired: number;
  readyRequired: number;
  coverageScore: number;
  items: CreditRiskChecklistItem[];
  missingRequired: string[];
  context?: CreditRiskContext;
};

export const FINANCIAL_DOMAIN_OPTIONS: Array<{ value: FinancialDomain; label: string; definition: string }> = [
  { value: "credit_risk", label: "Credit Risk / Underwriting", definition: "Default, delinquency, approval, scorecard, and underwriting model evidence." },
  { value: "fraud_aml", label: "Fraud / AML", definition: "Fraud, AML, KYC, suspicious activity, and investigative model evidence." },
  { value: "marketing_profitability", label: "Marketing / Profitability", definition: "Response, attrition, conversion, customer value, and campaign profitability evidence." },
  { value: "model_risk_governance", label: "Model Risk / Governance", definition: "Validation, documentation, limitations, approvals, and monitoring evidence." },
  { value: "portfolio_risk", label: "Portfolio Risk", definition: "Portfolio stability, challenger/champion, calibration, and macro-risk evidence." },
  { value: "decision_strategy", label: "Decision Strategy", definition: "Cutoffs, pricing, policy rules, and strategy tree evidence." },
];

export const CREDIT_RISK_TECHNIQUE_OPTIONS = [
  { value: "pdo", label: "PDO Scaling", category: "Underwriting Model Techniques" },
  { value: "woe", label: "Weight of Evidence", category: "Underwriting Model Techniques" },
  { value: "iv", label: "Information Value", category: "Underwriting Model Techniques" },
  { value: "manual_binning", label: "Manual Characteristic Binning", category: "Underwriting Model Techniques" },
  { value: "reject_inference", label: "Reject Inference", category: "Underwriting Model Techniques" },
  { value: "ttc", label: "Through-the-Cycle Calibration", category: "Portfolio Risk" },
  { value: "pit", label: "Point-in-Time Calibration", category: "Portfolio Risk" },
  { value: "psi", label: "Population Stability Index", category: "Portfolio Risk" },
  { value: "challenger_champion", label: "Challenger / Champion", category: "Portfolio Risk" },
  { value: "adverse_action", label: "Adverse Action Engineering", category: "Regulatory / Governance" },
  { value: "fair_lending", label: "Fair Lending Testing", category: "Regulatory / Governance" },
  { value: "monotonic_constraints", label: "Monotonic Variable Constraints", category: "Regulatory / Governance" },
  { value: "cutoff_optimization", label: "Cutoff Optimization", category: "Decision Strategy" },
  { value: "strategy_trees", label: "Strategy Trees / Rule Overlays", category: "Decision Strategy" },
  { value: "risk_based_pricing", label: "Risk-Based Pricing", category: "Decision Strategy" },
  { value: "monotonic_gbm", label: "Monotonic GBM", category: "Modern Underwriting" },
  { value: "surrogate_scorecard", label: "Surrogate Scorecard", category: "Modern Underwriting" },
  { value: "scorecard_scaling", label: "Scorecard Scaling", category: "Modern Underwriting" },
  { value: "odds_calibration", label: "Odds Calibration", category: "Modern Underwriting" },
];

export const PRODUCT_TYPE_OPTIONS = ["Credit Card", "Auto Loan", "Mortgage", "Personal Loan", "Small Business", "Deposit", "Other"];
export const MODEL_PURPOSE_OPTIONS = ["Origination", "Account Management", "Collections", "Line Assignment", "Pricing", "Fraud Review", "Portfolio Monitoring", "Other"];

export const CREDIT_RISK_DOCUMENTATION_MAPPING: Record<string, string[]> = {
  pdo: ["Model Interpretation", "Champion Model", "Appendix"],
  woe: ["Feature Engineering", "Interpretability Notes", "Appendix"],
  iv: ["Feature Engineering", "Model Diagnostics", "Appendix"],
  manual_binning: ["Feature Engineering", "Interpretability Notes", "Fair Lending / Compliance Considerations"],
  reject_inference: ["Data Sources", "Target Definition", "Model Limitations"],
  ttc: ["Performance Summary", "Monitoring Recommendations"],
  pit: ["Performance Summary", "Monitoring Recommendations"],
  psi: ["Model Diagnostics", "Monitoring Recommendations"],
  challenger_champion: ["Candidate Models", "Champion Model", "Monitoring Recommendations"],
  adverse_action: ["Interpretability Notes", "Fair Lending / Compliance Considerations"],
  fair_lending: ["Fair Lending / Compliance Considerations", "Model Limitations"],
  monotonic_constraints: ["Feature Engineering", "Interpretability Notes", "Fair Lending / Compliance Considerations"],
  cutoff_optimization: ["Champion Model", "Performance Summary", "Model Limitations"],
  strategy_trees: ["Model Purpose", "Implementation Plan", "Monitoring Recommendations"],
  risk_based_pricing: ["Intended Use", "Fair Lending / Compliance Considerations", "Model Limitations"],
  monotonic_gbm: ["Candidate Models", "Interpretability Notes", "Fair Lending / Compliance Considerations"],
  surrogate_scorecard: ["Model Interpretation", "Model Limitations", "Appendix"],
  scorecard_scaling: ["Champion Model", "Model Interpretation", "Appendix"],
  odds_calibration: ["Performance Summary", "Model Diagnostics", "Appendix"],
};

export const CREDIT_RISK_FORM_DEFINITIONS: Record<string, { title: string; fields: Array<{ key: string; label: string; helper: string }> }> = {
  woe: { title: "Add WOE / IV Evidence", fields: [
    { key: "characteristic", label: "Characteristic", helper: "Variable or scorecard characteristic reviewed." },
    { key: "woeSummary", label: "WOE Summary", helper: "Describe bin directionality and business meaning." },
    { key: "ivValue", label: "IV Value", helper: "Information Value or range for this characteristic." },
  ] },
  iv: { title: "Add WOE / IV Evidence", fields: [
    { key: "characteristic", label: "Characteristic", helper: "Variable or scorecard characteristic reviewed." },
    { key: "ivValue", label: "IV Value", helper: "Information Value or range for this characteristic." },
    { key: "selectionDecision", label: "Selection Decision", helper: "Keep, review, exclude, or monitor." },
  ] },
  pdo: { title: "Add PDO Scaling Evidence", fields: [
    { key: "pdo", label: "PDO", helper: "Points to double the odds." },
    { key: "baseScore", label: "Base Score", helper: "Score assigned at the base odds." },
    { key: "baseOdds", label: "Base Odds", helper: "Base odds such as 20:1 good-to-bad." },
  ] },
  manual_binning: { title: "Add Manual Binning Evidence", fields: [
    { key: "characteristic", label: "Characteristic", helper: "Variable manually binned." },
    { key: "binningRationale", label: "Binning Rationale", helper: "Business, monotonicity, stability, or adverse-action rationale." },
    { key: "fairLendingReview", label: "Fair Lending Review", helper: "Document proxy or disparate-impact review." },
  ] },
  reject_inference: { title: "Add Reject Inference Evidence", fields: [
    { key: "method", label: "Method", helper: "Fuzzy augmentation, parceling, extrapolation, or not applied." },
    { key: "population", label: "Population", helper: "Rejected or unbooked population considered." },
    { key: "limitation", label: "Limitation", helper: "Assumptions and validation caveats." },
  ] },
  fair_lending: { title: "Add Fair Lending Evidence", fields: [
    { key: "protectedClass", label: "Protected Class / Proxy", helper: "Group or proxy considered." },
    { key: "testPerformed", label: "Test Performed", helper: "Disparate impact, marginal effect, proxy screen, or override review." },
    { key: "finding", label: "Finding", helper: "Pass, review required, limitation, or remediation." },
  ] },
  adverse_action: { title: "Add Adverse Action Evidence", fields: [
    { key: "reasonCodeMethod", label: "Reason Code Method", helper: "Scorecard reason codes, SHAP mapping, surrogate logic, or policy rules." },
    { key: "explainabilityControl", label: "Explainability Control", helper: "How reason codes are validated and governed." },
    { key: "consumerImpact", label: "Consumer Impact", helper: "Where this affects approvals, pricing, or credit line assignment." },
  ] },
  psi: { title: "Add PSI Evidence", fields: [
    { key: "population", label: "Population Compared", helper: "Development vs OOT, test, monitoring window, or production." },
    { key: "psiValue", label: "PSI Value", helper: "Population Stability Index result." },
    { key: "status", label: "Status", helper: "Pass, warning, fail, or monitor." },
  ] },
  cutoff_optimization: { title: "Add Cutoff Optimization Evidence", fields: [
    { key: "cutoff", label: "Cutoff", helper: "Score, probability, or odds cutoff." },
    { key: "objective", label: "Business Objective", helper: "Loss, approval rate, profit, conversion, or operational capacity." },
    { key: "tradeoff", label: "Tradeoff", helper: "Approval, bad rate, fairness, pricing, or revenue impact." },
  ] },
  risk_based_pricing: { title: "Add Risk-Based Pricing Evidence", fields: [
    { key: "pricingBands", label: "Pricing Bands", helper: "Risk tiers or score bands used in pricing." },
    { key: "complianceReview", label: "Compliance Review", helper: "Fair Lending, FCRA/ECOA, or pricing governance note." },
    { key: "businessImpact", label: "Business Impact", helper: "Revenue, approval, margin, or customer-impact rationale." },
  ] },
};

export function techniqueLabel(value?: string) {
  return CREDIT_RISK_TECHNIQUE_OPTIONS.find((item) => item.value === value)?.label ?? (value ? value.replace(/_/g, " ") : "Credit Risk Evidence");
}

export function regulatoryForTechnique(technique: string): RegulatoryRelevance {
  return {
    adverseAction: ["adverse_action", "manual_binning", "scorecard_scaling"].includes(technique),
    fairLending: ["fair_lending", "manual_binning", "risk_based_pricing", "monotonic_constraints", "monotonic_gbm"].includes(technique),
    modelRisk: true,
    explainability: ["woe", "iv", "manual_binning", "adverse_action", "surrogate_scorecard", "scorecard_scaling"].includes(technique),
    pricingDecision: ["risk_based_pricing", "cutoff_optimization"].includes(technique),
  };
}
