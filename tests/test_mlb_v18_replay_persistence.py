"""Focused protection against the newly found ndarray serialization defect."""
import json
import numpy as np
import pytest
from scripts.run_mlb_v18_instrumented_replay_v2 import write

def test_full_paired_population_survives_json_round_trip(tmp_path):
    p=tmp_path/'population.json'
    home=np.arange(5000,dtype=np.int64)%31
    away=np.arange(5000,dtype=np.int64)%27
    write(p,{'homeRuns':home,'awayRuns':away,'nested':{'raw':home.copy()},'value':np.float64(.5)})
    saved=json.loads(p.read_bytes())
    assert isinstance(saved['homeRuns'],list)
    assert np.array_equal(saved['homeRuns'],home)
    assert np.array_equal(saved['awayRuns'],away)
    assert np.array_equal(saved['nested']['raw'],home)

def test_unknown_values_are_not_silently_stringified(tmp_path):
    with pytest.raises(TypeError):write(tmp_path/'bad.json',{'value':object()})
