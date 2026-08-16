import ModelingApp from "./apps/ModelingApp";
import ErrorBoundary from "./components/ErrorBoundary";

export default function AtlasApp() {
  return (
    <ErrorBoundary title="ASP Model Studio could not render the application workspace safely.">
      <ModelingApp />
    </ErrorBoundary>
  );
}
