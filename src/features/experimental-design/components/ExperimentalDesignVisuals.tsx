import { useId, useMemo } from "react";
import * as d3 from "d3";
import type {
  AnalysisResult,
  DesignResult,
  ExperimentalFactor,
  NuisanceFactor,
  PowerResult,
} from "../../../lib/experimentalDesignApi";
import { useReducedMotion } from "../../../visual-intelligence/useReducedMotion";

const ink = "#0f172a";
const muted = "#64748b";
const cyan = "#0891b2";
const amber = "#d97706";
const violet = "#7c3aed";

function EmptyVisual({ message }: { message: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-6 text-center text-sm text-slate-500">
      {message}
    </div>
  );
}

export function FactorStructureMap({
  factors,
  nuisance,
}: {
  factors: ExperimentalFactor[];
  nuisance: NuisanceFactor[];
}) {
  const reducedMotion = useReducedMotion();
  const nodes = useMemo(
    () => [
      ...factors.map((factor, index) => ({ id: factor.name, role: "factor", index, label: `${factor.name} · ${factor.levels.length} levels` })),
      ...nuisance.map((factor, index) => ({ id: factor.name, role: "nuisance", index, label: `${factor.name} · ${factor.strategy}` })),
    ],
    [factors, nuisance],
  );
  if (!nodes.length) return <EmptyVisual message="Add factors or nuisance variables to build the structure map." />;
  const width = 760;
  const height = Math.max(260, nodes.length * 46 + 70);
  const factorScale = d3.scalePoint<string>().domain(factors.map((factor) => factor.name)).range([64, height - 36]).padding(0.4);
  const nuisanceScale = d3.scalePoint<string>().domain(nuisance.map((factor) => factor.name)).range([64, height - 36]).padding(0.4);
  const responseY = height / 2;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Factor structure map connecting controllable and nuisance variables to the primary response"
      className="h-auto w-full"
      style={{ transitionDuration: reducedMotion ? "0ms" : "250ms" }}
    >
      <title>Factor structure map</title>
      <text x="28" y="28" fill={muted} fontSize="12" fontWeight="700">CONTROLLABLE FACTORS</text>
      <text x="520" y="28" fill={muted} fontSize="12" fontWeight="700">NUISANCE / BLOCKING</text>
      {factors.map((factor) => {
        const y = factorScale(factor.name) ?? responseY;
        return (
          <g key={`factor-${factor.factorId}`}>
            <path d={`M 224 ${y} C 300 ${y}, 315 ${responseY}, 370 ${responseY}`} fill="none" stroke="#67e8f9" strokeWidth="2" />
            <rect x="28" y={y - 17} width="196" height="34" rx="10" fill="#ecfeff" stroke="#a5f3fc" />
            <text x="42" y={y + 4} fill={ink} fontSize="12" fontWeight="650">{factor.name}</text>
            <text x="210" y={y + 4} fill={cyan} fontSize="11" textAnchor="end">{factor.levels.length}L</text>
          </g>
        );
      })}
      {nuisance.map((factor) => {
        const y = nuisanceScale(factor.name) ?? responseY;
        return (
          <g key={`nuisance-${factor.nuisanceId}`}>
            <path d={`M 520 ${y} C 470 ${y}, 465 ${responseY}, 438 ${responseY}`} fill="none" stroke="#fbbf24" strokeDasharray="5 4" strokeWidth="2" />
            <rect x="520" y={y - 17} width="212" height="34" rx="10" fill="#fffbeb" stroke="#fde68a" />
            <text x="534" y={y + 4} fill={ink} fontSize="12" fontWeight="650">{factor.name}</text>
          </g>
        );
      })}
      <rect x="370" y={responseY - 34} width="68" height="68" rx="20" fill="#0f172a" />
      <text x="404" y={responseY - 3} fill="white" fontSize="11" fontWeight="700" textAnchor="middle">PRIMARY</text>
      <text x="404" y={responseY + 13} fill="#a5f3fc" fontSize="11" fontWeight="700" textAnchor="middle">RESPONSE</text>
    </svg>
  );
}

export function PowerCurveChart({ result }: { result?: PowerResult }) {
  const gradientId = useId().replace(/:/g, "");
  if (!result?.curve?.length) return <EmptyVisual message="Calculate power to see the sample-size tradeoff curve." />;
  const width = 760;
  const height = 330;
  const margin = { top: 26, right: 26, bottom: 52, left: 62 };
  const x = d3.scaleLinear().domain(d3.extent(result.curve, (row) => row.total) as [number, number]).nice().range([margin.left, width - margin.right]);
  const y = d3.scaleLinear().domain([0, 1]).range([height - margin.bottom, margin.top]);
  const line = d3.line<(typeof result.curve)[number]>().x((row) => x(row.total)).y((row) => y(row.power)).curve(d3.curveMonotoneX);
  const area = d3.area<(typeof result.curve)[number]>().x((row) => x(row.total)).y0(y(0)).y1((row) => y(row.power)).curve(d3.curveMonotoneX);
  const xTicks = x.ticks(6);
  const yTicks = y.ticks(5);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Power curve by total sample size" className="h-auto w-full">
      <title>Power by total sample size</title>
      <defs>
        <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.32" />
          <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.03" />
        </linearGradient>
      </defs>
      {yTicks.map((tick) => (
        <g key={`y-${tick}`}>
          <line x1={margin.left} x2={width - margin.right} y1={y(tick)} y2={y(tick)} stroke="#e2e8f0" />
          <text x={margin.left - 12} y={y(tick) + 4} fill={muted} fontSize="11" textAnchor="end">{Math.round(tick * 100)}%</text>
        </g>
      ))}
      {xTicks.map((tick) => (
        <text key={`x-${tick}`} x={x(tick)} y={height - margin.bottom + 24} fill={muted} fontSize="11" textAnchor="middle">{d3.format(",")(tick)}</text>
      ))}
      <line x1={margin.left} x2={width - margin.right} y1={y(result.assumptions.targetPower as number)} y2={y(result.assumptions.targetPower as number)} stroke={amber} strokeDasharray="6 4" />
      <text x={width - margin.right} y={y(result.assumptions.targetPower as number) - 7} fill={amber} fontSize="11" textAnchor="end">Target power</text>
      <path d={area(result.curve) ?? ""} fill={`url(#${gradientId})`} />
      <path d={line(result.curve) ?? ""} fill="none" stroke={cyan} strokeWidth="3" />
      {result.curve.map((row) => (
        <circle key={`${row.total}-${row.power}`} cx={x(row.total)} cy={y(row.power)} r="3.5" fill="white" stroke={cyan} strokeWidth="2">
          <title>{`${row.total.toLocaleString()} total · ${(row.power * 100).toFixed(1)}% power`}</title>
        </circle>
      ))}
      <circle cx={x(result.totalSample)} cy={y(result.achievedPower)} r="7" fill={violet} stroke="white" strokeWidth="3">
        <title>{`Recommended: ${result.totalSample.toLocaleString()} total observations`}</title>
      </circle>
      <text x={width / 2} y={height - 8} fill={ink} fontSize="12" fontWeight="650" textAnchor="middle">Total sample size</text>
      <text transform={`translate(16 ${height / 2}) rotate(-90)`} fill={ink} fontSize="12" fontWeight="650" textAnchor="middle">Statistical power</text>
    </svg>
  );
}

export function DesignMatrixChart({ design }: { design?: DesignResult }) {
  if (!design?.rows?.length) return <EmptyVisual message="Generate the design to see treatment coverage and coded settings." />;
  const rows = design.rows.slice(0, 80);
  const factors = design.factorNames;
  const width = 760;
  const left = 120;
  const top = 54;
  const cellWidth = Math.min(118, Math.max(58, (width - left - 20) / Math.max(1, factors.length)));
  const cellHeight = Math.min(14, Math.max(6, 320 / rows.length));
  const height = top + rows.length * cellHeight + 36;
  const color = d3.scaleSequential(d3.interpolateRdYlBu).domain([1, -1]);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Coded experimental design matrix heatmap" className="h-auto w-full">
      <title>Coded design matrix</title>
      {factors.map((factor, column) => (
        <text key={factor} x={left + column * cellWidth + cellWidth / 2} y={38} fill={ink} fontSize="11" fontWeight="700" textAnchor="middle">
          {factor.length > 16 ? `${factor.slice(0, 14)}…` : factor}
        </text>
      ))}
      {rows.map((row, rowIndex) => (
        <g key={String(row.runId)}>
          <text x={left - 10} y={top + rowIndex * cellHeight + cellHeight * 0.75} fill={muted} fontSize={Math.max(7, Math.min(10, cellHeight - 1))} textAnchor="end">{String(row.runId)}</text>
          {factors.map((factor, column) => {
            const coded = Number((row._coded as Record<string, number> | undefined)?.[factor] ?? 0);
            return (
              <rect
                key={`${row.runId}-${factor}`}
                x={left + column * cellWidth}
                y={top + rowIndex * cellHeight}
                width={cellWidth - 2}
                height={Math.max(2, cellHeight - 1)}
                rx="2"
                fill={color(Math.max(-1, Math.min(1, coded)))}
              >
                <title>{`${row.runId} · ${factor}: ${String(row[factor])} (coded ${coded.toFixed(2)})`}</title>
              </rect>
            );
          })}
        </g>
      ))}
      {design.rows.length > rows.length ? <text x={left} y={height - 8} fill={muted} fontSize="11">{`Showing first ${rows.length} of ${design.rows.length} runs; exact table remains complete.`}</text> : null}
    </svg>
  );
}

export function AliasMap({ design }: { design?: DesignResult }) {
  const aliases = design?.aliasStructure ?? [];
  if (!aliases.length) return <EmptyVisual message="This design has no declared fractional-factor alias links." />;
  const width = 760;
  const rowHeight = 58;
  const height = Math.max(220, aliases.length * rowHeight + 38);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Alias structure map" className="h-auto w-full">
      <title>Fractional-factorial alias map</title>
      {aliases.map((alias, index) => {
        const y = 34 + index * rowHeight;
        return (
          <g key={`${alias.effect}-${index}`}>
            <path d={`M 220 ${y} C 305 ${y}, 340 ${y}, 430 ${y}`} fill="none" stroke="#c4b5fd" strokeWidth="3" />
            <rect x="28" y={y - 18} width="192" height="36" rx="10" fill="#f5f3ff" stroke="#ddd6fe" />
            <text x="44" y={y + 4} fill={violet} fontSize="12" fontWeight="750">{alias.effect}</text>
            <rect x="430" y={y - 18} width="302" height="36" rx="10" fill="#fff7ed" stroke="#fed7aa" />
            <text x="446" y={y + 4} fill="#9a3412" fontSize="12" fontWeight="650">{alias.aliasedWith}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function EffectParetoChart({ analysis }: { analysis?: AnalysisResult }) {
  const effects = analysis?.effects?.slice(0, 14) ?? [];
  if (!effects.length) return <EmptyVisual message="Analyze observed responses to rank main and interaction effects." />;
  const width = 760;
  const height = Math.max(260, effects.length * 34 + 70);
  const margin = { top: 22, right: 45, bottom: 34, left: 180 };
  const max = d3.max(effects, (effect) => Math.abs(effect.estimate)) || 1;
  const x = d3.scaleLinear().domain([0, max]).nice().range([margin.left, width - margin.right]);
  const y = d3.scaleBand().domain(effects.map((effect) => effect.term)).range([margin.top, height - margin.bottom]).padding(0.24);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Pareto chart of observed standardized effect magnitudes" className="h-auto w-full">
      <title>Observed effect magnitude ranking</title>
      {effects.map((effect) => (
        <g key={effect.term}>
          <text x={margin.left - 12} y={(y(effect.term) ?? 0) + y.bandwidth() / 2 + 4} fill={ink} fontSize="11" textAnchor="end">{effect.term}</text>
          <rect x={margin.left} y={y(effect.term)} width={Math.max(1, x(Math.abs(effect.estimate)) - margin.left)} height={y.bandwidth()} rx="5" fill={effect.kind === "main_effect" ? cyan : violet}>
            <title>{`${effect.term}: ${effect.estimate.toFixed(4)}`}</title>
          </rect>
          <text x={x(Math.abs(effect.estimate)) + 7} y={(y(effect.term) ?? 0) + y.bandwidth() / 2 + 4} fill={muted} fontSize="10">{effect.estimate.toFixed(3)}</text>
        </g>
      ))}
    </svg>
  );
}

export function ResidualPlot({ analysis }: { analysis?: AnalysisResult }) {
  const points = analysis?.residualDiagnostics?.points ?? [];
  if (!points.length) return <EmptyVisual message="Residual diagnostics appear after observed-response analysis." />;
  const width = 760;
  const height = 320;
  const margin = { top: 24, right: 28, bottom: 48, left: 60 };
  const xExtent = d3.extent(points, (point) => point.fitted) as [number, number];
  const yExtent = d3.extent(points, (point) => point.residual) as [number, number];
  const x = d3.scaleLinear().domain(xExtent[0] === xExtent[1] ? [xExtent[0] - 1, xExtent[1] + 1] : xExtent).nice().range([margin.left, width - margin.right]);
  const symmetric = Math.max(Math.abs(yExtent[0] || 0), Math.abs(yExtent[1] || 0), 1e-6);
  const y = d3.scaleLinear().domain([-symmetric, symmetric]).nice().range([height - margin.bottom, margin.top]);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Residuals versus fitted values" className="h-auto w-full">
      <title>Residuals versus fitted values</title>
      <line x1={margin.left} x2={width - margin.right} y1={y(0)} y2={y(0)} stroke={amber} strokeDasharray="6 4" />
      {points.map((point, index) => (
        <circle key={`${point.fitted}-${point.residual}-${index}`} cx={x(point.fitted)} cy={y(point.residual)} r="4" fill={cyan} opacity="0.72">
          <title>{`Fitted ${point.fitted.toFixed(3)} · residual ${point.residual.toFixed(3)}`}</title>
        </circle>
      ))}
      <text x={width / 2} y={height - 9} fill={ink} fontSize="12" fontWeight="650" textAnchor="middle">Fitted response</text>
      <text transform={`translate(16 ${height / 2}) rotate(-90)`} fill={ink} fontSize="12" fontWeight="650" textAnchor="middle">Residual</text>
    </svg>
  );
}
