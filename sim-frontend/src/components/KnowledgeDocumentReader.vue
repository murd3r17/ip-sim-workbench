<template>
  <el-dialog v-model="visible" title="资料全文" class="knowledge-reader-dialog" width="min(1200px, 96vw)" top="3vh" destroy-on-close @closed="invalidate">
    <div v-loading="loading" class="knowledge-reader">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon>
        <template #default><el-button link type="primary" @click="load">重试读取</el-button><span>版本改变时请关闭并刷新资料目录。</span></template>
      </el-alert>
      <template v-if="document && !error">
        <header class="reader-summary">
          <h2>{{ document.title || document.filename }}</h2>
          <p>{{ document.book_title || document.book || '其他资料' }} · {{ document.filename }}</p>
          <p>资料编号 {{ document.id }}<span v-if="document.source_path"> · {{ document.source_path }}</span></p>
          <p>当前全文 · 版本 {{ document.version?.slice(0, 12) }} · {{ formatSize(document.size) }} · 页码未映射</p>
          <p v-if="document.source_pdf">原教材：{{ document.source_pdf }}</p>
          <p>{{ document.message }}</p>
          <el-radio-group v-model="mode" size="small" aria-label="阅读方式">
            <el-radio value="formatted">排版阅读</el-radio><el-radio value="raw">原始文本</el-radio>
          </el-radio-group>
        </header>
        <div class="reader-layout">
          <nav class="reader-toc" aria-label="正文目录">
            <strong>正文目录 · {{ document.sections.length }} 节</strong>
            <button v-for="section in document.sections" :key="section.id" type="button" :style="{ paddingLeft: `${8 + (section.level - 1) * 8}px` }" @click="jump(section.id)">{{ section.title }}</button>
            <span v-if="!document.sections.length">正文无章节标题</span>
          </nav>
          <article ref="body" class="reader-body" tabindex="0" aria-label="资料正文">
            <section v-for="part in parts" :id="part.id" :key="part.id" :ref="el => remember(part.id, el)">
              <pre v-if="mode === 'raw'">{{ part.content }}</pre>
              <div v-else class="reader-markdown" v-html="renderMarkdown(part.content)" />
            </section>
          </article>
        </div>
      </template>
    </div>
    <template #footer><el-button type="primary" plain @click="visible = false">返回原页面</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { readKnowledgeDocument, type KnowledgeFullDocument } from '../api/knowledge'
import { renderMarkdown } from '../utils/markdownLite'
import { errorResponseMessage } from '../utils/requestError'
const visible = defineModel<boolean>({ default: false })
const props = defineProps<{ documentId?: string; filename?: string; version?: string }>()
const document = ref<KnowledgeFullDocument | null>(null)
const loading = ref(false), error = ref(''), mode = ref('formatted')
const body = ref<HTMLElement | null>(null)
const nodes = new Map<string, HTMLElement>()
let epoch = 0
function invalidate() { epoch++; loading.value = false; document.value = null; error.value = ''; nodes.clear() }
function remember(id: string, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLElement) nodes.set(id, el)
  else nodes.delete(id)
}
function jump(id: string) { nodes.get(id)?.scrollIntoView({ block: 'start', behavior: 'auto' }); body.value?.focus({ preventScroll: true }) }
const parts = computed(() => {
  const doc = document.value
  if (!doc) return []
  const lines = doc.content.split('\n')
  const headings = doc.sections.map(s => ({ id: s.id, start: s.line - 1 }))
  if (!headings.length || headings[0]!.start > 0) headings.unshift({ id: 'source-start', start: 0 })
  return headings.map((s, i) => ({ id: s.id, content: lines.slice(s.start, headings[i + 1]?.start ?? lines.length).join('\n') }))
})
function formatSize(bytes?: number) { return bytes == null ? '大小未知' : bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB` }
async function load() {
  const current = ++epoch
  document.value = null; error.value = ''; loading.value = true; nodes.clear()
  try {
    const result = await readKnowledgeDocument({ document_id: props.documentId || undefined, filename: props.filename || undefined, version: props.version || undefined })
    if (current === epoch && visible.value) document.value = result
  } catch (err) { if (current === epoch && visible.value) error.value = errorResponseMessage(err, '正文读取失败，请稍后重试。') }
  finally { if (current === epoch) loading.value = false }
}
watch(() => [visible.value, props.documentId, props.filename, props.version], () => {
  if (visible.value) { mode.value = 'formatted'; void load() } else invalidate()
}, { immediate: true })
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
.reader-body { max-height: 52vh; overflow: auto; min-width: 0; padding-right: 8px; line-height: 1.8; color: var(--el-text-color-primary); }
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
@media (max-width: 700px) {
  .reader-layout { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .reader-toc { max-height: 18vh; border-right: 0; border-bottom: 1px solid var(--el-border-color); }
  .reader-body { max-height: 45vh; }
}
</style>
<style>
.knowledge-reader-dialog { display: flex; flex-direction: column; max-height: 94vh; overflow: hidden; --el-text-color-primary: var(--v7b-text); --el-text-color-regular: var(--v7b-muted); --el-text-color-secondary: var(--v7b-muted); --el-fill-color-light: var(--v7b-surface-2); --el-border-color: var(--v7b-line); --el-mask-color: rgba(255, 255, 255, .85); }
.knowledge-reader-dialog .el-dialog__header, .knowledge-reader-dialog .el-dialog__footer { flex-shrink: 0; }
.knowledge-reader-dialog .el-dialog__body { min-height: 0; overflow: auto; }
</style>
