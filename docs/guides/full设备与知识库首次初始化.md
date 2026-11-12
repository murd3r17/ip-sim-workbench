# full 设备与知识库首次初始化

适用于接收方自己创建的空 MySQL 业务库。已有用户业务库或恢复副本使用现有设备、拓扑和实验，不运行设备初始化。以下命令均在交付根目录执行，不依赖开发机路径、原设备 ID 或相邻源教材仓库。

## 依赖与首次配置

使用 Python 3.12；首次安装需要能够下载 `backend/requirements.lock` 内的锁定依赖，或使用已安装这些依赖的虚拟环境。交付包有 `sim-frontend/dist` 时启动无需 Node。

```powershell
py -3.12 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\configure-full.ps1
```

若依赖环境和配置已经完成，跳过对应步骤。配置向导填写自己的 MySQL、DeepSeek、AnythingLLM、管理员和默认 SSH 凭据；不会覆盖已有 `.env`。设备清单不接受任何口令或密钥。配置和启动的完整约定见 [full 模式首次配置与启动](full模式首次配置与启动.md)。

## 准备并实际导入教材

先在接收方自己的 AnythingLLM 创建专用工作区，将它的 slug 填入配置。使用包内教材准备上传目录：

```powershell
backend\.venv\Scripts\python.exe backend\scripts\setup_full_workspace.py prepare-corpus --output .runtime\corpus-upload
```

命令要求输出目录尚不存在，按与本地知识库一致的准入规则选出 **135 篇正文**，排除 11 份索引及 `ingest: false` 文档，生成唯一的 `doc-001.md` 至 `doc-135.md` 和 `corpus-manifest.json`（原相对路径与内容哈希）。它只准备文件，**没有上传、嵌入或验证 AnythingLLM**。

工作台与本机 AnythingLLM 共用可访问的持久存储目录。请使用新建的空工作区和本机嵌入服务，并将 `KNOWLEDGE_ANYTHINGLLM_STORAGE` 指向 AnythingLLM 实际的 storage 路径。填写配置中的工作区 slug，再用下面的命令上传、嵌入并核验。命令里的 storage 和 slug 使用接收方自己的值。

```powershell
backend\.venv\Scripts\python.exe backend\scripts\sync_full_knowledge.py --corpus-dir .runtime\corpus-upload --storage '<本机 AnythingLLM storage 路径>' --confirm-workspace '<自己的 workspace slug>' --apply
```

脚本逐篇核对包内教材的内容哈希，保留持久源文件，并根据已解析文件与工作区成员续跑。失败后修正原因并重跑原命令。保持原语料目录、工作区和 storage。发生重名或工作区存在其他文档时会停止。若工作区已导入旧版语料，为新候选新建专用空间。

成功后重启接收方的 AnythingLLM，再运行同一条命令并去掉 `--apply`。该次核对 135 篇成员、原文字节版本和检索命中。之后可在工作台点开资料正文。需要验收 DeepSeek 生成与流式回答时，另按最终联调安排运行 `backend/scripts/verify_live_ai.py`。

## 初始化空库与三台设备

完成模型与知识库配置后初始化数据库，暂不启动工作台：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap-local.ps1 -Mode full -NoStart
Copy-Item scripts\examples\full-devices.example.json .runtime\full-devices.json
```

编辑 `.runtime/full-devices.json`：将每个 `EDIT-ME` 替换为自己设备的管理 IP，填写真实主机名、SSH 端口、型号。主机名要与实际 `sysname` 对应；三个 `(管理 IP, SSH 端口)` 必须不同，允许通过同一管理 IP 的三个转发端口访问三台设备。清单不含接口连接关系，不会捏造链路或真实基线。

保持后端停止，在下面参数中填写刚创建的数据库名称：

```powershell
backend\.venv\Scripts\python.exe backend\scripts\setup_full_workspace.py import-devices --manifest .runtime\full-devices.json --expect-database '<自己的数据库名>'
```

脚本核对当前有效配置确为 MySQL + SSH、数据库名完全一致、迁移结构就绪及配置的管理员存在。首次导入只允许业务表为空（用户、系统配置和审计可已存在），在同一事务内创建主拓扑、三台 `unknown` 设备和现有七个实验模板。SSH 凭据沿用接收方的默认配置；导入不会登录设备，也不会声称设备在线。

相同清单重复执行只核对收据并返回原 ID，不重建或覆盖实验编辑。清单改变、原设备身份改变或已有业务数据时明确拒绝；中途失败整体回滚。不要用它升级已有用户库。实验模板中的 R1/R2/R3、接口和网段是参考内容，接收方应按自己的真实拓扑修订后使用；模板导入不代表技能验证或配置已经执行。

之后按 full 启动指南运行 `scripts/start-full.ps1`，在界面进行设备连接检查、运行态校验并人工确认基线。真实校验需要 SSH 与相应发现信息可用；失败不得改用模拟结果作为基线。若设备尚未启用 LLDP，可在管理员明确确认的库存导入中使用 `inventory_only=true` 建立仅含三设备身份的基线；它允许完成首次受控配置准备，但不表示链路已发现或验证。正常 Excel 设备/链路导入同样必须经过明确确认。

## 从已确认基线导出白名单

部署白名单默认为空、拓扑及版本默认 0，防止继承开发机授权。将界面当前拓扑 ID 填入命令：

```powershell
backend\.venv\Scripts\python.exe backend\scripts\setup_full_workspace.py export-allowlist --expect-database '<自己的数据库名>' --topology-id <实际拓扑ID> --output .runtime\confirmed-allowlist.env
```

导出只读数据库，要求最新基线来自人工确认的三设备运行态校验，或具有匹配确认审计的 Excel/`inventory_only` 导入，且当前设备、端口和链路快照未变化。`inventory_only` 必须没有链路，导出文件明确标注它仅确认目标身份。输出四个实际白名单键，使用本库分配的设备 ID、管理 IP、拓扑 ID 和基线版本；不会覆盖 `.env`，不会改变 `DEPLOY_SIMULATE_ONLY=true`。接收方检查导出文件后自行合入配置并重启，另行确认写设备范围。执行部署时仍由后端重新核对基线和设备锁。
