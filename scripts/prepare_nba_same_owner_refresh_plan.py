"""Freeze an exact proposal from retained rights and schema; zero HTTP calls."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_nba_gen1.authority import reference, verified_bytes
from server.sports_nba_gen1.production import canonical_bytes, digest
from server.sports_nba_gen1.slate_inputs import META
from server.sports_nba_gen1.slate_lifecycle import immutable, read_ref
from server.sports_nba_gen1.slate_refresh import URL, schema_description


def build(root):
    original = root/'outputs/nba-gen1-long-gap-v1'
    capture_ref = reference(original/'future-schedule-capture.json')
    capture = read_ref(capture_ref)
    schema = schema_description(verified_bytes(capture['source']))
    return {'schema':'NBA_SAME_OWNER_REFRESH_PLAN_V1', 'authority':'PROPOSAL_ONLY_NOT_AUTHORIZED',
        'owner':'ASP NBA Forecast Publisher', 'networkEnabledByDefault':False,
        'validFromUtc':'2026-10-13T18:00:00+00:00', 'validUntilUtc':'2027-04-19T04:00:00+00:00',
        'assets':[{'name':'nba_schedule_2027.parquet','url':URL,'method':'GET','parameters':{},
                   'seasonEnd':2027,'purpose':'Schedule, status and full-game final scores for unchanged score/date features'}],
        'permittedTransportRedirects':[
            {'host':'release-assets.githubusercontent.com','pathPrefix':'/github-production-release-asset/'},
            {'host':'objects.githubusercontent.com','pathPrefix':'/github-production-release-asset-2e65be/'}],
        'redirectRules':'Only Location from preceding allowed request; HTTPS; no credentials; at most 3 redirects. Signed queries transport-only, never retained. No other API or discovery URLs.',
        'seasonCoverage':{'newCapture':'2026-27 regular season only; playoffs/preseason excluded',
                          'baseHistory':'Frozen admitted history through completed 2025-26; not reacquired'},
        'expectedPhysicalSchema':schema, 'schemaFingerprint':digest(schema),
        'admittedFields':META+['home_score','away_score'],
        'fieldUse':'Identity/status read first; scores only for metadata-selected regular-season FINAL records. Cup championship date-only context. No boxes, odds, injuries or player inputs.',
        'maximumCaptureAttemptsPerInvocation':1,'maximumHttpRequestsPerInvocation':4,
        'maximumCaptureAttemptsPerUtcDay':8,'maximumHttpRequestsPerUtcDay':32,
        'maximumResponseBytesPerInvocation':16*1024**2,'maximumResponseBytesPerUtcDay':128*1024**2,
        'maximumRetainedStorageBytes':5*1024**3,'minimumAttemptSpacingMinutes':60,
        'retryCount':0,'timeoutSecondsPerHttpRequest':45,'costUsd':0,'credentialsRequired':False,
        'conditionalRequests':{'headers':['If-None-Match','If-Modified-Since'],
            'status304':'Retain prior object reference and original acquisition clock; new immutable actual-revalidation receipt, zero duplicate raw bytes.',
            'status200SameHash':'Reuse original object and acquisition clock; actual revalidation recorded separately.',
            'status200Changed':'New physical object and revision lineage; admit whole snapshot atomically before publication.'},
        'cadence':{'ownerTickMinutes':15,'timezone':'America/New_York',
            'preseasonOpening':'First refresh T-7 days minus 60 minutes before earliest admitted regular tipoff; no earlier calls.',
            'daily':'First owner tick at/after 10:00 America/New_York; one successful validation satisfies that day.',
            'publicationLead':'Revalidate between 60 minutes before each T-7d/T-24h/T-6h/T-1h checkpoint and checkpoint if no validation since lead start.',
            'freshness':'Due games: refresh at 23h age; final hour at 90m age. Global minimum spacing and ceilings apply.',
            'postFinal':'First check at/after scheduled tipoff+4h (not assumed FINAL); unresolved status checks at >=2h age for at most 48h; accept only source FINAL.',
            'corrections':'Daily/status checks discover content changes; rebuild current-season history from complete snapshot with predecessor lineage; no refit.',
            'notDue':'Zero network intent; no download on ordinary 15-minute ticks.',
            'sourceCadenceQualification':'No published update SLA established by retained evidence. Cadence is a bounded polling policy, not a claim of hourly upstream updates.'},
        'observedCadenceEvidence':{'capture':capture_ref,
            'retainedReleaseMetadata':reference(original/'source-review/schedules-release.json'),
            'sourceLastModified':capture['responseHeaders'].get('Last-Modified'),
            'originalCaptureAtUtc':capture['capturedAtUtc'],'retainedAssetBytes':capture['source']['bytes']},
        'freshness':{'maximumScheduleValidationAgeHours':24,'maximumHistoryValidationAgeHours':24,
            'finalCheckpointMaximumAgeHours':2,'noElapsedUnresolvedGames':True,
            'meaning':'304 validates server version only. Missing finals block admission; original acquisition clocks never changed.'},
        'rightsEvidence':[reference(original/'source-review/admission.json'), reference(original/'source-review/hoopr-LICENSE.md')],
        'attribution':'SportsDataverse / hoopR, ESPN-derived records. CC BY 4.0 data; retain attribution, license and changes disclosure. No endorsement. Retained source approval remains authoritative.',
        'retention':'Private append-only source objects, capture/admission receipts and input projections outside Git. 5 GiB aggregate across refresh/ and input registry, with 32 MiB admission headroom reserved before capture. No automatic deletion; stop on capacity. Existing forecast populations, launcher/runner evidence and exchange retain the publisher retention policy, outside this acquisition allowance. No raw exchange upload.',
        'quarantine':'Access refusal, physical schema drift, identity/score inconsistency and unresolved interrupted HTTP stop. No retry loop. Retain failure/raw bytes privately and preserve admitted pointer. SOURCE_FINAL_PENDING is a status gap, reconsider only after next bounded changed capture.',
        'atomicity':'Complete all capture/schema/identity/history/model checks before pointer swap; failure skips all publication that invocation. Per-game render failures isolated after whole-bundle admission.',
        'limitsScope':'New prospective grant only, not a reset/reuse of previous historical allowances. Meter redirect requests and response body bytes; reserve maxima durably before request. No NBA.com, nba_api, team-box or paid endpoints.'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repository-root',default=r'C:\Users\james\asp-model-studio')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    bound=immutable(Path(a.output), canonical_bytes(build(Path(a.repository_root))))
    print(json.dumps(bound,indent=2))


if __name__=='__main__':
    main()
