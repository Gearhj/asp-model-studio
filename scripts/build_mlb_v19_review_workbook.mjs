// Author with the bundled spreadsheet runtime, not repository dependencies.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..');
const requireBundled = createRequire(path.join(root, '.runtime/mlb-v19-workbook/runtime.cjs'));
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(requireBundled.resolve('@oai/artifact-tool')).href);
const input = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const outputDir = path.join(root, 'outputs/mlb-v19-current-state-specialists-v1/review');
await fs.mkdir(outputDir, {recursive:true});
const workbook = Workbook.create();
for (const spec of input.sheets) workbook.worksheets.add(spec.name);

function columnName(n) {
  let result='';
  for(n++;n>0;n=Math.floor((n-1)/26)) result=String.fromCharCode(65+(n-1)%26)+result;
  return result;
}
for (const [index,spec] of input.sheets.entries()) {
  const sheet=workbook.worksheets.getItem(spec.name);
  sheet.showGridLines=false;
  const start=spec.raw ? 1 : 5;
  if(!spec.raw) {
    sheet.getRange('A2').values=[[spec.title]];
    sheet.getRange('A2').format.font={name:'Arial',size:15,bold:true,color:'#243B53'};
    sheet.getRange('A3').values=[[spec.subtitle || '']];
    sheet.getRange('A3').format.font={name:'Arial',size:10,italic:true,color:'#52606D'};
  }
  const typedRows=spec.rows.map(row=>row.map((value,column)=>{
    if(spec.columns[column].date && value!==null) {
      const date=new Date(value.length===10 ? `${value}T00:00:00Z` : value);
      if(!Number.isFinite(date.valueOf())) throw new Error(`Invalid source date in ${spec.name}`);
      return date;
    }
    return value;
  }));
  const rows=[spec.columns.map(x=>x.label),...typedRows];
  const end=start+rows.length-1;
  const last=columnName(spec.columns.length-1);
  const range=sheet.getRange(`A${start}:${last}${end}`);
  range.values=rows;
  range.format.font={name:'Arial',size:10,color:'#243B53'};
  range.format.rowHeight=21;
  range.format.verticalAlignment='center';
  const header=sheet.getRange(`A${start}:${last}${start}`);
  header.format={fill:'#334E68',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:34,horizontalAlignment:'center'};
  for(const [col,c] of spec.columns.entries()) {
    const letter=columnName(col);
    sheet.getRange(`${letter}${start}:${letter}${end}`).format.columnWidth=c.width || 20;
    if(c.format && end>start) sheet.getRange(`${letter}${start+1}:${letter}${end}`).setNumberFormat(c.format);
    if(c.editable && end>start) sheet.getRange(`${letter}${start+1}:${letter}${end}`).format.fill='#FFF4CE';
    if(c.wrap && end>start) {
      sheet.getRange(`${letter}${start+1}:${letter}${end}`).format.wrapText=true;
      sheet.getRange(`A${start+1}:${last}${end}`).format.rowHeight=spec.rowHeight || 54;
      sheet.getRange(`A${start+1}:${last}${end}`).format.verticalAlignment='top';
    }
  }
  for(const formula of spec.formulas || []) sheet.getRange(formula.cell).formulas=[[formula.formula]];
  sheet.freezePanes.freezeRows(start);
  if(spec.columns.length>6) sheet.freezePanes.freezeColumns(Math.min(2,spec.columns.length));
  sheet.tables.add(`A${start}:${last}${end}`,true,`V19Table${index+1}`);
  if(index===0) sheet.tabColor='#243B53';
}
workbook.recalculate();
const featureSheet=workbook.worksheets.getItem('Feature quality');
const coverageSheet=workbook.worksheets.getItem('Coverage');
const originalClassification=featureSheet.getRange('D6').values[0][0];
const originalCoverage=coverageSheet.getRange('C7').values[0][0];
featureSheet.getRange('D6').values=[['FULLY_CURRENT']];
workbook.recalculate();
const changedCoverage=coverageSheet.getRange('C7').values[0][0];
featureSheet.getRange('D6').values=[[originalClassification]];
workbook.recalculate();
if(originalClassification!=='HISTORICAL_PRIOR_BY_DESIGN' || originalCoverage!==176 || changedCoverage!==177 || coverageSheet.getRange('C7').values[0][0]!==176)
  throw new Error('Coverage formula did not respond and restore exactly');
const inspections=[];
for(const spec of input.sheets) {
  const range=spec.previewRange || `A1:${columnName(Math.min(spec.columns.length-1,5))}14`;
  const check=await workbook.inspect({kind:'table',range:`'${spec.name}'!${range}`,include:'values,formulas',tableMaxRows:14,tableMaxCols:6,maxChars:3000});
  inspections.push({sheet:spec.name,check:check.ndjson});
  if(!input.renderOnly || input.renderOnly.includes(spec.name)) {
    const preview=await workbook.render({sheetName:spec.name,range,scale:1.5,format:'png'});
    await fs.writeFile(path.join(outputDir,`${spec.name.replace(/[^A-Za-z0-9]/g,'_')}.png`),new Uint8Array(await preview.arrayBuffer()));
  }
}
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'Final formula error scan',maxChars:3000});
const exportFile=await SpreadsheetFile.exportXlsx(workbook);
await exportFile.save(path.join(outputDir,'MLB_V19_Research_Review.xlsx'));
await fs.writeFile(path.join(outputDir,'workbook-verification.json'),JSON.stringify({sheets:inspections,errorScan:errors.ndjson,
  coverageRecalculation:{original:originalCoverage,changed:changedCoverage,restored:176,sourceRestored:true}},null,2));
console.log(JSON.stringify({path:path.join(outputDir,'MLB_V19_Research_Review.xlsx'),sheets:input.sheets.length,errorScan:errors.ndjson}));
