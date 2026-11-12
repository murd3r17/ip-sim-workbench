---
doc_id: "hcip-datacom-core-training-08"
title: "园区网服务可靠性与STP/RSTP"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 8
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# 园区网服务可靠性与STP/RSTP

## CAPWAP 隧道

CAPWAP（Control And Provisioning of Wireless Access Points Protocol Specification，无线接入点控制和配置协议）定义了如何对 AP 进行管理、业务配置，即 AC 通过 CAPWAP 隧道来实现对 AP 的集中管理和控制。

CAPWAP 协议定义的主要内容有：AP 自动发现 AC，AC 对 AP 进行安全认证，AP 从 AC 获取软件，AP 从 AC 获得初始和动态配置等。通过该协议，AP 和 AC 之间建立起 CAPWAP 隧道。

CAPWAP 隧道有两种：

- **控制隧道**：主要传输控制报文（也称管理报文，是 AC 管理控制 AP 的报文）
- **数据隧道**：主要传输数据报文

CAPWAP 隧道可以进行数据传输层安全加密，因此传输的报文更加安全。当采用隧道转发模式时，AP 将 STA 发出的数据通过 CAPWAP 隧道实现与 AC 之间的交互。

## VRRP

虚拟路由冗余协议 VRRP（Virtual Router Redundancy Protocol）通过把几台路由设备联合组成一台虚拟的路由设备，将虚拟路由设备的 IP 地址作为用户的默认网关实现与外部网络通信。当网关设备发生故障时，VRRP 机制能够选举新的网关设备承担数据流量，从而保障网络的可靠通信。

通常，同一网段内的所有主机上都设置一条相同的、以网关为下一跳的缺省路由。主机发往其他网段的报文将通过缺省路由发往网关，再由网关进行转发。当网关发生故障时，本网段内所有以网关为缺省路由的主机将无法与外部网络通信。增加出口网关是提高系统可靠性的常见方法，此时如何在多个出口之间进行选路就成为需要解决的问题。VRRP 能够在不改变组网的情况下，将多台路由设备组成一个虚拟路由器，通过配置虚拟路由器的 IP 地址为默认网关，实现默认网关的备份。

- **冗余备份**：可将多台路由设备配置为缺省网关路由器，出现单点故障时通过备份链路进行业务传输。
- **负载分担**：多台设备同时承担业务流量，减轻主用设备压力。
- **联动功能**：VRRP 联动可以监视上行链路故障；当上行接口或链路故障时，Master 降低优先级并重新选举。VRRP 与 BFD 联动可提高主备切换速度。

## 集群 / 堆叠简介

- **iStack（Intelligent Stack，智能堆叠）**：将多台支持堆叠特性的交换机设备组合在一起，从逻辑上组合成一台交换设备。iStack 针对华为盒式交换机。
- **CSS（Cluster Switch System，集群交换机系统）**：将两台支持集群特性的交换机设备组合在一起，从逻辑上组合成一台交换设备。CSS 针对华为框式交换机。

堆叠系统建立之前，每台交换机都是单独的实体，有自己独立的 IP 地址和 MAC 地址；堆叠建立后成员对外体现为统一逻辑实体，用户使用一个 IP 地址对堆叠中的所有交换机进行管理和维护。通过交换机堆叠，可以实现网络大数据量转发和网络高可靠性，同时简化网络管理。

## DHCP

动态主机配置协议 DHCP（Dynamic Host Configuration Protocol）是一种用于集中对用户 IP 地址进行动态管理和配置的技术。即使规模较小的网络，通过 DHCP 也可以使后续增加网络设备变得简单快捷。

- DHCP 允许计算机动态地获取 IP 地址，而不是静态为每台主机指定地址。
- DHCP 能够分配其他配置参数，例如客户端的启动配置文件，使客户端仅用一个消息就获取它所需要的所有配置信息。
- DHCP 协议由 RFC 2131 定义，采用客户端/服务器通信模式，由客户端（DHCP Client）向服务器（DHCP Server）提出配置申请，服务器返回为客户端分配的配置信息。

DHCP 可以提供两种地址分配机制：

- **动态分配机制**：通过 DHCP 为主机分配一个有使用期限（租期）的 IP 地址。适用于主机需要临时接入网络，或空闲地址数小于网络主机总数且主机不需要永久连接网络的场景。
- **静态分配机制**：网络管理员通过 DHCP 为指定的主机分配固定的 IP 地址。相比手工静态配置，可避免人工配置错误，方便统一维护管理。

DHCP 受益主要有两点：降低客户端的配置和维护成本；集中管理。

## NTP

网络时间协议 NTP（Network Time Protocol）是 TCP/IP 协议族里面的一个应用层协议，用于在一系列分布式时间服务器与客户端之间同步时钟。NTP 的实现基于 IP 和 UDP。NTP 报文通过 UDP 传输，端口号是 123。

随着网络拓扑的日益复杂，整个网络内设备的时钟同步将变得十分重要。如果依靠管理员手工修改系统时钟，不仅工作量巨大，而且时钟的准确性也无法得到保证。NTP 的出现就是为了解决网络内设备系统时钟的同步问题。

主要应用场合示例：

- **网络管理**：对从不同路由器采集来的日志信息、调试信息进行分析时，需要以时间作为参照依据
- **计费系统**：要求所有设备的时钟保持一致
- **多系统协同处理**：为保证正确的执行顺序，多个系统必须参考同一时钟
- **增量备份**：要求备份服务器和所有客户机之间的时钟同步
- **系统时间**：某些应用程序需要知道用户登录系统的时间以及文件修改的时间

交换机既可以作为 NTP 的服务器，也可以作为 NTP 的客户端。

## LLDP

LLDP（Link Layer Discovery Protocol）是 IEEE 802.1ab 中定义的链路层发现协议。LLDP 是一种标准的二层发现方式，可以将本端设备的管理地址、设备标识、接口标识等信息组织起来，并发布给自己的邻居设备，邻居设备收到这些信息后将其以标准的管理信息库 MIB（Management Information Base）的形式保存起来，以供网络管理系统查询及判断链路的通信状况。

传统网络管理系统多数只能分析到三层网络拓扑结构，无法确定网络设备的详细拓扑信息、是否存在配置冲突等。通过 LLDP 获取的设备二层信息能够快速获取相连设备的拓扑状态；显示出客户端、交换机、路由器、应用服务器以及网络服务器之间的路径；检测设备间的配置冲突、查询网络失败的原因。

## SNMP

SNMP（Simple Network Management Protocol，简单网络管理协议）是广泛应用于 TCP/IP 网络的网络管理标准协议。SNMP 提供了一种通过运行网络管理软件的中心计算机（即网络管理工作站 NMS）来管理设备的方法。通过“利用网络管理网络”的方式，SNMP 实现了对网络设备的高效和批量管理；同时，SNMP 协议也屏蔽了不同产品之间的差异，实现了不同种类和厂商的网络设备之间的统一管理。

被网管设备上运行代理进程，并通过 MIB 向 NMS（例如 iMaster NCE）提供管理信息。

## NETCONF / YANG

SNMP 并不是面向配置的协议，随着网络规模的增大、复杂性的增加，SNMP 已经不能适应当前复杂网络的管理，特别是不能满足配置管理的需求。

NETCONF（Network Configuration Protocol，网络配置协议）提供了一种网管和网络设备之间通信的机制。网络管理员可以利用这套机制在网管上增加、修改、删除网络设备的配置，获取网络设备的配置和状态信息。NETCONF 基于 XML（Extensible Markup Language，可扩展标记语言）。

## 园区网络安全概述

- 通过防火墙实现不同安全区域之间的划分及业务隔离、安全管控。
- 通过 Anti-DDoS 设备抵御 DDoS 攻击。
- 通过 IPS 设备进行入侵检测及安全态势感知。
- 对不同的业务进行隔离部署、互访流量管控。
- 按需部署网络准入控制。
- 部署设备本机防攻击，提高设备抗攻击能力。
- 建议开启广播风暴控制、DHCP Snooping、IPSG、DAI 等安全功能，建议部署端口隔离，加强用户通信安全。
- 部署网络准入控制，对接入园区的用户的身份或终端进行认证，并根据结果授予网络访问权限。
- 部署无线空口安全及无线业务安全。

防火墙安全区域要点：

- 在一台防火墙上不允许创建两个相同安全级别（Priority）的安全区域；
- 防火墙的接口必须加入一个安全区域，否则不能正常转发流量；
- 防火墙的一个接口只能属于一个安全区域；
- 防火墙的一个安全区域可以拥有多个接口；
- 系统自带的缺省安全区域不能删除，用户可以根据实际需求创建自定义的安全区域。

### 防火墙双机热备

防火墙部署在网络出口位置时，如果发生故障会影响到整网业务，需提升网络的可靠性。部署多台防火墙可提升可靠性，需保证设备切换过程中的业务连续性。

方案：部署两台 FW 并组成双机热备。双机热备需要两台硬件和软件配置均相同的 FW。两台 FW 之间通过一条独立的链路连接，这条链路通常被称之为“心跳线”。两台 FW 通过心跳线了解对端的健康状况，向对端备份配置和表项（如会话表、IPSec SA 等）。当一台 FW 出现故障时，业务流量能平滑地切换到另一台设备上处理，使业务不中断。

### NAT

NAT（Network Address Translation）是将 IP 数据报文头中的 IP 地址转换为另一个 IP 地址的过程。

需求示例：内网用户（采用私网 IP 地址）需访问 Internet，需对其源 IP 地址进行转换，转换为公网 IP 地址；外网用户需访问采用私网 IP 地址的服务器（例如 WEB 服务器）。

常用 NAT：

- **源 IP 地址转换（Source IP address-based NAT）**：No-PAT（No-Port 地址转换）、NAPT（网络地址及端口转换）
- **目的 IP 地址转换（Destination IP address-based NAT）**：NAT Server

## VPN 相关协议名词

- **IPSec**：IP Security，因特网协议安全协议
- **GRE**：Generic Routing Encapsulation，通用路由封装协议
- **L2TP**：Layer 2 Tunneling Protocol，二层隧道协议
- **MPLS**：Multiprotocol Label Switching，多协议标签交换协议

## 单播 / 广播 / 组播对比（概述）

- **单播（Unicast）**：一台源 IP 主机和一台目的 IP 主机之间进行。网络上绝大部分数据以单播形式传输（如电子邮件、网上银行）。多个接收者时 Server 需发送多份拷贝，用户量大时带宽与设备压力大。
- **广播（Broadcast）**：一台源 IP 主机和网络中所有其它 IP 主机之间进行。广播被限制在广播域中；大量广播会消耗带宽及设备资源；信息安全性和有偿服务得不到保障。
- **组播（Multicast）**：一台源 IP 主机和多台（一组）IP 主机之间进行，中间网络设备根据接收者需要有选择地复制和转发。

组播相关概念：组播源、组播接收者、组播组、组播路由器、第一跳路由器、最后一跳路由器、IGMP 等（详见组播专章）。

## IPv6 概述（节选）

IPv4 地址空间不足问题日趋明显，IPv6 取代 IPv4 势在必行。IPv6（Internet Protocol Version 6）是网络层协议的第二代标准协议，也被称为 IPng（IP Next Generation）。IPv6 地址长度为 128 bit。

- **NDP**：Neighbor Discovery Protocol，邻居发现协议。
- IPv6 网络支持静态路由和动态路由协议：静态路由配置方式与 IPv4 相同；动态路由包括 OSPFv3、IS-IS（IPv6）、BGP4+ 等。

### 园区网章节思考题

1. （多选题）以下关于交换机二层接口的描述，正确的是？（）
   - A. 交换机的二层接口类型有 Access、Trunk、Hybrid。
   - B. Access 接口只能加入一个 VLAN。
   - C. 缺省情况下，Trunk 接口允许 VLAN1 的流量通过，而且在发送时不携带 VLAN Tag。
   - D. 在 Hybrid 接口上可通过命令指定接口在发送特定 VLAN 的流量时，是否携带 VLAN Tag。
2. （多选题）以太网链路聚合技术有哪些优势？（）
   - A. 增加带宽
   - B. 提高可靠性
   - C. 负载分担
   - D. 智能调优：可根据流量大小自动调整活动接口数量

参考：1. ABCD；2. ABC（D 不是链路聚合本身列举的优势）。

本章总结要点：园区网络典型技术场景化应用包括以太网交换基础、无线接入、网络可靠性、网络服务与网络管理、路由与网络可达性、网络安全、VPN 等。

## STP 原理要点

### BPDU 泛洪与报文格式

- 在初始形成 STP 树的过程中，所有 STP 交换机会周期性地（Hello Time，缺省为 2s）主动产生并发送配置 BPDU，大家都认为自己是根桥。
- 随着 BPDU 的泛洪和收集，各交换机根据 BPDU 包含的信息进行比较，并选举出根桥。
- 在此之后（STP 树形成后的稳定期），只有根桥会周期性地（缺省为 2s）主动产生并发送配置 BPDU。非根桥交换机从自己的根端口周期性地接收到配置 BPDU，并立即触发产生自己的配置 BPDU，然后从自己的指定端口发出。

配置 BPDU 携带的参数可分为 3 类：

1. **BPDU 对自身的标识**：协议标识（Protocol ID，总是 0x0000）、协议版本号（总是 0x00）、BPDU 类型（配置 BPDU 为 0x00）、标志（Flag）。
2. **用于进行 STP 计算的参数**：根桥 ID（Root ID）、根路径开销（RPC）、发送该 BPDU 的交换机 BID、发送该 BPDU 的端口 PID。
3. **时间参数**：消息寿命（Message Age）、最大寿命（Max Age，缺省 20s）、Hello Time（缺省 2s）、转发延迟（Forward Delay，缺省 15s）。

从根桥发出的配置 BPDU，Message Age 为 0；在实际实现中，配置 BPDU 每“经过”一个桥，Message Age 增加 1。

### STP 基本原理与四步建树

在具有物理环路的交换网络中，交换机通过运行 STP，自动生成一个没有环路的工作拓扑（STP 树）。

STP 采用四个步骤解决二层环路问题：

1. 在一个交换网络中选举一个根桥；
2. 在每个非根桥上选举一个根端口；
3. 为每个网段选举一个指定端口；
4. 阻塞交换机上所有剩余的非根、非指定端口（备用端口）。

主要通过比较 4 个参数：根桥 ID、根路径开销、网桥 ID 和端口 ID，值越小越优先。

- **根桥选举**：比较根桥 ID，最小胜出。
- **根端口选举**：依次比较 RPC、对端 BID、对端 PID 和本端 PID，最小胜出。
- **指定端口选举**：依次比较 RPC、本端 BID 和本端 PID，最小胜出。
- 在华为产品实现中，被阻塞的非指定端口表现为 Alternate Port。

### STP 端口状态

| 状态 | 说明 |
| --- | --- |
| Disabled | 端口无法接收和发出任何帧，处于关闭（down）状态 |
| Blocking | 只能接收并处理 BPDU，不能发送 BPDU，也不能转发用户数据帧 |
| Listening | 可接收并发送 BPDU，不进行 MAC 学习，不转发用户数据；过渡状态，持续 Forward Delay |
| Learning | 可接收并发送 BPDU，进行 MAC 学习，不转发用户数据；过渡状态，持续 Forward Delay |
| Forwarding | 可接收并发送 BPDU，进行 MAC 学习，并转发用户数据；仅根端口或指定端口可进入 |

端口状态迁移概要：初始 Disabled→Blocking；选为根/指定端口后进入 Listening→Learning→Forwarding；若角色变为非根/非指定则退回 Blocking；端口关闭或链路故障进入 Disabled。

### 拓扑变更（TCN）

当交换机检测到拓扑更改时，会通知生成树的根桥，然后根桥将该拓扑更改信息泛洪到整个网络。位于变化点的交换机以 Hello Time 为周期通过其根端口不断向上游发送 TCN BPDU，直到接收到 TCA 位置 1 的配置 BPDU；上游交换机继续向上传递，直到根桥收到 TCN；根桥发送 TC 位置 1 的配置 BPDU，通知下游设备删除桥 MAC 地址表项。

## RSTP 相对 STP 的改进

RSTP 可以兼容 STP：可与 STP 互操作，但此时会丧失快速收敛等 RSTP 优势。运行 RSTP 的交换设备在某端口上接收到运行 STP 的交换设备发出的配置 BPDU，在两个 Hello Time 时间之后，便把自己的端口转换到 STP 工作模式。在华为设备上可配置：运行 STP 的交换设备被撤离网络后，运行 RSTP 的交换设备可迁移回到 RSTP 工作模式。

RST BPDU 与 STP 配置 BPDU 的不同点包括 BPDU 类型和 Flag 字段：

- BPDU 类型：RST BPDU 类型值为 0x02
- Flag 位：bit7 TCA；bit6 Agreement（P/A）；bit5 Forwarding；bit4 Learning；bit3～2 端口角色（00 未知，01 Alternate/Backup，10 Root，11 Designated）；bit1 Proposal；bit0 TC

STP 只有指定端口会立即处理次优 BPDU，其他端口会忽略次优 BPDU，等到 Max Age 超时后缓存的次优 BPDU 才老化；RSTP 处理次优 BPDU 不再依赖定时器老化，任何端口角色都会处理次优 BPDU，从而加快收敛。

## STP/RSTP 基本配置

1. 配置生成树工作模式（缺省 MSTP）：

```cli
[Huawei] stp mode { stp | rstp | mstp }
```

2.（可选）配置当前设备为根桥 / 备份根桥：

```cli
[Huawei] stp root primary
[Huawei] stp root secondary
```

3.（可选）配置交换机 STP 优先级（0～61440，步长 4096，缺省 32768）：

```cli
[Huawei] stp priority priority
```

4.（可选）配置路径开销计算方法与接口开销：

```cli
[Huawei] stp pathcost-standard { dot1d-1998 | dot1t | legacy }
[Huawei-GigabitEthernet0/0/1] stp cost cost
```

- `dot1d-1998`：取值范围 1～65535
- `dot1t`：取值范围 1～200000000（缺省计算方法）
- `legacy`：华为计算方法，取值范围 1～200000

同一网络内所有交换机的接口路径开销应使用相同的计算方法。

5.（可选）配置接口优先级（0～240，步长 16，缺省 128）：

```cli
[Huawei-GigabitEthernet0/0/1] stp priority priority
```

6. 启用 STP/RSTP（缺省已启用）：

```cli
[Huawei] stp enable
```

7. 配置边缘端口、BPDU 保护、根保护、环路保护、TC 保护：

```cli
[Huawei-GigabitEthernet0/0/1] stp edged-port enable
[Huawei] stp bpdu-protection
[Huawei-GigabitEthernet0/0/1] stp root-protection
[Huawei-GigabitEthernet0/0/1] stp loop-protection
[Huawei] stp tc-protection interval interval-value
[Huawei] stp tc-protection threshold threshold
```

说明：配置了根保护的端口不可以配置环路保护。配置 TC 保护后，在 `stp tc-protection interval` 指定的时间内，设备只会处理 `stp tc-protection threshold` 指定数量的拓扑变化报文，其余延迟处理，可能影响收敛速度。

### RSTP 配置案例

```cli
[SW1] stp mode rstp
[SW1] stp enable
[SW1] stp root primary
[SW2] stp mode rstp
[SW2] stp enable
[SW2] stp root secondary
[SW3] stp mode rstp
[SW3] stp enable
[SW3-Ethernet0/0/1] stp edged-port enable
[SW1-GigabitEthernet0/0/1] stp root-protection
[SW1-GigabitEthernet0/0/2] stp root-protection
[SW3] stp bpdu-protection
```

### 思考题（RSTP）

1. （多选题）以下哪些是 RSTP 的端口状态？ Idle / Discarding / Forwarding / Learning
2. （单选题）RSTP 的根保护必须配置在设备的根端口上。（对 / 错）

参考：1. BCD；2. B（错）。

## MSTP 概述（引入）

RSTP 在 STP 基础上实现了网络拓扑快速收敛，但在划分 VLAN 的网络中运行 RSTP/STP，局域网内所有 VLAN 共享一棵生成树，被阻塞后的链路将不承载任何流量，无法在 VLAN 间实现数据流量的负载均衡，导致链路带宽利用率、设备资源利用率较低。

为了弥补 RSTP/STP 的缺陷，IEEE 于 2002 年发布的 802.1s 标准定义了 MSTP（Multiple Spanning Tree Protocol，多生成树协议）。MSTP 兼容 STP 和 RSTP，通过建立多棵无环路的树，解决广播风暴并实现冗余备份。

### RSTP/STP 的不足

**不足 1：流量无法负载分担**

背景：SW3 为接入交换机，使用两条链路连接 SW1 和 SW2，所有链路均允许 VLAN2 和 VLAN3 通过；希望将 SW1 设为 VLAN2 网关、SW2 设为 VLAN3 网关，并让不同 VLAN 使用不同链路。若网络中只有一个生成树，假设 SW3 与 SW2 相连的端口为阻塞端口，则 VLAN2 和 VLAN3 的数据都只能通过一条链路到汇聚交换机，不能实现流量负载分担。

**不足 2：二层次优路径**

由于 SW3 与 SW2 间的链路被阻塞，VLAN3 的数据到达网关的路径可能是次优的，最优路径应当是由 SW3 直达 SW2。

MSTP 可通过多棵生成树（基于 Instance，而非直接基于 VLAN）实现不同 VLAN 报文沿不同路径转发，实现负载分担。
