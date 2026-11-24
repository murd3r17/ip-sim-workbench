interface ReadingPart {
  id: string
  content: string
}

interface PageAnchor {
  physical: number
  section_id?: string | null
}

interface ReadingLocation {
  id: string
  page?: number
  excerpt: boolean
}

function compact(text: string) {
  return text.replace(/\s+/g, '')
}

function containsInOrder(content: string, fragments: string[]) {
  let after = 0
  return fragments.every(fragment => {
    const at = content.indexOf(fragment, after)
    if (at < 0) return false
    after = at + fragment.length
    return true
  })
}

function exactExcerpt(parts: ReadingPart[], excerpt: string, withinPhysicalPage = false) {
  const lines = excerpt.split('\n')
    .filter(line => !/^\s*(?:#{1,6}\s|`{3}|~{3})/.test(line))
    .map(compact)
    .filter(Boolean)
  const text = lines.join('')
  if (text.length < 18 || !/[\p{L}\d]/u.test(text)) return undefined

  const candidates = parts.map(part => ({ part, content: compact(part.content) }))
  const matches = candidates.filter(({ content }) => content.includes(text))
  if (matches.length) return matches.length === 1 ? matches[0]?.part : undefined

  // A table preview can omit rows. Require each retained line in order in a single part.
  const lineMatches = lines.length > 1 ? candidates.filter(({ content }) => containsInOrder(content, lines)) : []
  if (lineMatches.length) return lineMatches.length === 1 ? lineMatches[0]?.part : undefined
  if (!withinPhysicalPage) return undefined

  // Evidence may omit a whole sentence. Verify all retained fragments against
  // one section of the referenced physical page before marking a match.
  const sentences = lines.flatMap(line => line.split(/(?<=[。！？])/u))
  if (sentences.length <= lines.length) return undefined
  const sentenceMatches = candidates.filter(({ content }) => containsInOrder(content, sentences))
  return sentenceMatches.length === 1 ? sentenceMatches[0]?.part : undefined
}

export function findKnowledgeReadingLocation(
  parts: ReadingPart[], pages: PageAnchor[], source: {
    originalPage?: number
    sectionId?: string
    excerpt?: string
    requirePage?: boolean
  },
): ReadingLocation | undefined {
  const { originalPage, sectionId, excerpt, requirePage } = source
  if (originalPage !== undefined) {
    const start = parts.findIndex(part => part.id === pages.find(page => page.physical === originalPage)?.section_id)
    if (start === -1) return undefined
    const following = new Set(pages.filter(page => page.physical > originalPage).map(page => page.section_id))
    const nextPage = parts.findIndex((part, index) => index > start && following.has(part.id))
    const part = excerpt && exactExcerpt(parts.slice(start, nextPage < 0 ? undefined : nextPage), excerpt, true)
    return { id: part ? part.id : parts[start]!.id, page: originalPage, excerpt: Boolean(part) }
  }
  if (requirePage) return undefined
  const part = excerpt && exactExcerpt(parts, excerpt)
  if (part) return { id: part.id, excerpt: true }
  if (sectionId && parts.some(part => part.id === sectionId)) return { id: sectionId, excerpt: false }
  return undefined
}
