// src/state/stepOrder.ts
export const WORKFLOW_ORDER = [
  "/step01",
  "/step02",
  "/step03",
  "/step04",
  "/step05",
  "/step06",
  "/step07",
  "/step08",
  "/step09",
] as const;

export type StepPath = typeof WORKFLOW_ORDER[number];

export const getNextPath = (from: StepPath): StepPath | null => {
  const i = WORKFLOW_ORDER.indexOf(from);
  if (i < 0 || i >= WORKFLOW_ORDER.length - 1) return null;
  return WORKFLOW_ORDER[i + 1];
};
