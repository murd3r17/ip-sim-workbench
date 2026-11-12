import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {test} from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
function compile(file,require){const sandbox={exports:{},require};vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/utils/'+file+'.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,sandbox);return sandbox.exports}
const datetime=compile('datetime')
const {buildMonitorSeries}=compile('monitorSeries',name=>{assert.equal(name,'./datetime');return datetime})
test('names remain distinct for duplicate hostnames and unknown inventory names',()=>{
 const rows=buildMonitorSeries([{device_id:1,device_name:'R1',time:'2026-11-07T10:00:00',value:0},{device_id:2,device_name:'R1',time:'2026-11-07T10:00:00Z',value:3},{device_id:3,time:'2026-11-07T10:00:00Z',value:4}])
 assert.deepEqual(Array.from(rows,x=>x.name),['R1 · #1','R1 · #2','设备 #3'])
 assert.equal(rows[0].data[0][1],0)
 assert.equal(new Set(rows.map(x=>x.id)).size,3)
})
test('offsets sort by actual instant; invalid or absent samples never become zeros',()=>{
 const rows=buildMonitorSeries([{device_id:1,device_name:'R2',time:'2026-11-07T12:00:00+08:00',value:1},{device_id:1,time:'2026-11-07T05:00:00Z',value:2},{device_id:1,time:'bad',value:3},{device_id:1,time:'2026-11-07T04:00:00Z',value:null},{device_id:1,time:'2026-11-07T04:00:00Z',value:NaN}])
 assert.equal(rows.length,1)
 assert.equal(rows[0].name,'R2')
 assert.deepEqual(Array.from(rows[0].data,x=>x[1]),[1,2])
})
