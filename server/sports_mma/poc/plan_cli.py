from __future__ import annotations
import argparse,json
from .adapters import build_plan
def main()->None:
    p=argparse.ArgumentParser(description="MMA POC planner; dry-run is default")
    p.add_argument("--execute-live",action="store_true"); a=p.parse_args()
    if a.execute_live: raise SystemExit("LIVE_EXECUTION_NOT_IMPLEMENTED_IN_NO_NETWORK_HARNESS")
    print(json.dumps(build_plan(),ensure_ascii=False,sort_keys=True,indent=2))
if __name__=="__main__": main()
