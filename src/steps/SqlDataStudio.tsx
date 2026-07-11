import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  BarChart3,
  ChevronDown,
  ChevronRight,
  Clipboard,
  Code2,
  Copy,
  Database,
  Download,
  FileCode2,
  FolderTree,
  History,
  Play,
  Save,
  Search,
  ShieldAlert,
  Sparkles,
  Table2,
  TerminalSquare,
  Trash2,
  Wand2,
} from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { getDatasetProfile, listDatasets, type DatasetProfile, type DatasetSummary } from "../lib/datasetLibrary";
import { createEvidence } from "../lib/evidenceGraph";
import {
  deleteSqlQuery,
  downloadBlob,
  exportSqlResultExcel,
  listSavedSqlQueries,
  registerSqlResult,
  runSqlPreview,
  safeSqlAlias,
  saveSqlQuery,
  validateSql,
  type SavedSqlQuery,
  type SqlDatasetRef,
  type SqlPreviewResult,
} from "../lib/sqlDataStudio";
import { useWorkflowStore } from "../state/useWorkflowStore";

type SourceType = "dataset_library_preview" | "saved_query" | "external_metadata";
type AssistantTab = "templates" | "financial" | "mapping" | "governance" | "help";
type BottomTab = "results" | "schema" | "profile" | "messages" | "history" | "lineage";
type ObjectExplorerTab = "tables" | "saved" | "results" | "connectors";
type TemplateCategory =
  | "Customer / Account Analytics"
  | "Credit Risk"
  | "Fraud / AML"
  | "Marketing / Campaigns"
  | "Model Development"
  | "Monitoring"
  | "Data Quality"
  | "Demo Dataset Examples";

type SqlTemplate = {
  name: string;
  category: TemplateCategory;
  description: string;
  requiredColumns: string[];
  sql: string;
  tags: string[];
};

type QueryHistoryEntry = {
  id: string;
  timestamp: string;
  sql: string;
  status: string;
  runtimeMs: number;
  rowCount: number;
  tablesUsed: string[];
  warnings: string[];
};

const EXTERNAL_CONNECTORS = ["Snowflake", "BigQuery", "Postgres", "Oracle", "SQL Server", "Teradata", "SAS / Viya source"];
const HISTORY_KEY = "atlas-sql-studio-query-history";

const SQL_SNIPPETS = [
  { label: "Insert SELECT *", sql: "SELECT *\nFROM {table}\nLIMIT 100;" },
  { label: "Insert GROUP BY", sql: "\nGROUP BY {column}\nORDER BY COUNT(*) DESC" },
  { label: "Insert LEFT JOIN", sql: "\nLEFT JOIN {table2} b\n    ON a.{key} = b.{key}" },
  { label: "Insert CASE WHEN", sql: "CASE\n    WHEN {column} IS NULL THEN 'Missing'\n    ELSE 'Populated'\nEND AS {column}_flag" },
  { label: "Insert date filter", sql: "\nWHERE {date_column} >= '2026-01-01'" },
  { label: "Insert count distinct", sql: "COUNT(DISTINCT {customer_id}) AS distinct_customers" },
  { label: "Insert window rank", sql: "ROW_NUMBER() OVER (PARTITION BY {customer_id} ORDER BY {date_column} DESC) AS recency_rank" },
];

const FINANCIAL_TEMPLATES: SqlTemplate[] = [
  template("Customer 360 summary", "Customer / Account Analytics", "Summarize account and transaction footprint by customer.", ["customer_id", "account_id", "amount"], "SELECT\n    customer_id,\n    COUNT(DISTINCT account_id) AS account_count,\n    COUNT(*) AS record_count,\n    SUM(amount) AS total_amount\nFROM {table}\nGROUP BY customer_id\nORDER BY total_amount DESC\nLIMIT 100;", ["customer", "account"]),
  template("Account balance snapshot", "Customer / Account Analytics", "Latest balance by account.", ["account_id", "date_column", "amount"], "SELECT\n    account_id,\n    MAX(date_column) AS latest_snapshot_date,\n    AVG(amount) AS average_balance\nFROM {table}\nGROUP BY account_id\nLIMIT 100;", ["account"]),
  template("Active customer flag", "Customer / Account Analytics", "Create an active/inactive customer flag from recent activity.", ["customer_id", "date_column"], "SELECT\n    customer_id,\n    MAX(date_column) AS last_activity_date,\n    CASE WHEN MAX(date_column) >= '2026-01-01' THEN 1 ELSE 0 END AS active_customer_flag\nFROM {table}\nGROUP BY customer_id\nLIMIT 100;", ["customer"]),
  template("New vs existing customer", "Customer / Account Analytics", "Classify customers by first observed activity.", ["customer_id", "date_column"], "SELECT\n    customer_id,\n    MIN(date_column) AS first_seen_date,\n    CASE WHEN MIN(date_column) >= '2026-01-01' THEN 'New' ELSE 'Existing' END AS customer_status\nFROM {table}\nGROUP BY customer_id\nLIMIT 100;", ["customer"]),
  template("Customer tenure bands", "Customer / Account Analytics", "Bucket customer tenure for segmentation.", ["customer_id", "date_column"], "SELECT\n    customer_id,\n    CASE\n        WHEN MIN(date_column) >= '2026-01-01' THEN '0-6 months'\n        WHEN MIN(date_column) >= '2025-01-01' THEN '6-18 months'\n        ELSE '18+ months'\n    END AS tenure_band\nFROM {table}\nGROUP BY customer_id\nLIMIT 100;", ["customer"]),
  template("Householding summary", "Customer / Account Analytics", "Summarize customers by household identifier.", ["customer_id", "household_id"], "SELECT\n    household_id,\n    COUNT(DISTINCT customer_id) AS customers_in_household\nFROM {table}\nGROUP BY household_id\nORDER BY customers_in_household DESC\nLIMIT 100;", ["householding"]),
  template("Delinquency rate by segment", "Credit Risk", "Calculate delinquency prevalence by risk segment.", ["segment_column", "target_column"], "SELECT\n    segment_column,\n    COUNT(*) AS accounts,\n    AVG(CASE WHEN target_column = 1 THEN 1.0 ELSE 0.0 END) AS delinquency_rate\nFROM {table}\nGROUP BY segment_column\nORDER BY delinquency_rate DESC\nLIMIT 100;", ["risk"]),
  template("Charge-off rate by vintage", "Credit Risk", "Review charge-off rates by origination vintage.", ["date_column", "target_column"], "SELECT\n    SUBSTR(date_column, 1, 7) AS vintage_month,\n    COUNT(*) AS accounts,\n    AVG(CASE WHEN target_column = 1 THEN 1.0 ELSE 0.0 END) AS charge_off_rate\nFROM {table}\nGROUP BY vintage_month\nORDER BY vintage_month\nLIMIT 100;", ["risk", "vintage"]),
  template("Utilization bands", "Credit Risk", "Create utilization bands for credit exposure review.", ["amount_column"], "SELECT\n    CASE\n        WHEN amount_column < 0.30 THEN 'Low utilization'\n        WHEN amount_column < 0.70 THEN 'Moderate utilization'\n        ELSE 'High utilization'\n    END AS utilization_band,\n    COUNT(*) AS account_count\nFROM {table}\nGROUP BY utilization_band\nLIMIT 100;", ["risk"]),
  template("Credit line exposure", "Credit Risk", "Summarize total exposure by segment.", ["segment_column", "amount_column"], "SELECT\n    segment_column,\n    COUNT(*) AS accounts,\n    SUM(amount_column) AS total_exposure,\n    AVG(amount_column) AS average_exposure\nFROM {table}\nGROUP BY segment_column\nORDER BY total_exposure DESC\nLIMIT 100;", ["risk"]),
  template("Risk score distribution", "Credit Risk", "Profile score distribution by segment.", ["score_column", "segment_column"], "SELECT\n    segment_column,\n    COUNT(*) AS n,\n    AVG(score_column) AS avg_score,\n    MIN(score_column) AS min_score,\n    MAX(score_column) AS max_score\nFROM {table}\nGROUP BY segment_column\nLIMIT 100;", ["risk", "score"]),
  template("Vintage performance table", "Credit Risk", "Build a vintage performance table.", ["date_column", "target_column"], "SELECT\n    SUBSTR(date_column, 1, 7) AS vintage_month,\n    COUNT(*) AS booked_accounts,\n    SUM(CASE WHEN target_column = 1 THEN 1 ELSE 0 END) AS bad_accounts\nFROM {table}\nGROUP BY vintage_month\nORDER BY vintage_month\nLIMIT 100;", ["risk", "vintage"]),
  template("Roll-rate matrix", "Credit Risk", "Prepare delinquency roll-rate counts.", ["account_id", "segment_column"], "SELECT\n    segment_column AS prior_status,\n    segment_column AS current_status,\n    COUNT(DISTINCT account_id) AS accounts\nFROM {table}\nGROUP BY prior_status, current_status\nLIMIT 100;", ["risk"]),
  template("High-risk transaction review", "Fraud / AML", "Rank large or high-risk transactions.", ["customer_id", "date_column", "amount_column"], "SELECT\n    customer_id,\n    date_column,\n    amount_column\nFROM {table}\nWHERE amount_column IS NOT NULL\nORDER BY amount_column DESC\nLIMIT 100;", ["fraud", "aml"]),
  template("Velocity rules", "Fraud / AML", "Count transaction velocity by customer and day.", ["customer_id", "date_column"], "SELECT\n    customer_id,\n    date_column,\n    COUNT(*) AS daily_transaction_count\nFROM {table}\nGROUP BY customer_id, date_column\nORDER BY daily_transaction_count DESC\nLIMIT 100;", ["fraud"]),
  template("Duplicate transaction detection", "Fraud / AML", "Find repeated customer/date/amount combinations.", ["customer_id", "date_column", "amount_column"], "SELECT\n    customer_id,\n    date_column,\n    amount_column,\n    COUNT(*) AS duplicate_count\nFROM {table}\nGROUP BY customer_id, date_column, amount_column\nHAVING COUNT(*) > 1\nORDER BY duplicate_count DESC\nLIMIT 100;", ["fraud", "data quality"]),
  template("Dormant account reactivation", "Fraud / AML", "Find activity after long dormant periods.", ["account_id", "date_column"], "SELECT\n    account_id,\n    MIN(date_column) AS first_activity,\n    MAX(date_column) AS latest_activity,\n    COUNT(*) AS activity_count\nFROM {table}\nGROUP BY account_id\nHAVING COUNT(*) > 1\nLIMIT 100;", ["fraud", "aml"]),
  template("Unusual merchant activity", "Fraud / AML", "Summarize high-frequency merchant activity.", ["merchant_id", "amount_column"], "SELECT\n    merchant_id,\n    COUNT(*) AS transaction_count,\n    SUM(amount_column) AS total_amount\nFROM {table}\nGROUP BY merchant_id\nORDER BY transaction_count DESC\nLIMIT 100;", ["fraud"]),
  template("Structuring / threshold activity", "Fraud / AML", "Find transactions near reporting thresholds.", ["amount_column"], "SELECT\n    COUNT(*) AS near_threshold_transactions,\n    SUM(amount_column) AS near_threshold_amount\nFROM {table}\nWHERE amount_column BETWEEN 9000 AND 10000;", ["aml"]),
  template("KYC missingness review", "Fraud / AML", "Profile missing KYC fields.", ["customer_id"], "SELECT\n    COUNT(*) AS total_records,\n    SUM(CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END) AS missing_customer_id\nFROM {table};", ["kyc", "data quality"]),
  template("Campaign population waterfall", "Marketing / Campaigns", "Build campaign eligibility counts.", ["customer_id"], "SELECT\n    'Initial population' AS step,\n    COUNT(DISTINCT customer_id) AS customers\nFROM {table}\nUNION ALL\nSELECT\n    'Eligible population' AS step,\n    COUNT(DISTINCT customer_id) AS customers\nFROM {table}\nLIMIT 100;", ["marketing"]),
  template("Response rate by campaign", "Marketing / Campaigns", "Compare response rates by campaign.", ["campaign_column", "target_column"], "SELECT\n    campaign_column,\n    COUNT(*) AS customers,\n    AVG(CASE WHEN target_column = 1 THEN 1.0 ELSE 0.0 END) AS response_rate\nFROM {table}\nGROUP BY campaign_column\nORDER BY response_rate DESC\nLIMIT 100;", ["marketing"]),
  template("Offer exposure summary", "Marketing / Campaigns", "Summarize offers by exposure group.", ["campaign_column"], "SELECT\n    campaign_column,\n    COUNT(*) AS exposures\nFROM {table}\nGROUP BY campaign_column\nORDER BY exposures DESC\nLIMIT 100;", ["marketing"]),
  template("Test/control comparison", "Marketing / Campaigns", "Compare treatment and control outcomes.", ["segment_column", "target_column"], "SELECT\n    segment_column AS test_group,\n    COUNT(*) AS customers,\n    AVG(CASE WHEN target_column = 1 THEN 1.0 ELSE 0.0 END) AS outcome_rate\nFROM {table}\nGROUP BY test_group\nLIMIT 100;", ["marketing", "testing"]),
  template("Channel performance", "Marketing / Campaigns", "Compare response by channel.", ["campaign_column", "target_column"], "SELECT\n    campaign_column AS channel,\n    COUNT(*) AS customers,\n    AVG(CASE WHEN target_column = 1 THEN 1.0 ELSE 0.0 END) AS response_rate\nFROM {table}\nGROUP BY channel\nORDER BY response_rate DESC\nLIMIT 100;", ["marketing"]),
  template("Suppression waterfall", "Marketing / Campaigns", "Summarize suppression reasons.", ["segment_column"], "SELECT\n    segment_column AS suppression_reason,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY suppression_reason\nORDER BY records DESC\nLIMIT 100;", ["marketing"]),
  template("Train/Test/OOT population summary", "Model Development", "Summarize modeling populations by source split.", ["target_column"], "SELECT\n    COUNT(*) AS total_rows,\n    SUM(CASE WHEN target_column = 1 THEN 1 ELSE 0 END) AS events,\n    AVG(CASE WHEN target_column = 1 THEN 1.0 ELSE 0.0 END) AS event_rate\nFROM {table};", ["modeling"]),
  template("Target event rate by split", "Model Development", "Calculate target event rate for classification data.", ["target_column"], "SELECT\n    target_column,\n    COUNT(*) AS row_count,\n    COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS population_share\nFROM {table}\nGROUP BY target_column\nORDER BY target_column;", ["modeling"]),
  template("Feature missingness summary", "Model Development", "Count missingness for key modeling fields.", ["amount_column", "score_column"], "SELECT\n    COUNT(*) AS total_rows,\n    SUM(CASE WHEN amount_column IS NULL THEN 1 ELSE 0 END) AS missing_amount,\n    SUM(CASE WHEN score_column IS NULL THEN 1 ELSE 0 END) AS missing_score\nFROM {table};", ["modeling", "data quality"]),
  template("Feature stability summary", "Model Development", "Prepare segment-level feature stability inputs.", ["segment_column", "amount_column"], "SELECT\n    segment_column,\n    COUNT(*) AS n,\n    AVG(amount_column) AS avg_value\nFROM {table}\nGROUP BY segment_column\nORDER BY n DESC\nLIMIT 100;", ["modeling", "monitoring"]),
  template("Score distribution", "Model Development", "Summarize model score distribution.", ["score_column"], "SELECT\n    CASE\n        WHEN score_column < 0.2 THEN '0.0-0.2'\n        WHEN score_column < 0.4 THEN '0.2-0.4'\n        WHEN score_column < 0.6 THEN '0.4-0.6'\n        WHEN score_column < 0.8 THEN '0.6-0.8'\n        ELSE '0.8-1.0'\n    END AS score_band,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY score_band\nORDER BY score_band;", ["modeling", "score"]),
  template("Prediction band summary", "Model Development", "Summarize predictions by band.", ["score_column", "target_column"], "SELECT\n    CASE WHEN score_column >= 0.5 THEN 'High' ELSE 'Low' END AS prediction_band,\n    COUNT(*) AS records,\n    AVG(CASE WHEN target_column = 1 THEN 1.0 ELSE 0.0 END) AS actual_rate\nFROM {table}\nGROUP BY prediction_band;", ["modeling"]),
  template("Lift table input query", "Model Development", "Create score and target inputs for lift tables.", ["score_column", "target_column"], "SELECT\n    score_column AS score,\n    target_column AS actual\nFROM {table}\nWHERE score_column IS NOT NULL\nLIMIT 100;", ["modeling", "lift"]),
  template("Calibration table input query", "Model Development", "Prepare calibration inputs by score band.", ["score_column", "target_column"], "SELECT\n    CASE\n        WHEN score_column < 0.2 THEN '0.0-0.2'\n        WHEN score_column < 0.4 THEN '0.2-0.4'\n        WHEN score_column < 0.6 THEN '0.4-0.6'\n        WHEN score_column < 0.8 THEN '0.6-0.8'\n        ELSE '0.8-1.0'\n    END AS score_band,\n    COUNT(*) AS records,\n    AVG(score_column) AS avg_score,\n    AVG(CASE WHEN target_column = 1 THEN 1.0 ELSE 0.0 END) AS actual_rate\nFROM {table}\nGROUP BY score_band\nORDER BY score_band;", ["modeling", "calibration"]),
  template("Monthly score distribution", "Monitoring", "Monitor score movement by month.", ["date_column", "score_column"], "SELECT\n    SUBSTR(date_column, 1, 7) AS score_month,\n    COUNT(*) AS records,\n    AVG(score_column) AS avg_score\nFROM {table}\nGROUP BY score_month\nORDER BY score_month\nLIMIT 100;", ["monitoring"]),
  template("PSI input table", "Monitoring", "Prepare binned score counts for PSI.", ["score_column"], "SELECT\n    CASE\n        WHEN score_column < 0.2 THEN '0.0-0.2'\n        WHEN score_column < 0.4 THEN '0.2-0.4'\n        WHEN score_column < 0.6 THEN '0.4-0.6'\n        WHEN score_column < 0.8 THEN '0.6-0.8'\n        ELSE '0.8-1.0'\n    END AS score_band,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY score_band\nORDER BY score_band;", ["monitoring", "psi"]),
  template("Prediction drift summary", "Monitoring", "Track mean prediction by segment.", ["segment_column", "score_column"], "SELECT\n    segment_column,\n    COUNT(*) AS records,\n    AVG(score_column) AS avg_prediction\nFROM {table}\nGROUP BY segment_column\nORDER BY records DESC\nLIMIT 100;", ["monitoring"]),
  template("Outcome drift summary", "Monitoring", "Track actual outcomes over time.", ["date_column", "target_column"], "SELECT\n    SUBSTR(date_column, 1, 7) AS outcome_month,\n    COUNT(*) AS records,\n    AVG(CASE WHEN target_column = 1 THEN 1.0 ELSE 0.0 END) AS outcome_rate\nFROM {table}\nGROUP BY outcome_month\nORDER BY outcome_month\nLIMIT 100;", ["monitoring"]),
  template("Performance by month", "Monitoring", "Calculate monthly performance rates.", ["date_column", "target_column", "score_column"], "SELECT\n    SUBSTR(date_column, 1, 7) AS performance_month,\n    COUNT(*) AS records,\n    AVG(score_column) AS avg_score,\n    AVG(CASE WHEN target_column = 1 THEN 1.0 ELSE 0.0 END) AS event_rate\nFROM {table}\nGROUP BY performance_month\nORDER BY performance_month\nLIMIT 100;", ["monitoring"]),
  template("Segment stability", "Monitoring", "Profile segment population stability.", ["segment_column"], "SELECT\n    segment_column,\n    COUNT(*) AS records,\n    COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS population_share\nFROM {table}\nGROUP BY segment_column\nORDER BY records DESC\nLIMIT 100;", ["monitoring"]),
  template("Champion vs challenger comparison", "Monitoring", "Compare two prediction columns.", ["score_column"], "SELECT\n    COUNT(*) AS records,\n    AVG(score_column) AS champion_avg_score,\n    AVG(score_column) AS challenger_avg_score\nFROM {table};", ["monitoring"]),
  template("Null rate by column", "Data Quality", "Template for null-rate checks on key columns.", ["customer_id", "amount_column"], "SELECT\n    COUNT(*) AS total_rows,\n    SUM(CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END) AS null_customer_id,\n    SUM(CASE WHEN amount_column IS NULL THEN 1 ELSE 0 END) AS null_amount\nFROM {table};", ["data quality"]),
  template("Duplicate key check", "Data Quality", "Find duplicate business keys.", ["customer_id"], "SELECT\n    customer_id,\n    COUNT(*) AS duplicate_count\nFROM {table}\nGROUP BY customer_id\nHAVING COUNT(*) > 1\nORDER BY duplicate_count DESC\nLIMIT 100;", ["data quality"]),
  template("Referential integrity check", "Data Quality", "Identify missing join keys after a left join.", ["account_id"], "SELECT\n    account_id,\n    COUNT(*) AS records\nFROM {table}\nWHERE account_id IS NULL\nGROUP BY account_id\nLIMIT 100;", ["data quality"]),
  template("Out-of-range values", "Data Quality", "Find values outside expected range.", ["amount_column"], "SELECT\n    COUNT(*) AS out_of_range_records\nFROM {table}\nWHERE amount_column < 0;", ["data quality"]),
  template("Unexpected category values", "Data Quality", "Review category counts.", ["segment_column"], "SELECT\n    segment_column,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY segment_column\nORDER BY records DESC\nLIMIT 100;", ["data quality"]),
  template("Row count reconciliation", "Data Quality", "Summarize row count controls.", [], "SELECT\n    COUNT(*) AS source_row_count\nFROM {table};", ["data quality"]),
  template("Source-to-target control totals", "Data Quality", "Calculate source control totals.", ["amount_column"], "SELECT\n    COUNT(*) AS row_count,\n    SUM(amount_column) AS amount_control_total\nFROM {table};", ["data quality"]),
  template("REG_TRAIN income band profile", "Demo Dataset Examples", "California housing demo query that works with REG_TRAIN.", ["MedInc", "MedHouseVal", "Population"], "SELECT\n    CASE\n        WHEN MedInc < 0.6 THEN 'Low income band'\n        WHEN MedInc < 0.8 THEN 'Middle income band'\n        ELSE 'High income band'\n    END AS income_band,\n    COUNT(*) AS row_count,\n    AVG(MedHouseVal) AS avg_home_value,\n    AVG(Population) AS avg_population\nFROM REG_TRAIN\nGROUP BY income_band\nORDER BY avg_home_value DESC\nLIMIT 100;", ["demo", "regression"]),
  template("CLASS_TRAIN class distribution", "Demo Dataset Examples", "Fraud/classification demo class distribution.", ["Class"], "SELECT\n    Class,\n    COUNT(*) AS row_count,\n    COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS population_share\nFROM CLASS_TRAIN\nGROUP BY Class\nORDER BY Class;", ["demo", "classification"]),
  template("CLASS_TRAIN rare-event summary", "Demo Dataset Examples", "Rare-event summary for binary classification demos.", ["Class"], "SELECT\n    COUNT(*) AS total_rows,\n    SUM(CASE WHEN Class = 1 THEN 1 ELSE 0 END) AS events,\n    SUM(CASE WHEN Class = 0 THEN 1 ELSE 0 END) AS non_events,\n    AVG(CASE WHEN Class = 1 THEN 1.0 ELSE 0.0 END) AS event_rate\nFROM CLASS_TRAIN;", ["demo", "rare event"]),
];

const TEMPLATE_CATEGORIES: TemplateCategory[] = [
  "Customer / Account Analytics",
  "Credit Risk",
  "Fraud / AML",
  "Marketing / Campaigns",
  "Model Development",
  "Monitoring",
  "Data Quality",
  "Demo Dataset Examples",
];

const COLUMN_MAPPINGS = [
  { key: "customer_id", label: "Customer ID", candidates: ["customer_id", "cust_id", "cid", "party_id"] },
  { key: "account_id", label: "Account ID", candidates: ["account_id", "acct_id", "account_number"] },
  { key: "date_column", label: "Date column", candidates: ["date", "transaction_date", "post_date", "open_date", "Time"] },
  { key: "amount_column", label: "Amount column", candidates: ["amount", "transaction_amount", "balance", "Amount", "MedHouseVal"] },
  { key: "target_column", label: "Target column", candidates: ["target", "actual", "response", "default_ind", "fraud_ind", "Class"] },
  { key: "score_column", label: "Score column", candidates: ["score", "model_score", "predicted_value", "probability"] },
  { key: "segment_column", label: "Segment column", candidates: ["segment", "risk_band", "region", "V1", "MedInc"] },
  { key: "campaign_column", label: "Campaign column", candidates: ["campaign", "channel", "offer", "ContactChannel"] },
];

export default function SqlDataStudio() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [sourceType, setSourceType] = useState<SourceType>("dataset_library_preview");
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [profiles, setProfiles] = useState<Record<string, DatasetProfile>>({});
  const [savedQueries, setSavedQueries] = useState<SavedSqlQuery[]>([]);
  const [queryName, setQueryName] = useState("Home Price Summary by Income Band");
  const [description, setDescription] = useState("");
  const [sql, setSql] = useState("SELECT *\nFROM REG_TRAIN\nLIMIT 100;");
  const [validation, setValidation] = useState<{ status: string; warnings: string[]; error?: string } | null>(null);
  const [preview, setPreview] = useState<SqlPreviewResult | null>(null);
  const [registeredDataset, setRegisteredDataset] = useState<DatasetSummary | null>(null);
  const [message, setMessage] = useState("");
  const [working, setWorking] = useState(false);
  const [expandedTables, setExpandedTables] = useState<Record<string, boolean>>({});
  const [objectExplorerTab, setObjectExplorerTab] = useState<ObjectExplorerTab>("tables");
  const [assistantTab, setAssistantTab] = useState<AssistantTab>("financial");
  const [bottomTab, setBottomTab] = useState<BottomTab>("results");
  const [expandedCategory, setExpandedCategory] = useState<TemplateCategory>("Demo Dataset Examples");
  const [templateSearch, setTemplateSearch] = useState("");
  const [selectedTemplateName, setSelectedTemplateName] = useState("REG_TRAIN income band profile");
  const [columnMap, setColumnMap] = useState<Record<string, string>>({});
  const [queryHistory, setQueryHistory] = useState<QueryHistoryEntry[]>(() => readHistory());
  const [focusMode, setFocusMode] = useState(false);
  const [showRegisterPanel, setShowRegisterPanel] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement | null>(null);

  const selectedDatasets = useMemo(
    () => datasets.filter((dataset) => selectedIds.includes(dataset.datasetId) && dataset.latestVersion?.versionId),
    [datasets, selectedIds]
  );
  const datasetRefs: SqlDatasetRef[] = useMemo(
    () =>
      selectedDatasets.map((dataset) => ({
        datasetId: dataset.datasetId,
        versionId: dataset.latestVersion?.versionId || "",
        alias: safeSqlAlias(dataset),
      })),
    [selectedDatasets]
  );
  const selectedProfile = selectedDatasets[0] ? profiles[selectedDatasets[0].datasetId] : null;
  const selectedTemplate = FINANCIAL_TEMPLATES.find((item) => item.name === selectedTemplateName) ?? FINANCIAL_TEMPLATES[0];
  const availableColumns = useMemo(() => selectedDatasets.flatMap((dataset) => profiles[dataset.datasetId]?.schema?.map((column) => column.name) ?? []), [profiles, selectedDatasets]);
  const detectedMap = useMemo(() => autoDetectColumnMap(availableColumns), [availableColumns]);
  const activeColumnMap = { ...detectedMap, ...columnMap };
  const mappedTemplateSql = applyTemplate(selectedTemplate, datasetRefs, activeColumnMap);
  const templateIssues = selectedTemplate.requiredColumns.filter((field) => !activeColumnMap[field]);
  const filteredTemplates = FINANCIAL_TEMPLATES.filter((item) => {
    const needle = templateSearch.trim().toLowerCase();
    if (!needle) return true;
    return [item.name, item.category, item.description, item.tags.join(" ")].join(" ").toLowerCase().includes(needle);
  });
  const lineCount = Math.max(1, sql.split("\n").length);
  const cursorPosition = editorRef.current ? getCursorPosition(sql, editorRef.current.selectionStart) : { line: 1, column: 1 };
  const messages = buildMessages(validation, preview, datasetRefs, sourceType);
  const sqlResults = datasets.filter((dataset) => isSqlResultDataset(dataset));

  async function refresh() {
    setWorking(true);
    setMessage("");
    try {
      const payload = await listDatasets();
      const usable = payload.datasets.filter((dataset) => dataset.latestVersion?.versionId);
      setDatasets(usable);
      if (!selectedIds.length && usable[0]) {
        setSelectedIds([usable[0].datasetId]);
        const ref = { datasetId: usable[0].datasetId, versionId: usable[0].latestVersion?.versionId || "", alias: safeSqlAlias(usable[0]) };
        setSql(generateSelectTemplate([ref]));
      }
      setSavedQueries((await listSavedSqlQueries()).queries);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not load SQL Data Studio.");
    } finally {
      setWorking(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    selectedDatasets.forEach((dataset) => {
      const versionId = dataset.latestVersion?.versionId;
      if (!versionId || profiles[dataset.datasetId]) return;
      getDatasetProfile(dataset.datasetId, versionId)
        .then((payload) => setProfiles((current) => ({ ...current, [dataset.datasetId]: payload.profile })))
        .catch(() => undefined);
    });
  }, [profiles, selectedDatasets]);

  useEffect(() => {
    setColumnMap((current) => ({ ...detectedMap, ...current }));
  }, [detectedMap]);

  async function validateCurrentSql() {
    setWorking(true);
    setMessage("");
    try {
      const result = await validateSql({ sql, datasetRefs, limit: 100 });
      setValidation(result);
      setBottomTab("messages");
    } catch (error) {
      setValidation({ status: "error", warnings: [], error: error instanceof Error ? error.message : "Validation failed." });
      setBottomTab("messages");
    } finally {
      setWorking(false);
    }
  }

  async function runPreview() {
    setWorking(true);
    setMessage("");
    setRegisteredDataset(null);
    const started = performance.now();
    try {
      const result = await runSqlPreview({ sql, datasetRefs, limit: 100 });
      setPreview(result);
      setValidation({ status: result.ok ? "valid" : result.status, warnings: result.warnings, error: result.error });
      recordHistory({
        id: `qh_${Date.now()}`,
        timestamp: new Date().toISOString(),
        sql,
        status: result.status,
        runtimeMs: result.runtimeMs ?? Math.round(performance.now() - started),
        rowCount: result.returnedRows ?? 0,
        tablesUsed: datasetRefs.map((ref) => ref.alias),
        warnings: result.warnings ?? [],
      });
      setBottomTab("results");
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Preview failed.";
      setPreview(null);
      setValidation({ status: "error", warnings: [], error: errorMessage });
      recordHistory({
        id: `qh_${Date.now()}`,
        timestamp: new Date().toISOString(),
        sql,
        status: "error",
        runtimeMs: Math.round(performance.now() - started),
        rowCount: 0,
        tablesUsed: datasetRefs.map((ref) => ref.alias),
        warnings: [errorMessage],
      });
      setBottomTab("messages");
    } finally {
      setWorking(false);
    }
  }

  async function saveCurrentQuery() {
    setWorking(true);
    try {
      const saved = await saveSqlQuery({
        name: queryName,
        description,
        sql,
        datasetRefs,
        linkedProjectId: projectId,
        tags: inferTags(sql, selectedTemplate),
      });
      setMessage(`Saved SQL query "${saved.query.name}".`);
      setSavedQueries((await listSavedSqlQueries()).queries);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save this SQL query.");
    } finally {
      setWorking(false);
    }
  }

  async function deleteSavedQuery(query: SavedSqlQuery) {
    const confirmed = window.confirm(`Delete saved SQL query "${query.name}"?`);
    if (!confirmed) return;
    await deleteSqlQuery(query.queryId);
    setSavedQueries((await listSavedSqlQueries()).queries);
  }

  async function registerResult() {
    if (!preview?.rows?.length) {
      setMessage("Run Preview before registering a SQL result as a Dataset Library asset.");
      return;
    }
    setWorking(true);
    try {
      const payload = await registerSqlResult({
        queryName,
        description,
        sql,
        datasetRefs,
        resultRows: preview.rows,
        resultColumns: preview.columns,
        linkedProjectId: projectId,
        tags: inferTags(sql, selectedTemplate),
      });
      setRegisteredDataset(payload.dataset);
      setMessage(`Registered SQL Result dataset "${payload.dataset.name}".`);
      setBottomTab("lineage");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not register this SQL result.");
    } finally {
      setWorking(false);
    }
  }

  async function exportPreview() {
    if (!preview) {
      setMessage("Run Preview before exporting query results.");
      return;
    }
    try {
      const blob = await exportSqlResultExcel({
        queryName,
        sql,
        rows: preview.rows,
        columns: preview.columns,
        schemaProfile: preview.schemaProfile ?? [],
        datasetRefs,
        warnings: preview.warnings,
        lineage: { createdBy: "SQL Data Studio", sourceType, linkedProjectId: projectId },
      });
      downloadBlob(blob, "atlas-sql-data-studio-result.xlsx");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not export the SQL result.");
    }
  }

  async function saveQueryAsEvidence() {
    try {
      await createEvidence({
        projectId,
        projectName,
        evidenceType: "sql_query",
        title: `SQL Query: ${queryName}`,
        summary: description || `Governed SQL query using ${datasetRefs.length} source dataset(s).`,
        sourcePage: "SQL Data Studio",
        sourceRoute: "/sql-data-studio",
        artifactType: "sql_query",
        artifactId: queryName,
        datasetIds: datasetRefs.map((ref) => ref.datasetId),
        supportsSections: ["Lineage", "Appendix"],
        tags: ["governance", "model_risk", ...inferTags(sql, selectedTemplate)],
        status: validation?.status === "valid" ? "ready" : "needs_review",
        importance: "high",
        lineage: { datasetRefs, sourceType, validationStatus: validation?.status ?? "not_validated" },
        payload: { sqlPreview: sql.slice(0, 4000) },
        governance: { note: "SQL query text is captured for lineage review. Result rows are not duplicated in Model Evidence Center." },
      });
      setMessage("SQL query saved to Model Evidence Center.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save SQL query evidence.");
    }
  }

  async function saveSqlResultAsEvidence() {
    if (!preview) {
      setMessage("Run Preview before saving SQL result evidence.");
      return;
    }
    try {
      await createEvidence({
        projectId,
        projectName,
        evidenceType: "sql_result",
        title: `SQL Result: ${queryName}`,
        summary: `Preview returned ${preview.returnedRows} row(s), ${preview.columns.length} column(s), and ${preview.warnings?.length ?? 0} warning(s).`,
        sourcePage: "SQL Data Studio",
        sourceRoute: "/sql-data-studio",
        artifactType: "sql_result_preview",
        artifactId: registeredDataset?.datasetId || queryName,
        datasetIds: [...datasetRefs.map((ref) => ref.datasetId), registeredDataset?.datasetId].filter(Boolean) as string[],
        supportsSections: ["Lineage", "Data Quality"],
        tags: ["governance", "model_risk", ...inferTags(sql, selectedTemplate)],
        status: preview.ok ? "ready" : "needs_review",
        importance: "high",
        lineage: { datasetRefs, registeredDatasetId: registeredDataset?.datasetId, runtimeMs: preview.runtimeMs, returnedRows: preview.returnedRows },
        payload: { columns: preview.columns, warningCount: preview.warnings?.length ?? 0 },
        governance: { note: "SQL result evidence stores compact schema and lineage only; preview rows remain in SQL Data Studio output artifacts." },
      });
      setMessage("SQL result saved to Model Evidence Center.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save SQL result evidence.");
    }
  }

  function recordHistory(entry: QueryHistoryEntry) {
    setQueryHistory((current) => {
      const next = [entry, ...current].slice(0, 30);
      writeHistory(next);
      return next;
    });
  }

  function insertSnippet(snippet: string, mode: "replace" | "append" = "append") {
    const next = mode === "replace" ? snippet : `${sql.trim()}\n${snippet}`.trim();
    setSql(next);
    setPreview(null);
    setValidation(null);
    requestAnimationFrame(() => editorRef.current?.focus());
  }

  function insertTemplate(mode: "replace" | "append") {
    insertSnippet(mappedTemplateSql, mode);
    setQueryName(selectedTemplate.name);
    setDescription(selectedTemplate.description);
  }

  function openSavedQuery(query: SavedSqlQuery) {
    setQueryName(query.name);
    setDescription(query.description ?? "");
    setSql(query.sql);
    setSelectedIds((current) => {
      const ids = query.datasetRefs?.map((ref) => ref.datasetId).filter(Boolean) ?? [];
      return ids.length ? ids : current;
    });
    setBottomTab("messages");
  }

  function duplicateSavedQuery(query: SavedSqlQuery) {
    setQueryName(`${query.name} copy`);
    setDescription(query.description ?? "");
    setSql(query.sql);
  }

  async function renameSavedQuery(query: SavedSqlQuery) {
    const nextName = window.prompt("Rename saved SQL query", query.name)?.trim();
    if (!nextName || nextName === query.name) return;
    setWorking(true);
    try {
      await saveSqlQuery({
        name: nextName,
        description: query.description ?? "",
        sql: query.sql,
        datasetRefs: query.datasetRefs ?? [],
        linkedProjectId: query.linkedProjectId,
        tags: query.tags ?? [],
      });
      await deleteSqlQuery(query.queryId);
      setSavedQueries((await listSavedSqlQueries()).queries);
      setMessage(`Renamed SQL query "${query.name}" to "${nextName}".`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not rename this SQL query.");
    } finally {
      setWorking(false);
    }
  }

  function handleEditorKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.ctrlKey && event.key === "Enter") {
      event.preventDefault();
      runPreview();
    }
    if (event.ctrlKey && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveCurrentQuery();
    }
    if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "f") {
      event.preventDefault();
      setSql(formatSql(sql));
    }
  }

  return (
    <div className="w-full atlas-theme-sql">
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex min-h-[64px] flex-wrap items-center justify-between gap-3 border-b border-teal-300/30 bg-gradient-to-r from-slate-950 via-slate-900 to-teal-950 px-3 py-2 text-white">
          <div className="flex min-w-[260px] items-center gap-3">
            <BrandLogo size="sm" variant="dark" showSubtitle={false} />
            <div>
              <div className="flex items-center gap-2">
                <Database size={18} className="text-teal-200" />
                <h1 className="text-base font-semibold text-white">SQL Data Studio</h1>
                <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-teal-50">Compact IDE shell</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-teal-50/80">
                <span>Source: {sourceType === "dataset_library_preview" ? "Dataset Preview SQL" : sourceType}</span>
                <span>Query: {validation?.status ?? "not validated"}</span>
                <span>Rows: {preview?.returnedRows?.toLocaleString?.() ?? "-"}</span>
                <span>Runtime: {preview ? `${preview.runtimeMs} ms` : "-"}</span>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <ToolbarButton icon={<ShieldAlert size={14} />} label="Validate" onClick={validateCurrentSql} />
            <ToolbarButton icon={<Play size={14} />} label="Run Preview" onClick={runPreview} primary />
            <ToolbarButton icon={<Wand2 size={14} />} label="Format" onClick={() => setSql(formatSql(sql))} />
            <ToolbarButton icon={<Save size={14} />} label="Save Query" onClick={saveCurrentQuery} />
            <ToolbarButton icon={<Database size={14} />} label="Register Result" onClick={() => setShowRegisterPanel(true)} />
            <ToolbarButton icon={<Download size={14} />} label="Export" onClick={exportPreview} />
            <ToolbarButton icon={<Copy size={14} />} label="Copy SQL" onClick={() => navigator.clipboard?.writeText(sql)} />
            <Link to={`/notebook-studio?datasetId=${selectedDatasets[0]?.datasetId || ""}&versionId=${selectedDatasets[0]?.latestVersion?.versionId || ""}`} className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:border-blue-300 hover:text-blue-800">
              Send Query to Notebook Studio
            </Link>
            <ToolbarButton icon={<ShieldAlert size={14} />} label="Save Query to Model Evidence Center" onClick={saveQueryAsEvidence} />
            <ToolbarButton icon={<ShieldAlert size={14} />} label="Save SQL Result to Model Evidence Center" onClick={saveSqlResultAsEvidence} />
            <Link to="/model-evidence-center" className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs font-semibold text-blue-800 hover:bg-blue-100">
              Open Model Evidence Center
            </Link>
            <button type="button" onClick={() => setFocusMode((current) => !current)} className={`rounded-lg border px-2.5 py-1.5 text-xs font-semibold ${focusMode ? "border-blue-300 bg-blue-50 text-blue-800" : "border-slate-300 bg-white text-slate-700"}`}>
              Focus Mode
            </button>
          </div>
        </div>
        {message && <div className="border-b border-teal-200 bg-teal-50 px-3 py-2 text-sm text-teal-950">{message}</div>}

        <div
          className="grid min-h-[560px] gap-3 bg-teal-50/50 p-3"
          style={{
            height: "calc(100vh - 170px)",
            gridTemplateColumns: focusMode ? "minmax(700px, 1fr)" : "260px minmax(520px, 1fr) 320px",
            gridTemplateRows: focusMode ? "minmax(0, 1fr) 280px" : "minmax(0, 1fr) 260px",
          }}
        >
          {!focusMode && (
            <aside className="col-start-1 row-start-1 row-span-2 grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
              <PaneHeader icon={<FolderTree size={15} />} title="Object Explorer" subtitle="Tables, Saved Queries, SQL Results, Connectors" />
              <div className="flex border-b border-slate-200 bg-white">
                {[
                  ["tables", "Tables"],
                  ["saved", "Saved"],
                  ["results", "Results"],
                  ["connectors", "Connectors"],
                ].map(([id, label]) => (
                  <button key={id} type="button" onClick={() => setObjectExplorerTab(id as ObjectExplorerTab)} className={`flex-1 px-2 py-2 text-[11px] font-semibold ${objectExplorerTab === id ? "bg-blue-50 text-blue-800" : "text-slate-600 hover:bg-slate-50"}`}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="min-h-0 overflow-auto p-2">
                {objectExplorerTab === "tables" && (
                  <div className="space-y-2">
                    <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      Data Source
                    </label>
                    <select value={sourceType} onChange={(event) => setSourceType(event.target.value as SourceType)} className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs">
                      <option value="dataset_library_preview">Dataset Library Preview SQL</option>
                      <option value="saved_query">Saved SQL Query</option>
                      <option value="external_metadata">External Source Metadata</option>
                    </select>
                    {datasets.map((dataset) => {
                      const checked = selectedIds.includes(dataset.datasetId);
                      const alias = safeSqlAlias(dataset);
                      const expanded = expandedTables[dataset.datasetId];
                      const schema = profiles[dataset.datasetId]?.schema ?? [];
                      return (
                        <div key={dataset.datasetId} className={`rounded-lg border text-xs ${checked ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white"}`}>
                          <div className="flex items-center gap-2 px-2 py-1.5">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(event) =>
                                setSelectedIds((current) => event.target.checked ? [...current, dataset.datasetId] : current.filter((id) => id !== dataset.datasetId))
                              }
                            />
                            <button type="button" onClick={() => setExpandedTables((current) => ({ ...current, [dataset.datasetId]: !expanded }))} className="text-slate-500">
                              {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                            </button>
                            <div className="min-w-0">
                              <div className="truncate font-semibold text-slate-950">{alias}</div>
                              <div className="truncate text-[11px] text-slate-500">{dataset.latestVersion?.rowCount?.toLocaleString() ?? "-"} rows | {dataset.latestVersion?.columnCount ?? "-"} cols</div>
                            </div>
                          </div>
                          {expanded && (
                            <div className="max-h-44 overflow-auto border-t border-slate-200 bg-white px-2 py-1">
                              {schema.slice(0, 60).map((column) => (
                                <button key={column.name} type="button" onClick={() => insertSnippet(column.name)} className="flex w-full items-center justify-between rounded px-1.5 py-1 text-left hover:bg-slate-50">
                                  <span className="truncate font-mono text-[11px] text-slate-800">{column.name}</span>
                                  <span className="rounded bg-slate-100 px-1 text-[10px] text-slate-500">{column.dtype}</span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
                {objectExplorerTab === "saved" && (
                  <div className="space-y-2">
                    {savedQueries.slice(0, 16).map((query) => (
                      <div key={query.queryId} className="rounded-lg border border-slate-200 bg-white p-2 text-xs">
                        <div className="font-semibold text-slate-950">{query.name}</div>
                        <div className="mt-1 truncate text-[11px] text-slate-500">Updated {query.updatedAt ? new Date(query.updatedAt).toLocaleString() : "-"}</div>
                        <div className="mt-1 truncate text-[11px] text-slate-500">Status: Saved | Tags: {(query.tags ?? []).join(", ") || "-"}</div>
                        <div className="mt-2 flex flex-wrap gap-1">
                          <SmallButton label="Open" onClick={() => openSavedQuery(query)} />
                          <SmallButton label="Run" onClick={() => { openSavedQuery(query); setTimeout(runPreview, 0); }} />
                          <SmallButton label="Duplicate" onClick={() => duplicateSavedQuery(query)} />
                          <SmallButton label="Rename" onClick={() => renameSavedQuery(query)} />
                          <SmallButton label="Delete" onClick={() => deleteSavedQuery(query)} />
                          <SmallButton label="Export SQL" onClick={() => exportSqlDefinition(query.name, query.sql, query.datasetRefs ?? [])} />
                        </div>
                      </div>
                    ))}
                    {!savedQueries.length && <p className="text-xs leading-5 text-slate-500">Saved governed queries will appear here.</p>}
                  </div>
                )}
                {objectExplorerTab === "results" && (
                  <div className="space-y-2">
                    {sqlResults.slice(0, 12).map((dataset) => (
                      <Link key={dataset.datasetId} to={`/datasets/${dataset.datasetId}`} className="block rounded-lg border border-indigo-200 bg-indigo-50 px-2 py-2 text-xs font-semibold text-indigo-900">
                        {dataset.name}
                      </Link>
                    ))}
                    {!sqlResults.length && <p className="text-xs leading-5 text-slate-500">Registered SQL result datasets will appear here.</p>}
                  </div>
                )}
                {objectExplorerTab === "connectors" && (
                  <details className="rounded-lg border border-slate-200 bg-white p-2 text-xs" open>
                    <summary className="cursor-pointer font-semibold text-slate-800">External Connectors</summary>
                    <p className="mt-2 leading-5 text-slate-500">Connector not configured in this local build. Use Dataset Library Preview SQL until governed warehouse connections are enabled.</p>
                    <div className="mt-2 space-y-1">
                      {EXTERNAL_CONNECTORS.map((connector) => (
                        <div key={connector} className="flex justify-between rounded bg-slate-50 px-2 py-1 text-slate-600">
                          <span>{connector}</span>
                          <span>Not configured</span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            </aside>
          )}

          <main className={`${focusMode ? "col-start-1" : "col-start-2"} row-start-1 grid min-h-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm grid-rows-[auto_minmax(0,1fr)]`}>
            <div className="border-b border-slate-200 bg-slate-50 px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="inline-flex rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-900">Query 1 - Active</div>
                <div className="text-[11px] text-slate-500">Ctrl+Enter run preview / Ctrl+S save query / Ctrl+Shift+F format SQL</div>
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-[minmax(0,0.7fr)_minmax(0,1fr)]">
                <input value={queryName} onChange={(event) => setQueryName(event.target.value)} className="rounded-md border border-slate-300 px-2 py-1.5 text-sm" placeholder="Query title" />
                <input value={description} onChange={(event) => setDescription(event.target.value)} className="rounded-md border border-slate-300 px-2 py-1.5 text-sm" placeholder="Description / governance purpose" />
              </div>
            </div>
            <div className="grid min-h-0 grid-cols-[46px_minmax(0,1fr)] bg-slate-950">
              <pre className="select-none overflow-hidden border-r border-slate-800 bg-slate-900 px-2 py-3 text-right font-mono text-xs leading-6 text-slate-500">
                {Array.from({ length: lineCount }, (_, index) => index + 1).join("\n")}
              </pre>
              <textarea
                ref={editorRef}
                value={sql}
                onChange={(event) => {
                  setSql(event.target.value);
                  setPreview(null);
                  setValidation(null);
                }}
                onKeyDown={handleEditorKeyDown}
                spellCheck={false}
                className="h-full min-h-0 w-full resize-none bg-slate-950 px-4 py-3 font-mono text-sm leading-6 text-slate-100 outline-none"
              />
            </div>
          </main>

          {!focusMode && (
            <aside className="col-start-3 row-start-1 grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
              <PaneHeader icon={<Sparkles size={15} />} title="SQL Assistant" subtitle="Templates, financial tasks, mapping, governance" />
              <div className="flex border-b border-slate-200 bg-white">
                {[
                  ["templates", "Templates"],
                  ["financial", "Financial"],
                  ["mapping", "Mapping"],
                  ["governance", "Governance"],
                  ["help", "Help"],
                ].map(([id, label]) => (
                  <button key={id} type="button" onClick={() => setAssistantTab(id as AssistantTab)} className={`flex-1 px-2 py-2 text-[11px] font-semibold ${assistantTab === id ? "bg-blue-50 text-blue-800" : "text-slate-600 hover:bg-slate-50"}`}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="min-h-0 overflow-auto p-2">
                {assistantTab === "templates" && (
                  <Panel title="SQL Templates">
                    <div className="space-y-1">
                      {SQL_SNIPPETS.map((snippet) => (
                        <button key={snippet.label} type="button" onClick={() => insertSnippet(resolveSnippet(snippet.sql, datasetRefs, activeColumnMap))} className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-left text-xs font-semibold text-slate-700 hover:border-blue-200 hover:bg-blue-50">
                          {snippet.label}
                          <ChevronRight size={13} />
                        </button>
                      ))}
                    </div>
                  </Panel>
                )}
                {assistantTab === "financial" && (
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1.5">
                      <Search size={13} className="text-slate-500" />
                      <input value={templateSearch} onChange={(event) => setTemplateSearch(event.target.value)} placeholder="Search financial SQL tasks..." className="w-full bg-transparent text-xs outline-none" />
                    </label>
                    <Panel title="Selected Template Preview">
                      <div className="space-y-2 text-xs">
                        <div className="font-semibold text-slate-950">{selectedTemplate.name}</div>
                        <div className="text-[11px] text-slate-500">Required columns: {selectedTemplate.requiredColumns.join(", ") || "none"}</div>
                        {templateIssues.length > 0 && <div className="rounded border border-amber-200 bg-amber-50 p-2 text-amber-900">Needs mapping: {templateIssues.join(", ")}</div>}
                        <pre className="max-h-28 overflow-auto rounded-lg bg-slate-950 p-2 text-[11px] leading-5 text-slate-100">{mappedTemplateSql}</pre>
                        <div className="grid grid-cols-2 gap-1">
                          <button type="button" onClick={() => insertTemplate("replace")} className="rounded bg-slate-950 px-2 py-1.5 text-xs font-semibold text-white">Replace editor SQL</button>
                          <button type="button" onClick={() => insertTemplate("append")} className="rounded border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700">Append to editor SQL</button>
                        </div>
                      </div>
                    </Panel>
                    <Panel title="Financial Services SQL Tasks">
                      <div className="space-y-1">
                        {TEMPLATE_CATEGORIES.map((category) => {
                          const items = filteredTemplates.filter((item) => item.category === category);
                          if (!items.length) return null;
                          const open = expandedCategory === category;
                          return (
                            <div key={category} className="rounded-lg border border-slate-200 bg-white">
                              <button type="button" onClick={() => setExpandedCategory(open ? "Demo Dataset Examples" : category)} className="flex w-full items-center justify-between px-2 py-1.5 text-left text-xs font-semibold text-slate-800">
                                {category}
                                {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                              </button>
                              {open && (
                                <div className="border-t border-slate-100 p-1">
                                  {items.map((item) => (
                                    <div key={item.name} className={`rounded-md border p-2 text-xs ${item.name === selectedTemplateName ? "border-blue-300 bg-blue-50" : "border-transparent bg-white"}`}>
                                      <button type="button" onClick={() => setSelectedTemplateName(item.name)} className="w-full text-left">
                                        <div className="font-semibold text-slate-950">{item.name}</div>
                                        <div className="mt-1 line-clamp-2 text-[11px] text-slate-500">{item.description}</div>
                                        <div className="mt-1 text-[10px] text-slate-500">Required: {item.requiredColumns.join(", ") || "none"}</div>
                                      </button>
                                      <div className="mt-2 flex gap-1">
                                        <SmallButton label="Insert" onClick={() => insertTemplate("replace")} />
                                        <SmallButton label="Preview" onClick={() => setSelectedTemplateName(item.name)} />
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </Panel>
                  </div>
                )}
                {assistantTab === "mapping" && (
                  <Panel title="Column Mapping">
                    {selectedTemplate ? (
                      <div className="space-y-2">
                        {COLUMN_MAPPINGS.map((mapping) => (
                          <label key={mapping.key} className="block text-xs font-semibold text-slate-600">
                            {mapping.label}
                            <select value={activeColumnMap[mapping.key] ?? ""} onChange={(event) => setColumnMap((current) => ({ ...current, [mapping.key]: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-900">
                              <option value="">Not mapped</option>
                              {availableColumns.map((column) => <option key={`${mapping.key}-${column}`} value={column}>{column}</option>)}
                            </select>
                          </label>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">Select a template to map required columns.</p>
                    )}
                  </Panel>
                )}
                {assistantTab === "governance" && (
                  <div className="space-y-2">
                    <Panel title="Governance Controls">
                      <ul className="space-y-1 text-xs leading-5 text-slate-700">
                        <li>Read-only SELECT only.</li>
                        <li>Preview/sample-row execution only.</li>
                        <li>No production warehouse execution.</li>
                        <li>Dataset lineage required before registration.</li>
                        <li>Review PII and sensitive data.</li>
                      </ul>
                    </Panel>
                    <Panel title="Current query lineage">
                      <LineagePanel refs={datasetRefs} registeredDataset={registeredDataset} sql={sql} compact />
                    </Panel>
                  </div>
                )}
                {assistantTab === "help" && (
                  <Panel title="How to use SQL Data Studio">
                    <ol className="list-decimal space-y-1 pl-5 text-xs leading-5 text-slate-700">
                      <li>Select Dataset Library tables.</li>
                      <li>Insert a template or write SQL.</li>
                      <li>Validate and run preview.</li>
                      <li>Review Messages and Lineage.</li>
                      <li>Register approved SQL results.</li>
                    </ol>
                  </Panel>
                )}
                {showRegisterPanel && (
                  <Panel title="Register Result Form">
                    <div className="space-y-2 text-xs">
                      <Meta label="Dataset name" value={queryName} />
                      <Meta label="Dataset role" value="SQL Result" />
                      <Meta label="Preview row count" value={preview?.returnedRows?.toLocaleString() ?? "-"} />
                      <Meta label="Source datasets" value={datasetRefs.map((ref) => ref.alias).join(", ") || "-"} />
                      <Meta label="Linked project" value={projectId} />
                      <div className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-amber-900">Lineage warning: register only validated queries with approved source datasets.</div>
                      <button type="button" onClick={registerResult} className="w-full rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white">Register SQL Result</button>
                      {registeredDataset && (
                        <div className="grid gap-1">
                          <Link className="rounded bg-slate-950 px-2 py-1.5 text-center text-xs font-semibold text-white" to={`/datasets/${registeredDataset.datasetId}`}>Open Dataset Detail</Link>
                          <Link className="rounded bg-slate-950 px-2 py-1.5 text-center text-xs font-semibold text-white" to={`/analytics?datasetId=${registeredDataset.datasetId}`}>Open Analytics Workbench</Link>
                          <Link className="rounded bg-slate-950 px-2 py-1.5 text-center text-xs font-semibold text-white" to={`/chart-studio?datasetId=${registeredDataset.datasetId}`}>Open Chart Studio</Link>
                          <Link className="rounded bg-slate-950 px-2 py-1.5 text-center text-xs font-semibold text-white" to="/model-document-studio">Open Model Documentation Studio</Link>
                        </div>
                      )}
                    </div>
                  </Panel>
                )}
              </div>
            </aside>
          )}

          <section className={`${focusMode ? "col-start-1" : "col-start-2 col-span-2"} row-start-2 min-h-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm`}>
            <div className="flex flex-wrap border-b border-slate-200 bg-slate-50">
              {[
                ["results", "Results"],
                ["schema", "Schema"],
                ["profile", "Profile"],
                ["messages", "Messages"],
                ["history", "Query History"],
                ["lineage", "Lineage"],
              ].map(([id, label]) => (
                <button key={id} type="button" onClick={() => setBottomTab(id as BottomTab)} className={`border-r border-slate-200 px-3 py-2 text-xs font-semibold ${bottomTab === id ? "bg-white text-blue-700" : "text-slate-600 hover:bg-white"}`}>
                  {label}
                </button>
              ))}
              <div className="ml-auto px-3 py-2 text-xs text-slate-500">Status: {working ? "Working..." : validation?.status ?? "Idle"} | Cursor: {cursorPosition.line}:{cursorPosition.column}</div>
            </div>
            <div className="h-[calc(100%-37px)] overflow-auto p-3">
              {bottomTab === "results" && <ResultsGrid preview={preview} />}
              {bottomTab === "schema" && <SchemaGrid columns={preview?.columns ?? []} />}
              {bottomTab === "profile" && <SchemaProfile profile={preview?.schemaProfile ?? []} />}
              {bottomTab === "messages" && <MessagesPanel messages={messages} />}
              {bottomTab === "history" && <QueryHistoryPanel entries={queryHistory} onOpen={(entry) => setSql(entry.sql)} onRerun={(entry) => { setSql(entry.sql); setTimeout(runPreview, 0); }} onSave={(entry) => { setSql(entry.sql); setQueryName(`Saved from history ${new Date(entry.timestamp).toLocaleString()}`); }} />}
              {bottomTab === "lineage" && <LineagePanel refs={datasetRefs} registeredDataset={registeredDataset} sql={sql} />}
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}

function template(name: string, category: TemplateCategory, description: string, requiredColumns: string[], sql: string, tags: string[]): SqlTemplate {
  return { name, category, description, requiredColumns, sql, tags };
}

function ToolbarButton({ icon, label, onClick, primary = false }: { icon: React.ReactNode; label: string; onClick: () => void; primary?: boolean }) {
  return (
    <button type="button" onClick={onClick} className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold shadow-sm ${primary ? "bg-blue-700 text-white hover:bg-blue-800" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}>
      {icon}
      {label}
    </button>
  );
}

function PaneHeader({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) {
  return (
    <div className="border-b border-slate-200 bg-white px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">{icon}{title}</div>
      <div className="mt-1 text-xs text-slate-500">{subtitle}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      {children}
    </section>
  );
}

function StatusPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-xs font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return <span className="inline-flex rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-700">{children}</span>;
}

function Meta({ label, value }: { label: string; value?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 break-words text-xs font-medium text-slate-800">{value || "-"}</div>
    </div>
  );
}

function ResultsGrid({ preview }: { preview: SqlPreviewResult | null }) {
  if (!preview) return <EmptyState icon={<Table2 size={24} />} title="No query results yet" text="Run Preview to populate the IDE result grid." />;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 text-xs">
        <Chip>{preview.returnedRows.toLocaleString()} rows returned</Chip>
        <Chip>{preview.columns.length.toLocaleString()} columns</Chip>
        <Chip>{preview.runtimeMs} ms</Chip>
      </div>
      <div className="overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-left text-xs">
          <thead className="sticky top-0 z-10 bg-slate-100 text-slate-600">
            <tr>
              {preview.columns.map((column) => (
                <th key={column.name} className="whitespace-nowrap px-3 py-2 font-semibold">
                  {column.name}
                  <span className="ml-2 rounded-full bg-white px-1.5 py-0.5 text-[10px] text-slate-500">{column.type}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {preview.rows.map((row, index) => (
              <tr key={index} className="odd:bg-white even:bg-slate-50">
                {preview.columns.map((column) => (
                  <td key={`${index}-${column.name}`} className="max-w-[260px] whitespace-nowrap px-3 py-2 text-slate-700">
                    {row[column.name] == null ? <span className="italic text-slate-400">NULL</span> : String(row[column.name])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SchemaGrid({ columns }: { columns: Array<{ name: string; type: string }> }) {
  if (!columns.length) return <EmptyState icon={<Code2 size={24} />} title="No result schema" text="Run Preview to infer result columns and types." />;
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {columns.map((column) => (
        <div key={column.name} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="font-mono text-xs font-semibold text-slate-950">{column.name}</div>
          <div className="mt-1 text-[11px] uppercase text-slate-500">{column.type}</div>
        </div>
      ))}
    </div>
  );
}

function SchemaProfile({ profile }: { profile: Array<{ name: string; type: string; missingCount: number; distinctCount: number; min?: number; max?: number; mean?: number; sampleValues?: string[] }> }) {
  if (!profile.length) return <EmptyState icon={<BarChart3 size={24} />} title="No profile yet" text="Run Preview to calculate compact schema profile statistics." />;
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {profile.map((column) => (
        <div key={column.name} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
          <div className="font-semibold text-slate-950">{column.name}</div>
          <div className="mt-1 text-slate-600">{column.type} / missing {column.missingCount} / distinct {column.distinctCount}</div>
          {column.type === "numeric" ? <div className="mt-1 text-slate-500">min {fmt(column.min)} / max {fmt(column.max)} / mean {fmt(column.mean)}</div> : <div className="mt-1 truncate text-slate-500">{column.sampleValues?.join(", ")}</div>}
        </div>
      ))}
    </div>
  );
}

function MessagesPanel({ messages }: { messages: string[] }) {
  return (
    <div className="space-y-2">
      {messages.map((item) => (
        <div key={item} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">{item}</div>
      ))}
    </div>
  );
}

function QueryHistoryPanel({ entries, onOpen, onRerun, onSave }: { entries: QueryHistoryEntry[]; onOpen: (entry: QueryHistoryEntry) => void; onRerun: (entry: QueryHistoryEntry) => void; onSave: (entry: QueryHistoryEntry) => void }) {
  if (!entries.length) return <EmptyState icon={<History size={24} />} title="No query history" text="Each preview run records compact history: status, runtime, row count, tables, and warnings." />;
  return (
    <div className="space-y-2">
      {entries.map((entry) => (
        <div key={entry.id} className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold text-slate-950">{new Date(entry.timestamp).toLocaleString()}</div>
              <div className="mt-1 text-xs text-slate-500">{entry.status} / {entry.runtimeMs} ms / {entry.rowCount} rows / {entry.tablesUsed.join(", ") || "no tables"}</div>
            </div>
            <div className="flex flex-wrap gap-1">
              <SmallButton label="Open SQL" onClick={() => onOpen(entry)} />
              <SmallButton label="Rerun" onClick={() => onRerun(entry)} />
              <SmallButton label="Save as Query" onClick={() => onSave(entry)} />
            </div>
          </div>
          <pre className="mt-2 max-h-24 overflow-auto rounded bg-slate-950 p-2 text-[11px] text-slate-100">{entry.sql}</pre>
        </div>
      ))}
    </div>
  );
}

function LineagePanel({ refs, registeredDataset, sql, compact = false }: { refs: SqlDatasetRef[]; registeredDataset: DatasetSummary | null; sql: string; compact?: boolean }) {
  return (
    <div className="space-y-3">
      <div className={`grid gap-2 ${compact ? "" : "md:grid-cols-3"}`}>
        <Meta label="Source datasets" value={refs.map((ref) => ref.alias).join(", ") || "-"} />
        <Meta label="Versions" value={refs.map((ref) => ref.versionId).join(", ") || "-"} />
        <Meta label="Registered result" value={registeredDataset?.name ?? "Not registered"} />
      </div>
      {!compact && <pre className="max-h-48 overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">{sql}</pre>}
    </div>
  );
}

function EmptyState({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center">
      <div className="text-blue-700">{icon}</div>
      <div className="mt-2 text-sm font-semibold text-slate-950">{title}</div>
      <p className="mt-1 max-w-md text-xs leading-5 text-slate-500">{text}</p>
    </div>
  );
}

function SmallButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50">{label}</button>;
}

function fmt(value: unknown) {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(4) : "-";
}

function generateSelectTemplate(refs: SqlDatasetRef[]) {
  return `SELECT *\nFROM ${firstAlias(refs)}\nLIMIT 100;`;
}

function firstAlias(refs: SqlDatasetRef[]) {
  return refs[0]?.alias || "REG_TRAIN";
}

function applyTemplate(item: SqlTemplate, refs: SqlDatasetRef[], mapping: Record<string, string>) {
  let next = item.sql.replaceAll("{table}", firstAlias(refs));
  Object.entries(mapping).forEach(([key, value]) => {
    if (value) next = next.replaceAll(key, value).replaceAll(`{${key}}`, value);
  });
  return next;
}

function resolveSnippet(value: string, refs: SqlDatasetRef[], mapping: Record<string, string>) {
  let next = value.replaceAll("{table}", firstAlias(refs)).replaceAll("{table2}", refs[1]?.alias ?? "SECOND_TABLE");
  Object.entries(mapping).forEach(([key, mapped]) => {
    if (mapped) next = next.replaceAll(`{${key}}`, mapped).replaceAll(key, mapped);
  });
  return next.replaceAll("{column}", mapping.segment_column ?? "column_name").replaceAll("{key}", mapping.customer_id ?? "id");
}

function autoDetectColumnMap(columns: string[]) {
  const lower = new Map(columns.map((column) => [column.toLowerCase(), column]));
  const result: Record<string, string> = {};
  COLUMN_MAPPINGS.forEach((mapping) => {
    const found = mapping.candidates.find((candidate) => lower.has(candidate.toLowerCase()));
    if (found) result[mapping.key] = lower.get(found.toLowerCase()) ?? found;
  });
  return result;
}

function formatSql(value: string) {
  const keywords = ["select", "from", "where", "left join", "right join", "inner join", "join", "on", "group by", "order by", "having", "limit", "union all", "union"];
  let next = value.trim().replace(/\s+/g, " ");
  keywords.forEach((keyword) => {
    const upper = keyword.toUpperCase();
    next = next.replace(new RegExp(`\\b${keyword}\\b`, "gi"), `\n${upper}`);
  });
  next = next.replace(/^\n/, "").replace(/^SELECT\s+/i, "SELECT\n    ");
  next = next.replace(/,\s*/g, ",\n    ");
  next = next.replace(/\n\s*(FROM|WHERE|LEFT JOIN|RIGHT JOIN|INNER JOIN|JOIN|ON|GROUP BY|ORDER BY|HAVING|LIMIT|UNION ALL|UNION)\b/g, "\n$1");
  return next.replace(/\n{2,}/g, "\n").trim();
}

function buildMessages(validation: { status: string; warnings: string[]; error?: string } | null, preview: SqlPreviewResult | null, refs: SqlDatasetRef[], sourceType: SourceType) {
  const messages = [
    `Source mode: ${sourceType}.`,
    `Tables selected: ${refs.map((ref) => ref.alias).join(", ") || "none"}.`,
  ];
  if (validation?.status) messages.push(`Validation status: ${validation.status}.`);
  if (validation?.error) messages.push(`Error: ${validation.error}`);
  validation?.warnings?.forEach((warning) => messages.push(`Warning: ${warning}`));
  if (preview) {
    messages.push(`Preview returned ${preview.returnedRows} rows and ${preview.columns.length} columns in ${preview.runtimeMs} ms.`);
    preview.warnings?.forEach((warning) => messages.push(`Preview warning: ${warning}`));
  }
  if (!preview) messages.push("Run Preview to populate runtime, row count, schema, and result-grid messages.");
  return messages;
}

function inferTags(sql: string, templateItem: SqlTemplate) {
  const tags = new Set(["sql-data-studio", ...templateItem.tags]);
  const text = sql.toLowerCase();
  ["risk", "fraud", "marketing", "monitoring", "data quality", "modeling"].forEach((tag) => {
    if (text.includes(tag.replace(" ", "_")) || text.includes(tag)) tags.add(tag);
  });
  return Array.from(tags);
}

function getCursorPosition(value: string, index: number) {
  const prefix = value.slice(0, index);
  const lines = prefix.split("\n");
  return { line: lines.length, column: lines[lines.length - 1].length + 1 };
}

function readHistory(): QueryHistoryEntry[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.slice(0, 30) : [];
  } catch {
    return [];
  }
}

function writeHistory(entries: QueryHistoryEntry[]) {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, 30)));
  } catch {
    // Query history is convenience state only; do not block SQL workbench actions.
  }
}

function exportSqlDefinition(queryName: string, sql: string, refs: SqlDatasetRef[]) {
  const payload = { queryName, sql, sourceDatasets: refs, exportedAt: new Date().toISOString() };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  downloadBlob(blob, "atlas-sql-definition-lineage.json");
}

function isSqlResultDataset(dataset: DatasetSummary) {
  return (
    dataset.datasetRole === "sql_result" ||
    dataset.sourceType === "sql_studio" ||
    dataset.sourceInfo?.sourceType === "sql_studio" ||
    dataset.sourceInfo?.datasetRole === "sql_result"
  );
}
