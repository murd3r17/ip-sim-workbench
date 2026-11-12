import { parseApiTime } from '../utils/datetime'
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'

export type CopilotRole = 'user' | 'assistant' | 'system'

export interface CopilotAttachment {
  contentString: string
  mime?: string
  name?: string
}

export interface CopilotMessage {
  id: string
  role: CopilotRole
  content: string
  reasoning?: string
  reasoningOpen?: boolean
  sources?: Array<{ source_id?: string; filename?: string; title?: string; score?: number; content?: string; version?: string; captured_at?: string }>
  knowledgeStatus?: string
  draftCommands?: string[]
  draftTarget?: { deviceId: number; label: string; alarmId?: number | string; verifiedByServer?: boolean } | null
  draftRefused?: string
  cancelled?: boolean
  attachments?: CopilotAttachment[]
  streaming?: boolean
  requestId?: string
  requestState?: 'pending' | 'completed' | 'failed' | 'cancelled' | 'interrupted' | 'unconfirmed'
  recovered?: boolean
  createdAt: number
}

export interface CopilotSelection {
  kind: 'device' | 'alarm' | 'topology' | 'other'
  id?: number | string
  label: string
  detail?: string
  model?: string
}

export interface CopilotConversation {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: CopilotMessage[]
  serverRevision?: number
  pendingSync?: boolean
  conflicted?: boolean
  syncError?: string
}

const STORAGE_KEY = 'ai_copilot_sessions_v1'
const ACTIVE_KEY = 'ai_copilot_active_id'
const MAX_SESSIONS = 40

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function titleFromMessages(msgs: CopilotMessage[]) {
  const firstUser = msgs.find((m) => m.role === 'user' && m.content.trim())
  if (!firstUser) return '新对话'
  const text = firstUser.content.trim().replace(/\s+/g, ' ')
  return text.length > 28 ? `${text.slice(0, 28)}…` : text
}

// 持久化前压缩附件：图片降采样（canvas 缩至宽 300px、JPEG 0.7），文本截断，
// 每会话最多保留 MAX_STORED_ATTACH 个附件——防止 localStorage 5MB 撑爆。
const MAX_STORED_ATTACH = 3
const MAX_TEXT_ATTACH_CHARS = 5000

function compressAttachmentForStorage(att: CopilotAttachment): CopilotAttachment {
  if (!att || !att.contentString) return att
  if (att.contentString.startsWith('data:image/')) {
    // data URL 解码是异步的：此前赋值 img.src 后立刻读 img.complete，
    // 通常还没解码完 → 走不到降采样分支，原图（可能十几 MB）被塞进 localStorage。
    // 这里改为同步返回原图、由调用方 await 压缩结果。
    try {
      const img = new Image()
      img.src = att.contentString
      if (img.complete && img.naturalWidth > 0) {
        const shrunk = drawScaled(img, att)
        if (shrunk) return shrunk
      }
    } catch {
      /* 压缩失败则保留原样 */
    }
  } else if (att.contentString.length > MAX_TEXT_ATTACH_CHARS) {
    return { ...att, contentString: att.contentString.slice(0, MAX_TEXT_ATTACH_CHARS) + '\n[附件内容已截断(历史)]' }
  }
  return att
}

function drawScaled(img: HTMLImageElement, att: CopilotAttachment): CopilotAttachment | null {
  const scale = Math.min(1, 300 / img.naturalWidth)
  const w = Math.max(1, Math.round(img.naturalWidth * scale))
  const h = Math.max(1, Math.round(img.naturalHeight * scale))
  const cnv = document.createElement('canvas')
  cnv.width = w
  cnv.height = h
  const ctx = cnv.getContext('2d')
  if (!ctx) return null
  ctx.drawImage(img, 0, 0, w, h)
  const dataUrl = cnv.toDataURL('image/jpeg', 0.7)
  if (dataUrl.length < att.contentString.length) {
    return { ...att, contentString: dataUrl }
  }
  return null
}

/** 等图片解码完成后再降采样（localStorage 持久化前调用）。 */
export function compressAttachmentAsync(att: CopilotAttachment): Promise<CopilotAttachment> {
  if (!att || !att.contentString || !att.contentString.startsWith('data:image/')) {
    return Promise.resolve(compressAttachmentForStorage(att))
  }
  return new Promise((resolve) => {
    const img = new Image()
    const done = () => {
      try {
        resolve(drawScaled(img, att) || att)
      } catch {
        resolve(att)
      }
    }
    img.onload = done
    img.onerror = () => resolve(att)
    img.src = att.contentString
    if (img.complete && img.naturalWidth > 0) done()
  })
}

function sanitizeMessages(msgs: CopilotMessage[]): CopilotMessage[] {
  return msgs.map((m) => ({
    ...m,
    streaming: false,
    reasoningOpen: m.reasoningOpen ?? false,
  }))
}

function storedMessagesEqual(left: CopilotMessage[], right: CopilotMessage[]): boolean {
  // MySQL JSON storage may return object keys in a different order.
  const stable = (value: unknown) => JSON.stringify(value, (_key, item) =>
    item && typeof item === 'object' && !Array.isArray(item)
      ? Object.fromEntries(Object.keys(item).sort().filter((key) => key !== 'streaming' && key !== 'reasoningOpen').map((key) => [key, item[key]]))
      : item)
  return stable(left) === stable(right)
}

function shrinkForStorage(msgs: CopilotMessage[]): CopilotMessage[] {
  let nth = 0
  return msgs.map((m) => {
    if (!m.attachments?.length) return m
    nth++
    // 同步压缩只处理"已经解码完成"的图片（同步路径）；
    // 真正的降采样由 persist() 里的 compressAttachmentAsync 异步补齐。
    const atts = m.attachments.map(compressAttachmentForStorage)
    return {
      ...m,
      attachments: nth <= MAX_STORED_ATTACH ? atts : [],
      // 第 4+ 个带附件消息：占位提示，只存文字
    }
  })
}

/** 异步版：把消息里的图片附件全部降采样后再落盘（避免原图撑爆 localStorage）。 */
async function shrinkForStorageAsync(msgs: CopilotMessage[]): Promise<CopilotMessage[]> {
  const compressed = await Promise.all(
    msgs.map(async (m) => {
      if (!m.attachments?.length) return m
      const atts = await Promise.all(m.attachments.map((a) => compressAttachmentAsync(a)))
      return { ...m, attachments: atts }
    }),
  )
  return shrinkForStorage(compressed)
}

function loadSessions(): { conversations: CopilotConversation[]; activeId: string | null } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const activeId = localStorage.getItem(ACTIVE_KEY)
    if (!raw) return { conversations: [], activeId: null }
    const parsed = JSON.parse(raw) as CopilotConversation[]
    if (!Array.isArray(parsed)) return { conversations: [], activeId: null }
    const conversations = parsed
      .filter((c) => c && c.id && Array.isArray(c.messages))
      .map((c) => ({
        ...c,
        title: c.title || titleFromMessages(c.messages),
        createdAt: c.createdAt || Date.now(),
        updatedAt: c.updatedAt || c.createdAt || Date.now(),
        messages: sanitizeMessages(c.messages),
      }))
      .sort((a, b) => b.updatedAt - a.updatedAt)
    const validActive = activeId && conversations.some((c) => c.id === activeId) ? activeId : conversations[0]?.id || null
    return { conversations, activeId: validActive }
  } catch {
    return { conversations: [], activeId: null }
  }
}

export const useAiCopilotStore = defineStore('aiCopilot', () => {
  const open = ref(localStorage.getItem('ai_copilot_open') !== '0')
  const width = ref(Number(localStorage.getItem('ai_copilot_width') || 380))
  const loading = ref(false)
  const historyOpen = ref(false)

  const boot = loadSessions()
  const conversations = ref<CopilotConversation[]>(boot.conversations)
  const activeId = ref<string | null>(boot.activeId)
  const messages = ref<CopilotMessage[]>(
    boot.activeId
      ? sanitizeMessages(boot.conversations.find((c) => c.id === boot.activeId)?.messages || [])
      : []
  )

  const routePath = ref('')
  const pageName = ref('')
  const evidenceId = ref<number | null>(null)
  const selection = ref<CopilotSelection | null>(null)
  const notes = ref('')

  const contextLabel = computed(() => {
    const page = pageName.value || routePath.value || '工作台'
    if (selection.value?.label) return `${page} · ${selection.value.label}`
    return page
  })

  const selectionText = computed(() => {
    if (!selection.value) return ''
    const s = selection.value
    return [s.kind, s.label, s.detail, s.id != null ? `id=${s.id}` : '']
      .filter(Boolean)
      .join(' | ')
  })

  const historyList = computed(() =>
    [...conversations.value].sort((a, b) => b.updatedAt - a.updatedAt)
  )

  const activeTitle = computed(() => {
    const cur = conversations.value.find((c) => c.id === activeId.value)
    return cur?.title || '新对话'
  })
  const activeSyncError = computed(() => conversations.value.find((c) => c.id === activeId.value)?.syncError || '')
  const activeSyncConflict = computed(() => Boolean(conversations.value.find((c) => c.id === activeId.value)?.conflicted))

  // ── 后端持久化辅助（localStorage 为主，后端为增强备份/跨浏览器） ──
  let sessionEpoch = 0
  let persistenceGeneration = 0
  const syncTimers = new Map<string, number>()
  const dirtyVersions = new Map<string, number>()
  const inFlight = new Map<string, Promise<void>>()

  function scheduleBackendSync(id: string, markDirty = true) {
    if (markDirty) dirtyVersions.set(id, (dirtyVersions.get(id) || 0) + 1)
    if (conversations.value.find((c) => c.id === id)?.conflicted) return
    const timer = syncTimers.get(id)
    if (timer !== undefined) window.clearTimeout(timer)
    syncTimers.set(id, window.setTimeout(() => {
      syncTimers.delete(id)
      void syncConversationToBackend(id)
    }, 3000))
  }

  function markSyncError(id: string, conflicted: boolean) {
    const current = conversations.value.find((c) => c.id === id)
    if (!current) return
    current.conflicted = conflicted
    current.syncError = conflicted
      ? '会话版本冲突，本地内容已保留。可另存为新会话后继续同步。'
      : '会话暂未同步到服务器，本地内容已保留。'
    ElMessage.warning({ message: current.syncError, grouping: true })
    persist()
  }

  async function syncConversationToBackend(id: string): Promise<void> {
    if (inFlight.has(id)) return
    const conversation = conversations.value.find((c) => c.id === id)
    if (!conversation || conversation.conflicted) return
    const epoch = sessionEpoch
    const sentVersion = dirtyVersions.get(id)
    const payload = { title: conversation.title || '新对话', messages: shrinkForStorage(conversation.messages) }
    let revision = conversation.serverRevision
    const stillCurrent = () => epoch === sessionEpoch && conversations.value.some((c) => c.id === id)
    const task = (async () => {
      try {
        const { saveCopilotSession, getCopilotSession } = await import('../api/ai')
        if (!stillCurrent()) return
        if (revision === undefined) {
          const remote = await getCopilotSession(id, { silent: true })
          if (!stillCurrent()) return
          // Older local caches have no server revision. Only adopt one if the
          // content matches; guessing it would silently overwrite remote edits.
          if (remote.exists && (remote.title !== payload.title ||
              !storedMessagesEqual(shrinkForStorage(sanitizeMessages(remote.messages)), payload.messages))) {
            markSyncError(id, true)
            return
          }
          revision = remote.exists ? remote.revision : undefined
        }
        const saved = await saveCopilotSession(id, { ...payload, revision }, { silent: true })
        if (!stillCurrent()) return
        const current = conversations.value.find((c) => c.id === id)!
        current.serverRevision = saved.revision
        current.syncError = undefined
        if (dirtyVersions.get(id) === sentVersion) {
          current.pendingSync = false
          dirtyVersions.delete(id)
        }
        persist()
      } catch (error) {
        if (stillCurrent()) markSyncError(id, (error as { response?: { status?: number } })?.response?.status === 409)
      } finally {
        if (epoch === sessionEpoch) {
          inFlight.delete(id)
          if (stillCurrent() && dirtyVersions.has(id) && dirtyVersions.get(id) !== sentVersion) {
            scheduleBackendSync(id, false)
          }
        }
      }
    })()
    inFlight.set(id, task)
    return task
  }

  async function flushConversation(id = activeId.value): Promise<boolean> {
    if (!id) return false
    const epoch = sessionEpoch
    // An older save can be in flight when the request placeholder is inserted.
    // Wait for its revision, then persist the pending request identity as well.
    for (let attempt = 0; attempt < 2; attempt++) {
      const timer = syncTimers.get(id)
      if (timer !== undefined) window.clearTimeout(timer)
      syncTimers.delete(id)
      await inFlight.get(id)
      const current = conversations.value.find((c) => c.id === id)
      if (epoch !== sessionEpoch || !current || current.conflicted) return false
      if (!dirtyVersions.has(id)) return !current.pendingSync
      const version = dirtyVersions.get(id)
      await syncConversationToBackend(id)
      // A failed unchanged save remains visible and pending; don't immediately
      // retry it. A second iteration is only for edits made during the save.
      if (dirtyVersions.get(id) === version) return false
    }
    return epoch === sessionEpoch && !dirtyVersions.has(id)
      && Boolean(conversations.value.some((c) => c.id === id && !c.pendingSync))
  }

  function saveConflictAsNew(id = activeId.value) {
    const original = conversations.value.find((c) => c.id === id)
    if (!original || loading.value) return
    const copy: CopilotConversation = {
      id: newId(), title: `${original.title}（本地副本）`, createdAt: Date.now(), updatedAt: Date.now(),
      messages: sanitizeMessages(original.messages), pendingSync: true,
    }
    conversations.value.unshift(copy)
    activeId.value = copy.id
    messages.value = sanitizeMessages(copy.messages)
    persist()
    scheduleBackendSync(copy.id)
  }

  async function loadFromBackend(): Promise<void> {
    const epoch = sessionEpoch
    try {
      const { getCopilotSessions, getCopilotSession } = await import('../api/ai')
      const metas = await getCopilotSessions()
      if (epoch !== sessionEpoch || !Array.isArray(metas)) return
      // 合并：仅拉取本地没有的会话，避免覆盖本地最新
      const localIds = new Set(conversations.value.map((c) => c.id))
      const remote = metas.filter((m) => m && m.id && !localIds.has(m.id))
      for (const m of remote.slice(0, 20)) {
        try {
          const full = await getCopilotSession(m.id)
          if (epoch !== sessionEpoch) return
          if (full?.exists && Array.isArray(full.messages)) {
            conversations.value.unshift({
              id: full.id,
              title: full.title || '新对话',
              createdAt: full.created_at ? parseApiTime(full.created_at)?.getTime() ?? 0 : Date.now(),
              updatedAt: full.updated_at ? (parseApiTime(full.updated_at)?.getTime() ?? Date.now()) : Date.now(),
              messages: sanitizeMessages(full.messages),
              serverRevision: full.revision,
            })
          }
        } catch {
          /* 单条失败跳过 */
        }
      }
      if (remote.length) {
        conversations.value.sort((a, b) => b.updatedAt - a.updatedAt)
        conversations.value = conversations.value.slice(0, MAX_SESSIONS)
        persist()
      }
      for (const c of conversations.value) if (c.pendingSync) scheduleBackendSync(c.id)
    } catch {
      /* 静默 */
    }
  }

  function persist() {
    const generation = ++persistenceGeneration
    try {
      const trimmed = [...conversations.value]
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, MAX_SESSIONS)
      conversations.value = trimmed
      // 持久化前压缩附件（图片降采样/文本截断），防 localStorage 撑爆
      const storePayload = trimmed.map((c) => ({
        ...c,
        messages: shrinkForStorage(c.messages),
      }))
      const snapshot = JSON.stringify(storePayload)
      localStorage.setItem(STORAGE_KEY, snapshot)
      if (activeId.value) localStorage.setItem(ACTIVE_KEY, activeId.value)
      else localStorage.removeItem(ACTIVE_KEY)
      // 图片降采样需要等 data URL 解码完成；同步写完后异步再压一次，
      // 只有压得更小才覆盖（避免原图长期占用 localStorage 配额）。
      void compressStoredAttachments(trimmed, generation, snapshot)
    } catch {
      // 配额超限时降级：丢弃全部附件再存一次（保住文字历史）
      try {
        const trimmed = conversations.value.slice(0, MAX_SESSIONS)
        const bare = trimmed.map((c) => ({
          ...c,
          messages: c.messages.map((m) => ({ ...m, attachments: undefined })),
        }))
        localStorage.setItem(STORAGE_KEY, JSON.stringify(bare))
      } catch {
        /* 彻底失败则忽略 */
      }
    }
  }

  async function compressStoredAttachments(convs: CopilotConversation[], generation: number, snapshot: string) {
    try {
      const compressed = await Promise.all(
        convs.map(async (c) => ({ ...c, messages: await shrinkForStorageAsync(c.messages) })),
      )
      if (generation !== persistenceGeneration || localStorage.getItem(STORAGE_KEY) !== snapshot) return
      const next = JSON.stringify(compressed)
      if (next.length < snapshot.length) localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* 解码/配额失败：同步版本已经写入，忽略 */
    }
  }

  function syncActiveToList() {
    if (!activeId.value) return
    const idx = conversations.value.findIndex((c) => c.id === activeId.value)
    const now = Date.now()
    const payload: CopilotConversation = {
      ...(idx >= 0 ? conversations.value[idx] : {}),
      id: activeId.value,
      title: titleFromMessages(messages.value),
      createdAt: idx >= 0 ? conversations.value[idx].createdAt : now,
      updatedAt: now,
      messages: sanitizeMessages(messages.value),
      pendingSync: true,
    }
    if (idx >= 0) conversations.value[idx] = payload
    else conversations.value.unshift(payload)
    persist()
    scheduleBackendSync(payload.id)
  }

  function ensureActiveConversation() {
    if (activeId.value && conversations.value.some((c) => c.id === activeId.value)) return
    const id = newId()
    const now = Date.now()
    conversations.value.unshift({
      id,
      title: '新对话',
      createdAt: now,
      updatedAt: now,
      messages: [],
    })
    activeId.value = id
    messages.value = []
    persist()
  }

  function resetSession() {
    // Invalidate pending compression, remote reads and acknowledgements too.
    sessionEpoch++
    persistenceGeneration++
    for (const timer of syncTimers.values()) window.clearTimeout(timer)
    syncTimers.clear()
    dirtyVersions.clear()
    inFlight.clear()
    conversations.value = []
    activeId.value = null
    messages.value = []
    selection.value = null
    notes.value = ''
    historyOpen.value = false
    localStorage.removeItem(STORAGE_KEY)
    localStorage.removeItem(ACTIVE_KEY)
    localStorage.removeItem('ai_copilot_open')
    localStorage.removeItem('ai_copilot_width')
  }

  function setOpen(v: boolean) {
    open.value = v
    localStorage.setItem('ai_copilot_open', v ? '1' : '0')
    if (!v) historyOpen.value = false
  }

  function toggle() {
    setOpen(!open.value)
  }

  function setHistoryOpen(v: boolean) {
    historyOpen.value = v
  }

  function toggleHistory() {
    historyOpen.value = !historyOpen.value
  }

  function setWidth(w: number) {
    width.value = Math.min(560, Math.max(320, w))
    localStorage.setItem('ai_copilot_width', String(width.value))
  }

  function setPageContext(path: string, name: string) {
    routePath.value = path
    pageName.value = name
  }

  function setEvidenceId(v: number | null) { evidenceId.value = v }
  function setSelection(sel: CopilotSelection | null) {
    selection.value = sel
  }

  function setNotes(text: string) {
    notes.value = text
  }

  /** Archive current (if any messages) and start a blank chat. */
  function newChat() {
    if (messages.value.some((m) => m.content.trim())) {
      syncActiveToList()
    } else if (activeId.value) {
      // drop empty current from list
      conversations.value = conversations.value.filter((c) => c.id !== activeId.value)
    }
    const id = newId()
    const now = Date.now()
    conversations.value.unshift({
      id,
      title: '新对话',
      createdAt: now,
      updatedAt: now,
      messages: [],
    })
    activeId.value = id
    messages.value = []
    persist()
    historyOpen.value = false
  }

  /** @deprecated use newChat — kept for call sites expecting clear */
  function clearChat() {
    newChat()
  }

  function switchConversation(id: string) {
    if (id === activeId.value) {
      historyOpen.value = false
      return
    }
    if (messages.value.length) syncActiveToList()
    const target = conversations.value.find((c) => c.id === id)
    if (!target) return
    activeId.value = id
    messages.value = sanitizeMessages(target.messages)
    persist()
    historyOpen.value = false
  }

  function deleteConversation(id: string) {
    const wasActive = activeId.value === id
    conversations.value = conversations.value.filter((c) => c.id !== id)
    const timer = syncTimers.get(id)
    if (timer !== undefined) window.clearTimeout(timer)
    syncTimers.delete(id)
    dirtyVersions.delete(id)
    // Let an already-sent save finish before deleting, so it cannot recreate
    // the remote conversation after the delete request.
    const epoch = sessionEpoch
    const pending = inFlight.get(id)
    void (async () => {
      await pending
      if (epoch !== sessionEpoch) return
      const { deleteCopilotSession } = await import('../api/ai')
      if (epoch === sessionEpoch) await deleteCopilotSession(id)
    })().catch(() => undefined)
    if (wasActive) {
      const next = conversations.value[0]
      if (next) {
        activeId.value = next.id
        messages.value = sanitizeMessages(next.messages)
      } else {
        activeId.value = null
        messages.value = []
        ensureActiveConversation()
      }
    }
    persist()
  }

  function pushMessage(msg: Omit<CopilotMessage, 'id' | 'createdAt'> & { id?: string }) {
    ensureActiveConversation()
    const id = msg.id || newId()
    messages.value.push({
      id,
      role: msg.role,
      content: msg.content,
      reasoning: msg.reasoning || '',
      reasoningOpen: msg.reasoningOpen ?? true,
      sources: msg.sources,
      knowledgeStatus: msg.knowledgeStatus,
      draftCommands: msg.draftCommands,
      draftTarget: msg.draftTarget,
      attachments: msg.attachments,
      streaming: msg.streaming,
      requestId: msg.requestId,
      requestState: msg.requestState,
      createdAt: Date.now(),
    })
    syncActiveToList()
    return id
  }

  function appendContent(id: string, text: string) {
    const msg = messages.value.find((m) => m.id === id)
    if (!msg || !text) return
    msg.content += text
  }

  function appendReasoning(id: string, text: string) {
    const msg = messages.value.find((m) => m.id === id)
    if (!msg || !text) return
    msg.reasoning = (msg.reasoning || '') + text
    msg.reasoningOpen = true
  }

  function patchMessage(id: string, patch: Partial<CopilotMessage>) {
    const msg = messages.value.find((m) => m.id === id)
    if (!msg) return
    Object.assign(msg, patch)
  }

  function saveDraftToDeploy(commands: string[], target: CopilotMessage['draftTarget'] = null) {
    const text = commands.join('\n')
    localStorage.setItem('deploy_ai_draft', text)
    // Content match prevents stale metadata from binding a replaced/legacy draft.
    localStorage.setItem('deploy_ai_draft_context', JSON.stringify({ text, target }))
    localStorage.setItem('deploy_ai_draft_at', String(Date.now()))
    return text
  }

  // Persist after streaming finishes (streaming:false patches)
  watch(
    () => messages.value.map((m) => `${m.id}:${m.content.length}:${m.streaming ? 1 : 0}`).join('|'),
    () => {
      if (!activeId.value || loading.value) return
      if (!messages.value.length) return
      syncActiveToList()
    }
  )

  return {
    open,
    evidenceId,
    setEvidenceId,
    width,
    loading,
    historyOpen,
    messages,
    conversations,
    activeId,
    historyList,
    activeTitle,
    activeSyncError,
    activeSyncConflict,
    routePath,
    pageName,
    selection,
    notes,
    contextLabel,
    selectionText,
    setOpen,
    toggle,
    setHistoryOpen,
    toggleHistory,
    setWidth,
    setPageContext,
    setSelection,
    setNotes,
    newChat,
    clearChat,
    switchConversation,
    deleteConversation,
    saveConflictAsNew,
    syncActiveToList,
    flushConversation,
    loadFromBackend,
    pushMessage,
    appendContent,
    appendReasoning,
    patchMessage,
    saveDraftToDeploy,
    resetSession,
  }
})
