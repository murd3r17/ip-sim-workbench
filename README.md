# IP 仿真运维管理工作台

面向网络运维初学者的 Windows 工作台。可以从拓扑选中设备，查看接口和邻居证据，在右侧助手里询问操作或网络原理，再进入实训保存自己的观察和判断。

- 运维工具包括设备管理、拓扑、WebSSH、监控告警、配置审批、回读验证、版本与回退。
- 右侧助手结合当前页面和设备，支持教材问答、带来源的解释和待审阅配置草稿。
- 内置七个协议和排障实验，以及适合离线体验的模拟巡检。知识库附 135 篇整理正文。

## 2026-11-12 项目进度

当前为 **V7.0 E 阶段工程候选**。首次配置、独立 MySQL 迁移与恢复、知识初始化与断点续跑、实例启动停止、干净目录安装均已验证。冻结工程候选通过 2,311 项后端测试、130 项前端交互断言和 8 组浏览器旅程。

F 阶段的接收方完整模式首跑、真实模型与三台联网设备联合验证、设备变更恢复及初学者实测仍待完成。

## 在 Windows 上体验

安装 Python 3.12，确保可以访问 Python 包安装源，在仓库根目录运行以下命令。仓库包含预构建网页。

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap-local.ps1 -Mode minimal
~~~

打开 http://127.0.0.1:8000，用本机根目录 .env 中生成的管理员信息登录。此模式使用 SQLite、六台模拟设备和本地知识检索。

完整联网模式需要接收方自己的 MySQL、DeepSeek 接口、AnythingLLM 工作区、嵌入服务及可达的 SSH 设备。 [完整模式首次配置与启动](docs/guides/full模式首次配置与启动.md)

## 维护与参考

- 前端使用 Vue 3、TypeScript、Vite 和 Element Plus，后端使用 FastAPI、SQLAlchemy 与 Alembic。运行预构建网页时由后端托管。
- [用户手册](docs/guides/用户手册.md) · [设备与知识库初始化](docs/guides/full设备与知识库首次初始化.md) · [交付检查和隔离打包](docs/guides/交付检查与隔离打包.md)
- 运维基础来自原工作台项目。 [上游项目](https://github.com/drongzsy/probable-meme)
