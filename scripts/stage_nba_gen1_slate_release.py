"""Stage one immutable offline slate publisher. No task or consumer activation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_nba_gen1.authority import reference, verified_bytes
from server.sports_nba_gen1.production import CONFIGURATION, canonical_bytes, digest
from server.sports_nba_gen1.joint_residual import ENGINE, DRAW_COUNT, MASTER_SEED
from server.sports_nba_gen1.slate_lifecycle import POLICY, immutable, now, object_json, read_ref


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repository-root', default=r'C:\Users\james\asp-model-studio')
    p.add_argument('--source-root', default=str(Path(__file__).resolve().parents[1]))
    p.add_argument('--output-root', required=True)
    p.add_argument('--input-pointer', required=True)
    a = p.parse_args()
    source, root, output = Path(a.source_root), Path(a.repository_root), Path(a.output_root)
    result_path = output / 'release-receipt.json'
    if result_path.exists():
        saved = json.loads(result_path.read_bytes())
        for field in ('deploymentManifest', 'release'):
            verified_bytes(saved[field])
        manifest = read_ref(saved['deploymentManifest'])
        for m in manifest['members']:
            verified_bytes(dict(m, path=str(Path(saved['deploymentManifest']['path']).parent / m['relativePath'])))
        print(json.dumps(saved, indent=2))
        return
    paths = [source/'server/__init__.py', *sorted((source/'server/sports_nba_gen1').glob('*.py'))]
    paths += [source/'scripts'/name for name in ('run_nba_gen1_slate_publisher.py', 'admit_nba_gen1_slate_inputs.py',
        'capture_nba_slate_refresh.py', 'invoke_nba_gen1_slate_publisher.ps1', 'install_nba_gen1_slate_publisher.ps1')]
    members = [{'relativePath': path.relative_to(source).as_posix(), 'sha256': reference(path)['sha256'],
                'bytes': path.stat().st_size} for path in paths]
    identity = {'schema': 'NBA_GEN1_SLATE_DEPLOYMENT_IDENTITY_V1', 'sourceCommit': subprocess.check_output(
        ['git','rev-parse','HEAD'],cwd=source,text=True).strip(), 'members': members,
        'configurationIdentity': CONFIGURATION, 'distributionConfigurationIdentity': ENGINE,
        'drawCount': DRAW_COUNT, 'masterSeed': MASTER_SEED, 'policy': POLICY,
        'supersedesUninstalledDeployment': '7e04b1cc6f68ad4a4c0a3833f28751fdbfc54957e019e2cb5743946eeae25716'}
    deployment_id = digest(identity)
    deployment = root/'.deployments/nba-gen1-slate-publisher'/deployment_id
    for path, member in zip(paths, members):
        immutable(deployment/member['relativePath'], path.read_bytes())
    manifest = dict(identity, deploymentId=deployment_id, createdAtUtc=now(), status='STAGED_NOT_INSTALLED',
                    canonicalTaskName='ASP NBA Forecast Publisher', activationAuthorized=False)
    manifest_ref = immutable(deployment/'deployment-manifest.json', canonical_bytes(manifest))
    original = root/'outputs/nba-gen1-long-gap-v1'
    model_handoff = Path(r'C:\Users\james\asp-model-exchange\nba-gen1-production-v1\handoffs\sha256\7113b71ff5819c89103ad19d5f9afb22c51dbc92980be12b56ce8826cb34ccaf\index.json')
    handoff = read_ref(reference(model_handoff))
    for member in handoff['members']:
        verified_bytes(dict(member, path=str(model_handoff.parent/member['relativePath'])))
    pointer = read_ref(reference(a.input_pointer))
    read_ref(pointer['inputManifest'])
    effective = now()
    old_discovery = Path(r'C:\Users\james\asp-model-exchange\nba-gen1-production-v1\discovery\current.json')
    # Freeze a snapshot of legacy discovery so a later independent update cannot
    # rewrite the successor's record of preserved earlier publications.
    preserved = immutable(output/'preserved-legacy-discovery.json', old_discovery.read_bytes()) if old_discovery.exists() else None
    release = {'schema': 'NBA_GEN1_SLATE_RELEASE_V1', 'createdAtUtc': effective,
        'prospectiveEffectiveAtUtc': effective, 'deploymentManifest': manifest_ref,
        'configurationIdentity': CONFIGURATION, 'distributionConfigurationIdentity': ENGINE,
        'baseModelReceipt': reference(original/'current-research/receipt.json'),
        'baseCoverage': reference(original/'current-history-coverage.json'),
        'jointMethod': reference(root/'outputs/nba-gen1-joint-residual-v1/method-freeze.json'),
        'modelHandoff': reference(model_handoff), 'drawCount': DRAW_COUNT, 'masterSeed': MASTER_SEED,
        'inputPointer': str(Path(a.input_pointer).resolve()), 'initialInputVersion': pointer['inputManifest'],
        'preservedDiscovery': preserved, 'policy': POLICY, 'automaticExternalAcquisition': False,
        'authority': {'producerInstalled': False, 'consumerActivated': False, 'wageringAuthority': False,
                      'decisionAuthority': False, 'positionAuthority': False, 'modelPromotionAuthority': False},
        'channelAuthorities': {'expectedScores': 'Frozen Ridge alpha100 ordinary-rest',
            'winner': 'Separate chronological Elo', 'jointScoresAndTotals': ENGINE},
        'closeScoreChallengerEnabled': False,
        'publicationClockContract': 'V2 package publishedAtUtc is null; bound immutable publicationReceipt committedAtUtc is conservative first availability, separate from creation',
        'disclosures': ['Historical one-point finishes: 7.78% simulated versus 4.01% observed',
            'Close-score correction tested and rejected', 'Overtime games materially harder',
            'No player/lineup/injury inputs', 'No profitability claim'],
        'monitoring': {'reviewsAtCompletedGames': [50,100], 'metrics': ['score/margin/total MAE',
            'winner log loss/binary Brier', 'energy score', 'home/away/total/margin CRPS',
            'one-point frequency', 'regulation versus overtime performance']}}
    release_ref = object_json(output/'releases', release, 'release.json')
    result = {'schema': 'NBA_GEN1_SLATE_STAGING_RECEIPT_V1', 'deploymentId': deployment_id,
        'deploymentManifest': manifest_ref, 'release': release_ref, 'installed': False,
        'inputPointer': str(Path(a.input_pointer).resolve()), 'effectiveAtUtc': effective,
        'providerCalls': 0, 'costUsd': 0, 'aispWrites': 0}
    immutable(result_path, canonical_bytes(result))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
