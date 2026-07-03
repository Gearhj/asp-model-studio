import { atlasReportStyles, professionalTableHtml, renderReportContentHtml } from "../lib/reportFormatting";

type ParsedTable = {
  headers: string[];
  rows: string[][];
};

function isSeparatorLine(line: string) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function splitTableLine(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.replace(/\\\|/g, "|").trim());
}

function parseMarkdownTable(lines: string[], start: number): { table: ParsedTable; end: number } | null {
  if (start + 1 >= lines.length || !lines[start].includes("|") || !isSeparatorLine(lines[start + 1])) return null;
  const headers = splitTableLine(lines[start]);
  const rows: string[][] = [];
  let index = start + 2;
  while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
    rows.push(splitTableLine(lines[index]));
    index += 1;
  }
  return { table: { headers, rows }, end: index };
}

function flattenJsonRows(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>).map(([key, raw]) => {
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      const fields = raw as Record<string, unknown>;
      return {
        item: key,
        details: Object.entries(fields)
          .map(([field, fieldValue]) => `${field}: ${String(fieldValue ?? "-")}`)
          .join("; "),
      };
    }
    return { item: key, details: String(raw ?? "-") };
  });
}

function tryParseJsonObject(content: string) {
  try {
    const parsed = JSON.parse(content);
    const rows = flattenJsonRows(parsed);
    return rows.length ? rows : null;
  } catch {
    return null;
  }
}

function ReportTable({ table }: { table: ParsedTable }) {
  return (
    <div className="my-3 overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full border-collapse text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {table.headers.map((header, index) => (
              <th key={`${header}-${index}`} className="border-b border-slate-200 px-3 py-2 font-semibold">
                {header || "-"}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-t border-slate-100">
              {table.headers.map((_, cellIndex) => (
                <td key={cellIndex} className="px-3 py-2 align-top text-slate-700">
                  {row[cellIndex] || "-"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JsonTable({ rows }: { rows: { item: string; details: string }[] }) {
  return (
    <ReportTable
      table={{
        headers: ["Item", "Details"],
        rows: rows.map((row) => [row.item, row.details]),
      }}
    />
  );
}

function NarrativeBlock({ lines }: { lines: string[] }) {
  const text = lines.join("\n").trim();
  if (!text) return null;
  return <p className="my-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{text}</p>;
}

export default function ReportSectionContent({ content }: { content: string }) {
  const jsonRows = tryParseJsonObject(content.trim());
  const html = jsonRows
    ? professionalTableHtml(["Item", "Details"], jsonRows.map((row) => [row.item, row.details]), { compact: true })
    : renderReportContentHtml(content);

  if (html) {
    return (
      <div className="atlas-report">
        <style>{atlasReportStyles()}</style>
        <div dangerouslySetInnerHTML={{ __html: html }} />
      </div>
    );
  }

  const lines = content.split(/\r?\n/);
  const rendered: JSX.Element[] = [];
  let pendingText: string[] = [];
  let index = 0;

  const flushText = () => {
    if (!pendingText.some((line) => line.trim())) {
      pendingText = [];
      return;
    }
    rendered.push(<NarrativeBlock key={`text-${rendered.length}`} lines={pendingText} />);
    pendingText = [];
  };

  while (index < lines.length) {
    const parsed = parseMarkdownTable(lines, index);
    if (parsed) {
      flushText();
      rendered.push(<ReportTable key={`table-${rendered.length}`} table={parsed.table} />);
      index = parsed.end;
    } else {
      pendingText.push(lines[index]);
      index += 1;
    }
  }
  flushText();

  return <div>{rendered.length ? rendered : <NarrativeBlock lines={[content]} />}</div>;
}
