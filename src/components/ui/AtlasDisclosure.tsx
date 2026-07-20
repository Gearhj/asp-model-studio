import type React from "react";
import { ChevronDown } from "lucide-react";

type AtlasDisclosureProps = {
  title: string;
  summary?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
};

export default function AtlasDisclosure({ title, summary, children, defaultOpen = false }: AtlasDisclosureProps) {
  return (
    <details className="rounded-lg border border-slate-200 bg-white shadow-sm" open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3">
        <span>
          <span className="block text-sm font-semibold text-slate-950">{title}</span>
          {summary && <span className="mt-1 block text-xs leading-5 text-slate-500">{summary}</span>}
        </span>
        <ChevronDown size={16} className="shrink-0 text-slate-500" aria-hidden="true" />
      </summary>
      <div className="border-t border-slate-200 p-4">{children}</div>
    </details>
  );
}
