---
doc_id: "hcip-datacom-core-lab-15"
title: "8 VRRP 实验"
book: "HCIP-Datacom-Core-Lab"
book_title: "HCIP-Datacom-Core Technology V1.0 实验手册"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "lab"
source_pdf: "HCIP-Datacom-Core Technology V1.0 实验手册.pdf"
seq: 15
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 8 VRRP 实验

## 8.1 VRRP 基础配置

## 8.1.1 实验介绍

8.1.1.1 学习目标

- 实现VRRP 的部署

- 实现VRRP 与MSTP 的协同工作
- 实现BFD 与VRRP 的联动配置

8.1.1.2 实验组网介绍

图8-1 VRRP 基础配置 设备连接方式如图所示，网络中存在VLAN10、20，每个VLAN 中部署一组VRRP，使用与VLAN ID 相同的数值作为VRID，将S1 配置为VLAN10 的VRRP Master，将S2 配置为VLAN20 的VRRP Master。
``
同时在S1、S2、S3 上部署MSTP，创建Instance 1、2，将VLAN10 映射到MSTI 1、VLAN20 映射到MSTI 2，将S1 配置为MSTI 1 的主根桥、MSTI 2 的备份根桥，而将S2 配置为MSTI 1 的备份根桥、MSTI 2 的主根桥。
``
VLANIF 接口地址使用10.0.x.y/24，其中x 为VRID 组号，y 为设备编号，VRIP 使用10.0.x.254/24。

8.1.1.3 实验背景

为了实现网关冗余，作为网络管理员的你在两台汇聚交换机上部署了VRRP，同时为了实现终 端用户上行数据流量的负载分担，需要在每个VLAN 中各部署一组VRRP。为了防止环路，在 交换网络中部署MSTP，利用MSTP 的负载分担结合VRRP 进行协同工作。

## 8.1.2 实验任务

8.1.2.1 任务思路

1. 所有交换机上创建VLAN，配置MSTP，手动指定S1 为MSTI 1 的根桥、MSTI 2 的备份 根桥，指定S2 为MSTI 1 的备份根桥、MSTI 2 的根桥。
2. 在S1、S2 上创建VLANIF10、20，部署VRRP 组10、20，手动调整VRRP 优先级，使得 S1 成为VRRP 组10 的Master 设备、S2 成为VRRP 组20 的Master 设备。
3. 部署单跳检测的BFD，检测S1、S2 VLANIF 之间连通性，与VRRP 进行联动，实现VRRP 的快速切换。
``
8.1.2.2 任务步骤

步骤 1 MSTP 基础配置

在所有交换机上创建VLAN10、20，配置MSTP 域hcip，并创建两个新的实例：Instance 1、 Instance 2，将VLAN10 映射到Instance 1，将VLAN20 映射到Instance 2，同时将SW1 规 划为MSTI1 的主根桥、MSTI2 的备份根桥，将SW2 规划为MSTI2 的主根桥、MSTI1 的备份 根桥。

```cli
#设备命名
```
略

```cli
#关闭本实验中未使用的接口
```
略

```cli
#创建VLAN

[S1]vlan batch 10 20

[S2]vlan batch 10 20

[S3]vlan batch 10 20

#将所有互联接口配置为Trunk 接口，放通对应VLAN
```
``
略

```cli
#修改STP 模式为MSTP

[S1]stp mode mstp

[S2]stp mode mstp

[S3]stp mode mstp

#配置MSTP

[S1]stp region-configuration

[S1-mst-region] region-name hcip

[S1-mst-region] revision-level 1

[S1-mst-region] instance 1 vlan 10

[S1-mst-region] instance 2 vlan 20

[S1-mst-region] active region-configuration

Info: This operation may take a few seconds. Please wait for a moment...done.

[S1-mst-region] quit

[S2]stp region-configuration

[S2-mst-region] region-name hcip

[S2-mst-region] revision-level 1

[S2-mst-region] instance 1 vlan 10

[S2-mst-region] instance 2 vlan 20

[S2-mst-region] active region-configuration

Info: This operation may take a few seconds. Please wait for a moment...done.

[S2-mst-region] quit

[S3]stp region-configuration

[S3-mst-region] region-name hcip

[S3-mst-region] revision-level 1

[S3-mst-region] instance 1 vlan 10

[S3-mst-region] instance 2 vlan 20

[S3-mst-region] active region-configuration

Info: This operation may take a few seconds. Please wait for a moment...done.

[S3-mst-region] quit

#在S1 检查MSTP 实例和VLAN 的映射关系

[S1]display stp region-configuration

Oper configuration Format selector    :0 Region name        :hcip Revision level     :1

Instance   VLANs Mapped

0       1 to 9, 11 to 19, 21 to 29, 31 to 39, 41 to 49, 51 to 59, 61 to
```
``
69, 71 to 79, 81 to 4094

1       10,

2       20

```cli
#配置SW1 为MSTI1 的根桥、MSTI2 的备份根桥

[S1]stp instance 1 root primary

[S1]stp instance 2 root secondary

#配置SW2 为MSTI2 的根桥、MSTI1 的备份根桥

[S2]stp instance 1 root secondary

[S2]stp instance 2 root primary

#在S1 上查看MSTI1 的状态和统计信息摘要

[S1]display stp instance 1 brief

MSTID  Port                     Role  STP State           Protection

1    GigabitEthernet0/0/10       DESI  FORWARDING      NONE

1    GigabitEthernet0/0/11       DESI  FORWARDING      NONE

1    GigabitEthernet0/0/12       DESI  FORWARDING      NONE
```
``
S1 上所有接口都是指定接口，S1 为MSTI1 的根桥。

```cli
#在S2 上查看MSTI2 的状态和统计信息摘要

[S2]display stp instance 2 brief

MSTID  Port                     Role  STP State          Protection

2    GigabitEthernet0/0/10       DESI  FORWARDING      NONE

2    GigabitEthernet0/0/11       DESI  FORWARDING      NONE

2    GigabitEthernet0/0/13       DESI  FORWARDING      NONE
```
``
S2 上所有接口都是指定接口，S2 为MSTI1 的根桥。

步骤 2 VRRP 基础配置 在S1、S2 均创建VLANIF 10、20，分别加入VRRP 组10、20，手动配置VRRP 优先级，使 得S1 的VLAN10 成为VRRP Master、S2 的VLAN20 成为VRRP Master。

```cli
#创建VLANIF

[S1]interface Vlanif10

[S1-Vlanif10] ip address 10.0.10.1 255.255.255.0

[S1-Vlanif10] quit

[S1]interface Vlanif20

[S1-Vlanif20] ip address 10.0.20.1 255.255.255.0

[S1-Vlanif20] quit

[S2]interface Vlanif10

[S2-Vlanif10] ip address 10.0.10.2 255.255.255.0

[S2-Vlanif10] quit

[S2]interface Vlanif20

[S2-Vlanif20] ip address 10.0.20.2 255.255.255.0

[S2-Vlanif20] quit

#S1 上配置VRRP

[S1]interface Vlanif 10

[S1-Vlanif10] vrrp vrid 10 virtual-ip 10.0.10.254

[S1-Vlanif10] vrrp vrid 10 priority 120

[S1-Vlanif10] quit

[S1]interface Vlanif 20

[S1-Vlanif20] vrrp vrid 20 virtual-ip 10.0.20.254

[S1-Vlanif20] quit

#配置VLAN10 的VRRP 优先级为120，VLAN20 保持默认的100。

#S2 上配置VRRP

[S2]interface Vlanif10

[S2-Vlanif10] vrrp vrid 10 virtual-ip 10.0.10.254

[S2-Vlanif10] quit

[S2]interface Vlanif20

[S2-Vlanif20] vrrp vrid 20 virtual-ip 10.0.20.254

[S2-Vlanif20] vrrp vrid 20 priority 120

[S2-Vlanif20] quit

#配置VLAN20 的VRRP 优先级为120，VLAN10 保持默认的100。

#查看VRRP 组状态

<S1>display vrrp brief VRID State        Interface                  Type     Virtual IP ----------------------------------------------------------------

10    Master        Vlanif10                 Normal  10.0.10.254

20    Backup       Vlanif20                 Normal  10.0.20.254

---------------------------------------------------------------- Total:2     Master:1    Backup:1     Non-active:0

[S2]display vrrp brief

VRID State        Interface                  Type     Virtual IP ----------------------------------------------------------------

10    Backup       Vlanif10                 Normal  10.0.10.254

20    Master        Vlanif20                 Normal  10.0.20.254

---------------------------------------------------------------- Total:2     Master:1    Backup:1     Non-active:0
```
``
VRRP 组状态与配置预期结果一致。
``
步骤 3 配置VRRP 与BFD 联动进行快速切换 在S1、S2 上配置BFD 单跳检测，检测VLANIF 接口之间的连通性，将VRRP 与BFD 联动， 当BFD 会话状态Down 时，增加VRRP Backup 设备的优先级。

```cli
#在S1 上配置BFD 会话

[S1]bfd

[S1-bfd] quit

[S1]bfd vlanif10 bind peer-ip 10.0.10.2 interface Vlanif10

[S1-bfd-session-vlanif10] discriminator local 1

[S1-bfd-session-vlanif10] discriminator remote 2

[S1-bfd-session-vlanif10] min-tx-interval 100

[S1-bfd-session-vlanif10] min-rx-interval 100

[S1-bfd-session-vlanif10] commit

[S1-bfd-session-vlanif10] quit

[S1]bfd vlanif20 bind peer-ip 10.0.20.2 interface Vlanif20

[S1-bfd-session-vlanif20] discriminator local 11

[S1-bfd-session-vlanif20] discriminator remote 22

[S1-bfd-session-vlanif20] min-tx-interval 100

[S1-bfd-session-vlanif20] min-rx-interval 100

[S1-bfd-session-vlanif20] commit

[S1-bfd-session-vlanif20] quit

#在S2 上配置BFD 会话

[S2]bfd

[S2-bfd] quit

[S2]bfd vlanif10 bind peer-ip 10.0.10.1 interface Vlanif10

[S2-bfd-session-vlanif10] discriminator local 2

[S2-bfd-session-vlanif10] discriminator remote 1

[S2-bfd-session-vlanif10] min-tx-interval 100

[S2-bfd-session-vlanif10] min-rx-interval 100

[S2-bfd-session-vlanif10] commit

[S2-bfd-session-vlanif10] quit

[S2]bfd vlanif20 bind peer-ip 10.0.20.1 interface Vlanif20

[S2-bfd-session-vlanif20] discriminator local 22

[S2-bfd-session-vlanif20] discriminator remote 11

[S2-bfd-session-vlanif20] min-tx-interval 100

[S2-bfd-session-vlanif20] min-rx-interval 100

[S2-bfd-session-vlanif20] commit

[S2-bfd-session-vlanif20] quit

#检查BFD 会话状态

[S1]display bfd session all

-------------------------------------------------------------------------------- Local Remote     PeerIpAddr      State     Type        InterfaceName --------------------------------------------------------------------------------

1     2          10.0.10.2       Up        S_IP_IF     Vlanif10

11    22         10.0.20.2       Up        S_IP_IF     Vlanif20

-------------------------------------------------------------------------------- Total UP/DOWN Session Number : 2/0

[S2]display bfd session all

-------------------------------------------------------------------------------- Local Remote     PeerIpAddr      State     Type        InterfaceName --------------------------------------------------------------------------------

2     1          10.0.10.1       Up        S_IP_IF     Vlanif10

22    11         10.0.20.1       Up        S_IP_IF     Vlanif20

-------------------------------------------------------------------------------- Total UP/DOWN Session Number : 2/0
```
``
此时S1、S2 上BFD 会话状态都为Up。

```cli
#配置VRRP 与BFD 联动

[S1]interface Vlanif20

[S1-Vlanif20] vrrp vrid 20 track bfd-session 11 increased 30

[S1-Vlanif20] quit

[S2]interface Vlanif10

[S2-Vlanif10] vrrp vrid 10 track bfd-session 2 increased 30

[S2-Vlanif10] quit
```
``
注意，此处的bfd-session 号为本地的BFD discriminator，只需要在Backup 状态的接口上配 置联动，BFD 会话Down 时增加本地的VRRP 优先级。

```cli
#关闭S1 上所有接口，模拟链路故障

[S1]interface GigabitEthernet0/0/10

[S1-GigabitEthernet0/0/10] shutdown

[S1-GigabitEthernet0/0/10] quit

[S1]interface GigabitEthernet0/0/11

[S1-GigabitEthernet0/0/11] shutdown

[S1-GigabitEthernet0/0/11] quit

[S1]interface GigabitEthernet0/0/12

[S1-GigabitEthernet0/0/12] shutdown

[S1-GigabitEthernet0/0/12] quit

#在S2 上查看BFD 会话状态

<S2>display bfd session all

-------------------------------------------------------------------------------- Local Remote     PeerIpAddr      State     Type        InterfaceName --------------------------------------------------------------------------------

2     1          10.0.10.1       Down      S_IP_IF     Vlanif10

22    11         10.0.20.1       Down      S_IP_IF     Vlanif20

-------------------------------------------------------------------------------- Total UP/DOWN Session Number : 0/2
```
``
此时两个BFD 会话状态立马变为Down。

```cli
#在S2 上查看VRRP 组状态

<S2>display vrrp brief VRID  State        Interface                Type     Virtual IP ----------------------------------------------------------------

10    Master       Vlanif10                 Normal   10.0.10.254

20    Master       Vlanif20                 Normal   10.0.20.254

---------------------------------------------------------------- Total:2     Master:2     Backup:0     Non-active:0

VRRP
```
``
组10、20 的Master 此时都是S2。

```cli
#在S2 上查看VRRP 组的状态和配置参数信息

[S2]display vrrp

Vlanif10 | Virtual Router 10

State : Master Virtual IP : 10.0.10.254 Master IP : 10.0.10.2 PriorityRun : 130 PriorityConfig : 100 MasterPriority : 130 Preempt : YES   Delay Time : 0 s TimerRun : 1 s TimerConfig : 1 s Auth type : NONE Virtual MAC : 0000-5e00-010a Check TTL : YES Config type : normal-vrrp Track BFD : 2  Priority increased : 30 BFD-session state : DOWN Create time : 2020-06-05 11:01:54 UTC-08:00 Last change time : 2020-06-05 11:31:15 UTC-08:00

Vlanif20 | Virtual Router 20

State : Master Virtual IP : 10.0.20.254 Master IP : 10.0.20.2 PriorityRun : 120 PriorityConfig : 120 MasterPriority : 120 Preempt : YES   Delay Time : 0 s TimerRun : 1 s TimerConfig : 1 s
```
``
Auth type : NONE Virtual MAC : 0000-5e00-0114 Check TTL : YES Config type : normal-vrrp Create time : 2020-06-05 11:01:54 UTC-08:00 Last change time : 2020-06-05 11:01:55 UTC-08:00
``
VRRP 组10 的优先级此时为130，BFD 会话状态为Down，BFD 将VRRP 组10 的优先级提升
``
了30。

## 8.1.3 思考题

在什么情况下，设备发送的VRRP 报文中优先级为255？
``
## 8.1.4 配置参考

S1 设备配置

```cli
sysname S1

vlan batch 10 20

stp instance 1 root primary

stp instance 2 root secondary

stp region-configuration

region-name hcip revision-level 1 instance 1 vlan 10 instance 2 vlan 20 active region-configuration

bfd

interface Vlanif10

ip address 10.0.10.1 255.255.255.0

vrrp vrid 10 virtual-ip 10.0.10.254

vrrp vrid 10 priority 120

interface Vlanif20

ip address 10.0.20.1 255.255.255.0

vrrp vrid 20 virtual-ip 10.0.20.254

vrrp vrid 20 track bfd-session 11 increased 30

interface GigabitEthernet0/0/10
```
``
shutdown port link-type trunk port trunk allow-pass vlan 10 20

```cli
interface GigabitEthernet0/0/11
```
``
shutdown port link-type trunk port trunk allow-pass vlan 10 20

```cli
interface GigabitEthernet0/0/12
```
``
shutdown port link-type trunk port trunk allow-pass vlan 10 20

bfd vlanif10 bind peer-ip 10.0.10.2 interface Vlanif10 discriminator local 1 discriminator remote 2 min-tx-interval 100 min-rx-interval 100 commit

bfd vlanif20 bind peer-ip 10.0.20.2 interface Vlanif20 discriminator local 11 discriminator remote 22 min-tx-interval 100 min-rx-interval 100 commit

return
``
S2 设备配置

```cli
sysname S2

vlan batch 10 20

stp instance 1 root secondary

stp instance 2 root primary

stp region-configuration

region-name hcip revision-level 1 instance 1 vlan 10 instance 2 vlan 20 active region-configuration

bfd

interface Vlanif10

ip address 10.0.10.2 255.255.255.0

vrrp vrid 10 virtual-ip 10.0.10.254

vrrp vrid 10 track bfd-session 2 increased 30

interface Vlanif20

ip address 10.0.20.2 255.255.255.0

vrrp vrid 20 virtual-ip 10.0.20.254

vrrp vrid 20 priority 120

interface GigabitEthernet0/0/10

port link-type trunk port trunk allow-pass vlan 10 20

interface GigabitEthernet0/0/11

port link-type trunk port trunk allow-pass vlan 10 20

interface GigabitEthernet0/0/13

port link-type trunk port trunk allow-pass vlan 10 20

bfd vlanif10 bind peer-ip 10.0.10.1 interface Vlanif10 discriminator local 2 discriminator remote 1 min-tx-interval 100 min-rx-interval 100 commit

bfd vlanif20 bind peer-ip 10.0.20.1 interface Vlanif20 discriminator local 22 discriminator remote 11 min-tx-interval 100 min-rx-interval 100 commit

return
```
``
S3 设备配置

```cli
sysname S3

vlan batch 10 20

stp region-configuration

region-name hcip revision-level 1 instance 1 vlan 10 instance 2 vlan 20 active region-configuration

interface GigabitEthernet0/0/1

port link-type trunk port trunk allow-pass vlan 10 20

interface GigabitEthernet0/0/2

port link-type trunk port trunk allow-pass vlan 10 20

return
```
``