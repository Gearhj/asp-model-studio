import { useCallback, useState } from "react";
import ReactDOM from "react-dom/client";

import BureauReviewPanel, {
  type BureauReviewPanelResult,
  type BureauReviewPanelStatus,
} from "../src/components/BureauReviewPanel";
import type { CanonicalDatasetIdentity } from "../src/lib/datasetIdentity";
import { useWorkflowStore } from "../src/state/useWorkflowStore";

const projectId = "isolated-heloc-automatic-special-values";
const identity: CanonicalDatasetIdentity = {
  project_id: projectId,
  dataset_id: "isolated-heloc-dataset",
  dataset_version_id: "isolated-heloc-version",
  activation_revision: 2,
};

function AutomaticDetectionProbe() {
  const [handoff, setHandoff] = useState<BureauReviewPanelResult | null>(null);
  const [status, setStatus] = useState<BureauReviewPanelStatus | null>(null);
  const handleReviewResult = useCallback(
    (next: BureauReviewPanelResult | null) => setHandoff(next),
    [],
  );
  const handleReviewStatus = useCallback(
    (next: BureauReviewPanelStatus) => setStatus(next),
    [],
  );
  const callbackEvidence = handoff
    ? handoff.detection.variables.map((variable) => ({
        variable: variable.variable,
        values: variable.special_values.map((profile) => profile.value),
        count: variable.special_value_count,
      }))
    : null;

  return (
    <main data-testid="automatic-special-value-probe">
      <BureauReviewPanel
        target="bad_flag"
        eventValue={1}
        enabled
        datasetIdentity={identity}
        onReviewResult={handleReviewResult}
        onReviewStatus={handleReviewStatus}
      />
      <output
        data-testid="automatic-special-value-callback"
        data-ready={String(Boolean(handoff))}
        data-blocking={String(status?.blocking ?? true)}
      >
        {callbackEvidence ? JSON.stringify(callbackEvidence) : "pending"}
      </output>
    </main>
  );
}

useWorkflowStore.setState({
  projectId,
  projectName: "Isolated HELOC automatic special-value test",
  hasDataset: true,
  datasetIdentity: identity,
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <AutomaticDetectionProbe />,
);
