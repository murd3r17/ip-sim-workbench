import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'
import {effectScope} from 'vue'
const require=createRequire(import.meta.url),exports={}
const code=ts.transpileModule(readFileSync(new URL('../src/composables/useSnapshotRequest.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
vm.runInNewContext(code,{exports,require})
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{resolve,reject,promise}}
test('failed refresh preserves last data, exposes failure; successful retry clears it',async()=>{
 const state=exports.useSnapshotRequest('设备列表');let data=['old']
 await state.run(()=>Promise.reject(new Error('503')),v=>data=v)
 assert.deepEqual(data,['old']);assert.match(state.error.value,/读取失败.*可能陈旧/);assert.equal(state.loading.value,false)
 await state.run(()=>Promise.resolve(['new']),v=>data=v)
 assert.deepEqual(data,['new']);assert.equal(state.error.value,'')
})
test('late success or failure cannot replace a newer filter result or spinner',async()=>{
 const state=exports.useSnapshotRequest('审批列表');const a=deferred(),b=deferred();let value='saved'
 const first=state.run(()=>a.promise,v=>value=v),second=state.run(()=>b.promise,v=>value=v)
 a.resolve('old-filter');await first;assert.equal(value,'saved');assert.equal(state.loading.value,true)
 b.resolve('new-filter');await second;assert.equal(value,'new-filter')
 const c=deferred(),d=deferred();const third=state.run(()=>c.promise,v=>value=v),fourth=state.run(()=>d.promise,v=>value=v)
 d.resolve('latest');await fourth;c.reject(new Error('late503'));await third;assert.equal(state.error.value,'');assert.equal(value,'latest')
})
test('disposing the component scope discards a late response and rejects further reads',async()=>{
 const scope=effectScope();const state=scope.run(()=>exports.useSnapshotRequest('列表'));let value='saved';const a=deferred()
 const pending=state.run(()=>a.promise,v=>value=v);scope.stop();a.resolve('late');await pending
 assert.equal(value,'saved');let invoked=false;await state.run(async()=>{invoked=true;return'new'},v=>value=v);assert.equal(invoked,false)
})
