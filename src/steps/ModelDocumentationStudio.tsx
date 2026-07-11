import { useEffect, useMemo, useState } from "react";
import type React from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  BookOpenCheck,
  CheckCircle2,
  ClipboardCheck,
  Database,
  Download,
  Eye,
  FileSpreadsheet,
  FileText,
  FolderOpen,
  LayoutList,
  Paperclip,
  Presentation,
  RefreshCw,
  Save,
  Sparkles,
} from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { DATASET_API_BASE } from "../lib/datasetLibrary";
import { listEvidence, type EvidenceItem } from "../lib/evidenceGraph";
import {
  attachDocumentationEvidence,
  createModelDocumentation,
  exportModelDocumentation,
  getDocumentationEvidenceLibrary,
  getDocumentationProjectContext,
  listDocumentationTemplates,
  runDocumentationQualityCheck,
  saveDocumentationSection,
  type DocumentationEvidence,
  type DocumentationProjectContext,
  type DocumentationSection,
  type DocumentationSectionStatus,
  type DocumentationTemplate,
  type ModelDocumentationDocument,
} from "../lib/modelDocumentation";
import { loadLocalProjects, projectProgress, type LocalProjectRecord } from "../lib/localProjects";
import { useWorkflowStore } from "../state/useWorkflowStore";

type ProjectOption = {
  projectId: string;
  projectName: string;
  projectType: string;
  taskType?: string;
  target?: string;
  source: "browser" | "backend";
  lastModified?: string;
  recoveryStatus?: string;
};

type EvidenceCoverage = {
  datasets: number;
  diagnostics: number;
  charts: number;
  analytics: number;
  notebooks: number;
  governance: number;
  generatedCode: number;
  missingRequired: number;
};

const AVAILABLE_TEMPLATE = "model_development_document";

export default function ModelDocumentationStudio() {
  const [params] = useSearchParams();
  const activeProjectId = useWorkflowStore((state) => state.projectId);
  const activeProjectName = useWorkflowStore((state) => state.projectName);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState(params.get("projectId") || activeProjectId);
  const [templates, setTemplates] = useState<DocumentationTemplate[]>([]);
  const [templateType, setTemplateType] = useState(AVAILABLE_TEMPLATE);
  const [context, setContext] = useState<DocumentationProjectContext | null>(null);
  const [document, setDocument] = useState<ModelDocumentationDocument | null>(null);
  const [selectedSectionId, setSelectedSectionId] = useState("executive_summary");
  const [evidenceItems, setEvidenceItems] = useState<DocumentationEvidence[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState("");
  const [outlineFilter, setOutlineFilter] = useState("all");
  const [rightTab, setRightTab] = useState<"evidence" | "quality" | "export" | "source">("evidence");
  const [evidenceFilter, setEvidenceFilter] = useState("recommended");
  const [evidenceSearch, setEvidenceSearch] = useState("");
  const [previewMode, setPreviewMode] = useState<"section" | "summary">("section");

  useEffect(() => {
    refreshProjects();
    listDocumentationTemplates().then(setTemplates).catch(() => setTemplates(defaultTemplates()));
  }, []);

  useEffect(() => {
    if (!projectId) return;
    loadProjectContext(projectId).catch(() => undefined);
  }, [projectId]);

  useEffect(() => {
    if (!document) return;
    const exists = document.sections.some((section) => section.sectionId === selectedSectionId);
    if (!exists) setSelectedSectionId(document.sections[0]?.sectionId || "executive_summary");
  }, [document?.documentId]);

  async function refreshProjects() {
    const browserProjects = loadLocalProjects().map(projectFromLocal);
    const backendProjects = await fetchBackendProjects().catch(() => []);
    const byId = new Map<string, ProjectOption>();
    [...backendProjects, ...browserProjects].forEach((project) => byId.set(project.projectId, project));
    if (activeProjectId && !byId.has(activeProjectId)) {
      byId.set(activeProjectId, {
        projectId: activeProjectId,
        projectName: activeProjectName || "Current ATLAS Project",
        projectType: useWorkflowStore.getState().projectType,
        taskType: "",
        source: "browser",
      });
    }
    const next = Array.from(byId.values()).sort((a, b) => String(b.lastModified || "").localeCompare(String(a.lastModified || "")));
    setProjects(next);
    if (!projectId && next[0]) setProjectId(next[0].projectId);
  }

  async function loadProjectContext(nextProjectId: string) {
    setLoading(true);
    setError("");
    try {
      const payload = await getDocumentationProjectContext(nextProjectId);
      setContext(payload.context);
      const existingDocumentId = params.get("documentId") || String(payload.documents?.[0]?.documentId || "");
      if (existingDocumentId) {
        const loaded = await fetchDocument(existingDocumentId);
        setDocument(loaded);
        setEvidenceItems(await getDocumentationEvidenceLibrary(loaded.documentId, nextProjectId));
      } else {
        setDocument(null);
        setEvidenceItems([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not load documentation context.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshEvidence(nextDocument = document) {
    if (!nextDocument || !projectId) return;
    const items = await getDocumentationEvidenceLibrary(nextDocument.documentId, projectId);
    setEvidenceItems(items);
    const checked = await runDocumentationQualityCheck(nextDocument.documentId);
    setDocument(checked);
  }

  async function handleCreateOrRefreshDocument() {
    if (!projectId) return;
    setLoading(true);
    setError("");
    try {
      if (!document) {
        const created = await createModelDocumentation(projectId, templateType);
        setDocument(created);
        setSelectedSectionId(created.sections[0]?.sectionId || "executive_summary");
        const items = await getDocumentationEvidenceLibrary(created.documentId, projectId);
        setEvidenceItems(items);
        const ready = created.sections.filter((section) => normalizeSectionStatus(section) === "ready_for_review").length;
        const needsEvidence = created.sections.filter((section) => normalizeSectionStatus(section) === "needs_evidence").length;
        setMessage(`Documentation workspace created. ${created.sections.length} sections drafted. ${items.length} evidence items found. ${ready} sections ready for review. ${needsEvidence} sections need evidence.`);
      } else {
        await refreshEvidence(document);
        setMessage("Documentation workspace refreshed. User narratives were preserved.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not create or refresh this documentation workspace.");
    } finally {
      setLoading(false);
    }
  }

  async function handleEvidencePull(label: string) {
    if (!document) {
      setMessage("Create a documentation workspace before pulling evidence.");
      return;
    }
    try {
      await refreshEvidence(document);
      setMessage(`${label} refreshed the Evidence Library and document quality state.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `ATLAS could not run ${label}.`);
    }
  }

  async function handleImportFromEvidenceGraph() {
    if (!document) {
      setMessage("Create a documentation workspace before importing Model Evidence Center items.");
      return;
    }
    try {
      const graphItems = await listEvidence({ projectId });
      const converted = graphItems.map(evidenceGraphItemToDocumentationEvidence);
      setEvidenceItems((current) => dedupeDocumentationEvidence([...converted, ...current]));
      setEvidenceFilter("evidence_graph");
      setRightTab("evidence");
      setMessage(`Imported ${converted.length} Model Evidence Center item(s) into the Evidence Library.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not import from Model Evidence Center.");
    }
  }

  async function handleSaveSection(section: DocumentationSection) {
    if (!document) return;
    setError("");
    try {
      const saved = await saveDocumentationSection(document.documentId, section);
      setDocument(saved);
      setMessage(`${section.title} saved.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not save this documentation section.");
    }
  }

  async function handleAttachEvidence(evidence: DocumentationEvidence) {
    if (!document || !selectedSection) return;
    setError("");
    try {
      const saved = await attachDocumentationEvidence(document.documentId, selectedSection.sectionId, evidence);
      setDocument(saved);
      setMessage(`Attached ${evidence.title} to ${selectedSection.title}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not attach this evidence item.");
    }
  }

  async function handleAttachRecommendedEvidence() {
    if (!document || !selectedSection) return;
    const recommended = recommendedEvidenceForSection(selectedSection, evidenceItems);
    if (!recommended.length) {
      setMessage(`No matching recommended evidence is currently available for ${selectedSection.title}.`);
      return;
    }
    let latest = document;
    try {
      for (const item of recommended.slice(0, 5)) {
        latest = await attachDocumentationEvidence(latest.documentId, selectedSection.sectionId, item);
      }
      setDocument(latest);
      setMessage(`Attached ${Math.min(5, recommended.length)} recommended evidence item(s) to ${selectedSection.title}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not attach recommended evidence.");
    }
  }

  async function handleAutoAttachAvailableEvidence() {
    if (!document || !projectId) return;
    setError("");
    try {
      const available = evidenceItems.length ? evidenceItems : await getDocumentationEvidenceLibrary(document.documentId, projectId);
      if (!evidenceItems.length) setEvidenceItems(available);
      let latest = document;
      let attachedCount = 0;
      for (const section of latest.sections) {
        const current = latest.sections.find((item) => item.sectionId === section.sectionId) ?? section;
        const existing = new Set(current.attachedEvidence.map((item) => evidenceKey(item)));
        const matches = recommendedEvidenceForSection(current, available).filter((item) => !existing.has(evidenceKey(item))).slice(0, 6);
        for (const item of matches) {
          latest = await attachDocumentationEvidence(latest.documentId, current.sectionId, item);
          attachedCount += 1;
        }
      }
      const checked = await runDocumentationQualityCheck(latest.documentId);
      setDocument(checked);
      setMessage(`Auto-attached ${attachedCount} available evidence item(s). User narratives and manual attachments were preserved.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not auto-attach available evidence.");
    }
  }

  async function handleQualityCheck() {
    if (!document) return;
    setError("");
    try {
      const checked = await runDocumentationQualityCheck(document.documentId);
      setDocument(checked);
      setMessage("Document quality check completed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not run the documentation quality check.");
    }
  }

  async function handleExport(format: "word" | "powerpoint" | "evidence-excel") {
    if (!document) return;
    const missing = document.quality?.missingEvidenceCount ?? 0;
    if (missing > 0 && !window.confirm(`This document has ${missing} required section(s) with missing evidence. Export anyway?`)) return;
    setExporting(format);
    setError("");
    try {
      const exported = await exportModelDocumentation(document.documentId, format);
      downloadBlob(exported.blob, exported.filename);
      setMessage(`${exportLabel(format)} export created.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not create this documentation export.");
    } finally {
      setExporting("");
    }
  }

  const selectedProject = projects.find((project) => project.projectId === projectId);
  const selectedTemplate = templates.find((template) => template.templateType === templateType);
  const selectedSection = useMemo(
    () => document?.sections.find((section) => section.sectionId === selectedSectionId) ?? document?.sections[0],
    [document, selectedSectionId]
  );
  const quality = document?.quality;
  const coverage = useMemo(() => evidenceCoverage(context, document, evidenceItems), [context, document, evidenceItems]);
  const readiness = readinessStatus(quality);
  const selectedRecommendations = selectedSection ? evidenceRecommendations(selectedSection.sectionId) : [];
  const recommendedMatches = selectedSection ? recommendedEvidenceForSection(selectedSection, evidenceItems) : [];
  const visibleSections = useMemo(
    () => (document?.sections ?? []).filter((section) => matchesOutlineFilter(section, outlineFilter)),
    [document, outlineFilter]
  );
  const visibleEvidence = useMemo(
    () => filterEvidenceItems(evidenceItems, selectedSection, evidenceFilter, evidenceSearch),
    [evidenceItems, selectedSection, evidenceFilter, evidenceSearch]
  );

  return (
    <div className="atlas-page-shell atlas-theme-documentation">
      <section className="atlas-studio-hero">
        <div className="atlas-studio-hero__band">
        <BrandLogo size="md" variant="dark" showSubtitle className="mb-3" />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px] xl:items-start">
          <div>
            <div className="flex items-center gap-2">
              <BookOpenCheck size={22} className="text-violet-200" />
              <h1 className="text-2xl font-semibold text-white">Model Documentation Studio</h1>
            </div>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-violet-50/90">
              Assemble a governed, editable, export-ready Model Development Document from ATLAS projects, datasets,
              diagnostics, charts, notebook outputs, analytics insights, generated code, and governance notes.
            </p>
          </div>
          <div className="rounded-xl border border-violet-200 bg-white p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-violet-700">Primary action</div>
            <button
              type="button"
              onClick={handleCreateOrRefreshDocument}
              disabled={!projectId || selectedTemplate?.status !== "available" || loading}
              className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-3 text-sm font-semibold text-white shadow-sm disabled:bg-slate-400"
            >
              <Sparkles size={16} />
              {document ? "Refresh Workspace Evidence" : "Create Documentation Workspace"}
            </button>
            <p className="mt-2 text-xs leading-5 text-violet-900">
              Creates an editable Model Development Document draft from the current project, datasets, diagnostics, charts, and governance artifacts.
            </p>
          </div>
        </div>
        </div>

        <div className="grid gap-3 p-5 lg:grid-cols-[1fr_1fr_1fr]">
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Project
            <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              {projects.map((project) => (
                <option key={project.projectId} value={project.projectId}>{project.projectName}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Template
            <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={templateType} onChange={(event) => setTemplateType(event.target.value)}>
              {templates.map((template) => <option key={template.templateType} value={template.templateType} disabled={template.status !== "available"}>{template.label}{template.status !== "available" ? " - Coming soon" : ""}</option>)}
            </select>
          </label>
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Documentation Readiness</div>
            <div className="mt-1 text-sm font-semibold text-slate-950">{document ? `${document.projectName} / ${readiness.label}` : "Workspace not created"}</div>
          </div>
        </div>

        {message && <div className="mx-5 mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">{message}</div>}
        {error && <div className="mx-5 mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900">{error}</div>}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid gap-3 xl:grid-cols-[1fr_1fr]">
          <ReadinessPanel quality={quality} readiness={readiness} />
          <EvidenceCoveragePanel coverage={coverage} />
        </div>
      </section>

      <section className="grid min-h-[780px] gap-4 xl:grid-cols-[320px_minmax(0,1fr)_380px]">
        <aside className="min-h-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-slate-900">
            <LayoutList size={17} />
            <h2 className="text-sm font-semibold">Document Outline</h2>
          </div>
          <p className="mt-2 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
            Needs Evidence means ATLAS could not find or attach required supporting artifacts for this section. It does not mean you must manually write the section from scratch.
          </p>
          <div className="mt-3 flex flex-wrap gap-1">
            {["all", "needs_evidence", "needs_review", "complete", "not_applicable"].map((filter) => (
              <button
                key={filter}
                type="button"
                onClick={() => setOutlineFilter(filter)}
                className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${outlineFilter === filter ? "border-blue-300 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-600"}`}
              >
                {filter === "all" ? "All" : humanize(filter)}
              </button>
            ))}
          </div>
          <div className="mt-4 max-h-[670px] overflow-auto pr-1">
            {document ? visibleSections.map((section) => (
              <OutlineSectionButton
                key={section.sectionId}
                section={section}
                selected={selectedSectionId === section.sectionId}
                evidenceItems={evidenceItems}
                onSelect={() => {
                  setSelectedSectionId(section.sectionId);
                  setEvidenceFilter("recommended");
                  setRightTab("evidence");
                }}
              />
            )) : (
              <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">Create a workspace to load the document outline.</div>
            )}
          </div>
        </aside>

        <main className="min-w-0 space-y-4">
          {!document ? (
            <section className="rounded-xl border border-dashed border-slate-300 bg-white/90 p-10 text-center shadow-sm">
              <BookOpenCheck size={42} className="mx-auto text-blue-700" />
              <h2 className="mt-4 text-lg font-semibold text-slate-950">Create a governed documentation workspace</h2>
              <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">
                Use the primary button at the top to create the workspace. ATLAS will generate section drafts,
                recommended evidence, a document readiness score, and export-ready evidence packages.
              </p>
            </section>
          ) : selectedSection ? (
            <>
              <SectionRecommendations
                section={selectedSection}
                recommendations={selectedRecommendations}
                matches={recommendedMatches}
                onAttachRecommended={handleAttachRecommendedEvidence}
              />
              <SectionEditor
                section={selectedSection}
                onChange={(next) => setDocument(replaceSection(document, next))}
                onSave={handleSaveSection}
              />
              <DocumentPreview document={document} selectedSection={selectedSection} mode={previewMode} onModeChange={setPreviewMode} />
            </>
          ) : null}
        </main>

        <aside className="min-h-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <RightPaneTabs active={rightTab} onChange={setRightTab} />
          <div className="mt-4 max-h-[710px] overflow-auto pr-1">
            {rightTab === "evidence" && (
              <EvidenceLibrary
                items={visibleEvidence}
                allItems={evidenceItems}
                selectedSection={selectedSection}
                filter={evidenceFilter}
                search={evidenceSearch}
                onFilter={setEvidenceFilter}
                onSearch={setEvidenceSearch}
                onAttach={handleAttachEvidence}
              />
            )}
            {rightTab === "quality" && (
              <div className="space-y-4">
                <DocumentQuality quality={quality} onRun={handleQualityCheck} />
                <EvidenceActions onPull={handleEvidencePull} onAutoAttach={handleAutoAttachAvailableEvidence} onImportGraph={handleImportFromEvidenceGraph} disabled={!document} />
              </div>
            )}
            {rightTab === "export" && document && (
              <ExportPackage document={document} exporting={exporting} onExport={handleExport} />
            )}
            {rightTab === "source" && <OpenSourcePages />}
          </div>
        </aside>
      </section>
    </div>
  );
}

function OutlineSectionButton({
  section,
  selected,
  evidenceItems,
  onSelect,
}: {
  section: DocumentationSection;
  selected: boolean;
  evidenceItems: DocumentationEvidence[];
  onSelect: () => void;
}) {
  const readiness = sectionEvidenceReadiness(section, evidenceItems);
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`mb-2 grid w-full gap-2 rounded-lg border px-3 py-2 text-left text-sm transition ${
        selected ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-slate-950">{section.order}. {section.title}</span>
        <StatusBadge status={section.status} />
      </div>
      <div className="grid grid-cols-3 gap-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        <span>{readiness.attached} attached</span>
        <span>{readiness.available} available</span>
        <span>{readiness.missingCritical} critical gap</span>
      </div>
      <div className="text-xs leading-5 text-slate-500">{sectionNextAction(section, readiness)}</div>
    </button>
  );
}

function WorkflowBanner() {
  const steps = ["Select project", "Create workspace", "Review auto-drafted sections", "Attach evidence", "Run quality check", "Export Word / PowerPoint / Excel evidence pack"];
  return (
    <section className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Documentation workflow</div>
      <div className="mt-3 grid gap-2 md:grid-cols-3 xl:grid-cols-6">
        {steps.map((step, index) => (
          <div key={step} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <div className="grid h-7 w-7 place-items-center rounded-full bg-blue-600 text-xs font-semibold text-white">{index + 1}</div>
            <div className="mt-2 text-xs font-semibold leading-5 text-slate-800">{step}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ReadinessPanel({ quality, readiness }: { quality?: ModelDocumentationDocument["quality"]; readiness: { label: string; tone: string } }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Document Readiness</div>
          <div className="mt-1 text-3xl font-semibold text-slate-950">{quality ? `${quality.completionPct}%` : "0%"}</div>
          <div className={`mt-1 inline-flex rounded-full px-2 py-1 text-xs font-semibold ${readiness.tone}`}>{readiness.label}</div>
        </div>
        <BookOpenCheck size={28} className="text-blue-700" />
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        <Metric label="Required complete" value={quality ? `${quality.requiredSectionsComplete}/${quality.requiredSectionsTotal}` : "-"} />
        <Metric label="Missing evidence" value={quality ? String(quality.missingEvidenceCount) : "-"} />
        <Metric label="Needs review" value={quality ? String(quality.sectionsNeedingReview) : "-"} />
        <Metric label="Export readiness" value={quality?.exportReady ? "Export ready" : "Not ready"} />
        <Metric label="Governance readiness" value={quality ? `${Math.max(0, 100 - quality.governanceWarningsCount * 10)}%` : "-"} />
        <Metric label="Status" value={readiness.label} />
      </div>
    </section>
  );
}

function EvidenceCoveragePanel({ coverage }: { coverage: EvidenceCoverage }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <Database size={18} className="text-blue-700" />
        <h2 className="text-base font-semibold text-slate-950">Evidence Coverage Summary</h2>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        <Metric label="Datasets attached" value={String(coverage.datasets)} />
        <Metric label="Diagnostics attached" value={String(coverage.diagnostics)} />
        <Metric label="Charts attached" value={String(coverage.charts)} />
        <Metric label="Analytics insights" value={String(coverage.analytics)} />
        <Metric label="Notebook outputs" value={String(coverage.notebooks)} />
        <Metric label="Governance notes" value={String(coverage.governance)} />
        <Metric label="Generated code artifacts" value={String(coverage.generatedCode)} />
      </div>
      <div className={`mt-3 rounded-lg border px-3 py-2 text-sm ${coverage.missingRequired ? "border-amber-200 bg-amber-50 text-amber-950" : "border-emerald-200 bg-emerald-50 text-emerald-950"}`}>
        Missing required evidence: <strong>{coverage.missingRequired}</strong>
      </div>
    </section>
  );
}

function SectionRecommendations({ section, recommendations, matches, onAttachRecommended }: { section: DocumentationSection; recommendations: string[]; matches: DocumentationEvidence[]; onAttachRecommended: () => void }) {
  return (
    <section className="rounded-xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Section-level evidence recommendations</div>
          <h2 className="mt-1 text-lg font-semibold text-blue-950">{section.title}</h2>
          <p className="mt-1 text-sm leading-6 text-blue-900">ATLAS recommends the evidence below before this section is marked complete.</p>
        </div>
        <button type="button" onClick={onAttachRecommended} className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white">
          <Paperclip size={15} />
          Attach Recommended Evidence
        </button>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {recommendations.map((item) => <div key={item} className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-blue-950">{item}</div>)}
      </div>
      <div className="mt-3 text-xs leading-5 text-blue-900">
        Preview Evidence: {matches.length ? `${matches.length} matching item(s) currently available.` : "No matching evidence available yet. Pull latest evidence or open source pages."}
      </div>
    </section>
  );
}

function SectionEditor({ section, onChange, onSave }: { section: DocumentationSection; onChange: (section: DocumentationSection) => void; onSave: (section: DocumentationSection) => void }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Section Editor</div>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">{section.order}. {section.title}</h2>
          <p className="mt-1 text-sm text-slate-500">{section.required ? "Required section" : "Optional section"} / export {section.includeInExport ? "included" : "excluded"}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={normalizeSectionStatus(section)} onChange={(event) => onChange({ ...section, status: event.target.value as DocumentationSectionStatus })}>
            <option value="draft">Draft</option>
            <option value="needs_evidence">Needs Evidence</option>
            <option value="ready_for_review">Ready for Review</option>
            <option value="complete">Complete</option>
            <option value="not_applicable">Not Applicable</option>
          </select>
          <button type="button" className="atlas-secondary-button" onClick={() => onChange({ ...section, userNarrative: improvedDraft(section) })}>
            <Sparkles size={15} />
            Use Auto Draft
          </button>
          <button type="button" className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={() => onSave(section)}>
            <Save size={15} />
            Save Section
          </button>
        </div>
      </div>
      <div className="mt-4 grid gap-4">
        <div className="rounded-xl border border-blue-100 bg-blue-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-800">Auto-generated draft</div>
          <p className="mt-2 whitespace-pre-line text-sm leading-6 text-blue-950">{improvedDraft(section)}</p>
        </div>
        {section.missingEvidenceWarning && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-950">{section.missingEvidenceWarning}</div>
        )}
        <label className="grid gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Editable user narrative</span>
          <textarea
            value={section.userNarrative}
            onChange={(event) => onChange({ ...section, userNarrative: event.target.value })}
            className="min-h-[240px] rounded-xl border border-slate-300 p-4 text-sm leading-6 text-slate-900 shadow-inner"
            placeholder="Edit audit-ready narrative for this section..."
          />
        </label>
        <label className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <input type="checkbox" checked={section.includeInExport} onChange={(event) => onChange({ ...section, includeInExport: event.target.checked })} />
          Include this section in exports
        </label>
      </div>
    </section>
  );
}

function DocumentPreview({
  document,
  selectedSection,
  mode,
  onModeChange,
}: {
  document: ModelDocumentationDocument;
  selectedSection: DocumentationSection;
  mode: "section" | "summary";
  onModeChange: (mode: "section" | "summary") => void;
}) {
  const included = document.sections.filter((section) => section.includeInExport);
  const complete = document.sections.filter((section) => normalizeSectionStatus(section) === "complete").length;
  const draft = document.sections.filter((section) => normalizeSectionStatus(section) === "draft").length;
  const needsEvidence = document.sections.filter((section) => normalizeSectionStatus(section) === "needs_evidence").length;
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <Eye size={18} className="text-blue-700" />
          <h2 className="text-base font-semibold text-slate-950">Document Preview</h2>
        </div>
        <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1">
          <button type="button" onClick={() => onModeChange("section")} className={`rounded-md px-3 py-1 text-xs font-semibold ${mode === "section" ? "bg-white text-blue-700 shadow-sm" : "text-slate-600"}`}>Selected Section</button>
          <button type="button" onClick={() => onModeChange("summary")} className={`rounded-md px-3 py-1 text-xs font-semibold ${mode === "summary" ? "bg-white text-blue-700 shadow-sm" : "text-slate-600"}`}>Full Document Summary</button>
        </div>
      </div>
      {mode === "section" ? (
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected section preview</div>
          <h3 className="mt-2 text-lg font-semibold text-slate-950">{selectedSection.order}. {selectedSection.title}</h3>
          <p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-700">{selectedSection.userNarrative || improvedDraft(selectedSection)}</p>
          <div className="mt-3 text-xs font-semibold text-slate-500">Attached evidence summaries: {selectedSection.attachedEvidence.length}</div>
          <div className="mt-2 grid gap-2">
            {selectedSection.attachedEvidence.slice(0, 4).map((item, index) => (
              <div key={`${item.source}-${item.title}-${index}`} className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">{item.title} / {item.source}</div>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <Metric label="Completed sections" value={String(complete)} />
          <Metric label="Draft sections" value={String(draft)} />
          <Metric label="Needs evidence sections" value={String(needsEvidence)} />
          <Metric label="Main evidence included" value={String(included.reduce((sum, section) => sum + section.attachedEvidence.length, 0))} />
          <div className="md:col-span-2 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-700">
            Full document summary: {included.length} included section(s), {document.quality?.missingEvidenceCount ?? 0} missing required evidence item(s), export readiness is {document.quality?.exportReady ? "ready" : "not ready"}.
          </div>
        </div>
      )}
    </section>
  );
}

function DocumentQuality({ quality, onRun }: { quality?: ModelDocumentationDocument["quality"]; onRun: () => void }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <ClipboardCheck size={18} className="text-blue-700" />
            <h2 className="text-base font-semibold text-slate-950">Document Quality</h2>
          </div>
          <p className="mt-1 text-sm text-slate-500">Checks export readiness, missing evidence, required sections, and governance coverage.</p>
        </div>
        <button type="button" onClick={onRun} className="atlas-secondary-button">
          <RefreshCw size={15} />
          Run Quality Check
        </button>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {(quality?.checks ?? []).map((check) => (
          <div key={check.id} className={`rounded-lg border px-3 py-2 text-sm ${check.status === "pass" ? "border-emerald-200 bg-emerald-50 text-emerald-950" : "border-amber-200 bg-amber-50 text-amber-950"}`}>
            <div className="flex items-center gap-2 font-semibold">
              {check.status === "pass" ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
              {check.label}
            </div>
            <p className="mt-1 text-xs leading-5">{check.detail}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function EvidenceActions({ onPull, onAutoAttach, onImportGraph, disabled }: { onPull: (label: string) => void; onAutoAttach: () => void; onImportGraph: () => void; disabled: boolean }) {
  const actions = [
    "Pull Latest Project Evidence",
    "Pull Dataset Evidence",
    "Pull Model Diagnostics Evidence",
    "Pull Chart Studio Evidence",
    "Pull Notebook Studio Evidence",
    "Pull Analytics Workbench Evidence",
    "Pull Governance Notes",
  ];
  return (
    <Panel title="Refresh Evidence" icon={<RefreshCw size={17} />}>
      <div className="grid gap-2">
        <button type="button" disabled={disabled} onClick={onAutoAttach} className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
          <Paperclip size={14} />
          Auto-Attach Available Evidence
        </button>
        <button type="button" disabled={disabled} onClick={onImportGraph} className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
          <Paperclip size={14} />
          Import from Model Evidence Center
        </button>
        <Link to="/model-evidence-center" className="atlas-secondary-button justify-start">
          <FolderOpen size={14} />
          Open Model Evidence Center
        </Link>
        {actions.map((action) => (
          <button key={action} type="button" disabled={disabled} onClick={() => onPull(action)} className="atlas-secondary-button justify-start disabled:opacity-50">
            <RefreshCw size={14} />
            {action}
          </button>
        ))}
      </div>
    </Panel>
  );
}

function EvidenceLibrary({
  items,
  allItems,
  selectedSection,
  filter,
  search,
  onFilter,
  onSearch,
  onAttach,
}: {
  items: DocumentationEvidence[];
  allItems: DocumentationEvidence[];
  selectedSection?: DocumentationSection;
  filter: string;
  search: string;
  onFilter: (filter: string) => void;
  onSearch: (search: string) => void;
  onAttach: (item: DocumentationEvidence) => void;
}) {
  const filters = ["recommended", "all", "evidence_graph", "credit_risk", "datasets", "diagnostics", "charts", "notebooks", "analytics", "governance", "code"];
  return (
    <Panel title="Evidence Library" icon={<Paperclip size={17} />}>
      <div className="grid gap-2">
        <input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder="Search evidence by title, source, dataset, metric, or section"
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap gap-1">
          {filters.map((item) => (
            <button key={item} type="button" onClick={() => onFilter(item)} className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${filter === item ? "border-blue-300 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-600"}`}>
              {item === "recommended" ? "Recommended for this section" : item === "evidence_graph" ? "Model Evidence Center" : item === "credit_risk" ? "Credit Risk Evidence" : humanize(item)}
            </button>
          ))}
        </div>
        <div className="text-xs text-slate-500">{items.length} of {allItems.length} evidence item(s) shown for {selectedSection?.title ?? "the selected section"}.</div>
      </div>
      <div className="mt-3 max-h-[520px] overflow-auto pr-1">
        {items.length ? items.map((item, index) => (
          <div key={`${item.source}-${item.title}-${index}`} className="mb-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{item.type} / {item.source}</div>
                <div className="mt-1 text-sm font-semibold text-slate-950">{item.title || "Untitled evidence"}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{evidenceSummary(item)}</div>
                {item.createdAt && <div className="mt-1 text-[11px] text-slate-400">Created: {item.createdAt}</div>}
              </div>
              <button type="button" onClick={() => onAttach(item)} className="rounded-md bg-slate-950 px-2 py-1 text-[11px] font-semibold text-white">
                Attach to Current Section
              </button>
            </div>
            <details className="mt-2 rounded-lg border border-slate-200 bg-white p-2 text-[11px] text-slate-600">
              <summary className="cursor-pointer font-semibold">Advanced details</summary>
              <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap">{previewEvidence(item)}</pre>
            </details>
          </div>
        )) : (
          <div className="rounded-lg border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-500">
            Create a workspace, then use Evidence Actions to load Dataset Library, Analytics Workbench, Chart Studio, Notebook Studio, Model Diagnostics, generated code, and governance notes.
          </div>
        )}
      </div>
    </Panel>
  );
}

function ExportPackage({ document, exporting, onExport }: { document: ModelDocumentationDocument; exporting: string; onExport: (format: "word" | "powerpoint" | "evidence-excel") => void }) {
  const warning = document.quality?.missingEvidenceCount ? `${document.quality.missingEvidenceCount} section(s) have missing evidence.` : "Ready for governed export.";
  return (
    <Panel title="Export Package" icon={<Download size={17} />}>
      <div className={`mb-3 rounded-lg border px-3 py-2 text-xs leading-5 ${document.quality?.exportReady ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-950"}`}>
        Export readiness warning: {warning}
      </div>
      <ExportButton label="Export to Word" status={warning} icon={<FileText size={15} />} loading={exporting === "word"} onClick={() => onExport("word")} />
      <ExportButton label="Export to PowerPoint" status={warning} icon={<Presentation size={15} />} loading={exporting === "powerpoint"} onClick={() => onExport("powerpoint")} />
      <ExportButton label="Export Evidence Pack to Excel" status={warning} icon={<FileSpreadsheet size={15} />} loading={exporting === "evidence-excel"} onClick={() => onExport("evidence-excel")} />
    </Panel>
  );
}

function OpenSourcePages() {
  return (
    <Panel title="Open Source Pages" icon={<Sparkles size={17} />}>
      <Link className="atlas-secondary-button" to="/project-overview">Project Overview</Link>
      <Link className="atlas-secondary-button" to="/model-diagnostics">Model Diagnostics</Link>
      <Link className="atlas-secondary-button" to="/chart-studio">Chart Studio</Link>
      <Link className="atlas-secondary-button" to="/notebook-studio">Notebook Studio</Link>
      <Link className="atlas-secondary-button" to="/analytics">Analytics Workbench</Link>
      <Link className="atlas-secondary-button" to="/step11">Documentation Review Checkpoint</Link>
    </Panel>
  );
}

function RightPaneTabs({ active, onChange }: { active: "evidence" | "quality" | "export" | "source"; onChange: (tab: "evidence" | "quality" | "export" | "source") => void }) {
  const tabs: Array<{ id: "evidence" | "quality" | "export" | "source"; label: string }> = [
    { id: "evidence", label: "Evidence" },
    { id: "quality", label: "Quality" },
    { id: "export", label: "Export" },
    { id: "source", label: "Source Pages" },
  ];
  return (
    <div className="grid grid-cols-2 gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={`rounded-lg px-3 py-2 text-xs font-semibold ${active === tab.id ? "bg-white text-blue-700 shadow-sm" : "text-slate-600 hover:bg-white/70"}`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

async function fetchBackendProjects(): Promise<ProjectOption[]> {
  const response = await fetch(`${DATASET_API_BASE}/projects/registry`, { credentials: "include" });
  const payload = await response.json().catch(() => null);
  if (response.status === 401) throw new Error("Your session is not authenticated. Sign in again to create a documentation workspace.");
  if (!response.ok || payload?.ok === false) throw new Error(payload?.detail ?? payload?.error ?? "ATLAS could not load backend projects.");
  return (payload.projects ?? []).map((project: Record<string, unknown>) => ({
    projectId: String(project.projectId ?? ""),
    projectName: String(project.name ?? project.projectName ?? "Untitled ATLAS Project"),
    projectType: String(project.projectType ?? "unknown"),
    taskType: String(project.taskType ?? ""),
    target: String(project.target ?? ""),
    source: "backend" as const,
    lastModified: String(project.lastSavedAt ?? project.updatedAt ?? project.createdAt ?? ""),
    recoveryStatus: String(project.recoveryStatus ?? ""),
  })).filter((project: ProjectOption) => project.projectId);
}

async function fetchDocument(documentId: string) {
  const response = await fetch(`${DATASET_API_BASE}/model-documentation/${encodeURIComponent(documentId)}`, { credentials: "include" });
  const payload = await response.json().catch(() => null);
  if (response.status === 401) throw new Error("Your session is not authenticated. Sign in again to create a documentation workspace.");
  if (!response.ok || payload?.ok === false) throw new Error(payload?.detail ?? payload?.error ?? "ATLAS could not load the selected model documentation record.");
  return payload.document as ModelDocumentationDocument;
}

function projectFromLocal(project: LocalProjectRecord): ProjectOption {
  const progress = projectProgress(project.snapshot.workflowSteps ?? []);
  return {
    projectId: project.projectId,
    projectName: project.projectName,
    projectType: project.projectType,
    taskType: String((project.snapshot as unknown as { taskType?: string }).taskType ?? ""),
    target: String((project.snapshot as unknown as { target?: string }).target ?? ""),
    source: "browser",
    lastModified: project.lastModified,
    recoveryStatus: `${progress.complete} of ${progress.total} workflow steps complete`,
  };
}

function replaceSection(document: ModelDocumentationDocument, section: DocumentationSection): ModelDocumentationDocument {
  return {
    ...document,
    sections: document.sections.map((item) => item.sectionId === section.sectionId ? section : item),
  };
}

function evidenceCoverage(context: DocumentationProjectContext | null, document: ModelDocumentationDocument | null, items: DocumentationEvidence[]): EvidenceCoverage {
  const allAttached = document?.sections.flatMap((section) => section.attachedEvidence) ?? [];
  const combined = [...items, ...allAttached];
  const count = (matcher: (item: DocumentationEvidence) => boolean) => combined.filter(matcher).length;
  return {
    datasets: count((item) => item.source === "Dataset Library"),
    diagnostics: count((item) => item.source === "Model Diagnostics"),
    charts: count((item) => item.source === "Chart Studio"),
    notebooks: count((item) => item.source === "Notebook Studio"),
    analytics: count((item) => item.source === "Analytics Workbench"),
    governance: count((item) => item.source === "ATLAS Guide") + (context?.recoveredShell ? 1 : 0),
    generatedCode: count((item) => /code/i.test(`${item.type} ${item.title}`)),
    missingRequired: document?.quality?.missingEvidenceCount ?? 0,
  };
}

function readinessStatus(quality?: ModelDocumentationDocument["quality"]) {
  if (!quality) return { label: "Not ready", tone: "bg-slate-100 text-slate-700" };
  if (quality.exportReady) return { label: "Export ready", tone: "bg-emerald-100 text-emerald-700" };
  if (quality.completionPct >= 80 && quality.missingEvidenceCount <= 3) return { label: "Review ready", tone: "bg-blue-100 text-blue-700" };
  if (quality.completionPct >= 40) return { label: "Draft ready", tone: "bg-amber-100 text-amber-700" };
  return { label: "Not ready", tone: "bg-rose-100 text-rose-700" };
}

function evidenceRecommendations(sectionId: string) {
  const map: Record<string, string[]> = {
    executive_summary: ["Project metadata", "task type", "target", "champion model", "performance summary", "governance warnings"],
    business_objective: ["Project context", "business question", "decision context", "intended use"],
    model_use_case: ["project type", "task type", "target", "workflow context", "governance context"],
    target_definition: ["Target metadata", "target column", "classification or regression flag", "event rate", "target mean"],
    data_sources: ["Dataset inventory", "Dataset Library metadata", "Dataset versions", "Linked projects"],
    development_test_oot: ["TRAIN TEST OOT row counts", "target mean", "event rate", "version IDs"],
    eda: ["target distribution", "class balance", "event rate", "feature relationship", "missingness summary"],
    missing_value_treatment: ["Missing Values workflow page evidence", "imputation choices", "missingness summary"],
    outlier_treatment: ["Outliers workflow page evidence", "global method", "variable-level method", "no-treatment choices"],
    feature_engineering: ["generated feature list", "transformations", "scaling", "encoding", "leakage checks"],
    correlation_vif: ["VIF table", "correlation filtering", "thresholds", "recommendations"],
    model_training_strategy: ["validation strategy", "candidate models", "grid search", "PCA settings", "max parallel jobs"],
    candidate_models: ["selected algorithms", "training results", "best params", "training status"],
    champion_model_selection: ["champion model", "comparison table", "selected metric", "reason selected"],
    performance_summary: ["Training results", "Evaluation metrics", "Model Diagnostics fit summary", "Scored split comparison"],
    evaluation_diagnostics: ["Actual vs Predicted", "Residuals vs Predicted", "Q-Q Plot interpretation", "Residual distribution", "Lift table, if classification", "Calibration, if classification"],
    model_diagnostics: ["Prediction summary", "Regression fit summary", "Detailed lift table", "Population waterfall", "VIF analysis", "KPI aggregation", "Pozzolo calibration"],
    model_interpretation: ["Feature importance", "SHAP summary", "Coefficient table", "PDP and sensitivity", "Decision tree logic"],
    scoring_external_validation: ["scored TRAIN TEST OOT outputs", "prediction distribution", "split comparison", "residual diagnostics", "lift diagnostics"],
    fair_lending_governance: ["Governance notes", "Fair Lending review", "Compliance reminders", "Monitoring expectations"],
    implementation_plan: ["implementation workflow evidence", "scoring readiness", "export package metadata"],
    monitoring_plan: ["monitoring workflow evidence", "monitoring metrics", "drift recommendations", "stability recommendations"],
    limitations: ["recovered project warnings", "preview limitations", "model limitations", "missing artifacts"],
    appendices: ["generated Python", "SQL", "R", "SAS-compatible code", "exported evidence tables"],
  };
  return map[sectionId] ?? ["Project metadata", "Relevant dataset evidence", "Source-page insight", "Reviewer rationale"];
}

function recommendedEvidenceForSection(section: DocumentationSection, items: DocumentationEvidence[]) {
  const sources = evidenceSourcesForSection(section.sectionId);
  const keywords = evidenceRecommendations(section.sectionId).join(" ").toLowerCase().split(/\W+/).filter((word) => word.length > 3);
  return items.filter((item) => {
    const text = `${item.title} ${item.type} ${item.source} ${evidenceSummary(item)}`.toLowerCase();
    return sources.has(item.source) || keywords.some((word) => text.includes(word));
  });
}

function sectionNextAction(section: DocumentationSection, readiness = sectionEvidenceReadiness(section, [])) {
  const status = normalizeSectionStatus(section);
  if (status === "not_applicable") return "Marked not applicable.";
  if (status === "complete") return "Ready for export.";
  if (!section.attachedEvidence.length && readiness.available > 0) return "Evidence available. Attach recommended evidence.";
  if (!section.attachedEvidence.length && section.required) return evidenceRecommendations(section.sectionId)[0] ? `Next: add ${evidenceRecommendations(section.sectionId)[0].toLowerCase()}.` : "Next: add evidence.";
  if (!section.userNarrative) return "Next: review auto draft.";
  return "Next: mark complete or ready for review.";
}

function improvedDraft(section: DocumentationSection) {
  const evidenceCount = section.attachedEvidence.length;
  const support = evidenceCount ? `${evidenceCount} attached evidence item(s) currently support this section.` : "No project-specific evidence is attached yet.";
  const review = evidenceCount ? "Review the attached evidence for accuracy, lineage, and governance completeness." : "Attach the recommended evidence before final approval.";
  const caveat = section.required ? "Because this is a required MDD section, unresolved gaps should remain visible to validation and model risk reviewers." : "If this section is not applicable, mark it not applicable and preserve the rationale.";
  return `What ATLAS found: ${section.autoDraft}\n\nEvidence support: ${support}\n\nNeeds review: ${review}\n\nGovernance caveat: ${caveat}`;
}

function evidenceSummary(item: DocumentationEvidence) {
  const preview = item.preview ?? item.rows?.[0] ?? {};
  if (item.source === "Dataset Library") {
    return `${String(preview.dataset ?? preview.name ?? item.title)} with ${String(preview.rows ?? preview.rowCount ?? "-")} rows and ${String(preview.columns ?? preview.columnCount ?? "-")} columns.`;
  }
  if (item.source === "Model Diagnostics") return String(preview.summary ?? preview.businessQuestion ?? "Model diagnostic evidence saved from scored-output review.");
  if (item.source === "Chart Studio") return String(preview.summary ?? "Chart insight available for documentation.");
  if (item.source === "Notebook Studio") return String(preview.summary ?? "Notebook output available for documentation.");
  if (item.source === "Analytics Workbench") return String(preview.summary ?? "Analytics insight available for documentation.");
  if (item.source === "ATLAS Guide") return String(preview.detail ?? "Governance note detected.");
  return String(preview.summary ?? preview.detail ?? "Evidence item available for review.");
}

function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2 text-slate-900">
        {icon}
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      <div className="mt-3 grid gap-2">{children}</div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-lg font-semibold text-slate-950" title={value}>{value}</div>
    </div>
  );
}

function SmallFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950" title={value}>{value || "-"}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: DocumentationSectionStatus }) {
  const normalized = normalizeStatus(status);
  const label = humanize(normalized);
  const cls =
    normalized === "complete" ? "bg-emerald-100 text-emerald-700" :
    normalized === "needs_evidence" ? "bg-amber-100 text-amber-700" :
    normalized === "needs_review" || normalized === "ready_for_review" ? "bg-blue-100 text-blue-700" :
    normalized === "not_applicable" ? "bg-slate-100 text-slate-600" :
    "bg-blue-100 text-blue-700";
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cls}`}>{label}</span>;
}

function normalizeStatus(status: DocumentationSectionStatus | string) {
  if (status === "missing_evidence") return "needs_evidence";
  if (status === "needs_review") return "ready_for_review";
  return status || "draft";
}

function normalizeSectionStatus(section: DocumentationSection) {
  return normalizeStatus(section.status);
}

function matchesOutlineFilter(section: DocumentationSection, filter: string) {
  if (filter === "all") return true;
  const status = normalizeSectionStatus(section);
  if (filter === "needs_review") return status === "ready_for_review" || status === "needs_review" || status === "draft";
  return status === filter;
}

function filterEvidenceItems(items: DocumentationEvidence[], section: DocumentationSection | undefined, filter: string, search: string) {
  const recommended = section ? new Set(recommendedEvidenceForSection(section, items).map((item) => evidenceKey(item))) : new Set<string>();
  const searchText = search.trim().toLowerCase();
  return items.filter((item) => {
    const text = `${item.title} ${item.type} ${item.source} ${evidenceSummary(item)} ${previewEvidence(item)}`.toLowerCase();
    if (searchText && !text.includes(searchText)) return false;
    if (filter === "recommended") return recommended.has(evidenceKey(item));
    if (filter === "all") return true;
    if (filter === "evidence_graph") return item.source === "Evidence Graph" || item.source === "Model Evidence Center";
    if (filter === "credit_risk") return (item.source === "Evidence Graph" || item.source === "Model Evidence Center") && /credit_risk|pdo|woe|iv|manual_binning|reject_inference|fair_lending|adverse_action|psi|cutoff_optimization|risk_based_pricing/i.test(text);
    if (filter === "datasets") return item.source === "Dataset Library";
    if (filter === "diagnostics") return item.source === "Model Diagnostics";
    if (filter === "charts") return item.source === "Chart Studio";
    if (filter === "notebooks") return item.source === "Notebook Studio";
    if (filter === "analytics") return item.source === "Analytics Workbench";
    if (filter === "governance") return item.source === "ATLAS Guide";
    if (filter === "code") return /code/i.test(`${item.type} ${item.title}`);
    return true;
  });
}

function evidenceKey(item: DocumentationEvidence) {
  return `${item.source}::${item.type}::${item.title}`;
}

function evidenceGraphItemToDocumentationEvidence(item: EvidenceItem): DocumentationEvidence {
  return {
    type: item.evidenceType,
    title: item.title,
    source: "Model Evidence Center",
    createdAt: item.createdAt,
    preview: {
      summary: item.summary,
      sourcePage: item.sourcePage,
      sourceRoute: item.sourceRoute,
      status: item.status,
      importance: item.importance,
      supportsSections: item.supportsSections,
      datasetIds: item.datasetIds,
      modelIds: item.modelIds,
      notebookIds: item.notebookIds,
      financialDomain: item.financialDomain,
      financialTechnique: item.financialTechnique,
      regulatoryRelevance: item.regulatoryRelevance,
      creditRiskContext: item.creditRiskContext,
      lineage: item.lineage,
      governance: item.governance,
    },
  };
}

function dedupeDocumentationEvidence(items: DocumentationEvidence[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = evidenceKey(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function evidenceSourcesForSection(sectionId: string) {
  const sources = new Set<string>();
  if ([
    "executive_summary",
    "business_objective",
    "model_use_case",
    "target_definition",
    "population_definition",
    "inclusion_exclusion",
    "model_training_strategy",
    "champion_model_selection",
    "implementation_plan",
    "monitoring_plan",
    "limitations",
    "appendices",
  ].includes(sectionId)) sources.add("Project Registry");
  if (["data_sources", "development_test_oot", "target_definition", "population_definition", "scoring_external_validation"].includes(sectionId)) sources.add("Dataset Library");
  if (["eda", "missing_value_treatment", "outlier_treatment", "feature_engineering", "correlation_vif", "model_training_strategy", "candidate_models", "appendices"].includes(sectionId)) sources.add("Analytics Workbench");
  if (["evaluation_diagnostics", "model_interpretation", "scoring_external_validation", "appendices"].includes(sectionId)) sources.add("Chart Studio");
  if (["executive_summary", "eda", "model_interpretation", "evaluation_diagnostics", "model_diagnostics", "appendices"].includes(sectionId)) sources.add("Notebook Studio");
  if (["model_diagnostics", "scoring_external_validation", "performance_summary", "evaluation_diagnostics", "model_interpretation", "champion_model_selection"].includes(sectionId)) sources.add("Model Diagnostics");
  if (["fair_lending_governance", "executive_summary", "limitations"].includes(sectionId)) sources.add("ATLAS Guide");
  return sources;
}

function sectionEvidenceReadiness(section: DocumentationSection, items: DocumentationEvidence[]) {
  const available = recommendedEvidenceForSection(section, items).filter((item) => !section.attachedEvidence.some((attached) => evidenceKey(attached) === evidenceKey(item))).length;
  const attached = section.attachedEvidence.length;
  const hasDraft = Boolean(section.userNarrative || section.autoDraft);
  const missingCritical = section.required && attached === 0 && available === 0 && !hasDraft ? 1 : 0;
  return { attached, available, missingCritical };
}

function ExportButton({ label, status, icon, loading, onClick }: { label: string; status: string; icon: React.ReactNode; loading: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} disabled={loading} className="mb-2 grid w-full gap-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-left text-sm font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-60">
      <span className="inline-flex items-center gap-2">{icon}{loading ? "Exporting..." : label}</span>
      <span className="text-[11px] font-medium leading-4 text-slate-500">Status: {status}</span>
    </button>
  );
}

function defaultTemplates(): DocumentationTemplate[] {
  return [
    { templateType: AVAILABLE_TEMPLATE, label: "Model Development Document", status: "available", description: "Governed model development document." },
    { templateType: "validation_evidence_pack", label: "Model Validation Evidence Pack", status: "coming_soon", description: "Independent validation evidence package." },
    { templateType: "monitoring_handoff", label: "Model Monitoring Handoff", status: "coming_soon", description: "Monitoring setup, cadence, and escalation evidence." },
    { templateType: "executive_summary", label: "Executive Summary", status: "coming_soon", description: "Senior leadership summary narrative and deck." },
    { templateType: "technical_appendix", label: "Technical Appendix", status: "coming_soon", description: "Detailed methods, code evidence, and diagnostics." },
  ];
}

function previewEvidence(item: DocumentationEvidence) {
  return JSON.stringify(item.preview ?? item.rows ?? item, null, 2).slice(0, 900);
}

function exportLabel(format: "word" | "powerpoint" | "evidence-excel") {
  if (format === "word") return "Word";
  if (format === "powerpoint") return "PowerPoint";
  return "Excel evidence pack";
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function humanize(value: string) {
  return (value || "-").replace(/[_-]/g, " ").replace(/\b\w/g, (match) => match.toUpperCase());
}
