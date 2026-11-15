<template>
  <el-dialog v-model="visible" title="资料全文" class="knowledge-reader-dialog" width="min(1200px, 96vw)" top="3vh" destroy-on-close @closed="invalidate">
    <div v-loading="loading" class="knowledge-reader">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon>
        <template #default><el-button link type="primary" @click="load">重试读取</el-button><span>版本改变时请关闭并刷新资料目录。</span></template>
      </el-alert>
      <template v-if="document && !error">
        <header class="reader-summary">
          <h2>{{ document.title || document.filename }}</h2>
          <p>{{ document.book_title || document.book || '其他资料' }}<template v-if="document.edition"> · {{ document.edition }}</template></p>
          <details class="reader-details">
            <summary>资料信息</summary>
            <p>版本 {{ document.version?.slice(0, 12) }} · {{ formatSize(document.size) }}<template v-if="document.page_start"> · PDF 第 {{ document.page_start }}–{{ document.page_end }} 页</template></p>
            <p v-if="document.source_pdf">原教材 {{ document.source_pdf }}</p>
            <p>{{ document.source_path || document.id }}</p>
          </details>
          <el-radio-group v-model="mode" size="small" aria-label="阅读方式">
            <el-radio value="formatted">排版阅读</el-radio><el-radio value="raw">原始文本</el-radio>
          </el-radio-group>
        </header>
        <div v-if="document.subsections?.length" class="reader-subsections">
          <strong>本章小节</strong>
          <el-button v-for="subsection in document.subsections" :key="subsection.id" link type="primary" @click="openSubsection(subsection)">{{ subsection.title }}</el-button>
        </div>
        <p v-if="excerpt && !matchedPart" class="reader-message">当前正文中未能定位原片段。可以从目录继续阅读。</p>
        <div class="reader-layout">
          <label class="reader-chapter">章节
            <select :value="readingSection" @change="jump(($event.target as HTMLSelectElement).value)">
              <option v-for="section in document.sections" :key="section.id" :value="section.id">{{ section.title }}</option>
            </select>
          </label>
          <nav class="reader-toc" aria-label="正文目录">
            <strong>正文目录 · {{ document.sections.length }} 节</strong>
            <button v-for="section in document.sections" :key="section.id" type="button" :style="{ paddingLeft: `${8 + (section.level - 1) * 8}px` }" @click="jump(section.id)">{{ section.title }}</button>
            <span v-if="!document.sections.length">正文无章节标题</span>
          </nav>
          <article ref="body" class="reader-body" tabindex="0" aria-label="资料正文" @scroll.passive="savePosition">
            <el-alert v-for="warning in document.warnings" :key="warning" :title="warning" type="warning" show-icon :closable="false" />
            <details v-for="note in document.reviewed_notes" :key="note.id" class="reader-note">
              <summary>{{ note.title }} · 审校补充</summary>
              <p>{{ note.content }}</p>
              <a v-if="referenceUrl(note.url)" :href="note.url" target="_blank" rel="noopener noreferrer">{{ note.reference }}</a>
              <span v-else>{{ note.reference }}</span>
            </details>
            <section v-for="part in parts" :id="part.id" :key="part.id" :ref="el => remember(part.id, el)"
              :class="{ 'reader-located': part.id === matchedPart }">
              <p v-if="part.id === matchedPart" class="reader-message">本次引用所在章节</p>
              <pre v-if="mode === 'raw'">{{ part.content }}</pre>
              <div v-else class="reader-markdown" v-html="renderMarkdown(formatted(part.content))" />
              <el-button v-if="previewPages.has(part.id)" link type="primary" @click="showFigure(previewPages.get(part.id)!)">查看这页原图</el-button>
            </section>
            <details v-if="document.original_pages?.length" class="reader-original-pages">
              <summary>原教材页位</summary>
              <p>页号从 PDF 第一页计数。可预览的页带有原图入口。</p>
              <div class="reader-pages">
                <template v-for="page in document.original_pages" :key="page.physical">
                  <el-button v-if="page.preview" size="small" plain @click="showFigure(page.physical)">查看第 {{ page.physical }} 页</el-button>
                  <el-button v-else-if="page.section_id" size="small" text @click="jump(page.section_id)">第 {{ page.physical }} 页正文</el-button>
                  <span v-else>第 {{ page.physical }} 页</span>
                </template>
              </div>
            </details>
          </article>
        </div>
      </template>
    </div>
    <template #footer><el-button v-if="previousDocs.length" @click="returnToChapter">返回上一级资料</el-button><el-button type="primary" plain @click="visible = false">返回原页面</el-button></template>
  </el-dialog>
  <el-dialog v-model="figureVisible" :title="'原教材 PDF 第 ' + figurePage + ' 页'" width="min(980px, 96vw)" top="3vh" append-to-body destroy-on-close @closed="clearFigure">
    <div v-loading="figureLoading" class="reader-figure">
      <el-alert v-if="figureError" :title="figureError" type="warning" :closable="false" show-icon />
      <img v-if="figureUrl" :src="figureUrl" :alt="'原教材 PDF 第 ' + figurePage + ' 页'" />
    </div>
    <template #footer><el-button type="primary" plain @click="figureVisible = false">返回正文</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { getKnowledgeOriginalFigure, readKnowledgeDocument, type KnowledgeDocument, type KnowledgeFullDocument } from '../api/knowledge'
import { renderMarkdown } from '../utils/markdownLite'
import { errorResponseMessage } from '../utils/requestError'
const visible = defineModel<boolean>({ default: false })
const props = defineProps<{ documentId?: string; filename?: string; version?: string; excerpt?: string; sectionId?: string; originalPage?: number }>()
const document = ref<KnowledgeFullDocument | null>(null)
const loading = ref(false), error = ref(''), mode = ref('formatted')
const body = ref<HTMLElement | null>(null)
const nodes = new Map<string, HTMLElement>()
const readingSection = ref('')
let epoch = 0
const currentDoc = ref<KnowledgeDocument>(), previousDocs = ref<KnowledgeDocument[]>([])
const figureVisible = ref(false), figurePage = ref(0), figureUrl = ref(''), figureLoading = ref(false), figureError = ref('')
let figureEpoch = 0
const previewPages = computed(() => new Map((document.value?.original_pages || [])
  .filter((page): page is typeof page & { section_id: string } => page.preview && Boolean(page.section_id))
  .map(page => [page.section_id, page.physical])))
function clearFigure() {
  figureEpoch++
  if (figureUrl.value) URL.revokeObjectURL(figureUrl.value)
  figureUrl.value = ''; figureLoading.value = false; figureError.value = ''
}
function invalidate() {
  epoch++; loading.value = false; document.value = null; error.value = ''; nodes.clear()
  currentDoc.value = undefined; previousDocs.value = []; figureVisible.value = false; clearFigure()
}
function openSubsection(section: KnowledgeDocument) {
  if (!document.value) return
  previousDocs.value.push(document.value)
  currentDoc.value = section; void load()
}
function returnToChapter() {
  currentDoc.value = previousDocs.value.pop(); void load()
}
async function showFigure(page: number) {
  const doc = document.value
  if (!doc?.version) return
  clearFigure()
  const request = figureEpoch
  figurePage.value = page; figureVisible.value = true; figureLoading.value = true
  try {
    const blob = await getKnowledgeOriginalFigure({ document_id: doc.id, version: doc.version, page })
    if (request === figureEpoch && figureVisible.value) figureUrl.value = URL.createObjectURL(blob)
  } catch {
    if (request === figureEpoch) figureError.value = '原图读取失败。可用上方的 PDF 页号查阅本地原教材。'
  } finally {
    if (request === figureEpoch) figureLoading.value = false
  }
}
function remember(id: string, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLElement) nodes.set(id, el)
  else nodes.delete(id)
}
function jump(id: string, focus = true) {
  const node = nodes.get(id)
  if (!node || !body.value) return
  readingSection.value = id
  body.value.scrollTop = node.offsetTop
  if (focus) body.value.focus({ preventScroll: true })
}
function positionKey() { return `workbench-reading:${document.value?.id}:${document.value?.version}` }
function savePosition() {
  if (!body.value || !document.value) return
  const current = [...parts.value].reverse().find((part) =>
    (nodes.get(part.id)?.offsetTop ?? Number.POSITIVE_INFINITY) <= body.value!.scrollTop + 12)
  if (!current) return
  readingSection.value = current.id
  try { sessionStorage.setItem(positionKey(), current.id) } catch { /* Storage can be disabled. */ }
}
function referenceUrl(url: string) { return /^https:\/\/www\.rfc-editor\.org\/rfc\/rfc\d+\.html#section-[\d.]+$/.test(url) }
const parts = computed(() => {
  const doc = document.value
  if (!doc) return []
  const lines = doc.content.split('\n')
  const headings = doc.sections.map(s => ({ id: s.id, start: s.line - 1 }))
  if (!headings.length || headings[0]!.start > 0) headings.unshift({ id: 'source-start', start: 0 })
  return headings.map((s, i) => ({ id: s.id, content: lines.slice(s.start, headings[i + 1]?.start ?? lines.length).join('\n') }))
})
const matchedPart = computed(() => {
  if (currentDoc.value && currentDoc.value.id !== props.documentId) return ''
  if (props.sectionId && parts.value.some((part) => part.id === props.sectionId)) return props.sectionId
  if (props.originalPage) {
    const match = document.value?.original_pages?.find(page => page.physical === props.originalPage)
    if (match?.section_id) return match.section_id
  }
  if (!props.excerpt) return ''
  const normalize = (text: string) => text.replace(/\s+/g, '')
  const snippet = normalize(props.excerpt)
  if (snippet.length < 18) return ''
  const matching = parts.value.filter((part) => normalize(part.content).includes(snippet))
  return matching.length === 1 ? matching[0].id : ''
})
function formatted(text: string) {
  const lines = text.split('\n')
  if (lines[0]?.trim() === '# ' + document.value?.title) lines.shift()
  return lines.join('\n').replace(/^```[^\n]*\n((?:[ \t]*\|[^\n]*\n)+)```[ \t]*$/gm, (_, table: string) => {
    return /\|[ \t]*:?-{3,}/.test(table) ? table.trim() : _
  })
}
function formatSize(bytes?: number) { return bytes == null ? '大小未知' : bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB` }
async function load() {
  const current = ++epoch
  document.value = null; error.value = ''; loading.value = true; nodes.clear()
  try {
    const result = await readKnowledgeDocument({ document_id: currentDoc.value?.id || props.documentId || undefined,
      filename: currentDoc.value ? undefined : props.filename || undefined, version: currentDoc.value?.version || props.version || undefined })
    if (current === epoch && visible.value) {
      document.value = result
      await nextTick()
      if (current !== epoch || !visible.value) return
      let saved = ''
      try { saved = sessionStorage.getItem(positionKey()) || '' } catch { /* Storage can be disabled. */ }
      jump(matchedPart.value || saved || parts.value[0]?.id || '', false)
    }
  } catch (err) { if (current === epoch && visible.value) error.value = errorResponseMessage(err, '正文读取失败，请稍后重试。') }
  finally { if (current === epoch) loading.value = false }
}
watch(() => [visible.value, props.documentId, props.filename, props.version, props.sectionId, props.excerpt, props.originalPage], () => {
  if (visible.value) { mode.value = 'formatted'; void load() } else invalidate()
}, { immediate: true })
onUnmounted(invalidate)
</script>

<style scoped>
.knowledge-reader { min-height: 140px; min-width: 0; }
.reader-summary { font-size: 12px; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
.reader-summary h2 { margin: 0 0 6px; font-size: 19px; color: var(--el-text-color-primary); }
.reader-summary p { margin: 4px 0; }
.reader-summary .el-radio-group { margin: 8px 0 12px; }
.reader-layout { display: grid; grid-template-columns: minmax(150px, 24%) minmax(0, 1fr); gap: 18px; }
.reader-toc { max-height: 52vh; overflow: auto; display: flex; flex-direction: column; border-right: 1px solid var(--el-border-color); font-size: 12px; }
.reader-toc strong { margin-bottom: 8px; }
.reader-toc button { flex-shrink: 0; background: transparent; border: 0; text-align: left; padding: 7px 10px; color: var(--el-text-color-primary); cursor: pointer; overflow-wrap: anywhere; }
.reader-toc button:hover, .reader-toc button:focus-visible { color: var(--el-color-primary); background: var(--el-fill-color-light); }
.reader-body { position: relative; max-height: 58vh; overflow: auto; min-width: 0; padding-right: 8px; line-height: 1.8; color: var(--el-text-color-primary); }
.reader-details summary, .reader-note summary { cursor: pointer; }
.reader-note { padding: 8px 10px; margin-bottom: 8px; background: var(--v7b-surface-2); }
.reader-located { padding-inline: 10px; border-inline-start: 3px solid var(--v7b-accent); }
.reader-message { color: var(--v7b-muted); font-size: 13px; }
.reader-chapter { display: none; }
.reader-body pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.7 monospace; margin: 0; }
.reader-markdown :deep(h1) { font-size: 22px; }
.reader-markdown :deep(h2) { font-size: 19px; }
.reader-markdown :deep(h3), .reader-markdown :deep(h4) { font-size: 16px; }
.reader-markdown { overflow-wrap: anywhere; }
.reader-markdown :deep(.md-table-wrap) { overflow-x: auto; max-width: 100%; }
.reader-markdown :deep(table) { border-collapse: collapse; font-size: 13px; min-width: 100%; }
.reader-markdown :deep(td), .reader-markdown :deep(th) { border: 1px solid var(--el-border-color); padding: 7px 9px; text-align: left; min-width: 6em; }
.reader-markdown :deep(th) { background: var(--el-fill-color-light); }
.reader-markdown :deep(pre) { white-space: pre; overflow: auto; background: var(--el-fill-color-light); padding: 12px; }
.reader-markdown :deep(.code-toolbar) { display: none; }
.reader-subsections, .reader-pages { display: flex; gap: 8px 16px; flex-wrap: wrap; align-items: center; }
.reader-subsections { padding: 10px 0; }
.reader-pages { margin: 12px 0; }
.reader-original-pages { border-top: 1px solid var(--el-border-color); margin-top: 12px; padding-top: 12px; }
.reader-figure { overflow: auto; max-height: calc(85vh - 100px); }
.reader-figure img { display: block; max-width: 100%; margin: 0 auto; }
@media (max-width: 700px) {
  .reader-layout { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .reader-toc { display: none; }
  .reader-chapter { display: grid; gap: 4px; }
  .reader-chapter select { min-width: 0; max-width: 100%; padding: 6px; }
  .reader-body { max-height: 50vh; }
}
</style>
<style>
.knowledge-reader-dialog { display: flex; flex-direction: column; max-height: 94vh; overflow: hidden; --el-text-color-primary: var(--v7b-text); --el-text-color-regular: var(--v7b-muted); --el-text-color-secondary: var(--v7b-muted); --el-fill-color-light: var(--v7b-surface-2); --el-border-color: var(--v7b-line); --el-mask-color: rgba(255, 255, 255, .85); }
.knowledge-reader-dialog .el-dialog__header, .knowledge-reader-dialog .el-dialog__footer { flex-shrink: 0; }
.knowledge-reader-dialog .el-dialog__body { min-height: 0; overflow: auto; }
</style>
