import type { DecisionJournalEntry } from "./decisionJournal";
import { sanitizeReportHtml } from "./htmlSanitizer";

export function escapeHtml(value: unknown) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function atlasReportStyles() {
  return `
    .atlas-report { color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; line-height: 1.55; }
    .atlas-report h1 { margin: 0 0 6px; font-size: 28px; letter-spacing: 0; }
    .atlas-report h2 { margin: 0 0 14px; color: #173b75; font-size: 18px; letter-spacing: 0; }
    .atlas-report h3 { margin: 0 0 10px; color: #1d4ed8; font-size: 16px; letter-spacing: 0; }
    .atlas-report p { margin: 0 0 12px; font-size: 14px; }
    .atlas-report .meta { color: #64748b; margin-bottom: 28px; }
    .atlas-report section { break-inside: avoid; background: #ffffff; border: 1px solid #dbe3ef; border-radius: 12px; margin: 0 0 22px; padding: 20px; }
    .atlas-section-summary { background: #eff6ff; border: 1px solid #bfdbfe; border-left: 4px solid #2563eb; border-radius: 10px; color: #1e3a8a; margin: 10px 0 16px; padding: 14px 16px; }
    .atlas-section-summary strong { display: block; color: #173b75; font-size: 15px; margin-bottom: 4px; }
    .atlas-table-card { background: #ffffff; border: 1px solid #dbe3ef; border-radius: 12px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); margin: 16px 0 24px; overflow: hidden; }
    .atlas-table-scroll { max-width: 100%; overflow-x: auto; }
    .atlas-report-table { border-collapse: separate; border-spacing: 0; font-size: 14px; min-width: 760px; table-layout: fixed; text-align: left; width: 100%; }
    .atlas-report-table.compact { min-width: 520px; }
    .atlas-report-table.wide { min-width: 1180px; }
    .atlas-report-table thead th { background: #f8fafc; border-bottom: 1px solid #dbe3ef; color: #1e3a8a; font-size: 12px; font-weight: 700; letter-spacing: .02em; padding: 12px 14px; position: sticky; text-align: left; text-transform: uppercase; top: 0; z-index: 1; }
    .atlas-report-table tbody td { border-top: 1px solid #edf2f7; color: #243447; padding: 12px 14px; text-align: left; vertical-align: top; white-space: normal; word-break: normal; overflow-wrap: anywhere; }
    .atlas-report-table tbody tr:nth-child(even) td { background: #f8fafc; }
    .atlas-report-table tbody tr:hover td { background: #eef6ff; }
    .atlas-badge { border-radius: 999px; display: inline-block; font-size: 12px; font-weight: 700; line-height: 1; padding: 5px 9px; white-space: nowrap; }
    .atlas-badge-success { background: #dcfce7; color: #166534; }
    .atlas-badge-warning { background: #fef3c7; color: #92400e; }
    .atlas-badge-neutral { background: #e0f2fe; color: #075985; }
    .atlas-badge-danger { background: #fee2e2; color: #991b1b; }
    .atlas-callout { border-radius: 12px; margin: 14px 0; padding: 14px 16px; }
    .atlas-callout.info { background: #eff6ff; border: 1px solid #bfdbfe; color: #1e3a8a; }
    .atlas-callout.warning { background: #fffbeb; border: 1px solid #fcd34d; color: #92400e; }
    .atlas-kpi-grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 16px 0 22px; }
    .atlas-kpi { background: #f8fafc; border: 1px solid #dbe3ef; border-radius: 10px; padding: 14px; }
    .atlas-kpi span { color: #64748b; display: block; font-size: 11px; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; }
    .atlas-kpi strong { color: #0f172a; display: block; font-size: 20px; margin-top: 5px; }
    .atlas-timeline { margin: 16px 0 24px; position: relative; }
    .atlas-timeline-item { display: grid; gap: 12px; grid-template-columns: 18px 1fr; margin-bottom: 14px; }
    .atlas-timeline-dot { background: #2563eb; border: 3px solid #dbeafe; border-radius: 999px; height: 12px; margin-top: 9px; width: 12px; }
    .atlas-timeline-card { background: #ffffff; border: 1px solid #dbe3ef; border-radius: 12px; padding: 14px 16px; }
    .atlas-timeline-time { color: #64748b; font-size: 12px; font-weight: 700; margin-bottom: 5px; }
    .atlas-timeline-title { color: #0f172a; font-size: 15px; font-weight: 700; margin-bottom: 10px; }
    .atlas-audit-grid { display: grid; gap: 10px 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .atlas-audit-field span { color: #64748b; display: block; font-size: 11px; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; }
    .atlas-audit-field div { color: #243447; font-size: 14px; overflow-wrap: anywhere; }
    @media (max-width: 900px) { .atlas-audit-grid { grid-template-columns: 1fr; } .atlas-report section { padding: 16px; } }
    @media print {
      @page { margin: .5in; size: landscape; }
      .atlas-report { color: #111827; }
      .atlas-report section { break-inside: avoid; box-shadow: none; }
      .atlas-table-scroll { overflow: visible; }
      .atlas-report-table { min-width: 0; table-layout: auto; }
      .atlas-report-table thead th { position: static; }
    }
  `;
}

export function sectionSummaryHtml(title: string, body: string) {
  return `<div class="atlas-section-summary"><strong>${escapeHtml(title)}</strong>${escapeHtml(body)}</div>`;
}

export function statusBadgeHtml(value: unknown) {
  const label = String(value ?? "-");
  const normalized = label.toLowerCase();
  const tone = /complete|approved|pass|yes|champion|done|adequate/.test(normalized)
    ? "success"
    : /warning|draft|pending|review|not selected/.test(normalized)
      ? "warning"
      : /fail|error|missing|overrode|risk/.test(normalized)
        ? "danger"
        : "neutral";
  return `<span class="atlas-badge atlas-badge-${tone}">${escapeHtml(label)}</span>`;
}

export function professionalTableHtml(
  headers: string[],
  rows: unknown[][],
  options: { compact?: boolean; wide?: boolean; badgeColumns?: string[] } = {}
) {
  const tableClass = ["atlas-report-table", options.compact ? "compact" : "", options.wide ? "wide" : ""].filter(Boolean).join(" ");
  const badgeColumns = new Set((options.badgeColumns ?? []).map((column) => column.toLowerCase()));
  const headerHtml = headers.map((header) => `<th>${escapeHtml(header || "-")}</th>`).join("");
  const bodyHtml = rows
    .map(
      (row) =>
        `<tr>${headers
          .map((header, index) => {
            const raw = row[index] ?? "-";
            const content = badgeColumns.has(header.toLowerCase()) ? statusBadgeHtml(raw) : escapeHtml(raw);
            return `<td>${content}</td>`;
          })
          .join("")}</tr>`
    )
    .join("");
  return `<div class="atlas-table-card"><div class="atlas-table-scroll"><table class="${tableClass}"><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div></div>`;
}

export function objectTableHtml(value: unknown, fallback = "None documented") {
  if (!value || typeof value !== "object" || Array.isArray(value) || !Object.keys(value as Record<string, unknown>).length) {
    return fallback;
  }
  const rows = Object.entries(value as Record<string, unknown>).map(([key, raw]) => {
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      return [
        key,
        Object.entries(raw as Record<string, unknown>)
          .map(([field, fieldValue]) => `${field}: ${String(fieldValue ?? "-")}`)
          .join("; "),
      ];
    }
    return [key, String(raw ?? "-")];
  });
  return professionalTableHtml(["Item", "Details"], rows, { compact: true });
}

function splitTableLine(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.replace(/\\\|/g, "|").trim());
}

function isSeparatorLine(line: string) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function looksLikePipeTable(lines: string[], index: number) {
  return index + 1 < lines.length && lines[index].includes("|") && isSeparatorLine(lines[index + 1]);
}

function markdownTableToHtml(lines: string[], index: number) {
  const headers = splitTableLine(lines[index]);
  const rows: string[][] = [];
  let cursor = index + 2;
  while (cursor < lines.length && lines[cursor].includes("|") && lines[cursor].trim()) {
    rows.push(splitTableLine(lines[cursor]));
    cursor += 1;
  }
  const wide = headers.length >= 7;
  const badgeColumns = headers.filter((header) => /status|champion|decision|follow/i.test(header));
  return { html: professionalTableHtml(headers, rows, { wide, badgeColumns }), end: cursor };
}

function paragraphHtml(lines: string[]) {
  const text = lines.join("\n").trim();
  if (!text) return "";
  return `<p>${escapeHtml(text).replace(/\n/g, "<br />")}</p>`;
}

export function renderReportContentHtml(content: string) {
  const trimmed = content.trim();
  if (!trimmed) return "";
  if (trimmed.includes('class="atlas-') || /^<([a-z][\w-]*)(\s|>)/i.test(trimmed)) return sanitizeReportHtml(content);

  const lines = content.split(/\r?\n/);
  const parts: string[] = [];
  let pending: string[] = [];
  let index = 0;
  const flush = () => {
    const html = paragraphHtml(pending);
    if (html) parts.push(html);
    pending = [];
  };

  while (index < lines.length) {
    if (/^<([a-z][\w-]*)(\s|>)/i.test(lines[index].trim())) {
      flush();
      const firstHtmlLine = lines[index].trim();
      parts.push(lines[index]);
      index += 1;
      if (firstHtmlLine.includes("</")) {
        continue;
      }
      while (index < lines.length && lines[index].trim()) {
        parts.push(lines[index]);
        const currentLine = lines[index].trim();
        index += 1;
        if (currentLine.includes("</")) break;
      }
      continue;
    }
    if (looksLikePipeTable(lines, index)) {
      flush();
      const parsed = markdownTableToHtml(lines, index);
      parts.push(parsed.html);
      index = parsed.end;
      continue;
    }
    if (lines[index].trim().startsWith("- ")) {
      flush();
      const items: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith("- ")) {
        items.push(`<li>${escapeHtml(lines[index].trim().slice(2))}</li>`);
        index += 1;
      }
      parts.push(`<ul>${items.join("")}</ul>`);
      continue;
    }
    pending.push(lines[index]);
    index += 1;
  }
  flush();
  return sanitizeReportHtml(parts.join("\n"));
}

export function decisionJournalTimelineHtml(entries: DecisionJournalEntry[]) {
  if (!entries.length) return "No decision journal entries captured.";
  const sorted = [...entries].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  const items = sorted
    .slice(0, 250)
    .map((entry) => {
      const date = new Date(entry.timestamp);
      const dateText = Number.isNaN(date.getTime()) ? entry.timestamp : date.toLocaleString();
      return `
        <article class="atlas-timeline-item">
          <div class="atlas-timeline-dot"></div>
          <div class="atlas-timeline-card">
            <div class="atlas-timeline-time">${escapeHtml(dateText)}</div>
            <div class="atlas-timeline-title">${escapeHtml(entry.workflowStep)} updated</div>
            <div class="atlas-audit-grid">
              <div class="atlas-audit-field"><span>Action</span><div>${escapeHtml(entry.actionType.replace(/_/g, " "))}</div></div>
              <div class="atlas-audit-field"><span>Subject</span><div>${escapeHtml(entry.subject || "-")}</div></div>
              <div class="atlas-audit-field"><span>Previous</span><div>${escapeHtml(entry.previousValue || "-")}</div></div>
              <div class="atlas-audit-field"><span>New</span><div>${escapeHtml(entry.newValue || "-")}</div></div>
              <div class="atlas-audit-field"><span>Recommendation</span><div>${escapeHtml(entry.systemRecommendation || "-")}</div></div>
              <div class="atlas-audit-field"><span>Follow Status</span><div>${statusBadgeHtml(entry.followStatus || "unknown")}</div></div>
              <div class="atlas-audit-field"><span>Rationale</span><div>${escapeHtml(entry.userReason || "No user rationale captured.")}</div></div>
            </div>
          </div>
        </article>`;
    })
    .join("");
  return [
    sectionSummaryHtml(
      "Decision Journal Summary",
      `${entries.length} audit event${entries.length === 1 ? "" : "s"} were captured. The timeline below shows material workflow decisions in chronological order with prior value, new value, recommendation context, and rationale.`
    ),
    `<div class="atlas-timeline">${items}</div>`,
  ].join("\n");
}
