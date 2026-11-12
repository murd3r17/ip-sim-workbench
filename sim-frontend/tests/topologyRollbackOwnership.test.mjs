import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'
const source=readFileSync(new URL('../src/views/device/TopologyView.vue',import.meta.url),'utf8').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const ast=ts.createSourceFile('view.ts',source,ts.ScriptTarget.Latest,true)
const stmt=ast.statements.find(n=>ts.isVariableStatement(n)&&n.declarationList.declarations.some(d=>d.name.getText(ast)==='rollbackVersion'))
const compiled=ts.transpileModule(stmt.getText(ast)+'\nexports.run=rollbackVersion',{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve}}
function harness(){
 const confirmation=deferred(),response=deferred(),calls=[],notices=[],refs={topologyId:{value:1},versionsTarget:{value:1},rollingBack:{value:false}}
 const sandbox={...refs,exports:{},ElMessageBox:{confirm:()=>confirmation.promise},ElMessage:{warning:m=>notices.push(m),success:m=>notices.push(m)},
  rollbackTopologyVersion:(id,v)=>{calls.push(['rollback',id,v]);return response.promise},loadTopology:()=>calls.push(['refresh']),openVersions:()=>calls.push(['versions'])}
 vm.runInNewContext(compiled,sandbox);return{...refs,confirmation,response,calls,notices,run:sandbox.exports.run}
}
test('changing topology while confirmation is open never submits against the new target',{timeout:1000},async()=>{
 const h=harness();const pending=h.run(1);h.topologyId.value=2;h.confirmation.resolve();await pending;assert.equal(h.calls.length,0);assert.match(h.notices[0],/未提交回滚/)
})
test('a completed rollback keeps original identity after navigation and does not reopen versions on another target',{timeout:1000},async()=>{
 const h=harness();const pending=h.run(3);h.confirmation.resolve();await new Promise(setImmediate);h.topologyId.value=2;h.response.resolve();await pending
 assert.deepEqual(h.calls,[['rollback',1,3]]);assert.match(h.notices[0],/原拓扑 #1/)
})
test('unchanged target completes with readback, a pending action cannot double submit',{timeout:1000},async()=>{
 const h=harness();const pending=h.run(3);h.confirmation.resolve();await new Promise(setImmediate);await h.run(3);h.response.resolve();await pending
 assert.deepEqual(h.calls,[['rollback',1,3],['refresh'],['versions']]);assert.equal(h.rollingBack.value,false)
})
import { setImmediate } from 'node:timers'
