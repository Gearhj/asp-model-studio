"""Metadata-gated ESPN season export adapter for reconstructed NBA research.

The 2026 cohort is fixed before final-score columns are requested. Neutral
regular games update history only; Cup finals provide dates but never scores.
"""
from collections import Counter
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re

import pandas as pd
import pyarrow.dataset as ds

from .authority import json_bytes, reference, verified_bytes
from .historical_source import EVIDENCE_CLASS

TEAM_IDENTITIES = {
    1: ('ATL','ATL','Atlanta Hawks'), 2: ('BOS','BOS','Boston Celtics'),
    3: ('NO','NOP','New Orleans Pelicans'), 4: ('CHI','CHI','Chicago Bulls'),
    5: ('CLE','CLE','Cleveland Cavaliers'), 6: ('DAL','DAL','Dallas Mavericks'),
    7: ('DEN','DEN','Denver Nuggets'), 8: ('DET','DET','Detroit Pistons'),
    9: ('GS','GSW','Golden State Warriors'), 10: ('HOU','HOU','Houston Rockets'),
    11: ('IND','IND','Indiana Pacers'), 12: ('LAC','LAC','LA Clippers'),
    13: ('LAL','LAL','Los Angeles Lakers'), 14: ('MIA','MIA','Miami Heat'),
    15: ('MIL','MIL','Milwaukee Bucks'), 16: ('MIN','MIN','Minnesota Timberwolves'),
    17: ('BKN','BRK','Brooklyn Nets'), 18: ('NY','NYK','New York Knicks'),
    19: ('ORL','ORL','Orlando Magic'), 20: ('PHI','PHI','Philadelphia 76ers'),
    21: ('PHX','PHO','Phoenix Suns'), 22: ('POR','POR','Portland Trail Blazers'),
    23: ('SAC','SAC','Sacramento Kings'), 24: ('SA','SAS','San Antonio Spurs'),
    25: ('OKC','OKC','Oklahoma City Thunder'), 26: ('UTAH','UTA','Utah Jazz'),
    27: ('WSH','WAS','Washington Wizards'), 28: ('TOR','TOR','Toronto Raptors'),
    29: ('MEM','MEM','Memphis Grizzlies'), 30: ('CHA','CHO','Charlotte Hornets'),
}
REGULAR_START = '2025-10-21'
REGULAR_END = '2026-04-12'
CUP_ID = 401809839
CUP_DATE = '2025-12-16'
SCHEDULE_REFERENCE = 'https://pr.nba.com/2025-26-nba-regular-season-schedule/'


def _team(row, side):
    identifier = int(row[f'{side}_id'])
    if identifier not in TEAM_IDENTITIES:
        raise ValueError('Unregistered NBA team identity')
    abbreviation, canonical, display = TEAM_IDENTITIES[identifier]
    if row[f'{side}_abbreviation'] != abbreviation or row[f'{side}_display_name'] != display:
        raise ValueError('NBA team ID, abbreviation and full name must all match')
    return canonical


def classify_current_metadata(frame: pd.DataFrame) -> dict:
    """Classify only already-projected metadata; no outcome columns accepted."""
    if any(c in frame.columns for c in ('home_score','away_score','home_winner','away_winner','game_json')):
        raise ValueError('Scope classification must receive metadata only')
    if frame.id.duplicated().any() or not (frame.id == frame.game_id).all():
        raise ValueError('Game IDs must be unique and agree across source ID fields')
    if set(frame.season) != {2026}:
        raise ValueError('This fixed current-season adapter admits only season-end2026')
    days = pd.to_datetime(frame['date'], utc=True).dt.tz_convert('America/New_York').dt.date.astype(str)
    if not (days == frame.game_date.astype(str)).all():
        raise ValueError('Source UTC schedule dates and recorded New York calendar dates differ')
    included, contexts, excluded, postponed = [], [], [], []
    for row in frame.sort_values(['game_date','id']).to_dict('records'):
        gid, day = int(row['id']), str(row['game_date'])
        reason = None
        if int(row['season_type']) == 3:
            reason = 'PLAYOFFS'
        elif int(row['season_type']) == 5:
            reason = 'PLAY_IN'
        elif int(row['season_type']) != 2:
            raise ValueError('Unregistered competition type')
        elif int(row['type_id']) == 4 and row['type_abbreviation'] == 'ALLSTAR':
            reason = 'ALL_STAR'
        elif not bool(row['status_type_completed']):
            if row['status_type_name'] != 'STATUS_POSTPONED':
                raise ValueError('Unexpected uncompleted regular-season disposition')
            reason = 'POSTPONED_ORIGINAL_ID'
            postponed.append(row)
        elif row['status_type_name'] != 'STATUS_FINAL':
            raise ValueError('Only source FINAL records can be admitted')
        if reason:
            excluded.append({'source_game_id': gid, 'game_date': day, 'reason': reason,
                             'source_status': row['status_type_name']})
            continue
        home, away = _team(row, 'home'), _team(row, 'away')
        if home == away or not (REGULAR_START <= day <= REGULAR_END):
            raise ValueError('Invalid regular-season matchup or calendar boundary')
        record = {'source_game_id': gid, 'game_id': f'nba-espn:game:{gid}',
                  'season_end': 2026, 'game_date': day,
                  'home_team_code': home, 'away_team_code': away,
                  'home_team_id': f'nba-neil:franchise:{home}',
                  'away_team_id': f'nba-neil:franchise:{away}',
                  'neutral_site': bool(row['neutral_site']),
                  'orientation': 'PUBLISHER_FOCAL_AXIS_NO_HOME_CLAIM' if row['neutral_site'] else 'SOURCE_HOME_AWAY',
                  'target_eligible': not bool(row['neutral_site'])}
        if int(row['type_id']) == 39 or row['type_abbreviation'] == 'CC':
            if gid != CUP_ID or day != CUP_DATE or {home,away} != {'NYK','SAS'} or not row['neutral_site']:
                raise ValueError('Cup final metadata does not match the explicitly admitted context')
            contexts.append({'game_id': record['game_id'], 'game_date': day, 'season_end': 2026,
                'team_ids': sorted([record['home_team_id'],record['away_team_id']]),
                'classification': 'NBA_CUP_FINAL_DATE_ONLY', 'source_game_id': gid})
            continue
        if int(row['type_id']) != 1 or row['type_abbreviation'] != 'STD':
            raise ValueError('Unexpected regular-season game type')
        included.append(record)
    if len(contexts) != 1:
        raise ValueError('One declared Cup-final date context is required')
    for item in postponed:
        match = re.search(r'Makeup date ([A-Za-z]{3}) (\d{1,2})', str(item['notes_headline']))
        if not match:
            raise ValueError('Postponed record lacks an explicit makeup-date note')
        day = datetime.strptime(f'2026 {match[1]} {match[2]}', '%Y %b %d').date().isoformat()
        h, a = _team(item, 'home'), _team(item, 'away')
        successors = [g for g in included if g['game_date']==day and g['home_team_code']==h and g['away_team_code']==a]
        if len(successors) != 1:
            raise ValueError('Postponement note does not resolve to one completed same-orientation makeup record')
        excluded_record = next(g for g in excluded if g['source_game_id']==int(item['id']))
        excluded_record.update({'makeup_source_game_id': successors[0]['source_game_id'],
            'makeup_date': day, 'relationship_basis': 'SOURCE_NOTE_DATE_AND_SAME_HOME_AWAY_PAIR',
            'identity_merge_claimed': False})
    keys = [(g['game_date'],*sorted([g['home_team_id'],g['away_team_id']])) for g in included]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate date/team-pair games cannot be silently resolved')
    counts = Counter(t for g in included for t in [g['home_team_code'],g['away_team_code']])
    if len(included)!=1230 or len(counts)!=30 or set(counts.values())!={82}:
        raise ValueError('Complete regular-season count must reconcile to 1230 games and82 per team')
    return {'schema':'nba-gen1-current-identity-cohort-v1', 'seasonEnd':2026,
        'evidenceClass':EVIDENCE_CLASS, 'regularSeasonStart':REGULAR_START,'regularSeasonEnd':REGULAR_END,
        'scopePrimarySource':SCHEDULE_REFERENCE,'sourceRows':len(frame),'admittedGames':included,
        'contextOnlyEvents':contexts,'excludedIdentities':excluded,
        'exclusionCounts':dict(sorted(Counter(g['reason'] for g in excluded).items())),
        'orientedTargetGames':sum(g['target_eligible'] for g in included),
        'neutralHistoryOnlyGames':sum(g['neutral_site'] for g in included),
        'gamesPerTeam':dict(sorted(counts.items())),
        'teamMapping':{str(k):{'sourceAbbreviation':v[0],'canonicalCode':v[1],'displayName':v[2]} for k,v in TEAM_IDENTITIES.items()},
        'outcomeColumnsLoaded':False,'comparativePerformanceExamined':False}


def normalize_current_history(cohort_path: Path, model_freeze_path: Path):
    """Load only declared regular-game scores after a model pre-access freeze."""
    cohort = json.loads(cohort_path.read_bytes())
    if cohort.get('outcomeColumnsLoaded') is not False or cohort.get('comparativePerformanceExamined') is not False:
        raise ValueError('Require an unassessed metadata-only identity cohort')
    verified_bytes(cohort['source'])
    verified_bytes(cohort['metadata'])
    verified_bytes(cohort['declaration'])
    verified_bytes(cohort['adapter'])
    if cohort['adapter']['sha256'] != reference(Path(__file__))['sha256']:
        raise ValueError('Adapter changed after cohort lock')
    freeze = json.loads(model_freeze_path.read_bytes())
    if freeze.get('trainingThroughSeasonEnd') != 2025 or freeze.get('outcomes2026Accessed') is not False:
        raise ValueError('Models trained only through2025 must be frozen before2026 outcomes')
    records = cohort['admittedGames']
    ids = [g['source_game_id'] for g in records]
    if len(ids)!=len(set(ids)) or len(ids)!=1230:
        raise ValueError('Declared identity cohort is invalid')
    # Predicate/filter is fixed from metadata, before requesting outcome columns.
    # No excluded Cup, All-Star, postponed, play-in or playoff score is returned.
    source = ds.dataset(cohort['source']['path'],format='parquet')
    score_rows = source.to_table(columns=['id','home_score','away_score'],filter=ds.field('id').isin(ids)).to_pandas()
    if score_rows.id.duplicated().any() or set(score_rows.id)!=set(ids):
        raise ValueError('Eligible final rows fail the frozen identity reconciliation')
    lookup = score_rows.set_index('id')
    normalized=[]
    for record in records:
        row=dict(record)
        for side in ('home','away'):
            value=lookup.loc[record['source_game_id'],f'{side}_score']
            if pd.isna(value) or float(value)<0 or not float(value).is_integer():
                raise ValueError('A final score must be a nonnegative integer')
            row[f'{side}_score']=int(value)
        if row['home_score']==row['away_score']:
            raise ValueError('NBA final scores cannot be tied')
        row.update({'competition':'NBA_REGULAR_SEASON','evidence_class':EVIDENCE_CLASS,
            'record_classification':'SOURCE_FINAL_FULL_GAME_INCLUDING_OVERTIME',
            'source_row_numbers':str(row['source_game_id'])})
        normalized.append(row)
    normalized.sort(key=lambda g:(g['game_date'],g['game_id']))
    report={'schema':'nba-gen1-current-history-reconciliation-v1','evidenceClass':EVIDENCE_CLASS,
        'source':cohort['source'],'cohort':reference(cohort_path),'modelPreAccessFreeze':reference(model_freeze_path),
        'admittedGames':len(normalized),'orientedTargetGames':cohort['orientedTargetGames'],
        'neutralHistoryOnlyGames':cohort['neutralHistoryOnlyGames'],
        'contextOnlyEvents':cohort['contextOnlyEvents'],'exclusionCounts':cohort['exclusionCounts'],
        'originalGamePublicationVintages':None,'outcomeConversion':'Eligible regular-season IDs only; excluded outcome rows never returned to adapter',
        'teamMapping':cohort['teamMapping'],'currentScoreSource':'Finalized ESPN-derived records acquired now; CategoryA, not prospective'}
    return pd.DataFrame(normalized),report
