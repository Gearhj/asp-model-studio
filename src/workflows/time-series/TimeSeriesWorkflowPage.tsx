import { useParams } from "react-router-dom";
import TimeSeriesProjectContext from "./TimeSeriesProjectContext";
import TimeSeriesDataAcquisition from "./TimeSeriesDataAcquisition";
import TimeSeriesProfile from "./TimeSeriesProfile";
import TimeSeriesFeatureCalendarDesign from "./TimeSeriesFeatureCalendarDesign";
import TimeSeriesBacktestDesign from "./TimeSeriesBacktestDesign";
import TimeSeriesModelConfiguration from "./TimeSeriesModelConfiguration";
import TimeSeriesTrainBacktest from "./TimeSeriesTrainBacktest";
import TimeSeriesForecastResults from "./TimeSeriesForecastResults";
import TimeSeriesDiagnosticsStability from "./TimeSeriesDiagnosticsStability";
import TimeSeriesScenarioStress from "./TimeSeriesScenarioStress";
import TimeSeriesRecommendationMonitoring from "./TimeSeriesRecommendationMonitoring";
import TimeSeriesDocumentation from "./TimeSeriesDocumentation";

const pages = [
  TimeSeriesProjectContext,
  TimeSeriesDataAcquisition,
  TimeSeriesProfile,
  TimeSeriesFeatureCalendarDesign,
  TimeSeriesBacktestDesign,
  TimeSeriesModelConfiguration,
  TimeSeriesTrainBacktest,
  TimeSeriesForecastResults,
  TimeSeriesDiagnosticsStability,
  TimeSeriesScenarioStress,
  TimeSeriesRecommendationMonitoring,
  TimeSeriesDocumentation,
];

export default function TimeSeriesWorkflowPage() {
  const { stepNumber } = useParams();
  const index = Math.max(0, Math.min(pages.length - 1, Number(stepNumber ?? 1) - 1));
  const Page = pages[index] ?? TimeSeriesProjectContext;
  return <Page />;
}
