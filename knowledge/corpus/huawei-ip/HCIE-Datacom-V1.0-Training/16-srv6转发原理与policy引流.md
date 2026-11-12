---
doc_id: "hcie-datacom-v1.0-training-16"
title: "SRv6转发原理与Policy路径建立引流"
book: "HCIE-Datacom-V1.0-Training"
book_title: "HCIE-Datacom V1.0 培训教材"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "training"
source_pdf: "HCIE-Datacom+V1.0+培训教材.pdf"
seq: 16
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# SRv6转发原理与Policy路径建立引流

## 1. SRv6 Locator 配置示例

SRv6 SID 分为静态配置和动态配置两种方式。动态配置只需要配置 locator 命令，opcode 由 IGP 动态分配；静态配置则手动配置对应类型 SID 的 opcode。

静态配置 SID 时，SID 只占用静态段范围，静态段取值从 1 开始，动态段设置为 0；动态分配 SID 时，SID 会占用动态段和静态段范围，动态段取值从 1 开始，静态段取值从 0 开始。

本配置示例 Locator 是 `2001:DB8:ABCD::`，长度占用 64 位，静态段占用 32 位，动态段占用 32 位，args 字段占用 0 位。取值范围：

- 静态段起始值：`2001:DB8:ABCD:0000:0000:0000:0000:0001`；结束值：`2001:DB8:ABCD:0000:0000:0000:FFFF:FFFF`
- 动态段起始值：`2001:DB8:ABCD:0000:0000:0001:0000:0000`；结束值：`2001:DB8:ABCD:0000:FFFF:FFFF:FFFF:FFFF`

结构示意：`|--Locator--|--Dynamic Opcode--|--Static Opcode--|--Args--|`

```cli
[Huawei-segment-routing-ipv6] locator srv6_locator1 ipv6-prefix 2001:DB8:ABCD:: 64 static 32
```

推荐静态配置 End SID 和 End.X SID。动态生成的 SID 如果设备重启，SID 会变化，不利于维护。

## 2. SRv6 节点

RFC 8754 中定义了 SR 有三种类型节点：

- **源节点（SR Source Node）**：生成 SRv6 报文的源节点；
- **中转节点（Transit Node）**：转发 SRv6 报文但不进行 SRv6 处理的 IPv6 节点；
- **Endpoint 节点（SR Segment Endpoint Node）**：接收并处理 SRv6 报文的任何节点，该报文的 IPv6 目标地址必须是本地配置的 SID 或者本地接口地址。

### 2.1 SRv6 源节点

源节点将数据包引导到 SRv6 Segment List 中。如果 SRv6 Segment List 只包含单个 SID，并且无需在 SRv6 报文中添加信息或 TLV 字段，则 SRv6 报文的目的地址字段设置为该 SID。源节点可以是生成 IPv6 报文且支持 SRv6 的主机，也可以是 SRv6 域的边缘设备。

### 2.2 源节点行为

SRv6 源节点负责将流量引导到 SRv6 Policy 中，并执行可能的 SRH 封装。常见封装模式：

| 源节点行为 | 功能描述 |
| --- | --- |
| H.Insert | 为接收到的 IPv6 报文插入 SRH，并查表转发 |
| H.Insert.Red | 为接收到的 IPv6 报文插入 Reduced SRH，并查表转发 |
| H.Encaps | 为接收到的 IP 报文封装外层 IPv6 报文头与 SRH，并查表转发 |
| H.Encaps.Red | 为接收到的 IP 报文封装外层 IPv6 报文头与 Reduced SRH，并查表转发 |
| H.Encaps.L2 | 为接收到的二层帧外封装 IPv6 报文头与 SRH，并查表转发 |
| H.Encaps.L2.Red | 为接收到的二层帧外封装 IPv6 报文头与 Reduced SRH，并查表转发 |

Reduced SRH 和 SRH 的区别在于：Reduced SRH 中 Segment List 不包含已存在于 IPv6 目的地址中的第一个 Segment。

### 2.3 中转节点

中转节点是在 SRv6 报文转发路径上不参与 SRv6 处理的 IPv6 节点，只执行普通的 IPv6 报文转发。当节点收到 SRv6 报文后解析 IPv6 目的地址字段：如果既不是本地配置的 SRv6 SID 也不是本地接口地址，则将报文当做普通 IPv6 报文查询路由表执行转发，不处理 SRH。中转节点可以是普通 IPv6 节点，也可以是支持 SRv6 的节点。

### 2.4 Endpoint 节点

在 SRv6 报文转发过程中，若节点接收报文的 IPv6 目的地址是本地配置的 SID，则该节点被称为 Endpoint 节点。例如：R3 使用报文的 IPv6 目的地址查找 Local SID 表，命中 End SID 后，将报文 SL 减 1，同时将 SL=1 的 SID 作为报文目标 IPv6 地址，并查路由表转发出去。Endpoint Node 在数据转发路径上可以有多个，每个都会为报文提供转发、封装和解封装等服务。

使能 SRv6 的节点维护一个本地 SID（Local SID）表，该表包含所有在本节点生成的 SRv6 SID 信息，根据该表可以生成一个 SRv6 转发表（FIB）。本地 SID 表用途：

- 定义本地生成的 SID（例如 End.X SID 等）；
- 指定绑定到这些 SID 的指令；
- 存储和这些指令相关的转发信息（例如出接口和下一跳等）。

## 3. SRv6 转发模式

SRv6 有两种转发模式：SRv6 Policy 和 SRv6 BE。

- **SRv6 Policy**：可以实现流量工程，配合控制器可以更好地响应业务差异化需求，做到业务驱动网络。
- **SRv6 BE**：一种简化的 SRv6 实现，正常情况下不含有 SRH 扩展头，只能提供尽力而为的转发。

在 SRv6 发展早期，基于 IPv6 路由可达性，利用 SRv6 BE 快速开通业务具有优势；后续可按需升级网络中间节点，部署 SRv6 Policy，满足高价值业务需求。

### 3.1 SRv6 Locator 信息扩散

无论基于 SRv6 BE 或 SRv6 Policy 转发流量，路由器都需要有 SRv6 Locator 的相关路由信息才能转发 SRv6 报文。SRv6 节点通常通过扩展 IGP（扩展 OSPFv3 或扩展 IS-IS），将 Locator 相关路由扩散到网络节点上（包括源节点、中转节点、Endpoint 节点）。

### 3.2 SRv6 BE 转发过程

传统 MPLS 有 LDP 和 RSVP-TE 两种控制协议，其中 LDP 方式不支持流量工程能力，利用 IGP 算路结果建立 LDP LSP 指导转发。在 SRv6 里也有类似方式：仅使用一个业务 SID 来指引报文在 IP 网络里进行尽力而为（Best Effort，BE）转发，这种方式就是 SRv6 BE。SRv6 BE 的转发路径计算依据 IGP 开销。

### 3.3 SRv6 Policy 转发过程

在 SRv6 转发过程中每经过一个 SRv6 Endpoint 节点，Segments Left（SL）字段减 1，IPv6 报文头中的目的 IPv6 地址变换一次。Segments Left 和 Segment List 字段共同决定 IPv6 DA 信息。

与 SR-MPLS 不同，SRv6 SRH 是从下到上逆序操作，SRH 中的 Segment 在经过节点后也不会被弹出，因此 SRv6 报头可以做路径回溯。

当 SL=0 的 SID 类型为 END / END.X / END.DT 时，默认在倒数第二段会弹出 SRH 头部（对应 PSP 等行为）。

在 MPLS 中，使用 Implicit-Null 和 Non-null 选项定义了不同的弹出选项；PHP 指最外层标签在到达相邻 LER 之前被 LSR 移除。这些行为在 SRv6 中被定义成 PSP 和 USP。

---

## 4. SRv6 Policy 路径建立与引流

参考：[draft-ietf-spring-segment-routing-policy](https://datatracker.ietf.org/doc/draft-ietf-spring-segment-routing-policy/)

### 4.1 SRv6 Policy 简介

SRv6 Policy 是在 SRv6 技术基础上发展的一种新的引流技术。SRv6 Policy 路径表示为指定路径的段列表（Segment List / SID List）。每个 SID 列表是从源到目的地的端到端路径，并指示网络中的设备遵循指定路径，而不是遵循 IGP 计算的最短路径。如果数据包被导入 SRv6 Policy，SID 列表由头端添加到数据包上，网络的其余设备执行 SID 列表中嵌入的指令。

### 4.2 标识 SRv6 Policy

一个 SRv6 Policy 有一个元组标识 `<headend, color, endpoint>`。对于一个指定的源节点，SRv6 Policy 由 `<color, endpoint>` 标识：

- **头端（headend）**：SRv6 Policy 生成的节点，一般是全局唯一的 IP 地址；
- **颜色（color）**：32 比特扩展团体属性，用于标识某一种业务意图（例如低延时）；
- **尾端（endpoint）**：SRv6 Policy 的目的地址，一般是全局唯一的 IPv6 地址。

在特定头端，color 和 endpoint 被用于标识 SRv6 Policy 转发路径。

注意：SRv6 Policy 中的 endpoint 与 SRv6 中的 endpoint node 是不同概念——前者指隧道尾端节点（一般用 IPv6 地址表示）；后者指会处理 SRH 头部的设备类型。

### 4.3 SRv6 Policy 路径模型

- SR Policy P1 由三元组 `<headend, color, endpoint>` 唯一确定；
- 一个 SR Policy 可以有多个候选路径（如 CP1、CP2），每个路径由三元组 `<protocol, origin, discriminator>` 唯一确定；
- CP1 是激活路径（合法且优先级高）。CP1 的多个 SID-List 可下发到转发器，并按权重负载分担。

一个 SRv6 Policy 可以包含多个候选路径（Candidate Path），候选路径携带优先级属性（Preference）。优先级最高的有效候选路径为 SRv6 Policy 的主路径，优先级次高的有效路径为备份路径。一个候选路径就是 SRv6 Policy 通过静态配置或 BGP IPv6 SR Policy 向头端发送的基础单元。Segment List 附带权重（Weight）来控制 SRv6 路径的负载分担。

### 4.4 SRv6 Policy 实现方式

主流有三种方式：

- **BGP**：BGP-LS 用于收集拓扑，对于客户自研控制器无需引入新的接口协议；BGP IPv6 SR Policy 下发路径路由信息。
- **PCEP**：在 SR-MPLS TE 场景下较为成熟，但由于各厂家隧道实现模型不统一、交互流程更复杂，更推荐使用 BGP 扩展协议。
- **NETCONF/YANG**：把隧道路径作为配置下发，性能最差，不推荐用于隧道配置。整体方案中仍可用 NETCONF 下发其他配置。

华为主要使用 BGP 方式部署 SRv6 Policy。

### 4.5 华为解决方案中的路径建立概述

在华为 SRv6 Policy 解决方案架构中，依赖控制器（iMaster NCE-IP）建立路径：

1. 控制器通过 BGP-LS 收集扩展 IGP 协议收集的拓扑信息，用于计算 SRv6 Policy 路径和状态呈现；
2. 控制器通过 BGP IPv6 SR Policy 协议向源节点下发 SRv6 Policy 信息（headend、color、endpoint 等）。

还会使用 NETCONF 协议，主要用于下发业务接口、路由策略（添加 Color 属性）等其他配置。除通过 iMaster NCE-IP 下发外，也可手工部署 SRv6 Policy。

### 4.6 通过 BGP-LS 收集信息

在华为 SRv6 Policy 解决方案中，BGP-LS 主要功能：

1. 通过 BGP-LS 路由将 IS-IS/OSPFv3 收集的拓扑信息、前缀信息、SRv6 Locator 和 SID 信息通告给 iMaster NCE-IP；
2. 通过 BGP-LS 路由通告 SRv6 Policy 的状态。

```cli
[~PE1] display bgp link-state unicast routing-table
```

可看到 NODE / LINK / SRV6-SID / TEPOLICY 等类型路由信息。

补充：

- 收集隧道拓扑信息，用于计算 SR Policy 路径；
- 扩展支持收集 SR Policy 状态信息，用于控制器隧道状态呈现（见 [draft-ietf-idr-te-lsp-distribution](https://datatracker.ietf.org/doc/draft-ietf-idr-te-lsp-distribution/)）；
- 扩展支持 SRLB 信息封装和解封装，用于控制器获取 SRLB 信息以分配 BSID；
- 隧道源节点也需要部署 BGP-LS，主要用于通告 SRv6 Policy 状态。

### 4.7 通过 BGP IPv6 SR Policy 下发路径

iMaster NCE-IP 可通过 BGP IPv6 SR Policy 邻居下发 SRv6 Policy 给源节点。SRv6 Policy 在 BGP 路由表呈现为 `[distinguisher][color][endpoint]`。

```cli
[~PE1] display bgp sr-policy ipv6 routing-table [49][16][FC01::4]
```

路由条目可包含 Tunnel Encaps Attribute：Tunnel Type=SR Policy、Preference、Binding SID、Segment List（含 Weight、Path MTU、各 Segment SID）等。

BGP IPv6 SR Policy 连接作用：

- 控制器向转发器下发 SRv6 Policy 信息，生成 SRv6 Policy；
- 控制器下发 BGP 路由携带 Color 团体属性；头端基于 Color+Endpoint 迭代到 SRv6 Policy；
- 需要在控制器根据业务 SLA 要求统一规划算路约束，并通过不同 color 标识。根据 `{头节点，尾节点，COLOR}` 唯一确定一个 SRv6 Policy；业务报文迭代隧道时 BGP 路由需携带对应 color 扩展团体属性。

Binding SID 的主要作用是用于路径粘连。

### 4.8 SRv6 Policy 跨域路径建立（BGP EPE）

SRv6 设备需要获取全网 SID 信息才能实现端到端数据转发。在一个 AS 内，设备可通过扩展 IGP（OSPFv3 / IS-IS）获取 AS 内 SID；跨域场景中需借助 BGP 传递 SID，即 BGP EPE（Egress Peer Engineering）。

BGP EPE 可为域间路径分配 BGP Peer SID：

- **Peer-Node SID**：指示一个对等体节点。每一个 BGP 会话都会分配 Peer-Node SID。对于基于 Loopback 建立的 EBGP 邻居，物理链路可能有多条，则 Peer-Node SID 可对应多个出接口。Peer-Node SID 是一种 END SID。
- **Peer-Adj SID**：指示到达对等体的一个邻接。多链路时每个邻接都会分配一个 Peer-Adj SID，转发时只能使用指定链路。Peer-Adj SID 是一种 END.X SID。

BGP EPE 只是针对 BGP 邻居节点及相关链路分配 SID，并不能单独构建完整转发路径；BGP Peer SID 还需要与 IGP SID 配合才能形成 E2E 路径。

### 4.9 SRv6 Policy 路径粘连

SRv6 的 SRH 头部有栈深限制，大型网络可部署 SRv6 路径粘连方案。路径粘连主要通过粘连 SID（Binding SID）与粘连节点实现：

- Binding SID 可以表示一段 SRv6 Policy 转发路径；
- 粘连节点会处理 Binding SID 并压入 SRH 信息，一般是 ABR 或 ASBR 设备。

解决 SRH 头部过大的一般方法：

1. **SRv6 头部压缩**（如华为 G-SRv6）：在不损失 SID 信息基础上减少头部大小，提高转发效率（本节不做展开）；
2. **SRv6 路径粘连**：通过 Binding SID 将不同 SRv6 路径粘连在一起，使每段 SRH 头部不至于过大。

SRv6 栈深一般由设备能力决定。Binding SID 主要有 4 种：

- End.B6.Insert
- End.B6.Insert.RED
- End.B6.Encaps
- End.B6.Encaps.RED

常用两种封装模式：

- **Insert 模式**：在原始 IPv6 报文头后插入一个 SRH，数据包基于原始 IPv6 头部与新 SRH 头指导转发；
- **Encaps 模式**：在原始 IPv6 报文头前插入外层 IPv6 头部与 SRH 头，数据包基于外层 IPv6 头部与 SRH 头部转发。

Encaps 模式使用的 End.B6.Encaps 指令可拆解为 End + B6 + Encaps：B6 表示应用一个 SRv6 Policy，Encaps 表示采用封装外层 IPv6 报文头和 SRH 的方式来应用 SRv6 Policy。执行动作包括：内层 SRH 的 SL 减 1，将 SL 指向的 SID 复制到内层 IPv6 目的地址，再封装上一层 IPv6 报文头与 SRH，设置源地址为当前节点地址、目的地址为 SRv6 Policy 的第一个 SID，最后对新的 IPv6 报文查表转发。

### 4.10 基于 Color 引流

SRv6 Policy 可以基于路由 Color 属性引流：直接基于路由的扩展团体属性 Color 和目的地址迭代到 SRv6 Policy。

要点：

- 在 PE1 上配置隧道策略；收到 BGP 路由后，根据扩展团体属性（如 0:15、0:20）和下一跳迭代到不同的 SRv6 Policy，为到特定网段的报文添加具体 SRv6 SID 栈；
- Color 属性可以在路由始发路由器出方向修改，也可以在路由接受路由器入方向修改；
- 在数据始发路由器的 VPN-instance 中，也可以直接配置 Color，让该 VPN 的所有流量都指定通过某个 SRv6 Policy 转发。

### 4.11 基于 DSCP 引流

对于去往同一个目的地址的不同业务流量（HTTP、FTP 等），仅基于 Color 引流会导致所有流量都迭代到同一条转发路径，无法精细化控制，因此需要使用基于 DSCP 引流。

要点：

- PE 基于报文目标地址与路由下一跳匹配映射策略（Color），再基于 DSCP 迭代到不同转发路径；
- 当基于 DSCP 引流时，路由条目中的 Color 属性主要用于匹配映射策略；
- Color 可在本端发送前修改，也可在对端接收后修改；VPN-instance 也可直接配置 Color。

---

## 5. SRv6 典型用例

### 5.1 L3VPN Over SRv6 Policy

当使用 SRv6 Policy 承载 VPN 流量时，最末跳 SRv6 设备在处理数据时，与普通 SRv6 处理稍有不同：最末跳路由器可能进行两次查表（先命中 End SID 更新 DA 到 VPN SID，再命中 End.DT4 解封装并查 VPN 实例路由表）。

**路由传递流程**：

1. PE 配置 SRv6 和 SRv6 VPN，中间节点设备需要支持 IPv6 或 SRv6；
2. PE2 发布 SRv6 Locator 路由给 PE1；
3. CE 到 PE 的路由信息交换：CE2 把本站点路由发布给 PE2（静态/RIP/OSPFv3/IS-IS/BGP）；
4. PE2 从 CE2 学习到 VPN 路由后存放到 VPN 实例路由表，并转换成 MP-BGP 路由；
5. PE 之间路由发布：在 PE2 配置 BGP/VPN 出口策略（或在 PE1 配置入口策略），为路由设置扩展团体属性 Color，下一跳是 PE2；Update 报文还携带 RT 属性及 SRv6 VPN SID 属性；
6. PE1 接收 VPN 路由：下一跳可达且通过入口策略时，进行私网路由交叉、路由迭代 SRv6 路径、路由优选等，决定是否加入 VPN 实例路由表；VPN 路由下发同时关联 SRv6 VPN SID；
7. PE 到 CE 的路由信息交换：与对端对称，可用静态/RIP/OSPFv3/IS-IS/BGP。

**报文转发流程**：

1. 头端 PE1 收到 CE1 普通单播报文后，查找 VPN 实例路由表，出接口是 SRv6 Policy；插入 SRH、封装 SID List 与 IPv6 报文头后转发给中间节点；
2. 中间节点根据 SRH 信息逐跳转发；
3. 报文到达尾节点 PE2 后，使用 IPv6 目的地址查找 My Local SID 表，命中 End SID，将 SL 减 1，IPv6 DA 更新为 VPN SID；
4. PE2 再用 VPN SID 查找 My Local SID 表，命中 End.DT4，解封装去掉 SRH 和 IPv6 头，用内层目的地址查找对应 VPN 实例路由表，转发给 CE2。

### 5.2 L3VPN Over SRv6 BE

SRv6 BE 承载 VPN 流量时，PE 之间的 P 设备不作为 Endpoint 节点使用。外层 IPv6 DA 直接为 VPN SID（如 End.DT4），中间节点按 IPv6 路由转发；到达 PE2 后剥离外层 IPv6 头部，以普通 IP 报文转发。

**路由传递流程**与 Policy 场景类似，但 PE 之间发布时通常不强调 Color 引流到 Policy，而是路由迭代到 SRv6 BE 路径；Update 仍携带 RT 及 SRv6 VPN SID。

**报文转发流程**（教材描述）：头端封装后，中间按外层 IPv6 转发；尾节点根据 VPN SID（End.DT4）解封装并查 VPN 实例路由表转发。相对 Policy，BE 路径不依赖端到端 Segment List 严格约束。

> 注：原文部分段落在描述 BE 转发时仍出现“出接口是 SRv6 Policy / 插入 SRH”等表述，属 OCR/讲义混排痕迹；BE 场景正常情况下可不含 SRH，以业务 SID + IPv6 可达性完成尽力而为转发。

### 5.3 Native IPv6 Over SRv6 Policy

普通 IPv6 数据也能被 SRv6 承载。IPv6 报文依据 Color 被相应 SRv6 Policy 承载；中间基于外层 IPv6 头部转发；到尾端后剥离 SRH，以普通 IPv6 报文转发。

**路由传递流程**：

1. PE 配置 SRv6，中间节点支持 IPv6 或 SRv6；
2. PE2 发布 SRv6 Locator 路由给 PE1；
3. CE 到 PE 交换 IPv6 路由；
4. PE 之间：在 PE2 配置 BGP 出口策略（或在 PE1 配置入口策略）为路由设置 Color，下一跳为 PE2，通过 BGP 邻居发送给 PE1；
5. PE1 接收 IPv6 路由后，在下一跳可达且通过入口策略时，进行路由迭代 SRv6 路径、路由优选等；
6. PE 到 CE 再将 IPv6 路由下发到本站点。
