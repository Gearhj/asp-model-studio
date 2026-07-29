export type BoxPlotSeries = {
  id: string;
  label: string;
  count: number;
  minimum: number;
  q1: number;
  median: number;
  q3: number;
  maximum: number;
  whiskerLow: number;
  whiskerHigh: number;
  outlierCount?: number;
  color?: string;
};

type Props = {
  title: string;
  subtitle: string;
  series: BoxPlotSeries[];
  valueLabel: string;
  note?: string;
  dataTestId: string;
};

function formatValue(value: number) {
  return value.toLocaleString(undefined, {
    maximumFractionDigits: Math.abs(value) >= 1_000 ? 1 : 3,
  });
}

export default function StatisticalBoxPlot({
  title,
  subtitle,
  series,
  valueLabel,
  note,
  dataTestId,
}: Props) {
  const valid = series.filter((row) =>
    [
      row.minimum,
      row.q1,
      row.median,
      row.q3,
      row.maximum,
      row.whiskerLow,
      row.whiskerHigh,
    ].every(Number.isFinite),
  );
  if (!valid.length) return null;

  const observedMinimum = Math.min(...valid.map((row) => row.minimum));
  const observedMaximum = Math.max(...valid.map((row) => row.maximum));
  const observedSpan = observedMaximum - observedMinimum;
  const padding = observedSpan > 0 ? observedSpan * 0.04 : Math.max(1, Math.abs(observedMinimum) * 0.08);
  const domainMinimum = observedMinimum - padding;
  const domainMaximum = observedMaximum + padding;
  const domainSpan = domainMaximum - domainMinimum || 1;
  const plotLeft = 176;
  const plotRight = 860;
  const plotWidth = plotRight - plotLeft;
  const rowHeight = 78;
  const plotTop = 34;
  const axisY = plotTop + valid.length * rowHeight + 12;
  const height = axisY + 46;
  const x = (value: number) =>
    plotLeft + ((value - domainMinimum) / domainSpan) * plotWidth;
  const ticks = Array.from(
    { length: 5 },
    (_, index) => domainMinimum + (domainSpan * index) / 4,
  );
  const accessibleSummary = valid
    .map(
      (row) =>
        `${row.label}: Q1 ${formatValue(row.q1)}, median ${formatValue(row.median)}, Q3 ${formatValue(row.q3)}, ${row.outlierCount ?? 0} outliers`,
    )
    .join(". ");

  return (
    <section
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
      data-testid={dataTestId}
      aria-label={`${title}. ${accessibleSummary}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 bg-slate-50/80 px-4 py-3">
        <div>
          <h4 className="text-sm font-semibold text-slate-950">{title}</h4>
          <p className="mt-1 text-xs leading-5 text-slate-600">{subtitle}</p>
        </div>
        <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-slate-600">
          Exact summary statistics
        </span>
      </div>
      <div className="overflow-x-auto px-3 py-2">
        <svg
          className="min-w-[720px] w-full"
          viewBox={`0 0 900 ${height}`}
          role="img"
          aria-label={`${title}. ${accessibleSummary}`}
        >
          <title>{title}</title>
          <desc>{accessibleSummary}</desc>
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={x(tick)}
                x2={x(tick)}
                y1={plotTop - 10}
                y2={axisY}
                stroke="#e2e8f0"
                strokeWidth="1"
              />
              <text
                x={x(tick)}
                y={axisY + 17}
                textAnchor="middle"
                fill="#64748b"
                fontSize="10"
              >
                {formatValue(tick)}
              </text>
            </g>
          ))}
          {valid.map((row, index) => {
            const y = plotTop + index * rowHeight + 28;
            const color = row.color ?? "#2563eb";
            const outliers = Math.max(0, row.outlierCount ?? 0);
            return (
              <g key={row.id}>
                <title>
                  {row.label}: observed {formatValue(row.minimum)} to{" "}
                  {formatValue(row.maximum)}; Q1 {formatValue(row.q1)};
                  median {formatValue(row.median)}; Q3 {formatValue(row.q3)};
                  {` ${outliers.toLocaleString()} outliers`}
                </title>
                <text
                  x="10"
                  y={y - 5}
                  fill="#0f172a"
                  fontSize="12"
                  fontWeight="700"
                >
                  {row.label}
                </text>
                <text x="10" y={y + 13} fill="#64748b" fontSize="10">
                  {row.count.toLocaleString()} rows · {outliers.toLocaleString()} outliers
                </text>
                <line
                  x1={x(row.minimum)}
                  x2={x(row.maximum)}
                  y1={y}
                  y2={y}
                  stroke="#fda4af"
                  strokeWidth="2"
                  strokeDasharray="3 3"
                />
                <line
                  x1={x(row.whiskerLow)}
                  x2={x(row.whiskerHigh)}
                  y1={y}
                  y2={y}
                  stroke={color}
                  strokeWidth="2.5"
                />
                {[row.whiskerLow, row.whiskerHigh].map((value, capIndex) => (
                  <line
                    key={`${row.id}-cap-${capIndex}`}
                    x1={x(value)}
                    x2={x(value)}
                    y1={y - 13}
                    y2={y + 13}
                    stroke={color}
                    strokeWidth="2"
                  />
                ))}
                <rect
                  x={x(row.q1)}
                  y={y - 19}
                  width={Math.max(2, x(row.q3) - x(row.q1))}
                  height="38"
                  rx="4"
                  fill={color}
                  fillOpacity="0.22"
                  stroke={color}
                  strokeWidth="2"
                />
                <line
                  x1={x(row.median)}
                  x2={x(row.median)}
                  y1={y - 19}
                  y2={y + 19}
                  stroke={color}
                  strokeWidth="3"
                />
                <circle
                  cx={x(row.minimum)}
                  cy={y}
                  r="3"
                  fill="#e11d48"
                  aria-label={`Observed minimum ${formatValue(row.minimum)}`}
                />
                <circle
                  cx={x(row.maximum)}
                  cy={y}
                  r="3"
                  fill="#e11d48"
                  aria-label={`Observed maximum ${formatValue(row.maximum)}`}
                />
              </g>
            );
          })}
          <line
            x1={plotLeft}
            x2={plotRight}
            y1={axisY}
            y2={axisY}
            stroke="#94a3b8"
            strokeWidth="1"
          />
          <text
            x={(plotLeft + plotRight) / 2}
            y={axisY + 35}
            textAnchor="middle"
            fill="#475569"
            fontSize="11"
            fontWeight="600"
          >
            {valueLabel}
          </text>
        </svg>
      </div>
      {note ? (
        <p className="border-t border-slate-100 px-4 py-2.5 text-[11px] leading-5 text-slate-500">
          {note}
        </p>
      ) : null}
    </section>
  );
}
