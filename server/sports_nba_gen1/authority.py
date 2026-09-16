"""Offline real-data admission and season gates for NBA Gen 1.

No provider client or synthetic performance path. The index contains metadata
only; outcome payloads must be physically separated by season. An asserted flag
alone is not a source license: rights and timestamp semantics require bound
evidence and a named approval receipt.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

INDEX_SCHEMA = 'NBA_GEN1_REAL_POPULATION_INDEX_V1'
RESEARCH_FLAGS = {'researchOnly': True, 'productionAuthority': False, 'wageringAuthority': False,
                  'schedulerAuthority': False, 'accountCreationAuthority': False}
BOX = ('fgm', 'fga', 'fg3m', 'ftm', 'fta', 'oreb', 'dreb', 'tov', 'minutes')
META = ('game_id', 'season', 'season_type', 'home_team_id', 'away_team_id',
        'scheduled_tipoff_utc', 'schedule_available_at_utc', 'status', 'source_revision',
        'source_available_at_utc', 'source_published_at_utc', 'captured_at_utc', 'source_object_sha256')
OUTCOME_FIELDS = {'home_score', 'away_score', 'overtime_periods'} | {f'{side}_{key}' for side in ('home', 'away') for key in BOX}
RIGHTS = ('retrieval', 'rawRetention', 'historicalModelTraining', 'derivedForecastRetention', 'derivedForecastDisplay')


class NbaAdmissionError(ValueError):
    pass


def require(test, message):
    if not test:
        raise NbaAdmissionError(message)


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def reference(path):
    p = Path(path).resolve()
    raw = p.read_bytes()
    return {'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def verified_bytes(bound):
    require(isinstance(bound, Mapping) and {'path', 'sha256', 'bytes'} <= bound.keys(), 'Physical artifact binding required')
    raw = Path(bound['path']).read_bytes()
    require(len(raw) == bound['bytes'] and hashlib.sha256(raw).hexdigest() == bound['sha256'], 'Physical source bytes changed')
    return raw


def immutable_json(root, name, value):
    raw = json_bytes(value)
    sha = hashlib.sha256(raw).hexdigest()
    path = Path(root)/'objects/sha256'/sha/name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == raw, 'Immutable object collision')
    else:
        path.write_bytes(raw)
    return reference(path)


def numerical_source_bindings():
    """Bind the exact executable protocol; no fitted module imports required."""
    root = Path(__file__).resolve().parent
    names = ('authority.py', 'features.py', 'distribution.py', 'models.py', 'assessment.py', 'runner.py', 'forecast.py')
    require(all((root/name).is_file() for name in names), 'Complete numerical protocol must exist before registration')
    return {name: reference(root/name) for name in names}


def _integer_values(series, label, minimum=0):
    values = pd.to_numeric(series, errors='coerce').to_numpy(float)
    require(np.isfinite(values).all() and (values >= minimum).all() and (values == np.floor(values)).all(),
            'Expected integer '+label)


def _clocks(series, label):
    for value in series:
        try:
            parsed = pd.Timestamp(value)
        except (TypeError, ValueError):
            raise NbaAdmissionError('Uncertified source/schedule clock: '+label) from None
        require(not pd.isna(parsed) and parsed.tzinfo is not None, 'Explicit timezone required: '+label)
    return pd.to_datetime(series, utc=True, errors='raise')


def validate_index(index):
    """Inspect rights and identity metadata only; no score/box/OT payload opens."""
    require(index.get('schemaVersion') == INDEX_SCHEMA, 'Unsupported real-data source contract')
    require(index.get('dataClassification') == 'REAL_UNSCRAMBLED_OFFICIAL_GAMES', 'Fixtures, simulated and scrambled trial data are ineligible')
    require(index.get('reviewStatus') == 'VERIFIED_REAL_TRAINING_AUTHORITY', 'Named source review and permissions are missing')
    require(index.get('reviewedBy') and index.get('provider') and index.get('reviewedAtUtc'), 'Source review identity missing')
    verified_bytes(index['approvalReceipt'])
    require(all(index.get('rights', {}).get(k) is True for k in RIGHTS), 'Retrieval, retention, training and derivative rights must all be established')
    require(index.get('rightsEvidence'), 'Rights evidence is missing')
    for bound in index['rightsEvidence']:
        verified_bytes(bound)
    require(index.get('timestampSemantics') == 'AUTHENTICATED_SOURCE_REVISION_AVAILABILITY', 'No reconstructed next-day or acquisition-as-historical availability')
    verified_bytes(index['timestampEvidence'])
    require(index.get('costAuthorization', {}).get('newSpendingAllowed') is False, 'This assignment authorizes no spending')
    seasons = index.get('seasons', [])
    require(len(seasons) >= 5, 'At least three Development seasons, Validation and OOT required; shorter coverage is a separate pilot')
    _integer_values(pd.Series([s['season'] for s in seasons]), 'season', 1946)
    numbers = [int(s['season']) for s in seasons]
    require(numbers == sorted(set(numbers)) and np.all(np.diff(numbers) == 1), 'Consecutive, unique, ordered seasons required')
    require(all(s.get('completeRegularSeason') is True for s in seasons), 'Complete regular-season coverage must be certified')
    require(index.get('teamIdentityMap'), 'Stable team/franchise mapping required')
    verified_bytes(index['teamIdentityMap'])
    # Original response bytes can expose outcomes too. A shared multi-season
    # response must never be read through an earlier role's normalized table.
    raw_seasons = {}
    for part in seasons:
        require(part.get('rawObjects'), 'Original source byte receipts required')
        for raw in part['rawObjects']:
            require(isinstance(raw, Mapping) and {'path', 'sha256', 'bytes'} <= raw.keys(), 'Physical raw-object binding required')
            sha, season = raw['sha256'], int(part['season'])
            require(sha not in raw_seasons or raw_seasons[sha] == season,
                    'Outcome-bearing original source object crosses season partitions')
            raw_seasons[sha] = season
    all_metadata = []
    for part in seasons:
        # Only independent metadata objects open before the role declaration.
        meta = pd.read_parquet(io.BytesIO(verified_bytes(part['metadata'])))
        require(not (set(meta) & OUTCOME_FIELDS), 'Outcome columns found in identity-only index')
        require(set(META) <= set(meta), 'Missing stable identities or source/schedule clocks')
        _integer_values(meta.season, 'season', 1946)
        _integer_values(meta.source_revision, 'source revision', 1)
        require(set(meta.season.astype(int)) == {int(part['season'])}, 'Season metadata binding mismatch')
        require(set(meta.season_type) <= {'REGULAR'}, 'Playoffs/exhibitions require separate scope')
        require(set(meta.status) <= {'FINAL', 'CANCELLED', 'POSTPONED'}, 'Completed-season index has unsupported game statuses')
        require(meta.game_id.notna().all() and meta.home_team_id.notna().all() and meta.away_team_id.notna().all(), 'Null game/team identity')
        for identity in ('game_id', 'home_team_id', 'away_team_id'):
            require(meta[identity].map(lambda value: isinstance(value, str) and bool(value.strip())).all(), 'Canonical game/team identities must be nonempty strings; preserve original numeric provider IDs separately')
        require(all(meta[col].map(lambda x: bool(str(x).strip())).all() for col in ('game_id', 'home_team_id', 'away_team_id')), 'Blank game/team identity')
        require((meta.home_team_id != meta.away_team_id).all(), 'Home/away identity collision')
        for column in ('scheduled_tipoff_utc', 'schedule_available_at_utc', 'source_available_at_utc', 'source_published_at_utc', 'captured_at_utc'):
            _clocks(meta[column], column)
        require((pd.to_datetime(meta.schedule_available_at_utc, utc=True) < pd.to_datetime(meta.scheduled_tipoff_utc, utc=True)).all(), 'Schedule must have been published before tipoff')
        require((pd.to_datetime(meta.source_published_at_utc, utc=True) <= pd.to_datetime(meta.source_available_at_utc, utc=True)).all(), 'Availability precedes publication')
        require((pd.to_datetime(meta.source_available_at_utc, utc=True) <= pd.to_datetime(meta.captured_at_utc, utc=True)).all(), 'Source availability cannot exceed retained capture clock')
        finals = meta[meta.status == 'FINAL']
        require((pd.to_datetime(finals.source_available_at_utc, utc=True) > pd.to_datetime(finals.scheduled_tipoff_utc, utc=True)).all(), 'Final result availability must follow tipoff')
        require(part.get('rawObjects'), 'Original source byte receipts required')
        raw_shas = {x['sha256'] for x in part['rawObjects']}
        require(set(meta.source_object_sha256) <= raw_shas, 'Game revision is not bound to retained source bytes')
        for field in ('games', 'overtimePeriods'):
            require({'path', 'sha256', 'bytes'} <= part[field].keys(), 'Partitioned data artifact missing: '+field)
        all_metadata.append(meta)
    joined = pd.concat(all_metadata, ignore_index=True)
    require(not joined.duplicated(['game_id', 'source_revision']).any(), 'Duplicate game revision; replacement events must not double count')
    for gid, group in joined.groupby('game_id', sort=False):
        require(group.season.nunique() == group.home_team_id.nunique() == group.away_team_id.nunique() == 1, 'Unresolved identity/orientation revision: '+str(gid))
        require(group.scheduled_tipoff_utc.nunique() == 1, 'Rescheduled identities need an explicit resolved schedule-vintage index before admission')
        ordered = group.sort_values('source_revision')
        clocks = pd.to_datetime(ordered.source_available_at_utc, utc=True)
        require(clocks.is_monotonic_increasing, 'Revision availability runs backwards: '+str(gid))
    require(index.get('identityReconciliation', {}).get('unresolvedReplacementEvents') == 0, 'Unresolved cancelled/postponed/replacement identity')
    return joined


def register_plan(index_path, output):
    bound = reference(index_path)
    index = json.loads(verified_bytes(bound))
    metadata = validate_index(index)
    from .features import feature_contract
    contract = feature_contract()
    code = numerical_source_bindings()
    pointer = Path(output)/'declaration.json'
    if pointer.exists():
        previous_ref = json.loads(pointer.read_bytes())
        previous = json.loads(verified_bytes(previous_ref))
        require(previous.get('sourceIndex', {}).get('sha256') == bound['sha256'], 'Use a new study identity; source index changed')
        require(previous.get('featureContract') == contract, 'Use a new study identity; feature contract changed')
        old_sources = previous.get('numericalSources', {})
        require(set(old_sources) == set(code), 'Use a new study identity; numerical source inventory changed')
        for name, source in code.items():
            require(old_sources[name]['sha256'] == source['sha256'] and old_sources[name]['bytes'] == source['bytes'],
                    'Use a new study identity; numerical protocol changed: '+name)
        return previous_ref
    seasons = [int(s['season']) for s in index['seasons']]
    roles = {'development': seasons[:-2], 'validation': [seasons[-2]], 'oot': [seasons[-1]]}
    plan = {'schemaVersion': 'NBA_GEN1_CHRONOLOGICAL_DECLARATION_V1', 'createdAtUtc': datetime.now(timezone.utc).isoformat(),
        'sourceIndex': bound, 'roles': roles, 'scope': 'NBA_REGULAR_SEASON_FULL_GAME_INCLUDING_OVERTIME',
        'featureContract': contract, 'numericalSources': code,
        'gameIdentitySha256': hashlib.sha256(json_bytes(sorted(metadata.game_id.unique().tolist()))).hexdigest(),
        'metadataRows': len(metadata), 'distinctGames': metadata.game_id.nunique(), 'outcomesOpened': False,
        'featureWarmup': 'First Development games without eligible history are explicitly unsupported; no fixture/prior constant becomes a trained feature.',
        'screen': {'league': [{}], 'elo': [{}], 'ridge': [{'alpha': 10.0}, {'alpha': 100.0}],
            'hgb': [{'l2_regularization': 10.0}, {'l2_regularization': 50.0}]},
        'hyperparameterSelection': 'Earlier Development season-forward forecasts; chronological residual donors strictly earlier than each scored game. Joint energy chooses one setting within each family.',
        'selectionOrder': ['league', 'elo', 'ridge', 'hgb'], 'draws': 10000, 'seed': 20260913,
        'minimumTrainingGames': 400, 'minimumResidualDonors': 200, 'minimumOvertimePeriods': 20,
        'gate': {'minimumRelativeEnergyImprovement': .01, 'pairedEnergyUpper95BelowZero': True,
            'maximumLogLossDeterioration': .005, 'maximumBrierDeterioration': .002,
            'maximumMarginalCrpsRelativeDeterioration': .01, 'maximumAbsoluteCoverageDeterioration': .02,
            'minimumWidthRatio': .9, 'maximumWidthRatio': 1.2, 'bothValidationHalvesEnergyNonpositive': True},
        'calibration': 'DISABLED_FOR_GEN1_SCREEN', 'blend': 'DISABLED_FOR_GEN1_SCREEN',
        'outcomeAccess': 'Development first; Validation only after Development settings frozen; OOT only after signed selection artifact. One OOT run, no OOT tuning.',
        'postOotRefit': 'Selected locked configuration may refit through OOT for a separately identified research model; preserve assessment.',
        **RESEARCH_FLAGS}
    saved = immutable_json(output, 'declaration.json', plan)
    pointer.write_bytes(json_bytes(saved))
    return saved


def load_seasons(index, seasons):
    """Only call after the role's gate. One metadata row per retained source revision."""
    games, overtime = [], []
    for part in index['seasons']:
        if int(part['season']) not in seasons:
            continue
        meta = pd.read_parquet(io.BytesIO(verified_bytes(part['metadata'])))
        frame = pd.read_parquet(io.BytesIO(verified_bytes(part['games'])))
        require(set(META) | OUTCOME_FIELDS <= set(frame), 'Missing real game box fields')
        require(set(frame.season.astype(int)) == {int(part['season'])}, 'Payload escapes declared season')
        require(len(frame) == len(meta), 'Metadata and payload revision counts differ')
        pd.testing.assert_frame_equal(frame[list(META)].reset_index(drop=True), meta[list(META)].reset_index(drop=True), check_dtype=False)
        final = frame[frame.status == 'FINAL']
        require(final[list(OUTCOME_FIELDS)].notna().all().all(), 'Final scores/box fields missing')
        require((final.home_score != final.away_score).all(), 'Final NBA games cannot tie')
        for column in OUTCOME_FIELDS:
            values = pd.to_numeric(final[column], errors='raise').to_numpy(float)
            require(np.isfinite(values).all() and (values >= 0).all(), 'Invalid score or box quantity')
            if not column.endswith('_minutes'):
                _integer_values(final[column], column)
        for side in ('home', 'away'):
            require((final[side+'_fgm'] <= final[side+'_fga']).all() and (final[side+'_fg3m'] <= final[side+'_fgm']).all(), 'Impossible field goals')
            require((final[side+'_ftm'] <= final[side+'_fta']).all(), 'Impossible free throws')
            score = 2*final[side+'_fgm'] + final[side+'_fg3m'] + final[side+'_ftm']
            require(np.array_equal(score, final[side+'_score']), 'Box score points do not reconcile')
            require(np.allclose(final[side+'_minutes'], 240+25*final.overtime_periods, atol=.1, rtol=0), 'Team minutes must include overtime and five players')
        require((pd.to_datetime(final.source_available_at_utc, utc=True) > pd.to_datetime(final.scheduled_tipoff_utc, utc=True)).all(), 'Final result availability must follow tipoff')
        periods = pd.read_parquet(io.BytesIO(verified_bytes(part['overtimePeriods'])))
        period_fields = {'game_id', 'source_revision', 'period', 'home_points', 'away_points', 'source_available_at_utc', 'source_object_sha256'}
        require(period_fields <= set(periods), 'Actual overtime-period evidence is required for empirical tie treatment')
        require(not periods.duplicated(['game_id', 'source_revision', 'period']).any(), 'Duplicate overtime period')
        require(set(periods.game_id) <= set(final.game_id), 'Overtime period belongs outside admitted finals')
        require(set(zip(periods.game_id, periods.source_revision)) <= set(zip(final.game_id, final.source_revision)), 'Overtime period revision is outside admitted finals')
        for column in ('period', 'home_points', 'away_points', 'source_revision'):
            _integer_values(periods[column], 'overtime '+column, 1 if column == 'source_revision' else 0)
        require((periods.period >= 5).all() and (periods[['home_points', 'away_points']] >= 0).all().all(), 'Invalid overtime-period scoring')
        for _, game in final.iterrows():
            p = periods[(periods.game_id == game.game_id) & (periods.source_revision == game.source_revision)].sort_values('period')
            require(len(p) == int(game.overtime_periods), 'Missing declared overtime periods')
            if len(p):
                require(set(p.period) == set(range(5, 5+int(game.overtime_periods))), 'Nonconsecutive overtime sequence')
                require(p.iloc[-1].home_points != p.iloc[-1].away_points, 'Last actual overtime period must resolve the tie')
                require((p.iloc[:-1].home_points == p.iloc[:-1].away_points).all(), 'Earlier overtime periods must remain tied')
                require((p.source_available_at_utc == game.source_available_at_utc).all(), 'Overtime evidence revision clock mismatch')
                require((p.source_object_sha256 == game.source_object_sha256).all(), 'Overtime evidence source mismatch')
                home_regulation = game.home_score-p.home_points.sum()
                away_regulation = game.away_score-p.away_points.sum()
                require(home_regulation >= 0 and away_regulation >= 0 and home_regulation == away_regulation,
                        'Overtime scoring must reconcile to a tied regulation score and the final margin')
        for source in part['rawObjects']:
            verified_bytes(source)
        games.append(frame)
        overtime.append(periods)
    require(len(games) > 0, 'No admitted seasons')
    return pd.concat(games, ignore_index=True), pd.concat(overtime, ignore_index=True)


def latest_final_rows(games):
    """One governed latest final outcome per game for labels, never pregame facts."""
    frame = games.sort_values(['source_revision', 'source_available_at_utc']).drop_duplicates('game_id', keep='last')
    return frame[frame.status == 'FINAL'].copy()
