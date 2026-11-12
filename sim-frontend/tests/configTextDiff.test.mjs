import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { test } from 'node:test'
const raw=readFileSync(new URL('../src/utils/configTextDiff.ts',import.meta.url),'utf8')
const code=ts.transpileModule(raw,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
const sandbox={exports:{}};vm.runInNewContext(code,sandbox)
const {buildConfigDiff,configDiffContext}=sandbox.exports

test('case-only description changes retain original numbers including ignored comments',()=>{
 const d=buildConfigDiff('\n# section\ninterface GE0/0/1\n description SITE-A','# section\ninterface GE0/0/1\n description site-a')
 const r=d.rows.find(x=>x.kind==='changed')
 assert.equal(r.left.number,4);assert.equal(r.right.number,3);assert.equal(r.left.text,' description SITE-A')
})
test('duplicate lines are not collapsed into a set',()=>{
 const d=buildConfigDiff('interface GE0/0/1\n description duplicate\n description duplicate','interface GE0/0/1\n description duplicate')
 assert.equal(d.counts.removed,1);assert.equal(d.rows.at(-1).left.number,3)
})
test('identical leaves in changed interface context remain visible',()=>{
 const d=buildConfigDiff('interface GE0/0/1\n description same','interface GE0/0/2\n description same')
 assert.equal(d.counts.changed,2);assert.equal(d.rows[1].left.context,'interface GE0/0/1')
})
test('common large prefixes avoid quadratic allocation and preserve final line',()=>{
 const common=Array.from({length:10000},(_,i)=>`description row${i}`).join('\n')
 const d=buildConfigDiff(common+'\ndescription OLD',common+'\ndescription NEW')
 assert.equal(d.positional,false);assert.equal(d.counts.changed,1);assert.equal(d.rows.at(-1).right.number,10001)
})
test('large changed blocks explicitly switch to bounded positional mode',()=>{
 const d=buildConfigDiff('a\nb\nc','d\ne\nf',true,4)
 assert.equal(d.positional,true);assert.equal(d.counts.changed,3)
})
test('credential changes stay hidden in all exported data and cannot prove equality',()=>{
 const secret='D07_'+'PRIVATE_SENTINEL'
 const d=buildConfigDiff(`local-user lab password cipher ${secret}A`,`local-user lab password cipher ${secret}B`)
 assert.equal(d.hiddenCredentials,true);assert.equal(JSON.stringify(d).includes(secret),false);assert.equal(d.counts.changed,0)
})
test('empty local file can be compared to an added configuration',()=>{
 const d=buildConfigDiff('','sysname R1');assert.equal(d.counts.added,1);assert.equal(d.rows[0].right.number,1)
})

test('local routing keys and community credentials stay hidden in source and export',()=>{
 for(const prefix of ['key 1 cipher','community read','snmp-agent community write','authentication-mode md5']) {
  const d=buildConfigDiff('',prefix+' LOCAL_PRIVATE_SENTINEL')
  assert.equal(d.hiddenCredentials,true);assert.equal(JSON.stringify(d).includes('LOCAL_PRIVATE_SENTINEL'),false)
 }
})
test('context filtering retains neighbors rather than only isolated changed strings',()=>{
 const d=buildConfigDiff('description a\ndescription b\ndescription c','description a\ndescription NEW\ndescription c')
 assert.equal(configDiffContext(d.rows).length,3)
})
