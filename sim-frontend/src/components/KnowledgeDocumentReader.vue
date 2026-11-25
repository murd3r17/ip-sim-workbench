<template>
  <el-dialog v-model="visible" :title="readerTitle" class="knowledge-reader-dialog" width="min(1200px, 96vw)" top="3vh" append-to-body destroy-on-close @closed="invalidate">
    <div v-loading="loading" class="knowledge-reader">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon>
        <template #default><el-button link type="primary" @click="load">重试读取</el-button><span>版本改变时请关闭并刷新资料目录。</span></template>
      </el-alert>
      <template v-if="document && !error">
        <header class="reader-summary">
          <h2>{{ document.title || document.filename }}</h2>
          <p>{{ document.book_title || document.book || '其他资料' }}<template v-if="document.edition"> · {{ document.edition }}</template></p>
          <p v-if="suppliedDraft">可阅读随包整理资料。这份资料没有已核对的原书 PDF 页位。</p>
          <p v-else-if="document.reading_kind === 'body'">这是按原书页位整理的正文。</p>
          <p v-else-if="document.reading_kind === 'guide'">从本章小节进入整理内容。</p>
          <p v-else-if="document.reading_kind === 'excerpt'">此处提供教材摘录。</p>
          <p v-if="originalPageNotice">{{ originalPageNotice }}</p>
          <p v-if="document.historical_edition">当前打开的是这条引用发布时的教材整理版。</p>
          <details class="reader-details">
            <summary>资料信息</summary>
            <p>版本 {{ document.version?.slice(0, 12) }} · {{ formatSize(document.size) }}<template v-if="document.edition_version && document.page_start"> · PDF 第 {{ document.page_start }}–{{ document.page_end }} 页</template></p>
            <p v-if="document.source_pdf">原教材文件名 {{ document.source_pdf }}</p>
            <p>{{ document.source_path || document.id }}</p>
          </details>
          <el-radio-group v-model="mode" size="small" aria-label="阅读方式">
            <el-radio value="formatted">排版阅读</el-radio><el-radio value="raw">整理稿文本</el-radio>
          </el-radio-group>
        </header>
        <div v-if="document.subsections?.length" class="reader-subsections">
          <strong>本章小节</strong>
          <el-button v-for="subsection in document.subsections" :key="subsection.id" link type="primary" @click="openSubsection(subsection)">{{ subsection.title }}</el-button>
        </div>
        <p v-if="excerpt && !readingLocation" class="reader-message">当前正文中未能定位原片段。可以从目录继续阅读。</p>
        <div class="reader-layout">
          <label class="reader-chapter">章节
            <select :value="activeOutlineSection" @change="jump(($event.target as HTMLSelectElement).value)">
              <option v-for="section in outlineSections" :key="section.id" :value="section.id">{{ section.title }}</option>
            </select>
          </label>
          <nav class="reader-toc" aria-label="正文目录">
            <strong>正文目录</strong>
            <button v-for="section in outlineSections" :key="section.id" type="button" :style="{ paddingLeft: `${8 + (section.level - 1) * 8}px` }" @click="jump(section.id)">{{ section.title }}</button>
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
              :class="{ 'reader-located': part.id === readingLocation?.id }">
              <p v-if="part.id === readingLocation?.id" class="reader-message">
                <template v-if="readingLocation.page">PDF 第 {{ readingLocation.page }} 页 · </template>{{ readingLocation.excerpt ? '命中段落' : readingLocation.page ? '定位到本页开头' : '定位到本节' }}
              </p>
              <pre v-if="mode === 'raw'">{{ part.content }}</pre>
              <div v-else class="reader-markdown" v-html="formattedParts.get(part.id)" />
              <el-button v-if="previewPages.has(part.id)" link type="primary" @click="showFigure(previewPages.get(part.id)!)">查看这页原图</el-button>
              <el-button v-else-if="part.id === readingLocation?.id && matchedOriginal?.preview" link type="primary"
                @click="showFigure(matchedOriginal.physical)">查看这页原图</el-button>
            </section>
            <details v-if="document.original_pages?.length" class="reader-original-pages">
              <summary>原教材页位</summary>
              <p>页号从 PDF 第一页计数。选择页号可查看原书页面或对应整理稿。</p>
              <div class="reader-pages">
                <template v-for="page in document.original_pages" :key="page.physical">
                  <el-button v-if="page.preview" size="small" plain :title="page.printed_hint" @click="showFigure(page.physical)">查看第 {{ page.physical }} 页</el-button>
                  <el-button v-else-if="page.section_id" size="small" text :title="pageStatus(page)" @click="showEditorialPage(page)">第 {{ page.physical }} 页整理稿</el-button>
                  <span v-else :title="pageStatus(page)">第 {{ page.physical }} 页</span>
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
    <div class="reader-figure-controls" aria-label="原书页操作">
      <el-button :disabled="!previousPage" @click="showFigure(previousPage!.physical)">上一页</el-button>
      <el-button :disabled="!nextPage" @click="showFigure(nextPage!.physical)">下一页</el-button>
      <el-button :disabled="!figureUrl" @click="figureZoomed = !figureZoomed">{{ figureZoomed ? '适合窗口' : '放大' }}</el-button>
      <span v-if="figurePageInfo?.original_status === 'saved_preview'">存档原页预览</span>
    </div>
    <div v-loading="figureLoading" class="reader-figure">
      <el-alert v-if="figureError" :title="figureError" type="warning" :closable="false" show-icon />
      <img v-if="figureUrl" :class="{ 'reader-figure-zoomed': figureZoomed }" :src="figureUrl" :alt="'原教材 PDF 第 ' + figurePage + ' 页'" />
    </div>
    <template #footer><el-button type="primary" plain @click="figureVisible = false">返回正文</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { isAxiosError } from 'axios'
import { getKnowledgeOriginalFigure, readKnowledgeDocument, type KnowledgeDocument, type KnowledgeFullDocument, type KnowledgeOriginalPage } from '../api/knowledge'
import { renderMarkdown } from '../utils/markdownLite'
import { errorResponseMessage, extractErrorMessage } from '../utils/requestError'
import { useAiCopilotStore } from '../stores/aiCopilot'
import { findKnowledgeReadingLocation } from '../utils/knowledgeReadingLocation'
const visible = defineModel<boolean>({ default: false })
const copilot = useAiCopilotStore()
const props = defineProps<{
  documentId?: string; filename?: string; version?: string; editionVersion?: string
  excerpt?: string; sectionId?: string; originalPage?: number; requirePage?: boolean; openOriginal?: boolean
}>()
const document = ref<KnowledgeFullDocument | null>(null)
const suppliedDraft = computed(() => Boolean(document.value?.bundled && !document.value.edition_version))
const originalPageNotice = computed(() => {
  if (!document.value?.edition_version) return ''
  const pages = document.value.original_pages || []
  const canPreview = pages.some(page => page.preview)
  if (pages.some(page => page.original_status === 'original_not_mounted')) {
    return canPreview ? '原书 PDF 未挂载。带查看按钮的页仍可打开随附原图。' : '原书 PDF 未挂载。当前可按已核对页位阅读整理稿。'
  }
  return canPreview ? '可以在「原教材页位」打开有原图的页面。' : '当前没有可查看的原书页图。'
})
const readerTitle = computed(() => {
  if (suppliedDraft.value) return '随包整理稿'
  switch (document.value?.reading_kind) {
    case 'body': return '教材正文'
    case 'guide': return '章节导读'
    case 'excerpt': return '教材摘录'
    default: return '阅读资料'
  }
})
const loading = ref(false), error = ref(''), mode = ref('formatted')
const body = ref<HTMLElement | null>(null)
const nodes = new Map<string, HTMLElement>()
const readingSection = ref('')
const outlineSections = computed(() => {
  const sections = document.value?.sections || []
  if (document.value?.reading_kind !== 'body') return sections
  const headings = sections.filter(section => !/^PDF 第 \d+ 页/.test(section.title))
  return headings.length > 1 ? headings : sections
})
const activeOutlineSection = computed(() => {
  const current = document.value?.sections.find(section => section.id === readingSection.value)
  return [...outlineSections.value].reverse().find(section => section.line <= (current?.line ?? 0))?.id || ''
})
let epoch = 0
const currentDoc = ref<KnowledgeDocument>(), previousDocs = ref<KnowledgeDocument[]>([])
const figureVisible = ref(false), figurePage = ref(0), figureUrl = ref(''), figureLoading = ref(false), figureError = ref('')
const figureZoomed = ref(false)
const figurePageInfo = computed(() => document.value?.original_pages?.find(page => page.physical === figurePage.value))
const previousPage = computed(() => document.value?.original_pages?.find(page => page.preview && page.physical === figurePage.value - 1))
const nextPage = computed(() => document.value?.original_pages?.find(page => page.preview && page.physical === figurePage.value + 1))
let figureEpoch = 0
const previewPages = computed(() => new Map((document.value?.original_pages || [])
  .filter((page): page is typeof page & { section_id: string } => page.preview && Boolean(page.section_id))
  .map(page => [page.section_id, page.physical])))
function clearFigure() {
  figureEpoch++
  if (figureUrl.value) URL.revokeObjectURL(figureUrl.value)
  figureUrl.value = ''; figureLoading.value = false; figureError.value = ''; figureZoomed.value = false
}

function pageStatus(page: KnowledgeOriginalPage) {
  switch (page.original_status) {
    case 'editorial_only': return '本页原图未开放，可核对同版整理稿。'
    case 'original_not_mounted': return '尚未挂载这本书的原版 PDF。'
    case 'original_version_mismatch': return '已挂载的 PDF 与登记版本不同。'
    case 'original_unavailable': return '原件暂不可读取。'
    default: return '工作台未提供本页原图，可按物理页号查阅教材。'
  }
}
function rememberPage(page: number) {
  const doc = document.value
  if (!doc?.version) return
  copilot.setPageRecord({ kind:'original_page', document_id:doc.id, version:doc.version, page }, `教材 PDF 第 ${page} 页`)
}
function showEditorialPage(page: KnowledgeOriginalPage) {
  rememberPage(page.physical)
  if (page.section_id) jump(page.section_id)
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
  figurePage.value = page; figureVisible.value = true
  const pageInfo = doc.original_pages?.find(entry => entry.physical === page)
  if (pageInfo) rememberPage(page)
  if (!pageInfo?.preview) {
    figureError.value = pageInfo ? pageStatus(pageInfo) : '这份资料没有该原页的位置。'
    return
  }
  figureLoading.value = true
  try {
    const blob = await getKnowledgeOriginalFigure({ document_id: doc.id, version: doc.version, page })
    if (request === figureEpoch && figureVisible.value) figureUrl.value = URL.createObjectURL(blob)
  } catch (err) {
    let message = '原图读取失败。可用上方的 PDF 页号查阅本地原教材。'
    if (isAxiosError(err) && err.response?.data instanceof Blob) {
      try { message = extractErrorMessage(JSON.parse(await err.response.data.text()), message) } catch { /* Keep the general notice. */ }
    }
    if (request === figureEpoch) figureError.value = message
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
  saveReadingSection(id)
  body.value.scrollTop = node.offsetTop
  if (focus) body.value.focus({ preventScroll: true })
}
function positionKey() { return `workbench-reading:${document.value?.id}:${document.value?.version}` }
function savePosition() {
  if (!body.value || !document.value) return
  const current = [...parts.value].reverse().find((part) =>
    (nodes.get(part.id)?.offsetTop ?? Number.POSITIVE_INFINITY) <= body.value!.scrollTop + 12)
  if (!current || readingSection.value === current.id) return
  readingSection.value = current.id
  saveReadingSection(current.id)
}
function saveReadingSection(id: string) {
  try { sessionStorage.setItem(positionKey(), id) } catch { /* Storage can be disabled. */ }
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
const formattedParts = computed(() => new Map(parts.value.map(part => [part.id, renderMarkdown(formatted(part.content))])))
const readingLocation = computed(() => {
  if (currentDoc.value && currentDoc.value.id !== props.documentId) return undefined
  return findKnowledgeReadingLocation(parts.value, document.value?.original_pages || [], props)
})
const matchedOriginal = computed(() => document.value?.original_pages?.find(page =>
  page.physical === readingLocation.value?.page))
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
  copilot.clearPageRecord('original_page')
  document.value = null; error.value = ''; loading.value = true; nodes.clear()
  try {
    const result = await readKnowledgeDocument({ document_id: currentDoc.value?.id || props.documentId || undefined,
      filename: currentDoc.value ? undefined : props.filename || undefined, version: currentDoc.value?.version || props.version || undefined })
    if (current === epoch && visible.value) {
      if (props.editionVersion && result.edition_version !== props.editionVersion) {
        error.value = '资料版次已更新。请返回来源重新核对原页。'
        return
      }
      const followCitation = (props.requirePage || props.openOriginal) && (!currentDoc.value || currentDoc.value.id === props.documentId)
      const target = followCitation ? result.original_pages?.find(page => page.physical === props.originalPage) : undefined
      if (followCitation && !target?.section_id && !target?.preview) {
        error.value = `PDF 第 ${props.originalPage} 页当前无法回读。可返回查看原回答保存的片段。`
        return
      }
      document.value = result
      await nextTick()
      if (current !== epoch || !visible.value) return
      let saved = ''
      try { saved = sessionStorage.getItem(positionKey()) || '' } catch { /* Storage can be disabled. */ }
      jump(readingLocation.value?.id || saved || parts.value[0]?.id || '', false)
      if (target) rememberPage(target.physical)
      if (target && (props.openOriginal || (target.preview && !target.section_id))) void showFigure(target.physical)
    }
  } catch (err) { if (current === epoch && visible.value) error.value = errorResponseMessage(err, '正文读取失败，请稍后重试。') }
  finally { if (current === epoch) loading.value = false }
}
watch(() => [visible.value, props.documentId, props.filename, props.version, props.editionVersion,
  props.sectionId, props.excerpt, props.originalPage, props.requirePage, props.openOriginal], () => {
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
.reader-figure-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }
.reader-figure-controls :deep(.el-button + .el-button) { margin: 0; }
.reader-figure { overflow: auto; min-height: 96px; max-height: calc(85vh - 150px); }
.reader-figure img { display: block; max-width: 100%; margin: 0 auto; }
.reader-figure img.reader-figure-zoomed { width: 150%; max-width: none; }
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
