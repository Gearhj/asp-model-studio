import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Cloud, Loader2 } from "lucide-react";
import { PROJECT_SAVE_STATUS_EVENT, type ProjectSaveStatusDetail } from "../lib/projectPersistence";

function defaultStatus(): ProjectSaveStatusDetail {
  return {
    status: "unsaved",
    message: "No project snapshot saved in this session yet.",
  };
}

function formatTime(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

export default function ProjectSaveStatus() {
  const [detail, setDetail] = useState<ProjectSaveStatusDetail>(() => defaultStatus());

  useEffect(() => {
    const listener = (event: Event) => {
      const custom = event as CustomEvent<ProjectSaveStatusDetail>;
      if (custom.detail) setDetail(custom.detail);
    };
    window.addEventListener(PROJECT_SAVE_STATUS_EVENT, listener);
    return () => window.removeEventListener(PROJECT_SAVE_STATUS_EVENT, listener);
  }, []);

  const isSaving = detail.status === "saving";
  const isError = detail.status === "save_failed";
  const isPartial = detail.status === "partial_restore";
  const isSaved = detail.status === "saved" || detail.status === "restored";
  const Icon = isSaving ? Loader2 : isError || isPartial ? AlertTriangle : isSaved ? CheckCircle2 : Cloud;
  const label =
    detail.status === "saving"
      ? "Saving"
      : detail.status === "save_failed"
        ? "Save failed"
        : detail.status === "partial_restore"
          ? "Partial restore"
          : detail.status === "restored"
            ? "Restored"
            : detail.status === "saved"
              ? "Saved"
              : "Unsaved";

  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold shadow-sm ${
        isError
          ? "border-red-200 bg-red-50 text-red-800"
          : isPartial
            ? "border-amber-200 bg-amber-50 text-amber-800"
            : isSaved
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-slate-200 bg-white text-slate-600"
      }`}
      title={detail.message}
    >
      <Icon size={13} className={isSaving ? "animate-spin" : ""} />
      <span>{label}</span>
      {detail.savedAt && <span className="font-medium opacity-80">{formatTime(detail.savedAt)}</span>}
    </div>
  );
}
