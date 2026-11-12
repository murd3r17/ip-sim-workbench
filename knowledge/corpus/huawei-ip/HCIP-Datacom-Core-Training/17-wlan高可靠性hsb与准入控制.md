---
doc_id: "hcip-datacom-core-training-17"
title: "WLAN 高可靠性 HSB 与准入控制"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 17
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# WLAN 高可靠性 HSB 与准入控制

## VRRP 双机热备配置与验证（续）

查看 HSB 备份组与 HSB 主备服务信息：

```cli
[AC] display hsb-group group-index
[AC] display hsb-service service-index
```

### VRRP / HSB 配置示例

AC1 和 AC2 通过 VLANIF10 建立 VRRP 主备关系，VRRP 的虚拟 IP 为 `10.1.10.1`，AC1 为主设备，且优先级为 120；使用 HSB 技术实现双机热备。

```cli
[AC1] interface Vlanif10
[AC1-Vlanif10] ip address 10.1.10.100 255.255.255.0
[AC1-Vlanif10] vrrp vrid 1 virtual-ip 10.1.10.1
[AC1-Vlanif10] vrrp vrid 1 priority 120

[AC2] interface Vlanif10
[AC2-Vlanif10] ip address 10.1.10.200 255.255.255.0
[AC2-Vlanif10] vrrp vrid 1 virtual-ip 10.1.10.1
```

AC1 的 HSB 配置：

```cli
[AC1] hsb-service 0
[AC1-hsb-service-0] service-ip-port local-ip 10.1.10.100 peer-ip 10.1.10.200 local-data-port 10241 peer-data-port 10241
[AC1-hsb-service-0] quit
[AC1] hsb-group 0
[AC1-hsb-group-0] bind-service 0
[AC1-hsb-group-0] track vrrp vrid 1 interface Vlanif10
[AC1-hsb-group-0] quit
[AC1] hsb-service-type access-user hsb-group 0
[AC1] hsb-service-type dhcp hsb-group 0
[AC1] hsb-service-type ap hsb-group 0
[AC1] hsb-group 0
[AC1-hsb-group-0] hsb enable
```

AC2 配置与 AC1 相同，此处不再赘述。

### 查看运行情况

```cli
[AC1] display hsb-service 0
Hot Standby Service Information:
----------------------------------------------------------
Local IP Address       : 10.1.10.100
Peer IP Address        : 10.1.10.200
Source Port              : 10241
Destination Port       : 10241
Keep Alive Times       : 2
Keep Alive Interval    : 1
Service State             : Connected
----------------------------------------------------------
```

```cli
[AC1] display hsb-group 0
Hot Standby Group Information:
----------------------------------------------------------
HSB-group ID                     : 0
Vrrp Group ID                     : 1
Vrrp Interface                     : Vlanif10
Service Index                       : 0
Group Vrrp Status                : Master
Group Status                       : Active
Group Backup Process          : Realtime
Peer Group Device Name      : AirEngine 9700-M
Peer Group Software Version : V200R019C00
Group Backup Modules         : Access-user DHCP AP
```

---

## 双链路热备份

该方案除了支持主备备份之外，还支持负载分担模式。负载分担模式下可以指定一部分 AP 的主 AC 为 AC1，与其建立 CAPWAP 主链路，一部分 AP 的主 AC 为 AC2，与其建立 CAPWAP 主链路。

双链路双机热备的主备 AC 不受地理位置限制，部署灵活，可进行负载分担，有效利用资源，但业务切换速度较慢。

图中，AC1 和 AC2 经过部署为双链路双机热备，只绑定 HSB 主备服务，提供双机热备份 HSB 隧道。AP 需依次与两台 AC 建立 CAPWAP 隧道，通过 AC 下发的 CAPWAP 报文中的优先级判断主用 AC 与备用 AC。

### Discovery 阶段选主

建立主链路时，除了 Discovery 阶段要优选出主 AC，其他过程跟正常情况下的 CAPWAP 隧道建立过程一致。

在 Discovery 阶段，使能双链路备份功能后，AP 开始发送 Discovery Request 报文，分为单播方式和广播方式：

- 如果预先通过静态方式、DHCP 服务器方式或 DNS 方式指定了主备 AC 的 IP 地址，AP 向 AC 发送单播 Discovery Request 报文请求与主备 AC 关联。
- 如果没有配置 AC 的静态 IP 地址或者单播没有回应时，AP 将发送广播 Discovery Request 报文请求同网段内可关联的 AC。

不管是单播发现还是广播发现，如果主备 AC 都正常，都会回应 Discovery Response 报文，并在该报文中携带双链路特性开关、优先级、负载情况以及 IP 地址。

AP 收集到主备 AC 回应的 Discovery Response 报文后，根据 AC 的优先级、设备的负载情况以及 AC IP 地址来选择主 AC 并开始与其建立 CAPWAP 主链路，优选顺序如下：

1. 比较 AC 的优先级，优先级值小的为主 AC，默认优先级为 0，最大值为 7，优先级取值越小，优先级越高。
2. 优先级相同情况下，比较 AC 设备的负载情况，即 AP 个数和 STA 个数，负载轻的为主 AC。优先选择当前可接入 AP 数大的 AC 为主 AC，如果当前可接入 AP 数相同，则选择当前可接入 STA 数大的 AC 为主 AC。
3. 负载相同情况下，比较 IP 地址，IP 地址小的为主 AC。

说明：当前可接入 AP 数 = 可接入的最大 AP 数 − 当前已接入的 AP 数；当前可接入 STA 数 = 可接入的最大 STA 数 − 当前已接入的 STA 数。

### 备链路建立与心跳

- 如果该 AC 的优先级修改为比已经建立好 CAPWAP 链路的 AC 优先级高，也不进行主备倒换，待建立隧道完成后再进行倒换。
- AP 发送的 Join Request 中，会携带一个自定义消息类型，告诉备 AC 配置已经下发过了，不需要再下发。AC 收到 Join Request，获取到该自定义消息时，在配置下发阶段，会跳过配置下发流程，避免对 AP 重复下发配置。
- 备链路建立完成后，AP 重新根据两个链路的优先级决策出主备 AC。
- 缺省情况下，CAPWAP 心跳检测的间隔时间为 25 秒，心跳检测报文次数为 6。如果开启了双链路备份功能，则 CAPWAP 心跳检测的间隔时间为 25 秒，心跳检测报文次数为 3。

说明：

- 如果在配置双链路备份时需要使用 WDS 或 Mesh，建议配置 CAPWAP 心跳检测的间隔时间为 25 秒，心跳检测报文次数至少为 6 次。否则由于双链路备份时缺省的心跳报文间隔时间为 25 秒、次数为 3 次，会导致 WDS 或 Mesh 链路不稳定，无法保证用户正常接入。
- 配置 CAPWAP 心跳检测间隔时间和次数低于默认值会影响 CAPWAP 链路可靠性，请谨慎修改，建议使用默认值。

### 双链路备份配置命令

```cli
[AC-wlan-view] ac protect protect-ac { ip-address ip-address }
```

1. 配置备 AC 的 IP 地址。

```cli
[AC-wlan-view] ac protect priority priority
```

2. 配置本 AC 的优先级，默认为 0。

```cli
[AC-wlan-view] undo ac protect restore disable
```

3. 使能全局回切功能。

```cli
[AC-wlan-view] ac protect enable
```

4. 使能双链路备份功能。

```cli
[AC-wlan-view] ap-reset { all | ap-name ap-name | ap-mac ap-mac | ap-id ap-id | ap-group ap-group | ap-type { type type-name | type-id type-id } }
```

5. 重启 AP，使双链路备份功能生效。

HSB 相关（双链路热备场景绑定 HSB 服务）：

```cli
[AC] hsb-service service-index
[AC-hsb-service-0] service-ip-port local-ip { local-ipv4-address | local-ipv6-address } peer-ip { peer-ipv4-address | peer-ipv6-address } local-data-port local-port peer-data-port peer-port
[AC] hsb-service-type ap hsb-service service-number
[AC] hsb-service-type access-user hsb-service service-index
```

### 双链路热备配置示例

AC1 和 AC2 配置双链路双机热备，AC1 为主设备，优先级为 1，AC2 为备设备，优先级为 2；使用 HSB 技术实现双机热备。

AC1：

```cli
[AC1] wlan
[AC1-wlan-view] ac protect enable
[AC1-wlan-view] ac protect protect-ac 10.1.10.200 priority 1
[AC1] hsb-service 0
[AC1-hsb-service-0] service-ip-port local-ip 10.1.10.100 peer-ip 10.1.10.200 local-data-port 10241 peer-data-port 10241
[AC1-hsb-service-0] quit
[AC1] hsb-service-type ap hsb-service 0
[AC1] hsb-service-type access-user hsb-service 0
```

AC2：

```cli
[AC2] wlan
[AC2-wlan-view] ac protect enable
[AC2-wlan-view] ac protect protect-ac 10.1.10.100 priority 2
[AC2] hsb-service 0
[AC2-hsb-service-0] service-ip-port local-ip 10.1.10.200 peer-ip 10.1.10.100 local-data-port 10241 peer-data-port 10241
[AC2-hsb-service-0] quit
```

> （原图：AC1 `10.1.10.100/24`、AC2 `10.1.10.200/24`，中间 HSB 主备通道。）

验证：

```cli
[AC1] display hsb-service 0
Hot Standby Service Information:
----------------------------------------------------------
Local IP Address          : 10.1.10.100
Peer IP Address           : 10.1.10.200
Source Port                 : 10241
Destination Port          : 10241
Keep Alive Times         : 5
Keep Alive Interval       : 3
Service State                : Connected
Service Batch Modules  : AP Access-user DHCP
……
```

```cli
[AC1] display ac protect
------------------------------------------------------------
Protect state             : enable
Protect AC IPv4           : 10.1.10.200
Protect AC IPv6           : -
Priority                  : 0
Protect restore           : enable
...
```

---

## N+1 备份

当 AP 与主用 AC 之间的 CAPWAP 隧道中断时，将触发 AP 与备用 AC 建立 CAPWAP 隧道，此时 AP 会重新与该 AC 建链、重启并获取配置，在该过程中，业务将会受影响。

### 优先级与选主

- 当 AC 收到 AP 发送的 Discovery Request 报文时，如果 AC 没有为该 AP 配置个性优先级，则在回应的 Discovery Response 报文中携带全局优先级；
- 如果 AC 已为该 AP 配置了个性优先级，则在回应的 Discovery Response 报文中携带个性优先级。
- 正确配置主 AC 和备 AC 的不同优先级，可以控制 AP 能够在指定的主 AC 或备 AC 上线。

优选顺序如下：

1. AP 查看优选 AC，如果只有一个优选 AC，则此 AC 作为主 AC。如果存在多个优选 AC，则选择负载最轻的 AC 作为主 AC，如果负载相同选择 IP 地址最小的作为主 AC；
2. 负载的比较方式：比较 AC 设备的负载情况，即 AP 个数和 STA 个数，负载轻的为主 AC。优先选择当前可接入 AP 数大的 AC 为主 AC，如果当前可接入 AP 数相同，则选择当前可接入 STA 数大的 AC 为主 AC；
3. 如果没有优选 AC，查看备选 AC，如果只有一个备选 AC，则此 AC 作为主 AC，如果存在多个备选 AC，则选择负载最轻的 AC 作为主 AC，如果负载相同选择 IP 地址最小的作为主 AC；
4. 如果没有备选 AC，比较 AC 的优先级，优先级最高的作为主 AC。优先级取值越小，优先级越高；
5. 优先级相同情况下，则选择负载最轻的 AC 作为主 AC；
6. 负载相同情况下，继续比较 IP 地址，IP 地址小的为主 AC。

### N+1 配置命令

```cli
[AC-wlan-view] ap-system-profile name profile-name
```

1. 创建 AP 系统模板，并进入模板视图。

```cli
[AC-wlan-ap-system-prof-huawei] primary-access { ip-address ip-address | ipv6-address ipv6-address }
```

2. 配置优选 AC 的 IP 地址。

```cli
[AC-wlan-ap-system-prof-huawei] backup-access { ip-address ip-address | ipv6-address ipv6-address }
```

3. 配置备选 AC 的 IP 地址。

```cli
[AC-wlan-ap-group-huawei] ap-system-profile profile-name
```

4. 在 AP 组中引用 AP 系统模板。

```cli
[AC-wlan-ap-0] ap-system-profile profile-name
```

5. 在 AP 中引用 AP 系统模板。

```cli
[AC-wlan-view] ap-reset { all | ap-name ap-name | ap-mac ap-mac | ap-id ap-id | ap-group ap-group | ap-type { type type-name | type-id type-id } }
```

6. 重启 AP，使配置生效。

其它相关命令：

```cli
[AC-wlan-view] undo ac protect restore disable
```

1. 使能全局回切功能

```cli
[AC] capwap echo { interval interval-value | times times-value }
```

2. 配置 CAPWAP 心跳检测的间隔时间以及次数。

```cli
[AC-wlan-view] undo ac protect enable
```

3. 使能 N+1 备份功能。

说明：

- `ac protect enable` 命令用来使能全局双链路备份功能并去使能 N+1 备份功能。
- `undo ac protect enable` 命令用来去使能全局双链路备份功能并使能 N+1 备份功能。
- 缺省情况下，全局双链路备份功能未使能，N+1 备份功能使能。

### N+1 配置示例

场景说明：

- 已经完成各个 AC 和其它网络设备实现网络互通的配置。
- AC1 作为 AP1 的主 AC，AC2 作为 AP2 的主 AC，在主 AC 上配置主备 AC 信息。
- AC3 作为 AP1 和 AP2 的备 AC，在备 AC 上配置两个 AP 组，保持 WLAN 基本业务，业务配置和主 AC 保持一致。
- 先后在主备 AC 上配置 N+1 备份功能。配置完成后需要重启所有 AP。

AC1：

```cli
[AC1-wlan-view] ap-system-profile name ap-system1
[AC1-wlan-ap-system-prof-ap-system1] primary-access ip-address 10.23.201.1
[AC1-wlan-ap-system-prof-ap-system1] backup-access ip-address 10.23.203.1
[AC1-wlan-ap-system-prof-ap-system1] quit
[AC1-wlan-view] ap-group name ap-group1
[AC1-wlan-ap-group-ap-group1] ap-system-profile ap-system1
[AC1-wlan-ap-group-ap-group1] quit
```

AC2：

```cli
[AC2-wlan-view] ap-system-profile name ap-system2
[AC2-wlan-ap-system-prof-ap-system2] primary-access ip-address 10.23.202.1
[AC2-wlan-ap-system-prof-ap-system2] backup-access ip-address 10.23.203.1
[AC2-wlan-ap-system-prof-ap-system2] quit
[AC2-wlan-view] ap-group name ap-group2
[AC2-wlan-ap-group-ap-group2] ap-system-profile ap-system2
[AC2-wlan-ap-group-ap-group2] quit
```

AC3（备 AC，同时承载两组）：

```cli
[AC3-wlan-view] ap-system-profile name ap-system1
[AC3-wlan-ap-system-prof-ap-system1] primary-access ip-address 10.23.201.1
[AC3-wlan-ap-system-prof-ap-system1] backup-access ip-address 10.23.203.1
[AC3-wlan-ap-system-prof-ap-system1] quit
[AC3-wlan-view] ap-system-profile name ap-system2
[AC3-wlan-ap-system-prof-ap-system2] primary-access ip-address 10.23.202.1
[AC3-wlan-ap-system-prof-ap-system2] backup-access ip-address 10.23.203.1
[AC3-wlan-ap-system-prof-ap-system2] quit
[AC3-wlan-view] ap-group name ap-group1
[AC3-wlan-ap-group-ap-group1] ap-system-profile ap-system1
[AC3-wlan-ap-group-ap-group1] quit
[AC3-wlan-view] ap-group name ap-group2
[AC3-wlan-ap-group-ap-group2] ap-system-profile ap-system2
[AC3-wlan-ap-group-ap-group2] quit
```

使能 N+1 并重启 AP：

```cli
[AC3-wlan-view] undo ac protect restore disable
Info: Protect restore has already enabled.
[AC3-wlan-view] undo ac protect enable
Info: Backup function has already disabled.
[AC3-wlan-view] ap-reset all
Warning: Reset AP(s), continue?[Y/N]: y
```

```cli
[AC1-wlan-view] undo ac protect enable
Info: Backup function has already disabled.
[AC1-wlan-view] ap-reset all
Warning: Reset AP(s), continue?[Y/N]: y
[AC2-wlan-view] undo ac protect enable
Info: Backup function has already disabled.
[AC2-wlan-view] ap-reset all
Warning: Reset AP(s), continue?[Y/N]: y
```

说明：缺省情况下，全局回切功能处于使能状态；缺省情况下，N+1 备份功能开启。需要在主 AC 上继续执行 `ap-reset all` 重启所有 AP，AP 重启后，N+1 备份功能开始生效。

### N+1 配置验证

```cli
[AC1] display ac protect
------------------------------------------------------------
Protect state          : disable
Protect AC IPv4      : -
Protect AC IPv6      : -
Priority                  : 0
Protect restore       : enable
```

```cli
[AC1] display ap-system-profile name ap-system
---------------------------------------------------------------------------
AC priority                  : -
Protect AC IP address  : -
Primary AC                 : 10.23.201.1
Backup AC                  : 10.23.203.1
```

```cli
[AC2] display ap-system-profile name ap-system
---------------------------------------------------------------------------
AC priority                  : -
Protect AC IP address  : -
Primary AC                 : 10.23.202.1
Backup AC                  : 10.23.203.1
```

```cli
[AC3] display ac protect
------------------------------------------------------------
Protect state          : disable
Protect AC IPv4      : -
Protect AC IPv6      : -
Priority                  : 0
Protect restore       : enable
...
```

```cli
[AC3-wlan-view] display ap-system-profile name ap-system1
---------------------------------------------------------------------------
Primary AC                            : 10.23.201.1
Backup AC                             : 10.23.203.1
...
[AC3-wlan-view] display ap-system-profile name ap-system2
---------------------------------------------------------------------------
Primary AC                            : 10.23.202.1
Backup AC                             : 10.23.203.1
...
```

---

## 高可靠性方案对比

| 对比项 | VRRP 双机热备 | 双链路双机热备 | N+1 备份 |
|--------|---------------|----------------|----------|
| 切换速度 | 主备切换速度快，对业务影响小。通过配置 VRRP 抢占时间，相比于其他备份方式实现更快的切换 | AP 状态切换慢，需等待检测到 CAPWAP 断链超时后才会切换，主备切换后终端不需要重新上线 | AP 状态切换慢，需等待检测到 CAPWAP 断链超时后才会切换，AP、终端均需要重新上线，业务会出现短暂中断 |
| 主备 AC 异地部署 | 不建议主备 AC 异地部署 | 支持 | 支持 |
| 约束条件 | 主备 AC 的型号和软件版本需完全一致。一台备 AC 只支持为一台主 AC 提供备份。 | 主备 AC 的型号和软件版本需完全一致。一台备 AC 只支持为一台主 AC 提供备份。 | 主备 AC 产品形态可以不同，AC 的软件版本必须一致。一台备 AC 支持为多台主 AC 提供备份，能降低购买设备的成本。 |
| 适用范围 | 对可靠性要求高，且无须异地部署主备 AC 的场景 | 对可靠性要求高，且要求异地部署主备 AC 的场景 | 对可靠性要求较低，对成本控制要求较高的场景 |

---

## 准入控制技术

### 802.1X 认证

802.1X 认证系统使用可扩展认证协议（Extensible Authentication Protocol，EAP）来实现申请者、认证者和认证服务器之间的信息交互。常用的 802.1X 认证协议有防护扩展验证协议（Protected Extensible Authentication Protocol，PEAP）和传输层安全性协议（Transport Layer Security，TLS），其区别如下：

- **PEAP**：管理员给用户分配用户名、密码。用户在接入 WLAN 时输入用户名、密码进行认证。
- **TLS**：用户使用证书进行认证，此认证方式一般结合企业 App 使用，如华为的 EasyAccess。

对于大中型企业的员工，推荐使用 802.1X 认证。

### Portal 认证

**定义**：Portal 认证通常也称为 Web 认证，一般将 Portal 认证网站称为门户网站。用户上网时，必须在门户网站进行认证，如果未认证成功，仅可以访问特定的网络资源，认证成功后，才可以访问其他网络资源。

**优点**：

- 一般情况下，客户端不需要安装额外的软件，直接在 Web 页面上认证，简单方便。
- 便于运营，可以在 Portal 页面上进行业务拓展，如广告推送、企业宣传等。
- 技术成熟，被广泛应用于运营商、连锁快餐、酒店、学校等网络。
- 部署位置灵活，可以在接入层或关键数据的入口作访问控制。
- 用户管理灵活，可基于用户名与 VLAN/IP 地址/MAC 地址的组合对用户进行认证。

---

## 补充说明（问答要点）

1. AP 发送的 DHCP 广播请求报文是二层报文，不能在三层组网中传输，所以广播发现不了三层组网中 AC，必须通过 Option43 来通告 AC 的 IP 地址，否则 AP 获取不到 AC 的 IP 地址，后续 AP 无法上线。
2. 二层漫游和三层漫游的最大区别：漫游前后关联的 AP 的服务集上的 VLAN 不同。二层漫游是指客户端在同一子网内漫游；三层漫游是指客户端在不同子网间漫游。
3. 数据同步的方式有批量备份、实时备份和定时同步：
   - **批量备份**：在配置双机热备份功能后，先运行的主用设备会将已有的会话表项一次性同步到新加入的备份设备上。
   - **实时备份**：主用设备在产生新表项或表项变化后会及时备份到备份设备上。
   - **定时同步**：备用设备会每隔 30 分钟检查其已有的会话表项与主用设备是否一致，若不一致则将主用设备上的会话表项同步到备用设备。

### 思考题（WLAN）

1. （简答题）在部署 WLAN 三层组网的时候，需要配置 DHCP Option43，那么 Option43 的作用是什么？
2. （简答题）二层漫游和三层漫游的最大的区别是什么？
3. （简答题）WLAN 双机热备份数据同步的方式有几种，分别应用在什么场景下？

---

## 附录：数通产业与 CloudCampus 简述

万物互联：人与人、人与物、物与物互联；本质是数据的联结和计算。

数通网络如“河湖江海”，数通产业便是打造智能世界的数字基石：

- 数通是联结领域真正成网的产业，部署在网络的各个层级；
- 5G 接入和家宽接入犹如支流，园区网络好比池塘；
- 城域网好比长江的大型支流；骨干网好比长江；
- 核心数据中心是太平洋，区域数据中心是大型湖泊，接入数据中心是水库；
- 华为数通 4 大引擎：AirEngine（园区网络）、NetEngine（城域和骨干网络）、CloudEngine（DCN）、HiSecEngine（安全）。

企业 WAN 借助运营商提供的 WAN 网络，将企业分布在跨地域的多个分支、总部和数据中心实现互联。传统企业的关键应用和信息数据一般都存储在企业内部，WAN 带宽需求较小、业务变化不频繁；WAN 网络的运营和维护也一般依靠本地化的运维团队。

### 思考题（产品）

1. （单选题）以下哪个名称对应华为在 WLAN 领域的产品：A. AirEngine B. NetEngine C. CloudEngine D. HiSecEngine
2. （问答题）华为 CloudCampus 解决方案支持业务随行功能，该功能对于用户的价值是？

参考答案：

1. A
2. 业务随行：图形化策略配置，用户随时随地接入，漫游权限不变，体验不变。
