from copy import deepcopy

from server.sports_current_statcast.mlb_v18_current_slate import numerical_identity, source_body, write_object
from server.sports_current_statcast.mlb_v18_current_inputs import compose_current_input
from tests.test_mlb_v18_current_inputs import _fixture
import pytest


def test_incremental_source_objects_and_numerical_identity_ignore_publication_clocks(tmp_path):
    old = {'game': {'game_id': 'g', 'starts_at': '2026-09-10T23:00:00Z'},
           'sides': [], 'snapshotContentSha256': 'old-capture',
           'existingForecastMetadata': {'generated_at': '2026-09-10T10:00:00Z'}}
    new = deepcopy(old)
    new['snapshotContentSha256'] = 'new-capture'
    new['existingForecastMetadata']['generated_at'] = '2026-09-10T11:00:00Z'
    first, reused1 = write_object(tmp_path, 'source-evidence.json', source_body(old))
    second, reused2 = write_object(tmp_path, 'source-evidence.json', source_body(new))
    assert first == second and not reused1 and reused2
    identity = numerical_identity(game_id='g', model_sha='a' * 64, ordered_inputs=[1, 2], seed=18)
    assert identity == numerical_identity(game_id='g', model_sha='a' * 64, ordered_inputs=[1, 2], seed=18)
    assert identity != numerical_identity(game_id='g', model_sha='a' * 64, ordered_inputs=[1, 3], seed=18)
    changed = deepcopy(new)
    changed['game']['game_id'] = 'different-event'
    assert write_object(tmp_path, 'source-evidence.json', source_body(changed))[0] != first


def test_composition_rejects_actual_late_execution_and_future_evidence():
    metadata, event, evidence = _fixture()
    with pytest.raises(ValueError, match='pregame'):
        compose_current_input(source_order=metadata['sourceColumns'], event=event, batting_side='AWAY',
                              as_of_utc=event['startsAtUtc'], field_evidence=evidence)
    event['source']['availableAsOf'] = '2026-09-10T14:00:00Z'
    with pytest.raises(ValueError, match='CUTOFF'):
        compose_current_input(source_order=metadata['sourceColumns'], event=event, batting_side='AWAY',
                              as_of_utc='2026-09-10T13:00:00Z', field_evidence=evidence)
