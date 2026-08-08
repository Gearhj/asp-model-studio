import type {
  DataAcquisitionReproducibilityContext,
} from "./dataAcquisitionReproducibility";

export type InitialContractBootstrapIdentity = {
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
};

export type InitialContractBootstrapDecision = {
  shouldBootstrap: boolean;
  reason:
    | "fresh_target_pending"
    | "explicit_authority_reconfirmation"
    | "input_incomplete"
    | "identity_mismatch"
    | "authority_already_exists"
    | "partition_already_exists"
    | "context_not_ready";
};

function text(value: unknown) {
  return String(value ?? "").trim();
}

export function initialContractBootstrapKey(input: {
  identity: InitialContractBootstrapIdentity | null;
  target: string;
  eventValue: unknown;
  nonEventValue: unknown;
  selectedPredictors: string[];
}) {
  if (!input.identity || !text(input.target) || !input.selectedPredictors.length) {
    return "";
  }
  return [
    text(input.identity.project_id),
    text(input.identity.dataset_id),
    text(input.identity.dataset_version_id),
    text(input.target),
    JSON.stringify(input.eventValue),
    JSON.stringify(input.nonEventValue),
    [...input.selectedPredictors].map(text).filter(Boolean).sort().join("\u001f"),
  ].join("\u001e");
}

export function decideInitialContractBootstrap(input: {
  context: DataAcquisitionReproducibilityContext;
  identity: InitialContractBootstrapIdentity | null;
  target: string;
  selectedPredictors: string[];
  backendSynced: boolean;
  targetSelectionConfirmed: boolean;
  allowAuthorityReplacement?: boolean;
  localPartitionPresent: boolean;
}): InitialContractBootstrapDecision {
  const { context, identity } = input;
  if (
    !identity ||
    !input.backendSynced ||
    !input.targetSelectionConfirmed ||
    !text(input.target) ||
    !input.selectedPredictors.length
  ) {
    return { shouldBootstrap: false, reason: "input_incomplete" };
  }

  if (!context.identity) {
    return { shouldBootstrap: false, reason: "context_not_ready" };
  }
  if (
    text(context.identity.project_id) !== text(identity.project_id) ||
    text(context.identity.dataset_id) !== text(identity.dataset_id) ||
    text(context.identity.dataset_version_id) !==
      text(identity.dataset_version_id)
  ) {
    return { shouldBootstrap: false, reason: "identity_mismatch" };
  }
  // A sealed partition is immutable from this path. Existing pre-partition
  // authority can be replaced only after a new explicit UI confirmation; an
  // automatic mount/reload attempt remains initial-only.
  if (input.localPartitionPresent || context.analysis_partition) {
    return { shouldBootstrap: false, reason: "partition_already_exists" };
  }
  if (context.target_contract || context.predictor_authorization) {
    return input.allowAuthorityReplacement
      ? {
          shouldBootstrap: true,
          reason: "explicit_authority_reconfirmation",
        }
      : { shouldBootstrap: false, reason: "authority_already_exists" };
  }
  if (context.state !== "target_pending") {
    return { shouldBootstrap: false, reason: "context_not_ready" };
  }
  return { shouldBootstrap: true, reason: "fresh_target_pending" };
}

export function claimInitialContractBootstrapAttempt(
  attemptedKeys: Set<string>,
  key: string,
) {
  if (!key || attemptedKeys.has(key)) return false;
  attemptedKeys.add(key);
  return true;
}

export function releaseInitialContractBootstrapAttempt(
  attemptedKeys: Set<string>,
  key: string,
) {
  if (key) attemptedKeys.delete(key);
}
