---
doc_id: "hcip-datacom-core-training-16"
title: "Telemetry、网管运维与 WLAN 关键技术"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 16
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# Telemetry、网管运维与 WLAN 关键技术

## 网络运维挑战与 Telemetry

随着网络的普及和新技术的涌现，网络规模日益增大，部署的复杂度逐步提升，用户对业务的质量要求也不断提高。为了满足用户需求，网络运维务必更加精细化、智能化。当今网络的运维面临着如下挑战：

- **超大规模**：管理的设备数目众多，监控的信息数量非常庞大。
- **快速定位**：在复杂的网络中，能够快速地定位故障，达到秒级、甚至亚秒级的故障定位速度。
- **精细监控**：监控的数据类型更多，且监控粒度更细，以便完整、准确地反应网络状况，据此预估可能发生的故障，并为网络优化提供有力的数据依据。网络运维不仅需要监控接口上的流量统计信息、每条流上的丢包情况、CPU 和内存占用情况，还需要监控每条流的时延抖动、每个报文在传输路径上的时延、每台设备上的缓冲区占用情况等。

采集器、分析器和控制器都位于网管侧：

- **采集器**：用于接收和存储网络设备上报的监控数据。
- **分析器**：用于分析采集器接收到的监控数据，并对数据进行处理，例如以图形化界面的形式展现给用户。
- **控制器**：通过 NETCONF 等方式向设备下发配置，实现对网络设备的管理。控制器可以根据分析器提供的分析数据，为网络设备下发配置，对网络设备的转发行为进行调整；也可以控制网络设备对哪些数据进行采样和上报。

### gRPC 与 Telemetry

gRPC（Google Remote Procedure Call，Google 远程过程调用）是 Google 发布的基于 HTTP/2.0 传输层协议承载的高性能开源软件框架，提供了支持多种编程语言的、对网络设备进行配置和管理的方法。

传统的网络监控手段（SNMP、CLI、日志）已无法满足网络需要：

- SNMP 和 CLI 主要采用“拉模式”获取数据，即发送请求来获取设备上的数据，限制了可以监控的网络设备数量，且无法快速获取数据。
- SNMP Trap 和日志虽然采用“推模式”获取数据，即设备主动将数据上报给监控设备，但仅上报事件和告警，监控的数据内容极其有限，无法准确地反映网络状况。

Telemetry 是一项监控设备性能和故障的远程数据采集技术。它采用“推模式”及时获取丰富的监控数据，可以实现网络故障的快速定位，从而解决上述网络运维问题。

## Syslog

该协议从最初的加州大学伯克利分校软件中心整理，后来由于其操作管理的实用性迅速成为很多网络设备操作管理协议的一部分。现在已经有相应的 RFC3164、RFC3195 进行通用的定义。前者定义的是使用 UDP 形式传输，后者定义的是使用 TCP 形式传输。

几乎所有的网络设备都可以通过 syslog protocol 将日志信息以 UDP 方式传送到远端服务器，远端接收日志服务器必须通过 syslogd 来监听 UDP Port 514，并且根据 syslog.conf 中的配置来处理本机和接收访问系统的日志信息，把指定的事件写入特定档案中，供后台数据库管理和响应之用。

角色分类：

- **发送者（sender）**：产生 syslog message 的网元；
- **中继（relay）**：能接收到后进行转发 syslog message 的网元或其他设备；
- **收集者（collector）**：接收了不再转发 syslog message 的 syslog server。

## LLDP

LLDP 是一种邻近发现协议。它为以太网网络设备，如交换机、路由器和无线局域网接入点定义了一种标准的方法，使其可以向网络中其他节点公告自身的存在，并保存各个邻近设备的发现信息。例如设备配置和设备识别等详细信息都可以用该协议进行公告。

LLDP 信息是定期传输的，并且只在一定的期限内保留。IEEE 已经定义了一个建议的传输频率，即每 30 秒传输一次。LLDP 设备在收到邻近网络设备发出的 LLDP 信息后，将把 LLDP 信息存储在一个 IEEE 定义的简单网络管理协议（SNMP）管理信息库（MIB）中，并且在一定的时限内保持有效。定义该时限的 LLDP“生存时间”（TTL）值就包含在所收到的数据包内。

该协议使网络管理系统能够精确地发现和模拟物理网络拓扑结构。由于 LLDP 设备发送和接收公告，这些设备将会把自己发现的邻近设备信息存储下来。公告数据，如邻近设备的管理地址、设备类型和端口号，都有助于确定邻近设备到底属于什么类型，以及它们通过哪些端口实现互联。

组网模式：

- **单邻居组网模式**：交换机设备的接口之间直接相连，而且接口只有一个邻居设备的情况。
- **链路聚合组网模式**：交换机设备的接口之间存在链路聚合，接口之间是直接相连，链路聚合之间的每个接口只有一个邻居设备。

**Eth-Trunk（以太网链路聚合）**：简称链路聚合，它通过将多条以太网物理链路捆绑在一起成为一条逻辑链路，从而实现增加链路带宽的目的。

## 端口镜像

在网络维护的过程中会遇到需要对报文进行获取和分析的情况，比如怀疑有攻击报文，此时需要在不影响报文转发的情况下，对报文进行获取和分析。镜像可以在不影响报文正常处理流程的情况下，将镜像端口的报文复制一份到观察端口，用户利用数据监控设备来分析复制到观察端口的报文，进行网络监控和故障排除。

基本概念：

- **镜像端口**：被监控的端口，从镜像端口流经的所有报文或匹配流分类规则的报文将被复制到观察端口。
- **观察端口**：连接监控设备的端口，用于输出从镜像端口复制过来的报文。
- **观察端口组**：连接多个监控设备的一组端口。观察端口组中的多个成员端口分别连接多个监控设备，当使用观察端口组镜像报文时，镜像到观察端口组的报文将被复制到所有的成员端口。

类型：

- **端口镜像**：设备复制一份从镜像端口流经的报文，并将此报文传送到指定的观察端口进行分析和监控。
- **流镜像**：将镜像端口上特定业务流的报文复制到观察端口进行分析和监控。在流镜像中，镜像端口应用了包含流镜像行为的流策略。如果从镜像端口流经的报文匹配流分类规则，则将被复制到观察端口。

应用示例：若需监控交换机特定端口的入站或出站报文，可在观察端口接 PC 并安装协议分析软件，部署端口镜像后将业务口流量镜像到观察口进行分析。如果没有端口镜像技术，除非数据包的目的地是监控 PC（所连接的端口），否则报文是不会发向该端口的。因此事实上端口镜像就是将某个特定端口的流量拷贝到某个监控端口。

### 网络管理应用场景小结

- 随着网络的快速发展，数字化转型日益凸显，网络管理逐步从面向网元管理的方式转到面向场景的自动化。
- 网络管控系统是自治网络的演进方向，包含了控制器、分析器和管理器。
- SNMP 和 NETCONF 一般用于配置下发，Telemetry、NetStream 和 sFlow 一般用于数据上报。

### 什么是 iMaster NCE？

iMaster NCE 能力要点：

- SDN 自动化业务配置部署
- 统一数据底座
- 全生命周期管理
- AI 智能分析预测排障
- 感知定位处置一气呵成
- 仿真校验监控优化
- 自动化 + 智能化
- 管理 + 控制 + 分析
- 规 + 建 + 维 + 优

### iMaster NCE 产品架构和客户价值

- **网络自动化**：意图驱动，基于模型；跨域、跨层、跨厂家；场景化 APP。
- **网络智能化**：基于大数据和 AI 的预测性维护。
- **敏捷的系统集成**：可编程的 Design Studio；开放的 REST API。
- **统一云化平台**：基于云的弹性扩展；可部署于公有云 & 私有云；弹性扩展 & 高可靠。

### 思考题（网络管理）

1. （多选题）网络管理体系结构包含的两个关键元素是什么（）A. 管理设备 B. 被管理设备 C. 代理 D. 网管协议
2. （多选题）网络管理的基本功能，以下描述正确的是（）A. 配置管理 B. 性能管理 C. 故障管理 D. 安全管理 E. 计费管理

### 本章总结（网络管理）

- 随着数字化技术的快速发展，大数据、AI、云等技术与业务的发展交织在一起，促进了网络管理的变革。网络管理将逐渐向管理自动化和运维智能化方向发展。
- 网络管理主要由四个主要模型组成，包括组织结构模型、信息模型、通信模型和功能模型。
- 本章节主要从网络管理的配置、性能和故障三大功能来介绍相应的网络管理协议。各个不同协议的讲解主要从角色、数据组织和典型管理方式，三个维度展开。

### 更多信息 / 学习推荐

- RFC6241 - Network Configuration Protocol：https://tools.ietf.org/html/rfc6241
- Network Telemetry Framework - IETF Tools
- https://e.huawei.com/cn/talent/#/home

---

## 大型 WLAN 网络关键技术

### 相关概念补充

- **云桌面**：又称桌面虚拟化、云电脑，是替代传统电脑的一种新模式；用户安装客户端后通过特有的通信协议访问后端服务器上的虚拟机主机来实现交互式操作。
- **智真会议**：通过高分辨率摄像头和语音设备，提供真人大小面对面、眼对眼的视频会议。
- **VR（Virtual Reality）**：虚拟现实，指用计算机模拟三维环境。
- **AR（Augmented Reality）**：增强现实，在虚拟现实的基础上发展起来的新技术，将虚拟的信息应用到真实世界。

### 大型 WLAN 关键技术清单

1. VLAN Pool
2. DHCP 技术
3. 漫游技术
4. 高可靠性技术
5. 准入控制技术

要点：

- **VLAN Pool**：通过 VLAN Pool 把接入的用户分配到不同的 VLAN，可以减少广播域，减少网络中的广播报文，提升网络性能。
- **DHCP Option 43 & 52**：当 AC 和 AP 间是三层组网时，AP 通过发送广播请求报文的方式无法发现 AC，这时需要通过 DHCP 服务器回应给 AP 的报文中携带的 Option43 字段（IPv4）或 Option52（IPv6）来通告 AC 的 IP 地址。
- **漫游技术**：WLAN 漫游是指 STA 在不同 AP 覆盖范围之间移动且保持用户业务不中断的行为。
- **高可靠性技术**：为了保证 WLAN 业务的稳定运行，保证在主设备故障时业务能够顺利切换到备份设备的技术。
- **准入控制**：通过对接入网络的客户端和用户的认证来保证网络的安全，是一种“端到端”的安全技术。

## VLAN Pool

### 问题背景

由于无线终端的移动性，在无线网络中经常有大量用户从某个区域接入后，随着用户的移动，再漫游到其他区域，导致该区域的用户接入多，对 IP 地址数目要求大。比如：场馆入口、酒店的大堂等。目前一个 SSID 只能对应一个 VLAN，一个 VLAN 对应一个子网，如果大量用户从某一区域接入，只能扩大 VLAN 的子网，保证用户能够获取到 IP 地址。这样带来的问题就是广播域扩大，导致大量的广播报文（如：ARP、DHCP 等）带来严重的网络拥塞。

基于此问题考虑，一个 SSID 需要能够对应多个 VLAN，把大量用户分散到不同的 VLAN 减少广播域。VLAN Pool 提供多个 VLAN 的管理和分配算法，实现 SSID 对应多个 VLAN 的方案。

### VLAN Pool 概念

现有网络面临的挑战：

- 无线网络终端的移动性导致特定区域 IP 地址请求较多。
- 通常情况下，一个 SSID 只能对应一个业务 VLAN，如果通过扩大子网增加 IP 地址则会导致广播域扩大，大量的广播报文造成网络拥塞。

VLAN Pool 是一种把多个 VLAN 放在一个池中并提供分配算法的 VLAN 分配技术，又称为 VLAN 池。

### VLAN Pool 分配算法

| 分配算法 | 说明 | 优点 | 缺点 |
|----------|------|------|------|
| 顺序分配（even） | 把用户按上线顺序依次划分到不同的 VLAN 中 | 各个 VLAN 用户数目划分均匀 | 重新上线 VLAN 容易变更、IP 变化 |
| HASH 分配（hash） | 根据用户 MAC 地址 HASH 值分配 VLAN | 用户多次上线可分配相同的 VLAN、IP 不变 | 各个 VLAN 用户数划分不均衡 |

**VAP（Virtual Access Point）**：在一个物理实体 AP 上虚拟出多个 AP，每一个被虚拟出的 AP 就是一个 VAP，每个 VAP 提供和物理实体 AP 一样的功能。用户可以在一个 AP 上创建不同的 VAP 来为不同的用户群体提供无线接入服务。

### VLAN Pool 应用示例（门厅效应）

问题：大量用户从门口区域接入后再漫游到其他区域，若门口 SSID 仅对应单一大地址池 VLAN，广播域过大。

解决办法：使用 VLAN Pool 作为业务 VLAN，把大量用户分散到不同的 VLAN 中，以减少广播域。

VLAN Pool 中可以配置 VLAN 分配算法：`assignment { even | hash }`

- `even`：VLAN Pool 根据 STA 的上线顺序为 STA 分配业务 VLAN，尽量保证所有 VLAN 分配给 STA 的 IP 地址数目相近。但同一个 STA 如果多次上线，每次获取的地址通常都不相同。
- `hash`：VLAN Pool 根据 STA 的 MAC 地址进行哈希运算后的结果为 STA 分配业务 VLAN，只要 VLAN Pool 里面的 VLAN 不发生变化，通常 STA 都会获取到固定的业务 VLAN，STA 重新上线时也会被尽量优先分配到之前使用过的 IP 地址。

### VLAN Pool 配置

```cli
[AC] vlan pool pool-name
[AC-vlan-pool-pool-name] vlan { start-vlan [ to end-vlan ] } &<1-10>
[AC-vlan-pool-pool-name] assignment { even | hash }
[AC] wlan
[AC-wlan-view] vap-profile name profile-name
[AC-wlan-vap-prof-profile-name] service-vlan vlan-pool pool-name
```

1. 创建 VLAN Pool 并进入 VLAN Pool 视图。
2. 将指定 VLAN 添加到 VLAN Pool 中。
3. 配置 VLAN Pool 中的 VLAN 分配算法。
4. 配置 VAP 的业务 VLAN。

示例：

```cli
[AC] vlan pool STA
[AC-vlan-pool-STA] vlan 20 30
[AC-vlan-pool-STA] assignment hash
[AC-vlan-pool-STA] quit
[AC] wlan
[AC-wlan-vap-prof-huawei] service-vlan vlan-pool STA
```

查看：

```cli
<AC> display vlan pool all
--------------------------------------------------------------------------------
Name                            Assignment                      VLAN total
--------------------------------------------------------------------------------
STA                               hash                                 2
--------------------------------------------------------------------------------
Total: 2
```

## WLAN 场景下的 DHCP / DHCP Relay

随着网络规模的不断扩大，网络设备不断增多，企业内不同的用户可能分布在不同的网段，一台 DHCP 服务器在正常情况下无法满足多个网段的地址分配需求。企业内网各个网段通常都没有与 DHCP Server 在同一个二层广播域内，如果还需要通过 DHCP 服务器分配 IP 地址，则需要跨网段发送 DHCP 协议报文。

DHCP 客户端使用 IP 广播来寻找同一网段上的 DHCP 服务器。当服务器和客户端处在不同网段，即被路由器分割开来时，路由器是不会转发这样的广播包。DHCP 中继能够跨网段“透传”DHCP 报文，使得一个 DHCP 服务器同时为多个网段服务成为可能。

### DHCP Relay 配置命令（WLAN 场景）

```cli
[Huawei-GigabitEthernet0/0/0] dhcp select relay
[Huawei-GigabitEthernet0/0/0] dhcp relay server-ip ip-address
[Huawei] dhcp server group group-name
[Huawei-dhcp-server-group-HW] dhcp-server ip-address [ ip-address-index ]
[Huawei-GigabitEthernet0/0/0] dhcp relay server-select group-name
[Huawei-GigabitEthernet0/0/0] ip address dhcp-alloc
```

### DHCP Relay 配置举例（AC 作中继）

SW / AC / AR 示意配置：

```cli
[SW] vlan 10
[SW-vlan10] quit
[SW] interface GigabitEthernet 0/0/1
[SW-GigabitEthernet0/0/1] port link-type access
[SW-GigabitEthernet0/0/1] port default vlan 10
[SW-GigabitEthernet0/0/1] quit
[SW] interface GigabitEthernet 0/0/2
[SW-GigabitEthernet0/0/2] port link-type trunk
[SW-GigabitEthernet0/0/2] port trunk allow-pass vlan 10
[SW-GigabitEthernet0/0/2] quit
[SW] interface Vlanif 10
[SW-Vlanif10] ip address 10.1.1.1 24
```

```cli
[AC] vlan batch 10 20
[AC] interface GigabitEthernet 0/0/1
[AC-GigabitEthernet0/0/1] port link-type trunk
[AC-GigabitEthernet0/0/1] port trunk allow-pass vlan 10
[AC-GigabitEthernet0/0/1] quit
[AC] interface Vlanif 10
[AC-Vlanif10] ip address 10.1.1.2 24
[AC-Vlanif10] quit
[AC] interface Vlanif 20
[AC-Vlanif20] ip address 172.21.1.1 24
[AC-Vlanif20] quit
[AC] dhcp server group AP
[AC-dhcp-server-group-AP] dhcp-server 172.21.1.2
[AC-dhcp-server-group-AP] quit
[AC] interface Vlanif 10
[AC-Vlanif10] dhcp select relay
[AC-Vlanif10] dhcp relay server-select AP
[AC-Vlanif10] quit
```

```cli
[AR] interface GigabitEthernet 0/0/1
[AR-GigabitEthernet0/0/1] ip address 172.21.1.2 24
[AR-GigabitEthernet0/0/1] quit
[AR] ip pool AP
[AR-ip-pool-AP] network 10.1.1.0 mask 24
[AR-ip-pool-AP] gateway-list 10.1.1.2
[AR-ip-pool-AP] excluded-ip-address 10.1.1.1
[AR-ip-pool-AP] quit
[AR] interface GigabitEthernet 0/0/1
[AR-GigabitEthernet0/0/1] dhcp select global
[AR-GigabitEthernet0/0/1] quit
[AR] ip route-static 10.1.1.0 255.255.255.0 172.21.1.1
```

验证：

```cli
[AR] display ip pool name AP used
……
253       10.1.1.254    00e0-fcca-1150       2181    Used
```

```cli
<AC> display dhcp relay all
DHCP relay agent running information of interface Vlanif10 :
Server group name        : AP
Gateway address in use  : 10.1.1.2
```

## DHCP Option 43（AC 发现）

在 AC 和 AP 间是二层组网的情况下，也可以配置 Option43，AP 会根据 Option43 的内容先向指定 IP 地址的 AC 发送单播请求报文，如果发送十次报文，AP 都没有收到回应，则 AP 会继续以广播的方式来发现同一网段的 AC。所以在二层组网的情况下 Option 43 不是必配的参数，但在三层组网的情况下则是必配的。

Option 43 即为 Type 值为 43（0x2B）的 Option 字段，又称为厂商特定信息选项。当 DHCP 服务器接收到请求 Option43 信息的 DHCP 请求报文后，将在回复报文中携带 Option43，为 DHCP 客户端分配厂商指定的信息（本文中特指 AC 的 IP 地址）。

WLAN 三层组网场景：AP 的广播 Discovery Request 报文无法发现 AC，导致 CAPWAP 隧道无法建立。配置 DHCP Option 43 后，在 AP 获取 IP 地址阶段，同时获取了 AC 的 IP 地址，直接通过单播与 AC 建立联系。

### Option 43 配置方式

以 AC 或交换机配置 DHCP 服务器为例：

```cli
[AC-ip-pool-AP] option 43 sub-option 1 hex hex-string
[AC-ip-pool-AP] option 43 sub-option 2 ip-address ip-address
[AC-ip-pool-AP] option 43 sub-option 3 ascii ascii-string
```

说明：

- `option 43 sub-option 1 hex C0A80001C0A80002`：指定 AC IP 为 `192.168.0.1` 和 `192.168.0.2`（十六进制）。
- `option 43 sub-option 2 ip-address 192.168.0.1 192.168.0.2`
- `option 43 sub-option 3 ascii 192.168.0.1,192.168.0.2`：多个 IP 用逗号隔开。

示例：

```cli
[AR] ip pool AP
[AR-ip-pool-ap] option 43 sub-option 3 ascii 100.100.100.100
[AR-ip-pool-ap] quit
[AC] interface LoopBack 0
[AC-LoopBack0] ip address 100.100.100.100 32
[AC-LoopBack0] quit
[AC] capwap source interface LoopBack 0
```

```cli
[AR] display ip pool name AP
Pool-name           : AP
Option-code       : 43
Option-subcode : 3
Option-type        : ascii
Option-value       : 100.100.100.100
Gateway-0      : 10.1.1.2
Mask           : 255.255.255.0
```

```cli
[AC] display ap unauthorized record
Unauthorized AP record:
Total number: 1
AP type: AP4030TN
AP SN: 210235448310C92A877C
AP MAC address: 00e0-fcca-1150
AP IP address: 10.1.1.254
```

从上图可以看到 AP 已经成功发现 AC，在 AC 上可以随时将 AP 添加到 AC 上。

## 漫游技术

终端在移动过程中，如果逐渐远离接入 AP，则链路的信号质量也会逐步下降。当终端感知到信号质量降低一定程度（漫游门限）时，终端会主动漫游到附近 AP 来提高信号质量。

漫游一般包括如下动作：

1. 终端已经与 AP1 建链，终端在各种信道中发送 Probe Request。AP2 在其信道中收到请求后应答；终端评估后确定与 AP2 关联最合适。
2. 终端向 AP2 发送关联请求，AP2 使用关联响应做出应答，建立用户与 AP2 间的关联（此时与 AP1 的关联可能仍保持）。
3. 删除用户与 AP1 现有的关联（发送 802.11 解除关联信息）。

### AC 内 / AC 间漫游

- **AC 内漫游**：漫游过程中关联的是同一个 AC。
- **AC 间漫游**：漫游过程中关联的不是同一个 AC。
- **AC 间隧道**：为了支持 AC 间漫游，漫游组内的所有 AC 需要同步每个 AC 管理的 STA 和 AP 设备的信息，因此在 AC 间建立一条隧道作为数据同步和报文转发的通道。AC 间隧道也是利用 CAPWAP 协议创建的。

**漫游组服务器：**

- STA 在 AC 间进行漫游，通过选定一个 AC 作为漫游组服务器，在该 AC 上维护漫游组的成员表，并下发到漫游组内的各 AC，使漫游组内的各 AC 间相互识别并建立 AC 间隧道。
- 漫游组服务器既可以是漫游组外的 AC，也可以是漫游组内选择的一个 AC。
- 一个 AC 可以同时作为多个漫游组的漫游组服务器，但是自身只能加入一个漫游组。
- 漫游组服务器管理其他 AC 的同时不能被其他的漫游组服务器管理。
- 漫游组服务器作为一个集中配置点，不需要有特别强的数据转发能力，只需要能够和各个 AC 互通即可。

**家乡代理**：能够和 STA 家乡网络的网关二层互通的一台设备。为了支持 STA 漫游后仍能正常访问家乡网络，需要将 STA 的业务报文通过隧道转发到家乡代理，再由家乡代理中转。STA 的家乡代理由 HAC 或 HAP 兼任。

### 二层漫游与三层漫游

- **二层漫游**：客户端在 2 个 AP（或多个 AP）之间来回切换连接无线，前提是这些 AP 都绑定的是同一个 SSID 并且业务 VLAN 都在同一个 VLAN 内（在同一个 IP 地址段），漫游切换的过程中，无线客户端的接入属性（比如所属业务 VLAN、获取的 IP 地址等）不会有任何变化，直接平滑过渡，在漫游的过程中不会有丢包和断线重连的现象。
- **三层漫游**：漫游前后 SSID 的业务 VLAN 不同，AP 所提供的业务网络为不同的三层网络，对应不同的网关。此时，为保持漫游用户 IP 地址不变的特性，需要将用户流量迂回到初始接入网段的 AP，实现跨 VLAN 漫游。

网络中有时候会出现：两个业务 VLAN 的 VLAN ID 相同，但是这两个子网又属于不同的子网。此时为了避免系统仅仅依据 VLAN ID 将用户在两个子网间的漫游误判为二层漫游，需要通过漫游域来确定设备是否在同一个子网内，只有当 VLAN 相同且漫游域也相同的时候才是二层漫游，否则是三层漫游。

### 漫游流量走向

**二层漫游（示意）：**

- 漫游前：STA → HAP → 网关（交换机）→ 上层网络。
- 漫游后：STA → FAP → 网关（交换机）→ 上层网络。
- AC 间二层漫游隧道转发与直接转发流量走向一致。

**三层漫游：**

用户漫游前后不在同一个子网中，为了使用户漫游后仍能正常访问漫游前的网络，需要将用户流量通过隧道中转到原来的子网。

- **隧道转发模式**：HAP 和 HAC 之间的业务报文通过 CAPWAP 隧道封装，此时可以将 HAP 和 HAC 看作在同一个子网内，报文无需返回到 HAP，直接通过 HAC 进行中转到上层网络。
- **直接转发模式**：HAP 和 HAC 之间的业务报文不通过 CAPWAP 隧道封装，无法判定 HAP 和 HAC 是否在同一个子网内，此时设备默认报文需要返回到 HAP 进行中转。如果 HAP 和 HAC 在同一个子网时，可以将家乡代理设置为性能更强的 HAC，减少 HAP 的负荷并提高转发效率。

直接转发模式下三层漫游后典型路径：STA → FAP →（CAPWAP）FAC →（AC 间隧道）HAC →（CAPWAP）HAP → 上层网络；若家乡代理设为 HAC，则可在 HAC 直接上送上层网络。

### 漫游组配置

```cli
[AC-wlan-view] mobility-group name group-name
[AC-mc-mg-group-name] member { ip-address ipv4-address | ipv6-address ipv6-address } [ description description ]
```

1. 创建漫游组
2. 向漫游组中添加成员，此处添加的 AC 的 IP 地址为 AC 的源 IP 地址。

示例：

```cli
[AC1-wlan-view] mobility-group name mobility
[AC1-mc-mg-mobility] member ip-address 10.1.201.100
[AC1-mc-mg-mobility] member ip-address 10.1.201.200
[AC1-mc-mg-mobility] quit
[AC2-wlan-view] mobility-group name mobility
[AC2-mc-mg-mobility] member ip-address 10.1.201.100
[AC2-mc-mg-mobility] member ip-address 10.1.201.200
[AC2-mc-mg-mobility] quit
```

HAP 与 HAC、FAP 与 FAC 之间的组网方式为三层组网时，需配置 HAC 和 FAC 形成漫游组，保证 STA 的业务流量正常。

## 高可靠性技术概述

热备份是指，当两台设备在确定主用（Master）设备和备用（Backup）设备后，由主用设备进行业务的转发，而备用设备处于监控状态，同时主用设备实时向备用设备发送状态信息和需要备份的信息，当主用设备出现故障后，备用设备及时接替主用设备的业务运行。

### 备份方式对比

| 方式 | 要点 |
|------|------|
| VRRP 双机热备份 | 主备 AC 两个独立的 IP 地址，通过 VRRP 对外虚拟为同一个 IP 地址，单个 AP 和虚拟 IP 建立一条 CAPWAP 链路；主 AC 备份 AP/STA/CAPWAP 等信息，并通过 HSB 同步给备 AC |
| 双链路热备份 | 单个 AP 分别和主备 AC 建立 CAPWAP 链路（主链路 + 备链路）；主 AC 仅备份 STA 信息并通过 HSB 同步；主 AC 故障后 AP 切换到备链路 |
| 双链路冷备份 | 单个 AP 分别和主备 AC 建立 CAPWAP 链路；AC 不备份同步信息；主 AC 故障后 AP 切换到备链路 |
| N+1 备份 | 单个 AP 只和一个 AC 建立 CAPWAP 链路；AC 不备份同步信息；主 AC 故障后 AP 重新与备 AC 建链 |

### VRRP 双机热备特点

AC 目前支持 VRRP 单实例整机热备，不支持负载均衡。整机热备具有以下特点：

- 上行链路可以互为备份，主备 VRRP 可以 track 上行口状态，AC 整机主备状态可能与各下行链路通断状态不一致。
- 下行多条链路（包括有线、无线）采用 MSTP 破环，MSTP 状态变更时会自动清除链路上的 MAC/ARP 表。

两台 AC 组成一个 VRRP 组，主、备 AC 对 AP 始终显示为同一个虚拟 IP 地址，主 AC 通过 Hot Standby（HSB）主备通道同步业务信息到备 AC 上。所有 AP 与“虚拟 AC”建立 CAPWAP 隧道。AP 只看到一个 AC 的存在，AC 间的切换由 VRRP 决定。这种方式一般将主备 AC 部署在同一地理位置，和其他备份方式比较，其业务切换速度非常快。

### HSB 主备服务

基于 VRRP 的双机热备，热备相关的业务都注册到同一个 HSB 备份组，HSB 备份组内部绑定 HSB 服务，同时 HSB 备份组与一个 VRRP 实例绑定，从而业务通过 HSB 备份组获知当前用户的主备状态、以及主备切换等事件，并通过 HSB 组的接口进行备份数据的接收和发送。

HSB 主备服务主要包括：

- **建立主备备份通道**：通过配置主备服务本端和对端的 IP 地址和端口号，从而建立主备机制报文发送的 TCP 通道，为其他业务提供报文的收发以及链路状态变化通知服务。
- **维护主备通道的链路状态**：通过发送主备服务报文和重传等机制来防止 TCP 较长时间中断但协议栈没有检测到该连接中断。

HSB 业务实时备份内容包括：用户数据信息、CAPWAP 隧道信息、AP 表项、DHCP 地址信息等。HSB 主备通道可通过两台 AC 之间的直连物理链路承载，也可通过交换机承载（例如复用 VRRP 报文交互所处的物理通道）。

### VRRP 双机热备配置流程

1. 创建 VRRP 备份组并配置虚拟 IP 地址。
2. 创建 HSB 主备服务，建立 HSB 主备备份通道的 IP 地址和端口号。
3. 创建 HSB 备份组，配置 HSB 备份组绑定 HSB 主备服务、VRRP 备份组、WLAN 业务以及 DHCP。
4. 使能 HSB 备份组，HSB 备份组使能后，对 HSB 备份组的相关配置才会生效。
5. 检查 VRRP 热备份配置结果。

#### 配置命令

```cli
[AC-GigabitEthernet0/0/1] vrrp vrid virtual-router-id virtual-ip virtual-address
[AC-GigabitEthernet0/0/1] vrrp vrid virtual-router-id priority priority-value
[AC] hsb-service service-index
[AC-hsb-service-0] service-ip-port local-ip { local-ipv4-address | local-ipv6-address } peer-ip { peer-ipv4-address | peer-ipv6-address } local-data-port local-port peer-data-port peer-port
[AC] hsb-group group-index
[AC-hsb-group-0] bind-service service-index
[AC-hsb-group-0] track vrrp vrid virtual-router-id interface interface-type interface-number
[AC] hsb-service-type ap hsb-group group-index
[AC] hsb-service-type dhcp hsb-group group-index
[AC] hsb-service-type access-user hsb-group group-index
[AC-hsb-group-0] hsb enable
```

（完整配置示例与验证见下一章。）
