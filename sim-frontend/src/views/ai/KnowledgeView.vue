<template>
  <div class="knowledge-view">
    <header class="knowledge-header">
      <div><h2>知识库</h2><p>按教材和章节阅读原文，或检索相关片段。问答仍在右侧助手继续。</p></div>
      <el-button type="primary" plain :loading="docsLoading || healthLoading" @click="refresh">刷新资料状态</el-button>
    </header>
    <div class="knowledge-health">
      <el-tag :type="knowledgeHealth?.available ? 'success' : 'warning'">{{ knowledgeHealth?.available ? '知识服务可用' : '知识服务待检查' }}</el-tag>
      <span>{{ knowledgeHealth?.provider || catalog?.provider || '提供方未知' }}</span>
      <span>{{ catalog ? `${catalog.count} 篇资料 · ${catalog.readable_count} 篇可读全文` : docsError ? '目录暂不可用' : '目录待加载' }}</span>
      <span v-if="catalog">核对 {{ localTime(catalog.checked_at) }}</span>
    </div>
    <el-alert v-if="docsError || knowledgeHealth?.error" :title="docsError || knowledgeHealth?.error || ''" type="error" show-icon :closable="false" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="资料目录" name="docs">
        <div class="catalog-filters">
          <el-input v-model="filter" clearable placeholder="筛选标题、文件名或教材" aria-label="筛选资料" />
          <el-select v-model="book" clearable placeholder="全部教材" aria-label="教材分组">
            <el-option v-for="group in books" :key="group.key" :label="`${group.label}（${group.count}）`" :value="group.key" />
          </el-select>
          <span>{{ catalog ? `${filteredDocuments.length} / ${catalog.count} 篇` : '数量未知' }}</span>
        </div>
        <el-table :data="filteredDocuments" v-loading="docsLoading" row-key="id" class="catalog-table">
          <template #empty><el-empty :description="docsError || (filter || book ? '没有符合筛选条件的资料' : '当前没有资料，请管理员核对同步。')" :image-size="72" /></template>
          <el-table-column label="章节 / 资料" min-width="250">
            <template #default="{ row }"><el-button link type="primary" class="document-title" @click="openDocument(row)">{{ row.title || row.filename }}</el-button><div class="document-secondary">{{ row.filename }}</div><div class="document-secondary">{{ row.source_path || row.doc_id || row.id }}</div></template>
          </el-table-column>
          <el-table-column label="教材" min-width="210"><template #default="{ row }">{{ row.book_title || row.book || '其他资料' }}</template></el-table-column>
          <el-table-column label="源文件" min-width="160"><template #default="{ row }"><div>{{ row.readable ? `全文 · ${row.section_count ?? 0} 节` : '全文待核对' }}</div><div class="document-secondary">{{ formatSize(row.size) }} · 页码{{ row.page == null ? '未知' : row.page }}</div></template></el-table-column>
          <el-table-column label="版本 / 源更新时间" min-width="170"><template #default="{ row }"><code>{{ row.version?.slice(0, 12) || '版本未知' }}</code><div class="document-secondary">{{ localTime(row.modified_at) }}</div></template></el-table-column>
          <el-table-column label="操作" width="125"><template #default="{ row }">
            <el-button link type="primary" @click="openDocument(row)">{{ row.readable ? '阅读全文' : '查看原因' }}</el-button>
            <AdminAction v-if="!String(row.id).startsWith('corpus-')" v-slot="{ disabled }"><el-dropdown trigger="click"><el-button link :disabled="disabled" aria-label="资料更多操作">更多</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item :disabled="disabled" @click="handleDelete(row)">删除文档</el-dropdown-item></el-dropdown-menu></template></el-dropdown></AdminAction>
          </template></el-table-column>
        </el-table>
        <p class="knowledge-tip">章节来自当前知识工作区；大小与版本取自可核验的持久源文件。“源更新时间”不是入库时间。教材同步由管理员维护，临时文件请用助手的「文件」。</p>
      </el-tab-pane>
      <el-tab-pane label="检索资料" name="search">
        <div class="search-form"><el-input v-model="searchQuery" type="textarea" :rows="2" placeholder="输入关键词（Ctrl+Enter 检索）" aria-label="检索关键词" @keydown.ctrl.enter.prevent="handleSearch" @keydown.meta.enter.prevent="handleSearch" /><el-button type="primary" :loading="searchLoading" @click="handleSearch">检索</el-button></div>
        <el-alert v-if="searchError" :title="searchError" type="error" show-icon :closable="false" />
        <el-empty v-if="searched && !searchResults.length && !searchLoading && !searchError" description="未检索到相关片段，可换关键词或查看资料目录。" :image-size="72" />
        <el-card v-for="(result, i) in searchResults" :key="i" shadow="never" class="search-result">
          <header><strong>{{ result.title || result.filename || '检索片段' }}</strong><span>相关度 {{ ((result.score || 0) * 100).toFixed(1) }}%</span><el-button link type="primary" @click="openCitation(result)">片段详情</el-button></header>
          <pre>{{ result.text || result.content || '未附片段' }}</pre>
        </el-card>
      </el-tab-pane>
    </el-tabs>
    <el-drawer v-model="citationVisible" title="检索片段" size="min(620px, 96vw)" @closed="citation = null">
      <template v-if="citation"><h3>{{ citation.title || citation.filename || '知识资料' }}</h3><p>{{ citation.filename || '未提供文件名' }} · 页码{{ citation.page || '未知' }}</p><pre class="citation-text">{{ citation.text || citation.content || '未附正文' }}</pre><p class="knowledge-tip">这是本次检索返回的片段。下方另行读取当前源文件全文，不视为原回答采用的版本。</p><el-button type="primary" @click="openSearchDocument">阅读当前全文</el-button></template>
      <template #footer><el-button @click="citationVisible = false">返回检索结果</el-button></template>
    </el-drawer>
    <KnowledgeDocumentReader v-model="readerVisible" :document-id="readerId" :filename="readerFilename" :version="readerVersion" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { deleteKnowledgeDocument, getKnowledgeCatalog, getKnowledgeHealth, searchKnowledge, type KnowledgeDocument, type KnowledgeHealth, type KnowledgeSearchResult, type KnowledgeCatalog } from '../../api/knowledge'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import { errorResponseMessage } from '../../utils/requestError'
import AdminAction from '../../components/AdminAction.vue'
import KnowledgeDocumentReader from '../../components/KnowledgeDocumentReader.vue'
const copilot = useAiCopilotStore()
const activeTab = ref('docs'), filter = ref(''), book = ref('')
const catalog = ref<KnowledgeCatalog | null>(null), knowledgeHealth = ref<KnowledgeHealth | null>(null)
const docsLoading = ref(false), healthLoading = ref(false), docsError = ref('')
const citationVisible = ref(false), citation = ref<KnowledgeSearchResult | null>(null)
const readerVisible = ref(false), readerId = ref(''), readerFilename = ref(''), readerVersion = ref('')
let alive = true, docsEpoch = 0, searchEpoch = 0
const books = computed(() => {
  const groups = new Map<string, { key: string; label: string; count: number }>()
  for (const d of catalog.value?.documents || []) {
    const key = d.book || 'other', group = groups.get(key) || { key, label: d.book_title || d.book || '其他资料', count: 0 }
    group.count++; groups.set(key, group)
  }
  return [...groups.values()]
})
const filteredDocuments = computed(() => (catalog.value?.documents || []).filter(d => (!book.value || (d.book || 'other') === book.value)
  && (!filter.value.trim() || [d.title, d.filename, d.book_title, d.book].join(' ').toLowerCase().includes(filter.value.trim().toLowerCase()))))
function formatSize(bytes?: number) { return bytes == null ? '大小未知' : bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB` }
function localTime(value?: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '时间未知' }
function openDocument(doc: KnowledgeDocument) { readerId.value = doc.id; readerFilename.value = ''; readerVersion.value = doc.version || ''; readerVisible.value = true }
function openCitation(result: KnowledgeSearchResult) { citation.value = result; citationVisible.value = true }
function openSearchDocument() {
  const source = citation.value
  if (!source) return
  readerId.value = typeof source.document_id === 'string' ? source.document_id : ''
  readerFilename.value = String(source.filename || source.title || '')
  readerVersion.value = ''; readerVisible.value = true
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
async function handleSearch() {
  if (!searchQuery.value.trim() || searchLoading.value) return
  const current = ++searchEpoch; searchLoading.value = true; searched.value = true; searchError.value = ''; searchResults.value = []
  try { const result = await searchKnowledge({ question: searchQuery.value }); if (alive && current === searchEpoch) searchResults.value = result }
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
</style>
