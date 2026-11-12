# full 模式首次配置与启动

本入口用于接收方自己的 MySQL、真实 SSH 设备、DeepSeek 与 AnythingLLM。它不安装开发机的 `.runtime` 服务，不用 SQLite 代替 MySQL，也不把服务启动等同于三台设备全流程验收。

## 前置条件

- Windows PowerShell 5.1、Python 3.12（锁定依赖所用版本）、可安装 `backend/requirements.lock` 的网络或已配置的软件源。
- 可认证的 MySQL 服务、已创建的目标数据库和应用用户。目标可以是新空库，也可以是已核验的独立恢复副本。
- 接收方自己的 DeepSeek 接口、模型名和密钥；AnythingLLM 服务、工作区 slug 和 API Key。AnythingLLM 的嵌入服务由接收方自己的部署管理。
- 接收方自己的 SSH 凭据及设备可达网络。启动预检检查 SSH 模式与凭据完整性，不主动执行设备命令。
- 完整的 `sim-frontend/dist`。正常启动由后端托管页面，无需安装 Node；只有显式重建前端才需要 Node。

## 第一次配置

在交付根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap-local.ps1 -Mode full -NoStart
```

脚本先安装锁定的 Python 依赖。缺少根 `.env` 时会启动配置向导，地址和端口可填写外部或本机已安装服务；口令和 API Key 使用隐藏输入。新文件使用 `CreateNew`，先限制为当前 Windows 用户访问，再写入内容，不向控制台回显秘密。不要把此文件放进交付包。

向导会单独询问 `LLM_VISION_MODEL`，不推测文字模型是否支持图片。留空会关闭图片选择和粘贴，文本附件仍可用。本次完整交付验收要求填写同一兼容接口和密钥实际可调用的视觉模型，并在浏览器上传本机新生成的随机 PNG 挑战：挑战字符不放入提问，要求图片识别准确、SSE 正常结束且 AI 日志记录实际视觉模型。只填模型名或文字生成通过，不能代替这项验证。

已存在 `.env` 时，不会覆盖配置或密钥。有效配置优先级与工作台一致：进程环境变量高于 `backend/.env`，后者高于根 `.env`。不接受 dotenv `${...}` 插值，使用明确字面值。原来使用 minimal 的环境须由拥有者明确配置 `DB_BACKEND=mysql`、`DEVICE_MODE=ssh`、`KNOWLEDGE_PROVIDER=anythingllm`，并检查进程环境中是否仍有 minimal 覆盖；full 不会偷偷切换或覆盖这些值。

预检先认证 MySQL，确认结构状态，再使用数据库里实际生效的模型配置执行一个短的 DeepSeek 生成请求，并认证 AnythingLLM 指定工作区。模型探测会产生少量正常 API 用量。异常只报告配置键和错误类型，不输出响应正文、连接串或凭据。可单独执行：

```powershell
backend\.venv\Scripts\python.exe backend\scripts\full_preflight.py --phase prepare
```

任何预检失败都不会运行初始化或迁移。空库在显式 bootstrap 阶段初始化；未知结构直接拒绝。已有旧 MySQL 还必须提供已导出、核验的备份：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap-local.ps1 -Mode full -BackupFile '<已核验的备份路径>' -NoStart
```

备份文件存在且非空只是脚本门槛，不能替代恢复演练。启动入口不修改旧数据库结构。

新库完成管理员初始化后，还须按 [full 设备与知识库首次初始化](full设备与知识库首次初始化.md) 导入接收方自己的三台设备清单及七个实训实验，再运行 `start-full.ps1`。AnythingLLM 也须先完成离线语料包准备、135 篇语料上传与实际嵌入，不能把只有管理员的空库或只有工作区的知识库称为首次配置完成。该指南包含 `prepare-corpus`、`import-devices` 和绑定目标数据库的操作顺序。

## 独立副本联调

原库只进行授权的逻辑备份，不对原库执行 bootstrap、Alembic、清理或演示播种。创建新的 MySQL 实例，独立数据目录、端口、数据库和用户；先核对源与目标的实例标识、端口和数据目录不同，再恢复。不要将正在运行的原数据目录直接复制给新实例。

备份应核实引擎、客户端版本和权限。InnoDB 可使用一致性事务备份；非事务表需要额外保证备份期间不变化。现有 `backup-local.ps1` 使用逐表导出并含七日自动删除，不是本流程的无副作用克隆入口。MySQL 的一致性约束见 [官方 mysqldump 说明](https://dev.mysql.com/doc/refman/8.4/en/mysqldump.html)。

恢复后先检查表、行数、外键及版本，再对副本执行显式备份升级。副本应用使用独立配置和日志目录，关闭定时采集，待目标设备集合核对后才进行真实设备验收。原库加密的设备凭据需要其对应的 `FERNET_KEY`；不能用新向导随机生成的密钥去解密旧库。通过安全渠道仅向副本进程注入所需秘密，不写入报告或通用交付包。

## 启动与结果

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-full.ps1 -BackendPort 8000
```

可以将整个交付目录移到含空格的其它路径，也可用 `-Root '<交付根目录>'`。`-BackendPort` 可改端口；`-BindHost` 默认 `127.0.0.1`。外部服务地址来自有效配置，启动器只管理本次创建的后端进程。

已有端口监听会明确拒绝，不会把另一实例当作启动成功。成功条件是本次后端进程存活、MySQL/LLM/知识库 HTTP 健康通过且返回当前包的前端页面，随后使用管理员认证核对本次随机启动标识、PID（兼容 Windows 虚拟环境的父子解释器）、工作区指纹、数据库配置指纹和运行模式；失败只清理创建时间和父子关系均匹配的本次进程树。后台关闭继承的控制台管道，因此自动化捕获启动输出也能正常结束。MinIO 为可选配置，未配置时不阻断这三项核心依赖。日志在当前目录 `.runtime/logs/full-*.out` / `.err`。

首次向导保持 `DEPLOY_SIMULATE_ONLY=true`、`MONITOR_SCHEDULER_ENABLED=false`。这允许完成依赖配置和启动，不表示真实写设备已验收。后续完整验收还须明确三台设备集合、真实 WebSSH、本轮采集、DeepSeek/AnythingLLM 业务调用，以及已授权的配置确认、回读与恢复证据。不得把启动成功或 minimal 测试结果登记为 full 完成。

## AI 与实训业务验收

服务就绪后，在同一套有效配置下运行以下命令。三个管理端点必须已经入库且各自唯一；填写接收方自己的端点，不能直接使用占位示例。

```powershell
backend\.venv\Scripts\python.exe backend\scripts\verify_full_stack.py --api-url http://127.0.0.1:8000 --expected-endpoints '<设备一地址>:<SSH端口>,<设备二地址>:<SSH端口>,<设备三地址>:<SSH端口>'
```

也支持 `WORKBENCH_API_URL` 和 `WORKBENCH_EXPECTED_ENDPOINTS` 进程环境变量。管理员密码缺失、登录失败、数据库读取失败、HTTP 实例身份或设备映射不一致时，脚本返回非零，且不创建业务会话。身份匹配后会调用真实 AI、知识库和实训 API，并通过 Copilot 在第一台目标设备执行只读 `display version`；不会直接使用 SSH 库或执行配置。

报告写入 `.runtime/logs/verify-full-ai-*.json`，可用 `--report` 指定路径。它保留本轮 AI 日志 ID、工具审计 ID 和实训会话 ID，不删除业务证据，不把未验证过程记录伪造成技能通过。报告不含口令、令牌、模型回复正文或设备原始回显；源码在运行期间变化会判失败。此报告只覆盖 AI 与实训业务，完整交付仍需设备、监控、浏览器、真实下发与恢复等独立证据。
