import { useSyncExternalStore } from "react";

export const REDUCED_MOTION_MEDIA_QUERY = "(prefers-reduced-motion: reduce)";

type MediaQueryListLike = {
  matches: boolean;
  addEventListener?: (type: "change", listener: () => void) => void;
  removeEventListener?: (type: "change", listener: () => void) => void;
  /** Safari compatibility for older embedded WebKit builds. */
  addListener?: (listener: () => void) => void;
  removeListener?: (listener: () => void) => void;
};

export type MatchMediaLike = (query: string) => MediaQueryListLike;

function browserMatchMedia(): MatchMediaLike | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia.bind(window) as MatchMediaLike;
}

export function readReducedMotionPreference(matchMedia: MatchMediaLike | null = browserMatchMedia()): boolean {
  return matchMedia?.(REDUCED_MOTION_MEDIA_QUERY).matches === true;
}

export function subscribeReducedMotionPreference(
  onStoreChange: () => void,
  matchMedia: MatchMediaLike | null = browserMatchMedia(),
): () => void {
  if (!matchMedia) return () => undefined;
  const media = matchMedia(REDUCED_MOTION_MEDIA_QUERY);
  const listener = () => onStoreChange();
  if (media.addEventListener && media.removeEventListener) {
    media.addEventListener("change", listener);
    return () => media.removeEventListener?.("change", listener);
  }
  media.addListener?.(listener);
  return () => media.removeListener?.(listener);
}

/**
 * Reactive reduced-motion preference. Unlike a one-time `matchMedia().matches`
 * read, this updates an already-mounted chart when the operating-system setting
 * changes.
 */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotionPreference,
    readReducedMotionPreference,
    () => false,
  );
}
