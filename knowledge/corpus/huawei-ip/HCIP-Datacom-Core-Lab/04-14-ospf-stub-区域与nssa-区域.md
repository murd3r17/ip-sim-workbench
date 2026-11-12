---
doc_id: "hcip-datacom-core-lab-04"
title: "1.4 OSPF Stub 区域与NSSA 区域"
book: "HCIP-Datacom-Core-Lab"
book_title: "HCIP-Datacom-Core Technology V1.0 实验手册"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "lab"
source_pdf: "HCIP-Datacom-Core Technology V1.0 实验手册.pdf"
seq: 4
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 1.4 OSPF Stub 区域与NSSA 区域

## 1.4.1 实验介绍

1.4.1.1 学习目标

- 实现OSPF Stub 区域的配置
- 实现OSPF NSSA 区域的配置
- 描述Type-7 LSA 的内容
- 描述Type-7 LSA 与Type-5 LSA 之间的转换过程

1.4.1.2 实验组网介绍

图1-4 OSPF Stub 区域与NSSA 区域 设备互联方式及IP 地址规划如图所示，OSPF 区域规划如下： 1. R1 与R3 的互联接口、R1 的Loopback0 接口属于OSPF 区域2。 2. R3 与R4 的互联接口以及它们的Loopback0 接口属于OSPF 区域0。 3. R4 与R5 的互联接口属于OSPF 区域1，R5 的Loopback0 接口不属于任何区域。 4. R2 与R3 的互联接口属于OSPF 区域3，R2 的Loopback0 接口不属于任何区域。

1.4.1.3 实验背景

你是公司的网络管理员。现在公司的网络中有五台AR 路由器，其中R2、R3 和R4 在公司总 部。R5 在公司分部，R1 在公司的另外一个分部。

为了减轻分部设备的压力，你设置区域1 为NSSA 区域、区域2 为Stub 区域。 同时为了明确设备的Router ID，你配置设备使用固定的地址作为Router ID。

## 1.4.2 实验任务

1.4.2.1 任务思路

1. 设备IP 地址配置。
2. 按照规划配置OSPF 区域。
3. 检查OSPF 配置结果，检查OSPF 邻居关系状态，检查OSFP 路由表。
4. 在R2、R5 上将外部路由引入到OSPF 中。
5. 配置区域2 为Stub 区域，观察区域2 内OSPF 路由表、LSDB 的变化。
6. 配置区域1 为NSSA 区域，观察区域1 内OSPF 路由表、LSDB 的变化。
7. 查看R4 的OSPF 路由器身份，在R4 上观察Type-7 LSA 向Type-5 LSA 的转换。

1.4.2.2 任务步骤

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
#配置R1 的GE0/0/1、Loopback0 接口IP 地址

[R1]interface LoopBack0

[R1-LoopBack0] ip address 10.0.1.1 255.255.255.0

[R1-LoopBack0] quit

[R1]interface GigabitEthernet0/0/1

[R1-GigabitEthernet0/0/1] ip address 10.0.13.1 255.255.255.0

[R1-GigabitEthernet0/0/1] quit

#配置R2 的GE0/0/2、Loopback0 接口IP 地址

[R2]interface GigabitEthernet0/0/2

[R2-GigabitEthernet0/0/2] ip address 10.0.23.2 255.255.255.0

[R2-GigabitEthernet0/0/2] quit

[R2]interface LoopBack0

[R2-LoopBack0] ip address 10.0.2.2 255.255.255.0

[R2-LoopBack0] quit

#配置R3 的GE0/0/1、GE0/0/2、GE0/0/3、Loopback0 接口IP 地址

[R3]interface LoopBack0

[R3-LoopBack0] ip address 10.0.3.3 255.255.255.0

[R3-LoopBack0] quit

[R3]interface GigabitEthernet0/0/1

[R3-GigabitEthernet0/0/1] ip address 10.0.13.3 255.255.255.0

[R3-GigabitEthernet0/0/1] quit

[R3]interface GigabitEthernet0/0/2

[R3-GigabitEthernet0/0/2] ip address 10.0.34.3 255.255.255.0

[R3-GigabitEthernet0/0/2] quit

[R3]interface GigabitEthernet0/0/3

[R3-GigabitEthernet0/0/3] ip address 10.0.23.3 255.255.255.0

[R3-GigabitEthernet0/0/3] quit

#配置R4 的GE0/0/2、GE0/0/3、Loopback0 接口IP 地址

[R4]interface LoopBack0

[R4-LoopBack0] ip address 10.0.4.4 255.255.255.0

[R4-LoopBack0] quit

[R4]interface GigabitEthernet0/0/2

[R4-GigabitEthernet0/0/2] ip address 10.0.45.4 255.255.255.0

[R4-GigabitEthernet0/0/2] quit

[R4]interface GigabitEthernet0/0/3

[R4-GigabitEthernet0/0/3] ip address 10.0.34.4 255.255.255.0

[R4-GigabitEthernet0/0/3] quit

#配置R5 的GE0/0/3、Loopback0 接口IP 地址

[R5]interface LoopBack0

[R5-LoopBack0] ip address 10.0.5.5 255.255.255.0

[R5-LoopBack0] quit

[R5]interface GigabitEthernet0/0/3

[R5-GigabitEthernet0/0/3] ip address 10.0.45.5 255.255.255.0

[R5-GigabitEthernet0/0/3] quit

#在R3、R5 上检查互联地址连通性

<R3>ping -c 1 10.0.13.1 PING 10.0.13.1: 56  data bytes, press CTRL_C to break Reply from 10.0.13.1: bytes=56 Sequence=1 ttl=255 time=40 ms

--- 10.0.13.1 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 40/40/40 ms

<R3>ping -c 1 10.0.23.2 PING 10.0.23.2: 56  data bytes, press CTRL_C to break Reply from 10.0.23.2: bytes=56 Sequence=1 ttl=255 time=60 ms

--- 10.0.23.2 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 60/60/60 ms

<R3>ping -c 1 10.0.34.4 PING 10.0.34.4: 56  data bytes, press CTRL_C to break Reply from 10.0.34.4: bytes=56 Sequence=1 ttl=255 time=60 ms

--- 10.0.34.4 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 60/60/60 ms

<R5>ping -c 1 10.0.45.4 PING 10.0.45.4: 56  data bytes, press CTRL_C to break Reply from 10.0.45.4: bytes=56 Sequence=1 ttl=255 time=70 ms

--- 10.0.45.4 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 70/70/70 ms
```

步骤 2 配置多区域OSPF 按照规划配置OSPF，手动指定Loopback0 接口地址为OSPF Router ID，修改Loopback0 接 口的网络类型为Broadcast。

```cli
#配置R1

[R1] ospf 1 router-id 10.0.1.1

[R1-ospf-1] area 0.0.0.2

[R1-ospf-1-area-0.0.0.2] network 10.0.1.1 0.0.0.0

[R1-ospf-1-area-0.0.0.2] network 10.0.13.1 0.0.0.0

[R1-ospf-1-area-0.0.0.2] quit

[R1-ospf-1] quit

[R1] interface LoopBack0

[R1-LoopBack0] ospf network-type broadcast

#配置R2

[R2] ospf 1 router-id 10.0.2.2

[R2-ospf-1] area 0.0.0.3

[R2-ospf-1-area-0.0.0.3] network 10.0.23.2 0.0.0.0

[R2-ospf-1-area-0.0.0.3] quit

[R2-ospf-1] quit

[R2] interface LoopBack0

[R2-LoopBack0] ospf network-type broadcast

#配置R3

[R3] ospf 1 router-id 10.0.3.3

[R3-ospf-1] area 0.0.0.0

[R3-ospf-1-area-0.0.0.0] network 10.0.3.3 0.0.0.0

[R3-ospf-1-area-0.0.0.0] network 10.0.34.3 0.0.0.0

[R3-ospf-1-area-0.0.0.0] area 0.0.0.2

[R3-ospf-1-area-0.0.0.2] network 10.0.13.3 0.0.0.0

[R3-ospf-1-area-0.0.0.2] area 0.0.0.3

[R3-ospf-1-area-0.0.0.3] network 10.0.23.3 0.0.0.0

[R3-ospf-1-area-0.0.0.3] quit

[R3-ospf-1] quit

[R3] interface LoopBack0

[R3-LoopBack0] ospf network-type broadcast

#配置R4

[R4] ospf 1 router-id 10.0.4.4

[R4-ospf-1] area 0.0.0.0

[R4-ospf-1-area-0.0.0.0] network 10.0.4.4 0.0.0.0

[R4-ospf-1-area-0.0.0.0] network 10.0.34.4 0.0.0.0

[R4-ospf-1-area-0.0.0.0] area 0.0.0.1

[R4-ospf-1-area-0.0.0.1] network 10.0.45.4 0.0.0.0

[R4-ospf-1-area-0.0.0.1] quit

[R4-ospf-1] quit

[R4] interface LoopBack0

[R4-LoopBack0] ospf network-type broadcast

#配置R5

[R5] ospf 1 router-id 10.0.5.5

[R5-ospf-1] area 1

[R5-ospf-1-area-0.0.0.1] network 10.0.45.5 0.0.0.0

[R5-ospf-1-area-0.0.0.1] quit

[R5-ospf-1] quit

[R5] interface LoopBack0

[R5-LoopBack0] ospf network-type broadcast
```

步骤 3 检查OSPF 多区域配置

```cli
#在R3 上检查OSPF 邻居的概要信息

<R3>display ospf peer brief

OSPF Process 1 with Router ID 10.0.3.3

Peer Statistic Information ---------------------------------------------------------------------------- Area Id          Interface                      Neighbor id      State

0.0.0.0          GigabitEthernet0/0/2             10.0.4.4         Full

0.0.0.2          GigabitEthernet0/0/1             10.0.1.1         Full

0.0.0.3          GigabitEthernet0/0/3             10.0.2.2         Full

----------------------------------------------------------------------------

#在R5 上检查OSPF 邻居的概要信息

<R5>display ospf peer brief

OSPF Process 1 with Router ID 10.0.5.5

Peer Statistic Information ---------------------------------------------------------------------------- Area Id          Interface                      Neighbor id      State

0.0.0.1          GigabitEthernet0/0/3             10.0.4.4         Full

----------------------------------------------------------------------------
```

从输出信息可以判断出所有设备之间的OSPF 邻居关系状态正常。

```cli
#在R3 上查看OSPF 路由表

<R3>display ospf routing

OSPF Process 1 with Router ID 10.0.3.3

Routing Tables

Routing for Network Destination        Cost  Type       NextHop      AdvRouter       Area 10.0.3.0/24        0     Stub       10.0.3.3        10.0.3.3        0.0.0.0 10.0.13.0/24       1     Transit     10.0.13.3       10.0.3.3        0.0.0.2 10.0.23.0/24       1     Transit     10.0.23.3       10.0.3.3        0.0.0.3 10.0.34.0/24       1     Transit     10.0.34.3       10.0.3.3        0.0.0.0 10.0.1.0/24        1     Stub       10.0.13.1       10.0.1.1        0.0.0.2 10.0.4.0/24        1     Stub       10.0.34.4       10.0.4.4        0.0.0.0 10.0.45.0/24       2     Inter-area   10.0.34.4       10.0.4.4        0.0.0.0

Total Nets: 7 Intra Area: 6  Inter Area: 1  ASE: 0  NSSA: 0
```

除了未激活OSPF 的R2 Loopback0 接口、R5 Loopback0 接口，R3 已经学习到其余接口路 由。

步骤 4 配置将外部路由引入到OSPF 中

```cli
#将R5 的Loopback0 接口路由引入到OSPF 中

[R5] ospf 1

[R5-ospf-1] import-route direct

#在R2 上配置缺省路由，且指定出接口为 Loopback0 接口，并将该缺省路由引入到OSPF
```

中，外部路由类型设置为1，Cost 值设置为20，不携带always 参数

```cli
[R2] ip route-static 0.0.0.0 0.0.0.0 LoopBack 0

[R2] ospf 1

[R2-ospf-1] default-route-advertise type 1 cost 20

#在R3 上查看引入的外部路由，并测试其连通性

<R3>display ospf routing 0.0.0.0

OSPF Process 1 with Router ID 10.0.3.3

Destination : 0.0.0.0/0 AdverRouter : 10.0.2.2                 Tag       : 1
```

Cost        : 21                       Type      : Type1 NextHop     : 10.0.23.2                Interface : GigabitEthernet0/0/3 Priority    : Low                      Age       : 00h01m15s

```cli
<R3>display ospf routing 10.0.5.5

OSPF Process 1 with Router ID 10.0.3.3

Destination : 10.0.5.0/24 AdverRouter : 10.0.5.5                 Tag       : 1 Cost        : 1                        Type      : Type2 NextHop     : 10.0.34.4                Interface : GigabitEthernet0/0/2 Priority    : Low                      Age       : 00h05m20s

<R3>ping -c 1 10.0.5.5 PING 10.0.5.5: 56  data bytes, press CTRL_C to break Reply from 10.0.5.5: bytes=56 Sequence=1 ttl=254 time=50 ms

--- 10.0.5.5 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 50/50/50 ms

<R3>ping -c 1 10.0.2.2 PING 10.0.2.2: 56  data bytes, press CTRL_C to break Reply from 10.0.2.2: bytes=56 Sequence=1 ttl=255 time=50 ms

--- 10.0.2.2 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 50/50/50 ms
```

步骤 5 配置区域2 为Stub 区域

```cli
#在R1 上查看OSPF 路由表

<R1>display ospf routing

OSPF Process 1 with Router ID 10.0.1.1

Routing Tables

Routing for Network Destination        Cost  Type       NextHop       AdvRouter       Area 10.0.1.0/24        0     Stub       10.0.1.1        10.0.1.1        0.0.0.2 10.0.13.0/24       1     Transit     10.0.13.1       10.0.1.1        0.0.0.2 10.0.3.0/24        1     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2 10.0.4.0/24        2     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2 10.0.23.0/24       2     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2 10.0.34.0/24       2     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2 10.0.45.0/24       3     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2

Routing for ASEs Destination        Cost      Type       Tag         NextHop       AdvRouter

0.0.0.0/0          22        Type1      1           10.0.13.3       10.0.2.2 10.0.5.0/24        1         Type2      1           10.0.13.3       10.0.5.5

Total Nets: 9 Intra Area: 2  Inter Area: 5  ASE: 2  NSSA: 0
```

此时默认路由为OSPF 外部路由。

```cli
#在R1、R3 上配置区域2 为Stub 区域

[R1] ospf 1

[R1-ospf-1] area 0.0.0.2

[R1-ospf-1-area-0.0.0.2] stub

[R3] ospf 1

[R3-ospf-1] area 0.0.0.2

[R3-ospf-1-area-0.0.0.2] stub

#再次在R1 上查看OSPF 路由表

<R1>display ospf routing

OSPF Process 1 with Router ID 10.0.1.1

Routing Tables

Routing for Network Destination        Cost  Type       NextHop      AdvRouter       Area 10.0.1.0/24        0     Stub       10.0.1.1        10.0.1.1        0.0.0.2 10.0.13.0/24       1     Transit     10.0.13.1       10.0.1.1        0.0.0.2 0.0.0.0/0          2     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2 10.0.3.0/24        1     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2 10.0.4.0/24        2     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2 10.0.23.0/24       2     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2 10.0.34.0/24       2     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2 10.0.45.0/24       3     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2

Total Nets: 8 Intra Area: 2  Inter Area: 6  ASE: 0  NSSA: 0
```

此时R1 上不存在OSPF 外部路由，原本的OSPF 外部路由条目0.0.0.0/0、10.0.5.0/24 被一条 缺省的OSPF 区域间路由所取代。

```cli
#查看R1 的OSPF LSDB

<R1>display ospf lsdb

OSPF Process 1 with Router ID 10.0.1.1

Link State Database

Area: 0.0.0.2 Type      LinkState ID    AdvRouter        Age   Len   Sequence   Metric Router     10.0.3.3       10.0.3.3          628  36    80000004      1 Router     10.0.1.1       10.0.1.1          619  48    80000007      0 Network   10.0.13.1       10.0.1.1          619  32    80000002      0

Sum-Net   0.0.0.0        10.0.3.3          631  28    80000001      1 Sum-Net   10.0.34.0       10.0.3.3          631  28    80000001      1 Sum-Net   10.0.3.0       10.0.3.3          631  28    80000001      0 Sum-Net   10.0.4.0       10.0.3.3          631  28    80000001      1 Sum-Net   10.0.45.0       10.0.3.3          631  28    80000001      2 Sum-Net   10.0.23.0       10.0.3.3          631  28    80000001      1 R1 上
```

此时不存在Type-4 LSA、Type-5 LSA，去往OSPF 域外通过ABR 生成的Type-3 LSA 所 携带的缺省路由实现。同时此时前往其他区域的Type-3 LSA 依旧存在。 以上验证了将一个区域配置为Stub 区域以后，ABR 会阻断Type-4 LSA、Type-5 LSA 向该区 域发送，并通过Type-3 LSA 向该区域内泛洪一条默认路由指向ABR 自身。

```cli
#在R3 上配置区域2 为Totally Stub 区域

[R3] ospf 1

[R3-ospf-1] area 0.0.0.2

[R3-ospf-1-area-0.0.0.2] stub no-summary

#再次在R1 上查看OSPF 路由表、LSDB

<R1>display ospf routing

OSPF Process 1 with Router ID 10.0.1.1

Routing Tables

Routing for Network Destination        Cost  Type       NextHop      AdvRouter       Area 10.0.1.0/24        0     Stub       10.0.1.1        10.0.1.1        0.0.0.2 10.0.13.0/24       1     Transit     10.0.13.1       10.0.1.1        0.0.0.2 0.0.0.0/0          2     Inter-area   10.0.13.3       10.0.3.3        0.0.0.2

Total Nets: 3 Intra Area: 2  Inter Area: 1  ASE: 0  NSSA: 0

<R1>display ospf lsdb

OSPF Process 1 with Router ID 10.0.1.1

Link State Database

Area: 0.0.0.2 Type      LinkState ID    AdvRouter        Age  Len    Sequence   Metric Router     10.0.3.3       10.0.3.3          125  36    80000005      1 Router     10.0.1.1       10.0.1.1          121  48    8000000C       0 Network   10.0.13.1       10.0.1.1          121  32    80000002      0 Sum-Net   0.0.0.0        10.0.3.3          961  28    80000001      1
```

此时原本多条OSPF 区域间路由只剩一条0.0.0.0/0 缺省路由，LSDB 中Type-3 LSA 只剩一条 0.0.0.0。 这就验证了Totally Stub 区域中ABR 会阻断了Type-3 LSA、Type-4 LSA、Type-5 LSA，并生 成一条Type-3 LSA，通告一条指向自身的缺省路由。

步骤 6 配置区域1 为NSSA 区域

```cli
#查看R4 的OSPF 路由表

<R4>display ospf routing

OSPF Process 1 with Router ID 10.0.4.4

Routing Tables

Routing for Network Destination        Cost  Type       NextHop      AdvRouter       Area 10.0.4.0/24        0     Stub       10.0.4.4        10.0.4.4        0.0.0.0 10.0.34.0/24       1     Transit     10.0.34.4       10.0.4.4        0.0.0.0 10.0.45.0/24       1     Transit     10.0.45.4       10.0.4.4        0.0.0.1 10.0.1.0/24        2     Inter-area   10.0.34.3       10.0.3.3        0.0.0.0 10.0.3.0/24        1     Stub       10.0.34.3       10.0.3.3        0.0.0.0 10.0.13.0/24       2     Inter-area   10.0.34.3       10.0.3.3        0.0.0.0 10.0.23.0/24       2     Inter-area   10.0.34.3       10.0.3.3        0.0.0.0

Routing for ASEs Destination        Cost      Type       Tag         NextHop      AdvRouter 0.0.0.0/0          22        Type1      1           10.0.34.3       10.0.2.2 10.0.5.0/24        1         Type2      1           10.0.45.5       10.0.5.5

Total Nets: 9 Intra Area: 4  Inter Area: 3  ASE: 2  NSSA: 0
```

此时R5 存在一条由Type-5 LSA 描述的外部路由10.0.5.0/24。

```cli
#查看R5 的OSPF 路由表

<R5>display ospf routing

OSPF Process 1 with Router ID 10.0.5.5

Routing Tables

Routing for Network Destination        Cost  Type       NextHop      AdvRouter       Area 10.0.45.0/24       1     Transit    10.0.45.5       10.0.5.5        0.0.0.1 10.0.1.0/24        3     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1 10.0.3.0/24        2     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1 10.0.4.0/24        1     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1 10.0.13.0/24       3     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1 10.0.23.0/24       3     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1 10.0.34.0/24       2     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1

Routing for ASEs Destination        Cost      Type       Tag         NextHop        AdvRouter 0.0.0.0/0          23        Type1      1           10.0.45.4       10.0.2.2

Total Nets: 8 Intra Area: 1  Inter Area: 6  ASE: 1  NSSA: 0
```

在R5 的OSPF 路由表中出现的缺省路由是由Type-5 LSA 所描述的，该LSA 由R2 产生。

```cli
#在R4、R5 上配置区域1 为NSSA 区域

[R4]ospf 1

[R4-ospf-1] area 0.0.0.1

[R4-ospf-1-area-0.0.0.1] nssa

[R5]ospf 1

[R5-ospf-1] area 0.0.0.1

[R5-ospf-1-area-0.0.0.1] nssa

#再次查看R5 的OSPF 路由表

<R5>display ospf routing

OSPF Process 1 with Router ID 10.0.5.5

Routing Tables

Routing for Network Destination        Cost  Type       NextHop     AdvRouter       Area 10.0.45.0/24       1     Transit    10.0.45.5       10.0.5.5        0.0.0.1 10.0.1.0/24        3     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1 10.0.3.0/24        2     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1 10.0.4.0/24        1     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1 10.0.13.0/24       3     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1 10.0.23.0/24       3     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1 10.0.34.0/24       2     Inter-area  10.0.45.4       10.0.4.4        0.0.0.1

Routing for NSSAs Destination        Cost      Type       Tag         NextHop       AdvRouter 0.0.0.0/0          1         Type2      1           10.0.45.4       10.0.4.4

Total Nets: 8 Intra Area: 1  Inter Area: 6  ASE: 0  NSSA: 1
```

此时不存在由R2 发布的缺省路由，存在一条由R4 发布的Type-7 LSA 描述的OSPF 缺省路 由。

```cli
#查看R5 LSDB

<R5>display ospf lsdb

OSPF Process 1 with Router ID 10.0.5.5

Link State Database

Area: 0.0.0.1 Type      LinkState ID    AdvRouter          Age  Len   Sequence   Metric Router      10.0.5.5       10.0.5.5          100  36    80000005      1 Router      10.0.4.4       10.0.4.4          105  36    80000005      1 Network    10.0.45.5       10.0.5.5          100  32    80000002      0 Sum-Net    10.0.34.0       10.0.4.4          151  28    80000001      1 Sum-Net    10.0.13.0       10.0.4.4          151  28    80000001      2 Sum-Net    10.0.3.0       10.0.4.4          151  28    80000001      1 Sum-Net    10.0.1.0       10.0.4.4          151  28    80000001      2

Sum-Net    10.0.4.0       10.0.4.4          151  28    80000001      0 Sum-Net    10.0.23.0       10.0.4.4          151  28    80000001      2 NSSA     10.0.5.0       10.0.5.5          143  36    80000001      1 NSSA     10.0.45.0       10.0.5.5          143  36    80000002      1 NSSA     0.0.0.0        10.0.4.4          151  36    80000001      1
```

此时不存在Type-4 LSA、Type-5 LSA，外部路由以Type-7 LSA（NSSA）的形式存在。

```cli
#查看R4 的OSPF 路由表

[R4]display ospf routing

OSPF Process 1 with Router ID 10.0.4.4

Routing Tables

Routing for Network Destination        Cost  Type       NextHop       AdvRouter       Area 10.0.4.0/24        0     Stub       10.0.4.4        10.0.4.4        0.0.0.0 10.0.34.0/24       1     Transit     10.0.34.4       10.0.4.4        0.0.0.0 10.0.45.0/24       1     Transit     10.0.45.4       10.0.4.4        0.0.0.1 10.0.1.0/24        2     Inter-area   10.0.34.3       10.0.3.3        0.0.0.0 10.0.3.0/24        1     Stub       10.0.34.3       10.0.3.3        0.0.0.0 10.0.13.0/24       2     Inter-area   10.0.34.3       10.0.3.3        0.0.0.0 10.0.23.0/24       2     Inter-area   10.0.34.3       10.0.3.3        0.0.0.0

Routing for ASEs Destination        Cost      Type       Tag         NextHop       AdvRouter 0.0.0.0/0          22        Type1      1           10.0.34.3       10.0.2.2

Routing for NSSAs Destination        Cost      Type       Tag         NextHop       AdvRouter 10.0.5.0/24        1         Type2      1           10.0.45.5       10.0.5.5

Total Nets: 9 Intra Area: 4  Inter Area: 3  ASE: 1  NSSA: 1 R5
```

所引入的外部路由10.0.5.0/24 由Type-7 LSA 所描述。
以上验证了NSSA 区域阻断了外部的Type-4 LSA、Type-5 LSA 进入，并且ABR 会向区域内 下发一条由Type-7 LSA 描述的默认路由。ASBR 向NSSA 区域内下发Type-7 LSA 描述本区域 中引入的外部路由。

步骤 7 观察NSSA 对OSPF 产生的影响

```cli
#在R4 上查看OSPF 概要信息

<R4>display ospf brief

OSPF Process 1 with Router ID 10.0.4.4

OSPF Protocol Information

RouterID: 10.0.4.4         Border Router:  AREA  AS  NSSA Multi-VPN-Instance is not enabled

Global DS-TE Mode: Non-Standard IETF Mode Spf-schedule-interval: max 10000ms, start 500ms, hold 1000ms Default ASE parameters: Metric: 1 Tag: 1 Type: 2

Route Preference: 10

ASE Route Preference: 150 SPF Computation Count: 22 RFC 1583 Compatible Retransmission limitation is disabled Area Count: 2   Nssa Area Count: 1 ExChange/Loading Neighbors: 0

Area: 0.0.0.0          (MPLS TE not enabled) Authtype: None   Area flag: Normal SPF scheduled Count: 22 ExChange/Loading Neighbors: 0 Router ID conflict state: Normal

Interface: 10.0.4.4 (LoopBack0)

Cost: 0       State: DR        Type: Broadcast    MTU: 1500 Priority: 1 Designated Router: 10.0.4.4 Backup Designated Router: 0.0.0.0 Timers: Hello 10 , Dead 40 , Poll  120 , Retransmit 5 , Transmit Delay 1

Interface: 10.0.34.4 (GigabitEthernet0/0/3)

Cost: 1       State: BDR       Type: Broadcast    MTU: 1500 Priority: 1 Designated Router: 10.0.34.3 Backup Designated Router: 10.0.34.4 Timers: Hello 10 , Dead 40 , Poll  120 , Retransmit 5 , Transmit Delay 1

Area: 0.0.0.1          (MPLS TE not enabled) Authtype: None   Area flag:   NSSA SPF scheduled Count: 6 ExChange/Loading Neighbors: 0 NSSA Translator State: Elected Router ID conflict state: Normal

Interface: 10.0.45.4 (GigabitEthernet0/0/2)

Cost: 1       State: BDR       Type: Broadcast    MTU: 1500 Priority: 1 Designated Router: 10.0.45.5 Backup Designated Router: 10.0.45.4 Timers: Hello 10 , Dead 40 , Poll  120 , Retransmit 5 , Transmit Delay 1
```

在Border Router 字段可以看到R4 此时的身份为：AREA  AS  NSSA，分别代表该路由器为 ABR、ASBR 以及存在接口属于NSSA 区域。

```cli
#在R4 上观察Type-7 LSA 向Type-5 LSA 转换的过程，以10.0.5.0/24 为例观察路由信息的传递过程

<R4>display ospf lsdb nssa 10.0.5.0

OSPF Process 1 with Router ID 10.0.4.4

Area: 0.0.0.0

Link State Database

Area: 0.0.0.1 Link State Database

Type      : NSSA Ls id     : 10.0.5.0 Adv rtr   : 10.0.5.5 Ls age    : 587 Len       : 36 Options   :  NP seq#      : 80000001 chksum    : 0x3336 Net mask  : 255.255.255.0 TOS 0  Metric: 1 E type    : 2 Forwarding Address : 10.0.45.5 Tag       : 1 Priority  : Low
```

首先查看描述10.0.5.0/24 的Type-7 LSA，其options 字段为NP，表示该LSA 可以被ABR 转化成一条Type-5 LSA。

```cli
#在R4 上查看生成的用于描述10.0.5.0/24 的Type-5 LSA

<R4>display ospf lsdb ase 10.0.5.0

OSPF Process 1 with Router ID 10.0.4.4

Link State Database

Type      : External Ls id     : 10.0.5.0 Adv rtr   : 10.0.4.4 Ls age    : 753 Len       : 36 Options   :  E seq#      : 80000001 chksum    : 0xb6bc Net mask  : 255.255.255.0 TOS 0  Metric: 1 E type    : 2 Forwarding Address : 10.0.45.5 Tag       : 1 Priority  : Low
```

可以看到与Type-7 LSA 相比，其Ls id、net mask、FA 地址字段内容完全相同，adv rtr 字段值从10.0.5.5 变为了10.0.4.4，说明该Type-5 LSA 由R4 产生。

## 1.4.3 思考题

在什么场景下适合使用NSSA 区域？

## 1.4.4 配置参考

R1 设备配置

```cli
sysname R1

interface GigabitEthernet0/0/1

ip address 10.0.13.1 255.255.255.0

interface LoopBack0

ip address 10.0.1.1 255.255.255.0

ospf network-type broadcast

ospf 1 router-id 10.0.1.1

area 0.0.0.2
 network 10.0.1.1 0.0.0.0
 network 10.0.13.1 0.0.0.0
 stub
```

R2 设备配置

```cli
sysname R2

interface GigabitEthernet0/0/2

ip address 10.0.23.2 255.255.255.0

interface LoopBack0

ip address 10.0.2.2 255.255.255.0

ospf network-type broadcast

ospf 1 router-id 10.0.2.2

default-route-advertise cost 20 type 1

area 0.0.0.3
 network 10.0.23.2 0.0.0.0

ip route-static 0.0.0.0 0.0.0.0 LoopBack0
```

R3 设备配置

```cli
sysname R3

interface GigabitEthernet0/0/1

ip address 10.0.13.3 255.255.255.0

interface GigabitEthernet0/0/2

ip address 10.0.34.3 255.255.255.0

interface GigabitEthernet0/0/3

ip address 10.0.23.3 255.255.255.0

interface LoopBack0

ip address 10.0.3.3 255.255.255.0

ospf network-type broadcast

ospf 1 router-id 10.0.3.3

area 0.0.0.0
 network 10.0.3.3 0.0.0.0
 network 10.0.34.3 0.0.0.0
area 0.0.0.2
 network 10.0.13.3 0.0.0.0
 stub no-summary
area 0.0.0.3
 network 10.0.23.3 0.0.0.0
```

R4 设备配置

```cli
sysname R4

interface GigabitEthernet0/0/2

ip address 10.0.45.4 255.255.255.0

interface GigabitEthernet0/0/3

ip address 10.0.34.4 255.255.255.0

interface LoopBack0

ip address 10.0.4.4 255.255.255.0

ospf network-type broadcast

ospf 1 router-id 10.0.4.4

area 0.0.0.0
 network 10.0.4.4 0.0.0.0
 network 10.0.34.4 0.0.0.0
area 0.0.0.1
 network 10.0.45.4 0.0.0.0
 nssa
```

R5 设备配置

```cli
sysname R5

interface GigabitEthernet0/0/3

ip address 10.0.45.5 255.255.255.0

interface LoopBack0

ip address 10.0.5.5 255.255.255.0

ospf network-type broadcast

ospf 1 router-id 10.0.5.5

import-route direct

area 0.0.0.1
 network 10.0.45.5 0.0.0.0
 nssa
```
