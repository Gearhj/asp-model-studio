"""Freeze the Category-A pilot from metadata before parsing game outcomes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nba_gen1.authority import json_bytes, reference, verified_bytes, immutable_json, RESEARCH_FLAGS
from server.sports_nba_gen1.historical_features import historical_feature_contract

OUT = ROOT/'outputs/nba-gen1-historical-pilot-v1'


def main():
    pointer = OUT/'declaration.json'
    if pointer.exists():
        receipt = json.loads(pointer.read_bytes())
        verified_bytes(receipt['declaration'])
        print(json.dumps(receipt, indent=2))
        return
    acquired = json.loads((OUT/'acquisition.json').read_bytes())
    verified_bytes(acquired['metadata'])
    metadata = pd.read_parquet(acquired['metadata']['path'])
    metadata = metadata[(metadata.lg_id == 'NBA') & (metadata.is_playoffs == 0) & metadata.year_id.between(2010,2015)]
    assert len(metadata) == 14278 and metadata.game_id.nunique() == 7139
    roles = {2010:'INITIAL_FIT_WARMUP',2011:'DEVELOPMENT',2012:'DEVELOPMENT',2013:'DEVELOPMENT',2014:'VALIDATION',2015:'FINAL_CATEGORY_A_HOLDOUT'}
    population = []
    for year, group in metadata.groupby('year_id'):
        locations = group.groupby('game_id').game_location.agg(lambda x: ''.join(sorted(x)))
        assert set(locations.unique()) <= {'AH','NN'}
        population.append({'seasonEnd':int(year),'season':f'{year-1}-{str(year)[2:]}','role':roles[int(year)],
                           'games':len(locations),'eligibleHomeAway':int((locations=='AH').sum()),
                           'neutralHistoryOnly':int((locations=='NN').sum()),
                           'sourceGameIds':sorted(locations.index.tolist())})
    value = {
        'schemaVersion':'NBA_GEN1_CATEGORY_A_REDUCED_PILOT_DECLARATION_V1',
        'createdAtUtc':datetime.now(timezone.utc).isoformat(),
        'evidenceClass':'A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION',
        'scope':'NBA regular-season final full-game outcomes including overtime; date-ordered historical reconstruction, not certified-at-the-time assessment or prospective forecasts.',
        'priorInstruction':'Do not train on retrospectively reconstructed pregame facts without valid timestamps.',
        'currentAuthorization':'Latest user instruction explicitly permits classification A development from finalized records acquired today, with true acquisition clocks and disclosed missing revision vintages. Separate Category-A implementation; strict B/C implementation preserved.',
        'source':reference(OUT/'acquisition.json'),'rightsReview':reference(OUT/'source-option-review.json'),
        'sourceOptionsChecked':2,'thirdOption':'Not needed: a permitted real score population supports the requested league/Elo pilot.',
        'population':population,'populationSelection':'Latest six season-end years in verified metadata, before outcome parsing. No completeness claim beyond observed source coverage. 2012 has 990 games and 2013 has 1229; do not invent absent games.',
        'neutralPolicy':'NN games retain publisher _iscopy=0 focal axis as internal SIDE1, never asserted actual home. Zero Elo home advantage, update both teams history symmetrically, exclude from home/away fitting and assessment.',
        'chronology':'Emit all features for game date D from game dates < D; no same-day results. Historical source publication and original revision availability unknown; do not invent next-day timestamps.',
        'featureContract':historical_feature_contract(),
        'families':[{'family':'league','params':{},'winProbability':'Historical home-win fraction in earlier season training labels'},
                    {'family':'elo','params':{},'winProbability':'Rebuilt fixed Elo logistic probability with K20, home advantage65, scale400, initial1500, between-season regression2/3'}],
        'pointModels':'Reuse unmodified models.fit_model for league and Elo. Expected margin/total parameters fitted on earlier seasons only, frozen throughout each assessment season; Elo feature state updates only from earlier dates.',
        'modelFitCohort':'All source-home/away games in earlier declared seasons. First season initializes features/model; later assessment games retained even early-season, with support flags disclosed.',
        'assessmentProcedure':'Expanding earlier-season training. Development assesses each of 2011,2012,2013. Validation assesses2014 once. Freeze both unchanged benchmark configurations and validation conclusion before parsing or assessing2015 outcomes. Assess2015 once; no holdout tuning.',
        'metrics':['winner_log_loss','binary_brier','winner_pick_accuracy','home_mae','away_mae','margin_mae','total_mae'],
        'brierDefinition':'(pHomeWin - I(home_score>away_score))^2; pAwayWin=1-pHomeWin, final tie probability0.',
        'uncertainty':'Paired candidate-minus-league differences across the same whole games, 2000 deterministic calendar-week block-bootstrap replicates, seed731101. Descriptive uncertainty for this historical reconstruction, not contemporaneous availability certification.',
        'reportingSlices':['season','earlier current-season support <10 versus >=10 both teams','either team back-to-back','minimum rest 0,1,2+ calendar days'],
        'selection':'No full Gen1 champion selection: original primary joint energy gate cannot be evaluated without supported joint draws. Fit and retain both benchmarks. Identify directional point/probability gains; no calibration, blend, hyperparameter tuning or promotion.',
        'unavailable':['Ridge/HGB 65-feature screen: no team boxes or possession rates','Joint residual simulator: no overtime-period evidence under existing frozen gate','Energy, CRPS, prediction interval coverage, distribution tails','B contemporaneous source availability','C future schedule and pre-cutoff inputs'],
        'protectedPartitions':'No existing MLB/NFL or strict proposed modern NBA protected population is accessed. 2015 is a new Category-A internal final holdout only.',
        'authority':RESEARCH_FLAGS,'numericalModules':{name:reference(ROOT/'server/sports_nba_gen1'/name) for name in ('models.py','historical_features.py')},
        'performanceExaminedAtDeclaration':False,
    }
    bound = immutable_json(OUT,'declaration.json',value)
    pointer.write_bytes(json_bytes({'declaration':bound}))
    print(json.dumps({'declaration':bound,'counts':[{k:v for k,v in row.items() if k!='sourceGameIds'} for row in population]},indent=2))


if __name__ == '__main__':
    main()
