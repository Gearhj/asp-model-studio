"""Replay V18 from already isolated Development bytes. Never resolve source Gold."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[key] = '4'

import json
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from server.sports_current_statcast.mlb_regime_baseline import RUNTIME, sha_file
from server.sports_current_statcast.stage3_corrected_preprocessing_artifacts import load_research_pipeline
from server.sports_current_statcast.stage3_model_laboratory import _aligned_probabilities
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER

BASE_SHA = '0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9'
BASE = ROOT / f'outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache/baseline-reproduction-{BASE_SHA}.json'


def load_safe_cache():
    assert sha_file(BASE) == BASE_SHA
    meta = json.loads(BASE.read_text())
    frames = []
    for key in ('rawDevelopment', 'matchedOof'):
        ref = meta['artifacts'][key]
        path = Path(ref['path'])
        assert path.stat().st_size == ref['bytes'] and sha_file(path) == ref['sha256']
        frame = pd.read_parquet(path)
        assert frame.game_date.astype(str).max() <= '2026-08-06'
        assert not frame.canonicalPaId.duplicated().any()
        frames.append(frame)
    return meta, *frames


def main():
    meta, raw, oof = load_safe_cache()
    records = []
    raw = raw.set_index('canonicalPaId', drop=False, verify_integrity=True)
    for saved in meta['folds']:
        fold = saved['foldNumber']
        expected = oof[oof.foldNumber == fold]
        rows = raw.loc[expected.canonicalPaId]
        assert np.array_equal(rows.canonicalGameId, expected.canonicalGameId)
        pipeline = load_research_pipeline(saved['model'], root=RUNTIME)
        with threadpool_limits(limits=4):
            actual = np.vstack([
                _aligned_probabilities(pipeline.estimator, pipeline.preprocessor.encoder.transform(
                    pipeline.preprocessor.transform_frame(rows.iloc[i:i+20000][list(pipeline.ordered_features)])))
                for i in range(0, len(rows), 20000)
            ])
        original = expected[['probability_'+c for c in PA_CLASS_ORDER]].to_numpy()
        record = {'fold': fold, 'rows': len(rows), 'maximumAbsoluteDifference': float(np.abs(actual-original).max()),
                  'mismatchedValues': int(np.count_nonzero(actual != original)), 'estimator': saved['model']}
        print(json.dumps(record), flush=True)
        if not np.array_equal(actual, original):
            raise RuntimeError('Frozen baseline reproduction failed')
        records.append(record)
    result = {'schemaVersion': 'MLB_V19_BASELINE_REPLAY_V1', 'baselineReceiptSha256': BASE_SHA,
              'matchedRows': len(oof), 'matchedGames': int(oof.canonicalGameId.nunique()), 'folds': records,
              'finalOotPayloadBytesRead': 0, 'modelFits': 0, 'targetOrder': list(PA_CLASS_ORDER)}
    data = canonical_json_bytes(result)
    import hashlib
    digest = hashlib.sha256(data).hexdigest()
    path = ROOT / f'outputs/mlb-v19-current-state-specialists-v1/baseline/sha256/{digest}/reproduction.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data
    else:
        with path.open('xb') as handle:
            handle.write(data)
    print(json.dumps({'path': str(path), 'sha256': digest}), flush=True)


if __name__ == '__main__':
    main()
