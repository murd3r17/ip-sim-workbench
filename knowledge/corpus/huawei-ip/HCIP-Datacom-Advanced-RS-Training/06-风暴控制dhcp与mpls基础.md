---
doc_id: "hcip-datacom-advanced-rs-training-06"
title: "风暴控制、DHCP安全与MPLS基础"
book: "HCIP-Datacom-Advanced-RS-Training"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "training"
source_pdf: "HCIP-Datacom-Advanced+Routing+&+Switching+Technology+V1.0+培训教材(1).pdf"
seq: 6
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# 风暴控制、DHCP安全与MPLS基础

## 1. 流量抑制配置（续）

```cli
[Switch-GigabitEthernet0/0/1] unicast-suppression 80
[Switch-GigabitEthernet0/0/1] multicast-suppression 70
[Switch-GigabitEthernet0/0/1] broadcast-suppression 60
```

按百分比抑制未知单播 80%、未知组播 70%、广播 60%。验证：`display flow-suppression interface GigabitEthernet 0/0/1`。

接口与 VLAN 同时配置时，接口视图优先。

## 2. 风暴控制

网络环路时 BUM 泛洪可致广播风暴。风暴控制可在超阈值时 **block** 或 **shutdown** 端口；流量抑制仅限速丢弃多余流量。

```cli
[Switch] storm-control whitelist protocol arp-request
[Switch] interface gigabitethernet 0/0/1
[Switch-GigabitEthernet0/0/1] storm-control broadcast min-rate 1000 max-rate 2000
[Switch-GigabitEthernet0/0/1] storm-control multicast min-rate 1000 max-rate 2000
[Switch-GigabitEthernet0/0/1] storm-control unicast min-rate 1000 max-rate 2000
[Switch-GigabitEthernet0/0/1] storm-control interval 90
[Switch-GigabitEthernet0/0/1] storm-control action block
[Switch-GigabitEthernet0/0/1] storm-control enable trap
```

低阈值以下恢复正常转发；高阈值触发控制。查看：`display storm-control interface GigabitEthernet 0/0/1`。

## 3. DHCP Snooping

DHCP 无中继四步：Discover → Offer → Request → Ack；客户端收 Ack 后发免费 ARP 探测冲突。

DHCP Snooping 保证客户端从合法服务器获址，通过**信任口**与**绑定表**防御 Server 仿冒、DoS、报文仿冒等。

- 使能口：请求转所有信任口；响应丢弃
- 信任口：请求转其他信任口；响应仅转给对应客户端使能口

绑定表随租期老化或 Release 删除。

### 饿死攻击与防护

攻击者伪造大量不同 CHADDR/源 MAC 耗尽地址池。防护：

- 限制接口学习 MAC 数量
- `dhcp snooping check dhcp-chaddr enable`：源 MAC 与 CHADDR 一致性检查
- 注意：同时变换 MAC 与 CHADDR 且保持一致时可绕过一致性检查，需配合 MAC 数量限制

### 中间人 / IP-MAC Spoofing

攻击者用 ARP 投毒成为中间人。交换机侦听 DHCP 建绑定表；`arp dhcp-snooping-detect enable` 后，不匹配绑定的 ARP 被丢弃。

### 配置命令

```cli
[Huawei] dhcp snooping enable [ ipv4 | ipv6 ]
[Huawei-vlan2] dhcp snooping enable
[Huawei-vlan2] dhcp snooping trusted interface interface-type interface-number
[Huawei-GigabitEthernet0/0/1] dhcp snooping enable
[Huawei-GigabitEthernet0/0/1] dhcp snooping trusted
[Huawei] dhcp snooping check dhcp-giaddr enable vlan { vlan-id1 [ to vlan-id2 ] }
```

缺省接口非信任。配置举例：客户端口 enable，服务器口 enable+trusted。验证：`display dhcp snooping interface GigabitEthernet 0/0/3`。

## 4. IP Source Guard（IPSG）

基于绑定表对入接口/VLAN 的 IP 报文检查，丢弃非法主机，防私自改 IP 盗用权限。一般部署在接入设备。

无绑定表时使能 IPSG：除 DHCP 请求外拒绝所有 IP 报文。静态绑定含 MAC/IP/VLAN/入接口；动态绑定检查项可由用户配置。

```cli
[Huawei] user-bind static ...
[Huawei-GigabitEthernet0/0/1] ip source check user-bind enable
[Huawei-GigabitEthernet0/0/1] ip source check user-bind alarm enable
[Huawei-GigabitEthernet0/0/1] ip source check user-bind alarm threshold threshold
```

验证：`display dhcp static user-bind all`；改 IP 后无法上网。

## 5. 交换安全思考题与总结

1.（多选）DHCP Snooping 可防御：改变 CHADDR 饿死、仿冒 Server、中间人与 IP/MAC Spoofing 等（非 TCP flag）

**总结：** 端口隔离、MAC 表安全、端口安全、漂移检测、MACsec、流量抑制与风暴控制、DHCP Snooping、IPSG 共同构成以太网交换安全体系。

---

## 6. MPLS 原理与配置前言

传统 IP 逐跳查表成为瓶颈，MPLS 在边缘分析 IP，域内用定长标签转发。硬件提升后速度优势弱化，但多层标签与转控分离使其在 VPN、QoS 等场景广泛应用。

### 学习目标

- 描述 MPLS 基本概念、术语、工作原理与转发流程
- 实现静态 LSP 配置

### 课程内容

1. MPLS 基础（概述、术语、标签）  
2. MPLS 转发  
3. 静态 LSP 配置  

## 7. MPLS 基础

传统 IP：每跳解封装查最长匹配，面向无连接，QoS 保障弱。MPLS 起源于 IPv4，可扩展到多种网络层协议；用短而定长、仅本地意义的标签交换替代 IP 转发。

### 术语

- **MPLS 域**：连续运行 MPLS 的设备集合
- **LSR**：支持 MPLS 的设备；边缘为 LER，内部为核心 LSR
- **Ingress / Transit / Egress**：压入 / 交换 / 弹出标签
- **FEC**：转发等价类；常见为匹配同一路由的报文
- **LSP**：入站、出站及若干中转 LSR 的有序集合；单向；可静态或动态建立；双向需两条 LSP

### 标签

32 bit 头部：Label、TC（原 EXP，RFC5462）、S（栈底）、TTL。以太网 Type 0x8847 表示上层为 MPLS。标签空间各 LSR 独立。

操作：**Push / Swap / Pop**。

同一 FEC 可因 Ingress 不同而走不同 LSP；标签仅本地意义，各 LSR 分配可同可不同。

### 控制平面与转发平面

| 平面 | 内容 |
| --- | --- |
| 控制（无连接） | RIB、LIB（LDP/RSVP/静态等） |
| 转发（面向连接） | FIB、LFIB（ILM + NHLFE 等） |

LSP 建立原则：FEC 对应路由须在 IP 路由表；上游出标签 = 下游入标签。

静态 LSP 各节点不互感知整条路径；动态可用 LDP、RSVP-TE、MP-BGP 等。Tunnel ID 关联 FIB/ILM/NHLFE。

Ingress：查 FIB（FTN）+ NHLFE；Tunnel ID=0 走 IP，非 0 走 MPLS。Transit：ILM + NHLFE。Egress：Pop 后按内层处理。

## 8. 静态 LSP 配置

```cli
[Huawei] mpls lsr-id lsr-id
[Huawei] mpls
[Huawei-GigabitEthernet0/0/0] mpls
```

静态标签：`out-label` 16～1048575；`in-label` 16～1023。

```cli
[Huawei] static-lsp egress lsp-name [ incoming-interface interface-type interface-number ] in-label in-label
[Huawei] display mpls static-lsp ...
```

### 配置案例（续至下一章）

需求：1.1.1.0/24 与 3.3.3.0/24 经静态 LSP 互通。标签规划：R1 Out=200；R2 In=200 Out=300；R3 In=300 Out=Null。

```cli
[R1] mpls lsr-id 10.1.1.1
[R1] mpls
[R1-mpls] quit
[R1] interface GigabitEthernet 0/0/0
[R1-GigabitEthernet0/0/0] mpls
```

（Ingress/Transit/Egress 静态 LSP 命令与检查见下一章。）
