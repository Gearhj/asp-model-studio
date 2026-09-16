"""Build one genuine future NBA research package locally; never auto-publish."""
from pathlib import Path
import argparse
import io
import json
import sys

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nba_gen1.authority import (NbaAdmissionError, RESEARCH_FLAGS, immutable_json, require, verified_bytes)
from server.sports_nba_gen1.forecast import build_shadow_forecast
from server.sports_nba_gen1.runner import artifact, context, get_frame, load_pointer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True,
                        help='Verified real future target, sourceCutoffUtc and complete physical bindings; no example game is generated')
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/nba-gen1-v1/shadow')
    args = parser.parse_args()
    plan, plan_ref, _ = context(args.study)
    fitted, fitted_ref = load_pointer(args.study, 'refit')
    request = json.loads(args.request.read_bytes())
    bindings = request['bindings']
    fixed = {'modelArtifact': fitted['model'], 'preprocessorArtifact': fitted['model'],
        'featureContract': fitted['featureContractArtifact'], 'residualPopulation': fitted['residuals'],
        'residualReceipt': fitted['residualReceipt'], 'overtimePopulation': fitted['overtimeEvidence'],
        'sourceIndex': plan['sourceIndex']}
    for key, value in fixed.items():
        require(bindings.get(key) == value, 'Future request changed frozen fitted binding: '+key)
    for key in ('modelConfigurationIdentity', 'modelTrainingIdentitySha256'):
        require(bindings.get(key) == fitted[key], 'Future model identity differs from the retained refit')
    model = joblib.load(io.BytesIO(verified_bytes(fitted['model'])))
    result = build_shadow_forecast(model, get_frame(bindings['historyPopulation']), request['target'],
        get_frame(fitted['residuals']), get_frame(fitted['overtimeEvidence']), bindings,
        request['sourceCutoffUtc'], draws=plan['draws'], master_seed=plan['seed'])
    arrays = {k: v for k, v in result['population'].items() if isinstance(v, np.ndarray)}
    stream = io.BytesIO()
    np.savez_compressed(stream, **arrays)
    pop = artifact(args.output, 'population.npz', stream.getvalue())
    result['forecast']['population']['physicalArtifact'] = pop
    forecast = immutable_json(args.output, 'forecast.json', result['forecast'])
    audit = immutable_json(args.output, 'feature-audit.json', result['featureAudit'])
    index = immutable_json(args.output, 'index.json', {'schemaVersion': 'NBA_GEN1_RESEARCH_PACKAGE_V1',
        'forecastId': result['forecast']['forecastId'], 'forecast': forecast, 'population': pop, 'featureAudit': audit,
        'fittedRefit': fitted_ref, 'declaration': plan_ref, 'publicationStatus': 'BUILT_LOCALLY_NOT_PUBLISHED',
        'publishedAtUtc': None, 'consumerAcknowledgement': None, **RESEARCH_FLAGS})
    print(json.dumps({'status': 'BUILT_GENUINE_LOCAL_RESEARCH_PACKAGE', 'index': index,
        'publication': None, 'consumerAcknowledgement': None}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (NbaAdmissionError, ValueError) as exc:
        print(json.dumps({'status': 'UNSUPPORTED_NO_FORECAST_PUBLISHED', 'reason': str(exc)}))
        raise SystemExit(2)
