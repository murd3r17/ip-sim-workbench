---
doc_id: "hcip-datacom-advanced-rs-training-01"
title: "IGP高级特性"
book: "HCIP-Datacom-Advanced-RS-Training"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "training"
source_pdf: "HCIP-Datacom-Advanced+Routing+&+Switching+Technology+V1.0+培训教材(1).pdf"
seq: 1
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# IGP高级特性

OSPF 和 IS-IS 都是基于链路状态的内部网关路由协议，运行这两种协议的路由器通过同步 LSDB，采用 SPF 算法计算最优路由。

- 当网络拓扑发生变化时，OSPF 和 IS-IS 支持多种快速收敛和保护机制，能够降低网络故障导致的流量丢失。
- 为控制路由表规模，OSPF 和 IS-IS 支持路由选路及路由信息控制，减少特定路由器路由表大小。
- 本节介绍 OSPF 和 IS-IS 的高级特性，包括快速收敛机制、路由控制等。

## 学习目标

学完本课程后，您将能够：

- 描述 OSPF 和 IS-IS 的各种快速收敛技术
- 实现 OSPF 和 IS-IS 等价路由的配置
- 实现 OSPF 和 IS-IS 发布缺省路由
- 描述 OSPF 和 IS-IS 多进程使用场景
- 描述 OSPF 转发地址的使用场景
- 描述 IS-IS 的 LSP 分片扩展工作原理

## 课程内容

1. OSPF 快速收敛
2. OSPF 路由控制
3. OSPF 其他特性
4. IS-IS 高级特性

---

## 1. OSPF 快速收敛

### 1.1 概述

OSPF 快速收敛是为提高路由收敛速度而做的扩展特性，包括：PRC（Partial Route Calculation，部分路由计算）和智能定时器。同时，OSPF 支持故障恢复快速收敛，例如通过 OSPF IP FRR（Fast Reroute）实现备份链路快速切换，也可与 BFD 联动实现对故障的快速感知。

### 1.2 PRC

PRC 工作原理：当网络上路由发生变化时，只对发生变化的路由重新计算。PRC 不计算节点路径，而是根据 SPF 算法算出的最短路径树来更新路由。

> （原图：以 R1 为根的最短路径树；R5 新增 Loopback0 网段后，最短路径树不变，只在节点 R5 上新增叶子。）

场景说明：

1. 网络收敛后，以 R1 为根的最短路径树已形成；R1 访问 R5 时，经 R1 下行出接口与 R3 上行接口 IP 到达。
2. R5 将 Loopback0 开启 OSPF，域内新增网段。
3. PRC 计算：R5 全网泛洪新增 LSA；R1 收到后创建新路由，继承原有访问 R5 的路径及下一跳——最短路径树不变，只在节点 R5 上新增叶子。
4. 因此 R1 访问 R5 的 Loopback0 时，仍经原路径到达。

在路由计算中，节点代表路由器，叶子代表路由，PRC 只处理变化的叶子信息。价值：OSPF 网络新增网段时，只关注发生变化的路由，加快路由计算。

### 1.3 智能定时器

如果触发路由计算的时间间隔较长，同样会影响收敛速度。智能定时器首次超时时间固定；若超时前又有触发事件，则下一次超时时间会增加。

**LSA 产生间隔：**

```cli
[Huawei-ospf] lsa-originate-interval { 0 | { intelligent-timer max-interval start-interval hold-interval | other-type interval } }
```

- `0`：取消 LSA 的 5 秒更新间隔
- `intelligent-timer`：通过智能定时器设置 Router LSA / Network LSA 更新间隔
- `max-interval`：最长间隔，1～120000 ms，缺省 5000
- `start-interval`：初始间隔，0～60000 ms，缺省 500
- `hold-interval`：基数间隔，1～60000 ms，缺省 1000
- `other-type interval`：除 Router/Network LSA 外其他 LSA 更新间隔，0～10 s，缺省 5

**LSA 到达间隔：**

```cli
[Huawei-ospf-1] lsa-arrival-interval { interval | intelligent-timer max-interval start-interval hold-interval }
```

- `interval`：接收间隔，0～10000 ms
- 智能定时器参数含义类似；`max-interval` 缺省 1000 ms，`start-interval`/`hold-interval` 缺省 500 ms

**SPF 调度间隔：**

```cli
[Huawei-ospf-1] spf-schedule-interval { interval1 | intelligent-timer max-interval start-interval hold-interval | millisecond interval2 }
```

- `interval1`：1～10 s
- `millisecond interval2`：1～10000 ms
- 智能定时器：`max-interval` 缺省 10000 ms，`start-interval` 缺省 500，`hold-interval` 缺省 1000

### 1.4 OSPF IP FRR

OSPF IP FRR 是动态 IP FRR，利用 LFA（Loop-Free Alternates）算法预先计算备份路径并保存在转发表中，故障时将流量快速切换到备份链路，可将故障恢复时间降低到 50 ms 以内。

LFA 基本思路：以可提供备份链路的邻居为根，用 SPF 计算到目的的最短距离，再按不等式选出开销最小且无环的备份链路。

流量保护类型：

- **链路保护**：保护经过特定链路的流量
- **节点链路双保护**：保护经过特定设备的流量；节点保护优先级高于链路保护

#### 基础配置

1. 使能 OSPF IP FRR：

```cli
[Huawei-ospf-1] frr
[Huawei-ospf-1-frr] loop-free-alternate
```

2.（可选）阻止接口 FRR 能力：

```cli
[Huawei-GigabitEthernet0/0/1] ospf frr block
```

对承载重要业务的节点，可在指定接口禁止 OSPF IP FRR，避免对端成为备份路径节点而影响业务。

#### 配置举例

需求：R1 与 R3 链路故障时，流量经 R2 快速切换。

| 设备 | Router ID | 接口 | IP 地址 |
| --- | --- | --- | --- |
| R1 | 10.1.1.1 | GE0/0/0 | 10.1.13.1/24 |
| R1 | | GE0/0/1 | 10.1.12.1/24 |
| R2 | 10.1.2.2 | GE0/0/1 | 10.1.12.2/24 |
| R2 | | GE0/0/2 | 10.1.23.2/24 |
| R3 | 10.1.3.3 | GE0/0/0 | 10.1.13.3/24 |
| R3 | | GE0/0/1 | 10.1.34.3/24 |
| R3 | | GE0/0/2 | 10.1.23.3/24 |
| R4 | 10.1.4.4 | GE0/0/1 | 10.1.34.4/24 |

1. 配置接口地址及 OSPF（略）
2. 配置开销（以 R1 为例，R2/R3/R4 类似）：

```cli
[R1] interface GigabitEthernet 0/0/0
[R1-GigabitEthernet0/0/0] ospf cost 10
[R1-GigabitEthernet0/0/0] quit
[R1] interface GigabitEthernet 0/0/1
[R1-GigabitEthernet0/0/1] ospf cost 10
[R1-GigabitEthernet0/0/1] quit
```

3. 在 R1 使能 OSPF IP FRR：

```cli
[R1] ospf
[R1-ospf-1] frr
[R1-ospf-1-frr] loop-free-alternate
[R1-ospf-1-frr] quit
[R1-ospf-1] quit
```

验证：

```cli
[R1] display ospf routing 10.1.34.4
```

使能 IP FRR 后，路由中会出现 Backup Nexthop / Backup Interface（如 BackupType LFA LINK）。

### 1.5 BFD 联动

OSPF 默认通过 Hello / Dead Timer（缺省 40 s）检测邻居失效，对语音视频等敏感业务不够。配置进程或接口 OSPF 与 BFD 联动，可将故障检测提升到毫秒级。

前提：系统视图执行 `bfd` 使能全局 BFD。接口 BFD 优先级高于进程 BFD。

也可将 OSPF IP FRR 与 BFD 绑定，快速感知故障并切换备份路径：

```cli
[Huawei-ospf-1] bfd all-interfaces { min-rx-interval receive-interval | min-tx-interval transmit-interval | detect-multiplier multiplier-value | frr-binding }
```

- `min-rx-interval` / `min-tx-interval`：10～2000 ms，缺省 1000
- `detect-multiplier`：3～50，缺省 3
- `frr-binding`：BFD Down 时绑定接口物理层 Down，触发切备份路径

---

## 2. OSPF 路由控制

本课程重点介绍等价路由、缺省路由、对 LSA 的过滤；其他内容请参考《HCIP-Datacom-Core Technology》。

### 2.1 等价路由

```cli
[Huawei-ospf-1] maximum load-balancing number
```

`number` 为等价路由最大数量，取值因设备型号而异。

**配置举例：** 要求 R1 既可经 R1–R3，也可经 R1–R2–R3 访问 R3 环回。

```cli
[R1] ospf
[R1-ospf-1] maximum load-balancing 2
[R1] display ip routing-table
```

路由表中可见同一目的两条 OSPF 下一跳（如 10.1.13.3 / 10.1.12.2）。

### 2.2 缺省路由

缺省路由目的与掩码均为 0。Type3 缺省优先级高于 Type5/Type7。

| 区域类型 | 行为要点 |
| --- | --- |
| 普通区域 | 默认不产生缺省；需 `default-route-advertise`，产生 Type5 ASE LSA |
| Stub | ABR 自动产生 Type3 缺省 |
| Totally Stub | ABR 自动产生 Type3 缺省；不允许 Type3/Type5 区域内传播 |
| NSSA | ABR 可产生 Type7 缺省；或 ASBR 上 `nssa default-route-advertise`（需路由表有缺省） |
| Totally NSSA | ABR 自动下发 Type3 缺省；ASBR 不会自动下发，需手工配置 |

```cli
[Huawei-ospf-1] default-route-advertise [ [ always | permit-calculate-other ] | cost cost | type type | route-policy route-policy-name [ match-any ] ]
```

- `always`：无论是否有激活的非本 OSPF 缺省都发布，且不再计算其他设备缺省
- `permit-calculate-other`：有非本 OSPF 缺省才发布，仍计算其他设备缺省
- `type`：外部路由类型 1 或 2，缺省 2
- `route-policy` / `match-any`：按策略决定是否/如何发布

```cli
[Huawei-ospf-1] default-route-advertise summary cost cost
```

`summary`：发布 Type3 缺省 LSA（需先使能 VPN）。

### 2.3 LSA 过滤

接口出方向过滤：

```cli
[Huawei-GigabitEthernet0/0/1] ospf filter-lsa-out { all | { summary [ acl { acl-number | acl-name } ] | ase [ acl { acl-number | acl-name } ] | nssa [ acl { acl-number | acl-name } ] } }
```

区域出方向过滤：

```cli
[Huawei-ospf-1-area-0.0.0.1] filter { acl-number | acl-name acl-name | ip-prefix ip-prefix-name | route-policy route-policy-name } export
```

### 2.4 LSDB Overflow

外部路由过多可能导致无法正常处理。可限制 External LSA 最大条目：

```cli
[Huawei-ospf-1] lsdb-overflow-limit number
```

`number`：1～1000000。

为避免数据库超限，可设非缺省外部路由数量上限；达到上限进入 Overflow 状态，启动定时器（默认 5 s），超时后检查是否仍超限以决定退出或重启定时器。进入 Overflow 时删除自己产生的非缺省外部路由，不产生/丢弃新的非缺省外部路由。

### 2.5 路由控制配置举例

需求：R2 不向 Area1 注入 Type3 LSA，并发布缺省路由，使 R3 可经缺省访问其他区域。

```cli
[R2] acl 2000
[R2-acl-basic-2000] rule deny
[R2-acl-basic-2000] quit
[R2] ospf
[R2-ospf-1] area 1
[R2-ospf-1-area-0.0.0.1] filter 2000 import
[R2-ospf-1] default-route-advertise always
```

验证：`display ospf lsdb` 中 Area1 无 Type3，有 Type5 缺省；`display ip routing-table` 可见 `0.0.0.0/0` O_ASE。

### 2.6 园区流量出口与内部路径控制案例

需求概要：财务/市场部分别控制出口与内部路径；边界引入 Type2 外部路由并设不同 Cost；调整汇聚–核心、核心–边界开销实现路径优选与故障切换。

> （原图：边界 R1/R2、核心 S1/S2、汇聚 S3/S4；财务/市场服务器与客户端分区。）

R1 引入静态（Cost 100）示例：

```cli
[R1] acl 2000
[R1-acl-basic-2000] rule permit source 192.168.10.0 0.0.0.255
[R1-acl-basic-2000] quit
[R1] route-policy static2ospf permit node 10
[R1-route-policy] if-match acl 2000
[R1-route-policy] apply cost 100
[R1-route-policy] quit
[R1] route-policy static2ospf permit node 20
[R1-route-policy] quit
[R1] ospf
[R1-ospf-1] import-route static route-policy static2ospf type 2
```

R2 类似，`apply cost 200`。接口开销示例：

```cli
[R1] interface GigabitEthernet 0/0/1
[R1-GigabitEthernet0/0/1] ospf cost 50
```

---

## 3. OSPF 其他特性

### 3.1 多进程与 VPN

创建 OSPF 进程时若指定 VPN 实例，则进程属于该实例，否则属于全局实例。

### 3.2 OSPF 与 BGP 联动 / Stub Router

IGP 比 BGP 收敛快时，故障恢复可能导致流量黑洞。可用 Stub Router：

```cli
[Huawei-ospf-1] stub-router [ on-startup [ interval ] ]
```

- 未配 `on-startup`：始终为 Stub，相关 Cost 为 65535
- 配 `on-startup`：仅重启/故障期间保持 Stub，`interval` 缺省 500 s

### 3.3 转发地址 FA

FA（Forwarding Address）：到达所通告目的的数据包应转发到的地址；若为 0.0.0.0，则转发到始发 ASBR。Type5 / Type7 LSA 中的 FA 可在特殊场景避免次优路径。

无 FA 问题：ASBR 引入静态后，其他路由器可能把下一跳指到 ASBR，路径次优。设置 FA 为真实下一跳后，计算路由时下一跳指向 FA，可走更优路径。

NSSA Type7→Type5：缺省由 Router ID 最大的 ABR 转换；仅 P-bit 置位且 FA 非 0 的 Type7 可转换；ABR 产生的 Type7 缺省不置位 P-bit。

---

## 4. IS-IS 高级特性（本篇起）

### 4.1 快速收敛概述

IS-IS 快速收敛包括：I-SPF、PRC、智能定时器、LSP 快速扩散；并支持 Auto FRR 与 BFD 联动。

I-SPF：除首次全量计算外，之后只计算受影响节点，再与 PRC 结合更新叶子，降低 CPU 占用。

LSP 快速扩散：

```cli
[Huawei-isis-1] flash-flood [ lsp-count | max-timer-interval interval | [ level-1 | level-2 ] ]
```

- `lsp-count`：每接口一次扩散最大 LSP 数，1～15，缺省 5
- `max-timer-interval`：10～50000 ms，缺省 10

### 4.2 等价路由

可采用负载分担，或配置等价路由优先级（不负载分担，优最高优先级下一跳）。

```cli
[Huawei-isis-1] maximum load-balancing number
[Huawei-isis-1] nexthop ip-address weight value
```

`weight` 越小优先级越高，取值 1～254。

**负载分担举例：**

```cli
[R1] isis
[R1-isis-1] maximum load-balancing 2
[R1] display ip routing-table
```

**优先级举例：**

```cli
[R1] isis
[R1-isis-1] nexthop 10.1.13.3 weight 1
[R1-isis-1] nexthop 10.1.12.2 weight 2
```

（IS-IS 缺省路由、多进程、LSP 分片扩展等内容见下一章。）
