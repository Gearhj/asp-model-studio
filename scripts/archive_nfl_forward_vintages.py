"""Archive existing authorized NFL source snapshots without network or model work."""
import argparse
import json
from pathlib import Path

from server.sports_nfl_m1.forward_vintages import (
    DEFAULT_BRONZE, DEFAULT_OUTPUT, DEFAULT_SCHEDULE_HANDOFF, capture_forward_vintages,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-root", type=Path, default=DEFAULT_BRONZE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--schedule-handoff", type=Path, default=DEFAULT_SCHEDULE_HANDOFF)
    parser.add_argument("--no-schedule-projection", action="store_true")
    args = parser.parse_args()
    result = capture_forward_vintages(bronze_root=args.bronze_root, output_root=args.output_root,
                                     schedule_handoff=None if args.no_schedule_projection else args.schedule_handoff)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
