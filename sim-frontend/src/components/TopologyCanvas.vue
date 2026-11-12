<template>
  <section class="topology-canvas" aria-label="拓扑画布">
    <div class="canvas-bar">
      <div class="canvas-caption">
        <strong>网络关系图</strong>
        <span>拖动空白平移 · 拖动卡片调整布局</span>
      </div>
      <div class="canvas-actions">
        <label><input v-model="showAddresses" type="checkbox"> 管理地址</label>
        <label><input v-model="showInterfaces" type="checkbox"> 接口标签</label>
        <div class="zoom-controls" aria-label="画布缩放">
          <button type="button" aria-label="缩小画布" :disabled="camera.scale <= minScale" @click="zoom(1 / 1.25)">−</button>
          <span>{{ Math.round(camera.scale * 100) }}%</span>
          <button type="button" aria-label="放大画布" :disabled="camera.scale >= MAX_SCALE" @click="zoom(1.25)">+</button>
        </div>
        <button type="button" class="fit-button" @click="manualCamera = null">适应画布</button>
      </div>
    </div>

    <div v-if="selectedLink" class="link-detail" aria-live="polite">
      <div class="link-summary">
        <strong>链路详情</strong>
        <span>{{ selectedLink.label }}</span>
        <button type="button" @click="selectedLinkId = ''">关闭详情</button>
      </div>
      <div class="link-endpoints">
        <div><strong>{{ selectedLink.edge.source_name }}</strong> {{ selectedLink.edge.source_interface }} <span v-if="selectedLink.edge.source_ip">{{ selectedLink.edge.source_ip }}</span></div>
        <div><strong>{{ selectedLink.edge.target_name }}</strong> {{ selectedLink.edge.target_interface }} <span v-if="selectedLink.edge.target_ip">{{ selectedLink.edge.target_ip }}</span></div>
      </div>
      <div class="link-source">
        来源 {{ selectedLink.edge.discovery_source || '未登记' }}
        <span v-if="selectedLink.edge.bandwidth"> · {{ selectedLink.edge.bandwidth }}</span>
        <span v-if="selectedLink.tone === 'missing'"> · 可查看采集覆盖，确认哪些设备返回了邻居表</span>
      </div>
    </div>

    <div ref="surface" class="canvas-surface" :class="{ 'is-panning': gesture?.moved && !gesture.node }">
      <svg
        ref="svg" class="canvas-svg" aria-label="设备和链路"
        @pointerdown="startGesture($event)" @pointermove="moveGesture"
        @pointerup="endGesture" @pointercancel="cancelGesture" @lostpointercapture="cancelGesture"
      >
        <g :transform="transform">
          <g
            v-for="link in links" :key="link.id" class="canvas-edge"
            :class="[link.tone, { selected: selectedLink?.id === link.id }]"
            role="button" tabindex="0" :aria-pressed="selectedLink?.id === link.id"
            :aria-label="`${link.edge.source_name} ${link.edge.source_interface} 到 ${link.edge.target_name} ${link.edge.target_interface}，${link.label}`"
            @pointerdown.stop @click="selectedLinkId = link.id"
            @keydown.enter.prevent="selectedLinkId = link.id" @keydown.space.prevent="selectedLinkId = link.id"
          >
            <title>{{ link.edge.source_name }} {{ link.edge.source_interface }} ↔ {{ link.edge.target_name }} {{ link.edge.target_interface }} · {{ link.label }}</title>
            <path :d="link.path" class="edge-hit" />
            <path :d="link.path" class="edge-line" />
            <g v-if="showInterfaces" class="edge-label">
              <text :x="link.labelPoint.x" :y="link.labelPoint.y - 6">
                {{ shortInterface(link.edge.source_interface) }}{{ link.labelInline ? ` / ${shortInterface(link.edge.target_interface)}` : '' }}
              </text>
              <text v-if="!link.labelInline" :x="link.labelPoint.x" :y="link.labelPoint.y + 14">
                {{ shortInterface(link.edge.target_interface) }}
              </text>
            </g>
          </g>
          <g
            v-for="node in nodes" :key="node.id" class="canvas-node"
            :class="[statusFor(node).tone, { selected: selectedId === node.id }]"
            :transform="`translate(${points[node.id].x} ${points[node.id].y})`"
            role="button" tabindex="0" :aria-pressed="selectedId === node.id"
            :aria-label="`${node.label}，${statusFor(node).label}`"
            @pointerdown.stop="startGesture($event, node)"
            @click="selectAccessibleNode($event, node)"
            @keydown.enter.prevent="selectNode(node)" @keydown.space.prevent="selectNode(node)"
          >
            <title>{{ [node.label, node.model, node.mgmt_ip, node.network_role, statusFor(node).label].filter(Boolean).join(' · ') }}</title>
            <rect class="node-card" :x="-NODE_WIDTH / 2" :y="-NODE_HEIGHT / 2" :width="NODE_WIDTH" :height="NODE_HEIGHT" rx="11" />
            <rect class="node-accent" x="-85" y="-22" width="4" height="44" rx="2" />
            <rect class="node-icon" x="-70" y="-16" width="31" height="32" rx="8" />
            <text class="node-icon-label" x="-54.5" y="4">{{ deviceMark[node.type] || '网' }}</text>
            <text class="node-name" x="-28" :y="showAddresses ? -12 : -3">{{ compactTopologyLabel(node.label, 106) }}</text>
            <text v-if="showAddresses" class="node-address" x="-28" y="4">{{ compactTopologyLabel(node.mgmt_ip || '无管理地址', 138) }}</text>
            <circle class="node-status-dot" cx="-24" :cy="showAddresses ? 18 : 12" r="3" />
            <text class="node-status" x="-16" :y="showAddresses ? 22 : 16">{{ statusFor(node).label }}</text>
          </g>
        </g>
      </svg>
    </div>

    <div class="canvas-legend">
      <span v-for="item in legend" :key="item.tone"><i class="legend-mark" :class="item.tone" />{{ item.label }}</span>
      <span class="legend-hint">点选链路查看两端接口</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import type { TopologyLayoutPosition as Point } from '../api/device'
import { arrangeTopology, drawTopologyEdges, NODE_HEIGHT, NODE_WIDTH, type GraphEdge, type GraphNode } from '../utils/topologyCanvas'
import { compactTopologyLabel } from '../utils/topologyLabel'

const props = defineProps<{
  nodes: GraphNode[]
  edges: GraphEdge[]
  positions: Record<string, Point>
  selectedId?: string
}>()
const emit = defineEmits<{
  select: [node: GraphNode]
  move: [id: string, position: Point]
}>()

const legend = [
  { tone: 'baseline', label: '基线记录' },
  { tone: 'recorded', label: '基线管理链路／状态未标为 Up' },
  { tone: 'manual', label: '非基线登记' },
  { tone: 'unexpected', label: '本次非基线邻接' },
  { tone: 'missing', label: '本次未观察到' },
]
const deviceMark: Record<string, string> = { router: 'R', switch_l2: 'L2', switch_l3: 'L3', firewall: 'FW', server: 'S', pc: 'PC' }
const deviceStatus: Record<string, { tone: string, label: string }> = {
  online: { tone: 'online', label: '在线' },
  offline: { tone: 'offline', label: '离线' },
  error: { tone: 'offline', label: '异常' },
}
const unknownStatus = { tone: 'unknown', label: '状态未知' }
const statusFor = (node: GraphNode) => deviceStatus[node.status] || unknownStatus
const shortInterface = (value: string) => compactTopologyLabel(value.replace(/^GigabitEthernet/i, 'GE').replace(/^Ethernet/i, 'Eth') || '未登记', 88)
const MAX_SCALE = 3.2

interface Camera {
  center: Point
  scale: number
}
interface Gesture {
  pointerId: number
  node?: GraphNode
  start: Point
  camera: Camera
  origin?: Point
  moved: boolean
}

const surface = ref<HTMLElement>()
const svg = ref<SVGSVGElement>()
const viewport = shallowRef({ width: 1, height: 1 })
const manualCamera = shallowRef<Camera | null>(null)
const gesture = shallowRef<Gesture>()
const draggingPosition = shallowRef<Point>()
const showAddresses = ref(true)
const showInterfaces = ref(false)
const selectedLinkId = ref('')
const layout = computed(() => arrangeTopology(props.nodes))
const getPositions = () => Object.fromEntries(props.nodes.map(({ id }) => [id, props.positions[id] || layout.value.positions[id]]))
defineExpose({ getPositions })

const points = computed(() => Object.fromEntries(Object.entries(getPositions()).map(([id, position]) => {
  const point = gesture.value?.node?.id === id ? draggingPosition.value || position : position
  return [id, { x: point.x * layout.value.width, y: point.y * layout.value.height }]
})))
const links = computed(() => drawTopologyEdges(props.edges, points.value))
const selectedLink = computed(() => links.value.find(link => link.id === selectedLinkId.value))
const fitCamera = computed<Camera>(() => {
  let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity
  const include = ({ x, y }: Point, halfWidth = 0, halfHeight = 0) => {
    left = Math.min(left, x - halfWidth)
    right = Math.max(right, x + halfWidth)
    top = Math.min(top, y - halfHeight)
    bottom = Math.max(bottom, y + halfHeight)
  }
  for (const point of Object.values(points.value)) include(point, NODE_WIDTH / 2, NODE_HEIGHT / 2)
  for (const link of links.value) for (const point of link.points) include(point)
  const { width, height } = viewport.value
  const padding = Math.min(64, width * 0.15)
  const readableScale = Math.min(2.35, Math.max(1.15, Math.min(width / 680, height / 410)))
  return {
    center: { x: (left + right) / 2, y: (top + bottom) / 2 },
    scale: Math.min(readableScale, (width - padding) / (right - left), Math.max(1, height - 48) / (bottom - top)),
  }
})
const camera = computed(() => manualCamera.value || fitCamera.value)
const minScale = computed(() => Math.min(0.35, fitCamera.value.scale / 1.5))
const transform = computed(() => {
  const { center, scale } = camera.value
  return `translate(${viewport.value.width / 2} ${viewport.value.height / 2}) scale(${scale}) translate(${-center.x} ${-center.y})`
})

function zoom(factor: number) {
  const current = camera.value
  manualCamera.value = { center: current.center, scale: Math.max(minScale.value, Math.min(MAX_SCALE, current.scale * factor)) }
}

function selectNode(node: GraphNode) {
  selectedLinkId.value = ''
  emit('select', node)
}

function selectAccessibleNode(event: MouseEvent, node: GraphNode) {
  if (!event.detail) selectNode(node)
}

function startGesture(event: PointerEvent, node?: GraphNode) {
  if (event.button !== 0 || gesture.value || !svg.value) return
  svg.value.setPointerCapture(event.pointerId)
  gesture.value = {
    pointerId: event.pointerId,
    node,
    start: { x: event.clientX, y: event.clientY },
    origin: node ? points.value[node.id] : undefined,
    camera: camera.value,
    moved: false,
  }
}

function moveGesture(event: PointerEvent) {
  const active = gesture.value
  if (!active || active.pointerId !== event.pointerId) return
  const dx = event.clientX - active.start.x
  const dy = event.clientY - active.start.y
  if (!active.moved) {
    if (Math.hypot(dx, dy) < 5) return
    gesture.value = { ...active, moved: true }
    manualCamera.value = active.camera
  }
  const { scale, center } = active.camera
  if (active.origin) {
    const clamp = (value: number) => Math.max(0, Math.min(1, value))
    draggingPosition.value = {
      x: clamp((active.origin.x + dx / scale) / layout.value.width),
      y: clamp((active.origin.y + dy / scale) / layout.value.height),
    }
  } else {
    manualCamera.value = { center: { x: center.x - dx / scale, y: center.y - dy / scale }, scale }
  }
}

function cancelGesture(event: PointerEvent) {
  if (gesture.value?.pointerId !== event.pointerId) return
  gesture.value = undefined
  draggingPosition.value = undefined
}

function endGesture(event: PointerEvent) {
  const active = gesture.value
  if (!active || active.pointerId !== event.pointerId) return
  if (active.node && draggingPosition.value) emit('move', active.node.id, draggingPosition.value)
  else if (active.node) selectNode(active.node)
  else if (!active.moved) selectedLinkId.value = ''
  cancelGesture(event)
}

let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(([entry]) => {
    viewport.value = { width: entry.contentRect.width, height: entry.contentRect.height }
  })
  if (surface.value) observer.observe(surface.value)
})
onUnmounted(() => observer?.disconnect())
</script>

<style scoped>
.topology-canvas {
  min-width: 0;
  display: flex;
  flex: 1 0 auto;
  flex-direction: column;
  background: #fff;
  border: 1px solid var(--v7b-line);
  border-radius: 12px;
  overflow: hidden;
  color: var(--v7b-text);
}

.canvas-bar,
.canvas-legend,
.link-detail { padding: 10px 14px; }

.canvas-bar,
.canvas-actions,
.canvas-caption,
.canvas-legend,
.link-summary { display: flex; align-items: center; gap: 8px 14px; flex-wrap: wrap; }
.canvas-bar { justify-content: space-between; }
.canvas-caption strong { font-size: 14px; }
.canvas-caption span,
.canvas-legend,
.link-source { font-size: 12px; color: var(--v7b-muted); }
.canvas-actions { font-size: 13px; }
.canvas-actions label { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; }
.canvas-actions input { accent-color: #356bb3; }
.canvas-actions button,
.link-summary button {
  min-height: 30px;
  color: #25466e;
  background: #fff;
  border: 1px solid #c8d5e5;
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
}
.canvas-actions button:hover,
.link-summary button:hover { background: #edf4ff; }
.canvas-actions button:focus-visible,
.link-summary button:focus-visible { outline: 2px solid #2c64b5; outline-offset: 2px; }
.canvas-actions button:disabled { opacity: .46; cursor: default; }
.zoom-controls { display: inline-flex; align-items: center; gap: 6px; }
.zoom-controls button { width: 30px; font-size: 17px; }
.zoom-controls span { width: 4ch; text-align: center; font-variant-numeric: tabular-nums; }
.fit-button,
.link-summary button { padding: 0 10px; }
.canvas-surface {
  position: relative;
  flex: 1;
  min-height: clamp(290px, 46vh, 600px);
  overflow: hidden;
  border-block: 1px solid #e0e8f1;
  background: #f5f8fc radial-gradient(circle, #ccd8e8 1px, transparent 1.3px) 0 0 / 18px 18px;
}
.canvas-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  touch-action: none;
  user-select: none;
  cursor: grab;
}
.is-panning .canvas-svg { cursor: grabbing; }
.canvas-node { cursor: grab; outline: none; }
.canvas-node:active { cursor: grabbing; }
.canvas-node text,
.canvas-node circle,
.node-icon,
.node-accent,
.edge-line,
.edge-label { pointer-events: none; }
.node-card { fill: #fff; stroke: #b9cbe0; stroke-width: 1.2; }
.canvas-node:hover .node-card,
.canvas-node:focus-visible .node-card,
.canvas-node.selected .node-card { stroke: #3572c8; stroke-width: 2; }
.canvas-node.selected .node-card { fill: #f7faff; }
.node-icon { fill: #eaf1fb; }
.node-icon-label { fill: #315b8e; text-anchor: middle; font-size: 12px; font-weight: 700; }
.node-name { fill: #172a40; font-size: 14px; font-weight: 700; }
.node-address { fill: #4b617a; font-size: 11px; font-variant-numeric: tabular-nums; }
.node-status { fill: #4b617a; font-size: 11px; }
.node-accent,
.node-status-dot { fill: #8293a7; }
.online .node-accent,
.online .node-status-dot { fill: #378260; }
.online .node-status { fill: #28674a; }
.offline .node-accent,
.offline .node-status-dot { fill: #b44e50; }
.offline .node-status { fill: #98393b; }
.baseline { --edge-color: #4c7fbd; }
.recorded { --edge-color: #637b97; --edge-dash: 7 5; }
.manual { --edge-color: #718096; --edge-dash: 2 5; }
.unexpected { --edge-color: #a45d13; }
.missing { --edge-color: #b54144; --edge-dash: 8 5; }
.canvas-edge { cursor: pointer; outline: none; }
.edge-line { fill: none; stroke: var(--edge-color); stroke-width: 2.5; stroke-linecap: round; stroke-dasharray: var(--edge-dash, none); }
.edge-hit { fill: none; stroke: transparent; stroke-width: 16; }
.canvas-edge:hover .edge-line,
.canvas-edge:focus-visible .edge-line,
.canvas-edge.selected .edge-line { stroke-width: 4; }
.edge-label { fill: #28415f; stroke: #f5f8fc; stroke-width: 5; paint-order: stroke; text-anchor: middle; font-size: 11px; }
.canvas-legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend-mark { width: 17px; border-top: 2px solid var(--edge-color); }
.legend-mark.recorded,
.legend-mark.missing { border-top-style: dashed; }
.legend-mark.manual { border-top-style: dotted; }
.legend-hint { margin-left: auto; }
.link-detail { font-size: 13px; display: grid; gap: 7px; border-top: 1px solid #e0e8f1; background: #f9fbfe; }
.link-summary span { color: #365374; }
.link-summary button { margin-left: auto; }
.link-endpoints { display: flex; gap: 6px 20px; flex-wrap: wrap; overflow-wrap: anywhere; }
.link-endpoints span { color: #4b617a; }
</style>
