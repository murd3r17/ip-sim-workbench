import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {test} from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
const raw=readFileSync(new URL('../src/utils/recordOrigin.ts',import.meta.url),'utf8')
const sandbox={exports:{}};vm.runInNewContext(ts.transpileModule(raw,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,sandbox)
const {filterByRecordOrigin,recordOrigin}=sandbox.exports
test('unknown/legacy remain in all and named tests do not imply origin',()=>{
 const rows=[{id:1,name:'test mock',record_origin:'normal'},{id:2,name:'日常维护',record_origin:'test'},{id:3,name:'normal',execution_mode:'simulated'},{id:4,record_origin:'future'}]
 assert.equal(recordOrigin(rows[0]),'normal');assert.equal(recordOrigin(rows[2]),'unknown')
 assert.deepEqual(filterByRecordOrigin(rows,'test').map(x=>x.id),[2])
 assert.deepEqual(filterByRecordOrigin(rows,'unknown').map(x=>x.id),[3,4])
 assert.equal(filterByRecordOrigin(rows,'all').length,4);assert.equal(rows.length,4)
})
