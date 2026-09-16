"""Focused risks introduced by the reduced historical point/Elo assessment."""
import numpy as np
import pandas as pd
import pytest

from server.sports_nba_gen1.historical_pilot import score_predictions, paired_differences


def example():
    return pd.DataFrame({'game_id':['a','b'],'game_date':['2014-01-01','2014-01-10'],
                         'p_home_win':[.8,.3], 'home_score':[110,90], 'away_score':[100,95],
                         'expected_home_score':[108.,94.], 'expected_away_score':[99.,97.]})


def test_binary_probabilities_and_score_orientation():
    result=score_predictions(example())
    assert np.allclose(result.binary_brier,[.04,.09])
    assert np.allclose(result.log_loss,-np.log([.8,.7]))
    assert result.correct_pick.tolist()==[1,1]
    assert result.margin_mae.tolist()==[1,2]
    assert result.total_mae.tolist()==[3,6]
    assert np.array_equal(result.p_home_win+result.p_away_win+result.p_tie,np.ones(2))
    swapped=example().rename(columns={'home_score':'away_score','away_score':'home_score',
                                     'expected_home_score':'expected_away_score','expected_away_score':'expected_home_score'})
    swapped['p_home_win']=1-swapped.p_home_win
    reverse=score_predictions(swapped)
    assert np.allclose(result.log_loss,reverse.log_loss)
    assert np.allclose(result.binary_brier,reverse.binary_brier)
    assert np.allclose(result.margin_mae,reverse.margin_mae)


def test_no_tie_or_duplicate_observed_game_accepted():
    tied=example()
    tied.loc[0,'away_score']=110
    with pytest.raises(ValueError,match='untied'):
        score_predictions(tied)
    with pytest.raises(ValueError,match='One prediction'):
        score_predictions(pd.concat([example(),example()]))


def test_pairing_is_by_game_and_zero_difference_has_zero_uncertainty():
    base=score_predictions(example()).assign(family='league')
    changed=base.iloc[::-1].assign(family='elo')
    result=paired_differences(pd.concat([base,changed]),replicates=50)
    assert result['games']==2
    for metric in result['metrics'].values():
        assert metric['meanDifference']==0
        assert metric['interval95']==[0,0]
    changed=changed.iloc[:1]
    with pytest.raises(ValueError,match='cohorts differ'):
        paired_differences(pd.concat([base,changed]))
