---
doc_id: "hcip-datacom-core-lab-03"
title: "1.3 OSPF 的邻接关系和LSA"
book: "HCIP-Datacom-Core-Lab"
book_title: "HCIP-Datacom-Core Technology V1.0 实验手册"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "lab"
source_pdf: "HCIP-Datacom-Core Technology V1.0 实验手册.pdf"
seq: 3
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 1.3 OSPF 的邻接关系和LSA

## 1.3.1 实验介绍

1.3.1.1 学习目标

- 阐明在多路访问网络中接入多台路由器时的邻居关系建立过程
- 控制OSPF DR 的选举
- 描述5 种类型的LSA 的内容，以及它们的作用

1.3.1.2 实验组网介绍

图1-3 OSPF 的邻接关系和LSA 设备互联方式及IP 地址规划如图所示，其中R1 的Loopback0 接口属于OSPF 区域2，R4 的 GE0/0/2 接口属于OSPF 区域1，R1、R2、R3、R4 的其他接口都属于OSPF 区域0。 R5 的GE0/0/3 属于OSPF 区域1，R5 的Loopback0 不属于OSPF 域内。

1.3.1.3 实验背景

你是公司的网络管理员。现在公司的网络中有五台AR 路由器，其中R1、R2、R3 和R4 在公 司总部，通过以太网互联。R5 在公司分部，与公司总部的R4 相连。由于网络规模较大，为 了控制LSA 的洪泛，你设计了多区域的OSPF。 同时为了明确设备的Router ID，你配置设备使用固定的地址作为Router ID。 在R1、R2、R3 与R4 之间互联的网络上，需要干预DR 与BDR 的选举。实际使用中将R3 定 义为DR、R2 定义为BDR，R1、R4 定义为DROther。

## 1.3.2 实验任务

1.3.2.1 任务思路

1. 设备IP 地址配置。
2. 按照规划配置OSPF 多区域。
3. 检查OSPF 配置结果，检查OSPF 邻居关系状态，检查OSPF 路由表，检查OSPF LSDB。
4. 手动修改接口的DR 优先级，人工干预OSPF DR、BDR 的选举结果。
5. 在R5 上将直连路由引入到OSPF 中，在R1 上观察Type-5 LSA。
6. 单独观察Type-1 LSA、Type-2 LSA、Type-3 LSA、Type-4 LSA
7. R1 上通过debug 观察OSPF LSU、LSAck、LSR 报文。

1.3.2.2 任务步骤

步骤 1 互联接口、环回口IP 地址配置

```cli
#设备命名
```

略

```cli
#关闭本实验中未使用的接口
```

略

```cli
#配置R1 的GE0/0/1、Loopback0 接口IP 地址

[R1]interface GigabitEthernet0/0/1

[R1-GigabitEthernet0/0/1] ip address 10.0.123.1 24

[R1-GigabitEthernet0/0/1] quit

[R1]interface LoopBack 0

[R1-LoopBack0] ip address 10.0.1.1 24

[R1-LoopBack0] quit

#配置R2 的GE0/0/1、Loopback0 接口IP 地址

[R2]interface GigabitEthernet0/0/1

[R2-GigabitEthernet0/0/1] ip address 10.0.123.2 24

[R2-GigabitEthernet0/0/1] quit

[R2]interface LoopBack 0

[R2-LoopBack0] ip address 10.0.2.2 24

[R2-LoopBack0] quit

#配置R3 的GE0/0/1、Loopback0 接口IP 地址

[R3]interface GigabitEthernet0/0/1

[R3-GigabitEthernet0/0/1] ip address 10.0.123.3 24

[R3-GigabitEthernet0/0/1] quit

[R3]interface LoopBack 0

[R3-LoopBack0] ip address 10.0.3.3 24

[R3-LoopBack0] quit

#配置R4 的GE0/0/1、GE0/0/2、Loopback0 接口IP 地址

[R4]interface GigabitEthernet0/0/1

[R4-GigabitEthernet0/0/1] ip address 10.0.123.4 24

[R4-GigabitEthernet0/0/1] quit

[R4] interface GigabitEthernet0/0/2

[R4-GigabitEthernet0/0/2] ip address 10.0.45.4 24

[R4-GigabitEthernet0/0/2] quit

[R4]interface LoopBack 0

[R4-LoopBack0] ip address 10.0.4.4 24

[R4-LoopBack0] quit

#配置R5 的GE0/0/3、Loopback0 接口IP 地址

[R5]interface GigabitEthernet0/0/3

[R5-GigabitEthernet0/0/3] ip address 10.0.45.5 24

[R5-GigabitEthernet0/0/3] quit

[R5]interface LoopBack 0

[R5-LoopBack0] ip address 10.0.5.5 24

[R5-LoopBack0] quit

#在R4 上检测互联地址连通性

<R4>ping -c 1 10.0.123.1 PING 10.0.123.1: 56  data bytes, press CTRL_C to break Reply from 10.0.123.1: bytes=56 Sequence=1 ttl=255 time=100 ms

--- 10.0.123.1 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 100/100/100 ms

<R4>ping -c 1 10.0.123.2 PING 10.0.123.2: 56  data bytes, press CTRL_C to break Reply from 10.0.123.2: bytes=56 Sequence=1 ttl=255 time=110 ms

--- 10.0.123.2 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 110/110/110 ms

<R4>ping -c 1 10.0.123.3 PING 10.0.123.3: 56  data bytes, press CTRL_C to break Reply from 10.0.123.3: bytes=56 Sequence=1 ttl=255 time=110 ms

--- 10.0.123.3 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 110/110/110 ms

<R4>ping -c 1 10.0.45.5 PING 10.0.45.5: 56  data bytes, press CTRL_C to break Reply from 10.0.45.5: bytes=56 Sequence=1 ttl=255 time=60 ms

--- 10.0.45.5 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 60/60/60 ms
```

步骤 2 配置多区域OSPF 按照规划配置多区域OSPF，修改Loopback0 接口的网络类型为Broadcast。

```cli
#配置R1

[R1]ospf 1 router-id 10.0.1.1

[R1-ospf-1]area 0

[R1-ospf-1-area-0.0.0.0] network 10.0.123.1 0.0.0.0

[R1-ospf-1-area-0.0.0.0] quit

[R1-ospf-1]area 2

[R1-ospf-1-area-0.0.0.2] network 10.0.1.1 0.0.0.0

[R1-ospf-1-area-0.0.0.2] quit

[R1-ospf-1]quit

[R1]interface LoopBack 0

[R1-LoopBack0] ospf network-type broadcast

[R1-LoopBack0] quit

#配置R2

[R2]ospf 1 router-id 10.0.2.2

[R2-ospf-1]area 0

[R2-ospf-1-area-0.0.0.0] network 10.0.123.2 0.0.0.0

[R2-ospf-1-area-0.0.0.0] network 10.0.2.2 0.0.0.0

[R2-ospf-1-area-0.0.0.0] quit

[R2-ospf-1]quit

[R2]interface LoopBack 0

[R2-LoopBack0] ospf network-type broadcast

[R2-LoopBack0] quit

#配置R3

[R3]ospf 1 router-id 10.0.3.3

[R3-ospf-1]area 0

[R3-ospf-1-area-0.0.0.0] network 10.0.123.3 0.0.0.0

[R3-ospf-1-area-0.0.0.0] network 10.0.3.3 0.0.0.0

[R3-ospf-1-area-0.0.0.0] quit

[R3-ospf-1]quit

[R3]interface LoopBack 0

[R3-LoopBack0] ospf network-type broadcast

[R3-LoopBack0] quit

#配置R4

[R4]ospf 1 router-id 10.0.4.4

[R4-ospf-1]area 0

[R4-ospf-1-area-0.0.0.0] network 10.0.4.4 0.0.0.0

[R4-ospf-1-area-0.0.0.0] network 10.0.123.4 0.0.0.0

[R4-ospf-1-area-0.0.0.0] quit

[R4-ospf-1]area 1

[R4-ospf-1-area-0.0.0.1] network 10.0.45.4 0.0.0.0

[R4-ospf-1-area-0.0.0.1] quit

[R4-ospf-1]quit

[R4]interface LoopBack 0

[R4-LoopBack0] ospf network-type broadcast

[R4-LoopBack0] quit

#配置R5

[R5]ospf 1 router-id 10.0.5.5

[R5-ospf-1]area 1

[R5-ospf-1-area-0.0.0.1] network 10.0.45.5 0.0.0.0

[R5-ospf-1-area-0.0.0.1] quit

[R5-ospf-1]quit
```

步骤 3 检查OSPF 配置结果

```cli
#在R4 上检查OSPF 邻居的概要信息

[R4]display ospf peer brief

OSPF Process 1 with Router ID 10.0.4.4

Peer Statistic Information ---------------------------------------------------------------------------- Area Id          Interface                      Neighbor id      State

0.0.0.0          GigabitEthernet0/0/1             10.0.1.1         Full

0.0.0.0          GigabitEthernet0/0/1             10.0.2.2         Full

0.0.0.0          GigabitEthernet0/0/1             10.0.3.3         2-Way

0.0.0.1          GigabitEthernet0/0/2             10.0.5.5         Full

---------------------------------------------------------------------------- R3、R4 之间只建立了邻居关系，而没有邻接关系。

#在R4 上查看OSPF 路由表

[R4]display ospf routing

OSPF Process 1 with Router ID 10.0.4.4

Routing Tables

Routing for Network Destination        Cost  Type       NextHop      AdvRouter       Area 10.0.4.0/24        0     Stub       10.0.4.4        10.0.4.4        0.0.0.0 10.0.45.0/24       1     Transit     10.0.45.4       10.0.4.4        0.0.0.1 10.0.123.0/24      1     Transit     10.0.123.4      10.0.4.4        0.0.0.0 10.0.1.0/24        1     Inter-area   10.0.123.1      10.0.1.1        0.0.0.0 10.0.2.0/24        1     Stub       10.0.123.2      10.0.2.2        0.0.0.0 10.0.3.0/24        1     Stub       10.0.123.3      10.0.3.3        0.0.0.0

Total Nets: 6 Intra Area: 5  Inter Area: 1  ASE: 0  NSSA: 0

#在R5 上查看OSPF LSDB

[R5]display ospf lsdb

OSPF Process 1 with Router ID 10.0.5.5

Link State Database

Area: 0.0.0.1 Type      LinkState ID    AdvRouter           Age Len   Sequence   Metric Router      10.0.5.5       10.0.5.5          470  36    80000008      1 Router      10.0.4.4       10.0.4.4         1660  36    80000005      1 Network    10.0.45.4       10.0.4.4         1660  32    80000002      0 Sum-Net    10.0.3.0       10.0.4.4         1710  28    80000001      1 Sum-Net    10.0.2.0       10.0.4.4         1710  28    80000001      1 Sum-Net    10.0.1.0       10.0.4.4         1710  28    80000001      1 Sum-Net    10.0.4.0       10.0.4.4         1700  28    80000001      0 Sum-Net    10.0.123.0      10.0.4.4         1710  28    80000001      1 区域1 中仅存在2 台路由器，所以在R5 的LSDB 中，仅存在2 条Type-1 LSA，剩余的5 条 Type-3 LSA 为R4 向R5 通告的区域间路由。

#在R2 上查看OSPF LSDB

[R2]display ospf lsdb

OSPF Process 1 with Router ID 10.0.2.2

Link State Database

Area: 0.0.0.0 Type      LinkState ID    AdvRouter         Age  Len   Sequence   Metric Router     10.0.3.3       10.0.3.3          256  48    8000000B       1 Router     10.0.4.4       10.0.4.4          211  48    8000000A       1 Router     10.0.2.2       10.0.2.2          268  48    8000000C       1 Router     10.0.1.1       10.0.1.1          270  36    8000000B       1 Network   10.0.123.1      10.0.1.1          270  40    80000007      0 Sum-Net   10.0.1.0       10.0.1.1          399  28    80000002      0 Sum-Net   10.0.45.0       10.0.4.4          265  28    80000002      1 在R2 上除了4 条Type-1 LSA 以外，还有1 条Type-2 LSA。R2 的GE 0/0/1 接口所连接的是 一个广播型网络，该网络上的DR 会产生1 条Type-2 LSA 来描述所有的邻居。在这里可以从 AdvRouter 字段得知生成这条LSA 的路由器是R1，符合R1 是该网段DR 的结果。
```

步骤 4 修改接口的DR 优先级，影响DR 选举

```cli
#修改R4 的GE0/0/1 接口的DR 优先级为255，确保R4 成为10.0.123.0/24 网段的DR

[R4]interface GigabitEthernet0/0/1

[R4-GigabitEthernet0/0/1] ospf dr-priority 255

[R4-GigabitEthernet0/0/1] quit

#修改R3 的GE0/0/1 接口的DR 优先级为254，确保R3 成为10.0.123.0/24 网段的BDR

[R3]interface GigabitEthernet0/0/1

[R3-GigabitEthernet0/0/1] ospf dr-priority 254

[R3-GigabitEthernet0/0/1] quit

#修改R2 的GE0/0/1 接口的DR 优先级为0，确保R2 不参与选举

[R2]interface GigabitEthernet0/0/1

[R2-GigabitEthernet0/0/1] ospf dr-priority 0

[R2-GigabitEthernet0/0/1] quit

#为重新选举DR、BDR，关闭再重新打开R1、R2、R3、R4 的GE0/0/1 接口

[R1]interface GigabitEthernet 0/0/1

[R1-GigabitEthernet0/0/1] shutdown

[R2]interface GigabitEthernet 0/0/1

[R2-GigabitEthernet0/0/1] shutdown

[R3]interface GigabitEthernet 0/0/1

[R3-GigabitEthernet0/0/1] shutdown

[R4]interface GigabitEthernet 0/0/1

[R4-GigabitEthernet0/0/1] shutdown

[R1]interface GigabitEthernet 0/0/1

[R1-GigabitEthernet0/0/1] undo shutdown

[R1-GigabitEthernet0/0/1] quit

[R2]interface GigabitEthernet 0/0/1

[R2-GigabitEthernet0/0/1] undo shutdown

[R2-GigabitEthernet0/0/1] quit

[R3]interface GigabitEthernet 0/0/1

[R3-GigabitEthernet0/0/1] undo shutdown

[R3-GigabitEthernet0/0/1] quit

[R4]interface GigabitEthernet 0/0/1

[R4-GigabitEthernet0/0/1] undo shutdown

[R4-GigabitEthernet0/0/1] quit
```

为保证选举结果按照设置的优先级决定，尽量同时重新打开接口，否则可能会出现先打开接口 的路由器成为DR、BDR。

```cli
#在R3 上查看DR、BDR 选举结果

<R3>display ospf peer

OSPF Process 1 with Router ID 10.0.3.3

Neighbors

Area 0.0.0.0 interface 10.0.123.3(GigabitEthernet0/0/1)'s neighbors Router ID: 10.0.1.1         Address: 10.0.123.1 State: Full  Mode:Nbr is  Slave  Priority: 1 DR: 10.0.123.4  BDR: 10.0.123.3  MTU: 0 Dead timer due in 40  sec Retrans timer interval: 5

Neighbor is up for 00:59:26 Authentication Sequence: [ 0 ]

Router ID: 10.0.2.2         Address: 10.0.123.2 State: Full  Mode:Nbr is  Slave  Priority: 0 DR: 10.0.123.4  BDR: 10.0.123.3  MTU: 0 Dead timer due in 36  sec Retrans timer interval: 4 Neighbor is up for 00:59:36 Authentication Sequence: [ 0 ]

Router ID: 10.0.4.4         Address: 10.0.123.4 State: Full  Mode:Nbr is  Master  Priority: 255 DR: 10.0.123.4  BDR: 10.0.123.3  MTU: 0 Dead timer due in 34  sec Retrans timer interval: 0 Neighbor is up for 00:59:53 Authentication Sequence: [ 0 ]
```

此时R4 为DR、R3 为BDR。

```cli
#在R1 上查看R1、R2 之间的邻居关系

<R1>display ospf peer brief

OSPF Process 1 with Router ID 10.0.1.1

Peer Statistic Information ---------------------------------------------------------------------------- Area Id          Interface                      Neighbor id      State

0.0.0.0          GigabitEthernet0/0/1             10.0.2.2         2-Way

0.0.0.0          GigabitEthernet0/0/1             10.0.3.3         Full

0.0.0.0          GigabitEthernet0/0/1             10.0.4.4         Full

---------------------------------------------------------------------------- R1、R2 都为DRother，它们之间保持在2-Way 状态，只建立了邻居关系，不存在邻接关 系。
```

步骤 5 将直连路由引入OSPF 中

```cli
#R5 上Loopback0 接口不属于OSPF 区域，将Loopback0 接口路由引入到OSPF 中

[R5]ospf 1

[R5-ospf-1] import-route direct

#在R1 上查看引入的外部路由条目

<R1>display ospf routing

OSPF Process 1 with Router ID 10.0.1.1

Routing Tables

Routing for Network Destination        Cost  Type       NextHop       AdvRouter       Area 10.0.1.0/24        0     Stub       10.0.1.1        10.0.1.1        0.0.0.2

10.0.123.0/24      1     Transit     10.0.123.1      10.0.1.1        0.0.0.0 10.0.2.0/24        1     Stub       10.0.123.2      10.0.2.2        0.0.0.0 10.0.3.0/24        1     Stub       10.0.123.3      10.0.3.3        0.0.0.0 10.0.4.0/24        1     Stub       10.0.123.4      10.0.4.4        0.0.0.0 10.0.45.0/24       2     Inter-area   10.0.123.4      10.0.4.4        0.0.0.0

Routing for ASEs Destination        Cost      Type       Tag         NextHop       AdvRouter 10.0.5.0/24        1         Type2      1           10.0.123.4      10.0.5.5

Total Nets: 7 Intra Area: 5  Inter Area: 1  ASE: 1  NSSA: 0 Loopback0
```

接口路由已经成功被引入到OSPF 中，以外部路由形式存在。

```cli
#在R1 上查看Type-5 LSA

<R1>display ospf lsdb ase

OSPF Process 1 with Router ID 10.0.1.1

Link State Database

Type      : External Ls id     : 10.0.5.0 Adv rtr   : 10.0.5.5 Ls age    : 429 Len       : 36 Options   :  E seq#      : 80000001 chksum    : 0xa904 Net mask  : 255.255.255.0 TOS 0  Metric: 1 E type    : 2 Forwarding Address : 0.0.0.0 Tag       : 1 Priority  : Low

Type      : External Ls id     : 10.0.45.0 Adv rtr   : 10.0.5.5 Ls age    : 429 Len       : 36 Options   :  E seq#      : 80000001 chksum    : 0xef95 Net mask  : 255.255.255.0 TOS 0  Metric: 1 E type    : 2 Forwarding Address : 0.0.0.0 Tag       : 1 Priority  : Low
```

可以看到Type-5 LSA 存在2 条，但是R1 的路由表中OSPF 外部路由只存在1 条 10.0.5.0/24，这是因为关于10.0.45.0/24 路由同时还存在区域间路由，且区域间路由的优先 级高于OSPF 外部路由。

```cli
#在R1 上查看Type-3 LSA（以下只展示了区域0 中的Type-3 LSA）

<R1>display ospf lsdb summary

OSPF Process 1 with Router ID 10.0.1.1

Area: 0.0.0.0 Link State Database

Type      : Sum-Net Ls id     : 10.0.1.0 Adv rtr   : 10.0.1.1 Ls age    : 1487 Len       : 28 Options   :  E seq#      : 80000003 chksum    : 0x72d1 Net mask  : 255.255.255.0 Tos 0  metric: 0 Priority  : Low

Type      : Sum-Net Ls id     : 10.0.45.0 Adv rtr   : 10.0.4.4 Ls age    : 1506 Len       : 28 Options   :  E seq#      : 80000003 chksum    : 0x6fa1 Net mask  : 255.255.255.0 Tos 0  metric: 1 Priority  : Low
```

可以看到Type-3 LSA 中同样存在10.0.45.0/24，当Type-3 LSA 和Type-5 LSA 所描述的路由 前缀及掩码相同时，OSPF 优选通过Type-3 LSA 计算出的路由加载到路由表。

步骤 6 观察各种类型的LSA

```cli
#在R1 上查看Type-1 LSA 10.0.1.1

<R1>display ospf lsdb router 10.0.1.1

OSPF Process 1 with Router ID 10.0.1.1

Area: 0.0.0.0 Link State Database

Type      : Router Ls id     : 10.0.1.1

Adv rtr   : 10.0.1.1 Ls age    : 202 Len       : 36 Options   :  ABR  E seq#      : 80000015 chksum    : 0x31e4 Link count: 1 * Link ID: 10.0.123.4 Data   : 10.0.123.1 Link Type: TransNet Metric : 1 Area: 0.0.0.2 Link State Database

Type      : Router Ls id     : 10.0.1.1 Adv rtr   : 10.0.1.1 Ls age    : 180 Len       : 36 Options   :  ABR  E seq#      : 80000005 chksum    : 0x1615 Link count: 1 * Link ID: 10.0.1.0 Data   : 255.255.255.0 Link Type: StubNet Metric : 0 Priority : Low 对于Type-1 LSA 来说，Ls id 字段表示生成这条LSA 的路由器Router ID。
```

从输出信息中可以看到R1 生成了2 条Type-1 LSA，1 条在区域0 中泛洪，1 条在区域2 中泛 洪。 在区域0 中R1 与一个transmit 类型的网段相连，可以看到其Link ID 字段的值为该网段上的 DR 接口IP 地址，Data 部分为本地与DR 相连的接口IP 地址。 在区域2 中，R1 的Loopback0 接口属于该区域，可以看到其Link Type 为StubNet，其Link ID 值为该StubNet 网段的IP 地址，Data 部分为StubNet 网段的网络掩码。

```cli
#在R2 上查看Type-2 LSA

<R2>display ospf lsdb network

OSPF Process 1 with Router ID 10.0.2.2

Area: 0.0.0.0 Link State Database

Type      : Network Ls id     : 10.0.123.4 Adv rtr   : 10.0.4.4 Ls age    : 817 Len       : 40

Options   :  E seq#      : 80000007 chksum    : 0x373d Net mask  : 255.255.255.0 Priority  : Low Attached Router    10.0.4.4 Attached Router    10.0.1.1 Attached Router    10.0.2.2 Attached Router    10.0.3.3 Type-2 LSA 由DR 产生，从Adv rtr 字段可以验证这一点（该LSA 由10.0.4.4 产生，即DR 生 成），对于Type-2 LSA，其Ls ID 字段值为该网段上DR 的接口IP 地址，Attached Router 为 该网段上所有路由器的Router ID。

#在R1 上查看Type-3 LSA 10.0.45.0

<R1>display ospf lsdb summary 10.0.45.0

OSPF Process 1 with Router ID 10.0.1.1

Area: 0.0.0.0 Link State Database

Type      : Sum-Net Ls id     : 10.0.45.0 Adv rtr   : 10.0.4.4 Ls age    : 1290 Len       : 28 Options   :  E seq#      : 80000004 chksum    : 0x6da2 Net mask  : 255.255.255.0 Tos 0  metric: 1 Priority  : Low Area: 0.0.0.2 Link State Database

Type      : Sum-Net Ls id     : 10.0.45.0 Adv rtr   : 10.0.1.1 Ls age    : 1250 Len       : 28 Options   :  E seq#      : 80000004 chksum    : 0x9e76 Net mask  : 255.255.255.0 Tos 0  metric: 2 Priority  : Low Type-3 LSA 的Ls ID 字段值为网络前缀，而net mask 携带了网络掩码，在R1 上
```

可以看到2 条Type-3 LSA。一条在区域0 内，从adv rtr 可以判断出为R4 产生，由R4 从区域1 向区域
中通告产生，另外一条在区域2 中，从adv rtr 可以判断出由R1 自身产生，R1 作为连接区

域0 与区域2 的ABR，同样会产生一条Type-3 LSA，用于向区域2 通告。

```cli
#在R1 上查看Type-4 LSA

<R1>display ospf lsdb asbr 10.0.5.5

OSPF Process 1 with Router ID 10.0.1.1

Area: 0.0.0.0 Link State Database

Type      : Sum-Asbr Ls id     : 10.0.5.5 Adv rtr   : 10.0.4.4 Ls age    : 1257 Len       : 28 Options   :  E seq#      : 80000002 chksum    : 0xea49 Tos 0  metric: 1 Area: 0.0.0.2 Link State Database

Type      : Sum-Asbr Ls id     : 10.0.5.5 Adv rtr   : 10.0.1.1 Ls age    : 1256 Len       : 28 Options   :  E seq#      : 80000002 chksum    : 0x1c1d Tos 0  metric: 2 Type-4 LSA 用于描述如何到达ASBR，
```

从输出信息中可以看出R1 上存在2 条Type-4 LSA， 一条在区域0 中，从adv rtr 可知为R4 产生，另外一条为R1 自身产生，R1 作为连接区域0 与区域2 的ABR，自身生成了一条Type-4 LSA，其Adv rtr 字段为自身Router ID。

步骤 7 观察LSR、LSU 和LSAck 默认情况下，网络稳定运行，OSPF 路由器每30 分钟更新一次。为了触发OSPF 的查询和更 新信息，取消在R4 的Loopback0 接口上激活OSPF，在R1 上观察OSPF 报文。

```cli
#在R1 上开启debugging ospf packet update、debugging ospf packet ack

<R1>terminal debugging Info: Current terminal debugging is on. <R1>terminal monitor Info: Current terminal monitor is on. <R1>debugging ospf packet update <R1>debugging ospf packet ack

#取消R4 的Loopback0 接口激活OSPF 的配置

[R4]ospf 1

[R4-ospf-1]area 0

[R4-ospf-1-area-0.0.0.0] undo network 10.0.4.4 0.0.0.0

#查看R1 的debug 输出信息

May 25 2020 20:27:47.210.1-08:00 R1 RM/6/RMDEBUG: FileID: 0x70178024 Line: 2218 Level: 0x20

OSPF 1: RECV Packet. Interface: GigabitEthernet0/0/1

May 25 2020 20:27:47.210.2-08:00 R1 RM/6/RMDEBUG:  Source Address: 10.0.123.4 May 25 2020 20:27:47.210.3-08:00 R1 RM/6/RMDEBUG:  Destination Address: 224.0.0.5 May 25 2020 20:27:47.210.4-08:00 R1 RM/6/RMDEBUG:  Ver# 2, Type: 4 (Link-State Update) May 25 2020 20:27:47.210.5-08:00 R1 RM/6/RMDEBUG:  Length: 64, Router: 10.0.4.4 May 25 2020 20:27:47.210.6-08:00 R1 RM/6/RMDEBUG:  Area: 0.0.0.0, Chksum: 5451 May 25 2020 20:27:47.210.7-08:00 R1 RM/6/RMDEBUG:  AuType: 00 May 25 2020 20:27:47.210.8-08:00 R1 RM/6/RMDEBUG:  Key(ascii): 0 0 0 0 0 0 0 0 May 25 2020 20:27:47.210.9-08:00 R1 RM/6/RMDEBUG:  # LSAS: 1 May 25 2020 20:27:47.210.10-08:00 R1 RM/6/RMDEBUG:  LSA Type 1 May 25 2020 20:27:47.210.11-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.4.4 May 25 2020 20:27:47.210.12-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.4.4 May 25 2020 20:27:47.210.13-08:00 R1 RM/6/RMDEBUG:    LSA Age: 1 May 25 2020 20:27:47.210.14-08:00 R1 RM/6/RMDEBUG:    Options: ExRouting:ON May 25 2020 20:27:47.210.15-08:00 R1 RM/6/RMDEBUG:    Length: 36, Seq# 80000017 May 25 2020 20:27:47.210.16-08:00 R1 RM/6/RMDEBUG:    CheckSum: f014 May 25 2020 20:27:47.210.17-08:00 R1 RM/6/RMDEBUG:    NtBit: 0  VBit: 0 EBit: 0 BBit: 1 May 25 2020 20:27:47.210.18-08:00 R1 RM/6/RMDEBUG:    # Links: 1 May 25 2020 20:27:47.210.19-08:00 R1 RM/6/RMDEBUG:    LinkID: 10.0.123.4 May 25 2020 20:27:47.210.20-08:00 R1 RM/6/RMDEBUG:      LinkData: 10.0.123.4 May 25 2020 20:27:47.210.21-08:00 R1 RM/6/RMDEBUG:      LinkType: 2 May 25 2020 20:27:47.210.22-08:00 R1 RM/6/RMDEBUG:      TOS# 0 Metric 1 May 25 2020 20:27:47.210.23-08:00 R1 RM/6/RMDEBUG: May 25 2020 20:27:47.570.1-08:00 R1 RM/6/RMDEBUG: FileID: 0x70178024 Line: 2218 Level: 0x20

OSPF 1: RECV Packet. Interface: GigabitEthernet0/0/1

May 25 2020 20:27:47.570.2-08:00 R1 RM/6/RMDEBUG:  Source Address: 10.0.123.3 May 25 2020 20:27:47.570.3-08:00 R1 RM/6/RMDEBUG:  Destination Address: 224.0.0.5 May 25 2020 20:27:47.570.4-08:00 R1 RM/6/RMDEBUG:  Ver# 2, Type: 5 (Link-State Ack) May 25 2020 20:27:47.570.5-08:00 R1 RM/6/RMDEBUG:  Length: 44, Router: 10.0.3.3 May 25 2020 20:27:47.570.6-08:00 R1 RM/6/RMDEBUG:  Area: 0.0.0.0, Chksum: 6271 May 25 2020 20:27:47.570.7-08:00 R1 RM/6/RMDEBUG:  AuType: 00 May 25 2020 20:27:47.570.8-08:00 R1 RM/6/RMDEBUG:  Key(ascii): 0 0 0 0 0 0 0 0 May 25 2020 20:27:47.570.9-08:00 R1 RM/6/RMDEBUG:  # LSA Headers: 1 May 25 2020 20:27:47.570.10-08:00 R1 RM/6/RMDEBUG:  LSA Type 1 May 25 2020 20:27:47.570.11-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.4.4 May 25 2020 20:27:47.570.12-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.4.4 May 25 2020 20:27:47.570.13-08:00 R1 RM/6/RMDEBUG:    LSA Age: 1 May 25 2020 20:27:47.570.14-08:00 R1 RM/6/RMDEBUG:    Options: ExRouting:ON May 25 2020 20:27:47.570.15-08:00 R1 RM/6/RMDEBUG:    Length: 36, Seq# 80000017 May 25 2020 20:27:47.570.16-08:00 R1 RM/6/RMDEBUG:    CheckSum: f014 May 25 2020 20:27:47.570.17-08:00 R1 RM/6/RMDEBUG: May 25 2020 20:27:47.990.1-08:00 R1 RM/6/RMDEBUG: FileID: 0x70178025 Line: 4427 Level: 0x20

OSPF 1: SEND Packet. Interface: GigabitEthernet0/0/1

May 25 2020 20:27:47.990.2-08:00 R1 RM/6/RMDEBUG:  Source Address: 10.0.123.1 May 25 2020 20:27:47.990.3-08:00 R1 RM/6/RMDEBUG:  Destination Address: 224.0.0.6

May 25 2020 20:27:47.990.4-08:00 R1 RM/6/RMDEBUG:  Ver# 2, Type: 5 (Link-State Ack) May 25 2020 20:27:47.990.5-08:00 R1 RM/6/RMDEBUG:  Length: 44, Router: 10.0.1.1 May 25 2020 20:27:47.990.6-08:00 R1 RM/6/RMDEBUG:  Area: 0.0.0.0, Chksum: 6472 May 25 2020 20:27:47.990.7-08:00 R1 RM/6/RMDEBUG:  AuType: 00 May 25 2020 20:27:47.990.8-08:00 R1 RM/6/RMDEBUG:  Key(ascii): 0 0 0 0 0 0 0 0 May 25 2020 20:27:47.990.9-08:00 R1 RM/6/RMDEBUG:  # LSA Headers: 1 May 25 2020 20:27:47.990.10-08:00 R1 RM/6/RMDEBUG:  LSA Type 1 May 25 2020 20:27:47.990.11-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.4.4 May 25 2020 20:27:47.990.12-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.4.4 May 25 2020 20:27:47.990.13-08:00 R1 RM/6/RMDEBUG:    LSA Age: 2 May 25 2020 20:27:47.990.14-08:00 R1 RM/6/RMDEBUG:    Options: ExRouting:ON May 25 2020 20:27:47.990.15-08:00 R1 RM/6/RMDEBUG:    Length: 36, Seq# 80000017 May 25 2020 20:27:47.990.16-08:00 R1 RM/6/RMDEBUG:    CheckSum: f014
```

从输出信息中可以看到3 个报文，第1 个报文为：LSU，由R4（DR）发送，目的地址 224.0.0.5，其中只包含1 个网段，所以Links 字段值为1。 第二个报文LSAck，由R3（BDR）发送，目的地址224.0.0.5。第3 个报文同样为LSAck，由 R1 发送，目的地址224.0.0.6，该报文为R1 发送给DR、BDR。

```cli
#重新在Loopback0 接口上激活OSPF

[R4]ospf 1

[R4-ospf-1]area 0

[R4-ospf-1-area-0.0.0.0] network 10.0.4.4 0.0.0.0

#在R1 上查看debug 输出

May 25 2020 20:39:26.150.1-08:00 R1 RM/6/RMDEBUG: FileID: 0x70178024 Line: 2218 Level: 0x20

OSPF 1: RECV Packet. Interface: GigabitEthernet0/0/1

May 25 2020 20:39:26.150.2-08:00 R1 RM/6/RMDEBUG:  Source Address: 10.0.123.4 May 25 2020 20:39:26.150.3-08:00 R1 RM/6/RMDEBUG:  Destination Address: 224.0.0.5 May 25 2020 20:39:26.150.4-08:00 R1 RM/6/RMDEBUG:  Ver# 2, Type: 4 (Link-State Update) May 25 2020 20:39:26.150.5-08:00 R1 RM/6/RMDEBUG:  Length: 76, Router: 10.0.4.4 May 25 2020 20:39:26.150.6-08:00 R1 RM/6/RMDEBUG:  Area: 0.0.0.0, Chksum: c8cf May 25 2020 20:39:26.150.7-08:00 R1 RM/6/RMDEBUG:  AuType: 00 May 25 2020 20:39:26.150.8-08:00 R1 RM/6/RMDEBUG:  Key(ascii): 0 0 0 0 0 0 0 0 May 25 2020 20:39:26.150.9-08:00 R1 RM/6/RMDEBUG:  # LSAS: 1 May 25 2020 20:39:26.150.10-08:00 R1 RM/6/RMDEBUG:  LSA Type 1 May 25 2020 20:39:26.150.11-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.4.4 May 25 2020 20:39:26.150.12-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.4.4 May 25 2020 20:39:26.150.13-08:00 R1 RM/6/RMDEBUG:    LSA Age: 2 May 25 2020 20:39:26.150.14-08:00 R1 RM/6/RMDEBUG:    Options: ExRouting:ON May 25 2020 20:39:26.150.15-08:00 R1 RM/6/RMDEBUG:    Length: 48, Seq# 8000001b May 25 2020 20:39:26.150.16-08:00 R1 RM/6/RMDEBUG:    CheckSum: 6b77 May 25 2020 20:39:26.150.17-08:00 R1 RM/6/RMDEBUG:    NtBit: 0  VBit: 0 EBit: 0 BBit: 1 May 25 2020 20:39:26.150.18-08:00 R1 RM/6/RMDEBUG:    # Links: 2 May 25 2020 20:39:26.150.19-08:00 R1 RM/6/RMDEBUG:    LinkID: 10.0.123.4 May 25 2020 20:39:26.150.20-08:00 R1 RM/6/RMDEBUG:      LinkData: 10.0.123.4 May 25 2020 20:39:26.150.21-08:00 R1 RM/6/RMDEBUG:      LinkType: 2 May 25 2020 20:39:26.150.22-08:00 R1 RM/6/RMDEBUG:      TOS# 0 Metric 1 May 25 2020 20:39:26.150.23-08:00 R1 RM/6/RMDEBUG:    LinkID: 10.0.4.0 May 25 2020 20:39:26.150.24-08:00 R1 RM/6/RMDEBUG:      LinkData: 255.255.255.0 May 25 2020 20:39:26.150.25-08:00 R1 RM/6/RMDEBUG:      LinkType: 3

May 25 2020 20:39:26.150.26-08:00 R1 RM/6/RMDEBUG:      TOS# 0 Metric 0 May 25 2020 20:39:26.150.27-08:00 R1 RM/6/RMDEBUG: May 25 2020 20:39:26.580.1-08:00 R1 RM/6/RMDEBUG: FileID: 0x70178024 Line: 2218 Level: 0x20

OSPF 1: RECV Packet. Interface: GigabitEthernet0/0/1

May 25 2020 20:39:26.580.2-08:00 R1 RM/6/RMDEBUG:  Source Address: 10.0.123.3 May 25 2020 20:39:26.580.3-08:00 R1 RM/6/RMDEBUG:  Destination Address: 224.0.0.5 May 25 2020 20:39:26.580.4-08:00 R1 RM/6/RMDEBUG:  Ver# 2, Type: 5 (Link-State Ack) May 25 2020 20:39:26.580.5-08:00 R1 RM/6/RMDEBUG:  Length: 44, Router: 10.0.3.3 May 25 2020 20:39:26.580.6-08:00 R1 RM/6/RMDEBUG:  Area: 0.0.0.0, Chksum: e6fd May 25 2020 20:39:26.580.7-08:00 R1 RM/6/RMDEBUG:  AuType: 00 May 25 2020 20:39:26.580.8-08:00 R1 RM/6/RMDEBUG:  Key(ascii): 0 0 0 0 0 0 0 0 May 25 2020 20:39:26.580.9-08:00 R1 RM/6/RMDEBUG:  # LSA Headers: 1 May 25 2020 20:39:26.580.10-08:00 R1 RM/6/RMDEBUG:  LSA Type 1 May 25 2020 20:39:26.580.11-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.4.4 May 25 2020 20:39:26.580.12-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.4.4 May 25 2020 20:39:26.580.13-08:00 R1 RM/6/RMDEBUG:    LSA Age: 2 May 25 2020 20:39:26.580.14-08:00 R1 RM/6/RMDEBUG:    Options: ExRouting:ON May 25 2020 20:39:26.580.15-08:00 R1 RM/6/RMDEBUG:    Length: 48, Seq# 8000001b May 25 2020 20:39:26.580.16-08:00 R1 RM/6/RMDEBUG:    CheckSum: 6b77 May 25 2020 20:39:26.580.17-08:00 R1 RM/6/RMDEBUG: May 25 2020 20:39:26.910.1-08:00 R1 RM/6/RMDEBUG: FileID: 0x70178025 Line: 4427 Level: 0x20

OSPF 1: SEND Packet. Interface: GigabitEthernet0/0/1

May 25 2020 20:39:26.910.2-08:00 R1 RM/6/RMDEBUG:  Source Address: 10.0.123.1 May 25 2020 20:39:26.910.3-08:00 R1 RM/6/RMDEBUG:  Destination Address: 224.0.0.6 May 25 2020 20:39:26.910.4-08:00 R1 RM/6/RMDEBUG:  Ver# 2, Type: 5 (Link-State Ack) May 25 2020 20:39:26.910.5-08:00 R1 RM/6/RMDEBUG:  Length: 44, Router: 10.0.1.1 May 25 2020 20:39:26.910.6-08:00 R1 RM/6/RMDEBUG:  Area: 0.0.0.0, Chksum: e8fe May 25 2020 20:39:26.910.7-08:00 R1 RM/6/RMDEBUG:  AuType: 00 May 25 2020 20:39:26.910.8-08:00 R1 RM/6/RMDEBUG:  Key(ascii): 0 0 0 0 0 0 0 0 May 25 2020 20:39:26.910.9-08:00 R1 RM/6/RMDEBUG:  # LSA Headers: 1 May 25 2020 20:39:26.910.10-08:00 R1 RM/6/RMDEBUG:  LSA Type 1 May 25 2020 20:39:26.910.11-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.4.4 May 25 2020 20:39:26.910.12-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.4.4 May 25 2020 20:39:26.910.13-08:00 R1 RM/6/RMDEBUG:    LSA Age: 3 May 25 2020 20:39:26.910.14-08:00 R1 RM/6/RMDEBUG:    Options: ExRouting:ON May 25 2020 20:39:26.910.15-08:00 R1 RM/6/RMDEBUG:    Length: 48, Seq# 8000001b May 25 2020 20:39:26.910.16-08:00 R1 RM/6/RMDEBUG:    CheckSum: 6b77 May 25 2020 20:39:26.910.17-08:00 R1 RM/6/RMDEBUG: 首先第1 个报文还是来自R4（DR）的LSU，其中Links 字段值为2，多了1 个Loopback0 接 口路由，第2、
```

第3 个报文和之前一致：BDR 回应的LSAck 以及R1 自身回应的LSAck。

```cli
#在R1 上开启debugging ospf packet request，重置OSPF 进程

<R1>debugging ospf packet request <R1>reset ospf process 1

#观察R1 的debug 输出

FileID: 0x70178025 Line: 2886 Level: 0x20

OSPF 1: SEND Packet. Interface: GigabitEthernet0/0/1

May 25 2020 21:18:01.400.2-08:00 R1 RM/6/RMDEBUG:  Source Address: 10.0.123.1 May 25 2020 21:18:01.400.3-08:00 R1 RM/6/RMDEBUG:  Destination Address: 10.0.123 .3 May 25 2020 21:18:01.400.4-08:00 R1 RM/6/RMDEBUG:  Ver# 2, Type: 3 (Link-State Req) May 25 2020 21:18:01.400.5-08:00 R1 RM/6/RMDEBUG:  Length: 108, Router: 10.0.1.1 May 25 2020 21:18:01.400.6-08:00 R1 RM/6/RMDEBUG:  Area: 0.0.0.0, Chksum: e85a May 25 2020 21:18:01.400.7-08:00 R1 RM/6/RMDEBUG:  AuType: 00 May 25 2020 21:18:01.400.8-08:00 R1 RM/6/RMDEBUG:  Key(ascii): 0 0 0 0 0 0 0 0 May 25 2020 21:18:01.400.9-08:00 R1 RM/6/RMDEBUG:  # Requesting LSAs: 7 May 25 2020 21:18:01.400.10-08:00 R1 RM/6/RMDEBUG:  LSA Type 1 May 25 2020 21:18:01.400.11-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.1.1 May 25 2020 21:18:01.400.12-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.1.1 May 25 2020 21:18:01.400.13-08:00 R1 RM/6/RMDEBUG:  LSA Type 1 May 25 2020 21:18:01.400.14-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.2.2 May 25 2020 21:18:01.400.15-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.2.2 May 25 2020 21:18:01.400.16-08:00 R1 RM/6/RMDEBUG:  LSA Type 3 May 25 2020 21:18:01.400.17-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.45.0 May 25 2020 21:18:01.400.18-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.4.4 May 25 2020 21:18:01.400.19-08:00 R1 RM/6/RMDEBUG:  LSA Type 3 May 25 2020 21:18:01.400.20-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.1.0 May 25 2020 21:18:01.400.21-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.1.1 May 25 2020 21:18:01.400.22-08:00 R1 RM/6/RMDEBUG:  LSA Type 4 May 25 2020 21:18:01.400.23-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.5.5 May 25 2020 21:18:01.400.24-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.4.4 May 25 2020 21:18:01.400.25-08:00 R1 RM/6/RMDEBUG:  LSA Type 5 May 25 2020 21:18:01.400.26-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.5.0 May 25 2020 21:18:01.400.27-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.5.5 May 25 2020 21:18:01.400.28-08:00 R1 RM/6/RMDEBUG:  LSA Type 5 May 25 2020 21:18:01.400.29-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.45.0 May 25 2020 21:18:01.400.30-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.5.5 May 25 2020 21:18:01.400.31-08:00 R1 RM/6/RMDEBUG: May 25 2020 21:18:01.430.1-08:00 R1 RM/6/RMDEBUG: FileID: 0x70178025 Line: 2886 Level: 0x20

OSPF 1: SEND Packet. Interface: GigabitEthernet0/0/1

May 25 2020 21:18:01.430.2-08:00 R1 RM/6/RMDEBUG:  Source Address: 10.0.123.1 May 25 2020 21:18:01.430.3-08:00 R1 RM/6/RMDEBUG: May 25 2020 21:18:01.430.4-08:00 R1 RM/6/RMDEBUG:  Ver# 2, Type: 3 (Link-State R eq) May 25 2020 21:18:01.430.5-08:00 R1 RM/6/RMDEBUG:  Length: 108, Router: 10.0.1.1 May 25 2020 21:18:01.430.6-08:00 R1 RM/6/RMDEBUG:  Area: 0.0.0.0, Chksum: e85a May 25 2020 21:18:01.430.7-08:00 R1 RM/6/RMDEBUG:  AuType: 00 May 25 2020 21:18:01.430.8-08:00 R1 RM/6/RMDEBUG:  Key(ascii): 0 0 0 0 0 0 0 0 May 25 2020 21:18:01.430.9-08:00 R1 RM/6/RMDEBUG:  # Requesting LSAs: 7 May 25 2020 21:18:01.430.10-08:00 R1 RM/6/RMDEBUG:  LSA Type 1 May 25 2020 21:18:01.430.11-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.1.1 May 25 2020 21:18:01.430.12-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.1.1 May 25 2020 21:18:01.430.13-08:00 R1 RM/6/RMDEBUG:  LSA Type 1 May 25 2020 21:18:01.430.14-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.2.2 May 25 2020 21:18:01.430.15-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.2.2 May 25 2020 21:18:01.430.16-08:00 R1 RM/6/RMDEBUG:  LSA Type 3 May 25 2020 21:18:01.430.17-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.1.0 May 25 2020 21:18:01.430.18-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.1.1 May 25 2020 21:18:01.430.19-08:00 R1 RM/6/RMDEBUG:  LSA Type 3 May 25 2020 21:18:01.430.20-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.45.0 May 25 2020 21:18:01.430.21-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.4.4

May 25 2020 21:18:01.430.22-08:00 R1 RM/6/RMDEBUG:  LSA Type 4 May 25 2020 21:18:01.430.23-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.5.5 May 25 2020 21:18:01.430.24-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.4.4 May 25 2020 21:18:01.430.25-08:00 R1 RM/6/RMDEBUG:  LSA Type 5 May 25 2020 21:18:01.430.26-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.5.0 May 25 2020 21:18:01.430.27-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.5.5 May 25 2020 21:18:01.430.28-08:00 R1 RM/6/RMDEBUG:  LSA Type 5 May 25 2020 21:18:01.430.29-08:00 R1 RM/6/RMDEBUG:    LS ID: 10.0.45.0 May 25 2020 21:18:01.430.30-08:00 R1 RM/6/RMDEBUG:    Adv Rtr: 10.0.5.5
```

从输出可以看到R1 向R3（BDR）、R4（DR）发送了LS Request。

## 1.3.3 思考题

Type-4 LSA 什么时候会存在，其作用是？

## 1.3.4 配置参考

R1 设备配置

```cli
sysname R1

interface GigabitEthernet0/0/1

ip address 10.0.123.1 255.255.255.0

interface LoopBack0

ip address 10.0.1.1 255.255.255.0

ospf network-type broadcast

ospf 1 router-id 10.0.1.1

area 0.0.0.0 network 10.0.123.1 0.0.0.0 area 0.0.0.2 network 10.0.1.1 0.0.0.0
```

R2 设备配置

```cli
sysname R2

interface GigabitEthernet0/0/1

ip address 10.0.123.2 255.255.255.0

ospf dr-priority 0

interface LoopBack0

ip address 10.0.2.2 255.255.255.0

ospf network-type broadcast

ospf 1 router-id 10.0.2.2

area 0.0.0.0 network 10.0.123.2 0.0.0.0 network 10.0.2.2 0.0.0.0
```

R3 设备配置

```cli
sysname R3

interface GigabitEthernet0/0/1

ip address 10.0.123.3 255.255.255.0

ospf dr-priority 254

interface LoopBack0

ip address 10.0.3.3 255.255.255.0

ospf network-type broadcast

ospf 1 router-id 10.0.3.3

area 0.0.0.0 network 10.0.123.3 0.0.0.0 network 10.0.3.3 0.0.0.0
```

R4 设备配置

```cli
sysname R4

interface GigabitEthernet0/0/1

ip address 10.0.123.4 255.255.255.0

ospf dr-priority 255

interface GigabitEthernet0/0/2

ip address 10.0.45.4 255.255.255.0

interface LoopBack0

ip address 10.0.4.4 255.255.255.0

ospf network-type broadcast

ospf 1 router-id 10.0.4.4

area 0.0.0.0 network 10.0.123.4 0.0.0.0 network 10.0.4.4 0.0.0.0 area 0.0.0.1 network 10.0.45.4 0.0.0.0
```

R5 设备配置

```cli
sysname R5

interface GigabitEthernet0/0/3

ip address 10.0.45.5 255.255.255.0

interface LoopBack0

ip address 10.0.5.5 255.255.255.0

ospf network-type broadcast

ospf 1 router-id 10.0.5.5

import-route direct area 0.0.0.1 network 10.0.45.5 0.0.0.0
```
