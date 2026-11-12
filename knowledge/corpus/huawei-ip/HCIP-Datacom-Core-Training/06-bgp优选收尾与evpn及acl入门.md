---
doc_id: "hcip-datacom-core-training-06"
title: "BGP优选收尾、EVPN基础与ACL入门"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 6
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# BGP优选收尾、EVPN基础与ACL入门

## BGP 优选规则 10：Router ID / Originator_ID

前序规则相同时，优选通告者 **Router ID（或 Originator_ID）更小**的路径。

示例：R1 上两条路径前序相同，来自 `10.0.3.3` 的详细信息标注：

```text
not preferred for router ID
```

在 RR 场景中，比较的实质是 **Originator_ID**（原始发布者 Router ID），提示仍可能写为 router ID。

## BGP 优选规则 11：对等体地址

仍相同时，优选**对等体 IP 更小**者通告的路由。例如来自 `10.0.3.3` 相对 `10.0.2.2` 可能标注：

```text
not preferred for peer address
```

### 思考题（优选）

1. （简答）EBGP 路由通告给 IBGP 时如何把 Next_Hop 改为自身更新源？→ 使用 **`peer next-hop-local`**。
2. （判断）前三条相同后比 AS_Path 长度，长度相同再比 AS 号大小？→ **错**（比长度，不比 AS 号大小）。

---

## MP-BGP 与 EVPN 基础

### 前言与目标

标准 BGP-4 主要面向 IPv4 单播。**MP-BGP**（RFC4760）扩展允许多地址族同时分发（IPv4 组播、IPv6、L3VPN、EVPN 等）。

学完应能：描述 MP-BGP 概念；描述 EVPN 起源；描述常见 EVPN 路由类型；描述典型应用场景。

### MP-BGP 要点

- BGP-4 中 IPv4 的 NEXT_HOP、AGGREGATOR 等在 Path Attributes，NLRI 携带 IPv4 路由。
- MP-BGP 新增属性，将对应网络层的下一跳与 NLRI 放入 **MP_REACH_NLRI**（及撤销用的 MP_UNREACH_NLRI）。
- SAFI：1 单播、2 组播（IANA 分配，原则见 RFC2434）。
- EVPN：AFI=**25**（L2VPN），SAFI=**70**（EVPN）。

### 从 VPLS 到 EVPN

- MPLS“多协议”指可承载多种网络层；用标签交换替代纯 IP 转发。
- **VPLS**：基于以太网的二层 VPN，在 MPLS 上提供类 LAN 业务，多站点接入互通。
- VPLS 存在多活接入、收敛、负载均衡等方面不足；需求见 RFC7209，EVPN 见 RFC7432 等。更多原理见 HCIE-Datacom《Ethernet VPN》。

### EVPN NLRI

EVPN 定义新的 BGP NLRI，承载于 MP_REACH_NLRI：

| 字段 | 说明 |
|------|------|
| AFI | 25 |
| SAFI | 70 |
| Length of Next Hop Network Address | 下一跳地址长度 |
| Network Address of Next Hop | EVPN 路由下一跳 |
| Reserved | 全 0 |
| NLRI | EVPN NLRI |

双方需通过能力通告确认可处理该 AFI/SAFI。Type-5 IP Prefix Route 等扩展见相关 draft。

### 应用场景摘要

- **数据中心**：EVPN NVO（RFC8365）+ 推荐 VXLAN 数据面，Spine-Leaf Underlay。
- **园区**：同类 Overlay 思路，VXLAN + EVPN。
- **SD-WAN**：控制面可结合 EVPN；Overlay 含站点前缀、TNP、IPSec 密钥等（详见 SD-WAN 课程）。
- **广域**：可与 MPLS/SR/VPLS/VPWS 等结合。

MEF EVC 类型回顾：E-LINE（点到点）、E-LAN（多点到多点）、E-TREE（根到多点，叶不互通）。

### 本章总结（EVPN）

- MP-BGP 支持多地址族并行分发。
- EVPN 用于解决以太网二层 VPN 等问题，并扩展到 DC、园区、广域、SD-WAN 等场景。

参考：RFC4760、RFC7209、RFC7432、RFC8365；MEF EVC 定义等。

---

## 路由控制入门：ACL 与地址前缀列表

> （原图：IS-IS/OSPF 多业务网段，按策略引入部分业务路由。）

### ACL 组成

- **ACL 编号**：标识 ACL，不同类型编号范围不同。
- **规则**：若干 `permit`/`deny` 语句。
- **规则编号**：0～4294967294，按编号从小到大排序。
- **动作**：permit / deny（结合流量过滤、路由过滤等时含义不同）。
- **匹配项**：源/目的地址、MAC、协议、TCP/UDP 端口等。

```cli
acl number 2000
 rule 10 deny source 2.2.2.0 0.0.0.255
 rule 15 permit source 3.3.3.0 0.0.0.255
 # 末尾系统隐含规则等
```

### 通配符（Wildcard）

- 点分十进制；二进制 **0=匹配，1=不关心**；可与掩码不同且 0/1 可不连续。
- 全 0：精确匹配主机。
- `0.0.0.255` 配 `192.168.1.0`：匹配 `192.168.1.0/24` 网段。
- 全 1 配 `0.0.0.0`：匹配所有地址。

路由过滤场景通常用**基本 ACL**；ACL **只能匹配前缀，不能匹配掩码长度**（掩码长度需用 IP-Prefix）。

### ACL 匹配机制

- 按规则逐条匹配，**一旦命中即停止**（不论 permit 还是 deny 都算“匹配”）。
- ACL 不存在 / 无规则 / 全部未命中 → “不匹配”。
- 匹配顺序：缺省 **config**（按规则号）；另有 **auto**（深度优先，较复杂）。

注意：与路由过滤结合时，permit≈匹配该路由，deny≈不匹配该路由。

### 基本 ACL 配置

```cli
[Huawei] acl [ number ] acl-number [ match-order config ]
# 或命名：acl name acl-name { basic | acl-number } [ match-order config ]

[Huawei-acl-basic-2000] rule [ rule-id ] { deny | permit } [ source { source-address source-wildcard | any } | time-range time-name ]
```

编号型基本 ACL：2000～2999。

### IP Prefix List（地址前缀列表）

可同时约束网络前缀与**掩码长度范围**。

```cli
[Huawei] ip ip-prefix test index 10 permit 192.168.1.0 22 greater-equal 24 less-equal 26
```

要素：名称、序号（缺省每次 +10，首个 10）、permit/deny、IP/掩码长度、`greater-equal` / `less-equal`（满足 `mask-length ≤ ge ≤ le ≤ 32`）。

```cli
ip ip-prefix List1 index 10 permit 1.1.1.0 24 greater-equal 24 less-equal 27
# 前 24bit 同 1.1.1.0，掩码长度 24～27；故 1.1.1.1/32 不匹配
```

完整命令形式：

```cli
[Huawei] ip ip-prefix ip-prefix-name [ index index-number ] { permit | deny } ipv4-address mask-length [ match-network ] [ greater-equal ge ] [ less-equal le ]
```

#### 匹配案例要点

- 单节点 `permit 10.1.1.0 24`：仅精确该前缀被 permit，其余默认 deny。
- 单节点 `deny 10.1.1.0 24`：该前缀命中但被 deny；其余未命中亦默认 deny。
- 多节点：先 deny 某前缀再 permit 另一前缀；或 `greater-equal 26 less-equal 32` 匹配更长掩码。
- `0.0.0.0` 作通配：可匹配“所有前缀”在指定掩码长度范围（如 deny 24～32 再 permit 0～32）。

### Filter-Policy 概念

- **距离矢量**：基于路由表，filter-policy 可影响接收/发布。
- **链路状态（如 OSPF）**：filter-policy 过滤的是**计算后准备进路由表的路由**，一般不直接滤除 LSDB 中的 LSA；出方向常用于过滤引入后向外发布的路由。

OSPF 示例命令：

```cli
[Huawei-ospf-100] filter-policy { acl-number | acl-name name | ip-prefix name | route-policy name [ secondary ] } import
[Huawei-ospf-100] filter-policy { acl-number | acl-name name | ip-prefix name | route-policy name } export [ protocol [ process-id ] ]
```

IS-IS / BGP 亦有对应 import/export 及 peer filter-policy（细节续后续文档）。

```cli
ospf 1
 filter-policy 2000 import
# 未通过者不上路由表，但不影响 LSA 泛洪本身

ospf 1
 import-route static
 filter-policy 2000 export
# 对引入后向外发布做过滤
```



## 规则 10 / 11 回显补充

```cli
# Router ID / Originator_ID 落选
not preferred for router ID

# 对等体地址落选
not preferred for peer address
Originator: 10.0.4.4
Cluster list: 10.0.3.3
```

RR 场景下“router ID”提示常对应 **Originator_ID** 比较。

## EVPN / MP-BGP 补充

### MP_REACH_NLRI 字节布局

| 字段 | 长度 | 说明 |
|------|------|------|
| Address Family Identifier | 2 | EVPN: 25 |
| Subsequent Address Family Identifier | 1 | EVPN: 70 |
| Length of Next Hop Network Address | 1 | 下一跳长度 |
| Network Address of Next Hop | 可变 | EVPN 下一跳 |
| Reserved | 1 | 全 0 |
| NLRI | 可变 | EVPN NLRI |

能力通告：capability code 1（multiprotocol BGP）携带 AFI 25 / SAFI 70。

### 相关标准与数据面（教材脉络）

- RFC7432：BGP MPLS-Based Ethernet VPN
- RFC8365：Network Virtualization Overlay using EVPN
- 数据面常见：VXLAN、MPLS、SR-MPLS、SRv6、GRE/IPSec 等（场景相关）
- Type-5 IP Prefix Route：标准化进程中见 draft-ietf-bess-evpn-prefix-advertisement

### EVC 三类服务

- **E-LINE**：点到点，两 UNI。
- **E-LAN**：多点到多点，可增删 UNI。
- **E-TREE**：根到多点；根可与所有 UNI 通信，叶之间不直接通信。

## ACL / Prefix-List / Filter-Policy 补充

### 通配符例题

- 拒绝主机 `10.1.1.1`：`deny source 10.1.1.1 0`
- 允许 `10.1.1.0/24`：`permit source 10.1.1.0 0.0.0.255`
- 匹配 `1.1.1` 前缀且主机号为奇数：`permit source 1.1.1.1 0.0.0.254`（示意）

### Prefix-List 多节点案例

```cli
ip ip-prefix aa index 10 deny 10.1.1.0 24
ip ip-prefix aa index 20 permit 10.1.1.1 32
# 10.1.1.0/24 命中 deny；10.1.1.1/32 在 index20 permit；其余默认 deny

ip ip-prefix bb index 10 permit 10.1.1.0 24 greater-equal 26 less-equal 32
# 同前 24bit，掩码长度 26～32

ip ip-prefix bb index 10 deny 0.0.0.0 24 less-equal 32
ip ip-prefix bb index 20 permit 0.0.0.0 0 less-equal 32
# 先拒绝掩码 24～32 的所有前缀，再允许其余（含更短掩码）
```

### Filter-Policy 在各协议中的命令位置

```cli
# IS-IS
[Huawei-isis-1] filter-policy { acl-number | acl-name name | ip-prefix name | route-policy name } import
[Huawei-isis-1] filter-policy { ... } export [ protocol [ process-id ] ]

# BGP IPv4 地址族
[Huawei-bgp-af-ipv4] filter-policy { acl-number | acl-name name | ip-prefix name } import
[Huawei-bgp-af-ipv4] filter-policy { ... } export [ protocol [ process-id ] ]
[Huawei-bgp-af-ipv4] peer { group | ipv4 } filter-policy { acl-number | acl-name name } { import | export }
```

距离矢量：过滤器影响收发路由。链路状态：import 多在“算路后进路由表前”过滤，不直接删 LSDB 中 LSA。


（R2 路由表等实验续见下一文档。）
