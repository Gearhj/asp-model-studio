"""Execute only the predeclared reconstructed Development study."""
import json
from server.sports_nfl_m1.current_state_study import run_study

if __name__ == "__main__":
    result = run_study()
    print(json.dumps({"runId":result["runId"],"fits":result["actualFitAccounting"],"finalModel":result["finalModel"]}))
