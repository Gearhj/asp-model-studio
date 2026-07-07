import type { CodeLanguage } from "../../lib/codeExecution";

const LABELS: Record<CodeLanguage, string> = {
  python: "Python",
  sql: "SQL",
  r: "R",
  sas: "SAS",
};

export function CodeLanguageTabs({ active, onChange, badges }: { active: CodeLanguage; onChange: (language: CodeLanguage) => void; badges: Record<CodeLanguage, string> }) {
  return (
    <div className="flex flex-wrap gap-2">
      {(Object.keys(LABELS) as CodeLanguage[]).map((language) => (
        <button
          key={language}
          type="button"
          onClick={() => onChange(language)}
          className={`rounded-lg border px-3 py-2 text-sm font-semibold ${active === language ? "border-blue-300 bg-blue-50 text-blue-900" : "border-slate-200 bg-white text-slate-700 hover:border-blue-200"}`}
        >
          {LABELS[language]}
          <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-600">{badges[language]}</span>
        </button>
      ))}
    </div>
  );
}

