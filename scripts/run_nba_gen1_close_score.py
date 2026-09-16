"""One Development-only close-score transport of frozen paired NBA populations."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from server.sports_nba_gen1.authority import reference, verified_bytes, json_bytes
from server.sports_nba_gen1.close_score import CONFIGURATION as ENGINE, fit_kernel, transform
from server.sports_nba_gen1.joint_residual import joint_counts, DRAW_COUNT, totals_query
from scripts.run_nba_gen1_joint_residual import score

BASE = ROOT / 'outputs/nba-gen1-joint-residual-v1'
OUTPUT = ROOT / 'outputs/nba-gen1-close-score-v1/completed'
PRIOR = OUTPUT.parent


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, doc):
    data = json_bytes(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != data:
        raise ValueError('Refusing to overwrite frozen evidence: ' + str(path))
    path.write_bytes(data)
    return reference(path)


def development_diagnosis(root):
    """No later-season outcomes read to choose component scope or parameters."""
    if (PRIOR / 'development-diagnosis.json').exists() and root != PRIOR:
        original = json.loads((PRIOR / 'development-diagnosis.json').read_bytes())
        raw = verified_bytes(original['calibrationGames'])
        path = root / 'development-calibration-games.parquet'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('Development calibration copy differs')
        path.write_bytes(raw)
        return save(root / 'development-diagnosis.json', original)
    records, by_season = [], []
    for season in (2021, 2022, 2023):
        folder = BASE / 'assessment' / str(season)
        scores = pd.read_parquet(folder / 'scores.parquet')
        scores = scores[scores.configuration == 'paired']
        counts = pd.read_parquet(folder / 'paired-joint-counts.parquet')
        groups = counts.groupby('game_index', sort=False)
        total_source, total_observed = np.zeros(12, dtype=np.int64), np.zeros(12, dtype=np.int64)
        for row in scores.itertuples():
            cell = groups.get_group(row.game_index)
            assert cell['count'].sum() == DRAW_COUNT
            margin = abs(cell.home_score.to_numpy() - cell.away_score.to_numpy())
            source = np.bincount(margin, weights=cell['count'], minlength=13)[1:13].astype(np.int64)
            actual_margin = abs(row.actual_home - row.actual_away)
            observed = np.array([int(actual_margin == k) for k in range(1, 13)], dtype=np.int64)
            total_source += source
            total_observed += observed
            records.append({'game_id': row.game_id, 'game_date': row.game_date, 'season_end': season,
                            'game_index': row.game_index,
                            **{f'source_{k}': int(source[k-1]) for k in range(1, 9)},
                            **{f'observed_{k}': int(observed[k-1]) for k in range(1, 9)}})
        by_season.append({'season': season, 'games': len(scores), 'sourceCounts': total_source.tolist(),
                          'observedCounts': total_observed.tolist()})
    stats = pd.DataFrame(records).sort_values(['game_date', 'game_id']).reset_index(drop=True)
    path = root / 'development-calibration-games.parquet'
    if path.exists():
        raise ValueError('Development diagnosis already frozen')
    path.parent.mkdir(parents=True, exist_ok=True)
    stats.to_parquet(path, index=False, compression='zstd')
    n = len(stats)
    source = np.sum([x['sourceCounts'] for x in by_season], axis=0)
    observed = np.sum([x['observedCounts'] for x in by_season], axis=0)
    modeled = source / (n * DRAW_COUNT)
    actual = observed / n
    crossing = int(np.flatnonzero(np.cumsum(actual) >= np.cumsum(modeled))[0] + 1)
    assert n == 3338 and crossing == 8
    return save(root / 'development-diagnosis.json', {
        'createdAtUtc': now(), 'seasons': by_season, 'games': n,
        'bins': [{'absoluteMargin': k, 'predicted': float(modeled[k-1]), 'observed': float(actual[k-1]),
                  'predictedCumulative': float(modeled[:k].sum()), 'observedCumulative': float(actual[:k].sum())} for k in range(1, 13)],
        'firstCumulativeCrossingRadius': crossing, 'selectedRadius': 8,
        'selectionQualification': 'Radius and method chosen after inspecting Development 2021-2023 distribution counts; no proper-score optimization. Earlier Development results do not become untouched merely because kernel estimation excludes future dates.',
        'laterSeasonOutcomesUsedForChoice': False, 'calibrationGames': reference(path),
    })


def freeze(root):
    if (root / 'method-freeze.json').exists():
        return reference(root / 'method-freeze.json')
    baseline = json.loads((BASE / 'index.json').read_bytes())
    for ref in baseline['artifacts'] + baseline['code']:
        verified_bytes(ref)
    prior = json.loads((BASE / 'starting-preservation.json').read_bytes())
    preserved = [ref for ref in prior['files'] if 'inheritedDirtyTrackedFiles' not in ref['groups']]
    for ref in preserved:
        verified_bytes(ref)
    preservation = save(root / 'starting-preservation.json', {
        'capturedAtUtc': now(), 'branch': subprocess.check_output(['git','branch','--show-current'], cwd=ROOT, text=True).strip(),
        'head': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
        'inheritedTrackedChanges': subprocess.check_output(['git','status','--short','--untracked-files=no'], cwd=ROOT, text=True).splitlines(),
        'files': preserved, 'mlbNflOperationsTouched': False})
    parent_method = json.loads((BASE / 'method-freeze.json').read_bytes())
    diagnosis = development_diagnosis(root)
    dev = pd.read_parquet(root / 'development-calibration-games.parquet')
    final_kernel = fit_kernel(dev[[f'source_{i}' for i in range(1, 9)]].sum().to_numpy(),
                             dev[[f'observed_{i}' for i in range(1, 9)]].sum().to_numpy(), len(dev))
    frozen_kernel = save(root / 'frozen-development-kernel.json', {
        'frozenAtUtc': now(), 'engine': ENGINE, 'calibrationLastDate': str(dev.game_date.max()),
        'calibrationGameIdentitySha256': digest('\n'.join(dev.game_id).encode()), 'kernel': final_kernel,
        'note': 'Fitted solely on Development and physically saved before candidate assessment. No2024-2026 outcomes enter this fit.'})
    prior_kernel = json.loads((PRIOR / 'frozen-development-kernel.json').read_bytes())['kernel']
    assert final_kernel == prior_kernel
    code = [reference(ROOT / x) for x in (
        'scripts/run_nba_gen1_close_score.py', 'server/sports_nba_gen1/close_score.py',
        'scripts/run_nba_gen1_joint_residual.py', 'server/sports_nba_gen1/joint_residual_scoring.py')]
    declaration = {
        'schema': 'NBA_GEN1_CLOSE_SCORE_METHOD_FREEZE_V1', 'frozenAtUtc': now(), 'engine': ENGINE,
        'executionPredecessor': reference(PRIOR / 'method-freeze.json'),
        'integrationCorrection': reference(PRIOR / 'execution-attempt-1-failure.json'),
        'methodAndKernelUnchangedFromPredecessor': True,
        'parent': reference(BASE / 'index.json'), 'parentMethod': reference(BASE / 'method-freeze.json'),
        'parentCohort': reference(BASE / 'cohort-games.json'), 'cohort': parent_method['cohort'],
        'developmentDiagnosis': diagnosis, 'frozenDevelopmentKernel': frozen_kernel, 'preservation': preservation,
        'code': code, 'drawCount': DRAW_COUNT,
        'treatment': 'Conditional randomized quantile transport of absolute integer margins within1..8, separately for odd/even parity. SourceCDF is pooled saved Development paired-distribution count frequency; destinationCDF is matching Development observed frequency. Keep signed winner and exact integer total. Outside margin8 is unchanged. No scale, Ridge, Elo, donor, tail or overtime changes.',
        'estimation': 'For each Development target use only eligible Development calibration games with strictly earlier game_date; no same-date/target inclusion. At least200 games and20 actual close finishes in each parity; otherwise exact baseline fallback. No pseudocounts. Post2023 kernel is frozen using all3338 Development games only.',
        'populationOrder': 'Expand the original lossless paired counts in lexicographic HOME/AWAY order; cell plus within-cell replicate ordinal is the transformation identity. This is NOT a claim of original simulation trajectory order. Each original pair/count is retained as an input; none discarded or independently recombined.',
        'support': 'Nonnegative unequal integer finals. If a proposed margin exceeds the retained total, keep that original pair and count an explicit draw-level support fallback. Never discard mass.',
        'control': 'Saved paired V1 only. Original7009game cohort and baseline scores remain immutable; benchmark from earlier study is not rerun.',
        'assessment': {'primary': 'Joint energy V-statistic, lower better',
                       'other': ['home/away/margin CRPS', 'central50/80/90 coverage and width', 'one-point and close-margin probabilities', 'score/margin MAE', 'total and winner invariance'],
                       'groups': ['all', 'Development2021-2023', 'reused2024-2026', 'season', 'ordinary-rest', 'unavailable-rest', 'season-opener'],
                       'uncertainty': '2000 paired ISO calendar-week block bootstrap resamples; seed731201. Games are assessment units; no draw-level superiority intervals.',
                       'qualification': 'All seasons previously inspected, Category A finalized historical reconstruction, no fresh OOT or prospective evidence. Scope choice sees all Development; kernel parameters for each target remain strictly earlier.'},
        'decisionRule': 'One comparison only. Recommend further research if one-point absolute aggregate frequency error decreases on reused2024-2026, primary energy does not worsen, and margin CRPS does not worsen, while all support/mass/totals/winner invariants hold. Report uncertainty even if it includes zero. Otherwise retain baseline and report failure; no threshold retuning or promotion.',
        'fittedPointModelChanges': 0, 'providerRequests': 0, 'forecastPublications': 0,
        'consumerIntegration': False, 'authorityChanges': False,
    }
    return save(root / 'method-freeze.json', declaration)


def run(root):
    method = json.loads((root / 'method-freeze.json').read_bytes())
    for ref in method['code'] + [method['parent'], method['parentCohort'], method['developmentDiagnosis'], method['frozenDevelopmentKernel']]:
        verified_bytes(ref)
    dev_ref = json.loads((root / 'development-diagnosis.json').read_bytes())['calibrationGames']
    verified_bytes(dev_ref)
    dev = pd.read_parquet(dev_ref['path'])
    cum_source = np.vstack([np.zeros(8, dtype=np.int64), dev[[f'source_{i}' for i in range(1, 9)]].to_numpy().cumsum(axis=0)])
    cum_actual = np.vstack([np.zeros(8, dtype=np.int64), dev[[f'observed_{i}' for i in range(1, 9)]].to_numpy().cumsum(axis=0)])
    kernels, kernel_for_date, scored_ids = {}, {}, []
    cohort = json.loads((BASE / 'cohort-games.json').read_bytes())
    expected_ids = [g['game_id'] for g in cohort['eligible']]
    assert digest('\n'.join(expected_ids).encode()) == method['cohort']['eligibleIdentitySha256']
    for year in range(2021, 2027):
        destination = root / 'assessment' / str(year)
        if (destination / 'receipt.json').exists():
            raise ValueError('Completed assessment must not be repeated')
        destination.mkdir(parents=True, exist_ok=True)
        folder = BASE / 'assessment' / str(year)
        original_receipt = json.loads((folder / 'receipt.json').read_bytes())
        for ref in original_receipt['artifacts']:
            verified_bytes(ref)
        baseline = pd.read_parquet(folder / 'scores.parquet')
        baseline = baseline[baseline.configuration == 'paired'].sort_values(['game_date', 'game_id'])
        cells = pd.read_parquet(folder / 'paired-joint-counts.parquet')
        by_game = cells.groupby('game_index', sort=False)
        populations = pd.read_parquet(folder / 'populations.parquet')
        populations = populations[populations.configuration == 'paired'].set_index('game_index')
        scores, transformations, buffer = [], [], []
        writer = None
        for position, (_, game) in enumerate(baseline.iterrows()):
            date = str(game.game_date)
            if date not in kernel_for_date:
                count = int(np.searchsorted(dev.game_date.to_numpy(), date, side='left'))
                kernel_record = {'kernel': fit_kernel(cum_source[count], cum_actual[count], count),
                    'calibrationLatestDate': None if count == 0 else str(dev.iloc[count-1].game_date),
                    'calibrationGameIdentitySha256': digest('\n'.join(dev.iloc[:count].game_id).encode())}
                if count:
                    assert kernel_record['calibrationLatestDate'] < date
                kid = digest(json_bytes(kernel_record))
                kernels[kid] = kernel_record
                kernel_for_date[date] = kid
            kid = kernel_for_date[date]
            kernel_record = kernels[kid]
            kernel = kernel_record['kernel']
            original = by_game.get_group(game.game_index).sort_values(['home_score', 'away_score'])
            pairs = original[['home_score', 'away_score']].to_numpy(dtype=np.int64)
            counts = original['count'].to_numpy(dtype=np.int64)
            original_count_sha = digest(np.column_stack([pairs, counts]).astype('<i8').tobytes())
            assert original_count_sha == populations.loc[game.game_index, 'joint_counts_int64_le_sha256']
            assert counts.sum() == DRAW_COUNT
            draws = np.repeat(pairs, counts, axis=0)
            changed, effects = transform(draws, game.game_id, kernel)
            assert len(changed) == DRAW_COUNT and np.array_equal(draws.sum(axis=1), changed.sum(axis=1))
            assert np.array_equal(draws[:,0] > draws[:,1], changed[:,0] > changed[:,1])
            outer = abs(draws[:,0] - draws[:,1]) > 8
            assert np.array_equal(draws[outer], changed[outer])
            row = game.to_dict()
            if np.array_equal(draws, changed):
                result = dict(row)
            else:
                result = {**row, **score(changed, int(game.actual_home), int(game.actual_away))}
            for key in ('home_win_probability', 'away_win_probability', 'tie_probability', 'log_loss', 'binary_brier'):
                assert result[key] == row[key], (game.game_id, key)
            for key in row:
                if key.startswith('total_') and key in result:
                    assert abs(float(result[key])-float(row[key])) <= 1e-12, (game.game_id, key)
                    # Every integer total is already checked exactly above.
                    # Retain the original summary instead of changing its last
                    # floating bit solely because canonical draw order changed.
                    result[key] = row[key]
            result.update(configuration='close_score', kernel_id=kid, correction_supported=kernel['ready'])
            for k in range(1, 9):
                result[f'abs_margin_{k}_probability'] = float((abs(changed[:,0]-changed[:,1]) == k).mean())
                result[f'baseline_abs_margin_{k}_probability'] = float((abs(draws[:,0]-draws[:,1]) == k).mean())
            scores.append(result)
            transformed_pairs, transformed_counts = joint_counts(changed)
            transformed_sha = digest(np.column_stack([transformed_pairs, transformed_counts]).astype('<i8').tobytes())
            transformations.append({'game_id': game.game_id, 'game_index': game.game_index, 'game_date': date,
                'kernel_id': kid, 'calibration_games': kernel['calibrationGames'],
                'calibration_latest_date': kernel_record['calibrationLatestDate'], 'correction_supported': kernel['ready'],
                'original_joint_counts_sha256': original_count_sha, 'candidate_joint_counts_sha256': transformed_sha,
                'canonical_candidate_draws_sha256': digest(changed.astype('<i8').tobytes()),
                'changed_draw_count': int(np.any(draws != changed, axis=1).sum()),
                'home_mean_change': float((changed[:,0]-draws[:,0]).mean()),
                'away_mean_change': float((changed[:,1]-draws[:,1]).mean()),
                'max_absolute_team_score_change': int(abs(changed-draws).max()),
                'all_draw_totals_preserved': True, 'all_draw_winners_preserved': True, 'outer_pairs_preserved': True,
                'effects_json': json.dumps(effects, sort_keys=True)})
            buffer.append(pd.DataFrame({'game_index': np.full(len(transformed_pairs), game.game_index, dtype=np.int32),
                'home_score': transformed_pairs[:,0].astype(np.int32), 'away_score': transformed_pairs[:,1].astype(np.int32),
                'count': transformed_counts.astype(np.int32)}))
            if len(buffer) == 100 or position == len(baseline)-1:
                table = pa.Table.from_pandas(pd.concat(buffer, ignore_index=True), preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(destination/'joint-counts.parquet', table.schema, compression='zstd', compression_level=9)
                writer.write_table(table)
                buffer.clear()
            scored_ids.append(game.game_id)
            if (position+1) % 200 == 0:
                print(f'{year}: {position+1}/{len(baseline)}', flush=True)
        writer.close()
        pd.DataFrame(scores).to_parquet(destination/'scores.parquet', index=False, compression='zstd')
        pd.DataFrame(transformations).to_parquet(destination/'transformations.parquet', index=False, compression='zstd')
        # Reread the full retained joint measure once, reconciling counts/digests.
        check = pd.read_parquet(destination/'joint-counts.parquet').groupby('game_index', sort=False)
        for row in transformations:
            frame = check.get_group(row['game_index'])
            assert frame['count'].sum() == DRAW_COUNT
            assert digest(frame[['home_score','away_score','count']].to_numpy(dtype='<i8').tobytes()) == row['candidate_joint_counts_sha256']
        save(destination/'receipt.json', {'completedAtUtc': now(), 'games': len(baseline),
            'frozenMethod': reference(root/'method-freeze.json'), 'allRetainedCountDigestsVerified': True,
            'artifacts': [reference(destination/name) for name in ('scores.parquet','transformations.parquet','joint-counts.parquet')]})
        print(f'{year} complete', flush=True)
    assert scored_ids == expected_ids
    save(root/'kernel-artifacts.json', {'engine': ENGINE, 'createdAtUtc': now(), 'kernels': kernels, 'kernelByDate': kernel_for_date})
    assert fit_kernel(cum_source[-1], cum_actual[-1], len(dev)) == json.loads(verified_bytes(method['frozenDevelopmentKernel']))['kernel']
    old_index = json.loads((BASE/'index.json').read_bytes())
    for ref in old_index['artifacts'] + old_index['code']:
        verified_bytes(ref)
    for ref in json.loads(verified_bytes(method['preservation']))['files']:
        verified_bytes(ref)
    save(root/'run-receipt.json', {'completedAtUtc': now(), 'games': len(scored_ids), 'candidateDraws': len(scored_ids)*DRAW_COUNT,
        'originalBaselineIndexAndBoundArtifactsUnchanged': True, 'originalCohortExact': True,
        'originalPointModelsRefit': False, 'originalSimulationReexecuted': False,
        'consumerPublication': False, 'newProspectiveStudy': False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['freeze','run'])
    parser.add_argument('--output-root', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.action == 'freeze':
        print(json.dumps(freeze(args.output_root), indent=2))
    else:
        run(args.output_root)
