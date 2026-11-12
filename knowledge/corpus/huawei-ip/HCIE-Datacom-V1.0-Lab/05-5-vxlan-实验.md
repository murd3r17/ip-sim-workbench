---
doc_id: "hcie-datacom-v1.0-lab-05"
title: "5 VXLAN 实验"
book: "HCIE-Datacom-V1.0-Lab"
book_title: "HCIE-Datacom V1.0 实验手册"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "lab"
source_pdf: "HCIE-Datacom V1.0 实验手册.pdf"
seq: 5
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 5 VXLAN 实验

## 5.1 静态VXLAN 隧道实现二层互通

## 5.1.1 实验介绍

5.1.1.1 学习目标

- 使用CLI 完成静态VXLAN 隧道创建
- 通过VXLAN 隧道实现二层互通
- 使用VLAN 绑定接入方式实现VXLAN 业务接入

5.1.1.2 实验组网介绍

图5-1 静态VXLAN 隧道实现二层互通 设备互联方式如图所示，Border、Edge_1、Edge_2 上均创建Loopback0 接口，其IP 地址为 10.0.x.x（x 为设备编号，在配置步骤中会使用表格标明）。 Edge_1、Border 之间链路为Trunk 链路，放通VLAN12，Edge_1、Border 上创建VLANIF12 用于 三层互通，IP 地址配置为10.0.12.x/24。 Border、Edge_2 之间链路为Trunk 链路，放通VLAN23，Border、Edge_2 上创建VLANIF23 用于 三层互通，IP 地址配置为10.0.23.x/24。 Edge_1、Border、Edge_2 之间运行OSPF，使用Loopback0 接口IP 地址作为Router ID，在环回 口、互联接口上使能OSPF（进程号1）。 Edge_1、Edge_2 之间使用Loopback0 接口地址作为VXLAN NVE 接口源地址建立静态VXLAN 隧 道。 ACC_1、ACC_2 作为接入交换机，通过Access 接口与PC1、PC2 互联，Edge_1、Edge_2 通过二 层子接口与ACC_1、ACC_2 互联，放通VLAN100，并将三层子接口与BD10 进行绑定，用于实 现终端的报文通过二层子接口的方式接入VXLAN 网络。

## 5.1.2 实验任务

5.1.2.1 配置思路

1. 基础连通性配置
2. 业务接入点配置
3. 配置静态VXLAN 隧道

5.1.2.2 配置步骤

步骤 1 基础连通性配置 分别在Edge_1、Border、Edge_2 上按照下表完成互联接口IP 配置、OSPF 配置。 设备编号 设备名称 设备编号（X） Edge_1 Border Edge_2

```cli
#设备命名。
```

略

```cli
#Edge_1 VLAN、接口基础配置。

[Edge_1] vlan 12

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_1]

[Edge_1] interface GigabitEthernet0/0/1

[Edge_1-GigabitEthernet0/0/1] port link-type trunk

[Edge_1-GigabitEthernet0/0/1] port trunk allow-pass vlan 12

[Edge_1-GigabitEthernet0/0/1] quit

[Edge_1]

[Edge_1] interface Vlanif12

[Edge_1-Vlanif12] ip address 10.0.12.1 255.255.255.0

[Edge_1-Vlanif12] quit

[Edge_1]

[Edge_1] interface LoopBack 0

[Edge_1-LoopBack0] ip address 10.0.1.1 32

[Edge_1-LoopBack0] quit

# Border VLAN、接口基础配置。

[Border] vlan batch 12 23

Info: This operation may take a few seconds. Please wait for a moment...done.

[Border]

[Border] interface GigabitEthernet0/0/23

[Border-GigabitEthernet0/0/23] port link-type trunk

[Border-GigabitEthernet0/0/23] port trunk allow-pass vlan 12

[Border-GigabitEthernet0/0/23] quit

[Border] interface GigabitEthernet0/0/24

[Border-GigabitEthernet0/0/24] port link-type trunk

[Border-GigabitEthernet0/0/24] port trunk allow-pass vlan 23

[Border-GigabitEthernet0/0/24] quit

[Border]

[Border] interface Vlanif12

[Border-Vlanif12] ip address 10.0.12.2 255.255.255.0

[Border-Vlanif12] quit

[Border] interface Vlanif23

[Border-Vlanif23] ip address 10.0.23.2 255.255.255.0

[Border-Vlanif23] quit

[Border]

[Border] interface LoopBack 0

[Border-LoopBack0] ip address 10.0.2.2 32

[Border-LoopBack0] quit

#Edge_2 VLAN、接口基础配置。

[Edge_2] vlan 23

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_2]

[Edge_2] interface GigabitEthernet0/0/1

[Edge_2-GigabitEthernet0/0/1] port link-type trunk

[Edge_2-GigabitEthernet0/0/1] port trunk allow-pass vlan 23

[Edge_2-GigabitEthernet0/0/1] quit

[Edge_2]

[Edge_2] interface Vlanif 23

[Edge_2-Vlanif23] ip address 10.0.23.3 255.255.255.0

[Edge_2-Vlanif23] quit

[Edge_2]

[Edge_2] interface LoopBack 0

[Edge_2-LoopBack0] ip address 10.0.3.3 32

[Edge_2-LoopBack0] quit

#互联接口连通性测试。

[Border]ping 10.0.12.1

PING 10.0.12.1: 56  data bytes, press CTRL_C to break Reply from 10.0.12.1: bytes=56 Sequence=1 ttl=254 time=1 ms

Reply from 10.0.12.1: bytes=56 Sequence=2 ttl=254 time=1 ms Reply from 10.0.12.1: bytes=56 Sequence=3 ttl=254 time=1 ms Reply from 10.0.12.1: bytes=56 Sequence=4 ttl=254 time=1 ms Reply from 10.0.12.1: bytes=56 Sequence=5 ttl=254 time=1 ms

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

Area 0.0.0.0 interface  10.0.12.2(Vlanif12)'s neighbors Router ID: 10.0.1.1         Address: 10.0.12.1 State: Full  Mode:Nbr is  Slave  Priority: 1 R: 10.0.12.1  BDR: 10.0.12.2  MTU: 0 Dead timerdue in 36  sec Retrans timerinterval: 5 Neighbor is up for 00:01:57 Authentication Sequence: [ 0 ]

Neighbors

Area 0.0.0.0 interface 10.0.23.2(Vlanif23)'s neighbors Router ID: 10.0.3.3         Address: 10.0.23.3 State: Full  Mode:Nbr is  Master  Priority: 1 DR: 10.0.23.2  BDR: 10.0.23.3  MTU: 0 Dead timerdue in 28  sec Retrans timerinterval: 5 Neighbor is up for 00:01:24 Authentication Sequence: [ 0 ]

OSPF 邻居关系已经建立完成。

#Border 上检查OSPF 路由。

[Border]display ospf routing

OSPF Process 1 with Router ID 10.0.2.2

Routing Tables

Routing for Network Destination        Cost  Type       NextHop         AdvRouter       Area 10.0.2.2/32        0     Stub       10.0.2.2        10.0.2.2        0.0.0.0

10.0.12.0/24       1     Transit    10.0.12.2       10.0.2.2        0.0.0.0 10.0.23.0/24       1     Transit    10.0.23.2       10.0.2.2        0.0.0.0 10.0.1.1/32        1     Stub       10.0.12.1       10.0.1.1        0.0.0.0 10.0.3.3/32        1     Stub       10.0.23.3       10.0.3.3        0.0.0.0

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

步骤 2 业务接入点配置 Edge_1、Edge_2 上完成业务接入点的配置，创建子接口与ACC_1、ACC_2 互通，终结

```cli
VLAN100，并与BD10 进行绑定。
```

ACC_1、ACC_2 与PC 连接的接口配置为Access 接口，PVID 100，与Edge_1、Edge_2 互联的接 口配置为Trunk 接口，放通VLAN 100。

```cli
#Edge_1 配置。

[Edge_1] bridge-domain 10

[Edge_1-bd10] vxlan vni 1000

[Edge_1-bd10] quit

[Edge_1] vcmp role silent

[Edge_1] interface GigabitEthernet0/0/24

[Edge_1-GigabitEthernet0/0/24] port link-type trunk

Info: This operation may take a few seconds. Please wait for a moment...

[Edge_1-GigabitEthernet0/0/24] quit

[Edge_1] interface GigabitEthernet0/0/24.100 mode l2

[Edge_1-GigabitEthernet0/0/24.100] encapsulation dot1q vid 100

Info: This operation may take a few seconds. Please wait for a moment...

[Edge_1-GigabitEthernet0/0/24.100] bridge-domain 10

[Edge_1-GigabitEthernet0/0/24.100] quit
```

默认VCMP 配置会让子接口无法配置Dot1q 封装终结VLAN，需配置vcmp role silent 命令。

```cli
#Edge_2 配置。

[Edge_2] bridge-domain 10

[Edge_2-bd10] vxlan vni 1000

[Edge_2-bd10] quit

[Edge_2] vcmp role silent

[Edge_2] interface GigabitEthernet0/0/24

[Edge_2-GigabitEthernet0/0/24] port link-type trunk

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_2-GigabitEthernet0/0/24] quit

[Edge_2] interface GigabitEthernet0/0/24.100 mode l2

[Edge_2-GigabitEthernet0/0/24.100] encapsulation dot1q vid 100

Info: This operation may take a few seconds. Please wait for a moment...done.

[Edge_2-GigabitEthernet0/0/24.100] bridge-domain 10

[Edge_2-GigabitEthernet0/0/24.100] quit

#ACC_1 配置。

[ACC_1] vlan 100

Info: This operation may take a few seconds. Please wait for a moment...done.

[ACC_1-vlan100] interface GigabitEthernet0/0/24

[ACC_1-GigabitEthernet0/0/24] port link-type access

[ACC_1-GigabitEthernet0/0/24] port default vlan 100

[ACC_1-GigabitEthernet0/0/24] quit

[ACC_1] interface GigabitEthernet0/0/1

[ACC_1-GigabitEthernet0/0/1] port link-type trunk

[ACC_1-GigabitEthernet0/0/1] port trunk allow-pass vlan 100

[ACC_1-GigabitEthernet0/0/1] quit

#ACC_2 配置。

[ACC_2] vlan 100

Info: This operation may take a few seconds. Please wait for a moment...done.

[ACC_2-vlan100]interface GigabitEthernet0/0/23

[ACC_2-GigabitEthernet0/0/23] port link-type access

Info: This operation may take a few seconds. Please wait for a moment...done.

[ACC_2-GigabitEthernet0/0/23] port default vlan 100

[ACC_2-GigabitEthernet0/0/23] quit

[ACC_2] interface GigabitEthernet0/0/1

[ACC_2-GigabitEthernet0/0/1] port link-type trunk

[ACC_2-GigabitEthernet0/0/1] port trunk allow-pass vlan 100

[ACC_2-GigabitEthernet0/0/1] quit
```

步骤 3 静态VXLAN 隧道配置 在Edge_1、Edge_2 上以Loopback0 接口地址作为NVE 接口源地址，建立静态的VXLAN 隧道， 实现PC1、PC2 之间的互通。

```cli
#Edge_1 上创建NVE 接口。

[Edge_1]interface Nve1

[Edge_1-Nve1] source 10.0.1.1

[Edge_1-Nve1] vni 1000 head-end peer-list 10.0.3.3

[Edge_1-Nve1] quit

#Edge_2 上创建NVE 接口。

[Edge_2]interface Nve1

[Edge_2-Nve1] source 10.0.3.3

[Edge_2-Nve1] vni 1000 head-end peer-list 10.0.1.1

[Edge_2-Nve1] quit

#Edge_1、Edge_2 上查看VXLAN Tunnel。

[Edge_1]display vxlan tunnel
```

Tunnel ID      Source          Destination             State     Type --------------------------------------------------------------------------------------------------------------------

```cli
4026531841      10.0.1.1        10.0.3.3                  up       static

-------------------------------------------------------------------------------------------------------------------- Number of vxlan tunnel : Total: 1    Static: 1    L2 dynamic: 0    L3 dynamic: 0
```

```cli
[Edge_2]display vxlan tunnel
```

Tunnel ID      Source          Destination             State     Type --------------------------------------------------------------------------------------------------------------------

```cli
4026531841      10.0.3.3        10.0.1.1                  up       static

-------------------------------------------------------------------------------------------------------------------- Number of vxlan tunnel : Total: 1    Static: 1    L2 dynamic: 0    L3 dynamic: 0 可以看到Edge_1、Edge_2 上都已经存在类型为：static 且状态为Up 的VXLAN 隧道。 步骤 4 结果验证 在PC1 上访问PC2，并查看VXLAN 相关转发表项。
```

```cli
#在PC1 Ping PC2。
```

C:\Users\PC1>ping 192.168.100.2

正在 Ping 192.168.100.2 具有 32 字节的数据: 来自 192.168.100.2 的回复: 字节=32 时间=1ms TTL=128 来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=128 来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=128 来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=128

192.168.100.2 的 Ping 统计信息:

数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 0ms，最长 = 1ms，平均 = 0ms 此时PC1 能够与PC2 进行通信。

```cli
#查看Edge_1、Edge_2 上的MAC 地址表项。

[Edge_1]display mac-address

------------------------------------------------------------------------------- MAC Address    VLAN/VSI/BD          Learned-From     Type ------------------------------------------------------------------------------- 000c-292e-b4a3  -/-/10               10.0.3.3            dynamic 000c-29b3-efea   -/-/10               GE0/0/24.100     dynamic 9400-b049-9efd  12/-/-               GE0/0/1            dynamic ------------------------------------------------------------------------------- Total items displayed = 3

#在Edge_1 上可以看到从子接口 GE0/0/24.100 和远端VTEP（10.0.3.3）都学习到了一条MAC 地 址，分别为PC1、PC2 的MAC 地址。

[Edge_2]display mac-address

------------------------------------------------------------------------------- MAC Address    VLAN/VSI/BD             Learned-From    Type ------------------------------------------------------------------------------- 000c-292e-b4a3  -/-/10                  GE0/0/24.100     dynamic 000c-29b3-efea   -/-/10                  10.0.1.1            dynamic 9400-b049-9ef9  23/-/-                  GE0/0/1           dynamic ------------------------------------------------------------------------------- Total items displayed = 3
```

同样地Edge_2 上可以看到从本地子接口、远端VTEP（10.0.1.1）学习到的MAC 地址。

```cli
#在Border 上创建ACL 3000，用于匹配PC1 与PC2 通信时经由VXLAN 封装后的报文。

[Border]acl number 3000

[Border-acl-adv-3000] rule 1 permit udp source 10.0.1.1 0 destination 10.0.3.3 0 destination-port eq 4789

ACL 匹配源IP 地址为10.0.1.1，目的IP 地址为10.0.3.3，协议为UDP，且目的端口号为4789 的
```

报文。

```cli
#在Border 上使用capture-packet 命令抓取GE0/0/24 接口的报文。

[Border]capture-packet acl 3000 interface GigabitEthernet 0/0/24 destination file vxlan.cap outbound packet-num 10

Info: Packet getting is configured. Saved to flash:/vxlan.cap.

#在PC1 上再次Ping PC2。
```

C:\Users\PC1>ping 192.168.100.2

正在 Ping 192.168.100.2 具有 32 字节的数据: 来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=128 来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=128 来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=128 来自 192.168.100.2 的回复: 字节=32 时间<1ms TTL=128

192.168.100.2 的 Ping 统计信息:

数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 0ms，最长 = 0ms，平均 = 0ms

```cli
#设备完成抓包后会输出如下回显。

-----------------packet getting report----------------- file: flash:/vxlan.cap packets getting: interface GigabitEthernet0/0/24 ACL: 3000

vlan: -  cvlan: -
```

car: 64kbps timeout: 60s packets: 10 (expected) 10 (actual) length without tunnel header: 64 (expected) ------------------------------------------------------- Capture-packet 抓取到的报文所在路径已在回显中告知，可通过FTP、SFTP 的方式下载该抓 包，设备开启FTP、SFTP 方式可参考产品手册中相关配置。

```cli
#查看Border 上抓取到的报文。
```

Ethernet II, Src: 94:00:b0:49:9e:f9 (94:00:b0:49:9e:f9), Dst: 80:e1:bf:0e:56:59 (80:e1:bf:0e:56:59) 802.1Q Virtual LAN, PRI: 0, DEI: 0, ID: 23 Internet Protocol Version 4, Src: 10.0.1.1, Dst: 10.0.3.3 User Datagram Protocol, Src Port: 19456, Dst Port: 4789 Virtual eXtensible Local Area Network Flags: 0x0800, VXLAN Network ID (VNI) Group Policy ID: 0 VXLAN Network Identifier (VNI): 1000 Reserved: 0 Ethernet II, Src: 00:0c:29:b3:ef:ea, Dst: 00:0c:29:2e:b4:a3 Internet Protocol Version 4, Src: 192.168.100.1, Dst: 192.168.100.2 Internet Control Message Protocol

在Border 上抓取报文，可以看到外层IP 头部中源目IP 地址为10.0.1.1、10.0.3.3，分别为 Edge_1、Edge_2 的NVE 接口IP 地址。 在外层IP 头部后为UDP 头部，其目的端口号为4789，表明后续报文为VXLAN 封装。 在VXLAN 头部中可以看到VNI 值为1000。 在VXLAN 头部之后为PC1、PC2 之间通信的原始数据帧，可以看到PC1、PC2 之间相互通信时 的数据帧、IP 头部。

## 5.1.3 思考题

VTEP 从本地的BD 中收到来自主机的广播报文，将会如何处理？
