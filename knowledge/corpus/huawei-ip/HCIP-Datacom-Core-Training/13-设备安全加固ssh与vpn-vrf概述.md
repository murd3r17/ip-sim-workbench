---
doc_id: "hcip-datacom-core-training-13"
title: "设备安全加固、SSH 与 VPN/VRF 概述"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 13
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# 设备安全加固、SSH 与 VPN/VRF 概述

## URPF（单播逆向路径转发）

IP 网络的开放性决定了，只要路由可达，任何人都可以对目标主机进行访问或者攻击。对于某一个主机而言，访问它的客户端报文历经的路径通常是固定的，尤其是在网络边缘，这种路径的固定特性表现得更加明显。

URPF（Unicast Reverse Path Forwarding，单播逆向路径转发）分为严格模式、松散模式以及允许匹配缺省路由的方式。其原理是：当设备转发 IP 报文时，检查数据报文的源 IP 地址是否合法；检查原理是根据数据包的源 IP 地址查路由表。

- **严格模式**：如果报文能匹配明细路由，并且入接口跟匹配路由的出接口一致，则允许报文上送，否则丢弃报文。
- **松散模式**：如果报文匹配上明细路由，则允许报文上送，否则丢弃报文，不检查接口是否匹配。默认情况下，会认为缺省路由不存在，不会去匹配缺省路由，只有进行了配置时，才会去匹配缺省路由。
- **允许匹配缺省路由的模式**：必须和严格模式一起配置；报文匹配明细路由或者缺省路由，并且报文入接口跟匹配路由的出接口一致才上送，否则丢弃。不支持缺省路由与松散模式一起配置，因为这样无法达到防攻击的效果。松散模式和严格模式互斥，只能配置一种模式。

## 本机防攻击

在网络中，存在着大量针对 CPU 的恶意攻击报文以及需要正常上送 CPU 的各类报文。针对 CPU 的恶意攻击报文会导致 CPU 长时间繁忙地处理攻击报文，从而引发其他业务的断续甚至系统的中断；大量正常的报文也会导致 CPU 占用率过高、性能下降，从而影响正常业务。

为了保护 CPU，保证 CPU 对正常业务的处理和响应，设备提供了本机防攻击功能。本机防攻击针对的是上送 CPU 的报文，主要用于保护设备自身安全，保证已有业务在发生攻击时的正常运转，避免设备遭受攻击时各业务的相互影响。

本机防攻击包括 **CPU 防攻击** 和 **攻击溯源** 两部分：

- **CPU 防攻击**：针对上送 CPU 的报文进行限制和约束，使单位时间内上送 CPU 报文的数量限制在一定范围之内，从而保护 CPU 的安全，保证 CPU 对业务的正常处理。
- **攻击溯源**：针对 DoS（Denial of Service，拒绝服务）攻击进行防御。设备通过对上送 CPU 的报文进行分析统计，然后对统计的报文设置一定的阈值，将超过阈值的报文判定为攻击报文，再根据报文信息找出攻击源用户或者攻击源接口，最后通过日志、告警等方式提醒管理员，或直接丢弃攻击报文以对攻击源进行惩罚。

### CPU 防攻击多级安全机制

设备通过以下策略实现对设备的分级保护：

1. **第一级**：通过黑名单来过滤上送 CPU 的非法报文。
2. **第二级**：CPCAR（Control Plane Committed Access Rate）。对上送 CPU 的报文按照协议类型进行速率限制，保证每种协议上送 CPU 的报文不会过多。
3. **第三级**：对上送 CPU 的报文，按照协议优先级进行调度，保证优先级高的协议先得到处理。
4. **第四级**：对上送 CPU 的报文统一限速，对超过统一限速值的报文随机丢弃，保证整体上送 CPU 的报文不会过多，保护 CPU 安全。

**动态链路保护**：当设备检测到 SSH Session、Telnet Session、HTTP Session、FTP Session 以及 BGP Session 数据建立时，会启动对此 Session 的动态链路保护功能；后续上送报文如匹配此 Session 特征信息，此类数据将享受高速率上送的权利，由此保证此 Session 相关业务的运行可靠性、稳定性。

### 攻击溯源原理

攻击溯源包括报文解析、流量分析、攻击源识别和发送日志告警通知管理员以及实施惩罚四个过程。

> （原图：攻击溯源流程——报文解析 → 流量分析 → 攻击源识别 → 日志&告警 / 攻击惩罚；与芯片转发配合。）

通过上述过程找出攻击源后，管理员可通过 ACL 或配置黑名单的方式限制攻击源，以保护设备 CPU。

### 本章结构（设备安全加固）

1. 常见设备安全加固策略
2. 网络设备安全加固部署示例
   - STelnet 配置
   - 本机防攻击配置

---

## SSH 基本配置

### SSH 基本配置（1）

1. 使能设备的 SSH 服务器功能。

```cli
[Huawei] stelnet server enable
```

2. 配置 SSH 用户的认证方式。当用户使用 RSA 认证方式时，需要在 SSH 服务器上输入 SSH 客户端生成的密钥中的公钥部分。这样当客户端登录服务器时，自己的私钥如果与输入的公钥匹配成功，则认证通过。

3. 配置 SSH 服务器基于 SSH 客户端生成的密钥中的公钥部分。

```cli
[Huawei] rsa peer-public-key key-name
[Huawei-rsa-public-key] public-key-code begin
```

输入的公钥必须是按公钥格式编码的十六进制字符串，由支持 SSH 的客户端生成。

4. 退出公共密钥编辑视图；退出公共密钥视图，回到系统视图。

```cli
[Huawei-rsa-key-code] public-key-code end
[Huawei-rsa-public-key] peer-public-key end
```

### SSH 基本配置（2）

1. 为 SSH 用户分配 RSA 公钥。

```cli
[Huawei] ssh user user-name assign { rsa-key | ecc-key } key-name
```

2. 生成本地 RSA 主机密钥对和服务器密钥对。

```cli
[Huawei] rsa local-key-pair create
```

如果 RSA 密钥已经存在，则系统将提示用户确认是否替换原有密钥；执行此命令后，会提示您输入主机密钥的位数。服务器密钥对的位数与主机密钥对的位数至少相差 128 位。服务器密钥对和主机密钥对的最小长度为 512 位，最大长度为 2048 位，缺省长度为 2048 位。

3. 使能 SSH 客户端首次认证功能。

```cli
[Huawei] ssh client first-time enable
```

当 SSH 客户端首次访问 SSH 服务器，而 SSH 客户端没有配置 SSH 服务器端的公钥时，用户可以选择使能 SSH 客户端首次认证继续访问该 SSH 服务器，并在 SSH 客户端保存该主机公钥；当 SSH 客户端下次访问该 SSH 服务器时，就以保存的主机公钥来认证该 SSH 服务器。

### SSH 配置示例

用户希望安全地远程登录设备，因此配置 STelnet 方式进行远程安全登录。使用 RSA 认证方式登录 R3。配置安全策略，保证只有 R1 和 R2 才能登录设备。

> （原图：R1 `192.168.1.2`、R2 `192.168.1.3` 经 SW1 连接 R3 `192.168.1.1`。）

**配置步骤：**

1. 在 R3 生成本地密钥对，实现在服务器端和客户端进行安全的数据交互。
2. 在 R3 配置 SSH 用户 client001 和 client002。
3. 在 R3 开启 STelnet 服务功能。
4. 在 R3 配置 SSH 用户 client001 和 client002 的服务方式为 STelnet。
5. 在 R3 配置 SSH 服务器的端口号，有效防止攻击者对 SSH 服务标准端口的访问，确保安全性。
6. 用户 client001 和 client002 分别以 STelnet 方式实现登录 R3。

### SSH 配置命令

**（1）在 R3 生成本地密钥对**

```cli
[R3] rsa local-key-pair create
The key name will be: Host
RSA keys defined for Host already exist.
Confirm to replace them? (y/n):y
The range of public key size is (512 ~ 2048).
NOTES: If the key modulus is less than 2048,
It will introduce potential security risks.
Input the bits in the modulus[default = 2048]:2048
Generating keys...
++++++++
```

**（2）VTY、AAA 与本地用户**

```cli
[R3] user-interface vty 0 4
[R3-ui-vty0-4] authentication-mode aaa
[R3-ui-vty0-4] protocol inbound ssh
[R3-ui-vty0-4] quit
[R3] aaa
[R3-aaa] local-user client001 password irreversible-cipher Huawei@123
[R3-aaa] local-user client001 privilege level 3
[R3-aaa] local-user client002 password irreversible-cipher Huawei@123
[R3-aaa] local-user client002 privilege level 3
[R3-aaa] quit
```

**配置 SSH 用户认证类型、使能 STelnet、服务类型与端口**

```cli
[R3] ssh user client001 authentication-type password
[R3] ssh user client002 authentication-type rsa
[R3] stelnet server enable
[R3] aaa
[R3-aaa] local-user client001 service-type ssh
[R3-aaa] local-user client002 service-type ssh
[R3-aaa] quit
[R3] ssh server port 1025
```

**（3）在 R2 生成客户端本地密钥对**

```cli
[R2] rsa local-key-pair create
The key name will be: Host
RSA keys defined for Host already exist.
Confirm to replace them? (y/n):y
The range of public key size is (512 ~ 2048).
NOTES: If the key modulus is less than 2048,
It will introduce potential security risks.
Input the bits in the modulus[default = 2048]:2048
Generating keys...
++++++++
```

**（4）查看 R2 生成的 RSA 密钥对的公钥部分**

```cli
[R2] display rsa local-key-pair public
```

示例输出（Host Key 公钥片段）：

```cli
Key code:30820109 02820100
CB0E88EC A1C2CFEA F97126F9 36919C08 0455127B
A3A48594 69517096 35626F55 E4FAF0EB FDA2B9E9
5E417B2B E09F38B0 D26FCA73 FE2E3FC4 DFBEC8CF
4ED0C909 E8D975E6 FFC73C81 D13FE71E 759DC805
B0F0E877 4FC9288E BE1E197C 2A7186B0 B56F5573
3A5EA588 29C63E3B 20D56233 8E63278D F941734F
6B359C69 BBAE5A52 EB842179 04B4204D 5DB31D72
97F0C085 DA771F66 0AAADC28 D264CEB9 5BADA92C
CDE9F116 D6D99C48 CEBA3A1D 868B053A 32941D85
CCAA9796 A4B55760 0A8108ED DB45DA12 F61634C9
59431600 341FEDEF 5379D565 A8D1953D DEA018A2
72F99FFC 63DE04BF 2A6219BD DF13D705 27D63DEF
83D556BC 5B44D983 8D5EA126 C1EB71CB 0203 010001
```

**（5）将 R2 上产生的 RSA 公钥配置到服务器端**

（上页 `display` 命令显示信息中的公钥部分即为客户端产生的 RSA 公钥，将其拷贝粘贴至服务器端。）

```cli
[R3] rsa peer-public-key rsakey001
[R3-rsa-public-key] public-key-code begin
[R3-rsa-key-code] 02820100
[R3-rsa-key-code] CB0E88EC A1C2CFEA F97126F9 36919C08 0455127B
[R3-rsa-key-code] ...
[R3-rsa-key-code] 010001
[R3-rsa-key-code] public-key-code end
[R3-rsa-public-key] peer-public-key end
```

在 R3 上为 SSH 用户 client002 绑定 STelnet 客户端的 RSA 公钥：

```cli
[R3] ssh user client002 assign rsa-key rsakey001
```

### SSH 配置验证

**R1（password 认证用户 client001）登录：**

```cli
[R1] ssh client first-time enable
[R1] stelnet 192.168.1.1 1025
Please input the username:client001
Trying 192.168.1.1 ...
Press CTRL+K to abort
Connected to 192.168.1.1 ...
The server is not authenticated. Continue to access it?(y/n)[n]:y
Save the server's public key?(y/n)[n]:y
The server's public key will be saved with the name 192.168.1.1. Please wait.
Enter password:
<R3>
```

**R2（RSA 认证用户 client002）登录：**

```cli
[R2] ssh client first-time enable
[R2] stelnet 192.168.1.1 1025
Please input the username:client002
Trying 192.168.1.1 ...
Press CTRL+K to abort
Connected to 192.168.1.1
The server is not authenticated. Continue to access it?(y/n)[n]:y
Save the server's public key?(y/n)[n]:y
The server's public key will be saved with the name 192.168.1.1. Please wait.
<R3>
```

---

## 本机防攻击基本配置

1. 创建防攻击策略并进入防攻击策略视图。

```cli
[Huawei] cpu-defend policy policy-name
```

2. 配置黑名单。

```cli
[Huawei-cpu-defend-policy-test] blacklist blacklist-id acl acl-number
```

如果某个防攻击策略要配置多个黑名单，该防攻击策略的黑名单群中不允许出现二层 ACL 和基本 ACL、二层 ACL 和高级 ACL 以及三种 ACL 同时使用的情况。

3. 配置上送 CPU 报文的限制速率。

```cli
[Huawei-cpu-defend-policy-test] packet-type packet-type rate-limit rate-value
```

如果设备收到某种协议类型的攻击报文或大量上送 CPU 的正常报文，可以在防攻击策略中对该协议类型的报文进行限速，使该协议类型的报文限制在一个较小的速率范围内，减少对 CPU 处理正常业务的影响。

4. 配置上送 CPU 报文中指定协议类型报文的优先级。

缺省情况下，SSH 报文、Telnet 报文、SSHv6 报文、Telnetv6 报文、HTTP 报文、BGP 报文的动态链路保护功能的限制速率是 512 pps，FTP 报文的动态链路保护功能的限制速率是 1024 pps。

### 本机防攻击配置示例

如图所示，位于不同局域网的用户通过 R1 访问 Internet。为分析 R1 受攻击情况，需要配置攻击溯源检查功能记录攻击源信息。管理员发现存在以下现象：

> （原图：Net1、Net2 经 R1（含 GE2/0/2）连至 R2 / Internet。）

- 通过攻击溯源检查功能分析可知，Net1 中的某个用户经常会发生攻击行为。
- R1 收到大量的 ARP Request 报文，影响 CPU 的正常工作。
- R1 无法提供 FTP 服务。
- 局域网用户通过 DHCP 方式动态获取 IP 地址，但 R1 未优先处理上送 CPU 的 DHCP 报文。
- R1 收到大量的 Telnet 报文。

管理员希望通过在 R1 进行配置，以便解决上述问题。

### 本机防攻击配置命令

配置黑名单使用的 ACL：

```cli
[R1] acl number 4001
[R1-acl-L2-4001] rule 5 permit source-mac 0001-c0a8-0102
[R1-acl-L2-4001] quit
```

创建防攻击策略并配置攻击溯源、黑名单等：

```cli
[R1] cpu-defend policy devicesafety
[R1-cpu-defend-policy-devicesafety] auto-defend enable
[R1-cpu-defend-policy-devicesafety] auto-defend threshold 50
[R1-cpu-defend-policy-devicesafety] blacklist 1 acl 4001
```

配置要点说明：

1. 配置黑名单，将 Net1 网段中的攻击者（`0001-c0a8-0102`）列入黑名单，阻止其接入网络。
2. 配置 ARP Request 报文上送 CPU 的速率限制，使 ARP Request 报文限制在一个较小的速率范围内，减少对 CPU 处理正常业务的影响。
3. 配置 FTP 协议的动态链路保护功能，保证 R1 正常提供 FTP 功能。
4. 配置协议优先级，对 DHCP Client 报文设置较高的优先级，保证 R1 优先处理上送 CPU 的 DHCP Client 报文。
5. 关闭 R1 的 Telnet 服务器功能，使 R1 丢弃收到的 Telnet 报文。

应用层联动不需要使能，只要关闭 Router 的 Telnet 服务器功能，Router 会丢弃收到的 Telnet 报文。

### 本机防攻击配置验证

```cli
[R1] display cpu-defend policy devicesafety
Related slot  : <0>
Slot<0> : Success
Configuration :
Blacklist 1 ACL number : 4001
Packet-type arp-request rate-limit : 64(pps)
Packet-type dhcp-client priority : 3
Rate-limit all-packets : 2000(pps)(default)
```

查看上送到主控板的报文的统计信息，丢弃的报文表明设备对 arp-request 进行了速率限制：

```cli
<R1> display cpu-defend statistics
Packet Type      Pass Packets   Drop Packets
arp-request      1446576        127773
...
```

### 思考题（设备安全加固）

1. （判断题）当远程登录设备时，采用 STelnet 的方式比 Telnet 的方式更加安全，因为 STelnet 的方式登录采用 TCP 封装，而 Telnet 的方式登录设备采用 UDP 封装。
2. （判断题）本机防攻击包括 CPU 防攻击和攻击溯源两部分。

### 本章总结（设备安全加固）

- 设备的安全加固，需要从管理平面、控制平面和转发平面多个维度进行考虑。从设备本身的脆弱点出发，进行网络安全风险的评估，从而梳理出设备整体的安全架构和安全加固策略。
- 在设备支持的情况下，尽量采用 SSH、SFTP 等安全协议进行设备访问和数据传输。设备的 CPU 容易成为被攻击的对象，本机防攻击的部署至关重要。

---

## VPN 技术概述

常见 VPN 相关协议：

- **IPSec**：Internet Protocol Security，因特网协议安全协议。
- **GRE**：Generic Routing Encapsulation，通用路由封装协议。
- **L2TP**：Layer 2 Tunneling Protocol，二层隧道协议。
- **MPLS**：Multiprotocol Label Switching，多协议标签交换协议。

### 学习目标

学完本课程后，您将能够：

- 描述 VPN 的分类
- 描述 VPN 的实现方式

### 课程内容

1. 什么是 VPN
2. 常见 VPN 技术

### 技术背景

在 VPN 出现之前，企业分支之间的数据传输只能依靠现有物理网络（例如 Internet）。由于 Internet 中存在多种不安全因素，报文容易被网络中的黑客窃取或篡改，最终造成数据泄密、重要数据被破坏等后果。

除了通过 Internet，还可以通过搭建一条物理专网连接保证数据的安全传输，但其费用会非常昂贵，且专网的搭建和维护十分困难。

| 方式 | 特点 |
|------|------|
| 采用 Internet 传输数据 | 直接使用共享且不安全的 Internet 传输数据，可能导致数据被盗取、篡改 |
| 搭建专网传输数据 | 有效保证企业数据传输安全性，但面临使用成本高、使用率低、部署不灵活等问题 |

VPN 和传统的数据专网相比具有如下优势：

- **安全**：在远端用户、驻外机构、合作伙伴、供应商与公司总部之间建立可靠的连接，保证数据传输的安全性。这对于实现电子商务或金融网络与通讯网络的融合特别重要。
- **廉价**：利用公共网络进行信息通讯，企业可以用更低的成本连接远程办事机构、出差人员和业务伙伴。
- **支持移动业务**：支持驻外 VPN 用户在任何时间、任何地点的移动接入，能够满足不断增长的移动业务需求。
- **可扩展性**：由于 VPN 为逻辑上的网络，物理网络中增加或修改节点，不影响 VPN 的部署。

公共网络又经常被称为 VPN 骨干网（VPN Backbone），公共网络可以是 Internet，也可以是企业自建专网或运营商租赁专网。

### VPN 分类——根据建设单位不同

| 类型 | 说明 |
|------|------|
| 租用运营商 VPN 专线搭建企业 VPN 网络 | 最常见的场景为租用运营商 MPLS VPN 专线；VPN 网关为运营商所有 |
| 自建企业 VPN 网络 | 基于 Internet 建立企业 VPN 网络，常见的如 IPSec VPN、L2TP VPN、SSL VPN 等 |

### VPN 分类——根据组网方式不同

| 类型 | 说明 |
|------|------|
| 远程访问 VPN（Remote Access VPN） | 适用于出差员工 VPN 拨号接入的场景；常见的有 L2TP VPN、SSL VPN 等 |
| 局域网到局域网的 VPN（Site-to-site VPN） | 适用于公司两个异地机构的局域网互连；常见的有 MPLS VPN、IPSec VPN 等 |

### VPN 分类——根据实现的网络层次

| 层次 | 技术 |
|------|------|
| 应用层 | SSL VPN |
| 传输层 | — |
| 网络层 | IPSec VPN、GRE VPN、MPLS VPN |
| 数据链路层 | L2TP VPN、PPTP VPN |
| 物理层 | — |

### 隧道技术

隧道的功能就是在两个网络节点之间提供一条通路，使数据能够在这个通路上透明传输。VPN 隧道一般是指在 VPN 骨干网的 VPN 节点之间建立的用来传输 VPN 数据的虚拟连接。隧道是构建 VPN 不可或缺的部分，用于把 VPN 数据从一个 VPN 节点透明传送到另一个上。

隧道通过隧道协议实现。目前已存在不少隧道协议，如 GRE、L2TP 等。隧道协议通过在隧道的一端给数据加上隧道协议头（封装），使这些被封装的数据能在某网络中传输，并且在隧道的另一端去掉该数据携带的隧道协议头（解封装）。报文在隧道中传输前后都要经过封装和解封装两个过程。

部分隧道可以混合使用，如 GRE Over IPSec 隧道。

### VPN 关键技术——身份认证、数据加密与验证

身份认证、数据加密和认证技术可以有效保证 VPN 网络与数据的安全性：

- **身份认证**：可用于部署了远程接入 VPN 的场景，VPN 网关对用户的身份进行认证，保证接入网络的都是合法用户而非恶意用户；也可用于 VPN 网关之间对对方身份的认证。
- **数据加密**：将明文通过加密变成密文，使得数据即使被黑客截获，黑客也无法获取其中的信息。
- **数据验证**：通过数据验证技术对报文的完整性和真伪进行检查，丢弃被伪造和被篡改的报文。

| VPN | 用户身份认证 | 数据加密和验证 |
|-----|--------------|----------------|
| GRE | 不支持 | 支持简单的关键字验证、检验和验证；可结合 IPSec 使用 |
| L2TP | 支持基于 PPP 的 CHAP、PAP、EAP 认证 | 不支持；可结合 IPSec 的数据加密和验证特性 |
| IPSec | 支持 | 支持预共享密钥验证或证书认证；支持 IKEv2 的 EAP 认证 |
| SSL | 支持 | 支持用户名/密码或证书认证 |
| MPLS | 不支持 | 不支持；一般运行在专用的 VPN 骨干网络 |

### IPSec VPN

IPSec 提供的安全能力包括：

- **数据来源验证**：接收方验证发送方身份是否合法。
- **数据加密**：发送方对数据进行加密，以密文的形式在 Internet 上传送，接收方对接收的加密数据进行解密后处理或直接转发。
- **数据完整性**：接收方对接收的数据进行验证，以判定报文是否被篡改。
- **抗重放**：接收方拒绝旧的或重复的数据包，防止恶意用户通过重复发送捕获到的数据包所进行的攻击。

IPSec 使用认证头 AH（Authentication Header）和封装安全载荷 ESP（Encapsulating Security Payload）两种安全协议来传输和封装数据，提供认证或加密等安全服务。

- AH 和 ESP 协议提供的安全功能依赖于协议采用的验证、加密算法。
- AH 仅支持认证功能，不支持加密功能。ESP 支持认证和加密功能。
- 安全协议提供认证或加密等安全服务需要有密钥的存在。

密钥交换的方式有两种：

- **带外共享密钥**：在发送、接收设备上手工配置静态的加密、验证密钥。双方通过带外共享的方式（例如通过电话或邮件方式）保证密钥一致性。缺点是可扩展性差，在点到多点组网中配置密钥的工作量成倍增加；为提升网络安全性需要周期性修改密钥，这种方式下也很难实施。
- **通过 IKE 协议自动协商密钥**：IKE 建立在 Internet 安全联盟和密钥管理协议 ISAKMP 定义的框架上，采用 DH（Diffie-Hellman）算法在不安全的网络上安全地分发密钥。这种方式配置简单，可扩展性好，特别是在大型动态的网络环境下此优点更加突出。通信双方通过交换密钥交换材料来计算共享的密钥，即使第三方截获了双方用于计算密钥的所有交换数据，也无法计算出真正的密钥。

**SA（Security Association）**：由一个三元组来唯一标识，包括安全参数索引 SPI（Security Parameter Index）、目的 IP 地址和使用的安全协议号（AH 或 ESP）。其中，SPI 是为唯一标识 SA 而生成的一个 32 位比特的数值，它在 AH 和 ESP 头中传输。在手工配置 SA 时，需要手工指定 SPI 的取值；使用 IKE 协商产生 SA 时，SPI 将随机生成。

SA 是单向的逻辑连接，因此两个 IPSec 对等体之间的双向通信，最少需要建立两个 SA 来分别对两个方向的数据流进行安全保护。

IKE 作为密钥协商协议，存在两个版本：IKEv1 和 IKEv2。本课程采用 IKEv1 为例进行介绍，IKEv2 内容可参考产品文档对应内容。

- **IKEv1 协商阶段 1**：目的是建立 IKE SA。IKE SA 建立后对等体间的所有 ISAKMP 消息都将通过加密和验证，这条安全通道可以保证 IKEv1 第二阶段的协商能够安全进行。IKE SA 是一个双向的逻辑连接，两个 IPSec 对等体间只建立一个 IKE SA。
- **IKEv1 协商阶段 2**：目的就是建立用来安全传输数据的 IPSec SA，并为数据传输衍生出密钥。该阶段使用 IKEv1 协商阶段 1 中生成的密钥对 ISAKMP 消息的完整性和身份进行验证，并对 ISAKMP 消息进行加密，故保证了交换的安全性。

IKE 协商成功意味着双向的 IPSec 隧道已经建立，可以通过 ACL 方式或者安全框架方式定义 IPSec“感兴趣流”，符合感兴趣流流量特征的数据都将被送入 IPSec 隧道进行处理。

- **感兴趣流**：需要被 IPSec 保护的数据流。

### GRE VPN

如图所示，通过在 IPv4 网络上建立 GRE 隧道，解决了两个 IPv6 网络的通信问题。GRE 还具备封装组播报文的能力。由于动态路由协议中会使用组播报文，因此更多时候 GRE 会在需要传递组播路由数据的场景中被用到，这也是 GRE 被称为通用路由封装协议的原因。

**隧道接口（Tunnel Interface）** 是为实现报文的封装而提供的一种点对点类型的虚拟接口，与 Loopback 接口类似，都是一种逻辑接口。

如图所示，乘客协议为 IPv6，封装协议为 GRE，运输协议为 IPv4。整体转发流程如下：

1. 当 R1 收到 IP1 发来的 IPv6 数据包，查询设备路由表，发现出接口是隧道接口，则将此报文发给隧道接口处理。
2. 隧道接口给原始报文添加 GRE 头部，然后根据配置信息，给报文加上 IP 头。该 IP 头的源地址就是隧道源地址，IP 头的目的地址就是隧道目的地址。
3. 封装后的报文在 IPv4 网络中进行普通的 IPv4 路由转发，最终到达目的地 R2。
4. 解封装过程和封装过程相反。

### GRE Over IPSec

GRE 的主要缺点是不支持加密和认证，数据的安全传输得不到很好的保障。IPSec 的主要缺点是只支持 IP 协议，且不支持组播。可通过部署 GRE Over IPSec 结合两种 VPN 技术的优点。

> （原图：企业分支与企业总部之间，GRE 隧道在内层，IPSec 隧道在外层，数据被加密后经 Internet 传输。）

### L2TP VPN

VPDN 是指利用公共网络（如 ISDN 和 PSTN）的拨号功能及接入网来实现虚拟专用网，为企业、小型 ISP、移动办公人员提供接入服务。VPDN 采用专用的网络加密通信协议，在公共网络上为企业建立安全的虚拟专网。企业驻外机构和出差人员可从远程经由公共网络，通过虚拟加密隧道实现和企业总部之间的网络连接，而公共网络上其它用户则无法穿过虚拟隧道访问企业网内部的资源。VPDN 隧道协议有多种，目前使用最广泛的是 L2TP。

- **LAC**：网络上具有 PPP 和 L2TP 协议处理能力的设备。LAC 负责和 LNS 建立 L2TP 隧道连接。在不同的组网环境中，LAC 可以是不同的设备，可以是一台网关设备，也可以是一台终端设备。LAC 可以发起建立多条 L2TP 隧道使数据流之间相互隔离。
- **LNS**：LAC 的对端设备，即 LAC 和 LNS 建立了 L2TP 隧道；LNS 位于企业总部私网与公网边界，通常是企业总部的网关设备。

**控制消息**：用于 L2TP 隧道和会话连接的建立、维护和拆除。在控制消息的传输过程中，使用消息丢失重传和定时检测隧道连通性等机制来保证控制消息传输的可靠性，支持对控制消息的流量控制和拥塞控制。控制消息承载在 L2TP 控制通道上，控制通道实现了控制消息的可靠传输，将控制消息封装在 L2TP 报头内，再经过 IP 网络传输。

**数据消息**：用于封装 PPP 数据帧并在隧道上传输。数据消息是不可靠的传输，不重传丢失的数据报文，不支持对数据消息的流量控制和拥塞控制。数据消息携带 PPP 帧承载在不可靠的数据通道上，对 PPP 帧进行 L2TP 封装，再经过 IP 网络传输。

#### L2TP 典型场景

**NAS-Initiated 场景**：由远程拨号用户发起，远程系统通过 PSTN/ISDN 拨入 LAC，由 LAC 通过 Internet 向 LNS 发起建立隧道连接请求。拨号用户地址由 LNS 分配；对远程拨号用户的验证与计费既可由 LAC 侧的代理完成，也可在 LNS 完成。

- 用户必须采用 PPP 的方式接入到 Internet，也可以是 PPPoE 等协议。
- 运营商的接入设备（主要是 BAS 设备）需要开通相应的 VPN 服务。用户需要到运营商处申请该业务。
- L2TP 隧道两端分别驻留在 LAC 侧和 LNS 侧，且一个 L2TP 隧道可以承载多个会话。

**Client-Initialized 场景**：直接由 LAC 客户（指可在本地支持 L2TP 协议的用户）发起。客户需要知道 LNS 的 IP 地址。LAC 客户可直接向 LNS 发起隧道连接请求，无需再经过一个单独的 LAC 设备。在 LNS 设备上收到了 LAC 客户的请求之后，根据用户名、密码进行验证，并且给 LAC 客户分配私有 IP 地址。

- 用户需要安装 L2TP 的拨号软件。部分操作系统自带 L2TP 客户端软件。
- 用户上网的方式和地点没有限制，不需 ISP 介入。
- L2TP 隧道两端分别驻留在用户侧和 LNS 侧，一个 L2TP 隧道承载一个 L2TP 会话。
- 该场景建立过程如下：
  1. 移动办公用户与 LNS 建立 L2TP 隧道。
  2. 移动办公用户与 LNS 建立 L2TP 会话：移动办公用户会与 LNS 间建立 PPP 连接，L2TP 会话用来记录和管理它们之间的 PPP 连接状态。因此，在建立 PPP 连接以前，隧道双方需要为 PPP 连接预先协商出一个 L2TP 会话。会话中携带了移动办公用户的 LCP 协商信息和用户认证信息，LNS 对收到的信息认证通过后，通知移动办公用户会话建立成功。L2TP 会话连接由会话 ID 进行标识。
  3. 移动办公用户与 LNS 建立 PPP 连接。移动办公用户通过与 LNS 建立 PPP 连接获取 LNS 分配的企业内网 IP 地址。
  4. 移动办公用户发送业务报文访问企业总部服务器。

**Call-LNS 场景**：L2TP 除了可以为出差员工提供远程接入服务以外，还可以进行企业分支与总部的内网互联，实现分支用户与总部用户的互访。一般是由分支路由器充当 LAC 与 LNS 建立 L2TP 隧道，这样就可实现分支与总部网络之间的数据通过 L2TP 隧道互通。

企业出差用户和总部通信，使用 L2TP 功能建立 VPN 连接，总部部署为 LNS 对接入的用户进行认证。当出差用户需要向总部传输高机密信息时，L2TP 无法为报文传输提供足够的保护，这时可以和 IPSec 功能结合使用，保护传输的数据。在出差用户的 PC 终端上运行拨号软件，将数据报文先进行 L2TP 封装，再进行 IPSec 封装，发往总部。在总部网关，部署 IPSec 策略，最终还原数据。这种方式 IPSec 功能会对所有源地址为 LAC、目的地址为 LNS 的报文进行保护。

### MPLS VPN

MPLS VPN 网络一般由运营商搭建，VPN 用户购买 VPN 服务来实现用户网络之间（图中的分公司和总公司）的路由传递、数据互通等。

基本的 MPLS VPN 网络架构由 CE（Customer Edge）、PE（Provider Edge）和 P（Provider）三部分组成：

- **CE**：用户网络边缘设备，有接口直接与运营商网络相连。CE 可以是路由器或交换机，也可以是一台主机。通常情况下，CE“感知”不到 VPN 的存在，也不需要支持 MPLS。
- **PE**：运营商边缘路由器，是运营商网络的边缘设备，与 CE 直接相连。在 MPLS 网络中，对 VPN 的所有处理都发生在 PE 上，对 PE 性能要求较高。
- **P**：运营商网络中的骨干路由器，不与 CE 直接相连。P 设备只需要具备基本 MPLS 转发能力，不维护 VPN 相关信息。

更多 MPLS 及 MPLS VPN 的相关内容，参考 HCIP-Datacom-Advance 相应课程。

### 思考题（VPN）

1. （判断题）L2TP VPN 工作在网络层。A. 正确 B. 错误
2. （多选题）IPSec SA 包含以下哪些内容？A. SPI B. 安全协议 C. 源地址 D. 目的地址

### 本章总结（VPN）

- VPN 技术拥有安全、廉价、支持移动业务、灵活等一系列优势，已经成为现网中部署最为广泛的一类技术。
- 本课程从 VPN 基本概念与分类出发，简单介绍了如下几类常见 VPN 技术：
  - **IPSec VPN**：是一系列为 IP 网络提供安全性的协议和服务的集合，为 IP 网络提供安全的传输。
  - **GRE VPN**：提供了将一种协议的报文封装在另一种协议报文中的机制，解决异种网络的传输问题。
  - **L2TP VPN**：是一种能够提供移动用户远程接入服务的二层 VPN 技术。
  - **MPLS VPN**：一种通过标签交换技术，实现站点与站点之间互联的 VPN 技术。

---

## VRF 基本概念及应用

### 前言

回顾前面学习的课程，您还记得几个名字中带“V”的协议或技术？这些协议或技术又有哪些特点或共同点？

VRF（Virtual Routing and Forwarding，虚拟路由转发）技术通过在一台三层转发设备上创建多张路由表实现数据或业务的隔离，常用于 MPLS VPN、防火墙等一些需要实现隔离的应用场景。

本课程将介绍 VRF 的基本概念及其基本配置方法。

### 学习目标

学完本课程后，您将能够：

- 描述 VRF 的基本概念
- 描述 VRF 的典型应用
- 实现 VRF 的基本配置

### 课程内容

1. VRF 基本概念
2. VRF 典型配置案例

### 网络需求

某企业网络内有生产和管理两张网络，这两张网络独占接入和汇聚层交换机，共享核心交换机。核心交换机上同时连接了生产网络和管理网络的服务器群，两个网段均为 `192.168.100.0/24` 网段。

**需求**：实现生产和管理网络内部的数据通信，同时隔离两张网络之间的通信。

> （原图：生产网络服务器 / 管理网络服务器 均为 `192.168.100.0/24`；生产/管理客户端经核心交换机访问各自服务器。）

### 方案对比

**通过部署 ACL 实现**

在核心交换机部署 ACL，禁止生产和管理网络之间的互访流量。

缺陷：

- 配置繁琐，拓展性差。
- 无法解决两张网络使用重叠网段的问题，需要在部署时规避重叠网段。

**通过增加核心交换机实现**

增加核心交换机，从物理上隔离两张网络。

缺陷：增加额外的设备成本投入。

**通过 VRF 技术实现**

VRF 又称 VPN 实例（VPN Instance），是一种虚拟化技术。在物理设备上创建多个 VPN 实例，每个 VPN 实例拥有独立的接口、路由表和路由协议进程等。

示例路由表：

| VPN 实例 | 目的网段/掩码 | 协议 | 出接口 | 下一跳 |
|----------|---------------|------|--------|--------|
| VPNA | 192.168.100.0/24 | OSPF | VLANIF100 | 192.168.100.1 |
| VPNA | 192.168.1.0/24 | OSPF | VLANIF101 | 192.168.101.1 |
| VPNB | 192.168.100.0/24 | OSPF | VLANIF200 | 192.168.100.1 |
| VPNB | 172.16.1.0/24 | Static | VLANIF201 | 192.168.201.1 |

> （原图：PC1 `192.168.1.1` 网关 `192.168.1.254`；PC2 `172.16.1.1` 网关 `172.16.1.254`。）

### VRF 的实现过程

VRF 是对物理设备的一个逻辑划分，每个逻辑单元都被称为一个 VPN 实例，实例之间在路由层面是隔离的。VRF 实现过程如下：

1. 创建实例，并将三层接口（可以是路由器的物理接口或者子接口，也可以是 VLANIF 接口）绑定到实例；
2. （可选）配置与实例绑定的路由协议或静态路由；
3. 基于与实例绑定的接口和路由协议等建立实例路由表并基于实例路由表转发数据，实现实例间隔离。

> （原图：同一路由器上 GE0/0/0~GE0/0/3 分别归属 VPNA / VPNB；部署 OSPF 与 IS-IS 后形成 VPNA 路由表与 VPNB 路由表。）

### 举例：部署 VRF 前

背景：PC1、R1 及 R1 所连的 `1.1.1.0/24` 网段属于业务网络。PC2、R2 及 R2 所连的 `2.2.2.0/24` 网段属于管理网络。核心交换机上所有的直连路由，以及设备所发现的、到达远端网络的路由，均被存储在设备的路由表中（将该路由表称为全局路由表），业务及管理网络可以通过核心交换机实现互通。

**需求**：通过配置实现业务与管理网络完全隔离。

核心交换机部署 VRF 前的路由表示意：

| 目的网络/掩码 | 协议 | 出接口 | 下一跳 |
|---------------|------|--------|--------|
| 192.168.1.0/24 | Direct | VLANIF10 | 192.168.1.254 |
| 172.16.1.0/24 | Direct | VLANIF200 | 172.16.1.254 |
| 192.168.100.0/24 | Direct | VLANIF11 | 192.168.100.1 |
| 172.16.100.0/24 | Direct | VLANIF201 | 172.16.100.1 |
| 1.1.1.0/24 | Static | VLANIF11 | 192.168.100.2 |
| 2.2.2.0/24 | Static | VLANIF201 | 172.16.100.2 |

### 举例：创建 VPN 实例

创建 VPN 实例后，核心交换机保留全局（根）路由表，同时增加 VPN 实例路由表。业务侧路由进入 VPN 实例 1 路由表，管理侧路由进入对应实例路由表，从而实现隔离。

> （原图：核心交换机全局路由表与 VPN 实例 1 路由表并存；`192.168.100.2` 等地址归属业务侧实例。）

### 举例：部署动态路由协议

在设备上可运行多种动态路由协议，或运行同一种动态路由协议的多个进程，关联到 VPN 实例的动态路由协议进程专为该实例服务，从该进程学习到的路由加载到 VPN 实例的路由表中。

（本节配置命令与完整案例见下一章。）
