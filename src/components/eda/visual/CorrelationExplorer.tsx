import React, {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { color, scaleLinear, select } from "d3";
import {
  Download,
  Expand,
  Maximize2,
  Minimize2,
  RotateCcw,
  Search,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  createChartMotionController,
  runAtlasD3Transition,
} from "../../../visual-intelligence/motion";

export type CorrelationPair = {
  a: string;
  b: string;
  correlation?: number | null;
};

export type CorrelationVifValue = {
  vif: number | null;
  isInfinite?: boolean;
  /** Accepts the backend response shape without requiring a lossy remap. */
  is_infinite?: boolean;
};

export type CorrelationExplorerProps = {
  columns: string[];
  matrix: (number | null)[][];
  /** Pairwise complete-case N for each correlation cell. */
  correlationSampleSizes?: (number | null)[][];
  /** VIF values from the separately disclosed bounded backend cohort. */
  vifByFeature?: Record<
    string,
    CorrelationVifValue | number | null | undefined
  >;
  selectedVariable?: string | null;
  pinnedPair?: CorrelationPair | null;
  onSelectVariable: (name: string) => void;
  onPinPair: (pair: CorrelationPair) => void;
  onLaunch2D?: (pair: CorrelationPair) => void;
  onLaunch3D?: (pair: CorrelationPair) => void;
  className?: string;
  /** Primarily useful for deterministic tests and export rendering. */
  reducedMotion?: boolean;
};

type MatrixOrder = "original" | "alphabetical" | "clustered";
type MatrixViewMode = "readable" | "compact";

type ColumnRecord = {
  name: string;
  sourceIndex: number;
  key: string;
};

type CorrelationCell = {
  key: string;
  row: ColumnRecord;
  column: ColumnRecord;
  rowIndex: number;
  columnIndex: number;
  value: number | null;
  visible: boolean;
  diagonal: boolean;
};

type HoveredCell = CorrelationCell & {
  clientX: number;
  clientY: number;
};

const DEFAULT_SUBSET_LIMIT = 12;
const MAX_SUBSET_LIMIT = 50;
const BASE_CELL_SIZE = 54;
const MIN_MANUAL_ZOOM = 0.7;
const MIN_FIT_ZOOM = 0.08;
const MAX_ZOOM = 2;
const ZOOM_STEP = 0.15;
const EMPTY_VIF_LOOKUP: NonNullable<
  CorrelationExplorerProps["vifByFeature"]
> = {};
const NUMBER_FORMAT = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 3,
});
const CORRELATION_DETAIL_FORMAT = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 3,
  maximumFractionDigits: 6,
});
const INTEGER_FORMAT = new Intl.NumberFormat();

function useSystemReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  return reduced;
}

function readCorrelation(
  matrix: (number | null)[][],
  rowIndex: number,
  columnIndex: number,
): number | null {
  const value = matrix[rowIndex]?.[columnIndex];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readSampleSize(
  matrix: (number | null)[][] | undefined,
  rowIndex: number,
  columnIndex: number,
): number | null {
  const direct = matrix?.[rowIndex]?.[columnIndex];
  const reverse = matrix?.[columnIndex]?.[rowIndex];
  const value =
    typeof direct === "number" && Number.isFinite(direct) ? direct : reverse;
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.round(value))
    : null;
}

function normalizeVifValue(
  value: CorrelationVifValue | number | null | undefined,
): CorrelationVifValue | null {
  if (typeof value === "number") {
    return Number.isFinite(value)
      ? { vif: value }
      : { vif: null, isInfinite: value === Number.POSITIVE_INFINITY };
  }
  if (value && typeof value === "object" && "vif" in value) {
    return {
      vif:
        typeof value.vif === "number" && Number.isFinite(value.vif)
          ? value.vif
          : null,
      isInfinite:
        Boolean(value.isInfinite) ||
        Boolean(value.is_infinite) ||
        value.vif === Number.POSITIVE_INFINITY,
    };
  }
  return null;
}

function formatVif(value: CorrelationVifValue | null): string {
  if (value?.isInfinite) return "Infinite";
  if (value?.vif === null || value?.vif === undefined) return "Not evaluated";
  return NUMBER_FORMAT.format(value.vif);
}

function correlationSign(value: number | null): string {
  if (value === null) return "Not available";
  if (value > Number.EPSILON) return "Positive";
  if (value < -Number.EPSILON) return "Negative";
  return "No linear sign";
}

function correlationDistance(
  matrix: (number | null)[][],
  left: ColumnRecord,
  right: ColumnRecord,
): number {
  const direct = readCorrelation(matrix, left.sourceIndex, right.sourceIndex);
  const reverse = readCorrelation(matrix, right.sourceIndex, left.sourceIndex);
  const value = direct ?? reverse;
  return value === null ? 1 : 1 - Math.min(1, Math.abs(value));
}

/**
 * Deterministic average-linkage clustering with a simple endpoint-aware leaf
 * order. The explorer bounds this work to MAX_SUBSET_LIMIT variables.
 */
export function clusterCorrelationColumns(
  columns: ColumnRecord[],
  matrix: (number | null)[][],
): ColumnRecord[] {
  if (columns.length < 2) return columns.slice();
  let clusters = columns.map((entry) => [entry]);

  const averageDistance = (left: ColumnRecord[], right: ColumnRecord[]) => {
    let total = 0;
    let count = 0;
    left.forEach((leftEntry) => {
      right.forEach((rightEntry) => {
        total += correlationDistance(matrix, leftEntry, rightEntry);
        count += 1;
      });
    });
    return count ? total / count : 1;
  };

  while (clusters.length > 1) {
    let bestLeft = 0;
    let bestRight = 1;
    let bestDistance = Number.POSITIVE_INFINITY;

    for (let left = 0; left < clusters.length - 1; left += 1) {
      for (let right = left + 1; right < clusters.length; right += 1) {
        const distance = averageDistance(clusters[left], clusters[right]);
        if (
          distance < bestDistance - Number.EPSILON ||
          (Math.abs(distance - bestDistance) <= Number.EPSILON &&
            `${clusters[left][0].key}:${clusters[right][0].key}` <
              `${clusters[bestLeft][0].key}:${clusters[bestRight][0].key}`)
        ) {
          bestDistance = distance;
          bestLeft = left;
          bestRight = right;
        }
      }
    }

    const left = clusters[bestLeft];
    const right = clusters[bestRight];
    const arrangements = [
      [...left, ...right],
      [...left, ...right.slice().reverse()],
      [...left.slice().reverse(), ...right],
      [...left.slice().reverse(), ...right.slice().reverse()],
    ];
    arrangements.sort((first, second) => {
      const firstJoin = correlationDistance(
        matrix,
        first[left.length - 1],
        first[left.length],
      );
      const secondJoin = correlationDistance(
        matrix,
        second[left.length - 1],
        second[left.length],
      );
      if (firstJoin !== secondJoin) return firstJoin - secondJoin;
      return first.map((entry) => entry.key).join("|").localeCompare(
        second.map((entry) => entry.key).join("|"),
      );
    });

    const merged = arrangements[0];
    clusters = clusters.filter(
      (_cluster, index) => index !== bestLeft && index !== bestRight,
    );
    clusters.push(merged);
    clusters.sort((first, second) => first[0].key.localeCompare(second[0].key));
  }

  return clusters[0];
}

function truncateLabel(value: string, limit = 21): string {
  if (value.length <= limit) return value;
  return `${value.slice(0, Math.max(1, limit - 1))}…`;
}

function normalizePair(pair: CorrelationPair | null | undefined): string | null {
  if (!pair) return null;
  return [pair.a, pair.b].sort((left, right) => left.localeCompare(right)).join("\u0000");
}

function csvCell(value: string): string {
  const safeValue = /^[=+\-@]/.test(value) ? `'${value}` : value;
  return `"${safeValue.replace(/"/g, '""')}"`;
}

function isSamePair(cell: CorrelationCell, pairKey: string | null): boolean {
  if (!pairKey) return false;
  return normalizePair({ a: cell.row.name, b: cell.column.name }) === pairKey;
}

export default function CorrelationExplorer({
  columns,
  matrix,
  correlationSampleSizes,
  vifByFeature = EMPTY_VIF_LOOKUP,
  selectedVariable = null,
  pinnedPair = null,
  onSelectVariable,
  onPinPair,
  onLaunch2D,
  onLaunch3D,
  className = "",
  reducedMotion,
}: CorrelationExplorerProps) {
  const chartId = useId().replace(/:/g, "");
  const svgRef = useRef<SVGSVGElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const sectionRef = useRef<HTMLElement | null>(null);
  const expandButtonRef = useRef<HTMLButtonElement | null>(null);
  const closeExpandedButtonRef = useRef<HTMLButtonElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const subsetLimitUserAdjustedRef = useRef(false);
  const previousColumnCountRef = useRef(columns.length);
  const motionControllerRef = useRef(createChartMotionController());
  const actionRef = useRef({ onSelectVariable, onPinPair });
  actionRef.current = { onSelectVariable, onPinPair };
  const systemReducedMotion = useSystemReducedMotion();
  const shouldReduceMotion = reducedMotion ?? systemReducedMotion;

  const [query, setQuery] = useState("");
  const [subsetLimit, setSubsetLimit] = useState(() =>
    Math.min(
      DEFAULT_SUBSET_LIMIT,
      Math.max(2, Math.min(MAX_SUBSET_LIMIT, columns.length || 2)),
    ),
  );
  const [absoluteThreshold, setAbsoluteThreshold] = useState(0);
  const [order, setOrder] = useState<MatrixOrder>("original");
  const [containerWidth, setContainerWidth] = useState(960);
  const [hoveredCell, setHoveredCell] = useState<HoveredCell | null>(null);
  const [manualZoom, setManualZoom] = useState(1);
  const [zoomMode, setZoomMode] = useState<"manual" | "fit">("manual");
  const [matrixViewMode, setMatrixViewMode] =
    useState<MatrixViewMode>("readable");
  const [isExpanded, setIsExpanded] = useState(false);
  const [scrollState, setScrollState] = useState({
    left: 0,
    top: 0,
    clientWidth: 960,
    clientHeight: 640,
  });

  const readScrollState = useCallback(() => {
    const frame = frameRef.current;
    if (!frame) return;
    setScrollState({
      left: frame.scrollLeft,
      top: frame.scrollTop,
      clientWidth: frame.clientWidth,
      clientHeight: frame.clientHeight,
    });
  }, []);

  const handleFrameScroll = useCallback(() => {
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current);
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      readScrollState();
    });
  }, [readScrollState]);

  const openExpanded = useCallback(() => {
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : expandButtonRef.current;
    setIsExpanded(true);
  }, []);

  const closeExpanded = useCallback(() => {
    setIsExpanded(false);
    window.requestAnimationFrame(() => {
      returnFocusRef.current?.focus();
    });
  }, []);

  useEffect(() => {
    const previousColumnCount = previousColumnCountRef.current;
    previousColumnCountRef.current = columns.length;
    setSubsetLimit((current) => {
      const availableLimit = Math.max(
        2,
        Math.min(MAX_SUBSET_LIMIT, columns.length || 2),
      );
      if (
        !subsetLimitUserAdjustedRef.current &&
        previousColumnCount < DEFAULT_SUBSET_LIMIT &&
        columns.length >= DEFAULT_SUBSET_LIMIT
      ) {
        return DEFAULT_SUBSET_LIMIT;
      }
      return Math.max(2, Math.min(current, availableLimit));
    });
  }, [columns.length]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      setContainerWidth(Math.max(320, Math.floor(entry.contentRect.width)));
      readScrollState();
    });
    observer.observe(frame);
    return () => observer.disconnect();
  }, [readScrollState]);

  useEffect(() => {
    if (!isExpanded) return;
    const priorBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeExpandedButtonRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeExpanded();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        sectionRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => !element.hasAttribute("aria-hidden"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = priorBodyOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [closeExpanded, isExpanded]);

  useEffect(
    () => () => {
      motionControllerRef.current.cancel();
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
    },
    [],
  );

  const columnRecords = useMemo<ColumnRecord[]>(
    () =>
      columns.map((name, sourceIndex) => ({
        name,
        sourceIndex,
        key: `${sourceIndex}:${name}`,
      })),
    [columns],
  );

  const matchingColumns = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const matching = normalizedQuery
      ? columnRecords.filter((entry) =>
          entry.name.toLocaleLowerCase().includes(normalizedQuery),
        )
      : columnRecords.slice();

    if (order === "alphabetical") {
      matching.sort(
        (left, right) =>
          left.name.localeCompare(right.name, undefined, { sensitivity: "base" }) ||
          left.sourceIndex - right.sourceIndex,
      );
    }

    let subset = matching.slice(0, subsetLimit);
    const selected = matching.find((entry) => entry.name === selectedVariable);
    if (selected && !subset.some((entry) => entry.key === selected.key)) {
      subset = [...subset.slice(0, Math.max(0, subsetLimit - 1)), selected];
    }

    return order === "clustered"
      ? clusterCorrelationColumns(subset, matrix)
      : subset;
  }, [columnRecords, matrix, order, query, selectedVariable, subsetLimit]);

  const cells = useMemo<CorrelationCell[]>(() => {
    const result: CorrelationCell[] = [];
    matchingColumns.forEach((row, rowIndex) => {
      matchingColumns.forEach((column, columnIndex) => {
        const direct = readCorrelation(matrix, row.sourceIndex, column.sourceIndex);
        const reverse = readCorrelation(matrix, column.sourceIndex, row.sourceIndex);
        const value = direct ?? reverse;
        const diagonal = row.sourceIndex === column.sourceIndex;
        result.push({
          key: `${row.key}|${column.key}`,
          row,
          column,
          rowIndex,
          columnIndex,
          value,
          diagonal,
          visible:
            value !== null &&
            (diagonal || Math.abs(value) + Number.EPSILON >= absoluteThreshold),
        });
      });
    });
    return result;
  }, [absoluteThreshold, matchingColumns, matrix]);

  useEffect(() => {
    if (
      hoveredCell &&
      !cells.some((cell) => cell.key === hoveredCell.key && cell.visible)
    ) {
      setHoveredCell(null);
    }
  }, [cells, hoveredCell]);

  const fitZoom = useMemo(() => {
    if (!matchingColumns.length) return 1;
    const horizontalAllowance = isExpanded ? 254 : 218;
    const verticalAllowance = isExpanded ? 210 : 196;
    const horizontalZoom =
      Math.max(120, containerWidth - horizontalAllowance) /
      (matchingColumns.length * BASE_CELL_SIZE);
    const verticalZoom =
      scrollState.clientHeight > verticalAllowance
        ? (scrollState.clientHeight - verticalAllowance) /
          (matchingColumns.length * BASE_CELL_SIZE)
        : MAX_ZOOM;
    return Math.max(
      MIN_FIT_ZOOM,
      Math.min(MAX_ZOOM, horizontalZoom, verticalZoom),
    );
  }, [
    containerWidth,
    isExpanded,
    matchingColumns.length,
    scrollState.clientHeight,
  ]);
  const effectiveZoom = zoomMode === "fit" ? fitZoom : manualZoom;

  const dimensions = useMemo(() => {
    const margin = {
      top: isExpanded ? 172 : 158,
      right: isExpanded ? 44 : 34,
      bottom: 38,
      left: isExpanded ? 210 : 184,
    };
    const cellSize = BASE_CELL_SIZE * effectiveZoom;
    const matrixSize = matchingColumns.length * cellSize;
    const width = Math.max(
      containerWidth,
      margin.left + matrixSize + margin.right,
    );
    return {
      width,
      height: margin.top + matrixSize + margin.bottom,
      margin,
      matrixSize,
      cellSize: matchingColumns.length ? cellSize : 0,
    };
  }, [
    containerWidth,
    effectiveZoom,
    isExpanded,
    matchingColumns.length,
  ]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(readScrollState);
    return () => window.cancelAnimationFrame(frame);
  }, [
    dimensions.height,
    dimensions.width,
    isExpanded,
    readScrollState,
  ]);

  const colorScale = useMemo(
    () =>
      scaleLinear<string>()
        .domain([-1, 0, 1])
        .range(["#1d4ed8", "#f8fafc", "#be123c"])
        .clamp(true),
    [],
  );

  const cellFill = useCallback(
    (cell: CorrelationCell) => {
      if (!cell.visible || cell.value === null) return "#f1f5f9";
      return colorScale(Math.max(-1, Math.min(1, cell.value)));
    },
    [colorScale],
  );

  const cellTextColor = useCallback(
    (cell: CorrelationCell) => {
      const fill = color(cellFill(cell));
      if (!fill || !cell.visible) return "#64748b";
      const rgb = fill.rgb();
      const luminance =
        (0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b) / 255;
      return luminance < 0.49 ? "#ffffff" : "#172033";
    },
    [cellFill],
  );

  useEffect(() => {
    const svgNode = svgRef.current;
    if (!svgNode) return;
    const svg = select(svgNode)
      .attr("viewBox", `0 0 ${dimensions.width} ${dimensions.height}`)
      .attr("data-motion", shouldReduceMotion ? "reduced" : "enabled");
    const root = svg.select<SVGGElement>("g[data-layer='matrix-root']").attr(
      "transform",
      `translate(${dimensions.margin.left},${dimensions.margin.top})`,
    );
    const backgroundLayer = root.select<SVGGElement>("g[data-layer='background']");
    const cellLayer = root.select<SVGGElement>("g[data-layer='cells']");
    const valueLayer = root.select<SVGGElement>("g[data-layer='values']");
    const rowLabelLayer = root.select<SVGGElement>("g[data-layer='row-labels']");
    const columnLabelLayer = root.select<SVGGElement>(
      "g[data-layer='column-labels']",
    );
    const { revision, signal } = motionControllerRef.current.beginRevision();
    const chartIdValue = `correlation-${chartId}`;

    backgroundLayer
      .selectAll<SVGRectElement, number>("rect.atlas-correlation-background")
      .data(matchingColumns.length ? [1] : [])
      .join("rect")
      .attr("class", "atlas-correlation-background")
      .attr("x", 0)
      .attr("y", 0)
      .attr("width", dimensions.matrixSize)
      .attr("height", dimensions.matrixSize)
      .attr("rx", 4)
      .attr("fill", "#f8fafc")
      .attr("stroke", "#cbd5e1");

    const joinedCells = cellLayer
      .selectAll<SVGRectElement, CorrelationCell>("rect.atlas-correlation-cell")
      .data(cells, (cell) => cell.key);
    const exitingCells = joinedCells.exit();
    const exitingCellMotion = runAtlasD3Transition(
      exitingCells,
      (target) => {
        target.attr("opacity", 0);
        target.attr("width", 0);
        target.attr("height", 0);
      },
      {
        chartId: chartIdValue,
        channel: "cell-exit",
        kind: "exit",
        signal,
        reducedMotion: shouldReduceMotion,
        markCount: exitingCells.size(),
      },
    );
    void exitingCellMotion.finished.then(() => {
      if (motionControllerRef.current.isCurrent(revision)) exitingCells.remove();
    });

    const enteringCells = joinedCells
      .enter()
      .append("rect")
      .attr("class", "atlas-correlation-cell")
      .attr("x", (cell) => (cell.columnIndex + 0.5) * dimensions.cellSize)
      .attr("y", (cell) => (cell.rowIndex + 0.5) * dimensions.cellSize)
      .attr("width", 0)
      .attr("height", 0)
      .attr("rx", Math.min(3, dimensions.cellSize * 0.12))
      .attr("opacity", 0);
    const activeCells = enteringCells.merge(joinedCells);

    activeCells
      .attr("data-cell-key", (cell) => cell.key)
      .attr("data-row", (cell) => cell.row.name)
      .attr("data-column", (cell) => cell.column.name)
      .attr("data-visible", (cell) => String(cell.visible))
      .attr("role", (cell) => (cell.visible ? "button" : "presentation"))
      .attr("tabindex", (cell) => (cell.visible ? 0 : -1))
      .attr("aria-label", (cell) => {
        if (!cell.visible || cell.value === null) {
          return `${cell.row.name} and ${cell.column.name}: hidden below the absolute-correlation threshold`;
        }
        return `${cell.row.name} and ${cell.column.name}: correlation ${CORRELATION_DETAIL_FORMAT.format(cell.value)}${cell.diagonal ? "" : ". Press Enter to pin this pair."}`;
      })
      .style("cursor", (cell) =>
        cell.visible ? (cell.diagonal ? "pointer" : "crosshair") : "default",
      )
      .style("pointer-events", (cell) => (cell.visible ? "auto" : "none"))
      .on("pointerenter", function (event: PointerEvent, cell) {
        const bounds = svgNode.getBoundingClientRect();
        setHoveredCell({
          ...cell,
          clientX: event.clientX - bounds.left,
          clientY: event.clientY - bounds.top,
        });
      })
      .on("pointermove", function (event: PointerEvent, cell) {
        const bounds = svgNode.getBoundingClientRect();
        setHoveredCell({
          ...cell,
          clientX: event.clientX - bounds.left,
          clientY: event.clientY - bounds.top,
        });
      })
      .on("pointerleave", () => setHoveredCell(null))
      .on("focus", function (_event: FocusEvent, cell) {
        const bounds = (this as SVGRectElement).getBoundingClientRect();
        const svgBounds = svgNode.getBoundingClientRect();
        setHoveredCell({
          ...cell,
          clientX: bounds.left - svgBounds.left + bounds.width / 2,
          clientY: bounds.top - svgBounds.top + bounds.height / 2,
        });
      })
      .on("blur", () => setHoveredCell(null))
      .on("click", (_event: MouseEvent, cell) => {
        actionRef.current.onSelectVariable(cell.row.name);
        if (!cell.diagonal) {
          actionRef.current.onPinPair({ a: cell.row.name, b: cell.column.name });
        }
      })
      .on("keydown", (event: KeyboardEvent, cell) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        actionRef.current.onSelectVariable(cell.row.name);
        if (!cell.diagonal) {
          actionRef.current.onPinPair({ a: cell.row.name, b: cell.column.name });
        }
      });

    runAtlasD3Transition(
      enteringCells,
      (target) => {
        target.attr(
          "x",
          (cell) => cell.columnIndex * dimensions.cellSize + 0.7,
        );
        target.attr(
          "y",
          (cell) => cell.rowIndex * dimensions.cellSize + 0.7,
        );
        target.attr("width", Math.max(0, dimensions.cellSize - 1.4));
        target.attr("height", Math.max(0, dimensions.cellSize - 1.4));
        target.attr("fill", cellFill);
        target.attr("opacity", 1);
      },
      {
        chartId: chartIdValue,
        channel: "cell-enter",
        kind: "enter",
        signal,
        reducedMotion: shouldReduceMotion,
        markCount: enteringCells.size(),
        stagger: true,
      },
    );
    runAtlasD3Transition(
      joinedCells,
      (target) => {
        target.attr(
          "x",
          (cell) => cell.columnIndex * dimensions.cellSize + 0.7,
        );
        target.attr(
          "y",
          (cell) => cell.rowIndex * dimensions.cellSize + 0.7,
        );
        target.attr("width", Math.max(0, dimensions.cellSize - 1.4));
        target.attr("height", Math.max(0, dimensions.cellSize - 1.4));
        target.attr("rx", Math.min(3, dimensions.cellSize * 0.12));
        target.attr("fill", cellFill);
        target.attr("opacity", 1);
      },
      {
        chartId: chartIdValue,
        channel: "cell-update",
        kind: "update",
        signal,
        reducedMotion: shouldReduceMotion,
        markCount: joinedCells.size(),
        stagger: false,
      },
    );

    const showValues = dimensions.cellSize >= 32;
    const valueCells = showValues ? cells.filter((cell) => cell.visible) : [];
    const joinedValues = valueLayer
      .selectAll<SVGTextElement, CorrelationCell>("text.atlas-correlation-value")
      .data(valueCells, (cell) => cell.key);
    const exitingValues = joinedValues.exit();
    const exitingValueMotion = runAtlasD3Transition(
      exitingValues,
      (target) => target.attr("opacity", 0),
      {
        chartId: chartIdValue,
        channel: "value-exit",
        kind: "exit",
        signal,
        reducedMotion: shouldReduceMotion,
      },
    );
    void exitingValueMotion.finished.then(() => {
      if (motionControllerRef.current.isCurrent(revision)) exitingValues.remove();
    });
    const enteringValues = joinedValues
      .enter()
      .append("text")
      .attr("class", "atlas-correlation-value")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "central")
      .attr(
        "font-family",
        "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      )
      .attr("font-size", Math.max(8, Math.min(11, dimensions.cellSize * 0.25)))
      .attr("pointer-events", "none")
      .attr("opacity", 0);
    const activeValues = enteringValues
      .merge(joinedValues)
      .attr(
        "font-size",
        Math.max(10, Math.min(14, dimensions.cellSize * 0.25)),
      )
      .attr("font-weight", 650)
      .text((cell) =>
        cell.value === null
          ? ""
          : Math.abs(cell.value) >= 0.995
            ? cell.value.toFixed(1)
            : cell.value.toFixed(2),
      );
    runAtlasD3Transition(
      activeValues,
      (target) => {
        target.attr(
          "x",
          (cell) => (cell.columnIndex + 0.5) * dimensions.cellSize,
        );
        target.attr(
          "y",
          (cell) => (cell.rowIndex + 0.5) * dimensions.cellSize,
        );
        target.attr("fill", cellTextColor);
        target.attr("opacity", 1);
      },
      {
        chartId: chartIdValue,
        channel: "value-update",
        kind: enteringValues.size() ? "enter" : "update",
        signal,
        reducedMotion: shouldReduceMotion,
        markCount: activeValues.size(),
        stagger: enteringValues.size() > 0,
      },
    );

    const configureLabel = (
      layer: typeof rowLabelLayer,
      orientation: "row" | "column",
    ) => {
      const joined = layer
        .selectAll<SVGTextElement, ColumnRecord>(
          `text.atlas-correlation-${orientation}-label`,
        )
        .data(matchingColumns, (entry) => entry.key);
      const exiting = joined.exit();
      const exitMotion = runAtlasD3Transition(
        exiting,
        (target) => target.attr("opacity", 0),
        {
          chartId: chartIdValue,
          channel: `${orientation}-label-exit`,
          kind: "exit",
          signal,
          reducedMotion: shouldReduceMotion,
        },
      );
      void exitMotion.finished.then(() => {
        if (motionControllerRef.current.isCurrent(revision)) exiting.remove();
      });

      const entering = joined
        .enter()
        .append("text")
        .attr("class", `atlas-correlation-${orientation}-label`)
        .attr("role", "button")
        .attr("tabindex", 0)
        .attr("opacity", 0);
      const active = entering
        .merge(joined)
        .text((entry) =>
          truncateLabel(entry.name, isExpanded ? 30 : 23),
        )
        .attr("aria-label", (entry) => `Select variable ${entry.name}`)
        .attr("data-variable", (entry) => entry.name)
        .attr("font-size", isExpanded ? 13 : 12)
        .attr("font-weight", 550)
        .attr("fill", "#475569")
        .style("cursor", "pointer")
        .on("click", (_event: MouseEvent, entry) => actionRef.current.onSelectVariable(entry.name))
        .on("keydown", (event: KeyboardEvent, entry) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          actionRef.current.onSelectVariable(entry.name);
        });
      active.selectAll("title").data((entry) => [entry]).join("title").text(
        (entry) => entry.name,
      );

      runAtlasD3Transition(
        active,
        (target) => {
          if (orientation === "row") {
            target.attr("x", -12);
            target.attr(
              "y",
              (_entry, index) => (index + 0.5) * dimensions.cellSize,
            );
            target.attr("text-anchor", "end");
            target.attr("dominant-baseline", "central");
            target.attr("transform", null);
          } else {
            target.attr(
              "x",
              (_entry, index) => (index + 0.5) * dimensions.cellSize,
            );
            target.attr("y", -12);
            target.attr("text-anchor", "start");
            target.attr("dominant-baseline", "central");
            target.attr(
              "transform",
              (_entry, index) =>
                `rotate(-48 ${(index + 0.5) * dimensions.cellSize} -12)`,
            );
          }
          target.attr("opacity", 1);
        },
        {
          chartId: chartIdValue,
          channel: `${orientation}-label-update`,
          kind: entering.size() ? "enter" : "label",
          signal,
          reducedMotion: shouldReduceMotion,
          markCount: active.size(),
          stagger: entering.size() > 0,
        },
      );
    };

    configureLabel(rowLabelLayer, "row");
    configureLabel(columnLabelLayer, "column");
  }, [
    cellFill,
    cellTextColor,
    cells,
    chartId,
    dimensions,
    isExpanded,
    matchingColumns,
    shouldReduceMotion,
  ]);

  useEffect(() => {
    const svgNode = svgRef.current;
    if (!svgNode) return;
    const svg = select(svgNode);
    const pairKey = normalizePair(pinnedPair);
    const hoveredKey = hoveredCell?.key ?? null;
    const hasLinkedFocus = Boolean(
      hoveredCell || selectedVariable || pinnedPair,
    );
    const cellsSelection = svg
      .selectAll<SVGRectElement, CorrelationCell>("rect.atlas-correlation-cell")
      .attr("data-pinned", (cell) => String(isSamePair(cell, pairKey)))
      .attr("data-highlighted", (cell) => {
        const linked =
          cell.key === hoveredKey ||
          Boolean(
            hoveredCell &&
              (cell.row.name === hoveredCell.row.name ||
                cell.column.name === hoveredCell.column.name),
          ) ||
          Boolean(
            selectedVariable &&
              (cell.row.name === selectedVariable ||
                cell.column.name === selectedVariable),
          ) ||
          isSamePair(cell, pairKey);
        return String(linked);
      });

    runAtlasD3Transition(
      cellsSelection,
      (target) => {
        target.attr("fill-opacity", (cell) => {
          if (!hasLinkedFocus) return 1;
          const linked =
            cell.key === hoveredKey ||
            Boolean(
              hoveredCell &&
                (cell.row.name === hoveredCell.row.name ||
                  cell.column.name === hoveredCell.column.name),
            ) ||
            Boolean(
              selectedVariable &&
                (cell.row.name === selectedVariable ||
                  cell.column.name === selectedVariable),
            ) ||
            isSamePair(cell, pairKey);
          return linked ? 1 : 0.34;
        });
        target.attr("stroke", (cell) => {
          if (isSamePair(cell, pairKey)) return "#0f172a";
          if (cell.key === hoveredKey) return "#ffffff";
          return cell.visible ? "rgba(255,255,255,0.42)" : "#e2e8f0";
        });
        target.attr("stroke-width", (cell) => {
          if (isSamePair(cell, pairKey)) return 2.6;
          if (cell.key === hoveredKey) return 2;
          return 0.7;
        });
      },
      {
        chartId: `correlation-${chartId}`,
        channel: "linked-highlight",
        kind: "highlight",
        reducedMotion: shouldReduceMotion,
        markCount: cellsSelection.size(),
        stagger: false,
      },
    );

    const valueSelection = svg.selectAll<SVGTextElement, CorrelationCell>(
      "text.atlas-correlation-value",
    );
    runAtlasD3Transition(
      valueSelection,
      (target) => {
        target.attr("fill-opacity", (cell) => {
          if (!hasLinkedFocus) return 1;
          const linked =
            cell.key === hoveredKey ||
            Boolean(
              hoveredCell &&
                (cell.row.name === hoveredCell.row.name ||
                  cell.column.name === hoveredCell.column.name),
            ) ||
            Boolean(
              selectedVariable &&
                (cell.row.name === selectedVariable ||
                  cell.column.name === selectedVariable),
            ) ||
            isSamePair(cell, pairKey);
          return linked ? 1 : 0.28;
        });
      },
      {
        chartId: `correlation-${chartId}`,
        channel: "value-highlight",
        kind: "highlight",
        reducedMotion: shouldReduceMotion,
        markCount: valueSelection.size(),
        stagger: false,
      },
    );

    const labelSelection = svg
      .selectAll<SVGTextElement, ColumnRecord>(
        "text.atlas-correlation-row-label, text.atlas-correlation-column-label",
      )
      .attr("data-selected", (entry) =>
        String(
          entry.name === selectedVariable ||
            entry.name === hoveredCell?.row.name ||
            entry.name === hoveredCell?.column.name ||
            entry.name === pinnedPair?.a ||
            entry.name === pinnedPair?.b,
        ),
      );
    runAtlasD3Transition(
      labelSelection,
      (target) => {
        target.attr("fill", (entry) =>
          entry.name === selectedVariable ||
          entry.name === hoveredCell?.row.name ||
          entry.name === hoveredCell?.column.name ||
          entry.name === pinnedPair?.a ||
          entry.name === pinnedPair?.b
            ? "#0f172a"
            : "#64748b",
        );
        target.attr("font-weight", (entry) =>
          entry.name === selectedVariable ||
          entry.name === hoveredCell?.row.name ||
          entry.name === hoveredCell?.column.name ||
          entry.name === pinnedPair?.a ||
          entry.name === pinnedPair?.b
            ? 750
            : 550,
        );
      },
      {
        chartId: `correlation-${chartId}`,
        channel: "label-highlight",
        kind: "highlight",
        reducedMotion: shouldReduceMotion,
        markCount: labelSelection.size(),
        stagger: false,
      },
    );
  }, [
    chartId,
    hoveredCell,
    pinnedPair,
    selectedVariable,
    shouldReduceMotion,
  ]);

  const limitOptions = useMemo(() => {
    const maximum = Math.max(2, Math.min(MAX_SUBSET_LIMIT, columns.length || 2));
    return Array.from(
      new Set(
        [10, 12, 15, 20, 30, 40, 50, maximum]
          .map((value) => Math.min(value, maximum))
          .filter((value) => value >= 2),
      ),
    ).sort((left, right) => left - right);
  }, [columns.length]);

  const exportCsv = useCallback(() => {
    const header = ["Variable", ...matchingColumns.map((entry) => entry.name)]
      .map(csvCell)
      .join(",");
    const rows = matchingColumns.map((row) => {
      const values = matchingColumns.map((column) => {
        const direct = readCorrelation(matrix, row.sourceIndex, column.sourceIndex);
        const reverse = readCorrelation(matrix, column.sourceIndex, row.sourceIndex);
        const value = direct ?? reverse;
        if (
          value === null ||
          (row.sourceIndex !== column.sourceIndex &&
            Math.abs(value) + Number.EPSILON < absoluteThreshold)
        ) {
          return "";
        }
        return String(value);
      });
      return [csvCell(row.name), ...values].join(",");
    });
    const blob = new Blob([[header, ...rows].join("\r\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "atlas-correlation-matrix.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }, [absoluteThreshold, matchingColumns, matrix]);

  const zoomIn = useCallback(() => {
    setZoomMode("manual");
    setManualZoom(
      Math.max(
        MIN_MANUAL_ZOOM,
        Math.min(
          MAX_ZOOM,
          Math.round((effectiveZoom + ZOOM_STEP) * 100) / 100,
        ),
      ),
    );
  }, [effectiveZoom]);

  const zoomOut = useCallback(() => {
    setZoomMode("manual");
    setManualZoom(
      Math.max(
        MIN_MANUAL_ZOOM,
        Math.round((effectiveZoom - ZOOM_STEP) * 100) / 100,
      ),
    );
  }, [effectiveZoom]);

  const fitMatrix = useCallback(() => {
    setZoomMode("fit");
  }, []);

  const useReadableMode = useCallback(() => {
    setMatrixViewMode("readable");
    setZoomMode("manual");
    setManualZoom(1);
    frameRef.current?.scrollTo({
      left: 0,
      top: 0,
      behavior: shouldReduceMotion ? "auto" : "smooth",
    });
  }, [shouldReduceMotion]);

  const useCompactMode = useCallback(() => {
    setMatrixViewMode("compact");
    setZoomMode("fit");
    frameRef.current?.scrollTo({
      left: 0,
      top: 0,
      behavior: shouldReduceMotion ? "auto" : "smooth",
    });
  }, [shouldReduceMotion]);

  const resetZoom = useCallback(() => {
    setZoomMode("manual");
    setManualZoom(1);
    const frame = frameRef.current;
    if (frame) {
      frame.scrollTo({
        left: 0,
        top: 0,
        behavior: shouldReduceMotion ? "auto" : "smooth",
      });
    }
  }, [shouldReduceMotion]);

  const pinnedDetail = useMemo(() => {
    if (!pinnedPair) return null;
    const leftIndex = columns.indexOf(pinnedPair.a);
    const rightIndex = columns.indexOf(pinnedPair.b);
    const matrixValue =
      leftIndex >= 0 && rightIndex >= 0
        ? readCorrelation(matrix, leftIndex, rightIndex) ??
          readCorrelation(matrix, rightIndex, leftIndex)
        : null;
    const pair = {
      ...pinnedPair,
      correlation: matrixValue ?? pinnedPair.correlation ?? null,
    };
    return {
      pair,
      sampleSize:
        leftIndex >= 0 && rightIndex >= 0
          ? readSampleSize(correlationSampleSizes, leftIndex, rightIndex)
          : null,
      leftVif: normalizeVifValue(vifByFeature[pinnedPair.a]),
      rightVif: normalizeVifValue(vifByFeature[pinnedPair.b]),
    };
  }, [
    columns,
    correlationSampleSizes,
    matrix,
    pinnedPair,
    vifByFeature,
  ]);

  const visibleColumnIndices = useMemo(() => {
    if (!matchingColumns.length || !dimensions.cellSize) return [];
    const first = Math.max(
      0,
      Math.floor(
        (scrollState.left - dimensions.margin.left) / dimensions.cellSize,
      ),
    );
    const last = Math.min(
      matchingColumns.length - 1,
      Math.ceil(
        (scrollState.left +
          scrollState.clientWidth -
          dimensions.margin.left) /
          dimensions.cellSize,
      ),
    );
    return Array.from(
      { length: Math.max(0, last - first + 1) },
      (_value, index) => first + index,
    );
  }, [
    dimensions.cellSize,
    dimensions.margin.left,
    matchingColumns.length,
    scrollState.clientWidth,
    scrollState.left,
  ]);

  const visibleRowIndices = useMemo(() => {
    if (!matchingColumns.length || !dimensions.cellSize) return [];
    const first = Math.max(
      0,
      Math.floor(
        (scrollState.top - dimensions.margin.top) / dimensions.cellSize,
      ),
    );
    const last = Math.min(
      matchingColumns.length - 1,
      Math.ceil(
        (scrollState.top +
          scrollState.clientHeight -
          dimensions.margin.top) /
          dimensions.cellSize,
      ),
    );
    return Array.from(
      { length: Math.max(0, last - first + 1) },
      (_value, index) => first + index,
    );
  }, [
    dimensions.cellSize,
    dimensions.margin.top,
    matchingColumns.length,
    scrollState.clientHeight,
    scrollState.top,
  ]);

  const populatedCellCount = cells.filter(
    (cell) => cell.visible && !cell.diagonal,
  ).length;
  const tooltipLeft = hoveredCell
    ? Math.min(
        Math.max(12, hoveredCell.clientX + 14),
        Math.max(12, dimensions.width - 298),
      )
    : 0;
  const tooltipTop = hoveredCell
    ? Math.max(12, hoveredCell.clientY - 80)
    : 0;

  return (
    <>
      {isExpanded ? (
        <div
          className="fixed inset-0 z-[79] bg-slate-950/55 backdrop-blur-sm"
          aria-hidden="true"
          onClick={closeExpanded}
        />
      ) : null}
      <section
        ref={sectionRef}
        className={`rounded-2xl border border-slate-200 bg-white shadow-sm ${
          isExpanded
            ? "fixed inset-3 z-[80] max-h-[calc(100vh-1.5rem)] overflow-y-auto shadow-2xl sm:inset-6"
            : matrixViewMode === "compact"
              ? "overflow-hidden"
              : "overflow-visible"
        } ${className}`}
        aria-labelledby={`${chartId}-title`}
        aria-modal={isExpanded ? true : undefined}
        role={isExpanded ? "dialog" : undefined}
        tabIndex={isExpanded ? -1 : undefined}
        data-expanded={String(isExpanded)}
        data-view-mode={isExpanded ? "expanded" : matrixViewMode}
        data-testid="correlation-explorer"
      >
      <header className="rounded-t-2xl border-b border-slate-200 bg-slate-50/80 px-5 py-5 sm:px-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-2xl">
            <div className="mb-2 flex items-center gap-2">
              <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-blue-700">
                Full-population matrix
              </span>
              <span className="text-xs font-medium text-slate-500">
                Pearson correlation
              </span>
            </div>
            <h3
              id={`${chartId}-title`}
              className="text-lg font-semibold tracking-tight text-slate-950"
            >
              Correlation explorer
            </h3>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Search, focus, and pin relationships without changing the governed
              dataset. Ordering and thresholds affect this view and its export only.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={exportCsv}
              disabled={!matchingColumns.length}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3.5 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:border-slate-400 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Download aria-hidden="true" size={16} />
              Export current matrix
            </button>
            {isExpanded ? (
              <button
                ref={closeExpandedButtonRef}
                type="button"
                onClick={closeExpanded}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2"
                aria-label="Exit expanded correlation analysis"
              >
                <Minimize2 aria-hidden="true" size={16} />
                Exit expanded
              </button>
            ) : (
              <button
                ref={expandButtonRef}
                type="button"
                onClick={openExpanded}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2"
                data-testid="correlation-expand-matrix"
              >
                <Maximize2 aria-hidden="true" size={16} />
                Expand matrix
              </button>
            )}
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_150px_180px_minmax(220px,0.8fr)]">
          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-slate-700">
              Find a variable
            </span>
            <span className="relative block">
              <Search
                aria-hidden="true"
                size={16}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search full variable names"
                className="h-10 w-full rounded-lg border border-slate-300 bg-white pl-9 pr-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              />
            </span>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-slate-700">
              Variables shown
            </span>
            <select
              value={subsetLimit}
              onChange={(event) => {
                subsetLimitUserAdjustedRef.current = true;
                setSubsetLimit(Number(event.target.value));
              }}
              className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            >
              {limitOptions.map((value) => (
                <option key={value} value={value}>
                  Up to {value}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-slate-700">
              Matrix order
            </span>
            <select
              value={order}
              onChange={(event) => setOrder(event.target.value as MatrixOrder)}
              className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            >
              <option value="original">Dataset order</option>
              <option value="alphabetical">Alphabetical</option>
              <option value="clustered">Cluster similar variables</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 flex items-center justify-between gap-3 text-xs font-semibold text-slate-700">
              <span>Absolute threshold</span>
              <output className="font-semibold tabular-nums text-blue-700">
                ≥ {absoluteThreshold.toFixed(2)}
              </output>
            </span>
            <input
              type="range"
              min={0}
              max={0.95}
              step={0.05}
              value={absoluteThreshold}
              onChange={(event) =>
                setAbsoluteThreshold(Number(event.target.value))
              }
              className="h-10 w-full accent-blue-700"
              aria-label="Minimum absolute correlation displayed"
            />
          </label>
        </div>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3 text-xs text-slate-600 sm:px-6">
        <p aria-live="polite">
          <span className="font-semibold text-slate-900">
            {matchingColumns.length}
          </span>{" "}
          of {columns.length} variables ·{" "}
          <span className="font-semibold text-slate-900">
            {populatedCellCount}
          </span>{" "}
          off-diagonal cells visible
        </p>
        <div
          className="flex flex-wrap items-center gap-3"
          aria-label="Correlation color legend"
        >
          <span className="font-semibold text-slate-700">Correlation</span>
          <span className="font-semibold tabular-nums">−1</span>
          <span
            className="h-2.5 w-32 rounded-full border border-slate-200"
            style={{
              background:
                "linear-gradient(90deg, #1d4ed8 0%, #f8fafc 50%, #be123c 100%)",
            }}
            aria-hidden="true"
          />
          <span className="font-semibold tabular-nums">+1</span>
          <span className="inline-flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-sm border border-slate-200 bg-slate-100"
              aria-hidden="true"
            />
            below threshold
          </span>
        </div>
      </div>

      <div
        className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/80 px-5 py-2.5 sm:px-6"
        aria-label="Matrix zoom controls"
        data-testid="correlation-zoom-controls"
      >
        <div className="flex flex-wrap items-center gap-3">
          <div
            className="inline-flex rounded-lg border border-slate-300 bg-white p-1"
            role="group"
            aria-label="Correlation matrix display mode"
            data-testid="correlation-display-modes"
          >
            <button
              type="button"
              onClick={useReadableMode}
              aria-pressed={!isExpanded && matrixViewMode === "readable"}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                !isExpanded && matrixViewMode === "readable"
                  ? "bg-blue-700 text-white"
                  : "text-slate-700 hover:bg-slate-50"
              }`}
            >
              Readable
            </button>
            <button
              type="button"
              onClick={useCompactMode}
              aria-pressed={!isExpanded && matrixViewMode === "compact"}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                !isExpanded && matrixViewMode === "compact"
                  ? "bg-blue-700 text-white"
                  : "text-slate-700 hover:bg-slate-50"
              }`}
            >
              Compact
            </button>
            <button
              type="button"
              onClick={openExpanded}
              aria-pressed={isExpanded}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                isExpanded
                  ? "bg-slate-950 text-white"
                  : "text-slate-700 hover:bg-slate-50"
              }`}
            >
              Expanded matrix
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={zoomOut}
            disabled={effectiveZoom <= MIN_MANUAL_ZOOM}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 disabled:opacity-45"
            aria-label="Zoom out correlation matrix"
          >
            <ZoomOut aria-hidden="true" size={15} />
            Zoom out
          </button>
          <button
            type="button"
            onClick={zoomIn}
            disabled={effectiveZoom >= MAX_ZOOM}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 disabled:opacity-45"
            aria-label="Zoom in correlation matrix"
          >
            <ZoomIn aria-hidden="true" size={15} />
            Zoom in
          </button>
          <button
            type="button"
            onClick={fitMatrix}
            className={`inline-flex min-h-9 items-center gap-1.5 rounded-md border px-2.5 text-xs font-semibold shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${
              zoomMode === "fit"
                ? "border-blue-700 bg-blue-700 text-white"
                : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
            }`}
            aria-pressed={zoomMode === "fit"}
          >
            <Expand aria-hidden="true" size={15} />
            Auto-fit · Fit matrix
          </button>
          <button
            type="button"
            onClick={resetZoom}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
            aria-label="Reset correlation matrix zoom and scroll"
          >
            <RotateCcw aria-hidden="true" size={15} />
            Reset
          </button>
          </div>
        </div>
        <p className="text-xs text-slate-600" aria-live="polite">
          <span className="font-semibold text-slate-900">
            {Math.round(effectiveZoom * 100)}%
          </span>{" "}
          · {Math.round(dimensions.cellSize)}px cells
          {zoomMode === "fit"
            ? " · fitted overview"
            : matrixViewMode === "readable"
              ? " · complete readable matrix"
              : " · compact scroll mode"}
        </p>
      </div>

      <div className="relative bg-white">
        <div
          ref={frameRef}
          className={
            isExpanded
              ? "relative overflow-auto overscroll-contain max-h-[calc(100vh-19rem)] min-h-[22rem]"
              : matrixViewMode === "compact"
                ? "relative overflow-auto overscroll-contain max-h-[34rem]"
                : "relative overflow-visible"
          }
          onScroll={handleFrameScroll}
          data-testid="correlation-matrix-scroll-frame"
          data-zoom-mode={zoomMode}
          data-view-mode={isExpanded ? "expanded" : matrixViewMode}
          data-default-vertical-scroll={
            !isExpanded && matrixViewMode === "readable" ? "false" : "bounded"
          }
          data-scroll-boundary={
            !isExpanded && matrixViewMode === "readable" ? "page" : "nested"
          }
          data-matrix-height={dimensions.height.toFixed(0)}
          data-cell-size={dimensions.cellSize.toFixed(2)}
        >
        {matchingColumns.length ? (
          <svg
            ref={svgRef}
            width={dimensions.width}
            height={dimensions.height}
            className="block max-w-none"
            role="group"
            aria-roledescription="interactive correlation matrix"
            aria-labelledby={`${chartId}-svg-title ${chartId}-svg-description`}
            data-testid="correlation-matrix-svg"
          >
            <title id={`${chartId}-svg-title`}>Interactive correlation matrix</title>
            <desc id={`${chartId}-svg-description`}>
              {matchingColumns.length} by {matchingColumns.length} Pearson
              correlation matrix. Use Tab to focus visible cells and Enter to pin
              a pair. Exact values are also available in the data table below.
            </desc>
            <g data-layer="matrix-root">
              <g data-layer="background" />
              <g data-layer="cells" />
              <g data-layer="values" />
              <g data-layer="row-labels" />
              <g data-layer="column-labels" />
            </g>
          </svg>
        ) : (
          <div className="flex min-h-72 items-center justify-center px-6 py-12 text-center">
            <div>
              <p className="font-semibold text-slate-900">
                No variables match this view
              </p>
              <p className="mt-1 text-sm text-slate-500">
                Clear the search or increase the subset to restore the matrix.
              </p>
            </div>
          </div>
        )}

        {hoveredCell?.visible && hoveredCell.value !== null ? (
          <div
            role="status"
            aria-live="polite"
            className="pointer-events-none absolute z-10 w-72 rounded-xl border border-slate-700/20 bg-slate-950 px-3.5 py-3 text-white shadow-2xl"
            style={{ left: tooltipLeft, top: tooltipTop }}
            data-testid="correlation-tooltip"
          >
            <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-200">
              Pearson correlation
            </div>
            <div className="mt-1 break-words text-sm font-semibold leading-5">
              {hoveredCell.row.name} × {hoveredCell.column.name}
            </div>
            <div className="mt-2 flex items-end justify-between gap-4">
              <span className="text-xs text-slate-300">Exact value</span>
              <span className="text-lg font-bold tabular-nums">
                {CORRELATION_DETAIL_FORMAT.format(hoveredCell.value)}
              </span>
            </div>
            {!hoveredCell.diagonal ? (
              <div className="mt-2 border-t border-white/10 pt-2 text-[11px] text-slate-300">
                Click or press Enter to pin this pair.
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

        {matchingColumns.length ? (
          <div
            className="pointer-events-none absolute inset-0 z-20 overflow-hidden"
            aria-hidden="true"
            data-testid="correlation-sticky-labels"
          >
            <div
              className="absolute left-0 right-0 top-0 border-b border-slate-300 bg-white/95 shadow-sm backdrop-blur"
              style={{ height: Math.min(96, dimensions.margin.top - 18) }}
              data-testid="correlation-sticky-column-labels"
            >
              {visibleColumnIndices.map((index) => {
                const entry = matchingColumns[index];
                if (!entry) return null;
                const highlighted =
                  entry.name === selectedVariable ||
                  entry.name === hoveredCell?.row.name ||
                  entry.name === hoveredCell?.column.name ||
                  entry.name === pinnedPair?.a ||
                  entry.name === pinnedPair?.b;
                return (
                  <div
                    key={`sticky-column-${entry.key}`}
                    className={`absolute bottom-0 flex items-end justify-center overflow-hidden border-l border-slate-100 px-1 pb-2 text-[10px] font-semibold leading-tight ${
                      highlighted
                        ? "bg-blue-50/95 text-slate-950"
                        : "text-slate-600"
                    }`}
                    style={{
                      left:
                        dimensions.margin.left +
                        index * dimensions.cellSize -
                        scrollState.left,
                      width: dimensions.cellSize,
                      height: Math.min(96, dimensions.margin.top - 18),
                    }}
                  >
                    <span
                      className="block max-h-[82px] overflow-hidden"
                      style={{
                        writingMode: "vertical-rl",
                        transform: "rotate(180deg)",
                      }}
                    >
                      {entry.name}
                    </span>
                  </div>
                );
              })}
            </div>

            <div
              className="absolute bottom-0 left-0 top-0 border-r border-slate-300 bg-white/95 shadow-sm backdrop-blur"
              style={{ width: dimensions.margin.left }}
              data-testid="correlation-sticky-row-labels"
            >
              {visibleRowIndices.map((index) => {
                const entry = matchingColumns[index];
                if (!entry) return null;
                const highlighted =
                  entry.name === selectedVariable ||
                  entry.name === hoveredCell?.row.name ||
                  entry.name === hoveredCell?.column.name ||
                  entry.name === pinnedPair?.a ||
                  entry.name === pinnedPair?.b;
                return (
                  <div
                    key={`sticky-row-${entry.key}`}
                    className={`absolute left-0 flex items-center justify-end overflow-hidden border-t border-slate-100 px-3 text-right text-xs font-semibold ${
                      highlighted
                        ? "bg-blue-50/95 text-slate-950"
                        : "text-slate-700"
                    }`}
                    style={{
                      top:
                        dimensions.margin.top +
                        index * dimensions.cellSize -
                        scrollState.top,
                      width: dimensions.margin.left,
                      height: dimensions.cellSize,
                    }}
                    title={entry.name}
                  >
                    <span className="block max-w-full truncate">
                      {entry.name}
                    </span>
                  </div>
                );
              })}
            </div>

            <div
              className="absolute left-0 top-0 flex items-end border-b border-r border-slate-300 bg-slate-100 px-3 pb-2 text-xs font-bold uppercase tracking-wide text-slate-700"
              style={{
                width: dimensions.margin.left,
                height: Math.min(96, dimensions.margin.top - 18),
              }}
            >
              Variable
            </div>
          </div>
        ) : null}
      </div>

      {pinnedDetail ? (
        <section
          className="border-t border-blue-200 bg-gradient-to-r from-blue-50 via-white to-indigo-50 px-5 py-5 sm:px-6"
          aria-labelledby={`${chartId}-pinned-title`}
          data-testid="correlation-pinned-pair-detail"
        >
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0">
              <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-700">
                Pinned relationship
              </div>
              <h4
                id={`${chartId}-pinned-title`}
                className="mt-1 break-words text-base font-semibold leading-6 text-slate-950"
              >
                {pinnedDetail.pair.a}
                <span className="mx-2 text-slate-400" aria-hidden="true">
                  ↔
                </span>
                <span className="sr-only"> and </span>
                {pinnedDetail.pair.b}
              </h4>
              <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-600">
                Correlation uses pairwise complete observations. VIF values use
                the separately disclosed bounded complete-case backend cohort;
                “Not evaluated” means a feature was outside that cohort.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => onLaunch2D?.(pinnedDetail.pair)}
                disabled={!onLaunch2D}
                className="inline-flex min-h-10 items-center justify-center rounded-lg border border-blue-300 bg-white px-3.5 text-sm font-semibold text-blue-800 shadow-sm hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 disabled:cursor-not-allowed disabled:opacity-45"
              >
                Launch 2D scatter
              </button>
              <button
                type="button"
                onClick={() => onLaunch3D?.(pinnedDetail.pair)}
                disabled={!onLaunch3D}
                className="inline-flex min-h-10 items-center justify-center rounded-lg bg-blue-700 px-3.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-45"
              >
                Launch 3D explorer
              </button>
            </div>
          </div>

          <dl className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            {[
              [
                "Exact correlation",
                pinnedDetail.pair.correlation === null ||
                pinnedDetail.pair.correlation === undefined
                  ? "Not available"
                  : CORRELATION_DETAIL_FORMAT.format(
                      pinnedDetail.pair.correlation,
                    ),
              ],
              [
                "Sign",
                correlationSign(pinnedDetail.pair.correlation ?? null),
              ],
              [
                "Pairwise N",
                pinnedDetail.sampleSize === null
                  ? "Not returned"
                  : INTEGER_FORMAT.format(pinnedDetail.sampleSize),
              ],
              [
                `VIF · ${pinnedDetail.pair.a}`,
                formatVif(pinnedDetail.leftVif),
              ],
              [
                `VIF · ${pinnedDetail.pair.b}`,
                formatVif(pinnedDetail.rightVif),
              ],
            ].map(([label, value]) => (
              <div
                key={label}
                className="min-w-0 rounded-lg border border-slate-200 bg-white px-3 py-3 shadow-sm"
              >
                <dt className="break-words text-[10px] font-bold uppercase tracking-wide text-slate-500">
                  {label}
                </dt>
                <dd className="mt-1 break-words text-sm font-semibold tabular-nums text-slate-950">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      <details className="group border-t border-slate-200">
        <summary className="cursor-pointer list-none px-5 py-4 text-sm font-semibold text-slate-800 outline-none transition hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600 sm:px-6">
          <span className="inline-flex items-center gap-2">
            <span
              aria-hidden="true"
              className="text-slate-400 transition-transform group-open:rotate-90"
            >
              ▸
            </span>
            Accessible data table
          </span>
        </summary>
        <div className="max-h-[32rem] overflow-auto border-t border-slate-200">
          <table className="min-w-full border-separate border-spacing-0 text-xs">
            <caption className="sr-only">
              Current Pearson correlation matrix. Values below the selected
              threshold are omitted.
            </caption>
            <thead className="sticky top-0 z-[2] bg-slate-100 text-slate-700">
              <tr>
                <th
                  scope="col"
                  className="sticky left-0 z-[3] border-b border-r border-slate-200 bg-slate-100 px-3 py-2 text-left font-semibold"
                >
                  Variable
                </th>
                {matchingColumns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className="min-w-40 max-w-64 border-b border-slate-200 px-3 py-2 text-right font-semibold"
                    title={column.name}
                  >
                    <span className="block whitespace-normal break-words">
                      {column.name}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matchingColumns.map((row) => (
                <tr key={row.key} className="odd:bg-white even:bg-slate-50/60">
                  <th
                    scope="row"
                    title={row.name}
                    className="sticky left-0 z-[1] min-w-56 max-w-sm border-r border-slate-200 bg-inherit px-3 py-2 text-left font-semibold text-slate-800"
                  >
                    <span className="block whitespace-normal break-words">
                      {row.name}
                    </span>
                  </th>
                  {matchingColumns.map((column) => {
                    const direct = readCorrelation(
                      matrix,
                      row.sourceIndex,
                      column.sourceIndex,
                    );
                    const reverse = readCorrelation(
                      matrix,
                      column.sourceIndex,
                      row.sourceIndex,
                    );
                    const value = direct ?? reverse;
                    const visible =
                      value !== null &&
                      (row.sourceIndex === column.sourceIndex ||
                        Math.abs(value) + Number.EPSILON >= absoluteThreshold);
                    return (
                      <td
                        key={column.key}
                        className="border-b border-slate-100 px-3 py-2 text-right tabular-nums text-slate-700"
                      >
                        {visible && value !== null
                          ? NUMBER_FORMAT.format(value)
                          : "—"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      </section>
    </>
  );
}
