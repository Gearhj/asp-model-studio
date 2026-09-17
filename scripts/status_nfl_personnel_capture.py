"""Print the current bounded NFL personnel capture owner status."""
from __future__ import annotations
import json
from pathlib import Path
import sys
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from server.sports_nfl_m1.personnel_prospective import DEFAULT_DATA_ROOT, DEFAULT_RUNTIME_ROOT


def main() -> int:
    runtime = DEFAULT_RUNTIME_ROOT
    data = DEFAULT_DATA_ROOT
    def load(path: Path):
        return json.loads(path.read_bytes()) if path.exists() else None
    current = load(data / "current.json")
    evidence = load(data / "evidence" / "CURRENT.json")
    result = {"runtimeManifest": load(runtime / "deployment.json"), "lastRun": load(runtime / "LAST_RUN.json"),
              "captureCurrent": current, "evidenceCurrent": evidence,
              "rightsAcknowledgementPresent": (runtime / "RIGHTS_ACKNOWLEDGEMENT.json").exists()}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
