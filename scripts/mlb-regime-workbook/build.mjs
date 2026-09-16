import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const resultPath = path.resolve(process.argv[2]);
const outputDir = path.resolve(process.argv[3]);
const result = JSON.parse(await fs.readFile(resultPath, 'utf8'));
const workbook = Workbook.create();
const review = workbook.worksheets.add('Cluster review');
const comparison = workbook.worksheets.add('Comparison');
const font = { name: 'Arial', size: 10, color: '#182533' };
function setup(sheet, title, width) {
  sheet.showGridLines = false;
  sheet.tabColor = '#29465F';
  sheet.getRange(`A1:${width}5`).format.font = font;
  sheet.getRange('A2').values = [[title]];
  sheet.getRange('A2').format.font = { ...font, size: 14, bold: true };
  sheet.getRange(`A3:${width}3`).format.borders = { bottom: { style: 'thin', color: '#29465F' } };
  sheet.getRange('A4').values = [['May 2–August 6, 2026 Development. Standalone residual system in cluster rows. Final OOT sealed.']];
  sheet.getRange('A5').values = [['Retain V18. Preserve ensemble for research. Amber cells are editable reviewer notes.']];
  sheet.getRange('A6').values = [[`Source: ${result.studyId}. Matched study result and diagnostics; see research report.`]];
  sheet.getRange(`A4:${width}6`).format.font = { ...font, size: 10 };
  sheet.freezePanes.freezeRows(7);
}
setup(review, 'MLB cluster and specialist review', 'M');
setup(comparison, 'MLB forecast comparison', 'H');
comparison.getRange('A4').values = [['Selection April 6–May 1; evaluation May 2–August 6, 2026. Raw and calibrated outputs remain separate.']];
comparison.getRange('A5').values = [['Selected ensemble: 89.2% V18, 10.8% existing RF, 0% specialists. No promotion or wagering authority.']];
const rows = result.clusterProfiles.map(row => [
  row.clusterId, row.domain, (row.features || []).join('\n'), row.interpretation,
  row.populationPAs, (row.seasons || []).join(', '), row.stabilityARI ?? 'n.a.',
  row.globalLogLoss ?? 'n.a.', row.specialistLogLoss ?? 'n.a.', null,
  row.meanAdjustment ?? 'n.a.', row.recommendation, '',
]);
review.getRange('A7:M7').values = [['Cluster', 'Family', 'Defining features', 'Interpretation', 'Population (PAs)',
  'Seasons', 'Stability (ARI)', 'V18 log loss', 'Residual-system log loss', 'Log-loss change',
  'Mean probability adjustment', 'Recommendation', 'Reviewer notes']];
if (rows.length) {
  review.getRange(`A8:M${7 + rows.length}`).values = rows;
  for (let r = 8; r < 8 + rows.length; r++) review.getRange(`J${r}`).formulas = [[`=IF(AND(ISNUMBER(H${r}),ISNUMBER(I${r})),I${r}-H${r},"n.a.")`]];
  review.getRange(`A7:M${7 + rows.length}`).format.font = font;
  for (let i = 0; i < rows.length; i++) review.getRange(`A${8+i}:M${8+i}`).format.rowHeight =
    result.clusterProfiles[i].features.length * 12 + 20;
  review.getRange(`A8:D${7 + rows.length}`).format.wrapText = true;
  review.getRange(`A8:M${7 + rows.length}`).format.verticalAlignment = 'center';
  review.getRange(`L8:M${7 + rows.length}`).format.wrapText = true;
  review.getRange(`M8:M${7 + rows.length}`).format.fill = '#FFF4CD';
  review.getRange(`E8:E${7 + rows.length}`).setNumberFormat('#,##0');
  review.getRange(`F8:F${7 + rows.length}`).format.horizontalAlignment = 'center';
  review.getRange(`G8:J${7 + rows.length}`).setNumberFormat('0.000000');
  review.getRange(`K8:K${7 + rows.length}`).setNumberFormat('0.0000');
  review.tables.add(`A7:M${7 + rows.length}`, true, 'MlbClusterReview').style = 'TableStyleLight1';
}
for (const [col, width] of Object.entries({ A:25, B:24, C:64, D:46, E:15, F:18, G:16, H:17, I:20, J:18, K:24, L:35, M:38 })) {
  review.getRange(`${col}7:${col}${Math.max(8, 7 + rows.length)}`).format.columnWidth = width;
}
const order = ['EVALUATION_CALIBRATED', 'EVALUATION_RAW', 'SELECTION_CALIBRATED', 'SELECTION_RAW'];
const comparisons = [...result.leaderboard].sort((a,b) => order.indexOf(a.phase)-order.indexOf(b.phase)).map(row => [row.model, row.phase, row.observations,
  row.games, row.logLoss, row.brier, row.deltaLogLoss, row.temperature ?? 1]);
comparison.getRange('A7:H7').values = [['Forecast', 'Period / output', 'PAs', 'Games', 'Log loss', 'Brier score', 'Change vs matched V18', 'Temperature']];
if (comparisons.length) {
  comparison.getRange(`A8:H${7 + comparisons.length}`).values = comparisons;
  comparison.getRange(`A7:H${7 + comparisons.length}`).format.font = font;
  comparison.getRange(`A8:H${7 + comparisons.length}`).format.rowHeight = 32;
  comparison.getRange(`A8:B${7 + comparisons.length}`).format.wrapText = true;
  comparison.getRange(`A8:H${7 + comparisons.length}`).format.verticalAlignment = 'center';
  comparison.getRange(`C8:D${7 + comparisons.length}`).setNumberFormat('#,##0');
  comparison.getRange(`E8:H${7 + comparisons.length}`).setNumberFormat('0.000000');
  comparison.tables.add(`A7:H${7 + comparisons.length}`, true, 'MlbForecastComparison').style = 'TableStyleLight1';
}
for (const [col, width] of Object.entries({ A:42, B:35, C:14, D:12, E:15, F:15, G:25, H:17 })) {
  comparison.getRange(`${col}7:${col}${Math.max(8, 7 + comparisons.length)}`).format.columnWidth = width;
}
for (const [sheet, last] of [[review, 'M'], [comparison, 'H']]) {
  sheet.getRange(`A7:${last}7`).format = { fill: '#29465F', font: { ...font, color: '#FFFFFF', bold: true },
    wrapText: true, rowHeight: 42, horizontalAlignment: 'center', verticalAlignment: 'center' };
}
await fs.mkdir(outputDir, { recursive: true });
workbook.recalculate();
for (let i = 0; i < rows.length; i++) {
  const actual = review.getRange(`J${8+i}`).values[0][0];
  const expected = rows[i][8] - rows[i][7];
  if (typeof actual !== 'number' || Math.abs(actual-expected) > 1e-12) throw new Error('Cluster delta formula mismatch');
}
console.log((await workbook.inspect({ kind:'table', range:'Cluster review!G7:K12', include:'values,formulas', tableMaxRows:6, tableMaxCols:5 })).ndjson);
console.log((await workbook.inspect({ kind:'match', searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!|#CALC!', options:{ useRegex:true, maxResults:25 } })).ndjson);
for (const [sheetName, range, name] of [['Cluster review','A1:F11','cluster-left'], ['Cluster review','G7:M11','cluster-right'], ['Comparison','A1:H20','comparison']]) {
  const image = await workbook.render({ sheetName, range, scale:1, format:'png' });
  await fs.writeFile(path.join(outputDir, `${name}.png`), new Uint8Array(await image.arrayBuffer()));
}
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(path.join(outputDir, 'MLB_Regime_Hybrid_Review.xlsx'));
console.log(JSON.stringify({ status:'EXPORTED', clusters:rows.length, comparisons:comparisons.length }));
