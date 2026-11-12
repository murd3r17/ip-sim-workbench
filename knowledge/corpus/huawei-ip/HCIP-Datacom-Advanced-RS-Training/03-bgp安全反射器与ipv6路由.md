---
doc_id: "hcip-datacom-advanced-rs-training-03"
title: "BGP安全反射器与IPv6路由"
book: "HCIP-Datacom-Advanced-RS-Training"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "training"
source_pdf: "HCIP-Datacom-Advanced+Routing+&+Switching+Technology+V1.0+培训教材(1).pdf"
seq: 3
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# BGP安全反射器与IPv6路由

## 1. BGP 认证与 GTSM

BGP 使用 TCP 传输。只要源/目的地址、端口与序号正确，BGP 即认为报文有效，攻击者易于伪造。可在邻居间使用 **MD5** 或 **Keychain** 认证降低被攻击可能。

- MD5：配置简单，单一密码，需人工更换
- Keychain：一组密码可自动切换，配置较复杂，适合高安全要求网络
- 注意：MD5 与 Keychain 认证互斥

```cli
[Huawei-bgp] peer { group-name | ipv4-address | ipv6-address } keychain keychain-name
```

未使能 GTSM 时，大量非法 BGP 报文会直接上送控制面，导致 CPU 飙高。GTSM 通过检查 TTL 过滤非法报文。

```cli
[Huawei-bgp] peer { group-name | ipv4-address | ipv6-address } valid-ttl-hops [ hops ]
[Huawei] gtsm default-action { drop | pass }
[Huawei] gtsm log drop-packet all
```

配置 `hops` 后，有效 TTL 范围为 `[255-hops+1, 255]`；`hops` 缺省 255。

### GTSM 配置举例

AS101 内 R1/R2/R3 用 Loopback0 建立 IBGP 全互联并开启 GTSM。

| 设备 | 接口 | 地址 |
| --- | --- | --- |
| R1 | Loopback0 | 10.1.1.1/32 |
| R2 | Loopback0 | 10.1.2.2/32 |
| R3 | Loopback0 | 10.1.3.3/32 |

直连邻居 `valid-ttl-hops 1`（TTL 有效范围 [255,255]）；经一跳的 R1–R3 取 `valid-ttl-hops 2`（[254,255]）：

```cli
[R1-bgp] peer 10.1.2.2 valid-ttl-hops 1
[R2-bgp] peer 10.1.1.1 valid-ttl-hops 1
[R2-bgp] peer 10.1.3.3 valid-ttl-hops 1
[R3-bgp] peer 10.1.2.2 valid-ttl-hops 1
[R1-bgp] peer 10.1.3.3 valid-ttl-hops 2
[R3-bgp] peer 10.1.1.1 valid-ttl-hops 2
```

查看：`display bgp peer 10.1.3.3 verbose`，可见 `GTSM has been enabled, valid-ttl-hops: 2`。

## 2. BGP 路由反射器

### 2.1 角色与发布规则

| 角色 | 说明 |
| --- | --- |
| RR | 可将从 IBGP 学到的路由反射给其他 IBGP 对等体 |
| Client | 与 RR 形成反射邻居；AS 内只需与 RR 直连 |
| Non-Client | 非 RR 也非客户机；与 RR 及非客户机之间仍需全互联 |
| Originator | AS 内始发路由的设备；Originator_ID 防集群内环路 |
| Cluster | RR 及其客户机集合；Cluster_List 防集群间环路 |

指定 RR 时需指定 Client；Client 本身无需配置，不知网络中存在 RR。

发布规则：

- 从非客户机学到的路由 → 发布给所有客户机
- 从客户机学到的路由 → 发布给所有非客户机和客户机
- 从 EBGP 学到的路由 → 发布给所有非客户机和客户机

### 2.2 备份 RR 组网

同一集群配置多个 RR 防单点故障；转发路径上路由器与所有 RR 建 IBGP。同集群 RR 配置相同 Cluster ID：互相反射时发现 Cluster_List 已含本 Cluster ID 则丢弃，避免环路。

### 2.3 多集群与分级 RR

一个 AS 可有多个集群，各集群 RR 之间建 IBGP（同级全互联）。客户机只与本集群 RR 建连，仍能收到全部路由。

分级 RR 设计需考虑：顶层全互联规模；可替代路径数量（层次越多负载分担链路越少，资源消耗更少）。分级与单级发布规则相同。

### 2.4 单集群问题与多集群设计

备份 RR 同 Cluster ID 时，RR 之间更新被丢弃。若某客户机与一台 RR 的 IBGP 失效，可能失去冗余。多集群设计（不同 Cluster）可在 IBGP 会话失效时仍通过另一集群学习路由，提供逻辑冗余。

## 3. BGP 高级特性思考题与总结

1. 关于 AS_Path 匹配的选择题（原文题干部分 OCR 残缺，保留考点：路径属性匹配）
2.（判断）BGP 的 GTSM 可以预防非法 BGP 邻居建立
3.（判断）备份 RR 组网中，主备 RR 收到对方反射路由会丢弃以避免环路

**总结：** AS_Path Filter / Community Filter 实现路由控制；ORF、对等体组、安全特性提升性能与安全；RR 打破 IBGP 水平分割，常见备份 RR 与多集群组网。

---

## 4. IPv6 路由概述

随着 IPv4 地址不足，IPv6 势在必行。IPv6 同样支持静态路由与动态路由：OSPFv3，以及对 IS-IS、BGP 的扩展（BGP4+）。

### 学习目标

- 实现 IPv6 静态路由配置
- 分析 OSPFv3 与 OSPFv2 不同点并完成基本配置
- 描述 IS-IS 对 IPv6 的扩展并完成配置
- 描述 BGP 对 IPv6 的扩展并完成 BGP4+ 配置

### 课程内容

1. IPv6 静态路由  
2. OSPFv3 原理与配置  
3. IS-IS（IPv6）原理与配置  
4. BGP4+ 原理与配置  

## 5. IPv6 静态路由

与 IPv4 静态主要差别在目的与下一跳使用 IPv6 地址。

```cli
[Huawei] ipv6 route-static dest-ipv6-address prefix-length { interface-type interface-number [ nexthop-ipv6-address ] | nexthop-ipv6-address | vpn-instance vpn-destination-name nexthop-ipv6-address } [ preference preference ] [ permanent | inherit-cost ] [ description text ]
```

- `preference`：1～255，缺省 60
- `permanent`：永久发布
- `inherit-cost`：继承迭代路由开销
- `description`：1～80 字符

VPN 实例静态还可指定 `public` 表示下一跳为公网地址。

### 配置举例

```cli
[R1] ipv6 route-static 2001:DB8:2345:2:2 128 2001:DB8:2345:12:2
[R2] ipv6 route-static 2001:DB8:2345:1:1 128 2001:DB8:2345:12:1
[R1] ping ipv6 2001:DB8:2345:2:2
```

| 设备 | 接口 | IPv6 地址 |
| --- | --- | --- |
| R1 | GE0/0/1 | 2001:DB8:2345:12:1/64 |
| R1 | Loopback0 | 2001:DB8:2345:1:1/128 |
| R2 | GE0/0/1 | 2001:DB8:2345:12:2/64 |
| R2 | Loopback0 | 2001:DB8:2345:2:2/128 |

## 6. OSPFv3 概述与原理

OSPFv2 面向 IPv4，OSPFv3 面向 IPv6，二者不兼容。OSPFv3 主要目标是开发独立于具体网络层的路由协议，内部路由器信息被重新设计。

相同点包括对特殊区域、虚连接、多进程等支持（细节见 Core 课程）。

### 与 OSPFv2 的主要不同

- 基于链路运行与拓扑计算，不再基于网段
- 支持一条链路多个实例（Instance ID）
- 报文与 Router-LSA/Network-LSA 中不含 IP 地址；新 LSA 承载 IPv6 前缀；LSA 定义泛洪范围
- 邻居仅由 Router ID 标识（非接口 IPv4 地址）
- 使用链路本地地址发送 OSPFv3 报文（虚连接除外）

IPv6 中链路与前缀分离：同链路节点即使前缀不同也可通信。

### 报文类型

Hello、DD、LSR、LSU、LSAck——作用与 OSPFv2 类似。头部含 Version=3、Type、Packet length、Router ID、Area ID、Checksum 等；Hello 含 Rtr Pri、Options（AT/DC/R/NP/MC/E/V6 等）、HelloInterval、DeadInterval、DR/BDR ID、Neighbor ID。

### LSA 类型与范围

LS Type 高位含 U（未知 LSA 处理）与 S2/S1（泛洪范围：链路本地 / 区域 / AS）。常见 LSA：Router、Network、Inter-Area-Prefix、Inter-Area-Router、AS-External、NSSA、Link-LSA、Intra-Area-Prefix-LSA。

PrefixOptions 含 P/MC/LA/NU 等位。AS-External 含 E（Metric 类型）、F（FA 存在）、T（Tag 存在）等。

Intra-Area-Prefix-LSA：链路或前缀变化时发送，**不触发 SPF 计算**。

查看示例：

```cli
[R2] display ospfv3 lsdb intra-prefix
```

## 7. OSPFv3 基本配置

配置方式与 OSPFv2 类似。接口网络类型：

```cli
[Huawei-GigabitEthernet0/0/1] ospfv3 network-type { broadcast | nbma | p2mp [ non-broadcast ] | p2p } [ instance instance-id ]
```

进入区域：`[Huawei-ospfv3-1] area area-id`

查看 LSDB：`display ospfv3 [ process-id ] lsdb ...`

### OSPF 双栈配置举例（续至下一章）

场景：公司已部署 OSPFv2，同时部署 OSPFv3 做 IPv6 测试；三区域；各路由器学到 AS 内全部 IPv4/IPv6 路由。

部署 IPv4（以 R1/R2/R3 片段为例）：

```cli
[R1] ospf 1 router-id 10.1.1.1
[R1-ospf-1] area 1
[R1-ospf-1-area-0.0.0.1] network 10.1.12.1 0.0.0.0
[R2] ospf 1 router-id 10.1.2.2
[R2-ospf-1] area 1
[R2-ospf-1-area-0.0.0.1] network 10.1.12.2 0.0.0.0
[R2-ospf-1] area 0
[R2-ospf-1-area-0.0.0.0] network 10.1.23.2 0.0.0.0
[R3] ospf 1 router-id 10.1.3.3
[R3-ospf-1] area 0
[R3-ospf-1-area-0.0.0.0] network 10.1.23.3 0.0.0.0
[R3-ospf-1] area 2
[R3-ospf-1-area-0.0.0.2] network 10.1.35.3 0.0.0.0
```

部署 IPv6：全局/接口使能 IPv6 后启动 OSPFv3，接口下 `ospfv3 1 area x`。（接口使能细节与验证见下一章。）
