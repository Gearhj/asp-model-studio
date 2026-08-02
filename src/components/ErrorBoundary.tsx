// src/components/ErrorBoundary.tsx
import React from "react";

type ErrorBoundaryProps = {
  children: React.ReactNode;
  title?: string;
  /** Optional UI to show when an error occurs */
  fallback?: React.ReactNode;
  /** Optional hook for logging */
  onError?: (error: Error, info: React.ErrorInfo) => void;
  /** Clears a captured route error after the project or route changes. */
  resetKey?: string;
};

type ErrorBoundaryState = {
  hasError: boolean;
  error?: Error;
  info?: React.ErrorInfo;
  diagnosticId?: string;
};

class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      error,
      diagnosticId: `atlas-ui-${Date.now().toString(36)}`,
    };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    this.setState({ info });
    if (this.props.onError) this.props.onError(error, info);
    // Keep this console for local debugging; remove if you prefer quieter logs.
    console.error("[ErrorBoundary]", error, info);
  }

  componentDidUpdate(previousProps: ErrorBoundaryProps) {
    if (
      this.state.hasError
      && previousProps.resetKey !== this.props.resetKey
    ) {
      this.reset();
    }
  }

  reset = () => this.setState({ hasError: false, error: undefined, info: undefined, diagnosticId: undefined });

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return <>{this.props.fallback}</>;
      return (
        <div className="rounded-xl border border-red-300 bg-red-50 p-4 text-red-800" data-testid="atlas-safe-error-boundary">
          <div className="font-semibold mb-2">
            {this.props.title ?? "Something went wrong while rendering this section."}
          </div>
          <p className="text-sm leading-6">
            ATLAS stopped this section safely. No workflow decision or dataset identity was changed.
          </p>
          <p className="mt-1 text-xs font-medium text-red-700">
            Diagnostic reference: {this.state.diagnosticId ?? "atlas-ui-render"}
          </p>
          <button
            className="mt-3 px-3 py-1 rounded-lg bg-white border border-red-300"
            onClick={this.reset}
            type="button"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;         // <-- default export (fixes your import)
export { ErrorBoundary };             // named export (optional)
