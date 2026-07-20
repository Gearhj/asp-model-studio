import { useParams } from "react-router-dom";
import WorkflowPlaceholderStep from "../../../steps/WorkflowPlaceholderStep";
import TimeSeriesWorkflowPage from "../../../workflows/time-series/TimeSeriesWorkflowPage";
import LlmWorkflowPage from "../../../workflows/llm/LlmWorkflowPage";

export default function ExperimentalDesignWorkflowPage() {
  const { workflowId } = useParams();

  if (workflowId === "time_series_forecasting") {
    return <TimeSeriesWorkflowPage />;
  }

  if (workflowId === "llm_generative_ai") {
    return <LlmWorkflowPage />;
  }

  return <WorkflowPlaceholderStep />;
}
