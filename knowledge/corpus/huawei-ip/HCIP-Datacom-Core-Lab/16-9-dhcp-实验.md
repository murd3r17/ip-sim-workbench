---
doc_id: "hcip-datacom-core-lab-16"
title: "9 DHCP 实验"
book: "HCIP-Datacom-Core-Lab"
book_title: "HCIP-Datacom-Core Technology V1.0 实验手册"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "lab"
source_pdf: "HCIP-Datacom-Core Technology V1.0 实验手册.pdf"
seq: 16
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 9 DHCP 实验

## 9.1 DHCP Relay 配置

## 9.1.1 实验介绍

9.1.1.1 学习目标

- 实现部署DHCP Relay 让终端动态获取IP 地址
- 实现DHCP 静态地址绑定配置
- 分析DHCP Relay 的debug 信息

9.1.1.2 实验组网介绍

图9-1 DHCP Relay 配置 S4 上创建VLANIF10、20、30 模拟DHCP Client，S3 作为DHCP Relay 设备，S1 作为DHCP Server，在S1 上创建全局地址池为S4 的三个VLANIF 分配地址。 S3、S4 之间的接口配置为Trunk 模式，放通VLAN10、20、30，S1、S3 之间的接口配置为 Access 模式，PVID 设置为40。

9.1.1.3 实验背景

你是公司的网络管理员，由于公司网络主机数量较多，使用静态地址分配难以管理，因此需要 架设DHCP Server。 核心交换机S1 做DHCP Server，S4 为DHCP Client，S3 作为各个网段的网关，由于DHCP Discover 是广播报文不能穿越路由器，因此部署DHCP Relay 将请求报文从S3 发送到S1。 同时针对特殊的Client，如服务器、打印机等，要求DHCP 分配固定的IP 地址。

## 9.1.2 实验任务

9.1.2.1 任务思路

1. 在每台交换机上创建VLAN，配置接口为对应的模式，放通相应的VLAN。
2. 配置DHCP Server，创建地址池为终端分配地址，同时创建静态分配地址。
3. 配置DHCP Relay 设备，在接口下配置DHCP Relay 所代理的DHCP Server IP 地址。
4. 在DHCP Client 上开启通过DHCP 获取地址。
5. 通过debug 观察DHCP Relay 设备中继DHCP 报文的过程。

9.1.2.2 任务步骤

步骤 1 基础配置 在三台交换机上创建相应的VLAN、VLANIF，配置接口放通对应的VLAN。VLANIF 地址为 10.0.x.y/24，其中x 为VLAN ID，y 为设备编号，S4 上的VLANIF 暂不需要配置地址。

```cli
#创建VLAN

[S1]vlan 40

[S3]vlan batch 10 20 30 40

[S4]vlan batch 10 20 30

#配置接口放通相应的VLAN

[S4]interface GigabitEthernet0/0/3

[S4-GigabitEthernet0/0/3] port link-type trunk

[S4-GigabitEthernet0/0/3] port trunk allow-pass vlan 10 20 30

[S4-GigabitEthernet0/0/3] quit

[S3]interface GigabitEthernet0/0/1

[S3-GigabitEthernet0/0/1] port link-type access

[S3-GigabitEthernet0/0/1] port default vlan 40

[S3-GigabitEthernet0/0/1] quit

[S3]interface GigabitEthernet0/0/3

[S3-GigabitEthernet0/0/3] port link-type trunk

[S3-GigabitEthernet0/0/3] port trunk allow-pass vlan 10 20 30

[S3-GigabitEthernet0/0/3] quit

[S1]interface GigabitEthernet0/0/12

[S1-GigabitEthernet0/0/12] port link-type access

[S1-GigabitEthernet0/0/12] port default vlan 40

[S1-GigabitEthernet0/0/12] quit

#VLANIF 配置

[S4]interface Vlanif 10

[S4-Vlanif10] quit

[S4]interface Vlanif 20

[S4-Vlanif20] quit

[S4]interface Vlanif 30

[S4-Vlanif30] quit

[S3]interface Vlanif 10

[S3-Vlanif10] ip address 10.0.10.3 24

[S3-Vlanif10] quit

[S3]interface Vlanif 20

[S3-Vlanif20] ip address 10.0.20.3 24

[S3-Vlanif20] quit

[S3]interface Vlanif 30

[S3-Vlanif30] ip address 10.0.30.3 24

[S3-Vlanif30] quit

[S3]interface Vlanif 40

[S3-Vlanif40] ip address 10.0.40.3 24

[S3-Vlanif40] quit

[S1]interface Vlanif 40

[S1-Vlanif40] ip address 10.0.40.1 24

[S1-Vlanif40] quit

#检查S1、S3 之间的VLANIF40 接口连通性

[S1]ping -c 1 10.0.40.3

PING 10.0.40.3: 56  data bytes, press CTRL_C to break Reply from 10.0.40.3: bytes=56 Sequence=1 ttl=255 time=60 ms

--- 10.0.40.3 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 60/60/60 msDHCP Server
```
``
与DHCP Relay 之间能够正常通信。
``
步骤 2 DHCP Server 配置 开启DHCP 服务，配置全局地址池，同时为S4 上的VLANIF30 分配静态IP 地址。

#开启DHCP 服务

```cli
[S1]dhcp enable

#创建地址池VLAN10，用于给S4 的VLANIF10 分配地址

[S1]ip pool vlan10

[S1-ip-pool-vlan10] gateway-list 10.0.10.3

[S1-ip-pool-vlan10] network 10.0.10.0 mask 255.255.255.0

[S1-ip-pool-vlan10] dns-list 10.0.10.3

[S1-ip-pool-vlan10] quit

#创建地址池VLAN20，用于给S4 的VLANIF20 分配地址

[S1]ip pool vlan20

[S1-ip-pool-vlan20] gateway-list 10.0.20.3

[S1-ip-pool-vlan20] network 10.0.20.0 mask 255.255.255.0

[S1-ip-pool-vlan20] dns-list 10.0.20.3

[S1-ip-pool-vlan20] quit

#创建地址池VLAN30，用于给S4 的VLANIF30 分配地址

[S1]ip pool vlan30

[S1-ip-pool-vlan30] gateway-list 10.0.30.3

[S1-ip-pool-vlan30] network 10.0.30.0 mask 255.255.255.0

[S1-ip-pool-vlan30] dns-list 10.0.30.3

[S1-ip-pool-vlan30] quit

#查看S4 的VLANIF30 的接口MAC 地址

[S4]display interface Vlanif 30

Vlanif30 current state : UP
```
``
Line protocol current state : DOWN Description:

Route Port,The Maximum Transmit Unit is 1500
``
Internet protocol processing : disabled

IP Sending Frames' Format is PKTFMT_ETHNT_2, Hardware address is 4c1f-cc49-4c7c
``
Current system time: 2020-06-05 16:51:20-08:00 Input bandwidth utilization  : -- Output bandwidth utilization : -- 实际MAC 地址以实验环境设备为准。

```cli
#在S1 上为S4 的VLANIF30 配置静态地址分配

[S1]ip pool vlan30

[S1-ip-pool-vlan30] static-bind ip-address 10.0.30.2 mac-address 4c1f-cc49-4c7c
```
``
为其分配固定IP 地址10.0.30.2。

#在VLANIF40 接口下使能DHCP Server

```cli
[S1]interface Vlanif 40

[S1-Vlanif40] dhcp select global

#查看IP 地址池配置情况

[S1]display ip pool name vlan10

Pool-name      : vlan10 Pool-No        : 0 Lease          : 1 Days 0 Hours 0 Minutes Domain-name    : - DNS-server0    : 10.0.10.3 NBNS-server0   : - Netbios-type   : - Position       : Local           Status           : Unlocked

Gateway-0      : 10.0.10.3 Mask           : 255.255.255.0 VPN instance   : -- ----------------------------------------------------------------------------- Start           End     Total  Used  Idle(Expired)  Conflict  Disable -----------------------------------------------------------------------------

10.0.10.1     10.0.10.254   253     0        253(0)         0        0

-----------------------------------------------------------------------------

[S1]display ip pool name vlan20

Pool-name      : vlan20 Pool-No        : 1 Lease          : 1 Days 0 Hours 0 Minutes Domain-name    : - DNS-server0    : 10.0.20.3 NBNS-server0   : - Netbios-type   : - Position       : Local           Status           : Unlocked Gateway-0      : 10.0.20.3 Mask           : 255.255.255.0 VPN instance   : -- ----------------------------------------------------------------------------- Start           End     Total  Used  Idle(Expired)  Conflict  Disable -----------------------------------------------------------------------------

10.0.20.1     10.0.20.254   253     0        253(0)         0        0

-----------------------------------------------------------------------------

[S1]display ip pool name vlan30

Pool-name      : vlan30 Pool-No        : 2 Lease          : 1 Days 0 Hours 0 Minutes Domain-name    : - DNS-server0    : 10.0.30.3 NBNS-server0   : - Netbios-type   : - Position       : Local           Status           : Unlocked Gateway-0      : 10.0.30.3 Mask           : 255.255.255.0 VPN instance   : -- ----------------------------------------------------------------------------- Start           End     Total  Used  Idle(Expired)  Conflict  Disable -----------------------------------------------------------------------------

10.0.30.1     10.0.30.254   253     1        252(0)         0        0

-----------------------------------------------------------------------------
```
``
地址池vlan30 已经存在一个“Used”地址，该地址为静态分配的地址。

```cli
#配置前往用户网段的路由

[S1]ip route-static 10.0.10.0 24 10.0.40.3

[S1]ip route-static 10.0.20.0 24 10.0.40.3

[S1]ip route-static 10.0.30.0 24 10.0.40.3
```
``
DHCP Relay 设备接收到DHCP Client 的DHCP 报文之后，使用接口IP 地址中继客户端的

DHCP 报文，因此需要保证接口IP 与DHCP Server 之间的连通性。

#检查DHCP Server 与DHCP Relay 接口之间的连通性

```cli
<S1>ping -c 1 10.0.10.3 PING 10.0.10.3: 56  data bytes, press CTRL_C to break Reply from 10.0.10.3: bytes=56 Sequence=1 ttl=255 time=50 ms

--- 10.0.10.3 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 50/50/50 ms

<S1>ping -c 1 10.0.20.3 PING 10.0.20.3: 56  data bytes, press CTRL_C to break Reply from 10.0.20.3: bytes=56 Sequence=1 ttl=255 time=40 ms

--- 10.0.20.3 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 40/40/40 ms

<S1>ping -c 1 10.0.30.3 PING 10.0.30.3: 56  data bytes, press CTRL_C to break Reply from 10.0.30.3: bytes=56 Sequence=1 ttl=255 time=30 ms

--- 10.0.30.3 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 30/30/30 ms
```
``
步骤 3 DHCP Relay 配置 在S3 上完成DHCP Relay 相关配置

#开启DHCP 服务

```cli
[S3]dhcp enable

#在接口上配置DHCP Relay，指定DHCP Server

[S3]interface Vlanif10

[S3-Vlanif10] dhcp select relay

[S3-Vlanif10] dhcp relay server-ip 10.0.40.1

[S3-Vlanif10] quit

[S3]interface Vlanif20

[S3-Vlanif20] dhcp select relay

[S3-Vlanif20] dhcp relay server-ip 10.0.40.1

[S3-Vlanif20] quit

[S3]interface Vlanif30

[S3-Vlanif30] dhcp select relay

[S3-Vlanif30] dhcp relay server-ip 10.0.40.1

[S3-Vlanif30] quit

#检查DHCP Relay 配置结果

[S3]display dhcp relay all

DHCP relay agent running information of interface Vlanif10 :
```
``
Server IP address [01] : 10.0.40.1 Gateway address in use : 10.0.10.3

```cli
DHCP relay agent running information of interface Vlanif20 :
```
``
Server IP address [01] : 10.0.40.1 Gateway address in use : 10.0.20.3

```cli
DHCP relay agent running information of interface Vlanif30 :
```
``
Server IP address [01] : 10.0.40.1 Gateway address in use : 10.0.30.3

步骤 4 DHCP Client 配置 在S4 上配置VLANIF10、20、30 接口通过DHCP 获取IP 地址

#开启DHCP 服务

```cli
[S4]dhcp enable

#开启接口通过DHCP 获取地址

[S4]interface Vlanif10

[S4-Vlanif10] ip address dhcp-alloc

[S4-Vlanif10] quit

[S4]interface Vlanif20

[S4-Vlanif20] ip address dhcp-alloc

[S4-Vlanif20] quit

[S4]interface Vlanif30

[S4-Vlanif30] ip address dhcp-alloc

[S4-Vlanif30] quit

#查看各个接口IP 地址获取情况

<S4>display interface Vlanif 10

Vlanif10 current state : UP
```
``
Line protocol current state : UP Last line protocol up time : 2020-06-05 17:37:57 UTC-08:00 Description:

Route Port,The Maximum Transmit Unit is 1500
``
Internet Address is allocated by DHCP, 10.0.10.254/24

```cli
[S4]display interface Vlanif 20

Vlanif20 current state : UP
```
``
Line protocol current state : UP

Last line protocol up time : 2020-06-05 17:41:23 UTC-08:00 Description:

Route Port,The Maximum Transmit Unit is 1500
``
Internet Address is allocated by DHCP, 10.0.20.254/24

```cli
[S4]display interface Vlanif 30

Vlanif30 current state : UP
```
``
Line protocol current state : UP Last line protocol up time : 2020-06-05 17:43:22 UTC-08:00 Description:

Route Port,The Maximum Transmit Unit is 1500
``
Internet Address is allocated by DHCP, 10.0.30.2/24 接口已经通过DHCP 获取到IP 地址，并且VLANIF30 的地址为静态分配的地址：10.0.30.2。

步骤 5 观察DHCP Relay 过程 在S3 上开启debugging dhcp relay info、debugging dhcp relay packet，删除S4VLANIF30 下DHCP 获取地址的配置，之后重新配置，观察debug 输出信息。

```cli
#在S3 上开启debug

<S3>debugging dhcp relay info <S3>debugging dhcp relay packet <S3>terminal debugging Info: Current terminal debugging is on. <S3>terminal monitor Info: Current terminal monitor is on.

#删除S4 VLANIF30 接口下配置

[S4]interface Vlanif 30

[S4-Vlanif30] undo ip address dhcp-alloc

#S3 上debug 输出信息

Jun  5 2020 18:41:41.510.1-08:00 S3 DHCP/7/DEBUG:[dhcpr-pkt]:Receives DHCP RELEASE message from

interface Vlanif30.
```
``
Jun  5 2020 18:41:41.510.2-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:srcip:10.0.30.2 dstip:10.0.40.1 vpnid:0 Jun  5 2020 18:41:41.510.3-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:msgtype:BOOT-REQUEST dhcp msgtype:DHCP RELEASE bflag:uc chaddr:4c1f-cc49-4c7c ciaddr:10.0.30.2 reqip:0.0.0.0 giaddr:0.0.0.0 serverid:10.0.40.1 Jun  5 2020 18:41:41.510.4-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:Select 10.0.30.3 as giaddr. Jun  5 2020 18:41:41.510.5-08:00 S3 DHCP/7/DEBUG:[dhcpr-pkt]:Relay DHCP RELEASE to server 10.0.40.1. S3 从VLANIF30 收到了DHCP Release 报文，其源IP 为10.0.30.2，目的IP 为10.0.40.1，其 中giaddr 字段值为0.0.0.0，S3 将该字段填充为10.0.30.3 之后（VLANIF30 接口IP）发送给 了DHCP Server。

```cli
#重新配置S4 VLANIF30 接口下配置

[S4]interface Vlanif 30

[S4-Vlanif30] ip address dhcp-alloc

# S3 上debug 输出信息
```
``
Jun  5 2020 18:38:42.600.1-08:00 S3 DHCP/7/DEBUG:[dhcpr-pkt]:Receives DHCP DISCOVER message from interface Vlanif30. Jun  5 2020 18:38:42.600.2-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:srcip:0.0.0.0 dstip:255.255.255.255 vpnid:0 Jun  5 2020 18:38:42.600.3-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:msgtype:BOOT-REQUEST dhcp msgtype:DHCP DISCOVER bflag:uc chaddr:4c1f-cc49-4c7c ciaddr:0.0.0.0 reqip:0.0.0.0 giaddr:0.0.0.0 serverid:0.0.0.0 Jun  5 2020 18:38:42.600.4-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:Select 10.0.30.3 as giaddr. Jun  5 2020 18:38:42.600.5-08:00 S3 DHCP/7/DEBUG:[dhcpr-pkt]:Relay DHCP DISCOVER to server 10.0.40.1. S3 收到来自Client 的DHCP Discover，源IP 为0.0.0.0，目的IP 为255.255.255.255，S3 填 充giaddr 字段值为10.0.30.3 之后，将报文单播转发给了DHCP Server 10.0.40.1，此时报文 源IP 为10.0.30.3。

Jun  5 2020 18:38:42.610.1-08:00 S3 DHCP/7/DEBUG:[dhcpr-pkt]:Receives DHCP OFFER message from

```cli
interface Vlanif40.
```
``
Jun  5 2020 18:38:42.610.2-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:srcip:10.0.40.1 dstip:10.0.30.3 vpnid:0 Jun  5 2020 18:38:42.610.3-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:msgtype:BOOT-REPLY dhcp msgtype:DHCP OFFER bflag:uc chaddr:4c1f-cc49-4c7c ciaddr:0.0.0.0 reqip:0.0.0.0 giaddr:10.0.30.3 serverid:10.0.40.1 Jun  5 2020 18:38:42.610.4-08:00 S3 DHCP/7/DEBUG:[dhcpr-pkt]:Unicast DHCP OFFER to client. (Chaddr=4c1f-cc49-4c7c, Ciaddr=10.0.30.2) S3 收到来自DHCP Server 的DHCP Offer，源IP 为10.0.40.1，目的IP 为10.0.30.3，其中携 带携带了DHCP Server ID（DHCP Option 54），S3 之后将报文单播发送给Client。

Jun  5 2020 18:38:42.650.1-08:00 S3 DHCP/7/DEBUG:[dhcpr-pkt]:Receives DHCP REQUEST message from interface Vlanif30. Jun  5 2020 18:38:42.650.2-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:srcip:0.0.0.0 dstip:255.255.255.255 vpnid:0 Jun  5 2020 18:38:42.650.3-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:msgtype:BOOT-REQUEST dhcp msgtype:DHCP REQUEST bflag:uc chaddr:4c1f-cc49-4c7c ciaddr:0.0.0.0 reqip:10.0.30.2 giaddr:0.0.0.0 serverid:10.0.40.1 Jun  5 2020 18:38:42.650.4-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:Select 10.0.30.3 as giaddr. Jun  5 2020 18:38:42.650.5-08:00 S3 DHCP/7/DEBUG:[dhcpr-pkt]:Relay DHCP REQUEST to server 10.0.40.1. S3 收到来自Client 的DHCP Request，该Request 为广播报文，S3 随后将报文转成单播发送 给DHCP Server。

Jun  5 2020 18:38:42.660.1-08:00 S3 DHCP/7/DEBUG:[dhcpr-pkt]:Receives DHCP ACK message from

```cli
interface Vlanif40.

Jun  5 2020 18:38:42.660.2-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:srcip:10.0.40.1 dstip:10.0.30.3 vpnid:0
```
``
Jun  5 2020 18:38:42.660.3-08:00 S3 DHCP/7/DEBUG:[dhcpr-info]:msgtype:BOOT-REPLY dhcp msgtype:DHCP ACK bflag:uc chaddr:4c1f-cc49-4c7c ciaddr:0.0.0.0 reqip:0.0.0.0 giaddr:10.0.30.3 serverid:10.0.40.1 Jun  5 2020 18:38:42.660.4-08:00 S3 DHCP/7/DEBUG:[dhcpr-pkt]:Unicast DHCP ACK to client. (Chaddr=4c1f-cc49-4c7c, Ciaddr=10.0.30.2) S3 收到来自DHCP Server 的DHCP ACK，源IP 为10.0.40.1，目的IP 为10.0.30.3，S3 之后 将报文单播发送给Client，至此整个DHCP 新获取地址过程结束。

## 9.1.3 思考题
``
DHCP Server 收到来自DHCP Relay 中继的DHCP 报文之后，如何选择地址池？
``
## 9.1.4 配置参考

S1 设备配置

```cli
sysname S1

vlan batch 40

dhcp enable

ip pool vlan10
```
``
gateway-list 10.0.10.3 network 10.0.10.0 mask 255.255.255.0 dns-list 10.0.10.3

ip pool vlan20
``
gateway-list 10.0.20.3 network 10.0.20.0 mask 255.255.255.0 dns-list 10.0.20.3

ip pool vlan30
``
gateway-list 10.0.30.3 network 10.0.30.0 mask 255.255.255.0 static-bind ip-address 10.0.30.2 mac-address 4c1f-cc49-4c7c dns-list 10.0.30.3

```cli
interface Vlanif40

ip address 10.0.40.1 255.255.255.0

dhcp select global

interface GigabitEthernet0/0/12

port link-type access port default vlan 40

ip route-static 10.0.10.0 255.255.255.0 10.0.40.3

ip route-static 10.0.20.0 255.255.255.0 10.0.40.3

ip route-static 10.0.30.0 255.255.255.0 10.0.40.3

return
```
``
S3 设备配置

```cli
sysname S3

vlan batch 10 20 30 40

dhcp enable

interface Vlanif10

ip address 10.0.10.3 255.255.255.0

dhcp select relay

dhcp relay server-ip 10.0.40.1

interface Vlanif20

ip address 10.0.20.3 255.255.255.0

dhcp select relay

dhcp relay server-ip 10.0.40.1

interface Vlanif30

ip address 10.0.30.3 255.255.255.0

dhcp select relay

dhcp relay server-ip 10.0.40.1

interface Vlanif40

ip address 10.0.40.3 255.255.255.0

interface GigabitEthernet0/0/1

port link-type access port default vlan 40

interface GigabitEthernet0/0/3

port link-type trunk port trunk allow-pass vlan 10 20 30

user-interface con 0

user-interface vty 0 4

return
```
``
S4 设备配置

```cli
sysname S4

vlan batch 10 20 30

dhcp enable

interface Vlanif10

ip address dhcp-alloc

interface Vlanif20

ip address dhcp-alloc

interface Vlanif30

ip address dhcp-alloc

interface GigabitEthernet0/0/3

port link-type trunk port trunk allow-pass vlan 10 20 30

Return
```
``