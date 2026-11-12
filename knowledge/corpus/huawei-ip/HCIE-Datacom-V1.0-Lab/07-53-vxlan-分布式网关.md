---
doc_id: "hcie-datacom-v1.0-lab-07"
title: "5.3 VXLAN 分布式网关"
book: "HCIE-Datacom-V1.0-Lab"
book_title: "HCIE-Datacom V1.0 实验手册"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "lab"
source_pdf: "HCIE-Datacom V1.0 实验手册.pdf"
seq: 7
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 5.3 VXLAN 分布式网关

## 5.3.1 实验介绍

5.3.1.1 学习目标

- 配置VXLAN 分布式网关
- 解析VXLAN 分布式网关场景下同网段、跨网段报文转发流程

5.3.1.2 实验组网介绍

图5-3 VXLAN 分布式网关拓扑 设备互联方式如图所示，Border、Edge_1、Edge_2 上均创建Loopback0 接口，其IP 地址为 10.0.x.x（x 为设备编号，在配置步骤中会使用表格标明）。 Edge_1、Border 之间链路为Trunk 链路，放通VLAN12，Edge_1、Border 上创建VLANIF12 用于 三层互通，IP 地址配置为10.0.12.x/24。 Border、Edge_2 之间链路为Trunk 链路，放通VLAN23，Border、Edge_2 上创建VLANIF23 用于 三层互通，IP 地址配置为10.0.23.x/24。 Edge_1、Border、Edge_2 之间运行OSPF，使用Loopback0 接口IP 地址作为Router ID，在环回 口、互联接口上使能OSPF。 Edge_1、Edge_2 之间使用Loopback0 接口地址作为VXLAN NVE 接口源地址，传递BD10、20 的 流量。 ACC_1、ACC_2 作为接入交换机，通过Access 接口与PC1、PC2 互联，ACC_1 上将PC1 划分到

```cli
VLAN 100、ACC_2 上将PC2 分别划分到200，同时在ACC_2 上创建VLANIF100，模拟VLAN 100
```

内的终端。Edge_1、Edge_2 通过二层子接口与ACC_1、ACC_2 互联，Edge_1 终结VLAN100， Edge_2 终结VLAN100、200，并分别将子接口关联到BD10、BD20 中。 在Edge_1、Edge_2 上均创建VBDIF10、VBDIF20 作为BD10、BD20 内的终端网关（分布式网 关），在Edge_1、Edge_2 之间建立BGP EVPN 邻居关系传递Type2 路由以实现主机路由、 MAC 地址的传递。

## 5.3.2 实验任务配置

5.3.2.1 配置思路

1. 基础连通性配置。
2. 业务接入点配置。
3. 创建VBDIF 接口、配置NVE 接口。
4. 配置EVPN 实例、IP VPN 实例，并分别绑定到BD、VBDIF 接口中。
5. 建立BGP EVPN 对等体。

5.3.2.2 配置步骤

步骤 1 基础连通性配置 分别在Edge_1、Border、Edge_2 上按照下表完成互联接口IP 配置、OSPF 配置。 设备编号 设备名称 设备编号（X） Edge_1 Border Edge_2

```cli
#设备命名。
```

略

```cli
#Edge_1 VLAN、接口基础配置。

[Edge_1]vlan batch 12

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_1]interface GigabitEthernet0/0/1

[Edge_1-GigabitEthernet0/0/1] port link-type trunk

[Edge_1-GigabitEthernet0/0/1] port trunk allow-pass vlan 12

[Edge_1-GigabitEthernet0/0/1] quit

[Edge_1]interface Vlanif12

[Edge_1-Vlanif12] ip address 10.0.12.1 255.255.255.0

[Edge_1-Vlanif12] quit

[Edge_1]interface LoopBack 0

[Edge_1-LoopBack0] ip address 10.0.1.1 32

[Edge_1-LoopBack0] quit

# Border VLAN、接口基础配置。

[Border]vlan batch 12 23

Info: This operation may take a few seconds. Please wait for a moment...done.

[Border]interface GigabitEthernet0/0/23

[Border-GigabitEthernet0/0/23] port link-type trunk

[Border-GigabitEthernet0/0/23] port trunk allow-pass vlan 12

[Border-GigabitEthernet0/0/23] quit

[Border]interface GigabitEthernet0/0/24

[Border-GigabitEthernet0/0/24] port link-type trunk

[Border-GigabitEthernet0/0/24] port trunk allow-pass vlan 23

[Border-GigabitEthernet0/0/24] quit

[Border]interface Vlanif12

[Border-Vlanif12] ip address 10.0.12.2 255.255.255.0

[Border-Vlanif12] quit

[Border]interface Vlanif23

[Border-Vlanif23] ip address 10.0.23.2 255.255.255.0

[Border-Vlanif23] quit

[Border]interface LoopBack 0

[Border-LoopBack0] ip address 10.0.2.2 32

[Border-LoopBack0] quit

#Edge_2 VLAN、接口基础配置。

[Edge_2]vlan 23

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_2]

[Edge_2]interface GigabitEthernet0/0/1

[Edge_2-GigabitEthernet0/0/1] port link-type trunk

[Edge_2-GigabitEthernet0/0/1] port trunk allow-pass vlan 23

[Edge_2-GigabitEthernet0/0/1] quit

[Edge_2]

[Edge_2]interface Vlanif 23

[Edge_2-Vlanif23] ip address 10.0.23.3 255.255.255.0

[Edge_2-Vlanif23] quit

[Edge_2]

[Edge_2]interface LoopBack 0

[Edge_2-LoopBack0] ip address 10.0.3.3 32

[Edge_2-LoopBack0] quit

#互联接口连通性测试。

[Border]ping 10.0.12.1

PING 10.0.12.1: 56  data bytes, press CTRL_C to break Reply from 10.0.12.1: bytes=56 Sequence=1 ttl=254 time=1 ms Reply from 10.0.12.1: bytes=56 Sequence=2 ttl=254 time=1 ms Reply from 10.0.12.1: bytes=56 Sequence=3 ttl=254 time=1 ms Reply from 10.0.12.1: bytes=56 Sequence=4 ttl=254 time=1 ms Reply from 10.0.12.1: bytes=56 Sequence=5 ttl=254 time=1 ms

--- 10.0.12.1 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 1/1/1 ms

[Border]ping 10.0.23.3

PING 10.0.23.3: 56  data bytes, press CTRL_C to break Request time out Reply from 10.0.23.3: bytes=56 Sequence=2 ttl=254 time=1 ms Reply from 10.0.23.3: bytes=56 Sequence=3 ttl=254 time=1 ms Reply from 10.0.23.3: bytes=56 Sequence=4 ttl=254 time=1 ms Reply from 10.0.23.3: bytes=56 Sequence=5 ttl=254 time=1 ms

--- 10.0.23.3 ping statistics ---

5 packet(s) transmitted

4 packet(s) received
```

20.00% packet loss round-trip min/avg/max = 1/1/1 ms 在Border 上测试与Edge_1、Edge_2 的VLANIF 接口连通性。

```cli
#Edge_1 OSPF 配置。

[Edge_1]ospf 1 router-id 10.0.1.1

[Edge_1-ospf-1] area 0.0.0.0

[Edge_1-ospf-1-area-0.0.0.0] network 10.0.1.1 0.0.0.0

[Edge_1-ospf-1-area-0.0.0.0] network 10.0.12.0 0.0.0.255

[Edge_1-ospf-1-area-0.0.0.0] quit

#使用Loopback0 接口作为Router ID，在Loopback0 接口、VLANIF12 接口上使能OSPF。

#Border OSPF 配置。

[Border]ospf 1 router-id 10.0.2.2

[Border-ospf-1] area 0.0.0.0

[Border-ospf-1-area-0.0.0.0] network 10.0.2.2 0.0.0.0

[Border-ospf-1-area-0.0.0.0] network 10.0.12.0 0.0.0.255

[Border-ospf-1-area-0.0.0.0] network 10.0.23.0 0.0.0.255

[Border-ospf-1-area-0.0.0.0] quit

#使用Loopback0 接口作为Router ID，在Loopback0 接口、VLANIF12、VLANIF23 接口上使能

OSPF。

#Edge_2 OSPF 配置。

[Edge_2]ospf 1 router-id 10.0.3.3

[Edge_2-ospf-1] area 0.0.0.0

[Edge_2-ospf-1-area-0.0.0.0] network 10.0.3.3 0.0.0.0

[Edge_2-ospf-1-area-0.0.0.0] network 10.0.23.0 0.0.0.255

[Edge_2-ospf-1-area-0.0.0.0] quit

#Border 上检查OSPF 邻居关系、OSPF 路由表。

[Border]display ospf peer

OSPF Process 1 with Router ID 10.0.2.2

Neighbors

Area 0.0.0.0 interface 10.0.12.2(Vlanif12)'s neighbors Router ID: 10.0.1.1         Address: 10.0.12.1 State: Full  Mode:Nbr is  Slave  Priority: 1 R: 10.0.12.1  BDR: 10.0.12.2  MTU: 0 Dead timerdue in 36  sec Retrans timerinterval: 5 Neighbor is up for 00:01:57 Authentication Sequence: [ 0 ]

Neighbors

Area 0.0.0.0 interface 10.0.23.2(Vlanif23)'s neighbors Router ID: 10.0.3.3         Address: 10.0.23.3 State: Full  Mode:Nbr is  Master  Priority: 1 DR: 10.0.23.2  BDR: 10.0.23.3  MTU: 0 Dead timerdue in 28  sec Retrans timerinterval: 5 Neighbor is up for 00:01:24 Authentication Sequence: [ 0 ]

OSPF 邻居关系已经建立完成。

#Border 上检查OSPF 路由。

[Border]display ospf routing

OSPF Process 1 with Router ID 10.0.2.2

Routing Tables

Routing for Network Destination        Cost  Type       NextHop         AdvRouter       Area 10.0.2.2/32        0     Stub       10.0.2.2        10.0.2.2        0.0.0.0 10.0.12.0/24       1     Transit    10.0.12.2       10.0.2.2        0.0.0.0 10.0.23.0/24       1     Transit    10.0.23.2       10.0.2.2        0.0.0.0 10.0.1.1/32        1     Stub       10.0.12.1       10.0.1.1        0.0.0.0 10.0.3.3/32        1     Stub       10.0.23.3       10.0.3.3        0.0.0.0

Total Nets: 5 Intra Area: 5  Inter Area: 0  ASE: 0  NSSA: 0 Border 上
```

已经学习到了Edge_1、Edge_2 的Loopback0 接口生成的路由。

```cli
#测试Edge_1、Edge_2 之间Loopback0 接口的连通性。

[Edge_1]ping -a 10.0.1.1 10.0.3.3

PING 10.0.3.3: 56  data bytes, press CTRL_C to break Reply from 10.0.3.3: bytes=56 Sequence=1 ttl=253 time=1 ms Reply from 10.0.3.3: bytes=56 Sequence=2 ttl=253 time=1 ms Reply from 10.0.3.3: bytes=56 Sequence=3 ttl=253 time=1 ms Reply from 10.0.3.3: bytes=56 Sequence=4 ttl=253 time=1 ms Reply from 10.0.3.3: bytes=56 Sequence=5 ttl=253 time=1 ms

--- 10.0.3.3 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 1/1/1 ms Edge_1、Edge_2 之间的Loopback0 接口可以正常通信。
```

步骤 2 业务接入点配置 在Edge_1、2 上完成业务接入点配置，创建子接口与ACC_1、2 互通，终结VLAN100、200， 并与BD10、20 进行关联。 ACC_1、ACC_2 与PC 连接的接口配置为Access 接口，PVID 分别设置为100、200，与Edge_1、

# 2 互联的接口配置为Trunk 接口，放通VLAN100、200。

同时在ACC_2 上创建VLANIF100，配置其IP 地址为192.168.100.2/24，模拟终端用户。

```cli
#Edge_1 配置。

[Edge_1]bridge-domain 10

[Edge_1-bd10] vxlan vni 1000

[Edge_1-bd10] quit

[Edge_1]bridge-domain 20

[Edge_1-bd20] vxlan vni 2000

[Edge_1-bd20] quit

[Edge_1]vcmp role silent

[Edge_1]interface GigabitEthernet0/0/24

[Edge_1-GigabitEthernet0/0/24]port link-type trunk

Info: This operation may take a few seconds. Please wait for a moment...

[Edge_1-GigabitEthernet0/0/24]quit

[Edge_1]interface GigabitEthernet0/0/24.100 mode l2

[Edge_1-GigabitEthernet0/0/24.100] encapsulation dot1q vid 100

Info: This operation may take a few seconds. Please wait for a moment...

[Edge_1-GigabitEthernet0/0/24.100] bridge-domain 10

[Edge_1-GigabitEthernet0/0/24.100] quit
```

默认VCMP 配置会让子接口无法配置Dot1q 封装终结VLAN，需配置vcmp role silent 命令。

```cli
#Edge_2 配置。

[Edge_2]bridge-domain 10

[Edge_2-bd10] vxlan vni 1000

[Edge_2-bd10] quit

[Edge_2]bridge-domain 20

[Edge_2-bd20] vxlan vni 2000

[Edge_2-bd20] quit

[Edge_2]vcmp role silent

[Edge_2]interface GigabitEthernet0/0/24

[Edge_2-GigabitEthernet0/0/24]port link-type trunk

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_2-GigabitEthernet0/0/24]quit

[Edge_2]interface GigabitEthernet0/0/24.200 mode l2

[Edge_2-GigabitEthernet0/0/24.200] encapsulation dot1q vid 200

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_2-GigabitEthernet0/0/24.200] bridge-domain 20

[Edge_2-GigabitEthernet0/0/24.200] quit

[Edge_2]interface GigabitEthernet0/0/24.100 mode l2

[Edge_2-GigabitEthernet0/0/24.100] encapsulation dot1q vid 100

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_2-GigabitEthernet0/0/24.100] bridge-domain 10

[Edge_2-GigabitEthernet0/0/24.100] quit
```

创建BD10、20，常见子接口终结VLAN100、200。

```cli
#ACC_1 配置。

[ACC_1]vlan batch 100 200

Info: This operation may take a few seconds. Please wait for a moment...done.

[ACC_1-vlan100]interface GigabitEthernet0/0/24

[ACC_1-GigabitEthernet0/0/24] port link-type access

[ACC_1-GigabitEthernet0/0/24] port default vlan 100

[ACC_1-GigabitEthernet0/0/24] quit

[ACC_1]interface GigabitEthernet0/0/1

[ACC_1-GigabitEthernet0/0/1] port link-type trunk

[ACC_1-GigabitEthernet0/0/1] port trunk allow-pass vlan 100 200

[ACC_1-GigabitEthernet0/0/1] quit

#ACC_2 配置。

[ACC_2] vlan batch 100 200

Info: This operation may take a few seconds. Please wait for a moment...done.

[ACC_2] interface GigabitEthernet0/0/23

[ACC_2-GigabitEthernet0/0/23] port link-type access

[ACC_2-GigabitEthernet0/0/23] port default vlan 200

[ACC_2-GigabitEthernet0/0/23] quit

[ACC_2] interface GigabitEthernet0/0/1

[ACC_2-GigabitEthernet0/0/1] port link-type trunk

[ACC_2-GigabitEthernet0/0/1] port trunk allow-pass vlan 100 200

[ACC_2-GigabitEthernet0/0/1] quit

[ACC_2] interface vlanif100

[ACC_2-Vlanif100] ip address 192.168.100.2 255.255.255.0

[ACC_2-Vlanif100] quit

[ACC_2] ip route-static 192.168.200.0 255.255.255.0 192.168.100.254
```

创建VLANIF100，通过静态路由指定前往192.168.200.0/24 的下一跳为192.168.100.254。 步骤 3 创建VBDIF 接口、配置NVE 接口 在Edge_1、Edge_2 上创建NVE 接口，其中头端复制列表协议选择为BGP。

```cli
#Edge_1 上配置NVE 接口。

[Edge_1] interface Nve1

[Edge_1-Nve1] source 10.0.1.1

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_1-Nve1] vni 1000 head-end peer-list protocol bgp

[Edge_1-Nve1] vni 2000 head-end peer-list protocol bgp

[Edge_1-Nve1] quit

#Edge_2 上配置NVE 接口。

[Edge_2]interface Nve1

[Edge_2-Nve1] source 10.0.3.3

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_2-Nve1] vni 1000 head-end peer-list protocol bgp

[Edge_2-Nve1] vni 2000 head-end peer-list protocol bgp

[Edge_2-Nve1] quit

#Edge_1 创建VBDIF10、VBDIF20。

[Edge_1]interface Vbdif10

[Edge_1-Vbdif10] ip address 192.168.100.254 255.255.255.0

[Edge_1-Vbdif10] mac-address 0000-5e00-0110

[Edge_1-Vbdif10] arp collect host enable

[Edge_1-Vbdif10] quit

[Edge_1]interface Vbdif20

[Edge_1-Vbdif20] ip address 192.168.200.254 255.255.255.0

[Edge_1-Vbdif20] mac-address 0000-5e00-0120

[Edge_1-Vbdif20] arp collect host enable

[Edge_1-Vbdif20] quit

#Edge_2 创建VBDIF10、VBDIF20。

[Edge_2]interface Vbdif10

[Edge_2-Vbdif10] ip address 192.168.100.254 255.255.255.0

[Edge_2-Vbdif10] mac-address 0000-5e00-0110

[Edge_2-Vbdif10] arp collect host enable

[Edge_2-Vbdif10] quit

[Edge_2]interface Vbdif20

[Edge_2-Vbdif20] ip address 192.168.200.254 255.255.255.0

[Edge_2-Vbdif20] mac-address 0000-5e00-0120

[Edge_2-Vbdif20] arp collect host enable

[Edge_2-Vbdif20] quit

#在Edge_1、Edge_2 上均创建VBDIF10、20，为保证主机在不同的汇聚交换机下进行迁移时， 网关的MAC 地址保持不变，且主机无需重新进行ARP 表项学习，在上述配置中，需手动修改 接口的MAC 地址分别为0000-5e00-0110、0000-5e00-0120，并在VBDIF 接口下开启arp collect host enable 命令，由主机的ARP 信息生成Type2 路由，通过BGP EVPN 进行传递。 步骤 4 配置EVPN 实例、IP VPN 实例，并分别绑定到BD、VBDIF 接口中 在Edge_1、Edge_2 上创建EVPN 实例、IP VPN 实例，分别绑定到BD、VBDIF 接口下，为了保 证EVPN 路由、IP 路由的正常相互学习，EVPN、IP VPN 实例的规划如下： Edge_1 EVPN 实例规划 EVPN实例名称 BD RD Export RT Import RT Edge_1_BD_10 21:10 213:10、313:12 213:10 Edge_1_BD_20 21:20 213:20、313:12 213:20 Edge_2 EVPN 实例规划 EVPN实例名称 BD RD Export RT Import RT
```

```cli
Edge_2_BD_10 23:10 213:10、313:12 213:10 Edge_2_BD_20 23:20 213:20、313:12 213:20 Edge_1 IP VPN 实例规划 VPN实例名称 VBDIF L3 VNI RD Export RT Import RT Edge_1_VPN_10_20 31:12 313:12 313:12 Edge_2 VPN 实例规划 VPN实例名称 VBDIF L3 VNI RD Export RT Import RT Edge_2_VPN_10_20 33:12 313:12 313:12 EVPN 实例规划解释（在以下规划中，Edge_1、Border、Edge_2 的编号分别为1，2，3）： EVPN 实例规划解释： 1. RD：2Y：Z，其中2 代表该RD 值为EVPN 实例，Y 为设备编号，Z 代表BD 值，以Edge_1 的BD10 为例，其对应的EVPN 实例RD 值为21:10。 2. Import RT 值：213:Z，213 的第一个2 代表EVPN 实例，13 代表该RT 值用于Edge_1、 Edge_2 之间传递EVPN 路由，Z 代表BD 值，以Edge_1 的BD10 为例，其对应的EVPN 实 例Export RT 值为213:10。 3. Export RT 值：除了与Import RT 值相同的213:Z 之外，还存在一个用于将IP 路由引入到IP VPN 实例路由表中的313:12。
```

```cli
IP VPN 实例规划解释：

1. RD：3X：12，第一个3 代表IP VPN 实例，X 代表设备编号，12 代表VBDIF10、VBDIF20 所 使用。 2. Export RT、Import RT：313:12，3 代表IP VPN 实例，13 代表Edge_1、Edge_2 之间使用，
```

## 12 代表VBDIF10、VBDIF20。

3. L3 VNI：1020，代表BD10、20 之间通信使用的三层VNI。

```cli
#Edge_1 创建EVPN 实例并绑定到BD 中。

[Edge_1]evpn vpn-instance Edge_1_BD_10 bd-mode

[Edge_1-evpn-instance-Edge_1_BD_10] route-distinguisher 21:10

[Edge_1-evpn-instance-Edge_1_BD_10] vpn-target 213:10 export-extcommunity

[Edge_1-evpn-instance-Edge_1_BD_10] vpn-target 313:12 export-extcommunity

[Edge_1-evpn-instance-Edge_1_BD_10] vpn-target 213:10 import-extcommunity

[Edge_1-evpn-instance-Edge_1_BD_10] quit

[Edge_1]evpn vpn-instance Edge_1_BD_20 bd-mode

[Edge_1-evpn-instance-Edge_1_BD_20] route-distinguisher 21:20

[Edge_1-evpn-instance-Edge_1_BD_20] vpn-target 213:20 export-extcommunity

[Edge_1-evpn-instance-Edge_1_BD_20] vpn-target 313:12 export-extcommunity

[Edge_1-evpn-instance-Edge_1_BD_20] vpn-target 213:20 import-extcommunity

[Edge_1-evpn-instance-Edge_1_BD_20] quit

[Edge_1]bridge-domain 10

[Edge_1-bd10]evpn binding vpn-instance Edge_1_BD_10

[Edge_1-bd10]quit

[Edge_1]bridge-domain 20

[Edge_1-bd20]evpn binding vpn-instance Edge_1_BD_20

[Edge_1-bd20]quit

#Edge_2 创建EVPN 实例并绑定到BD 中。

[Edge_2]evpn vpn-instance Edge_2_BD_10 bd-mode

[Edge_2-evpn-instance-Edge_2_BD_10] route-distinguisher 23:10

[Edge_2-evpn-instance-Edge_2_BD_10] vpn-target 213:10 export-extcommunity

[Edge_2-evpn-instance-Edge_2_BD_10] vpn-target 313:12 export-extcommunity

[Edge_2-evpn-instance-Edge_2_BD_10] vpn-target 213:10 import-extcommunity

[Edge_2-evpn-instance-Edge_2_BD_10] quit

[Edge_2]evpn vpn-instance Edge_2_BD_20 bd-mode

[Edge_2-evpn-instance-Edge_2_BD_20] route-distinguisher 23:20

[Edge_2-evpn-instance-Edge_2_BD_20] vpn-target 213:20 export-extcommunity

[Edge_2-evpn-instance-Edge_2_BD_20] vpn-target 313:12 export-extcommunity

[Edge_2-evpn-instance-Edge_2_BD_20] vpn-target 213:20 import-extcommunity

[Edge_2-evpn-instance-Edge_2_BD_20] quit

[Edge_2]bridge-domain 10

[Edge_2-bd10]evpn binding vpn-instance Edge_2_BD_10

[Edge_2-bd10]quit

[Edge_2]bridge-domain 20

[Edge_2-bd20]evpn binding vpn-instance Edge_2_BD_20

[Edge_2-bd20]quit

#Edge_1 创建IP VPN 实例并绑定到VBDIF 中。

[Edge_1]ip vpn-instance Edge_1_VPN_10_20

[Edge_1-vpn-instance-Edge_1_VPN_10_20] ipv4-family

[Edge_1-vpn-instance-Edge_1_VPN_10_20-af-ipv4] route-distinguisher 31:12

[Edge_1-vpn-instance-Edge_1_VPN_10_20-af-ipv4] vpn-target 313:12 export-extcommunity evpn

[Edge_1-vpn-instance-Edge_1_VPN_10_20-af-ipv4] vpn-target 313:12 import-extcommunity evpn

[Edge_1-vpn-instance-Edge_1_VPN_10_20-af-ipv4] quit

[Edge_1-vpn-instance-Edge_1_VPN_10_20] vxlan vni 1020

[Edge_1-vpn-instance-Edge_1_VPN_10_20] quit

[Edge_1]interface Vbdif 10

[Edge_1-Vbdif10]ip binding vpn-instance Edge_1_VPN_10_20

Info: IGMP/MLD snooping configurations in the corresponding VLAN are cleared! Info: All IPv4 related configurations on this interface are removed! Info: All IPv6 related configurations on this interface are removed!

[Edge_1-Vbdif10]quit

[Edge_1]interface Vbdif 20

[Edge_1-Vbdif20]ip binding vpn-instance Edge_1_VPN_10_20

Info: IGMP/MLD snooping configurations in the corresponding VLAN are cleared! Info: All IPv4 related configurations on this interface are removed! Info: All IPv6 related configurations on this interface are removed!

[Edge_1-Vbdif20]quit

[Edge_1]interface Vbdif10

[Edge_1-Vbdif10] ip address 192.168.100.254 255.255.255.0

[Edge_1-Vbdif10] quit

[Edge_1]interface Vbdif20

[Edge_1-Vbdif20] ip address 192.168.200.254 255.255.255.0

[Edge_1-Vbdif20] quit
```

注意，绑定IP VPN 实例之后，接口下的IP 地址配置会被清空，需要重新配置IP 地址。

```cli
#Edge_2 创建IP VPN 实例并绑定到VBDIF 中。

[Edge_2]ip vpn-instance Edge_2_VPN_10_20

[Edge_2-vpn-instance-Edge_2_VPN_10_20] ipv4-family

[Edge_2-vpn-instance-Edge_2_VPN_10_20-af-ipv4] route-distinguisher 33:12

[Edge_2-vpn-instance-Edge_2_VPN_10_20-af-ipv4] vpn-target 313:12 export-extcommunity

[Edge_2-vpn-instance-Edge_2_VPN_10_20-af-ipv4] vpn-target 313:12 export-extcommunity evpn

[Edge_2-vpn-instance-Edge_2_VPN_10_20-af-ipv4] vpn-target 313:12 import-extcommunity

[Edge_2-vpn-instance-Edge_2_VPN_10_20-af-ipv4] vpn-target 313:12 import-extcommunity evpn

[Edge_2-vpn-instance-Edge_2_VPN_10_20-af-ipv4] quit

[Edge_2-vpn-instance-Edge_2_VPN_10_20] vxlan vni 1020

[Edge_2-vpn-instance-Edge_2_VPN_10_20] quit

[Edge_2]interface Vbdif 10

[Edge_2-Vbdif10]ip binding vpn-instance Edge_2_VPN_10_20

Info: IGMP/MLD snooping configurations in the corresponding VLAN are cleared! Info: All IPv4 related configurations on this interface are removed! Info: All IPv6 related configurations on this interface are removed!

[Edge_2-Vbdif10]quit

[Edge_2]interface Vbdif 20

[Edge_2-Vbdif20]ip binding vpn-instance Edge_2_VPN_10_20

Info: IGMP/MLD snooping configurations in the corresponding VLAN are cleared! Info: All IPv4 related configurations on this interface are removed! Info: All IPv6 related configurations on this interface are removed!

[Edge_2-Vbdif20]quit

[Edge_2]interface Vbdif10

[Edge_2-Vbdif10] ip address 192.168.100.254 255.255.255.0

[Edge_2-Vbdif10] quit

[Edge_2]interface Vbdif20

[Edge_2-Vbdif20] ip address 192.168.200.254 255.255.255.0

[Edge_2-Vbdif20] quit
```

注意，绑定IP VPN 实例之后，接口下的IP 地址配置会被清空，需要重新配置IP 地址。 步骤 5 建立BGP EVPN 对等体 在Edge_1、Edge_2 之间建立IBGP 对等体关系，使用Loopback 接口作为BGP 会话源地址，在 EVPN 地址族中开启发布IRB 路由，在VPN 实例中开启通告L2VPN EVPN 路由。

```cli
#Edge_1 上配置BGP EVPN。

[Edge_1] bgp 100

[Edge_1-bgp] router-id 10.0.1.1

[Edge_1-bgp] peer 10.0.3.3 as-number 100

[Edge_1-bgp] peer 10.0.3.3 connect-interface LoopBack0

[Edge_1-bgp] ipv4-family vpn-instance Edge_1_VPN_10_20

[Edge_1-bgp-Edge_1_VPN_10_20] advertise l2vpn evpn

[Edge_1-bgp-Edge_1_VPN_10_20] quit

[Edge_1-bgp] l2vpn-family evpn

[Edge_1-bgp-af-evpn] policy vpn-target

[Edge_1-bgp-af-evpn] peer 10.0.3.3 enable

[Edge_1-bgp-af-evpn] peer 10.0.3.3 advertise irb

[Edge_1-bgp-af-evpn] quit

#Edge_2 上配置BGP EVPN。

[Edge_2] bgp 100

[Edge_2-bgp] router-id 10.0.3.3

[Edge_2-bgp] peer 10.0.1.1 as-number 100

[Edge_2-bgp] peer 10.0.1.1 connect-interface LoopBack0

[Edge_2-bgp] ipv4-family vpn-instance Edge_2_VPN_10_20

[Edge_2-bgp-Edge_2_VPN_10_20] advertise l2vpn evpn

[Edge_2-bgp-Edge_2_VPN_10_20] quit

[Edge_2-bgp] l2vpn-family evpn

[Edge_2-bgp-af-evpn] policy vpn-target

[Edge_2-bgp-af-evpn] peer 10.0.1.1 enable

[Edge_2-bgp-af-evpn] peer 10.0.1.1 advertise irb

[Edge_2-bgp-af-evpn] quit

#分别在Edge_1、Edge_2 上查看BGP EVPN 对等体状态。

[Edge_1]display bgp evpn peer
```

Status codes: * - Dynamic

```cli
BGP local router ID : 10.0.1.1
```

Local AS number : 100 Total number of peers : 1                Peers in established state : 1 Total number of dynamic peers : 0

```cli
Peer           V          AS  MsgRcvd  MsgSent OutQ   Up/Down      State    PrefRcv
```

10.0.3.3        4         100        4        4     0        00:00:04     Established       2

```cli
[Edge_2]display bgp evpn peer
```

Status codes: * - Dynamic

```cli
BGP local router ID : 10.0.3.3
```

Local AS number : 100 Total number of peers : 1                Peers in established state : 1 Total number of dynamic peers : 0

```cli
Peer           V          AS  MsgRcvd  MsgSent OutQ   Up/Down      State    PrefRcv
```

10.0.1.1        4         100        4        4     0        00:00:08     Established       2 Edge_1 与Edge_2 之间的BGP EVPN 对等体关系已经正常建立。 步骤 6 结果验证与通信过程查看 在PC1 上Ping 同网段的192.168.100.2（Edge_2 的VLANIF 100）、跨网段的PC2，查看BGP EVPN 如何建立VXLAN 隧道、头端复制列表，分析同子网数据转发过程、跨子网数据转发过 程。

```cli
#首先使用PC1、PC2、VLANIF100 Ping 各自的网关。
```

C:\Users\PC1>ping 192.168.100.254

正在 Ping 192.168.100.254 具有 32 字节的数据: 来自 192.168.100.254 的回复: 字节=32 时间<1ms TTL=254 来自 192.168.100.254 的回复: 字节=32 时间<1ms TTL=254 来自 192.168.100.254 的回复: 字节=32 时间<1ms TTL=254 来自 192.168.100.254 的回复: 字节=32 时间<1ms TTL=254

192.168.100.254 的 Ping 统计信息:

数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 0ms，最长 = 0ms，平均 = 0ms

C:\Users\PC2>ping 192.168.200.254

正在 Ping 192.168.200.254 具有 32 字节的数据: 来自 192.168.200.254 的回复: 字节=32 时间<1ms TTL=254 来自 192.168.200.254 的回复: 字节=32 时间<1ms TTL=254 来自 192.168.200.254 的回复: 字节=32 时间<1ms TTL=254 来自 192.168.200.254 的回复: 字节=32 时间<1ms TTL=254

192.168.200.254 的 Ping 统计信息:

数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 0ms，最长 = 0ms，平均 = 0ms

```cli
<ACC_2>ping 192.168.100.254 PING 192.168.100.254: 56  data bytes, press CTRL_C to break Reply from 192.168.100.254: bytes=56 Sequence=1 ttl=254 time=1 ms Reply from 192.168.100.254: bytes=56 Sequence=2 ttl=254 time=1 ms Reply from 192.168.100.254: bytes=56 Sequence=3 ttl=254 time=1 ms Reply from 192.168.100.254: bytes=56 Sequence=4 ttl=254 time=1 ms Reply from 192.168.100.254: bytes=56 Sequence=5 ttl=254 time=1 ms

--- 192.168.100.254 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 1/1/1 ms 都可以正常和对应的VBDIF 网关进行通信。

#查看Edge_1 的VXLAN 隧道信息。

[Edge_1]display vxlan tunnel
```

Tunnel ID      Source                        Destination                  State     Type -------------------------------------------------------------------------------------------------------------------- 4026531841      10.0.1.1                       10.0.3.3                      up        l2 dynamic 3                 10.0.1.1                       10.0.3.3                      up        l3 dynamic -------------------------------------------------------------------------------------------------------------------- Number of vxlan tunnel : Total: 2    Static: 0    L2 dynamic: 1    L3 dynamic: 1 已经与Edge_2 之间建立了二层以及三层的VXLAN 隧道。

```cli
#查看Edge_1 上的Type3 BGP EVPN 路由。

<Edge_1> display bgp evpn all routing-table inclusive-route
```

Local AS number : 100

```cli
BGP  Local router ID is 10.0.1.1
```

Status codes: * - valid, > - best, d - damped, x - best external, a - add path, h - history, i - internal, s - suppressed, S - Stale Origin : i - IGP, e - EGP, ? - incomplete

EVPN address family: Number of Inclusive Multicast Routes: 4

```cli
Route Distinguisher: 21:10
```

Network(EthTagId/IpAddrLen/OriginalIp)                 NextHop *>     0:32:10.0.1.1                                              0.0.0.0

```cli
Route Distinguisher: 21:20
```

Network(EthTagId/IpAddrLen/OriginalIp)                 NextHop *>     0:32:10.0.1.1                                              0.0.0.0

```cli
Route Distinguisher: 23:10
```

Network(EthTagId/IpAddrLen/OriginalIp)                 NextHop *>i    0:32:10.0.3.3                                               10.0.3.3

```cli
Route Distinguisher: 23:20
```

Network(EthTagId/IpAddrLen/OriginalIp)                 NextHop *>i    0:32:10.0.3.3                                               10.0.3.3 可以看到存在两条来自10.0.3.3 的Type 3 路由，在收到Type 3 路由之后，设备会建立二层头 端复制列表。

```cli
#查看Edge_1 的VXLAN 对等体信息。

[Edge_1]display vxlan peer
```

Vni ID      Source                               Destination                     Type -------------------------------------------------------------------------------------------------------------- 1000         10.0.1.1                             10.0.3.3                         l2 dynamic 2000         10.0.1.1                             10.0.3.3                         l2 dynamic -              10.0.1.1                             10.0.3.3                         l3 dynamic -------------------------------------------------------------------------------------------------------------- Number of peers : Total: 3   Static: 0   L2 dynamic: 2   L3 dynamic: 1 分别建立了二层以及三层的VXLAN 对等体。

```cli
#测试PC1 与Edge_2 的VLANIF100 的连通性。
```

C:\Users\PC1>ping 192.168.100.2

正在 Ping 192.168.100.2 具有 32 字节的数据: 来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=254 来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=254 来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=254

来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=254

192.168.100.2 的 Ping 统计信息:

数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 0ms，最长 = 0ms，平均 = 0ms 可以正常进行通信。

```cli
#在PC1 上查看192.168.100.2 的ARP 信息（已省略不相关条目）。
```

C:\Users\PC1>arp -a

接口: 192.168.100.1 --- 0xc Internet 地址         物理地址              类型

192.168.100.2         b0-08-75-0e-fb-db     动态

192.168.100.2 对应的MAC 地址为b0-08-75-0e-fb-db。

```cli
#在Edge_1 上查看BD10 中的MAC 地址条目。

<Edge_1>display mac-address bridge-domain 10 ------------------------------------------------------------------------------- MAC Address      VLAN/VSI/BD             Learned-From     Type ------------------------------------------------------------------------------- 000c-29b3-efea     -/-/10                  GE0/0/24.100     dynamic b008-750e-fbdb    -/-/10                  10.0.3.3            dynamic

------------------------------------------------------------------------------- Total items displayed = 2 Edge_1 上MAC 地址条目：b008-750e-fbdb 为通过远端VTEP（10.0.3.3）学习而来。
```

此时，如果PC1 发送一个单播帧给192.168.100.2，该帧到达Edge_1 后，Edge_1 查看其目的 MAC 地址，在对应的BD 中查找该MAC 地址（BD10），发现所匹配的结果为学习自远端VTEP 的MAC 地址条目，且该条目由通过BGP EVPN 学习的路由生成。

```cli
#查看Edge_1 的BGP EVPN Type 2 路由。

<Edge_1>display bgp evpn all routing-table mac-route
```

Local AS number :100

```cli
BGP Local router ID is 10.0.1.1
```

Status codes: * - valid, > - best, d - damped, h - history, i - internal, s - suppressed, S - Stale

Origin : i - IGP, e - EGP, ? - incomplete

EVPN address family: Number of Mac Routes : 3

```cli
Route Distinguisher: 21:10
```

Network(EthTagId/MacAddrLen/MacAddr/IpAddrLen/IpAddr)  NextHop *>     0:48:000c-29b3-efea:32:192.168.100.1                          0.0.0.0

```cli
Route Distinguisher: 23:10
```

Network(EthTagId/MacAddrLen/MacAddr/IpAddrLen/IpAddr)  NextHop *>i    0:48:b008-750e-fbdb:32:192.168.100.2                          10.0.3.3

```cli
Route Distinguisher: 23:20
```

Network(EthTagId/MacAddrLen/MacAddr/IpAddrLen/IpAddr)  NextHop *>i    0:48:000c-292e-b4a3:32:192.168.200.2                          10.0.3.3 VPN-Instance Edge_1_VPN_10_20, Router ID 10.0.1.1: Total Number of Routes: 2 Network           NextHop        MED        LocPrf    PrefVal Path/Ogn *>i  192.168.100.2/32   10.0.3.3                       100        0      ? *>i  192.168.200.2/32   10.0.3.3                       100        0      ?

可以看到一条来自10.0.3.3 的Type 2 路由，其中包含了192.168.100.2 对应的MAC 地址。

```cli
#查看该路由条目的明细信息。

<Edge_1>display bgp evpn all routing-table mac-route 0:48:b008-750e-fbdb:32:192.168.100.2

BGP local router ID : 10.0.1.1
```

Local AS number : 100

Total routes of Route Distinguisher(23:10): 1

```cli
BGP routing table entry information of 0:48:b008-750e-fbdb:32:192.168.100.2:
```

Label information (Received/Applied): 1000 1020/NULL From: 10.0.3.3 (10.0.3.3)

```cli
Route Duration: 00h29m22s
```

Relay IP Nexthop: 10.0.12.2 Relay IP Out-Interface: Vlanif12 Original nexthop: 10.0.3.3 Qos information : 0x0 Ext-Community:RT <213 : 10>, RT <313 : 12>, Tunnel Type <VxLan(8)>, MAC Mobility <flag:0 seq:1 res:0>, Router's MAC <80e1-bf0e-5650> AS-path Nil, origin incomplete, localpref 100, pref-val 0, valid, internal, best, select, pre 255, IGP cost 2

```cli
Route Type: 2 (MAC Advertisement Route)
```

Ethernet Tag ID:0, MAC Address/Len: b008-750e-fbdb/48, IP Address/Len: 192.168.100.2/32, ESI: 0000.0000.0000.0000.0000 Not advertised to any peer yet

```cli
#在Label 信息中可以看到实际携带的VXLAN VNI，第一个为L2 VNI（1000），第二个为L3 VNI （1020），在RT 中可以看到213 : 10、313 : 12。 该路由为Edge_2 根据BD10 域内的主机ARP 信息生成（VBDIF 下开启arp collect host enable 命 令之后，会将学习到的下连终端ARP 信息转换成EVPN Type2 路由对外通告），其中包含主机
```

IP 地址、主机MAC 地址、L2 VNI、L3 VNI。
Edge_1 此时要执行的是L2 转发，即根据MAC 地址表查找结果将数据帧封装在VXLAN 头部中 转发到Edge_2，此时VXLAN 报文中携带的VNI 为L2 VNI，即BD10 中绑定的VNI（1000）。

```cli
#查看PC1 与PC2 的通信过程。
```

C:\Users\PC1>ping 192.168.200.2

正在 Ping 192.168.200.2 具有 32 字节的数据: 来自 192.168.200.2 的回复: 字节=32 时间<1ms TTL=126 来自 192.168.200.2 的回复: 字节=32 时间<1ms TTL=126 来自 192.168.200.2 的回复: 字节=32 时间<1ms TTL=126 来自 192.168.200.2 的回复: 字节=32 时间<1ms TTL=126

192.168.200.2 的 Ping 统计信息:

数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 0ms，最长 = 0ms，平均 = 0ms PC1、PC2 可以正常通信。

```cli
#查看Edge_1 的IP 路由表。

<Edge_1>display ip routing-table vpn-instance Edge_1_VPN_10_20

Route Flags: R - relay, D - download to fib, T - to vpn-instance

------------------------------------------------------------------------------ Routing Tables: Edge_1_VPN_10_20 Destinations : 6        Routes : 6

Destination/Mask    Proto   Pre  Cost      Flags NextHop         Interface

192.168.100.0/24  Direct  0    0          D   192.168.100.254  Vbdif10 192.168.100.2/32  IBGP   255  0          RD  10.0.3.3          VXLAN 192.168.100.254/32  Direct  0    0          D   127.0.0.1         Vbdif10 192.168.200.0/24  Direct  0    0          D   192.168.200.254  Vbdif20 192.168.200.2/32  IBGP   255  0          RD  10.0.3.3          VXLAN 192.168.200.254/32  Direct  0    0          D   127.0.0.1         Vbdif20
```

PC1 与PC2 通信属于跨子网通信，PC1 发往PC2 的报文首先会被发到PC1 的网关（Edge_1 的 VBDIF10），此时数据帧的目的MAC 地址为0000-5e00-0110，为Edge_1 自身接口的MAC 地 址，Edge_1 查看报文的目的IP 地址，发现并非自身接口IP 地址，判断需继续转发该报文。由 于接收该报文的三层接口（VBDIF10）与IP VPN 实例Edge_1_VPN_10_20 绑定，此时Edge_1 会 在该IP VPN 实例中查找路由，查找到匹配的路由为一条下一跳为10.0.3.3 的IBGP 路由，出接 口为VXLAN 逻辑接口，此时Edge_1 会将数据帧封装在VXLAN 头部中发往10.0.3.3，但此时 VXLAN 头部中的VNI 值需要查看BGP EVPN 路由条目确定。

```cli
#查看Edge_1 的BGP VPNv4 路由。

<Edge_1>display bgp vpnv4 vpn-instance Edge_1_VPN_10_20 routing-table 192.168.200.2

BGP local router ID : 10.0.1.1
```

Local AS number : 100

VPN-Instance Edge_1_VPN_10_20, Router ID 10.0.1.1: Paths:   1 available, 1 best, 1 select

```cli
BGP routing table entry information of 192.168.200.2/32:
```

Label information (Received/Applied): 1020/NULL From: 10.0.3.3 (10.0.3.3)

```cli
Route Duration: 00h48m07s
```

Relay Tunnel Out-Interface: VXLAN Relay token: 0x3 Original nexthop: 10.0.3.3 Qos information : 0x0 Ext-Community:RT <213 : 20>, RT <313 : 12>, Tunnel Type <VxLan(8)>, MAC Mobility <flag:0 seq:3 res:0>, Router's MAC <80e1-bf0e-5650> AS-path Nil, origin incomplete, localpref 100, pref-val 0, valid, internal, best, select, active, pre 255 Not advertised to any peer yet 在BGP VPNv4 条目中可以看到路由条目192.168.200.2 的Label（L3 VNI）值为1020，Router’s Mac 为80e1-bf0e-5650，该VNI 值以及MAC 地址分别为重新封装数据帧的VXLAN VNI 值以及 内部数据帧的目的MAC 地址。 接下来继续查看BGP EVPN Type2 路由。

```cli
#查看Edge_1 的BGP EVPN Type 2 路由。

<Edge_1>display bgp evpn all routing-table mac-route
```

Local AS number :100

```cli
BGP Local router ID is 10.0.1.1
```

Status codes: * - valid, > - best, d - damped, h - history, i - internal, s - suppressed, S - Stale

Origin : i - IGP, e - EGP, ? - incomplete

EVPN address family: Number of Mac Routes : 3

```cli
Route Distinguisher: 21:10
```

Network(EthTagId/MacAddrLen/MacAddr/IpAddrLen/IpAddr)  NextHop *>     0:48:000c-29b3-efea:32:192.168.100.1                   0.0.0.0

```cli
Route Distinguisher: 23:10
```

Network(EthTagId/MacAddrLen/MacAddr/IpAddrLen/IpAddr)  NextHop *>i    0:48:b008-750e-fbdb:32:192.168.100.2                  10.0.3.3

```cli
Route Distinguisher: 23:20
```

Network(EthTagId/MacAddrLen/MacAddr/IpAddrLen/IpAddr)  NextHop *>i    0:48:000c-292e-b4a3:32:192.168.200.2                   10.0.3.3

VPN-Instance Edge_1_VPN_10_20, Router ID 10.0.1.1: Total Number of Routes: 2 Network           NextHop        MED        LocPrf    PrefVal Path/Ogn

*>i  192.168.100.2/32   10.0.3.3                   100        0      ? *>i  192.168.200.2/32   10.0.3.3                   100        0      ?

可以看到一条来自10.0.3.3 的Type2 路由，其中包含了主机MAC 地址（000c-292e-b4a3）、主 机IP 地址（192.168.200.2），并且RD 值为23:20。

```cli
#继续查看Type2 路由 0:48:000c-292e-b4a3:32:192.168.200.2 的详细信息。

<Edge_1>display bgp evpn all routing-table mac-route 0:48:000c-292e-b4a3:32:192.168.200.2

BGP local router ID : 10.0.1.1
```

Local AS number : 100

Total routes of Route Distinguisher(23:20): 1

```cli
BGP routing table entry information of 0:48:000c-292e-b4a3:32:192.168.200.2:
```

Label information (Received/Applied): 2000 1020/NULL From: 10.0.3.3 (10.0.3.3)

```cli
Route Duration: 00h52m19s
```

Relay IP Nexthop: 10.0.12.2 Relay IP Out-Interface: Vlanif12 Original nexthop: 10.0.3.3 Qos information : 0x0 Ext-Community:RT <213 : 20>, RT <313 : 12>, Tunnel Type <VxLan(8)>, MAC Mobility <flag:0 seq:3 res:0>, Router's MAC <80e1-bf0e-5650> AS-path Nil, origin incomplete, localpref 100, pref-val 0, valid, internal, best, select, pre 255, IGP cost 2

```cli
Route Type: 2 (MAC Advertisement Route)
```

Ethernet Tag ID:0, MAC Address/Len: 000c-292e-b4a3/48, IP Address/Len: 192.168.200.2/32, ESI: 0000.0000.0000.0000.0000 Not advertised to any peer yet

可以看到该路由同时携带了L2、L3 VNI，以及Edge_2 上EVPN 实例中绑定的Export RT 值， Edge_1 在收到之后会和本地的EVPN 实例Import RT、IP VPN 实例Import RT 值进行对比，能够 与BD20 所绑定的EVPN 实例、IP VPN 实例Edge_1_VPN_10_20 匹配，并且该路由中携带了主 机IP 地址、主机MAC 地址，为此Edge_1 会将主机MAC 地址学习到BD20 域的MAC 的地址表 中，同时将其中携带的主机IP 地址学习到对应的IP VPN 实例路由表中。 通过RT 值的控制，Edge_1 通过Type2 IRB 路由完成MAC 条目学习、IP 路由学习的过程。 此时，PC1 与PC2 通信的数据帧经由Edge_1 进行封装后，在VXLAN 头部中携带的VNI 值为 1020，用于告知Edge_2 报文所属的IP VPN 实例，内层数据帧目的MAC 则为BGP EVPN 路由中 所携带的Router MAC，该MAC 地址与设备的桥MAC 地址类似，用于标志设备自身。

```cli
#查看Edge_2 的IP VPN 实例Edge_2_VPN_10_20 对应的路由表。

[Edge_2]display ip routing-table vpn-instance Edge_2_VPN_10_20

Route Flags: R - relay, D - download to fib, T - to vpn-instance

------------------------------------------------------------------------------ Routing Tables: Edge_2_VPN_10_20 Destinations : 5        Routes : 5

Destination/Mask    Proto   Pre  Cost      Flags NextHop         Interface

192.168.100.0/24   Direct  0    0           D   192.168.100.254   Vbdif10 192.168.100.1/32   IBGP    255  0          RD  10.0.1.1            VXLAN 192.168.100.254/32  Direct  0    0           D   127.0.0.1          Vbdif10 192.168.200.0/24   Direct  0    0           D   192.168.200.254   Vbdif20 192.168.200.254/32  Direct  0    0           D   127.0.0.1          Vbdif20 Edge_2 收到来自Edge_1 的报文之后，根据VXLAN 头部的VNI 值以及内层数据帧的目的MAC 地址判断自身需要对内层数据帧执行三层查表转发，在VNI 1020 对应的IP VPN 实例中进行路 由查找，结果为一条直连路由。

#在Edge_2 上查看ARP、MAC 地址表。

[Edge_2]display arp all | in 192.168.200.2

IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE        INTERFACE   VPN-INSTANCE

VLAN/CEVLAN(SIP/DIP)

------------------------------------------------------------------------------ 192.168.200.254 0000-5e00-0120            I -            Vbdif20         Edge_2_VPN_10_20 192.168.200.2   000c-292e-b4a3 4         D-0          GE0/0/24.200  Edge_2_VPN_10_20 ------------------------------------------------------------------------------ Total:7         Dynamic:3       Static:0    Interface:4

[Edge_2]display mac-address 000c-292e-b4a3

------------------------------------------------------------------------------- MAC Address    VLAN/VSI/BD            Learned-From       Type ------------------------------------------------------------------------------- 000c-292e-b4a3  -/-/20                 GE0/0/24.200       dynamic

------------------------------------------------------------------------------- Total items displayed = 1
```

根据查询结果，将数据帧重新封装，由GE0/0/24.200 子接口发送出去，交由ACC_2 进行处 理。 此时该数据帧的目的MAC 地址为PC2 的MAC 地址。 至此，PC1 至PC2 的报文转发过程结束，在整个过程中，Ingress VTEP（Edge_1）、Egress VTEP（Edge_2）都进行了 L3 查表，根据路由表查询结果进行转发，在VTEP 之间转发报文时内 层数据帧携带的VNI 为L3 VNI。

## 5.3.3 思考题

```cli
#在分布式网关中，同网段之间通信是否可以实现VTEP 之间执行三层转发？
```
