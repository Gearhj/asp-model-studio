import { WorkflowStep } from "./workflow.schema";

export const WORKFLOW_STEPS: WorkflowStep[] = [
  { id: "dashboard",          title: "Dashboard",                     description: "Overview" },
  { id: "data-acquisition",   title: "Step 1: Data Acquisition",      description: "Load & summarize",              requires: ["dashboard"] },
  { id: "eda",                title: "Step 2: EDA",                   description: "Explore features & imbalance",  requires: ["data-acquisition"] },
  { id: "outlier-handling",   title: "Step 3: Outlier Analysis",      description: "Detect & cap",                  requires: ["eda"] },
  { id: "missing-values",     title: "Step 4: Missing Values",        description: "Profile & impute",              requires: ["outlier-handling"] },
  { id: "feature-engineering",title: "Step 5: Feature Engineering",   description: "Encode, scale, interactions",   requires: ["missing-values"] },
  { id: "data-balancing",     title: "Step 6: Balancing & Split",     description: "Class balance & holdout split", requires: ["feature-engineering"] },
  { id: "model-training",     title: "Step 7: Model Training",        description: "Select & train",                requires: ["data-balancing"] },
  { id: "evaluation",         title: "Step 8: Evaluation",            description: "Metrics & charts",              requires: ["model-training"] },
  { id: "interpretation",     title: "Step 9: Model Interpretation",  description: "Explain & select features",      requires: ["evaluation"] },
  { id: "scoring",            title: "Step 10: Final Scoring",        description: "TEST/OOT scoring & stability",   requires: ["interpretation"] },
];
