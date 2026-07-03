import React, { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { upsertProjectFromState } from "../lib/localProjects";
import { useWorkflowStore } from "../state/useWorkflowStore";
import StepPythonPanel from "./StepPythonPanel";

type Props = {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  nextDisabled?: boolean;
  nextLabel?: string;
  /** Optional pre-navigation task (persist/validate). Throw to block navigation. */
  onNext?: () => void | boolean | Promise<void | boolean>;
  /** Where to navigate on click, e.g. "/step05" */
  nextPath?: string;
};

export default function StepShell({
  title,
  subtitle,
  children,
  nextDisabled,
  nextLabel = "Mark Complete & Next Step",
  onNext,
  nextPath,
}: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const markComplete = useWorkflowStore((state) => state.markComplete);
  const getNextStepPath = useWorkflowStore((state) => state.getNextStepPath);
  const [navigationError, setNavigationError] = useState<string | null>(null);

  const handleNext = async () => {
    setNavigationError(null);
    try {
      if (onNext) {
        const result = await onNext();
        if (result === false) return;
      }

      const currentStep = location.pathname.replace("/", "");
      let targetPath = nextPath;
      if (/^step(?:0[0-9]|1[0-3])$/.test(currentStep) || currentStep === "step01b" || currentStep === "dashboard") {
        markComplete(currentStep as Parameters<typeof markComplete>[0]);
        targetPath = targetPath ?? getNextStepPath(currentStep as Parameters<typeof markComplete>[0]);
      }

      upsertProjectFromState(useWorkflowStore.getState());

      if (targetPath) {
        navigate(targetPath);
        window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
      }
    } catch (error) {
      console.error("ATLAS navigation/save failed", error);
      setNavigationError(error instanceof Error ? error.message : "ATLAS could not save and navigate. Please try again.");
    }
  };

  return (
    <div className="w-full space-y-5">
      {(title || subtitle) && (
        <div className="pt-2">
          {title && <h1 className="text-xl font-semibold text-gray-900">{title}</h1>}
          {subtitle && <p className="text-gray-600 mt-1">{subtitle}</p>}
        </div>
      )}

      <div>{children}</div>

      {navigationError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900 shadow-sm">
          <div className="flex items-start gap-2">
            <AlertTriangle size={17} className="mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">ATLAS could not save this page.</div>
              <div className="mt-1">{navigationError}</div>
            </div>
          </div>
        </div>
      )}

      <StepPythonPanel />

      <div className="flex justify-center pb-14 pt-7">
        <button
          data-step-next-button="true"
          className={
            nextDisabled
              ? "min-w-64 rounded-xl bg-indigo-300 px-7 py-3 text-sm font-semibold text-white shadow-sm cursor-not-allowed"
              : "min-w-64 rounded-xl bg-indigo-600 px-7 py-3 text-sm font-semibold text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-indigo-700 hover:shadow-md"
          }
          disabled={!!nextDisabled}
          onClick={handleNext}
          title={nextDisabled ? "Complete required actions first" : nextLabel}
        >
          {nextLabel}
        </button>
      </div>
    </div>
  );
}
