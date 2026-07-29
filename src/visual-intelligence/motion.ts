import {
  easeCubicIn,
  easeCubicInOut,
  easeCubicOut,
  type BaseType,
  type Selection,
  type Transition,
  type ValueFn,
} from "d3";

/**
 * Shared motion timing for analytical charts.
 *
 * The values intentionally sit inside the EDA Visual Intelligence brief:
 * initial reveal 400-700ms, updates 250-400ms, and hover/highlight 100-180ms.
 * All delays are deterministic; no chart animation uses random timing.
 */
export const ATLAS_MOTION_TOKENS = {
  durationMs: {
    enter: 560,
    update: 320,
    exit: 260,
    axis: 320,
    label: 280,
    marker: 320,
    highlight: 140,
  },
  stagger: {
    stepMs: 18,
    maxTotalMs: 180,
  },
  easing: {
    enter: "cubicOut",
    update: "cubicInOut",
    exit: "cubicIn",
    highlight: "cubicOut",
  },
  /** ECharts' default is also bounded, but keeping the value here makes the
   * large-mark behavior explicit and testable across every chart. */
  animationThreshold: 2_000,
} as const;

export type AtlasMotionKind = keyof typeof ATLAS_MOTION_TOKENS.durationMs;

export type AtlasMotionEnvironment = {
  reducedMotion?: boolean;
  /** Export and screenshot rendering must jump directly to the final state. */
  exportMode?: boolean;
  /** An explicit escape hatch for resize/final-state rendering. */
  immediate?: boolean;
  /** Large canvas/WebGL views may animate as a whole but never stagger marks. */
  largeData?: boolean;
  markCount?: number;
  stagger?: boolean;
};

export type ResolvedAtlasMotion = {
  kind: AtlasMotionKind;
  enabled: boolean;
  durationMs: number;
  easing: string;
  staggered: boolean;
  delayFor: (index: number) => number;
  totalDurationMs: number;
  disabledReason: "reduced-motion" | "export-mode" | "immediate" | null;
};

function easingFor(kind: AtlasMotionKind): string {
  if (kind === "exit") return ATLAS_MOTION_TOKENS.easing.exit;
  if (kind === "update" || kind === "axis" || kind === "label" || kind === "marker") {
    return ATLAS_MOTION_TOKENS.easing.update;
  }
  if (kind === "highlight") return ATLAS_MOTION_TOKENS.easing.highlight;
  return ATLAS_MOTION_TOKENS.easing.enter;
}

/**
 * Deterministic, bounded mark delay. When a chart has many marks, the step is
 * compressed so the final mark never starts later than maxTotalMs.
 */
export function deterministicStaggerDelay(
  index: number,
  markCount: number,
  stepMs = ATLAS_MOTION_TOKENS.stagger.stepMs,
  maxTotalMs = ATLAS_MOTION_TOKENS.stagger.maxTotalMs,
): number {
  const count = Math.max(0, Math.floor(markCount));
  if (count <= 1) return 0;
  const safeIndex = Math.max(0, Math.min(count - 1, Math.floor(index)));
  const compressedStep = Math.min(Math.max(0, stepMs), Math.max(0, maxTotalMs) / (count - 1));
  return Math.round(safeIndex * compressedStep * 1000) / 1000;
}

export function resolveAtlasMotion(
  kind: AtlasMotionKind,
  environment: AtlasMotionEnvironment = {},
): ResolvedAtlasMotion {
  const disabledReason = environment.reducedMotion
    ? "reduced-motion"
    : environment.exportMode
      ? "export-mode"
      : environment.immediate
        ? "immediate"
        : null;
  const enabled = disabledReason === null;
  const markCount = Math.max(0, Math.floor(environment.markCount ?? 0));
  const defaultStagger = kind === "enter";
  const staggered =
    enabled &&
    !environment.largeData &&
    markCount > 1 &&
    (environment.stagger ?? defaultStagger);
  const durationMs = enabled ? ATLAS_MOTION_TOKENS.durationMs[kind] : 0;
  const delayFor = staggered
    ? (index: number) => deterministicStaggerDelay(index, markCount)
    : () => 0;

  return {
    kind,
    enabled,
    durationMs,
    easing: easingFor(kind),
    staggered,
    delayFor,
    totalDurationMs: durationMs + (staggered ? delayFor(markCount - 1) : 0),
    disabledReason,
  };
}

export type AtlasEChartsMotionOptions = {
  animation: boolean;
  animationThreshold: number;
  animationDuration: number;
  animationDurationUpdate: number;
  animationEasing: string;
  animationEasingUpdate: string;
  animationDelay: number | ((dataIndex: number) => number);
  animationDelayUpdate: number | ((dataIndex: number) => number);
};

/**
 * Adds the shared timing contract without mutating the caller's ECharts option.
 * Reduced-motion and export-mode both force true final-state rendering:
 * animation=false and every duration/delay is zero.
 */
export function atlasEChartsMotionOptions(
  environment: AtlasMotionEnvironment = {},
): AtlasEChartsMotionOptions {
  const enter = resolveAtlasMotion("enter", environment);
  const update = resolveAtlasMotion("update", { ...environment, stagger: false });
  return {
    animation: enter.enabled,
    animationThreshold: ATLAS_MOTION_TOKENS.animationThreshold,
    animationDuration: enter.durationMs,
    animationDurationUpdate: update.durationMs,
    animationEasing: enter.easing,
    animationEasingUpdate: update.easing,
    animationDelay: enter.staggered ? enter.delayFor : 0,
    animationDelayUpdate: 0,
  };
}

export function withAtlasEChartsMotion<T extends object>(
  option: T,
  environment: AtlasMotionEnvironment = {},
): T & AtlasEChartsMotionOptions {
  return Object.assign({}, option, atlasEChartsMotionOptions(environment));
}

export type ChartMotionRevision = Readonly<{
  revision: number;
  signal: AbortSignal;
}>;

export type ChartMotionController = {
  /** Starts an independent chart update and aborts only this chart's prior update. */
  beginRevision: () => ChartMotionRevision;
  isCurrent: (revision: number) => boolean;
  track: <T>(work: Promise<T>) => Promise<T>;
  /** Export/screenshot callers can await this chart without waiting on any other chart. */
  whenSettled: () => Promise<void>;
  cancel: () => void;
  currentRevision: () => number;
};

/**
 * Per-chart lifecycle controller. It deliberately has no global registry, so
 * one slow chart can never serialize or block another chart's motion.
 */
export function createChartMotionController(): ChartMotionController {
  let revision = 0;
  let active = new AbortController();
  const pending = new Set<Promise<unknown>>();

  return {
    beginRevision() {
      active.abort();
      active = new AbortController();
      revision += 1;
      return { revision, signal: active.signal };
    },
    isCurrent(candidate) {
      return candidate === revision && !active.signal.aborted;
    },
    track<T>(work: Promise<T>): Promise<T> {
      let tracked: Promise<T>;
      tracked = work.then(
        (value) => {
          pending.delete(tracked);
          return value;
        },
        (error) => {
          pending.delete(tracked);
          throw error;
        },
      );
      pending.add(tracked);
      return tracked;
    },
    async whenSettled() {
      while (pending.size) {
        await Promise.allSettled(Array.from(pending));
      }
    },
    cancel() {
      active.abort();
      revision += 1;
    },
    currentRevision() {
      return revision;
    },
  };
}

export type AtlasD3TransitionTarget<
  GElement extends BaseType,
  Datum,
  PElement extends BaseType,
  PDatum,
> = {
  attr(
    name: string,
    value:
      | string
      | number
      | boolean
      | null
      | ValueFn<GElement, Datum, string | number | boolean | null>,
  ): AtlasD3TransitionTarget<GElement, Datum, PElement, PDatum>;
  style(
    name: string,
    value:
      | string
      | number
      | boolean
      | null
      | ValueFn<GElement, Datum, string | number | boolean | null>,
  ): AtlasD3TransitionTarget<GElement, Datum, PElement, PDatum>;
  call(
    callback: (...args: any[]) => any,
    ...args: any[]
  ): AtlasD3TransitionTarget<GElement, Datum, PElement, PDatum>;
};

export type AtlasD3TransitionResult = {
  name: string;
  durationMs: number;
  finished: Promise<"completed" | "interrupted" | "immediate">;
  cancel: () => void;
};

export type AtlasD3TransitionOptions = AtlasMotionEnvironment & {
  chartId: string;
  kind: AtlasMotionKind;
  channel?: string;
  signal?: AbortSignal;
};

function safeTransitionSegment(value: string): string {
  return value.trim().replace(/[^a-zA-Z0-9_-]+/g, "-") || "chart";
}

/** Stable D3 transition names are what make `.interrupt(name)` reliable. */
export function atlasTransitionName(chartId: string, channel = "marks"): string {
  return `atlas-${safeTransitionSegment(chartId)}-${safeTransitionSegment(channel)}`;
}

function d3Ease(kind: AtlasMotionKind): (normalizedTime: number) => number {
  if (kind === "exit") return easeCubicIn;
  if (kind === "update" || kind === "axis" || kind === "label" || kind === "marker") {
    return easeCubicInOut;
  }
  return easeCubicOut;
}

/**
 * Runs one named, interruption-safe D3 transition.
 *
 * Callers describe only the final state in `configure`. In reduced-motion,
 * export, or immediate mode the same callback is applied directly to the
 * selection, which guarantees screenshots and exports receive the final state.
 * A new run on the same chart/channel interrupts the old run cleanly.
 */
export function runAtlasD3Transition<
  GElement extends BaseType,
  Datum,
  PElement extends BaseType,
  PDatum,
>(
  selection: Selection<GElement, Datum, PElement, PDatum>,
  configure: (
    target: AtlasD3TransitionTarget<GElement, Datum, PElement, PDatum>,
  ) => void,
  options: AtlasD3TransitionOptions,
): AtlasD3TransitionResult {
  const name = atlasTransitionName(options.chartId, options.channel);
  selection.interrupt(name);

  if (options.signal?.aborted) {
    return {
      name,
      durationMs: 0,
      finished: Promise.resolve("interrupted"),
      cancel: () => selection.interrupt(name),
    };
  }

  const motion = resolveAtlasMotion(options.kind, options);
  if (!motion.enabled) {
    configure(selection as unknown as AtlasD3TransitionTarget<GElement, Datum, PElement, PDatum>);
    return {
      name,
      durationMs: 0,
      finished: Promise.resolve("immediate"),
      cancel: () => selection.interrupt(name),
    };
  }

  const transition = selection
    .transition(name)
    .duration(motion.durationMs)
    .ease(d3Ease(options.kind))
    .delay((_datum, index) => motion.delayFor(index));
  configure(transition as unknown as AtlasD3TransitionTarget<GElement, Datum, PElement, PDatum>);

  const cancel = () => selection.interrupt(name);
  options.signal?.addEventListener("abort", cancel, { once: true });
  const finished: Promise<"completed" | "interrupted"> = transition.end()
    .then(
      () => "completed" as const,
      () => "interrupted" as const,
    )
    .finally(() => {
      options.signal?.removeEventListener("abort", cancel);
    });

  return {
    name,
    durationMs: motion.totalDurationMs,
    finished,
    cancel,
  };
}
