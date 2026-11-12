import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
const source=readFileSync(new URL('../src/views/monitor/MonitorDashboardView.vue',import.meta.url),'utf8').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const ast=ts.createSourceFile('monitor.ts',source,ts.ScriptTarget.Latest,true)
const statements=ast.statements.filter(n=>ts.isVariableStatement(n)&&n.declarationList.declarations.some(d=>['loadInspectionTasks','loadChartData'].includes(d.name.getText(ast))))
assert.equal(statements.length,2)
const code=ts.transpileModule(statements.map(s=>s.getText(ast)).join('\n')+'\nexports={loadInspectionTasks,loadChartData};',{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{resolve,reject,promise}}
function harness(){
 const chart=[],task=[];const h={exports:{},chartReqSeq:0,inspectReqSeq:0,selectedTopology:{value:1},inspectionTasks:{value:['saved']},inspectionError:{value:''},chartError:{value:''},trendData:{value:{metrics:{cpu_usage:['saved']}}},getMonitorTasks(){const d=deferred();task.push(d);return d.promise},getMonitorTrends(){const d=deferred();chart.push(d);return d.promise},updateCpuChart(){},updateMemoryChart(){},updateInterfaceChart(){},updateOspfChart(){},latestMetricValue(){return 0},notifyRequestError(){}}
 vm.runInNewContext(code,h);return{h,chart,task}
}
test('failed same-target chart and inspection refresh preserve successful saved snapshots',async()=>{
 const{h,chart,task}=harness();const a=h.exports.loadChartData(),b=h.exports.loadInspectionTasks();chart[0].reject(Error('offline'));task[0].reject(Error('offline'));await Promise.all([a,b]);assert.equal(h.trendData.value.metrics.cpu_usage[0],'saved');assert.equal(h.inspectionTasks.value[0],'saved');assert.match(h.chartError.value,/陈旧/);assert.match(h.inspectionError.value,/陈旧/)
})
test('late previous-target charts and tasks cannot replace the new target',async()=>{
 const{h,chart,task}=harness();const a=h.exports.loadChartData(),b=h.exports.loadInspectionTasks();h.selectedTopology.value=2;const c=h.exports.loadChartData(),d=h.exports.loadInspectionTasks();const next={metrics:{cpu_usage:['new']}};chart[1].resolve(next);task[1].resolve(['new']);await Promise.all([c,d]);chart[0].resolve({metrics:{cpu_usage:['old']}});task[0].reject(Error('old failure'));await Promise.all([a,b]);assert.equal(h.trendData.value,next);assert.equal(h.inspectionTasks.value[0],'new');assert.equal(h.inspectionError.value,'')
})
test('no target does not issue unscoped trend or task requests',async()=>{
 const{h,chart,task}=harness();h.selectedTopology.value=null;await h.exports.loadChartData();await h.exports.loadInspectionTasks();assert.equal(chart.length,0);assert.equal(task.length,0)
})
