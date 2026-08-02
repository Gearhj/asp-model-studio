export type ProjectRegistryLoadStatus = "idle" | "loading" | "success" | "empty" | "error";

export type ProjectRegistryLoadErrorKind =
  | "authentication"
  | "authorization"
  | "network"
  | "response"
  | "server"
  | "unknown";

export type ProjectRegistryLoadError = {
  kind: ProjectRegistryLoadErrorKind;
  message: string;
  status?: number;
};

export type ProjectRegistryLoadState<T> = {
  status: ProjectRegistryLoadStatus;
  requestId: number;
  projects: T[];
  error: ProjectRegistryLoadError | null;
};

export class ProjectRegistryResponseValidationError extends Error {
  readonly code = "invalid_response";

  constructor(message = "The project registry returned an invalid response.") {
    super(message);
    this.name = "ProjectRegistryResponseValidationError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function errorStatus(error: unknown): number | undefined {
  if (!isRecord(error)) return undefined;
  const value = error.status;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function errorCode(error: unknown): string {
  if (!isRecord(error)) return "";
  return typeof error.code === "string" ? error.code : "";
}

export function isProjectRegistryAbortError(error: unknown): boolean {
  return isRecord(error) && error.name === "AbortError";
}

export function isProjectRegistryProject(value: unknown): value is { projectId: string } {
  return isRecord(value) && typeof value.projectId === "string" && value.projectId.trim().length > 0;
}

export function validateProjectRegistryResponse<T>(
  value: unknown,
  isProject: (project: unknown) => project is T = isProjectRegistryProject as (project: unknown) => project is T,
): T[] {
  const projects = Array.isArray(value)
    ? value
    : isRecord(value) && Array.isArray(value.projects)
      ? value.projects
      : null;

  if (!projects) {
    throw new ProjectRegistryResponseValidationError(
      "The project registry returned an invalid response: expected a projects array.",
    );
  }

  if (!projects.every(isProject)) {
    throw new ProjectRegistryResponseValidationError(
      "The project registry returned an invalid response: every project must include a non-empty projectId.",
    );
  }

  return projects;
}

export function classifyProjectRegistryLoadError(error: unknown): ProjectRegistryLoadError | null {
  if (isProjectRegistryAbortError(error)) return null;

  const status = errorStatus(error);
  if (status === 401) {
    return {
      kind: "authentication",
      status,
      message: "Your session is not authenticated. Sign in again to open ATLAS projects.",
    };
  }
  if (status === 403) {
    return {
      kind: "authorization",
      status,
      message: "You are signed in, but you do not have permission to view the ATLAS project registry.",
    };
  }

  if (
    error instanceof ProjectRegistryResponseValidationError
    || errorCode(error) === "invalid_response"
    || (isRecord(error) && (
      error.name === "PersistenceResponseValidationError"
      || error.name === "ProjectRegistryResponseValidationError"
    ))
  ) {
    return {
      kind: "response",
      message: error instanceof Error
        ? error.message
        : "The project registry returned an invalid response.",
    };
  }

  if (error instanceof TypeError) {
    return {
      kind: "network",
      message: "The project registry request could not reach ATLAS. Check the service and retry.",
    };
  }

  if (typeof status === "number" && status >= 500) {
    return {
      kind: "server",
      status,
      message: `The project registry service failed with HTTP ${status}. Retry when the service is available.`,
    };
  }

  return {
    kind: "unknown",
    ...(status === undefined ? {} : { status }),
    message: status === undefined
      ? "The project registry request failed. Retry the request."
      : `The project registry request failed with HTTP ${status}.`,
  };
}

export function initialProjectRegistryLoadState<T>(): ProjectRegistryLoadState<T> {
  return { status: "idle", requestId: 0, projects: [], error: null };
}

export function startProjectRegistryLoad<T>(
  _current: ProjectRegistryLoadState<T>,
  requestId: number,
): ProjectRegistryLoadState<T> {
  return { status: "loading", requestId, projects: [], error: null };
}

export function resolveProjectRegistryLoad<T>(
  current: ProjectRegistryLoadState<T>,
  requestId: number,
  projects: T[],
): ProjectRegistryLoadState<T> {
  if (current.requestId !== requestId || current.status !== "loading") return current;
  return {
    status: projects.length > 0 ? "success" : "empty",
    requestId,
    projects: [...projects],
    error: null,
  };
}

export function rejectProjectRegistryLoad<T>(
  current: ProjectRegistryLoadState<T>,
  requestId: number,
  error: unknown,
): ProjectRegistryLoadState<T> {
  if (current.requestId !== requestId || current.status !== "loading") return current;
  const classified = classifyProjectRegistryLoadError(error);
  if (!classified) return current;
  return { status: "error", requestId, projects: [], error: classified };
}

export function formatProjectRegistryLoadError(error: ProjectRegistryLoadError | null): string {
  return error?.message ?? "";
}

export type ProjectRegistryLoadControllerOptions<T> = {
  loadProjects: (signal: AbortSignal) => Promise<unknown>;
  onStateChange?: (state: ProjectRegistryLoadState<T>) => void;
  validate?: (value: unknown) => T[];
};

export class ProjectRegistryLoadController<T> {
  private generation = 0;
  private activeController: AbortController | null = null;
  private state: ProjectRegistryLoadState<T> = initialProjectRegistryLoadState<T>();
  private readonly loadProjects: ProjectRegistryLoadControllerOptions<T>["loadProjects"];
  private readonly onStateChange?: ProjectRegistryLoadControllerOptions<T>["onStateChange"];
  private readonly validate: (value: unknown) => T[];

  constructor(options: ProjectRegistryLoadControllerOptions<T>) {
    this.loadProjects = options.loadProjects;
    this.onStateChange = options.onStateChange;
    this.validate = options.validate ?? ((value) => validateProjectRegistryResponse<T>(value));
  }

  getState(): ProjectRegistryLoadState<T> {
    return this.state;
  }

  async load(): Promise<ProjectRegistryLoadState<T>> {
    const requestId = ++this.generation;
    this.activeController?.abort();
    const controller = new AbortController();
    this.activeController = controller;
    this.update(startProjectRegistryLoad(this.state, requestId));

    try {
      const value = await this.loadProjects(controller.signal);
      if (requestId !== this.generation || controller.signal.aborted) return this.state;
      const projects = this.validate(value);
      this.update(resolveProjectRegistryLoad(this.state, requestId, projects));
    } catch (error) {
      if (requestId !== this.generation || controller.signal.aborted || isProjectRegistryAbortError(error)) {
        return this.state;
      }
      this.update(rejectProjectRegistryLoad(this.state, requestId, error));
    } finally {
      if (this.activeController === controller) this.activeController = null;
    }

    return this.state;
  }

  dispose(): void {
    this.generation += 1;
    this.activeController?.abort();
    this.activeController = null;
  }

  private update(state: ProjectRegistryLoadState<T>): void {
    this.state = state;
    this.onStateChange?.(state);
  }
}

export function createProjectRegistryLoadController<T>(
  options: ProjectRegistryLoadControllerOptions<T>,
): ProjectRegistryLoadController<T> {
  return new ProjectRegistryLoadController(options);
}
