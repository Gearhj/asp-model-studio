import { useState } from "react";
import { AlertTriangle, CheckCircle2, Circle, LockKeyhole } from "lucide-react";
import type {
  OptimizationInputRoleDefinition,
  OptimizationTemplateDefinition,
} from "../../config/optimizationTemplates";
import type {
  TransportationBundleRole,
  TransportationFormulation,
  TransportationInputBundle,
  TransportationScenarioAnalysis,
  TransportationSensitivity,
  TransportationSolveResult,
} from "../../lib/optimizationWorkflow";

export const TRANSPORTATION_STAGE_LABELS = [
  "Context",
  "Inputs",
  "Readiness",
  "Objective",
  "Variables",
  "Constraints",
  "Solver",
  "Scenarios",
  "Optimize",
  "Sensitivity",
  "Validation",
  "Decision",
  "Implementation",
  "Documentation",
];

function format(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Not available";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

function percent(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Not available";
  return `${format(value * 100, 1)}%`;
}

function ChartFrame({
  title,
  interpretation,
  scope,
  evidence,
  children,
}: {
  title: string;
  interpretation: string;
  scope: string;
  evidence: "Ready" | "Needs review" | "Blocked";
  children: React.ReactNode;
}) {
  const tone = evidence === "Ready" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : evidence === "Blocked" ? "border-red-200 bg-red-50 text-red-800" : "border-amber-200 bg-amber-50 text-amber-900";
  return (
    <figure className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <figcaption className="flex flex-col gap-2 border-b border-slate-100 pb-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
          <p className="mt-1 text-xs leading-5 text-slate-600">{interpretation}</p>
        </div>
        <span className={`inline-flex w-fit items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide ${tone}`}>
          {evidence === "Ready" ? <CheckCircle2 size={12} /> : evidence === "Blocked" ? <LockKeyhole size={12} /> : <AlertTriangle size={12} />}
          {evidence}
        </span>
      </figcaption>
      <div className="py-4">{children}</div>
      <div className="border-t border-slate-100 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Data scope: {scope}</div>
    </figure>
  );
}

export function TransportationLifecycleMap({ currentStep, completedThrough, evidenceSteps = [] }: { currentStep: number; completedThrough: number; evidenceSteps?: number[] }) {
  const statusStyle = {
    current: { border: "border-blue-600", circle: "bg-blue-600 text-white", text: "text-blue-800", label: "Current" },
    evidence: { border: "border-emerald-600", circle: "bg-emerald-600 text-white", text: "text-emerald-800", label: "Evidence" },
    complete: { border: "border-teal-500", circle: "bg-teal-100 text-teal-800", text: "text-teal-800", label: "Complete" },
    pending: { border: "border-slate-300", circle: "bg-slate-100 text-slate-600", text: "text-slate-600", label: "Pending" },
    blocked: { border: "border-amber-300", circle: "bg-amber-100 text-amber-800", text: "text-amber-800", label: "Blocked" },
  } as const;
  return (
    <nav aria-label="Transportation optimization workflow" className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div
        className="grid min-w-[1080px] gap-1.5"
        style={{ gridTemplateColumns: `repeat(${TRANSPORTATION_STAGE_LABELS.length}, minmax(70px, 1fr))` }}
      >
        {TRANSPORTATION_STAGE_LABELS.map((label, index) => {
          const number = index + 1;
          const state = number === currentStep
            ? "current"
            : evidenceSteps.includes(number)
              ? "evidence"
              : number <= completedThrough
                ? "complete"
                : number === completedThrough + 1
                  ? "pending"
                  : "blocked";
          const style = statusStyle[state];
          return (
            <div key={label} className={`relative min-w-0 border-t-4 px-1 pt-2 text-center ${style.border}`} title={`${label}: ${style.label}`}>
              <div className={`mx-auto flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${style.circle}`}>
                {state === "evidence" || state === "complete" ? <CheckCircle2 size={13} /> : state === "blocked" ? <LockKeyhole size={11} /> : number}
              </div>
              <div className={`mt-1 truncate text-[10px] font-semibold ${style.text}`} title={label}>{label}</div>
              <div className={`mt-0.5 text-[8px] font-semibold uppercase tracking-wide ${style.text}`}>{style.label}</div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex min-w-[980px] flex-wrap gap-x-5 gap-y-2 border-t border-slate-100 pt-3 text-[10px] leading-4 text-slate-600" aria-label="Workflow status legend">
        <StatusDefinition label="Current" color="bg-blue-600" text="The user is viewing or working on this step." />
        <StatusDefinition label="Complete" color="bg-teal-500" text="The step's required workflow state is complete." />
        <StatusDefinition label="Evidence" color="bg-emerald-600" text="The step is complete and its governed evidence artifact is captured or ready." />
        <StatusDefinition label="Pending" color="bg-slate-400" text="The step has not been completed." />
        <StatusDefinition label="Blocked" color="bg-amber-500" text="The step cannot continue because required upstream state is missing." />
      </div>
    </nav>
  );
}

function StatusDefinition({ label, color, text }: { label: string; color: string; text: string }) {
  return <span className="inline-flex items-start gap-1.5"><span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${color}`} /><span><strong className="text-slate-800">{label}:</strong> {text}</span></span>;
}

type TemplateBundleRole = OptimizationInputRoleDefinition & {
  requirement: "required" | "optional";
  bundle_key: TransportationBundleRole;
};

export function InputBundleCompletenessChart({ bundle, template, roles, evidenceCaptured = false }: { bundle: TransportationInputBundle; template: OptimizationTemplateDefinition; roles: TemplateBundleRole[]; evidenceCaptured?: boolean }) {
  const required = roles.filter((role) => role.requirement === "required");
  const optional = roles.filter((role) => role.requirement === "optional");
  const requiredLoaded = required.filter((role) => Boolean(bundle[role.bundle_key]?.datasetId)).length;
  const optionalLoaded = optional.filter((role) => Boolean(bundle[role.bundle_key]?.datasetId)).length;
  const complete = requiredLoaded === required.length;
  return (
    <ChartFrame title="Input bundle completeness" interpretation={`${requiredLoaded} of ${required.length} required inputs assigned. ${optionalLoaded} of ${optional.length} optional inputs assigned.`} scope={`${template.display_name} registered dataset references`} evidence={complete ? "Ready" : "Needs review"}>
      <div className="mb-4 grid gap-2 sm:grid-cols-4">
        <BundleSummary label="Required inputs complete" value={`${requiredLoaded} of ${required.length}`} tone={complete ? "success" : "warning"} />
        <BundleSummary label="Optional inputs complete" value={`${optionalLoaded} of ${optional.length}`} tone="neutral" />
        <BundleSummary label="Ready to normalize" value={complete ? "Yes" : "No"} tone={complete ? "success" : "warning"} />
        <BundleSummary label="Evidence captured" value={evidenceCaptured ? "Yes" : "No"} tone={evidenceCaptured ? "success" : "neutral"} />
      </div>
      <div className="grid gap-2">
        {roles.map((role) => {
          const ready = Boolean(bundle[role.bundle_key]?.datasetId);
          return (
            <div key={role.role_id} className="grid grid-cols-[minmax(0,1fr)_96px] items-center gap-3">
              <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-slate-700">{ready ? <CheckCircle2 size={15} className="shrink-0 text-emerald-600" /> : <Circle size={15} className="shrink-0 text-slate-400" />}<span className="min-w-0">{role.display_name}</span><span className="ml-auto shrink-0 text-[9px] font-semibold uppercase tracking-wide text-slate-400">{role.requirement}</span></div>
              <div className="h-2 overflow-hidden rounded-sm bg-slate-100"><div className={`h-full ${ready ? "w-full bg-emerald-500" : "w-0 bg-slate-300"}`} /></div>
            </div>
          );
        })}
      </div>
      {optionalLoaded === 0 && <div className="mt-4 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">Inventory or handling cost was not supplied. The objective will use route transportation cost only.</div>}
    </ChartFrame>
  );
}

function BundleSummary({ label, value, tone }: { label: string; value: string; tone: "success" | "warning" | "neutral" }) {
  const classes = tone === "success" ? "border-emerald-200 bg-emerald-50" : tone === "warning" ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50";
  return <div className={`rounded-md border px-3 py-2 ${classes}`}><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-sm font-bold text-slate-950">{value}</div></div>;
}

function heatColor(value: number, minimum: number, maximum: number, palette: "cost" | "allocation") {
  const ratio = maximum <= minimum ? 0.5 : Math.max(0, Math.min(1, (value - minimum) / (maximum - minimum)));
  if (palette === "allocation") {
    return `hsl(${158 - ratio * 22} 58% ${96 - ratio * 45}%)`;
  }
  return `hsl(${212 - ratio * 25} 78% ${96 - ratio * 48}%)`;
}

export function RouteMatrixChart({ formulation, result, mode = "cost", activeOverrides = {}, exclusionRationales = {} }: { formulation: TransportationFormulation; result?: TransportationSolveResult | null; mode?: "cost" | "variables" | "allocation"; activeOverrides?: Record<string, boolean>; exclusionRationales?: Record<string, string> }) {
  const [selectedRouteId, setSelectedRouteId] = useState(formulation.routes[0]?.route_id ?? "");
  const suppliers = formulation.suppliers.map((row) => row.supplier);
  const customers = formulation.customers.map((row) => row.customer);
  const allocation = new Map((result?.decisionVector ?? []).map((row) => [`${row.supplier}|${row.customer}`, row.quantity]));
  const values = formulation.routes.map((route) => mode === "allocation" ? allocation.get(`${route.supplier}|${route.customer}`) ?? 0 : route.total_unit_cost ?? 0);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const title = mode === "allocation" ? "Optimized allocation heatmap" : mode === "variables" ? "Route decision-variable matrix" : "Route cost matrix";
  const interpretation = mode === "allocation"
    ? "Cell annotations show optimized quantity. Darker cells carry more volume."
    : mode === "variables"
      ? "Every valid customer and supplier intersection creates one continuous route variable."
      : "Cell annotations show total unit cost: route transportation cost plus supplier inventory cost.";
  const selectedRoute = formulation.routes.find((route) => route.route_id === selectedRouteId) ?? formulation.routes[0];
  const selectedAllocation = selectedRoute ? allocation.get(`${selectedRoute.supplier}|${selectedRoute.customer}`) ?? 0 : 0;
  return (
    <ChartFrame title={title} interpretation={interpretation} scope={`${customers.length} customers, ${suppliers.length} suppliers, ${formulation.routes.length} full-artifact routes`} evidence={mode === "allocation" ? (result?.businessValidityStatus === "valid" ? "Ready" : "Blocked") : formulation.formulationReady ? "Ready" : "Needs review"}>
      <div className="overflow-x-auto">
        <div className="grid min-w-[650px] gap-1" style={{ gridTemplateColumns: `120px repeat(${suppliers.length}, minmax(88px, 1fr))` }}>
          <div />
          {suppliers.map((supplier) => <div key={supplier} className="px-2 py-1 text-center text-[10px] font-semibold uppercase text-slate-500">{supplier}</div>)}
          {customers.flatMap((customer) => [
            <div key={`${customer}-label`} className="flex items-center px-2 text-xs font-semibold text-slate-700">{customer}</div>,
            ...suppliers.map((supplier) => {
              const route = formulation.routes.find((item) => item.customer === customer && item.supplier === supplier)!;
              const value = mode === "allocation" ? allocation.get(`${supplier}|${customer}`) ?? 0 : route.total_unit_cost ?? 0;
              return (
                <button type="button" key={`${supplier}-${customer}`} onClick={() => setSelectedRouteId(route.route_id)} className={`min-h-14 border px-2 py-2 text-center outline-none transition focus:ring-2 focus:ring-blue-600 ${selectedRoute?.route_id === route.route_id ? "border-blue-700 ring-2 ring-blue-300" : "border-white/70"}`} style={{ backgroundColor: heatColor(value, minimum, maximum, mode === "allocation" ? "allocation" : "cost") }} title={`Inspect ${route.variable_name}: ${format(value, 3)}`}>
                  <div className="text-sm font-bold text-slate-950">{format(value, mode === "allocation" ? 1 : 2)}</div>
                  <div className="mt-0.5 truncate text-[9px] text-slate-700">{mode === "variables" ? route.variable_name : mode === "allocation" ? `Cost ${format(route.total_unit_cost, 2)}` : route.variable_name}</div>
                </button>
              );
            }),
          ])}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
        {mode === "allocation" ? <><LegendSwatch color="bg-emerald-700" label="Color intensity = allocation volume" /><LegendSwatch color="bg-emerald-100" label="Zero = unused route" /><span>Cell value = shipped quantity | Cost label = total unit cost</span></> : <><LegendSwatch color="bg-blue-800" label="Darker blue = higher total unit cost" /><LegendSwatch color="bg-blue-100" label="Lighter blue = lower total unit cost" /><span>Cell value = total unit cost | Variable label = supplier-customer route variable | Total unit cost = transportation cost + supplier inventory or handling cost</span></>}
      </div>
      {selectedRoute && <div className="mt-3 rounded-md border border-blue-200 bg-blue-50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div><div className="text-[10px] font-semibold uppercase text-blue-700">Route inspection</div><div className="mt-1 text-sm font-bold text-slate-950">{selectedRoute.supplier} to {selectedRoute.customer} | {selectedRoute.variable_name}</div></div><span className={`rounded-md px-2 py-1 text-[10px] font-semibold uppercase ${activeOverrides[selectedRoute.route_id] === false ? "bg-red-100 text-red-800" : "bg-emerald-100 text-emerald-800"}`}>{activeOverrides[selectedRoute.route_id] === false ? "Excluded" : "Active"}</span></div><dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4"><RouteFact label="Transportation cost" value={format(selectedRoute.transportation_cost)} /><RouteFact label="Inventory cost" value={format(selectedRoute.inventory_cost)} /><RouteFact label="Total unit cost" value={format(selectedRoute.total_unit_cost)} /><RouteFact label="Optimized quantity" value={result ? format(selectedAllocation, 2) : "Not solved"} /><RouteFact label="Source tables" value={selectedRoute.source_tables.join(", ")} /><RouteFact label="Validation status" value={selectedRoute.total_unit_cost == null ? "Needs review" : "Valid route"} /><RouteFact label="Lower bound" value={format(selectedRoute.lower_bound)} /><RouteFact label="Upper bound" value={activeOverrides[selectedRoute.route_id] === false ? "0, excluded" : format(selectedRoute.upper_bound)} /><RouteFact label="Rationale" value={exclusionRationales[selectedRoute.route_id] || (activeOverrides[selectedRoute.route_id] === false ? "Required before continuation" : "Not applicable")} /></dl></div>}
    </ChartFrame>
  );
}

function LegendSwatch({ color, label }: { color: string; label: string }) { return <span className="inline-flex items-center gap-2"><span className={`h-3 w-3 border border-white shadow-sm ${color}`} />{label}</span>; }
function RouteFact({ label, value }: { label: string; value: string }) { return <div><dt className="text-[9px] font-semibold uppercase text-slate-500">{label}</dt><dd className="mt-1 break-words font-semibold text-slate-900">{value}</dd></div>; }

export function DemandCapacityChart({ formulation }: { formulation: TransportationFormulation }) {
  const rows = [
    { label: "Demand", value: formulation.metrics.totalDemand, color: "bg-slate-800" },
    { label: "Supply maximum", value: formulation.metrics.totalSupplyMax, color: "bg-blue-600" },
    { label: "Transport capacity", value: formulation.metrics.totalTransportCapacity, color: "bg-emerald-600" },
  ];
  const maximum = Math.max(...rows.map((row) => row.value), 1);
  const feasible = formulation.metrics.totalSupplyMax >= formulation.metrics.totalDemand && formulation.metrics.totalTransportCapacity >= formulation.metrics.totalDemand;
  return (
    <ChartFrame title="Demand versus capacity" interpretation={formulation.metrics.totalTransportCapacity < formulation.metrics.totalSupplyMax ? "Transportation capacity is the tighter aggregate limit." : "Supplier supply is the tighter aggregate limit."} scope="Full normalized input bundle" evidence={feasible ? "Ready" : "Blocked"}>
      <div className="grid gap-4">
        {rows.map((row) => <div key={row.label} className="grid grid-cols-[128px_minmax(0,1fr)_72px] items-center gap-3"><div className="text-xs font-semibold text-slate-700">{row.label}</div><div className="h-5 bg-slate-100"><div className={`h-full ${row.color}`} style={{ width: `${Math.max(1, row.value / maximum * 100)}%` }} /></div><div className="text-right text-sm font-bold text-slate-950">{format(row.value, 0)}</div></div>)}
      </div>
    </ChartFrame>
  );
}

export function ObjectiveDistributionChart({ formulation }: { formulation: TransportationFormulation }) {
  const costs = formulation.routes.map((route) => route.total_unit_cost).filter((value): value is number => value !== null && Number.isFinite(value));
  const min = Math.min(...costs);
  const max = Math.max(...costs);
  const binCount = Math.min(8, Math.max(4, Math.ceil(Math.sqrt(costs.length))));
  const width = max === min ? 1 : (max - min) / binCount;
  const bins = Array.from({ length: binCount }, (_, index) => ({ start: min + index * width, end: index === binCount - 1 ? max : min + (index + 1) * width, count: 0 }));
  costs.forEach((cost) => { bins[Math.min(binCount - 1, Math.floor((cost - min) / width))].count += 1; });
  const peak = Math.max(...bins.map((bin) => bin.count), 1);
  return (
    <ChartFrame title="Objective coefficient distribution" interpretation={`Route total unit costs range from ${format(min)} to ${format(max)} across ${costs.length} route variables.`} scope="Route transportation plus inventory costs" evidence={costs.length === formulation.routes.length ? "Ready" : "Needs review"}>
      <div className="flex h-44 items-end gap-2 border-b border-l border-slate-300 px-3 pt-4">
        {bins.map((bin) => <div key={bin.start} className="flex h-full flex-1 flex-col justify-end"><div className="mb-1 text-center text-[10px] font-semibold text-slate-600">{bin.count}</div><div className="bg-blue-600" style={{ height: `${Math.max(3, bin.count / peak * 100)}%` }} /><div className="mt-1 whitespace-nowrap text-center text-[9px] text-slate-500">{format(bin.start, 1)}</div></div>)}
      </div>
    </ChartFrame>
  );
}

export function ConstraintReadinessChart({ formulation }: { formulation: TransportationFormulation }) {
  const rows = [
    ["Demand equalities", formulation.metrics.demandConstraintCount, formulation.metrics.customerCount],
    ["Supply limits", formulation.metrics.supplyConstraintCount, formulation.metrics.supplierCount],
    ["Transport limits", formulation.metrics.transportConstraintCount, formulation.metrics.supplierCount],
    ["Non-negativity bounds", formulation.metrics.nonNegativityBoundCount, formulation.metrics.routeCount],
  ] as const;
  return (
    <ChartFrame title="Constraint readiness" interpretation="Generated executable rules are reconciled to the normalized business entities." scope={`Formulation ${formulation.formulationId}`} evidence={formulation.formulationReady ? "Ready" : "Blocked"}>
      <div className="grid gap-3">
        {rows.map(([label, actual, expected]) => <div key={label} className="grid grid-cols-[150px_minmax(0,1fr)_72px] items-center gap-3"><div className="text-xs font-semibold text-slate-700">{label}</div><div className="h-2 bg-slate-100"><div className={`${actual === expected ? "bg-emerald-500" : "bg-amber-500"} h-full`} style={{ width: `${Math.min(100, actual / Math.max(1, expected) * 100)}%` }} /></div><div className="text-right text-xs font-bold text-slate-900">{actual} / {expected}</div></div>)}
      </div>
    </ChartFrame>
  );
}

export function SupplierUtilizationChart({ result }: { result: TransportationSolveResult }) {
  const maximum = Math.max(...result.supplierUtilization.map((row) => Math.max(row.supplyMax, row.transportCapacity)), 1);
  return (
    <ChartFrame title="Supplier utilization" interpretation="Used quantity is compared with both supplier supply maximum and transportation capacity." scope={`Solver run ${result.runId}`} evidence={result.businessValidityStatus === "valid" ? "Ready" : "Blocked"}>
      <div className="mb-4 flex flex-wrap gap-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700"><LegendSwatch color="bg-emerald-500" label="Used quantity" /><LegendSwatch color="bg-blue-200" label="Supply maximum" /><span className="inline-flex items-center gap-2"><span className="h-4 border-r-2 border-amber-500" />Transport-capacity limit</span></div>
      <div className="grid gap-4">
        {result.supplierUtilization.map((row) => <div key={row.supplier}><div className="mb-1 flex justify-between text-xs"><span className="font-semibold text-slate-800">{row.supplier}</span><span className="text-slate-600">Used {format(row.used, 1)} | Transport {format(row.transportCapacity, 0)} | Supply {format(row.supplyMax, 0)}</span></div><div className="relative h-5 bg-slate-100"><div className="absolute inset-y-0 left-0 bg-blue-200" style={{ width: `${row.supplyMax / maximum * 100}%` }} /><div className="absolute inset-y-0 left-0 bg-emerald-500" style={{ width: `${row.used / maximum * 100}%` }} /><div className="absolute inset-y-0 border-r-2 border-amber-500" style={{ left: `${row.transportCapacity / maximum * 100}%` }} /></div></div>)}
      </div>
    </ChartFrame>
  );
}

export function CustomerFulfillmentChart({ result }: { result: TransportationSolveResult }) {
  return (
    <ChartFrame title="Customer demand fulfillment" interpretation={`Fulfilled ${format(result.demandFulfilled, 1)} of ${format(result.totalDemand, 1)} required units.`} scope={`Solver run ${result.runId}`} evidence={result.unmetDemand <= 1e-6 ? "Ready" : "Blocked"}>
      <div className="grid gap-3">
        {result.customerFulfillment.map((row) => <div key={row.customer} className="grid grid-cols-[104px_minmax(0,1fr)_88px] items-center gap-3"><div className="text-xs font-semibold text-slate-700">{row.customer}</div><div className="relative h-4 bg-red-100"><div className="h-full bg-emerald-500" style={{ width: `${Math.min(100, row.fulfillmentRate * 100)}%` }} /></div><div className="text-right text-xs font-bold text-slate-900">{format(row.supplied, 1)} / {format(row.demand, 1)}</div></div>)}
      </div>
    </ChartFrame>
  );
}

export function CostContributionChart({ result }: { result: TransportationSolveResult }) {
  const rows = [...result.costBreakdown.bySupplier].sort((a, b) => b.cost - a.cost);
  const maximum = Math.max(...rows.map((row) => row.cost), 1);
  return (
    <ChartFrame title="Cost contribution by supplier" interpretation="Bars identify the suppliers contributing most to optimized distribution cost." scope={`Business-valid solution ${result.solutionId ?? "not saved"}`} evidence={result.businessValidityStatus === "valid" ? "Ready" : "Blocked"}>
      <div className="grid gap-3">
        {rows.map((row) => <div key={row.supplier} className="grid grid-cols-[104px_minmax(0,1fr)_88px] items-center gap-3"><div className="text-xs font-semibold text-slate-700">{row.supplier}</div><div className="h-4 bg-slate-100"><div className="h-full bg-slate-800" style={{ width: `${row.cost / maximum * 100}%` }} /></div><div className="text-right text-xs font-bold text-slate-950">{format(row.cost)}</div></div>)}
      </div>
    </ChartFrame>
  );
}

export function ScenarioComparisonChart({ analysis }: { analysis: TransportationScenarioAnalysis }) {
  const validCosts = analysis.results.map((row) => row.totalCost).filter((value): value is number => value !== null);
  const maximum = Math.max(...validCosts, 1);
  return (
    <ChartFrame title="Total logistics cost by scenario" interpretation={`${analysis.validScenarioCount} scenarios remain business-valid; ${analysis.infeasibleScenarioCount} are solver-infeasible under stress.`} scope={`${analysis.scenarioCount} transportation-specific scenarios`} evidence={analysis.available && analysis.results.length ? "Ready" : "Blocked"}>
      <div className="grid gap-3">
        {analysis.results.map((row) => <div key={row.scenarioId} className="grid grid-cols-[160px_minmax(0,1fr)_104px] items-center gap-3"><div><div className="text-xs font-semibold text-slate-800">{row.scenarioName}</div><div className={`text-[10px] font-semibold uppercase ${row.feasible ? "text-emerald-700" : "text-red-700"}`}>{row.feasible ? "Feasible" : "Infeasible"} | unmet {format(row.unmetDemand, 0)}</div></div><div className="h-5 bg-slate-100"><div className={`h-full ${row.businessValid ? "bg-blue-600" : "bg-red-400"}`} style={{ width: `${row.totalCost === null ? 2 : Math.max(2, row.totalCost / maximum * 100)}%` }} /></div><div className="text-right text-xs font-bold text-slate-950">{row.totalCost === null ? "No solution" : format(row.totalCost)}</div></div>)}
      </div>
    </ChartFrame>
  );
}

export function SensitivityTornadoChart({ analysis }: { analysis: TransportationSensitivity }) {
  const rows = analysis.tornado.filter((row) => row.costChange !== null).slice(0, 10);
  const maximum = Math.max(...rows.map((row) => Math.abs(row.costChange ?? 0)), 1);
  return (
    <ChartFrame title="Sensitivity tornado" interpretation={analysis.conclusion} scope={`${analysis.perturbationPercent}% perturbations around run ${analysis.baseRunId}`} evidence={analysis.available ? "Ready" : "Blocked"}>
      <div className="mb-4 flex flex-wrap items-center gap-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700"><LegendSwatch color="bg-amber-500" label="Orange = cost increase" /><LegendSwatch color="bg-emerald-500" label="Green = cost decrease" /><span className="inline-flex items-center gap-2"><span className="h-4 border-r border-slate-500" />Center line = base optimized solution</span></div>
      <div className="grid gap-2">
        {rows.map((row) => {
          const value = row.costChange ?? 0;
          return <div key={`${row.driver}-${row.direction}`} className="grid grid-cols-[160px_minmax(0,1fr)_84px] items-center gap-3" title={`Active route change: ${row.activeRouteChange}. Allocation turnover: ${percent(row.allocationTurnover)}. Binding changes: ${row.bindingConstraintChanges.join(", ") || "None"}.`}><div className="text-xs font-semibold text-slate-700">{row.driver}: {row.direction}</div><div className="grid h-5 grid-cols-2 bg-slate-50"><div className="flex justify-end border-r border-slate-400">{value < 0 && <div className="h-full bg-emerald-500" style={{ width: `${Math.abs(value) / maximum * 100}%` }} />}</div><div>{value >= 0 && <div className="h-full bg-amber-500" style={{ width: `${Math.abs(value) / maximum * 100}%` }} />}</div></div><div className={`text-right text-xs font-bold ${value > 0 ? "text-amber-800" : "text-emerald-800"}`}>{value > 0 ? "+" : ""}{format(value)}</div></div>;
        })}
      </div>
      <div className="mt-3 text-center text-[10px] font-semibold uppercase text-slate-500">Change in total logistics cost</div>
    </ChartFrame>
  );
}

export function ResultKpi({ label, value, detail, tone = "neutral" }: { label: string; value: string; detail?: string; tone?: "neutral" | "success" | "warning" | "danger" }) {
  const classes = tone === "success" ? "border-emerald-200 bg-emerald-50" : tone === "warning" ? "border-amber-200 bg-amber-50" : tone === "danger" ? "border-red-200 bg-red-50" : "border-slate-200 bg-white";
  return <div className={`rounded-lg border p-3 ${classes}`}><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-lg font-bold text-slate-950">{value}</div>{detail && <div className="mt-1 text-xs text-slate-600">{detail}</div>}</div>;
}

export { format as formatTransportationValue, percent as formatTransportationPercent };
