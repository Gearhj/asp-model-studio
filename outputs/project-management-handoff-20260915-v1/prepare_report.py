"""Package a report from retained reports only; never read model outcome datasets."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sources = {
    'feature_audit': 'outputs/multisport-feature-engineering-audit-v1/REPORT.md',
    'mlb_pa': 'outputs/mlb-v18-empirical-diagnosis-v1/REPORT.md',
    'mlb_doubles': 'outputs/mlb-v18-doubles-followup-v1/decision.md',
    'mlb_misses': 'outputs/mlb-v18-september12-miss-analysis-v1/decision-note.md',
    'mlb_counters': 'outputs/mlb-v18-population-diagnostics-v1/decision-note.md',
    'mlb_calibration': 'outputs/mlb-v18-ensemble-release-candidate-v1/DECISION.md',
    'mlb_rf': 'outputs/mlb-v18-rf-operationalization-v1/rf-artifact-inventory.json',
    'mlb_transitions': 'outputs/mlb-v18-transition-shrinkage-v1/notes/sha256/c3ac6638a154c8b2a3b17a242c923a46b31adadf6979ba9c192feffcc6374b1b/DECISION.md',
    'mlb_archetype': 'outputs/mlb-pitcher-archetype-survival-v1/DECISION.md',
    'mlb_filter': 'outputs/mlb-v18-score-limited-v1/decision-note.md',
    'mlb_formal': 'outputs/mlb-prospective-closeout-and-explanations-v1/formal-revision1/RESULTS.md',
    'mlb_totals': 'outputs/mlb-v18-totals-distribution-v1/completion-note.md',
    'mlb_preview': 'outputs/mlb-show-preview-feasibility-v1/REPORT.md',
    'mlb_shrinkage': 'outputs/mlb-matchup-starter-shrinkage-v1/REPORT.md',
    'nfl_update': 'outputs/nfl-m1-current-season-update-v1/DECISION.md',
    'nfl_qb': 'outputs/nfl-m1-qb-context-residual-v1/RESULTS.md',
    'nfl_play': 'outputs/nfl-play-level-engine-v1/MODEL_CARD.md',
    'nfl_drive': 'outputs/nfl-drive-competing-risks-v1/REPORT.md',
    'nfl_import': 'outputs/nfl-week2-successor-automation-v1/consumer-observation/sha256/153b12814aa74e0f02680eb96e7110a5e1b4d3ae4ac8eec4a766bbd19cc32a28/consumer-observation.json',
    'nfl_eligibility': 'outputs/nfl-week2-paper-eligibility-20260915-v1/batch/sha256/82d2a87fd4a24deb9c1a7b26dfc4f11347e9a3daf9f1a39d9ea4ac5aacc890b1/CLAUDE_HANDOFF.md',
    'nba_recent': 'outputs/nba-gen1-recent-v1/REPORT.md',
    'nba_rest': 'outputs/nba-gen1-long-gap-v1/REPORT.md',
    'nba_joint': 'outputs/nba-gen1-joint-residual-v1/REPORT.md',
    'nba_close': 'outputs/nba-gen1-close-score-v1/completed/REPORT.md',
    'nba_future': 'outputs/nba-gen1-joint-prospective-v1/final/package/sha256/00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d/CLAUDE_HANDOFF.md',
    'cfb_source': 'outputs/cfb-gen1-v1/SOURCE_REVIEW.md',
    'cfb_initial': 'outputs/cfb-gen1-v1/REPORT.md',
    'cfb_current': 'outputs/cfb-gen1-current-v1/REPORT.md',
    'cfb_extensions': 'outputs/cfb-archetype-extended-gap-v1/REPORT.md',
    'preview': 'outputs/multisport-show-preview-producer-v1/REPORT.md',
    'preview_handoff': 'outputs/multisport-show-preview-producer-v1/CLAUDE_HANDOFF.md',
    'timing': 'outputs/mlb-v18-delivery-timing-audit-v1/sha256/ced67bf4b4a0a4447a67b34f56934729452848f8efc4c1730f7c555fd7b7f972/CLAUDE_HANDOFF.md',
    'roster': 'outputs/mlb-roster-freshness-repair-v1/sha256/abe9ee20b75dc992b5926063b7ac631820c3cb6748a7c0f5c8b84387549d7522/CLAUDE_HANDOFF.md',
    'natural_tick': 'outputs/mlb-v18-unattended-v1/objects/sha256/498926e2c02df8791669595896dc6787e6b19be78400369ba8182f4936e3fed7/tick.json',
    'governance': 'AGENTS.md',
}
groups = {
    'Executive summary': ['mlb_preview','mlb_shrinkage','nfl_import','nba_rest','nba_joint','cfb_current','cfb_extensions','natural_tick'],
    '1. What Model Studio has built': ['feature_audit','preview','mlb_counters','mlb_totals'],
    '2. How Model Studio and AISP work together': ['preview_handoff','nfl_eligibility','timing','mlb_totals','mlb_counters'],
    '3. Data and evidence qualifications': ['governance','nba_rest','cfb_source','nfl_update','mlb_shrinkage'],
    '4. MLB: controlling V18 and the approaches tested': ['mlb_pa','mlb_doubles','mlb_misses','mlb_counters','mlb_calibration','mlb_rf','mlb_transitions','mlb_archetype','mlb_filter','mlb_formal','mlb_preview','mlb_shrinkage'],
    '5. NFL: M1, current-season repair and research alternatives': ['nfl_update','nfl_qb','nfl_play','nfl_drive','nfl_import','nfl_eligibility','timing'],
    '6. NBA: real-data baseline, robustness repair and joint distributions': ['nba_recent','nba_rest','nba_joint','nba_close','nba_future'],
    '7. College Football: fitted Gen 1 and rejected extensions': ['cfb_source','cfb_initial','cfb_current','cfb_extensions'],
    '8. Publication, Show Preview and operational readiness': ['timing','roster','natural_tick','preview','preview_handoff','mlb_preview','mlb_shrinkage'],
    '9. Reading the metrics correctly': ['mlb_pa','nfl_qb','nba_joint','mlb_totals'],
    '10. Exact handoff references and next dependency': ['mlb_shrinkage','preview_handoff','nba_future','mlb_formal','nfl_import'],
    '11. Starting instructions for the new project-management chat': ['governance','mlb_shrinkage','natural_tick'],
}

def sha(b): return hashlib.sha256(b).hexdigest()
def save(p,v): p.write_text(json.dumps(v,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
now = datetime.now(timezone.utc).isoformat()
index=[]
for sid, relative in sources.items():
    p=ROOT/relative
    b=p.read_bytes()
    index.append(dict(id=sid,path=str(p),bytes=len(b),sha256=sha(b),classification='retained report or operational/identity receipt; not a new assessment',inspectedForHandoff=True))
save(OUT/'SOURCE_INDEX.json',{'createdAt':now,'evidenceClockPolicy':'Each report/receipt retains its own evidence cutoff. Retrieval time is not data freshness.','sources':index})
byid={v['id']:v for v in index}
md=(OUT/'REPORT.md').read_text(encoding='utf-8')
parts=re.split(r'(?m)^## ',md)
sections=[]
queries={}
for i,part in enumerate(parts[1:]):
    heading=part.split('\n',1)[0]
    ids=groups[heading]
    qid=f'section_{i+1:02d}'
    queries[qid]={'rows':[byid[k] for k in ids], 'source':{
        'name':heading,'executedAt':now,'description':'Evidence index for this report section. Metrics are transcribed from these completed reports, not recomputed from outcomes.',
        'metricDefinitions':{'bytes':{'label':'Physical source bytes','definition':'Length of the exact retained source file, without newline normalization.'},'sha256':{'label':'Physical SHA-256','definition':'SHA-256 of the exact source bytes.'}},
        'evidenceFlow':[{'title':'Retained completed evidence','detail':'Read only the named reports, scoped receipts and instruction file; preserve historical/prospective and current/superseded distinctions.'},{'title':'Handoff synthesis','detail':'Transcribe matched cohort results with units, model identities, exceptions and independent output channels. No fitting, provider calls or outcome re-analysis.'}],
    }}
    chunks=[]
    qids=[qid]
    text_lines=[]
    table_lines=[]
    table_n=0
    narrative_n=0
    context_title=heading
    def flush_text():
        global narrative_n
        if text_lines:
            narrative_n+=1
            chunks.append({'kind':'prose','id':f'{qid}:prose:{narrative_n}','markdown':'\n'.join(text_lines).strip()})
            text_lines.clear()
    def flush_table():
        global table_n
        if not table_lines:return
        table_n+=1
        tid=f'{qid}_table_{table_n}'
        cells=lambda line:[c.strip().replace('**','').replace('`','') for c in line.strip().strip('|').split('|')]
        headers=cells(table_lines[0])
        columns=[{'field':f'c{j}','label':label} for j,label in enumerate(headers)]
        rows=[]
        for line in table_lines[2:]:
            vals=cells(line)
            assert len(vals)==len(headers),(heading,line)
            rows.append({f'c{j}':v for j,v in enumerate(vals)})
        source=dict(queries[qid]['source'])
        source['name']=context_title
        source['description']='Exact formatted values transcribed from completed source reports. Source references: '+', '.join(ids)
        source['files']=[byid[k] for k in ids]
        source['metricDefinitions']={c['field']:{'label':c['label'],'definition':'Retained report value; cohort, units, scoring convention and qualifications appear in the adjacent narrative and bound source reports.'} for c in columns}
        queries[tid]={'rows':rows,'source':source}
        qids.append(tid)
        chunks.append({'kind':'table','id':tid,'title':context_title,'columns':columns})
        table_lines.clear()
    for line in ('## '+part.strip()).splitlines():
        if line.startswith('|'):
            flush_text();table_lines.append(line)
        else:
            flush_table()
            if line.startswith('### '):context_title=line[4:]
            text_lines.append(line)
    flush_table();flush_text()
    sections.append({'id':qid,'title':heading,'chunks':chunks,'queryIds':qids})
save(OUT/'sections.json',sections)
snapshot={'surface':'report','title':'Four sports have working models; preview delivery is the remaining MLB gap','generatedAt':now,'status':'reviewed','buildStatus':'creating','filters':[], 'report':{},'queries':queries}
save(OUT/'reviewed.json',snapshot)
catalog=['# Source catalog','', 'Physical checksums and byte counts are in SOURCE_INDEX.json. These links point to retained local evidence; later reports may explicitly supersede earlier conclusions.','']
for v in index:
    catalog.append(f"- [{v['id']}]({Path(v['path']).as_posix()}): `{v['sha256']}` ({v['bytes']:,} bytes)")
(OUT/'SOURCES.md').write_text('\n'.join(catalog)+'\n',encoding='utf-8')
(OUT/'HANDOFF.md').write_text(md+'\n\n'+ '\n'.join(catalog).replace('# Source catalog','## Appendix: source catalog',1)+'\n',encoding='utf-8')
def git(*a):return subprocess.check_output(['git',*a],cwd=ROOT,text=True).strip()
save(OUT/'REPORT_RECEIPT.json',{'createdAt':now,'branch':git('branch','--show-current'),'head':git('rev-parse','HEAD'),'preexistingTrackedStatus':git('status','--short','--untracked-files=no').splitlines(),'reportSha256':sha((OUT/'REPORT.md').read_bytes()),'reportBytes':(OUT/'REPORT.md').stat().st_size,'sourceCount':len(index),'sourceIndexSha256':sha((OUT/'SOURCE_INDEX.json').read_bytes()),'providerCalls':0,'externalBytes':0,'incrementalCostUSD':0,'aispWrites':0,'modelsFitted':0,'forecastsGenerated':0,'outcomeDatasetAccessForNewAssessment':False,'qualification':'Read-only synthesis of completed evidence. No live AISP integration or profitability re-audit.'})
print(json.dumps({'sourceCount':len(index),'reportWords':len(md.split()),'sectionCount':len(sections),'head':git('rev-parse','HEAD')}))
