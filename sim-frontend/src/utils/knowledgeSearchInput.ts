const originalSearchLead = /^(?:请)?(?:查找|定位|检索|搜索|帮我(?:查找|定位|找到))(?:一下)?(?:原书|原版教材|原版\s*PDF|PDF)(?:原文|中的|里的|中|里)?(?:原句|这句话|这句|文字)?[：:]?$/iu
const originalPageQuestion = /^(?:(?:这句话|这句)\s*)?在\s*(?:原书|原版教材|原版\s*PDF|PDF)(?:的|中|里)?\s*(?:哪一页|哪页|第几页|什么位置)[。.?？]?$/iu

export function originalQuoteForLookup(input: string): string {
  const match = /“([^“”\r\n]+)”|"([^"\r\n]+)"/u.exec(input)
  if (!match) return ''
  const before = input.slice(0, match.index).trim()
  const after = input.slice(match.index + match[0].length).trim()
  const lookupRequest = (before === '' || originalSearchLead.test(before)) && /^[。.]?$/u.test(after)
  const pageQuestion = before === '' && originalPageQuestion.test(after)
  if (!lookupRequest && !pageQuestion) return ''
  const quote = (match[1] || match[2] || '').trim()
  const length = quote.normalize('NFKC').match(/[\p{L}\p{N}]/gu)?.length ?? 0
  return length >= 8 && length <= 180 ? quote : ''
}
