import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/utils/knowledgeReadingLocation.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } })
const module = { exports: {} }
new Function('module', 'exports', outputText)(module, module.exports)
const { findKnowledgeReadingLocation } = module.exports

const evidence = '设备在五个周期内未收到心跳后发免费 ARP，交换机更新自己的 MAC 地址表。'
const parts = [
  { id: 'page-46', content: '### PDF 第 46 页' },
  { id: 'section-a', content: `#### 故障动作\n\n${evidence}` },
  { id: 'page-47', content: '### PDF 第 47 页' },
  { id: 'section-b', content: `#### 恢复动作\n\n${evidence}` },
]
const pages = [
  { physical: 46, section_id: 'page-46' },
  { physical: 47, section_id: 'page-47' },
]

test('each identical paragraph lands within its cited physical page', () => {
  assert.deepEqual(findKnowledgeReadingLocation(parts, pages, { originalPage: 46, excerpt: evidence }),
    { id: 'section-a', page: 46, excerpt: true })
  assert.deepEqual(findKnowledgeReadingLocation(parts, pages, { originalPage: 47, excerpt: evidence }),
    { id: 'section-b', page: 47, excerpt: true })
})

test('a reproducible route table excerpt can skip irrelevant rows in the same section', () => {
  const header = 'Destination         Cost Type        NextHop'
  const row = '10.5.0.0/24           2 Inter-area  10.0.24.4'
  const longerPart = { id: 'section-a', content: `#### 路由表\n\n\`\`\`text\n${header}\n10.1.0.0/24 1 Stub 10.0.24.1\n${row}\n\`\`\`` }
  assert.deepEqual(findKnowledgeReadingLocation([parts[0], longerPart, ...parts.slice(2)], pages, {
    originalPage: 46, excerpt: `${header}\n${row}`,
  }), { id: 'section-a', page: 46, excerpt: true })
})

test('missing excerpts and older page-only links mark the physical page rather than a paragraph', () => {
  for (const options of [{ excerpt: '本页未展示的测试语句，但上一页或者下一页可能有类似文字。' }, { requirePage: true }]) {
    assert.deepEqual(findKnowledgeReadingLocation(parts, pages, { ...options, originalPage: 46 }),
      { id: 'page-46', page: 46, excerpt: false })
  }
  assert.equal(findKnowledgeReadingLocation(parts, pages, { originalPage: 99, excerpt: evidence }), undefined)
})
