import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useWorkflowStore } from "../state/useWorkflowStore";

type Props = {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  nextDisabled?: boolean;
  nextLabel?: string;
  /** Optional pre-navigation task (persist/validate). Throw to block navigation. */
  onNext?: () => void | Promise<void>;
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

  const handleNext = async () => {
    if (onNext) {
      await onNext();
    }

    const currentStep = location.pathname.replace("/", "");
    if (/^step0[1-9]$/.test(currentStep) || currentStep === "dashboard") {
      markComplete(currentStep as Parameters<typeof markComplete>[0]);
    }

    if (nextPath) navigate(nextPath);
  };

  return (
    <div className="w-full">
      <div className="mx-4 md:px-8 py-6">
        <h1 className="text-xl font-semibold text-gray-900">{title}</h1>
        {subtitle && <p className="text-gray-600 mt-1">{subtitle}</p>}
      </div>

      <div className="mx-4 md:px-8">{children}</div>

      <div className="mx-4 md:px-8 flex justify-center mt-8 mb-12">
        <button
          data-step-next-button="true"
          className={
            nextDisabled
              ? "px-4 py-2 rounded-lg text-white bg-indigo-300 cursor-not-allowed"
              : "px-4 py-2 rounded-lg text-white bg-indigo-600 hover:bg-indigo-700"
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
