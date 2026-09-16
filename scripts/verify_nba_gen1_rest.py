"""Focused preservation and real-model verification for the rest correction."""
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nba_gen1.authority import reference, verified_bytes
from server.sports_nba_gen1.recent_features import recent_feature_contract
from server.sports_nba_gen1.recent_study import now, save
from server.sports_nba_gen1.rest_support import CHANGED_COLUMNS, transform_rest, learn_rest_support


def main():
    root = ROOT/'outputs/nba-gen1-long-gap-v1'
    prior = ROOT/'outputs/nba-gen1-recent-v1'
    start = json.loads((root/'starting-state.json').read_bytes())
    for bound in start['preservedFiles'] + start['dirtyFiles']:
        verified_bytes(bound)
    if (root/'verification.json').exists():
        existing = json.loads((root/'verification.json').read_bytes())
        for stage in ('development', 'reused-diagnostics'):
            receipt = json.loads((root/stage/'receipt.json').read_bytes())
            for bound in list(receipt['artifacts'].values()) + list(receipt['numericalModules'].values()):
                verified_bytes(bound)
        print(json.dumps({'status': 'REUSED_VERIFIED_RECEIPT', 'receipt': reference(root/'verification.json')}, indent=2))
        return
    checks = []
    for stage in ('development', 'reused-diagnostics'):
        folder = root/stage
        receipt = json.loads((folder/'receipt.json').read_bytes())
        for bound in receipt['artifacts'].values():
            verified_bytes(bound)
        for bound in receipt['numericalModules'].values():
            verified_bytes(bound)
        source = prior/('development' if stage == 'development' else 'holdout')/'features.parquet'
        raw = pd.read_parquet(source)
        ledger = pd.read_parquet(folder/'predictions.parquet')
        models = json.loads((folder/'models.json').read_bytes())
        for year, bound in models.items():
            verified_bytes(bound['artifact'])
            model = joblib.load(bound['artifact']['path'])
            target = raw[(raw.season_end == int(year)) & raw.target_eligible].copy()
            train = raw[(raw.season_end < int(year)) & raw.target_eligible].copy()
            assert model.rest_support == learn_rest_support(train)
            assert tuple(train.game_id) == model.training_game_ids
            assert not set(target.game_id) & set(model.training_game_ids)
            assert (target.history_latest_game_date < target.game_date).all()
            expected = ledger[(ledger.model_id == 'ridge_a100_rest') & (ledger.season_end == int(year))]
            assert list(target.game_id) == list(expected.game_id)
            values = model.predict(target)
            saved = expected[['expected_home_score', 'expected_away_score']].to_numpy()
            assert np.array_equal(values, saved), 'Numerical reproduction changed'
            treated, audit = transform_rest(target, model.rest_support)
            unaffected = [n for n in recent_feature_contract()['numericFeatures'] if n not in CHANGED_COLUMNS]
            assert len(unaffected) == 71
            pd.testing.assert_frame_equal(target[unaffected], treated[unaffected])
            base = ledger[(ledger.model_id == 'ridge_a100') & (ledger.season_end == int(year))]
            a, b = expected.set_index('game_id').sort_index(), base.set_index('game_id').sort_index()
            assert np.array_equal(a.p_home_win.to_numpy(), b.p_home_win.to_numpy())
            assert np.max(np.abs(a.p_home_win + a.p_away_win + a.p_tie - 1)) == 0
            margin_total = model.predict_margin_total(target)
            assert np.allclose(values[:, 0] - values[:, 1], margin_total[:, 0], rtol=0, atol=1e-12)
            assert np.allclose(values[:, 0] + values[:, 1], margin_total[:, 1], rtol=0, atol=1e-12)
            checks.append({'stage': stage, 'seasonEnd': int(year), 'games': len(target),
                           'model': bound['artifact'], 'maximumReproductionError': float(np.max(abs(values-saved))),
                           'fittedMaximumRestDays': model.rest_support['maximumDays'],
                           'unchangedNumericColumns': 71, 'unchangedElo': True,
                           'negativeTeamExpectations': int((values < 0).sum()),
                           'bothOrdinaryGames': int(audit.both_ordinary_supported.sum())})
    value = {'schema': 'nba-gen1-rest-focused-verification-v1', 'createdAtUtc': now(),
             'startingState': reference(root/'starting-state.json'),
             'preservedHistoricalArtifactFiles': len(start['preservedFiles']),
             'preservedUnrelatedDirtyFiles': len(start['dirtyFiles']), 'checks': checks,
             'assessmentGames': sum(c['games'] for c in checks),
             'scope': 'Only changed numerical behavior, inputs, model reproduction and preservation; no broad suite or re-scoring of original baselines'}
    save(root/'verification.json', value)
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    main()
