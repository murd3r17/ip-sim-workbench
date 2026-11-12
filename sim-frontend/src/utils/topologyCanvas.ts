import type { TopologyLayoutPosition as Point } from '../api/device'

export interface GraphNode {
  id: string
  label: string
  status: string
  type: string
  model: string
  mgmt_ip: string
  network_role?: string
}

export interface GraphEdge {
  source: string
  target: string
  source_name: string
  target_name: string
  source_interface: string
  target_interface: string
  source_ip?: string
  target_ip?: string
  link_type: string
  status: string
  bandwidth: string
  discovery_source: string
  source_type?: string
  runtime_diff?: 'missing' | 'unexpected'
}

export const NODE_WIDTH = 170
export const NODE_HEIGHT = 68
const HALF_W = NODE_WIDTH / 2
const HALF_H = NODE_HEIGHT / 2
const COLUMN_GAP = 236
const ROW_GAP = 146
const ROLE_LAYERS: Record<string, number> = {
  core: 0, core_router: 0, backbone_router: 0, provincial_router: 0, vpn_rr: 0,
  aggregation: 1, bras: 1, external_router: 1,
  access: 2, business_switch: 2, management_switch: 3,
}

function nodeLayer(node: GraphNode) {
  const role = node.network_role ? ROLE_LAYERS[node.network_role] : undefined
  return role ?? (node.type === 'switch_l2' ? 2 : node.type === 'server' ? 3 : 1)
}

export function arrangeTopology(nodes: GraphNode[]) {
  const sorted = [...nodes].sort((a, b) => a.label.localeCompare(b.label, 'zh-CN', { numeric: true }))
  const rows: GraphNode[][] = []
  const columns = Math.min(5, Math.max(3, Math.ceil(Math.sqrt(nodes.length))))
  for (let layer = 0; layer < 4; layer++) {
    const group = sorted.filter(node => nodeLayer(node) === layer)
    for (let index = 0; index < group.length; index += columns) {
      rows.push(group.slice(index, index + columns))
    }
  }
  // The logical surface is independent of the browser viewport. The saved layout
  // contract remains normalized coordinates, including drafts from older versions.
  const width = 1280
  const height = Math.max(640, rows.length * ROW_GAP + 80)
  const positions: Record<string, Point> = {}
  rows.forEach((row, y) => row.forEach((node, x) => {
    positions[node.id] = {
      x: 0.5 + (x - (row.length - 1) / 2) * COLUMN_GAP / width,
      y: 0.5 + (y - (rows.length - 1) / 2) * ROW_GAP / height,
    }
  }))
  return { width, height, positions }
}

export function edgeAppearance(edge: GraphEdge) {
  if (edge.runtime_diff === 'missing') return { tone: 'missing', label: '本次未观察到' }
  if (edge.runtime_diff === 'unexpected') return { tone: 'unexpected', label: '本次非基线邻接' }
  if (edge.source_type !== 'baseline') return { tone: 'manual', label: '非基线登记' }
  if (edge.link_type === 'management' || edge.status !== 'up') {
    return { tone: 'recorded', label: edge.link_type === 'management' ? '基线 · 管理链路' : '基线 · 状态未标为 Up' }
  }
  return { tone: 'baseline', label: '基线记录' }
}

function roundedPath(points: Point[]) {
  let path = `M ${points[0].x} ${points[0].y}`
  for (let i = 1; i < points.length - 1; i++) {
    const [before, corner, after] = points.slice(i - 1, i + 2)
    const incoming = Math.hypot(before.x - corner.x, before.y - corner.y)
    const outgoing = Math.hypot(after.x - corner.x, after.y - corner.y)
    if (!incoming || !outgoing) continue
    const radius = Math.min(9, incoming / 2, outgoing / 2)
    const start = { x: corner.x + (before.x - corner.x) * radius / incoming, y: corner.y + (before.y - corner.y) * radius / incoming }
    const end = { x: corner.x + (after.x - corner.x) * radius / outgoing, y: corner.y + (after.y - corner.y) * radius / outgoing }
    path += ` L ${start.x} ${start.y} Q ${corner.x} ${corner.y} ${end.x} ${end.y}`
  }
  const end = points[points.length - 1]
  return `${path} L ${end.x} ${end.y}`
}

function routeLink(a: Point, b: Point, lane: number, blocked: boolean) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const sx = Math.sign(dx) || 1
  const sy = Math.sign(dy) || 1
  let points: Point[]
  if (Math.abs(dy) >= NODE_HEIGHT + 40) {
    const start = { x: a.x + lane, y: a.y + sy * HALF_H }
    const end = { x: b.x + lane, y: b.y - sy * HALF_H }
    const mid = (a.y + b.y) / 2 + lane
    points = start.x === end.x ? [start, end] : [start, { x: start.x, y: mid }, { x: end.x, y: mid }, end]
  } else if (!blocked && Math.abs(dx) >= NODE_WIDTH + 52) {
    const start = { x: a.x + sx * HALF_W, y: a.y + lane }
    const end = { x: b.x - sx * HALF_W, y: b.y + lane }
    const mid = (a.x + b.x) / 2 + lane
    points = start.y === end.y ? [start, end] : [start, { x: mid, y: start.y }, { x: mid, y: end.y }, end]
  } else {
    const start = { x: a.x - 16 + lane, y: a.y - HALF_H }
    const end = { x: b.x + 16 + lane, y: b.y - HALF_H }
    const channel = Math.min(start.y, end.y) - 35 + lane
    points = [start, { x: start.x, y: channel }, { x: end.x, y: channel }, end]
  }
  // Center the label along the longest segment, away from the bend or card.
  let length = 0
  let labelPoint = points[0]
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]
    const b = points[i]
    const segment = Math.hypot(b.x - a.x, b.y - a.y)
    if (segment > length) {
      labelPoint = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
      length = segment
    }
  }
  return { path: roundedPath(points), points, labelPoint, labelInline: length >= 124 }
}

function linkId(edge: GraphEdge) {
  return JSON.stringify([[edge.source, edge.source_interface], [edge.target, edge.target_interface]].sort())
}

export function drawTopologyEdges(edges: GraphEdge[], positions: Record<string, Point>) {
  const pairs = new Map<string, GraphEdge[]>()
  for (const edge of edges) {
    if (!positions[edge.source] || !positions[edge.target]) continue
    const key = JSON.stringify([edge.source, edge.target].sort())
    const group = pairs.get(key)
    if (group) group.push(edge)
    else pairs.set(key, [edge])
  }
  const locations = Object.entries(positions)
  return Array.from(pairs.values()).flatMap(group => group
    .sort((a, b) => linkId(a).localeCompare(linkId(b)))
    .map((edge, index) => {
      const a = positions[edge.source]
      const b = positions[edge.target]
      const lane = (index - (group.length - 1) / 2) * Math.min(16, 46 / Math.max(1, group.length - 1))
      const blocked = locations.some(([id, point]) => id !== edge.source && id !== edge.target
        && point.x > Math.min(a.x, b.x) && point.x < Math.max(a.x, b.x)
        && Math.min(Math.abs(point.y - a.y), Math.abs(point.y - b.y)) <= NODE_HEIGHT)
      return { edge, id: linkId(edge), ...edgeAppearance(edge), ...routeLink(a, b, lane, blocked) }
    }))
}
