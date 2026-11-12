---
doc_id: "hcie-datacom-v1.0-training-18"
title: "SRv6基础配置与基于iMaster NCE-IP部署"
book: "HCIE-Datacom-V1.0-Training"
book_title: "HCIE-Datacom V1.0 培训教材"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "training"
source_pdf: "HCIE-Datacom+V1.0+培训教材.pdf"
seq: 18
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---
# SRv6基础配置与基于iMaster NCE-IP部署

## L3VPNv4 over SRv6 BE（续）

### 配置思路回顾

1. 完成设备接口 IPv6 地址及 IS-IS 配置（略）。
2. 在 PE1 与 PE2 之间建立 MP-BGP 对等体关系。
3. 骨干网上使能 Segment Routing，建立 SRv6 BE 路径。
4. PE 上配置使能 IPv4 地址族 VPN 实例。
5. PE 之间配置 MP-IBGP 交换路由信息。
6. 结果验证。

> （原图：CE1—PE1—P—PE2—CE2；骨干 `2001:DB88:12::/96`、`2001:DB88:23::/96`；Loopback0：`2001:DB8:1::1` / `2001:DB8:2::2` / `2001:DB8:3::3`；CE Loopback1：`10.1.4.4/32`、`10.1.5.5/32`。）

### 配置 VPN 实例（PE1 示例，PE2 略）

```cli
[~PE1] ip vpn-instance vpna
[*PE1-vpn-instance-vpna] ipv4-family
[*PE1-vpn-instance-vpna-af-ipv4] route-distinguisher 100:1
[*PE1-vpn-instance-vpna-af-ipv4] vpn-target 111:1 both
[*PE1-vpn-instance-vpna-af-ipv4] quit
[*PE1-vpn-instance-vpna] quit
[~PE1] bgp 100
[*PE1-bgp] ipv4-family vpn-instance vpna
[*PE1-bgp-vpna] peer 10.0.14.4 as-number 65000
[*PE1-bgp-vpna] segment-routing ipv6 best-effort
[*PE1-bgp-vpna] segment-routing ipv6 locator as100
[*PE1-bgp-vpna] commit
[~PE1-bgp-vpna] quit
[~PE1-bgp] quit
```

### 配置说明：私网路由迭代 SRv6 BE

1. `bgp { as-number-plain | as-number-dot }`：进入 BGP 视图。
2. `ipv4-family vpn-instance vpn-instance-name`：进入 BGP-VPN 实例 IPv4 地址族视图。
3. `segment-routing ipv6 best-effort`：使能根据路由携带的 SID 属性进行私网路由迭代。
4. `segment-routing ipv6 locator locator-name [ auto-sid-disable ]`：使能 VPN 私网路由携带 SID 属性。
   - 未配置 `auto-sid-disable`：支持动态 SID 分配；若 locator 下存在静态 SID 则用静态，否则动态分配。
   - 配置 `auto-sid-disable`：BGP 不动态分配 SID。
5. `commit` 提交配置。

### 验证：PE2 本地 SID 表

```cli
<PE2> display segment-routing ipv6 local-sid forwarding

My Local-SID Forwarding Table
-------------------------------------
SID         : 2001:DB8:300::1:0:0/128    FuncType : End
LocatorName : as100                      LocatorID: 2
SID         : 2001:DB8:300::1:0:1/128    FuncType : End
LocatorName : as100                      LocatorID: 2
SID         : 2001:DB8:300::1:0:2/128    FuncType : End.X
LocatorName : as100                      LocatorID: 2
SID         : 2001:DB8:300::1:0:3/128    FuncType : End.X
LocatorName : as100                      LocatorID: 2
SID         : 2001:DB8:300::1:0:20/128   FuncType : End.DT4
LocatorName : as100
```

PE2 本地生成 End.DT4 类型 SID，并发布给 PE1。

### 验证：PE1 查看 VPNv4 路由

```cli
<PE1> display bgp vpnv4 all routing-table 10.1.5.5

BGP local router ID : 10.0.1.1
Local AS number : 100
Total routes of Route Distinguisher(100:1): 1

BGP routing table entry information of 10.1.5.5/32:
Label information (Received/Applied): 3/NULL
From: 2001:DB8:3::3 (10.0.3.3)
Route Duration: 0d00h15m54s
Relay IP Nexthop: FE80::DE99:14FF:FE7A:C301
Relay IP Out-Interface: GigabitEthernet0/3/0.12
Relay Tunnel Out-Interface:
Original nexthop: 2001:DB8:3::3
Qos information : 0x0
Ext-Community: RT <111 : 1>
Prefix-sid: 2001:DB8:300::1:0:20
AS-path Nil, origin incomplete, MED 0, localpref 100, pref-val 0,
valid, internal, best, select, pre 255, IGP cost 20
Not advertised to any peer yet
```

说明：对等体 IPv6 地址为 `2001:DB8:3::3`；`10.1.5.5` 对应的 SID 与 PE2 本地分配相同。

### 验证：PE1 查看 vpna 路由

```cli
<PE1> display ip routing-table vpn-instance vpna 10.1.5.5 verbose

Route Flags: R - relay, D - download to fib, T - to vpn-instance, B - black hole
------------------------------------------------------------------------------
Routing Table : vpna
Summary Count : 1

Destination: 10.1.5.5/32
Protocol: IBGP               Process ID: 0
Preference: 255              Cost: 0
NextHop: 2001:DB8:300::1:0:20
Neighbour: 2001:DB8:3::3
State: Active Adv Relied     Age: 00h17m40s
Tag: 0                       Priority: low
Label: 3                     QoSInfo: 0x0
IndirectID: 0x1000177        Instance:
RelayNextHop: 2001:DB8:300::1:0:20
Interface: SRv6 BE
TunnelID: 0x0                Flags: RD
```

PE1 转发目的地址为 `10.1.5.5` 的报文时，直接使用该 IPv6 SID；接口类型为 **SRv6 BE**。

### 结果验证：CE1 Ping CE2

```cli
<CE1> ping -a 10.1.4.4 10.1.5.5
PING 10.1.5.5: 56 data bytes, press CTRL_C to break
Reply from 10.1.5.5: bytes=56 Sequence=1 ttl=254 time=1 ms
Reply from 10.1.5.5: bytes=56 Sequence=2 ttl=254 time=1 ms
Reply from 10.1.5.5: bytes=56 Sequence=3 ttl=254 time=1 ms
Reply from 10.1.5.5: bytes=56 Sequence=4 ttl=254 time=1 ms
Reply from 10.1.5.5: bytes=56 Sequence=5 ttl=254 time=1 ms
```

---

## L3VPNv4 over SRv6 Policy

### 组网需求

1. PE1 和 PE2 各有一个 CE 属于 VPN 实例 `vpna`。
2. 在骨干网部署 L3VPN 迭代 SRv6 Policy，使 CE1 与 CE2 的 Loopback1 可互通。

### 配置思路

1. 完成设备接口 IPv6 地址及 IS-IS 配置（略）。
2. 在 PE1 与 PE2 之间建立 MP-BGP 对等体关系。
3. 骨干网上使能 Segment Routing，建立 SRv6 Policy 路径。
4. PE 上配置使能 IPv4 地址族 VPN 实例，PE 之间配置 MP-IBGP 交换路由信息。
5. 配置隧道策略，引入私网流量。
6. 结果验证。

本实验中 SRv6 Policy 路径通过指定 **END** 类型 SID 建立。PE1 / P / PE2 对应 SID 分别为：

- `2001:DB8:1000::111`
- `2001:DB8:2000::222`
- `2001:DB8:3000::333`

### 建立 MP-IBGP

```cli
[~PE1] bgp 100
[~PE1-bgp] peer 2001:DB8:3::3 as-number 100
[*PE1-bgp] peer 2001:DB8:3::3 connect-interface loopback 0
[*PE1-bgp] ipv4-family vpnv4
[*PE1-bgp-af-vpnv4] peer 2001:DB8:3::3 enable
[*PE1-bgp-af-vpnv4] commit
[~PE1-bgp-af-vpnv4] quit
[~PE1-bgp] quit
```

```cli
<PE1> display bgp vpnv4 all peer

BGP local router ID : 10.0.1.1
Local AS number : 100
Total number of peers : 1
Peers in established state : 1

Peer            V    AS  MsgRcvd MsgSent Up/Down  State
2001:DB8:3::3   4   100        3       4 00:00:04 Established
```

### 配置静态 END SID（PE1 示例，P/PE2 略）

推荐静态配置 SRv6 SID。

```cli
[~PE1] segment-routing ipv6
[*PE1-segment-routing-ipv6] encapsulation source-address 2001:DB8:1::1
[*PE1-segment-routing-ipv6] locator as1000 ipv6-prefix 2001:DB8:1000:: 64 static 32
[*PE1-segment-routing-ipv6-locator] opcode ::111 end
[*PE1-segment-routing-ipv6-locator] quit
[*PE1-segment-routing-ipv6] quit
[*PE1] bgp 100
[*PE1-bgp] ipv4-family vpnv4
[*PE1-bgp-af-vpnv4] peer 2001:DB8:3::3 prefix-sid
[*PE1-bgp-af-vpnv4] quit
[~PE1-bgp] quit
[~PE1] isis 1
[~PE1-isis-1] segment-routing ipv6 locator as1000 auto-sid-disable
[*PE1-isis-1] commit
[~PE1-isis-1] quit
```

配置步骤说明：

1. `locator ...`：配置 SRv6 Locator。
2. `opcode func-opcode end`：配置静态 End SID Opcode。
3. `opcode func-opcode end-x interface interface-name nexthop nexthop-address [ no-psp ]`：配置静态 End.X SID Opcode。
4. `quit` 退出 Locator 视图。

### 配置 SRv6 Policy（PE1 示例，PE2 略）

按先后顺序指定 P、PE2 的 END SID；并指定隧道 Color 与 Endpoint。

```cli
[~PE1] segment-routing ipv6
[~PE1-segment-routing-ipv6] segment-list list1
[*PE1-segment-routing-ipv6-segment-list-list1] index 5 sid ipv6 2001:DB8:2000::222
[*PE1-segment-routing-ipv6-segment-list-list1] index 10 sid ipv6 2001:DB8:3000::333
[*PE1-segment-routing-ipv6-segment-list-list1] commit
[~PE1-segment-routing-ipv6-segment-list-list1] quit
[~PE1-segment-routing-ipv6] srv6-te-policy locator as1000
[*PE1-segment-routing-ipv6] srv6-te policy policy1 endpoint 2001:DB8:3::3 color 101
[*PE1-segment-routing-ipv6-policy-policy1] binding-sid 2001:DB8:1000::100
[*PE1-segment-routing-ipv6-policy-policy1] candidate-path preference 100
[*PE1-segment-routing-ipv6-policy-policy1-path] segment-list list1
[*PE1-segment-routing-ipv6-policy-policy1-path] commit
[~PE1-segment-routing-ipv6-policy-policy1-path] quit
[~PE1-segment-routing-ipv6-policy-policy1] quit
[~PE1-segment-routing-ipv6] quit
```

#### 配置 Segment List

1. `system-view` → `segment-routing ipv6`
2. `segment-list list-name`：创建候选路径显式路径。
3. `index index sid ipv6 ipv6address`：按 index 从小到大生成 SID 栈；每个 Segment List 最多 10 个 SID。
4. `commit`

#### 配置 SRv6 Policy

1. `srv6-te-policy locator locator-name`：关联 Locator，用于指定 Binding SID。
2. `srv6-te policy name-value endpoint endpoint-ip color color-value`：创建 Policy。
3. （可选）`binding-sid binding-sid`：取值须在 Locator 静态段范围内。
4. `candidate-path preference preference`：配置候选路径及优先级；preference 越大优先级越高。
5. `segment-list list-name [ weight weight-value | path-mtu mtu-value ] *`：绑定已创建的 Segment List。
6. `commit`

### 配置 VPN 实例与引流（PE1）

```cli
[~PE1] ip vpn-instance vpna
[*PE1-vpn-instance-vpna] ipv4-family
[*PE1-vpn-instance-vpna-af-ipv4] route-distinguisher 100:1
[*PE1-vpn-instance-vpna-af-ipv4] vpn-target 111:1 both
[*PE1-vpn-instance-vpna-af-ipv4] quit
[*PE1-vpn-instance-vpna] quit
[*PE1] bgp 100
[*PE1-bgp] ipv4-family vpn-instance vpna
[*PE1-bgp-vpna] segment-routing ipv6 traffic-engineer best-effort
[*PE1-bgp-vpna] segment-routing ipv6 locator as1000
[*PE1-bgp-vpna] commit
[~PE1-bgp-vpna] quit
[~PE1-bgp] quit
```

说明：`segment-routing ipv6 traffic-engineer best-effort` —— 当网络中存在 SRv6 BE 时，可配置 `best-effort`，使 SRv6 Policy 故障时业务可用 SRv6 BE 作为逃生路径。

### 配置隧道策略引入私网流量

```cli
[~PE1] route-policy p1 permit node 10
[*PE1-route-policy] apply extcommunity color 0:101
[*PE1-route-policy] quit
[*PE1] bgp 100
[*PE1-bgp] ipv4-family vpnv4
[*PE1-bgp-af-vpnv4] peer 2001:DB8:3::3 route-policy p1 import
[*PE1-bgp-af-vpnv4] quit
[*PE1-bgp] quit
[*PE1] tunnel-policy p1
[*PE1-tunnel-policy-p1] tunnel select-seq ipv6 srv6-te-policy load-balance-number 1
[*PE1-tunnel-policy-p1] quit
[*PE1] ip vpn-instance vpna
[*PE1-vpn-instance-vpna] ipv4-family
[*PE1-vpn-instance-vpna-af-ipv4] tnl-policy p1
[*PE1-vpn-instance-vpna-af-ipv4] commit
[~PE1-vpn-instance-vpna-af-ipv4] quit
[~PE1-vpn-instance-vpna] quit
```

### 验证：SRv6 Policy 状态

```cli
<PE1> display srv6-te policy

PolicyName              : policy1
Color                   : 101
Endpoint                : 2001:DB8:3::3
TunnelId                : 1
Binding SID             : 2001:DB8:1000::100
TunnelType              : SRv6-TE Policy
Policy State            : Up
Admin State             : UP
Candidate-path Count    : 1
Candidate-path Preference : 100
Path State              : Active
Path Type               : Primary
Protocol-Origin         : Configuration(30)
Segment-List            : list1
List State              : Up
Weight                  : 1
SID                     : 2001:DB8:2000::222
                          2001:DB8:3000::333
```

### 验证：VPNv4 路由携带 Color

```cli
<PE1> display bgp vpnv4 all routing-table 10.1.5.5

BGP local router ID : 10.0.1.1
Local AS number : 100
Total routes of Route Distinguisher(100:1): 1

BGP routing table entry information of 10.1.5.5/32:
Label information (Received/Applied): 3/NULL
From: 2001:DB8:3::3 (10.0.13.3)
Route Duration: 0d00h03m30s
Original nexthop: 2001:DB8:3::3
Ext-Community: RT <111 : 1>, Color <0 : 101>
Prefix-sid: 2001:DB8:3000::1:0:1E
AS-path 65000, origin incomplete, MED 0, localpref 100, pref-val 0,
valid, internal, best, select, pre 255, IGP cost 20
Not advertised to any peer yet
```

根据 Color 属性迭代对应的 SRv6 Policy。

### 验证：出接口为 SRv6 Policy

```cli
<PE1> display ip routing-table vpn-instance vpna 10.1.5.5 verbose

Routing Table : vpna
Summary Count : 1
Destination: 10.1.5.5/32
Protocol: IBGP               Process ID: 0
Preference: 255              Cost: 0
NextHop: 2001:DB8:3::3
Neighbour: 2001:DB8:3::3
State: Active Adv Relied     Age: 00h08m38s
RelayNextHop: ::
Interface: policy1
TunnelID: 0x000000003400000001
Flags: RD
```

### CE1 Ping 验证

```cli
<CE1> ping -a 10.1.4.4 10.1.5.5
PING 10.1.5.5: 56 data bytes, press CTRL_C to break
Reply from 10.1.5.5: bytes=56 Sequence=1 ttl=254 time=1 ms
Reply from 10.1.5.5: bytes=56 Sequence=2 ttl=254 time=1 ms
Reply from 10.1.5.5: bytes=56 Sequence=3 ttl=254 time=1 ms
Reply from 10.1.5.5: bytes=56 Sequence=4 ttl=254 time=1 ms
Reply from 10.1.5.5: bytes=56 Sequence=5 ttl=254 time=1 ms
```

---

## 基于 iMaster NCE-IP 部署 SRv6

### 为什么用控制器

现网静态部署 SRv6 会带来运维挑战：周期长、无法按全局规划路径、难以按网络质量调整转发路径。通过 iMaster NCE-IP 部署可较好地规避这些问题。

iMaster NCE-IP 通过以下协议部署 SRv6 隧道及相关 VPN 业务：

- **BGP-LS**：拓扑信息收集并向控制器通告。存在 RR 时可仅在 RR 上部署 BGP-LS 并与控制器建邻。
- **BGP IPv6 SR Policy**：控制器与转发器建立邻居，下发 SRv6 Policy 指导转发；可部署 RR，PE 与控制器均作为 RR 客户端以简化邻居数量。
- **NETCONF**：控制器将业务配置下发给转发器（本文不展开 NETCONF 配置）。

相关角色：

- **IGP**：路由器生成网络拓扑信息（带宽、时延、SID 等）。
- **BGP-LS**：拓扑收集与上报。
- **BGP IPv6 SR Policy**：控制器下发路径。

### SRv6 Policy 隧道发布流程

控制器能力：

- 创建双向隧道（创建源→宿时同时创建宿→源）。
- 支持隧道模板、Color 模板，简化重复配置。

在华为云广域网络解决方案中：

- SRv6 Policy 配置信息由 **BGP IPv6 SR Policy** 下发。
- 隧道状态由 **BGP-LS** 上报。

流程：

1. 设备通过 BGP-LS 将网络拓扑上报控制器，控制器基于需求形成转发路径。
2. 控制器通过 BGP IPv6 SR Policy 将计算出的路径下发给设备。
3. 相关流量按路径转发。

### 算路所需关键信息

iMaster NCE-IP 计算 SRv6 路径需通过 IGP 收集：

- SID：END SID、END.X SID
- Locator：节点配置后生成 Locator 网段路由，经 IGP 在 SR 域扩散
- 接口带宽：物理带宽、可预留带宽
- 接口时延与丢包率
- 网络拓扑信息

BGP-LS 将 IGP 收集的信息发布给 iMaster NCE-IP。

### IGP 基本配置

华为 SRv6 解决方案中，IGP 推荐选用扩展 **IS-IS** 收集网络基本信息。

```cli
[P1] isis 1
[P1-isis-1] is-level level-2
[P1-isis-1] cost-style wide
# narrow 模式不支持携带 TE 场景所需 TE 信息（带宽等），需配置为 wide
[P1-isis-1] network-entity 49.0001.0010.0000.0005.00
[P1-isis-1] is-name P1
[P1-isis-1] ipv6 enable topology ipv6
[P1-isis-1] ipv6 bgp-ls enable level-2
# 将 IS-IS 拓扑经 BGP-LS 发到控制器；该功能只需在 RR 上执行即可
# （IGP 域内实际只需一台设备与控制器通过 BGP-LS 传递拓扑）
[P1-isis-1] ipv6 advertise link attributes
# 开启在 LSP 中携带链路属性相关 TLV（接口 IPv6 地址、接口 Index 等）
[P1-isis-1] ipv6 metric-delay advertisement enable level-1-2
# 配置 IPv6 时延发布，由 IS-IS 收集/扩散链路时延，经 BGP-LS 上报控制器算路
[P1-isis-1] ipv6 traffic-eng level-2
# 使能 IS-IS TE，向 TE 模块发送链路带宽信息
[P1] interface GigabitEthernet0/3/0
[P1-GigabitEthernet0/3/0] isis ipv6 enable 1
[P1-GigabitEthernet0/3/0] isis circuit-type p2p
# 接口网络类型必须为 P2P，否则控制器无法形成网络拓扑
```

### BGP-LS 上报拓扑信息

每台路由器维护链路状态数据库（接口 IP、链路度量、TE 度量、链路带宽、可预留带宽等）。BGP 进程从这些数据库获取信息，通过扩展 NLRI 携带：

- Node NLRI
- Link NLRI
- Topology Prefix NLRI（IPv4 / IPv6）

上报给控制器，并通告给 BGP-LS 邻居。

### BGP-LS 部署方案

iMaster NCE-IP 至少需与两类设备建立 BGP-LS 邻居：

1. 与 AS 内某网络节点：获取网络拓扑（一般使用 BGP RR）。
2. 与隧道源节点：获取 SRv6 Policy 隧道状态。

两种方案：

| 方案 | 说明 | 推荐 |
|------|------|------|
| 方案一 | 控制器与所有 PE、P 建立 BGP-LS 邻居 | — |
| 方案二 | 控制器与 RR 建立 BGP-LS，其余设备与 RR 建立 BGP-LS | **推荐**（减少控制器维护的邻居数） |

### 建立 BGP-LS 邻居

```cli
[P1] bgp 65001
[P1-bgp] peer 2000::102 as-number 65001
[P1-bgp] peer 2000::102 connect-interface LoopBack0
[P1-bgp] link-state-family unicast
[P1-bgp-af-ls] peer 2000::102 enable
```

```cli
[P1] display bgp link-state unicast peer

BGP local router ID : 1.0.0.5
Local AS number : 65001
Total number of peers : 1
Peers in established state : 1

Peer       V      AS  MsgRcvd MsgSent OutQ Up/Down    State    PrefRcv
2000::102  4   65001    72877   72106     0 1039h31m Established 0
```

BGP-LS 邻居可使用 IPv4 或 IPv6 地址建立；本课程主要使用 IPv6。
