"""Build a reduced point/Elo research export only with actual captured inputs."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_nba_gen1.authority import reference
from server.sports_nba_gen1.point_forecast import PointForecastUnavailable, build_point_forecast, export_point_forecast


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-receipt", required=True)
    parser.add_argument("--schedule-evidence", required=True)
    parser.add_argument("--history-coverage", required=True)
    parser.add_argument("--source-cutoff", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        forecast = build_point_forecast(reference(args.current_receipt), reference(args.schedule_evidence),
                                        reference(args.history_coverage), args.source_cutoff)
        print(json.dumps({"status": "EXPORTED_LOCAL_RESEARCH_ONLY", "index": export_point_forecast(forecast, args.output)}))
    except (PointForecastUnavailable, FileNotFoundError, KeyError, ValueError) as error:
        print(json.dumps({"status": "UNAVAILABLE_NO_FORECAST_EXPORTED", "reason": str(error)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
