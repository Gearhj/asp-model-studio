import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

// Feature values come from executable-policy evidence; Excel is the editable
// review surface, not an alternate preprocessing engine.
const input = process.argv[2];
if (!input) throw new Error('Pass the immutable enriched feature-policy JSON');
const policyBytes = await fs.readFile(input);
const policy = JSON.parse(policyBytes);
const output = path.resolve('outputs/nfl-semantic-session-v1');
const rows = policy.rows;
if (rows.length !== policy.sourceFeatureCount || new Set(rows.map(r=>r.stableId)).size !== rows.length) throw new Error('Policy identity/count mismatch');
const wb = Workbook.create();
const overview = wb.worksheets.add('Overview');
const catalog = wb.worksheets.add('Feature catalog');
const treatment = wb.worksheets.add('Treatment decisions');
const text = value => value == null ? 'Not recorded' : Array.isArray(value) ? value.join(', ') : typeof value === 'object' ? JSON.stringify(value) : value;
const columnName = n => {let value=''; for(n++;n;n=Math.floor((n-1)/26))value=String.fromCharCode(65+(n-1)%26)+value;return value;};
const columns = (sheet, specs) => {
  const values = [specs.map(s=>s[0]), ...rows.map(r=>specs.map(s=>text(s[1](r))))];
  sheet.getRangeByIndexes(0,0,values.length,specs.length).values=values;
  sheet.showGridLines=false;
  const full=sheet.getRangeByIndexes(0,0,values.length,specs.length);
  full.format.font={name:'Arial',size:10};
  full.format.verticalAlignment='top';
  full.format.wrapText=true;
  sheet.getRangeByIndexes(0,0,1,specs.length).format={fill:'#243C5A',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};
  specs.forEach((s,i)=>sheet.getRangeByIndexes(0,i,values.length,1).format.columnWidth=s[2]||42);
  // Fit each long-form scientific record; preserve all metadata visibly.
  sheet.getRangeByIndexes(1,0,rows.length,specs.length).format.autofitRows();
  sheet.getRangeByIndexes(0,0,1,specs.length).format.rowHeight=36;
  sheet.tables.add(`A1:${columnName(specs.length-1)}${values.length}`,true,sheet===catalog?'NflFeatureCatalog':'NflTreatmentDecisions');
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(2);
};

columns(catalog,[
 ['Stable ID',r=>r.stableId,25],['Feature',r=>r.feature,52],['Source role',r=>r.stableId.startsWith('NFL197_')?'Registered M1 input':r.disposition.startsWith('IMPLEMENTED')?'New candidate input':'Proposed / excluded',25],
 ['Side / family',r=>[r.side,r.family].filter(Boolean).join(' / ')||'Game context',25],
 ['Definition',r=>r.definition,57],['Football meaning',r=>r.footballMeaning,57],['Units',r=>r.units,28],['Entity / grain',r=>r.entityGrain,38],['Valid domain',r=>r.validDomain,47],
 ['Source',r=>r.source,58],['Source identity',r=>r.sourceIdentity,69],['Join keys',r=>r.joinKeys,44],['Earliest defensible availability',r=>r.availability,54],['Observation / release timing',r=>r.releaseTiming,58],
 ['Historical rows',r=>typeof r.historicalRows==='number'?r.historicalRows:'Not validated',18],['Historically present',r=>typeof r.historicalPresent==='number'?r.historicalPresent:'Not validated',20],
 ['Historical missing fraction',r=>null,21],['Weeks 1–4 rows',r=>typeof r.weeks1to4Rows==='number'?r.weeks1to4Rows:'Not validated',20],['Weeks 1–4 present',r=>typeof r.weeks1to4Present==='number'?r.weeks1to4Present:'Not validated',21],['Weeks 1–4 missing fraction',r=>null,22],
 ['Current coverage / evidence state',r=>r.currentCoverage,64],['Missingness reason',r=>r.missingnessReason,64],['Disposition',r=>r.disposition,47],['Required source / limitation',r=>r.reason||r.rationale,64],
]);
for(let i=0;i<rows.length;i++){
  const n=i+2;
  catalog.getRange(`Q${n}`).formulas=[[`=IF(AND(ISNUMBER(O${n}),ISNUMBER(P${n}),O${n}>0),1-P${n}/O${n},"Not validated")`]];
  catalog.getRange(`T${n}`).formulas=[[`=IF(AND(ISNUMBER(R${n}),ISNUMBER(S${n}),R${n}>0),1-S${n}/R${n},"Not validated")`]];
}
catalog.getRange(`Q2:Q${rows.length+1}`).setNumberFormat('0.0%');
catalog.getRange(`T2:T${rows.length+1}`).setNumberFormat('0.0%');
catalog.getRange(`O2:P${rows.length+1}`).setNumberFormat('#,##0');
catalog.getRange(`R2:S${rows.length+1}`).setNumberFormat('#,##0');

columns(treatment,[
 ['Stable ID',r=>r.stableId,25],['Feature',r=>r.feature,52],['Selected designs',r=>r.selectedIn,20],['Disposition',r=>r.disposition,48],
 ['Structural zero',r=>r.structuralZero,61],['Exposure denominator',r=>r.exposureDenominator,55],['Season reset',r=>r.seasonReset,61],['Sparse history',r=>r.sparseHistory,61],['Rookie / new entity',r=>r.rookieNewEntity,61],
 ['Source outage',r=>r.sourceOutage,65],['Stale evidence',r=>r.staleEvidence,61],['Not applicable',r=>r.notApplicable,55],['Prior hierarchy',r=>r.priorHierarchy,65],['Sufficient statistics',r=>r.sufficientStatistics,65],
 ['Reliability / sample size',r=>r.reliability,60],['Recency / offseason',r=>[r.recency,r.offseasonTreatment].filter(Boolean).join('; ')||r.staleEvidence,61],['Uncertainty',r=>r.uncertainty,61],
 ['Outlier / transformation',r=>r.transformation,64],['Rationale',r=>r.rationale,65],['State indicators',r=>r.stateIndicators,61],['Historical / live parity',r=>r.historicalLiveParity,68],['Implementation',r=>r.implementation,70],['Reviewer decision',r=>'',30],['Reviewer notes',r=>'',55],
]);
treatment.getRange(`W2:X${rows.length+1}`).format.fill='#FFF7DE';
treatment.getRange(`W2:W${rows.length+1}`).dataValidation={rule:{type:'list',values:['Accept documented treatment','Request revision','Defer unsupported input']}};

overview.showGridLines=false;
overview.tabColor='#243C5A';
overview.getRange('A1:J34').format.font={name:'Arial',size:10};
overview.getRange('A2').values=[['NFL Feature Treatment Specification']];
overview.getRange('A2').format.font={name:'Arial',size:15,bold:true,color:'#243C5A'};
overview.getRange('A2:J2').format.borders={bottom:{style:'thin',color:'#243C5A'}};
overview.getRange('A4:C4').values=[['Coverage','Count','Definition']];
overview.getRange('A4:C4').format={fill:'#243C5A',font:{name:'Arial',bold:true,color:'#FFFFFF'}};
const end=rows.length+1;
overview.getRange('A5:A10').values=[['Source feature catalog'],['Registered M1 inputs'],['Implemented registered inputs'],['Excluded registered inputs'],['Added implemented inputs'],['Generic median branches in new recipes']];
overview.getRange('B5:B10').formulas=[
 [`=COUNTA('Feature catalog'!A2:A${end})`],
 [`=COUNTIFS('Feature catalog'!C2:C${end},"Registered M1 input")`],
 [`=COUNTIFS('Feature catalog'!C2:C${end},"Registered M1 input",'Feature catalog'!W2:W${end},"IMPLEMENTED")`],
 ['=B6-B7'],
 [`=COUNTIF('Feature catalog'!C2:C${end},"New candidate input")`],
 ['=0'],
];
overview.getRange('C5:C10').values=[['Registered and proposed source features; not expanded model columns'],['Exact legacy source-input order retains both home and away entries'],['Semantic/native-missingness decisions implemented in executable code'],['Roof open/closed status lacks pregame release authority'],['Lagged passing-personnel mixture; not the known target starter'],['Legacy T0–T2 remain declared median-treated baselines only']];
overview.getRange('A12:C12').values=[['Design','Active source inputs','Implemented treatment']];
overview.getRange('A12:C12').format={fill:'#243C5A',font:{name:'Arial',bold:true,color:'#FFFFFF'}};
overview.getRange('A13:A15').values=[['C1'],['C2'],['C3']];
overview.getRange('B13:B15').formulas=[['=B7'],['=B7+B9'],['=B14']];
overview.getRange('C13:C15').values=[['Team priors, prior-season information, offseason regression and valid-game reliability'],['C1 plus prior-date passing-personnel histories and uncertainty; no asserted actual starter'],['C2 plus training-only simple exposure/experience peer pooling']];
overview.getRange('A17:C17').values=[['Record','Value','Meaning']];
overview.getRange('A17:C17').format={fill:'#243C5A',font:{name:'Arial',bold:true,color:'#FFFFFF'}};
overview.getRange('A18:C24').values=[
 ['Policy',policy.contract,'Executable-policy metadata supplement; numerical fit authority remains separately hashed'],
 ['Policy SHA-256',crypto.createHash('sha256').update(policyBytes).digest('hex'),'Exact workbook source identity'],
 ['Development seasons','1999–2024','6991 games; five outer validation seasons2020–2024'],
 ['Current candidate limitation','Protected 2025 initialization not used','Current-slate publisher must expose missing/stale authority and never relabel publication time as source time'],
 ['Undefined versus zero','Raw exposure remains separate','Zero completed games is observed. Undefined opportunity rate is not an observed rate0. Native missingness handles unavailable rates.'],
 ['Research authority','RESEARCH_SHADOW / NOT_PROMOTED','No wagering authority; AISP imports evidence and does not execute models'],
 ['Editable review','Yellow cells in Treatment decisions','Reviewer decisions do not alter fitted artifacts. An executable change needs a separately versioned recipe.'],
 ];
let results;
try{
 const ptr=JSON.parse(await fs.readFile('outputs/nfl-semantic-lab-v1/CURRENT.json','utf8'));
 const bytes=await fs.readFile(ptr.resultPath);
 if(crypto.createHash('sha256').update(bytes).digest('hex')!==ptr.resultSha256) throw new Error('Model-result hash mismatch');
 results=JSON.parse(bytes);
}catch(error){if(error.code!=='ENOENT')throw error;}
overview.getRange('A26:C26').values=[['Fitted finalist','Expanded columns','Artifact SHA-256']];
overview.getRange('A26:C26').format={fill:'#243C5A',font:{name:'Arial',bold:true,color:'#FFFFFF'}};
if(results?.fittedArtifacts?.length){overview.getRangeByIndexes(26,0,results.fittedArtifacts.length,3).values=results.fittedArtifacts.map(f=>[f.pipelineId,f.expandedColumns,f.sha256]);}
else overview.getRange('A27:C27').values=[['Model run still in progress','Not yet frozen','This workbook must be rebuilt from completed result before final delivery']];
overview.getRange('A30:C32').values=[
 ['Source use',policy.rights,'Original source restrictions and attribution retained'],
 ['nflverse timing','https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html','Historical releases are not guaranteed contemporaneous archived vintages'],
 ['Reference structure','ASP_MLB_Feature_Treatment_Specification.xlsx','Adapted feature matrix, treatment archetypes, missingness evidence and editable reviewer decisions; no forced240-feature NFL total'],
];
overview.getRange('A1:A34').format.columnWidth=42;
overview.getRange('B1:B34').format.columnWidth=43;
overview.getRange('C1:C34').format.columnWidth=98;
overview.getRange('A4:C32').format.wrapText=true;
overview.getRange('A4:C32').format.verticalAlignment='center';
overview.getRange('A4:C32').format.autofitRows();
overview.getRange('B5:B15').setNumberFormat('#,##0');

wb.recalculate();
const expectedCounts = [[5,300],[6,197],[7,196],[8,1],[9,12],[10,0],[13,196],[14,208],[15,208]];
for (const [row,expected] of expectedCounts) {
  const actual=overview.getRange(`B${row}`).values[0][0];
  if(actual!==expected)throw new Error(`Summary B${row}: ${actual} != independent policy count ${expected}`);
}
console.log((await wb.inspect({kind:'table',range:'Overview!A4:C15',include:'values,formulas',tableMaxRows:12,tableMaxCols:3,maxChars:4500})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!',options:{useRegex:true,maxResults:20},summary:'Final formula scan'})).ndjson);
await fs.mkdir(output,{recursive:true});
for(const [sheetName,range,name] of [['Overview','A1:C16','overview'],['Feature catalog','A1:I3','catalog'],['Treatment decisions','A1:H3','treatments']]){
 const preview=await wb.render({sheetName,range,scale:1,format:'png'});
 await fs.writeFile(path.join(output,`${name}-preview.png`),new Uint8Array(await preview.arrayBuffer()));
}
const file=await SpreadsheetFile.exportXlsx(wb);
await file.save(path.join(output,'NFL_Feature_Treatment_Specification.xlsx'));
console.log(JSON.stringify({workbook:path.join(output,'NFL_Feature_Treatment_Specification.xlsx'),sourcePolicy:path.resolve(input),rows:rows.length,finalModelArtifacts:results?.fittedArtifacts?.length||0}));
