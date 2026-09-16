"""Market-line masses from an existing, complete original V18 total-run PMF.

All probabilities are fractions. This helper does not infer, simulate, normalize
an invalid PMF, round scores, truncate tails, fetch quotes, or select wagers.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import math

UNITS = 'FRACTION_0_TO_1'

def validated_pmf(rows, sample_count):
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count <= 0:
        raise ValueError('Original positive integer sample count required')
    seen = set()
    bins = []
    for row in rows:
        value, p = row['value'], row['probability']
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value in seen:
            raise ValueError('PMF values must be unique nonnegative integers')
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError('PMF probabilities must be fractions from 0 to 1')
        count = round(p * sample_count)
        if abs(p * sample_count - count) > 1e-8:
            raise ValueError('PMF mass is not consistent with original sample count')
        bins.append((value, count, float(p)))
        seen.add(value)
    if not bins or sum(x[1] for x in bins) != sample_count or abs(math.fsum(x[2] for x in bins)-1) > 1e-12:
        raise ValueError('Complete PMF count and mass must reconcile; no renormalization')
    return sorted(bins)

def line_probabilities(rows, sample_count, line, decimal_odds=None):
    """Query both sides of an illustrative or caller-supplied market line.

    Optional decimal_odds is {'over': number, 'under': number}; no quote source
    or selection authority is implied. Never use conditional non-push win
    probability in the raw expected-net-return formula.
    """
    if isinstance(line, bool):
        raise ValueError('An integer or half-run line is required')
    try:
        threshold = Decimal(str(line))
    except InvalidOperation as exc:
        raise ValueError('Invalid total-run line') from exc
    if not threshold.is_finite() or threshold < 0 or threshold * 2 != (threshold * 2).to_integral_value():
        raise ValueError('Only nonnegative integer and half-run lines are supported')
    bins = validated_pmf(rows, sample_count)
    above = sum(count for value, count, _ in bins if value > threshold)
    equal = sum(count for value, count, _ in bins if value == threshold)
    below = sum(count for value, count, _ in bins if value < threshold)
    result = {'line':float(threshold),'probabilityUnits':UNITS,'sampleCount':sample_count,
              'totalDefinition':'ORIGINAL_PAIRED_AWAY_PLUS_HOME_FULL_GAME_INCLUDING_EXTRA_INNINGS'}
    prices = decimal_odds or {}
    if set(prices) - {'over', 'under'}:
        raise ValueError('Price keys must be over or under')
    for side, wins, losses in [('over', above, below), ('under', below, above)]:
        p_win, p_loss, p_push = wins/sample_count, losses/sample_count, equal/sample_count
        item = {'pWin':p_win,'pPush':p_push,'pLoss':p_loss,
                'winCount':wins,'pushCount':equal,'lossCount':losses,
                'fairDecimalOdds':1+p_loss/p_win if p_win > 0 else None}
        if p_win == 0:
            item['fairOddsUnavailableReason'] = 'ZERO_WIN_PROBABILITY'
        if side in prices:
            odds = prices[side]
            if isinstance(odds, bool) or not isinstance(odds, (int, float)) or not math.isfinite(odds) or odds <= 1:
                raise ValueError('Decimal odds must be finite and greater than one')
            item.update(decimalOdds=odds, expectedNetReturnPerUnitStake=p_win*(odds-1)-p_loss)
        result[side] = item
    return result

def focused_checks():
    rows = [{'value':7,'probability':.2},{'value':8,'probability':.3},{'value':9,'probability':.5}]
    integer = line_probabilities(rows, 10, 8, {'over':2.1,'under':4.0})
    half = line_probabilities(rows, 10, '8.5')
    checks = {'integerPush':integer['over']['pPush'] == integer['under']['pPush'] == .3,
        'reverseWinLoss':integer['over']['pWin'] == integer['under']['pLoss'] == .5 and integer['over']['pLoss'] == integer['under']['pWin'] == .2,
        'halfRunZeroPush':half['over']['pPush'] == half['under']['pPush'] == 0,
        'halfRunWinLoss':half['over']['pWin'] == half['over']['pLoss'] == .5,
        'integerMass':math.fsum(integer['over'][k] for k in ('pWin','pPush','pLoss')) == 1,
        'netReturn':math.isclose(integer['over']['expectedNetReturnPerUnitStake'], .35),
        'pushAwareFairOdds':math.isclose(integer['over']['fairDecimalOdds'],1.4),
        'zeroWinFairOdds':line_probabilities(rows,10,99)['over']['fairDecimalOdds'] is None,
        'tailKept':line_probabilities([{'value':0,'probability':.5},{'value':100,'probability':.5}],10,99.5)['over']['pWin'] == .5}
    invalid = [('percentUnits',[{'value':8,'probability':100}],10,8),
        ('quarterLine',rows,10,8.25),('missingMass',rows[:-1],10,8),
        ('duplicateBins',rows+rows,10,8),('nonIntegerCounts',rows,3,8)]
    for name, bad_rows, count, line in invalid:
        try:
            line_probabilities(bad_rows,count,line)
        except ValueError:
            checks[name+'Rejected'] = True
        else:
            checks[name+'Rejected'] = False
    assert all(checks.values()), checks
    return {'schemaVersion':'MLB_V18_TOTALS_LINE_FOCUSED_CHECKS_V1','data':'SYNTHETIC_ONLY',
            'allPassed':True,'checks':checks,'newRandomDraws':0}

if __name__ == '__main__':
    import json
    print(json.dumps(focused_checks()))
