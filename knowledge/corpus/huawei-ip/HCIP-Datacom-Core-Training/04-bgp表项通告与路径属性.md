---
doc_id: "hcip-datacom-core-training-04"
title: "BGP表项、通告原则与路径属性"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 4
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# BGP表项、通告原则与路径属性

## 状态机收尾：OpenSent → Established

TCP 完成后发 Open → **OpenSent**；收到对端合法 Open 并发 Keepalive → **OpenConfirm**；再收到对端 Keepalive → **Established**。

## BGP 对等体表

作用：列出本设备 BGP 对等体及其状态等信息。

```cli
<R1>display bgp peer
BGP local router ID : 10.0.1.1
 Local AS number : 100
 Total number of peers : 1
 Peers in established state : 1
 Peer         V   AS   MsgRcvd MsgSent OutQ Up/Down    State        PrefRcv
 10.0.12.2    4   100  25719   25714   0    0428h32m   Established  1
```

| 字段 | 含义 |
|------|------|
| Peer | 对等体地址 |
| V | 版本号 |
| AS | 对等体 AS |
| MsgRcvd / MsgSent | 收/发报文数 |
| OutQ | 发送队列积压（一般为 0） |
| Up/Down | 处于该状态时长 |
| State | 状态机状态 |
| PrefRcv | 从该对等体收到的前缀数 |

## BGP 路由表

列出本设备发现的所有 BGP 路由；同目的多条都列出，但每目的只优选一条。

```cli
<R1>display bgp routing-table
BGP Local router ID is 10.0.1.1
 Status codes: * - valid, > - best, d - damped, h - history, i - internal, s - suppressed, S - Stale
 Origin : i - IGP, e - EGP, ? - incomplete
 Network          NextHop
 *>i 10.0.45.0/24  10.0.4.4 ?
 * i               10.0.4.4 ?
```

详细信息：

```cli
<R1>display bgp routing-table 10.0.45.0 24
BGP local router ID : 10.0.1.1
 Local AS number : 100
 Paths: 2 available, 1 best, 1 select
 BGP routing table entry information of 10.0.45.0/24:
 From: 10.0.2.2 (10.0.2.2)
 Route Duration: 06h19m44s
 Relay IP Nexthop: 10.0.12.2
 Relay IP Out-Interface: GigabitEthernet0/0/0
 Original nexthop: 10.0.4.4
 AS-path Nil, origin incomplete, MED 0, localpref 100, pref-val 0,
 valid, internal, best, select, active, pre 255, IGP cost 2
 Originator: 10.0.4.4
 Cluster list: 10.0.2.2
 Not advertised to any peer yet
```

可看到来源、原始/迭代下一跳、路径属性、是否优选等。

## BGP 路由的生成

BGP 自身不发现拓扑计算路由，而是把已有路由注入 BGP 表再经 Update 传递。

注入方式：

1. **network**
2. **import-route**
3. 另支持 **aggregate** 手工聚合

### network

注入的路由必须已存在于 IP 路由表。

```cli
bgp 200
 network 10.1.0.0 24
 network 10.2.0.0 24
```

### import-route

```cli
bgp 200
 import-route ospf
 import-route static
```

### 聚合

本地表在明细之外增加聚合条目；`detail-suppressed` 时只向对等体通告聚合、不通告明细。

```cli
bgp 200
 aggregate 10.1.0.0 22 detail-suppressed
```

## BGP 通告原则

1. **只发布最优且有效（下一跳可达）的路由**（`*` 有效，`>` 最优）。
2. **从 EBGP 学到的路由，发布给所有对等体**（含 EBGP 与 IBGP）。
3. **IBGP 水平分割**：从 IBGP 学到的路由不再发给其他 IBGP（防环）；解决办法常为 AS 内 IBGP 全互联或路由反射器。
4. **BGP 同步规则**（经典）：从 IBGP 学到的路由，除非 IGP（含静态）也学到该前缀，否则不能使用或通告给 EBGP——用于规避非 BGP 路由器造成的黑洞。现代网络多通过全网 IBGP/反射器解决，较少再把 BGP 重分发进 IGP。

黑洞示例：R5→R3→迭代到 R1，但 R1 非 BGP 且无该前缀 → 丢弃。同步或全互联 IBGP 可避免。

## BGP 基本配置

```cli
[Huawei] bgp { as-number-plain | as-number-dot }
[Huawei-bgp] router-id ipv4-address
# 1. 启动 BGP，建议 Router ID 用 Loopback

[Huawei-bgp] peer { ipv4-address | ipv6-address } as-number { ... }
# 2. 配置对等体

[Huawei-bgp] peer ipv4-address connect-interface interface-type interface-number [ ipv4-source-address ]
[Huawei-bgp] peer ipv4-address ebgp-max-hop [ hop-count ]
# 3. 源接口；EBGP 最大跳数（缺省 1，仅直连）
```

未配 Router ID 时沿用系统视图 Router ID。

### 配置举例

- Loopback1：`10.0.x.x/32` 作 Router ID。
- R1–R3：Loopback 建 IBGP；R3–R4：互联地址建 EBGP。

```cli
[R1] bgp 100
[R1-bgp] router-id 10.0.1.1
[R1-bgp] peer 10.0.3.3 as-number 100
[R1-bgp] peer 10.0.3.3 connect-interface LoopBack1

[R3] bgp 100
[R3-bgp] router-id 10.0.3.3
[R3-bgp] peer 10.0.1.1 as-number 100
[R3-bgp] peer 10.0.1.1 connect-interface LoopBack1
[R3-bgp] peer 10.0.34.4 as-number 200

[R4] bgp 200
[R4-bgp] router-id 10.0.4.4
[R4-bgp] peer 10.0.34.3 as-number 100
```

验证：`display bgp peer` 可见 IBGP/EBGP 均 Established。

### 思考题（BGP 基础）

1. TCP 目的端口？→ **179**
2. 对等体种类？→ **IBGP / EBGP**，依据是否同 AS。
3. （多选）建邻、更新路由分别用？→ **B Open**、**D Update**

---

## BGP 路径属性

Update 携带 Path Attribute，影响选路。属性分类：公认必遵、公认任意、可选过渡、可选非过渡。

### AS_Path

- 途经 AS 列表；其它条件相同时，**AS_Path 更短更优**。
- 聚合可能丢失 AS_Path 致环路风险；聚合加 **as-set** 可用 AS_SET（`{...}` 无序集合）携带明细中的 AS。
- 另有 AS_Confed_Sequence / AS_Confed_Set（联邦，本课不展开）。

### Origin

| 值 | 符号 | 来源 |
|----|------|------|
| IGP | i | network 等方式 |
| EGP | e | 经 EGP 学习 |
| Incomplete | ? | 如 import-route |

优先级：IGP > EGP > Incomplete。

### Next_Hop

- 向 EBGP 发布：下一跳设为与对端建邻的本地接口地址。
- 本地始发路由向 IBGP 发布：下一跳设为建邻本地接口地址。
- 收到 EBGP 路由再传给 IBGP：**默认保持 Next_Hop 不变**。
- 若 Next_Hop 与更新对象同网段，可保持不变传递。
- IBGP 侧下一跳不可达会使路由无效；常用：

```cli
bgp 200
 peer 10.0.23.3 as-number 200
 peer 10.0.23.3 next-hop-local
```

将通告给该 IBGP 时的下一跳改为本端 TCP 源地址。

### Local_Preference

IBGP 内影响离开本 AS 的出口；值**越大越优**（缺省常见 100）。可用 route-policy 修改出口/入口策略。

### Community

自定义或公认团体，便于策略分组（如生产 `100:10`、办公 `100:20`）。

| 公认值 | 含义 |
|--------|------|
| Internet | 缺省；可向任何对等体发送 |
| No_Advertise | 不向任何 BGP 对等体发送 |
| No_Export | 不向 AS 外发送 |
| No_Export_Subconfed | 不向 AS 外及子 AS 发布（涉联邦） |

### MED

影响**进入**本 AS 的路径选择；通常**越小越优**；可选非过渡，一般不跨 AS 传递。缺省不携带时按 0 比较（场景相关）。

### Atomic_Aggregate / Aggregator

- Atomic_Aggregate：公认任意，标记聚合可能丢失属性，收到后需保留且不可再明细化。
- Aggregator：可选过渡，记录执行聚合的 AS 与 Router-ID。

```cli
bgp 300
 aggregate 10.0.0.0 16 detail-suppressed
```

### Preferred-Value（PrefVal）

华为私有扩展，仅本地有效；**越大越优**，选路顺序中很靠前。

---

## BGP 路由反射器（RR）

IBGP 水平分割要求全互联，规模大时用 RR：客户（Client）与非客户；RR 只反射自己使用的最优路由。

反射规则（摘要）：

- 从客户学到的 IBGP 路由 → 反射给所有非客户及**其他**客户。
- 反射时一般不改 Next_Hop、AS_Path、Local_Preference、MED（改则可能环路）。

防环属性：

- **Originator_ID**：原始发布者 Router ID。
- **Cluster_List**：反射时追加 Cluster_ID；若含自身 Cluster_ID 则丢弃（防环）。

```cli
[Huawei-bgp] peer { group-name | ipv4-address } reflect-client
[Huawei-bgp] reflector cluster-id cluster-id
# 缺省以自身 Router ID 为 Cluster ID
```

### RR 配置举例

AS100 内 OSPF；R2 为 RR，R3 为 Client；R3–R4 EBGP；R4 `network 10.4.4.0 24`。

```cli
[R1] bgp 100
[R1-bgp] router-id 10.0.1.1
[R1-bgp] peer 10.0.2.2 as-number 100
[R1-bgp] peer 10.0.2.2 connect-interface LoopBack0

[R2] bgp 100
[R2-bgp] router-id 10.0.2.2
[R2-bgp] peer 10.0.1.1 as-number 100
[R2-bgp] peer 10.0.1.1 connect-interface LoopBack0
[R2-bgp] peer 10.0.3.3 as-number 100
[R2-bgp] peer 10.0.3.3 connect-interface LoopBack0
[R2-bgp] peer 10.0.3.3 reflect-client

[R3] bgp 100
[R3-bgp] router-id 10.0.3.3
[R3-bgp] peer 10.0.2.2 as-number 100
[R3-bgp] peer 10.0.2.2 connect-interface LoopBack0
[R3-bgp] peer 10.0.34.4 as-number 200

[R4] bgp 200
[R4-bgp] router-id 10.0.4.4
[R4-bgp] peer 10.0.34.3 as-number 100
[R4-bgp] network 10.4.4.0 24
```

R3 从 EBGP 学到 `10.4.4.0/24` 后通告给 R2；R1 经 R2 反射学到，详细信息中可见 Originator、Cluster list，且 Original nexthop 可保持为 EBGP 下一跳（续验证见下一文档）。


## 通告原则场景补充

### IBGP 水平分割环路示意

若忽略水平分割：R2→R3→R1→R2 传递同一 IBGP 路由会形成环路。因此从 IBGP 学到的路由不得再发给其他 IBGP。

全互联补救：R2 与 R3 再建 IBGP，使 R2 可直接把路由交给 R3，而不依赖 R1 转发 IBGP 路由。

### 同步与黑洞步骤

1. R4 将 `10.0.4.0/24` 交给 R2（EBGP）。
2. R2 交给非直连 IBGP 对等体 R3。
3. 若无同步约束，R3 再交给 R5（EBGP）。
4. R5 访问 `10.0.4.4`：R3 按 BGP 下一跳迭代到 R1，但 R1 非 BGP、无该前缀 → 丢弃。

同步要求：仅当 IGP 也有该前缀时才使用/向 EBGP 通告 IBGP 路由。实践中更常用全网 IBGP/RR，而不是把 BGP 重分发进 IGP。

### network / import / aggregate 流程小结

1. IGP（如 OSPF）学到明细 → `network` 或 `import-route` 注入 BGP 表。
2. Update 传递给对等体。
3. `aggregate ... detail-suppressed` 后，对等体侧往往只见聚合前缀（如 `10.1.0.0/22`）。

## 路径属性补充示例

### AS_Path 与 AS_SET

聚合前明细可能分别经 AS100、AS200；在 R3 对 `10.0.0.0/16` 聚合并加 `as-set` 后，AS_PATH 可类似：

```text
AS_PATH = 300 {100, 200}
```

同时包含 AS_SEQUENCE 与 AS_SET，用于防环。

### Origin 显示

```cli
[R2] display bgp routing-table
 Origin : i - IGP, e - EGP, ? - incomplete
 Network          NextHop      MED LocPrf PrefVal Path/Ogn
 *>i 10.0.1.0/24  10.0.12.1    0   200    —      i
 * i              10.0.23.3    0   100    —      i
```

### Next_Hop 与 next-hop-local 对比

缺省：R2 把学自 R1 的路由传给 R3 时，Next_Hop 可能仍为 `10.0.12.1`；若 AS200 的 IGP 无该网段，R3 上该 BGP 路由无效。

```cli
bgp 200
 peer 10.0.23.3 as-number 200
 peer 10.0.23.3 next-hop-local
```

之后 Next_Hop 变为 R2 的更新源（如 `10.0.23.2`），便于 IGP 迭代。

### Local_Preference 选路示意

R1 向 R2 通告 LocPrf=200，R3 保持 100 时，R2 优选来自 R1 的路径。

### Community 公认值（RFC1997）

| 名称 | 典型取值 | 行为 |
|------|----------|------|
| Internet | — | 缺省可向任何对等体发送 |
| No_Export | 0xFFFFFF01 | 不向 AS 外发送 |
| No_Advertise | 0xFFFFFF02 | 不向任何 BGP 对等体发送 |
| No_Export_Subconfed | 0xFFFFFF03 | 不向 AS 外及子 AS 发布 |

### MED 选路示意

R2 通告 MED=10、R3 通告 MED=20（其他相同）时，R4 优选 R2。MED 为可选非过渡，通常不跨 AS 传递。

### Aggregator 显示

```cli
[R4]display bgp routing-table 10.0.0.0 16
 BGP routing table entry information of 10.0.0.0/16:
 AS-path 300, origin igp, ...
 Aggregator: AS 300, Aggregator ID 10.0.3.3, Atomic-aggregate
```

## RR 反射与防环补充

- 从客户学到的 IBGP 路由：反射给所有非客户及其他客户。
- 从非客户学到的 IBGP 路由：通常只反射给客户（教材图示区分“主动发送的更新”与“反射的更新”）。
- 反射一般不修改 Next_Hop、AS_Path、Local_Preference、MED。
- 多级 RR：Cluster_List 逐跳追加；收到含自身 Cluster_ID 的更新则丢弃。


