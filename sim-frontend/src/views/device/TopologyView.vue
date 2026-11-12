<template>
  <div class="topology-page">
    <PageHeader
      title="拓扑"
      subtitle="核对库存设备的 LLDP 邻接与链路基线；布局发布、基线修改和运行态观察分别记录。"
    >
      <template #actions>
        <el-button :loading="loading" @click="loadTopology">刷新</el-button>
        <AdminAction v-slot="{ disabled }"><el-button type="primary" :disabled="disabled" :loading="discovering" @click="runDiscover">运行态校验</el-button></AdminAction>
        <AdminAction v-slot="{ disabled }">
          <el-button type="primary" :disabled="disabled || !nodes.length || savingDraft" :loading="publishing" @click="publishToDashboard">发布到总览</el-button>
        </AdminAction>
        <el-dropdown trigger="click" @command="handleTopologyCommand">
          <el-button>更多</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <AdminAction v-slot="{ disabled }">
                <el-dropdown-item command="create" :disabled="disabled">新建拓扑</el-dropdown-item>
                <el-dropdown-item command="excel" :disabled="disabled">导入 Excel 基线</el-dropdown-item>
                <el-dropdown-item command="baseline" :disabled="disabled" v-if="canConfirmRuntimeBaseline">确认 LLDP 基线</el-dropdown-item>
                <el-dropdown-item command="save" :disabled="disabled || !nodes.length || savingDraft || publishing">保存草稿</el-dropdown-item>
              </AdminAction>
              <el-dropdown-item command="versions" divided>版本记录</el-dropdown-item>
              <el-dropdown-item command="restore" :disabled="savingDraft || publishing">恢复已发布布局</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </template>
    </PageHeader>

    <el-alert v-if="topologyLoadError" :title="topologyLoadError" type="error" :closable="false" show-icon />
    <div class="topology-context">
      <div class="topology-counts">
        <el-tag type="info">{{ topologyLoadError ? '拓扑数据暂不可用' : `设备 ${nodes.length}` }}</el-tag>
        <el-tag v-if="!topologyLoadError" type="info">{{ baselineEdgeCount ? `基线关系 ${baselineEdgeCount}` : '未设置链路基线' }}</el-tag>
        <el-tag v-if="manualEdgeCount" type="info">非基线关系 {{ manualEdgeCount }}</el-tag>
        <el-tag v-if="selectedNode" type="warning">选中 {{ selectedNode.label }}</el-tag>
      </div>
      <div v-if="selectedNode" class="v7b-actions">
        <el-button size="small" type="primary" @click="openSelectedWebSSH">开终端</el-button>
        <el-button size="small" @click="openSelectedDeploy">去下发</el-button>
      </div>
      <input ref="fileInput" class="file-input" type="file" accept=".xlsx" @change="onExcelSelected">
    </div>

    <div v-if="runtimeCheck" class="runtime-status">
      <el-tag :type="runtimeCheck.is_stale || runtimeCheck.evidence_stale || runtimeCheck.mode_changed ? 'info' : runtimeCheck.status === 'matched' ? 'success' : 'warning'">
        {{ runtimeStatusText }}
      </el-tag>
      <span>SSH返回 {{ runtimeCheck.ssh_success }}/{{ runtimeCheck.ssh_success + runtimeCheck.ssh_failed }}</span>
      <span>可解析 {{ runtimeCheck.coverage?.parsed_devices ?? '未知' }}/{{ runtimeCheck.coverage?.expected_devices ?? nodes.length }}</span>
      <span>未观察到 {{ runtimeCheck.diff.missing.length }}</span>
      <span>非基线邻接 {{ runtimeCheck.diff.unexpected.length }}</span>
      <span v-if="runtimeCheck.created_at">{{ formatTime(runtimeCheck.created_at) }}</span>
      <span v-if="discoverResult">{{ discoverResult }}</span>
    </div>

    <p class="topology-scope">LLDP记录邻接关系，可能经过共享二层段；单向观察不代表双向确认。本图不检验业务可达，也不证明完整物理网络。</p>
    <details v-if="runtimeCheck" class="coverage-details">
      <summary>查看采集覆盖与差异</summary>
      <div class="coverage-body">
        <template v-if="runtimeCheck.coverage">
          <p>观察覆盖仅针对本次库存 {{ runtimeCheck.coverage.expected_devices }} 台；双向邻接 {{ runtimeCheck.coverage.bidirectional_links }} 条，单向邻接 {{ runtimeCheck.coverage.one_sided_links }} 条。观察有效期五分钟；历史差异保留供回看。</p>
          <el-table :data="runtimeCheck.coverage.devices" size="small">
            <el-table-column prop="hostname" label="设备" min-width="120" />
            <el-table-column label="命令返回" min-width="100"><template #default="{ row }">{{ row.ssh_ok ? '已返回' : '未成功' }}</template></el-table-column>
            <el-table-column label="解析范围" min-width="160"><template #default="{ row }">{{ row.state === 'parsed' ? '已解析邻居表' : row.state === 'empty' ? '明确报告零邻居' : row.state === 'truncated' ? '回显截断/分页' : row.state === 'failed' ? '采集失败' : '无法确认' }}</template></el-table-column>
            <el-table-column label="观察时间" min-width="170"><template #default="{ row }">{{ formatTime(row.observed_at) }}</template></el-table-column>
          </el-table>
          <p v-if="runtimeCheck.coverage.unmanaged_neighbors.length">库存外邻居：只显示观察，不自动创建资产或链路。</p>
          <ul><li v-for="(item, i) in runtimeCheck.coverage.unmanaged_neighbors" :key="`unmanaged-${i}`">{{ item.hostname }} {{ item.local_interface }} → {{ item.neighbor_device }} {{ item.remote_interface }}</li></ul>
          <p v-if="runtimeCheck.coverage.multi_neighbor_ports.length">同一端口观察到多个邻居，可能存在共享二层段；未假造中间设备。</p>
          <ul><li v-for="(item, i) in runtimeCheck.coverage.multi_neighbor_ports" :key="`shared-${i}`">{{ item.hostname }} {{ item.local_interface }}：{{ item.neighbors.join('、') }}</li></ul>
        </template>
        <p v-else>这份历史记录没有逐设备解析覆盖与观察时效证明，请重新运行校验。原始差异仍保留。</p>
        <p>基线中本次未观察到：{{ runtimeCheck.diff.missing.length }} 条；本次观察到的非基线邻接：{{ runtimeCheck.diff.unexpected.length }} 条。采集不完整时不能据此断定物理断线。</p>
        <ul><li v-for="(link, i) in runtimeCheck.diff.missing" :key="`missing-${i}`">未观察到 · {{ link.source_device }} {{ link.source_interface }} ↔ {{ link.target_device }} {{ link.target_interface }}</li><li v-for="(link, i) in runtimeCheck.diff.unexpected" :key="`new-${i}`">非基线邻接 · {{ link.source_device }} {{ link.source_interface }} ↔ {{ link.target_device }} {{ link.target_interface }}</li></ul>
      </div>
    </details>

    <el-alert
      v-if="runtimeCheck?.errors.length"
      class="runtime-diagnostics"
      type="warning"
      title="校验不完整：以下问题未解决前不能确认基线"
      :closable="false"
      show-icon
    >
      <ul>
        <li v-for="(error, index) in runtimeCheck.errors" :key="index">{{ error }}</li>
      </ul>
    </el-alert>

    <TopologyCanvas
      v-if="nodes.length" :key="topologyId" ref="canvas"
      :nodes="nodes" :edges="edges" :positions="draftPositions" :selected-id="selectedNode?.id"
      @select="selectGraphNode" @move="moveGraphNode"
    />
    <div v-if="!nodes.length && !loading && !topologyLoadError" class="empty-state">
      <template v-if="!topologyId">
        还没有拓扑，请先
        <AdminAction v-slot="{ disabled }">
          <el-button link type="primary" :disabled="disabled" @click="showCreateDialog = true">新建拓扑</el-button>
        </AdminAction>
        ，再导入 Excel 或添加设备。
      </template>
      <template v-else>
        当前拓扑还没有设备，请
        <AdminAction v-slot="{ disabled }">
          <el-button link type="primary" :disabled="disabled" @click="selectExcel">导入 Excel 基线</el-button>
        </AdminAction>
        或
        <el-button link type="primary" @click="router.push('/devices')">添加设备</el-button>
      </template>
    </div>

    <el-dialog v-model="importDialogVisible" title="Excel基线导入预检" width="min(640px, 92vw)" draggable>
      <el-checkbox v-model="inventoryOnly" :disabled="importing || validatingImport" @change="validateSelectedExcel">
        仅设备库存（链路尚未验证）
      </el-checkbox>
      <el-alert v-if="inventoryOnly" type="warning" :closable="false"
        title="仅记录设备身份，不代表 LLDP 或链路验证通过。仅适用于当前和历史基线均无链路的拓扑，Excel 不能包含互联关系。" />
      <div v-if="importPreview" class="import-preview">
        <el-alert
          :type="importPreview.is_valid ? 'success' : 'error'"
          :closable="false"
          :title="importPreview.is_valid ? '校验通过' : '校验失败'"
        />
        <div class="preview-counts">
          <span>设备 {{ importPreview.current_device_count }} → {{ importPreview.device_count }}</span>
          <span>链路 {{ importPreview.current_link_count }} → {{ importPreview.link_count }}</span>
          <span v-if="importPreview.replaced_link_count" class="replacement-warning">
            将替换 {{ importPreview.replaced_link_count }} 条现有基线链路
          </span>
          <span>已忽略敏感列 {{ importPreview.ignored_sensitive_columns.length }}</span>
        </div>
        <el-table v-if="importPreview.issues.length" :data="importPreview.issues" max-height="260">
          <el-table-column prop="code" label="规则" width="190" />
          <el-table-column prop="message" label="问题" />
          <el-table-column prop="row" label="行" width="70" />
        </el-table>
      </div>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="validatingImport || !importPreview?.is_valid || importPreview.inventory_only !== inventoryOnly" :loading="importing" @click="confirmImport">
          确认导入并创建版本
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="versionsVisible" title="拓扑基线版本" width="min(860px, 94vw)" draggable>
      <el-alert v-if="versionLoadError" :title="versionLoadError" type="error" :closable="false" show-icon><el-button @click="openVersions">重试版本记录</el-button></el-alert>
      <el-table
        :data="versions"
        :empty-text="versionsLoading ? '加载中...' : versionLoadError || '暂无版本记录'"
        max-height="460"
      >
        <el-table-column prop="version" label="版本" width="80">
          <template #default="scope">v{{ scope.row.version }}</template>
        </el-table-column>
        <el-table-column prop="source_name" label="来源" min-width="180" />
        <el-table-column prop="source_type" label="类型" width="170">
          <template #default="{ row }">{{ row.source_type === 'inventory_only' ? '仅库存（链路未验证）' : row.source_type === 'lldp' ? 'LLDP观察固化' : row.source_type === 'ensp' ? '历史LLDP固化' : row.source_type }}</template>
        </el-table-column>
        <el-table-column label="变更" min-width="220">
          <template #default="scope">{{ versionSummary(scope.row) }}</template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="scope">{{ formatTime(scope.row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="scope">
            <AdminAction v-slot="{ disabled }">
              <el-button link type="danger" :disabled="disabled || rollingBack" @click="rollbackVersion(scope.row.version)">回滚</el-button>
            </AdminAction>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="showCreateDialog" title="新建拓扑" width="420px" draggable>
      <el-form :model="createForm" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" placeholder="例如：实训主拓扑" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creatingTopo" @click="handleCreateTopology">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import PageHeader from '../../components/v7b/PageHeader.vue'
import TopologyCanvas from '../../components/TopologyCanvas.vue'
import { formatApiTime } from '../../utils/datetime'
import { type GraphEdge, type GraphNode } from '../../utils/topologyCanvas'
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElCheckbox } from 'element-plus/es/components/checkbox/index'
import { notifyRequestError } from '../../utils/requestError'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { useAutoRefresh } from '../../utils/autoRefresh'
import {
  createTopology,
  discoverTopologyLinks,
  confirmRuntimeTopologyBaseline,
  getDevices,
  getLatestRuntimeCheck,
  getTopologies,
  getTopologyLinks,
  getTopologyLayout,
  getTopologyVersions,
  importTopologyBaseline,
  publishTopologyLayout,
  rollbackTopologyVersion,
  saveTopologyLayoutDraft,
  validateTopologyImport,
  type DeviceRecord,
  type ImportPreview,
  type RuntimeCheckResult,
  type TopologyLinkRecord,
  type TopologyLayoutPosition,
  type TopologyRuntimeDiff,
  type TopologyVersion,
} from '../../api/device'
import { useLabContextStore } from '../../stores/labContext'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import AdminAction from '../../components/AdminAction.vue'

const canvas = ref<InstanceType<typeof TopologyCanvas>>()
const fileInput = ref<HTMLInputElement>()
const nodes = ref<GraphNode[]>([])
const edges = ref<GraphEdge[]>([])
const selectedNode = ref<GraphNode | null>(null)
const router = useRouter()

function handleTopologyCommand(command: string) {
  if (command === 'create') showCreateDialog.value = true
  else if (command === 'excel') selectExcel()
  else if (command === 'baseline') confirmRuntimeBaseline()
  else if (command === 'save') saveDraft()
  else if (command === 'versions') openVersions()
  else if (command === 'restore') restorePublished()
}
const route = useRoute()
const labCtx = useLabContextStore()
const copilot = useAiCopilotStore()

function selectGraphNode(node: GraphNode) {
  selectedNode.value = node
  const deviceId = Number(node.id)
  labCtx.setDevice({
    id: deviceId,
    hostname: node.label,
    mgmt_ip: node.mgmt_ip,
  })
  copilot.setSelection({
    kind: 'device',
    id: deviceId,
    label: node.label,
    detail: node.mgmt_ip || '',
  })
  // At this breakpoint the assistant overlays the topology and device actions.
  if (!copilot.open && !window.matchMedia('(max-width: 900px)').matches) copilot.setOpen(true)
}

function openSelectedWebSSH() {
  if (!selectedNode.value) return
  router.push(`/webssh/${selectedNode.value.id}`)
}

function openSelectedDeploy() {
  if (!selectedNode.value) return
  router.push({ path: '/deploy', query: { device_id: selectedNode.value.id } })
}
const loading = ref(false)
const topologyLoadError = ref('')
let topologyLoadEpoch = 0
const discovering = ref(false)
const savingDraft = ref(false)
const publishing = ref(false)
const rollingBack = ref(false)
const creatingTopo = ref(false)
const showCreateDialog = ref(false)
const createForm = ref({ name: '', description: '' })
const discoverResult = ref('')
const topologyId = ref(0)
const selectedExcel = ref<File>()
const importPreview = ref<ImportPreview>()
const importDialogVisible = ref(false)
const importing = ref(false)
const inventoryOnly = ref(false)
const validatingImport = ref(false)
const versionsVisible = ref(false)
const versionRequest = useSnapshotRequest('拓扑版本记录')
const versionsLoading = versionRequest.loading
const versionLoadError = versionRequest.error
const versionsTarget = ref<number | null>(null)
const versions = ref<TopologyVersion[]>([])
const runtimeCheck = ref<RuntimeCheckResult | null>(null)
const draftPositions = ref<Record<string, TopologyLayoutPosition>>({})
// 本地有未保存的拖拽改动时，轮询不得用服务端草稿覆盖
const layoutDirty = ref(false)
let layoutRevision = 0

const canConfirmRuntimeBaseline = computed(() => Boolean(
  runtimeCheck.value
  && !runtimeCheck.value.is_stale
  && runtimeCheck.value.evidence_stale === false
  && !runtimeCheck.value.mode_changed
  && runtimeCheck.value.coverage?.version === 'lldp-brief-d05.1'
  && !runtimeCheck.value.confirmed_version_id
  && runtimeCheck.value.status !== 'partial'
  && runtimeCheck.value.errors.length === 0
  && runtimeCheck.value.ssh_failed === 0
  && runtimeCheck.value.ssh_success === nodes.value.length
  && runtimeCheck.value.links.length,
))

const baselineEdgeCount = computed(() => edges.value.filter(edge => edge.source_type === 'baseline' && edge.runtime_diff !== 'unexpected').length)
const manualEdgeCount = computed(() => edges.value.filter(edge => edge.source_type !== 'baseline' && edge.runtime_diff !== 'unexpected').length)
const runtimeStatusText = computed(() => runtimeCheck.value?.is_stale ? '历史校验：基线已变更，请重新校验'
  : runtimeCheck.value?.mode_changed ? '执行模式已改变，请重新校验'
  : runtimeCheck.value?.evidence_stale ? '历史观察已过期或覆盖未知，请重新校验' : ({
  matched: '本次库存 LLDP 邻接与基线相符',
  different: '本次库存 LLDP 邻接存在差异',
  partial: '运行态校验不完整',
  no_baseline: '无链路基线，仅记录本次 LLDP 邻接',
}[runtimeCheck.value?.status || 'partial']))

const edgeKey = (source: string, sourceInterface: string, target: string, targetInterface: string) =>
  [source + ':' + sourceInterface, target + ':' + targetInterface].sort().join('|')

const applyRuntimeDiff = (baseEdges: GraphEdge[], diff?: TopologyRuntimeDiff) => {
  if (!diff) return baseEdges
  const missing = new Set(diff.missing.map(link => edgeKey(
    link.source_device, link.source_interface, link.target_device, link.target_interface,
  )))
  const nodeIds = new Map(nodes.value.map(node => [node.label, node.id]))
  const decorated: GraphEdge[] = baseEdges.map(edge => ({
    ...edge,
    runtime_diff: edge.source_type === 'baseline' && missing.has(edgeKey(edge.source_name, edge.source_interface, edge.target_name, edge.target_interface))
      ? 'missing' as const
      : undefined,
  }))
  for (const link of diff.unexpected) {
    const source = nodeIds.get(link.source_device)
    const target = nodeIds.get(link.target_device)
    if (!source || !target) continue
    decorated.push({
      source,
      target,
      source_name: link.source_device,
      target_name: link.target_device,
      source_interface: link.source_interface,
      target_interface: link.target_interface,
      source_ip: link.source_ip,
      target_ip: link.target_ip,
      link_type: 'physical',
      status: 'up',
      bandwidth: '',
      discovery_source: 'lldp',
      source_type: 'observed',
      runtime_diff: 'unexpected',
    })
  }
  return decorated
}

const clearTopologyView = () => {
  nodes.value = []
  edges.value = []
  selectedNode.value = null
  runtimeCheck.value = null
  draftPositions.value = {}
  layoutDirty.value = false
  layoutRevision++
  versionsVisible.value = false
  versionsTarget.value = null
}

const loadTopology = async () => {
  const epoch = ++topologyLoadEpoch
  loading.value = true
  try {
    const topologies = await getTopologies()
    if (epoch !== topologyLoadEpoch) return
    if (!topologies || !topologies.length) {
      topologyId.value = 0
      clearTopologyView()
      topologyLoadError.value = ''
      return
    }

    const withDevices = topologies.filter((t: { device_count?: number }) => (t.device_count || 0) > 0)
    const preferred = Number(route.query.topology_id || labCtx.topologyId || topologyId.value || 0)
    const matched = preferred
      ? topologies.find((t: { id: number }) => t.id === preferred)
      : null
    const chosen = matched || withDevices[0] || topologies[0]
    if (topologyId.value !== (chosen?.id || topologies[0].id)) {
      clearTopologyView()
    }
    topologyId.value = chosen?.id || topologies[0].id
    labCtx.setTopology(topologyId.value)
    const revision = layoutRevision
    const [devices, links, latestCheck, layout] = await Promise.all([
      getDevices({ topology_id: topologyId.value }),
      getTopologyLinks(topologyId.value),
      getLatestRuntimeCheck(topologyId.value),
      getTopologyLayout(topologyId.value),
    ])
    if (epoch !== topologyLoadEpoch) return

    nodes.value = devices.map((d: DeviceRecord) => ({
      id: String(d.id),
      label: d.hostname,
      status: d.status,
      type: d.device_type,
      model: d.model || '',
      mgmt_ip: d.mgmt_ip,
      network_role: d.network_role
    }))
    if (selectedNode.value) {
      selectedNode.value = nodes.value.find(node => node.id === selectedNode.value?.id) || null
    }

    const names = new Map(devices.map(device => [device.id, device.hostname]))
    const baseEdges = links.map((l: TopologyLinkRecord) => ({
      source: String(l.source_device_id),
      target: String(l.target_device_id),
      source_name: names.get(l.source_device_id) || String(l.source_device_id),
      target_name: names.get(l.target_device_id) || String(l.target_device_id),
      source_interface: l.source_interface,
      target_interface: l.target_interface,
      source_ip: l.source_ip,
      target_ip: l.target_ip,
      link_type: l.link_type || 'physical',
      status: l.status,
      bandwidth: l.bandwidth || '',
      discovery_source: l.discovery_source || '',
      source_type: l.source_type,
    }))
    runtimeCheck.value = latestCheck
    edges.value = applyRuntimeDiff(baseEdges, latestCheck?.is_stale || latestCheck?.evidence_stale || latestCheck?.mode_changed ? undefined : latestCheck?.diff)
    // 保留尚未保存的本地布局
    if (!layoutDirty.value && revision === layoutRevision) {
      draftPositions.value = layout.draft_positions
    }

    topologyLoadError.value = ''
  } catch (error) {
    if (epoch === topologyLoadEpoch) {
      topologyLoadError.value = '拓扑读取失败，暂时无法确认当前拓扑；已显示图形可能陈旧，请刷新重试。'
      notifyRequestError(error, '加载拓扑失败')
    }
  } finally {
    if (epoch === topologyLoadEpoch) loading.value = false
  }
}

const currentPositions = () => canvas.value?.getPositions() || {}

function moveGraphNode(id: string, position: TopologyLayoutPosition) {
  if (!nodes.value.some(node => node.id === id)) return
  draftPositions.value = { ...draftPositions.value, [id]: position }
  layoutDirty.value = true
  layoutRevision++
}

const handleCreateTopology = async () => {
  const name = createForm.value.name.trim()
  if (!name) {
    ElMessage.warning('请填写拓扑名称')
    return
  }
  creatingTopo.value = true
  try {
    const created = await createTopology({
      name,
      description: createForm.value.description.trim() || undefined,
      topology_type: 'main',
    }) as unknown as { id: number }
    clearTopologyView()
    topologyId.value = created.id
    labCtx.setTopology(created.id)
    showCreateDialog.value = false
    createForm.value = { name: '', description: '' }
    ElMessage.success('拓扑已创建，可导入 Excel 或添加设备')
    await loadTopology()
  } catch {
    /* 拦截器已提示 */
  } finally {
    creatingTopo.value = false
  }
}

const saveDraft = async () => {
  const target = topologyId.value
  if (!target || !nodes.value.length || savingDraft.value || publishing.value) return
  const revision = layoutRevision
  savingDraft.value = true
  try {
    const layout = await saveTopologyLayoutDraft(target, currentPositions())
    if (topologyId.value !== target) return
    acceptLayout(layout.draft_positions, revision)
    ElMessage.success('拓扑草稿已保存')
  } catch {
    /* 拦截器已提示 */
  } finally {
    savingDraft.value = false
  }
}

const restorePublished = async () => {
  const target = topologyId.value
  if (!target || savingDraft.value || publishing.value) return
  const revision = layoutRevision
  savingDraft.value = true
  try {
    const layout = await getTopologyLayout(target)
    if (topologyId.value === target && acceptLayout(layout.published_positions, revision)) {
      ElMessage.success('已恢复已发布布局')
    }
  } catch (error) {
    notifyRequestError(error, '恢复已发布布局失败')
  } finally {
    savingDraft.value = false
  }
}

function acceptLayout(positions: Record<string, TopologyLayoutPosition>, revision: number) {
  if (layoutRevision !== revision) return false
  draftPositions.value = positions
  layoutDirty.value = false
  layoutRevision++
  return true
}

const publishToDashboard = async () => {
  const target = topologyId.value
  if (!target || !nodes.value.length || savingDraft.value || publishing.value) return
  try {
    await ElMessageBox.confirm('确定把当前布局发布到运维总览？发布后总览页将使用这份拓扑。', '发布到运维总览', { type: 'warning' })
  } catch {
    return
  }
  if (topologyId.value !== target || savingDraft.value || publishing.value) return
  const revision = layoutRevision
  publishing.value = true
  try {
    const saved = await saveTopologyLayoutDraft(target, currentPositions())
    const accepted = topologyId.value === target && acceptLayout(saved.draft_positions, revision)
    const layout = await publishTopologyLayout(target)
    if (accepted && topologyId.value === target) acceptLayout(layout.published_positions, revision + 1)
    ElMessage.success('已发布到运维总览')
  } catch {
    /* 拦截器已提示 */
  } finally {
    publishing.value = false
  }
}

const runDiscover = async () => {
  if (!topologyId.value) {
    ElMessage.warning('请先加载拓扑')
    return
  }
  discovering.value = true
  discoverResult.value = ''
  try {
    const result = await discoverTopologyLinks(topologyId.value)
    discoverResult.value = `已归属库存的运行态链路 ${result.discovered} 条，未修改基线`
    await loadTopology()
    if (result.status === 'partial' || result.errors.length) {
      ElMessage.warning('运行态校验不完整，请查看页面诊断后重新校验')
    } else if (result.status === 'no_baseline') {
      ElMessage.warning('未设置链路基线，本次仅记录 LLDP 邻接；可查看采集覆盖')
    } else {
      ElMessage.success('运行态校验完成')
    }
  } catch (error) {
    notifyRequestError(error, '运行态校验失败')
  } finally {
    discovering.value = false
  }
}

const confirmRuntimeBaseline = async () => {
  if (!topologyId.value || !runtimeCheck.value || !canConfirmRuntimeBaseline.value) return
  try {
    await ElMessageBox.confirm(
      `将以本次 LLDP 运行态校验的 ${runtimeCheck.value.links.length} 条链路替换当前基线，并创建可回滚版本。`,
      '确认固化 LLDP 基线',
      { type: 'warning', confirmButtonText: '确认固化', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const result = await confirmRuntimeTopologyBaseline(topologyId.value, runtimeCheck.value.check_id)
    await loadTopology()
    ElMessage.success(`已固化 LLDP 基线 v${result.version}，共 ${result.link_count} 条链路`)
  } catch (error) {
    notifyRequestError(error, 'eNSP 基线固化失败')
  }
}

const selectExcel = () => fileInput.value?.click()

const onExcelSelected = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !topologyId.value) return
  selectedExcel.value = file
  inventoryOnly.value = false
  importDialogVisible.value = true
  await validateSelectedExcel()
}

const validateSelectedExcel = async () => {
  if (!selectedExcel.value || !topologyId.value) return
  importPreview.value = undefined
  validatingImport.value = true
  try {
    importPreview.value = await validateTopologyImport(topologyId.value, selectedExcel.value, inventoryOnly.value)
  } catch (error) {
    notifyRequestError(error, 'Excel基线校验失败')
  } finally {
    validatingImport.value = false
  }
}

const confirmImport = async () => {
  if (!selectedExcel.value || !importPreview.value?.is_valid || validatingImport.value || importPreview.value.inventory_only !== inventoryOnly.value) return
  importing.value = true
  try {
    await importTopologyBaseline(topologyId.value, selectedExcel.value, inventoryOnly.value)
    importDialogVisible.value = false
    await loadTopology()
    ElMessage.success(inventoryOnly.value ? '设备库存版本已创建，链路尚未验证' : '基线导入完成，已创建新版本')
  } catch (error) {
    notifyRequestError(error, '基线导入失败')
  } finally {
    importing.value = false
  }
}

const openVersions = async () => {
  if (!topologyId.value) return
  const target = topologyId.value
  if (versionsTarget.value !== target) versions.value = []
  versionsTarget.value = target
  versionsVisible.value = true
  await versionRequest.run(() => getTopologyVersions(target), value => {
    if (target === topologyId.value) versions.value = value
    else versionsVisible.value = false
  })
}

const rollbackVersion = async (version: number) => {
  if (rollingBack.value) return
  const target = topologyId.value
  if (versionsTarget.value !== topologyId.value) {
    ElMessage.warning('拓扑已切换，请重新打开版本记录后操作')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将拓扑基线回滚到 v${version}？系统会先保留当前版本记录。`,
      '回滚拓扑基线',
      { type: 'warning', confirmButtonText: '确认回滚', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  if (target !== topologyId.value || versionsTarget.value !== target) {
    ElMessage.warning('拓扑已切换，本次未提交回滚，请重新打开版本记录')
    return
  }
  rollingBack.value = true
  try {
    await rollbackTopologyVersion(target, version)
    if (topologyId.value !== target) {
      ElMessage.success(`原拓扑 #${target} 已完成回滚，请在对应拓扑查看结果`)
      return
    }
    await Promise.all([loadTopology(), openVersions()])
    ElMessage.success(`已回滚到 v${version}`)
  } catch {
    /* 拦截器已提示 */
  } finally {
    rollingBack.value = false
  }
}

const versionSummary = (version: TopologyVersion) => {
  const summary = version.summary
  return `设备 +${summary.added_devices || 0}/-${summary.removed_devices || 0}/改${summary.changed_devices || 0}，链路 +${summary.added_links || 0}/-${summary.removed_links || 0}/改${summary.changed_links || 0}`
}

const formatTime = (value: string) => formatApiTime(value)

onMounted(() => {
  loadTopology()
  useAutoRefresh(loadTopology, 20000)
})

onUnmounted(() => {
  topologyLoadEpoch++
})
</script>

<style scoped>
.topology-page {
  min-width: 0;
  min-height: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.topology-toolbar,
.runtime-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.toolbar-actions,
.toolbar-counts,
.runtime-status,
.preview-counts {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.file-input {
  display: none;
}

.runtime-status {
  justify-content: flex-start;
  min-height: 36px;
  padding: 8px 12px;
  border-left: 3px solid #35c7d7;
  background: var(--v7b-surface);
  color: var(--v7b-text);
  font-size: 13px;
}

.runtime-diagnostics {
  flex-shrink: 0;
  margin-bottom: 12px;
  max-height: 180px;
  overflow-y: auto;
}

.runtime-diagnostics ul {
  margin: 6px 0 0;
  padding-left: 20px;
  overflow-wrap: anywhere;
}

.empty-state {
  padding: 40px;
  text-align: center;
  color: #7f93a6;
}

.import-preview {
  display: grid;
  gap: 16px;
}

.preview-counts {
  color: var(--v7b-muted);
}

.replacement-warning {
  color: #ff6b6b;
  font-weight: 600;
}

@media (max-width: 720px) {
  .topology-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar-actions {
    width: 100%;
  }
}

.topology-context { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.topology-scope { color: var(--v7b-muted); font-size: 12px; line-height: 1.6; margin: 8px 0; }
.coverage-details { flex-shrink: 0; margin-bottom: 10px; color: var(--v7b-text); font-size: 12px; }
.coverage-details summary { cursor: pointer; color: var(--v7b-accent); padding: 7px 0; }
.coverage-body { max-height: 36vh; overflow: auto; padding: 10px 12px; background: var(--v7b-surface); border: 1px solid var(--v7b-line); line-height: 1.7; overflow-wrap: anywhere; }
.topology-counts { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.topology-counts :deep(.el-tag--info) { background: #fff; color: var(--v7b-muted); border-color: var(--v7b-line); }
</style>
