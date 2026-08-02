export type WorkflowActionBarRect = {
  left: number;
  right: number;
};

export type WorkflowActionBarBounds = {
  left: number;
  width: number;
};

const VIEWPORT_GUTTER_PX = 12;
const CONTENT_CLEARANCE_PX = 24;
const DEFAULT_BAR_HEIGHT_PX = 120;

function roundLayoutPixel(value: number) {
  return Math.round(value * 100) / 100;
}

/**
 * Constrains a viewport-fixed workflow action bar to the measured workflow
 * column. The column measurement already accounts for the sidebar, centered
 * max-width container, responsive page padding, and current Atlas Guide mode.
 */
export function resolveWorkflowActionBarBounds(
  rect: WorkflowActionBarRect,
  viewportWidth: number,
): WorkflowActionBarBounds {
  const safeViewportWidth = Number.isFinite(viewportWidth)
    ? Math.max(viewportWidth, VIEWPORT_GUTTER_PX * 2)
    : VIEWPORT_GUTTER_PX * 2;
  const viewportRight = safeViewportWidth - VIEWPORT_GUTTER_PX;
  const measuredLeft = Number.isFinite(rect.left) ? rect.left : VIEWPORT_GUTTER_PX;
  const measuredRight = Number.isFinite(rect.right) ? rect.right : viewportRight;
  const left = Math.min(Math.max(measuredLeft, VIEWPORT_GUTTER_PX), viewportRight);
  const right = Math.min(Math.max(measuredRight, left), viewportRight);

  return {
    left: roundLayoutPixel(left),
    width: roundLayoutPixel(right - left),
  };
}

/** Keeps the last page content fully visible above the fixed action bar. */
export function workflowActionBarClearance(barHeight: number) {
  const safeHeight = Number.isFinite(barHeight)
    ? Math.max(0, barHeight)
    : DEFAULT_BAR_HEIGHT_PX;
  return Math.ceil(safeHeight + CONTENT_CLEARANCE_PX);
}

