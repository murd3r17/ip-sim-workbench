/** 页面实时数据快照：供右侧 Copilot 感知当前页面真实数据（设备/告警/任务/拓扑等）。
 * 每次路由切换时由 AiCopilotPanel 调用，失败静默返回空串（不影响对话）。 */
import { getDevices, getTopologies } from '../api/device'
import { getDashboardSummary } from '../api/dashboard'
import { getAlarms, getMonitorStats, getMonitorTasks } from '../api/monitor'
import { getConfigVersions, getDeployBatches, getDeployTasks } from '../api/deploy'
import { getOperationLogs, getSession, getSessionFaults, listLabs } from '../api/training'
import { getKnowledgeHealth, getKnowledgeDocuments } from '../api/knowledge'
import { getSystemInfo } from '../api/system'
import { formatApiTime } from './datetime'

export interface PageDataCtx {
  sessionId?: number | null
  labId?: number | null
  labTitle?: string
  topologyId?: number | null
  device?: { id: number; hostname: string; mgmt_ip?: string } | null
  labSteps?: any[]
}

function fmtTime(value?: string | null): string {
  return formatApiTime(value)
}

async function buildTrainingSnapshot(ctx: PageDataCtx): Promise<string> {
  const labs = (await listLabs().catch(() => [])) as any[]
  const lines = labs.map((l: any) => {
    const mode = l.mode_facts?.device_mode
    const connection = mode === 'sim' ? '模拟设备' : mode === 'ssh' ? '真实设备' : '设备连接方式未知'
    return `- ${l.title} | ${l.status} | ${l.is_sandbox ? '自由练习' : '引导实验'} | ${connection} | topo=${l.topology_id}`
  })
  const parts = [`【实训】Lab列表:\n${(lines.join('\n') || '无')}`]
  if (!ctx.sessionId) return parts.join('\n')
  try {
    const session = await getSession(ctx.sessionId) as any
    const logs = (await getOperationLogs(ctx.sessionId).catch(() => [])) as any[]
    const faults = (await getSessionFaults(ctx.sessionId).catch(() => [])) as any[]
    const openFaults = faults.filter((f) => f.resolved_correctly !== true)
    const recent = logs.slice(-15).map((row) => `- ${row.command || row.action} | 客户端报告${row.success ? '成功' : '失败'}（未验证） | ${row.target_device || '-'}`)
    const steps = Array.isArray(ctx.labSteps) ? ctx.labSteps : []
    parts.push(
      `当前会话 #${ctx.sessionId} 「${ctx.labTitle || ''}」 status=${session.status} 技能达标未验证${session.score != null ? `（历史参考分 ${session.score}，未经验证）` : ''} 用时=${session.time_spent_seconds ?? '-'}s`,
      `步骤总数 ${steps.length || '未设置'}；当前步骤及完成进度未验证，不能根据日志条数推断达标或当前步骤。`,
      `未解决故障 ${openFaults.length} 条`,
      `最近操作:\n${recent.join('\n') || '无'}`,
    )
  } catch {
    parts.push(`当前会话 #${ctx.sessionId}（详情暂不可用）`)
  }
  return parts.join('\n')
}

export async function buildPageDataContext(path: string, ctx: PageDataCtx = {}): Promise<string> {
  try {
    if (path === '/dashboard' || path === '/') {
      const s = await getDashboardSummary()
      const lines = [
        `设备: 总数${s.devices?.total ?? '-'}, 在线${s.devices?.online ?? '-'}, SSH可达${s.devices?.ssh_reachable ?? '-'}`,
        `告警: 活跃${s.alarms?.active ?? '-'}, 严重${s.alarms?.critical ?? '-'}`,
        `任务: 运行${s.tasks?.active ?? '-'}, 等待${s.tasks?.pending ?? '-'}`,
        `风险: ${s.risks?.items?.length ?? 0}项`,
        `拓扑: ${s.topology?.name || '未配置'}, ${s.topology?.device_count ?? 0}设备/${s.topology?.link_count ?? 0}链路`,
        `实训进行中: ${s.training?.active ?? 0}`,
      ]
      if (ctx.sessionId) lines.push(`当前实训会话 #${ctx.sessionId} ${ctx.labTitle || ''}`)
      return `【运维总览】\n${lines.join('\n')}`
    }
    if (path === '/devices' || path.startsWith('/webssh')) {
      const devices = (await getDevices()) as any[]
      if (!devices?.length) return '【设备】当前无设备记录'
      const lines = devices.map((d: any) => `- ${d.hostname} | ${d.mgmt_ip || '-'}:${d.ssh_port ?? 22} | ${d.status || '-'} | ${d.model || d.device_type || '-'}`)
      const extras: string[] = []
      if (ctx.device) extras.push(`当前选中设备: ${ctx.device.hostname}#${ctx.device.id} ${ctx.device.mgmt_ip || ''}`)
      if (ctx.sessionId) {
        extras.push(`当前实训会话 #${ctx.sessionId} ${ctx.labTitle || ''}`)
        const logs = (await getOperationLogs(ctx.sessionId).catch(() => [])) as any[]
        const recent = logs.slice(-8).map((row) => `- ${row.command || row.action} | 客户端报告${row.success ? '成功' : '失败'}（未验证）`)
        extras.push(`最近实训命令:\n${recent.join('\n') || '无'}`)
      }
      return `【设备列表 ${devices.length}台】\n${lines.join('\n')}${extras.length ? `\n${extras.join('\n')}` : ''}`
    }
    if (path === '/topology') {
      const topologies = (await getTopologies().catch(() => [])) as any[]
      const devices = (await getDevices().catch(() => [])) as any[]
      const topoLines = topologies.map((t) => `- ${t.name} (id=${t.id}, ${t.status || '-'})`)
      const devLines = devices.map((d) => `- ${d.hostname} | ${d.mgmt_ip} | ${d.status}`)
      return `【拓扑】\n拓扑列表:\n${(topoLines.join('\n') || '无')}\n设备:\n${(devLines.join('\n') || '无')}${ctx.topologyId ? `\n当前拓扑 id=${ctx.topologyId}` : ''}`
    }
    if (path === '/alarms') {
      const alarms = await getAlarms({ limit: 20 })
      if (!alarms?.length) return '【告警】当前无告警'
      const lines = alarms.map((a: any) => `- ${a.device_name || a.device_id} | ${a.alarm_type} | ${a.severity} | ${a.status} | ${a.message || ''}`)
      return `【告警 ${alarms.length}条】\n${lines.join('\n')}`
    }
    if (path === '/monitor') {
      const stats = (await getMonitorStats().catch(() => null)) as Record<string, any> | null
      const tasks = (await getMonitorTasks({ limit: 5 }).catch(() => [])) as any[]
      const s = stats || {}
      const taskLines = tasks.map((t: any) => `- job#${t.id} ${t.job_type} ${t.status} success=${t.success_count ?? 0} fail=${t.failure_count ?? 0}`)
      return `【监控】\n设备总数${s.totalDevices ?? '-'}, 在线${s.onlineDevices ?? '-'}, 活跃告警${s.activeAlarms ?? '-'}, 警告${s.warningAlarms ?? '-'}\n最近任务:\n${(taskLines.join('\n') || '无')}`
    }
    if (path === '/deploy') {
      const batches = (await getDeployBatches().catch(() => [])) as any[]
      const tasks = (await getDeployTasks().catch(() => [])) as any[]
      const batchLines = batches.map((b: any) => `- batch#${b.id} ${b.name || ''} ${b.source || ''} items=${(b.items || []).length}`)
      const taskLines = tasks.slice(0, 10).map((t: any) => `- task#${t.id} device=${t.device_id} ${t.status}`)
      return `【配置下发】\n批次:\n${(batchLines.join('\n') || '无')}\n任务:\n${(taskLines.join('\n') || '无')}`
    }
    if (path === '/config-versions') {
      const versions = (await getConfigVersions().catch(() => [])) as any[]
      const lines = versions.slice(0, 10).map((v: any) => `- v${v.version_number} device=${v.device_id} ${v.source || ''} ${fmtTime(v.created_at)}`)
      return `【配置管理】最近版本:\n${(lines.join('\n') || '无')}`
    }
    if (path === '/training') {
      return await buildTrainingSnapshot(ctx)
    }
    if (path === '/knowledge') {
      const health = (await getKnowledgeHealth().catch(() => null)) as Record<string, any> | null
      const docs = (await getKnowledgeDocuments().catch(() => [])) as any[]
      const h = health || {}
      return `【知识库】provider=${h.provider || '-'} available=${h.available ?? '-'} 文档数=${h.document_count ?? docs.length}`
    }
    if (path.startsWith('/system')) {
      const info = (await getSystemInfo().catch(() => null)) as Record<string, any> | null
      if (!info) return '【系统管理】系统信息暂不可用（可能需要管理员权限）'
      return `【系统管理】app=${info.app_name || info.version || '-'} db=${info.database_status || info.db_status || '-'} ${JSON.stringify(info).slice(0, 800)}`
    }
    return ''
  } catch {
    return ''
  }
}
