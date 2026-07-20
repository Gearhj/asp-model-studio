import type { AnalyticalResult } from "../../types/analyticsEngine";

export function InterpretationPanel({ result }: { result: AnalyticalResult }) {
  if (!result.interpretations.length && !result.warnings.length) return null;
  return <div className="grid gap-2">{result.interpretations.map((item, index) => <div key={`${item.title}-${index}`} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950"><strong>{item.title}:</strong> {item.finding}{item.recommended_action ? ` ${item.recommended_action}` : ""}</div>)}{result.warnings.filter((item) => item.message).map((item, index) => <div key={`${item.message}-${index}`} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">{item.message}</div>)}</div>;
}
