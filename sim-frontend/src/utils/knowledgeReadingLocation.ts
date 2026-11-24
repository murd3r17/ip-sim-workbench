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

function exactExcerpt(parts: ReadingPart[], excerpt: string) {
  const lines = excerpt.split('\n')
    .filter(line => !/^\s*(?:#{1,6}\s|`{3}|~{3})/.test(line))
    .map(compact)
    .filter(Boolean)
  const text = lines.join('')
  if (text.length < 18 || !/[\p{L}\d]/u.test(text)) return undefined

  const matches = parts.filter(part => compact(part.content).includes(text))
  if (matches.length === 1) return matches[0]
  if (matches.length > 1 || lines.length < 2) return undefined

  // A table preview can omit rows. Require each retained line in order in a single part.
  const lineMatches = parts.filter(part => {
    const source = compact(part.content)
    let after = 0
    return lines.every(line => {
      const at = source.indexOf(line, after)
      if (at < 0) return false
      after = at + line.length
      return true
    })
  })
  return lineMatches.length === 1 ? lineMatches[0] : undefined
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
    const part = excerpt && exactExcerpt(parts.slice(start, nextPage < 0 ? undefined : nextPage), excerpt)
    return { id: part ? part.id : parts[start]!.id, page: originalPage, excerpt: Boolean(part) }
  }
  if (requirePage) return undefined
  const part = excerpt && exactExcerpt(parts, excerpt)
  if (part) return { id: part.id, excerpt: true }
  if (sectionId && parts.some(part => part.id === sectionId)) return { id: sectionId, excerpt: false }
  return undefined
}
