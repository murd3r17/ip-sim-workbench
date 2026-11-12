---
doc_id: "hcip-datacom-core-training-03"
title: "IS-IS基础与BGP概述"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 3
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# IS-IS基础与BGP概述

## IS-IS 开销类型与 Cost

早期 ISO10589 接口最大开销 63，类型为 **narrow**；RFC3784 扩展到 16777215，类型为 **wide**。华为缺省为 **narrow**。

| 开销类型 | 常用 TLV |
|----------|----------|
| narrow | 128 IP Internal Reachability；130 IP External Reachability；2 IS Neighbors |
| wide | 135 Extended IP Reachability（可带 sub-TLV）；22 IS Extended Neighbors |

- 与 OSPF 不同：IS-IS 缺省 Cost **不按带宽**，无论带宽缺省均为 **10**（也可按带宽自动计算）。
- 路径 Cost = 沿途链路 Cost 之和。例：R3 到 `10.0.1.1/32` 为 10+10+0=20。

开销设置优先级（高→低）：接口开销 → 全局开销 → 按带宽自动计算。

TLV 亦称 CLV（Code-Length-Value）。常见：IP Internal/External Reachability、Protocols Supported、IP Interface Address 等，出现在 IIH、LSP 中。

## 邻接与接口注意点

- 可将以太网接口模拟为点到点，建立 P2P 邻接。
- 两端地址不在同一网段时，可配置忽略 Hello 的 IP 地址检查（P2P 直接配；以太网需先模拟为 P2P）。
- 三层接口可配一个主 IP、最多 31 个从 IP（多网段共接口场景）。

## LSP 要点

- **伪节点 ID** 非零表示伪节点生成的 LSP。
- **分片号**：信息量大时生成多个 LSP 分片。
- LSP 内容可含：AREA ADDR、INTF ADDR、NBR ID（邻接）、IP-Internal（网段）等。
- 伪节点 LSP 中伪节点到各路由器 Cost 为 0。

触发新 LSP 的事件包括：邻接 Up/Down、接口 Up/Down、引入/区间 IP 路由变化、metric 变更、周期性刷新（约 15min）等。

## IS-IS 基本配置

```cli
[Huawei] isis [process-id]
# 1. 创建进程（缺省进程 1）

[Huawei-isis-1] network-entity net
# 2. 配置 NET；区域变更时可配多个 NET（最多 3，System ID 须相同）

[Huawei-isis-1] is-level { level-1 | level-1-2 | level-2 }
# 3. 全局 Level（缺省 level-1-2；运行中改级别可能重启进程）

[Huawei] interface interface-type interface-number
[Huawei-GigabitEthernet0/0/1] isis enable [ process-id ]
# 4–5. 接口使能

[Huawei-GigabitEthernet0/0/1] isis circuit-level [ level-1 | level-1-2 | level-2 ]
# 6. 接口 Level（两台 L1-2 缺省会建 L1+L2；可改只建其一）

[Huawei-GigabitEthernet0/0/1] isis circuit-type p2p
# 7. 广播口模拟 P2P（相关定时器/认证等恢复缺省；DIS 相关配置失效）

[Huawei-GigabitEthernet0/0/1] undo isis circuit-type
# 8. 恢复缺省网络类型

[Huawei-GigabitEthernet0/0/1] isis dis-priority priority [ level-1 | level-2 ]
# 9. DIS 优先级（缺省 64）
```

### 配置示例

```cli
# R1：Level-1
[R1] isis 1
[R1-isis-1] is-level level-1
[R1-isis-1] network-entity 49.0001.0010.0100.1001.00
[R1] interface gigabitethernet 0/0/0
[R1-GigabitEthernet0/0/0] isis enable 1
[R1] interface gigabitethernet 0/0/1
[R1-GigabitEthernet0/0/1] isis enable 1

# R2：Level-1-2
[R2] isis 1
[R2-isis-1] is-level level-1-2
[R2-isis-1] network-entity 49.0001.0020.0200.2002.00
[R2] interface gigabitethernet 0/0/0
[R2-GigabitEthernet0/0/0] isis enable 1
[R2] interface gigabitethernet 0/0/1
[R2-GigabitEthernet0/0/1] isis enable 1

# R4：Level-2
[R4] isis 1
[R4-isis-1] is-level level-2
[R4-isis-1] network-entity 49.0002.0040.0400.4004.00
[R4] interface gigabitethernet 0/0/0
[R4-GigabitEthernet0/0/0] isis enable 1
[R4] interface gigabitethernet 0/0/1
[R4-GigabitEthernet0/0/1] isis enable 1
[R4] interface gigabitethernet 0/0/2
[R4-GigabitEthernet0/0/2] isis enable 1
```

R1 为 L1；R2/R3 为 L1-2；R4/R5 为 L2。

### 邻居与路由验证要点

- 邻居表字段：System Id、Interface、Type（L1/L2）、PRI（DIS 优先级）等。
- L1 路由器路由表：区内明细 + 通向 L1-2 的等价缺省。
- L1-2 同时有 Level-1 与 Level-2 转发表。

### 路由泄露（L2→L1）示例

```cli
[R2] ip ip-prefix 1 permit 192.168.10.0 24
[R2] isis 1
[R2-isis-1] import-route isis level-2 into level-1 filter-policy ip-prefix 1

[R3] ip ip-prefix 1 permit 192.168.20.0 24
[R3] isis 1
[R3-isis-1] import-route isis level-2 into level-1 filter-policy ip-prefix 1
```

（Filter-policy 细节见后续课程。）

### IS-IS 认证

```cli
# 区域认证
[Huawei-isis-1] area-authentication-mode { simple | md5 | keychain | hmac-sha256 ... } [ snp-packet ... ]

# 路由域认证
[Huawei-isis-1] domain-authentication-mode { ... }

# 接口认证（Hello）
[Huawei-GigabitEthernet0/0/0] isis authentication-mode { keychain | md5 | simple } [ level-1 | level-2 ] [ send-only ]
```

对端未配认证时，`display isis error` 可见 `Bad Authentication` 计数增加。

### 思考题（IS-IS）

1. （多选）关于 OSPF 与 IS-IS？→ **A/B/C/D**（均为链路状态；集成 IS-IS 支持 CLNP+IP；OSPF Area0 为骨干；IS-IS 骨干由 L2 与 L1-2 组成）
2. （多选）关于 L1？→ **A/C/D**（仅同区域建邻接；缺省靠缺省出区域；LSDB 仅 L1 LSP）。**B 错**：L1 不与同区域的纯 L2 建邻接。

---

## BGP 概述

### 为什么需要 BGP

- IANA 负责 AS 号等分配；16bit AS 中 **64512–65534** 为私有；32bit 中 **4200000000–4294967294** 为私有。
- 随规模扩大，IGP 难管大规模网络，引入 **AS**；AS 间需合适协议传递路由 → BGP。

### BGP 特点与历史

- 基于 **TCP 179**，可达即可建会话；只传路由、不暴露 AS 内拓扑；**触发式更新**非周期更新。
- 演进：EGP → BGP-1（RFC1105）→ 路径属性（RFC1163）→ BGP-4（RFC1771，无类）→ RFC4271；IPv6 等用 MP-BGP（RFC4760）。

企业应用：分支间 BGP；企业与运营商 BGP 交互。

### BGP 定义与特征

BGP 实现 AS 间路由可达并选最佳路由的路径矢量协议。

- TCP 传输，触发式增量更新，可承载大批量前缀。
- 丰富路径属性与策略；支撑 MPLS/VPN；支持聚合与衰减提高稳定性。

运行 BGP 的路由器称 **BGP Speaker**；建立会话的双方互为 **Peer**。

### 对等体类型

| 类型 | 条件 |
|------|------|
| EBGP | 不同 AS；对等体 IP 路由可达且能建 TCP |
| IBGP | 相同 AS |

不必物理直连（基于 TCP）。双方都可能发起 TCP，最终只保留一条：比较 Open 中 BGP Identifier（Router ID），较小一方关闭本地发起的连接。

### 对等体建立过程

1. 先启动端向对端 179 发起 TCP；
2. 互发 **Open**（含 My AS、Hold Time、BGP Identifier 等）；
3. 协商成功后互发 **Keepalive**，进入 Established，并周期性 Keepalive；
4. 之后用 **Update** 通告路由。

### BGP 报文类型

五种报文共用头部：Marker(16) + Length(2) + Type(1)。

| 报文 | 作用 | 发送时机 |
|------|------|----------|
| Open | 协商参数，建对等体 | TCP 建立后 |
| Update | 发布/撤销路由 | 有路由需发或变化时 |
| Notification | 报告错误并中止 | 发现错误时 |
| Keepalive | 维持连接 | 协商成功后周期发送 |
| Route-refresh | 请求对等体重发路由 | 策略变更且双方支持时 |

#### Open 主要字段

Version、My AS、Hold Time、BGP Identifier、Optional parameters（能力协商，如多协议）。

#### Update 主要字段

Withdrawn Routes、Path Attributes（TLV）、NLRI（前缀+长度）。一个 Update 可通告多条同属性路由，也可携带多条撤销。

#### Notification / Keepalive / Route-refresh

- Notification：Error Code / Subcode / Data，随后拆链。
- Keepalive：仅报文头。
- Route-refresh：AFI/SAFI；不支持时可配 `keep-all-routes` 保留原始路由以便软刷新（缺省未开）。

### BGP 状态机

| 状态 | 含义 |
|------|------|
| Idle | 初始；收 Start 后尝试 TCP |
| Connect | 等待 TCP；失败→Active；成功发 Open→OpenSent |
| Active | 反复尝试 TCP |
| OpenSent | 已发 Open，等待对端 Open 并校验 |
| OpenConfirm | 已发 Keepalive，等待对端 Keepalive |
| Established | 可交换 Update/Keepalive/Route-refresh |

- 任意状态收到 Notification/TCP 拆链等 → Idle。
- 缺去往对等体路由是长期停在 Idle 的常见原因。
- Connect Retry 超时等行为按规范在 Connect/Active 间转换。



## IS-IS 邻居与路由表示例（详）

R4 建立 Level-2 邻接、R1 建立 Level-1 邻接时，邻居表关注字段：

- **System Id**：邻接系统 ID
- **Interface**：本端出接口
- **Type**：邻接类型（L1/L2）
- **PRI**：对应端口 DIS 优先级
- **Circuit Id / State / HoldTime**

示例（示意）：

| System Id | Interface | Circuit Id | State | HoldTime | Type |
|-----------|-----------|------------|-------|----------|------|
| 0020.0200.2002 | GE0/0/0 | 0040.0400.4004.01 | Up | 25s | L2 |
| 0050.0500.5005 | GE0/0/1 | 0050.0500.5005.01 | Up | 13s | L2 |

R1（L1）转发表示意：存在区域内明细路由，以及经 GE0/0/0、GE0/0/1 的等价缺省 `0.0.0.0/0`（下一跳分别为 `10.1.12.2`、`10.1.13.3`）。

R3（L1-2）同时存在 Level-1 与 Level-2 Forwarding Table；Flags 常见：`D` Direct、`A` Added to URT、`L` Advertised in LSPs、`U` Up/Down Bit Set。

泄露后 R1 全局路由表示意：除缺省外可见 `192.168.10.0/24`、`192.168.20.0/24` 等 ISIS-L1 路由（Pre 常见为 15）。

### LSP 内容阅读提示

伪节点 LSP 示例含义：

- `NBR ID 0100.0000.1001.00 COST: 0`：描述广播网中成员；伪节点到成员 Cost 为 0。
- 普通 LSP 中 `INTF ADDR`、`NBR ID ... COST`、`IP-Internal ... COST` 分别描述接口、邻接与网段。

### 接口认证排错

```cli
[R1] interface GigabitEthernet0/0/0
# 在 R1 的 GE0/0/0 上配置接口认证后，若 R2 未配：
[R1] display isis error
Hello packet errors:
 Mismatched Max Area Addr : 0
 Bad Authentication : 6
```

## BGP 状态机行为细节

### Idle / Connect / Active

- **Idle**：拒绝对等体连接请求；收到本机 Start 事件（配置/重置 BGP）后尝试 TCP 并转 Connect。任何状态收到 Notification 或 TCP 拆链等 Error → Idle。缺乏去往对等体路由是长期停在 Idle 的常见原因。
- **Connect**：启动 Connect Retry，等待 TCP。成功则发 Open → OpenSent；失败 → Active；重传超时仍无响应则继续尝试并留在 Connect。
- **Active**：持续尝试 TCP。成功发 Open → OpenSent；失败留在 Active；重传超时 → Connect。

### OpenSent / OpenConfirm / Established

- **OpenSent**：等待并对 Open 中 AS 号、版本、认证等检查。正确则发 Keepalive → OpenConfirm；错误则发 Notification → Idle。
- **OpenConfirm**：等待 Keepalive（→ Established）或 Notification（→ Idle）。
- **Established**：可交换 Update / Keepalive / Route-refresh / Notification。错误 Update/Keepalive → Notification 并 Idle；Route-refresh 不改变状态；Notification 或 TCP 拆链 → Idle。

### 双 TCP 连接收敛

双方都可能发起 TCP 三次握手，可能短暂存在两条连接；从 Open 取得对端 BGP Identifier 后，**Router ID 较小的一端关闭本地发起的连接**，保留对端主动发起的那条。

### Update 字段补充

- **Withdrawn Routes Length**：撤销部分长度，0 表示无撤销。
- **Total path attribute length**：路径属性长度，0 表示无 Path Attributes。
- **NLRI**：可达前缀与前缀长度二元组；同一 Update 可通告多条相同路径属性的路由。

### Route-refresh 与软复位

Open 协商支持 Route-refresh 时，可用 `refresh bgp` 做软复位，不中断连接即可按新策略重算。不支持时可配 `keep-all-routes` 保留对等体原始路由（缺省未开启）。

### BGP 报文头 Type 取值

| Type | 报文 |
|------|------|
| 1 | Open |
| 2 | Update |
| 3 | Notification |
| 4 | Keepalive |
| 5 | Route-refresh |

Marker 16 字节全 1；Length 含头部总长。


（对等体表、路由表、通告原则与基本配置见下一文档。）
