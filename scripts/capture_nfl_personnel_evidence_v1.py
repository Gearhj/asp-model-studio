"""Plan, or explicitly execute, one bounded NFL personnel evidence capture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server.sports_nfl_m1.personnel_capture import DEFAULT_ROOT, build_capture_plan, execute_capture


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--season", type=int, default=2026)
    result.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    result.add_argument("--execute", action="store_true")
    result.add_argument("--rights-approved", action="store_true",
                        help="Explicit acknowledgement that acquisition/retention rights were reviewed.")
    return result


def _fetch(asset, conditional_headers, maximum_bytes):
    headers = {"User-Agent": "asp-model-studio-nfl-personnel-capture-v1", **conditional_headers}
    request = Request(asset.url, headers=headers)
    try:
        with urlopen(request, timeout=120) as response:
            chunks = []
            total = 0
            while True:
                chunk = response.read(min(1024 * 1024, maximum_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum_bytes:
                    raise RuntimeError("streamed response exceeds remaining capture byte ceiling")
                chunks.append(chunk)
            return b"".join(chunks), {**dict(response.headers.items()), "X-ASP-HTTP-Status": str(response.status)}
    except HTTPError as error:
        if error.code == 304:
            return None, {**dict(error.headers.items()), "X-ASP-HTTP-Status": "304"}
        if error.code == 404:
            return None, {"X-ASP-HTTP-Status": "404"}
        raise


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    plan = build_capture_plan(args.season, include_schedule=False)
    if not args.execute:
        print(json.dumps({**plan.content(), "status": "DRY_RUN_NO_NETWORK",
                          "outputRoot": str(args.output_root.resolve()),
                          "requestsPerformed": 0, "responseBytes": 0, "costUsd": 0}, indent=2, sort_keys=True))
        return 0
    if not args.rights_approved:
        raise SystemExit("--execute also requires --rights-approved")
    print(json.dumps(execute_capture(plan, output_root=args.output_root, allow_network=True,
                                     rights_approved=True, fetcher=_fetch), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
