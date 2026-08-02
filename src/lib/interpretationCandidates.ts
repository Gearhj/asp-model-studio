import {
  canonicalDatasetStorageKey,
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";

export type CandidateTask = "classification" | "regression" | "anomaly";

/**
 * Frozen browser representation of a backend-governed training candidate.
 *
 * The browser never creates any of these identifiers. It only validates and
 * preserves the exact contract returned by the training service so Evaluation
 * and Interpretation can address one immutable candidate. `key` and `name`
 * remain display fields and are never used as candidate identity.
 */
export type InterpretationCandidate = {
  candidate_id: string;
  training_job_id: string;
  training_run_id: string;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  target: string;
  feature_manifest_version: string;
  validation_design_id: string;
  validation_design_version: string;
  split_id: string;
  key: string;
  name: string;
  task: CandidateTask;
  selectedAt: string;
};

export type InterpretationCandidateInput = Partial<InterpretationCandidate> & Record<string, unknown>;

export type CandidateRequestContext = Pick<
  InterpretationCandidate,
  | "candidate_id"
  | "training_job_id"
  | "training_run_id"
  | "project_id"
  | "dataset_id"
  | "dataset_version_id"
  | "target"
  | "feature_manifest_version"
  | "validation_design_id"
  | "validation_design_version"
  | "split_id"
>;

const REQUIRED_FIELDS: ReadonlyArray<keyof CandidateRequestContext> = [
  "candidate_id",
  "training_job_id",
  "training_run_id",
  "project_id",
  "dataset_id",
  "dataset_version_id",
  "target",
  "feature_manifest_version",
  "validation_design_id",
  "validation_design_version",
  "split_id",
];

function requiredString(value: unknown, field: string): string {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) throw new Error(`Candidate contract is missing required ${field}.`);
  return text;
}

function optionalString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function assertEmbeddedContractMatches(input: InterpretationCandidateInput) {
  const embedded = input.candidate_contract;
  if (!embedded || typeof embedded !== "object" || Array.isArray(embedded)) return;
  const contract = embedded as Record<string, unknown>;
  const targetDefinition =
    contract.target_definition && typeof contract.target_definition === "object" && !Array.isArray(contract.target_definition)
      ? contract.target_definition as Record<string, unknown>
      : {};
  const comparisons: Array<[string, string, string]> = [
    ["candidate_id", optionalString(input.candidate_id), optionalString(contract.candidate_id)],
    ["training_job_id", optionalString(input.training_job_id), optionalString(contract.training_job_id)],
    ["training_run_id", optionalString(input.training_run_id), optionalString(contract.training_run_id)],
    ["project_id", optionalString(input.project_id), optionalString(contract.project_id)],
    ["dataset_id", optionalString(input.dataset_id), optionalString(contract.dataset_id)],
    ["dataset_version_id", optionalString(input.dataset_version_id), optionalString(contract.dataset_version_id)],
    ["target", optionalString(input.target), optionalString(contract.target ?? contract.target_name)],
    [
      "feature_manifest_version",
      optionalString(input.feature_manifest_version),
      optionalString(contract.feature_manifest_version ?? contract.feature_manifest_hash),
    ],
    ["validation_design_id", optionalString(input.validation_design_id), optionalString(contract.validation_design_id)],
    [
      "validation_design_version",
      optionalString(input.validation_design_version),
      optionalString(contract.validation_design_version),
    ],
    ["split_id", optionalString(input.split_id), optionalString(contract.split_id)],
    ["problem_type", optionalString(input.task), optionalString(contract.problem_type ?? targetDefinition.problem_type)],
    ["algorithm_id", optionalString(input.key), optionalString(contract.algorithm_id)],
  ];
  for (const [field, rowValue, contractValue] of comparisons) {
    if (rowValue && contractValue && rowValue !== contractValue) {
      throw new Error(`Candidate row conflicts with its frozen ${field} binding.`);
    }
  }
}

export function requireInterpretationCandidate(input: InterpretationCandidateInput): InterpretationCandidate {
  assertEmbeddedContractMatches(input);
  const identity = requireCanonicalDatasetIdentity(
    {
      project_id: input.project_id,
      dataset_id: input.dataset_id,
      dataset_version_id: input.dataset_version_id,
    },
    "Training candidate dataset identity",
  );
  const task = requiredString(input.task, "task");
  if (task !== "classification" && task !== "regression" && task !== "anomaly") {
    throw new Error(`Candidate contract contains unsupported task ${task}.`);
  }
  return {
    candidate_id: requiredString(input.candidate_id, "candidate_id"),
    training_job_id: requiredString(input.training_job_id, "training_job_id"),
    training_run_id: requiredString(input.training_run_id, "training_run_id"),
    ...identity,
    target: requiredString(input.target, "target"),
    feature_manifest_version: requiredString(input.feature_manifest_version, "feature_manifest_version"),
    validation_design_id: requiredString(input.validation_design_id, "validation_design_id"),
    validation_design_version: requiredString(input.validation_design_version, "validation_design_version"),
    split_id: requiredString(input.split_id, "split_id"),
    key: requiredString(input.key, "display key"),
    name: requiredString(input.name, "display name"),
    task,
    selectedAt: requiredString(input.selectedAt, "selectedAt"),
  };
}

function keyFor(identity: CanonicalDatasetIdentity) {
  return canonicalDatasetStorageKey("atlas-interpretation-candidates", identity);
}

export function candidateMatchesDataset(
  candidate: InterpretationCandidate,
  identity: CanonicalDatasetIdentity,
): boolean {
  return (
    candidate.project_id === identity.project_id &&
    candidate.dataset_id === identity.dataset_id &&
    candidate.dataset_version_id === identity.dataset_version_id
  );
}

export function sameCandidate(left: InterpretationCandidate, right: InterpretationCandidate): boolean {
  return REQUIRED_FIELDS.every((field) => left[field] === right[field]);
}

export function candidateRequestParams(candidate: InterpretationCandidate): URLSearchParams {
  const params = new URLSearchParams();
  for (const field of REQUIRED_FIELDS) params.set(field, candidate[field]);
  params.set("problem_type", candidate.task);
  return params;
}

export function loadInterpretationCandidates(identity: CanonicalDatasetIdentity): InterpretationCandidate[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(keyFor(identity)) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((item) => {
      try {
        const candidate = requireInterpretationCandidate(item);
        return candidateMatchesDataset(candidate, identity) ? [candidate] : [];
      } catch {
        return [];
      }
    });
  } catch {
    return [];
  }
}

export function saveInterpretationCandidates(
  identity: CanonicalDatasetIdentity,
  candidates: InterpretationCandidate[],
) {
  const validated = candidates.map(requireInterpretationCandidate);
  if (!validated.every((candidate) => candidateMatchesDataset(candidate, identity))) {
    throw new Error("Cannot persist an Interpretation candidate from another project or dataset version.");
  }
  localStorage.setItem(keyFor(identity), JSON.stringify(validated));
  return validated;
}
