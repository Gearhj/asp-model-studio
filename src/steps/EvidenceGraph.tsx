import { useEffect, useMemo, useState } from "react";
import type React from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Database, Download, FileText, Filter, GitBranch, Network, PlusCircle, RefreshCw, Search, ShieldCheck } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  autoCaptureEvidence,
  createEvidence,
  deleteEvidence,
  EVIDENCE_TYPES,
  exportEvidencePack,
  FINANCIAL_SERVICES_TAGS,
  getEvidenceCoverage,
  getEvidenceGraph,
  listEvidence,
  updateEvidence,
  type EvidenceCoverage,
  type EvidenceGraphPayload,
  type EvidenceItem,
} from "../lib/evidenceGraph";
import {
  CREDIT_RISK_DOCUMENTATION_MAPPING,
  CREDIT_RISK_FORM_DEFINITIONS,
  CREDIT_RISK_TECHNIQUE_OPTIONS,
  FINANCIAL_DOMAIN_OPTIONS,
  MODEL_PURPOSE_OPTIONS,
  PRODUCT_TYPE_OPTIONS,
  regulatoryForTechnique,
  techniqueLabel,
} from "../lib/financialServicesEvidence";
import { useWorkflowStore } from "../state/useWorkflowStore";

type EvidenceTab = "inventory" | "timeline" | "map" | "coverage" | "financial";

export default function EvidenceGraph() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [items, setItems] = useState<EvidenceItem[]>([]);
  const [coverage, setCoverage] = useState<EvidenceCoverage | null>(null);
  const [graph, setGraph] = useState<EvidenceGraphPayload>({ nodes: [], edges: [] });
  const [selected, setSelected] = useState<EvidenceItem | null>(null);
  const [tab, setTab] = useState<EvidenceTab>("inventory");
  const [mapFocusMode, setMapFocusMode] = useState(false);
  const [filters, setFilters] = useState({ search: "", evidenceType: "", status: "", importance: "", tag: "", financialDomain: "", financialTechnique: "", productType: "", modelPurpose: "", regulatoryRelevance: "" });
  const [creditRiskForm, setCreditRiskForm] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    setMessage("");
    try {
      const nextItems = await listEvidence({ projectId, ...filters });
      const [nextGraph, nextCoverage] = await Promise.all([
        getEvidenceGraph(projectId).catch(() => ({ nodes: [], edges: [] })),
        getEvidenceCoverage(projectId).catch(() => null),
      ]);
      setItems(nextItems);
      setGraph(nextGraph);
      setCoverage(nextCoverage);
      setSelected((current) => nextItems.find((item) => item.evidenceId === current?.evidenceId) ?? nextItems[0] ?? null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not load evidence.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [projectId, filters.evidenceType, filters.status, filters.importance, filters.tag, filters.financialDomain, filters.financialTechnique, filters.productType, filters.modelPurpose, filters.regulatoryRelevance]);

  const filtered = useMemo(() => {
    const search = filters.search.trim().toLowerCase();
    if (!search) return items;
    return items.filter((item) => `${item.title} ${item.summary} ${item.sourcePage} ${item.projectName}`.toLowerCase().includes(search));
  }, [items, filters.search]);

  async function captureCurrentProject() {
    setLoading(true);
    try {
      const captured = await autoCaptureEvidence({ projectId, projectName });
      setMessage(`Captured or refreshed ${captured.length} evidence item(s).`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not capture evidence.");
    } finally {
      setLoading(false);
    }
  }

  async function markStatus(item: EvidenceItem, status: EvidenceItem["status"]) {
    const updated = await updateEvidence(item.evidenceId, { status });
    setItems((current) => current.map((candidate) => (candidate.evidenceId === updated.evidenceId ? updated : candidate)));
    setSelected(updated);
  }

  async function attachToDocumentation(item: EvidenceItem) {
    const sections = Array.from(new Set([...(item.supportsSections ?? []), "Model Development Document", "Appendix"]));
    const updated = await updateEvidence(item.evidenceId, { supportsSections: sections, status: item.status === "draft" ? "ready" : item.status });
    setItems((current) => current.map((candidate) => (candidate.evidenceId === updated.evidenceId ? updated : candidate)));
    setSelected(updated);
    setMessage("Evidence attached to documentation mapping.");
  }

  async function exportPack() {
    const blob = await exportEvidencePack(projectId);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "atlas-evidence-pack.xlsx";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function saveCreditRiskEvidence(technique: string, values: Record<string, string>) {
    const mapping = CREDIT_RISK_DOCUMENTATION_MAPPING[technique] ?? ["Fair Lending / Compliance Considerations", "Appendix"];
    const saved = await createEvidence({
      projectId,
      projectName,
      evidenceType: technique === "psi" || technique === "cutoff_optimization" ? "model_diagnostics" : "governance",
      title: `${techniqueLabel(technique)} Evidence`,
      summary: values.rationale || values.finding || values.selectionDecision || `${techniqueLabel(technique)} evidence captured for credit-risk governance.`,
      sourcePage: "Model Evidence Center",
      sourceRoute: "/model-evidence-center",
      artifactType: "credit_risk_evidence",
      artifactId: technique,
      tags: ["credit_risk", technique, "fair_lending", "model_risk"].filter(Boolean),
      financialDomain: "credit_risk",
      financialTechnique: technique,
      regulatoryRelevance: regulatoryForTechnique(technique),
      creditRiskContext: {
        productType: values.productType,
        modelPurpose: values.modelPurpose,
        targetEvent: values.targetEvent,
        targetWindow: values.targetWindow,
        scorecardStyle: values.scorecardStyle,
        pdoConfigured: technique === "pdo",
        baseOddsConfigured: Boolean(values.baseOdds),
        baseScoreConfigured: Boolean(values.baseScore),
      },
      supportsSections: mapping,
      status: "ready",
      importance: regulatoryForTechnique(technique).fairLending || regulatoryForTechnique(technique).adverseAction ? "critical" : "high",
      payload: {
        ...values,
        pdoFormula: technique === "pdo" ? "Score = Offset + Factor * ln(odds); Factor = PDO / ln(2); Offset = BaseScore - Factor * ln(BaseOdds)" : undefined,
      },
      governance: {
        documentationMapping: mapping,
        guidance: "Captured from the Financial Services Evidence Taxonomy for credit-risk model governance.",
      },
    });
    setSelected(saved);
    setCreditRiskForm(null);
    setMessage(`${techniqueLabel(technique)} evidence saved to the Model Evidence Center.`);
    await refresh();
  }

  return (
    <div className="min-h-[calc(100vh-8rem)] space-y-5">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
            <div className="flex items-center gap-2">
              <Network size={23} className="text-blue-700" />
              <h1 className="text-2xl font-semibold tracking-tight text-slate-950">Model Evidence Center</h1>
            </div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
              Collects the proof behind your model: datasets, SQL, notebooks, charts, diagnostics, documentation, governance notes, and financial-services evidence.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => setCreditRiskForm("woe")} className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-800 shadow-sm hover:bg-blue-100">
              <PlusCircle size={15} />
              Add Credit Risk Evidence
            </button>
            <button type="button" onClick={captureCurrentProject} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
              Capture Current Project Evidence
            </button>
            <button type="button" onClick={exportPack} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <Download size={15} />
              Export Model Evidence Pack
            </button>
          </div>
        </div>
        {message && <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{message}</div>}
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <InfoCard
          title="Why this matters"
          text="Financial-services models must be defensible. The Model Evidence Center helps you track what was done, where the proof lives, what documentation sections it supports, and what evidence is still missing before validation, audit, or model risk review."
        />
        <InfoCard
          title="What counts as evidence?"
          text="Datasets, SQL queries, saved analyses, charts, notebook outputs, model training results, diagnostics, governance warnings, credit-risk evidence, documentation sections, and exported review packages."
        />
      </section>

      {creditRiskForm && (
        <CreditRiskEvidenceForm
          technique={creditRiskForm}
          onTechniqueChange={setCreditRiskForm}
          onCancel={() => setCreditRiskForm(null)}
          onSave={saveCreditRiskEvidence}
        />
      )}

      <section className="grid gap-4 md:grid-cols-5">
        <Metric label="Total Evidence" value={String(filtered.length)} />
        <Metric label="Ready Evidence" value={String(coverage?.readyEvidence ?? filtered.filter((item) => item.status === "ready" || item.status === "accepted").length)} />
        <Metric label="Needs Review" value={String(coverage?.needsReviewEvidence ?? filtered.filter((item) => item.status === "needs_review").length)} />
        <Metric label="Missing Critical Evidence" value={String((coverage?.missingRecommended ?? []).length + (coverage?.financialServices?.creditRisk?.missingRequired?.length ?? 0))} />
        <Metric label="Coverage Score" value={`${coverage?.coverageScore ?? 0}%`} />
      </section>
      <section className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-sm font-semibold text-slate-950">Evidence status at a glance</div>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <Metric label="Total Evidence" value={String(filtered.length)} />
            <Metric label="Ready Evidence" value={String(coverage?.readyEvidence ?? 0)} />
            <Metric label="Missing Critical Evidence" value={String((coverage?.missingRecommended ?? []).length + (coverage?.financialServices?.creditRisk?.missingRequired?.length ?? 0))} />
          </div>
        </div>
        <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 shadow-sm">
          <div className="text-sm font-semibold text-blue-950">Recommended Next Actions</div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={captureCurrentProject} className="rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white">Capture current project evidence</button>
            <button type="button" onClick={() => setCreditRiskForm("woe")} className="rounded-lg border border-blue-300 bg-white px-3 py-2 text-xs font-semibold text-blue-800">Add credit-risk evidence</button>
            <button type="button" onClick={exportPack} className="rounded-lg border border-blue-300 bg-white px-3 py-2 text-xs font-semibold text-blue-800">Export evidence pack</button>
            <Link to="/model-document-studio" className="rounded-lg border border-blue-300 bg-white px-3 py-2 text-xs font-semibold text-blue-800">Attach evidence to documentation</Link>
          </div>
        </div>
      </section>

      <section className={`grid gap-5 ${tab === "map" ? (mapFocusMode ? "xl:grid-cols-1" : "xl:grid-cols-[260px_minmax(0,1fr)]") : "xl:grid-cols-[260px_minmax(0,1fr)_340px]"}`}>
        <aside className={`${tab === "map" && mapFocusMode ? "hidden" : ""} rounded-2xl border border-slate-200 bg-white p-4 shadow-sm`}>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <Filter size={16} />
            Filters
          </div>
          <label className="mt-4 block text-xs font-semibold uppercase tracking-wide text-slate-500">Search</label>
          <div className="mt-1 flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-2 py-1">
            <Search size={14} className="text-slate-400" />
            <input value={filters.search} onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))} className="min-w-0 flex-1 py-1 text-sm outline-none" placeholder="Evidence text..." />
          </div>
          <FilterSelect label="Evidence Type" value={filters.evidenceType} options={EVIDENCE_TYPES} onChange={(value) => setFilters((current) => ({ ...current, evidenceType: value }))} />
          <FilterSelect label="Status" value={filters.status} options={["draft", "ready", "needs_review", "accepted", "deprecated"]} onChange={(value) => setFilters((current) => ({ ...current, status: value }))} />
          <FilterSelect label="Importance" value={filters.importance} options={["low", "medium", "high", "critical"]} onChange={(value) => setFilters((current) => ({ ...current, importance: value }))} />
          <FilterSelect label="Financial Services Tag" value={filters.tag} options={FINANCIAL_SERVICES_TAGS} onChange={(value) => setFilters((current) => ({ ...current, tag: value }))} />
          <FilterSelect label="Financial Domain" value={filters.financialDomain} options={FINANCIAL_DOMAIN_OPTIONS.map((item) => item.value)} onChange={(value) => setFilters((current) => ({ ...current, financialDomain: value }))} />
          <FilterSelect label="Credit Risk Technique" value={filters.financialTechnique} options={CREDIT_RISK_TECHNIQUE_OPTIONS.map((item) => item.value)} onChange={(value) => setFilters((current) => ({ ...current, financialTechnique: value }))} />
          <FilterSelect label="Product Type" value={filters.productType} options={PRODUCT_TYPE_OPTIONS} onChange={(value) => setFilters((current) => ({ ...current, productType: value }))} />
          <FilterSelect label="Model Purpose" value={filters.modelPurpose} options={MODEL_PURPOSE_OPTIONS} onChange={(value) => setFilters((current) => ({ ...current, modelPurpose: value }))} />
          <FilterSelect label="Regulatory Relevance" value={filters.regulatoryRelevance} options={["adverseAction", "fairLending", "modelRisk", "explainability", "pricingDecision"]} onChange={(value) => setFilters((current) => ({ ...current, regulatoryRelevance: value }))} />
        </aside>

        <main className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 pb-3">
            {[
              ["inventory", "Evidence Inventory"],
              ["timeline", "Timeline"],
              ["map", "Evidence Map"],
              ["coverage", "Coverage"],
              ["financial", "Financial Services"],
            ].map(([id, label]) => (
              <button key={id} type="button" onClick={() => setTab(id as EvidenceTab)} className={`rounded-lg px-3 py-2 text-sm font-semibold ${tab === id ? "bg-slate-950 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}>
                {label}
              </button>
            ))}
          </div>
          {tab === "inventory" && <EvidenceTable items={filtered} onSelect={setSelected} onReady={(item) => markStatus(item, "ready")} onReview={(item) => markStatus(item, "needs_review")} onAttach={attachToDocumentation} />}
          {tab === "timeline" && <EvidenceTimeline items={filtered} onSelect={setSelected} />}
          {tab === "map" && <InteractiveEvidenceMapView graph={graph} items={filtered} onCapture={captureCurrentProject} focusMode={mapFocusMode} onFocusModeChange={setMapFocusMode} />}
          {tab === "coverage" && <CoverageView coverage={coverage} />}
          {tab === "financial" && <FinancialServicesView coverage={coverage} />}
        </main>

        {tab !== "map" && <aside className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <ShieldCheck size={16} />
            Evidence Detail
          </div>
          {selected ? (
            <div className="mt-4 space-y-3">
              <div>
              <div className="text-lg font-semibold text-slate-950">{selected.title}</div>
                <div className="mt-1 flex flex-wrap gap-1">
                  <Badge>{selected.evidenceType}</Badge>
                  <Badge>{selected.status}</Badge>
                  <Badge>{selected.importance}</Badge>
                </div>
              </div>
              <p className="text-sm leading-6 text-slate-600">{selected.summary}</p>
              <DetailBlock title="What this proves" text={evidenceProof(selected)} />
              <DetailBlock title="Where it came from" text={`${selected.sourcePage || "ATLAS"}\n${selected.sourceRoute || ""}`} />
              <DetailBlock title="What it supports" text={(selected.supportsSections ?? []).join("\n") || "No model document sections mapped."} />
              <DetailBlock title="Lineage" text={JSON.stringify(selected.lineage ?? {}, null, 2)} />
              <DetailBlock title="Document support" text={(selected.supportsSections ?? []).join("\n") || "No model document sections mapped."} />
              <DetailBlock title="Financial Services Context" text={`Domain: ${selected.financialDomain || "-"}\nTechnique: ${selected.financialTechnique || "-"}\nProduct: ${selected.creditRiskContext?.productType || "-"}\nPurpose: ${selected.creditRiskContext?.modelPurpose || "-"}`} />
              <DetailBlock title="Regulatory Relevance" text={JSON.stringify(selected.regulatoryRelevance ?? {}, null, 2)} />
              <DetailBlock title="Credit Risk Context" text={JSON.stringify(selected.creditRiskContext ?? {}, null, 2)} />
              <DetailBlock title="Governance notes" text={JSON.stringify(selected.governance ?? {}, null, 2)} />
              <DetailBlock title="Recommended action" text={selected.status === "ready" || selected.status === "accepted" ? "Attach this evidence to the appropriate model document section or include it in an audit evidence pack." : "Review this evidence, resolve gaps, then mark it ready before validation or audit use."} />
              <div className="grid gap-2">
                {selected.sourceRoute && (
                  <Link to={selected.sourceRoute} className="atlas-secondary-button justify-center">
                    Open Source <ArrowUpRight size={14} />
                  </Link>
                )}
                <button type="button" onClick={() => markStatus(selected, "ready")} className="atlas-secondary-button justify-center">Mark Ready</button>
                <button type="button" onClick={() => markStatus(selected, "needs_review")} className="atlas-secondary-button justify-center">Mark Needs Review</button>
                <button type="button" onClick={() => attachToDocumentation(selected)} className="inline-flex items-center justify-center rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white">Attach to Documentation</button>
                <button type="button" onClick={() => deleteEvidence(selected.evidenceId).then(refresh)} className="rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700">Delete Evidence</button>
              </div>
            </div>
          ) : (
            <p className="mt-4 rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">Select an evidence item to inspect lineage, mappings, and governance notes.</p>
          )}
        </aside>}
      </section>
    </div>
  );
}

function CreditRiskEvidenceForm({ technique, onTechniqueChange, onCancel, onSave }: { technique: string; onTechniqueChange: (technique: string) => void; onCancel: () => void; onSave: (technique: string, values: Record<string, string>) => Promise<void> }) {
  const definition = CREDIT_RISK_FORM_DEFINITIONS[technique] ?? CREDIT_RISK_FORM_DEFINITIONS.woe;
  const [values, setValues] = useState<Record<string, string>>({
    productType: PRODUCT_TYPE_OPTIONS[0],
    modelPurpose: MODEL_PURPOSE_OPTIONS[0],
    targetEvent: "Default / bad outcome",
    targetWindow: "12 months",
    scorecardStyle: "Traditional scorecard",
  });
  const [saving, setSaving] = useState(false);
  const update = (key: string, value: string) => setValues((current) => ({ ...current, [key]: value }));
  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50/70 p-5 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Credit Risk Evidence Capture</div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">{definition.title}</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
            Capture audit-ready evidence for underwriting, portfolio risk, regulatory governance, decision strategy, and modern scorecard documentation.
          </p>
          {technique === "pdo" && (
            <div className="mt-2 rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-900">
              PDO guidance: Score = Offset + Factor * ln(odds); Factor = PDO / ln(2); Offset = BaseScore - Factor * ln(BaseOdds).
            </div>
          )}
        </div>
        <select value={technique} onChange={(event) => onTechniqueChange(event.target.value)} className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-slate-900">
          {CREDIT_RISK_TECHNIQUE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <FormSelect label="Product Type" value={values.productType} options={PRODUCT_TYPE_OPTIONS} onChange={(value) => update("productType", value)} />
        <FormSelect label="Model Purpose" value={values.modelPurpose} options={MODEL_PURPOSE_OPTIONS} onChange={(value) => update("modelPurpose", value)} />
        <FormInput label="Target Window" value={values.targetWindow} helper="Example: 12 months, 90 days, application time." onChange={(value) => update("targetWindow", value)} />
        <FormInput label="Target Event" value={values.targetEvent} helper="Default, delinquency, approval, charge-off, loss, or other event." onChange={(value) => update("targetEvent", value)} />
        <FormInput label="Scorecard Style" value={values.scorecardStyle} helper="Traditional scorecard, monotonic GBM, surrogate scorecard, or policy overlay." onChange={(value) => update("scorecardStyle", value)} />
        {definition.fields.map((field) => (
          <FormInput key={field.key} label={field.label} value={values[field.key] ?? ""} helper={field.helper} onChange={(value) => update(field.key, value)} />
        ))}
        <label className="lg:col-span-3 grid gap-1 text-xs font-semibold uppercase text-slate-500">
          Rationale
          <textarea value={values.rationale ?? ""} onChange={(event) => update("rationale", event.target.value)} rows={3} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case text-slate-900" placeholder="Document the decision, evidence, limitations, and reviewer rationale." />
        </label>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" disabled={saving} onClick={async () => { setSaving(true); try { await onSave(technique, values); } finally { setSaving(false); } }} className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white">
          {saving ? "Saving..." : "Save Credit Risk Evidence"}
        </button>
        <button type="button" onClick={onCancel} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700">Cancel</button>
      </div>
    </section>
  );
}

function InfoCard({ title, text }: { title: string; text: string }) {
  return (
    <section className="rounded-2xl border border-blue-100 bg-white p-5 shadow-sm">
      <div className="text-sm font-semibold text-slate-950">{title}</div>
      <p className="mt-2 text-sm leading-6 text-slate-600">{text}</p>
    </section>
  );
}

function EvidenceTable({ items, onSelect, onReady, onReview, onAttach }: { items: EvidenceItem[]; onSelect: (item: EvidenceItem) => void; onReady: (item: EvidenceItem) => void; onReview: (item: EvidenceItem) => void; onAttach: (item: EvidenceItem) => void }) {
  return (
    <div className="mt-4 overflow-auto rounded-xl border border-slate-200">
      <table className="min-w-[1100px] w-full text-left text-sm">
        <thead className="sticky top-0 bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
          <tr>
            {["Title", "Type", "Credit Risk", "Source", "Project", "Dataset", "Status", "Importance", "Created", "Document support", "Actions"].map((header) => (
              <th key={header} className="px-3 py-2">{header}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((item, index) => (
            <tr key={item.evidenceId} className={index % 2 ? "bg-white" : "bg-slate-50/80"}>
              <td className="max-w-xs px-3 py-3 font-semibold text-slate-950"><button type="button" onClick={() => onSelect(item)} className="text-left hover:text-blue-700">{item.title}</button></td>
              <td className="px-3 py-3">{item.evidenceType}</td>
              <td className="px-3 py-3">
                <div className="flex flex-wrap gap-1">
                  {item.financialDomain && <Badge>{item.financialDomain}</Badge>}
                  {item.financialTechnique && <Badge>{techniqueLabel(item.financialTechnique)}</Badge>}
                </div>
              </td>
              <td className="px-3 py-3">{item.sourcePage || "-"}</td>
              <td className="px-3 py-3">{item.projectName || item.projectId || "-"}</td>
              <td className="px-3 py-3">{item.datasetIds?.join(", ") || "-"}</td>
              <td className="px-3 py-3"><StatusBadge status={item.status} /></td>
              <td className="px-3 py-3">{item.importance}</td>
              <td className="px-3 py-3">{formatDate(item.createdAt)}</td>
              <td className="max-w-sm px-3 py-3">{item.supportsSections?.join(", ") || "-"}</td>
              <td className="px-3 py-3">
                <div className="flex flex-wrap gap-1">
                  {item.sourceRoute && <Link className="rounded bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700" to={item.sourceRoute}>Open Source</Link>}
                  <button type="button" className="rounded bg-emerald-100 px-2 py-1 text-xs font-semibold text-emerald-700" onClick={() => onReady(item)}>Mark Ready</button>
                  <button type="button" className="rounded bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-700" onClick={() => onReview(item)}>Mark Needs Review</button>
                  <button type="button" className="rounded bg-blue-100 px-2 py-1 text-xs font-semibold text-blue-700" onClick={() => onAttach(item)}>Attach to Documentation</button>
                </div>
              </td>
            </tr>
          ))}
          {!items.length && (
            <tr><td colSpan={11} className="px-3 py-10 text-center text-slate-500">No evidence has been captured yet. Start by capturing current project evidence. ATLAS will scan datasets, SQL results, notebooks, charts, diagnostics, documentation, and governance notes.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceTimeline({ items, onSelect }: { items: EvidenceItem[]; onSelect: (item: EvidenceItem) => void }) {
  const groups = new Map<string, EvidenceItem[]>();
  items.forEach((item) => {
    const date = (item.createdAt ?? "").slice(0, 10) || "Undated";
    groups.set(date, [...(groups.get(date) ?? []), item]);
  });
  return (
    <div className="mt-4 space-y-4">
      {Array.from(groups.entries()).map(([date, rows]) => (
        <section key={date} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <h3 className="text-sm font-semibold text-slate-950">{date}</h3>
          <div className="mt-3 space-y-2">
            {rows.map((item) => (
              <button key={item.evidenceId} type="button" onClick={() => onSelect(item)} className="block w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-left hover:border-blue-200">
                <span className="block text-sm font-semibold text-slate-900">{item.title}</span>
                <span className="text-xs text-slate-500">{item.sourcePage} · {item.evidenceType}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

type EvidenceMapLayout = "flow" | "source" | "documentation" | "credit";
type EvidenceMapShow = "all" | "ready" | "needs_review" | "missing";
type EvidenceMapFocus = "project" | "dataset" | "documentation" | "credit_risk";
type EvidenceMapNode = EvidenceGraphPayload["nodes"][number] & { column: number; row: number; color: string };

function InteractiveEvidenceMapView({ graph, items, onCapture, focusMode, onFocusModeChange }: { graph: EvidenceGraphPayload; items: EvidenceItem[]; onCapture: () => void; focusMode: boolean; onFocusModeChange: (value: boolean) => void }) {
  const [layout, setLayout] = useState<EvidenceMapLayout>("flow");
  const [show, setShow] = useState<EvidenceMapShow>("all");
  const [focus, setFocus] = useState<EvidenceMapFocus>("project");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [domainFilter, setDomainFilter] = useState("");
  const [sectionFilter, setSectionFilter] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [showOnlySelectedConnections, setShowOnlySelectedConnections] = useState(false);
  const [groupDocumentationSections, setGroupDocumentationSections] = useState(true);

  const itemById = useMemo(() => new Map(items.map((item) => [item.evidenceId, item])), [items]);
  const map = useMemo(
    () => buildEvidenceMap(graph, items, { layout, show, focus, typeFilter, statusFilter, domainFilter, sectionFilter, groupDocumentationSections }),
    [graph, items, layout, show, focus, typeFilter, statusFilter, domainFilter, sectionFilter, groupDocumentationSections],
  );
  const selectedNode = map.nodes.find((node) => node.id === selectedNodeId) ?? map.nodes[0] ?? null;
  const connectedIds = useMemo(() => {
    const ids = new Set<string>();
    if (!selectedNode) return ids;
    map.edges.forEach((edge) => {
      const source = edge.source || edge.from || "";
      const target = edge.target || edge.to || "";
      if (source === selectedNode.id || target === selectedNode.id) {
        ids.add(source);
        ids.add(target);
      }
    });
    return ids;
  }, [map.edges, selectedNode]);

  if (!items.length && !graph.nodes.length) {
    return (
      <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
        <Network size={34} className="mx-auto text-slate-400" />
        <h3 className="mt-3 text-lg font-semibold text-slate-950">No evidence map yet.</h3>
        <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-600">Capture current project evidence to build the map.</p>
        <button type="button" onClick={onCapture} className="mt-4 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white">Capture Current Project Evidence</button>
      </div>
    );
  }

  const datasetOnly = items.length > 0 && items.every((item) => item.evidenceType === "dataset");

  return (
    <div className="mt-4 space-y-4">
      <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">
        <div className="font-semibold">Evidence Map</div>
        <p className="mt-1">This visual map shows how ATLAS evidence connects from project and datasets through analysis artifacts, model artifacts, documentation sections, governance review, and export packages.</p>
        {datasetOnly && <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">ATLAS found dataset evidence, but the map is incomplete. Save SQL queries, notebook outputs, charts, diagnostics, or documentation sections to build the full evidence chain.</p>}
      </div>
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-semibold text-slate-950">Graph Controls</div>
          <button type="button" onClick={() => onFocusModeChange(!focusMode)} className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white">
            {focusMode ? "Exit Map Focus" : "Expand Map"}
          </button>
        </div>
        <div className="grid gap-3 xl:grid-cols-4">
          <GraphSelect label="Layout" value={layout} options={[["flow", "Evidence Flow"], ["source", "Source View"], ["documentation", "Documentation View"], ["credit", "Credit Risk View"]]} onChange={(value) => setLayout(value as EvidenceMapLayout)} />
          <GraphSelect label="Show" value={show} options={[["all", "All"], ["ready", "Ready"], ["needs_review", "Needs Review"], ["missing", "Missing"]]} onChange={(value) => setShow(value as EvidenceMapShow)} />
          <GraphSelect label="Focus" value={focus} options={[["project", "Project"], ["dataset", "Dataset"], ["documentation", "Documentation"], ["credit_risk", "Credit Risk"]]} onChange={(value) => setFocus(value as EvidenceMapFocus)} />
          <div className="flex items-end gap-2">
            <button type="button" onClick={() => { setLayout("flow"); setShow("all"); setFocus("project"); setTypeFilter(""); setStatusFilter(""); setDomainFilter(""); setSectionFilter(""); setSelectedNodeId(""); }} className="h-10 flex-1 rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700 hover:bg-slate-50">Reset View</button>
            <button type="button" className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700">Zoom -</button>
            <button type="button" className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700">Zoom +</button>
          </div>
        </div>
        <div className="mt-3 grid gap-3 xl:grid-cols-4">
          <GraphSelect label="Node Type" value={typeFilter} options={nodeTypeOptions(map.allTypes)} onChange={setTypeFilter} />
          <GraphSelect label="Status" value={statusFilter} options={nodeTypeOptions(map.allStatuses)} onChange={setStatusFilter} />
          <GraphSelect label="Financial Domain" value={domainFilter} options={nodeTypeOptions(map.allDomains)} onChange={setDomainFilter} />
          <GraphSelect label="Documentation Section" value={sectionFilter} options={nodeTypeOptions(map.allSections)} onChange={setSectionFilter} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <TogglePill label="Show edge labels" checked={showEdgeLabels} onChange={setShowEdgeLabels} />
          <TogglePill label="Show only selected connections" checked={showOnlySelectedConnections} onChange={setShowOnlySelectedConnections} />
          <TogglePill label="Group documentation sections" checked={groupDocumentationSections} onChange={setGroupDocumentationSections} />
        </div>
      </section>
      <section className="space-y-4">
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-sm font-semibold text-slate-950">Interactive Graph Canvas</div>
              <div className="text-xs text-slate-500">{map.nodes.length} nodes · {map.edges.length} edges · {layoutLabel(layout)}</div>
            </div>
            <GraphLegend />
          </div>
          <div className="evidence-map-full-width-workspace overflow-auto rounded-xl border border-slate-100 bg-slate-50">
            <svg role="img" aria-label="Evidence Map graph canvas" viewBox={`0 0 ${map.width} ${map.height}`} className="min-h-[650px] w-full min-w-[1180px]">
              <defs>
                <marker id="evidence-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
                </marker>
              </defs>
              {map.columns.map((column) => (
                <g key={column.label}>
                  <rect x={column.x - 92} y={18} width={184} height={map.height - 36} rx={18} fill="#f8fafc" stroke="#e2e8f0" />
                  <text x={column.x} y={46} textAnchor="middle" className="fill-slate-500 text-[12px] font-semibold uppercase tracking-wide">{column.label}</text>
                </g>
              ))}
              {map.edges.filter((edge) => {
                if (!showOnlySelectedConnections || !selectedNode) return true;
                const sourceId = edge.source || edge.from || "";
                const targetId = edge.target || edge.to || "";
                return sourceId === selectedNode.id || targetId === selectedNode.id;
              }).map((edge) => {
                const source = map.nodeById.get(edge.source || edge.from || "");
                const target = map.nodeById.get(edge.target || edge.to || "");
                if (!source || !target) return null;
                const active = !selectedNode || source.id === selectedNode.id || target.id === selectedNode.id || connectedIds.has(source.id) || connectedIds.has(target.id);
                return (
                  <g key={edge.id || `${edge.source}-${edge.target}-${edge.type}`} opacity={active ? 1 : 0.18}>
                    <path d={`M ${source.x ?? 0} ${source.y ?? 0} C ${(source.x ?? 0) + 80} ${source.y ?? 0}, ${(target.x ?? 0) - 80} ${target.y ?? 0}, ${target.x ?? 0} ${target.y ?? 0}`} fill="none" stroke={active ? "#64748b" : "#cbd5e1"} strokeWidth={active ? 2 : 1.2} markerEnd="url(#evidence-arrow)" />
                    {showEdgeLabels && <text x={((source.x ?? 0) + (target.x ?? 0)) / 2} y={((source.y ?? 0) + (target.y ?? 0)) / 2 - 6} textAnchor="middle" className="fill-slate-500 text-[10px]">{edge.label || edge.type?.replace(/_/g, " ")}</text>}
                  </g>
                );
              })}
              {map.nodes.map((node) => {
                const active = !selectedNode || selectedNode.id === node.id || connectedIds.has(node.id);
                return (
                  <g key={node.id} role="button" tabIndex={0} onClick={() => setSelectedNodeId(node.id)} className="cursor-pointer" opacity={active ? 1 : 0.35}>
                    <rect x={(node.x ?? 0) - 76} y={(node.y ?? 0) - 25} width={152} height={50} rx={12} fill="white" stroke={selectedNode?.id === node.id ? "#2563eb" : node.color} strokeWidth={selectedNode?.id === node.id ? 3 : 2} />
                    <circle cx={(node.x ?? 0) - 58} cy={(node.y ?? 0)} r={8} fill={node.color} />
                    <text x={(node.x ?? 0) - 44} y={(node.y ?? 0) - 5} className="fill-slate-900 text-[11px] font-semibold">{truncate(node.label, 22)}</text>
                    <text x={(node.x ?? 0) - 44} y={(node.y ?? 0) + 11} className="fill-slate-500 text-[10px]">{node.type || node.kind}</text>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>
        <GraphNodeDetail node={selectedNode} item={selectedNode?.evidenceId ? itemById.get(selectedNode.evidenceId) : undefined} />
      </section>
    </div>
  );
}

function EvidenceGraphView({ graph, items }: { graph: EvidenceGraphPayload; items: EvidenceItem[] }) {
  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-3 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">
        <div className="font-semibold">Evidence Map · Foundation view</div>
        <p className="mt-1">
          This map shows how evidence connects across ATLAS. For example, a dataset can support a SQL query, which supports a notebook output, which supports a chart, diagnostic, or model documentation section.
        </p>
        <p className="mt-1 text-xs font-semibold text-blue-800">Interactive graph exploration will be added in a later phase.</p>
      </div>
      <GraphGroup title="Datasets" nodes={graph.nodes.filter((node) => node.kind === "dataset")} icon={<Database size={16} />} />
      <GraphGroup title="Evidence Items" nodes={items.map((item) => ({ id: item.evidenceId, label: item.title, kind: item.evidenceType, status: item.status }))} icon={<GitBranch size={16} />} />
      <GraphGroup title="Documentation Sections" nodes={graph.nodes.filter((node) => node.kind === "documentation_section")} icon={<FileText size={16} />} />
      <div className="lg:col-span-3 rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">
        Evidence Map uses simple grouped nodes in this foundation release. Edges captured: {graph.edges.length}. A full interactive graph renderer can be layered onto this same API later.
      </div>
    </div>
  );
}

function GraphGroup({ title, nodes, icon }: { title: string; nodes: Array<{ id: string; label: string; kind?: string; type?: string; status?: string }>; icon: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">{icon}{title}</div>
      <div className="mt-3 grid gap-2">
        {nodes.slice(0, 12).map((node) => (
          <div key={node.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
            <div className="font-semibold text-slate-900">{node.label}</div>
            <div className="mt-1 text-slate-500">{node.kind}{node.status ? ` · ${node.status}` : ""}</div>
          </div>
        ))}
        {!nodes.length && <div className="rounded-lg border border-dashed border-slate-300 p-3 text-xs text-slate-500">No nodes yet.</div>}
      </div>
    </section>
  );
}

function buildEvidenceMap(
  graph: EvidenceGraphPayload,
  items: EvidenceItem[],
  controls: { layout: EvidenceMapLayout; show: EvidenceMapShow; focus: EvidenceMapFocus; typeFilter: string; statusFilter: string; domainFilter: string; sectionFilter: string; groupDocumentationSections: boolean },
) {
  const itemById = new Map(items.map((item) => [item.evidenceId, item]));
  const itemNodes = items.map((item) => ({
    id: item.evidenceId,
    label: item.title,
    kind: item.evidenceType,
    type: item.financialDomain === "credit_risk" ? "Credit Risk Evidence" : evidenceTypeLabel(item.evidenceType),
    status: item.status,
    importance: item.importance,
    sourcePage: item.sourcePage,
    evidenceId: item.evidenceId,
    metadata: {
      datasetIds: item.datasetIds,
      supportsSections: item.supportsSections,
      financialDomain: item.financialDomain,
      financialTechnique: item.financialTechnique,
    },
  }));
  let rawNodes = uniqueNodes([...graph.nodes, ...itemNodes]);
  const hasDocumentationSections = rawNodes.some((node) => node.kind === "documentation_section");
  if (controls.groupDocumentationSections && hasDocumentationSections && !controls.sectionFilter) {
    rawNodes = [
      ...rawNodes.filter((node) => node.kind !== "documentation_section"),
      {
        id: "section:documentation-sections",
        label: "Documentation Sections",
        kind: "documentation_section",
        type: "Documentation Section",
        status: "ready",
        importance: "high",
        metadata: { section: "Grouped documentation sections" },
      },
    ];
  }
  const allTypes = Array.from(new Set(rawNodes.map((node) => node.type || node.kind || "Evidence").filter(Boolean))).sort();
  const allStatuses = Array.from(new Set(rawNodes.map((node) => node.status || "").filter(Boolean))).sort();
  const allDomains = Array.from(new Set(items.map((item) => item.financialDomain || "").filter(Boolean))).sort();
  const allSections = Array.from(new Set(items.flatMap((item) => item.supportsSections ?? []))).sort();

  let nodes = rawNodes.filter((node) => {
    const item = node.evidenceId ? itemById.get(node.evidenceId) : undefined;
    if (controls.show === "ready" && !["ready", "accepted"].includes(node.status || "")) return false;
    if (controls.show === "needs_review" && node.status !== "needs_review") return false;
    if (controls.show === "missing" && node.status !== "missing") return false;
    if (controls.typeFilter && (node.type || node.kind) !== controls.typeFilter) return false;
    if (controls.statusFilter && node.status !== controls.statusFilter) return false;
    if (controls.domainFilter && item?.financialDomain !== controls.domainFilter && node.metadata?.financialDomain !== controls.domainFilter) return false;
    if (controls.sectionFilter && node.kind !== "documentation_section" && !item?.supportsSections?.includes(controls.sectionFilter)) return false;
    return true;
  });
  if (controls.focus === "dataset") nodes = prioritizeNodes(nodes, (node) => node.kind === "dataset" || node.type === "Dataset");
  if (controls.focus === "documentation") nodes = prioritizeNodes(nodes, (node) => node.kind === "documentation_section" || node.type === "Documentation Section");
  if (controls.focus === "credit_risk") nodes = prioritizeNodes(nodes, (node) => node.type === "Credit Risk Evidence" || Boolean(node.metadata?.financialTechnique));

  const visibleIds = new Set(nodes.map((node) => node.id));
  const rawEdges = buildEdges(graph, items).map((edge) => {
    if (!controls.groupDocumentationSections || controls.sectionFilter) return edge;
    const source = (edge.source || edge.from || "").startsWith("section:") ? "section:documentation-sections" : edge.source || edge.from || "";
    const target = (edge.target || edge.to || "").startsWith("section:") ? "section:documentation-sections" : edge.target || edge.to || "";
    return { ...edge, source, target, from: source, to: target };
  });
  const seenEdges = new Set<string>();
  const edges = rawEdges.filter((edge) => {
    const key = `${edge.source || edge.from}|${edge.target || edge.to}|${edge.type}`;
    if (seenEdges.has(key)) return false;
    seenEdges.add(key);
    return visibleIds.has(edge.source || edge.from || "") && visibleIds.has(edge.target || edge.to || "");
  });
  const columnLabels = columnLabelsForLayout(controls.layout);
  const columns = columnLabels.map((label, index) => ({ label, x: 110 + index * 190 }));
  const positioned = nodes.map((node) => ({ ...node, column: columnForNode(node, controls.layout), color: colorForNode(node) }));
  const rowsByColumn = new Map<number, number>();
  const finalNodes: EvidenceMapNode[] = positioned.map((node) => {
    const row = rowsByColumn.get(node.column) ?? 0;
    rowsByColumn.set(node.column, row + 1);
    return { ...node, row, x: columns[node.column]?.x ?? 110, y: 94 + row * 82 };
  });
  const maxRows = Math.max(5, ...Array.from(rowsByColumn.values()));
  return {
    nodes: finalNodes,
    edges,
    nodeById: new Map(finalNodes.map((node) => [node.id, node])),
    columns,
    width: Math.max(1160, columns.length * 190 + 80),
    height: Math.max(560, 120 + maxRows * 82),
    allTypes,
    allStatuses,
    allDomains,
    allSections,
  };
}

function buildEdges(graph: EvidenceGraphPayload, items: EvidenceItem[]) {
  const edges = [...graph.edges];
  const projectNode = graph.nodes.find((node) => node.kind === "project" || node.type === "Project");
  const exportNode = graph.nodes.find((node) => node.kind === "export_package" || node.type === "Export Package");
  items.forEach((item) => {
    if (projectNode) edges.push({ id: `edge-project-${item.evidenceId}`, source: projectNode.id, target: item.evidenceId, label: "linked to project", type: "linked_to_project" });
    item.datasetIds?.forEach((datasetId) => edges.push({ id: `edge-${datasetId}-${item.evidenceId}`, source: `dataset:${datasetId}`, target: item.evidenceId, label: "generated from", type: "generated_from" }));
    item.supportsSections?.forEach((section) => {
      edges.push({ id: `edge-${item.evidenceId}-${section}`, source: item.evidenceId, target: `section:${section}`, label: "supports section", type: "supports_section" });
      if (exportNode) edges.push({ id: `edge-${section}-export`, source: `section:${section}`, target: exportNode.id, label: "documents", type: "documents" });
    });
  });
  const seen = new Set<string>();
  return edges.filter((edge) => {
    const key = `${edge.source || edge.from}|${edge.target || edge.to}|${edge.type}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function uniqueNodes(nodes: EvidenceGraphPayload["nodes"]) {
  const byId = new Map<string, EvidenceGraphPayload["nodes"][number]>();
  nodes.forEach((node) => {
    if (!byId.has(node.id)) byId.set(node.id, { ...node, type: node.type || node.kind || "Evidence" });
  });
  return Array.from(byId.values());
}

function prioritizeNodes(nodes: EvidenceGraphPayload["nodes"], predicate: (node: EvidenceGraphPayload["nodes"][number]) => boolean) {
  return [...nodes].sort((a, b) => Number(predicate(b)) - Number(predicate(a)));
}

function columnLabelsForLayout(layout: EvidenceMapLayout) {
  if (layout === "source") return ["Dataset Library", "SQL Data Studio", "Notebook / Analytics", "Chart Studio", "Diagnostics", "Governance"];
  if (layout === "documentation") return ["Evidence", "Data Sections", "Model Sections", "Governance Sections", "Appendices", "Export"];
  if (layout === "credit") return ["Project", "Scorecard", "Risk Evidence", "Fair Lending", "Monitoring", "Governance"];
  return ["Project", "Datasets", "Analysis Artifacts", "Model Artifacts", "Documentation Sections", "Governance / Export"];
}

function columnForNode(node: EvidenceGraphPayload["nodes"][number], layout: EvidenceMapLayout) {
  const type = node.type || node.kind || "";
  const kind = node.kind || "";
  const source = node.sourcePage || "";
  if (layout === "source") {
    if (source.includes("Dataset") || kind === "dataset") return 0;
    if (source.includes("SQL") || type.includes("SQL")) return 1;
    if (source.includes("Notebook") || source.includes("Analytics") || type === "Notebook" || type === "Analytics Insight") return 2;
    if (source.includes("Chart") || type === "Chart") return 3;
    if (source.includes("Diagnostics") || type === "Model Diagnostics") return 4;
    return 5;
  }
  if (layout === "documentation") {
    if (kind !== "documentation_section") return 0;
    if (/Data|Population|Target|Quality/i.test(node.label)) return 1;
    if (/Model|Performance|Training|Diagnostic|Interpretability/i.test(node.label)) return 2;
    if (/Fair Lending|Governance|Compliance|Monitoring/i.test(node.label)) return 3;
    if (/Appendix|Journal/i.test(node.label)) return 4;
    return 5;
  }
  if (layout === "credit") {
    if (kind === "project") return 0;
    if (/pdo|woe|iv|binning|scorecard/i.test(`${node.label} ${node.metadata?.financialTechnique ?? ""}`)) return 1;
    if (type === "Credit Risk Evidence") return 2;
    if (/fair|adverse|eco|fcra/i.test(`${node.label} ${node.metadata?.financialTechnique ?? ""}`)) return 3;
    if (/psi|monitor|stability/i.test(node.label)) return 4;
    return 5;
  }
  if (kind === "project" || type === "Project") return 0;
  if (kind === "dataset" || type === "Dataset") return 1;
  if (["SQL Query", "SQL Result", "Analytics Insight", "Chart", "Notebook"].includes(type)) return 2;
  if (["Model Training", "Evaluation", "Model Diagnostics", "Credit Risk Evidence"].includes(type)) return 3;
  if (kind === "documentation_section" || type === "Documentation Section") return 4;
  return 5;
}

function colorForNode(node: EvidenceGraphPayload["nodes"][number]) {
  if (node.status === "needs_review" || node.status === "missing") return "#ef4444";
  if (node.type === "Credit Risk Evidence" || node.metadata?.financialTechnique) return "#d97706";
  if (node.kind === "dataset" || node.type === "Dataset") return "#2563eb";
  if (node.type === "Notebook") return "#7c3aed";
  if (node.type === "Model Diagnostics" || node.type === "Evaluation") return "#059669";
  if (node.type === "Governance Warning") return "#f97316";
  if (node.kind === "documentation_section" || node.type === "Documentation Section") return "#64748b";
  if (node.type === "Project") return "#0f172a";
  return "#0891b2";
}

function GraphSelect({ label, value, options, onChange }: { label: string; value: string; options: Array<[string, string]>; onChange: (value: string) => void }) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold normal-case tracking-normal text-slate-900">
        {options.map(([optionValue, labelText]) => <option key={optionValue} value={optionValue}>{labelText}</option>)}
      </select>
    </label>
  );
}

function TogglePill({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className={`inline-flex cursor-pointer items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold ${checked ? "border-blue-200 bg-blue-50 text-blue-800" : "border-slate-200 bg-white text-slate-600"}`}>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="h-3.5 w-3.5 accent-blue-700" />
      {label}
    </label>
  );
}

function nodeTypeOptions(values: string[]): Array<[string, string]> {
  return [["", "All"], ...values.map((value) => [value, value.replace(/_/g, " ")] as [string, string])];
}

function GraphLegend() {
  const rows = [
    ["#2563eb", "Dataset"],
    ["#7c3aed", "Notebook"],
    ["#059669", "Diagnostic"],
    ["#f97316", "Governance"],
    ["#ef4444", "Needs Review"],
    ["#d97706", "Credit Risk Evidence"],
    ["#64748b", "Documentation Section"],
  ];
  return (
    <div className="flex flex-wrap gap-2 text-[11px] text-slate-600">
      {rows.map(([color, label]) => (
        <span key={label} className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
          {label}
        </span>
      ))}
    </div>
  );
}

function GraphNodeDetail({ node, item }: { node: EvidenceMapNode | null; item?: EvidenceItem }) {
  if (!node) return <section className="rounded-2xl border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-500">Select a node to inspect its evidence role.</section>;
  return (
    <section className="selected-node-detail-below-map rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected Node Detail</div>
          <h3 className="mt-2 text-lg font-semibold text-slate-950">{node.label}</h3>
          <div className="mt-2 flex flex-wrap gap-1">
            <Badge>{node.type || node.kind}</Badge>
            {node.status && <Badge>{node.status}</Badge>}
            {node.importance && <Badge>{node.importance}</Badge>}
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Source Page</div>
          <div className="mt-1 font-semibold text-slate-900">{node.sourcePage || item?.sourcePage || "ATLAS"}</div>
        </div>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <DetailBlock title="What this proves" text={item ? evidenceProof(item) : "This node anchors an evidence relationship in the ATLAS governance map."} />
        <DetailBlock title="Where it came from" text={item?.sourceRoute || node.sourcePage || "Model Evidence Center"} />
        <DetailBlock title="What it supports" text={(item?.supportsSections ?? (typeof node.metadata?.section === "string" ? [node.metadata.section] : [])).join("\n") || "No documentation section mapped."} />
        <DetailBlock title="Linked datasets" text={(item?.datasetIds ?? []).join("\n") || "No linked dataset."} />
        <DetailBlock title="Linked documentation sections" text={(item?.supportsSections ?? []).join("\n") || "No linked documentation section."} />
        <DetailBlock title="Financial-services context" text={`Domain: ${item?.financialDomain || node.metadata?.financialDomain || "-"}\nTechnique: ${item?.financialTechnique || node.metadata?.financialTechnique || "-"}`} />
        <DetailBlock title="Recommended action" text={item?.status === "ready" || item?.status === "accepted" ? "Attach to model documentation or include in the evidence pack." : "Review this node and resolve evidence gaps before validation use."} />
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Actions</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {item?.sourceRoute && <Link to={item.sourceRoute} className="atlas-secondary-button justify-center">Open source <ArrowUpRight size={14} /></Link>}
            {item && <Link to="/model-document-studio" className="atlas-secondary-button justify-center">Attach to documentation</Link>}
          </div>
        </div>
      </div>
    </section>
  );
}

function evidenceTypeLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function layoutLabel(layout: EvidenceMapLayout) {
  return layout === "source" ? "Source View" : layout === "documentation" ? "Documentation View" : layout === "credit" ? "Credit Risk View" : "Evidence Flow";
}

function truncate(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

function FinancialServicesView({ coverage }: { coverage: EvidenceCoverage | null }) {
  if (!coverage) return <p className="mt-4 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-500">Financial-services coverage is not available for this project yet.</p>;
  const creditRisk = coverage.financialServices?.creditRisk;
  return (
    <div className="mt-4 space-y-4">
      <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
        <div className="text-sm font-semibold text-blue-950">Financial Services Coverage</div>
        <p className="mt-1 text-sm leading-6 text-blue-900">
          Suggested domain: {coverage.financialServices?.suggestedDomain?.label ?? "Model Risk / Governance"}. Credit Risk is the first implemented evidence pack; Fraud / AML and Marketing / Profitability are registered placeholders.
        </p>
      </div>
      {creditRisk ? (
        <CoverageView coverage={{ ...coverage, categories: [], warnings: [] }} />
      ) : (
        <div className="rounded-xl border border-dashed border-slate-300 p-5 text-sm text-slate-500">No Credit Risk evidence checklist is available yet.</div>
      )}
    </div>
  );
}

function CoverageView({ coverage }: { coverage: EvidenceCoverage | null }) {
  if (!coverage) return <p className="mt-4 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-500">Coverage is not available for this project yet.</p>;
  const creditRisk = coverage.financialServices?.creditRisk;
  const grouped = new Map<string, NonNullable<typeof creditRisk>["items"]>();
  creditRisk?.items.forEach((item) => grouped.set(item.category, [...(grouped.get(item.category) ?? []), item]));
  return (
    <div className="mt-4 space-y-4">
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-950">Coverage categories</div>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {coverage.categories.map((item) => (
            <div key={item.category} className="rounded-lg border border-slate-200 bg-white p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-semibold capitalize text-slate-900">{item.category.replace(/_/g, " ")}</div>
                <StatusBadge status={item.status} />
              </div>
              <div className="mt-2 h-2 rounded-full bg-slate-100">
                <div className="h-2 rounded-full bg-blue-600" style={{ width: `${Math.min(100, item.count * 25)}%` }} />
              </div>
              <div className="mt-1 text-xs text-slate-500">{item.ready} ready of {item.count} item(s)</div>
            </div>
          ))}
        </div>
      </div>
      {coverage.warnings.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <div className="font-semibold">Governance warnings</div>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {coverage.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </div>
      )}
      <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-sm font-semibold text-blue-950">Financial Services Coverage</div>
            <p className="mt-1 text-xs leading-5 text-blue-900">Suggested domain: {coverage.financialServices?.suggestedDomain?.label ?? "Model Risk / Governance"} ({coverage.financialServices?.suggestedDomain?.confidence ?? 0}% confidence).</p>
          </div>
          <div className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-blue-900">
            Credit Risk Coverage: {creditRisk?.coverageScore ?? 0}%
          </div>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Metric label="Required credit-risk evidence" value={`${creditRisk?.readyRequired ?? 0}/${creditRisk?.totalRequired ?? 0}`} />
          <Metric label="Missing required" value={String(creditRisk?.missingRequired?.length ?? 0)} />
          <Metric label="Placeholders" value="Fraud/AML, Marketing" />
        </div>
      </div>
      {creditRisk && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="text-sm font-semibold text-slate-950">Credit Risk Evidence Coverage</div>
          <div className="mt-3 space-y-4">
            {Array.from(grouped.entries()).map(([category, rows]) => (
              <section key={category}>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{category}</div>
                <div className="grid gap-2 md:grid-cols-2">
                  {rows.map((item) => (
                    <div key={item.technique} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-semibold text-slate-900">{item.label}</div>
                        <StatusBadge status={item.status} />
                      </div>
                      <div className="mt-1 text-xs text-slate-500">{item.ready} ready of {item.count} evidence item(s) · {item.required ? "Required" : "Optional"}</div>
                      <div className="mt-2 text-xs leading-5 text-slate-600">Maps to: {item.documentationSections.join(", ") || "Appendix"}</div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FormSelect({ label, value, options, onChange }: { label: string; value?: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
      {label}
      <select value={value ?? ""} onChange={(event) => onChange(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case text-slate-900">
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function FormInput({ label, value, helper, onChange }: { label: string; value?: string; helper: string; onChange: (value: string) => void }) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
      {label}
      <input value={value ?? ""} onChange={(event) => onChange(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case text-slate-900" />
      <span className="text-[11px] font-normal normal-case leading-4 text-slate-500">{helper}</span>
    </label>
  );
}

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="mt-3 block text-xs font-semibold uppercase tracking-wide text-slate-500">
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm font-medium normal-case tracking-normal text-slate-900">
        <option value="">All</option>
        {options.map((option) => <option key={option} value={option}>{option.replace(/_/g, " ")}</option>)}
      </select>
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-semibold text-slate-600">{children}</span>;
}

function StatusBadge({ status }: { status: string }) {
  const cls = status === "ready" || status === "accepted" ? "bg-emerald-100 text-emerald-700" : status === "needs_review" || status === "missing" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600";
  return <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${cls}`}>{status.replace(/_/g, " ")}</span>;
}

function DetailBlock({ title, text }: { title: string; text: string }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-700">{text}</pre>
    </section>
  );
}

function evidenceProof(item: EvidenceItem) {
  if (item.evidenceType === "dataset") return "This proves which dataset version was used or registered for the project.";
  if (item.financialDomain === "credit_risk") return "This supports underwriting, explainability, regulatory review, or model governance evidence needs.";
  if (item.evidenceType === "sql_query" || item.evidenceType === "sql_result") return "This proves the query logic or result summary used to prepare analytical evidence.";
  if (item.evidenceType === "notebook") return "This proves reproducible notebook analysis and outputs used in the model review.";
  if (item.evidenceType === "model_diagnostics") return "This proves diagnostic review of model predictions, stability, residuals, or score behavior.";
  return "This evidence supports model documentation, validation, governance, or audit review.";
}

function formatDate(value?: string) {
  if (!value) return "-";
  return new Date(value).toLocaleDateString();
}
