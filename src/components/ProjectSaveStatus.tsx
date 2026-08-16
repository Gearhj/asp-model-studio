import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Cloud, Loader2 } from "lucide-react";
import { PROJECT_SAVE_STATUS_EVENT, type ProjectSaveStatusDetail } from "../lib/projectPersistence";

function defaultStatus(): ProjectSaveStatusDetail {
  return {
    status: "local_only",
    message: "Browser persistence is active. Sports project synchronization is available through the isolated local database.",
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
  const isError = detail.status === "save_failed" || detail.status === "database_save_failed";
  const isUnavailable = detail.status === "backend_unavailable";
  const isPartial = detail.status === "partial_restore" || detail.status === "registry_warning" || isUnavailable;
  const isSaved = detail.status === "database_saved";
  const Icon = isSaving ? Loader2 : isError || isPartial ? AlertTriangle : isSaved ? CheckCircle2 : Cloud;
  const label =
    detail.status === "saving"
      ? "Saving"
      : detail.status === "save_failed" || detail.status === "database_save_failed"
        ? "Save failed"
        : detail.status === "backend_unavailable"
          ? "Backend unavailable"
        : detail.status === "database_saved"
          ? "Saved to local database"
        : detail.status === "local_only" || detail.status === "saved" || detail.status === "restored"
          ? "Local only"
        : detail.status === "registry_warning"
          ? "Local only"
          : detail.status === "partial_restore"
            ? "Partial restore"
            : "Local only";

  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs font-semibold shadow-sm ${
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
