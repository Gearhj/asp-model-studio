"""One retained 2026 row checks feature equivalence; no forecast is generated."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from server.sports_nba_gen1.authority import reference
from server.sports_nba_gen1.point_forecast import build_target_features
from server.sports_nba_gen1.recent_features import FEATURE_COLUMNS


root = Path(__file__).resolve().parents[1] / "outputs/nba-gen1-long-gap-v1"
output = root / "point-snapshot-verification.json"
if output.exists():
    raise ValueError("Preserve the existing verification receipt")
paths = {"features": root / "assessment-2026/features.parquet", "games": root / "assessment-2026/games.parquet",
         "metadata": root / "scope-metadata-2026.parquet", "context": root / "assessment-2026/history-context.json"}
before = {key: reference(path) for key, path in paths.items()}
features, games, metadata = [pd.read_parquet(paths[key]) for key in ("features", "games", "metadata")]
row = features[features.season_end.eq(2026) & features.target_eligible].iloc[0]
source = metadata[metadata.id.astype(str).eq(row.game_id.rsplit(":", 1)[-1])].iloc[0]
target = {key: row[key] for key in ("game_id", "game_date", "home_team_id", "away_team_id", "home_team_code", "away_team_code")}
target.update(source_game_id=str(source.id), season_end=int(row.season_end), neutral_site=False, status="SCHEDULED",
              season_type="REGULAR", scheduled_tipoff_utc=pd.Timestamp(source.date).isoformat(),
              source_revision="RETAINED_FINAL_EXPORT_FEATURE_EQUIVALENCE_ONLY")
context = json.loads(paths["context"].read_bytes())["contextOnlyEvents"]
reproduced, audit = build_target_features(games, target, context)
actual = reproduced.iloc[0][list(FEATURE_COLUMNS)].to_numpy(float)
expected = row[list(FEATURE_COLUMNS)].to_numpy(float)
np.testing.assert_array_equal(actual, expected)
assert before == {key: reference(path) for key, path in paths.items()}
result = {"schema": "nba-gen1-point-target-snapshot-equivalence-v1", "createdAtUtc": datetime.now(timezone.utc).isoformat(),
          "gameId": row.game_id, "gameDate": row.game_date, "numericFeatures": 78,
          "allNumericValuesExactlyEqualIncludingMissingness": True, "maximumAbsoluteFiniteDifference": float(np.nanmax(np.abs(actual - expected))),
          "inputsUnchanged": True, "inputs": before, "featureAudit": audit,
          "forecastExecutable": reference(Path(__file__).resolve().parents[1] / "server/sports_nba_gen1/point_forecast.py"),
          "verificationScript": reference(Path(__file__)),
          "qualification": "One already-assessed 2026 row verifies calculation equivalence. Harness status=SCHEDULED and revision label exercise the identity-only API; they are not historical schedule captures. Actual retained final-export tipoff/date are used. Target/same-date/later scores are metadata-excluded before feature construction. No target final is fabricated and no forecast/probability is produced.",
          "genuineForecastsProduced": 0}
output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
print(json.dumps(reference(output)))
