---
doc_id: "hcie-datacom-v1.0-lab-06"
title: "5.2 VXLAN 集中式网关"
book: "HCIE-Datacom-V1.0-Lab"
book_title: "HCIE-Datacom V1.0 实验手册"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "lab"
source_pdf: "HCIE-Datacom V1.0 实验手册.pdf"
seq: 6
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 5.2 VXLAN 集中式网关

## 5.2.1 实验介绍

5.2.1.1 学习目标

- 实现配置VXLAN 集中式网关完成跨三层互通
- 阐述VXLAN 集中式网关方式下报文转发流程

5.2.1.2 实验组网介绍

图5-2 VXLAN 集中式网关拓扑 设备互联方式如图所示，Border、Edge_1、Edge_2 上均创建Loopback0 接口，其IP 地址为 10.0.x.x（x 为设备编号，在配置步骤中会使用表格标明）。 Edge_1、Border 之间链路为Trunk 链路，放通VLAN12，Edge_1、Border 上创建VLANIF12 用于 三层互通，IP 地址配置为10.0.12.x/24。 Border、Edge_2 之间链路为Trunk 链路，放通VLAN23，Border、Edge_2 上创建VLANIF23 用于 三层互通，IP 地址配置为10.0.23.x/24。 Edge_1、Border、Edge_2 之间运行OSPF，使用Loopback0 接口IP 地址作为Router ID，在环回 口、互联接口上使能OSPF。

Edge_1、Border、Edge_2 之间使用Loopback0 接口地址作为VXLAN NVE 接口源地址，其中 Edge_1、Border 之间建立VXLAN 隧道，用于传递BD10 的流量；Border、Edge_2 之间建立 VXLAN 隧道，用于传递BD20 的流量。 ACC_1、ACC_2 作为接入交换机，通过Access 接口与PC1、PC2 互联，分别将PC 划分到

```cli
VLAN100、200 中，Edge_1、Border 通过二层子接口与ACC_1、ACC_2 互联，分别终结

VLAN100、200，并分别将子接口关联到BD10、BD20 中。
```

Border 上创建VBDIF10、VBDIF20 作为BD10、BD20 内终端的网关，并实现BD10、BD20 内终 端的跨三层互通。

## 5.2.2 实验任务配置

5.2.2.1 配置思路

1. 基础连通性配置
2. 业务接入点配置
3. 配置Border 与Edge_1、Border 与Edge_2 之间的静态VXLAN 隧道
4. 创建VBDIF 接口

5.2.2.2 配置步骤

步骤 1 基础连通性配置 分别在Edge_1、Border、Edge_2 上按照下表完成互联接口IP 配置、OSPF 配置。

```cli
#设备编号 设备名称 设备编号（X） Edge_1 Border Edge_2

#设备命名。
```

略

```cli
#Edge_1 VLAN、接口基础配置。

[Edge_1]vlan 100

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_1]

[Edge_1]interface GigabitEthernet0/0/1

[Edge_1-GigabitEthernet0/0/1] port link-type trunk

[Edge_1-GigabitEthernet0/0/1] port trunk allow-pass vlan 12

[Edge_1-GigabitEthernet0/0/1] quit

[Edge_1]

[Edge_1]interface Vlanif12

[Edge_1-Vlanif12] ip address 10.0.12.1 255.255.255.0

[Edge_1-Vlanif12] quit

[Edge_1]

[Edge_1]interface LoopBack 0

[Edge_1-LoopBack0] ip address 10.0.1.1 32

[Edge_1-LoopBack0] quit

# Border VLAN、接口基础配置。

[Border]vlan batch 12 23

Info: This operation may take a few seconds. Please wait for a moment...done.

[Border]

[Border]interface GigabitEthernet0/0/23

[Border-GigabitEthernet0/0/23] port link-type trunk

[Border-GigabitEthernet0/0/23] port trunk allow-pass vlan 12

[Border-GigabitEthernet0/0/23] quit

[Border]interface GigabitEthernet0/0/24

[Border-GigabitEthernet0/0/24] port link-type trunk

[Border-GigabitEthernet0/0/24] port trunk allow-pass vlan 23

[Border-GigabitEthernet0/0/24] quit

[Border]

[Border]interface Vlanif12

[Border-Vlanif12] ip address 10.0.12.2 255.255.255.0

[Border-Vlanif12] quit

[Border]interface Vlanif23

[Border-Vlanif23] ip address 10.0.23.2 255.255.255.0

[Border-Vlanif23] quit

[Border]

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

Area 0.0.0.0 interface 10.0.23.2(Vlanif23)'s neighbors Router ID: 10.0.3.3         Address: 10.0.23.3 State: Full  Mode:Nbr is  Master  Priority: 1 DR: 10.0.23.2  BDR: 10.0.23.3  MTU: 0 Dead timerdue in 28  sec Retrans timerinterval: 5

Neighbor is up for 00:01:24 Authentication Sequence: [ 0 ]

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

步骤 2 业务接入点配置 在Edge_1、2 上完成业务接入点配置，创建子接口与ACC_1、2 互通，分别终结VLAN100、 200，并与BD10、20 进行关联。

ACC_1、ACC_2 与PC 连接的接口配置为Access 接口，PVID 分别设置为100、200，与 Edge_1、2 互联的接口配置为Trunk 接口，分别放通VLAN100、200。

```cli
#Edge_1 配置。

[Edge_1]bridge-domain 10

[Edge_1-bd10] vxlan vni 1000

[Edge_1-bd10] quit

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

#ACC_1 配置。

[ACC_1]vlan 100

Info: This operation may take a few seconds. Please wait for a moment...done.

[ACC_1-vlan100]interface GigabitEthernet0/0/24

[ACC_1-GigabitEthernet0/0/24] port link-type access

[ACC_1-GigabitEthernet0/0/24] port default vlan 100

[ACC_1-GigabitEthernet0/0/24] quit

[ACC_1]interface GigabitEthernet0/0/1

[ACC_1-GigabitEthernet0/0/1] port link-type trunk

[ACC_1-GigabitEthernet0/0/1] port trunk allow-pass vlan 100

[ACC_1-GigabitEthernet0/0/1] quit

#ACC_2 配置。

[ACC_2]vlan 200

Info: This operation may take a few seconds. Please wait for a moment...d

[ACC_2]interface GigabitEthernet0/0/23

[ACC_2-GigabitEthernet0/0/23] port link-type access

[ACC_2-GigabitEthernet0/0/23] port default vlan 200

[ACC_2-GigabitEthernet0/0/23] quit

[ACC_2]interface GigabitEthernet0/0/1

[ACC_2-GigabitEthernet0/0/1] port link-type trunk

[ACC_2-GigabitEthernet0/0/1] port trunk allow-pass vlan 200

[ACC_2-GigabitEthernet0/0/1] quit
```

步骤 3 静态VXLAN 隧道、VBDIF 配置 在Edge_1、Border、Edge_2 之间使用Loopback0 接口地址作为NVE 接口源地址建立VXLAN 隧 道，在Edge_1、Border 之间建立VXLAN 隧道传递BD10 的数据，在Border、Edge_2 之间建立 VXLAN 隧道传递BD20 的数据。 在Border 上建立VBDIF10、VBDIF20 作为PC1、PC2 的网关。

```cli
#在Edge_1、Border 上配置NVE 接口实现静态VXLAN 隧道。

[Edge_1] interface Nve1

[Edge_1-Nve1] source 10.0.1.1

[Edge_1-Nve1] vni 1000 head-end peer-list 10.0.2.2

[Edge_1-Nve1] quit
```

注意Border 上需先创建BD10。

```cli
[Border]bridge-domain 10

[Border-bd10] vxlan vni 1000

[Border-bd10] quit

[Border]interface Nve1

[Border-Nve1] source 10.0.2.2

[Border-Nve1] vni 1000 head-end peer-list 10.0.1.1

[Border-Nve1] quit

#在Edge_2、Border 上配置NVE 接口实现静态VXLAN 隧道。

[Edge_2]interface Nve1

[Edge_2-Nve1] source 10.0.3.3

[Edge_2-Nve1] vni 2000 head-end peer-list 10.0.2.2

[Edge_2-Nve1] quit
```

注意Border 上需先创建BD20。

```cli
[Border] bridge-domain 20

[Border-bd20] vxlan vni 2000

[Border-bd20] quit

[Border] interface Nve 1

[Border-Nve1] vni 2000 head-end peer-list 10.0.3.3

[Border-Nve1] quit

#分别在Edge_1、2 以及Border 上检查VXLAN 隧道状态。

[Edge_1]display  vxlan tunnel
```

Tunnel ID      Source   Destination  State     Type --------------------------------------------------------------------------------------------------------------------

```cli
4026531842     10.0.1.1  10.0.2.2     up         static

-------------------------------------------------------------------------------------------------------------------- Number of vxlan tunnel : Total: 1    Static: 1    L2 dynamic: 0    L3 dynamic: 0
```

```cli
[Edge_2]display vxlan tunnel
```

Tunnel ID      Source   Destination  State     Type --------------------------------------------------------------------------------------------------------------------

```cli
4026531842     10.0.3.3  10.0.2.2       up       static

-------------------------------------------------------------------------------------------------------------------- Number of vxlan tunnel : Total: 1    Static: 1    L2 dynamic: 0    L3 dynamic: 0
```

```cli
[Border]display vxlan tunnel
```

Tunnel ID      Source   Destination  State     Type --------------------------------------------------------------------------------------------------------------------

```cli
4026531841     10.0.2.2  10.0.1.1       up       static

4026531842     10.0.2.2  10.0.3.3       up       static

-------------------------------------------------------------------------------------------------------------------- Number of vxlan tunnel : Total: 2    Static: 2    L2 dynamic: 0    L3 dynamic: 0 三台设备上的VXLAN 隧道状态都为Up。
```

```cli
#在Border 上创建VBDIF10、20，并按照规划配置其IP 地址。

[Border]interface Vbdif10

[Border-Vbdif10] ip address 192.168.100.254 255.255.255.0

[Border-Vbdif10] quit

[Border]interface Vbdif20

[Border-Vbdif20] ip address 192.168.200.254 255.255.255.0

[Border-Vbdif20] quit
```

步骤 4 结果验证 在PC1 Ping PC2，并观察分析整个转发过程。

```cli
#PC1、PC2 分别测试与网关地址的连通性。
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
#在Border 上查看VBDIF10、20 的接口MAC 地址。

[Border]display interface Vbdif 10 | in Hardware

IP Sending Frames' Format is PKTFMT_ETHNT_2, Hardware address is 9400-b049-9efb

[Border]display interface Vbdif 20 | in Hardware

IP Sending Frames' Format is PKTFMT_ETHNT_2, Hardware address is 9400-b049-9ef6
```

与VLANIF 接口类似，VBDIF10、20 具有相同的MAC 地址，都为9400-b049-9ef6。

```cli
#在Edge_1 上查看BD10 内的MAC 地址表项。

[Edge_1]display  mac-address bridge-domain 10

------------------------------------------------------------------------------- MAC Address    VLAN/VSI/BD   Learned-From       Type ------------------------------------------------------------------------------- 000c-29b3-efea    -/-/10        GE0/0/24.100       dynamic 9400-b049-9efb   -/-/10        10.0.2.2              dynamic ------------------------------------------------------------------------------- Total items displayed = 2
```

此时Edge_1 上BD10 内存在2 条MAC 地址条目，分别为从子接口GE0/0/24.100、远端VTEP （10.0.2.2）学习到，两个MAC 地址分别为PC1 的网卡MAC、Border 上VBDIF10 接口的MAC 地 址。

```cli
#捕获Border 从GE0/0/23 口接收的VXLAN 报文。

[Border]capture-packet interface GigabitEthernet 0/0/23 destination file VXLAN.cap inbound packet-num 50
```

此时Border 不再是转发VXLAN 报文的中间设备，而是VXLAN 报文的终结设备，使用过滤条件 进行报文抓取将会无法匹配到任何报文。

```cli
#在PC1 Ping PC2。
```

C:\Users\PC1>ping 192.168.200.2

正在 Ping 192.168.200.2 具有 32 字节的数据: 来自 192.168.200.2 的回复: 字节=32 时间<1ms TTL=127 来自 192.168.200.2 的回复: 字节=32 时间<1ms TTL=127 来自 192.168.200.2 的回复: 字节=32 时间<1ms TTL=127 来自 192.168.200.2 的回复: 字节=32 时间<1ms TTL=127

192.168.200.2 的 Ping 统计信息:

数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 0ms，最长 = 0ms，平均 = 0ms 可以正常通信。

```cli
#设备完成抓包后会输出如下回显。

-----------------packet getting report----------------- file: flash:/VXLAN.cap packets getting: interface GigabitEthernet0/0/24 ACL: 3000

vlan: -  cvlan: -
```

car: 64kbps timeout: 60s packets: 10 (expected) 10 (actual) length without tunnel header: 64 (expected) ------------------------------------------------------- Capture-packet 抓取到的报文所在路径已在回显中告知，可通过FTP、SFTP 的方式下载该抓 包，设备开启FTP、SFTP 方式可参考产品手册中相关配置。

```cli
#查看Border 上抓包结果。

Ethernet II, Src: d4:46:49:82:34:8d (d4:46:49:82:34:8d), Dst: 94:00:b0:49:9e:fd (94:00:b0:49:9e:fd) 802.1Q Virtual LAN, PRI: 0, DEI: 0, ID: 12 Internet Protocol Version 4, Src: 10.0.1.1, Dst: 10.0.2.2 User Datagram Protocol, Src Port: 256, Dst Port: 4789 Virtual eXtensible Local Area Network Flags: 0x0800, VXLAN Network ID (VNI) Group Policy ID: 0 VXLAN Network Identifier (VNI): 1000 Reserved: 0 Ethernet II, Src: 00:0c:29:b3:ef:ea, Dst: 94:00:b0:49:9e:fb Internet Protocol Version 4, Src: 192.168.100.1, Dst: 192.168.200.2 Internet Control Message Protocol 手动过滤查看VXLAN 报文。 该报文封装了PC1 Ping PC2 的原始数据帧，经由Edge_1 封装VXLAN 头部（VNI 值1000），使 用Edge_1 的NVE 1 接口源地址作为IP 头部的源IP 地址（10.0.1.1），使用Border 的NVE 1 接 口源地址作为IP 头部的目的IP 地址（10.0.2.2）。 Border 收到该数据帧之后，通过数据帧的目的MAC 地址（94:00:b0:49:9e:fd，为自身VLANIF12 的接口MAC 地址），判断出该数据帧应由自身终结。 解封装之后查看目的IP 地址，发现为10.0.2.2，为本地Loopback0 接口IP 地址，继续解封装查 看上层数据，发现为VXLAN 封装，查看VXLAN 头部的VNI，根据VNI 1000 判断内层数据帧需 要在BD10 域内查表转发。 在BD10 域中查看内层数据帧目的MAC 地址（94:00:b0:49:9e:fb），该MAC 地址为VBDIF10 接 口MAC 地址，因此Border 判断该数据帧需要VBDIF10 处理，继续解封装查看上层数据，发现 内层数据帧中的网络层目的IP 为192.168.200.2，非本地接口IP 地址，此时Border 将会执行 L3 查表转发，查看本地的IP 路由表。
#查看Border 上的IP 路由表。

[Border]display ip routing-table 192.168.200.2

Route Flags: R - relay, D - download to fib, T - to vpn-instance

------------------------------------------------------------------------------ Routing Table: Public
```

```cli
Summary Count : 1 Destination/Mask    Proto   Pre  Cost      Flags NextHop         Interface
```

192.168.200.0/24   Direct  0    0           D   192.168.200.254   Vbdif20

通过命令display ip routing-table192.168.200.2，查看Border 对目的IP 地址为192.168.200.2 的 报文执行路由查表的结果，可以看到匹配结果为一条由VBDIF20 接口产生的直连路由，此时 Border 将会根据ARP 表项、MAC 地址表项确定转发接口。

```cli
#查看Border 的ARP、MAC 地址表项。

[Border]display arp | include 192.168.200.2

IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE        INTERFACE   VPN-INSTANCE

VLAN/CEVLAN(SIP/DIP)

------------------------------------------------------------------------------

192.168.200.254 9400-b049-9ef6              I -               Vbdif20

192.168.200.2   000c-292e-b4a3   11        D-0             Vbdif20

------------------------------------------------------------------------------ Total:9         Dynamic:4       Static:0    Interface:5

[Border]display mac-address 000c-292e-b4a3

------------------------------------------------------------------------------- MAC Address    VLAN/VSI/BD    Learned-From       Type ------------------------------------------------------------------------------- 000c-292e-b4a3   -/-/20          10.0.3.3             dynamic

------------------------------------------------------------------------------- Total items displayed = 1 通过查询ARP 表项、MAC 地址表项可知，数据帧需要重新封装并发给远端VTEP 10.0.3.3。
```

此时Border 将会重新封装内层数据帧（替换源目MAC 地址），将数据帧通过VXLAN 静态隧道 发往Edge_2。

## 5.2.3 思考题

Edge_2 收到来自Border 的VXLAN 报文（封装着PC1 Ping PC2 的原始数据帧）之后，将会如何 处理？
