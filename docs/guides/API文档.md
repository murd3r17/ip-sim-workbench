# IP仿真运维管理工作台 - API文档

## 基础信息

- **Base URL**: `http://localhost:8000/api/v1`
- **认证方式**: Bearer Token (JWT)
- **Content-Type**: `application/json`

## 健康检查

### GET /health

聚合健康状态。仅 MySQL 失败会把 `status` 打成 `unhealthy`（HTTP 503）；MinIO、AnythingLLM、LLM 失败只把整体打成 `degraded`（HTTP 200）。Ollama 只服务知识库嵌入，失败时 `components.ollama.optional=true`，**不**拖死整体。侧探测带 60s TTL 缓存。

`components.llm.config_source` 为 `system_config`（读了 DB `llm.*`）或 `env`（回退 `.env`）。业务路径（对话/教练/Copilot）同样走 `SystemService.build_llm_provider(db)`。

**注意**：对话 LLM 是 DeepSeek（`openai_compatible`），不依赖 11434。

**响应**:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 3600.5,
  "components": {
    "mysql": { "status": "healthy", "latency_ms": 4.2 },
    "llm": { "status": "healthy", "provider": "openai_compatible", "model": "deepseek-v4-flash-vision-exp", "config_source": "system_config" },
    "minio": { "status": "healthy", "latency_ms": 8.1 },
    "ollama": { "status": "healthy", "latency_ms": 12.0 },
    "knowledge": { "status": "healthy", "provider": "anythingllm", "document_count": 135, "workspace_slug": "ip-ops-kb" }
  },
  "timestamp": "2026-08-25T04:00:00Z"
}
```

## 认证接口

### POST /auth/login

用户登录获取Token。

**请求体**:
```json
{
  "username": "admin",
  "password": "<REDACTED>"
}
```

**响应**:
```json
{
  "access_token": "<REDACTED>",
  "token_type": "bearer",
  "user": { "id": 1, "username": "admin", "role": "admin" }
}
```

> 速率限制：登录 30 次/分钟/IP（`core/rate_limiter.py`，按 IP + 路由模板分桶）。
> 说明：原为 10 次/分钟，对实训教室（同一 NAT 出口下几十名学生各登录一次）过紧会互相 429；30 次仍足以挡暴力破解。

### POST /auth/users

创建新用户（需管理员权限）。

### GET /auth/me

获取当前用户信息。

### PUT /auth/password

修改密码。

## 设备管理

### GET /devices

获取设备列表。

### POST /devices

创建设备。

### GET /devices/{id}

获取设备详情。

### PUT /devices/{id}

更新设备信息（需管理员权限；不含改所属拓扑）。

### DELETE /devices/{id}

删除设备（需管理员权限）。

## 拓扑管理

### POST /topologies/{id}/discover

运行态校验（对照当前 eNSP/SSH 链路，**不改基线**）。不是触发自动发现并写入拓扑。

### GET /topology

获取拓扑数据。

## WebSSH

### WS /ws/ssh/{device_id}

WebSocket SSH连接。

## AI助手

### POST /ai/generate-cli

自然语言生成CLI命令。

### POST /ai/review-config

配置审查。下发页「AI 审查配置」调用此接口；不自动下发。后端接口保留。

### POST /ai/ask

知识库问答。

### GET /ai/knowledge/health

知识库健康检查。

> `GET /ai/stream/{request_id}` 已**删除**（P2-05）：该路径从未接任务队列，长期只返回 501，
> 属于"假接口"。流式对话请用 `POST /ai/copilot/chat/stream`。

### POST /ai/generate-and-validate

生成并校验配置。下发页「AI 生成并校验」调用此接口；结果只填入文本框，不自动下发。后端接口保留。

### GET /ai/logs

查询AI交互日志。

### POST /ai/logs/{id}/feedback

设置日志反馈。

### POST /ai/copilot/chat

右侧常驻助手（非流式）。请求体：
```json
{
  "message": "问题",
  "history": [{"role": "user", "content": "..."}],
  "context": {"route": "/topology", "page_name": "拓扑可视化", "selection": "", "notes": "当前实训=..."},
  "want_draft": false,
  "device_model": "NE40E",
  "top_k": 6,
  "page_data": "",
  "attachments": [{"contentString": "data:image/png;base64,...", "mime": "image/png"}],
  "lab_steps": [{"id": 1, "name": "...", "goal": "...", "config_hint": "...", "verify_command": "...", "verify_contains": ["..."]}]
}
```
返回：`{answer, sources, draft_commands, draft_explanation, assist_only, status, images_used, files_used}`。

### POST /ai/copilot/chat/stream

右侧助手 SSE 流式（逐 token）。事件类型：`meta`（来源/状态）、`reasoning`（思考）、`token`（正文）、`tool`（工具调用 running/done）、`draft`（配置草稿）、`done`、`error`。
请求体同 `/ai/copilot/chat`；`lab_steps` 传实训实验步骤时 AI 按教练角色引导（优先工具验证）。

### GET /ai/copilot/sessions

获取当前用户的 Copilot 会话列表（仅元信息：id/title/updated_at/message_count）。

### GET /ai/copilot/sessions/{conv_id}

获取单个 Copilot 会话完整内容（含 messages）。

### PUT /ai/copilot/sessions/{conv_id}

保存/更新 Copilot 会话（全量覆盖）。请求体：`{"title": "...", "messages": [...]}`。

### DELETE /ai/copilot/sessions/{conv_id}

删除 Copilot 会话。

### POST /ai/report

AI报告助手。

### POST /ai/coach

AI实训教练。

## 知识库

### POST /ai/knowledge/upload

适配器上传接口仍在，但**知识库页没有上传 UI**。静态 135 篇教材语料走 `scripts/sync-corpus.ps1`；实时文件走右侧助手。不要把本接口当成常规入库入口。

### GET /ai/knowledge/documents

列出知识库文档。

### DELETE /ai/knowledge/documents/{doc_id}

删除知识库文档。

### POST /ai/knowledge/search

语义检索知识库。返回命中片段列表（`id/filename/title/text/score`，AnythingLLM 另含 `page`）。
前端「检索测试」页点击任一命中卡片会打开**引用详情抽屉**（B6），展示标题、来源文件、相关度、页码与片段全文。

## 报告助手扩展（B5）

### POST /ai/inspection-summary

对一次巡检/采集任务的结果做 AI 归因总结。

- 入参：`{job_id}`（监控任务 ID）
- 权限：登录用户；限流与其它 AI 端点一致
- 行为：读取该任务的 `report_json/summary_json` 作为唯一输入（不重新采集），交给报告助手生成结构化结果；LLM 不可用时走静态降级文案，**不返回 5xx**
- 返回：`{job_id, title, summary, key_findings[], root_causes[], impact_analysis[], recommendations[], report_text}`
- 错误：404 任务不存在；409 任务仍在执行

### POST /ai/diff-explanation

用白话解释两个配置版本之间的差异。

- 入参：`{version_id_a, version_id_b}`
- 安全：只把**脱敏后的差异行**（`redact_sensitive`）送进模型，不回放整份配置
- 返回：`{version_id_a, version_id_b, diff, title, summary, key_findings[], recommendations[], report_text}`；两版本一致时直接返回"没有差异"且不调用模型
- 错误：400 两个版本相同；404 版本不存在

## 配置下发

### POST /deploy

创建配置下发任务。

### POST /deploy/transaction

事务性配置下发（批量+自动回滚）。

### POST /deploy/transaction/stream

SSE推送下发进度。

### GET /deploy/tasks

获取下发任务列表。

### GET /deploy/tasks/{id}

获取任务详情。

### POST /deploy/tasks/{id}/verify

验证下发结果。

### POST /deploy/tasks/verify-batch

批量验证。

### POST /deploy/validate

校验VRP配置语法。

## 配置模板

### POST /config-templates

创建配置模板。

### GET /config-templates

获取模板列表。

### POST /config-templates/render

渲染模板。

### POST /config-templates/validate

校验模板语法。

## 配置版本

### GET /config-versions

获取配置版本列表。

### GET /config-versions/compare?version1=1&version2=2

对比两个配置版本。

### POST /config-versions/{id}/rollback

**已禁用（恒 409）**：该入口会绕过写锁与授权校验，故只在受控流程里回滚。请改用下面的受控回滚任务接口。

### POST /deploy/config-versions/{id}/rollback-task

由历史配置快照生成**受控回滚任务**（B2）。

- 权限：配置版本创建者或 admin（越权返回 403）
- 行为：创建一条 `change_level=high_risk`、`status=awaiting_confirmation` 的下发任务，`config_content` 取该快照；**不直接执行**，需人工确认（高风险二次确认）后走 写锁 → 执行 → 回读验证 链路
- 内容校验：快照中若含 `reset saved-configuration`/`reboot` 等破坏性命令直接 400
- 审计：`deploy_rollback_task_created`（含来源版本 id/版本号）
- 返回：`{task_id, device_id, hostname, status, source_version_id, source_version_number}`
- 错误：400 版本不存在/无快照/含破坏性命令；403 无权限

## 变更审批（前端页面 /approvals）

审批页复用下列既有接口，无需新端点：

- `GET /deploy/tasks`：返回列表，新增字段 `has_lock`（该任务当前是否持有设备写锁），便于审批时判断"确认后能否直接执行"
- `GET /deploy/tasks/{id}`：详情（含 `config_content`，按归属校验）
- `POST /deploy/tasks/{id}/confirm`：确认（高风险首个确认返回 422，带 `risk_confirm=true` 重试）
- `POST /deploy/tasks/{id}/cancel`：取消并释放写锁

## 监控

### GET /monitor/metrics

获取监控指标数据。

### POST /monitor/collect

触发指标采集。

### GET /monitor/stats

获取监控统计。

### GET /monitor/stream

SSE实时监控流。

## 告警

### GET /alarms

获取告警列表。

### POST /alarms/{id}/acknowledge

确认告警。

### POST /alarms/{id}/close

关闭告警。

## 实训

### GET /training/labs

获取实训实验室列表。

### POST /training/labs

创建实训实验室。

### GET /training/labs/{id}

获取实验室详情。

### PUT /training/labs/{id}

更新实验室。

### DELETE /training/labs/{id}

删除实验室。

### POST /training/sessions

启动实训会话。

### GET /training/sessions/{id}

获取会话详情。

### DELETE /training/sessions/{id}

删除实训会话（本人或管理员；连同故障注入与操作日志）。有会话时不能删实验。

### POST /training/sessions/{id}/complete

完成实训会话。

### GET /training/sessions/{id}/hint

生成训练提示。

### GET /training/sessions/{id}/report

生成训练复盘报告。

### POST /training/sessions/{id}/inject

只把故障场景写入 `fault_injection` 表，**不 SSH、不改设备**。响应含 `applied: false`。

### POST /training/faults/{id}/resolve

只把该条记录标为已解决，不下发回滚命令。

### POST /training/sessions/{id}/score

评分。

### POST /training/sandbox/start

启动沙箱模式。

### POST /training/sessions/{id}/log

记录操作日志。

### GET /training/sessions/{id}/logs

获取操作日志。

### GET /training/sessions/{id}/logs/jsonl

导出JSONL日志。

## 系统管理

### GET /system/info

获取系统信息（版本、状态、统计）。

**响应**:
```json
{
  "app_name": "IP仿真运维管理工作站",
  "app_version": "1.0.0",
  "python_version": "3.12.3",
  "database_status": "healthy",
  "llm_status": "healthy",
  "llm_provider": "openai_compatible",
  "llm_model": "deepseek-v4-flash-vision-exp",
  "device_count": 10,
  "user_count": 2,
  "uptime_seconds": 3600.5,
  "log_level": "INFO",
  "fernet_configured": true,
  "jwt_configured": true
}
```

### GET /system/config

获取系统配置列表。

### GET /system/config/{key}

获取单个配置项。

### POST /system/config

创建配置项（需管理员）。

**请求体**:
```json
{
  "config_key": "app.maintenance_mode",
  "config_value": "false",
  "description": "维护模式开关"
}
```

### PUT /system/config/{key}

更新配置项（需管理员）。

### DELETE /system/config/{key}

删除配置项（需管理员）。

### GET /system/audit-logs

查询审计日志。

创建、更新、删除系统配置都会写入审计日志。

**查询参数**:
- `page` (int): 页码，默认1
- `page_size` (int): 每页条数，默认20，最大100
- `module` (string): 模块筛选（auth/device/deploy/monitor/ai/training）
- `user_id` (int): 用户ID筛选

**响应**:
```json
{
  "items": [
    {
      "id": 1,
      "user_id": 1,
      "username": "admin",
      "module": "deploy",
      "action": "create_deploy",
      "resource_type": "deploy_task",
      "resource_id": "42",
      "detail": "...",
      "ip_address": "192.168.1.100",
      "result": "success",
      "created_at": "2026-06-15T10:00:00Z"
    }
  ],
  "total": 100,
  "page": 1,
  "page_size": 20
}
```

### GET /system/logs

获取日志文件列表（需管理员）。

### GET /system/logs/{filename}

读取日志文件内容（需管理员）。

**查询参数**:
- `tail` (int): 返回最后N行，默认200，最大5000

### GET /system/tasks

获取后台任务列表。

### GET /system/tasks/{id}

获取任务详情。

### POST /system/health

健康检查（需认证）。

## 通用说明

### 错误响应格式

```json
{
  "detail": "错误描述"
}
```

### HTTP状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 409 | 资源冲突 |
| 422 | 数据验证失败 |
| 429 | 请求过于频繁 |
| 500 | 服务器内部错误 |

### 分页参数

支持分页的接口使用以下参数：
- `page`: 页码（从1开始）
- `page_size`: 每页条数（默认20）

### WebSocket 关闭码（WebSSH）

前端用子协议传 token（`new WebSocket(url, [token])`）。服务端拒绝时会**先完成握手再关闭**并回显子协议，
否则浏览器只能看到 1006（无原因）。前端据此把原因显示在终端且不再自动重连：

| 关闭码 | 含义 |
|---|---|
| 4001 | 缺少认证 token / 认证失败 |
| 4004 | 设备不存在 |
| 4005 | 数据库未初始化 |
| 4006 | 并发终端会话数已达上限（每用户上限见 `WEBSSH_MAX_SESSIONS_PER_USER`，默认 5） |
| 4009 | 设备存在待执行配置写任务（写锁未释放） |
