---
doc_id: "hcie-datacom-v1.0-lab-08"
title: "6.1 VXLAN 虚拟化园区部署"
book: "HCIE-Datacom-V1.0-Lab"
book_title: "HCIE-Datacom V1.0 实验手册"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "lab"
source_pdf: "HCIE-Datacom V1.0 实验手册.pdf"
seq: 8
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 6.1 VXLAN 虚拟化园区部署

## 6.1.1 实验介绍

6.1.1.1 学习目标

- 掌握站点创建及设备上线流程
- 掌握Fabric 网络创建、资源部署、Underlay 网络自动化部署流程
- 掌握Overlay 网络部署流程
- 掌握业务随行及准入控制部署流程
- 掌握WLAN 业务部署流程

6.1.1.2 实验组网介绍

图6-1 VXLAN 虚拟化园区部署 如图所示，该组网分为两部分：HQ 和云端。

HQ：ACC_1 和ACC_2 下连有线终端，为有线用户提供网络服务；ACC_2 下挂AP，为无线用户 提供网络服务，Edge_1 和Edge_2 作为汇聚层设备，Border 作为核心层设备。AR3 作为园区出 口，同时作为DHCP 服务器为HQ 内的其他设备及用户终端分配IP 地址。 云端：该部分通过交换机AR_Server_SW 模拟，负责连通HQ 与iMaster NCE 控制器，且 AR_Server_SW 是iMaster NCE 的网关。 VXLAN 网络：本实验组网是VXLAN 到汇聚的分布式网关模型，Edge_1 和Edge_2 作为VXLAN 网络的Edge 节点，Border 作为VXLAN 网络的Border 节点。 完成本实验后，最终能通过控制器实现网络及业务的集中管理和配置下发。 本实验与广域互联网络部署实验存在一定关联性，建议完成本实验后不要立马恢复环境，与下 一个实验一起完成后再进行环境恢复。

6.1.1.3 实验规划

本部分内容所展示的数据规划为后续实验步骤所需的所有数据，请仔细阅读。 6.1.1.3.1 AR3 配置规划 AR3 手动配置GE0/0/9 接口IP 地址以及前往iMaster NCE 的静态路由，自身作为DHCP 服务 器，为下连设备及用户终端分配IP 地址，并通过DHCP Option 148 告知下连设备iMaster NCE 的IP 地址及端口号信息。 AR3 VLAN 端口类型以及参数规划表 设备 端口 端口类型

```cli
VLAN参数
```

AR3 GE0/0/1 Hybrid PVID：VLAN 10 Tagged VLAN：130、140、150 Untagged VLAN：10

```cli
VLAN10 作为PVID，用于响应交换机的DHCP 请求，VLAN 130、140、150 用于对接Border 上不
```

同VN 的外部网络以及网络服务资源互联接口。

```cli
IP 地址规划

#设备 端口 IP地址 AR3 GE0/0/9 65.0.0.3/24

VLANIF 10

172.16.10.254/24 iMaster NCE / 172.99.0.99

6.1.1.3.2 设备上线规划 在iMaster NCE 上，可以在站点中通过设备型号或ESN 码添加本实验环境中的交换机及AP，以 便实现设备纳管。 设备ESN 码 设备 设备ESN 设备型号 站点 设备类型 角色 Border W02140038942 S5731-H24T4XC HQ LSW 核心 Edge_1 W02140014081 S5731-H24T4XC LSW 汇聚 Edge_2 W02130010540 S5731-H24T4XC LSW 汇聚 ACC_1 W02140038919 S5731-H24T4XC LSW 接入 ACC_2 DM20A9900120 S5731-H24P4XC LSW 接入 AP1 2102352UBR10L6001315 AirEngine5760-1 AP AP 具体设备ESN，以自身实验环境为准。 6.1.1.3.3 园区Fabric 与Underlay 网络规划 在基于物理网络创建Fabric 之前，需要配置Fabric 所使用的资源，包括网络资源池（例如

VLAN 资源、IP 地址资源、BD 资源、VNI 资源等），在后续的Fabric 创建时，需使用到这些预
```

先创建好的资源。 此外，还需要规划外部网络，网络服务资源，以及模板（包括服务器模板及认证模板），在后 续的逻辑网络创建及接入管理配置时，需要使用这些创建好的内容。

以下为网络资源池规划。 Fabric 全局资源池规划 网络资源 取值 说明

```cli
VLAN
```

100~300 业务VLAN ID池，包括：外部网络互联VLAN、网络服 务资源互联VLAN、策略联动管理VLAN、终端用户的 接入VLAN。 桥接广播域（BD） 1~1000 即Bridge Domain，每个BD都使用一个BD-ID进行标 识，后续控制器为设备下发配置时自动进行ID挑 选。

VXLAN网络标识（VNI） 1~1000 VXLAN网络标识符，用于区分VXLAN网络隔离域。

Underlay 自动化资源池规划 资源 取值 说明 互联VLAN 10-20 用于Fabric内Border与Edge互联 互联IP 172.20.0.0~172.20.0.0/16 用于Fabric内Border与Edge互联 环回口ID 3.3.3.0~3.3.3.0/24 即Loopback接口IP地址 在自动配置Underlay路由域，以及自动完成 Fabric与网络服务资源的对接时，用于建立

```cli
BGP EVPN对等体关系。
```

以下为策略模板规划，包含认证模板以及认证服务器，用于实现对用户进行接入认证。 RADIUS 服务器模板规划 参数项 取值 名称 RADIUS（可自定义） 内置服务器 打开 认证组件 内置认证服务 密钥 Huawei@123（可自定义）

Portal 服务器模板规划 参数项 取值 名称 Portal（可自定义） 内置服务器 打开 推送协议 HTTPS 认证组件 内置认证服务 密钥 Huawei@123（可自定义）

802.1X 和MAC 认证模板规划 参数项 取值 名称 MAC_802.1X（可自定义） 认证方式 MAC，802.1X RADIUS服务器模板 RADIUS（使用此前创建的模板）

Portal 认证模板规划 参数项 取值 名称 Portal 认证方式 Portal RADIUS服务器模板 RADIUS（使用此前创建的模板） Portal服务器模板 Portal（使用此前创建的模板）

```cli
#在本实验中，我们将基于一个园区物理网络构建一个Fabric 网络，且该Fabric 网络的VXLAN 范围是从核心交换机到汇聚交换机，组网方式为VXLAN 分布式网关。 以下为关于Fabric 网络的规划。 Fabric 网络规划 参数项 取值 名称 HQ（可自定义） 组网类型 分布式网关 无线WAC位置 核心（边界网关节点） 自动配置路由域 打开 反射器集群ID
```

Fabric 网络设备角色规划 设备 角色 Border 边界网关节点 Edge_1 边缘节点 Edge_2 边缘节点 ACC_1 拓展节点 ACC_2 拓展节点 站点配置开关 打开 域 单域（自定义） 加密 无（自定义）

```cli
#在本实验中，我们将基于园区物理网络创建2 个逻辑网络：OA（用于非研发办公）、RD（用 于研发），然后创建2 个外部网络，分别供上述两个虚拟网的接入用户访问外部网络所用。 此外，还需配置DHCP 网络服务资源，供虚拟网OA、RD 的接入用户获取IP 地址所用。 最后配置一个类型为other 的外部服务器，用于模拟E-mail 服务器。 以下为本实验的外部网络以及网络服务资源规划。 OA 外部网络规划 参数项 取值 与外部网络互联 L3独占出口 名称 OA（可自定义） 连接Internet 打开 核心设备 Border 互联端口 GigabitEthernet0/0/1
```

VLAN
IP地址类型 IPv4 本端IPv4地址 13.1.1.2

对端IPv4地址 13.1.1.1 IPv4掩码

RD 外部网络规划 参数项 取值 与外部网络互联 L3独占出口 名称 RD（可自定义） 连接Internet 打开 核心设备 Border 互联端口 GigabitEthernet0/0/1

```cli
VLAN
```

IP地址类型 IPv4 本端IPv4地址 14.1.1.2 对端IPv4地址 14.1.1.1 IPv4掩码

网络服务资源-DHCP 服务器、other 服务器规划 参数项 取值 名称

```cli
DHCP_Email（可自定义）
```

服务器类型
DHCP、其他

DHCP服务器

192.168.150.1 Other服务器 172.17.3.3/32 服务器互通源地址 / 场景 直连交换机 互联设备 Border
互联端口 GigabitEthernet0/0/1 互联VLAN 互联IPv4 192.168.150.2 对端IPv4 192.168.150.1 掩码 在本实验中，我们将对有线接入用户执行802.1X 或MAC 认证，对无线用户执行Portal 认证。 ACC_1 仅接入有线用户，ACC_2 则分别接入有线及无线用户。 以下是关于接入管理的相关规划。 Edge_1 接入管理规划 参数项 取值 认证控制点 Edge_1 认证控制点管理参数配置 策略联动管理VLAN 策略联动管理IP 172.16.16.1/23 端口名称 GigabitEthernet0/0/24 对端连接类型 Fabric扩展接入交换机 认证模板 MAC_802.1X 认证执行点设备配置 设备名称 ACC_1 端口名称 GigabitEthernet0/0/24 对端连接类型 终端(PC、话机、哑终端、非Fabric扩展交换机/AP) 继承认证控制点端口认证模板 是

Edge_2 接入管理规划 参数项 取值

认证控制点 Edge_2 认证控制点管理参数配置 策略联动管理VLAN 策略联动管理IP 172.16.18.1/23 端口名称 GigabitEthernet0/0/24 对端连接类型 Fabric扩展接入交换机 认证模板 MAC_802.1X 认证执行点设备配置 设备名称 ACC_1 端口名称 GigabitEthernet0/0/23 对端连接类型 终端(PC、话机、哑终端、非Fabric扩展交换机/AP) 继承认证控制点端口认证模板 是 端口名称 GigabitEthernet0/0/24 对端连接类型 终端(PC、话机、哑终端、非Fabric扩展交换机/AP) 继承认证控制点端口认证模板 否

6.1.1.3.4 Overlay 网络自动化规划 创建2 个逻辑网络：OA 以及RD，分别关联此前所创建的外部网络，且2 个逻辑网络的接入用 户都可以从外部服务资源DHCP 服务器获取IP 地址。 以下为逻辑网络相关规划。 逻辑网络OA 数据规划 参数项 取值 创建VN 名称 OA（可自定义） 用户网关位置 Fabric内

自定义VRF名称 OA 外部网络 OA（使用此前创建的外部网络） 网络服务资源
DHCP_E-mail（使用此前创建的网络服务资源）
手动指定用户网关 用户网关1 名称 Sales_Wired（可自定义）

```cli
VLAN类型
```

动态VLAN

```cli
VLAN
```

```cli
IPv4子网 172.17.10.0/24 IPv4网关地址 172.17.10.254 用户网关2 名称 Market_Wired（可自定义）
```

```cli
VLAN类型
```

动态VLAN

```cli
VLAN
```

```cli
IPv4子网 172.17.20.0/24 IPv4网关地址 172.17.20.254 用户网关3 名称 Sales_Wireless（可自定义）
```

```cli
VLAN类型
```

动态VLAN

```cli
VLAN
```

```cli
IPv4子网 172.17.11.0/24 IPv4网关地址 172.17.11.254 用户网关4 名称 Market_Wireless（可自定义）
```

```cli
VLAN类型
```

动态VLAN

```cli
VLAN
```

```cli
IPv4子网 172.17.21.0/24 IPv4网关地址 172.17.21.254 用户有线接入 业务名称 OA（可自定义） 设备名称：ACC_1 端口：GigabitEthernet0/0/24 业务VLAN：动态VLAN 设备名称：ACC_2 端口：GigabitEthernet0/0/23 业务VLAN：动态VLAN 用户无线接入 站点 HQ 选择设备 Border
```

逻辑网络RD 数据规划 参数项 取值 创建VN 名称 RD（可自定义） 用户网关位置 Fabric内 自定义VRF名称 RD 外部网络 RD（使用此前创建的外部网络） 网络服务资源
DHCP_E-mail（使用此前创建的网络服务资源）
手动指定用户网关 名称 RD（可自定义）

```cli
VLAN类型
```

动态VLAN

```cli
VLAN
```

```cli
IPv4子网 172.17.30.0/24 IPv4网关地址 172.17.30.254 用户有线接入 业务名称 RD（可自定义） 设备名称：ACC_1 端口：GigabitEthernet0/0/24 业务VLAN：动态VLAN 设备名称：ACC_2 端口：GigabitEthernet0/0/23 业务VLAN：动态VLAN
```

下面是VN 互通之间的规划。 VN 间互通规划 参数项 取值 名称 OA_to_RD（可自定义） 互通设备 Border 互通方式 部分互通 IP类型 IPv4 源VN OA 源IPv4前缀 Market_Wired(172.17.20.0/24) 目的VN RD 目的IPv4前缀 RD(172.17.30.0/24) 6.1.1.3.5 业务随行及准备认证规划 创建5 个安全组Sales_Wired、Sales_Wireless、Market_Wired、Market_Wireless、 RD，分别对应OA 以及RD 2 个逻辑网络中的销售有线用户、销售无线用户、市场有线用户、 市场无线用户、研发用户。 以下是准入认证规划。

用户认证账号规划 参数项 取值 RD用户组 用户名 kris（可自定义） 密码 Huawei@123（可自定义） 下次登录修改密码 关闭 允许登录方式 802.1X Sales用户组 用户名 sales（可自定义） 密码 Huawei@123（可自定义） 下次登录修改密码 关闭 允许登录方式 802.1X、Portal Market用户组 用户名 market（可自定义） 密码 Huawei@123（可自定义） 下次登录修改密码 关闭 允许登录方式 802.1X、Portal

授权结果规划 参数项 取值 Sales_Wired（802.1X认证） 名称 Sales_Wired_Result（可自定义） 安全组 Sales_Wired（使用此前创建的安全组）

```cli
VLAN
```

Sales_Wireless（Portal认证）

名称 Sales_Wireless_Result（可自定义） 安全组 Sales_Wireless（使用此前创建的安全组）

```cli
VLAN
```

Market_Wired（802.1X认证） 名称 Market_Wired_Result（可自定义） 安全组 Market_Wired（使用此前创建的安全组）

```cli
VLAN
```

Market_Wireless（Portal认证） 名称 Market_Wireless_Result（可自定义） 安全组 Market_Wireless（使用此前创建的安全组）

```cli
VLAN
```

RD（802.1X认证） 名称 RD_Result（可自定义） 安全组 RD（使用此前创建的安全组）

```cli
VLAN
```

授权规则规划 参数项 取值 Sales_Wired（802.1X认证） 名称 Sales_Wired_Rule（可自定义） 认证方式 用户接入认证 开启Portal-HACA协议 关闭 接入方式 有线 用户组信息匹配 打开 选择用户组：Sales 授权结果 Sales_Wired_Result

Sales_Wireless（Portal认证） 名称 Sales_Wireless_Rule（可自定义） 认证方式 用户接入认证 开启Portal-HACA协议 关闭 接入方式 Wi-Fi 用户组信息匹配 打开 选择用户组：Sales SSID匹配 Sales 授权结果 Sales_Wireless_Result Market_Wired（802.1X认证） 名称 Market_Wired_Rule（可自定义） 认证方式 用户接入认证 开启Portal-HACA协议 关闭 接入方式 有线 用户组信息匹配 打开 选择用户组：Market 授权结果 Market_Wired_Result Market_Wireless（Portal认证） 名称 Market_Wireless_Rule（可自定义） 认证方式 用户接入认证 开启Portal-HACA协议 关闭 接入方式 Wi-Fi 用户组信息匹配 打开 选择用户组：Market SSID匹配 Market

授权结果 Market_Wireless_Result RD（802.1X认证） 名称 RD_Rule（可自定义） 认证方式 用户接入认证 开启Portal-HACA协议 关闭 接入方式 有线 用户组信息匹配 打开 选择用户组：RD 授权结果 RD_Result 6.1.1.3.6 WLAN 业务规划 完成WLAN 业务配置，实现AP 和无线用户上线，其中包括AP 上线配置：PnP 配置、Border 侧的子网配置（包含DHCP Option 148 以及控制器地址配置）、CAPWAP 源地址配置。 AP 上线配置 参数项 取值 随板AC位置 Border AP上线方式 设置单独的PnP VLAN AP管理VLAN AP管理网段 172.16.20.0/24 AC地址 172.16.20.254 AP获取控制器地址方式 自动协商控制器地址

控制器侧无线认证配置 参数项 取值 名称：Sales SSID Sales

认证方式 开放网络 页面推送方式 云平台内置认证 Portal协议类型 Portal 2.0 主Portal服务器 Portal RADIUS服务器 RADIUS 推送方式 快速推送 推送页面 默认用户名密码认证定制界面 Portal免认证 开启 逃生策略 勾选，保持默认配置 设备 Border 名称：Market SSID Market 认证方式 开放网络 页面推送方式 云平台内置认证 Portal协议类型 Portal 2.0 主Portal服务器 Portal RADIUS服务器 RADIUS 推送方式 快速推送 推送页面 默认用户名密码认证定制界面 Portal免认证 开启 逃生策略 勾选，保持默认配置 设备 Border

WLAN 业务规划 参数项 取值

业务名称：Sales_Wireless 业务VLAN SSID模板 名称：Sales（可自定义） SSID名称：Sales VAP模板 名称：Sales（可自定义） 业务VLAN：VLAN110 转发模式：隧道转发 引用模板：SSID模板“Sales”，认证模板“Portal” 业务名称：Market_Wireless 业务VLAN SSID模板 名称：Market（可自定义） SSID名称：Market VAP模板 名称：Market（可自定义） 业务VLAN：VLAN210 转发模式：隧道转发 引用模板：SSID模板“Market”，认证模板选用控制器配置的模板。

## 6.1.2 实验任务配置

6.1.2.1 配置思路

1. 基础预配置，实现AR3 与控制器IP 可达，完成NAT 配置（用于设备上线），完成AR3 作 为DHCP 服务器（设备上线以及终端用户）和模拟外部网络的配置，创建一个环回口用于 模拟外部E-mail 服务器，并且实现路由可达。
2. 创建站点HQ，站点内所有设备通过AR3 的DHCP 服务获取控制器IP 地址，通过AR3 上的

```cli
NAT 实现与控制器的通信。

3. 设备上线之后，按照规划完成Fabric 全局资源池、Underlay 资源池配置。 4. 配置策略模板：包括RADIUS 服务器、Portal 服务器、认证模板（Portal、802.1X）。 5. 配置Fabric 网络，组网模式部署为分布式，VXLAN 到汇聚，使用Border 作为随板AC 纳管 AP。 6. 配置外部网络OA、RD，分别为后续需要创建的逻辑网络（VN）调用。

7. 配置网络服务资源，包括一个DHCP 服务器以及Other 类型的服务器。 8. 配置接入管理，配置与接入交换机对接的端口为扩展交换机。 9. 创建逻辑网络OA 以及RD，在OA 中分别为市场部门（Market）、销售部门（Sales）的无 线、有线网络创建用户网关，在RD 中只创建有线网络的网关，并关联对应的外部网络以 及网络资源服务器。 10. 配置VN 的部分互通，实现Market 与RD 之间的路由可达。 11. 业务随行配置：分别为OA 中的Market、Sales 的有线、无线用户以及RD 的有线用户创建 安全组，创建一个资源组E_Mail（对应之前网络服务资源中的Other 类型服务器）。创建 策略控制矩阵，实现：Market 的有线用户安全组可以访问RD，RD 不能访问E_Mail 资源 组。 12. 准入认证：Market、Sales、RD 各创建一个用户组，分别为OA 中的Market、Sales 的有线 无线用户、RD 的有线用户创建授权结果以及授权规则，并创建Portal 免认证策略，实现 Market、Sales 的无线用户的Portal 无感知重认证。 13. WLAN 业务：使用Border 作为随板AC，为Market、Sales 的无线用户创建不同的SSID，使 用不同的业务VLAN。

6.1.2.2 初始化（可选操作）

#在开始实验时，为避免上一个用户所做的配置影响本实验，需要将环境中的iMaster NCE 及网 络设备（Border、Edge_1、Edge_2、ACC_1、ACC_2）进行配置清除，将这些节点的配置还原 为出厂状态。 说明：先删除iMaster NCE 上的配置，再删除网络设备上的配置。 具体步骤请参考本实验的“配置清除”一章。 说明：若实验环境已完成初始化过程，则跳过此步骤。

6.1.2.3 AR3 的预配置

#在本实验中，AR3 作为HQ 园区的出口路由器，首先需完成预配置，以便AR3 与后续的整个园 区的配置形成联动。这些预配置包括：VLAN 配置、VLANIF 配置、IP 路由配置、DHCP 服务配 置、模拟外部网络的相关配置、LLDP 使能配置、NAT 配置等。 6.1.2.3.1 DHCP Server（用于实现设备即插即用）预配置 AR3 作为DHCP 服务器，为HQ 内的交换机分配管理IP 地址。同时，AR3 需要向HQ 内的交换 机通告iMaster NCE 控制器的IP 地址及端口号信息。 在本预配置中，VLAN10 用于AR3 与Border 对接，AR3 下联的交换机将通过该VLAN 获得IP 地 址，并获知iMaster NCE 控制器的IP 地址及端口号信息。 步骤 1

VLAN 相关配置

#在AR3 上创建VLAN 10。

[AR3]vlan 10

#配置AR3 与Border 的互联接口类型为hybrid，配置VLAN 10 为untagged，以及设置PVID 为
```

10。

```cli
[AR3]interface GigabitEthernet 0/0/1

[AR3-GigabitEthernet0/0/1] portswitch

[AR3-GigabitEthernet0/0/1] port link-type hybrid

[AR3-GigabitEthernet0/0/1] port hybrid pvid vlan 10

[AR3-GigabitEthernet0/0/1] undo port hybrid vlan 1

[AR3-GigabitEthernet0/0/1] port hybrid untagged vlan 10
```

步骤 2

```cli
DHCP 相关

#在AR3 上全局开启DHCP 服务，配置VLANIF10 的接口IP 地址，选择接口地址池，并配置

DHCP 静态绑定以及Option 148.

#全局开启DHCP 服务。

[AR3]dhcp enable

#在AR3 上创建VLANIF10，并配置对应IP 地址。

[AR3]interface Vlanif10

[AR3-Vlanif10] ip address 172.16.10.254 255.255.255.0

[AR3-Vlanif10] dhcp select interface

[AR3-Vlanif10] dhcp server static-bind ip-address 172.16.10.1 mac-address 9400-b049-9ef2

[AR3-Vlanif10] dhcp server static-bind ip-address 172.16.10.2 mac-address d446-4982-348d

[AR3-Vlanif10] dhcp server static-bind ip-address 172.16.10.3 mac-address 80e1-bf0e-5652

[AR3-Vlanif10] dhcp server static-bind ip-address 172.16.10.4 mac-address 9400-b049-9d82

[AR3-Vlanif10] dhcp server static-bind ip-address 172.16.10.5 mac-address b008-750e-fbd0

[AR3-Vlanif10] dhcp server option 148 ascii agilemode=agile-cloud;agilemanage-mo
```

de=ip;agilemanage-domain=172.99.0.99;agilemanage-port=10020; 使用接口地址池为下连设备分配IP 地址，并通过Option 148 告知控制器IP 地址。 为下连设备静态绑定IP 地址为可选配置，可在下连交换机上查看VLANIF 的接口MAC 地址作 为地址绑定MAC。 6.1.2.3.2 DHCP Server（用于为Host 分配IP 地址）预配置 AR3 作为DHCP 服务器，为HQ 内的Host 分配IP 地址。 步骤 1 创建DHCP 地址池 分别为逻辑网络OA、RD 内的终端创建DHCP 地址池。

```cli
#创建Sales 的有线网络地址池。

[AR3]ip pool Sales_Wired

[AR3-ip-pool-Sales_Wired] gateway-list 172.17.10.254

[AR3-ip-pool-Sales_Wired] network 172.17.10.0 mask 255.255.255.0

[AR3-ip-pool-Sales_Wired] quit

#创建Sales 的无线网络地址池。

[AR3]ip pool Sales_Wireless

[AR3-ip-pool-Sales_Wireless] gateway-list 172.17.11.254

[AR3-ip-pool-Sales_Wireless] network 172.17.11.0 mask 255.255.255.0

[AR3-ip-pool-Sales_Wireless] quit

#创建Market 的有线网络地址池。

[AR3]ip pool Market_Wired

[AR3-ip-pool-Market_Wired] gateway-list 172.17.20.254

[AR3-ip-pool-Market_Wired] network 172.17.20.0 mask 255.255.255.0

[AR3-ip-pool-Market_Wired] quit

#创建Market 的无线网络地址池。

[AR3]ip pool Market_Wireless

[AR3-ip-pool-Market_Wireless] gateway-list 172.17.21.254

[AR3-ip-pool-Market_Wireless] network 172.17.21.0 mask 255.255.255.0

[AR3-ip-pool-Market_Wireless] quit

#创建RD 的地址池。

[AR3]ip pool RD

[AR3-ip-pool-RD] gateway-list 172.17.30.254

[AR3-ip-pool-RD] network 172.17.30.0 mask 255.255.255.0

[AR3-ip-pool-RD] quit
```

步骤 2 互联配置 为能够实现向主机提供地址分配的服务，需在AR3 上创建对应的互联接口（VLANIF），以及 在互联接口上放通对应的VLAN。 此处的配置可参照实验规划中的网络服务资源-DHCP 服务器、other 服务器规划。

```cli
#创建VLAN。

[AR3]vlan 150

#创建VLANIF 接口。

[AR3]interface Vlanif150

[AR3-Vlanif150] ip address 192.168.150.1 255.255.255.252

[AR3-Vlanif150] dhcp select global

[AR3-Vlanif150] quit
```

接口下使能选择全局地址池的功能。

```cli
#互联接口VLAN 配置。

[AR3]interface GigabitEthernet0/0/1

[AR3-GigabitEthernet0/0/1] port hybrid tagged vlan 150

6.1.2.3.3 模拟外部网络预配置 完成AR3 上与外部网络相关的配置，包括与Border 的互联配置，用于模拟E-mail Server 的环 回接口配置。

#创建Loopback1。

[AR3]interface LoopBack1

[AR3-LoopBack1] ip address 172.17.3.3 32

#完成与逻辑网络OA 相关的配置。

[AR3]vlan 130

[AR3]interface Vlanif130

[AR3-Vlanif130] ip address 13.1.1.1 255.255.255.252

[AR3-Vlanif130] quit

[AR3]interface GigabitEthernet0/0/1

[AR3-GigabitEthernet0/0/1] port hybrid tagged vlan 130
```

创建用于与逻辑网络OA 互联的VLANIF 接口，并在物理接口上放通对应的VLAN。

```cli
#完成与逻辑网络RD 相关的配置。

[AR3]vlan 140

[AR3]interface Vlanif140

[AR3-Vlanif140] ip address 14.1.1.1 255.255.255.252

[AR3-Vlanif140] quit

[AR3]interface GigabitEthernet0/0/1

[AR3-GigabitEthernet0/0/1] port hybrid tagged 140

#在AR3 的预配置中，我们使用到了多个VLAN，通过下图帮助各位理解每个VLAN 的作用。

6.1.2.3.4 AR3 LLDP 配置 AR3 使能LLDP 功能，使iMaster NCE 控制器能够发现Fabric 与外部网络的互联链路。

[AR3] lldp enable

6.1.2.3.5 AR3 连通配置 完成AR3 与外部网络的连通配置，以实现AR3 能够与iMaster NCE 进行通信，并通过源NAT 完 成下连交换机与iMaster NCE 的通信。 同时需在AR3 上配置前往主机网段的回程路由。

#配置AR3 与外部网络互联接口的IP 地址。

[AR3]interface GigabitEthernet0/0/9

[AR3-GigabitEthernet0/0/9] ip address 65.0.0.3 255.255.255.0

[AR3-GigabitEthernet0/0/9] quit

#配置源NAT。

[AR3]acl 3000

[AR3-acl-adv-3000]rule permit ip

[AR3-acl-adv-3000]quit

[AR3]interface GigabitEthernet0/0/9

[AR3-GigabitEthernet0/0/9]nat outbound 3000

#配置前往逻辑网络OA 中主机网段的回程路由。

[AR3]ip route-static 172.17.10.0 255.255.255.0 13.1.1.2

[AR3]ip route-static 172.17.11.0 255.255.255.0 13.1.1.2

[AR3]ip route-static 172.17.20.0 255.255.255.0 13.1.1.2

[AR3]ip route-static 172.17.21.0 255.255.255.0 13.1.1.2

#配置前往逻辑网络RD 中主机网段的回程路由。

[AR3]ip route-static 172.17.30.0 255.255.255.0 14.1.1.2

#配置AR3 前往外部网络的默认路由。

[AR3]ip route-static 0.0.0.0 0.0.0.0 65.0.0.254

6.1.2.4 创建站点及设备上线

#在一个实际项目中，交换机的数量是庞大的，这些设备完成上电后，需进行初始化并完成基本 的IP 连通性等配置，我们将这些配置称为开局配置。传统的开局配置需要大量的手工操作， 效率太低，CloudCampus 解决方案支持零配置开局（Zero-Touch Provisioning），也称为设备即 插即用，即设备以出厂的状态加电并完成连线后，即可自动完成开局配置，大大地简化了运维 管理成本。 当前支持两种开局场景：网络设备先上线后配置和先配置后网络设备上线，本实验展示设备先 上线后配置的方式。 步骤 1 获取设备ESN 码 根据自身实验环境查看交换机、AP 的ESN 码，本实验中不展示如何登录交换机、AP 并查看 ESN，具体查阅对应设备的产品文档。 步骤 2 登录iMaster NCE 控制器，开始开局操作 进入iMaster NCE 控制器后，首先看到的是首页，如下图所示。 读者需关注的是图示的两个区域。其中顶部导航包括“设计”等等在内的一系列选项，这些选 项将覆盖园区网络的全生命周期管理。用户需对网络进行管理或者实现业务发放时，可选择相 应的选项，进入配置页面进行配置。 为了简化用户的管理操作，iMaster NCE 提供了面向典型开局场景的配置导航，见下图所示的 “开局场景”，其中的“Fabric 网络”可快速引导用户完成园区VXLAN 网络的业务规划和配 置。当然组合使用iMaster NCE 顶部导航中的相应选项，也可以实现与“Fabric 网络”开局部 署场景相同的目的。

#在iMaster NCE 控制器的首页点击“开局场景 > Fabric 网络”，进入Fabric 网络配置界面，如
```

下图所示。

步骤 3 创建站点并添加设备

```cli
#新建站点。
```

点击“网络规划 > 站点设计”进入站点设计页面，在该页面中点击“创建”，新建一个站点 并添加设备。 为了确保iMaster NCE 能够顺利纳管园区网络中的物理设备，用户首先需要在iMaster NCE 上 创建站点，并且向站点中添加设备，此处的设备需与园区网络中的物理设备一一对应，用户可 以选择手工逐台设备添加，也可以批量导入。

```cli
#选择设备类型。
```

需注意设备类型中，WAC、LSW 为必选项，同时建议勾选AR，用于后期SD-WAN 的实验。 部分设备可直接通过ESN 码添加，部分设备可通过设备型号添加。 本实验采用的S5731-H24P4XC、S5731-H24T4XC 需通过设备型号添加。

```cli
#通过设备型号分别添加S5731-H24P4XC、S5731-H24T4XC。
```

添加S5731-H24T4XC 时不选择角色。

```cli
#设置名称、角色以及补充ESN 号。
```

按照规划补充信息。 再次提醒，在此步骤请确保所有交换机都已清空配置重启，并在启动阶段无任何命令行输入， 直到设备上线之后才可对命令行进行操作。 步骤 4 查看设备注册状态

```cli
#查看设备上线状态。

#在iMaster NCE 控制器首页点击“开局场景 > Fabric 网络”，然后点击“网络规划 > 设备管 理”进入设备管理页面，可以看到设备的状态为正常（或者存在告警），因为在此之前，设备 已经完成了初始化过程，当控制器完成站点创建和设备添加后，设备即可顺利注册到控制器。 说明：需注意的是由于当前尚未完成接入管理配置，此时AP 无法完成上线操作，因此本步骤 中不对AP 进行上线操作，等到对应步骤时，再进行AP 上线配置。
```

6.1.2.5 园区Fabric 与Underlay 网络自动化

6.1.2.5.1 配置网络资源和策略模板 在本环节我们会完成“网络规划”中的“资源池配置”以及“策略模板”配置，具体配置参数 参考实验规划中相关模板。 步骤 1 Fabric 全局资源池 完成Fabric 全局资源池配置，按照Fabric 全局资源池规划完成。

```cli
#配置Fabric 资源池。

#在iMaster NCE 控制器首页点击“开局场景 > Fabric 网络”，然后点击“网络规划 > Fabric 全 局资源池”进入Fabric 全局资源池配置页面。 需要注意各参数添加完需点击后边的“+”确认。 步骤 2 配置Underlay 自动化资源池 完成Underlay 自动化资源池配置，按照Underlay 自动化资源池规划完成。

#配置Underlay 自动化资源池。

#在顶部导航中点击“Underlay 自动化资源池”，在Underlay 自动化资源池配置页面中填写相 应的参数，点击“+”确认。 步骤 3 配置策略模板 按照规划，完成策略模板中“RADIUS 服务器”、“Portal 服务器”、“认证模板”的配置。

#配置RADIUS 服务器。

#在顶部导航栏中点击“RADIUS 服务器”-“创建”，在弹出窗口中完成RADIUS 服务器配置， 最后点击“确定”完成配置。

#配置Portal 服务器。

#在当前页面点击“Portal 服务器”-“创建”，在弹出窗口中完成Portal 服务器配置，最后点击 “确定”完成配置。

#创建认证模板MAC_802.1X。

#在当前页面点击“认证模板”-“创建”，创建一个新的802.1X 及MAC 认证模板。

#创建认证模板Portal。

#在当前页面点击“认证模板”-“创建”，创建一个新的Portal 认证模板。 6.1.2.5.2 配置Fabric 网络 步骤 1 创建Fabric 网络并完成Underlay 网络自动化部署 按照之前规划，完成Fabric 网络的创建。

#创建Fabric。

#在当前页面点击顶部的“Fabric 网络”进入Fabric 管理页面，点击“创建Fabric”。 如果控制器上并不存在任何Fabric，此时会直接提示创建Fabric。

#按规划完成Fabric 创建。
```

完成后点击“应用”。

```cli
#添加设备。
```

点击1 处图标，切换视图，点击“添加设备”，添加交换机到Fabric。

```cli
#设置设备角色。

#在弹出的页面中，将左侧设备添加到右侧（选中后使用1 处按钮），并按照规划设置交换机的 角色。 在本例中Edge_1 和Edge_2 需被指定为边缘节点（VXLAN 的边缘），ACC_1 和ACC_2 需被指定 为扩展节点，而核心交换机Border 需指定为边界网关节点（连接Fabric 与外部网络的边界设 备）。

#完成物理网络自动化部署。

#在接下来的页面，打开站点HQ 的配置开关，关闭OSPF 邻居之间的认证，最后点击“应 用”。

#检查配置结果。

#在当前页面点击“配置状态”按钮，界面中所有的配置项的“配置状态”均为“成功”。 步骤 2 配置外部网络 在本步骤中，我们将完成Fabric 外部网络的创建。

#创建OA 外部网络。

#在“开局场景”-“Fabric 网络”中切换到Fabric 配置界面，点击页面左侧的外部网络的修改按 钮，在弹出的页面中点击“创建”按钮进行外部网络的创建。
```

选择“L3 独占出口”，之后点击“确定”。

```cli
#配置外部网络名称，勾选“连接Internet”。
```

核心设备选择Border，点击“增加”按钮，添加互联端口。 在当前页面中，“核心设备”选择“Border”，这意味着告知iMaster NCE 控制器：这台交换 机将作为连接外部网络的边界设备。 在“互联端口”中点击“增加”，为该交换机添加去往外部网络的接口，并按照数据规划表配 置互联信息。

该页面配置参数含义如下： 1. 名称：可自定义，此处以“OA”为例。 2. 端口：在该外部网络中，Border 设备用于连接外部设备（在本例中指的是AR3）的接口。 3.
VLAN：在该外部网络中，Border 设备用于连接外部设备的VLAN。
4.
IP 地址类型：可根据实际情况勾选IPv4 和IPv6，在本例中仅选择IPv4。

5. 本端IPv4 或IPv6 地址：在该外部网络中，Border 设备用于连接外部设备的本地接口IP 地 址（指的是上面的VLAN 对应的VLANIF 的IP 地址）。 6. 对端IPv4 或IPv6 地址：在该外部网络中，对端设备的IP 地址。 7. IPv4 或IPv6 掩码：IPv4 或IPv6 地址掩码。 按规划配置互联接口，之后点击“确定”，“下一步”。

```cli
#在最后的“路由配置”中点击“应用”，至此，外部网络OA 的创建已经完成。

#创建RD 外部网络。
```

外部网络RD 的创建步骤与OA 类似，在此不再展示，按照规划配置即可。 步骤 3 配置网络服务资源 本步骤完成Fabric 与网络服务资源（DHCP 服务器、RADIUS 服务器、Portal 服务器，以及其他 服务器）的连接关系（设备地址、互联VLAN、互联地址、对端地址、互联端口等）。 在本例中，我们配置的网络服务资源包括为终端分配IP 地址的DHCP 服务器以及充当E-mail Server 的Other 类型服务器。

```cli
#创建网络服务资源。

#在“开局场景”-“Fabric 网络”中切换到Fabric 配置界面，点击页面左侧的网络服务资源的修 改按钮，在弹出的页面中点击“创建”按钮进行网络服务资源的创建。
```

按照规划配置网络服务资源中的DHCP 服务器以及E-mail 服务器，点击“下一步”。

按照规划完成互联部分配置，场景需选择为“直连交换机”，最终点击“完成”，完成网络服 务资源的创建。

```cli
#查看网络服务资源部署状态。
```

当状态为“部署成功”时，表示部署完成。 步骤 4 配置接入管理 在本实验中，我们需在园区网络部署准入控制，包括802.1X 认证、MAC 认证和Portal 认证， 其中802.1X 认证及MAC 认证在实现中需RADIUS 服务器配合，而Portal 认证则需RADIUS 服务 器和Portal 服务器配合。

```cli
#切换ACC_1、ACC_2 的工作模式。

[ACC_1]undo as-mode disable

Warning: Changing the AS mode will clear current configuration and reboot the system, causing WLAN services unavailable. Continue? [Y/N]:y

[ACC_2]undo as-mode disable

Warning: Changing the AS mode will clear current configuration and reboot the system, causing WLAN services unavailable. Continue? [Y/N]:y
```

为实现与Edge_1、2 共同完成策略联动，需将ACC_1、2 的工作模式切换为AS 模式，默认情 况下S5731-H 系列的工作模式为parent，因此需要使用该命令进行切换。

```cli
#进入“接入管理”。

#在“开局场景”-“Fabric 网络”中切换到Fabric 配置界面，点击“接入管理”即可进入接入管 理配置界面，默认已经选择了一个认证控制点。

#配置认证控制点Edge_1。
```

按照接入管理规划表配置Edge_1。 ACC 交换机将会通过策略联动VLAN 实现和Edge 交换机共同完成对接入终端的认证。 因为采用策略联动方式，所以需要将连接ACC_1 交换机的端口设置为“Fabric 扩展接入交换 机”，同时配置认证模板为“ MAC_802.1X”。

```cli
#在“认证执行点设备配置”中选择ACC_1 连接终端的接口（GE0/0/24），设置对端连接类型 为“终端（PC、话机、哑终端、非Fabric 扩展交换机/AP）”，同时勾选“继承认证控制点端 口认证模板”，ACC_1 的GE0/0/24 将会继承Edge_1 的认证模板，并协同和Edge_1 完成对终 端的准入认证。 最终点击页面右下角的“应用”，完成对Edge_1 的接入管理配置。

#配置认证控制点Edge_2。

#在当前页面认证控制点下拉选择“Edge_2”，切换到Edge_2 的配置界面，请注意在此之前应 用了Edge_1 的配置。
```

按照接入管理规划表配置Edge_2。

```cli
#在“认证执行点设备配置”中选择ACC_2 连接终端的接口（GE0/0/23），设置对端连接类型 为“终端（PC、话机、哑终端、非Fabric 扩展交换机/AP）”，同时勾选“继承认证控制点端 口认证模板”，而对于连接AP 的接口，只需设置对端连接类型。

#检查Fabric 配置下发结果。

#在当前页面点击右上角的“配置状态”，查看配置下发结果。
```

6.1.2.6 Overlay 网络自动化

6.1.2.6.1 逻辑网络（VN） 在本部分内容中，我们将会创建两个VN 网络：OA、RD，关联对应的外部网络以及网络服务 资源，并为用户创建网关。 步骤 1 创建OA 逻辑网络 按照规划表创建OA 逻辑网络。

```cli
#创建逻辑网络OA。

#将页面切换到“逻辑网络”，点击“创建”。在新页面中创建VN：OA，配置VRF 名称为 OA，关联网络服务资源：DHCP_Email，关联外部网络：OA。
#在下一步的“用户网关”中通过“手动指定”的方式，配置OA 内的用户网关。
```

Sales_Wired 的用户网关配置如上图所示，其余三个用户网关配置方式一致，不再展示。

点击“下一步”，配置用户接入。

点击“+”号按钮，添加有线接入。

```cli
#配置名称为OA，点击增加。
```

勾选中ACC_1、2，添加到已选中，之后确定。

设置ACC_1 的GE0/0/24 接口的业务VLAN 为动态VLAN。

设置ACC_2 的GE0/0/23 接口的业务VLAN 为动态VLAN，最后点击应用。

```cli
#配置无线接入。
```

点击“增加”，选中Border 之后，最后点击确定。

最后点击应用，完成逻辑网络OA 的配置。 步骤 2 创建RD 逻辑网络 参照逻辑网络OA 的创建步骤，完成逻辑网络RD 创建。相关参数请参考逻辑网络RD 数据规 划。需注意的是，RD 中并不允许无线用户接入。

步骤 3 查看配置状态 在逻辑网络管理页面中，如下图所示点击配置结果图标查看配置结果。

6.1.2.6.2 配置VN 互通 缺省情况下，VN 之间完全隔离，但是在某些特殊情况下，我们可能希望VN 之间能够互访， 此时需要将VN 之间的路由打通。 例如在本实验中，假设接入OA 中的市场人员（Market_Wired）能够访问RD 以获取相应的设 备规划，为此需要按照规划配置OA 中172.16.20.0/24 网段与RD 中172.16.30.0/24 网段之间的 互通。

```cli
#创建VN 互通。

#在当前页面点击“VN 互通”，点击“增加”。
```

按规划完成VN 互通配置，最后点击应用。

```cli
#查看配置状态。
```

已配置成功。

6.1.2.7 业务随行及准入认证

```cli
#在大型园区网络中，一般允许员工从网络中的任意位置、任意VLAN、任意IP 网段接入的同时 还可以始终控制其网络访问权限。华为引入了业务随行，通过控制器和敏捷交换机，让网络权 限自动跟随人移动，以此解决移动办公体验糟糕的问题。 业务随行从三个方面解决传统园区中遇到的问题： 1. 业务策略与IP 地址解耦 2. 用户信息集中管理 3. 策略集中管理 业务随行功能允许管理员在园区网络中定义逻辑的组（安全组），管理员可基于iMaster NCE 的 图形化界面配置组与组之间的通信规则（策略控制矩阵），并将该通信规则下发到网络的策略 执行点上（交换机）。结合后续部署的准入认证，当用户接入园区网络并完成准入认证后，会 获得相应的安全组授权，如此一来，用户之间交互的流量便会被识别为安全组与安全组之间的 交互流量，在策略执行点上，设备按照管理员所定义的策略控制矩阵针对这些流量执行策略。 在本实验中，我们将创建5 个安全组Sales_Wired、Sales_Wireless、Market_Wired、Market_Wireless、 RD 以及1 个资源组E_mail。 6.1.2.7.1 业务随行 步骤 1 创建安全组

#切换页面。

#在iMaster NCE 控制器首页点击“开局场景 > Fabric 网络”，然后点击“业务部署”进入业务 部署页面，在该页面中点击“安全组/资源组”。

#创建安全组。
```

点击“创建”，进入创建安全组页面视图，创建Sales_Wired，之后点击确定。 采用相同的步骤创建剩下的4 个安全组。

```cli
#创建资源组。
```

创建资源组E_mail，成员为172.17.3.3/32。 步骤 2 创建策略控制矩阵

```cli
#切换页面。
```

点击“策略控制”进入策略控制配置页面，然后点击“创建”，新建一个策略控制矩阵。

```cli
#配置策略控制矩阵。

#设备选中Border、Edge_1、Edge_2，有线用户之间的访问由Edge_1、2 进行策略矩阵的执行， 但本实验中使用Border 作为AC，并且WLAN 的业务为隧道转发，因此还需在Border 上也执行 策略矩阵。

#配置策略控制矩阵。

#在空白处点击“+”，创建一个互访规则。
#在“缺省权限”一栏中选择“禁止”，勾选“反向规则”，点击“确定”。
```

最后点击“部署”，将策略矩阵部署到设备上。 按规划，策略矩阵应实现：Market 的有线用户可以访问RD，RD 无法访问E_mail 资源组。 注意虽然Sales 部门的两个安全组与RD 之间未配置VN 互通，在Fabric 内无法实现路由可达， 但他们可以通过外部网络（即AR3）实现路由可达，因此需明确在策略矩阵中禁止。 对于策略矩阵我们应只放通需要通信的，其余全保持禁止。 步骤 3

```cli
IP 安全组订阅
```

本场景不需要。 6.1.2.7.2 准入认证 针对用户准入认证配置，首先需要在控制器的用户管理页面配置用户组、用户认证账号，用户 可以通过该账号进行准入认证。 配置完用户账号后，需要配置认证授权，包括：认证规则、授权结果和授权规则。 步骤 1 用户组以及用户账号创建 创建用户组以及用户，参照用户认证账号规划完成。

# 进入用户管理页面。

```cli
#在iMaster NCE 控制器首页点击“开局场景 > Fabric 网络”，然后点击“业务部署”，在该页 面中点击“用户管理”进入用户管理页面。

#创建用户组。
```

创建用户组RD。 按照同样方式创建用户组Sales、Market。

注意每次创建完用户组之后，需要点击一下ROOT 组，这样新创建的用户组才是在ROOT 组 下，否则将会是嵌套创建在上一个组内。

```cli
#创建用户账号。

#在对应的用户组中创建对应的账号。 以用户kris 为例（RD 用户组内），去勾选“下次登录修改密码”，以及对于RD 内的用户，无 需使用Portal 认证，在“允许登录方式”中去勾选Portal。 按照同样步骤创建另外两个账号在对应的用户组中。 步骤 2 创建认证规则 按规划完成认证规则配置。

#切换页面。

#在本实验中，认证规则无需再手工创建，控制器缺省的认证规则“Default”，可直接作为所有 用户的认证规则。
```

但此处需修改改认证规则，点击“Default”规则的“操作”一栏中的“修改”按钮，编辑该缺 省规则，勾选如上图所示三个认证协议。 步骤 3 创建授权结果 根据规划完成授权结果创建，在本步骤我们会为sales、market 的有线、无线用户以及RD 分 别创建不同的授权结果。

```cli
#切换页面。
```

点击创建，创建新的授权结果。

```cli
#在授权结果中进行安全组、VLAN 授权。 确认无误后点击“确定”。 此时系统提示需要将授权结果绑定到指定站点。在下图所示的页面点击“增加”。
```

选择HQ，将其添加到已选择列表中，然后点击“确定”。 这样就完成了授权结果Sales_Wired_Result 的配置。 以相同步骤，创建剩下的4 个授权结果，并与站点HQ 绑定。需注意的是这4 个授权结果中的 授权VLAN 和授权安全组信息都不同，必须根据授权结果数据规划来输入。

步骤 4 创建授权规则

根据规划完成授权规则创建，在本步骤我们会为Sales、Market 的有线、无线用户以及RD 分 别创建不同的授权规则。

```cli
#切换页面。

#在当前页面点击授权规则。
```

接入方式匹配为有线、打开用户组信息匹配，授权结果配置为Sales_Wired_Result。完成配置 后点击“确定”，之后就完成了该条授权规则的配置。 之后按照规划配置剩下的授权规则。

至此授权规则配置完毕。

6.1.2.8 WLAN 业务

本实验使用Border 的随板AC 作为AP 上线的AC。 为实现Border 作为AC 纳管AP，我们需要进行如下配置： 1. 在设备管理中添加AP 到站点HQ。 2. 在站点配置中将AP 分配给Border。 3. 在站点配置中创建一个用于AP 上线、纳管的网段，并配置其VLAN ID 为2。 4. 在站点配置中设置Border 的无线PnP 管理VLAN 为2。 5. 在Border 的WEB 页面中手动配置CAPWAP 隧道源接口为VLANIF2。 之后即可按照规划登录Border 的WEB 页面，配置WLAN 业务。

步骤 1 AP 上线配置

```cli
#添加AP。

#在“设计”-“设备管理”中为站点HQ 添加设备（协议选择为NETCONF），通过ESN 码添加 AP，但此时还未完成相关配置，AP 无法上线，状态为未注册，属于正常状态。

#分配AP。

#在“配置”-“站点配置”中选择交换机的管理Fit AP 功能，点击Border，之后点击增加，将 AP1 分配给Border。

#创建子网。

#在当前页面点击“子网”，之后点击创建，创建用于AP 上线的子网。
```

按照上图配置子网参数，通过该子网，AP 将获取AC 地址以及控制器IP 地址。

```cli
#设置Border 的无线PnP VLAN。

#在当前页面点击“站点”-“管理VLAN”，选择Border，之后点击修改。
#修改无线自协商管理VLAN 为2，这样Border 会通过LLDP 协议一直向下游传递该配置，ACC_2 识别到接口GE0/0/24 对端为AP 之后，会自动将AP 划分到VLAN2，同时从ACC_2 到Border 之 间的VLAN2 也会被放通。

#在Border 的WEB 界面中设置CAPWAP 隧道源地址。
```

设置CAPWAP 通信源接口为VLANIF2。

```cli
#检查AP 上线状态。

[Border]display ap all
```

Total AP information: nor  : normal          [1] ExtraInfo : Extra information P    : insufficient power supply --------------------------------------------------------------------------------------------------------- ID    MAC            Name Group   IP            Type              State  STA  Uptime    ExtraInfo --------------------------------------------------------------------------------------------------------- 0    f4de-af36-b580  AP1  default 172.16.20.183 AirEngine5760-10 nor    0    5H:13M:30S - --------------------------------------------------------------------------------------------------------- AP1 成功被识别并加入到VLAN2，通过VLANIF2 的地址池获取到IP 地址、AC 地址后，正常注 册到Border。

```cli
#在设备管理中，AP1 同样正常注册到了控制器。 步骤 2 Portal 业务相关配置 在本实验中我们使用iMaster NCE 作为Portal 服务器，认证设备经由AR3 的源地址转换与 Portal 服务器进行通信，为保证Portal 服务器能够与认证设备进行通信，需主动将认证设备用 于监听Portal 服务器消息的端口进行放通。 在本实验中我们使用Border 作为WAC，为此需要将Border 与Portal 服务器进行通信的IP 及 其相应的端口号（UDP 2000）进行放通。

#在出口路由器AR3 上配置静态NAT。

[AR3]interface GigabitEthernet0/0/9

[AR3-GigabitEthernet0/0/9] nat static protocol udp global current-interface 2000 inside 172.16.10.1 2000 netmask

255.255.255.255
```

此处的172.16.10.1 为Border 的VLANIF 接口地址（DHCP 获取），这也是在AR3 上配置静态地 址绑定的原因，方便在进行映射时固定内部私网IP 地址。 步骤 3 配置控制器侧无线业务 完成控制器侧无线相关配置，下发Portal 认证相关配置到Border。

```cli
#创建无线认证。

#在“站点配置”-“交换机”-“认证”中点击“无线认证”。创建无线认证。
```

按规划完成Sales 无线认证配置。Market 配置方法相同，这里不做演示。

```cli
#无线认证配置结果。

#查看无线认证配置结果，重点需关注认证模板ID，后续在Border 配置无线业务时需关联对应 的模板，需记住不同业务SSID 生成对应的模板ID。 步骤 4 登录Border 的WEB 页面

#进入设备管理页面。

#在“设计”-“设备管理”中选择站点HQ，点击Border，进去Border 的设备管理界面。
```

点击右上角的“设备配置”，在新浏览器页签中将会打开设备的WEB 管理界面。（部分浏览 器可能会拦截弹出页面，请注意浏览器提示）。 之后输入账号密码即可进入设备WEB 管理界面。 步骤 5 创建并配置SSID 模板 分别为Sales、Market 创建不同的SSID 模板，按照规划完成配置。

```cli
#新建SSID 模板。
```

点击“新建”。

新建名称为“Sales”的SSID 模板，点击“确定”。

```cli
#在弹出界面中配置SSID 名称，点击“应用”。 SSID 模板“Sales”创建完成，使用相同方法完成“Market”的创建。 步骤 6 创建并配置VAP 模板 分别为Sales、Market 创建不同的VAP 模板，按照规划完成配置。

#创建VAP 模板。
```

点击“新建”。

新建名称为“Sales”的VAP 模板，点击“确定”。

```cli
#在弹出的界面中按照规划配置VAP 模板参数（业务VLAN ID 以及修改转发模式为隧道转发）， 之后点击应用。

#绑定SSID 模板到VAP 模板。

#在“模板管理”菜单中选择创建的VAP 模板，然后展开该模板，点击该模板下的“SSID 模 板”。在右侧的“SSID 模板”中选择此前创建的SSID 模板“Sales”，然后点击“应用”。

#配置安全模板。

#在VAP 模板中点击安全模板，配置默认安全模板的安全策略为“Open”。

#绑定认证模板到VAP 模板。

#在“模块管理”菜单中选择创建的VAP 模板，然后展开该模板，点击该模板下的“认证模 板”。在右侧的“认证模板”中点击“...”，在弹出的窗口中选择我们在控制器上为SSID： Sales 创建的无线认证模板。 至此，Sales 的VAP 模板创建完毕，按照相关方法完成Market 的VAP 模板配置。 步骤 7 配置AP 组关联VAP 模板 将配置好的VAP 模板关联到AP 组中。

#进入AP 组。
```

进去默认AP 组：default。

```cli
#添加VAP 模板。
```

添加VAP 模板Sales，之后再添加Market。

至此完成VAP 模板配置。

6.1.2.9 结果验证

6.1.2.9.1 准入认证验证 步骤 1 802.1X 认证 使用PC1、2 进行认证，分别测试使用sales、market、kris 这三个账号，查看认证通过之后获 取的IP 地址、交换机授权结果。

```cli
#修改网卡属性。
```

以PC1 为例，进入操作系统的 “控制面板 > 网络和Internet > 网络和共享中心 > 更改适配 器设置”页面，找到终端与接入交换机连接的网卡，右键单击该网卡，选择“属性”。

```cli
#身份认证。
```

点击“身份验证”页签，然后点击“其他设置”。在弹出的窗口中选择“用户身份验证”，并 点击“替代凭据”。

```cli
#在系统弹出的替换凭据窗口，在该窗口中输入用户名及密码，此处输入在iMaster NCE 上所创 建的用户名及密码，这里以sales 为例。

#PC1 上登录kris。
```

PS C:\Users\PC1\Desktop> ipconfig

Windows IP 配置

以太网适配器 Ethernet0:

连接特定的 DNS 后缀 . . . . . . . : 本地链接 IPv6 地址. . . . . . . . :  fe80::a46b:62f8:a696:b974%12 IPv4 地址 . . . . . . . . . . . . :        172.17.30.225 子网掩码  . . . . . . . . . . . . :       255.255.255.0 默认网关. . . . . . . . . . . . . :        172.17.30.254 此时PC1 获取的IP 地址为172.17.30.0/24 网段，符合预期。

```cli
#PC2 上登录sales。
```

C:\Users\PC2>ipconfig

Windows IP 配置

以太网适配器 Ethernet1:

连接特定的 DNS 后缀 . . . . . . . : 本地链接 IPv6 地址. . . . . . . . :  fe80::407a:8e15:4cf:679%5 IPv4 地址 . . . . . . . . . . . . :        172.17.10.138 子网掩码  . . . . . . . . . . . . :       255.255.255.0 默认网关. . . . . . . . . . . . . :        172.17.10.254 此时PC2 获取的IP 地址为172.17.10.0/24 网段，符合预期。

```cli
#PC2 上登录market。
```

C:\Users\PC2>ipconfig

Windows IP 配置

以太网适配器 Ethernet1:

连接特定的 DNS 后缀 . . . . . . . : 本地链接 IPv6 地址. . . . . . . . :  fe80::407a:8e15:4cf:679%5 IPv4 地址 . . . . . . . . . . . . :        172.17.20.167 子网掩码  . . . . . . . . . . . . :       255.255.255.0 默认网关. . . . . . . . . . . . . :        172.17.20.254 此时PC2 获取的IP 地址为172.17.20.0/24 网段，符合预期。

```cli
#Edge_1 查看在线用户。

<Edge_1>display access-user ------------------------------------------------------------------------------------------------------ UserID  Username              IP address                    MAC            Status ------------------------------------------------------------------------------------------------------ 49170   kris                   172.17.30.225                000c-29b3-efea Success ------------------------------------------------------------------------------------------------------ Total: 1, printed: 1
```

此时Edge_1 为认证控制点。

```cli
#查看kris 的详细用户信息。

<Edge_1>display access-user username kris detail
```

Basic: User ID                        : 49170 User name                      : kris Domain-name                  : default User MAC                       : 000c-29b3-efea User IP address                  : 172.17.30.225 User vpn-instance              : RD User IPv6 address               : FE80::A46B:62F8:A696:B974 User IPv6 link local address      : FE80::A46B:62F8:A696:B974 User access Interface           : GigabitEthernet0/0/24 User vlan event                 : Success QinQVlan/UserVlan           : 0/300 User vlan source                : server vlan User access time                : ****/**/** **:**:** User accounting session ID    : Edge_10002400000030019****0300012 User access type                : 802.1x AS ID                          : 0 AS name                        : ACC_1 AS IP                            : 172.16.17.133 AS MAC                         : 9400-b049-9d80 AS Interface                    : GigabitEthernet0/0/24 Terminal Device Type           : Data Terminal Dynamic VLAN ID              : 300

Dynamic group index(Effective): 5 Dynamic group name(Effective) : RD Service Scheme Priority         : 0

AAA: User authentication type        : 802.1x authentication Current authentication method  : RADIUS Current authorization method   : - Current accounting method     : RADIUS

```cli
------------------------------------------------------------------------------ Total: 1, printed: 1 在授权信息中可明确看到授权的VLAN ID 以及授权的安全组。 步骤 2 Portal 认证 使用无线终端（PC3）进行Portal 认证，验证Portal 认证是否可以成功，以及是否能正常获取 相关授权信息。
```

```cli
#连接SSID：Sales。
```

首先展开Wi-Fi 列表，在其中找到此前定义的SSID“Sales”，连接该SSID。

```cli
#查看IP 地址。
```

C:\Users\PC3>ipconfig

Windows IP 配置

无线局域网适配器 WLAN:

连接特定的 DNS 后缀 . . . . . . . : 本地链接 IPv6 地址. . . . . . . . :  fe80::407a:8e15:4cf:679%5 IPv4 地址 . . . . . . . . . . . . :        172.17.11.70 子网掩码  . . . . . . . . . . . . :       255.255.255.0 默认网关. . . . . . . . . . . . . :        172.17.11.254 获取地址为172.17.11.0/24 网段，符合预期。

```cli
#Portal 认证。
```

用户可以打开浏览器并访问任何IP 地址（本实验未部署DNS，因此只能输入IP）。此时由于 该用户未通过认证，因此认证点（交换机Border）会将用户的访问重定向到Portal 认证页面。

输入账号sales，可以成功进行登录。

```cli
#尝试使用market 账号登录。

#在连接SSID：Sales 时，尝试使用账号market 进行登录，会发现认证失败，因为无法匹配控制 器侧的授权规则，通过授权规则匹配SSID 以及用户组信息，实现了该SSID 只能为用户组Sales 内的账号进行认证。

#在Border 查看认证用户。

<Border>display access-user ------------------------------------------------------------------------------------------------------ UserID  Username             IP address                   MAC             Status ------------------------------------------------------------------------------------------------------

32790   sales                  172.17.11.70               200d-b04b-a0c0 Success

------------------------------------------------------------------------------------------------------ Total: 1, printed: 1 在PC3 上重新登录账号sales，之后在Border 查看接入用户。

#在Border 查看用户sales 的详细信息。

<Edge_1>display access-user username sales detail Basic: User ID                        : 32790 User name                      : sales Domain-name                  : aaa46d7bd04792c27bbdc4c User MAC                       : 200d-b04b-a0c0 User IP address                  : 172.17.11.70 User vpn-instance              : OA User IPv6 address               : - User access Interface           : Wlan-Dbss2282 User vlan event                 : Success QinQVlan/UserVlan           : 0/110 User vlan source                : user request User access time                :  ****/**/** **:**:** User accounting session ID     : Border00024000000110db****0200016 User accounting mult session ID : F4DEAF36B580200DB04BA0C0613AC****C5CA321 User access type                : WEB AP name                        : AP1 Radio ID                       : 1 AP MAC                         : f4de-af36-b580 SSID                            : Sales Online time                     : 132(s) Web-server IP address           : 172.99.0.99 Dynamic group index(Effective): 2 Dynamic group name(Effective): Sales_Wireless User inbound data flow(Packet): 365 User inbound data flow(Byte)   : 33,637 User outbound data flow(Packet): 40 User outbound data flow(Byte)   : 33,768 Service Scheme Priority          : 0
```

AAA: User authentication type        : WEB authentication Current authentication method  : RADIUS Current authorization method   : - Current accounting method     : RADIUS

```cli
------------------------------------------------------------------------------ Total: 1, printed: 1
```

已正常授权安全组。 步骤 3 认证日志查看 在iMaster NCE 控制器查看Portal 日志以及RADIUS 日志。

```cli
#切换页面。
```

点击iMaster NCE 控制器的“监控 > 终端认证日志”，进入终端认证日志页面。

```cli
#查看Portal 日志。
```

可查看到所有Portal 上下线日志。

```cli
#查看RADIUS 日志。
```

通过站点以及时间可进行RADIUS 认证日志过滤，在过滤结果中我们可以看到之前PC3 连接 SSID：Sales 时尝试使用账号：market 登录的失败日志，并且记录了失败原因。 6.1.2.9.2 网络连通性验证 验证业务随行是否生效，通过以下场景进行测试： 1. PC1 执行802.1X 认证，登录账号kris，PC2 执行802.1X 认证，登录账号sales，PC3 连接 SSID：Sales，登录账号sales。 2. PC1 执行802.1X 认证，登录账号kris，PC2 执行802.1X 认证，登录账号market，PC3 连接 SSID：Market，登录账号market。

步骤 1 场景1 验证

```cli
#访问资源组测试。
```

C:\Users\PC1>ping 172.17.3.3

正在 Ping 172.17.3.3 具有 32 字节的数据: 请求超时。 请求超时。 请求超时。 请求超时。

172.17.3.3 的 Ping 统计信息:

数据包: 已发送 = 4，已接收 = 0，丢失 = 4 (100% 丢失)，

C:\Users\PC2>ping 172.17.3.3

正在 Ping 172.17.3.3 具有 32 字节的数据:

来自 172.17.3.3 的回复: 字节=32 时间<1ms TTL=253 来自 172.17.3.3 的回复: 字节=32 时间<1ms TTL=253 来自 172.17.3.3 的回复: 字节=32 时间<1ms TTL=253 来自 172.17.3.3 的回复: 字节=32 时间<1ms TTL=253

172.17.3.3 的 Ping 统计信息:

数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 0ms，最长 = 0ms，平均 = 0ms

C:\Users\PC3>ping 172.17.3.3

正在 Ping 172.17.3.3 具有 32 字节的数据: 来自 172.17.3.3 的回复: 字节=32 时间=4ms TTL=254 来自 172.17.3.3 的回复: 字节=32 时间=4ms TTL=254 来自 172.17.3.3 的回复: 字节=32 时间=3ms TTL=254 来自 172.17.3.3 的回复: 字节=32 时间=3ms TTL=254

172.17.3.3 的 Ping 统计信息:

数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 3ms，最长 = 4ms，平均 = 3ms 测试访问资源组E_mail，只有PC1 无法访问。

```cli
#sales 有线、无线用户互访测试。
```

C:\Users\PC3>ipconfig

Windows IP 配置

无线局域网适配器 WLAN:

连接特定的 DNS 后缀 . . . . . . . : 本地链接 IPv6 地址. . . . . . . . : fe80::4c25:e93f:ee11:5ad1%16 IPv4 地址 . . . . . . . . . . . . : 172.17.11.70 子网掩码  . . . . . . . . . . . . : 255.255.255.0 默认网关. . . . . . . . . . . . . : 172.17.11.254

C:\Users\PC3>ping 172.17.10.138 -n 1

正在 Ping 172.17.10.138 具有 32 字节的数据: 来自 172.17.10.138 的回复: 字节=32 时间=5ms TTL=126

172.17.10.138 的 Ping 统计信息:

数据包: 已发送 = 1，已接收 = 1，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 5ms，最长 = 5ms，平均 = 5ms

C:\Users\PC2>ipconfig

Windows IP 配置

以太网适配器 Ethernet1:

连接特定的 DNS 后缀 . . . . . . . : 本地链接 IPv6 地址. . . . . . . . : fe80::407a:8e15:4cf:679%5 IPv4 地址 . . . . . . . . . . . . : 172.17.10.138 子网掩码  . . . . . . . . . . . . : 255.255.255.0 默认网关. . . . . . . . . . . . . : 172.17.10.254

C:\Users\PC2>ping 172.17.11.70 -n 1

正在 Ping 172.17.11.70 具有 32 字节的数据: 来自 172.17.11.70 的回复: 字节=32 时间=4ms TTL=126

172.17.11.70 的 Ping 统计信息:

数据包: 已发送 = 1，已接收 = 1，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 4ms，最长 = 4ms，平均 = 4ms PC2、PC3 此时登录账号同属安全组Sales，属于同一个逻辑网络OA，策略矩阵无限制，可互 访。

```cli
#sales 有线、无线用户访问逻辑网络RD 测试。
```

C:\Users\PC2>ping 172.17.30.225 -n 1

正在 Ping 172.17.30.225 具有 32 字节的数据: 请求超时。

172.17.30.225 的 Ping 统计信息:

数据包: 已发送 = 1，已接收 = 0，丢失 = 1 (100% 丢失)，

C:\Users\PC3>ping 172.17.30.225 -n 1

正在 Ping 172.17.30.225 具有 32 字节的数据: 请求超时。

172.17.30.225 的 Ping 统计信息:

数据包: 已发送 = 1，已接收 = 0，丢失 = 1 (100% 丢失)， 无法访问逻辑网络RD 内的PC1。 步骤 2 场景2 验证

```cli
#PC2、PC3 访问资源组测试。
```

C:\Users\PC2>ping 172.17.3.3 -n 1

正在 Ping 172.17.3.3 具有 32 字节的数据: 来自 172.17.3.3 的回复: 字节=32 时间<1ms TTL=253

172.17.3.3 的 Ping 统计信息:

数据包: 已发送 = 1，已接收 = 1，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 0ms，最长 = 0ms，平均 = 0ms

C:\Users\PC3>ping 172.17.3.3 -n 1

正在 Ping 172.17.3.3 具有 32 字节的数据: 来自 172.17.3.3 的回复: 字节=32 时间=4ms TTL=254

172.17.3.3 的 Ping 统计信息:

数据包: 已发送 = 1，已接收 = 1，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 4ms，最长 = 4ms，平均 = 4ms 都可正常访问。

```cli
#PC2、3 访问逻辑网络RD 测试。
```

C:\Users\PC2>ping 172.17.30.225 -n 1

正在 Ping 172.17.30.225 具有 32 字节的数据:

来自 172.17.30.225 的回复: 字节=32 时间<1ms TTL=125

172.17.30.225 的 Ping 统计信息:

数据包: 已发送 = 1，已接收 = 1，丢失 = 0 (0% 丢失)， 往返行程的估计时间(以毫秒为单位): 最短 = 0ms，最长 = 0ms，平均 = 0ms

C:\Users\PC3>ping 172.17.30.225 -n 1

正在 Ping 172.17.30.225 具有 32 字节的数据: 请求超时。

172.17.30.225 的 Ping 统计信息:

数据包: 已发送 = 1，已接收 = 0，丢失 = 1 (100% 丢失)， PC2 可以访问，PC3 无法访问，符合预期，即Market 有线网络可以访问，无线网络无法访 问。

## 6.1.3 （可选）配置清除

```cli
#在开始实验时，为避免上一个用户所做的配置影响本实验，需要对环境中的iMaster NCE 及网 络设备（Border、Edge_1、Edge_2、ACC_1、ACC_2）进行配置清除，将这些节点的配置还原 为出厂状态。 说明：先删除iMaster NCE 上的配置，再删除网络设备上的配置。
```

6.1.3.1 删除认证规则、授权规则、授权结果
步骤 1 点击iMaster NCE 控制器的“准入 > 准入策略 > 认证授权”，进入认证授权页面。 步骤 2 删除认证规则 如下图所示，点击“认证规则”进入认证规则配置页面。

除默认的认证规则“Default”外，若存在其他自定义的认证规则，则需要选中所有已创建的规 则，点击“删除”。 步骤 3 删除授权规则

点击当前页面中的“授权规则”进入授权规则配置页面，除默认的授权规则“Default”外，若 存在其他自定义的授权规则，则需要选中所有已创建的规则，点击“删除”。 步骤 4 删除授权结果 点击当前页面中的“授权结果”进入授权结果配置页面，除默认的授权结果“允许接入”和 “拒绝接入”外，若存在其他自定义的授权结果，则均需删除。 在待删除的授权结果中点击绑定站点" "按钮，选择“HQ”，点击“删除”，将该授权结 果与HQ 站点解绑定，只有完成该操作，该授权结果才能够被删除。采用相同的步骤，将除了 默认授权结果之外的其他条目全部解除站点绑定。解除站点绑定后，选中所有已创建的授权结 果，点击“删除”。

6.1.3.2 强制下线用户，删除用户账号

说明：为保证用户账号能正常删除，需先对在线用户进行强制下线操作。 步骤 1 点击iMaster NCE 控制器的“准入 > 准入策略 > 用户在线控制”，进入在线用户视图， 选中所有用户，点击“更多 > 强制下线”。 步骤 2 点击iMaster NCE 控制器的“准入 > 准入资源 > 用户管理”，进入用户管理页面。 步骤 3 选中所有已创建的用户账号，点击“删除”。

6.1.3.3 删除策略控制矩阵和安全组

步骤 1 点击iMaster NCE 控制器的“准入 > 策略控制”进入策略控制配置页面。 步骤 2 点击“ ”图标删除已创建的策略矩阵。 步骤 3 点击iMaster NCE 控制器的“准入 > 安全组”进入安全组配置页面。选中所有已创建的安 全组，点击“删除”。

6.1.3.4 删除VN 互通策略和VN

步骤 1 点击iMaster NCE 控制器的“配置 > 逻辑网络”进入逻辑网络配置页面，在该页面中点击 “VN 互通”进入VN 互通策略配置页面，删除已创建的VN 互通策略。 步骤 2 在每一个已创建的VN 的“操作”栏中点击“ ”图标，分别将VN 删除。

6.1.3.5 删除接入管理

步骤 1 点击iMaster NCE 控制器的“配置 > Fabric 管理”进入Fabric 管理页面，在该页面中点击 “接入管理”进入接入管理配置页面。

步骤 2 缺省时当前页面的“认证控制点”选择的是Edge_1，将页面滚动到底部，点击“重置” 按钮将Edge_1 的接入管理配置进行重置。 步骤 3 在“认证控制点”中选择Edge_2，将页面滚动到底部，点击“重置”按钮将Edge_2 的接 入管理配置进行重置。

6.1.3.6 删除网络服务资源和外部网络

步骤 1 点击iMaster NCE 控制器的“配置 > Fabric 管理” 进入Fabric 管理页面。 步骤 2 在该页面中点击“外部网络”一栏中的“ ”图标进入外部网络配置页面，在该页面中 分别点击已创建的外部网络的的“ ”图标，将所有外部网络删除。 步骤 3 在Fabric 管理页面点击“网络服务资源”一栏中的“ ”图标进入网络服务资源配置页 面，在该页面中点击已创建的网络服务资源的“ ”图标，将其删除。

6.1.3.7 删除Fabric 中的设备和Fabric

步骤 1 点击iMaster NCE 控制器的“配置 > Fabric 管理”进入Fabric 管理页面 步骤 2 在当前页面中，点击右侧的“ ”图标，然后勾选所有节点，点击“删除设备”。 步骤 3 如下图所示步骤，删除当前的Fabric。

6.1.3.8 删除Fabric 全局资源池和Underlay 自动化资源池

步骤 1 点击iMaster NCE 控制器的“设计 > 网络设置”进入网络设置页面，在该页面中选择已创 建的VLAN，点击删除“ ”图标将其删除；选择已创建的BD，点击删除“ ”图标将 其删除；选择已创建的VNI，点击删除“ ”图标将其删除。 步骤 2 在当前页面点击“Underlay 自动化资源池”进入Underlay 自动化资源池配置页面，在该 页面中选择已创建的互联VLAN，点击删除“ ”图标将其删除；选择已创建的互联IP， 点击删除“ ”图标将其删除；选择已创建的环回口IP，点击删除“ ”图标将其删 除。

6.1.3.9 删除控制器纳管设备

步骤 1 点击iMaster NCE 控制器的“设计 > 设备管理”进入设备管理页面，选中HQ 站点下的 所有设备，点击“删除设备”。

6.1.3.10 删除站点

步骤 1 点击iMaster NCE 控制器的“设计 > 站点管理”进入站点管理页面，选中站点，然后点击 删除图标“ ”删除站点。

6.1.3.11 删除认证模板和服务器模板

步骤 1 删除认证模板。 点击iMaster NCE 控制器的“设计 > 模板管理”进入模板管理页面，在该页面左侧的菜单中选 择“认证模板”，然后勾选所有已创建的模板，点击“删除”按钮。 步骤 2 删除RADIUS 服务器模板。 继续在页面左侧菜单中选择“RADIUS 服务器”，然后勾选所有已创建的RADIUS 服务器模板， 点击“删除”按钮。 步骤 3 删除Portal 服务器模板。 继续在页面左侧菜单中选择“Portal 服务器”，然后勾选所有已创建的Portal 服务器模板，点 击“删除”按钮。

6.1.3.12 删除交换机上的配置

分别登录Border、Edge_1、Edge_2、ACC_1、ACC_2，执行如下命令，将设备恢复出厂状态。 <Border>system-view Enter system view, return user view with Ctrl+Z.

```cli
[Border]reset netconf db-configuration

Warning: This operation will clear the database configuration and saved configuration file and restart the device. Continue? [Y/N]:y

6.1.3.13 删除AR3 上的配置
```

要将AR3 当前的配置清除，恢复缺省状态，则在登录设备后执行如下命令： <AR3>set factory-configuration from default Warning: The current factory configuration will be replaced, and it's irreversible. Are you sure to set the factory configuration?[Y/N]:y Info: Successfully set factory config! <AR3>factory-configuration reset Warning: It will clean the configuration which you have saved. If you have set the factory-configuration by hand, it will start from the modified factory-configuration, else it will start from the original one, when you restart the device. Continue? [y/n]:y

```cli
Info: Successfully set factory config! <AR3>reset saved-configuration Warning: This will delete the configuration in the flash memory. The device configurations will be erased to reconfigure. Are you sure? (y/n):y Info: Clear the configuration in the device successfully. <AR3>reboot fast System will reboot! Continue? [y/n]:y
```

## 6.1.4 思考题

```cli
#在iMaster NCE 控制器上配置的网络服务资源，逻辑网络调用之后，底层的配置如何实现逻辑 网络到网络服务资源的路由可达？
```

## 7 广域互联网络部署
