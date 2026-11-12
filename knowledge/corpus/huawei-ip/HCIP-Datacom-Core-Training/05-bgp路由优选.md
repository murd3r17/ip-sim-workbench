---
doc_id: "hcip-datacom-core-training-05"
title: "BGP路由优选"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 5
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# BGP路由优选

## 路由反射器验证收尾

R1 上查看经 RR 学到的路由时，可见下一跳未改、Originator 与 Cluster list：

```cli
Relay IP Nexthop: 10.0.12.2
Relay IP Out-Interface: GigabitEthernet0/0/0
Original nexthop: 10.0.34.4
AS-path 200, origin igp, MED 0, localpref 100, pref-val 0,
valid, internal, best, select, active, pre 255, IGP cost 3
Originator: 10.0.3.3
Cluster list: 10.0.2.2
Not advertised to any peer yet
```

### 思考题（路径属性 / RR）

1. （单选）AS_Path 属于？→ **C. 公认必遵**
2. MED 作用？能否跨 AS？→ 影响进入本 AS 的路径；可选非过渡，**一般不可跨 AS 传递**。
3. RR 防环用何属性？→ **Originator_ID、Cluster_List（Cluster_ID）**

---

## BGP 路由优选规则

到达同一目的多条路由时，按序比较；当前规则能决出最优则停止。下文为常用 12 步（先丢弃下一跳不可达）：

1. 优选 **Preferred-Value** 最大
2. 优选 **Local_Preference** 最大
3. **本地始发**优于从对等体学习；本地优先级：手动聚合 > 自动聚合 > network > import > 从对等体学到
4. 优选 **AS_Path** 最短
5. 优选 **Origin** 最优：IGP > EGP > Incomplete
6. 优选 **MED** 最小
7. 优选 **EBGP** 优于 IBGP
8. 优选到 Next_Hop 的 **IGP 度量**最小
9. 优选 **Cluster_List** 最短
10. 优选 **Router ID / Originator_ID** 最小
11. 优选对等体 **IP 地址**最小

前 8 条属性均相同时可形成负载分担（另需配置）。AIGP 本课优选规则不涉及。

> 拓扑基准（后续案例）：AS100 的 R4/R5 通告 `10.0.45.0/24`；AS200 的 R2/R3 与之 EBGP，R1 为 IBGP 核心。

### 下一跳可达（前提）

R2/R3 向 R1 通告时若保持外部 Next_Hop（`10.0.24.4` / `10.0.35.5`），而外部接口未进 OSPF，则 R1 迭代失败，路由无效（无 `*>`）。

```cli
bgp 200
 peer 10.0.1.1 next-hop-local
```

开启后 Next_Hop 变为 `10.0.2.2` / `10.0.3.3`，可迭代成功。后续案例默认已开 next-hop-local。

### 规则 1：Preferred-Value

```cli
bgp 200
 peer 10.0.3.3 preferred-value 100
```

R1 将优选 PrefVal=100 的 R3 路径（大于 R2 缺省 0）。

### 规则 2：Local_Preference

```cli
ip ip-prefix local_pref index 10 permit 10.0.45.0 24
route-policy local_pref permit node 10
 if-match ip-prefix local_pref
 apply local-preference 200
route-policy local_pref permit node 20
bgp 200
 peer 10.0.1.1 route-policy local_pref export
```

LocPrf 200 > 100 时，优选该路径。

### 规则 3：本地始发 vs 对等体 / 聚合优先级

手动聚合示例：

```cli
ip route-static 10.0.45.0 255.255.255.128 null0
ip route-static 10.0.45.128 255.255.255.128 null0
bgp 200
 import-route static
 aggregate 10.0.45.0 255.255.255.0 detail-suppressed
```

本地手动聚合优于对等体通告；表中 `s` 表示明细被抑制。

自动聚合：

```cli
bgp 200
 summary automatic
 import-route static
```

按自然网段聚合；本地自动聚合仍优于对等体通告的同前缀。

同时存在手动与自动聚合时，详细信息带 **Atomic-aggregate** 且为 Aggregated route 的为手动聚合，**手动 > 自动**。自动聚合不携带 Atomic-aggregate。network 优于 import（案例从略）。

### 规则 4：AS_Path 长度

```cli
ip ip-prefix as_path index 10 permit 10.0.45.0 24
route-policy as_path permit node 10
 if-match ip-prefix as_path
 apply as-path 400 additive
route-policy as_path permit node 20
bgp 200
 peer 10.0.1.1 route-policy as_path export
```

人为加长一侧 AS_Path 后，优选更短一侧。（AS_Path **长度**相同不比 AS 号大小——见文档 06 判断题。）

### 规则 5：Origin

import-route 注入 Origin 为 `?`；改为 **network** 后为 `i`，则优选 `i`。

### 规则 6：MED

```cli
ip ip-prefix med index 10 permit 10.0.45.0 24
route-policy med permit node 10
 if-match ip-prefix med
 apply cost 20
route-policy med permit node 20
bgp 200
 peer 10.0.1.1 route-policy med export
 compare-different-as-med
```

缺省只比较同源 AS 的 MED；`compare-different-as-med` 允许跨 AS 比较。不携带 MED 时按 0；MED 更小更优。

### 规则 7：EBGP 优于 IBGP

R3 同时收到 R1（IBGP，为对齐 AS_Path 可 additive `500`）与 R5（EBGP）通告的同前缀时，详细信息中 IBGP 路径可能标注 `not preferred for peer type`。

### 规则 8：到 Next_Hop 的 IGP Cost

详细信息中的 IGP cost 来自本地到 Original nexthop 的 IGP 度量。增大一侧接口 OSPF Cost 后，该侧可能 `not preferred for IGP cost`。

### 等价负载分担

- 使能后，满足条件的多条等代价路由可同时下载到 IP 路由表；BGP 表仍只标一条最优，且**只通告最优**给对等体。
- 公网中 IBGP 与 EBGP 不同时参与负载分担；缺省要求 AS_Path 完全相同，可用 `load-balancing as-path-ignore` 忽略。

```cli
bgp 200
 maximum load-balancing ibgp 2
```

```cli
[R1]display ip routing-table 10.0.45.0 24
# 可出现两条 IBGP 等价
[R1]display bgp routing-table
# 仍只有一条带 >
```

### 规则 9：Cluster_List

前序规则无法决出时，Cluster_List **更短**更优；较长一侧详细信息可标 `not preferred for Cluster List`。



## 优选案例回显补充

### 下一跳不可达时的表项形态

```text
Total Number of Routes: 2
 Network          NextHop     MED LocPrf PrefVal Path/Ogn
 i  10.0.45.0/24  10.0.24.4   0   100    0       100?
 i                10.0.35.5   0   100    0       300?
```

无 `*>`，两条均非有效最优。开启 `next-hop-local` 后可见：

```text
 *>i 10.0.45.0/24  10.0.2.2  ...
 * i               10.0.3.3  ...
```

### Preferred-Value 回显

```cli
[R1] display bgp routing-table
 Network           NextHop  MED LocPrf PrefVal Path/Ogn
 *>i 10.0.45.0/24  10.0.3.3 —   —      100     300 i
 * i               10.0.2.2 0   —      0       100 i
```

### Local_Preference 回显

```text
 *>i 10.0.45.0/24  10.0.3.3  0  200  0  300?
 * i               10.0.2.2  0  100  0  100?
```

### 本地手动聚合详细信息

```cli
[R3]display bgp routing-table 10.0.45.0 24
 Paths: 2 available, 1 best, 1 select
 BGP routing table entry information of 10.0.45.0/24:
 Aggregated route.
 Direct Out-interface: NULL0
 Original nexthop: 127.0.0.1
 AS-path Nil, origin incomplete, pref-val 0, valid, local, best, select, active, pre 255
 Aggregator: AS 200, Aggregator ID 10.0.3.3, Atomic-aggregate
 Advertised to such 2 peers: 10.0.35.5 10.0.1.1
```

自动聚合对比：同前缀多路径时，带 Atomic-aggregate 的聚合条目为手动聚合，优先于自动聚合。

### MED / peer type / IGP cost 提示语

- MED 更大一侧落选（在允许比较的前提下）。
- `not preferred for peer type`：因 EBGP 优于 IBGP 落选。
- `not preferred for IGP cost`：到下一跳 IGP 度量更大而落选。

### 规则 9 详例（Cluster_List）

多 RR 路径前序相同时，Cluster_List 更长一侧可出现：

```text
not preferred for Cluster List
Originator: 10.0.3.3
Cluster list: 10.0.1.1
```


（规则 10、11 见下一文档。）
