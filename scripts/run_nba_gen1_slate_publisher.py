"""One offline canonical-owner NBA slate tick. No scheduler installation."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nba_gen1.authority import reference, verified_bytes
from server.sports_nba_gen1.slate_inputs import validate_bundle
from server.sports_nba_gen1.slate_lifecycle import now, object_json, read_ref, tick
from server.sports_nba_gen1.slate_render import render, verify_package


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--release', required=True)
    p.add_argument('--release-sha256', required=True)
    p.add_argument('--input-pointer', required=True)
    p.add_argument('--state-root', required=True)
    p.add_argument('--exchange-root', required=True, help='Dedicated NBA production tree, not exchange parent')
    p.add_argument('--result-file', required=True)
    args = p.parse_args()
    try:
        ref = reference(args.release)
        if ref['sha256'] != args.release_sha256:
            raise ValueError('Release physical hash mismatch')
        release = read_ref(ref)
        manifest = read_ref(release['deploymentManifest'])
        for member in manifest['members']:
            verified_bytes(dict(member, path=str(Path(release['deploymentManifest']['path']).parent / member['relativePath'])))
        pointer = read_ref(reference(args.input_pointer))
        receipt, bound = tick(bundle_ref=pointer['inputManifest'], release_ref=ref,
            state_root=args.state_root, exchange_root=args.exchange_root,
            renderer=render, verifier=verify_package, bundle_validator=validate_bundle)
    except Exception as exc:
        receipt = {'schema': 'NBA_GEN1_SLATE_RUNNER_RECEIPT_V1', 'completedAtUtc': now(),
                   'disposition': 'FAILED', 'exitCode': 1, 'errorType': type(exc).__name__, 'reason': str(exc),
                   'providerCalls': 0, 'providerBytes': 0, 'costUsd': 0, 'aispWrites': 0}
        bound = object_json(Path(args.state_root) / 'runner-receipts', receipt)
    result = {'disposition': receipt['disposition'], 'exitCode': receipt['exitCode'], 'receipt': bound}
    from server.sports_nba_gen1.slate_lifecycle import immutable
    from server.sports_nba_gen1.production import canonical_bytes
    immutable(Path(args.result_file), canonical_bytes(result))
    print(json.dumps(result))
    return receipt['exitCode']


if __name__ == '__main__':
    sys.exit(main())
