"""Run the one governed MLB V18 PA-finalist/game-baseline finalization."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.sports_current_statcast.mlb_v18_game_baseline import finalize


def main() -> int:
    starting_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True
    ).strip()
    result = finalize(
        repository_root=REPOSITORY_ROOT,
        database_path=REPOSITORY_ROOT / ".runtime/asp-model-studio/persistence/asp_model_studio.db",
        comparison_path=REPOSITORY_ROOT / "outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d.json",
        output_root=REPOSITORY_ROOT / "outputs/mlb-v18-pa-game-baseline",
        exchange_root=Path(r"C:\Users\james\asp-model-exchange"),
        starting_commit=starting_commit,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
