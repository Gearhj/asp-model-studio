import { useEffect, useMemo, useState } from "react";
import ReactDOM from "react-dom/client";

import "../src/index.css";
import BureauMetadataBindingPanel from "../src/components/BureauMetadataBindingPanel";
import BureauReviewPanel from "../src/components/BureauReviewPanel";
import type { CanonicalDatasetIdentity } from "../src/lib/datasetIdentity";
import { useWorkflowStore } from "../src/state/useWorkflowStore";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const projects = {
  A: {
    projectId: "synthetic-project-alpha-001",
    datasetId: "synthetic-dataset-alpha-001",
    datasetVersionId: "synthetic-version-alpha-001",
    sourceLabel: "Synthetic bureau data",
    featureNames: ["SYN000", "SYN004"],
    scenario: "Exact match and canonical EDA handoff",
  },
  B: {
    projectId: "synthetic-project-beta-002",
    datasetId: "synthetic-dataset-beta-002",
    datasetVersionId: "synthetic-version-beta-002",
    sourceLabel: "Synthetic bureau mixed mapping data",
    featureNames: [
      "SYN000",
      "ALIAS_SCORE",
      "SYN004",
      "AMBIGUOUS_FIELD",
      "LOCAL_ONLY",
      "SYN005",
    ],
    scenario: "Complete governed-state and contradiction review",
  },
  C: {
    projectId: "synthetic-project-gamma-003",
    datasetId: "synthetic-dataset-gamma-003",
    datasetVersionId: "synthetic-version-gamma-003",
    sourceLabel: "Synthetic bureau data without entitlement",
    featureNames: ["SYN000", "SYN004"],
    scenario: "No entitlement",
  },
  D: {
    projectId: "synthetic-project-delta-004",
    datasetId: "synthetic-dataset-delta-004",
    datasetVersionId: "synthetic-version-delta-004",
    sourceLabel: "Synthetic retail telemetry",
    featureNames: ["LOCAL_A", "LOCAL_B"],
    scenario: "Non-bureau dataset",
  },
  E: {
    projectId: "synthetic-project-epsilon-005",
    datasetId: "synthetic-dataset-epsilon-005",
    datasetVersionId: "synthetic-version-epsilon-005",
    sourceLabel: "Synthetic bureau multi-user isolation",
    featureNames: ["SYN000", "SYN004"],
    scenario: "Multi-user isolation",
  },
} as const;

type ProjectKey = keyof typeof projects;
type ProjectFixture = (typeof projects)[ProjectKey];

function selectedProject() {
  const requested = new URLSearchParams(window.location.search).get("project")?.toUpperCase();
  const key: ProjectKey = requested && requested in projects ? requested as ProjectKey : "A";
  return { key, fixture: projects[key] };
}

type EdaHandoff = {
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  development_only: boolean;
  final_holdout_accessed: boolean;
  training_started: boolean;
  bureau_semantic_annotations?: {
    annotation_set?: {
      annotation_set_id?: string;
      binding_revision?: number;
      crosswalk_revision?: number;
    };
  };
};

function CanonicalEdaHandoff({ projectId, identity }: { projectId: string; identity: CanonicalDatasetIdentity }) {
  const [handoff, setHandoff] = useState<EdaHandoff | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    const path = [projectId, identity.dataset_id, identity.dataset_version_id]
      .map(encodeURIComponent)
      .join("/");
    void fetch(`${API_BASE}/isolated/canonical-eda-handoff/${path}`, {
      credentials: "include",
      signal: controller.signal,
      headers: { Accept: "application/json" },
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => null);
        if (!response.ok || !payload?.ok) throw new Error("Canonical handoff is not available.");
        setHandoff(payload as EdaHandoff);
      })
      .catch((cause: unknown) => {
        if (!(cause instanceof DOMException && cause.name === "AbortError")) {
          setError("Canonical EDA handoff is not yet available for this exact identity.");
        }
      });
    return () => controller.abort();
  }, [identity.dataset_id, identity.dataset_version_id, projectId]);

  return (
    <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm" data-testid="synthetic-canonical-eda-handoff">
      <div className="text-[11px] font-bold uppercase tracking-wide text-emerald-700">Canonical downstream handoff</div>
      <h2 className="mt-1 text-base font-semibold text-emerald-950">EDA receives the exact governed semantic identity</h2>
      {handoff ? (
        <>
          <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-3" data-testid="synthetic-eda-identity-contract">
            <div className="rounded-lg border border-emerald-200 bg-white p-3"><dt className="font-semibold">Project ID</dt><dd className="mt-1 break-all">{handoff.project_id}</dd></div>
            <div className="rounded-lg border border-emerald-200 bg-white p-3"><dt className="font-semibold">Dataset ID</dt><dd className="mt-1 break-all">{handoff.dataset_id}</dd></div>
            <div className="rounded-lg border border-emerald-200 bg-white p-3"><dt className="font-semibold">Dataset version ID</dt><dd className="mt-1 break-all">{handoff.dataset_version_id}</dd></div>
            <div className="rounded-lg border border-emerald-200 bg-white p-3"><dt className="font-semibold">Annotation set</dt><dd className="mt-1 break-all">{handoff.bureau_semantic_annotations?.annotation_set?.annotation_set_id}</dd></div>
            <div className="rounded-lg border border-emerald-200 bg-white p-3"><dt className="font-semibold">Binding / crosswalk</dt><dd className="mt-1">r{handoff.bureau_semantic_annotations?.annotation_set?.binding_revision} / r{handoff.bureau_semantic_annotations?.annotation_set?.crosswalk_revision}</dd></div>
            <div className="rounded-lg border border-emerald-200 bg-white p-3"><dt className="font-semibold">Isolation proof</dt><dd className="mt-1">Final holdout: {handoff.final_holdout_accessed ? "accessed" : "not accessed"} · Training: {handoff.training_started ? "started" : "not started"}</dd></div>
          </dl>
          <p className="mt-3 text-xs leading-5 text-emerald-900">
            Development-only handoff: {handoff.development_only ? "verified" : "not verified"}. The response above is rendered directly from the exact canonical handoff API; no browser or latest-version fallback is used.
          </p>
        </>
      ) : (
        <p className="mt-3 text-xs text-emerald-900">{error || "Loading exact canonical EDA handoff…"}</p>
      )}
    </section>
  );
}

type ConsistencyResult = {
  dataset_field: string;
  consistency_state: string;
  recommendations_blocked: boolean;
  observed_undefined_special_codes?: string[];
  checks?: Record<string, { state?: string; detail?: string }>;
};

function CatalogConsistency({ projectId, identity }: { projectId: string; identity: CanonicalDatasetIdentity }) {
  const [results, setResults] = useState<ConsistencyResult[]>([]);
  const [overall, setOverall] = useState("loading");
  useEffect(() => {
    const controller = new AbortController();
    const base = `/projects/${encodeURIComponent(projectId)}/datasets/${encodeURIComponent(identity.dataset_id)}/versions/${encodeURIComponent(identity.dataset_version_id)}/bureau-metadata`;
    void fetch(`${API_BASE}${base}/crosswalk/consistency`, {
      credentials: "include",
      signal: controller.signal,
      headers: { Accept: "application/json" },
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => null);
        if (!response.ok || !payload?.ok) throw new Error("Consistency evidence is not available.");
        setResults(Array.isArray(payload.results) ? payload.results : []);
        setOverall(String(payload.overall_consistency_state || "unavailable"));
      })
      .catch((cause: unknown) => {
        if (!(cause instanceof DOMException && cause.name === "AbortError")) setOverall("not available");
      });
    return () => controller.abort();
  }, [identity.dataset_id, identity.dataset_version_id, projectId]);
  const contradictions = results.filter((result) => result.consistency_state === "contradictory");
  return (
    <section className="rounded-xl border border-rose-200 bg-white p-5 shadow-sm" data-testid="synthetic-catalog-consistency" data-overall-state={overall}>
      <div className="text-[11px] font-bold uppercase tracking-wide text-rose-700">Backend-authoritative consistency</div>
      <h2 className="mt-1 text-base font-semibold text-slate-950">Catalog-to-observed datatype and range reconciliation</h2>
      <p className="mt-1 text-xs leading-5 text-slate-600">Overall state: <strong>{overall.replaceAll("_", " ")}</strong>. Contradictory recommendations remain blocked.</p>
      <div className="mt-3 space-y-2">
        {contradictions.map((result) => (
          <div key={result.dataset_field} className="rounded-lg border border-rose-300 bg-rose-50 p-3" data-testid={`synthetic-contradiction-${result.dataset_field}`}>
            <div className="flex flex-wrap items-center justify-between gap-2"><strong>{result.dataset_field}</strong><span className="rounded-full border border-rose-300 bg-white px-2 py-1 text-[10px] font-bold uppercase text-rose-800">Contradictory · recommendations blocked</span></div>
            <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
              {Object.entries(result.checks ?? {}).map(([name, check]) => (
                <div key={name} className="rounded border border-rose-200 bg-white p-2">
                  <div><span className="font-semibold">{name.replaceAll("_", " ")}:</span> {String(check.state ?? "unavailable").replaceAll("_", " ")}</div>
                  {check.detail ? <div className="mt-1 leading-4 text-rose-800">{check.detail}</div> : null}
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-rose-900">Observed undefined special codes: {(result.observed_undefined_special_codes ?? []).join(", ") || "none"}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function StableAtlasGuide({ fixture }: { fixture: ProjectFixture }) {
  return (
    <aside className="h-fit rounded-xl border border-slate-200 bg-white p-4 shadow-sm xl:sticky xl:top-4" data-testid="synthetic-atlas-guide-stable" data-stability-key={`${fixture.projectId}:${fixture.datasetVersionId}`}>
      <div className="text-[10px] font-bold uppercase tracking-wide text-blue-700">Atlas Guide · isolated acceptance sentinel</div>
      <h2 className="mt-1 text-sm font-semibold text-slate-950">Data Acquisition</h2>
      <p className="mt-2 text-xs leading-5 text-slate-600">Review the exact entitled catalog, record bounded field decisions, and keep treatment choices separate from provider definitions.</p>
      <dl className="mt-3 space-y-2 text-[11px]"><div><dt className="font-semibold">Project</dt><dd className="break-all">{fixture.projectId}</dd></div><div><dt className="font-semibold">Version</dt><dd className="break-all">{fixture.datasetVersionId}</dd></div></dl>
    </aside>
  );
}

function AcceptancePage({ projectKey, fixture }: { projectKey: ProjectKey; fixture: ProjectFixture }) {
  const identity: CanonicalDatasetIdentity = useMemo(() => ({
    project_id: fixture.projectId,
    dataset_id: fixture.datasetId,
    dataset_version_id: fixture.datasetVersionId,
    activation_revision: 1,
  }), [fixture]);
  const showSpecialValueReview = projectKey === "A" || projectKey === "B";
  return (
    <main className="min-h-screen bg-slate-100 px-6 py-6 text-slate-950" data-testid="synthetic-da-workspace" data-project-scenario={projectKey} data-route-name="data-acquisition">
      <div className="mx-auto max-w-[1800px]">
        <header className="rounded-xl bg-slate-950 px-5 py-4 text-white">
          <div className="text-[11px] font-bold uppercase tracking-wide text-blue-200">Synthetic isolated acceptance · project {projectKey}</div>
          <h1 className="mt-1 text-xl font-semibold">Data Acquisition — {fixture.scenario}</h1>
          <p className="mt-1 text-xs text-slate-300">Exact synthetic project and dataset-version identity only. No training, holdout, or modeling operation is available on this route.</p>
        </header>
        <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
          <div className="min-w-0 space-y-5">
            <BureauMetadataBindingPanel projectId={fixture.projectId} datasetIdentity={identity} featureNames={[...fixture.featureNames]} sourceLabel={fixture.sourceLabel} enabled />
            {projectKey === "B" ? <CatalogConsistency projectId={fixture.projectId} identity={identity} /> : null}
            {showSpecialValueReview ? (
              <BureauReviewPanel target="synthetic_outcome" eventValue={1} enabled datasetIdentity={identity} />
            ) : null}
            {projectKey === "A" ? <CanonicalEdaHandoff projectId={fixture.projectId} identity={identity} /> : null}
          </div>
          <StableAtlasGuide fixture={fixture} />
        </div>
      </div>
    </main>
  );
}

const selection = selectedProject();
useWorkflowStore.setState({
  projectId: selection.fixture.projectId,
  projectName: `Synthetic isolated project ${selection.key}`,
  hasDataset: true,
  datasetIdentity: {
    project_id: selection.fixture.projectId,
    dataset_id: selection.fixture.datasetId,
    dataset_version_id: selection.fixture.datasetVersionId,
    activation_revision: 1,
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <AcceptancePage projectKey={selection.key} fixture={selection.fixture} />,
);
