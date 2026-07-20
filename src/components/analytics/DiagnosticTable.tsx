import type { AnalyticalTable } from "../../types/analyticsEngine";

export function DiagnosticTable({ table }: { table: AnalyticalTable }) {
  return <div className="overflow-auto rounded-lg border border-slate-200 bg-white"><table className="min-w-full text-left text-xs"><thead className="bg-slate-950 text-slate-100"><tr>{table.columns.map((column) => <th key={column} className="whitespace-nowrap px-3 py-2 font-semibold">{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody className="divide-y divide-slate-100">{table.rows.slice(0, 250).map((row, index) => <tr key={index}>{table.columns.map((column) => <td key={column} className="whitespace-nowrap px-3 py-2 text-slate-700">{String(row[column] ?? "-")}</td>)}</tr>)}</tbody></table></div>;
}
