# full 真实验收证据格式

`scripts/delivery.py` 的 full 门禁使用 schema 2，拒绝旧版“九项 PASS + 任意报告哈希”清单。每份原始脱敏报告必须内嵌，门禁计算 canonical JSON 的 SHA-256 并核对引用；单独提供文件名、格式正确的哈希或手填断言不能通过。

## 运行绑定

真实探针在实际操作前、资源关闭后分别调用 `core.live_evidence.capture_binding(settings)`，写入 `binding.start` 和 `binding.finish`。报告的开始、结束时间位于这两个时间点内，或直接采用两端 `captured_at`。源码、知识库正文、数据库配置指纹、工作区、运行模式发生变化时本轮失败；不得事后给旧报告补签指纹。

源码指纹来自 `delivery.code_fingerprint(delivery.manifest(root))`，包括 `backend`、`scripts`、`sim-frontend`、`knowledge`、`init-sql`、`nginx` 和 `.env.example`。报告不含秘密或原始配置，只保留身份、计数、审计 ID 和脱敏输出哈希。指纹是完整性校验，不是数字签名；仍需可信环境实际运行探针。

主实例普通报告的 `deploy_simulate_only` 必须与合并报告的身份一致；真实部署验收采用经批准的临时 `false` 配置，结束后恢复安全默认配置。只有部署 `prepare` 阶段可在相同数据库、目录与目标下先使用 `true`；`apply/restore` 必须为 `false`。独立接收方报告强制自己的 `true` 配置；隔离迁移和故障注入绑定各自实例，不能借此混入不同主实例的普通报告。

## 合并实际报告

在 Python 中导入 `scripts/delivery.py` 后，调用 `assemble_live_evidence(reports, manifest(root))` 可将已运行的原始报告列表合并。至少需要一份模型/知识库报告和一份三设备报告，以推导统一模型与目标集合。该函数不运行探针、不增加绑定、不修复失败报告；各项状态仍由下层观察值验证生成。将返回 JSON 保存为新文件后执行：

```powershell
backend\.venv\Scripts\python.exe scripts\delivery.py record-live --root '<已准备的交付目录>' --report '<合并报告路径>'
backend\.venv\Scripts\python.exe scripts\delivery.py check --root '<已准备的交付目录>' --mode full
```

报告顶层包含 `schema: 2`、`scope: full_live_acceptance`、`source_fingerprint`、带时区的 `started_at/finished_at`、`identity`、`reports` 和 `checks`。`identity` 包含统一 `database_fingerprint`、`root_fingerprint`、`device_mode: ssh`、`knowledge_provider: anythingllm`，以及 `llm: {provider,base_url,model}`、三个 `targets: [{id,hostname,mgmt_ip,ssh_port}]`。每个附件为 `{sha256, report}`；`checks` 中每项以 `report_sha256` 引用附件，而非声明结果事实。

## 已接入观察值

- `verify_live_ai.py`：真实 DeepSeek 随机挑战响应、流内容和正常终止、AnythingLLM 健康且 135 篇正文、带来源及正文哈希的真实检索片段；静态 fallback 不可通过。
- `verify_live_readonly.py`：精确三端点的 SSH 适配器、VRP 版本、配置身份与完整性、接口和 LLDP 解析、连接关闭。LLDP 未启用仍失败，不能用 `core_readonly_ok` 冒充全部通过。
- `verify_full_stack.py`：认证及运行绑定、实际生成/审查/问答/工具/实训全部步骤，加本轮匹配模型的 AI 日志、真实工具审计和会话 ID；客户端过程记录只能得到未验证评分。
- `verify_live_workflows.py`：三台真实 WebSSH 连接各自得到 VRP 版本并关闭；采集与巡检分别是本轮独立任务，三设备全部成功、无跳过，指标数、任务时间和设备集合匹配。它证明 WebSSH 服务协议及监控路径，浏览器交互由下一项另验。
- `verify_live_browser` schema 2：九项核心页面/操作均为 `mode: live`，浏览器无错误，文字 Copilot 和图片识别均有非 fallback 流式完成和匹配模型的本轮 AI 日志；图片挑战只存在上传图片中。只读页面冒烟或浏览器注入的成功响应不替代真实 Copilot；注入失败场景也不能当外部服务断网实测。
- `verify_live_migration.py`：原库只读、独立空目标库及仅有目标库权限的恢复账号；加密备份和 SQL 哈希、全部旧列逐表内容哈希与行数、严格授权的数据校正、升级版本和重复执行一致。源库内容必须保持不变。
- `verify_live_deploy.py`：同一操作单的 `prepare/apply/restore` 三份原始报告，精确三设备、白名单与基线、真实任务和审计、释放锁、运行/保存配置回读，以及恢复后语义状态与原状态一致。原始文本哈希继续保留，不以易变时间戳替代语义判断。
- 异常与并发组同时需要 `verify_live_resilience.py`、`verify_live_dependency_faults.py`、接收方首跑和浏览器权限报告：真实 30 个并发读取客户端（共用一个管理员身份）、真实终端互斥与释放恢复、匿名和受限账号权限、独立首跑重启，以及仅访问自有回环端口的依赖失败注入。故障注入必须证明没有 fallback 假成功、知识回答与来源为空、连接关闭且锁可再次取得；它不声称已中断真实外部服务。
- `verify_recipient_first_run.py`：相同构建的独立目录与全新 MySQL，实际 bootstrap、清单导入三设备和七个现有实验、准备 135 篇语料、两次启动和认证、静态前端与数据库持久化、真实 DeepSeek/AnythingLLM 及三设备核心 SSH/运行保存一致性子报告。三设备身份必须在清单、数据库与报告间一致。仅此首次凭据检查允许 LLDP 尚未启用，不能抵替完整三设备或链路验收。

新增 producer 必须先定义并测试具体报告 schema，再接入 `validate_live_evidence` 的对应校验；当前缺少完整报告的项显示 `SKIP`，不会永远依赖固定布尔开关。WebSSH/采集、真实浏览器、受控部署/回读/恢复、异常与并发、接收方首跑要分别提供所覆盖的观察值，不能互相替代。

隔离迁移与接收方独立目录的数据库、根目录本来就应不同；这类报告需明确自己的源/目标指纹、运行前后证据、相同构建，并使用各自 schema 校验，不能冒充当前业务实例的普通报告。历史迁移证据可以保留作审计记录，不追认为本轮冻结源码上的实测。最终 full 完成仍要求全部九组检查通过。

## 接收方首跑 producer

先按 [首次初始化说明](full设备与知识库首次初始化.md) 在独立交付目录完成自己的配置，并为本次验收建立完全空的专用 MySQL 库。该 producer 自行执行 bootstrap 和设备导入，因此此库不能事先运行初始化。AnythingLLM 工作区需已完成 135 篇正文导入和嵌入；`prepare-corpus` 只准备文件，不代表已上传。

参考身份 JSON 只包含主验收的 `source_fingerprint/root_fingerprint/database_fingerprint`，不含凭据。设备清单使用实际接收方目标；新目录不得读取或复制参考目录的 `.env`。在新目录运行：

```powershell
backend\.venv\Scripts\python.exe backend\scripts\verify_recipient_first_run.py --reference-identity '<脱敏参考身份JSON>' --manifest '<三设备清单JSON>' --expect-database '<本轮空MySQL库名>' --backend-port <空闲端口> --exclusive-window --recipient-configured --output .runtime\recipient-acceptance
```

输出目录必须尚不存在。此命令会调用收费模型、知识库与设备只读命令，需要已配置且允许使用的测试凭据和独占设备窗口；不会写设备配置。启动收据记录本轮 PID、创建时间和启动 ID，正常结束或失败都按进程身份清理，不猜测端口归属。任一步失败或源码变化都会返回非零并保留失败报告；不要补签为成功。
