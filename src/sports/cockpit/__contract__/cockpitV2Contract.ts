// Phase 7D.4 (B9 / Gate 9) — TS side of the shared backend↔frontend contract. It imports the SAME JSON fixture
// the Python contract test validates against the Pydantic DTOs, and assigns each entry to its V2 type. tsc
// therefore proves the representative payloads match the exact response shapes the cockpit reads. If the backend
// DTO and this fixture diverge in any field (type/shape), this module fails to compile (and `tsc -b` fails).
import fixture from "./cockpit_v2_contract.json";
import type {
  ActiveCandidateResponseV2, ModelEvaluationResponseV2, ModelCalibrationResponseV2,
  ModelRegistryEvidenceResponseV2, FeatureFamilyComparisonResponseV2,
} from "../cockpitApiV2";

// A JSON import widens string-literal discriminants (the `schemaVersion` fields) to `string`; loosen ONLY those
// top-level literal-string fields so the fixture is structurally checkable. Every non-literal field (numbers,
// booleans, arrays, nested objects) is still verified exactly by tsc.
type LooseLiterals<T> = { [K in keyof T]: T[K] extends string ? string : T[K] };

export const activeCandidateContract: LooseLiterals<ActiveCandidateResponseV2> = fixture.activeCandidate;
export const evaluationContract: LooseLiterals<ModelEvaluationResponseV2> = fixture.evaluation;
export const calibrationContract: LooseLiterals<ModelCalibrationResponseV2> = fixture.calibration;
export const registryEvidenceContract: LooseLiterals<ModelRegistryEvidenceResponseV2> = fixture.registryEvidence;
export const comparisonContract: LooseLiterals<FeatureFamilyComparisonResponseV2> = fixture.comparison;

// Touch the exports so an unused-locals config never elides the checks.
export const _v2ContractShapes = [
  activeCandidateContract.schemaVersion, evaluationContract.schemaVersion, calibrationContract.schemaVersion,
  registryEvidenceContract.schemaVersion, comparisonContract.schemaVersion,
];
