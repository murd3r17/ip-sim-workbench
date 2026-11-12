import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
const text=await readFile(new URL('../src/views/training/TrainingLabView.vue',import.meta.url),'utf8')
const ast=ts.createSourceFile('view.ts',text.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1],ts.ScriptTarget.Latest,true,ts.ScriptKind.TS)
const wanted=['loadWorkspace','saveWorkspace','overwriteWithLocal','workspaceContent']
const body=ast.statements.filter(n=>ts.isFunctionDeclaration(n)&&wanted.includes(n.name?.text)).map(n=>n.getText(ast)).join('\n')
const code=ts.transpileModule(body,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
function harness(){
  const reads=[],saves=[],confirmations=[]
  const refs=Object.fromEntries(['currentSession','workspaceNotes','workspaceSteps','workspaceRevision','workspaceReadOnly','workspaceSaving','workspaceSavedAt','workspaceConflict','workspaceLoading','workspaceError','workspaceSavedContent'].map(k=>[k,{value:null}]))
  Object.assign(refs.currentSession,{value:{id:1,status:'in_progress'}})
  refs.workspaceNotes.value='A';refs.workspaceSteps.value=[{id:1,status:'todo'}];refs.workspaceRevision.value=3
  const deps={...refs,normalizeWorkspaceSteps:v=>v,
    getTrainingWorkspace:()=>{const d=deferred();reads.push(d);return d.promise},
    updateTrainingWorkspace:(id,data)=>{const d=deferred();saves.push({...d,id,data});return d.promise},
    ElMessage:{success(){},error(){},warning(){}},
    ElMessageBox:{confirm:()=>{const d=deferred();confirmations.push(d);return d.promise}}}
  const methods=new Function(...Object.keys(deps),'let sessionSelectionSeq=0,workspaceReadSeq=0,workspaceSaveSeq=0;'+code+';return {loadWorkspace,saveWorkspace,overwriteWithLocal};')(...Object.values(deps))
  return {...refs,...methods,reads,saves,confirmations}
}
test('late A save cannot change B revision, saved time or save spinner',async()=>{
  const h=harness();const a=h.saveWorkspace();h.currentSession.value={id:2};h.workspaceRevision.value=10;h.workspaceSavedAt.value='B';h.workspaceSaving.value=false
  const b=h.saveWorkspace();h.saves[0].resolve({revision:4,updated_at:'A'});await a
  assert.equal(h.workspaceRevision.value,10);assert.equal(h.workspaceSavedAt.value,'B');assert.equal(h.workspaceSaving.value,true)
  h.saves[1].resolve({revision:11,updated_at:'B2'});await b
})
test('failed workspace read preserves local content and locks save until successful retry',async()=>{
  const h=harness();const p=h.loadWorkspace(1);h.reads[0].reject(new Error('offline'));await p
  assert.equal(h.workspaceNotes.value,'A');assert.match(h.workspaceError.value,/读取.*失败/);assert.equal(h.workspaceReadOnly.value,true)
  await h.saveWorkspace();assert.equal(h.saves.length,0)
})
test('edits during save stay local; payload and acknowledged content describe only the sent version',async()=>{
  const h=harness();const p=h.saveWorkspace();h.workspaceNotes.value='new';h.workspaceSteps.value[0].status='done'
  assert.equal(h.saves[0].data.notes,'A');assert.equal(h.saves[0].data.steps[0].status,'todo')
  h.saves[0].resolve({revision:4,updated_at:'saved'});await p
  assert.equal(h.workspaceNotes.value,'new');assert.equal(h.workspaceSteps.value[0].status,'done')
  assert.equal(h.workspaceRevision.value,4);assert.notEqual(h.workspaceSavedContent.value,JSON.stringify({notes:h.workspaceNotes.value,steps:h.workspaceSteps.value}))
})
test('a conflict response fetched after switching cannot install A conflict on B',async()=>{
  const h=harness();const p=h.saveWorkspace();h.saves[0].reject({response:{status:409}});await Promise.resolve()
  h.currentSession.value={id:2};h.reads[0].resolve({revision:8,notes:'A latest',steps:[]});await p
  assert.equal(h.workspaceConflict.value,null)
})
test('confirmation to overwrite A cannot write B after navigation',{timeout:1000},async()=>{
  const h=harness();h.workspaceConflict.value={revision:8,notes:'A',steps:[]}
  const p=h.overwriteWithLocal();h.currentSession.value={id:2};h.workspaceConflict.value={revision:20,notes:'B',steps:[]};h.confirmations[0].resolve();await p
  assert.equal(h.saves.length,0);assert.equal(h.workspaceConflict.value.revision,20)
})
