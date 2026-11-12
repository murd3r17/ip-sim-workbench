---
doc_id: "hcip-datacom-core-training-10"
title: "IP组播基础、IGMP与PIM"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 10
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# IP组播基础、IGMP与PIM

## 前言与目标

网络业务从流量模型看一般分两类：

- **点到点业务**（如 FTP、WEB）：不同用户有不同需求，一般由单播承载。
- **点到多点业务**（如 IPTV、视频会议）：多个用户有相同需求，可用单播、组播、广播承载；使用单播或广播承载点到多点业务时存在一定问题。组播技术能够较好解决这些问题。

学完后应能够：描述组播的定义及组播的地址结构；描述组播数据的转发原理；描述反向路径转发（RPF）的原理。

## 单播 / 广播 / 组播

- **单播**：一台源与一台目的之间。多个接收者时 Server 需发送与接收者数目相同的单播数据包；接收者成百上千时，Server 与链路带宽压力大。
- **广播**：一台源与网络中所有其它主机之间。广播限制在广播域内；大量广播消耗带宽与设备资源；安全性和有偿服务得不到保障。
- **组播**：一台源与多台（一组）目的之间，中间设备根据接收者需要有选择地复制和转发。有效满足单点发送、多点接收需求，节约带宽、降低网络负载。

**组播分发树**：组播流量的转发路径。

## 组播数据报文结构

组播数据报文结构与单播类似，但目的 MAC / 目的 IP 不同：

- **组播目的 IP**：224.0.0.0～239.255.255.255
- **组播目的 MAC**：由组播 IP 地址映射而来

## IPv4 组播地址

- IPv4 地址空间分 A/B/C/D/E 类；D 类为组播地址，范围 224.0.0.0～239.255.255.255，用于标识组播组，仅能作为目的地址，不能作为源地址。
- 组播报文源地址字段为 IPv4 单播地址（A/B/C 类），不能是 D/E 类。
- 加入同一组播组的所有用户主机能够识别同一个 IPv4 组播组地址。

### 组播 MAC 映射

IPv4 组播地址前 4 位固定为 1110，对应组播 MAC 地址的高 25 位；后 28 位中只有 23 位被映射到 MAC，丢失 5 位信息，结果是有 32 个 IPv4 组播地址映射到同一 MAC 地址。例如 224.0.1.1、224.128.1.1、225.0.1.1、239.128.1.1 等的组播 MAC 都为 01-00-5e-00-01-01。

- 组播 MAC 第 1 个字节的最低比特位为 1（例如 0100-5e-00ab）。
- 组播/广播 MAC 不能作为数据帧源 MAC，只能作为目的 MAC。
- 另有一类不与组播 IP 映射的组播 MAC（如 STP BPDU 目的 MAC 0180-c200-0000）。

## 组播网络角色

| 角色 | 说明 |
| --- | --- |
| 组播源（Source） | 组播流量发送者；无需运行组播协议，只需发送组播数据 |
| 组播接收者（Receiver） | 组播组成员 |
| 组播组（Multicast Group） | 用 IP 组播地址标识的集合 |
| 组播路由器 | 支持组播、运行组播协议的网络设备 |
| 第一跳路由器 | 与组播源相连并负责转发其组播数据的 PIM 路由器 |
| 最后一跳路由器 | 与组成员相连并负责向该组成员转发组播数据的 PIM 路由器 |
| IGMP | 因特网组管理协议，在接收者与直接相邻组播路由器之间建立、维护组成员关系 |

## ASM 与 SSM

**ASM 特点**：

- 可在路由器上配置针对组播源的过滤策略以提高安全性。
- 要求组地址在整个组播网络中唯一；同一时刻一个 ASM 地址只能被一种组播应用使用，否则接收者会同时收到来自两个源的数据。

**SSM 特点**：

- 对组地址不再要求全网唯一，只需每个组播源保持唯一（同一源上不同应用使用不同 SSM 地址）。
- 不同源之间可使用相同组地址，因为针对每一个（源，组）都会生成表项。
- SSM 组播地址范围：232.0.0.0～232.255.255.255。

## 组播数据转发困局与 RPF

基于目的网络的路由表在转发组播数据时可能出现：转发环路、次优路径、重复报文等问题。

- 组播路由表项出接口一般需通过组播路由协议确定。
- 组播路由表项包含组播源与组播组，因此有时又被称为（S，G）表项。

**RPF 检查**：组播路由器根据报文的源地址通过路由表（单播路由表、MBGP 路由表或组播静态路由表）查找到达“报文源”的路由，查看该路由表项的出接口是否与收到组播报文的入接口一致。如果一致，则认为该组播报文从正确的接口到达，从而保证转发路径的正确性和唯一性。

从候选最优路由中选择 RPF 路由的原则：

1. 若配置按最长匹配选择，则选出最长匹配路由；
2. 若掩码一样，则选择优先级最高的路由；
3. 若优先级也相同，则按组播静态路由 → MBGP 路由 → 单播路由的顺序选择。

- **MBGP**：主要用于传递组播源相关的路由条目。
- **组播静态路由表**：手工配置组播源与出接口的对应关系。

## 组播分发树与协议

通过 RPF 机制与组播路由协议，组播网络可形成无环、无次优且无重复包的组播转发路径，称为组播分发树。以组播源为根，以组成员为叶子。

组播协议分工：

| 协议 | 作用 |
| --- | --- |
| IGMP | 成员端网络：告知组成员位置与所加组播组 |
| PIM | 生成 AS 域内的组播分发树 |
| MSDP | 帮助生成 AS 域间的组播分发树 |
| MBGP | 帮助跨域组播流进行 RPF 校验 |

### 思考题（组播基础）

1. IPv4 组播地址范围？（D 类：224.0.0.0～239.255.255.255）
2. 相关多选题答案要点：A、C

### 本章总结（组播基础）

- 组播解决单播/广播承载点到多点流量时的问题。
- 组播网络一般由源端网络、组播转发网络、成员端网络组成。
- 转发中可能存在环路、次优路径、重复报文；RPF 检查可部分或全部解决。

## IGMP 原理要点

### IGMPv1 普遍组查询与响应

1. IGMP 查询器发送目的地址为 224.0.0.1 的普遍组查询报文；组成员启动定时器。普遍组查询缺省每隔 60 秒发送一次。定时器缺省为 0～10 秒之间的随机值。
2. 第一个定时器超时的组成员发送针对该组的报告报文。
3. 查询器收到报告后了解本网段存在该组成员，生成 IGMP 组表项与（*，G）IGMP 路由表项。

**成员关系报告报文抑制**：其他组成员收到报告后停止定时器，不再发送针对该组的报告，减少网段流量。

Assert Winner 或 DR 用于转发组播流量（详见 PIM 课程）。

### IGMPv2 报文字段

| 字段 | 说明 |
| --- | --- |
| Type | 0x11 查询；0x12 IGMPv1 报告；0x16 IGMPv2 报告；0x17 离开 |
| Max Response Time | 普遍组查询缺省 10s；特定组查询缺省 1s |
| Group Address | 普遍组查询为 0；特定组查询/报告/离开为对应组地址 |

### IGMPv3 与 SSM Mapping

IGMPv3 支持源列表改变报告（ALLOW_NEW_SOURCES / BLOCK_OLD_SOURCES）等。SSM Mapping 功能在 IGMP 特性章节介绍。

## IGMP Snooping 与二层组播

二层组播转表示意：

| (Source, Group) | Interface | 说明 |
| --- | --- | --- |
| Router-port | IF3 | 路由器端口 |
| (*, 239.0.0.1) | IF1 / IF2 | 成员端口 |

- **动态路由器端口**：收到源地址不为 0.0.0.0 的 IGMP 普遍组查询或 PIM Hello 的接口。
- **静态路由器端口**：手工配置。
- **动态成员端口**：收到 IGMP Report 的接口。
- **静态成员端口**：手工配置。

路由器端口老化计时器默认 180s；成员端口老化定时器 = 健壮系数 × 普遍组查询间隔 + 最大响应时间。

IGMP Snooping 下不再使用成员关系报告抑制：设备将报告只从路由器接口发送出去，避免其余组成员收到报告。收到离开报文后，成员端口老化定时器 = 健壮系数（默认 2）× 特定组查询间隔（默认 1s）。

## IGMP / IGMP Snooping 配置

```cli
[Huawei-GigabitEthernet1/0/0] igmp enable
[Huawei-GigabitEthernet1/0/0] igmp version number
[Huawei] igmp-snooping enable
[Huawei-vlan10] igmp-snooping proxy
[Huawei-GigabitEthernet1/0/0] igmp ssm-mapping enable
[Huawei-igmp] ssm-mapping group-address group-mask source-address
```

查看命令：

```cli
<Huawei> display igmp interface
<Huawei> display igmp group
<Huawei> display igmp ssm-mapping
<Huawei> display l2-multicast forwarding-table vlan vlan-id
```

RTA 配置示例：

```cli
[RTA] multicast routing-enable
[RTA] interface g0/0/1
[RTA-GigabitEthernet0/0/1] ip address 192.168.1.1 24
[RTA-GigabitEthernet0/0/1] igmp enable
[RTA-GigabitEthernet0/0/1] igmp version 2
```

`display igmp interface` 可看到：IGMP version、query interval（configured 60s）、maximum query response time（10s）、Querier 地址等。

### 思考题（IGMP）

1. IGMPv1 中最后一个成员离开后，多久删除对应转发表项？（60×2+10=130s）
2. IGMPv2 特定组查询的目的 IP 是 224.0.0.1 吗？（否，是所查询组播组的组播 IP）
3. IGMP 支持哪些版本？（IGMPv1、IGMPv2、IGMPv3）

## PIM 路由表 Flag 字段（节选）

| Flag | 描述 |
| --- | --- |
| act | 已经有实际数据到达的组播路由表项 |
| del | 准备删除的组播路由表项 |
| loc | 在与组播源网段直连的设备上的组播路由表项 |
| spt | 最短路径树上的路由表项 |
| wc | 表示（*，G）表项 |
| rpt | 处于共享树上但不使用共享树数据的路由表项 |
| … | 另有 2msdp、msdp、niif、nonbr、sg_rcvr、sgjoin、swt、upchg 等 |

## PIM-DM 配置

```cli
[Huawei] multicast routing-enable
[Huawei-GigabitEthernet1/0/0] pim dm
```

查看：

```cli
<Huawei> display pim neighbor
<Huawei> display pim routing-table
```

示例（R1/R2/R3，源 10.10.10.10/24，组 224.1.1.1；省略接口 IP、OSPF）：

```cli
[R1] multicast routing-enable
[R1] interface g0/0/2
[R1-GigabitEthernet0/0/2] pim dm
[R1-GigabitEthernet0/0/2] interface g0/0/0
[R1-GigabitEthernet0/0/0] pim dm
[R1-GigabitEthernet0/0/0] interface g0/0/1
[R1-GigabitEthernet0/0/1] pim dm

[R2] multicast routing-enable
[R2] interface g0/0/0
[R2-GigabitEthernet0/0/0] pim dm
[R2-GigabitEthernet0/0/0] interface g0/0/1
[R2-GigabitEthernet0/0/1] igmp enable

[R3] multicast routing-enable
[R3] interface g0/0/0
[R3-GigabitEthernet0/0/0] pim dm
[R3-GigabitEthernet0/0/0] interface g0/0/1
[R3-GigabitEthernet0/0/1] igmp enable
```

## PIM-SM 配置

```cli
[Huawei] multicast routing-enable
[Huawei-GigabitEthernet1/0/0] pim sm
[Huawei-pim] static-rp rp-address
```

示例（静态 RP 1.1.1.1）：

```cli
[R1] multicast routing-enable
[R1] interface g0/0/2
[R1-GigabitEthernet0/0/2] pim sm
[R1-GigabitEthernet0/0/2] interface g0/0/0
[R1-GigabitEthernet0/0/0] pim sm
[R1-GigabitEthernet0/0/0] interface g0/0/1
[R1-GigabitEthernet0/0/1] pim sm
[R1] pim
[R1-pim] static-rp 1.1.1.1

[R2] multicast routing-enable
[R2] interface g0/0/0
[R2-GigabitEthernet0/0/0] pim sm
[R2-GigabitEthernet0/0/0] interface g0/0/1
[R2-GigabitEthernet0/0/1] igmp enable
[R2] pim
[R2-pim] static-rp 1.1.1.1

[R3] multicast routing-enable
[R3] interface g0/0/0
[R3-GigabitEthernet0/0/0] pim sm
[R3-GigabitEthernet0/0/0] interface g0/0/1
[R3-GigabitEthernet0/0/1] igmp enable
[R3] pim
[R3-pim] static-rp 1.1.1.1
```

### 思考题（PIM）

1. （单选题）PIM 组播报文的目的 IP 地址是？224.0.0.2 / 224.0.0.1 / 224.0.0.5 / **224.0.0.13**
2. （多选题）组播防止重复报文的机制有？**RPF**、**Assert 选举**、**DR 选举**；IGMP 查询者选举不是防重复报文机制。

## IPv6 概述（节选开篇）

IPv4 设计不足日益明显，IPv6 解决了 IPv4 的一些问题。IPv6 也被称为 IPng，是 IETF 设计的一套规范，是 IPv4 的升级版本。本课程后续将介绍 IPv6 基本概念、地址分类、报文格式等。

学完 IPv6 课程后应能够：描述 IPv6 发展现状与相对 IPv4 的优势；描述基本概念、报文头部格式、地址格式和类型；实现 IPv6 地址以及 IPv6 路由的简单配置。

### IPv4 地址耗尽与 RIR

IANA 将部分 IPv4 地址分配给大洲级 RIR，再由各 RIR 分配：RIPE、LACNIC、ARIN、AFRINIC、APNIC。20 世纪 90 年代 IETF 推出 NAT 与 CIDR 等技术推迟地址耗尽，但只能减缓不能从根本上解决问题。

### Why IPv6

| IPv4 问题 | IPv6 优势 |
| --- | --- |
| 公网地址枯竭 | “无限”地址、层次化分配 |
| 包头设计不合理 | 简化的报文头部 |
| 路由表过大 | 便于聚合 |
| 对 ARP 依赖导致广播泛滥 | 邻居发现等机制 |
| — | 即插即用、安全特性、移动性、增强 QoS、保证端到端完整性 |

IPv6 优势展开：近乎无限地址空间（128 bit）；层次化地址结构；SLAAC 即插即用；端到端完整性（减少 NAT）；IPsec 原生设计；扩展头可扩展；移动性改善；流标签增强 QoS。

### IPv6 过渡技术

短时间内 IPv6 和 IPv4 将会共存，主要有三种技术：

1. **双栈**：设备同时启用 IPv4 与 IPv6 协议栈
2. **隧道**：将一种协议数据封装在另一种协议中
3. **转换**：IPv6 与 IPv4 地址/报文转换（如 NAT64/DNS64）

没有最好的单一过渡技术，通常是多种技术组合。

### IPv6 路由协议简介

| 协议 | 要点 |
| --- | --- |
| OSPFv3 | 基于链路运行，单链路支持多实例；与网络层协议解耦；新 LSA 支持 IPv6 路由发布 |
| IS-IS for IPv6 | 原有协议简单扩展；新增 NLPID/TLV 宣告 IPv6 |
| BGP4+ | MP-BGP 支持 IPv6 地址族；新 NLRI 发布 IPv6 可达路由 |
| PIM | 协议无关组播；区别在于协议与数据报文使用 IPv6 地址 |
