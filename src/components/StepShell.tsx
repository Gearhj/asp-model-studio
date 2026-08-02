import React, { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { createSnapshotFromState, saveActiveProjectBeforeNavigation } from "../lib/localProjects";
import { saveWorkflowStateToDatabase } from "../lib/serverPersistence";
import { useWorkflowStore } from "../state/useWorkflowStore";
import {
  resolveWorkflowActionBarBounds,
  workflowActionBarClearance,
  type WorkflowActionBarBounds,
} from "../lib/workflowActionBarLayout";
import StepPythonPanel from "./StepPythonPanel";
import ErrorBoundary from "./ErrorBoundary";
import {
  AtlasWorkflowHero,
  type AtlasWorkflowMetric,
  type AtlasWorkflowVariant,
} from "./ui/AtlasWorkflow";

const creditRiskStepByPredictiveRoute: Record<string, string> = {
  "/step00": "project-context",
  "/step01": "data-acquisition",
  "/step01b": "credit-bureau-data-review",
  "/step02": "eda",
  "/step03": "outliers",
  "/step04": "missing-values",
  "/step05": "feature-engineering",
  "/step06": "balance-split",
  "/step07": "model-training",
  "/step08": "evaluation",
  "/step09": "interpretation",
  "/step10": "scoring",
  "/step11": "documentation-review",
  "/step12": "model-implementation",
  "/step13": "model-monitoring",
};

function preserveCreditRiskStudioRoute(targetPath?: string) {
  if (!targetPath || window.location.pathname !== "/credit-risk-studio") return targetPath;
  const slug = creditRiskStepByPredictiveRoute[targetPath];
  return slug ? `/credit-risk-studio?step=${slug}` : targetPath;
}

type Props = {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  nextDisabled?: boolean;
  nextDisabledReason?: string;
  nextLabel?: string;
  /** Optional pre-navigation task (persist/validate). Throw to block navigation. */
  onNext?: () => void | boolean | Promise<void | boolean>;
  /** Optional direct click handler for workflows that need to own the visible button behavior. */
  onNextClick?: React.MouseEventHandler<HTMLButtonElement>;
  nextButtonTestId?: string;
  nextFooterTestId?: string;
  nextStatusTestId?: string;
  nextStatusLine?: React.ReactNode;
  /** Optional page-specific actions displayed in the sticky workflow bar. */
  nextExtraActions?: React.ReactNode;
  nextDebugPanel?: React.ReactNode;
  /** Where to navigate on click, e.g. "/step05" */
  nextPath?: string;
  /** Explicit workflow step for embedded routes whose pathname does not identify the active step. */
  workflowStepId?: Parameters<ReturnType<typeof useWorkflowStore.getState>["markComplete"]>[0];
  variant?: AtlasWorkflowVariant;
  eyebrow?: string;
  heroMetrics?: AtlasWorkflowMetric[];
  heroAction?: React.ReactNode;
  hideHeader?: boolean;
  /** Project Context is intentionally concise and does not expose page-level code tools. */
  showDeveloperTools?: boolean;
  /** Keep the workflow action available when this step is rendered inside Credit Risk Studio. */
  showEmbeddedNext?: boolean;
  /** Pin the workflow action to the viewport instead of placing it after long page content. */
  nextAlwaysVisible?: boolean;
  /** Require the exact completed workflow snapshot to be durably accepted before navigation. */
  nextRequireDurableWorkflowSave?: boolean;
};

export default function StepShell({
  title,
  subtitle,
  children,
  nextDisabled,
  nextDisabledReason,
  nextLabel = "Mark Complete & Next Step",
  onNext,
  onNextClick,
  nextButtonTestId,
  nextFooterTestId,
  nextStatusTestId,
  nextStatusLine,
  nextExtraActions,
  nextDebugPanel,
  nextPath,
  workflowStepId,
  variant = "standard",
  eyebrow = "Predictive Modeling Workflow",
  heroMetrics = [],
  heroAction,
  hideHeader = false,
  showDeveloperTools = true,
  showEmbeddedNext = false,
  nextAlwaysVisible = false,
  nextRequireDurableWorkflowSave = false,
}: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const markComplete = useWorkflowStore((state) => state.markComplete);
  const getNextStepPath = useWorkflowStore((state) => state.getNextStepPath);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const workflowBarRef = useRef<HTMLDivElement>(null);
  const [workflowBarBounds, setWorkflowBarBounds] = useState<WorkflowActionBarBounds | null>(null);
  const [workflowBarBottomClearance, setWorkflowBarBottomClearance] = useState(144);
  const hideEmbeddedNext = location.pathname === "/credit-risk-studio" && !showEmbeddedNext;
  const workflowBarClassName = nextAlwaysVisible
    ? "fixed bottom-3 z-50 rounded-lg border border-slate-200 bg-white/95 p-2 shadow-xl shadow-slate-900/15 backdrop-blur-xl sm:p-3"
    : "sticky bottom-2 z-10 mt-8 rounded-lg border border-slate-200 bg-white/95 p-2 shadow-lg shadow-slate-900/10 backdrop-blur-xl sm:bottom-3 sm:p-3";

  useLayoutEffect(() => {
    if (!nextAlwaysVisible || hideEmbeddedNext) {
      setWorkflowBarBounds(null);
      return undefined;
    }

    const shell = shellRef.current;
    const workflowBar = workflowBarRef.current;
    if (!shell || !workflowBar) return undefined;

    let animationFrame = 0;
    const measure = () => {
      const shellRect = shell.getBoundingClientRect();
      const nextBounds = resolveWorkflowActionBarBounds(shellRect, window.innerWidth);
      setWorkflowBarBounds((current) => (
        current && current.left === nextBounds.left && current.width === nextBounds.width
          ? current
          : nextBounds
      ));

      const nextClearance = workflowActionBarClearance(workflowBar.getBoundingClientRect().height);
      setWorkflowBarBottomClearance((current) => current === nextClearance ? current : nextClearance);
    };
    const scheduleMeasure = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(measure);
    };

    const resizeObserver = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(scheduleMeasure);
    let ancestor: HTMLElement | null = shell;
    while (ancestor) {
      resizeObserver?.observe(ancestor);
      ancestor = ancestor.parentElement;
    }
    resizeObserver?.observe(workflowBar);
    window.addEventListener("resize", scheduleMeasure);
    window.visualViewport?.addEventListener("resize", scheduleMeasure);
    measure();

    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver?.disconnect();
      window.removeEventListener("resize", scheduleMeasure);
      window.visualViewport?.removeEventListener("resize", scheduleMeasure);
    };
  }, [hideEmbeddedNext, nextAlwaysVisible]);

  const workflowBarStyle: CSSProperties | undefined = nextAlwaysVisible
    ? {
        left: workflowBarBounds?.left ?? 12,
        width: workflowBarBounds?.width ?? "calc(100vw - 24px)",
        maxWidth: "calc(100vw - 24px)",
      }
    : undefined;
  const shellStyle: CSSProperties | undefined = nextAlwaysVisible && !hideEmbeddedNext
    ? { paddingBottom: workflowBarBottomClearance }
    : undefined;

  const handleNext = async () => {
    setNavigationError(null);
    try {
      if (onNext) {
        const result = await onNext();
        if (result === false) return;
      }

      const currentStep = workflowStepId ?? location.pathname.replace("/", "");
      let targetPath = nextPath;
      if (/^step(?:0[0-9]|1[0-3])$/.test(currentStep) || currentStep === "step01b" || currentStep === "dashboard") {
        targetPath = targetPath ?? getNextStepPath(currentStep as Parameters<typeof markComplete>[0]);
        if (nextRequireDurableWorkflowSave) {
          const snapshot = createSnapshotFromState(useWorkflowStore.getState());
          const targetStep = snapshot.workflowSteps.find(
            (step) => step.route === targetPath || step.id === targetPath?.replace(/^\//, ""),
          );
          const completedSnapshot = {
            ...snapshot,
            currentStepId: targetStep?.id ?? snapshot.currentStepId,
            workflowSteps: snapshot.workflowSteps.map((step) =>
              step.id === currentStep ? { ...step, status: "complete" as const } : step,
            ),
          };
          const persisted = await saveWorkflowStateToDatabase(completedSnapshot);
          if (!persisted) {
            throw new Error(
              "ATLAS confirmed the feature contract, but could not durably record Feature Engineering completion. Retry to continue; no duplicate materialization will be created.",
            );
          }
        }
        markComplete(currentStep as Parameters<typeof markComplete>[0]);
      }

      const saveResult = saveActiveProjectBeforeNavigation(useWorkflowStore.getState());
      if (!saveResult.ok) {
        setNavigationError(`${saveResult.message} Navigation will continue, but reopen may restore only workflow progress.`);
      }

      const guardedTargetPath = preserveCreditRiskStudioRoute(targetPath);
      if (guardedTargetPath) {
        navigate(guardedTargetPath);
        window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
      }
    } catch (error) {
      console.error("ATLAS navigation/save failed", error);
      setNavigationError(error instanceof Error ? error.message : "ATLAS could not save and navigate. Please try again.");
    }
  };

  return (
    <div
      ref={shellRef}
      className={`w-full space-y-5 ${hideEmbeddedNext ? "" : nextAlwaysVisible ? "pb-36" : "pb-28"}`}
      style={shellStyle}
    >
      {!hideHeader && (title || subtitle) ? (
        <AtlasWorkflowHero
          eyebrow={eyebrow}
          title={title || "Workflow Step"}
          description={subtitle}
          variant={variant}
          metrics={heroMetrics}
          action={heroAction}
        />
      ) : null}

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

      {showDeveloperTools ? (
        <ErrorBoundary
          title="Code & Reproducibility is temporarily unavailable."
          resetKey={`${useWorkflowStore.getState().projectId}:${location.pathname}`}
          fallback={(
            <section className="atlas-card border-amber-200 bg-amber-50 text-sm text-amber-950" data-testid="step-python-panel-safe-fallback">
              <div className="font-semibold">Code & Reproducibility is disabled for this page.</div>
              <p className="mt-1">The primary workflow remains available. Reload the route after its governed dataset identity is verified.</p>
            </section>
          )}
        >
          <StepPythonPanel />
        </ErrorBoundary>
      ) : null}

      {!hideEmbeddedNext && (
        <div
          ref={workflowBarRef}
          data-testid={nextFooterTestId ?? "workflow-next-bar"}
          data-workflow-action-scope={nextAlwaysVisible ? "main-content-column" : "document-flow"}
          className={workflowBarClassName}
          style={workflowBarStyle}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="hidden min-w-0 sm:block">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {nextDisabled ? "Action required" : "Ready for next step"}
              </div>
              <div
                data-testid={nextStatusTestId}
                className={`mt-1 text-sm ${nextDisabled ? "text-amber-800" : "text-slate-600"}`}
              >
                {nextDisabled && nextDisabledReason ? nextDisabledReason : nextStatusLine || "Complete this workflow step and continue."}
              </div>
            </div>
            <div className="flex w-full flex-wrap items-center justify-end gap-2 lg:w-auto">
              {nextExtraActions}
            <button
              type="button"
              data-testid={nextButtonTestId}
              data-step-next-button="true"
              className={nextDisabled ? "atlas-primary-button w-full min-w-0 cursor-not-allowed opacity-60 sm:w-auto sm:min-w-64" : "atlas-primary-button w-full min-w-0 sm:w-auto sm:min-w-64"}
              disabled={!!nextDisabled}
              onClick={onNextClick ?? handleNext}
              title={nextDisabled ? nextDisabledReason || "Complete required actions first" : nextLabel}
            >
              {nextLabel}
            </button>
            </div>
          </div>
          {nextDebugPanel && <div className="mt-3">{nextDebugPanel}</div>}
        </div>
      )}
    </div>
  );
}
