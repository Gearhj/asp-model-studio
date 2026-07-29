import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { PredictorVisualSuiteProps } from "./predictorVisualTypes";

const PredictorSecondaryInsights = lazy(
  () => import("./PredictorSecondaryInsights")
);

export default function LazyPredictorSecondaryInsights(
  props: PredictorVisualSuiteProps
) {
  const boundaryRef = useRef<HTMLDivElement | null>(null);
  const [shouldRender, setShouldRender] = useState(false);

  useEffect(() => {
    if (shouldRender) return;
    const boundary = boundaryRef.current;
    if (!boundary || typeof IntersectionObserver === "undefined") {
      setShouldRender(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setShouldRender(true);
        observer.disconnect();
      },
      { rootMargin: "360px 0px", threshold: 0.01 }
    );
    observer.observe(boundary);
    return () => observer.disconnect();
  }, [shouldRender]);

  return (
    <div
      ref={boundaryRef}
      data-testid="predictor-secondary-insights-boundary"
      data-load-state={
        shouldRender ? "rendering-or-ready" : "deferred"
      }
      data-aggregate-boundary="single-batched-predictor-response"
      className={props.className}
    >
      {shouldRender ? (
        <Suspense fallback={<SecondaryInsightsPlaceholder loading />}>
          <PredictorSecondaryInsights {...props} />
        </Suspense>
      ) : (
        <SecondaryInsightsPlaceholder
          onLoad={() => setShouldRender(true)}
        />
      )}
    </div>
  );
}

function SecondaryInsightsPlaceholder({
  loading = false,
  onLoad,
}: {
  loading?: boolean;
  onLoad?: () => void;
}) {
  return (
    <section
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-busy={loading}
      aria-label="Secondary predictor insights"
    >
      <p className="text-xs font-bold uppercase tracking-[0.16em] text-indigo-700">
        Predictor visual intelligence
      </p>
      <h3 className="mt-1 text-lg font-semibold text-slate-950">
        {loading
          ? "Loading secondary predictor insights"
          : "Secondary predictor insights load as you approach"}
      </h3>
      <p className="mt-1 text-sm text-slate-600">
        Event-rate shapes, the quality matrix, and exceptional-value treatment
        detail use the same already-loaded aggregate response.
      </p>
      {!loading && onLoad ? (
        <button
          type="button"
          className="atlas-secondary-button mt-3"
          onClick={onLoad}
        >
          Load secondary predictor insights now
        </button>
      ) : null}
    </section>
  );
}
