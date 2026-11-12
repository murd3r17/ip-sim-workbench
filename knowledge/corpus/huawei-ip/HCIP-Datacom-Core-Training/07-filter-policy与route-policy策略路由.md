---
doc_id: "hcip-datacom-core-training-07"
title: "Filter-Policy、Route-Policy与策略路由"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 7
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# Filter-Policy、Route-Policy与策略路由

## Filter-Policy 在 OSPF 中的作用

通过 `filter-policy export` 对引入的路由在发布时进行过滤，只将满足条件的外部路由转换为 Type5 LSA（AS-external-LSA）并发布出去。

> （原图：Filter-Policy / Route-Policy；filter-policy import / export；链路状态信息 LSA1～LSA4；R1 与 R2 路由表示意，网段如 172.16.x.0/24、10.1.x.0/24）

OSPF 的路由信息记录在 LSDB 中，`filter-policy import` 实际上是对 OSPF 计算出来的路由进行过滤，不是对发布和接收的 LSA 进行过滤。

- `filter-policy export` 可通过指定 `protocol` 或 `process-id` 对特定协议或某一进程的路由进行过滤。
- 如果没有指定 `protocol` 和 `process-id`，则 OSPF 将对所有引入的路由信息进行过滤。

## Filter-Policy 在 IS-IS 中的作用

当网络中同时部署了 IS-IS 和其他路由协议时，如果已经在边界设备上引入其他路由协议的路由，缺省情况下，该设备将把引入的全部外部路由发布给 IS-IS 邻居。如果只希望将引入的部分外部路由发布给邻居，可以使用 `filter-policy export` 实现。

> （原图：Filter-Policy / Route-Policy；R1、R2 路由表示意）

- IS-IS 的路由表项需要被成功下发到 IP 路由表中，才能用来指导 IP 报文转发。
- 如果 IS-IS 路由表中有到达某个目的网段的路由，但是并不希望将该路由下发到 IP 路由表中，可以使用 `filter-policy import` 命令结合基本 ACL、IP-Prefix、路由策略等方式，只将部分 IS-IS 路由下发到 IP 路由表中。

## BGP 中使用 Filter-Policy

```cli
bgp 100
ipv4-family unicast
 filter-policy 2000 import
```

使用 `filter-policy import` 可以对 BGP 设备全局接收的路由进行过滤，决定是否将路由添加到 BGP 路由表中。

```cli
bgp 100
ipv4-family unicast
 filter-policy 2000 export
```

使用 `filter-policy export` 可以将对外发布的路由进行过滤，只有通过过滤的路由才能加入 BGP 本地路由表，并被 BGP 发布。

> （原图：AS 100 内 R1、R2；BGP Update 中 NLRI Route-entry 经 filter-policy 过滤前后对比）

## Route-Policy 基本原理

一个路由策略中包含 N（N≥1）个节点（Node）。路由进入路由策略后，按节点序号从小到大依次检查各个节点是否匹配。匹配条件由 If-match 子句定义。

- 当路由与该节点的所有 If-match 子句都匹配成功后，进入匹配模式选择，不再匹配其他节点。匹配模式分 permit 和 deny 两种：
  - **permit**：路由将被允许通过，并且执行该节点的 apply 子句对路由信息的一些属性进行设置。
  - **deny**：路由将被拒绝通过。
- 当路由与该节点的任意一个 If-match 子句匹配失败后，进入下一节点。如果和所有节点都匹配失败，路由信息将被拒绝通过。

命令：`route-policy route-policy-name { permit | deny } node node`

- **permit**：指定 Route-Policy 节点的匹配模式为允许。如果路由与节点所有的 if-match 子句匹配成功，则执行此节点 apply 子句；否则，进行下一节点。
- **deny**：指定 Route-Policy 节点的匹配模式为拒绝。如果路由与节点所有的 if-match 子句匹配成功，则该路由将被拒绝通过；否则进行下一节点。
- **node node**：指定 Route-Policy 的节点号。当使用 Route-Policy 时，node 的值小的节点先进行匹配。一个节点匹配成功后，路由将不再匹配其他节点。全部节点匹配失败后，路由将被过滤。整数形式，取值范围是 0～65535。

```cli
[Huawei] route-policy route-policy-name { permit | deny } node node
```

### 创建 Route-Policy 与 if-match / apply

1. 创建路由策略并进入 Route-Policy 视图。

```cli
[Huawei-route-policy] if-match ?
```

可选匹配条件示例：

| 关键字 | 说明 |
| --- | --- |
| acl | 匹配基本 ACL |
| cost | 匹配路由信息的 cost |
| interface | 匹配路由信息的出接口 |
| ip-prefix | 匹配前缀列表 |

2.（可选）配置 if-match 子句。

apply 子句用来为路由策略指定动作，用来设置匹配成功的路由的属性。在一个节点中，如果没有配置 apply 子句，则该节点仅起过滤路由的作用。如果配置一个或多个 apply 子句，则通过节点匹配的路由将执行所有 apply 子句。

```cli
[Huawei-route-policy] apply ?
```

可选动作示例：

| 关键字 | 说明 |
| --- | --- |
| cost | 设置路由的 cost |
| cost-type { type-1 \| type-2 } | 设置 OSPF 的开销类型 |
| ip-address next-hop | 设置 IPv4 路由信息的下一跳地址 |
| preference | 设置路由协议的优先级 |
| tag | 设置路由信息的标记域 |

3.（可选）配置 apply 子句。

## 案例：Filter-Policy import（仅影响本机路由表）

通过 Filter-Policy 进行路由过滤，只影响本地的路由表，因此 R3 可以正常学习到 192.168.1.0/24 网段的路由。

> （原图：OSPF Area0，R1—R2—R3；网段 192.168.1.0/24～192.168.4.0/24）

- R1、R2、R3 运行 OSPF，R1 将 192.168.1.0/24、192.168.2.0/24、192.168.3.0/24 和 192.168.4.0/24 宣告进 OSPF。
- 要求 R2 不能访问 R1 上 192.168.1.0/24 网段，但是 R3 可以正常访问。
- 为实现该需求，可以在 R2 上对接收的路由使用 Filter-Policy 进行过滤。

R2 的配置如下（网络基础配置略）：

```cli
[R2] ip ip-prefix in index 10 permit 192.168.2.0 24
[R2] ip ip-prefix in index 20 permit 192.168.3.0 24
[R2] ip ip-prefix in index 30 permit 192.168.4.0 24
[R2] ospf
[R2-ospf-1] filter-policy ip-prefix in import
```

## 案例：Filter-Policy export（过滤引入后发布）

- R1、R2、R3 运行 OSPF，R1 将直连网段 192.168.1.0/24、192.168.2.0/24、192.168.3.0/24 和 192.168.4.0/24 引入 OSPF。
- 要求 R2、R3 只能学习到 192.168.1.0/24 网段的路由，学习不到其他三个网段的路由。
- 为实现该需求，可以在 R1 上使用 Filter-Policy 对引入的路由在发布时进行过滤。

R1 的配置如下（网络基础配置略）：

```cli
[R1] ip ip-prefix out index 10 permit 192.168.1.0 24
[R1] ospf
[R1-ospf-1] import-route direct
[R1-ospf-1] filter-policy ip-prefix out export
```

## 案例：Route-Policy 修改外部路由类型

- R1、R2、R3 运行 OSPF，R1 将直连网段 192.168.1.0/24 引入 OSPF。
- 要求 R2、R3 学到的 OSPF 路由 192.168.1.0/24 为 external-type 1 路由（默认为 external-type 2 路由）。
- 为实现该需求，可以在 R1 上使用 Route-Policy 在引入路由时修改外部路由的类型为 external-type 1。

R1 的配置如下（网络基础配置略）：

```cli
[R1] ip ip-prefix external index 10 permit 192.168.1.0 24
[R1] route-policy RP permit node 10
[R1-route-policy] if-match ip-prefix external
[R1-route-policy] apply cost-type type-1
[R1-route-policy] quit
[R1] ospf
[R1-ospf-1] import-route direct route-policy RP
```

## 双点双向路由重发布与次优路径、环路

在边界路由器上把两个路由域的路由相互引入，称之为双向路由重发布。两个路由域存在两个边界路由器，并且都执行双向路由重分发，此时称为双点双向路由重发布。

双点双向路由重发布是一种经典的路由模型：因单点的双向路由重发布缺乏冗余性，一旦单点的边界路由器故障，两个路由域之间的通信可能就会出现问题，因此在大型网络部署中一般采用双点双向路由重发布。双点双向重发布虽然增强了网络的可靠性，但是容易引发次优路径、路由环路等问题。

> （原图：OSPF 域 R1—R2—R3，IS-IS 域 R2—R3—R4；网段 10.4.4.0/24 等）

以 10.1.1.0/24 为例：

- R1 将直连路由 10.1.1.0/24 引入到 OSPF 中。
- R2、R3 执行双向路由重发布，R2 先将 10.1.1.0/24 重发布到 IS-IS 中，R3 将会学习到来自 R4 的 IS-IS 路由。
- 对 R3 而言，IS-IS 路由（优先级 15）优于 OSPF 外部路由（优先级 150），因此优选来自 R4 的 IS-IS 路由。后续 R3 访问 10.1.1.0/24 网段的路径为：R3→R4→R2→R1，这是次优路径。

| Destination/Mask | Proto | Pre |
| --- | --- | --- |
| 10.1.1.0/24 | ISIS | 15 |

### 解决次优路径：filter-policy import

```cli
[R3] acl 2001
[R3-acl-basic-2001] rule 5 deny source 10.1.1.0 0
[R3-acl-basic-2001] rule 10 permit
[R3] isis
[R3-isis-1] filter-policy 2001 import
```

### 解决次优路径：修改 OSPF 外部路由优先级

```cli
[R3] acl 2000
[R3-acl-basic-2000] rule permit source 10.1.1.0 0
[R3-acl-basic-2000] quit
[R3] route-policy hcip permit node 10
[R3-route-policy] if-match acl 2000
[R3-route-policy] apply preference 14
[R3-route-policy] quit
[R3] ospf 1
[R3-ospf-1] preference ase route-policy hcip
```

修改后路由表示意：

| Destination/Mask | Proto | Pre |
| --- | --- | --- |
| 10.1.1.0/24 | OSPF | 14 |

### 路由环路场景

场景描述：

1. R1 将直连路由 10.1.1.0/24 引入到 OSPF 中。
2. R1、R2、R3 运行 OSPF 协议，10.1.1.0/24 网段路由在全 OSPF 域内通告。
3. R2 执行了双向路由重发布。
4. R2、R3、R4 运行 IS-IS 协议，10.1.1.0/24 网段路由在全 IS-IS 域内通告。
5. R3 执行了双向路由重发布。
6. 10.1.1.0/24 网段路由再次被通告进 OSPF 域内，形成路由环路。

### 防环：引入时用 Route-Policy 过滤

```cli
[R3] acl 2001
[R3-acl-basic-2001] rule 5 deny source 10.1.1.0 0
[R3-acl-basic-2001] rule 10 permit
[R3] route-policy RP permit node 10
[R3-route-policy] if-match acl 2001
[R3-route-policy] quit
[R3] ospf
[R3-ospf-1] import-route isis 1 route-policy RP
```

### 防环：使用 Tag 标记与过滤

在路由重发布的实际应用中，通过 IP 前缀进行路由匹配固然可行，但当网络规模较大时，配置工作量较大；通过 Tag 进行路由匹配可以极大简化配置工作量。

在 R2 上为从 OSPF 引入到 IS-IS 的 10.1.1.0/24 打上 tag 200：

```cli
[R2] acl 2000
[R2-acl-basic-2000] rule permit source 10.1.1.0 0
[R2-acl-basic-2000] quit
[R2] route-policy hcip permit node 10
[R2-route-policy] if-match acl 2000
[R2-route-policy] apply tag 200
[R2-route-policy] quit
[R2] isis 1
[R2-isis-1] import-route ospf route-policy hcip
```

在 R3 上过滤携带 tag 200 的路由，避免再引入回 OSPF：

```cli
[R3] route-policy hcip deny node 10
[R3-route-policy] if-match tag 200
[R3-route-policy] quit
[R3] route-policy hcip permit node 20
[R3] ospf 1
[R3-ospf-1] import-route isis route-policy hcip
```

思考：在 R1 上将 10.1.1.0/24 引入到 OSPF，在 R4 上将 10.4.4.0/24 引入到 IS-IS，R2、R3 上执行双向路由重发布，该场景下如何使用匹配 Tag 的方式防止路由环路？

### 思考题（路由过滤）

1. （简答题）Filter-Policy export 在 OSPF、BGP 中的作用分别是？
2. （简答题）Route-Policy 多个节点之间的逻辑关系为？一个节点内多个条件语句的逻辑关系为？

参考要点：

1. 在 OSPF 中的作用为过滤从其他路由协议引入到 OSPF 中的路由条目；在 BGP 中的作用为限制本地对外发布的路由条目。
2. 节点之间的逻辑关系为或，条件语句间的逻辑关系为与。

## 策略路由（PBR）

可通过策略路由（以及接口、模块化 QoS 命令行）的方式控制报文的转发路径和进行流量过滤。

PBR 的节点匹配模式：

- **permit**：对满足匹配条件的报文进行策略路由
- **deny**：对满足匹配条件的报文不进行策略路由

当 ACL 的 rule 配置为 permit 时，设备会对匹配该规则的报文执行本地策略路由的动作：

- 本地策略路由中策略点为 permit 时对满足匹配条件的报文进行策略路由；
- 本地策略路由中策略点为 deny 时对满足匹配条件的报文不进行策略路由，即根据目的地址查找路由表转发报文。
- 当 ACL 配置了 rule，如果报文未匹配上任何规则，则根据目的地址查找路由表转发报文。
- 当 ACL 的 rule 配置为 deny 或 ACL 未配置规则时，应用该 ACL 的本地策略路由不生效，即根据目的地址查找路由表转发报文。

### PBR 配置步骤

1. 创建策略路由和策略点，若策略点已创建则进入本地策略路由视图。

```cli
[Huawei] policy-based-route policy-name { deny | permit } node node-id
```

2. 设置 IP 报文的匹配条件。缺省情况下，策略路由中未配置匹配条件，可以设置使用 ACL 匹配 IP 地址，也可以设置匹配报文长度。

```cli
[Huawei-policy-based-route-PBR-10] if-match acl acl-number
[Huawei-policy-based-route-PBR-10] if-match packet-length min-length max-length
```

3. 指定 PBR 中报文的出接口。缺省情况下，策略路由中未配置报文出接口。配置成功后，将匹配策略点的报文从指定出接口发送出去。报文的出接口不能为以太接口等广播型接口。

```cli
[Huawei-policy-based-route-PBR-10] apply output-interface interface-type interface-number
```

4. 设置 PBR 中报文的下一跳。用户可以指定报文的下一跳。当该策略点未配置出接口时，匹配策略点的报文被发往指定的下一跳。

```cli
[Huawei-policy-based-route-PBR-10] apply ip-address next-hop ip-address1 [ ip-address2 ]
```

除出接口/下一跳方式之外，接口策略路由还可以使用 MQC 的方式进行配置。

5. 全局 PBR 调用：

```cli
[Huawei] ip local policy-based-route Policy-name
```

6. 接口 PBR 调用：

```cli
[Huawei-GigabitEthernet0/0/0] ip policy-based-route Policy-name
```

### PBR 配置案例

1. 配置 ACL 3000：rule 1 deny 网段 1 访问服务器的流量，rule 2 匹配网段 1 访问 Internet 的流量。

```cli
[RTA] acl number 3000
[RTA-acl-adv-3000] rule 1 deny ip source 10.1.1.0 0.0.0.255 destination 10.1.3.254 0
[RTA-acl-adv-3000] rule 2 permit ip source 10.1.1.0 0.0.0.255 destination 0.0.0.0 0
```

2. 配置 ACL 3001：rule 1 deny 网段 2 访问服务器的流量，rule 2 匹配网段 2 访问 Internet 的流量。

```cli
[RTA] acl number 3001
[RTA-acl-adv-3001] rule 1 deny ip source 10.1.2.0 0.0.0.255 destination 10.1.3.254 0
[RTA-acl-adv-3001] rule 2 permit ip source 10.1.2.0 0.0.0.255 destination 0.0.0.0 0
```

3. 创建 PBR hcip，创建节点 10，调用 ACL 3000，指定其转发下一跳为 202.1.2.3。

```cli
[RTA] policy-based-route hcip permit node 10
[RTA-policy-based-route-hcip-10] if-match acl 3000
[RTA-policy-based-route-hcip-10] apply ip-address next-hop 202.1.2.3
```

4. 创建 PBR hcip 节点 20，调用 ACL 3001，指向其转发下一跳为 154.1.2.3。

```cli
[RTA] policy-based-route hcip permit node 20
[RTA-policy-based-route-hcip-20] if-match acl 3001
[RTA-policy-based-route-hcip-20] apply ip-address next-hop 154.1.2.3
```

5. 在 GE0/0/0 接口调用 PBR hcip。

```cli
[RTA] interface GigabitEthernet 0/0/0
[RTA-GigabitEthernet0/0/0] ip policy-based-route hcip
```

## MQC（模块化 QoS）

流分类中各规则之间的关系分为：and 或 or，缺省情况下的关系为 or。

- **and**：当流分类中包含 ACL 规则时，报文必须匹配其中一条 ACL 规则以及所有非 ACL 规则；当流分类中没有 ACL 规则时，报文必须匹配所有非 ACL 规则。
- **or**：报文只要匹配了流分类中的一个规则，设备就认为报文匹配中该流分类。

匹配字段示意：

- ACL 4000～4999：可匹配 VLAN 报文 Tag 的 ID 信息等
- ACL 2000～3999：可匹配 IPv4 报文长度、IP 优先级、出接口、入接口、所有报文等

1. 创建流分类。缺省情况下，流分类中各规则之间的关系为“或”（or）。流分类中的匹配规则配置可查阅产品手册。

```cli
[Huawei] traffic classifier classifier-name [ operator { and | or } ]
```

2. 创建流行为。根据实际情况定义流行为中的动作，只要各动作不冲突，都可以在同一流行为中配置。流行为具体配置可查阅产品手册。

```cli
[Huawei] traffic behavior behavior-name
```

3. 创建流策略，并绑定流分类与流行为。

```cli
[Huawei] traffic policy policy-name
[Huawei-trafficpolicy-policyname] classifier classifier-name behavior behavior-name
```

### MQC 重定向案例

> （原图：RTA 连接 ISP1/ISP2；网段 10.1.1.0/24、10.1.2.0/24；下一跳 202.1.2.3、154.1.2.3；入接口 GE0/0/0）

RTA 的配置如下：

1. 配置 ACL3000、3001 分别匹配网段 1、网段 2 访问 Internet 的流量。

```cli
[RTA] acl number 3000
[RTA-acl-adv-3000] rule 2 permit ip source 10.1.1.0 0.0.0.255 destination 0.0.0.0 0
[RTA] acl number 3001
[RTA-acl-adv-3001] rule 2 permit ip source 10.1.2.0 0.0.0.255 destination 0.0.0.0 0
```

2. 创建流分类 1、2 分别匹配 ACL3000、ACL3001。

```cli
[RTA] traffic classifier 1
[RTA-classifier-1] if-match acl 3000
[RTA] traffic classifier 2
[RTA-classifier-2] if-match acl 3001
```

3. 创建流行为 1、2 分别执行将报文重定向到 202.1.2.3、154.1.2.3 的动作。

```cli
[RTA] traffic behavior 1
[RTA-behavior-1] redirect ip-nexthop 202.1.2.3
[RTA] traffic behavior 2
[RTA-behavior-2] redirect ip-nexthop 154.1.2.3
```

4. 创建流策略 Redirect，将流分类 1、2 与流行为 1、2 一一绑定。

```cli
[RTA] traffic policy Redirect
[RTA-trafficpolicy-Redirect] classifier 1 behavior 1
[RTA-trafficpolicy-Redirect] classifier 2 behavior 2
```

5. 在 GE0/0/0 接口入方向调用流策略 Redirect。

```cli
[RTA] interface GigabitEthernet 0/0/0
[RTA-GigabitEthernet0/0/0] traffic-policy Redirect inbound
```

## Traffic-Filter 与 MQC 对比

Traffic-Filter 只能应用在接口视图下，而 MQC 可以调用在多种视图。Traffic-Filter 部署的位置不同，其调用的 ACL 内容也不相同。

### Traffic-Filter 案例

> （原图：部门 1/2/3 网关均在 RTA；10.1.1.0/24、10.1.2.0/24、10.1.3.0/24；GE0/0/0～GE0/0/2）

RTA 的配置如下：

1. 配置 ACL 拒绝部门 2 访问部门 3，并放通其余所有流量。

```cli
[RTA] acl number 3000
[RTA-acl-adv-3000] rule 1 deny ip source 10.1.2.0 0.0.0.255 destination 10.1.3.0 0.0.0.255
[RTA-acl-adv-3000] rule 2 permit ip
```

2. 在 GE0/0/2 接口调用 Traffic-Filter。

```cli
[RTA] interface GigabitEthernet 0/0/2
[RTA-GigabitEthernet0/0/2] traffic-filter outbound acl 3000
```

思考：ACL 的写法、Traffic-Filter 调用的接口是否还有别的可能？

### MQC 过滤案例

部门 1、2、3 的网关都在 RTA 上，现要求在 RTA 上使用 MQC 限制部门 2 与部门 3 之间的相互访问。

1. 配置 ACL 匹配部门 2 访问部门 3 的流量。

```cli
[RTA] acl number 3000
[RTA-acl-adv-3000] rule 1 permit ip source 10.1.2.0 0.0.0.255 destination 10.1.3.0 0.0.0.255
```

2. 创建流分类 2_3、流行为 2_3。

```cli
[RTA] traffic classifier 2_3
[RTA-classifier-2_3] if-match acl 3000
[RTA] traffic behavior 2_3
[RTA-behavior-2_3] deny
```

为匹配 ACL 规则的报文指定报文过滤动作时：如果此 ACL 中的 rule 规则配置为 permit，则设备对此报文采取的动作由流行为中配置的 deny 或 permit 决定；如果此 ACL 中的 rule 规则配置为 deny，则无论流行为中配置了 deny 或 permit，此报文都被丢弃。

3. 创建流策略，绑定流分类 2_3 与流行为 2_3。

```cli
[RTA] traffic policy 2_3
[RTA-trafficpolicy-2_3] classifier 2_3 behavior 2_3
```

4. 在接口 GE0/0/1 入向调用流策略 2_3。

```cli
[RTA] interface GigabitEthernet 0/0/1
[RTA-GigabitEthernet0/0/1] traffic-policy 2_3 inbound
```

要点：

- 本地策略路由对本地始发的流量生效，而接口策略路由只会对接口入方向的流量生效。
- MQC 调用的 ACL 里 permit、deny 只代表是否匹配流量，不代表是否放通、拒绝流量；而 Traffic-Filter 调用的 ACL 里 permit、deny 代表放通、拒绝流量。

### 思考题（PBR / MQC）

1. （简答题）本地策略路由与接口策略路由的区别在于？
2. （简答题）使用 MQC 方式过滤流量时，流分类中匹配的 ACL 与 Traffic-Filter 调用的 ACL 有何区别？

## 园区网典型技术应用概述（节选）

工厂、政府机关、商场、写字楼、校园、公园等场所内为了实现数据互通而搭建的网络都可以称之为园区网。园区网络一般划分为出口层、核心层、汇聚层及接入层。

学完本课程后，应能够：

- 描述大型园区网络的典型架构
- 描述常用以太网交换技术
- 描述 WLAN 常见应用场景
- 描述园区网络可靠性的常用技术
- 描述园区网络网络服务与管理的常用技术
- 描述园区网络安全的常用技术
- 描述园区网络常用的 VPN 技术

课程结构概览：园区网络架构与常见技术概述；以太网交换基础；无线接入；网络可靠性；网络服务与网络管理；网络安全；VPN；组播；IPv6。

### 什么是园区网络

- 园区网络一般是指企业或者机构的内部网络。
- 主要目的是使企业或者机构的各项业务运作更有效率。
- 按规模划分：
  - 大型：终端用户数量 > 2000；网元数量 > 100
  - 中型：200 ≤ 终端用户数量 ≤ 2000；25 ≤ 网元数量 ≤ 100
  - 小型：终端用户数量 < 200；网元数量 < 25
- 有些企业还存在不同地域的办公分支机构，每个分支机构网络可看做一个单园区网络。

### 园区网络典型架构

| 层次/区域 | 说明 |
| --- | --- |
| 核心层 | 园区网骨干，联接数据中心、管理中心、园区出口等 |
| 汇聚层 | 中间层次，完成数据汇聚或交换，可提供路由、安全等功能 |
| 接入层 | 为终端用户提供园区网接入，是园区网的边界 |
| 出口区 | 内部网络到外部网络的边界 |
| 数据中心区 | 部署服务器和应用系统 |
| 网管运维区 | 网络管理与运维 |

常见技术名词：

- **NAT**：Network Address Translation，网络地址转换
- **LLDP**：Link Layer Discovery Protocol，链路层发现协议（IEEE 802.1ab）
- **NETCONF**：Network Configuration Protocol，网络配置协议
- **YANG**：Yet Another Next Generation，NETCONF 数据建模语言
- **SNMP**：Simple Network Management Protocol，简单网络管理协议
- **VRRP**：Virtual Router Redundancy Protocol，虚拟路由冗余协议
- **MSTP**：Multiple Spanning Tree Protocol，多生成树协议

### 以太网二层交换基础

将网络的通信过程划分为小一些、简单一些的部件，有助于各个部件的开发、设计和故障排除；通过网络组件的标准化，允许多个供应商进行开发；通过定义在模型的每一层实现什么功能，鼓励产业的标准化；允许各种类型的网络硬件和软件相互通信。

TCP/IP 封装示意：应用层 Payload → 传输层段（Segment）→ 网络层报文（Packet）→ 数据链路层帧（Frame）→ 物理层比特（Bit）。

- 接入层通常由接入交换机组成，数量众多、安装位置分散，通常是简单的二层交换机。
- 如果终端层存在无线终端设备，接入层需要无线接入点 AP，AP 通过接入交换机接入网络。

二层交换设备工作在数据链路层，对数据包的转发建立在 MAC 地址基础之上：通过解析和学习以太网帧的源 MAC 维护 MAC 与接口对应关系，通过目的 MAC 查找 MAC 表决定向哪个接口转发。不同接口属于不同冲突域。

### VLAN

VLAN（Virtual Local Area Network）即虚拟局域网，是将一个物理的 LAN 在逻辑上划分成多个广播域的通信技术。

- 一个 VLAN 中所有设备都是在同一广播域内，不同的 VLAN 为不同的广播域。
- VLAN 内的设备间可以直接通信，而 VLAN 间不能直接互通。
- VLAN 之间互相隔离，不同 VLAN 间需通过三层设备实现相互通信。
- 一个 VLAN 一般为一个逻辑子网。
- VLAN 中成员多基于交换机的端口分配。

### 以太网二层接口类型

| 类型 | 说明 |
| --- | --- |
| Access | 常用来连接用户 PC、服务器等终端；通常收发无标记帧；只能加入一个 VLAN |
| Trunk | 允许多个 VLAN 的数据帧通过，通过 802.1Q Tag 区分；常用于交换机互联或连接路由器/防火墙子接口 |
| Hybrid | 与 Trunk 类似，允许多个 VLAN 通过；可灵活指定发送某个（或某些）VLAN 的数据帧时是否携带 Tag |

所有二层接口都有缺省 VLAN ID，称为 PVID（Port Default VLAN ID）。在华为交换机上，PVID 缺省为 1。出于提高数据帧处理效率的考虑，在交换机内部，数据帧一律携带 Tag。

#### Trunk 收发行为要点

- 接口收到不带 Tag 的帧：打上 PVID；当 PVID 在该接口允许通过的 VLAN 列表里时接收，否则丢弃。
- 接口收到带 Tag 的帧：当该帧的 VLAN ID 在允许列表里时接收，否则丢弃。
- 发送时：帧的 VLAN ID 与接口 PVID 相同则剥除 Tag 后发送；不同则保留 Tag 发送（前提是 VLAN ID 在允许列表中）。

Hybrid 与 Trunk 在接收行为上大体相同；发送时 Hybrid 可通过命令指定某个/某些 VLAN 发送时不携带 Tag。

### VLAN 划分方式

| 划分方式 | 原理 |
| --- | --- |
| 基于接口 | 根据交换机的接口来划分 VLAN |
| 基于 MAC 地址 | 根据数据帧的源 MAC 地址来划分 VLAN |
| 基于子网 | 根据数据帧中的源 IP 地址来划分 VLAN |
| 基于协议 | 根据数据帧所属的协议（族）类型及封装格式来划分 VLAN |
| 基于策略 | 根据配置的策略划分，可组合接口、MAC、IP 等 |

实现 VLAN 之间的 IP 可达性可通过：路由器物理接口、路由器子接口、三层交换机（VLANIF）等方式。

### 链路聚合

随着网络规模不断扩大，用户对骨干链路的带宽和可靠性提出越来越高的要求。采用链路聚合技术可以在不进行硬件升级的条件下，通过将多个物理接口捆绑为一个逻辑接口，达到增加链路带宽的目的，并采用备份链路机制提高可靠性。

LAG 是指将若干条以太链路捆绑在一起所形成的逻辑链路，简写为 Eth-Trunk。每个聚合组唯一对应着一个逻辑接口（聚合接口或 Eth-Trunk 接口）。

优势：

- **增加带宽**：链路聚合接口的最大带宽可以达到各成员接口带宽之和
- **提高可靠性**：当某条活动链路出现故障时，流量可以切换到其他可用的成员链路上
- **负载分担**：在一个链路聚合组内，可以实现在各成员活动链路上的负载分担

### 生成树技术

生成树工作在二层网络，用于解决交换网络中的环路问题，动态适应网络拓扑变更，配合冗余链路保证二层网络可靠性。

### WLAN 与主要网元

WLAN（Wireless Local Area Network，无线局域网）广义上是指以无线电波、激光、红外线等来代替有线局域网中的部分或全部传输介质所构成的网络。本文介绍的 WLAN 技术基于 802.11 标准系列。

- **无线接入点（AP，Access Point）**
  - 一般支持 FAT AP（胖 AP）、FIT AP（瘦 AP）和云管理 AP 三种工作模式，可根据网络规划灵活切换。
  - **FAT AP**：适用于家庭，独立工作，需单独配置，功能较为单一，成本低；独立完成用户接入、认证、数据安全、业务转发和 QoS 等功能。
  - **FIT AP**：适用于大中型企业，需要配合 AC 使用，由 AC 统一管理和配置，功能丰富；用户接入、AP 上线、认证、路由、AP 管理、安全协议、QoS 等功能需要同 AC 配合完成。
  - **云管理**：适用于中小型企业，配合云管理平台使用，即插即用，对维护人员技能要求较低。
- **无线接入控制器（AC，Access Controller）**
  - 一般位于整个网络的汇聚层，提供高速、安全、可靠的 WLAN 业务。
  - 提供大容量、高性能、高可靠性、易安装、易维护的无线数据控制业务。

AC 和 AP 之间使用 CAPWAP（Control And Provisioning of Wireless Access Points）。CAPWAP 定义：AP 自动发现 AC，AC 对 AP 进行安全认证，AP 从 AC 获取软件，AP 从 AC 获得初始和动态配置等。通过该协议，AP 和 AC 之间建立起 CAPWAP 隧道（控制隧道与数据隧道）。CAPWAP 隧道可以进行 DTLS（Datagram Transport Layer Security）加密。

相比于 FAT AP 架构，AC+FIT AP 架构的优点包括：配置与部署集中、安全性增强、更新与扩展更便捷等。
