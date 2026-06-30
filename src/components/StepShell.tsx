import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Info, Lightbulb } from "lucide-react";
import { getAdaptiveRecommendations, type AdaptiveRecommendation } from "../lib/adaptiveWorkflow";
import { useWorkflowStore } from "../state/useWorkflowStore";
import StepPythonPanel from "./StepPythonPanel";

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
  const adaptiveRecommendations = getAdaptiveRecommendations(location.pathname);

  const handleNext = async () => {
    if (onNext) {
      await onNext();
    }

    const currentStep = location.pathname.replace("/", "");
    if (/^step(?:0[0-9]|1[01])$/.test(currentStep) || currentStep === "step01b" || currentStep === "dashboard") {
      markComplete(currentStep as Parameters<typeof markComplete>[0]);
    }

    if (nextPath) navigate(nextPath);
  };

  return (
    <div className="w-full space-y-5">
      <div className="pt-2">
        <h1 className="text-xl font-semibold text-gray-900">{title}</h1>
        {subtitle && <p className="text-gray-600 mt-1">{subtitle}</p>}
      </div>

      {!!adaptiveRecommendations.length && (
        <div className="grid gap-3">
          {adaptiveRecommendations.map((recommendation) => (
            <AdaptiveRecommendationBanner key={`${recommendation.kind}-${recommendation.headline}`} recommendation={recommendation} />
          ))}
        </div>
      )}

      <div>{children}</div>

      <StepPythonPanel />

      <div className="flex justify-center pb-12 pt-2">
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

function AdaptiveRecommendationBanner({ recommendation }: { recommendation: AdaptiveRecommendation }) {
  const Icon =
    recommendation.kind === "warning"
      ? AlertTriangle
      : recommendation.kind === "skip"
        ? CheckCircle2
        : recommendation.kind === "default"
          ? Lightbulb
          : Info;

  const classes =
    recommendation.kind === "warning"
      ? "border-amber-200 bg-amber-50 text-amber-950"
      : recommendation.kind === "skip"
        ? "border-emerald-200 bg-emerald-50 text-emerald-950"
        : recommendation.kind === "review"
          ? "border-blue-200 bg-blue-50 text-blue-950"
          : "border-violet-200 bg-violet-50 text-violet-950";

  return (
    <section className={`rounded-lg border px-4 py-3 shadow-sm ${classes}`}>
      <div className="flex items-start gap-3">
        <Icon size={18} className="mt-0.5 shrink-0" />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold">{recommendation.headline}</h2>
            <span className="rounded-full bg-white/70 px-2 py-0.5 text-[11px] font-semibold">
              {Math.round(recommendation.confidence * 100)}% confidence
            </span>
          </div>
          <p className="mt-1 text-sm leading-6">{recommendation.explanation}</p>
          <p className="mt-2 text-xs leading-5 opacity-85">
            <span className="font-semibold">Suggested action: </span>
            {recommendation.suggestedAction}
          </p>
          <p className="mt-1 text-xs leading-5 opacity-85">
            <span className="font-semibold">Why this matters: </span>
            {recommendation.why}
          </p>
        </div>
      </div>
    </section>
  );
}
