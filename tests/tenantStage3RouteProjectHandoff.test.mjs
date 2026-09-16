import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const sourceRoot = process.env.ASP_HANDOFF_TEST_SOURCE_ROOT ?? fileURLToPath(new URL('../', import.meta.url));
const source = await readFile(path.join(sourceRoot, 'src/sports/workflow/GuidedStageContent.tsx'), 'utf8');
const compiled = ts.transpileModule(source, { fileName: 'GuidedStageContent.tsx', compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React } }).outputText;
// Keep the real component logic; replace presentation-only imports with a JSX recorder.
const code = `const React={createElement:(type,props,...children)=>({type,props:{...props,children}})}; const PaModelingCockpit='project-cockpit';\n` + compiled.replace(/^import[\s\S]*?;\r?\n/gm, '');
const { GuidedStageContent } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
const readState = { status: 'idle', review: null };

test('fresh contract hydration uses the explicit route project on the first render', () => {
  const view = GuidedStageContent({ number: 3, projectId: 'project-route-a', dataset: null, contract: null, currentGoldReview: readState });
  assert.equal(view.type, 'project-cockpit');
  assert.equal(view.props.projectId, 'project-route-a');
});

test('a stale contract from another project cannot change the cockpit request project', () => {
  const view = GuidedStageContent({ number: 3, projectId: 'project-route-a', dataset: null, contract: { projectId: 'project-old-b' }, currentGoldReview: readState });
  assert.equal(view.props.projectId, 'project-route-a');
});

test('missing selected project cannot mount a cockpit from a contract or placeholder', () => {
  const view = GuidedStageContent({ number: 3, projectId: '', dataset: null, contract: { projectId: 'project-old-b' }, currentGoldReview: readState });
  assert.notEqual(view.type, 'project-cockpit');
  assert.equal(view.props.role, 'alert');
});
