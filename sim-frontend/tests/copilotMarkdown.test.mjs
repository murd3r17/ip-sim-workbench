import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/utils/markdownLite.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } })
const module = { exports: {} }
new Function('module', 'exports', outputText)(module, module.exports)
const { renderMarkdown } = module.exports

test('full document deep headings render safely without activating embedded markup', () => {
  const html = renderMarkdown('#### 四级 <img src=x onerror=alert(1)>\n##### 五级\n###### 六级\n\n[恶意](javascript:alert(1))')
  assert.match(html, /<h4>四级 &lt;img/)
  assert.match(html, /<h5>五级<\/h5>/)
  assert.match(html, /<h6>六级<\/h6>/)
  assert.ok(!html.includes('<img'))
  assert.ok(!html.includes('<a'))
})

test('review-note citation spelling links to the same immutable source', () => {
  const html = renderMarkdown('DSA 的限制见[1审校]；无效[7审校]。`array[1审校]`', 1)
  assert.match(html, /data-source-index="0"[^>]*>\[1审校\]<\/button>/)
  assert.match(html, /\[7审校 · 无对应来源\]/)
  assert.equal((html.match(/data-source-index=/g) || []).length, 1)
  assert.ok(!renderMarkdown('生成中[1审校]').includes('data-source-index'))
})

test('real model compact n citations retain bounds and leave code literal', () => {
  const html = renderMarkdown('同步协议见[n5]，另一处[N:2]，未知[n9]；`array[n5]`；[node5]', 5)
  assert.match(html, /data-source-index="4"[^>]*>\[5\]<\/button>/)
  assert.match(html, /data-source-index="1"[^>]*>\[2\]<\/button>/)
  assert.match(html, /\[9 · 无对应来源\]/)
  assert.equal((html.match(/data-source-index=/g) || []).length, 2)
  assert.match(html, /<code class="md-inline">array\[n5\]<\/code>/)
  assert.match(html, /\[node5\]/)
  assert.ok(!renderMarkdown('生成中[n5]').includes('data-source-index'))
})

test('spaced editorial labels from real answers retain the original source identity', () => {
  const html = renderMarkdown('条件[4 审校说明]；补充[2审校补充]；未知[9 审校说明]；`a[4 审校说明]`；[4 外部链接]', 4)
  assert.match(html, /data-source-index="3"[^>]*>\[4 审校说明\]<\/button>/)
  assert.match(html, /data-source-index="1"[^>]*>\[2审校补充\]<\/button>/)
  assert.match(html, /\[9 审校说明 · 无对应来源\]/)
  assert.equal((html.match(/data-source-index=/g) || []).length, 2)
  assert.match(html, /<code class="md-inline">a\[4 审校说明\]<\/code>/)
  assert.ok(!renderMarkdown('[4 审校说明]').includes('data-source-index'))
})

test('only existing prose citations become controls; code and untrusted HTML remain literal', () => {
  const html = renderMarkdown('事实 [1] [6] [9]\n\n`array[1]`\n\n```text\na[2]\n```\n\n<img src=x onerror=alert(1)>', 6)
  assert.equal((html.match(/data-source-index=/g) || []).length, 2)
  assert.match(html, /data-source-index="5"/)
  assert.match(html, /\[9 · 无对应来源\]/)
  assert.match(html, /<code class="md-inline">array\[1\]<\/code>/)
  assert.ok(!html.includes('<img'))
})

test('citations in tables are reachable and streaming output has no premature controls', () => {
  assert.match(renderMarkdown('|结论|依据|\n|---|---|\n|内容|[2]|', 2), /data-source-index="1"/)
  assert.ok(!renderMarkdown('尚未完整 [1]').includes('data-source-index'))
})

test('ordinary code fences never create a deployment action', () => {
  for (const lang of ['text', 'cli', 'vrp', 'huawei', 'shell']) {
    const html = renderMarkdown('```' + lang + '\ndisplay ospf peer\n```\n```' + lang + '\ninterface GigabitEthernet0/0/1\nshutdown\n```')
    assert.equal((html.match(/class="code-copy"/g) || []).length, 2)
    assert.ok(!html.includes('code-deploy'))
  }
})

test('completed answers visibly distinguish nonexistent sources without changing code or pending output', () => {
  const html = renderMarkdown('结论[1]，补充[9]。`a[9]`\n```text\na[1]\n```', 1)
  assert.equal((html.match(/data-source-index=/g) || []).length, 1)
  assert.match(html, /class="citation-unmatched"[^>]*>\[9 · 无对应来源\]/)
  assert.match(html, /<code class="md-inline">a\[9\]<\/code>/)
  assert.match(renderMarkdown('结论[1]', 0), /无对应来源/)
  assert.ok(!renderMarkdown('尚在生成[1]').includes('无对应来源'))
  assert.ok(!renderMarkdown('```text\na[1]\n```', 0).includes('无对应来源'))
})

test('real model n-prefixed citations map to the same bounded source without touching code', () => {
  const html = renderMarkdown('内容[n:2]，另一条[2]，错误[n:999]；`a[n:2]`', 2)
  assert.equal((html.match(/data-source-index="1"/g) || []).length, 2)
  assert.match(html, /999 · 无对应来源/)
  assert.match(html, /<code class="md-inline">a\[n:2\]<\/code>/)
  assert.ok(!renderMarkdown('生成中[n:2]').includes('data-source-index'))
})
