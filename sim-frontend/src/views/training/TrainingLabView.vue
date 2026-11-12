<template>
  <div class="training-lab v7b-page">
    <PageHeader
      title="实训"
      subtitle="从实验列表开始或继续会话，在同一页记录笔记、查看提示和复盘；历史会话只读，不会覆盖旧记录。"
    >
      <template #actions>
        <el-button @click="loadLabs">刷新</el-button>
        <AdminAction v-slot="{ disabled }">
          <el-button type="primary" :disabled="disabled || !topologies.length" @click="showCreateDialog = true">创建 Lab</el-button>
        </AdminAction>
      </template>
    </PageHeader>
    <el-alert v-if="labLoadError" :title="labLoadError" type="error" :closable="false" show-icon />
    <el-alert v-if="topologyLoadError" :title="topologyLoadError" type="error" :closable="false" show-icon><el-button @click="loadTopologies">重试拓扑列表</el-button></el-alert>
    <!-- 顶部统计 -->
    <el-row class="training-stats" :gutter="16" style="margin-bottom: 16px">
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value">{{ labLoadError ? '—' : stats.totalLabs }}</div>
            <div class="stat-label">Lab总数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value" style="color: var(--v7b-ok)">{{ labLoadError ? '—' : stats.readyLabs }}</div>
            <div class="stat-label">就绪Lab</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value" style="color: #409eff">{{ sessionLoadError ? '—' : stats.activeSessions ?? '-' }}</div>
            <div class="stat-label">进行中会话</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value" style="color: var(--v7b-warn)">{{ sessionLoadError ? '—' : stats.completedSessions }}</div>
            <div class="stat-label">已完成会话</div>
          </div>
        </el-card>
      </el-col>
    </el-row>
    <div class="training-note">
      关闭「实训会话」窗口不会结束实验。进行中的会话列在下方，也可从页面顶部实训条重新打开。
      历史会话只读回看，不再绑定终端或教练。
    </div>

    <!-- 操作栏：创建/刷新已在页头，避免重复；此处只保留搜索与拓扑缺口的说明。 -->
    <div class="lab-toolbar">
      <el-input v-model="searchText" placeholder="搜索 Lab 名称或目标" style="width: min(320px, 100%)" clearable />
      <div class="lab-toolbar-meta">
        <span>{{ labLoadError ? '实验列表暂不可用' : `共 ${filteredLabs.length} 个实验` }}</span>
        <el-button v-if="!topologies.length && !topologyLoadError" link type="primary" @click="$router.push('/topology')">先去创建拓扑</el-button>
      </div>
    </div>

    <!-- Lab列表 -->
    <el-card>
      <el-table :data="filteredLabs" row-key="id" v-loading="loading" max-height="420">
        <template #empty>
          <el-empty :description="labLoadError || '暂无实训实验。管理员可创建 Lab，无拓扑时请先到拓扑页导入基线。'" :image-size="72">
            <el-button v-if="!labLoadError" type="primary" @click="$router.push('/topology')">去拓扑页</el-button>
          </el-empty>
        </template>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="title" label="Lab名称" min-width="200" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="教学方式" width="110">
          <template #default="{ row }">
            <el-tag :type="row.is_sandbox ? 'warning' : 'info'" size="small">
              {{ row.is_sandbox ? '自由练习' : '引导实验' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="环境" width="120">
          <template #default="{ row }">
            <el-tooltip :content="modeSummary(row)" placement="top">
              <el-tag :type="deviceTagType(factsOf(row))" effect="plain" size="small">
                {{ deviceTagLabel(row) }}
              </el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="步骤" width="90" class-name="hide-narrow">
          <template #default="{ row }">
            <el-button
              v-if="Array.isArray(row.objectives) && row.objectives.length"
              link
              type="primary"
              aria-label="实验步骤"
              @click="showSteps(row)"
            >{{ row.objectives.length }} 步</el-button>
            <span v-else style="color: var(--el-text-color-secondary)">未设置</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <div class="lab-actions">
              <el-button v-if="activeSessionOf(row)" size="small" type="primary" @click="resumeLab(row)">继续实训</el-button>
              <el-button v-else size="small" type="primary" @click="handleStart(row)">开始实训</el-button>
              <el-dropdown trigger="click">
                <el-button size="small" aria-label="更多实验操作">更多操作</el-button>
                <template #dropdown><el-dropdown-menu>
                  <el-dropdown-item v-if="activeSessionOf(row)" @click="handleStart(row)">新开会话</el-dropdown-item>
                  <el-dropdown-item @click="handleSandbox(row)">自由练习</el-dropdown-item>
                  <AdminAction v-slot="{ disabled }"><el-dropdown-item :disabled="disabled" divided @click="handleDelete(row)">删除实验</el-dropdown-item></AdminAction>
                </el-dropdown-menu></template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card style="margin-top: 16px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>我的实训会话</span>
          <el-button size="small" @click="loadSessions">刷新</el-button>
        </div>
      </template>
      <el-alert v-if="sessionLoadError" :title="sessionLoadError" type="error" :closable="false" show-icon />
      <el-table :data="sessions" row-key="id" v-loading="sessionsLoading" max-height="480">
        <template #empty>
          <el-empty :description="sessionLoadError || '还没有实训会话。在上方实验点「开始实训」后，关闭窗口也能从这里再点进去。'" :image-size="72" />
        </template>
        <el-table-column prop="id" label="会话" width="80" />
        <el-table-column prop="lab_title" label="实验" min-width="180" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="sessionStatusType(row.status)">{{ sessionStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="技能结果" min-width="160">
          <template #default="{ row }">{{ row.score != null ? `历史参考 ${row.score}（未验证）` : '未验证' }}</template>
        </el-table-column>
        <el-table-column label="开始时间" width="180">
          <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260">
          <template #default="{ row }">
            <el-button type="primary" link @click="resumeSession(row.id)">
              {{ row.status === 'in_progress' ? '继续' : '查看' }}
            </el-button>
            <el-button type="danger" link @click="handleDeleteSession(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 实验步骤大纲弹窗 -->
    <el-dialog v-model="showStepsDialog" title="实验步骤" width="min(760px, 94vw)" draggable>
      <div v-if="stepsLab" class="steps-panel">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          :title="`建议时限 ${stepsLab?.time_limit_minutes ?? 45} 分钟。观察命令用于取证；手动勾选与AI回答不代表技能通过。`"
        />
        <div v-if="stepsLab.environment_spec" class="lab-requirements">
          <strong>先修与环境 · {{ stepsLab.content_version || '版本未登记' }}</strong>
          <ul><li v-for="(item, index) in stepsLab.environment_spec.prerequisites || []" :key="index">{{ item }}</li></ul>
          <p>环境绑定：{{ stepsLab.environment_spec.supports_binding === false ? '流程演示；现场核对请使用旁边的版本化网络实验' : stepsLab.environment_spec.trust_environment_id ? `#${stepsLab.environment_spec.trust_environment_id}，新会话冻结该环境` : '未绑定；可阅读，核对前需管理员绑定与预检' }}</p>
          <div v-if="isAdmin && stepsLab.environment_spec.supports_binding !== false" class="binding-actions">
            <el-select v-model="bindingEnvironmentId" placeholder="选择已建环境" clearable aria-label="实验绑定环境">
              <el-option v-for="env in bindingEnvironments" :key="env.id" :value="env.id" :label="`${env.name} · ${env.version} · ${env.status}`" />
            </el-select>
            <el-button :loading="bindingSaving" @click="saveLabBinding">保存环境绑定</el-button>
          </div>
          <p v-if="isAdmin && stepsLab.environment_spec.supports_binding !== false" class="muted">只影响之后的新会话；旧会话保持原版本。协议先修与设备写入仍单独核对。</p>
          <details><summary>内容来源</summary><p v-for="source in stepsLab.environment_spec.sources || []" :key="source" class="source-path">{{ source }}</p></details>
        </div>
        <div v-for="(s, i) in stepsLab.objectives || []" :key="i" class="step-item">
          <div class="step-head">
            <span class="step-no">{{ i + 1 }}</span>
            <strong>{{ s.name || s.goal }}</strong>
          </div>
          <div class="step-goal">目标：{{ s.goal }}</div>
          <div v-if="s.config_hint" class="step-hint">配置提示：{{ s.config_hint }}</div>
          <div v-if="s.verify_command" class="step-verify">
            观察建议：<code>{{ s.verify_command }}</code>
          </div>
          <div v-if="s.verification" class="step-goal">核验范围：{{ s.verification.limitations }}</div>
        </div>
      </div>
    </el-dialog>

    <!-- 创建Lab对话框 -->
    <el-dialog v-model="showCreateDialog" title="创建实训Lab" width="560px" draggable>      <el-form :model="createForm" label-width="100px">
        <el-form-item label="Lab名称">
          <el-input v-model="createForm.title" placeholder="输入Lab名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="3" placeholder="Lab描述" />
        </el-form-item>
        <el-form-item label="所属拓扑">
          <el-select v-model="createForm.topology_id" placeholder="选择拓扑" :disabled="!topologies.length">
            <el-option v-for="t in topologies" :key="t.id" :label="`${t.name} (id=${t.id})`" :value="t.id" />
          </el-select>
          <div v-if="!topologies.length" style="margin-top: 6px; color: var(--v7b-warn); font-size: 12px">
            还没有拓扑，请先到
            <el-button link type="primary" @click="$router.push('/topology')">拓扑页</el-button>
            创建或导入。
          </div>
        </el-form-item>
        <el-form-item label="时限(分钟)">
          <el-input-number v-model="createForm.time_limit_minutes" :min="5" :max="480" />
        </el-form-item>
        <el-form-item label="教学方式">
          <el-switch v-model="createForm.is_sandbox" active-text="自由练习" inactive-text="引导实验" />
          <div style="margin-left: 12px; color: var(--v7b-muted); font-size: 12px">
            教学方式只决定是否按步骤引导；设备连接与配置下发方式以服务端事实为准，未核验环境不生成可执行草稿。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="submitCreate" :loading="submitting">确定</el-button>
      </template>
    </el-dialog>

    <!-- 会话详情对话框 -->
    <el-dialog v-model="showSessionDialog" class="session-dialog" :title="sessionDialogTitle" width="min(700px, 96vw)" draggable :close-on-click-modal="false" append-to-body destroy-on-close>
      <el-alert
        v-if="sessionReadOnly"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
        :title="`该会话${sessionStatusLabel(currentSession?.status || '')}，只能回看：不能继续记操作、绑定终端或请求教练。需要练习请新开会话。`"
      />
      <el-alert
        v-else
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
        title="关闭本窗口不会结束实训。回到本页「我的实训会话」或点顶部实训条即可再打开。"
      />
      <div v-if="currentSession">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="会话ID">{{ currentSession.id }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="sessionStatusType(currentSession.status)">{{ sessionStatusLabel(currentSession.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="教学方式">{{ teachingLabel(currentSession) }}</el-descriptions-item>
          <el-descriptions-item label="设备连接">
            <el-tag :type="deviceTagTypeFor(currentSession)" effect="plain">{{ deviceTagLabelFor(currentSession) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="配置下发">{{ deployLabel(currentSession) }}</el-descriptions-item>
          <el-descriptions-item label="环境绑定">{{ bindingLabel(currentSession) }}</el-descriptions-item>
          <el-descriptions-item label="环境快照">
            <template v-if="currentSession.trust_environment?.snapshot?.environment">
              v{{ currentSession.trust_environment.version }} · {{ (currentSession.trust_environment.snapshot.devices || []).length }} 设备 · {{ (currentSession.trust_environment.snapshot.protections || []).length }} 保护 · {{ currentSession.trust_environment.snapshot.preflight?.status || '未核验' }}/{{ currentSession.trust_environment.snapshot.preflight?.mode || 'unknown' }}
              <div class="muted">预期邻居 {{ (currentSession.trust_environment.snapshot.expected_neighbors || []).join('、') || '未登记' }} · 核验 {{ currentSession.trust_environment.snapshot.preflight?.checked_at || '无时间' }}</div>
            </template>
            <span v-else>未绑定或旧快照不足</span>
          </el-descriptions-item>
          <el-descriptions-item label="实验内容版本">{{ currentSession.content_version || (currentSession.content_source === 'session_snapshot' ? '未登记内容版本（新建会话）' : '未记录（旧会话）') }}</el-descriptions-item>
          <el-descriptions-item label="历史参考分（未验证）">{{ currentSession.score ?? '无' }}</el-descriptions-item>
          <el-descriptions-item label="技能达标">
            <el-tag type="warning">未验证</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="用时">{{ formatDuration(currentSession.time_spent_seconds) }}</el-descriptions-item>
        </el-descriptions>

        <el-alert
          :type="modeAlertType(currentSession)"
          :closable="false"
          show-icon
          style="margin-top: 12px"
          :title="modeAlertTitle(currentSession)"
        />
        <el-alert
          v-if="currentSession.content_warning"
          type="warning"
          :closable="false"
          show-icon
          style="margin-top: 8px"
          :title="currentSession.content_warning"
        />

        <!-- 仅复盘参考，不作为技能成绩 -->
        <div v-if="currentSession?.score_detail" style="margin-top: 16px">
          <h4>复盘参考明细（不代表技能达标）</h4>
          <el-progress
            :percentage="scoreRate(currentSession.score_detail.operation_score)"
            :format="() => scoreItemLabel(currentSession!.score_detail!.operation_score, scoreWeight('operation'))"
            status="success"
            style="margin-bottom: 8px"
          >
            <span>自报操作规范（参考权重 {{ Math.round(scoreWeight('operation') * 100) }}%）</span>
          </el-progress>
          <el-progress
            :percentage="scoreRate(currentSession.score_detail.fault_score)"
            :format="() => scoreItemLabel(currentSession!.score_detail!.fault_score, scoreWeight('fault'))"
            status="warning"
            style="margin-bottom: 8px"
          >
            <span>教员故障确认（参考权重 {{ Math.round(scoreWeight('fault') * 100) }}%）</span>
          </el-progress>
          <el-progress
            :percentage="scoreRate(currentSession.score_detail.time_score)"
            :format="() => scoreItemLabel(currentSession!.score_detail!.time_score, scoreWeight('time'))"
            status="primary"
          >
            <span>用时效率（参考权重 {{ Math.round(scoreWeight('time') * 100) }}%）</span>
          </el-progress>
        </div>

        <!-- B-10：连续任务视图：笔记/步骤持久化，刷新恢复，已结束只读 -->
        <details class="workspace-panel" :open="workspaceOpen" @toggle="workspaceOpen = ($event.target as HTMLDetailsElement).open">
          <summary>
            连续任务 · 笔记与步骤
            <span class="workspace-meta">revision {{ workspaceRevision }}<template v-if="workspaceReadOnly"> · 只读</template></span>
          </summary>
          <div class="workspace-body">
            <el-alert v-if="workspaceError" type="error" :closable="false" :title="workspaceError">
              <el-button size="small" :loading="workspaceLoading" @click="loadWorkspace(currentSession!.id)">重新读取笔记</el-button>
            </el-alert>
            <el-alert
              v-else-if="workspaceReadOnly && !workspaceLoading"
              type="info"
              :closable="false"
              show-icon
              title="该会话已结束：可以回看笔记与步骤，不能修改。需要继续练习请新开会话。"
            />
            <el-alert
            v-if="workspaceConflict"
            type="warning"
            :closable="false"
            show-icon
            title="保存冲突：本地稿仍在，未自动覆盖"
          >
            <template #default>
              <p class="conflict-copy">服务端已有 revision {{ workspaceConflict.revision }}。请先查看最新内容，合并后再保存；不会自动用新 revision 覆盖他人。</p>
              <pre class="conflict-pre">{{ workspaceConflict.notes || '（服务端笔记为空）' }}</pre>
              <div class="v7b-actions">
                <el-button size="small" @click="loadServerConflict">载入服务端最新（丢弃本地）</el-button>
                <el-button size="small" type="warning" @click="overwriteWithLocal">确认用本地稿覆盖</el-button>
                <el-button size="small" text @click="workspaceConflict = null">继续手动合并</el-button>
              </div>
            </template>
          </el-alert>
          <div class="workspace-grid">
              <div>
                <div class="workspace-label">我的笔记</div>
                <el-input
                  v-model="workspaceNotes"
                  type="textarea"
                  :rows="5"
                  :disabled="workspaceReadOnly"
                  placeholder="记录当前现象、判断和下一步；刷新或重开会话后可恢复。"
                />
              </div>
              <div>
                <div class="workspace-label">步骤状态 <small>（点击切换，保存后持久化）</small></div>
                <div class="workspace-steps">
                  <button
                    v-for="(step, index) in workspaceSteps"
                    :key="`${step.id || index}`"
                    type="button"
                    class="workspace-step"
                    :class="{ done: step.status === 'done' }"
                    :disabled="workspaceReadOnly"
                    @click="toggleWorkspaceStep(index)"
                  >
                    <span class="step-state">{{ step.status === 'done' ? '✓' : '○' }}</span>
                    <span>{{ step.name || step.goal || `步骤 ${index + 1}` }}</span>
                  </button>
                  <div v-if="!workspaceSteps.length" class="workspace-empty">本实验未配置步骤，可在笔记里记录过程。</div>
                </div>
              </div>
            </div>
            <div class="v7b-actions" style="margin-top: 10px">
              <el-button type="primary" :loading="workspaceSaving" :disabled="workspaceReadOnly" @click="saveWorkspace">保存笔记/步骤</el-button>
              <span v-if="workspaceDirty && !workspaceReadOnly" class="workspace-meta">有未保存更改</span>
              <span v-if="workspaceSavedAt" class="workspace-meta">上次保存 {{ workspaceSavedAt }}</span>
            </div>
          </div>
        </details>

        <StepVerificationPanel
          :key="currentSession.id" :session-id="currentSession.id" :active="currentSession.status === 'in_progress'"
          :steps="sessionVerificationSteps" :environment-id="currentSession.trust_environment?.id || null"
          :devices="sessionVerificationDevices"
          :binding-supported="sessionBindingSupported"
        />
        <!-- 操作日志 -->
        <div style="margin-top: 16px">
          <h4>操作日志</h4>
          <!-- 记录操作（进行中会话） -->
          <div v-if="currentSession?.status === 'in_progress'" style="display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap">
            <el-input v-model="logForm.command" placeholder="输入执行的命令，如 display interface brief" style="width: 320px" clearable @keyup.enter="handleLogOperation" />
            <el-input v-model="logForm.target_device" placeholder="目标设备(可选)" style="width: 160px" clearable />
            <el-select v-model="logForm.action" style="width: 130px">
              <el-option label="命令执行" value="command" />
              <el-option label="查看" value="inspect" />
              <el-option label="配置下发" value="config" />
              <el-option label="故障排查" value="troubleshoot" />
            </el-select>
            <el-tooltip content="记录为失败操作">
              <el-switch v-model="logForm.success" active-text="成功" inactive-text="失败" />
            </el-tooltip>
            <el-button type="primary" @click="handleLogOperation" :loading="logSubmitting">记录操作</el-button>
          </div>
          <el-table :data="operationLogs" size="small" max-height="240">
            <template #empty>
              <p class="session-empty">暂无记录。进行中会话可在上方填写命令后点「记录操作」。</p>
            </template>
            <el-table-column label="时间" width="170">
              <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
            </el-table-column>
            <el-table-column prop="action" label="操作" width="110" />
            <el-table-column prop="target_device" label="目标设备" width="140" />
            <el-table-column prop="command" label="命令" min-width="200" show-overflow-tooltip />
            <el-table-column label="上报结果" width="90">
              <template #default="{ row }">
                <el-tag :type="row.success ? 'success' : 'danger'" size="small">
                  {{ row.success ? '成功' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
          <div style="margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap">
            <el-dropdown trigger="click" @command="handleExportRecord">
              <el-button size="small" :loading="exporting">导出记录</el-button>
              <template #dropdown><el-dropdown-menu>
                <el-dropdown-item command="jsonl">操作日志（JSONL）</el-dropdown-item>
                <el-dropdown-item command="session">已保存笔记与复盘（JSON）</el-dropdown-item>
              </el-dropdown-menu></template>
            </el-dropdown>
            <el-button v-if="!sessionReadOnly" size="small" type="primary" @click="handleLoadHint" :loading="hintLoading">获取训练提示</el-button>
            <el-button size="small" :loading="reportReading" @click="handleViewReport">查看复盘</el-button>
            <el-button size="small" type="success" @click="handleLoadReport" :loading="reportLoading">
              {{ reportVersions.length ? '重新生成复盘报告' : '生成复盘报告' }}
            </el-button>
          </div>
          <p class="muted">导出会遮蔽凭据；笔记采用已保存修订，复盘采用当前显示版本。未保存草稿不会导出。</p>
          <el-alert v-if="exportError" :title="exportError" type="error" :closable="false" show-icon />
        </div>

        <!-- 故障注入与处理（进行中会话） -->
        <el-alert v-if="labDeviceLoadError" :title="labDeviceLoadError" type="error" :closable="false" show-icon><el-button @click="loadLabDevices">重试设备列表</el-button></el-alert>
        <div v-if="currentSession?.status === 'in_progress'" style="margin-top: 16px">
          <h4>故障注入</h4>
          <el-alert
            type="warning"
            :closable="false"
            show-icon
            title="只把场景写入本会话记录，不会 SSH、不会改设备。真故障请在 WebSSH 按实验步骤自行操作。"
            style="margin-bottom: 8px"
          />
          <div style="display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap">
            <el-select v-model="faultForm.device_id" placeholder="选择设备" style="width: 200px">
              <el-option
                v-for="d in labDevices"
                :key="d.id"
                :label="`${d.hostname} · ${d.model || 'NE40E'}`"
                :value="d.id"
              />
            </el-select>
            <el-select v-model="faultForm.fault_type" placeholder="故障类型" style="width: 220px">
              <el-option v-for="(label, value) in FAULT_TYPES" :key="value" :label="label" :value="value" />
            </el-select>
            <AdminAction v-slot="{ disabled }">
              <el-button type="danger" :disabled="disabled" @click="handleInjectFault" :loading="faultSubmitting">注入故障</el-button>
            </AdminAction>
          </div>
          <el-table :data="sessionFaults" size="small" max-height="260" v-loading="faultsLoading">
            <template #empty>
              <p class="session-empty">暂无记录。注入只写会话、不下发设备。</p>
            </template>
            <!-- 展开行：把"到底注入了什么、怎么回滚"摊开说清（此前只显示设备 ID+类型，学员不知道要复现什么） -->
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="fault-detail">
                  <div v-if="faultObjects(row).length">
                    <strong>涉及对象</strong>
                    <ul class="hint-list">
                      <li v-for="(obj, idx) in faultObjects(row)" :key="`obj-${idx}`">{{ obj }}</li>
                    </ul>
                  </div>
                  <div v-if="row.injected_commands?.length">
                    <strong>注入命令（效果等价于这些命令已执行）</strong>
                    <pre class="fault-pre">{{ row.injected_commands.join('\n') }}</pre>
                  </div>
                  <div v-if="row.rollback_commands?.length">
                    <strong>回滚命令（把网络恢复到故障前）</strong>
                    <pre class="fault-pre">{{ row.rollback_commands.join('\n') }}</pre>
                  </div>
                  <p class="fault-tip">
                    真机排障请在左侧「WebSSH终端」连到对应设备操作（支持 Ctrl+V 粘贴多行）；注入本身不会改设备。
                  </p>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column label="设备" min-width="110">
              <template #default="{ row }">{{ deviceName(row.device_id) }}</template>
            </el-table-column>
            <el-table-column label="故障类型" min-width="170">
              <template #default="{ row }">{{ FAULT_TYPES[row.fault_type] || row.fault_type }}</template>
            </el-table-column>
            <el-table-column label="注入时间" width="170">
              <template #default="{ row }">{{ formatTime(row.injected_at) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.resolved_correctly === true" type="success" size="small">已解决</el-tag>
                <el-tag v-else-if="row.resolved_correctly === false" type="danger" size="small">解决失败</el-tag>
                <el-tag v-else type="warning" size="small">未处理</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220">
              <template #default="{ row }">
                <template v-if="currentSession?.status === 'in_progress' && row.resolved_correctly == null">
                  <!-- 不用 AdminAction 置灰：灰色按钮不弹 tooltip，学员看不出为什么点不动；
                       后端要求教员确认，这里直接说明 -->
                  <el-button size="small" type="success" @click="handleResolveFault(row, true)">标记已解决</el-button>
                  <el-button size="small" type="danger" @click="handleResolveFault(row, false)">标记未解决</el-button>
                </template>
                <span v-else style="color: var(--el-text-color-secondary)">已处理</span>
              </template>
            </el-table-column>
          </el-table>
          <p class="fault-tip">「标记已解决」需要教员/管理员账号确认；学员排障完成后可先点「标记未解决」记录待复核。</p>
        </div>

        <div ref="hintBlockRef" style="margin-top: 16px">
          <h3 class="training-section-heading">训练辅助</h3>
          <el-alert v-if="trainingHint" :title="trainingHint.summary" type="info" :closable="false" style="margin-bottom: 12px">
            <template #default>
              <div class="hint-body">
                <el-alert
                  v-if="trainingHint.degraded"
                  type="warning"
                  :closable="false"
                  show-icon
                  style="margin-bottom: 8px"
                  title="本次为本地模板（模型未返回可用提示）"
                />
                <p v-if="trainingHint.knowledge_status === 'unavailable'" class="report-source-warning">知识检索暂时不可用，当前提示未获得教材参考；这不表示知识库没有资料。</p>
                <p v-else-if="!trainingHint.sources?.length" class="muted">本次未获得可用的教材参考片段。</p>
                <!-- 风险提示：会中断邻居/改管理口这类操作，必须显示（此前后端给了却从没渲染） -->
                <el-alert
                  v-if="trainingHint.risk_notes?.length"
                  type="error"
                  :closable="false"
                  show-icon
                  style="margin-bottom: 10px"
                >
                  <template #title>风险提示</template>
                  <template #default>
                    <ul class="hint-list">
                      <li v-for="(item, index) in trainingHint.risk_notes" :key="`risk-${index}`">{{ item }}</li>
                    </ul>
                  </template>
                </el-alert>
                <div v-if="trainingHint.next_steps?.length">
                  <strong>建议下一步</strong>
                  <ul class="hint-list">
                    <li v-for="(item, index) in trainingHint.next_steps" :key="`next-${index}`">{{ item }}</li>
                  </ul>
                </div>
                <!-- coach_text 是最具体的一段（含命令代码块），此前被丢弃 -->
                <div v-if="trainingHint.coach_text">
                  <strong>教练说明</strong>
                  <div class="hint-text" @click="copyCoachCode" v-html="renderCoachText(trainingHint.coach_text)"></div>
                </div>
                <div v-if="trainingHint.corrections?.length">
                  <strong>纠错建议</strong>
                  <ul class="hint-list">
                    <li v-for="(item, index) in trainingHint.corrections" :key="`fix-${index}`">{{ item }}</li>
                  </ul>
                </div>
                <div v-if="trainingHint.explanations?.length">
                  <strong>知识解释</strong>
                  <ul class="hint-list">
                    <li v-for="(item, index) in trainingHint.explanations" :key="`exp-${index}`">{{ item }}</li>
                  </ul>
                </div>
                <div v-if="trainingHint.sources?.length" class="hint-sources">
                  <strong>本次检索参考</strong>
                  <ul class="hint-list">
                    <li v-for="(src, index) in trainingHint.sources" :key="`src-${index}`">
                      <details class="report-source">
                        <summary>{{ src.title || src.filename || '知识库片段' }} · 展开片段</summary>
                        <p class="muted">参考材料不等于现场证据。{{ src.truncated ? '仅保留完整段落节选，未提供全文。' : '' }}</p>
                        <pre>{{ src.content || '本来源未附正文。' }}</pre>
                      </details>
                    </li>
                  </ul>
                </div>
              </div>
            </template>
          </el-alert>
          <el-card v-if="reportError" shadow="never" style="margin-bottom: 12px">
            <el-alert type="error" :closable="false" show-icon :title="reportError">
              <template #default>
                <span v-if="trainingReport">当前显示所选成功版本 v{{ trainingReport.version }}。</span>
                <span v-else>当前没有可显示的版本，保存状态请以成功读取的结果为准。</span>
              </template>
            </el-alert>
          </el-card>
          <el-card v-if="trainingReport" shadow="never">
            <template #header>
              <div class="report-heading">
                <span>{{ trainingReport.title }}</span>
                <span class="report-heading-meta">
                  <el-tag type="success">已保存 v{{ trainingReport.version }}</el-tag>
                  <el-select
                    v-if="reportVersions.filter(v => v.status === 'ready').length > 1"
                    :model-value="trainingReport.version" aria-label="已保存复盘版本" style="width: 150px"
                    :disabled="reportReading || reportLoading" @change="handleReportVersionChange"
                  >
                    <el-option v-for="v in reportVersions.filter(v => v.status === 'ready')" :key="v.version" :value="v.version" :label="`已保存 v${v.version}`" />
                  </el-select>
                  <el-tag v-if="trainingReport.input_summary?.degraded" type="warning">本地模板（非模型生成）</el-tag>
                  <span class="muted">{{ formatTime(trainingReport.generated_at) }}</span>
                </span>
              </div>
            </template>
            <el-alert
              v-if="reportVersions.length > 1"
              type="info"
              :closable="false"
              style="margin-bottom: 10px"
              :title="`共 ${reportVersions.filter(v => v.status === 'ready').length} 个成功版本；当前显示 v${trainingReport.version}，重新生成会新增版本。`"
            />
            <div class="report-sections">
              <section v-if="trainingReport.summary">
                <h4>摘要</h4><p>{{ trainingReport.summary }}</p>
              </section>
              <section v-if="trainingReport.key_findings?.length">
                <h4>证据与发现</h4><ul><li v-for="(item, i) in trainingReport.key_findings" :key="`k-${i}`">{{ item }}</li></ul>
              </section>
              <section v-if="trainingReport.root_causes?.length">
                <h4>原因判断</h4><ul><li v-for="(item, i) in trainingReport.root_causes" :key="`r-${i}`">{{ item }}</li></ul>
              </section>
              <section v-if="trainingReport.impact_analysis?.length">
                <h4>影响与待验证</h4><ul><li v-for="(item, i) in trainingReport.impact_analysis" :key="`i-${i}`">{{ item }}</li></ul>
              </section>
              <section v-if="trainingReport.recommendations?.length">
                <h4>建议下一步</h4><ul><li v-for="(item, i) in trainingReport.recommendations" :key="`rec-${i}`">{{ item }}</li></ul>
              </section>
            </div>
            <details class="report-raw">
              <summary>查看完整生成文本（模型原文，可能含未结构化内容）</summary>
              <div style="white-space: pre-wrap; line-height: 1.7">{{ trainingReport.report_text }}</div>
            </details>
            <div v-if="trainingReport.sources?.length" class="hint-sources">
              <strong>生成时的检索参考</strong>
              <p class="muted">检索结果供核对，不代表每条内容都支撑报告结论。</p>
              <ul class="hint-list">
                <li v-for="(src, index) in trainingReport.sources" :key="`report-src-${index}`">
                  <details v-if="src.prompt_sha256 && src.content" class="report-source">
                    <summary>{{ src.title || src.filename || '知识库片段' }} · 查看生成时片段</summary>
                    <p class="muted">这是随报告保存的来源快照，当前教材可能已更新。{{ src.truncated ? '仅保留完整段落节选，未提供全文。' : '' }}</p>
                    <pre>{{ src.content }}</pre>
                  </details>
                  <template v-else>
                    {{ src.title || src.filename || '知识库片段' }}
                    <span class="muted"> · 旧报告未记录可核对的生成片段</span>
                  </template>
                </li>
              </ul>
            </div>
            <p v-else-if="trainingReport.input_summary?.knowledge_status === 'unavailable'" class="report-source-warning">生成时知识检索不可用，报告未获得教材参考；这不表示知识库没有资料。</p>
            <p v-else-if="trainingReport.input_summary?.knowledge_status === 'empty'" class="muted">生成时未检索到可用的参考片段。</p>
            <p v-else-if="trainingReport.input_summary?.knowledge_status === 'not_requested'" class="muted">本次生成未请求知识检索。</p>
            <p v-else class="muted">旧报告未记录知识检索状态，无法判断当时是否完成检索。</p>
          </el-card>
          <el-card v-else-if="!reportError && !reportReading" shadow="never">
            <el-empty description="还没有保存的复盘报告。点「生成复盘报告」会让模型读取本会话证据并保存一个新版本；之后「查看复盘」只读数据库，不再调用模型。" :image-size="64" />
          </el-card>
        </div>
      </div>
      <template #footer>
        <div class="session-footer">
          <div class="session-cta">
            <el-button type="primary" @click="goTopology">看拓扑</el-button>
            <el-button @click="goDevices">去设备</el-button>
            <el-button @click="goWebSSH">开终端</el-button>
          </div>
          <div class="session-end-actions">
            <el-button v-if="currentSession?.status === 'in_progress'" type="warning" @click="handleComplete">结束实训</el-button>
            <el-dropdown trigger="click" @command="handleSessionFooterCommand">
              <el-button>更多</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="close">关闭窗口</el-dropdown-item>
                  <el-dropdown-item v-if="currentSession?.status === 'in_progress'" command="abandon" divided>放弃本次实训</el-dropdown-item>
                  <el-dropdown-item v-if="currentSession?.status === 'in_progress'" command="score">冻结参考并结束</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { notifyRequestError } from '../../utils/requestError'
import { renderMarkdown } from '../../utils/markdownLite'
import { formatApiTime } from '../../utils/datetime'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import StepVerificationPanel from '../../components/training/StepVerificationPanel.vue'
import { getEnvironments, type EnvironmentRecord, type EnvironmentDevice } from '../../api/trust'
import { useCurrentUser } from '../../composables/useCurrentUser'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import {
  listLabs, createLab, deleteLab, startSession, getSession, listSessions, getLab, updateLab,
  scoreSession, startSandbox, getOperationLogs, exportLogsJsonl, exportTrainingSession,
  getTrainingHint, getTrainingReport, generateTrainingReport, getTrainingWorkspace, updateTrainingWorkspace,
  logOperation, completeSession, abandonSession,
  deleteSession, injectFaults, resolveFault, getSessionFaults,
  bindLabEnvironment,
} from '../../api/training'
import { getTopologies, getDevices, type DeviceRecord } from '../../api/device'
import { useLabContextStore } from '../../stores/labContext'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import AdminAction from '../../components/AdminAction.vue'
import PageHeader from '../../components/v7b/PageHeader.vue'
const { isAdmin } = useCurrentUser()

interface ModeFacts {
  teaching_mode: 'guided' | 'free' | 'unknown'
  device_mode: 'sim' | 'ssh' | 'unknown'
  device_label: string
  deploy_mode: 'simulated' | 'real' | 'unknown'
  deploy_label: string
  environment_binding: 'verified' | 'unverified' | 'unknown'
  environment_binding_label: string
  webssh_write_risk: 'none' | 'possible' | 'unknown'
  summary: string
}

interface Lab {
  id: number
  title: string
  description: string
  status: string
  topology_id: number
  objectives: string[] | any[]
  scoring_rules: Record<string, number>
  time_limit_minutes: number
  is_sandbox: boolean
  mode_facts?: ModeFacts
  content_version?: string
  environment_spec?: { prerequisites?: string[]; sources?: string[]; trust_environment_id?: number; supports_binding?: boolean }
  created_at: string
}

interface ScoreDetail {
  verification_status?: 'unverified'
  reference_score?: number
  note?: string
  operation_score: number
  fault_score: number | null
  time_score: number
  weights?: { operation?: number; fault?: number; time?: number }
}

interface Session {
  id: number
  lab_id: number
  status: string
  score: number | null
  score_detail: ScoreDetail | null
  passed: boolean | null
  started_at: string | null
  completed_at: string | null
  time_spent_seconds: number | null
  content_version?: string | null
  content_snapshot?: Record<string, unknown> | null
  mode_facts?: ModeFacts
  mode_source?: string
  content_source?: string
  content_warning?: string
  is_active?: boolean
  trust_environment?: {
    id: number | null
    version: string | null
    snapshot: {
      environment?: Record<string, unknown>
      devices?: Array<Record<string, unknown>>
      protections?: Array<Record<string, unknown>>
      expected_neighbors?: string[]
      expected_routes?: string[]
      preflight?: { status?: string; mode?: string; checked_at?: string }
    }
  }
}

interface OpLog {
  id: number
  timestamp: string
  action: string
  target_device: string
  command: string
  result: string
  success: boolean
}

interface TrainingHint {
  session_id: number
  lab_id: number
  goal: string
  summary: string
  next_steps: string[]
  corrections: string[]
  explanations: string[]
  risk_notes: string[]
  coach_text: string
  sources: Record<string, unknown>[]
  degraded?: boolean
  knowledge_status?: string
}

interface TrainingReport {
  session_id: number
  version: number
  status: string
  title: string
  summary: string
  key_findings: string[]
  root_causes: string[]
  impact_analysis: string[]
  recommendations: string[]
  report_text: string
  sources: Record<string, unknown>[]
  input_hash?: string
  input_summary?: Record<string, unknown>
  generated_at?: string | null
  model?: string
  degraded?: boolean
  knowledge_status?: string
}

interface TrainingReportVersion {
  version: number
  status: string
  generated_at?: string | null
  input_hash?: string | null
}

interface TrainingReportEnvelope {
  session_id: number
  lab_id: number
  status: string
  report: TrainingReport | null
  versions: TrainingReportVersion[]
  last_failure?: { version: number; error?: string; generated_at?: string } | null
  reused?: boolean
}

interface SessionFault {
  id: number
  session_id: number
  device_id: number
  fault_type: string
  fault_config: Record<string, unknown> | null
  injected_at: string | null
  resolved_at: string | null
  resolved_correctly: boolean | null
}

// 故障类型（与后端 FaultType 枚举一致）
const FAULT_TYPES: Record<string, string> = {
  interface_shutdown: '接口shutdown',
  ospf_neighbor_down: 'OSPF邻居中断',
  vlan_mismatch: 'VLAN不匹配',
  acl_block: 'ACL阻断',
  route_blackhole: '路由黑洞',
  mtu_mismatch: 'MTU不匹配',
  dns_fault: 'DNS故障',
}

interface SessionSummary {
  id: number
  lab_id: number
  lab_title: string
  status: string
  score: number | null
  passed: boolean | null
  started_at: string | null
  completed_at: string | null
  time_spent_seconds: number | null
}

const labRequest = useSnapshotRequest('实验列表')
const loading = labRequest.loading
const labLoadError = labRequest.error
const sessionRequest = useSnapshotRequest('实训会话列表')
const sessionsLoading = sessionRequest.loading
const sessionLoadError = sessionRequest.error
const submitting = ref(false)
const searchText = ref('')
const labs = ref<Lab[]>([])
const sessions = ref<SessionSummary[]>([])
const showCreateDialog = ref(false)
const showSessionDialog = ref(false)
const currentSession = ref<Session | null>(null)
const sessionVerificationSteps = computed(() => {
  const steps = currentSession.value?.content_snapshot?.objectives
  return Array.isArray(steps) ? steps.filter((s) => s && typeof s === 'object' && Number.isInteger(s.id)) : []
})
const sessionBindingSupported = computed(() => (currentSession.value?.content_snapshot?.environment_spec as { supports_binding?: boolean } | undefined)?.supports_binding !== false)
const sessionVerificationDevices = computed(() => {
  const spec = currentSession.value?.content_snapshot?.environment_spec as { devices?: Array<{ role?: string }> } | undefined
  const roles = (spec?.devices || []).map((d) => d.role)
  return ((currentSession.value?.trust_environment?.snapshot?.devices || []) as unknown as EnvironmentDevice[]).filter((d) => roles.includes(d.role))
})
const currentLab = ref<Lab | null>(null)
const operationLogs = ref<OpLog[]>([])
const sessionFaults = ref<SessionFault[]>([])
const trainingHint = ref<TrainingHint | null>(null)
const trainingReport = ref<TrainingReport | null>(null)
const router = useRouter()
const route = useRoute()
const labCtx = useLabContextStore()
const copilot = useAiCopilotStore()

// 操作记录与故障注入表单
const logForm = ref({ action: 'command', target_device: '', command: '', success: true })
const logSubmitting = ref(false)
const labDevices = ref<DeviceRecord[]>([])
const labDeviceRequest = useSnapshotRequest('实训设备列表')
const labDeviceLoadError = labDeviceRequest.error
const faultForm = ref({ device_id: 0, fault_type: 'interface_shutdown' })
const faultSubmitting = ref(false)
const faultsLoading = ref(false)

function bindLabContext(lab: Lab, sessionId: number) {
  currentLab.value = lab
  labCtx.startLab({
    sessionId,
    labId: lab.id,
    labTitle: lab.title,
    topologyId: lab.topology_id,
    // 旧实验的 objectives 可能是字符串数组；后端 lab_steps 契约是 list[dict]，先过滤避免自动引导 422。
    labSteps: (Array.isArray(lab.objectives) ? lab.objectives : []).filter(
      (item) => item && typeof item === 'object' && !Array.isArray(item),
    ),
    modeFacts: lab.mode_facts,
  })
}

// 实验步骤大纲弹窗
const showStepsDialog = ref(false)
const stepsLab = ref<Lab | null>(null)
const bindingEnvironments = ref<EnvironmentRecord[]>([])
const bindingEnvironmentId = ref<number | undefined>()
const bindingSaving = ref(false)
let bindingSelection = 0
async function showSteps(lab: Lab) {
  const selected = ++bindingSelection
  bindingSaving.value = false
  stepsLab.value = lab
  bindingEnvironmentId.value = lab.environment_spec?.trust_environment_id
  showStepsDialog.value = true
  if (isAdmin.value) {
    try {
      const environments = await getEnvironments() as unknown as EnvironmentRecord[]
      if (selected === bindingSelection) bindingEnvironments.value = environments
    } catch (error) { if (selected === bindingSelection) notifyRequestError(error, '读取环境失败，请重开步骤重试') }
  }
}
async function saveLabBinding() {
  const lab = stepsLab.value
  if (!lab || bindingSaving.value) return
  const selected = bindingSelection
  const environmentId = bindingEnvironmentId.value
  const stillSelected = () => selected === bindingSelection && stepsLab.value?.id === lab.id
  bindingSaving.value = true
  try {
    await bindLabEnvironment(lab.id, environmentId || null)
    lab.environment_spec = { ...lab.environment_spec, trust_environment_id: environmentId }
    if (stillSelected()) ElMessage.success('已保存，仅用于之后的新会话；已有会话保持原绑定')
  } catch (error) { if (stillSelected()) notifyRequestError(error, '保存绑定失败') }
  finally { if (stillSelected()) bindingSaving.value = false }
}

function goTopology() {
  showSessionDialog.value = false
  const tid = currentLab.value?.topology_id || labCtx.topologyId
  if (tid) router.push({ path: '/topology', query: { topology_id: String(tid) } })
  else router.push('/topology')
}

function goDevices() {
  showSessionDialog.value = false
  router.push('/devices')
}

function goWebSSH() {
  showSessionDialog.value = false
  if (labCtx.device?.id) router.push(`/webssh/${labCtx.device.id}`)
  else router.push('/webssh')
}
const hintLoading = ref(false)
const hintBlockRef = ref<HTMLElement | null>(null)
/** 教练说明可能含 ```cli 代码块与标题：复用 AI 面板的轻量 markdown 渲染（内部先 escapeHtml） */
const renderCoachText = (text: string) => renderMarkdown(text || '')

async function copyCoachCode(event: MouseEvent) {
  const target = event.target instanceof Element ? event.target : null
  const button = target?.closest('.code-copy')
  if (!button || !(event.currentTarget instanceof Element) || !event.currentTarget.contains(button)) return
  event.preventDefault()
  const code = button.closest('.code-block')?.querySelector('pre code')?.textContent
  if (!code) return
  try {
    await navigator.clipboard.writeText(code)
    ElMessage.success('已复制代码')
  } catch {
    ElMessage.error('复制失败，请选中代码后手动复制')
  }
}

/** 故障涉及对象（fault_config 是 key:value 文本，摊平成可读行） */
const faultObjects = (row: any): string[] => {
  const config = row?.fault_config
  if (!config) return []
  if (typeof config === 'object') {
    return Object.entries(config).map(([key, value]) => `${key} = ${value}`)
  }
  return String(config).split(/[;\n]/).map((item: string) => item.trim()).filter(Boolean)
}

/** 设备 id → 主机名（故障表只显示数字 ID，学员不知道是哪台） */
const deviceName = (deviceId: unknown) => {
  const found = labDevices.value.find((item) => Number(item.id) === Number(deviceId))
  return found ? found.hostname : `设备 ${deviceId ?? '-'}`
}
const reportLoading = ref(false)
const reportReading = ref(false)
const exporting = ref(false)
const exportError = ref('')
let exportRequestSeq = 0
const reportError = ref('')
const reportVersions = ref<TrainingReportVersion[]>([])
let sessionSelectionSeq = 0
let reportReadSeq = 0
let reportGenerateSeq = 0
let hintRequestSeq = 0
let workspaceReadSeq = 0
let workspaceSaveSeq = 0

function invalidateSessionRequests() {
  exportRequestSeq++
  exporting.value = false
  exportError.value = ''
  sessionSelectionSeq++
  reportReadSeq++
  reportGenerateSeq++
  hintRequestSeq++
  workspaceReadSeq++
  workspaceSaveSeq++
  reportReading.value = false
  reportLoading.value = false
  hintLoading.value = false
  workspaceSaving.value = false
  workspaceLoading.value = false
}
const workspaceOpen = ref(false)
const workspaceNotes = ref('')
const workspaceSteps = ref<Array<Record<string, any>>>([])
const workspaceRevision = ref(0)
const workspaceReadOnly = ref(false)
const workspaceSaving = ref(false)
const workspaceLoading = ref(false)
const workspaceError = ref('')
const workspaceSavedContent = ref('')
const workspaceDirty = computed(() => workspaceSavedContent.value !== workspaceContent(workspaceNotes.value, workspaceSteps.value))
const workspaceSavedAt = ref('')
const workspaceConflict = ref<{ revision: number; notes: string; steps: Array<Record<string, any>> } | null>(null)


function normalizeWorkspaceSteps(saved: Array<Record<string, any>>) {
  const objectives = (currentLab.value?.objectives || []).filter((item) => item && typeof item === 'object' && !Array.isArray(item)) as Array<Record<string, any>>
  const byId = new Map(saved.map((item) => [String(item.id ?? item.name ?? ''), item]))
  if (!objectives.length) return saved
  return objectives.map((item, index) => {
    const key = String(item.id ?? item.name ?? index)
    const previous = byId.get(key)
    return {
      id: item.id ?? index,
      name: item.name || item.goal || `步骤 ${index + 1}`,
      status: previous?.status === 'done' ? 'done' : 'todo',
    }
  })
}

async function loadWorkspace(sessionId: number) {
  const selection = sessionSelectionSeq
  const request = ++workspaceReadSeq
  const owns = () => selection === sessionSelectionSeq && request === workspaceReadSeq && currentSession.value?.id === sessionId
  workspaceReadOnly.value = true
  workspaceLoading.value = true
  workspaceError.value = ''
  try {
    const res = await getTrainingWorkspace(sessionId) as unknown as {
      notes: string; steps: Array<Record<string, any>>; revision: number; updated_at: string; read_only: boolean
    }
    if (!owns()) return
    workspaceNotes.value = res.notes || ''
    workspaceSteps.value = normalizeWorkspaceSteps(res.steps || [])
    workspaceRevision.value = res.revision || 0
    workspaceReadOnly.value = res.read_only === true
    workspaceSavedAt.value = res.updated_at || ''
    workspaceSavedContent.value = workspaceContent(workspaceNotes.value, workspaceSteps.value)
    return true
  } catch {
    if (!owns()) return
    workspaceError.value = '读取笔记与步骤失败，暂时不能保存；已有内容保留，请重新读取。'
    workspaceReadOnly.value = true
    return false
  } finally {
    if (owns()) workspaceLoading.value = false
  }
}

function toggleWorkspaceStep(index: number) {
  if (workspaceReadOnly.value) return
  const step = workspaceSteps.value[index]
  if (!step) return
  step.status = step.status === 'done' ? 'todo' : 'done'
}

function workspaceContent(notes: string, steps: Array<Record<string, any>>) {
  return JSON.stringify({ notes, steps })
}

async function saveWorkspace() {
  const sessionId = currentSession.value?.id
  if (!sessionId || workspaceReadOnly.value || workspaceSaving.value || workspaceLoading.value) return
  const selection = sessionSelectionSeq
  const request = ++workspaceSaveSeq
  const owns = () => selection === sessionSelectionSeq && request === workspaceSaveSeq && currentSession.value?.id === sessionId
  const content = workspaceContent(workspaceNotes.value, workspaceSteps.value)
  const payload = { ...JSON.parse(content), revision: workspaceRevision.value }
  workspaceSaving.value = true
  try {
    const res = await updateTrainingWorkspace(sessionId, payload) as unknown as { revision: number; updated_at: string }
    if (!owns()) return
    workspaceRevision.value = res.revision
    workspaceSavedAt.value = res.updated_at
    workspaceSavedContent.value = content
    workspaceConflict.value = null
    ElMessage.success('笔记/步骤已保存')
  } catch (error: any) {
    if (!owns()) return
    if (error?.response?.status === 409) {
      try {
        const latest = await getTrainingWorkspace(sessionId) as unknown as {
          notes: string; steps: Array<Record<string, any>>; revision: number
        }
        if (!owns()) return
        workspaceConflict.value = { revision: latest.revision || 0, notes: latest.notes || '', steps: latest.steps || [] }
      } catch {
        if (!owns()) return
        workspaceConflict.value = { revision: -1, notes: '读取最新版本失败，请刷新后重试', steps: [] }
      }
      ElMessage.warning('笔记并发冲突：本地稿已保留，请查看服务端最新内容后合并')
    } else {
      ElMessage.error(error?.response?.data?.detail || '保存失败')
    }
  } finally {
    if (owns()) workspaceSaving.value = false
  }
}

async function loadServerConflict() {
  const sessionId = currentSession.value?.id
  if (!sessionId || workspaceSaving.value) return
  const selection = sessionSelectionSeq
  const loaded = await loadWorkspace(sessionId)
  if (loaded && selection === sessionSelectionSeq && currentSession.value?.id === sessionId) workspaceConflict.value = null
}

async function overwriteWithLocal() {
  const conflict = workspaceConflict.value
  const sessionId = currentSession.value?.id
  const selection = sessionSelectionSeq
  if (!conflict || conflict.revision < 0 || !sessionId || workspaceSaving.value) return
  try {
    await ElMessageBox.confirm('这会用当前本地稿覆盖服务端最新版本，确定继续吗？', '确认覆盖', { type: 'warning' })
  } catch { return }
  if (selection !== sessionSelectionSeq || currentSession.value?.id !== sessionId || workspaceConflict.value !== conflict) return
  workspaceRevision.value = conflict.revision
  workspaceConflict.value = null
  await saveWorkspace()
}


const sessionReadOnly = computed(() => {
  const status = currentSession.value?.status
  return !!status && status !== 'in_progress'
})

// 窄屏打开会话弹窗时收起助手，避免 dock 面板遮住弹窗右侧的主动作；用户可随时再展开。
watch(showSessionDialog, (open) => {
  if (open && window.innerWidth < 1600) copilot.setOpen(false)
  if (!open) invalidateSessionRequests()
})

/** AF-04：设备连接/下发/绑定以服务端 mode_facts 为准，不用固定文案。 */
const UNKNOWN_FACTS: ModeFacts = {
  teaching_mode: 'unknown',
  device_mode: 'unknown',
  device_label: '设备连接方式未知',
  deploy_mode: 'unknown',
  deploy_label: '下发方式未知',
  environment_binding: 'unknown',
  environment_binding_label: '无环境绑定信息',
  webssh_write_risk: 'unknown',
  summary: '设备连接或下发方式未记录，不能推断为模拟或真实。',
}

function factsOf(row: { mode_facts?: ModeFacts } | null | undefined): ModeFacts {
  return row?.mode_facts || UNKNOWN_FACTS
}

function deviceTagLabel(row: { mode_facts?: ModeFacts }) {
  const mode = factsOf(row).device_mode
  return mode === 'sim' ? '模拟设备' : mode === 'ssh' ? '真实设备' : '设备未知'
}

function deviceTagType(facts: ModeFacts) {
  const mode = facts.device_mode
  return (mode === 'sim' ? 'info' : mode === 'ssh' ? 'danger' : 'warning') as 'info' | 'danger' | 'warning'
}

function modeSummary(row: { mode_facts?: ModeFacts }) {
  return factsOf(row).summary
}

function teachingLabel(session: Session | null) {
  const mode = factsOf(session).teaching_mode
  return mode === 'free' ? '自由练习' : mode === 'guided' ? '引导实验' : '教学方式未记录'
}

function deviceTagLabelFor(session: Session | null) {
  const facts = factsOf(session)
  return facts.device_mode === 'sim' ? '模拟设备' : facts.device_mode === 'ssh' ? '真实设备（共享）' : '设备未知'
}

function deviceTagTypeFor(session: Session | null) {
  return deviceTagType(factsOf(session))
}

function deployLabel(session: Session | null) {
  return factsOf(session).deploy_label
}

function bindingLabel(session: Session | null) {
  const snapshot = session?.trust_environment?.snapshot
  if (snapshot?.environment) {
    return `已绑定 ${session?.trust_environment?.version || 'v?'} · ${snapshot.preflight?.status || '未核验'}/${snapshot.preflight?.mode || 'unknown'}`
  }
  return factsOf(session).environment_binding_label
}

function modeAlertType(session: Session | null) {
  const facts = factsOf(session)
  return (facts.device_mode === 'sim' ? 'info' : 'warning') as 'info' | 'warning'
}

function modeAlertTitle(session: Session | null) {
  const facts = factsOf(session)
  const source = session?.mode_source === 'unknown_history' ? '历史会话未记录当时的连接/下发方式。' : ''
  return `${facts.summary}${source}`
}

const createForm = ref({
  title: '',
  description: '',
  topology_id: 0,
  time_limit_minutes: 60,
  is_sandbox: false,
})

// 拓扑下拉（创建 Lab 绑定真实拓扑，替代硬编码 id=1）
const topologies = ref<{ id: number; name: string; status?: string }[]>([])
const topologyRequest = useSnapshotRequest('拓扑列表')
const topologyLoadError = topologyRequest.error
const loadTopologies = async () => {
  await topologyRequest.run(() => getTopologies(), value => {
    topologies.value = value as { id: number; name: string; status?: string }[]
    if (topologies.value.length && !createForm.value.topology_id) {
      createForm.value.topology_id = topologies.value[0].id
    }
  })
}

const loadLabDevices = async () => {
  await labDeviceRequest.run(() => getDevices(), value => {
    labDevices.value = value
    const ids = new Set(labDevices.value.map((d) => d.id))
    if (!ids.has(faultForm.value.device_id) && labDevices.value[0]) {
      faultForm.value.device_id = labDevices.value[0].id
    }
  })
}

const stats = computed(() => {
  const total = labs.value.length
  const ready = labs.value.filter(l => l.status === 'ready').length
  const active = sessions.value.filter(s => s.status === 'in_progress').length
  const completed = sessions.value.filter(s => s.status === 'completed').length
  return { totalLabs: total, readyLabs: ready, activeSessions: active, completedSessions: completed }
})

const sessionDialogTitle = computed(() => {
  if (!currentSession.value) return '实训会话'
  const lab = labs.value.find(l => l.id === currentSession.value?.lab_id)
  const name = lab?.title || currentLab.value?.title || `会话 #${currentSession.value.id}`
  return `实训会话 #${currentSession.value.id} · ${name}`
})

function activeSessionOf(lab: Lab): SessionSummary | undefined {
  return sessions.value.find(s => s.lab_id === lab.id && s.status === 'in_progress')
}

function resumeLab(lab: Lab) {
  const session = activeSessionOf(lab)
  if (session) resumeSession(session.id)
}

const filteredLabs = computed(() => {
  if (!searchText.value) return labs.value
  const q = searchText.value.toLowerCase()
  return labs.value.filter(l => l.title.toLowerCase().includes(q))
})

function statusType(s: string) {
  const map: Record<string, string> = { draft: 'info', ready: 'success', in_progress: 'warning', completed: '' }
  return (map[s] || 'info') as '' | 'success' | 'warning' | 'info' | 'danger'
}

function statusLabel(s: string) {
  const map: Record<string, string> = { draft: '草稿', ready: '就绪', in_progress: '进行中', completed: '已完成' }
  return map[s] || s
}

function sessionStatusType(s: string) {
  const map: Record<string, string> = { pending: 'info', in_progress: 'warning', completed: 'success', abandoned: 'info' }
  return (map[s] || 'info') as '' | 'success' | 'warning' | 'info' | 'danger'
}

function sessionStatusLabel(s: string) {
  const map: Record<string, string> = { pending: '待开始', in_progress: '进行中', completed: '已完成', abandoned: '已放弃' }
  return map[s] || s
}

function formatTime(t?: string | null) {
  return formatApiTime(t)
}

function formatDuration(sec: number | null) {
  if (!sec) return '-'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}分${s}秒`
}

async function loadLabs() {
  await labRequest.run(() => listLabs(), value => { labs.value = value as unknown as Lab[] })
}

async function loadSessions() {
  await sessionRequest.run(() => listSessions(), value => { sessions.value = value as unknown as SessionSummary[] })
}

async function resumeSession(id: number) {
  invalidateSessionRequests()
  const selection = sessionSelectionSeq
  try {
    const session = await getSession(id) as unknown as Session
    if (selection !== sessionSelectionSeq) return
    let lab = labs.value.find(l => l.id === session.lab_id) || null
    if (!lab) {
      try {
        lab = await getLab(session.lab_id) as unknown as Lab
      } catch {
        lab = null
      }
    }
    if (selection !== sessionSelectionSeq) return
    currentLab.value = lab
    // A-04：只有进行中的会话才绑定终端/教练；已结束会话只读回看。
    if (lab && session.status === 'in_progress') {
      bindLabContext(lab, session.id)
    } else if (labCtx.sessionId === session.id) {
      labCtx.clearLab()
    }
    await loadSession(id, selection)
  } catch {
    /* 拦截器已提示 */
  }
}

function onTrainingOpenSession(ev: Event) {
  const id = Number((ev as CustomEvent).detail?.sessionId || 0)
  if (id) resumeSession(id)
}

async function submitCreate() {
  if (!createForm.value.title) {
    ElMessage.warning('请输入Lab名称')
    return
  }
  if (!createForm.value.topology_id) {
    ElMessage.warning('请选择所属拓扑')
    return
  }
  submitting.value = true
  try {
    await createLab(createForm.value)
    ElMessage.success('创建成功')
    showCreateDialog.value = false
    createForm.value = {
      title: '',
      description: '',
      topology_id: topologies.value[0]?.id || 0,
      time_limit_minutes: 60,
      is_sandbox: false,
    }
    await loadLabs()
  } catch (error) {
    notifyRequestError(error, '创建失败')
  } finally {
    submitting.value = false
  }
}

async function ensureLabReady(lab: Lab) {
  if (lab.status !== 'draft') return
  await updateLab(lab.id, { status: 'ready' })
  lab.status = 'ready'
}

async function handleStart(lab: Lab) {
  try {
    const existing = activeSessionOf(lab)
    if (existing) {
      await ElMessageBox.confirm(
        `「${lab.title}」已有进行中的会话 #${existing.id}。新开会话不会结束旧会话，旧会话仍可从列表继续。确定再开一个？`,
        '已有进行中会话',
        { type: 'warning' },
      )
    } else {
      await ElMessageBox.confirm(`确认开始 "${lab.title}" 实训?`, '确认')
    }
    await ensureLabReady(lab)
    const res = await startSession(lab.id) as unknown as { id: number }
    ElMessage.success('实训已开始')
    bindLabContext(lab, res.id)
    await loadSessions()
    await loadSession(res.id)
    await loadLabs()
    // 自动触发 AI 助手引导（监听方为 AiCopilotPanel）
    window.dispatchEvent(new CustomEvent('copilot-send', {
      detail: { prompt: `我刚刚开始实训「${lab.title}」。请根据实验步骤引导我完成：先说明第一步要做什么和注意事项。` },
    }))
  } catch { /* cancelled */ }
}

async function handleSandbox(lab: Lab) {
  try {
    await ensureLabReady(lab)
    const res = await startSandbox(lab.id) as unknown as { id: number }
    ElMessage.success(`自由练习已开始：${lab.mode_facts?.summary || '设备与下发方式以会话详情为准'}`)
    bindLabContext(lab, res.id)
    await loadSessions()
    await loadSession(res.id)
    await loadLabs()
    window.dispatchEvent(new CustomEvent('copilot-send', {
      detail: { prompt: `我刚刚以自由练习方式开始实训「${lab.title}」。请根据实验步骤引导我完成：先说明第一步要做什么和注意事项。` },
    }))
  } catch (error) {
    notifyRequestError(error, '启动自由练习失败')
  }
}

async function handleDelete(lab: Lab) {
  try {
    await ElMessageBox.confirm(`确认删除 "${lab.title}"?`, '危险操作', { type: 'warning' })
    await deleteLab(lab.id)
    ElMessage.success('已删除')
    await loadLabs()
  } catch (error) {
    if (error === 'cancel') return
    notifyRequestError(error, '删除实验失败')
  }
}

async function handleDeleteSession(row: SessionSummary) {
  try {
    const warn = row.status === 'in_progress'
      ? `会话 #${row.id} 仍在进行中，删除会中断实训且记录不可恢复。确定删除？`
      : `确定删除会话 #${row.id}（「${row.lab_title}」）？删除后才能删除该实验。`
    await ElMessageBox.confirm(warn, '删除会话', { type: 'warning' })
    await deleteSession(row.id)
    if (currentSession.value?.id === row.id) {
      showSessionDialog.value = false
      currentSession.value = null
    }
    if (labCtx.sessionId === row.id) {
      labCtx.clearLab()
    }
    ElMessage.success('会话已删除')
    await loadSessions()
    await loadLabs()
  } catch (error) {
    if (error === 'cancel') return
    notifyRequestError(error, '删除会话失败')
  }
}

async function loadSession(id: number, selection?: number) {
  if (selection === undefined) {
    invalidateSessionRequests()
    selection = sessionSelectionSeq
  }
  try {
    const [session, logs, faults] = await Promise.all([getSession(id), getOperationLogs(id), getSessionFaults(id)])
    if (selection !== sessionSelectionSeq) return
    currentSession.value = session as unknown as Session
    operationLogs.value = logs as unknown as OpLog[]
    sessionFaults.value = faults as unknown as SessionFault[]
    trainingHint.value = null
    trainingReport.value = null
    reportVersions.value = []
    reportError.value = ''
    workspaceConflict.value = null
    workspaceNotes.value = ''
    workspaceSteps.value = []
    workspaceRevision.value = 0
    workspaceSavedAt.value = ''
    workspaceSavedContent.value = workspaceContent('', [])
    // 读取已保存的复盘（不调用模型）；失败不影响会话本身
    await Promise.all([readStoredReport(id), loadWorkspace(id)])
    if (selection === sessionSelectionSeq) showSessionDialog.value = true
  } catch (error) {
    if (selection === sessionSelectionSeq) notifyRequestError(error, '加载会话失败')
  }
}

/** 读取已保存复盘：GET 只查库，不触发检索/模型。 */
function handleReportVersionChange(version: number) {
  if (currentSession.value) void readStoredReport(currentSession.value.id, version)
}

async function readStoredReport(sessionId: number, version?: number) {
  if (currentSession.value?.id !== sessionId || reportLoading.value) return
  const selection = sessionSelectionSeq
  const request = ++reportReadSeq
  const owns = () => selection === sessionSelectionSeq && request === reportReadSeq && currentSession.value?.id === sessionId
  reportReading.value = true
  reportError.value = ''
  try {
    const envelope = await getTrainingReport(sessionId, version) as unknown as TrainingReportEnvelope
    if (!owns()) return
    if (envelope.session_id !== sessionId || (envelope.report && envelope.report.session_id !== sessionId)) {
      throw new Error('Report session mismatch')
    }
    if (version !== undefined && envelope.report?.version !== version) throw new Error('Report version mismatch')
    reportVersions.value = envelope.versions || []
    trainingReport.value = envelope.report
    const failureVersion = envelope.last_failure?.version || 0
    const readyVersion = envelope.report?.version || 0
    const latestReadyVersion = Math.max(readyVersion, ...reportVersions.value.filter(v => v.status === 'ready').map(v => v.version))
    if (envelope.last_failure && failureVersion > latestReadyVersion) {
      const stage = (envelope.last_failure as { stage?: string }).stage
      const label = stage === 'provider_init'
        ? '模型服务初始化失败，本次未调用模型'
        : stage === 'generate'
          ? '模型生成失败'
          : stage === 'save'
            ? '结果保存失败'
            : '生成失败'
      reportError.value = envelope.report
        ? `生成尝试 v${failureVersion} 失败（${label}）；当前保留所选成功版本 v${readyVersion}。`
        : `上一次生成失败（v${failureVersion}，${label}）。请稍后重试，旧版本不会被替换。`
    }
  } catch {
    if (!owns()) return
    reportError.value = trainingReport.value
      ? '读取复盘报告失败，当前保留已显示的版本；请稍后点击“查看复盘”重试。'
      : '读取复盘报告失败，暂时无法确认是否已有报告；请稍后点击“查看复盘”重试。'
  } finally {
    if (owns()) reportReading.value = false
  }
}

async function handleLogOperation() {
  if (!currentSession.value) return
  if (!logForm.value.command.trim()) {
    ElMessage.warning('请输入命令内容')
    return
  }
  logSubmitting.value = true
  try {
    await logOperation(currentSession.value.id, {
      lab_id: currentLab.value?.id ?? currentSession.value.lab_id,
      action: logForm.value.action,
      target_device: logForm.value.target_device.trim() || undefined,
      command: logForm.value.command.trim(),
      success: logForm.value.success,
    })
    ElMessage.success('操作已记录')
    operationLogs.value = (await getOperationLogs(currentSession.value.id)) as unknown as OpLog[]
    logForm.value.command = ''
  } catch (error: any) {
    notifyRequestError(error, '记录操作失败')
  } finally {
    logSubmitting.value = false
  }
}

async function loadSessionFaults() {
  if (!currentSession.value) return
  faultsLoading.value = true
  try {
    sessionFaults.value = (await getSessionFaults(currentSession.value.id)) as unknown as SessionFault[]
  } catch {
    sessionFaults.value = []
  } finally {
    faultsLoading.value = false
  }
}

async function handleInjectFault() {
  if (!currentSession.value) return
  if (!faultForm.value.device_id) {
    ElMessage.warning('请选择要记录故障的设备')
    return
  }
  faultSubmitting.value = true
  try {
    await injectFaults(currentSession.value.id, [{ device_id: faultForm.value.device_id, fault_type: faultForm.value.fault_type }])
    ElMessage.success('已记录故障场景（未下发设备）')
    await loadSessionFaults()
  } catch (error: any) {
    notifyRequestError(error, '注入故障失败（需要管理员权限）')
  } finally {
    faultSubmitting.value = false
  }
}

async function handleResolveFault(row: SessionFault, correct: boolean) {
  try {
    await resolveFault(row.id, correct)
    ElMessage.success(correct ? '已标记为解决' : '已标记为未解决')
    await loadSessionFaults()
  } catch (error: any) {
    notifyRequestError(error, '操作失败')
  }
}

function scoreWeight(key: 'operation' | 'fault' | 'time') {
  const weights = currentSession.value?.score_detail?.weights
  const fallback = { operation: 0.6, fault: 0.3, time: 0.1 }
  const value = weights?.[key]
  return typeof value === 'number' ? value : fallback[key]
}

function scoreRate(raw: number | null | undefined) {
  return Math.min(100, Math.max(0, Math.round(Number(raw) || 0)))
}

function scoreItemLabel(raw: number | null | undefined, weight: number) {
  if (raw == null) return '不适用'
  const rate = Number(raw) || 0
  const contrib = Math.round(rate * weight * 10) / 10
  return `${rate}% · 参考折算 ${contrib}`
}

function handleSessionFooterCommand(command: string) {
  if (command === 'close') showSessionDialog.value = false
  else if (command === 'abandon') handleAbandon()
  else if (command === 'score') handleScore()
}

async function handleScore() {
  if (!currentSession.value) return
  try {
    // 评分即结束会话：用时冻结、操作记录与故障注入区关闭，必须提前告知（此前无确认，学员以为只是"看看多少分"）
    await ElMessageBox.confirm(
      '将生成复盘参考明细并结束本次会话，冻结用时、操作记录和故障判定。当前记录无法验证技能达标，不会生成技能成绩或通过判定。确定结束？',
      '生成参考结果并结束',
      { type: 'warning', confirmButtonText: '生成并结束', cancelButtonText: '再练一会儿' },
    )
  } catch {
    return
  }
  try {
    const res = await scoreSession(currentSession.value.id) as unknown as {
      session_id: number
      score: number | null
      passed: boolean | null
      detail: ScoreDetail
    }
    currentSession.value = {
      ...currentSession.value,
      score: res.score,
      passed: res.passed,
      score_detail: res.detail ?? currentSession.value.score_detail,
      status: 'completed',
      completed_at: new Date().toISOString(),
    }
    // 会话已结束：清掉顶部"正在实训·继续"条与 AI 的实训上下文，否则会一直催"继续"
    labCtx.clearLab()
    const detail = res.detail as (ScoreDetail & { note?: string }) | undefined
    ElMessage.info(detail?.note || '参考结果已冻结，技能达标未验证')
    await loadSessions()
  } catch {
    /* 拦截器已提示 */
  }
}

async function handleComplete() {
  if (!currentSession.value) return
  try {
    await ElMessageBox.confirm(
      '结束后将冻结本次会话的操作记录、故障判定与用时；技能达标仍为未验证。确定结束？',
      '结束实训',
      { type: 'warning' },
    )
    await completeSession(currentSession.value.id)
    currentSession.value = { ...currentSession.value, status: 'completed', completed_at: new Date().toISOString() }
    labCtx.clearLab()
    ElMessage.success('实训已结束')
    showSessionDialog.value = false
    await loadSessions()
    await loadLabs()
  } catch {
    /* cancelled or interceptor */
  }
}

/** 放弃会话：保留记录只读回看，不生成参考明细。 */
async function handleAbandon() {
  if (!currentSession.value) return
  try {
    await ElMessageBox.confirm(
      '放弃后本会话只能回看：不能继续记录操作、绑定终端或请求教练。记录与已保存的复盘会保留。确定放弃？',
      '放弃本次实训',
      { type: 'warning', confirmButtonText: '放弃并结束', cancelButtonText: '继续练习' },
    )
    await abandonSession(currentSession.value.id)
    currentSession.value = { ...currentSession.value, status: 'abandoned', completed_at: new Date().toISOString() }
    labCtx.clearLab()
    ElMessage.success('会话已放弃，可随时回看')
    showSessionDialog.value = false
    await loadSessions()
    await loadLabs()
  } catch {
    /* cancelled or interceptor */
  }
}

async function handleExportRecord(kind: string) {
  if (!currentSession.value || exporting.value || !['jsonl', 'session'].includes(kind)) return
  const sessionId = currentSession.value.id
  const version = trainingReport.value?.version
  const selection = sessionSelectionSeq
  const request = ++exportRequestSeq
  const owns = () => selection === sessionSelectionSeq && request === exportRequestSeq && currentSession.value?.id === sessionId
  exporting.value = true
  exportError.value = ''
  try {
    const data = kind === 'jsonl' ? await exportLogsJsonl(sessionId) as unknown as string
      : await exportTrainingSession(sessionId, version) as unknown as { session: { id: number }; report: { version: number } | null }
    if (!owns()) return
    if (typeof data !== 'string' && (data.session.id !== sessionId || (version !== undefined && data.report?.version !== version))) throw new Error('Export identity mismatch')
    const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
    const blob = new Blob([text], { type: kind === 'jsonl' ? 'application/jsonl' : 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = kind === 'jsonl' ? `session_${sessionId}_logs.jsonl` : `session_${sessionId}_report_v${typeof data === 'string' ? 0 : data.report?.version ?? 0}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    if (owns()) {
      exportError.value = '导出失败，已保存记录和页面草稿均保留；请从「导出记录」重试。'
      notifyRequestError(error, '导出失败')
    }
  } finally {
    if (owns()) exporting.value = false
  }
}

async function handleLoadHint() {
  if (!currentSession.value) return
  const sessionId = currentSession.value.id
  const selection = sessionSelectionSeq
  const request = ++hintRequestSeq
  const owns = () => selection === sessionSelectionSeq && request === hintRequestSeq && currentSession.value?.id === sessionId
  hintLoading.value = true
  try {
    const hint = await getTrainingHint(sessionId) as unknown as TrainingHint
    if (!owns()) return
    trainingHint.value = hint
    if (hint.degraded) ElMessage.warning('模型未返回可用提示，已显示本地核对建议。')
    else ElMessage.success('训练提示已生成（在下方「训练辅助」区）')
    // 结果在操作日志下方，学员常以为按钮没反应 —— 生成后滚过去
    await nextTick()
    if (owns()) hintBlockRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (error) {
    if (owns()) notifyRequestError(error, '获取训练提示失败')
  } finally {
    if (owns()) hintLoading.value = false
  }
}

/** 查看已保存复盘：纯读取，不调用模型。 */
async function handleViewReport() {
  if (!currentSession.value) return
  const sessionId = currentSession.value.id
  const selection = sessionSelectionSeq
  const owns = () => selection === sessionSelectionSeq && currentSession.value?.id === sessionId
  await readStoredReport(sessionId)
  if (owns() && (trainingReport.value || reportError.value)) {
    await nextTick()
    if (owns()) hintBlockRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

/** 生成/重生成复盘：只在用户明确点击时调用模型；已有版本时要求确认。 */
async function handleLoadReport() {
  if (!currentSession.value || reportLoading.value) return
  const sessionId = currentSession.value.id
  const selection = sessionSelectionSeq
  const request = ++reportGenerateSeq
  const previousReport = trainingReport.value
  const owns = () => selection === sessionSelectionSeq && request === reportGenerateSeq && currentSession.value?.id === sessionId
  if (previousReport) {
    try {
      await ElMessageBox.confirm(
        `将基于当前证据生成一个新版本（当前 v${previousReport.version} 会保留）。只有证据变化或你想重新解读时才需要重生成。`,
        '重新生成复盘报告',
        { type: 'warning', confirmButtonText: '生成新版本', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  if (!owns()) return
  // A read started before generation cannot replace the newly generated version.
  reportReadSeq++
  reportReading.value = false
  reportLoading.value = true
  reportError.value = ''
  try {
    const envelope = await generateTrainingReport(sessionId, {
      regenerate: !!previousReport,
    }) as unknown as TrainingReportEnvelope
    if (!owns()) return
    if (envelope.session_id !== sessionId || !envelope.report || envelope.report.session_id !== sessionId) {
      throw new Error('Report session mismatch')
    }
    reportVersions.value = envelope.versions || []
    trainingReport.value = envelope.report
    ElMessage.success(envelope.reused ? '证据未变，已复用已保存的报告' : '复盘报告已生成并保存')
    await nextTick()
    if (owns()) hintBlockRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (error: any) {
    if (!owns()) return
    reportError.value = error?.response?.data?.detail || '复盘报告生成失败'
    reportError.value += '；已显示的版本会保留。可点击“查看复盘”核对保存结果。'
    notifyRequestError(error, '生成复盘报告失败')
  } finally {
    if (owns()) reportLoading.value = false
  }
}

watch(
  () => route.query.session_id,
  (value) => {
    const id = Number(Array.isArray(value) ? value[0] : value)
    if (id) resumeSession(id)
  },
)

onMounted(async () => {
  await Promise.all([loadLabs(), loadTopologies(), loadSessions(), loadLabDevices()])
  const qid = Number(Array.isArray(route.query.session_id) ? route.query.session_id[0] : route.query.session_id)
  if (qid) await resumeSession(qid)
  window.addEventListener('training-open-session', onTrainingOpenSession as EventListener)
})

onUnmounted(() => {
  invalidateSessionRequests()
  window.removeEventListener('training-open-session', onTrainingOpenSession as EventListener)
})
</script>

<style scoped>
.training-lab {
  min-height: 100%;
}
/* Keep both lists usable; the page scrolls rather than shrinking a card to its header. */
.training-lab > * { flex-shrink: 0; }
.training-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 140px), 1fr)); gap: 12px; margin: 0 0 16px !important; }
.training-stats > .el-col { max-width: 100%; padding: 0 !important; }
/* 1102px 下操作列不把 Lab 名称挤成竖排：按钮允许换行，名称列保留最小可读宽度 */
.lab-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.lab-actions :deep(.el-button + .el-button) { margin-left: 0; }
/* 会话弹窗内容过长时只滚动正文，底部“结束/放弃/关闭”始终可见 */
:deep(.session-dialog .el-dialog__body) {
  max-height: 62vh;
  overflow-y: auto;
}
.stat-card {
  text-align: center;
  padding: 6px 0;
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #edf5fa;
}
.stat-label {
  font-size: 13px;
  color: #7f93a6;
  margin-top: 4px;
}
h4 {
  margin: 0 0 8px;
  color: var(--el-text-color-primary, #dce8f2);
  font-size: 14px;
}
.session-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  width: 100%;
}
.session-cta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.steps-panel { max-height: 60vh; overflow-y: auto; }
.lab-requirements { padding: 12px; border: 1px solid var(--v7b-line); border-radius: 8px; margin-bottom: 12px; color: var(--v7b-text); line-height: 1.6; }
.binding-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.binding-actions .el-select { flex: 1; min-width: 200px; }
.source-path { overflow-wrap: anywhere; font-size: 12px; }
.step-item {
  border: 1px solid var(--v7b-line);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: var(--v7b-surface-2);
}
.step-head { display: flex; align-items: center; gap: 8px; color: var(--v7b-text); }
.step-no {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #e8f0ff;
  color: #245b9d;
  font-size: 12px;
  font-weight: 700;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.step-goal { margin-top: 6px; font-size: 12px; color: var(--v7b-muted); line-height: 1.5; }
.step-hint { margin-top: 4px; font-size: 12px; color: var(--v7b-text); line-height: 1.5; }
.step-verify { margin-top: 4px; font-size: 11.5px; color: #245b9d; line-height: 1.5; }
.step-verify code {
  background: #eef4fc;
  color: #245b9d;
  border: 1px solid var(--v7b-line);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 11px;
}
/* 训练辅助区：教练说明/风险/引用 */
.hint-body { display: flex; flex-direction: column; gap: 10px; }
.hint-list { margin: 4px 0 0; padding-left: 18px; }
.hint-list li { font-size: 12px; line-height: 1.75; }
.hint-text { margin-top: 4px; font-size: 12px; line-height: 1.75; }
.hint-text :deep(pre), .hint-text :deep(code) { font-family: Consolas, Monaco, monospace; }
.hint-text :deep(pre) {
  padding: 8px 10px;
  overflow: auto;
  border: 1px solid #d7e0ea;
  border-radius: 4px;
  background: #f7f9fc;
  color: #1f2933;
}
.hint-text :deep(.code-block) { margin: 8px 0; border: 1px solid #d7e0ea; border-radius: 8px; overflow: hidden; background: #f7f9fc; }
.hint-text :deep(.code-toolbar) { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 5px 10px; border-bottom: 1px solid #dde5ee; background: #eef2f7; }
.hint-text :deep(.code-lang) { color: #52606d; font-size: 11px; }
.hint-text :deep(.code-copy) { border: 1px solid #cbd5e1; border-radius: 4px; background: #fff; color: #334155; padding: 3px 9px; font: inherit; cursor: pointer; }
.hint-text :deep(.code-copy:hover), .hint-text :deep(.code-copy:focus-visible) { border-color: #2f6fba; color: #2f6fba; outline: 2px solid #b9d6f7; outline-offset: 2px; }
.hint-text :deep(.code-block pre) { margin: 0; border: 0; border-radius: 0; }
.hint-sources .muted { color: var(--v7b-muted); }
.muted { color: var(--v7b-muted); font-size: 12px; }
/* 故障展开行 */
.fault-detail { padding: 4px 8px 8px; font-size: 12px; line-height: 1.7; }
.fault-detail > div { margin-bottom: 8px; }
.fault-pre {
  margin: 4px 0 0;
  padding: 8px 10px;
  overflow: auto;
  border: 1px solid #2a3a4c;
  border-radius: 4px;
  background: #0a1016;
  font-family: Consolas, Monaco, monospace;
  font-size: 11.5px;
  white-space: pre-wrap;
}
.fault-tip { margin: 6px 0 0; color: #52606d; font-size: 12px; line-height: 1.6; }
.session-empty { margin: 12px 0; color: #52606d; line-height: 1.6; }
.report-heading, .report-heading-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.report-heading { justify-content: space-between; overflow-wrap: anywhere; }
.training-section-heading { padding-top: 16px; border-top: 1px solid #dbe3ea; color: #344054; font-size: 14px; }
</style>
<style>
/* 弹窗被 teleport 到 body，scoped 选择器命不中；这里约束正文滚动，底部动作始终可见。 */
.session-dialog .el-dialog__body {
  max-height: 62vh;
  overflow-y: auto;
}

.workspace-panel { margin-top: 14px; border: 1px solid var(--v7b-line); border-radius: 9px; background: rgba(16, 26, 36, .65); }
.workspace-panel > summary { cursor: pointer; padding: 10px 12px; color: var(--v7b-text); font-size: 12px; font-weight: 650; }
.workspace-panel > summary:focus-visible { outline: 2px solid var(--v7b-accent); outline-offset: 2px; }
.workspace-meta { color: var(--v7b-faint); font-size: 10px; font-weight: 400; margin-left: 8px; }
.workspace-body { padding: 0 12px 12px; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 12px; margin-top: 8px; }
.workspace-label { color: var(--v7b-muted); font-size: 11px; margin-bottom: 6px; }
.workspace-label small { color: var(--v7b-faint); }
.workspace-steps { display: flex; flex-direction: column; gap: 4px; max-height: 180px; overflow: auto; }
.workspace-step { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; border: 1px solid var(--v7b-line); background: transparent; color: var(--v7b-text); border-radius: 6px; padding: 7px 9px; cursor: pointer; font-size: 12px; }
.workspace-step.done { border-color: rgba(79, 209, 139, .35); color: var(--v7b-ok); background: rgba(79, 209, 139, .06); }
.workspace-step:disabled { cursor: default; opacity: .8; }
.step-state { width: 14px; text-align: center; }
.workspace-empty { color: var(--v7b-faint); font-size: 11px; }
@media (max-width: 900px) { .workspace-grid { grid-template-columns: 1fr; } }

@media (max-width: 1280px) {
  :deep(.hide-narrow) { display: none !important; }
}

.conflict-copy { margin: 6px 0; font-size: 12px; }
.conflict-pre { max-height: 100px; overflow: auto; white-space: pre-wrap; background: rgba(0,0,0,.18); padding: 6px; border-radius: 4px; font-size: 11px; }

.training-note { color: var(--v7b-muted); font-size: 12px; line-height: 1.6; }
.lab-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; padding: 10px 12px; background: #fff; border: 1px solid var(--v7b-line); border-radius: 10px; }
.lab-toolbar-meta { display: flex; align-items: center; gap: 8px; color: var(--v7b-muted); font-size: 12px; }
@media (max-width: 760px) { .lab-toolbar { align-items: stretch; } }

.report-sections { display: flex; flex-direction: column; gap: 10px; margin-bottom: 10px; }
.report-sections h4 { margin: 0 0 4px; color: #344054; font-size: 12px; }
.report-sections p, .report-sections li { margin: 0; color: #1f2933; font-size: 12px; line-height: 1.65; }
.report-sections ul { margin: 0; padding-left: 18px; }
.report-raw { margin: 8px 0; color: #52606d; font-size: 12px; }
.report-raw pre, .report-raw > div { background: #f8fafc; padding: 8px; border-radius: 6px; }
.report-source summary { cursor: pointer; color: #315d9c; overflow-wrap: anywhere; }
.report-source pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; color: #1f2933; background: #f8fafc; padding: 10px; border: 1px solid #e2e8ef; border-radius: 6px; }
.report-source-warning { color: #7a4b10; background: #fff8e8; padding: 10px; border-radius: 6px; }
</style>
