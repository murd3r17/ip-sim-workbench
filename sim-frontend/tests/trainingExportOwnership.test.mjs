import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
const vue=readFileSync(new URL('../src/views/training/TrainingLabView.vue',import.meta.url),'utf8')
const source=vue.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const ast=ts.createSourceFile('view.ts',source,ts.ScriptTarget.Latest,true)
const fn=ast.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='handleExportRecord')
const code=ts.transpileModule(fn.getText(ast),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText
function harness(){
 const calls=[],downloads=[],refs={currentSession:{value:{id:1}},trainingReport:{value:{version:2}},exporting:{value:false},exportError:{value:''}}
 const request=(kind,id,version)=>new Promise((resolve,reject)=>calls.push({kind,id,version,resolve,reject}))
 const deps={...refs,exportLogsJsonl:id=>request('jsonl',id),exportTrainingSession:(id,v)=>request('session',id,v),Blob,
  URL:{createObjectURL:blob=>{downloads.push({blob});return 'owned-blob'},revokeObjectURL(){}},
  document:{createElement:()=>({click(){Object.assign(downloads.at(-1),{filename:this.download})}})},notifyRequestError(){}}
 const methods=new Function(...Object.keys(deps),'let sessionSelectionSeq=0,exportRequestSeq=0;'+code+';return{run:handleExportRecord,close(){sessionSelectionSeq++;exportRequestSeq++;exporting.value=false}}')(...Object.values(deps))
 return {...refs,...methods,calls,downloads}
}
test('download pins sent session/version while current displayed version changes',async()=>{
 const h=harness();const pending=h.run('session');h.trainingReport.value={version:3}
 assert.deepEqual([h.calls[0].id,h.calls[0].version],[1,2]);h.calls[0].resolve({session:{id:1},report:{version:2}});await pending
 assert.match(h.downloads[0].filename,/session_1_report_v2.json/);assert.equal(JSON.parse(await h.downloads[0].blob.text()).report.version,2)
})
test('closing or switching the session discards late export and does not clear a new export spinner',async()=>{
 const h=harness();const a=h.run('session');h.close();h.currentSession.value={id:2};const b=h.run('jsonl')
 h.calls[0].resolve({session:{id:1},report:{version:2}});await a;assert.equal(h.downloads.length,0);assert.equal(h.exporting.value,true)
 h.calls[1].resolve('{"id":2}\n');await b;assert.equal(h.downloads[0].filename,'session_2_logs.jsonl')
})
test('failed and mismatched exports do not download or retry silently',async()=>{
 const h=harness();const a=h.run('session');h.calls[0].resolve({session:{id:9},report:{version:2}});await a
 assert.equal(h.downloads.length,0);assert.match(h.exportError.value,/导出失败/);assert.equal(h.calls.length,1)
 const b=h.run('session');h.calls[1].reject(new Error('503'));await b;assert.equal(h.downloads.length,0);assert.equal(h.calls.length,2)
 const c=h.run('session');h.calls[2].resolve({session:{id:1},report:{version:2}});await c;assert.equal(h.exportError.value,'');assert.equal(h.downloads.length,1)
})
