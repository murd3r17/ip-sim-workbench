import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
const vue = await readFile(new URL('../src/views/training/TrainingLabView.vue', import.meta.url), 'utf8')
const script = vue.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const ast = ts.createSourceFile('view.ts', script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const names = new Set(['readStoredReport', 'handleLoadReport', 'invalidateSessionRequests'])
const functions = ast.statements.filter(n => ts.isFunctionDeclaration(n) && names.has(n.name?.text)).map(n => n.getText(ast)).join('\n')
const compiled = ts.transpileModule(functions, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
function deferred() { let resolve, reject; const promise = new Promise((a,b) => { resolve=a;reject=b });return {promise,resolve,reject} }
function harness() {
  const reads=[],generations=[],confirmations=[]
  const refs=Object.fromEntries(['currentSession','reportReading','reportLoading','reportError','reportVersions','trainingReport','hintLoading','workspaceSaving','workspaceLoading','exporting','exportError'].map(k => [k,{value:null}]))
  refs.currentSession.value={id:1}; refs.reportVersions.value=[]
  const deps={...refs,getTrainingReport:()=>{const d=deferred();reads.push(d);return d.promise},
    generateTrainingReport:id=>{const d=deferred();generations.push({...d,id});return d.promise},
    ElMessageBox:{confirm:()=>{const d=deferred();confirmations.push(d);return d.promise}},
    ElMessage:{success(){}},nextTick:async()=>{},hintBlockRef:{value:null},notifyRequestError(){}}
  const methods = new Function(...Object.keys(deps), 'let sessionSelectionSeq=0,reportReadSeq=0,reportGenerateSeq=0,hintRequestSeq=0,workspaceReadSeq=0,workspaceSaveSeq=0,exportRequestSeq=0;'+compiled+';return {readStoredReport,handleLoadReport,invalidateSessionRequests};')(...Object.values(deps))
  return {...refs,...methods,reads,generations,confirmations}
}
const envelope = (id, value) => ({session_id:id,report:{session_id:id,version:1,summary:value},versions:[{version:1}]})
test('late A report never replaces B or clears B loading', async () => {
  const h=harness();const a=h.readStoredReport(1);h.currentSession.value={id:2};const b=h.readStoredReport(2)
  h.reads[0].resolve(envelope(1,'A'));await a
  assert.equal(h.trainingReport.value,null);assert.equal(h.reportReading.value,true)
  h.reads[1].resolve(envelope(2,'B'));await b;assert.equal(h.trainingReport.value.summary,'B')
})
test('failed read preserves saved content and explicitly reports unavailable', async () => {
  const h=harness();h.trainingReport.value=envelope(1,'saved').report
  const pending=h.readStoredReport(1);h.reads[0].reject(new Error('network'));await pending
  assert.equal(h.trainingReport.value.summary,'saved');assert.match(h.reportError.value,/读取.*失败/)
})
test('late A generation cannot overwrite B after navigation', async () => {
  const h=harness();const a=h.handleLoadReport();h.invalidateSessionRequests();h.currentSession.value={id:2};const b=h.readStoredReport(2)
  h.reads[0].resolve(envelope(2,'B'));await b;h.generations[0].resolve(envelope(1,'A'));await a
  assert.equal(h.trainingReport.value.summary,'B')
})
test('confirming regenerate after switching sessions sends no request', {timeout:1000}, async () => {
  const h=harness();h.trainingReport.value=envelope(1,'A').report
  const a=h.handleLoadReport();h.currentSession.value={id:2};h.confirmations[0].resolve();await a
  assert.equal(h.generations.length,0)
})

test('same-session read from before generation cannot replace the new version', async () => {
  const h=harness();const a=h.readStoredReport(1);const b=h.handleLoadReport()
  h.generations[0].resolve(envelope(1,'new'));await b
  h.reads[0].resolve(envelope(1,'old'));await a
  assert.equal(h.trainingReport.value.summary,'new')
})

test('closing and reopening the same session invalidates old generation', async () => {
  const h=harness();const a=h.handleLoadReport();h.invalidateSessionRequests();const b=h.readStoredReport(1)
  h.reads[0].resolve(envelope(1,'saved'));await b;h.generations[0].resolve(envelope(1,'late'));await a
  assert.equal(h.trainingReport.value.summary,'saved')
})

test('generation failure retains old report and a visible error without silent retry', async () => {
  const h=harness();h.trainingReport.value=envelope(1,'saved').report
  const a=h.handleLoadReport();h.confirmations[0].resolve();await Promise.resolve()
  h.generations[0].reject(new Error('network'));await a
  assert.equal(h.trainingReport.value.summary,'saved');assert.match(h.reportError.value,/生成失败/)
  assert.equal(h.generations.length,1);assert.equal(h.reads.length,0)
})

test('wrong-session response is rejected without replacing saved report', async () => {
  const h=harness();h.trainingReport.value=envelope(1,'saved').report
  const a=h.readStoredReport(1);h.reads[0].resolve(envelope(2,'wrong'));await a
  assert.equal(h.trainingReport.value.summary,'saved');assert.match(h.reportError.value,/读取.*失败/)
})
