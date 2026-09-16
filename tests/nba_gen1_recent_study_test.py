"""Focused declared selection-gate risks; synthetic mechanics only."""
import pytest

from server.sports_nba_gen1.recent_study import choose_development, choose_validation


R={'id':'ridge_a100','family':'ridge','params':{'alpha':100.0}}
H={'id':'hgb_l2_50','family':'hgb','params':{'l2_regularization':50.0}}


def report(ridge=(95,10,15),hgb=(94.8,10,15)):
    return {'overall':{key:dict(zip(('team_score_mse','margin_mae','total_mae'),values))
                       for key,values in [('elo',(100,10,15)),(R['id'],ridge),(H['id'],hgb)]}}


def test_point_gate_requires_improvement_and_preserves_both_error_guards():
    result=choose_validation(report(ridge=(98,10.3,14),hgb=(99.5,10,15)),[R,H])
    assert result['selectedPointConfig']['id']=='elo'
    assert not any(row['passesPointGate'] for row in result['candidateGates'])


def test_near_tie_prefers_simpler_ridge_but_material_hgb_gain_wins():
    assert choose_validation(report(),[R,H])['selectedPointConfig']==R
    assert choose_validation(report(hgb=(90,10,15)),[R,H])['selectedPointConfig']==H
    assert choose_validation(report(ridge=(95,10,15.31),hgb=(94,10,15)),[R,H])['selectedPointConfig']==H


def test_equal_development_loss_uses_declared_stronger_regularization():
    r10={'id':'ridge_a10','family':'ridge','params':{'alpha':10.0}}
    h10={'id':'hgb_l2_10','family':'hgb','params':{'l2_regularization':10.0}}
    assessment={'overall':{c['id']:{'team_score_mse':100} for c in [R,H,r10,h10]}}
    selected=choose_development(assessment,[r10,h10,R,H])
    assert selected=={'ridge':R,'hgb':H}
