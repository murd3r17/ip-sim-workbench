import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { test } from 'node:test'
const raw=readFileSync(new URL('../src/utils/display.ts',import.meta.url),'utf8')
const code=ts.transpileModule(raw,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
const sandbox={exports:{}};vm.runInNewContext(code,sandbox)
const {executionModeLabel,savedVerificationState}=sandbox.exports
test('current settings and boolean coercion cannot manufacture persisted real execution',()=>{
 for(const mode of [null,undefined,true,false,'true','false','unknown'])assert.match(executionModeLabel(mode),/未记录/)
 assert.equal(executionModeLabel('real'),'真实执行');assert.equal(executionModeLabel('simulated'),'模拟执行')
})
test('simulated success does not become a readback pass',()=>{
 assert.equal(savedVerificationState({execution_mode:'simulated',status:'success',verified:false}),'not_performed')
 assert.equal(savedVerificationState({execution_mode:'simulated',status:'success',verified:true}),'not_performed')
})
test('real unverified success is not relabeled as simulated no-readback',()=>{
 assert.equal(savedVerificationState({execution_mode:'real',status:'success',verified:false}),'unverified')
 assert.equal(savedVerificationState({execution_mode:'real',status:'success',verified:true}),'passed')
})
test('legacy and restored records preserve their original verification boundary',()=>{
 assert.equal(savedVerificationState({status:'success',verified:true}),'unknown')
 assert.equal(savedVerificationState({execution_mode:'real',status:'rolled_back',verified:false}),'failed')
})
