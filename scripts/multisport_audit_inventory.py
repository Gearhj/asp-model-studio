"""Schema-bound, source-backed multisport feature inventory (no outcomes)."""
from __future__ import annotations
import ast,json,re
from collections import Counter
from pathlib import Path
import pandas as pd
from run_multisport_feature_audit_v1 import ROOT,OUT,ref,write,now
from multisport_audit_empirical import family,names,clean,save

MLB=ROOT/'outputs/mlb-v18-conditional-champion-v1/frozen-model/sha256/6297787b57e7e74436036e75b40cf67339115f0cbf6333406766179c9569a235/model-bindings.json'
MP=ROOT/'.runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/21f13e822fcfc204bcbc769f171e4e57379b56c58d7bf330ceb3cc9a0f877df5.json'
MC=ROOT/'outputs/mlb-v18-current-state-pipeline-v1/objects/sha256/3a2570895b6a51174017a224604f46b8fc0c86ac958262c05825eba95f80580b/raw246-field-contract.json'
NFL=Path('C:/Users/james/asp-data-staging/nfl/m1-modeling-benchmark-v1/research-artifact/objects/sha256/ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9/manifest.json')
NV=Path('C:/Users/james/asp-data-staging/nfl/m1-prospective-shadow-v1/feature-vectors/sha256/39cb2f9ce1d22881b45600a1cd9232c29e4b385b5d905990b01093c8fc256cba/feature-vector.json')
NBA=ROOT/'outputs/nba-gen1-long-gap-v1/current-research/receipt.json'
CFB=ROOT/'outputs/cfb-gen1-v1/feature-contract.json'
SOURCES=[]
def load(p):
    # Only explicitly named model/feature contracts in this module are admitted.
    if 'inputs-after' in str(p) or 'inputs-before' in str(p) or 'miss-analysis' in str(p):raise ValueError('Rejected snapshot')
    SOURCES.append(ref(p));return json.loads(Path(p).read_text(encoding='utf-8'))
def code(p):
    p=ROOT/p;SOURCES.append(ref(p));return str(p)
def row(sport,engine,n,stage='MODEL_INPUT',status='ACTIVE',**kw):
    r=dict(sport=sport,model_or_engine=engine,feature_name=n,stage=stage,feature_family=family(sport,n) if sport in ['NBA','NFL','CFB'] else 'DOCUMENTED_CONTEXT',target_channel='EXPECTED_HOME_AWAY_POINTS',raw_or_derived='DERIVED',definition='UNAVAILABLE_SEE_BOUND_CONTRACT',mathematical_transformation='UNAVAILABLE_SEE_BOUND_CONTRACT',source='UNAVAILABLE',source_grain='TEAM_GAME',source_clock='Actual acquisition timestamp retained; historical publication/revision vintage uncertified',earliest_availability='After earlier completed game, before target cutoff',required_lag='Strictly earlier game date; target excluded',historical_coverage='Component metadata/code only in this audit; no additional label population opened',prospective_availability='Requires admitted source evidence before cutoff',missingness='NOT_MEASURED',imputation_or_fallback='Component-specific support gate; no audit imputation',normalization_or_encoding='Component-specific bound implementation; no additional audit transformation',rolling_window='Component-specific; not an additional point-model rolling feature',opponent_adjustment='NONE_EXPLICIT',orientation='HOME/AWAY separate; difference=HOME minus AWAY',identity_embedded='TEAM_HISTORY_KEY_NOT_ONE_HOT',preprocessing_object='NO_SEPARATE_OBJECT_IDENTIFIED',version_or_contract='SEE_BOUND_SOURCE',status=status,leakage_risk='Finalized historical reconstruction; capture time does not prove old availability',known_limitations='Component metadata alone does not establish measured incremental value',importance_evidence='FEATURE_IMPORTANCE_AND_ABLATION.json; grouped permutation is associational',working_signal='UNKNOWN',source_feature=n)
    r.update(kw);return r

def nba_definition(n):
    q=n.removeprefix('home_').removeprefix('away_')
    d={
      'elo':'Pre-target chronological Elo: initial1500,K20,home advantage65,400-point logistic scale; season carry (2/3)^elapsed seasons.',
      'elo_home_win_probability':'1/(1+10^(-(home_elo-away_elo+65)/400)); independent Elo winner channel, also numeric Ridge input.',
      'home_court':'1 for eligible oriented home-court targets; neutral historical context is not an assessed target.',
      'rest_days':'max(0,calendar-day gap-1); corrected treatment keeps finite known non-opener values only within training-derived pooled maximum; otherwise NaN.',
      'rest_known':'1 only when ordinary rest is known and within fitted support, otherwise0.',
      'back_to_back':'1 when treated rest_days=0 and supported; original calendar spacing is one day.',
      'current_season_weight':'n/(n+10), n=earlier current-season games.',
      'season_games_played':'Count of strictly earlier admitted current-season team games.',
      'prior_season_games':'Count of admitted team games in immediately preceding season; not an assumed82.',
      'rolling_games':'min(20,earlier current-season games).',
      'history_supported':'1 when current or previous team season has at least5 games.',
      'early_season':'1 when current-season support is less than10 games.',
      'variability_supported':'1 when current rolling or prior team population has at least2 games.',
      'prior_fallback_available':'1 when earlier league moments exist; does not certify team history.',
      'league_history_games':'Count of strictly earlier admitted games; not independent team exposures.',
      'league_mean_home_score':'Mean home final points of earlier nonneutral games.',
      'league_mean_away_score':'Mean away final points of earlier nonneutral games.',
      'league_mean_total':'Sum of earlier league home and away means.',
      'league_mean_home_margin':'Earlier league home mean minus away mean.',
    }
    if n in d:return d[n]
    if q in d:return d[q]
    if n.startswith('difference_'):return 'HOME minus AWAY '+n[11:]+'; rest difference computed before independent train-only imputation.'
    if q.startswith('games_last_'):return 'Count of earlier admitted team dates in last '+q.removeprefix('games_last_').replace('_',' ')+'; includes declared Cup date-only context.'
    base=q.removeprefix('rolling_').removeprefix('prior_').removesuffix('_std')
    measure={'points_for':'team final points','points_allowed':'opponent final points','margin':'team minus opponent final points','total':'sum of both final scores'}.get(base,base)
    if q.endswith('_std'):
        return ('Population SD (ddof0) of '+measure+' over last20 earlier current-season games; at least2 support.' if q.startswith('rolling_') else 'sqrt(max(0,shrunk second moment - squared shrunk first moment)) of '+measure+';10 prior pseudo-games; missing if unsupported.')
    if q.startswith('rolling_'):return 'Mean '+measure+' over last20 earlier current-season games; NaN before any.'
    if q.startswith('prior_'):return 'Previous-season '+measure+' mean shrunk with10 pseudo-games to earlier league mean.'
    return 'Current earlier-season mean '+measure+' shrunk with10 pseudo-games to prior season; actual count n/(n+10).'

def nfl_definition(n):
    q=n.removeprefix('home_').removeprefix('away_');window=next((w for w in ['season_to_date','last_4','last_8','last_16'] if q.endswith('_'+w)),None)
    if window:
        metric=q[:-(len(window)+1)]
        base={
         'points_for':'designated team final score','points_against':'opponent final score',
         'offensive_epa_per_play':'mean source EPA over pass/run plays','pass_epa_per_play':'mean source EPA over pass plays','rush_epa_per_play':'mean source EPA over run plays',
         'success_rate':'mean source success indicator over pass/run plays','explosive_pass_rate':'fraction of pass plays with yards_gained>=20','explosive_rush_rate':'fraction of run plays with yards_gained>=10',
         'early_down_success_rate':'mean success over down1/2 pass/run plays','third_down_conversion_rate':'mean third_down_converted on down3','fourth_down_conversion_rate':'mean fourth_down_converted on down4',
         'red_zone_td_play_rate':'fraction of pass/run plays from yardline_100<=20 that score a touchdown; NOT drive red-zone conversion',
         'turnover_rate':'mean max(interception,fumble_lost), coalesced0, over attributed plays','sack_rate':'mean sack over qb_dropback=1','penalty_rate':'mean penalty over attributed plays',
         'seconds_per_play':'mean current minus next game-clock seconds over pass/run plays where elapsed is0..120; uses source order_sequence',
        }
        if metric.startswith('defensive_'):
            b=metric.removeprefix('defensive_').replace('_allowed_rate','_rate')
            b='offensive_epa_per_play' if b=='epa_per_play' else b
            desc='opponent realized offensive game metric: '+base.get(b,b)
        else:desc=base.get(metric,metric)
        return 'Unweighted mean of game-date means of '+desc+' over '+window+'. Same-date team games grouped before lag; missing game-metric observations skipped.'
    d={'days_since_previous_game':'Calendar days since prior completed team game; across seasons retained.', 'short_week':'1 if days_since_previous_game<6.', 'bye_or_long_rest':'1 if days_since_previous_game>=10.', 'prior_games':'Count of all earlier completed team games.', 'prior_season_games':'Count of earlier games in TARGET season (despite misleading name).', 'source_era_missing':'1 if prior_games==0; not a per-feature missing indicator.'}
    if q in d:return d[q]
    return {'season':'Target schedule season year.','week':'Target schedule week.','game_type':'Governed schedule competition type; historical gold uses WC/DIV/CON/SB for playoffs.','game_month':'Target game calendar month.','game_weekday':'Day of week from schedule date, DuckDB Sunday=0.','neutral_site':'1 when location is Neutral.','division_game':'Schedule div_game indicator.','roof':'Schedule roof category; historical revision vintage uncertified.','surface':'Schedule surface category; historical revision vintage uncertified.'}[n]

def cfb_definition(n):
    q=n.removeprefix('home_').removeprefix('away_')
    if n.startswith('elo') or q=='elo':return 'Chronological Elo: FBS1500/nonFBS1350, K24, home55 unless neutral,400 scale, season carry2/3; difference includes site.'
    if q=='rest_days_capped21':return 'Same-season days between scheduled kickoffs capped21; opener default14. No actual completion clock inferred.'
    if q=='season_opener':return '1 before any admitted same-season team game.'
    if q=='long_gap':return '1 when same-season kickoff gap>21 days; not offseason length.'
    if q=='current_season_games':return 'Count of earlier context-eligible team games this season.'
    if n=='rest_difference':return 'HOME capped-rest days minus AWAY capped-rest days.'
    if n in ['neutral_site','conference_competition','week']:return 'Governed pregame schedule '+n+'; conference_competition is an indicator, not conference strength.'
    if 'trailing5' in n:return 'Arithmetic mean '+('team minus opponent scores' if 'margin' in n else 'combined game scores')+' over previous5 context games; crosses season boundaries; no history falls back to shrunk season estimate.'
    if 'prior_' in n:return 'Previous season '+('margin' if 'margin' in n else 'total')+' shrunk n/(n+5) toward0 margin/56 total; immediate preceding season only.'
    default='28 points' if 'points_' in n else '375 yards' if 'yards' in n else '1.5 turnovers'
    measure=q.replace('_season','').replace('_',' ')
    return 'Mean earlier current-season '+measure+'; no current observations -> previous-season mean shrunk by5 pseudo-games to '+default+'. Missing source boxes are skipped, not observed zeros.'

def build():
    SOURCES.clear();rows=[];bindings={};contracts={}
    mlb,prep,mc=load(MLB),load(MP),load(MC)
    bindings['MLB']={'model':mlb['modelIdentity'],'artifact':mlb['paArtifact'],'featureContract':{k:v for k,v in mlb['featureContract'].items() if k not in ['rawOrderedFields','treatedOrderedFields']},'counts':{'RAW_DEPENDENCY':246,'TREATED_MODEL_INPUT':273,'ENCODED_ESTIMATOR_COLUMN':436},'currentFieldSnapshot':ref(MC),'chronology':mlb['historicalIntegrity']['notice']}
    raw={r['field']:r for r in mc['fields']};cols={r['feature']:r for r in prep['transformationContracts']['modelFeatureColumns']};traincheck=prep['trainingModelInputValidation']['features']
    constant_flags={n:v for n,v in prep['categoricalLevelsIncludingUnknown'].items() if len([x for x in v if x!='UNKNOWN'])<=1}
    modelbase=dict(target_channel='EIGHT_PA_CLASS_PROBABILITIES_THEN_SIMULATION',historical_coverage='Operational fold5 nominal2023-03-30..2026-05-01; PIT training chronology uncertified; no outcome use in this audit',preprocessing_object=str(MP),version_or_contract=mlb['featureContract']['modelFeatureSchemaChecksum'],normalization_or_encoding='Frozen semantic/prior treatment, numeric pass-through plus fitted one-hot with UNKNOWN; no generic median',identity_embedded='PLAYER_HISTORY_LOOKUP; participant identity not automatically estimator coordinate',importance_evidence='SKIPPED proper-score permutation: current fold fitted through2026 and historical chronology uncertified; no MLB outcome payload loaded')
    for n,r in raw.items():
        spec=r.get('acceptedSpecification') or {};selected=n in cols
        rows.append(row('MLB','V18_HGB_PA_FOLD5',n,'RAW_DEPENDENCY',status='ACTIVE_SOURCE_DEPENDENCY' if selected else 'DEPENDENCY_NOT_DIRECT_MODEL_SLOT',**modelbase,
          feature_family=r['sourceFamily'],definition=r['definition'],mathematical_transformation=json.dumps(r['v18Transformation'],ensure_ascii=False,sort_keys=True),source=str(MC),source_grain=r['entityGrain'],source_clock=r['requiredAvailability'],required_lag=r['lookbackWindow'],rolling_window=r['lookbackWindow'],prospective_availability=r['currentImplementationStatus'],imputation_or_fallback=r['missingValueTreatment']+' '+r['coldStartTreatment'],missingness=json.dumps({'historical_spec_missing_percent':spec.get('missing_percent'),'currentCategory':r['categoryName'],'categoryScope':'bound pregame field snapshot, not all future games'}),working_signal='DIRECT_SLOT' if selected else 'DEPENDENCY_ONLY',known_limitations='Raw availability is not outcome-vintage certification. '+str(spec.get('primary_missing_reason',''))))
    for n,c in cols.items():
        src=c.get('sourceFeature',n);r=raw.get(src,{})
        check=traincheck.get(n,{}); count=int(check.get('validatedRows',0));missing=int(check.get('nativeMissingRows',0))
        rows.append(row('MLB','V18_HGB_PA_FOLD5',n,'TREATED_MODEL_INPUT',**modelbase,feature_family=r.get('sourceFamily','FROZEN_PRIOR_SUPPORT'),source_feature=src,definition=r.get('definition','Frozen treatment output of '+src),mathematical_transformation=json.dumps(c,sort_keys=True),source=str(MP),source_grain=r.get('entityGrain','DERIVED_PA_INPUT'),rolling_window=r.get('lookbackWindow','FROZEN_TRAINING_PRIOR'),missingness=json.dumps(check),imputation_or_fallback='Frozen native NaN or governed posterior/history state; global imputation prohibited',working_signal='CONSTANT_CATEGORICAL_OR_RESERVED_UNKNOWN' if n in constant_flags else 'NATIVE_MISSING_ALL' if count and missing==count else 'POPULATED_TREATED_SLOT_NOT_PROOF_OF_RAW_OBSERVATION',known_limitations='Some categorical flags observed in one state plus reserved UNKNOWN only; support encoding is not extra external information.'))
    enc=mlb['fittedPreprocessor']['encoder'];encnames=enc.get('featureNamesOut',enc.get('outputFeatureNames',enc.get('encodedFeatureNames')))
    if encnames is None:
        lists=[v for k,v in enc.items() if isinstance(v,list) and len(v)==436];assert len(lists)==1;encnames=lists[0]
    contracts['MLB_encoded_columns']=encnames
    # Expanded indicators are fully mapped separately, not counted as new raw signals.
    for n in encnames:
        unpref=n.split('__',1)[1]; candidates=[c for c in cols if unpref==c or unpref.startswith(c+'_')];src=max(candidates,key=len) if candidates else unpref
        rows.append(row('MLB','V18_HGB_PA_FOLD5',n,'ENCODED_ESTIMATOR_COLUMN',**modelbase,feature_family=raw.get(cols.get(src,{}).get('sourceFeature',src),{}).get('sourceFamily','FROZEN_PRIOR_SUPPORT'),source_feature=src,definition='Encoded estimator coordinate of treated input '+src,mathematical_transformation='Numeric identity' if n.startswith('numeric__') else 'Fitted categorical equality indicator; unknown category has explicit level',source=str(MLB),imputation_or_fallback='Inherited from treated source; UNKNOWN may be reserved',working_signal='ENCODING_NOT_NEW_SIGNAL',known_limitations='Do not add encoded counts to raw-feature counts.'))
    bindings['MLB']['constantCategoricalTrainingLevels']=constant_flags
    nf,nv=load(NFL),load(NV);assert nf['featureNames']==list(names('NFL'))==nv['featureNames']
    bindings['NFL_M1']={k:nf[k] for k in ['candidateId','featureCount','modelArtifact','foundationManifestSha256','recencyStrategy','hyperparameters']}
    bindings['NFL_M1']['sourceManifest']=ref(NFL);bindings['NFL_M1']['currentFeatureVector']={**ref(NV),'forecastCutoffUtc':nv['forecastCutoffUtc'],'sourceCutoffUtc':nv['sourceCutoffUtc'],'missingFeatures':nv['missingFeatures'],'nonnullValues':sum(x is not None for x in nv['values']),'eventId':nv['eventId']}
    nb=load(NBA);bindings['NBA_POINT_ELO']={'configurationIdentity':nb['configurationIdentity'],'models':{k:v['artifact'] for k,v in nb['models'].items()},'pointFeatureCount':78,'winnerChannel':'Separate chronological Elo; no lineup/player features'}
    cf=load(CFB);bindings['CFB_POINT']={'contract':ref(CFB),'featureCount':35,'model':ref(ROOT/'outputs/cfb-gen1-v1/models/selected-through-2025.joblib'),'recipe':'Ridge alpha100 margin+total;35 features; Development-only probability calibration separate'}
    definitions={'NFL':nfl_definition,'NBA':nba_definition,'CFB':cfb_definition}
    engines={'NFL':'NFL_M1_XGBOOST','NBA':'NBA_RIDGE_A100_ORDINARY_REST','CFB':'CFB_RIDGE_ALPHA100'}
    preprocess={'NFL':str(NFL),'NBA':nb['models']['ridge_a100_rest']['artifact']['path'],'CFB':bindings['CFB_POINT']['model']['path']}
    src={'NFL':code('server/sports_nfl/canonical.py')+'; '+code('server/sports_nfl/gold.py'),'NBA':code('server/sports_nba_gen1/historical_features.py')+'; '+code('server/sports_nba_gen1/recent_features.py')+'; '+code('server/sports_nba_gen1/rest_support.py'),'CFB':code('server/sports_cfb_gen1/pipeline.py')}
    cov=pd.concat([pd.read_csv(OUT/'empirical'/stage/'coverage.csv') for stage in ['development','later']],ignore_index=True)
    for sport in ['NFL','NBA','CFB']:
        for n in names(sport):
            cv=cov[(cov.sport==sport)&(cov.feature==n)];miss=int(cv.missing.sum());den=int(cv.n.sum());const=bool(cv.distinct.le(1).all())
            missing={'assessedMissing':miss,'assessedRows':den,'fraction':miss/den,'constantWithinEveryAssessedSeason':const,'definition':'after governed treatment; nonnull CFB may be fallback'}
            if sport=='NFL':missing['currentVectorValueMissing']=nv['values'][nv['featureNames'].index(n)] is None
            rows.append(row(sport,engines[sport],n,definition=definitions[sport](n),mathematical_transformation=definitions[sport](n),source=src[sport],historical_coverage={'NFL':'Gold1999-2025; current artifact through2025 season. Audit 2022/23/24 only, earlier training >=2000.','NBA':'Admitted recent2019-20..2025-26; audit2020-21..2024-25 only.','CFB':'2014..2025 history; current2026 source separate. Audit2021..2024 only.'}[sport],missingness=json.dumps(missing),imputation_or_fallback={'NFL':'Fold-local numeric median + missing indicator; all-missing0 + indicator; categorical SOURCE_OR_HISTORY_MISSING, unknown ignored.','NBA':'Ordinary rest treatment before training-only numeric median; no added imputer indicators; existing support flags.','CFB':'Feature-builder prior/default fallback first; remaining NaN training-only median.'}[sport],normalization_or_encoding='Training-only StandardScaler; '+('categorical one-hot' if sport=='NFL' else 'numeric only'),rolling_window={'NFL':'season_to_date and4/8/16 prior team dates; arithmetic, not exponential weights','NBA':'last20 current-season games, previous season,3/7/14 calendar days;10 pseudo-games','CFB':'current season, cross-season last5, prior season;5 pseudo-games,rest cap21'}[sport],preprocessing_object=preprocess[sport],version_or_contract={'NFL':nf['foundationManifestSha256'],'NBA':nb['models']['ridge_a100_rest']['featureContractSha256'] if 'featureContractSha256' in nb['models']['ridge_a100_rest'] else 'NBA_GEN1_ORDINARY_REST_RIDGE_A100_V1','CFB':str(CFB)}[sport],required_lag='Strictly earlier date; target and same-date outcomes excluded' if sport!='CFB' else 'Earlier kickoff; equal kickoff excluded; actual completion clock not checked in historical builder',opponent_adjustment='Elo implicitly opponent-relative; no adjusted box-efficiency fit' if 'elo' in n else 'NONE_EXPLICIT',working_signal='MISSING_ALL' if miss==den else 'CONSTANT_WITHIN_ASSESSED_SEASONS' if const else 'POPULATED_VARYING_INPUT',known_limitations={'NFL':'Unweighted game-rate means; overlapping windows. Source-ERA flag does not measure per-metric support. Current nonnull is not all-current-season support.','NBA':'Scores/dates only; no possessions, players or lineup. Point and Elo channels independently estimated.','CFB':'No observed-vs-fallback indicator for every box metric; yards are not per-play efficiency; schedule conference flag is not strength.'}[sport]))
    # Separate documented engines: never add these to primary point-model counts.
    from server.sports_current_statcast.mlb_regime_clusters import DOMAIN_FEATURES
    from server.sports_current_statcast.mlb_pitcher_style_profiles import STYLE_FEATURES
    from server.sports_current_statcast.mlb_starter_duration_current_inputs import FEATURES as DUR
    from server.sports_cfb_gen1.archetype_gap import TEAM_VARIABLES
    blocks=[('MLB','MLB_STARTER_DURATION_HGB_RESEARCH',list(DUR),code('server/sports_current_statcast/mlb_starter_duration_current_inputs.py'),'PREGAME_STARTER_HISTORY'),('MLB','MLB_PITCHER_STYLE_RESEARCH',list(STYLE_FEATURES),code('server/sports_current_statcast/mlb_pitcher_style_profiles.py'),'PITCHER_STYLE_NOT_ACTIVE'),('CFB','CFB_ARCHETYPE_CLUSTER_RESEARCH',list(TEAM_VARIABLES),code('server/sports_cfb_gen1/archetype_gap.py'),'CLUSTER_INPUT_NOT_ADDITIONAL_POINT_FEATURE')]
    for domain,ns in DOMAIN_FEATURES.items():blocks.append(('MLB','MLB_REGIME_'+domain,list(ns),code('server/sports_current_statcast/mlb_regime_clusters.py'),'CLUSTER_INPUT_NOT_ACTIVE'))
    for sport,engine,ns,source,stage in blocks:
        bindings[engine]={'count':len(ns),'features':ns,'source':ref(source),'status':'EXPERIMENTAL_NOT_CONTROLLING'}
        for n in ns:
            if n in raw:desc=raw[n]['definition']
            elif n in cols:
                srcname=cols[n].get('sourceFeature',n);desc=raw.get(srcname,{}).get('definition',srcname)+'; treatment coordinate '+json.dumps(cols[n],sort_keys=True)
            elif n=='style_throws_left':desc='Left-handed pitcher indicator from eligible prior telemetry; actual target pitch outcomes excluded.'
            elif 'STYLE' in engine:desc='365 strictly prior days; '+n+' denotes pitch-group usage or its named telemetry quantile in stated units; min200 pitches/3 dates/30 measurement pitches; unknown pitch type is its own group.'
            elif sport=='CFB':desc=cfb_definition('home_'+n)
            else:desc={'homePitcher':'1 for HOME starter,0 AWAY.','calendarMonth':'Target game calendar month1..12.','priorStartCount':'Count of all eligible earlier starts in the frozen history universe; completeness required.','priorStartBfMean':'Sum of BF across those eligible prior starts / priorStartCount; NULL if certified count0.','daysRest':'Target date minus latest eligible prior start date minus1; NULL only certified no-history.','historyMissing':'True only when certified eligible priorStartCount=0; unavailable source is not this branch.'}[n]
            rows.append(row(sport,engine,n,stage,status='EXPERIMENTAL',definition=desc,mathematical_transformation=desc,source=source,source_grain='PLAYER_START' if sport=='MLB' else 'TEAM_PREGAME',preprocessing_object=source,version_or_contract=engine,working_signal='EXPERIMENTAL_NOT_ACTIVE',imputation_or_fallback='Exact frozen contract: no unsupported source filling; unavailable candidate falls back to baseline',known_limitations='Research coordinates do not establish deployment or incremental gain.'))
    drive=load(ROOT/'outputs/nfl-drive-competing-risks-v1/FEATURE_CONTRACT.json');bindings['NFL_DRIVE_SURVIVAL']={'count':drive['featureCount'],'contract':ref(ROOT/'outputs/nfl-drive-competing-risks-v1/FEATURE_CONTRACT.json'),'status':'COMPLETED_RETAIN_BASELINE; NOT_ADVANCING'}
    for v in drive['features']:rows.append(row('NFL','NFL_DRIVE_SURVIVAL_RESEARCH',v['name'],'RISK_STATE',status='EXPERIMENTAL_NOT_ADVANCING',definition=v['definition'],mathematical_transformation=v['definition'],source=drive['implementation']['path'],source_grain='PREDECISION_DRIVE_RISK_STATE',required_lag='Earlier snaps only; simulated state evolves in future rollouts',imputation_or_fallback=drive['missingTreatment'],working_signal='CONSTANT_ZERO_IN_FITTING' if v['name']=='overtime' else 'SUPPORTED_RISK_INPUT',known_limitations='25 named coordinates; OT flag is never1 in fitting and is not learned OT evidence.',preprocessing_object=drive['implementation']['path'],version_or_contract=drive['schemaVersion'] if 'schemaVersion' in drive else 'NFL_DRIVE_COMPETING_RISKS_V1'))
    play={'phase':'SCRIMMAGE/TRY/KICKOFF','down':'Exact1..4;0 outside scrimmage','distance_bin':'searchsorted thresholds2,5,10 yards','field_bin':'min(9,floor(yardline_100/10))','late_clock_bin':'0 ordinary,1 half<=120sec,2 half<=30sec','score_bin':'ordinary sign; late thresholds[-16,-8,-3,0,3,8,16]','offense_team':'Canonical offensive team donor bank','defense_team':'Canonical defensive team donor bank','season':'Discount team support0.65^elapsed seasons','yardline_100':'Continuous return/turnover feasibility constraint; not extra binned state'}
    for n,d in play.items():rows.append(row('NFL','NFL_HIERARCHICAL_PLAY_ENGINE',n,'SIMULATION_STATE',status='EXPERIMENTAL',definition=d,mathematical_transformation=d,source=code('server/sports_nfl_m1/play_model.py'),source_grain='SIMULATED_PREPLAY_STATE',required_lag='State evolves within simulated game; historical donor fitting uses earlier seasons',imputation_or_fallback='Required state fails closed; sparse banks shrink to pooled phase',working_signal='ACTIVE_WITHIN_RESEARCH_ENGINE',preprocessing_object='Nested empirical donor banks; no sklearn197-column vector',version_or_contract='NFL_PLAY_LEVEL_RESEARCH',known_limitations='10 documented selector/support inputs; six context-key axes plus identity/season/feasibility, not ten independent learned regressors.'))
    for engine,items,source in [
      ('NBA_ELO_WINNER',{'home_elo':'Earlier HOME Elo','away_elo':'Earlier AWAY Elo','home_advantage65':'Fixed65 points added before400-scale logistic; no fitting to current game'},'server/sports_nba_gen1/historical_features.py'),
      ('NBA_JOINT_PAIRED_RESIDUAL',{'ridge_home_mean':'Corrected earlier-trained point expectation','ridge_away_mean':'Corrected earlier-trained point expectation','paired_home_residual':'HOME residual from eligible chronological OOF donor','paired_away_residual':'AWAY residual from SAME donor','donor_date':'Strictly earlier date, min200 donors'},'server/sports_nba_gen1/joint_residual.py'),
      ('NBA_CLOSE_MARGIN_POSTPROCESSOR',{'absolute_margin':'Input joint abs margin<=8 only','total_parity':'Odd/even total, exact total retained','signed_winner':'Winner retained','development_cdf':'Earlier Development or frozen Development-only margin CDF'},'server/sports_nba_gen1/close_score.py'),
      ('CFB_PAIRED_RESIDUAL',{'predicted_margin':'Earlier-trained35-feature Ridge margin','predicted_total':'Earlier-trained35-feature Ridge total','paired_home_residual':'Chronological HOME residual','paired_away_residual':'Same-game AWAY residual','donor_kickoff':'Earlier kickoff; not actual completion certificate'},'server/sports_cfb_gen1/pipeline.py'),
      ('NFL_M1_RESIDUAL_DISTRIBUTION',{'expected_home_points':'M1 XGBoost HOME mean','expected_away_points':'M1 XGBoost AWAY mean','paired_home_residual':'Chronological OOF HOME residual','paired_away_residual':'Same OOF donor AWAY residual','scenario':'Frozen BASE and registered variance handling','seed_draw_count':'Frozen10000 draw seed731001; numerical provenance, not a predictor'},'server/sports_nfl_m1/prospective_shadow.py')]:
        sport=engine[:3];bindings[engine]={'documentedInputs':len(items),'source':ref(ROOT/source),'separateFromPointFeatures':True}
        for n,d in items.items():rows.append(row(sport,engine,n,'SEPARATE_CHANNEL_OR_POSTPROCESSOR',status='RESEARCH',definition=d,mathematical_transformation=d,source=code(source),source_grain='GAME_DISTRIBUTION_INPUT',required_lag='Earlier chronological OOF donors; frozen Development kernel where applicable',imputation_or_fallback='Insufficient required support -> explicit unavailable/frozen baseline fallback per component',working_signal='POSTPROCESSOR_NOT_POINT_FEATURE',preprocessing_object=source,version_or_contract=engine,known_limitations='No claim these channels are one identical simulation law. No distribution ablation or draws regenerated.'))
    current_pub=code('server/sports_current_statcast/mlb_v18_current_publication.py')
    simulator_inputs={'confirmedLineups':'Exactly nine confirmed ordered batters per side; authority status CONFIRMED with authentic evidence clocks. No bench substitution policy.', 'awayStarter':'Confirmed AWAY pitcher with source/player identity and raw246 history binding.', 'homeStarter':'Confirmed HOME pitcher with source/player identity and raw246 history binding.', 'awayBullpen':'Pregame anonymous team-staff template mixture; not named-reliever availability.', 'homeBullpen':'Pregame anonymous team-staff template mixture; not named-reliever availability.', 'transitionModel':'Frozen base/out/runner transition model; evolves within each simulated game; includes non-PA events where supported.'}
    bindings['MLB_CURRENT_SIMULATOR']={'source':ref(current_pub),'inputContractCount':len(simulator_inputs),'simulationCount':5000,'frozenParentSimulationSettings':mlb['simulator']['acceptedSimulationSettings'],'originalRuntimeReferences':mlb['simulator']['runtimeCodeBindings'],'qualification':'Frozen registration runtime references may predate source-only repairs; current source hashes are bound separately, never treated as current scalar model weights.'}
    for n,d in simulator_inputs.items():
        rows.append(row('MLB','MLB_V18_CURRENT_SIMULATOR',n,'PREGAME_SIMULATOR_CONTRACT',feature_family='CONFIRMED_INPUT_OR_FROZEN_TRANSITION',target_channel='JOINT_GAME_SCORES',definition=d,mathematical_transformation=d,source=current_pub,source_grain='PREGAME_GAME_INPUT',source_clock='Observed/available/captured before forecast cutoff; original source and publication clocks retained in forecast',required_lag='Confirmed pregame evidence; never actual future substitutions',identity_embedded='CANONICAL_BATTER_PITCHER_TEAM_LOOKUPS',preprocessing_object=current_pub,version_or_contract='MLB_V18_CURRENT_STATE_PIPELINE_V1',working_signal='SUPPORTED_ONLY_AFTER_PREGAME_GATES',known_limitations='Fixed ordered lineup and anonymous relief mixture; stateful PA inputs are simulated rather than actual future-PA predictions.'))
    codefiles=['server/sports_nfl_m1/prospective_shadow.py','server/sports_nfl_m1/preprocessing.py','server/sports_nfl_m1/models.py','server/sports_nfl_m1/distributions.py','server/sports_nfl/current_season_sync.py','server/sports_current_statcast/mlb_v18_current_features.py','server/sports_current_statcast/mlb_v18_current_inputs.py','server/sports_current_statcast/mlb_v18_prospective_transform.py','server/sports_current_statcast/mlb_v18_whole_game_challenger.py','server/sports_phase5/base_out_transition.py','server/sports_phase5/whole_game_monte_carlo.py','server/sports_current_statcast/mlb_v18_current_exposure.py','server/artifacts/governance/mlb-final-oot-quarantine-v1.json']
    for p in codefiles:code(p)
    for p in [Path(mlb['paArtifact']['path']),Path(nb['models']['ridge_a100_rest']['artifact']['path']),Path(nb['models']['elo']['artifact']['path']),NFL.parent/'model.joblib',ROOT/'outputs/cfb-gen1-v1/models/selected-through-2025.joblib']:
        SOURCES.append(ref(p)) # Physical binding only; no model payload deserialization.
    frame=pd.DataFrame(rows)
    for engine,channel,fam in [('NFL_DRIVE_SURVIVAL_RESEARCH','DRIVE_CAUSE_HAZARD_AND_JOINT_GAME_SCORES','PREDECISION_RISK_STATE'),('NFL_HIERARCHICAL_PLAY_ENGINE','NEXT_PLAY_EVENT_AND_JOINT_GAME_SCORES','EMPIRICAL_DONOR_CONTEXT'),('NBA_ELO_WINNER','HOME_WIN_PROBABILITY','CHRONOLOGICAL_ELO')]:
        mask=frame.model_or_engine.eq(engine);frame.loc[mask,'target_channel']=channel;frame.loc[mask,'feature_family']=fam
    frame.loc[frame.stage.eq('SEPARATE_CHANNEL_OR_POSTPROCESSOR') & ~frame.model_or_engine.eq('NBA_ELO_WINNER'),'target_channel']='JOINT_SCORE_DISTRIBUTION_OR_POSTPROCESSING'
    assert not frame.duplicated(['sport','model_or_engine','stage','feature_name']).any()
    frame.to_csv(OUT/'CURRENT_FEATURE_INVENTORY.csv',index=False,encoding='utf-8',lineterminator='\n')
    counts=frame.groupby(['sport','model_or_engine','stage']).size().reset_index(name='rows').to_dict('records')
    save(OUT/'MODEL_AND_FEATURE_BINDINGS.json',dict(createdAtUtc=now(),models=bindings,inventoryCounts=counts,encodedContracts=contracts,qualification='Counts describe different stages and components; never sum them into one model count. Historical missingness, current source state and observed variation are distinct.'))
    save(OUT/'SOURCE_BINDINGS.json',dict(createdAtUtc=now(),files=list({r['path']:r for r in SOURCES}.values()),access='Metadata/code/feature contracts and physical hashes; no bound MLB outcome payload or current NFL model deserialization. ACCESS_EXCEPTION.json qualifies the separate earlier snapshot exposure.'))
    print(json.dumps({'rows':len(frame),'sourceFiles':len({r['path'] for r in SOURCES}),'counts':counts}))

if __name__=='__main__':build()
