import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {test} from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
const sandbox={exports:{}}
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/utils/display.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,sandbox)
const {observationStatusLabel,observationCompletenessLabel,observationModeLabel}=sandbox.exports
test('missing, unknown and partial observation fields cannot appear successful or real',()=>{
 for(const value of [undefined,'unknown','partial','empty','future']){
  assert.notEqual(observationStatusLabel(value),'读取成功')
  assert.notEqual(observationCompletenessLabel(value),'输出完整')
  assert.notEqual(observationModeLabel(value),'真实读取')
 }
 assert.equal(observationModeLabel('sim'),'模拟读取')
 assert.equal(observationModeLabel('simulated'),'模拟读取')
 assert.equal(observationStatusLabel('future'),'future')
 assert.equal(observationCompletenessLabel('future'),'future')
})
