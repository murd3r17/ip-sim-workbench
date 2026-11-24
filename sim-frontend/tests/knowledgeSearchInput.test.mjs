import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/utils/knowledgeSearchInput.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } })
const module = { exports: {} }
new Function('module', 'exports', outputText)(module, module.exports)
const { originalQuoteForLookup } = module.exports

test('offers original-page lookup for a pasted quote and explicit requests to find it', () => {
  const quote = '阐明在多路访问网络中接入多台路由器时的邻居关系建立过程'
  for (const input of [`“${quote}”。`, `请定位原书中的原句：“${quote}”`, `"${quote}"这句在原版 PDF 哪一页？`]) {
    assert.equal(originalQuoteForLookup(input), quote, input)
  }
})

test('leaves technical explanations, multiple quotes and stated book or page constraints with the original query', () => {
  const quote = '路由器在共享网络中建立邻居关系'
  for (const input of [
    `解释“${quote}”的机制`,
    `请定位原书《网络基础》：“${quote}”`,
    `请在 PDF 第 41 页解释“${quote}”`,
    `“${quote}”与“另一个设备如何建立邻居”分别指什么`,
    `不要查原书“${quote}”`,
    '“邻居关系”',
  ]) assert.equal(originalQuoteForLookup(input), '')
})
