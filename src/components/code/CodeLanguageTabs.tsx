import type { CodeLanguage } from "../../lib/codeExecution";

export type CodeWorkspaceLanguage = CodeLanguage | "metadata";

const LABELS: Record<CodeWorkspaceLanguage, string> = {
  python: "Python",
  sql: "SQL",
  r: "R",
  sas: "SAS",
  metadata: "Metadata",
};

export function CodeLanguageTabs({ active, onChange, badges, languages }: { active: CodeWorkspaceLanguage; onChange: (language: CodeWorkspaceLanguage) => void; badges: Partial<Record<CodeWorkspaceLanguage, string>>; languages: CodeWorkspaceLanguage[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {languages.map((language) => (
        <button
          key={language}
          type="button"
          onClick={() => onChange(language)}
          className={`rounded-lg border px-3 py-2 text-sm font-semibold ${active === language ? "border-blue-300 bg-blue-50 text-blue-900" : "border-slate-200 bg-white text-slate-700 hover:border-blue-200"}`}
        >
          {LABELS[language]}
          <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-600">{badges[language] ?? "Configured"}</span>
        </button>
      ))}
    </div>
  );
}
