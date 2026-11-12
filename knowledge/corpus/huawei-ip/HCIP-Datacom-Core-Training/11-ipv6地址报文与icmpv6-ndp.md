---
doc_id: "hcip-datacom-core-training-11"
title: "IPv6地址、报文结构与ICMPv6/NDP"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 11
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# IPv6地址、报文结构与ICMPv6/NDP

## 被请求节点组播地址

在 IPv6 中，ARP 及广播都被取消。当设备需要请求某个 IPv6 地址对应的 MAC 地址时，仍发送请求报文，但该报文是组播报文，其目的 IPv6 地址是目标 IPv6 单播地址对应的**被请求节点组播地址**。由于只有目标节点才会侦听这个地址，所以不会占用其他非目标节点的网络性能。

示例：PC1 发送数据至 PC2 前，使用 ICMPv6 的 NS/NA 实现地址解析。NS 报文目的地址为目标单播地址对应的被请求节点组播地址（如 FF02::1:FF84:EFDC）。

## 任播地址（Anycast）

任播过程涉及一个任播报文发起方和一个或多个响应方。任播地址与单播地址在格式上无任何差异，区别是一台设备可以给多台具有相同地址的设备发送报文。

优势：

- **业务冗余**：多台使用相同地址的服务器提供同一服务；一台故障时可自动与另一台通信。
- **更优服务**：基于路由优选，用户优先访问距离更近的服务器，降低时延。

## IPv6 与 IPv4 地址比较

| 对比项 | IPv4 | IPv6 |
| --- | --- | --- |
| 表示方式 | 点分十进制 | 冒号隔开的十六进制 |
| 地址类型 | 单播、组播、广播 | 单播、组播、任播 |
| 主类地址 | A、B、C 等 | 无此概念 |
| 组播 | 224.0.0.0/4 | FF00::/8 |
| 广播 | 有 | 无 |
| 未指定 | 0.0.0.0/32 | ::/128 |
| 环回 | 127.0.0.0/8 | ::1/128 |
| 公网 | 公网 IP | 全球单播地址 |
| 私网 | 10/8、172.16/12、192.168/16 | 唯一本地地址（FD00::/8） |
| 链路本地类 | APIPA 169.254.0.0/16 | 链路本地地址 FE80::/10 |

## IPv6 地址格式与结构

- 长度为 128 bit，一般用冒号分割为 8 段，每段 16 bit，段内十六进制表示。字母大小写不敏感。
- 用“IPv6 地址/掩码长度”表示，例如 `2001:0DB8:2345:CD30:1230:4567:89AB:CDEF/64`。
- 可分为：**网络前缀**（n bit）与**接口标识**（128−n bit）。

常用前缀：

| 地址或前缀 | 含义 |
| --- | --- |
| 2001::/16 | 用于 IPv6 Internet，类似 IPv4 公网地址 |
| 2002::/16 | 用于 6to4 隧道 |
| FE80::/10 | 链路本地地址 |
| FF00::/8 | 组播地址 |
| ::/128 | 未指定地址 |
| ::1/128 | 环回地址 |

接口 ID 产生方式：IEEE EUI-64（由 48 位 MAC 生成：第 7 bit 置 1，中间插入 FFFE）；设备随机生成；手动配置。

## IPv6 地址类型

- **单播（Unicast）**：标识一个接口
- **组播（Multicast）**：标识多个接口
- **任播（Anycast）**：标识一组接口，发往路由意义上最近的一个
- IPv6 **没有**定义广播地址

### 常见单播地址

**GUA（Global Unicast Address，全球单播地址）**：全球唯一，用于需互联网访问的主机，相当于 IPv4 公网地址。结构：全局路由前缀 + 子网 ID + 接口标识。全局路由前缀一般至少 48 bit。地址块示例：2000::/3。

**ULA（Unique Local Address，唯一本地地址）**：IPv6 私网地址，公网不可路由。使用 FC00::/7，目前主要使用 FD00::/8（FC00::/8 预留扩展）。

**LLA（Link-Local Address，链路本地地址）**：前缀 FE80::/10，有效范围本地链路。用于无状态自动配置、邻居发现等。每一个 IPv6 接口都必须具备一个链路本地地址。华为设备支持自动生成和手工指定。

### IPv6 组播地址结构

由前缀（FF::/8）、Flags、Scope、Group ID 组成。

- Flags：0000 永久组播地址；0001 临时组播地址
- Scope：1 节点本地；2 链路本地；5 站点本地；8 组织本地；E 全球；F 预留

IPv6 组播 MAC：以太网上对应 MAC 为 `0x3333` + 组播 IP 后 32 bit 的直接映射。

## IPv6 地址规划建议

- 根据获取到的地址前缀，确定子网地址划分为几个功能块，明确各功能块含义与占用 bit，避免浪费。
- ISP 获取前缀往往至少 /32；企业用户往往 /48。
- 确保全网唯一性（除 anycast 等特殊应用）；确保连续性、可聚合性、可扩展性。
- 业务地址：可规划适当 bit 承载业务信息、VLAN 信息或位置信息，利于路由规划、QoS 部署。
- 建议：Loopback 分配 /128；P2P 链路分配 /127；终端网段与 VLANIF 使用 /64。

## IPv6 报文结构

IPv6 数据报文由：

1. **IPv6 基本报头**：固定 40 字节，提供转发基本信息，路径上所有路由器解析。
2. **扩展报头**：可选，可有零个或多个，长度可变；一般由目的路由器解析处理。
3. **上层协议数据单元**：如 ICMPv6 / TCP / UDP。

基本报头字段：Version（6）、Traffic Class、Flow Label（新增，20 bit）、Payload Length、Next Header、Hop Limit、源/目的 IPv6 地址。

RFC 2460 定义的扩展头包括：逐跳选项、目的选项、路由、分段、认证（AH）、封装安全净载（ESP）等。扩展头总是 8 字节整数倍。Next Header 链式指明下一扩展头或上层协议类型。

## IPv6 / OSPFv3 基础配置

```cli
[Huawei] ipv6
[Huawei] interface interface-type interface-number
[Huawei-GigabitEthernet1/0/0] ipv6 enable
[Huawei-GigabitEthernet1/0/0] ipv6 address { ipv6-address prefix-length | ipv6-address/prefix-length }
```

每个接口下最多可配置 10 个全球单播地址。

```cli
[Huawei] ospfv3 [ process-id ]
[Huawei-ospfv3-1] router-id router-id
[Huawei] interface interface-type interface-number
[Huawei-GigabitEthernet1/0/0] ospfv3 process-id area area-id
```

OSPFv3 的 Router ID 必须手工配置，否则无法正常运行。

### 案例：配置双栈网络

需求：R1、R2 分别配置 OSPFv2 和 OSPFv3，实现 PC1 和 PC2 的双栈互访。

R1 示例：

```cli
[R1] ipv6
[R1] interface GigabitEthernet 1/0/0
[R1-GigabitEthernet1/0/0] ipv6 enable
[R1] interface GigabitEthernet 2/0/0
[R1-GigabitEthernet2/0/0] ipv6 enable
[R1] interface GigabitEthernet 1/0/0
[R1-GigabitEthernet1/0/0] ip address 10.0.12.1 24
[R1-GigabitEthernet1/0/0] ipv6 address 2001:DB8:1::1 64
[R1] interface GigabitEthernet 2/0/0
[R1-GigabitEthernet2/0/0] ip address 192.168.1.254 24
[R1-GigabitEthernet2/0/0] ipv6 address 2001:DB8:2::1 64

[R1] ospf 1 router-id 10.0.1.1
[R1-ospf-1] area 0
[R1-ospf-1-area-0.0.0.0] network 10.0.12.0 0.0.0.255
[R1-ospf-1-area-0.0.0.0] network 192.168.1.0 0.0.0.255

[R1] ospfv3
[R1-ospfv3-1] router-id 10.0.1.1
[R1-ospfv3-1] quit
[R1] interface gigabitethernet1/0/0
[R1-gigabitethernet1/0/0] ospfv3 1 area 0
[R1] interface gigabitethernet2/0/0
[R1-gigabitethernet2/0/0] ospfv3 1 area 0
```

R2 类似配置 OSPFv2/OSPFv3 及接口地址。可用 `ping ipv6` 验证连通性。

### IPv6 相对 IPv4 要点回顾

“无限”地址空间，层次化地址结构，即插即用，简化报文头部，安全特性，移动性，增强 QoS。报文层面：基本报头+扩展报头；取消 IP 校验与中间节点分片；定长基本报头利于硬件转发；支持 IPSec；增加流标签。

## ICMPv6 与 NDP

### ICMPv6 概述

ICMPv6 是 IPv6 的基础协议之一。IPv6 报文头部 Next Header 值为 58 对应 ICMPv6。用于通告相关信息或错误，并广泛应用于 NDP、Path MTU 发现等。控制地址自动配置、地址解析、地址冲突检测、路由选择以及差错控制等关键环节。

报文格式字段：Type、Code、Checksum；载荷因类型而异。

两类报文：

| 类别 | Type 范围 | 作用 |
| --- | --- | --- |
| 差错报文 | 0～127（最高 bit 为 0） | 报告转发错误，如目的不可达、超时、报文过大（Type=2，用于 PMTU） |
| 信息报文 | 128～255（最高 bit 为 1） | 节点通信、组播成员管理等 |

Ping：Echo Request（Type=128）、Echo Reply（Type=129）。

其它常用 Type：133 RS、134 RA、135 NS、136 NA、137 Redirect；以及 MLD 相关 130/131/132/143。

### NDP 概述

RFC 2461 定义 NDP，主要功能：路由器发现、无状态自动配置、重复地址检测、地址解析、邻居状态跟踪、前缀重编址、重定向。

使用报文：RS / RA / NS / NA / Redirect。

### 路由器发现

主机发现本地链路上路由器并确定配置信息的过程，包括：路由器发现、前缀发现、参数发现。使用 RS/RA：主机发送 RS 触发路由器回应 RA；路由器也可周期发送 RA。

可用 `ipv6 nd ra { max-interval ... | min-interval ... }` 配置发送周期。

### 地址解析（NS/NA）

PC1 不知 PC2 链路层地址时：发送 NS 到被请求节点组播地址，选项携带本端链路层地址；PC2 回复 NA 并携带自己的链路层地址；双方建立邻居缓存表项（类似 IPv4 ARP 表）。

### 邻居状态

可用 `display ipv6 neighbors` 查看。五种状态：Incomplete、Reachable、Stale、Delay、Probe。邻居可达时间缺省 30 秒；Probe 状态缺省每 1s 发送单播 NS。

### 重复地址检测（DAD）

节点在使用某地址前验证其在本地链路唯一。发送 NS；规定时间内无 NA 应答则认为唯一可用；若有冲突则不能配置到接口。两台主机同时争用同一地址时，后收到对方 NS 者停止使用并等待重新生成。

### 重定向

网关发现报文从其它网关转发更优时，发送重定向报文告知发送者选择更优下一跳。

### 思考题（ICMPv6/NDP）

1. ICMPv6 报文类型分为哪几大类？差错报文、信息报文
2. IPv6 地址解析通过哪些报文实现？NS、NA

## IPv6 地址配置方式（开篇）

IPv6 地址配置可分为静态配置和动态配置；动态又分为：

- **无状态地址自动配置（SLAAC）**：基于 NDP
- **有状态地址自动配置**：基于 DHCPv6

### SLAAC 过程概要

1. PC 根据本地接口 ID 自动生成链路本地地址并做 DAD。
2. PC 发送 RS，路由器回应 RA（携带可用于无状态配置的前缀）。
3. PC 用前缀 + 接口 ID 生成 IPv6 单播地址并再做 DAD。

RA 中 Flags：

- **M-bit**：为 1 时终端使用 DHCPv6 获取地址及其他信息（`ipv6 nd autoconfig managed-address-flag`）
- **O-bit**：为 1 时终端使用 DHCPv6 获取除地址之外的其他参数（`ipv6 nd autoconfig other-flag`）

前缀选项中 A-bit 指示终端能否使用该前缀做无状态自动配置。地址生命周期：Tentative → Preferred → Deprecated → Invalid（由 Preferred lifetime / Valid lifetime 控制）。

### DHCPv6 概述（开篇）

DHCPv6 针对 IPv6 编址方案设计，支持分配 IPv6 前缀、IPv6 地址和其他网络配置参数。分为：有状态自动配置、无状态自动配置（仅 DNS 等参数）、DHCPv6 PD（前缀代理）自动配置。

角色：DHCPv6 Client、Server、Relay。

有效时间（Valid Lifetime）不得小于优选时间（Preferred Lifetime）；Valid Lifetime 须不小于 3 小时，Preferred Lifetime 须不小于 2 小时。

四步交互：Solicit → Advertise → Request → Reply（详见下一章）。
