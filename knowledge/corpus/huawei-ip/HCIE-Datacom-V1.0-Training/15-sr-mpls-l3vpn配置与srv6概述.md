---
doc_id: "hcie-datacom-v1.0-training-15"
title: "SR-MPLS L3VPN配置与SRv6概述"
book: "HCIE-Datacom-V1.0-Training"
book_title: "HCIE-Datacom V1.0 培训教材"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "training"
source_pdf: "HCIE-Datacom+V1.0+培训教材.pdf"
seq: 15
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# SR-MPLS L3VPN配置与SRv6概述

本篇接续 Segment Routing 基础配置：L3VPN over SR-MPLS TE、L3VPN over 静态 SR-MPLS Policy，完结 SR-MPLS 章节后进入 SRv6 概述与原理。

课程结构回顾：

1. Segment Routing 概述
2. Segment Routing 的基本原理
3. Segment Routing 隧道保护与检测技术
4. Segment Routing 的典型应用场景
5. Segment Routing 的基础配置（SR-MPLS BE / TE / Policy）

---

## 1. L3VPN over SR-MPLS TE

### 1.1 组网需求与配置思路

组网需求：

1. PE1 和 PE2 设备各有一个 CE 属于 VPN 实例 vpna；
2. 在骨干网络中部署 L3VPN 迭代 SR-MPLS TE 隧道，使得 CE1 和 CE2 的 Loopback1 接口可以相互通信。

配置思路：

1. 完成设备接口 IP 地址及 OSPF 配置（略）；
2. 骨干网上使能 MPLS，配置 Segment Routing，建立 SR-MPLS TE LSP；
3. 在 PE1 与 PE2 之间建立 MP-BGP 对等体关系；
4. PE 上使能 VPN 实例 IPv4 地址族；
5. PE 之间配置 MP-IBGP 交换路由信息；
6. 在 PE 设备上配置隧道选择策略，优选 SR-MPLS TE；
7. 结果验证。

### 1.2 使能 MPLS TE

在 SR-MPLS 域的所有节点上使能 MPLS TE 是配置 SR-MPLS TE 隧道的首要步骤：

1. `system-view` 进入系统视图；
2. `mpls lsr-id lsr-id` 配置本节点 LSR ID；
3. `mpls` 进入 MPLS 视图，`mpls te` 全局使能本节点的 MPLS TE；
4. （可选）使能接口的 MPLS TE 能力：在控制器算路和头节点算路场景必须使能；静态显式路径场景可忽略。接口下执行 `mpls` 与 `mpls te`；
5. `commit` 提交配置。

### 1.3 显式路径配置

本例中通过指定 Prefix SID 的方式建立显式路径。显式路径由一系列节点构成，按配置的先后顺序组成一条向量路径。既可以通过显式路径中指定下一跳标签来规划 SR-MPLS TE LSP 途径路径，也可以通过指定下一跳 IP 地址来规划。显式路径中的 IP 地址一般使用接口 IP 地址。使用中的显式路径支持更新。

配置步骤：

1. `explicit-path path-name` 创建显式路径并进入显式路径视图；
2. 指定下一跳标签：`next sid label label-value type { adjacency | prefix | binding-sid }`；
3. `commit`。

### 1.4 PE1 配置示例（BGP / VPN）

```cli
[~PE1] bgp 100
[*PE1-bgp] peer 10.0.3.3 as-number 100
[*PE1-bgp] peer 10.0.3.3 connect-interface loopback 0
[*PE1-bgp] ipv4-family vpnv4
[*PE1-bgp-af-vpnv4] peer 10.0.3.3 enable
[*PE1-bgp-af-vpnv4] commit
[~PE1-bgp-af-vpnv4] quit
[~PE1-bgp] quit

[~PE1] ip vpn-instance vpna
[*PE1-vpn-instance-vpna] ipv4-family
[*PE1-vpn-instance-vpna-af-ipv4] route-distinguisher 100:1
[*PE1-vpn-instance-vpna-af-ipv4] vpn-target 111:1 both
[*PE1-vpn-instance-vpna-af-ipv4] quit
[*PE1-vpn-instance-vpna] quit

[~PE1] bgp 100
[*PE1-bgp] ipv4-family vpn-instance vpna
[*PE1-bgp-vpna] peer 10.0.14.4 as-number 65000
```

### 1.5 隧道策略配置与验证

```cli
[~PE1] tunnel-policy p2
[*PE1-tunnel-policy-p2] tunnel select-seq sr-te load-balance-number 1
[*PE1-tunnel-policy-p2] quit
[~PE1] commit

[~PE1] ip vpn-instance vpna
[*PE1-vpn-instance-vpna] ipv4-family
[*PE1-vpn-instance-vpna-af-ipv4] tnl-policy p2
[*PE1-vpn-instance-vpna-af-ipv4] quit
[*PE1-vpn-instance-vpna] quit
[~PE1] commit
```

在 PE1 上执行 `display tunnel-info all`，可看到到达 PE2 的 SR-TE 隧道状态为 UP（示例 Tunnel ID：`0x000000000300000001`，Type：`sr-te`，Destination：`10.0.3.3`）。

查看 vpna 路由 verbose 信息时，出接口应为 Tunnel 接口（如 `Interface: Tunnel1`），表示将 VPNv4 标签和 SR-TE LSP 结合指导数据包转发。

使用 `tracert lsp segment-routing te Tunnel 1` 跟踪 SR LSP，并在 CE1 上 ping 验证互通。

---

## 2. L3VPN over 静态 SR-MPLS Policy

### 2.1 组网需求与配置思路

组网需求：

1. PE1 和 PE2 设备各有一个 CE 属于 VPN 实例 vpna；
2. 在骨干网络中部署 L3VPN 迭代静态 SR-MPLS Policy，使得 CE1 和 CE2 的 Loopback1 接口可以相互通信。

配置思路：

1. 完成设备接口 IP 地址及 OSPF 配置（略）；
2. 骨干网上使能 MPLS，配置 SR-MPLS Policy；
3. 在 PE1 与 PE2 之间建立 MP-BGP 对等体关系；
4. PE 上使能 VPN 实例 IPv4 地址族；
5. 在 PE 设备为路由配置扩展团体属性 Color，并交换路由信息；
6. 在 PE 设备上配置隧道选择策略；
7. 结果验证。

本例中使用静态方式配置 Adjacency SID。

### 2.2 SR-MPLS Policy 配置要点

SR-MPLS Policy 用来引导流量通过 SR-MPLS TE 网络。每个 SR-MPLS Policy 可以有多个候选路径，每个候选路径有不同的优先级：优先级最高的有效候选路径作为主路径，优先级次高有效候选路径作为备份路径。

配置 Segment List：

1. `segment-routing` 使能全局 SR 能力并进入 Segment Routing 视图；
2. `segment-list list-name` 创建 SR-MPLS TE 候选路径的显式标签路径；
3. `index index sid label label` 配置 Segment List 中指定下一跳标签。

### 2.3 路由着色（Color）

通过路由策略对路由增加扩展团体属性 Color，携带 Color 的路由可以根据 Color 与下一跳地址迭代 SR-MPLS Policy。

配置 Route-Policy：

1. `route-policy route-policy-name { deny | permit } node node` 创建路由策略；
2. 配置 If-match 过滤条件（可选）；
3. `apply extcommunity color color` 配置 BGP 扩展团体属性 Color；
4. `commit`。

### 2.4 隧道策略与验证

```cli
[~PE1] tunnel-policy p3
[*PE1-tunnel-policy-p3] tunnel select-seq sr-te-policy load-balance-number 1 unmix
[*PE1-tunnel-policy-p3] quit
[~PE1] commit

[~PE1] ip vpn-instance vpna
[*PE1-vpn-instance-vpna] ipv4-family
[*PE1-vpn-instance-vpna-af-ipv4] tnl-policy p3
[*PE1-vpn-instance-vpna-af-ipv4] quit
[*PE1-vpn-instance-vpna] quit
[~PE1] commit
```

`display tunnel-info all` 中可见 `srtepolicy` 类型隧道 UP。查看私网路由 verbose 时，出接口可显示为 Policy（如 `Interface: policy100`），表示将 VPNv4 标签和 SR-TE Policy LSP 结合指导转发。

使用 Tracert 跟踪 SR-TE Policy 的 Segment List，并在 CE1 上 ping 验证。

---

## 3. 思考题与本章总结（SR-MPLS）

### 思考题

1. （单选题）OSPF 通过以下哪种类型的 LSA 来携带 Node SID？
   - A. Type 1
   - B. Type 2
   - C. Type 7
   - D. Type 10
2. （多选题）缺省情况下，SBFD 报文使用以下哪些端口？
   - A. 4784
   - B. 3784
   - C. 6784
   - D. 7784

参考答案：1. D；2. A、D

### 本章总结

- SR 是基于源路由理念而设计的在网络上转发数据包的一种架构。SR-MPLS 相比于 LDP 和 RSVP-TE，简化了 MPLS 网络的控制平面，仅通过 IGP 协议扩展即可携带标签等相关信息；中间节点不需要维护路径信息，扩展能力更强；通过源节点即可控制数据包转发路径。配合集中算路模块，可灵活简便地实现路径控制与调整，更好向 SDN 平滑演进。
- SR-MPLS 支持三种不同类型的 LSP：SR-MPLS BE、SR-MPLS TE、SR-MPLS Policy。针对不同类型的 LSP，可提供多种检测和保护机制，例如 TI-LFA FRR 与 Anycast FRR、Hot-Standby、VPN FRR、防微环、BFD 与 SBFD。
- SR-MPLS 同时支持传统网络和 SDN 网络，兼容现有设备，支持跨域对接等多种场景。本课程给出了基于命令行配置 SR-MPLS 的举例；后续课程将介绍如何使用控制器完成 SR-MPLS 的配置。

---

## 4. SRv6 概述（新章节开始）

### 前言

Segment Routing 架构设计之初，就为数据平面设计了两种实现方式：一种是 SR-MPLS，其复用了 MPLS 数据平面，可以在现有 IP/MPLS 网络上增量部署；另一种是 SRv6，使用 IPv6 数据平面，基于 IPv6 路由扩展头进行扩展。本文将介绍 SRv6 的概念与原理和基于华为 NetEngine 系列路由器的应用。

### 学习目标

学完本课程后，您将能够：

- 描述 SRv6 的产生背景；
- 描述 SRv6 的技术优势；
- 描述 SRv6 的基本概念与技术原理；
- 描述 SRv6 高可靠性的概念与技术原理；
- 描述 SRv6 BE 与静态 SRv6 Policy 配置；
- 描述基于 iMaster NCE-IP 部署 SRv6。

### 课程内容

1. SRv6 概述
2. SRv6 原理
3. SRv6 高可靠性
4. SRv6 基础配置
5. 基于 iMaster NCE-IP 部署 SRv6

### 4.1 从 ATM/IP 竞争到 IP/MPLS

在网络发展初期，为满足不同业务需求存在着不同网络形态（X.25、FR、ATM、IP）。ATM 采用固定长度信元、面向连接，可提供更好的 QoS，设计哲学是“以网络为中心，提供可靠传输”；IP 是无连接、尽力而为，报文长度不固定，依靠 TCP 保证可靠性，体现“以端为中心，尽力而为”。随着网络规模扩大、业务变多，ATM 的复杂度和管理成本高于 IP，逐渐被 IP 取代。

为弥补 IP 网络 QoS 不足，业界提出过 LANE、IPoA 等融合技术，直到 1996 年 MPLS 的出现更好解决此问题。

**IP/MPLS 网络简介**：MPLS 是介于二层和三层之间的 2.5 层技术，为面向无连接的 IP 网络增加了面向连接的属性。早期 MPLS 标签转发能提高转发效率；随着硬件能力提升此优点已不明显，但面向连接的标签转发为 IP 网络提供很好的 QoS 保障，同时可很好支持 TE、VPN 和 FRR。IP/MPLS 网络最终应用于骨干网、城域网、移动承载网等多种场景，支持多业务综合承载，实现互联网的 ALL IP 化。

### 4.2 MPLS LDP 与 RSVP-TE 存在的问题

**LDP**：

- 本身并无算路能力，需依赖 IGP 进行路径计算；
- 控制面需要 IGP 及 LDP，设备之间需要发送大量消息维持邻居关系及路径状态；
- 若 LDP 与 IGP 未同步，则可能出现数据转发问题。

**RSVP-TE**：

- 配置复杂，不支持负载分担；
- 为了实现 TE，设备之间需要发送大量 RSVP 报文维持邻居关系及路径状态；
- 本质上是分布式架构，每台设备只知道自己的状态，设备之间需要交互信令报文。

本质上 MPLS 仅是指导数据转发的隧道技术，有完整的隧道创建、管理和维护机制——这些是从网络运营和管理角度驱动的需求，不是由应用驱动网络需求。

### 4.3 SR 的起源与解决方案

SDN 概念提出后，业界出现诸多实现协议（OpenFlow、POF、P4、Segment Routing）。相比革命性协议，Segment Routing 同时考虑对现网的兼容、平滑演进和可编程能力，是事实上的 SDN 标准。

SR 有两种解决方案：基于 MPLS 转发的 SR-MPLS，以及基于 IPv6 转发的 SRv6。

| 对比 | SRv6 | SR-MPLS |
| --- | --- | --- |
| 特点 | 基于 IPv6 路由扩展头进行扩展 | 在现有 IP/MPLS 网络上增量部署 |

相对 LDP/RSVP-TE：SR 提供路径规划能力、配置相对简单、可负载分担；简化协议数量，减轻与 IGP 同步问题。

### 4.4 从 MPLS 到 SRv6

MPLS 虽然在 ALL IP 化中发挥重要作用，但也带来网络孤岛问题：增加跨域互通复杂性（如 MPLS VPN Option A/B/C）；云数据中心增多后 Overlay（如 VXLAN）兴起，MPLS 进入数据中心尝试因边界多、复杂度高、扩展性不足而失败。典型用户访问数据中心流量可能经历 VLAN、IP、IP/MPLS 与 VXLAN 多种网络。

MPLS 与 Segment Routing 结合初衷是为网络提供可编程能力，但受限于 MPLS 封装可扩展性不足，无法很好满足 SFC 和 IOAM 等需要携带元数据的业务需求。IPv6 与 SR 结合带来新机遇——SRv6。

演进路径概览：

| 阶段 | 控制面 | 转发面 |
| --- | --- | --- |
| Classic MPLS | LDP / RSVP-TE | Push / Swap / Pop |
| SR-MPLS | IGP + SR extension | Push / Continue / Next |
| SRv6 | IGP + SR extension | IPv6 + SRH |

SRv6 统一转发平面，同时拥有简化协议、高扩展性和可编程等优势。

### 4.5 SRv6 的技术价值

SRv6 技术本身可以简化现有网络协议、降低网络管理复杂度；更核心的优势是 Native IPv6 特质与网络编程能力。

- 基于 Native IPv6 特质：更好促进云网融合、兼容存量网络、提升跨域体验；
- 基于网络编程能力：更好地进行路径编程，满足业务 SLA，同时还能将网络和应用连接起来，构建智能云网。

---

## 5. SRv6 原理：基本概念

SRv6 原理章节结构：

- SRv6 基本概念
- SRv6 Policy 路径建立与引流
- SRv6 典型用例

### 5.1 SRv6 原理简介

SRv6 在头节点上对数据压入段路由扩展报文头（SRH，Segment Routing Header）来指导数据转发。SRv6 报文没有改变原有 IPv6 报文的封装结构，仍旧是 IPv6 报文，普通 IPv6 设备也可以识别，所以说 SRv6 是 Native IPv6 技术。该特质使得 SRv6 设备能够和普通 IPv6 设备共同组网，对现有网络具有更好的兼容性。

### 5.2 IPv6 SRH 介绍

RFC 8754 定义 IPv6 SRH 扩展头标准。Routing Extension Header 的 Routing Type 建议值为 4，表明是 SR Header（SRH）。Next Header=43 表明是 Routing Extension Header。

SRH 扩展头主要包含：

- **Segment List**：有序的 SRv6 SID 列表；
- **Segments Left (SL)**：SRv6 激活的 SID 为 `Slist[SL]`。转发过程中通过修改 SL，同时更换 DIP 为活跃 SID 来分段完成转发；
- **Tag**：用于对数据包分组，可实现基于组的策略；
- **SRH TLVs**（NSH metadata、HMAC TLV、Padding TLV 等）：可作为与 Segment List 的 SID 共同使用的全局参数。

SRv6 与 SR-MPLS 最大区别在于 IPv6 SRH。更多详情见 [RFC 8754](https://datatracker.ietf.org/doc/rfc8754)。

### 5.3 SRv6 Segment（SID）结构

SRv6 Segment 是 IPv6 地址形式，通常也称为 SRv6 SID。SID 由 Locator、Function 和 Arguments 三部分组成，格式为 `Locator:Function:Arguments`，注意 `Length(L+F+A) <= 128`。当长度和小于 128 时，保留位用 0 补齐。若没有 Arguments 字段，格式则是 `Locator:Function`。Locator 占据 IPv6 地址的高比特位，Function 部分占据剩余部分。

#### Locator

Locator 是网络拓扑中一个网络节点的标识，用于路由和转发报文到该节点，实现网络指令的可寻址。Locator 具有可路由和可聚合两个重要属性。节点配置 Locator 之后，系统会生成一条 Locator 网段路由，并通过 IGP 在 SR 域内扩散。网络内其他节点通过 Locator 网段路由就可以定位到本节点，同时本节点发布的所有 SRv6 SID 也都可以通过该条 Locator 网段路由到达。

华为设备配置示例（前缀 `2001:DB8:ABCD::`，长度 64 bit）：

```cli
[Huawei] segment-routing ipv6
[Huawei-segment-routing-ipv6] locator srv6_locator1 ipv6-prefix 2001:DB8:ABCD:: 64
```

Locator 具有定位功能，一般要在 SR 域内唯一。在一些特殊场景（如 Anycast 保护）中，多个设备可能配置相同的 Locator。

#### Function & Arguments

Function 用来标识该指令要执行的转发动作。在 SRv6 网络编程中，不同的转发行为由不同的 Function 标识，例如 RFC 中定义了公认的 End、End.X、End.DX4、End.DX6 等。

End.X 类似 SR-MPLS 中的 Adjacency SID，用于标识某条链路：

```cli
[Huawei-segment-routing-ipv6] locator srv6_locator1 ipv6-prefix 2001:DB8:ABCD:: 64
[Huawei-segment-routing-ipv6] opcode ::1 end-x interface G3/0/0 next-hop 2001:DB8:200::1
```

此 Function 对应的 opcode 为 `::1`，此时没有 Arguments，则 SRv6 SID 值为 `2001:db8:abcd::1`。行为表示将报文从指定接口（G3/0/0）转发给对应邻居节点。

在一些场景下，一个 SRv6 Endpoint 可以要求额外动作，此时需要 Arguments 字段一起被封装。例如在 EVPN VPLS 的 CE 多归场景转发 BUM 流量时，Function 字段为 End.DT2M，Arguments 字段用于提供本地对于 ESI 的映射以实现水平分割。Function 和 Arguments 都可由工程师定义，这也反映出 SRv6 SID 结构更有利于网络编程。多数场景下不配置 Arguments。

### 5.4 SRv6 Segment 类型

| 类型 | 功能描述 | 发布协议 | 类别 |
| --- | --- | --- | --- |
| End | Endpoint SID，标识某个目的节点（Node）。转发动作：更新 IPv6 DA，查找 IPv6 FIB 转发 | IGP | 路径 SID |
| End.X | 三层交叉连接 Endpoint SID，标识某条链路。转发动作：更新 IPv6 DA，从绑定出接口转发 | IGP | 路径 SID |
| End.DT4 | PE 类型 Endpoint SID，标识某个 IPv4 VPN 实例。解封装后查找 IPv4 VPN 实例路由表转发；等价于 IPv4 VPN 标签 | BGP | 业务 SID |
| End.DT6 | PE 类型 Endpoint SID，标识某个 IPv6 VPN 实例；等价于 IPv6 VPN 标签 | BGP | 业务 SID |
| End.DX4 | PE 类型三层交叉连接 Endpoint SID，标识某个 IPv4 CE；解封装后在绑定的三层接口转发；等价于连接到 CE 的邻接标签 | BGP | 业务 SID |
| End.DX6 | PE 类型三层交叉连接 Endpoint SID，标识某个 IPv6 CE | BGP | 业务 SID |

L2 VPN 相关 SID：

- **End.DX2**：二层交叉连接 Endpoint SID；若存在 Bypass 隧道会自动生成 End.DX2L。解封装后将剩余报文转发到 SID 对应出接口。可用于 EVPN VPWS。
- **End.DT2U**：二层交叉连接且进行单播 MAC 表查找；若存在 Bypass 隧道会自动生成 End.DT2UL。可用于 EVPN VPLS 单播。
- **End.DT2M**：二层交叉连接且进行广播泛洪；去掉 IPv6 头及扩展头后在 BD 内广播。可用于 EVPN VPLS BUM。

运维相关：

- **End.OP**（OAM Endpoint with Punt）：对 OAM 报文实现上送操作，主要用于 Ping/Tracert 场景。

### 5.5 SRv6 Segment 命名规则

可从命名组合中快速判断指令功能：

- **End**：最基础的 Segment Endpoint 执行指令，中止当前指令并开始执行下一个指令（SL−1，并将 SL 指向的 SID 复制到 IPv6 目的地址）；
- **X**：指定一个或一组三层接口转发报文；
- **T**：查询路由表并转发报文；
- **D**：解封装（移除 IPv6 报文头及相关扩展头）；
- **V**：根据 VLAN 查表转发；
- **U**：根据单播 MAC 查表转发；
- **M**：查询二层转发表进行组播转发；
- **B6**：应用指定的 SRv6 Policy；
- **BM**：应用指定的 SR-MPLS Policy。

### 5.6 SRv6 Segment 举例

- End SID 类似 SR-MPLS 中的 Node SID：通过 IGP 扩散，全局可见、本地有效。
- End.X SID 类似 Adjacency SID：通过 IGP 扩散，全局可见、本地有效。
- End.DT4 SID 在 L3VPNv4 场景使用，等价于 IPv4 VPN 标签；可通过静态配置生成，也可通过 BGP 在 Locator 的动态 SID 范围内自动分配。

> （原图：PE1/P/PE2 及 CE1/CE2 上 End / End.X / End.DT4 SID 分配示例）

### 5.7 SRv6 Flavors 附加行为

Flavors 是为增强 SRv6 Segment 而定义的附加行为（可选项）。Segment Routing over IPv6 (SRv6) Network Programming 中定义了：

| 附加行为 | 功能描述 | 附着的 End 指令 |
| --- | --- | --- |
| PSP | 在倒数第二个 Endpoint 节点执行移除 SRH 操作 | End、End.X、End.DT2、End.DT4、End.DT6 |
| USP | 在最后一个 Endpoint 节点执行移除 SRH 操作 | 同上 |
| USD | 在最后一个 Endpoint 节点执行解封装外层 IPv6 报文头操作 | 同上 |

Flavors 可以组合定义。例如 End SID 带上 PSP 和 USP：在倒数第二个节点执行 PSP，在倒数第一个节点执行 USP/USD 相关动作。

### 5.8 SRv6 Locator / SID 配置命令

`static static-length`：指定静态段长度，决定能在该 Locator 下配置多少静态 Opcode。  
`args args-length`：指定参数段长度；参数段在 SID 最末端预留，静态或动态 SID 不会占用该段。

```cli
[Huawei] segment-routing ipv6
```

使能 SRv6 功能并进入 SRv6 视图后，可配置 Locator 和 SRv6 SID，以生成 SRv6 Local SID 转发表项。

```cli
[Huawei-segment-routing-ipv6] locator locator-name [ ipv6-prefix ipv6-address prefix-length [ [ static static-length ] | [ args args-length ] ] * ]
```

SRv6 SID 是 IPv6 地址形式，总计 128 位，格式为 `Locator:Function:Args`：

- Locator 字段对应 `ipv6-prefix`，长度由 `prefix-length` 决定；
- Function 字段也称为 Opcode，可通过 IGP 动态分配，也可通过 `opcode` 命令静态配置。配置 Locator 时可通过 `static static-length` 指定静态段长度；IGP 动态分配 Opcode 时会在静态段范围外申请，确保最终构成的 SRv6 SID 不会冲突；
- Args 字段由 `args args-length` 决定，可选。

配置静态 End / End.X SID：

```cli
[Huawei-segment-routing-ipv6-locator] opcode func-opcode end [no-flavor | psp | psp-usp-usd ]
[Huawei-segment-routing-ipv6-locator] opcode func-opcode end-x interface {interface-name | interface-type interface-number} nexthop nexthop-address [no-flavor | psp | psp-usp-usd]
```

End SID 标识一个 SRv6 节点；End.X SID 全称为 Layer-3 cross-connect，表示 SRv6 节点的三层邻接，需指定接口和接口下一跳地址。
