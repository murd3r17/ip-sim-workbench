---
doc_id: "hcip-datacom-advanced-rs-training-08"
title: "MPLS VPN原理与配置"
book: "HCIP-Datacom-Advanced-RS-Training"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "training"
source_pdf: "HCIP-Datacom-Advanced+Routing+&+Switching+Technology+V1.0+培训教材(1).pdf"
seq: 8
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# MPLS VPN原理与配置

## 1. 报文转发过程（续）

典型双标签转发：

1. 入口 PE 根据入接口找 VPN 实例，匹配目的前缀打**内层标签（I-L）**，再按下一跳 Tunnel-ID 打**外层公网标签（O-L）** 送入隧道
2. 骨干 P 只交换外层标签，直至出口 PE
3. 出口 PE 去掉外层标签，按内层标签确定下一跳并剥离，以纯 IPv4 发给 CE
4. CE 按常规 IPv4 处理

> （原图：用户 X/Y 多站点，CE–PE–P–PE–CE，报文携带 O-L 与 I-L。）

私网标签分配：每路由一标签，或每 VPN 实例一标签（省标签）。收到 VPNv4 后与本地 RT **交叉**；再按下一跳做**隧道迭代**，成功才装入 VPN 路由表。

## 2. 配置命令摘要

### VPN 实例

```cli
[PE] ip vpn-instance vpn-instance-name
[PE-vpn-instance-InstanceName] ipv4-family
[PE-vpn-instance-InstanceName] route-distinguisher route-distinguisher
[PE-vpn-instance-InstanceName] vpn-target vpn-target &<1-8> [ both | export-extcommunity | import-extcommunity ]
[PE-GigabitEthernet0/0/0] ip binding vpn-instance vpn-instance-name
```

RD 配置后一般不可直接改；绑定/解绑接口会清该口 IP 与相关特性，需重配。

### MP-BGP

```cli
[PE] bgp { as-number-plain | as-number-dot }
[PE-bgp] peer ipv4-address as-number as-number
[PE-bgp] peer ipv4-address connect-interface LoopBack interface-number
[PE-bgp] ipv4-family vpnv4 [ unicast ]
[PE-bgp-af-vpnv4] peer ipv4-address enable
[PE-bgp-af-vpnv4] policy vpn-target
```

PE 之间建议用 /32 Loopback 建 MP-IBGP 以便迭代到隧道。非 IPv4 单播地址族需手动 enable。`policy vpn-target` 缺省已使能。

### PE–CE 路由

EBGP：

```cli
[PE-bgp] ipv4-family vpn-instance vpn-instance-name
[PE-bgp-InstanceName] peer ipv4-address as-number as-number
```

OSPF：

```cli
[PE] ospf process-id [ router-id router-id ] vpn-instance vpn-instance-name
[PE-ospf-processid] import-route bgp [ permit-ibgp ] ...
[PE-bgp] ipv4-family vpn-instance vpn-instance-name
[PE-bgp] import-route ospf process-id ...
```

## 3. 配置示例

客户 X/Y 各两站点，经 MPLS VPN 互联；X 与 PE 用 OSPF，Y 与 PE 用 BGP。

配置思路：

1. 骨干：IGP → MPLS/LDP → MP-BGP  
2. 用户接入：建 VPN 实例（RD/RT）→ 接口绑定 → PE–CE 路由  

数据规划示例（PE1/PE2 的 VPNX/VPNY RD 与 IRT/ERT 交叉匹配）。

骨干 OSPF（PE1）：

```cli
[PE1] ospf 100 router-id 1.1.1.1
[PE1-ospf-100] area 0
[PE1-ospf-100-area-0.0.0.0] network 10.0.12.1 0.0.0.0
[PE1-ospf-100-area-0.0.0.0] network 1.1.1.1 0.0.0.0
```

MPLS/LDP（PE1）：

```cli
[PE1] mpls lsr-id 1.1.1.1
[PE1] mpls
[PE1-mpls] mpls ldp
[PE1] interface GigabitEthernet 0/0/0
[PE1-GigabitEthernet0/0/0] mpls
[PE1-GigabitEthernet0/0/0] mpls ldp
```

验证：`display mpls lsp`；`display bgp vpnv4 all peer`。

VPN 实例（PE1）：

```cli
[PE1] ip vpn-instance VPNX
[PE1-vpn-instance-VPNX] route-distinguisher 100:1
[PE1-vpn-instance-VPNX-af-ipv4] vpn-target 100:321 import-extcommunity
[PE1-vpn-instance-VPNX-af-ipv4] vpn-target 100:123 export-extcommunity
[PE1] ip vpn-instance VPNY
[PE1-vpn-instance-VPNY] route-distinguisher 200:1
[PE1-vpn-instance-VPNY-af-ipv4] vpn-target 200:234 import-extcommunity
[PE1-vpn-instance-VPNY-af-ipv4] vpn-target 200:432 export-extcommunity
```

接口绑定后重配 IP；再建与实例绑定的 OSPF/BGP 与 CE 交互。

## 4. 本章总结

- MPLS VPN 隔离不同客户路由与数据
- 控制面：VRF+RD 唯一化 VPNv4；RT 控制收发；MP-BGP 传递前缀/标签/RT；LDP 等建公网 LSP
- 转发面：内层区分私网，外层穿通公网

---

## 5. MPLS VPN 部署与应用开篇

下一主题覆盖 Intranet/Extranet/Hub-Spoke、跨域，以及 OSPF VPN 扩展（Domain ID、DN 位、Route Tag、Sham link）等。（详见下一章。）
