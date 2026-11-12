---
doc_id: "hcip-datacom-core-training-12"
title: "DHCPv6、IPv6地址配置与防火墙基础"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 12
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# DHCPv6、IPv6地址配置与防火墙基础

## DHCPv6 有状态自动配置：四步交互

1. 客户端发送 **Solicit**，请求分配 IPv6 地址/前缀和网络配置参数。
2. 服务器回复 **Advertise**，通知可分配的地址/前缀和参数。
3. 若收到多台服务器的 Advertise，客户端根据接收先后、服务器优先级等选择一台，发送 **Request** 请求确认。
4. 服务器回复 **Reply**，确认将地址/前缀和参数分配给客户端。

两步交换可提高效率，但适用在网络中只存在一台 DHCPv6 服务器的情况。多服务器网络中，客户端实际只能使用其中一个服务器分配的地址/前缀和参数。

## 地址 / 前缀租约更新

DHCPv6 服务器分配的 IPv6 地址/前缀具有有效时间。超过有效时间后客户端不能再使用该地址/前缀；若希望继续使用，需在超时前更新租约。

### T1 时刻 Renew

1. 客户端在 T1 时刻（默认为 Preferred Lifetime 的 1/2）发送 **Renew** 进行租约更新请求。
2. 若可继续使用，服务器回应续约成功的 **Reply**；否则回应续约失败的 Reply。

### T2 时刻 Rebind

若服务器未响应 T1 的 Renew，客户端在 T2（默认为 Preferred Lifetime 的 0.8 倍）向所有 DHCPv6 服务器组播发送 **Rebind** 请求更新租约；服务器以 Reply 回应成功或失败。

## DHCPv6 无状态自动配置与 PD

主机生成链路本地地址并 DAD 无冲突后，发起路由器发现（RS/RA）。若 RA 中 M-bit 为 0、O-bit 为 1，则主机通过 DHCPv6 **无状态**自动配置获取除地址/前缀外的其他参数（如 DNS、SIP、SNTP 等）。

**DHCPv6 PD** 一般用于网络中存在路由器（作为 DHCPv6 客户端）需要继续为下连 IPv6 主机分配前缀的场景：客户端可同时请求 IA_NA（WAN 口地址）和 IA_PD（LAN 侧前缀）；下层路由器把获得前缀（一般长度小于 64）细分成 /64，再通过 RA 通告给主机。

## DHCPv6 中继

当服务器和客户端不在同一网段时，使用中继：

1. 客户端向所有 DHCPv6 服务器和中继的组播地址 FF02::1:2 发送请求。
2. 中继将报文封装在 **Relay-Forward** 的中继消息选项中，发给服务器或下一跳中继。
3. 服务器解析请求，选取地址和其他参数，发送 **Relay-Reply** 给中继。
4. 中继解析应答并转发给客户端。

## 地址确认、冲突检测与释放

- **Confirm**：客户端断电、掉线、漫游等后，发送 Confirm 确认地址是否可用；合法则服务器回应，否则重新申请。
- **Decline**：客户端完成申请后发起 DAD；若冲突，发送 Decline 通知服务器并不再使用该地址。
- **Release**：不再需要某地址时发送 Release，服务器以 Reply 确认。

## DHCPv6 报文总结

| 报文 | 作用 |
| --- | --- |
| Solicit | 客户端请求分配地址/前缀和网络配置参数 |
| Advertise | 服务器通知可分配内容 |
| Request | 客户端请求服务器确认分配 |
| Reply | 服务器确认分配/续约/释放等结果 |
| Information-request | 客户端请求除地址外的配置参数（Option Request） |
| Renew | T1 时向原服务器单播更新租约 |
| Rebind | T2 时向所有服务器组播更新租约 |
| Confirm | 确认地址是否仍可用 |
| Decline | 发现地址冲突时通知服务器 |

## 地址自动配置比较

| 对比项 | 基于 DHCPv6 | 基于 NDP（SLAAC） |
| --- | --- | --- |
| 地址管理 | 有状态，服务器存储分配/释放信息 | 无状态，不保存用户地址分配信息 |
| 部署价值 | 支持 128bit 地址和不同长度前缀，扩展性强 | 只支持 64bit 前缀配置，扩展性差 |
| 实现难度 | 配置复杂 | 配置简单 |
| 安全性 | 应用层协议，安全性相对更强 | 安全性较差 |

## IPv6 基本配置命令

```cli
[Huawei] ipv6
[Huawei-GigabitEthernet0/0/0] ipv6 enable
[Huawei-GigabitEthernet0/0/0] ipv6 address ipv6-address link-local
[Huawei-GigabitEthernet0/0/0] ipv6 address auto link-local
[Huawei-GigabitEthernet0/0/0] ipv6 address { ipv6-address prefix-length | ipv6-address/prefix-length }
[Huawei-GigabitEthernet0/0/0] ipv6 address auto { global | dhcp }
[Huawei] display ipv6 interface [ interface-type interface-number | brief ]
[Huawei] display ipv6 neighbors
[Huawei-GigabitEthernet0/0/0] undo ipv6 nd ra halt
```

默认情况下，华为路由器接口抑制 ICMPv6 RA 报文发送。需要周期性发布前缀和有状态标志位时，使用 `undo ipv6 nd ra halt` 使能发布 RA。

## IPv6 地址配置举例

配置需求：

- R1 的 GE0/0/0、GE0/0/1 手工配置 IPv6 地址
- R2 的 GE0/0/0 通过无状态地址自动配置获取
- R3 的 GE0/0/0 通过 DHCPv6 获取

### 静态配置（R1）

```cli
[R1] ipv6
[R1] interface GigabitEthernet 0/0/0
[R1-GigabitEthernet0/0/0] ipv6 enable
[R1-GigabitEthernet0/0/0] ipv6 address auto link-local
[R1-GigabitEthernet0/0/0] ipv6 address 2001:DB8:13::1 64
[R1-GigabitEthernet0/0/0] interface GigabitEthernet 0/0/1
[R1-GigabitEthernet0/0/1] ipv6 address 2001:DB8:12::1 64
```

### 无状态自动配置（R2）

```cli
[R1] interface GigabitEthernet 0/0/1
[R1-GigabitEthernet0/0/1] undo ipv6 nd ra halt
[R2] interface GigabitEthernet 0/0/0
[R2-GigabitEthernet0/0/0] ipv6 address auto global
```

### DHCPv6（R1 作服务器，R3 作客户端）

```cli
[R1] dhcp enable
[R1] dhcpv6 pool pool1
[R1-dhcpv6-pool-pool1] address prefix 2001:DB8:13::/64
[R1-dhcpv6-pool-pool1] excluded-address 2001:DB8:13::1
[R1] interface GigabitEthernet 0/0/0
[R1-GigabitEthernet0/0/0] dhcpv6 server pool1

[R3] dhcp enable
[R3] interface GigabitEthernet 0/0/0
[R3-GigabitEthernet0/0/0] ipv6 address auto dhcp
```

验证：

```cli
[R2] display ipv6 interface GigabitEthernet 0/0/0
[R3] display dhcpv6 client
```

### 思考题（地址自动配置）

1. 基于 NDP 的无状态地址自动配置只能为主机分配 IPv6 前缀（不能直接分配完整 128 位地址、DNS 等）——选 C。
2. 用到 Reply 报文的过程包括：信息获取、前缀分配两步交互、地址分配四步交互、地址释放、地址续约等。

### 本章总结（IPv6 地址配置）

- 网络设备互联地址、环回口等多用静态；终端多用动态自动配置。
- SLAAC 只支持 /64 前缀，管控较弱；DHCPv6 可实现 PD 等更丰富功能。
- 客户端采用何种方式由 RA 中 M-bit、O-bit 决定。

## 华为防火墙技术

### 为什么需要防火墙

路由器和交换机构建互联互通网络，同时带来安全隐患。企业边界常见诉求：外部网络安全隔离、内部网络安全管控、内容安全过滤、入侵防御、防病毒等。

防火墙形态包括框式、盒式、桌面型、软件防火墙；本课程聚焦框式/盒式硬件防火墙。

| 设备 | 作用（园区网示例） |
| --- | --- |
| 交换机 | 接入终端和汇聚内部路由，组建局域网 |
| 路由器 | 路由分发、寻址和转发，构建外部连接 |
| 防火墙 | 流量控制和安全防护，区分和隔离不同安全区域 |

防火墙转发流程比路由器复杂：除接口、LPU、交换网板外，还有 SPU（Service Processing Unit）实现 DDoS 防范、会话匹配、状态检测、认证/安全/NAT/内容安全/带宽策略等。

**DMZ（Demilitarized Zone）**：介于严格管制区与松散公共区之间的部分管制区域；企业中一般用于放置需对外提供服务的服务器。

### 防火墙发展历程

包过滤防火墙 → 状态检测 → 基于 ASIC → UTM → 多核+分布式架构 NGFW → AI 防火墙。趋势：访问控制更精细、防护更强、性能更高。

包过滤主要基于五元组等信息，实现简单但性能随 ACL 复杂度下降、难适应动态安全、不检查会话状态。状态检测防火墙对连接首包检测确定状态，后续报文按连接状态控制。

华为 HiSecEngine USG6000E 等为 AI 防火墙方向产品；相关概念包括 APT、沙箱（如 Firehunter）、CIS、CDE、AIE 等。

### 安全区域（Security Zone）

安全区域是防火墙若干接口所连网络的集合，同一区域内用户具有相同安全属性。防火墙大部分安全策略基于安全区域实施。

默认安全区域（小写、大小写敏感）：

| 区域 | 典型用途 |
| --- | --- |
| untrust | Internet 等不安全网络 |
| dmz | 内网服务器区（常被外网访问，一般不允许其主动访问外网） |
| trust | 内网终端用户区 |
| local | 设备本身；用户不能改变 local 配置、不能向其中添加接口 |

流量的源、目的地址决定互访区域（例如 PC 访问防火墙接口：trust→local；PC 访问 Internet：trust→untrust）。

### 安全策略

安全策略控制防火墙对流量转发以及内容安全一体化检测。收到流量后识别属性（五元组、用户、时间段等）并与策略条件匹配，匹配则执行对应动作。

动作：

- **允许**：无内容安全检测则放行；有则按各安全配置文件结论决定
- **禁止**：丢弃，并可选择 Reset 客户端/服务器、ICMP 不可达等反馈

系统默认存在缺省安全策略 default，位于列表最底部，条件均为 any，动作默认为禁止。

### 会话表与 Server-map

会话表记录通信双方连接状态（如协议、地址端口、VPN 实例等）。防火墙为各种协议设定会话老化；长连接（Long Link）可为特殊业务设定超长老化时间。

- **单通道协议**：只需一个端口（如 WWW/80）
- **多通道协议**：需两个或以上端口（如 FTP 控制连接+数据连接；主动/被动模式）

Server-map：在配置 ASPF、NAT Server、No-PAT 源 NAT 等时生成。报文先查会话表；未命中再查 Server-map；命中 Server-map 不受安全策略控制，并据之生成会话表。

### 防火墙基础配置

接口与管理：

```cli
[Huawei] interface interface-type interface-number
[Huawei-GigabitEthernet0/0/1] service-manage { http | https | ping | ssh | snmp | netconf | telnet | all } { permit | deny }
```

缺省开启接口访问控制管理；仅管理口放开 HTTP/HTTPS/Ping，非管理口默认全关。即使配置了安全策略允许访问 local，未放开 service-manage 也不能通过该接口访问本机。

安全区域：

```cli
[Huawei] firewall zone name zone-name [ id id ]
[Huawei-zone-name] set priority security-priority
[Huawei-zone-name] add interface interface-type { interface-number | interface-number.subinterface-number }
```

优先级 1～100，全局唯一，值越大优先级越高。默认区域不能删除，优先级也不能重配。

安全策略：

```cli
[Huawei] security-policy
[Huawei-policy-security] rule name rule-name
[Huawei-policy-security-rule-name] source-zone { zone-name &<1-6> | any }
[Huawei-policy-security-rule-name] destination-zone { zone-name &<1-6> | any }
```

### 防火墙配置案例

需求：新建安全区域 OM（优先级 95）；允许 GE1/0/1 响应 Ping；允许 OM 区域 ICMP 访问 untrust。

```cli
[FW] interface GigabitEthernet 1/0/1
[FW-GigabitEthernet1/0/1] ip address 1.1.1.1 24
[FW-GigabitEthernet1/0/1] service-manage ping permit
[FW] interface GigabitEthernet 1/0/2
[FW-GigabitEthernet1/0/2] ip address 2.2.2.1 24
[FW] interface GigabitEthernet 1/0/3
[FW-GigabitEthernet1/0/3] ip address 3.3.3.1 24

[FW] firewall zone name OM
[FW-zone-OM] set priority 95
[FW] firewall zone trust
[FW-zone-trust] add interface GigabitEthernet 1/0/1
[FW] firewall zone OM
[FW-zone-OM] add interface GigabitEthernet 1/0/2
[FW] firewall zone untrust
[FW-zone-untrust] add interface GigabitEthernet 1/0/3

[FW] security-policy
[FW-policy-security] rule name R1
[FW-policy-security-rule-R1] source-zone OM
[FW-policy-security-rule-R1] destination-zone untrust
[FW-policy-security-rule-R1] service icmp
[FW-policy-security-rule-R1] action permit
```

验证：`display firewall session table`。ICMP 无端口，但防火墙生成会话时会生成相应“端口号”以满足状态检测。

### 思考题（防火墙）

1. 缺省情况下防火墙有几个安全区域？**4**
2. 防火墙在生成会话表之前，都需要先生成 Server-map？**否**
3. 华为 AI 防火墙相关能力可包括内置恶意文件检测引擎（CDE）、APT 检测引擎（AIE）等。

## 网络设备安全特性（开篇）

IP 网络设备数量多、协议复杂，安全与业务灵活性、维护便利性之间存在矛盾。管理员常追求业务可用性而忽略安全加固。本课程介绍常见设备安全加固策略。

学完后应能够：描述常见设备安全加固策略；实现 STelnet 配置；实现本机防攻击配置。

常见攻击示例：恶意登录执行非法操作；伪造大量控制报文造成 CPU 升高。

加固方向：

1. 关闭不使用的业务和协议端口
2. 废弃不安全的访问通道
3. 基于可信路径的访问控制
4. 本机防攻击

关闭不使用端口示例：

```cli
[SW1] undo ftp server
[SW1] port-group portgroup1
[SW1-port-group-portgroup1] group-member GigabitEthernet 0/0/4 to GigabitEthernet 0/0/48
[SW1-port-group-portgroup1] shutdown
```

登录与传输建议采用 SSH、HTTPS、SNMPv3、SFTP 等加密通道。STelnet 基于 SSH，提供安全认证；SSH 最新版本 V2.0，1.3/1.5 存在安全隐患。SSH 使用的算法类别包括 MAC、加密、密钥交换、主机公钥（RSA/DSA）等。
