import type { TimeSeriesPageKey } from "./timeSeriesTypes";

export const timeSeriesCodeTemplates: Record<TimeSeriesPageKey, string[]> = {
  "project-context": [
    "forecast_context = {",
    "    'goal': study_goal,",
    "    'target_outcome': target_outcome,",
    "    'horizon': forecast_horizon,",
    "    'cadence': decision_cadence,",
    "    'governance_context': governance_context,",
    "}",
  ],
  "data-acquisition": [
    "dataset = atlas.dataset_library.load_dataset(dataset_id=dataset_id, version_id=version_id)",
    "df[time_col] = pd.to_datetime(df[time_col], errors='coerce', utc=True)",
    "grain = [time_col, *entity_cols]",
    "series = df.groupby(grain)[target_col].agg(aggregation_method).reset_index()",
    "series = atlas.timeseries.apply_frequency(series, date_col=time_col, freq=frequency)",
    "quality = atlas.timeseries.profile_timestamp_gaps(series, time_col, entity_cols)",
    "atlas.evidence.save('time_series_input_bundle', mapping=mapping, quality=quality)",
    "/* SAS: PROC TIMESERIES DATA=source INTERVAL=DAY ACCUMULATE=TOTAL; ID date; VAR sales; BY store item; RUN; */",
  ],
  profile: [
    "rolling_mean = series.rolling(window=rolling_window).mean()",
    "rolling_volatility = series.rolling(window=rolling_window).std()",
    "acf_values = acf(series.dropna(), nlags=24)",
    "anomalies = detect_temporal_anomalies(series, sensitivity=anomaly_sensitivity)",
  ],
  "feature-calendar-design": [
    "features['lag_1'] = target.shift(1)",
    "features['rolling_mean_7'] = target.shift(1).rolling(7).mean()",
    "features['month_end'] = time_index.is_month_end.astype(int)",
    "assert all_future_drivers_known_at_forecast_time(feature_plan)",
  ],
  "backtest-design": [
    "for cutoff in rolling_origin_cutoffs:",
    "    train = df[df.date <= cutoff]",
    "    validation = df[(df.date > cutoff + gap) & (df.date <= cutoff + horizon)]",
    "    folds.append({'cutoff': cutoff, 'train': train, 'validation': validation})",
  ],
  "model-configuration": [
    "candidates = [Naive(), SeasonalNaive(), ETS(), SarimaTemplate(), LagBoosting()]",
    "config = {'intervals': interval_level, 'refit_cadence': refit_cadence, 'seed': seed}",
    "queue = build_forecast_training_queue(candidates, config)",
  ],
  "train-backtest": [
    "if backend_available:",
    "    run_record = train_and_backtest(queue, folds)",
    "else:",
    "    run_record = preview_backtest_run(queue, folds)",
    "persist_run_record('time_series_backtest', run_record)",
  ],
  "forecast-results": [
    "forecast = champion.predict(horizon=horizon, intervals=True)",
    "forecast[['period', 'entity', 'forecast', 'lower', 'upper']].to_csv('forecast.csv', index=False)",
  ],
  "diagnostics-stability": [
    "residuals = actuals - forecasts",
    "diagnostics = compute_residual_acf_bias_coverage(residuals, forecast_horizon)",
    "segment_errors = summarize_error_by_entity(residuals, entity_col)",
  ],
  "scenario-stress": [
    "scenario_forecast = apply_stress(base_forecast, shock_type, magnitude, duration)",
    "scenario_forecast['delta'] = scenario_forecast.forecast - base_forecast.forecast",
    "risk_flags = classify_scenario_impact(scenario_forecast)",
  ],
  "recommendation-monitoring": [
    "monitoring_table = pd.DataFrame(threshold_rows)",
    "recommendation = build_forecast_recommendation(evidence, monitoring_table)",
    "persist_evidence('time_series_monitoring_plan', recommendation)",
  ],
  documentation: [
    "package = assemble_time_series_governance_package(evidence_inventory)",
    "export_governed_json(package)",
    "export_forecast_csv(forecast)",
    "export_backtest_results_csv(backtest_results)",
  ],
};
