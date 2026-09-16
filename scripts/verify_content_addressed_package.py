"""Verify an ASP member-hash addressed package from its delivered bytes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_shared.content_addressed_package import verify_package_directory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_package_directory(args.package), ensure_ascii=False,
                     allow_nan=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
