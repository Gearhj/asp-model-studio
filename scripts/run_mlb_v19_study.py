"""Bounded, restartable-by-explicit-command V19 study; no operational writes."""
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'scripts'))
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '4'

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, ExtraTreesClassifier
from threadpoolctl import threadpool_limits
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast.mlb_regime_baseline import RUNTIME, sha_file
from server.sports_current_statcast.stage3_corrected_preprocessing_artifacts import load_research_pipeline
from server.sports_current_statcast.mlb_v19_models import SemanticPriors, FoldClusters, CandidatePipeline, predict_estimator
from server.sports_current_statcast.mlb_v19_evaluation import regime_masks, discover_persistent_regimes
from server.sports_current_statcast.mlb_v19_launch_guard import require_v19_launch_authority
from reproduce_mlb_v19_baseline import load_safe_cache, BASE_SHA

OUT = ROOT/'outputs/mlb-v19-current-state-specialists-v1'
VARIANTS = ('SEMANTIC_HGB', 'SEMANTIC_EXTRA_TREES', 'REGIME_HGB', 'REGIME_CLUSTER_HGB')
GAME_PATH = ROOT/'outputs/mlb-v19-current-state-specialists-v1/game-context/sha256/b94fa31772a6d79e5f8b80ec414e0ec8b41a2dcf36b65c3fae9dba0e47bcfd9a/game-context.parquet'
GAME_SHA = '9a642b0f373ef27bb684f46304661929843e9d60bef8188d2341c6373790296d'


def clean(value):
    if isinstance(value, dict): return {str(k): clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [clean(v) for v in value]
    if isinstance(value, np.ndarray): return clean(value.tolist())
    if isinstance(value, np.generic): return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value): return None
    return value


def write_json(path, payload):
    data = canonical_json_bytes(clean(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data: raise ValueError(f'Immutable conflict {path}')
    else:
        with path.open('xb') as handle: handle.write(data)
    return ref(path)


def ref(path):
    return {'path': str(path.resolve()), 'sha256': sha_file(path), 'bytes': path.stat().st_size}


def emit(event, **data):
    payload = clean({'event': event, 'atUtc': datetime.now(timezone.utc).isoformat(), **data})
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT/'fit-events.jsonl').open('a', encoding='utf8') as handle: handle.write(json.dumps(payload, sort_keys=True)+'\n')
    print(json.dumps(payload), flush=True)


def fitted(name, function, fold):
    emit('FIT_STARTED', fit=name, fold=fold)
    start = time.monotonic()
    try:
        result = function()
    except Exception as error:
        emit('FIT_FAILED', fit=name, fold=fold, error=repr(error), seconds=time.monotonic()-start)
        raise
    emit('FIT_COMPLETED', fit=name, fold=fold, seconds=time.monotonic()-start)
    return result


def join_teams(raw):
    if sha_file(GAME_PATH) != GAME_SHA: raise ValueError('Game map checksum differs')
    games = pd.read_parquet(GAME_PATH, columns=['canonicalGameId','homeTeamId','awayTeamId'])
    result = raw.merge(games, on='canonicalGameId', how='left', validate='many_to_one', sort=False)
    if result.homeTeamId.isna().any(): raise ValueError('Missing historical team identity')
    result['battingTeamId'] = np.where(result.context_top_bottom == 1, result.homeTeamId, result.awayTeamId)
    result['fieldingTeamId'] = np.where(result.context_top_bottom == 1, result.awayTeamId, result.homeTeamId)
    return result


def main(folds):
    require_v19_launch_authority("GLOBAL_STUDY")
    meta, raw, oof = load_safe_cache()
    raw = join_teams(raw).reset_index(drop=True)
    specs = json.loads((RUNTIME/'corrected-hgb-recovery-1/study.json').read_text())['folds']
    probabilities = oof[['probability_'+c for c in meta['targetOrder']]].to_numpy()
    full_oof = raw.set_index('canonicalPaId', drop=False).loc[oof.canonicalPaId].reset_index(drop=True)
    assert np.array_equal(full_oof.observedClassIndex, oof.observedClassIndex)
    assert full_oof.groupby('canonicalGameId').foldNumber.nunique().max() == 1
    for number in folds:
        directory = OUT/f'folds/fold-{number}'
        complete = directory/'complete.json'
        if complete.exists():
            receipt = json.loads(complete.read_text())
            for entry in receipt['artifacts']:
                assert sha_file(Path(entry['path'])) == entry['sha256']
            emit('COMPLETED_FOLD_REUSED', fold=number)
            continue
        directory.mkdir(parents=True, exist_ok=True)
        fold, saved = specs[number-1], meta['folds'][number-1]
        training = raw[raw.game_date.astype(str).between(fold['trainStart'], fold['trainEnd'])].reset_index(drop=True)
        validation = full_oof[full_oof.foldNumber == number].reset_index(drop=True)
        assert training.game_date.max() < validation.game_date.min()
        assert not set(training.canonicalGameId).intersection(validation.canonicalGameId)
        # Eligibility sees V18 prior folds only, before fitting/evaluating this fold.
        eligibility = discover_persistent_regimes(full_oof, probabilities, before_fold=number)
        write_json(directory/'specialist-eligibility.json', eligibility)
        authority = {'schemaVersion':'MLB_V19_OUTER_FOLD_PREFIT_V1', 'fold':fold, 'trainRows':len(training),
            'validationRows':len(validation),'rawCache':meta['artifacts']['rawDevelopment'],
            'baselineReceiptSha256':BASE_SHA,'frozenV18Model':saved['model'],
            'targetOrder':meta['targetOrder'], 'declaration':ref(ROOT/'docs/MLB_V19_STUDY_DECLARATION_V1.md'),
            'orderedRawFeatures':meta['rawFeatureColumns'], 'finalOotPayloadBytesRead':0,
            'code':[ref(ROOT/name) for name in ('scripts/run_mlb_v19_study.py',
                'server/sports_current_statcast/mlb_v19_models.py','server/sports_current_statcast/mlb_v19_evaluation.py')],
            'scheduledGlobalFitSlots':4, 'nativeWorkers':4}
        write_json(directory/'prefit-native-missing-v2.json', authority)
        pipeline = load_research_pipeline(saved['model'], root=RUNTIME)
        checkpoint = directory/'feature-assets.joblib'
        with threadpool_limits(limits=4):
            if checkpoint.exists():
                prepared = joblib.load(checkpoint)
                semantic, clusters = prepared['semantic'], prepared['clusters']
                emit('FEATURE_ASSETS_REUSED', fold=number)
            else:
                semantic = fitted('SEMANTIC_PRIOR_HYPERPARAMETERS', lambda:SemanticPriors().fit(training), number)
                semantic_train, _ = semantic.transform(raw, training)
                combined = pd.concat([training, semantic_train], axis=1)
                clusters = fitted('TRAINING_ONLY_CLUSTER_SYSTEM',lambda:FoldClusters().fit(combined,20260911+number),number)
                joblib.dump({'semantic':semantic,'clusters':clusters},checkpoint,compress=3)
                write_json(directory/'semantic-priors.json', {'fittedEnd':semantic.fitted_end,'parameters':semantic.parameters,
                    'featureOrder':semantic.feature_names,'uncertaintyOnlyExcludedFromMeans':semantic.uncertainty_names})
                write_json(directory/'clusters.json', {'domains':clusters.reports,'fittedEnd':clusters.fitted_end,
                    'unsupportedDomains':{'BULLPEN_AVAILABILITY':'NO_HISTORICAL_ROSTER_WORKLOAD_VINTAGES'}})
            semantic_train, _ = semantic.transform(raw, training)
            semantic_valid, uncertainty_valid = semantic.transform(raw, validation)
            emit('SEMANTIC_FEATURES_TRANSFORMED', fold=number, trainRows=len(training), validationRows=len(validation))
            treated_train = pipeline.preprocessor.transform_frame(training)
            treated_valid = pipeline.preprocessor.transform_frame(validation)
            base_train = pipeline.preprocessor.encoder.transform(treated_train)
            base_valid = pipeline.preprocessor.encoder.transform(treated_valid)
            xtrain = np.column_stack([base_train, semantic_train.to_numpy()])
            xvalid = np.column_stack([base_valid, semantic_valid.to_numpy()])
            if (np.isinf(xtrain).any() or np.isinf(xvalid).any() or
                not np.isfinite(semantic_train.to_numpy()).all() or not np.isfinite(semantic_valid.to_numpy()).all()):
                raise ValueError('Infinite or nonfinite NEW semantic feature; no generic fill allowed')
            write_json(directory/'native-missing-receipt.json', {
                'treatment':'PRESERVE_FROZEN_V18_NATIVE_NAN_NO_IMPUTATION',
                'trainingNativeMissingCells':int(np.isnan(base_train).sum()),
                'validationNativeMissingCells':int(np.isnan(base_valid).sum()),
                'newSemanticMissingCells':0,'estimatorsNativeNaNSupported':True})
            base_names = list(pipeline.preprocessor.get_feature_names_out())+semantic.feature_names
            masks_train, _ = regime_masks(training)
            masks_valid, registry = regime_masks(validation)
            regime_order = list(masks_train)
            ztrain = np.column_stack([masks_train[n] for n in regime_order]).astype(float)
            zvalid = np.column_stack([masks_valid[n] for n in regime_order]).astype(float)
            ctrain,_ = clusters.transform(pd.concat([training,semantic_train],axis=1))
            cvalid, labels = clusters.transform(pd.concat([validation,semantic_valid],axis=1))
            labels.insert(0,'canonicalPaId',validation.canonicalPaId)
            labels.to_parquet(directory/'cluster-labels.parquet',index=False)
            write_json(directory/'regime-input-registry.json',registry)
            y = training.observedClassIndex.to_numpy(dtype=int)
            artifacts = [ref(checkpoint),ref(directory/'cluster-labels.parquet')]
            for variant in VARIANTS:
                artifact_path = directory/(variant+'.joblib')
                prediction_path = directory/(variant+'-probabilities.npy')
                verified_path = directory/(variant+'-verified.json')
                if verified_path.exists():
                    receipt = json.loads(verified_path.read_text())
                    assert sha_file(artifact_path)==receipt['model']['sha256'] and sha_file(prediction_path)==receipt['predictions']['sha256']
                    artifacts.extend([ref(artifact_path),ref(prediction_path),ref(verified_path)])
                    emit('VERIFIED_MODEL_REUSED',fold=number,model=variant)
                    continue
                if artifact_path.exists() or prediction_path.exists():
                    raise RuntimeError('Incomplete candidate attempt exists; preserve and review before explicit recovery')
                tx,vx,names=xtrain,xvalid,list(base_names)
                if variant in ('REGIME_HGB','REGIME_CLUSTER_HGB'):
                    tx,vx=np.column_stack([tx,ztrain]),np.column_stack([vx,zvalid])
                    names += ['regime_'+n for n in regime_order]
                if variant=='REGIME_CLUSTER_HGB':
                    tx,vx=np.column_stack([tx,ctrain.to_numpy()]),np.column_stack([vx,cvalid.to_numpy()])
                    names += list(ctrain.columns)
                if variant=='SEMANTIC_EXTRA_TREES':
                    model=ExtraTreesClassifier(n_estimators=240,max_depth=20,min_samples_leaf=50,max_features=.7,
                        bootstrap=False,n_jobs=4,random_state=20260911+number)
                    with joblib.parallel_backend('threading'):
                        fitted(variant,lambda:model.fit(tx,y),number)
                else:
                    params=dict(saved['modelParameters'])
                    params['random_state']=20260911+number
                    model=HistGradientBoostingClassifier(**params)
                    fitted(variant,lambda:model.fit(tx,y),number)
                candidate=CandidatePipeline(pipeline.preprocessor,semantic,clusters,model,variant,names,regime_order)
                joblib.dump(candidate,artifact_path,compress=3)
                predictions=predict_estimator(model,vx)
                with prediction_path.open('xb') as handle: np.save(handle,predictions,allow_pickle=False)
                reloaded=joblib.load(artifact_path)
                replay=predict_estimator(reloaded.estimator,vx)
                if not np.array_equal(predictions,replay): raise ValueError('Full validation model reload mismatch')
                fixture=validation.iloc[:32].copy()
                fixture_x=candidate.matrix(fixture,raw)
                fixture_probability=candidate.predict_proba(fixture,raw)
                reload_probability=reloaded.predict_proba(fixture,raw,uncertainty_only_override={'dispersion':1e9})
                if not np.array_equal(fixture_x,vx[:32],equal_nan=True): raise ValueError('Full preprocessing feature parity differs')
                if not np.array_equal(fixture_probability,reload_probability) or not np.array_equal(fixture_probability,predictions[:32]):
                    raise ValueError('Full pipeline reload or uncertainty mean invariance differs')
                fixture_path=directory/(variant+'-reload-fixture.joblib')
                joblib.dump({'rows':fixture,'historyReference':meta['artifacts']['rawDevelopment'],
                    'teamIdentityMap':ref(GAME_PATH),'probabilities':fixture_probability,'orderedFeatures':names},fixture_path,compress=3)
                receipt={'fold':number,'modelName':variant,'model':ref(artifact_path),'predictions':ref(prediction_path),
                    'fixture':ref(fixture_path),'modelReloadComparedRows':len(validation),'modelReloadMismatchCount':0,
                    'fullPipelineReloadComparedRows':32,'fullPipelineReloadMismatchCount':0,
                    'uncertaintyOnlyMeanInvariance':True,'featureCount':len(names),'orderedFeatures':names,
                    'sourceHistoryMaximumDate':str(raw.game_date.max()),'featureCountCutoffRule':'STRICTLY_PRIOR_GAME_DATE',
                    'rawSchema':list(pipeline.ordered_features),'targetOrder':meta['targetOrder'],
                    'researchStatus':'RESEARCH_SHADOW','wageringAuthority':False,'finalOotPayloadBytesRead':0}
                write_json(verified_path,receipt)
                artifacts.extend([ref(artifact_path),ref(prediction_path),ref(fixture_path),ref(verified_path)])
                emit('CANDIDATE_ARTIFACT_RELOAD_VERIFIED',fold=number,model=variant,rows=len(validation),featureCount=len(names))
                del model,candidate,reloaded,tx,vx,predictions,replay
            write_json(complete,{'fold':number,'artifacts':artifacts,'globalFitsCompleted':4,'validationRows':len(validation)})
            emit('FOLD_COMPLETED',fold=number,globalFitsCompleted=4)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--folds',nargs='+',type=int,default=[1,2,3,4,5])
    args=parser.parse_args()
    if any(n not in range(1,6) for n in args.folds): raise ValueError('Only the five registered folds')
    main(args.folds)
