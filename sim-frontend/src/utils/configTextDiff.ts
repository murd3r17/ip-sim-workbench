export interface ConfigDiffLine { number: number; text: string; context: string; key: string }
export interface ConfigDiffRow { kind: 'equal' | 'added' | 'removed' | 'changed'; left?: ConfigDiffLine; right?: ConfigDiffLine }

/** Browser-local reader. Credential lines stay hidden in rendering and exports. */
export function hideConfigCredentials(text: string): { text: string; hidden: boolean } {
  let hidden = false
  const value = text.split('\n').map(line => {
    if (/(?:\b(?:password|passwd|secret|api[-_]key|access[-_]token|refresh[-_]token|authorization|pre-shared-key|authentication-key|key-string|shared-key)\b|\bcommunity(?:\s|$)|\bkey\s+(?:\d+\s+)?(?:cipher|simple)\b|authentication-mode\s+(?:md5|simple|hmac|sha)|privacy-mode\s+)/i.test(line)) {
      hidden = true
      return `${line.match(/^\s*/)?.[0] || ''}[凭据行已隐藏]`
    }
    return line
  }).join('\n')
  return { text: value, hidden }
}

function sourceLines(text: string, ignoreFormatting: boolean): ConfigDiffLine[] {
  let root = '', child = ''
  const rows: ConfigDiffLine[] = []
  for (const [index, raw] of text.split(/\r?\n/).entries()) {
    const trim = raw.trim()
    if (trim.startsWith('#') || trim === 'return' || trim === 'system-view') root = child = ''
    if (trim === 'quit') { if (child) child = ''; else root = '' }
    if (/^(?:interface|ospf|bgp|isis|vlan|aaa|acl|user-interface|route-policy|ip vpn-instance)(?:\s|$)/i.test(trim)) { root = trim; child = '' }
    else if (/^(?:area|ipv4-family|ipv6-family)(?:\s|$)/i.test(trim)) child = trim
    const context = [root, child].filter(Boolean).join(' > ') || '全局 / 未分组'
    if (ignoreFormatting && (!trim || /^[#!]/.test(trim))) continue
    const contentKey = ignoreFormatting ? trim.replace(/\s+/g, ' ') : raw
    rows.push({ number:index + 1, text:raw, context, key:`${context}\0${contentKey}` })
  }
  return rows
}

/** Bounded LCS after common prefix/suffix. Large changed blocks use explicit positional mode. */
export function buildConfigDiff(leftText: string, rightText: string, ignoreFormatting = true, maxCells = 1_000_000) {
  const leftSafe = hideConfigCredentials(leftText), rightSafe = hideConfigCredentials(rightText)
  const left = sourceLines(leftSafe.text, ignoreFormatting), right = sourceLines(rightSafe.text, ignoreFormatting)
  const rows: ConfigDiffRow[] = []
  let prefix = 0, tail = 0
  while (prefix < left.length && prefix < right.length && left[prefix].key === right[prefix].key) { rows.push({kind:'equal',left:left[prefix],right:right[prefix]}); prefix++ }
  while (tail < left.length-prefix && tail < right.length-prefix && left[left.length-1-tail].key === right[right.length-1-tail].key) tail++
  const a = left.slice(prefix,left.length-tail), b = right.slice(prefix,right.length-tail)
  const positional = (a.length + 1) * (b.length + 1) > maxCells
  const middle: ConfigDiffRow[] = []
  if (positional) {
    for (let i=0;i<Math.max(a.length,b.length);i++) middle.push({kind:!a[i]?'added':!b[i]?'removed':a[i].key===b[i].key?'equal':'changed',left:a[i],right:b[i]})
  } else {
    const width = b.length + 1, dp = new Uint32Array((a.length+1)*width)
    for (let i=a.length-1;i>=0;i--) for(let j=b.length-1;j>=0;j--) dp[i*width+j] = a[i].key===b[j].key ? 1+dp[(i+1)*width+j+1] : Math.max(dp[(i+1)*width+j],dp[i*width+j+1])
    let i=0,j=0
    while(i<a.length||j<b.length) {
      if(i<a.length&&j<b.length&&a[i].key===b[j].key) { middle.push({kind:'equal',left:a[i++],right:b[j++]}); continue }
      if(i<a.length&&(j===b.length||dp[(i+1)*width+j]>=dp[i*width+j+1])) middle.push({kind:'removed',left:a[i++]})
      else middle.push({kind:'added',right:b[j++]})
    }
  }
  // Pair neighboring replacement runs without dropping duplicates or original line numbers.
  for(let i=0;i<middle.length;) {
    if(middle[i].kind==='equal'||positional) { rows.push(middle[i++]); continue }
    const removed: ConfigDiffLine[]=[],added: ConfigDiffLine[]=[]
    while(i<middle.length&&middle[i].kind!=='equal') { const x=middle[i++]; if(x.left)removed.push(x.left); if(x.right)added.push(x.right) }
    for(let k=0;k<Math.max(removed.length,added.length);k++) rows.push({kind:!removed[k]?'added':!added[k]?'removed':'changed',left:removed[k],right:added[k]})
  }
  for(let i=tail;i>0;i--) rows.push({kind:'equal',left:left[left.length-i],right:right[right.length-i]})
  return { rows, positional, hiddenCredentials:leftSafe.hidden||rightSafe.hidden,
    counts:{added:rows.filter(x=>x.kind==='added').length,removed:rows.filter(x=>x.kind==='removed').length,changed:rows.filter(x=>x.kind==='changed').length},
    leftText:leftSafe.text,rightText:rightSafe.text }
}

export function configDiffContext(rows: ConfigDiffRow[], radius = 2): ConfigDiffRow[] {
  const keep = new Set<number>()
  rows.forEach((r,i)=>{if(r.kind!=='equal')for(let j=Math.max(0,i-radius);j<=Math.min(rows.length-1,i+radius);j++)keep.add(j)})
  return rows.filter((_,i)=>keep.has(i))
}
