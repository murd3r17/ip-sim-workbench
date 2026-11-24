<template>
  <aside id="workbench-assistant" class="copilot" aria-label="AI 助手" :class="{ collapsed: !store.open, focused: !!preFocusWidth }" :style="panelStyle">
    <button v-if="!store.open" class="copilot-fab" title="打开 AI 助手" @click="store.setOpen(true)">AI</button>

    <template v-else>
      <header class="copilot-header">
        <div class="title-wrap">
          <span class="dot" />
          <div>
            <div class="title">AI 助手</div>
            <div class="sub">仅辅助 · 不代操作</div>
          </div>
        </div>
        <div class="header-actions">
          <button class="icon-btn header-text" aria-label="新对话" title="新对话" @click="onNewChat">新建</button>
          <button class="icon-btn header-text" aria-label="历史对话" title="历史对话" :class="{ on: store.historyOpen }" @click="store.toggleHistory()">历史</button>
          <button class="icon-btn" :aria-label="preFocusWidth ? '恢复面板大小' : '专注展开'" :title="preFocusWidth ? '恢复面板大小' : '专注展开'" @click="toggleFocus">{{ preFocusWidth ? '▣' : '⛶' }}</button>
          <el-dropdown class="display-settings" trigger="click" @command="onDisplayCommand">
            <button class="icon-btn" aria-label="助手显示设置" title="助手显示设置">⋯</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="narrow">调窄助手</el-dropdown-item>
                <el-dropdown-item command="wide">调宽助手</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <button class="icon-btn" aria-label="收起助手" title="收起" @click="store.setOpen(false)">›</button>
        </div>
      </header>

      <div v-if="store.activeSyncError" class="history-panel" role="status">
        <p>{{ store.activeSyncError }}</p>
        <button
          v-if="store.activeSyncConflict"
          type="button"
          class="text-btn"
          :disabled="store.loading"
          @click="store.saveConflictAsNew()"
        >保留本地内容并另存</button>
      </div>

      <div v-if="store.historyOpen" class="history-panel">
        <div class="history-head">
          <span>历史对话</span>
          <button type="button" class="text-btn" @click="store.setHistoryOpen(false)">关闭</button>
        </div>
        <div v-if="!store.historyList.length" class="history-empty">暂无历史记录</div>
        <ul v-else class="history-list">
          <li
            v-for="item in store.historyList"
            :key="item.id"
            class="history-item"
            :class="{ active: item.id === store.activeId }"
          >
            <button type="button" class="history-main" :disabled="store.loading" @click="onSwitch(item.id)">
              <span class="history-title">{{ item.title || '新对话' }}</span>
              <span class="history-meta">{{ formatHistoryTime(item.updatedAt) }} · {{ item.messages.length }} 条</span>
            </button>
            <button
              type="button"
              class="history-del"
              title="删除"
              :disabled="store.loading"
              @click.stop="onDelete(item.id)"
            >×</button>
          </li>
        </ul>
      </div>

      <!-- 空对话：顶栏横滑推荐 + 页面联动 -->
      <div v-if="showStarters" class="starter">
        <div class="starter-row">
          <button class="page-pill" type="button" :title="pageMeta.title" @click="askAboutPage">
            {{ pageMeta.title }}
          </button>
          <span v-if="labLinked" class="ctx-chip">
            <button
              class="lab-pill"
              type="button"
              :title="labCtx.label"
              @click="askAboutLab"
            >实训 · {{ labCtx.label }}</button>
            <button
              class="sel-x"
              type="button"
              title="移除实训上下文（不会发送消息）"
              aria-label="移除实训上下文"
              @click.stop="clearLab"
            >×</button>
          </span>
          <button v-else-if="labCtx.isActive" class="page-pill" type="button" @click="linkCurrentLab">关联当前实训</button>
          <span v-if="store.pageRecord" class="ctx-chip">
            <span class="page-pill" :title="store.pageRecord.label">{{ store.pageRecord.label }}</span>
            <button class="sel-x" type="button" aria-label="移除已选记录" @click.stop="store.clearPageRecord()">×</button>
          </span>
          <span v-else-if="store.selection" class="ctx-chip">
            <button
              class="sel-pill"
              type="button"
              :title="store.selection.detail || store.selection.label"
              @click="askAboutSelection"
            >{{ store.selection.label }}</button>
            <button class="sel-pin" type="button" :aria-pressed="store.selectionPinned" @click="store.setSelectionPinned(!store.selectionPinned)">
              {{ store.selectionPinned ? '解除固定' : '固定对象' }}
            </button>
            <button
              class="sel-x"
              type="button"
              title="移除选中项（不会发送消息）"
              aria-label="移除选中项"
              @click.stop="clearSelection"
            >×</button>
          </span>
          <span v-if="store.knowledgeSource?.label" class="ctx-chip">
            <span class="page-pill" :title="store.knowledgeSource.label">{{ store.knowledgeSource.label }}</span>
            <button class="sel-x" type="button" aria-label="清除教材来源" @click.stop="store.selectKnowledgeSource({ mode: 'cleared' })">×</button>
          </span>
          <span v-else-if="store.knowledgeSource?.reference.mode === 'cleared'" class="page-pill" role="status">教材来源已清除</span>
          <button v-else-if="canClearBookSource" class="page-pill" type="button" @click.stop="store.selectKnowledgeSource({ mode: 'cleared' })">清除上轮教材来源</button>
          <button
            v-for="link in pageMeta.links"
            :key="link.path"
            class="link-pill"
            type="button"
            @click="go(link.path)"
          >
            {{ link.label }}
          </button>
        </div>
        <div class="chip-rail" ref="chipRail">
          <button
            v-for="chip in pageMeta.chips"
            :key="chip.label"
            class="chip"
            type="button"
            :disabled="store.loading"
            @click="send(chip.prompt, !!chip.wantDraft)"
          >
            {{ chip.label }}
          </button>
          <button v-if="visionEnabled" class="chip chip-vision" type="button" :disabled="store.loading" @click="pickFile">
            发截图解读
          </button>
        </div>
      </div>

      <!-- 已有对话：紧凑联动条 -->
      <div v-else class="live-bar">
        <button class="page-pill sm" type="button" @click="askAboutPage">{{ pageMeta.title }}</button>
        <span v-if="labLinked" class="ctx-chip">
          <button
            class="lab-pill sm"
            type="button"
            :title="labCtx.label"
            @click="askAboutLab"
          >{{ labCtx.label }}</button>
          <button
            class="sel-x"
            type="button"
            title="移除实训上下文（不会发送消息）"
            aria-label="移除实训上下文"
            @click.stop="clearLab"
          >×</button>
        </span>
        <button v-else-if="labCtx.isActive" class="page-pill sm" type="button" @click="linkCurrentLab">关联当前实训</button>
        <span v-if="store.pageRecord" class="ctx-chip">
          <span class="page-pill sm" :title="store.pageRecord.label">{{ store.pageRecord.label }}</span>
          <button class="sel-x" type="button" aria-label="移除已选记录" @click.stop="store.clearPageRecord()">×</button>
        </span>
        <span v-else-if="store.selection" class="ctx-chip">
          <button
            class="sel-pill sm"
            type="button"
            :title="store.selection.detail || store.selection.label"
            @click="askAboutSelection"
          >{{ store.selection.label }}</button>
          <button class="sel-pin" type="button" :aria-pressed="store.selectionPinned" @click="store.setSelectionPinned(!store.selectionPinned)">
            {{ store.selectionPinned ? '解除固定' : '固定对象' }}
          </button>
          <button
            class="sel-x"
            type="button"
            title="移除选中项（不会发送消息）"
            aria-label="移除选中项"
            @click.stop="clearSelection"
          >×</button>
        </span>
        <span v-if="store.knowledgeSource?.label" class="ctx-chip">
          <span class="page-pill sm" :title="store.knowledgeSource.label">{{ store.knowledgeSource.label }}</span>
          <button class="sel-x" type="button" aria-label="清除教材来源" @click.stop="store.selectKnowledgeSource({ mode: 'cleared' })">×</button>
        </span>
        <span v-else-if="store.knowledgeSource?.reference.mode === 'cleared'" class="page-pill sm" role="status">教材来源已清除</span>
        <button v-else-if="canClearBookSource" class="page-pill sm" type="button" @click.stop="store.selectKnowledgeSource({ mode: 'cleared' })">清除上轮教材来源</button>
        <div class="live-spacer" />
        <button
          v-for="link in pageMeta.links.slice(0, 2)"
          :key="link.path"
          class="link-pill sm"
          type="button"
          @click="go(link.path)"
        >
          {{ link.label }}
        </button>
      </div>

      <div ref="listEl" class="messages">
        <div v-if="!store.messages.length" class="empty">
          <p>可以问当前页面怎么操作，或请助手解读选中的设备与证据。</p>
          <p class="empty-tip">{{ visionEnabled ? '可以添加截图或文本文件供助手解读。' : '可添加终端输出或配置等文本文件。' }}</p>
        </div>
        <div
          v-for="msg in store.messages"
          :key="msg.id"
          class="msg"
          :class="msg.role"
        >
          <div class="bubble" :class="{ streaming: msg.streaming }" @click="onBubbleClick($event, msg)">
            <div v-if="msg.sentContext" class="msg-time sent-context">提问时 · {{ msg.sentContext }}</div>
            <div v-if="msg.role === 'assistant' && msg.streaming && !msg.content" class="thinking-line" role="status">
              {{ toolStatus || progressStatus }}
            </div>
            <div
              v-if="msg.role === 'assistant' && msg.content"
              class="md-body"
              v-html="renderMarkdown(msg.content, msg.streaming ? undefined : availableReferences(msg))"
            />
            <p v-else-if="msg.role === 'assistant' && !msg.streaming && !msg.requestId" class="md-body">这条历史回复未保存完整内容，无法查询原回答。</p>
            <template v-else-if="msg.role === 'user'">
              <div v-if="msg.attachments?.length" class="msg-attachments">
                <template v-for="(att, i) in msg.attachments" :key="i">
                  <button v-if="isImageAttachment(att) && att.contentString" class="msg-file-tag" type="button"
                    :aria-label="'查看图片 ' + (att.name || '附件')" @click="zoomImage(att.contentString)">
                    <img :src="att.contentString" :alt="att.name || '已发送图片'" class="msg-img" />
                  </button>
                  <button v-else class="msg-file-tag" type="button" @click="openAttachment(msg, i)">
                    {{ att.name || '附件' }}
                  </button>
                </template>
              </div>
              <pre class="text">{{ msg.content }}</pre>
            </template>
            <span v-if="msg.streaming && msg.content" class="caret" />
            <details v-if="answerSources(msg).length" class="sources">
              <summary class="sources-title">{{ msg.generationStatus === 'retrieval_only' ? '检索到的教材' : '引用资料' }}（{{ answerSources(msg).length }}）</summary>
              <button
                v-for="{ source: s, index: i } in answerSources(msg)"
                :key="i"
                class="source-item source-link"
                type="button"
                @click="openCitation(msg, i)"
              >
                <strong>[{{ i + 1 }}] {{ s.title || s.filename || '引用资料' }}</strong>
                <span v-if="s.book_title && s.book_title !== s.title" class="source-book">{{ s.book_title }}</span>
                <span v-if="s.page" class="source-page">{{ citationPageLabel(s) }}</span>
                <span v-if="s.reviewed_notes?.length" class="source-review">审校补充 {{ s.reviewed_notes.length }} 条</span>
              </button>
            </details>
            <div v-else-if="msg.role === 'assistant' && !msg.streaming && ['degraded', 'empty'].includes(msg.knowledgeStatus || '')" class="sources">
              <div class="sources-title">{{ msg.knowledgeStatus === 'degraded' ? '本次未能连接知识服务' : '本次检索没有找到可引用的片段' }}</div>
            </div>
            <div v-else-if="msg.role === 'assistant' && !msg.streaming && msg.requestState === 'completed' && msg.knowledgeStatus === 'ok'" class="sources">
              <div class="sources-title">已检索资料，正文没有引用检索片段。</div>
            </div>
            <div v-if="msg.modelUnavailable && msg.generationStatus !== 'retrieval_only' && !msg.streaming" class="offline-help">
              可继续查看页面上已保存的内容，或<button type="button" class="text-btn" @click="go('/knowledge')">打开知识库</button>检索和阅读教材。
            </div>
            <div v-if="msg.draftRefused && !msg.streaming" class="draft-refused">
              未生成配置草稿：{{ msg.draftRefused }}
            </div>
            <div v-if="msg.draftCommands?.length && !msg.streaming" class="draft-actions">
              <span class="draft-target">草稿目标：{{ msg.draftTarget?.verifiedByServer ? msg.draftTarget.label : '未核验设备，载入后需选择' }}</span>
              <button class="draft-btn" type="button" @click="copyDraft(msg.draftCommands!)">复制草稿</button>
              <button class="draft-btn primary" type="button" @click="applyDraft(msg)">填入下发</button>
            </div>
            <div v-if="msg.requestId && !msg.streaming && !msg.cancelled && msg.requestState && msg.requestState !== 'completed'" class="request-recovery" role="status">
              <span v-if="msg.generationStatus === 'retrieval_only'">已保留本次教材检索结果。</span>
              <span v-else>回答{{ msg.requestState === 'failed' ? '失败' : '尚未确认完成' }}，可查询已保存的内容。</span>
              <button type="button" class="text-btn" :disabled="store.loading || !!recoveringRequest" @click="recoverReply(msg)">{{ msg.generationStatus === 'retrieval_only' ? '查询已保存结果' : '查询原回答' }}</button>
              <span v-if="recoveryNotice.id === msg.id">{{ recoveryNotice.text }}</span>
              <button v-if="retryMessageId === msg.id" type="button" class="text-btn"
                :disabled="store.loading || !!recoveringRequest" @click="restoreQuestion(msg)">恢复原问题</button>
            </div>
            <details v-if="msg.requestId && !msg.streaming && (msg.cancelled || msg.requestState === 'failed' || msg.requestState === 'interrupted')" class="request-details">
              <summary>诊断详情</summary>
              <span>请求编号 <code>{{ msg.requestId }}</code></span>
            </details>
            <div v-if="msg.recovered" class="msg-time">这条回复已恢复原请求结果 · 未重新生成</div>
            <div class="msg-time">{{ formatMsgTime(msg.createdAt) }}</div>
          </div>
        </div>
        <!-- 工具调用状态：放在消息流末尾，多轮对话后跟随最新消息可见 -->
        <div v-if="toolStatus && streamingStarted" class="tool-note" role="status">{{ toolStatus }}</div>
      </div>

      <footer class="composer">
        <div v-if="carryContextHint" class="carry-hint">{{ carryContextHint }}</div>
        <div v-if="store.configComparison?.kind === 'saved'" class="carry-hint">
          差异问题会使用已保存的 A #{{ store.configComparison.version_id_a }} 和 B #{{ store.configComparison.version_id_b }}。
        </div>
        <div v-else-if="store.configComparison?.kind === 'local'" class="carry-hint">
          本地 A/B 文件仅在浏览器中比对。需要助手解读时，可以附上要核对的片段。
        </div>
        <div v-if="attachmentContext && !pendingAttachments.length" class="carry-hint">
          本次将读取 {{ attachmentContext.attachments?.map(a => a.name || '附件').join('、') }}
          <button type="button" class="text-btn" @click="composer().ignoreAttachment = true">仅回答问题</button>
        </div>
        <input
          ref="fileInput"
          type="file"
          :accept="attachmentAccept"
          multiple
          style="display:none"
          @change="onFileChange"
        />
        <div v-if="pendingAttachments.length" class="attach-preview">
          <div v-for="(att, i) in pendingAttachments" :key="i" class="attach-item" :title="att.name || '附件'">
            <img v-if="att.contentString.startsWith('data:image/')" :src="att.contentString" alt="" />
            <span v-else class="attach-file">{{ att.name || '文件' }}</span>
            <button class="attach-del" type="button" title="移除" @click="removeAttachment(i)">×</button>
          </div>
          <button class="attach-add" type="button" title="添加文件" @click="pickFile">
            <span>＋</span>
          </button>
          <div class="attach-hint">
            <span v-if="visionEnabled">支持截图/图片与文本文件（.txt/.md/.log/.csv/.json/.conf/.cfg）</span>
            <span v-else class="attach-hint-off">{{ visionHint }}；仍可添加文本文件</span>
          </div>
        </div>
        <div v-if="!visionEnabled && !pendingAttachments.length" class="attach-hint attach-hint-off">{{ visionHint }}；仍可添加文本文件</div>
        <textarea
          ref="promptInput"
          v-model="input"
          rows="3"
          aria-label="向 AI 助手提问"
          :placeholder="pageMeta.placeholder"
          :disabled="store.loading"
          @keydown="onKeydown"
          @paste="onPaste"
        />
        <div class="composer-row">
          <label class="draft-toggle">
            <input v-model="wantDraft" type="checkbox" />
            附带配置草稿
          </label>
          <div class="composer-actions">
            <button class="attach-btn" type="button" :title="visionEnabled ? '添加文件（截图/图片/文本）' : '添加文本文件（图片功能未启用）'" @click="pickFile">
              <span class="attach-btn-label">文件</span>
            </button>
            <button
              v-if="store.loading"
              class="stop-btn"
              type="button"
              title="停止生成（请求开始后即可取消）"
              @click="stopGenerating"
            >停止</button>
            <button
              v-else
              class="send-btn"
              type="button"
              :disabled="store.loading || (!input.trim() && !pendingAttachments.length)"
              @click="send()"
            >发送</button>
          </div>
        </div>
      </footer>

      <el-dialog v-model="attachmentVisible" :title="openedAttachment?.name || '对话附件'" append-to-body width="min(42rem, 92vw)">
        <p v-if="attachmentOpening">正在读取已保存的文件…</p>
        <template v-else-if="openedAttachment?.contentString">
          <img v-if="isImageAttachment(openedAttachment)" :src="openedAttachment.contentString" alt="已保存图片" class="saved-attachment-image" />
          <pre v-else class="saved-attachment-text">{{ openedAttachment.contentString }}</pre>
          <button class="draft-btn primary" type="button" @click="continueWithAttachment">用此附件追问</button>
        </template>
        <p v-else>暂时无法读取附件。请确认原会话已同步，或重新选择文件。</p>
      </el-dialog>

      <!-- 引用原文 -->
      <div v-if="citation" class="citation-mask" @click.self="closeCitation">
        <section ref="citationPanel" class="citation-panel" role="dialog" aria-modal="true" aria-label="引用原文" tabindex="-1" @keydown="onCitationKeydown">
          <header class="citation-head">
            <div class="citation-heading">
              <strong>[{{ citation.index + 1 }}] {{ citation.title || citation.filename || '引用片段' }}</strong>
              <span v-if="citation.book_title && citation.book_title !== citation.title" class="source-book">{{ citation.book_title }}</span>
              <span v-if="citation.legacy?.physical?.length" class="source-page">PDF 物理页 {{ legacyPageRange(citation.legacy.physical) }}</span>
              <span v-else-if="citation.page" class="source-page">{{ citationPageLabel(citation) }}</span>
            </div>
            <button class="icon-btn" type="button" title="关闭引用" aria-label="关闭引用" @click="closeCitation">×</button>
          </header>
          <p v-if="citation.status === 'ok'" class="citation-meta">
            {{ citation.scope === 'retrieval_excerpt' ? '本次检索保存的片段' : citation.scope === 'answer_excerpt' ? '原回答保存的片段' : '当前资料正文' }}
            <span v-if="citation.version"> · {{ citation.scope === 'answer_excerpt' || citation.scope === 'retrieval_excerpt' ? '片段指纹' : '资料版本' }} {{ citation.version.slice(0, 12) }}</span>
            <span v-if="citation.captured_at"> · {{ new Date(citation.captured_at).toLocaleString('zh-CN') }}</span>
          </p>
          <p v-if="citation.status === 'ok' && citation.message" class="citation-meta">{{ citation.message }}</p>
          <p v-if="citation.status === 'ok' && citation.truncated" class="citation-meta">{{ citation.scope === 'retrieval_excerpt' ? '以下为本次检索保留的节选，可继续阅读同版正文。' : '以下为回答实际采用的段落节选，可继续阅读资料正文。' }}</p>
          <div v-if="citation.status === 'ok'" ref="citationBody" class="citation-body">
            <section>
              <strong>{{ citation.scope === 'retrieval_excerpt' ? '本机教材整理稿' : citation.scope === 'answer_excerpt' ? (citation.edition_version ? '回答引用的教材整理稿' : '回答引用的片段') : '当前资料' }}</strong>
              <pre>{{ citation.content || '该来源未附正文片段。' }}</pre>
            </section>
            <section v-if="citation.reviewed_notes?.length" ref="citationReviews" class="citation-reviews" tabindex="-1">
              <strong>审校补充 · 非教材原文</strong>
              <article v-for="note in citation.reviewed_notes" :key="note.id" class="citation-review">
                <strong>{{ note.title }}</strong>
                <p>{{ note.content }}</p>
                <p><a :href="reviewedReferenceUrl(note.url)" target="_blank" rel="noopener noreferrer">{{ note.reference }}</a>
                  · 核对 {{ note.reviewed_at }}</p>
              </article>
            </section>
            <p v-else-if="citation.requestsReview" class="citation-meta">这条来源未保存对应的审校补充。</p>
          </div>
          <p v-else-if="citation.status === 'loading'" class="citation-meta">正在校验引用…</p>
          <p v-else class="citation-error">{{ citation.message }}</p>
          <footer class="citation-foot">
            <button v-if="citation.legacy?.status === 'archive-only'" class="draft-btn" type="button" @click="closeCitation(); go('/knowledge')">打开资料目录</button>
            <button v-else-if="citation.status === 'ok'" class="draft-btn" type="button" @click="fullDocumentVisible = true">{{ citation.legacy ? '查阅核对过的原页位置' : citation.document_version ? '阅读同版正文' : '阅读当前全文' }}</button>
            <button class="draft-btn" type="button" @click="closeCitation">返回对话</button>
          </footer>
        </section>
      </div>
      <KnowledgeDocumentReader v-model="fullDocumentVisible" :document-id="citation?.legacy?.document?.id || citation?.document_id" :filename="citation?.filename"
        :version="citation?.legacy?.document?.version || citation?.document_version"
        :edition-version="citation?.legacy?.edition_version"
        :section-id="citation?.legacy ? (citation.legacy.section_id ?? undefined) : citation?.section_id"
        :original-page="citation?.legacy ? (citation.legacy.target_page ?? citation.legacy.physical?.[0]) : (citation?.edition_version ? citation.page : undefined)"
        :require-page="citation?.legacy?.status === 'exact-page-locator'"
        :excerpt="citation?.legacy ? undefined : citation?.content" />
      <div v-if="zoomVisible" class="zoom-mask" @click="zoomVisible = false">
        <img :src="zoomSrc" class="zoom-img" alt="预览" />
        <button class="zoom-close" type="button" title="关闭" @click="zoomVisible = false">×</button>
      </div>
    </template>
  </aside>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { cancelCopilotRequest, copilotChatStream, getAICapabilities, getCopilotRequest, getCopilotSession, type CopilotReference } from '../api/ai'
import { useAiCopilotStore, type CopilotAttachment, type CopilotMessage } from '../stores/aiCopilot'
import { useLabContextStore } from '../stores/labContext'
import { sessionFetch } from '../stores/browserSession'
import { referencedSourceIndices, renderMarkdown } from '../utils/markdownLite'
import KnowledgeDocumentReader from './KnowledgeDocumentReader.vue'
import { resolvePageMeta } from '../utils/copilotContext'
import { buildPageDataContext } from '../utils/pageDataContext'
import { resolveWorkbenchDeviceModel } from '../utils/deviceModel'

const store = useAiCopilotStore()
const labCtx = useLabContextStore()
const route = useRoute()
const router = useRouter()
type Composer = { text: string; files: CopilotAttachment[]; wantsDraft: boolean; uploadId?: string; ignoreAttachment?: boolean }
const drafts = reactive(new Map<string, Composer>())
function composer(id = store.activeId || '') {
  if (!drafts.has(id)) drafts.set(id, { text: '', files: [], wantsDraft: false })
  return drafts.get(id)!
}
const input = computed({
  get: () => composer().text,
  set: (text) => { store.ensureActiveConversation(); composer().text = text },
})
const promptInput = ref<HTMLTextAreaElement | null>(null)
const wantDraft = computed({
  get: () => composer().wantsDraft,
  set: (value) => { store.ensureActiveConversation(); composer().wantsDraft = value },
})
const labLinked = computed(() => labCtx.isActive && store.linkedLabSession === labCtx.sessionId)
const listEl = ref<HTMLElement | null>(null)
const streamingStarted = ref(false)
const progressStatus = ref('正在准备问题与页面信息…')
const preFocusWidth = ref(0)

function resizeNarrower() {
  store.setWidth(store.width - 40)
}
function resizeWider() {
  store.setWidth(store.width + 40)
}
function onDisplayCommand(command: string) {
  if (command === 'narrow') resizeNarrower()
  if (command === 'wide') resizeWider()
}
function toggleFocus() {
  if (preFocusWidth.value) {
    store.setWidth(preFocusWidth.value)
    preFocusWidth.value = 0
  } else {
    preFocusWidth.value = store.width
    store.setWidth(520)
  }
}
type StreamRequest = {
  controller: AbortController
  assistantId: string
  conversationId: string | null
  requestId: string
  cancelled: boolean
}
let activeRequest: StreamRequest | null = null

function newRequestId() {
  const cryptoApi = globalThis.crypto as Crypto | undefined
  if (cryptoApi?.randomUUID) return `copilot-${cryptoApi.randomUUID()}`
  return `copilot-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
}

function isCurrentRequest(request: StreamRequest) {
  return activeRequest === request && store.activeId === request.conversationId
}

// 待发送附件（图片 data URL）
const pendingAttachments = computed({
  get: () => composer().files,
  set: (value: CopilotAttachment[]) => { composer().files = value },
})
const MAX_ATTACHMENTS = 4
const MAX_ATTACH_MB = 12
// Capability is authenticated and fail-closed; an unconfigured image must not
// silently become an ordinary text request that appears to have read it.
const visionEnabled = ref(false)
const visionMimeTypes = ref<string[]>([])
const visionHint = ref('正在确认图片功能')
const attachmentAccept = computed(() => [...(visionEnabled.value ? visionMimeTypes.value : []), '.txt', '.md', '.log', '.csv', '.json', '.conf', '.cfg', 'text/plain', 'text/markdown'].join(','))
const fileInput = ref<HTMLInputElement | null>(null)

const showStarters = computed(() => store.messages.length === 0)
const pageMeta = computed(() => resolvePageMeta(store.routePath || route.path))

// 工具调用状态提示（AI 实时查证数据时展示，如"正在查询设备状态…"）
const toolStatus = ref('')
const TOOL_LABELS: Record<string, string> = {
  query_devices: '查询设备状态',
  query_device_detail: '查询设备详情',
  run_display_command: '在设备上执行只读命令',
  query_monitor_stats: '查询监控统计',
  query_alarms: '查询告警',
  query_deploy_tasks: '查询下发任务',
  query_config_versions: '查询配置版本',
  search_knowledge: '检索知识库',
  query_topology: '查询拓扑',
  query_audit_logs: '查询审计日志',
}

const panelStyle = computed(() =>
  store.open ? { width: `${store.width}px` } : { width: '0px' }
)

// 页面数据快照在发送消息时实时采集（见 send 流程），此处只同步页面上下文。
function pageCtx() {
  const selected = store.selection
  const labDevice = labCtx.device
  return {
    sessionId: labLinked.value ? labCtx.sessionId : null,
    labId: labLinked.value ? labCtx.labId : null,
    labTitle: labLinked.value ? labCtx.labTitle : '',
    topologyId: labLinked.value ? labCtx.topologyId : null,
    device: labLinked.value && selected?.kind === 'device' && selected.id === labDevice?.id ? labDevice : null,
    labSteps: labLinked.value ? labCtx.labSteps : [],
  }
}

watch(
  () => [route.path, route.name],
  () => {
    store.setPageContext(route.path, String(route.name || pageMeta.value.title))
  },
  { immediate: true, flush: 'sync' }
)

async function scrollBottom() {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}

function go(path: string) {
  router.push(path)
}

function clearSelection() {
  store.clearSelection()
}

function clearLab() {
  store.linkLab(null)
}

function linkCurrentLab() {
  if (labCtx.isActive) store.linkLab(labCtx.sessionId)
}

function askAboutLab() {
  if (!labCtx.hasLab) return
  if (labCtx.sessionId) {
    router.push({ path: '/training', query: { session_id: String(labCtx.sessionId) } })
  }
  send(`当前实训「${labCtx.label}」。请说明本实验建议步骤，以及如何结合拓扑、设备、WebSSH、下发完成验证。`)
}

function askAboutPage() {
  send(`请结合当前「${pageMeta.value.title}」页面，说明它做什么、初学者该怎么用，以及和相邻模块怎么配合。`)
}

function askAboutSelection() {
  const s = store.selection
  if (!s) return
  send(`当前选中：${s.label}${s.detail ? `（${s.detail}）` : ''}。请结合「${pageMeta.value.title}」给出实训向的解读与下一步建议。`)
}

function onNewChat() {
  cancelActiveRequest()
  const draft = composer()
  store.newChat(Boolean(draft.text.trim() || draft.files.length))
}

function onSwitch(id: string) {
  if (store.loading) {
    ElMessage.warning('请等待当前回复完成后再切换')
    return
  }
  cancelActiveRequest()
  store.switchConversation(id)
  nextTick(() => scrollBottom())
}

const carryContextHint = computed(() => {
  const bits: string[] = []
  if (labLinked.value) bits.push(`实训「${labCtx.label}」`)
  if (store.selection?.label) bits.push(`${store.selectionPinned ? '已固定' : '跟随本页'}「${store.selection.label}」`)
  if (!bits.length) return ''
  return `下次提问 · ${bits.join('、')}`
})

function onDelete(id: string) {
  if (store.loading && id === store.activeId) {
    ElMessage.warning('请等待当前回复完成后再删除')
    return
  }
  if (id === store.activeId) {
    cancelActiveRequest()
  }
  store.deleteConversation(id)
}

function formatHistoryTime(ts: number) {
  const d = new Date(ts)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function formatMsgTime(ts: number) {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function onKeydown(e: KeyboardEvent) {
  // isComposing：中文/日文输入法选词时按回车是"上屏候选词"，不能当成发送，
  // 否则会把自己的拼音/半成品发出去（中文平台高频踩坑）
  if (e.isComposing || (e as KeyboardEvent & { keyCode?: number }).keyCode === 229) return
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

// ── 附件：图片 / 文本文件 选择、粘贴、预览 ─────────────────────────────
const TEXT_EXTS = ['.txt', '.md', '.log', '.csv', '.json', '.conf', '.cfg']
const TEXT_MIME = ['text/plain', 'text/markdown', 'application/json', 'application/xml']

function pickFile() {
  fileInput.value?.click()
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  onFilesSelected(input.files)
  input.value = ''
}

function onFilesSelected(files: FileList | null) {
  if (!files) return
  const list = Array.from(files)
  for (const f of list) {
    if (pendingAttachments.value.length >= MAX_ATTACHMENTS) {
      ElMessage.warning(`最多添加 ${MAX_ATTACHMENTS} 个附件`)
      break
    }
    const isText = TEXT_EXTS.includes(extOf(f.name)) || TEXT_MIME.includes(f.type)
    if (!isText && !f.type.startsWith('image/')) {
      ElMessage.warning(`不支持的文件类型：${f.name}（支持图片与 ${TEXT_EXTS.join(' / ')}）`)
      continue
    }
    if (isText) readTextFile(f)
    else readImage(f)
  }
}

function extOf(name: string) {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

function readTextFile(file: File) {
  store.ensureActiveConversation()
  const draft = composer()
  const maxChars = 300000 // 约 300KB 文本，控制上下文
  if (file.size > maxChars * 3) {
    ElMessage.warning(`文本文件过大（>${Math.round(maxChars * 3 / 1024)}KB）已截断前部分：${file.name}`)
  }
  const reader = new FileReader()
  reader.onload = () => {
    let text = String(reader.result)
    if (text.length > maxChars) text = text.slice(0, maxChars) + `\n\n[内容已截断，原文件 ${file.name} 共 ${file.size} 字节]`
    if (draft.files.length >= MAX_ATTACHMENTS) return
    draft.files.push({
      contentString: text,
      mime: 'text/plain',
      name: file.name,
    })
  }
  reader.onerror = () => ElMessage.error('文件读取失败')
  reader.readAsText(file, 'utf-8')
}

function readImage(file: File) {
  if (!visionEnabled.value) {
    ElMessage.warning(visionHint.value)
    return
  }
  if (!visionMimeTypes.value.includes(file.type)) {
    ElMessage.warning('当前图片格式不受支持')
    return
  }
  if (file.size > MAX_ATTACH_MB * 1024 * 1024) {
    ElMessage.warning(`图片过大（>${MAX_ATTACH_MB}MB）：${file.name}`)
    return
  }
  store.ensureActiveConversation()
  const draft = composer()
  const reader = new FileReader()
  reader.onload = () => {
    if (draft.files.length >= MAX_ATTACHMENTS) return
    draft.files.push({
      contentString: String(reader.result),
      mime: file.type,
      name: file.name,
    })
  }
  reader.onerror = () => ElMessage.error('图片读取失败')
  reader.readAsDataURL(file)
}

function onPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) {
        e.preventDefault()
        readImage(file)
      }
    }
  }
}

function removeAttachment(i: number) {
  pendingAttachments.value.splice(i, 1)
}

// 请求归属在取消时即失效，迟到的回调/finally 不得影响下一条回复。
function cancelActiveRequest() {
  const request = activeRequest
  if (!request) return
  request.cancelled = true
  // Ignore old callbacks immediately, but give the server cancellation a
  // bounded chance to arrive before disconnecting the stream. An immediate
  // abort otherwise races the acknowledgement and gets saved as interrupted.
  const cancelTimeout = setTimeout(() => request.controller.abort(), 1500)
  cancelCopilotRequest(request.requestId).catch(() => { /* 请求可能已结束 */ }).finally(() => {
    clearTimeout(cancelTimeout)
    request.controller.abort()
  })
  if (isCurrentRequest(request)) {
    const msg = store.messages.find((m) => m.id === request.assistantId)
    store.patchMessage(request.assistantId, { streaming: false, cancelled: true, requestState: 'cancelled' })
    store.appendContent(request.assistantId, msg?.content ? '\n\n（已取消，以上内容未完成）' : '（已取消本次请求）')
    store.syncActiveToList()
  }
  activeRequest = null
  store.loading = false
  streamingStarted.value = false
  progressStatus.value = '正在准备问题与页面信息…'
  toolStatus.value = ''
}

function stopGenerating() {
  cancelActiveRequest()
  ElMessage.info('已停止生成')
}

const recoveringRequest = ref('')
const recoveryNotice = ref({ id: '', text: '' })
const retryMessageId = ref('')
async function recoverReply(message: CopilotMessage) {
  if (!message.requestId || store.loading || recoveringRequest.value) return
  const conversationId = store.activeId
  const requestId = message.requestId
  recoveringRequest.value = requestId
  const stillCurrent = () => store.activeId === conversationId
    && store.messages.some((m) => m.id === message.id && m.requestId === requestId && !m.cancelled)
  try {
    const saved = await getCopilotRequest(requestId)
    if (!stillCurrent()) return
    if (saved.state === 'running') {
      recoveryNotice.value = { id: message.id, text: '原请求仍在处理或结果未确认；本次查询没有重跑模型。稍后可再次查询。' }
      store.patchMessage(message.id, { requestState: 'unconfirmed' })
      return
    }
    const result = saved.response
    const incomplete = saved.state !== 'completed'
    const retrievalOnly = result?.generation_status === 'retrieval_only'
    const answer = result?.answer || result?.error_message || '原请求未保存回答内容。'
    store.patchMessage(message.id, {
      content: answer + (incomplete && !retrievalOnly ? '\n\n> 原请求未完成，以上为已保存的内容。' : ''),
      sources: result?.sources || [],
      knowledgeStatus: result?.knowledge_status,
      generationStatus: result?.generation_status,
      draftCommands: incomplete ? [] : result?.draft_commands || [],
      draftTarget: incomplete ? null : serverDraftTarget(result?.draft_target),
      draftRefused: result?.draft_refused_reason || undefined,
      streaming: false,
      requestState: saved.state,
      modelUnavailable: incomplete && message.modelUnavailable,
      cancelled: saved.state === 'cancelled',
      recovered: true,
    })
    recoveryNotice.value = { id: '', text: '' }
    retryMessageId.value = saved.state === 'failed' || saved.state === 'interrupted' ? message.id : ''
    store.syncActiveToList()
  } catch (error: any) {
    if (stillCurrent()) {
      const status = error?.response?.status
      retryMessageId.value = status === 404 ? message.id : ''
      recoveryNotice.value = { id: message.id, text: status === 403
        ? '当前权限不能读取原请求结果，请联系管理员核对权限；本次未重新生成。'
        : status === 404
          ? '未找到原请求记录。可以恢复原问题再发送。'
          : '暂时无法查询原请求；已有内容保留，可稍后再查。' }
    }
  } finally {
    if (recoveringRequest.value === requestId) recoveringRequest.value = ''
  }
}

// A browser closed after generation may have saved only the request anchor.
// Recover that empty placeholder once from the owned request; never regenerate
// or poll a still-running request. Older unlinked messages stay explicitly unknown.
const automaticRecoveries = new Set<string>()
watch(() => [store.activeId, store.open, store.loading, recoveringRequest.value,
  store.messages.slice(-20).map(m => `${m.id}:${m.requestId}:${m.requestState}:${m.streaming}:${m.content?.length || 0}`).join('|')],
async () => {
  if (!store.open || store.loading || recoveringRequest.value) return
  const message = store.messages.slice(-20).find(m => m.role === 'assistant' && !m.content
    && !m.streaming && !m.cancelled && m.requestId && m.requestState !== 'completed'
    && !automaticRecoveries.has(`${store.activeId}:${m.id}:${m.requestId}`))
  if (!message) return
  automaticRecoveries.add(`${store.activeId}:${message.id}:${message.requestId}`)
  await recoverReply(message)
}, { immediate: true })

function restoreQuestion(message: CopilotMessage) {
  const index = store.messages.findIndex((item) => item.id === message.id)
  const original = store.messages.slice(0, index).reverse().find((item) => item.role === 'user')
  if (!original) return
  if (input.value.trim() || pendingAttachments.value.length) {
    ElMessage.warning('请先处理输入框里的问题，再恢复原问题。')
    return
  }
  input.value = original.content
  composer().uploadId = original.attachments?.length ? original.id : original.attachmentMessageId
  composer().ignoreAttachment = false
  wantDraft.value = false
  void nextTick(() => promptInput.value?.focus())
}

function isImageAttachment(item: CopilotAttachment) {
  return item.mime?.startsWith('image/') || item.contentString.startsWith('data:image/')
}

const attachmentVisible = ref(false)
const attachmentOpening = ref(false)
const openedAttachment = ref<CopilotAttachment>()
let openedUploadId = ''
let attachmentRead = 0

async function openAttachment(message: CopilotMessage, index: number) {
  const item = message.attachments?.[index]
  const conversationId = store.activeId
  if (!item || !conversationId) return
  const sequence = ++attachmentRead
  openedAttachment.value = item
  openedUploadId = message.id
  attachmentVisible.value = true
  attachmentOpening.value = !item.contentString
  if (item.contentString) return
  try {
    const saved = await getCopilotSession(conversationId, { silent: true })
    if (sequence !== attachmentRead || store.activeId !== conversationId || !attachmentVisible.value) return
    const full = saved.messages.find((entry) => entry.id === message.id)?.attachments?.[index]
    if (full?.contentString) openedAttachment.value = full
  } catch {
    // Keep the file identity and its unavailable state visible.
  } finally {
    if (sequence === attachmentRead) attachmentOpening.value = false
  }
}

function continueWithAttachment() {
  if (!openedAttachment.value?.contentString) return
  composer().uploadId = openedUploadId
  composer().ignoreAttachment = false
  attachmentVisible.value = false
  void nextTick(() => promptInput.value?.focus())
}

function priorUpload(question: string) {
  const draft = composer()
  if (draft.ignoreAttachment || /不(?:用|看|读取|结合|引用)(?:此前|之前|上次|原来的)?(?:文件|附件|表格|截图)/.test(question)) return
  const uploads = store.messages.filter((item) => item.role === 'user' && item.attachments?.length)
  if (draft.uploadId) return uploads.find((item) => item.id === draft.uploadId)
  const named = uploads.slice().reverse().find((item) => item.attachments?.some((file) =>
    file.name && question.toLowerCase().includes(file.name.toLowerCase())))
  if (named) return named
  const recent = uploads[uploads.length - 1]
  if (!recent) return
  if (/附件|这个表|这份表|表[里中内]|这份日志|刚才的日志|刚才的图|截图[里中上]|那一行/.test(question)) return recent
  if (/只(?:讲|聊|解释|按)原理|只问概念|脱离.{0,4}(?:实训|实验|现场)|不(?:要|用|必|需要)?(?:结合|参考).{0,4}(?:实训|实验|现场)|当前设备|本次观察|刚采集|实时状态|接口.{0,8}(?:现在|当前|实时)/.test(question)) return
  const interfaces = (value: string) => (value.match(/\b(?:X?GigabitEthernet|X?GE|LoopBack|Eth-Trunk|Vlanif)\s*\d+(?:\/\d+)*(?:\.\d+)?/gi) || [])
    .map(name => name.toLowerCase().replace(/gigabitethernet/g, 'ge').replace(/\s+/g, ''))
  const requestedPorts = interfaces(question)
  if (!requestedPorts.length) return
  if (recent.attachments?.some(file => !isImageAttachment(file)
    && interfaces(file.contentString).some(port => requestedPorts.includes(port)))) return recent
}
const attachmentContext = computed(() => priorUpload(input.value))

watch(() => store.activeId, (id) => {
  attachmentVisible.value = false
  attachmentRead++
  retryMessageId.value = ''
  if (!id) drafts.clear()
})
watch(() => store.conversations.map((conversation) => conversation.id), (ids) => {
  for (const id of drafts.keys()) if (id && !ids.includes(id)) drafts.delete(id)
})

// 图片放大：面板内弹层，避免 window.open 被拦截/新窗口体验差
const zoomSrc = ref('')
const zoomVisible = ref(false)
function reviewedReferenceUrl(url: string): string | undefined {
  return /^https:\/\/www\.rfc-editor\.org\/rfc\/rfc\d+\.html#section-[\d.]+$/.test(url) ? url : undefined
}
const fullDocumentVisible = ref(false)
type OpenCitation = CopilotReference & {
  index: number
  requestsReview: boolean
  document_id?: string
  document_version?: string
  section_id?: string
  legacy?: {
    status: 'exact-page-locator' | 'archive-only'
    document?: { id: string; version: string; book_title?: string }
    physical?: number[]
    target_page?: number
    edition_version?: string
    section_id?: string | null
  }
  scope?: string
  truncated?: boolean
  status: 'loading' | 'ok' | 'revoked' | 'unverifiable'
  message?: string
}
const citation = ref<OpenCitation | null>(null)

function citationPageLabel(source: CopilotReference) {
  return source.edition_version ? `PDF 物理页 ${source.page}` : `来源页 ${source.page}`
}

function legacyPageRange(pages: number[]) {
  return [...new Set(pages)].join('–')
}

function referenceIndex(source: CopilotReference, position: number) {
  return (source.reference_index ?? position + 1) - 1
}

function answerSources(message: CopilotMessage) {
  if (!message.sources?.length || message.streaming) return []
  const numbers = referencedSourceIndices(message.content)
  return message.sources.flatMap((source, position) => {
    const index = referenceIndex(source, position)
    return numbers.has(index) ? [{ source, index }] : []
  })
}
function availableReferences(message: CopilotMessage) {
  return new Set((message.sources || []).map(referenceIndex))
}
const citationPanel = ref<HTMLElement | null>(null)
const citationBody = ref<HTMLElement | null>(null)
const citationReviews = ref<HTMLElement | null>(null)
let citationReturnFocus: HTMLElement | null = null
watch(() => !!citation.value, async (opened) => {
  if (opened) {
    citationReturnFocus = document.activeElement as HTMLElement | null
    await nextTick()
    if (citation.value) citationPanel.value?.focus()
  } else if (citationReturnFocus?.isConnected) {
    citationReturnFocus.focus()
  }
})
function onCitationKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    closeCitation()
  } else if (event.key === 'Tab') {
    const buttons = citationPanel.value?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href]')
    if (!buttons?.length) return
    const first = buttons[0]!
    const last = buttons[buttons.length - 1]!
    if (event.shiftKey && (document.activeElement === first || document.activeElement === citationPanel.value)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }
}
let citationSeq = 0
const canClearBookSource = computed(() => {
  if (store.loading || store.knowledgeSource) return false
  const last = [...store.messages].reverse().find(message => message.role === 'assistant')
  return Boolean(last?.sources?.some(source => source.edition_version && source.page))
})
async function openCitation(msg: Pick<CopilotMessage, 'sources' | 'requestId'>, index: number, requestsReview = false) {
  const s = msg.sources?.find((source, position) => referenceIndex(source, position) === index)
  if (!s) return
  const conversation = store.activeId
  const seq = ++citationSeq
  citation.value = { index, requestsReview, title: s.title, filename: s.filename, version: s.version,
    page: s.page, book_title: s.book_title, edition_version: s.edition_version, status: 'loading' }
  const filename = s.filename || s.title || ''
  if (!filename) {
    if (seq === citationSeq) citation.value = { ...citation.value, status: 'unverifiable', message: '该来源缺少文件名，无法校验。' }
    return
  }
  try {
    const params = new URLSearchParams({ filename })
    if (msg.requestId && s.source_id) {
      params.set('request_id', msg.requestId)
      params.set('source_id', s.source_id)
    }
    const resp = await sessionFetch(`/api/v1/ai/copilot/citations/read?${params}`)
    if (seq !== citationSeq) return  // 晚到的 A 不能污染 B
    if (resp.status === 410) {
      citation.value = { ...citation.value, status: 'revoked', content: '', message: '该引用已失效或已撤权，不再展示旧片段。' }
    } else if (resp.status === 404) {
      citation.value = { ...citation.value, status: 'unverifiable', message: '无法读取原回答保存的这条引用。原有的引用编号已保留。' }
    } else if (!resp.ok) {
      citation.value = { ...citation.value, status: 'unverifiable', content: '', message: '暂时无法校验引用，未展示原文。' }
    } else {
      const doc = await resp.json()
      if (seq !== citationSeq) return
      citation.value = { ...citation.value, status: 'ok', content: doc.content, version: doc.version,
        document_id: doc.document_id,
        document_version: doc.document_version,
        section_id: doc.section_id,
        page: doc.page,
        book_title: doc.legacy_locator?.document?.book_title || doc.book_title || citation.value.book_title,
        edition_version: doc.edition_version || citation.value.edition_version,
        legacy: doc.legacy_locator,
        title: doc.title || citation.value.title, scope: doc.scope, captured_at: doc.captured_at, truncated: doc.truncated,
        reviewed_notes: doc.reviewed_notes, message: doc.message }
      if (store.activeId === conversation && msg.requestId && s.source_id && s.edition_version && s.page
          && doc.scope === 'answer_excerpt' && doc.available_now === true && doc.legacy_locator?.status !== 'archive-only') {
        store.selectKnowledgeSource({ mode: 'selected', request_id: msg.requestId, source_id: s.source_id }, `教材 PDF 第 ${s.page} 页`)
      }
      if (requestsReview) {
        await nextTick()
        if (seq === citationSeq && citationBody.value && citationReviews.value) {
          citationBody.value.scrollTop = citationReviews.value.offsetTop
          citationReviews.value.focus({ preventScroll: true })
        }
      }
    }
  } catch {
    if (seq !== citationSeq) return
    citation.value = { ...citation.value, status: 'unverifiable', content: '', message: '网络不可用，未展示原文。' }
  }
}
function closeCitation() {
  citationSeq++
  fullDocumentVisible.value = false
  citation.value = null
}
function zoomImage(src: string) {
  zoomSrc.value = src
  zoomVisible.value = true
}

async function send(preset?: string, forceDraft = false) {
  const text = (preset ?? input.value).trim() || (!preset && pendingAttachments.value.length ? '请解读这份附件。' : '')
  if ((!text && !pendingAttachments.value.length) || store.loading) return
  // Capture the entire request before any awaited page read. Selection changes
  // during that read belong to the next question, never half of this one.
  const context = {
    route: store.routePath,
    page_name: store.pageName || pageMeta.value.title,
    selection: store.selectionText,
    notes: store.notes,
    config_comparison: route.path === '/config-versions' ? store.configComparison ?? undefined : undefined,
    page_record: store.pageRecord?.reference,
    knowledge_source: store.knowledgeSource?.reference,
  }
  const snapshotContext = JSON.parse(JSON.stringify(pageCtx()))
  const evidenceId = store.evidenceId
  const comparison = context.config_comparison
  const comparisonLabel = comparison?.kind === 'saved'
    ? `A #${comparison.version_id_a} → B #${comparison.version_id_b}`
    : comparison?.kind === 'local' ? '本地文件比对' : ''
  const sentContext = [context.page_name, store.pageRecord?.label || store.selection?.label, snapshotContext.labTitle, comparisonLabel].filter(Boolean).join(' · ')
  const requestedDraft = forceDraft || (!preset && wantDraft.value)
  const deviceModel = resolveWorkbenchDeviceModel(store.selection?.model || snapshotContext.device?.model)
  const labId = snapshotContext.labId
  const labSessionId = snapshotContext.sessionId
  const attachments = preset ? [] : pendingAttachments.value.map((a) => ({ ...a }))
  const upload = !preset && !attachments.length ? priorUpload(text) : undefined
  if (!preset) {
    input.value = ''
    pendingAttachments.value = []
    composer().uploadId = undefined
    composer().ignoreAttachment = false
    wantDraft.value = false
  }

  // 历史必须在 push 本轮消息之前取：否则本轮提问会同时出现在 message 与
  // history 末尾，被发给模型两次（此前只在 push 之后过滤掉 assistant 占位符）。
  const history = store.messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .slice(-8)
    .map((m) => ({ role: m.role, content: m.content,
      ...(m.role === 'assistant' && m.requestId ? { request_id: m.requestId } : {}) }))

  store.pushMessage({
    role: 'user',
    content: text,
    attachments: attachments.length ? attachments : undefined,
    attachmentMessageId: upload?.id,
  })
  const requestId = newRequestId()
  const assistantId = store.pushMessage({
    role: 'assistant',
    content: '',
    sentContext,
    streaming: true,
    draftTarget: null,
    requestId,
    requestState: 'pending',
  })
  store.loading = true
  streamingStarted.value = false
  progressStatus.value = '正在准备问题与页面信息…'
  const request: StreamRequest = {
    controller: new AbortController(),
    assistantId,
    conversationId: store.activeId,
    requestId,
    cancelled: false,
  }
  activeRequest = request
  store.patchMessage(assistantId, { requestId: request.requestId, requestState: 'pending' })
  let receivedDone = false
  let failureMarked = false
  let retrievalOnly = false
  function markFailed(hint: string, modelUnavailable = false) {
    if (!isCurrentRequest(request) || failureMarked) return
    failureMarked = true
    store.patchMessage(assistantId, { requestState: 'interrupted', modelUnavailable })
    if (retrievalOnly) return
    const msg = store.messages.find((m) => m.id === assistantId)
    store.appendContent(assistantId, msg?.content ? `\n\n> ${hint}（回答未完成）` : hint)
  }

  try {
    await scrollBottom()
    if (!isCurrentRequest(request)) return
    // Persist the recovery pointer before generation can finish and the tab can
    // close. The final answer already has its own durable server request record.
    await store.flushConversation(request.conversationId)
    if (!isCurrentRequest(request)) return
    // 快照也是请求生命周期的一部分；失败或取消均须正确收尾。
    const freshPageData = await buildPageDataContext(context.route || route.path, snapshotContext)
    if (!isCurrentRequest(request)) return
    const snapshotText = freshPageData
      ? `（工作台数据快照，采集于 ${new Date().toLocaleString('zh-CN', { hour12: false })}）\n${freshPageData}`
      : ''
    // 有服务端证据 ID 时发送结构化包装；后端回读观察并核验，不用客户端快照当现场事实
    const pageData = evidenceId
      ? JSON.stringify({ evidence_id: evidenceId, text: snapshotText })
      : snapshotText
    await copilotChatStream(
      {
        message: text,
        history,
        context,
        want_draft: requestedDraft,
        device_model: deviceModel,
        top_k: 6,
        page_data: pageData,
        attachments: attachments.length ? attachments : undefined,
        conversation_id: request.conversationId || undefined,
        attachment_message_id: upload?.id,
        lab_id: labId,
        lab_session_id: labSessionId,
        request_id: request.requestId,
      },
      (event) => {
        if (!isCurrentRequest(request)) return
        // 迟到事件：带 request_id 且不是本次请求的，一律丢弃（不写进当前会话）
        const eventId = (event as { request_id?: string }).request_id
        if (eventId && eventId !== request.requestId) return
        if (failureMarked && event.type !== 'done' && event.type !== 'references') return
        if (event.type === 'meta') {
          retrievalOnly ||= event.generation_status === 'retrieval_only'
          store.patchMessage(assistantId, {
            knowledgeStatus: event.knowledge_status || (['empty', 'degraded'].includes(event.status || '') ? event.status : undefined),
            generationStatus: event.generation_status,
            draftRefused: event.draft_refused_reason || undefined,
            draftTarget: serverDraftTarget(event.draft_target),
            recovered: event.replayed === true,
          })
        } else if (event.type === 'references') {
          retrievalOnly ||= event.generation_status === 'retrieval_only'
          store.patchMessage(assistantId, { sources: event.sources || [], generationStatus: event.generation_status })
        } else if (event.type === 'policy') {
          if (event.retrieval_only) {
            retrievalOnly = true
            store.patchMessage(assistantId, { generationStatus: 'retrieval_only' })
          } else {
            store.patchMessage(assistantId, { draftRefused: event.draft_refused_reason || '当前环境未核验，不生成可执行草稿' })
          }
          if (typeof event.replace_answer === 'string') {
            store.patchMessage(assistantId, { content: event.replace_answer, draftCommands: [], draftTarget: null })
          }
          if (Object.prototype.hasOwnProperty.call(event, 'draft_target')) {
            store.patchMessage(assistantId, { draftTarget: serverDraftTarget(event.draft_target) })
          }
        } else if (event.type === 'tool') {
          const label = TOOL_LABELS[event.name || ''] || event.name || '工具'
          toolStatus.value = event.status === 'running' ? `正在${label}…` : ''
          if (event.status !== 'running') progressStatus.value = '正在整理已读取的信息…'
          if (event.status === 'running') scrollBottom()
        } else if (event.type === 'progress' || event.type === 'reasoning') {
          // Progress is not the first answer token: keep a visible status until
          // actual content arrives, without saving provider deliberation.
          progressStatus.value = '正在生成回答…'
        } else if (event.type === 'token') {
          if (!streamingStarted.value) streamingStarted.value = true
          store.appendContent(assistantId, event.text || '')
          scrollBottom()
        } else if (event.type === 'draft') {
          store.patchMessage(assistantId, {
            draftCommands: event.draft_commands || [],
          })
        } else if (event.type === 'done') {
          receivedDone = true
          store.consumeKnowledgeSource(context.knowledge_source)
          if (event.cancelled) {
            request.cancelled = true
          } else if (event.status === 'failed' || event.status === 'unavailable' || event.status === 'interrupted') {
            // AF2-04：模型依赖失败要说清“未调用模型”，不能冒充环境策略拒绝。
            const modelUnavailable = event.reason === 'provider_unavailable'
            markFailed(modelUnavailable ? '模型服务暂不可用，回答未完成。' : '生成失败，请稍后重试。', modelUnavailable)
          }
          store.patchMessage(assistantId, { requestState: request.cancelled ? 'cancelled'
            : event.status === 'interrupted' ? 'interrupted'
            : failureMarked ? 'failed' : 'completed' })
          // blocked_environment / degraded 是有效回答（安全说明或知识降级），不标失败。
        } else if (event.type === 'cancelled') {
          request.cancelled = true
          receivedDone = true
        } else if (event.type === 'error') {
          retrievalOnly ||= event.generation_status === 'retrieval_only'
          const modelUnavailable = event.code === 'provider_unavailable'
          markFailed(modelUnavailable ? '模型服务暂不可用，回答未完成。' : event.message || '生成失败，请稍后重试。', modelUnavailable)
        }
      },
      request.controller.signal
    )

    if (!isCurrentRequest(request)) return
    if (request.cancelled) {
      store.patchMessage(assistantId, { streaming: false, cancelled: true, requestState: 'cancelled' })
      return
    }
    if (!receivedDone) markFailed('连接中断，未收到完成确认，请重试。')
    const msg = store.messages.find((m) => m.id === assistantId)
    if (msg && !msg.content.trim()) {
      store.appendContent(assistantId, '暂无回答')
    }
  } catch (err: any) {
    if (!isCurrentRequest(request) || request.controller.signal.aborted || request.cancelled) return
    const raw = String(err?.message || '')
    const modelUnavailable = err?.code === 'provider_unavailable'
    const hint = modelUnavailable ? '模型服务暂不可用，回答未完成。'
      : err?.code === 'attachment_unavailable' ? raw
      : raw.includes('知识库') || raw.includes('AnythingLLM') || raw.includes('3001')
      ? '知识检索暂不可用，请到知识库页查看当前服务状态后重试。'
      : request.requestId ? '连接中断或请求失败，请先查询原回答。' : '请求失败，请稍后重试。'
    markFailed(hint, modelUnavailable)
  } finally {
    // 即使会话在流中被切换，也要清掉 loading，否则面板会卡在“不可输入、无可停止”状态。
    if (activeRequest === request) {
      store.patchMessage(assistantId, { streaming: false })
      store.loading = false
      streamingStarted.value = false
      toolStatus.value = ''
      activeRequest = null
      store.syncActiveToList()
      await scrollBottom()
    }
  }
}

async function copyDraft(cmds: string[]) {
  try {
    await navigator.clipboard.writeText(cmds.join('\n'))
    ElMessage.success('已复制配置草稿')
  } catch {
    ElMessage.error('复制失败')
  }
}

async function onBubbleClick(e: MouseEvent, message: CopilotMessage) {
  const target = e.target as HTMLElement | null
  const source = target?.closest('[data-source-index]') as HTMLElement | null
  if (source) {
    e.preventDefault()
    await openCitation(message, Number(source.dataset.sourceIndex), source.dataset.sourceReview === 'true')
    return
  }
  const btn = target?.closest('.code-copy') as HTMLElement | null
  if (!btn) return
  e.preventDefault()
  const block = btn.closest('.code-block')
  const code = block?.querySelector('code')?.textContent || ''
  if (!code) return
  try {
    await navigator.clipboard.writeText(code)
    ElMessage.success('已复制代码')
  } catch {
    ElMessage.error('复制失败')
  }
}

function serverDraftTarget(value?: { device_id: number; hostname: string; alarm_id?: number } | null): CopilotMessage['draftTarget'] {
  if (!value || !Number.isSafeInteger(value.device_id) || value.device_id <= 0 || typeof value.hostname !== 'string' || !value.hostname.trim()) return null
  return { deviceId: value.device_id, label: value.hostname, verifiedByServer: true,
    ...(Number.isSafeInteger(value.alarm_id) && value.alarm_id! > 0 ? { alarmId: value.alarm_id } : {}) }
}

async function applyDraft(message: CopilotMessage) {
  const cmds = message.draftCommands || []
  if (!cmds.length) return
  const target = message.draftTarget?.verifiedByServer === true ? message.draftTarget : null
  store.saveDraftToDeploy(cmds, target)
  const deviceId = target?.deviceId
  const query: Record<string, string> = { draft: '1' }
  if (deviceId != null) query.device_id = String(deviceId)
  if (route.path !== '/deploy') {
    await router.push({ path: '/deploy', query })
  } else {
    window.dispatchEvent(new CustomEvent('deploy-ai-draft', { detail: { autoLoad: true } }))
  }
}

onMounted(() => {
  store.setPageContext(route.path, String(route.name || pageMeta.value.title))
  // 1102px 等窄屏默认收起，避免常驻面板把主表格/终端挤到不可读；顶部 AI 按钮仍可随时展开。
  if (window.innerWidth < 1280 && !labCtx.hasLab) store.setOpen(false)
  // 拉取后端会话（跨浏览器恢复历史；失败静默）
  store.loadFromBackend()
  void getAICapabilities().then((capabilities) => {
    visionEnabled.value = capabilities.vision_enabled === true
    visionMimeTypes.value = capabilities.image_mime_types || []
    visionHint.value = visionEnabled.value ? '' : '图片功能未启用，请联系管理员配置视觉模型'
  }).catch(() => {
    visionEnabled.value = false
    visionHint.value = '图片功能状态读取失败，请稍后刷新重试'
  })
  window.addEventListener('copilot-prefill', onExternalPrefill)
})

onUnmounted(() => {
  window.removeEventListener('copilot-prefill', onExternalPrefill)
  cancelActiveRequest()
})

function onExternalPrefill(e: Event) {
  const detail = (e as CustomEvent).detail
  const prompt = detail?.prompt
  if (typeof prompt !== 'string' || !prompt.trim()) return
  store.setOpen(true)
  if (!input.value.trim()) {
    input.value = prompt
    wantDraft.value = false
  } else if (input.value !== prompt) {
    ElMessage.info('输入框有尚未发送的问题。清空后可从原页面再次载入本次问题。')
  }
  void nextTick(() => promptInput.value?.focus())
}
</script>

<style scoped>
.request-recovery {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--v7b-line, #cbd5e1);
  font-size: 12px;
  line-height: 1.6;
  color: inherit;
}
.request-recovery .text-btn { text-decoration: underline; }
.request-details { margin-top: 8px; font-size: 12px; overflow-wrap: anywhere; }
.request-details summary { cursor: pointer; }
.copilot {
  position: relative;
  flex: 0 0 auto;
  min-width: 0;
  height: 100dvh;
  border-left: 1px solid var(--v7b-line, var(--v7b-line));
  background: var(--v7b-surface);
  color: var(--v7b-text);
  display: flex;
  flex-direction: column;
  transition: width 0.18s ease;
  overflow: hidden;
}
.copilot { max-width: min(42vw, 560px); }
.copilot.collapsed { border-left: 0; }
@media (max-width: 1500px) {
  .copilot:not(.collapsed) { max-width: 480px; }
}
@media (max-width: 1200px) {
  .copilot:not(.collapsed) { max-width: 340px; }
}
.copilot.focused { max-width: 560px !important; }
@media (max-width: 1100px) {
  .copilot:not(.collapsed) {
    position: fixed;
    z-index: 24;
    inset: 54px 0 0;
    height: calc(100dvh - 54px);
    min-height: 0;
    width: 100% !important;
    max-width: none !important;
    border-left: 0;
    border-top: 1px solid var(--v7b-line-strong);
    transition: none;
  }
  .copilot.collapsed { flex: 0 0 0; height: 0; }
  .copilot-fab, .header-actions [aria-label="专注展开"], .header-actions [aria-label="恢复面板大小"] { display: none !important; }
}
.copilot-fab {
  position: fixed;
  right: 14px;
  bottom: 18px;
  z-index: 40;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  border: 1px solid var(--v7b-accent);
  background: var(--v7b-accent-soft);
  color: var(--v7b-accent);
  font-weight: 700;
  font-size: 13px;
  line-height: 1;
  letter-spacing: 1.5px;
  display: grid;
  place-items: center;
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  user-select: none;
  cursor: pointer;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
.copilot-header {
  min-height: 50px;
  flex-shrink: 0;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--v7b-line);
  background: var(--v7b-surface);
}
.title-wrap { display: flex; gap: 10px; align-items: center; }
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #55d98c;
  box-shadow: 0 0 0 3px rgba(85, 217, 140, 0.15);
}
.title { font-size: 13px; font-weight: 650; color: var(--v7b-text); }
.sub { font-size: 10px; color: var(--v7b-muted); margin-top: 1px; }
.header-actions { display: flex; gap: 4px; }
.icon-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--v7b-line);
  background: transparent;
  color: var(--v7b-muted);
  cursor: pointer;
  border-radius: 6px;
}
.icon-btn:hover { border-color: var(--v7b-accent); color: var(--v7b-accent); }
.header-text { width: auto; padding: 0 7px; font-size: 12px; white-space: nowrap; }
.icon-btn.on { border-color: var(--v7b-accent); color: var(--v7b-accent); background: var(--v7b-accent-soft); }

.history-panel {
  flex-shrink: 0;
  max-height: 42%;
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--v7b-line);
  background: var(--v7b-surface-2);
}
.history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  color: var(--v7b-muted);
  font-size: 11px;
  font-weight: 600;
}
.text-btn {
  border: 0;
  background: transparent;
  color: var(--v7b-muted);
  cursor: pointer;
  font-size: 11px;
}
.text-btn:hover { color: var(--v7b-accent); }
.history-empty {
  padding: 16px 12px 20px;
  color: var(--v7b-muted);
  font-size: 12px;
  text-align: center;
}
.history-list {
  list-style: none;
  margin: 0;
  padding: 0 0 8px;
  overflow-y: auto;
}
.history-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 28px;
  gap: 2px;
  align-items: stretch;
  padding: 0 6px;
}
.history-item.active .history-main {
  border-color: var(--v7b-line-strong);
  background: var(--v7b-accent-soft);
}
.history-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  text-align: left;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  cursor: pointer;
}
.history-main:hover { background: var(--v7b-surface-2); }
.history-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--v7b-text);
  font-size: 12px;
}
.history-meta {
  color: var(--v7b-muted);
  font-size: 10px;
}
.history-del {
  border: 0;
  background: transparent;
  color: var(--v7b-muted);
  font-size: 16px;
  cursor: pointer;
  border-radius: 6px;
}
.history-del:hover { color: #b42318; background: var(--v7b-surface-2); }

.starter {
  border-bottom: 1px solid var(--v7b-line);
  background: var(--v7b-surface-2);
  padding: 8px 0 10px;
}
.starter-row,
.live-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 12px 8px;
  max-height: 5.5rem;
  overflow: auto;
  scrollbar-width: thin;
}
.live-bar {
  padding: 8px 12px;
  border-bottom: 1px solid var(--v7b-line);
  background: var(--v7b-surface-2);
}
.live-spacer { flex: 1; min-width: 8px; }
.chip-rail {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 12px;
  max-height: 6rem;
  overflow-y: auto;
}
.page-pill,
.sel-pill,
.link-pill,
.chip {
  flex: 0 0 auto;
  border: 1px solid var(--v7b-line);
  background: var(--v7b-surface-2);
  color: var(--v7b-muted);
  font-size: 11px;
  padding: 5px 9px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  scroll-snap-align: start;
}
.page-pill { border-color: var(--v7b-line-strong); color: var(--v7b-accent); background: var(--v7b-accent-soft); }
.lab-pill {
  flex: 0 0 auto;
  border: 1px solid #f0d49a;
  background: #fff8e8;
  color: #9a6400;
  font-size: 11px;
  padding: 5px 9px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.lab-pill:hover { border-color: #9a6400; color: #9a6400; }
.sel-pill { border-color: #b7e4c7; color: #197a4b; background: #effaf4; display: inline-flex; align-items: center; gap: 4px; }
/* 上下文胶囊 + 独立关闭按钮：关闭是独立可聚焦控件，点标签本体才会发送消息。 */
.ctx-chip { display: inline-flex; align-items: center; gap: 2px; flex: 0 1 auto; min-width: 0; max-width: 100%; }
.ctx-chip .lab-pill,
.ctx-chip .sel-pill { display: block; flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.sel-pin {
  border: 0;
  background: transparent;
  color: var(--el-color-primary);
  cursor: pointer;
  font-family: inherit;
  font-size: 11px;
  padding: 2px 3px;
  white-space: nowrap;
}
.sent-context { margin: 0 0 6px; }
.sel-x {
  display: inline-grid;
  place-items: center;
  width: 24px;
  flex: 0 0 24px;
  height: 24px;
  padding: 0;
  border: 1px solid #b7e4c7;
  border-radius: 50%;
  background: #effaf4;
  color: #197a4b;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}
.sel-x:hover { color: #197a4b; background: #effaf4; border-color: #197a4b; }
.sel-x:focus-visible { outline: 2px solid var(--v7b-accent); outline-offset: 1px; }
.link-pill { color: var(--v7b-muted); }
.page-pill:hover,
.sel-pill:hover,
.link-pill:hover,
.chip:hover:not(:disabled) {
  border-color: var(--v7b-accent);
  color: var(--v7b-accent);
}
.chip:disabled { opacity: 0.5; cursor: not-allowed; }
.chip-vision { border-color: #b7e4c7; color: #197a4b; background: #effaf4; font-family: "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji", "Microsoft YaHei", sans-serif; }
.chip-vision:hover:not(:disabled) { border-color: #197a4b; color: #197a4b; }
.sm { padding: 3px 8px; font-size: 10.5px; }

.messages {
  min-height: 0;
  flex: 1;
  overflow: auto;
  padding: 10px 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  scrollbar-width: thin;
}
.tool-note {
  flex-shrink: 0;
  border: 1px dashed var(--v7b-line-strong);
  background: var(--v7b-accent-soft);
  color: var(--v7b-accent);
  font-size: 11px;
  padding: 6px 10px;
  border-radius: 8px;
}
.empty {
  margin-top: 18px;
  color: var(--v7b-muted);
  font-size: 12px;
  line-height: 1.6;
}
.empty-tip {
  margin-top: 6px;
  color: var(--v7b-muted);
  font-size: 11px;
  font-family: "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji", "Microsoft YaHei", sans-serif;
}
.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.msg.assistant { justify-content: flex-start; }
.bubble {
  min-width: 0;
  box-sizing: border-box;
  max-width: 100%;
  border-radius: 12px;
  padding: 10px 12px;
  border: 1px solid var(--v7b-line);
}
.msg.user .bubble { background: var(--v7b-accent-soft); border-color: var(--v7b-line-strong); }
.msg.assistant .bubble { background: var(--v7b-surface); }
.text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--v7b-text);
}
.md-body {
  font-size: 12.5px;
  line-height: 1.55;
  color: #1f2933;
  word-break: break-word;
}
.md-body :deep(p) { margin: 0 0 0.55em; }
.md-body :deep(p:last-child) { margin-bottom: 0; }
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) {
  margin: 0.4em 0 0.35em;
  color: #111827;
  font-weight: 650;
  line-height: 1.35;
}
.md-body :deep(h1) { font-size: 14px; }
.md-body :deep(h2) { font-size: 13.5px; }
.md-body :deep(h3) { font-size: 13px; }
.md-body :deep(ul),
.md-body :deep(ol) { margin: 0.35em 0 0.55em; padding-left: 1.25em; }
.md-body :deep(li) { margin: 0.15em 0; }
.md-body :deep(strong) { color: #111827; font-weight: 650; }
.md-body :deep(em) { color: #475467; }
.md-body :deep(.md-table-wrap) {
  margin: 0.55em 0 0.7em;
  overflow-x: auto;
  border: 1px solid #dbe3ea;
  border-radius: 8px;
}
.md-body :deep(.md-table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
  line-height: 1.45;
}
.md-body :deep(.md-table th),
.md-body :deep(.md-table td) {
  padding: 7px 9px;
  border-bottom: 1px solid #e2e8ef;
  text-align: left;
  vertical-align: top;
  color: #1f2933;
  /* Keep protocol names and address tokens intact. The table wrapper owns
     horizontal scrolling when an observation has more columns than fit. */
  word-break: normal;
  overflow-wrap: normal;
}
.md-body :deep(.md-table th) {
  background: #f2f6fa;
  color: #475467;
  font-weight: 650;
  white-space: nowrap;
}
.md-body :deep(.md-table tr:last-child td) { border-bottom: 0; }
.md-body :deep(.md-table tbody tr:nth-child(even) td) { background: #f8fafc; }
.md-body :deep(.md-inline) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  padding: 1px 5px;
  border-radius: 4px;
  background: #eef2f7;
  border: 1px solid #d7e0ea;
  color: #0f3d5c;
}
.md-body :deep(.code-block) {
  margin: 0.55em 0;
  border: 1px solid #d7e0ea;
  border-radius: 8px;
  overflow: hidden;
  background: #f7f9fc;
}
.md-body :deep(.code-toolbar) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 8px;
  border-bottom: 1px solid #dde5ee;
  background: #eef2f7;
}
.md-body :deep(.code-lang) {
  font-size: 10px;
  color: #52606d;
  text-transform: lowercase;
}
.md-body :deep(.code-actions) { display: flex; gap: 4px; }
.md-body :deep(.code-copy),
.md-body :deep(.code-deploy) {
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #334155;
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 4px;
  cursor: pointer;
}
.md-body :deep(.code-copy:hover),
.md-body :deep(.code-deploy:hover) {
  border-color: #2f6fba;
  color: #2f6fba;
}
.md-body :deep(pre) { margin: 0; padding: 10px 12px; overflow-x: auto; }
.md-body :deep(pre code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  line-height: 1.5;
  color: #1f2933;
  white-space: pre;
}
.caret {
  display: inline-block;
  width: 7px;
  height: 13px;
  margin-left: 2px;
  vertical-align: -2px;
  background: var(--v7b-accent);
  animation: blink 1s step-end infinite;
}
@keyframes blink { 50% { opacity: 0; } }
.bubble.streaming { border-color: var(--v7b-line-strong); }
.sources {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--v7b-line);
}
.sources-title { font-size: 11px; color: var(--v7b-muted); margin-bottom: 4px; }
.source-item { font-size: 11.5px; color: var(--v7b-muted); line-height: 1.5; }
.draft-actions { display: flex; gap: 6px; margin-top: 10px; }
.draft-target { flex-basis: 100%; font-size: 12px; color: var(--v7b-muted); }
.draft-refused {
  margin-top: 8px;
  padding: 6px 9px;
  border: 1px solid #f0d49a;
  border-radius: 6px;
  background: #fff8e8;
  color: #9a6400;
  font-size: 11.5px;
  line-height: 1.6;
}
.msg-time {
  margin-top: 6px;
  font-size: 11px;
  color: var(--v7b-muted);
  text-align: right;
  user-select: none;
  line-height: 1;
}
.draft-btn {
  border: 1px solid var(--v7b-line);
  background: transparent;
  color: var(--v7b-muted);
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 6px;
  cursor: pointer;
}
.draft-btn.primary { border-color: var(--v7b-accent); color: var(--v7b-accent); }
.carry-hint {
  margin: 0 0 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--v7b-accent-soft);
  color: var(--v7b-accent);
  font-size: 11px;
  line-height: 1.4;
}
.composer {
  flex-shrink: 0;
  border-top: 1px solid var(--v7b-line);
  padding: 10px 12px 12px;
  background: var(--v7b-surface);
}
.attach-preview {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.attach-item {
  position: relative;
  width: 46px;
  height: 46px;
  border: 1px solid var(--v7b-line);
  border-radius: 8px;
  overflow: hidden;
  flex-shrink: 0;
}
.attach-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.attach-file {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  padding: 4px;
  box-sizing: border-box;
  font-size: 9px;
  line-height: 1.25;
  color: var(--v7b-muted);
  background: var(--v7b-surface-2);
  text-align: center;
  word-break: break-all;
  overflow: hidden;
}
.attach-del {
  position: absolute;
  top: 1px;
  right: 1px;
  width: 16px;
  height: 16px;
  border: 0;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.65);
  color: #ff8f8f;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
  padding: 0;
}
.attach-del:hover { background: rgba(120, 0, 0, 0.75); color: #fff; }
.attach-add {
  width: 46px;
  height: 46px;
  border: 1px dashed var(--v7b-line);
  border-radius: 8px;
  background: transparent;
  color: var(--v7b-muted);
  font-size: 18px;
  cursor: pointer;
  flex-shrink: 0;
}
.attach-add:hover { border-color: var(--v7b-accent); color: var(--v7b-accent); }
.attach-hint {
  font-size: 11px;
  color: var(--v7b-muted);
  line-height: 1.4;
  max-width: 180px;
}
.attach-hint-off { color: var(--v7b-muted); }
.composer-row {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.composer-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.attach-btn {
  min-width: 44px;
  height: 28px;
  padding: 0 8px;
  border: 1px solid var(--v7b-line);
  background: transparent;
  color: var(--v7b-muted);
  display: grid;
  place-items: center;
  cursor: pointer;
  border-radius: 8px;
}
.attach-btn-label {
  font-size: 11px;
  line-height: 1;
  letter-spacing: 1px;
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}
.attach-btn:hover { border-color: var(--v7b-accent); color: var(--v7b-accent); }
.msg-attachments {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.msg-img {
  max-width: 210px;
  max-height: 140px;
  border: 1px solid var(--v7b-line);
  border-radius: 8px;
  cursor: zoom-in;
  display: block;
}
.msg-file-tag {
  display: inline-flex;
  align-items: center;
  max-width: 180px;
  padding: 4px 9px;
  border: 1px solid var(--v7b-line-strong);
  border-radius: 6px;
  background: var(--v7b-accent-soft);
  color: var(--v7b-accent);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.zoom-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(0, 0, 0, 0.78);
  display: grid;
  place-items: center;
  cursor: zoom-out;
}
.zoom-img {
  max-width: 92vw;
  max-height: 88vh;
  border-radius: 8px;
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.6);
}
.zoom-close {
  position: absolute;
  top: 14px;
  right: 18px;
  width: 34px;
  height: 34px;
  border: 1px solid var(--v7b-line-strong);
  border-radius: 50%;
  background: rgba(20, 30, 40, 0.9);
  color: var(--v7b-text);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
}
.zoom-close:hover { border-color: var(--v7b-accent); color: var(--v7b-accent); }
.composer textarea {
  width: 100%;
  resize: none;
  border: 1px solid var(--v7b-line);
  border-radius: 10px;
  background: var(--v7b-surface-2);
  color: var(--v7b-text);
  padding: 10px;
  font-size: 12.5px;
  line-height: 1.45;
  outline: none;
  box-sizing: border-box;
}
.composer textarea:focus { border-color: var(--v7b-accent); }
.composer-row {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.draft-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--v7b-muted);
  user-select: none;
}
.send-btn {
  border: 0;
  background: var(--v7b-accent);
  color: #ffffff;
  font-weight: 650;
  font-size: 12px;
  padding: 7px 14px;
  border-radius: 8px;
  cursor: pointer;
}
.send-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.stop-btn {
  border: 0;
  background: #8a4b2f;
  color: #f5e6d5;
  font-weight: 650;
  font-size: 12px;
  padding: 7px 14px;
  border-radius: 8px;
  cursor: pointer;
}
.stop-btn:hover { background: #a55a38; }
@media (max-width: 1100px) {
  .copilot-header { padding-block: 5px !important; }
  .display-settings { display: none; }
  .starter { padding-block: 5px; }
  .starter-row { padding-bottom: 4px; }
  .messages { padding-block: 6px; }
  .composer { padding-block: 6px; }
  .composer textarea { min-height: 42px; height: 48px; }
  .composer .attach-hint-off { display: none; }
}
@media (max-width: 1100px) and (max-height: 540px) {
  .copilot:not(.collapsed) { flex-basis: min(64dvh, 350px); }
}

.citation-mask { position: absolute; inset: 0; z-index: 40; background: rgba(10, 18, 26, .55); display: flex; align-items: stretch; justify-content: center; }
.citation-panel { min-width: 0; margin: 16px; flex: 1; background: #fff; color: #1f2933; border-radius: 10px; display: flex; flex-direction: column; min-height: 0; box-shadow: 0 12px 32px rgba(0,0,0,.35); }
.citation-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 12px; border-bottom: 1px solid #e2e8ef; font-size: 13px; }
.citation-meta { margin: 8px 12px 0; color: var(--v7b-muted); font-size: 11.5px; }
.citation-heading { min-width: 0; display: grid; gap: 3px; }
.citation-body { position: relative; flex: 1; overflow: auto; margin: 8px 12px; padding: 10px; background: #f8fafc; border: 1px solid #e2e8ef; border-radius: 6px; font-family: inherit; font-size: 12px; line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.citation-body pre { margin: 0; font: inherit; white-space: pre-wrap; overflow-wrap: anywhere; }
.citation-reviews { margin-top: 14px; }
.citation-review { margin-top: 6px; padding: 10px; border: 1px solid #c6d8ef; border-radius: 6px; background: #edf4fd; color: #233b58; white-space: normal; }
.citation-review p { margin: 6px 0 0; }
.citation-review a { color: #245f9e; text-decoration: underline; }
.citation-foot { padding: 8px 12px 12px; display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
.citation-error { margin: 12px; padding: 10px; background: #fff4f4; border: 1px solid #f0c2c2; color: #8a2c2c; border-radius: 6px; font-size: 12px; }
summary.sources-title { width: fit-content; cursor: pointer; }
.source-link { display: grid; gap: 2px; width: 100%; overflow-wrap: anywhere; margin-top: 5px; background: var(--v7b-surface); border: 1px solid var(--v7b-line); border-radius: 6px; padding: 6px 8px; text-align: left; cursor: pointer; }
.source-link strong { color: var(--v7b-accent); }
.source-link:hover { border-color: var(--v7b-accent); }
.source-book { color: var(--v7b-muted); font-size: 11.5px; overflow-wrap: anywhere; }
.source-page { color: var(--v7b-accent); font-size: 12px; font-weight: 650; }
.source-review { color: var(--v7b-muted); }
.offline-help { margin-top: 6px; color: var(--v7b-muted); font-size: 12px; }

.copilot :focus-visible { outline: 2px solid var(--v7b-accent); outline-offset: 2px; }
.md-body :deep(.citation-inline) { color: var(--v7b-accent); background: var(--v7b-accent-soft); border: 0; border-radius: 4px; padding: 1px 4px; cursor: pointer; font: inherit; }
.md-body :deep(.citation-unmatched) { color: #80531c; background: #fff5e5; border-radius: 4px; padding: 1px 3px; font-size: .9em; overflow-wrap: anywhere; }
.citation-head strong { min-width: 0; overflow-wrap: anywhere; }
.citation-meta { overflow-wrap: anywhere; }
.draft-actions, .composer-row { flex-wrap: wrap; }
.saved-attachment-text { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 55vh; overflow: auto; }
.saved-attachment-image { display: block; max-width: 100%; max-height: 55vh; object-fit: contain; margin-bottom: 12px; }
.title-wrap { flex-shrink: 0; }
.copilot-header { gap: 8px; flex-wrap: wrap; padding-block: 8px; }
.header-actions { margin-left: auto; }
@media (prefers-reduced-motion: reduce) { .copilot { transition: none; } .caret { animation: none; } }
</style>
