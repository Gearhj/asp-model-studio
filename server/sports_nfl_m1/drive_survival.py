"""Bounded, research-only drive hazard challenger. Operational modules unchanged.

One index is an ordinary live snap/kick decision OR a supported presnap penalty
transition. Administrative records are retained in the audit, never counted as
snaps. END_OF_HALF_OR_GAME includes post-snap runoff to an observed half end.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .play_evidence import classify_play, SOURCE_COLUMNS
from .play_engine import apply_play, model_state, remaining, other, assert_state

CAUSES = ('CONTINUE', 'TOUCHDOWN', 'FIELD_GOAL_MADE', 'FIELD_GOAL_MISSED_OR_BLOCKED',
          'PUNT', 'OFFENSIVE_TURNOVER', 'TURNOVER_ON_DOWNS', 'SAFETY', 'END_OF_HALF_OR_GAME')
FEATURES = ('down1', 'down2', 'down3', 'down4', 'distance', 'log_distance', 'yard',
            'red_zone', 'goal_to_go', 'half_seconds', 'two_minute', 'final_30',
            'quarter4', 'overtime', 'score', 'leading', 'trailing', 'home',
            'drive_start_yard', 'prior_snaps', 'elapsed', 'recent_pass_fraction',
            'fourth_yard', 'fourth_distance', 'late_score')
EXTRA_COLUMNS = ('total_home_score total_away_score posteam_score_post defteam_score_post '
                 'fixed_drive_result drive_end_transition drive_game_clock_end '
                 'drive_play_id_started drive_play_id_ended game_seconds_remaining td_team '
                 'quarter_end timeout fourth_down_failed fourth_down_converted location order_sequence').split()
READ_COLUMNS = list(dict.fromkeys(SOURCE_COLUMNS + EXTRA_COLUMNS))
LIVE = {'run', 'pass', 'punt', 'field_goal', 'qb_kneel', 'qb_spike'}
SUPPORTED_KINDS = {'RUSH', 'QB_SNEAK', 'QB_SCRAMBLE', 'PASS_COMPLETE', 'PASS_INCOMPLETE',
                   'SACK', 'INTERCEPTION', 'PUNT', 'FIELD_GOAL', 'KNEEL', 'SPIKE', 'PENALTY'}


def seed_for(*parts: Any) -> int:
    return int.from_bytes(hashlib.sha256('|'.join(map(str, parts)).encode()).digest()[:4], 'little')


def number(x: Any, default=float('nan')) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def historical_cause(r: dict) -> int:
    # Priority makes return TDs an offensive turnover, never an offensive TD.
    if number(r.get('interception')) == 1 or number(r.get('fumble_lost')) == 1:
        return 5
    if number(r.get('safety')) == 1: return 7
    if number(r.get('touchdown')) == 1 and r.get('td_team') == r.get('posteam'): return 1
    if number(r.get('field_goal_attempt')) == 1:
        return 2 if r.get('field_goal_result') == 'made' else 3
    if number(r.get('punt_attempt')) == 1: return 4
    if number(r.get('fourth_down_failed')) == 1: return 6
    return 0


def reconstruct(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Whole-drive eligibility; source drive summaries are labels/checks ONLY."""
    if not frame.season.isin(range(2018, 2025)).all(): raise ValueError('protected season')
    risk, drives, games = [], [], []
    exclusions, semantics = Counter(), Counter()
    for game_id, g in frame.groupby('game_id', sort=False):
        # nflverse play IDs can be assigned after correction; order_sequence is
        # the retained event order (e.g. 2024_01_CAR_NO play1672 precedes1613).
        if 'order_sequence' not in g or g.order_sequence.isna().any():
            raise ValueError('authentic event ordering unavailable')
        g = g.sort_values(['order_sequence','play_id'], kind='stable')
        first = g.iloc[0]
        duplicate = bool(g.play_id.duplicated().any())
        score = g[['total_home_score', 'total_away_score']].ffill().fillna(0).to_numpy(float)
        changes = np.diff(np.vstack(([0., 0.], score)), axis=0)
        final = np.array([first.home_score, first.away_score], float)
        score_ok = bool(np.array_equal(score[-1], final) and (changes >= 0).all())
        games.append(dict(game_id=game_id, season=int(first.season), date=str(first.game_date),
                          week=int(first.week), season_type=first.season_type,
                          home_team=first.home_team, away_team=first.away_team,
                          home_score=int(final[0]), away_score=int(final[1]),
                          score_reconciled=score_ok, duplicate_play=duplicate,
                          full_score_delta_home=float(changes[:, 0].sum()),
                          full_score_delta_away=float(changes[:, 1].sum())))
        # Every raw score increment remains attributable even for excluded drives.
        g = g.copy(); g['delta_home'] = changes[:, 0]; g['delta_away'] = changes[:, 1]
        for did, d in g.groupby('fixed_drive', dropna=False, sort=False):
            raw = d.to_dict('records'); rows = []
            reason = None
            if not score_ok: reason = 'GAME_SCORE_NOT_RECONCILED'
            if duplicate: reason = 'DUPLICATE_GAME_PLAY_ID'
            if not np.isfinite(number(did)): reason = 'MISSING_DRIVE_ID'
            starts=d.drive_play_id_started.dropna().unique();ends=d.drive_play_id_ended.dropna().unique()
            if not len(starts) or not len(ends): reason=reason or 'MISSING_DRIVE_ENDPOINT_METADATA'
            elif not (set(starts).issubset(set(d.play_id)) and set(ends).issubset(set(d.play_id))):
                reason=reason or 'TRUNCATED_DRIVE_ENDPOINT_NOT_RETAINED'
            for r in raw:
                semantics[str(r.get('play_type'))] += 1
                if number(r.get('play_deleted')) == 1:
                    semantics['deleted_records_retained_in_audit'] += 1
                    continue
                if number(r.get('extra_point_attempt')) == 1 or number(r.get('two_point_attempt')) == 1:
                    continue  # Tries belong to scoreboard accounting, not drive survival.
                if r.get('play_type') not in LIVE and r.get('play_type') != 'no_play': continue
                kind, why = classify_play(r)
                # Timeouts, replay markers, two-minute warnings have no snap.
                if r.get('play_type') == 'no_play' and number(r.get('penalty')) != 1:
                    semantics['administrative_no_play'] += 1
                    continue
                if kind not in SUPPORTED_KINDS:
                    reason = reason or ('UNSUPPORTED_' + str(why))
                    continue
                if r.get('posteam') not in (first.home_team, first.away_team):
                    reason = reason or 'UNKNOWN_POSSESSION'; continue
                if not all(np.isfinite(number(r.get(k))) for k in
                           ('down', 'ydstogo', 'yardline_100', 'qtr', 'quarter_seconds_remaining',
                            'half_seconds_remaining', 'score_differential')):
                    reason = reason or 'MISSING_PREPLAY_STATE'; continue
                if number(r['quarter_seconds_remaining'])<=0:
                    reason=reason or 'UNTIMED_OR_ZERO_CLOCK_DECISION_UNSUPPORTED';continue
                r['kind'] = kind; rows.append(r)
            if not rows: reason = reason or 'NO_SUPPORTED_DRIVE_DECISIONS'
            transitions = set(str(x) for x in d.drive_end_transition.dropna().unique())
            end_half = bool(transitions & {'END_HALF', 'END_GAME'})
            cs = [historical_cause(r) for r in rows]
            if rows and cs[-1] == 0 and end_half:
                cs[-1] = 8
            if rows and sum(c != 0 for c in cs) != 1: reason = reason or 'MISSING_OR_MULTIPLE_TERMINALS'
            if rows and cs[-1] == 0: reason = reason or 'TERMINAL_NOT_LAST_DECISION'
            if rows and len({r['posteam'] for r in rows}) != 1: reason = reason or 'POSSESSION_CHANGED_WITHIN_DRIVE'
            if rows:
                expected = {1: {'TOUCHDOWN'}, 2: {'FIELD_GOAL'}, 3: {'MISSED_FG','BLOCKED_FG'},
                            4: {'PUNT'}, 5: {'INTERCEPTION','FUMBLE'}, 6: {'DOWNS'},
                            7: {'SAFETY'}, 8: {'END_HALF','END_GAME'}}.get(cs[-1], set())
                if not (transitions & expected): reason = reason or 'SOURCE_TERMINAL_DISAGREEMENT'
                h = [(r['qtr'] > 2, r['qtr'] > 4) for r in rows]
                if len(set(h)) > 1: reason = reason or 'DRIVE_CROSSES_HALF_OR_OVERTIME'
                if np.any(np.diff([r['half_seconds_remaining'] for r in rows])>0):
                    reason=reason or 'AMBIGUOUS_WITHIN_DRIVE_CLOCK_REVISION'
            key = f'{game_id}:{did:g}' if np.isfinite(number(did)) else f'{game_id}:missing'
            info = dict(drive_key=key, game_id=game_id, season=int(first.season), week=int(first.week),
                        date=str(first.game_date), season_type=first.season_type,
                        eligible=reason is None, exclusion=reason, raw_records=len(d),
                        source_terminal='|'.join(sorted(transitions)),
                        home_points=float(d.delta_home.sum()), away_points=float(d.delta_away.sum()))
            if reason:
                exclusions[reason] += 1; drives.append(info); continue
            start = rows[0]; start_clock=float(start['half_seconds_remaining'])
            endtext = d.drive_game_clock_end.dropna()
            end_clock = None
            if len(endtext):
                try:
                    mm, ss = str(endtext.iloc[-1]).split(':'); end_clock = int(mm)*60+int(ss)
                    if rows[-1]['qtr'] in (1,3): end_clock += 900
                except ValueError: pass
            if end_half: end_clock = 0.
            elapsed = start_clock-end_clock if end_clock is not None else None
            if elapsed is not None and elapsed < 0:
                info.update(eligible=False, exclusion='NEGATIVE_DRIVE_DURATION')
                exclusions['NEGATIVE_DRIVE_DURATION'] += 1; drives.append(info); continue
            pre_snaps=0; recent=[]; local=[]
            for i,(r,c) in enumerate(zip(rows,cs)):
                s = dict(phase='SCRIMMAGE', offense_team=r['posteam'], defense_team=r['defteam'],
                         season=int(first.season), quarter=int(r['qtr']),
                         quarter_seconds=float(r['quarter_seconds_remaining']),
                         half_seconds=float(r['half_seconds_remaining']), down=int(r['down']),
                         yards_to_go=float(r['ydstogo']), yardline_100=float(r['yardline_100']),
                         score_differential=float(r['score_differential']),
                         home=int(r['posteam']==first.home_team), drive_start_yard=float(start['yardline_100']),
                         prior_snaps=pre_snaps, elapsed=start_clock-float(r['half_seconds_remaining']),
                         recent_pass_fraction=float(np.mean(recent[-3:])) if recent else 0.)
                local.append(dict(**s, drive_key=key, game_id=game_id, play_id=float(r['play_id']),
                                  index=i, cause=c, kind=r['kind'], date=str(first.game_date),
                                  week=int(first.week), season_type=first.season_type,
                                  home_team=first.home_team, away_team=first.away_team,
                                  remaining_decisions=len(rows)-i, final_cause=cs[-1],
                                  remaining_seconds=None if elapsed is None else elapsed-s['elapsed']))
                if r['kind']!='PENALTY':
                    pre_snaps += 1; recent.append(r['kind'] in {'PASS_COMPLETE','PASS_INCOMPLETE','INTERCEPTION','SACK','QB_SCRAMBLE','SPIKE'})
            risk.extend(local)
            offhome=start['posteam']==first.home_team
            info.update(terminal_cause=CAUSES[cs[-1]], decisions=len(rows), snaps=pre_snaps,
                        offense_team=start['posteam'], home=offhome, start_yard=float(start['yardline_100']),
                        start_half_seconds=start_clock, start_quarter=int(start['qtr']),
                        start_score=float(start['score_differential']), duration_seconds=elapsed,
                        offensive_points=(info['home_points'] if offhome else info['away_points']),
                        terminal_points=6 if cs[-1]==1 else 3 if cs[-1]==2 else -2 if cs[-1]==7 else 0)
            drives.append(info)
    r,d,g = pd.DataFrame(risk),pd.DataFrame(drives),pd.DataFrame(games)
    if len(r):
        assert r.groupby('drive_key').cause.apply(lambda x:int((x!=0).sum())).eq(1).all()
        assert not r.duplicated(['game_id','play_id']).any()
    return r,d,g,dict(rawRows=len(frame), gameCount=len(g), driveCount=len(d), supportedDrives=int(d.eligible.sum()),
                      riskRows=len(r), exclusions=dict(exclusions), rawRecordSemantics=dict(semantics),
                      gameScoreReconciliationFailures=int((~g.score_reconciled).sum()),
                      terminalCounts=(r.loc[r.cause.ne(0),'cause'].map(lambda i:CAUSES[i]).value_counts().to_dict() if len(r) else {}),
                      administrativeRecordsAreNotSnaps=True, unsupportedDrivesAreWholeDriveExcluded=True)


def features(s: dict) -> np.ndarray:
    down=int(s['down']); yard=float(s['yardline_100']); dist=float(s['yards_to_go'])
    half=float(s['half_seconds']); score=float(s['score_differential'])
    return np.asarray([*(int(down==i) for i in range(1,5)), dist, np.log1p(max(0,dist)), yard,
                       int(yard<=20), int(dist>=yard), half, int(half<=120), int(half<=30),
                       int(s['quarter']==4), int(s['quarter']>4), score, int(score>0), int(score<0),
                       s.get('home',0), s.get('drive_start_yard',yard), s.get('prior_snaps',0),
                       s.get('elapsed',0), s.get('recent_pass_fraction',0),
                       yard*(down==4), dist*(down==4), score*(half<=120)],float)


@dataclass
class Hazard:
    scaler: Any
    model: Any
    through_season: int
    lower: np.ndarray
    upper: np.ndarray
    training_rows: int

    def predict(self, s: dict) -> np.ndarray:
        x=features(s)
        z=((x-self.scaler.mean_)/self.scaler.scale_)@self.model.coef_.T+self.model.intercept_
        p=np.exp(z-z.max()); p/=p.sum()
        result=np.zeros(len(CAUSES));result[self.model.classes_.astype(int)]=p
        return result

    def supported(self,s:dict) -> bool:
        x=features(s)
        # Overtime is deliberately exact fallback: distinct tactical/rule support.
        return (int(s['season'])>self.through_season and int(s['quarter'])<=4 and
                np.isfinite(x).all() and np.all(x>=self.lower) and np.all(x<=self.upper))


def fit_hazard(rows:pd.DataFrame, through:int) -> Hazard:
    if not rows.season.le(through).all() or through>2023: raise ValueError('future training row')
    train=rows[rows.quarter.le(4)]
    x=np.stack([features(s) for s in train.to_dict('records')]); y=train.cause.to_numpy(int)
    scaler=StandardScaler().fit(x)
    model=LogisticRegression(C=.1, max_iter=600, solver='lbfgs', tol=1e-5)
    model.fit(scaler.transform(x), y)
    return Hazard(scaler,model,through,x.min(0),x.max(0),len(train))


def legal_state(s:dict) -> dict:
    # Translation only; baseline law depends on score difference, not score level.
    diff=int(s['score_differential']); off='HOME' if s.get('home',0) else 'AWAY'
    h=max(diff,0) if off=='HOME' else max(-diff,0)
    a=max(-diff,0) if off=='HOME' else max(diff,0)
    state=dict(possession=off, quarter=int(s['quarter']), clockSeconds=float(s['quarter_seconds']),
               down=int(s['down']), distance=float(s['yards_to_go']), yardline100=float(s['yardline_100']),
               homeScore=h, awayScore=a, phase='SCRIMMAGE')
    state['gameSecondsRemaining']=remaining(state)
    return state


def sample_cause(s:dict, sample:dict) -> int:
    b=legal_state(s); a,o=apply_play(b,sample,season=int(s['season']))
    if o['turnover']: return 5
    if o['scoringType']=='SAFETY': return 7
    if o['scoringType']=='TD': return 1
    if sample['type']=='FIELD_GOAL': return 2 if o['scoringType']=='FG' else 3
    if sample['type']=='PUNT': return 4
    if o['turnoverDowns']: return 6
    if a['clockSeconds']==0 and b['quarter'] in (2,4,5): return 8
    return 0


@dataclass
class SurvivalAdapter:
    """Finite-proposal 25% hazard branch; each accepted donor remains unmodified.

    On the hazard branch, 16 baseline proposals define actual feasible causes.
    Learned hazards are projected to those causes and select one original donor.
    The other 75% uses the original sampler directly. This is NOT an assertion
    that the resulting marginal law equals the raw classifier probabilities.
    """
    baseline: Any
    hazard: Hazard
    weight: float=.25
    proposals: int=16
    home_team: str | None=None
    counts: Counter=field(default_factory=Counter)
    _last: dict | None=None

    def reset(self): self._last=None

    def augment(self,s:dict) -> dict:
        s=dict(s)
        last=self._last
        new=(last is None or last['offense']!=s['offense_team'] or
             last['ended'] or (last['quarter']==2 and s['quarter']==3))
        if s['phase']!='SCRIMMAGE':
            self._last=None;return s
        if new:
            s.update(drive_start_yard=s['yardline_100'],prior_snaps=0,elapsed=0.,recent_pass_fraction=0.)
            history=[]; start=float(s['half_seconds'])
        else:
            history=last['history'];start=last['start']
            s.update(drive_start_yard=last['yard'],prior_snaps=last['snaps'],
                     elapsed=max(0.,start-float(s['half_seconds'])),recent_pass_fraction=float(np.mean(history[-3:])) if history else 0.)
        if 'home' not in s:
            if self.home_team is None: raise ValueError('home identity required by survival adapter')
            s['home']=int(s['offense_team']==self.home_team)
        self._pending=(history,start,s)
        return s

    def sample(self,state:dict,rng:np.random.Generator,scenario='BASE') -> dict:
        if self.weight==0 or state['phase']!='SCRIMMAGE':
            if state['phase']!='SCRIMMAGE':self._last=None
            self.counts['exact_baseline_calls']+=1
            return self.baseline.sample(state,rng,scenario)
        s=self.augment(state)
        if not self.hazard.supported(s):
            result=self.baseline.sample(state,rng,scenario);self.counts['unsupported_exact_fallback']+=1
        elif rng.random()>=self.weight:
            result=self.baseline.sample(state,rng,scenario);self.counts['baseline_mixture_branch']+=1
        else:
            pool=[self.baseline.sample(state,rng,scenario) for _ in range(self.proposals)]
            causes=np.array([sample_cause(s,p) for p in pool],int)
            counts=np.bincount(causes,minlength=len(CAUSES));p=self.hazard.predict(s)
            w=np.where(counts>0,p,0.); self.counts['missing_cause_probability_millionths']+=int(round((1-w.sum())*1e6))
            if w.sum()==0:
                result=pool[0];self.counts['zero_supported_hazard_pool']+=1
            else:
                w=w[causes]/counts[causes];w/=w.sum()
                result=pool[min(int(np.searchsorted(np.cumsum(w),rng.random())),len(pool)-1)]
            self.counts['hazard_branch']+=1
        history,start,s=self._pending
        if result['type']!='PENALTY':history=history+[result['type'] in {'PASS_COMPLETE','PASS_INCOMPLETE','INTERCEPTION','SACK','QB_SCRAMBLE','SPIKE'}]
        self._last=dict(offense=s['offense_team'],ended=sample_cause(s,result)!=0,
                        quarter=s['quarter'],history=history,start=start,yard=s['drive_start_yard'],
                        snaps=s['prior_snaps']+(result['type']!='PENALTY'))
        return result


def drive_rollout(model:Any,s:dict,seed:int) -> dict:
    state=legal_state(s);initial=dict(state); rng=np.random.default_rng(seed)
    decisions=snaps=0; seconds=0.; cause=0;points=0
    if isinstance(model,SurvivalAdapter):
        if s.get('prior_snaps',0)>0 and 'recent_pass_flags' not in s:
            raise ValueError('midpoint rollout requires retained preceding play types')
        model.reset();model._last=dict(offense=s['offense_team'],ended=False,quarter=s['quarter'],
            history=list(s.get('recent_pass_flags',[])),start=s['half_seconds']+s.get('elapsed',0),
            yard=s.get('drive_start_yard',s['yardline_100']),snaps=s.get('prior_snaps',0))
    while not cause:
        if decisions>150: raise ValueError('drive did not end; no truncation fallback')
        if state['clockSeconds']<=0:
            if state['quarter'] in (1,3):
                state.update(quarter=state['quarter']+1,clockSeconds=900.);state['gameSecondsRemaining']=remaining(state)
            else: cause=8;break
        ms=model_state(state,s['home_team'],s['away_team'],s['season']);ms['home']=int(state['possession']=='HOME')
        sample=model.sample(ms,rng)
        cause=sample_cause(ms,sample);after,out=apply_play(state,sample,season=s['season'])
        decisions+=1;snaps+=sample['type']!='PENALTY';seconds+=out['seconds']
        points+=(out['homePointsAdded']-out['awayPointsAdded'])*(1 if initial['possession']=='HOME' else -1)
        state=after;assert_state(state)
    return dict(cause=cause,decisions=decisions,snaps=snaps,seconds=seconds,points=points)
