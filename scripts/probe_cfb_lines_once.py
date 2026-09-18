"""Run only the separately authorized one-request 2026 week-four lines probe."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_cfb_gen1.lines_probe import probe
from server.sports_cfb_gen1.publication_io import reference


def main():
    parser = argparse.ArgumentParser()
    for name in ('state-root', 'plan', 'grant', 'deployment', 'probe-grant', 'entitlement-receipt', 'env-file'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        result = probe(state_root=args.state_root, plan_ref=reference(args.plan),
                       grant_ref=reference(args.grant), deployment=args.deployment,
                       probe_grant_ref=reference(args.probe_grant),
                       entitlement_receipt_ref=reference(args.entitlement_receipt), env_file=args.env_file)
    except Exception as exc:
        print(json.dumps({'disposition': 'PRE_REQUEST_BLOCKED', 'errorType': type(exc).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result['disposition'] == 'CAPTURED_LINES_PROBE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
