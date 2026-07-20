import { useParams } from "react-router-dom";
import LlmUseCaseRiskContext from "./LlmUseCaseRiskContext";
import LlmDataKnowledgeSources from "./LlmDataKnowledgeSources";
import LlmTaskOutputSchema from "./LlmTaskOutputSchema";
import LlmPromptInstructionDesign from "./LlmPromptInstructionDesign";
import LlmRetrievalRagConfiguration from "./LlmRetrievalRagConfiguration";
import LlmEvaluationDataset from "./LlmEvaluationDataset";
import LlmEvaluation from "./LlmEvaluation";
import LlmSafetyComplianceReview from "./LlmSafetyComplianceReview";
import LlmHumanReviewQualityControl from "./LlmHumanReviewQualityControl";
import LlmDeploymentMonitoringPlan from "./LlmDeploymentMonitoringPlan";
import LlmRecommendationApproval from "./LlmRecommendationApproval";
import LlmDocumentation from "./LlmDocumentation";

const pages = [
  LlmUseCaseRiskContext,
  LlmDataKnowledgeSources,
  LlmTaskOutputSchema,
  LlmPromptInstructionDesign,
  LlmRetrievalRagConfiguration,
  LlmEvaluationDataset,
  LlmEvaluation,
  LlmSafetyComplianceReview,
  LlmHumanReviewQualityControl,
  LlmDeploymentMonitoringPlan,
  LlmRecommendationApproval,
  LlmDocumentation,
];

export default function LlmWorkflowPage() {
  const { stepNumber } = useParams();
  const index = Math.max(0, Math.min(pages.length - 1, Number(stepNumber ?? 1) - 1));
  const Page = pages[index] ?? LlmUseCaseRiskContext;
  return <Page />;
}
