---
doc_id: "hcip-security-v4.0-training-05"
title: "IPSec VPN应用场景与高可靠性"
book: "HCIP-Security-V4.0-Training"
book_title: "HCIP-Security V4.0 培训教材"
track: "security"
level: "hcip"
series: "security-v4"
doc_type: "training"
source_pdf: "HCIP-Security V4.0 培训教材.pdf"
seq: 5
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# IPSec VPN应用场景与高可靠性

## IPSec模板方式配置

采用点到点IPSec VPN传统配置方式时要求指定对端IP地址，很多场景下建立IPSec VPN的一端（比如较小的分支机构、门店）并无公网IP或固定IP。当分支机构众多时，总部需要为每个分支机构单独维护一份配置，总部的配置量无疑将会非常臃肿。此时可以采用IPSec模板方式配置，可以有效的解决以上问题。

IPSec模板：不限制对端IP地址，可以严格指定对端IP地址（单个IP），可以宽泛指定对端IP地址（IP地址段），也可以干脆不指定对端IP（意味着对端IP可以是任意IP）。

本文仅介绍IPSec配置流程，安全策略相关配置请参考配置手册。

配置思路- 模板方式：

- Security ACL Rule：定义需要保护的数据流
- Ike Proposal：配置IKE安全提议（authentication-method、authentication-algorithm、encryption-algorithm、dh）
- Ike Peer：配置IKE对等体（version、exchange-mode、pre-shared-key）
- IPSec Proposal：配置IPSec安全提议（encapsulation-mode、AH or ESP、parameter）
- IPSec policy-template X：配置模板方式的IPSec安全策略（关联Security ACL、IPSec Proposal、Ike Peer）
- IPSec policy Y：配置基本参数，绑定策略和模板并调用（IPSec policy Y seq isakmp template X）
- interface：接口下调用IPSec policy Y

关键配置：

选择“网络> IPSec > IPSec”，单击“新建”，建立模板方式（即点到多点场景）的IPSec策略。

## GRE over IPSec应用场景

IPSec VPN本端设备无法感知对端有几个设备，本端共用一个IPSec SA。报文封装中没有对端设备的下一跳，所以无法传输组播、广播和非IP报文，比如OSPF协议，导致分支与总部的内部网络之间无法使用OSPF路由。

GRE over IPSec可利用GRE和IPSec的优势，通过GRE将组播、广播和非IP报文封装成普通的IP报文，通过IPSec为封装后的IP报文提供安全地通信，进而可以提供在总部和分支之间安全地传送广播、组播的业务。

> （原图：GRE over IPSec组网示意图，展示分支与总部通过防火墙A和防火墙B建立GRE over IPSec隧道，传输单播、广播、组播、非IP报文）

GRE over IPSec报文封装过程：

- GRE协议能够支持非IP单播报文，比如IPX报文、组播报文等，原始报文被封装在GRE隧道中。
- GRE隧道封装包被封装在IPSec隧道封装包中。

当网关之间采用GRE over IPSec连接时，先进行GRE封装，再进行IPSec封装。GRE over IPSec使用的封装模式可以为隧道模式也可以为传输模式。采用AH协议的GRE over IPSec报文封装过程如下：

> （原图：GRE over IPSec报文封装过程示意图，展示原始报文、GRE封装、IPSec封装（传输模式与隧道模式）的报文格式）

GRE over IPSec的优势：

| 特性 | GRE是否支持 | IPSec是否支持 | GRE over IPSec是否支持 |
| --- | --- | --- | --- |
| 支持组播 | Y | N | Y |
| 对动态路由协议的支持 | Y | N | Y |
| 对丰富的网络层协议的支持 | Y | 支持有限 | Y |
| 机密性 | N | Y | Y |
| 完整性 | N | Y | Y |
| 数据源验证 | N | Y | Y |

- 组播：组播类型的报文；
- 动态路由协议：如OSPF、IS-IS等，动态路由协议报文有些是组播或者广播报文；
- 丰富的网络层协议：支持网络层协议，IP协议、IPX协议、ARP协议和ICMP协议等；
- 机密性：支持对报文进行加密；
- 完整性：支持对收到的报文进行校验，检查报文是否完整，是否被改动；
- 数据源认证：对收到数据的源进行认证。

GRE over IPSec的配置思路：

- Security ACL Rule：定义需要保护的数据流
- Ike Proposal：配置IKE安全提议（authentication-method、authentication-algorithm、encryption-algorithm、dh）
- Ike Peer：配置IKE对等体（version、exchange-mode、pre-shared-key、Remote-address）
- IPSec Proposal：配置IPSec安全提议（encapsulation-mode、AH or ESP、parameter）
- IPSec policy X seq isakmp：配置ISAKMP模式的IPSec安全策略（关联Security ACL、IPSec Proposal、Ike Peer）
- interface：接口下调用IPSec policy X
- interface tunnel 1：配置GRE隧道（tunnel-protocol gre、ip address ip、source ip、destination ip）

以ISAKMP模式的IPSec VPN为例，按照GRE和IPSec点到点配置思路配置即可。

## IPSec VPN证书认证场景

IPSec VPN点到多点场景中，进行身份认证时如果使用预共享密钥方式，总部和每个分部之间形成的对等体都要配置预共享密钥。如果所有对等体都使用同一个密钥，存在安全风险；而每个对等体都使用不同的密钥，又不便于管理和维护。

为了解决上述问题，可以使用证书认证。IKE通过借用了PKI中的证书机制来进行对等体的身份认证，不必再为每个对等体配置单独的密钥，降低管理成本。

> （原图：证书认证组网示意图，总部、分支1、分支2与CA的组网关系）

使用证书进行身份认证流程如下：

- 防火墙生成公钥和私钥对并将公钥和实体信息一同发送给CA；
- CA通过防火墙发送的信息生成CA证书和防火墙的证书，再由防火墙通过在线或者离线的方式进行申请获得；
- 防火墙通过ISAKMP消息交换证书；
- 防火墙使用CA证书校验对方的身份。

使用证书进行身份认证需要经历两个步骤：

- 证书导入：使用设备的密钥及必要信息到CA颁发证书，并将成对的证书导入到设备；
- 证书认证：IPSec身份认证时，各自将导入的本地证书发送给对端验证身份。

> （原图：证书导入与认证流程示意图，防火墙A和防火墙B分别向CA导出公钥和其他信息，CA生成证书，双方通过IKE ISAKMP消息交换证书信息，并验证对端证书）

### 防火墙申请本地证书

配置RSA密钥对，申请本地证书时，需先配置RSA密钥对生成公钥和私钥。公钥由PKI实体发送给CA，可以被对端用来加密明文；私钥由PKI实体保留，可以被用来数字签名和解密对端发送过来的密文。

完成配置后，可执行命令display pki cert-req查看证书请求文件的内容。

本地证书注册成功后，可以通过带外方式下载本地证书。下载后，可以通过文件传输协议导入到设备的存储介质中。

关键配置– 防火墙申请本地证书：

- 创建公私密钥对。创建一个2048位的RSA密钥对rsa，并设置为可以从设备上导出。
- 配置PKI实体信息。
- 配置为PKI实体离线申请本地证书。申请本地证书时，申请文件中的IP地址需要配置为防火墙建立IPSec隧道时所使用的IP地址。

```cli
[FW] pki rsa local-key-pair create rsakey exportable
[FW] pki entity user01
[FW-pki-entity-user01] common-name devicea
[FW-pki-entity-user01] country cn
[FW-pki-entity-user01] ip-address 10.1.61.11
[FW-pki-entity-user01] state Hangzhou
[FW-pki-entity-user01] organization-unit Training
[FW-pki-entity-user01] quit
[FW] pki realm abc
[FW-pki-realm-abc] entity user01
[FW-pki-realm-abc] rsa local-key-pair rsakey
[FW-pki-realm-abc] quit
[FW] pki enroll-certificate realm abc pkcs10 filename cer_req
```

### 导入本地及CA证书

证书申请好之后，在“对象> 证书> 本地证书”中导入本地证书；在“对象> 证书> CA证书”中导入CA认证。

如果此处选择“RSA数字信封”模式，除了导入本端证书，还需要导入对端证书，此证书中的部分信息将会在隧道建立过程中发给对端，供双方验证对端的合法性。

### 采用RSA签名认证

选择“网络> IPSec > IPSec”，在“IPSec策略列表”下单击“新建”。

按如下参数配置“基本配置”：

- 认证方式选择“RSA签名”；
- 选择已导入的证书进行验证，本端ID和对端ID需要与申请证书时填写的一致。

## IPSec VPN NAT穿越场景

### IPSec VPN在NAT场景中存在的问题

采用AH安全协议完全不支持NAT穿越场景，ESP安全协议受限于端口，需要用额外端口实现。

默认情况下，IPSec VPN传输数据时外层IP头部之上为ESP header或者AH header，传输模式和隧道模式在传输路径中存在源NAT设备时都会遇到问题。

下图以隧道模式为例介绍：

> （原图：AH与ESP在NAT场景下的问题示意图。AH协议认证范围包含外层IP头部，SNAT后校验失败；ESP协议加密原始报文，但ESP Header无字段支持源端口转换，NAPT无法转换）

- AH协议：网关2收到之后验证AH校验内容，因为外层IP头部中的IP地址已经发生变化，校验失败，将该报文丢弃，通信失败。
- ESP协议：ESP校验范围不包括外层IP头部，因此SNAT不会影响校验结果，但是ESP对原始报文进行加密，并且自身的ESP Header中并无字段支持进行源端口转换，因此NAPT不支持对IP+ESP封装格式的报文进行转换。

### NAT穿越功能简介

为解决上述问题，必须在建立IPSec隧道的两个网关上开启NAT穿越功能（NAT Traversal）。

开启NAT穿越之后，当检测到（IKE协商过程中进行检测）两台网关中间存在NAT设备，ESP报文会被封装在一个UDP头部中，源目端口号4500，以此支持NAT转换。

> （原图：NAT穿越报文封装示意图，ESP报文添加UDP头部（SIP：4500，DIP：4500），经过SNAT（NAPT）后UDP源端口改变）

添加了UDP头部之后，经过SNAT（NAPT）会改变UDP头部中的源端口。

### NAT穿越检测原理

开启NAT穿越时，IKEv1协商第一阶段的前两个消息会发送标识NAT穿越（NAT Traversal，简称NAT-T）能力的Vendor ID载荷（主模式和野蛮模式都是）。用于检查通信双方是否支持NAT-T，当双方都在各自的消息中包含了该载荷时，才会进行相关的NAT-T协商。

主模式消息3和消息4中发送NAT-D（NAT Discovery）载荷。NAT-D载荷用于探测两个要建立IPSec隧道的网关之间是否存在NAT设备以及NAT设备的位置。

- Remote HASH：指将发送报文中的目的IP地址和端口号进行HASH运算后的数值。
- Local HASH：指将发送报文中的源IP地址和端口号进行HASH运算后的数值。
- 通过对比Remote HASH和Local HASH值，可以判断网关之间是否存在NAT设备以及NAT网关的位置。

发现NAT设备后，后续ISAKMP消息（主模式从消息5开始）的端口号转换为4500。

以IKEv1主模式为例，介绍NAT穿越检测原理：

> （原图：NAT穿越检测原理示意图，网关1与网关2之间通过NAT设备交互ISAKMP消息，消息1和2确认双方是否支持NAT-T功能，消息3和4判断通信过程是否存在NAT设备，若存在NAT设备，通信源目端口号从500转换为4500）

### NAT穿越会话保活机制

NAT Keepalive报文格式非常简单，在UDP头部之后为两个十六进制F，用于刷新NAT设备会话表项。

华为防火墙检测出IPSec VPN处于NAT穿越场景后，NAT设备内侧设备（发起方网关1）会定期发送NAT Keepalive报文，保证中间NAT设备上的源NAT会话不老化。

如图所示为NAPT场景，网关1处在NAT设备之后。若网关1未主动发起访问，则NAT设备不存在NAT会话表项，此时网关2无法访问网关1。

为解决以上问题，需要网关1开启NAT会话保活功能。开启后，网关1会定期发送NAT Keepalive报文，使NAT设备上产生并维持NAT表项，使得网关2可以主动访问网关1。

> （原图：NAT穿越会话保活机制示意图，网关1定期发送NAT Keepalive报文，NAT设备产生并持续刷新NAT表项，使网关2可以主动访问网关1）

### NAT穿越场景(1)

该场景中，NAT设备位于分部网络之外，分部网关1出接口的私网IP地址X，经过NAT设备转换后变为公网IP地址Y。由于总部无从获知经过NAT设备转换后的分部公网IP地址，也就无法在总部网关2上明确指定对端的公网地址。因此，总部网关2必须使用模板方式来配置IPSec，同时总部和分布的网关都要开启NAT穿越功能。

总部既然使用了模板方式，那就无法主动访问分部，只能由分部主动向总部发起ISAKMP协商。

> （原图：NAT穿越场景(1)组网示意图，分部网关1（IP：X）经NAT设备（SNAT/NAPT）转换后变为IP：Y，与总部网关2（IP：Z）建立IPSec隧道，开启NAT Traversal，使用模板方式建立IPSec VPN，只能由分部主动发起ISAKMP协商）

该场景中，分部网关为防火墙，NAT设备的公网地址对总部不可见，所以需要使用模板方式建立IPSec，此时虽然分部与总部之间存在NAT设备，但是防火墙的安全策略相关配置与非NAT穿越场景一致。

网关1与网关2的安全区域划分规则，连接内部网络的区域为trust区域，连接外部网络的区域为untrust区域，设备本身地址为local区域，安全策略配置如下：

- 网关1安全策略：
  - local -> untrust，网关1的IP地址：X -> 网关2的IP地址：Z；
  - trust -> untrust，分部内网地址-> 总部内网地址；
  - untrust -> local，网关2的IP地址：Z -> 网关1的IP地址：X。
- 网关2安全策略：
  - local -> untrust，网关2的IP地址：Z -> any；
  - trust -> untrust，总部内网地址-> 分部内网地址；
  - untrust -> local，any -> 网关2的IP地址：Z。

### NAT穿越场景(2)

该场景中，NAT设备位于分部网络之外，分部网关1出接口的私网IP地址X，经过NAT设备转换后变为公网IP地址Y。NAT转换设备为分部自己管理设备，并且公网IP地址固定，此时转换后的公网地址可知。因此，总部可以使用模板方式或者手动指定对等体的方式配置IPSec VPN。

由于NAT设备只进行源地址转换，所以依旧只能由分部主动发起ISAKMP协商。

> （原图：NAT穿越场景(2)组网示意图，NAT设备为分部的管理设备，分部网关1（IP：X）经NAT设备（SNAT/NAPT）转换后变为IP：Y，与总部网关2（IP：Z）建立IPSec隧道，开启NAT Traversal，使用模板方式、手动指定对等体方式均可，只能由分部主动发起ISAKMP协商）

该场景中，分部网关为防火墙，NAT设备的公网地址固定，总部对NAT设备的公网地址可知，所以可以使用模板方式或者手动指定对等体的方式配置IPSec，此时由于分部与总部之间存在NAT设备，所以防火墙的安全策略相关配置与非NAT穿越场景有差别。

网关1与网关2的安全区域划分规则，连接内部网络的区域为trust区域，连接外部网络的区域为untrust区域，设备本身地址为local区域，安全策略配置如下：

- 网关1安全策略：
  - local -> untrust，网关1的IP：X -> 网关2的IP：Z；
  - trust -> untrust，分部内网地址-> 总部内网地址；
  - untrust -> local，网关2的IP：Z -> 网关1的IP：X。
- 网关2安全策略：
  - local -> untrust，网关2的IP：Z -> NAT设备的IP：Y；
  - trust -> untrust，总部内网地址-> 分部内网地址；
  - untrust -> local，NAT设备的IP：Y -> 网关2的IP：Z。

### NAT穿越场景(3)

该场景中，NAT设备为分部管理设备，提供NAT Server功能，映射网关的接口地址，总部上使用手动指定对等体方式配置IPSec，此时可以实现总部主动发起ISAKMP协商以及流量访问。

> （原图：NAT穿越场景(3)组网示意图，NAT设备（SNAT/NAPT + NAT Server）将网关1的IP：X映射到公网IP：Y，总部网关2（IP：Z）与分部网关1建立IPSec隧道，开启NAT Traversal，使用模板方式、手动指定对等体方式均可，总部、分部都可以同时发起ISAKMP协商）

该场景中，分部网关为防火墙，NAT设备的公网地址固定，总部对NAT设备的公网地址可知，所以可以使用模板方式或者手动指定对等体的方式配置IPSec；由于NAT设备配置了NAT Server将网关1的IP：X映射到公网，所以此时总部也可以主动向分部发起ISAKMP协商。

网关1与网关2的安全区域划分规则，连接内部网络的区域为trust区域，连接外部网络的区域为untrust区域，设备本身地址为local区域，安全策略配置如下：

- 网关1安全策略：
  - local -> untrust，网关1的IP：X -> 网关2的IP：Z；
  - trust -> untrust，分部内网地址-> 总部内网地址；
  - untrust -> local，网关2的IP：Z -> 网关1的IP：X。
- 网关2安全策略：
  - local -> untrust，网关2的IP：Z -> NAT设备的IP：Y；
  - trust -> untrust，总部内网地址-> 分部内网地址；
  - untrust -> local，NAT设备的IP：Y -> 网关2的IP：Z。

### NAT穿越场景关键配置

开启NAT穿越功能命令：

```cli
<sysname> system-view
[sysname] ike Peer Peer1
[sysname-ike-Peer-Peer1] nat traversal
```

配置IPSec NAT穿越的UDP端口号（默认端口号为UDP 4500），可以执行命令ipsec nat-traversal source-port进行配置：

```cli
<sysname> system-view
[sysname] ipsec nat-traversal source-port 4510
```

当对等体间存在NAT网关，为防止NAT表项老化，NAT网关内网侧的设备会以一定的时间间隔向对端发送NAT Keepalive报文，以维持NAT会话的存活：

```cli
<sysname> system-view
[sysname] ike nat-keepalive-timer interval 30
```

配置NAT穿越功能时，使用的IPSec安全提议ipsec proposal只能选择ESP安全协议：

```cli
<sysname> system-view
[sysname] ipsec proposal newprop1
[sysname-ipsec-proposal-newprop1] transform esp
```

## IPSec VPN高可靠性

### 双机热备

防火墙支持主备方式和负载分担方式两种双机热备，需根据实际组网情况进行选择。上文主要介绍的是主备方式，负载分担方式可自行参考华为防火墙产品手册进行学习。

总部分支场景下，防火墙A和防火墙B对外配置VRRP备份组1，并在VRRP备份组1和分支网关防火墙C的物理接口之间建立IPSec隧道。当主用防火墙A物理接口、链路或主机故障时，流量被引导到备用防火墙B进行IPSec和转发处理。这种情况下，原有的IPSec隧道并不会被拆除，切换速度更具优势。

> （原图：IPSec双机热备组网示意图，总部防火墙A和防火墙B配置VRRP备份组1和备份组2，与分支防火墙C建立IPSec Tunnel）

配置思路：

- 完成防火墙基本配置，比如接口添加安全区域和相关策略等；
- 配置防火墙双机热备，采用主备方式；
- 配置IPSec基本参数，包括对端和本段信息、选择感兴趣数据流和安全提议等；
- 配置路由保证互联互通。

关键配置(1)：假设两台防火墙的心跳接口为GE0/0/3，上下行接口为GE0/0/2、GE0/0/4，双机热备关键配置如下：

> （原图：双机热备关键配置(1)界面示意图）

关键配置(2)：假设两台防火墙连接Internet接口为GE0/0/2，这两个接口组成VRRP冗余备份组2，总部IPSec关键配置如下：

> （原图：双机热备关键配置(2)界面示意图）

### 链路冗余备份

#### IPSec主备链路冗余备份

为提高网络可靠性，企业分支通过两条链路与企业总部建立IPSec连接，形成两条主备链路。当主链路故障时，启用备份链路建立IPSec隧道，旧的IPSec隧道被拆除，流量切换也随之完成。

如下图所示，防火墙A通过两条主备链路连接防火墙B，正常情况下，流量通过由主链路和Tunnel1接口建立的IPSec隧道传输；当主链路故障时，防火墙A感知变化，采用Tunnel2接口与防火墙B的备份链路建立IPSec隧道。

> （原图：IPSec主备链路冗余备份组网示意图，防火墙A通过主链路和备链路连接防火墙B，Tunnel1接口对应主链路，Tunnel2接口对应备链路）

在防火墙A上创建两个Tunnel接口，借用同一个物理接口的IP地址，分别应用不同的IPSec安全策略，在防火墙B的两个物理接口上也分别应用不同的IPSec安全策略，这样就可以创建主备两条IPSec隧道。

关键配置(1)：总部防火墙的主用出口为GE0/0/1，备用出口为GE0/0/2，需要创建两套IPSec安全策略，分别调用在两个出接口中：

```cli
[FW_B] ipsec policy map1 10 isakmp
[FW_B-ipsec-policy-isakmp-map1-10] security acl 3000
[FW_B-ipsec-policy-isakmp-map1-10] proposal tran1
[FW_B-ipsec-policy-isakmp-map1-10] ike-Peer b
[FW_B-ipsec-policy-isakmp-map1-10] quit
[FW_B] ipsec policy map2 10 isakmp
[FW_B-ipsec-policy-isakmp-map1-10] security acl 3000
[FW_B-ipsec-policy-isakmp-map1-10] proposal tran1
[FW_B-ipsec-policy-isakmp-map1-10] ike-Peer b
[FW_B-ipsec-policy-isakmp-map1-10] quit
[FW_B] interface GigabitEthernet 0/0/1
[FW_B-GigabitEthernet0/0/1] ipsec policy map1
[FW_B-GigabitEthernet0/0/1] quit
[FW_B] interface GigabitEthernet 0/0/2
[FW_B-GigabitEthernet0/0/2] ipsec policy map2
[FW_B-GigabitEthernet0/0/2] quit
```

关键配置(2)：分支防火墙上创建两个Tunnel接口，借用同一个物理接口的IP地址，分别应用不同的IPSec安全策略：

```cli
[FW_A] interface tunnel 1
[FW_A-Tunnel1] ip address unnumbered interface GigabitEthernet 0/0/1
[FW_A-Tunnel1] tunnel-protocol ipsec
[FW_A-Tunnel1] quit
[FW_A] interface tunnel 2
[FW_A-Tunnel1] ip address unnumbered interface GigabitEthernet 0/0/1
[FW_A-Tunnel1] tunnel-protocol ipsec
[FW_A-Tunnel1] quit
[FW_A] interface tunnel 1
[FW_A-Tunnel1] ipsec policy map1
[FW_A-Tunnel1] quit
[FW_A] interface tunnel 2
[FW_A-Tunnel2] ipsec policy map2
[FW_A-Tunnel2] quit
```

#### IPSec多链路冗余备份

为提高网络可靠性，企业分支通过两条或多条链路与企业总部建立IPSec连接。当主物理链路失效时，其路由变为不可达，流量切换到备用链路。IPSec隧道不需要进行重协商，可快速完成流量切换。

如下图所示，防火墙A通过两条主备链路连接防火墙B，系统在防火墙A的物理接口与防火墙B的Tunnel接口之间建立一个IPSec隧道，流量通过Tunnel接口进行IPSec处理，然后通过路由表选择物理接口发送。当主物理链路失效时，其路由变为不可达，流量自然切换到备用链路。

> （原图：IPSec多链路冗余备份组网示意图，防火墙A通过主链路和备链路连接防火墙B，通过Tunnel接口建立IPSec隧道）

通过Tunnel接口进行链路冗余备份可以实现多条链路的冗余备份，而且与主备链路冗余备份相比，配置更简单，流量切换速度更快。

关键配置：在总部设备上创建隧道接口与分部建立IPSec VPN，当主链路故障时，主链路路由失效，流量切换到备链路传输，并且主备链路切换时，保证IPSec流量不中断。配置到分部的静态路由，此处假设分部的地址为10.4.0.0/24：

```cli
[FW_B] interface tunnel 0
[FW_B-tunnel0] tunnel-protocol ipsec
[FW_B-tunnel0] ip address 1.1.0.2 24
[FW_B-tunnel0] ipsec policy map1
[FW_B-tunnel0] quit
[FW_B] ip route-static 10.4.0.0 255.255.255.0 tunnel 0
```

### 智能选路

防火墙作为分支的网关时，可以通过配置IPSec智能选路功能实现多条IPSec隧道动态切换。按照链路切换机制的不同可以分为两种不同场景：基于链路质量探测结果和基于路由状态变化。

- 基于链路质量探测结果：防火墙实时检测当前IPSec隧道的时延或丢包率，在时延或丢包率高于设定的阈值时，动态切换到备用链路上重新建立IPSec隧道。
- 基于路由状态变化：根据路由状态建立IPSec隧道，当链路出现故障后，路由不可达，基于路由变化自动将IPSec隧道切换到备链路。

> （原图：智能选路两种场景示意图。上图为基于链路质量探测结果切换，分支防火墙B与总部防火墙A之间通过Link1和Link2建立IPSec隧道；下图为基于路由状态变化切换，分支防火墙B与总部防火墙A之间运行动态路由协议（OSPF），通过Link1和Link2建立IPSec隧道）

基于链路质量探测结果切换：在防火墙B上配置IPSec智能选路功能后，防火墙B会选择一条链路建立IPSec隧道（Link1）。而后防火墙B通过发送ICMP报文检测IPSec隧道的时延或丢包率。当隧道的时延或丢包率高于设定的阈值时，防火墙B会拆除当前的IPSec隧道，并选择另一条链路建立IPSec隧道（Link2）。这样，就能确保分支和总部之间始终使用满足质量要求的IPSec隧道通信。

基于路由状态变化切换：从分支网关防火墙B到总部网关防火墙A之间有两条链路Link1和Link2，防火墙B与Internet之间运行动态路由协议（此处以OSPF为例）。在防火墙B上配置IPSec智能选路功能，可以实现分支和总部之间多条IPSec隧道动态切换。Link1和Link2链路状态都正常的情况下，防火墙B会选择一条链路建立IPSec隧道，例如选择Link1链路。当Link1链路出现故障时，通过Link1到达防火墙A的路由就会消失，于是防火墙B会根路由变化自动将IPSec隧道切换到Link2上。

## IPSec VPN故障排除

### IPSec诊断

#### Web诊断

在使用IPSec时，如出现故障，可通过以下方式来对故障进行诊断：

- 选择“监控> 诊断中心”，单击“IPSec诊断”。
- 配置IPSec诊断：诊断对象、IPSec策略名称、本端接口及策略名称。单击“诊断”，即可得到诊断信息。

#### CLI诊断

查看IPSec处理报文的统计信息，如受安全保护的进出报文统计信息、加解密报文统计信息、被丢弃的受安全保护的详细统计信息以及IKE协商相关的报文统计信息等，这有助于IPSec故障诊断和维护：

```cli
<sysname> display ipsec statistics
```

display ipsec statistics命令输出信息描述：

- IPSec statistics information：IPSec报文统计信息。
- Number of IPSec tunnels：IPSec隧道数目。
- Number of standby IPSec tunnels：业务板备份时，备用IPSec隧道数目。
- the security packet statistics：受安全保护的报文统计信息。
  - input/output security packets：受安全保护的进出报文数。
  - input/output security bytes：受安全保护的进出字节数。
  - input/output dropped security packets：被丢弃的受安全保护的进出报文数。
- the encrypt packet statistics：加密报文的统计信息。
- the decrypt packet statistics：解密报文的统计信息。
- dropped security packet detail：被丢弃的受安全保护报文的详细统计信息。
- negotiate about packet statistics：IKE协商相关的报文统计信息。

查看IKE SA协商结果：

```cli
<sysname> display ike sa
```

display ike sa命令可以查看到的信息包括：安全联盟的连接索引、安全联盟的对端IP地址、VPN实例名称、SA所属阶段、对端ID类型、对端ID、此安全联盟的状态。

查看IPSec SA的配置信息：

```cli
<sysname> display ipsec sa
```

### IPSec VPN主要故障

从故障现象的维度进行划分，IPSec故障可分为如下两大类：

- IPSec隧道建立失败（隧道协商失败）。
- IPSec隧道建立成功后业务异常（加密数据流不通）。

IPSec故障分析可以按照故障出现的先后顺序从以下几个现象入手：

- 配置阶段：IPSec配置界面不可见。
- 业务触发阶段：没有数据流触发IKE协商。
- IKE协商阶段：IKE协商不成功（IKE SA、IPSec SA协商不成功）。
- 数据传输阶段：IKE协商成功，但VPN业务异常（不通或质量不好）。

其中IKE协商不成功是IPSec故障的核心问题，可以结合IKE协商过程进行深入分析；其它故障仅表现为IPSec业务故障，多为防火墙基本特性的错误配置，如license、接口、链路、路由、安全区域、NAT等，需要结合具体场景来处理。

### IPSec VPN故障处理思路

#### 没有数据流触发IKE协商

IKE没有建立成功，首先需要检查是否有数据流触发IKE协商，可能原因和检查措施如下：

- 主机到网关路由不可达
- 缺少到IKE对等体私网的路由或路由不正确
- 域间安全策略配置错误
- IPSec策略没有正确应用到接口上
- （若兼作NAT网关）NAT策略干扰
- Security ACL与实际待保护数据流不匹配

检查措施：

- 检查VPN数据流是否匹配了Server map表和反向Server map表
- 检查VPN数据流是否匹配了目的NAT策略
- 检查VPN数据流是否匹配了源NAT策略

#### IKE SA协商不成功

有数据流触发IKE协商，但是IKE协商失败，可能原因如下：

- 运营商对IKE协商报文进行了限制
- 到IKE对等体的路由不可达
- 本端的“对端网关”和对端的“本地地址”不匹配
- 两端IKE Peer的其它参数不匹配
- 两端IKE proposal配置不匹配
- IKE版本号不一致
- （IKEv1）协商模式不一致
- 身份ID配置不匹配
- 其它身份认证参数不正确
- 加密算法不一致
- 身份认证方法及算法不一致
- （IKEv2）完整性认证算法不一致
- DH组不一致

#### IPSec SA协商不成功

IKE协商成功后，IPSec SA无法建立，可能原因如下：

- (IKEv1)两端ACL不是镜像或发起方范围比响应方范围小；(IKEv2)两端ACL没有交集
- 两端IPSec proposal配置不一致
- (IKEv1)PFS配置不一致
- 安全协议不一致
- 加密算法不一致
- 验证算法不一致
- 封装模式不一致

### 案例一：local-address与remote-address不匹配

#### 故障现象

在两台防火墙之间建立IPSec隧道。组网如图所示，在修改参数之前，隧道能够建立成功。当在防火墙B的公网接口增加了sub地址并修改了IPSec配置后，发现隧道建立不成功。经检查，两端IPSec和IKE参数配置均正确。路由、接口、安全策略等配置也正确。

> （原图：案例一组网示意图，防火墙A（GE0/0/3：10.1.1.1/24，GE0/0/1：1.1.1.2/24）与防火墙B（GE0/0/1：2.2.2.2/24，sub地址2.2.2.3/24，GE0/0/3：10.2.1.1/24）建立IPSec隧道，PC1（10.1.1.2/24）与PC2（10.2.1.2/24）通信）

有时为了使路由设备的一个接口能够与多个子网相连，可以在一个接口上配置多个IP地址，其中一个为主IP地址，其余为从IP地址。Sub地址就是接口的从IP地址。

#### 故障分析

主要从IKE对等体间路由、IKE Peer和IKE Proposal等方面进行分析。故障由防火墙B的公网接口增加sub地址引起，猜测可能是sub地址触发了IPSec协商，使IKE协商失败导致。

检查防火墙A上IKE SA是否存在，执行display ike sa命令，发现sa number已经变成0：

```cli
<FW_A> display ike sa
current ike sa number: 0
```

检查防火墙A上IKE对等体的配置信息，执行display ike peer命令，防火墙A的remote address为2.2.2.2：

```cli
[FW_A] display ike peer brief
current ike Peer number: 1
-----------------------------------------------------------------------------------
Peer Name    Version  Exchange-mode  Proposal  Id-type  RemoteAddr
-----------------------------------------------------------------------------------
b                  v1v2       N/A                 10            IP         2.2.2.2
```

在防火墙B上查询配置发现，防火墙A的remote address和防火墙B的local address不一致：

```cli
[FW_B-ipsec-policy-isakmp-map1-10]display this
ipsec policy map1 10 isakmp
 security acl 3000
 ike-Peer a
 proposal tran1
 local-address 2.2.2.3
```

#### 故障处理

已经得知是本端的“对端网关”和对端的“本地地址”不匹配导致IKE协商失败，故只要在防火墙A上修改IKE对等体的remote address即可：

```cli
[FW_A] ike Peer b
[FW_A-ike-Peer-b] remote-address 2.2.2.3
[FW_A-ike-Peer-b] quit
[FW_A] display ike sa
current ike sa number: 2
------------------------------------------------------------
conn-id    Peer                    flag          phase   vpn
------------------------------------------------------------
40003      2.2.2.3                RD|ST         v2:2  public
3             2.2.2.3                RD|ST         v2:1  public
```

总结：在配置IPSec安全策略时，local-address命令为可选配置。当本端发起IPSec隧道协商的IP地址与实际应用IPSec策略的接口IP地址不同时，需要配置local-address为本端发起协商的IP地址，且该地址需要和对端使用remote-address命令设置的目的地址一致。

两端私
