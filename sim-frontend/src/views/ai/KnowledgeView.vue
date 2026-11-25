<template>
  <div class="knowledge-view">
    <header class="knowledge-header">
      <div><h2>知识库</h2><p>按教材和章节阅读资料，或检索书名、原句和技术问题。</p></div>
      <el-button type="primary" plain :loading="docsLoading || healthLoading" @click="refresh">刷新资料状态</el-button>
    </header>
    <div class="knowledge-health" aria-live="polite">
      <el-tag :type="searchStatus.available ? 'success' : healthLoading ? 'info' : 'warning'">{{ searchStatus.available ? '检索可用' : healthLoading ? '正在检查检索' : '检索待检查' }}</el-tag>
      <span v-if="searchStatus.provider">{{ searchStatus.provider }}</span>
      <span v-if="searchStatus.edition" :title="searchStatus.edition">教材版本 {{ searchStatus.edition.slice(0, 12) }}</span>
      <span>{{ catalog ? catalogSummary : docsLoading ? '正在读取教材目录' : docsError ? '目录暂不可用' : '目录待加载' }}</span>
      <span v-if="catalog">核对 {{ localTime(catalog.checked_at) }}</span>
    </div>
    <el-alert v-if="searchStatus.reason" :title="searchStatus.reason" type="info" show-icon :closable="false" />
    <el-alert v-if="knowledgeError" :title="knowledgeError" type="error" show-icon :closable="false" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="资料目录" name="docs">
        <div class="catalog-filters">
          <el-input v-model="filter" clearable placeholder="筛选标题、文件名或教材" aria-label="筛选资料" />
          <el-select v-model="book" clearable placeholder="全部教材" aria-label="教材分组">
            <el-option v-for="group in books" :key="group.key" :label="`${group.label}（${group.count}）`" :value="group.key" />
          </el-select>
          <el-checkbox v-if="subsectionsCount" v-model="showSubsections">显示小节入口</el-checkbox>
          <span v-if="catalog">{{ filteredDocuments.length }} 条</span>
          <el-button plain @click="searchBody">按正文检索</el-button>
        </div>
        <el-table :data="filteredDocuments" v-loading="docsLoading" row-key="id" class="catalog-table">
          <template #empty><el-empty :description="docsError || (filter || book ? '没有符合筛选条件的资料' : '当前没有资料，请管理员核对同步。')" :image-size="72" /></template>
          <el-table-column label="章节 / 资料" min-width="250">
            <template #default="{ row }"><el-button link type="primary" class="document-title" @click="openDocument(row)">{{ row.title || row.filename }}</el-button><div class="document-secondary" v-if="row.page_start">{{ row.catalog_kind === 'subsection' ? '小节 · ' : '' }}PDF 第 {{ row.page_start }}–{{ row.page_end }} 页</div><div class="document-secondary" v-else-if="row.readable">{{ row.section_count ?? 0 }} 节</div></template>
          </el-table-column>
          <el-table-column label="教材" min-width="210"><template #default="{ row }">{{ row.book_title || row.book || '其他资料' }}</template></el-table-column>
          <el-table-column label="操作" width="125"><template #default="{ row }">
            <el-button link type="primary" @click="openDocument(row)">{{ readingAction(row) }}</el-button>
            <AdminAction v-if="!row.bundled && !String(row.id).startsWith('corpus-')" v-slot="{ disabled }"><el-dropdown trigger="click"><el-button link :disabled="disabled" aria-label="资料更多操作">更多</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item :disabled="disabled" @click="handleDelete(row)">删除文档</el-dropdown-item></el-dropdown-menu></template></el-dropdown></AdminAction>
          </template></el-table-column>
        </el-table>
        <p class="knowledge-tip">{{ originalLookupUnavailable || '目录筛选用于找章节。已核对的原书页位可在阅读器中查看。' }}</p>
      </el-tab-pane>
      <el-tab-pane label="检索资料" name="search">
        <el-radio-group v-if="searchStatus.edition" v-model="searchMode" aria-label="检索范围" :disabled="searchLoading" @change="resetSearchResults">
          <el-radio-button value="body">教材正文</el-radio-button>
          <el-radio-button value="original" :disabled="Boolean(originalLookupUnavailable)">原书原句</el-radio-button>
        </el-radio-group>
        <div v-if="searchBooks.length" class="search-books">
          <el-select v-model="searchBook" placeholder="全部教材" clearable aria-label="检索教材范围" :disabled="searchLoading" @change="resetSearchResults">
            <el-option v-for="group in searchBooks" :key="group.key" :label="group.label" :value="group.key" />
          </el-select>
        </div>
        <div class="search-form"><el-input v-model="searchQuery" type="textarea" :rows="2" :placeholder="searchMode === 'original' ? '粘贴 PDF 内连续的原句' : '输入章名、关键词或问题（Ctrl+Enter 检索）'" aria-label="检索关键词" @keydown.ctrl.enter.prevent="handleSearch" @keydown.meta.enter.prevent="handleSearch" /><el-button type="primary" :loading="searchLoading" :disabled="searchMode === 'original' && Boolean(originalLookupUnavailable)" @click="handleSearch">检索</el-button></div>
        <p v-if="originalLookupUnavailable" class="knowledge-tip">{{ originalLookupUnavailable }}</p>
        <p v-else-if="searchMode === 'original'" class="knowledge-tip">粘贴原句找对应 PDF 页。{{ originalLookupStatus?.scan_available ? '标为「扫描定位」的结果请打开原页核对。' : '当前使用 PDF 可选文字。' }}</p>
        <p v-else-if="originalLookupStatus?.state === 'ready'" class="knowledge-tip">教材正文查整理稿。手上有从 PDF 复制的原句，可以切换到「原书原句」找页。</p>
        <el-alert v-if="searchError" :title="searchError" type="error" show-icon :closable="false" />
        <el-button v-if="originalQuoteRetry && !searchLoading && !searchError" link type="primary" @click="retryOriginalQuote">查找原书中的这句</el-button>
        <el-empty v-if="searched && !searchResults.length && !originalResults.length && !searchLoading && !searchError" :description="searchMode === 'original' ? '没有找到这段原句。可缩短原句，或切换到教材正文检索。' : '整理稿中未检索到相关片段。可换关键词或查看资料目录。'" :image-size="72" />
        <el-card v-for="result in originalResults" :key="`${result.document_id}:${result.page}`" shadow="never" class="search-result">
          <header>
            <strong>{{ result.title }}</strong>
            <el-button link type="primary" @click="openOriginal(result)">查看原页</el-button>
          </header>
          <p class="document-secondary">{{ result.book_title }} · {{ result.edition }} · PDF 第 {{ result.page }} 页<template v-if="result.match_type === 'scan_locator'"> · 扫描定位</template></p>
        </el-card>
        <p v-if="searchResults.length" class="knowledge-tip">结果按本次查询的匹配程度排序。请打开片段核对内容。</p>
        <el-card v-for="(result, i) in searchResults" :key="i" shadow="never" class="search-result">
          <header>
            <strong>{{ result.title || result.filename || '检索片段' }}</strong>
            <span>
              <el-button v-if="hasEditionLocation(result)" link type="primary" @click="openResult(result)">打开定位</el-button>
              <el-button link type="primary" @click="openCitation(result)">片段详情</el-button>
            </span>
          </header>
          <p v-if="resultLocation(result)" class="document-secondary">{{ resultLocation(result) }}</p>
          <p v-for="note in result.reviewed_notes" :key="note.id"><strong>{{ note.title }}</strong> · {{ note.content }}</p>
          <template v-if="resultOutputTable(result)">
            <p v-if="result.partial_readonly_table" class="document-secondary">以下是匹配的回显行，可打开同版正文查看完整回显。</p>
            <pre class="search-output" tabindex="0" aria-label="教材回显表格">{{ resultOutputTable(result) }}</pre>
          </template>
          <p v-else class="search-excerpt">{{ resultExcerpt(result) }}</p>
        </el-card>
      </el-tab-pane>
    </el-tabs>
    <el-drawer v-model="citationVisible" title="检索片段" size="min(620px, 96vw)" @closed="citation = null">
      <template v-if="citation">
        <h3>{{ citation.title || citation.filename || '知识资料' }}</h3>
        <p v-if="resultLocation(citation)">{{ resultLocation(citation) }}</p>
        <pre v-if="resultOutputTable(citation)" class="citation-text search-output" tabindex="0" aria-label="教材回显表格">{{ resultOutputTable(citation) }}</pre>
        <pre v-else class="citation-text">{{ citation.text || citation.content || '未附正文' }}</pre>
        <el-button v-if="citationAction.kind === 'read'" type="primary" @click="openSearchDocument">
          {{ citationAction.label }}
        </el-button>
        <p v-else class="knowledge-tip" role="status">{{ citationAction.label }}</p>
        <el-button v-if="citationAction.kind === 'retry'" @click="loadDocuments">重新读取目录</el-button>
        <el-button v-if="citationAction.kind === 'catalog'" @click="findCitationInCatalog">去资料目录</el-button>
      </template>
      <template #footer><el-button @click="citationVisible = false">返回检索结果</el-button></template>
    </el-drawer>
    <KnowledgeDocumentReader v-model="readerVisible" :document-id="readerId" :filename="readerFilename" :version="readerVersion"
      :excerpt="readerExcerpt" :section-id="readerSection" :original-page="readerPage"
      :open-original="readerOpenOriginal" :edition-version="readerEdition" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { deleteKnowledgeDocument, getKnowledgeCatalog, getKnowledgeHealth, searchKnowledge, searchOriginalQuote, type KnowledgeDocument, type KnowledgeHealth, type KnowledgeSearchResult, type KnowledgeCatalog, type OriginalQuoteResult } from '../../api/knowledge'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import { errorResponseMessage } from '../../utils/requestError'
import AdminAction from '../../components/AdminAction.vue'
import KnowledgeDocumentReader from '../../components/KnowledgeDocumentReader.vue'
import { originalQuoteForLookup } from '../../utils/knowledgeSearchInput'
const copilot = useAiCopilotStore()
const activeTab = ref('docs'), filter = ref(''), book = ref('')
const searchBook = ref('')
const showSubsections = ref(false)
const catalog = ref<KnowledgeCatalog | null>(null), knowledgeHealth = ref<KnowledgeHealth | null>(null)
const docsLoading = ref(false), healthLoading = ref(false), docsError = ref('')
const citationVisible = ref(false), citation = ref<KnowledgeSearchResult | null>(null)
const readerVisible = ref(false), readerId = ref(''), readerFilename = ref(''), readerVersion = ref('')
const readerExcerpt = ref(''), readerSection = ref('')
const readerPage = ref<number>()
const readerEdition = ref(''), readerOpenOriginal = ref(false)
let alive = true, docsEpoch = 0, searchEpoch = 0
const books = computed(() => {
  const groups = new Map<string, { key: string; label: string; count: number }>()
  for (const d of catalog.value?.documents || []) {
    if (d.catalog_kind === 'subsection') continue
    const key = d.book || 'other', group = groups.get(key) || { key, label: d.book_title || d.book || '其他资料', count: 0 }
    group.count++; groups.set(key, group)
  }
  return [...groups.values()]
})
const searchStatus = computed(() => {
  const actual = knowledgeHealth.value || catalog.value
  const provider = actual?.search_provider || actual?.provider
  const reason = actual?.search_fallback_reason === 'workspace_mismatch'
    ? '已用当前教材的本机索引检索。配置的向量库属于另一版资料。'
    : actual?.search_fallback_reason === 'provider_unavailable' ? '向量检索暂不可用，当前使用同版教材的本机索引。' : ''
  return {
    provider: provider === 'local' ? '本机索引' : provider,
    available: actual?.search_available ?? knowledgeHealth.value?.available ?? false,
    edition: actual?.active_edition,
    reason: actual?.search_fallback ? reason : '',
  }
})
const searchBooks = computed(() => searchStatus.value.edition ? books.value.filter(group => /^huawei-b\d+$/.test(group.key)) : [])
const originalLookupStatus = computed(() => knowledgeHealth.value?.original_quote_status ?? catalog.value?.original_quote_status)
const originalLookupUnavailable = computed(() => {
  switch (originalLookupStatus.value?.state) {
    case 'unmounted': return '本机未挂载原书 PDF，暂不能查找原书原句。可阅读目录中已有的整理资料。'
    case 'index_needed': return '原书原句需要管理员为本版原书建立索引。已开放的原页仍可从阅读器查看。'
    default: return ''
  }
})
const knowledgeError = computed(() => docsError.value || (searchStatus.value.available ? '' : knowledgeHealth.value?.error || ''))
const subsectionsCount = computed(() => catalog.value?.documents.filter(doc => doc.catalog_kind === 'subsection').length || 0)
const catalogSummary = computed(() => {
  const chapters = catalog.value?.documents.filter(doc => doc.catalog_kind === 'chapter').length || 0
  return chapters
    ? `${chapters} 个教材章节 · ${subsectionsCount.value} 个章内阅读入口`
    : `${catalog.value?.count || 0} 篇资料 · ${catalog.value?.readable_count || 0} 篇可读全文`
})
const filteredDocuments = computed(() => (catalog.value?.documents || []).filter(d => (showSubsections.value || filter.value.trim() || d.catalog_kind !== 'subsection')
  && (!book.value || (d.book || 'other') === book.value)
  && (!filter.value.trim() || [d.title, d.filename, d.book_title, d.book].join(' ').toLowerCase().includes(filter.value.trim().toLowerCase()))))
function localTime(value?: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '时间未知' }
function readingAction(doc: KnowledgeDocument) {
  if (!doc.readable) return '查看原因'
  if (doc.bundled && doc.source_status !== 'edition') return '查看随包整理稿'
  if (doc.reading_kind === 'body') return '阅读正文'
  if (doc.reading_kind === 'guide') return '查看导读'
  if (doc.reading_kind === 'excerpt') return '查看摘录'
  return '阅读资料'
}
function openDocument(doc: KnowledgeDocument) {
  readerId.value = doc.id; readerFilename.value = ''; readerVersion.value = doc.version || ''
  readerExcerpt.value = ''; readerSection.value = ''; readerPage.value = undefined
  readerEdition.value = ''; readerOpenOriginal.value = false; readerVisible.value = true
}
function openCitation(result: KnowledgeSearchResult) { citation.value = result; citationVisible.value = true }
const readableCitation = computed(() => {
  const source = citation.value
  if (!source?.document_id && !source?.filename) return undefined
  const documents = catalog.value?.documents || []
  const matches = documents.filter(document => source.document_id
    ? document.id === source.document_id
    : document.filename === source.filename)
  return matches.length === 1 && matches[0].readable ? matches[0] : undefined
})
function hasEditionLocation(source: KnowledgeSearchResult) {
  return Boolean(source.document_id && source.document_version && source.edition_version)
}
const citationAction = computed(() => {
  if (citation.value && hasEditionLocation(citation.value)) return { kind: 'read', label: '阅读同版正文' }
  if (docsLoading.value) return { kind: 'loading', label: '正在目录中查找可读资料。' }
  if (docsError.value) return { kind: 'retry', label: '目录读取失败，当前仍可阅读本片段。' }
  const document = readableCitation.value
  if (document) return { kind: 'read', label: document.bundled && document.source_status !== 'edition' ? '查看随包整理稿' : '查看当前全文' }
  return { kind: 'catalog', label: '目录中没有找到可核对的全文，当前仍可阅读本片段。' }
})
function resultExcerpt(result: KnowledgeSearchResult) {
  const raw = result.text || result.content || ''
  const text = raw.replace(/^\s*#{1,6}\s+.*$/gm, '').replace(/\*\*/g, '').replace(/\s+/g, ' ').trim()
  return text ? text.slice(0, 360) + (text.length > 360 ? '…' : '') : '查看片段详情'
}
function resultOutputTable(result: KnowledgeSearchResult) {
  const raw = (result.text || result.content || '').trim()
  if (raw.length > 1200) return ''
  const output = raw.match(/^(?:#{1,6} [^\r\n]+\r?\n\s*)?```(?:text|cli)?\r?\n([\s\S]+?)\r?\n```$/u)?.[1]
  if (!output || output.includes('```')) return ''
  return result.partial_readonly_table || /^\s*Instance[ \t]+VLANs?[ \t]+Mapped\s*$/im.test(output) ? output : ''
}
function resultLocation(result: KnowledgeSearchResult) {
  return [result.book_title, result.edition, result.page && hasEditionLocation(result) ? `PDF 第 ${result.page} 页` : '']
    .filter(Boolean).join(' · ')
}
function openSearchDocument() {
  const source = citation.value
  if (!source || citationAction.value.kind !== 'read') return
  openResult(source, hasEditionLocation(source) ? undefined : readableCitation.value)
}
function openResult(source: KnowledgeSearchResult, catalogEntry?: KnowledgeDocument) {
  const editionLocation = hasEditionLocation(source)
  readerId.value = catalogEntry?.id || source.document_id || ''
  readerFilename.value = String(source.filename || source.title || '')
  readerVersion.value = String(catalogEntry?.version || (editionLocation ? source.document_version : '') || '')
  readerSection.value = editionLocation ? String(source.section_id || '') : ''
  readerExcerpt.value = String(source.text || source.content || '')
  readerPage.value = editionLocation ? source.page ?? undefined : undefined
  readerEdition.value = editionLocation ? String(source.edition_version) : ''
  readerOpenOriginal.value = false
  readerVisible.value = true
}
function openOriginal(result: OriginalQuoteResult) {
  readerId.value = result.document_id; readerVersion.value = result.document_version; readerFilename.value = ''
  readerExcerpt.value = ''; readerSection.value = ''; readerPage.value = result.page
  readerEdition.value = originalEdition.value; readerOpenOriginal.value = true; readerVisible.value = true
}
function findCitationInCatalog() {
  filter.value = citation.value?.title || citation.value?.filename || ''
  book.value = ''
  activeTab.value = 'docs'
  citationVisible.value = false
}
async function loadDocuments() {
  const current = ++docsEpoch; docsLoading.value = true
  try { const result = await getKnowledgeCatalog(); if (alive && current === docsEpoch) { catalog.value = result; docsError.value = '' } }
  catch (err) { if (alive && current === docsEpoch) { catalog.value = null; docsError.value = errorResponseMessage(err, '目录读取失败，不是空库。') } }
  finally { if (alive && current === docsEpoch) docsLoading.value = false }
}
async function loadHealth() {
  healthLoading.value = true
  try { const result = await getKnowledgeHealth(); if (alive) { knowledgeHealth.value = result; copilot.setNotes(`知识库 provider=${result.provider || '-'}；available=${result.available}；docs=${result.document_count ?? '-'}`) } }
  catch (err) { if (alive) knowledgeHealth.value = { available: false, error: errorResponseMessage(err, '知识服务状态读取失败。') } }
  finally { if (alive) healthLoading.value = false }
}
function refresh() { void loadDocuments(); void loadHealth() }
async function handleDelete(doc: KnowledgeDocument) {
  try {
    await ElMessageBox.confirm(`删除「${doc.title || doc.filename}」？资料将退出知识库，关联引用可能无法再核验。`, '删除文档', { type: 'warning' })
    const result = await deleteKnowledgeDocument(doc.id) as unknown as { status?: string; error?: string }
    if (result.status && !['ok', 'success'].includes(result.status)) { ElMessage.warning(result.error || '删除未完成'); return }
    ElMessage.success('删除成功'); refresh()
  } catch { /* 取消或请求拦截器已提示 */ }
}
const searchQuery = ref(''), searchResults = ref<KnowledgeSearchResult[]>([]), searchLoading = ref(false), searched = ref(false), searchError = ref('')
const searchMode = ref<'body' | 'original'>('body')
const originalResults = ref<OriginalQuoteResult[]>([]), originalEdition = ref('')
const submittedSearch = ref('')
const originalQuoteRetry = computed(() => {
  if (originalLookupStatus.value?.state !== 'ready' || searchMode.value !== 'body') return ''
  if (submittedSearch.value !== searchQuery.value.trim()) return ''
  return originalQuoteForLookup(submittedSearch.value)
})
function resetSearchResults() {
  copilot.clearPageRecord('original_page')
  searched.value = false; searchError.value = ''; searchResults.value = []
  originalResults.value = []; originalEdition.value = ''; submittedSearch.value = ''
}
function searchBody() {
  if (searchLoading.value) return
  searchMode.value = 'body'; resetSearchResults()
  if (filter.value.trim()) searchQuery.value = filter.value.trim()
  searchBook.value = searchBooks.value.some(group => group.key === book.value) ? book.value : ''
  activeTab.value = 'search'
  if (filter.value.trim()) void handleSearch()
}
function retryOriginalQuote() {
  const quote = originalQuoteRetry.value
  if (!quote) return
  searchQuery.value = quote
  searchMode.value = 'original'
  void handleSearch()
}
async function handleSearch() {
  if (!searchQuery.value.trim() || searchLoading.value) return
  if (searchMode.value === 'original' && originalLookupUnavailable.value) return
  const current = ++searchEpoch
  resetSearchResults(); searchLoading.value = true; searched.value = true
  const scope = searchBooks.value.find(group => group.key === searchBook.value)
  const input = searchQuery.value.trim()
  submittedSearch.value = input
  try {
    if (searchMode.value === 'original') {
      const result = await searchOriginalQuote({ quote: input, book: scope ? Number(scope.key.slice(8)) : undefined })
      if (alive && current === searchEpoch) {
        originalResults.value = result.results; originalEdition.value = result.edition
      }
    } else {
      const result = await searchKnowledge({ question: scope ? `《${scope.label}》${input}` : input })
      if (alive && current === searchEpoch) searchResults.value = result
    }
  }
  catch (err) { if (alive && current === searchEpoch) searchError.value = errorResponseMessage(err, '检索失败，不是空结果。') }
  finally { if (alive && current === searchEpoch) searchLoading.value = false }
}
onMounted(refresh)
onUnmounted(() => { alive = false; docsEpoch++; searchEpoch++ })
</script>

<style scoped>
.knowledge-view { min-width: 0; color: var(--v7b-text); --el-text-color-primary: var(--v7b-text); --el-text-color-regular: var(--v7b-muted); --el-text-color-secondary: var(--v7b-muted); --el-fill-color-light: var(--v7b-surface-2); --el-mask-color: rgba(255, 255, 255, .85); }
.knowledge-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }
.knowledge-header h2 { margin: 0; font-size: 24px; }
.knowledge-header p, .knowledge-tip, .document-secondary { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; }
.knowledge-health { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 14px 0; font-size: 12px; }
.catalog-filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 12px 0; font-size: 12px; }
.catalog-filters .el-input { width: min(340px, 100%); }
.catalog-filters .el-select { width: min(360px, 100%); }
.catalog-table { width: 100%; }
.document-title { max-width: 100%; height: auto; text-align: left; white-space: normal; line-height: 1.7; }
.document-title :deep(span) { white-space: normal; overflow-wrap: anywhere; }
.document-secondary { overflow-wrap: anywhere; }
.search-form { display: flex; align-items: flex-end; gap: 12px; margin: 12px 0 18px; max-width: 900px; }
.search-result { margin-bottom: 12px; }
.search-result header { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; font-size: 13px; }
.search-result header span { color: var(--el-text-color-secondary); }
.search-result pre, .citation-text { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; font-size: 13px; line-height: 1.8; }
.citation-text { padding: 12px; background: var(--el-fill-color-light); border: 1px solid var(--el-border-color); }
.search-result .search-output, .citation-text.search-output { font-family: ui-monospace, Consolas, monospace; white-space: pre; overflow-x: auto; line-height: 1.55; }
.search-result .search-output { padding: 8px 10px; background: var(--el-fill-color-light); }
</style>
