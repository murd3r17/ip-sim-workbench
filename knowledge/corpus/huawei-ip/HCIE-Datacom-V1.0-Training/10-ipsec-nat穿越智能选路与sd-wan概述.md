---
doc_id: "hcie-datacom-v1.0-training-10"
title: "IPsec、NAT穿越、智能选路与SD-WAN概述"
book: "HCIE-Datacom-V1.0-Training"
book_title: "HCIE-Datacom V1.0 培训教材"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "training"
source_pdf: "HCIE-Datacom+V1.0+培训教材.pdf"
seq: 10
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# IPsec、NAT穿越、智能选路与SD-WAN概述

## 1. IPsec 安全协议与工作原理

### AH 与 ESP

- **AH** 仅支持认证功能，不支持加密功能。AH 在每一个数据包的标准 IP 报头后面添加一个 AH 报文头。AH 对数据包和认证密钥进行 Hash 计算，接收方收到带有计算结果的数据包后，执行同样的 Hash 计算并与原计算结果比较；传输过程中对数据的任何更改将使计算结果无效，从而提供数据来源认证和数据完整性校验。AH 协议的完整性验证范围为整个 IP 报文。
- **ESP** 支持认证和加密功能。ESP 在每一个数据包的标准 IP 报头后面添加一个 ESP 报文头，并在数据包后面追加 ESP Trailer 和 ESP Auth data。与 AH 不同的是，ESP 将数据中的有效载荷进行加密后再封装到数据包中，以保证数据的机密性；但 ESP 没有对 IP 头的内容进行保护，除非 IP 头被封装在 ESP 内部（采用隧道模式）。

关键字段含义：

- **Sequence Number**：从 1 开始的单项递增计数器，唯一标识每一个数据包，用于防止重放攻击。
- **SPI**：IPsec 安全参数索引，用于唯一标识 IPsec 安全联盟。
- **Authentication Data**：包含数据完整性校验值 ICV（Integrity Check Value），用于接收方进行完整性校验。可选择的认证算法有 MD5、SHA1、SHA2、SM3。

### 传输模式与隧道模式

- **传输模式**：AH 头或 ESP 头被插入到 IP 头与传输层协议头之间，保护 TCP/UDP/ICMP 负载。由于未添加额外的 IP 头，原始报文中的 IP 地址在加密后报文的 IP 头中可见。
- **隧道模式**：AH 头或 ESP 头被插到原始 IP 头之前，另外生成一个新的报文头放到 AH/ESP 头之前，保护 IP 头和负载。

### IPsec 基本工作流程

1. 通过 IKE 协商第一阶段协商出 IKE SA。
2. 使用 IKE SA 加密 IKE 协商第二阶段的报文，即 IPsec SA。
3. 使用 IPsec SA 加密数据。

### IKEv1 协商

采用 IKEv1 协商安全联盟主要分为两个阶段：

- **第一阶段**：通信双方协商并建立 IKE 协议本身使用的安全通道，即建立一个 IKE SA。
- **第二阶段**：利用第一阶段已通过认证与安全保护的安全通道，建立一对用于数据安全传输的 IPsec SA。

#### 主模式与野蛮模式（阶段 1）

主模式包含三次双向交换，用到六条 ISAKMP 信息：

1. **消息①和②：提议交换**  
   发起方发送一个或多个 IKE 安全提议，响应方查找最先匹配的 IKE 安全提议并回应。匹配原则为协商双方具有相同的加密算法、认证算法、认证方法和 Diffie-Hellman 组标识。
2. **消息③和④：密钥信息交换**  
   双方交换 Diffie-Hellman 公共值和 nonce 值，用于 IKE SA 的认证和加密密钥在这个阶段产生。
3. **消息⑤和⑥：身份和认证信息交换**  
   双方使用生成的密钥发送信息，进行身份认证和对整个主模式交换内容的认证。

野蛮模式只用到三条信息：前两条消息①和②用于协商 IKE 安全提议，交换 Diffie-Hellman 公共值、必需的辅助信息以及身份信息，并且消息②中还包括响应方发送身份信息供发起方认证；消息③用于响应方认证发起方。与主模式相比，野蛮模式减少了交换信息数目、提高协商速度，但没有对身份信息进行加密保护。

#### IKEv1 阶段 2

通过三条 ISAKMP 消息完成双方 IPsec SA 的建立：

1. 协商发起方发送本端的安全参数和身份认证信息（被保护数据流、IPsec 安全提议等；身份认证信息包括第一阶段计算出的密钥和第二阶段产生的密钥材料等，可再次认证对等体）。
2. 协商响应方发送确认的安全参数和身份认证信息并生成新的密钥。IPsec SA 数据传输需要的加密、验证密钥由第一阶段产生的密钥、SPI、协议等参数衍生得出，以保证每个 IPsec SA 都有自己独一无二的密钥。
3. 发送方发送确认信息，确认与响应方可以通信，协商结束。

### IKEv2 协商

IKEv2 简化了 IKEv1 协商 SA 的过程。IKEv2 通常使用 2 次交换共 4 条消息就可以完成一对 IPsec SA 的建立；如果要求建立的 IPsec SA 大于一对，每一对 IPsec SA 只需额外增加 1 次创建子 SA 交换（2 条消息）。

IKEv2 定义了三种交换：

- 初始交换（Initial Exchanges）
- 创建子 SA 交换（Create_Child_SA Exchange）
- 通知交换（Informational Exchange）

#### IKE_SA_INIT 与 IKE_AUTH

- 消息①和②属于第一次交换（IKE_SA_INIT），以明文方式完成 IKE SA 的参数协商，包括协商加密和验证算法、交换临时随机数和 DH 交换。之后生成共享密钥材料，可衍生出 IPsec SA 的所有密钥。
- 消息③和④属于第二次交换（IKE_AUTH），以加密方式完成身份认证、对前两条信息的认证和 IPsec SA 的参数协商。IKEv2 支持 RSA 签名认证、预共享密钥认证以及扩展认证方法 EAP（Extensible Authentication Protocol）。发起者可通过在消息 3 中省去认证载荷来表明需要使用 EAP 认证。

#### 创建子 SA 与通知交换

当一个 IKE SA 需要创建多对 IPsec SA 时，使用创建子 SA 交换来协商多于一对的 IPsec SA；还可用于 IKE SA 的重协商。创建子 SA 交换包含一个交换两条消息，对应 IKEv1 协商阶段 2；发起者可以是初始交换的协商发起方，也可以是响应方。

运行 IKE 协商的两端有时会传递控制信息（错误信息或通告信息），在 IKEv2 中通过通知交换完成。通知交换必须在 IKE SA 保护下进行，只能发生在初始交换之后。

### 路由方式引入 IPsec 流量的优点

- 通过路由将需要 IPsec 保护的数据流引到虚拟隧道接口，不需使用 ACL 定义待加/解密的流量特征，简化配置复杂性。
- 支持动态路由协议。
- 通过 GRE over IPsec 支持对组播流量的保护。

### IPsec 应用场景：GRE over IPsec / L2TP over IPsec

#### GRE over IPsec

- 封装模式可以是隧道模式也可以是传输模式。隧道模式比传输模式增加了 IPsec 头，报文更长、更容易导致分片，所以 GRE over IPsec 推荐采用传输模式。
- IPsec 封装过程中增加的 IP 头：源地址为 IPsec 网关应用 IPsec 安全策略的接口地址，目的地址为对等体应用安全策略的接口地址。
- IPsec 需要保护的数据流为从 GRE 起点到 GRE 终点的数据流。GRE 封装增加的 IP 头源为 GRE 隧道源端地址，目的为 GRE 隧道目的端地址。

#### L2TP over IPsec

- 报文在隧道中传输时先进行 L2TP 封装再进行 IPsec 封装。
- IPsec 需要保护的是从 L2TP 起点到终点的数据流。分支接入总部组网中，L2TP 起点为 LAC 出接口 IP，终点为 LNS 入接口 IP。
- 由于 L2TP 封装已增加一个公网 IP 头，隧道模式又多增加一个公网 IP 头，更容易导致分片，推荐采用传输模式 L2TP over IPsec。
- 出差用户远程接入总部网络时，协商顺序和封装顺序与分支接入总部相同；不同的是用户侧 L2TP 和 IPsec 封装在客户端完成。L2TP 起点地址为客户端将要获取的内网地址（可为 LNS 地址池中任意地址），终点为 LNS 入接口地址。

缩写：SA = Source Address；DA = Destination Address；SP = Source Port；DP = Destination Port。

### IPsec 穿越 NAT

为解决 NAT 环境下 IPsec 互通问题，必须在建立 IPsec 隧道的两个网关上开启 NAT 穿越功能（NAT Traversal）。开启后，当检测到（IKE 协商过程中检测）两台网关中间存在 NAT 设备，ESP 报文会被封装在一个 UDP 头部中，源目端口号 4500，以此支持经过 NAT 设备。添加 UDP 头部之后，经过 SNAT（NAPT）会改变 UDP 头部中的源端口。

#### NAT-T 协商要点（IKEv1）

- 开启 NAT 穿越时，IKEv1 协商第一阶段的前两个消息会发送标识 NAT Traversal（NAT-T）能力的 Vendor ID 载荷（主模式和野蛮模式都是），用于检查双方是否支持 NAT-T；双方都包含该载荷时才会进行相关协商。
- 主模式消息 3 和消息 4（野蛮模式消息 2 和消息 3）中发送 NAT-D（NAT Discovery）载荷，用于探测两个要建立 IPsec 隧道的网关之间是否存在 NAT 网关以及 NAT 位置。通过协商双方向对端发送源和目的 IP 地址与端口的 Hash 值，可检测地址和端口在传输过程中是否发生变化。若双方计算的 Hash 值与收到的一致，则表示没有 NAT；否则说明传输过程中对 IP 或端口进行了 NAT 转换。
- 发现 NAT 网关后，后续 ISAKMP 消息（主模式从消息 5、野蛮模式从消息 3 开始）的端口号转换为 4500。

#### 场景（1）：分部在 NAT 后，总部不知分部公网地址

NAT 设备位于分部网络之外，分部网关出接口私网 IP 为 X，经 NAT 后变为公网 Y。总部无从获知转换后的分部公网地址，无法在总部明确指定对端公网地址。因此总部必须使用模板方式配置 IPsec，同时总部和分部网关上都要开启 NAT 穿越。总部使用模板方式后无法主动访问分部，只能由分部主动向总部发起 ISAKMP 协商。

#### 场景（2）：分部自管 NAT，公网地址固定

NAT 为分部自己管理设备，且公网 IP 固定、可知。总部可使用模板方式或手动指定对等体方式配置 IPsec。由于 NAT 设备只进行源地址转换，依旧只能由分部主动发起 ISAKMP 协商。

#### 场景（3）：NAT Server 映射 UDP 500/4500

NAT 设备为分部管理设备，提供 NAT Server 功能，映射网关接口地址（UDP 500、UDP 4500）。总部使用手动指定对等体方式配置 IPsec，可实现总部主动发起 ISAKMP 协商以及流量访问；总部、分部都可以同时发起 ISAKMP 协商。

#### NAT 会话保活

网关 1 处在 SNAT（NAPT）设备之后时，通常只能由网关 1 主动发起流量访问；网关 2 无法主动发起，或仅在 NAT 转换表项存在期间可以主动访问。为了保证双方都可以任意发起流量访问，需要保证 SNAT 设备的 NAT 会话不会超时。

NAT Keepalive 报文格式非常简单：在 UDP 头部之后为两个十六进制 F，用于刷新 NAT 设备会话表项。

## 2. 广域互联 NAT 穿越技术

### NAT 基本原理

NAT（Network Address Translation，网络地址转换）于 1994 年提出。当专用网内部主机已分配本地 IP 地址，但又想和因特网上的主机通信（并不需要加密）时，可使用 NAT。NAT 不仅能解决 IP 地址不足的问题，还能有效避免来自网络外部的攻击，隐藏并保护网络内部的计算机。

#### NAPT / Easy-IP

NAPT 借助端口可以实现一个公有地址同时对应多个私有地址。该模式同时对 IP 地址和传输层端口进行转换，实现不同私有〔源 IP、端口〕映射到同一个〔公有地址、不同源端口〕上。

由于 TCP/UDP 的端口数量有限（0~65535），一个地址能够映射的私网会话有限；基于 NAT 地址池，NAPT 可以将私网会话随机映射到地址池中的一个地址，缓解私网会话过多的问题。

NAT 映射条目由首包触发，当一段时间没有流量时，为了安全考虑 NAT 映射条目自动删除。由于 NAPT/Easy-IP 只改变数据包源地址和端口，所以也被称为源 NAT。

#### NAT Server

NAT Server：指定〔公有地址：端口〕与〔私有地址：端口〕的一对一映射关系，将内部服务器映射到公网，私有网络中的服务器需要对公网提供服务时使用。外网主机主动访问〔公有地址：端口〕实现对内部服务器的访问。

示例映射：`192.168.1.10:80` ↔ `122.1.2.1:8080`。

#### NAT 地址池的路由发布

某些情况下 NAT 设备不一定是出口设备，因此需要将回程流量引导至 NAT 设备，可在路由协议中引入 UNR 路由。

UNR（User Network Route，用户网络路由）是非接口 IP 产生的路由，不存在于任何接口上。NAT 场景中，设备会为 NAT 地址池中的地址创建 UNR 主机路由。例如地址池中有 `122.1.2.2` 和 `122.1.2.3`，则设备会自动创建 `122.1.2.2/32` 和 `122.1.2.3/32` UNR 路由，并可通过 OSPF 等协议传递。

### NAT 类型介绍

NAT 有 4 种不同的类型：

1. Full Cone NAT
2. Restricted Cone NAT
3. Port Restricted Cone NAT
4. Symmetric NAT

#### Full Cone NAT（完全圆锥型）

同一内部 Tuple 请求被 NAT 转换至同一外部 Tuple，任意外部主机都能以外部 Tuple 中的地址和端口为目标发送报文，NAT 设备对收到的报文能正确转发。处理方法简单，但安全性有缺陷：内网 PC 与 Web 服务器通信后生成映射表，攻击者以外部 Tuple 为目标发送数据即可打到 PC。

#### Restricted Cone NAT（限制圆锥型）

对外部主机回包时，除查看报文目的地址+端口是否与外部 Tuple 一致外，还会查看报文源 IP 是否与目标 Tuple 中的 IP 地址一致，一致才转发。攻击者需要以外部 Tuple 为目标地址+端口，并以目标 Tuple 的 IP 为源发送数据，数据才会被发送给内网 PC。

#### Port Restricted Cone NAT（端口限制圆锥型）

Restricted Cone NAT 的进一步受限版本：对外部主机回包除检查源 IP+端口外，还需要检查目的 IP+端口是否与目标 Tuple 一致。安全性很高。攻击者需要以外部 Tuple 为目标，并以目标 Tuple（含端口，如 `200.1.2.3:80`）为源发送数据。

#### Symmetric NAT（对称型）

同一内部 Tuple 加上同一目标 Tuple 才会被 NAT 转换成同一外部 Tuple，否则会转换成不同外部 Tuple。对返回数据的处理和 Port Restricted Cone NAT 类似，需要查看回程数据的源 IP+端口、目的 IP+端口与外部 Tuple 和目标 Tuple 是否一致。内网 PC 与不同目标（如 Web 与 DNS）通信时，即使源 IP+端口一致也会生成不同映射表项。

#### 应用场景说明

现网中 NAPT 或 Easy-IP 技术一般使用的是 Symmetric NAT 类型。现网可能存在 NAT 穿越要求，此时可以使用 Cone NAT 支持 NAT 穿越技术。

### NAT 穿越技术介绍

NAT 技术虽能使私网访问公网，但也有缺陷：NAT 隐藏了私网 IP，部分服务器为防 DoS 会限制同一 IP 访问频率；部分应用也没法有效溯源原始设备，导致网络管理定位困难。为解决 IP 端到端应用在 NAT 环境下遇到的问题，产生了多种 NAT 穿越技术。

现有方法主要包括：

- UPnP（Universal Plug and Play）
- ALG（Application Layer Gateway）
- MIDCOM（Middlebox Communications）
- Full Proxy
- STUN（Simple Traversal of UDP Through Network Address Translators / Session Traversal Utilities for NAT）
- TURN（Traversal Using Relay NAT）
- ICE（Interactive Connectivity Establishment）
- STUNT

本课程主要介绍 ALG、STUN 这两种穿越技术。

#### NAT ALG

现网提供各类服务（HTTP、DNS、FTP 等）的服务器一般部署在私网，因此需要在 NAT 上部署 NAT Server 使外网用户能够访问。但部分服务用到的协议是多通道协议（如 FTP、DNS、SIP 等），仅部署 NAT Server 不能使外网用户完整访问。对于这些多通道协议，可以使用 NAT ALG 解决问题。

以 FTP 被动模式为例：管理通道建立后，服务器告知客户端数据通道所用端口；若 NAT 映射表内无相关信息，数据通道建立失败。FTP 无论主动模式还是被动模式都难以单靠 NAT Server 解决多通道问题。

NAT ALG（Application Level Gateway）可以对报文的载荷字段进行解析，识别并转换其中包含的重要信息（比如 FTP 数据通道目标端口），基于这些重要信息形成 NAT 映射表项，帮助外部主机访问私网服务器。

NAT ALG 的缺陷：

- 需要读取协议报文内容，对新协议需要升级 ALG 特性，基本不支持私有多通道协议。
- 现网有大量设备不支持 NAT ALG，部署成本比较高。

#### STUN

STUN 在 RFC3489 中定义，最初作为完整的 NAT 穿透解决方案，全称 Simple Traversal of UDP Through NATs。在 RFC5389 修订中把 STUN 定位于为穿透 NAT 提供工具，而不是完整解决方案，全称 Session Traversal Utilities for NAT；与 RFC3489 除名称变化外，最大区别是支持 TCP 穿透。

STUN 采用客户端/服务器通信模式，通过 STUN 客户端与 STUN 服务器之间的报文交互，可以发现 NAT 设备的存在，并确定 NAT 设备分配的 IP 地址和端口号。

基本流程：

1. STUN 客户端向 STUN 服务器发送 Binding Request。
2. STUN 服务器获取该报文源 IP 和源端口，构建 Binding Response 发送给客户端。
3. 客户端根据响应获取 IP/端口，与发送请求时的源 IP/端口比较；不一致则前面存在 NAT 设备。
4. 客户端之间学习对端 NAT 信息（NAT 前/后的 IP 与端口）。
5. 客户端使用本端 NAT 前地址端口分别与对端 NAT 前、NAT 后地址端口构建 Binding Request 发往对端；对端同样操作。
6. 对端收到后回 Binding Response；完成交互后建立可 NAT 穿越的数据通道。

## 3. 广域互联智能选路技术

### SAC 介绍

云计算时代，网络不能只基于过去的五元组管理网络，而需要以应用为维度管理监控网络。传统路由交换设备难以识别应用层信息。SAC（Smart Application Control，智能应用控制）利用 SA（Service Awareness，业务感知）和 FPI（First Packet Identification，首包识别），对报文中的第 4～7 层内容（如 HTTP、RTP）进行检测和识别。

SAC 特征库文件只能以升级方式更新，不可以手动修改。升级方式：

- **在线升级**：可通过安全中心平台或者内网升级服务器升级。
- **本地升级**：通过安全中心平台下载升级包，经 FTP 上传到设备本地并升级。

识别流程（与前文一致）：五元组命中已识别应用则直转发；否则进入 SAC：FPI ACL → FPI DNS 关联表 → FPI 协议端口表 → SA。

#### SA

设备接收数据后可使用 SA 匹配应用。SA 使用 SA 特征库感知业务，现有特征库内置 6000+ 应用，对公有应用有非常高的识别率。一般不能手工修改，只能通过在线或本地升级更新。匹配条件常包括域名、Server IP、协议等。

#### FPI

FPI 应用分为：

- 基于协议+端口的预定义/自定义 FPI 应用（生成协议端口表项）。
- 基于 DNS 域名的预定义/自定义 FPI 应用（与 DNS 功能联动，生成 DNS 关联应用表项）。
- 基于五元组+DSCP 的自定义 FPI 应用（高级 ACL）。

基于 DNS 域名的识别：FPI 特征库包含域名和应用对应关系，DNS 应答携带域名和 IP 对应关系，设备建立“IP—应用”关联表，再根据业务报文 IP 查找识别应用。

### SPR 介绍

SPR（Smart Policy Routing，智能策略路由）可主动探测链路质量并匹配业务需求，选择最优链路转发业务数据，有效避免网络黑洞、网络震荡等问题。

SPR 支持通过以下属性区分业务：

- 协议类型：IP、TCP、UDP、GRE、IGMP、IPINIP、OSPF、ICMP。
- 报文应用：DSCP、TOS、IP Precedence、Fragment、VPN、TCP-flag。
- 报文信息：Source/Destination IP Address、Protocol、Source/Destination Port、Source/Destination IP Prefix。

CMI 计算：

- 根据 NQA：`CMI = 9000 – cmi-method`，其中 cmi-method 缺省定义为 `D+J+L`；使用 NQA 时 CMI 值越大越优。
- 根据 IP FPM：`CMI = D+J+L`；使用 IP FPM 时 CMI 值越小越优。

#### 探测链路与链路组

探测链路通过探针（NQA、IP FPM）获取链路质量参数，SPR 根据链路质量匹配业务需求实现智能选路。SPR 以链路组形式使用探测链路，一个链路组可有一条或多条探测链路。链路角色分为：主用链路组、备用链路组和逃生链路；业务无法从主用/备用链路组找到合适链路时可启用逃生链路。

#### 振荡抑制

网络时好时坏会导致 SPR 频繁切换链路。振荡抑制周期默认不生效，由用户配置。SPR 切换链路后计时器开始计时；若业务驻留链路时间未达到振荡抑制周期，则不会执行链路切换。超时后，若一个切换周期内链路仍不满足业务需求则切换；若质量变好满足需求则不切换。

#### 使用 iMaster NCE 实现 SPR

使用 NCE 部署 SPR 时，提高全网站点规格，采用站点与应用策略分离及流量触发选路相结合的方式。NCE 仅维护站点邻接信息和应用策略，SPR 配置由路由器创建；使用流量触发选路，按需生成 SPR 配置，避免设备创建大量配置，同时减少探测选路（基于 IP FPM）对设备 CPU 造成的冲击。NCE 可通过 SAC，基于应用分类业务流量。

## 思考题

1. （多选题）以下哪些是专线技术？
   - A. SDH
   - B. L2TP
   - C. MPLS VPN
   - D. IPsec VPN  
   **答案：A、C**

2. （判断题）SRP（SPR）技术能基于链路质量灵活选择出口链路。  
   - A. 正确  
   - B. 错误  
   **答案：A（正确）**

## 本章总结（广域互联常用技术）

- 广域网互联方式主要使用 GRE Over IPsec 技术，用户远程接入内网主要使用 L2TP Over IPsec 技术。
- 基于 IKE SA 信息，IPsec SA 信息就能在公网上安全传输；基于 IPsec SA 信息，业务数据就能在公网上安全传输。
- 在两台私网设备之间建立广域互联需要使用 NAT 穿越技术，常用的 NAT 穿越技术为 STUN。
- 保障广域网可靠性一般需要先探测链路质量，基于链路质量再通过特定技术选择合适出口或出口链路。

---

## 4. 华为 SD-WAN 解决方案概述（续篇开头）

### 前言与目标

广域互联网经过多年发展与演进，发生了重大变化。过去主要以网络为中心，应用整体较少；随着云计算崛起，应用潜能被充分挖掘，广域互联网逐渐变为以应用为中心。面对云计算对广域互联网的挑战，华为推出了 SD-WAN 解决方案。

学完本课程后，您将能够：

- 描述企业广域互联网面临的挑战
- 描述华为 SD-WAN 解决方案的架构与功能
- 描述 SD-WAN 组网设计方案
- 描述 SD-WAN 业务设计方案
- 描述 SD-WAN 可靠性设计方案
- 描述 SD-WAN 安全设计方案

课程大纲：

1. 企业广域互联网络发展趋势与挑战
2. 华为 SD-WAN 解决方案概述
3. 华为 SD-WAN 组网设计
4. 华为 SD-WAN 业务设计
5. 华为 SD-WAN 可靠性与安全设计

### 企业广域互联面临的挑战

#### 云计算挑战

云计算被广泛应用之前，网络应用数量总体较少，网络服务质量主要依靠带宽，互联网主要以网络为中心构建。云计算时代网络应用数量大大增加，企业面对激增的流量，很难在线路价格和业务质量之间找到平衡点。

#### 多业务挑战

企业对于业务流量感知能力比较差，无法有效保障关键业务；同时监控能力不足，无法快速调整业务流量。典型问题：

- 应用不可视，流量难调度；语音、视频、SaaS 等关键业务难管理。
- 优先级冲突：关键应用无法识别，调度优先级低。
- 带宽冲突：业务高峰突发流量可达平均流量 3~5 倍，冲击关键应用；MPLS 主链路高峰拥塞，Internet 备份链路带宽利用率低。
- SaaS 应用总部出局延时大。

#### 大量分支挑战

跨市、跨省、跨国分支增多导致：

- 分支过多导致运维成本过高。
- 分支新业务开通周期较长（商务选型、审批、现场勘测、硬件运输安装、软件调测等）。
- 分支网络排错困难。

#### 相关组织

- **ONUG**（Open Networking User Group）：大企业主导、IT 用户为主的用户组织，致力于大型企业 IT 实现和网络技术转型。
- **Gartner**：全球权威 IT 研究与顾问咨询公司。
- **MEF**（Metro Ethernet Forum）：专注城域以太网技术问题的非盈利组织；面向运营商管理服务市场，提供基于 LSO（Lifecycle Service Orchestration）的方案和架构，并定义北向接口。

### 华为 SD-WAN 解决方案概览

客户价值方向示例：运维成本下降、WAN 利用率提升、分钟级业务发放、运维效率提升（云管理 & 自动化）、收入提升、平滑演进与开放快速集成。

关键技术能力方向：

- 5G 上行：CPE 全系列支持 5G；大带宽（如 UL:230M，DL:900M）；全网通；双架构 NSA/SA。
- 高性能：CPU+NP 异构转发架构。
- 优体验：智能应用选路，关键应用体验可保障；A-FEC 使能视频 20% 丢包不卡顿、不花屏。
- 简运维：全流程自动化，即插即用；多方式 ZTP，网点网络分钟级部署；应用/网点/设备/链路状态可视，集中管理。
- 混合 WAN：DSL/以太网/互联网/LTE、MPLS 等。

### SD-WAN 总体架构

从功能角度看，SD-WAN 解决方案总体架构主要包含网络层、控制层以及编排（管理）层，各层次通过标准接口和通信协议相互关联：

- **管理层**：控制器对企业互联业务全流程精细管理，南向通过 NETCONF 实现对网络设备的纳管，北向提供标准 RESTful 接口与第三方应用对接。
- **控制层**：控制器与分布式控制组件配合，负责区域内不同站点间的路由传递，实现区域间网络的互联互通。
- **网络层**：分支、总部和云平台之间通过高性价比的网络设备，采用 Overlay 技术，按需构建基于 Internet、传统专线等任意链路的全网络联接。

iMaster NCE-WAN / iMaster NCE-Campus 都可以被作为华为 SD-WAN 控制器使用。企业分支、总部、数据中心以及在云上部署的 IT 基础设施可统称为企业站点。

#### iMaster NCE-WAN 控制器框架（要点）

- 北向：RESTful、SNMP Trap、Syslog 等，对接 OSS/BSS、分析系统及其他应用。
- 业务功能：即插即用、流量策略、安全策略、可视化运维、多租户管理、隧道管理、设备配置等。
- 南向：NETCONF、HTTP2.0 等对接 CPE 等网络设备。

虚拟网络可以有多张，服务于同一租户不同业务（如多个部门），也可以服务于不同租户。从网络设备功能定位划分，SD-WAN 网络层主要由 **EDGE** 和 **GW（Gateway）** 两种类型的网元构成。

### EDGE / RR / GW

- **EDGE**：SD-WAN 网络的边界点，EDGE 之间通过 IP Overlay 隧道技术互联。一般可采用传统硬件设备，公有云站点可部署软件虚拟设备（vCPE）。企业所有 SD-WAN EDGE 设备被 iMaster NCE 控制器统一纳管，由租户管理员管理和维护。
- **RR 站点**：站点的 EDGE 承担路由反射器工作，基于 VPN 拓扑策略，负责 EDGE 之间的 EVPN 路由分发。若租户管理员添加出口 EDGE 时设置角色为“网关+路由反射器”，则该站点为 RR 站点；否则为 EDGE 站点。一个 EDGE 站点可支持同时与两个 RR 建立 IBGP 邻居，两个 RR 互为备份。一个租户下可部署多个 RR，所有 RR 之间在控制面是 Full-Mesh 连接。
- **GW**：在不同业务场景有不同角色名称，如与传统站点连接的 IWG（Interworking Gateway）、与云连接的 Cloud GW；也可扩展互联组建 POP（Point of Presence）网络，称为 POP GW。

华为 CPE 设备示例：NetEngine AR 系列路由器（如 AR6300/AR6280、AR6100、AR650、AR610 等）可被用作 EDGE、RR、GW。

### 华为 SD-WAN 主要功能

- **零配置开局**：通过多种零配置开局方式，使得 EDGE 能快速注册到 iMaster NCE 控制器。
- **转控分离，灵活组网**：EDGE 与控制器之间通过 Netconf 建立管理通道，控制器下发配置建立 IP Overlay 隧道。
- **应用体验，业务可控可视**：采用业务感知技术识别应用；采用 TCP FPM、IP FPM 实现基于应用的质量检测；采用 IP FPM 实现链路质量检测；采用智能策略路由 SPR 实现基于应用质量进行智能链路切换。
- **完整安全防御体系**：支持 IPsec、MPLS 多种 VPN 技术提供端到端防护，支持防火墙功能，提供硬件、管道、应用多层级全方位安全保障。

#### ZTP

ZTP（Zero Touch Provisioning，零配置开局）优点：

- 由控制器统一配置部署，提高开局效率，适用于大规模网络站点开局。
- 通过 URL 链接或 DHCP Option 参数实现开局配置，简化流程，一键完成开局部署。
- 开局后设备自动注册到控制器，降低控制器使用难度。

U 盘开局、邮件开局与 DHCP 开局的开局文件均可通过 iMaster NCE 控制器生成。

#### 三通道

- **管理通道**：iMaster NCE 通过 Netconf 与所有设备建立管理通道连接，进行整网网元管理和业务编排。
- **控制通道**：EDGE 与 RR 之间建立控制通道；引入集中控制机制，RR 负责分支站点间业务路由的集中控制和分发；使用增强的 BGP EVPN 协议，实现租户 VPN 路由和下一跳信息分离承载和 IPsec 隧道的 SA 协商功能。
- **数据通道**：EDGE 之间建立数据通道。

管理通道下发配置主要提供：EDGE 统一管理、业务自动下发和 Overlay 网络统一控制；应用可视与自动调优；网络安全业务等。

#### TNP

TNP（Transport Network Port）：CPE 接入 Transport Network 的 WAN 接口，关键信息包括：Site ID、EDGE Router ID、Transport network-ID、public IP、private IP、Tunnel Encapsulation 等。

#### 数据通道

华为 SD-WAN 主要通过 GRE 或 GRE Over IPsec 建立数据通道。设备基于 BGP EVPN 传递的 TNP 与 IPsec SA 建立 GRE 或 GRE Over IPsec 隧道；基于 BGP EVPN 传递的业务路由转发数据。
