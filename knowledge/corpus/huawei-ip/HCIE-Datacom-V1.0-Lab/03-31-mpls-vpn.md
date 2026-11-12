---
doc_id: "hcie-datacom-v1.0-lab-03"
title: "3.1 MPLS VPN"
book: "HCIE-Datacom-V1.0-Lab"
book_title: "HCIE-Datacom V1.0 实验手册"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "lab"
source_pdf: "HCIE-Datacom V1.0 实验手册.pdf"
seq: 3
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 3.1 MPLS VPN

## 3.1.1 实验介绍

3.1.1.1 学习目标

- 实现MPLS 配置
- 实现MPLS LDP 配置
- 实现MPLS VPN 配置
- 实现采用不同的方式完成CE-PE 间的路由交换
- 实现通过RT 值控制CE 间的路由学习

3.1.1.2 实验组网介绍

图3-1 MPLS VPN 实验拓扑 设备连接方式、IP 地址规划如图所示，接口互联地址均为10.0.0.Y/30，其中Y 值已在图中标 注。所有设备均创建Loopback0 接口，Loopback 接口IP 地址为10.0.X.X，其中X 值会在对应配 置步骤中使用表格标明。 在本实验中我们会通过控制RT 值来实现控制HQ 与分支之间的路由学习。

## 3.1.2 实验任务

3.1.2.1 配置思路

1. 设备基础IP 地址配置。
2. 配置AS 65100 域内的IS-IS，在互联接口、Loopback0 接口上开启IS-IS，实现域内IGP 互 通。
3. 配置AS 65100 域内的MPLS，全局使能MPLS，配置MPLS LSR ID，在互联接口使能 MPLS、MPLS LDP。
4. 在P1 上创建VPN 实例，完成P1、P2 之间的EBGP 对等体配置。
5. 在PE4 上创建VPN 实例，完成PE4、PE3 之间的EBGP 对等体配置。
6. 在PE2 上创建VPN 实例，完成PE2、PE1 之间的OSPF 配置。

3.1.2.2 配置步骤

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

#配置PE4 的互联接口、Loopback0 接口IP 地址。

[PE4]interface LoopBack0

[PE4-LoopBack0] ip address 10.0.4.4 32

[PE4-LoopBack0] quit

[PE4]interface GigabitEthernet0/5/0

[PE4-GigabitEthernet0/5/0] ip address 10.0.0.26 30

[PE4-GigabitEthernet0/5/0] quit

[PE4]interface GigabitEthernet0/5/1

[PE4-GigabitEthernet0/5/1] ip address 10.0.0.22 255.255.255.252

[PE4-GigabitEthernet0/5/1] quit

#配置P1 的互联接口、Loopback0 接口IP 地址。

[P1]interface LoopBack0

[P1-LoopBack0] ip address 10.0.5.5 32

[P1-LoopBack0] quit

[P1]interface GigabitEthernet0/5/0

[P1-GigabitEthernet0/5/0] ip address 10.0.0.13 30

[P1-GigabitEthernet0/5/0] quit

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

[P2-GigabitEthernet0/5/2] ip address 10.0.0.21 255.255.255.252
```

步骤 2 配置IS-IS 配置AS 65100 内的IS-IS，IS-IS 区域为49.0001，进程号使用1，所有设备均为L2，NET 配置 为：49.0001.000X.000X.000X.00，其中X 值见步骤1 表格，在Loopback0 接口以及互联接口上 开启IS-IS，配置接口的网络类型模拟为P2P 类型（该配置非强制要求）。

需要注意此时要配置cost-style 为wide，用于支持IS-IS 扩展特性。

```cli
#配置PE2 的IS-IS。

[PE2]isis 1

[PE2-isis-1] is-level level-2

[PE2-isis-1] cost-style wide

[PE2-isis-1] network-entity 49.0001.0002.0002.0002.00

[PE2-isis-1] is-name PE2

[PE2-isis-1]interface LoopBack0

[PE2-LoopBack0] isis enable 1

[PE2-LoopBack0] quit

[PE2]interface GigabitEthernet0/5/1

[PE2-GigabitEthernet0/5/1] isis enable 1

[PE2-GigabitEthernet0/5/1] isis circuit-type p2p

[PE2-GigabitEthernet0/5/1] quit

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

[PE4]interface GigabitEthernet0/5/1

[PE4-GigabitEthernet0/5/1] isis enable 1

[PE4-GigabitEthernet0/5/1] isis circuit-type p2p

[PE4-GigabitEthernet0/5/1] quit

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

[P2]interface GigabitEthernet0/5/1

[P2-GigabitEthernet0/5/1] isis enable 1

[P2-GigabitEthernet0/5/1] isis circuit-type p2p

[P2-GigabitEthernet0/5/1] quit

[P2]interface GigabitEthernet0/5/2

[P2-GigabitEthernet0/5/2] isis enable 1

[P2-GigabitEthernet0/5/2] isis circuit-type p2p

[P2-GigabitEthernet0/5/2] quit

#在P2 检查IS-IS 邻居关系。

[P2]display isis peer

Peer information for ISIS(1)
```

System Id     Interface          Circuit Id        State HoldTime Type     PRI -------------------------------------------------------------------------------- PE2             GE0/5/1          0000000007       Up   25s      L2       -- PE4             GE0/5/2          0000000007       Up   30s      L2       --

```cli
Total Peer(s): 2
```

邻居状态正常。

```cli
#在P2 检查IS-IS 路由。

[P2]display isis route

Route information for ISIS(1)

-----------------------------

ISIS(1) Level-2 Forwarding Table --------------------------------

IPV4 Destination   IntCost    ExtCost ExitInterface     NextHop         Flags ------------------------------------------------------------------------------- 10.0.0.8/30        10         NULL   GE0/5/1           Direct          D/-/L/- 10.0.0.20/30      10         NULL   GE0/5/2           Direct          D/-/L/- 10.0.2.2/32        10         NULL   GE0/5/1           10.0.0.9         A/-/-/- 10.0.4.4/32        10         NULL   GE0/5/2           10.0.0.22       A/-/-/- 10.0.6.6/32        0          NULL   Loop0             Direct          D/-/L/- Flags: D-Direct, A-Added to URT, L-Advertised in LSPs, S-IGP Shortcut, U-Up/Down Bit Set, LP-Local Prefix-Sid Protect Type: L-Link Protect, N-Node Protect 已完成路由学习。 步骤 3 配置MPLS 在所有设备上开启MPLS，配置MPLS LSR ID（使用Loopback0 接口IP），在互联接口上开启 MPLS 和MPLS LDP。

#配置MPLS LSR ID，全局使能MPLS。

[PE2]mpls lsr-id 10.0.2.2

[PE2]mpls

[PE2]mpls ldp

[PE4]mpls lsr-id 10.0.4.4

[PE4]mpls

[PE4]mpls ldp

[P2]mpls lsr-id 10.0.6.6

[P2]mpls

[P2]mpls ldp

#在互联接口开启MPLS、MPLS LDP。

[P2]interface GigabitEthernet0/5/1

[P2-GigabitEthernet0/5/1] mpls

[P2-GigabitEthernet0/5/1] mpls ldp

[P2]interface GigabitEthernet0/5/2

[P2-GigabitEthernet0/5/2] mpls

[P2-GigabitEthernet0/5/2] mpls ldp

[P2-GigabitEthernet0/5/2] quit

[PE2]interface GigabitEthernet0/5/1

[PE2-GigabitEthernet0/5/1] mpls

[PE2-GigabitEthernet0/5/1] mpls ldp

[PE4]interface GigabitEthernet0/5/1

[PE4-GigabitEthernet0/5/1] mpls

[PE4-GigabitEthernet0/5/1] mpls ldp

#在P2 检查MPLS LDP 会话状态。

[P2]display mpls ldp adjacency all
```

```cli
LDP Adjacency Information Codes: R: Remote Adjacency, L: Local Adjacency An asterisk (*) before an adjacency means the adjacency is being deleted. ------------------------------------------------------------------------------- SN   SourceAddr      PeerID       VrfID AdjAge(DDDD:HH:MM) RcvdHello Type -------------------------------------------------------------------------------

1    10.0.0.9         10.0.2.2        0     0000:00:01             17        L

2    10.0.0.22       10.0.4.4        0     0000:00:00             13        L

------------------------------------------------------------------------------- TOTAL: 2 Record(s) Found.

步骤 4 L3VPN 配置 完成AS 65100 内的MP-BGP 对等体配置，使用Loopback0 接口地址作为Router ID 以及建立
```

```cli
BGP 对等体的连接源地址，其中P2 配置为RR，通过P2 实现VPNv4 路由的传递。

#PE2 配置。

[PE2]bgp 65100

[PE2-bgp] router-id 10.0.2.2

[PE2-bgp] peer 10.0.6.6 as-number 65100

[PE2-bgp] peer 10.0.6.6 connect-interface LoopBack0

[PE2-bgp] ipv4-family vpnv4

[PE2-bgp-af-vpnv4] peer 10.0.6.6 enable

[PE4]bgp 65100

[PE4-bgp] router-id 10.0.4.4

[PE4-bgp] peer 10.0.6.6 as-number 65100

[PE4-bgp] peer 10.0.6.6 connect-interface LoopBack0

[PE4-bgp] ipv4-family vpnv4

[PE4-bgp-af-vpnv4] peer 10.0.6.6 enable

[P2]bgp 65100

[P2-bgp] router-id 10.0.6.6

[P2-bgp] peer 10.0.2.2 as-number 65100

[P2-bgp] peer 10.0.2.2 connect-interface LoopBack0

[P2-bgp] peer 10.0.4.4 as-number 65100

[P2-bgp] peer 10.0.4.4 connect-interface LoopBack0

[P2-bgp] ipv4-family vpnv4

[P2-bgp-af-vpnv4] undo policy vpn-target

[P2-bgp-af-vpnv4] peer 10.0.2.2 enable

[P2-bgp-af-vpnv4] peer 10.0.2.2 reflect-client

[P2-bgp-af-vpnv4] peer 10.0.4.4 enable

[P2-bgp-af-vpnv4] peer 10.0.4.4 reflect-client

#配置RR 时注意关闭对VPNv4 路由的RT 值检查。

#在P2 检查VPNv4 对等体状态。

[P2]display bgp vpnv4 all peer

BGP local router ID : 10.0.6.6
```

```cli
Local AS number : 65100 Total number of peers : 2                 Peers in established state : 2

Peer               V          AS  MsgRcvd  MsgSent OutQ Up/Down  State          PrefRcv 10.0.2.2            4       65100        6        6     0     00:02:05    Established        0 10.0.4.4            4       65100        6        6     0     00:02:04    Established        0

步骤 5 完成HQ 的CE-PE 间配置 从此步骤开始，我们将会配置CE-PE 之间的路由协议，并通过配置IRT、ERT 达成如下效果： 1. 来自Branch1、2 的路由可被HQ 正常学习。 2. Branch 之间相互学习到的对端路由下一跳为HQ。 3. Branch 之间互访需通过HQ 实现。 为满足该需求，我们需要在P1、P2 之间划分两个VPN 实例，分别用于接收、发送路由，因此 除了物理接口之外，还需要创建一个子接口。
```

```cli
#配置P1、P2 之间的子接口。

[P1]interface GigabitEthernet0/5/0.1

[P1-GigabitEthernet0/5/0.1] vlan-type dot1q 10

[P1-GigabitEthernet0/5/0.1] ip address 10.0.0.113 255.255.255.252

[P1-GigabitEthernet0/5/0.1] quit

[P2]interface GigabitEthernet0/5/0.1

[P2-GigabitEthernet0/5/0.1] vlan-type dot1q 10

[P2-GigabitEthernet0/5/0.1] ip address 10.0.0.114 255.255.255.252

[P2-GigabitEthernet0/5/0.1] quit

#测试子接口连通性。

[P2]ping 10.0.0.113

PING 10.0.0.113: 56  data bytes, press CTRL_C to break Reply from 10.0.0.113: bytes=56 Sequence=1 ttl=255 time=1 ms Reply from 10.0.0.113: bytes=56 Sequence=2 ttl=255 time=1 ms Reply from 10.0.0.113: bytes=56 Sequence=3 ttl=255 time=1 ms Reply from 10.0.0.113: bytes=56 Sequence=4 ttl=255 time=1 ms Reply from 10.0.0.113: bytes=56 Sequence=5 ttl=255 time=1 ms

--- 10.0.0.113 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 1/1/1 ms

#完成P1 的BGP 配置，使用Loopback0 接口作为Router ID，使用直连接口建立EBGP 对等体关
```

```cli
系。
```

```cli
[P1]bgp 65003

[P1-bgp] router-id 10.0.5.5

[P1-bgp] peer 10.0.0.14 as-number 65100

[P1-bgp] peer 10.0.0.114 as-number 65100

#在P2 上创建VPN 实例：vpna_in、vpna_out，分别用于接受路由以及发送路由。
```

```cli
整个网络中充当MPLS VPN PE 功能的设备，按照如下规划配置VPN 实例。 VPN 实例规划 设备编号 VPN实例 RD IRT ERT P2 vpna_in 10:60 10:46、10:26 - P2 vpna_out 10:6060 - 10:624 PE2 vpna 10:20 10:624 10:26 PE4 vpna 10:40 10:624 10:46
```

```cli
[P2]ip vpn-instance vpna_in

[P2-vpn-instance-vpna_in] ipv4-family

[P2-vpn-instance-vpna_in-af-ipv4] route-distinguisher 10:60

[P2-vpn-instance-vpna_in-af-ipv4] vpn-target 10:46 import-extcommunity

[P2-vpn-instance-vpna_in-af-ipv4] vpn-target 10:26 import-extcommunity

[P2-vpn-instance-vpna_in-af-ipv4] quit

[P2-vpn-instance-vpna_in] quit

[P2]ip vpn-instance vpna_out

[P2-vpn-instance-vpna_out] ipv4-family

[P2-vpn-instance-vpna_out-af-ipv4] route-distinguisher 10:6060

[P2-vpn-instance-vpna_out-af-ipv4] vpn-target 10:624 export-extcommunity

[P2-vpn-instance-vpna_out-af-ipv4] quit

[P2-vpn-instance-vpna_out] quit

#完成VPN-Instance 的配置后，需要将对应接口划分到对应的VPN-Instance 中。

[P2]interface GigabitEthernet0/5/0

[P2-GigabitEthernet0/5/0] ip binding vpn-instance vpna_out

[P2-GigabitEthernet0/5/0] ip address 10.0.0.14 255.255.255.252

[P2-GigabitEthernet0/5/0] quit

[P2]interface GigabitEthernet0/5/0.1

[P2-GigabitEthernet0/5/0.1] vlan-type dot1q 10

[P2-GigabitEthernet0/5/0.1] ip binding vpn-instance vpna_in

[P2-GigabitEthernet0/5/0.1] ip address 10.0.0.114 255.255.255.252
```

请注意重新配置接口的IP 地址。

```cli
#完成P2 的EBGP 配置。

[P2]bgp 65100

[P2-bgp] ipv4-family vpn-instance vpna_in

[P2-bgp-vpna_in] peer 10.0.0.113 as-number 65003

[P2-bgp-vpna_in] peer 10.0.0.113 substitute-as

[P2-bgp-vpna_in] ipv4-family vpn-instance vpna_out

[P2-bgp-vpna_out] peer 10.0.0.13 as-number 65003

[P2-bgp-vpna_out] peer 10.0.0.13 allow-as-loop 2
```

Vpna_in 这个VPN 实例中接收的BGP VPNv4 路由在AS_Path 属性中会携带AS 65003，P1 会因 为防环机制丢弃路由，为此需要配置substitute-as 参数，将AS 替换。 Vpna_in 中学习到的分支路由，会经由HQ 的CE（P1）再以BGP 路由的形式传递到Vpna_out 实例中，但P2 因存在自身AS，不会学习该路由，为此需配置allow-as-loop 参数。

```cli
#在P1 查看BGP 对等体状态。

[P1]display bgp peer

BGP local router ID : 10.0.5.5
```

```cli
Local AS number : 65003 Total number of peers : 2                 Peers in established state : 2

Peer                     V        AS    MsgRcvd  MsgSent   OutQ Up/Down      State       PrefRcv 10.0.0.14                4       65100     1258     1263     0 18:13:13      Established        1 10.0.0.114               4       65100     1290     1298     0 18:38:11      Established        1 已正常建立。
```

```cli
#在P1 上创建Loopback1，模拟业务网段。

[P1]interface LoopBack1

[P1-LoopBack1] ip address 10.1.5.5 32

#配置其IP 地址为10.1.5.5/32。

#在P1 的BGP 中宣告该路由。

[P1] bgp 65003

[P1-bgp] network 10.1.5.5 255.255.255.255
```

步骤 6 完成Branch2 的CE-PE 间配置 按照规划完成PE4 上的VPN-Instance 配置，将接口划分到对应的VPN-Instance 中，完成PE4、 PE3 间的EBGP 配置，在PE3 上创建Loopback1 接口模拟业务，并引入到BGP 中。

```cli
#在PE4 上创建VPN-Instance。

[PE4]ip vpn-instance vpna

[PE4-vpn-instance-vpna] ipv4-family

[PE4-vpn-instance-vpna-af-ipv4] route-distinguisher 10:40

[PE4-vpn-instance-vpna-af-ipv4] vpn-target 10:46 export-extcommunity

[PE4-vpn-instance-vpna-af-ipv4] vpn-target 10:624 import-extcommunity

[PE4-vpn-instance-vpna-af-ipv4] quit

[PE4-vpn-instance-vpna] quit

#将连接CE 角色的接口划分到VPN-Instance 中。

[PE4]interface GigabitEthernet0/5/0

[PE4-GigabitEthernet0/5/0] ip binding vpn-instance vpna

[PE4-GigabitEthernet0/5/0] ip address 10.0.0.26 255.255.255.252

#完成PE4 的EBGP 配置，使用直连接口建立BGP 对等体关系。

[PE4]bgp 65100

[PE4-bgp] ipv4-family vpn-instance vpna

[PE4-bgp-vpna] peer 10.0.0.25 as-number 65003

[PE4-bgp-vpna] peer 10.0.0.25 substitute-as
```

```cli
注意配置substitute-as 参数。
```

```cli
#完成PE3 的EBGP 配置，使用Loopback0 接口IP 地址作为Router ID。

[PE3]bgp 65003

[PE3-bgp] router-id 10.0.3.3

[PE3-bgp] peer 10.0.0.26 as-number 65100

#在PE4 查看EBGP 对等体关系状态。

[PE4]display bgp vpnv4 vpn-instance vpna peer

BGP local router ID : 10.0.4.4
```

```cli
Local AS number : 65100

VPN-Instance vpna, Router ID 10.0.4.4: Total number of peers : 1                 Peers in established state : 1

Peer                     V        S  MsgRcvd  MsgSent   OutQ Up/Down      State       PrefRcv 10.0.0.25                4       65003     1290     1298     0 18:42:33      Established        1 已正常建立。
```

```cli
#在PE3 上创建Loopback1 接口，宣告到BGP 中。

[PE3]interface LoopBack1

[PE3-LoopBack1] ip address 10.1.3.3 32

[PE3-LoopBack1] quit

[PE3]bgp 65003

[PE3-bgp] network 10.1.3.3 255.255.255.255
```

步骤 7 完成Branch1 的CE-PE 间配置 按照规划完成PE2 上的VPN-Instance 配置，将接口划分到对应的VPN-Instance 中，完成PE2、 PE1 间的OSPF 配置，在PE1 上创建Loopback1 接口模拟业务，并引入到OSPF 中。

```cli
#在PE2 创建VPN-Instance。

[PE2]ip vpn-instance vpna

[PE2-vpn-instance-vpna] ipv4-family

[PE2-vpn-instance-vpna-af-ipv4] route-distinguisher 10:20

[PE2-vpn-instance-vpna-af-ipv4] apply-label per-instance

[PE2-vpn-instance-vpna-af-ipv4] vpn-target 10:26 export-extcommunity

[PE2-vpn-instance-vpna-af-ipv4] vpn-target 10:624 import-extcommunity

#将PE2 接口划分到VPN-Instance 中。

[PE2]interface GigabitEthernet0/5/0

[PE2-GigabitEthernet0/5/0] ip binding vpn-instance vpna

[PE2-GigabitEthernet0/5/0] ip address 10.0.0.2 255.255.255.252
```

请注意重新配置接口IP 地址。

```cli
#配置PE2 的OSPF。

[PE2]ospf 1 router-id 10.0.2.2 vpn-instance vpna

[PE2-ospf-1] import-route bgp cost 20 type 2

[PE2-ospf-1] area 0.0.0.0
```

```cli
引入BGP 路由。
```

```cli
#在互联接口开启OSPF。

[PE2]interface GigabitEthernet0/5/0

[PE2-GigabitEthernet0/5/0] ospf enable 1 area 0.0.0.0

#配置PE1 的OSPF。

[PE1]ospf 1 router-id 10.0.1.1

[PE1-ospf-1] area 0.0.0.0

#在互联接口开启OSPF。

[PE1]interface GigabitEthernet0/5/0

[PE1-GigabitEthernet0/5/0] ospf enable 1 area 0.0.0.0

#PE1 上创建Loopback1 接口，在接口上启用OSPF。

[PE1]interface LoopBack1

[PE1-LoopBack1] ip address 10.1.1.1 32

[PE1-LoopBack1] ospf enable 1 area 0.0.0.0

#在PE2 上检查OSPF 邻居状态。

[PE2]display ospf peer brief
```

```cli
(M) Indicates MADJ neighbor
```

```cli
OSPF Process 1 with Router ID 10.0.2.2

Peer Statistic Information Total number of peer(s): 1 Peer(s) in full state: 1 ----------------------------------------------------------------------------- Area Id         Interface          Neighbor id        State
```

0.0.0.0         GE0/5/0           10.0.1.1             Full

```cli
----------------------------------------------------------------------------- 邻居状态正常。

#通过IP 前缀列表以及Route-Policy 限制引入BGP 的OSPF 路由。

[PE2]ip ip-prefix Loopback1 index 10 permit 10.1.1.1 32

[PE2]route-policy O2B permit node 10

[PE2-route-policy] if-match ip-prefix Loopback1

#在BGP 的VPN 实例视图中引入OSPF 路由。

[PE2]bgp 65100

[PE2-bgp] ipv4-family vpn-instance vpna

[PE2-bgp-vpna] import-route ospf 1 route-policy O2B
```

步骤 8 路由验证 分别查看分支与总部的CE、PE 的BGP VPNv4 路由以及对应的IGP 协议、BGP 协议路由表。

```cli
#查看HQ 的PE（P2）其VPNv4 路由表。

[P2]display bgp vpnv4 vpn-instance vpna_in routing-table

BGP Local router ID is 10.0.6.6
```

```cli
Status codes: * - valid, > - best, d - damped, x - best external, a - add path, h - history, i - internal, s - suppressed, S - Stale Origin : i - IGP, e - EGP, ? - incomplete RPKI validation codes: V - valid, I - invalid, N - not-found

VPN-Instance  vpna_in, Router ID 10.0.6.6:

Total Number of Routes: 4 Network         NextHop                  MED        LocPrf    PrefVal Path/Ogn *>    10.1.5.5/32        10.0.0.113                    0                     0      65003i *>i    10.1.1.1/32        10.0.2.2                       2          100        0       ? *>i    10.1.3.3/32        10.0.4.4                       0          100        0      65003i 在VPN-Instance vpna_in 中
```

已经学习到了来自分支的路由：10.1.1.1/32、10.1.3.3/32。

```cli
[P2]display bgp vpnv4 vpn-instance vpna_out routing-table

BGP Local router ID is 10.0.6.6
```

```cli
Status codes: * - valid, > - best, d - damped, x - best external, a - add path, h - history, i - internal, s - suppressed, S - Stale Origin : i - IGP, e - EGP, ? - incomplete RPKI validation codes: V - valid, I - invalid, N - not-found

VPN-Instance vpna_out, Router ID 10.0.6.6:

Total Number of Routes: 4 Network           NextHop                 MED        LocPrf    PrefVal Path/Ogn

*>     10.1.5.5/32        10.0.0.13                0                        0      65003i *>     10.1.1.1/32        10.0.0.13                                         0      65003 65100? *>     10.1.3.3/32        10.0.0.13                                         0      65003 65100 65100i 在VPN-Instance vpna_out 中
```

已经学习到了来自HQ 的路由：10.1.1.1/32、10.1.3.3/32，并且此 时下一跳为10.0.0.13，即 P1。

```cli
#查看PE2、PE4 的BGP VPNv4 路由表。

[PE2]display bgp vpnv4 all routing-table

BGP Local router ID is 10.0.2.2
```

```cli
Status codes: * - valid, > - best, d - damped, x - best external, a - add path, h - history, i - internal, s - suppressed, S - Stale Origin : i - IGP, e - EGP, ? - incomplete RPKI validation codes: V - valid, I - invalid, N - not-found

Total number of routes from all PE: 4
```

Route Distinguisher: 10:20

Network          NextHop                    MED        LocPrf    PrefVal Path/Ogn

```cli
*>     10.1.1.1/32        0.0.0.0                        2                     0       ?
```

Route Distinguisher: 10:6060

Network          NextHop                   MED        LocPrf    PrefVal Path/Ogn

```cli
*>i    10.1.1.1/32        10.0.6.6                                  100        0      65003 65100? *>i    10.1.3.3/32        10.0.6.6                                  100        0      65003 65100 65100i *>i    10.1.5.5/32        10.0.6.6                       0          100        0      65003i

VPN-Instance  vpna, Router ID 10.0.2.2:

Total Number of Routes: 4 Network         NextHop                  MED        LocPrf    PrefVal Path/Ogn

*>    10.1.1.1/32        0.0.0.0                        2                     0       ? * i                        10.0.6.6                                  100        0      65003 65100? *>i    10.1.3.3/32        10.0.6.6                                  100        0      65003 65100 65100i *>i    10.1.5.5/32        10.0.6.6                       0          100        0      65003i PE2
```

已经学习到前往另外一个分支以及总部的业务路由，并且下一跳都为总部的PE。

```cli
[PE4]display bgp vpnv4 all routing-table

BGP Local router ID is 10.0.4.4
```

```cli
Status codes: * - valid, > - best, d - damped, x - best external, a - add path, h - history, i - internal, s - suppressed, S - Stale Origin : i - IGP, e - EGP, ? - incomplete RPKI validation codes: V - valid, I - invalid, N - not-found

Total number of routes from all PE: 4
```

Route Distinguisher: 10:40

Network        NextHop                       MED        LocPrf    PrefVal Path/Ogn

```cli
*>     10.1.3.3/32        10.0.0.25                      0                     0      65003i
```

Route Distinguisher: 10:6060

Network      NextHop                       MED        LocPrf    PrefVal Path/Ogn

```cli
*>i    10.1.1.1/32        10.0.6.6                                  100        0      65003 65100? *>i    10.1.3.3/32        10.0.6.6                                  100        0      65003 65100 65100i *>i    10.1.5.5/32        10.0.6.6                       0          100        0      65003i

VPN-Instance vpna, Router ID 10.0.4.4:

Total Number of Routes: 4 Network        NextHop                    MED        LocPrf    PrefVal Path/Ogn

*>i    10.1.1.1/32        10.0.6.6                                 100        0      65003 65100? *>    10.1.3.3/32        10.0.0.25                    0                     0      65003i * i                       10.0.6.6                                  100        0      65003 65100 65100i *>i    10.1.5.5/32       10.0.6.6                       0          100        0      65003i PE4
```

已经学习到前往另外一个分支以及总部的业务路由，并且下一跳都为总部的PE。

```cli
#查看PE1、PE3 的IGP 协议路由表。

[PE1]display ospf routing

OSPF Process 1 with Router ID 10.0.1.1
```

Routing Tables

```cli
Routing for Network Destination        Cost     Type       NextHop      AdvRouter       Area 10.0.0.0/30        1        Direct     10.0.0.1        10.0.1.1        0.0.0.0 10.1.1.1/32        0        Direct     10.1.1.1        10.0.1.1        0.0.0.0
```

Routing for ASEs Destination        Cost       Type       Tag          NextHop       AdvRouter 10.1.3.3/32        20         Type2     3489726028  10.0.0.2        10.0.2.2 10.1.5.5/32        20         Type2     3489726028  10.0.0.2        10.0.2.2

```cli
Total Nets: 4 Intra Area: 2  Inter Area: 0  ASE: 2  NSSA: 0 PE1
```

的OSPF 路由表正常学习到了前往总部以及分支的路由。

```cli
[PE3]display bgp routing-table

BGP Local router ID is 10.0.3.3
```

```cli
Status codes: * - valid, > - best, d - damped, x - best external, a - add path, h - history, i - internal, s - suppressed, S - Stale Origin : i - IGP, e - EGP, ? - incomplete RPKI validation codes: V - valid, I - invalid, N - not-found

Total Number of Routes: 3 Network        NextHop                       MED        LocPrf    PrefVal Path/Ogn

*>     10.1.1.1/32        10.0.0.26                                            0      65100 65100 65100? *>     10.1.3.3/32        0.0.0.0                        0                      0       i *>     10.1.5.5/32        10.0.0.26                                            0      65100 65100i PE3 的BGP 路由表中
```

已经学习到了前往总部以及分支的路由。

```cli
#在PE3 上测试业务连通性。

[PE3]ping -a 10.1.3.3 10.1.1.1

PING 10.1.1.1: 56  data bytes, press CTRL_C to break Reply from 10.1.1.1: bytes=56 Sequence=1 ttl=250 time=1 ms Reply from 10.1.1.1: bytes=56 Sequence=2 ttl=250 time=1 ms Reply from 10.1.1.1: bytes=56 Sequence=3 ttl=250 time=1 ms Reply from 10.1.1.1: bytes=56 Sequence=4 ttl=250 time=1 ms Reply from 10.1.1.1: bytes=56 Sequence=5 ttl=250 time=1 ms

--- 10.1.1.1 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 1/1/1 ms 可以正常进行通信，注意源地址需要为本地的业务网段地址。

#查看业务流量路径。

[PE3]tracert -a 10.1.3.3 10.1.1.1
```

```cli
traceroute to 10.1.1.1(10.1.1.1), max hops: 30, packet length: 40, press CTRL_C to break

1 10.0.0.26 27 ms  2 ms  3 ms

2 10.0.0.14 4 ms  2 ms  3 ms

3 10.0.0.13 2 ms  2 ms  2 ms

4 10.0.0.114 3 ms  3 ms  4 ms

5 10.0.0.2 6 ms  2 ms  4 ms

6 10.1.1.1 3 ms  2 ms  2 ms

可以看到流量经由总部HQ 的P1 进行了转发，这样总部若想对分支之间的互访进行限制，即 可执行相应的操作。
```

## 3.1.3 思考题

```cli
#在PE1 的OSPF 路由表中，我们可以看到Tag 值为：3489726028，请问该Tag 值如何产生？
```

4 EVPN
