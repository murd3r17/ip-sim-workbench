---
doc_id: "hcia-security-v4.0-training-06"
title: "IPSec VPN与SSL VPN配置举例"
book: "HCIA-Security-V4.0-Training"
book_title: "HCIA-Security V4.0 培训教材"
track: "security"
level: "hcia"
series: "security-v4"
doc_type: "training"
source_pdf: "HCIA-Security+V4.0+培训教材(1).pdf"
seq: 6
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# IPSec VPN与SSL VPN配置举例

## IKE协商过程详解

### IKEv1第一阶段——主模式交换

- 数字进行运算，得出一个DH值Xa和Xb（Xa是发起方的DH值，Xb是响应者的DH值），然后双方再根据DH算法运算得出一个临时值Ni和Nr。
- 第二次交换中，双方交换各自的密钥交换载荷（即Diffie-Hellman交换）以及临时值载荷（即nonce交换）。其中密钥交换载荷包含了Xa和Xb，临时值交换包含了Ni和Nr。
- 双方交换了临时值载荷Ni和Nr之后，配合事先预置好的预共享密钥，再通过随机函数运算便可产生一个密钥SKEYID，这个密钥是后续所有密钥生成的基础。随后，通过自己算出来的DH值、交换得到的DH值以及SKEYID进行运算便可产生一个只有双方才知道的共享密钥SKEYID_d。此共享密钥并不进行传输，传输的只是DH值以及临时值，因此即使第三方得到了这些材料也无法计算出共享密钥。
- 在第二次交换完成之后，双方所需的计算材料都已经交换完毕，此时，双方就可以将所有的密钥计算出来，并使用该密钥对随后的IKE消息提供安全保护。这些密钥包括：SKEYID_a以及SKEYID_e。SKEYID_a用来为IKE消息提供完整性以及数据源身份验证等安全服务；SKEYID_e则用于对IKE消息进行加密。
- 第三次交换是对标识载荷和散列载荷进行交换。标识载荷包含了发起者的标识信息、IP地址或主机名，散列载荷包含上一过程中产生的三组密钥进行Hash运算得出的值。这两个载荷通过SKEYID_e进行加密，如果双方的载荷相同，那么认证成功。IKE第一阶段主模式预共享密钥交换也就完成了。

### IKEv1第一阶段——野蛮模式交换

- 从上述主模式协商的叙述中可以看到，在第二次交换之后便可生成会话密钥，会话密钥的生成材料中包含了预共享密钥。而当一个对等体同时与多个对等体进行协商SA时，则需要为每个对等体设置一个预共享密钥。为了对每个对等体正确地选择对应的预共享密钥，主模式需要根据前面交换信息中的IP地址来区分不同的对等体。
- 但是当发起者的IP地址是动态分配获得时，由于发起者的IP地址不可能被响应者提前知道，而且双方都打算采用预共享密钥验证方法，此时响应者就无法根据IP地址选择对应的预共享密钥。野蛮模式就是被用于解决这个矛盾的。
- 与主模式不同，野蛮模式仅用3条信息便完成了IKE SA的建立。由于对消息数进行了限制，野蛮模式同时也限制了它的协商能力，而且不会提供身份保护。
- 在野蛮模式的协商过程中，发起者会提供一个保护套件列表、Diffie-Hellman公共值、nonce以及身份资料。所有这些信息都是随第一条信息进行交换的。作为响应者，则需要回应选择一个保护套件、Diffie-Hellman公共值、nonce、身份资料以及一个验证载荷。发起者将它的验证载荷在最后一条消息交换。
- 野蛮模式由于在其第一条信息中就携带了身份信息，因此本身无法对身份信息进行加密保护，这就降低了协商的安全性，但也因此不依赖IP地址标识身份，在野蛮模式下也就有了更多灵活的应用。

### IKEv1主模式和野蛮模式区别

- 交换的消息：
  - 主模式为6个，野蛮模式为3个。
- 身份保护：
  - 主模式的最后两条消息有加密，可以提供身份保护功能；而野蛮模式消息集成度过高，因此无身份保护功能。
- 对等体标识：
  - 主模式只能采用IP地址方式标识对等体；而野蛮模式可以采用IP地址方式或者Name方式标识对等体。

### IKEv1第二阶段——快速模式交换

- 建立好IKE SA之后（无论通过主模式还是通过野蛮模式交换），便可用它为IPSec生成相应的SA。IPSec SA是通过快速模式交换来建立的，对快速模式交换来说，它是在已经建立好的IKE SA的保护下完成的。
- 在一次快速交换模式中，通信双方需要协商拟定IPSec安全联盟的各项特征，并为其生成密钥。IKE SA保护快速模式交换的方法是：对其进行加密，并对消息进行验证。消息的验证是通过伪随机函数来进行的。来自IKE SA的SKEYID_a的值作为一个密钥，对快速模式交换的整个消息进行验证。这种验证除了能提供数据完整性保证之外，还能对数据源的身份进行验证。在消息接收到之后，我们知道它只有可能来自验证通过的实体，而且那条消息在传送过程并未发生改变。而通过加密（使用SKEYID_e），则可保障交换的机密性。
- 快速模式需要从SKEYID_d状态中衍生出用于IPSec SA的密钥，这个密钥将在伪随机函数中使用，这样便可确保每个SA都有自己独一无二的密钥。每个SA都有一个不同的SPI，所以入方向SA的密钥也会与出方向SA不同。所有IPSec密钥都是根据相同的来源衍生的，所以相互间都有关联。假如一名攻击者能够根据IKE SA判断出SKEYID_d的值，那么就能非常容易地掌握自那个SKEYID_d衍生出来的IPSec SA的任何密钥。另外，还能继续掌握未来将要衍生的所有密钥，这显然是个大问题，所有这些密钥都不能保证所谓的"完美向前保密（PFS）"。快速模式为此专门提供了一个PFS选项，来满足这方面的需要，用户可根据自己的安全需要选择是否使用PFS。
- 为了在快速模式交换中实现PFS，需要执行一次额外的Diffie-Hellman交换，最终生成的共享密钥将在为IPSec生成密钥的过程中用到。显然，一旦交换完成，这个密钥便不复存在。一旦完成，它所驻留的那个内存位置必须清零和释放。从而保证了密钥之间的不相关性。
- 我们前面将快速模式描述成一种简单的请求/响应交换，但它的实际功用远不止于此。发起者可能需要一个"在场"证据，证明响应者在线，而且已经实际地处理了它的初始快速模式消息。为了达到这个要求，响应者需要在验证散列载荷中，加入交换的发起者nonce以及消息ID。这个摘要现在不仅能保障消息的完整性，也能为发起者提供源验证功能，另外还能提供在场证据。
- 响应者也需要一个在场证据，从发起者传来的可能是一条过期的消息，是由不怀好意的人重播的。这个人可能不知道消息的内容，但通过对通信的分析，能够知道它是一条快速模式消息。如果重播那条消息，响应者便不得不创建多余的SA。我们可将其想像成一种"服务否认"攻击，只是属于比较温和的那种，因为响应者会根据这条消息，增加不必要的内存及SA管理开销。想要防范此类攻击，需在快速模式交换中增加第三条消息。在这条消息中，发起者需要同时包括nonce和此次交换的消息ID，并把它们保存在一个验证散列载荷中。这样发起者便可向响应者证实：自己是此次交换的活动参与者。
- 在前两条消息中，发起者和响应者都发送了SA载荷，和主模式、野蛮模式一样，SA载荷是用来协商各种保护算法的。而Ni、Nr以及ID则是用来提供"在场证据"的。Xa以及Xb则是用来生成新的DH共享密钥，保证PFS的。Xa以及Xb将与IKE第一阶段生成的SKEYID_d、Ni、Nr以及SPI等信息共同生成最终用于IPSec加密的密钥。
- 最后发起者会发送一条确认信息，响应者收到该信息后就知道发起者已经收到了第二条消息。此时IKE第二阶段结束。

### IKEv2协商

- 采用IKEv2协商安全联盟比IKEv1协商过程要简化的多。要建立一对IPSec SA，IKEv1需要经历两个阶段："主模式＋快速模式"或者"野蛮模式＋快速模式"，前者至少需要交换9条消息，后者也至少需要6条消息。而IKEv2正常情况使用2次交换共4条消息就可以完成一对IPSec SA的建立，如果要求建立的IPSec SA大于一对时，每一对IPSec SA只需额外增加1次创建子SA交换，也就是2条消息就可以完成。

#### 初始交换过程

- 消息①和②属于第一次交换（称为IKE_SA_INIT交换），以明文方式完成IKE SA的参数协商，包括协商加密和验证算法、交换临时随机数和DH交换。IKE_SA_INIT交换后生成一个共享密钥材料，通过这个共享密钥材料可以衍生出IPSec SA的所有密钥。
- 消息③和④属于第二次交换（称为IKE_AUTH交换），以加密方式完成身份认证、对前两条信息的认证和IPSec SA的参数协商。IKEv2支持RSA签名认证、预共享密钥认证以及扩展认证方法EAP（Extensible Authentication Protocol）。EAP认证是作为附加的IKE_AUTH交换在IKE中实现的，发起者通过在消息3中省去认证载荷来表明需要使用EAP认证。

#### 创建子SA交换

- 当一个IKE SA需要创建多对IPSec SA时，需要使用创建子SA交换来协商多于一对的IPSec SA。另外，创建子SA交换还可以用于IKE SA的重协商。
- 创建子SA交换包含一个交换两条消息，对应IKEv1协商阶段2，交换的发起者可以是初始交换的协商发起方，也可以是初始交换的协商响应方。创建子SA交换必须在初始交换完成后进行，交换消息由初始交换协商的密钥进行保护。
- 类似于IKEv1，如果启用PFS，创建子SA交换需要额外进行一次DH交换，生成新的密钥材料。生成密钥材料后，子SA的所有密钥都从这个密钥材料衍生出来。

#### IKEv2通知交换

- 运行IKE协商的两端有时会传递一些控制信息，例如错误信息或者通告信息，这些信息在IKEv2中是通过通知交换完成的。
- 通知交换必须在IKE SA保护下进行，也就是说通知交换只能发生在初始交换之后。控制信息如果是IKE SA的，由IKE SA来保护进行。
- 协商发起方发送控制信息，协商响应方根据控制信息进行相应操作，接受参数并回应控制信息。

## L2TP VPN简介

- L2TP（Layer Two Tunneling Protocol）二层隧道协议是另一种常见VPN协议。
- L2TP是虚拟私有拨号网VPDN（Virtual Private Dial-up Network）隧道协议的一种，它扩展了点到点协议PPP的应用，是一种在远程办公场景中为出差员工或企业分支远程访问企业内网资源提供接入服务的VPN。

### L2TP VPN主要使用场景

- NAS-Initiated VPN：由远程拨号用户发起，远程系统通过PSTN/ISDN拨入LAC。由LAC通过Internet向LNS发起建立隧道连接请求，拨号用户地址则由LNS分配。对远程拨号用户的验证与计费既可由LAC侧的代理完成，也可在LNS完成。
- Call-LNS：L2TP除了可以为出差员工提供远程接入服务以外，还可以进行企业分支与总部的内网互联，实现分支用户与总部用户的互访。
- Client-Initialized：直接由LAC客户（指可在本地支持L2TP协议的用户）发起。客户需要知道LNS的IP地址。LAC客户可直接向LNS发起隧道连接请求，无需再经过一个单独的LAC设备。在LNS设备上收到了LAC客户的请求之后，根据用户名、密码进行验证，并且给LAC客户分配私有IP地址。

### Client-Initiated场景中的L2TP VPN原理

从隧道协商、报文封装、安全策略这3个方面介绍Client-Initiated场景中L2TP VPN的工作原理。

#### 隧道协商

移动办公用户在访问企业总部服务器之前，需要先通过L2TP VPN软件与LNS建立L2TP VPN隧道。移动办公用户与LNS协商建立L2TP VPN隧道，直至最后成功访问企业内网资源的完整过程如下：

> （原图：L2TP Client、LNS、内网服务器、Internet组网，依次建立L2TP隧道、建立L2TP会话、建立PPP连接、数据封装传输）

#### 报文转发过程

- L2TP Client发往内网服务器的报文的转发过程如下：
  - L2TP Client将原始报文用PPP头、L2TP头、UDP头、外层公网IP头层层封装，成为L2TP报文。
  - L2TP报文穿过Internet到达LNS。
  - LNS收到报文后，在L2TP模块中完成了身份认证和报文的解封装，去掉PPP头、L2TP头、UDP头、外层公网IP头，还原成原始报文。
  - 原始报文只携带了内层私网IP头，内层私网IP头中的源地址是L2TP Client获取到的私网IP地址，目的地址是内网服务器的私网IP地址。LNS根据目的地址查找路由表，然后根据路由匹配结果转发报文。

#### 安全策略处理

移动办公用户访问企业总部服务器的过程中，经过LNS的流量分为以下2类，对应流量的安全策略处理原则如下：

- 移动办公用户与LNS间的L2TP报文：此处的L2TP报文既包含移动办公用户与LNS建立隧道时的L2TP协商报文，也包含移动办公用户访问企业总部服务器被解封装前的业务报文，这些L2TP报文会经过Untrust > Local区域。
- 移动办公用户访问企业总部内网服务器的业务报文：LNS通过VT接口将移动办公用户访问企业总部服务器的业务报文解封装以后，这些报文经过的安全域间为DMZ > Trust。DMZ区域为LNS上Tunnel接口所在的安全区域，Trust为LNS连接总部内网接口所在的安全区域。

## SSL VPN简介

- SSL VPN主要应用场景：企业出差员工，需要在外地远程办公，并期望能够通过Internet随时随地的远程访问企业内部资源。同时，企业为了保证内网资源的安全性，希望能对移动办公用户进行多种形式的身份认证，并对移动办公用户可访问内网资源的权限做精细化控制。
- 防火墙作为企业出口网关连接至Internet，并向移动办公用户（即出差员工）提供SSL VPN接入服务。移动办公用户使用终端（如便携机、PAD或智能手机）与防火墙建立SSL VPN隧道以后，就能通过SSL VPN隧道远程访问企业内网的Web服务器、文件服务器、邮件服务器等资源。

### SSL VPN封装

- SSL封装位于传输层与各种应用层协议之间，为数据通讯提供安全支持，建立在可靠的传输协议（如TCP）之上，为高层协议提供数据封装、压缩、加密等基本功能的支持。

> （原图：SSL封装位于传输层与应用层协议之间，HTTP经SSL加密后由TCP/IP承载）

### SSL VPN业务-Web代理

移动办公用户登录SSL VPN虚拟网关并访问企业内网资源的过程如下：

- 用户登录：移动办公用户在浏览器中输入SSL VPN虚拟网关的IP地址或域名，请求建立SSL连接。虚拟网关向远程用户发送自己的证书，远程用户对虚拟网关的证书进行身份认证。认证通过后，远程用户与虚拟网关成功建立SSL连接，进入SSL VPN虚拟网关的登录页面。
- 用户认证：在登录页面输入用户名、密码后，虚拟网关将对该用户进行身份认证。虚拟网关验证用户身份的方式有很多种，包括本地认证、服务器认证、证书匿名认证、证书挑战认证等。
- 角色授权：用户身份认证通过后，虚拟网关会查询该用户所属的角色信息，然后再将该角色所拥有的资源链接推送给用户。角色代表了一类用户的资源访问权限，例如企业中总经理这个角色的资源访问权限和普通员工这个角色的资源访问权限是不一样的。
- 资源访问：用户点击虚拟网关资源列表中的链接就可以访问对应资源。

#### Web代理业务交互流程

- 远程用户通过域名（https://svn）来访问虚拟网关。
- 登录虚拟网关成功后，远程用户会在虚拟网关中看到自己有权访问的Web资源列表，然后单击要访问的资源链接。防火墙在将内网资源（http://website/resource.html）呈现给远程用户时，会改写该资源的URL。远程用户点击资源链接后，发送给防火墙的HTTPS链接请求就是虚拟网关改写以后的URL，改写后的URL实质上是由https://svn和http://website/resource.html这两个URL拼接而成。
- 防火墙收到上述URL后，会向Web Server重新发起一个HTTP请求，这个HTTP请求就是Web资源实际的URL（http://website/resource.html）。
- Web Server以HTTP方式向防火墙返回资源页面。
- 虚拟网关将Web Server返回的资源页面，再经过HTTPS方式转发给远程用户。

#### Web改写

- Web改写中的"改写"包含两层含义。第一层含义是加密，即远程用户在点击虚拟网关资源列表中的链接时，虚拟网关会将用户要访问的真实URL进行加密。第二层含义是适配。随着网络技术不断的发展，远程用户接入Internet的终端类型也变得丰富起来，如智能手机、PAD、便携机等越来越普及。这些不同的终端设备使用不同的操作系统和浏览器，这就使得它们在Web资源的支持上存在差异。为了解决终端类型差异对业务的影响，这就需要防火墙不仅能将内网Web资源转发给远程用户，而且还要对Web资源进行"改写"，使之能够适配这些不同的终端。

#### Web Link

- Web Link不会进行加密和适配，只做单纯转发远程用户的Web资源请求。

### SSL VPN业务-文件共享

- 在文件共享业务中防火墙起到了协议转换器的作用，以访问内网Windows文件服务器为例，具体实现过程如图所示。

> （原图：文件共享业务中防火墙作为协议转换器的实现过程）

### SSL VPN业务-端口转发

- 端口转发需要在客户端上运行一个ActiveX控件作为端口转发器，用于侦听指定端口上的连接。以用户Telnet到内网服务器为例，端口转发的实现过程如图所示。

> （原图：端口转发业务中ActiveX控件作为端口转发器的实现过程）

### SSL VPN业务-网络扩展

- 远程用户通过Web浏览器登录虚拟网关。
- 成功登录虚拟网关后启动网络扩展功能。启动网络扩展功能，会触发以下几个动作：
  - 远程用户与虚拟网关之间会建立一条SSL VPN隧道。
  - 远程用户本地PC会自动生成一个虚拟网卡。虚拟网关从地址池中随机选择一个IP地址，分配给远程用户的虚拟网卡，该地址作为远程用户与企业内网Server之间通信之用。有了该私网IP地址，远程用户就如同企业内网用户一样可以方便访问内网IP资源。
  - 虚拟网关向远程用户下发到达企业内网服务器的路由信息。虚拟网关会根据网络扩展业务中的配置，向远程用户下发不同的路由信息。
- 远程用户向企业内网的服务器发送业务请求报文，该报文通过SSL VPN隧道到达虚拟网关。
- 虚拟网关收到报文后进行解封装，并将解封装后的业务请求报文发送给内网服务器。
- 内网服务器响应远程用户的业务请求。
- 响应报文到达虚拟网关后进入SSL VPN隧道。

网络扩展业务报文封装与解封装过程：

- 业务请求报文（SSL封装）：源IP 6.6.6.6，源Port 443，目的IP 1.1.1.1，目的Port 6293，TCP，加密。
- 业务请求报文（SSL解封装）：源IP 192.168.1.1，源Port 5800，目的IP 10.1.1.2，目的Port 5060，UDP，DATA。
- 业务响应报文（SSL封装）：源IP 6.6.6.6，源Port 443，目的IP 1.1.1.1，目的Port 6293，TCP，加密。
- 业务响应报文（SSL解封装）：源IP 10.1.1.2，源Port 5060，目的IP 192.168.1.1，目的Port 5800，UDP，DATA。

## IPSec VPN配置举例

### 需求描述

- 两个网关之间通过IKE方式协商IPSec VPN隧道（采用预共享密钥认证），从而实现局域网之间安全地互访。
- 网络A和网络B通过防火墙A和B之间建立的IPSec隧道互联互通。
- 网络A属于10.1.1.0/24子网，通过接口GigabitEthernet0/0/3与防火墙A连接。
- 网络B属于10.1.2.0/24子网，通过接口GigabitEthernet0/0/3与防火墙B连接。
- 防火墙A和防火墙B路由可达。

> （原图：网络A（10.1.1.1/24）—防火墙A（GE0/0/3、GE0/0/1 1.1.3.1/24）—Internet—防火墙B（GE0/0/1 1.1.5.1/24、GE0/0/3）—网络B（10.1.2.1/24），防火墙A与防火墙B之间为IPSec隧道）

### 配置思路

- 完成接口基本配置。
- 配置安全策略，允许私网指定网段进行报文交互。
- 配置到对端内网的路由。
- 配置IPSec策略，包括配置IPSec策略的基本信息、配置待加密的数据流、配置安全提议的协商参数。

配置流程：

1. 基础配置：配置接口IP地址、配置接口加入安全区域。
2. 定义被保护的数据流（ACL）。
3. 配置IPSec安全提议。
4. 配置域间安全策略。
5. 配置IKE安全提议。
6. 配置到对端网络静态路由。
7. 配置并应用IPSec策略。

### 配置步骤

#### 定义被保护的数据流

- 防火墙A：配置高级ACL3000，允许10.1.1.0/24网段访问10.1.2.0/24网段。

```cli
[FW_A] acl 3000
[FW_A-acl-adv-3000] rule 5 permit ip source 10.1.1.0 0.0.0.255 destination 10.1.2.0 0.0.0.255
[FW_A-acl-adv-3000] quit
```

- 防火墙B：配置高级ACL3000，允许10.1.2.0/24网段访问10.1.1.0/24网段。

```cli
[FW_B] acl 3000
[FW_B-acl-adv-3000] rule 5 permit ip source 10.1.2.0 0.0.0.255 destination 10.1.1.0 0.0.0.255
[FW_B-acl-adv-3000] quit
```

#### 配置IPSec安全提议

防火墙A与防火墙B配置相同，缺省参数可不配置。

```cli
[FW_A] ipsec proposal tran1
[FW_A-ipsec-proposal-tran1] esp authentication-algorithm sha2-256
[FW_A-ipsec-proposal-tran1] esp encryption-algorithm aes-256
[FW_A-ipsec-proposal-tran1] quit
```

#### 配置IKE安全提议

防火墙A与防火墙B配置相同。

```cli
[FW_A] ike proposal 10
[FW_A-ike-proposal-10] authentication-method pre-share
[FW_A-ike-proposal-10] prf hmac-sha2-256
[FW_A-ike-proposal-10] encryption-algorithm aes-256
[FW_A-ike-proposal-10] dh group14
[FW_A-ike-proposal-10] integrity-algorithm hmac-sha2-256
[FW_A-ike-proposal-10] quit
```

#### 配置IKE peer与IPSec策略

防火墙A配置：

```cli
[FW_A] ike peer b
[FW_A-ike-peer-b] ike-proposal 10
[FW_A-ike-peer-b] remote-address 1.1.5.1
[FW_A-ike-peer-b] pre-shared-key Test!1234
[FW_A-ike-peer-b] quit
[FW_A] ipsec policy map1 10 isakmp
[FW_A-ipsec-policy-isakmp-map1-10] security acl 3000
[FW_A-ipsec-policy-isakmp-map1-10] proposal tran1
[FW_A-ipsec-policy-isakmp-map1-10] ike-peer b
[FW_A-ipsec-policy-isakmp-map1-10] quit
```

防火墙B配置：

```cli
[FW_B] ike peer a
[FW_B-ike-peer-a] ike-proposal 10
[FW_B-ike-peer-a] remote-address 1.1.3.1
[FW_B-ike-peer-a] pre-shared-key Test!1234
[FW_B-ike-peer-a] quit
[FW_B] ipsec policy map1 10 isakmp
[FW_B-ipsec-policy-isakmp-map1-10] security acl 3000
[FW_B-ipsec-policy-isakmp-map1-10] proposal tran1
[FW_B-ipsec-policy-isakmp-map1-10] ike-peer a
[FW_B-ipsec-policy-isakmp-map1-10] quit
```

#### 引用IPSec策略

- 防火墙A：在接口GigabitEthernet0/0/1上应用IPSec策略组map1。

```cli
[FW_A] interface GigabitEthernet 0/0/1
[FW_A-GigabitEthernet0/0/1] ipsec policy map1
[FW_A-GigabitEthernet0/0/1] quit
```

- 防火墙B：在接口GigabitEthernet0/0/1上应用IPSec策略组map1。

```cli
[FW_B] interface GigabitEthernet 0/0/1
[FW_B-GigabitEthernet0/0/1] ipsec policy map1
[FW_B-GigabitEthernet0/0/1] quit
```

## SSL VPN配置举例

### 需求描述

- 企业网络如图所示，企业希望移动办公用户通过Web代理访问企业Web服务器（Web Link）。
- 企业使用防火墙的本地认证对各部门的员工进行用户认证，通过认证的用户能够获得接入企业内部网络的权限。

> （原图：移动办公用户—Internet—防火墙（GE1/0/1 1.1.1.1/24、GE1/0/2 10.2.0.1/24）—总部Web服务器（10.2.0.2/24），移动办公用户与防火墙之间为SSL VPN隧道）

### 配置思路

1. 基础配置：配置接口IP地址、配置接口加入安全区域。
2. 配置用户与认证：配置认证域，创建用户组和用户。
3. 配置SSL VPN虚拟网关。
4. 启用Web Link功能：启用Web Link功能，配置Web Link资源。
5. 配置角色授权：将用户组添加到虚拟网关中，创建角色，将角色与用户组绑定，同时启用Web Link功能。
6. 配置安全策略：允许移动办公用户登录SSL VPN网关；允许出差员工访问Web代理资源。

### 配置步骤

#### 配置用户与认证

用户user0001所属的用户组为"/default/group1"，认证类型为本地认证，密码为Password@123。需要注意，在新建用户user0001之前，应先新建用户组"/default/group1"，这样才能在新建用户时引用已创建好的用户组。

命令行配置如下：

```cli
[FW] aaa
[FW-aaa] domain default
[FW-aaa-domain-default] authentication-scheme default
[FW-aaa-domain-default] service-type ssl-vpn
[FW-aaa-domain-default] quit
[FW-aaa] quit
[FW] user-manage group /default/group1
[FW-usergroup-/default/group1] quit
[FW] user-manage user user0001 domain default
[FW-localuser-user0001] password Password@123
[FW-localuser-user0001] parent-group /default/group1
[FW-localuser-user0001] quit
```

#### 配置SSL VPN虚拟网关

命令行配置如下：

```cli
[FW] v-gateway gateway interface GigabitEthernet 0/0/1 private
[FW] v-gateway gateway udp-port 443
[FW] v-gateway gateway authentication-domain default
```

#### 启用Web Link功能

命令行配置如下：

```cli
[FW] v-gateway gateway
[FW-gateway] service
[FW-gateway-service] web-proxy enable
[FW-gateway-service] web-proxy web-link enable
```

#### 配置Web Link资源

命令行配置如下：

```cli
[FW-gateway-service] web-proxy link-resource Web-Server
```

资源URL为：http://10.2.0.2:8080，show-link方式。

#### 配置角色授权

命令行配置如下：

```cli
[FW-gateway] vpndb
[FW-gateway-vpndb] group /default/sslvpn
[FW-gateway-vpndb] quit
[FW-gateway] role
[FW-gateway-role] role role
[FW-gateway-role] role role group /default/sslvpn
[FW-gateway-role] role role web-proxy enable
[FW-gateway-role] role role web-proxy resource Web-Server
[FW-gateway-role] quit
[FW-gateway] quit
```

## 思考题

1.（判断题）IPSec采用的是非对称加密算法加密用户数据的方式来保证信息传递机密性的。
   A.正确  B.错误

2.（多选题）以下哪些项属于防火墙SSL VPN的主要功能？
   A.端口转发  B.网络扩展  C.文件共享  D.Web代理

答案：1.B  2.ABCD

## 本章总结

- 本课程简要介绍了不同加密技术的应用场景，系统介绍了VPN技术的产生背景、加解密的工作原理，以及不同VPN技术的配置方法和典型案例。
- 通过本课程的学习，搭配基于实际环境的练习，您将能独立完成IPSec VPN、SSL VPN等多种VPN技术的配置。
