import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const vue = await readFile(new URL('../src/views/ai/KnowledgeView.vue', import.meta.url), 'utf8')
const script = vue.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const { outputText } = ts.transpileModule(script + `
export { loadDocuments, openCitation, openSearchDocument, citationAction, resultLocation,
  readerVisible, readerId, readerVersion, readerEdition, readerPage, readerOpenOriginal };
`, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })

function knowledgeView(getKnowledgeCatalog) {
  const dependencies = {
    vue: { ref: value => ({ value }), computed: read => ({ get value() { return read() } }), onMounted() {}, onUnmounted() {} },
    '../../api/knowledge': { getKnowledgeCatalog },
    '../../stores/aiCopilot': { useAiCopilotStore: () => ({}) },
    '../../utils/requestError': { errorResponseMessage: (_, fallback) => fallback },
  }
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(name => dependencies[name] ?? {}, module, module.exports)
  return module.exports
}

const source = { document_id: 'corpus-a', document_version: 'legacy-file-version', filename: 'chapter.md', page: 9 }
const supplied = { id: 'corpus-a', version: 'verified-file-version', filename: 'chapter.md', readable: true, bundled: true }

test('a late catalog verifies the bundled reading action before opening a file, never a PDF page', async () => {
  let resolve
  const view = knowledgeView(() => new Promise(done => { resolve = done }))
  const pending = view.loadDocuments()
  view.openCitation(source)
  assert.equal(view.citationAction.value.kind, 'loading')
  view.openSearchDocument()
  assert.equal(view.readerVisible.value, false)
  assert.doesNotMatch(view.resultLocation(source), /PDF/)
  resolve({ documents: [supplied] })
  await pending
  assert.deepEqual(view.citationAction.value, { kind: 'read', label: '查看随包整理稿' })
  view.openSearchDocument()
  assert.equal(view.readerId.value, supplied.id)
  assert.equal(view.readerVersion.value, supplied.version)
  assert.equal(view.readerPage.value, undefined)
  assert.equal(view.readerEdition.value, '')
})

test('a failed catalog can retry, and a loaded catalog without a readable match offers directory search', async () => {
  const replies = [() => Promise.reject(new Error('offline')), async () => ({ documents: [{ ...supplied, readable: false }] })]
  const view = knowledgeView(() => replies.shift()())
  view.openCitation(source)
  await view.loadDocuments()
  assert.equal(view.citationAction.value.kind, 'retry')
  await view.loadDocuments()
  assert.equal(view.citationAction.value.kind, 'catalog')
  assert.match(vue, /citationAction.kind === 'retry'[^>]*@click="loadDocuments"/)
  assert.match(vue, /citationAction.kind === 'catalog'[^>]*@click="findCitationInCatalog"/)
})

test('verified edition coordinates work during a directory request and open the matching editorial page', async () => {
  const view = knowledgeView(async () => ({ documents: [] }))
  const pending = view.loadDocuments()
  const reviewed = { ...source, edition_version: 'reading-edition' }
  view.openCitation(reviewed)
  assert.deepEqual(view.citationAction.value, { kind: 'read', label: '阅读同版正文' })
  assert.match(view.resultLocation(reviewed), /PDF 第 9 页/)
  view.openSearchDocument()
  assert.equal(view.readerEdition.value, reviewed.edition_version)
  assert.equal(view.readerVersion.value, reviewed.document_version)
  assert.equal(view.readerPage.value, 9)
  assert.equal(view.readerOpenOriginal.value, false)
  await pending
})
