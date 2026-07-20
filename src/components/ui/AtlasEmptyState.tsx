import type React from "react";

type AtlasEmptyStateProps = {
  title: string;
  body?: string;
  action?: React.ReactNode;
};

export default function AtlasEmptyState({ title, body, action }: AtlasEmptyStateProps) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-5 py-6 text-center">
      <div className="text-sm font-semibold text-slate-950">{title}</div>
      {body && <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-600">{body}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
