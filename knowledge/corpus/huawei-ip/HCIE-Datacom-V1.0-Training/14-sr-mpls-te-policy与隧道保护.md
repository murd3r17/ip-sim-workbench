---
doc_id: "hcie-datacom-v1.0-training-14"
title: "SR-MPLS TE/Policy、隧道保护与L3VPN over SR-MPLS BE"
book: "HCIE-Datacom-V1.0-Training"
book_title: "HCIE-Datacom V1.0 培训教材"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "training"
source_pdf: "HCIE-Datacom+V1.0+培训教材.pdf"
seq: 14
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# SR-MPLS TE/Policy、隧道保护与L3VPN over SR-MPLS BE

## 1. SR-MPLS TE

SR-MPLS TE 使用多个 SID 进行组合来指导数据转发，这种工作机制可以对数据的转发路径进行一定约束，从而满足流量工程的需求，因此被称为 SR-MPLS TE（Traffic Engineering）。

SID 的组合形式：

- 使用多个 Node SID；
- 使用多个 Adjacency SID；
- 使用 Node SID 与 Adjacency SID 组合。

## 2. SR-MPLS BE LSP

SR-MPLS BE LSP 是指使用 SR 技术建立的标签转发路径，由一个 Prefix 或 Node Segment 指导数据包转发。其中，SR-MPLS BE 是指 IGP 使用最短路径算法计算得到的最优 SR LSP。

SR-MPLS BE LSP 的创建过程和数据转发与 LDP LSP 类似。这种 LSP 不存在 Tunnel 接口。

### 2.1 SR-MPLS BE LSP 的创建

LSP 创建需要完成以下动作：网络拓扑上报（仅在基于控制器创建 LSP 时需要）/标签分配、路径计算。

对于 SR-MPLS BE LSP，主要基于前缀标签创建。目的节点通过 IGP 协议发布 Prefix SID，转发器解析 Prefix SID，并根据自己的 SRGB 计算标签值。此后各节点使用 IGP 协议收集的拓扑信息，根据最短路径算法计算标签转发路径，并将计算的下一跳及出标签（Outer Label）信息下发转发表，指导数据报文转发。

示例（各节点 SRGB 不同时的标签计算）：

| 节点 | SRGB 示例 | Prefix Index=100 时的入站 Label |
| --- | --- | --- |
| R1 | 20000–65535 | 20100 |
| R2 | 30000–65535 | 30100 |
| R3 | 40000–65535 | 40100 |
| R4 | 50000–65535 | 50100 |

### 2.2 数据转发过程

- **Push（压入）**：当报文进入 LSP 时，入节点设备在报文二层首部和 IP 首部之间插入一个标签；或者根据需要在报文标签栈的栈顶增加一个新的标签。
- **Swap（置换）**：当报文在 SR 域内转发时，根据标签转发表，用下一跳分配的标签替换 SR 报文的栈顶标签。
- **Pop（弹出）**：当报文在离开 SR 域时，根据栈顶的标签查找转发出接口，然后将 SR 报文的栈顶标签剥掉。

## 3. 流量工程与传统分布式 MPLS TE

### 3.1 流量工程简介

流量工程（TE，Traffic Engineering）是最重要的网络业务之一。历史上流行的 TE 技术是基于 MPLS 的，被称为 MPLS TE。它可以精确控制流量流经的路径，从而充分地利用现有带宽资源。

典型能力：路径规划（不同业务规划不同路径）、流量调优（重大事件导致流量不均衡时，将流量均衡分配至空载链路）、故障保护（设备或链路故障后的快速切换保护）。

### 3.2 传统分布式 MPLS TE 功能架构

传统 MPLS TE 采用分布式方法，由头节点根据路径约束计算路径，然后通过 RSVP-TE 信令建立基于约束的 LSP。由 MPLS 节点维护完整的 TE 功能架构，有以下四大组件：

1. **信息发布组件**：扩展 IS-IS/OSPF 携带 TE 信息，在域内泛洪 IGP 和 TE 信息，生成 TEDB；
2. **路径选择/计算组件**：通过 CSPF 算法，基于 TEDB 信息计算满足约束的路径；
3. **信令组件**：使用 RSVP-TE 建立 LSP；
4. **报文转发组件**：基于 MPLS 标签转发数据。

## 4. 集中式 SR-MPLS TE 功能架构

SR-MPLS TE（Segment Routing-MPLS Traffic Engineering）是使用 SR 作为控制协议的一种新型 TE 隧道技术。SR-MPLS TE 支持采用集中式架构：控制器收集全局网络拓扑信息和 TE 信息，集中算路，然后把算路结果下发给网络设备。也支持使用手工方式配置。

集中式流程：

1. 扩展 IS-IS/OSPF 携带 TE 信息，在域内泛洪 IGP 和 TE 信息，生成 TEDB；
2. 通过 BGP-LS 收集网络信息，建立全局 TE 数据库；
3. 控制器基于约束全局算路；
4. 使用 PCEP 或 BGP SR Policy 将算路结果下发设备；
5. 报文转发组件基于标签栈转发。

### 4.1 SR-MPLS TE 与 RSVP-TE 的比较

| 比较项 | SR-MPLS TE | RSVP-TE |
| --- | --- | --- |
| 标签分配 | 通过对 IGP 协议扩展进行标签分配和扩散。每条链路仅分配一个标签，所有 LSP 共用这一个标签，减少标签资源占用，减轻标签转发表维护工作量 | 通过对 RSVP 协议扩展进行标签分配和扩散。每条 LSP 分配一个标签；多条 LSP 时同一链路需分配多个标签，维护工作量大 |
| 控制平面 | 信令控制协议为 IGP 协议扩展，减少协议数量 | 需要 RSVP-TE 作为 MPLS 的控制协议，控制平面较复杂 |
| 可扩展性 | 网络中间设备不感知隧道，隧道信息携带在每个报文中，无需维护隧道状态信息，只需维护转发表项，可扩展性强 | 需要维护隧道状态信息与转发表项，可扩展性差 |
| 路径调整和控制 | 中间设备不感知隧道，仅通过对入节点报文进行标签操作即可任意控制业务路径，无需逐节点下发配置。节点故障时由控制器重算并更新入节点标签栈即可完成路径调整 | 无论是正常业务调整还是故障场景的被动路径调整，都需逐节点下发配置 |

补充：

- 对于使能了 SR 能力的 IGP，会为所有使能 IGP 协议的出接口分配 SR 邻接标签；邻接标签通过 IGP 泛洪到整个网络中。
- 在华为早期解决方案中，也可以使用 IGP 收集网络拓扑。由于 IGP 具有域的限制，当前主要采用 BGP-LS。

## 5. SR-MPLS TE 标签分配与隧道建立

### 5.1 标签分配

SR-MPLS TE 方案中由转发器的 IGP 协议分配标签，并通过 BGP-LS 将分配的标签上报给控制器。SR-MPLS TE 主要使用邻接标签，也可以使用节点标签。邻接标签是源节点分配的，只在本地有效，并且具有一定的方向性。

标签分配过程示例（以 R4 为例）：

1. 在设备上分别使能 IGP SR 能力。对于使能了 SR 能力的 IGP 实例，会对所有使能 IGP 协议的出接口分配 SR 邻接标签；邻接标签通过 IGP 的 SR 协议扩展泛洪到整个网络。
2. R4 的 IGP 协议为其邻接分配本地动态标签。例如为邻接 R4→R5 分配邻接标签 1045。
3. R4 的 IGP 协议发布邻接标签，泛洪到整个网络。
4. R4 上生成邻接标签对应的标签转发表。
5. 网络中的其它设备的 IGP 协议学习到 R4 发布的邻接标签，但是不生成标签转发表。
6. 其他设备按同样方式分配和发布邻接标签，生成标签转发表。BGP-LS 将带有 SR 标签信息的网络拓扑和 TE 信息上报给控制器。

在 SR-MPLS TE 隧道创建之前，需要在各转发器之间建立 IS-IS/OSPF 邻居关系，实现网络层互通，完成标签分配以及网络拓扑信息收集，并将标签和网络拓扑信息上送给控制器，供控制器进行路径计算。如果没有控制器，也可以在 SR-MPLS TE 隧道的头节点使能 CSPF 算路功能，由转发器使用 CSPF 完成路径计算。

在转发器上配置 SR-MPLS TE 隧道的方式除了手工配置显式路径外，也可以使用头节点算路功能。

### 5.2 控制器算路的隧道建立过程

当配置了某种业务（例如 VPN 业务）时，该业务需要绑定到 SR-MPLS TE 隧道，将按照以下过程建立：

1. 控制器基于 SR-MPLS TE 的隧道约束属性，通过路径计算单元 PCE（Path Computation Element）进行类似普通 TE 的路径计算，生成一个标签栈（即算路结果）。
2. 控制器通过 NETCONF 将隧道配置信息下发给转发器、通过 PCEP 将标签栈下发给转发器。
3. 转发器根据控制器下发的隧道配置和标签栈信息建立 SR-MPLS TE 隧道 LSP。

协议分工：

- **BGP-LS**：转发器上报标签和网络拓扑信息；
- **PCEP**：控制器下发标签栈；转发器上报 LSP 状态；
- **NETCONF**：控制器下发隧道配置。

基于控制器的 SR-MPLS TE 隧道建立的优势：

- 支持带宽计算与资源预留；
- 可以站在全局视角计算最优路径；
- 控制器可以与应用配合，由应用提出网络诉求，控制器计算满足诉求的转发路径，实现业务驱动网络；
- 省去大量手工配置，适合大规模网络。

### 5.3 SR-MPLS TE 数据转发

转发器上根据 SR-MPLS TE 隧道 LSP 对应的标签栈，对报文进行标签操作，并根据栈顶标签逐跳查找转发出接口，指导数据报文转发到隧道目的地址。主要分为：

- **基于邻接标签转发**（严格路径）：标签栈严格确定转发路径，不支持负载分担；
- **基于节点+邻接标签转发**（松散路径）：设备在处理节点标签时，可以按最短路径转发，也可以负载分担，路径并不是严格固定。

当前主流方案是基于邻接标签的严格路径转发。

## 6. SR-MPLS BE 与 SR-MPLS TE 的流量导入

流量导入：SR 隧道建立完成后，需将业务流量引入到 SR 隧道。

**SR-MPLS BE（没有隧道接口）引流方式**：

- 隧道策略：按照隧道的优先级顺序选择 SR-BE 隧道；
- 静态路由：将静态路由的下一跳指定为 SR-BE 隧道的目的地址，根据下一跳地址迭代到 SR-BE 隧道；
- 根据路由下一跳迭代：BGP 等公网路由可以根据路由的下一跳迭代到 SR-BE 隧道。

**SR-MPLS TE（隧道接口）引流方式**：

- 隧道策略：按照隧道的优先级顺序选择 SR-TE 隧道；
- 静态路由：配置静态路由时，将路由的出接口指定为 SR-TE 隧道的接口；
- 自动路由：将 SR-TE 隧道当做逻辑链路参与 IGP 路由计算；
- 策略路由：在策略路由的执行语句中，使用 SR-TE 隧道接口作为出接口。

## 7. 早期 SR-MPLS TE 不足与 SR Policy

### 7.1 早期 SR-MPLS TE 不足

早期的 SR-MPLS TE 沿用 RSVP-TE 的“隧道接口”概念，采用隧道接口实现 SR。示例配置：

```cli
[R1] interface tunnel1
[R1-Tunnel1] ip address unnumbered interface LoopBack0
[R1-Tunnel1] tunnel-protocol mpls te
[R1-Tunnel1] destination 3.3.3.3
[R1-Tunnel1] mpls te tunnel-id 1
[R1-Tunnel1] mpls te signal-protocol segment-routing
```

### 7.2 SR Policy 简介

SR Policy 使用段列表（Segment List）指定转发路径，但是抛弃了隧道接口的概念。SR Policy 根据 Segment 不同分为 SR-MPLS Policy 和 SRv6 Policy。本文将介绍 SR-MPLS Policy。

控制器基于代表业务 SLA 的 Color 属性计算路径，并将结果下发转发器构成 SR-MPLS Policy 隧道。网络头端节点通过业务路由的 Color 团体属性和下一跳信息匹配到对应的 SR-MPLS Policy 隧道进行业务转发。

```cli
<PE1> display tunnel-info all
Tunnel ID                 Type         Destination     Status
0x0000000001004c4c04      ldp          1.0.0.12        UP
0x000000002900000004      srbe-lsp     1.0.0.12        UP
0x000000000300002001      sr-te        1.0.0.12        UP
0x000000003400002001      srv6tepolicy FC01:12         UP
```

### 7.3 SR-MPLS Policy 元组标识

一个 SR-MPLS Policy 由一个元组标识 `<headend, color, endpoint>`。对于一个指定的节点，SR-MPLS Policy 则由 `<color, endpoint>` 标识：

- **头端（headend）**：SR-MPLS Policy 生成的节点，一般是全局唯一的 IP 地址；
- **颜色（color）**：32 比特扩展团体属性，用于标识某一种业务意图（例如低延时）；
- **尾端（endpoint）**：SR-MPLS Policy 的目的地址，一般是全局唯一的 IP 地址。

Color 和 endpoint 被用于在特定头端标识转发路径。

### 7.4 SR Policy 实现方式

主流有三种方式：

- **BGP**：BGP-LS 用于收集拓扑，对于客户自研控制器无需引入新的接口协议；BGP SR Policy 下发路径路由信息。
- **PCEP**：在 SR-MPLS TE 场景下较为成熟，但由于各厂家隧道实现模型不统一，无法实现互通，且 PCEP 交互流程较于 BGP 更复杂，推荐使用 BGP 扩展协议。
- **NETCONF/YANG**：把隧道路径作为配置下发到转发器。本质上是配置下发，性能最差，不推荐。在整体解决方案中使用 NETCONF 下发其他配置，而不是隧道配置。

更详细的 SR Policy 细节见 [I-D.ietf-spring-segment-routing-policy](https://datatracker.ietf.org/doc/draft-ietf-idr-segment-routing-te-policy/)。

**BGP-LS 连接**：

- 收集隧道拓扑信息，用于计算 SR Policy 路径；
- BGP-LS 协议扩展支持收集 SR Policy 状态信息，用于控制器实现隧道状态呈现（见 [draft-ietf-idr-te-lsp-distribution](https://datatracker.ietf.org/doc/draft-ietf-idr-te-lsp-distribution/)）；
- BGP-LS 协议扩展支持 SRLB 信息封装和解封装，用于控制器获取 SRLB 信息以分配 BSID（每一条 SR-Policy 隧道的备份路径都对应一个 Binding SID）。

**BGP SR Policy 连接**：

- 控制器向转发器下发 SR Policy 信息，生成 SR Policy 隧道；
- 控制器下发 BGP 路由携带 Color 团体属性，并支持此属性传递。隧道头端节点匹配 BGP 路由后基于 Color+Endpoint 方式迭代到 SR Policy 隧道；
- 需要在控制器根据业务 SLA 要求统一规划各个应用的网络隧道算路约束，并通过不同的 color 来标识。根据 `{头节点，尾节点，COLOR}` 来唯一确定一个 SR Policy 隧道。业务报文迭代隧道时其 BGP 路由需要携带对应的 color 扩展团体属性。

**候选路径与 BSID**：

- 一个 SR Policy 可以有多个候选路径（如 CP1、CP2），每个路径由三元组 `<protocol, origin, discriminator>` 唯一确定。
- CP1 是激活路径（合法且优先级高）。CP1 的多个 SID-List 可下发到转发器，并按权重负载分担。当前主流实现上一个候选路径只有一个 Segment List。
- BSID 的来源可以是 SRLB 和 SRGB。同一 SR Policy 不同备选路径的 BSID 一般相同；不同 SR Policy 的 BSID 一定不同。BSID 一般需要预先规划预留范围，不可以和其他业务共用。
- 转发头端通过 BSID 将报文转发绑定到 SR 策略上；用于标签流量引流场景，特别是标签粘连场景，以及不同隧道协议 interworking 场景（如 LDP over SR）。

**前提准备**：

- 控制器规划：用户可根据业务 SLA 要求在控制器上统一规划 color，以及 color 与 SR 隧道路径 SLA 要求（算路约束）的对应关系；
- 在设备上使能 Segment Routing 相关功能；
- 网络头尾节点创建 BGP 会话，便于传递 BGP 私网路由；
- BGP 对等体关系建立成功，头尾节点之间有可达的路由信息，能够传递携带 color 团体属性的路由。

## 8. SR Policy 业务流程

背景：R3 作为 Egress 路由器向 Ingress 路由器 R1 通告路由 `5.5.5.5/32`，最终从 R1–R3 建立 SR Policy 隧道，Color 为 Green。

### 8.1 路由着色

控制器通过 NETCONF 向 Egress 路由器下发 VPN 出口策略或 BGP 出口策略，为路由前缀 `5.5.5.5/32` 设置扩展团体属性 Color:Green，路由下一跳是 R3 的地址 `3.3.3.3`。

### 8.2 路由传递

Egress 路由器将着色的路由通过 MP-BGP 通告给 Ingress 路由器。

> 本教材中的步骤仅帮助读者学习理解，并不代表实际先后顺序。真实环境中控制器下发 SR Policy 和 NETCONF 下发配置可能同时进行。

### 8.3 引流及报文转发

控制器通过 BGP SR Policy 下发路径；Ingress 路由器将 SR Policy 生成转发面隧道。头结点根据 Color 完成引流转发。也支持其他引流方式，例如 DSCP 引流。

### 8.4 扩展：BGP SR Policy NLRI

SR Policy 的 NLRI 在 BGP Update 消息中携带。在 BGP 路由表呈现为 `[distinguisher][policy color][endpoint]`。

| 字段 | 长度 | 说明 |
| --- | --- | --- |
| NLRI Length | 1 Byte | NLRI 的长度 |
| Distinguisher | 4 Byte | policy 在元组中的唯一标示 |
| Policy Color | 4 Byte | color 标示 |
| Endpoint | 4 or 16 Byte | policy 的尾端 |

```cli
[PE1] display bgp sr-policy routing-table
```

示例路由条目形式：`[22][5][1.0.0.12]`、`[26][3][1.0.0.12]`、`[27][3][1.0.0.12]`。

### 8.5 小结：SR-MPLS 路径的生成方式

Segment Routing 是一种允许在头端节点选路而不需要依靠逐跳信令交互（LDP/RSVP-TE）的技术。SR-MPLS 的路径依靠由 IGP 通告的 Segment 组成。SR-MPLS 路径有多种生成机制：

- 转发器算路（SPF/CSPF）；
- 静态配置显式路径（CLI/NETCONF）；
- 控制器算路（PCEP/BGP SR Policy）。

BGP SR Policy 是当前主流的路径下发方式。

## 9. Segment Routing 隧道保护与检测技术

### 9.1 故障保护技术概览

TE 隧道故障保护有两种思路：局部保护与端到端保护。SR-MPLS TE 沿用此思路，并在此基础上增强。

| 类型 | 技术 | 特点 |
| --- | --- | --- |
| 局部保护 | TI-LFA FRR、Anycast FRR | 切换快；主要保护链路/节点 |
| 端到端保护 | Hot-Standby | 依赖检测机制快速切换；保护端到端路径 |

传统 LFA 无法形成备份路径的本质在于：分布式网络架构下每台设备独立计算路径，故障瞬间对于最短路径的理解没有共识。更多 TI-LFA FRR 原理细节请参考 NE 系列产品文档“TI-LFA FRR”。

### 9.2 TI-LFA FRR 的应用场景与配置

为了实现整体路径的保护，需要在多个节点 IGP 中使能 TI-LFA FRR 局部保护。

```cli
[Router] isis 1
[Router-isis-1] frr
[Router-isis-1-frr] loop-free-alternate level-2
[Router-isis-1-frr] ti-lfa level-2
```

**局限**：对于 SR 隧道中的指定必经节点（首节点、尾节点、路径约束节点）故障，TI-LFA 无法生成保护。

### 9.3 Anycast FRR

通过 Anycast FRR 可以实现对于指定节点的故障保护。让多台设备发布相同的 SID（Anycast SID）。Anycast SID 会在 IGP 中发布，其下一跳会指向路径中最近的节点；该最近节点称为 Anycast SID 的最优节点，另一台为备份节点。

补充：指向虚拟节点的链路开销可为 0，虚拟节点指向各设备的链路开销可为无穷大。

### 9.4 Hot-Standby

SR 的 Hot-Standby 就是通过控制器算出一条与主路径不同的备份路径，实现端到端的路径保护。SR-MPLS Policy 由主候选路径和备候选路径形成 Hot-Standby；主、备候选路径属于一个 SR-MPLS Policy。

若 Segment List 发生故障，将触发故障切换。SR-MPLS Policy 的故障感知需要依靠 BFD 或 SBFD 等检测机制。

**Hot-Standby 的局限**：若 PE2 发生故障，只能通过路由收敛来恢复业务（端到端路径保护无法覆盖 PE 节点故障本身）。

### 9.5 VPN FRR 回顾

传统 TE 隧道保护技术中，一旦 PE 节点发生故障，只能通过端到端路由收敛、LSP 收敛来恢复业务。业务收敛时间与 MPLS VPN 内部路由数量、承载网跳数密切相关。对于 VPN FRR，其收敛时间只取决于远端 PE 故障的检测并修改对应隧道状态的时间，从而解决了 PE 节点故障恢复时间与其承载的私网路由数量相关的问题。

Hot-Standby 和 VPN FRR 的故障感知都需要依赖 BFD 或 SBFD 等检测机制。

### 9.6 SR 防微环

完成收敛之后消失的暂态环路被称为微环（MicroLoop）。

**本地正切防微环**：设备收敛时间不同导致微环。例如 P1 路由收敛后不再携带 RepairList，查询到达目的路由下一跳为 P3；若 P3 未完成收敛，其下一跳依然为 P1，产生本地正切环路。启用防微环后 P1 启动定时器 T1，期间报文依旧按照 TI-LFA 策略转发，等待其他节点收敛。

```cli
[P1] isis 1
[P1-isis-1] avoid-microloop frr-protected
```

**本地回切防微环**：故障恢复后路径回切时也可能出现微环。启用防微环后，已收敛节点可计算防微环 Segment List，在定时器 T 内生效。

```cli
[P3] isis 1
[P3-isis-1] avoid-microloop frr-protected
```

**远端防微环**：路径切换过程中也可能引起远端节点之间形成环路。使能远端防微环后，率先收敛的节点针对访问目的的报文计算防微环 Segment List，在定时器 T 内生效。

```cli
[P2] isis 1
[P2-isis-1] avoid-microloop segment-routing
```

**TI-LFA 与防微环对比**：

| 对比项 | TI-LFA | 防微环 |
| --- | --- | --- |
| 目的 | 为目的地址在本地计算备份路径 | 防止主路径更新时的临时环路 |
| 触发条件 | 主路径链路/节点故障 | 主路径信息更新 |

### 9.7 SBFD 与单臂 BFD

BFD 进行大量链路检测时，其状态机的协商时间会变长，不适合 Segment Routing。SBFD（Seamless Bidirectional Forwarding Detection）是 BFD 的一种简化机制，简化了 BFD 的状态机，缩短协商时间，提高整个网络的灵活性，能够支撑 SR 隧道检测。

要点：

- 发起端状态机只有 Up 和 Down 状态，发出的报文也只有 Up 和 Down 状态，只能接收 Up 或 Admin Down 状态报文。SBFD 报文由发起端首先向反射端发送，报文初始状态为 Down。目的端口号 7784，源端口号 4784；目的 IP 为用户配置的 127 网段任意 IP，源 IP 为本端 LSR ID。
- 反射端无 SBFD 状态机、无检测机制，不会主动发送 SBFD Echo 报文，仅用于构造环回 SBFD 报文。反射端构造报文的目的端口号 4784，源端口号 7784；源 IP 为本端 LSR ID，目的 IP 为发起端的源 IP。多个检测端可共享一个反射端。

**单臂 BFD 检测**：BFD 和 SBFD 均需要两端设备支持。在特定场景下要与不支持 BFD 的设备对接时，华为设备支持配置 BFD 单臂功能（单臂 Echo）。一端配置 BFD 检测，另一端无需有 BFD 能力；使能单臂 Echo 的设备发送特殊 BFD 报文（IP 头中源和目的 IP 都是本端设备 IP，BFD 报文中本地标识和远端标识相同），对端收到后直接环回到本端，以此判断链路是否正常。

## 10. Segment Routing 典型应用场景

### 10.1 单域 SR-MPLS BE

SR-MPLS BE 适用于无严格 SLA 要求、无需路径规划的业务。下游路由器向上游分配 SID，形成 SR-MPLS 转发路径；控制面使用 MP-BGP 发布私网业务标签。另外，SR-MPLS BE 在生产网络中可以作为 SR-MPLS TE 业务的备份方案。

### 10.2 单域 SR-MPLS TE

SR-MPLS TE 适用于有严格 SLA 要求、需要路径规划的场景，例如 DCI（Data Center Interconnection）。SR 标签由 IGP 协议发布；控制器使用 BGP-LS 收集网络拓扑、网络带宽、时延和标签等属性；控制器根据约束条件计算出符合业务需求的转发路径，然后将算路结果通过 PCEP 或 NETCONF 下发到转发器。也可由工程师手工配置严格转发路径，然后通过 PCEP 将路径托管到控制器。

PCEP 最早在光传送领域被提出，由于在 IP 网络应用少、厂家间互通困难和性能弱等问题较少在企业生产网络中部署。因此在 SR-MPLS 网络中，推荐使用 BGP SR-Policy。

### 10.3 跨域 E2E SR-MPLS TE

跨自治域访问场景下，推荐由控制器集中计算然后下发端到端 SR-MPLS TE。

1. 在 ASBR 之间配置 BGP EPE（Egress Peer Engineering），互相分配 BGP Peer SID；ASBR 通过 BGP-LS 上报 BGP EPE 生成的标签和网络拓扑信息。
2. 在 E2E SR-MPLS TE 隧道创建之前，控制器需要先完成域内 SR-MPLS TE 隧道创建。如需减少标签深度，可以为域内隧道配置 Binding SID。
3. 控制器全局计算，将路径标签整合生成标签栈下发给转发器。例如 PE1 到 PE2 的标签栈为 `<1000, 304, 2000>`，其中 1000 和 2000 为 BSID，在域内转发时会替换为域内的 SR 标签栈。

## 11. L3VPN over SR-MPLS BE 基础配置

### 11.1 组网需求与配置思路

组网需求：

1. PE1 和 PE2 设备各有一个 CE 属于 VPN 实例 vpna；
2. 在骨干网络中部署 L3VPN 迭代 SR-MPLS BE 隧道，使得 CE1 和 CE2 的 Loopback1 接口可以相互通信。

配置思路：

1. 完成设备接口 IP 地址及 OSPF 配置（略）；
2. 骨干网上使能 MPLS，配置 Segment Routing，建立 SR LSP；
3. 在 PE1 与 PE2 之间建立 MP-BGP 对等体关系；
4. PE 上使能 VPN 实例 IPv4 地址族；
5. 在 PE 设备上配置隧道选择策略，优选 SR LSP；
6. 结果验证。

### 11.2 使能 MPLS 与 SR-MPLS BE 基本功能

在 SR-MPLS 域的所有节点上使能 MPLS 是配置 SR-MPLS BE 隧道的首要步骤：

1. `system-view` 进入系统视图；
2. `mpls lsr-id lsr-id` 配置本节点的 LSR ID（无缺省值，必须手工配置；推荐使用某个 Loopback 接口地址）；
3. `mpls` 使能 MPLS。

配置 SR-MPLS BE 基本功能主要包括：全局使能 SR 能力、配置 Segment Routing 全局标签范围、配置 Segment Routing 前缀标签。

全局使能 SR 能力：

```cli
system-view
segment-routing
commit
quit
```

### 11.3 PE1 配置示例（MP-BGP 与 VPN 实例）

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

### 11.4 隧道策略与 VPN 迭代

配置顺序选择方式的隧道策略：

1. `tunnel-policy policy-name` 创建隧道策略并进入隧道策略视图；
2. `tunnel select-seq sr-lsp load-balance-number load-balance-number [ unmix ]` 配置选择隧道的优先级顺序和负载分担条数；
3. `commit` / `quit`。

配置 BGP L3VPN 迭代到 SR-MPLS BE 隧道：

1. 进入 VPN 实例 IPv4 地址族视图；
2. `tnl-policy policy-name` 对 VPN 实例 IPv4 地址族应用隧道策略；
3. `commit`。

### 11.5 结果验证要点

在 PE1 上查看 VPNv4 路由信息（`display bgp vpnv4 all routing-table`），确认远端私网前缀、标签、下一跳及中继信息。

在 PE1 上查看 vpna 路由信息（`display ip routing-table vpn-instance vpna ... verbose`），确认将 VPNv4 标签和 SR LSP 结合指导数据包转发（含 Tunnel ID）。

在 PE1 上 Tracert SR LSP（`tracert lsp segment-routing ip ...`），并在 CE1 上 ping 验证互通。

> （原图：PE1—P—PE2，CE1/CE2 通过 Loopback1 互通的拓扑；请结合设备回显思考标签如何由 SRGB + Index 计算得到）
