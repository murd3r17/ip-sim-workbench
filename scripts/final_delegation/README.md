# 三设备隔离开发环境（2026-11-05 修复版）

仅用于 Windows、本项目 .runtime 下的新临时实例。已通过路径/配置/进程负例及本机双实例初始化、预检、停止、重启验证。旧失败证据保留在 docs/ops/V7.0-最后一轮协作协调审核-2026-11-04.md；修复证据见 docs/ops/V7.0增量开发验证记录-2026-11-05.md。这不代表 C 阶段、真实模型或设备验收通过。

## 使用

在 D:/work/ip-sim-workbench 执行，使用不存在的 run 目录与空闲端口：

```powershell
backend/.venv/Scripts/python.exe -B scripts/final_delegation/isolated_env.py init --run-dir .runtime/v7/local-dev/env-a --backend-port 18280 --frontend-port 18273
backend/.venv/Scripts/python.exe -B scripts/final_delegation/isolated_env.py status --run-dir .runtime/v7/local-dev/env-a
backend/.venv/Scripts/python.exe -B scripts/final_delegation/isolated_env.py stop --run-dir .runtime/v7/local-dev/env-a
backend/.venv/Scripts/python.exe -B scripts/final_delegation/isolated_env.py start --run-dir .runtime/v7/local-dev/env-a
```

- init 只接受新目录，重复初始化拒绝；start 保留数据库，产生新 launch_id 并重新预检。
- SQLite、日志、临时文件、预算及配置检查结果都在 run-dir。private/credentials.json 保存本实例临时凭据，不回显、不提交、不复制进报告。
- Python 子进程使用同一允许列表环境并禁用 dotenv；Vite envDir 指向本实例。固定 sim、SQLite、本地语料库、关闭调度、清空 provider key；不继承根 .env 的联网配置。
- 2026-11-06补修：教材读取限定 knowledge/corpus/huawei-ip 的135篇正文，不把上一级名称映射TXT当教材；本地provider上传存储指向本实例knowledge-storage。设置只在新子进程导入应用前生效，清除该子进程provider缓存，启动检查核对实际provider两个目录；不改正常应用默认目录或现用知识空间。
- 只监听 127.0.0.1，先检查前后端端口。端口上已有服务不能认领成本实例。
- 收据 schema=2，绑定目录、数据库、启动 nonce，以及 PID、完整 Windows 创建时间、可执行文件和命令行；后端 runtime-identity 和前端代理目标另行校验。
- stop 在同一进程句柄上再次核验创建时间/可执行路径，终止后确认退出。不用 taskkill，不按名字或端口杀，不遍历未知进程树。缺失归属或退出失败返回非零。
- status 查询当前进程及后端身份。旧 READY 但进程已退出时 live_ready=false 并返回非零；旧版 instance.json 不升级、不接管、不启停。
- 预检必须 ready/sim 才能 READY。失败只清理确认归属的进程，无法完整证明归属保留 CLEANUP_REQUIRED。预检本身已有必要取证，不重复追加一轮观察。
- operation.lock 防止并发启停。异常遗留锁须先确认操作结束、核对本实例，再人工处理；脚本不凭旧 PID 自动抢锁。

## 边界

这是防误操作的开发工具，不是运行恶意代码的操作系统沙箱。路径检查拒绝越界、链接/junction 和共享硬链接；本机外部进程不得在核验期间擅自篡改实例文件。未知进程归属时拒绝操作。

reference-data/scenarios.json 等旧材料仍待 C.2 语义修正，不能因为启动器修复就视为可信夹具。实际 DeepSeek、三设备 OSPF、最终首次配置仍单独验收。
