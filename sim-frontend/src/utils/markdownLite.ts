/** Minimal Markdown → safe HTML for Copilot bubbles (no external deps). */

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inlineMarkdown(text: string, sourceCount?: number): string {
  let s = escapeHtml(text)
  // inline code
  s = s.replace(/`([^`]+)`/g, '<code class="md-inline">$1</code>')
  // bold
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // italic (single *)
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  // Only validated source indices in prose become controls. Never interpret HTML,
  // URLs or a numeric expression inside inline/fenced code as a citation.
  s = s.split(/(<code\b[^>]*>[\s\S]*?<\/code>)/g).map(part => part.startsWith('<code') ? part
    : part.replace(/\[(?:n:?\s*)?(\d{1,6})([ \t]{0,2}审校(?:说明|补充)?[ \t]{0,2})?\]/gi, (match, number, review) => {
      const index = Number(number)
      const label = `${index}${review || ''}`
      if (sourceCount === undefined) return match
      return index >= 1 && index <= sourceCount
        ? `<button type="button" class="citation-inline" data-source-index="${index - 1}" aria-label="查看来源 ${label}">[${label}]</button>`
        : `<span class="citation-unmatched" title="该编号不在本次回答的来源列表中">[${label} · 无对应来源]</span>`
    })).join('')
  return s
}

function isTableRow(line: string): boolean {
  const t = line.trim()
  if (!t.startsWith('|')) return false
  return t.indexOf('|', 1) >= 0
}

function isTableSeparator(line: string): boolean {
  const t = line.trim()
  if (!t.includes('-')) return false
  // |---|---|  /  | :---:|---|  /  ---|---
  return /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(t)
}

function splitCells(line: string): string[] {
  let t = line.trim()
  if (t.startsWith('|')) t = t.slice(1)
  if (t.endsWith('|')) t = t.slice(0, -1)
  return t.split('|').map((c) => c.trim())
}

function renderTable(rows: string[][], sourceCount?: number): string {
  if (!rows.length) return ''
  const [header, ...body] = rows
  const thead =
    `<thead><tr>${header.map((c) => `<th>${inlineMarkdown(c, sourceCount)}</th>`).join('')}</tr></thead>`
  const tbody = body.length
    ? `<tbody>${body
        .map((r) => `<tr>${r.map((c) => `<td>${inlineMarkdown(c, sourceCount)}</td>`).join('')}</tr>`)
        .join('')}</tbody>`
    : ''
  return `<div class="md-table-wrap" tabindex="0" role="region" aria-label="回答表格"><table class="md-table">${thead}${tbody}</table></div>`
}

function renderParagraphs(block: string, sourceCount?: number): string {
  const lines = block.split('\n')
  const out: string[] = []
  let listType: 'ul' | 'ol' | null = null
  let listItems: string[] = []
  let i = 0

  const flushList = () => {
    if (!listType || !listItems.length) return
    out.push(`<${listType}>${listItems.join('')}</${listType}>`)
    listType = null
    listItems = []
  }

  while (i < lines.length) {
    const line = lines[i].trimEnd()

    // GFM table (允许行间空行，模型常会这样输出)
    if (isTableRow(line) && !isTableSeparator(line)) {
      flushList()
      const tableLines: string[] = []
      while (i < lines.length) {
        const cur = lines[i].trimEnd()
        if (!cur.trim()) {
          i += 1
          continue
        }
        if (isTableRow(cur) || isTableSeparator(cur)) {
          tableLines.push(cur.trim())
          i += 1
          continue
        }
        break
      }

      const cells: string[][] = []
      for (const tl of tableLines) {
        if (isTableSeparator(tl)) continue
        cells.push(splitCells(tl))
      }
      if (cells.length) out.push(renderTable(cells, sourceCount))
      continue
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(line)
    if (heading) {
      flushList()
      const level = heading[1].length
      out.push(`<h${level}>${inlineMarkdown(heading[2], sourceCount)}</h${level}>`)
      i += 1
      continue
    }

    // 中文小节标题：一、二、… / 1. /
    const cnHeading = /^(?:[一二三四五六七八九十]+[、．.]|\d+[、.])\s*(.+)$/.exec(line.trim())
    if (cnHeading && line.trim().length < 40 && !line.includes('|')) {
      flushList()
      out.push(`<h3>${inlineMarkdown(line.trim(), sourceCount)}</h3>`)
      i += 1
      continue
    }

    const ul = /^[-*]\s+(.+)$/.exec(line)
    if (ul) {
      if (listType && listType !== 'ul') flushList()
      listType = 'ul'
      listItems.push(`<li>${inlineMarkdown(ul[1], sourceCount)}</li>`)
      i += 1
      continue
    }

    const ol = /^(\d+)\.\s+(.+)$/.exec(line)
    if (ol) {
      if (listType && listType !== 'ol') flushList()
      listType = 'ol'
      listItems.push(`<li>${inlineMarkdown(ol[2], sourceCount)}</li>`)
      i += 1
      continue
    }

    if (!line.trim()) {
      flushList()
      i += 1
      continue
    }

    flushList()
    out.push(`<p>${inlineMarkdown(line, sourceCount)}</p>`)
    i += 1
  }
  flushList()
  return out.join('')
}

/**
 * Render markdown-ish content to HTML. Code fences become copyable blocks.
 */
export function renderMarkdown(src: string, sourceCount?: number): string {
  if (!src) return ''
  const parts: string[] = []
  const fenceRe = /```([\w+-]*)\r?\n?([\s\S]*?)```/g
  let last = 0
  let m: RegExpExecArray | null

  while ((m = fenceRe.exec(src)) !== null) {
    if (m.index > last) {
      parts.push(renderParagraphs(src.slice(last, m.index), sourceCount))
    }
    const lang = (m[1] || 'text').trim() || 'text'
    const code = escapeHtml(m[2].replace(/\n$/, ''))
    parts.push(renderCodeBlock(lang, code))
    last = m.index + m[0].length
  }

  const rest = src.slice(last)
  const openIdx = rest.indexOf('```')
  if (openIdx >= 0) {
    const afterOpen = rest.slice(openIdx + 3)
    const closeIdx = afterOpen.indexOf('```')
    if (closeIdx < 0) {
      if (openIdx > 0) parts.push(renderParagraphs(rest.slice(0, openIdx), sourceCount))
      const nl = afterOpen.indexOf('\n')
      let lang = 'text'
      let body = afterOpen
      if (nl >= 0) {
        const maybeLang = afterOpen.slice(0, nl).trim()
        if (/^[\w+-]*$/.test(maybeLang)) {
          lang = maybeLang || 'text'
          body = afterOpen.slice(nl + 1)
        }
      } else if (/^[\w+-]+$/.test(afterOpen.trim())) {
        lang = afterOpen.trim() || 'text'
        body = ''
      }
      parts.push(renderCodeBlock(lang, escapeHtml(body)))
      return parts.join('')
    }
  }

  if (rest) parts.push(renderParagraphs(rest, sourceCount))
  return parts.join('')
}

function renderCodeBlock(lang: string, escapedCode: string): string {
  // A prose code fence is not a validated configuration draft. The explicit
  // draft card owns the deployment action, including its server-side policy.
  return (
    `<div class="code-block">` +
    `<div class="code-toolbar"><span class="code-lang">${escapeHtml(lang)}</span>` +
    `<div class="code-actions"><button type="button" class="code-copy">复制</button></div></div>` +
    `<pre><code class="language-${escapeHtml(lang)}">${escapedCode}</code></pre>` +
    `</div>`
  )
}
