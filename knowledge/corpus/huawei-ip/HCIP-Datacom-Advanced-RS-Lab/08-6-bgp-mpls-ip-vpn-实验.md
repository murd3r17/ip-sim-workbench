---
doc_id: "hcip-datacom-advanced-rs-lab-08"
title: "6 BGP/MPLS IP VPN 实验"
book: "HCIP-Datacom-Advanced-RS-Lab"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 实验手册"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "lab"
source_pdf: "HCIP-Datacom-Advanced Routing & Switching Technology V1.0 实验手册.pdf"
seq: 8
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 6 BGP/MPLS IP VPN 实验

## 6.1 BGP/MPLS IP VPN 综合实验

## 6.1.1 实验介绍

6.1.1.1 学习目标

- 实现MPLS 配置
- 实现MPLS LDP 配置
- 实现MPLS VPN 配置

6.1.1.2 实验组网介绍

图6-1 BGP/MPLS IP VPN 实验拓扑
IP 互联地址、BGP AS 号如图所示。R3 为VPN 路由反射器，R2、R4 为R3 的客户端。BGP

```cli
AS 65100 内通过IS-IS 构建底层网络。 R2、R4 是MPLS VPN 网络的PE 设备，R1、R5 为Finance VPN 的CE 设备，R1、S1、S2 为 OA VPN 的CE 设备。
```

6.1.1.3 实验背景

某企业网络有一个总部（Headquarter）与3 个分支，其中分支一（Branch1）的主要业务是财 务，分支二（Branch2）与分支三（Branch3）的主要业务是企业办公业务。 企业总部需要接收分支一、分支二、分支三的路由条目，分支一不允许接收分支二与分支三的 路由条目。 该企业骨干网规模较大，所以需要使用VPN RR 简化配置。

## 6.1.2 实验任务

6.1.2.1 任务思路

1. 设备IP 地址配置。
2. 在骨干网部署IS-IS，构建底层网络。
3. 合理规划VPN 实例的RT 与RD 值，并在PE 上将VPN 与相应接口绑定。
4. 在骨干网部署MPLS 与MPLS LDP。
5. 在骨干网创建VPNv4 IBGP 对等体。
6. 发布Finance VPN 中的路由条目。
7. 发布OA VPN 中的路由条目。

6.1.2.2 任务步骤

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
#配置R1 的GE0/0/2、Loopback0 接口IP 地址

[R1]interface LoopBack0

[R1-LoopBack0] ip address 10.0.1.1 255.255.255.255

[R1-LoopBack0] quit

[R1]interface GigabitEthernet0/0/2

[R1-GigabitEthernet0/0/2] ip address 10.0.12.1 255.255.255.0

[R1-GigabitEthernet0/0/2] quit

#配置R2 的GE0/0/1、GE0/0/2、Loopback0 接口IP 地址。GE0/0/3 与GE0/0/4 接口需要绑定
```

VPN 实例，所以暂时不配地址

```cli
[R2]interface LoopBack0

[R2-LoopBack0] ip address 10.10.10.2 255.255.255.255

[R2-LoopBack0] quit

[R2]interface GigabitEthernet0/0/1

[R2-GigabitEthernet0/0/1] ip address 10.0.24.2 255.255.255.0

[R2-GigabitEthernet0/0/1] quit

[R2]interface GigabitEthernet0/0/2

[R2-GigabitEthernet0/0/2] ip address 10.0.23.2 255.255.255.0

[R2-GigabitEthernet0/0/2] quit

#配置R3 的GE0/0/2、GE0/0/3、Loopback0 接口IP 地址

[R3]interface LoopBack0

[R3-LoopBack0] ip address 10.10.10.3 255.255.255.255

[R3-LoopBack0]quit

[R3]interface GigabitEthernet0/0/2

[R3-GigabitEthernet0/0/2] ip address 10.0.34.3 255.255.255.0

[R3-GigabitEthernet0/0/2] quit

[R3]interface GigabitEthernet0/0/3

[R3-GigabitEthernet0/0/3]ip address 10.0.23.3 255.255.255.0

[R3-GigabitEthernet0/0/3]quit

#配置R4 的GE0/0/1、GE0/0/3、Loopback0 接口IP 地址。GE0/0/2 与GE0/0/5 接口需要绑定
```

VPN 实例，所以暂时不配地址

```cli
[R4]interface LoopBack0

[R4-LoopBack0] ip address 10.10.10.4 255.255.255.255

[R4-LoopBack0] quit

[R4]interface GigabitEthernet0/0/1

[R4-GigabitEthernet0/0/1] ip address 10.0.24.4 255.255.255.0

[R4-GigabitEthernet0/0/1] quit

[R4]interface GigabitEthernet0/0/3

[R4-GigabitEthernet0/0/3] ip address 10.0.34.4 255.255.255.0

[R4-GigabitEthernet0/0/3] quit

#配置R5 的GE0/0/3、Loopback0 接口IP 地址

[R5]interface LoopBack0

[R5-LoopBack0] ip address 10.0.1.2 255.255.255.255

[R5-LoopBack0] quit

[R5]interface GigabitEthernet0/0/3

[R5-GigabitEthernet0/0/3] ip address 10.0.45.5 255.255.255.0

[R5-GigabitEthernet0/0/3] quit

#配置S1 的GE0/0/2 所属VLAN 以及VLANIF 1、Loopback0 接口IP 地址

[S1]interface LoopBack0

[S1-LoopBack0] ip address 10.0.2.1 255.255.255.255

[S1-LoopBack0] quit

[S1]interface GigabitEthernet0/0/2

[S1-GigabitEthernet0/0/2] port link-type access

[S1-GigabitEthernet0/0/2] port default vlan 1

[S1-GigabitEthernet0/0/2] quit

[S1]interface Vlanif 1

[S1-Vlanif1] ip address 10.1.21.1 24

[S1-Vlanif1] quit

#配置S2 的GE0/0/4 所属VLAN 以及VLANIF 1、Loopback0 接口IP 地址

[S2]interface LoopBack0

[S2-LoopBack0] ip address 10.0.2.2 255.255.255.255

[S2-LoopBack0] quit

[S2]interface GigabitEthernet0/0/4

[S2-GigabitEthernet0/0/4] port link-type access

[S2-GigabitEthernet0/0/4] port default vlan 1

[S2-GigabitEthernet0/0/4] quit

[S2]interface Vlanif 1

[S2-Vlanif1] ip address 10.0.42.2 24

[S2-Vlanif1] quit
```

步骤 2 骨干网部署IS-IS 协议，搭建底层网络 按照拓扑设计在R2、R3、R4 上部署IS-IS 进程，进程号使用1，所有IS-IS 路由器都是L2 路 由器，cost 类型为wide，NET 地址的区域号是49.0001，System ID 根据环回口设置，IS-IS 主 机命与设备名保持一致。

```cli
#在R2 上部署IS-IS

[R2]isis 1

[R2-isis-1] is-level level-2

[R2-isis-1] cost-style wide

[R2-isis-1] network-entity 49.0001.0100.1001.0002.00

[R2-isis-1] is-name R2

[R2-isis-1] quit

[R2]interface LoopBack0

[R2-LoopBack0] isis enable 1

[R2-LoopBack0] quit

[R2]interface GigabitEthernet0/0/1

[R2-GigabitEthernet0/0/1] isis enable 1

[R2-GigabitEthernet0/0/1] quit

[R2]interface GigabitEthernet0/0/2

[R2-GigabitEthernet0/0/2] isis enable 1

[R2-GigabitEthernet0/0/2] quit

#在R3 上部署IS-IS

[R3]isis 1

[R3-isis-1] is-level level-2

[R3-isis-1] cost-style wide

[R3-isis-1] network-entity 49.0001.0100.1001.0003.00

[R3-isis-1] is-name R3

[R3-isis-1] quit

[R3]interface LoopBack0

[R3-LoopBack0] isis enable 1

[R3-LoopBack0] quit

[R3]interface GigabitEthernet0/0/2

[R3-GigabitEthernet0/0/2] isis enable 1

[R3-GigabitEthernet0/0/2] quit

[R3]interface GigabitEthernet0/0/3

[R3-GigabitEthernet0/0/3] isis enable 1

[R3-GigabitEthernet0/0/3] quit

#在R4 上部署IS-IS

[R4]isis 1

[R4-isis-1] is-level level-2

[R4-isis-1] cost-style wide

[R4-isis-1] network-entity 49.0001.0100.1001.0004.00

[R4-isis-1] is-name R4

[R4-isis-1] quit

[R4]interface LoopBack0

[R4-LoopBack0] isis enable 1

[R4-LoopBack0] quit

[R4]interface GigabitEthernet0/0/1

[R4-GigabitEthernet0/0/1] isis enable 1

[R4-GigabitEthernet0/0/1] quit

[R4]interface GigabitEthernet0/0/3

[R4-GigabitEthernet0/0/3] isis enable 1

[R4-GigabitEthernet0/0/3] quit

#检查IS-IS 配置结果

#在R3 查看IS-IS 邻居

[R3]display isis peer

Peer information for ISIS(1)

System Id       Interface          Circuit Id    State HoldTime Type     PRI1 ------------------------------------------------------------------------------- R4*             GE0/0/2            R4.02       Up   8s       L2       64 R2*             GE0/0/3            R2.02       Up   9s       L2       64

Total Peer(s): 2

[R3]display isis interface

Interface information for ISIS(1)

---------------------------------

Interface       Id      IPV4.State          IPV6.State        MTU  Type DIS

GE0/0/2       001         Up                Up          1497 L1/L2 No/No GE0/0/3       002         Up                Up          1497 L1/L2 No/No Loop0        001         Up                Up          1500 L1/L2 --
#在路由器上检查IS-IS IPv4 路由表，以R3 路由器为例

[R3]display isis route

Route information for ISIS(1)

-----------------------------

ISIS(1) Level-2 Forwarding Table --------------------------------

IPV4 Destination     IntCost   ExtCost ExitInterface   NextHop         Flags ------------------------------------------------------------------------------- 10.0.24.0/24         20       NULL    GE0/0/2     10.0.34.4         A/-/-/- GE0/0/3     10.0.23.2 10.10.10.3/32        0        NULL    Loop0      Direct           D/-/L/- 10.10.10.2/32        10       NULL    GE0/0/3     10.0.23.2         A/-/-/- 10.0.23.0/24         10       NULL    GE0/0/3     Direct           D/-/L/- 10.0.34.0/24         10       NULL    GE0/0/2     Direct           D/-/L/- 10.10.10.4/32        10       NULL    GE0/0/2     10.0.34.4         A/-/-/-

Flags: D-Direct, A-Added to URT, L-Advertised in LSPs, S-IGP Shortcut, U-Up/DownBit Set
```

从输出信息可以看到IPv4 与IPv6 的路由已经被路由器学到。

步骤 3 配置VPN 实例，并绑定接口 VPN 实例需要规划RD 与RT 值。 RD 值可以区分重复的路由，也能用来标注路由来自哪个区域。 来自总部的路由条目RD 为65100:12 来自分支一的路由条目RD 为65100:1 来自分支二的路由条目RD 为65001:2 来自分支三的路由条目RD 为65002:2

RT 值规划需要根据业务情况：总部需要与分支一互通，总部、分支二、分支三之间需要互 通，分支一与分支二、分支三之间不能互通。 来自总部的路由条目RT 为Export：65100:12 65001:65002，Import：65100:12 65001:65002 来自分支一的路由条目RT 为Export：65100:12，Import：65100:12 来自分支二的路由条目RT 为Export：65001:65002，Import：65001:65002 来自分支三的路由条目RT 为Export：65001:65002，Import：65001:65002

```cli
#在R2 上配置VPN 实例，并绑定接口，配置IP 地址

[R2]ip vpn-instance Finance&OA

[R2-vpn-instance-Finance&OA] route-distinguisher 65100:12

[R2-vpn-instance-Finance&OA-af-ipv4] vpn-target 65100:12 65001:65002

[R2-vpn-instance-Finance&OA-af-ipv4] quit

[R2]ip vpn-instance OA

[R2-vpn-instance-OA]

[R2-vpn-instance-OA] route-distinguisher 65001:2

[R2-vpn-instance-OA-af-ipv4] vpn-target 65001:65002

[R2-vpn-instance-OA-af-ipv4] quit

[R2]interface GigabitEthernet0/0/3

[R2-GigabitEthernet0/0/3] ip binding vpn-instance Finance&OA

[R2-GigabitEthernet0/0/3] ip address 10.0.12.2 255.255.255.0

[R2-GigabitEthernet0/0/3] quit

[R2]interface GigabitEthernet0/0/4

[R2-GigabitEthernet0/0/4] ip binding vpn-instance OA

[R2-GigabitEthernet0/0/4] ip address 10.0.21.2 255.255.255.0

[R2-GigabitEthernet0/0/4] quit

#在R4 上配置VPN 实例，并绑定接口，配置IP 地址

[R4]ip vpn-instance Finance

[R4-vpn-instance-Finance] route-distinguisher 65100:1

[R4-vpn-instance-Finance -af-ipv4] vpn-target 65100:12

[R4-vpn-instance-Finance -af-ipv4] quit

[R4]ip vpn-instance OA

[R4-vpn-instance-OA] route-distinguisher 65002:2

[R4-vpn-instance-OA-af-ipv4] vpn-target 65001:65002

[R4-vpn-instance-OA-af-ipv4] quit

[R4]interface GigabitEthernet0/0/2

[R4-GigabitEthernet0/0/2] ip binding vpn-instance Finance

[R4-GigabitEthernet0/0/2] ip address 10.0.45.4 255.255.255.0

[R4-GigabitEthernet0/0/2] quit

[R4]interface GigabitEthernet0/0/5

[R4-GigabitEthernet0/0/5] ip binding vpn-instance OA

[R4-GigabitEthernet0/0/5] ip address 10.0.42.4 255.255.255.0

[R4-GigabitEthernet0/0/5] quit

#检查VPN 实例配置结果

#在PE 上查看VPN 实例配置，以R2 为例

[R2]display current-configuration section vpn-instance

ip vpn-instance Finance&OA
```

ipv4-family route-distinguisher 65100:1 vpn-target 65100:12 65001:65002 export-extcommunity vpn-target 65100:12 65001:65002 import-extcommunity

```cli
ip vpn-instance OA
```

ipv4-family route-distinguisher 65001:2 vpn-target 65001:65002 export-extcommunity vpn-target 65001:65002 import-extcommunity

```cli
#在PE 上产看VPN 实例绑定信息，以R2 为例

[R2]display ip vpn-instance interface
```

Total VPN-Instances configured      : 2

VPN-Instance Name and ID : Finance&OA, 1

```cli
Interface Number : 1

Interface list : GigabitEthernet0/0/3
```

VPN-Instance Name and ID : OA, 2

```cli
Interface Number : 1

Interface list : GigabitEthernet0/0/4
```

通过以上信息可以确认VPN 实例配置是否正确，接口绑定是否正确。

步骤 4 部署MPLS 与MPLS LDP MPLS 与MPLS LDP 需要在BGP/MPLS IP VPN 数据转发的路径上配置。 本实验R2-R4 是主路径，R2-R3-R4 是备份路径，所以R2、R3、R4 设备与互联接口都需要开 启MPLS 与MPLS LDP。 MPLS LSR-ID 使用设备环回口的IP 地址。

```cli
#配置R2 MPLS

[R2]mpls lsr-id 10.10.10.2

[R2]mpls

[R2-mpls] quit

[R2]mpls ldp

[R2-mpls-ldp] quit

[R2]interface GigabitEthernet0/0/1

[R2-GigabitEthernet0/0/1] mpls

[R2-GigabitEthernet0/0/1] mpls ldp

[R2-GigabitEthernet0/0/1] quit

[R2]interface GigabitEthernet0/0/2

[R2-GigabitEthernet0/0/2] mpls

[R2-GigabitEthernet0/0/2] mpls ldp

[R2-GigabitEthernet0/0/2] quit

#配置R3 MPLS

[R3]mpls lsr-id 10.10.10.3

[R3]mpls

[R3-mpls] quit

[R3]mpls ldp

[R3-mpls-ldp] quit

[R3]interface GigabitEthernet0/0/2

[R3-GigabitEthernet0/0/2] mpls

[R3-GigabitEthernet0/0/2] mpls ldp

[R3-GigabitEthernet0/0/2] quit

[R3]interface GigabitEthernet0/0/3

[R3-GigabitEthernet0/0/3] mpls

[R3-GigabitEthernet0/0/3] mpls ldp

[R3-GigabitEthernet0/0/3] quit

#配置R4 MPLS

[R4]mpls lsr-id 10.10.10.4

[R4]mpls

[R4-mpls] quit

[R4]mpls ldp

[R4-mpls-ldp] quit

[R4]interface GigabitEthernet0/0/1

[R4-GigabitEthernet0/0/1] mpls

[R4-GigabitEthernet0/0/1] mpls ldp

[R4-GigabitEthernet0/0/1] quit

[R4]interface GigabitEthernet0/0/3

[R4-GigabitEthernet0/0/3] mpls

[R4-GigabitEthernet0/0/3] mpls ldp

[R4-GigabitEthernet0/0/3] quit

#检查MPLS 配置结果

#在R3 查看MPLS LDP 邻居

[R3]display mpls ldp peer
```

LDP Peer Information in Public network A '*' before a peer means the peer is being deleted. ------------------------------------------------------------------------------

PeerID              TransportAddress    DiscoverySource ------------------------------------------------------------------------------ 10.10.10.2:0           10.10.10.2         GigabitEthernet0/0/3 10.10.10.4:0           10.10.10.4         GigabitEthernet0/0/2 ------------------------------------------------------------------------------ TOTAL: 2 Peer(s) Found.

```cli
#在R3 查看MPLS LSP 表

[R3]display mpls lsp

-------------------------------------------------------------------------------------------------------- LSP Information: LDP LSP -------------------------------------------------------------------------------------------------------- FEC             In/Out Label    In/Out IF                      Vrf Name 10.10.10.2/32      NULL/3       -/GE0/0/3 10.10.10.2/32      1024/3         -/GE0/0/3 10.10.10.3/32      3/NULL       -/- 10.10.10.4/32      NULL/3       -/GE0/0/2 10.10.10.4/32      1025/3         -/GE0/0/2
```

从输出信息可以发现MPLS LSP 已经建立。

步骤 5 在骨干网建立VPNv4 IBGP 对等体 在AS 65100 内部署VPNv4 IBGP 对等体关系，R3 作为VPN RR， R2、R4 是R3 的反射器客 户端。 AS65100 只需要传递VPNv4 路由，所以可以不建立IPv4 IBGP 对等体关系。 R3 作为VPN RR，由于没有配置VPN 实例，所以需要关闭RT 过滤功能。

```cli
#配置R2 VPNv4 IBGP 对等体

[R2]bgp 65100

[R2-bgp] undo default ipv4-unicast

[R2-bgp] peer 10.10.10.3 as-number 65100

[R2-bgp] peer 10.10.10.3 connect-interface LoopBack0

[R2-bgp] ipv4-family vpnv4

[R2-bgp-af-vpnv4] peer 10.10.10.3 enable

[R2-bgp-af-vpnv4] quit

#配置R3 VPNv4 IBGP 对等体，R3 作为VPN RR 需要关闭RT 过滤功能。

[R3]bgp 65100

[R3-bgp] undo default ipv4-unicast

[R3-bgp] peer 10.10.10.2 as-number 65100

[R3-bgp] peer 10.10.10.2 connect-interface LoopBack0

[R3-bgp] peer 10.10.10.4 as-number 65100

[R3-bgp] peer 10.10.10.4 connect-interface LoopBack0

[R3-bgp] ipv4-family vpnv4

[R3-bgp-af-vpnv4] undo policy vpn-target

[R3-bgp-af-vpnv4] peer 10.10.10.2 enable

[R3-bgp-af-vpnv4] peer 10.10.10.2 reflect-client

[R3-bgp-af-vpnv4] peer 10.10.10.4 enable

[R3-bgp-af-vpnv4] peer 10.10.10.4 reflect-client

[R3-bgp-af-vpnv4] quit

#配置R4 VPNv4 IBGP 对等体

[R4]bgp 65100

[R4-bgp] undo default ipv4-unicast

[R4-bgp] peer 10.10.10.3 as-number 65100

[R4-bgp] peer 10.10.10.3 connect-interface LoopBack0

[R4-bgp] ipv4-family vpnv4

[R4-bgp-af-vpnv4] peer 10.10.10.3 enable

[R4-bgp-af-vpnv4] quit

#检查BGP 配置结果

#在R3 上查看BGP VPNv4 邻居

[R3-bgp]display bgp vpnv4 all peer

BGP local router ID : 10.10.10.3
```

Local AS number : 65100 Total number of peers : 2    Peers in established state : 2

```cli
Peer            V          AS  MsgRcvd  MsgSent  OutQ  Up/Down       State PrefRcv
```

10.10.10.2       4        65100      312      320      0   05:04:45  Established      0 10.10.10.4       4        65100      311      316      0   05:04:40  Established      0 查看结果可以发现IBGP 的VPNv4 邻居已建立。

步骤 6 发布Finance VPN 的路由条目 R1 与R5 作为CE 使用OSPF 将Loopback0 接口路由发送给PE，然后再由PE 相互传递路由。
OSPF 进程号使用1，区域号为0，Router ID 使用路由器的环回口地址，以R2 为例：

10.10.10.2。

```cli
#在R1（CE）与R2（PE）之间建立OSPF 邻居

[R1]router id 10.10.10.1

[R1]ospf 1

[R1-ospf-1] area 0

[R1-ospf-1-area-0.0.0.0] network 10.0.1.1 0.0.0.0

[R1-ospf-1-area-0.0.0.0] network 10.0.12.1 0.0.0.0

[R2]router id 10.10.10.2

[R2]ospf 1 vpn-instance Finance&OA

[R2-ospf-1] area 0

[R2-ospf-1-area-0.0.0.0] network 10.0.12.2 0.0.0.0

[R2-ospf-1-area-0.0.0.0] quit

#在R4（CE）与R5（PE）之间建立OSPF 邻居

[R5]router id 10.10.10.5

[R5]ospf 1

[R5-ospf-1] area 0

[R5-ospf-1-area-0.0.0.0] network 10.0.1.2 0.0.0.0

[R5-ospf-1-area-0.0.0.0] network 10.0.45.5 0.0.0.0

[R4]router id 10.10.10.4

[R4]ospf 1 vpn-instance Finance

[R4-ospf-1] area 0

[R4-ospf-1-area-0.0.0.0] network 10.0.45.4 0.0.0.0

[R4-ospf-1-area-0.0.0.0] quit

#在R2 与R4 上进行双向路由引入

[R2]ospf 1 vpn-instance Finance&OA

[R2-ospf-1] import-route bgp

[R2-ospf-1] quit

[R2]bgp 65100

[R2-bgp] ipv4-family vpn-instance Finance&OA
```

[R2-bgp-Finance&OA] network 10.0.1.1 32

```cli
[R4]ospf 1 vpn-instance Finance

[R4-ospf-1] import-route bgp

[R4-ospf-1] quit

[R4]bgp 65100

[R4-bgp] ipv4-family vpn-instance Finance
```

[R4-bgp-Finance&OA] network 10.0.1.2 32

```cli
#检查配置结果

#在R1、R5 上检查路由表（以R1 为例）

[R1]display ip routing-table
```

Route Flags: R - relay, D - download to fib

```cli
------------------------------------------------------------------------------ Routing Tables: Public Destinations : 9       Routes : 9
```

Destination/Mask    Proto   Pre  Cost      Flags NextHop         Interface

10.0.1.1/32  Direct   0    0         D   127.0.0.1        LoopBack0 10.0.1.2/32  OSPF   10   3         D   10.0.12.2        GigabitEthernet0/0/2 10.0.12.0/24  Direct   0    0         D   10.0.12.1        GigabitEthernet0/0/2 10.0.12.1/32  Direct   0    0         D   127.0.0.1        GigabitEthernet0/0/2 10.0.12.255/32  Direct   0    0         D   127.0.0.1        GigabitEthernet0/0/2 127.0.0.0/8   Direct   0    0         D   127.0.0.1        InLoopBack0 127.0.0.1/32  Direct   0    0         D   127.0.0.1        InLoopBack0 127.255.255.255/32  Direct   0    0         D   127.0.0.1        InLoopBack0 255.255.255.255/32  Direct   0    0         D   127.0.0.1        InLoopBack0

```cli
#在R1 上测试Loopback0 接口与R5 Loopback0 接口的连通性

[R1]ping -a 10.0.1.1 10.0.1.2

PING 10.0.1.2: 56  data bytes, press CTRL_C to break Reply from 10.0.1.2: bytes=56 Sequence=1 ttl=253 time=60 ms

--- 10.0.1.2 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 30/40/60 ms 通过以上信息可以确认，Finance VPN 的网段已经能够互通。
```

步骤 7 发布OA VPN 的路由条目 S1 与S2 作为CE 使用BGP 将Looback0 接口路由发送给PE，然后再由PE 相互传递路由。

```cli
#在S1（CE）与R2（PE）之间建立BGP 对等体关系并发布路由

[S1]bgp 65001

[S1-bgp] peer 10.0.21.2 as-number 65100

[S1-bgp] network 10.0.2.1 32

[S1-bgp] quit

[R2]bgp 65100

[R2-bgp] ipv4 vpn-instance OA

[R2-bgp-OA] peer 10.0.21.1 as-number 65001

[R2-bgp-OA] quit

#在S2（CE）与R4（PE）之间建立BGP 对等体关系并发布路由

[S2]bgp 65002

[S2-bgp] peer 10.0.42.4 as-number 65100

[S2-bgp] network 10.0.2.2 32

[S2-bgp] quit

[R4]bgp 65100

[R4-bgp] ipv4 vpn-instance OA

[R4-bgp-OA] peer 10.0.42.2 as-number 65002

[R4-bgp-OA] quit

#检查配置结果

#在R1、S1、S2 上检查路由表（以R1 为例）

[R1]display ip routing-table

Route Flags: R - relay, D - download to fib

------------------------------------------------------------------------------ Routing Tables: Public Destinations : 9       Routes : 9

Destination/Mask    Proto   Pre  Cost      Flags NextHop         Interface

10.0.1.1/32  Direct   0    0         D   127.0.0.1        LoopBack0 10.0.1.2/32  OSPF   10   3         D   10.0.12.2        GigabitEthernet0/0/2 10.0.2.1/32  O_ASE  150  1         D   10.0.12.2        GigabitEthernet0/0/2 10.0.2.2/32  O_ASE  150  1         D   10.0.12.2        GigabitEthernet0/0/2 10.0.12.0/24  Direct   0    0         D   10.0.12.1        GigabitEthernet0/0/2 10.0.12.1/32  Direct   0    0         D   127.0.0.1        GigabitEthernet0/0/2

10.0.12.255/32  Direct   0    0         D   127.0.0.1        GigabitEthernet0/0/2 127.0.0.0/8   Direct   0    0         D   127.0.0.1        InLoopBack0 127.0.0.1/32  Direct   0    0         D   127.0.0.1        InLoopBack0 127.255.255.255/32  Direct   0    0         D   127.0.0.1        InLoopBack0 255.255.255.255/32  Direct   0    0         D   127.0.0.1        InLoopBack0

#在R1 测试Loopback0 接口与S2 Loopback0 接口的连通性

<R1>ping -a 10.0.1.1 10.0.2.2 PING 10.0.2.2: 56  data bytes, press CTRL_C to break Reply from 10.0.2.2: bytes=56 Sequence=1 ttl=253 time=50 ms

--- 10.0.2.2 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 30/42/50 ms

#在S1 测试Loopback0 接口与S2 Loopback0 接口的连通性

[S1]ping -a 10.0.2.1 10.0.2.2

PING 10.0.2.2: 56  data bytes, press CTRL_C to break Reply from 10.0.2.2: bytes=56 Sequence=1 ttl=253 time=50 ms

--- 10.0.2.2 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 50/60/70 ms

#在S1 测试Loopback0 接口与R5 Loopback0 接口的连通性

[S1]ping -a 10.0.2.1 10.0.1.2

PING 10.0.1.2: 56  data bytes, press CTRL_C to break Request time out Request time out Request time out Request time out Request time out

--- 10.0.1.2 ping statistics ---

5 packet(s) transmitted

0 packet(s) received
```

100.00% packet loss 通过以上信息可以得出OA VPN 内，S1、S2 都可以与R1 互通，但是S1、S2 不能与R5 （Finance VPN 互通）。

## 6.1.3 思考题

如果需要让R5 与S1、S2 互通，VPN 实例配置应该如何修改？

## 6.1.4 配置参考

R1 设备配置

```cli
sysname R1
```

router id 10.10.10.1

```cli
interface GigabitEthernet0/0/2

ip address 10.0.12.1 255.255.255.0

interface LoopBack0

ip address 10.0.1.1 255.255.255.255

ospf 1

area 0.0.0.0 network 10.0.1.1 0.0.0.0 network 10.0.12.1 0.0.0.0

return
```

R2 设备配置

```cli
sysname R2
```

router id 10.10.10.2

```cli
ip vpn-instance Finance&OA
```

ipv4-family route-distinguisher 65100:12 vpn-target 65100:12 65001:65002 export-extcommunity vpn-target 65100:12 65001:65002 import-extcommunity

```cli
ip vpn-instance OA
```

ipv4-family route-distinguisher 65001:2 vpn-target 65001:65002 export-extcommunity vpn-target 65001:65002 import-extcommunity

```cli
mpls lsr-id 10.10.10.2 mpls

mpls ldp

isis 1 is-level level-2 cost-style wide network-entity 49.0001.0100.1001.0002.00 is-name R2
```

```cli
interface GigabitEthernet0/0/1

ip address 10.0.24.2 255.255.255.0

isis enable 1
```

```cli
mpls mpls ldp
```

```cli
interface GigabitEthernet0/0/2

ip address 10.0.23.2 255.255.255.0

isis enable 1 mpls mpls ldp

interface GigabitEthernet0/0/3

ip binding vpn-instance Finance&OA

ip address 10.0.12.2 255.255.255.0

interface GigabitEthernet0/0/4

ip binding vpn-instance OA

ip address 10.0.21.2 255.255.255.0

interface LoopBack0

ip address 10.10.10.2 255.255.255.255

isis enable 1

bgp 65100

undo default ipv4-unicast

peer 10.10.10.3 as-number 65100 peer 10.10.10.3 connect-interface LoopBack0
```

ipv4-family unicast

```cli
undo synchronization

undo peer 10.10.10.3 enable
```

ipv4-family vpnv4 policy vpn-target peer 10.10.10.3 enable

ipv4-family vpn-instance Finance&OA network 10.0.1.1 255.255.255.255

ipv4-family vpn-instance OA peer 10.0.21.1 as-number 65001

```cli
ospf 1 vpn-instance Finance&OA

import-route bgp area 0.0.0.0 network 10.0.12.2 0.0.0.0

return
```

R3 设备配置

```cli
sysname R3
```

router id 10.10.10.3

```cli
mpls lsr-id 10.10.10.3
```

mpls

```cli
mpls ldp

isis 1 is-level level-2 cost-style wide network-entity 49.0001.0100.1001.0003.00 is-name R3
```

```cli
interface GigabitEthernet0/0/2

ip address 10.0.34.3 255.255.255.0

isis enable 1 mpls mpls ldp

interface GigabitEthernet0/0/3

ip address 10.0.23.3 255.255.255.0

isis enable 1 mpls mpls ldp

interface LoopBack0

ip address 10.10.10.3 255.255.255.255

isis enable 1

bgp 65100

undo default ipv4-unicast

peer 10.10.10.2 as-number 65100 peer 10.10.10.2 connect-interface LoopBack0 peer 10.10.10.4 as-number 65100 peer 10.10.10.4 connect-interface LoopBack0
```

ipv4-family unicast

```cli
undo synchronization

undo peer 10.10.10.2 enable

undo peer 10.10.10.4 enable
```

ipv4-family vpnv4

```cli
undo policy vpn-target

peer 10.10.10.2 enable peer 10.10.10.2 reflect-client peer 10.10.10.4 enable peer 10.10.10.4 reflect-client

return
```

R4 设备配置

```cli
sysname R4
```

router id 10.10.10.4

```cli
ip vpn-instance Finance
```

ipv4-family route-distinguisher 65100:1 vpn-target 65100:12 export-extcommunity vpn-target 65100:12 import-extcommunity

```cli
ip vpn-instance OA
```

ipv4-family route-distinguisher 65002:2 vpn-target 65001:65002 export-extcommunity vpn-target 65001:65002 import-extcommunity

```cli
mpls lsr-id 10.10.10.4 mpls

mpls ldp

isis 1 is-level level-2 cost-style wide network-entity 49.0001.0100.1001.0004.00 is-name R4
```

```cli
interface GigabitEthernet0/0/1

ip address 10.0.24.4 255.255.255.0

isis enable 1 mpls mpls ldp

interface GigabitEthernet0/0/2

ip binding vpn-instance Finance

ip address 10.0.45.4 255.255.255.0

interface GigabitEthernet0/0/3

ip address 10.0.34.4 255.255.255.0

isis enable 1 mpls mpls ldp

interface GigabitEthernet0/0/5

ip binding vpn-instance OA

ip address 10.0.42.4 255.255.255.0

interface LoopBack0

ip address 10.10.10.4 255.255.255.255

isis enable 1

bgp 65100

undo default ipv4-unicast

peer 10.10.10.3 as-number 65100 peer 10.10.10.3 connect-interface LoopBack0
```

ipv4-family unicast

```cli
undo synchronization

undo peer 10.10.10.3 enable
```

ipv4-family vpnv4 policy vpn-target peer 10.10.10.3 enable

ipv4-family vpn-instance Finance network 10.0.1.2 255.255.255.255

ipv4-family vpn-instance OA peer 10.0.42.2 as-number 65002

```cli
ospf 1 vpn-instance Finance

import-route bgp area 0.0.0.0 network 10.0.45.4 0.0.0.0

return
```

R5 设备配置

```cli
sysname R5
```

router id 10.10.10.5

```cli
interface GigabitEthernet0/0/3

ip address 10.0.45.5 255.255.255.0

interface LoopBack0

ip address 10.0.1.2 255.255.255.255

ospf 1

area 0.0.0.0 network 10.0.1.2 0.0.0.0 network 10.0.45.5 0.0.0.0

return
```

S1 设备配置

```cli
sysname S1

interface Vlanif1

ip address 10.0.21.1 255.255.255.0

interface GigabitEthernet0/0/2
```

port link-type access

```cli
interface LoopBack0

ip address 10.0.2.1 255.255.255.255

bgp 65001

peer 10.0.21.2 as-number 65100
```

ipv4-family unicast

```cli
undo synchronization

network 10.0.2.1 255.255.255.255 peer 10.0.21.2 enable

return
```

S2 设备配置

```cli
sysname S2

interface Vlanif1

ip address 10.0.42.2 255.255.255.0

interface GigabitEthernet0/0/4
```

port link-type access

```cli
interface LoopBack0

ip address 10.0.2.2 255.255.255.255

bgp 65002

peer 10.0.42.4 as-number 65100
```

ipv4-family unicast

```cli
undo synchronization

network 10.0.2.2 255.255.255.255 peer 10.0.42.4 enable

return
```

思考题参考答案 《IGP 高级特性实验》参考答案 1.
OSPF 区域间的路由通告依赖Type-3 LSA，在OSPF 中，ABR 将到达其他区域的区域间
路由通过Type-3 LSA 注入本区域，用户可以在ABR 的区域视图下执行filter 命令对区域 内出、入方向ABR Type-3 LSA 设置过滤条件，只有通过过滤的信息才能被发布、接收。 值得注意的是，区域视图下的filter 命令只能够在ABR 上执行，而且只对Type-3 LSA 生 效。OSPF 区域的内部路由计算依赖于Type-1 LSA、Type-2 LSA，因此该命令对这些 LSA 无法进行过滤。

《BGP 高级特性实验》参考答案 1.

```cli
BGP 对等体接收到路由时会将路由放入BGP Adj-IN 路由表然后通过BGP 进方向路由策
```

略处理路由。 如果BGP 对等体只需要接收一部分路由，那么就不需要邻居发送全部路由条目，解决这 个问题有两种方式： a. 邻居出方向部署路由策略过滤发给BGP 对等体的路由，该方法需要邻居配合，灵活 性较差。 b. BGP 对等体使用ORF 特性，告知邻居只发送部分路由，该方法配置比较灵活，但是 需要两端都支持ORF 特性。 现网中可根据需求选择其中一种方式。

《IPv6 实验》参考答案 1. ISIS 由于使用了TLV 结构的LSP，使得使用ISIS 部署双栈网络时不需要重新开发新的协 议框架，但是ISIS 在计算拓扑时，默认只使用IPv4 网络构成的SPT 树。 如果ISIS 网络需要部署双栈网络，但部分设备不支持IPv6，此时默认情况下ISIS 依然会 使用基于IPv4 网络构成的SPT 树，有可能导致IPv6 数据包被发往不支持IPv6 的设备上 导致丢包。因此需要多拓扑特性。
OSPF 对于IPv6 网络专门开发了OSPFv3，OSPFv3 会基于IPv6 网络形成SPT 树，所以不
需要多拓扑特性。

《VLAN 高级技术实验》参考答案 1. 在本地ARP 表项中可以查找到被请求的主机其ARP 表项（动态学习或者静态绑定皆 可），则Super-VLAN 的VLANIF 会进行ARP 响应。

《以太网交换安全实验》参考答案 1. 所有同网段的终端之间通信都通过网关，网关可以对终端之间的通信进行限制、监管（优 点），但原本应由交换机进行二层转发的流量现全部由网关进行三层转发，增加了网关的 负担。

《BGP/MPLS IP VPN 实验》参考答案 1. VPN 实例中可以配置多个Export RT 值和Import RT 值，对端收到路由后，只要路由中的 一个Export RT 值与本地配置的一个Import RT 值匹配就能接收路由。 因此如果需要让R5 也能接收S1 与S2 的路由，只需要在R4 的VPN 实例Finance 中添加 Import RT 65001:65002 即可。
