# IP 仿真运维管理工作台

面向网络运维初学者的工作台。从首页「入门巡检」开始，查看拓扑、记录一条接口观察并保存到实训历史。继续学习时可通过课程步骤打开教材对应页，或请右侧助手解释步骤和证据。

**V7.0 增量候选** · [Windows 快速启动](#windows-快速启动) · [Linux 最小模式](#linux-最小模式) · [首次验收](#首次验收) · [启动与接管指南](启动与验收.md)

## 本机演示

**全新演示账号 `admin`，密码 `123456`。** 仓库自带预构建前端、模拟设备、实训和可搜索的教材整理稿。首次启动需要能下载 Python 依赖，也可使用离线 wheel 包。运行随仓库附带的网页无需安装 Node.js。

### Windows

安装 Git 和 Python 3.12，在终端运行下列命令。如果系统只提供 `python` 命令，先确认 `python --version` 显示 3.12，再将 `py -3.12` 换成 `python`。

```powershell
git clone --branch main https://github.com/murd3r17/ip-sim-workbench.git
cd ip-sim-workbench
py -3.12 scripts/bootstrap_local.py --demo
```

### Ubuntu 24.04

先安装 Git、Python 3.12 和 `python3.12-venv`，再启动。

```bash
sudo apt update
sudo apt install git python3.12 python3.12-venv
git clone --branch main https://github.com/murd3r17/ip-sim-workbench.git
cd ip-sim-workbench
python3.12 scripts/bootstrap_local.py --demo
```

打开 [本机工作台](http://127.0.0.1:8000/login)。端口占用时加 `--port 18080`，按终端显示的地址访问。按 Ctrl+C 停止。演示只监听本机，数据保存在 `.runtime/demo`。重新启动会保留已有记录和密码。

可先做「入门巡检」，或在右侧助手输入「请查教材并列出 VRRP 抢占延时的出处」。离线状态可打开命中的随包整理稿。生成对话回答需配置自己的 DeepSeek 密钥，查看 PDF 原页需挂载获授权的教材和登记原书。 [模型和教材配置](启动与验收.md)

## 完整教材与索引

冻结教材 V06 覆盖 10 册、8,573 个物理页，包含 259 篇整理稿、页位、审校图和两份可直接使用的原书检索索引。原版 PDF 单独下载。下载后按 Windows 或 Ubuntu 的命令挂载，即可用同版教材检索并回查原页。 [下载完整教材、索引和原书 PDF](https://github.com/murd3r17/ip-sim-workbench/releases/tag/textbooks-v06-b6518384dfac) · [校验与挂载步骤](启动与验收.md#挂载发布版完整教材)

## 界面预览

截图来自本地模拟实训环境，点击图片可查看原尺寸。

[![工作台首页与六台模拟设备的全局拓扑](docs/images/workbench/dashboard.png)](docs/images/workbench/dashboard.png)

| 拓扑与链路 | 设备只读观察 |
| --- | --- |
| [![展示设备和登记链路的拓扑页](docs/images/workbench/topology.png)](docs/images/workbench/topology.png) | [![设备列表与接口采集结果](docs/images/workbench/device-observation.png)](docs/images/workbench/device-observation.png) |

| WebSSH 终端 | 终端内打开实训会话 |
| --- | --- |
| [![连接模拟设备并查看命令回显](docs/images/workbench/webssh.png)](docs/images/workbench/webssh.png) | [![在终端原页打开会话，查看实训笔记和步骤](docs/images/workbench/training-session.png)](docs/images/workbench/training-session.png) |

| 实训课程目录 | 知识库目录 |
| --- | --- |
| [![实训目录显示课程和可用条件](docs/images/workbench/training-courses.png)](docs/images/workbench/training-courses.png) | [![随包教材目录与全文入口](docs/images/workbench/knowledge.png)](docs/images/workbench/knowledge.png) |

## Windows 快速启动

如果需要自己的独立账号和长期使用的本机数据库，可从仓库根目录用 PowerShell 7 后台启动。

```powershell
pwsh -NoProfile -File .\scripts\bootstrap-local.ps1 -Mode minimal
```

脚本就绪后打开 [本机工作台](http://127.0.0.1:8000)。在仓库根目录的 `.env` 查看首次生成的 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD`，登录后进入「工作台」。8000 端口有占用时，在启动命令末尾加 `-BackendPort 18080`，按脚本打印的地址访问。

## Linux 最小模式

按「本机演示」准备 Python 和 venv。如果需要生成自己的初始管理员账号，从仓库根目录启动常规模拟环境。

```bash
python3.12 scripts/bootstrap_local.py
```

在根目录 `.env` 查看初始管理员账号。按 Ctrl+C 停止，或通过 `--port 18080` 改用空闲端口。完整模式的安装与真设备接入请参考对应指南。[完整模式](docs/guides/full模式首次配置与启动.md)

需要自己重建网页时，安装 Node.js 20 或更新版本，从 `sim-frontend` 运行 `npm ci` 和 `npm run build`。

## 首次验收

1. 在「工作台」核对六台设备和五条链路。点「打开拓扑页」，选择一条链路查看两端接口。
2. 进入「设备」，对 R-1 点「只读观察」→「采集只读事实」，查看接口状态和采集时间。也可以在「终端」连接 R-1，输入 `display interface brief` 查看回显。
3. 回首页点「入门巡检」和「开始巡检」。按提示记录设备、接口、状态和观察时间，点「保存笔记/步骤」。在终端页点右上角「实训进行中」，可原地查看或编辑会话，关窗后继续使用终端。
4. 进入「知识库」→「检索资料」，输入 `OSPF` 并打开一个结果。本机可阅读和检索随仓库提供的整理稿。挂载获授权的同版教材资产后，也可从实训步骤和助手引用打开对应正文与可用原图。
5. 管理员可在「系统管理」的「账号管理」创建或重置普通账号。学员从右上角账号菜单修改自己的密码。

## 接管与扩展

| 接下来要做的事 | 入口 |
| --- | --- |
| 停止或重启本地服务，处理首跑、登录和备份 | [启动与验收](启动与验收.md) |
| 使用设备管理、监控告警、配置审批、版本与回退 | [用户手册](docs/guides/用户手册.md) |
| 接入自有模型或获授权的本地教材目录 | [开启对话助手](启动与验收.md#开启对话助手) · [自有教材目录](启动与验收.md#自有教材目录) |
| 配置 MySQL、真实 SSH 设备和联网知识服务 | [完整模式首次配置与启动](docs/guides/full模式首次配置与启动.md) |
| 核对依赖、扫描交付文件、生成接收方副本 | [交付检查与隔离打包](docs/guides/交付检查与隔离打包.md) |

当前增量候选在 Windows 本地模拟环境验证了入门巡检、笔记保存与复盘回读、模型配置、典型审批流程以及独立 Edge 的全屏、窗口变化和 200% 键盘操作。真实设备联调与变更恢复、接收方独立部署及真人上手分别验收。

前端位于 `sim-frontend`，使用 Vue 3、TypeScript 和 Vite。后端位于 `backend`，使用 FastAPI、SQLAlchemy 和 Alembic。前后端检查可在 GitHub Actions 查看。运维基础继承自原工作台项目。[CI](https://github.com/murd3r17/ip-sim-workbench/actions/workflows/ci.yml) · [上游项目](https://github.com/drongzsy/probable-meme)

反馈问题时请附启动方式、复现步骤、预期和实际结果，以及有助于定位的脱敏截图或日志。[反馈问题](https://github.com/murd3r17/ip-sim-workbench/issues/new)
