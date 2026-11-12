---
doc_id: "hcie-datacom-v1.0-training-21"
title: "网络编程与自动化及 SSH/Paramiko"
book: "HCIE-Datacom-V1.0-Training"
book_title: "HCIE-Datacom V1.0 培训教材"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "training"
source_pdf: "HCIE-Datacom+V1.0+培训教材.pdf"
seq: 21
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# 网络编程与自动化及 SSH/Paramiko

## IPv6 配套系统改造（续）

### 网管系统 IPv6 改造

- 网管系统不面向用户，IP 地址需求数量不多，系统内部通信向 IPv6 演进的需求不强烈，因此可以仍保留 IPv4 地址，不进行 IPv6 改造。
- 网管系统其他方面改造：
  - 能够实现各种 IPv6 地址类型的识别和管理。
  - 支持 IPv6 中 DNS 解析监控功能。
  - 支持对 IPv6 设备和双栈设备的性能、资源、故障等数据采集，满足性能管理、资源管理、故障管理及分析等功能。
  - 支持对双栈设备的各种资源、性能、故障等数据与历史数据平滑关联。
  - 应可以通过基于 IPv4 的 SNMP 访问相关设备 IPv6 MIB，通过 IPv6 MIB 获得 IPv6 配置和流量等相关信息。

### 服务器操作系统 IPv6 改造

常见 Linux 系统开始支持 IPv6 的版本（均已默认安装 IPv6）：

- Fedora 13
- Red Hat Enterprise Linux 6
- Ubuntu 12.04
- Oracle Solaris 10
- SUSE Linux Enterprise Server 11 等

Windows Server：

- Windows 2003 Server 支持 IPv6，但默认未安装，需手工安装相应软件包。
- Windows 2008 Server 及以后的服务器版本均已默认安装 IPv6。

### 思考题（IPv6 演进）

1.（多选题）广域网络 IPv6 演进过程中，有可能采用以下哪些选项的部署方案？

- A. 双栈
- B. 6VPE
- C. SRv6
- D. VXLAN Underlay IPv4 + Overlay 双栈

参考答案：A、B、C

2.（判断题）IPv6+ 技术包括以网络编程、网络切片、确定性网络、随流检测、新型组播、应用感知等为代表的网络创新技术。（）

- A. 正确
- B. 错误

参考答案：A

### IPv6 章节小结

- 企业网络一般涉及数据中心、广域网、园区网络，IPv6 演进需要考虑应用、终端、网络的整体能力升级协同，保障演进过程中不影响现有业务用户体验；方案设计需确保可平滑持续演进，并兼顾当前最优 IPv6 技术选择，构建新一代 IPv6 信息化基础设施。
- 本课程介绍了数据中心、广域网、园区网等场景 IPv6 网络演进趋势，并讲解了 IPv6+ 相关技术应用。

---

## 网络编程与自动化概述

### 前言与目标

网络产业发展方向是让网络变得更加开放、灵活和简单。华为希望帮助客户构建意图驱动的智简网络。网络开放可编程是智简网络的必由之路；人工智能与网络结合是大势所趋（如 iMaster NAIE）。

学完本课程后，您将能够：

- 描述网络编程与自动化的背景
- 描述网络开放的层次
- 描述华为 iMaster NCE 的开放能力
- 描述网络自动化工程师的定位和相关能力
- 描述网络人工智能的需求
- 描述华为网络人工智能引擎 iMaster NAIE 服务

大纲：1. 网络编程与自动化概述 2. 网络自动化开发工程师 3. 网络自动化的分类 4. 网络人工智能概述

### 背景：复杂的网络

从计算机网络产生起，网络变得越来越复杂且难以管理，体现在：

- 网络设备越来越多样：路由器、交换机、防火墙、IDS 等。
- 不同厂家设备管理方式不同，甚至同厂家不同型号也不同。
- 设备复杂导致网络管理复杂：多套网管系统；管理方式多样（SNMP / CLI / IPFIX / Web-UI 等）。

### SDN 分层与接口（复习）

| 层次/接口 | 说明 |
|----------|------|
| 协同应用层 | OSS、OpenStack 等；也可调用控制器北向接口的安全 APP（如 Block(Source IP, Dest IP)） |
| 控制器层 | SDN 控制器，核心是网络业务编排 |
| 设备层 | 接收控制器指令并执行转发 |
| NBI | 北向接口，主要为 RESTful |
| SBI | 南向接口：NETCONF、SNMP、OpenFlow、OVSDB 等 |

### 初级网络自动化

网络自动化即通过工具实现网络自动化部署和运维，逐步减少对人的依赖。业界开源工具如 Ansible、SaltStack、Puppet、Chef 等，通过 SSH 连接设备实现批量化操作，属于初级网络自动化。相关关键词：Chef、SaltStack、Ansible、Python、Shell、网管工具、自动化脚本。

### 网络自动化的发展

初级网络自动化基于 CLI 管理网络，痛点在于设备返回非结构化文本回显，不利于计算机处理。发展基础需求是设备提供结构化数据（XML/JSON），开放 NETCONF/RESTCONF 等接口。

对比：

| 类型 | 特点 | 示例 |
|------|------|------|
| 非结构化数据 | 人易于理解 | CLI 文本回显（Interface / InUti / OutUti / inErrors / outErrors） |
| 结构化数据 | 机器易于理解 | JSON：`{"Interfaces": {"GigabitEthernet0/0/0": {"InUti": "10", "OutUti": "20", ...}}}` |

协议对比：CLI/SSH、SNMP ↔ NETCONF、RESTCONF。

### 网络开放与可编程简介

网络开放与可编程：在开放网络前提下使用编程手段实现自动化。传统网络与 SDN 会长期并存。开放体现在两个层面：

- **基于设备的开放与可编程**：CLI/SSH、SNMP、NETCONF、RESTCONF、Telemetry、OPS 等
- **基于 SDN 平台的开放与可编程**：RESTful API

### 华为 iMaster NCE 业务开放可编程

iMaster NCE（简称 NCE）是华为网络云化引擎。整体开放编程能力包括自动化、分析和意图，目标是打造全生命周期开放可编程架构。NCE 业务开放可编程定位于助力客户实现业务自动化。NCE 不仅是控制器，还包含分析和网络管理等功能。

### 网络自动化开发工程师

**网络工程师**：掌握网络技术与职业技能，能沟通需求、制定实施方案与计划、调动资源保障落地，并完成培训与文档交付。

**网络自动化开发工程师**：掌握网络和开发技术，具备项目实施和开发经验，满足企业网络自动化部署、开发和运维需求。

综合能力模型对比：与网络工程师相比，基本素质和职业技能相同，但专业知识上需额外掌握开发相关技术、产品和工程知识；并可能涉及数据库、算法、密码学、软件开发生命周期、开发框架、大数据、云计算和人工智能等。

### 网络自动化的分类

#### 设备开放可编程

定位于指导工程师根据设备开放能力编程实现自动化。华为设备开放能力包括：Python（paramiko、pysnmp、ncclient、requests、gRPC 等）、CLI/SSH、SNMP、NETCONF、RESTCONF、Telemetry、FTP、MIB、YANG、OPS（Open Programmability System）等。

#### NCE 北向开放

控制器开放可编程：华为 iMaster NCE 提供北向开放 RESTful API，覆盖 iMaster NCE-Fabric / Campus / WAN / IP 等。

#### 网元驱动包与业务包（概要）

- 网元驱动包以设备 YANG 抽象设备能力；用户根据 YANG 与少量 Python 生成驱动包，上传 NCE 后实现设备管理与业务发放。
- SND 类型：
  - **NETCONF SND**：YANG → NETCONF
  - **CLI SND**：YANG → CLI
  - **Customized SND**：YANG → 其他协议（如 RESTCONF）
- 业务包支持自定义网络业务（APP），如快速开通 L3 VPN；涉及多设备、多协议，需业务 YANG、业务映射 Python（回调逻辑）和 Jinja2 模板。北到南基本原理：
  1. 业务模型自动生成北向接口或 UI，被外部调用发起业务请求
  2. 业务逻辑处理（Python + Jinja 模板）
  3. Python 实现与厂家无关逻辑；模板实现厂家相关下发数据
  4. SND 将设备模型转换为协议报文下发（如 NETCONF）

### 网络人工智能概述

通用目的技术（GPT, General Purpose Technology）是推进经济社会转型的主要动力。AI 已成为新的通用目的技术，使能千行百业。

AI 引入网络成为产业共识，演进等级：

| 等级 | 名称 | 特点概要 |
|------|------|---------|
| L0 | 人工作业 | 人重复执行 |
| L1 | 工具辅助自动化 | 子任务级 |
| L2 | 部分自动驾驶网络 | 单元级 |
| L3 | 限制条件的自动网络 | 领域级 |
| L4 | 高度自动驾驶网络 | 业务级/跨领域 |
| L5 | 完全自动驾驶网络 | 公共 ICT 基础设施级，机器主导感知决策 |

难点：业务专家与 AI 专家配合；业务专家转型难；数据来源少且需治理；算法工程化；算力获取难。AI 本质带来组织转型，走向人机共存的 AIOps。

### 网络人工智能引擎 iMaster NAIE

iMaster NAIE 是华为将 AI 引入电信网络的一站式 AI 应用开发云平台。基于公有云模式，提供数据服务、模型训练、模型生成和通信模型服务，覆盖数据准备、特征探索、模型调优等复杂工作，便于开发者快速获取 NAIE 能力（如节省数据准备时间、经验嵌入提升训练效率、低门槛/低编码模型生成等）。

### 示例：智能流量分拣

数据中心同时承载大数据、分布式存储、高性能计算、GPU 集群等业务。流量分拣即交换机识别分类流量报文，确定每个数据流/报文属于哪种业务。可基于华为 AI Fabric 交换机嵌入式 AI 平台 API（兼容 Tensorflow 和 Caffe）实现流量分类算法。

模型评估：将真实数据区分为训练集与测试集；用训练集训练，用测试集误差评估最终效果。误差越小，算法模型越优秀。

参考：https://devstar.developer.huaweicloud.com/devstar/code-templates/e9078ee2d7024ffabbac3f8fd1bad806 ；更多见华为人工智能认证。

### 思考题（网络编程与 AI）

1.（多选题）控制器与设备交互的协议包括以下哪些选项？

- A. NETCONF
- B. SNMP
- C. OpenFlow
- D. RESTful

参考答案：A、B、C  
（说明：RESTful 主要为北向接口；南向常见为 NETCONF/SNMP/OpenFlow 等。）

### 网络编程与自动化小结

- 网络编程与自动化在开放网络前提下用编程实现自动化；开放分设备开放与 SDN 平台开放两层。
- 网络自动化开发工程师需具备网络、系统与开发融合能力。
- 网络与人工智能结合是发展趋势；iMaster NAIE 让网络 AI 开放更简单。

---

## SSH 与 Paramiko

### 前言与目标

面对复杂业务与网络架构，网络自动化不断普及。SSH 登录设备是工程师最熟悉的远程管理方法，有必要学习自动化工具实现 SSH 远程登录、模拟人机交互、自动传输文件等。本课程使用 Python Paramiko 编写自动化脚本，实现基于 SSH 的初级网络自动化。

学完后，您将能够：

- 描述 SSH 的基本概念和工作原理
- 描述 Paramiko 的概念
- 描述 Paramiko 的组成及常用方法
- 实现 Paramiko 的常用方法

大纲：1. SSH 介绍 2. Paramiko 组件架构 3. SSH 实践

### SSH 简介

SSH（Secure Shell，安全外壳协议）用于在不安全网络上进行安全远程登录及其他安全网络服务。由三个组件构成：

| 组件 | 作用 |
|------|------|
| SSH 传输层协议 | 版本协商、算法协商、密钥交换 |
| SSH 用户认证协议 | 用户认证（口令、密钥） |
| SSH 连接协议 | 建立会话连接 |

**完美前向保密（PFS, Perfect Forward Secrecy）**：长期密钥泄露不会导致过去会话密钥泄露，保护历史通信。SSH 传输层采用的 Diffie-Hellman 密钥交换可提供 PFS。更多见 RFC 4251 9.3.7：https://www.ietf.org/rfc/rfc4251.txt

**公钥与数字签名**：公钥用于验证信息来自拥有私钥者且完整正确；协议启动时从传输层接收会话 ID，会话 ID 唯一标识会话并参与签名以证明私钥所有权。

**TCP/IP 连接转发**：可将其他 TCP 端口数据经 SSH 通道转发以保证安全。Telnet、SMTP、IMAP 等可经 SSH 转发避免明文；防火墙限制端口但允许 SSH 时也可借此通讯。X11 转发可将 Linux 图形界面经 SSH 投射到客户端。会话是程序的远程执行（shell、应用、命令或子系统）；可用 `invoke_shell()`、`exec_command()` 等方法。

### SSH 工作原理（五阶段）

1. **版本协商**：SSH1 / SSH2，双方协商版本。
2. **算法协商**：双方根据支持列表协商加密等算法。
3. **密钥交换**：生成会话密钥，此后会话加密。
4. **用户认证**：客户端发起认证，服务器认证客户端。
5. **会话交互**：认证通过后进行信息交互。

对应协议分层：传输层协议 → 用户认证协议 → 连接协议。

#### 版本协商细节

服务端打开端口 22 等待连接。客户端发起 TCP 连接并握手后，发送版本标志字符串（协议版本号、次版本号、软件版本号）。服务端解析后决定使用的版本。

#### 算法协商细节

从客户端算法列表取第一个算法，在服务器列表中查找；匹配成功则协商该算法，否则继续取下一个，直到匹配成功。

#### 密钥交换（DH 概要）

1. 双方约定公开质数 p 和 g。
2. 各自随机产生私钥 Xc、Xs。
3. 各自计算公钥 Yc、Ys 并交换。
4. 根据公私钥计算会话密钥。

私钥始终保密；即使获得 p、g、Yc、Ys，因离散对数困难也无法推断私钥。该阶段公私钥仅用于产生会话密钥，与后续用户认证无关；完成后后续报文均由会话密钥加密。

#### 用户认证：口令认证

客户端发送携带用户名和口令的认证请求，服务器与本地用户数据匹配。

```text
客户端 -- SSH_MSG_USERAUTH_REQUEST (username/password) --> 服务器
客户端 <-- SSH_MSG_USERAUTH_SUCCESS -- 服务器
```

#### 用户认证：公钥认证

客户端发送携带数字签名的认证请求，服务器用公钥解密数字签名进行认证。请求中可包含用户名、认证方法 publickey、公钥算法（ssh-rsa/ssh-dss 等）、公钥及由私钥签名的数据（含用户名、会话 ID、公钥算法、公钥等）。

通道类型包括：会话通道、X11 通道、转发的 tcp-ip 通道、非转发（直连）tcp-ip 通道。更多见 RFC 4250 4.9.1：https://www.ietf.org/rfc/rfc4250.txt

### Paramiko 简介

在 HCIA 课程中学习过 telnetlib；生产环境更推荐安全的 Paramiko 进行 SSH 远程连接。

### Paramiko 组件架构

最常用类为 **SSHClient** 与 **SFTPClient**。课程涉及：Transport、Key handling、SSHClient、SFTPClient。

相关类作用：

| 类 | 作用 |
|----|------|
| Channel | 执行命令、请求 X11、发送数据、打开交互式会话等（常用方法多已包装进 SSHClient） |
| Message | 向流写入/提取字节等 |
| Packetizer | 检查握手、获取 channel ID 等 |
| Transport | 公钥认证、打开 channel 等 |
| SSHClient | 建立连接、打开交互式会话等 |
| SFTPClient | 文件上传、下载等 |

OpenSSH 是 SSH 的免费开源实现；Linux 普遍集成。OpenSSH 将访问过的主机公钥记录在 `~/.ssh/known_hosts`，下次核对公钥，不同则警告以防中间人攻击。

由于 SSHClient 集成了 Transport、Channel、SFTPClient，许多能力可由 SSHClient 单独完成。

### Key handling 类

用于创建对应密钥类型实例（RSA、DSS/DSA），包含密钥读取、写入等方法。

```python
key = paramiko.RSAKey.from_private_key_file(r"C:\Users\exampleuser\.ssh\id_rsa")
```

| 常用方法 | 功能 |
|---------|------|
| RSAKey.from_private_key_file(filename) | 从文件读取 RSA 私钥创建密钥对象 |
| DSSKey.from_private_key_file(filename) | 从文件读取 DSS 私钥创建密钥对象 |

### SFTPClient 类

通过打开的 SSH Transport 会话通道创建 SFTP 连接并执行远程文件操作。

典型用例：

```python
key = paramiko.RSAKey.from_private_key_file(r"C:\Users\exampleuser\.ssh\id_rsa")
tran = paramiko.Transport(("192.168.56.100", 22))
tran.connect(username="client", pkey=key)
sftp = paramiko.SFTPClient.from_transport(tran)
local_path = r"C:\Users\exampleuser\.ssh\vrpcfg.cfg"
remote_path = "/vrpcfg.cfg"
sftp.get(remote_path, local_path)
```

| 常用方法 | 功能 |
|---------|------|
| from_transport() | 从打开的 Transport 创建 SFTP 会话 |
| get() | 下载指定文件 |
| put() | 上传指定文件 |

**from_transport()** 参数：已认证开启的 Transport；可选 `window_size`、`max_packet_size`。

**get(remotepath, localpath)**：将远程文件复制到本地；`localpath` 应包含文件名。

**put(localpath, remotepath)**：将本地文件复制到远端；`remotepath` 应包含文件名。

### SSHClient 类

SSHClient 是与 SSH 服务器会话的高级表示，包装了 Transport、Channel、SFTPClient。

典型用例：

```python
client = paramiko.client.SSHClient()
client.connect(
    hostname="192.168.56.100",
    port=22,
    username="client",
    password="<REDACTED>",
)
stdin, stdout, stderr = client.exec_command("ls -l")
```

| 常用方法 | 功能 |
|---------|------|
| connect() | 远程连接与认证 |
| set_missing_host_key_policy() | 未知主机密钥策略 |
| load_system_host_keys() | 从系统文件加载主机密钥 |
| exec_command() | 在远程执行 Linux 命令 |
| invoke_shell() | 启动交互式 shell |
| open_sftp() | 创建 SFTP 通道 |
| close() | 关闭连接 |

**connect()** 参数：

| 参数 | 说明 |
|------|------|
| hostname | 目标主机（必选） |
| port | 默认 22 |
| username | 认证用户名 |
| password | 用户密码 |
| key_filename | 私钥文件名或列表 |
| pkey | 用于身份验证的私钥对象 |

示例：

```python
client.connect(hostname="192.168.56.100", port=22, username="client", key_filename="id_rsa")
client.connect(hostname="192.168.56.100", port=22, username="client", password="<REDACTED>")
```

```python
client.load_system_host_keys()
stdin, stdout, stderr = client.exec_command("ls -l")
cli = client.invoke_shell()
sftp = client.open_sftp()
```

首次连接未知主机时，通常需确认 Yes/No；可用 `AutoAddPolicy` 等策略自动处理（实验常用，生产需谨慎）。

---

## SSH / SFTP 实践

### 案例：使用 SSH 登录设备（RSA）

拓扑：STelnet 服务器 `192.168.56.100`（GE1/0/0）— STelnet 客户端 `192.168.56.1`。

流程：配置设备 STelnet → 配置用户 → 创建密钥对 → 配置公钥 → 编写 Python 代码 → 结果验证。

#### 服务器端配置

1. 配置管理网口 IP，使能 STelnet，配置 VTY：

```cli
<HUAWEI> system-view immediately
[SSH Server] interface GE1/0/0
[SSH Server-GE1/0/0] ip address 192.168.56.100 24
[SSH Server-GE1/0/0] quit
[SSH Server] stelnet server enable
[SSH Server] user-interface vty 0 4
[SSH Server-ui-vty0-4] authentication-mode aaa
[SSH Server-ui-vty0-4] protocol inbound ssh
[SSH Server-ui-vty0-4] user privilege level 3
[SSH Server-ui-vty0-4] quit
```

2. 创建本地用户并加入管理员组，配置服务类型：

```cli
[SSH Server] aaa
[SSH Server-aaa] local-user client password irreversible-cipher Huawei@123
[SSH Server-aaa] local-user client user-group manage-ug
[SSH Server-aaa] local-user client service-type ssh
[SSH Server-aaa] quit
```

3. 创建 SSH 用户，配置认证方式与服务方式：

```cli
[SSH Server] ssh user client
[SSH Server] ssh user client authentication-type rsa
[SSH Server] ssh user client service-type stelnet
```

4. 在设备上配置客户端公钥（将客户端 `id_rsa.pub` 内容导入并绑定用户）。命令详见产品文档：  
https://support.huawei.com/enterprise/zh/doc/EDOC1000097324/466984de

#### 客户端创建 RSA 密钥对

使用 Git Bash：

```bash
$ ssh-keygen -t rsa
# 按提示选择保存路径与通行短语（可回车默认）
$ cat /c/Users/exampleuser/.ssh/id_rsa.pub
```

生成私钥 `id_rsa` 与公钥 `id_rsa.pub`。

#### 客户端 Python 代码

```python
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    hostname="192.168.56.100",
    port=22,
    username="client",
    key_filename=r"C:\Users\exampleuser\.ssh\id_rsa",
)
cli = ssh.invoke_shell()
cli.send("screen-length 0 temporary\n")
cli.send("display current-configuration\n")
time.sleep(3)
dis_cu = cli.recv(999999).decode()
print(dis_cu)
ssh.close()
```

#### 结果验证

运行代码后应成功显示 SSH 服务器当前配置信息（含 Software Version 等回显）。

---

### 案例：使用 SFTP 上传和下载文件

SFTP（SSH File Transfer Protocol）建立在 SSH 之上，功能覆盖 FTP 且更安全可靠。

拓扑：SFTP 服务器 `192.168.56.100` — SFTP 客户端 `192.168.56.1`。本例以 RSA 认证演示 Paramiko SFTP 上传下载。

#### 服务器端配置

```cli
<HUAWEI> system-view immediately
[SFTP Server] interface GE1/0/0
[SFTP Server-GE1/0/0] ip address 192.168.56.100 24
[SFTP Server-GE1/0/0] quit
[SFTP Server] ssh user client
[SFTP Server] ssh user client authentication-type rsa
[SFTP Server] ssh user client service-type sftp
[SFTP Server] ssh user client sftp-directory cfcard:
[SFTP Server] ssh authorization-type default root
[SFTP Server] sftp server enable
```

客户端同样用 `ssh-keygen -t rsa` 生成密钥，并将公钥配置到设备（文档同上）。

#### 客户端 Python 代码

```python
import paramiko

key = paramiko.RSAKey.from_private_key_file(r"C:\Users\exampleuser\.ssh\id_rsa")
tran = paramiko.Transport(("192.168.56.100", 22))
tran.connect(username="client", pkey=key)
sftp = paramiko.SFTPClient.from_transport(tran)
local_path = r"C:\Users\exampleuser\.ssh\vrpcfg.cfg"
remote_path = "/vrpcfg.cfg"
sftp.get(remote_path, local_path)          # 下载
sftp.put(local_path, "/test.cfg")          # 上传
tran.close()
```

#### 结果验证

- 客户端本地成功下载指定文件（如 `vrpcfg.cfg`）。
- 服务器端 `dir` 可看到上传文件，例如：

```cli
<SFTP Server> dir
```

```text
Directory of cfcard:/
Idx  Attr  Size(Byte)  FileName
...
       2428            test.cfg
```

### 思考题（SSH）

1.（多选题）SSH 协议有哪几个工作阶段？

- A. 版本协商阶段
- B. 算法协商阶段
- C. 密钥交换阶段
- D. 用户认证阶段
- E. 会话交互阶段

参考答案：A、B、C、D、E

### SSH/Paramiko 本章小结

- 介绍了 Paramiko 与 SSH 概念，重点分析 SSH 工作原理。
- 介绍了 Paramiko 组件和常用方法，并通过 Python SSH 及 SFTP 示例实现基于 SSH 的初级网络自动化。

更多信息：

- Paramiko 文档：https://docs.paramiko.org/en/latest/index.html
- SSH RFC：https://tools.ietf.org/html/rfc4251  
  https://tools.ietf.org/html/rfc4252  
  https://tools.ietf.org/html/rfc4253  
  https://tools.ietf.org/html/rfc4254
