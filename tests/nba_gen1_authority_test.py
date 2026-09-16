"""Synthetic source-contract mechanics only; never a real-data/model assessment."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
import pytest

from server.sports_nba_gen1 import authority as a


def _write(path, value):
    path.write_bytes(a.json_bytes(value))
    return a.reference(path)


def _parquet(path, rows):
    pd.DataFrame(rows).to_parquet(path, index=False)
    return a.reference(path)


def _record(season, raw_sha):
    return dict(game_id=f"test-{season}", season=season, season_type="REGULAR", home_team_id="A", away_team_id="B",
                scheduled_tipoff_utc=f"{season}-11-01T23:00:00Z", schedule_available_at_utc=f"{season}-10-01T00:00:00Z",
                status="FINAL", source_revision=1, source_available_at_utc=f"{season}-11-02T02:00:00Z",
                source_published_at_utc=f"{season}-11-02T02:00:00Z", captured_at_utc="2026-09-13T23:00:00Z",
                source_object_sha256=raw_sha)


def _payload(meta, ot=0):
    row = {**meta, "home_score": 110, "away_score": 100, "overtime_periods": ot}
    for side, fgm in (("home", 40), ("away", 35)):
        row.update({f"{side}_fgm": fgm, f"{side}_fga": 90, f"{side}_fg3m": 10,
                    f"{side}_ftm": 20, f"{side}_fta": 25, f"{side}_oreb": 10,
                    f"{side}_dreb": 30, f"{side}_tov": 12, f"{side}_minutes": 240+25*ot})
    return row


def _index(tmp_path):
    # The parser tests use symbolic review evidence. They establish no source
    # permission and must never be passed to fitting or reported as coverage.
    proof = _write(tmp_path/"test-only-review.json", {"purpose": "UNIT_TEST_ONLY_NOT_SOURCE_AUTHORIZATION"})
    index = dict(schemaVersion=a.INDEX_SCHEMA, dataClassification="REAL_UNSCRAMBLED_OFFICIAL_GAMES",
                 reviewStatus="VERIFIED_REAL_TRAINING_AUTHORITY", reviewedBy="UNIT_TEST", provider="UNIT_TEST",
                 reviewedAtUtc="2026-09-13T23:00:00Z", approvalReceipt=proof, rights={key: True for key in a.RIGHTS},
                 rightsEvidence=[proof], timestampSemantics="AUTHENTICATED_SOURCE_REVISION_AVAILABILITY", timestampEvidence=proof,
                 costAuthorization={"newSpendingAllowed": False}, teamIdentityMap=proof,
                 identityReconciliation={"unresolvedReplacementEvents": 0}, seasons=[])
    for season in range(2020, 2025):
        source = _write(tmp_path/f"test-only-source-{season}.json", {"purpose": "UNIT_TEST_ONLY_NOT_REAL_GAMES", "season": season})
        metadata = _record(season, source['sha256'])
        # These nonexistent files prove registration never accesses outcomes.
        missing = {"path": str(tmp_path/f"DO-NOT-OPEN-{season}.parquet"), "sha256": "0"*64, "bytes": 1}
        index['seasons'].append(dict(season=season, completeRegularSeason=True,
                                    metadata=_parquet(tmp_path/f"metadata-{season}.parquet", [metadata]),
                                    rawObjects=[source], games=missing, overtimePeriods=dict(missing)))
    return index


def _modify_metadata(index, part_index, transform):
    part = index['seasons'][part_index]
    path = Path(part['metadata']['path'])
    frame = pd.read_parquet(path)
    result = transform(frame)
    part['metadata'] = _parquet(path, result if result is not None else frame)


def _add_payloads(index, season, tmp_path, *, ot=0, periods=None):
    part = next(p for p in index['seasons'] if p['season'] == season)
    meta = pd.read_parquet(part['metadata']['path']).iloc[0].to_dict()
    part['games'] = _parquet(tmp_path/f"games-{season}.parquet", [_payload(meta, ot)])
    fields = ['game_id', 'source_revision', 'period', 'home_points', 'away_points', 'source_available_at_utc', 'source_object_sha256']
    rows = [{**{key: meta[key] for key in ('game_id', 'source_revision', 'source_available_at_utc', 'source_object_sha256')},
             **entry} for entry in (periods or [])]
    path = tmp_path/f"periods-{season}.parquet"
    pd.DataFrame(rows, columns=fields).to_parquet(path, index=False)
    part['overtimePeriods'] = a.reference(path)


def test_metadata_only_registration_locks_roles_and_is_idempotent(tmp_path, monkeypatch):
    index = _index(tmp_path)
    index_path = tmp_path/"index.json"
    _write(index_path, index)
    binding = a.reference(Path(a.__file__))
    monkeypatch.setattr(a, 'numerical_source_bindings', lambda: {name: binding for name in ('authority.py', 'features.py', 'distribution.py', 'models.py', 'assessment.py', 'runner.py', 'forecast.py')})
    first = a.register_plan(index_path, tmp_path/"study")
    before = Path(first['path']).read_bytes()
    second = a.register_plan(index_path, tmp_path/"study")
    assert first == second and Path(first['path']).read_bytes() == before
    plan = json.loads(before)
    assert plan['roles'] == {'development': [2020, 2021, 2022], 'validation': [2023], 'oot': [2024]}
    assert plan['outcomesOpened'] is False
    assert plan['featureContract']['sha256']
    assert len(plan['numericalSources']) == 7
    monkeypatch.setattr(a, 'numerical_source_bindings', lambda: {'authority.py': {**binding, 'sha256': '1'*64}})
    with pytest.raises(a.NbaAdmissionError, match='numerical source inventory changed'):
        a.register_plan(index_path, tmp_path/"study")


@pytest.mark.parametrize('mutation,message', [
    (lambda d: d.update(dataClassification='FIXTURES'), 'Fixtures'),
    (lambda d: d.update(dataClassification='SCRAMBLED_TRIAL'), 'Fixtures'),
    (lambda d: d['rights'].update(historicalModelTraining=False), 'rights'),
    (lambda d: d.update(rightsEvidence=[]), 'Rights evidence'),
    (lambda d: d.update(timestampSemantics='RECONSTRUCTED_NEXT_DAY'), 'reconstructed'),
    (lambda d: d.update(costAuthorization={'newSpendingAllowed': True}), 'spending'),
    (lambda d: d.update(seasons=d['seasons'][:-1]), 'three Development'),
    (lambda d: d['identityReconciliation'].update(unresolvedReplacementEvents=1), 'replacement'),
])
def test_fixture_rights_scope_and_lineage_fail_closed(tmp_path, mutation, message):
    index = _index(tmp_path)
    mutation(index)
    with pytest.raises(a.NbaAdmissionError, match=message):
        a.validate_index(index)


@pytest.mark.parametrize('field,value,message', [
    ('home_score', 110, 'Outcome columns'),
    ('away_team_id', 'A', 'identity collision'),
    ('home_team_id', '', 'nonempty strings'),
    ('source_revision', 1.5, 'integer source revision'),
    ('schedule_available_at_utc', '2020-11-01T23:00:00Z', 'before tipoff'),
    ('source_available_at_utc', '2020-11-01T23:00:00Z', 'Availability precedes publication'),
    ('source_available_at_utc', '2020-11-02 02:00:00', 'timezone'),
])
def test_identity_and_clock_errors_rejected_before_outcomes(tmp_path, field, value, message):
    index = _index(tmp_path)
    def transform(frame):
        frame[field] = value
        return frame
    _modify_metadata(index, 0, transform)
    with pytest.raises(a.NbaAdmissionError, match=message):
        a.validate_index(index)


def test_revision_orientation_and_replacement_resolutions_are_required(tmp_path):
    index = _index(tmp_path)
    def transform(frame):
        newer = frame.iloc[0].to_dict()
        newer.update(source_revision=2, home_team_id='B', away_team_id='A')
        return pd.concat([frame, pd.DataFrame([newer])], ignore_index=True)
    _modify_metadata(index, 0, transform)
    with pytest.raises(a.NbaAdmissionError, match='orientation'):
        a.validate_index(index)


def test_phase_loading_never_opens_adjacent_seasons(tmp_path, monkeypatch):
    index = _index(tmp_path)
    _add_payloads(index, 2022, tmp_path)
    a.validate_index(index)
    opened = []
    original = a.verified_bytes
    def track(bound):
        opened.append(bound['path'])
        return original(bound)
    monkeypatch.setattr(a, 'verified_bytes', track)
    games, periods = a.load_seasons(index, [2022])
    assert set(games.season) == {2022} and periods.empty
    assert not any('DO-NOT-OPEN' in path or 'metadata-2023' in path or 'metadata-2024' in path for path in opened)


def test_original_outcome_bytes_cannot_cross_season_partitions(tmp_path):
    index = _index(tmp_path)
    index['seasons'][1]['rawObjects'] = deepcopy(index['seasons'][0]['rawObjects'])
    with pytest.raises(a.NbaAdmissionError, match='crosses season partitions'):
        a.validate_index(index)


def test_overtime_sorting_source_binding_and_final_score_reconciliation(tmp_path):
    index = _index(tmp_path)
    _add_payloads(index, 2022, tmp_path, ot=2, periods=[
        {'period': 6, 'home_points': 12, 'away_points': 2},
        {'period': 5, 'home_points': 10, 'away_points': 10},
    ])
    games, periods = a.load_seasons(index, [2022])
    assert len(games) == 1 and len(periods) == 2
    part = index['seasons'][2]
    path = Path(part['overtimePeriods']['path'])
    frame = pd.read_parquet(path)
    frame.loc[frame.period == 6, 'home_points'] = 13
    part['overtimePeriods'] = _parquet(path, frame)
    with pytest.raises(a.NbaAdmissionError, match='reconcile'):
        a.load_seasons(index, [2022])


@pytest.mark.parametrize('field,value,message', [
    ('home_points', 20.5, 'integer overtime'),
    ('period', 5.5, 'integer overtime'),
    ('source_revision', 2, 'revision is outside'),
    ('source_object_sha256', 'f'*64, 'source mismatch'),
    ('source_available_at_utc', '2022-11-02T02:01:00Z', 'clock mismatch'),
])
def test_overtime_integer_revision_and_source_requirements(tmp_path, field, value, message):
    index = _index(tmp_path)
    _add_payloads(index, 2022, tmp_path, ot=1, periods=[{'period': 5, 'home_points': 20, 'away_points': 10}])
    part = index['seasons'][2]
    path = Path(part['overtimePeriods']['path'])
    frame = pd.read_parquet(path)
    frame[field] = value
    part['overtimePeriods'] = _parquet(path, frame)
    with pytest.raises(a.NbaAdmissionError, match=message):
        a.load_seasons(index, [2022])
