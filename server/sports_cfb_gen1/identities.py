"""Season-effective CFBD identity names; IDs, never fuzzy school matching."""
from .lifecycle import utc


def normalized(name):
    return ' '.join(str(name).split()).casefold()


def build_aliases(teams, season, captured_at, source):
    result=[]
    seen=set()
    for row in teams:
        ident=int(row['id'])
        if ident<=0 or ident in seen:
            raise ValueError('Duplicate/invalid CFBD school ID')
        seen.add(ident)
        names=[row['school'],*(row.get('alternateNames') or [])]
        for name in sorted(set(n for n in names if n)):
            result.append({'source':'CFBD','sourceTeamId':ident,'school':row['school'],'alias':name,
                'validFromUtc':f'{season}-07-01T00:00:00+00:00',
                'validUntilUtc':f'{season+1}-07-01T00:00:00+00:00','knownAtUtc':captured_at,
                'scope':'SOURCE_YEAR_FBS_MEMBERSHIP_NOT_A_LEGAL_RENAME_DATE','sourceEvidence':source})
    return {'schema':'CFB_EFFECTIVE_SCHOOL_ALIASES_V1','season':season,'aliases':result,
            'newSchoolPolicy':'No merge by name. An unseen ID/name requires a reviewed successor mapping.'}


def resolve(mapping, ident, name, kickoff, cutoff):
    rows=[x for x in mapping['aliases'] if normalized(x['alias'])==normalized(name)
          and utc(x['validFromUtc'])<=utc(kickoff)<utc(x['validUntilUtc'])
          and utc(x['knownAtUtc'])<=utc(cutoff)]
    ids={x['sourceTeamId'] for x in rows}
    if ids!={int(ident)}:
        raise ValueError('UNKNOWN_OR_AMBIGUOUS_SCHOOL_ALIAS:'+str(ident))
    return rows[0]['school']
