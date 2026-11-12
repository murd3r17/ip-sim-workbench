---
doc_id: "hcip-datacom-core-training-01"
title: "设备转发与IP路由、OSPF基础"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 1
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# 设备转发与IP路由、OSPF基础

## 设备报文处理与转发

- 设备处理报文可分为两类：**业务报文**与**协议报文**。
- 业务报文：设备只做转发——从一个接口进入后，依据转发表项从另一接口发出。
- 协议报文（如 ARP、OSPF、BGP 等）：收到后交由控制层面处理。例如 ARP 由控制层面判断是否回应、是否学习源 MAC/源 IP。

### 相关术语

- **PFE（Packet Forwarding Engine）**：包转发引擎。
- **业务报文**：服务、应用交互过程中的报文。
- **切片**：把报文送往交换网板前，按固定粒度切成固定长度。
- **重组**：将交换网板发来的已切片报文重新组合。

### 二层 / 三层查表

- 二层转发查询 **MAC 地址表**；三层转发查询 **三层路由表（实际为 FIB）**。

### 协议报文上送与限速

- 主控板 CPU 收到协议报文并处理后，如需回应则构造协议报文（如 ARP Reply、ICMP Echo Reply）。
- 主控板 CPU 处理能力有限，过多协议报文上送会造成繁忙；设备默认限制各类协议报文上送 CPU 的速率。
- 在转发引擎 PFE（NP 或 ASIC）做报文解析时，若从二层帧头协议字段即可判断需上送本机 CPU（如 ARP、RARP、IS-IS、LLDP、LACP、PPP 控制报文等），或目的地址为保留组播 `224.0.0.1`～`224.0.0.255`（供路由协议使用），上行**不需要查表转发**。
- 业务报文上行查表后获得目的接口板与出接口，交换网板据此交换到下行单板。对解析即可识别的协议报文（如 BGP），上行不查表，目的接口板填为与入接口板相同的板号，出接口为 CPU（上行 LPU 与下行 LPU 实际为同一 LPU）。
- 能根据二层帧头或目的 IP 识别的协议报文，上行 LPU 直接上送 CPU。

### 思考题（答案）

1. （单选）框式设备中负责运行路由协议、生成/维护路由表的模块是？→ **C. 主控板**
2. （简答）高端框式设备转发业务报文时是否会向主控板查询转发表项？→ **不需要**。高端框式设备将转发信息下发到接口板，接口板直接转发，无需向主控板查询转发表项。

---

## IP 路由基础

当路由器收到 IP 数据包，会根据目的 IP 查找 **FIB（Forwarding Information Base，转发信息库）**，找到“最匹配”路由后，按出接口或下一跳转发出去。

路由器获取路由的方式有三种：动态路由（如 OSPF）、静态路由、直连路由。本课程介绍 IP 路由基础知识，包括路由转发、路由表以及路由引入。

### 学习目标

- 识别 IP 路由表和 FIB 表
- 分析路由转发流程
- 描述路由引入的原理与使用场景

### IP 路由概述

> （原图：PC1 `192.168.11.1/24` — 路由器 — PC2 `192.168.21.1/24`，路由器按目的地址匹配路由条目。）

当路由器收到 IP 报文时：

- 若有匹配路由条目，则依据出接口或下一跳转发；
- 若无匹配路由，则丢弃该报文。

### 路由表与 FIB 表

- **路由表**：位于控制平面，并不直接指导数据转发。真正指导转发的是 FIB。路由器将路由表中的最优路由下载到 FIB；路由表变化时 FIB 立即同步。阐述转发时常用“查路由表”说法，实际查询的是 FIB。
- **FIB 表**：位于数据平面（转发表项），每条指明到达某目的地的出接口及下一跳等。
- 具有路由功能的华为数通产品包括路由器、三层交换机等，本课程以路由器为例。

OSPF（Open Shortest Path First）和 IS-IS（Intermediate System to Intermediate System）均基于链路状态，使用最短路径优先算法。路由器支持 OSPF/IS-IS **多进程**，进程号为本地概念，不影响与其它路由器的报文交换。

### 路由表关键字段

| 字段 | 含义 |
|------|------|
| Destination | 目的地址或目的网络 |
| Mask | 子网掩码长度 |
| Proto | 学习该路由的协议 |
| Pre（Preference） | 路由协议优先级（外部优先级可手工配置；内部优先级不可改）。先比外部优先级，相同时再比内部优先级 |
| Cost | 路由开销 |
| NextHop | 下一跳 |
| Interface | 出接口 |

- **Preference** 用于不同协议间比较；**Cost** 用于同一种协议内部比较。

### FIB 表字段

查看命令：`display fib [ slot-id ]`

| 字段 | 含义 |
|------|------|
| Total number of Routes | 路由总数 |
| Destination/Mask | 目的/掩码 |
| Nexthop | 下一跳 |
| Flag | G/H/U/S/D/B 组合：Gateway / Host / Up / Static / Dynamic / Black Hole |
| TimeStamp | 表项存在时间（秒） |
| Interface | 出接口 |
| TunnelID | 转发表项索引；非 0 表示经隧道（如 MPLS）转发 |

### 路由来源

- **直连路由**：直连接口网段，设备自动生成。
- **静态路由**：管理员手工配置。
- **动态路由**：通过 OSPF、IS-IS、BGP 等学习。

BGP（Border Gateway Protocol）是实现 AS（Autonomous System）之间路由可达并选择最佳路由的路径矢量协议。AS 指在同一实体管辖下、拥有相同选路策略的 IP 网络。

### 动态路由协议分类

- **IGP（Interior Gateway Protocol）**：自治系统内部，如 OSPF、IS-IS。
- **EGP（Exterior Gateway Protocol）**：不同 AS 之间，目前常用 BGP。

> （原图：A/B 公司网络经 ASBR 以 OSPF/IS-IS 与 BGP 互联，网段如 `192.168.11.0/24`、`192.168.21.0/24` 等。）

### 路由迭代

路由必须有**直连下一跳**才能指导转发。静态路由或 BGP 路由的下一跳可能不是直连邻居，需计算出直连下一跳，此过程称为**路由迭代**。

> （原图：R1—R2—R3，网段 `10.0.12.0/24`、`10.0.23.0/24`，目标 `192.168.21.0/24`。）

```cli
# R1 配置示例
ip route-static 192.168.21.0 24 10.0.23.3
ip route-static 10.0.23.0 24 10.0.12.2
```

| 目的网络 | 下一跳 | 出接口 |
|----------|--------|--------|
| 192.168.21.0/24 | 10.0.23.3 | GE0/0/0 |
| 10.0.23.0/24 | 10.0.12.2 | GE0/0/0 |

PC1→PC2 转发流程简述：PC1→网关 R1→查表转发 R2→R3→目的属本地网段则本地转发至 PC2。

### IP 路由高级应用：多协议共存与路由引入

OSPF 与 IS-IS 是不同动态路由协议，路由信息无法直接交互。大型企业常多种协议共存（如骨干 BGP、区域核心 IS-IS、地市 OSPF/静态），需通过**路由引入**实现全网互通。

引入时需注意收敛时间控制；更多理论与配置见后续章节。

#### 华为定义的路由优先级（Preference）

| 协议 | Preference |
|------|------------|
| Direct | 0 |
| OSPF | 10 |
| IS-IS | 15 |
| Static | 60 |
| OSPF ASE | 150 |
| OSPF NSSA | 150 |
| IBGP | 255 |
| EBGP | 255 |

不同厂商协定可能不同。

#### 路由回灌

场景：R1 将直连 `10.1.1.0/24` 引入 OSPF → OSPF 域内通告 → R2 在 IS-IS 中引入 OSPF → IS-IS 域内通告 → R3 在 OSPF 中引入 IS-IS → 路由再次进入 OSPF，形成**路由回灌**。

#### 路由引入与度量值

不同协议对度量值定义不同，引入时需明确被引入路由的 Cost 如何定义。

#### 路由引入主要场景

1. 动态路由协议之间引入
2. 引入直连路由到动态路由协议
3. 引入静态路由到动态路由协议

说明：当 OSPF 设备需访问其他协议网络时，需将其他协议路由引入 OSPF。若路由表协议字段为 `O_ASE`，表明为 OSPF 外部路由。

- 希望直连接口路由发布到动态协议：可激活接口上的动态协议，或将直连路由 `import` 进该协议。
- 静态路由对动态协议而言是域外信息；希望域内学习到，需将静态路由引入动态协议。
- 在两动态协议边界做引入，是最常见场景（如 R2 上 IS-IS ↔ OSPF 互引）。

### 思考题（IP 路由）

1. （单选）FIB 中有 `0.0.0.0/0`、`10.0.0.0/16`、`10.0.1.0/24`、`10.0.2.0/24`，目的 `10.0.1.1` 按哪条转发？→ **C. 10.0.1.0/24**（最长匹配）
2. （多选）关于路由引入错误的有？注意：`import-route` 应在**目标**路由协议视图执行；引入直连/静态不会因此激活接口上的 OSPF Hello。

### 本章要点（IP 路由）

- 到达同一目的可能有多条路由，按优先级与开销选优后放入 FIB，按 FIB 转发。
- 多协议时通过路由引入互通；引入可能带来大量路由，需路由控制按需分发。

---

## OSPF 基础

### OSPF 简介

- BGP 使用基于距离矢量修改后的**路径矢量（Path Vector）**算法；IGP 在同一 AS 内发现与计算路由；EGP 主要用于 AS 之间互联。
- 按工作区域：IGP（OSPF、IS-IS）与 EGP（BGP）。
- 按工作机制：距离矢量（如 RIP）与链路状态（OSPF、IS-IS）。

**链路状态通告**：每台路由器产生描述自身直连接口状态（开销、邻居关系等）的通告。

**SPF** 是 OSPF 核心算法，用于复杂网络中的路由优选。

链路状态路由协议四步：

1. 建立相邻路由器邻居关系
2. 邻居交互链路状态并同步 LSDB
3. 优选路径计算
4. 根据最短路径树生成路由并加载到路由表

OSPF 是 IETF 定义的基于链路状态的 IGP。IPv4 使用 OSPFv2（RFC2328）；IPv6 使用 OSPFv3（RFC2740）。

**优点：**

- 基于 SPF，以累计链路开销为选路参考
- 部分协议报文组播收发
- 支持区域划分
- 支持等价路由负载分担
- 支持报文认证

**应用场景（大型企业）：**

- 核心/汇聚部署在骨干区域 Area 0
- 接入/汇聚部署在非骨干区域
- 接入层：低成本高端口密度；汇聚层：策略连接与隔离；核心层：冗余、可靠、高速传输

### 基础术语：Router ID

- 32 位无符号整数，在 AS 中唯一标识一台 OSPF 路由器。
- 选举：手工配置（推荐）→ 无则取 Loopback 最大 IP → 再无则取物理接口最大 IP。
- 选定后若要更改需重启 OSPF 进程。
- 工程建议：规划私有网段（如 `192.168.1.0/24`），启用 OSPF 前在每台设备建 `/32` Loopback 作为 Router ID，可不发布到 OSPF。

### 基础术语：区域

- 逻辑分组，用 Area ID 标识。
- Area ID 为 32bit 非负整数，可点分十进制（如 `0.0.0.1`）或十进制（Area1）。例：`Area0.0.0.255`=Area255，`Area0.0.1.0`=Area256。

### 基础术语：度量值 Cost

- 缺省接口 Cost = `100 Mbit/s ÷ 接口带宽`（参考带宽可配）。
- 路径开销为沿途各路由器**出接口 Cost 之和**。
- 例：FE/GE 默认 Cost=1，Serial 1.544M 默认 Cost=64；R3 到 `10.0.1.1/32` 经 GE+Serial 时 Cost=1+64=65。
- 推荐按带宽**手工配置 Cost**，而非修改参考带宽。
- 规划时可使汇聚层直连链路 Cost > 接入环所有链路 Cost 之和，避免绕行。

```cli
[R4]display ip routing-table 10.0.1.1
```

> （原图：修改 Cost 前后，R4 到 `10.0.1.1/32` 由双下一跳变为单下一跳。）

### OSPF 三大表项

#### 邻居表

- 传递链路状态前需先建邻居；通过 Hello 建立。
- 查看：`display ospf peer`

```cli
<R1> display ospf peer
OSPF Process 1 with Router ID 10.0.1.1
Neighbors
 Area 0.0.0.0 interface 10.0.12.1(GigabitEthernet1/0/0)'s neighbors
 Router ID: 10.0.2.2    Address: 10.0.12.2    GR State: Normal
 State: Full  Mode:Nbr is Master  Priority: 1
 DR: 10.0.12.1  BDR: 10.0.12.2   MTU: 0
 Dead timer due in 35 sec
 Retrans timer interval: 5
 Neighbor is up for 00:00:05
 Authentication Sequence: [ 0 ]
```

#### LSDB

- 保存自己产生及从邻居收到的 LSA；Type 标识类型，AdvRouter 标识发送者。
- 查看：`display ospf lsdb`

```cli
<R1> display ospf lsdb
OSPF Process 1 with Router ID 10.0.1.1
 Link State Database
 Area: 0.0.0.0
 Type     LinkStateID   AdvRouter   Age   Len  Sequence   Metric
 Router   10.0.2.2      10.0.2.2         8000000B
 Router   10.0.1.1      10.0.1.1         80000005
 Network  10.0.12.2     10.0.2.2         80000004
```

#### OSPF 路由表

- 与全局路由表不同；含 Destination、Cost、NextHop 等。
- 查看：`display ospf routing`
- 并非所有 OSPF 路由都会进入全局路由表。

```cli
<R1> display ospf routing
OSPF Process 1 with Router ID 10.0.1.1
 Routing Tables
 Routing for Network
 Destination     Cost  Type     NextHop     AdvRouter   Area
 10.0.1.1/32     0     stub     10.0.1.1    10.0.1.1    0.0.0.0
 10.1.12.0/20    1     Transit  10.0.12.1   10.0.1.1    0.0.0.0
 10.0.2.2/32     1     stub     10.0.12.2   10.0.2.2    0.0.0.0
 Total Nets: 3 Intra Area: 3 Inter Area: 0 ASE: 0 NSSA: 0
```

### OSPF 报文格式与类型

- OSPF 报文直接 IP 封装，协议号 **89**；五种报文共用相同头部。

| Type | 报文名称 | 功能 |
|------|----------|------|
| Hello | Hello | 发现和维护邻居 |
| Database Description | DD | 交互 LSDB 摘要 |
| Link State Request | LSR | 请求特定链路状态 |
| Link State Update | LSU | 发送详细链路状态 |
| Link State Ack | LSAck | 确认 LSA |

头部重要字段：Version（OSPFv2=2）、Router ID、Area ID、Type、Packet length、Checksum、Auth Type（0 不认证 / 1 明文 / 2 MD5）、Authentication。

### OSPF 工作过程概览

1. Hello 发现邻居
2. 协商 Master/Slave，用 DD 描述 LSDB 摘要
3. 更新 LSA，同步 LSDB
4. 计算路由（各方独立完成）

邻居关系 → 邻接关系。

#### 建立邻居（Hello）

- 首个 Hello 邻居列表为空；对端匹配参数后将本端加入邻居列表再发 Hello。
- 以太网缺省组播 Hello：`224.0.0.5`（所有 OSPF）、`224.0.0.6`（DR/BDR）；不支持组播的链路可用单播。

邻居状态：

- **Down**：初始，未收到邻居信息
- **Init**：已收到 Hello，但本 Router ID 不在对方邻居列表
- **2-way**：本 Router ID 已出现在对方邻居列表中

#### 建立邻接（DD 交换要点）

- ExStart：双方发首个 DD（I=1,M=1,MS=1），Router ID 较大者成为 Master。
- Exchange：交换含 LSDB 摘要的 DD；Slave 需确认 Master 的每个 DD。
- Loading / Full：按需 LSR/LSU 后进入 Full。
- DD 中 Interface MTU：两端不等则丢弃；华为缺省未开 MTU 检查。

#### DR / BDR

- MA 分 BMA（广播多路访问，如以太网）与 NBMA（非广播多路访问，如帧中继逻辑划分）。
- DRother：既非 DR 也非 BDR。
- Waiting 时长等于 DeadTimer（默认 40s）；Waiting 内若 Hello 已带 DR/BDR 则承认现网，不重选。
- 新加入路由器无论 Router ID/优先级多高，都承认现有 DR/BDR。
- DR Down 后 BDR 升为 DR，其余优先级>0 者竞争新 BDR。
- 仅多台同时起来时才按选举规则产生 DR。

#### 网络类型

| 网络类型 | 常见链路 | 是否选举 DR | 邻接建立 |
|----------|----------|-------------|----------|
| Point-to-point | PPP、HDLC | 否 | 是 |
| Broadcast | 以太网 | 是 | DR↔BDR/DRother；BDR↔DR/DRother；DRother 之间仅邻居 |
| NBMA | 帧中继 | 是（需手工指定邻居） | — |
| P2MP | 需手工指定 | 否 | 是 |

- 网络类型由数据链路层封装自动设置；以太网缺省 Broadcast。
- 逻辑上点对点的以太网互联可改为 P2P，避免无谓 DR/BDR 选举等待：

```cli
ospf network-type { p2p | p2mp | broadcast | nbma }
```

- Loopback 缺省以 `/32` 主机路由发布；若要发布实际网段，接口网络类型需改为 NBMA 或广播型。

### OSPF 基本配置

```cli
[Huawei] ospf [ process-id ] [ router-id Router-ID ]
# 1. 启动 OSPF 进程（进程号本地概念）

[Huawei-ospf-1] area area-id
# 2. 进入区域视图

[Huawei-ospf-1-area-0.0.0.0] network network-address wildcard-mask
# 3. 区域中使能网段（接口主 IP 须在网段内且掩码长度 ≥ network 指定）

[Huawei-GigabitEthernet1/0/0] ospf enable process-id area area-id
# 4. 接口使能（优先级高于 network）

[Huawei-GigabitEthernet1/0/0] ospf dr-priority priority
# 5. DR 优先级（缺省 1）

[Huawei-GigabitEthernet1/0/0] ospf timer hello interval
# 6. Hello 间隔（P2P/Broadcast 缺省 10s；Dead=4×Hello）

[Huawei-GigabitEthernet1/0/0] ospf network-type { broadcast | nbma | p2mp | p2p }
# 7. 网络类型
```

### 配置举例

- Router ID：`10.0.x.x`（x 为路由器编号）。
- 互联地址：`10.0.xy(z).x(y/z)/24` 等规则。
- 五台路由器均在 Area 0。

```cli
[R2]ospf 1 router-id 10.0.2.2
[R2-ospf-1]area 0.0.0.0
[R2-ospf-1-area-0.0.0.0] network 10.0.12.0 0.0.0.255
[R2-ospf-1-area-0.0.0.0] network 10.0.24.2 0.0.0.0
[R2-ospf-1-area-0.0.0.0] network 10.0.35.2 0.0.0.0
```

### 配置验证（接口）

`display ospf interface all` 可查看 Hello/Dead、链路类型、MTU、DR/优先级等。

```cli
[R2]display ospf interface all
OSPF Process 1 with Router ID 10.0.2.2
 Area: 0.0.0.0
 Interface: 10.0.12.2 (GigabitEthernet0/0/0)
 Cost: 1       State: DR      Type: Broadcast    MTU: 1500  Priority: 1
 Designated Router: 10.0.12.2
 Backup Designated Router: 10.0.12.1
 Timers: HELLO 10 , Dead 40 , Poll 120 , Retransmit 5 , Transmit Delay 1

 Interface: 10.0.235.2 (GigabitEthernet0/0/1)
 Cost: 1      State: DROther Type: Broadcast  MTU: 1500  Priority: 1
 Designated Router: 10.0.235.5
 Backup Designated Router: 10.0.235.3
 Timers: HELLO 10 , Dead 40 , Poll 120 , Retransmit 5 , Transmit Delay 1

 Interface: 10.0.24.2 (Serial1/0/1) --> 10.0.24.4
 Cost: 48      State: P-2-P     Type: P2P       MTU: 1500
 Timers: HELLO 10 , Dead 40 , Poll 120 , Retransmit 5 , Transmit Delay 1
```

### 配置验证（邻居）

```cli
<R2>display ospf peer
OSPF Process 1 with Router ID 10.0.2.2
 Area 0.0.0.0 interface 10.0.12.2(GigabitEthernet0/0/0)'s neighbors
 Router ID: 10.0.1.1          Address: 10.0.12.1
 State: Full  Mode:Nbr is Slave  Priority: 1
 DR: 10.0.12.2  BDR: 10.0.12.1  MTU: 0
 Dead timer due in 28 sec
 Retrans timer interval: 5
 Neighbor is up for 00:01:31
 Authentication Sequence: [ 0 ]
 Area 0.0.0.0 interface 10.0.235.2(GigabitEthernet0/0/1)'s neighbors
 Router ID: 10.0.3.3          Address: 10.0.235.3
 State: Full  Mode:Nbr is Master  Priority: 1
 DR: 10.0.235.5  BDR: 10.0.235.3  MTU: 0
 Dead timer due in 30 sec
 Retrans timer interval: 5
 Neighbor is up for 00:01:31
 Authentication Sequence: [ 0 ]
```

`display ospf peer` 可查看邻居 Router ID、状态（Full/2-Way/Down 等）。（续见下一文档。）
