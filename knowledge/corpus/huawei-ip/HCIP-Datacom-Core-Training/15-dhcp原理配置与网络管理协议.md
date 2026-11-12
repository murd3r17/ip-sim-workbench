---
doc_id: "hcip-datacom-core-training-15"
title: "DHCP 原理配置与网络管理协议"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 15
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# DHCP 原理配置与网络管理协议

## DHCP 优点与角色

DHCP 相对于手工配置有如下优点：

- 效率高
- 灵活性强
- 易于管理

**DHCP 服务器**响应请求；**DHCP 客户端**发起请求。

网络终端设备，例如主机、打印机、笔记本电脑、手机和 AP，作为 DHCP 客户端，向 DHCP 服务器请求分配相关网络参数。DHCP 服务器响应 DHCP 客户端请求进行动态分配。

### 课程内容

1. DHCP 产生背景
2. DHCP 工作原理与配置
3. DHCP Relay 工作原理与配置

## DHCP 客户端首次接入网络的工作原理

1. **发现阶段**：DHCP 客户端发现 DHCP 服务器的阶段。DHCP 客户端发送 DHCP DISCOVER 报文来发现 DHCP 服务器。DHCP DISCOVER 报文中携带了客户端的 MAC 地址、需要请求的参数列表选项、广播标志位等信息。
2. **提供阶段**：DHCP 服务器提供网络配置信息的阶段。服务器接收到 DHCP DISCOVER 报文后，选择跟接收 DHCP DISCOVER 报文接口的 IP 地址处于同一网段的地址池，并且从中选择一个可用的 IP 地址，然后通过 DHCP OFFER 报文发送给 DHCP 客户端。
3. **选择阶段**：DHCP 客户端选择 IP 地址的阶段。如果有多个 DHCP 服务器向 DHCP 客户端回应 DHCP OFFER 报文，则 DHCP 客户端一般只接收第一个收到的 DHCP OFFER 报文，然后以广播方式发送 DHCP REQUEST 报文，该报文中包含客户端想选择的 DHCP 服务器标识符和客户端 IP 地址。
4. **确认阶段**：DHCP 服务器确认所分配 IP 地址的阶段。DHCP 客户端收到 DHCP ACK 报文，会广播发送免费 ARP 报文，探测本网段是否有其他终端使用服务器分配的 IP 地址。

报文交互概要：

| 阶段 | 报文 | 发送方式 |
|------|------|----------|
| 发现阶段 | DHCP DISCOVER | 广播 |
| 提供阶段 | DHCP OFFER | 单播/广播 |
| 选择阶段 | DHCP REQUEST | 广播 |
| 确认阶段 | DHCP ACK | 单播 |

### IP 地址冲突处理

在确认阶段，两种情况可能出现 IP 地址的冲突：

- DHCP 服务器收到 DHCP DISCOVER 报文时，给客户端分配 IP 地址前会发送 Ping 探测，如果能 Ping 通则标识该地址不可用，并选择其他 IP 地址分配给客户端。
- DHCP 客户端获取 IP 地址成功后，会立即发送免费 ARP 报文，如果收到响应，则发送 DHCP DECLINE 报文通知 DHCP 服务器该 IP 地址冲突，DHCP 服务器标识该地址不可用，客户端发送 DHCP DISCOVER 报文重新申请 IP 地址。

## DHCP 报文格式

重要字段说明：

- **Op（op code）**：表示报文的类型，取值为 1 或 2。1：客户端请求报文；2：服务器响应报文。
- **Secs（seconds）**：由客户端填充，表示从客户端开始获得 IP 地址或 IP 地址续借后所使用了的秒数。
- **Flags**：客户端请求服务器发送响应报文的形式，只有最高位有意义，其余 15 位置 0。最高位为 0 时请求发送单播响应，最高位为 1 时请求发送广播响应。
- **Yiaddr（your client IP address）**：表示服务器分配给客户端的 IP 地址。当服务器进行 DHCP 响应时，将分配给客户端的 IP 地址填入此字段。
- **Siaddr（server IP address）**：DHCP 服务器的 IP 地址。
- **Chaddr（client hardware address）**：客户端的 MAC 地址。
- **Options**：DHCP 通过此字段包含了服务器分配给终端的配置信息。

其它字段：

- **Htype（hardware type）**：表示硬件地址的类型。
- **Hlen（hardware length）**：表示硬件地址的长度。
- **Hops**：表示当前 DHCP 报文经过的 DHCP Relay 数目。该字段由客户端设置为 0，每经过一个 DHCP Relay 时，该字段加 1。此字段的作用是限制 DHCP 报文所经过的 DHCP Relay 数目。
- **Xid**：表示 DHCP 客户端选取的随机数，使 DHCP 服务器的回复与 DHCP 客户端的报文相关联。
- **Sname（server host name）**：表示客户端获取配置信息的服务器名字。此字段由 DHCP 服务器填写，是可选的。如果填写，必须是一个以 0 结尾的字符串。
- **File（file name）**：表示客户端启动 DHCP 相关配置的文件名。此字段由 DHCP 服务器填写，随着 DHCP 地址分配的同时下发至客户端。本字段是可选的，如果填写，必须是一个以 0 结尾的字符串。

### Options 字段

DHCP 报文中 Options 字段为可变长度字段，最多为 312 Byte，此字段包含了 DHCP 报文类型，服务器分配给终端的配置信息，如网关 IP 地址、DNS 服务器的 IP 地址、客户端可以使用 IP 地址的有效租期等信息。

Options 字段由 Type、Length 和 Value 三部分组成。其中 Type 字段取值范围 1~255。常见的 Options 如下表所示：

| Type / 选项 | 作用 |
|-------------|------|
| Subnet Mask | 设置子网掩码选项 |
| Router（网关） | 设置网关地址选项 |
| Requested IP Address | 设置请求 IP 地址选项 |
| IP Address Lease Time | 设置 IP 地址租约时间选项 |
| Message Type | 设置 DHCP 消息类型 |
| DHCP Server Identifier | 设置服务器标识 |
| Parameter Request List | 设置请求选项列表。客户端利用该选项指明需要从服务器获取哪些网络配置参数 |
| Renewal Time Value | 设置续约 T1 时间，一般是租期时间的 50% |
| Rebinding Time Value | 设置续约 T2 时间，一般是租期时间的 87.5% |

### DHCP 的消息类型

DHCP 报文通过 Options 选项中的 Type=53 来表示 DHCP 的报文类型。当 Type=53，Length=1，Value 取值从 01 到 08 分别表示不同的 DHCP 报文类型：

| Value | 报文类型 | 说明 |
|-------|----------|------|
| 1 | DHCP DISCOVER | DHCP 客户端首次登录网络时进行 DHCP 交互过程发送的第一个消息，用来寻找 DHCP 服务器 |
| 2 | DHCP OFFER | DHCP 服务器用来响应 DHCP DISCOVER 消息，此消息携带了各种配置信息 |
| 3 | DHCP REQUEST | DHCP 客户端广播请求回应 DHCP 服务器 OFFER 消息；DHCP 客户端重启广播确认之前的 IP 地址等配置信息；续租 |
| 4 | DHCP DECLINE | 当客户端发现服务器分配给它的 IP 地址发生冲突时会通过发送此消息来通知服务器 |
| 5 | DHCP ACK | DHCP 服务器对客户端的 DHCP REQUEST 消息的确认响应消息 |
| 6 | DHCP NAK | 服务器对客户端的 DHCP REQUEST 消息的拒绝响应消息 |
| 7 | DHCP RELEASE | 客户端可通过发送此消息主动释放服务器分配给它的 IP 地址 |
| 8 | DHCP INFORM | DHCP 客户端获取 IP 地址后，如果需要向 DHCP 服务器获取更为详细的配置信息（网关地址、DNS 服务器地址），则向 DHCP 服务器发送 DHCP INFORM 请求消息 |

### Option 82 / Option 43

管理员可以从 Option 82 中获得 DHCP 客户端的信息，例如 DHCP 客户端所连接交换机端口的 VLAN ID、二层端口号、中继设备的 MAC 地址等。

**Option 43** 称为厂商特定信息选项。DHCP 服务器和 DHCP 客户端通过 Option 43 交换厂商特定的信息。当 DHCP 服务器接收到请求 Option 43 信息的 DHCP 请求报文（Option 55 中带有 Option 43 参数）后，将在回复报文中携带 Option 43，为 DHCP 客户端分配厂商指定的信息。在 WLAN 组网中，AP 作为 DHCP 客户端，DHCP 服务器可以为 AP 指定 AC 的 IP 地址，以方便 AP 与 AC 建立连接。

目前 Option 82 中常用的 Sub-Option 如下：

- **Sub-Option 1**：代理电路 id（circuit id）子项。通常在 DHCP 中继设备上配置，定义了在传输报文的时候要携带 DHCP 客户端所连接交换机端口的 vlan-id 及二层端口号。通常 Sub-Option 1 与 Sub-Option 2 子选项要共同使用来标识 DHCP 源端的信息。
- **Sub-Option 2**：代理远程 id（remote id）子项。通常在 DHCP 中继设备上配置，定义了在传输报文的时候要携带中继设备的 mac 地址信息。
- **Sub-Option 5**：链路选择（link selection）子项，该选项中包含了 DHCP 中继添加的 IP 地址。这样 DHCP server 在分配 IP 地址给 DHCP 客户端的时候就可以分配与该地址同网段的 IP 地址。

## DHCP 地址续租

- 当租期达到 50%（T1）时，DHCP 客户端会自动以单播的方式向 DHCP 服务器发送 DHCP REQUEST 报文，请求更新 IP 地址租期。如果收到 DHCP 服务器回应的 DHCP ACK 报文，则租期更新成功。
- 当租期达到 87.5%（T2）时，如果仍未收到 DHCP 服务器的应答，DHCP 客户端会自动以广播的方式向 DHCP 服务器发送 DHCP REQUEST 报文，请求更新 IP 地址租期。如果收到 DHCP 服务器回应的 DHCP ACK 报文，则租期更新成功。
- 如果租期时间到时都没有收到服务器的回应，客户端停止使用此 IP 地址，重新发送 DHCP DISCOVER 报文请求新的 IP 地址。

DHCP 服务器给每个分配给客户端的 IP 地址定义一个使用期限，该使用期限被称为租期。在租期到期前，DHCP 客户端如果仍需要使用该 IP 地址，可以请求延长租期；如果不需要，可以主动释放该 IP 地址。在没有其他空闲地址可用的情况下，DHCP 服务器会把客户端主动释放的 IP 地址分配给其他客户端。

DHCP 客户端无论在 T1 还是 T2 时刻发送 DHCP REQUEST 报文后，如果收到 DHCP NAK 报文，则重新发送 DHCP DISCOVER 报文请求新的 IP 地址。

客户端在租期时间到之前，如果用户不想使用分配的 IP 地址（例如客户端网络位置需要变更），会触发 DHCP 客户端向 DHCP 服务器发送 DHCP RELEASE 报文，通知 DHCP 服务器释放 IP 地址的租期。DHCP 服务器会保留这个 DHCP 客户端的配置信息，将 IP 地址列为曾经分配过的 IP 地址中，以便后续重新分配给该客户端或其他客户端。客户端可以通过发送 DHCP INFORM 报文向服务器请求更新配置信息。

思考：为什么每次电脑被分配的 IP 地址都是同一个呢？——与地址重用及分配顺序有关。

## DHCP 客户端重用曾经使用过的地址

DHCP 客户端非首次接入网络时，可以重用曾经使用过的地址。例如，网络中的主机作为 DHCP 客户端，在关机再开机的过程中，需要重新获取相关网络参数，则可以请求分配曾经使用过的 IP 地址。是否支持重用曾经使用过的 IP 地址，因不同客户端而异。

1. **选择阶段**：客户端广播发送包含前一次分配的 IP 地址的 DHCP REQUEST 报文，报文中的 Option 50（请求的 IP 地址选项）字段填入曾经使用过的 IP 地址。
2. **确认阶段**：DHCP 服务器收到 DHCP REQUEST 报文后，根据 DHCP REQUEST 报文中携带的 MAC 地址来查找有没有相应的租约记录。如果有则返回 DHCP ACK 报文，通知 DHCP 客户端可以继续使用这个 IP 地址，如果没有租约记录，则不响应。

## DHCP 分配 IP 地址顺序

DHCP 服务器按照如下次序为客户端选择 IP 地址：

1. DHCP 服务器的数据库中与客户端 MAC 地址静态绑定的 IP 地址。
2. 客户端以前曾经使用过的 IP 地址，即客户端发送的请求报文中请求 IP 地址选项的地址。
3. 在 DHCP 地址池中，顺序查找可供分配的空闲 IP 地址，最先找到的 IP 地址。
4. 如果在 DHCP 地址池中未找到可供分配的空闲 IP 地址，则依次查询超过租期、发生冲突的 IP 地址，如果找到可用的 IP 地址，则进行分配，否则报告错误。

顺序示意：MAC 静态绑定的 IP → 已使用过的 IP → 空闲状态的 IP → 超过租期的 IP → 产生冲突的 IP。

## DHCP 配置命令介绍

### （1）全局地址池

```cli
[Huawei] ip pool ip-pool-name
```

1. 创建全局地址池

```cli
[Huawei-ip-pool-HW] gateway-list ip-address
```

2. 配置 DHCP 客户端的网关地址

```cli
[Huawei-ip-pool-HW] network ip-address [ mask { mask | mask-length } ]
```

3. 配置全局地址池可动态分配的 IP 地址范围

```cli
[Huawei-ip-pool-HW] excluded-ip-address start-ip-address [ end-ip-address ]
```

4. 配置地址池中不参与自动分配的 IP 地址

```cli
[Huawei-ip-pool-HW] lease { day day [ hour hour [ minute minute ] ] | unlimited }
```

5. 配置地址池的地址租期

```cli
[Huawei-ip-pool-HW] static-bind ip-address ip-address mac-address mac-address [ option-template template-name | description description ]
```

6. 配置为指定 DHCP Client 分配固定 IP 地址

此处以 ip pool 的名字为 HW 举例说明。缺省情况下，没有配置为指定 DHCP Client 分配固定 IP 地址。

### （2）接口地址池

```cli
[Huawei] interface interface-type interface-number
```

1. 配置基于接口方式的地址池

```cli
[Huawei-GigabitEthernet0/0/1] dhcp server gateway-list ip-address
```

2. 配置接口地址池的网关 IP 地址

```cli
[Huawei-GigabitEthernet0/0/1] dhcp server static-bind ip-address ip-address mac-address mac-address [ description description ]
```

3. 配置为指定 DHCP Client 分配固定 IP 地址

```cli
[Huawei-GigabitEthernet0/0/1] dhcp server excluded-ip-address start-ip-address [ end-ip-address ]
```

4. 配置地址池中不参与自动分配的 IP 地址

```cli
[Huawei-GigabitEthernet0/0/1] dhcp server lease { day day [ hour hour [ minute minute ] ] | unlimited }
```

5. 配置地址池的地址租期

```cli
[Huawei-GigabitEthernet0/0/1] ip address ip-address { mask | mask-length }
```

接口地址所属的 IP 地址网段即为接口地址池。并且接口地址的掩码不能配置为 31，否则会导致接口地址池配置失败。此处以接口 GigabitEthernet0/0/1 举例说明。

## DHCP 配置举例

**实验要求：**

- 采用基于全局地址池的方式为 PC1 分配 IP 地址。
- 采用基于接口地址池的方式为 PC2 和 PC3 分配 IP 地址，且 PC3 获取固定的 IP 地址。

> （原图：R1 作为 DHCP 服务器；SW1—PC1 接 GE0/0/0；SW2—PC2/PC3 接 GE0/0/1；PC3 IP `192.168.2.2/24`，MAC `00e0-fc00-00aa`。）

全局地址池侧：

```cli
[R1] dhcp enable
[R1] ip pool HW
[R1-ip-pool-HW] gateway-list 192.168.1.1
[R1-ip-pool-HW] network 192.168.1.0 mask 24
[R1-ip-pool-HW] excluded-ip-address 192.168.1.200 192.168.1.254
[R1] interface GigabitEthernet 0/0/0
[R1-GigabitEthernet0/0/0] dhcp select global
```

接口地址池侧：

```cli
[R1] interface GigabitEthernet 0/0/1
[R1-GigabitEthernet0/0/1] ip address 192.168.2.1 24
[R1-GigabitEthernet0/0/1] dhcp select interface
[R1-GigabitEthernet0/0/1] dhcp server excluded-ip-address 192.168.2.254
[R1-GigabitEthernet0/0/1] dhcp server static-bind ip-address 192.168.2.2 mac-address 00e0-fc00-00aa
```

### DHCP 配置结果

```cli
[R1] display ip pool
Pool-name      : HW
Gateway-0   : 192.168.1.1
Mask          : 255.255.255.0
IP address Statistic
Total: ...       Idle: 198
Expired: 0        Conflict: 0 Disable: 55
```

根据 IP 地址的使用情况，地址池中的 IP 地址可以分为多种状态：

- **Used**：表示此 IP 地址已使用。
- **Idle**：表示此 IP 地址处于空闲状态。
- **Expired**：表示此 IP 地址租期已过，处于空闲状态。
- **Conflict**：表示此 IP 地址与网络上其他地址冲突。
- **Disable**：表示此 IP 地址无法使用。

PC3 获取到了静态绑定的 IP 地址示例：

```cli
PC3> ipconfig
IPv4 address......................: 192.168.2.2
Subnet mask.......................: 255.255.255.0
Gateway...........................: 192.168.2.1
```

## DHCP Relay

DHCP Relay 即 DHCP 中继，它是为解决 DHCP 服务器和 DHCP 客户端不在同一个广播域而提出的，提供了对 DHCP 广播报文的中继转发功能，能够把 DHCP 客户端的广播报文“透明地”传送到其它广播域的 DHCP 服务器上，同样也能够收到 DHCP 服务器端的应答报文“透明地”传送到其它广播域的 DHCP 客户端。

> （原图：Client A/B 分属不同二层广播域，经中继到达 DHCP Server 所在广播域。）

### DHCP Relay 报文格式

DHCP Relay 主要负责转发 DHCP 客户端与 DHCP 服务器之间的 DHCP 报文，所以 DHCP Relay 的报文格式只是把 DHCP 的报文部分字段做了相应的修改，报文格式没有发生变化：

- **Hops**：表示当前的 DHCP 报文经过的 DHCP 中继的数目。该字段由客户端或服务器设置为 0，每经过一个 DHCP 中继时，该字段加 1。
- **Giaddr（gateway IP address）**：表示第一个 DHCP 中继的 IP 地址。当客户端发出 DHCP 请求时，第一个 DHCP 中继在将 DHCP 请求报文转发给 DHCP 服务器时，会把自己的 IP 地址填入此字段。

Hops 字段的作用是限制 DHCP 报文所经过的 DHCP 中继数目。服务器和客户端之间的 DHCP 中继数目不能超过 16 个，也就是 Hops 值不能大于 16，否则 DHCP 报文将被丢弃。

Giaddr 字段：DHCP 服务器会根据此字段来判断出客户端所在的网段地址，从而选择合适的地址池，为客户端分配该网段的 IP 地址。服务器还会根据此地址将响应报文发送给此 DHCP 中继，再由 DHCP 中继将此报文转发给客户端。若在到达 DHCP 服务器前经过了多个 DHCP 中继，该字段作为客户端所在的网段的标记，填充了第一个 DHCP 中继的 IP 地址后不会再变更，只是每经过一个 DHCP 中继，hops 字段的数值会加 1。

### DHCP Relay 工作原理

有中继场景时 DHCP 客户端首次接入网络的工作原理：

1. **发现阶段**：DHCP 中继接收到 DHCP 客户端广播发送的 DHCP DISCOVER 报文后，通过路由转发将 DHCP 报文单播发送到 DHCP 服务器或下一跳中继。
2. **提供阶段**：DHCP 服务器根据 DHCP DISCOVER 报文中的 Giaddr 字段选择地址池为客户端分配相关网络参数，DHCP 中继收到 DHCP OFFER 报文后，以单播或广播方式发送给 DHCP Client。
3. **选择阶段**：中继接收到来自客户端的 DHCP REQUEST 报文的处理过程同“发现阶段”。
4. **确认阶段**：中继接收到来自服务器的 DHCP ACK 报文的处理过程同“提供阶段”。

DHCP 中继收到 DHCP DISCOVER 报文后，处理规则为：

- 检查 DHCP 报文中的 Hops 字段，如果大于 16，则丢弃 DHCP 报文；否则，将 Hops 字段加 1（表明经过一次 DHCP 中继），并继续下面的操作。
- 检查 DHCP 报文中的 Giaddr 字段。如果是 0，将 Giaddr 字段设置为接收 DHCP DISCOVER 报文的接口 IP 地址。如果不是 0，则不修改该字段，继续下面的操作。
- 将 DHCP 报文的目的 IP 地址改为 DHCP 服务器或下一跳中继的 IP 地址，源地址改为中继连接客户端的接口地址，通过路由转发将 DHCP 报文单播发送到 DHCP 服务器或下一跳中继。

DHCP 服务器接收到 DHCP DISCOVER 报文后，选择与报文中 Giaddr 字段为同一网段的地址池，并为客户端分配 IP 地址等参数，然后向 Giaddr 字段标识的 DHCP 中继单播发送 DHCP OFFER 报文。DHCP 中继收到 DHCP OFFER 报文后，会进行如下处理：

- 检查报文中的 Giaddr 字段，如果不是接口的地址，则丢弃该报文；否则，继续下面的操作。
- DHCP 中继检查报文的广播标志位。如果广播标志位为 1，则将 DHCP OFFER 报文广播发送给 DHCP 客户端；否则将 DHCP OFFER 报文单播发送给 DHCP 客户端。

### DHCP Relay 配置命令

```cli
[Huawei-GigabitEthernet0/0/0] dhcp select relay
```

1. 使能接口的 DHCP 中继功能

```cli
[Huawei-GigabitEthernet0/0/0] dhcp relay server-ip ip-address
```

2. 在接口视图下配置 DHCP 服务器的 IP 地址

```cli
[Huawei] dhcp server group group-name
```

3. 创建 DHCP 服务器组

```cli
[Huawei-dhcp-server-group-HW] dhcp-server ip-address [ ip-address-index ]
```

4. 在 DHCP 服务器组中配置 DHCP 服务器成员

```cli
[Huawei-GigabitEthernet0/0/0] dhcp relay server-select group-name
```

5. 配置接口应用的 DHCP 服务器组

```cli
[Huawei-GigabitEthernet0/0/0] ip address dhcp-alloc
```

6. 开启接口下的 DHCP Client 功能

### DHCP Relay 配置举例

**配置要求：**

- R1 通过 DHCP 获取 IP 地址。
- R2 的 GE0/0/0 接口开启 DHCP Relay 功能，并且指定 DHCP Server 的 IP 地址为 `10.1.1.2`。
- R3 创建地址池名字为 `HW-1`，地址范围为 `192.168.1.0/24`，网关为 `192.168.1.1`。

> （原图：R1（DHCP Client）—R2（DHCP Relay）—R3（DHCP Server）；网段 `192.168.1.0/24` 与 `10.1.1.0/24`。）

R1、R2 配置如下（各设备配置 DHCP 前需要在全局视图下通过 `dhcp enable` 命令开启 DHCP 功能）：

```cli
[R2] dhcp server group HW
[R2-dhcp-server-group-HW] dhcp-server 10.1.1.2
[R2-dhcp-server-group-HW] quit
[R2] interface GigabitEthernet 0/0/1
[R2-GigabitEthernet0/0/1] ip address 10.1.1.1 24
[R2-GigabitEthernet0/0/1] quit
[R2] interface GigabitEthernet 0/0/0
[R2-GigabitEthernet0/0/0] ip address 192.168.1.1 24
[R2-GigabitEthernet0/0/0] dhcp select relay
[R2-GigabitEthernet0/0/0] dhcp relay server-select HW
[R2-GigabitEthernet0/0/0] quit
[R1] interface GigabitEthernet0/0/0
[R1-GigabitEthernet0/0/0] ip address dhcp-alloc
[R1-GigabitEthernet0/0/0] quit
```

R3 配置如下：

```cli
[R3] ip pool HW-1
[R3-ip-pool-HW-1] network 192.168.1.0 mask 24
[R3-ip-pool-HW-1] gateway-list 192.168.1.1
[R3-ip-pool-HW-1] quit
[R3] interface GigabitEthernet 0/0/1
[R3-GigabitEthernet0/0/1] ip address 10.1.1.2 24
[R3-GigabitEthernet0/0/1] dhcp select global
[R3-GigabitEthernet0/0/1] quit
[R3] ip route-static 192.168.1.0 255.255.255.0 10.1.1.1
```

### DHCP Relay 配置验证

```cli
<R2> display dhcp relay all
DHCP relay agent running information of interface GigabitEthernet0/0/0 :
Server group name : HW
Gateway address in use                     : 192.168.1.1
```

```cli
<R2> display dhcp relay statistics
The statistics of DHCP RELAY:
DHCP packets received from clients    : 2
DHCP packets sent to clients          : 2
DHCP packets received from servers    : 2
DHCP packets sent to servers          : 2
……
```

```cli
<R1> display dhcp client
DHCP client lease information on interface GigabitEthernet0/0/0 :
Current machine state : Bound
Internet address assigned via : DHCP
Physical address : 00e0-fce6-4691
IP address : 192.168.1.254
Subnet mask : 255.255.255.0
Gateway ip address : 192.168.1.1
DHCP server : 10.1.1.2
……
```

从上图中可以看到 R1 的 GE0/0/0 接口已获取到 IP 地址和网关地址；R2 的 GE0/0/0 接口开启了 DHCP Relay 功能，且 R2 作为 DHCP Relay 分别和 DHCP Client、DHCP Server 交互报文。

### 思考题（DHCP）

1. （单选题）DHCP 客户端向 DHCP Server 进行续租时会发送哪种报文？A. DHCP DISCOVER B. DHCP OFFER C. DHCP REQUEST D. DHCP ACK
2. （单选题）以下哪条命令可以开启路由器接口的 DHCP 中继功能？A. dhcp select server B. dhcp select global C. dhcp select interface D. dhcp select relay

参考答案：1. C  2. D

---

## 网络管理协议介绍

### 前言

随着人工智能、大数据、云计算等新技术快速发展，未来各行业将面临数字化转型，企业业务随着数字化转型也变得丰富多样，使网络管理成为网络管理员面临的最具挑战的问题之一。我们无法仅依赖人手动来完成整个的网络管理的工作，迫切的需要一种自动化和智能化的工具协助我们管理网络中的设备和资源。

本次课程，将简要介绍网络管理的发展历程及网络管理的相关概念，同时会着重介绍网络管理中使用到的不同的协议以及它们的使用场景。最后，简要介绍网络管理的典型应用案例。

### 学习目标

学完本课程后，您将能够：

- 阐释网络管理的发展趋势及功能特征
- 阐释网络管理协议的功能
- 阐释不同网络管理协议的机制和应用场景的异同点
- 阐释网络管理协议的应用场景

### 课程内容

1. 网络管理的发展历程
2. 网络管理的功能特征
3. 网络管理的协议分类
4. 网络管理的应用场景

### 网络管理的发展历程

随着互联网产业的飞速发展，网络面临巨大变革，多业务融合成为未来网络的主流趋势。网络的融合需要管理的融合，统一网管能实现多业务、多设备的统一集中管理。

人工智能、大数据、云计算等新技术正在快速发展，未来十年各行业将面临数字化转型，企业业务随着数字化转型也变得丰富多样。因此，数字化带来网络模型的变化，传统的网络管理模式已经不能适应数字化业务带来的新需求。传统网络的建设、管理和运维手段已无法满足数字化带来的新的网络需求。

**OPEX（Operating Expense，运营支出）**：指企业运行付出的各种支出成本，包括维护费用、营销费用、人工成本以及折旧。

根据行业知名分析机构在 2019 年 4 月发布的关于 AI 和自动化提高网络可靠性的报告中指出，到 2022 年，将会有 65% 的企业在园区网络部署网络自动化技术，而当时这个比例只有 17%。

**管理自动化**：正如家用洗衣机一样，从手动到半自动，到今天的全自动甚至是智能洗衣，让人人都能操作一个复杂的机器完成复杂的任务。对于网络管理也是如此，从基于命令行的逐台设备的配置与管理，到基于图形化界面的管理控制系统，到今天基于业务语言对网络进行自动化配置。从网络管理的视角，企业网络管理将几乎 1/3 的时间花费在网络的规划、部署上。未来网络自动化有两个层面：

- **全生命周期的自动化**：包括自动化工具是否能从网络的规划、部署、策略发放、网络状态监测和维护以及管理的全生命周期，均实现自动化。
- **整网自动化**：包括企业的 LAN、WLAN、以及 WAN 网络是否能够进行集中式地管理和策略配置，是否能从全局视角定义基于用户身份和应用类型的业务策略。

**运维智能化**：智能化是网络管理运维的更高级别能力。以前，网络运维工作很简单，主要关注网络和设备的 KPI 指标，无法感知用户体验和业务质量。而今天，网络连接的质量直接影响到了业务的质量，从而影响了企业的运作效率。甚至在部分工业和生产场景，因不同业务的需要，网络质量有了差异化的要求，每终端的带宽、时延、丢包、无线漫游的切换时间仅依托以网元为中心的运维系统是无法完成如此复杂的工作。

### 什么是网络管理？

网络管理，简单地说是对网络的管理，是一个网络的基本诉求。当前，用户能够通过各种协议、工具、应用或设备来实现对网络的管理，其管理对象包括网络中的硬件及软件。

网络管理的目标是实现对网络软硬件的监控、测试、配置、分析、评价及控制等，确保网络运行正常。

### 网络管理的典型架构

通常情况下，网络管理系统具有相同的基本体系结构。该体系结构包含两个关键元素：

- 管理设备，也被称为网络管理站。
- 被管理设备，也被称为代理设备。

> （原图：网络管理站经 SNMP/NETCONF/Telemetry 等协议与多台被管理设备上的 Agent 交互。）

### 网络管理模型

- **组织结构模型**：定义管理者、代理和被管理对象。它描述了网络管理系统的组件，组件的功能和基础架构。
- **信息模型**：与信息结构和存储有关。它指定用于描述被管理对象及其关系的信息库。管理信息结构（SMI）定义了存储在管理信息库（MIB）中的管理信息的语法和语义。代理进程和管理器进程都使用 MIB 进行管理信息交换和存储。
- **通信模型**：处理代理与管理者之间以及管理者之间交换信息的方式。通信模型中包含三个关键元素：传输协议，应用程序协议和要传达的实际消息。
- **功能模型**：包括网络管理的五个功能区域：配置管理、性能管理、故障管理、安全管理和计费管理。

### OSI 五大功能模型

- **配置管理（Configuration Management）**：涉及初始化网络，提供网络资源和服务以及监视和控制网络。更具体地说，配置管理的职责包括在网络运行期间设置，维护，添加和更新组件之间的关系以及组件的状态。配置管理包括设备配置和网络配置。设备配置可以在本地或远程执行。自动化的网络配置，例如动态主机配置协议（DHCP）和域名服务（DNS）在网络管理中发挥关键作用。
- **性能管理（Performance Management）**：与评估和报告被管理网络对象的行为和有效性有关。网络监视系统可以测量和显示网络状态，例如收集有关流量，网络可用性，响应时间和吞吐量的统计信息。
- **故障管理（Fault Management）**：涉及检测，隔离和纠正可能导致 OSI 网络故障的异常操作。故障管理的主要目标是确保网络始终可用，并在发生故障时尽快将其修复。
- **安全管理（Security Management）**：可以保护网络和系统免受未经授权的访问和安全攻击。安全管理机制包括身份验证，加密和授权。安全管理还涉及加密密钥以及其他与安全相关的信息的生成，分发和存储。安全管理可以包括提供实时事件监视和事件日志的安全系统，例如防火墙和入侵检测系统。
- **计费管理（Accounting Management）**：可以计量被管理对象的使用费用，并确定这种使用的成本。该度量可能包括消耗的资源，用于收集会计数据的设施以及为客户使用的服务设置计费参数，维护用于计费目的的数据库，以及准备资源使用情况和计费报告。

### 协议分类概览

| 协议 | 配置管理 | 监控管理 |
|------|----------|----------|
| CLI | 支持 | 支持 |
| SNMP | Set 功能 | Trap 功能 |
| NETCONF | Edit 功能 | Get 功能 |

### CLI / Telnet / SSH

网络管理员可以采用 CLI 对设备进行配置和网络监控，操作简单便捷，一旦进行大规模部署，就必须借助于自动化工具来进行批量配置。

**Telnet**：使用专用的 TCP 端口号 23，它不是一种安全通信协议，通过网络/互联网传输明文格式的数据，包括密码。Telnet 中没有使用任何验证策略及数据加密方法。

**SSH（Secure Shell）**：使用专用的 TCP 端口号 22，它是一种非常安全的协议，通过网络/互联网传输加密格式的数据，一旦经过加密就极难解压和读取该数据。SSH 还使用公钥用于对访问者的用户身份验证，这种方式提供了更高的安全性。

Telnet 和 SSH 是两种远程管理设备的方式，其中 SSH 连接方式较 Telnet 更为安全，因此目前网络都会要求部署 SSH。

### SNMP 相关角色

- **网络管理站（NMS）**：向被管理设备发送各种查询报文，以及接收被管理设备发送的告警。
- **被管理设备（Devices）**：网络中的各种接受网管的设备。
- **代理（Agent）**：驻留在被管理设备上的一个进程。作用包括：
  - 接收、解析来自网管站的查询报文。
  - 根据报文类型对管理变量进行 Read 或 Write 操作，并生成响应报文，返回给网管站。
  - 根据各协议模块对告警触发条件的定义，当发生某个事件（如端口 UP/DOWN，STP 拓扑变更、OSPF 邻居关系 DOWN 掉等）的时候，主动触发一个告警，向网管站报告该事件。
- **MIB（Management Information Base）**：是一个数据库，指明了被管理设备所维护的变量（即能够被 Agent 查询和设置的信息）。MIB 在数据库中定义了被管理设备的一系列属性：对象的名称、对象的状态、对象的访问权限和对象的数据类型等。
- **OID（Object Identifier）**：MIB 是以树状结构进行存储的，树的节点表示管理对象 Object，对象可以用从根 Root 开始的一条路径来唯一的识别，这就是 OID 也即对象标识符。

### SNMP 的应用场景

在网络管理站中配置 SNMP 管理程序，在被管理设备端启用 Agent 代理程序，同时在组网中配置 SNMP 协议。通过 SNMP 协议：

- 网络管理站可以通过 Agent 获取或变更设备的信息，实现远程监控和管理。
- Agent 可以及时地向网络管理站报告设备的状态（Trap）。

### NETCONF

- NETCONF 使用 SSH 实现安全传输，使用 RPC（Remote Procedure Call）远程调用的机制实现客户端和服务端的通信。
- NETCONF 消息以 XML 格式呈现。
- NETCONF 提供一套管理网络设备的机制。用户可以使用这套机制增加、修改、删除、备份、恢复、锁定、解锁网络设备的配置，同时还具备事务和会话操作功能，从而来获取网络设备的配置和状态信息。

### NetStream

一个典型的 NetStream 系统由网络流数据输出器（NetStream Data Exporter, NDE）、网络流数据收集器（NetStream Collector, NSC）和网络流数据分析器（NetStream Data Analyzer, NDA）三部分组成。

- **NDE**：负责对网络流进行分析处理，提取符合条件的流进行统计，并将统计信息输出给 NDA 设备。输出前也可对数据进行一些处理，比如聚合。配置了 NetStream 功能的设备在 NetStream 系统中担当 NDE 角色。
- **NSC**：通常为运行于 Unix 或者 Windows 上的一个应用程序，负责解析来自 NDE 的报文，把统计数据收集到数据库中，可供 NDA 进行解析。NSC 可以采集多个 NDE 设备输出的数据，对数据进行进一步的过滤和聚合。
- **NDA**：是一个网络流量分析工具，它从 NSC 中提取统计数据，进行进一步的加工处理，生成报表，为各种业务提供依据（比如流量计费、网络规划，攻击监测）。通常，NDA 具有图形化用户界面，使用户可以方便地获取、显示和分析收集到的数据。

NetStream 流输出方式：

- **原始流输出方式**：在流老化时间超时后，每条流的统计信息都要输出到 NSC。优点是 NSC 可以得到每条流的详细统计信息。
- **聚合流输出方式**：设备对与聚合关键项完全相同的原始流统计信息进行汇总，从而得到对应的聚合流统计信息。通过对原始流进行聚合后输出，可以明显减少网络带宽。

在实际的应用中，NSC 和 NDA 一般集成在一台 NetStream 服务器上。NDE 通过 NetStream 采样获取接口出方向流量信息，并按照一定条件建立 NetStream 流，当 NetStream 缓存区已满或者 NetStream 流达到老化时间，NDE 会将统计的信息封装成 NetStream 报文发送到 NetStream 服务器。

传统的流量统计的实现方法和局限性：

- 基于 IP 报文计数：统计的信息简单，无法针对多种信息进行统计。
- 使用 ACL：要求 ACL 的容量很大，对于 ACL 规则以外的流没有办法统计。
- SNMP 协议：功能不强。要不断的通过轮询向网管查询，浪费 CPU 和网络资源。
- 端口镜像：成本高，同时消耗设备的一个接口，对于无法镜像的端口无能为力。
- 物理层复制：成本高，同时还需要购买专用的硬件设备。

### sFlow

- **Flow 采样**：sFlow Agent 设备在指定接口上按照特定的采样方向和采样比对报文进行采样分析，用于获取报文数据内容的相关信息。该采样方式主要是关注流量的细节，这样就可以监控和分析网络上的流行为。Flow 采样可以截取原始报文的全部，也可以截取一部分报头。
- **Counter 采样**：sFlow Agent 设备周期性的获取接口上的流量统计信息。与 Flow 采样相比，Counter 采样只关注接口上流量的数量，而不关注流量的详细信息。

只需要在支持 sFlow Agent 的设备上进行部署，远端连接一个 sFlow Collector，就可以对流量进行基于接口的搜集和详细的分析。

使用 NetStream 也可以对网络流量进行统计分析，而 NetStream 是一种基于网络流信息的统计技术，网络设备自身需要对网络流进行初步的统计分析，并把统计信息储存在缓存区，当缓存区满或者流统计信息老化后输出统计信息。与 NetStream 相比，sFlow 不需要缓存区，网络设备仅进行报文的采样工作，网络流的统计分析工作由远端的采集器完成。

sFlow 与 NetStream 比较具有以下优势：

- **节省资源、降低成本**：由于不需要缓存区，对网络设备的资源占用少，实现成本低。
- **采集器灵活、随需的部署**：由于网络流的分析和统计工作由采集器完成，采集器可以灵活的配置网络流特征进行统计分析，实现灵活、随需的部署。
