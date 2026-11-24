export interface TextbookPageLocation {
  document_id: string
  document_version: string
  edition_version: string
  book_title: string
  title: string
  page: number
}

const guideMessages = {
  no_match: '这次没有找到足以回答的教材片段。',
  partial: '这次只找到部分依据。',
  ambiguous: '这次无法确定是哪一处教材内容。',
  unavailable: '暂时无法核对教材。',
} as const

export interface CopilotSourceGuide {
  status: keyof typeof guideMessages
  candidates: TextbookPageLocation[]
}

export function sourceGuideMessage(guide: CopilotSourceGuide) {
  return guideMessages[guide.status]
}

export function readSourceGuide(value: unknown): CopilotSourceGuide | undefined {
  if (!value || typeof value !== 'object') return undefined
  const guide = value as Partial<CopilotSourceGuide>
  if (!guide.status || !Object.prototype.hasOwnProperty.call(guideMessages, guide.status)) return undefined
  const candidates: TextbookPageLocation[] = []
  if (guide.status === 'unavailable') return { status: guide.status, candidates }
  for (const entry of Array.isArray(guide.candidates) ? guide.candidates.slice(0, 6) : []) {
    if (!entry || typeof entry !== 'object' || typeof entry.document_id !== 'string' || !entry.document_id.trim()
      || typeof entry.book_title !== 'string' || !entry.book_title.trim() || typeof entry.title !== 'string'
      || typeof entry.document_version !== 'string' || typeof entry.edition_version !== 'string'
      || !/^[\da-f]{64}$/.test(entry.document_version) || !entry.edition_version.trim() || entry.edition_version.length > 128
      || !Number.isSafeInteger(entry.page) || entry.page < 1 || entry.page > 10000) continue
    const { document_id, document_version, edition_version, book_title, title, page } = entry
    if (!candidates.some(item => item.document_id === document_id && item.document_version === document_version
      && item.edition_version === edition_version && item.page === page)) {
      candidates.push({ document_id, document_version, edition_version, book_title, title, page })
    }
  }
  return { status: guide.status, candidates }
}

export function textbookPageQuestion(location: TextbookPageLocation, question: string) {
  const title = location.book_title.trim().replace(/^《(.*)》$/u, '$1')
  return `请只根据本地教材《${title}》PDF 第 ${location.page} 页回答。本页没有依据的内容请指出。\n\n${question.trim()}`
}
