---
doc_id: "hcie-datacom-v1.0-lab-11"
title: "8.2 L3VPNv4 over SR-MPLS TE"
book: "HCIE-Datacom-V1.0-Lab"
book_title: "HCIE-Datacom V1.0 实验手册"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "lab"
source_pdf: "HCIE-Datacom V1.0 实验手册.pdf"
seq: 11
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 8.2 L3VPNv4 over SR-MPLS TE

## 8.2.1 实验介绍

8.2.1.1 学习目标

- 实现通过IS-IS 完成PE 之间的路由可达
- 实现手动配置SR-MPLS TE 隧道
- 实现CE 之间互访使用的L3VPN 隧道迭代到SR-MPLS TE 隧道
- 观察SR-MPLS TE 隧道转发报文时的标签变化

8.2.1.2 实验组网介绍

图8-2 L3VPNv4 over SR-MPLS TE 实验 设备连接方式、IP 地址规划如图所示，接口互联地址均为10.0.0.Y/30，其中Y 值已在图中标 注。所有设备均创建Loopback0 接口，Loopback 接口IP 地址为10.0.X.X，其中X 值会在对应配 置步骤中使用表格标明。 PE1、PE4 上创建Loopback1 接口，地址分别为10.1.1.1/32、10.1.4.4/32，用于模拟CE 接入用 户。

## 8.2.2 实验任务

8.2.2.1 配置思路

1. 设备基础IP 地址配置。
2. 配置SR 域内的IS-IS，在互联接口、Loopback0 接口上开启IS-IS，实现SR 域内互通。
3. 配置MPLS，使能设备MPLS 功能、MPLS TE 功能，配置MPLS LSR ID。
4. 完成SR 配置，全局使能SR，在IS-IS 中开启对SR 的扩展能力、开启流量工程能力，配置 Node SID。
5. PE1、PE4 上配置显式路径以及TE 隧道接口。
6. 配置VPN 实例，将PE1、PE4 的Loopback1 接口划分到实例中，并在PE1、PE4 与P1、P2 之间建立VPNv4 对等体关系。
7. 配置隧道选择策略，将VPN 流量迭代到TE 隧道。

8.2.2.2 配置步骤

步骤 1 设备基础配置 指定命令生效模式为立即生效，配置互联接口、Loopback0 接口IP 地址，其中Loopback0 接口 地址按下表规划配置。 设备 Loopback0 接口 IP 规划：

| 设备编号 | Loopback0 接口 IP |
| --- | --- |
| PE1 | 10.0.1.1 |
| PE2 | 10.0.2.2 |
| PE3 | 10.0.3.3 |
| PE4 | 10.0.4.4 |
| P1 | 10.0.5.5 |
| P2 | 10.0.6.6 |

```cli
#设备命名。
```

略

```cli
#关闭本实验中不需要的接口。
```

略

```cli
#配置命令行生效模式为立即生效。

<PE1>system-view immediately
<PE2>system-view immediately
<PE3>system-view immediately

<PE4>system-view immediately
<P1>system-view immediately
<P2>system-view immediately

#所有设备关闭全局DCN 功能。

[PE1] undo dcn

Warning: This operation will disable DCN function. Continue? [Y/N]:y
```

以PE1 为例，其他设备执行相同操作。 NE 路由器接口默认开启了DCN 功能，为方便实验，所有设备上全局关闭DCN 功能。

```cli
#配置PE1 的互联接口、Loopback0 接口IP 地址。

[PE1]interface LoopBack0

[PE1-LoopBack0] ip address 10.0.1.1 32

[PE1-LoopBack0] quit

[PE1]interface GigabitEthernet0/5/0

[PE1-GigabitEthernet0/5/0]ip address 10.0.0.1 30

[PE1-GigabitEthernet0/5/0] quit

[PE1]interface GigabitEthernet0/5/1

[PE1-GigabitEthernet0/5/1]ip address 10.0.0.5 30

[PE1-GigabitEthernet0/5/1] quit

#配置PE2 的互联接口、Loopback0 接口IP 地址。

[PE2]interface LoopBack0

[PE2-LoopBack0] ip address 10.0.2.2 32

[PE2-LoopBack0] quit

[PE2]interface GigabitEthernet0/5/0

[PE2-GigabitEthernet0/5/0] ip address 10.0.0.2 30

[PE2-GigabitEthernet0/5/0] quit

[PE2]interface GigabitEthernet0/5/1

[PE2-GigabitEthernet0/5/1] ip address 10.0.0.9 30

[PE2-GigabitEthernet0/5/1] quit

#配置PE3 的互联接口、Loopback0 接口IP 地址。

[PE3]interface LoopBack0

[PE3-LoopBack0] ip address 10.0.3.3 32

[PE3-LoopBack0] quit

[PE3]interface GigabitEthernet0/5/0

[PE3-GigabitEthernet0/5/0] ip address 10.0.0.25 30

[PE3-GigabitEthernet0/5/0] quit

[PE3]interface GigabitEthernet0/5/1

[PE3-GigabitEthernet0/5/1] ip address 10.0.0.18 30

[PE3-GigabitEthernet0/5/1] quit

#配置PE4 的互联接口、Loopback0 接口IP 地址。

[PE4]interface LoopBack0

[PE4-LoopBack0] ip address 10.0.4.4 32

[PE4-LoopBack0] quit

[PE4]interface GigabitEthernet0/5/0

[PE4-GigabitEthernet0/5/0] ip address 10.0.0.26 30

[PE4-GigabitEthernet0/5/0] quit

[PE4]interface GigabitEthernet0/5/1

[PE4-GigabitEthernet0/5/1] undo shutdown

[PE4-GigabitEthernet0/5/1] ip address 10.0.0.22 255.255.255.252

[PE4-GigabitEthernet0/5/1] quit

#配置P1 的互联接口、Loopback0 接口IP 地址。

[P1]interface LoopBack0

[P1-LoopBack0] ip address 10.0.5.5 32

[P1-LoopBack0] quit

[P1]interface GigabitEthernet0/5/0

[P1-GigabitEthernet0/5/0] ip address 10.0.0.13 30

[P1-GigabitEthernet0/5/0] quit

[P1]interface GigabitEthernet0/5/1

[P1-GigabitEthernet0/5/1] ip address 10.0.0.6 30

[P1-GigabitEthernet0/5/1] quit

[P1]interface GigabitEthernet0/5/2

[P1-GigabitEthernet0/5/2] ip address 10.0.0.17 30

[P1-GigabitEthernet0/5/2] quit

#配置P2 的互联接口、Loopback0 接口IP 地址。

[P2]interface LoopBack0

[P2-LoopBack0] ip address 10.0.6.6 32

[P2-LoopBack0] quit

[P2]interface GigabitEthernet0/5/0

[P2-GigabitEthernet0/5/0] ip address 10.0.0.14 30

[P2-GigabitEthernet0/5/0] quit

[P2]interface GigabitEthernet0/5/1

[P2-GigabitEthernet0/5/1] ip address 10.0.0.10 30

[P2-GigabitEthernet0/5/1] quit

[P2]interface GigabitEthernet0/5/2

[P2-GigabitEthernet0/5/2] undo shutdown

[P2-GigabitEthernet0/5/2] ip address 10.0.0.21 255.255.255.252
```

步骤 2 配置IS-IS IS-IS 区域为49.0001，进程号使用1，所有设备均为L2，NET 配置为： 49.0001.000X.000X.000X.00，其中X 值见步骤1 表格，在Loopback0 接口以及互联接口上开启 IS-IS。 需要注意此时要配置cost-style 为wide，用于支持IS-IS 扩展特性。

```cli
#配置PE1 的IS-IS。

[PE1]isis 1

[PE1-isis-1] is-level level-2

[PE1-isis-1] cost-style wide

[PE1-isis-1] network-entity 49.0001.0001.0001.0001.00

[PE1-isis-1] is-name PE1

[PE1]interface LoopBack0

[PE1-LoopBack0] isis enable 1

[PE1-LoopBack0] quit

[PE1]interface GigabitEthernet0/5/0

[PE1-GigabitEthernet0/5/0] isis enable 1

[PE1-GigabitEthernet0/5/0] isis circuit-type p2p

[PE1-GigabitEthernet0/5/0] quit

[PE1]interface GigabitEthernet0/5/1

[PE1-GigabitEthernet0/5/1] isis enable 1

[PE1-GigabitEthernet0/5/1] isis circuit-type p2p

[PE1-GigabitEthernet0/5/1] quit

#配置PE2 的IS-IS。

[PE2]isis 1

[PE2-isis-1] is-level level-2

[PE2-isis-1] cost-style wide

[PE2-isis-1] network-entity 49.0001.0002.0002.0002.00

[PE2-isis-1] is-name PE2

[PE2-isis-1]interface LoopBack0

[PE2-LoopBack0] isis enable 1

[PE2-LoopBack0] quit

[PE2]interface GigabitEthernet0/5/0

[PE2-GigabitEthernet0/5/0] isis enable 1

[PE2-GigabitEthernet0/5/0] isis circuit-type p2p

[PE2-GigabitEthernet0/5/0] quit

[PE2]interface GigabitEthernet0/5/1

[PE2-GigabitEthernet0/5/1] isis enable 1

[PE2-GigabitEthernet0/5/1] isis circuit-type p2p

[PE2-GigabitEthernet0/5/1] quit

#配置PE3 的IS-IS。

[PE3]isis 1

[PE3-isis-1] is-level level-2

[PE3-isis-1] cost-style wide

[PE3-isis-1] network-entity 49.0001.0003.0003.0003.00

[PE3-isis-1] is-name PE3

[PE3-isis-1] quit

[PE3]interface LoopBack0

[PE3-LoopBack0] isis enable 1

[PE3-LoopBack0] quit

[PE3]interface GigabitEthernet0/5/0

[PE3-GigabitEthernet0/5/0] isis enable 1

[PE3-GigabitEthernet0/5/0] isis circuit-type p2p

[PE3-GigabitEthernet0/5/0] quit

[PE3]interface GigabitEthernet0/5/1

[PE3-GigabitEthernet0/5/1] isis enable 1

[PE3-GigabitEthernet0/5/1] isis circuit-type p2p

[PE3-GigabitEthernet0/5/1] quit

#配置PE4 的IS-IS。

[PE4]isis 1

[PE4-isis-1] is-level level-2

[PE4-isis-1] cost-style wide

[PE4-isis-1] network-entity 49.0001.0004.0004.0004.00

[PE4-isis-1] is-name PE4

[PE4-isis-1] quit

[PE4]interface LoopBack0

[PE4-LoopBack0] isis enable 1

[PE4-LoopBack0] quit

[PE4]interface GigabitEthernet0/5/0

[PE4-GigabitEthernet0/5/0] isis enable 1

[PE4-GigabitEthernet0/5/0] isis circuit-type p2p

[PE4-GigabitEthernet0/5/0] quit

[PE4]interface GigabitEthernet0/5/1

[PE4-GigabitEthernet0/5/1] isis enable 1

[PE4-GigabitEthernet0/5/1] isis circuit-type p2p

[PE4-GigabitEthernet0/5/1] quit

#配置P1 的IS-IS。

[P1]isis 1

[P1-isis-1] is-level level-2

[P1-isis-1] cost-style wide

[P1-isis-1] network-entity 49.0001.0005.0005.0005.00

[P1-isis-1] is-name P1

[P1-isis-1] quit

[P1]interface LoopBack0

[P1-LoopBack0] isis enable 1

[P1-LoopBack0] quit

[P1]interface GigabitEthernet0/5/0

[P1-GigabitEthernet0/5/0] isis enable 1

[P1-GigabitEthernet0/5/0] isis circuit-type p2p

[P1-GigabitEthernet0/5/0] quit

[P1]interface GigabitEthernet0/5/1

[P1-GigabitEthernet0/5/1] isis enable 1

[P1-GigabitEthernet0/5/1] isis circuit-type p2p

[P1-GigabitEthernet0/5/1] quit

[P1]interface GigabitEthernet0/5/2

[P1-GigabitEthernet0/5/2] isis enable 1

[P1-GigabitEthernet0/5/2] isis circuit-type p2p

[P1-GigabitEthernet0/5/2] quit

#配置P2 的IS-IS。

[P2]isis 1

[P2-isis-1] is-level level-2

[P2-isis-1] cost-style wide

[P2-isis-1] network-entity 49.0001.0006.0006.0006.00

[P2-isis-1] is-name P2

[P2-isis-1] quit

[P2]interface LoopBack0

[P2-LoopBack0] isis enable 1

[P2-LoopBack0] quit

[P2]interface GigabitEthernet0/5/0

[P2-GigabitEthernet0/5/0] isis enable 1

[P2-GigabitEthernet0/5/0] isis circuit-type p2p

[P2-GigabitEthernet0/5/0] quit

[P2]interface GigabitEthernet0/5/1

[P2-GigabitEthernet0/5/1] isis enable 1

[P2-GigabitEthernet0/5/1] isis circuit-type p2p

[P2-GigabitEthernet0/5/1] quit

[P2]interface GigabitEthernet0/5/2

[P2-GigabitEthernet0/5/2] isis enable 1

[P2-GigabitEthernet0/5/2] isis circuit-type p2p

[P2-GigabitEthernet0/5/2] quit

#在P1、PE2、PE4 上检查IS-IS 邻居关系。

[P1]display isis peer

Peer information for ISIS(1)
```

System Id     Interface          Circuit Id            State HoldTime Type     PRI

```cli
-------------------------------------------------------------------------------- P2             GE0/5/0            0000000006         Up   26s       L2       -- PE1            GE0/5/1            0000000007         Up   25s       L2       -- PE3            GE0/5/2            0000000007         Up   27s       L2       --

Total Peer(s): 3

[PE2]display isis peer

Peer information for ISIS(1)
```

System Id     Interface          Circuit Id            State HoldTime Type     PRI -------------------------------------------------------------------------------- PE1           GE0/5/0            0000000006         Up   26s       L2       -- P2            GE0/5/1            0000000007         Up   25s       L2       --

```cli
Total Peer(s): 2

[PE4]display isis peer

Peer information for ISIS(1)
```

System Id     Interface          Circuit Id            State HoldTime Type     PRI -------------------------------------------------------------------------------- PE3           GE0/5/0            0000000006         Up   23s       L2       -- P2            GE0/5/1            0000000007         Up   23s       L2       --

```cli
Total Peer(s): 2

#在P1 上检查IS-IS 路由。

[P1]display isis route

Route information for ISIS(1)

-----------------------------

ISIS(1) Level-2 Forwarding Table --------------------------------

IPV4 Destination   IntCost    ExtCost ExitInterface     NextHop         Flags ------------------------------------------------------------------------------- 10.0.0.0/30        20         NULL   GE0/5/1           10.0.0.5         A/-/-/- 10.0.0.4/30        10         NULL   GE0/5/1           Direct          D/-/L/- 10.0.0.8/30        20         NULL   GE0/5/0           10.0.0.14       A/-/-/- 10.0.0.12/30      10         NULL   GE0/5/0           Direct          D/-/L/- 10.0.0.16/30      10         NULL   GE0/5/2           Direct          D/-/L/-
```

10.0.0.20/30      20         NULL   GE0/5/0           10.0.0.14       A/-/-/- 10.0.0.24/30      20         NULL   GE0/5/2           10.0.0.18       A/-/-/- 10.0.1.1/32        10         NULL   GE0/5/1           10.0.0.5         A/-/-/- 10.0.2.2/32        20         NULL   GE0/5/1           10.0.0.5         A/-/-/- GE0/5/0           10.0.0.14 10.0.3.3/32        10         NULL   GE0/5/2           10.0.0.18       A/-/-/- 10.0.4.4/32        20         NULL   GE0/5/2           10.0.0.18       A/-/-/- GE0/5/0           10.0.0.14 10.0.5.5/32        0          NULL   Loop0             Direct          D/-/L/- 10.0.6.6/32        10         NULL   GE0/5/0           10.0.0.14       A/-/-/- Flags: D-Direct, A-Added to URT, L-Advertised in LSPs, S-IGP Shortcut, U-Up/Down Bit Set, LP-Local Prefix-Sid Protect Type: L-Link Protect, N-Node Protect 已完成路由学习。 步骤 3 配置MPLS 在所有设备上开启MPLS，配置MPLS LSR ID（使用Loopback0 接口IP），无需在接口上开启 MPLS。

```cli
[PE1]mpls lsr-id 10.0.1.1

[PE1]mpls

[PE2]mpls lsr-id 10.0.2.2

[PE2]mpls

[PE3]mpls lsr-id 10.0.3.3

[PE3]mpls

[PE4]mpls lsr-id 10.0.4.4

[PE4]mpls

[P1]mpls lsr-id 10.0.5.5

[P1]mpls

[P2]mpls lsr-id 10.0.6.6

[P2]mpls
```

步骤 4 配置设备的SR 能力 全局使能SR-MPLS，在IS-IS 中开启对SR 功能的扩展支持，在IS-IS 中配置全局SRGB，所有设 备SRGB 范围统一配置为：16000~17000。

```cli
#配置Loopback0 接口的SID，采用index 的方式指定标签相对值，该相对值为X，X 参照步骤1 中表格。

#配置PE1。

[PE1] segment-routing

[PE1-segment-routing] quit

[PE1] isis 1

[PE1-isis-1] segment-routing mpls

[PE1-isis-1] segment-routing global-block 16000 17000

[PE1-isis-1] quit

[PE1] interface LoopBack 0

[PE1-LoopBack0] isis prefix-sid index 1

[PE1-LoopBack0] quit

#配置PE2。

[PE2] segment-routing

[PE2-segment-routing] quit

[PE2] isis 1

[PE2-isis-1] segment-routing mpls

[PE2-isis-1] segment-routing global-block 16000 17000

[PE2-isis-1] quit

[PE2] interface LoopBack 0

[PE2-LoopBack0] isis prefix-sid index 2

[PE2-LoopBack0] quit

#配置PE3。

[PE3] segment-routing

[PE3-segment-routing] quit

[PE3] isis 1

[PE3-isis-1] segment-routing mpls

[PE3-isis-1] segment-routing global-block 16000 17000

[PE3-isis-1] quit

[PE3] interface LoopBack 0

[PE3-LoopBack0] isis prefix-sid index 3

[PE3-LoopBack0] quit

#配置PE4。

[PE4] segment-routing

[PE4-segment-routing] quit

[PE4] isis 1

[PE4-isis-1] segment-routing mpls

[PE4-isis-1] segment-routing global-block 16000 17000

[PE4-isis-1] quit

[PE4] interface LoopBack 0

[PE4-LoopBack0] isis prefix-sid index 4

[PE4-LoopBack0] quit

#配置P1。

[P1] segment-routing

[P1-segment-routing] quit

[P1] isis 1

[P1-isis-1] segment-routing mpls

[P1-isis-1] segment-routing global-block 16000 17000

[P1-isis-1] quit

[P1] interface LoopBack 0

[P1-LoopBack0] isis prefix-sid index 5

[P1-LoopBack0] quit

#配置P2。

[P2] segment-routing

[P2-segment-routing] quit

[P2] isis 1

[P2-isis-1] segment-routing mpls

[P2-isis-1] segment-routing global-block 16000 17000

[P2-isis-1] quit

[P2] interface LoopBack 0

[P2-LoopBack0] isis prefix-sid index 6

[P2-LoopBack0] quit

#P1、P2 上手动配置adjacency SID
```

```cli
为了在配置显式路径时指定的邻接标签一直保持不变，建议静态配置邻接标签，这样可保持设 备重启之后标签不变。 P1、P2 的静态邻接标签值配置按下表。 邻接标签 设备编号 本端IP 对端IP 标签值 P1 10.0.0.6 10.0.0.5 142336 P1 10.0.0.13 10.0.0.14 142337 P1 10.0.0.17 10.0.0.18 142338 P2 10.0.0.10 10.0.0.9 142336 P2 10.0.0.14 10.0.0.13 142337

P2 10.0.0.21 10.0.0.22 142338
```

```cli
[P1] segment-routing

[P1-segment-routing] ipv4 adjacency local-ip-addr 10.0.0.6 remote-ip-addr 10.0.0.5 sid 142336

[P1-segment-routing] ipv4 adjacency local-ip-addr 10.0.0.13 remote-ip-addr 10.0.0.14 sid 142337

[P1-segment-routing] ipv4 adjacency local-ip-addr 10.0.0.17 remote-ip-addr 10.0.0.18 sid 142338

[P2] segment-routing

[P2-segment-routing] ipv4 adjacency local-ip-addr 10.0.0.10 remote-ip-addr 10.0.0.9 sid 142336

[P2-segment-routing] ipv4 adjacency local-ip-addr 10.0.0.14 remote-ip-addr 10.0.0.13 sid 142337

[P2-segment-routing] ipv4 adjacency local-ip-addr 10.0.0.21 remote-ip-addr 10.0.0.22 sid 142338
```

步骤 5 配置SR-MPLS TE 显式路径以及TE 隧道接口 在PE1、PE4 上配置显式路径，指定路径必须经过的节点（通过指定Node SID 以及邻接SID 实 现），并在PE1、PE4 上创建TE 隧道接口，调用配置的显式路径。 该实验通过命令行实现，无控制器参与，正常有控制器参与的场景下，路径为控制器计算生 成。

```cli
#创建显式路径，强制指定转发路径。

[PE1] explicit-path PE1_PE4_Manual

[PE1-explicit-path-PE1_PE4_Manual] next sid label 16005 type prefix

[PE1-explicit-path-PE1_PE4_Manual] next sid label 142337 type adjacency

[PE1-explicit-path-PE1_PE4_Manual] next sid label 142338 type adjacency

#在PE1 上配置显式路径PE1_PE4_Manual，强制指定经过P1、P1 的GE0/5/0 接口、P2 的 GE0/5/2 接口。

[PE4] explicit-path PE4_PE1_Manual

[PE4-explicit-path-PE4_PE1_Manual] next sid label 16003 type prefix

[PE4-explicit-path-PE4_PE1_Manual] next sid label 16005 type prefix

[PE4-explicit-path-PE4_PE1_Manual] next sid label 142337 type adjacency

[PE4-explicit-path-PE4_PE1_Manual] next sid label 142336 type adjacency

[PE4-explicit-path-PE4_PE1_Manual] next sid label 16001 type prefix

#在PE4 上配置显式路径PE4_PE1_Manual，强制指定经过PE3、P1、P1 的GE0/5/0 接口、P2 的 GE0/5/1、PE2。

#全局开启MPLS TE。

[PE1]mpls

[PE1-mpls]mpls te

[PE4]mpls

[PE4-mpls]mpls te

#创建TE 隧道接口。

[PE1] interface Tunnel10

[PE1-Tunnel10] ip address unnumbered interface LoopBack0

[PE1-Tunnel10] tunnel-protocol mpls te

[PE1-Tunnel10] destination 10.0.4.4

[PE1-Tunnel10] mpls te signal-protocol segment-routing

[PE1-Tunnel10] mpls te tunnel-id 10

[PE1-Tunnel10] mpls te path explicit-path PE1_PE4_Manual
```

```cli
PE1 上创建Tunnel 接口10，借用Loopback0 接口IP 地址，目的地址配置为10.0.4.4（PE4 Loopback0 接口IP 地址），关联显式路径PE1_PE4_Manual。
```

```cli
[PE4] interface Tunnel10

[PE4-Tunnel10] ip address unnumbered interface LoopBack0

[PE4-Tunnel10] tunnel-protocol mpls te

[PE4-Tunnel10] destination 10.0.1.1

[PE4-Tunnel10] mpls te signal-protocol segment-routing

[PE4-Tunnel10] mpls te tunnel-id 10

[PE4-Tunnel10] mpls te path explicit-path PE4_PE1_Manual
```

```cli
PE4 上创建Tunnel 接口10，借用Loopback0 接口IP 地址，目的地址配置为10.0.1.1（PE4 Loopback0 接口IP 地址），关联显式路径PE4_PE1_Manual。
```

```cli
#检查SR-MPLS TE 隧道状态。

[PE1]display tunnel-info all
```

```cli
Tunnel ID               Type             Destination              Status ---------------------------------------------------------------------------------------- 0x000000000300000001  sr-te            10.0.4.4                   UP 0x000000002900000004  srbe-lsp        10.0.2.2                   UP 0x000000002900000005  srbe-lsp        10.0.3.3                   UP 0x000000002900000006  srbe-lsp        10.0.4.4                   UP 0x000000002900000007  srbe-lsp        10.0.5.5                   UP 0x000000002900000008  srbe-lsp        10.0.6.6                   UP
```

```cli
[PE4]display tunnel-info all
```

```cli
Tunnel ID               Type             Destination              Status ---------------------------------------------------------------------------------------- 0x000000000300000001  sr-te            10.0.1.1                   UP 0x000000002900000003  srbe-lsp        10.0.1.1                   UP 0x000000002900000004  srbe-lsp        10.0.2.2                   UP 0x000000002900000005  srbe-lsp        10.0.4.4                   UP 0x000000002900000007  srbe-lsp        10.0.5.5                   UP

0x000000002900000008  srbe-lsp        10.0.6.6                   UP PE1、PE4 上隧道状态正常。
```

```cli
#PE1、PE4 上检查Tunnel 隧道的连通性。

[PE1]ping lsp segment-routing te Tunnel 10
```

```cli
LSP PING FEC: SEGMENT ROUTING TE TUNNEL IPV4 SESSION QUERY Tunnel10 : 100  data bytes, press CTRL_C to break Reply from 10.0.4.4: bytes=100 Sequence=1 time=8 ms Reply from 10.0.4.4: bytes=100 Sequence=2 time=3 ms Reply from 10.0.4.4: bytes=100 Sequence=3 time=3 ms Reply from 10.0.4.4: bytes=100 Sequence=4 time=2 ms Reply from 10.0.4.4: bytes=100 Sequence=5 time=3 ms

--- FEC: SEGMENT ROUTING TE TUNNEL IPV4 SESSION QUERY Tunnel10 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 2/3/8 ms
```

```cli
[PE4]ping lsp segment-routing te Tunnel 10
```

```cli
LSP PING FEC: SEGMENT ROUTING TE TUNNEL IPV4 SESSION QUERY Tunnel10 : 100  data bytes, press CTRL_C to break Reply from 10.0.1.1: bytes=100 Sequence=1 time=8 ms Reply from 10.0.1.1: bytes=100 Sequence=2 time=3 ms Reply from 10.0.1.1: bytes=100 Sequence=3 time=3 ms Reply from 10.0.1.1: bytes=100 Sequence=4 time=3 ms Reply from 10.0.1.1: bytes=100 Sequence=5 time=3 ms

--- FEC: SEGMENT ROUTING TE TUNNEL IPV4 SESSION QUERY Tunnel10 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 3/4/8 ms TE 隧道连通性都正常。

步骤 6 配置L3VPN 在PE1、PE4 上均创建VPN-Instance vpna，创建Loopback1 接口并将其划分到VPN 实例中，在 PE1、PE4 与P1、P2 之间建立MP-BGP EVPN 对等体关系（AS 号采用65100），其中P1、P2 为 RR，PE1、PE4 为RR 客户端，通过P1、P2 实现VPNv4 路由的传递。
```

```cli
#创建VPN-Instance vpna。

[PE1]ip vpn-instance vpna

[PE1-vpn-instance-vpna] ipv4-family

[PE1-vpn-instance-vpna-af-ipv4] route-distinguisher 100:10

[PE1-vpn-instance-vpna-af-ipv4] vpn-target 100:1020 both

[PE1-vpn-instance-vpna-af-ipv4] quit

[PE4]ip vpn-instance vpna

[PE4-vpn-instance-vpna] ipv4-family

[PE4-vpn-instance-vpna-af-ipv4] route-distinguisher 100:40

[PE4-vpn-instance-vpna-af-ipv4] vpn-target 100:1020 both

[PE4-vpn-instance-vpna-af-ipv4] quit

#创建Loopback1 接口，关联VPN-Instance，并配置接口IP 地址。

[PE1]interface LoopBack 1

[PE1-LoopBack1]ip binding vpn-instance vpna

Info: All IPv4 and IPv6 related configurations on this interface are removed.

[PE1-LoopBack1]ip address 10.1.1.1 32

[PE4]interface LoopBack 1

[PE4-LoopBack1]ip binding vpn-instance vpna

Info: All IPv4 and IPv6 related configurations on this interface are removed.

[PE4-LoopBack1]ip address 10.1.4.4 32
```

注意先关联接口到VPN-Instance，再配置接口IP 地址。

```cli
#配置MP-BGP VPNv4 对等体关系，采用Loopback0 接口建立邻居关系、作为Router ID。

[PE1]bgp 65100

[PE1-bgp] router-id 10.0.1.1

[PE1-bgp] peer 10.0.5.5 as-number 65100

[PE1-bgp] peer 10.0.5.5 connect-interface LoopBack0

[PE1-bgp] peer 10.0.6.6 as-number 65100

[PE1-bgp] peer 10.0.6.6 connect-interface LoopBack0

[PE1-bgp] ipv4-family vpnv4

[PE1-bgp-af-vpnv4] peer 10.0.5.5 enable

[PE1-bgp-af-vpnv4] peer 10.0.6.6 enable

[PE2]bgp 65100

[PE2-bgp] router-id 10.0.2.2

[PE2-bgp] peer 10.0.5.5 as-number 65100

[PE2-bgp] peer 10.0.5.5 connect-interface LoopBack0

[PE2-bgp] peer 10.0.6.6 as-number 65100

[PE2-bgp] peer 10.0.6.6 connect-interface LoopBack0

[PE2-bgp] ipv4-family vpnv4

[PE2-bgp-af-vpnv4] peer 10.0.5.5 enable

[PE2-bgp-af-vpnv4] peer 10.0.6.6 enable

[PE3-bgp] router-id 10.0.3.3

[PE3-bgp] peer 10.0.5.5 as-number 65100

[PE3-bgp] peer 10.0.5.5 connect-interface LoopBack0

[PE3-bgp] peer 10.0.6.6 as-number 65100

[PE3-bgp] peer 10.0.6.6 connect-interface LoopBack0

[PE3-bgp] ipv4-family vpnv4

[PE3-bgp-af-vpnv4] peer 10.0.5.5 enable

[PE3-bgp-af-vpnv4] peer 10.0.6.6 enable

[PE4]bgp 65100

[PE4-bgp] router-id 10.0.4.4

[PE4-bgp] peer 10.0.5.5 as-number 65100

[PE4-bgp] peer 10.0.5.5 connect-interface LoopBack0

[PE4-bgp] peer 10.0.6.6 as-number 65100

[PE4-bgp] peer 10.0.6.6 connect-interface LoopBack0

[PE4-bgp] ipv4-family vpnv4

[PE4-bgp-af-vpnv4] peer 10.0.5.5 enable

[PE4-bgp-af-vpnv4] peer 10.0.6.6 enable

[P1]bgp 65100

[P1-bgp] router-id 10.0.5.5

[P1-bgp] peer 10.0.1.1 as-number 65100

[P1-bgp] peer 10.0.1.1 connect-interface LoopBack0

[P1-bgp] peer 10.0.2.2 as-number 65100

[P1-bgp] peer 10.0.2.2 connect-interface LoopBack0

[P1-bgp] peer 10.0.3.3 as-number 65100

[P1-bgp] peer 10.0.3.3 connect-interface LoopBack0

[P1-bgp] peer 10.0.4.4 as-number 65100

[P1-bgp] peer 10.0.4.4 connect-interface LoopBack0

[P1-bgp] ipv4-family vpnv4

[P1-bgp-af-vpnv4] undo policy vpn-target

[P1-bgp-af-vpnv4] peer 10.0.1.1 enable

[P1-bgp-af-vpnv4] peer 10.0.1.1 reflect-client

[P1-bgp-af-vpnv4] peer 10.0.2.2 enable

[P1-bgp-af-vpnv4] peer 10.0.2.2 reflect-client

[P1-bgp-af-vpnv4] peer 10.0.3.3 enable

[P1-bgp-af-vpnv4] peer 10.0.3.3 reflect-client

[P1-bgp-af-vpnv4] peer 10.0.4.4 enable

[P1-bgp-af-vpnv4] peer 10.0.4.4 reflect-client

#配置RR 时注意关闭对VPNv4 路由的RT 值检查。

[P2]bgp 65100

[P2-bgp] router-id 10.0.6.6

[P2-bgp] peer 10.0.1.1 as-number 65100

[P2-bgp] peer 10.0.1.1 connect-interface LoopBack0

[P2-bgp] peer 10.0.2.2 as-number 65100

[P2-bgp] peer 10.0.2.2 connect-interface LoopBack0

[P2-bgp] peer 10.0.3.3 as-number 65100

[P2-bgp] peer 10.0.3.3 connect-interface LoopBack0

[P2-bgp] peer 10.0.4.4 as-number 65100

[P2-bgp] peer 10.0.4.4 connect-interface LoopBack0

[P2-bgp] ipv4-family vpnv4

[P2-bgp-af-vpnv4] undo policy vpn-target

[P2-bgp-af-vpnv4] peer 10.0.1.1 enable

[P2-bgp-af-vpnv4] peer 10.0.1.1 reflect-client

[P2-bgp-af-vpnv4] peer 10.0.2.2 enable

[P2-bgp-af-vpnv4] peer 10.0.2.2 reflect-client

[P2-bgp-af-vpnv4] peer 10.0.3.3 enable

[P2-bgp-af-vpnv4] peer 10.0.3.3 reflect-client

[P2-bgp-af-vpnv4] peer 10.0.4.4 enable

[P2-bgp-af-vpnv4] peer 10.0.4.4 reflect-client

#在P1、P2 检查VPNv4 邻居关系状态。

[P1]display bgp vpnv4 all peer

BGP local router ID : 10.0.5.5
```

```cli
Local AS number : 65100 Total number of peers : 4                 Peers in established state : 4

Peer               V          AS  MsgRcvd  MsgSent OutQ Up/Down  State          PrefRcv 10.0.1.1            4       65100        6        6     0     00:02:07    Established        0 10.0.2.2            4       65100        6        6     0     00:02:05    Established        0 10.0.3.3            4       65100        6        6     0     00:02:06    Established        0 10.0.4.4            4       65100        6        6     0     00:02:04    Established        0
```

```cli
[P2]display bgp vpnv4 all peer

BGP local router ID : 10.0.6.6
```

```cli
Local AS number : 65100 Total number of peers : 4                 Peers in established state : 4

Peer               V          AS  MsgRcvd  MsgSent OutQ Up/Down  State          PrefRcv 10.0.1.1            4       65100        6        6     0     00:02:07    Established        0 10.0.2.2            4       65100        6        6     0     00:02:05    Established        0 10.0.3.3            4       65100        6        6     0     00:02:06    Established        0 10.0.4.4            4       65100        6        6     0     00:02:04    Established        0
```

```cli
#将Loopback1 接口的直连路由引入到BGP 中，使得PE2、PE4 能够学习到对端PE 的
```

```cli
Loopback1 接口地址的路由。
```

```cli
[PE1] bgp 65100

[PE1-bgp] ipv4-family vpn-instance vpna

[PE1-bgp-vpna] import-route direct

[PE4] bgp 65100

[PE4-bgp] ipv4-family vpn-instance vpna

[PE4-bgp-vpna] import-route direct

#在PE1 上检查VPNv4 路由。

[PE1]display bgp vpnv4 all routing-table | include 10.1.4.4

BGP Local router ID is 10.0.1.1
```

```cli
Status codes: * - valid, > - best, d - damped, x - best external, a - add path, h - history, i - internal, s - suppressed, S - Stale Origin : i - IGP, e - EGP, ? - incomplete RPKI validation codes: V - valid, I - invalid, N - not-found

Total number of routes from all PE: 4
```

Route Distinguisher: 100:10

Network       NextHop          MED        LocPrf    PrefVal Path/Ogn

Route Distinguisher: 100:40

Network       NextHop           MED        LocPrf    PrefVal Path/Ogn *>i     10.1.4.4/32      10.0.4.4              0          100        0       ?

```cli
VPN-Instance vpna, Router ID 10.0.1.1:

Total Number of Routes: 4 Network        NextHop          MED        LocPrf    PrefVal Path/Ogn *>i     10.1.4.4/32       10.0.4.4               0         100        0       ? PE1 已经通过MP-BGP 学习到了来自PE4 的VPNv4 路由。
```

```cli
#查看PE1、PE4 的VPN 实例路由表。

[PE1]display ip routing-table vpn-instance vpna
```

Route Flags: R - relay, D - download to fib, T - to vpn-instance, B - black hole route

```cli
------------------------------------------------------------------------------ Routing Table: vpna Destinations : 4        Routes : 4
```

Destination/Mask    Proto   Pre  Cost        Flags NextHop       Interface

10.1.1.1/32    Direct  0    0             D   127.0.0.1       LoopBack1 10.1.4.4/32    IBGP    255  0             RD  10.0.4.4        GigabitEthernet0/5/0 IBGP    255  0             RD  10.0.4.4        GigabitEthernet0/5/1

127.0.0.0/8     Direct  0    0             D   127.0.0.1       InLoopBack0 255.255.255.255/32  Direct  0    0             D   127.0.0.1       InLoopBack0

```cli
[PE4]display ip routing-table vpn-instance vpna
```

Route Flags: R - relay, D - download to fib, T - to vpn-instance, B - black hole route

```cli
------------------------------------------------------------------------------ Routing Table: vpna Destinations : 4        Routes : 4
```

Destination/Mask    Proto   Pre  Cost        Flags NextHop         Interface

10.1.1.1/32    IBGP    255  0             RD  10.0.1.1        GigabitEthernet0/5/0 IBGP    255  0             RD  10.0.1.1        GigabitEthernet0/5/1 10.1.4.4/32    Direct  0    0             D   127.0.0.1       LoopBack1 127.0.0.0/8     Direct  0    0             D   127.0.0.1       InLoopBack0 255.255.255.255/32  Direct  0    0             D   127.0.0.1       InLoopBack0 已学习到对端发送的路由。 步骤 7 配置隧道选择策略 配置隧道选择策略，优选SR-MPLS TE，并在VPN-Instance 中关联该隧道策略。

```cli
#配置隧道选择策略。

[PE1] tunnel-policy p1

[PE1-tunnel-policy-p1] tunnel select-seq sr-te load-balance-number 1

[PE1-tunnel-policy-p1] quit

[PE4] tunnel-policy p1

[PE4-tunnel-policy-p1] tunnel select-seq sr-te load-balance-number 1

[PE4-tunnel-policy-p1] quit

#在VPN-Instance 中调用隧道策略。

[PE1] ip vpn-instance vpna

[PE1-vpn-instance-vpna] ipv4-family

[PE1-vpn-instance-vpna-af-ipv4] tnl-policy p1

[PE4] ip vpn-instance vpna

[PE4-vpn-instance-vpna] ipv4-family

[PE4-vpn-instance-vpna-af-ipv4] tnl-policy p1

#查看PE1、PE4 的VPN 实例路由表。

[PE1]display ip routing-table vpn-instance vpna
```

Route Flags: R - relay, D - download to fib, T - to vpn-instance, B - black hole route

```cli
------------------------------------------------------------------------------ Routing Table: vpna Destinations : 4        Routes : 4
```

Destination/Mask    Proto   Pre  Cost        Flags NextHop         Interface

10.1.1.1/32    Direct  0    0             D   127.0.0.1       LoopBack1 10.1.4.4/32    IBGP    255  0             RD  10.0.4.4        Tunnel10 127.0.0.0/8     Direct  0    0             D   127.0.0.1       InLoopBack0 255.255.255.255/32  Direct  0    0             D   127.0.0.1       InLoopBack0

```cli
[PE4]display ip routing-table vpn-instance vpna
```

Route Flags: R - relay, D - download to fib, T - to vpn-instance, B - black hole route

```cli
------------------------------------------------------------------------------ Routing Table: vpna Destinations : 4        Routes : 4
```

Destination/Mask    Proto   Pre  Cost        Flags NextHop         Interface

10.1.1.1/32    IBGP    255  0             RD  10.0.1.1        Tunnel10 10.1.4.4/32    Direct  0    0             D   127.0.0.1       LoopBack1 127.0.0.0/8     Direct  0    0             D   127.0.0.1       InLoopBack0 255.255.255.255/32  Direct  0    0             D   127.0.0.1       InLoopBack0 PE1、PE4 上去往对端CE 下属网段的路由已经迭代到SR-MPLS TE 隧道。

```cli
#最后验证连通性。

[PE1]ping -vpn-instance vpna -a 10.1.1.1 10.1.4.4

PING 10.1.4.4: 56  data bytes, press CTRL_C to break Reply from 10.1.4.4: bytes=56 Sequence=1 ttl=251 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=2 ttl=251 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=3 ttl=251 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=4 ttl=251 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=5 ttl=251 time=1 ms

--- 10.1.4.4 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 1/1/1 ms 可以正常通信。
```

## 8.2.3 思考题

```cli
#在SR-MPLS TE 场景中如何强制报文经由某个设备的某个接口转发？
```
