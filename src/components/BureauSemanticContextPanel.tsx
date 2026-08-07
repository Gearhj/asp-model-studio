import { useEffect, useMemo, useState } from "react";
import { BookOpen, ShieldCheck, TriangleAlert } from "lucide-react";
import type { CanonicalDatasetIdentity } from "../lib/datasetIdentity";
import {
  annotationForDatasetField,
  bureauSemanticAuthorityPresentation,
  fetchBureauSemanticAnnotations,
  type BureauSemanticAnnotationContract,
} from "../lib/bureauSemanticAnnotations";

type BureauSemanticContextPanelProps = {
  datasetIdentity: CanonicalDatasetIdentity;
  datasetFields: readonly string[];
  pageName: "EDA" | "Outliers" | "Missing Values" | "Feature Engineering";
};

function compactChecksum(value?: string) {
  if (!value) return "not available";
  return `${value.slice(0, 8)}\u2026${value.slice(-8)}`;
}

/**
 * A read-only, bounded consumer of the canonical semantic annotation envelope.
 * The component performs one exact-version request for the page. Selecting a
 * field only changes local presentation; it never reads provider source files or
 * calls a treatment, predictor, partition, or feature-manifest mutation API.
 */
export default function BureauSemanticContextPanel({
  datasetIdentity,
  datasetFields,
  pageName,
}: BureauSemanticContextPanelProps) {
  const [contract, setContract] =
    useState<BureauSemanticAnnotationContract | null>(null);
  const [failedClosed, setFailedClosed] = useState(false);
  const [selectedField, setSelectedField] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setContract(null);
    setFailedClosed(false);
    setSelectedField("");
    fetchBureauSemanticAnnotations({
      projectId: datasetIdentity.project_id,
      datasetIdentity,
      signal: controller.signal,
    })
      .then((nextContract) => {
        if (!controller.signal.aborted) setContract(nextContract);
      })
      .catch((error: unknown) => {
        if (
          !controller.signal.aborted &&
          !(error instanceof DOMException && error.name === "AbortError")
        ) {
          setFailedClosed(true);
        }
      });
    return () => controller.abort();
  }, [
    datasetIdentity.project_id,
    datasetIdentity.dataset_id,
    datasetIdentity.dataset_version_id,
    datasetIdentity.activation_revision,
  ]);

  const fields = useMemo(
    () =>
      Array.from(
        new Set(datasetFields.map((field) => field.trim()).filter(Boolean)),
      ).sort((left, right) => left.localeCompare(right)),
    [datasetFields],
  );
  const activeField = fields.includes(selectedField)
    ? selectedField
    : fields[0] ?? "";
  const annotation =
    contract && activeField
      ? annotationForDatasetField(contract, activeField)
      : undefined;
  const authority = annotation
    ? bureauSemanticAuthorityPresentation(annotation)
    : null;

  // Optional metadata must stay unobtrusive for non-bureau datasets and users
  // without catalog entitlement. Data Acquisition owns those user-facing states.
  if (!failedClosed && contract?.state !== "available") return null;

  return (
    <section
      className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm"
      data-testid={`bureau-semantic-context-${pageName.toLowerCase().replaceAll(" ", "-")}`}
      aria-label={`${pageName} bureau metadata context`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <BookOpen className="mt-0.5 shrink-0 text-blue-600" size={16} />
          <div>
            <h2 className="text-sm font-semibold text-slate-950">
              Bureau metadata context
            </h2>
            <p className="mt-0.5 text-xs leading-5 text-slate-600">
              Read-only provider context for this exact dataset version. It does
              not change calculations, treatments, predictor authorization, the
              Analysis Partition, or the feature manifest.
            </p>
          </div>
        </div>

        {failedClosed ? (
          <span
            className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800"
            title="The exact semantic identity could not be verified, so no provider authority is asserted."
          >
            <TriangleAlert size={13} /> Non-authoritative (identity unavailable)
          </span>
        ) : contract?.state === "available" ? (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800">
            <ShieldCheck size={13} /> {contract.annotations.length} accepted mappings
          </span>
        ) : null}
      </div>

      {contract?.state === "available" ? (
        <div className="mt-3 grid gap-3 border-t border-slate-100 pt-3 lg:grid-cols-[minmax(13rem,0.8fr)_minmax(0,1.8fr)]">
          <label className="text-xs font-semibold text-slate-700">
            Dataset feature
            <select
              className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900"
              value={activeField}
              onChange={(event) => setSelectedField(event.target.value)}
              aria-label={`${pageName} bureau metadata feature`}
            >
              {fields.map((field) => (
                <option key={field} value={field}>
                  {field}
                </option>
              ))}
            </select>
          </label>

          <div className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs text-slate-700">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span
                className={`inline-flex items-center rounded-full border px-2 py-0.5 font-bold ${
                  authority?.providerAuthoritative
                    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                    : "border-amber-200 bg-amber-50 text-amber-800"
                }`}
                title={authority?.detail ?? "No accepted provider mapping exists for this feature."}
              >
                {authority?.label ?? "Heuristic / non-authoritative"}
              </span>
              <span className="font-medium text-slate-500">
                Binding r{contract.annotationSet.bindingRevision} \u00b7 Crosswalk r
                {contract.annotationSet.crosswalkRevision ?? "\u2014"} \u00b7 Catalog {" "}
                {contract.annotationSet.catalogKey.dictionaryVersion}
              </span>
            </div>

            {annotation ? (
              <details className="mt-2" data-testid="bureau-provider-definition-detail">
                <summary className="cursor-pointer font-semibold text-blue-700">
                  View provider definition and lineage
                </summary>
                <div className="mt-2 grid gap-1.5 border-t border-slate-200 pt-2 leading-5 sm:grid-cols-2">
                  <p className="sm:col-span-2">
                    <strong>Definition:</strong>{" "}
                    {annotation.description || "No bounded description was supplied."}
                  </p>
                  <p><strong>Provider attribute:</strong> {annotation.candidateAttributeCode ?? "Not resolved"}</p>
                  <p><strong>Type / units:</strong> {[annotation.dataType, annotation.units].filter(Boolean).join(" / ") || "Not specified"}</p>
                  <p><strong>Mapping state:</strong> {annotation.mappingState.replaceAll("_", " ")}</p>
                  <p><strong>Authority:</strong> {authority?.detail}</p>
                  <p><strong>Binding checksum:</strong> {compactChecksum(annotation.bindingRevisionChecksum)}</p>
                  <p><strong>Catalog checksum:</strong> {compactChecksum(annotation.catalogChecksum)}</p>
                  {annotation.ordinaryRange ? (
                    <p className="sm:col-span-2"><strong>Ordinary range:</strong> {annotation.ordinaryRange.expression || [annotation.ordinaryRange.minimum, annotation.ordinaryRange.maximum].filter(Boolean).join(" to ") || "Not specified"}</p>
                  ) : null}
                  {annotation.specialDefinitions.length ? (
                    <p className="sm:col-span-2"><strong>Provider special definitions:</strong> {annotation.specialDefinitions.map((definition) => `${definition.valueCode}: ${definition.meaning}`).join(" \u00b7 ")}</p>
                  ) : null}
                </div>
              </details>
            ) : (
              <p className="mt-2 leading-5 text-slate-600">
                No accepted provider mapping exists for {activeField || "this feature"}.
                Observed behavior and ATLAS heuristics remain non-authoritative.
              </p>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}
