---
doc_id: "hcip-datacom-core-training-14"
title: "VRF 配置、BFD 联动与 VRRP 原理"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 14
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# VRF 配置、BFD 联动与 VRRP 原理

## VRF 与动态路由（续）

在设备上可运行多种动态路由协议，或运行同一种动态路由协议的多个进程，关联到 VPN 实例的动态路由协议进程专为该实例服务，从该进程学习到的路由加载到 VPN 实例的路由表中。

更多 BGP/MPLS IP VPN 相关内容，请参考 HCIP-Datacom-Advance 相关课程。

### 课程内容

1. VRF 基本概念
2. VRF 典型配置案例

## VRF 基本配置命令

### （1）创建实例、使能地址族、绑定接口

1. 创建 VPN 实例 / 进入 VPN 实例视图

```cli
[Huawei] ip vpn-instance vpn-instance-name
```

`ip vpn-instance` 命令用来创建 VPN 实例，并进入 VPN 实例视图。缺省情况下，未配置 VPN 实例。

2. 使能 VPN 实例的 IPv4 类型的路由通告和数据转发功能

```cli
[Huawei-vpn-instance-InstanceName] ipv4-family
```

`ipv4-family` 命令用来使能 VPN 实例的 IPv4 地址族，并进入 VPN 实例 IPv4 地址族视图。缺省情况下，未使能 VPN 实例的 IPv4 地址族。接口不能与未使能任何地址族的 VPN 实例绑定。

3. 将接口绑定到 VPN 实例

`ip binding vpn-instance` 命令用来将 PE 上的接口与 VPN 实例绑定。缺省情况下，接口不与任何 VPN 实例绑定，属于根实例。配置接口与 VPN 实例绑定后，或取消接口与 VPN 实例的绑定，都会清除该接口的 IP 地址、三层特性和 IP 相关的路由协议，如果需要应重新配置。

### （2）静态路由、动态协议与维护命令

4. 向 VPN 实例的路由表中添加静态路由

```cli
[Huawei] ip route-static vpn-instance vpn-instance-name ip-address { mask | mask-length } { nexthop-address | interface-type interface-number }
```

5. 创建与 VPN 实例绑定的动态路由协议进程（以 OSPF 为例）

```cli
[Huawei] ospf [ process-id | router-id router-id ] vpn-instance vpn-instance-name
```

注：不同 VPN 实例之间的进程号不可重叠。

6. VPN 实例维护命令

```cli
[Huawei] display ip routing-table vpn-instance vpn-instance-name
[Huawei] tracert -vpn-instance vpn-instance-name host
```

注：如果执行 ping 时没有携带 `vpn-instance` 关键字及参数，则默认在根设备上执行 ping 操作，并且所产生的 ICMP 报文根据全局路由表进行转发。tracert 操作同理。

## VRF 配置案例

### 背景介绍与需求分析

某企业内部有生产和管理两张网络，其拓扑简化如下：

- PC1 属于生产网络，PC2 属于管理网络，S1 是这两台 PC 的接入交换机，将两台 PC 分别划入 VLAN10 和 VLAN20。
- R1 上通过配置子接口作为 PC1 和 PC2 的网关。

**需求**：将生产和管理网络隔离开来，并使用静态路由实现网络内部通信。

> （原图：生产网络 `192.168.100.0/24`、管理网络 `192.168.200.0/24`；R1 GE0/0/1=`192.168.101.1/24`、GE0/0/2=`192.168.102.1/24`；PC1 `192.168.1.1` 网关 `192.168.1.254`；PC2 `192.168.2.1` 网关 `192.168.2.254`。）

R1 未部署 VRF 前的路由表示意：

| 目的网络/掩码 | 协议 | 出接口 | 下一跳 |
|---------------|------|--------|--------|
| 192.168.100.0/24 | Static | GE0/0/1 | 192.168.101.254 |
| 192.168.200.0/24 | Static | GE0/0/2 | 192.168.102.254 |
| 192.168.1.0/24 | Direct | GE0/0/0.1 | 192.168.1.254 |
| 192.168.2.0/24 | Direct | GE0/0/0.2 | 192.168.2.254 |

### 配置过程（1）：创建 VPN 实例

1. 交换机上完成 VLAN 相关配置（略）
2. 创建生产与管理网络的 VPN 实例，并使能 IPv4 地址族

```cli
[R1] ip vpn-instance production
[R1-vpn-instance-production] ipv4-family
[R1-vpn-instance-production-af-ipv4] quit
[R1-vpn-instance-production] quit
[R1] ip vpn-instance management
[R1-vpn-instance-management] ipv4-family
[R1-vpn-instance-management-af-ipv4] quit
[R1-vpn-instance-management] quit
```

### 配置过程（2）：将接口绑定到实例

```cli
[R1] interface GigabitEthernet 0/0/0.1
[R1-GigabitEthernet0/0/0.1] ip binding vpn-instance production
Info: All IPv4 related configurations on this interface are removed!
[R1-GigabitEthernet0/0/0.1] ip address 192.168.1.254 24
[R1-GigabitEthernet0/0/0.1] quit
[R1] interface GigabitEthernet 0/0/0.2
[R1-GigabitEthernet0/0/0.2] ip binding vpn-instance management
Info: All IPv4 related configurations on this interface are removed!
[R1-GigabitEthernet0/0/0.2] ip address 192.168.2.254 24
[R1-GigabitEthernet0/0/0.2] quit
```

接口绑定到实例后，接口下关于 IP 的配置将被清除，需要重新配置。

### 配置过程（3）：往实例中添加静态路由并检查

```cli
[R1] ip route-static vpn-instance production 192.168.100.0 24 192.168.101.254
[R1] ip route-static vpn-instance management 192.168.200.0 24 192.168.102.254
[R1] display ip routing-table vpn-instance production
Route Flags: R - relay, D - download to fib
Routing Tables: production
Destinations : 5 Routes : 5
Destination/Mask    Proto   Pre  Cost   Flags NextHop         Interface
...
```

### 思考题（VRF）

1. （单选题）VRF 技术可以实现（）的隔离。A. 物理层 B. 网络层 C. 数据链路层 D. 应用层
2. （判断题）缺省情况下，华为数通产品上所有三层接口都属于根实例。A. 正确 B. 错误

### 本章总结（VRF）

- VRF 技术实现了同一物理设备上不同网络之间的逻辑隔离，当在物理设备上部署多个 VRF 实例时，每一个 VRF 实例就相当于一个虚拟的网络设备。VRF 实例之间的接口和路由天然隔离，当同一个物理设备连接到多个相同的网段时，也不用担心 IP 地址冲突的问题。
- VRF 技术广泛应用在防火墙虚拟系统、BGP/MPLS IP VPN 等多个场景中。

---

## BFD 与应用联动

### 故障检测问题

> （原图：R1—SW1—R2 连接 Internet；对比动态路由故障检测与静态路由故障检测。）

- **监测模块**负责对链路状态、网络性能等进行监测，并将探测结果通知给 Track 模块。
- **Track 模块**收到监测模块的探测结果后，及时改变 Track 项的状态，并通知应用模块。
- **应用模块**根据 Track 项的状态，进行相应的处理，从而实现联动。

可联动的应用包括：VRRP、静态路由、策略路由、接口备份等。

### OSPF 与 BFD 联动（1）

OSPF 在未绑定 BFD 的情况下，链路故障检测时间由协议 Hello 机制决定，通常是秒级。通过绑定 BFD，可以实现毫秒级故障检测。

BFD 与 OSPF 联动就是将 BFD 和 OSPF 协议关联起来，BFD 将链路故障的快速检测结果告知 OSPF 协议。

1. OSPF 通过自己的 Hello 机制发现邻居并建立连接。
2. OSPF 在建立了新的邻居关系后，将邻居信息（包括目的地址和源地址等）通告给 BFD。
3. BFD 根据收到的邻居信息建立会话，会话建立以后，BFD 开始检测链路故障。
4. 正常情况下，R1 根据 OSPF 路径开销大小选择经过 R2 到达 R4。

> （原图：R1—R2—R3—R4 链路示意。）

### OSPF 与 BFD 联动（2）

BFD 会话建立后会周期性地快速发送 BFD 报文，如果在检测时间内没有收到 BFD 报文则认为该双向转发路径发生了故障，通知被服务的上层应用进行相应的处理。

1. 当 R1 和 R2 之间链路出现故障，BFD 首先快速检测到链路故障，BFD 会话状态变为 Down 并通知 R1。
2. R1 处理邻居 Down 事件，通知本地 OSPF 进程邻居不可达，重新进行路由计算，选择通过 R3 到达 R4。

### BFD 会话配置命令

1. 创建 BFD 会话绑定信息，并进入 BFD 会话视图。缺省情况下，未创建 BFD 会话。在第一次创建单跳 BFD 会话时，必须绑定对端 IP 地址和本端相应接口，且创建后不可修改。如果需要修改，则只能删除后重新创建。

```cli
[Huawei] bfd session-name bind peer-ip ip-address [ vpn-instance vpn-name ] interface interface-type interface-number [ source-ip ip-address ]
```

2. 创建使用组播地址作为对端地址的 BFD 会话，并进入 BFD 会话视图。

```cli
[Huawei] bfd session-name bind peer-ip default-ip interface interface-type interface-number [ source-ip ip-address ]
```

3. 创建 BFD for IPv6 的绑定信息，并进入 BFD 会话视图。在第一次创建单跳 BFD6 会话时，必须绑定对端 IPv6 地址和本端相应接口，且创建后不可修改。

```cli
[Huawei] bfd session-name bind peer-ipv6 ip-address [ vpn-instance vpn-name ] interface interface-type interface-number [ source-ipv6 ip-address ]
```

4. 创建静态标识符自协商 BFD 会话

```cli
[Huawei] bfd session-name bind peer-ip ip-address [ vpn-instance vpn-name ] interface interface-type interface-number [ source-ip ip-address ] auto
```

5. 创建单臂 Echo 功能的 BFD 会话

```cli
[Huawei] bfd session-name bind peer-ip ip-address [ vpn-instance vpn-name ] interface interface-type interface-number [ source-ip ip-address ] one-arm-echo
```

6. 配置 BFD 会话的本地标识符

```cli
[Huawei-bfd-session-test] discriminator local discr-value
```

7. 配置 BFD 会话的远端标识符

```cli
[Huawei-bfd-session-test] discriminator remote discr-value
```

配置标识符时，本端的本地标识符与对端的远端标识符必需相同，否则 BFD 会话无法正确建立。并且，本地标识符和远端标识符配置成功后不可修改。此处假设 BFD Session 名称是 test。

配置编辑完成后，用户可以执行 `commit` 提交配置，使新的配置数据在当前的系统运行配置中生效。

### 静态 BFD 会话配置示例

在 R1 与 R2 之间建立静态 BFD 会话：

```cli
[R1] bfd
[R1] bfd 12 bind peer-ip 10.0.12.2 interface GigabitEthernet 0/0/1
[R1-bfd-session-12] discriminator local 10
[R1-bfd-session-12] discriminator remote 20
[R1-bfd-session-12] commit

[R2] bfd
[R2] bfd 21 bind peer-ip 10.0.12.1 interface GigabitEthernet 0/0/1
[R2-bfd-session-21] discriminator local 20
[R2-bfd-session-21] discriminator remote 10
[R2-bfd-session-21] commit
```

在 R1 上配置静态路由并绑定 BFD 会话：

```cli
[R1] ip route-static 4.4.4.4 32 10.0.12.2 track bfd-session 12
[R1] ip route-static 4.4.4.4 32 10.0.13.2 preference 100
```

> （原图：Loopback0 `4.4.4.4/32` 在 R4；R1—R2 / R1—R3—R4 路径。其它配置此处省略。）

```cli
[R1] display bfd session all verbose
Session MIndex : 256       (One Hop)
State : Up        Name : 12
Local Discriminator    : 10
Remote Discriminator   : 20
Session Detect Mode  : Asynchronous Mode Without Echo Function
BFD Bind Type          : Interface(GigabitEthernet0/0/1)
Bind Session Type      : Static
Bind Peer IP Address   : 10.0.12.2
NextHop Ip Address     : 10.0.12.2
Bind Interface         : GigabitEthernet0/0/1
Min Tx Interval (ms)   : 1000
Min Rx Interval (ms)   : 1000
Actual Tx Interval (ms): 1000
Actual Rx Interval (ms): 1000
Local Detect Multi     : 3
Detect Interval (ms)   : 3000
...
```

要点：

- BFD 会话状态为 Up
- BFD 会话类型为静态 BFD
- 系统配置 BFD 控制报文最小接收间隔和最小发送间隔
- 系统协商后的 BFD 控制报文实际最小接收间隔和最小发送间隔
- 系统检测次数以及故障检测间隔

### OSPF 与 BFD 联动配置

**实验要求：**

- R1、R2、R3 运行 OSPF 协议，且都属于 Area 0；
- 配置 OSPF 与 BFD 联动，通过设置所有 OSPF 接口的 BFD 会话参数进一步提高链路状态变化时 OSPF 的收敛速度；
- 将 BFD 会话的最大发送间隔和最大接收间隔都设置为 100 ms，检测次数默认不变。

R1 配置如下：

```cli
[R1] bfd
[R1] interface GigabitEthernet 0/0/1
[R1-GigabitEthernet0/0/1] ip address 10.0.12.1 30
[R1] ospf 1
[R1-ospf-1] area 0
[R1-ospf-1-area-0.0.0.0] network 10.0.12.0 0.0.0.3
[R1-ospf-1-area-0.0.0.0] quit
[R1-ospf-1] bfd all-interfaces enable
[R1-ospf-1] bfd all-interfaces min-tx-interval 100 min-rx-interval 100 detect-multiplier 3
```

> （原图：R1—R2—R3，链路 `10.0.12.0/30`、`10.0.23.0/30`，同属 OSPF Area 0。）

R2 和 R3 的配置与 R1 类似，此处省略。

```cli
[R1] display ospf 1 bfd session all
OSPF Process 1 with Router ID 10.0.12.1
Area 0.0.0.0 interface 10.0.12.1(GigabitEthernet0/0/0)'s BFD Sessions
NeighborId:10.0.12.2 AreaId:0.0.0.0
Interface:GigabitEthernet0/0/0
BFDState:up rx :100              tx :100 Multiplier:3
BFD Local Dis:8192
LocalIpAdd: 10.0.12.1 RemoteIpAdd:10.0.12.2
Diagnostic Info:No diagnostic information
```

```cli
[R1] display bfd session all verbose
Session MIndex : 256       (One Hop)
State : Up        Name : dyn_8192
Local Discriminator   : 8192
Remote Discriminator   : 8192
Session Detect Mode : Asynchronous Mode Without Echo Function
BFD Bind Type        : Interface(GigabitEthernet0/0/0)
Bind Session Type   : Dynamic
Bind Peer IP Address   : 10.0.12.2
Min Tx Interval (ms)   : 100
Min Rx Interval (ms)   : 100
Actual Tx Interval (ms): 100
Actual Rx Interval (ms): 100
Local Detect Multi     : 3
Detect Interval (ms)   : 300
...
```

### 思考题（BFD）

1. （多选题）BFD 会话建立过程中有以下哪几种状态？A. Down B. Init C. Up D. Establish
2. （多选题）BFD 检测模式有哪些？A. 异步模式 B. 同步模式 C. 查询模式 D. 回声模式

参考答案：1. ABC  2. ACD

---

## VRRP 原理与配置

### 前言

局域网中的用户终端通常采用配置一个默认网关的形式访问外部网络，如果默认网关设备发生故障，那么所有用户终端访问外部网络的流量将会中断。可以通过部署多个网关的方式来解决单点故障，但是需要解决多个网关之间的冲突问题。

VRRP（Virtual Router Redundancy Protocol，虚拟路由器冗余协议）既能够实现网关的备份，又能解决多个网关之间互相冲突的问题，从而提高网络可靠性。

本课程主要介绍 VRRP 的工作原理与基本配置，以及在网络中的典型应用。

### 学习目标

学完本课程后，您将能够：

- 分析局域网单网关引发的问题
- 阐述 VRRP 基本概念及工作原理
- 描述 VRRP 主备切换过程
- 实现 VRRP 基本配置

### 课程内容

1. VRRP 技术概述
2. VRRP 技术原理
3. VRRP 典型应用
4. VRRP 基本配置

### 单网关面临的问题

当网关 Router 出现故障时，本网段内以该设备为网关的主机都不能与 Internet 进行通信。

> （原图：单网关场景下 HostA/B/C 默认网关均为 `192.168.1.254`。）

配置多个网关设备实现冗余是否可行？需要解决 IP/MAC 冲突与终端如何选择网关等问题——VRRP 正是为此设计。

### VRRP 的运行结果

VRRP 的运行结果是在局域网上提供一个虚拟路由器。

本例中：

- 局域网中有两个路由器 R1 和 R2，R1 端口 IP 地址为 `192.168.1.251/24`，R2 端口 IP 地址为 `192.168.1.252/24`。
- 配置 R1 和 R2 关联到同一个虚拟路由器，该虚拟路由器使用 `192.168.1.254` 做为端口 IP 地址。
- 所有的 PC 使用 `192.168.1.254` 做为默认网关。

### VRRP 的基本概念

**VRRP 路由器**：运行 VRRP 协议的路由器，如 R1 和 R2。VRRP 是配置在路由器的接口上的，而且也是基于接口来工作的。

**VRID**：一个 VRRP 组（VRRP Group）由多台协同工作的路由器（的接口）组成，使用相同的 VRID（Virtual Router Identifier，虚拟路由器标识符）进行标识。属于同一个 VRRP 组的路由器之间交互 VRRP 协议报文并产生一台虚拟“路由器”。一个 VRRP 组中只能出现一台 Master 路由器。

**虚拟路由器（Virtual Router）**：该路由器并非真实存在的物理设备，而是由 VRRP 虚拟出来的逻辑设备。一个 VRRP 组只会产生一台虚拟路由器。

**虚拟 IP 地址及虚拟 MAC 地址**：虚拟路由器拥有自己的 IP 地址以及 MAC 地址，其中 IP 地址由网络管理员在配置 VRRP 时指定，一台虚拟路由器可以有一个或多个 IP 地址，通常情况下用户使用该地址作为网关地址。而虚拟 MAC 地址的格式是 `0000-5e00-01xx`，其中 xx 为 VRID。

示例：虚拟 IP `192.168.1.254`，虚拟 MAC `0000-5e00-0101`（VRID=1）。

**Master 路由器**：在一个 VRRP 组中承担报文转发任务。在每一个 VRRP 组中，只有 Master 路由器才会响应针对虚拟 IP 地址的 ARP Request。Master 路由器会以一定的时间间隔周期性地发送 VRRP 报文，以便通知同一个 VRRP 组中的 Backup 路由器关于自己的存活情况。

**Backup 路由器**：也被称为备份路由器。Backup 路由器将会实时侦听 Master 路由器发送出来的 VRRP 报文，它随时准备接替 Master 路由器的工作。

**Priority**：优先级值是选举 Master 路由器和 Backup 路由器的依据，优先级取值范围 0–255，值越大越优先，值相等则比较接口 IP 地址大小，大者优先。

### VRRP 报文字段

- **Ver**：VRRP 目前有两个版本，其中 VRRPv2 仅适用于 IPv4 网络，VRRPv3 适用于 IPv4 和 IPv6 两种网络。
- **Virtual Rtr ID**：该报文所关联的虚拟路由器的标识。
- **Priority**：发送该报文的 VRRP 路由器的优先级。
- **Count IP Addrs**：该 VRRP 报文中所包含的虚拟 IP 地址的数量。
- **Auth Type**：VRRP 支持三种认证类型：不认证、纯文本密码认证、MD5 方式认证，对应值分别为 0、1、2。
- **Adver Int**：发送 VRRP 通告消息的间隔。默认为 1 秒。
- **IP Address**：所关联的虚拟路由器的虚拟 IP 地址，可以为多个。
- **Authentication Data**：验证所需要的密码信息。

### VRRP 定时器

在 VRRP 协议工作过程中，VRRP 定义了两个定时器：

- **ADVER_INTERVAL 定时器**：Master 发送 VRRP 通告报文时间周期，缺省值为 1 秒。
- **MASTER_DOWN 定时器**：Backup 设备监听该定时器超时后，会变为 Master 状态。

MASTER_DOWN 定时器计算公式如下：

- `MASTER_DOWN = (3 * ADVER_INTERVAL) + Skew_time`
- 其中，`Skew_Time = (256 - Priority) / 256`

### VRRP 协议状态

**Master 状态：**

1. 定期（ADVER_INTERVAL）发送 VRRP 报文。
2. 以虚拟 MAC 地址响应对虚拟 IP 地址的 ARP 请求。
3. 转发目的 MAC 地址为虚拟 MAC 地址的 IP 报文。
4. 默认允许 ping 通虚拟 IP 地址。
5. 当多台设备同时为 Master 时，若设备收到与自己优先级相同的报文时，会进一步比较 IP 地址的大小。如果收到报文的源 IP 地址比自己大，则切换到 Backup 状态，否则保持 Master 状态。

**Backup 状态：**

1. 接收 Master 设备发送的 VRRP 报文，判断 Master 设备的状态是否正常。
2. 对虚拟 IP 地址的 ARP 请求，不做响应。
3. 丢弃目的 MAC 地址为虚拟 MAC 地址的 IP 报文。
4. 丢弃目的 IP 地址为虚拟 IP 地址的 IP 报文。
5. 如果收到优先级和自己相同或者比自己优先级大的报文时，重置 MASTER_DOWN 定时器，不进一步比较 IP 地址的大小。

### 启动与选举说明

- 初始创建 VRRP 的设备工作在 Initialize 状态，收到接口 Up 的消息后，若此设备的优先级小于 255，则会先切换至 Backup 状态，等待 MASTER_DOWN 定时器超时后再切换至 Master 状态。
- 如果优先级高的设备先启动，优先级低的设备后启动，则优先级高的设备先进入 Master 状态，优先级低的设备收到高优先级的 VRRP 通告报文，自己仍处于 Backup 状态。
- 如果优先级低的先启动，优先级高的后启动，则优先级低的先由 Backup 状态切换为 Master 状态，优先级高的设备收到优先级低的 VRRP 通告报文，重新进行选举，将优先级高的设备切换为 Master 状态。

一个 Startup 事件可以由系统在 VRRP 配置完成后自动触发，也可以是在已经配置 VRRP 的端口上，底层链路由不可用变为可用而触发。

### IP 地址拥有者

通常情况下，VRRP 路由器的接口 IP 地址不会与虚拟路由器的 IP 地址重叠，也就是说我们会为虚拟路由器单独规划一个 IP 地址，而不会使用某台路由器的接口 IP 地址。当然也存在一个特殊的情况，例如在某些网络中 IP 地址资源比较紧缺，那么也有可能会将某台路由器的接口 IP 地址用于虚拟路由器，此时该路由器将无条件成为 Master。

无法手动将 VRRP 接口优先级配置为 255，当接口 IP 地址为 IP 地址拥有者时，优先级自动成为 255。

### 主备切换时间

- 当 Master 设备主动放弃 Master 地位（如 Master 设备退出备份组）时，会发送优先级为 0 的通告报文，用来使 Backup 设备快速切换成 Master 设备，而不用等到 MASTER_DOWN 定时器超时。这个切换的时间称为 Skew_time。
- 当 Master 设备发生网络故障而不能发送通告报文的时候，Backup 设备并不能立即知道其工作状况。等到 MASTER_DOWN 定时器超时后，才会认为 Master 设备无法正常工作，从而将状态切换为 Master。

### VRRP 主备回切

1. 正常情况下，由 Master 设备负责转发用户报文，所有用户流量通过 R1 到达 Internet。
2. 当 R1 出现故障时，网络会重新进行 VRRP 主备选举，此时 R2 会成为新的 Master 设备负责转发用户报文。

开启抢占模式的 VRRP 备份组，当主备进行切换时，总共时长为：

`3 × Adver_Interval + Skew_time + Delay_time`

在抢占模式下，当 Master 的设备状态不稳定或者网络质量差时，会导致 VRRP 备份组频繁切换，从而引发终端 ARP 表项频繁刷新。为缓解此问题，通常设置抢占延时定时器，通过 MASTER_INTERVAL 定时器超时时间加上延时时间，确定状态稳定后，再进行主备回切。

### VRRP 负载分担

通过创建多个虚拟路由器，每个物理路由器在不同的 VRRP 组中扮演不同的角色，不同虚拟路由器的 Virtual IP 作为不同的内网网关地址可以实现流量转发负载分担。

示例：

| 组 | R1 角色 | R2 角色 | Virtual IP | 优先级示例 |
|----|---------|---------|------------|------------|
| VRID 1 | Master | Backup | 192.168.1.254 | 200 / 100 |
| VRID 2 | Backup | Master | 192.168.1.251 | 100 / 200 |

部分主机网关指向 `192.168.1.254`，部分指向 `192.168.1.251`，从而实现负载分担。

### VRRP 监视上行与 BFD 联动

如果用户未配置 VRRP 监视上行端口，则当 VRRP 备份组中的 Master 设备 R1 的上行接口或者链路出现故障时，VRRP 备份组无法感知，Master 无法向外转发流量。但是由于主备不会发生切换，导致出现流量黑洞。

当 VRRP 备份组之间的链路出现故障时，由于此时 VRRP 报文无法正常交互，Backup 设备需要等待 Master_Down_Timer 计时器超时后才会切换为 Master 设备，在等待切换期间内，业务流量仍会发往 Master 设备，此时会造成业务流量丢失。

通过在 Master 设备和 Backup 设备之间建立 BFD 会话并与 VRRP 备份组进行绑定，由 BFD 机制快速检测 VRRP 备份组之间的通信故障，并在出现故障时及时通知 VRRP 备份组进行主备切换，从而大大减少应用中断时间。

在普通 BFD 联动中，VRRP 备份组会根据 BFD 会话的状态进行优先级调整，并根据调整后的优先级判断是否进行主备切换。在实际应用中，通常 Master 设备配置延时抢占，而 Backup 设备配置立即抢占，当 Backup 设备检测到 BFD 会话状态出现 DOWN 后，通过增加自身优先级大于 Master 优先级实现快速切换，当故障排除，BFD 会话状态出现 UP 时，新的 Master 通过减小自己的优先级，发送 VRRP 通告报文，经过延迟时间后再次切换为 Backup。

### VRRP + MSTP

- MSTP 是将一个或多个 VLAN 映射到一个生成树的实例，若干个 VLAN 共用一个生成树，MSTP 可以实现负载均衡。
- VRRP 配置网关可以灵活根据网络拓扑变化而自动切换，提高网络可靠性。
- VRRP + MSTP 可以在实现负载分担的同时保证网络冗余备份。

### VRRP 常用配置命令

1. 创建 VRRP 备份组并给备份组配置虚拟 IP 地址

```cli
[interface-GigabitEthernet0/0/0] vrrp vrid virtual-router-id virtual-ip virtual-address
```

注意：各备份组之间的虚拟 IP 地址不能重复；同属一个备份组的设备接口需使用相同的 VRID。

2. 配置路由器在备份组中的优先级

```cli
[interface-GigabitEthernet0/0/0] vrrp vrid virtual-router-id priority priority-value
```

注意：通常情况下，Master 设备的优先级应高于 Backup 设备。

3. 配置备份组中设备的抢占延迟时间

```cli
[interface-GigabitEthernet0/0/0] vrrp vrid virtual-router-id preempt-mode timer delay delay-value
```

4. 配置 VRRP 备份组中设备采用非抢占模式

```cli
[interface-GigabitEthernet0/0/0] vrrp vrid virtual-router-id preempt-mode disable
```

缺省情况下，抢占模式已被激活。

5. 配置 VRRP 备份组监视接口

```cli
[interface-GigabitEthernet0/0/0] vrrp vrid virtual-router-id track interface interface-type interface-number [ increased value-increased | reduced value-decreased ]
```

可配置设备当检测到上行接口或链路出现故障时，增加或者减少自身优先级，IP 地址拥有者和 Eth-Trunk 成员口不允许配置 VRRP 监视功能。

6. 配置 VRRP 备份组联动普通 BFD 会话

```cli
[interface-GigabitEthernet0/0/0] vrrp vrid virtual-router-id track bfd-session { bfd-session-id | session-name bfd-configure-name } [ increased value-increased | reduced value-reduced ]
```

如果选择参数 `session-name bfd-configure-name`，可以绑定静态 BFD 会话或者标识符自协商的静态 BFD 会话。如果选择参数 `bfd-session-id`，只能绑定静态 BFD 会话。

### VRRP 基础配置实例

**配置要求：**

- R1 与 R2 组成一个 VRRP 备份组，其中 R1 为 Master，R2 为 Backup；
- Master 设备故障恢复时采用抢占模式，抢占延时 10 秒；
- Master 设备监视上行接口状态实现 VRRP 主备自动切换。

R1 配置如下：

```cli
[R1] interface GigabitEthernet0/0/0
[R1-GigabitEthernet0/0/0] ip address 192.168.1.253 24
[R1-GigabitEthernet0/0/0] vrrp vrid 1 virtual-ip 192.168.1.254
[R1-GigabitEthernet0/0/0] vrrp vrid 1 priority 120
[R1-GigabitEthernet0/0/0] vrrp vrid 1 preempt-mode timer delay 10
[R1-GigabitEthernet0/0/0] vrrp vrid 1 track interface GigabitEthernet0/0/1 reduced 30
```

R2 配置如下：

```cli
[R2] interface GigabitEthernet0/0/0
[R2-GigabitEthernet0/0/0] ip address 192.168.1.252 24
[R2-GigabitEthernet0/0/0] vrrp vrid 1 virtual-ip 192.168.1.254
[R2-GigabitEthernet0/0/0] vrrp vrid 1 priority 110
```

### VRRP 基础配置验证

```cli
[R1] display vrrp
GigabitEthernet0/0/0 | Virtual Router 1
State:Master
Virtual IP : 192.168.1.254
Master IP : 192.168.1.253
PriorityRun:120
PriorityConfig : 120
MasterPriority : 120
Preempt:YES DelayTime：10s
TimerRun : 1 s
TimerConfig : 1 s
Auth type : NONE
Virtual MAC : 0000-5e00-0101
Track IF : GigabitEthernet0/0/1 Priority reduced : 30
IF state : UP
```

```cli
[R2] display vrrp
GigabitEthernet0/0/0 | Virtual Router 1
State:Backup
Virtual IP : 192.168.1.254
Master IP : 192.168.1.253
PriorityRun:110
PriorityConfig : 110
MasterPriority : 120
Preempt:YES DelayTime：0s
TimerRun : 1 s
TimerConfig : 1 s
Auth type : NONE
Virtual MAC : 0000-5e00-0101
```

要点：

- VRRP 组 ID 为 1
- R1 在组中状态为 Master，R2 为 Backup
- 接口在本 VRRP 组中优先级分别为 120 / 110
- R1 开启抢占模式，且延迟时间为 10 秒

### 思考题（VRRP）

1. （多选题）以下关于 VRRP 报文中 IP 地址的设置正确的说法是（）
   - A. 源 IP 地址为 Master 设备端口的 IP 地址
   - B. 源 IP 地址为虚拟路由器的虚拟 IP 地址
   - C. 目的 IP 地址为广播 IP 地址
   - D. 目的 IP 地址为组播 IP 地址

2. （多选题）以下关于 VRRP 协议中各定时器的说法正确的是（）
   - A. VRRP 通告消息发送间隔默认为 1 秒，关联到同一虚拟路由器 VRRP 路由器上配置的 VRRP 消息通告间隔必须一致。
   - B. 配置抢占延迟时间为 4 秒，表示如果 4 秒之内没有收到 Master 发送的 VRRP 通告消息，则 Slave 应当成为新的 Master。
   - C. 配置抢占延迟时间为 4 秒，配置 VRRP 消息通告间隔为 2 秒，表示如果 6 秒之内没有收到 Master 发送的 VRRP 通告消息，则 Slave 应当成为新的 Master。
   - D. 在比较繁忙的网络中，应当适当的将抢占延迟设置为一个较大的值，以避免不必要的 VRRP 角色振荡。

### 本章总结（VRRP）

- VRRP 作为一种非常重要的可靠性技术，常用于实现网关设备冗余，该协议既能提高网络可靠性，又可以实现网络负载分担。
- VRRP 主备选举、主备切换及主备回切都主要通过 VRRP 优先级来控制，为了确保网络稳定性，VRRP 设计了抢占延时机制，减少网络震荡。
- VRRP 可监视上行接口状态，从而感知网络故障，联动 VRRP 实现网络可靠性。VRRP 亦可绑定 BFD 会话实现快速收敛。此外，VRRP 可与 MSTP 结合使用，在园区网络中，这是常见的组网方案。

---

## DHCP 原理与配置（导读）

### 课程内容

1. DHCP 产生背景
2. DHCP 工作原理与配置
3. DHCP Relay 工作原理与配置

### DHCP 产生背景

手工配置主机 IP 地址、网络掩码、网关地址、DNS 服务器地址等网络参数时，需要经过地址规划、地址分配、地址配置、地址维护等复杂的操作流程。这使地址分配灵活性差，IP 地址资源利用率低，同时较大的工作量导致配置容易出错，对人员素质要求较高。

### DHCP 的基本概念

DHCP 是一种用于集中对用户 IP 地址进行动态管理和配置的协议。

DHCP 采用 C/S（Client/Server，客户端/服务器）通信模式，协议报文基于 UDP 的方式进行交互，采用 67（DHCP 服务器）和 68（DHCP 客户端）两个端口号：

- 正常工作时由客户端向服务器提出配置申请。
- 服务器返回为客户端分配的 IP 地址等相应的配置信息。

（DHCP 优点、报文交互与详细配置见下一章。）
