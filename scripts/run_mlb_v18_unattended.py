"""One OS-owned bounded V18 tick; no Codex session or heartbeat dependency."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_current_statcast.mlb_v18_unattended import STATE_ROOT, execute_tick, single_owner


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--run-now", action="store_true", help="One operator-requested tick now; game cooldowns and real-time cutoffs still apply")
    args = parser.parse_args()
    if args.plan_only:
        print(json.dumps({"mode": "PLAN_ONLY", "owner": "WINDOWS_TASK_SCHEDULER",
            "stateRoot": str(STATE_ROOT), "networkCalls": 0, "modelExecutions": 0,
            "killSwitch": str(STATE_ROOT / "STOP"), "wakeMinutes": 5,
            "scope": "CURRENT_AND_NEXT_SLATE_PRESTART_ONLY"}, indent=2))
    else:
        with single_owner(STATE_ROOT / "producer.lock") as acquired:
            if not acquired:
                print(json.dumps({"status": "ANOTHER_OWNER_RUNNING_NO_ACTION"}))
            else:
                report = execute_tick(run_now=args.run_now, publish_exchange=True)
                print(json.dumps({key: report[key] for key in ("status", "receipt", "completedAt")}, indent=2))
                if report["status"] == "FAILED_BOUNDED_TICK":
                    raise SystemExit(1)
