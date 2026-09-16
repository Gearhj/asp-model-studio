"""Publish immutable research rule/package with OS-held ownership and actual clocks."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.package_mlb_v18_transition_adapter_v2 import canonical, reference, verify_ref, immutable, aware
from server.sports_current_statcast.mlb_v18_unattended import single_owner

OUT = ROOT / 'outputs/mlb-v18-score-limited-v1'
EXCHANGE = ROOT.parent / 'asp-model-exchange/mlb-v18-ensemble-research-v1/score-limited-v1'

def now():
    return datetime.now(timezone.utc).isoformat()

def publish_rule():
    rule = json.loads((OUT/'development-rule/current.json').read_bytes())['rule']
    source = verify_ref(rule)
    destination = EXCHANGE/'rules/sha256'/rule['sha256']/'rule.json'
    receipt_path = OUT/'publication/rule-publication.json'
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_bytes())
        assert receipt['rule'] == rule
        verify_ref(receipt['deliveredRule'])
        return reference(receipt_path)
    started = now()
    with single_owner(EXCHANGE/'publisher.lock') as owned:
        if not owned:
            raise RuntimeError('EXISTING_PUBLICATION_LOCK_OWNED; no takeover')
        immutable(destination, source.read_bytes())
        delivered = reference(destination)
        assert (delivered['sha256'], delivered['bytes']) == (rule['sha256'], rule['bytes'])
        immutable(receipt_path, canonical({'schemaVersion':'MLB_V18_SCORE_LIMIT_RULE_PUBLICATION_V1',
            'startedAtUtc':started, 'publishedAtUtc':now(), 'status':'PUBLISHED_RULE', 'rule':rule,
            'deliveredRule':delivered, 'forecastPerformanceExamined':False,
            'productionAuthority':False}))
    return reference(receipt_path)

def publish_package(receipt_path):
    receipt_path = Path(receipt_path)
    receipt = json.loads(receipt_path.read_bytes())
    package_root = Path(receipt['packageRoot'])
    # Artifact keys are supplied by the existing candidate adapter, not inferred.
    handoff = verify_ref(receipt['handoff'])
    forecasts = list(package_root.glob('forecasts/*/forecast.json'))
    if not forecasts:
        forecasts = list(package_root.rglob('forecast.json'))
    cutoff = min(aware(json.loads(p.read_bytes())['policyCutoffUtc']) for p in forecasts)
    destination = EXCHANGE/'packages/sha256'/handoff.parent.name
    local_receipt = OUT/'publication/package-publication.json'
    if local_receipt.exists():
        previous = json.loads(local_receipt.read_bytes())
        assert previous['sourcePackageReceipt']['sha256'] == reference(receipt_path)['sha256']
        for item in previous['deliveredFiles']:
            verify_ref(item)
        return reference(local_receipt)
    started = now()
    if datetime.now(timezone.utc) >= cutoff:
        raise RuntimeError('EXPIRED_UNPUBLISHED; cannot backfill')
    delivered = []
    with single_owner(EXCHANGE/'publisher.lock') as owned:
        if not owned:
            raise RuntimeError('EXISTING_PUBLICATION_LOCK_OWNED; no takeover')
        for item in receipt['artifacts']:
            source = verify_ref(item)
            if source == handoff:
                continue
            target = destination/source.relative_to(package_root)
            immutable(target, source.read_bytes())
            copy_ref = reference(target)
            assert (copy_ref['sha256'], copy_ref['bytes']) == (item['sha256'], item['bytes'])
            delivered.append(copy_ref)
        immutable(destination/'package-receipt.json', receipt_path.read_bytes())
        delivered.append(reference(destination/'package-receipt.json'))
        # The discoverable handoff is the commit point. Never expose it while
        # dependencies are incomplete or when their copy consumed the window.
        if datetime.now(timezone.utc) >= cutoff:
            raise RuntimeError('EXPIRED_DURING_DEPENDENCY_COPY; handoff remains unpublished')
        immutable(destination/handoff.relative_to(package_root), handoff.read_bytes())
        delivered.append(reference(destination/handoff.relative_to(package_root)))
        completed = now()
        on_time = aware(completed) < cutoff
        immutable(local_receipt, canonical({'schemaVersion':'MLB_V18_SCORE_LIMIT_PACKAGE_PUBLICATION_V1',
            'startedAtUtc':started,'publishedAtUtc':completed,'deadlineUtc':cutoff.isoformat(),
            'status':'PUBLISHED_PREGAME_RESEARCH' if on_time else 'EXPIRED_DURING_COPY_NOT_PROSPECTIVE',
            'sourcePackageReceipt':reference(receipt_path),'deliveredFiles':delivered,
            'handoff':reference(destination/handoff.relative_to(package_root)),
            'configurationId':'mlb-v18-score-limited-v1','consumerSupportConfirmed':False,
            'importConfirmed':False,'productionAuthority':False}))
    return reference(local_receipt)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rule', action='store_true')
    parser.add_argument('--package-receipt')
    args = parser.parse_args()
    if args.rule == bool(args.package_receipt):
        parser.error('choose exactly --rule or --package-receipt')
    print(json.dumps(publish_rule() if args.rule else publish_package(args.package_receipt)))
