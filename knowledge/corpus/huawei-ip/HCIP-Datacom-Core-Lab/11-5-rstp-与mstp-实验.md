---
doc_id: "hcip-datacom-core-lab-11"
title: "5 RSTP 与MSTP 实验"
book: "HCIP-Datacom-Core-Lab"
book_title: "HCIP-Datacom-Core Technology V1.0 实验手册"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "lab"
source_pdf: "HCIP-Datacom-Core Technology V1.0 实验手册.pdf"
seq: 11
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 5 RSTP 与MSTP 实验

## 5.1 RSTP、MSTP 基础配置

## 5.1.1 实验介绍

5.1.1.1 学习目标

- 实现手动修改桥优先级影响根桥选举
- 实现手动修改端口开销值控制根端口选举
- 实现手动修改端口优先级控制根端口选举
- 实现配置MSTP 以达到不同VLAN 间流量负载均衡

5.1.1.2 实验组网介绍

图5-1 RSTP、MSTP 基础配置 交换机连接方式如图所示，配置RSTP、MSTP 打破二层环路，同时手动指定根桥、备份根 桥。

5.1.1.3 实验背景

你是公司的网络管理员。公司的网络采用了备份网络，为避免环路问题，在网络中部署了 RSTP。所有的VLAN 共享一棵STP 生成树，为了实现VLAN 间数据流量的负载均衡，在网络 中部署MSTP。

## 5.1.2 实验任务

5.1.2.1 任务思路

1. 开启STP，修改STP 模式为RSTP。
2. 手动指定S1 为RSTP 根桥、S2 为RSTP 备份根桥。
3. 通过修改接口开销值，使得S4 的GE0/0/1 接口成为根端口。
4. 通过修改S1 的GE0/0/11 接口优先级，使得S2 的GE0/0/11 接口成为根端口。
5. 修改STP 模式为MSTP，创建Instance1、2，指定SW1 为MSTI1 的根桥、MSTI2 的备 份根桥，指定SW2 为MSTI2 的根桥、MSTI1 的备份根桥。

5.1.2.2 任务步骤

步骤 1 RSTP 基础配置 在S1、S2、S3、S4 上开启STP，并将STP 模式切换为RSTP

```cli
#设备命名
```
略

```cli
#关闭本实验中未使用的接口
```
略

```cli
#S1 上配置

[S1]stp enable

[S1]stp mode rstp

#S2 上配置

[S2]stp enable

[S2]stp mode rstp

#S3 上配置

[S3]stp enable

[S3]stp mode rstp

#S4 上配置

[S4]stp enable

[S4]stp mode rstp

#查看STP 的状态和统计信息摘要

<S1>display stp instance 0 brief MSTID  Port                    Role  STP State           Protection

0    GigabitEthernet0/0/10       DESI  FORWARDING      NONE

0    GigabitEthernet0/0/11       DESI  FORWARDING      NONE

0    GigabitEthernet0/0/12       DESI  FORWARDING      NONE

0    GigabitEthernet0/0/13       DESI  FORWARDING      NONE

[S2]display stp brief

MSTID  Port                    Role   STP State          Protection

0    GigabitEthernet0/0/10       ROOT  FORWARDING     NONE

0    GigabitEthernet0/0/11       ALTE  DISCARDING     NONE

0    GigabitEthernet0/0/12       ALTE  DISCARDING     NONE

0    GigabitEthernet0/0/13       DESI   FORWARDING     NONE

[S3]display stp brief

MSTID  Port                    Role    STP State         Protection

0    GigabitEthernet0/0/1        ROOT   FORWARDING    NONE

0    GigabitEthernet0/0/2        ALTE   DISCARDING    NONE

0    GigabitEthernet0/0/3        ALTE   DISCARDING    NONE

[S4]display stp brief

MSTID  Port                    Role   STP State          Protection

0    GigabitEthernet0/0/1        DESI   FORWARDING     NONE

0    GigabitEthernet0/0/2        ROOT  FORWARDING     NONE

0    GigabitEthernet0/0/3        DESI   FORWARDING     NONE
```
``
S1 上所有接口都是指定端口，S1 为根桥交换机，实际实验中，由于交换机MAC 地址的不可 确定性，实际的实验结果可能与如上结果有差异。

```cli
#在S1 上查STP 的状态和统计信息，可以看到如下内容

<S1>display stp -------[CIST Global Info][Mode RSTP]------- CIST Bridge         :32768.4c1f-cc1d-61a8 Config Times        :Hello 2s MaxAge 20s FwDly 15s MaxHop 20 Active Times        :Hello 2s MaxAge 20s FwDly 15s MaxHop 20 CIST Root/ERPC      :32768.4c1f-cc1d-61a8 / 0 CIST RegRoot/IRPC   :32768.4c1f-cc1d-61a8 / 0 CIST RootPortId     :0.0 BPDU-Protection     :Disabled TC or TCN received  :15 TC count per hello  :0

STP Converge Mode   :Normal

Time since last TC  :0 days 0h:11m:14s Number of TC        :17 Last TC occurred    :GigabitEthernet0/0/13 S1
```
``
为根桥交换机。

步骤 2 根桥选举控制 配置S1 为主根桥、S2 为备份根桥

```cli
#手动调整STP 优先级，指定S1 为主根桥、S2 为备份根桥

[S1]stp priority 4096

[S2]stp priority 8192

#在另外两台交换机保持默认桥优先级（32768）的情况下，S1 拥有最小的桥优先级，S2 次 之。

#在S1 上查看STP 的状态和统计信息，可以看到如下内容

[S1]display stp

-------[CIST Global Info][Mode RSTP]------- CIST Bridge         :4096 .4c1f-cc1d-61a8 Config Times        :Hello 2s MaxAge 20s FwDly 15s MaxHop 20 Active Times        :Hello 2s MaxAge 20s FwDly 15s MaxHop 20 CIST Root/ERPC      :4096 .4c1f-cc1d-61a8 / 0 CIST RegRoot/IRPC   :4096 .4c1f-cc1d-61a8 / 0 CIST RootPortId     :0.0 BPDU-Protection     :Disabled TC or TCN received  :75 TC count per hello  :0

STP Converge Mode   :Normal

Time since last TC  :0 days 0h:1m:16s Number of TC        :45 Last TC occurred    :GigabitEthernet0/0/10
```
``
此时S1 的桥优先级为4096，并且此时S1 依旧是根桥。

```cli
#取消S1、S2 上手动调整桥优先级的配置，使用stp root 命令指定根桥、备份根桥

[S1]undo stp priority

[S1]stp root primary

[S2]undo stp priority

[S2]stp root secondary

#S1、S2 上查看STP 的状态和统计信息，可以看到如下内容

[S1]display stp

-------[CIST Global Info][Mode RSTP]------- CIST Bridge         :0    .4c1f-cc1d-61a8 Config Times        :Hello 2s MaxAge 20s FwDly 15s MaxHop 20 Active Times        :Hello 2s MaxAge 20s FwDly 15s MaxHop 20 CIST Root/ERPC      :0    .4c1f-cc1d-61a8 / 0 CIST RegRoot/IRPC   :0    .4c1f-cc1d-61a8 / 0 CIST RootPortId     :0.0 BPDU-Protection     :Disabled CIST Root Type      :Primary root TC or TCN received  :85

TC count per hello  :0

STP Converge Mode   :Normal

Time since last TC  :0 days 0h:0m:9s Number of TC        :51 Last TC occurred    :GigabitEthernet0/0/10

[S2]display stp

-------[CIST Global Info][Mode RSTP]------- CIST Bridge         :4096 .4c1f-cc69-5bf7 Config Times        :Hello 2s MaxAge 20s FwDly 15s MaxHop 20 Active Times        :Hello 2s MaxAge 20s FwDly 15s MaxHop 20 CIST Root/ERPC      :0    .4c1f-cc1d-61a8 / 20000 CIST RegRoot/IRPC   :4096 .4c1f-cc69-5bf7 / 0 CIST RootPortId     :128.10 BPDU-Protection     :Disabled CIST Root Type      :Secondary root TC or TCN received  :213 TC count per hello  :0

STP Converge Mode   :Normal

Time since last TC  :0 days 0h:0m:35s Number of TC        :44 Last TC occurred    :GigabitEthernet0/0/12 S1
```
``
的桥优先级为0，而S2 的桥优先级为4096，此时S1 为根桥，S2 为备份根桥。

步骤 3 修改接口开销值控制根端口选举

```cli
#在S4 上查看STP 的状态和统计信息摘要

[S4]display  stp brief

MSTID  Port                     Role  STP State          Protection

0    GigabitEthernet0/0/1        ALTE  DISCARDING     NONE

0    GigabitEthernet0/0/2        ROOT  FORWARDING     NONE

0    GigabitEthernet0/0/3        DESI   FORWARDING     NONE
```
``
S4 上GE0/0/2 拥有更小的RPC（根路径开销），从而成为根端口。

```cli
#在S4 上查看GE0/0/2 接口的STP 的状态和统计信息

[S4]display stp interface GigabitEthernet 0/0/2

-------[CIST Global Info][Mode RSTP]------- CIST Bridge         :32768.4c1f-cc49-4c7c Config Times        :Hello 2s MaxAge 20s FwDly 15s MaxHop 20 Active Times        :Hello 2s MaxAge 20s FwDly 15s MaxHop 20 CIST Root/ERPC      :0    .4c1f-cc1d-61a8 / 20000 CIST RegRoot/IRPC   :32768.4c1f-cc49-4c7c / 0 CIST RootPortId     :128.2 BPDU-Protection     :Disabled TC or TCN received  :98 TC count per hello  :0

STP Converge Mode   :Normal

Time since last TC  :0 days 0h:8m:35s Number of TC        :47 Last TC occurred    :GigabitEthernet0/0/2 ----[Port2(GigabitEthernet0/0/2)][FORWARDING]----

Port Protocol       :Enabled Port Role           :Root Port Port Priority       :128 Port Cost(Dot1T )   :Config=auto / Active=20000 Designated Bridge/Port   :0.4c1f-cc1d-61a8 / 128.13 Port Edged          :Config=default / Active=disabled Point-to-point      :Config=auto / Active=true Transit Limit       :147 packets/hello-time Protection Type     :None Port STP Mode       :RSTP Port Protocol Type  :Config=auto / Active=dot1s BPDU Encapsulation  :Config=stp / Active=stp PortTimes           :Hello 2s MaxAge 20s FwDly 15s RemHop 0 TC or TCN send      :26 TC or TCN received  :40 BPDU Sent           :1747 TCN: 0, Config: 0, RST: 1747, MST: 0 BPDU Received       :1048 TCN: 0, Config: 0, RST: 1048, MST: 0
```
``
此时路径开销计算方法为Dot1t，接口的STP cost 值为20000。

```cli
#修改S4 的GE0/0/2 接口的STP cost 值为40001

[S4]interface GigabitEthernet 0/0/2

[S4-GigabitEthernet0/0/2] stp cost 40001

#再次在S4 上查看STP 的状态和统计信息摘要

<S4>display stp brief MSTID  Port                    Role   STP State          Protection

0    GigabitEthernet0/0/1        ROOT  FORWARDING     NONE

0    GigabitEthernet0/0/2        ALTE  DISCARDING     NONE

0    GigabitEthernet0/0/3        ALTE  DISCARDING     NONE
```
``
此时GE0/0/1 接口的RPC 为40000，小于GE0/0/2 接口的RPC 40001，S4 的GE0/0/1 接口 成为根端口。

步骤 4 修改接口优先级控制根端口选举

```cli
#在S2 上查看STP 的状态和统计信息摘要

[S2]display stp brief

MSTID  Port                    Role    STP State          Protection

0    GigabitEthernet0/0/10       ROOT  FORWARDING      NONE

0    GigabitEthernet0/0/11       ALTE  DISCARDING      NONE

0    GigabitEthernet0/0/12       DESI   FORWARDING      NONE

0    GigabitEthernet0/0/13       DESI   FORWARDING      NONE
```
``
S2 上GE0/0/10、GE0/0/11 接口收到的BPDU 拥有相同的RPC、网桥ID、接口优先级，此时 将会比较接收到的BPDU 接口ID 中的接口编号。

```cli
#在S1、S2 上开启LLDP，查看接口的互联关系

[S1]lldp enable

[S2]lldp enable

[S2]display lldp neighbor brief

Local Intf   Neighbor Dev             Neighbor Intf               Exptime GE0/0/10     S1                       GE0/0/10                  102 GE0/0/11     S1                       GE0/0/11                  102 GE0/0/12     S4                       GE0/0/1                   108 GE0/0/13     S3                       GE0/0/2                   103 S2
```
``
的GE0/0/10 接口对端为S1 的GE0/0/10 接口，S2 的GE0/0/11 接口对端为S1 的 GE0/0/11 接口，S2 的GE0/0/10 接口接收到的BPDU 拥有更小的接口编号，这是GE0/0/10 成为根端口的原因。

#在S1 上修改GE0/0/11 的STP 接口优先级，使其发送的BPDU 优于 GE0/0/10 发送的
``
BPDU

```cli
[S1]interface GigabitEthernet 0/0/11

[S1-GigabitEthernet0/0/11] stp port priority 64

STP
```
``
接口优先级为128，数值越小越优。

```cli
#再次查看S2 上的STP 状态和统计信息摘要

[S2]display stp brief

MSTID  Port                    Role    STP State          Protection

0    GigabitEthernet0/0/10       ROOT  FORWARDING      NONE

0    GigabitEthernet0/0/11       ALTE  DISCARDING      NONE

0    GigabitEthernet0/0/12       DESI   FORWARDING      NONE

0    GigabitEthernet0/0/13       DESI   FORWARDING      NONE
```
``
此时S2 的GE0/0/10 接口成为根端口。

步骤 5 MSTP 基础配置 在所有交换机上创建VLAN10、20、30、40、50、60、70、80，配置MSTP 域hcip，并创建 两个新的实例：Instance 1、Instance 2，将VLAN10、30、50、70 映射到Instance 1，将VLAN20、40、60、80 映射到Instance 2，同时将SW1 规划为MSTI1 的主根桥、MSTI2 的备份根桥，将SW2 规划为MSTI2 的主根桥、MSTI1 的备份根桥。

```cli
#创建VLAN

[S1]vlan batch 10 20 30 40 50 60 70 80

[S2]vlan batch 10 20 30 40 50 60 70 80

[S3]vlan batch 10 20 30 40 50 60 70 80

[S4]vlan batch 10 20 30 40 50 60 70 80

#将所有互联接口配置为Trunk 接口，放通所有VLAN
```
``
略

```cli
#修改STP 模式为MSTP

[S1]stp mode mstp

[S2]stp mode mstp

[S3]stp mode mstp

[S4]stp mode mstp

#配置MSTP

[S1]stp region-configuration

[S1-mst-region] region-name hcip

[S1-mst-region] revision-level 1

[S1-mst-region] instance 1 vlan 10 30 50 70

[S1-mst-region] instance 2 vlan 20 40 60 80

[S1-mst-region] active region-configuration

Info: This operation may take a few seconds. Please wait for a moment...done.

[S1-mst-region] quit

[S2]stp region-configuration

[S2-mst-region] region-name hcip

[S2-mst-region] revision-level 1

[S2-mst-region] instance 1 vlan 10 30 50 70

[S2-mst-region] instance 2 vlan 20 40 60 80

[S2-mst-region] active region-configuration

Info: This operation may take a few seconds. Please wait for a moment...done.

[S2-mst-region] quit

[S3]stp region-configuration

[S3-mst-region] region-name hcip

[S3-mst-region] revision-level 1

[S3-mst-region] instance 1 vlan 10 30 50 70

[S3-mst-region] instance 2 vlan 20 40 60 80

[S3-mst-region] active region-configuration

Info: This operation may take a few seconds. Please wait for a moment...done.

[S3-mst-region] quit

[S4]stp region-configuration

[S4-mst-region] region-name hcip

[S4-mst-region] revision-level 1

[S4-mst-region] instance 1 vlan 10 30 50 70

[S4-mst-region] instance 2 vlan 20 40 60 80

[S4-mst-region] active region-configuration

Info: This operation may take a few seconds. Please wait for a moment...done.

[S4-mst-region] quit

#在S1 检查MSTP 实例和VLAN 的映射关系

[S1]display stp region-configuration

Oper configuration Format selector    :0 Region name        :hcip Revision level     :1

Instance   VLANs Mapped

0       1 to 9, 11 to 19, 21 to 29, 31 to 39, 41 to 49, 51 to 59, 61 to
```
``
69, 71 to 79, 81 to 4094

1       10, 30, 50, 70

2       20, 40, 60, 80

```cli
#配置SW1 为MSTI1 的根桥、MSTI2 的备份根桥

[S1]stp instance 1 root primary

[S1]stp instance 2 root secondary

#配置SW2 为MSTI2 的根桥、MSTI1 的备份根桥

[S2]stp instance 1 root secondary

[S2]stp instance 2 root primary

#在S1 上查看MSTI1 的状态和统计信息摘要

[S1]display stp instance 1 brief

MSTID  Port                     Role  STP State          Protection

1    GigabitEthernet0/0/10       DESI  FORWARDING      NONE

1    GigabitEthernet0/0/11       DESI  FORWARDING      NONE

1    GigabitEthernet0/0/12       DESI  FORWARDING      NONE

1    GigabitEthernet0/0/13       DESI  FORWARDING      NONE
```
``
S1 上所有接口都是指定接口，S1 为MSTI1 的根桥。

```cli
#在S2 上查看MSTI2 的状态和统计信息摘要

[S2]display stp instance 2 brief

MSTID  Port                     Role  STP State          Protection

2    GigabitEthernet0/0/10       DESI  FORWARDING      NONE

2    GigabitEthernet0/0/11       DESI  FORWARDING      NONE

2    GigabitEthernet0/0/12       DESI  FORWARDING      NONE

2    GigabitEthernet0/0/13       DESI  FORWARDING      NONE
```
``
S2 上所有接口都是指定接口，S2 为MSTI2 的根桥。

## 5.1.3 思考题

相比较于STP，RTSP 优化了哪些内容？

## 5.1.4 配置参考

S1 设备配置

```cli
sysname S1

vlan batch 10 20 30 40 50 60 70 80

lldp enable

stp instance 0 root primary

stp instance 1 root primary

stp instance 2 root secondary

stp region-configuration

region-name hcip revision-level 1 instance 1 vlan 10 30 50 70 instance 2 vlan 20 40 60 80 active region-configuration

interface GigabitEthernet0/0/10

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

interface GigabitEthernet0/0/11

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

stp instance 0 port priority 64

interface GigabitEthernet0/0/12

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

interface GigabitEthernet0/0/13

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

return
```
``
S2 设备配置

```cli
sysname S2

vlan batch 10 20 30 40 50 60 70 80

lldp enable

stp instance 0 root secondary

stp instance 1 root secondary

stp instance 2 root primary

stp region-configuration

region-name hcip revision-level 1 instance 1 vlan 10 30 50 70 instance 2 vlan 20 40 60 80 active region-configuration

interface GigabitEthernet0/0/10

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

interface GigabitEthernet0/0/11

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

stp instance 0 port priority 64

interface GigabitEthernet0/0/12

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

interface GigabitEthernet0/0/13

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

return
```
``
S3 设备配置

```cli
sysname S3

vlan batch 10 20 30 40 50 60 70 80

lldp enable

stp region-configuration

region-name hcip revision-level 1 instance 1 vlan 10 30 50 70 instance 2 vlan 20 40 60 80 active region-configuration

interface GigabitEthernet0/0/1

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

interface GigabitEthernet0/0/2

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

interface GigabitEthernet0/0/3

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

return
```
``
S4 设备配置

```cli
sysname S4

vlan batch 10 20 30 40 50 60 70 80

lldp enable

stp region-configuration

region-name hcip revision-level 1 instance 1 vlan 10 30 50 70 instance 2 vlan 20 40 60 80 active region-configuration

interface GigabitEthernet0/0/1

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

interface GigabitEthernet0/0/2

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

stp instance 0 cost 40001

interface GigabitEthernet0/0/3

port link-type trunk port trunk allow-pass vlan 10 20 30 40 50 60 70 80

return
```
``