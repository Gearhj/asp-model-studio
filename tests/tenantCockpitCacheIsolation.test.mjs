import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const sourceRoot = process.env.ASP_CACHE_TEST_SOURCE_ROOT ?? new URL('../', import.meta.url).pathname;
const dataUrl = text => 'data:text/javascript;base64,' + Buffer.from(text).toString('base64');
const transpile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
const authUrl = dataUrl(transpile(await readFile(new URL('src/lib/authSession.ts', new URL(`file:///${sourceRoot.replaceAll('\\', '/').replace(/^\//, '')}/`)), 'utf8')));
const auth = await import(authUrl);
const reactUrl = dataUrl('export const useCallback=fn=>fn; export const useEffect=()=>{}; export const useLayoutEffect=()=>{}; export const useRef=()=>({}); export const useState=()=>[]; export const useSyncExternalStore=()=>null;');
const storeUrl = dataUrl('export const useCockpitStore={getState:()=>({})};');
let code = transpile(await readFile(new URL('src/sports/cockpit/cockpitPersistence.ts', new URL(`file:///${sourceRoot.replaceAll('\\', '/').replace(/^\//, '')}/`)), 'utf8'));
code = code.replace(/from "\.\.\/\.\.\/lib\/authSession"/g, `from "${authUrl}"`).replace(/from "react"/g, `from "${reactUrl}"`).replace(/from "\.\/cockpitApi"/g, `from "${storeUrl}"`);
const cache = await import(dataUrl(code));
globalThis.localStorage = { values: new Map(), getItem(key) { return this.values.get(key) ?? null; }, setItem(key, value) { this.values.set(key, String(value)); } };

test('cache preserves authored drafts while omitting computed evidence', () => {
  auth.setCachedUserId('synthetic-user-a');
  const value = cache.saveCockpitSnapshot('synthetic-project', { config: { features: ['alpha'], family: 'xgboost' }, notes: { objective: 'Retain this authored hypothesis' }, labSelected: ['xgboost'],
    labSuite: { priorDataset: { logLoss: 0.1 } }, lastResult: { datasetId: 'old-dataset' }, lastSim: { old: true }, engineeredProfiles: { old: true }, savedSteps: { trained: true } });
  assert.deepEqual(value.notes, { objective: 'Retain this authored hypothesis' });
  assert.deepEqual(value.config.features, ['alpha']);
  assert.deepEqual(value.labSelected, ['xgboost']);
  assert.equal(value.labSuite, undefined); assert.equal(value.lastResult, undefined); assert.equal(value.lastSim, undefined);
  assert.deepEqual(value.engineeredProfiles, {}); assert.deepEqual(value.savedSteps, {});
});

test('old snapshots are sanitized on read without modifying the stored original', () => {
  auth.setCachedUserId('synthetic-user-a');
  const key = cache.cockpitStorageKey('historical-project');
  const original = JSON.stringify({ version: 1, savedAt: 'synthetic-time', config: { features: ['beta'] }, notes: { draft: 'Keep my notes' }, lastResult: { foreignAuthority: true }, labSuite: { foreign: true } });
  localStorage.setItem(key, original);
  const value = cache.loadCockpitSnapshot('historical-project');
  assert.deepEqual(value.notes, { draft: 'Keep my notes' }); assert.deepEqual(value.config.features, ['beta']);
  assert.equal(value.lastResult, undefined); assert.equal(value.labSuite, undefined);
  assert.equal(localStorage.getItem(key), original);
});

test('session changes notify immediately and cannot restore another user draft', () => {
  const seen = [];
  const unsubscribe = auth.subscribeCachedUserId(() => seen.push(auth.getCachedUserId()));
  auth.setCachedUserId('synthetic-user-b');
  assert.deepEqual(seen, ['synthetic-user-b']);
  assert.equal(cache.loadCockpitSnapshot('synthetic-project'), null);
  auth.setCachedUserId('synthetic-user-a');
  assert.equal(cache.loadCockpitSnapshot('synthetic-project').notes.objective, 'Retain this authored hypothesis');
  unsubscribe();
});
