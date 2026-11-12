---
doc_id: "hcie-datacom-v1.0-lab-14"
title: "9.2 EVPN L3VPN over SRv6 Policy"
book: "HCIE-Datacom-V1.0-Lab"
book_title: "HCIE-Datacom V1.0 实验手册"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "lab"
source_pdf: "HCIE-Datacom V1.0 实验手册.pdf"
seq: 14
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 9.2 EVPN L3VPN over SRv6 Policy

## 9.2.1 实验介绍

9.2.1.1 学习目标

- 实现手动分配私网路由的SID
- 实现CE 之间互访使用的L3VPN 隧道迭代到SRv6 Policy
- 实现通过配置多个Segment List 实现承载网络的高可靠性
- 实现通过配置多个Candidate Path 实现承载网络的高可靠性

9.2.1.2 实验组网介绍

图9-2 EVPN L3VPNv4 over SRv6 Policy 拓扑 设备连接方式、IP 地址规划如图所示，接口互联地址均为2001::Y/126，其中Y 值已在图中标 注。所有设备均创建Loopback0 接口，Loopback 接口IP 地址为2001::X:X/128，其中X 值会在 对应配置步骤中使用表格标明。 PE1、PE4 上创建Loopback1 接口，IP 地址配置为10.1.X.X/32，其中X 值会在对应配置步骤中 使用表格标明，用于模拟CE 用户的接入。 PE1、PE4 上创建Loopback2 接口，配置其IPv6 地址为2002::X:X/128，其中X 值会在对应配置 步骤中使用表格标明，用于模拟CE 用户的接入。 PE1、PE4 之间的L3VPN 流量通过SRv6 TE Policy 进入广域承载网络，配置多条Candidate Path 实现业务的高可靠性，在Candidate Path 1 中配置多条Segment List 实现路径的高可靠性。

## 9.2.2 实验任务

9.2.2.1 配置思路

1. 设备基础IP 地址配置。
2. 配置SR 域内的IS-IS，在互联接口、Loopback0 接口上开启IS-IS，实现SR 域内互通。
3. 创建VPN-Instance，名称为vpna，在PE1、PE4 上将Loopback1 接口划分到该VPN- Instance，并在BGP 实例中引入直连路由。创建VPN-Instance vpna6，在PE1、PE4 上将 Loopback2 接口划分到该VPN-Instance，并在BGP 实例中引入直连路由。
4. 配置整个PE1、P1、P2、PE4 的IBGP 对等体关系，其中P1、P2 作为RR，反射来自PE1、 PE4 的VPNv4 路由。
5. 配置路由策略，实现PE1、PE4 之间相互发布VPNv4 路由时打上Color 值。
6. 完成SRv6 配置，全局使能SRv6，在IS-IS 中开启对SR 的扩展能力，配置SRv6 封装源地 址、Locator 前缀，手动为VPN 实例路由分配SID，手动为设备分配标识节点自身的SID， 开启向BGP 对等体发布路由时携带SID 功能。
7. 配置隧道策略，将私网路由迭代到SRv6 Policy。

9.2.2.2 配置步骤

步骤 1 基础连通性配置 指定命令生效模式为立即生效，配置互联接口、Loopback0 接口IP 地址，其中Loopback0 接口 地址按下表规划配置。 设备Loopback0 接口IP 设备编号 X值 Loopback0接口IP PE1 2001::1:1 PE2 2001::2:2 PE3 2001::3:3 PE4 2001::4:4 P1 2001::5:5 P2 2001::6:6

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

<PE1>system-view immediately 以PE1 为例，其他设备执行相同操作。

#所有设备关闭全局DCN 功能。

[PE1] undo dcn

Warning: This operation will disable DCN function. Continue? [Y/N]:y
```

以PE1 为例，其他设备执行相同操作。 NE 路由器接口默认开启了DCN 功能，为方便实验，所有设备上全局关闭DCN 功能。

```cli
#配置PE1 的互联接口、Loopback0 接口IPv6 地址。

[PE1]interface LoopBack0

[PE1-LoopBack0] ipv6 enable

[PE1-LoopBack0] ipv6 address 2001::1:1/128

[PE1-LoopBack0] quit

[PE1]interface GigabitEthernet0/5/0

[PE1-GigabitEthernet0/5/0] ipv6 enable

[PE1-GigabitEthernet0/5/0] ipv6 address 2001::1/126

[PE1-GigabitEthernet0/5/0] quit

[PE1]interface GigabitEthernet0/5/1

[PE1-GigabitEthernet0/5/1] ipv6 enable

[PE1-GigabitEthernet0/5/1] ipv6 address 2001::5/126

[PE1-GigabitEthernet0/5/1] quit

#配置PE2 的互联接口、Loopback0 接口IPv6 地址。

[PE2]interface LoopBack0

[PE2-LoopBack0] ipv6 enable

[PE2-LoopBack0] ipv6 address 2001::2:2/128

[PE2-LoopBack0] quit

[PE2]interface GigabitEthernet0/5/0

[PE2-GigabitEthernet0/5/0] ipv6 enable

[PE2-GigabitEthernet0/5/0] ipv6 address 2001::2/126

[PE2-GigabitEthernet0/5/0] quit

[PE2]interface GigabitEthernet0/5/1

[PE2-GigabitEthernet0/5/1] ipv6 enable

[PE2-GigabitEthernet0/5/1] ipv6 address 2001::9/126

[PE2-GigabitEthernet0/5/1] quit

#配置PE3 的互联接口、Loopback0 接口IPv6 地址。

[PE3]interface LoopBack0

[PE3-LoopBack0] ipv6 enable

[PE3-LoopBack0] ipv6 address 2001::3:3/128

[PE3-LoopBack0] quit

[PE3]interface GigabitEthernet0/5/0

[PE3-GigabitEthernet0/5/0] ipv6 enable

[PE3-GigabitEthernet0/5/0] ipv6 address 2001::19/126

[PE3-GigabitEthernet0/5/0] quit

[PE3]interface GigabitEthernet0/5/1

[PE3-GigabitEthernet0/5/1] ipv6 enable

[PE3-GigabitEthernet0/5/1] ipv6 address 2001::12/126

[PE3-GigabitEthernet0/5/1] quit

#配置PE4 的互联接口、Loopback0 接口IPv6 地址。

[PE4]interface LoopBack0

[PE4-LoopBack0] ipv6 enable

[PE4-LoopBack0] ipv6 address 2001::4:4/128

[PE4-LoopBack0] quit

[PE4]interface GigabitEthernet0/5/0

[PE4-GigabitEthernet0/5/0] ipv6 enable

[PE4-GigabitEthernet0/5/0] ipv6 address 2001::1a/126

[PE4-GigabitEthernet0/5/0] quit

[PE4]interface GigabitEthernet0/5/1

[PE4-GigabitEthernet0/5/1] ipv6 enable

[PE4-GigabitEthernet0/5/1] ipv6 address 2001::16/126

[PE4-GigabitEthernet0/5/1] quit

#配置P1 的互联接口、Loopback0 接口IPv6 地址。

[P1]interface LoopBack0

[P1-LoopBack0] ipv6 enable

[P1-LoopBack0] ipv6 address 2001::5:5/128

[P1-LoopBack0] quit

[P1]interface GigabitEthernet0/5/0

[P1-GigabitEthernet0/5/0] ipv6 enable

[P1-GigabitEthernet0/5/0] ipv6 address 2001::d/126

[P1-GigabitEthernet0/5/0] quit

[P1]interface GigabitEthernet0/5/1

[P1-GigabitEthernet0/5/1] ipv6 enable

[P1-GigabitEthernet0/5/1] ipv6 address 2001::6/126

[P1-GigabitEthernet0/5/1] quit

[P1]interface GigabitEthernet0/5/2

[P1-GigabitEthernet0/5/2] ipv6 enable

[P1-GigabitEthernet0/5/2] ipv6 address 2001::11/126

[P1-GigabitEthernet0/5/2] quit

#配置P2 的互联接口、Loopback0 接口IPv6 地址。

[P2]interface LoopBack0

[P2-LoopBack0] ipv6 enable

[P2-LoopBack0] ipv6 address 2001::6:6/128

[P2-LoopBack0] quit

[P2]interface GigabitEthernet0/5/0

[P2-GigabitEthernet0/5/0] ipv6 enable

[P2-GigabitEthernet0/5/0] ipv6 address 2001::e/126

[P2-GigabitEthernet0/5/0] quit

[P2]interface GigabitEthernet0/5/1

[P2-GigabitEthernet0/5/1] ipv6 enable

[P2-GigabitEthernet0/5/1] ipv6 address 2001::a/126

[P2-GigabitEthernet0/5/1] quit

[P2]interface GigabitEthernet0/5/2

[P2-GigabitEthernet0/5/2] ipv6 enable

[P2-GigabitEthernet0/5/2] ipv6 address 2001::15/126

[P2-GigabitEthernet0/5/2] quit

#在P1、PE2、PE4 上测试互联接口连通性。

[P1]ping ipv6 -c 1 2001::5

PING 2001::5 : 56  data bytes, press CTRL_C to break Reply from 2001::5 bytes=56 Sequence=1 hop limit=64 time=1 ms

--- 2001::5 ping statistics---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max=1/1/1 ms

[P1]ping ipv6 -c 1 2001::12

PING 2001::12 : 56  data bytes, press CTRL_C to break Reply from 2001::12 bytes=56 Sequence=1 hop limit=64 time=1 ms

--- 2001::12 ping statistics---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max=1/1/1 ms

[P1]ping ipv6 -c 1 2001::e

PING 2001::E : 56  data bytes, press CTRL_C to break Reply from 2001::E bytes=56 Sequence=1 hop limit=64 time=1 ms

--- 2001::E ping statistics---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max=1/1/1 ms

[PE2]ping ipv6 -c 1 2001::1

PING 2001::1 : 56  data bytes, press CTRL_C to break Reply from 2001::1 bytes=56 Sequence=1 hop limit=64 time=1 ms

--- 2001::1 ping statistics---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max=1/1/1 ms

[PE2]ping ipv6 -c 1 2001::a

PING 2001::A : 56  data bytes, press CTRL_C to break Reply from 2001::A bytes=56 Sequence=1 hop limit=64 time=1 ms

--- 2001::A ping statistics---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max=1/1/1 ms

[PE4]ping ipv6 -c 1 2001::15

PING 2001::15 : 56  data bytes, press CTRL_C to break Reply from 2001::15 bytes=56 Sequence=1 hop limit=64 time=1 ms

--- 2001::15 ping statistics---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max=1/1/1 ms

[PE4]ping ipv6 -c 1 2001::19

PING 2001::19 : 56  data bytes, press CTRL_C to break Reply from 2001::19 bytes=56 Sequence=1 hop limit=64 time=1 ms

--- 2001::19 ping statistics---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max=1/1/1 ms 连通性正常。
```

步骤 2 IS-IS 配置 部署SRv6 域内的IS-IS，进程号使用1，所有IS-IS 路由器都是L2 路由器，cost 类型是wide（用 于支持IS-IS 扩展特性），NET 地址的区域号是49.0001，System ID 使用如下值： 49.0001.000X.000X.000X，其中X 为设备编号值，参照步骤1 中表格，IS-IS 主机名与设备名保 持一致。 在互联接口、Loopback0 接口上使能IS-IS，同时注意修改接口类型为P2P。

```cli
#部署PE1 的IS-IS。

[PE1]isis 1

[PE1-isis-1] is-level level-2

[PE1-isis-1] cost-style wide

[PE1-isis-1] network-entity 49.0001.0001.0001.0001.00

[PE1-isis-1] is-name PE1

[PE1-isis-1] ipv6 enable topology ipv6

[PE1-isis-1] quit

[PE1]interface GigabitEthernet0/5/0

[PE1-GigabitEthernet0/5/0] isis ipv6 enable 1

[PE1-GigabitEthernet0/5/0] isis circuit-type p2p

[PE1-GigabitEthernet0/5/0] quit

[PE1]interface GigabitEthernet0/5/1

[PE1-GigabitEthernet0/5/1] isis ipv6 enable 1

[PE1-GigabitEthernet0/5/1] isis circuit-type p2p

[PE1-GigabitEthernet0/5/1] quit

[PE1]interface LoopBack 0

[PE1-LoopBack0] isis ipv6 enable 1

#部署PE2 的IS-IS。

[PE2]isis 1

[PE2-isis-1] is-level level-2

[PE2-isis-1] cost-style wide

[PE2-isis-1] network-entity 49.0001.0002.0002.0002.00

[PE2-isis-1] is-name PE2

[PE2-isis-1] ipv6 enable topology ipv6

[PE2-isis-1] quit

[PE2]interface GigabitEthernet0/5/0

[PE2-GigabitEthernet0/5/0] isis ipv6 enable 1

[PE2-GigabitEthernet0/5/0] isis circuit-type p2p

[PE2-GigabitEthernet0/5/0] quit

[PE2]interface GigabitEthernet0/5/1

[PE2-GigabitEthernet0/5/1] isis ipv6 enable 1

[PE2-GigabitEthernet0/5/1] isis circuit-type p2p

[PE2-GigabitEthernet0/5/1] quit

[PE2]interface LoopBack 0

[PE2-LoopBack0] isis ipv6 enable 1

#部署PE3 的IS-IS。

[PE3]isis 1

[PE3-isis-1] is-level level-2

[PE3-isis-1] cost-style wide

[PE3-isis-1] network-entity 49.0001.0003.0003.0003.00

[PE3-isis-1] is-name PE3

[PE3-isis-1] ipv6 enable topology ipv6

[PE3-isis-1] quit

[PE3]interface GigabitEthernet0/5/0

[PE3-GigabitEthernet0/5/0] isis ipv6 enable 1

[PE3-GigabitEthernet0/5/0] isis circuit-type p2p

[PE3-GigabitEthernet0/5/0] quit

[PE3]interface GigabitEthernet0/5/1

[PE3-GigabitEthernet0/5/1] isis ipv6 enable 1

[PE3-GigabitEthernet0/5/1] isis circuit-type p2p

[PE3-GigabitEthernet0/5/1] quit

[PE3]interface LoopBack 0

[PE3-LoopBack0] isis ipv6 enable 1

#部署PE4 的IS-IS。

[PE4]isis 1

[PE4-isis-1] is-level level-2

[PE4-isis-1] cost-style wide

[PE4-isis-1] network-entity 49.0001.0004.0004.0004.00

[PE4-isis-1] is-name PE4

[PE4-isis-1] ipv6 enable topology ipv6

[PE4-isis-1] quit

[PE4]interface GigabitEthernet0/5/0

[PE4-GigabitEthernet0/5/0] isis ipv6 enable 1

[PE4-GigabitEthernet0/5/0] isis circuit-type p2p

[PE4-GigabitEthernet0/5/0] quit

[PE4]interface GigabitEthernet0/5/1

[PE4-GigabitEthernet0/5/1] isis ipv6 enable 1

[PE4-GigabitEthernet0/5/1] isis circuit-type p2p

[PE4-GigabitEthernet0/5/1] quit

[PE4]interface LoopBack 0

[PE4-LoopBack0] isis ipv6 enable 1

#部署P1 的IS-IS。

[P1]isis 1

[P1-isis-1] is-level level-2

[P1-isis-1] cost-style wide

[P1-isis-1] network-entity 49.0001.0005.0005.0005.00

[P1-isis-1] is-name P1

[P1-isis-1] ipv6 enable topology ipv6

[P1-isis-1] quit

[P1]interface GigabitEthernet0/5/0

[P1-GigabitEthernet0/5/0] isis ipv6 enable 1

[P1-GigabitEthernet0/5/0] isis circuit-type p2p

[P1-GigabitEthernet0/5/0] quit

[P1]interface GigabitEthernet0/5/1

[P1-GigabitEthernet0/5/1] isis ipv6 enable 1

[P1-GigabitEthernet0/5/1] isis circuit-type p2p

[P1-GigabitEthernet0/5/1] quit

[P1]interface GigabitEthernet0/5/2

[P1-GigabitEthernet0/5/2] isis ipv6 enable 1

[P1-GigabitEthernet0/5/2] isis circuit-type p2p

[P1-GigabitEthernet0/5/2] quit

[P1]interface LoopBack 0

[P1-LoopBack0] isis ipv6 enable 1

#部署P2 的IS-IS。

[P2]isis 1

[P2-isis-1] is-level level-2

[P2-isis-1] cost-style wide

[P2-isis-1] network-entity 49.0001.0006.0006.0006.00

[P2-isis-1] is-name P2

[P2-isis-1] ipv6 enable topology ipv6

[P2-isis-1] quit

[P2]interface GigabitEthernet0/5/0

[P2-GigabitEthernet0/5/0] isis ipv6 enable 1

[P2-GigabitEthernet0/5/0] isis circuit-type p2p

[P2-GigabitEthernet0/5/0] quit

[P2]interface GigabitEthernet0/5/1

[P2-GigabitEthernet0/5/1] isis ipv6 enable 1

[P2-GigabitEthernet0/5/1] isis circuit-type p2p

[P2-GigabitEthernet0/5/1] quit

[P2]interface GigabitEthernet0/5/2

[P2-GigabitEthernet0/5/2] isis ipv6 enable 1

[P2-GigabitEthernet0/5/2] isis circuit-type p2p

[P2-GigabitEthernet0/5/2] quit

[P2]interface LoopBack 0

[P2-LoopBack0] isis ipv6 enable 1

[P2-LoopBack0] quit

#在P1、PE2、PE4 上检查IS-IS 邻居关系。

[P1]display isis peer

Peer information for ISIS(1)

System Id     Interface          Circuit Id            State HoldTime Type     PRI -------------------------------------------------------------------------------- P2*            GE0/5/0            0000000006         Up   26s       L2       -- PE1*           GE0/5/1            0000000007         Up   25s       L2       -- PE3*           GE0/5/2            0000000007         Up   27s       L2       --

Total Peer(s): 3

[PE2]display isis peer

Peer information for ISIS(1)

System Id     Interface          Circuit Id            State HoldTime Type     PRI -------------------------------------------------------------------------------- PE1*          GE0/5/0            0000000006         Up   26s       L2       -- P2*           GE0/5/1            0000000007         Up   25s       L2       --

Total Peer(s): 2

[PE4]display isis peer

Peer information for ISIS(1)

System Id     Interface          Circuit Id            State HoldTime Type     PRI -------------------------------------------------------------------------------- PE3*          GE0/5/0            0000000006         Up   23s       L2       -- P2*           GE0/5/1            0000000007         Up   23s       L2       --

Total Peer(s): 2

#在P1 上检查IS-IS 路由。

[P1]display isis route

Route information for ISIS(1)

-----------------------------

ISIS(1) Level-2 Forwarding Table --------------------------------

IPV6 Dest.     ExitInterface      NextHop                      Cost     Flags -------------------------------------------------------------------------------- 2001::/126     GE0/5/1            FE80::F29B:B8FF:FECC:7453  20       A/-/-/- 2001::4/126    GE0/5/1            Direct                       10       D/-/L/- 2001::8/126    GE0/5/0            FE80::F29B:B8FF:FECC:740A  20       A/-/-/- 2001::C/126     GE0/5/0            Direct                       10       D/-/L/- 2001::10/126    GE0/5/2            Direct                       10       D/-/L/- 2001::14/126    GE0/5/0            FE80::F29B:B8FF:FECC:740A  20       A/-/-/- 2001::18/126    GE0/5/2            FE80::F29B:B8FF:FECC:70C3  20       A/-/-/- 2001::1:1/128   GE0/5/1            FE80::F29B:B8FF:FECC:7453  10       A/-/-/- 2001::2:2/128   GE0/5/1            FE80::F29B:B8FF:FECC:7453  20       A/-/-/- GE0/5/0            FE80::F29B:B8FF:FECC:740A 2001::3:3/128   GE0/5/2            FE80::F29B:B8FF:FECC:70C3  10       A/-/-/- 2001::4:4/128   GE0/5/2            FE80::F29B:B8FF:FECC:70C3  20       A/-/-/- GE0/5/0            FE80::F29B:B8FF:FECC:740A 2001::5:5/128   Loop0              Direct                       0        D/-/L/- 2001::6:6/128   GE0/5/0            FE80::F29B:B8FF:FECC:740A  10       A/-/-/- Flags: D-Direct, A-Added to URT, L-Advertised in LSPs, S-IGP Shortcut, U-Up/Down Bit Set, LP-Local Prefix-Sid Protect Type: L-Link Protect, N-Node Protect 已正常学习到所有路由。 步骤 3 配置L3VPN 在PE1、PE4 上均创建VPN-Instance vpna，创建Loopback1 接口并将其划分到VPN 实例中。 在PE1、PE4 上均创建VPN-Instance vpna6，在PE1、PE4 上将Loopback2 接口划分到该VPN- Instance，并在BGP 实例中引入直连路由。 在PE1、PE4 与P1、P2 之间建立MP-BGP EVPN 对等体关系（AS 号采用65100），其中P1、P2 为RR，PE1、PE4 为RR 客户端，通过P1、P2 实现EVPN 路由的传递。
#创建VPN-Instance vpna。

[PE1]ip vpn-instance vpna

[PE1-vpn-instance-vpna] ipv4-family

[PE1-vpn-instance-vpna-af-ipv4] route-distinguisher 100:10

[PE1-vpn-instance-vpna-af-ipv4] vpn-target 100:1020 evpn

[PE1-vpn-instance-vpna-af-ipv4] evpn mpls routing-enable

[PE4]ip vpn-instance vpna

[PE4-vpn-instance-vpna] ipv4-family

[PE4-vpn-instance-vpna-af-ipv4] route-distinguisher 100:40

[PE4-vpn-instance-vpna-af-ipv4] vpn-target 100:1020 evpn

[PE4-vpn-instance-vpna-af-ipv4] evpn mpls routing-enable
```

只需配置EVPN RT 值，同时开启EVPN 生成和发布IP 前缀路由和IRB 路由的功能。

```cli
#创建Loopback1 接口，关联VPN-Instance，并参照步骤1 中表格配置接口IP 地址。

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
#创建VPN-Instance vpna6。

[PE1]ip vpn-instance vpna6

[PE1-vpn-instance-vpna6] ipv6-family

[PE1-vpn-instance-vpna6-af-ipv6] route-distinguisher 100:11

[PE1-vpn-instance-vpna6-af-ipv6] vpn-target 100:1122 evpn

[PE1-vpn-instance-vpna6-af-ipv6] evpn mpls routing-enable

[PE4]ip vpn-instance vpna6

[PE4-vpn-instance-vpna6] ipv6-family

[PE4-vpn-instance-vpna6-af-ipv6] route-distinguisher 100:44

[PE4-vpn-instance-vpna6-af-ipv6] vpn-target 100:1122 evpn

[PE4-vpn-instance-vpna6-af-ipv6] evpn mpls routing-enable
```

只需配置EVPN RT 值，同时开启EVPN 生成和发布IP 前缀路由和IRB 路由的功能。

```cli
#创建Loopback2 接口，关联VPN-Instance，并参照步骤1 中表格配置接口IP 地址。

[PE1]interface LoopBack 2

[PE1-LoopBack2]ip binding vpn-instance vpna6

Info: All IPv4 and IPv6 related configurations on this interface are removed.

[PE1-LoopBack2]ipv6 enable

[PE1-LoopBack2]ipv6 address 2002::1:1 128

[PE4]interface LoopBack 2

[PE4-LoopBack2]ip binding vpn-instance vpna6

Info: All IPv4 and IPv6 related configurations on this interface are removed.

[PE4-LoopBack2]ipv6 enable

[PE4-LoopBack2]ipv6 address 2002::4:4 128
```

注意先关联接口到VPN-Instance，再配置接口IP 地址。

```cli
#配置MP-BGP EVPN 对等体关系，采用Loopback0 接口建立邻居关系，Router ID 使用
```

10.0.X.X，其中X 值参照步骤1 中表格。

```cli
[PE1]bgp 65100

[PE1-bgp] router-id 10.0.1.1

[PE1-bgp] peer 2001::5:5 as-number 65100

[PE1-bgp] peer 2001::5:5 connect-interface LoopBack 0

[PE1-bgp] peer 2001::6:6 as-number 65100

[PE1-bgp] peer 2001::6:6 connect-interface LoopBack 0

[PE1-bgp] l2vpn-family evpn

[PE1-bgp-af-evpn] peer 2001::5:5 enable

[PE1-bgp-af-evpn] peer 2001::5:5 advertise encap-type srv6

[PE1-bgp-af-evpn] peer 2001::6:6 enable

[PE1-bgp-af-evpn] peer 2001::6:6 advertise encap-type srv6
```

默认情况下，本端设备向邻居发布的EVPN 路由携带MPLS 封装属性，无法用于实现SRv6 转 发，需要配置advertise encap-type srv6 命令以实现EVPN 路由迭代到SRv6 转发。

```cli
[PE4]bgp 65100

[PE4-bgp] router-id 10.0.4.4

[PE4-bgp] peer 2001::5:5 as-number 65100

[PE4-bgp] peer 2001::5:5 connect-interface LoopBack0

[PE4-bgp] peer 2001::6:6 as-number 65100

[PE4-bgp] peer 2001::6:6 connect-interface LoopBack0

[PE4-bgp] l2vpn-family evpn

[PE4-bgp-af-evpn] peer 2001::5:5 enable

[PE4-bgp-af-evpn] peer 2001::5:5 advertise encap-type srv6

[PE4-bgp-af-evpn] peer 2001::6:6 enable

[PE4-bgp-af-evpn] peer 2001::6:6 advertise encap-type srv6

[P1]bgp 65100

[P1-bgp] router-id 10.0.5.5

[P1-bgp] peer 2001::1:1 as-number 65100

[P1-bgp] peer 2001::1:1 connect-interface LoopBack0

[P1-bgp] peer 2001::4:4 as-number 65100

[P1-bgp] peer 2001::4:4 connect-interface LoopBack0

[P1-bgp] l2vpn-family evpn

[P1-bgp-af-evpn] undo policy vpn-target

[P1-bgp-af-evpn] peer 2001::1:1 enable

[P1-bgp-af-evpn] peer 2001::1:1 advertise encap-type srv6

[P1-bgp-af-evpn] peer 2001::1:1 reflect-client

[P1-bgp-af-evpn] peer 2001::4:4 enable

[P1-bgp-af-evpn] peer 2001::4:4 advertise encap-type srv6

[P1-bgp-af-evpn] peer 2001::4:4 reflect-client

[P2]bgp 65100

[P2-bgp] router-id 10.0.6.6

[P2-bgp] peer 2001::1:1 as-number 65100

[P2-bgp] peer 2001::1:1 connect-interface LoopBack0

[P2-bgp] peer 2001::4:4 as-number 65100

[P2-bgp] peer 2001::4:4 connect-interface LoopBack0

[P2-bgp] l2vpn-family evpn

[P2-bgp-af-evpn] undo policy vpn-target

[P2-bgp-af-evpn] peer 2001::1:1 enable

[P2-bgp-af-evpn] peer 2001::1:1 advertise encap-type srv6

[P2-bgp-af-evpn] peer 2001::1:1 reflect-client

[P2-bgp-af-evpn] peer 2001::4:4 enable

[P2-bgp-af-evpn] peer 2001::4:4 advertise encap-type srv6

[P2-bgp-af-evpn] peer 2001::4:4 reflect-client

#在P1、P2 上检查MP-BGP 对等体关系。

[P1]display bgp evpn peer

BGP local router ID : 10.0.5.5
```

Local AS number : 65100 Total number of peers : 2                 Peers in established state : 2

```cli
Peer             V       AS   MsgRcvd  MsgSent OutQ Up/Down      State           PrefRcv 2001::1:1        4       65100        6        6     0  00:00:48        Established        0 2001::4:4        4       65100        6        6     0  00:00:49        Established        0
```

```cli
[P2]display bgp evpn peer

BGP local router ID : 10.0.6.6
```

Local AS number : 65100 Total number of peers : 2                 Peers in established state : 2

```cli
Peer             V       AS   MsgRcvd  MsgSent OutQ Up/Down      State           PrefRcv 2001::1:1        4       65100        6        6     0  00:00:48        Established        0 2001::4:4        4       65100        6        6     0  00:00:49        Established        0
```

```cli
#将Loopback1 接口的直连路由引入到BGP 中。

[PE1]bgp 65100

[PE1-bgp]ipv4-family vpn-instance vpna

[PE1-bgp-vpna] import-route direct

[PE1-bgp-vpna] advertise l2vpn evpn

[PE4]bgp 65100

[PE4-bgp]ipv4-family vpn-instance vpna

[PE4-bgp-vpna] import-route direct

[PE4-bgp-vpna] advertise l2vpn evpn
```

并注意使能VPN 实例向EVPN 实例发布IP 路由功能。 注意此时还未配置SRv6，EVPN 路由并未携带任何SRv6 参数，所以暂时无法看到对外传递的 EVPN 路由。

```cli
#将Loopback2 接口的直连路由引入到BGP 中。

[PE1] bgp 65100

[PE1-bgp] ipv6-family vpn-instance vpna6

[PE1-bgp-6-vpna6] import-route direct

[PE1-bgp-6-vpna6] advertise l2vpn evpn

[PE4] bgp 65100

[PE4-bgp] ipv6-family vpn-instance vpna6

[PE4-bgp-6-vpna6] import-route direct

[PE4-bgp-6-vpna6] advertise l2vpn evpn
```

步骤 4 配置SRv6 所有设备全局使能SRv6，配置封装源地址为Loopback0 接口的IPv6 地址，配置Locator，分配 代表节点自身的SID，同时为VPN 实例中私网路由手动分配SID。在BGP L2VPN 视图中开启私 网路由传递时携带私网路由SRv6 SID 功能、IS-IS 中开启支持SRv6 Locator 对外发布功能。

SRv6 Locator 配置参考下表规划： 图9-3 SRv6 Locator 规划表 设备 IPv6 Prefix MASK 静态段长度 PE1 2001:1:: PE2 2001:2:: PE3 2001:3:: PE4 2001:4:: P1 2001:5:: P2 2001:6::

```cli
#全局使能SR，配置封装源地址，Locator。

[PE1]segment-routing ipv6

[PE1-segment-routing-ipv6] encapsulation source-address 2001::1:1

[PE1-segment-routing-ipv6] locator SRv6 ipv6-prefix 2001:1:: 96 static 16

[PE1-segment-routing-ipv6-locator] opcode ::1 end

[PE1-segment-routing-ipv6-locator] opcode ::11 end-dt4 vpn-instance vpna evpn

[PE1-segment-routing-ipv6-locator] opcode ::61 end-dt6 vpn-instance vpna6 evpn
```

分配end 类型的opcode，在PE1、4 上手动分配VPN 实例的end-dt4、end-dt6 类型的SID。

```cli
[PE2]segment-routing ipv6

[PE2-segment-routing-ipv6] encapsulation source-address 2001::2:2

[PE2-segment-routing-ipv6] locator SRv6 ipv6-prefix 2001:2:: 96 static 16

[PE2-segment-routing-ipv6-locator] opcode ::1 end

[PE3]segment-routing ipv6

[PE3-segment-routing-ipv6] encapsulation source-address 2001::3:3

[PE3-segment-routing-ipv6] locator SRv6 ipv6-prefix 2001:3:: 96 static 16

[PE3-segment-routing-ipv6-locator] opcode ::1 end

[PE4]segment-routing ipv6

[PE4-segment-routing-ipv6] encapsulation source-address 2001::4:4

[PE4-segment-routing-ipv6] locator SRv6 ipv6-prefix 2001:4:: 96 static 16

[PE4-segment-routing-ipv6-locator] opcode ::1 end

[PE4-segment-routing-ipv6-locator] opcode ::44 end-dt4 vpn-instance vpna evpn

[PE4-segment-routing-ipv6-locator] opcode ::64 end-dt6 vpn-instance vpna6 evpn

[P1]segment-routing ipv6

[P1-segment-routing-ipv6] encapsulation source-address 2001::5:5

[P1-segment-routing-ipv6] locator SRv6 ipv6-prefix 2001:5:: 96 static 16

[P1-segment-routing-ipv6-locator] opcode ::1 end

[P2]segment-routing ipv6

[P2-segment-routing-ipv6] encapsulation source-address 2001::6:6

[P2-segment-routing-ipv6] locator SRv6 ipv6-prefix 2001:6:: 96 static 16

[P2-segment-routing-ipv6-locator] opcode ::1 end

#在BGP VPN 实例中使能业务迭代SRv6 Policy 隧道的功能。

[PE1]bgp 65100

[PE1-bgp] ipv4-family vpn-instance vpna

[PE1-bgp-vpna] segment-routing ipv6 locator SRv6 evpn

[PE1-bgp-vpna] segment-routing ipv6 traffic-engineer best-effort evpn

[PE1-bgp-vpna] quit

[PE1-bgp] ipv6-family vpn-instance vpna6

[PE1-bgp-6-vpna6] segment-routing ipv6 locator SRv6 evpn

[PE1-bgp-6-vpna6] segment-routing ipv6 traffic-engineer best-effort evpn

[PE4-bgp] ipv4-family vpn-instance vpna

[PE4-bgp-vpna] segment-routing ipv6 locator SRv6 evpn

[PE4-bgp-vpna] segment-routing ipv6 traffic-engineer best-effort evpn

[PE4-bgp-vpna] quit

[PE4-bgp] ipv6-family vpn-instance vpna6

[PE4-bgp-6-vpna6] segment-routing ipv6 locator SRv6 evpn

[PE4-bgp-6-vpna6] segment-routing ipv6 traffic-engineer best-effort evpn
```

通过segment-routing ipv6 traffic-engineer best-effort evpn 命令配置VPN 实例中EVPN 路由迭代 到SRv6 Policy，同时使用SRv6 BE 隧道作为备份逃生路径。

```cli
#开启IS-IS 支持SRv6 Locator 对外发布功能。

[PE1]isis 1

[PE1-isis-1] segment-routing ipv6 locator SRv6 auto-sid-disable
```

这里以PE1 为例，其他设备的操作一致，不再赘述，由于手动分配了END SID，这里关闭自动 分配。

```cli
#以P1 为例，查看END SID。

[P1]display segment-routing ipv6 local-sid end forwarding
```

My Local-SID End Forwarding Table ---------------------------------

SID        : 2001:5::1/128                               FuncType : End Flavor     : PSP LocatorName: SRv6                                         LocatorID: 1

Total SID(s): 1 END SID 将会用于后续的SRv6 Policy 中的转发路径配置。

```cli
#查看PE1 上END.DT4 SID。

[PE1]display segment-routing ipv6 local-sid end-dt4 forwarding
```

My Local-SID End.DT4 Forwarding Table -------------------------------------

SID           : 2001:1::11/128                               FuncType : End.DT4 VPN Name   : vpna                                         VPN ID  : 3 LocatorName : SRv6                                         LocatorID: 1

Total SID(s): 1

```cli
#查看PE4 的EVPN 路由0:10.1.1.1:32 携带的SID 值。

[PE4]display bgp evpn all routing-table prefix-route 0:10.1.1.1:32 | include Prefix

BGP local router ID : 10.0.4.4
```

Local AS number : 65100 Prefix-sid: 2001:1::11

```cli
Route Type: 5 (Ip Prefix Route)
```

Ethernet Tag ID: 0, IP Prefix/Len: 10.1.1.1/32, ESI: 0000.0000.0000.0000.0000, GW IP Address: 0.0.0.0 Prefix-sid: 2001:1::11

```cli
Route Type: 5 (Ip Prefix Route)
```

Ethernet Tag ID: 0, IP Prefix/Len: 10.1.1.1/32, ESI: 0000.0000.0000.0000.0000, GW IP Address: 0.0.0.0 与预期一致，PE4 上收到的EVPN 路由中携带的Prefix SID 为PE1 上分配的END.DT4 SID。

```cli
#查看PE1 上END.DT6 SID。

[PE1-isis-1]display segment-routing ipv6 local-sid end-dt6 forwarding
```

My Local-SID End.DT6 Forwarding Table -------------------------------------

SID           : 2001:1::61/128                               FuncType : End.DT6 VPN Name   : vpna6                                        VPN ID  : 3 LocatorName: SRv6                                         LocatorID: 1

Total SID(s): 1

```cli
#查看PE4 的EVPN 路由0:[2002::1:1]:128 携带的SID 值。

[PE4]display bgp evpn all routing-table prefix-route 0:[2002::1:1]:128 | include Prefix

BGP local router ID : 10.0.4.4
```

Local AS number : 65100 Prefix-sid: 2001:1::61

```cli
Route Type: 5 (Ip Prefix Route)
```

Ethernet Tag ID: 0, IPv6 Prefix/Len: 2002::1:1/128, ESI: 0000.0000.0000.0000.0000, GW IPv6 Address: :: Prefix-sid: 2001:1::61

```cli
Route Type: 5 (Ip Prefix Route)
```

Ethernet Tag ID: 0, IPv6 Prefix/Len: 2002::1:1/128, ESI: 0000.0000.0000.0000.0000, GW IPv6 Address: :: 与预期一致，PE4 上收到的EVPN 路由中携带的Prefix SID 为PE1 上分配的END.DT6 SID。 步骤 5 配置SRv6 Policy、隧道策略 在PE1、PE4 上按规划配置2 条候选路径以及3 个Segment List，在SRv6 Policy 中调用该候选 路径。

```cli
#PE1 配置候选路径。

[PE1]segment-routing ipv6

[PE1-segment-routing-ipv6] segment-list PE1_PE4_VPNA_1

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_1] index 5 sid ipv6 2001:5::1

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_1] index 10 sid ipv6 2001:3::1

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_1] index 15 sid ipv6 2001:4::1

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_1] quit

[PE1-segment-routing-ipv6] segment-list PE1_PE4_VPNA_2

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_2] index 5 sid ipv6 2001:5::1

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_2] index 10 sid ipv6 2001:6::1

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_2] index 15 sid ipv6 2001:4::1

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_2] quit

[PE1-segment-routing-ipv6] segment-list PE1_PE4_VPNA_3

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_3] index 5 sid ipv6 2001:2::1

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_3] index 10 sid ipv6 2001:6::1

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_3] index 15 sid ipv6 2001:4::1

[PE1-segment-routing-ipv6-segment-list-PE1_PE4_VPNA_3] quit

[PE1-segment-routing-ipv6] srv6-te policy p1 endpoint 2001::4:4 color 100

[PE1-segment-routing-ipv6-policy-p1] candidate-path preference 100

[PE1-segment-routing-ipv6-policy-p1-path] segment-list PE1_PE4_VPNA_1 weight 2

[PE1-segment-routing-ipv6-policy-p1-path] segment-list PE1_PE4_VPNA_2 weight 1

[PE1-segment-routing-ipv6-policy-p1-path] quit

[PE1-segment-routing-ipv6-policy-p1] candidate-path preference 50

[PE1-segment-routing-ipv6-policy-p1-path] segment-list PE1_PE4_VPNA_3

[PE1-segment-routing-ipv6-policy-p1-path] quit
```

Segment List 1 经由P1、PE3 到达PE4 ，Segment List 2 经由P1、P2 到达PE4，Segment List 3 经 由PE2、P2 到达PE4，其中Segment List 1 和2 共同组成候选路径1，Segment List 3 组成候选 路径2。

```cli
#PE4 配置候选路径。

[PE4]segment-routing ipv6

[PE4-segment-routing-ipv6] segment-list PE4_PE1_VPNA_1

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_1] index 5 sid ipv6 2001:3::1

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_1] index 10 sid ipv6 2001:5::1

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_1] index 15 sid ipv6 2001:1::1

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_1] quit

[PE4-segment-routing-ipv6] segment-list PE4_PE1_VPNA_2

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_2] index 5 sid ipv6 2001:6::1

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_2] index 10 sid ipv6 2001:5::1

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_2] index 15 sid ipv6 2001:1::1

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_2] quit

[PE4-segment-routing-ipv6] segment-list PE4_PE1_VPNA_3

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_3] index 5 sid ipv6 2001:6::1

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_3] index 10 sid ipv6 2001:2::1

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_3] index 15 sid ipv6 2001:1::1

[PE4-segment-routing-ipv6-segment-list-PE4_PE1_VPNA_3] quit

[PE4-segment-routing-ipv6] srv6-te policy p1 endpoint 2001::1:1 color 100

[PE4-segment-routing-ipv6-policy-p1] candidate-path preference 100

[PE4-segment-routing-ipv6-policy-p1-path] segment-list PE4_PE1_VPNA_1 weight 2

[PE4-segment-routing-ipv6-policy-p1-path] segment-list PE4_PE1_VPNA_2 weight 1

[PE4-segment-routing-ipv6-policy-p1-path] quit

[PE4-segment-routing-ipv6-policy-p1] candidate-path preference 50

[PE4-segment-routing-ipv6-policy-p1-path] segment-list PE4_PE1_VPNA_3

[PE4-segment-routing-ipv6-policy-p1-path] quit
```

Segment List 1 经由PE3、P1 到达PE1 ，Segment List 2 经由P2、P1 到达PE1，Segment List 3 经 由P2、PE2 到达PE1，其中Segment List 1 和2 共同组成候选路径1，Segment List 3 组成候选 路径2。

```cli
#配置隧道选择策略。

[PE1]tunnel-policy p1

[PE1-tunnel-policy-p1] tunnel select-seq ipv6 srv6-te-policy load-balance-number 1

[PE4]tunnel-policy p1

[PE4-tunnel-policy-p1] tunnel select-seq ipv6 srv6-te-policy load-balance-number 1

#在VPN 实例中调用隧道选择策略。

[PE1]ip vpn-instance vpna

[PE1-vpn-instance-vpna]tnl-policy p1 evpn

[PE4]ip vpn-instance vpna

[PE4-vpn-instance-vpna]tnl-policy p1 evpn

[PE1] ip vpn-instance vpna6

[PE1-vpn-instance-vpna6] ipv6-family

[PE1-vpn-instance-vpna6-af-ipv6] tnl-policy p1 evpn

[PE4] ip vpn-instance vpna6

[PE4-vpn-instance-vpna6] ipv6-family

[PE4-vpn-instance-vpna6-af-ipv6] tnl-policy p1 evpn

#设备VPN 实例路由的默认Color 值。

[PE1]ip vpn-instance vpna

[PE1-vpn-instance-vpna] ipv4-family

[PE1-vpn-instance-vpna-af-ipv4] default-color 100 evpn

[PE4]ip vpn-instance vpna

[PE4-vpn-instance-vpna] ipv4-family

[PE4-vpn-instance-vpna-af-ipv4] default-color 100 evpn
```

为了让VPN 实例中的路由迭代到对应的SRv6 Policy 中，可选择使用路由策略的方式为路由打 上Color 值，或者设置本地VPN 实例中路由的默认Color 值，此处采用第二种方式。

```cli
[PE1] ip vpn-instance vpna6

[PE1-vpn-instance-vpna6] ipv6-family

[PE1-vpn-instance-vpna6-af-ipv6] default-color 100 evpn

[PE4] ip vpn-instance vpna6

[PE4-vpn-instance-vpna6] ipv6-family

[PE4-vpn-instance-vpna6-af-ipv6] default-color 100 evpn

#查看PE1、PE4 的VPN 实例IP 路由表。

[PE1]display ip routing-table vpn-instance vpna

Route Flags: R - relay, D - download to fib, T - to vpn-instance, B - black hole route

------------------------------------------------------------------------------ Routing Table: vpna Destinations : 4        Routes : 4

Destination/Mask    Proto   Pre  Cost        Flags NextHop       Interface

10.1.1.1/32    Direct  0    0             D   127.0.0.1       LoopBack1 10.1.4.4/32    IBGP    255  0             RD 2001::4:4       p1 127.0.0.0/8     Direct  0    0             D   127.0.0.1       InLoopBack0 255.255.255.255/32  Direct  0    0             D   127.0.0.1       InLoopBack0 路由已经迭代到逻辑接口（隧道策略）。

[PE4]display ip routing-table vpn-instance vpna

Route Flags: R - relay, D - download to fib, T - to vpn-instance, B - black hole route

------------------------------------------------------------------------------ Routing Table: vpna Destinations : 4        Routes : 4

Destination/Mask    Proto   Pre  Cost        Flags NextHop       Interface

10.1.1.1/32    IBGP    255  0             RD 2001::1:1       p1 10.1.4.4/32    Direct  0    0             D   127.0.0.1       LoopBack1 127.0.0.0/8     Direct  0    0             D   127.0.0.1       InLoopBack0 255.255.255.255/32  Direct  0    0             D   127.0.0.1       InLoopBack0

#查看PE1、PE4 的VPN 实例IPv6 路由的详细信息。

[PE1]display ipv6 routing-table vpn-instance vpna6 2002::4:4 verbose

Route Flags: R - relay, D - download to fib, T - to vpn-instance, B - black hole route

------------------------------------------------------------------------------ Routing Table: vpna6 Summary Count : 1

Destination   : 2002::4:4                               PrefixLength  : 128 NextHop     : 2001::4:4                               Preference    : 255 Neighbour    : 2001::5:5                               ProcessID    : 0 Label         : NULL                                   Protocol     : IBGP State         : Active Adv Relied                       Cost          : 0 Entry ID     : 0                                       EntryFlags    : 0x00000000 Reference Cnt : 0                                       Tag           : 0 Priority       : low                                     Age           : 105sec IndirectID     : 0x10000C5                               Instance    : RelayNextHop : ::                                      TunnelID     : 0x000000003400000001

Interface       : p1                                      Flags        : RD

[PE4]display ipv6 routing-table vpn-instance vpna6 2002::1:1 verbose

Route Flags: R - relay, D - download to fib, T - to vpn-instance, B - black hole route

------------------------------------------------------------------------------ Routing Table: vpna6 Summary Count : 1

Destination    : 2002::1:1                               PrefixLength  : 128 NextHop      : 2001::1:1                               Preference    : 255 Neighbour     : 2001::5:5                               ProcessID    : 0 Label          : NULL                                   Protocol     : IBGP State          : Active Adv Relied                       Cost          : 0 Entry ID      : 0                                       EntryFlags    : 0x00000000 Reference Cnt  : 0                                       Tag           : 0 Priority        : low                                     Age           : 188sec IndirectID      : 0x10000C4                               Instance    : RelayNextHop : ::                                      TunnelID      : 0x000000003400000001

Interface       : p1                                      Flags         : RD
```

IPv6 路由已经迭代到逻辑接口（隧道策略）。

```cli
#PE4 上查看路由10.1.1.1 详细信息。

[PE4]display ip routing-table vpn-instance vpna  10.1.1.1  verbose

Route Flags: R - relay, D - download to fib, T - to vpn-instance, B - black hole route

------------------------------------------------------------------------------ Routing Table: vpna Summary Count : 1

Destination: 10.1.1.1/32 Protocol   :  IBGP               Process ID   : 0
```

Preference   : 255                      Cost     : 0 NextHop : 2001::1:1           Neighbour    : 2001::5:5 State   : Active Adv Relied         Age     : 00h07m40s Tag   : 0                       Priority   : low Label  : NULL                  QoSInfo  : 0x0 IndirectID    : 0x100010C             Instance  : RelayNextHop : ::                       Interface : p1 TunnelID  : 0x000000003400000001    Flags : RD 该路由迭代到了Tunnel ID 为 0x000000003400000001 的隧道。

```cli
#查看PE4 上隧道信息。

[PE4]display tunnel-info all | include 0x000000003400000001

Info: It will take a long time if the content you searchis too much orthe string you input is too long, you can press CTRL_C to break. Tunnel ID                Type                Destination          Status ---------------------------------------------------------------------------------------- 0x000000003400000001  srv6tepolicy        2001::1:1            UP 该隧道为一条SRv6 Policy。 步骤 6 路径切换测试 开启头结点的故障感知功能，测试业务流量是否能切换到不同的Segment List。

#在PE1 上测试L3VPNv6 业务流量连通性。

[PE1]ping ipv6 vpn-instance vpna6 -a 2002::1:1 2002::4:4

PING 2002::4:4 : 56  data bytes, press CTRL_C to break Reply from 2002::4:4 bytes=56 Sequence=1 hop limit=64 time=11 ms Reply from 2002::4:4 bytes=56 Sequence=2 hop limit=64 time=3 ms Reply from 2002::4:4 bytes=56 Sequence=3 hop limit=64 time=3 ms Reply from 2002::4:4 bytes=56 Sequence=4 hop limit=64 time=3 ms Reply from 2002::4:4 bytes=56 Sequence=5 hop limit=64 time=2 ms

--- 2002::4:4 ping statistics---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max=2/4/11 ms IPv6 流量转发正常。

#PE1 上测试L3VPNv4 业务流量连通性。

[PE1]ping -vpn-instance vpna -a 10.1.1.1 10.1.4.4

PING 10.1.4.4: 56  data bytes, press CTRL_C to break Reply from 10.1.4.4: bytes=56 Sequence=1 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=2 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=3 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=4 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=5 ttl=255 time=1 ms

--- 10.1.4.4 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 1/1/1 ms 流量转发正常。

#为测试转发路径信息，需在两端头结点配置END.OP 类型opcode。

[PE1]segment-routing ipv6

[PE1-segment-routing-ipv6] locator SRv6

[PE1-segment-routing-ipv6-locator] opcode ::2 end-op

[PE4]segment-routing ipv6

[PE4-segment-routing-ipv6] locator SRv6

[PE4-segment-routing-ipv6-locator] opcode ::2 end-op

#在PE1 上通过tracert 命令测试SRv6 Policy 的连通性。

[PE1] tracert  srv6-te policy  policy-name  p1 end-op 2001:4::2
```

Trace Route srv6-te policy : 100  data bytes, press CTRL_C to break srv6-te policy's segment list: Preference: 100; Path Type: primary; Protocol-Origin: local; Originator: 0, 0.0.0.0; Discriminator: 100; Segment-List ID: 1; Xcindex: 1; end-op: 2001:4::2 TTL    Replier                Time    Type      SRH 0                                      Ingress   [SRH: 2001:5::1, 2001:3::1, 2001:4::1, 2001:4::2, SL=3] 1      2001::6                8 ms    Transit   [SRH: 2001:5::1, 2001:3::1, 2001:4::1, 2001:4::2, SL=3] 2      2001::12                3 ms    Transit   [SRH: 2001:5::1, 2001:3::1, 2001:4::1, 2001:4::2, SL=2] 3      2001:4::2               3 ms    Egress   [SRH: 2001:5::1, 2001:3::1, 2001:4::1, 2001:4::2, SL=1] srv6-te policy's segment list: Preference: 100; Path Type: primary; Protocol-Origin: local; Originator: 0, 0.0.0.0; Discriminator: 100; Segment-List ID: 4; Xcindex: 3; end-op: 2001:4::2 TTL    Replier                 Time    Type      SRH 0                                       Ingress   [SRH: 2001:5::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=3] 1      2001::6                 6 ms    Transit   [SRH: 2001:5::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=3] 2      2001::E                 2 ms    Transit   [SRH: 2001:5::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=2] 3      2001:4::2                3 ms    Egress   [SRH: 2001:5::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=1]

此时分别沿着Segment List 1、2 到达PE4。

```cli
#开启头端节点的故障感知功能。

[PE1]segment-routing ipv6

[PE1-segment-routing-ipv6] srv6-te-policy path verification enable

[PE1-segment-routing-ipv6] srv6-te policy p1

[PE1-segment-routing-ipv6-policy-p1] path verification enable

[PE4]segment-routing ipv6

[PE4-segment-routing-ipv6] srv6-te-policy path verification enable

[PE4-segment-routing-ipv6] srv6-te policy p1

[PE4-segment-routing-ipv6-policy-p1] path verification enable

#关闭PE3 的所有互联接口，模拟该节点故障。

[PE3]interface GigabitEthernet0/5/0

[PE3-GigabitEthernet0/5/0] shutdown

[PE3-GigabitEthernet0/5/0] quit

[PE3]interface GigabitEthernet0/5/1

[PE3-GigabitEthernet0/5/1] shutdown

[PE3-GigabitEthernet0/5/1] quit

#PE1 上测试业务流量连通性。

[PE1]ping -vpn-instance vpna -a 10.1.1.1 10.1.4.4

PING 10.1.4.4: 56  data bytes, press CTRL_C to break Reply from 10.1.4.4: bytes=56 Sequence=1 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=2 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=3 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=4 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=5 ttl=255 time=1 ms

--- 10.1.4.4 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 1/1/1 ms 业务流量正常。

[PE1]ping ipv6 vpn-instance vpna6 -a 2002::1:1 2002::4:4

PING 2002::4:4 : 56  data bytes, press CTRL_C to break Reply from 2002::4:4 bytes=56 Sequence=1 hop limit=64 time=8 ms Reply from 2002::4:4
```

bytes=56 Sequence=2 hop limit=64 time=2 ms Reply from 2002::4:4 bytes=56 Sequence=3 hop limit=64 time=3 ms Reply from 2002::4:4 bytes=56 Sequence=4 hop limit=64 time=2 ms Reply from 2002::4:4 bytes=56 Sequence=5 hop limit=64 time=2 ms

```cli
--- 2002::4:4 ping statistics---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max=2/3/8 ms IPv6 业务流量正常。
```

```cli
#再次在PE1 上通过tracert 命令测试SRv6 Policy 的连通性。

[PE1]tracert srv6-te policy policy-name p1 end-op 2001:4::2 -m 4
```

Trace Route srv6-te policy : 100  data bytes, press CTRL_C to break srv6-te policy's segment list: Preference: 100; Path Type: primary; Protocol-Origin: local; Originator: 0, 0.0.0.0; Discriminator: 100; Segment-List ID: 1; Xcindex: 0; end-op: 2001:4::2 TTL    Replier             Time    Type      SRH 0                                    Ingress   [SRH: 2001:5::1, 2001:3::1, 2001:4::1, 2001:4::2, SL=3]

```cli
1      ::                      *       Transit

2      ::                      *       Transit

3      ::                      *       Transit

4      ::                      *       Transit
```

srv6-te policy's segment list: Preference: 100; Path Type: primary; Protocol-Origin: local; Originator: 0, 0.0.0.0; Discriminator: 100; Segment-List ID: 4; Xcindex: 3; end-op: 2001:4::2 TTL    Replier               Time    Type      SRH 0                                     Ingress   [SRH: 2001:5::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=3] 1      2001::6               8 ms    Transit   [SRH: 2001:5::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=3] 2      2001::E               3 ms    Transit   [SRH: 2001:5::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=2] 3      2001:4::2              2 ms    Egress   [SRH: 2001:5::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=1]

使用-m 参数限制Tracert 检测的超时跳数。 可以看到此时Segment List 1 已经无法正常工作。

```cli
#关闭P1 的所有接口，模拟P1 节点故障。

[P1]interface GigabitEthernet0/5/0

[P1-GigabitEthernet0/5/0] shutdown

[P1-GigabitEthernet0/5/0] quit

[P1]interface GigabitEthernet0/5/1

[P1-GigabitEthernet0/5/1] shutdown

[P1-GigabitEthernet0/5/1] quit

[P1]interface GigabitEthernet0/5/2

[P1-GigabitEthernet0/5/2] shutdown

[P1-GigabitEthernet0/5/2] quit

#PE1 上测试业务流量连通性。

[PE1]ping -vpn-instance vpna -a 10.1.1.1 10.1.4.4

PING 10.1.4.4: 56  data bytes, press CTRL_C to break Reply from 10.1.4.4: bytes=56 Sequence=1 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=2 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=3 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=4 ttl=255 time=1 ms Reply from 10.1.4.4: bytes=56 Sequence=5 ttl=255 time=1 ms

--- 10.1.4.4 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 1/1/1 ms 业务流量依旧正常。

[PE1]ping ipv6 vpn-instance vpna6 -a 2002::1:1 2002::4:4

PING 2002::4:4 : 56  data bytes, press CTRL_C to break Reply from 2002::4:4 bytes=56 Sequence=1 hop limit=64 time=8 ms Reply from 2002::4:4 bytes=56 Sequence=2 hop limit=64 time=2 ms Reply from 2002::4:4 bytes=56 Sequence=3 hop limit=64 time=3 ms Reply from 2002::4:4 bytes=56 Sequence=4 hop limit=64 time=2 ms Reply from 2002::4:4 bytes=56 Sequence=5 hop limit=64 time=2 ms

--- 2002::4:4 ping statistics---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max=2/3/8 ms IPv6 业务流量正常。

#PE1 上通过tracert 命令测试SRv6 Policy 的连通性。

[PE1]tracert srv6-te policy policy-name p1 end-op 2001:4::2 -m 4
```

Trace Route srv6-te policy : 100  data bytes, press CTRL_C to break

srv6-te policy's segment list: Preference: 50; Path Type: primary; Protocol-Origin: local; Originator: 0, 0.0.0.0; Discriminator: 50; Segment-List ID: 3; Xcindex: 65; end-op: 2001:4::2 TTL    Replier             Time    Type      SRH 0                                   Ingress   [SRH: 2001:2::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=3] 1      2001::2             10 ms   Transit   [SRH: 2001:2::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=3] 2      2001::A              2 ms    Transit   [SRH: 2001:2::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=2] 3      2001:4::2            2 ms    Egress   [SRH: 2001:2::1, 2001:6::1, 2001:4::1, 2001:4::2, SL=1]

可以发现此时已经切换为通过第二条Candidate Path 中的Segment List 转发。

## 9.2.3 思考题

除了头结点故障感知功能，还可以通过什么方式检测Segment List 是否正常工作呢？

## 10 网络开放可编程
