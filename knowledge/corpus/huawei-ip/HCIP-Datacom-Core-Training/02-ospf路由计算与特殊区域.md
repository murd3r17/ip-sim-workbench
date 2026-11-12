---
doc_id: "hcip-datacom-core-training-02"
title: "OSPF路由计算与特殊区域"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 2
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# OSPF路由计算与特殊区域

## OSPF 配置验证（续）

邻居表关注：邻居 Router ID、状态（Full / 2-Way / Down 等）。

```cli
<R2>display ospf peer
OSPF Process 1 with Router ID 10.0.2.2
 Area 0.0.0.0 interface 10.0.235.2(GigabitEthernet0/0/1)'s neighbors
 Router ID: 10.0.5.5          Address: 10.0.235.5
 State: Full  Mode:Nbr is Master  Priority: 1
 DR: 10.0.235.5  BDR: 10.0.235.3  MTU: 0
 Dead timer due in 40 sec
 Retrans timer interval: 0
 Neighbor is up for 00:01:27
 Authentication Sequence: [ 0 ]
 Area 0.0.0.0 interface 10.0.24.2(Serial1/0/1)'s neighbors
 Router ID: 10.0.4.4          Address: 10.0.24.4
 State: Full  Mode:Nbr is Master  Priority: 1
 DR: None   BDR: None   MTU: 0
 Dead timer due in 35 sec
 Retrans timer interval: 5
 Neighbor is up for 00:01:56
 Authentication Sequence: [ 0 ]
```

P2P 网络不选举 DR/BDR，故 Serial 接口上 DR/BDR 显示为 **None**。

### LSDB 与路由表验证

```cli
<R2>display ospf lsdb
OSPF Process 1 with Router ID 10.0.2.2
 Link State Database
 Area: 0.0.0.0
 Type     LinkState ID   AdvRouter   Sequence
 Router   10.0.4.4       10.0.4.4    80000006
 Router   10.0.2.2       10.0.2.2    8000000C
 Router   10.0.1.1       10.0.1.1    80000007
 Router   10.0.5.5       10.0.5.5    8000000B
 Router   10.0.3.3       10.0.3.3    80000009
 Network  10.0.235.5     10.0.5.5    80000005
 Network  10.0.12.2      10.0.2.2    80000003
```

- LSDB 由多种 LSA 构成，共用相同头部（Type、LinkState ID、AdvRouter 等）。
- `display ospf routing` 可确认已通过 OSPF 获知全网路由。

```cli
<R2>display ospf routing
OSPF Process 1 with Router ID 10.0.2.2
 Routing Tables
 Destination      Cost  Type     NextHop      AdvRouter   Area
 10.0.12.0/24     —     Transit  10.0.12.2    10.0.2.2    0.0.0.0
 10.0.24.0/24     —     Stub     10.0.24.2    10.0.2.2    0.0.0.0
 10.0.235.0/24    —     Transit  10.0.235.2   10.0.2.2    0.0.0.0
 10.0.13.0/24     —     Stub     10.0.12.1    10.0.1.1    0.0.0.0
 10.0.13.0/24     —     Stub     10.0.235.3   10.0.3.3    0.0.0.0
 10.0.45.0/24     —     Stub     10.0.235.5   10.0.5.5    0.0.0.0
```

### 思考题（OSPF 基础配置）

1. （单选）维护邻居关系用哪种报文？→ **A. Hello**
2. （多选）支持的网络类型？→ **A/B/C/D**（P2P、P2MP、广播、NBMA）

小结：OSPF 有 5 种报文、相同头部；周期性 Hello 发现/维持邻居；DD/LSR/LSU/LSAck 配合完成 LSDB 同步；本章介绍了单区域简单配置。

---

## OSPF 路由计算

LSDB 中各 LSA 含何信息？路由器如何据此完成路由计算？

### LSA 头部关键字段

| 字段 | 含义 |
|------|------|
| LS Age | 始发为 0，泛洪中累加；达 MaxAge（缺省 3600s）不再用于路由计算 |
| LS Sequence Number | 判断新旧/重复；范围 `0x80000001`～`0x7FFFFFFF`；更新时 +1，到最大后重新以 `0x80000001` 产生 |
| Options | 各 bit 对应协议特性 |
| LS Type | LSA 类型 |
| Link State ID | 随 LSA 类型而异 |
| Advertising Router | 产生该 LSA 的 Router ID |
| LS Checksum | 完整性校验 |
| Length | 含头部的总长度 |

- **Type + Link State ID + Advertising Router** 唯一标识一条 LSA。
- Age、Sequence、Checksum 用于判断新旧。
- 习惯称呼：1 类=Router LSA，2 类=Network LSA，以此类推。

LSU 可携带多种 LSA，各类共用相同头部。

### Router LSA（1 类）

标志位：

- **V**：虚连接端点则置 1
- **E**：ASBR 则置 1
- **B**：ABR 则置 1
- **#links**：链路数量

Link State ID = 产生者 Router ID。

| Link Type | 含义 | Link ID | Link Data |
|-----------|------|---------|-----------|
| Point-to-Point | 到邻居的 P2P（拓扑） | 邻居 Router ID | 本端接口 IP |
| TransNet | 到 Transit 网段（拓扑） | DR 接口 IP | 本端接口 IP |
| StubNet | 到 Stub 网段（网段信息） | 网络地址 | 网络掩码 |

### Network LSA（2 类）

由 DR 产生，描述 MA 网络中与之形成邻接的路由器及自身。

```cli
OSPF Process 1 with Router ID 10.0.2.2
 Area: 0.0.0.0
 Link State Database
 Type      : Network
 Ls id     : 10.0.235.2
 Adv rtr   : 10.0.2.2
 Net mask  : 255.255.255.0
 Attached Router    10.0.2.2
 Attached Router    10.0.3.3
 Attached Router    10.0.5.5
```

> （原图：DR 向邻居发送 Network-LSA，携带拓扑与网段信息 `10.0.235.0/24`。）

### SPF 计算要点

- 候选总开销 = 本 LSA 描述的 Metric + 父节点到根的开销。
- 候选列表本质记录邻居列表；同节点多 Cost 时取较小者加入最短路径树。
- 第二阶段根据 Router LSA 的 Stub、Network LSA 的路由信息完成最优路由计算；按节点加入 SPF 树的顺序添加叶子路由。

示例（以 R1 为根计算后）：

```cli
<R1>display ospf routing
 Destination        Cost  Type       NextHop     AdvRouter   Area
 10.0.12.0/24       1     Transit    10.0.12.1   10.0.1.1    0.0.0.0
 10.0.13.0/24       48    Stub       10.0.13.1   10.0.1.1    0.0.0.0
 10.0.24.0/24       49    Stub       10.0.12.2   10.0.2.2    0.0.0.0
 10.0.45.0/24       50    Stub       10.0.12.2   10.0.5.5    0.0.0.0
 10.0.235.0/24      2     Transit    10.0.12.2   10.0.5.5    0.0.0.0
```

全局路由表示例：直连 Pre=0；OSPF Pre=10，Cost 与上表对应。

### 思考题（路由计算）

1. （多选）Router-LSA 主要链路类型？→ **A/B/C/D**（P2P、TransNet、StubNet、Vlink）
2. （判断）SPF 算出的最优 OSPF 路由一定进全局路由表？→ **错**

---

## 多区域与区域间路由

单区域问题：LSDB 臃肿、变更全网泛洪重算、无法部署区域间汇总。

区域间路由通过 ABR 产生的 **Network Summary LSA（3 类）** 传递。

示例（`192.168.1.0/24`）：

1. R2 在 Area1 内由 1/2 类算出区域内路由，用 3 类通告到 Area0；
2. R3 据此算区域间路由，再重新生成 3 类注入 Area2；
3. 全网可学到该网段。

```cli
Type : Sum-Net
 Ls id : 192.168.1.0
 Adv rtr : 10.0.2.2
 Net mask : 255.255.255.0
 Tos0 metric: 1
```

R5 到达该网段 Cost = 自身到 ABR 的 Cost + 3 类中 Metric（示例中为 1+3=4）。

- 区域间传播类似距离矢量，需要防环。
- **ABR 至少有一个接口属于骨干区域**。
- 骨干区域必须连续（可为逻辑连续）；虚连接可使骨干逻辑连续，但违背区域间防环规则，某些场景可致环路，**不建议部署虚连接**。

虚连接配置示例：

```cli
[R2-ospf-1]area 1
[R2-ospf-1-area-0.0.0.1]vlink-peer 10.0.3.3
[R3-ospf-1]area 1
[R3-ospf-1-area-0.0.0.1]vlink-peer 10.0.2.2
```

防环要点：非骨干均直连唯一骨干；非骨干间通信经骨干中转；从骨干传来的 3 类 LSA **不再传回骨干**。

### 思考题（多区域）

1. （判断）一条 Network Summary LSA 只能描述一条路由？→ **对**
2. （简答）如何避免区域间环路？→ 骨干唯一且连续；非骨干经骨干中转；骨干来的 3 类不再回注骨干等。

---

## OSPF 外部路由引入

背景：部分链路未开 OSPF（连外网用静态/BGP，或服务器直连未开 OSPF）。

```cli
[R1]ospf 1
[R1-ospf-1]import-route { bgp [ permit-ibgp ] | direct | unr | rip [ process-id ] | static | isis [ process-id ] | ospf [ process-id ] } [ cost cost | type type | tag tag | route-policy name ] *
```

### 5 类 LSA（AS-External）

- **Forwarding Address**：为 `0.0.0.0` 时流量发往引入该路由的 ASBR；非 0 则发往该 FA，可规避次优路径。
- **External Route Tag**：外部路由标记，常用于策略。

```cli
[R1]ospf 1
[R1-ospf-1] import-route direct
```

R1 引入直连 `192.168.1.0/24` 后，AS-External-LSA 在整域泛洪。

同区域设备可据 1/2 类算出到 ASBR 的路由；跨区域还需 **4 类 ASBR-Summary LSA**（ABR 产生，描述到 ASBR 的可达）。

### 外部路由类型与开销

| 类型 | 描述 | 开销计算 |
|------|------|----------|
| Metric-Type-1 | 可信程度高 | AS 内部开销 + AS 外部开销 |
| Metric-Type-2（缺省） | 可信程度低，外部开销远大于内部 | 仅 AS 外部开销 |

```cli
[R1]ospf 1
[R1-ospf-1]import-route direct type 1 cost 1
```

Type1 时：R3 Cost = 外部 1 + 到 ASBR 内部开销；R5 类似叠加自身到 ASBR 的内部开销。

### 思考题（外部路由）

1. （多选）ABR 可能产生？→ **A/C/D** 等（含 ASBR-Summary、Router、Network Summary；5 类由 ASBR 产生）
2. （单选）同前缀优先级最高？→ **A. 区域内路由**

---

## OSPF 特殊区域及其他特性

规模变大时 LSDB/计算负担增加。如何在保持可达的前提下减少 LSA？

### 区域角色

- **传输区域（Transit）**：可承载穿越流量（如 Area0）。
- **末端区域（Stub）**：只承载本区域发起/访问本区域的流量。

### Stub / Totally Stub

```cli
ospf 1
area 0.0.0.2 stub
```

Stub：无 4/5 类，仍有描述区域间路由的 3 类。

```cli
area 0.0.0.2 stub no-summary
```

Totally Stub：阻挡 3/4/5 类，ABR 注入一条由 3 类描述的**缺省路由**；区域内靠缺省达外部及其他区域。

非 ABR 无需追加 `no-summary`（该参数作用于 ABR 是否向区域注入明细 3 类）。

### NSSA / Totally NSSA

Stub 不能引入外部路由。既需本地引入外部、又不希望学习其他区域外部路由时用 **NSSA**：

- **7 类 LSA（NSSA LSA）**：NSSA 内 ASBR 描述外部路由；仅在始发 NSSA 泛洪。
- NSSA 的 ABR 将 7 类转为 5 类注入骨干。
- NSSA 内无 4/5 类；ABR 自动注入用 7 类描述的缺省路由。

```cli
area 0.0.0.2 nssa
area 0.0.0.2 nssa no-summary   # Totally NSSA：再挡 3 类，仅保留缺省等
```

### LSA 类型回顾

| 类型 | 名称 | 说明 |
|------|------|------|
| 1 | Router LSA | 每台设备产生，描述链路状态与开销，区内泛洪 |
| 2 | Network LSA | DR 产生，描述 MA 邻接成员，区内泛洪 |
| 3 | Network Summary LSA | ABR 产生，区域间路由 |
| 4 | ASBR Summary LSA | ABR 产生，描述到 ASBR |
| 5 | AS External LSA | ASBR 产生，域外路由 |
| 7 | NSSA LSA | NSSA 内 ASBR 产生；ABR 转 5 类进 Area0 |

### LSA 处理原则

- 本地没有 → 更新 LSDB 并泛洪
- 本地有但收到更新 → 更新并泛洪
- 相同 → 忽略并终止泛洪
- 损坏（如 Checksum 错）→ 不接收

### 路由汇总

- **ABR 汇总**：区域间（`abr-summary`）
- **ASBR 汇总**：引入的外部路由（`asbr-summary`）

```cli
[R2]ospf
[R2-ospf-1]area 1
[R2-ospf-1-area-0.0.0.1]abr-summary 172.16.0.0 255.255.248.0
```

汇总后 ABR 只向 Area0 通告 `172.16.0.0/21`；明细翻动影响限制在 Area1。

```cli
ospf 1
asbr-summary 172.18.0.0 255.255.248.0
asbr-summary 172.19.0.0 255.255.248.0
asbr-summary 172.17.0.0 255.255.248.0
```

### Silent-Interface

```cli
[R1]ospf
[R1-ospf-1]area 0
[R1-ospf-1-area-0.0.0.0]network 192.168.4.0 0.0.0.255
[R1-ospf-1]silent-interface GigabitEthernet 0/0/1
```

接口仍在 network 范围内故路由可被通告，但不再收发 Hello，减少资源消耗（无其他 OSPF 邻居时适用）。

### OSPF 报文认证

支持区域认证与接口认证；两者都存在时**优先接口认证**。

- 区域：同区域认证模式与口令一致（`authentication-mode`）
- 接口：直连邻居接口认证一致（`ospf authentication-mode`）

```cli
[R2]ospf
[R2-ospf-1]area 0
# 区域认证
[R2]interface GigabitEthernet 0/0/1
# 接口认证；邻居需完成对应配置
```

### 思考题（特殊区域）

1. （多选）特殊区域？→ **A/B/C/D**（Stub、Totally Stub、NSSA、Totally NSSA）
2. Stub 与 Totally Stub 差别？→ Stub 允许 3 类、禁 4/5 类；Totally Stub 再禁 3 类，仅允许缺省 3 类。
3. 区域间汇总在哪配？→ **ABR**

---

## IS-IS 入门（衔接）

- IS-IS 与 OSPF 同为链路状态：Hello 发现邻居、建邻接、交互链路状态。
- CLNS 组成：CLNP（类比 IP）、IS-IS（类比 OSPF）、ES-IS（类比 ARP/ICMP）。
- ES：终端系统；IP 环境不涉及 CLNP/ES-IS，本课程不展开。
- OSPF：只支持 IP、IP 封装；IS-IS 属 ISO OSI 的 CLNS 一部分，集成 IS-IS 可支持 IP。

### 地址与拓扑差异（相对 OSPF）

- **Area ID**：由 IDP + High Order DSP 组成，标识路由域与区域；同区域节点区域地址相同；一进程最多 3 个区域地址（便于合并/分割）。
- **System ID**：区内唯一标识，实现中固定 6 Byte。
- 差异：
  - IS-IS：每台路由器只属一个区域；OSPF：不同接口可属不同区域。
  - IS-IS：无“单个 Area0 骨干”概念；OSPF：Area0 为骨干。
  - IS-IS：L1 与 L2 均用 SPF；OSPF：仅区内 SPF，区间经骨干。

层次：L1 在非骨干；L2 与 L1-2 在骨干；非骨干经 L1-2 连骨干。华为缺省全局 Level 为 **Level-1-2**。

NBMA 需配子接口，类型为 P2P。

（IS-IS 开销、TLV、配置与验证见下一文档。）
